import time
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import numpy as np

%matplotlib widget

from acadia.data import DataManager

fig,ax = plt.subplots(figsize=(8,4))
(line_re,) = ax.plot([], [])
(line_im,) = ax.plot([], [])
ax.set_ylim(-0.01, 0.01)
ax.set_xlim(0,5)
ax.grid()

# Make a function that will draw and update a plot
def update_plot(frame):
    time.sleep(0.02)
    traces = DataManager.receive_group("traces", ("192.168.2.69", 6672))
    
    if traces is not None:
        # Just plot only the most recently received trace
        axis = traces.axis()*1e6
        trace = traces.data()[-1,:]
        
        # Prepare the background
        line_re.set_data(axis, np.real(trace))
        line_im.set_data(axis, np.imag(trace))
        
        # ax.relim()
        # ax.autoscale_view()
    
    return line_re,line_im
    
animation = FuncAnimation(fig, update_plot, 400, blit=True)