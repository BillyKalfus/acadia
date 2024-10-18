#include "datamanager.h"
#include "io.h"

// #define ACADIA_DEBUG

#ifdef ACADIA_DEBUG
FILE* acadia_log = NULL;
#endif

static int load_metadata(DataManager*, int, int, size_t*, char***, size_t**);
static int save_metadata(DataManager*, int, int);


// Load metadata from a file or socket
// Returns 0 on success, or -1 when error
// group_names is a pointer to an array of strings
static int load_metadata(DataManager* self, int fd, int timeout_ms, size_t* num_groups, char*** group_names, size_t** num_records)
{
    unsigned char uniform;
    unsigned char flags;
    RecordGroup* group;
    int retval;
    size_t idx;

    // First, read number of groups
    if(timeout_ms == 0)
    {
        retval = readline(fd, self->line_buf, self->line_buf_size);
    }
    else
    {
        retval = recvline_polled(fd, self->line_buf, self->line_buf_size, timeout_ms);
    }

    if(retval == -1)
    {
        // String set inside
        return -1;
    }

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "load_metadata received line: %s\n", self->line_buf);
    fflush(acadia_log);
    #endif

    if(sscanf(self->line_buf, "%zu groups\n", num_groups) == EOF)
    {
        PyErr_Format(PyExc_ValueError, "Error loading number of groups");
        return -1;
    }

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "load_metadata parsed line: %d groups\n", *num_groups);
    fflush(acadia_log);
    #endif

    *group_names = (char**)malloc(*num_groups*sizeof(char*));
    if(*group_names == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Error allocating memory for %d group names", *num_groups);
        return -1;
    }

    *num_records = (size_t*)malloc(*num_groups*sizeof(size_t));
    if(*num_records == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Error allocating memory for record counts");
        return -1;
    }

    for(idx = 0; idx < *num_groups; idx++)
    {
        if(timeout_ms == 0)
        {
            retval = readline(fd, self->line_buf, self->line_buf_size);
        }
        else
        {
            retval = recvline_polled(fd, self->line_buf, self->line_buf_size, timeout_ms);
        }

        if(retval == -1)
        {
            return -1;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "load_metadata received line: %s\n", self->line_buf);
        fflush(acadia_log);
        #endif

        if(self->line_buf[0] == '#')
        {
            // Comment
            continue;
        }

        if(sscanf(self->line_buf, 
            "%m[a-zA-Z0-9_]:num_records=%zu:uniform=%hhu:flags=%hhx\n", 
            (*group_names) + idx, 
            (*num_records) + idx, 
            &uniform, 
            &flags) == EOF)
        {
            PyErr_Format(PyExc_ValueError, "Error processing line of group data %s", self->line_buf);
            return -1;
        }

        // If we already have this group, add_group will just return it
        group = DataManager_add_group(self, *((*group_names) + idx));
        if(group == NULL)
        {
            PyErr_Format(PyExc_ValueError, "Error adding group %s", *((*group_names) + idx));
            return -1;
        }

        group->uniform = uniform;
        group->flags = flags;
    }

    return 0;
}

