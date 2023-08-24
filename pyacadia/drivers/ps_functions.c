#include <arm_neon.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

void add_rows(
    int16_t* input,
    int32_t* output,
    uint32_t col_start, 
    uint32_t col_end, 
    uint16_t num_rows, 
    uint32_t num_cols
) {
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
    
    for(element = 0; element < (col_end-col_start); element += 4*8) {
        // Clear the sum
        s0 = vdupq_n_s32(0);
        s1 = vdupq_n_s32(0);
        s2 = vdupq_n_s32(0);
        s3 = vdupq_n_s32(0);
        s4 = vdupq_n_s32(0);
        s5 = vdupq_n_s32(0);
        s6 = vdupq_n_s32(0);
        s7 = vdupq_n_s32(0);
        
        for(row_start = 0; row_start < num_cols*num_rows; row_start += num_cols) {
            // Load the addends
            a0 = vld1_s16(input + row_start + col_start + element);
            a1 = vld1_s16(input + row_start + col_start + element + 4);
            a2 = vld1_s16(input + row_start + col_start + element + 8);
            a3 = vld1_s16(input + row_start + col_start + element + 12);
            a4 = vld1_s16(input + row_start + col_start + element + 16);
            a5 = vld1_s16(input + row_start + col_start + element + 20);
            a6 = vld1_s16(input + row_start + col_start + element + 24);
            a7 = vld1_s16(input + row_start + col_start + element + 28);
            
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
        vst1q_s32(output + element, s0);
        vst1q_s32(output + element + 4, s1);
        vst1q_s32(output + element + 8, s2);
        vst1q_s32(output + element + 12, s3);
        vst1q_s32(output + element + 16, s4);
        vst1q_s32(output + element + 20, s5);
        vst1q_s32(output + element + 24, s6);
        vst1q_s32(output + element + 28, s7);
    }
}

void add_rows_input_phys_output_file(
    uint64_t input_address, 
    char* output_filename, 
    uint32_t col_start, 
    uint32_t col_end, 
    uint16_t num_rows, 
    uint32_t num_cols
) {

    int fd_in = open("/dev/mem", O_RDWR | O_SYNC);
    int16_t* input = (int16_t*)mmap(NULL, num_cols*num_rows*sizeof(int16_t), PROT_READ | PROT_WRITE, MAP_SHARED, fd_in, input_address); 
    
    int fd_out = open(output_filename, O_CREAT | O_RDWR | O_SYNC, S_IRWXU | S_IRWXG | S_IRWXO);
    ftruncate(fd_out, (col_end-col_start)*sizeof(int32_t));
    int32_t* output = (int32_t*)mmap(NULL, (col_end-col_start)*sizeof(int32_t), PROT_READ | PROT_WRITE, MAP_SHARED, fd_out, 0); 
    
    add_rows(input, output, col_start, col_end, num_rows, num_cols);

    munmap(input);
    munmap(output);

    close(fd_in);
    close(fd_out);
}

void add_rows_input_phys_output_phys(
    uint64_t input_address, 
    uint64_t output_address, 
    uint32_t col_start, 
    uint32_t col_end, 
    uint16_t num_rows, 
    uint32_t num_cols
) {

    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    int16_t* input = (int16_t*)mmap(NULL, num_cols*num_rows*sizeof(int16_t), PROT_READ | PROT_WRITE, MAP_SHARED, fd, input_address);     
    int32_t* output = (int32_t*)mmap(NULL, (col_end-col_start)*sizeof(int32_t), PROT_READ | PROT_WRITE, MAP_SHARED, fd, output_address); 
    
    add_rows(input, output, col_start, col_end, num_rows, num_cols);

    munmap(input);
    munmap(output);

    close(fd);
}

