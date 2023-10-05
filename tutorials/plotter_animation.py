import time
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import numpy as np

%matplotlib widget

from acadia.data import DataManager

fig,ax = plt.subplots(figsize=(8,4))
(line_re,) = ax.plot([], [])
(line_im,) = ax.plot([], [])
ax.grid()

# Make a function that will draw and update a plot
def update_plot(frame):
    time.sleep(0.1)
    data = DataManager.receive_all(("192.168.2.69", 6672))
    
    if data is not None:
        # Just plot only the most recently received trace
        axis = data["traces"].axis()*1e6
        trace = data["traces"].data()[-1,:]
        
        # Prepare the background
        line_re.set_data(axis, np.real(trace))
        line_im.set_data(axis, np.imag(trace))
        ax.relim()
        ax.autoscale_view()
    
    return line_re,line_im
    
animation = FuncAnimation(fig, update_plot, 100, blit=True)