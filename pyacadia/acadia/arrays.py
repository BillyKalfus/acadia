from typing import Union

import numpy as np

from .compiler import ManagedMemory, Operation
from .channel import Channel

__all__ = ["Array", 
           "ProceduralArrayMixin", 
           "Waveform", 
           "ProcessedWaveform", 
           "ConstantWaveform", 
           "WindowedConstantWaveform"]

class Array:
    """
    A wrapper for a segment of memory in the Acadia hardware. Instances are 
    initialized with a region specifier that indicates which region of memory 
    the array should encapsulate (described further in :meth:`__init__`).
    The memory segment backing an instance of this class is not allocated 
    until :meth:`allocate` is explicitly called on it, allowing higher-level 
    functions to manipulate the array in ways that would require recompilation
    without having to instantiate a new object (and therefore lose any 
    references to it enclosed within other objects).
    """
    
    def __init__(self, 
                 dtype_or_resource, 
                 length: int = None, 
                 offset: int = None, 
                 region = None):
        """
        Create an empty reference to an array.
        
        :param dtype_or_resource: This can either be a data type from which
            (along with ``length``) memory will be allocated, or it can be 
            data to wrap.
        :type dtype_or_resource: ``str``, ``numpy.dtype``, ``type``, or 
            ``dict`` for dtype-like arguments, or ``numpy.ndarray``, ``Array``,
            ``memoryview``, ``bytes``, or ``bytearray`` for data-like 
            arguments. Additionally, any objects whose type is a subclass of
            ``ManagedMemory`` is a data-like argument. For arguments of type 
            ``Array``, a view of the underlying resource is stored in the new
            instance.
        :param length: Array length in number of elements. If 
            ``dtype_or_resource`` is a dtype-like argument, this indicates the
            number of elements to allocate and if it's a data-like argument, 
            this indicates how many elements of the underlying resource to wrap
            starting from ``offset``.
        :type length: int
        :param offset: When ``dtype_or_resource`` is a data-like argument, this
            specifies the offset within the data at which this wrapper will
            start. This is ignored for dtype-like arguments.
        :type offset: int
        :param region: The memory region in which to create the array. If an
            instance of :class:`Channel`, the type of the underlying memory 
            will be determined by the instance's ``memory_type`` attribute.
            Otherwise, one may pass a subclass of ``type`` which will be
            directly used to instantiate the array when allocated.
        :type region: :class:`Channel` or :class:`ManagedMemory`   
        """
        if isinstance(region, Channel):
            if not region.is_dac:
                raise ValueError(f"Attempted to create array for ADC"
                                 " channel. Because there is no dedicated"
                                 " memory for capture in Acadia, the capture"
                                 " memory region is not automatically able to"
                                 " be inferred. If you do not know what to put"
                                 " here, use the `PLDDR0Array` attribute of"
                                 " the `Acadia` object that this is capturing"
                                 " on.")
            self._class = region.memory_type
        elif isinstance(region, ManagedMemory):
            self._class = region
        elif region is None:
            self._class = None
        else:
            raise TypeError(f"Invalid region specifier {region}")
        
        if isinstance(dtype_or_resource, (str, np.dtype, type, dict)):
            if offset is not None:
                raise TypeError(f"Offset undefined for dtype-like initializers")
            self._dtype = np.dtype(dtype_or_resource)
            self._resource = None
            if length is not None:
                self.allocate(length)
            
        elif isinstance(dtype_or_resource, (np.ndarray, memoryview, bytes, bytearray)):
            if offset is not None:
                if length is not None:
                    self._resource = dtype_or_resource[offset:offset+length]
                else:
                    self._resource = dtype_or_resource[offset:]
            else:
                if length is not None:
                    self._resource = dtype_or_resource[:length]
                else:
                    self._resource = dtype_or_resource
                    
            self._dtype = dtype_or_resource.dtype if isinstance(dtype_or_resource, np.ndarray) else np.dtype('V')
            
        elif isinstance(type(dtype_or_resource), ManagedMemory):
            byte_offset = (dtype_or_resource.word_width*offset) if offset is not None else 0
            byte_length = (dtype_or_resource.word_width*length) if length is not None else dtype_or_resource.byte_length()
            
            self._resource = dtype_or_resource.view(byte_offset=byte_offset, byte_length=byte_length)
            self._dtype = np.dtype(f"V{dtype_or_resource.word_width // 8}")
            
        elif isinstance(dtype_or_resource, Array):
            Array.__init__(self, dtype_or_resource._resource, length, offset, region)
            
        else:
            raise TypeError(f"Undefined `Array` initializer for type"
                            f" {type(dtype_or_resource)}")
        
    def allocate(self, length):
        """
        Create an instance of the underlying memory type, thereby reserving a
        resource ID for that type and notifying the compiler to reserve memory
        (in the case of a hardware array). Note that compilation is necessary
        after calling this function.
        
        :param length: Array length in elements
        :type length: int
        :param dtype: Memory type of the array
        :type dtype: np.dtype
        """
        
        if self.allocated():
            raise ValueError("Attempted re-allocation of non-free memory")
                
        if self._class is None:
            self._resource = np.empty(shape=length, dtype=self._dtype)
        elif isinstance(self._class, ManagedMemory):
            # ManagedMemory objects always use bytes for size regardless of the dtype
            self._resource = self._class(size=length*self._dtype.itemsize, dtype=self._dtype)
        else:
            raise TypeError(f"Unable to instantiate array of type {self._class}")
        
    def allocated(self):
        """
        :return: ``True`` if the underlying memory resource has been allocated
        :rtype: bool
        """
        return self._resource is not None
        
    @property    
    def memory(self):
        """
        Retrieve a reference to the underlying resource memory, if present.
        
        :raises: ``ValueError`` if the memory has not been allocated
        :raises: ``AttributeError`` if the memory is not mapped, determined
            by checking whether the underlying resource has a memory attribute.
        
        """
        if not self.allocated():
            raise ValueError("Attempted access of unallocated array")
        
        if hasattr(self._resource, "memory"):
            return self._resource.memory
        
        return self._resource
    
    @property
    def dtype(self):
        return self._dtype
    
    def free(self):
        """
        Removed internal reference to underlying memory resources, allowing 
        reallocation.
        """
        self._resource = None
                
    def __getitem__(self, k):
        return self.memory[k]
    
    def __setitem__(self, k, v):
        self.memory[k] = v
        
    def __len__(self):
        return len(self.memory)
    
    @property
    def __array_interface__(self):
        return self.memory.__array_interface__
    
    def __array__(self):
        return self.memory.__array__()
    
    def word_address(self):
        if not self.allocated():
            raise ValueError("Attempted address access of unallocated array")
        
        if not hasattr(self._resource, "word_address"):
            raise AttributeError(f"Attempted to obtain word address of"
                                 f" non-managed resource of type"
                                 f" {type(self._resource)}.")

        return self._resource.word_address()
    
    def byte_address(self):
        if not self.allocated():
            raise ValueError("Attempted address access of unallocated array")
        
        if not hasattr(self._resource, "byte_address"):
            raise AttributeError(f"Attempted to obtain byte address of"
                                 f" non-managed resource of type"
                                 f" {type(self._resource)}.")
        
        return self._resource.byte_address()
    
    def word_length(self):
        if not self.allocated():
            raise ValueError("Attempted length access of unallocated array")
        
        if hasattr(self._resource, "word_length"):
            return self._resource.word_length()
        
        return len(self._resource)
    
    def byte_length(self):
        if not self.allocated():
            raise ValueError("Attempted length access of unallocated array")
        
        if hasattr(self._resource, "byte_length"):
            return self._resource.byte_length()
        
        return self.word_length() * self._dtype.itemsize
    
    def split(self, idx):
        """
        Create two new :class:`Array` objects wrapping the memory underlying 
        this one. The new objects create "views" into this one and, when 
        instances of a type inherited from :class:`ManagedMemory`, are not 
        tracked.
        
        :param idx: Index in the array at which to split. The first piece will
            contain indices ``0:idx-1`` and the second piece will contain 
            indices ``idx:``
        :type idx: int
        """
        if idx == 0 or idx == self.word_length():
            return (self,)
        
        piece1 = Array(self._resource, 
                       length=idx, 
                       offset=0)
        piece2 = Array(self._resource, 
                       length=self.word_length()-idx, 
                       offset=idx)
        
        return piece1,piece2
        
