from dataclasses import dataclass
from acadia.runtime import Runtime

@dataclass
class LoopbackRuntime(Runtime):
    """
    A :class:`Runtime` subclass for sending a signal out of a DAC and capturing
    it on an ADC.
    """

    stimulus: dict
    capture: dict
    iterations: int
        
    def main(self):     
        from acadia.system import Acadia
        
        # Create an acadia object and grab a couple of its channels
        acadia = Acadia()
        stimulus_channel = acadia.channel(self.stimulus["channel"])
        capture_channel = acadia.channel(self.capture["channel"])

        # Create the waveforms that we'll need 
        stimulus_waveform = acadia.create_waveform(stimulus_channel, **self.stimulus["waveform"])
        capture_waveform = acadia.create_waveform(capture_channel, **self.capture["waveform"]) 
        
        # Create a record group for saving captured data
        self.data.add_group("traces", uniform=True)
                
        # Create a sequence for the sequencer to generate the pulse and capture it
        def sequence(a: Acadia):
            capture_stream = acadia.configure_dsp(capture_channel, self.capture["waveform"]["decimation"])

            with a.channel_synchronizer():
                a.schedule_waveform(stimulus_waveform)
                a.stream(capture_stream, capture_waveform)

        # Compile the sequence
        acadia.compile(sequence)
                
        # Attach to the hardware
        acadia.attach()

        # Configure channel analog parameters
        stimulus_channel.set(**self.stimulus["datapath"])
        capture_channel.set(**self.capture["datapath"])

        # Populate the stimulus with data
        stimulus_waveform.set(**self.stimulus["signal"])

        # Assemble and load the program
        acadia.load(*acadia.assemble())

        for i in range(self.iterations):
            acadia.run(assemble=False)
            self.data["traces"].write(capture_waveform.array)
            self.data.serve()


    def initialize(self):
        # Set the matplotlib backend to one which we can actually update
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")

        from acadia.processing import DynamicLine
        import matplotlib.pyplot as plt
        from tqdm.notebook import tqdm

        self.fig,self.ax = plt.subplots(1,1, figsize=(3,3))
        self.fig.tight_layout()

        self.line_re = DynamicLine(self.ax, ".-")
        self.line_im = DynamicLine(self.ax, ".-")
        self.ax.set_xlabel("Time [s]")
        self.ax.set_ylabel("Signal Amplitude [arb. V]")
        self.ax.grid()

        self.progress_bar = tqdm(desc="Iterations", dynamic_ncols=True, total=self.iterations)
        self.previous_completed_iterations = 0

        self.time_axis = None
        # self.fig.show()

    def update(self):
        import numpy as np

        # First make sure that we actually have new data to process
        if "traces" not in self.data or len(self.data["traces"]) == 0:
            return

        # Update the progress bar based on the number of iterations that have been completed
        completed_iterations = len(self.data["traces"])
        self.progress_bar.update(completed_iterations - self.previous_completed_iterations)
        self.previous_completed_iterations = completed_iterations        

        # We'll make an x-axis for the plot, but we only need to make it once
        if self.time_axis is None:
            # Last index is for quadrature
            samples_per_trace = self.data["traces"].records().shape[-2]
            capture_time = self.capture["waveform"]["length"]
            self.time_axis = np.linspace(0, capture_time, samples_per_trace, endpoint=False)

        # Sum the traces from each iteration
        # Each trace has the shape (samples, 2) where the number of samples is determined
        # at runtime from the specified waveform length in seconds. 
        # Because the record group is uniform, when we get the records from the
        # group, they are stacked into a single array of shape (iterations, samples, 2)
        self.trace_summed = np.sum(self.data["traces"].records(), axis=0)
        self.line_re.update(self.time_axis, self.trace_summed[:,0])
        self.line_im.update(self.time_axis, self.trace_summed[:,1])
        self.ax.relim()
        self.ax.autoscale(tight=True)
        self.fig.canvas.draw_idle()

    def finalize(self):
        super().finalize()
        self.progress_bar.close()


if __name__ == "__main__":    

    stimulus: dict = {
        "channel": "DAC1",

        "datapath": {
            "vop": 12000,
            "nyquist_zone": 2,
            "nco": {
                "frequency": 4.6e9
            }
        },

        "waveform": {
            "length": 1e-6,
            # "flat_top_length": 1e-6
        },
        
        "signal": {
            "data": ("scipy", "hann"),
            "scale": 0.2
        }
    }

    capture: dict = {
        "channel": "ADC1",

        "datapath": {
            "nyquist_zone": 2,
            "nco": {
                "frequency": 4.6e9
            }
        },

        "waveform": {
            "length": 4.096e-6,
            "decimation": 0,
            "region": "plddr"
        }
    }

    rt = LoopbackRuntime(stimulus, capture, iterations=100000)
    rt.deploy("192.168.2.69", "loopback", files=[__file__], log_debug=True, remove_remote_directory=False, remote_directory="/home/root/%y%m%d_%H%M%S")    
    rt.display()
    
