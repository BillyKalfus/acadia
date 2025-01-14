#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>
#include <fcntl.h>
#include <math.h>

#ifdef __aarch64__
#include <arm_neon.h>
#endif

#include "system_timer.h"
#include "sequencer.h"

typedef struct {
    int mem_fd;
    volatile uint32_t* gpio_mem; 
    volatile uint32_t* cache_mem; 
    volatile uint32_t* barrier_cache_mem; 
} module_state_t;

static PyObject* py_attach(PyObject* self) {
    #ifdef __aarch64__

    module_state_t* state = (module_state_t*)PyModule_GetState(self);

    state->mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if(state->mem_fd == -1)
    {
        PyErr_SetString(PyExc_ValueError, "Failed to open /dev/mem");
        return NULL;
    }

    state->gpio_mem = (volatile uint32_t*)mmap(NULL, 
                                        0x400, 
                                        PROT_READ | PROT_WRITE, 
                                        MAP_SHARED, 
                                        state->mem_fd, 
                                        0xFF0A0000);

    if(!state->gpio_mem) 
    {
        PyErr_SetString(PyExc_ValueError, "Failed to map GPIO memory");
        return NULL;
    }

    // TODO: detect this from the firmware
    // 2**20 bits = 1Mbit = 128K bytes = 32K 32-bit words
    state->cache_mem = (volatile uint32_t*)mmap(NULL, 
                                        (1 << (20-3)), 
                                        PROT_READ | PROT_WRITE, 
                                        MAP_SHARED, 
                                        state->mem_fd, 
                                        0xB0000000);

    if(!state->cache_mem) 
    {
        PyErr_SetString(PyExc_ValueError, "Failed to map cache memory");
        return NULL;
    }

    // TODO: make this not arbitrary, seems like this could break something
    state->barrier_cache_mem = state->cache_mem + 32700;

    Py_RETURN_NONE;

    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_detach(PyObject* self) {
    #ifdef __aarch64__
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    munmap((void*)(state->gpio_mem), 0x400);
    munmap((void*)(state->cache_mem), (1 << (20-3)));
    close(state->mem_fd);
    Py_RETURN_NONE;
    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_next_highest_power_of_2(PyObject* self, PyObject* args, PyObject* kwargs)
{
    unsigned int num;
    unsigned char log = 0;
    unsigned int i = 0;
    unsigned int val = 1;
    static char* kwlist[] = {"num", "log", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "I|B", kwlist, &num, &log))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    while(val < num)
    {
        i += 1;
        val <<= 1;
    }

    return PyLong_FromLong(log ? i : val);
}

static PyObject* py_clock_monotonic_ns(PyObject* self) {
    return PyLong_FromUnsignedLongLong(clock_monotonic_ns());
}

static PyObject* py_clock_monotonic_raw_ns(PyObject* self) {
    return PyLong_FromUnsignedLongLong(clock_monotonic_raw_ns());
}

static PyObject* py_sys_nanosleep(PyObject* self, PyObject* sleep_ns) {
    if(!PyLong_Check(sleep_ns))
    {
        return PyErr_Format(PyExc_TypeError, "Function %s requires an int.", __FUNCTION__);
    }
    
    unsigned long long v = PyLong_AsUnsignedLongLong(sleep_ns);
    sys_nanosleep(v);
    Py_RETURN_NONE;
}

static PyObject* py_sequencer_halt_and_reset(PyObject* self) {
    #ifdef __aarch64__

    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    sequencer_halt_and_reset(state->gpio_mem);
    Py_RETURN_NONE;

    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_run(PyObject* self) {
    #ifdef __aarch64__

    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    sequencer_run(state->gpio_mem);
    Py_RETURN_NONE;

    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_done(PyObject* self) {
    #ifdef __aarch64__

    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    return PyBool_FromLong((long)sequencer_done(state->gpio_mem));

    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_complete(PyObject* self) {
    #ifdef __aarch64__

    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    sequencer_complete(state->gpio_mem);
    Py_RETURN_NONE;

    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_mem_barrier(PyObject* self) {
    #ifdef __aarch64__

    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    sequencer_mem_barrier(state->barrier_cache_mem);
    Py_RETURN_NONE;

    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyMethodDef UtilsMethods[] = {
  {"attach",                   (PyCFunction)py_attach, METH_NOARGS, "Map memory for interacting with the hardware."},
  {"detach",                   (PyCFunction)py_detach, METH_NOARGS, "Unmap hardware memory."},
  {"next_highest_power_of_2",  (PyCFunction)py_next_highest_power_of_2, METH_VARARGS | METH_KEYWORDS, "Given a number, find the next highest power of 2."},
  {"clock_monotonic_ns",       (PyCFunction)py_clock_monotonic_ns, METH_NOARGS, "Retrieve the time in ns from CLOCK_MONOTONIC."},
  {"clock_monotonic_raw_ns",   (PyCFunction)py_clock_monotonic_raw_ns, METH_NOARGS, "Retrieve the time in ns from CLOCK_MONOTONIC_RAW."},
  {"sys_nanosleep",            (PyCFunction)py_sys_nanosleep, METH_O, "Sleep for a given amount of time (in nanoseconds)."},
  {"sequencer_halt_and_reset", (PyCFunction)py_sequencer_halt_and_reset, METH_NOARGS, "Halt and reset the sequencer."},
  {"sequencer_run",            (PyCFunction)py_sequencer_run, METH_NOARGS, "Run the sequencer."},
  {"sequencer_done",           (PyCFunction)py_sequencer_done, METH_NOARGS, "Determine whether the sequencer is completed or not."},
  {"sequencer_complete",       (PyCFunction)py_sequencer_complete, METH_NOARGS, "Block execution until the sequencer is complete."},
  {"sequencer_mem_barrier",    (PyCFunction)py_sequencer_mem_barrier, METH_NOARGS, "Set the barrier cache location to the constant 0xBEEBB00A and block execution until it changes."},
  {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef utils_module = {
    PyModuleDef_HEAD_INIT,
    "acadia.utils",
    "Various utilities for computational functions and driving signals on the RFSoC hardware.", 
    sizeof(module_state_t),
    UtilsMethods
};

PyMODINIT_FUNC
PyInit_utils(void)
{
    PyObject *m;

    m = PyModule_Create(&utils_module);
    if (m == NULL) {
        return NULL;
    }

    return m;
}
