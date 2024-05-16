#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "ps_functions.h"

static PyObject* py_add_rows(PyObject* self, PyObject* args, PyObject* kwargs) {
    static char *kwlist[] = {"input", "output", "threads", NULL};
    Py_buffer input, output;
    int i, retval;
    uint32_t num_rows, num_cols, threads;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "y*w*I", kwlist,
                                  &input, &output, &threads))
    {
        PyErr_SetString(PyExc_ValueError, "Error parsing arguments in add_rows");
        return NULL;
    }

    // Flatten the array to 2D
    num_cols = input.shape[input.ndim-1];
    num_rows = 1;
    for(i = 0; i < input.ndim-1; i++) {
        num_rows *= input.shape[i];
    }
    
    retval = _add_rows(
        (int16_t*)input.buf, 
        (int32_t*)output.buf, 
        num_rows, 
        num_cols,
        threads
    );

    PyBuffer_Release(&input);
    PyBuffer_Release(&output);

    return PyLong_FromLong(retval);
}

typedef struct {
    int mem_fd;
    volatile uint32_t* gpio_mem; 
    volatile uint32_t* cache_mem; 
    volatile uint32_t* barrier_cache_mem; 
} module_state_t;

static PyObject* py_attach(PyObject* self, PyObject* args) {
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
}

static PyObject* py_detach(PyObject* self) {
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    munmap(state->gpio_mem, 0x400);
    munmap(state->cache_mem, (1 << (20-3)));
    close(state->mem_fd);
    Py_RETURN_NONE;
}

static PyObject* py_get_tbclk(PyObject* self) {
    return PyLong_FromUnsignedLong(get_tbclk());
}

static PyObject* py_sequencer_halt_and_reset(PyObject* self) {
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    sequencer_halt_and_reset(state->gpio_mem);
    Py_RETURN_NONE;
}

static PyObject* py_sequencer_run(PyObject* self) {
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    sequencer_run(state->gpio_mem);
    Py_RETURN_NONE;
}

static PyObject* py_sequencer_done(PyObject* self) {
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    uint8_t done = sequencer_done(state->gpio_mem);
    return PyBool_FromLong((long)done);
}

static PyObject* py_sequencer_complete(PyObject* self) {
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    sequencer_complete(state->gpio_mem);
    Py_RETURN_NONE;
}

static PyObject* py_sequencer_mem_barrier(PyObject* self) {
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    sequencer_mem_barrier(state->barrier_cache_mem);
    Py_RETURN_NONE;
}

static PyMethodDef PSMethods[] = {
  {"add_rows",                 (PyCFunction)py_add_rows, METH_VARARGS | METH_KEYWORDS, "Add rows of a multidimensional array."},
  {"attach",                   (PyCFunction)py_attach, METH_NOARGS, "Map memory for interacting with the hardware."},
  {"detach",                   (PyCFunction)py_detach, METH_NOARGS, "Unmap hardware memory."},
  {"get_tbclk",                (PyCFunction)py_get_tbclk, METH_NOARGS, "Get TB clk."},
  {"sequencer_halt_and_reset", (PyCFunction)py_sequencer_halt_and_reset, METH_NOARGS, "Halt and reset the sequencer."},
  {"sequencer_run",            (PyCFunction)py_sequencer_run, METH_NOARGS, "Run the sequencer."},
  {"sequencer_done",           (PyCFunction)py_sequencer_done, METH_NOARGS, "Determine whether the sequencer is completed or not."},
  {"sequencer_complete",       (PyCFunction)py_sequencer_complete, METH_NOARGS, "Block execution until the sequencer is complete."},
  {"sequencer_mem_barrier",    (PyCFunction)py_sequencer_mem_barrier, METH_NOARGS, "Set the barrier cache location to the constant 0xBEEBB00A and block execution until it changes."},
  {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef ps_functions_module = {
    PyModuleDef_HEAD_INIT,
    "acadia.ps_functions",   /* name of module */
    NULL, /* module documentation, may be NULL */
    sizeof(module_state_t),       /* size of per-interpreter state of the module,
                 or -1 if the module keeps state in global variables. */
    PSMethods
};

PyMODINIT_FUNC
PyInit_ps_functions(void)
{
    PyObject *m;

    m = PyModule_Create(&ps_functions_module);
    if (m == NULL) {
        return NULL;
    }

    return m;
}
