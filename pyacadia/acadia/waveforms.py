from typing import Union
from functools import reduce
from operator import mul
import logging

import numpy as np

from acadia.rfdc import Channel
from .compiler import Symbol, Operation
from .sample_arithmetic import sample_to_complex as s2c
from .sample_arithmetic import complex_to_sample as c2s
from .sample_arithmetic import get_function

__all__ = ["WaveformMemory", 
           "ChannelWaveformMemory",
           "DecimatedChannelWaveformMemory",
           "FixedChannelWaveformMemory", 
           "WindowedConstantWaveformMemory"]

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
        
        if isinstance(shape, int):
            self._shape = (shape, 2)
        else:
            self._shape = (*shape, 2)

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

    def duplicate(self):
        """
        Create a copy of the memory. Note that this just creates another WaveformMemory
        with the same shape, dtype, and resource allocator as this one; it does not
        copy the contents of the memory. Note additionally that if this memory is attached,
        the duplicated memory will not be.
        """
        return WaveformMemory(self.shape, self.dtype, self._resource_allocator)
    
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
    
    def set(self, 
            data: Union[str, np.ndarray, float, complex], 
            scale: complex = 1.0,
            **kwargs) -> None:
        """
        Load the memory with data according to the type of the 
        ``data`` parameter.

        If ``data`` is a numpy array or a scalar, the numeric data will be
        converted into to integer sample values assuming a full-scale range
        of [-1,1] in each quadrature. The ``scale`` parameter can be used to
        scale the conversion factor, allowing for more efficient amplitude
        scaling and phase-shifting then pre-scaling the floating-point data. 
        Providing any extra keyword arguments will cause an exception to be 
        raised.
        
        If ``data`` is a string, it must be a valid function name for 
        :func:`sample_arithmetic.functional_populate`. The function will be 
        passed the output array as the first positional argument and the scale 
        as the third. Any other provided keyword arguments will be passed 
        through.
            
        :param data: Loading specifier as described above
        :type data: tuple of str, np.ndarray, float, complex
        :param scale: Optional scale factor for sample-data
        :type scale: complex
        """
        if isinstance(data, str):
            func = get_function(data)
            func(self.array, scale, **kwargs)
        elif isinstance(data, WaveformMemory):
            self.set(data.array)
       
        # For numpy scalars, make 1D array and recurse
        elif isinstance(data, (float, np.float64, np.float32, complex, np.complex64, np.complex128)):
            # Make 1D array from scalar for proper broadcasting and cast to complex
            data = np.array(data, ndmin=1)
            if data.dtype.kind == 'f':
                data = data.astype(np.dtype(f"<c{2*data.dtype.itemsize}"))
            
            self.set(data)
            
        elif isinstance(data, np.ndarray):
            if len(kwargs) != 0:
                raise ValueError(f"Keyword arguments are not allowed for"
                                 " array or scalar data.")

            if data.dtype.kind == 'i':
                if data.shape[-1] != 2:
                    raise ValueError(f"Setting a WaveformMemory with sample data must"
                                     f" have a final dimension of length 2;"
                                     f" received ndarray has shape {data.shape}")
                
                # copyto will automatically broadcast if necessary
                np.copyto(self.array, data)

            elif data.dtype.kind == 'c':
                # complex_to_sample will automatically take care of broadcasting a 1D array
                if self._resource is None:
                    raise ValueError(f"Attempted to set data of non-attached"
                                   f" memory with array of shape {data.shape}.")
                
                WaveformMemory.complex_to_sample(data, output=self.array, scale=scale)
            else:
                raise TypeError(f"Unable to convert waveform data of dtype"
                                f" {data.dtype} to complex.")

        else:
            raise TypeError(f"Unable to set WaveformMemory using object of type {type(data)}")
        
       
    @staticmethod
    def sample_to_complex(input: np.ndarray, 
                            output: Union[np.ndarray, np.dtype, None] = None, 
                            scale: Union[float, complex] = 1.0) -> np.ndarray:
        """
        Convert sample data from its signed integer quadratures to complex 
        floating-point numbers. Inputs must have an innermost dimension of 
        size 2.
        """

        input = np.array(input)

        if input.dtype.kind != "i":
            raise TypeError(f"Unable to accept input with dtype kind {input.dtype.kind}")
        
        if input.shape[-1] != 2:
            raise ValueError(f"Last dimension of input array must correspond to quadrature")
        
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
        
        s2c(input, output, np.complex128(scale))
        return output
            
    @staticmethod
    def complex_to_sample(input: Union[np.ndarray], 
                        output: Union[np.ndarray, np.dtype] = None, 
                        scale: Union[float, complex] = 1.0) -> np.ndarray:
        """
        Convert complex floating-point data into integer samples and pack into
        an array in the order expected by the RF tiles. The input 
        floating-point values must be in the range [-1, 1). Note that the upper
        bound is exclusive; the last valid value in the range is 1 - 2^-13.
        """
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
        
        c2s(input, output, np.complex128(scale))
        return output
        
