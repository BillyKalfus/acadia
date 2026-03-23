import os
from setuptools import setup, find_packages, Extension
import subprocess
import sysconfig

utils_sources = []
for filename in os.listdir("acadia/utils"):
    if filename.endswith(".c"):
        utils_sources += [os.path.join("acadia/utils", filename)]

utils_module = Extension("acadia.utils", sources=utils_sources)

result = subprocess.run("lscpu | grep Cortex-A53", shell=True)
on_rfsoc = result.returncode == 0

# For some reason importing numpy in this file breaks things in
# later version of Python and in virtual environments on WSL, 
# so we can't use the regular numpy get_include()
numpy_include_dir = os.path.join(sysconfig.get_path("platlib"), "numpy", "core", "include")

data_module = Extension("acadia.data",
                        sources=["acadia/data/io.c",
                                 "acadia/data/recordgroup.c", 
                                 "acadia/data/datamanager.c",
                                 "acadia/data/data_py.c"],
                        include_dirs=[numpy_include_dir])


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
       version = '9.0',
       description = 'Assembler, hardware interface, and firmware management for the Acadia quantum control system.',
       author = 'William Kalfus',
       author_email = 'william.kalfus@yale.edu',
       packages=find_packages(),
       ext_modules=[data_module, rfdc_module, rfclk_module, utils_module],
       extras_require={
          'host': ['jupyter', 'ipywidgets', 'ipython', 'ipympl', 'tqdm', 'scipy', 'numpy<2.0.0', 'lmfit']
      })
