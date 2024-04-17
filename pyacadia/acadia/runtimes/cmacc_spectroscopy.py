import logging
from dataclasses import dataclass

from acadia.runtime import Runtime, PyPlotRuntimeComponent, CounterRuntimeComponent
from acadia.data import DataManager, ArrayRecordGroup, CounterRecordGroup

@dataclass
class CMACCSpectroscopyRuntime(Runtime):
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
    
    # Total length of the capture. If ``0``, will be set to stimulus_ramp_time + stimulus_flat_time
    capture_time: float = 0
    
    # Add this much delay at the start of the capture to account for round-trip time of the stimulus
    capture_delay: float = 0

    # Determine how the capture will be carried out
    # If 0, the full waveform will be integrated
    # Otherwise, this amount of decimation will be used
    kernel_amplitude: complex = 1.0
    
    # If ``True``, the phases in the plot will be unwrapped
    plot_unwrap_phase: bool = True
    
    # If ``0``, automatically fit phase data to 
    # extract an electrical delay. If any ``float``, this will be 
    # interpreted as the electrical delay to apply.
    plot_electrical_delay: float = 0 

    # The number of full spectra to take
    iterations: int = 10
    
    FILENAME = __file__

    def initialize(self) -> None:
        self.add_component(SpectroscopyPlot)
        self.add_component(CounterRuntimeComponent, "Iterations")
        self.add_component(CounterRuntimeComponent, "Frequencies")
    
    def main(self, directory: str, datamanager: DataManager):
        import time
        import numpy as np
        
        from acadia.system import Acadia
        from acadia.arrays import Array, Waveform, WindowedConstantWaveform
        
        acadia = Acadia()
        pulse_channel = acadia.DAC(self.DAC)
        capture_channel = acadia.ADC(self.ADC)
        
        if self.stimulus_constant_time == 0:
            pulse = Waveform(pulse_channel, 
                             length=acadia.convert(self.stimulus_ramp_time, "seconds", "samples"))
        else:
            pulse = WindowedConstantWaveform(pulse_channel, 
                                            constant_length_seconds=self.stimulus_constant_time,
                                            window_length_seconds=self.stimulus_ramp_time)
        
        
        capture_time = self.capture_time if self.capture_time != 0 else self.stimulus_ramp_time + self.stimulus_constant_time                        
        datamanager.create_group(ArrayRecordGroup, "traces", capture_time=capture_time)
                
        # Create a sequence for the sequencer
        def sequence(a: Acadia):
            with a.channel_synchronizer():
                a.generate(pulse)
                if self.capture_delay > 0:
                    a.generate_blank(capture_channel, self.capture_delay)

                capture_data, cfg, kernel = a.stream_accumulated(capture_channel, 
                                                                accumulation_length=capture_time, 
                                                                accumulation_length_units="seconds",
                                                                write_mode="upper",
                                                                kernel_length=0)
                
            return capture_data, kernel

        # Compile only once
        capture_data, kernel = acadia.compile(sequence)
                
        # Attach to the hardware
        acadia.attach()
        
        acadia.configure_clocks(reference="external")
        acadia.align_tile_latencies()

        pulse_complex = np.hanning(len(pulse)).astype(np.complex64)
        Waveform.from_complex(pulse_complex, pulse, scale=self.stimulus_amplitude)

        # Load the kernel
        Waveform.from_complex(np.array([self.kernel_amplitude], dtype=np.complex64), kernel)

        # Configure channel parameters
        pulse_channel.set_nyquist_zone(self.stimulus_NZ)
        pulse_channel.set_vop(self.stimulus_VOP)

        # Set up the channels for synchronized NCO updates
        pulse_channel.configure_nco(update_source="sysref")
        capture_channel.configure_nco(update_source="sysref")

        # Assemble and load the program
        acadia.load(*acadia.assemble())

        for i in datamanager.count(self.iterations, "Iterations"):
            for frequency in datamanager.count(self.frequencies, "Frequencies"):
                # Set the modulation frequencies and reset phases
                acadia.update_nco_frequency(pulse_channel, frequency=frequency)
                acadia.update_nco_frequency(capture_channel, frequency=-frequency)
                acadia.reset_nco_phase(pulse_channel)
                acadia.reset_nco_phase(capture_channel)
                acadia.update_ncos_synchronized()
                                            
                # Run the sequencer and wait until it's done
                acadia.run(assemble=False)

                # Grab the output data and save it
                datamanager.write("traces", capture_data[0])

