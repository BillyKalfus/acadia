from dataclasses import dataclass
from acadia.runtime import Runtime

@dataclass
class ConstantRuntime(Runtime):
    """
    A Runtime for streaming a constant pulse out of a DAC channel forever.
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

    def main(self):        
        from acadia.system import Acadia
        from acadia.arrays import ConstantWaveform
        
        acadia = Acadia()

        pulse_channel = acadia.DAC(self.dac_channel)
        pulse = ConstantWaveform(pulse_channel, length_seconds=1e-6)
        
        def sequence(a: Acadia):
            with a.sequencer().loop():
                # If there are no pulses queued for the channel, play another
                with a.sequencer().test(a.channel_occupancy(pulse_channel) == 0):
                    with a.channel_synchronizer(block=False):
                        a.generate(pulse)

        acadia.compile(sequence)
        acadia.attach()
        
        pulse[:] = self.pulse_amplitude
        pulse_channel.set_nyquist_zone(self.channel_nyquist_zone)
        pulse_channel.configure_nco(frequency=self.nco_frequency)
        pulse_channel.set_vop(self.channel_vop)
        
        acadia.run()
    
if __name__ == "__main__":
    rt = ConstantRuntime(dac_channel=0, nco_frequency=4.2e9)
    rt.deploy("192.168.2.69", "acadia.runtimes.constant")    
    rt.display()
    