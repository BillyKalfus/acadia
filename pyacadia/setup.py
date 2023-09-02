from setuptools import setup, find_packages, Command, Extension
import platform
import os
import shutil
import pathlib
from cffi import FFI

# Install the RFDC drivers

class RFDCCommand(Command):
    """
    A custom setuptools command for installing the Xilinx RFDC drivers alongside the package.
    """

    EMBEDDEDSW = "/media/sd-mmcblk0p1/embeddedsw-master"
    RFDC_SUBDIR = "XilinxProcessorIPLib/drivers/rfdc/src"
    RFCLK_SUBDIR = "XilinxProcessorIPLib/drivers/board_common/src/rfclk/src"
    PACKAGE_DIR = "/usr/lib/python3.7/site-packages"

    HEADERS = {"rfdc": '#include "xrfdc.h"\n'
                       '#include <metal/sys.h>\n'
                       'u32 metal_init_METAL_INIT_DEFAULTS() { struct metal_init_params init_param = METAL_INIT_DEFAULTS; init_param.log_level = METAL_LOG_DEBUG; return metal_init(&init_param); }\n'
                       'u32 def_XRFDC_BLOCK_BASE(u32 type, u32 tile, u32 block) { return XRFDC_BLOCK_BASE(type, tile, block); }\n'
                       'void XRFdc_WriteReg16Wrapper(XRFdc* InstancePtr, u32 BaseAddress, u32 RegOffset, u32 RegisterValue) { XRFdc_WriteReg16(InstancePtr, BaseAddress, RegOffset, RegisterValue); }',
               "rfclk": '#include "xrfclk.h"\n'}
    
    user_options = []
    
    def initialize_options(self):
        pass
        
    def finalize_options(self):
        pass
    
    def run(self):
        # We need to do some tricks to get the directory of embeddedsw, because the 
        # CFFI compiler requires a relative path for the 
        current_path = str(pathlib.Path().resolve())
        root_distance = current_path.count("/")
        script_dir = pathlib.Path(__file__).parent.resolve()

        # Make FFI objects to build the two libraries separately
        rfdc_ffibuilder = FFI()
        rfclk_ffibuilder = FFI()

        # Read in the source
        with open(os.path.join(script_dir, f"drivers/rfdc_packed_structs.h")) as f:
            rfdc_ffibuilder.cdef(f.read(), pack=1)
            
        with open(os.path.join(script_dir, f"drivers/rfdc_functions.h")) as f:
            rfdc_ffibuilder.cdef(f.read())
            
        with open(os.path.join(script_dir, f"drivers/rfclk_functions.h")) as f:
            rfclk_ffibuilder.cdef(f.read())

        # Set sources and properties of the libraries
        for builder,lib,src_dir in [(rfdc_ffibuilder, "rfdc", f"{'../'*root_distance}{RFDCCommand.EMBEDDEDSW}/{RFDCCommand.RFDC_SUBDIR}"),
                                    (rfclk_ffibuilder, "rfclk", f"{'../'*root_distance}{RFDCCommand.EMBEDDEDSW}/{RFDCCommand.RFCLK_SUBDIR}")]:
            
            builder.set_source(f"pyx{lib}", 
                  RFDCCommand.HEADERS[lib], 
                  sources=[os.path.join(src_dir, f) for f in os.listdir(src_dir) if ".c" in f], 
                  libraries=["metal"], 
                  include_dirs=[src_dir], 
                  extra_compile_args=["-Wall", "-fPIC"])

            builder.compile(verbose=True)
        
        # Copy the compiled libraries into a directory where Python will find them
        for f in os.listdir(current_path):
            if f.endswith(".so"):
                shutil.copy2(os.path.join(current_path, f), RFDCCommand.PACKAGE_DIR)
                
ps_functions_module = Extension("acadia.ps_functions",
                                sources=["drivers/ps_functions.c", "drivers/ps_functions_py.c"],
                                libraries=["pthread"])
                
setup (name = 'pyacadia',
       version = '1.0',
       description = 'Assembler, hardware interface, and firmware management for the Acadia quantum control system.',
       author = 'William Kalfus',
       author_email = 'william.kalfus@yale.edu',
    #    cmdclass = {"install_drivers": RFDCCommand},
       packages=find_packages(),
       ext_modules=([ps_functions_module] if platform.processor() == "aarch64" else []))