static int save_metadata(DataManager* self, int fd, int timeout_ms)
{
    RecordGroup* group;
    char* group_name;
    size_t idx;
    size_t line_length;
    ssize_t retval;

    // First, write number of groups
    if(sprintf(self->line_buf, "%zu groups\n", self->num_groups) < 0)
    {
        PyErr_Format(PyExc_ValueError, "Error forming group count string");
        return -1;
    }

    line_length = strlen(self->line_buf);
    if(timeout_ms == 0)
    {
        retval = write(fd, self->line_buf, line_length);
    }
    else
    {
        retval = send(fd, self->line_buf, line_length, 0);
    }

    if(retval == -1)
    {
        PyErr_Format(PyExc_ValueError, "Error writing line to file: %s", strerror(errno));
        return -1;
    }

    if(retval != (ssize_t)line_length)
    {
        PyErr_Format(PyExc_ValueError, "Error writing line to file (write() returned %d)", retval);
        return -1;
    }

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "save_metadata wrote line: %s\n", self->line_buf);
    fflush(acadia_log);
    #endif

    // Write groups themselves
    for(idx = 0; idx < self->num_groups; idx++)
    {
        group = *(self->groups + idx);
        group_name = *(self->group_names + idx);

        if(sprintf(self->line_buf, "%s:num_records=%zu:uniform=%hhu:flags=%hhx\n", 
            group_name,
            group->num_records, 
            group->uniform, 
            group->flags) == EOF)
        {
            PyErr_Format(PyExc_ValueError, "Error forming metadata string for group %s", group_name);
            return -1;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "save_metadata created line: %s\n", self->line_buf);
        fflush(acadia_log);
        #endif

        line_length = strlen(self->line_buf);
        if(timeout_ms == 0)
        {
            retval = write(fd, self->line_buf, line_length);
        }
        else
        {
            retval = send(fd, self->line_buf, line_length, 0);
        }

        if(retval == -1)
        {
            PyErr_Format(PyExc_ValueError, "Error writing line to file for group %s: %s", group_name, strerror(errno));
            return -1;
        }

        if(retval != (ssize_t)line_length)
        {
            PyErr_Format(PyExc_ValueError, "Error writing line to file for group %s (write() returned %d)", group_name, retval);
            return -1;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "save_metadata wrote line: %s\n", self->line_buf);
        fflush(acadia_log);
        #endif
    }

    return 0;
}

int DataManager_init(DataManager* self, size_t line_buf_size)
{
    // Initialize defaults for everything
    self->num_groups = 0;
    self->groups = NULL;
    self->group_names = NULL;

    // Initialize storage for socket file descriptors
    self->client_fd = -1;
    self->server_fd = -1;
    self->is_server = 0;
    self->connected = 0;

    // Initialize a receive buffer for clients
    self->line_buf = (char*)malloc(line_buf_size);
    if(self->line_buf == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Failed to allocate %d bytes for DataManager receive buffer", line_buf_size);
        return -1;
    }

    self->line_buf_size = line_buf_size;

    #ifdef ACADIA_DEBUG
    if(acadia_log == NULL)
    {
        acadia_log = fopen("/tmp/acadia_log.log", "w");
    }
    #endif
    
    return 0;
}

void DataManager_free(DataManager* self)
{
    size_t idx;

    DataManager_disconnect(self);

    for(idx = 0; idx < self->num_groups; idx++)
    {
        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "Freeing group %s (index %d)\n", self->group_names[idx], idx);
        fflush(acadia_log);
        #endif

        free(self->group_names[idx]);
        RecordGroup_free(self->groups[idx]);
        free(self->groups[idx]);
    }

    free(self->groups);
    self->groups = NULL;
    free(self->group_names);
    self->group_names = NULL;
}

