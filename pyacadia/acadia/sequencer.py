import struct
import os
import operator
from enum import Enum
from typing import get_type_hints
from dataclasses import dataclass
from contextlib import contextmanager

from .dsp_modes import DSPMode, save_dsp_modes, load_dsp_modes
from .compiler import ManagedResource, Symbol, Operation, Processor, Operable, ProcessorInstruction

__all__ = ["Sequencer", "DSPConfiguration"]

DSP_MODES_PATH = "/tmp/dsp_modes.bin"

if not os.path.exists(DSP_MODES_PATH):
    save_dsp_modes(DSP_MODES_PATH)

def is_numeric(obj):
    """
    Determines whether a given object is a valid numeric argument.

    :return: ``True`` if a given object is suitable as a numeric argument for assembly.
    :rtype: ``bool``
    """

    for t in [int, bool, DSPConfiguration, ProcessorInstruction]:
        if (isinstance(obj, t) 
            or (isinstance(obj, Symbol) 
                and (obj.value_type() is t 
                    or t in obj.value_type().__bases__))):
            return True
        
    if isinstance(obj, Operation):
        if obj._op not in Operable.NUMERIC_OPERATORS:
            return False
        for arg in obj._args:
            if not is_numeric(arg):
                return False
        for key,value in obj._kwargs.items():
            if not is_numeric(value):
                return False
        return True
    return False    

@dataclass
class SequencerDatapathPort:
    major: object = None
    minor: int = 0

    def __post_init__(self):
        if not isinstance(self.major, type(self).Major):
            raise TypeError(f"Expecting type {type(self).Major} for field major;"
                            f" received {self.major}.")

        if not isinstance(self.minor, int):
            raise TypeError(f"Expecting int for field minor;"
                            f" received {self.minor}.")

    def value(self):
        minor_value = self.minor.value() if "value" in dir(self.minor) else self.minor
        return (self.major.value << 3) + minor_value

    def __str__(self):
        if self.major is type(self).Major.REG:
            minor_str = self.minor
        elif "DSP" in self.major.name:
            minor_str = self.minor
        else:
            minor_str = ""
        return f"{self.major.name}{minor_str}"

    def __repr__(self):
        return str(self)
            
class Source(SequencerDatapathPort, metaclass=Operable):
    class Major(Enum):
        REG = 0
        REG_LO = 1
        REG_HI = 2
        # 3 is skipped intentionally
        PC = 4
        IMM = 5
        EXT = 6
        STACK = 7
        BUS_DATA = 8
        DSP_PATTERN = 9
        DSP_P = 10
            
class Destination(SequencerDatapathPort):
    PC_ABSOLUTE_BRANCH = 0b00
    PC_RELATIVE_BRANCH = 0b01
    PC_ABSOLUTE_HOLD   = 0b10
    PC_RELATIVE_HOLD   = 0b11
    
    class Major(Enum):
        REG = 0
        PC = 1
        MASK = 2
        EXT = 3
        STACK = 4
        BUS_DATA = 5
        BUS_ADDR = 6
        DSP_CFG = 7
        DSP_AB = 8
        DSP_C = 9

    def __str__(self):
        if self.major is Destination.Major.REG:
            minor_str = self.minor
        elif "DSP" in self.major.name:
            minor_str = self.minor
        elif self.major is Destination.Major.PC:
            if self.minor == Destination.PC_ABSOLUTE_BRANCH:
                minor_str = " (absolute branch)"
            elif self.minor == Destination.PC_RELATIVE_BRANCH:
                minor_str = " (relative branch)"
            elif self.minor == Destination.PC_ABSOLUTE_HOLD:
                minor_str = " (absolute hold)"
            elif self.minor == Destination.PC_RELATIVE_HOLD:
                minor_str = " (relative hold)"
            else:
                raise ValueError(f"Invalid minor value {self.minor}")
        else:
            minor_str = ""
        return f"{self.major.name}{minor_str}"
    
    def __repr__(self):
        return str(self)

@dataclass
class DSPConfiguration:
    """
    A container for a 32-bit value to be written to the DSP configuration port.
    """

    # Mode in which to operate the DSP slice at the next clock cycle
    # May be a string or a DSPMode
    mode: [DSPMode, str] = "P" 

    # If `True`, the RST pin of the P register is pulsed when
    # the configuration register is written.
    rst_p: bool = False

    # Indicates how the clock enable for the DSP P register
    # should be driven. If "pulse", the P register will be pulsed for one
    # cycle immediately following the configuration. If "set", the input
    # will be set high until reset. If "reset", the input will be set low.
    # If `None` or omitted, no action will be taken and the pin will remain
    # in its current state.
    dsp_cep: str = None
    
    def __post_init__(self):
        """
        Assembles a 32-bit value which, when written to the DSP configuration
        destination on the sequencer, configures a given DSP slice.

        """
        if not hasattr(DSPConfiguration, "DSP_MODES"):
            DSPConfiguration.DSP_MODES = load_dsp_modes(DSP_MODES_PATH)
        
        if isinstance(self.mode, str):
            mode = DSPConfiguration.DSP_MODES[self.mode]
        else:
            mode = self.mode
            
        opmode = (mode.w << 7) | (mode.z << 4) | (mode.y << 2) | mode.x

        if self.dsp_cep is None or self.dsp_cep == "reset":
            dsp_cep_bits = 0
        elif self.dsp_cep == "set":
            dsp_cep_bits = 1
        elif self.dsp_cep == "pulse":
            dsp_cep_bits = 3
        else:
            raise ValueError(f"Invalid DSP CEP setting {self.dsp_cep}.")

        # Constants below from the Acadia manual, as these are determined
        # by the logic
        self._value = ((dsp_cep_bits << 15)
                    | (self.rst_p << 14)
                    | (mode.cin << 13)
                    | (opmode << 4)
                    | mode.alumode)
        
    def value(self):
        return self._value
    
