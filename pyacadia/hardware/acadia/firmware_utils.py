"""
firmware.py
Software for generating firmware images and associated software support files for the Acadia quantum control system.
William Kalfus, Yale University
October 2022
"""
import os
import numpy as np

from ..assembler import Symbol

def connect_bd_net(f, pin1, pin2):
    f.write(f"connect_bd_net [get_bd_pins {pin1}] [get_bd_pins {pin2}]\n")
    
def connect_bd_intf_net(f, pin1, pin2):
    f.write(f"connect_bd_intf_net [get_bd_intf_pins {pin1}] [get_bd_intf_pins {pin2}]\n")
    
def create_concatenator(f, name, widths):
    tmp = f"create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 {name}\n"
    tmp += f"set_property -dict [list "
    for i,width in enumerate(widths):
        tmp +=  f"CONFIG.IN{i}_WIDTH.VALUE_SRC USER "
    tmp += f"] [get_bd_cells {name}]\n"
    
    tmp += f"set_property -dict [list CONFIG.NUM_PORTS {{{len(widths)}}} "
    for i,width in enumerate(widths):
        tmp += f"CONFIG.IN{i}_WIDTH {{{width}}} "
            
    tmp += f"] [get_bd_cells {name}]\n"
    
    f.write(tmp)
    
def create_slice(f, name, input_width, input_from, input_to):
    f.write(f"create_bd_cell -type ip -vlnv xilinx.com:ip:xlslice:1.0 {name}\n")
    f.write(f"set_property -dict [list CONFIG.DIN_WIDTH {{{input_width}}} CONFIG.DIN_TO {{{input_to}}} CONFIG.DIN_FROM {{{input_from}}} CONFIG.DOUT_WIDTH {{{input_from - input_to + 1}}}] [get_bd_cells {name}]\n")

def create_module(f, name, reference):
    f.write(f"create_bd_cell -type module -reference {reference} {name}\n")
    
def next_highest_power_of_2(num):
    # https://graphics.stanford.edu/~seander/bithacks.html#RoundUpPowerOf2
    n = np.uint32(num)
    n -= 1
    n |= n >> 1
    n |= n >> 2
    n |= n >> 4
    n |= n >> 8
    n |= n >> 16
    n += 1
    return n

class HDLModule(object):
    """
    An object representing a custom HDL module.
    """
    def __init__(self, module_name):
        self._module_name = module_name
        
    @property
    def module_name(self):
        return self._module_name
        
    def generate_hdl(self):
        """
        Generates an HDL file for the module.
        """
        pass