// Returns -1 when error
// Returns 0 when we successfully sent the client data
// Returns 1 when there's no client
// Returns 2 when there's a client but they didn't request anything
// Returns 3 when the client requested a disconnect
int DataManager_serve(DataManager* self, int timeout_ms)
{
    size_t idx;
    unsigned int recv_data;
    struct sockaddr_in server_sockaddr;
    const int enable = 1;
    RecordGroup* group;

    if(self->server_fd == -1)
    {
        // Create the server socket in non-blocking mode
        self->server_fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0);
        if(self->server_fd == -1)
        {
            PyErr_SetString(PyExc_ValueError, "Failed to open socket");
            return -1;
        }

        if(setsockopt(self->server_fd, SOL_SOCKET, SO_REUSEADDR, &enable, sizeof(int)) < 0)
        {
            PyErr_SetString(PyExc_ValueError, "Failed to set socket to reuse address.");
            return -1;
        }

        // Bind the server address to the socket
        memset(&server_sockaddr, 0, sizeof(server_sockaddr));
        server_sockaddr.sin_family = AF_INET; 
        server_sockaddr.sin_addr.s_addr = htonl(INADDR_ANY); 
        server_sockaddr.sin_port = htons(DATAMANAGER_SERVER_PORT);
        if(bind(self->server_fd, (struct sockaddr*)&server_sockaddr, sizeof(server_sockaddr)))
        {
            PyErr_SetString(PyExc_ValueError, "Failed to bind to socket");
            DataManager_disconnect(self);
            return -1;
        }

        // Begin listening
        if(listen(self->server_fd, 1) != 0)
        {
            PyErr_SetString(PyExc_ValueError, "Failed to set socket listening");
            DataManager_disconnect(self);
            return -1;
        }

        self->is_server = 1;
    }

    // Accept a client connection (if there is one)
    if(self->client_fd == -1)
    {
        self->client_fd = accept(self->server_fd, NULL, NULL);
        if(self->client_fd == -1)
        {
            if(errno == EWOULDBLOCK)
            {
                // No client, this is ok
                return DATAMANAGER_SERVE_NO_CLIENT;
            }

            // A real error occurred
            PyErr_Format(PyExc_ValueError, "Error accepting client connection: %s", strerror(errno));
            DataManager_disconnect(self);
            return -1;
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "serve accepted client\n");
        fflush(acadia_log);
        #endif
    }
    
    // See if the client sent anything
    // If so, it should only be a single uint32
    if(recv(self->client_fd, &recv_data, sizeof(unsigned int), MSG_DONTWAIT) == -1)
    {
        if(errno == EWOULDBLOCK || errno == EAGAIN)
        {
            // no requests
            return DATAMANAGER_SERVE_NO_REQUEST;
        }

        PyErr_Format(PyExc_ValueError, "Error receiving data from client: %s", strerror(errno));
        DataManager_disconnect(self);
        return -1;
    }

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "serve received data from client: 0x%X\n", recv_data);
    fflush(acadia_log);
    #endif

    if(recv_data == DATAMANAGER_SERVER_HANGUP_KEY)
    {
        return DATAMANAGER_SERVE_HANGUP;
    }

    // Make sure it's the special secret
    if(recv_data != DATAMANAGER_SERVER_SYNC_KEY)
    {
        PyErr_Format(PyExc_ValueError, "Received invalid request from client: 0x%X", recv_data);
        DataManager_disconnect(self);
        return -1;
    }
    
    // We have a client requesting data
    // First, send metadata
    if(save_metadata(self, self->client_fd, timeout_ms) == -1)
    {
        // Error set inside
        DataManager_disconnect(self);
        return -1;
    }

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "serve sent metadata\n");
    fflush(acadia_log);
    #endif

    for(idx = 0; idx < self->num_groups; idx++)
    {   
        // Send the record data
        group = self->groups[idx];
        if(RecordGroup_save(group, self->client_fd) == -1)
        {
            // exception set inside RecordGroup_flush
            DataManager_disconnect(self);
            return -1;
        }

        if(group->flags & GROUP_FLAG_CLEAR_AFTER_SEND)
        {
            RecordGroup_clear(group);
        }

        #ifdef ACADIA_DEBUG
        fprintf(acadia_log, "serve saved group: %s\n", self->group_names[idx]);
        fflush(acadia_log);
        #endif
    }
    
    return DATAMANAGER_SERVE_SENT;
}

