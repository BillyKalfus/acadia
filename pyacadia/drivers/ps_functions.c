#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <arm_neon.h>

#include "ps_functions.h"

// A structure containing details for a thread for distributing work
struct add_rows_worker_t {
    int16_t* input;
    int32_t* output;
    uint32_t num_rows;
    uint32_t worker_cols;
    uint32_t total_cols;

    pthread_t thread_id;
    pthread_attr_t thread_attr;
};

void* add_rows_worker(void* work_data) {
    // We'll do the loop in a particular order; so that we can keep the running
    // sum in a SIMD register, we'll load some number of samples from the first
    // vector, then load the corresponding samples from the second vector and
    // add them to the first, then those of the third, and so on.
    // Then, we'll move on to the next set of samples.
    
    // Cache lines are 64 bytes, so we'll load that in each iteration
    // this is 32 16-bit words, but we need to load them in groups of
    // 4 so that we can do a widening addition (the result will be a 
    // 32x4 register). Therefore, we need 8 16x4 registers to load
    // data into, and we'll keep the sum in 8 32x4 registers
    // This works so long as we don't add more than 2**16 numbers together
    int16x4_t a0, a1, a2, a3, a4, a5, a6, a7;
    int32x4_t s0, s1, s2, s3, s4, s5, s6, s7;
    uint32_t row_start; // The offset in the array at which the current vector starts
    uint32_t element; // The particular element within the vector

    struct add_rows_worker_t* work = (struct add_rows_worker_t*)work_data;

    for(element = 0; element < work->worker_cols; element += 4*8) {
        // Clear the sum
        s0 = vdupq_n_s32(0);
        s1 = vdupq_n_s32(0);
        s2 = vdupq_n_s32(0);
        s3 = vdupq_n_s32(0);
        s4 = vdupq_n_s32(0);
        s5 = vdupq_n_s32(0);
        s6 = vdupq_n_s32(0);
        s7 = vdupq_n_s32(0);
        
        for(row_start = 0; row_start < work->total_cols * work->num_rows; row_start += work->total_cols) {
            // Load the addends
            a0 = vld1_s16(work->input + row_start + element);
            a1 = vld1_s16(work->input + row_start + element + 4);
            a2 = vld1_s16(work->input + row_start + element + 8);
            a3 = vld1_s16(work->input + row_start + element + 12);
            a4 = vld1_s16(work->input + row_start + element + 16);
            a5 = vld1_s16(work->input + row_start + element + 20);
            a6 = vld1_s16(work->input + row_start + element + 24);
            a7 = vld1_s16(work->input + row_start + element + 28);
            
            s0 = vaddw_s16(s0, a0);
            s1 = vaddw_s16(s1, a1);
            s2 = vaddw_s16(s2, a2);
            s3 = vaddw_s16(s3, a3);
            s4 = vaddw_s16(s4, a4);
            s5 = vaddw_s16(s5, a5);
            s6 = vaddw_s16(s6, a6);
            s7 = vaddw_s16(s7, a7);
        }
        
        // Write the sums to the output
        vst1q_s32(work->output + element, s0);
        vst1q_s32(work->output + element + 4, s1);
        vst1q_s32(work->output + element + 8, s2);
        vst1q_s32(work->output + element + 12, s3);
        vst1q_s32(work->output + element + 16, s4);
        vst1q_s32(work->output + element + 20, s5);
        vst1q_s32(work->output + element + 24, s6);
        vst1q_s32(work->output + element + 28, s7);
    }

    return NULL;
}

int _add_rows(
    int16_t* input, 
    int32_t* output, 
    uint16_t num_rows, 
    uint32_t num_cols,
    uint8_t threads
) {
    uint8_t t;
    uint32_t worker_cols;
    struct add_rows_worker_t* worker_data;
    void* retval;

    // Input sanity checks
    if(threads == 0) {
        return 1;
    }

    // Each worker needs to have a multiple of 32 elements 
    if(num_cols % (threads*32) != 0) {
        return 2;
    }

    worker_cols = num_cols / threads;
    
    // Initialize data for all of the workers and start the threads
    worker_data = (struct add_rows_worker_t*)malloc(threads*sizeof(struct add_rows_worker_t));
    for(t = 0; t < threads; t++) {
        // Set up argument information
        worker_data[t].input = input + t*worker_cols;
        worker_data[t].output = output + t*worker_cols;
        worker_data[t].num_rows = num_rows;
        worker_data[t].worker_cols = worker_cols;
        worker_data[t].total_cols = num_cols;

        // Create thread attributes
        if(!pthread_attr_init(&worker_data[t].thread_attr)) {
            return (1 << 8) + t;
        }
        
        // Create and start the thread
        if(!pthread_create(&worker_data[t].thread_id, 
                            &worker_data[t].thread_attr,
                            &add_rows_worker,
                            &worker_data[t])) {
            return (2 << 8) + t;
        }
    }

    // Destroy the thread attribute and wait for the worker to finish
    for(t = 0; t < threads; t++) {
        if(!pthread_attr_destroy(&worker_data[t].thread_attr)) {
            return (3 << 8) + t;
        }

        if(!pthread_join(worker_data[t].thread_id, &retval)) {
            return (4 << 8) + t;
        }
    }

    return 0;
}

int add_rows_input_phys(
    uint64_t input_address, 
    int32_t* output, 
    uint16_t num_rows, 
    uint32_t num_cols,
    uint8_t threads
) {
    int fd;
    int16_t* input;
    int retval;

    // Map the input array
    fd = open("/dev/mem", O_RDWR | O_SYNC);
    input = (int16_t*)mmap(NULL, num_cols*num_rows*sizeof(int16_t), PROT_READ | PROT_WRITE, MAP_SHARED, fd, input_address); 
    
    retval = _add_rows(input, output, num_rows, num_cols, threads);

    munmap(input, num_cols*num_rows*sizeof(int16_t));
    close(fd);

    return retval;
}

