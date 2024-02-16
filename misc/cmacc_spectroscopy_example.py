%matplotlib widget
from acadia.runtimes.cmacc_spectroscopy import CMACCSpectroscopyRuntime
import numpy as np
import logging
rt = CMACCSpectroscopyRuntime(frequencies=np.linspace(4.401e9, 4.451e9, 51),
                         DAC=1,
                         ADC=1, 
                         stimulus_ramp_time=1e-6,
                         stimulus_constant_time=255e-6,
                         stimulus_amplitude=1,
                         stimulus_NZ=2,
                         capture_delay=224e-9,
                         plot_unwrap_phase=False)
rt.deploy("192.168.2.69", log_level=logging.DEBUG)