%matplotlib widget
from acadia.runtimes.spectroscopy import SpectroscopyRuntime
import numpy as np
rt = SpectroscopyRuntime(frequencies=np.linspace(9.180e9, 9.240e9, 61),
                         DAC=4,
                         ADC=4, 
                         stimulus_ramp_time=1e-6,
                         stimulus_constant_time=255e-6,
                         stimulus_amplitude=1,
                         stimulus_NZ=2,
                         capture_decimation=0,
                         capture_delay=224e-9,
                         plot_unwrap_phase=False)
rt.deploy("192.168.2.70")