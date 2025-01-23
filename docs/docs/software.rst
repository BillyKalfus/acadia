 Software Infrastructure
=========================

It would be highly cumbersome to have to write low-level machine code to program hardware for a measurement. Therefore, a comprehensive software stack has been developed that allows the system to be programmed using high-level commands directly in Python. While much of the functionality of the stack is described in the docstrings of its functions, herein we provide a general overview of the stack to help orient you when navigating the sea of files and functions.

 Hardware Interface Layer
--------------------------

 Compiler Utility Layer
------------------------

 Hardware Primitive Objects
----------------------------

 Waveform Abstractions
-----------------------
 
 Acadia System Abstraction
---------------------------

 Runtime Framework
-------------------

 Programming Patterns and Recipes
==================================

In this section, we'll describe some common recipes and patterns that can be helpful when using the system. 

 Collecting and processing data
--------------------------------

 Branching and conditional execution
-------------------------------------

 Loops
-------

 Two pulses separated by a constant delay
------------------------------------------

It's a common design pattern in experiments to play a pulse, wait some time, and play another pulse. When the wait time is known ahead of time and is constant, it's recommended to use blank waveforms in a single synchronizer to separate the pulses, as this has the lowest minimum delay time (the same as for any waveform, since the "delay" is just a waveform). 

 Two pulses separated by a dynamic delay
-----------------------------------------
It's also desirable to be able to play a pulse and then wait for some amount of time that is determined at runtime, such as when it is loaded into cache by the PS. This can easily be done by using a synchronizer to play the first pulse, 