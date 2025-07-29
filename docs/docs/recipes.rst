======================
 Static Configuration
======================

Certain hardware settings are expected to be configured infrequently. These largely include clock settings, such as choice of reference clock source, tile sampling clocks, and internal clock distribution. Although we could reconfigure these every time we deploy a Runtime, the latency incurred quickly adds up. Therefore, we'll list a few examples of how to configure these settings by logging into the board.

 Choosing a clock source
-------------------------

It's often desirable to derive the system clocks from an external source, either for relating the frequencies among multiple instruments or for optimizing a phase noise profile. All system clocking is controlled by the CLK104 daughterboard, and more specifically the LMK04828 clock synthesizer on this board. The firmware expects a 10 MHz clock source, and the LMK04828 can use either the onboard crystal oscillator or a 10 MHz signal provided through the SMA connector labeled "REF IN".

By default, the `remote_install.sh` script configures the hardware to use the onboard crystal. When an external signal is plugged into the "REF IN" connector, the source switchover does NOT happen automatically. A command can be issued to the LMK04828 to switch its reference by accessing a Python shell on the board and issuing the following set of commands:

```
from acadia import Acadia
a = Acadia()
a.attach()
a.configure_clocks(reference="external")
a.reset_logic()
```

This code only needs to be run once; the use of the external source will persist until the board is restarted. In order to switch back to the internal source, run the same code but replace `"external"` with `"internal"` (or omit the keyword entirely). Note that after switching the clock source, the entire PL is reset; because of the clock disruption created by switching the source, in order for the logic to operate in a stable manner, it must be reset. 

 Changing the sampling rate
----------------------------

To optimize the location of Nyquist zone boundaries for filtering and power requirements, the high-frequency sampling rates of the DACs and ADCs can be changed from software. Note that the fabric interface rate (that is, the rate at which samples are provided to the RF tile from the FPGA or vice versa) is constant; the interpolation (or decimation) is adjusted to match the choice of sampling rate. Because there are only a handful of available interpolation (and decimation) rates available in the tiles, there is a finite set of sampling rates to choose from. In GS/s, the options for the DACs are: 0.8, 1.6, 2.4, 3.2, 4.0, 4.8, 6.4, 8.0, 9.6. For the ADCs, the options are: 0.8, 1.6, 2.4. Note that for any DAC sampling rates above 7.0 GS/s, the NCOs function differently and must be accounted for in the channel settings using the image-rejection (IMR) mode.

The sampling rate is a tile setting; all channels in a given tile share the same sampling clock signal, and therefore operate at the same sampling rate. The following code can be used to change the sampling rate for a tile:

```
from acadia import Acadia, rfdc

a = Acadia()
a.attach()
a.configure_clocks()
a.reset_logic()

rfdc.set_analog_sample_rate(tile="DACTile0", sample_frequency=6.4e9)
rfdc.startup()
```

This example sets the sampling rate of DAC tile 0 to 6.4 GS/s. To change the tile being configured or the frequency being set, modify the arguments to `set_analog_sample_rate` as necessary. As described in "Choosing a clock source", the keyword argument `reference="external"` should be passed to `a.configure_clocks()` if an external clock reference is to be used.  

==================================
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