class ChannelWaveformMemory(WaveformMemory):
    """
    A :class:`WaveformMemory` intended to abstract signals to be streamed out of a
    DAC channel or in from an ADC channel. This is distinguished from a regular
    :class:`WaveformMemory` because a regular waveform can be stored in any region 
    and need not be associated with any specific channel, but instances of 
    :class:`ChannelWaveformMemory` are associated with a specific channel and may 
    be used to calculate DMA parameters.
    """
    
    def __init__(self, 
                 channel: Channel, 
                 shape: Union[int, tuple],
                 dtype: Union[np.dtype, str] = "<i2",
                 resource_allocator: callable = None):
        """
        :param channel: An object of type :class:`Channel` from which the 
            sampling parameters will be extracted.
        :type channel: :class:`Channel`
        :param shape: The shape of the waveform (or its shape) in samples, where each 
            sample is a pair of numbers.
        :type shape: int or tuple of ints
        :param resource_allocator: A callable that will be called with the keyword 
            argument ``size`` in order to create the internal memory resource
        :type resource_allocator: callable
        """
        if not isinstance(channel, Channel):
            raise TypeError(f"Must create ChannelWaveformMemory objects with Channel"
                            f" instances (received {type(channel)})")
        
        self.channel = channel

        if resource_allocator is None:
            raise ValueError(f"Region must be provided for ChannelWaveformMemory"
                                 f" associated with channel {channel}")

        super().__init__(shape, dtype, resource_allocator)
    
    def dma_parameters(self) -> list[dict]:
        """
        Generate a `dict` of parameters for the :class:`Acadia` `generate` 
        method.
        """
        if self._resource is None:
            raise TypeError(f"Attempted to get DMA parameters of non-allocated array.")
        
        if self.nbytes % self.channel.interface_width_bytes != 0:
            raise ValueError("Requested DMA parameters for WaveformMemory with"
                             f" misaligned length ({self.nbytes:X} bytes)")

        # Guaranteed aligned when allocated with DACArray
        word_address = self._resource._resource_id // self.channel.interface_width_bytes
        length_cycles = self.nbytes // self.channel.interface_width_bytes

        return [{
            "channel": self.channel,
            "length": length_cycles,
            "word_address": word_address
        }]
    
class DecimatedChannelWaveformMemory(ChannelWaveformMemory):
    """
    A :class:`WaveformMemory` intended to abstract signals streamed in from an
    ADC channel.
    """
    
    def __init__(self, 
                 channel: Channel, 
                 shape: Union[int, tuple],
                 decimation: int,
                 resource_allocator: callable = None):
        """
        :param channel: An object of type :class:`Channel` from which the 
            sampling parameters will be extracted.
        :type channel: :class:`Channel`
        :param shape: The shape of the waveform (or its shape) in samples, where each 
            sample is a pair of numbers. Note that the decimation is not taken into 
            account when allocating; this should contain the shape after decimation,
            if any.
        :type shape: int or tuple of ints
        :param resource_allocator: A callable that will be called with the keyword 
            argument ``size`` in order to create the internal memory resource
        :type resource_allocator: callable
        :param decimation: The decimation factor applied to the stream of samples when
            captured. This is used to determine the data type of the array and the length
            of the DMA stream in cycles.
        :type decimation: int
        """
        super().__init__(channel, shape=shape, dtype="<i4", resource_allocator=resource_allocator)

        if channel.is_dac:
            raise TypeError(f"DecimatedChannelWaveformMemory objects may only be"
                            f" created for ADC channels")
        
        self._decimation = decimation

        # The provided shape is the shape after decimation
        # Therefore, we need to know the minimum decimation; 
        # i.e., the decimation value that would produce one 
        # value per cycle at the output of the decimator
        # This tells us the scale factor by which we need to
        # divide the decimation when converting to samples

        input_samples_per_cycle = self.channel.interface_width_bytes // 4
        # cycles per output sample = input samples per output sample / input samples per cycle
        self.cycles_per_output_sample = self._decimation // input_samples_per_cycle
        self.length_cycles = self.size * self.cycles_per_output_sample
    
    def dma_parameters(self) -> list[dict]:
        """
        Generate a `dict` of parameters for the :class:`Acadia` `generate` 
        method.
        """
        return [{
            "channel": self.channel,
            "length": self.length_cycles,
            "word_address": 0,
            "fixed": False,
            "blank": False
        }]
        
