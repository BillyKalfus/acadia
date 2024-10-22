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
    plot: bool = False
    electrical_delay: float = 0 
    iterations: int = 10
        
    def main(self):        
        from itertools import product
        from acadia import Acadia, DataManager
        
        acadia = Acadia()
        stimulus_channel = acadia.channel(self.stimulus["channel"])
        capture_channel = acadia.channel(self.capture["channel"])

        stimulus_waveform = acadia.create_waveform(stimulus_channel, **self.stimulus["waveform"])
        capture_waveform = acadia.create_waveform(capture_channel, decimation=0, **self.capture["waveform"]) 
                
        self.data.add_group("traces", uniform=True)
                
        def sequence(a: Acadia):
            capture_stream, kernel = acadia.configure_cmacc(capture_channel, reset_fifo=True)
            acadia.cmacc_load(capture_stream, 0)

            with a.channel_synchronizer():
                a.schedule_waveform(stimulus_waveform)
                a.stream(capture_stream, capture_waveform)

            return kernel

        kernel = acadia.compile(sequence)
        acadia.attach()
        acadia.align_tile_latencies()

        # When we set the channel properties, configure the NCO for synchronization
        stimulus_channel.set(nco_update_event_source="sysref", **self.stimulus["datapath"])
        capture_channel.set(nco_update_event_source="sysref", **self.capture["datapath"])

        import numpy as np
        kernel.set(np.float64(0.1))

        acadia.assemble()
        acadia.load()

        for i,amplitude in product(range(self.iterations), self.amplitudes):
            self.stimulus["signal"]["scale"] = amplitude
            stimulus_waveform.set(**self.stimulus["signal"])
            for frequency in self.frequencies:
                # Synchronously set the modulation frequencies and reset phases
                acadia.update_nco_frequency(stimulus_channel, frequency=frequency)
                acadia.update_nco_frequency(capture_channel, frequency=-frequency)
                acadia.reset_nco_phase(stimulus_channel)
                acadia.reset_nco_phase(capture_channel)
                acadia.update_ncos_synchronized()

                acadia.run()
                self.data["traces"].write(capture_waveform.array)
        
                if self.data.serve() == DataManager.serve_hangup():
                    self.data.disconnect()
                    return
        
        self.final_serve()

    def initialize(self):
        if self.plot:
            from acadia import DynamicLine
            import matplotlib.pyplot as plt
            import matplotlib.colors as colors
            import matplotlib.cm as cm

            self.fig = plt.figure(figsize=(8,3))
            gs = self.fig.add_gridspec(1, 2, bottom=0.2, right=0.8, width_ratios=[20, 1], wspace=0.1)
            gs_plots = gs[0].subgridspec(1, 2, wspace=0.35)
            ax_mag, ax_phase = gs_plots.subplots()
            ax_colorbar = self.fig.add_subplot(gs[1])

            # Create some colors for the various amplitudes
            cmap = plt.get_cmap("Spectral")
            norm = colors.LogNorm(self.amplitudes[0], self.amplitudes[-1])
            sm = cm.ScalarMappable(norm, cmap)

            # Create a plot for the spectral magnitude
            self.lines_mag = [DynamicLine(ax_mag, ".-", c=sm.to_rgba(a)) for a in self.amplitudes]
            ax_mag.set_xlabel("Frequency [MHz]")
            ax_mag.set_ylabel("Magnitude [arb. V*s]")
            ax_mag.set_title("Spectral Magnitude")
            ax_mag.grid()
            
            # Create a plot for the spectral phase
            self.lines_phase = [DynamicLine(ax_phase, ".-", c=sm.to_rgba(a)) for a in self.amplitudes]
            ax_phase.set_xlabel("Frequency [MHz]")
            ax_phase.set_ylabel("Phase [rad.]")
            ax_phase.set_title("Spectral Phase")
            ax_phase.grid()

            # Create a colorbar
            self.fig.colorbar(sm, cax=ax_colorbar, label="Amplitude")

            from tqdm.notebook import tqdm

        else:
            from tqdm import tqdm
        self.iterations_progress_bar = tqdm(desc="Iterations", dynamic_ncols=True, total=self.iterations)
        self.iterations_previous = 0
        self.amplitudes_progress_bar = tqdm(desc="Amplitude Sweep Points", dynamic_ncols=True, total=len(self.amplitudes)*self.iterations)
        self.amplitudes_previous = 0
        self.frequencies_progress_bar = tqdm(desc="Frequency Sweep Points", dynamic_ncols=True, total=len(self.frequencies)*len(self.amplitudes)*self.iterations)
        self.frequencies_previous = 0

        import numpy as np
        self.data_summed = None
        self.data_complex = np.empty((len(self.amplitudes), len(self.frequencies)), dtype=np.complex128)
        self.electrical_delay_phases = np.exp(2*np.pi*1j*self.frequencies*self.electrical_delay)

    def update(self):
        import numpy as np
        from acadia.waveforms import Waveform

        # First make sure that we actually have new data to process
        if "traces" not in self.data:
            return
        
        # Update the progress bars
        completed_iterations = len(self.data["traces"]) // (len(self.frequencies)*len(self.amplitudes))
        self.iterations_progress_bar.update(completed_iterations - self.iterations_previous)

        completed_amplitudes = len(self.data["traces"]) // len(self.frequencies)
        self.amplitudes_progress_bar.update(completed_amplitudes - self.amplitudes_previous)

        completed_frequencies = len(self.data["traces"])
        self.frequencies_progress_bar.update(completed_frequencies - self.frequencies_previous)

        # Only continue processing data if we have at least one complete iteration
        if completed_iterations != 0:
            valid_traces = completed_iterations*len(self.frequencies)*len(self.amplitudes)
            data = self.data["traces"].records()[:valid_traces, ...]

            samples_per_trace = data.shape[-2]
            data_reshaped = data.reshape(-1, len(self.amplitudes), len(self.frequencies), samples_per_trace, 2)
            new_data = data_reshaped[self.iterations_previous:, :, :, :, :]

            # Sum the new data and then add it to the aggregated array of trace data
            new_data_summed = np.sum(new_data, axis=(0,3), keepdims=False)
            if self.data_summed is None:
                self.data_summed = new_data_summed
            else:
                self.data_summed += new_data_summed
            
            for idx,amp in enumerate(self.amplitudes):
                scale = amp / completed_iterations
                self.data_complex[idx, :] = Waveform.sample_to_complex(self.data_summed[idx, :], scale=scale)

            # Apply the electrical delay
            self.data_complex *= self.electrical_delay_phases

            if self.plot:
                for idx,amp in enumerate(self.amplitudes):
                    # Don't rescale the plot when updating the lines, we'll do it all at once when we have the full plot
                    self.lines_mag[idx].update(self.frequencies, np.abs(self.data_complex[idx,:]), rescale_axis=False)
                    self.lines_phase[idx].update(self.frequencies, np.angle(self.data_complex[idx,:]), rescale_axis=False)

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

    stimulus: dict = {
        "channel": "DAC4",

        "datapath": {
            "vop": 4000,
            "nyquist_zone": 2
        },

        "waveform": {
            "length": 128e-9,
            "fixed_length": 10e-6
        },
        
        "signal": {
            "data": ("scipy", "hann"),
            "scale": 0.5
        }
    }

    capture: dict = {
        "channel": "ADC4",

        "datapath": {
            "nyquist_zone": 1
        },

        "waveform": {
            "length": 10e-6,
            "region": "plddr"
        }
    }

    frequencies = np.linspace(9.15e9, 9.25e9, 201)
    amplitudes = np.linspace(0.2, 0.8, 4)

    # Run the program on the target
    rt = VariableAmplitudeSpectroscopyRuntime(
        frequencies=frequencies,
        amplitudes=amplitudes,
        stimulus=stimulus,
        capture=capture,
        iterations=1000,
        plot=plot,
        electrical_delay=108e-9)
    
    if plot:
        # Set the matplotlib backend to one which we can actually update
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

    rt.deploy("192.168.2.70")    
    rt.display()
    
    return rt

if __name__ == "__main__":
    rt = run()
    
