from dataclasses import dataclass

from acadia.runtime import Runtime

@dataclass
class FixedStimulusVariableAmplitudeSpectroscopyRuntime(Runtime):
    """
    A :class:`Runtime` for measuring the response of a system
    when sweeping the frequency and amplitude of a probe tone that is NOT
    the spectroscopic stimulus.
    """
    
    probe_frequencies: list 
    probe_amplitudes: list
    probe: dict
    stimulus: dict
    capture: dict
    plot: bool = False
    iterations: int = 10
        
    def main(self):        
        from acadia.system import Acadia
        
        acadia = Acadia()
        probe_channel = acadia.channel(self.probe["channel"])
        stimulus_channel = acadia.channel(self.stimulus["channel"])
        capture_channel = acadia.channel(self.capture["channel"])

        probe_waveform = acadia.create_waveform(probe_channel, **self.probe["waveform"])
        stimulus_waveform = acadia.create_waveform(stimulus_channel, **self.stimulus["waveform"])
        capture_waveform = acadia.create_waveform(capture_channel, decimation=0, **self.capture["waveform"]) 
                
        self.data.add_group("traces", uniform=True)
                
        def sequence(a: Acadia):
            capture_stream, kernel = acadia.configure_cmacc(capture_channel, reset_fifo=True)
            acadia.cmacc_load(capture_stream, 0)

            with a.channel_synchronizer():
                a.schedule_waveform(probe_waveform)
                a.barrier()
                a.schedule_waveform(stimulus_waveform)
                a.stream(capture_stream, capture_waveform)

            return kernel

        kernel = acadia.compile(sequence)
        acadia.attach()
        acadia.align_tile_latencies()

        # We don't need sysref synchronization here, since the stimulus
        # and capture frequencies aren't changing once being set initially
        probe_channel.set(**self.probe["datapath"])
        stimulus_channel.set(**self.stimulus["datapath"])
        capture_channel.set(**self.capture["datapath"])

        # Synchronize the phases of the DAC and ADC NCOs
        acadia.reset_nco_phase(stimulus_channel)
        acadia.reset_nco_phase(capture_channel)
        acadia.update_ncos_synchronized()

        # Load the stimulus waveform
        stimulus_waveform.set(**self.stimulus["signal"])

        import numpy as np
        kernel.set(np.float64(0.1))

        acadia.load(*acadia.assemble())

        for i in range(self.iterations):
            for amplitude in self.probe_amplitudes:
                self.probe["signal"]["scale"] = amplitude
                probe_waveform.set(**self.probe["signal"])
                for frequency in self.probe_frequencies:
                    probe_channel.set_nco(frequency=frequency)                    
                    acadia.run(assemble=False)
                    self.data["traces"].write(capture_waveform.array)            
                    self.data.serve()

    def initialize(self):
        if self.plot:
            # Set the matplotlib backend to one which we can actually update
            from IPython.core.getipython import get_ipython
            get_ipython().run_line_magic("matplotlib", "widget")

            from acadia.processing import DynamicLine
            import matplotlib.pyplot as plt
            import matplotlib.colors as colors
            import matplotlib.cm as cm
            from IPython.display import display
            from ipywidgets import Label

            self.fig,ax = plt.subplots(1,2, figsize=(7,3))
            self.fig.subplots_adjust(hspace=0.35)
            self.fig.tight_layout()

            # Create a plot for the spectral magnitude
            cmap = plt.get_cmap("Spectral")
            norm = colors.LogNorm(self.probe_amplitudes[0], self.probe_amplitudes[-1])
            sm = cm.ScalarMappable(norm, cmap)
            self.lines_mag = [DynamicLine(ax[0], ".-", c=sm.to_rgba(a)) for a in self.probe_amplitudes]
            ax[0].set_xlabel("Frequency [MHz]")
            ax[0].set_ylabel("Magnitude [arb. V*s]")
            ax[0].set_title("Spectral Magnitude")
            ax[0].grid()
            
            # Create a plot for the spectral phase
            self.lines_phase = [DynamicLine(ax[1], ".-", c=sm.to_rgba(a)) for a in self.probe_amplitudes]
            ax[1].set_xlabel("Frequency [MHz]")
            ax[1].set_ylabel("Phase [rad.]")
            ax[1].set_title("Spectral Phase")
            ax[1].grid()

            # Create a label for displaying the electrical delay
            self._delay_label = Label("Electrical delay: ")
            display(self._delay_label)
            from tqdm.notebook import tqdm

        else:
            from tqdm import tqdm
        self.iterations_progress_bar = tqdm(desc="Iterations", dynamic_ncols=True, total=self.iterations)
        self.iterations_previous = 0
        self.amplitudes_progress_bar = tqdm(desc="Amplitude Sweep Points", dynamic_ncols=True, total=len(self.probe_amplitudes)*self.iterations)
        self.amplitudes_previous = 0
        self.frequencies_progress_bar = tqdm(desc="Frequency Sweep Points", dynamic_ncols=True, total=len(self.probe_frequencies)*len(self.probe_amplitudes)*self.iterations)
        self.frequencies_previous = 0

        import numpy as np
        self.data_summed = None
        self.data_complex = np.empty((len(self.probe_amplitudes), len(self.probe_frequencies)), dtype=np.complex128)

    def update(self):
        import numpy as np
        from acadia.waveforms import Waveform

        # First make sure that we actually have new data to process
        if "traces" not in self.data:
            return
        
        # Update the progress bars
        completed_iterations = len(self.data["traces"]) // (len(self.probe_frequencies)*len(self.probe_amplitudes))
        self.iterations_progress_bar.update(completed_iterations - self.iterations_previous)

        completed_amplitudes = len(self.data["traces"]) // len(self.probe_frequencies)
        self.amplitudes_progress_bar.update(completed_amplitudes - self.amplitudes_previous)

        completed_frequencies = len(self.data["traces"])
        self.frequencies_progress_bar.update(completed_frequencies - self.frequencies_previous)

        # Only continue processing data if we have at least one complete iteration
        if completed_iterations != 0:
        
            valid_traces = completed_iterations*len(self.probe_frequencies)*len(self.probe_amplitudes)
            data = self.data["traces"].records()[:valid_traces, ...]

            samples_per_trace = data.shape[-2]
            data_reshaped = data.reshape(-1, len(self.probe_amplitudes), len(self.probe_frequencies), samples_per_trace, 2)
            new_data = data_reshaped[self.iterations_previous:, :, :, :, :]

            # Sum the new data and then add it to the aggregated array of trace data
            new_data_summed = np.sum(new_data, axis=(0,3), keepdims=False)
            if self.data_summed is None:
                self.data_summed = new_data_summed
            else:
                self.data_summed += new_data_summed
            
            self.data_complex = Waveform.sample_to_complex(self.data_summed, scale=1/completed_iterations)

            if self.plot:
                for idx,amp in enumerate(self.probe_amplitudes):
                    # Don't rescale the plot when updating the lines, we'll do it all at once when we have the full plot
                    self.lines_mag[idx].update(self.probe_frequencies, np.abs(self.data_complex[idx,:]), rescale_axis=False)
                    self.lines_phase[idx].update(self.probe_frequencies, np.unwrap(np.angle(self.data_complex[idx,:])), rescale_axis=False)

                # Rescale axes and redraw plot
                self.lines_mag[0]._ax.relim()
                self.lines_mag[0]._ax.autoscale(tight=True)
                self.lines_phase[0]._ax.relim()
                self.lines_phase[0]._ax.autoscale(tight=True)
                self.fig.canvas.draw_idle()

        self.iterations_previous = completed_iterations
        self.amplitudes_previous = completed_amplitudes
        self.frequencies_previous = completed_frequencies

    def finalize(self):
        super().finalize()
        self.iterations_progress_bar.close()
        self.amplitudes_progress_bar.close()
        self.frequencies_progress_bar.close()

