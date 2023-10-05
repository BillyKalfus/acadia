%matplotlib widget

import matplotlib.pyplot as plt
import numpy as np

from acadia.data import DataManager, Plotter, ArrayRecordGroup

import logging
logging.basicConfig(format='[%(asctime)s] %(threadName)s: %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p', level=logging.INFO)

# Make a function that will draw and update a plot
def plot(groups):
    # Just plot only the most recently received trace
    axis = groups["traces"].axis()*1e6
    trace = groups["traces"].data()[-1,:]
    
    # Prepare the background
    fig,ax = plt.subplots(figsize=(8,4))
    (line_re,) = ax.plot(axis, np.real(trace))
    (line_im,) = ax.plot(axis, np.imag(trace))
    ax.grid()
    plt.show()
    
    while True:
        line_re.set_data(axis, np.real(trace))
        line_im.set_data(axis, np.imag(trace))
        fig.canvas.draw()
        yield
    
# Create and start a plotting client
plotter = Plotter(plot)
plotter.run(("192.168.2.69", 6672))