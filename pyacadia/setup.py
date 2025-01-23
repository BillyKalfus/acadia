import os
from setuptools import setup, find_packages, Extension
import subprocess
import numpy as np

utils_sources = []
for filename in os.listdir("acadia/utils"):
    if filename.endswith(".c"):
        utils_sources += [os.path.join("acadia/utils", filename)]

utils_module = Extension("acadia.utils", sources=utils_sources)

result = subprocess.run("lscpu | grep Cortex-A53", shell=True)
on_rfsoc = result.returncode == 0
if not on_rfsoc:
    requirements = ["numpy"]

data_module = Extension("acadia.data",
                        sources=["acadia/data/io.c",
                                 "acadia/data/recordgroup.c", 
                                 "acadia/data/datamanager.c",
                                 "acadia/data/data_py.c"],
                        include_dirs=[np.get_include()])


rfdc_libraries = ["metal"] if on_rfsoc else []
    
rfdc_sources = []
for filename in os.listdir("acadia/rfdc"):
    if filename.endswith(".c"):
        rfdc_sources += [os.path.join("acadia/rfdc", filename)]

rfdc_module = Extension("acadia.rfdc",
                        sources=rfdc_sources,
                        libraries=rfdc_libraries)

rfclk_module = Extension("acadia.rfclk",
    sources=["acadia/rfclk/xrfclk.c", "acadia/rfclk/rfclk_py.c"])
                
setup (name = 'pyacadia',
       version = '7.0',
       description = 'Assembler, hardware interface, and firmware management for the Acadia quantum control system.',
       author = 'William Kalfus',
       author_email = 'william.kalfus@yale.edu',
       packages=find_packages(),
       ext_modules=[data_module, rfdc_module, rfclk_module, utils_module],
       extras_require={
          'host': ['jupyter', 'ipywidgets', 'ipython', 'ipympl', 'tqdm', 'scipy', 'numpy', 'lmfit']
      })