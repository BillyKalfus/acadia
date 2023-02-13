__all__ = ["Sequencer", "DSPConfiguration", "DSP_MODES"]

from collections import namedtuple
from enum import Enum
from itertools import permutations
from dataclasses import dataclass
from contextlib import contextmanager
import re

from .compiler import ManagedResource, Symbol, Operation, Processor, Operable

def is_numeric(obj):
    """
    :return: `True` if a given object is suitable as a numeric argument for assembly.
    :rtype: `bool`
    """
    if isinstance(obj, int):
        return obj.bit_length() <= 32
    if isinstance(obj, bool):
        return True
    if isinstance(obj, Symbol) and obj.value_type() is int:
        return True
    if isinstance(obj, DSPConfiguration):
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

class InstructionField(type):

    def __new__(meta_cls, name, bases, dct):
        
        def field_init(self, major, minor=0):
            self.major = major
            self.minor = minor
            
            if not isinstance(self.major, type(self).Major):
                raise TypeError(f"Expecting type {type(self).Major} for field major;"
                                f" received {self.major}.")

            if not isinstance(self.minor, int):
                raise TypeError(f"Expecting int for field minor;"
                                f" received {self.minor}.")

        def field_value(self):
            minor_value = self.minor.value() if "value" in dir(self.minor) else self.minor
            return self.major.value + minor_value

        def field_str(self):
            minor_str = self.minor if self.major is type(self).Major.REG or "DSP" in self.major.name else ""
            return f"{self.major.name}{minor_str}"

        def field_repr(self):
            return str(self)
        
        def field_getattr(self, attr):
            return self(getattr(self.Major, attr))
        
        dct["__init__"] = field_init
        dct["value"] = field_value
        dct["__str__"] = field_str
        dct["__repr__"] = field_repr
        meta_cls.__getattr__ = field_getattr

        return super(InstructionField, meta_cls).__new__(meta_cls, name, bases, dct)
    
class Source(metaclass=InstructionField):
    class Major(Enum):
        REG = 0
        PC = 8
        IMM = 16
        FLAGS = 32
        STACK = 40
        BUS_DATA = 48
        DSP_PATTERN = 56
        DSP_DATA = 64
            
class Destination(metaclass=InstructionField):
    class Major(Enum):
        REG = 0
        PC = 8
        HOLD = 16
        MASK = 24
        STACK = 40
        BUS_ADDR = 48
        BUS_DATA = 56
        DSP_CFG = 64
        DSP_AB = 72
        DSP_C = 80

# Create dataclasses for abstracting machine code
@dataclass
class STP:
    src1: 'Source or int' = Source.REG
    src2: 'Source or int' = Source.REG
    dest1: 'Destination or int' = Destination.REG
    dest2: 'Destination or int' = Destination.REG
    imm1: 'int or bool or Symbol or Operation or DSPMode' = 0
    imm2: 'int or bool or Symbol or Operation or DSPMode' = 0
    dsp_cep: 'InstructionField' = None
    push_return: 'bool or int' = False

    def __post_init__(self):
        # Check types
        if is_numeric(self.src1):
            self.imm1 = self.src1
            self.src1 = Source.IMM
        if not isinstance(self.src1, Source):
            raise TypeError(f"STP field src1 must be of type Source;"
                            f" received {self.src1}.")
        
        if is_numeric(self.src2):
            self.imm2 = self.src2
            self.src2 = Source.IMM
        if not isinstance(self.src2, Source):
            raise TypeError(f"STP field src2 must be of type Source;"
                            f" received {self.src2}.")

        if not isinstance(self.dest1, Destination):
            raise TypeError(f"STP field dest1 must be of type Destination;"
                            f" received {self.dest1}.")
            
        if not isinstance(self.dest2, Destination):
            raise TypeError(f"STP field dest2 must be of type Destination;"
                            f" received {self.dest2}.")
            
        if not is_numeric(self.imm1):
            raise TypeError(f"STP field imm1 must be numeric or DSPConfiguration;"
                            f" received {self.imm1}.")
            
        if not is_numeric(self.imm2):
            raise TypeError(f"STP field imm2 must be numeric or DSPConfiguration;"
                            f" received {self.imm2}.")
            
        if self.dsp_cep is not None and not (isinstance(self.dsp_cep, InstructionField) 
                                             or "DSP" not in self.dsp_cep.major.name):
            raise TypeError(f"STP field dsp_cep must be an InstructionField"
                            f" with \"DSP\" in the major member name;"
                            f" received {self.dsp_cep}.")
            
        if not (isinstance(self.push_return, int) or isinstance(self.push_return, bool)):
            raise TypeError(f"STP field push_return must be of type int or bool;"
                            f" received {self.push_return}.")

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
        tmp |= (self.dsp_cep.value() << 64) if self.dsp_cep is not None else 0

        if (isinstance(self.imm1, Symbol) 
            or isinstance(self.imm1, Operation)
            or isinstance(self.imm1, DSPConfiguration)):
            tmp |= self.imm1.value() << 32
        else:
            tmp |= self.imm1 << 32

        if (isinstance(self.imm2, Symbol) 
            or isinstance(self.imm2, Operation)
            or isinstance(self.imm2, DSPConfiguration)):
            tmp |= self.imm2.value()
        else:
            tmp |= self.imm2

        return tmp

