from dataclasses import dataclass

from acadia.runtime import Runtime

@dataclass
class SpectroscopyRuntime(Runtime):
    """
    A :class:`Runtime` subclass for performing swept spectroscopy.
    """
    # Iterable of frequencies
    frequencies: list 
    
    stimulus: dict
    capture: dict
    
    # If ``0``, automatically fit phase data to 
    # extract an electrical delay. If any ``float``, this will be 
    # interpreted as the electrical delay to apply.
    plot_electrical_delay: float = 0 

    # The number of full spectra to take
    iterations: int = 10
        
    def main(self):        
        from acadia.system import Acadia
        
        acadia = Acadia()
        stimulus_channel = acadia.channel(self.stimulus["channel"])
        capture_channel = acadia.channel(self.capture["channel"])

        stimulus = acadia.create_waveform(stimulus_channel, **self.stimulus["waveform"])
        capture_data = acadia.create_waveform(capture_channel, **self.capture["waveform"]) 
                
        self.data.add_group("traces", uniform=True)
                
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                a.schedule_waveform(stimulus)
                a.stream(capture_channel, capture_data)

        acadia.compile(sequence)
        acadia.attach()
        acadia.align_tile_latencies()

        # When we set the channel properties, configure the NCO for synchronization
        stimulus_channel.set(**self.stimulus["datapath"])
        stimulus_channel.set_nco(update_source="sysref")
        capture_channel.set(**self.capture["datapath"])
        capture_channel.set_nco(update_source="sysref")

        stimulus.set(**self.stimulus["signal"])

        acadia.load(*acadia.assemble())

        for i in range(self.iterations):
            for frequency in self.frequencies:
                # Synchronously set the modulation frequencies and reset phases
                acadia.update_nco_frequency(stimulus_channel, frequency=frequency)
                acadia.update_nco_frequency(capture_channel, frequency=-frequency)
                acadia.reset_nco_phase(stimulus_channel)
                acadia.reset_nco_phase(capture_channel)
                acadia.update_ncos_synchronized()

                # Run the sequencer                        
                acadia.run(assemble=False)
                self.data["traces"].write(capture_data.array)
            
                # Check whether the host wants data
                self.data.serve()

    def initialize(self):
        # Set the matplotlib backend to one which we can actually update
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

        from acadia.processing import DynamicLine
        import matplotlib.pyplot as plt
        from IPython.display import display
        from ipywidgets import Label
        from tqdm.notebook import tqdm

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

        self.iterations_progress_bar = tqdm(desc="Iterations", dynamic_ncols=True, total=self.iterations)
        self.iterations_previous = 0
        self.frequencies_progress_bar = tqdm(desc="Frequencies", dynamic_ncols=True, total=len(self.frequencies))
        self.frequencies_previous = 0

    def update(self):
        import numpy as np
        from scipy.optimize import curve_fit
        from acadia.arrays import Waveform

        # First make sure that we actually have new data to process
        if "traces" not in self.data:
            return
        
        # Update the progress bar based on the number of iterations
        completed_iterations = len(self.data["traces"]) // len(self.frequencies)
        self.iterations_progress_bar.update(completed_iterations - self.iterations_previous)
        self.iterations_previous = completed_iterations

        completed_frequencies = len(self.data["traces"]) % len(self.frequencies)
        self.frequencies_progress_bar.update(completed_frequencies - self.frequencies_previous)
        self.frequencies_previous = completed_frequencies

        # Only continue processing data if we have at least one complete iteration
        if completed_iterations == 0:
            return
        
        valid_traces = completed_iterations*len(self.frequencies)
        data = self.data["traces"].records()[:valid_traces, ...]

        # Get the collection of data and reshape it so that the axes index as: 
        # (iteration, frequency, sample time, sample quadrature)
        samples_per_trace = data.shape[-2]
        self.data_reshaped = data.reshape(-1, len(self.frequencies), samples_per_trace, 2)
        
        # Sum all the samples in a given trace and sum all the 
        # iterations together for SNR
        # TODO: we could do this much more intelligently by only adding the new traces
        # that have been received since the last update, but for simplicity we'll leave it as is
        self.data_summed = np.sum(self.data_reshaped, axis=(0,2))

        # Convert the summed sample data to a complex number and choose 
        # the scale so that we turn the sum into an average
        # At the same time, we'll remove the length-of-1 dimensions
        self.data_complex = np.squeeze(Waveform.sample_to_complex(self.data_summed))

        # Apply the electrical delay
        self.data_complex *= np.exp(2*np.pi*1j*self.frequencies*self.plot_electrical_delay)

        # We now have a 1D array of the amplitudes as a function of frequency,
        # so we can do whatever processing we want
        mags = np.abs(self.data_complex)
        phases = np.unwrap(np.angle(self.data_complex))
        self.line_mag.update(self.frequencies, mags)
        self.line_phase.update(self.frequencies, phases)

        # Update the fit
        def model(freqs, delay, phi0):
            return 2*np.pi*freqs*delay + phi0
    
        popt,pcov = curve_fit(model, self.frequencies, phases)
        self._delay_label.value = f"Electrical delay = {round(popt[0]*1e9,1)} ns +/- {round(pcov[0,0]*1e12)} ps"

        # Update the plot itself
        self.fig.canvas.draw_idle()

        # Save the data
        self.data.save(self.local_directory)

    def finalize(self):
        super().finalize()
        self.iterations_progress_bar.close()
        self.frequencies_progress_bar.close()


if __name__ == "__main__":
    import numpy as np

    stimulus: dict = {
        "channel": "DAC1",

        "datapath": {
            "vop": 12000,
            "nyquist_zone": 2
        },

        "waveform": {
            "length": 1e-6,
            "flat_top_length": 1e-6
        },
        
        "signal": {
            "data": ("scipy", "hann"),
            "scale": 0.01
        }
    }
    
    capture: dict = {
        "channel": "ADC1",

        "datapath": {
            "nyquist_zone": 2
        },

        "waveform": {
            "length": 4e-6,
            "decimation": 0,
            "region": "plddr"
        }
    }
    
    # Run the program on the target
    rt = SpectroscopyRuntime(frequencies=np.linspace(4.55e9, 4.9e9, 101),
                            stimulus=stimulus,
                            capture=capture,
                            iterations=1000,
                            plot_electrical_delay=60e-9)
    rt.deploy("192.168.2.69", "spectroscopy", files=[__file__])    
    rt.display()
    
