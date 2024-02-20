from dataclasses import dataclass
from acadia.runtime import Runtime
from acadia.data import DataManager

@dataclass
class ConstantRuntime(Runtime):
    """
    A Runtime for streaming a constant pulse out of a DAC channel forever.
    No display is rendered, and the process must be manually killed when one
    wishes to end the synthesis.
    """
    
    # The channel to stream the constant on
    dac_channel: int

    # The carrier frequency of the constant signal
    nco_frequency: float

    # Amplitude of the constant loaded into memory
    pulse_amplitude: float = 1.0

    # Nyquist zone of the DAC to use
    channel_nyquist_zone: int = 2

    # Current reference for output channel
    channel_vop: int = 12000

    FILE = __file__

    def main(self, directory: str, datamanager: DataManager):        
        from acadia.system import Acadia
        from acadia.arrays import Waveform, ConstantWaveform
        
        acadia = Acadia()

        pulse_channel = acadia.DAC(self.dac_channel)
        pulse = ConstantWaveform(pulse_channel, length=1024)
        
        def sequence(a: Acadia):
            with a.sequencer().loop():
                # If there are no pulses queued for the channel, play another
                with a.sequencer().test(a.channel_occupancy(pulse_channel) == 0):
                    with a.channel_synchronizer(block=False):
                        a.generate(pulse)

        acadia.compile(sequence)
        acadia.attach()
        Waveform.from_complex(pulse, scale=self.pulse_amplitude)
        pulse_channel.set_nyquist_zone(self.channel_nyquist_zone)
        pulse_channel.configure_nco(frequency=self.nco_frequency)
        pulse_channel.set_vop(self.channel_vop)
        
        acadia.run()
    
