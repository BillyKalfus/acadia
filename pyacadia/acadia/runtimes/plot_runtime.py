from dataclasses import dataclass

import numpy as np

from acadia.runtime import Runtime
from acadia.data import DataManager

@dataclass
class PlotRuntime(Runtime):
    """
    A simple runtime for demonstrating the use of a live plot with dynamically
    updating data.
    """
    iterations: int = 1000
    delay: float = 0.01
    plot_points: int = 101

    def main(self, directory: str, datamanager: DataManager):
        import time
        for _ in datamanager.count(self.iterations, "counter"):
            time.sleep(self.delay)

    def initialize(self):
        from acadia.processing import DynamicLine, DynamicFigure
        import matplotlib.pyplot as plt

        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", "widget")
        
        fig,ax = plt.subplots()
        ax.set_xlim(0, self.plot_points)
        ax.set_ylim(-self.iterations, self.iterations)
        self.line = DynamicLine(ax, ".-")
        self.fig = DynamicFigure(fig)
        self.x = np.arange(self.plot_points)        

    def update(self, *args):
        if "counter" not in self.data:
            return
        
        iteration = self.data["counter"].count
        y = np.linspace(-iteration, iteration, self.plot_points)
        self.line.update(self.x, y)
        self.fig.update()

if __name__ == "__main__":
    import logging
    
    rt = PlotRuntime()
    rt.deploy("192.168.2.69", "plot_runtime", update_period=0.05, files = [__file__], log_level = logging.DEBUG)    
    rt.display()
    