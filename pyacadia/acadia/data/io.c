#include "io.h"

int recvline_polled(int fd, char* buf, size_t buf_size, int timeout_ms)
{
    struct pollfd poll_struct;
    int retval;
    char* newline_ptr;
    size_t recv_size;
    size_t buf_occupancy;

    // Make sure we leave a space at the end for the null byte
    buf_size--;
    buf_occupancy = 0;

    do
    {
        // Wait until the file can be read
        poll_struct.fd = fd;
        poll_struct.events = POLLIN | POLLERR | POLLRDHUP;
        poll_struct.revents = 0;

        retval = poll(&poll_struct, 1, timeout_ms);
        if(retval == 0)
        {
            // Timeout occurred
            PyErr_SetString(PyExc_TimeoutError, "Timeout occurred waiting for line");
            return -1;
        }

        if(retval == -1)
        {
            // An error polling (not captured in revents)
            PyErr_Format(PyExc_ValueError, "Unexpected error when polling: %s", strerror(errno));
            return -1;
        }

        if(poll_struct.revents & POLLRDHUP)
        {
            PyErr_Format(PyExc_ValueError, "Socket peer closed connection");
            return -1;
        }

        if(poll_struct.revents & POLLERR)
        {
            PyErr_Format(PyExc_ValueError, "Polling error");
            return -1;
        }

        if(!(poll_struct.revents & POLLIN))
        {
            PyErr_Format(PyExc_ValueError, "Polling error without POLLERR");
            return -1;
        }

        // Peek in the socket receive buffer to find a newline
        retval = recv(fd, buf + buf_occupancy, buf_size - buf_occupancy, MSG_PEEK);
        if(retval == -1)
        {
            PyErr_Format(PyExc_ValueError, "Failed to read from socket after successful poll: %s", strerror(errno));
            return -1;
        }

        newline_ptr = (char*)memchr(buf + buf_occupancy, '\n', (size_t)retval);
        if(newline_ptr)
        {
            // There's a newline in the data we received
            // Pop the data (up to the newline) from the receive buffer and return
            // Add one so that there's a space for the newline itself
            recv_size = newline_ptr - (buf + buf_occupancy) + 1;
            retval = recv(fd, buf + buf_occupancy, recv_size, 0);
            if(retval == -1)
            {
                PyErr_Format(PyExc_ValueError, "Failed to read from socket when reading up to newline: %s", strerror(errno));
                return -1;
            }

            buf_occupancy += retval;

            // Add a null byte
            buf[buf_occupancy] = '\0';
            return (int)buf_occupancy;
        }

        // We got data but there's no newline in it, pop the data and keep going
        retval = recv(fd, buf + buf_occupancy, retval, 0);
        if(retval == -1)
        {
            PyErr_Format(PyExc_ValueError, "Failed to read from socket when buffering line");
            return -1;
        }
        
        buf_occupancy += retval;

    } while(buf_occupancy < buf_size);

    PyErr_SetString(PyExc_ValueError, "Buffer filled before finding newline");
    return -1;
}

// Read a line from a file
// The only reason this function exists is so that we don't need to structure the 
// entire messaging system to accomodate FILE* structs just to use fgets
int readline(int fd, char* buf, size_t buf_size)
{
    int retval;
    char* newline_ptr;
    off_t starting_offset;
    size_t buf_occupancy;

    // Make sure we leave a space at the end for the null byte
    buf_size--;
    buf_occupancy = 0;
    
    // Get the starting offset of the file
    starting_offset = lseek(fd, 0, SEEK_CUR);
    if(starting_offset == -1)
    {
        PyErr_Format(PyExc_ValueError, "Failed to retrieve file offset: %s", strerror(errno));
        return -1;
    }

    do
    {
        // Peek in the socket receive buffer to find a newline
        retval = read(fd, buf + buf_occupancy, buf_size - buf_occupancy);
        if(retval == -1)
        {
            PyErr_Format(PyExc_ValueError, "Failed to read from file: %s", strerror(errno));
            return -1;
        }

        newline_ptr = (char*)memchr(buf + buf_occupancy, '\n', (size_t)retval);
        buf_occupancy += retval;

        if(newline_ptr)
        {
            // There's a newline in the data we received
            // Seek the file descriptor back to the point just after the newline
            // buf_occupancy tells us how many total characters have been read
            // newline_ptr - buf tells us the offset within the buffer of the newline
            // +1 to seek to the point just after the newline
            if(lseek(fd, starting_offset + (off_t)(newline_ptr - buf) + 1, SEEK_SET) == -1)
            {
                PyErr_Format(PyExc_ValueError, "Failed to seek file descriptor after reading newline: %s", strerror(errno));
                return -1;
            }
            
            // Add null char for string termination
            buf[buf_occupancy] = '\0';
            return (int)buf_occupancy;
        }
    } while(buf_occupancy < buf_size);

    PyErr_SetString(PyExc_ValueError, "Buffer filled before finding newline");
    return -1;
}

// Read a file using poll() and handle errors
// The destination must have enough memory allocated to store the full set of data
int read_polled(int fd, void* dest, size_t size, int timeout_ms)
{
    struct pollfd poll_struct;
    int retval;

    // Run a loop, since the data may not be available right away
    while(size)
    {
        // Wait until the file can be read
        poll_struct.fd = fd;
        poll_struct.events = POLLIN | POLLERR | POLLRDHUP;
        poll_struct.revents = 0;

        retval = poll(&poll_struct, 1, timeout_ms);
        if(retval == 0)
        {
            PyErr_Format(PyExc_TimeoutError, "Timeout occurred polling for read");
            return -1;
        }

        if(retval == -1)
        {
            PyErr_Format(PyExc_ValueError, "Unexpected error when polling: %s", strerror(errno));
            return -1;
        }

        if(poll_struct.revents & POLLRDHUP)
        {
            PyErr_Format(PyExc_ValueError, "Socket peer closed connection");
            return -1;
        }

        if(poll_struct.revents & POLLERR)
        {
            PyErr_Format(PyExc_ValueError, "Polling error");
            return -1;
        }

        if(!(poll_struct.revents & POLLIN))
        {
            PyErr_Format(PyExc_ValueError, "Polling error without POLLERR");
            return -1;
        }

        retval = read(fd, dest, size);
        if(retval <= 0)
        {
            // Since we've already polled to wait for the file to be readable,
            // this indicates an error
            PyErr_Format(PyExc_ValueError, "Failed to read %zu bytes after polling: %s", size, strerror(errno));
            return -1;
        }

        dest += retval;
        size -= retval;
    }

    return 0;
}
