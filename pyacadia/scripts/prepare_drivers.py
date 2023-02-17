from cffi import FFI
import os
import re

RFDC_SRC_DIR = "../../embeddedsw-master/XilinxProcessorIPLib/drivers/rfdc/src"

with open("rfdc_functions.h") as f:
    header = f.read()

ffibuilder = FFI()
ffibuilder.cdef(header)
ffibuilder.set_source("pyxrfdc", 
                      "\n".join(["#include \"xrfdc.h\""]), 
                      sources=[os.path.join(RFDC_SRC_DIR, f) for f in os.listdir(RFDC_SRC_DIR) if ".c" in f], 
                      libraries=["metal"], 
                      include_dirs=[RFDC_SRC_DIR], 
                      extra_compile_args=["-Wall", "-fPIC"])

ffibuilder.compile(verbose=True)