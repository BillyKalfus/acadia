__all__ = ["HDLModule", "BusDevice", "BusDataport", "BusDecoder", "BusDatamoverController"]

from .compiler import Symbol
from .utils import next_highest_power_of_2

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

class BusDevice():
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
    
    INPUT = "in"
    OUTPUT = "out"
    GATE_RESET = 1
    GATE_REGCE = 2
    
    def __init__(self, name, ports, bus_data_bits=32, bus_addr_bits=32):
        """
        A module to split the data signals of a memory bus port. Optionally,
        the output signals may be gated by the memory enable signal to either 
        be reset when not enabled, or latched when not written.
        :param name: name of the module
        :type name: str
        :param ports: List of ports 
        :type ports: `list` of `dict`, where each element specifies a port. 
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
        
        # Make the delayed enable signals
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
        
        # Delay the enable signals
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
        if isinstance(obj, BusDevice):
            if obj.bus_data_bits != self.bus_data_bits:
                raise ValueError("Connected BusDevices and BusDecoders must have the same number of bits in a data word.")
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
            hdl += f'        {obj.name}_mosi : out std_logic_vector({self.bus_data_bits-1} downto 0);\n'
            hdl += f'        {obj.name}_miso : in  std_logic_vector({self.bus_data_bits-1} downto 0);\n'
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
            hdl += f'    -- {obj.name} interface (local bus address 0x{obj.address().value()-self.address().value():08X}), (global bus address 0x{obj.address().value():08X})\n'         
            hdl += f'    {obj.name}_clk  <= master_bus_clk;\n\n'
            if pipeline:
                hdl += f'    {obj.name}_proc: process(master_bus_clk) begin\n'
                hdl += f'        if rising_edge(master_bus_clk) then\n'
                hdl += f'            {obj.name}_mosi <= master_bus_mosi;\n'
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
                hdl += f'    {obj.name}_mosi <= master_bus_mosi;\n'
                hdl += f'    {obj.name}_addr <= master_bus_addr({low_address_bit-1} downto 0);\n'
                hdl += f'    {obj.name}_wr   <= master_bus_wr when to_integer(unsigned(master_bus_addr({region_bits}))) = {i} else \'0\';\n'
                hdl += f'    {obj.name}_en   <= master_bus_en when to_integer(unsigned(master_bus_addr({region_bits}))) = {i} else \'0\';\n'
            

        hdl += f'end rtl;\n'
        
        return hdl
    
class BusDataMoverController(BusDevice, HDLModule):
        
    def __init__(self, name, datamovers, addr_bits, bus_data_bits=32, bus_addr_bits=32):
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
            return self + 4*key
        elif isinstance(key, str):
            return self + 4*self.datamovers.index(key)
        else:
            raise TypeError(f"Incompatible type for key {key}")
        
    def generate_hdl(self):
        if not self.address_assigned():
            raise ValueError("Device must be assigned before generating HDL.")
            
        num_ports = next_highest_power_of_2(self.size)
        bus_addr_bits = next_highest_power_of_2(num_ports, log=True)
        
        # Throw an error if a smarter strategy is needed
        if num_ports > (2**self.bus_addr_bits):
            raise ValueError(f"Too many devices on the bus to be allocated (attempted to allocate {num_ports} devices with a max size of {max_size}).")
            
        # Finally, write the HDL for the decoder
        hdl = f'library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;\nuse IEEE.NUMERIC_STD.ALL;\n\n'
        hdl += f'entity {self.name} is\n'
        hdl += f'    port (\n'
        hdl += f'        clk  : in std_logic;\n'
        hdl += f'        nrst : in std_logic;\n\n'
        hdl += f'        -- Slave interface\n'
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