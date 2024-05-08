from dataclasses import dataclass

import numpy as np

from acadia.runtime import Runtime

@dataclass
class PlotRuntime(Runtime):
    """
    A simple runtime for demonstrating the use of a live plot with dynamically
    updating data.
    """
    iterations: int = 1000
    delay: float = 0.01
    plot_points: int = 101

    def main(self):
        import time
        for _ in self.data.count(self.iterations, "counter"):
            time.sleep(self.delay)

    def initialize(self):
        from acadia.processing import DynamicLine, ProgressBar
        import matplotlib.pyplot as plt

        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")
        
        self.fig,ax = plt.subplots()
        ax.set_xlim(0, self.plot_points)
        ax.set_ylim(-self.iterations, self.iterations)
        self.line = DynamicLine(ax, ".-")
        self.x = np.arange(self.plot_points)        

        self.progress_bar = ProgressBar("Counter")

    def update(self, *args):
        if "counter" not in self.data:
            return
        
        iteration = self.data["counter"].count
        y = np.linspace(-iteration, iteration, self.plot_points)
        self.line.update(self.x, y)
        self.fig.canvas.draw_idle()
        self.progress_bar.update(self.data["counter"])

    def finalize(self):
        super().finalize()
        self.progress_bar.finalize()

if __name__ == "__main__":    
    rt = PlotRuntime()
    rt.deploy("192.168.2.69", "acadia.runtimes.plot_example")    
    rt.display()
    