@dataclass
class STC:
    src_stval: 'Source' = Source.REG
    src_tval: 'Source' = Source.REG
    dest_stval: 'Destination' = Destination.REG
    op: 'int' = 0
    imm_stval: 'int or bool or Symbol or Operation' = 0
    imm_tval: 'int or bool or Symbol or Operation' = 0
    dsp_cep: 'InstructionField' = None
    push_return: 'bool or int' = False

    def __post_init__(self):
        # Check types
        if is_numeric(self.src_stval):
            self.imm_stval = self.src_stval
            self.src_stval = Source.IMM
        if not isinstance(self.src_stval, Source):
            raise TypeError(f"STP field src_stval must be of type Source;"
                            f" received {self.src_stval}.")
        
        if is_numeric(self.src_tval):
            self.imm_tval = self.src_tval
            self.src_tval = Source.IMM
        if not isinstance(self.src_tval, Source):
            raise TypeError(f"STP field src_tval must be of type Source;"
                            f" received {self.src_tval}.")
            
        if not isinstance(self.dest_stval, Destination):
            raise TypeError(f"STP field dest_stval must be of type Destination;"
                            f" received {self.dest_stval}.")
            
        if not is_numeric(self.op):
            raise TypeError(f"STP field op must be numeric;"
                            f" received {self.op}.")
            
        if not is_numeric(self.imm_stval):
            raise TypeError(f"STP field imm_stval must be of type int, bool, Symbol,"
                            f" Operation, or DSPConfiguration;"
                            f" received {self.imm_stval}.")
            
        if not is_numeric(self.imm_tval):
            raise TypeError(f"STP field imm_tval must be of type int, bool, Symbol,"
                            f" Operation, or DSPConfiguration;"
                            f" received {self.imm_tval}.")
            
        if self.dsp_cep is not None and not (isinstance(self.dsp_cep, InstructionField) 
                                             or "DSP" not in self.dsp_cep.major.name):
            raise TypeError(f"STP field dsp_cep must be an InstructionField"
                            f" with \"DSP\" in the major member name;"
                            f" received {self.dsp_cep}.")
            
        if not (isinstance(self.push_return, int) or isinstance(self.push_return, bool)):
            raise TypeError(f"STP field push_return must be of type int or bool;"
                            f" received {self.push_return}.")

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
        tmp |= (self.dsp_cep.value() << 64) if self.dsp_cep is not None else 0

        if (isinstance(self.imm_stval, Symbol) 
            or isinstance(self.imm_stval, Operation)
            or isinstance(self.imm_stval, DSPConfiguration)):
            tmp |= self.imm_stval.value() << 32
        else:
            tmp |= self.imm_stval << 32

        if (isinstance(self.imm_tval, Symbol)
            or isinstance(self.imm_tval, Operation)
            or isinstance(self.imm_tval, DSPConfiguration)):
            tmp |= self.imm_tval.value()
        else:
            tmp |= self.imm_tval

        return tmp
    
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
        for sign,alumode in [("+", 0b0000), ("-", 0b0011)]:
            for w_name,w in [("", 0), ("P", 0b01), ("C", 0b11)]:
                for y_name,y in [("", 0), ("C", 0b11)]:
                    for set_cin in range(2):
                        w_str = f"+{w_name}" if w else "+0"
                        z_str = f"{sign}{z_name}" if z else "+0"
                        y_str = f"{sign}{y_name}" if y else "+0"
                        x_str = f"{sign}{x_name}" if x else "+0"
                        cin_str = f"{sign}1" if set_cin else "+0"

                        # Because addition is commutative, generate all permutations
                        # of the operands
                        for str_pieces in permutations([w_str, z_str, y_str, x_str, cin_str]):

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
    :param rst_a: If `True`, the RST pin of the A register is pulsed when 
    the configuration register is written.
    :type rst_a: `bool`, optional
    :param rst_b: If `True`, the RST pin of the B register is pulsed when 
    the configuration register is written.
    :type rst_b: `bool`, optional
    :param rst_c: If `True`, the RST pin of the C register is pulsed when
    the configuration register is written.
    :type rst_c: `bool`, optional
    :param rst_p: If `True`, the RST pin of the P register is pulsed when
    the configuration register is written.
    :type rst_p: `bool`, optional
    :param dsp_data_register_load: Indicates which DSP register should be 
    written, if the DSP_DATA destination is simultaneously written. Value
    should be "AB" or "C".
    :type dsp_data_register_load: `str`, optional
    :param dsp_data_signed: Indicates whether data loaded into a DSP 
    register is signed (and therefore, whether it should be sign-extended).
    If so, the sign is extended for the fill 48-bit width of the register.
    :type dsp_data_signed: `bool`, optional
    :param dsp_cep: Indicates how the clock enable for the DSP P register
    should be driven. If "pulse", the P register will be pulsed for one
    cycle immediately following the configuration. If "set", the input
    will be set high until reset. If "reset", the input will be set low.
    If `None` or omitted, no action will be taken and the pin will remain
    in its current state.
    :type dsp_cep: str, optional
    """
    mode: "DSPMode or str" = "P" # By default do nothing by loading P -> P
    rst_p: "bool" = False
    dsp_cep: "'pulse' or 'set' or 'reset'" = None
    
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
            
        self.Register = ManagedResource(
            "Register", 
            (), 
            {"operator_handler": resource_load,
             "__str__": register_str,
             "__repr__": register_str,
             "load": resource_load,
             "OPERATORS": ["eq", "ne", "gt", "lt", "ge", "le", 
                           "add", "radd", "iadd", "sub", "rsub", "isub", 
                           "and", "rand", "iand", "or", "ror", "ior", 
                           "mul", "rmul", "imul", 
                           "xor", "rxor", "ixor", "invert"]},
            instance_limit=Sequencer.NUM_REGISTERS)
        
        def dsp_str(dsp_self):
            return f"DSP{dsp_self._resource_id}"
            
        def dsp_getitem(dsp_self, key):
            return Operation("getitem", dsp_self, key)
                
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
                self.STP(src1=DSPConfiguration(mode="AB", 
                                               dsp_cep="pulse"), 
                         dest1=Destination(major=Destination.Major.DSP_CFG,
                                           minor=dsp_self._resource_id), 
                         src2=value, 
                         dest2=Destination(major=Destination.Major.DSP_AB,
                                           minor=dsp_self._resource_id))
                
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
            
        self.DSP = ManagedResource(
            "DSP", 
            (), 
            {"__str__": dsp_str,
             "__repr__": dsp_str,
             "load": resource_load,
             "operator_handler": resource_load,
             "__setitem__": dsp_setitem,
             "__getitem__": dsp_getitem,
             "start_count": dsp_start_count,
             "stop_count": dsp_stop_count,
             "OPERATORS": ["eq", "ne", "gt", "lt", "ge", "le", 
                           "add", "radd", "iadd", "sub", "rsub", "isub", 
                           "and", "rand", "iand", "or", "ror", "ior", 
                           "mul", "rmul", "imul", 
                           "xor", "rxor", "ixor", "invert"]},
            instance_limit=Sequencer.NUM_DSP)
     
    def bus_read(self, address):
        """
        Reads a value from the bus.
        """
        return Operation("bus_read", address)
    
    @Processor.instruction()
    def bus_write(self, instruction_resource):
        """
        Writes a value to the bus.
        """
        if len(instruction_resource["args"]) > 0:
            raise ValueError("Positional arguments not supported for store;"
                             f" received {instruction_resource._args}.")
    
        data = instruction_resource["kwargs"]["data"]
        address = instruction_resource["kwargs"]["address"]
        
        compiled_addr,addr_instructions,addr_resources = self.compile_source(address)
        compiled_data,data_instructions,data_resources = self.compile_source(data)
        
        instructions = addr_instructions + data_instructions
        instructions.append(STP(src1=Source.IMM,
                                imm1=compiled_addr, 
                                dest1=Destination.BUS_ADDR,
                                src2=compiled_data, 
                                dest2=Destination.BUS_DATA))
        
        for res in addr_resources + data_resources:
            res._released = True
            
        instruction_resource["compiled_instructions"] = instructions
        
    def goto(self, target):
        self.store(src=target, dest=Destination.PC)
        
    def nop(self):
        self.store(src=Source.REG, dest=Destination.REG)
                
    @Processor.instruction()
    def STP(self, instruction_resource):
        """
        A direct abstraction of the STP instruction.
        """
        kwargs = instruction_resource["kwargs"]
        compiled_kwargs = {}
        compiled_kwargs["src1"] = kwargs["src1"] if "src1" in kwargs else Source.REG
        compiled_kwargs["src2"] = kwargs["src2"] if "src2" in kwargs else Source.REG
        compiled_kwargs["dest1"] = kwargs["dest1"] if "dest1" in kwargs else Destination.REG
        compiled_kwargs["dest2"] = kwargs["dest2"] if "dest2" in kwargs else Destination.REG
        compiled_kwargs["imm1"] = kwargs["imm1"] if "imm1" in kwargs else 0
        compiled_kwargs["imm2"] = kwargs["imm2"] if "imm2" in kwargs else 0
        compiled_kwargs["dsp_cep"] = kwargs["dsp_cep"] if "dsp_cep" in kwargs else None
        compiled_kwargs["push_return"] = kwargs["push_return"] if "push_return" in kwargs else False
        instruction_resource["compiled_instructions"] = [STP(**compiled_kwargs)]
        
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
        
        if len(instruction_resource["args"]) > 0:
            raise ValueError("Positional arguments not supported for store;"
                             f" received {instruction_resource._args}.")
            
        # We need src and dest; these will throw KeyError if they aren't 
        # present, which is basically our desired behavior so no need to 
        # manually add key checking for this
        kwargs = instruction_resource["kwargs"]
        src = kwargs["src"]
        dest = kwargs["dest"]
                
        # Convert dest into a Destination if necessary
        if isinstance(dest, Operation):
            if dest._op == "getitem" and isinstance(dest._args[0], self.DSP):
                # Store directly into the port
                if dest._args[1] == "AB":
                    dest = Destination(major=Destination.Major.DSP_AB,
                                       minor=dsp_self._resource_id)
                elif dest._args[1] == "C":
                    dest = Destination(major=Destination.Major.DSP_C,
                                       minor=dsp_self._resource_id)
                elif dest._args[1] == "P":
                    # Handle below by replacing dest with the resource itself
                    dest = dest._args[0]
                else:
                    raise ValueError(f"Invalid DSP key {dest._args[1]}.")
            else:
                raise ValueError(f"Unable to store into destination {dest}.")
        elif isinstance(dest, self.Register):
            dest = Destination(major=Destination.Major.REG, 
                               minor=dest._resource_id)
        
        # Some other optional settings; we don't want to pop these from kwargs
        # because we want to keep the Instruction dict intact
        when = kwargs["when"] if "when" in kwargs else None
        mask = kwargs["mask"] if "mask" in kwargs else None
        dsp_cep = kwargs["dsp_cep"] if "dsp_cep" in kwargs else None
        push_return = kwargs["push_return"] if "push_return" in kwargs else False
        allow_hold = kwargs["allow_hold"] if "allow_hold" in kwargs else False
        
        instructions = []
        if when is not None:
            stc_kwargs,condition_instructions,condition_resources = self.compile_condition(when, mask)
            instructions += condition_instructions
        
        if isinstance(src, Operation):    
            # If it's not a compatible argument, it must be an Operation that
            # requires compilation and computation with a DSP slice.
            # If the destination is itself a DSP slice, we can pass that down
            # so that the compiled instructions just do the computation in the
            # desired destination slice.
            # Otherwise, after compiling we'll need to add our own instruction
            # to write the computed result from the slice into the destination
            if isinstance(dest, self.DSP):
                # Load P through AB
                compiled_src,src_instructions,src_resources = self.compile_source(src, dsp=dest)
                instructions += src_instructions
            else:
                compiled_src,src_instructions,src_resources = self.compile_source(src)
                instructions += src_instructions
                dest_field = Destination(major=Destination.Major.REG, 
                                         minor=dest._resource_id) if isinstance(dest, self.Register) else dest
                instructions.append(STP(src1=compiled_src, 
                                         dest1=dest_field,
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
                instructions.append(STP(src1=Source.IMM, 
                                         dest1=Destination(Destination.Major.DSP_CFG, 
                                                           dest._resource_id), 
                                         imm1=DSPConfiguration(mode="AB", 
                                                               dsp_cep="pulse"),
                                         src2=compiled_src, 
                                         dest2=Destination(Destination.Major.DSP_AB, 
                                                           dest._resource_id),
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
                
        instruction_resource["compiled_instructions"] = instructions
    
    def compile_source(self, obj, dsp=None):
        """
        Compiles an object into a sequencer source. In some cases, a resource 
        (or multiple) will need to be allocated to compute the appropriate 
        source value; these resources and the additional instructions needed to
        operate them will be returned along with the compiled argument.
        :param obj: Object to translate
        :param dsp: A pre-allocated DSP slice for use in the computation.
        :type dsp: :class:`self.DSPSlice`
        :return: A reference to the object ready to be assembled, a `list` of 
        generated instructions, and a `list` of allocated resources.
        """

        if dsp and not isinstance(dsp, self.DSP):
            raise TypeError(f"Provided DSP resource must be of type DSP;"
                            f" received {dsp}.")
        
        if is_numeric(obj) or isinstance(obj, Source):
            return obj,[],[]
        
        if isinstance(obj, self._Instruction):
            return obj["compiled_address"],[],[]
        
        if isinstance(obj, self.Register):
            return Source(major=Source.Major.REG, minor=obj._resource_id),[],[]
        
        if isinstance(obj, self.DSP):
            return Source(major=Source.Major.DSP_DATA, minor=obj._resource_id),[],[]
        
        # Note: not sure whether we need these
        if hasattr(obj, "address"):
            if callable(obj.address):
                return obj.address(),[],[]
            return obj.address,[],[]
        
        if isinstance(obj, Symbol) and "address" in dir(obj.value_type()):
            if callable(obj.value_type().address):
                return obj.value().address(),[],[]
            return obj.value().address,[],[]

        # An Operation involving a resource; compile recursively
        # The if statements above along with the "getitem" Operation form
        # the bases cases for the recursion
        if isinstance(obj, Operation):
               
            # Check that we have the right argument structure. invert will take
            # exactly one argument, otherwise we need exactly two. In both 
            # cases, there should be no keyword arguments since this was 
            # created by an operator (presumably)
            if len(obj._kwargs) > 0:
                raise ValueError(f"Operation expects no keywords arguments;"
                                 f" received {obj._kwargs}.")
                
            elif obj._op in ["invert", "bus_read"]:
                # Using this if structure (instead of just anding the two
                # conditions together) so that we don't execute the next elif
                # when the op is invert or bus_read
                if len(obj._args) != 1:
                    raise ValueError(f"Operation expects one argument;"
                                     f" received {obj}.")
                
            elif len(obj._args) != 2:
                raise ValueError(f"Operations inside of arguments"
                                 f" should have two arguments and"
                                 f" no keywords; received {obj}.")
            
            # Handle bus operations
            if obj._op == "bus_read":
                addr,addr_instructions,addr_resources = self.compile_source(obj._args[0])
                addr_instructions.append(STP(src1=Source.IMM, imm1=addr, dest1=Destination.BUS_ADDR))
                addr_instructions.append(STP())
                addr_instructions.append(STP())
                addr_instructions.append(STP())
                addr_instructions.append(STP())
                for res in addr_resources:
                    res._released = True
                return Source.BUS_DATA,addr_instructions,[]
                
            
            instructions = []
            resources = []
            
            # At this point, we know we'll actually be performing some 
            # non-trivial mathematical operation on hardware on actual 
            # hardware resources (the case where the operation is between 
            # numerics is handled in is_numeric).
            # If we were given a DSP slice, we have to decide which
            # argument to give it to when compiling, since either one could
            # require its own slice for temporary argument compilation
            # We'll (arbitrarily) choose to give it to arg1 if arg1 is an
            # Operation, and if it's not then we'll give it to arg2
            arg1_dsp = dsp if isinstance(obj._args[0], Operation) else None
            arg2_dsp = dsp if not isinstance(obj._args[0], Operation) else None
                        
            # Now, actually compile the arguments
            arg1,arg1_instructions,arg1_resources = self.compile_source(obj._args[0], dsp=arg1_dsp)
            instructions += arg1_instructions
            resources += arg1_resources
                
            if obj._op != "invert":
                arg2,arg2_instructions,arg2_resources = self.compile_source(obj._args[1], dsp=arg2_dsp)
                instructions += arg2_instructions
                resources += arg2_resources
                
            # If we're not given a DSP slice to use and we didn't allocate one
            # when compiling arg1 and arg2, we must allocate one here
            # We will choose to use a DSP slice allocated during the 
            # compilation of arg2 before using that of arg1, because the one
            # allocated most recently will be able to have greater flexibility
            # in using previously-allocated slices for its PCIN input
            if dsp is not None:
                current_dsp = dsp
            elif obj._op != "invert" and arg2_resources and isinstance(arg2_resources[0], self.DSP):
                current_dsp = arg2_resources[0]
            elif arg1_resources and isinstance(arg1_resources[0], self.DSP):
                current_dsp = arg1_resources[0]
            else:
                current_dsp = self.DSP()
                resources.append(current_dsp)
                
            # Now, determine the arguments to the slices and how they must
            # physically enter. By default, they'll need to be loaded into the
            # external inputs exposed to the datapath
            # If the arguments are AB and C, we'll need separate instructions
            # to configure the DSP and load its inputs; otherwise, we can do 
            # this in one cycle
            arg1_input = "AB"
            arg2_input = "C"
            if isinstance(arg1, Source) and "DSP" in arg1.major.name:                
                # If we're operating on the current DSP, use the P register
                if arg1.minor == current_dsp._resource_id:
                    arg1_input = "P"
                    
                # If we're operating on the lower neighboring DSP, use the cascade input
                elif arg1.minor == current_dsp._resource_id-1:
                    arg1_input = "PCIN"
                    
            # For addition and subtraction by 1, we can use the carry input
            elif isinstance(arg1, int) and abs(arg1) == 1 and obj._op in ["add", "sub"]:
                arg1_input = str(arg1)
                    
            if isinstance(arg2, Source) and "DSP" in arg2.name:
                num = int(arg2.name[3:])
                
                # If we're operating on the current DSP, use the P register
                if num == current_dsp._resource_id:
                    arg2_input = "P"

                # If we're operating on the lower neighboring DSP, use the cascade input
                elif num == current_dsp._resource_id-1:
                    arg2_input = "PCIN"
                    
            # For addition and subtraction by 1, we can use the carry input
            elif isinstance(arg2, int) and abs(arg2) == 1 and obj._op in ["add", "sub"]:
                arg2_input = str(arg2)
                
            # If we only have one external input, make it C
            if arg1_input == "AB" and arg2_input != "C":
                arg1_input = "C"
                
            # Look at the operator encoded in the Operation and convert it into
            # an operating configuration for the DSP slice
            dsp_mode_key = None
                    
            if obj._op == "invert":
                dsp_mode_key = f"NOT {arg1_input}"
                
            # elif obj._op == "mul" or obj._op == "rmul" or obj._op == "imul": 
            #     # One of the arguments must be an integer with a magnitude of
            #     # 2 or 3. Figure out which one this is
            #     if isinstance(arg1, int) and (abs(arg1) == 2 or abs(arg1) == 3):
            #         sign = "-" if arg1 < 0 else "+"
            #         dsp_mode_key = f"{sign}{arg2_input}"*abs(arg1)
            #         if dsp_mode_key.startswith("+"):
            #             dsp_mode_key = dsp_mode_key[1:]
            #     elif isinstance(arg2, int) and (abs(arg2) == 2 or abs(arg2) == 3):
            #         sign = "-" if arg2 < 0 else "+"
            #         dsp_mode_key = f"{sign}{arg1_input}"*abs(arg2)
            #         if dsp_mode_key.startswith("+"):
            #             dsp_mode_key = dsp_mode_key[1:]
            #     else:
            #         raise ValueError(f"Only multiplication by integers with"
            #                          f" magnitudes of 2 or 3 are supported;"
            #                          f" received Operation {obj}.")
                    
            else:
                for base,key_format in [("add", "{}+{}"), 
                                        ("sub", "{}-{}"), 
                                        ("or", "{} OR {}"), 
                                        ("and", "{} AND {}"),
                                        ("xor", "{} XOR {}")]:
                    if obj._op == base or obj._op == f"i{base}":
                        dsp_mode_key = key_format.format(arg1_input, arg2_input)
                    elif obj._op == f"r{base}":
                        dsp_mode_key = key_format.format(arg2_input, arg1_input)
                    
            if not dsp_mode_key:
                raise ValueError(f"Unable to find a DSP configuration for"
                                 f" Operation {obj}.")
                                
            # Finally, configure the slice
            # If we're still using AB, it means we must be using both external
            # inputs, so it's a two-cycle config
            if arg1_input == "AB":
                instructions.append(STP(src1=Source.IMM, 
                                        imm1=DSPConfiguration(mode=dsp_mode_key),
                                        dest1=Destination(Destination.Major.DSP_CFG,
                                                          current_dsp._resource_id),
                                        src2=arg1, 
                                        dest2=Destination(Destination.Major.DSP_AB,
                                                          current_dsp._resource_id)))
                
            # The next STP (or the only one, if arg1_input isn't AB)
            # will load C if necessary, and in either case CEP will be pulsed
            # If arg1 or arg2 are C, this means we're still loading some 
            # external input. Otherwise we might just be performing an
            # operation between registers inside the slice
            if arg1_input == "C":
                instructions.append(STP(src1=Source.IMM,
                                        imm1=DSPConfiguration(mode=dsp_mode_key, 
                                                              dsp_cep="pulse"), 
                                        dest1=Destination(Destination.Major.DSP_CFG,
                                                          current_dsp._resource_id),
                                        src2=arg1,
                                        dest2=Destination(Destination.Major.DSP_C,
                                                          current_dsp._resource_id)))
            elif arg2_input == "C":
                instructions.append(STP(src1=Source.IMM,
                                        imm1=DSPConfiguration(mode=dsp_mode_key, 
                                                              dsp_cep="pulse"), 
                                        dest1=Destination(Destination.Major.DSP_CFG,
                                                          current_dsp._resource_id),
                                        src2=arg2,
                                        dest2=Destination(Destination.Major.DSP_C,
                                                          current_dsp._resource_id)))
            
            # No external inputs are being loaded, therefore it's a purely
            # internal operation
            else:
                instructions.append(STP(src1=Source.IMM, 
                                        imm1=DSPConfiguration(mode=dsp_mode_key, 
                                                               dsp_cep="pulse"),
                                        dest1=Destination(Destination.Major.DSP_CFG,
                                                          current_dsp._resource_id)))
            
            # The DSP slice we used will contain the answer at the end, so 
            # return it along with any resources allocated during compilation
            return Source(Source.Major.DSP_DATA, current_dsp._resource_id),instructions,resources

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
            stc_kwargs["src_tval"] = Source(major=Source.Major.DSP_DATA, 
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
            
            # Base cases for recursive operation simplification
            elif condition._op == "eq":
                # not (SRC XOR MASK)
                stc_kwargs["op"] = 0b101
            elif condition._op == "and" or condition._op == "rand":
                stc_kwargs["op"] = 0b00
            elif condition._op == "xor" or condition._op == "rxor" or condition._op == "ne":
                stc_kwargs["op"] = 0b01
            
            
        # Next, let's look at the arguments and compile as necessary
        # If one of them is a numeric, we'll prefer to put that in the mask
        # since that's not time-sensitive 
        instructions = []
        
        if mask is not None:
            if mask == "left":
                compiled_mask,mask_instructions,mask_resources = self.compile_source(condition._args[0])
                instructions += mask_instructions
                instructions.append(STP(src1=compiled_mask, dest1=Destination.MASK))
                for res in mask_resources:
                    res._released = True
                compiled_src,src_instructions,src_resources = self.compile_source(condition._args[1])
            elif mask == "right":
                compiled_mask,mask_instructions,mask_resources = self.compile_source(condition._args[1])
                instructions += mask_instructions
                instructions.append(STP(src1=compiled_mask, dest1=Destination.MASK))
                for res in mask_resources:
                    res._released = True
                compiled_src,src_instructions,src_resources = self.compile_source(condition._args[0])
            else:
                raise ValueError(f"Mask directive must be one of \"left\" or \"right\"; received {mask}.")
        elif is_numeric(condition._args[0]):
            instructions.append(STP(src1=condition._args[0], dest1=Destination.MASK))
            compiled_src,src_instructions,src_resources = self.compile_source(condition._args[1])
        else:
            instructions.append(STP(src1=condition._args[1], dest1=Destination.MASK))
            compiled_src,src_instructions,src_resources = self.compile_source(condition._args[0])
        
        stc_kwargs["src_tval"] = compiled_src
        instructions += src_instructions
        return stc_kwargs,instructions,src_resources

    
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
            jump = self.store(dest=Destination.PC, 
                              when=~condition,
                              mask=mask)
        else:
            # Jump to the block and push the return location
            # if the condition passes
            jump = self.store(dest=Destination.PC, 
                              when=condition,
                              mask=mask,
                              push_return=True)
            jump_target = self._Instruction.next_instance()

        self.block_start(inline=speculation)
        num_before = self._Instruction.usage()
        yield Source.TEST_VALUE
        self.block_end(inline=speculation)
        
        # TODO
        # If only one instruction was added and if it's a store with a single
        # write, just replace it with an STC
        
        if speculation:
            jump_target = self._Instruction.next_instance()
        else:
            # Return from the block
            self.store(src=Source.STACK, dest=Destination.PC)
 
        jump["kwargs"]["src"] = jump_target
        
    @contextmanager
    def wait_until(self, condition, mask=None):
        """
        Waits until a particular condition is satisfied. If possible, the value
        to be written to the branch mask register is inferred. If this is not 
        possible, a block of code is declared with a jump back to the beginning
        at the end if the condition is not satisfied (analogous to a "do-while" 
        loop in other languages). 
        """
        return_instruction = self._Instruction.next_instance()
        yield
        mask_determined = (mask is not None)
        for arg in range(2):
            if is_numeric(condition._args[arg]):
                mask_determined = True
        
        # Note that it may be difficult to rearrange the "if" structure here, 
        # because if the clauses add any instructions then checking whether the
        # next_instance symbol was assigned will break
        if mask_determined:
            if not self._Instruction.next_instance_assigned():
                # No instructions have been added in the block and we can infer 
                # which argument should be stored in the mask. Therefore, we can
                # use the hold destination                
                hold_instruction = self.store(dest=Destination.HOLD,
                                   when=~condition,
                                   mask=mask)
                
                # Call next_instance() again because store() will mean that
                # return_instruction will not have the value we want
                hold_instruction["kwargs"]["src"] = self._Instruction.next_instance()
                
            # TODO
                # Alternatively, if we added only one DSP augmenting operation
                # and the external argument is either a constant or a register,
                # we can configure the DSP before the loop starts and set 
                # dsp_cep
            else:
                # We have some instructions added in the block so we can't just 
                # hold, but we can still determine what to store in the mask.
                # Therefore, jump back to the beginning of the block
                self.store(src=return_instruction, 
                           dest=Destination.PC,
                           when=~condition,
                           mask=mask)
        else:
            raise ValueError(f"Unable to determine branch mask for"
                             f" condition {condition}.")
            
        
                
    @contextmanager
    def loop(self, *args):
        """
        Repeats a block of code multiple times. There are multiple valid call 
        signatures which must be used positionally (i.e., keyword arguments
        are not supported):
        `loop(stop)`
        `loop(start, stop)
        `loop(start, stop, step)`
        where the behavior and definitions of these parameters are identical to
        those of `range`. 
        The loop is implemented with a DSP, and the context target yielded by
        this function is the allocated DSP object (which will inherently 
        contain the iteration variable)
        """
        if len(args) == 1:
            start = 0
            stop = args[0]
            step = 1
        elif len(args) == 2:
            start = args[0]
            stop = args[1]
            step = 1
        elif len(args) == 3:
            start = args[0]
            stop = args[1]
            step = args[2]
        else:
            raise ValueError(f"Unrecognized call signature for loop;"
                             f" receieved {args}.")
        dsp = self.DSP()
        
        # TODO
        # If the start value is 0, we don't need a separate instruction to load
        # P first, since we can reset it when 