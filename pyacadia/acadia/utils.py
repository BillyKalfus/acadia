def next_highest_power_of_2(num, log=False):
    """
    Given an unsigned integer `num`, returns the smallest power of 2 greater than of equal to `num`. Optionally, it can return the base-2 log of this number instead, representing the number of bits needed to store `num`.
    :param num: Search limit
    :type num: int
    :param log: If `True`, returns the base-2 log of the integer.
    """
    i = 0
    while (1 << i) < num:
        i += 1
    return (i if log else (1 << i))

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