#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <structmember.h>

#include "datamanager.h"
#include "recordgroup.h"

typedef struct {
    PyObject_HEAD
    RecordGroup* rg;
    unsigned char borrowed;
} RecordGroupObject;

// ------------------- RecordGroup Python API ----------------------- //

static const char RECORDGROUP_INIT_DOCSTRING[] = "Create and initialize a RecordGroup.\n\n"
    ":param uniform: When the records will have identical size, setting this will improve the storage efficiency. Note that no bounds checking is performed, so only set this if you are confident that records will be of identical size.\n"
    ":type uniform: bool\n"
    ":param cache_chunk_size: Pre-allocates this much memory for records\n"
    ":type cache_size: int";
static int PyRecordGroup_init(PyObject* self, PyObject* args, PyObject* kwargs)
{
    // Update defaults from arguments
    RecordGroup* self_rg;
    static char* kwlist[] = {"uniform", NULL};
    
    self_rg = (RecordGroup*)malloc(sizeof(RecordGroup));
    if(self_rg == NULL)
    {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate memory for RecordGroup");
    }
    
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "|p", kwlist, &(self_rg->uniform)))
    {
        return -1;
    }

    ((RecordGroupObject*)self)->rg = self_rg;
    ((RecordGroupObject*)self)->borrowed = 0;
    return RecordGroup_init(self_rg);
}

static void PyRecordGroup_dealloc(PyObject* self)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    if(!(((RecordGroupObject*)self)->borrowed))
    {
        RecordGroup_free(self_rg);
        free(self_rg);
    }
    
    Py_TYPE(self)->tp_free(self);
}

static const char RECORDGROUP_WRITE_DOCSTRING[] = "Write a record into the record group."
    " Note that when this group was initialized with `uniform=True`,"
    " bounds checking is not performed; it is the responsibility of"
    " the caller to ensure that the provided record is indeed uniform.\n\n"
    ":param record: Record to write\n"
    ":type record: object";
static PyObject* PyRecordGroup_write(PyObject* self, PyObject* args, PyObject* kwargs)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    static char* kwlist[] = {"record", "clear", NULL};
    PyObject* record;
    int clear = 0;
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "O|p", kwlist, &record, &clear))
    {
        PyErr_Format(PyExc_ValueError, "Failed parsing arguments in RecordGroup.write()");
        return NULL;
    }

    if(RecordGroup_write(self_rg, record, (unsigned char)clear) != 0)
    {
        // Exception set in RecordGroup_write
        return NULL;
    }

    Py_RETURN_NONE;
}

static const char RECORDGROUP_READ_DOCSTRING[] = "Read a record from the record group.\n\n"
    ":param record_num: Record number to retrieve\n"
    ":type record_num: int";
static PyObject* PyRecordGroup_read(PyObject* self, PyObject* index)
{
    size_t record_num;
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    if(!PyLong_Check(index))
    {
        PyErr_SetString(PyExc_ValueError, "Record index provided to RecordGroup.read() cannot be converted into an integer.");
        return NULL;
    }

    record_num = PyLong_AsSize_t(index);
    return RecordGroup_read(self_rg, record_num);
}

static const char RECORDGROUP_SAVE_DOCSTRING[] = "Save record data to a file or socket.\n\n"
    ":param file_descriptor: File descriptor to save records into\n"
    ":type file_descriptor: int";
static PyObject* PyRecordGroup_save(PyObject* self, PyObject* fd)
{
    int file_descriptor;
    int retval;
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    
    if(!PyLong_Check(fd))
    {
        PyErr_SetString(PyExc_ValueError, "File descriptor provided to RecordGroup.save() cannot be converted into an integer.");
        return NULL;
    }

    file_descriptor = (int)PyLong_AsLong(fd);
    retval = RecordGroup_save(self_rg, file_descriptor);
    if(retval != 0)
    {
        // Exception set in RecordGroup_save
        return NULL;
    }

    Py_RETURN_NONE;
}

