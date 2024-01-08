from dataclasses import dataclass

from acadia.runtime import Runtime
from acadia.data import DataManager, PlotMixin, ArrayRecordGroup
                
@dataclass
class SpectroscopyRuntime(Runtime):
    """
    A :class:`Runtime` subclass for performing swept spectroscopy.
    """
    # Iterable of frequencies
    frequencies: list 
    
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
    
    # Total length of the capture. If ``None``, will be set to stimulus_ramp_time + stimulus_flat_time
    capture_time: float = None
    
    # Add this much delay at the start of the capture to account for round-trip time of the stimulus
    capture_delay: float = 0

    # Decimation to use for capture
    # 1 applies no decimation, captures at full bandwidth
    # 0 applies a decimation factor equal to the trace length, producing a single accumulated point
    # any other factor uses that
    capture_decimation: int = 1
    
    # If ``True``, the phases in the plot will be unwrapped
    plot_unwrap_phase: bool = True
    
    # If ``None``, automatically fit phase data to 
    # extract an electrical delay. If any ``float``, this will be 
    # interpreted as the electrical delay to apply.
    plot_electrical_delay: float = None 
    
    FILENAME = __file__
    
    def main(self, directory: str, datamanager: DataManager):
        import time
        import numpy as np
        
        from acadia.system import Acadia
        from acadia.arrays import Waveform, WindowedConstantWaveform, DecimatedWaveform
        
        acadia = Acadia()
        pulse_channel = acadia.DAC(self.DAC)
        capture_channel = acadia.ADC(self.ADC)
        
        if self.stimulus_constant_time == 0:
            pulse = Waveform(pulse_channel, length_seconds=self.stimulus_constant_time)
        else:
            pulse = WindowedConstantWaveform(pulse_channel, 
                                            constant_length_seconds=self.stimulus_constant_time,
                                            window_length_seconds=self.stimulus_ramp_time)
        
        
        capture_time = self.capture_time if self.capture_time is not None else self.stimulus_ramp_time + self.stimulus_constant_time
        if self.capture_decimation == 1:
            capture_data = Waveform(capture_channel, 
                                    length_seconds=capture_time, 
                                    region=acadia.PLDDR0Array)
        elif self.capture_decimation == 0:   
            capture_data = DecimatedWaveform(capture_channel, 
                                    length_seconds=(1/acadia.sequencer_clock_frequency()), 
                                    region=acadia.PLDDR0Array,
                                    decimation=self.capture_decimation)
        else:
            capture_data = DecimatedWaveform(capture_channel, 
                                    length_seconds=capture_time, 
                                    region=acadia.PLDDR0Array,
                                    decimation=self.capture_decimation)
                        
        # We'll collect the data traces in a record group
        datamanager.add_group(SpectroscopyRecordGroup("traces", 
                                         directory,
                                         axes=[self.frequencies, capture_data.axis()],
                                         electrical_delay=self.electrical_delay,
                                         unwrap_phase=self.unwrap_phase))
                
        # Create a sequence for the sequencer
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                a.generate(pulse)
                if self.capture_delay > 0:
                    a.generate_blank(capture_channel, self.capture_delay)
                a.stream(capture_channel, capture_data)

        # Compile only once
        acadia.compile(sequence)
                
        # Attach to the hardware
        acadia.attach()
        
        acadia.configure_clocks(reference="external")
        time.sleep(1)
        acadia.align_tile_latencies()
        time.sleep(1)

        pulse[:] = np.hanning(len(pulse))
        pulse.flush(scale=self.stimulus_amplitude)

        # Configure channel parameters
        pulse_channel.set_nyquist_zone(self.stimulus_NZ)
        pulse_channel.set_vop(self.stimulus_VOP)
        pulse_channel.configure_nco(update_source="sysref")
        capture_channel.configure_nco(update_source="sysref")

        frequency_iterator = datamanager.report_iterations(self.frequencies, "Frequencies")
        for idx_frequency,frequency in enumerate(frequency_iterator):
            acadia.update_nco_frequency(pulse_channel, frequency=frequency)
            acadia.update_nco_frequency(capture_channel, frequency=-frequency)
            pulse_channel.reset_nco_phase()
            capture_channel.reset_nco_phase()
            acadia.pulse_sysref(1)
                
            time.sleep(0.005)
                                          
            acadia.run(assemble=(idx_frequency==0))
            with capture_data.unbuffer():
                datamanager.write("traces", capture_data.memory)
        
