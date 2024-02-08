from dataclasses import dataclass

import numpy as np

from acadia.runtime import Runtime, PyPlotRuntimeComponent, CounterRuntimeComponent
from acadia.data import DataManager, ArrayRecordGroup

class LoopbackPlot(PyPlotRuntimeComponent):
    """
    A custom record group for collecting the results of the 
    :class:`LoopbackRuntime` and displaying them in a plot.
    """

    def create_plot(self):
        self.figure().set_size_inches(6,4) 
        self.ax = self.figure().add_subplot()
        self.line_re = self.ax.plot([], [], animated=False)
        self.line_im = self.ax.plot([], [], animated=False)
        self.ax.set_ylim(-0.05, 0.05)
        self.ax.grid()
    
    def update_plot(self):
        import numpy as np
        from acadia.arrays import Waveform

        if "traces" in self.runtime.data and self.runtime.data["traces"].records() is not None:
            records = self.runtime.data["traces"].records()
            if not hasattr(self, "axis"):
                num_samples = records.shape[-1]
                capture_time = self.runtime.data["traces"].metadata()["capture_time"]
                self.axis = np.linspace(0, capture_time, num_samples)
                self.ax.set_xlim(self.axis[0]*1e6, self.axis[-1]*1e6)

            # Just plot only the most recently received trace
            trace = Waveform.to_complex(records[-1,:])
            PyPlotRuntimeComponent.update_line(self.line_re, self.axis*1e6, np.real(trace))
            PyPlotRuntimeComponent.update_line(self.line_im, self.axis*1e6, np.imag(trace))
    
@dataclass           
class LoopbackRuntime(Runtime):
    """
    A :class:`Runtime` for synthesizing a signal on a DAC and capturing it on
    an ADC.
    """

    # DAC channel used for stimulus
    DAC: int 
    
    # ADC channel for capture
    ADC: int 

    # frequency to synthesize
    frequency: float
    
    # Length of the stimulus signal flat top in seconds
    stimulus_constant_time: float 
    
    # Length of the stimulus signal ramp in seconds (Total)
    stimulus_ramp_time: float
    
    # DAC amplitude of stimulus
    stimulus_amplitude: complex = 1.0
    
    # DAC Nyquist zone (1 or 2)
    stimulus_NZ: int = 2
    
    # VOP setting for DAC (2250 - 40000)
    stimulus_VOP: int = 12000
    
    # Total length of the capture. If ``None``, will be set to stimulus_ramp_time + stimulus_flat_time
    capture_time: float = None

    # Number of times to run the sequence
    iterations: int = 100
    
    FILENAME = __file__

    def initialize(self) -> None:
        self.add_component(LoopbackPlot)
        self.add_component(CounterRuntimeComponent, "Iterations")
    
    def main(self, directory: str, datamanager: DataManager):
        import time
        from acadia.system import Acadia
        from acadia.arrays import Waveform, WindowedConstantWaveform
        
        acadia = Acadia()

        pulse_channel = acadia.DAC(self.DAC)
        pulse = WindowedConstantWaveform(pulse_channel, 
                                            constant_length_seconds=self.stimulus_constant_time,
                                            window_length_seconds=self.stimulus_ramp_time)

        capture_channel = acadia.ADC(self.DAC)
        capture_time = self.capture_time if self.capture_time is not None else self.stimulus_ramp_time + self.stimulus_constant_time
                        
        # We'll collect the data traces in a record group
        datamanager.create_group(ArrayRecordGroup, "traces", capture_time=capture_time)
        
        # Create a sequence for the sequencer
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                capture_data,_ = a.stream(capture_channel, length=capture_time, length_units="seconds")
                a.generate(pulse)

            return capture_data

        capture_data = acadia.compile(sequence)

        # Attach to the hardware
        acadia.attach()
        
        acadia.configure_clocks(reference="external")
        time.sleep(1)
        acadia.align_tile_latencies()
        time.sleep(1)

        # Load the wave memory with the pulse by calling the generator function
        pulse_complex = np.hanning(len(pulse)).astype(np.complex64)
        Waveform.from_complex(pulse_complex, pulse, scale=self.stimulus_amplitude)

        # Configure channel parameters
        pulse_channel.set_nyquist_zone(self.stimulus_NZ)
        pulse_channel.set_vop(self.stimulus_VOP)
        pulse_channel.configure_nco(update_source="sysref")
        capture_channel.configure_nco(update_source="sysref")
        acadia.update_nco_frequency(pulse_channel, frequency=self.frequency)
        acadia.update_nco_frequency(capture_channel, frequency=-self.frequency)
        pulse_channel.reset_nco_phase()
        capture_channel.reset_nco_phase()
        acadia.pulse_sysref(1)        
                
        for shot in datamanager.count(self.iterations, name="Iterations"):
            acadia.run(assemble=(shot==0))
            datamanager.write("traces", capture_data)
