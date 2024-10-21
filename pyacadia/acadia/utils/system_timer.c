#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "system_timer.h"

void timer_enable(volatile uint32_t* mem, int enabled) {
    *(mem + (0x0 / sizeof(uint32_t))) = enabled;
}

uint64_t timer_value(volatile uint32_t* mem)
{
    volatile unsigned long cnt_h;
    volatile unsigned long cnt_h2;
    volatile unsigned long cnt_l;
	// asm volatile("isb"); // TODO: For some reason this causes a kernel crash saying that ISB is an invalid instruction, but this makes no sense since we're definitely on aarch64
	
    cnt_h = *(mem + (0xC / sizeof(uint32_t)));
    cnt_l = *(mem + (0x8 / sizeof(uint32_t)));
    cnt_h2 = *(mem + (0xC / sizeof(uint32_t)));

    // Check whether the upper 32 bits changed while we were reading the 
    // lower bits, in which case we need to reread the lower value
    if(cnt_h != cnt_h2)
    {
        cnt_l = *(mem + (0x8 / sizeof(uint32_t)));
        cnt_h = cnt_h2;
    }

    return (cnt_h << 32) | cnt_l;
}

uint32_t timer_frequency(volatile uint32_t* mem)
{
    return *(mem + (0x20 / sizeof(uint32_t)));
}
