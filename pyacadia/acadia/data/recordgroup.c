#include "recordgroup.h"
#include "io.h"

// #define ACADIA_DEBUG

static unsigned char numpy_initialized = 0;

#ifdef ACADIA_DEBUG
extern FILE* acadia_log;
#endif

// Read a header from a stream
// Header must be pre-allocated
static int read_header(int fd, char* header, size_t* header_size, size_t* record_data_size, int timeout_ms)
{
    size_t ndim;
    size_t* dims;
    PyArray_Descr* descr;
    int retval;

    // Read the first four bytes so that we can figure out what kind of data it is the data
    if(timeout_ms == 0)
    {
        // It's a file
        retval = read(fd, header, 4);
        if(retval == -1)
        {
            PyErr_Format(PyExc_ValueError, "Read error when retrieiving header type: %s", strerror(errno));
            return -1;
        }
    }
    else
    {
        retval = read_polled(fd, header, 4, timeout_ms);
        if(retval == -1)
        {
            return -1;
        }
    }

    if(*header == 78 && *(header + 1) == 80)
    {
        // Numpy array
        descr = PyArray_DescrFromType((int)*(header + 2));    
        ndim = (size_t)*(header + 3); // read ndim as a byte and cast to size_t
        dims = (size_t*)(header + 4);

        // Read all the dimensions from the file
        if(timeout_ms == 0)
        {
            retval = read(fd, header + 4, sizeof(size_t)*ndim);
            if(retval == -1)
            {
                PyErr_Format(PyExc_ValueError, "Read error when retrieiving numpy array dimensions: %s", strerror(errno));
                return -1;
            }
        }
        else
        {
            retval = read_polled(fd, header + 4, sizeof(size_t)*ndim, timeout_ms);
            if(retval == -1)
            {
                return -1;
            }
        }
        
        *header_size = 4 + sizeof(size_t)*ndim;
        *record_data_size = (descr->elsize)*PyArray_MultiplyList((npy_intp*)dims, ndim);
    }
    else if(*header == 80 && *(header + 1) == 89)
    {
        // pickled object
        *header_size = 4 + sizeof(size_t);
        if(timeout_ms == 0)
        {
            retval = read(fd, header + 4, sizeof(size_t));
            if(retval == -1)
            {
                PyErr_Format(PyExc_ValueError, "Read error when retrieiving header type: %s", strerror(errno));
                return -1;
            }
        }
        else
        {
            retval = read_polled(fd, header + 4, sizeof(size_t), timeout_ms);
            if(retval == -1)
            {
                return -1;
            }
        }
    
        *record_data_size = *(size_t*)(header + 4);
    }
    else
    {
        PyErr_Format(PyExc_ValueError, 
            "Unable to parse record header when loading new record (found 0x%X, 0x%X)", 
            *(header),
            *(header + 1));
        return -1;
    }

    return 0;
}

// Expand the internal record memory and array of record offsets to add num_records records each of size record_size
static void* expand_record_memory(RecordGroup* self, size_t record_size, size_t num_records, unsigned char clear)
{
    void* ptr;
    size_t new_memory_size;
    size_t idx;

    if(clear)
    {
        new_memory_size = record_size*num_records;
        self->record_memory_size = 0;
        self->num_records = 0;
    }
    else
    {
        new_memory_size = self->record_memory_size + record_size*num_records;
    }

    self->record_memory = realloc(self->record_memory, new_memory_size);
    if(self->record_memory == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Failed resizing memory to %zu bytes: %s", new_memory_size, strerror(errno));
        return NULL;
    }

    self->record_offsets = realloc(self->record_offsets, sizeof(size_t)*(self->num_records + num_records));
    if(self->record_offsets == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Failed resizing memory offsets for %zu records: %s", num_records, strerror(errno));
        return NULL;
    }

    ptr = self->record_memory + self->record_memory_size;
    for(idx = 0; idx < num_records; idx++)
    {
        self->record_offsets[self->num_records + idx] = self->record_memory_size + idx*record_size;
    }
    
    self->record_memory_size = new_memory_size;

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "Expanded record memory for %zu records of size %zu (clear=%d)\n", num_records, record_size, clear);
    fflush(acadia_log);
    #endif

    return ptr;
}

