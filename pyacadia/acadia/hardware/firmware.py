import os
import numpy as np

class Firmware(object):
    
    def __init__(self, project_dir="/tmp"):
        """
        Initializes the object with a path to a temporary directory for building the firmware image.
        :param project_dir: Directory in which to generate the project and all associated files.
        """
        self._modules = []
        self._project_dir = project_dir
        self._hdl_filename = None
        self._hedgehog_tcl_filename = None
        
        if not os.path.exists(project_dir):
            os.mkdir(project_dir)
            
    def items(self):
        """
        :return: A `list` of all contained :class:`HDLModule` objects.
        :rtype: `list` of :class:`HDLModule`
        """
        return self._modules
    
    def keys(self):
        """
        :return: A `list` of all module names, as extracted by accessing the `name` attribute of the :class:`HDLModule` objects.
        :rtype: `list` of strings
        """
        return [m.name for m in self._modules]
    
    def __iter__(self):
        """
        :return: An iterator over the result of :
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
        if not isinstance(value, HDLModule):
            raise TypeError("Only HDLModules can be added to the firmware.")
            
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
        Writes a TCL script to populate the HEDGEHOG logic in the standard image.
        Child classes should override this function to implement unique functionality.
        :param filename: The name of the file in the project directory in which to write the file.
        :type filename: str, optional
        """
        self._hedgehog_tcl_filename = os.path.join(self._project_dir, filename)
        
    
    
        