class SpectroscopyRecordGroup(ArrayRecordGroup, PlotMixin):
    
    def plot(self, fig):
        import numpy as np
        from acadia.system import DecimatedWaveform
        
        fig.set_size_inches(12,4)
        
        ax_data = fig.add_subplot(131)
        ax_mag = fig.add_subplot(132)
        ax_phase = fig.add_subplot(133)
        (data_re,) = ax_data.plot([], [], ".-", animated=False)
        (data_im,) = ax_data.plot([], [], ".-", animated=False)
        (data_mag,) = ax_mag.plot([], [], ".-", animated=False)
        (data_phase,) = ax_phase.plot([], [], ".-", animated=False)
        ax_mag.grid()
        ax_phase.grid()
        
        if self.metadata()["electrical_delay"] is None:
            from ipywidgets import Label
            from IPython.display import display
            fit_label = Label(f"Electrical delay:")
            display(fit_label)
          
        def update(animation, framedata):
            if self.records() is not None:
                # We have at least one measurement, plot it
                time_axis = self.axis(1)
                trace = DecimatedWaveform(data=self.records()[0,:,:]).unpack()
                trace = trace.reshape((len(self.axis(0)), -1))
                # trace = (self.records()[0,0,:] & 0xFFFFFFFF).astype(np.int32) + 1j*((self.records()[0,0,:] >> 32) & 0xFFFFFFFF).astype(np.int32)
                data_re.set_data(time_axis, trace[0,:].real)
                data_im.set_data(time_axis, trace[0,:].imag)
                
                ylims = np.max([abs(np.max(trace[0,:].real)), 
                                abs(np.min(trace[0,:].real)), 
                                abs(np.max(trace[0,:].imag)), 
                                abs(np.min(trace[0,:].imag))])
                ax_data.set_xlim(0, time_axis[-1])
                ax_data.set_ylim(-ylims, ylims)
            
                mean = np.mean(trace, axis=1)
                if self.metadata()["electrical_delay"] is not None:        
                    mean *= np.exp(1j * 2*np.pi * self.axis(0) * self.metadata()["electrical_delay"])                
                
                data_mag.set_data(self.axis(0), np.abs(mean))
                
                phase = np.angle(mean)
                unwrapped_phase = np.unwrap(phase)
                
                if self.metadata()["electrical_delay"] is None:
                    from scipy.optimize import curve_fit
                    import logging
                    
                    def model(freqs, delay, phi0):
                        return 2*np.pi*freqs*delay + phi0
                    
                    popt,pcov = curve_fit(model, self.axis(0), unwrapped_phase)
                    logging.info(f"Electrical delay fit returned popt={popt}, pcov={pcov}")
                    fit_label.value = f"Electrical delay: {round(popt[0]*1e9, 2)} ns +/- {round(pcov[0,0]*1e12, 2)} ps"
                                
                phase_plot_data = unwrapped_phase if self.metadata()["unwrap_phase"] else phase
                data_phase.set_data(self.axis(0), phase_plot_data)
                
                ax_mag.set_xlim(self.axis(0)[0], self.axis(0)[-1])
                ax_mag.set_ylim(0, np.max(np.abs(mean)))
                ax_phase.set_xlim(self.axis(0)[0], self.axis(0)[-1])
                ax_phase.set_ylim(np.min(phase_plot_data), np.max(phase_plot_data))
        
        return update