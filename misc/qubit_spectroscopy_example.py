%matplotlib widget
from acadia.runtimes.qubit_spectroscopy import QubitSpectroscopyRuntime
import numpy as np
import logging
rt = QubitSpectroscopyRuntime(qubit_frequencies=np.linspace(4.401e9, 4.451e9, 51),
                              qubit_DAC=3,
                              qubit_stimulus_ramp_time=1e-6,
                              qubit_stimulus_constant_time=255e-6,
                              qubit_stimulus_NZ=2,
                            readout_DAC=1,
                            readout_ADC=1, 
                            readout_frequency=4.45e9,
                            readout_stimulus_ramp_time=1e-6,
                            readout_stimulus_constant_time=255e-6,
                            readout_stimulus_amplitude=1,
                            readout_stimulus_NZ=2,
                            readout_capture_delay=224e-9,
                            plot_unwrap_phase=False)
rt.deploy("192.168.2.69", log_level=logging.DEBUG)