int DataManager_connect(DataManager* self, const char* server_address, size_t attempt_limit, size_t attempt_delay)
{
    int retval;
    size_t attempts;
    struct sockaddr_in server_sockaddr;
    const int enable = 1;

    // Do some error-checking
    if(self->is_server)
    {
        PyErr_SetString(PyExc_ValueError, "`connect` should only be called on DataManager objects that aren't already servers.");
        self->connected = 0;
        return -1;
    }

    if(self->server_fd != -1)
    {
        PyErr_SetString(PyExc_ValueError, "Server file descriptor already exists! Call `disconnect`.");
        return -1;
    }

    // Open the socket (nonblocking)
    self->server_fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0);
    if(self->server_fd == -1)
    {
        PyErr_SetString(PyExc_ValueError, "Failed to open socket");
        self->connected = 0;
        return -1;
    }

    if(setsockopt(self->server_fd, SOL_SOCKET, SO_REUSEADDR, &enable, sizeof(int)) < 0)
    {
        PyErr_SetString(PyExc_ValueError, "Failed to set socket to reuse address.");
        self->connected = 0;
        return -1;
    }

    // Connect to the server
    memset(&server_sockaddr, 0, sizeof(server_sockaddr));
    server_sockaddr.sin_family = AF_INET; 
    server_sockaddr.sin_addr.s_addr = inet_addr(server_address); 
    server_sockaddr.sin_port = htons(DATAMANAGER_SERVER_PORT);
    retval = connect(self->server_fd, &server_sockaddr, sizeof(server_sockaddr));
    attempts = 0;
    while(retval || attempts < attempt_limit)
    {
        switch(errno) {
            case EISCONN:
                // Already connected
                retval = 0;
                break;

            case EALREADY:
                // Previous connection attempt not yet completed
            case EINPROGRESS:
                // Connection cannot be completed immediately
                usleep(attempt_delay);
                retval = connect(self->server_fd, &server_sockaddr, sizeof(server_sockaddr));
                break;

            default:
                PyErr_SetFromErrno(PyExc_OSError);
                DataManager_disconnect(self);
                return -1;
        }
        attempts++;
    }

    if(retval != 0)
    {
        PyErr_SetString(PyExc_ValueError, "Timed out connecting to server");
        DataManager_disconnect(self);
        self->connected = 0;
        return -1;
    }

    self->connected = 1;
    return 0;
}

void DataManager_disconnect(DataManager* self)
{
    if(self->server_fd != -1)
    {
        close(self->server_fd);
        self->server_fd = -1;
    }
    
    if(self->client_fd != -1)
    {
        close(self->client_fd);
        self->client_fd = -1;
    }
    
    self->connected = 0;
    self->is_server = 0;
}

RecordGroup* DataManager_get_group(DataManager* self, const char* name, size_t* index)
{
    for(*index = 0; (*index) < self->num_groups; (*index)++)
    {
        if(!strcmp(name, self->group_names[*index]))
        {
            return self->groups[*index];
        }
    }

    return NULL;
}

RecordGroup* DataManager_add_group(DataManager* self, const char* name)
{
    size_t idx;
    RecordGroup* group;

    group = DataManager_get_group(self, name, &idx);
    if(group != NULL)
    {
        return group;
    }

    self->num_groups += 1;
    self->groups = (RecordGroup**)realloc(self->groups, self->num_groups*sizeof(RecordGroup*));
    if(self->groups == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Failed to extend groups list for group %s", name);
        return NULL;
    }

    group = (RecordGroup*)malloc(sizeof(RecordGroup));
    if(group == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Failed to allocate memory for group %s", name);
        return NULL;
    }

    RecordGroup_init(group);
    self->groups[self->num_groups-1] = group;

    self->group_names = (char**)realloc(self->group_names, self->num_groups*sizeof(char*));
    if(self->group_names == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Failed to extend group name list for group %s", name);
        return NULL;
    }

    self->group_names[self->num_groups-1] = (char*)malloc(strlen(name)+1);
    if(self->group_names[self->num_groups-1] == NULL)
    {
        PyErr_Format(PyExc_MemoryError, "Failed to allocate memory for group name %s", name);
        return NULL;
    }

    if(!strcpy(self->group_names[self->num_groups-1], name))
    {
        PyErr_Format(PyExc_MemoryError, "Failed to copy group name %s", name);
        return NULL;
    }

    return group;
}

