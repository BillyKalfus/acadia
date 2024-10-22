#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <structmember.h>

#include <math.h>

#ifdef __aarch64__

#include "xrfdc.h"
#include <metal/device.h>
#include <metal/sys.h>
#include <string.h>
static XRFdc xrfdc;
static struct metal_device* metal;
static XRFdc_MultiConverter_Sync_Config dac_mts_config;
static XRFdc_MultiConverter_Sync_Config adc_mts_config;

#endif

#define RFDC_WRONG_HARDWARE_MESSAGE "%s may only be called on RFSoC hardware."
#define RFDC_WRONG_HARDWARE_EXCEPTION PyErr_Format(PyExc_SystemError, RFDC_WRONG_HARDWARE_MESSAGE, __FUNCTION__)

typedef struct {
    PyObject_HEAD
    unsigned char tile;
    unsigned char block;
    unsigned char is_dac;
    unsigned char interface_width_bytes;
    double interface_sample_frequency;
    double analog_sample_frequency;
} ChannelObject;

static int PyChannel_init(PyObject* self, PyObject* args, PyObject* kwargs)
{
    ChannelObject* self_channel = (ChannelObject*)self;
    self_channel->analog_sample_frequency = 0;
    self_channel->interface_sample_frequency = 0;

    static char* kwlist[] = {"tile", "block", "is_dac", "interface_width_bytes", "interface_sample_frequency", "analog_sample_frequency", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "BBBBd|d", kwlist, 
        &(self_channel->tile), 
        &(self_channel->block), 
        &(self_channel->is_dac),
        &(self_channel->interface_width_bytes),
        &(self_channel->interface_sample_frequency),
        &(self_channel->analog_sample_frequency)))
    {
        PyErr_SetString(PyExc_ValueError, "Unable to parse arguments in Channel.__init__");
        return -1;
    }

    return 0;
}

static PyObject* PyChannel_str(PyObject* self)
{
    ChannelObject* self_channel = (ChannelObject*)self;
    unsigned int num = (self_channel->tile)*4 + (self_channel->block);
    return PyUnicode_FromFormat("%s%lu", 
        self_channel->is_dac ? "DAC" : "ADC",
        num);
}

static PyObject* PyChannel_num(PyObject* self)
{
    ChannelObject* self_channel = (ChannelObject*)self;
    return PyLong_FromLong((self_channel->tile)*4 + (self_channel->block));
}

static const char CHANNEL_STATUS_DOCSTRING[] = "Retrieve the status of the channel.";
static PyObject* PyChannel_status(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    XRFdc_BlockStatus status;
    PyObject* key;
    PyObject* value;

    if(XRFdc_GetBlockStatus(&xrfdc, self_channel->is_dac, self_channel->tile, self_channel->block, &status) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_SystemError, "Call to XRFdc_GetBlockStatus failed in function %s", __FUNCTION__);
    }

    PyObject* d = PyDict_New();

    key = PyUnicode_FromString("sampling_freq");
    value = PyFloat_FromDouble(status.SamplingFreq);
    PyDict_SetItem(d, key, value);
    Py_DECREF(key);
    Py_DECREF(value);

    key = PyUnicode_FromString("datapath_clocks_status");
    value = PyBool_FromLong((long)(status.DataPathClocksStatus));
    PyDict_SetItem(d, key, value);
    Py_DECREF(key);
    Py_DECREF(value);

    key = PyUnicode_FromString("fifo_flags_enabled");
    value = PyBool_FromLong((long)(status.IsFIFOFlagsEnabled));
    PyDict_SetItem(d, key, value);
    Py_DECREF(key);
    Py_DECREF(value);

    key = PyUnicode_FromString("fifo_flags_asserted");
    value = PyBool_FromLong((long)(status.IsFIFOFlagsAsserted));
    PyDict_SetItem(d, key, value);
    Py_DECREF(key);
    Py_DECREF(value);

    if(self_channel->is_dac)
    {
        key = PyUnicode_FromString("inverse_sinc_enabled");
        value = PyBool_FromLong(status.AnalogDataPathStatus & (0xF << 0));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("decoder_mode");
        value = PyBool_FromLong(status.AnalogDataPathStatus & (0xF << 4));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("fifo_status");
        value = PyBool_FromLong(status.DigitalDataPathStatus & (0xF << 0));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("interpolation");
        value = PyBool_FromLong(status.DigitalDataPathStatus & (0xF << 4));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("adder_status");
        value = PyBool_FromLong(status.DigitalDataPathStatus & (0xF << 8));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("mixer_mode");
        value = PyBool_FromLong(status.DigitalDataPathStatus & (0xF << 12));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);
    }
    else
    {
        key = PyUnicode_FromString("enabled");
        value = PyBool_FromLong(status.AnalogDataPathStatus & (1 << 0));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("fifo_status");
        value = PyBool_FromLong(status.DigitalDataPathStatus & (0xF << 0));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("decimation");
        value = PyBool_FromLong(status.DigitalDataPathStatus & (0xF << 4));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("mixer_mode");
        value = PyBool_FromLong(status.DigitalDataPathStatus & (0xF << 8));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);
    }
    
    return d;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_LOAD_SAMPLE_FREQUENCY_DOCSTRING[] = "Loads the analog sample frequency from the tile into the internal data structure.";
static PyObject* PyChannel_load_sample_frequency(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    XRFdc_BlockStatus status;

    if(XRFdc_GetBlockStatus(&xrfdc, self_channel->is_dac, self_channel->tile, self_channel->block, &status) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_SystemError, "Call to XRFdc_GetBlockStatus failed in function %s", __FUNCTION__);
    }

    self_channel->analog_sample_frequency = status.SamplingFreq*1e9;

    Py_RETURN_NONE;
    
    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_NCO_UPDATE_EVENT_SOURCE_DOCSTRING[] = "Sets the source with which NCO setting updates will be triggered.\nValid options are 'immediate', 'slice', 'tile', 'marker', 'pl', and 'sysref'";
