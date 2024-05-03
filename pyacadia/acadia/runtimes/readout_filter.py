from dataclasses import dataclass

from acadia.runtime import Runtime
from acadia.data import DataManager

@dataclass
class ReadoutFilterRuntime(Runtime):
    """
    A :class:`Runtime` subclass for performing swept spectroscopy.
    """
    # Iterable of frequencies
    qubit_frequencies: list 
    
    # DAC channel used for stimulus
    qubit_DAC: int 

    readout_frequency: float

    readout_DAC: int

    readout_ADC: int
    
    # Length of the stimulus signal flat top in seconds
    qubit_stimulus_constant_time: float = 1e-3
    
    # Length of the stimulus signal ramp in seconds (Total)
    # must be nonzero
    qubit_stimulus_ramp_time: float = 1e-6
    
    # DAC amplitude of stimulus
    qubit_stimulus_amplitude: complex = 1.0
    
    # DAC Nyquist zone (1 or 2)
    qubit_stimulus_NZ: int = 2
    
    # VOP setting for DAC (2250 - 40000)
    qubit_stimulus_VOP: int = 12000

    # Length of the stimulus signal flat top in seconds
    readout_stimulus_constant_time: float = 1e-3
    
    # Length of the stimulus signal ramp in seconds (Total)
    readout_stimulus_ramp_time: float = 1e-6
    
    # DAC amplitude of stimulus
    readout_stimulus_amplitude: complex = 1.0
    
    # DAC Nyquist zone (1 or 2)
    readout_stimulus_NZ: int = 2
    
    # VOP setting for DAC (2250 - 40000)
    readout_stimulus_VOP: int = 12000
    
    # Total length of the capture. If ``0``, will be set to stimulus_ramp_time + stimulus_flat_time
    readout_capture_time: float = 0
    
    # Add this much delay at the start of the capture to account for round-trip time of the stimulus
    readout_capture_delay: float = 0

    # Determine how the capture will be carried out
    # If 0, the full waveform will be integrated
    # Otherwise, this amount of decimation will be used
    readout_capture_decimation: int = 0

    # The number of full spectra to take
    iterations: int = 10
        
    def main(self):
        import numpy as np
        
        from acadia.system import Acadia
        from acadia.data import ArrayRecordGroup
        from acadia.arrays import Waveform, WindowedConstantWaveform
        
        # Create an acadia object and grab a couple of its channels
        acadia = Acadia()
        qubit_channel = acadia.DAC(self.qubit_DAC)
        readout_stimulus_channel = acadia.DAC(self.readout_DAC)
        readout_capture_channel = acadia.ADC(self.readout_ADC)
        
        # Determine what kind of pulse waveform we'll need depending on input parameters
        qubit_pulse = WindowedConstantWaveform(qubit_channel, 
                                            constant_length_seconds=self.qubit_stimulus_constant_time,
                                            window_length_seconds=self.qubit_stimulus_ramp_time)
            
        readout_pulse = WindowedConstantWaveform(readout_stimulus_channel, 
                                            constant_length_seconds=self.qubit_stimulus_constant_time,
                                            window_length_seconds=self.qubit_stimulus_ramp_time)
        
        # Determine how long to capture for
        capture_time = self.readout_capture_time if self.readout_capture_time != 0 else self.readout_stimulus_ramp_time + self.readout_stimulus_constant_time                        
        
        # Create a record group for saving captured data, storing the chosen capture time along with it
        self.data.create_group(ArrayRecordGroup, "traces", capture_time=capture_time)
                
        # Create a sequence for the sequencer to generate the pulse and capture it
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                a.generate(qubit_pulse)
                a.barrier()
                a.generate(readout_pulse)
                a.generate_blank(readout_capture_channel, self.readout_capture_delay)
                capture_data, _ = a.stream(readout_capture_channel, 
                                   length=capture_time, 
                                   length_units="seconds", 
                                   decimation=self.readout_capture_decimation)
                
            return capture_data

        # Compile the sequence
        capture_data = acadia.compile(sequence)
                
        # Attach to the hardware and configure clocking
        acadia.attach()
        acadia.align_tile_latencies()

        # Populate the pulse memory in hardware with samples
        if self.qubit_stimulus_ramp_time != 0:
            pulse_complex = np.hanning(len(qubit_pulse)).astype(np.complex64)
            qubit_pulse[:] = Waveform.complex_to_sample(pulse_complex, scale=self.qubit_stimulus_amplitude)
        else:
            qubit_pulse[:] = np.complex64(self.qubit_stimulus_amplitude)

        if self.readout_stimulus_ramp_time != 0:
            pulse_complex = np.hanning(len(readout_pulse)).astype(np.complex64)
            readout_pulse[:] = Waveform.complex_to_sample(pulse_complex, scale=self.readout_stimulus_amplitude)
        else:
            readout_pulse[:] = np.complex64(self.readout_stimulus_amplitude)

        # Configure channel analog parameters
        qubit_channel.set_nyquist_zone(self.qubit_stimulus_NZ)
        qubit_channel.set_vop(self.qubit_stimulus_VOP)
        readout_stimulus_channel.set_nyquist_zone(self.readout_stimulus_NZ)
        readout_stimulus_channel.set_vop(self.readout_stimulus_VOP)

        # Set up the channels for synchronized NCO updates
        readout_stimulus_channel.configure_nco(update_source="sysref")
        readout_capture_channel.configure_nco(update_source="sysref")
        acadia.update_nco_frequency(readout_stimulus_channel, frequency=self.readout_frequency)
        acadia.update_nco_frequency(readout_capture_channel, frequency=-self.readout_frequency)
        acadia.reset_nco_phase(readout_stimulus_channel)
        acadia.reset_nco_phase(readout_capture_channel)
        acadia.update_ncos_synchronized()

        # Assemble and load the program
        acadia.load(*acadia.assemble())

        # Loop while reporting progress back to the host
        for i in self.data.count(self.iterations, "Iterations"):
            for frequency in self.data.count(self.qubit_frequencies, "Frequencies"):
                qubit_channel.configure_nco(frequency=frequency)
                acadia.run(assemble=False)
                self.data.write("traces", capture_data)

    def initialize(self):
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

        from acadia.processing import DynamicLine
        import matplotlib.pyplot as plt
        from matplotlib.colors import LogNorm

        self.fig,ax = plt.subplots(1,2, figsize=(7,3))
        self.fig.subplots_adjust(hspace=0.35)
        self.fig.tight_layout()

        # Create a plot for the quadratures
        self.line_re = DynamicLine(ax[0], ".-", label="Re")
        self.line_im = DynamicLine(ax[0], ".-", Label="Im")
        ax[0].set_xlabel("Qubit Drive Frequency [MHz]")
        ax[0].set_ylabel("Quadrature Amplitude [arb. V*s]")
        ax[0].set_title("Signal Amplitude")
        ax[0].grid()
        

    def update(self):
        import numpy as np
        from acadia.arrays import Waveform
        

        if not self.data.available("traces"):
            return

        data = np.squeeze(Waveform.sample_to_complex(self.data["traces"].records()))

        mags = np.abs(data)
        phases = np.unwrap(np.angle(data))
        self.line_mag.update(self.qubit_frequencies, mags)
        self.line_phase.update(self.qubit_frequencies, phases)

        # Update the plot itself
        self.plots.update()

        data = np.squeeze(Waveform.to_complex(rt.data["traces"].records()))
        hist = np.histogram2d(np.real(data), np.imag(data), bins=25)

        plt.figure()
        plt.pcolormesh(hist[1], hist[2], hist[0])
        plt.show()


if __name__ == "__main__":
    import numpy as np
    import logging
    
    # Run the program on the target
    rt = ReadoutFilterRuntime(qubit_frequencies=np.linspace(4.0e9, 4.1e9, 101),
                            qubit_DAC=2,
                            readout_DAC=4,
                            readout_ADC=4, 
                            qubit_stimulus_ramp_time=1e-6,
                            qubit_stimulus_constant_time=1000e-6,
                            qubit_stimulus_amplitude=1,
                            qubit_stimulus_NZ=2,
                            readout_frequency=9.215e9,
                            readout_stimulus_ramp_time=1e-6,
                            readout_stimulus_constant_time=100e-6,
                            readout_stimulus_amplitude=0.3,
                            readout_stimulus_NZ=2,
                            readout_stimulus_VOP=4500,
                            readout_capture_decimation=0,
                            readout_capture_delay=224e-9,
                            iterations=100)
    rt.deploy("192.168.2.70", "qubit_spectroscopy", files=[__file__], log_debug=True)    
    rt.display()
    