static const char RECORDGROUP_LOAD_DOCSTRING[] = "Load record data from a file or socket and internally update stored records.\n\n"
    ":param file_descriptor: File descriptor to load records from\n"
    ":type file_descriptor: int\n"
    ":param num_records: Number of records to load\n"
    ":type num_records: int\n"
    ":param timeout_ms: Timeout for the file read operation\n"
    ":type timeout_ms: int";
static PyObject* PyRecordGroup_load(PyObject* self, PyObject* args, PyObject* kwargs)
{
    int file_descriptor;
    size_t num_records;
    int timeout_ms = 1000;
    int retval;
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    
    static char* kwlist[] = {"file_descriptor", "num_records", "timeout_ms", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "ik|i", kwlist, &file_descriptor, &num_records, &timeout_ms))
    {
        PyErr_SetString(PyExc_ValueError, "Failed parsing arguments for RecordGroup.load()");
        return NULL;
    }

    retval = RecordGroup_load(self_rg, file_descriptor, num_records, timeout_ms);
    if(retval != 0)
    {
        // Exception set in RecordGroup_flush
        return NULL;
    }

    Py_RETURN_NONE;
}

static PyObject* PyRecordGroup_clear(PyObject* self)
{
    RecordGroup_clear(((RecordGroupObject*)self)->rg);
    Py_RETURN_NONE;
}

static const char RECORDGROUP_RECORDS_DOCSTRING[] = "Read bulk record data from the group."
    "If the group contains uniform data, the full set of records is wrapped in a numpy array"
    " and returned. Otherwise, a list of all records is returned.";
static PyObject* PyRecordGroup_records(PyObject* self)
{
    return RecordGroup_records(((RecordGroupObject*)self)->rg);
}

static PyObject* PyRecordGroup_is_finalized(PyObject* self)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    if(self_rg->flags & GROUP_FLAG_FINALIZED)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;
}

static PyObject* PyRecordGroup_is_uniform(PyObject* self)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    if(self_rg->uniform)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;
}

static PyObject* PyRecordGroup_clear_before_load(PyObject* self)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    if(self_rg->flags & GROUP_FLAG_CLEAR_BEFORE_LOAD)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;
}

static PyObject* PyRecordGroup_clear_before_sync(PyObject* self)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    if(self_rg->flags & GROUP_FLAG_CLEAR_BEFORE_SYNC)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;
}

static PyObject* PyRecordGroup_clear_after_save(PyObject* self)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    if(self_rg->flags & GROUP_FLAG_CLEAR_AFTER_SAVE)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;
}

static PyObject* PyRecordGroup_clear_after_send(PyObject* self)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    if(self_rg->flags & GROUP_FLAG_CLEAR_AFTER_SEND)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;
}

static Py_ssize_t PyRecordGroup_length(PyObject* self)
{
    RecordGroup* self_rg = ((RecordGroupObject*)self)->rg;
    return (Py_ssize_t)(self_rg->num_records);
}

static PyMemberDef RecordGroupMembers[] = {
    {"num_records", T_ULONG, offsetof(RecordGroupObject, rg) + offsetof(RecordGroup, num_records), 0},
    {NULL}
};

