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

typedef struct {
    int mem_fd;
    volatile uint32_t* gpio_mem; 
    volatile uint32_t* cache_mem; 
    volatile uint32_t* barrier_cache_mem; 
} module_state_t;

static PyObject* py_attach(PyObject* self, PyObject* arg) {
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

static PyObject* py_detach(PyObject* self, PyObject* arg) {
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

// void to_samples(
//     float* input,
//     int16_t* output,
//     uint32_t n,
//     float scale
// ) {
//     float total_scale = scale*(1 << 15);
//     for(uint32_t i = 0; i < n; i++) {
//         output[i] = round(input[i] * total_scale);
//     }
// }

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

// def next_highest_power_of_2(num, log=False):
//     """
//     Given an unsigned integer ``num``, returns the smallest power of 2 greater 
//     than or equal to ``num``. Optionally, it can return the base-2 log of this
//     number instead, representing the number of bits needed to store ``num``.

//     :param num: Search limit
//     :type num: int
//     :param log: If ``True``, returns the base-2 log of the integer.
//     """
//     i = 0
//     while (1 << i) < num:
//         i += 1
//     return (i if log else (1 << i))

// void to_samples_simd(
//     float* input,
//     int16_t* output,
//     uint32_t n,
//     float scale
// ) {
//     float32x4_t s_in;
//     int16x4_t s_out; 
//     float total_scale = scale*(1 << 15);

//     for(uint32_t i = 0; i < n; i += 4) {
//         s_in = vld1q_f32(input + i); // Load
//         s_in = vmulq_n_f32(s_in, total_scale); // Multiply
//         s_in = vrndnq_f32(s_in); // Round
//         s_out = vqmovn_s32(vcvtq_s32_f32(s_in)); // Convert to int16
//         vst1_s16(output + i, s_out); // Store
//     }
// }

// void to_samples_simd_batched(
//     float* input,
//     int16_t* output,
//     uint32_t n,
//     float scale
// ) {
//     float32x4_t s_in0, s_in1, s_in2, s_in3, s_in4, s_in5, s_in6, s_in7;
//     int16x4_t s_out0, s_out1, s_out2, s_out3, s_out4, s_out5, s_out6, s_out7; 
//     float total_scale = scale*(1 << 15);

//     for(uint32_t i = 0; i < n; i += 4*8) {
//         // Load
//         s_in0 = vld1q_f32(input + i);
//         s_in1 = vld1q_f32(input + i + 4);
//         s_in2 = vld1q_f32(input + i + 8);
//         s_in3 = vld1q_f32(input + i + 12);
//         s_in4 = vld1q_f32(input + i + 16);
//         s_in5 = vld1q_f32(input + i + 20);
//         s_in6 = vld1q_f32(input + i + 24); 
//         s_in7 = vld1q_f32(input + i + 28);
        
//         // Multiply
//         s_in0 = vmulq_n_f32(s_in0, total_scale);
//         s_in1 = vmulq_n_f32(s_in1, total_scale);
//         s_in2 = vmulq_n_f32(s_in2, total_scale);
//         s_in3 = vmulq_n_f32(s_in3, total_scale);
//         s_in4 = vmulq_n_f32(s_in4, total_scale);
//         s_in5 = vmulq_n_f32(s_in5, total_scale);
//         s_in6 = vmulq_n_f32(s_in6, total_scale);
//         s_in7 = vmulq_n_f32(s_in7, total_scale);
        
//         // Round
//         s_in0 = vrndnq_f32(s_in0);
//         s_in1 = vrndnq_f32(s_in1);
//         s_in2 = vrndnq_f32(s_in2);
//         s_in3 = vrndnq_f32(s_in3);
//         s_in4 = vrndnq_f32(s_in4);
//         s_in5 = vrndnq_f32(s_in5);
//         s_in6 = vrndnq_f32(s_in6);
//         s_in7 = vrndnq_f32(s_in7);

//         // Convert to int16
//         s_out0 = vqmovn_s32(vcvtq_s32_f32(s_in0));
//         s_out1 = vqmovn_s32(vcvtq_s32_f32(s_in1));
//         s_out2 = vqmovn_s32(vcvtq_s32_f32(s_in2));
//         s_out3 = vqmovn_s32(vcvtq_s32_f32(s_in3));
//         s_out4 = vqmovn_s32(vcvtq_s32_f32(s_in4));
//         s_out5 = vqmovn_s32(vcvtq_s32_f32(s_in5));
//         s_out6 = vqmovn_s32(vcvtq_s32_f32(s_in6));
//         s_out7 = vqmovn_s32(vcvtq_s32_f32(s_in7));

//         // Store
//         vst1_s16(output + i, s_out0);
//         vst1_s16(output + i + 4, s_out1);
//         vst1_s16(output + i + 8, s_out2);
//         vst1_s16(output + i + 12, s_out3);
//         vst1_s16(output + i + 16, s_out4);
//         vst1_s16(output + i + 20, s_out5);
//         vst1_s16(output + i + 24, s_out6);
//         vst1_s16(output + i + 28, s_out7); 
//     }
// }

static PyObject* py_timer_frequency(PyObject* self, PyObject* arg) {
    #ifdef __aarch64__
    // https://github.com/Xilinx/u-boot-xlnx/blob/master/arch/arm/cpu/armv8/generic_timer.c
	unsigned long cntfrq;
	asm volatile("mrs %0, cntfrq_el0" : "=r" (cntfrq));
    return PyLong_FromUnsignedLong(cntfrq);
    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_timer_value(PyObject* self, PyObject* arg) {
    #ifdef __aarch64__
    unsigned long cntpct;
	// asm volatile("isb"); // TODO: For some reason this causes a kernel crash saying that ISB is an invalid instruction, but this makes no sense since we're definitely on aarch64
	asm volatile("mrs %0, cntpct_el0" : "=r" (cntpct));
    return PyLong_FromUnsignedLong(cntpct);
    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_halt_and_reset(PyObject* self, PyObject* arg) {
    #ifdef __aarch64__
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    // Unmask and clear GPIO 89 and 90
    const uint32_t mask = (1 << 9) | (1 << 10);
    const uint32_t data = (~mask) << 16;
    volatile uint32_t* mask_data5_msw = (volatile uint32_t*)(state->gpio_mem + (0x2C >> 2));
    *mask_data5_msw = data;
    Py_RETURN_NONE;
    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_run(PyObject* self, PyObject* arg) {
    #ifdef __aarch64__
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    const uint32_t mask = (1 << 9) | (1 << 10);
    const uint32_t data = ((~mask) << 16) | mask;
    volatile uint32_t* mask_data5_msw = (volatile uint32_t*)(state->gpio_mem + (0x2C >> 2));
    *mask_data5_msw = data;
    Py_RETURN_NONE;
    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_done(PyObject* self, PyObject* arg) {
    #ifdef __aarch64__
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    // Read GPIO 64
    volatile uint32_t* data5_ro = (volatile uint32_t*)(state->gpio_mem + (0x74 >> 2));
    uint8_t done = (uint8_t)(*data5_ro & 0x1);
    return PyBool_FromLong((long)done);
    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_complete(PyObject* self, PyObject* arg) {
    #ifdef __aarch64__
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    // Wait until the sequencer is finished
    // Block until GPIO 64 is set
    volatile uint32_t* data5_ro = (volatile uint32_t*)(state->gpio_mem + (0x74 >> 2));
    while(~(*data5_ro) & 0x1);
    Py_RETURN_NONE;
    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyObject* py_sequencer_mem_barrier(PyObject* self, PyObject* arg) {
    #ifdef __aarch64__
    module_state_t* state = (module_state_t*)PyModule_GetState(self);
    // Set the value of the memory equal to a constant and wait for it to change
    *(state->barrier_cache_mem) = 0xBEEBB00A;
    while(*(state->barrier_cache_mem) == 0xBEEBB00A);
    Py_RETURN_NONE;
    #else
    return PyErr_Format(PyExc_SystemError, "Function %s may only be called on RFSoC hardware.", __FUNCTION__);
    #endif
}

static PyMethodDef UtilsMethods[] = {
  {"attach",                   (PyCFunction)py_attach, METH_NOARGS, "Map memory for interacting with the hardware."},
  {"detach",                   (PyCFunction)py_detach, METH_NOARGS, "Unmap hardware memory."},
  {"next_highest_power_of_2",  (PyCFunction)py_next_highest_power_of_2, METH_VARARGS | METH_KEYWORDS, "Given a number, find the next highest power of 2."},
  {"timer_frequency",          (PyCFunction)py_timer_frequency, METH_NOARGS, "Read timer frequency in Hz."},
  {"timer_value",              (PyCFunction)py_timer_value, METH_NOARGS, "Read timer value."},
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
