from setuptools import setup, find_packages, Extension
import subprocess

ps_functions_module = Extension("acadia.ps_functions",
                                sources=["drivers/ps_functions.c", "drivers/ps_functions_py.c"],
                                libraries=["pthread"])

result = subprocess.run("lscpu | grep Cortex-A53", shell=True)
on_rfsoc = result.returncode == 0
                
setup (name = 'pyacadia',
       version = '4.2',
       description = 'Assembler, hardware interface, and firmware management for the Acadia quantum control system.',
       author = 'William Kalfus',
       author_email = 'william.kalfus@yale.edu',
       packages=find_packages(),
       ext_modules=([ps_functions_module] if on_rfsoc else []),
       extras_require={
          'host': ['jupyter', 'ipywidgets', 'ipython', 'ipympl', 'tqdm', 'scipy', 'numpy', 'lmfit']
      })