int add_rows_input_phys_output_phys(
    uint64_t input_address, 
    uint64_t output_address,  
    uint16_t num_rows, 
    uint32_t num_cols,
    uint8_t threads
) {
    int fd;
    int16_t* input;
    int32_t* output;
    int retval;

    // Map the input array
    fd = open("/dev/mem", O_RDWR | O_SYNC);
    input = (int16_t*)mmap(NULL, num_cols*num_rows*sizeof(int16_t), PROT_READ | PROT_WRITE, MAP_SHARED, fd, input_address); 
    output = (int32_t*)mmap(NULL, num_cols*sizeof(int32_t), PROT_READ | PROT_WRITE, MAP_SHARED, fd, output_address); 

    retval = _add_rows(input, output, num_rows, num_cols, threads);

    munmap(input, num_cols*num_rows*sizeof(int16_t));
    munmap(output, num_cols*sizeof(int32_t));

    close(fd);

    return retval;
}

void to_samples(
    float* input,
    int16_t* output,
    uint32_t n,
    float scale
) {
    float total_scale = scale*(1 << 15);
    for(uint32_t i = 0; i < n; i++) {
        output[i] = round(input[i] * total_scale);
    }
}

void to_samples_simd(
    float* input,
    int16_t* output,
    uint32_t n,
    float scale
) {
    float32x4_t s_in;
    int16x4_t s_out; 
    float total_scale = scale*(1 << 15);

    for(uint32_t i = 0; i < n; i += 4) {
        s_in = vld1q_f32(input + i); // Load
        s_in = vmulq_n_f32(s_in, total_scale); // Multiply
        s_in = vrndnq_f32(s_in); // Round
        s_out = vqmovn_s32(vcvtq_s32_f32(s_in)); // Convert to int16
        vst1_s16(output + i, s_out); // Store
    }
}

void to_samples_simd_batched(
    float* input,
    int16_t* output,
    uint32_t n,
    float scale
) {
    float32x4_t s_in0, s_in1, s_in2, s_in3, s_in4, s_in5, s_in6, s_in7;
    int16x4_t s_out0, s_out1, s_out2, s_out3, s_out4, s_out5, s_out6, s_out7; 
    float total_scale = scale*(1 << 15);

    for(uint32_t i = 0; i < n; i += 4*8) {
        // Load
        s_in0 = vld1q_f32(input + i);
        s_in1 = vld1q_f32(input + i + 4);
        s_in2 = vld1q_f32(input + i + 8);
        s_in3 = vld1q_f32(input + i + 12);
        s_in4 = vld1q_f32(input + i + 16);
        s_in5 = vld1q_f32(input + i + 20);
        s_in6 = vld1q_f32(input + i + 24); 
        s_in7 = vld1q_f32(input + i + 28);
        
        // Multiply
        s_in0 = vmulq_n_f32(s_in0, total_scale);
        s_in1 = vmulq_n_f32(s_in1, total_scale);
        s_in2 = vmulq_n_f32(s_in2, total_scale);
        s_in3 = vmulq_n_f32(s_in3, total_scale);
        s_in4 = vmulq_n_f32(s_in4, total_scale);
        s_in5 = vmulq_n_f32(s_in5, total_scale);
        s_in6 = vmulq_n_f32(s_in6, total_scale);
        s_in7 = vmulq_n_f32(s_in7, total_scale);
        
        // Round
        s_in0 = vrndnq_f32(s_in0);
        s_in1 = vrndnq_f32(s_in1);
        s_in2 = vrndnq_f32(s_in2);
        s_in3 = vrndnq_f32(s_in3);
        s_in4 = vrndnq_f32(s_in4);
        s_in5 = vrndnq_f32(s_in5);
        s_in6 = vrndnq_f32(s_in6);
        s_in7 = vrndnq_f32(s_in7);

        // Convert to int16
        s_out0 = vqmovn_s32(vcvtq_s32_f32(s_in0));
        s_out1 = vqmovn_s32(vcvtq_s32_f32(s_in1));
        s_out2 = vqmovn_s32(vcvtq_s32_f32(s_in2));
        s_out3 = vqmovn_s32(vcvtq_s32_f32(s_in3));
        s_out4 = vqmovn_s32(vcvtq_s32_f32(s_in4));
        s_out5 = vqmovn_s32(vcvtq_s32_f32(s_in5));
        s_out6 = vqmovn_s32(vcvtq_s32_f32(s_in6));
        s_out7 = vqmovn_s32(vcvtq_s32_f32(s_in7));

        // Store
        vst1_s16(output + i, s_out0);
        vst1_s16(output + i + 4, s_out1);
        vst1_s16(output + i + 8, s_out2);
        vst1_s16(output + i + 12, s_out3);
        vst1_s16(output + i + 16, s_out4);
        vst1_s16(output + i + 20, s_out5);
        vst1_s16(output + i + 24, s_out6);
        vst1_s16(output + i + 28, s_out7); 
    }
}

// https://github.com/Xilinx/u-boot-xlnx/blob/master/arch/arm/cpu/armv8/generic_timer.c
unsigned long get_tbclk(void)
{
	unsigned long cntfrq;
	asm volatile("mrs %0, cntfrq_el0" : "=r" (cntfrq));
	return cntfrq;
}

unsigned long timer_read_counter(void)
{
	unsigned long cntpct;

	isb();
	asm volatile("mrs %0, cntpct_el0" : "=r" (cntpct));

	return cntpct;
}