class FixedChannelWaveformMemory(ChannelWaveformMemory):
    """
    A waveform with a constant value.
    """
    
    def __init__(self, 
                 channel: Channel, 
                 length_cycles: Union[int, Symbol, Operation],
                 blank=False,
                 resource_allocator: callable = None):
        """
        :param channel: Channel for the waveform
        :type channel: :class:`Channel`
        :param length: Length of the constant in seconds
        :type length: float or :class:`Symbol` wrapping a float
        """
        if not isinstance(channel, Channel):
            raise TypeError(f"Channel for a FixedChannelWaveformMemory must be a Channel object")
        
        self.channel = channel
        self.blank = blank
        self.length_cycles = Symbol(length_cycles) if isinstance(length_cycles, int) else length_cycles
        
        # Only DACs require allocation in a local waveform memory specific to the channel,
        # ADCs don't have dedicated waveform memory
        if channel.is_dac:
            interface_width_samples = channel.interface_width_bytes // 4
            super().__init__(channel, shape=interface_width_samples, resource_allocator=resource_allocator)

    def dma_parameters(self) -> list[dict]:  
        if self.channel.is_dac:
            if self._resource is None:
                raise ValueError("FixedWaveformMemory for DAC channel not allocated")
            word_address = self._resource._resource_id // self.channel.interface_width_bytes
        else:
            word_address = 0

        return [{
            "channel": self.channel,
            "length": self.length_cycles,
            "word_address": word_address,
            "fixed": True,
            "blank": self.blank
        }]
    
    def set(self, data, scale: complex = 1.0):

        # If the user specifies a scipy signal envelope but a zero-length window,
        # we can't just call set() on the data argument because WaveformMemory.set() will 
        # try to populate the nominally-constant four-wide memory block of the fixed
        # waveform with non-constant values. therefore, only use pass through the 
        # data argument if the user provided a number or a direct array
        # Otherwise, just pass in a constant 1 so that the constant will be broadcasted
        # during the assignment
        set_data = data if np.isscalar(data) or isinstance(data, np.ndarray) else np.float64(1.0)
        super().set(set_data, scale)

                
class WindowedConstantWaveformMemory(ChannelWaveformMemory):
    """
    A constant waveform whose sharp rise and fall events are tapered with a 
    window function. This is carried out by
    """
    def __init__(self, 
                 channel: Channel, 
                 window_length_samples: int,
                 constant_length_cycles: int = None,
                 resource_allocator: callable = None):
        """
        :param channel: Channel on which to apply the waveform
        :type channel: :class:`Channel`
        :param window_shape: The shape of the windowed portion
            of the waveform (the sum of the regions before and after the 
            rectangular segment). This may be zero.
        :type window_shape: int or tuple
        :param constant_length_cycles: The length of the rectangular portion
            of the waveform
        :type constant_length_cycles: int
        """

        self._window_length_samples = window_length_samples
        self.channel = channel

        if window_length_samples > 0:
            super().__init__(channel, window_length_samples, resource_allocator=resource_allocator)
            # `seconds_to_bytes` will check whether we have an integer number of cycles
            # Each cycle, one interface-width of data is streamed out, so divide the
            # memory size by the width of the interface to get the number of cycles    
            self.window_length_cycles = window_length_samples * 4 // channel.interface_width_bytes
            self.split_cycle = self.window_length_cycles // 2
            self.split_sample = self.split_cycle * self.channel.interface_width_bytes // 4
        else:
            self.split_cycle = None
            self.split_sample = None
        
        self._constant = FixedChannelWaveformMemory(channel, constant_length_cycles, resource_allocator=resource_allocator)
        
    def dma_parameters(self) -> list[dict]:
        constant_parameters = self._constant.dma_parameters()
        if self._window_length_samples == 0:
            return constant_parameters
        
        ramp_first = super().dma_parameters()
        ramp_first[0]["length"] = self.split_cycle
        
        ramp_second = super().dma_parameters()
        ramp_second[0]["length"] -= self.split_cycle
        ramp_second[0]["word_address"] += self.split_cycle
        
        return ramp_first + constant_parameters + ramp_second
    
    def set(self, data, scale: complex = 1.0):
        if self.split_sample is not None:
            # update the pulse memory for the ramp part as usual
            super().set(data, scale=scale) 
            split_sample_value = self.array.reshape(-1,2)[self.split_sample,:]
            self._constant.set(split_sample_value, scale=scale)
        else:
            self._constant.set(data, scale=scale)
        