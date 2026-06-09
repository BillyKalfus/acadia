from dataclasses import dataclass

from acadia.runtime import Runtime

@dataclass
class SpectroscopyRuntime(Runtime):
    """
    A Runtime for performing spectroscopy using the CMACC module for integration.
    """

    # Iterable of frequencies points to sweep over
    frequencies: list 
    
    stimulus: dict
    capture: dict

    full_traces: bool = False
    kernel_scale: float = 0.1
    use_upper_data: bool = False

    plot: bool = False
    
    # If ``0``, automatically fit phase data to 
    # extract an electrical delay. If any ``float``, this will be 
    # interpreted as the electrical delay to apply.
    electrical_delay: float = 0 

    # The number of full spectra to take
    iterations: int = 10

    minimum_run_delay: int = 1000000
        
    def main(self):       
        import numpy as np 
        from acadia import Acadia, DataManager, WaveformMemory
        
        acadia = Acadia()
        stimulus_channel = acadia.channel(self.stimulus["channel"])
        capture_channel = acadia.channel(self.capture["channel"])

        # Create a waveform to store the stimulus signal
        stimulus_waveform = acadia.create_waveform_memory(stimulus_channel, length=self.stimulus["length"])

        # For the capture waveform, we need to set decimation to zero so that
        # the output will be a single sample if we're not capturing decimated traces
        # The output of the CMACC will be sent to the DDR
        capture_waveform = acadia.create_waveform_memory(
            capture_channel,
            length=self.capture["length"],
            decimation=(4 if self.full_traces else 0), 
            region="plddr") 

        # Get a stream configuration for the CMACC that we'll use
        stream_config = acadia.request_stream_configuration(capture_channel, "cmacc")

        # Make a single-sample kernel.
        # Here, it's easier to just instantiate the WaveformMemory object directly.
        # We specify a datatype of 2-byte signed integers and specify that the memory should
        # be allocated in the kernel memory for the designated CMACC
        kernel = WaveformMemory(shape=1, dtype="<i2", resource_allocator=acadia.memory_region(stream_config))
                
        # Create a data record group for storing the data that we collect
        # we can mark it as uniform because we know that every record we collect
        # will have the same shape.
        self.data.add_group("traces", uniform=True)
                
        def sequence(a: Acadia):
            # We first need to set up the CMACC
            # Use a preload of 0
            a.assign_cmacc_preload(stream_config, 0)

            # Specify the kernel that will be used for integration
            a.assign_cmacc_kernel(stream_config, kernel)

            # Configure the CMACC
            a.configure_cmacc(
                stream_config,
                arm_preload=True,
                accumulator_update_mode=("after_kernel_start" if self.full_traces else "after_arm"),
                latch_update_mode="last",
                stream_update_mode=("kernel" if self.full_traces else "last"),
                use_upper_data=self.use_upper_data)

            # Prepare the datamover to write the stream
            a.write_stream(stream_config, capture_waveform)

            # Create a synchronizer block to arrange cycle-accurate pulse scheduling
            with a.channel_synchronizer():
                # Play the stimulus out of the DAC
                a.schedule_dac_waveform(stimulus_waveform)
                a.schedule_adc_stream(stream_config, length=self.capture["length"])


        # Compile the sequence
        acadia.compile(sequence)

        # Connect to the hardware and align the RF tiles
        acadia.attach()
        acadia.align_tile_latencies()

        # Configure the channel properties according to the settings provided
        # Here we will also configure the NCOs to be synchronously updated
        stimulus_channel.set(nco_update_event_source="sysref", **self.stimulus["datapath"])
        capture_channel.set(nco_update_event_source="sysref", **self.capture["datapath"])

        # Load the stimulus waveform memory with a hann function (raised cosine)
        from scipy.signal.windows import hann
        stimulus_waveform.load(hann(stimulus_waveform.size), scale=self.stimulus["waveform_scale"])

        # Set the amplitude of the boxcar integration kernel 
        kernel.load(self.kernel_scale)

        # Assemble the sequence and load it into sequencer instruction memory
        acadia.assemble()
        acadia.load()

        for i in self.iterate(self.iterations):
            for frequency in self.frequencies:
                # Synchronously set the modulation frequencies and reset phases
                acadia.update_nco_frequency(stimulus_channel, frequency=frequency)
                acadia.update_nco_frequency(capture_channel, frequency=-frequency)
                acadia.reset_nco_phase(stimulus_channel)
                acadia.reset_nco_phase(capture_channel)
                acadia.update_ncos_synchronized()
                # acadia.update_ncos_synchronized()

                # Run the sequencer                    
                acadia.run(minimum_delay=self.minimum_run_delay)

                # When the sequencer was run, the integrated signal was stored into
                # capture_waveform because it was provided to acadia.stream()
                # Because of how WaveformMemory objects work, we can just grab the data in 
                # that memory as if it were any numpy array. Here we'll get the data
                # and write it into the record group we created above
                self.data["traces"].write(capture_waveform.array)
        
        self.final_serve()

    def initialize(self):
        # Set the matplotlib backend to one which we can actually update
        if self.plot:
            from acadia.processing import DynamicLine
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
            ax[0].set_xlim(self.frequencies[0], self.frequencies[-1])
            
            # Create a plot for the spectral phase
            self.line_phase = DynamicLine(ax[1], ".-")
            ax[1].set_xlabel("Frequency [MHz]")
            ax[1].set_ylabel("Phase [rad.]")
            ax[1].set_title("Spectral Phase")
            ax[1].grid()
            ax[1].set_xlim(self.frequencies[0], self.frequencies[-1])

            # Create a label for displaying the electrical delay
            self._delay_label = Label("Electrical delay: ")
            display(self._delay_label)

            from tqdm.notebook import tqdm

        else:
            from tqdm import tqdm

        self.iterations_progress_bar = tqdm(desc="Iterations", dynamic_ncols=True, total=self.iterations)
        self.iterations_previous = 0
        self.frequencies_progress_bar = tqdm(desc="Frequency Sweep Points", dynamic_ncols=True, total=len(self.frequencies)*self.iterations)
        self.frequencies_previous = 0

        import numpy as np
        self.data_summed = None
        self.electrical_delay_phases = np.exp(2*np.pi*1j*self.frequencies*self.electrical_delay)
        self.fit_electrical_delay = 0.0
        self.fit_electrical_delay_error = 0.0

    def update(self):
        import numpy as np
        from scipy.optimize import curve_fit
        from acadia.sample_arithmetic import sample_to_complex

        # First make sure that we actually have new data to process
        if "traces" not in self.data:
            return
        
        # Update the progress bar based on the number of iterations
        completed_iterations = len(self.data["traces"]) // len(self.frequencies)
        self.iterations_progress_bar.update(completed_iterations - self.iterations_previous)

        completed_frequencies = len(self.data["traces"])
        self.frequencies_progress_bar.update(completed_frequencies - self.frequencies_previous)

        # Only continue processing data if we have at least one complete iteration
        if completed_iterations != 0:
        
            valid_traces = completed_iterations*len(self.frequencies)
            data = self.data["traces"].records()[:valid_traces, ...]

            # Get the collection of data and reshape it so that the axes index as: 
            # (iteration, frequency, sample time, sample quadrature)
            samples_per_trace = data.shape[-2]
            data_reshaped = data.reshape(-1, len(self.frequencies), samples_per_trace, 2)
            
            # Slice the data so that we have an array containing only the traces
            # we didn't have the last time update() was called
            self.new_data = data_reshaped[self.iterations_previous:, :, :, :]

            # Sum the new data and then add it to the aggregated array of trace data
            new_data_summed = np.sum(self.new_data, axis=(0,2), keepdims=False)
            if self.data_summed is None:
                self.data_summed = new_data_summed
            else:
                self.data_summed += new_data_summed

            # Convert the summed sample data to a complex number and choose 
            # the scale so that we turn the sum into a mean
            # Simultaneously, choose the scale so that the result is independent
            # of amplitude
            scale = (self.stimulus["waveform_scale"] / completed_iterations)
            self.data_complex = sample_to_complex(self.data_summed, scale=scale)

            # Apply the electrical delay
            self.data_complex *= self.electrical_delay_phases

            # We now have a 1D array of the amplitudes as a function of frequency,
            # so we can do whatever processing we want
            mags = np.abs(self.data_complex)
            phases = np.unwrap(np.angle(self.data_complex))

            # Update the fit
            def model(freqs, delay, phi0):
                return 2*np.pi*freqs*delay + phi0
        
            popt,pcov = curve_fit(model, self.frequencies, phases)
            self.fit_electrical_delay = popt[0]
            self.fit_electrical_delay_error = pcov[0,0]

            # Update the plot itself
            if self.plot:
                self.line_mag.update(self.frequencies, mags)
                self.line_phase.update(self.frequencies, phases)
                self._delay_label.value = f"Fit electrical delay = {round(self.fit_electrical_delay*1e9,1)} ns +/- {round(self.fit_electrical_delay_error*1e12)} ps"
                self.fig.canvas.draw_idle()

            # Save the data
            self.data.save(self.local_directory)

        self.iterations_previous = completed_iterations
        self.frequencies_previous = completed_frequencies

    def finalize(self):
        super().finalize()
        self.iterations_progress_bar.close()
        self.frequencies_progress_bar.close()

def run(plot=True):
    import numpy as np

    stimulus: dict = {
        "channel": "DAC4",

        "datapath": {
            "vop": 4000,
            "mix_reconstruction": True
        },

        "length": 2400e-9,        
        "waveform_scale": 0.9
    }
    
    capture: dict = {
        "channel": "ADC0",

        "datapath": {
            "mix_reconstruction": True
        },

        "length":  2.56e-6,
    }

    frequencies = np.linspace(4.4512345e9, 4.55e9, 21)
    # frequencies = np.concatenate((frequencies, frequencies[::-1]))

    # Run the program on the target
    rt = SpectroscopyRuntime(
        frequencies=frequencies,
        stimulus=stimulus,
        capture=capture,
        iterations=1000,
        minimum_run_delay=1000000,
        plot=plot,
        electrical_delay=0,
        full_traces=True,
        use_upper_data=False,
        kernel_scale=2e-5)
    
    if plot:
        # Set the matplotlib backend to one which we can actually update
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

    rt.deploy("10.66.138.216", log_debug=True)    
    rt.display()
    
    return rt

if __name__ == "__main__":
    rt = run()