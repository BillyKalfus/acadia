import re
import struct
from itertools import permutations
from dataclasses import dataclass

__all__ = ["DSPMode", "save_dsp_modes", "load_dsp_modes"]

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
    
    def __post_init__(self):
        if isinstance(self.name, bytes):
            self.name = self.name.decode("ascii").strip('\x00')
            
        if len(self.name) > 26:
            raise ValueError(f"DSPMode name {self.name} is too long (must be"
                             " less than 26 characters)")
    
    def pack(self):
        return struct.pack("<BBBBBB26s", 
                           self.w, 
                           self.z, 
                           self.y, 
                           self.x, 
                           self.alumode, 
                           self.cin,
                           self.name.encode("ascii"))
    
    @staticmethod    
    def unpack(data):
        return DSPMode(*struct.unpack("<BBBBBB26s", data))
    
def generate_dsp_modes():
    modes = {}
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
                                
                                if key not in modes:
                                    modes[key] = DSPMode(w, z, y, x, alumode, set_cin, key)

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
                                modes[key] = DSPMode(0, z, y, x, alumode+inv_z, False, key)
                                
    return modes

def save_dsp_modes(file):
    modes = generate_dsp_modes()
    with open(file, "wb") as f:
        for mode in modes.values():
            f.write(mode.pack())
            
def load_dsp_modes(file):
    modes = {}
    with open(file, "rb") as f:
        while True:
            data = f.read(32)
            if len(data) == 0:
                break
            elif len(data) != 32:
                raise ValueError(f"Received unexpected number of bytes ({len(data)})")
            mode = DSPMode.unpack(data)
            modes[mode.name] = mode
    return modes