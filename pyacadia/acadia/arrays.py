from contextlib import contextmanager

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
    
    def __init__(self, dtype_or_resource, length=None, offset=None, region=None, buffer_dtype=None):
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
        :param buffer_dtype: If not ``None``, an internal buffer will be 
            created with the same number of elements as the underlying 
            resource, but with a dtype specified by this parameter
        :type buffer_dtype: Any valid argument to the initializer of
            ``numpy.dtype``        
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
        
        self._buffer = None
        self._buffer_dtype = buffer_dtype
        self._buffer_mode = False
        
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
                    
            self._dtype = dtype_or_resource.dtype if isinstance(dtype_or_resource, np.ndarray) else np.uint8
            self._axis = np.arange(len(self._resource), dtype=np.float32)
            
        elif isinstance(type(dtype_or_resource), ManagedMemory):
            byte_offset = (dtype_or_resource.word_width*offset) if offset is not None else 0
            byte_length = (dtype_or_resource.word_width*length) if length is not None else dtype_or_resource.byte_length()
            
            self._resource = dtype_or_resource.view(byte_offset=byte_offset, byte_length=byte_length)
            self._dtype = np.dtype(f"V{dtype_or_resource.word_width // 8}")
            self._axis = np.arange(self._resource.word_length(), dtype=np.float32)
            
        elif isinstance(dtype_or_resource, Array):
            Array.__init__(self, dtype_or_resource._resource, length, offset, region, buffer_dtype)
            self._buffer = dtype_or_resource._buffer
            self._buffer_mode = dtype_or_resource._buffer_mode
            
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
                
        self._axis = np.arange(length, dtype=np.float32)
                
        if self._class is None:
            self._resource = np.empty(shape=length, dtype=self._dtype)
        elif isinstance(self._class, ManagedMemory):
            # ManagedMemory objects always use bytes for size regardless of the dtype
            self._resource = self._class(size=length*self._dtype.itemsize, dtype=self._dtype)
        else:
            raise TypeError(f"Unable to instantiate array of type {self._class}")
        
        if self._buffer_dtype is not None:
            self._buffer = np.empty(length, dtype=self._buffer_dtype)
        
    def allocated(self):
        """
        :return: ``True`` if the underlying memory resource has been allocated
        :rtype: bool
        """
        return self._resource is not None
    
    @property
    def buffered(self):
        """
        :return: ``True`` if the underlying memory is buffered with an internal
            cache
        :rtype: bool
        """
        return self._buffer is not None and self._buffer_mode
    
    @buffered.setter
    def buffered(self, v):
        if v and (self._buffer is None):
            if self._buffer_dtype is None:
                self._buffer_dtype = self._dtype
            if isinstance(self._class, ManagedMemory):
                self._buffer = np.empty(shape=(self._resource.word_length(),), 
                                        dtype=self._buffer_dtype)
            else:
                self._buffer = np.empty(shape=self._resource.shape, 
                                        dtype=self._buffer_dtype)
                 
        self._buffer_mode = v
    
    @contextmanager
    def buffer(self):
        """
        Operate on the array in buffered mode; any accesses or modifications 
        affect only the internal cache rather than the underlying resource 
        directly. To update the hardware resource, call :meth:`flush`.
        """
        tmp = self.buffered
        self.buffered = True
        yield
        self.buffered = tmp
        
    @contextmanager
    def unbuffer(self):
        """
        Operate on the array in unbuffered mode; any accesses or modifications 
        will directly update the hardware resource.
        """
        tmp = self.buffered
        self.buffered = False
        yield
        self.buffered = tmp
        
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
        
        if self.buffered:
            return self._buffer
        
        if hasattr(self._resource, "memory"):
            return self._resource.memory
        
        return self._resource
    
    def flush(self, **kwargs):
        """
        Transfer any data in an internal cache into hardware. If there is no
        buffer, no action is taken. Subclasses may add custom behavior that 
        accepts keyword arguments, but by default these are ignored.
        """
        if self.buffered and self.allocated():
            tmp = self._buffer_mode
            self._buffer_mode = False
            self.memory[:] = self._buffer[:]
            self._buffer_mode = tmp
    
    @property
    def dtype(self):
        return self._dtype
    
    def free(self):
        """
        Removed internal reference to underlying memory resources, allowing 
        reallocation.
        """
        self._resource = None
        
    def axis(self):
        if not self.allocated():
            raise ValueError(f"Unable to retrieve axis of unallocated array.")
        
        return self._axis
                
    def __getitem__(self, k):
        if not self.allocated():
            raise ValueError("Attempted access of unallocated array")
        
        if self._buffer_mode:
            return self._buffer[k]
        
        return self._resource[k]
    
    def __setitem__(self, k, v):
        if not self.allocated():
            raise ValueError("Attempted access of unallocated array")
        
        if self._buffer_mode:
            self._buffer[k] = v
        
        self._resource[k] = v
        
    def __len__(self):
        """
        :return: The length of the array in elements.
        :rtype: int
        """
        return self.word_length()
    
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
        
        # if self._buffer_mode:
        #     raise ValueError(f"Attempted to access byte address of `Array` in"
        #                      f" buffer mode.")
        
        if not hasattr(self._resource, "byte_address"):
            raise AttributeError(f"Attempted to obtain byte address of"
                                 f" non-managed resource of type"
                                 f" {type(self._resource)}.")
        
        return self._resource.byte_address()
    
    def word_length(self):
        if not self.allocated():
            raise ValueError("Attempted length access of unallocated array")
        
        if self._buffer_mode:
            return len(self._buffer)
        
        if hasattr(self._resource, "word_length"):
            return self._resource.word_length()
        
        return len(self._resource)
    
    def byte_length(self):
        if not self.allocated():
            raise ValueError("Attempted length access of unallocated array")
        
        if not self._buffer_mode and hasattr(self._resource, "byte_length"):
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
        
        piece1 = Array(self._resource, idx, 0, buffer_dtype=self._buffer_dtype)
        piece2 = Array(self._resource, self.word_length()-idx, idx, buffer_dtype=self._buffer_dtype)
        
        if self._buffer is not None:
            piece1._buffer = self._buffer[:idx]
            piece2._buffer = self._buffer[idx:]
            
        piece1.buffered = self.buffered
        piece2.buffered = self.buffered
        
        return piece1,piece2
    
