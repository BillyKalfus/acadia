#ifndef _IO_H
#define _IO_H

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
#include <poll.h>

int recvline_polled(int, char*, size_t, int);
int read_polled(int, void*, size_t, int);
int readline(int, char*, size_t);

#endif