# Create dataclasses for abstracting machine code
@dataclass
class STP:
    src1: Source = Source(Source.Major.REG)
    src2: Source = Source(Source.Major.REG)
    dest1: Destination = Destination(Destination.Major.REG)
    dest2: Destination = Destination(Destination.Major.REG)
    imm1: [int, bool, Symbol, Operation, DSPConfiguration, ProcessorInstruction] = 0
    imm2: [int, bool, Symbol, Operation, DSPConfiguration, ProcessorInstruction] = 0
    dsp_cep: [Source, Destination, int] = None
    push_return: [bool, int] = False
    comment: str = None

    def __post_init__(self):
        # Check types
        self.name = "STP"
        if is_numeric(self.src1):
            self.imm1 = self.src1
            self.src1 = Source(Source.Major.IMM)
        if not isinstance(self.src1, Source):
            raise TypeError(f"STP field src1 must be of type Source;"
                            f" received {self.src1}.")
        
        if is_numeric(self.src2):
            self.imm2 = self.src2
            self.src2 = Source(Source.Major.IMM)
            
        # Do basic type-checking
        for field,field_type in get_type_hints(self).items(): 
            field_value = getattr(self, field)
            if field_value is not None:
                if isinstance(field_type, list):
                    found = False
                    for t in field_type:
                        if isinstance(field_value, t):
                            found = True
                            break
                    if not found:
                        raise TypeError(f"The type of field {field} must be one of"
                                        f" {field_type}; received {field_value}.")
                elif not isinstance(field_value, field_type):
                    raise TypeError(f"Field {field} must be of type {field_type};"
                                    f" received {field_value}.")
                
    def pprint(self):
        """
        Return a nicely-formatted (and non-exhaustive) description of this 
        instruction.

        """

        s = ""
        if (str(self.src1) == "REG0" 
            and str(self.dest1) == "REG0"):
            s += "NOP"
        else:
            if self.src1.major is Source.Major.IMM:
                v = self.imm1.value() if isinstance(self.imm2, Symbol) else self.imm1
                if isinstance(v, ProcessorInstruction):
                    s += f"{v.__class__.__name__} @ {v.address.value():08X}"
                elif isinstance(v, int):
                    s += f"{v:08X}"
                else:
                    s += f"{v}"
            else:
                s += f"{self.src1}"
            s += f" -> {self.dest1}"

        s += "  |  "

        if (str(self.src2) == "REG0" 
            and str(self.dest2) == "REG0"):
            s += "NOP"
        else:
            if self.src2.major is Source.Major.IMM:
                v = self.imm2.value() if isinstance(self.imm2, Symbol) else self.imm2
                if isinstance(v, ProcessorInstruction):
                    s += f"{v.__class__.__name__} @ {v.address.value():08X}"
                elif isinstance(v, int):
                    s += f"{v:08X}"
                else:
                    s += f"{v}"
            else:
                s += f"{self.src2}"
            s += f" -> {self.dest2}"

        if self.dsp_cep is not None:
            s += f"  | {self.dsp_cep} CEP"

        if self.push_return:
            s += f"  | PUSH_RETURN"

        if self.comment is not None:
            s += f"  ; {self.comment}"

        return s

    def assemble(self):
        """
        Assembles the instruction into a binary word.

        :return: A binary word representing the machine instruction.
        :rtype: int
        """

        tmp = 0
        # Opcode = 0 for STP
        tmp |= self.push_return << (104-64)
        tmp |= self.src1.value() << (96-64)
        tmp |= self.src2.value() << (88-64)
        tmp |= self.dest1.value() << (80-64)
        tmp |= self.dest2.value() << (72-64)
        tmp |= ((self.dsp_cep.value() | 0x8) << (64-64)) if self.dsp_cep is not None else 0

        imm1_value = self.imm1
        while hasattr(imm1_value, "value") or hasattr(imm1_value, "address"):
            if hasattr(imm1_value, "null") and imm1_value.null:
                return struct.pack("<IIQ", 0, 0, 0)
            if hasattr(imm1_value, "value"):
                if callable(imm1_value.value):
                    imm1_value = imm1_value.value()
                else:
                    imm1_value = imm1_value.value
            if hasattr(imm1_value, "address"):
                if callable(imm1_value.address):
                    imm1_value = imm1_value.address()
                else:
                    imm1_value = imm1_value.address

        imm2_value = self.imm2
        while hasattr(imm2_value, "value") or hasattr(imm2_value, "address"):
            if hasattr(imm2_value, "null") and imm2_value.null:
                return struct.pack("<IIQ", 0, 0, 0)
            if hasattr(imm2_value, "value"):
                if callable(imm2_value.value):
                    imm2_value = imm2_value.value()
                else:
                    imm2_value = imm2_value.value
            if hasattr(imm2_value, "address"):
                if callable(imm2_value.address):
                    imm2_value = imm2_value.address()
                else:
                    imm2_value = imm2_value.address
            
        return struct.pack("<IIQ", imm2_value, imm1_value, tmp)

@dataclass
class STC:
    src_stval: Source = Source(Source.Major.REG)
    src_tval: Source = Source(Source.Major.REG)
    dest_stval: Destination = Destination(Destination.Major.REG)
    op: int = 0
    imm_stval: [int, bool, Symbol, Operation, DSPConfiguration, ProcessorInstruction] = 0
    imm_tval: [int, bool, Symbol, Operation, DSPConfiguration, ProcessorInstruction] = 0
    dsp_cep: [Source, Destination, int] = None
    push_return: bool = False
    comment: str = None

    def __post_init__(self):
        self.name = "STC"
        # Check types
        if is_numeric(self.src_stval):
            self.imm_stval = self.src_stval
            self.src_stval = Source(Source.Major.IMM)
        if not isinstance(self.src_stval, Source):
            raise TypeError(f"STP field src_stval must be of type Source;"
                            f" received {self.src_stval}.")
        
        if is_numeric(self.src_tval):
            self.imm_tval = self.src_tval
            self.src_tval = Source(Source.Major.IMM)
        if not isinstance(self.src_tval, Source):
            raise TypeError(f"STP field src_tval must be of type Source;"
                            f" received {self.src_tval}.")
            
        # Do basic type-checking
        for field,field_type in get_type_hints(self).items(): 
            field_value = getattr(self, field)
            if field_value is not None:
                if isinstance(field_type, list):
                    found = False
                    for t in field_type:
                        if isinstance(field_value, t):
                            found = True
                            break
                    if not found:
                        raise TypeError(f"The type of field {field} must be one of"
                                        f" {field_type}; received {field_value}.")
                elif not isinstance(field_value, field_type):
                    raise TypeError(f"Field {field} must be of type {field_type};"
                                    f" received {field_value}.")
                
    def pprint(self):
        """
        Return a nicely-formatted (and non-exhaustive) description of this 
        instruction.

        """

        s = ""
        if (str(self.src_stval) == "REG0" 
            and str(self.dest_stval) == "REG0"):
            s += "NOP"
        else:
            if self.src_stval.major is Source.Major.IMM:
                v = self.imm_stval.value() if isinstance(self.imm_stval, Symbol) else self.imm_stval
                if isinstance(v, ProcessorInstruction):
                    s += f"{v.__class__.__name__} @ {v.address.value():08X}"
                elif isinstance(v, int):
                    s += f"{v:08X}"
                else:
                    s += f"{v}"
            else:
                s += f"{self.src_stval}"
            s += f" -> {self.dest_stval}"

        s += " if "

        if self.op & 0b11 == 2:
            s += "not("

        if self.src_tval.major is Source.Major.IMM:
            v = self.imm_tval.value() if isinstance(self.imm_tval, Symbol) else self.imm_tval
            if isinstance(v, ProcessorInstruction):
                s += f"{v.__class__.__name__} @ {v.address.value():08X}"
            elif isinstance(v, int):
                s += f"{v:08X}"
            else:
                s += f"{v}"
        else:
            s += f"{self.src_tval}"

        if self.op & 0b11 == 0:
            s += " AND MASK"
        elif self.op & 0b11 == 1:
            s += " XOR MASK"
        elif self.op & 0b11 == 2:
            s += ") AND MASK"

        s += f" {'' if self.op & 0b100 else '!'}= 0"

        if self.dsp_cep is not None:
            s += f"  | {self.dsp_cep} CEP"

        if self.push_return:
            s += f"  | PUSH_RETURN"

        if self.comment is not None:
            s += f"  ; {self.comment}"

        return s

    def assemble(self):
        """
        Assembles the instruction into a binary word.

        :return: A binary word representing the machine instruction.
        :rtype: int
        """

        tmp = 0
        tmp |= 1 << (112-64) # Opcode for STC
        tmp |= self.push_return << (104-64)
        tmp |= self.src_stval.value() << (96-64)
        tmp |= self.src_tval.value() << (88-64)
        tmp |= self.dest_stval.value() << (80-64)
        tmp |= self.op << (72-64)
        tmp |= ((self.dsp_cep.value() | 0x8) << (64-64)) if self.dsp_cep is not None else 0

        imm_stval_value = self.imm_stval
        while hasattr(imm_stval_value, "value") or hasattr(imm_stval_value, "address"):
            if hasattr(imm_stval_value, "null") and imm_stval_value.null:
                return struct.pack("<IIQ", 0, 0, 0)
            if hasattr(imm_stval_value, "value"):
                if callable(imm_stval_value.value):
                    imm_stval_value = imm_stval_value.value()
                else:
                    imm_stval_value = imm_stval_value.value
            if hasattr(imm_stval_value, "address"):
                if callable(imm_stval_value.address):
                    imm_stval_value = imm_stval_value.address()
                else:
                    imm_stval_value = imm_stval_value.address

        imm_tval_value = self.imm_tval
        while hasattr(imm_tval_value, "value") or hasattr(imm_tval_value, "address"):
            if hasattr(imm_tval_value, "null") and imm_tval_value.null:
                return struct.pack("<IIQ", 0, 0, 0)
            if hasattr(imm_tval_value, "value"):
                if callable(imm_tval_value.value):
                    imm_tval_value = imm_tval_value.value()
                else:
                    imm_tval_value = imm_tval_value.value
            if hasattr(imm_tval_value, "address"):
                if callable(imm_tval_value.address):
                    imm_tval_value = imm_tval_value.address()
                else:
                    imm_tval_value = imm_tval_value.address
            
        return struct.pack("<IIQ", imm_tval_value, imm_stval_value, tmp)
    
