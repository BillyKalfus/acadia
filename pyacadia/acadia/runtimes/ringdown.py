import os
from typing import Union
from dataclasses import dataclass

from acadia.runtime import Runtime
from acadia.data import ArrayRecordGroup
from acadia.arrays import Waveform
import numpy as np

@dataclass
class RingdownRuntime(Runtime):
    """
    A :class:`Runtime` for performing time-domain cavity response 
    measurements.
    """
    # Resonator drive frequency, HZ
    frequency: float
    
    # DAC channel used for stimulus
    DAC: int 
    
    # ADC channel for capture
    ADC: int 
    
    # Length of the stimulus signal flat top in seconds
    stimulus_constant_time: float 
    
    # Length of the stimulus signal ramp in seconds (Total)
    stimulus_ramp_time: float
    
    # DAC amplitude of stimulus
    stimulus_amplitude: complex = 1.0
    
    # DAC Nyquist zone (1 or 2)
    stimulus_NZ: int = 2
    
    # VOP setting for DAC (2250 - 40000)
    stimulus_VOP: int = 12000
    
    # Total length of the capture. If ``0``, will be set to stimulus_ramp_time + stimulus_flat_time
    capture_time: float = 0
    
    # Add this much delay at the start of the capture to account for round-trip time of the stimulus
    capture_delay: float = 0

    # Determine how the capture will be carried out
    # If 0, the full waveform will be integrated
    # Otherwise, this amount of decimation will be used
    capture_decimation: int = 4

    # The number of full spectra to take
    iterations: int = 10

    # time (in seconds) when the pulse is stop, used in fitting the tail of decay trace
    pulse_stop_time: Union[float, None] = None
    
    # Place to write generic string which will be saved to metadata
    comments_field: str = 'No Comment'
    
    # control whether square-mean and mean-square plots keep y = 0 in the field of view
    pwr_plot_has_zero: bool = False
    
    # not intended to be an input argument; gets modified in the runtime sequence below
    # completed_iterations: int = 0
    
    plot_backend: str = "widget"
    
    plot_save_transparent: bool = False
    
                
    def main(self):
        import time
        import numpy as np
        
        from acadia.system import Acadia
        from acadia.arrays import Waveform, WindowedConstantWaveform
        
        acadia = Acadia()
        pulse_channel = acadia.DAC(self.DAC)
        capture_channel = acadia.ADC(self.ADC)
        
        pulse = WindowedConstantWaveform(pulse_channel, 
                                            constant_length_seconds=self.stimulus_constant_time,
                                            window_length_seconds=self.stimulus_ramp_time)
        
        capture_time = self.capture_time if self.capture_time != 0 else self.stimulus_ramp_time + self.stimulus_constant_time                        
        
        # self.data.write("time", thing)
        
        traces_metadata_dict = {}
        
        traces_metadata_dict['capture_time'] = capture_time
        traces_metadata_dict['comments_field'] = self.comments_field
        
        self.data.create_group(ArrayRecordGroup, "traces", 
                            #    capture_time=capture_time,
                               **traces_metadata_dict
                               )
                
        # Create a sequence for the sequencer
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                a.generate(pulse)
                if self.capture_delay != 0:
                    a.generate_blank(capture_channel, self.capture_delay)
                capture_data, _ = a.stream(capture_channel, 
                                   length=capture_time, 
                                   length_units="seconds", 
                                   decimation=self.capture_decimation)
                
            return capture_data

        # Compile only once
        capture_data = acadia.compile(sequence)
                
        # Attach to the hardware
        acadia.attach()        
        acadia.align_tile_latencies()

        # write pulse data to memory
        if self.stimulus_ramp_time != 0:
            
            pulse_complex = np.hanning(len(pulse)).astype(np.complex64)
              
            pulse[:] = Waveform.complex_to_sample(pulse_complex, scale=self.stimulus_amplitude)
        else:
            pulse[:] = np.complex64(self.stimulus_amplitude)

        # Configure channel parameters
        pulse_channel.set_nyquist_zone(self.stimulus_NZ)
        pulse_channel.set_vop(self.stimulus_VOP)

        # Set up the channels for synchronized NCO updates
        pulse_channel.configure_nco(update_source="sysref")
        capture_channel.configure_nco(update_source="sysref")

        # Set the modulation frequencies
        acadia.update_nco_frequency(pulse_channel, frequency=self.frequency)
        acadia.update_nco_frequency(capture_channel, frequency=-self.frequency)

        # When the frequencies are updated, also reset the NCO phases
        pulse_channel.reset_nco_phase()
        capture_channel.reset_nco_phase()

        # Carry out a synchronized NCO update
        acadia.pulse_sysref(1)

        # Wait a moment so that the sysref will have actually happened
        time.sleep(0.001)
        
        for i in self.data.count(self.iterations, "Iterations"):                                    
            acadia.run(assemble=(i==0))
            self.data.write("traces", capture_data)


    def initialize(self):
        # Set the matplotlib backend to one which we can actually update
        from IPython.core.getipython import get_ipython
        get_ipython().run_line_magic("matplotlib", self.plot_backend)
        import matplotlib.pyplot as plt
        from acadia.processing import DynamicLine, ProgressBar, set_scientific_notation
        
        # Create a progress bar for viewing things
        self.progress_bar = ProgressBar("Iterations")

        # Make a figure with our plots
        # self.fig, axes = plt.subplots(3,1,figsize=(4,12))   
        self.fig, self.axes = plt.subplots(1,3,figsize=(8,3)) 
        (ax_data, ax_mag, ax_pwr) = self.axes     
        self.fig.subplots_adjust(hspace=0.3)
        
        # figure_title = 'Test figure title'
        
        timestamp_str = self.data['properties']['time'].strftime('%Y%m%d_%H%M%S')
        pulse_freq_str = str(self.frequency*1e-9)+' GHz'
        pulse_amp_str = str(self.stimulus_amplitude)+' DAC'
        pulse_len_str = str(self.stimulus_constant_time)+' seconds'
        pulse_ramp = self.stimulus_ramp_time
        if pulse_ramp != 0:
            pulse_ramp_str = '(with '+str(pulse_ramp)+' s ramp)'
            pulse_len_str = pulse_len_str + ' '+pulse_ramp_str
            
        pulse_str = pulse_freq_str+' drive at '+pulse_amp_str+' for '+pulse_len_str
        
        if self.comments_field != 'No Comment':
            fig_title_top = self.comments_field
        else:
            fig_title_top = ''
        fig_title_bottom = timestamp_str+': '+pulse_str
        
        figure_title = fig_title_top + '\n' + fig_title_bottom
        self.fig.suptitle(figure_title, # https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.suptitle.html
                          x = 0.5, y = 0.95,
                        #   fontsize = 10
                          )
    
        # Configuring the appearance of each subplot...

        # Plot for I and Q
        self.data_re = DynamicLine(ax_data, ".", label="I")
        self.data_im = DynamicLine(ax_data, ".", label="Q")
        ax_data.set_xlabel("Time [s]")
        ax_data.set_ylabel("Amplitude [arb. V]")
        # ax_data.set_ticklabel_format(axis='y', style='sci')
        set_scientific_notation(ax_data.xaxis) 
        set_scientific_notation(ax_data.yaxis) 
        # ax_data.set_title("Average Signal Amplitude")
        ax_data.legend()

        # Plot for average-square-sum of I and Q
        self.data_mag = DynamicLine(ax_mag, ".", label="Magnitude")
        if self.pulse_stop_time is not None:
            self.data_mag_fit = DynamicLine(ax_mag, "-", label="Magnitude (fit)")
        ax_mag.set_xlabel("Time [s]")
        # ax_mag.set_ylabel("Magnitude [arb. V**2]")
        # ax_mag.set_ylabel("$\left<\left|{I + jQ}\\right|\\right>^2$ [arb. V**2]")
        ax_mag.set_ylabel(r"$\left<I\right>^2 + \left<Q\right>^2$ [arb. $\rm{V}^2$]")
        # ax_mag.set_ticklabel_format(axis='y', style='sci')
        set_scientific_notation(ax_mag.xaxis)
        set_scientific_notation(ax_mag.yaxis) 
        # ax_mag.set_title("$\left|\overline{I + i Q}\\right|^2$")
        # ax_mag.legend()

        # Plot for square-average-sum of I and Q
        self.data_pwr = DynamicLine(ax_pwr, ".", label="Power")
        if self.pulse_stop_time is not None:
            self.data_pwr_fit = DynamicLine(ax_pwr, "-", label="Power (fit)")
        ax_pwr.set_xlabel("Time [s]")
        # ax_pwr.set_ylabel("Power [arb. V**2]")
        ax_pwr.set_ylabel(r"$\left<{I^2 + Q^2}\right>$ [arb. $\rm{V}^2$]")
        # ax_pwr.set_ticklabel_format(axis='y', style='sci')
        set_scientific_notation(ax_pwr.xaxis) 
        set_scientific_notation(ax_pwr.yaxis) 
        # ax_pwr.set_title("$\overline{I^2 + Q^2}$")
        # ax_pwr.legend()
        
        self.did_tight_layout = False # Enables a tight_layout operation only after the first data is plotted

    def update(self):
        # Do nothing if we don't have the data that we want
        if not self.data.available("traces"):
            return
        
        if "Iterations" in self.data:
            self.progress_bar.update(self.data["Iterations"])
        
        traces_packed = self.data["traces"].records()
        if not hasattr(self, "time_axis"):
            num_samples = traces_packed.shape[-1]
            capture_time = self.data["traces"].metadata()["capture_time"]
            self.time_axis = np.linspace(0, capture_time, num_samples, endpoint = False)

        # Convert the packed sample data into an array of integers (adding another axis)
        # so that we can do all of our operations on integers rather than floats
        traces_int = Waveform.sample_to_int(traces_packed)

        # First, plot the average data <I> and <Q>
        traces_summed = np.sum(traces_int, axis=0, dtype=np.int32)
        number_of_shots = traces_int.shape[0]
        capture_decimation = self.capture_decimation
        compensate_v8_vs_v4 = 2**-16
        scale_factor = number_of_shots*capture_decimation*compensate_v8_vs_v4
        traces_avg_normalized = Waveform.to_complex(traces_summed, scale=scale_factor)
        # traces_avg_normalized = Waveform.to_complex(traces_summed, scale=traces_int.shape[0])
        self.data_re.update(self.time_axis, traces_avg_normalized.real)
        self.data_im.update(self.time_axis, traces_avg_normalized.imag)
        
        # Plot the phase-sensitive mean-square-summed trace, |<I + iQ>|^2
        mag_mean = np.abs(traces_avg_normalized)
        mag_meansq = mag_mean**2
        ylim_bottom = 0 if self.pwr_plot_has_zero else 'auto'
        self.data_mag.update(self.time_axis, mag_meansq, ylim_bottom = ylim_bottom)
        
        # Plot the phase-insensitive power (square-mean-summed trace), <|I + iQ|^2> = <I**2 + Q**2>
        traces_squared = np.multiply(traces_int, traces_int, dtype=np.int64)
        power_sum = np.sum(traces_squared, axis=(0,-1))  # Sum over traces and over quadratures
        int_to_fraction_of_ADC = 2**15
        scale_factor_pwr = number_of_shots*(capture_decimation**2)*(int_to_fraction_of_ADC**2)
        power_avg = np.divide(power_sum, scale_factor_pwr)
        # power_avg = np.divide(power_sum, traces_squared.shape[0])
        ylim_bottom = 0 if self.pwr_plot_has_zero else 'auto'
        self.data_pwr.update(self.time_axis, power_avg, ylim_bottom = ylim_bottom)
        
        # Fit the decay part if `pulse_stop_time` is provided
        if self.pulse_stop_time is not None: 
            stop_index = np.argmin(np.abs(self.time_axis - self.pulse_stop_time))
            fit_time_axis = np.copy(self.time_axis[stop_index:])
            
            # Shift and scale the data to make the fit more reasonable
            fit_time_axis -= fit_time_axis[0]
            fit_time_axis *= 1e6
            
            from lmfit.models import ConstantModel, ExponentialModel
            model = ConstantModel() + ExponentialModel()

            fit_guess = model.guess(mag_mean[stop_index:], fit_time_axis)
            mag_fit = model.fit(mag_mean[stop_index:], fit_guess, x=fit_time_axis)     
            self.data_mag_fit.update(fit_time_axis, mag_fit.best_fit/1e8)
            
            fit_guess = model.guess(power_avg[stop_index:], fit_time_axis)    
            pwr_fit = model.fit(power_avg[stop_index:], fit_guess, x=fit_time_axis)
            self.data_pwr_fit.update(fit_time_axis, pwr_fit.best_fit/1e16)
            
            # add fitting results to legends
            t2_str = f"T2 (us): {mag_fit.params['tau'].value:.2e} ± {mag_fit.params['tau'].stderr:.2e}"
            t1_str = f"T1 (us): {pwr_fit.params['tau'].value:.2e} ± {pwr_fit.params['tau'].stderr:.2e}"
            self.data_mag._ax.legend().get_texts()[1].set_text(t2_str)
            self.data_pwr._ax.legend().get_texts()[1].set_text(t1_str)

            # update all axis scales
            for ax in self.fig.get_axes():
                ax.relim()
                ax.autoscale(axis='y')
                ax.set_xlim(0, self.time_axis[-1])
                
        if self.did_tight_layout == False: 
            self.axes[0].relim()
            self.axes[0].autoscale(axis='y') # ensure both I and Q fit in the axes limits
            self.fig.tight_layout()
            self.did_tight_layout = True # No more tight layout operations after the first, until it is applied again finalize().

        self.fig.canvas.draw_idle()

    def finalize(self):
        self.progress_bar.update(self.data["Iterations"])
        self.progress_bar.finalize()
        self.axes[0].relim()
        self.axes[0].autoscale(axis='y') # ensure both I and Q fit in the axes limits
        self.fig.tight_layout()
        self.data.write("properties", key="figure", record=self.fig)
        self.fig.savefig(os.path.join(self.local_directory, "plots.png"), 
                                    dpi=500, 
                                    transparent=self.plot_save_transparent)
    
if __name__ == "__main__":
    import numpy as np
    
    # Run the program on the target
    rt = RingdownRuntime(frequency=6.2e9,
                            DAC=0,
                            ADC=0, 
                            stimulus_ramp_time=0,
                            stimulus_constant_time=1e-3,
                            stimulus_amplitude=1,
                            stimulus_NZ=2,
                            capture_decimation=1000,
                            capture_delay=0.1e-6,
                            capture_time=2.5e-3,
                            iterations=1000,
                            pulse_stop_time=None)
    rt.deploy("192.168.2.69", "acadia.runtimes.ringdown")    
    rt.display()