int DataManager_load(DataManager* self, const char* directory)
{
    int metadata_fd;
    char* path;
    size_t idx;
    char** group_names;
    size_t num_groups;
    size_t* num_records;
    size_t unused;
    int record_fd;
    int retval;
    RecordGroup* group;

    path = (char*)malloc(32768);

    // Open the metadata file
    memcpy(path, directory, strlen(directory));
    strcpy(path + strlen(directory), "/metadata.txt");

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "DataManager_load loading metadata from file %s", path);
    fflush(acadia_log);
    #endif

    metadata_fd = open(path, O_RDONLY);
    if(metadata_fd == -1)
    {
        if(errno == ENOENT)
        {
            PyErr_Format(PyExc_FileNotFoundError, "No metadata found in directory %s", directory);
        }
        else
        {
            PyErr_Format(PyExc_ValueError, "Error opening metadata file in directory %s: %s", directory, strerror(errno));
        }

        return -1;
    }

    if(load_metadata(self, metadata_fd, 0, &num_groups, &group_names, &num_records) == -1)
    {
        // Error string set inside
        return -1;
    }

    close(metadata_fd);

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "DataManager_load found %d groups\n", num_groups);
    fflush(acadia_log);
    #endif

    retval = 0;
    for(idx = 0; idx < num_groups; idx++)
    {
        if(!retval)
        {
            // Load data for this RecordGroup
            group = DataManager_get_group(self, group_names[idx], &unused);
            if(group == NULL)
            {
                PyErr_Format(PyExc_ValueError, "Group not found during load: %s", group_names[idx]);
                retval = -1;
                continue;
            }

            // Open the binary file holding the data and load it
            sprintf(path, "%s/%s.bin", directory, group_names[idx]);
            record_fd = open(path, O_RDONLY);

            // If there are any errors, we continue the loop so that the memory allocated by load_metadata gets freed
            if(record_fd == -1)
            {
                PyErr_Format(PyExc_ValueError, "Error opening record file %s: %s", path, strerror(errno));
                retval = -1;
                continue;
            }

            // Clear the group if needed
            if(group->flags & GROUP_FLAG_CLEAR_BEFORE_LOAD)
            {
                RecordGroup_clear(group);
            }

            #ifdef ACADIA_DEBUG
            fprintf(acadia_log, "DataManager_load loading group %s with %zu records\n", group_names[idx], num_records[idx]);
            fflush(acadia_log);
            #endif
            
            retval = RecordGroup_load(group, record_fd, num_records[idx], 0);
            close(record_fd);
        }

        free(group_names[idx]);
    }

    #ifdef ACADIA_DEBUG
    fprintf(acadia_log, "DataManager_load complete with retval %d\n", retval);
    fflush(acadia_log);
    #endif

    free(group_names);
    free(num_records);

    return retval;
}

int DataManager_save(DataManager* self, const char* directory)
{
    int metadata_fd;
    char* path;
    size_t idx;
    size_t unused;
    int record_fd;
    int retval;
    char* group_name;
    RecordGroup* group;
    size_t directory_strlen;

    path = (char*)malloc(32768);
    if(directory == NULL)
    {
        if(!getcwd(path, 32768))
        {
            PyErr_Format(PyExc_ValueError, "Error retrieving current directory: %s", strerror(errno));
            free(path);
            return -1;
        }
        directory_strlen = strlen(path);
    }
    else
    {
        directory_strlen = strlen(directory);
        memcpy(path, directory, directory_strlen);
    }

    // Open the metadata file
    strcpy(path + directory_strlen, "/metadata.txt");
    metadata_fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, S_IRWXU | S_IRWXG | S_IRWXO);
    if(metadata_fd == -1)
    {
        PyErr_Format(PyExc_ValueError, "Error opening metadata file: %s", strerror(errno));
        free(path);
        return -1;
    }

    if(save_metadata(self, metadata_fd, 0) == -1)
    {
        // Error string set inside
        free(path);
        return -1;
    }

    close(metadata_fd);

    for(idx = 0; idx < self->num_groups; idx++)
    {
        // Load data for this RecordGroup
        group_name = self->group_names[idx];
        group = DataManager_get_group(self, group_name, &unused);

        // Open the binary file holding the data and load it
        strcpy(path + directory_strlen + 1, group_name);
        strcpy(path + strlen(path), ".bin");
        record_fd = open(path, O_WRONLY | O_CREAT, S_IRWXU | S_IRWXG | S_IRWXO);
        retval = RecordGroup_save(group, record_fd);
        close(record_fd);

        if(group->flags & GROUP_FLAG_CLEAR_AFTER_SAVE)
        {
            RecordGroup_clear(group);
        }
        
        if(retval)
        {
            free(path);
            return -1;
        }
    }
    free(path);
    return 0;
}

