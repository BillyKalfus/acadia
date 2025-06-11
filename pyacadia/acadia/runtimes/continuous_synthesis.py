from dataclasses import dataclass
from acadia import Runtime
import acadia.utils as utils
import logging

@dataclass
class ContinuousSynthesisRuntime(Runtime):
    """
    A Runtime for streaming a pulse out of a DAC channel indefinitely.
    """
    
    channel: str
    amplitude: float = 0.999
    frequency: float = 0
    mix_reconstruction: bool = True
    vop: int = 12000

    # Amount of time in seconds to run for
    timeout: float = 20

    FILE = __file__

    def main(self):        
        from acadia import Acadia
        import time
        
        acadia = Acadia()
        channel = acadia.channel(self.channel)
        pulse = acadia.create_waveform_memory(channel, length=1e-6)
        
        def sequence(a: Acadia):
            with a.sequencer().loop():
                # If there are no pulses queued for the channel, play another
                with a.sequencer().test(a.channel_is_fifo_empty(channel)):
                    with a.channel_synchronizer(block=False):
                        a.schedule_waveform(pulse)

        acadia.compile(sequence)
        acadia.attach()
        
        channel.set(
            nco_update_event_source="immediate", 
            mix_reconstruction=self.mix_reconstruction, 
            vop=self.vop, 
            nco_frequency=self.frequency)
        channel.nco_immediate_update_event()
        
        pulse.load(self.amplitude)
        
        acadia.assemble()
        acadia.load()
        
        acadia.run(block=False)
        time.sleep(self.timeout)
        
        utils.sequencer_halt_and_reset()

def run():
    rt = ContinuousSynthesisRuntime(channel="DAC2", 
                                    amplitude = 0.9,
                                    mix_reconstruction=True,
                                    frequency=6e9, 
                                    vop=10000)

    rt.deploy("10.66.3.224", "continuous_synthesis", files=[__file__])    
    rt.display()

    return rt
    
if __name__ == "__main__":
    rt = run()
    