class BusDevice(Symbol):
    def __init__(self, name, size=0, word_bits=32, bus_bits=32, address=None):
        """
        A device which can be added to a memory bus.
        :param name: Name of the device to be added
        :type name: str
        :param size: Number of words needed in the address space of the bus.
        :type size: int, optional
        :param bus_bits: The number of bits in the bus interface
        :type bus_bits: int, optional
        :type parent_device: int, optional
        :param base_address: The base address of this decoder, from which the address of all its children will be determined and assigned.
        :type base_address: int, optional
        """
        self._name = name
        self._size = size
        self._word_bits = word_bits
        self._bus_bits = bus_bits
        
        Symbol.__init__(self, address)
        
    @property
    def name(self):
        """
        The name of the device.
        """
        return self._name
        
    @property
    def size(self):
        """
        The amount of space (in number of words) needed by this device on the bus.
        """
        if self._size == 0:
            raise ValueError("Object of zero size queried.")
            
        return self._size
    
    def words(self, word_bits):
        """
        The amount of words of a given bit size that this device requires
        """
        return self.size * self._word_bits / word_bits
    
    @property
    def word_bits(self):
        """
        The width of the data word
        """
        return self._word_bits
    
    @property
    def bus_bits(self):
        """
        The width of the bus address space
        """
        return self._bus_bits
    
    @property
    def size_bits(self):
        """
        The number of bits needed to encode the object size.
        """
        return round(np.log2(next_highest_power_of_2(self._size)))
    
    def assign(self):
        """
        Assign addresses of any slave modules, if applicable.
        """
        pass

    @property
    def address(self):
        return self.value
    
    @property
    def byte_address(self):
        return self.value * (self.word_bits // 8)

class BusRegisters(BusDevice, HDLModule):
    
    INPUT = 1
    OUTPUT = 2
    
    def __init__(self, name, regs, word_bits=32, bus_bits=32, pipeline_master=0, address=None):
        """
        A set of registers accessible on the bus, specified either by the size of the register file or by the register names themselves
        :param name: name of the register file
        :type name: str
        :param reg_names: List of register names. 
        :param base_address: The base address of this decoder, from which the address of all its children will be determined and assigned.
        :type base_address: int, optional
        """
        self._pipeline_master = pipeline_master
        self._regs = {}
        for (n, direction, pipeline) in regs:
            self._regs[n] = (Symbol(), direction, pipeline)
        
        BusDevice.__init__(self, name, len(self._regs), word_bits, bus_bits, address)
        HDLModule.__init__(self, name)
        
    @property
    def size(self):
        return len(self._regs)
    
    def __getitem__(self, key):
        """
        Return the Symbol associated with the register.
        """
        return self._regs[key][0]
    
    def items(self):
        return [(key,item[0]) for (key,item) in self._regs.items()]
    
    def keys(self):
        return self._regs.keys()
    
    def __iter__(self):
        return iter(self._regs.keys())
    
    def assign(self):
        """
        Assign registers to particular addresses.
        """       
        # Throw an error if a smarter strategy is needed
        if len(self._regs) > (2**self._bus_bits):
            raise ValueError(f"Too many devices on the bus to be allocated (attempted to allocate {num_ports} devices with a max size of {max_size}).")
    
        for i,(reg_name, (symbol, direction, pipeline)) in enumerate(self._regs.items()):
            # Assign the value of the underlying Symbols to be offset from the address of this BusRegisters object
            symbol.value = self.value + i
        
    def generate_hdl(self):
        if not self.assigned:
            raise ValueError("Device must be assigned before generating HDL.")
            
        num_ports = next_highest_power_of_2(self.size)
        
        # Throw an error if a smarter strategy is needed
        if num_ports > (2**self.bus_bits):
            raise ValueError(f"Too many devices on the bus to be allocated (attempted to allocate {num_ports} devices with a max size of {max_size}).")
            
        # Finally, write the HDL for the decoder
        hdl = f'library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;\nuse IEEE.NUMERIC_STD.ALL;\n\n'
        hdl += f'entity {self.name} is\n'
        hdl += f'    port (\n'
        hdl += f'        nrst : in std_logic;\n\n'
        hdl += f'        -- Slave interface\n'
        hdl += f'        master_bus_mosi : in  std_logic_vector({self.word_bits-1} downto 0);\n'
        hdl += f'        master_bus_miso : out std_logic_vector({self.word_bits-1} downto 0);\n'
        hdl += f'        master_bus_addr : in  std_logic_vector({round(np.log2(num_ports))-1} downto 0);\n'
        hdl += f'        master_bus_wr   : in  std_logic;\n'
        hdl += f'        master_bus_clk  : in  std_logic;\n'
        hdl += f'        master_bus_en   : in  std_logic;\n\n'
        
        for i,(reg_name, (symbol, direction, pipeline)) in enumerate(self._regs.items()):
            hdl += f'        -- {reg_name} interface (bus address 0x{symbol.value:08X})\n'
            if direction & BusRegisters.OUTPUT:
                hdl += f'        {reg_name}_mosi : out std_logic_vector({self.word_bits-1} downto 0);\n'
            if direction & BusRegisters.INPUT:
                hdl += f'        {reg_name}_miso : in  std_logic_vector({self.word_bits-1} downto 0);\n'
        
        hdl = hdl[:-2] + f"\n    );\n" # Get rid of the last semicolon
        hdl += f'end {self.name};\n\n'

        hdl += f'architecture rtl of {self.name} is\n\n'
        
        # Assign attributes
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO : STRING;\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_MODE : STRING;\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus ADDR";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_wr  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_clk : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus CLK";\n\n'
        
        master_bus_mosi = f'master_bus_mosi{("_" if self._pipeline_master > 0 else "") + "d"*self._pipeline_master}'
        master_bus_addr = f'master_bus_addr{("_" if self._pipeline_master > 0 else "") + "d"*self._pipeline_master}'
        master_bus_wr = f'master_bus_wr{("_" if self._pipeline_master > 0 else "") + "d"*self._pipeline_master}'
        master_bus_en = f'master_bus_en{("_" if self._pipeline_master > 0 else "") + "d"*self._pipeline_master}'
        
        if self._pipeline_master > 0:
            hdl += f'    signal master_bus_miso_int : std_logic_vector({self.word_bits-1} downto 0);\n'
            for p in range(self._pipeline_master):
                hdl += f'    signal master_bus_mosi_{"d"*(p+1)}    : std_logic_vector({self.word_bits-1} downto 0);\n'
                hdl += f'    signal master_bus_miso_int_{"d"*(p+1)} : std_logic_vector({self.word_bits-1} downto 0);\n'
                hdl += f'    signal master_bus_addr_{"d"*(p+1)}    : std_logic_vector({round(np.log2(num_ports))-1} downto 0);\n'
                hdl += f'    signal master_bus_wr_{"d"*(p+1)}      : std_logic;\n'
                hdl += f'    signal master_bus_en_{"d"*(p+1)}      : std_logic;\n\n'
        
        for i,(reg_name, (symbol, direction, pipeline)) in enumerate(self._regs.items()):
            if direction & BusRegisters.INPUT:
                for p in range(pipeline):
                    hdl += f'    signal {reg_name}_miso_{"d"*(p+1)}: std_logic_vector({self.word_bits-1} downto 0);\n'
            if direction & BusRegisters.OUTPUT:
                hdl += f'    signal {reg_name}_mosi_reg : std_logic_vector({self.word_bits-1} downto 0);\n'
                for p in range(pipeline):
                    hdl += f'    signal {reg_name}_mosi_reg_{"d"*(p+1)}: std_logic_vector({self.word_bits-1} downto 0);\n'
            hdl += f'\n'
        hdl += f'begin\n'
        
        # Pipeline interfaces as specified
        hdl += f'    pipeline_proc : process(master_bus_clk) begin\n'
        hdl += f'        if rising_edge(master_bus_clk) then\n'
        
        for p in range(self._pipeline_master):
            hdl += f'        master_bus_mosi_{"d"*(p+1)} <= master_bus_mosi{("_" if p > 0 else "") + "d"*p};\n'
            hdl += f'        master_bus_miso_int_{"d"*(p+1)} <= master_bus_miso_int{("_" if p > 0 else "") + "d"*p};\n'
            hdl += f'        master_bus_addr_{"d"*(p+1)} <= master_bus_addr{("_" if p > 0 else "") + "d"*p};\n'
            hdl += f'        master_bus_en_{"d"*(p+1)} <= master_bus_en{("_" if p > 0 else "") + "d"*p};\n'
            hdl += f'        master_bus_wr_{"d"*(p+1)} <= master_bus_wr{("_" if p > 0 else "") + "d"*p};\n'
        
        for i,(reg_name, (symbol, direction, pipeline)) in enumerate(self._regs.items()):
            if direction & BusRegisters.INPUT:
                for p in range(pipeline):
                    hdl += f'        {reg_name}_miso_{"d"*(p+1)} <= {reg_name}_miso{("_" if p > 0 else "") + "d"*p};\n'
            if direction & BusRegisters.OUTPUT:
                for p in range(pipeline):
                    hdl += f'        {reg_name}_mosi_reg_{"d"*(p+1)} <= {reg_name}_mosi_reg{("_" if p > 0 else "") + "d"*p};\n'
            hdl += f'\n'
            
        hdl += f'        end if;\n'    
        hdl += f'    end process pipeline_proc;\n\n'
        
        if self._pipeline_master > 0:
            hdl += f'    master_bus_miso <= master_bus_miso_int_{"d"*self._pipeline_master};\n\n'
        
        for i,(reg_name, (symbol, direction, pipeline)) in enumerate(self._regs.items()):
            if direction & BusRegisters.OUTPUT:
                hdl += f'    {reg_name}_mosi <= {reg_name}_mosi_reg{("_" if pipeline > 0 else "") + "d"*pipeline};\n'
        hdl += f'\n'
        
        # Multiplex the master input
        hdl += f'    master_bus_miso_int   <= '
        for i,(reg_name, (symbol, direction, pipeline)) in enumerate(self._regs.items()):
            if direction & BusRegisters.INPUT:
                hdl += f'                  {reg_name}_miso{("_" if pipeline > 0 else "") + "d"*pipeline} when to_integer(unsigned({master_bus_addr}({self.size_bits-1} downto 0))) = {i} else \n'
        hdl += f'                  (others => \'0\');\n\n'
        
        # Connect all the register outputs
        hdl += f'    {self.name}_regs_proc : process(master_bus_clk) begin\n'
        hdl += f'        if rising_edge(master_bus_clk) then\n'
        
        for i,(reg_name, (symbol, direction, pipeline)) in enumerate(self._regs.items()):
            if direction & BusRegisters.OUTPUT:
                hdl += f'            if(nrst = \'0\') then\n'
                hdl += f'                {reg_name}_mosi_reg <= (others => \'0\'); -- bus address 0x{symbol.value:08X}\n'
                hdl += f'            elsif({master_bus_wr} = \'1\' and {master_bus_en} = \'1\' and to_integer(unsigned({master_bus_addr}({self.size_bits-1} downto 0))) = {i}) then\n'
                hdl += f'                {reg_name}_mosi_reg <= {master_bus_mosi}; -- bus address 0x{symbol.value:08X}\n'
                hdl += f'            end if;\n'
            
        hdl += f'        end if;\n'    
        hdl += f'    end process {self.name}_regs_proc;\n\n'
        hdl += f'end rtl;\n\n'
        
        return hdl
    
class BusDecoder(BusDevice, HDLModule):
    def __init__(self, name, word_bits=32, bus_bits=32, pipeline_miso=False, address=None):
        """
        Generate an HDL file for a memory bus decoder.
        :param name: name of the decoder to generate
        :type name: str
        :param word_bits: number of bits in the data word
        :type word_bits: int, optional
        :param bus_bits: number of bits in the address word
        :type bus_bits: int, optional
        :param pipeline_miso: indicates whether to pipeline the signal driving the master data input
        :type pipeline_miso: bool, optional
        :param base_address: The base address of this decoder, from which the address of all its children will be determined and assigned.
        :type base_address: int, optional
        """
        self._name = name
        self._bus_objects = []
        self._pipeline_miso = pipeline_miso
            
        BusDevice.__init__(self, name, 0, word_bits, bus_bits, address)
        HDLModule.__init__(self, name)
        
    def add(self, obj, pipeline=False):
        if isinstance(obj, BusDevice):
            if obj.word_bits != self.word_bits:
                raise ValueError("Connected BusDevices and BusDecoders must have the same number of bits in a data word.")
            self._bus_objects.append((obj, pipeline))
        else:
            raise TypeError("Can only add BusDevices to a BusDecoder.")
            
    def max_slave_size(self):
        return next_highest_power_of_2(np.array(list(map(lambda x: x[0].size, self._bus_objects))).max())
    
    def items(self):
        return [obj for (obj,_) in self._bus_objects]
    
    def __iter__(self):
        return iter([obj for (obj,_) in self._bus_objects])
    
    def keys(self):
        return [obj.name for (obj,_) in self._bus_objects]
    
    def __getitem__(self, key):
        """
        Return the Symbol associated with the object.
        """
        for (obj, pipeline) in self._bus_objects:
            if obj.name == key:
                return obj
        
        raise KeyError(f"No BusDevice found attached to this BusDecoder with name {key}.")
        
    @property
    def size(self):
        return self.max_slave_size()*next_highest_power_of_2(len(self._bus_objects))
        
    def assign(self):
        """
        Assign attached devices to particular addresses.
        
        There are multiple strategies we could use to allocate bus space with varying levels of efficiency.
        Since the bus is single-cycle it's beneficial to have the decoding logic 
        be as minimal as possible so as to reduce routing delays, 
        so we'll choose a strategy that allows us to make the smallest decoder.
        This is achieved by making a decoder that just has one output per address region,
        and if all the regions are identical and next to one another, then we only need to 
        decode as many address bits as are needed to store the number of regions
        Of course, when there are large discrepancies in the sizes of the regions
        it will not be very efficient in terms of address space utilization,
        but as long as we don't run out of space then it doesn't really matter
        
        We could imagine that this would really only become a problem when we have some large memories 
        attached to the bus along with a bunch of small things (e.g, registers or DMAs). 
        As a future upgrade, we could perform one round of allocation on all the
        big things and make a bunch of large regions, then repeat within a region for the smaller things.
        
        We'll also assume that we can ignore the bits above those necessary for decoding,
        which means the address space will be inherently tiled across the upper bits
        For example, if 1K of address space is used in total, then writing to location 1024 + x will have the 
        same effect as writing to x because all bits above the 10th are ignored.
        """
        max_size = self.max_slave_size()
        num_ports = next_highest_power_of_2(len(self._bus_objects))
        
        # Throw an error if a smarter strategy is needed
        if num_ports*max_size > (2**self._bus_bits):
            raise ValueError(f"Too many devices on the bus to be allocated (attempted to allocate {num_ports} devices with a max size of {max_size}).")
            
        for i,(obj,pipeline) in enumerate(self._bus_objects):
            # Assign the value of the underlying Symbol
            obj.value = self.value + i*max_size 
            obj.assign()
                
    def generate_hdl(self):
        if not self.assigned:
            raise ValueError("Device must be assigned before generating HDL.")
        
        max_size = self.max_slave_size()
        num_ports = next_highest_power_of_2(len(self._bus_objects))
        
        # We now have all the information we need to figure out which bits we can ignore.
        # The max region size tells us how many lower bits we can ignore.
        # We then need enough bits to decode the number of regions that we have
        # We can then ignore all the bits above that
        decoder_inputs = round(np.log2(num_ports)) # We've guaranteed these numbers to be powers of 2 above
        low_address_bit = round(np.log2(max_size))
        
        # Finally, write the HDL for the decoder
        hdl = f'library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;\nuse IEEE.NUMERIC_STD.ALL;\n\n'
        hdl += f'entity {self._name} is\n'
        hdl += f'    port (\n'
        hdl += f'        -- Slave interface\n'
        hdl += f'        master_bus_mosi : in  std_logic_vector({self.word_bits-1} downto 0);\n'
        hdl += f'        master_bus_miso : out std_logic_vector({self.word_bits-1} downto 0);\n'
        hdl += f'        master_bus_addr : in  std_logic_vector({round(np.log2(self.size))-1} downto 0);\n'
        hdl += f'        master_bus_wr   : in  std_logic;\n'
        hdl += f'        master_bus_en   : in  std_logic;\n'
        hdl += f'        master_bus_clk  : in  std_logic;\n\n'
        
        for i,(obj,pipeline) in enumerate(self._bus_objects):
            hdl += f'        -- {obj.name} interface (local bus address 0x{obj.value-self.value:08X}), (global bus address 0x{obj.value:08X})\n'
            hdl += f'        {obj.name}_mosi : out std_logic_vector({self.word_bits-1} downto 0);\n'
            hdl += f'        {obj.name}_miso : in  std_logic_vector({self.word_bits-1} downto 0);\n'
            hdl += f'        {obj.name}_addr : out std_logic_vector({low_address_bit-1} downto 0);\n'
            hdl += f'        {obj.name}_wr   : out std_logic;\n'
            hdl += f'        {obj.name}_en   : out std_logic;\n'
            hdl += f'        {obj.name}_clk  : out std_logic;\n\n'
            
        hdl = hdl[:-3] + f"\n    );\n" # Get rid of the last semicolon
        hdl += f'end {self._name};\n\n'

        hdl += f'architecture rtl of {self._name} is\n\n'
        
        # Assign attributes
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO : STRING;\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_MODE : STRING;\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus ADDR";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_wr  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_clk : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus CLK";\n\n'
        
        for (obj,pipeline) in self._bus_objects:
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {obj.name}_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 {obj.name} DIN";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {obj.name}_miso: SIGNAL is "xilinx.com:interface:bram:1.0 {obj.name} DOUT";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {obj.name}_addr: SIGNAL is "xilinx.com:interface:bram:1.0 {obj.name} ADDR";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {obj.name}_wr  : SIGNAL is "xilinx.com:interface:bram:1.0 {obj.name} WE";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {obj.name}_en  : SIGNAL is "xilinx.com:interface:bram:1.0 {obj.name} EN";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {obj.name}_clk : SIGNAL is "xilinx.com:interface:bram:1.0 {obj.name} CLK";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_MODE of {obj.name}_mosi: SIGNAL is "Master";\n\n'
            
        hdl += f'begin\n'
        region_bits = f'{low_address_bit + decoder_inputs - 1} downto {low_address_bit}'

        # Multiplex the master inputs
        if self._pipeline_miso:
            hdl += f'    master_bus_miso_proc: process(master_bus_clk) begin\n'
            hdl += f'        if rising_edge(master_bus_clk) then\n'
            hdl += f'            case master_bus_addr({region_bits}) is\n'
            for i,(obj,pipeline) in enumerate(self._bus_objects):
                hdl += f'                when "{f"{i:b}".zfill(decoder_inputs)}" => master_bus_miso <= {obj.name}_miso;\n' 
            hdl += f'                when others => master_bus_miso <= (others => \'0\');\n' 
            hdl += f'            end case;\n'
            hdl += f'        end if;\n'
            hdl += f'    end process master_bus_miso_proc;\n'
        else:
            hdl += f'    master_bus_miso   <= '
            for i,(obj,pipeline) in enumerate(self._bus_objects):
                hdl += f'                  {obj.name}_miso when to_integer(unsigned(master_bus_addr({region_bits}))) = {i} else \n'

            hdl += f'                  (others => \'0\');\n\n'
        
        # Connect all the master output ports
        for i,(obj, pipeline) in enumerate(self._bus_objects):
            hdl += f'    -- {obj.name} interface (local bus address 0x{obj.value-self.value:08X}), (global bus address 0x{obj.value:08X})\n'         
            hdl += f'    {obj.name}_clk  <= master_bus_clk;\n\n'
            if pipeline:
                hdl += f'    {obj.name}_proc: process(master_bus_clk) begin\n'
                hdl += f'        if rising_edge(master_bus_clk) then\n'
                hdl += f'            {obj.name}_mosi <= master_bus_mosi;\n'
                hdl += f'            {obj.name}_addr <= master_bus_addr({low_address_bit-1} downto 0);\n'
                hdl += f'            {obj.name}_wr   <= master_bus_wr;\n'
                hdl += f'            if (master_bus_addr({region_bits}) = "{f"{i:b}".zfill(decoder_inputs)}") then \n'
                hdl += f'                {obj.name}_en   <= \'1\';\n'
                hdl += f'            else\n'
                hdl += f'                {obj.name}_en   <= \'0\';\n'
                hdl += f'            end if;\n'
                hdl += f'        end if;\n'
                hdl += f'    end process {obj.name}_proc;\n'
            else:
                hdl += f'    {obj.name}_mosi <= master_bus_mosi;\n'
                hdl += f'    {obj.name}_addr <= master_bus_addr({low_address_bit-1} downto 0);\n'
                hdl += f'    {obj.name}_wr   <= master_bus_wr;\n'
                hdl += f'    {obj.name}_en   <= master_bus_en when to_integer(unsigned(master_bus_addr({region_bits}))) = {i} else \'0\';\n'
            

        hdl += f'end rtl;\n'
        
        return hdl
    
class BusDataMoverController(BusDevice, HDLModule):
        
    def __init__(self, name, datamovers, addr_bits, word_bits=32, bus_bits=32, address=None):
        """
        A bus interface for access to the command and status ports of an array of AXI DataMovers.
        A small number of registers are also provided for interacting with a given DataMover, where the base address of the 
        registers for that DataMover is the base address of this device, plus 4 times the DataMover number.
        The registers are:
            0: CMD_ADDR/STS
                Writing to this register issues a command to the DataMover command FIFO whose 
                address field is populated with the data written to this register. 
                The values of the other fields are derived from prior writes to other registers (see below).
                Reading this register returns a status word from the status FIFO and pops it.
            1: CMD_BTT/STS_VLD
                This register stores the number of bytes for the DataMover to transfer when its next command is issued.
                Reading this register returns a value with one bit per DataMover. 
                A bit is set when the corresponding DataMover when sts_tvalid signal is high.
            2: CMD_MISC/CMD_ACK
                This register stores additional miscellaneous bits needed for a DataMover command:
                    0     : TYPE
                    1     : EOF
                    5-2   : TAG
                    9-6   : xCACHE
                    13-10 : xUSER
                    ADDR_BITS+14 - 14 : ADDR high bits
                Reading this register returns a value with one bit per DataMover. This bit is set once the DataMover 
                command interface sets TREADY after this module sets TVALID, indicating that it accepted the command 
                driven by the module (this includes when TREADY is already set when the command is issued).
            3: ACK_RST/DM_ERR
                Writing a value to this register with a given bit set clears CMD_ACK signals for the DataMover
                corresponding to that bit position. Multiple bits may be set to clear multiple registers at once.
                The value returned by this register contains one bit per DataMover, where each bit is directly 
                connected to the error signal for the DataMover.
                
        :param datamovers: A list of strings containing the names of the DataMovers
        """
        self._datamovers = datamovers
        self._addr_bits = addr_bits
        
        BusDevice.__init__(self, name, self.size, word_bits, bus_bits, address)
        HDLModule.__init__(self, name)
        
    @property
    def size(self):
        # 4 registers per datamover
        return 4*len(self._datamovers)
    
    def __getitem__(self, key):
        """
        Return the Symbol associated with the registers for a particular datamover, as indexed by name or number.
        :param key: a number or string indexing the datamover
        :type key: int or str
        """
        if isinstance(key, int):
            return self + 4*key
        elif isinstance(key, str):
            return self + 4*self.datamovers.index(key)
        else:
            raise TypeError(f"Incompatible type for key {key}")
        
    def generate_hdl(self):
        if not self.assigned:
            raise ValueError("Device must be assigned before generating HDL.")
            
        num_ports = next_highest_power_of_2(self.size)
        bus_addr_bits = round(np.log2(num_ports))
        
        # Throw an error if a smarter strategy is needed
        if num_ports > (2**self.bus_bits):
            raise ValueError(f"Too many devices on the bus to be allocated (attempted to allocate {num_ports} devices with a max size of {max_size}).")
            
        # Finally, write the HDL for the decoder
        hdl = f'library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;\nuse IEEE.NUMERIC_STD.ALL;\n\n'
        hdl += f'entity {self.name} is\n'
        hdl += f'    port (\n'
        hdl += f'        clk  : in std_logic;\n'
        hdl += f'        nrst : in std_logic;\n\n'
        hdl += f'        -- Slave interface\n'
        hdl += f'        master_bus_mosi : in  std_logic_vector({self.word_bits-1} downto 0);\n'
        hdl += f'        master_bus_miso : out std_logic_vector({self.word_bits-1} downto 0);\n'
        hdl += f'        master_bus_addr : in  std_logic_vector({bus_addr_bits-1} downto 0);\n'
        hdl += f'        master_bus_wr   : in  std_logic;\n'
        hdl += f'        master_bus_en   : in  std_logic;\n\n'
        
        for datamover in self._datamovers:
            hdl += f'        -- {datamover} interface\n'
            hdl += f'        {datamover}_err        : in  std_logic;\n'
            hdl += f'        {datamover}_cmd_tdata  : out std_logic_vector(87 downto 0);\n'
            hdl += f'        {datamover}_cmd_tvalid : out std_logic;\n'
            hdl += f'        {datamover}_cmd_tready : in  std_logic;\n'
            
            hdl += f'        {datamover}_sts_tdata  : in  std_logic_vector(31 downto 0);\n'
            hdl += f'        {datamover}_sts_tvalid : in  std_logic;\n'
            hdl += f'        {datamover}_sts_tready : out std_logic;\n\n'
            

        hdl = hdl[:-3] + f"\n    );\n" # Get rid of the last semicolon
        hdl += f'end {self.name};\n\n'

        hdl += f'architecture rtl of {self.name} is\n\n'
        
        # Assign attributes
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO      : STRING;\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_MODE      : STRING;\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;\n\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus ADDR";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_wr  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";\n\n'
        
        for datamover in self._datamovers:
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_cmd_tdata  : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_cmd TDATA";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_cmd_tvalid : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_cmd TVALID";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_cmd_tready : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_cmd TREADY";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_MODE of {datamover}_cmd_tdata : SIGNAL is "Master";\n\n'
            
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_sts_tdata  : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_sts TDATA";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_sts_tvalid : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_sts TVALID";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_sts_tready : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_sts TREADY";\n\n'
            
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of clk: SIGNAL is "xilinx.com:signal:clock:1.0 clk clk";\n'
        bus_names = [s+f"_{d}" for s in self._datamovers for d in ["cmd","sts"]]
        hdl += f'    ATTRIBUTE X_INTERFACE_PARAMETER of clk: SIGNAL is "ASSOCIATED_BUSIF {":".join(bus_names)}";\n'
            
        hdl += f'    signal dm_err     : std_logic_vector(31 downto 0);\n'
        hdl += f'    signal dm_sts_vld : std_logic_vector(31 downto 0);\n'
        hdl += f'    signal dm_cmd_ack : std_logic_vector(31 downto 0);\n\n'
        hdl += f'    signal dm_ack_rst : std_logic_vector(31 downto 0);\n\n'
            
        for datamover in self._datamovers:
            hdl += f'    signal {datamover}_cmd_waiting : std_logic;\n\n'
            hdl += f'    signal {datamover}_cmd_btt     : std_logic_vector(22 downto 0);\n'
            hdl += f'    signal {datamover}_cmd_misc    : std_logic_vector({self._addr_bits-32+14-1} downto 0);\n\n'
        
        hdl += f'begin\n\n'
        
        hdl += f'    wr_proc: process(clk) begin\n'
        hdl += f'        if rising_edge(clk) then\n'
        hdl += f'            if (nrst = \'0\') then\n'
        hdl += f'                dm_cmd_ack <= (others => \'0\');\n'
        hdl += f'                dm_ack_rst <= (others => \'0\');\n'
        
        for i,datamover in enumerate(self._datamovers):    
            hdl += f'                {datamover}_cmd_tdata   <= (others => \'0\');\n'
            hdl += f'                {datamover}_cmd_waiting <= \'0\';\n'
            hdl += f'                {datamover}_cmd_btt     <= (others => \'0\');\n'
            hdl += f'                {datamover}_cmd_misc    <= (others => \'0\');\n'
        
        hdl += f'            elsif (master_bus_en = \'1\' and master_bus_wr = \'1\') then\n'
        hdl += f'                case master_bus_addr is\n'
        
        for i,datamover in enumerate(self._datamovers):    
            hdl += f'                    when "{f"{(i*4):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        {datamover}_cmd_tdata  <= {datamover}_cmd_misc(13 downto 6) & "0000" & {datamover}_cmd_misc(5 downto 2) & {datamover}_cmd_misc({self._addr_bits-32+14-1} downto 14) & master_bus_mosi & "0" & {datamover}_cmd_misc(1) & "000000" & {datamover}_cmd_misc(0) & {datamover}_cmd_btt;\n'
            hdl += f'                        {datamover}_cmd_waiting <= \'1\';\n'
            hdl += f'                        dm_ack_rst <= (others => \'0\');\n'
            hdl += f'                    when "{f"{(i*4 + 1):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        {datamover}_cmd_btt  <=  master_bus_mosi(22 downto 0);\n'
            hdl += f'                        dm_ack_rst <= (others => \'0\');\n'
            hdl += f'                    when "{f"{(i*4 + 2):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        {datamover}_cmd_misc <=  master_bus_mosi({self._addr_bits-32+14-1} downto 0);\n'
            hdl += f'                        dm_ack_rst <= (others => \'0\');\n'
            hdl += f'                    when "{f"{(i*4 + 3):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        dm_ack_rst <= master_bus_mosi;\n'
        hdl += f'                    when others =>\n'
        hdl += f'                        dm_ack_rst <= (others => \'0\');\n'
        hdl += f'                end case;\n'
        hdl += f'            else\n'
        hdl += f'                -- Clear the waiting signals if the cmd FIFO is ready\n'
        
        for i,datamover in enumerate(self._datamovers):  
            hdl += f'                if({datamover}_cmd_tready = \'1\') then\n'
            hdl += f'                    {datamover}_cmd_waiting <= \'0\';\n'
            hdl += f'                end if;\n\n'
        
        hdl += f'                -- Also clear dm_ack_rst, since it should only be high for one cycle\n'
        hdl += f'                dm_ack_rst <= (others => \'0\');\n'
        hdl += f'            end if;\n'
        hdl += f'        end if;\n'
        hdl += f'    end process wr_proc;\n\n'
        
        hdl += f'    -- Connect the cmd_tvalid signals to the waiting signal\n'
        for i,datamover in enumerate(self._datamovers):  
            hdl += f'    {datamover}_cmd_tvalid <= {datamover}_cmd_waiting;\n'
        hdl += f'    \n'
        
        hdl += f'    dm_cmd_ack_proc: process(clk) begin\n'
        hdl += f'        if rising_edge(clk) then\n'
        hdl += f'            if (nrst = \'0\') then\n'
        hdl += f'                dm_cmd_ack <= (others => \'0\');\n'
        hdl += f'            else\n'
        
        for i,datamover in enumerate(self._datamovers):  
            hdl += f'                if({datamover}_cmd_waiting = \'1\' and {datamover}_cmd_tready = \'1\') then\n'
            hdl += f'                    dm_cmd_ack({i}) <= \'1\';\n'
            hdl += f'                elsif(dm_ack_rst({i}) = \'1\') then\n'
            hdl += f'                    dm_cmd_ack({i}) <= \'0\';\n'
            hdl += f'                end if;\n\n'
        
        hdl += f'            end if;\n'
        hdl += f'        end if;\n'
        hdl += f'    end process dm_cmd_ack_proc;\n\n'
        
        
        hdl += f'    -- Combine the DataMover status valid signals into one vector\n'
        for i,datamover in enumerate(self._datamovers):
            hdl += f'    dm_sts_vld({i}) <= {datamover}_sts_tvalid;\n'
        hdl += f'    dm_sts_vld(31 downto {len(self._datamovers)}) <= (others => \'0\');\n\n'
        
        hdl += f'    -- Combine the DataMover error signals into one vector\n'
        for i,datamover in enumerate(self._datamovers):
            hdl += f'    dm_err({i}) <= {datamover}_err;\n'
        hdl += f'    dm_err(31 downto {len(self._datamovers)}) <= (others => \'0\');\n\n'
        
        hdl += f'    rd_proc: process(clk) begin\n'
        hdl += f'        if rising_edge(clk) then\n'
        hdl += f'            if (master_bus_en = \'1\' and master_bus_wr = \'0\') then\n'
        hdl += f'                case master_bus_addr is\n'
        
        for i,datamover in enumerate(self._datamovers):    
            hdl += f'                    when "{f"{(i*4):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        master_bus_miso <= {datamover}_sts_tdata;\n'
            hdl += f'                        {datamover}_sts_tready <= \'1\';\n'
            hdl += f'                    when "{f"{(i*4 + 1):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        master_bus_miso <= dm_sts_vld;\n'
            hdl += f'                        {datamover}_sts_tready <= \'0\';\n'
            hdl += f'                    when "{f"{(i*4 + 2):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        master_bus_miso <= dm_cmd_ack;\n'
            hdl += f'                        {datamover}_sts_tready <= \'0\';\n'
            hdl += f'                    when "{f"{(i*4 + 3):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        master_bus_miso <= dm_err;\n'
            hdl += f'                        {datamover}_sts_tready <= \'0\';\n'
            
        hdl += f'                    when others =>\n'
        
        for i,datamover in enumerate(self._datamovers): 
            hdl += f'                        {datamover}_sts_tready <= \'0\';\n'
            
        hdl += f'                end case;\n'
        hdl += f'            else\n'
        hdl += f'                -- Clear the signals that pop status words from the status FIFOs\n'
        for i,datamover in enumerate(self._datamovers):    
            hdl += f'                {datamover}_sts_tready <= \'0\';\n'
        hdl += f'            end if;\n'
        hdl += f'        end if;\n'
        hdl += f'    end process rd_proc;\n\n'
        
        
        hdl += f'end rtl;\n\n'
        
        return hdl

class AcadiaFirmware(object):
    
    def __init__(self, project_dir="/tmp"):
        """
        Initializes the object with a path to a temporary directory for building the firmware image.
        """
        self._modules = []
        self._project_dir = project_dir
        self._hdl_filename = None
        self._project_tcl_filename = None
        self._hedgehog_tcl_filename = None
        
        if not os.path.exists(project_dir):
            os.mkdir(project_dir)
            
    def items(self):
        return self._modules
    
    def __iter__(self):
        return iter(self.keys())
    
    def keys(self):
        return [m.name for m in self._modules]
            
    def __getitem__(self, key):
        for m in self._modules:
            if m.name == key:
                return m
            
        raise KeyError(f"No module found in AcadiaFirmware object with name {key}.")
            
    def add(self, value):
        """Adds an HDL module to the firmware image.
        """
        if not isinstance(value, HDLModule):
            raise TypeError("Only HDLModules can be added to the firmware.")
            
        self._modules.append(value)
        
    def write_project_tcl(self, filename="make_project.tcl"):
        """Writes a TCL script to create a Vivado project in the project directory.
        Child classes should override this function to implement unique functionality.
        :param filename: The name of the file in the project directory in which to write the file.
        :type filename: str, optional
        """
        self._project_tcl_filename = os.path.join(self._project_dir, filename)
        raise NotImplementedError("TODO: make the project base TCL script")
            
    def write_hdl(self, filename="python_modules.vhd"):
        """Writes a VHDL file containing the address decoding for the HEDGEHOG bus.
        Child classes should override this function to add custom HDL, if not included in the initializer.
        :param filename: The name of the file in the project directory in which to write the file.
        :type filename: str, optional
        """
        self._hdl_filename = os.path.join(self._project_dir, filename)
        
        with open(self._hdl_filename, "w") as f:
            for module in self._modules:
                f.write(module.generate_hdl() + '\n')
    
    def write_hedgehog_tcl(self, filename="hedgehog.tcl"):
        """Writes a TCL script to populate the HEDGEHOG logic in the standard image.
        Child classes should override this function to implement unique functionality.
        :param filename: The name of the file in the project directory in which to write the file.
        :type filename: str, optional
        """
        self._hedgehog_tcl_filename = os.path.join(self._project_dir, filename)
        
    
    
    
        