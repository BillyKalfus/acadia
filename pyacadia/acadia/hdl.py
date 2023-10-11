__all__ = ["HDLModule", "BusDevice", "BusDataport", "BusDecoder", "BusDatamoverController"]

import os

from .compiler import Symbol
from .utils import next_highest_power_of_2

# TCL utility functions
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
    
def create_ip(f, name, vlnv):
    f.write(f"create_bd_cell -type ip -vlnv {vlnv} {name}\n")
    
def set_property(f, name, properties, property_prefix="CONFIG.", property_suffix="", value_prefix="{", value_suffix="}"):
    tmp = "set_property -dict [list "
    
    if isinstance(properties, dict):
        tmp += ' '.join(f"{property_prefix}{k}{property_suffix} {value_prefix}{str(v).lower() if isinstance(v, bool) else v}{value_suffix}" for k,v in properties.items())
    elif isinstance(properties, str):
        tmp += properties
    else:
        raise TypeError("Unrecognized type for properties.")
        
    tmp += f"] [get_bd_cells {name}]\n"
    f.write(tmp)
    
def assign_bd_address(f, target_address_space, addr_seg, offset=None, range=None, force=True):
    tmp = "assign_bd_address "
    if offset is not None:
        tmp += f"-offset 0x{offset:010X} "
    if range is not None:
        tmp += f"-range {range} "
        
    tmp += f" -target_address_space {target_address_space} [get_bd_addr_segs {addr_seg}] "
    
    if force:
        tmp += "-force "
        
    tmp += "\n"
    
    f.write(tmp)
    
def exclude_bd_addr_seg(f, target_address_space, addr_seg):
    f.write(f"exclude_bd_addr_seg [get_bd_addr_segs {addr_seg}] -target_address_space [get_bd_addr_spaces {target_address_space}]\n")

class HDLModule:
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

class BusDevice:
    def __init__(self, name, size=0, bus_data_bits=32, bus_addr_bits=32):
        """
        A device which can be added to a memory bus.

        :param name: Name of the device to be added
        :type name: str
        :param size: Number of words needed in the address space of the bus.
        :type size: int, optional
        :param bus_data_bits: Number of bits in a data word, equal to the width of the data bus
        :type bus_data_bits: int, optional
        :param bus_addr_bits: The number of bits in the bus interface
        :type bus_addr_bits: int, optional
        :param address: The address of the device, whose interpretation is left to be defined by child classes
        :type address: int, optional
        """

        self._name = name
        self._size = size
        self._bus_data_bits = bus_data_bits
        self._bus_addr_bits = bus_addr_bits
        
        self._address = Symbol(value_type=int)
        
    def assign_address(self, value):
        """
        Assign the address of the device.

        :param value: Address to assign
        :type value: int
        """

        self._address.assign(value)
        
    def address_assigned(self):
        return self._address.assigned()
        
    def address(self):
        return self._address
        
    @property
    def name(self):
        """
        :return: The name of the device.
        :rtype: str
        """

        return self._name
        
    @property
    def size(self):
        """
        :return: The amount of space (in number of words) needed by this device on the bus.
        :rtype: int
        :raises: :class:`ValueError` when called on an object of zero size, as this generally indicates an instantiation error
        """

        if self._size == 0:
            raise ValueError("Object of zero size queried.")
            
        return self._size
    
    def words(self, bus_data_bits):
        """
        :return: The equivalent number of words required by this device for a given word width
        :rtype: int
        """

        return self.size * self._bus_data_bits / bus_data_bits
    
    @property
    def bus_data_bits(self):
        """
        :return: The width of the data word
        :rtype: int
        """

        return self._bus_data_bits
    
    @property
    def bus_addr_bits(self):
        """
        :return: The width of the bus address space
        :rtype: int
        """

        return self._bus_addr_bits
    
class BusDataport(BusDevice, HDLModule):
    """
    A module to split the data signals of a memory bus port. Optionally,
    the output signals may be gated by the memory enable signal to either 
    be reset when not enabled, or latched when not written.
    """
    
    INPUT = "in"
    OUTPUT = "out"
    GATE_RESET = 1
    GATE_REGCE = 2
    
    def __init__(self, name, ports, bus_data_bits=32, bus_addr_bits=32):
        """
        :param name: name of the module
        :type name: str
        :param ports: List of ports 
        :type ports: ``list`` of ``dict``, where each element specifies a port. 
        Valid keys are: "name", "from", "to", "direction", "gate", "pipeline"
        """
        self._ports = {}
        self._max_write_delay = 0
        
        self._used_input_bits = 0
        
        for idx,port in enumerate(ports):
            # Load keywords for each port and assign default values if necessary
            port_name = port.pop("name", f"{name}{idx}")
            port_offset = port.pop("offset", 0)
            port_width = port.pop("width", bus_data_bits)
            port_direction = port.pop("direction", BusDataport.INPUT)
            port_gate = port.pop("gate", None)
            port_pipeline = port.pop("pipeline", 0)
            port_mask = (2**port_width - 1) << port_offset
            
            # There should be no keys left, throw an error if there are
            if len(port) != 0:
                raise KeyError(f"Unrecognized data port keys: {port}")
                
            # Keep track of whether we need to make a delayed write signal for pipelined gated signals
            if (port_gate is not None) and port_pipeline > self._max_write_delay:
                self._max_write_delay = port_pipeline
             
            # Update the mask that keeps track of used inputs, so that we can later
            # set all unused bits to a constant
            if port_direction == BusDataport.INPUT:
                self._used_input_bits |= port_mask
            
            self._ports[port_name] = {"width": port_width, 
                                      "offset": port_offset, 
                                      "direction": port_direction, 
                                      "gate": port_gate, 
                                      "pipeline": port_pipeline,
                                      "mask": port_mask}
        
        BusDevice.__init__(self, name, 1, bus_data_bits, bus_addr_bits)
        HDLModule.__init__(self, name)
        
    @property
    def size(self):
        return len(self._ports)
    
    def __getitem__(self, key):
        return self._ports[key]
        
    def generate_hdl(self):
        if not self.address_assigned():
            raise ValueError("Device must be assigned before generating HDL.")
            
        # Finally, write the HDL for the decoder
        hdl = f'library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;\nuse IEEE.NUMERIC_STD.ALL;\n\n'
        hdl += f'entity {self.name} is\n'
        hdl += f'    port (\n'
        hdl += f'        nrst            : in  std_logic;\n\n'
        hdl += f'        -- Slave interface\n'
        hdl += f'        master_bus_mosi : in  std_logic_vector({self.bus_data_bits-1} downto 0);\n'
        hdl += f'        master_bus_miso : out std_logic_vector({self.bus_data_bits-1} downto 0);\n'
        hdl += f'        master_bus_wr   : in  std_logic;\n'
        hdl += f'        master_bus_clk  : in  std_logic;\n'
        hdl += f'        master_bus_en   : in  std_logic;\n\n'
        
        for port_name, port in self._ports.items():
            hdl += f'        {port_name} : {port["direction"]} std_logic_vector({port["width"]-1} downto 0);\n'
            
        hdl = hdl[:-2] + f"\n    );\n" # Get rid of the last semicolon
        hdl += f'end {self.name};\n\n'

        hdl += f'architecture rtl of {self.name} is\n\n'
        
        # Assign attributes
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO : STRING;\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_MODE : STRING;\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_wr  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_clk : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus CLK";\n\n'
        
        # Make the delayed write enable signals
        for d in range(1,self._max_write_delay):
            hdl += f'    signal master_bus_wr_{"d"*d}: std_logic;\n'
        hdl += "\n"
        
        for port_name, port in self._ports.items():
            for p in range(1,port["pipeline"]):
                if port["direction"] == BusDataport.OUTPUT:
                    hdl += f'    signal master_bus_mosi_{"d"*p}_{port_name}: std_logic_vector({port["width"]-1} downto 0);\n'
                elif port["direction"] == BusDataport.INPUT:
                    hdl += f'    signal {port_name}_{"d"*p}: std_logic_vector({port["width"]-1} downto 0);\n'
            if port["pipeline"] > 1:        
                hdl += f'\n'
        hdl += f'\nbegin\n'
        
        # Delay the write enable signals
        if self._max_write_delay > 1:
            hdl += f"    delay_enable_proc: process(master_bus_clk) begin\n"
            hdl += f"        if rising_edge(master_bus_clk) then\n"
            for d in range(1,self._max_write_delay):
                hdl += f'            master_bus_wr_{"d"*d} <= master_bus_wr{" and master_bus_en" if d == 1 else ("_" + "d"*d)};\n'
            hdl += f"        end if;\n"
            hdl += f"    end process delay_enable_proc;\n\n"
        
        # Pipeline interfaces as specified
        for port_name, port in self._ports.items():
            port_slice = f'({port["width"] + port["offset"] - 1} downto {port["offset"]})'
            
            if port["pipeline"] == 0:
                # Combinational connection, just connect to the bus data pins except for any output reset gating
                if port["direction"] == BusDataport.INPUT:
                    hdl += f'    master_bus_miso{port_slice} <= {port_name};\n\n'
                elif port["gate"] == BusDataport.GATE_RESET:
                    hdl += f'    {port_name} <= master_bus_mosi{port_slice} when (master_bus_en and master_bus_wr) = \'1\' else (others => \'0\');\n\n'
                else:
                    hdl += f'    {port_name} <= master_bus_mosi{port_slice};\n\n'
            else:
                # Pipelined connection, create a process with the appropriate control signals (chip enables or resets as appropriate)
                hdl += f'    {port_name}_proc : process(master_bus_clk) begin\n'
                hdl += f'        if rising_edge(master_bus_clk) then\n'
                
                if port["direction"] == BusDataport.INPUT:
                    for p in range(port["pipeline"]):
                        hdl += f'            {"master_bus_miso"+port_slice if p == port["pipeline"]-1 else port_name + "_" + "d"*(p+1)} <= {port_name}{"" if p == 0 else "_" + "d"*p};\n'
                else:
                    for p in range(port["pipeline"]):
                        if port["gate"] == BusDataport.GATE_RESET:
                            hdl += f'            if(nrst = \'0\' or {"(" if p == 0 else ""}master_bus_wr{" and master_bus_en)" if p == 0 else ("_" + "d"*p)} = \'0\') then\n'
                        else:
                            hdl += f'            if(nrst = \'0\') then\n'
                            
                        hdl += f'                {"" if p == port["pipeline"]-1 else ("master_bus_mosi_" + "d"*(p+1) + "_")}{port_name} <= (others => \'0\');\n'  
                            
                        if port["gate"] == BusDataport.GATE_REGCE:
                            hdl += f'            elsif({"(" if p == 0 else ""}master_bus_wr{" and master_bus_en)" if p == 0 else ("_" + "d"*p)} = \'1\') then\n'
                        else:
                            hdl += f'            else\n'
                            
                        hdl += f'                {"" if p == port["pipeline"]-1 else ("master_bus_mosi_" + "d"*(p+1) + "_")}{port_name} <= master_bus_mosi{port_slice if p == 0 else ("_" + "d"*p + "_" + port_name)};\n'
                        hdl += f'            end if;\n\n'
                    
                hdl += f'        end if;\n'    
                hdl += f'    end process {port_name}_proc;\n\n'
                
        # Finally, assign all unused inputs to a constant
        for bit in range(self._bus_data_bits):
            if not (self._used_input_bits & (1 << bit)):
                hdl += f'    master_bus_miso({bit}) <= \'0\';\n'
                
        hdl += f'end rtl;\n'
                        
        return hdl
    
