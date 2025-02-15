from typing import Union, Callable, Tuple

import numpy as np
from numpy.typing import NDArray

from acadia import Acadia, Channel, ChannelWaveformMemory

# I couldn't find a module that provides function form of these windows, so they are manually written here...
window_functions = {
    'hann': lambda x: 0.5 - 0.5 * np.cos(2 * np.pi * x),
    'hamming': lambda x: 0.54 - 0.46 * np.cos(2 * np.pi * x),
    'blackman': lambda x: 0.42 - 0.5 * np.cos(2 * np.pi * x) + 0.08 * np.cos(4 * np.pi * x),
}


def flattop_function_generator(ramp_function: Union[str, Callable], ramp_time, flat_time) -> Callable:
    """
    Create a continuous flattop function for generating waveform data
    The waveform is defined as follows:
      - For t < 0 or t >= ramping_time + flat_time, the value is 0.
      - For 0 ≤ t < ramping_time/2, the function uses the ramping function over the interval [0, 0.5) (ramp up).
      - For ramping_time/2 ≤ t < ramping_time/2 + flat_time, the waveform holds flat at the value
        of ramping_function(0.5).
      - For ramping_time/2 + flat_time ≤ t < ramping_time + flat_time, the function uses the ramping
        function over the interval [0.5, 1] (ramp down).

    :param ramp_function: A callable (or a string key corresponding to one) that accepts a single input
        defined on the interval [0, 1].
    :param ramp_time: Total time for the ramp-up and ramp-down regions.
    :param flat_time: Duration of the flat region.
    :return:
    """

    if type(ramp_function) == str:
        if ramp_function in window_functions:
            ramp_function = window_functions[ramp_function]
        else:
            raise KeyError(f"Unable to find ramping function {ramp_function}, "
                           f"available ones are:\n{list(window_functions.keys())}")

    @np.vectorize
    def func(t):
        if t < 0:
            return 0
        elif t < ramp_time / 2:
            return ramp_function(t / ramp_time)
        elif t < ramp_time / 2 + flat_time:
            return ramp_function(0.5)
        elif t < ramp_time + flat_time:
            return ramp_function((t - flat_time) / ramp_time)
        else:
            return 0

    return func


def prepare_flattop_length_sweep(acadia: Acadia, channel: Channel,
                                 flat_lengths: Union[list, NDArray], ramp_function: Union[str, Callable],
                                 **pulse_memory_config) -> Tuple[ChannelWaveformMemory, NDArray]:
    """
    Generate the waveform memory and a 2D array of waveform data for sweeping the flat-part length of a flat-top pulse.

    :param acadia: Instance of Acadia
    :param channel: The channel on which to create the waveform
    :param flat_lengths: A list or numpy array of duration values for the flat part of the pulses
    :param ramp_function: The function used to generate the ramp portions of the waveform.
        See `ramp_function` in `flattop_function_generator`
    :param pulse_memory_config: Configuration parameters for the waveform memory, in which the `length` value will be
        used as the total ramping (up+down) time of the pulse, and the `fixed_length` value will be omitted

    :return: A tuple containing:
        - Waveform memory for storing the pulse
        - A 2D array (shape: (len(flattop_durations), number of samples)) containing the data to be loaded to the
            waveform

    """
    # create a waveform memory that can store the longest pulse
    mem_cgf = pulse_memory_config.copy()
    ramp_time = mem_cgf["length"]
    interface_sample_freq = acadia.channel(channel).interface_sample_frequency
    max_len = np.max(flat_lengths) + ramp_time
    # the memory will be ChannelWaveformMemory instead of WindowedConstantWaveformMemory
    mem_cgf["fixed_length"] = 0.0
    mem_cgf["length"] = np.ceil(max_len * interface_sample_freq) / interface_sample_freq
    long_waveform_mem = acadia.create_waveform_memory(channel, **mem_cgf)

    # generate waveform data for pulse with each specific flat-part length
    samples = long_waveform_mem.shape[0]
    wf_datas = np.zeros((len(flat_lengths), samples), dtype=complex)
    t_sampled = np.arange(0, samples) / interface_sample_freq

    for i, length in enumerate(flat_lengths):
        wf_func = flattop_function_generator(ramp_function, ramp_time, length)
        wf_datas[i] = wf_func(t_sampled)

    return long_waveform_mem, wf_datas


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    sec_per_sample = 1.25e-9
    samples = 224
    t_sampled = np.arange(0, samples) * sec_per_sample
    ramping_time = 60e-9
    flat_length_list = np.linspace(0, 204e-9, 21) + 20e-9
    wf_datas = np.zeros((len(flat_length_list), samples), dtype=complex)

    plt.figure()
    for i, length in enumerate(flat_length_list):
        wf_func = flattop_function_generator("hann", ramping_time, length)
        wf_datas[i] = wf_func(t_sampled)
        plt.plot(t_sampled, wf_datas[i])