// Initialize the record group 
int RecordGroup_init(RecordGroup* self)
{
    // Defaults for internal flags
    self->num_records = 0;
    self->uniform = 0;
    self->flags = 0;

    self->record_memory = NULL;
    self->record_offsets = NULL;
    self->record_memory_size = 0;
    
    if(!numpy_initialized)
    {
        if(_import_array() < 0)
        {
            return -1;
        }

        numpy_initialized = 1;
    }

    return 0;
}

void RecordGroup_free(RecordGroup* self)
{
    free(self->record_memory);
    free(self->record_offsets);
    self->num_records = 0;
}

// Write a record into the group
// If clear != 0, the group will be cleared before writing to it
int RecordGroup_write(RecordGroup* self, PyObject* record, unsigned char clear)
{
    char ndim;
    char dim;
    char* record_data;
    size_t record_data_size;
    char* internal_record;
    PyObject* pickle = NULL;
    PyObject* pickled_data = NULL;
    PyObject* method_name = NULL;
    volatile unsigned long long* chunk_data_ptr;
    size_t copy_size;
    size_t idx;

    if(record == NULL)
    {
        PyErr_SetString(PyExc_ValueError, "Cannot write null record");
        return -1;
    }

    if(self == NULL)
    {
        PyErr_SetString(PyExc_ValueError, "Cannot write into null record group");
        return -1;
    }

    if(PyArray_Check(record))
    {
        ndim = PyArray_NDIM((PyArrayObject*)record);
        record_data = (char*)PyArray_DATA((PyArrayObject*)record);
        record_data_size = PyArray_NBYTES((PyArrayObject*)record);

        if(self->num_records == 0 || !(self->uniform) || clear)
        {
            // Store the record and header
            // header format for numpy arrays: 
            //    78, 80, type_char as uint8, ndim as uint8
            //    each dim as uint32
            
            // Get memory for header and the record            
            internal_record = expand_record_memory(self, 4 + sizeof(size_t)*ndim + record_data_size, 1, clear);
            if(internal_record == NULL)
            {
                return -1; // Exception set inside
            }

            // write the header
            *internal_record = 78;
            internal_record++;
            *internal_record = 80;
            internal_record++;
            *internal_record = (char)PyArray_TYPE((PyArrayObject*)record);
            internal_record++;
            *internal_record = (char)PyArray_NDIM((PyArrayObject*)record);
            internal_record++;

            for(dim = 0; dim < ndim; dim++)
            {
                *((size_t*)internal_record) = PyArray_DIM((PyArrayObject*)record, (size_t)dim);
                internal_record += sizeof(size_t);
            }
        }
        else
        {
            // It's a uniform record, it isn't the first, and we're not clearing
            // Therefore, no header needed; just get enough space for the record data
            internal_record = expand_record_memory(self, record_data_size, 1, clear);
            if(internal_record == NULL)
            {
                return -1; // Exception set inside
            }
        }
    }
    else
    {
        // It's an arbitrary python object, pickle it
        // uniformity doesn't apply here, throw an error
        if(self->uniform)
        {
            PyErr_SetString(PyExc_TypeError, "Cannot write an arbitrary object to a uniform RecordGroup");
            return -1;
        }

        // header format for pickled objects: 
        //    Full size of the record in bytes, including the header (and this number)
        //    80, 89, 0, 0
        //    record size in bytes as size_t
        pickle = PyImport_ImportModule("pickle");
        method_name = PyUnicode_FromString("dumps");
        pickled_data = PyObject_CallMethodOneArg(pickle, method_name, record);
        Py_DECREF(method_name);
        Py_DECREF(pickle);

        record_data_size = (int)PyBytes_Size(pickled_data);
        if(record_data_size < 0)
        {
            Py_XDECREF(pickled_data);
            PyErr_SetString(PyExc_ValueError, "Failed retrieving pickled data size");
            return -1;
        }

        internal_record = expand_record_memory(self, 4 + sizeof(size_t) + record_data_size, 1, clear);
        if(internal_record == NULL)
        {
            return -1; // Exception set inside
        }

        *internal_record = 80;
        internal_record++;
        *internal_record = 89;
        internal_record++;
        *internal_record = 0;
        internal_record++;
        *internal_record = 0;
        internal_record++;
        *(size_t*)internal_record = record_data_size;
        internal_record += sizeof(size_t);

        record_data = (char*)PyBytes_AS_STRING(pickled_data);
    }

    // ARM64 memcpy has a weird bug when copying data with nonstandard caching (see https://support.xilinx.com/s/question/0D52E00007CfAiMSAV/set-reserved-memory-so-that-memcpy-does-not-bus-error?language=en_US)
    // Therefore, we'll make our own loop to do the copy
    // We'll copy as much as we can using 64-bit values, since these copies will be
    // most efficient for the kernel to burst
    chunk_data_ptr = (volatile unsigned long long*)record_data;
    copy_size = record_data_size / sizeof(unsigned long long);
    for(idx = 0; idx < copy_size; idx++)
    {
        *(((unsigned long long*)internal_record) + idx) = *(chunk_data_ptr + idx);
    }

    for(idx = copy_size*sizeof(unsigned long long); idx < record_data_size; idx++)
    {
        *(((char*)internal_record) + idx) = *(((volatile char*)chunk_data_ptr) + idx);
    }

    Py_XDECREF(pickled_data);
    self->num_records++;
    return 0;
}

