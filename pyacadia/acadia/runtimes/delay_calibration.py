from dataclasses import dataclass
from acadia import Runtime, WaveformMemory

from scipy.signal import find_peaks
from scipy.optimize import curve_fit

def linear(x, m, b):
    return m*x + b

@dataclass
class DelayCalibrationRuntime(Runtime):
    """
    A :class:`Runtime` subclass for calibrating delays between synchronizers.
    """

    stimulus: dict
    capture: dict
    iterations: int
    delays: list[int]
    figsize: tuple[int] = (4,8)
    procedure: int = 0
        
    def main(self):     
        import numpy as np
        from acadia import Acadia, DataManager
        
        # Create an acadia object and grab a couple of its channels
        acadia = Acadia()
        stimulus_channel = acadia.channel(self.stimulus["channel"])
        second_stimulus_channel = acadia.channel("DAC3")
        capture_channel = acadia.channel(self.capture["channel"])

        # Create the waveforms that we'll need 
        stimulus_waveform = acadia.create_waveform_memory(stimulus_channel, **self.stimulus["waveform"])
        second_stimulus_waveform = acadia.create_waveform_memory(second_stimulus_channel, **self.stimulus["waveform"])
        capture_waveform = acadia.create_waveform_memory(capture_channel, **self.capture["waveform"]) 

        # Create an array in the cache that we can use to load in the 
        # delay value so that we don't have to reassemble every time
        cache = acadia.CacheArray(shape=(1,), dtype=np.dtype("<i4"))

        # Create a record group for saving captured data
        self.data.add_group("traces", uniform=True)
                
        # Create a sequence for the sequencer to generate the pulse and capture it
        def sequence(a: Acadia):
            if self.procedure == 0:
                # Initialize a DSP to act as a counter
                counter = acadia.sequencer().DSP()

                # Start capturing right away and don't block
                capture_stream = acadia.configure_dsp(capture_channel, self.capture["waveform"]["decimation"])
                with a.channel_synchronizer(block=False):
                    a.stream(capture_stream, capture_waveform)

                # Play the first pulse and block until it's done
                with a.channel_synchronizer():
                    a.schedule_waveform(stimulus_waveform)
                
                # Start the counter and wait until the counter equals the cache value
                # Note that in this situation, the compiler is not able to determine whether
                # the DSP value or the cache value should be loaded into the mask register,
                # since either one could be changing over time. However, we know that the 
                # cache value should be constant for this program; therefore, we manually tell
                # the compiler that the cache value should be put into the mask by indicating
                # that the right argument is to be used.
                counter.start_count(clear=True)
                with a.sequencer().repeat_until(counter == cache[0], mask="right"):
                    pass

                # Play the second pulse (and this time we'll block)
                with a.channel_synchronizer():
                    a.schedule_waveform(stimulus_waveform)

            elif self.procedure == 1:
                # Load the DSP at the start and then count down
                # Initialize a DSP to act as a counter
                counter = acadia.sequencer().DSP()

                # Load the counter with the value we put into the cache
                counter.load(cache[0])

                # Start capturing right away and don't block
                capture_stream = acadia.configure_dsp(capture_channel, self.capture["waveform"]["decimation"])
                with a.channel_synchronizer(block=False):
                    a.stream(capture_stream, capture_waveform)

                # Play the first pulse and block until it's done
                with a.channel_synchronizer():
                    a.schedule_waveform(stimulus_waveform)
                
                # Start the counter and wait until it reaches zero
                counter.start_count(inc=int(np.int32(-1).astype(np.uint32)))
                with a.sequencer().repeat_until(counter == 0):
                    pass

                # Play the second pulse (and this time we'll block)
                with a.channel_synchronizer():
                    a.schedule_waveform(stimulus_waveform)

            elif self.procedure == 2:
                # Amortize the delay with the playing of the first pulse
                # Initialize a DSP to act as a counter
                counter = acadia.sequencer().DSP()

                # Load the counter with the value we put into the cache
                counter.load(cache[0])

                # Start capturing right away and don't block
                capture_stream = acadia.configure_dsp(capture_channel, self.capture["waveform"]["decimation"])
                with a.channel_synchronizer(block=False):
                    a.stream(capture_stream, capture_waveform)

                # Play the first pulse and again don't block
                with a.channel_synchronizer(block=False):
                    a.schedule_waveform(stimulus_waveform)
                
                # Start the counter and wait until it reaches zero
                counter.start_count(inc=int(np.int32(-1).astype(np.uint32)))
                with a.sequencer().repeat_until(counter == 0):
                    pass

                # Play the second pulse (and this time we'll block)
                with a.channel_synchronizer():
                    a.schedule_waveform(stimulus_waveform)

            elif self.procedure == 3:
                # Same as 2, but with the second pulse on a different channel
                # Initialize a DSP to act as a counter
                counter = acadia.sequencer().DSP()

                # Load the counter with the value we put into the cache
                counter.load(cache[0])

                # Start capturing right away and don't block
                capture_stream = acadia.configure_dsp(capture_channel, self.capture["waveform"]["decimation"])
                with a.channel_synchronizer(block=False):
                    a.stream(capture_stream, capture_waveform)

                # Play the first pulse and again don't block
                with a.channel_synchronizer(block=False):
                    a.schedule_waveform(stimulus_waveform)
                
                # Start the counter and wait until it reaches zero
                counter.start_count(inc=int(np.int32(-1).astype(np.uint32)))
                with a.sequencer().repeat_until(counter == 0):
                    pass

                # Play the second pulse (and this time we'll block)
                with a.channel_synchronizer():
                    a.schedule_waveform(second_stimulus_waveform)


        # Compile the sequence
        acadia.compile(sequence)
                
        # Attach to the hardware
        acadia.attach()

        # Configure channel analog parameters
        stimulus_channel.set(nco_update_event_source="immediate", **self.stimulus["datapath"])
        second_stimulus_channel.set(nco_update_event_source="immediate", **self.stimulus["datapath"])
        capture_channel.set(nco_update_event_source="immediate", **self.capture["datapath"])
        stimulus_channel.nco_immediate_update_event()
        second_stimulus_channel.nco_immediate_update_event()
        capture_channel.nco_immediate_update_event()

        # Populate the stimulus with data
        stimulus_waveform.set(**self.stimulus["signal"])
        second_stimulus_waveform.set(**self.stimulus["signal"])

        # Assemble and load the program
        acadia.assemble()
        acadia.load()

        import time
        for i in range(self.iterations):
            for delay in self.delays:
                cache[0] = delay

                acadia.run()
                time.sleep(0.001)
                self.data["traces"].write(capture_waveform.array)
            
            if self.data.serve() == DataManager.serve_hangup():
                self.data.disconnect()
                return
        
        self.final_serve()

    def initialize(self):
        # Set the matplotlib backend to one which we can actually update
        from acadia.processing import DynamicLine
        import matplotlib.pyplot as plt
        from tqdm.notebook import tqdm

        self.fig, self.ax = plt.subplots(2, 1, figsize=self.figsize)
        self.fig.tight_layout()
        self.fig.subplots_adjust(hspace=0.4, left=0.25, bottom=0.25)

        self.lines = []
        self.peak_locations = []
        colors = ["blue"]
        for delay in self.delays:
            self.lines.append(DynamicLine(self.ax[0], ".-", label=f"{delay}"))
            self.peak_locations.append(DynamicLine(self.ax[0], color="black"))
        self.ax[0].set_xlabel("Time [s]")
        self.ax[0].set_ylabel("Signal Amplitude [arb. V]")
        self.ax[0].grid()

        self.aggregated_line = DynamicLine(self.ax[1], ".-")
        self.ax[1].set_xlabel("Programmed Delay [cycles]")
        self.ax[1].set_ylabel("Actual Delay [cycles]")
        self.ax[1].grid()

        self.time_axis = None

        self.progress_bar = tqdm(desc="Iterations", dynamic_ncols=True, total=self.iterations)
        self.previous_completed_iterations = 0

        self.data_summed = None
        self.data_complex = None

    def update(self):
        import numpy as np

        # First make sure that we actually have new data to process
        if "traces" not in self.data or len(self.data["traces"]) == 0:
            return


        # Update the progress bar based on the number of iterations that have been completed
        completed_iterations = len(self.data["traces"]) // len(self.delays)
        self.progress_bar.update(completed_iterations - self.previous_completed_iterations)
                
        if completed_iterations != 0:
            # Get the collection of data and reshape it so that the axes index as: 
            # (iteration, frequency, sample time, sample quadrature)
            valid_traces = completed_iterations*len(self.delays)
            data = self.data["traces"].records()[:valid_traces, ...]
            samples_per_trace = data.shape[-2]
            data_reshaped = data.reshape(-1, len(self.delays), samples_per_trace, 2)

            if self.time_axis is None:
                self.time_axis = np.linspace(0, self.capture["waveform"]["length"], samples_per_trace, endpoint=False)
            
            # Slice the data so that we have an array containing only the traces
            # we didn't have the last time update() was called
            self.new_data = data_reshaped[self.previous_completed_iterations:, :, :, :]

            # Sum the new data and then add it to the aggregated array of trace data
            new_data_summed = np.sum(self.new_data, axis=0, keepdims=False)
            if self.data_summed is None:
                self.data_summed = new_data_summed
            else:
                self.data_summed += new_data_summed

            # Convert the summed sample data to a complex number and choose 
            # the scale so that we turn the sum into a mean
            self.data_complex = WaveformMemory.sample_to_complex(self.data_summed, scale=float(completed_iterations))
            self.data_mags = np.abs(self.data_complex)
            
            for idx,_ in enumerate(self.delays):
                self.lines[idx].update(self.time_axis, self.data_mags[idx,:])

            self.ax[0].relim()
            self.ax[0].autoscale(tight=True)

            
            self.measured_delays = np.empty(len(self.delays), dtype=np.float64)
            for idx,delay in enumerate(self.delays):
                peaks, peak_properties = find_peaks(self.data_mags[idx,:], width=7)
                peak_time = self.time_axis[peaks[-1]]
                self.peak_locations[idx].update([peak_time, peak_time], self.ax[0].get_ylim())
                self.measured_delays[idx] = peak_time - self.time_axis[peaks[0]]
            
            self.aggregated_line.update(self.delays, self.measured_delays)
            self.fit, pcov = curve_fit(linear, self.delays, self.measured_delays)

            # The code above measures the time between pulse centers. To get all of the added delay
            # due to the synchronizers and DSP, subtract off the pulse time so that we get
            # the time between end of pulse 1 and start of pulse 2
            self.extra_delay = self.fit[1] - self.stimulus["waveform"]["length"]

            self.ax[1].relim()
            self.ax[1].autoscale(tight=True)
            self.fig.canvas.draw_idle()

        self.previous_completed_iterations = completed_iterations

    def finalize(self):
        super().finalize()
        self.progress_bar.close()

def run(plot=True):   
    stimulus: dict = {
        "channel": "DAC1",

        "datapath": {
            "vop": 4000,
            "mix_reconstruction": True,
            "nco_frequency": 4.4e9
        },

        "waveform": {
            "length": 20e-9,
        },
        
        "signal": {
            "data": "hann",
            "scale": 0.9
        }
    }

    capture: dict = {
        "channel": "ADC1",

        "datapath": {
            "nco_frequency": 4.4e9
        },

        "waveform": {
            "length": 1.2e-6,
            "decimation": 1,
            "region": "plddr"
        }
    }

    import numpy as np
    delays = np.arange(2, 102, 2, dtype=np.int32)

    if plot:
        # Set the matplotlib backend to one which we can actually update
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

    rt = DelayCalibrationRuntime(stimulus, capture, procedure=3, delays=delays, iterations=100000)
    rt.deploy("192.168.2.69")    
    rt.display()

    return rt

if __name__ == "__main__":
    rt = run()
    
