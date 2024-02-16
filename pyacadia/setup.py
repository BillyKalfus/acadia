from setuptools import setup, find_packages, Extension
import platform

ps_functions_module = Extension("acadia.ps_functions",
                                sources=["drivers/ps_functions.c", "drivers/ps_functions_py.c"],
                                libraries=["pthread"])
                
setup (name = 'pyacadia',
       version = '3.0',
       description = 'Assembler, hardware interface, and firmware management for the Acadia quantum control system.',
       author = 'William Kalfus',
       author_email = 'william.kalfus@yale.edu',
       packages=find_packages(),
       ext_modules=([ps_functions_module] if platform.processor() == "aarch64" else []),
       extras_require={
          'host': ['jupyter', 'ipywidgets', 'ipython', 'ipympl', 'tqdm', 'scipy']
      })