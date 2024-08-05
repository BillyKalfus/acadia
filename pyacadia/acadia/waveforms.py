from typing import Union
from functools import reduce
from operator import mul

import numpy as np
from .channel import Channel
from .compiler import Symbol, Operation

__all__ = ["Waveform", 
           "ChannelWaveform",
           "DecimatedChannelWaveform",
           "FixedChannelWaveform", 
           "WindowedConstantWaveform"]

class Waveform:
    """
    A wrapper for waveforms, which are distinguished from regular arrays in 
    that their elements are pairs of integers and that they live in 
    specific hardware memory regions dpeending the channel with which they're
    associated.
    """
    
    def __init__(self, 
                 shape: Union[int, tuple],
                 dtype: Union[np.dtype, str] = None, 
                 resource_allocator: callable = None):
        """
        Create a Waveform for a channel with the specified data type.

        :type channel: Channel
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
            self._resource = None
        else:
            self._resource = resource_allocator(shape=self._shape, dtype=self._dtype)
    
    @property
    def __array_interface__(self) -> dict:
        if self._resource is None:
            raise MemoryError(f"Attempted access of non-attached memory {self}"
                              f" with resource {self._resource}")
        return self._resource.__array_interface__
    
    @property
    def byte_address(self) -> int:
        if self._resource is None:
            raise MemoryError(f"Attempted access of non-attached memory {self}"
                              f" with resource {self._resource}")
        return self._resource.byte_address
    
    @property
    def nbytes(self) -> int:
        return reduce(mul, self._shape, self._dtype.itemsize)
    
    @property
    def shape(self) -> tuple:
        return self._shape[:-1]
    
    @property
    def dtype(self) -> np.dtype:
        return self._dtype
    
    @property
    def array(self) -> np.ndarray:
        if self._resource is None or self._resource.__array_interface__ is None:
            raise MemoryError(f"Attempted access of non-attached memory {self}"
                                f" with resource {self._resource}")
        
        a = self._resource.__array_interface__
        return np.frombuffer(a["data"], 
                             dtype=np.dtype(a["typestr"]), 
                             offset=a["offset"],
                             count=reduce(mul, self._shape)).reshape(self._shape)
    
    @property
    def data(self) -> memoryview:
        return self.array.data
        
    @property
    def size(self) -> int:
        return reduce(mul, self._shape[:-1], 1)

    def __getitem__(self, k):
        return self.data[k]
    
    def set(self, 
            data: Union[tuple[str,str], np.ndarray, float, complex], 
            scale: complex = 1.0,
            **kwargs) -> None:
        """
        Load a :class:`Waveform` with data according to the type of the 
        ``data`` parameter.

        If ``data`` is a numpy array or a scalar, the numeric data will be
        converted into to integer sample values assuming a full-scale range
        of [-1,1] in each quadrature. The ``scale`` parameter can be used to
        scale the conversion factor, allowing for more efficient amplitude
        scaling and phase-shifting then pre-scaling the floating-point data. 
        Providing any extra keyword arguments will cause an exception to be 
        raised.
        
        If ``data`` is a tuple of two strings, the strings will be used to 
        specify a function for populating the waveform. Note that any extra
        keyword arguments will be passed into the call. Valid values are:

        - ``("scipy", name)``: This format is designed to populate a 
            :class:`Waveform` using the signal window functions in 
            ``scipy.signal.windows``; the second argument should be a valid 
            window passed to ``scipy.signal.windows.get_window``, and the 
            returned floating-point array will be used to populate the 
            :class:`Waveform` as if passed in through ``data``.
            
        :param waveform: Waveform to load
        :type waveform: :class:`Waveform`
        :param data: Loading specifier as described above
        :type data: tuple of str, np.ndarray, float, complex
        :param scale: Optional scale factor for sample-data
        :type scale: complex
        """
        if np.isscalar(data) or isinstance(data, np.ndarray):
            if len(kwargs) != 0:
                raise ValueError(f"Keyword arguments are not allowed for"
                                 " scalar or array data.")
            if not hasattr(data, "dtype"):
                raise AttributeError(f"Scalar inputs must define a dtype")

            # Make 1D array from scalar for proper broadcasting
            data = np.array(data, dtype=data.dtype, ndmin=1)
            if data.dtype.kind == 'f':
                data = data.astype(np.dtype(f"<c{2*data.dtype.itemsize}"))

            if data.dtype.kind == 'i':
                if data.shape[-1] != 2:
                    raise ValueError(f"Setting a Waveform with sample data must"
                                     f" have a final dimension of length 2;"
                                     f" received ndarray has shape {data.shape}")
                
                # copyto will automatically broadcast if necessary
                np.copyto(self.array, data)

            elif data.dtype.kind == 'c':
                # complex_to_sample will automatically take care of broadcasting a scalar
                Waveform.complex_to_sample(data, output=self.array, scale=scale)
            else:
                raise TypeError(f"Unable to convert waveform data of dtype"
                                f" {data.dtype} to complex.")
            
            
        elif isinstance(data, (tuple, list)):
            if len(data) != 2 or (not isinstance(data[0], str)) or (not isinstance(data[1], str)):
                raise ValueError(f"Invalid tuple for setting Waveform data:"
                                 f" {data}")
            
            if data[0] == "scipy":
                from scipy.signal.windows import get_window
                self.set(get_window(data[1], self.size), scale=scale)
            else:
                raise ValueError(f"Unrecognized signature specifier for"
                                 f" waveform set: {data[0]}")
        else:
            raise TypeError(f"Unable to set Waveform using object of type {type(data)}")
        
       
    @staticmethod
    def sample_to_complex(input: np.ndarray, 
                            output: Union[np.ndarray, np.dtype, None] = None, 
                            scale: Union[float, complex] = 1.0) -> np.ndarray:
        """
        Convert sample data from its integer quadratures to complex 
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
        
        float_type = np.dtype(f"<f{output.dtype.itemsize // 2}")

        scale *= 2**(input.dtype.itemsize*8 - 1) - 1 
        np.multiply(np.reshape(input, -1), 
                    1/scale, 
                    out=np.reshape(output, -1).view(float_type), 
                    dtype=float_type,
                    casting="safe")
            
        return output

    @staticmethod
    def complex_to_sample(input: Union[np.ndarray], 
                        output: Union[np.ndarray, np.dtype] = None, 
                        scale: Union[float, complex] = 1.0) -> np.ndarray:
        """
        Convert complex floating-point data into integer samples and pack into
        an array in the order expected by the RF tiles.
        """
        if not hasattr(input, "dtype"):
            raise TypeError(f"Input must have a dtype (input is of type"
                            f" {type(input)})")
        
        if input.dtype.kind != "c":
            raise TypeError(f"Input dtype must be complex (found kind"
                            f" {input.dtype.kind})")
        
        float_type = np.dtype(f"<f{input.dtype.itemsize // 2}")

        if output is None:
            output = np.dtype("<i2")

        if isinstance(output, np.dtype):
            output = np.empty((*input.shape, 2), dtype=output)

        if not hasattr(output, "dtype"):
            raise TypeError(f"Output must have a dtype (output is of type"
                            f" {type(output)})")

        if output.dtype.kind != "i":
            raise TypeError(f"Output dtype must be integer (found kind"
                            f" {output.dtype.kind})")
        
        if output.shape[-1] != 2:
            raise ValueError(f"Converting complex values to samples requires"
                             f" the last dimension to correspond to quadrature"
                             f" (received shape {output.shape})")
        
        scale *= 2**(output.dtype.itemsize*8 - 1) - 1 

        # If the input is a complex scalar, this will keep the outer length-1
        # dimension and allow the rounding to broadcast correctly
        scaled = np.multiply(input, scale).view(float_type).reshape(-1, 2)
        np.rint(scaled, 
                out=np.reshape(output, (-1,2)), 
                casting="unsafe")
        return output
        
