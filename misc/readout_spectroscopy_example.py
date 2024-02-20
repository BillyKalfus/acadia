%matplotlib widget
from acadia.runtimes.cmacc_spectroscopy import CMACCSpectroscopyRuntime
import numpy as np
import logging
rt = CMACCSpectroscopyRuntime(frequencies=np.linspace(9.21e9, 9.23e9, 101),
                         DAC=4,
                         ADC=4, 
                         stimulus_ramp_time=1e-6,
                         stimulus_constant_time=255e-6,
                         stimulus_amplitude=1,
                         stimulus_NZ=2,
                         capture_delay=224e-9,
                         plot_electrical_delay=105e-9,
                         plot_unwrap_phase=True)
rt.deploy("192.168.2.70", log_level=logging.DEBUG)