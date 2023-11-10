#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <pthread.h>
#include <arm_neon.h>

int _add_rows(
    int16_t*, // input, 
    int32_t*, // output, 
    uint16_t, // num_rows, 
    uint32_t, // num_cols,
    uint8_t // threads
);

int add_rows_input_phys(
    uint64_t, // input_address, 
    int32_t*, // output, 
    uint16_t, // num_rows, 
    uint32_t, // num_cols,
    uint8_t // threads
);

int add_rows_input_phys_output_phys(
    uint64_t, // input_address, 
    uint64_t, // output_address,  
    uint16_t, // num_rows, 
    uint32_t, // num_cols,
    uint8_t // threads
);

void to_samples(
    float*, // input,
    int16_t*, // output,
    uint32_t, // n
    float // scale
);

void to_samples_simd(
    float*, // input,
    int16_t*, // output,
    uint32_t, // n
    float // scale
);

void to_samples_simd_batched(
    float*, // input,
    int16_t*, // output,
    uint32_t, // n
    float // scale
);

// https://github.com/Xilinx/u-boot-xlnx/blob/master/arch/arm/cpu/armv8/generic_timer.c
unsigned long get_tbclk(void);
unsigned long timer_read_counter(void);