from acadia import Runtime
from acadia.utils import sequencer_complete

import numpy as np

class BenchmarkRuntime(Runtime):
    """
    Various benchmarks.
    """

    procedure: int
    waveform_length: float
    iterations: int
        
    def main(self):     
        from acadia import Acadia, DataManager
        
        acadia = Acadia()
        waveform = acadia.create_waveform_memory("DAC0", length=self.waveform_length)
        self.data.add_group("counts", uniform=True)
        cache = acadia.CacheArray(shape=(4,), dtype=np.dtype("<i4"))
                
        # Create a sequence that will cause the sequencer to act like a stopwatch
        # The "start" signal is the PS setting cache[0] to 1, 
        # and the "stop" signal is it setting it to 2
        def sequence(a: Acadia):
            counter = a.sequencer().DSP()
            counter.start_count()

            cache[1] = counter
            with a.sequencer().repeat_until(cache[0] == 1):
                pass
            cache[2] = counter
            with a.sequencer().repeat_until(cache[0] == 2):
                pass
            cache[3] = counter

        # Compile the sequence
        acadia.compile(sequence)                
        acadia.attach()
        acadia.assemble()
        acadia.load()

        if self.procedure == 0:
            # A baseline check
            for i in range(self.iterations):
                cache[0] = 0
                acadia.run(block=False)
                cache[0] = 1
                cache[0] = 2
                sequencer_complete()

                self.data["counts"].write(cache._array)
                
                if self.data.serve() == DataManager.serve_hangup():
                    self.data.disconnect()
                    return
        elif self.procedure == 1:
            # Set the waveform with a constant
            for i in range(self.iterations):
                cache[0] = 0
                acadia.run(block=False)
                cache[0] = 1
                waveform.set(0.0)
                cache[0] = 2
                sequencer_complete()

                self.data["counts"].write(cache._array)
                
                if self.data.serve() == DataManager.serve_hangup():
                    self.data.disconnect()
                    return
        elif self.procedure == 2:
            # Set the waveform with a hann shape
            for i in range(self.iterations):
                cache[0] = 0
                acadia.run(block=False)
                cache[0] = 1
                waveform.set("hann")
                cache[0] = 2
                sequencer_complete()

                self.data["counts"].write(cache._array)
                
                if self.data.serve() == DataManager.serve_hangup():
                    self.data.disconnect()
                    return
        else:
            raise ValueError(f"Unrecognized procedure {self.procedure}")
        
        self.final_serve()

    def initialize(self):
        from tqdm.notebook import tqdm
        self.progress_bar = tqdm(desc="Iterations", dynamic_ncols=True, total=self.iterations)
        self.previous_completed_iterations = 0

    def update(self):
        # First make sure that we actually have new data to process
        if "counts" not in self.data or len(self.data["counts"]) == 0:
            return

        # Update the progress bar based on the number of iterations that have been completed
        completed_iterations = len(self.data["counts"])
        self.progress_bar.update(completed_iterations - self.previous_completed_iterations)
        self.previous_completed_iterations = completed_iterations        

    def finalize(self):
        super().finalize()
        self.progress_bar.close()

        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")
        import matplotlib.pyplot as plt

        # Plot results
        if self.procedure in [0,1,2]:
            records = self.data["counts"].records()
            intervals = (records[:,3] - records[:,2])*5 # Convert to ns
            median = np.median(intervals)
            median_deviation = np.abs(intervals - median)
            median_median_deviation = np.median(median_deviation)
            intervals_to_bin = intervals[median_deviation < 8*median_median_deviation]
            histogram, bin_edges = np.histogram(intervals_to_bin)

            fig, ax = plt.subplots(figsize=(4,3))
            ax.set_title(f"Interval histogram"
            f"\n{len(intervals_to_bin)} / {len(intervals)} samples used"
            f"\nmean = {round(np.mean(intervals_to_bin), 2)}"
            f"\nstd = {round(np.std(intervals_to_bin), 2)}")
            ax.set_xlabel("Intervals [ns]")
            ax.set_ylabel("Occurrences")
            ax.bar(bin_edges[:-1], histogram, width=np.diff(bin_edges), align="edge")

def run():   
    rt = BenchmarkRuntime(procedure=1, waveform_length=1e-6, iterations=10000)
    rt.deploy("192.168.2.69", files=[__file__], runtime_module="benchmarks")    
    rt.display()
    return rt

if __name__ == "__main__":
    rt = run()
    