class ProceduralArrayMixin:
    """
    A mixin class for hardware arrays with efficient routines for dynamically
    populating them.
    """
    
    def set_generator(self, generator, signature):
        """
        Assign a generator.
        
        :param generator: A function that can be used to populate the array
        :type generator: callable
        :param signature: A string describing the call signature for the 
            generator. Options are:
            
            - ``in_place``: f(memory, *args, **kwargs) -> None
            - ``in_place_axis``: f(memory, axis, *args, **kwargs) -> None
            - ``axis``: f(axis, *args, **kwargs) -> output
            - ``scipy``: f(len(axis), *args, **kwargs) -> output
            - ``ctypes``: f(len(axis), memory.ctypes.data, axis.ctypes.data, *args, **kwargs) -> None
            
        :type signature: str
        """        
        try:
            self._signature_idx = ["in_place", 
                             "in_place_axis", 
                             "axis", 
                             "scipy",
                             "ctypes"].index(signature)
        except ValueError:
            raise ValueError(f"Invalid generator signature {signature}")
        
        self._generator = generator
        
    def populate(self, *args, flush_params={}, **kwargs):
        """
        Populate the underlying array resource, passing any arguments to the
        encapsulated generator function. The object instance must implement
        the method ``memory`` with a similar signature to ``Array.memory``.
        By default, :meth:`flush` is called with any keyword arguments passed
        in `flush_params`. This can be set to `None` to disable this behavior.
        
        :raises: ``ValueError`` if the array does not have a generator
        """    
        
        if self._generator is None:
            raise ValueError("Attempted to populate array without generator")
        
        if self._signature_idx == 0:
            # in_place
            self._generator(self.memory, *args, **kwargs)
        elif self._signature_idx == 1:
            # in_place_axis
            self._generator(self.memory, self.axis(), *args, **kwargs)
        elif self._signature_idx == 2:
            # axis
            self.memory[:] = self._generator(self.axis(), *args, **kwargs)
        elif self._signature_idx == 3:
            # scipy
            self.memory[:] = self._generator(len(self.axis()), *args, **kwargs)
        elif self._signature_idx == 4:
            # ctypes    
            self._generator(len(self.axis()), 
                            self.memory.ctypes.data, 
                            self.axis().ctypes.data,
                            *args, **kwargs)   
            
        if flush_params is not None:
            self.flush(**flush_params)
        