static PyObject* PyChannel_set_nco_update_event_source(PyObject* self, PyObject* source_obj)
{
    #ifdef __aarch64__

    const char* source;
    uint16_t source_int;
    uint32_t base_address;
    ChannelObject* self_channel = (ChannelObject*)self;

    if(!PyArg_Parse(source_obj, "s", &source))
    {
        return PyErr_Format(PyExc_ValueError, "Parsing arguments in %s failed.", __FUNCTION__);
    }

    if(strcmp(source, "immediate") == 0)
    {
        source_int = XRFDC_EVNT_SRC_IMMEDIATE;
    }
    else if(strcmp(source, "slice") == 0)
    {
        source_int = XRFDC_EVNT_SRC_SLICE;
    }
    else if(strcmp(source, "tile") == 0)
    {
        source_int = XRFDC_EVNT_SRC_TILE;
    }
    else if(strcmp(source, "marker") == 0)
    {
        source_int = XRFDC_EVNT_SRC_MARKER;
    }
    else if(strcmp(source, "pl") == 0)
    {
        source_int = XRFDC_EVNT_SRC_PL;
    }
    else if(strcmp(source, "sysref") == 0)
    {
        source_int = XRFDC_EVNT_SRC_SYSREF;
    }
    else
    {
        return PyErr_Format(PyExc_ValueError, "Invalid event source string `%s`.", source);
    }

    base_address = XRFDC_BLOCK_BASE(self_channel->is_dac, self_channel->tile, self_channel->block);
    XRFdc_ClrSetReg(
        (&xrfdc), 
        base_address, 
        XRFDC_NCO_UPDT_OFFSET, 
        XRFDC_NCO_UPDT_MODE_MASK,
        source_int
    );
    
    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_NCO_UPDATE_EVENT_SOURCE_DOCSTRING[] = "Retrieves the source with which NCO setting updates will be triggered.\n";
static PyObject* PyChannel_get_nco_update_event_source(PyObject* self)
{
    #ifdef __aarch64__

    const char* source;
    uint16_t source_int;
    uint32_t base_address;
    ChannelObject* self_channel = (ChannelObject*)self;

    base_address = XRFDC_BLOCK_BASE(self_channel->is_dac, self_channel->tile, self_channel->block);
    source_int = XRFdc_ReadReg16((&xrfdc), base_address, XRFDC_NCO_UPDT_OFFSET) & XRFDC_NCO_UPDT_MODE_MASK;

    switch(source_int)
    {
        case XRFDC_EVNT_SRC_IMMEDIATE:
            return PyUnicode_FromString("immediate");
        case XRFDC_EVNT_SRC_SLICE:
            return PyUnicode_FromString("slice");
        case XRFDC_EVNT_SRC_TILE:
            return PyUnicode_FromString("tile");
        case XRFDC_EVNT_SRC_MARKER:
            return PyUnicode_FromString("marker");
        case XRFDC_EVNT_SRC_PL:
            return PyUnicode_FromString("pl");
        case XRFDC_EVNT_SRC_SYSREF:
            return PyUnicode_FromString("sysref");
        default:
            return PyErr_Format(PyExc_ValueError, "Received invalid source `%d`.", source);
    }

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_DELAY_DOCSTRING[] = "Set parameters for the analog delay line in the channel.";
static PyObject* PyChannel_set_delay(PyObject* self, PyObject* delay_obj)
{
    #ifdef __aarch64__

    // TODO
    return NULL;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_DELAY_DOCSTRING[] = "Retrieve parameters for the analog delay line in the channel.";
static PyObject* PyChannel_get_delay(PyObject* self)
{
    #ifdef __aarch64__

    // TODO
    return NULL;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_FREQUENCY_TO_NCO_WORD_DOCSTRING[] = "Converts a floating-point frequency in Hz into an NCO tuning word for the channel using its internally-stored analog sampling frequency.";
static PyObject* PyChannel_frequency_to_nco_word(PyObject* self, PyObject* frequency_obj)
{
    ChannelObject* self_channel = (ChannelObject*)self;
    double nco_sample_frequency;
    double frequency;
    double word_double;
    int64_t word;

    if(!PyArg_Parse(frequency_obj, "d", &frequency))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    nco_sample_frequency = self_channel->analog_sample_frequency;
    if(nco_sample_frequency == 0)
    {
        return PyErr_Format(PyExc_ValueError, "Analog sample rate not yet assigned to %s%d_%d, which is required for function %s", 
            (self_channel->is_dac ? "DAC" : "ADC"),
            (self_channel->tile),
            (self_channel->block),
            __FUNCTION__);
    }
    else if(nco_sample_frequency > 7e9)
    {
        nco_sample_frequency /= 2;
    }

    word_double = round(((int64_t)1 << 48) * frequency / nco_sample_frequency);
    // We can just mask the appropriate bits of the word after multiplying 
    // in order to put it into the correct nyquist zone  
    word = ((int64_t)word_double) & (((int64_t)1 << 48)-1);
    return PyLong_FromLongLong(word);
}

static const char CHANNEL_SET_NCO_FREQUENCY_WORD_DOCSTRING[] = "Updates the frequency of the NCO by directly writing to the registers in the tile. The argument is the integer word value of the NCO increment.";
static PyObject* PyChannel_set_nco_frequency_word(PyObject* self, PyObject* word_obj)
{
    #ifdef __aarch64__
    int64_t word = 0;
    if(!PyArg_Parse(word_obj, "L", &word))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t address_base = XRFDC_BLOCK_BASE(self_channel->is_dac, 
                                             self_channel->tile, 
                                             self_channel->block);

    XRFdc_WriteReg16((&xrfdc), address_base, XRFDC_ADC_NCO_FQWD_LOW_OFFSET, word & 0xFFFF);
    XRFdc_WriteReg16((&xrfdc), address_base, XRFDC_ADC_NCO_FQWD_MID_OFFSET, (word >> 16) & 0xFFFF);
    XRFdc_WriteReg16((&xrfdc), address_base, XRFDC_ADC_NCO_FQWD_UPP_OFFSET, (word >> 32) & 0xFFFF);

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_NCO_FREQUENCY_DOCSTRING[] = "Updates the frequency of the NCO by directly writing to the registers in the tile.";
static PyObject* PyChannel_set_nco_frequency(PyObject* self, PyObject* frequency_obj)
{
    #ifdef __aarch64__
    PyObject* word;

    word = PyChannel_frequency_to_nco_word(self, frequency_obj);
    if(!word)
    {
        return NULL;
    }

    return PyChannel_set_nco_frequency_word(self, word);

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_NCO_FREQUENCY_WORD_DOCSTRING[] = "Retrieves the frequency of the NCO by directly reading the registers in the tile.";
static PyObject* PyChannel_get_nco_frequency_word(PyObject* self)
{
    #ifdef __aarch64__

    int64_t low, mid, high;
    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t address_base = XRFDC_BLOCK_BASE(self_channel->is_dac, 
                                             self_channel->tile, 
                                             self_channel->block);

    low = (int64_t)XRFdc_ReadReg16((&xrfdc), address_base, XRFDC_ADC_NCO_FQWD_LOW_OFFSET);
    mid = (int64_t)XRFdc_ReadReg16((&xrfdc), address_base, XRFDC_ADC_NCO_FQWD_MID_OFFSET);
    high = (int64_t)XRFdc_ReadReg16((&xrfdc), address_base, XRFDC_ADC_NCO_FQWD_UPP_OFFSET);
    return PyLong_FromLongLong(low | (mid << 16) | (high << 32));

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_PHASE_TO_NCO_WORD_DOCSTRING[] = "Converts a floating-point phase in radians into an NCO tuning word for the channel.";
static PyObject* PyChannel_phase_to_nco_word(PyObject* self, PyObject* phase_obj)
{
    double phase;
    int32_t phase_word;

    if(!PyArg_Parse(phase_obj, "d", &phase))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    phase_word = (int32_t)round((1 << 18) * phase / (2 * M_PI)) & ((1 << 18)-1);
    return PyLong_FromLong(phase_word);
}

static const char CHANNEL_SET_NCO_PHASE_WORD_DOCSTRING[] = "Updates the phase of the NCO by directly writing to the registers in the tile.";
static PyObject* PyChannel_set_nco_phase_word(PyObject* self, PyObject* word_obj)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    int32_t word;
    if(!PyArg_Parse(word_obj, "i", &word))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    uint32_t address_base = XRFDC_BLOCK_BASE(self_channel->is_dac, 
                                             self_channel->tile, 
                                             self_channel->block);

    XRFdc_WriteReg16((&xrfdc), address_base, XRFDC_NCO_PHASE_LOW_OFFSET, word & 0xFFFF);
    XRFdc_WriteReg16((&xrfdc), address_base, XRFDC_NCO_PHASE_UPP_OFFSET, (word >> 16) & 0x3);
    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_NCO_PHASE_DOCSTRING[] = "Updates the phase of the NCO by directly writing to the registers in the tile. The argument is a float in units of radians.";
static PyObject* PyChannel_set_nco_phase(PyObject* self, PyObject* phase_obj)
{
    #ifdef __aarch64__
    PyObject* word;

    word = PyChannel_phase_to_nco_word(self, phase_obj);
    if(!word)
    {
        return NULL;
    }

    return PyChannel_set_nco_phase_word(self, word);

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_NCO_PHASE_WORD_DOCSTRING[] = "Retrieves the phase of the NCO by directly reading the registers in the tile.";
static PyObject* PyChannel_get_nco_phase_word(PyObject* self)
{
    #ifdef __aarch64__

    int32_t low, high;
    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t address_base = XRFDC_BLOCK_BASE(self_channel->is_dac, 
                                             self_channel->tile, 
                                             self_channel->block);

    low = (int32_t)XRFdc_ReadReg16((&xrfdc), address_base, XRFDC_NCO_PHASE_LOW_OFFSET);
    high = (int32_t)XRFdc_ReadReg16((&xrfdc), address_base, XRFDC_NCO_PHASE_UPP_OFFSET);
    return PyLong_FromLong(low | (high << 16));

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_RESET_NCO_PHASE_DOCSTRING[] = "Resets the phase of the NCO by directly writing to the registers in the tile.";
static PyObject* PyChannel_reset_nco_phase(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    if(XRFdc_ResetNCOPhase((&xrfdc), self_channel->is_dac, self_channel->tile, self_channel->block) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_ResetNCOPhase in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_TRIGGER_NCO_UPDATE_EVENT_DOCSTRING[] = "Apply an NCO update event to the channel.";
static PyObject* PyChannel_trigger_nco_update_event(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    if(XRFdc_UpdateEvent((&xrfdc), self_channel->is_dac, self_channel->tile, self_channel->block, XRFDC_EVENT_MIXER) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_UpdateEvent in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_VOP_DOCSTRING[] = "Updates the VOP of a DAC channel.";
static PyObject* PyChannel_set_vop(PyObject* self, PyObject* vop_obj)
{
    #ifdef __aarch64__
    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t vop;
    if(!PyArg_Parse(vop_obj, "I", &vop))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    if(XRFdc_SetDACVOP((&xrfdc), self_channel->tile, self_channel->block, vop) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetDACVOP in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_VOP_DOCSTRING[] = "Retrieves the VOP of a DAC channel.";
static PyObject* PyChannel_get_vop(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t vop;

    if(XRFdc_GetOutputCurr((&xrfdc), self_channel->tile, self_channel->block, &vop) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetOutputCurr in %s failed.", __FUNCTION__);
    }

    return PyLong_FromUnsignedLong(vop);

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_DSA_DOCSTRING[] = "Updates the DSA of an ADC channel.";
static PyObject* PyChannel_set_dsa(PyObject* self, PyObject* dsa_obj)
{
    #ifdef __aarch64__
    XRFdc_DSA_Settings settings;
    ChannelObject* self_channel = (ChannelObject*)self;
    float dsa;
    if(!PyArg_Parse(dsa_obj, "f", &dsa))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    if(XRFdc_GetDSA((&xrfdc), self_channel->tile, self_channel->block, &settings) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetDSA in %s failed.", __FUNCTION__);
    }

    settings.Attenuation = dsa;

    if(XRFdc_SetDSA((&xrfdc), self_channel->tile, self_channel->block, &settings) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetDSA in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_DSA_DOCSTRING[] = "Retrieves the DSA of an ADC channel.";
static PyObject* PyChannel_get_dsa(PyObject* self)
{
    #ifdef __aarch64__

    XRFdc_DSA_Settings settings;
    ChannelObject* self_channel = (ChannelObject*)self;

    if(XRFdc_GetDSA((&xrfdc), self_channel->tile, self_channel->block, &settings) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetDSA in %s failed.", __FUNCTION__);
    }

    return PyFloat_FromDouble((double)(settings.Attenuation));

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_MIX_RECONSTRUCTION_DOCSTRING[] = "Sets whether the mix-mode reconstruction filter is used, which allows power to be focused into different Nyquist zones.";
static PyObject* PyChannel_set_mix_reconstruction(PyObject* self, PyObject* use_mix_obj)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint8_t use_mix;
    if(!PyArg_Parse(use_mix_obj, "B", &use_mix))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }
    
    if(XRFdc_SetNyquistZone((&xrfdc), 
        self_channel->is_dac, 
        self_channel->tile, 
        self_channel->block, 
        (use_mix ? XRFDC_EVEN_NYQUIST_ZONE : XRFDC_ODD_NYQUIST_ZONE)) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetNyquistZone in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_MIX_RECONSTRUCTION_DOCSTRING[] = "Queries whether the channel will use mix-mode reconstruction.";
static PyObject* PyChannel_get_mix_reconstruction(PyObject* self)
{
    #ifdef __aarch64__
    uint32_t nz;
    ChannelObject* self_channel = (ChannelObject*)self;
    if(XRFdc_GetNyquistZone((&xrfdc), self_channel->is_dac, self_channel->tile, self_channel->block, &nz) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetNyquistZone in %s failed.", __FUNCTION__);
    }

    if(nz == XRFDC_EVEN_NYQUIST_ZONE)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_HIGH_LINEARITY_MODE_DOCSTRING[] = "Updates the decoder mode of a DAC channel to use high-linearity mode (randomized decoder).";
static PyObject* PyChannel_set_high_linearity_mode(PyObject* self, PyObject* mode_obj)
{
    #ifdef __aarch64__
    ChannelObject* self_channel = (ChannelObject*)self;
    uint8_t mode;
    if(!PyArg_Parse(mode_obj, "B", &mode))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }
    
    if(XRFdc_SetDecoderMode((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        (mode ? XRFDC_DECODER_MAX_LINEARITY_MODE : XRFDC_DECODER_MAX_SNR_MODE)) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetDecoderMode in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_HIGH_LINEARITY_MODE_DOCSTRING[] = "Determines whether a DAC channel is configured to use high linearity mode.";
static PyObject* PyChannel_get_high_linearity_mode(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t mode;
    
    if(XRFdc_GetDecoderMode((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        &mode) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetDecoderMode in %s failed.", __FUNCTION__);
    }

    if(mode == XRFDC_DECODER_MAX_LINEARITY_MODE)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_IMR_HIGHPASS_DOCSTRING[] = "Enables or disables highpass mode on the high-frequency NCO image-reject filter for a DAC channel.";
static PyObject* PyChannel_set_imr_highpass(PyObject* self, PyObject* mode_obj)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t mode;
    if(!PyArg_Parse(mode_obj, "I", &mode))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }
    
    if(XRFdc_SetIMRPassMode((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        (mode ? XRFDC_DAC_IMR_MODE_HIGHPASS : XRFDC_DAC_IMR_MODE_LOWPASS)) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetIMRPassMode in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_IMR_HIGHPASS_DOCSTRING[] = "Retrieves the setting for the high-frequency NCO image-reject filter for a DAC channel.";
static PyObject* PyChannel_get_imr_highpass(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t mode;
    
    if(XRFdc_GetIMRPassMode((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        &mode) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetIMRPassMode in %s failed.", __FUNCTION__);
    }

    if(mode == XRFDC_DAC_IMR_MODE_HIGHPASS)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_INV_SINC_DOCSTRING[] = "Updates the inverse-sinc filter for a DAC channel. Must be one of: 0 (disable), 1 (first Nyquist zone), or 2 (second Nyquist zone)";
static PyObject* PyChannel_set_inv_sinc(PyObject* self, PyObject* mode_obj)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint16_t mode;
    if(!PyArg_Parse(mode_obj, "H", &mode))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }
    
    if(XRFdc_SetInvSincFIR((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        mode) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetInvSincFIR in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_INV_SINC_DOCSTRING[] = "Retrieves the setting for the inverse-sinc filter for a DAC channel.";
static PyObject* PyChannel_get_inv_sinc(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint16_t mode;
    if(XRFdc_GetInvSincFIR((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        &mode) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetInvSincFIR in %s failed.", __FUNCTION__);
    }

    return PyLong_FromLong((long)mode);

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_DITHER_DOCSTRING[] = "Updates the dithering setting of an ADC channel.";
static PyObject* PyChannel_set_dither(PyObject* self, PyObject* dither_obj)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t dither;
    if(!PyArg_Parse(dither_obj, "I", &dither))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }
    
    if(XRFdc_SetDither((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        dither) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetDither in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_DITHER_DOCSTRING[] = "Retrieves the dithering setting of an ADC channel.";
static PyObject* PyChannel_get_dither(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t dither;
    if(XRFdc_GetDither((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        &dither) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetDither in %s failed.", __FUNCTION__);
    }

    if(dither)
    {
        Py_RETURN_TRUE;
    }

    Py_RETURN_FALSE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_DATAPATH_MODE_DOCSTRING[] = "Updates the datapath mode for a DAC channel. "
    "Valid values are "
    "1 (use NCO from 0-Fs/2), "
    "2 (use NCO from 0-Fs/4, implies IMR lowpass), "
    "3 (use NCO from Fs/4-Fs/2, implies IMR highpass), or "
    "4 (disable NCO)";
static PyObject* PyChannel_set_datapath_mode(PyObject* self, PyObject* mode_obj)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t mode;
    if(!PyArg_Parse(mode_obj, "I", &mode))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }
    
    if(XRFdc_SetDataPathMode((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        mode) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetDataPathMode in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_DATAPATH_MODE_DOCSTRING[] = "Retrieves the datapath mode for a DAC channel. "
    "The returned value is an integer whose values correspond to those for set_datapath_mode.";
static PyObject* PyChannel_get_datapath_mode(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t mode;
    if(XRFdc_GetDataPathMode((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        &mode) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetDataPathMode in %s failed.", __FUNCTION__);
    }

    return PyLong_FromLong(mode);

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}


static const char CHANNEL_SET_INTERPOLATION_DOCSTRING[] = "Updates the interpolation setting for a DAC channel. Note that this does not in any way adjust the clocking settings.";
static PyObject* PyChannel_set_interpolation(PyObject* self, PyObject* interpolation_obj)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t interpolation;
    if(!PyArg_Parse(interpolation_obj, "I", &interpolation))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }
    
    if(XRFdc_SetInterpolationFactor((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        interpolation) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetInterpolationFactor in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_INTERPOLATION_DOCSTRING[] = "Retrieves the interpolation setting for a DAC channel.";
static PyObject* PyChannel_get_interpolation(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t interpolation;
    if(XRFdc_GetInterpolationFactor((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        &interpolation) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetInterpolationFactor in %s failed.", __FUNCTION__);
    }

    return PyLong_FromLong(interpolation);

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_DECIMATION_DOCSTRING[] = "Updates the decimation setting for an ADC channel. Note that this does not in any way adjust the clocking settings.";
static PyObject* PyChannel_set_decimation(PyObject* self, PyObject* decimation_obj)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t decimation;
    if(!PyArg_Parse(decimation_obj, "I", &decimation))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }
    
    if(XRFdc_SetDecimationFactor((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        decimation) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetDecimationFactor in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_GET_DECIMATION_DOCSTRING[] = "Retrieves the decimation setting for an ADC channel.";
static PyObject* PyChannel_get_decimation(PyObject* self)
{
    #ifdef __aarch64__

    ChannelObject* self_channel = (ChannelObject*)self;
    uint32_t decimation;
    if(XRFdc_GetDecimationFactor((&xrfdc), 
        self_channel->tile, 
        self_channel->block, 
        &decimation) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_GetDecimationFactor in %s failed.", __FUNCTION__);
    }

    return PyLong_FromLong(decimation);

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_SET_DOCSTRING[] = "Sets parameters of the channel according to keyword. This is equivalent to calling the individual ``set_<x>`` methods on the channel. Any arguments of type ``dict`` will be unpacked into the function call.";
static PyObject* PyChannel_set(PyObject* self, PyObject* const* args, Py_ssize_t nargs, PyObject *kwnames)
{
    #ifdef __aarch64__

    int i;
    PyObject* retval = NULL;
    Py_ssize_t num_kwargs;
    PyObject* kwname_obj;
    const char* kwname = NULL;

    if(nargs != 0)
    {
        return PyErr_Format(PyExc_ValueError, "Positional arguments are not supported in set()");
    }

    if(kwnames == NULL)
    {
        Py_RETURN_NONE;    
    }

    // kwnames is guaranteed to be a tuple of strings
    num_kwargs = PyTuple_GET_SIZE(kwnames);
    for(i = 0; i < num_kwargs; i++)
    {
        kwname_obj = PyTuple_GET_ITEM(kwnames, i);
        if(kwname_obj == NULL)
        {
            return PyErr_Format(PyExc_ValueError, "Unable to retrieve kwarg from tuple", i);
        }

        kwname = PyUnicode_AsUTF8(kwname_obj);
        if(kwname == NULL)
        {
            return PyErr_Format(PyExc_ValueError, "Unable to convert kwarg name into a string for keyword arg %d", i);
        }

        if(strcmp(kwname, "nco_update_event_source") == 0)
        {
            retval = PyChannel_set_nco_update_event_source(self, args[i]);
        }
        else if(strcmp(kwname, "delay") == 0)
        {
            retval = PyChannel_set_delay(self, args[i]);
        }
        else if(strcmp(kwname, "nco_update_event_source") == 0)
        {
            retval = PyChannel_set_nco_update_event_source(self, args[i]);
        }
        else if(strcmp(kwname, "nco_frequency_word") == 0)
        {
            retval = PyChannel_set_nco_frequency_word(self, args[i]);
        }
        else if(strcmp(kwname, "nco_frequency") == 0)
        {
            retval = PyChannel_set_nco_frequency(self, args[i]);
        }
        else if(strcmp(kwname, "nco_phase_word") == 0)
        {
            retval = PyChannel_set_nco_phase_word(self, args[i]);
        }
        else if(strcmp(kwname, "nco_phase") == 0)
        {
            retval = PyChannel_set_nco_phase(self, args[i]);
        }
        else if(strcmp(kwname, "nco_phase_reset") == 0)
        {
            retval = PyChannel_reset_nco_phase(self);
        }
        else if(strcmp(kwname, "vop") == 0)
        {
            retval = PyChannel_set_vop(self, args[i]);
        }
        else if(strcmp(kwname, "dsa") == 0)
        {
            retval = PyChannel_set_dsa(self, args[i]);
        }
        else if(strcmp(kwname, "mix_reconstruction") == 0)
        {
            retval = PyChannel_set_mix_reconstruction(self, args[i]);
        }
        else if(strcmp(kwname, "high_linearity") == 0)
        {
            retval = PyChannel_set_high_linearity_mode(self, args[i]);
        }
        else if(strcmp(kwname, "imr_highpass") == 0)
        {
            retval = PyChannel_set_imr_highpass(self, args[i]);
        }
        else if(strcmp(kwname, "inv_sinc") == 0)
        {
            retval = PyChannel_set_inv_sinc(self, args[i]);
        }
        else if(strcmp(kwname, "dither") == 0)
        {
            retval = PyChannel_set_dither(self, args[i]);
        }
        else if(strcmp(kwname, "datapath_mode") == 0)
        {
            retval = PyChannel_set_datapath_mode(self, args[i]);
        }
        else if(strcmp(kwname, "interpolation") == 0)
        {
            retval = PyChannel_set_interpolation(self, args[i]);
        }
        else if(strcmp(kwname, "decimation") == 0)
        {
            retval = PyChannel_set_decimation(self, args[i]);
        }
        else 
        {
            retval = PyErr_Format(PyExc_ValueError, "Unknown channel parameter %s", kwname);
        }

        if(retval == NULL)
        {
            return retval;
        }
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char CHANNEL_TILE_DOCSTRING[] = "Tile index; valid values are 0-3.";
static const char CHANNEL_BLOCK_DOCSTRING[] = "Block index; valid values are 0-3.";
static const char CHANNEL_IS_DAC_DOCSTRING[] = "Whether or not the channel is a DAC; valid values are ``True`` or ``False``.";
static const char CHANNEL_INTERFACE_WIDTH_BYTES_DOCSTRING[] = "The width in bytes of the interface to the DAC channel presented to the fabric.";
static const char CHANNEL_INTERFACE_SAMPLE_FREQUENCY_DOCSTRING[] = "Interface sample frequency of the channel in Hz.";
static const char CHANNEL_ANALOG_SAMPLE_FREQUENCY_DOCSTRING[] = "Analog sample frequency of the channel in Hz. If the channel is not attached to hardware, this will be 0.";

static PyMemberDef PyChannelMembers[] = {
    {"tile", T_UBYTE, offsetof(ChannelObject, tile), 0, CHANNEL_TILE_DOCSTRING},
    {"block", T_UBYTE, offsetof(ChannelObject, block), 0, CHANNEL_BLOCK_DOCSTRING},
    {"is_dac", T_BOOL, offsetof(ChannelObject, is_dac), 0, CHANNEL_IS_DAC_DOCSTRING},
    {"interface_width_bytes", T_UBYTE, offsetof(ChannelObject, interface_width_bytes), 0, CHANNEL_INTERFACE_WIDTH_BYTES_DOCSTRING},
    {"interface_sample_frequency", T_DOUBLE, offsetof(ChannelObject, interface_sample_frequency), 0, CHANNEL_INTERFACE_SAMPLE_FREQUENCY_DOCSTRING},
    {"analog_sample_frequency", T_DOUBLE, offsetof(ChannelObject, analog_sample_frequency), 0, CHANNEL_ANALOG_SAMPLE_FREQUENCY_DOCSTRING},
    
    {NULL}
};

static PyMethodDef PyChannelMethods[] = {
    {"num", (PyCFunction)PyChannel_num, METH_NOARGS, ""},
    {"status", (PyCFunction)PyChannel_status, METH_NOARGS, CHANNEL_STATUS_DOCSTRING},
    {"load_sample_frequency", (PyCFunction)PyChannel_load_sample_frequency, METH_NOARGS, CHANNEL_LOAD_SAMPLE_FREQUENCY_DOCSTRING},
    {"set_nco_update_event_source", (PyCFunction)PyChannel_set_nco_update_event_source, METH_O, CHANNEL_SET_NCO_UPDATE_EVENT_SOURCE_DOCSTRING},
    {"get_nco_update_event_source", (PyCFunction)PyChannel_get_nco_update_event_source, METH_NOARGS, CHANNEL_GET_NCO_UPDATE_EVENT_SOURCE_DOCSTRING},
    {"set_delay", (PyCFunction)PyChannel_set_delay, METH_O, CHANNEL_SET_DELAY_DOCSTRING},
    {"get_delay", (PyCFunction)PyChannel_get_delay, METH_NOARGS, CHANNEL_GET_DELAY_DOCSTRING},
    {"frequency_to_nco_word", (PyCFunction)PyChannel_frequency_to_nco_word, METH_O, CHANNEL_FREQUENCY_TO_NCO_WORD_DOCSTRING},
    {"set_nco_frequency_word", (PyCFunction)PyChannel_set_nco_frequency_word, METH_O, CHANNEL_SET_NCO_FREQUENCY_WORD_DOCSTRING},
    {"set_nco_frequency", (PyCFunction)PyChannel_set_nco_frequency, METH_O, CHANNEL_SET_NCO_FREQUENCY_DOCSTRING},
    {"get_nco_frequency_word", (PyCFunction)PyChannel_get_nco_frequency_word, METH_NOARGS, CHANNEL_GET_NCO_FREQUENCY_WORD_DOCSTRING},
    {"phase_to_nco_word", (PyCFunction)PyChannel_phase_to_nco_word, METH_O, CHANNEL_PHASE_TO_NCO_WORD_DOCSTRING},
    {"set_nco_phase_word", (PyCFunction)PyChannel_set_nco_phase_word, METH_O, CHANNEL_SET_NCO_PHASE_WORD_DOCSTRING},
    {"set_nco_phase", (PyCFunction)PyChannel_set_nco_phase, METH_O, CHANNEL_SET_NCO_PHASE_DOCSTRING},
    {"get_nco_phase_word", (PyCFunction)PyChannel_get_nco_phase_word, METH_NOARGS, CHANNEL_GET_NCO_PHASE_WORD_DOCSTRING},
    {"reset_nco_phase", (PyCFunction)PyChannel_reset_nco_phase, METH_NOARGS, CHANNEL_RESET_NCO_PHASE_DOCSTRING},
    {"trigger_nco_update_event", (PyCFunction)PyChannel_trigger_nco_update_event, METH_NOARGS, CHANNEL_TRIGGER_NCO_UPDATE_EVENT_DOCSTRING},
    {"set_vop", (PyCFunction)PyChannel_set_vop, METH_O, CHANNEL_SET_VOP_DOCSTRING},
    {"get_vop", (PyCFunction)PyChannel_get_vop, METH_NOARGS, CHANNEL_GET_VOP_DOCSTRING},
    {"set_dsa", (PyCFunction)PyChannel_set_dsa, METH_O, CHANNEL_SET_DSA_DOCSTRING},
    {"get_dsa", (PyCFunction)PyChannel_get_dsa, METH_NOARGS, CHANNEL_GET_DSA_DOCSTRING},
    {"set_mix_reconstruction", (PyCFunction)PyChannel_set_mix_reconstruction, METH_O, CHANNEL_SET_MIX_RECONSTRUCTION_DOCSTRING},
    {"get_mix_reconstruction", (PyCFunction)PyChannel_get_mix_reconstruction, METH_NOARGS, CHANNEL_GET_MIX_RECONSTRUCTION_DOCSTRING},
    {"set_high_linearity_mode", (PyCFunction)PyChannel_set_high_linearity_mode, METH_O, CHANNEL_SET_HIGH_LINEARITY_MODE_DOCSTRING},
    {"get_high_linearity_mode", (PyCFunction)PyChannel_get_high_linearity_mode, METH_NOARGS, CHANNEL_GET_HIGH_LINEARITY_MODE_DOCSTRING},
    {"set_imr_highpass", (PyCFunction)PyChannel_set_imr_highpass, METH_O, CHANNEL_SET_IMR_HIGHPASS_DOCSTRING},
    {"get_imr_highpass", (PyCFunction)PyChannel_get_imr_highpass, METH_NOARGS, CHANNEL_GET_IMR_HIGHPASS_DOCSTRING},
    {"set_inv_sinc", (PyCFunction)PyChannel_set_inv_sinc, METH_O, CHANNEL_SET_INV_SINC_DOCSTRING},
    {"get_inv_sinc", (PyCFunction)PyChannel_get_inv_sinc, METH_NOARGS, CHANNEL_GET_INV_SINC_DOCSTRING},
    {"set_dither", (PyCFunction)PyChannel_set_dither, METH_O, CHANNEL_SET_DITHER_DOCSTRING},
    {"get_dither", (PyCFunction)PyChannel_get_dither, METH_NOARGS, CHANNEL_GET_DITHER_DOCSTRING},
    {"set_datapath_mode", (PyCFunction)PyChannel_set_datapath_mode, METH_O, CHANNEL_SET_DATAPATH_MODE_DOCSTRING},
    {"get_datapath_mode", (PyCFunction)PyChannel_get_datapath_mode, METH_NOARGS, CHANNEL_GET_DATAPATH_MODE_DOCSTRING},
    {"set_interpolation", (PyCFunction)PyChannel_set_interpolation, METH_O, CHANNEL_SET_INTERPOLATION_DOCSTRING},
    {"get_interpolation", (PyCFunction)PyChannel_get_interpolation, METH_NOARGS, CHANNEL_GET_INTERPOLATION_DOCSTRING},
    {"set_decimation", (PyCFunction)PyChannel_set_decimation, METH_O, CHANNEL_SET_DECIMATION_DOCSTRING},
    {"get_decimation", (PyCFunction)PyChannel_get_decimation, METH_NOARGS, CHANNEL_GET_DECIMATION_DOCSTRING},
    {"set", (PyCFunction)PyChannel_set, METH_FASTCALL | METH_KEYWORDS, CHANNEL_SET_DOCSTRING},
    {NULL, NULL, 0, NULL}
};

static const char CHANNEL_DOCSTRING[] = "An abstraction class for RF channels of the ZU49DR and associated methods.";
static PyTypeObject ChannelTypeObject = {
    .ob_base = PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "acadia.rfdc.Channel",
    .tp_doc = CHANNEL_DOCSTRING,
    .tp_basicsize = sizeof(ChannelObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
    .tp_init = PyChannel_init,
    .tp_str = PyChannel_str,
    .tp_members = PyChannelMembers,
    .tp_methods = PyChannelMethods
};

static const char RFDC_ATTACH_DOCSTRING[] = "Attach to the hardware and initialize all relevant structures. This will throw an error if called on a machine not running on the RFSoC PS.";
static PyObject* PyRfdc_attach(PyObject* unused, PyObject* unused2)
{
    // Initialize and attach to hardware
    #ifdef __aarch64__

    // Initialize libmetal
    struct metal_init_params init_param = METAL_INIT_DEFAULTS; 
    init_param.log_level = METAL_LOG_INFO; 
    u32 retval = metal_init(&init_param); 

    // Get the RFDC configuration
    XRFdc_Config* cfg = XRFdc_LookupConfig(0);
    if(cfg == NULL)
    {
        PyErr_SetString(PyExc_ValueError, "Unable to lookup RFDC config.");
        return NULL;
    }

    // Register the struct with libmetal
    if(XRFdc_RegisterMetal(&xrfdc, 0, &metal) != XRFDC_SUCCESS)
    {
        PyErr_SetString(PyExc_ValueError, "Unable to register XRFDC structure with libmetal.");
        return NULL;
    }

    if(XRFdc_CfgInitialize(&xrfdc, cfg) != XRFDC_SUCCESS)
    {
        PyErr_SetString(PyExc_ValueError, "Unable to initialize RFDC library with provided configuration.");
        return NULL;
    }

    Py_RETURN_NONE;

    #else

    return RFDC_WRONG_HARDWARE_EXCEPTION;

    #endif
}

static const char RFDC_STATUS_DOCSTRING[] = "Retrieve the status of the RFDC driver.";
static PyObject* PyRfdc_status(PyObject* unused)
{
    #ifdef __aarch64__

    XRFdc_IPStatus status;
    XRFdc_TileStatus* tile_status;
    PyObject* full = NULL;
    PyObject* d = NULL;
    PyObject* key;
    PyObject* value;
    uint32_t tile;

    if(XRFdc_GetIPStatus((&xrfdc), &status) != XRFDC_SUCCESS)
    {
        PyErr_SetString(PyExc_ValueError, "Unable to get RFDC IP status.");
        return NULL;
    }

    full = PyDict_New();

    // Add DAC tiles
    for(tile = 0; tile < 4; tile++)
    {
        tile_status = &(status.DACTileStatus[tile]);
        d = PyDict_New();

        key = PyUnicode_FromString("enabled");
        value = PyBool_FromLong(tile_status->IsEnabled);
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("tile_state");
        value = PyLong_FromLong(tile_status->TileState);
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("block_status_mask");
        value = PyLong_FromLong((long)(tile_status->BlockStatusMask));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);
        
        key = PyUnicode_FromString("powerup_state");
        value = PyLong_FromLong((long)(tile_status->PowerUpState));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("pll_state");
        value = PyLong_FromLong((long)(tile_status->PLLState));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromFormat("DACTile%d", tile);
        PyDict_SetItem(full, key, d);
        Py_DECREF(key);
        Py_DECREF(d);
    }

    // Add ADC tiles
    for(tile = 0; tile < 4; tile++)
    {
        tile_status = &(status.ADCTileStatus[tile]);
        d = PyDict_New();

        key = PyUnicode_FromString("enabled");
        value = PyBool_FromLong(tile_status->IsEnabled);
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("tile_state");
        value = PyLong_FromLong(tile_status->TileState);
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("block_status_mask");
        value = PyLong_FromLong((long)(tile_status->BlockStatusMask));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);
        
        key = PyUnicode_FromString("powerup_state");
        value = PyLong_FromLong((long)(tile_status->PowerUpState));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromString("pll_state");
        value = PyLong_FromLong((long)(tile_status->PLLState));
        PyDict_SetItem(d, key, value);
        Py_DECREF(key);
        Py_DECREF(value);

        key = PyUnicode_FromFormat("ADCTile%d", tile);
        PyDict_SetItem(full, key, d);
        Py_DECREF(key);
        Py_DECREF(d);
    }

    return full;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFDC_STARTUP_DOCSTRING[] = "Reset all tiles without clearing the register settings.";
static PyObject* PyRfdc_startup(PyObject* self)
{
    #ifdef __aarch64__

    if(XRFdc_StartUp((&xrfdc), 0, -1) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_StartUp for ADCs in %s failed.", __FUNCTION__);
    }

    if(XRFdc_StartUp((&xrfdc), 1, -1) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_StartUp for DACs in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFDC_RESET_DOCSTRING[] = "Reset all tiles back to the configuration contained in the firmware image.";
static PyObject* PyRfdc_reset(PyObject* self)
{
    #ifdef __aarch64__
    
    if(XRFdc_Reset((&xrfdc), 0, -1) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_Reset for ADCs in %s failed.", __FUNCTION__);
    }

    if(XRFdc_Reset((&xrfdc), 1, -1) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_Reset for DACs in %s failed.", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFDC_GET_CLOCK_DISTRIBUTION_DOCSTRING[] = "Retrieve clock distribution settings for the RFDC system.";
static PyObject* PyRfdc_get_clock_distribution(PyObject* unused)
{
    #ifdef __aarch64__

    PyObject* distributions = PyList_New(0);
    PyObject* d = NULL;
    int i;
    int type;
    int tile;
    XRFdc_Tile_Clock_Settings* clock_settings;
    XRFdc_Distribution_Settings* distribution = NULL;
    XRFdc_Distribution_System_Settings DistributionSystem;

    PyObject* key;
    PyObject* value;

    XRFdc_GetClkDistribution((&xrfdc), &DistributionSystem);
    for(i = 0; i < 8; i++)
    {
        distribution = &(DistributionSystem.Distributions[i]);
        if(distribution->SourceTileId != XRFDC_CLK_DST_INVALID)
        {
            d = PyDict_New();

            key = PyUnicode_FromString("source_tile");
            value = PyUnicode_FromFormat("%s%lu", (distribution->SourceType == 0 ? "ADCTile" : "DACTile"), distribution->SourceTileId);
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("edge_tile0");
            value = PyUnicode_FromFormat("%s%lu", (distribution->EdgeTypes[0] == 0 ? "ADCTile" : "DACTile"), distribution->EdgeTileIds[0]);
            PyDict_SetItem(d, key, value); 
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("edge_tile1");
            value = PyUnicode_FromFormat("%s%lu", (distribution->EdgeTypes[1] == 0 ? "ADCTile" : "DACTile"), distribution->EdgeTileIds[1]);
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("dist_ref_clk_freq");
            value = PyFloat_FromDouble(distribution->DistRefClkFreq);
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("distributed_clock");
            value = PyLong_FromLong(distribution->DistributedClock);
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("shutdown_mode");
            value = PyLong_FromLong(distribution->ShutdownMode);
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("max_delay");
            value = PyLong_FromLong((long)((distribution->Info).MaxDelay));
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("min_delay");
            value = PyLong_FromLong((long)((distribution->Info).MinDelay));
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("is_delay_balanced");
            value = PyBool_FromLong((long)((distribution->Info).IsDelayBalanced));
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("source");
            value = PyLong_FromLong((long)((distribution->Info).Source));
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("upper_bound");
            value = PyLong_FromLong((long)((distribution->Info).UpperBound));
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            key = PyUnicode_FromString("lower_bound");
            value = PyLong_FromLong((long)((distribution->Info).LowerBound));
            PyDict_SetItem(d, key, value);
            Py_DECREF(key);
            Py_DECREF(value);

            for(type = 0; type < 2; type++)
            {
                for(tile = 0; tile < 4; tile++)
                {
                    if(distribution->SampleRates[type][tile] != 0)
                    {
                        key = PyUnicode_FromFormat("%s%lu_sample_rate", (type == 0 ? "ADCTile" : "DACTile"), tile);
                        value = PyFloat_FromDouble(distribution->SampleRates[type][tile]);
                        PyDict_SetItem(d, key, value);
                        Py_DECREF(key);
                        Py_DECREF(value);       

                        clock_settings = &((distribution->Info).ClkSettings[type][tile]);

                        key = PyUnicode_FromFormat("%s%lu_source_tile", (type == 0 ? "ADCTile" : "DACTile"), tile);
                        value = PyUnicode_FromFormat("%s%lu", (clock_settings->SourceType == 0 ? "ADCTile" : "DACTile"), clock_settings->SourceTile);
                        PyDict_SetItem(d, key, value);
                        Py_DECREF(key);
                        Py_DECREF(value);  

                        key = PyUnicode_FromFormat("%s%lu_pll_enable", (type == 0 ? "ADCTile" : "DACTile"), tile);
                        value = PyBool_FromLong((long)(clock_settings->PLLEnable));
                        PyDict_SetItem(d, key, value);
                        Py_DECREF(key);
                        Py_DECREF(value);  

                        key = PyUnicode_FromFormat("%s%lu_ref_clk_freq", (type == 0 ? "ADCTile" : "DACTile"), tile);
                        value = PyFloat_FromDouble(clock_settings->RefClkFreq);
                        PyDict_SetItem(d, key, value);
                        Py_DECREF(key);
                        Py_DECREF(value);  

                        key = PyUnicode_FromFormat("%s%lu_sample_rate", (type == 0 ? "ADCTile" : "DACTile"), tile);
                        value = PyFloat_FromDouble(clock_settings->SampleRate);
                        PyDict_SetItem(d, key, value);
                        Py_DECREF(key);
                        Py_DECREF(value); 

                        key = PyUnicode_FromFormat("%s%lu_division_factor", (type == 0 ? "ADCTile" : "DACTile"), tile);
                        value = PyLong_FromLong((long)(clock_settings->DivisionFactor));
                        PyDict_SetItem(d, key, value);
                        Py_DECREF(key);
                        Py_DECREF(value); 

                        key = PyUnicode_FromFormat("%s%lu_delay", (type == 0 ? "ADCTile" : "DACTile"), tile);
                        value = PyLong_FromLong((long)(clock_settings->Delay));
                        PyDict_SetItem(d, key, value);
                        Py_DECREF(key);
                        Py_DECREF(value); 

                        key = PyUnicode_FromFormat("%s%lu_distributed_clock", (type == 0 ? "ADCTile" : "DACTile"), tile);
                        value = PyLong_FromLong((long)(clock_settings->DistributedClock));
                        PyDict_SetItem(d, key, value);
                        Py_DECREF(key);
                        Py_DECREF(value); 
                    }
                }
            }

            PyList_Append(distributions, d);  
            Py_DECREF(d);
            d = NULL;         
        }
    }
	    
	return distributions;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

// This has directly been adapted from XRFdc_GetClkDistribution, but slimmed down
static const char RFDC_SET_CLOCK_DISTRIBUTION_DOCSTRING[] = "Create a clock distribution in the RFDC system.\n"
    "For the source tile and the edge tiles, the tile ID (0-3) must be provided along with whether or not the tile is a DAC. "
    "The distributed reference clock must be provided in Hz."
    "The parameter distributed_clock indicates which clock the source tile will distribute and must be 0 (none), 1 (the received reference clock), or 2 (a full-rate clock from the internal divider)."
    "Sample rates for tiles not included in this distribution do not need to be provided.";
static PyObject* PyRfdc_set_clock_distribution(PyObject* self, PyObject* args, PyObject* kwargs)
{
    #ifdef __aarch64__

    XRFdc_Distribution_Settings distribution;
    for(int i = 0; i < 2; i++)
    {
        for(int j = 0; j < 4; j++)
        {
            distribution.SampleRates[i][j] = 0.0;
        }
    }
    distribution.ShutdownMode = 0;

    static char* kwlist[] = {"source_tile_is_dac", "source_tile_id", 
        "edge_tile0_is_dac", "edge_tile0_id",
        "edge_tile1_is_dac", "edge_tile1_id", 
        "dist_ref_clk_freq", 
        "distributed_clock",
        "ADCTile0_sample_rate",
        "ADCTile1_sample_rate",
        "ADCTile2_sample_rate",
        "ADCTile3_sample_rate",
        "DACTile0_sample_rate",
        "DACTile1_sample_rate",
        "DACTile2_sample_rate",
        "DACTile3_sample_rate",
        "shutdown",
        NULL};

    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "IIIIIIdd|ddddddddI", kwlist, 
        &(distribution.SourceType), 
        &(distribution.SourceTileId), 
        &(distribution.EdgeTypes[0]),
        &(distribution.EdgeTileIds[0]),
        &(distribution.EdgeTypes[1]),
        &(distribution.EdgeTileIds[1]),
        &(distribution.DistRefClkFreq),
        &(distribution.DistributedClock),
        &(distribution.SampleRates[0][0]),
        &(distribution.SampleRates[0][1]),
        &(distribution.SampleRates[0][2]),
        &(distribution.SampleRates[0][3]),
        &(distribution.SampleRates[1][0]),
        &(distribution.SampleRates[1][1]),
        &(distribution.SampleRates[1][2]),
        &(distribution.SampleRates[1][3]),
        &(distribution.ShutdownMode)))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    if(XRFdc_SetClkDistribution((&xrfdc), &distribution) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_SetClkDistribution failed in %s", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFDC_SET_SYSREF_ENABLED_DOCSTRING[] = "Enables or disables SYSREF detection for the RFDC system.";
static PyObject* PyRfdc_set_sysref_enabled(PyObject* self, PyObject* en)
{
    #ifdef __aarch64__

    unsigned int enabled;
    if(!PyArg_Parse(en, "I", &enabled))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    if(!XRFdc_MTS_Sysref_Config((&xrfdc), &dac_mts_config, &adc_mts_config, enabled))
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_MTS_Sysref_Config failed in %s", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFDC_DYNAMIC_PLL_CONFIG_DOCSTRING[] = "Reconfigures the settings of the RF tile PLL.\n"
    ":param tile: Tile to configure. Valid options are 'ADCTilex' or 'DACTilex', where 'x' can be 0-3.\n"
    ":param external_clock: If True, indicates that the PLL should be disabled and that the tile should use an external sampling clock.\n"
    ":param reference_frequency: Frequency in Hz of the reference clock input to the tile.\n"
    ":param sample_frequency: Desired sample frequency in Hz for the tile.\n";
static PyObject* PyRfdc_dynamic_pll_config(PyObject* self, PyObject* args, PyObject* kwargs)
{
    #ifdef __aarch64__

    const char* tile;
    int external_clock;
    double reference_frequency;
    double sample_frequency;

    unsigned int tile_type;
    unsigned int tile_id;

    static char* kwlist[] = {"tile", "external_clock", "reference_frequency", "sample_frequency", NULL};
    if(!PyArg_ParseTupleAndKeywords(args, kwargs, "spdd", kwlist, 
        &tile, 
        &external_clock, 
        &reference_frequency,
        &sample_frequency))
    {
        return PyErr_Format(PyExc_ValueError, "Unable to parse arguments in %s", __FUNCTION__);
    }

    if((strcmp(tile, "ADCTile0") == 0) || (strcmp(tile, "ADCTile1") == 0) || (strcmp(tile, "ADCTile2") == 0) || (strcmp(tile, "ADCTile3") == 0))
    {
        tile_type = XRFDC_ADC_TILE;
    }
    else if((strcmp(tile, "DACTile0") == 0) || (strcmp(tile, "DACTile1") == 0) || (strcmp(tile, "DACTile2") == 0) || (strcmp(tile, "DACTile3") == 0))
    {
        tile_type = XRFDC_DAC_TILE;
    }
    else 
    {
        return PyErr_Format(PyExc_ValueError, "Invalid tile specification %s", tile);
    }

    tile_id = tile[7] - '0';

    if(XRFdc_DynamicPLLConfig(
        (&xrfdc), 
        tile_type, 
        tile_id, 
        (external_clock ? XRFDC_EXTERNAL_CLK : XRFDC_INTERNAL_PLL_CLK),
        reference_frequency / 1e6,
        sample_frequency / 1e6) != XRFDC_SUCCESS)
    {
        return PyErr_Format(PyExc_ValueError, "Call to XRFdc_DynamicPLLConfig failed in %s", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFDC_MTS_INIT_DOCSTRING[] = "Initializes multi-tile synchronization (MTS).";
static PyObject* PyRfdc_mts_init(PyObject* self)
{
    #ifdef __aarch64__

    if(XRFdc_MultiConverter_Init(&dac_mts_config, NULL, NULL, 0) != XRFDC_MTS_OK)
    {
        return PyErr_Format(PyExc_ValueError, "Unable to initialize MTS for DAC in %s", __FUNCTION__);
    }

    if(XRFdc_MultiConverter_Init(&adc_mts_config, NULL, NULL, 0) != XRFDC_MTS_OK)
    {
        return PyErr_Format(PyExc_ValueError, "Unable to initialize MTS for ADC in %s", __FUNCTION__);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static const char RFDC_MTS_SYNC_DOCSTRING[] = "Carries out multi-tile synchronization (MTS).";
static PyObject* PyRfdc_mts_sync(PyObject* self)
{
    #ifdef __aarch64__

    uint32_t retval;
    uint32_t tile;
    int latency;

    adc_mts_config.RefTile = 0;
    adc_mts_config.Tiles = 0xF;
    adc_mts_config.Target_Latency = -1;
    adc_mts_config.SysRef_Enable = 1;

    // First run for the ADC
    retval = XRFdc_MultiConverter_Sync((&xrfdc), XRFDC_ADC_TILE, &adc_mts_config);
    if(retval != XRFDC_MTS_OK)
    {
        return PyErr_Format(PyExc_ValueError, "Unable to synchronize ADCs (pre) with MTS in %s (retval %d)", __FUNCTION__, retval);
    }

    // Get the maximum latency
    latency = 0;
    for(tile = 0; tile < 4; tile++)
    {
        if(adc_mts_config.Latency[tile] > latency)
        {
            latency = adc_mts_config.Latency[tile];
        }
    }

    // Run the sync again but with a higher target latency to ensure that the calibration converged
    adc_mts_config.Target_Latency = 16 + latency;
    retval = XRFdc_MultiConverter_Sync((&xrfdc), XRFDC_ADC_TILE, &adc_mts_config);
    if(retval != XRFDC_MTS_OK)
    {
        return PyErr_Format(PyExc_ValueError, "Unable to synchronize ADCs (post) with MTS in %s (retval %d)", __FUNCTION__, retval);
    }

    dac_mts_config.RefTile = 0;
    dac_mts_config.Tiles = 0xF;
    dac_mts_config.Target_Latency = -1;
    dac_mts_config.SysRef_Enable = 1;

    // First run for the DAC
    retval = XRFdc_MultiConverter_Sync((&xrfdc), XRFDC_DAC_TILE, &dac_mts_config);
    if(retval != XRFDC_MTS_OK)
    {
        return PyErr_Format(PyExc_ValueError, "Unable to synchronize DACs (pre) with MTS in %s (retval %d)", __FUNCTION__, retval);
    }

    // Get the maximum latency
    latency = 0;
    for(tile = 0; tile < 4; tile++)
    {
        if(dac_mts_config.Latency[tile] > latency)
        {
            latency = dac_mts_config.Latency[tile];
        }
    }

    // Run the sync again but with a higher target latency to ensure that the calibration converged
    dac_mts_config.Target_Latency = 16 + latency;
    retval = XRFdc_MultiConverter_Sync((&xrfdc), XRFDC_DAC_TILE, &dac_mts_config);
    if(retval != XRFDC_MTS_OK)
    {
        return PyErr_Format(PyExc_ValueError, "Unable to synchronize DACs (post) with MTS in %s (retval %d)", __FUNCTION__, retval);
    }

    Py_RETURN_NONE;

    #else
    return RFDC_WRONG_HARDWARE_EXCEPTION;
    #endif
}

static PyMethodDef PyRfdcMethods[] = {
    {"attach", (PyCFunction)PyRfdc_attach, METH_NOARGS, RFDC_ATTACH_DOCSTRING},
    {"status", (PyCFunction)PyRfdc_status, METH_NOARGS, RFDC_STATUS_DOCSTRING},
    {"startup", (PyCFunction)PyRfdc_startup, METH_NOARGS, RFDC_STARTUP_DOCSTRING},
    {"reset", (PyCFunction)PyRfdc_reset, METH_NOARGS, RFDC_RESET_DOCSTRING},
    {"get_clock_distribution", (PyCFunction)PyRfdc_get_clock_distribution, METH_NOARGS, RFDC_GET_CLOCK_DISTRIBUTION_DOCSTRING},
    {"set_clock_distribution", (PyCFunction)PyRfdc_set_clock_distribution, METH_KEYWORDS | METH_VARARGS, RFDC_SET_CLOCK_DISTRIBUTION_DOCSTRING},
    {"set_sysref_enabled", (PyCFunction)PyRfdc_set_sysref_enabled, METH_O, RFDC_SET_SYSREF_ENABLED_DOCSTRING},
    {"dynamic_pll_config", (PyCFunction)PyRfdc_dynamic_pll_config, METH_KEYWORDS | METH_VARARGS, RFDC_DYNAMIC_PLL_CONFIG_DOCSTRING},
    {"mts_init", (PyCFunction)PyRfdc_mts_init, METH_NOARGS, RFDC_MTS_INIT_DOCSTRING},
    {"mts_sync", (PyCFunction)PyRfdc_mts_sync, METH_NOARGS, RFDC_MTS_SYNC_DOCSTRING},
    {NULL, NULL, 0, NULL}
};

static const char RFDC_DOCSTRING[] = "A Python interface to the RFDC for the ZCU216.";
static struct PyModuleDef PyRfdc_module = {
    PyModuleDef_HEAD_INIT,
    "acadia.rfdc",  
    RFDC_DOCSTRING,
    -1,
    PyRfdcMethods
};

PyMODINIT_FUNC
PyInit_rfdc(void)
{
    PyObject *module;

    if (PyType_Ready(&ChannelTypeObject) < 0)
    {
        return NULL;
    }

    // Create the module
    module = PyModule_Create(&PyRfdc_module);
    if (module == NULL) 
    {
        return NULL;
    }

    // Add Channel
    Py_INCREF(&ChannelTypeObject);
    if (PyModule_AddObject(module, "Channel", (PyObject*)&ChannelTypeObject) < 0) 
    {
        Py_DECREF(&ChannelTypeObject);
        Py_DECREF(module);
        return NULL;
    }
    
    return module;
}