class Sequencer(Processor):
    """
    A :class:`Processor` for the sequencer embedded in the Acadia control 
    system.

    """
    
    # The total number of general-purpose registers in the sequencer
    NUM_REGISTERS = 8
    
    # The total number of DSP slices accessible from the sequencer
    NUM_DSP = 8
    
    def __init__(self):
        super().__init__()
                
        def resource_load(resource_self, value):
            self.store(src=value, dest=resource_self)
            
        def resource_augment(resource_self, op, *args):
            self.store(src=Operation(Operable.AUGMENTING_OPERATORS[op], 
                                     resource_self, 
                                     *args), 
                      dest=resource_self)
                        
        def register_str(reg_self):
            return f"REG{reg_self._resource_id}"
        
        def register_source(reg_self):
            return Source(Source.Major.REG, reg_self._resource_id)
        
        def register_source_lo(reg_self):
            return Source(Source.Major.REG_LO, reg_self._resource_id)
        
        def register_source_hi(reg_self):
            return Source(Source.Major.REG_HI, reg_self._resource_id)
        
        def register_destination(reg_self):
            return Destination(Destination.Major.REG, reg_self._resource_id)
                        
        reg_dct = {"augmenting_operator_handler": resource_augment,
                     "__str__": register_str,
                     "__repr__": register_str,
                     "load": resource_load,
                     "source": register_source,
                     "lo": register_source_lo,
                     "hi": register_source_hi,
                     "destination": register_destination}
        
        reg_dct.update(Operable.make_operator_functions(["eq", "ne", "gt", "lt", "ge", "le", 
                           "add", "radd", "iadd", "sub", "rsub", "isub", 
                           "and", "rand", "iand", "or", "ror", "ior", 
                           "xor", "rxor", "ixor", "invert"]))
            
        self.Register = ManagedResource("Register", 
                                        (), 
                                        reg_dct, 
                                        allocation_limit=Sequencer.NUM_REGISTERS)
        
        def dsp_str(dsp_self):
            return f"DSP{dsp_self._resource_id}"
            
        def dsp_getitem(dsp_self, key):
            """
            Get a Destination corresponding to a DSP port.
            """

            if key == "AB":
                return Destination(major=Destination.Major.DSP_AB,
                                   minor=dsp_self._resource_id)
            if key == "C":
                return Destination(major=Destination.Major.DSP_C,
                                   minor=dsp_self._resource_id)
            if key == "CFG":
                return Destination(major=Destination.Major.DSP_CFG,
                                   minor=dsp_self._resource_id)
            if key == "P":
                return dsp_self
            
            raise ValueError(f"Invalid DSP port {key}.")
        
        def dsp_source(dsp_self):
            return Source(Source.Major.DSP_P, dsp_self._resource_id)
        
        def dsp_setitem(dsp_self, key, value):
            if key == "AB":
                self.store(src=value, 
                           dest=Destination(major=Destination.Major.DSP_AB,
                                            minor=dsp_self._resource_id))
            elif key == "C":
                self.store(src=value, 
                           dest=Destination(major=Destination.Major.DSP_C,
                                            minor=dsp_self._resource_id))
            elif key == "P":
                self.store(src=value, dest=dsp_self)
                
            else:
                raise ValueError(f"Invalid key {key}; must be"
                                 f" \"AB\", \"C\", or \"P\".")
                
        def dsp_start_count(dsp_self, clear=False, inc=1):
            """
            Command a DSP slice to begin incrementing every clock cycle without
            intervention from the sequencer.

            :param inc: Increment amount, defaults to 1
            :type inc: int, optional
            :param clear: If `True`\, sets the counter value to zero before 
                incrementing
            """
            if isinstance(inc, int) and inc == 1:
                self.store(src=DSPConfiguration(mode="P+1", 
                                                dsp_cep="set", 
                                                rst_p=clear), 
                           dest=Destination(major=Destination.Major.DSP_CFG,
                                            minor=dsp_self._resource_id))
            elif is_numeric(inc):
                self.STP(src1=DSPConfiguration(mode="P+AB", 
                                               dsp_cep="set",
                                               rst_p=clear), 
                         dest1=Destination(major=Destination.Major.DSP_CFG,
                                           minor=dsp_self._resource_id), 
                         src2=inc, 
                         dest2=Destination(major=Destination.Major.DSP_AB,
                                           minor=dsp_self._resource_id))
            else:
                raise TypeError(f"Provided increment must be numeric;"
                                f" received {inc}.")
                
        def dsp_stop_count(dsp_self):
            self.store(src=DSPConfiguration(dsp_cep="reset"), 
                       dest=Destination(major=Destination.Major.DSP_CFG,
                                        minor=dsp_self._resource_id))
        
        @contextmanager
        def dsp_enabled(dsp_self):
            start_idx = len(self.Instruction.instances)
            yield
            for instruction in self.Instruction.instances[start_idx:]:
                if "dsp_cep" not in instruction.kwargs:
                    instruction.kwargs["dsp_cep"] = dsp_self
        
        dsp_dct = {"__str__": dsp_str,
                     "__repr__": dsp_str,
                     "load": resource_load,
                     "augmenting_operator_handler": resource_augment,
                     "__setitem__": dsp_setitem,
                     "__getitem__": dsp_getitem,
                     "start_count": dsp_start_count,
                     "stop_count": dsp_stop_count,
                     "enabled": dsp_enabled,
                     "source": dsp_source}
        
        dsp_dct.update(Operable.make_operator_functions(["eq", "ne", "gt", "lt", "ge", "le", 
                           "add", "radd", "iadd", "sub", "rsub", "isub", 
                           "and", "rand", "iand", "or", "ror", "ior", 
                           "xor", "rxor", "ixor", "invert"]))
        
        self.DSP = ManagedResource("DSP", 
                                    (), 
                                    dsp_dct, 
                                    allocation_limit=Sequencer.NUM_DSP)
     
    def bus_read(self, address=None, latency=0, **kwargs):
        """
        Reads a value from the bus. If no address is provided, the value from
        the input port at the time of invocation is returned.

        :param address: Bus address to read
        :type address: int, optional
        :param latency: Additional latency cycles to add after addressing the 
        bus
        """

        # Note: the behavior described above is carried out by the compiler
        # when compiling an Operation with "bus_read"
        return Operation("bus_read", address=address, latency=latency, **kwargs)
    
    def bus_write(self, address, data, **kwargs):
        """
        Writes a value to the bus.
        """

        self.STP(src1=address, 
                dest1=Destination(Destination.Major.BUS_ADDR),
                src2=data, 
                dest2=Destination(Destination.Major.BUS_DATA),
                **kwargs)
        
    def halt(self):
        """
        Halts the sequencer. The reset pin must be toggled in order for the
        sequencer to execute any further instructions.
        """

        self.store(src=0, dest=Destination(Destination.Major.PC, 
                                           Destination.PC_RELATIVE_HOLD))
        
    def goto(self, target):
        self.store(src=target, dest=Destination(Destination.Major.PC, 
                                                Destination.PC_ABSOLUTE_BRANCH))
        
    def nop(self, **kwargs):
        self.store(src=Source(Source.Major.REG), 
                   dest=Destination(Destination.Major.REG),
                   **kwargs)
            
    @Processor.instruction()
    def STP(self, instruction_resource):
        """
        A direct abstraction of the STP instruction with additional source
        compilation.
        """

        kwargs = instruction_resource.kwargs
        instructions = []
        resources = []

        # We'll use lists to aggregate the two separate assignments so that
        # in case only src2/dest2 is specified, it gets prioritized to src1/dest1
        srcs = []
        dests = []
    
        for num in range(1,3):
            # Compile the source
            if f"src{num}" in kwargs:
                if f"dest{num}" not in kwargs:
                    raise ValueError(f"src{num} missing destination.")
                src,src_instrs,src_resources = self.compile_source(kwargs[f"src{num}"])
                srcs.append(src)
                instructions += src_instrs
                resources += src_resources

            # Resolve the destination if necessary
            if f"dest{num}" in kwargs:
                if f"src{num}" not in kwargs:
                    raise ValueError(f"dest{num} missing source.")
                
                dest = kwargs[f"dest{num}"]
                if isinstance(dest, self.Register) or isinstance(dest, self.DSP):
                    dests.append(dest.destination()) 
                else:
                    dests.append(dest)

        # Make sure that we didn't mess anything up
        if len(srcs) != len(dests):
            raise ValueError(f"Found {len(srcs)} sources and {len(dests)} destinations.")

        instructions.append(
            STP(src1=srcs[0],
                dest1=dests[0],
                src2=(srcs[1] if len(srcs) > 1 else Source(Source.Major.REG)),
                dest2=(dests[1] if len(dests) > 1 else Source(Source.Major.REG)),
                dsp_cep=(kwargs["dsp_cep"].source() if "dsp_cep" in kwargs else None),
                comment=(kwargs["comment"] if "comment" in kwargs else None),
                push_return=(kwargs["push_return"] if "push_return" in kwargs else False))
        )
        

        # Propagate any provided comment to the compiled instructions
        if "comment" in kwargs:
            for instr in instructions:
                instr.comment = kwargs["comment"]

        instruction_resource.compiled = instructions

        for res in resources:
            res._released = True
            
    @Processor.instruction()
    def STC(self, instruction_resource):
        """
        A direct abstraction of the STC instruction with additional source
        compilation.
        """

        kwargs = instruction_resource.kwargs
        instructions = []
        resources = []

        # Compile the sources       
        src_stval,extra_instrs,extra_resources = self.compile_source(kwargs[f"src_stval"])
        instructions += extra_instrs
        resources += extra_resources
        
        src_tval,extra_instrs,extra_resources = self.compile_source(kwargs[f"src_tval"])
        instructions += extra_instrs
        resources += extra_resources

        # Compile the destination
        dest_stval = kwargs["dest_stval"]
        if isinstance(dest_stval, self.Register) or isinstance(dest_stval, self.DSP):
            dest_stval = dest_stval.destination()

        # Create the instruction itself
        instructions.append(
            STC(src_stval=src_stval,
                dest_stval=dest_stval,
                src_tval=src_stval,
                op=kwargs["op"],
                dsp_cep=(kwargs["dsp_cep"].source() if "dsp_cep" in kwargs else None),
                comment=(kwargs["comment"] if "comment" in kwargs else None))
        )

        # Propagate any provided comment to the compiled instructions
        if "comment" in kwargs:
            for instr in instructions:
                instr.comment = kwargs["comment"]

        instruction_resource.compiled = instructions

        for res in resources:
            res._released = True
        
    @Processor.instruction()
    def store(self, instruction_resource):
        """
        A generalized method for storing data. It is assumed that multiple 
        consecutive calls to ``store`` may be aggregated into a smaller number
        of STP and/or STC instructions.
        
        Keyword arguments:

        :param src: The source of the data to store.
        :param dest: The destination for the data.
        :param when: The condition for the data to be stored. By default,
            ``store`` operations are unconditional.
        :type when: :class:`Operation`\, optional
        :param mask: Specifies the value to load into the mask register.
        """

        if len(instruction_resource.args) > 0:
            raise ValueError(f"Positional arguments not supported for store;"
                             f" must specify the source with the `src` keyword"
                             f" argument and the destination with the `dest`"
                             f" keyword argument."
                             f" Received {instruction_resource.args}.")
            
        # We need src and dest; these will throw KeyError if they aren't 
        # present, which is basically our desired behavior so no need to 
        # manually add key checking for this
        kwargs = instruction_resource.kwargs
        src = kwargs["src"]
        dest = kwargs["dest"]
        
        # Some other optional settings; we don't want to pop these from kwargs
        # because we want to keep the Instruction dict intact
        when = kwargs["when"] if "when" in kwargs else None
        mask = kwargs["mask"] if "mask" in kwargs else None
        dsp_cep = kwargs["dsp_cep"] if "dsp_cep" in kwargs else None
        push_return = kwargs["push_return"] if "push_return" in kwargs else False    
            
        # Check that we have valid destinations
        if isinstance(dest, self.Register):
            dest = Destination(major=Destination.Major.REG, 
                               minor=dest._resource_id)
        elif not (isinstance(dest, self.DSP) or isinstance(dest, Destination)):
            raise TypeError("The `dest` field must be either a `Register`,"
                            " `DSP`, or `Destination`.")
                                                                        
        if isinstance(dsp_cep, self.DSP):
            dsp_cep = dsp_cep.source()
        
        instructions = []
        if when is not None:
            stc_kwargs,condition_instructions,condition_resources = self.compile_condition(when, mask)
            instructions += condition_instructions
        
        if isinstance(src, Operation):    
            # If the destination is a DSP, we may be able to do the calculation in-place
            if isinstance(dest, self.DSP):    
                compiled_src,src_instructions,src_resources = self.compile_source(src, dsp=dest)
                instructions += src_instructions
            else:
                compiled_src,src_instructions,src_resources = self.compile_source(src)
                instructions += src_instructions
                instructions.append(STP(src1=compiled_src, 
                                         dest1=dest,
                                         dsp_cep=dsp_cep,
                                         push_return=push_return))
        else:
            # Otherwise, we can just directly generate a single write 
            # instruction (the dataclass will enforce types in __post_init__)     
            compiled_src,src_instructions,src_resources = self.compile_source(src)
            instructions += src_instructions
            
            if isinstance(dest, self.DSP):
                if when is not None:
                    raise ValueError(f"Cannot conditionally write to DSP P port.")
                    
                # Load P through AB
                instructions.append(STP(src1=Source(Source.Major.IMM), 
                                         dest1=dest["CFG"], 
                                         imm1=DSPConfiguration(mode="AB", 
                                                               dsp_cep="pulse"),
                                         src2=compiled_src, 
                                         dest2=dest["AB"],
                                         dsp_cep=dsp_cep,
                                         push_return=push_return))
            else:                
                if when is not None:
                    instructions.append(STC(src_stval=compiled_src, 
                                             dest_stval=dest, 
                                             dsp_cep=dsp_cep,
                                             push_return=push_return,
                                             **stc_kwargs))
                else:
                    instructions.append(STP(src1=compiled_src, 
                                             dest1=dest,
                                             dsp_cep=dsp_cep,
                                             push_return=push_return))
        if when is not None:
            for res in condition_resources:
                res._released = True
                
        if "comment" in kwargs:
            if len(instructions) == 1:
                instructions[0].comment = kwargs["comment"]
            else:
                for idx_instr,instr in enumerate(instructions):
                    instr.comment = f"({idx_instr+1}) " + kwargs["comment"]

        instruction_resource.compiled = instructions
    
    def compile_source(self, obj, dsp=None):
        """
        Compiles an object into a sequencer source. In some cases, a resource 
        (or multiple) will need to be allocated to compute the appropriate 
        source value; these resources and the additional instructions needed to
        operate them will be returned along with the compiled argument.

        :param obj: Object to translate
        :param dsp: If the eventual destination of the source is a DSP slice, 
            this argument will contain the DSP object.
        :type dsp: :class:`self.DSP`
        :return: A reference to the object ready to be assembled, a ``list`` of 
            generated instructions, and a ``list`` of allocated resources.
        """

        if dsp is not None and not isinstance(dsp, self.DSP):
            raise TypeError(f"Provided DSP destination must be of type DSP;"
                            f" received {dsp}.")
        
        if is_numeric(obj) or isinstance(obj, Source):
            return obj, [], []
        
        if isinstance(obj, self.Register) or isinstance(obj, self.DSP):
            return obj.source(), [], []

        # An Operation involving a resource; compile recursively
        # The if statements above along with the "getitem" Operation form
        # the bases cases for the recursion
        if isinstance(obj, Operation):
            # First check to see if we've received the special "bus_read" operation
            if obj._op == "bus_read":
                if "address" in obj._kwargs and obj._kwargs["address"] is not None:
                    addr,addr_instructions,addr_resources = self.compile_source(obj._kwargs["address"])
                    address_instr = STP(src1=addr, dest1=Destination(Destination.Major.BUS_ADDR))
                    latency_instrs = [STP(comment=f"Latency for bus read from address {addr}") for i in range(obj._kwargs["latency"])]

                    return Source(Source.Major.BUS_DATA), addr_instructions + [address_instr] + latency_instrs, addr_resources
                
                # If we haven't given it any address, just return the source associated with the bus
                return Source(Source.Major.BUS_DATA), [], []
            # Check that we have the right argument structure. invert will take
            # exactly one argument, otherwise we need exactly two. In both 
            # cases, there should be no keyword arguments
            if len(obj._kwargs) > 0:
                raise ValueError(f"Operation expects no keywords arguments;"
                                 f" received {obj._kwargs}.")
            
            if obj._op.__name__ == "invert":
                # This is the only operation that takes one argument. 
                # To make the compiler simpler, we can replace inversion 
                # with an XOR of all 1's
                return self.compile_source(
                            Operation(operator.xor, obj._args[0], 0xFFFFFFFF), 
                            dsp=dsp)
            
            if len(obj._args) != 2:
                raise ValueError(f"Operations inside of arguments"
                                 f" should have two arguments and"
                                 f" no keywords; received {obj}.")
                
            
            instructions = []
            resources = []
            
            # At this point, we know we'll actually be performing some 
            # non-trivial mathematical operation on hardware on actual 
            # hardware resources (the case where the operation is between 
            # numerics is handled in is_numeric).
            
            # We first need to compile the arguments into things that the DSP
            # slices can natively operate on
            args = [None, None]
            for i in range(2):
                args[i],arg_instructions,arg_resources = self.compile_source(obj._args[i])
                instructions += arg_instructions
                resources += arg_resources
                    
            if args[0] is None or args[1] is None:
                raise ValueError(f"Argument compilation failed;"
                                 f" received {args}.")
            
            # Figure out what DSP slice we'll use to carry out the computation
            # If we were given a DSP slice, it means we'll use it for an 
            # in-place calculation
            current_dsp = dsp
            
            # See if a DSP slice was allocated when compiling the arguments
            # Reverse the list of resources to prioritize reusing a DSP slice
            # allocated during the compilation of the last argument, because 
            # the one allocated most recently will be able to have greater 
            # flexibility in using previously-allocated slices for its PCIN 
            # input
            if current_dsp is None:
                for res in reversed(resources):
                    if isinstance(res, self.DSP):
                        current_dsp = res
                        break
            
            # If we still don't have a DSP slice, allocate one now
            if current_dsp is None:
                current_dsp = self.DSP()
                resources.append(current_dsp)
                
            # Now, determine how the arguments of the operation will enter the 
            # DSP slice performing it. By default, they'll need to be loaded 
            # into the external inputs exposed to the datapath
            # If the arguments are AB and C, we'll need separate instructions
            # to configure the DSP and load its inputs; otherwise, we can do 
            # this in one cycle
            arg_inputs = ["AB", "C"]
            for i,arg in enumerate(args):
                if isinstance(arg, Source) and "DSP" in arg.major.name:                
                    # If we're operating on the current DSP, use the P register
                    if arg.minor == current_dsp._resource_id:
                        arg_inputs[i] = "P"

                    # If we're operating on the lower neighboring DSP, use the
                    # cascade input
                    elif arg.minor == current_dsp._resource_id-1:
                        arg_inputs[i] = "PCIN"
                    
                # For addition and subtraction by 1, we can use the carry input
                elif (isinstance(arg, int) 
                      and abs(arg) == 1 
                      and obj._op in ["add", "sub"]):
                    arg_inputs[i] = str(arg)
                    
            # If we only have one external input, make it C, as the 
            # DSP slice is much more flexible in using C than AB
            if arg_inputs[0] == "AB" and arg_inputs[1] != "C":
                arg_inputs[0] = "C"
                
            # Look at the operator encoded in the Operation and convert it into
            # an operating configuration for the DSP slice
            if obj._op.__name__ == "add" or obj._op.__name__ == "iadd":
                dsp_mode_key = "{}+{}".format(*arg_inputs)
            elif obj._op.__name__ == "sub" or obj._op.__name__ == "isub":
                dsp_mode_key = "{}-{}".format(*arg_inputs) 
            elif obj._op.__name__ == "or_" or obj._op.__name__ == "ior":
                dsp_mode_key = "{} OR {}".format(*arg_inputs) 
            elif obj._op.__name__ == "and_" or obj._op.__name__ == "iand":
                dsp_mode_key = "{} AND {}".format(*arg_inputs) 
            elif obj._op.__name__ == "xor" or obj._op.__name__ == "ixor":
                dsp_mode_key = "{} XOR {}".format(*arg_inputs)         
            else:
                raise ValueError(f"Unable to find a DSP configuration for"
                                 f" Operation {obj}.")
                                
            # Finally, configure the slice
            # If we're still using AB, it means we must be using both external
            # inputs, so it's a two-cycle config and we need to spend a cycle
            # just loading AB
            if arg_inputs[0] == "AB":
                instructions.append(STP(src1=args[0], dest1=current_dsp["AB"]))
                
            # The next STP (or the only one, if arg_inputs[0] isn't AB)
            # will load C if necessary, and in either case CEP will be pulsed
            # If arg1 or arg2 are C, this means we're still loading some 
            # external input. Otherwise we might just be performing an
            # operation between registers inside the slice
            stp_args = {"src1": Source(Source.Major.IMM),
                        "imm1": DSPConfiguration(mode=dsp_mode_key, dsp_cep="pulse"),
                        "dest1": current_dsp["CFG"]}
            if arg_inputs[0] == "C":
                stp_args["src2"] = args[0]
                stp_args["dest2"] = current_dsp["C"]
            elif arg_inputs[1] == "C":
                stp_args["src2"] = args[1]
                stp_args["dest2"] = current_dsp["C"]
            
            # No external inputs are being loaded, therefore it's a purely
            # internal operation
            instructions.append(STP(**stp_args))
            
            # The DSP slice we used will contain the answer at the end, so 
            # return it along with any resources allocated during compilation
            return current_dsp.source(), instructions, resources

        raise TypeError(f"Unable to compile {obj} (type {type(obj)}).")
        
    def compile_condition(self, condition, mask=None):
        """
        Compiles an object into a sequencer condition. In some cases, a resource 
        (or multiple) will need to be allocated to compute the appropriate 
        source value; these resources and the additional instructions needed to
        operate them will be returned along with the compiled condition.

        :param condition: condition to translate
        :type condition: :class:`Operation`
        :param mask: The value to load into the mask, as indicated by "left" or
            "right", which correspond to the left-hand side and right-hand side of 
            the condition equation respectively. If not provided, an attempt to 
            infer it is made and an error is thrown if not possible.
        :return: A reference to the object ready to be assembled, a ``list`` of 
            generated instructions, and a ``list`` of allocated resources.
        """

        # Depending on what the condition ends up being, we'll populate a dict
        # with the eventual keyword arguments to the constructor for the 
        # instruction
        stc_kwargs = {}
        
        # We need to decode the provided condition into a test supported by the
        # sequencer's conditional store module
        # The following computations are supported, omitting the implicit
        # reduced OR across all bits of the result:
        # 0: SRC AND MASK
        # 1: SRC XOR MASK
        # 2: (NOT SRC) AND MASK
        # 3: SRC
        # If the condition is a primitive, we'll still insert the instructions
        # (in the future we may want to remove this for optimization, but for
        # now this could possibly be useful for testing and providing uniformity
        # in PS loops whose index variable is stored in a Symbol)
        if is_numeric(condition) or isinstance(condition, Source):
            stc_kwargs["src_tval"] = condition
            stc_kwargs["op"] = 0b11
            return stc_kwargs,[],[]
        elif isinstance(condition, self.Register):
            stc_kwargs["src_tval"] = Source(major=Source.Major.REG, 
                                            minor=condition._resource_id)
            stc_kwargs["op"] = 0b11
            return stc_kwargs,[],[]
        elif isinstance(condition, self.DSP):
            stc_kwargs["src_tval"] = Source(major=Source.Major.DSP_P, 
                                            minor=condition._resource_id)
            stc_kwargs["op"] = 0b11
            return stc_kwargs,[],[]
        elif isinstance(condition, Operation):
            # This Operation must be the comparison
            # Some operators can be recursively simplified
            if condition._op.__name__ == "invert":
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[0], mask)
                # Toggle the third bit, corresponding to the inverted condition
                stc_kwargs["op"] ^= 0b100
                return stc_kwargs,instructions,resources
            elif condition._op.__name__ == "gt":
                # We can only check if 0 > x
                if condition._args[0] != 0:
                    raise ValueError("Greater-than comparisons can only check 0 > x or x >= 0.")
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[1] & (1 << 31), mask)
                return stc_kwargs,instructions,resources
            elif condition._op.__name__ == "lt":
                # We can only check if x < 0
                if condition._args[1] != 0:
                    raise ValueError("Less-than comparisons can only check x < 0 or 0 <= x.")
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[0] & (1 << 31), mask)
                return stc_kwargs,instructions,resources
            elif condition._op.__name__ == "ge":
                # We can only check if x >= 0
                if condition._args[1] != 0:
                    raise ValueError("Greater-than comparisons can only check 0 > x or x >= 0.")
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[0] & (1 << 31), mask)
                stc_kwargs["op"] ^= 0b100
                return stc_kwargs,instructions,resources
            elif condition._op.__name__ == "le":
                # We can only check if 0 <= x
                if condition._args[0] != 0:
                    raise ValueError("Less-than comparisons can only check x < 0 or 0 <= x.")
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[1] & (1 << 31), mask)
                stc_kwargs["op"] ^= 0b100
                return stc_kwargs,instructions,resources
            elif condition._op.__name__ == "ne":
                new_condition = Operation(operator.eq, *condition._args, **condition._kwargs)
                stc_kwargs,instructions,resources = self.compile_condition(new_condition, mask)
                stc_kwargs["op"] ^= 0b100
                return stc_kwargs,instructions,resources
            
            # Base cases for recursive operation simplification
            elif condition._op.__name__ == "eq":
                if ((isinstance(condition._args[0], int) and condition._args[0] == 0) 
                    or (isinstance(condition._args[0], Symbol) 
                        and condition._args[0].assigned()
                        and condition._args[0].value_type() is int
                        and condition._args[0] == 0)):
                    stc_kwargs,instructions,resources = self.compile_condition(condition._args[1], mask)
                    stc_kwargs["op"] ^= 0b100
                    return stc_kwargs,instructions,resources
                elif ((isinstance(condition._args[1], int) and condition._args[1] == 0) 
                    or (isinstance(condition._args[1], Symbol) 
                        and condition._args[1].assigned()
                        and condition._args[1].value_type() is int
                        and condition._args[1] == 0)):
                    stc_kwargs,instructions,resources = self.compile_condition(condition._args[0], mask)
                    stc_kwargs["op"] ^= 0b100
                    return stc_kwargs,instructions,resources
                
                # not (SRC XOR MASK)
                stc_kwargs["op"] = 0b101
            elif condition._op.__name__ == "and_":
                stc_kwargs["op"] = 0b00
            elif condition._op.__name__ == "xor":
                stc_kwargs["op"] = 0b01
            else:
                # The Operation is computing something that is not a comparison,
                # compile it as a source and test whether the result is nonzero
                return self.compile_condition(condition != 0, mask)
                
            
        # Next, let's look at the arguments and compile as necessary
        # If one of them is a numeric or a register, we'll prefer to 
        # put that in the mask since those don't need to be monitored 
        # as closely        
        if mask is not None:
            if mask == "left":
                mask_obj = condition._args[0]
                test_obj = condition._args[1]
            elif mask == "right":
                mask_obj = condition._args[1]
                test_obj = condition._args[0]
            else:
                raise ValueError(f"Mask directive must be one of \"left\" or \"right\"; received {mask}.")
        elif is_numeric(condition._args[0]):
            mask_obj = condition._args[0]
            test_obj = condition._args[1]
        elif is_numeric(condition._args[1]):
            mask_obj = condition._args[1]
            test_obj = condition._args[0]
            
        # We can't combine these conditions with those above because we want 
        # to check for any numerics first
        elif isinstance(condition._args[0], self.Register):
            mask_obj = condition._args[0]
            test_obj = condition._args[1]
        elif isinstance(condition._args[1], self.Register):
            mask_obj = condition._args[1]
            test_obj = condition._args[0]
        else:
            raise TypeError(f"Unable to determine test and mask roles for"
                            f" condition {condition}")
            
        instructions = []
            
        compiled_mask,mask_instructions,mask_resources = self.compile_source(mask_obj)
        instructions += mask_instructions
        instructions.append(STP(src1=compiled_mask, 
                                dest1=Destination(Destination.Major.MASK)))
        for res in mask_resources:
            res._released = True
            
        # Check to see if we should use the special operation mode that inverts
        # the test value
        if (isinstance(test_obj, Operation) 
                and test_obj._op == "invert" 
                and stc_kwargs["op"] & 0b11 == 0b00):
            stc_kwargs["op"] = 0b10
            test_obj = test_obj._args[0]
        
        compiled_src, src_instructions, src_resources = self.compile_source(test_obj)
        stc_kwargs["src_tval"] = compiled_src
        instructions += src_instructions
        return stc_kwargs,instructions,src_resources
    
    def add_latencies(self):
        """
        Iterates through a compiled program and ensures that operations requiring
        manually-added latency are correctly buffered. Note that this will only work
        in situations where the compiler is able to determine that the relevant 
        resources are being modified, so it is encouraged for the user to verify
        the timings of expected procedures.

        :return: ``True`` if the program was modified, otherwise ``False``
        :rtype: bool
        """

        # If we used any DSP slices, we need to make sure that we add delays
        # to account for the computation latency
        # We'll do this by associating a counter with every DSP slice. When
        # a DSP slice has its CEP pin activated, the counter will get set to
        # the required latency amount and will decrement every cycle thereafter
        # (unless the CEP pin is pulsed again, in which case it is reset). 
        # When an instruction encountered that depends on the value of a given
        # DSP slice, if the counter for that slice is non-zero, that many NOPs
        # are added.
        dsp_count_init = 2
        counts = {f"DSP{i}": 0 for i in range(8)}
        
        for idx_instr,instr in enumerate(self._compiled_program):  
            # Decrement all counts to indicate that a cycle has passed
            for k in counts.keys():
                if counts[k] > 0:
                    counts[k] -= 1
                    
            if instr.dsp_cep is not None:
                if isinstance(instr.dsp_cep, SequencerDatapathPort):
                    counts[instr.dsp_cep.minor] = dsp_count_init
                elif isinstance(instr.dsp_cep, int):
                    counts[instr.dsp_cep] = dsp_count_init
                else:
                    raise TypeError(f"DSP CEP field must be of type"
                                    f" `SequencerDatapathPort` or `int`;"
                                    f" received {instr.dsp_cep}.")

            srcs = [instr.src_stval if isinstance(instr, STC) else instr.src1,
                     instr.src_tval if isinstance(instr, STC) else instr.src2]
            dests = [instr.dest_stval if isinstance(instr, STC) else instr.dest1,
                     None if isinstance(instr, STC) else instr.dest2]
            imms = [instr.imm_stval if isinstance(instr, STC) else instr.imm1,
                     instr.imm_tval if isinstance(instr, STC) else instr.imm2]
            for src,dest,imm in zip(srcs, dests, imms):
                # If we're configuring a DSP CFG register, it's very likely 
                # that its CEP pin will be affected, so we'll reset the counter
                # just in case
                
                # If a source of the operation we're configuring the DSP for
                # depends on PCIN, we may need to add delays
                # If we can't figure it out, assume the user was cautious
                # (probably a bad assumption but we'll need a smarter way to
                # detect issues with this)
                # we also won't add delays if we've detected that we need to
                # restart the search, since the insertion of delays elsewhere
                # could lead to adding too many delays
                if dest is not None:
                    if dest.major is Destination.Major.DSP_CFG:
                        counts[f"DSP{dest.minor}"] = dsp_count_init
                        if ( (isinstance(src, DSPConfiguration) and "PCIN" in src.mode)
                          or (src.major is Source.Major.IMM 
                              and isinstance(imm, DSPConfiguration)
                              and "PCIN" in imm.mode)):

                            if counts[f"DSP{dest.minor-1}"] > 0:
                                nops = [STP(comment=f"Pipeline latency for DSP{dest.minor-1}")]*counts[f"DSP{dest.minor-1}"]
                                self.insert_compiled_instructions(idx_instr, nops)
                                return True

                # Now check the sources. If we are depending on the value 
                # of a DSP slice, we need to make sure that we've given it 
                # enough time to complete the computation
                if src.major is Source.Major.DSP_P:
                    if counts[f"DSP{src.minor}"] > 0:
                        nops = [STP(comment=f"Pipeline latency for DSP{src.minor}")]*counts[f"DSP{src.minor}"]
                        self.insert_compiled_instructions(idx_instr, nops)
                        return True
                
        return False

    def compile_all(self, overwrite=False):
        """
        Invokes the typical compilation procedure and then verifies that any
        intermediate computations are buffered with an appropriate amount of
        pipeline cycles.
        """

        super().compile_all(overwrite)

        # Add necessary latencies until it can be confirmed that no more are
        # needed
        while self.add_latencies():
            pass
    
    @contextmanager
    def test(self, condition, mask=None, speculation=True):
        """
        Executes a block of code when the provided condition is satisfied. For
        best performance, one may specify the most likely outcome of the 
        condition if known, which will influence the placement of the resulting
        block.
        
        :param condition: Condition to test
        :type condition: :class:`Operation`
        :param mask: The object to load into the mask register, when provided
        :param speculation: The speculated outcome of the condition (e.g.,
            ``True`` if the condition is expected to pass the majority of the time).
        :type speculation: ``bool``
        """

        if speculation:
            # The block to execute if the condition passes is inline
            # Jump past the block if the condition fails
            jump = self.store(dest=Destination(Destination.Major.PC, 
                                               Destination.PC_ABSOLUTE_BRANCH), 
                              when=~condition,
                              mask=mask)
        else:
            # Jump to the block and push the return location
            # if the condition passes
            jump = self.store(dest=Destination(Destination.Major.PC, 
                                               Destination.PC_ABSOLUTE_BRANCH), 
                              when=condition,
                              mask=mask,
                              push_return=True)
            jump_target = self.Instruction.next_instance()

        self.block_start(inline=speculation)
        num_before = self.Instruction.usage()
        yield
        self.block_end(inline=speculation)
        
        # TODO
        # If only one instruction was added and if it's a store with a single
        # write, just replace it with an STC
        
        if speculation:
            jump_target = self.Instruction.next_instance()
        else:
            # Return from the block
            self.store(src=Source(Source.Major.STACK), 
                       dest=Destination(Destination.Major.PC, 
                                        Destination.PC_ABSOLUTE_BRANCH))
 
        jump.kwargs["src"] = jump_target
        
    @contextmanager
    def repeat_until(self, condition, mask=None):
        """
        Waits until a particular condition is satisfied. If possible, the value
        to be written to the branch mask register is inferred. If this is not 
        possible, a block of code is declared with a jump back to the beginning
        at the end if the condition is not satisfied (analogous to a "do-while" 
        loop in other languages). 
        """

        return_instruction = self.Instruction.next_instance()
        yield

        if not return_instruction.assigned():
            # No instructions have been added in the block and we can infer 
            # which argument should be stored in the mask. Therefore, we can
            # use the hold destination                
            hold_instruction = self.store(dest=Destination(Destination.Major.PC, 
                                                           Destination.PC_ABSOLUTE_HOLD),
                                           when=~condition,
                                           mask=mask)

            # Call next_instance() again because store() will mean that
            # return_instruction will not have the value we want
            hold_instruction.kwargs["src"] = self.Instruction.next_instance()
        else:
            # We have some instructions added in the block so we can't just 
            # hold, but we can still determine what to store in the mask.
            # Therefore, jump back to the beginning of the block
            self.store(src=return_instruction, 
                       dest=Destination(Destination.Major.PC, 
                                        Destination.PC_ABSOLUTE_BRANCH),
                       when=~condition,
                       mask=mask)
            
    @contextmanager
    def loop(self, *args):
        """
        Repeats a block of code multiple times. There are multiple valid call 
        signatures which must be used positionally (i.e., keyword arguments
        are not supported):

        - ``loop()``
        - ``loop(stop)``
        - ``loop(start, stop)``
        - ``loop(start, stop, step)``

        where the behavior and definitions of these parameters are identical to
        those of ``range``\, and when no parameters are provided the loop will 
        execute forever. The loop is implemented with a DSP, and the context 
        target yielded by this function is the allocated DSP object (which will
        inherently contain the iteration variable)
        """

        dsp = self.DSP()
        if len(args) == 0:
            # Do nothing
            pass

        elif len(args) == 1:
            start = 0
            stop = args[0]
            step = 1
            self.store(dest=dsp["CFG"], 
                       src=DSPConfiguration("P+1", rst_p=True), 
                       comment="Configure DSP for loop")
        elif len(args) == 2:
            start = args[0]
            stop = args[1]
            step = 1
            # We have to insert an instruction to load P with the start value,
            # since it requires one store to load the start value into a DSP 
            # register and another to configure the DSP to load P with it
            dsp.load(start)
            self.store(dest=dsp["CFG"], 
                       src=DSPConfiguration("P+1"),
                       comment="Configure DSP for loop")
        elif len(args) == 3:
            start = args[0]
            stop = args[1]
            step = args[2]
            dsp.load(start)
            self.STP(src1=Source(Source.Major.IMM), 
                     dest1=dsp["CFG"], 
                     imm1=DSPConfiguration("P+AB"),
                     src2=step,
                     dest2=dsp["AB"],
                     comment="Configure DSP for loop")
        else:
            raise ValueError(f"Unrecognized call signature for loop;"
                             f" receieved {args}.")
        
        loop_block_start = self.Instruction.next_instance()
            
        yield dsp
            
        # Branch back to the start of the loop block if we haven't reached the end
        jump_condition = (dsp != stop) if len(args) > 0 else None

        self.store(src=loop_block_start.value(), 
                    dest=Destination(Destination.Major.PC, 
                                    Destination.PC_ABSOLUTE_BRANCH), 
                    when=jump_condition,
                    dsp_cep=dsp.source(),
                    comment="Branch back to loop start")

