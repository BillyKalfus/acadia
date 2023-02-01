__all__ = ["DMA", "Descriptor"]

from dataclasses import dataclass
from contextlib import contextmanager

from .compiler import Processor, Symbol, Operation

@dataclass
class Descriptor:
    """
    An analog of machine instructions for direct memory access (DMA) modules,
    descriptors define a single transfer to be carried out by a DMA.
    """
    trace_length: 'int or Symbol or Operation' = 0
    trace_address: 'int or Symbol or Operation' = 0
    decimate: 'int or Symbol' = 0
    hold: 'bool' = False
    
    def assemble(self):
        tmp = 0
        tmp |= self.hold << 40
        
        if isinstance(self.decimate, Symbol):
            tmp |= self.decimate.value() << 32
        else:
            tmp |= self.decimate << 32
            
        if isinstance(self.trace_address, Symbol) or isinstance(self.trace_address, Operation):
            tmp |= self.trace_address.value() << 16
        else:
            tmp |= self.trace_address << 16
            
        if isinstance(self.trace_length, Symbol) or isinstance(self.trace_length, Operation):
            tmp |= self.trace_length.value()
        else:
            tmp |= self.trace_length
            
        return tmp
    
class DMA(Processor):
    """
    An abstraction of the real-time direct memory access (DMA) modules used for
    streaming data in and out of the Acadia hardware.
    """
    
    @Processor.instruction()
    def stream(self, instruction_resource):
        """
        Instructs the DMA to stream a trace. The length of the trace is found
        by calling :meth:`len` on the first (and only allowed) positional
        argument. Two additional optional keyword arguments are detailed below.
        
        :param trace_address: The trace to be streamed from the DMA.
        :type trace_address: Address of the trace in trace memory
        :param trace_length:
        :param decimate: The decimation factor to set in the DMA
        :type decimate: `int`, :class:`Symbol`, or :class:`Operation`, optional
        :param hold: If `True`, decimated samples are considered valid for the
        entire length of the decimation period, rather than just in the first
        cycle.
        :type hold: `bool`, optional
        """
        fields = {}
        fields["hold"] = False
        fields["decimate"] = 0
        
        if len(instruction_resource["args"]) == 1:
            arg = instruction_resource["args"][0]
            fields["trace_address"] = arg.address() if hasattr(arg, "address") else None
            fields["trace_length"] = len(arg) if hasattr(arg, "__len__") else None
        elif len(instruction_resource["args"]) == 0:
            fields["trace_address"] = None
            fields["trace_length"] = None
        else:
            raise ValueError("Stream instruction should have one or zero"
                             " positional arguments; received"
                             f" args={instruction_resource['args']}")
            
        for key in instruction_resource["kwargs"].keys():
            if key in ["decimate", "hold", "trace_length", "trace_address"]:
                fields[key] = instruction_resource["kwargs"][key]
            else:
                raise KeyError(f"Unrecognized keyword argument {key}.")
            
        descriptor = Descriptor(**fields)
        instruction_resource["compiled_instructions"] = [descriptor]