static PyMethodDef RecordGroupMethods[] = {
    {"write", (PyCFunction)PyRecordGroup_write, METH_VARARGS | METH_KEYWORDS, RECORDGROUP_WRITE_DOCSTRING},
    {"read", (PyCFunction)PyRecordGroup_read, METH_O, RECORDGROUP_READ_DOCSTRING},
    {"save", (PyCFunction)PyRecordGroup_save, METH_O, RECORDGROUP_SAVE_DOCSTRING},
    {"load", (PyCFunction)PyRecordGroup_load, METH_VARARGS | METH_KEYWORDS, RECORDGROUP_LOAD_DOCSTRING},
    {"clear", (PyCFunction)PyRecordGroup_clear, METH_NOARGS, ""},
    {"records", (PyCFunction)PyRecordGroup_records, METH_NOARGS, RECORDGROUP_RECORDS_DOCSTRING},
    {"is_finalized", (PyCFunction)PyRecordGroup_is_finalized, METH_NOARGS, ""},
    {"is_uniform", (PyCFunction)PyRecordGroup_is_uniform, METH_NOARGS, ""},
    {"clear_before_sync", (PyCFunction)PyRecordGroup_clear_before_sync, METH_NOARGS, ""},
    {"clear_before_load", (PyCFunction)PyRecordGroup_clear_before_load, METH_NOARGS, ""},
    {"clear_after_save", (PyCFunction)PyRecordGroup_clear_after_save, METH_NOARGS, ""},
    {"clear_after_send", (PyCFunction)PyRecordGroup_clear_after_send, METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}
};

static PyMappingMethods RecordGroupMappingMethods = {
    .mp_length = PyRecordGroup_length,
    .mp_subscript = PyRecordGroup_read
};

static PyTypeObject RecordGroupTypeObject = {
    .ob_base = PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "acadia.data.RecordGroup",
    .tp_doc = PyDoc_STR(RECORDGROUP_INIT_DOCSTRING),
    .tp_basicsize = sizeof(RecordGroupObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
    .tp_as_mapping = &RecordGroupMappingMethods,
    .tp_members = RecordGroupMembers,
    .tp_methods = RecordGroupMethods,
    .tp_init = PyRecordGroup_init,
    .tp_dealloc = PyRecordGroup_dealloc
};

// ------------------ DataManager Python API -------------------------- //

typedef struct {
    PyObject_HEAD
    DataManager* dm;
} DataManagerObject;

static const char DATAMANAGER_DOCSTRING[] = "A series of caching and communication functions"
    " for organizing and transmitting collected data records stored in RecordGroup objects."
    " Record groups managed by a DataManager will call its notify() method when there are new records."
    " At this point, if the DataManager instance previously had its serve() method called and there's a"
    " client connected that has requested data, it will transmit records to the client."
    " Client DataManagers can request records from remote server DataManagers by first connecting to"
    " the server using the connect() method (which establishes a persistent TCP connection to the server),"
    " and then calling the client's sync() method anytime in the future to update its local records"
    " according to what the server provides.";

static int PyDataManager_init(PyObject* self, PyObject* args, PyObject* kwargs)
{
    DataManager* self_dm;
    self_dm = (DataManager*)malloc(sizeof(DataManager));
    if(self_dm == NULL)
    {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate memory for DataManager");
        return -1;
    }

    ((DataManagerObject*)self)->dm = self_dm;
    DataManager_init(self_dm, 32768);
    return 0;
}

static void PyDataManager_dealloc(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    DataManager_free(self_dm);
    free(self_dm);
}

static const char DATAMANAGER_SERVE_DOCSTRING[] = "Create and/or update a server in this DataManager to which"
    " other client DataManagers may connect for synchronization. If the server has"
    " already been created, check for any client requests and respond accordingly.\n\n"
    ":return: 0 if data was successfully sent to a connected client,"
    " 1 if there's no client, 2 if there's a client but they didn't request anything, 3 if the client requested a hangup";
static PyObject* PyDataManager_serve(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    int retval;
    retval = DataManager_serve(self_dm, 2000);
    if(retval == -1)
    {
        // Error set inside
        return NULL;
    }

    return PyLong_FromLong(retval);
}

static const char DATAMANAGER_CONNECT_DOCSTRING[] = "Connect the DataManager to another DataManager in server mode.\n\n"
    ":param server_address: IP address of the server\n"
    ":type server_address: str";
static PyObject* PyDataManager_connect(PyObject* self, PyObject* args, PyObject* kwargs)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    char* server_address;
    size_t attempt_limit = 5000;
    size_t attempt_delay = 1000;
    static char* kwlist[] = {"server_address", "attempt_limit", "attempt_delay", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "s|II", kwlist, &server_address, &attempt_limit, &attempt_delay))
    {
        PyErr_SetString(PyExc_ValueError, "Unable to parse arguments in DataManager.connect");
        return NULL;
    }

    if(DataManager_connect(self_dm, server_address, attempt_limit, attempt_delay) == -1)
    {
        return NULL;
    }

    Py_RETURN_NONE;
}