int DataManager_sync(DataManager* self, int timeout_ms)
{
    int retval;
    const unsigned int key = DATAMANAGER_SERVER_SYNC_KEY;
    char** group_names;
    size_t num_groups;
    size_t* num_records;
    size_t idx;
    size_t unused;
    RecordGroup* group;

    if(self->is_server)
    {
        PyErr_SetString(PyExc_ValueError, "Server DataManagers should not call `sync`.");
        return -1;
    }

    if(self->server_fd == -1)
    {
        PyErr_SetString(PyExc_ValueError, "Not connected to server.");
        return -1;
    }

    // Send the special sentinel key to the server to request data
    if(send(self->server_fd, &key, sizeof(unsigned int), 0) == -1)
    {
        PyErr_Format(PyExc_ValueError, "Error sending sentinel key to server: %s", strerror(errno));
        DataManager_disconnect(self);
        return -1;
    }

    // Receive metadata length from the server
    if(load_metadata(self, self->server_fd, timeout_ms, &num_groups, &group_names, &num_records) == -1)
    {
        // Error string set inside
        return -1;
    }

    retval = 0;
    for(idx = 0; idx < num_groups; idx++)
    {
        if(!retval)
        {
            // Load data for this RecordGroup
            // If there's an error, don't return, continue the loop so that all the memory allocated by load_metadata gets freed
            group = DataManager_add_group(self, group_names[idx]);
            if(group == NULL)
            {
                retval = -1;
                continue;
            }

            if(group->flags & GROUP_FLAG_CLEAR_BEFORE_SYNC)
            {
                RecordGroup_clear(group);
            }

            #ifdef ACADIA_DEBUG
            fprintf(acadia_log, "sync loading group %s\n", group_names[idx]);
            fflush(acadia_log);
            #endif

            retval = RecordGroup_load(group, self->server_fd, num_records[idx], timeout_ms);
        }

        free(group_names[idx]);
    }

    // We can free the group_names array without freeing its elements because
    // its elements are now stored in the record group
    free(group_names);
    free(num_records);

    return retval;
}

// Send a hangup request to the remote side
int DataManager_hangup(DataManager* self)
{
    const unsigned int key = DATAMANAGER_SERVER_HANGUP_KEY;

    // Send the special sentinel key to the server to request that it close
    if(send(self->server_fd, &key, sizeof(unsigned int), 0) == -1)
    {
        PyErr_Format(PyExc_ValueError, "Error sending hangup sentinel key to server: %s", strerror(errno));
        DataManager_disconnect(self);
        return -1;
    }

    return 0;
}

void DataManager_finalize(DataManager* self)
{
    size_t idx;

    for(idx = 0; idx < self->num_groups; idx++)
    {
        self->groups[idx]->flags |= GROUP_FLAG_FINALIZED;
    }
}

int DataManager_contains(DataManager* self, const char* group_name)
{
    size_t idx;
    RecordGroup* group;
    group = DataManager_get_group(self, group_name, &idx);
    if(group == NULL)
    {
        return 0;
    }
    
    return 1;
}

