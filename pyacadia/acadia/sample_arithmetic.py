from typing import Union, Callable

import numpy as np
from scipy.signal.windows import hann as scipy_hann

__all__ = ["sample_to_complex", "complex_to_sample", "get_function"]

def sample_to_complex(input: np.ndarray, output: np.ndarray, scale: np.complex128):
    float_type = np.dtype(f"<f{output.dtype.itemsize // 2}")
    input_complex = np.reshape(input, -1).astype(float_type).view(output.dtype)

    scale *= 2**(input.dtype.itemsize*8 - 1) 
    np.multiply(input_complex, 
                1/scale, 
                out=np.reshape(output, -1))


def complex_to_sample(input: np.ndarray, output: np.ndarray, scale: np.complex128):
    # shift range from [-1,1) to [0,2)
    shifted = np.reshape(input*scale, -1) + 1 + 1j

    # scale range from [0,2) to [0, 2^16 - 1] and round
    float_type = np.dtype(f"<f{input.dtype.itemsize // 2}")
    scaled = np.multiply(shifted, (2**16-1)/2.0).view(float_type)
    rounded = np.rint(scaled).astype(np.int16, casting="unsafe")

    # shift range from [0, 2^16-1] to [-2^15, 2^15-1]
    rounded -= 2**15
    np.copyto(np.reshape(output, (-1, 2)), np.reshape(rounded, (-1, 2)))

_FUNCTIONS = {}
def register_function(name: str, func: Callable):
    """
    Register a function with the dictionary available to 
    :func:`get_function`. The function should have the 
    """
    _FUNCTIONS[name] = func

def get_function(name: str) -> Callable:
    """
    Retrieve a function for populating sample arrays from the local dictionary 
    of functions. The returned function will have the call signature 
    ``(output, scale, **kwargs)`` where ``output`` is the numpy array of 
    integer sample data and ``scale`` is a complex scale factor for the sample
    conversion. Other keyword arguments may be passed in and provided to the 
    function. The function will populate the output array and return ``None``.
    """
    return _FUNCTIONS[name]

def hann(output, scale, **kwargs):
    window_data = scipy_hann(output.size // 2).astype(np.complex128)
    complex_to_sample(window_data, output, scale)
register_function("hann", hann)