static const char DATAMANAGER_DISCONNECT_DOCSTRING[] = "Disconnect client DataManagers from their servers"
    " and stop hosting servers.";
static PyObject* PyDataManager_disconnect(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    DataManager_disconnect(self_dm);
    Py_RETURN_NONE;
}

static const char DATAMANAGER_ADD_GROUP_DOCSTRING[] = "Add a new group to the DataManager.";
static PyObject* PyDataManager_add_group(PyObject* self, PyObject* args, PyObject* kwargs)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    RecordGroup* rg;
    RecordGroupObject* rg_obj;
    char* name;
    char* name_copied;
    unsigned char uniform = 0;
    unsigned char clear_before_sync = 0;
    unsigned char clear_before_load = 1;
    unsigned char clear_after_save = 0;
    unsigned char clear_after_send = 1;

    static char* kwlist[] = {"name", "uniform", "clear_before_sync", "clear_before_load", "clear_after_save", "clear_after_send", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "s|bbbbb", kwlist, 
        &name, &uniform, &clear_before_sync, &clear_before_load, &clear_after_save, &clear_after_send))
    {
        PyErr_SetString(PyExc_ValueError, "Failed parsing arguments in DataManager.add_group");
        return NULL;
    }

    name_copied = (char*)malloc(strlen(name) + 1);
    if(name_copied == NULL)
    {
        PyErr_SetString(PyExc_MemoryError, "Failed allocating memory for group name");
        return NULL;
    }

    strcpy(name_copied, name);

    // Make a new record group
    rg = DataManager_add_group(self_dm, name_copied);
    if(rg == NULL)
    {
        // Error set inside
        return NULL;
    }

    rg->uniform = uniform;
    rg->flags = 0;
    if(clear_before_sync)
    {
        rg->flags |= GROUP_FLAG_CLEAR_BEFORE_SYNC;
    }

    if(clear_before_load)
    {
        rg->flags |= GROUP_FLAG_CLEAR_BEFORE_LOAD;
    }
    
    if(clear_after_send)
    {
        rg->flags |= GROUP_FLAG_CLEAR_AFTER_SEND;
    }

    if(clear_after_save)
    {
        rg->flags |= GROUP_FLAG_CLEAR_AFTER_SAVE;
    }

    // Make a new RecordGroupObject that points to the record group that we created
    rg_obj = (RecordGroupObject*)PyType_GenericNew(&RecordGroupTypeObject, NULL, NULL);
    rg_obj->rg = rg;
    rg_obj->borrowed = 1;
    return (PyObject*)rg_obj;
}

static const char DATAMANAGER_LOAD_DOCSTRING[] = "Load data from the DataManager's directory."
    " The DataManager will be populated according to the metadata, which will"
    " be loaded from a file named `metadata.txt` in the DataManager's directory."
    " This should only be called by DataManagers that are not servers.";
static PyObject* PyDataManager_load(PyObject* self, PyObject* directory)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    char* directory_c;
    PyObject* directory_bytes;

    if(!PyUnicode_Check(directory))
    {
        PyErr_SetString(PyExc_TypeError, "Load location must be a string representing a directory path");
        return NULL;
    }

    directory_bytes = PyUnicode_AsASCIIString(directory);
    directory_c = PyBytes_AsString(directory_bytes);
    DataManager_load(self_dm, directory_c);
    Py_DECREF(directory_bytes);
    Py_RETURN_NONE;
}

