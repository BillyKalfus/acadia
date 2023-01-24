from numbers import Number
from collections import namedtuple
from ..assembler import ManagedResource, Symbol
from ..processors import Processor

class Sequencer(Processor):
    """
    A :class:`Processor` for the sequencer embedded in the Acadia control 
    system.
    """
    
    # The total number of general-purpose registers in the sequencer
    NUM_REGISTERS = 8
    
    # The total number of DSP slices accessible from the sequencer
    NUM_DSP = 4
    
    # The constants that represent data sources
    SRC_REG = 0
    SRC_PC = 8
    SRC_IMM = 9
    SRC_TEST = 10
    SRC_FLAGS = 11
    SRC_STACK = 12
    SRC_BUS_ADDR = 13
    SRC_BUS_DATA = 14
    SRC_BUS_PEEK = 15
    SRC_DSP_P_LO = 16
    SRC_DSP_P_HI = 20
    
    # The constants for data destinations
    DEST_REG = 0
    DEST_PC = 8
    DEST_HOLD = 9
    DEST_MASK = 10
    DEST_FLAGS = 11
    DEST_STACK = 12
    DEST_BUS_ADDR = 13
    DEST_BUS_DATA = 14
    DEST_DSP_AB = 16
    DEST_DSP_C_LO = 20
    DEST_DSP_C_HI = 24
    DEST_DSP_CFG = 28
    DEST_DSP_CIN = 29
    DEST_DSP_P_EN = 30
    
    @staticmethod
    def is_numeric(obj):
        """
        :return: `True` if a given object is suitable as a numeric argument for assembly.
        :rtype: `bool`
        """
        if isinstance(obj, int):
            return obj.bit_length() <= 32
        if isinstance(obj, Symbol) and obj.value_type() is int:
            return True
        if isinstance(obj, Operation):
            return (reduce(operator.and_, map(Sequencer.is_numeric, obj._args)) 
                    and reduce(operator.and_, map(Sequencer.is_numeric, obj._kwargs.values())))
        return False
    
    # Field names for instructions
    STP_FIELDS = ["src1", "src2", "dest1", "dest2", "imm1", "imm2", 
                  "dsp_p_en", "push_return"]
    STC_FIELDS = ["src_stval", "src_tval", "dest_stval", "op", "imm_stval", "imm_tval", 
                  "dsp_p_en", "push_return"]
    
    # DSP operating modes
    # Create a list of all possible operations able to be implemented in the slice
    # All constants come from Xilinx UG579
    DSPMode = namedtuple("DSPMode", ["w", "z", "y", "x", "alumode", "cin"])

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

                            # Addition is commutative, so sort the resulting expression
                            # by its terms, and include the carry input (which we'll
                            # choose to arbitrarily call J)
                            str_pieces = [w_str, z_str, y_str, x_str, cin_str]
                            str_pieces.sort(key=lambda s: s[1])
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

                            DSP_MODES[key] = DSPMode(w, z, y, x, alumode)

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
                                DSP_MODES[key] = DSPMode(0, z, y, x, alumode+inv_z)
    
    def __init__(self):
        # We'll start by making resource managers for the registers and DSP
        # slices. For both of them, we'll delegate the main Symbol methods
        # to the resource ID
        def resource_id_assign(resource_self, v, force=False):
            resource_self._resource_id.assign(v, force=force)
            
        def resource_id_assigned(resource_self):
            return resource_self._resource_id.assigned()
        
        def resource_id_value(resource_self):
            return resource_self._resource_id.value()
        
        def resource_id_value_type(resource_self):
            return resource_self._resource_id.value_type()
        
        # Begin register-specific methods
        
        def register_load(reg_self, value):
            compiled_value,resources = self.compile_arg(value)
            self.STP(src1=compiled_value, dest1=reg_self)
            for res in resources:
                res._released = True
                
            
        self.Register = ManagedResource(
            "Register", 
            (Symbol,), 
            {"assign": resource_id_assign,
             "assigned": resource_id_assigned, 
             "value": resource_id_value,
             "value_type": resource_id_value_type,
             "__setattr__": resource_setattr,
             "OPERATORS": ["eq", "ne", "gt", "lt", "ge", "le", 
                           "add", "radd", "iadd", "sub", "rsub", "isub", 
                           "and", "rand", "iand", "or", "ror", "ior", 
                           "mul", "rmul", "imul", # We can natively multiply by 2 or 3
                           "xor", "rxor", "ixor", "invert"]},
            instance_limit=Sequencer.NUM_REGISTERS)
        
        # Begin DSP-specific methods
        
        def dsp_load(dsp_self, value):
            compiled_value,resources = self.compile_arg(value)
            self.STP(src1=compiled_value, dest1=reg_self)
            for res in resources:
                res._released = True
        
        def dsp_configure(dsp_self, 
                       mode=0, 
                       rst_a=False, 
                       rst_b=False, 
                       rst_c=False, 
                       rst_p=False, 
                       dsp_data_dest="C", 
                       dsp_data_signed=True, 
                       dsp_cep=None):
            """
            Creates a 32-bit value to be written to the DSP configuration port.
            :param mode: Configuration fields for the OPMODE and ALUMODE ports of 
            the DSP slice.
            :type mode: :class:`Sequencer.DSPMode`
            :param rst_ab: If `True`, the RST pins of the A and B registers are
            pulsed when the configuration register is written.
            :type rst_ab: `bool`
            :param rst_c: If `True`, the RST pin of the C register is pulsed when
            the configuration register is written.
            :param rst_cin: If `True`, the RST pin of the CIN register is pulsed
            when the configuration register is written.
            :param rst_p: If `True`, the RST pin of the P register is pulsed when
            the configuration register is written.
            """
            opmode = (mode.w << 7) | (mode.z << 4) | (mode.y << 2) | mode.x
            
            if dsp_data_dest == "C" and dsp_data_signed:
                dsp_data_dest_bits = 0 | (not dsp_data_signed)
            elif dsp_data_dest == "AB":
                dsp_data_dest_bits = 2 | (not dsp_data_signed)
            else:
                raise ValueError(f"Invalid DSP data destination {dsp_data_dest}.")
                
            if not dsp_cep:
                dsp_cep_bits = 0
            elif dsp_cep == "pulse":
                dsp_cep_bits = 1
            elif dsp_cep == "set":
                dsp_cep_bits = 2
            elif dsp_cep == "reset":
                dsp_cep_bits = 3
            else:
                raise ValueError(f"Invalid DSP CEP setting {dsp_cep}.")
                
            # Constants below from the Acadia manual, as these are determined
            # by the logic
            return ((dsp_self.value() << 28) 
                    | (dsp_cep_bits << 21)
                    | (dsp_data_dest_bits << 18)
                    | (rst_p << 17)
                    | (rst_c << 16)
                    | (rst_b << 15)
                    | (rst_a << 14)
                    | (mode.cin << 13)
                    | (opmode << 4)
                    | mode.alumode)
        
        self.DSPSlice = ManagedResource("DSPSlice", 
                                        (Symbol,), 
                                        {"assign": resource_id_assign,
                                         "assigned": resource_id_assigned, 
                                         "value": resource_id_value,
                                         "value_type": resource_id_value_type,
                                         "config_value": dsp_config_value},
                                        instance_limit=Sequencer.NUM_DSP)
        
        self.bus = type("Bus", (), {})()
        self.PC = type("PC", (), {})()
        self.stack = type("Stack", (), {})()
        self.flags = type("Flags", (), {})()
        self.test_value = type("TestValue", (), {})()
    
    def is_argument(self, obj):
        """
        :return: `True` if a given object is a valid argument for assembly.
        :rtype: `bool`
        """
        return (Sequencer.is_numeric(obj)
                    or obj in [self.bus, self.PC, self.stack, self.flags, self.test_value]
                    or isinstance(obj, self.Register)
                    or isinstance(obj, self.DSPSlice)) 
    
    # Then, we want to implement the behavior where we can write values to
    # things with Python syntax
    def compile_arg(self, obj, dsp=None):
        """
        Compiles an object into an argument able to be directly assembled into
        a sequencer instruction. In some cases, a resource will need to be
        allocated to compute an argument; such resources will be returned along
        with the compiled argument.
        :param obj: Object to translate
        """
        if dsp is not None and not isinstance(dsp, self.DSPSlice):
            raise TypeError(f"Provided resource must be a DSPSlice; received {dsp}.")

        if self.is_argument(obj):
            return obj,[]

        # An Operation involving a resource; compile recursively
        # The if statements above along with the "getitem" Operation form
        # the bases cases for the recursion
        if isinstance(obj, Operation):
            if obj._op == "getitem":
                # If we're reading from the bus, we need to calculate and write
                # the address first
                if obj._args[0] == self.bus:
                    addr,addr_resources = self.compile_arg(obj._args[1], dsp=dsp)
                    self.STP(src1=addr, dest1=DEST_BUS_ADDR)
                    
                    # Release any resources needed to calculate the address
                    for resource in addr_resources:
                        resource._released = True
                    return self.bus,[]
                else:
                    raise TypeError("getitem Operations only supported for the 
                                    f" bus; received Operation {obj}")
               
            # Check that we have the right argument structure. invert will take
            # exactly one argument, otherwise we need exactly two. In both 
            # cases, there should be no keyword arguments since this was 
            # created by an operator (presumably)
            if (obj._op == "invert" 
                    and (len(obj._kwargs) > 0 or len(obj._args) != 1)):
                raise ValueError(f"invert Operations inside of arguments"
                                 f" should have two arguments and"
                                 f" no keywords; received {obj}.")
                
            elif len(obj._kwargs) > 0 or len(obj._args) != 2:
                raise ValueError(f"Operations inside of arguments without"
                                 f" getitem should have two arguments and"
                                 f" no keywords; received {obj}.")
            
            # At this point, we know we'll actually be performing some 
            # non-trivial mathematical operation on hardware on actual 
            # hardware resources (the case where the operation is between 
            # numerics is handled in is_argument).
            # If we were given a DSP slice, we have to decide which
            # argument to give it to when compiling, since either one could
            # require its own slice for temporary argument compilation
            # We'll (arbitrarily) choose to give it to arg1 if arg1 is an
            # Operation, and if it's not then we'll give it to arg2
            arg1_dsp = dsp if isinstance(obj._args[0], Operation) else None
            arg2_dsp = dsp if not isinstance(obj._args[0], Operation) else None
            
            arg1,arg1_resources = self.compile_arg(obj._args[0], dsp=arg1_dsp)
            if not self.is_argument(arg1):
                raise TypeError(f"Compilation returned object unsuitable for"
                                f" compilation: {arg1}")
                
            if obj._op != "invert":
                arg2,arg2_resources = self.compile_arg(obj._args[1], dsp=arg2_dsp)
                if not self.is_argument(arg2):
                    raise TypeError(f"Compilation returned object unsuitable for"
                                    f" compilation: {arg2}")
            else:
                arg2 = None
                arg2_resources = []
                
            resources = arg1_resources + arg2_resources
                
            # For certain operators we'll still need to return an Operation
            # with the operator information, but just with the arguments
            # properly compiled. We can return that here, and if it turns out
            # that this Operation was actually nested in another, then the 
            # outer call to compile_arg will throw an error (since Operation
            # will fail an is_argument check), but if we're in the outermost
            # call, then it'll just return
            if obj._op in ["eq", "ne", "gt", "lt", "ge", "le"]:
                return Operation(obj._op, arg1, arg2),resources
                
            # If we're not given a DSP slice to use and we didn't allocate one
            # when compiling arg1 and arg2, we must allocate one here
            # We will choose to use a DSP slice allocated during the 
            # compilation of arg2 before using that of arg1, because the one
            # allocated most recently will be able to have greater flexibility
            # in using previously-allocated slices for its PCIN input
            # While we choose this, construct the list of allocated resources
            # to be returned
            if dsp is not None:
                current_dsp = dsp
            elif arg2_resources and isinstance(arg2_resources[0], self.DSPSlice):
                current_dsp = arg2_resources[0]
            elif arg1_resources and isinstance(arg1_resources[0], self.DSPSlice):
                current_dsp = arg1_resources[0]
            else:
                current_dsp = self.DSPSlice()
                resources.append(current_dsp)
                
            # Now, determine the arguments to the slice's and how they must
            # physically enter. By default, they'll need to be loaded into the
            # external inputs exposed to the datapath
            # If the arguments are AB and C, we'll need separate instructions
            # to configure the DSP and load its inputs; otherwise, we can do 
            # this in one cycle
            arg1_input = "AB"
            arg2_input = "C"
            if isinstance(arg1, self.DSPSlice):
                # If we're operating on the current DSP, use the P register
                if arg1._resource_id.value == current_dsp._resource_id.value:
                    arg1_input = "P"
                    
                # If we're operating on the lower neighboring DSP, use the cascade input
                elif arg1._resource_id.value == current_dsp._resource_id.value-1:
                    arg1_input = "PCIN"
                    
            # For addition and subtraction, we can use the carry input
            elif isinstance(arg1, int) and abs(arg1) == 1 and obj._op in ["add", "sub"]:
                arg1_input = str(arg1)
                    
            if isinstance(arg2, self.DSPSlice):
                # If we're operating on the current DSP, use the P register
                if arg2._resource_id.value == current_dsp._resource_id.value:
                    arg2_input = "P"

                # If we're operating on the lower neighboring DSP, use the cascade input
                elif arg2._resource_id.value == current_dsp._resource_id.value-1:
                    arg2_input = "PCIN"
                    
            # For addition and subtraction, we can use the carry input
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
                
            elif obj._op == "mul" or obj._op == "rmul" or obj._op == "imul": 
                # One of the arguments must be an integer with a magnitude of
                # 2 or 3. Figure out which one this is
                if isinstance(arg1, int) and (abs(arg1) == 2 or abs(arg1) == 3):
                    sign = "-" if arg1 < 0 else "+"
                    dsp_mode_key = f"{sign}{arg2_input}"*abs(arg1)
                    if dsp_mode_key.startswith("+"):
                        dsp_mode_key = dsp_mode_key[1:]
                elif isinstance(arg2, int) and (abs(arg2) == 2 or abs(arg2) == 3):
                    sign = "-" if arg2 < 0 else "+"
                    dsp_mode_key = f"{sign}{arg1_input}"*abs(arg2)
                    if dsp_mode_key.startswith("+"):
                        dsp_mode_key = dsp_mode_key[1:]
                else:
                    raise ValueError(f"Only multiplication by integers with"
                                     f" magnitudes of 2 or 3 are supported;"
                                     f" received Operation {obj}.")
                    
            else:
                for base,key_format in [("add", "{}+{}"), 
                                        ("sub", "{}-{}"), 
                                        ("or", "{} OR {}"), 
                                        ("and", "{} AND {}"),
                                        ("xor", "{} XOR {}")]:
                # We should cover the augmenting operators here too, because
                # the handler will take care of the actual assignment part
                # but the name of the augmented operator will remain in the
                # Operation object
                if obj._op == base or obj._op == f"i{base}":
                    dsp_mode_key = key_format.format(arg1_input, arg2_input)
                elif obj._op == f"r{base}"
                    dsp_mode_key = key_format.format(arg2_input, arg1_input)
                    
            if not dsp_mode_key:
                raise ValueError(f"Unable to find a DSP configuration for"
                                 f" Operation {obj}.")
                
            # Finally, configure the slice
            # If we're still using AB, it means we must be using both external
            # inputs, so it's a two-cycle config
            if arg1_input == "AB":
                config_value = current_dsp.configure(dsp_data_dest="AB")
                self.STP(src1=SRC_IMM, dest1=DSP_CFG, imm1=config_value,
                         src2=arg1, dest2=DSP_DATA)
                
            # The next STP (or the only one, if arg1_input isn't AB)
            # will load C if necessary, and in either case CEP will be pulsed
            if arg2_input == "C":
                config_value = current_dsp.configure(dsp_data_dest="C", dsp_cep="pulse")
                self.STP(src1=SRC_IMM, dest1=DSP_CFG, imm1=config_value,
                         src2=arg2, dest2=DSP_DATA)    
            else:
                config_value = current+dsp.configure(dsp_cep="pulse")
                self.STP(src1=SRC_IMM, dest1=DSP_CFG, config_value)
            
            
            # The DSP slice we used will contain the answer at the end, so 
            # return it along with any resources allocated during compilation
            return current_dsp,resources

        raise TypeError(f"Unable to compile {obj} (type {type(obj)}).")
    
    @Processor.instruction()
    def STP(self, instruction_resource):
        if len(instruction["args"] != 0):
            raise ValueError(f"STP does not accept positional arguments;"
                             f" received {instruction['args']}")
        compiled_fields = {}
        for field in Sequencer.STP_FIELDS:
            field_value = instruction_resource["kwargs"].pop(field, 0)
            compiled_fields[field] = self.compile_arg()
    