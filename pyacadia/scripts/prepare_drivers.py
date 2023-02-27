from cffi import FFI
import os
import re

EMBEDDEDSW = "../../../embeddedsw-master"

SRC_DIRS = {"rfdc": f"{EMBEDDEDSW}/XilinxProcessorIPLib/drivers/rfdc/src",
            "rfclk": f"{EMBEDDEDSW}/XilinxProcessorIPLib/drivers/board_common/src/rfclk/src"}

HEADERS = {"rfdc": '#include "xrfdc.h"\n'
                   '#include <metal/sys.h>\n'
                   'void INITIALIZE_METAL_INIT_DEFAULTS(struct metal_init_params* p) { *p = METAL_INIT_DEFAULTS; }\n'
                   'u32 DEF_XRFDC_BLOCK_BASE(u32 type, u32 tile, u32 block) { return XRFDC_BLOCK_BASE(type, tile, block); }\n'
                   'void XRFdc_WriteReg16Wrapper(xRFdc* InstancePtr, u32 BaseAddress, u32 RegOffset, u32 RegisterValue) { XRFdc_WriteReg16(InstancePtr, BaseAddress, RegOffset, RegisterValue); }',
           "rfclk": '#include "xrfclk.h"\n'}


for lib,src_dir in SRC_DIRS.items():
    ffibuilder = FFI()
    
    with open(f"{lib}_functions.h") as f:
        ffibuilder.cdef(f.read(), packed=True)
    
    ffibuilder.set_source(f"pyx{lib}", 
                          HEADERS[lib], 
                          sources=[os.path.join(src_dir, f) for f in os.listdir(src_dir) if ".c" in f], 
                          libraries=["metal"], 
                          include_dirs=[src_dir], 
                          extra_compile_args=["-Wall", "-fPIC"])

    ffibuilder.compile(verbose=True)