static const char DATAMANAGER_SAVE_DOCSTRING[] = "";
static PyObject* PyDataManager_save(PyObject* self, PyObject* directory)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    char* directory_c;
    PyObject* directory_bytes;

    // If no directory was provided, the C library will get the current directory
    if(Py_IsNone(directory))
    {
        if(DataManager_save(self_dm, NULL) == -1)
        {
            return NULL;
        }
        Py_RETURN_NONE;
    }

    if(!PyUnicode_Check(directory))
    {
        PyErr_SetString(PyExc_TypeError, "Save location must be a string representing a directory path");
        return NULL;
    }

    directory_bytes = PyUnicode_AsASCIIString(directory);
    directory_c = PyBytes_AsString(directory_bytes);
    if(DataManager_save(self_dm, directory_c) == -1)
    {
        Py_DECREF(directory_bytes);
        return NULL;
    }
    
    Py_DECREF(directory_bytes);
    Py_RETURN_NONE;
}

static const char DATAMANAGER_SYNC_DOCSTRING[] = "Synchronize the DataManager with a remote server DataManager."
    " Retrieved metadata will be written to the file `metadata.txt` in the DataManager's directory"
    " and additional files will be written as necessary for storing record groups.";
static PyObject* PyDataManager_sync(PyObject* self, PyObject* args, PyObject* kwargs)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    size_t timeout_ms = 2000;
    static char* kwlist[] = {"timeout_ms", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "|I", kwlist, &timeout_ms))
    {
        PyErr_SetString(PyExc_ValueError, "Failed parsing arguments in DataManager.sync");
        return NULL;
    }

    if(DataManager_sync(self_dm, timeout_ms) == -1)
    {
        return NULL;
    }

    Py_RETURN_NONE;
}

static const char DATAMANAGER_FINALIZE_DOCSTRING[] = "Finalize all record groups in the DataManager.\n\n";

static PyObject* PyDataManager_finalize(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    DataManager_finalize(self_dm);
    Py_RETURN_NONE;
}

static PyObject* PyDataManager_hangup(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    if(DataManager_hangup(self_dm) == -1)
    {
        return NULL;
    }

    Py_RETURN_NONE;
}

static PyObject* PyDataManager_is_finalized(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    RecordGroup* group;
    size_t idx;

    for(idx = 0; idx < self_dm->num_groups; idx++)
    {
        group = self_dm->groups[idx];
        if(!(group->flags & GROUP_FLAG_FINALIZED))
        {
            Py_RETURN_FALSE;
        }
    }

    Py_RETURN_TRUE;
}

static PyObject* PyDataManager_is_connected(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    if(self_dm->connected)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;
}

static int PyDataManager_contains(PyObject* self, PyObject* value)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    char* name;
    PyObject* name_bytes;

    if(!PyUnicode_Check(value))
    {
        // Must index by string
        return 0;
    }

    name_bytes = PyUnicode_AsASCIIString(value);
    name = PyBytes_AsString(name_bytes);
    Py_DECREF(name_bytes);
    return DataManager_contains(self_dm, name);
}

static Py_ssize_t PyDataManager_length(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    return (Py_ssize_t)(self_dm->num_groups);
}

static PyObject* PyDataManager_getitem(PyObject* self, PyObject* key)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    char* name;
    PyObject* name_bytes;
    size_t unused;
    RecordGroup* rg;
    RecordGroupObject* rg_obj;

    if(!PyUnicode_Check(key))
    {
        PyErr_SetString(PyExc_TypeError, "Must retrieve RecordGroup from DataManager with string key");
        return NULL;
    }

    name_bytes = PyUnicode_AsASCIIString(key);
    name = PyBytes_AsString(name_bytes);

    rg = DataManager_get_group(self_dm, name, &unused);
    if(rg == NULL)
    {
        PyErr_Format(PyExc_KeyError, "Group %s not found", name);
        Py_DECREF(name_bytes);
        return NULL;
    }

    Py_DECREF(name_bytes);

    // Make a new RecordGroupObject that points to the record group that we created
    rg_obj = (RecordGroupObject*)PyType_GenericNew(&RecordGroupTypeObject, NULL, NULL);
    rg_obj->rg = rg;
    rg_obj->borrowed = 1;
    return (PyObject*)rg_obj;
}

