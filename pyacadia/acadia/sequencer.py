__all__ = ["Sequencer", "DSPConfiguration", "DSP_MODES"]

import re
from collections import namedtuple
from enum import Enum
from typing import get_type_hints
from itertools import permutations
from dataclasses import dataclass
from contextlib import contextmanager

from .compiler import ManagedResource, Symbol, Operation, Processor, Operable, ProcessorInstruction

def is_numeric(obj):
    """
    :return: `True` if a given object is suitable as a numeric argument for assembly.
    :rtype: `bool`
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
    major: "" = None
    minor: "" = 0

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
        
        # def field_getattr(self, attr):
        #     return self(getattr(self.Major, attr))
            
class Source(SequencerDatapathPort, metaclass=Operable):
    class Major(Enum):
        REG = 0
        PC = 1
        IMM = 2
        EXT = 3
        STACK = 4
        BUS_DATA = 5
        DSP_PATTERN = 6
        DSP_P = 7
            
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

# DSP operating modes
# All constants come from Xilinx UG579
@dataclass
class DSPMode:
    w: int = 0
    z: int = 0
    y: int = 0
    x: int = 0
    alumode: int = 0
    cin: int = 0
    name: str = ""

DSP_MODES = {}
for z_name,z in [("", 0),("P", 0b010), ("C",0b011), ("I", 0b001), ("S", 0b110)]:
    for x_name,x in [("", 0), ("P", 0b10), ("A", 0b11)]:
        for z_sign,wyxcin_sign,minus_one,alumode in [("+", "+", False, 0b0000), ("+", "-", False, 0b0011), ("-", "+", True, 0b0001), ("-", "-", True, 0b0010)]:
            for w_name,w in [("", 0), ("P", 0b01), ("C", 0b11)]:
                for y_name,y in [("", 0), ("C", 0b11)]:
                    for set_cin in range(2):
                        z_str = f"{z_sign}{z_name}" if z else "+0"
                        w_str = f"{wyxcin_sign}{w_name}" if w else "+0"
                        y_str = f"{wyxcin_sign}{y_name}" if y else "+0"
                        x_str = f"{wyxcin_sign}{x_name}" if x else "+0"
                        
                        # Because of the +1 associated with CIN and the -1 
                        # associated with computing the NOT of an arithmetic
                        # operation in 2's complement, the operation could have
                        # an additive constant with a couple of different 
                        # potential values
                        constant = 0
                        constant += -set_cin if wyxcin_sign == "-" else set_cin
                        constant += -1 if minus_one else 0
                        constant_str = f"{'+' if constant >= 0 else ''}{constant}"

                        # Because addition is commutative, generate all permutations
                        # of the operands
                        for str_pieces in permutations([w_str, z_str, y_str, x_str, constant_str]):

                            key = "".join(str_pieces)

                            # Simplify some zeros before adding to the list
                            key = key.replace("+0", "")
                            for k in ["C", "P"]:
                                key = key.replace(f"-{k}+{k}", "")
                                key = key.replace(f"+{k}-{k}", "")
                            if key.startswith("+"):
                                key = key[1:]
                            key = (key.replace("A", "AB")
                                       .replace("I", "PCIN")
                                       .replace("S", "(P >> 17)"))
                            
                            if key not in DSP_MODES:
                                DSP_MODES[key] = DSPMode(w, z, y, x, alumode, set_cin, key)

        # Add the two-input logic operations
        if x and z:
            for op_name,y,alumode in [("XOR", 0, 0b0100), ("XNOR", 0, 0b0110),
                                      ("AND", 0, 0b1100), ("NAND", 0, 0b1110),
                                      ("OR", 0b10, 0b1100), ("NOR", 0b10, 0b1110)]:
                # Implement patterns for versions where Z is inverted as
                # well as with keys where we've reversed the order of the
                # arguments (since the logic operations are commutative)
                for inv_z in range(2):
                    for reverse in range(2):
                        if inv_z:
                            if reverse:
                                key = f"(NOT {z_name}) {op_name} {x_name}"
                            else:
                                key = f"{x_name} {op_name} (NOT {z_name})"
                        else:
                            if reverse:
                                key = f"{x_name} {op_name} {z_name}"
                            else:
                                key = f"{z_name} {op_name} {x_name}"

                        # Apply some logical simplifications:
                        # A NOR (NOT B) = (NOT A) AND B
                        # A NAND (NOT B) = (NOT A) OR B
                        # A XNOR (NOT B) = A XOR B
                        for regex,replacement in [("([APCIS]) NOR \\(NOT ([APCIS])\\)", 
                                                   "(NOT {}) AND {}"),
                                                  ("([APCIS]) NAND \\(NOT ([APCIS])\\)", 
                                                   "(NOT {}) OR {}"),
                                                  ("([APCIS]) XNOR \\(NOT ([APCIS])\\)", 
                                                   "{} XOR {}"),
                                                  ("\\(NOT ([APCIS])\\) NOR ([APCIS])", 
                                                   "{} AND (NOT {})"),
                                                  ("\\(NOT ([APCIS])\\) NAND ([APCIS])", 
                                                   "{} OR (NOT {})"),
                                                  ("\\(NOT ([APCIS])\\) XNOR ([APCIS])", 
                                                   "{} XOR {}")]:
                            operands = re.findall(regex, key)
                            if operands:
                                if len(operands) > 1:
                                    raise ValueError(f"Found more than one"
                                                     f" match for {regex} in"
                                                     f" key {key}")
                                key = replacement.format(*(operands[0]))

                        # A NAND A = NOT A
                        # A NOR A = NOT A
                        for gate in ["NAND", "NOR"]:
                            operands = re.findall(f"([APCIS]) {gate} \\1", key)
                            if operands:
                                if len(operands) > 1:
                                    raise ValueError(f"Found more than one"
                                                     f" match in key {key}")
                                key = f"NOT {operands[0]}"

                        # Discard some trivial operations
                        # A XOR A = 0
                        # A XNOR A = 1
                        # A AND A = A
                        # A OR A = A
                        for gate in ["XOR", "XNOR", "AND", "OR"]:
                            if re.search(f"([APCIS]) {gate} \\1", key):
                                key = ""

                        # A AND (NOT A) = 0
                        # A OR (NOT A) = 1
                        # A XOR (NOT A) = 1
                        # A XNOR (NOT A) = 0
                        for gate in ["XOR", "XNOR", "AND", "OR"]:
                            if re.search(f"([APCIS]) {gate} \\(NOT \\1\\)", key):
                                key = ""
                            if re.search(f"\\(NOT ([APCIS])\\) {gate} \\1", key):
                                key = ""

                        # Finally, replace our single-character 
                        # placeholders for AB and PCIN, while fixing the
                        # fact that this messes up "AND"
                        key = (key
                               .replace("A", "AB")
                               .replace("ABND", "AND")
                               .replace("I", "PCIN")
                               .replace("S", "(P >> 17)"))

                        if key:
                            DSP_MODES[key] = DSPMode(0, z, y, x, alumode+inv_z, False, key)

@dataclass
class DSPConfiguration:
    """
    A container for a 32-bit value to be written to the DSP configuration port.
    :param dsp: DSP to configure
    :type dsp: `int`, :class:`Source`, :class:`Destination`, or 
    :class:`Sequencer.DSP`
    :param mode: Mode in which to operate the DSP slice at the next clock cycle
    :type mode: :class:`DSPMode` or `str`
    :param rst_p: If `True`, the RST pin of the P register is pulsed when
    the configuration register is written.
    :type rst_p: `bool`, optional
    :param dsp_cep: Indicates how the clock enable for the DSP P register
    should be driven. If "pulse", the P register will be pulsed for one
    cycle immediately following the configuration. If "set", the input
    will be set high until reset. If "reset", the input will be set low.
    If `None` or omitted, no action will be taken and the pin will remain
    in its current state.
    :type dsp_cep: str, optional
    """
    mode: [DSPMode, str] = "P" # By default do nothing by loading P -> P
    rst_p: bool = False
    dsp_cep: str = None
    
    def __post_init__(self):
        """
        Assembles a 32-bit value which, when written to the DSP configuration
        destination on the sequencer, configures a given DSP slice.
        """
        if isinstance(self.mode, str):
            mode = DSP_MODES[self.mode]
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

    def assemble(self):
        """
        Assembles the instruction into a binary word.
        :return: A binary word representing the machine instruction.
        :rtype: int
        """
        tmp = 0
        # Opcode = 0 for STP
        tmp |= self.push_return << 104
        tmp |= self.src1.value() << 96
        tmp |= self.src2.value() << 88
        tmp |= self.dest1.value() << 80
        tmp |= self.dest2.value() << 72
        tmp |= ((self.dsp_cep.value() | 0x8) << 64) if self.dsp_cep is not None else 0

        imm1_value = self.imm1
        while hasattr(imm1_value, "value") or hasattr(imm1_value, "address"):
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

        tmp |= imm1_value << 32

        imm2_value = self.imm2
        while hasattr(imm2_value, "value") or hasattr(imm2_value, "address"):
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
            
        tmp |= imm2_value

        return tmp

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

    def assemble(self):
        """
        Assembles the instruction into a binary word.
        :return: A binary word representing the machine instruction.
        :rtype: int
        """
        tmp = 0
        tmp |= 1 << 112 # Opcode for STC
        tmp |= self.push_return << 104
        tmp |= self.src_stval.value() << 96
        tmp |= self.src_tval.value() << 88
        tmp |= self.dest_stval.value() << 80
        tmp |= self.op << 72
        tmp |= ((self.dsp_cep.value() | 0x8) << 64) if self.dsp_cep is not None else 0

        imm_stval_value = self.imm_stval
        while hasattr(imm_stval_value, "value") or hasattr(imm_stval_value, "address"):
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

        tmp |= imm_stval_value << 32

        imm_tval_value = self.imm_tval
        while hasattr(imm_tval_value, "value") or hasattr(imm_tval_value, "address"):
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
            
        tmp |= imm_tval_value

        return tmp
    
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
                        
        def register_str(reg_self):
            return f"REG{reg_self._resource_id}"
        
        def register_source(reg_self):
            return Source(Source.Major.REG, reg_self._resource_id)
        
        def register_destination(reg_self):
            return Destination(Destination.Major.REG, reg_self._resource_id)
                        
        reg_dct = {"operator_handler": resource_load,
                     "__str__": register_str,
                     "__repr__": register_str,
                     "load": resource_load,
                     "source": register_source,
                     "destination": register_destination}
        
        reg_dct.update(Operable.make_operator_functions(["eq", "ne", "gt", "lt", "ge", "le", 
                           "add", "radd", "iadd", "sub", "rsub", "isub", 
                           "and", "rand", "iand", "or", "ror", "ior", 
                           "mul", "rmul", "imul", 
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
                
        def dsp_start_count(dsp_self, inc=1):
            if isinstance(inc, int) and inc == 1:
                self.store(src=DSPConfiguration(mode="P+1", dsp_cep="set"), 
                           dest=Destination(major=Destination.Major.DSP_CFG,
                                            minor=dsp_self._resource_id))
            elif is_numeric(inc):
                self.STP(src1=DSPConfiguration(mode="P+AB", dsp_cep="set"), 
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
                     "operator_handler": resource_load,
                     "__setitem__": dsp_setitem,
                     "__getitem__": dsp_getitem,
                     "start_count": dsp_start_count,
                     "stop_count": dsp_stop_count,
                     "enabled": dsp_enabled,
                     "source": dsp_source}
        
        dsp_dct.update(Operable.make_operator_functions(["eq", "ne", "gt", "lt", "ge", "le", 
                           "add", "radd", "iadd", "sub", "rsub", "isub", 
                           "and", "rand", "iand", "or", "ror", "ior", 
                           "mul", "rmul", "imul", 
                           "xor", "rxor", "ixor", "invert"]))
        
        self.DSP = ManagedResource("DSP", 
                                    (), 
                                    dsp_dct, 
                                    allocation_limit=Sequencer.NUM_DSP)
     
    def bus_read(self, address=None, write_address=True):
        """
        Reads a value from the bus. If multiple reads are performed back-to-back, 
        the additional wait time needed to overcome the bus latency may be 
        unnecessary and may be excluded by setting `wait` to `False`. Additionally,
        if the address was already written to the bus address register, it may be
        unnecessary to write it again, and setting `write_address` to `False` will
        skip this. 
        """
        if write_address:
            if address is None:
                raise ValueError("Address must be provided when"
                                 " `write_address=True`.")
            self.STP(src1=address, 
                     dest1=Destination(Destination.Major.BUS_ADDR))
        
        return Source(Source.Major.BUS_DATA)
    
    def bus_write(self, address, data):
        """
        Writes a value to the bus.
        """
        self.STP(src1=address, 
                dest1=Destination(Destination.Major.BUS_ADDR),
                src2=data, 
                dest2=Destination(Destination.Major.BUS_DATA))
        
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
        
    def nop(self):
        self.store(src=Source(Source.Major.REG), 
                   dest=Destination(Destination.Major.REG))
            
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
        
        # Determine whether the operation was determined to be trivial
        if len(srcs) > 0:
            new_kwargs = {k:v for k,v in kwargs.items() if "src" not in k and "dest" not in k}
            for i in range(len(srcs)):
                new_kwargs[f"src{i+1}"] = srcs[i]
                new_kwargs[f"dest{i+1}"] = dests[i]

            instructions.append(STP(**new_kwargs))
        elif len(instructions) != 0:
            raise ValueError("Trivial STP generated with nonzero instruction buffer.")

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
        consecutive calls to `store` may be aggregated into a smaller number
        of STP and/or STC instructions.
        
        Keyword arguments:
        :param src: The source of the data to store.
        :param dest: The destination for the data.
        :param when: The condition for the data to be stored. By default,
        `store` operations are unconditional.
        :type when: :class:`Operation`, optional
        :param mask: Specifies the value to load into the mask register.
        """
        if len(instruction_resource.args) > 0:
            raise ValueError(f"Positional arguments not supported for store;"
                             f" must specify the source with the `src` keyword"
                             f" argument and the destination with the `dest`"
                             f" keyword argument."
                             f" Received {instruction_resource._args}.")
            
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
            # If the destination is a DSP, we may+ be able to do the calculation in-place
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
            for instr in instructions:
                instr.comment = kwargs["comment"]

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
        :return: A reference to the object ready to be assembled, a `list` of 
        generated instructions, and a `list` of allocated resources.
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
                return Source(Source.Major.BUS_DATA), [], []
            # Check that we have the right argument structure. invert will take
            # exactly one argument, otherwise we need exactly two. In both 
            # cases, there should be no keyword arguments
            if len(obj._kwargs) > 0:
                raise ValueError(f"Operation expects no keywords arguments;"
                                 f" received {obj._kwargs}.")
            
            if obj._op == "invert":
                # This is the only operation that takes one argument. 
                # To make the compiler simpler, we can replace inversion 
                # with an XOR of all 1's
                return self.compile_source(
                            Operation("xor", obj._args[0], 0xFFFFFFFF), 
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
            dsp_mode_key = None
                    
            for base,key_format in [("add", "{}+{}"), 
                                    ("sub", "{}-{}"), 
                                    ("or", "{} OR {}"), 
                                    ("and", "{} AND {}"),
                                    ("xor", "{} XOR {}")]:
                if obj._op == base or obj._op == f"i{base}":
                    dsp_mode_key = key_format.format(*arg_inputs)
                elif obj._op == f"r{base}":
                    dsp_mode_key = key_format.format(*reversed(arg_inputs))
                    
            if not dsp_mode_key:
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
        :return: A reference to the object ready to be assembled, a `list` of 
        generated instructions, and a `list` of allocated resources.
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
            # Some operators can be recursively simplified
            if condition._op == "invert":
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[0], mask)
                # Toggle the third bit, corresponding to the inverted condition
                stc_kwargs["op"] ^= 0b100
                return stc_kwargs,instructions,resources
            elif condition._op == "gt":
                # We can only check if 0 > x
                if condition._args[0] != 0:
                    raise ValueError("Greater-than comparisons can only check 0 > x or x >= 0.")
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[1] & (1 << 31), mask)
                return stc_kwargs,instructions,resources
            elif condition._op == "lt":
                # We can only check if x < 0
                if condition._args[1] != 0:
                    raise ValueError("Less-than comparisons can only check x < 0 or 0 <= x.")
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[0] & (1 << 31), mask)
                return stc_kwargs,instructions,resources
            elif condition._op == "ge":
                # We can only check if x >= 0
                if condition._args[1] != 0:
                    raise ValueError("Greater-than comparisons can only check 0 > x or x >= 0.")
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[0] & (1 << 31), mask)
                stc_kwargs["op"] ^= 0b100
                return stc_kwargs,instructions,resources
            elif condition._op == "le":
                # We can only check if 0 <= x
                if condition._args[0] != 0:
                    raise ValueError("Less-than comparisons can only check x < 0 or 0 <= x.")
                stc_kwargs,instructions,resources = self.compile_condition(condition._args[1] & (1 << 31), mask)
                stc_kwargs["op"] ^= 0b100
                return stc_kwargs,instructions,resources
            elif condition._op == "ne":
                new_condition = Operation("eq", *condition._args, **condition._kwargs)
                stc_kwargs,instructions,resources = self.compile_condition(new_condition, mask)
                stc_kwargs["op"] ^= 0b100
                return stc_kwargs,instructions,resources
            
            # Base cases for recursive operation simplification
            elif condition._op == "eq":
                
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
            elif condition._op == "and" or condition._op == "rand":
                stc_kwargs["op"] = 0b00
            elif condition._op == "xor" or condition._op == "rxor":
                stc_kwargs["op"] = 0b01
            
            
        # Next, let's look at the arguments and compile as necessary
        # If one of them is a numeric or a register, we'll prefer to 
        # put that in the mask since those don't need to be monitored as closely 
        instructions = []
        
        if mask is not None:
            if mask == "left":
                compiled_mask,mask_instructions,mask_resources = self.compile_source(condition._args[0])
                instructions += mask_instructions
                instructions.append(STP(src1=compiled_mask, 
                                        dest1=Destination(Destination.Major.MASK)))
                for res in mask_resources:
                    res._released = True
                compiled_src,src_instructions,src_resources = self.compile_source(condition._args[1])
            elif mask == "right":
                compiled_mask,mask_instructions,mask_resources = self.compile_source(condition._args[1])
                instructions += mask_instructions
                instructions.append(STP(src1=compiled_mask, 
                                        dest1=Destination(Destination.Major.MASK)))
                for res in mask_resources:
                    res._released = True
                compiled_src,src_instructions,src_resources = self.compile_source(condition._args[0])
            else:
                raise ValueError(f"Mask directive must be one of \"left\" or \"right\"; received {mask}.")
        elif is_numeric(condition._args[0]):
            instructions.append(STP(src1=condition._args[0], 
                                    dest1=Destination(Destination.Major.MASK)))
            compiled_src,src_instructions,src_resources = self.compile_source(condition._args[1])
        elif isinstance(condition._args[0], self.Register) or isinstance(condition._args[0], self.DSP):
            instructions.append(STP(src1=condition._args[0].source(), 
                                    dest1=Destination(Destination.Major.MASK)))
            compiled_src,src_instructions,src_resources = self.compile_source(condition._args[1])
        elif isinstance(condition._args[1], self.Register) or isinstance(condition._args[1], self.DSP):
            instructions.append(STP(src1=condition._args[1].source(), 
                                    dest1=Destination(Destination.Major.MASK)))
            compiled_src,src_instructions,src_resources = self.compile_source(condition._args[0])
        else:
            instructions.append(STP(src1=condition._args[1], 
                                    dest1=Destination(Destination.Major.MASK)))
            compiled_src,src_instructions,src_resources = self.compile_source(condition._args[0])
        
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
        :return: `True` if the program was modified, otherwise `False`
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
        dsp_count_init = 4
        bus_count_init = 4
        counts = {f"DSP{i}": 0 for i in range(8)}
        counts["BUS"] = 0
        
        for idx_instr,instr in enumerate(self._compiled_program):  
            # Decrement all counts to indicate that a cyle has passed
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

                    # If we're writing to the bus address register, we need to
                    # make sure to give the bus enough time to respond
                    elif dest.major is Destination.Major.BUS_ADDR:
                        counts["BUS"] = bus_count_init

                # Now check the sources. If we are depending on the value 
                # of a DSP slice, we need to make sure that we've given it 
                # enough time to complete the computation
                if src.major is Source.Major.DSP_P:
                    if counts[f"DSP{src.minor}"] > 0:
                        nops = [STP(comment=f"Pipeline latency for DSP{src.minor}")]*counts[f"DSP{src.minor}"]
                        self.insert_compiled_instructions(idx_instr, nops)
                        return True

                # If we're getting data from the bus, we need to make sure 
                # that we've given the bus enough time to shuttle the data
                elif src.major is Source.Major.BUS_DATA:
                    if counts[f"BUS"] > 0:
                        nops = [STP(comment=f"Pipeline latency for bus")]*counts[f"BUS"]
                        self.insert_compiled_instructions(idx_instr, nops)
                        return True
                
        return False

    def compile_all(self):
        """
        Invokes the typical compilation procedure and then verifies that any
        intermediate computations are buffered with an appropriate amount of
        pipeline cycles.
        """
        super().compile_all()

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
        `True` if the condition is expected to pass the majority of the time).
        :type speculation: `bool`
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
    def wait_until(self, condition, mask=None):
        """
        Waits until a particular condition is satisfied. If possible, the value
        to be written to the branch mask register is inferred. If this is not 
        possible, a block of code is declared with a jump back to the beginning
        at the end if the condition is not satisfied (analogous to a "do-while" 
        loop in other languages). 
        """
        return_instruction = self.Instruction.next_instance()
        yield
        
        if not self.Instruction.next_instance_assigned():
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
        `loop()`
        `loop(stop)`
        `loop(start, stop)
        `loop(start, stop, step)`
        where the behavior and definitions of these parameters are identical to
        those of `range`, and when no parameters are provided the loop will 
        execute forever. 
        The loop is implemented with a DSP, and the context target yielded by
        this function is the allocated DSP object (which will inherently 
        contain the iteration variable)
        """
        dsp = None
        if len(args) == 0:
            # Do nothing
            pass

        elif len(args) == 1:
            dsp = self.DSP()
            start = 0
            stop = args[0]
            step = 1
            self.store(dsp["CFG"], DSPConfiguration("P+1", rst_p=True))
        elif len(args) == 2:
            dsp = self.DSP()
            start = args[0]
            stop = args[1]
            step = 1
            # We have to insert an instruction to load P with the start value,
            # since it requires one store to load the start value into a DSP 
            # register and another to configure the DSP to load P with it
            dsp.load(start)
            self.store(dsp["CFG"], DSPConfiguration("P+1"))
        elif len(args) == 3:
            dsp = self.DSP()
            start = args[0]
            stop = args[1]
            step = args[2]
            dsp.load(start)
            self.STP(src1=Source(Source.Major.IMM), 
                     dest1=dsp["CFG"], 
                     imm1=DSPConfiguration("P+AB"),
                     src2=step,
                     dest2=dsp["AB"])
        else:
            raise ValueError(f"Unrecognized call signature for loop;"
                             f" receieved {args}.")
        
        loop_block_start = self.Instruction.next_instance()
            
        yield dsp
            
        block_empty = not self.Instruction.next_instance_assigned()
        if not block_empty and len(args) > 0:
            loop_block_start.kwargs["dsp_cep"] = dsp.source()
            
        end_condition = (dsp != stop) if len(args) > 0 else None

        jump = self.store(src=loop_block_start, 
                         dest=Destination(Destination.Major.PC, 
                                          Destination.PC_ABSOLUTE_BRANCH), 
                         when=end_condition)
        if block_empty and len(args) > 0:
            jump.kwargs["dsp_cep"] = dsp.source()