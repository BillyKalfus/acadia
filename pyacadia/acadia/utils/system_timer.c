#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "system_timer.h"

uint64_t clock_monotonic_ns()
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return now.tv_sec*1000000000ULL + now.tv_nsec;
}

uint64_t clock_monotonic_raw_ns()
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC_RAW, &now);
    return now.tv_sec*1000000000ULL + now.tv_nsec;
}

int sys_nanosleep(uint64_t sleep_ns)
{
    struct timespec req;
    req.tv_sec = sleep_ns / 1000000000ULL;
    req.tv_nsec = sleep_ns % 1000000000ULL;
    return nanosleep(&req, NULL);
}