static PyObject* PyDataManager_groups(PyObject* self)
{
    DataManager* self_dm = ((DataManagerObject*)self)->dm;
    PyObject* d;
    RecordGroupObject* rg_obj;
    size_t idx;

    d = PyDict_New();
    for(idx = 0; idx < self_dm->num_groups; idx++)
    {
        rg_obj = (RecordGroupObject*)PyType_GenericNew(&RecordGroupTypeObject, NULL, NULL);
        rg_obj->rg = self_dm->groups[idx];
        if(PyDict_SetItemString(d, self_dm->group_names[idx], (PyObject*)rg_obj))
        {
            PyErr_Format(PyExc_ValueError, "Failed to add group %s to dict", self_dm->group_names[idx]);
            return NULL;
        }
    }
    
    return d;
}

static PyObject* PyDataManager_serve_sent(PyObject* self) 
{
    return PyLong_FromLong(DATAMANAGER_SERVE_SENT);
}

static PyObject* PyDataManager_serve_no_client(PyObject* self) 
{
    return PyLong_FromLong(DATAMANAGER_SERVE_NO_CLIENT);
}

static PyObject* PyDataManager_serve_no_request(PyObject* self) 
{
    return PyLong_FromLong(DATAMANAGER_SERVE_NO_REQUEST);
}

static PyObject* PyDataManager_serve_hangup(PyObject* self) 
{
    return PyLong_FromLong(DATAMANAGER_SERVE_HANGUP);
}

static PyMemberDef PyDataManagerMembers[] = {
    {"num_groups", T_ULONG, offsetof(DataManagerObject, dm) + offsetof(DataManager, num_groups), 0},
    {NULL}
};

static PyMethodDef PyDataManagerMethods[] = {
    {"serve", (PyCFunction)PyDataManager_serve, METH_NOARGS, DATAMANAGER_SERVE_DOCSTRING},
    {"connect", (PyCFunction)PyDataManager_connect, METH_VARARGS | METH_KEYWORDS, DATAMANAGER_CONNECT_DOCSTRING},
    {"disconnect", (PyCFunction)PyDataManager_disconnect, METH_NOARGS, DATAMANAGER_DISCONNECT_DOCSTRING},
    {"add_group", (PyCFunction)PyDataManager_add_group, METH_VARARGS | METH_KEYWORDS, DATAMANAGER_ADD_GROUP_DOCSTRING},
    {"load", (PyCFunction)PyDataManager_load, METH_O, DATAMANAGER_LOAD_DOCSTRING},
    {"save", (PyCFunction)PyDataManager_save, METH_O, DATAMANAGER_SAVE_DOCSTRING},
    {"sync", (PyCFunction)PyDataManager_sync, METH_VARARGS | METH_KEYWORDS, DATAMANAGER_SYNC_DOCSTRING},
    {"finalize", (PyCFunction)PyDataManager_finalize, METH_NOARGS, DATAMANAGER_FINALIZE_DOCSTRING},
    {"hangup", (PyCFunction)PyDataManager_hangup, METH_NOARGS, ""},
    {"is_finalized", (PyCFunction)PyDataManager_is_finalized, METH_NOARGS, ""},
    {"is_connected", (PyCFunction)PyDataManager_is_connected, METH_NOARGS, ""},
    {"groups", (PyCFunction)PyDataManager_groups, METH_NOARGS, ""},
    {"serve_sent", (PyCFunction)PyDataManager_serve_sent, METH_STATIC | METH_NOARGS, ""},
    {"serve_no_client", (PyCFunction)PyDataManager_serve_no_client, METH_STATIC | METH_NOARGS, ""},
    {"serve_no_request", (PyCFunction)PyDataManager_serve_no_request, METH_STATIC | METH_NOARGS, ""},
    {"serve_hangup", (PyCFunction)PyDataManager_serve_hangup, METH_STATIC | METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}
};