class BusDecoder(BusDevice, HDLModule):
    def __init__(self, name, bus_data_bits=32, bus_addr_bits=32, pipeline_miso=False, byte_write=False):
        """
        Generate an HDL file for a memory bus decoder.

        :param name: name of the decoder to generate
        :type name: str
        :param bus_data_bits: number of bits in the data word
        :type bus_data_bits: int, optional
        :param bus_addr_bits: number of bits in the address word
        :type bus_addr_bits: int, optional
        :param pipeline_miso: indicates whether to pipeline the signal driving the master data input
        :type pipeline_miso: bool, optional
        :param byte_write: indicates whether the write enable signal should have one bit per byte or per word
        :type byte_write: bool, optional
        """
        self._name = name
        self._bus_objects = []
        self._pipeline_miso = pipeline_miso
        self._byte_write = byte_write
            
        BusDevice.__init__(self, name, 0, bus_data_bits, bus_addr_bits)
        HDLModule.__init__(self, name)
        
    def add(self, obj, pipeline=False):
        """
        Add a new device to the bus decoder. 

        :param obj: Device to add
        :type obj: :class:`BusDevice`
        :param pipeline: If `True`\, a pipeline stage will be added on this
            port. 
        :type pipeline: bool, optional
        """
        if isinstance(obj, BusDevice):
            if obj.bus_data_bits > self.bus_data_bits:
                raise ValueError(f"Bus device data port width ({obj.bus_data_bits})"
                                 f" too large for bus decoder ({self.bus_data_bits}).")
            self._bus_objects.append((obj, pipeline))
        else:
            raise TypeError("Can only add BusDevices to a BusDecoder.")
            
    def max_slave_size(self):
        return next_highest_power_of_2(max(map(lambda x: x[0].size, self._bus_objects)))
    
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
        
    def assign_address(self, value=None):
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
        if num_ports*max_size > (2**self._bus_addr_bits):
            raise ValueError(f"Too many devices on the bus to be allocated (attempted to allocate {num_ports} devices with a max size of {max_size}).")
            
        super().assign_address(value)
        for i,(obj,pipeline) in enumerate(self._bus_objects):
            obj.assign_address(value + i*max_size)
                
    def generate_hdl(self):
        if not self.address_assigned():
            raise ValueError("Device must be assigned before generating HDL.")
        
        max_size = self.max_slave_size()
        num_ports = next_highest_power_of_2(len(self._bus_objects))
        
        # We now have all the information we need to figure out which bits we can ignore.
        # The max region size tells us how many lower bits we can ignore.
        # We then need enough bits to decode the number of regions that we have
        # We can then ignore all the bits above that
        decoder_inputs = next_highest_power_of_2(num_ports, log=True) # We've guaranteed these numbers to be powers of 2 above
        low_address_bit = next_highest_power_of_2(max_size, log=True)
        
        # Finally, write the HDL for the decoder
        hdl = f'library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;\nuse IEEE.NUMERIC_STD.ALL;\n\n'
        hdl += f'entity {self._name} is\n'
        hdl += f'    port (\n'
        hdl += f'        -- Slave interface\n'
        hdl += f'        master_bus_mosi : in  std_logic_vector({self.bus_data_bits-1} downto 0);\n'
        hdl += f'        master_bus_miso : out std_logic_vector({self.bus_data_bits-1} downto 0);\n'
        hdl += f'        master_bus_addr : in  std_logic_vector({next_highest_power_of_2(self.size, log=True)-1} downto 0);\n'
        if self._byte_write:
            hdl += f'        master_bus_wr   : in  std_logic_vector({(self.bus_data_bits // 8)-1} downto 0);\n'
        else:
            hdl += f'        master_bus_wr   : in  std_logic;\n'
        hdl += f'        master_bus_en   : in  std_logic;\n'
        hdl += f'        master_bus_clk  : in  std_logic;\n\n'
        
        for i,(obj,pipeline) in enumerate(self._bus_objects):
            hdl += f'        -- {obj.name} interface (local bus address 0x{obj.address().value()-self.address().value():08X}), (global bus address 0x{obj.address().value():08X})\n'
            hdl += f'        {obj.name}_mosi : out std_logic_vector({obj.bus_data_bits-1} downto 0);\n'
            hdl += f'        {obj.name}_miso : in  std_logic_vector({obj.bus_data_bits-1} downto 0);\n'
            hdl += f'        {obj.name}_addr : out std_logic_vector({low_address_bit-1} downto 0);\n'
            if self._byte_write:
                hdl += f'        {obj.name}_wr   : out std_logic_vector({(self.bus_data_bits // 8)-1} downto 0);\n'
            else:
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
                if obj.bus_data_bits == self.bus_data_bits:
                    hdl += f'                when "{f"{i:b}".zfill(decoder_inputs)}" => master_bus_miso <= {obj.name}_miso;\n'
                else:
                    hdl += f'                when "{f"{i:b}".zfill(decoder_inputs)}" => master_bus_miso({obj.bus_data_bits-1} downto 0) <= {obj.name}_miso; master_bus_miso({self.bus_data_bits-1} downto {obj.bus_data_bits}) <= (others => \'0\');\n' 
 
            hdl += f'                when others => master_bus_miso <= (others => \'0\');\n' 
            hdl += f'            end case;\n'
            hdl += f'        end if;\n'
            hdl += f'    end process master_bus_miso_proc;\n'
        else:
            hdl += f'    master_bus_miso   <= '
            for i,(obj,pipeline) in enumerate(self._bus_objects):
                if obj.bus_data_bits == self.bus_data_bits:
                    hdl += f'                  {obj.name}_miso when to_integer(unsigned(master_bus_addr({region_bits}))) = {i} else \n'
                else:
                    hdl += f'                  "{"0"*(self.bus_data_bits-obj.bus_data_bits)}" & {obj.name}_miso when to_integer(unsigned(master_bus_addr({region_bits}))) = {i} else \n'


            hdl += f'                  (others => \'0\');\n\n'
        
        # Connect all the master output ports
        for i,(obj, pipeline) in enumerate(self._bus_objects):
            hdl += f'    -- {obj.name} interface (local bus address 0x{obj.address().value()-self.address().value():08X}), (global bus address 0x{obj.address().value():08X})\n'         
            hdl += f'    {obj.name}_clk  <= master_bus_clk;\n\n'
            if pipeline:
                hdl += f'    {obj.name}_proc: process(master_bus_clk) begin\n'
                hdl += f'        if rising_edge(master_bus_clk) then\n'
                
                if obj.bus_data_bits == self.bus_data_bits:
                    hdl += f'            {obj.name}_mosi <= master_bus_mosi;\n'
                else:
                    hdl += f'            {obj.name}_mosi <= master_bus_mosi({obj.bus_data_bits-1} downto 0);\n'
                
                hdl += f'            {obj.name}_addr <= master_bus_addr({low_address_bit-1} downto 0);\n'
                hdl += f'            if (master_bus_addr({region_bits}) = "{f"{i:b}".zfill(decoder_inputs)}") then \n'
                hdl += f'                {obj.name}_en   <= \'1\';\n'
                hdl += f'                {obj.name}_wr   <= master_bus_wr;\n'
                hdl += f'            else\n'
                hdl += f'                {obj.name}_en   <= \'0\';\n'
                if self._byte_write:
                    hdl += f'                {obj.name}_wr   <= (others => \'0\');\n'
                else:
                    hdl += f'                {obj.name}_wr   <= \'0\';\n'
                hdl += f'            end if;\n'
                hdl += f'        end if;\n'
                hdl += f'    end process {obj.name}_proc;\n'
            else:
                if obj.bus_data_bits == self.bus_data_bits:
                    hdl += f'    {obj.name}_mosi <= master_bus_mosi;\n'
                else:
                    hdl += f'    {obj.name}_mosi <= master_bus_mosi({obj.bus_data_bits-1} downto 0);\n'

                hdl += f'    {obj.name}_addr <= master_bus_addr({low_address_bit-1} downto 0);\n'
                hdl += f'    {obj.name}_wr   <= master_bus_wr when to_integer(unsigned(master_bus_addr({region_bits}))) = {i} else \'0\';\n'
                hdl += f'    {obj.name}_en   <= master_bus_en when to_integer(unsigned(master_bus_addr({region_bits}))) = {i} else \'0\';\n'
            

        hdl += f'end rtl;\n'
        
        return hdl
    