class ChannelWaveform(Waveform):
    """
    A :class:`Waveform` intended to abstract signals to be streamed out of a
    DAC channel or in from an ADC channel. This is distinguished from a regular
    :class:`Waveform` because a regular waveform can be stored in any region 
    and need not be associated with any specific channel, but instances of 
    :class:`ChannelWaveform` are associated with a specific channel and may 
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
            raise TypeError(f"Must create DACWaveform objects with Channel"
                            f" instances (received {type(channel)})")
        
        self.channel = channel

        if resource_allocator is None:
            if channel.is_dac:
                if not hasattr(channel, "memory_type"):
                    raise ValueError("Must provide an attached channel when"
                                    " creating a DACWaveform with no allocator.")
                resource_allocator = channel.memory_type
            else:
                raise ValueError(f"Region must be provided for ChannelWaveform"
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
            raise ValueError("Requested DMA parameters for Waveform with"
                             f" misaligned length ({self.nbytes:X} bytes)")

        # Guaranteed aligned when allocated with DACArray
        word_address = self._resource._resource_id // self.channel.interface_width_bytes
        length_cycles = self.nbytes // self.channel.interface_width_bytes

        return [{
            "channel": self.channel,
            "length": length_cycles,
            "word_address": word_address
        }]
    
class DecimatedChannelWaveform(ChannelWaveform):
    """
    A :class:`Waveform` intended to abstract signals streamed in from an
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
            raise TypeError(f"DecimatedChannelWaveform objects may only be"
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
        
class FixedChannelWaveform(ChannelWaveform):
    """
    A waveform with a constant value.
    """
    
    def __init__(self, 
                 channel: Channel, 
                 length_cycles: Union[int, Symbol, Operation],
                 blank=False):
        """
        :param channel: Channel for the waveform
        :type channel: :class:`Channel`
        :param length: Length of the constant in seconds
        :type length: float or :class:`Symbol` wrapping a float
        """
        if not isinstance(channel, Channel):
            raise TypeError(f"Channel for a FixedChannelWaveform must be a Channel object")
        
        self.channel = channel
        self.blank = blank
        self.length_cycles = Symbol(length_cycles) if isinstance(length_cycles, int) else length_cycles
        
        if channel.is_dac:
            interface_width_samples = channel.interface_width_bytes // 4
            super().__init__(channel, shape=interface_width_samples)

    def dma_parameters(self) -> list[dict]:  
        if self.channel.is_dac:
            if self._resource is None:
                raise ValueError("FixedWaveform for DAC channel not allocated")
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
        # we can't just call set() on the data argument because Waveform.set() will 
        # try to populate the nominally-constant four-wide memory block of the fixed
        # waveform with non-constant values. therefore, only use pass through the 
        # data argument if the user provided a number or a direct array
        # Otherwise, just pass in a constant 1 so that the constant will be broadcasted
        # during the assignment
        set_data = data if np.isscalar(data) or isinstance(data, np.ndarray) else np.float64(1.0)
        super().set(set_data, scale)

                
class WindowedConstantWaveform(ChannelWaveform):
    """
    A constant waveform whose sharp rise and fall events are tapered with a 
    window function. This is carried out by
    """
    def __init__(self, 
                 channel: Channel, 
                 window_length_samples: int,
                 constant_length_cycles: int = None):
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
            super().__init__(channel, window_length_samples)
            # `seconds_to_bytes` will check whether we have an integer number of cycles
            # Each cycle, one interface-width of data is streamed out, so divide the
            # memory size by the width of the interface to get the number of cycles    
            self.window_length_cycles = window_length_samples * 4 // channel.interface_width_bytes
            self.split_cycle = self.window_length_cycles // 2
            self.split_sample = self.split_cycle * self.channel.interface_width_bytes // 4
        else:
            self.split_cycle = None
            self.split_sample = None
        
        self._constant = FixedChannelWaveform(channel, constant_length_cycles)
        
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
        