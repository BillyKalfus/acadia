__all__ = ["LinuxMemory", "AxisSwitch"]

import mmap
import os
from enum import Enum

class LinuxMemory:
    """
    An abstraction for accessing the hardware onboard the ZCU216.
    As this class is intended to be instantiated on the hardware itself,
    it implements a singleton pattern. 
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__()
        return cls._instance
    
    def __init__(self):
        self._mem_file = os.open("/dev/mem", os.O_SYNC | os.O_RDWR)
        self._maps = []
    
    def attach_resource(self, resource_manager, mem_cast='c'):
        """
        Maps the memory associated with a managed resource in the physical 
        address space of the hardware. Instances of `memoryview` are assigned
        to the resource instances under the attribute `memory`.
        
        :param resource_manager: Resource with instances to be mapped
        :type resource_manager: :class:`ManagedResource`
        :param mem_cast: The memory type to which the view should be casted,
        as indicated by a `struct` format character.
        :type mem_cast: str, optional
        """
        m = mmap.mmap(self._mem_file, 
            resource_manager.pool_size * resource_manager.word_width // 8, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            resource_manager.base_byte_address)
        
        self._maps.append(m)
        resource_manager._memory = m
        
        for instance in resource_manager.instances:
            start_byte = instance.byte_address() - resource_manager.base_byte_address
            end_byte = start_byte + instance.byte_length()
            instance.memory = memoryview(m)[start_byte:end_byte].cast(mem_cast)
        
    def attach_memory(self, address, size, mem_cast='c'):
        """
        Maps a region of memory in the physical address space of the hardware.
        
        :param address: Physical address to map
        :type address: int
        :param size: Size of the space to map in bytes
        :type size: int
        """
        m = mmap.mmap(self._mem_file, 
            size, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            address)
        self._maps.append(m)
        
        return memoryview(m).cast(mem_cast)
        
    def detach_all(self):
        """
        Unmaps all mapped memory.
        """
        for m in self._maps:
            m.close()
            
class AxisSwitch:
    """
    Methods for controlling the Xilinx AXIS switch IP over the AXI-Lite
    interface.
    """
    MUX0_REG = 0x40 >> 2
    DISABLE_VALUE = 1 << 31
    
    CONTROL_REG = 0
    COMMIT_VALUE = 1 << 1
    
    def __init__(self, address, mem):
        self._address = address
        self._mem = mem
        
    def attach(self):
        self._regs = self._mem.attach_memory(self._address, 0x1000, mem_cast="I")
        
        # by default, disable all connections
        for i in range(16):
            self._regs[MUX0_REG + i] = DISABLE_VALUE
            
    def disconnect(self, mi, commit=True):
        self._regs[MUX0_REG + mi] = DISABLE_VALUE
        if commit:
            self._regs[CONTROL_REG] = COMMIT_VALUE
        
    def connect(self, mi, si, commit=True):
        self._regs[MUX0_REG + mi] = si
        if commit:
            self._regs[CONTROL_REG] = COMMIT_VALUE
        
class RFDC:
    """
    High-level interface to the Xilinx RFDC IP.
    """
    
    _channel_handler = None
    _instance = None
    
    def __new__(cls, channel_handler=None):
        if cls._instance is None:
            import pyxrfdc.lib as xrfdc
            if channel_handler is None:
                raise ValueError("Channel handler must be provided for first instantiation.")
                
            cls._channel_handler = channel_handler
            cls._instance = super().__new__()
            
        return cls._instance
    
    def __init__(self):
        self._attached = False
    
    def attach(self):
        if not self._attached:
            metal_init_params = xrfdc.ffi.new("struct metal_init_params*", )
            self._config_ptr = xrfdc.ffi.new("XRFdc_Config*")
            self._device_ptr = xrfdc.ffi.new("struct metal_device*")
            
            self._attached = True
            
    
    def status(self):
        """
        Get the status of the IP.
        """
        
        pass
    
            
        
    