#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <structmember.h>

#ifdef __aarch64__
#include "xrfclk.h"
#endif

#define RFCLK_WRONG_HARDWARE_MESSAGE "%s may only be called on RFSoC hardware."
#define RFCLK_WRONG_HARDWARE_EXCEPTION PyErr_Format(PyExc_SystemError, RFCLK_WRONG_HARDWARE_MESSAGE, __FUNCTION__)


static const char RFCLK_INIT_DOCSTRING[] = "Attach to the physical interface of the clock system.";
static PyObject* PyRfclk_init(PyObject* self, PyObject* gpio_obj)
{
    #ifdef __aarch64__

    int gpio;
    if(!PyArg_Parse(gpio_obj, "i", &gpio))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    if(XRFClk_Init(gpio) != XST_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Unable to initialize RFClk subsystem.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFCLK_WRONG_HARDWARE_EXCEPTION;
    #endif
}


static const char RFCLK_WRITE_REG_DOCSTRING[] = "Write a register in one of the chips in the clock system.";
static PyObject* PyRfclk_write_reg(PyObject* self, PyObject* args, PyObject* kwargs)
{
    #ifdef __aarch64__

    uint32_t chip_id;
    uint32_t address;
    uint32_t data;

    static char* kwlist[] = {"chip_id", "address", "data", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "III", kwlist, &chip_id, &address, &data))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    data = address << 8 | (data & 0xFF);

    if(XRFClk_WriteReg(chip_id, data) != XST_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Failed to write register in %s", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFCLK_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFCLK_READ_REG_DOCSTRING[] = "Read a register in one of the chips in the clock system.";
static PyObject* PyRfclk_read_reg(PyObject* self, PyObject* args, PyObject* kwargs)
{
    #ifdef __aarch64__

    uint32_t chip_id;
    uint32_t address;

    static char* kwlist[] = {"chip_id", "address", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "II", kwlist, &chip_id, &address))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    address <<= 8;

    if(XRFClk_ReadReg(chip_id, &address) != XST_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Failed to read register in %s", __FUNCTION__);
    }

    return PyLong_FromLong(address);

    #else
    return RFCLK_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFCLK_RESET_CHIP_DOCSTRING[] = "Reset a chip in the clocking system.";
static PyObject* PyRfclk_reset_chip(PyObject* self, PyObject* chip_id_obj)
{
    #ifdef __aarch64__

    uint32_t chip_id;
    if(!PyArg_Parse(chip_id_obj, "I", &chip_id))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    if(XRFClk_ResetChip(chip_id) != XST_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Unable to reset chip in RFClk subsystem.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFCLK_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFCLK_SET_CONFIG_ON_ONE_CHIP_FROM_CONFIG_ID_DOCSTRING[] = "";
static PyObject* PyRfclk_set_config_on_one_chip_from_config_id(PyObject* self, PyObject* args, PyObject* kwargs)
{
    #ifdef __aarch64__

    uint32_t chip_id;
    uint32_t config_id = 1;

    static char* kwlist[] = {"chip_id", "config_id", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "II", kwlist, &chip_id, &config_id))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    if(XRFClk_SetConfigOnOneChipFromConfigId(chip_id, config_id) != XST_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Failed to configure clock chip in %s", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFCLK_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static PyMethodDef PyRfclkMethods[] = {
    {"init", (PyCFunction)PyRfclk_init, METH_O, RFCLK_INIT_DOCSTRING},
    {"write_reg", (PyCFunction)PyRfclk_write_reg, METH_VARARGS | METH_KEYWORDS, RFCLK_WRITE_REG_DOCSTRING},
    {"read_reg", (PyCFunction)PyRfclk_read_reg, METH_VARARGS | METH_KEYWORDS, RFCLK_READ_REG_DOCSTRING},
    {"reset_chip", (PyCFunction)PyRfclk_reset_chip, METH_O, RFCLK_RESET_CHIP_DOCSTRING},
    {"set_config_on_one_chip_from_config_id", (PyCFunction)PyRfclk_set_config_on_one_chip_from_config_id, METH_VARARGS | METH_KEYWORDS, RFCLK_SET_CONFIG_ON_ONE_CHIP_FROM_CONFIG_ID_DOCSTRING},
    {NULL, NULL, 0, NULL}
};

static const char RFCLK_DOCSTRING[] = "A Python interface to the RF clock synthesis and distribution system for the ZCU216.";
static struct PyModuleDef PyRfclk_module = {
    PyModuleDef_HEAD_INIT,
    "acadia.rfclk",  
    RFCLK_DOCSTRING,
    -1,
    PyRfclkMethods
};

PyMODINIT_FUNC
PyInit_rfclk(void)
{
    PyObject *module;

    module = PyModule_Create(&PyRfclk_module);
    if(module == NULL) 
    {
        return NULL;
    }

    #ifdef __aarch64__
    if(PyModule_AddIntConstant(module, "CHIP_ID_LMK", RFCLK_LMK) < 0) 
    {
        Py_DECREF(module);
        return NULL;
    }

    if(PyModule_AddIntConstant(module, "CHIP_ID_LMX_ADC", RFCLK_LMX2594_1) < 0) 
    {
        Py_DECREF(module);
        return NULL;
    }

    if(PyModule_AddIntConstant(module, "CHIP_ID_LMX_DAC", RFCLK_LMX2594_2) < 0) 
    {
        Py_DECREF(module);
        return NULL;
    }
    #endif
    
    return module;
}
