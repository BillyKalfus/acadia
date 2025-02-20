from typing import Union, Callable

import numpy as np

__all__ = ["sample_to_complex", "complex_to_sample", "get_function"]

def sample_to_complex_unsafe(input: np.ndarray, output: np.ndarray, scale: np.complex128):
    float_type = np.dtype(f"<f{output.dtype.itemsize // 2}")
    input_complex = np.reshape(input, -1).astype(float_type).view(output.dtype)
    scale *= 2**(input.dtype.itemsize*8 - 1) 
    np.multiply(input_complex, 1.0/scale, out=np.reshape(output, -1))

def complex_to_sample_unsafe(input: np.ndarray, output: np.ndarray, scale: np.complex128):
    float_type = np.dtype(f"<f{input.dtype.itemsize // 2}")
    scaled = np.multiply(input, scale*(2**15)).view(float_type)
    rounded = np.rint(scaled).astype(np.int16, casting="unsafe")
    np.copyto(np.reshape(output, (-1, 2)), np.reshape(rounded, (-1, 2)))

def sample_to_complex(input: np.ndarray, 
                        output: Union[np.ndarray, np.dtype, None] = None, 
                        scale: Union[float, complex] = 1.0) -> np.ndarray:
    """
    Convert sample data from signed integer quadratures to complex 
    floating-point numbers. Inputs must have an innermost dimension of 
    size 2 (corresponding to quadrature).
    """
    
    if input.dtype.kind != "i":
        raise TypeError(f"Unable to accept input with dtype kind {input.dtype.kind}")
    
    if input.shape[-1] != 2:
        raise ValueError(f"Last dimension of input array must have length 2"
                        " (corresponding to quadrature)")
    
    if output is None:
        output = np.dtype("<c16")

    if isinstance(output, np.dtype):
        output = np.empty(input.shape[:-1], dtype=output)
        
    elif not hasattr(output, "dtype"):
        raise TypeError(f"Output must have (or be) a dtype, got type"
                        f" {type(output)}")
    
    if output.dtype.kind != "c":
        raise TypeError(f"Output dtype must be complex (found kind"
                        f" {output.dtype.kind})")
    
    sample_to_complex_unsafe(input, output, np.complex128(scale))
    return output
        
def complex_to_sample(input: Union[np.ndarray], 
                    output: Union[np.ndarray, np.dtype] = None, 
                    scale: Union[float, complex] = 1.0) -> np.ndarray:
    """
    Convert complex floating-point data into integer samples and pack into
    an array in the order expected by the RF tiles. The input 
    floating-point values must be in the range [-1, 1). Note that the upper
    bound is exclusive; the last valid value in the range is 1 - 2^-15.
    """
    if isinstance(input, (float, np.float64, np.float32, complex, np.complex64, np.complex128)):
        # Make 1D array from scalar for proper broadcasting and cast to complex
        input = np.array(input, ndmin=1)
        if input.dtype.kind == 'f':
            input = input.astype(np.dtype(f"<c{2*input.dtype.itemsize}"))

    if not hasattr(input, "dtype"):
        raise TypeError(f"Input must have a dtype (input is of type"
                        f" {type(input)})")
    
    if input.dtype.kind == "f":
        input = input.astype(f"<c{input.dtype.itemsize*2}")
    
    if input.dtype.kind != "c":
        raise TypeError(f"Input dtype must be complex (found kind"
                        f" {input.dtype.kind})")
    
    if output is None:
        output = np.empty((*input.shape, 2), dtype=np.int16)

    if not hasattr(output, "dtype"):
        raise TypeError(f"Output must have a dtype (output is of type"
                        f" {type(output)})")

    if output.dtype.kind != "i" or output.dtype.itemsize != 2:
        raise TypeError(f"Output dtype must be 16-bit integer (found dtype"
                        f" {output.dtype})")
    
    if output.shape[-1] != 2:
        raise ValueError(f"Converting complex values to samples requires"
                            f" the last dimension to correspond to quadrature"
                            f" (received shape {output.shape})")
    
    complex_to_sample_unsafe(input, output, np.complex128(scale))
    return output
