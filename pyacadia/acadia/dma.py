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
    trace_length: [int, Symbol, Operation]
    trace_address: [int, Symbol, Operation]
    decimate: [int, Symbol] = 0
    blank: [bool, Symbol] = False
    fixed: [bool, Symbol] = False
    
    def __eq__(self, other):
        return (hasattr(other, "decimate") and self.decimate is other.decimate
            and hasattr(other, "trace_length") and self.trace_length is other.trace_length
            and hasattr(other, "trace_address") and self.trace_address is other.trace_address
            and hasattr(other, "fixed") and self.fixed is other.fixed
            and hasattr(other, "blank") and self.blank is other.blank)
    
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
            tmp |= self.decimate.value() << 48
        else:
            tmp |= self.decimate << 48
            
        if isinstance(self.blank, Symbol):
            tmp |= self.blank.value() << 56
        else:
            tmp |= self.blank << 56
            
        if isinstance(self.fixed, Symbol):
            tmp |= self.fixed.value() << 57
        else:
            tmp |= self.fixed << 57
              
        return tmp
    
class DMA(Processor):
    """
    An abstraction of the real-time direct memory access (DMA) modules used for
    streaming data in and out of the Acadia hardware.
    """
    def request_descriptor(self, trace_address, trace_length, decimate=0, blank=False, fixed=False):
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
        :param blank: The value of the `blank` flag in the descriptor.
        :type blank: bool
        :param fixed: The value of the `blank` flag in the descriptor
        """
        request_descriptor = Descriptor(trace_address=trace_address, 
                                        trace_length=trace_length, 
                                        decimate=decimate,
                                        blank=blank,
                                        fixed=fixed)
        
        for instruction in self.Instruction.instances:
            cmp_descriptor = Descriptor(**instruction.kwargs)
            if cmp_descriptor == request_descriptor:
                return instruction
            
        return self.add_descriptor(trace_address=trace_address, 
                                    trace_length=trace_length, 
                                    decimate=decimate,
                                    blank=blank,
                                    fixed=fixed)
    
    @Processor.instruction()
    def add_descriptor(self, instruction_resource):
        """
        Instructs the DMA to stream a trace. The length of the trace is found
        by calling :meth:`len` on the first (and only allowed) positional
        argument. Two additional optional keyword arguments are detailed below.
        """
        descriptor = Descriptor(**instruction_resource.kwargs)
        instruction_resource.compiled = [descriptor]
