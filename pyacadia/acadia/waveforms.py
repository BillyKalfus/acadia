from typing import Union
from functools import reduce
from operator import mul
import logging

import numpy as np

from acadia.rfdc import Channel
from .compiler import Symbol, Operation
from .sample_arithmetic import sample_to_complex
from .sample_arithmetic import complex_to_sample

__all__ = ["WaveformMemory"]

logger = logging.getLogger("acadia")

class WaveformMemory:
    """
    A wrapper for waveforms, which are distinguished from regular arrays in 
    that their elements are pairs of integers and that they live in 
    specific hardware memory regions.
    """
    
    def __init__(self, 
                 shape: Union[int, tuple],
                 dtype: Union[np.dtype, str] = None, 
                 resource_allocator: callable = None):
        """
        Create a WaveformMemory for a channel with the specified data type.

        :type channel: Channel
        :param shape: The shape of the array. Note that this should NOT include
            the dimension indexing quadrature.
        :type shape: int or tuple of ints
        :type dtype: np.dtype or str
        :param resource_allocator: A callable that will be called with the 
            keyword arguments ``shape`` and ``dtype`` in order to create the
            internal memory resource
        :type resource_allocator: callable
        """
        if dtype is None:
            dtype = "<i2"

        if not isinstance(dtype, (np.dtype, str)):
            raise TypeError(f"Waveform data type must be something from which"
                            f" a numpy dtype can be constructed;"
                            f" received {dtype}")
        
        self._dtype = np.dtype(dtype)
        
        if np.issubdtype(type(shape), int):
            self._shape = (shape, 2)
        elif isinstance(shape, tuple):
            self._shape = (*shape, 2)
        else:
            raise TypeError(f"Received invalid shape for WaveformMemory: {type(shape)}")

        if resource_allocator is None:
            # For arrays in local memory, we can set the array property immediately
            # since there's no notion of attachment
            self._resource = np.empty(shape=self._shape, dtype=self._dtype)
            self._attached_array = self._resource
        else:
            # For hardware arrays, we need to defer array assignment to when it's 
            # actually requested, since this must happen after the array is attached
            self._resource = resource_allocator(shape=self._shape, dtype=self._dtype)
            self._attached_array = None

        # The only reason we need to stash a reference internally is so that we can 
        # duplicate the memory if needed
        self._resource_allocator = resource_allocator

    def duplicate(self, **kwargs):
        """
        Create a copy of the memory. Note that this just creates another WaveformMemory
        with the same shape, dtype, and resource allocator as this one; it does not
        copy the contents of the memory. Note additionally that if this memory is attached,
        the duplicated memory will not be.
        """
        _kwargs = {"shape": self.shape, "dtype": self.dtype, "resource_allocator": self._resource_allocator}
        _kwargs.update(kwargs)
        return WaveformMemory(**_kwargs)
    
    @property
    def __array_interface__(self) -> dict:
        if self._resource.__array_interface__ is None:
            raise MemoryError(f"Attempted access of unattached memory {self}")
        return self._resource.__array_interface__
    
    @property
    def byte_address(self) -> int:
        if self._resource is None:
            raise MemoryError(f"Attempted access of unattached memory {self}")
        if isinstance(self._resource, np.ndarray):
            raise TypeError(f"Byte address not defined for resources in local memory.")
        return self._resource.byte_address
    
    @property
    def nbytes(self) -> int:
        return reduce(mul, self._shape, self._dtype.itemsize)
    
    @property
    def shape(self) -> tuple:
        """
        The shape of the array in samples (i.e., the rightmost dimension does 
        not correspond to quadrature and is not necessarily of length 2).
        """
        return self._shape[:-1]
    
    @property
    def dtype(self) -> np.dtype:
        return self._dtype

    @property
    def itemsize(self) -> int:
        return self._dtype.itemsize
    
    @property
    def array(self) -> np.ndarray:
        """
        Retrieve the underlying array of integer data. The returned array will
        have its rightmost dimension be of length 2, corresponding to 
        quadrature.
        """
        if self._attached_array is not None:
            return self._attached_array
        
        a = self.__array_interface__
        self._attached_array = np.frombuffer(a["data"], 
                             dtype=np.dtype(a["typestr"]), 
                             offset=a["offset"],
                             count=reduce(mul, self._shape)).reshape(self._shape)
        return self._attached_array
    
    @property
    def data(self) -> memoryview:
        return self.array.data
        
    @property
    def size(self) -> int:
        """
        The size of the array in number of samples.
        """
        return reduce(mul, self._shape[:-1], 1)

    def __getitem__(self, k):
        return self._resource[k]

    def __setitem__(self, k, v):
        self._resource[k] = v
    
    def load(self, 
            data: Union[np.ndarray, float, complex], 
            scale: complex = 1.0) -> None:
        """
        Load the memory with data.

        If ``data`` is a numpy array or a scalar of floats, it is passed 
        directly into :func:``sample_arithmetic.complex_to_sample``. If it
        is a numpy array of ints and the dtype matches this object's dtype,
        it is loaded in.
            
        :param data: Loading specifier as described above
        :type data: np.ndarray, float, complex
        :param scale: Optional scale factor for sample-data
        :type scale: complex
        """
        if self._resource is None:
            raise ValueError(f"Attempted to load non-attached memory.")

        if isinstance(data, WaveformMemory):
            self.load(data.array, scale)
        elif np.issubdtype(type(data), float) or np.issubdtype(type(data), complex):
            self.load(complex_to_sample(data, scale=scale))
        elif isinstance(data, np.ndarray):
            if data.dtype.kind == 'c' or data.dtype.kind == 'f':
                self.load(complex_to_sample(data, scale=scale))
            elif data.dtype.kind == 'i':
                if data.shape[-1] != 2:
                    raise ValueError(f"Setting a WaveformMemory with sample data must"
                                     f" have a final dimension of length 2;"
                                     f" received ndarray has shape {data.shape}")
                if data.dtype != self.dtype:
                    raise TypeError(f"Unable to load WaveformMemory of dtype"
                                    f" {self.dtype} from array of dtype {data.dtype}")                
                np.copyto(self.array, data)
            else:
                raise TypeError(f"Unable to convert waveform data of dtype"
                                f" {data.dtype} to complex.")
        else:
            raise TypeError(f"Unable to load WaveformMemory from object of type {type(data)}")