// Retrieve a record from the group
PyObject* RecordGroup_read(RecordGroup* self, size_t record_idx)
{ 
    char* header;
    void* record_data;
    size_t record_data_size;
    size_t ndim;
    size_t* dims;
    PyArray_Descr* descr; 
    PyObject* pickle;
    PyObject* pickled_data;
    PyObject* unpickled_data;
    PyObject* method_name;
    PyObject* array_object;

    header = self->record_memory + (self->uniform ? 0 : self->record_offsets[record_idx]);

    if(*header == 78 && *(header + 1) == 80)
    {
        // Numpy array
        ndim = (size_t)*(header + 3);
        dims = (size_t*)(header + 4);
        descr = PyArray_DescrFromType((int)*(header + 2));  

        // If the data is uniform, we need to get the actual address of the data, since the header
        // will be that of the first record
        // This also means that if we're trying to read the first record, we need to jump past the header
        if(self->uniform)
        {
            if(record_idx == 0)
            {
                record_data = self->record_memory + 4 + ndim*sizeof(size_t);
            }
            else
            {
                record_data = self->record_memory + self->record_offsets[record_idx];
            }   
        }
        else
        {
            record_data = header + 4 + ndim*sizeof(size_t);
        }
        
        array_object = PyArray_NewFromDescr(&PyArray_Type, descr, ndim, (npy_intp*)dims, NULL, record_data, 0, NULL);
        return PyArray_Return((PyArrayObject*)array_object);
    }
    else if(*header == 80 && *(header + 1) == 89)
    {
        // pickled object
        record_data_size = *(size_t*)(header + 4);
        record_data = header + 4 + sizeof(size_t);
        pickle = PyImport_ImportModule("pickle");
        pickled_data = PyMemoryView_FromMemory(record_data, record_data_size, PyBUF_READ);
        method_name = PyUnicode_FromString("loads");
        unpickled_data = PyObject_CallMethodOneArg(pickle, method_name, pickled_data);
        Py_XDECREF(method_name);
        Py_XDECREF(pickle);
        Py_XDECREF(pickled_data);
        return unpickled_data;
    }
    
    return PyErr_Format(PyExc_ValueError, "Unexpected error retrieving record index %zu", record_idx);
}

