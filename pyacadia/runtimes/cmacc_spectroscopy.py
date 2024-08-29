from spectroscopy import SpectroscopyRuntime

class CMACCSpectroscopyRuntime(SpectroscopyRuntime):
    """
    A Runtime for performing spectroscopy using the CMACC module for integration.
    """
        
    def main(self):       
        import numpy as np 
        from acadia.system import Acadia
        
        acadia = Acadia()
        stimulus_channel = acadia.channel(self.stimulus["channel"])
        capture_channel = acadia.channel(self.capture["channel"])

        stimulus_waveform = acadia.create_waveform(stimulus_channel, **self.stimulus["waveform"])

        # For the capture waveform, we need to set decimation to zero so that
        # the output will be a single sample
        capture_waveform = acadia.create_waveform(capture_channel, decimation=0, **self.capture["waveform"]) 
                
        self.data.add_group("traces", uniform=True)
                
        def sequence(a: Acadia):
            # When specifying no kernel, a single-sample array will be returned to
            # be populated with the amplitude for a boxcar kernel
            capture_stream, kernel = acadia.configure_cmacc(capture_channel, reset_fifo=True)
            acadia.cmacc_load(capture_stream, 0)
            with a.channel_synchronizer():
                a.schedule_waveform(stimulus_waveform)
                a.stream(capture_stream, capture_waveform)

            # We can return anything here and it will be returned by Acadia.compile
            return kernel

        kernel = acadia.compile(sequence)
        acadia.attach()
        acadia.align_tile_latencies()

        # When we set the channel properties, configure the NCO for synchronization
        stimulus_channel.set(**self.stimulus["datapath"])
        stimulus_channel.set_nco(update_source="sysref")
        capture_channel.set(**self.capture["datapath"])
        capture_channel.set_nco(update_source="sysref")

        stimulus_waveform.set(**self.stimulus["signal"])
        kernel.set(np.float64(0.1))

        acadia.load(*acadia.assemble())

        for i in range(self.iterations):
            for frequency in self.frequencies:
                # Synchronously set the modulation frequencies and reset phases
                acadia.update_nco_frequency(stimulus_channel, frequency=frequency)
                acadia.update_nco_frequency(capture_channel, frequency=-frequency)
                acadia.reset_nco_phase(stimulus_channel)
                acadia.reset_nco_phase(capture_channel)
                acadia.update_ncos_synchronized()

                # Run the sequencer                        
                acadia.run(assemble=False)
                self.data["traces"].write(capture_waveform.array)
                # self.data["traces"].write(np.array([[1000, 2000]], dtype=np.int32))
            
                # Check whether the host wants data
                self.data.serve()

def run(plot=True):
    import numpy as np

    stimulus: dict = {
        "channel": "DAC4",

        "datapath": {
            "vop": 4000,
            "nyquist_zone": 2
        },

        "waveform": {
            "length": 64e-9,
            "fixed_length": 2e-6
        },
        
        "signal": {
            "data": ("scipy", "hann"),
            "scale": 0.8
        }
    }
    
    capture: dict = {
        "channel": "ADC4",

        "datapath": {
            "nyquist_zone": 2
        },

        "waveform": {
            "length": 2.56e-6,
            "region": "plddr"
        }
    }

    frequencies = np.linspace(9.15e9, 9.25e9, 201)

    # Run the program on the target
    rt = CMACCSpectroscopyRuntime(
        frequencies=frequencies,
        stimulus=stimulus,
        capture=capture,
        iterations=1000,
        plot=plot,
        electrical_delay=108e-9)
    rt.deploy("192.168.2.70", "cmacc_spectroscopy", files=[__file__, "spectroscopy.py"])    
    rt.display()
    
    return rt

if __name__ == "__main__":
    rt = run()