class BusDataMoverController(BusDevice, HDLModule):
        
    def __init__(self, name, datamovers, addr_bits, bus_data_bits=32, bus_addr_bits=32, status_count_width=16):
        """
        A bus interface for access to the command and status ports of an array
        of AXI DataMovers. A small number of registers are also provided for 
        interacting with a given DataMover, where the base address of the 
        registers for that DataMover is the base address of this device, plus
        4 times the DataMover number.
        
        The registers are:

        - 0: CMD_ADDR/TRANSFER_STATUS
            Writing to this register issues a command to the DataMover 
            command FIFO whose address field is populated with the data
            written to this register. The values of the other fields are 
            derived from prior writes to other registers (see below).
            Reading this register pops a word from the status FIFO.

        - 1: CMD_BTT/TRANSFER_STATUS_COUNT
            This register stores the number of bytes for the DataMover to
            transfer when its next command is issued. Reading this register 
            returns the number of status words received by the controller
            since its last reset.

        - 2: CMD_MISC/TOTAL_BYTES_TRANSFERRED
            This register stores additional miscellaneous bits needed for a
            DataMover command:
                0     : TYPE
                1     : EOF
                5-2   : TAG
                9-6   : xCACHE
                13-10 : xUSER
                ADDR_BITS+14 - 14 : ADDR high bits
                
            Reading this register returns the total number of bytes transferred
            by the DataMover since the controller was last reset.

        - 3: CONTROLLER_RESET/CONTROLLER_STATUS
            Writing any value to this register clears its lowest bit 
            (described below) as well as TRANSFER_STATUS_COUNT and 
            TOTAL_BYTES_TRANSFERRED.
            Reading this register returns a bitfield with some status signals:
                0: This bit is set once the DataMover command interface sets 
                    TREADY after this module sets TVALID, indicating that it 
                    accepted the command driven by the module (this includes
                    when TREADY is already set when the command is issued).
                1: This bit is connected directly to the error signal for the
                   DataMover.
                
        :param datamovers: A list of strings containing the names of the DataMovers
        """
        self._datamovers = datamovers
        self._addr_bits = addr_bits
        self._status_count_width = status_count_width
        
        BusDevice.__init__(self, name, self.size, bus_data_bits, bus_addr_bits)
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
            return self._address.value() + 4*key
        elif isinstance(key, str):
            return self._address.value() + 4*self._datamovers.index(key)
        else:
            raise TypeError(f"Incompatible type for key {key}")
        
    def generate_hdl(self):
        if not self.address_assigned():
            raise ValueError("Device must be assigned before generating HDL.")
            
        num_ports = next_highest_power_of_2(self.size)
        bus_addr_bits = next_highest_power_of_2(num_ports, log=True)
        
        # Throw an error if a smarter strategy is needed
        if num_ports > (2**self.bus_addr_bits):
            raise ValueError(f"Too many devices on the bus to be allocated (attempted to allocate {num_ports} devices).")
            
        # Finally, write the HDL for the decoder
        hdl = f'library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;\nuse IEEE.NUMERIC_STD.ALL;\n\nlibrary xpm;\nuse xpm.vcomponents.all;\n\n'
        hdl += f'entity {self.name} is\n'
        hdl += f'    port (\n'
        
        hdl += f'        datamover_cmd_clk  : in std_logic;\n'
        hdl += f'        nrst : in std_logic;\n\n'

        hdl += f'        -- Slave interface\n'
        hdl += f'        master_bus_clk  : in std_logic;\n'
        hdl += f'        master_bus_mosi : in  std_logic_vector({self.bus_data_bits-1} downto 0);\n'
        hdl += f'        master_bus_miso : out std_logic_vector({self.bus_data_bits-1} downto 0);\n'
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
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of master_bus_clk : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus CLK";\n\n'
        
        for datamover in self._datamovers:
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_cmd_tdata  : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_cmd TDATA";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_cmd_tvalid : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_cmd TVALID";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_cmd_tready : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_cmd TREADY";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_MODE of {datamover}_cmd_tdata : SIGNAL is "Master";\n\n'
            
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_sts_tdata  : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_sts TDATA";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_sts_tvalid : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_sts TVALID";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of {datamover}_sts_tready : SIGNAL is "xilinx.com:interface:axis_rtl:1.0 {datamover}_sts TREADY";\n\n'
            
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of datamover_cmd_clk: SIGNAL is "xilinx.com:signal:clock:1.0 datamover_cmd_clk CLK";\n'
        bus_names = [s+f"_{d}" for s in self._datamovers for d in ["cmd","sts"]]
        hdl += f'    ATTRIBUTE X_INTERFACE_PARAMETER of datamover_cmd_clk: SIGNAL is "ASSOCIATED_BUSIF {":".join(bus_names)}";\n'
            
        hdl += f'    signal dm_err     : std_logic_vector(31 downto 0);\n'
        hdl += f'    signal dm_cmd_ack : std_logic_vector(31 downto 0);\n'
        hdl += f'    signal dm_rst     : std_logic_vector(31 downto 0);\n\n'
            
        for datamover in self._datamovers:
            hdl += f'    signal {datamover}_cmd_waiting : std_logic;\n\n'
            hdl += f'    signal {datamover}_cmd_btt     : std_logic_vector(22 downto 0);\n'
            hdl += f'    signal {datamover}_cmd_misc    : std_logic_vector({self._addr_bits-32+14-1} downto 0);\n\n'
            hdl += f'    signal {datamover}_sts         : std_logic_vector(31 downto 0);\n'
            hdl += f'    signal {datamover}_sts_rd      : std_logic;\n'
            hdl += f'    signal {datamover}_sts_cnt     : std_logic_vector({self._status_count_width-1} downto 0);\n'
        hdl += f'begin\n\n'
        
        hdl += f'    reg_wr_proc: process(master_bus_clk) begin\n'
        hdl += f'        if rising_edge(master_bus_clk) then\n'
        hdl += f'            if (nrst = \'0\') then\n'
        hdl += f'                dm_rst <= (others => \'0\');\n'
        
        for i,datamover in enumerate(self._datamovers):    
            hdl += f'                {datamover}_cmd_tdata   <= (others => \'0\');\n'
            hdl += f'                {datamover}_cmd_waiting <= \'0\';\n'
            hdl += f'                {datamover}_cmd_btt     <= (others => \'0\');\n'
            hdl += f'                {datamover}_cmd_misc    <= (others => \'0\');\n'
            
        
        hdl += f'            elsif (master_bus_en = \'1\' and master_bus_wr = \'1\') then\n'
        hdl += f'                case master_bus_addr({bus_addr_bits-1} downto 0) is\n'
        
        for i,datamover in enumerate(self._datamovers):    
            hdl += f'                    when "{f"{(i*4):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        {datamover}_cmd_tdata  <= {datamover}_cmd_misc(13 downto 6) & "0000" & {datamover}_cmd_misc(5 downto 2) & {datamover}_cmd_misc({self._addr_bits-32+14-1} downto 14) & master_bus_mosi & "0" & {datamover}_cmd_misc(1) & "000000" & {datamover}_cmd_misc(0) & {datamover}_cmd_btt;\n'
            hdl += f'                        {datamover}_cmd_waiting <= \'1\';\n'
            hdl += f'                        dm_rst <= (others => \'0\');\n'
            hdl += f'                    when "{f"{(i*4 + 1):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        {datamover}_cmd_btt  <=  master_bus_mosi(22 downto 0);\n'
            hdl += f'                        dm_rst <= (others => \'0\');\n'
            hdl += f'                    when "{f"{(i*4 + 2):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        {datamover}_cmd_misc <=  master_bus_mosi({self._addr_bits-32+14-1} downto 0);\n'
            hdl += f'                        dm_rst <= (others => \'0\');\n'
            hdl += f'                    when "{f"{(i*4 + 3):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                        dm_rst <= master_bus_mosi;\n'
        hdl += f'                    when others =>\n'
        hdl += f'                        dm_rst <= (others => \'0\');\n'
        hdl += f'                end case;\n'
        hdl += f'            else\n'
        hdl += f'                -- Clear the waiting signals if the cmd FIFO is ready\n'
        
        for i,datamover in enumerate(self._datamovers):  
            hdl += f'                if({datamover}_cmd_tready = \'1\') then\n'
            hdl += f'                    {datamover}_cmd_waiting <= \'0\';\n'
            hdl += f'                end if;\n\n'
        
        hdl += f'                -- Also clear dm_rst, since it should only be high for one cycle\n'
        hdl += f'                dm_rst <= (others => \'0\');\n'
        hdl += f'            end if;\n'
        hdl += f'        end if;\n'
        hdl += f'    end process reg_wr_proc;\n\n'
        
        hdl += f'    -- Connect the cmd_tvalid signals to the waiting signal\n'
        for i,datamover in enumerate(self._datamovers):  
            hdl += f'    {datamover}_cmd_tvalid <= {datamover}_cmd_waiting;\n'
        hdl += f'    \n'
        
        hdl += f'    dm_cmd_ack_proc: process(master_bus_clk) begin\n'
        hdl += f'        if rising_edge(master_bus_clk) then\n'
        hdl += f'            if (nrst = \'0\') then\n'
        hdl += f'                dm_cmd_ack <= (others => \'0\');\n'
        hdl += f'            else\n'
        
        for i,datamover in enumerate(self._datamovers):  
            hdl += f'                if ({datamover}_cmd_waiting = \'1\' and {datamover}_cmd_tready = \'1\') then\n'
            hdl += f'                    dm_cmd_ack({i}) <= \'1\';\n'
            hdl += f'                elsif (dm_rst({i}) = \'1\') then\n'
            hdl += f'                    dm_cmd_ack({i}) <= \'0\';\n'
            hdl += f'                end if;\n\n'
        
        hdl += f'            end if;\n'
        hdl += f'        end if;\n'
        hdl += f'    end process dm_cmd_ack_proc;\n\n'
        
        hdl += f'    -- Combine the DataMover error signals into one vector\n'
        for i,datamover in enumerate(self._datamovers):
            hdl += f'    dm_err({i}) <= {datamover}_err;\n'
        hdl += f'    dm_err(31 downto {len(self._datamovers)}) <= (others => \'0\');\n\n'
        
        hdl += f'    rd_proc: process(master_bus_clk) begin\n'
        hdl += f'        if rising_edge(master_bus_clk) then\n'
        hdl += f'            case master_bus_addr({bus_addr_bits-1} downto 0) is\n'
        
        for i,datamover in enumerate(self._datamovers):    
            hdl += f'                when "{f"{(i*4):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                    master_bus_miso <= {datamover}_sts;\n'
            hdl += f'                when "{f"{(i*4 + 1):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                    master_bus_miso <= "{"0"*(32-self._status_count_width)}" & {datamover}_sts_cnt;\n'
            hdl += f'                when "{f"{(i*4 + 2):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                    master_bus_miso <= dm_cmd_ack;\n'
            hdl += f'                when "{f"{(i*4 + 3):b}".zfill(bus_addr_bits)}" =>\n'
            hdl += f'                    master_bus_miso <= dm_err;\n'
            
        hdl += f'                when others =>\n'
        hdl += f'                    master_bus_miso <= (others => \'0\');\n'
        hdl += f'            end case;\n'
        hdl += f'        end if;\n'
        hdl += f'    end process rd_proc;\n\n'

        hdl += f'    -- Create FIFOs for the status words\n'
        for i,datamover in enumerate(self._datamovers): 
            hdl += f'    {datamover}_sts_tready <= nrst and not dm_rst({i});\n'
            hdl += f'    {datamover}_sts_rd <= \'1\' when master_bus_addr({bus_addr_bits-1} downto 0) = "{f"{(i*4):b}".zfill(bus_addr_bits)}" and master_bus_en = \'1\' and master_bus_wr = \'0\' else \'0\';\n\n'
            hdl += f'    -- Create a status counter\n'
            hdl += f'    {datamover}_sts_cnt_proc: process(master_bus_clk) begin\n' 
            hdl += f'        if rising_edge(master_bus_clk) then\n'
            hdl += f'            if(nrst = \'0\' or dm_rst({i}) = \'1\') then\n'
            hdl += f'                {datamover}_sts_cnt <= (others => \'0\');\n'
            hdl += f'            elsif({datamover}_sts_tvalid = \'1\') then\n'
            hdl += f'                {datamover}_sts_cnt <= std_logic_vector(unsigned({datamover}_sts_cnt) + 1);\n'
            hdl += f'            end if;\n'
            hdl += f'        end if;\n'
            hdl += f'    end process {datamover}_sts_cnt_proc;\n\n' 
            hdl += f'    {datamover}_sts_fifo : xpm_fifo_sync\n'
            hdl += f'        generic map (\n'
            hdl += f'            DOUT_RESET_VALUE    => "0",\n'
            hdl += f'            ECC_MODE            => "no_ecc",\n'
            hdl += f'            FIFO_MEMORY_TYPE    => "distributed", -- String\n'
            hdl += f'            FIFO_READ_LATENCY   => 0,\n'
            hdl += f'            FIFO_WRITE_DEPTH    => 16,\n'
            hdl += f'            FULL_RESET_VALUE    => 0,\n'
            hdl += f'            PROG_EMPTY_THRESH   => 10,\n'
            hdl += f'            PROG_FULL_THRESH    => 10,\n'
            hdl += f'            RD_DATA_COUNT_WIDTH => 4,\n'
            hdl += f'            READ_DATA_WIDTH     => 32,\n'
            hdl += f'            READ_MODE           => "fwft",\n'
            hdl += f'            SIM_ASSERT_CHK      => 0,\n'
            hdl += f'            USE_ADV_FEATURES    => "0000",\n'
            hdl += f'            WAKEUP_TIME         => 0,\n'
            hdl += f'            WRITE_DATA_WIDTH    => 32,\n'
            hdl += f'            WR_DATA_COUNT_WIDTH => 4\n'
            hdl += f'        )\n'
            hdl += f'        port map (\n'
            hdl += f'            almost_empty  => open,\n'
            hdl += f'            almost_full   => open,\n'
            hdl += f'            data_valid    => open,\n'
            hdl += f'            dbiterr       => open,\n'
            hdl += f'            dout          => {datamover}_sts,\n'
            hdl += f'            empty         => open,\n'
            hdl += f'            full          => open,\n'
            hdl += f'            overflow      => open,\n'
            hdl += f'            prog_empty    => open,\n'
            hdl += f'            prog_full     => open,\n'
            hdl += f'            rd_data_count => open,\n'
            hdl += f'            rd_rst_busy   => open,\n'
            hdl += f'            sbiterr       => open,\n'
            hdl += f'            underflow     => open,\n'
            hdl += f'            wr_ack        => open,\n'
            hdl += f'            wr_data_count => open,\n'
            hdl += f'            wr_rst_busy   => open,\n'
            hdl += f'            din           => {datamover}_sts_tdata,\n'
            hdl += f'            injectdbiterr => \'0\',\n'
            hdl += f'            injectsbiterr => \'0\',\n'
            hdl += f'            rd_en         => {datamover}_sts_rd,\n'
            hdl += f'            rst           => dm_rst({i}),\n'
            hdl += f'            sleep         => \'0\',\n'
            hdl += f'            wr_clk        => master_bus_clk,\n'
            hdl += f'            wr_en         => {datamover}_sts_tvalid\n'
            hdl += f'        );\n\n'
        
        
        hdl += f'end rtl;\n\n'
        
        return hdl
    