static PyMappingMethods PyDataManagerMappingMethods = {
    .mp_length = PyDataManager_length,
    .mp_subscript = PyDataManager_getitem
};

static PySequenceMethods PyDataManagerSequenceMethods = {
    .sq_contains = PyDataManager_contains
};

static PyTypeObject DataManagerTypeObject = {
    .ob_base = PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "acadia.data.DataManager",
    .tp_doc = PyDoc_STR(DATAMANAGER_DOCSTRING),
    .tp_basicsize = sizeof(DataManagerObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
    .tp_init = PyDataManager_init,
    .tp_as_mapping = &PyDataManagerMappingMethods,
    .tp_as_sequence = &PyDataManagerSequenceMethods,
    .tp_members = PyDataManagerMembers,
    .tp_methods = PyDataManagerMethods,
    .tp_dealloc = PyDataManager_dealloc
};

static PyMethodDef DataMethods[] = {
  {NULL, NULL, 0, NULL}
};

static struct PyModuleDef data_module = {
    PyModuleDef_HEAD_INIT,
    "acadia.data",   /* name of module */
    NULL, /* module documentation, may be NULL */
    -1,       /* size of per-interpreter state of the module,
                 or -1 if the module keeps state in global variables. */
    DataMethods
};

PyMODINIT_FUNC
PyInit_data(void)
{
    PyObject *module;

    import_array();
    if(PyErr_Occurred())
    {
        return NULL;
    }

    if (PyType_Ready(&RecordGroupTypeObject) < 0)
    {
        return NULL;
    }

    if (PyType_Ready(&DataManagerTypeObject) < 0)
    {
        return NULL;
    }

    // Create the module
    module = PyModule_Create(&data_module);
    if (module == NULL) 
    {
        return NULL;
    }

    // Add RecordGroup
    Py_INCREF(&RecordGroupTypeObject);
    if (PyModule_AddObject(module, "RecordGroup", (PyObject*) &RecordGroupTypeObject) < 0) 
    {
        Py_DECREF(&RecordGroupTypeObject);
        Py_DECREF(module);
        return NULL;
    }

    // Add DataManager to the module
    Py_INCREF(&DataManagerTypeObject);
    if (PyModule_AddObject(module, "DataManager", (PyObject*) &DataManagerTypeObject) < 0) 
    {
        Py_DECREF(&RecordGroupTypeObject);
        Py_DECREF(&DataManagerTypeObject);
        Py_DECREF(module);
        return NULL;
    }

    // Add constants to the module
    if (PyModule_AddIntConstant(module, "SERVE_SENT", DATAMANAGER_SERVE_SENT) < 0) 
    {
        Py_DECREF(&RecordGroupTypeObject);
        Py_DECREF(&DataManagerTypeObject);
        Py_DECREF(module);
        return NULL;
    }

    if (PyModule_AddIntConstant(module, "SERVE_NO_CLIENT", DATAMANAGER_SERVE_NO_CLIENT) < 0) 
    {
        Py_DECREF(&RecordGroupTypeObject);
        Py_DECREF(&DataManagerTypeObject);
        Py_DECREF(module);
        return NULL;
    }

    if (PyModule_AddIntConstant(module, "SERVE_NO_REQUEST", DATAMANAGER_SERVE_NO_REQUEST) < 0) 
    {
        Py_DECREF(&RecordGroupTypeObject);
        Py_DECREF(&DataManagerTypeObject);
        Py_DECREF(module);
        return NULL;
    }

    if (PyModule_AddIntConstant(module, "SERVE_HANGUP", DATAMANAGER_SERVE_HANGUP) < 0) 
    {
        Py_DECREF(&RecordGroupTypeObject);
        Py_DECREF(&DataManagerTypeObject);
        Py_DECREF(module);
        return NULL;
    }
    
    return module;
}