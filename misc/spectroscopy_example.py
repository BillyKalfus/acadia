%matplotlib widget
from acadia.runtimes.spectroscopy import SpectroscopyRuntime
import numpy as np
rt = SpectroscopyRuntime(frequencies=np.linspace(4.401e9, 4.451e9, 51),
                         DAC=1,
                         ADC=1, 
                         stimulus_ramp_time=1e-6,
                         stimulus_constant_time=0,
                         stimulus_amplitude=1,
                         stimulus_NZ=2,
                         capture_decimation=4,
                         capture_delay=224e-9,
                         plot_unwrap_phase=False)
rt.deploy("192.168.2.69")