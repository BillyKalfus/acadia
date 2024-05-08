from dataclasses import dataclass
from typing import Sequence

from acadia.runtime import Runtime

@dataclass
class SweptAmplitudeSpectroscopyRuntime(Runtime):
    """
    A :class:`Runtime` subclass for performing spectroscopy while sweeping the
    amplitude of the stimulus.
    """

    # Iterable of frequencies
    frequencies: list 
    
    # DAC channel used for stimulus
    DAC: int 
    
    # ADC channel for capture
    ADC: int 
    
    # Length of the stimulus signal flat top in seconds
    stimulus_constant_time: float 
    
    # Length of the stimulus signal ramp in seconds (Total)
    stimulus_ramp_time: float
    
    # DAC amplitude of stimulus or array thereof
    stimulus_amplitudes: Sequence[complex]
    
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
    capture_decimation: int = 4
    
    # If ``0``, automatically fit phase data to 
    # extract an electrical delay. If any ``float``, this will be 
    # interpreted as the electrical delay to apply.
    plot_electrical_delay: float = 0 

    # The number of full spectra to take
    iterations: int = 10
        
    def main(self):
        import numpy as np
        
        from acadia.system import Acadia
        from acadia.data import ArrayRecordGroup
        from acadia.arrays import Waveform, WindowedConstantWaveform, ConstantWaveform
        
        # Create an acadia object and grab a couple of its channels
        acadia = Acadia()
        pulse_channel = acadia.DAC(self.DAC)
        capture_channel = acadia.ADC(self.ADC)
        
        # Determine what kind of pulse waveform we'll need depending on input parameters
        if self.stimulus_constant_time == 0:
            pulse = Waveform(pulse_channel, 
                             length=pulse_channel.seconds_to_bytes(self.stimulus_ramp_time) // 4, 
                             region=pulse_channel)
        elif self.stimulus_ramp_time == 0:
            pulse = ConstantWaveform(pulse_channel, 
                                    length_seconds=self.stimulus_constant_time)
        else:
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
                if self.capture_delay > 0:
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

        # Create the pulse shape (we'll load it later with the appropriate scale value)
        if self.stimulus_ramp_time != 0:
            pulse_complex = np.hanning(len(pulse)).astype(np.complex64)
        else:
            pulse_complex = np.complex64(1)


        # Configure channel analog parameters
        pulse_channel.set_nyquist_zone(self.stimulus_NZ)
        pulse_channel.set_vop(self.stimulus_VOP)

        # Set up the channels for synchronized NCO updates
        pulse_channel.configure_nco(update_source="sysref")
        capture_channel.configure_nco(update_source="sysref")

        # Assemble and load the program
        acadia.load(*acadia.assemble())

        # Loop while reporting progress back to the host
        for i in self.data.count(self.iterations, "Iterations"):
            for amplitude in self.stimulus_amplitudes:
                pulse[:] = Waveform.complex_to_sample(pulse_complex, scale=amplitude)
                for frequency in self.data.count(self.frequencies, "Frequencies"):
                    # Synchronously set the modulation frequencies and reset phases
                    acadia.update_nco_frequency(pulse_channel, frequency=frequency)
                    acadia.update_nco_frequency(capture_channel, frequency=-frequency)
                    acadia.reset_nco_phase(pulse_channel)
                    acadia.reset_nco_phase(capture_channel)
                    acadia.update_ncos_synchronized()

                    # Run the sequencer                        
                    acadia.run(assemble=False)

                    # Grab the data from memory and save it
                    self.data.write("traces", capture_data)

    def initialize(self):
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

        from acadia.processing import DynamicLine
        import matplotlib.pyplot as plt

        self.fig,ax = plt.subplots(1,2, figsize=(7,3))
        self.fig.subplots_adjust(hspace=0.35)
        self.fig.tight_layout()

        # Create a plot for the spectral magnitude
        ax[0].set_xlabel("Frequency [MHz]")
        ax[0].set_ylabel("Magnitude [arb. V*s]")
        ax[0].set_title("Spectral Magnitude")
        ax[0].grid()
        
        # Create a plot for the spectral phase
        ax[1].set_xlabel("Frequency [MHz]")
        ax[1].set_ylabel("Phase [rad.]")
        ax[1].set_title("Spectral Phase")
        ax[1].grid()

        self.lines_mag = []
        self.lines_phase = []

        for amp in self.stimulus_amplitudes:
            self.lines_mag.append(DynamicLine(ax[0], ".-", label=f"{amp}"))
            self.lines_phase.append(DynamicLine(ax[1], ".-", label=f"{amp}"))

        ax[0].legend()

        self.electrical_delay_vec = np.exp(2*np.pi*1j*self.frequencies*self.plot_electrical_delay)

    def update(self):
        import numpy as np
        from acadia.arrays import Waveform

        # First make sure that we actually have new data to process
        if not self.data.available("traces"):
            return

        data_int = Waveform.sample_to_int(self.data["traces"].records())
        data_reshaped = data_int.reshape(-1, len(self.stimulus_amplitudes), len(self.frequencies), self.data["traces"].shape[-1], 2)
        data_summed = np.sum(data_reshaped, axis=(0,3))
        data_complex = np.squeeze(Waveform.to_complex(data_summed))

        for idx_amplitude,_ in enumerate(self.stimulus_amplitudes):
            amplitude_data = data_complex[idx_amplitude,:]

            # Apply the electrical delay
            amplitude_data *= self.electrical_delay_vec

            # We now have a 1D array of the amplitudes as a function of frequency,
            # so we can do whatever processing we want
            mags = np.abs(amplitude_data)
            phases = np.unwrap(np.angle(amplitude_data))
            self.lines_mag[idx_amplitude].update(self.frequencies, mags)
            self.lines_phase[idx_amplitude].update(self.frequencies, phases)

        self.lines_mag[0]._ax.relim()
        self.lines_mag[0]._ax.autoscale()
        self.lines_phase[0]._ax.relim()
        self.lines_phase[0]._ax.autoscale()

        # Update the plot itself
        self.fig.canvas.draw_idle()


if __name__ == "__main__":
    import numpy as np
    
    # Run the program on the target
    rt = SweptAmplitudeSpectroscopyRuntime(frequencies=np.linspace(9.18e9, 9.24e9, 41),
                            DAC=4,
                            ADC=4, 
                            stimulus_ramp_time=1e-6,
                            stimulus_constant_time=100e-6,
                            stimulus_amplitudes=np.round(np.linspace(0.1, 1, 10), 1),
                            stimulus_NZ=2,
                            stimulus_VOP=4500,
                            capture_decimation=0,
                            capture_delay=224e-9,
                            iterations=100,
                            plot_electrical_delay=112.2e-9)
        
    rt.deploy("192.168.2.70", "acadia.runtimes.swept_amplitude_spectroscopy")    
    rt.display()
    