// Retrieve all records from the group
// If the data is uniform, it's wrapped in a numpy array
// Otherwise, a list is made containing all the records
PyObject* RecordGroup_records(RecordGroup* self)
{ 
    char* header;
    void* record_data;
    size_t record_data_size;
    size_t ndim;
    size_t* dims;
    PyArray_Descr* descr; 
    PyObject* pickle = NULL;
    PyObject* pickled_data;
    PyObject* method_name = NULL;
    PyObject* obj;
    PyObject* list;
    size_t idx;

    if(self->uniform)
    {
        // Data is uniform and contiguous
        ndim = (size_t)*(self->record_memory + 3);
        dims = (size_t*)malloc((ndim+1)*sizeof(size_t));
        if(dims == NULL)
        {
            PyErr_Format(PyExc_MemoryError, "Failed to allocate memory for dims when wrapping records in numpy array: %s", strerror(errno));
            return NULL;
        }

        dims[0] = self->num_records;
        memcpy(dims+1, self->record_memory + 4, ndim*sizeof(size_t));
        descr = PyArray_DescrFromType((int)*(self->record_memory + 2));        
        return PyArray_NewFromDescr(&PyArray_Type, descr, ndim+1, (npy_intp*)dims, NULL, self->record_memory + 4 + ndim*sizeof(size_t), 0, NULL);
    }

    list = PyList_New((Py_ssize_t)self->num_records);
    for(idx = 0; idx < self->num_records; idx++)
    {
        header = self->record_memory + self->record_offsets[idx];
        if(*header == 78 && *(header + 1) == 80)
        {
            // Numpy array
            ndim = (size_t)*(header + 3);
            dims = (size_t*)(header + 4);
            descr = PyArray_DescrFromType((int)*(header + 2));  
            record_data = header + 4 + ndim*sizeof(size_t);
            obj = PyArray_NewFromDescr(&PyArray_Type, descr, ndim, (npy_intp*)dims, NULL, record_data, 0, NULL);
            PyList_SET_ITEM(list, (Py_ssize_t)idx, obj);
        }
        else if(*header == 80 && *(header + 1) == 89)
        {
            // pickled object
            if(pickle == NULL)
            {
                pickle = PyImport_ImportModule("pickle");
                method_name = PyUnicode_FromString("loads");
            }

            record_data_size = *(size_t*)(header + 4);
            record_data = header + 4 + sizeof(size_t);
            pickled_data = PyMemoryView_FromMemory(record_data, record_data_size, PyBUF_READ);
            obj = PyObject_CallMethodOneArg(pickle, method_name, pickled_data);
            Py_XDECREF(pickled_data);
            PyList_SET_ITEM(list, (Py_ssize_t)idx, obj);
        }
        else
        {
            PyErr_Format(PyExc_ValueError, "Unexpected error processing header for record %zu", idx);
            return NULL;
        }
    }
    
    Py_XDECREF(method_name);
    Py_XDECREF(pickle);
    
    return list;
}

void RecordGroup_clear(RecordGroup* self)
{
    free(self->record_memory);
    self->record_memory = NULL;
    free(self->record_offsets);
    self->record_offsets = NULL;
    self->record_memory_size = 0;
    self->num_records = 0;
}

// Write internally-cached records to a file or socket and clear the cache
// It is assumed that the metadata has been sent or stored separately, so the
// receiver should know how many records to expect
int RecordGroup_save(RecordGroup* self, int fd)
{
    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "recordgroup_save saving %zu bytes\n", self->record_memory_size);
    fflush(acadia_log);
    #endif

    if(write(fd, self->record_memory, self->record_memory_size) != (ssize_t)self->record_memory_size)
    {
        PyErr_Format(PyExc_ValueError, "Failed to write %zu record data bytes: %s", self->record_memory_size, strerror(errno));
        return -1;
    }

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "recordgroup_save saved successfully\n");
    fflush(acadia_log);
    #endif

    return 0;
}


