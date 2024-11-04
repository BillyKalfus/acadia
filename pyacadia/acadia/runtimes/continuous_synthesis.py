from dataclasses import dataclass
from acadia import Runtime
import acadia.utils as utils
import logging

@dataclass
class ContinuousSynthesisRuntime(Runtime):
    """
    A Runtime for streaming a pulse out of a DAC channel repeatedly.
    """
    
    stimulus: dict

    # Amount of time in seconds to run for
    timeout: float = 5

    def main(self):        
        from acadia import Acadia
        import time
        logger = logging.getLogger("acadia")
        
        acadia = Acadia()

        channel = acadia.channel(self.stimulus["channel"])
        pulse = acadia.create_waveform(channel, **self.stimulus["waveform"])
        
        def sequence(a: Acadia):
            with a.sequencer().loop():
                # If there are no pulses queued for the channel, play another
                with a.sequencer().test(a.channel_occupancy(channel) == 0):
                    with a.channel_synchronizer(block=False):
                        a.schedule_waveform(pulse)

        acadia.compile(sequence)
        acadia.attach()
        
        channel.set(nco_update_event_source="immediate", **self.stimulus["datapath"])
        channel.nco_immediate_update_event()
        
        pulse.set(**self.stimulus["signal"])
        
        acadia.assemble()
        acadia.load()
        
        acadia.run(block=False)
        time.sleep(self.timeout)
        
        # utils.sequencer_halt_and_reset()

def run():
    stimulus: dict = {
        "channel": "DAC4",

        "datapath": {
            "vop": 30000,
            "mix_reconstruction": False,
            "nco_frequency": 0.05e9
        },

        "waveform": {
            "length": 0.0,
            "fixed_length": 1e-6
        },
        
        "signal": {
            "data": ("scipy", "hann"),
            "scale": 0.99
        }
    }

    rt = ContinuousSynthesisRuntime(stimulus)
    rt.deploy("10.66.3.198", "continuous_synthesis", files=[__file__])    
    rt.display()

    return rt
    
if __name__ == "__main__":
    rt = run()
    