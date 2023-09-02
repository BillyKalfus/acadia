#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "ps_functions.h"

static PyObject* add_rows(PyObject* self, PyObject* args, PyObject* kwargs) {
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

    return Py_BuildValue("i", retval);
}

static PyMethodDef PSMethods[] = {
  {"add_rows",  (PyCFunction)add_rows, METH_KEYWORDS, "Add rows of a multidimensional array."},
  {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef ps_functions_module = {
    PyModuleDef_HEAD_INIT,
    "acadia.ps_functions",   /* name of module */
    NULL, /* module documentation, may be NULL */
    -1,       /* size of per-interpreter state of the module,
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