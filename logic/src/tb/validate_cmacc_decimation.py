import numpy as np

# ------------- SETTINGS ------------- #
# The value of the real quadrature of the first sample to enter the CMACC. 
# Every following quadrature value sequentially increments by one.
starting_sample = 0x0560

# Accumulator Update Mode
#     When 00, the accumulator never updates, and computes input+preload for every sample.
#     When 01, the accumulator loads input+preload for the first input sample after arm_preload = '1', 
#         and accum+input for every following sample.
#     When 10, the accumulator loads input+preload for the first point of each kernel, 
#         and accum+input for every following point.
#     When 11, the accumulator never updates, and computes input+preload for every sample.
accumulator_update_mode = 2

# Preload values (shifted by 15, since the preload loads the upper 
# 32 bits of the accumulator and clears the lower ones.)
accumulator_re_preload = (0xA << 15)
accumulator_im_preload = (0xC << 15)

# Samples where the input is valid
# By default all inputs are valid, but we can optionally make some invalid here
start_time = 692
input_valid = np.empty((820-start_time) // 4, dtype=bool)
input_valid.fill(True)
input_valid[(764-start_time) // 4] = False

# The integration kernel
kernel = np.empty((4,2), dtype=np.uint16)
kernel[0,0] = 0x5678
kernel[0,1] = 0x1234
kernel[1,0] = 0x8FFF
kernel[1,1] = 0x0000
kernel[2,0] = 0x0000
kernel[2,1] = 0xFACE
kernel[3,0] = 0xB00C
kernel[3,1] = 0xABCD

# ------------- EXECUTION --------------- #

def sign_extended_mult(a,b):
    # Multiplies an 18-bit input a and a 16-bit input b and sign-extends the result to 47 bits
    # First, sign-extend the inputs to 18+16 bits 
    a = int(a)
    if a & (1 << 17):
        for i in range(18,18+16):
            a |= (1 << i)

    b = int(b)
    if b & (1 << 15):
        for i in range(16,18+16):
            b |= (1 << i)

    # Now multiply and mask the relevant bits (since two's-complement 
    # multiplication produces a lot of bits to be thrown out)
    ab = (a*b) & ((1 << 18+16) - 1)

    # Finally, sign-extend the result to 47 bits
    for i in range(18+16, 47):
        if ab & (1 << (18+16-1)):
            ab |= (1 << i)
        else:
            ab &= ~(1 << i)

    return ab


# Create the input signal
# 4 samples per cycle, 2 quadratures per sample
input_signal = starting_sample + np.arange(len(input_valid)* 4 * 2, dtype=np.uint16)
input_signal = input_signal.astype(np.uint32).reshape(len(input_valid), 4, 2)

# Sum the samples in a given cycle, but maintain quadrature separation
input_summed = np.sum(input_signal, axis=1)

kernel_pointer = 0
accum_re = 0
accum_im = 0
for i in range(len(input_valid)):
    input_last = (i == (len(input_valid) - 1))
    kernel_first = kernel_pointer == 0
    kernel_last = (kernel_pointer == (kernel.shape[0] - 1))

    input_re_element_strs = [f'{x:04x}' for x in input_signal[i,:,0]]
    input_im_element_strs = [f'{x:04x}' for x in input_signal[i,:,1]]

    a_re = input_summed[i,0]
    a_im = input_summed[i,1]
    b_re = kernel[kernel_pointer,0]
    b_im = kernel[kernel_pointer,1]

    a_re_b_re = sign_extended_mult(a_re, b_re)
    a_re_b_im = sign_extended_mult(a_re, b_im)
    a_im_b_re = sign_extended_mult(a_im, b_re)
    a_im_b_im = sign_extended_mult(a_im, b_im)

    full_product_re = a_re_b_re - a_im_b_im
    full_product_im = a_im_b_re + a_re_b_im

    print(f"-------- Input cycle {i} (sim time = {start_time + i*4}) --------")
    print(f"Input real: {','.join(input_re_element_strs)}")
    print(f"Input imag: {','.join(input_im_element_strs)}")
    print(f"Input valid: {input_valid[i]}")
    print(f"Input last: {input_last}")
    print(f"")

    print(f"Kernel pointer: {kernel_pointer:04x}")
    print(f"Kernel real: {int(kernel[kernel_pointer,0]):04x}")
    print(f"Kernel imag: {int(kernel[kernel_pointer,1]):04x}")
    print(f"Kernel first: {kernel_first}")
    print(f"Kernel last: {kernel_last}")
    print(f"")
    
    print(f"Summed input data: evaluate just after transition at t={start_time + i*4 + 4}")
    print(f"({a_re:08x}, {a_im:08x})")
    print("")

    print(f"Partial products and full product: evaluate just after transition at t={start_time + i*4 + 8}")
    print(f"a_re_b_re: {a_re_b_re:012x}")
    print(f"a_im_b_im: {a_im_b_im:012x}")
    print(f"a_re_b_im: {a_re_b_im:012x}")
    print(f"a_im_b_re: {a_im_b_re:012x}")
    print(f"Full product: ({full_product_re:012x}, {full_product_im:012x})")
    print(f"")

    # print(f"Starting accumulator value: evaluate just before t={start_time + i*4 + 8}")
    # print(f"({accum_re:012x}, {accum_im:012x})")
    # print("")

    if input_valid[i]:
        kernel_pointer = (kernel_pointer + 1) % kernel.shape[0]
            
        if accumulator_update_mode == 1:
            if i == 0:
                accum_re = accumulator_re_preload + full_product_re
                accum_im = accumulator_im_preload + full_product_im
            else:
                accum_re += full_product_re
                accum_im += full_product_im
        elif accumulator_update_mode == 2:
            if kernel_first:
                accum_re = accumulator_re_preload + full_product_re
                accum_im = accumulator_im_preload + full_product_im
            else:
                accum_re += full_product_re
                accum_im += full_product_im
        else:
            accum_re = accumulator_re_preload + full_product_re
            accum_im = accumulator_im_preload + full_product_im

    print(f"New accumulator value: evaluate just after t={start_time + i*4 + 12}")
    print(f"({accum_re:012x}, {accum_im:012x})")
    print(f"")

            