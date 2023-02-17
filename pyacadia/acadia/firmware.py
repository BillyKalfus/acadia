__all__ = ["Firmware"]

import os
from . import hdl
from .utils import connect_bd_net, connect_bd_intf_net, create_ip, create_module, create_concatenator, create_slice, set_property, assign_bd_address, exclude_bd_addr_seg, next_highest_power_of_2

class Firmware(object):
    
    def __init__(self, project_dir=None):
        """
        Initializes the object with a path to a temporary directory for
        building the firmware image.
        
        :param project_dir: Directory in which to generate the project and all
        associated files.
        :type project_dir: `str`
        """
        self._modules = []
        self._project_dir = project_dir
        self._hdl_filename = None
        self._hedgehog_tcl_filename = None
        self._hedgehog_constraints = []
        
        if project_dir is not None and not os.path.exists(project_dir):
            os.mkdir(project_dir)
            
    def items(self):
        """
        :return: A `list` of all contained :class:`hdl.HDLModule` objects.
        :rtype: `list` of :class:`hdl.HDLModule`
        """
        return self._modules
    
    def keys(self):
        """
        :return: A `list` of all module names, as extracted by accessing the 
        `name` attribute of the :class:`hdl.HDLModule` objects.
        :rtype: `list` of strings
        """
        return [m.name for m in self._modules]
    
    def __iter__(self):
        """
        :return: An iterator over the names of modules contained in the firmware.
        """
        return iter(self.keys())
            
    def __getitem__(self, key):
        for m in self._modules:
            if m.name == key:
                return m
            
        raise KeyError(f"No module found in AcadiaFirmware object with name {key}.")
            
    def add(self, value):
        """
        Adds an HDL module to the firmware image.
        """
        if not isinstance(value, hdl.HDLModule):
            raise TypeError("Only hdl.HDLModules can be added to the firmware.")
            
        self._modules.append(value)
            
    def write_hdl(self, filename="python_modules.vhd"):
        """
        Writes a VHDL file containing the address decoding for the HEDGEHOG bus.
        Child classes should override this function to add custom HDL, if not included in the initializer.
        :param filename: The name of the file in the project directory in which to write the file.
        :type filename: str, optional
        """
        self._hdl_filename = os.path.join(self._project_dir, filename)
        
        with open(self._hdl_filename, "w") as f:
            for module in self._modules:
                f.write(module.generate_hdl() + '\n')
    
    def write_hedgehog_tcl(self, filename="hedgehog.tcl"):
        """
        Writes a TCL script to populate the HEDGEHOG logic.
        Child classes should override this function to implement unique functionality.
        :param filename: The name of the file in the project directory in which to write the file.
        :type filename: str, optional
        """
        self._hedgehog_tcl_filename = os.path.join(self._project_dir, filename)
        with open(self._hedgehog_tcl_filename, "w") as f:
            # Read the VHDL file containing our custom modules
            f.write(f"read_vhdl {self._hdl_filename}\n")
            
    def write_hedgehog_constraints(self, filename="hedgehog.xdc"):
        """
        Writes a TCL script to populate a constraints file for the HEDGEHOG logic.
        Child classes should override this function to implement unique functionality.
        :param filename: The name of the file in the project directory in which to write the file.
        :type filename: str, optional
        """
        self._hedgehog_tcl_filename = os.path.join(self._project_dir, filename)
        
        with open(self._hedgehog_tcl_filename, "w") as f:
            # Read the VHDL file containing our custom modules
            for constraint in self._hedgehog_constraints:
                f.write(f"{constraint}\n")