def run(plot=True):
    import numpy as np

    probe: dict = {
        "channel": "DAC2",

        "datapath": {
            "vop": 36000,
            "nyquist_zone": 2,
            "nco": {
                "update_source": "immediate"
            }
        },

        "waveform": {
            "length": 1e-6,
            "fixed_length": 1e-3
        },
        
        "signal": {
            "data": ("scipy", "hann"),
        }
    }

    stimulus: dict = {
        "channel": "DAC4",

        "datapath": {
            "vop": 4000,
            "nyquist_zone": 2,
            "nco": {
                "update_source": "sysref",
                "frequency": 9.2153e9
            }
        },

        "waveform": {
            "length": 128e-9,
            "fixed_length": 2e-6
        },
        
        "signal": {
            "data": ("scipy", "hann"),
            "scale": 0.8
        }
    }

    capture: dict = {
        "channel": "ADC4",

        "datapath": {
            "nyquist_zone": 1,
            "nco": {
                "update_source": "sysref",
                "frequency": -9.2153e9
            }
        },

        "waveform": {
            "length": 2e-6,
            "region": "plddr"
        }
    }

    probe_frequencies = np.linspace(4.2e9, 4.6e9, 401)
    probe_amplitudes = np.linspace(0.2, 0.8, 4)

    # Run the program on the target
    rt = FixedStimulusVariableAmplitudeSpectroscopyRuntime(
        probe_frequencies=probe_frequencies,
        probe_amplitudes=probe_amplitudes,
        probe=probe,
        stimulus=stimulus,
        capture=capture,
        iterations=1000,
        plot=plot)
    rt.deploy("192.168.2.70", "fixed_stimulus_variable_amplitude_spectroscopy", files=[__file__], log_debug=True)    
    rt.display()
    
    return rt

if __name__ == "__main__":
    rt = run()
    
