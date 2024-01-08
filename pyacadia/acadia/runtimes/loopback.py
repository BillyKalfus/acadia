from dataclasses import dataclass

from acadia.runtime import Runtime
from acadia.data import DataManager, PlotMixin, ArrayRecordGroup

class LoopbackRecordGroup(ArrayRecordGroup, PlotMixin):
    """
    A custom record group for collecting the results of the 
    :class:`LoopbackRuntime` and displaying them in a plot.
    """
    
    def plot(self, fig):
        fig.set_size_inches(6,4) 
        ax = fig.add_subplot()
        (line_re,) = ax.plot([], [], animated=False)
        (line_im,) = ax.plot([], [], animated=False)
        ax.set_ylim(-0.05, 0.05)
        ax.set_xlim(0,5)
        ax.grid()
          
        def update(animation, framedata):
            import numpy as np
            from acadia.arrays import Waveform

            if self.records() is not None:
                # Just plot only the most recently received trace
                axis = self.axis()
                sample_rate = 1 / (axis[1] - axis[0])
                trace = Waveform(sample_rate_or_channel=sample_rate, 
                                 data=self.records()[-1,:]).unpack()
                
                line_re.set_data(axis*1e6, np.real(trace))
                line_im.set_data(axis*1e6, np.imag(trace))
        
        return update

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
    iterations: int = 1000
    
    FILENAME = __file__
    
    def main(self, directory: str, datamanager: DataManager):
        import time
        import numpy as np
        from acadia.system import Acadia
        from acadia.arrays import Waveform, WindowedConstantWaveform
        
        acadia = Acadia()

        pulse_channel = acadia.DAC(self.DAC)
        pulse = WindowedConstantWaveform(pulse_channel, 
                                            constant_length_seconds=self.stimulus_constant_time,
                                            window_length_seconds=self.stimulus_ramp_time)

        capture_channel = acadia.ADC(self.DAC)
        capture_time = self.capture_time if self.capture_time is not None else self.stimulus_ramp_time + self.stimulus_constant_time
        capture_data = Waveform(capture_channel, length_seconds=capture_time, region=acadia.PLDDR0Array)
                        
        # We'll collect the data traces in a record group
        datamanager.add_group(LoopbackRecordGroup("traces", 
                                                  directory, 
                                                  axes=[capture_data.axis()]))
        
        # Create a sequence for the sequencer
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                a.stream(capture_channel, capture_data)
                a.generate(pulse)

        acadia.compile(sequence)

        # Attach to the hardware
        acadia.attach()
        
        acadia.configure_clocks(reference="external")
        time.sleep(1)
        acadia.align_tile_latencies()
        time.sleep(1)

        # Load the wave memory with the pulse by calling the generator function
        pulse[:] = np.hanning(len(pulse))
        pulse.flush(scale=self.stimulus_amplitude)

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
                
        for shot in datamanager.report_iterations(range(self.iterations)):
            acadia.run(assemble=(shot==0))
            with capture_data.unbuffer():
                datamanager.write("traces", capture_data.memory)