class SpectroscopyPlot(PyPlotRuntimeComponent):

    def create_plot(self):
        self.figure().set_size_inches(8,4)

        self.ax_mag = self.figure().add_subplot(121)
        self.data_mag = self.ax_mag.plot([], [], ".-", animated=False)
        self.ax_mag.set_xlabel("Frequency [MHz]")
        self.ax_mag.set_ylabel("Magnitude [arb. V*s]")
        self.ax_mag.set_title("Spectral Magnitude")
        self.ax_mag.grid()
        
        self.ax_phase = self.figure().add_subplot(122)
        self.data_phase = self.ax_phase.plot([], [], ".-", animated=False)
        self.ax_phase.set_xlabel("Frequency [MHz]")
        self.ax_phase.set_ylabel("Phase [rad.]")
        self.ax_phase.set_title("Spectral Phase")
        self.ax_phase.grid()

        self.figure().subplots_adjust(hspace=0.35)
        
        if self.runtime.plot_electrical_delay == 0:
            from ipywidgets import Label
            from IPython.display import display
            self.fit_label = Label(f"Electrical delay:")
            display(self.fit_label)

    def update_plot(self):
        from acadia.arrays import Waveform
        import numpy as np

        if "traces" in self.runtime.data and self.runtime.data["traces"].records() is not None:
            # We have at least one measurement, plot it

            traces = Waveform.to_complex(self.runtime.data["traces"].records()[0,:,:], np.dtype("c8"))
            if not hasattr(self, "time_axis"):
                num_samples = traces.shape[-1]
                capture_time = self.runtime.data["traces"].metadata()["capture_time"]
                self.time_axis = np.linspace(0, capture_time, num_samples)
                self.frequency_axis = self.runtime.frequencies * 1e-6

            # trace = trace.reshape((len(self.time_axis), -1))
            PyPlotRuntimeComponent.update_line(self.data_re, self.time_axis, traces[1,:].real)
            PyPlotRuntimeComponent.update_line(self.data_im, self.time_axis, traces[1,:].imag)
            
            ylims = np.max([abs(np.max(traces[0,:].real)), 
                            abs(np.min(traces[0,:].real)), 
                            abs(np.max(traces[0,:].imag)), 
                            abs(np.min(traces[0,:].imag))])
            self.ax_data.set_xlim(0, self.time_axis[-1])
            self.ax_data.set_ylim(-ylims, ylims)
        
            mean = np.mean(traces, axis=1)
            logging.debug(f"Mean shape: {mean.shape}")
            if self.runtime.plot_electrical_delay != 0:        
                mean *= np.exp(1j * 2*np.pi * self.runtime.frequencies * self.runtime.plot_electrical_delay)                
            
            abs_mean = np.abs(mean)
            PyPlotRuntimeComponent.update_line(self.data_mag, self.frequency_axis, abs_mean)
            
            max_abs = np.max(abs_mean)
            logging.debug(f"Maximum magnitude: {max_abs}")
            self.ax_mag.set_xlim(self.frequency_axis[0], self.frequency_axis[-1])
            self.ax_mag.set_ylim(0, max_abs)
            
            phase = np.angle(mean)
            unwrapped_phase = np.unwrap(phase)
            
            if self.runtime.plot_electrical_delay == 0:
                from scipy.optimize import curve_fit
                
                def model(freqs, delay, phi0):
                    return 2*np.pi*freqs*delay + phi0
                
                popt,pcov = curve_fit(model, self.runtime.frequencies, unwrapped_phase)
                logging.info(f"Electrical delay fit returned popt={popt}, pcov={pcov}")
                self.fit_label.value = f"Electrical delay: {round(popt[0]*1e9, 2)} ns +/- {round(pcov[0,0]*1e12, 2)} ps"
                            
            phase_plot_data = unwrapped_phase if self.runtime.plot_unwrap_phase else phase
            PyPlotRuntimeComponent.update_line(self.data_phase, self.frequency_axis, phase_plot_data)
            
            self.ax_phase.set_xlim(self.frequency_axis[0], self.frequency_axis[-1])
            self.ax_phase.set_ylim(np.min(phase_plot_data), np.max(phase_plot_data))
