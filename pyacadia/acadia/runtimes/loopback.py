from dataclasses import dataclass

from acadia.runtime import Runtime

@dataclass
class LoopbackRuntime(Runtime):
    """
    A :class:`Runtime` subclass for performing swept spectroscopy.
    """
    # Pulse frequency
    frequency: float 
    
    # DAC channel used for stimulus
    DAC: int 
    
    # ADC channel for capture
    ADC: int 
    
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
    
    # Total length of the capture. If ``0``, will be set to stimulus_ramp_time + stimulus_flat_time
    capture_time: float = 0
    
    # Add this much delay at the start of the capture to account for round-trip time of the stimulus
    capture_delay: float = 0

    # Determine how the capture will be carried out
    # If 0, the full waveform will be integrated
    # Otherwise, this amount of decimation will be used
    capture_decimation: int = 1

    # The number of full spectra to take
    iterations: int = 10
        
    def main(self):
        import numpy as np
        
        from acadia.system import Acadia
        from acadia.data import ArrayRecordGroup
        from acadia.arrays import Waveform, WindowedConstantWaveform
        
        # Create an acadia object and grab a couple of its channels
        acadia = Acadia()
        pulse_channel = acadia.DAC(self.DAC)
        capture_channel = acadia.ADC(self.ADC)
        
        pulse = WindowedConstantWaveform(pulse_channel, 
                                            constant_length_seconds=self.stimulus_constant_time,
                                            window_length_seconds=self.stimulus_ramp_time)
        
        # Determine how long to capture for
        capture_time = self.capture_time if self.capture_time != 0 else self.stimulus_ramp_time + self.stimulus_constant_time                        
        
        # Create a record group for saving captured data, storing the chosen capture time along with it
        self.data.create_group(ArrayRecordGroup, "traces", capture_time=capture_time)
                
        # Create a sequence for the sequencer to generate the pulse and capture it
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                a.generate(pulse)
                a.generate_blank(capture_channel, self.capture_delay)
                capture_data, _ = a.stream(capture_channel, 
                                   length=capture_time, 
                                   length_units="seconds", 
                                   decimation=self.capture_decimation)
                
            return capture_data

        # Compile the sequence
        capture_data = acadia.compile(sequence)
                
        # Attach to the hardware and configure clocking
        acadia.attach()
        acadia.align_tile_latencies()

        # Populate the pulse memory in hardware with samples
        if self.stimulus_ramp_time != 0:
            pulse_complex = np.hanning(len(pulse)).astype(np.complex64)
            pulse[:] = Waveform.complex_to_sample(pulse_complex, scale=self.stimulus_amplitude)
        else:
            pulse[:] = np.complex64(self.stimulus_amplitude)

        # Configure channel analog parameters
        pulse_channel.set_nyquist_zone(self.stimulus_NZ)
        pulse_channel.set_vop(self.stimulus_VOP)

        # Set up the channels for synchronized NCO updates
        pulse_channel.configure_nco(update_source="sysref")
        capture_channel.configure_nco(update_source="sysref")
        acadia.update_nco_frequency(pulse_channel, frequency=self.frequency)
        acadia.update_nco_frequency(capture_channel, frequency=-self.frequency)
        acadia.reset_nco_phase(pulse_channel)
        acadia.reset_nco_phase(capture_channel)
        acadia.update_ncos_synchronized()

        # Assemble and load the program
        acadia.load(*acadia.assemble())

        for i in self.data.count(self.iterations, "Iterations"):
            acadia.run(assemble=False)
            self.data.write("traces", capture_data)

    def initialize(self):
        # Set the matplotlib backend to one which we can actually update
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

        from acadia.processing import DynamicLine, ProgressBar
        import matplotlib.pyplot as plt

        self.fig,self.ax = plt.subplots(1,1, figsize=(3,3))
        self.fig.tight_layout()

        self.line_re = DynamicLine(self.ax, ".-")
        self.line_im = DynamicLine(self.ax, ".-")
        self.ax.set_xlabel("Time [s]")
        self.ax.set_ylabel("Signal Amplitude [arb. V]")
        self.ax.grid()

        self.progress_bar = ProgressBar("Iterations")
        self.time_axis = None

    def update(self):
        import numpy as np

        # First make sure that we actually have new data to process
        if not self.data.available("traces"):
            return
        
        if "Iterations" in self.data:
            self.progress_bar.update(self.data["Iterations"])

        if self.time_axis is None:
            self.time_axis = np.linspace(0, self.data["traces"].metadata()["capture_time"], self.data["traces"].shape[0], endpoint=False)

        trace_re = np.sum(self.data["traces"].records()["re"], axis=0)
        trace_im = np.sum(self.data["traces"].records()["im"], axis=0)
        self.line_re.update(self.time_axis, trace_re)
        self.line_im.update(self.time_axis, trace_im)
        self.ax.relim()
        self.ax.autoscale_view()
        self.fig.canvas.draw_idle()

    def finalize(self):
        super().finalize()
        self.progress_bar.finalize()


if __name__ == "__main__":    

    rt = LoopbackRuntime(frequency=4.4e9,
                            DAC=4,
                            ADC=4, 
                            stimulus_ramp_time=256e-9,
                            stimulus_constant_time=256e-9,
                            stimulus_amplitude=1,
                            stimulus_NZ=2,
                            capture_time=1024e-9,
                            capture_decimation=0,
                            capture_delay=0e-9,
                            iterations=100000)
    rt.deploy("192.168.2.69", "acadia.runtimes.loopback")    
    rt.display()
    