class Waveform(Array):
    """
    An extension of :class:`Array` that is intended to sample functions of time
    using parameters extracted from :class:`Channel` objects. The data 
    underlying the instance is expected to be pairs of integers, so the chosen
    dtype is raw bytes comprised of the two complex quadratures packed 
    together.
    """
    
    def __init__(self, 
                 sample_rate_or_channel: float = None, 
                 length_seconds: float = None, 
                 region = None, 
                 data = None,
                 integer_width: int = 16,
                 float_width: int = 32):
        """
        :param sample_rate_or_channel: When of type ``float``, this is the sample rate
            used to derive axis values and allocate memory. Alternatively, 
            this can be an object of type :class:`Channel` from which the 
            sampling parameters will be extracted. This may be ``None``, in
            which case no axis will be created.
        :type sample_rate_or_channel: :class:`Channel`
        :param length_seconds: The length of the waveform in seconds. If omitted,
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
        :param integer_width: The width of the integer data comprising the 
            hardware sample encoding, in bits per quadrature.
        :type integer_width: int
        :param float_width: The width of the floating-point data used for
            bufering and conversion, in bits per quadrature.
        :type float_width: int
        """
        
        self._sample_rate_or_channel = sample_rate_or_channel
        
        if data is not None:
            if length_seconds is not None:
                raise ValueError(f"When initializing with data the length must"
                                 f" be inferred from the underlying memory"
                                 f" (received {length_seconds})")
                
            if isinstance(data, np.ndarray) or isinstance(data, Array):
                if data.dtype.kind == "i":
                    self._int_type = data.dtype
                    self._sample_type = np.dtype(f'V{2*self._int_type.itemsize}')
                    self._float_type = np.dtype(f'<f{float_width//8}')
                    self._complex_type = np.dtype(f'<c{2*float_width//8}')
                    super().__init__(data, buffer_dtype=self._complex_type)
                elif data.dtype.kind == "V":
                    self._sample_type = data.dtype
                    self._int_type = np.dtype(f'<i{self._sample_type.itemsize//2}')
                    self._float_type = np.dtype(f'<f{float_width//8}')
                    self._complex_type = np.dtype(f'<c{2*float_width//8}')
                    super().__init__(data, buffer_dtype=self._complex_type)
                elif data.dtype.kind == "c":
                    self._int_type = np.dtype(f'<i{integer_width//8}')
                    self._sample_type = np.dtype(f'V{2*self._int_type.itemsize}')
                    self._float_type = np.dtype(f'<f{data.itemsize//2}')
                    self._complex_type = data.dtype
                    super().__init__(self._sample_type, 
                                     length=len(data), 
                                     buffer_dtype=data.dtype)
                    self._buffer = data
                else:
                    raise TypeError(f"Unable to construct Waveform from"
                                    f" array of dtype {data.dtype}")
            else:
                raise TypeError(f"Waveforms can only be constructed from"
                                f" numpy arrays (received type {type(data)})")
            
            if isinstance(self._sample_rate_or_channel, float):
                self._axis = np.arange(len(data)) / self._sample_rate_or_channel
            elif isinstance(self._sample_rate_or_channel, Channel):
                sample_time = self._sample_rate_or_channel.samples_to_seconds(1)
                self._axis = np.arange(len(data)) * sample_time
            else:
                self._axis = None
            
        else:
            # We can pass length_seconds to `__init__` because it'll only be used
            # as an argument to `allocate`
            self._axis = None
            self._length_seconds = None
            
            self._int_type = np.dtype(f'<i{integer_width//8}')
            self._sample_type = np.dtype(f'V{2*self._int_type.itemsize}')
            self._float_type = np.dtype(f'<f{float_width//8}')
            self._complex_type = np.dtype(f'<c{2*float_width//8}')
            
            super().__init__(self._sample_type, 
                             length=length_seconds, 
                             region=region, 
                             buffer_dtype=self._complex_type)
        
        # Waveforms must be buffered so that the buffer can convert between
        # floating-point and fixed-point values    
        self.buffered = True
               
    def allocate(self, length_seconds):
        """
        Create an instance of the underlying memory type, thereby reserving a
        resource ID for that type and notifying the compiler to reserve memory
        (in the case of a hardware array).
        
        :param length: Waveform length in seconds
        :type length: float
        """
        if isinstance(self._sample_rate_or_channel, float):
            samples = self._sample_rate_or_channel * length_seconds
            if round(samples, 2) != samples:
                raise ValueError(f"Obtained non-integer number of samples"
                                 f" ({samples}) for Waveform length"
                                 f" {length_seconds} at sample rate"
                                 f" {self._sample_rate_or_channel}")
            super().allocate(samples)
        elif isinstance(self._sample_rate_or_channel, Channel):
            # ``seconds_to_samples`` will make sure that it's an integer number of cycles
            super().allocate(self._sample_rate_or_channel.seconds_to_samples(length_seconds))
        else:
            raise ValueError(f"Unable to allocate `Waveform` with sample"
                             f" rate/channel of type {type(self._sample_rate_or_channel)}.")
        
        # Scale the element axis by the sample time
        self._axis = np.arange(len(self._axis)) * (length_seconds / len(self._axis))
    
    def dma_parameters(self):
        """
        Generate a `dict` of parameters for the :class:`Acadia` `generate` method.
        """
        if not isinstance(self._sample_rate_or_channel, Channel):
            raise TypeError(f"DMA parameters may only be requested for `Waveform` objects instantiated with `Channel` instances")
        
        return [{
            "channel": self._sample_rate_or_channel,
            "length": self.byte_length() // self._sample_rate_or_channel.interface_width_bytes,
            "word_address": (self.word_address() if self._sample_rate_or_channel.is_dac else 0) // (self._sample_rate_or_channel.interface_width_bytes // 4)
        }]
        
    def split(self, split_time):
        """
        Produce two new instances that wrap disparate segments of the 
        underlying memory.
        """
        # ``seconds_to_samples`` will make sure that it's an integer number of cycles
        if isinstance(self._sample_rate_or_channel, float):
            split_idx = self._sample_rate_or_channel * split_time
            if round(split_idx, 2) != split_idx:
                raise ValueError(f"Obtained non-integer sample time"
                                 f" ({split_idx}) for Waveform split time"
                                 f" {split_time} at sample rate"
                                 f" {self._sample_rate_or_channel}")
        elif isinstance(self._sample_rate_or_channel, Channel):
            split_idx = self._sample_rate_or_channel.seconds_to_samples(split_time)
        else:
            raise TypeError(f"Can't split Waveform with sample rate/Channel of"
                            f" type {type(self._sample_rate_or_channel)}")
            
        arrays = super().split(split_idx)
        return tuple(Waveform(self._sample_rate_or_channel, data=arr) for arr in arrays)
        
    def unpack(self, out=None, scale=1):
        """
        Unpack the integer sample data in memory into complex floating-point 
        numbers.
        
        :param precision: Floating-point precision used for numerical data.
            This must correspond to a numpy dtype.
        """
        
        if out is not None:
            if out.dtype != self._complex_type:
                raise TypeError(f"Expected output to have dtype"
                                f" {self._complex_type}; found dtype"
                                f" {out.dtype}")

            with self.unbuffer():
                np.copyto(dst=out.view(self._float_type), 
                        src=self.memory.view(self._int_type))
            out /= scale * (2**15)
            
            return out

        with self.unbuffer():
            buf = self.memory.view(self._int_type).astype(self._float_type)
            
        buf /= scale * (2**15)
        return buf.view(self._complex_type)
    
    def pack(self, out=None, scale=1):
        """
        Pack the complex floating-point data in an array into integer samples.
        """
        
        if out is not None:
            if out.dtype != self._sample_type:
                raise TypeError(f"Expected output to have dtype"
                                f" {self._sample_type}; found dtype"
                                f" {out.dtype}")
                
            with self.buffer():
                np.rint(self.memory.view(self._float_type) * (scale * (2**15)), 
                        out=out.view(self._int_type),
                        casting="unsafe")
            return out
        
        with self.buffer():
            buf = self.memory.view(self._float_type) * (scale * (2**15))
            
        return buf.astype(self._int_type).view(self._sample_type)
    
    def flush(self, **kwargs):
        # Get a reference to the internal memory that we can pack
        # data into
        self.buffered = False
        mem = self.memory
        self.buffered = True
        self.pack(out=mem,
                  scale=(kwargs["scale"] if "scale" in kwargs else 1))
        
        
