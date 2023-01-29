__all__ = ["DMA", "Descriptor"]

from dataclasses import dataclass

from .compiler import Processor, Symbol
from contextlib import contextmanager

@dataclass
class Descriptor:
    length: 'int or Symbol or Operation' = 0
    address: 'int or Symbol or Operation' = 0
    decimate: 'int or Symbol' = 0
    hold: 'bool' = False
    
    def assemble(self):
        tmp = 0
        tmp |= hold << 40
        
        if isinstance(self.decimate, Symbol):
            tmp |= decimate.value() << 32
        else:
            tmp |= decimate << 32
            
        if isinstance(self.address, Symbol) or isinstance(self.address, Operation):
            tmp |= address.value() << 16
        else:
            tmp |= address
            
        if isinstance(self.length, Symbol) or isinstance(self.length, Operation):
            tmp |= length.value()
        else:
            tmp |= length
            
        return tmp
    
class DMA(Processor):
    
    @Processor.instruction()
    def stream(self, instruction_resource):
        """
        Instructs the DMA to stream a trace.
        """
        if (len(instruction_resource._args) != 1):
            raise ValueError("Stream instruction should have one positional"
                             " argument; received"
                             f" args={instruction_resource._args}")
            

        hold = False
        decimate = 0    
        for key in instruction_resource._kwargs.keys():
            if key == "decimate":
                decimate = instruction_resource._kwargs[key]
            elif key == "hold":
                hold = instruction_resource._kwargs[key]
            else:
                raise KeyError(f"Unrecognized keyword argument {key}.")
            
        arg = instruction_resource._args[0]
        descriptor = Descriptor(length=len(arg), decimate=decimate, hold=hold)
        instruction_resource["compiled_instructions"] = descriptor
        
    @contextmanager
    def sequence(self, symbols=False):
        """
        Creates a tracked sequence of streams for this DMA. The context target
        may be provided in two forms, depending on the value of `symbols`.
        If `True`, the target is a tuple of :class:`Symbol` objects; the first
        :class:`Symbol` contains the instruction resource of the first stream 
        in the sequence and the second :class:`Symbol` contains the last. If
        `False`, the target is an :class:`Operation` on these :class:`Symbol`
        objects that packs the compiled address of the start stream and the 
        final stream into a single 32-bit integer, in the form expected by 
        the Acadia sequencer.
        
        :param symbols: Determines whether this context will yield a tuple of
        :class:`Symbol` objects or an :class:`Operation` packing them.
        :type symbols: `bool`, optional
        """
        seq_start = self._Instruction.next_instance()
        seq_end = Symbol(value_type=self._Instruction)
        
        self.block_start()
        if symbols:
            yield seq_start,seq_end
        else:
            yield (seq_end["compiled_address"] << 16) | seq_start["compiled_address"]
        self.block_end()
        
        seq_end.assign(self._Instruction.instances[-1])
        
    def assemble(self):
        descriptors = []
        for resource in self._compiled_program:
            # The compiled instructions should just be the Descriptor object
            descriptor_bin = resource["compiled_instructions"].assemble()
            descriptor_bin |= resource["compiled_address"] << 16
            descriptors.append(descriptor_bin)
        return descriptors