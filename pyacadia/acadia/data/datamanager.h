#ifndef _DATA_MANAGER_H
#define _DATA_MANAGER_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <netinet/in.h> 
#include <arpa/inet.h> 
#include <sys/socket.h> 
#include <sys/types.h> 
#include <sys/ioctl.h> 
#include <unistd.h>
#include <fcntl.h>

#include "recordgroup.h"

#define DATAMANAGER_SERVER_PORT 6672
#define DATAMANAGER_SERVER_SYNC_KEY 0xBEEBBAAB
#define DATAMANAGER_SERVER_HANGUP_KEY 0xBB13D00D

// Group flags 
#define GROUP_FLAG_CLEAR_BEFORE_LOAD (1 << 1)
#define GROUP_FLAG_CLEAR_BEFORE_SYNC (1 << 2)
#define GROUP_FLAG_CLEAR_AFTER_SAVE (1 << 3)
#define GROUP_FLAG_CLEAR_AFTER_SEND (1 << 4)
#define GROUP_FLAG_FINALIZED (1 << 5)

typedef struct {
    // The total number of groups
    size_t num_groups;

    // The record groups themselves
    RecordGroup** groups;

    // The names of the groups as strings
    char** group_names;

    // Server stuff
    int server_fd;
    int client_fd;
    unsigned char is_server;
    unsigned char connected;

    // A buffer for receiving metadata lines from files or sockets
    char* line_buf;
    size_t line_buf_size;
} DataManager;

int DataManager_init(DataManager*, size_t);
void DataManager_free(DataManager*);
int DataManager_serve(DataManager*, int);
int DataManager_connect(DataManager*, const char*, size_t, size_t);
void DataManager_disconnect(DataManager*);
RecordGroup* DataManager_get_group(DataManager*, const char*, size_t*);
RecordGroup* DataManager_add_group(DataManager*, const char*);
int DataManager_load(DataManager*, const char*);
int DataManager_save(DataManager*, const char*);
int DataManager_sync(DataManager*, int);
void DataManager_finalize(DataManager*);
int DataManager_hangup(DataManager*);
int DataManager_contains(DataManager*, const char*);

#endif // _DATAMANAGER_H