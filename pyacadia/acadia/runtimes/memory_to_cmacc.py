import numpy as np 
from acadia import Acadia, WaveformMemory, DecimatedChannelWaveformMemory

acadia = Acadia()

# Create a waveform to store the stimulus signal
src_waveform = WaveformMemory((100,), dtype="<i2", resource_allocator=acadia.PLDDR0Array)
dst_waveform = DecimatedChannelWaveformMemory(acadia.channel("ADC0"), (25,), decimation=4, resource_allocator=acadia.PLDDR0Array)


def sequence(a: Acadia):
    # stream, kernel = a.configure_cmacc(src_waveform, write_mode="input", last_only=False, reset_fifo=True)
    stream, kernel = a.configure_cmacc(src_waveform, write_mode="upper", last_only=False, reset_fifo=True)
    a.cmacc_load(stream, (0,0))
    a.stream(stream, dst_waveform, memory_input=src_waveform)
    return kernel

kernel = acadia.compile(sequence)
acadia.attach()
src_waveform.array.fill(128)
dst_waveform.array.fill(0)

kernel.array[:,0] = 32767
kernel.array[:,1] = 0

acadia.assemble()
acadia.load()
acadia.run()
