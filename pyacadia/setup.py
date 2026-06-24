import os
from setuptools import setup, find_packages, Extension
import importlib.util
import subprocess
import sysconfig

NUMPY_REQUIREMENT = "numpy==1.26.0"

utils_sources = []
for filename in os.listdir("acadia/utils"):
    if filename.endswith(".c"):
        utils_sources += [os.path.join("acadia/utils", filename)]

utils_module = Extension("acadia.utils", sources=utils_sources)

result = subprocess.run("lscpu | grep Cortex-A53", shell=True)
on_rfsoc = result.returncode == 0

# Find NumPy's C headers without importing numpy, since importing it here can
# break in some Python/virtualenv combinations. Under PEP 517 build isolation,
# NumPy is installed in the build environment rather than sysconfig's platlib.
def get_numpy_include_dir():
    spec = importlib.util.find_spec("numpy")
    if spec is not None and spec.origin:
        numpy_root = os.path.dirname(spec.origin)
        include_dir = os.path.join(numpy_root, "core", "include")
        if os.path.isdir(include_dir):
            return include_dir

    return os.path.join(sysconfig.get_path("platlib"), "numpy", "core", "include")


numpy_include_dir = get_numpy_include_dir()

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
       version = '8.0',
       description = 'Assembler, hardware interface, and firmware management for the Acadia quantum control system.',
       author = 'William Kalfus',
       author_email = 'william.kalfus@yale.edu',
       packages=find_packages(),
       ext_modules=[data_module, rfdc_module, rfclk_module, utils_module],
       install_requires=[NUMPY_REQUIREMENT],
       extras_require={
          'host': ['jupyter', 'ipywidgets', 'ipython', 'ipympl', 'tqdm', 'scipy', NUMPY_REQUIREMENT, 'lmfit']
      })