class AXIMemoryArray(HDLModule):
    """
    Creates a wrapper for an AXI BRAM controller connected to a memory.
    """
    
    def __init__(self, 
                 module_name, 
                 size_bits, 
                 width, 
                 elements=1, 
                 primitive="auto", 
                 synchronous=True, 
                 controller_width=None, 
                 controller_port_input_pipeline=1, 
                 controller_port_output_pipeline=1, 
                 user_port_input_pipeline=1, 
                 user_port_output_pipeline=1, 
                 axi4_lite=False, 
                 axi_id_width=0,
                 read_only=False, 
                 use_rst=True, 
                 instantiate_memories=True,
                 synth_jobs=16):
        """
        :param module_name: The name of the module
        :type module_name: str
        :param width: The width of the user data port.
        :type width: int
        :param size_bits: The size of a single memory element in bits
        :type depth: int
        :param elements: Number of memory elements to create
        :type elements: int, optional
        :param primitive: The memory primitive to use. One of "auto", "block", 
            "distributed", "mixed", "ultra"
        :type primitive: str, optional
        :param synchronous: If ``True``, the memory will be a synchronous 
            single-clock memory driven by the AXI clock. Otherwise, a separate
            clock signal will be created on the memory interface.
        :param controller_width: Width of the port connected to the controller
        :type controller_width: int
        :param controller_port_input_pipeline: Number of pipeline stages to
            add to the memory's input signals (din, addr, we) on the port connected
            to the controller.
        :type controller_port_input_pipeline: int
        :param controller_port_output_pipeline: Number of pipeline stages to
            add to the memory's data output signal on the port connected to the 
            controller.
        :type controller_port_output_pipeline: int
        :param user_port_input_pipeline: Number of pipeline stages to
            add to the memory's input signals (din, addr, we) on the user port.
        :type user_port_output_pipeline: int
        :param user_port_output_pipeline: Number of pipeline stages to
            add to the memory's data output signal on the user port.
        :type user_port_output_pipeline: int
        :param axi4_lite: If ``True``, the BRAM controller will be implemented
            with an AXI4-Lite interface instead of full AXI4.
        :type axi4_lite: bool, optional
        :param axi_id_width: The width of the ID port on the AXI interface
        :type axi_id_width: int
        :param read_only: If ``True``, the write enable of the user port will be 
            tied low.
        :type read_only: bool, optional
        :param use_rst: If ``False``, the reset signal of the exposed port will 
            be tied low. If ``True``, an additional output pipeline stage with a 
            reset input will be added.
        :type use_rst: bool, optional
        :param read_data_pipeline: The number of additional pipeline stages to
            add to the data output of the memory.
        :type read_data_pipeline: int, optional
        :param instatiate_memories: If ``True``, The memories will be integrated
            into the module; otherwise, the segmented memory controller will be
            exposed as the user port.
        :param synth_jobs: Number of processor jobs to use for synthesizing the
            BRAM controller IP
        :type synth_jobs: int, optional
        """

        self._size_bits = size_bits
        self._width = width
        self._synchronous = synchronous
        
        if elements <= 0:
            raise ValueError("Number of memory elements must be a positive number")
        self._elements = elements
        
        if primitive not in ["auto", "block", "distributed", "ultra"]:
            raise ValueError("Primitive must be one of 'auto', 'block', 'distributed', or 'ultra'.")
        self._primitive = primitive
        
        self._controller_width = controller_width if controller_width is not None else width
        self._controller_port_input_pipeline = controller_port_input_pipeline
        self._controller_port_output_pipeline = controller_port_output_pipeline
        self._user_port_input_pipeline = user_port_input_pipeline
        self._user_port_output_pipeline = user_port_output_pipeline
        
        self._axi4_lite = axi4_lite
        self._axi_id_width = axi_id_width
        self._read_only = read_only
        self._use_rst = use_rst
        self._synth_jobs = synth_jobs
        self._instantiate_memories = instantiate_memories
        super().__init__(module_name)
        
    def generate_hdl(self):
        """
        Generates an HDL file for the controller.
        """        
        
        # Make some constants that we'll use later        
        log2_elements = next_highest_power_of_2(self._elements, log=True) 
        log2_mem_depth = next_highest_power_of_2(self._size_bits // self._width, log=True) 
        
        controller_address_bits = next_highest_power_of_2((self._size_bits // 8)*self._elements, log=True) 
        controller_unused_bits = next_highest_power_of_2(self._controller_width // 8, log=True)        
        
        hdl = f'library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;\nuse IEEE.NUMERIC_STD.ALL;\n\nlibrary xpm;\nuse xpm.vcomponents.all;\n\n'
        hdl += f'entity {self._module_name}_axi_memory is\n'
        hdl += f'    port (\n'
        hdl += f'        s_axi_aclk    : in  std_logic;\n'
        hdl += f'        s_axi_aresetn : in  std_logic;\n\n'
        
        hdl += f'        s_axi_awaddr  : in  std_logic_vector({controller_address_bits-1} downto 0);\n'
        hdl += f'        s_axi_awvalid : in  std_logic;\n'
        hdl += f'        s_axi_awready : out std_logic;\n'
        if not self._axi4_lite:
            if self._axi_id_width > 0:
                hdl += f'        s_axi_awid    : in  std_logic_vector({self._axi_id_width-1} downto 0);\n'
            hdl += f'        s_axi_awlen   : in  std_logic_vector(7 downto 0);\n'
            hdl += f'        s_axi_awsize  : in  std_logic_vector(2 downto 0);\n'
            hdl += f'        s_axi_awburst : in  std_logic_vector(1 downto 0);\n'
            hdl += f'        s_axi_awlock  : in  std_logic;\n'
            hdl += f'        s_axi_awprot  : in  std_logic_vector(2 downto 0);\n'
            hdl += f'        s_axi_awcache : in  std_logic_vector(3 downto 0);\n'
        
        hdl += f'        s_axi_wdata   : in  std_logic_vector({self._controller_width-1} downto 0);\n'
        hdl += f'        s_axi_wstrb   : in  std_logic_vector({(self._controller_width // 8) - 1} downto 0);\n'
        hdl += f'        s_axi_wvalid  : in  std_logic;\n'
        hdl += f'        s_axi_wready  : out std_logic;\n'
        if not self._axi4_lite:
            hdl += f'        s_axi_wlast   : in  std_logic;\n'
        
        hdl += f'        s_axi_bresp   : out std_logic_vector(1 downto 0);\n'
        hdl += f'        s_axi_bvalid  : out std_logic;\n'
        hdl += f'        s_axi_bready  : in  std_logic;\n'
        if (not self._axi4_lite) and self._axi_id_width > 0:
            hdl += f'        s_axi_bid     : out std_logic_vector({self._axi_id_width-1} downto 0);\n'
        
        hdl += f'        s_axi_araddr  : in  std_logic_vector({controller_address_bits-1} downto 0);\n'
        hdl += f'        s_axi_arvalid : in  std_logic;\n'
        hdl += f'        s_axi_arready : out std_logic;\n'
        if not self._axi4_lite:
            if self._axi_id_width > 0:
                hdl += f'        s_axi_arid    : in  std_logic_vector({self._axi_id_width-1} downto 0);\n'
            hdl += f'        s_axi_arlen   : in  std_logic_vector(7 downto 0);\n'
            hdl += f'        s_axi_arsize  : in  std_logic_vector(2 downto 0);\n'
            hdl += f'        s_axi_arburst : in  std_logic_vector(1 downto 0);\n'
            hdl += f'        s_axi_arlock  : in  std_logic;\n'
            hdl += f'        s_axi_arprot  : in  std_logic_vector(2 downto 0);\n'
            hdl += f'        s_axi_arcache : in  std_logic_vector(3 downto 0);\n'
        
        hdl += f'        s_axi_rdata   : out std_logic_vector({self._controller_width-1} downto 0);\n'
        hdl += f'        s_axi_rresp   : out std_logic_vector(1 downto 0);\n'
        hdl += f'        s_axi_rvalid  : out std_logic;\n'
        hdl += f'        s_axi_rready  : in  std_logic;\n'
        if not self._axi4_lite:
            hdl += f'        s_axi_rlast   : out std_logic;\n'
            if self._axi_id_width > 0:
                hdl += f'        s_axi_rid     : out std_logic_vector({self._axi_id_width-1} downto 0);\n'
            
        for i in range(self._elements):
            hdl += f'\n'
            if not self._read_only:
                hdl += f'        mem{i}_din     : {"in " if self._instantiate_memories else "out"} std_logic_vector({self._width-1} downto 0);\n'
            hdl += f'        mem{i}_dout    : {"out" if self._instantiate_memories else "in "} std_logic_vector({self._width-1} downto 0);\n'
            hdl += f'        mem{i}_addr    : {"in " if self._instantiate_memories else "out"} std_logic_vector({log2_mem_depth-1} downto 0);\n'
            if not self._synchronous:
                hdl += f'        mem{i}_clk     : {"in " if self._instantiate_memories else "out"} std_logic;\n'
            if not self._read_only:
                if self._instantiate_memories:
                    hdl += f'        mem{i}_we      : in  std_logic;\n'
                else:
                    hdl += f'        mem{i}_we      : out std_logic_vector({(self._controller_width // 8)-1} downto 0);\n'

            if self._use_rst:
                hdl += f'        mem{i}_rst     : {"in " if self._instantiate_memories else "out"} std_logic;\n'
            if not self._instantiate_memories:
                hdl += f'        mem{i}_en      : out std_logic;\n'
        
        hdl = hdl[:-2] + f"\n    );\n"
        hdl += f'end {self._module_name}_axi_memory;\n\n'

        hdl += f'architecture rtl of {self._module_name}_axi_memory is\n\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO      : STRING;\n' 
        hdl += f'    ATTRIBUTE X_INTERFACE_MODE      : STRING;\n' 
        hdl += f'    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;\n\n'
        
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awaddr  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWADDR";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awvalid : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWVALID";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awready : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWREADY";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_wdata   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI WDATA";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_wstrb   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI WSTRB";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_wvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI WVALID";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_wready  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI WREADY";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_bresp   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI BRESP";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_bvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI BVALID";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_bready  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI BREADY";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_araddr  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARADDR";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arvalid : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARVALID";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arready : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARREADY";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_rdata   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI RDATA";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_rresp   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI RRESP";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_rvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI RVALID";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_rready  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI RREADY";\n'
        
        if not self._axi4_lite:
            if self._axi_id_width > 0:
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_bid     : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI BID";\n'
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awid    : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWID";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awlen   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWLEN";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awsize  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWSIZE";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awburst : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWBURST";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awlock  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWLOCK";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awprot  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWPROT";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_awcache : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI AWCACHE";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_wlast   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI WLAST";\n'
            
            if self._axi_id_width > 0:
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_rid     : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI RID";\n'
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arid    : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARID";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arlen   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARLEN";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arsize  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARSIZE";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arburst : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARBURST";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arlock  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARLOCK";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arprot  : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARPROT";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_arcache : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI ARCACHE";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_rlast   : SIGNAL is "xilinx.com:interface:aximm:1.0 S_AXI RLAST";\n'
         
        hdl += f'\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_INFO of s_axi_aclk      : SIGNAL is "xilinx.com:signal:clock:1.0 s_axi_aclk CLK";\n'
        hdl += f'    ATTRIBUTE X_INTERFACE_PARAMETER of s_axi_aclk : SIGNAL is "ASSOCIATED_BUSIF S_AXI";\n'
        
        hdl += f'\n'
        hdl += (f'    ATTRIBUTE X_INTERFACE_PARAMETER of s_axi_awaddr : SIGNAL is "'
                        f'MAX_BURST_LENGTH {1 if self._axi4_lite else 256},'
                        f'SUPPORTS_NARROW_BURST {0 if self._axi4_lite else 1},'
                        f'READ_WRITE_MODE READ_WRITE,'
                        f'BUSER_WIDTH 0,'
                        f'RUSER_WIDTH 0,'
                        f'WUSER_WIDTH 0,'
                        f'ARUSER_WIDTH 0,'
                        f'AWUSER_WIDTH 0,'
                        f'ADDR_WIDTH {controller_address_bits},'
                        f'ID_WIDTH {self._axi_id_width},'
                        f'PROTOCOL {"AXI4LITE" if self._axi4_lite else "AXI4"},'
                        f'DATA_WIDTH {self._controller_width},'
                        f'HAS_BURST {1 if self._axi4_lite else 0},'
                        f'HAS_CACHE 1,'
                        f'HAS_LOCK 1,'
                        f'HAS_PROT 1,'
                        f'HAS_QOS 0,'
                        f'HAS_REGION 0,'
                        f'HAS_WSTRB 1,'
                        f'HAS_BRESP 1,'
                        f'HAS_RRESP 1'
                        f'";\n')

        for i in range(self._elements):
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of mem{i}_addr : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem{i} ADDR";\n'
            if not self._read_only:
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of mem{i}_din  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem{i} DIN";\n'
            hdl += f'    ATTRIBUTE X_INTERFACE_INFO of mem{i}_dout : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem{i} DOUT";\n'
            if not self._synchronous:
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of mem{i}_clk  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem{i} CLK";\n'
            if not self._read_only:
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of mem{i}_we   : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem{i} WE";\n'
            if self._use_rst:
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of mem{i}_rst  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem{i} RST";\n'
            if not self._instantiate_memories:
                hdl += f'    ATTRIBUTE X_INTERFACE_INFO of mem{i}_en   : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem{i} EN";\n'        
                hdl += f'    ATTRIBUTE X_INTERFACE_MODE of mem{i}_addr : SIGNAL is "Master";\n'
        
        hdl += "\n"
        hdl += f'    component {self._module_name}_ip\n'
        hdl += f'        port (\n'
        hdl += f'            s_axi_aclk    : in  std_logic;\n'
        hdl += f'            s_axi_aresetn : in  std_logic;\n\n'
        
        hdl += f'            s_axi_awaddr  : in  std_logic_vector({controller_address_bits-1} downto 0);\n'
        hdl += f'            s_axi_awvalid : in  std_logic;\n'
        hdl += f'            s_axi_awready : out std_logic;\n'
        if not self._axi4_lite:
            if self._axi_id_width > 0:
                hdl += f'            s_axi_awid    : in  std_logic_vector({self._axi_id_width-1} downto 0);\n'
            hdl += f'            s_axi_awlen   : in  std_logic_vector(7 downto 0);\n'
            hdl += f'            s_axi_awsize  : in  std_logic_vector(2 downto 0);\n'
            hdl += f'            s_axi_awburst : in  std_logic_vector(1 downto 0);\n'
            hdl += f'            s_axi_awlock  : in  std_logic;\n'
            hdl += f'            s_axi_awprot  : in  std_logic_vector(2 downto 0);\n'
            hdl += f'            s_axi_awcache : in  std_logic_vector(3 downto 0);\n'
            
        
        hdl += f'            s_axi_wdata   : in  std_logic_vector({self._controller_width-1} downto 0);\n'
        hdl += f'            s_axi_wstrb   : in  std_logic_vector({(self._controller_width // 8) - 1} downto 0);\n'
        hdl += f'            s_axi_wvalid  : in  std_logic;\n'
        hdl += f'            s_axi_wready  : out std_logic;\n'
        if not self._axi4_lite:
            hdl += f'            s_axi_wlast   : in  std_logic;\n'
        
        hdl += f'            s_axi_bresp   : out std_logic_vector(1 downto 0);\n'
        hdl += f'            s_axi_bvalid  : out std_logic;\n'
        hdl += f'            s_axi_bready  : in  std_logic;\n'
        if (not self._axi4_lite) and self._axi_id_width > 0:
            hdl += f'            s_axi_bid     : out std_logic_vector({self._axi_id_width-1} downto 0);\n'
        
        
        hdl += f'            s_axi_araddr  : in  std_logic_vector({controller_address_bits-1} downto 0);\n'
        hdl += f'            s_axi_arvalid : in  std_logic;\n'
        hdl += f'            s_axi_arready : out std_logic;\n'
        if not self._axi4_lite:
            if self._axi_id_width > 0:
                hdl += f'            s_axi_arid    : in  std_logic_vector({self._axi_id_width-1} downto 0);\n'
            hdl += f'            s_axi_arlen   : in  std_logic_vector(7 downto 0);\n'
            hdl += f'            s_axi_arsize  : in  std_logic_vector(2 downto 0);\n'
            hdl += f'            s_axi_arburst : in  std_logic_vector(1 downto 0);\n'
            hdl += f'            s_axi_arlock  : in  std_logic;\n'
            hdl += f'            s_axi_arprot  : in  std_logic_vector(2 downto 0);\n'
            hdl += f'            s_axi_arcache : in  std_logic_vector(3 downto 0);\n'
        
        hdl += f'            s_axi_rdata   : out std_logic_vector({self._controller_width-1} downto 0);\n'
        hdl += f'            s_axi_rresp   : out std_logic_vector(1 downto 0);\n'
        hdl += f'            s_axi_rvalid  : out std_logic;\n'
        hdl += f'            s_axi_rready  : in  std_logic;\n'
        if not self._axi4_lite:
            hdl += f'            s_axi_rlast   : out std_logic;\n'
            if self._axi_id_width > 0:
                hdl += f'            s_axi_rid     : out std_logic_vector({self._axi_id_width-1} downto 0);\n'
            
            
        hdl += f'\n'
        
        # The critical issue with the BRAM controller - the width of the address port
        # is determined by the number of bytes in the BRAM, rather than the number of words
        hdl += f'            bram_addr_a   : out std_logic_vector({controller_address_bits-1} downto 0);\n'
        hdl += f'            bram_wrdata_a : out std_logic_vector({self._controller_width-1} downto 0);\n'
        hdl += f'            bram_rddata_a : in  std_logic_vector({self._controller_width-1} downto 0);\n'
        hdl += f'            bram_we_a     : out std_logic_vector({(self._controller_width // 8) - 1} downto 0);\n'
        hdl += f'            bram_en_a     : out std_logic;\n'
        hdl += f'            bram_clk_a    : out std_logic\n'
        
        hdl += f"        );\n"
        hdl += f"    end component;\n\n"
        
        hdl += f'    signal controller_addr   : std_logic_vector({controller_address_bits-1} downto 0);\n'
        hdl += f'    signal controller_wrdata : std_logic_vector({self._controller_width-1} downto 0);\n'
        hdl += f'    signal controller_rddata : std_logic_vector({self._controller_width-1} downto 0);\n'
        hdl += f'    signal controller_we     : std_logic_vector({(self._controller_width // 8) - 1} downto 0);\n'
        hdl += f'    signal controller_en     : std_logic;\n\n'

        controller_input_to_output_delay = self._controller_port_input_pipeline + self._controller_port_output_pipeline
        
        for element in range(self._elements):
            hdl += f'    signal controller_mem{element}_en_gated : std_logic;\n'
        
        for i in range(controller_input_to_output_delay):
            hdl += f'    signal controller_addr_{"d"*(i+1)}   : std_logic_vector({controller_address_bits-1} downto 0);\n'
        
        for i in range(self._controller_port_input_pipeline):
            hdl += f'    signal controller_wrdata_{"d"*(i+1)} : std_logic_vector({self._controller_width-1} downto 0);\n'
            hdl += f'    signal controller_we_{"d"*(i+1)} : std_logic_vector({(self._controller_width // 8)-1} downto 0);\n'
        hdl += "\n"
        
        for i in range(self._controller_port_input_pipeline):
            for element in range(self._elements):
                hdl += f'    signal controller_mem{element}_en_gated_{"d"*(i+1)} : std_logic;\n'
            hdl += "\n"
        
        for element in range(self._elements):
            hdl += f'    signal controller_mem{element}_rddata : std_logic_vector({self._controller_width-1} downto 0);\n'
            # for i in range(self._controller_port_output_pipeline):
            #     hdl += f'    signal controller_mem{element}_rddata_{"d"*(i+1)} : std_logic_vector({self._controller_width-1} downto 0);\n'    
        
        hdl += "\n"

        if self._instantiate_memories:
            user_input_to_output_delay = self._user_port_input_pipeline + self._user_port_output_pipeline
            for element in range(self._elements):
                for i in range(self._user_port_input_pipeline):
                    hdl += f'    signal mem{element}_addr_{"d"*(i+1)} : std_logic_vector({log2_mem_depth-1} downto 0);\n'
                    
                    if not self._read_only:
                        hdl += f'    signal mem{element}_din_{"d"*(i+1)}  : std_logic_vector({self._width-1} downto 0);\n'
                        hdl += f'    signal mem{element}_we_{"d"*(i+1)}   : std_logic;\n'
                
                hdl += f'    signal mem{element}_dout_int : std_logic_vector({self._width-1} downto 0);\n'  
                
                for i in range(self._user_port_output_pipeline):
                    hdl += f'    signal mem{element}_dout_int_{"d"*(i+1)} : std_logic_vector({self._width-1} downto 0);\n'    

                if self._use_rst:
                    for i in range(user_input_to_output_delay+1):
                        hdl += f'    signal mem{element}_rst_{"d"*(i+1)}  : std_logic;\n'
                    
                hdl += "\n"
        
        hdl += "\n"
        
        hdl += f'begin\n\n'
    
        hdl += f'    bram_ctrl_inst: {self._module_name}_ip\n'
        hdl += f'        port map (\n'
        
        
        hdl += f'            s_axi_aclk    => s_axi_aclk,\n'
        hdl += f'            s_axi_aresetn => s_axi_aresetn,\n\n'
        
        hdl += f'            s_axi_awaddr  => s_axi_awaddr,\n'
        hdl += f'            s_axi_awvalid => s_axi_awvalid,\n'
        hdl += f'            s_axi_awready => s_axi_awready,\n'
        if not self._axi4_lite:
            if self._axi_id_width > 0:
                hdl += f'            s_axi_awid    => s_axi_awid,\n'
            hdl += f'            s_axi_awlen   => s_axi_awlen,\n'
            hdl += f'            s_axi_awsize  => s_axi_awsize,\n'
            hdl += f'            s_axi_awburst => s_axi_awburst,\n'
            hdl += f'            s_axi_awlock  => s_axi_awlock,\n'
            hdl += f'            s_axi_awprot  => s_axi_awprot,\n'
            hdl += f'            s_axi_awcache => s_axi_awcache,\n'
        
        hdl += f'            s_axi_wdata   => s_axi_wdata,\n'
        hdl += f'            s_axi_wstrb   => s_axi_wstrb,\n'
        hdl += f'            s_axi_wvalid  => s_axi_wvalid,\n'
        hdl += f'            s_axi_wready  => s_axi_wready,\n'
        if not self._axi4_lite:
            hdl += f'            s_axi_wlast   => s_axi_wlast,\n'
        
        hdl += f'            s_axi_bresp   => s_axi_bresp,\n'
        hdl += f'            s_axi_bvalid  => s_axi_bvalid,\n'
        hdl += f'            s_axi_bready  => s_axi_bready,\n'
        if (not self._axi4_lite) and self._axi_id_width > 0:
            hdl += f'            s_axi_bid     => s_axi_bid,\n'
        
        hdl += f'            s_axi_araddr  => s_axi_araddr,\n'
        hdl += f'            s_axi_arvalid => s_axi_arvalid,\n'
        hdl += f'            s_axi_arready => s_axi_arready,\n'
        if not self._axi4_lite:
            if self._axi_id_width > 0:
                hdl += f'            s_axi_arid    => s_axi_arid,\n'
            hdl += f'            s_axi_arlen   => s_axi_arlen,\n'
            hdl += f'            s_axi_arsize  => s_axi_arsize,\n'
            hdl += f'            s_axi_arburst => s_axi_arburst,\n'
            hdl += f'            s_axi_arlock  => s_axi_arlock,\n'
            hdl += f'            s_axi_arprot  => s_axi_arprot,\n'
            hdl += f'            s_axi_arcache => s_axi_arcache,\n'
        
        hdl += f'            s_axi_rdata   => s_axi_rdata,\n'
        hdl += f'            s_axi_rresp   => s_axi_rresp,\n'
        hdl += f'            s_axi_rvalid  => s_axi_rvalid,\n'
        hdl += f'            s_axi_rready  => s_axi_rready,\n'
        if not self._axi4_lite:
            hdl += f'            s_axi_rlast   => s_axi_rlast,\n'
            if self._axi_id_width > 0:
                hdl += f'            s_axi_rid     => s_axi_rid,\n'
            
        hdl += f'\n'
        
        hdl += f'            bram_addr_a   => controller_addr,\n'
        hdl += f'            bram_clk_a    => open,\n'
        hdl += f'            bram_en_a     => controller_en,\n'
        hdl += f'            bram_we_a     => controller_we,\n'
        hdl += f'            bram_wrdata_a => controller_wrdata,\n'
        hdl += f'            bram_rddata_a => controller_rddata\n'
        
        hdl += f'        );\n\n'
        
        for element in range(self._elements):
            hdl += f'    controller_mem{element}_en_gated <= controller_en'
            if self._elements == 1:
                hdl += ';\n'
            else:
                hdl += f' when controller_addr({controller_address_bits-1} downto {controller_address_bits-log2_elements}) = "{f"{element:b}".zfill(log2_elements)}" else \'0\';\n'
        
        # Create the controller interface
        if self._controller_port_input_pipeline > 0 or self._controller_port_output_pipeline > 0:
            hdl += f'    controller_pipeline_proc: process(s_axi_aclk) begin\n'
            hdl += f'        if rising_edge(s_axi_aclk) then\n'

            for i in range(self._controller_port_input_pipeline):
                delay = "_" + "d"*i if i != 0 else ""
                hdl += f'            controller_wrdata_{"d"*(i+1)}        <= controller_wrdata{delay};\n' 
                hdl += f'            controller_we_{"d"*(i+1)}            <= controller_we{delay};\n' 
                
                for element in range(self._elements):
                    hdl += f'            controller_mem{element}_en_gated_{"d"*(i+1)} <= controller_mem{element}_en_gated{delay};\n' 

            hdl += "\n"
            
            for i in range(controller_input_to_output_delay):
                delay = "_" + "d"*i if i != 0 else ""
                hdl += f'            controller_addr_{"d"*(i+1)}          <= controller_addr{delay};\n' 

            hdl += "\n"

            hdl += f'        end if;\n'
            hdl += f'    end process controller_pipeline_proc;\n\n'
        
        hdl += f'    controller_rddata <= '
        
        if self._elements == 1:
            hdl += f'controller_mem0_rddata;\n\n'
        else:
            for element in range(self._elements):
                hdl += f'        controller_mem{element}_rddata when controller_addr{"_" + "d"*controller_input_to_output_delay if controller_input_to_output_delay != 0 else ""}({controller_address_bits-1} downto {controller_address_bits-log2_elements}) = "{f"{element:b}".zfill(log2_elements)}" else\n'
            hdl += f'    (others => \'0\');\n\n'

        
            
        if self._instantiate_memories:
            if self._user_port_input_pipeline > 0:
                for element in range(self._elements):
                    # Create the user interface
                    user_clk = "s_axi_aclk" if self._synchronous else f"mem{element}_clk"
                    hdl += f'    mem{element}_user_port_input_pipeline_proc: process({user_clk}) begin\n'
                    hdl += f'        if rising_edge({user_clk}) then\n'

                    for i in range(self._user_port_input_pipeline):
                        delay = "_" + "d"*i if i != 0 else ""
                        hdl += f'            mem{element}_addr_{"d"*(i+1)}     <= mem{element}_addr{delay};\n' 
                        if not self._read_only:
                            hdl += f'            mem{element}_din_{"d"*(i+1)}      <= mem{element}_wrdata{delay};\n' 
                            hdl += f'            mem{element}_we_{"d"*(i+1)}       <= mem{element}_we{delay};\n' 
                    
                    hdl += f'        end if;\n'
                    hdl += f'    end process mem{element}_user_port_input_pipeline_proc;\n\n'

            for element in range(self._elements):
                user_clk = "s_axi_aclk" if self._synchronous else f"mem{element}_clk"
                if self._use_rst:
                    hdl += f'    mem{element}_user_port_rst_proc: process({user_clk}) begin\n'
                    hdl += f'        if rising_edge({user_clk}) then\n'

                    for i in range(user_input_to_output_delay+1):
                        delay = "_" + "d"*i if i != 0 else ""
                        hdl += f'            mem{element}_rst_{"d"*(i+1)}      <= mem{element}_rst{delay};\n'
                    hdl += "\n"

                    hdl += f'            if(mem{element}_rst_{"d"*(user_input_to_output_delay+1)} = \'1\') then\n'   
                    hdl += f'                mem{element}_dout <= (others => \'0\');\n' 
                    hdl += f'            else\n'
                    hdl += f'                mem{element}_dout <= mem{element}_dout_int;\n'
                    hdl += f'            end if;\n'
                    hdl += f'        end if;\n'
                    hdl += f'    end process mem{element}_user_port_rst_proc;\n\n'
                else:
                    hdl += f'    mem{element}_dout <= mem{element}_dout_int;\n\n'
            
        delayed_controller_input_suffix = "_" + "d"*self._controller_port_input_pipeline if self._controller_port_input_pipeline != 0 else ""
        for element in range(self._elements):     
            if self._instantiate_memories:
                delayed_user_input_suffix = "_" + "d"*self._user_port_input_pipeline if self._user_port_input_pipeline != 0 else ""
           
                hdl += f'    mem{element}_inst : xpm_memory_tdpram\n'
                hdl += f'        generic map (\n'
                hdl += f'           ADDR_WIDTH_A            => {controller_address_bits-log2_elements-controller_unused_bits},\n'
                hdl += f'           ADDR_WIDTH_B            => {log2_mem_depth},\n'
                hdl += f'           AUTO_SLEEP_TIME         => 0,\n'
                hdl += f'           BYTE_WRITE_WIDTH_A      => 8,\n'
                hdl += f'           BYTE_WRITE_WIDTH_B      => 8,\n'
                hdl += f'           CASCADE_HEIGHT          => 0,\n'
                hdl += f'           CLOCKING_MODE           => "{"common_clock" if self._synchronous else "independent_clock"}",\n'
                hdl += f'           ECC_MODE                => "no_ecc",\n'
                hdl += f'           MEMORY_INIT_FILE        => "none",\n'
                hdl += f'           MEMORY_INIT_PARAM       => "0",\n'
                hdl += f'           MEMORY_OPTIMIZATION     => "true",\n'
                hdl += f'           MEMORY_PRIMITIVE        => "{self._primitive}",\n'
                hdl += f'           MEMORY_SIZE             => {self._size_bits},\n'
                hdl += f'           MESSAGE_CONTROL         => 0,\n'
                hdl += f'           READ_DATA_WIDTH_A       => {self._controller_width},\n'
                hdl += f'           READ_DATA_WIDTH_B       => {self._width},\n'
                hdl += f'           READ_LATENCY_A          => {1 + self._controller_port_output_pipeline},\n'
                hdl += f'           READ_LATENCY_B          => {1 + self._user_port_output_pipeline},\n'
                hdl += f'           READ_RESET_VALUE_A      => "0",\n'
                hdl += f'           READ_RESET_VALUE_B      => "0",\n'
                hdl += f'           RST_MODE_A              => "SYNC",\n'
                hdl += f'           RST_MODE_B              => "SYNC",\n'
                hdl += f'           SIM_ASSERT_CHK          => 0,\n'
                hdl += f'           USE_EMBEDDED_CONSTRAINT => 0,\n'
                hdl += f'           USE_MEM_INIT            => 1,\n'
                hdl += f'           USE_MEM_INIT_MMI        => 0,\n'
                hdl += f'           WAKEUP_TIME             => "disable_sleep",\n'
                hdl += f'           WRITE_DATA_WIDTH_A      => {self._controller_width},\n'
                hdl += f'           WRITE_DATA_WIDTH_B      => {self._width},\n'
                hdl += f'           WRITE_MODE_A            => "no_change",\n'
                hdl += f'           WRITE_MODE_B            => "no_change",\n'
                hdl += f'           WRITE_PROTECT           => 1\n'
                hdl += f'        )\n'
                hdl += f'        port map (\n'
                hdl += f'           clka   => s_axi_aclk,\n'
                hdl += f'           addra  => controller_addr{delayed_controller_input_suffix}({controller_address_bits-log2_elements-1} downto {controller_unused_bits}),\n'
                hdl += f'           douta  => controller_mem{element}_rddata,\n'
                hdl += f'           dina   => controller_wrdata{delayed_controller_input_suffix},\n'
                hdl += f'           ena    => controller_mem{element}_en_gated{delayed_controller_input_suffix},\n'
                hdl += f'           regcea => \'1\',\n'
                hdl += f'           rsta   => \'0\',\n'
                hdl += f'           wea    => controller_we{delayed_controller_input_suffix},\n\n'
                
                hdl += f'           clkb   => {"s_axi_aclk" if self._synchronous else f"mem{element}_clk"},\n'
                hdl += f'           addrb  => mem{element}_addr{delayed_user_input_suffix},\n'
                hdl += f'           doutb  => mem{element}_dout_int,\n'
                if self._read_only:
                    hdl += f'           dinb   => "{"0"*self._width}",\n'
                else:
                    hdl += f'           dinb   => mem{element}_din{delayed_user_input_suffix},\n'
                hdl += f'           enb    => \'1\',\n'
                hdl += f'           regceb => \'1\',\n'
                hdl += f'           rstb   => \'0\',\n'
                    
                if self._read_only:
                    hdl += f'           web    => "{"0"*(self._width // 8)}",\n'
                else:
                    for i in range(self._width // 8):
                        hdl += f'           web({i}) => mem{element}_we{delayed_user_input_suffix},\n'
                        
                hdl += '\n'
                hdl += f'           dbiterra => open,\n'
                hdl += f'           dbiterrb => open,\n'
                hdl += f'           sbiterra => open,\n'
                hdl += f'           sbiterrb => open,\n'
                hdl += f'           injectdbiterra => \'0\',\n'
                hdl += f'           injectdbiterrb => \'0\',\n'
                hdl += f'           injectsbiterra => \'0\',\n'
                hdl += f'           injectsbiterrb => \'0\',\n'
                hdl += f'           sleep => \'0\'\n'
                hdl += f'        );\n\n'
            else:
                hdl += f'    mem{element}_addr  <= controller_addr{delayed_controller_input_suffix}({controller_address_bits-log2_elements-1} downto {controller_unused_bits});\n'
                hdl += f'    controller_mem{element}_rddata <= mem{element}_dout;\n'
                hdl += f'    mem{element}_din   <= controller_wrdata{delayed_controller_input_suffix};\n'
                hdl += f'    mem{element}_en    <= controller_mem{element}_en_gated{delayed_controller_input_suffix};\n'
                hdl += f'    mem{element}_we    <= controller_we{delayed_controller_input_suffix};\n'
                if not self._synchronous:
                    hdl += f'    mem{element}_clk    <= s_axi_aclk;\n'
            
        hdl += f'end rtl;\n\n'
        
        return hdl
    
    def generate_ip_tcl(self, project_dir):
        """
        Generate TCL commands to create the IP and add it to the project.

        :param project_dir: The directory in which the project is located,
        needed for generating IP files into the correct locations.
        :type project_dir: str
        """

        ip_name = self._module_name + "_ip"
        s = ''
        s += (f'create_ip'
                f' -name axi_bram_ctrl'
                f' -vendor xilinx.com'
                f' -library ip'
                f' -version 4.1'
                f' -module_name'
                f' {ip_name}\n')
        s += ('set_property -dict [list'
                f' CONFIG.DATA_WIDTH {{{self._controller_width}}}'
                f' CONFIG.MEM_DEPTH {{{self._elements*self._size_bits // self._controller_width}}}'
                f' CONFIG.SINGLE_PORT_BRAM {{1}}'
                f' CONFIG.ID_WIDTH {{{self._axi_id_width}}}'
                f' CONFIG.ECC_TYPE {{0}}'
                f' CONFIG.Component_Name {{{ip_name}}}'
                f' CONFIG.READ_LATENCY {{{self._controller_port_input_pipeline + self._controller_port_output_pipeline + 1}}}'
                f' CONFIG.RD_CMD_OPTIMIZATION {{0}}]'
                f' [get_ips {ip_name}]\n')
        xci_path = os.path.join(project_dir, f"acadia.srcs/sources_1/ip/{ip_name}/{ip_name}.xci") 
        simlib_path = os.path.join(project_dir, "acadia.cache/compile_simlib")
        
        s += f'generate_target {{instantiation_template}} [get_files {xci_path}]\n'
        s += f'generate_target all [get_files {xci_path}]\n'
        s += f'catch {{ config_ip_cache -export [get_ips -all {ip_name}] }}\n'
        s += f'export_ip_user_files -of_objects [get_files {xci_path}] -no_script -sync -force -quiet\n'
        s += f'set_property GENERATE_SYNTH_CHECKPOINT 0 [get_files {xci_path}]\n'
        
        # s += f'create_ip_run [get_files -of_objects [get_fileset sources_1] {xci_path}] -force\n'
        # s += f'launch_runs {ip_name}_synth_1 -jobs {self._synth_jobs}\n'
        s += (f'export_simulation'
                f' -of_objects [get_files {xci_path}]'
                f' -directory {os.path.join(project_dir, "acadia.ip_user_files/sim_scripts")}'
                f' -ip_user_files_dir {os.path.join(project_dir, "acadia.ip_user_files")}'
                f' -ipstatic_source_dir {os.path.join(project_dir, "acadia.ip_user_files/ipstatic")}')
        s += f' -lib_map_path [list'
        for lib in ["modelsim", "questa", "ies", "xcelium", "vcs", "riviera"]:
            s += f' {{{lib}={os.path.join(simlib_path, lib)}}}'
        s += f'] -use_ip_compiled_libs -force -quiet\n'
        
        return s
    
class BusGTY:
    """
    A bus-controlled interface to the GTY transceivers.
    """
    pass

    # create_ip -name gtwizard_ultrascale -vendor xilinx.com -library ip -version 1.7 -module_name gtwizard_ultrascale_0
    # set_property -dict [list 
    # CONFIG.INS_LOSS_NYQ {0} CONFIG.TX_LINE_RATE {10} CONFIG.TX_REFCLK_FREQUENCY {250} CONFIG.TX_DATA_ENCODING {8B10B} CONFIG.TX_USER_DATA_WIDTH {32} CONFIG.TX_INT_DATA_WIDTH {40} CONFIG.TX_BUFFER_MODE {0} CONFIG.TX_OUTCLK_SOURCE {TXPROGDIVCLK} CONFIG.TX_DIFF_SWING_EMPH_MODE {CUSTOM} CONFIG.RX_LINE_RATE {10} CONFIG.RX_REFCLK_FREQUENCY {250} CONFIG.RX_DATA_DECODING {8B10B} CONFIG.RX_INT_DATA_WIDTH {40} CONFIG.RX_BUFFER_MODE {0} CONFIG.RX_JTOL_FC {5.9988002} CONFIG.RX_TERMINATION {FLOAT} CONFIG.RX_COUPLING {DC} CONFIG.RX_REFCLK_SOURCE {X0Y4 clk1} CONFIG.TX_REFCLK_SOURCE {X0Y4 clk1} CONFIG.RX_RECCLK_OUTPUT {X0Y4 clk0} CONFIG.TXPROGDIV_FREQ_VAL {250} CONFIG.FREERUN_FREQUENCY {250} CONFIG.LOCATE_TX_USER_CLOCKING {CORE} CONFIG.LOCATE_RX_USER_CLOCKING {CORE} CONFIG.RX_COMMA_PRESET {K28.5} CONFIG.RX_COMMA_P_ENABLE {true} CONFIG.RX_COMMA_M_ENABLE {true} CONFIG.RX_COMMA_DOUBLE_ENABLE {false} CONFIG.RX_COMMA_MASK {1111111111} CONFIG.RX_COMMA_ALIGN_WORD {4} CONFIG.RX_COMMA_SHOW_REALIGN_ENABLE {false}] [get_ips gtwizard_ultrascale_0]
    # generate_target {instantiation_template} [get_files /home/billy/acadia-build/acadia.srcs/sources_1/ip/gtwizard_ultrascale_0/gtwizard_ultrascale_0.xci]
    # generate_target all [get_files  /home/billy/acadia-build/acadia.srcs/sources_1/ip/gtwizard_ultrascale_0/gtwizard_ultrascale_0.xci]
    # catch { config_ip_cache -export [get_ips -all gtwizard_ultrascale_0] }
    # export_ip_user_files -of_objects [get_files /home/billy/acadia-build/acadia.srcs/sources_1/ip/gtwizard_ultrascale_0/gtwizard_ultrascale_0.xci] -no_script -sync -force -quiet
    # create_ip_run [get_files -of_objects [get_fileset sources_1] /home/billy/acadia-build/acadia.srcs/sources_1/ip/gtwizard_ultrascale_0/gtwizard_ultrascale_0.xci]
    # launch_runs gtwizard_ultrascale_0_synth_1 -jobs 16
    # export_simulation -of_objects [get_files /home/billy/acadia-build/acadia.srcs/sources_1/ip/gtwizard_ultrascale_0/gtwizard_ultrascale_0.xci] -directory /home/billy/acadia-build/acadia.ip_user_files/sim_scripts -ip_user_files_dir /home/billy/acadia-build/acadia.ip_user_files -ipstatic_source_dir /home/billy/acadia-build/acadia.ip_user_files/ipstatic -lib_map_path [list {modelsim=/home/billy/acadia-build/acadia.cache/compile_simlib/modelsim} {questa=/home/billy/acadia-build/acadia.cache/compile_simlib/questa} {ies=/home/billy/acadia-build/acadia.cache/compile_simlib/ies} {xcelium=/home/billy/acadia-build/acadia.cache/compile_simlib/xcelium} {vcs=/home/billy/acadia-build/acadia.cache/compile_simlib/vcs} {riviera=/home/billy/acadia-build/acadia.cache/compile_simlib/riviera}] -use_ip_compiled_libs -force -quiet

