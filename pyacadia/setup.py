from setuptools import setup, find_packages, Extension
import subprocess
import numpy as np

ps_functions_module = Extension("acadia.ps_functions",
                                sources=["drivers/ps_functions.c", "drivers/ps_functions_py.c"],
                                libraries=["pthread"])

result = subprocess.run("lscpu | grep Cortex-A53", shell=True)
on_rfsoc = result.returncode == 0

data_module = Extension("acadia.data",
                        sources=["acadia/data/io.c",
                                 "acadia/data/recordgroup.c", 
                                 "acadia/data/datamanager.c",
                                 "acadia/data/data_py.c"],
                        include_dirs=[np.get_include()])
                        # extra_compile_args=['-fPIC', '-O0', '-g'],
                        # extra_link_args=['-O0', '-g'])
                
setup (name = 'pyacadia',
       version = '5.0',
       description = 'Assembler, hardware interface, and firmware management for the Acadia quantum control system.',
       author = 'William Kalfus',
       author_email = 'william.kalfus@yale.edu',
       packages=find_packages(),
       ext_modules=[data_module] + ([ps_functions_module] if on_rfsoc else []),
       extras_require={
          'host': ['jupyter', 'ipywidgets', 'ipython', 'ipympl', 'tqdm', 'scipy', 'numpy', 'lmfit']
      })