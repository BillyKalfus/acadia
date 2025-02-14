from typing import Union, Callable

import numpy as np

window_functions = {
    'hann': lambda x: 0.5 - 0.5 * np.cos(2 * np.pi * x),
    'hamming': lambda x: 0.54 - 0.46 * np.cos(2 * np.pi * x),
    'blackman': lambda x: 0.42 - 0.5 * np.cos(2 * np.pi * x) + 0.08 * np.cos(4 * np.pi * x),
}


def flattop_generator(ramping_function: Union[str, Callable], ramping_time, flat_time) -> Callable:
    """
    Generate a continuous flattop waveform function.
    The waveform is defined as follows:
      - For t < 0 or t >= ramping_time + flat_time, the value is 0.
      - For 0 ≤ t < ramping_time/2, the function uses the ramping function over the interval [0, 0.5) (ramp up).
      - For ramping_time/2 ≤ t < ramping_time/2 + flat_time, the waveform holds flat at the value
        of ramping_function(0.5).
      - For ramping_time/2 + flat_time ≤ t < ramping_time + flat_time, the function uses the ramping
        function over the interval [0.5, 1] (ramp down).

    :param ramping_function: A callable (or a string key corresponding to one) that accepts a single input
        defined on the interval [0, 1].
    :param ramping_time: Total time for the ramp-up and ramp-down regions.
    :param flat_time: Duration of the flat region.
    :return:
    """

    if type(ramping_function) == str:
        if ramping_function in window_functions:
            ramping_function = window_functions[ramping_function]
        else:
            raise AttributeError(f"Unable to find ramping function {ramping_function}, "
                                 f"available ones are {list(window_functions.keys())}")

    @np.vectorize
    def func(t):
        if t < 0:
            return 0
        elif t < ramping_time / 2:
            return ramping_function(t / ramping_time)
        elif t < ramping_time / 2 + flat_time:
            return ramping_function(0.5)
        elif t < ramping_time + flat_time:
            return ramping_function((t - flat_time) / ramping_time)
        else:
            return 0

    return func


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
        wf_func = flattop_generator("hann", ramping_time, length)
        wf_datas[i] = wf_func(t_sampled)
        plt.plot(t_sampled, wf_datas[i])
