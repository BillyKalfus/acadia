__all__ = ["DMA", "Descriptor"]

from dataclasses import dataclass
from contextlib import contextmanager

from .compiler import Processor, Symbol, Operation

@dataclass(eq=False)
class Descriptor:
    """
    An analog of machine instructions for direct memory access (DMA) modules,
    descriptors define a single transfer to be carried out by a DMA.
    """
    trace_length: [int, Symbol, Operation] = 0
    trace_address: [int, Symbol, Operation] = 0
    decimate: [int, Symbol] = 0
    
    def __eq__(self, other):
        return (hasattr(other, "decimate") and self.decimate is other.decimate
            and hasattr(other, "trace_length") and self.trace_length is other.trace_length
            and hasattr(other, "trace_address") and self.trace_address is other.trace_address)
    
    def assemble(self):
        tmp = 0
        
        if isinstance(self.trace_length, Symbol) or isinstance(self.trace_length, Operation):
            tmp |= self.trace_length.value()-1
        else:
            tmp |= self.trace_length-1
            
        if isinstance(self.trace_address, Symbol) or isinstance(self.trace_address, Operation):
            tmp |= self.trace_address.value() << 32
        else:
            tmp |= self.trace_address << 32
        
        if isinstance(self.decimate, Symbol):
            tmp |= self.decimate.value() << (32+16)
        else:
            tmp |= self.decimate << (32+16)
              
        return tmp
    
class DMA(Processor):
    """
    An abstraction of the real-time direct memory access (DMA) modules used for
    streaming data in and out of the Acadia hardware.
    """
    def request_descriptor(self, trace_address, trace_length, decimate=0):
        """
        Request the DMA to stream a trace. All existing descriptors will be 
        checked to determine whether one exists that is equal to the one
        requested, and if so, it is returned. Otherwise, a new descriptor is
        allocated.
        :param trace_address: The trace to be streamed from the DMA.
        :type trace_address: Address of the trace in trace memory
        :param trace_length:
        :param decimate: The decimation factor to set in the DMA
        :type decimate: `int`, :class:`Symbol`, or :class:`Operation`, optional
        """
        request_descriptor = Descriptor(trace_address=trace_address, 
                                        trace_length=trace_length, 
                                        decimate=decimate)
        
        for instruction in self.Instruction.instances:
            cmp_descriptor = Descriptor(**instruction_resource.kwargs)
            if cmp_descriptor == request_descriptor:
                return instruction_resource.address
            
        return self.add_descriptor(trace_address=trace_address, 
                                    trace_length=trace_length, 
                                    decimate=decimate).address
    
    @Processor.instruction()
    def add_descriptor(self, instruction_resource):
        """
        Instructs the DMA to stream a trace. The length of the trace is found
        by calling :meth:`len` on the first (and only allowed) positional
        argument. Two additional optional keyword arguments are detailed below.
        """
        descriptor = Descriptor(**instruction_resource.kwargs)
        instruction_resource.compiled = [descriptor]
