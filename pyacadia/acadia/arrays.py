
import numpy as np

from .channel import Channel
from .compiler import ManagedMemory

__all__ = ["Array", "ProceduralArray", "ProceduralWaveform"]

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
    
    def __init__(self, region=None):
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
        
    def allocate(self, size, dtype=np.uint8):
        """
        Create an instance of the underlying memory type, thereby reserving a
        resource ID for that type and notifying the compiler to reserve memory
        (in the case of a hardware array).
        
        :param size: Array size in bytes
        :type size: int
        :param dtype: Memory type of the array to cast
        :type dtype: np.dtype
        """
        self._size = size
        self._dtype = dtype
        
        if self.allocated():
            raise ValueError("Attempted re-allocation of non-free memory")
                
        if self._class is None:
            self._resource = np.empty(shape=(size // dtype(0).nbytes,), dtype=dtype)
        else:
            self._resource = self._class(size=self._size, dtype=dtype)
            
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
        if not self.allocated():
            raise ValueError("Attempted access of unallocated array")
        
        if not hasattr(self._resource, "memory"):
            raise ValueError("Attempted access of unmapped memory.")
        
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
        
        
class ProceduralArray(Array):
    """
    A wrapper for hardware arrays with efficient 
    routines for dynamically populating them.
    """
    def __init__(self, generator, region=None):
        """
        Create an empty reference to an array.
        
        :param generator: A function that can be used to populate the array.
            This should be a callable that accepts a numpy array as the first
            argument, which is understood to be a mapped array encapsulating
            the underlying memory. The function may accept any other positional
            or keyword arguments, which will be able to passed in when the 
            array is populated.
        
        :param region: The memory region in which to create the array. If an
            instance of :class:`Channel`, the type of the underlying memory 
            will be determined by the instance's ``memory_type`` attribute.
            Otherwise, one may pass a subclass of ``type`` which will be
            directly used to instantiate the array when allocated.
            
        :type region: :class:`Channel` or :class:`ManagedMemory`
        
        """
        
        self._generator = generator
        super().__init__(region)
        
                
    def populate(self, *args, **kwargs):
        """
        Populate the underlying array resource, passing any arguments to the
        encapsulated generator function.
        
        :raises: ``AttributeError`` if the memory is not mapped, determined
            by checking whether the underlying resource has a memory attribute.
        :raises: ``ValueError`` if the array does not have a generator
        """    
        if not self.allocated():
            raise ValueError("Attempted to populate non-allocated array")
            
        if not hasattr(self._resource, "memory"):
            raise AttributeError(f"Attempted to populate non-mapped array")
        
        if self._generator is None:
            raise ValueError("Attempted to populate array without generator")
        
        self._generator(self._resource.memory, *args, **kwargs)

class ProceduralWaveform(ProceduralArray):
    """
    An extension of :class:`ProceduralArray` that is intended to sample 
    functions of time using parameters extracted from :class:`Channel` objects.
    """
    
    def __init__(self, channel, generator, region=None):
        """
        Create an empty reference to an array.
        
        :param channel: A channel from which the sampling parameters for
            procedurally populating the memory can be derived.
            
        :type channel: :class:`Channel`
        
        :param generator: A function that can be used to populate the array.
            This should be a callable that accepts a numpy array as the first
            argument, which is understood to be a mapped array encapsulating
            the underlying memory. The second argument will be a numpy array 
            of floats, which are understood to be the time values for the 
            corresponding entries in the output array. The function may accept
            any other positional or keyword arguments, which will be able to 
            passed in when the array is populated.
        
        :param region: The memory region in which to create the array. If an
            instance of :class:`Channel`, the type of the underlying memory 
            will be determined by the instance's ``memory_type`` attribute.
            Otherwise, one may pass a subclass of ``type`` which will be
            directly used to instantiate the array when allocated.
            
        :type region: :class:`Channel` or :class:`ManagedMemory`
        
        """
        
        self._time_axis = None
        self._channel = channel
        super().__init__(generator, region)
        
    def allocate(self, length):
        """
        Create an instance of the underlying memory type, thereby reserving a
        resource ID for that type and notifying the compiler to reserve memory
        (in the case of a hardware array).
        
        :param length: Waveform length in seconds
        :type length: float
        """
        
        samples = self._channel.seconds_to_samples(length)
        bytes_per_sample = 2*2 # factor of two because two quadratures
        super().allocate(samples*bytes_per_sample, np.int16)
        
        # Cache an array of time points for evaluating the generator
        self._time_axis = np.arange(0, length, self._channel.samples_to_seconds(1))
        
    def __len__(self):
        """
        :return: The length of the waveform in samples
        :rtype: int
        """
        return self.byte_length() // 4
        
    def populate(self, *args, **kwargs):
        """
        Populate the underlying array resource, passing any arguments to the
        encapsulated generator function.
        
        :raises: ``AttributeError`` if the memory is not mapped, determined
            by checking whether the underlying resource has a memory attribute.
        :raises: ``ValueError`` if the array does not have a generator
        """    
        super().populate(self._time_axis, *args, **kwargs)
        
    def axis(self):
        if not self.allocated():
            raise ValueError(f"Attempted axis access of unallocated waveform.")
        return self._time_axis
    
class Waveform(ProceduralWaveform):
    """
    A waveform of constant length.
    """
    
    def __init__(self, channel, length, region=None):
        super().__init__(channel, None, region)
        self.allocate(length)
        