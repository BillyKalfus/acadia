#ifndef _RECORD_GROUP_H
#define _RECORD_GROUP_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <unistd.h>
#include <fcntl.h>

#define NPY_NO_DEPRECATED_API NPY_1_7_API_VERSION
#include "numpy/arrayobject.h"

typedef struct {
    // Number of records in the group
    size_t num_records;

    // If 0, each record stored may have a unique format. Its binary data
    //     is preceded by a header. There is no guarantee about the memory
    //     placement of neighboring records
    // If 1, only the first record has a header and all remaining records
    //     follow it without headers. Loading a set of uniform records
    //     guarantees that the loaded set of records will be contiguous in
    //     memory, but records actively being written to a uniform record 
    //     group may not be placed contiguously.
    unsigned char uniform;

    // List of pointers to records
    char* record_memory;
    size_t* record_offsets; 
    size_t record_memory_size;

    // Arbitrary flags to be used by the DataManager
    unsigned char flags; 

} RecordGroup;

int RecordGroup_init(RecordGroup*);
void RecordGroup_free(RecordGroup*);
int RecordGroup_write(RecordGroup*, PyObject*, unsigned char);
PyObject* RecordGroup_read(RecordGroup*, size_t);
PyObject* RecordGroup_records(RecordGroup*);
void RecordGroup_clear(RecordGroup*);
int RecordGroup_save(RecordGroup*, int);
int RecordGroup_load(RecordGroup*, int, size_t, int);
int RecordGroup_record_info(RecordGroup*, size_t, char**, size_t*, void**, size_t*);

#endif
