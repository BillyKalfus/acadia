from dataclasses import dataclass

from acadia.runtime import Runtime

@dataclass
class SpectroscopyRuntime(Runtime):
    """
    A :class:`Runtime` subclass for performing swept spectroscopy.
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

        # Assemble and load the program
        acadia.load(*acadia.assemble())

        # Loop while reporting progress back to the host
        for i in self.data.count(self.iterations, "Iterations"):
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
        # Set the matplotlib backend to one which we can actually update
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

        from acadia.processing import DynamicLine, ProgressBar
        import matplotlib.pyplot as plt
        from IPython.display import display
        from ipywidgets import Label

        self.fig,ax = plt.subplots(1,2, figsize=(7,3))
        self.fig.subplots_adjust(hspace=0.35)
        self.fig.tight_layout()

        # Create a plot for the spectral magnitude
        self.line_mag = DynamicLine(ax[0], ".-")
        ax[0].set_xlabel("Frequency [MHz]")
        ax[0].set_ylabel("Magnitude [arb. V*s]")
        ax[0].set_title("Spectral Magnitude")
        ax[0].grid()
        
        # Create a plot for the spectral phase
        self.line_phase = DynamicLine(ax[1], ".-")
        ax[1].set_xlabel("Frequency [MHz]")
        ax[1].set_ylabel("Phase [rad.]")
        ax[1].set_title("Spectral Phase")
        ax[1].grid()

        # Create a label for displaying the electrical delay
        self._delay_label = Label("Electrical delay: ")
        display(self._delay_label)

        self.progress_bar = ProgressBar("Iterations")

    def update(self):
        import numpy as np
        from scipy.optimize import curve_fit
        from acadia.processing import process_data
        from acadia.arrays import Waveform

        # First make sure that we actually have new data to process
        if not self.data.available("traces"):
            return
        
        if "Iterations" in self.data:
            self.progress_bar.update(self.data["Iterations"])

        # Get the sample data from the record group
        # The data in the record group will have a custom structured dtype 
        # because each sample contains both quadratures packed together, so
        # we need to convert it either to integers or to floating-point values
        # if we want to do operations on it. Because integer math is often 
        # much faster than floating point (and accrues no error), it's preferable
        # to wait as long as possible before converting to floating point
        # Keep in mind that this will add an extra dimension of length 2 on the
        # right
        data = Waveform.sample_to_int(self.data["traces"].records())

        # Now sum over time and datasets
        # We can do this with `process_data` by providing an argument 
        # with the appropriate structure. See its documentation for further details.
        # The example here has three elements, one for each dimension of the 
        # data. The dimensions are C-style; that is, elements are arranged in
        # memory such that moving from one element to the next in the 
        # flattened array corresponds to moving along the rightmost axis.
        #
        # Therefore, we can interpret the structure as follows (moving right to left):
        # - The rightmost axis corresponds to the two quadratures, since they are 
        #   packed next to each other in memory. We don't want to merge them in any 
        #   way (yet), so we pass `None` to do nothing
        # - The next axis corresponds to the time axis, because the records 
        #   written to the group are time-series sample arrays. The length of this
        #   axis (i.e., the number of samples per record) is extracted from the 
        #   shape of the record group; since the program writes time-series traces
        #   back-to-back, we can get the length of a trace by looking at its rightmost
        #   axis length
        # - Traces are collected while sweeping frequency, with one trace collected 
        #   per frequency point. Therefore, frequency is the next axis; we extract its
        #   length by directly giving it the array of frequencies being swept over 
        #   (which we take directly from the runtime object).
        # - Once we've collected a trace for every frequency point, we've completed 
        #   a "dataset". In principle we could decide to be done and report what we have,
        #   but oftentimes we'll collect multiple datasets and average them to reduce
        #   the noise of the measurement. Therefore, for the outermost axis, we extract
        #   all the datasets available by specifying `-1` as the axis length and sum them
        #   together.
        processing_spec = [(-1, np.sum), (self.frequencies, None), (self.data["traces"].shape[-1], np.sum), (2, None)]
        data,_ = process_data(data, processing_spec)

        # Convert the data to complex
        data = Waveform.to_complex(data)

        # By default, process_data and Waveform.to_complex will not remove the 
        # length-1 axes that result from reduction. 
        # In this case, we don't need them, so get rid of them
        data = np.squeeze(data)

        # Apply the electrical delay
        data *= np.exp(2*np.pi*1j*self.frequencies*self.plot_electrical_delay)

        # We now have a 1D array of the amplitudes as a function of frequency,
        # so we can do whatever processing we want
        mags = np.abs(data)
        phases = np.unwrap(np.angle(data))
        self.line_mag.update(self.frequencies, mags)
        self.line_phase.update(self.frequencies, phases)

        # Update the fit
        def model(freqs, delay, phi0):
            return 2*np.pi*freqs*delay + phi0
    
        popt,pcov = curve_fit(model, self.frequencies, phases)
        self._delay_label.value = f"Electrical delay = {round(popt[0]*1e9,1)} ns +/- {round(pcov[0,0]*1e12)} ps"

        # Update the plot itself
        self.fig.canvas.draw_idle()

    def finalize(self):
        super().finalize()
        self.progress_bar.finalize()


if __name__ == "__main__":
    import numpy as np
    
    # Run the program on the target
    rt = SpectroscopyRuntime(frequencies=np.linspace(9.15e9, 9.25e9, 101),
                            DAC=4,
                            ADC=4, 
                            stimulus_ramp_time=1e-6,
                            stimulus_constant_time=10e-6,
                            stimulus_amplitude=1,
                            stimulus_NZ=2,
                            capture_decimation=0,
                            capture_delay=224e-9,
                            iterations=100,
                            plot_electrical_delay=112.2e-9)
    rt.deploy("192.168.2.70", "acadia.runtimes.spectroscopy", log_debug=True)    
    rt.display()
    