// Load records from binary record data. 
// The first record in the file must have a header. If we already have records and know
// that they're uniform, this header is discarded
// The metadata will have been loaded previously, so we know how many records to consume from the file
// The sizes of the individual records are determined from the header(s)
// Returns -1 on error, otherwise 0
int RecordGroup_load(RecordGroup* self, int fd, size_t num_records, int timeout_ms)
{
    char* header;
    size_t header_size;
    size_t idx;
    char* record_data_destination;
    size_t record_data_size;
    int retval;

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "recordgroup_load entered\n");
    fflush(acadia_log);
    #endif

    // There can't be more than 255 dimensions in a numpy array and the 
    // pickled object header is always 8 bytes, so allocate enough data to store
    // the biggest possible header
    header = (char*)malloc(4 + 255*sizeof(size_t));
    if(header == NULL)
    {
        PyErr_Format(PyExc_MemoryError, 
            "Failed to allocate %zu bytes for reading headers",
            4 + 255*sizeof(size_t));
        return -1;
    }

    // Now we can decide how we want to allocate memory
    if(self->uniform)
    {
        // For uniform records, all of the records loaded in a single load() call
        // must be contiguous. Therefore, determine how we want to allocate memory
        // depending on whether or not we already have records
        // The data will always start with a header. Use this to allocate a new cache chunk
        // so that all of the loaded data is contiguous
        retval = read_header(fd, header, &header_size, &record_data_size, timeout_ms);
        if(retval == -1)
        {
            // Exception set inside
            return -1;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "recordgroup_load read header for uniform records of size %zu\n", record_data_size);
        fflush(acadia_log);
        #endif

        // For uniform groups with no records, write in the header
        if(self->num_records == 0)
        {
            self->record_memory = realloc(self->record_memory, header_size);
            if(self->record_memory == NULL)
            {
                PyErr_Format(PyExc_MemoryError, 
                    "Failed to allocate %zu bytes for loading %zu uniform records: %s", 
                    header_size + num_records*record_data_size,
                    num_records,
                    strerror(errno));
                free(header);
                return -1;
            }

            memcpy(self->record_memory, header, header_size);
            self->record_memory_size = header_size;
        }

        free(header);

        record_data_destination = expand_record_memory(self, record_data_size, num_records, 0);
        if(record_data_destination == NULL)
        {
            return -1;
        }

        // If we had written in the header before, the record memory array will
        // not have started with zero size, so rewind the pointer for the first record slightly
        // The returned value from expand_record_memory will point to the location just after 
        // the header for the first record
        if(self->num_records == 0)
        {
            self->record_offsets[0] -= header_size;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "recordgroup_load reading %zu bytes for uniform record\n", record_data_size*num_records);
        fflush(acadia_log);
        #endif
        
        // Load in the actual record data
        retval = read_polled(fd, record_data_destination, record_data_size*num_records, timeout_ms);
        if(retval == -2)
        {
            PyErr_Format(PyExc_ValueError, "Timed out waiting for %zu records", num_records);
            return -1;
        }
        if(retval == -1)
        {
            // Exception set inside
            return -1;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "recordgroup_load read successfully\n");
        fflush(acadia_log);
        #endif

        self->num_records += num_records;

        return 0;
    }

    // We have non-uniform data. We need to request cache and a header for each record
    for(idx = 0; idx < num_records; idx++)
    {
        retval = read_header(fd, header, &header_size, &record_data_size, timeout_ms);
        if(retval == -1)
        {
            // Exception set inside
            return -1;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "recordgroup_load read header for non-uniform record of size %zu\n", record_data_size);
        fflush(acadia_log);
        #endif

        // Allocate memory for both the record and its header
        record_data_destination = expand_record_memory(self, header_size + record_data_size, 1, 0);
        if(record_data_destination == NULL)
        {
            return -1;
        }

        memcpy(record_data_destination, header, header_size);

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "recordgroup_load reading %zu bytes for non-uniform record\n", record_data_size);
        fflush(acadia_log);
        #endif

        // Finally, read the record data in
        retval = read_polled(fd, record_data_destination + header_size, record_data_size, timeout_ms);
        if(retval == -2)
        {
            PyErr_Format(PyExc_ValueError, 
                    "Timeout occurred reading %zu bytes when loading new record %zu", 
                    record_data_size,
                    idx);
            free(header);
            return -1;
        }
        if(retval == -1)
        {
            // Error set in read_polled
            free(header);
            return -1;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "recordgroup_load read successfully\n");
        fflush(acadia_log);
        #endif

        self->num_records++;
    }

    free(header);
    return 0;
}
