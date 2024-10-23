from dataclasses import dataclass
from acadia import Runtime

@dataclass
class ContinuousSynthesisRuntime(Runtime):
    """
    A Runtime for streaming a pulse out of a DAC channel repeatedly.
    """
    
    stimulus: dict

    # Amount of time in seconds to run for
    length: float = 5

    def main(self):        
        from acadia import Acadia
        import time
        
        acadia = Acadia()

        channel = acadia.channel(self.stimulus["channel"])
        pulse = acadia.create_waveform(channel, length_seconds=1e-6)
        
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
        time.sleep(self.length)
        acadia.sequencer_halt()

def run():
    stimulus: dict = {
        "channel": "DAC1",

        "datapath": {
            "vop": 12000,
            "mix_reconstruction": True,
            "nco_frequency": 4.6e9
        },

        "waveform": {
            "length": 1e-6,
            "fixed_length": 1e-6
        },
        
        "signal": {
            "data": ("scipy", "hann"),
            "scale": 0.99
        }
    }

    rt = ContinuousSynthesisRuntime(stimulus)
    rt.deploy("10.66.3.214")    
    rt.display()

    return rt
    
if __name__ == "__main__":
    rt = run()
    