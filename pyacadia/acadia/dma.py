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
    decimate: int = 0
    blank: [bool, Symbol] = False
    fixed: [bool, Symbol] = False
    
    def __eq__(self, other):
        return (hasattr(other, "trace_length") and self.trace_length is other.trace_length
            and hasattr(other, "trace_address") and self.trace_address is other.trace_address
            and hasattr(other, "decimate") and self.decimate is other.decimate
            and hasattr(other, "fixed") and self.fixed is other.fixed
            and hasattr(other, "blank") and self.blank is other.blank)
    
    def assemble(self):
        tmp = 0
        
        if isinstance(self.trace_length, Symbol) or isinstance(self.trace_length, Operation):
            trace_length = self.trace_length.value()-1
        elif isinstance(self.trace_length, int):
            trace_length = self.trace_length-1
        else:
            raise TypeError(f"Trace length must be an int; received {self.trace_length}")
            
        if trace_length & 0xFFFFFFFF != trace_length:
            raise ValueError(f"Trace length must fit in 32 bits; received {trace_length}")
        
        if trace_length < 0:
            raise ValueError(f"Received negative trace length for descriptor {self}")
            
        if trace_length == 0:
            # Indicate that this is truly a null descriptor
            self.null = True
            return 0
            
        tmp |= trace_length
            
        if isinstance(self.trace_address, Symbol) or isinstance(self.trace_address, Operation):
            trace_address = self.trace_address.value()
        elif isinstance(self.trace_address, int):
            trace_address = self.trace_address
        else:
            raise TypeError(f"Trace address must be an int; received {self.trace_address}")
            
        if trace_address & 0xFFFF != trace_address:
            raise ValueError(f"Trace address must fit in 16 bits; received {trace_address}")
            
        tmp |= trace_address << 32
            
        if isinstance(self.decimate, Symbol) or isinstance(self.decimate, Operation):
            tmp |= self.decimate.value() << 60
        else:
            tmp |= self.decimate << 60
            
        if isinstance(self.fixed, Symbol) and self.fixed._value_type is bool:
            tmp |= self.fixed.value() << 62
        elif isinstance(self.fixed, bool):
            tmp |= self.fixed << 62
        else:
            raise TypeError(f"Descriptor parameter `fixed` must either be of"
                            f" type `bool` or a `Symbol` encapsulating one"
                            f" (received {self.fixed})")

        if isinstance(self.blank, Symbol) and self.blank._value_type is bool:
            tmp |= self.blank.value() << 63
        elif isinstance(self.blank, bool):
            tmp |= self.blank << 63
        else:
            raise TypeError(f"Descriptor parameter `blank` must either be of"
                            f" type `bool` or a `Symbol` encapsulating one"
                            f" (received {self.blank})")
              
        return tmp
    
class DMA(Processor):
    """
    An abstraction of the real-time direct memory access (DMA) modules used for
    streaming data in and out of the Acadia hardware.
    """

    def request_descriptor(self, trace_address, trace_length, decimate=0, fixed=False, blank=False):
        """
        Request the DMA to stream a trace. All existing descriptors will be 
        checked to determine whether one exists that is equal to the one
        requested, and if so, it is returned. Otherwise, a new descriptor is
        allocated.

        :param trace_address: Address of the trace in trace memory
        :type trace_address: int
        :param trace_length: The length of the trace in cycles.
        :type trace_length: int
        :param blank: If ``True``, the DMA will hold its valid output low.
        :type blank: bool
        :param fixed: If ``True``, the address output of the DMA will not
            increment each cycle.
        :type fixed: bool
        """
        request_descriptor = Descriptor(trace_address=trace_address, 
                                        trace_length=trace_length, 
                                        fixed=fixed,
                                        decimate=decimate,
                                        blank=blank)
        
        for instruction in self.Instruction.instances:
            cmp_descriptor = Descriptor(**instruction.kwargs)
            if cmp_descriptor == request_descriptor:
                return instruction
            
        return self.add_descriptor(trace_address=trace_address, 
                                    trace_length=trace_length, 
                                    fixed=fixed,
                                    decimate=decimate,
                                    blank=blank)
    
    @Processor.instruction()
    def add_descriptor(self, instruction_resource):
        """
        Instructs the DMA to stream a trace. The length of the trace is found
        by calling :meth:`len` on the first (and only allowed) positional
        argument. Two additional optional keyword arguments are detailed below.
        """
        
        descriptor = Descriptor(**instruction_resource.kwargs)
        instruction_resource.compiled = [descriptor]
