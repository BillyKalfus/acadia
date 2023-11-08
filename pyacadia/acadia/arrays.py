
import numpy as np

from .channel import Channel
from .compiler import ManagedMemory

__all__ = ["Array", 
           "ProceduralArrayMixin", 
           "Waveform", 
           "ProceduralWaveform", 
           "ConstantWaveform"]

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
    
    def __init__(self, dtype, size=None, region=None):
        """
        Create an empty reference to an array.
        
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
        
        # The actual underlying memory resource will be stored here
        self._resource = None
        
        self._dtype = dtype
        
        if size is not None:
            self.allocate(size)
        
    def allocate(self, size: int):
        """
        Create an instance of the underlying memory type, thereby reserving a
        resource ID for that type and notifying the compiler to reserve memory
        (in the case of a hardware array). Note that compilation is necessary
        after calling thsi function.
        
        :param size: Array size in bytes
        :type size: int
        :param dtype: Memory type of the array to cast
        :type dtype: np.dtype
        """
        self._size = size
        
        if self.allocated():
            raise ValueError("Attempted re-allocation of non-free memory")
                
        if self._class is None:
            self._resource = np.empty(shape=(self._size // self._dtype(0).nbytes,), 
                                      dtype=self._dtype)
        else:
            self._resource = self._class(size=self._size, dtype=self._dtype)
            
        self._axis = np.arange(self._size)
            
    def allocated(self):
        """
        :return: ``True`` if the underlying memory resource has been allocated
        :rtype: bool
        """
        return self._resource is not None
    
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
    
    def dtype(self):
        return self._dtype
                
    def __getitem__(self, k):
        if not self.allocated():
            raise ValueError("Attempted access of unallocated array")
        
        return self._resource[k]
    
    def __setitem__(self, k, v):
        if not self.allocated():
            raise ValueError("Attempted access of unallocated array")
        
        self._resource[k] = v
        
    def __len__(self):
        """
        :return: The length of the array in bytes.
        :rtype: int
        """
        
        if not self.allocated():
            raise ValueError("Attempted to access length of unallocated array")
        return self._size
    
    def memory(self):
        """
        Retrieve a reference to the underlying resource memory, if present.
        
        :raises: ``ValueError`` if the memory has not been allocated
        :raises: ``AttributeError`` if the memory is not mapped, determined
            by checking whether the underlying resource has a memory attribute.
        
        """
        if not self.allocated():
            raise ValueError("Attempted access of unallocated array")
        
        if not hasattr(self._resource, "memory"):
            raise AttributeError("Attempted access of unmapped memory.")
        
        return self._resource.memory
    
    def word_address(self):
        if not self.allocated():
            raise ValueError("Attempted address access of unallocated array")
        
        return self._resource.word_address()
    
    def byte_address(self):
        if not self.allocated():
            raise ValueError("Attempted address access of unallocated array")
        
        return self._resource.byte_address()
    
    def word_length(self):
        if not self.allocated():
            raise ValueError("Attempted length access of unallocated array")
        
        return self._resource.word_length()
    
    def byte_length(self):
        if not self.allocated():
            raise ValueError("Attempted length access of unallocated array")
        
        return self._resource.byte_length()

        
class ProceduralArrayMixin:
    """
    A mixin class for hardware arrays with efficient routines for dynamically
    populating them.
    """
    
    @property
    def generator(self):
        return self._generator
    
    @generator.setter
    def generator(self, generator):
        """
        Assign a generator.
        
        :param generator: A function that can be used to populate the array.
            This should be a callable that accepts a numpy array as the first
            argument, which is understood to be a mapped array encapsulating
            the underlying memory. The function must accept another numpy array
            as its second argument, which is understood to be the axis values 
            for the output array.The function may accept any other positional
            or keyword arguments, which will be able to passed in when the 
            array is populated.
        :type generator: callable
        """        
        self._generator = generator
        
    def populate(self, *args, **kwargs):
        """
        Populate the underlying array resource, passing any arguments to the
        encapsulated generator function. The object instance must implement
        the method ``memory`` with a similar signature to ``Array.memory``.
        
        :raises: ``ValueError`` if the array does not have a generator
        """    
        
        if self._generator is None:
            raise ValueError("Attempted to populate array without generator")
        
        self._generator(self.memory(), self.axis(), *args, **kwargs)
        
        
class Waveform(Array):
    """
    An extension of :class:`Array` that is intended to sample 
    functions of time using parameters extracted from :class:`Channel` objects.
    """
    
    def __init__(self, channel, length=None, region=None):
        """
        Create an empty reference to an array.
        
        :param channel: A channel from which the sampling parameters for
            procedurally populating the memory can be derived.
            
        :type channel: :class:`Channel`
        
        :param region: The memory region in which to create the array. If an
            instance of :class:`Channel`, the type of the underlying memory 
            will be determined by the instance's ``memory_type`` attribute.
            Otherwise, one may pass a subclass of ``type`` which will be
            directly used to instantiate the array when allocated.
            
        :type region: :class:`Channel` or :class:`ManagedMemory`
        
        :param length: The length of the waveform in seconds. If omitted,
            :meth:`allocate` must be called manually.
        
        """        
        self._channel = channel
        self._length = length
        super().__init__(np.int16, length, region)
        
    def allocate(self, length):
        """
        Create an instance of the underlying memory type, thereby reserving a
        resource ID for that type and notifying the compiler to reserve memory
        (in the case of a hardware array).
        
        :param length: Waveform length in seconds
        :type length: float
        """
        super().allocate(self._channel.seconds_to_bytes(length))
        
        # Scale the element axis by the sample time
        sample_times = np.arange(self._channel.seconds_to_samples(length))*self._channel.samples_to_seconds(1)
        
        # The sample times must be repeated because of the two quadratures
        self._axis = np.repeat(sample_times, 2)
        
    def __len__(self):
        """
        :return: The length of the waveform in samples
        :rtype: int
        """
        return self._channel.bytes_to_samples(self.byte_length())
    
    def dma_parameters(self):
        """
        Generate a `dict` of parameters for the :class:`Acadia` `generate` method.
        """
        return [{
            "channel": self._channel,
            "length": self.byte_length() // self._channel.interface_width_bytes,
            "word_address": self.word_address()
        }]
        
class ProceduralWaveform(Waveform, ProceduralArrayMixin):
    pass
        
class ConstantWaveform(Waveform):
    """
    A waveform with a constant value.
    """
    
    def __init__(self, channel, length):
        """
        :param channel: Channel for the waveform
        :type channel: :class:`Channel`
        :param length: Length of the constant in seconds
        :type length: float
        """
        super().__init__(channel, length, channel.memory_type)
        
    def allocate(self, length):
        # Allocate only a single cycle but store the length in time for later
        self._length = length
        super().allocate(self._channel.bytes_to_seconds(self._channel.interface_width_bytes))
        
    def populate(self, value):
        """
        Set the complex amplitude of the constant.
        
        :param value: Waveform value
        :type value: complex
        
        """
        # Load the DAC memory with the new amplitude
        arr = np.empty(self._channel.bytes_to_samples(self._channel.interface_width_bytes), np.complex64)
        arr.fill(value)
        Channel.to_samples(arr, out=self.memory())
        
    def dma_parameters(self):
        """
        Generate a `dict` of parameters for the :class:`Acadia` `generate` method.
        """            
        return [{
            "channel": self._channel,
            "length": self._channel.seconds_to_bytes(self._length) // self._channel.interface_width_bytes,
            "word_address": self.word_address(),
            "fixed": True
        }]