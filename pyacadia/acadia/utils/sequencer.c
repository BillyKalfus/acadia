#include "sequencer.h"

void sequencer_halt_and_reset(volatile uint32_t* mem) {
    // Unmask and clear GPIO 89 and 90
    const uint32_t mask = (1 << 9) | (1 << 10);
    const uint32_t data = (~mask) << 16;
    volatile uint32_t* mask_data5_msw = (volatile uint32_t*)(mem + (0x2C >> 2));
    *mask_data5_msw = data;
}

void sequencer_run(volatile uint32_t* mem) {
    const uint32_t mask = (1 << 9) | (1 << 10);
    const uint32_t data = ((~mask) << 16) | mask;
    volatile uint32_t* mask_data5_msw = (volatile uint32_t*)(mem + (0x2C >> 2));
    *mask_data5_msw = data;
}

uint8_t sequencer_done(volatile uint32_t* mem) {
    // Read GPIO 64
    volatile uint32_t* data5_ro = (volatile uint32_t*)(mem + (0x74 >> 2));
    return (uint8_t)(*data5_ro & 0x1);    
}

void sequencer_complete(volatile uint32_t* mem) {
    // Wait until the sequencer is finished
    // Block until GPIO 64 is set
    volatile uint32_t* data5_ro = (volatile uint32_t*)(mem + (0x74 >> 2));
    while(~(*data5_ro) & 0x1);
}

void sequencer_mem_barrier(volatile uint32_t* mem) {
    // Set the value of the memory equal to a constant and wait for it to change
    *mem = 0xBEEBB00A;
    while(*mem == 0xBEEBB00A);
}
