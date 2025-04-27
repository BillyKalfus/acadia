from acadia.system import Acadia
from acadia.channel import Channel
import pyxrfdc as xrfdc

acadia = Acadia()
acadia.attach()

acadia.configure_clocks(reference="external")

# Using their own PLLs, distributing a reference:
settings = xrfdc.ffi.new("XRFdc_Distribution_Settings*")
Channel.RFDC_call_checked("GetClkDistribution", settings)

settings.DAC[0].SourceTile = Channel.RFDC_def("XRFDC_CLK_DST_TILE_230")
settings.DAC[1].SourceTile = Channel.RFDC_def("XRFDC_CLK_DST_TILE_230")
settings.DAC[2].SourceTile = Channel.RFDC_def("XRFDC_CLK_DST_TILE_230")
settings.DAC[3].SourceTile = Channel.RFDC_def("XRFDC_CLK_DST_TILE_230")

settings.DAC[0].PLLEnable = True
settings.DAC[1].PLLEnable = True
settings.DAC[2].PLLEnable = True
settings.DAC[3].PLLEnable = True

settings.DAC[0].PLLSettings.Enabled = True
settings.DAC[1].PLLSettings.Enabled = True
settings.DAC[2].PLLSettings.Enabled = True
settings.DAC[3].PLLSettings.Enabled = True

settings.DAC[0].PLLSettings.RefClkFreq = 250
settings.DAC[1].PLLSettings.RefClkFreq = 250
settings.DAC[2].PLLSettings.RefClkFreq = 250
settings.DAC[3].PLLSettings.RefClkFreq = 250

settings.DAC[0].PLLSettings.SampleRate = 6400
settings.DAC[1].PLLSettings.SampleRate = 6400
settings.DAC[2].PLLSettings.SampleRate = 6400
settings.DAC[3].PLLSettings.SampleRate = 6400

settings.DAC[0].DistributedClock = Channel.RFDC_def("XRFDC_DIST_OUT_NONE")
settings.DAC[1].DistributedClock = Channel.RFDC_def("XRFDC_DIST_OUT_NONE")
settings.DAC[2].DistributedClock = Channel.RFDC_def("XRFDC_DIST_OUT_RX")
settings.DAC[3].DistributedClock = Channel.RFDC_def("XRFDC_DIST_OUT_NONE")

settings.ADC[0].PLLSettings.SampleRate = 2400
settings.ADC[1].PLLSettings.SampleRate = 2400
settings.ADC[2].PLLSettings.SampleRate = 2400
settings.ADC[3].PLLSettings.SampleRate = 2400

Channel.RFDC_call_checked("SetClkDistribution", settings)