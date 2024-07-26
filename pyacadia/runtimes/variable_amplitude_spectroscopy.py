from dataclasses import dataclass

from acadia.runtime import Runtime

@dataclass
class VariableAmplitudeSpectroscopyRuntime(Runtime):
    """
    A :class:`Runtime` subclass for performing swept spectroscopy.
    """
    
    frequencies: list 
    amplitudes: list
    stimulus: dict
    capture: dict
    plot_electrical_delay: float = 0 
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

        acadia.load(*acadia.assemble())

        for i in range(self.iterations):
            for amplitude in self.amplitudes:
                self.stimulus["signal"]["scale"] = amplitude
                stimulus.set(**self.stimulus["signal"])
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
        import matplotlib.colors as colors
        import matplotlib.cm as cm
        from IPython.display import display
        from ipywidgets import Label
        from tqdm.notebook import tqdm

        self.fig,ax = plt.subplots(1,2, figsize=(7,3))
        self.fig.subplots_adjust(hspace=0.35)
        self.fig.tight_layout()

        # Create a plot for the spectral magnitude
        cmap = plt.get_cmap("Spectral")
        norm = colors.LogNorm(self.amplitudes[0], self.amplitudes[-1])
        sm = cm.ScalarMappable(norm, cmap)
        self.lines_mag = [DynamicLine(ax[0], ".-", c=sm.to_rgba(a)) for a in self.amplitudes]
        ax[0].set_xlabel("Frequency [MHz]")
        ax[0].set_ylabel("Magnitude [arb. V*s]")
        ax[0].set_title("Spectral Magnitude")
        ax[0].grid()
        
        # Create a plot for the spectral phase
        self.lines_phase = [DynamicLine(ax[1], ".-", c=sm.to_rgba(a)) for a in self.amplitudes]
        ax[1].set_xlabel("Frequency [MHz]")
        ax[1].set_ylabel("Phase [rad.]")
        ax[1].set_title("Spectral Phase")
        ax[1].grid()

        # Create a label for displaying the electrical delay
        self._delay_label = Label("Electrical delay: ")
        display(self._delay_label)

        self.iterations_progress_bar = tqdm(desc="Iterations", dynamic_ncols=True, total=self.iterations)
        self.iterations_previous = 0
        self.amplitudes_progress_bar = tqdm(desc="Amplitudes", dynamic_ncols=True, total=len(self.amplitudes))
        self.amplitudes_previous = 0
        self.frequencies_progress_bar = tqdm(desc="Frequencies", dynamic_ncols=True, total=len(self.frequencies))
        self.frequencies_previous = 0


    def update(self):
        import numpy as np
        from acadia.waveforms import Waveform

        # First make sure that we actually have new data to process
        if "traces" not in self.data:
            return
        
        # Update the progress bars
        completed_iterations = len(self.data["traces"]) // (len(self.frequencies)*len(self.amplitudes))
        self.iterations_progress_bar.update(completed_iterations - self.iterations_previous)
        self.iterations_previous = completed_iterations

        extra_traces = len(self.data["traces"]) % (len(self.frequencies)*len(self.amplitudes))

        completed_amplitudes = extra_traces // len(self.frequencies)
        self.amplitudes_progress_bar.update(completed_amplitudes - self.amplitudes_previous)
        self.amplitudes_previous = completed_amplitudes

        completed_frequencies = extra_traces % len(self.frequencies)
        self.frequencies_progress_bar.update(completed_frequencies - self.frequencies_previous)
        self.frequencies_previous = completed_frequencies

        # Only continue processing data if we have at least one complete iteration
        if completed_iterations == 0:
            return
        
        valid_traces = completed_iterations*len(self.frequencies)*len(self.amplitudes)
        data = self.data["traces"].records()[:valid_traces, ...]

        samples_per_trace = data.shape[-2]
        self.data_reshaped = data.reshape(-1, len(self.amplitudes), len(self.frequencies), samples_per_trace, 2)
        self.data_summed = np.sum(self.data_reshaped, axis=(0,3))

        # Apply the electrical delay and update lines
        # Don't rescale the plot when updating the lines, we'll do it all at once when we have the 
        for idx,amp in enumerate(self.amplitudes):
            spectrum = np.squeeze(Waveform.sample_to_complex(self.data_summed[idx, ...], scale=amp))
            spectrum *= np.exp(2*np.pi*1j*self.frequencies*self.plot_electrical_delay)
            self.lines_mag[idx].update(self.frequencies, np.abs(spectrum), rescale_axis=False)
            self.lines_phase[idx].update(self.frequencies, np.unwrap(np.angle(spectrum)), rescale_axis=False)

        # Rescale axes and redraw plot
        self.lines_mag[0]._ax.relim()
        self.lines_mag[0]._ax.autoscale(tight=True)
        self.lines_phase[0]._ax.relim()
        self.lines_phase[0]._ax.autoscale(tight=True)
        self.fig.canvas.draw_idle()

    def finalize(self):
        super().finalize()
        self.iterations_progress_bar.close()
        self.amplitudes_progress_bar.close()
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
            "scale": 1
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
    
    frequencies = np.linspace(4.55e9, 4.9e9, 101)
    amplitudes = np.logspace(-2, 0, 21)

    # Run the program on the target
    rt = VariableAmplitudeSpectroscopyRuntime(frequencies=frequencies,
                             amplitudes=amplitudes,
                            stimulus=stimulus,
                            capture=capture,
                            iterations=1000,
                            plot_electrical_delay=60e-9)
    rt.deploy("192.168.2.69", "variable_amplitude_spectroscopy", files=[__file__])    
    rt.display()
    
