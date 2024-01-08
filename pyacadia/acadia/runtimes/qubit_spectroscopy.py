from dataclasses import dataclass

from acadia.runtime import Runtime
from acadia.data import DataManager, PlotMixin, ArrayRecordGroup
                
@dataclass
class QubitSpectroscopyRuntime(Runtime):
    """
    A :class:`Runtime` subclass for performing swept qubit spectroscopy.
    """
    # Start frequency in Hz
    qubit_frequencies: list
    
    # DAC channel used for stimulus
    qubit_DAC: int 
    
    # Length of the stimulus signal flat top in seconds
    qubit_stimulus_constant_time: float 
    
    # Length of the stimulus signal ramp in seconds (Total)
    qubit_stimulus_ramp_time: float
    
    # DAC amplitude of stimulus
    qubit_stimulus_amplitude: complex = 1.0
    
    # DAC Nyquist zone (1 or 2)
    qubit_stimulus_NZ: int = 2
    
    # VOP setting for DAC (2250 - 40000)
    qubit_stimulus_VOP: int = 12000

    # DAC channel used for readout stimulus
    readout_DAC: int 
    
    # ADC channel for capture
    readout_ADC: int 

    # Frequency of the readout signal
    readout_frequency: float

    # Length of the stimulus signal flat top in seconds
    readout_stimulus_constant_time: float 
    
    # Length of the stimulus signal ramp in seconds (Total)
    readout_stimulus_ramp_time: float
    
    # DAC amplitude of stimulus
    readout_stimulus_amplitude: complex = 1.0
    
    # DAC Nyquist zone (1 or 2)
    readout_stimulus_NZ: int = 2
    
    # VOP setting for DAC (2250 - 40000)
    readout_stimulus_VOP: int = 12000
    
    # Total length of the capture. If ``None``, will be set to stimulus_ramp_time + stimulus_flat_time
    readout_capture_time: float = None
    
    # Add this much delay at the start of the capture to account for round-trip time of the stimulus
    readout_capture_delay: float = 0

    # Decimation to use for capture
    # 1 applies no decimation, captures at full bandwidth
    # 0 applies a decimation factor equal to the trace length, producing a single accumulated point
    # any other factor uses that
    readout_capture_decimation: int = 1
    
    FILENAME = __file__
    
    def main(self, directory: str, datamanager: DataManager):
        import time
        import numpy as np
        
        from acadia.system import Acadia
        from acadia.arrays import Waveform, WindowedConstantWaveform, DecimatedWaveform
        
        acadia = Acadia()
        qubit_pulse_channel = acadia.DAC(self.qubit_DAC)
        readout_pulse_channel = acadia.DAC(self.readout_DAC)
        readout_capture_channel = acadia.ADC(self.readout_ADC)
        
        if len(self.qubit_frequencies) == 0:
            raise ValueError("Frequency axis has no points!")
        
        if self.qubit_stimulus_constant_time == 0:
            qubit_pulse = Waveform(qubit_pulse_channel, length_seconds=self.qubit_stimulus_constant_time)
        else:
            qubit_pulse = WindowedConstantWaveform(qubit_pulse_channel, 
                                            constant_length_seconds=self.qubit_stimulus_constant_time,
                                            window_length_seconds=self.qubit_stimulus_ramp_time)
            
        if self.readout_stimulus_constant_time == 0:
            readout_pulse = Waveform(readout_pulse_channel, length_seconds=self.readout_stimulus_constant_time)
        else:
            readout_pulse = WindowedConstantWaveform(readout_pulse_channel, 
                                            constant_length_seconds=self.readout_stimulus_constant_time,
                                            window_length_seconds=self.readout_stimulus_ramp_time)
        
        
        if self.decimation == 1:
            capture_data = Waveform(capture_channel, 
                                    length_seconds=capture_time, 
                                    region=acadia.PLDDR0Array)
        else:
            capture_data = DecimatedWaveform(capture_channel, 
                                    length_seconds=capture_time, 
                                    region=acadia.PLDDR0Array,
                                    decimation=self.decimation)
                        
        # We'll collect the data traces in a record group
        datamanager.add_group(SpectroscopyRecordGroup("traces", 
                                         directory,
                                         axes=[frequencies, capture_data.axis()],
                                         electrical_delay=self.electrical_delay,
                                         unwrap_phase=self.unwrap_phase))
                
        # Create a sequence for the sequencer
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                a.generate(pulse)
                if self.capture_delay > 0:
                    a.generate_blank(capture_channel, self.capture_delay)
                a.stream(capture_channel, capture_data)
                
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

        # Compile only once
        acadia.compile(sequence)
         
        for idx_frequency,frequency in enumerate(datamanager.report_iterations(frequencies, "Frequencies")):
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