class DecimatedWaveform(Waveform):
    """
    An extension of :class:`Waveform` for waveforms decimated by stream DSP modules.
    """
    
    def __init__(self, 
                 sample_rate_or_channel=None, 
                 length_seconds=None, 
                 region=None, 
                 decimation=None, 
                 data=None, 
                 float_width=32):   
        
        if decimation is not None:
            if not isinstance(sample_rate_or_channel, Channel):
                raise TypeError(f"Instantiating a DecimatedWaveform with a decimation"
                                f" value is only supported when `sample_rate_or_channel`"
                                f" is of type `Channel` (received"
                                f" {type(sample_rate_or_channel)})")
            if decimation % (sample_rate_or_channel.interface_width_bytes // 4) != 0:
                raise ValueError(f"Decimation must be a multiple of"
                                f" {sample_rate_or_channel.interface_width_bytes // 4}"
                                f" (received {decimation})")
        
        self._decimation = decimation        
        
        super().__init__(sample_rate_or_channel=sample_rate_or_channel, 
                         length_seconds=length_seconds, 
                         region=region, 
                         data=data,
                         integer_width=32,
                         float_width=float_width)  
    
    def allocate(self, length_seconds):
        """
        Create an instance of the underlying memory type, thereby reserving a
        resource ID for that type and notifying the compiler to reserve memory
        (in the case of a hardware array).
        
        :param length_seconds: Waveform length in seconds
        :type length_seconds: float
        """
        
        if self._decimation is None:
            raise ValueError(f"May not allocate DecimatedWaveform without"
                             f" a decimation value.")
        
        super().allocate(length_seconds / self._decimation)
        self._axis *= self._decimation
        
    def dma_parameters(self):
        params = super().dma_parameters()
        # The length of the DMA valid period is determined by memory size, 
        # which has been reduced by the decimation factor in our overridden `allocate`
        params[0]["length"] *= self._decimation
        return params
        
class ConstantWaveform(Array):
    """
    A waveform with a constant value.
    """
    
    def __init__(self, 
                 channel: Channel, 
                 length_seconds: float = None):
        """
        :param channel: Channel for the waveform
        :type channel: :class:`Channel`
        :param length: Length of the constant in seconds
        :type length: float or :class:`Symbol` wrapping a float
        """
        self._channel = channel
        self._length_seconds = length_seconds
        super().__init__(np.dtype('V4'), 
                         length=channel.interface_width_bytes // 4, 
                         region=channel.memory_type)
        
    def populate(self, 
                 amplitude: float = None, 
                 length_seconds: float = None):
        """
        Set the complex amplitude and length of the constant.
        
        :param value: Waveform value
        :type value: complex
        
        """
        # Load the DAC memory with the new amplitude
        if amplitude is not None:
            arr = np.empty(self._channel.bytes_to_samples(self._channel.interface_width_bytes), np.complex64)
            arr.fill(amplitude)
            Channel.to_samples(arr, out=self.memory)
        if length_seconds is not None:
            self._length_seconds = length_seconds
        
    def dma_parameters(self):
        """
        Generate a `dict` of parameters for the :class:`Acadia` `generate` method.
        """        
        if self._length_seconds is None:
            raise ValueError(f"Must provide length of `ConstantWaveform`"
                             " prior to requesting DMA parameters")    
        
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
        
        
class WindowedConstantWaveform(Waveform, ProceduralArrayMixin):
    """
    A constant waveform whose sharp rise and fall events are tapered with a 
    window function. In contrast to the
    typical interface of :class:`ProceduralArrayMixin`, the signature of the 
    window function is chosen to match that of ``scipy.signal.windows``.
    """
    def __init__(self, 
                 channel: Channel, 
                 window_length_seconds: float = None, 
                 window_function: callable = None, 
                 window_function_signature: str = "scipy",
                 constant_length_seconds: float = None):
        """
        :param channel: Channel on which to apply the waveform
        :type channel: :class:`Channel`
        :param window_length_seconds: The total length of the windowed portion
            of the waveform (the sum of the regions before and after the 
            rectangular segment)
        :type window_length_seconds: float
        :param window_function: Callable with which to populate the window 
            memory. 
        :param constant_length_seconds: The length of the rectangular portion
            of the waveform
        :type constant_length_seconds: float
        """

        super().__init__(channel, 
                         length_seconds=window_length_seconds, 
                         region=channel.memory_type)
        self.set_generator(window_function, window_function_signature)
        self._constant = ConstantWaveform(channel, constant_length_seconds)
        
        # `seconds_to_bytes` will check whether we have an integer number of cycles    
        self.split_cycle = channel.seconds_to_bytes(window_length_seconds / 2) // channel.interface_width_bytes
        
    def populate(self, amplitude=None, constant_length_seconds=None, *args, **kwargs):
        super().populate(*args, flush_params={"scale": amplitude}, **kwargs)
        self._constant.populate(amplitude, constant_length_seconds)
        
    def dma_parameters(self):
        ramp_first = super().dma_parameters()
        ramp_first[0]["length"] = self.split_cycle
        
        ramp_second = super().dma_parameters()
        ramp_second[0]["length"] -= self.split_cycle
        ramp_second[0]["word_address"] += self.split_cycle
        
        return ramp_first + self._constant.dma_parameters() + ramp_second
    