class Waveform(Array):
    """
    An extension of :class:`Array` that is intended to sample functions of 
    time. The data underlying the instance is expected to be pairs of integers,
    so the chosen dtype is raw bytes comprised of the two quadratures packed 
    together.
    """
    
    def __init__(self, 
                 channel: Channel = None, 
                 length: int = None, 
                 region = None, 
                 data = None,
                 quadrature_width: int = 16):
        """
        :param channel: An object of type :class:`Channel` from which the 
            sampling parameters will be extracted.
        :type channel: :class:`Channel`
        :param length: The length of the waveform in samples. If omitted,
            :meth:`allocate` must be called manually.
        :param region: The memory region in which to create the array. If an
            instance of :class:`Channel`, the type of the underlying memory 
            will be determined by the instance's ``memory_type`` attribute.
            Otherwise, one may pass a subclass of ``type`` which will be
            directly used to instantiate the array when allocated.
        :type region: :class:`Channel` or :class:`ManagedMemory`
        :param data: If not ``None``, this will be provided as the 
            ``dtype_or_resource`` argument for the :class:`Array` initializer.
        :type data: ``numpy.ndarray`` 
        :param quadrature_width: The width of the integer data comprising the 
            hardware sample encoding, in bits per quadrature.
        :type quadrature_width: int
        """
        
        self._channel = channel

        if data is not None:
            if not hasattr(data, "dtype"):
                raise TypeError("Provided data resource must have a `dtype` property.")
            
            if data.dtype.kind != 'V':
                raise TypeError("Initializing a Waveform with data requires"
                                " the data to be in sample units. Please use"
                                " `Waveform.from_complex()` to initialize a"
                                " waveform using complex floats.")
                
            super().__init__(data)
        else:           
            sample_type = np.dtype(f'V{2 * quadrature_width // 8}')
            super().__init__(sample_type, length=length, region=region)
    
    def dma_parameters(self):
        """
        Generate a `dict` of parameters for the :class:`Acadia` `generate` 
        method.
        """
        if not isinstance(self._channel, Channel):
            raise TypeError(f"DMA parameters may only be requested for"
                            " `Waveform` objects instantiated with `Channel`"
                            " instances")
            
        if self.word_address() % (self._channel.interface_width_bytes // 4) != 0:
            raise ValueError("Requested DMA parameters for Waveform with"
                             f" misaligned word address (address"
                             f" {self.word_address():X})")
            
        if self.byte_length() % self._channel.interface_width_bytes != 0:
            raise ValueError("Requested DMA parameters for Waveform with"
                             f" misaligned length ("
                             f" {self.byte_length():X} bytes)")
        
        return [{
            "channel": self._channel,
            "length": self.byte_length() // self._channel.interface_width_bytes,
            "word_address": (self.word_address() if self._channel.is_dac else 0) // (self._channel.interface_width_bytes // 4)
        }]
        
    def split(self, split_time):
        """
        Produce two new instances that wrap disparate segments of the 
        underlying memory.
        """
        # ``seconds_to_samples`` will make sure that it's an integer number of cycles
        split_idx = self._channel.seconds_to_samples(split_time)
        arrays = super().split(split_idx)
        return tuple(Waveform(self._channel, data=arr) for arr in arrays)
        
    @staticmethod
    def to_complex(input: Union[Array, np.ndarray], 
                   output: Union[Array, np.ndarray, np.dtype, int] = 64, 
                   scale: float = 1):
        """
        Unpack the integer sample data in memory into complex floating-point 
        numbers.
        
        :param output: This can be either a numpy array with a complex dtype to
            pack the data into, or a dtype itself (in which case an output 
            array will be allocated).
        :type output:
        """
        if not hasattr(input, "dtype"):
            raise TypeError(f"Input must have a dtype (input is of type"
                            f" {type(input)})")
        if hasattr(input, "memory"):
            input_memory = input.memory
        elif isinstance(input, np.ndarray):
            input_memory = input
        else:
            raise TypeError(f"Invalid input type for `to_complex`: {type(input)}")
        
        if input_memory.dtype.kind != "V":
            raise TypeError(f"Input dtype must be void (found kind"
                            f" {input_memory.dtype.kind})")
        
        int_type = np.dtype(f"<i{input_memory.dtype.itemsize // 2}")

        if isinstance(output, int):
            output = np.dtype(f"c{output // 8}")

        if isinstance(output, np.dtype):
            output = np.empty(input_memory.shape, dtype=output)
        elif not hasattr(output, "dtype"):
            raise TypeError(f"Output must have (or be) a dtype, got type"
                            f" {type(output)}")
        
        if hasattr(output, "memory"):
            output_memory = output.memory
        elif isinstance(output, np.ndarray):
            output_memory = output
        else:
            raise TypeError(f"Invalid output type for `to_complex`:"
                            f" {type(output)} (memory type {type(output_memory)})")
        
        if output_memory.dtype.kind != "c":
            raise TypeError(f"Output dtype must be complex (found kind"
                            f" {output_memory.dtype.kind})")
        
        float_type = np.dtype(f"<f{output_memory.dtype.itemsize // 2}")

        scale *= 2**(int_type.itemsize*8 - 1) - 1 
        np.divide(input_memory.view(int_type), 
                    scale, 
                    out=output_memory.view(float_type), 
                    dtype=float_type)
            
        return output
    
    @staticmethod
    def from_complex(input: Union[Array, np.ndarray], 
                     output: Union[Array, np.ndarray, np.dtype, int] = 32, 
                     scale: float = 1):
        """
        Pack the complex floating-point data in an array into integer samples.
        """
        if not hasattr(input, "dtype"):
            raise TypeError(f"Input must have a dtype (input is of type"
                            f" {type(input)})")
        if hasattr(input, "memory"):
            input_memory = input.memory
        elif isinstance(input, np.ndarray):
            input_memory = input
        else:
            raise TypeError(f"Invalid input type for `from_complex`: {type(input)}")
        
        if input_memory.dtype.kind != "c":
            raise TypeError(f"Input dtype must be complex (found kind"
                            f" {input_memory.dtype.kind})")
        
        float_type = np.dtype(f"<f{input_memory.dtype.itemsize // 2}")

        if isinstance(output, int):
            output = Waveform(length=len(input_memory), quadrature_width=(output // 2))
        elif isinstance(output, np.dtype):
            output = Waveform(length=len(input_memory), quadrature_width=(8 * output.itemsize // 2))
        elif not hasattr(output, "dtype"):
            raise TypeError(f"Output must have (or be) a dtype, got type"
                            f" {type(output)}")
        
        if hasattr(output, "memory"):
            output_memory = output.memory
        elif isinstance(output, np.ndarray):
            output_memory = output
        else:
            raise TypeError(f"Invalid output type for `from_complex`: {type(output)}")
        
        if output_memory.dtype.kind != "V":
            raise TypeError(f"Output dtype must be void (found kind"
                            f" {output_memory.dtype.kind})")
        
        int_type = np.dtype(f"<i{output_memory.dtype.itemsize // 2}")

        scale *= 2**(int_type.itemsize*8 - 1) - 1 
        scaled = (input_memory * scale).view(float_type) 
                
        np.rint(scaled, out=output_memory.view(int_type), casting="unsafe")
        return output
    
class ConstantWaveform(Waveform):
    """
    A waveform with a constant value.
    """
    
    def __init__(self, 
                 channel: Channel, 
                 length_seconds: float):
        """
        :param channel: Channel for the waveform
        :type channel: :class:`Channel`
        :param length: Length of the constant in seconds
        :type length: float or :class:`Symbol` wrapping a float
        """
        self._length_seconds = length_seconds
        self._channel = channel
        super().__init__(channel, 
                         length=(channel.interface_width_bytes // 4), 
                         region=channel)
        
    def dma_parameters(self):
        """
        Generate a `dict` of parameters for the :class:`Acadia` `generate` method.
        """
        # We'll use an Operation to construct the length so that it can be dynamically
        # changed while only requiring reassembly
        length_cycles = Operation(Channel.seconds_to_bytes, 
                                self._channel, 
                                self._length_seconds) // self._channel.interface_width_bytes
        
        return [{
            "channel": self._channel,
            "length": length_cycles,
            "word_address": self.word_address() // (self._channel.interface_width_bytes // 4),
            "fixed": True
        }]
    
    def __setitem__(self, k, v):
        v_array = np.array([v]*len(self), dtype=np.complex64)
        v_samples = Waveform.from_complex(v_array, np.dtype('V4'))
        super().__setitem__(slice(0,len(self)), v_samples)
        
class WindowedConstantWaveform(Waveform):
    """
    A constant waveform whose sharp rise and fall events are tapered with a 
    window function. This is carried out by
    """
    def __init__(self, 
                 channel: Channel, 
                 constant_length_seconds: float = None,
                 window_length_seconds: float = None):
        """
        :param channel: Channel on which to apply the waveform
        :type channel: :class:`Channel`
        :param window_length_seconds: The total length of the windowed portion
            of the waveform (the sum of the regions before and after the 
            rectangular segment)
        :param constant_length_seconds: The length of the rectangular portion
            of the waveform
        :type constant_length_seconds: float
        :type window_length_seconds: float
        :param window_function: Callable with which to populate the window 
            memory. 
        """

        self._window_length_seconds = window_length_seconds
        super().__init__(channel, 
                         length=channel.seconds_to_bytes(window_length_seconds) // 4, 
                         region=channel)
        self._constant = ConstantWaveform(channel, constant_length_seconds)
        
        # `seconds_to_bytes` will check whether we have an integer number of cycles    
        self.split_cycle = channel.seconds_to_bytes(window_length_seconds / 2) // channel.interface_width_bytes
        
    def dma_parameters(self):
        ramp_first = super().dma_parameters()
        ramp_first[0]["length"] = self.split_cycle
        
        ramp_second = super().dma_parameters()
        ramp_second[0]["length"] -= self.split_cycle
        ramp_second[0]["word_address"] += self.split_cycle
        
        return ramp_first + self._constant.dma_parameters() + ramp_second
    
    def __setitem__(self, k, v):
        split_sample_idx = self.split_cycle * self._channel.interface_width_bytes // 4
        self._constant.memory.fill(v[split_sample_idx])
    