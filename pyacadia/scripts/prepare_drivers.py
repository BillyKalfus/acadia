import os
import re
import shutil
import sys
import pathlib
from cffi import FFI

EMBEDDEDSW = "/media/sd-mmcblk0p1/embeddedsw-master"
PACKAGE_DIR = "/usr/lib/python3.7/site-packages"

HEADERS = {"rfdc": '#include "xrfdc.h"\n'
                   '#include <metal/sys.h>\n'
                   'u32 metal_init_METAL_INIT_DEFAULTS() { struct metal_init_params init_param = METAL_INIT_DEFAULTS; return metal_init(&init_param); }\n'
                   'u32 def_XRFDC_BLOCK_BASE(u32 type, u32 tile, u32 block) { return XRFDC_BLOCK_BASE(type, tile, block); }\n'
                   'void XRFdc_WriteReg16Wrapper(XRFdc* InstancePtr, u32 BaseAddress, u32 RegOffset, u32 RegisterValue) { XRFdc_WriteReg16(InstancePtr, BaseAddress, RegOffset, RegisterValue); }',
           "rfclk": '#include "xrfclk.h"\n'}

# We need to do some tricks to get the directory of embeddedsw, because the 
# CFFI compiler requires a relative path for the 
current_path = str(pathlib.Path().resolve())
root_distance = current_path.count("/")
src_dirs = {"rfdc": "../"*root_distance + f"{EMBEDDEDSW}/XilinxProcessorIPLib/drivers/rfdc/src",
            "rfclk": "../"*root_distance + f"{EMBEDDEDSW}/XilinxProcessorIPLib/drivers/board_common/src/rfclk/src"}
script_dir = pathlib.Path(__file__).parent.resolve()

for lib,src_dir in src_dirs.items():
    ffibuilder = FFI()
    
    with open(os.path.join(script_dir, f"{lib}_functions.h")) as f:
        ffibuilder.cdef(f.read())
    
    ffibuilder.set_source(f"pyx{lib}", 
                          HEADERS[lib], 
                          sources=[os.path.join(src_dir, f) for f in os.listdir(src_dir) if ".c" in f], 
                          libraries=["metal"], 
                          include_dirs=[src_dir], 
                          extra_compile_args=["-Wall", "-fPIC"])

    ffibuilder.compile(verbose=True)
    
# Copy the compiled libraries into a directory where Python will find them
for f in os.listdir(current_path):
    if f.endswith(".so"):
        shutil.copy2(os.path.join(current_path, f), PACKAGE_DIR)