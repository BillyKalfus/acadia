__all__ = ["Channel"]

from dataclasses import dataclass

import numpy as np

from .compiler import Processor

try:
    import pyxrfdc as xrfdc
except:
    pass

@dataclass
class Channel:
    """
    An abstraction of an RF data converter channel.
    
    Some parameters of the channel can be configured to update on a particular
    event. These events can be:  
    
    - ``"immediate"``: The update is carried out when the update function is
        called.
                
    - ``"slice"``: The update is carried out when ``nco_update_event`` is called
        on a `Channel` with both a block and a tile.
            
    - ``"tile"``: The update is carried out when `nco_update_event` is called 
        on a `Channel` with no block specified. This can be used to 
        synchronize updates for multiple channels in a tile.
            
    - ``"sysref"``: The update is carried out when a SYSREF event is generated
        by the CLK104. This can be used to synchronize updates 
        across tiles when the interface frequencies are the same
        and MTS is enabled.
                
    - ``"pl"``: The update is carried out when the corresponding signal is 
        driven from the PL. 

    """

    tile: int = None
    block: int = None
    is_dac: bool = None
    
    def __hash__(self):
        return hash((self.tile, self.block, self.is_dac))

    def __post_init__(self):
        self.num = self.tile*4 + self.block
        self.bank = (228 if self.is_dac else 224) + self.tile

        if self.tile > 4 or self.tile < 0:
            raise ValueError(f"Received invalid tile {self.tile}.")

        if self.block > 4 or self.block < 0:
            raise ValueError(f"Received invalid block {self.block}.")
            
    def name(self):
        return f"{'DAC' if self.is_dac else 'ADC'}{self.num}"
    
    def register_base_address(self):
        return xrfdc.lib.def_XRFDC_BLOCK_BASE(self.converter_type(), 
                                              self.tile, 
                                              self.block)
    
    def converter_type(self):
        return xrfdc.lib.XRFDC_DAC_TILE if self.is_dac else xrfdc.lib.XRFDC_ADC_TILE
    
    @classmethod
    def RFDC_init(cls):
        """
        Initializes the RFDC library and stores a reference to the initialized
        driver instance internally. This function should only be called on live
        hardware.
        """

        cls._rfdc = xrfdc.ffi.new("XRFdc*")
        cls._device_ptr = xrfdc.ffi.new("struct metal_device**")
        
        xrfdc.lib.metal_init_METAL_INIT_DEFAULTS()
        
        config_ptr = xrfdc.lib.XRFdc_LookupConfig(0)
        if config_ptr is xrfdc.ffi.NULL:
            raise ValueError("XRFdc_LookupConfig failed.")

        cls.RFDC_call_checked("RegisterMetal", 0, cls._device_ptr)
        cls.RFDC_call_checked("CfgInitialize", config_ptr)
        
    @classmethod
    def RFDC_call(cls, func_name, *args, **kwargs):
        """
        Call a function in the XRFDC driver. 

        :param func_name: Name of RFDC function to execute. Omit any "XRFdc_"
            prefix.
        :type func_name: str
        """

        if not hasattr(cls, "_rfdc"):
            raise ValueError("RFDC driver not initialized.")
            
        return getattr(xrfdc.lib, f"XRFdc_{func_name}")(cls._rfdc, *args, **kwargs)
        
    @classmethod
    def RFDC_call_checked(cls, func_name, *args, **kwargs):
        """
        Call a function in the XRFDC driver and throw an exception if the call
        returns a failure code.

        :param func_name: Name of RFDC function to execute. Omit any "XRFdc_"
            prefix.
        :type func_name: str
        """

        if not hasattr(cls, "_rfdc"):
            raise ValueError("RFDC driver not initialized.")
            
        if cls.RFDC_call(func_name, *args, **kwargs) != xrfdc.lib.XRFDC_SUCCESS:
            raise ValueError(f"XRFdc_{func_name} failed.")
            
    @classmethod
    def RFDC_def(cls, name):
        """
        Get a definition from the XRFDC library by name.
        """ 

        return getattr(xrfdc.lib, name)
    
    @classmethod
    def RFDC_struct(cls, name, init=None):
        """
        Get a definition from the XRFDC library by name.
        """

        if not hasattr(cls, "_rfdc"):
            raise ValueError("RFDC driver not initialized.")
            
        return xrfdc.ffi.new(name, init)
    
    @classmethod
    def RFDC_status(cls):
        """
        Get the status of the RFDC IP.
        """

        s = xrfdc.ffi.new("XRFdc_IPStatus*")
        cls.RFDC_call_checked("GetIPStatus", s)
        
        result = {}
        for dc in ["ADC", "DAC"]:
            for tile in range(4):
                tile_status = getattr(s, f"{dc}TileStatus")[tile]
                result[f"{dc}{tile}"] = {
                    "enabled": tile_status.IsEnabled,
                    "tile_state": tile_status.TileState,
                    "converters_enabled": tile_status.BlockStatusMask,
                    "powerup_state": tile_status.PowerUpState,
                    "PLL_locked": tile_status.PLLState
                }
                
        return result
    
    def status(self):
        """
        Get the status of the converter.
        """

        s = xrfdc.ffi.new("XRFdc_BlockStatus*")
        self.RFDC_call_checked("GetBlockStatus", 
                   self.converter_type(), 
                   self.tile, 
                   self.block, 
                   s)
        d = {
            "sampling_frequency": s.SamplingFreq,
            "is_FIFO_flags_enabled": bool(s.IsFIFOFlagsEnabled),
            "is_FIFO_flags_asserted": bool(s.IsFIFOFlagsAsserted),
            "all_required_clocks_enabled": bool(s.DataPathClocksStatus)
        }
        
        if self.is_dac:
            d["inverse_sinc_enabled"] = s.AnalogDataPathStatus & 0xF
            d["decoder_mode"] = (s.AnalogDataPathStatus >> 4) & 0xF
            d["fifo_enabled"] = s.DigitalDataPathStatus & 0xF
            d["interpolation_factor"] = (s.DigitalDataPathStatus >> 4) & 0xF
            d["adder_status"] = (s.DigitalDataPathStatus >> 8) & 0xF
            mixer_mode = (s.DigitalDataPathStatus >> 12) & 0xF
            
        else:
            d["converter_enabled"] = s.AnalogDataPathStatus
            d["fifo_enabled"] = s.DigitalDataPathStatus & 0xF
            d["decimation_factor"] = (s.DigitalDataPathStatus >> 4) & 0xF
            mixer_mode = (s.DigitalDataPathStatus >> 8) & 0xF

        for mode in ["OFF", "C2C", "C2R", "R2C"]:
            if mixer_mode == self.RFDC_def(f"XRFDC_MIXER_MODE_{mode}"):
                d["mixer_mode"] = mode
                break

        if "mixer_mode" not in d:
            raise ValueError(f"Invalid mixer mode {mixer_mode}")

        return d
    
    def startup(self):
        self.RFDC_call_checked("StartUp", self.converter_type(), self.tile)
        
    def shutdown(self):
        self.RFDC_call_checked("Shutdown", self.converter_type(), self.tile)
    
    @classmethod
    def shutdown_all(cls):
        cls.RFDC_call_checked("Shutdown", cls.RFDC_def("XRFDC_DAC_TILE"), -1)
        cls.RFDC_call_checked("Shutdown", cls.RFDC_def("XRFDC_ADC_TILE"), -1)
        
    @classmethod
    def startup_all(cls):
        cls.RFDC_call_checked("StartUp", cls.RFDC_def("XRFDC_DAC_TILE"), -1)
        cls.RFDC_call_checked("StartUp", cls.RFDC_def("XRFDC_ADC_TILE"), -1)
    
    def reset(self):
        self.RFDC_call_checked("Reset", self.converter_type(), self.tile)
        
    @classmethod
    def reset_all(cls):
        cls.RFDC_call_checked("Reset", cls.RFDC_def("XRFDC_DAC_TILE"), -1)
        cls.RFDC_call_checked("Reset", cls.RFDC_def("XRFDC_ADC_TILE"), -1)
        
    @classmethod
    def _clk_dst_tile_to_str(cls, clk_dst_tile):
        for tile in range(8):
            if clk_dst_tile == cls.RFDC_def(f"XRFDC_CLK_DST_TILE_{224+tile}"):
                return f"{'ADC' if tile < 4 else 'DAC'} Tile {tile % 4}"
        return None
    
    @classmethod
    def reset_clk_distribution(cls):
        s = xrfdc.ffi.new("XRFdc_Distribution_Settings*")
        cls.RFDC_call_checked("GetClkDistribution", s)
        cls.RFDC_call_checked("SetClkDistribution", s)
        
    @classmethod
    def get_clk_distribution(cls):
        s = xrfdc.ffi.new("XRFdc_Distribution_Settings*")
        cls.RFDC_call_checked("GetClkDistribution", s)
        result = {}
        for i in range(8):
            distribution_status = s.DistributionStatus[i]
                
            if distribution_status.Enabled == 1:
                d = {
                    "distribution_enabled": distribution_status.Enabled,
                    "distribution_source": Channel._clk_dst_tile_to_str(distribution_status.DistributionSource),
                    "distribution_upper_bound": Channel._clk_dst_tile_to_str(distribution_status.UpperBound),
                    "distribution_lower_bound": Channel._clk_dst_tile_to_str(distribution_status.LowerBound),
                    "distribution_max_delay": distribution_status.MaxDelay,
                    "distribution_min_delay": distribution_status.MinDelay,
                    "distribution_is_delay_balanced": bool(distribution_status.IsDelayBalanced),
                }

                result[f"dist{i}"] = d
            
        for i,dc in enumerate(["ADC", "DAC"]):
            for tile in range(4):
                clock_settings = getattr(s, dc)[tile]
                
                d = {
                    "clock_source_tile": Channel._clk_dst_tile_to_str(clock_settings.SourceTile),
                    "PLL_enabled": clock_settings.PLLEnable,
                    "clock_divider_if_PLL_bypassed": clock_settings.DivisionFactor,
                    "clock_delay_to_source_tile": clock_settings.Delay,
                    "PLL_Settings_Enabled": clock_settings.PLLSettings.Enabled,
                    "PLL_Settings_ref_clk_freq": clock_settings.PLLSettings.RefClkFreq,
                    "PLL_Settings_sample_rate": clock_settings.PLLSettings.SampleRate,
                    "PLL_Settings_ref_clk_divider": clock_settings.PLLSettings.RefClkDivider,
                    "PLL_Settings_feedback_divider": clock_settings.PLLSettings.FeedbackDivider,
                    "PLL_Settings_output_divider": clock_settings.PLLSettings.OutputDivider
                }
                
                if clock_settings.DistributedClock == cls.RFDC_def(f"XRFDC_DIST_OUT_NONE"):
                    d["distributed_clock"] = "not distributed"
                elif clock_settings.DistributedClock == cls.RFDC_def(f"XRFDC_DIST_OUT_RX"):
                    d["distributed_clock"] = "rx clock"
                elif clock_settings.DistributedClock == cls.RFDC_def(f"XRFDC_DIST_OUT_OUTDIV"):
                    d["distributed_clock"] = "output divider"
                else:
                    raise ValueError(f"Received invalid distributed clock"
                                     f" {clock_settings.DistributedClock}")
                result[f"{dc}{tile}"] = d
            
        return result
        
    def configure_nco(self, mixer_type=None, frequency=None, phase=None, update_source=None, mixer_mode=None):
        """
        Configures the modulator and NCO settings for the channel. The frequency
        and phase of the NCO will be cleared.

        :param enable: If ``False``, the NCO is disabled.
        :type enable: bool, optional
        :param frequency: The frequency of the NCO in Hz.
        :param phase: The phase offset of the NCO in radians
        :param update_source: The source of events upon which the NCO frequency
            and phase are updated. See the description of update event sources in the
            documentation of the :class:`Channel` object.
        :type update_source: str, optional
        """

        if (update_source is not None 
              and update_source.upper() not in ["IMMEDIATE", "SLICE", "TILE", "SYSREF", "PL", "MARKER"]):
            raise ValueError(f"Invalid source {update_source}.")
            
        settings = self.RFDC_struct("XRFdc_Mixer_Settings*")
        self.RFDC_call_checked("GetMixerSettings",
                       self.converter_type(), 
                       self.tile, 
                       self.block,
                       settings)
        
        if frequency is not None:
            settings.Freq = frequency/1e6
            
        if phase is not None:
            settings.PhaseOffset = 180*phase/np.pi
            
        if update_source is not None:
            settings.EventSource = self.RFDC_def(f"XRFDC_EVNT_SRC_{update_source.upper()}")
        else:
            settings.EventSource = self.RFDC_def(f"XRFDC_EVNT_SRC_IMMEDIATE")

        if mixer_mode is not None:
            settings.MixerMode = self.RFDC_def(f"XRFDC_MIXER_MODE_{mixer_mode.upper()}")
            
        if mixer_type is not None:
            settings.MixerType = self.RFDC_def(f"XRFDC_MIXER_TYPE_{mixer_type.upper()}")
            
        self.RFDC_call_checked("SetMixerSettings",
                       self.converter_type(), 
                       self.tile, 
                       self.block,
                       settings)
        
    
    def get_nco_settings(self):
        """
        :return: A dict with NCO settings
        :rtype: dict
        """

        settings = self.RFDC_struct("XRFdc_Mixer_Settings*")
        self.RFDC_call_checked("GetMixerSettings",
                       self.converter_type(), 
                       self.tile, 
                       self.block,
                       settings)
        d = {"frequency": settings.Freq*1e6,
             "phase": settings.PhaseOffset}
        
        for event_source in ["IMMEDIATE", "SLICE", "TILE", "SYSREF", "MARKER", "PL"]:
            if settings.EventSource == self.RFDC_def(f"XRFDC_EVNT_SRC_{event_source}"):
                d["event_source"] = event_source
                break
        if "event_source" not in d:
            raise ValueError(f"Received invalid event source {settings.EventSource}")
        
        for coarse_mix_freq in ["OFF", 
                                "SAMPLE_FREQ_BY_TWO", 
                                "SAMPLE_FREQ_BY_FOUR", 
                                "MIN_SAMPLE_FREQ_BY_FOUR", 
                                "BYPASS"]:
            if settings.CoarseMixFreq == self.RFDC_def(f"XRFDC_COARSE_MIX_{coarse_mix_freq}"):
                d["coarse_mixer_frequency"] = coarse_mix_freq
        if "coarse_mixer_frequency" not in d:
            raise ValueError(f"Invalid coarse mixer frequency {settings.CoarseMixerFreq}")
        
        for mixer_mode in ["OFF", "C2C", "C2R", "R2C"]:
            if settings.MixerMode == self.RFDC_def(f"XRFDC_MIXER_MODE_{mixer_mode}"):
                d["mixer_mode"] = mixer_mode
                break
        if "mixer_mode" not in d:
            raise ValueError(f"Invalid mixer mode {settings.MixerMode}")
        
        for fine_mixer_scale in ["AUTO", "1P0", "0P7"]:
            if settings.FineMixerScale == self.RFDC_def(f"XRFDC_MIXER_SCALE_{fine_mixer_scale}"):
                d["fine_mixer_scale"] = fine_mixer_scale
                break
        if "fine_mixer_scale" not in d:
            raise ValueError(f"Invalid mixer scale {settings.FineMixerScale}")
        
        for mixer_type in ["COARSE", "FINE", "OFF", "DISABLED"]:
            if settings.MixerType == self.RFDC_def(f"XRFDC_MIXER_TYPE_{mixer_type}"):
                d["mixer_type"] = mixer_type
                break
        if "mixer_type" not in d:
            raise ValueError(f"Invalid mixer type {settings.MixerType}")
        
        return d

    def configure_delay(self, delay=None, update_source=None):
        """
        Configures the delay line of the channel.

        :param delay: Number of samples to delay the output. 
        :type delay: int, optional
        :param update_source: Event source for updating the delay.
        :type update_source: str, optional
        """
        
        if (update_source is not None 
              and update_source not in ["immediate", "slice", "tile", "sysref", "pl"]):
            raise ValueError(f"Invalid source {update_source}.")
        
        settings = self.RFDC_struct("XRFdc_CoarseDelay_Settings*")
        self.RFDC_call_checked("GetCoarseDelaySettings",
                       self.converter_type(), 
                       self.tile, 
                       self.block,
                       settings)
        
        if delay is not None:
            settings.CoarseDelay = delay
            
        if update_source is not None:
            settings.EventSource = update_source
            
        self.RFDC_call_checked("SetCoarseDelaySettings",
                       self.converter_type(), 
                       self.tile, 
                       self.block,
                       settings)
        
    def get_delay(self):
        """
        :return: The number of samples by which the channel is delayed.
        :rtype: int
        """

        settings = self.RFDC_struct("XRFdc_CoarseDelay_Settings*")
        self.RFDC_call_checked("GetCoarseDelaySettings",
                       self.converter_type(), 
                       self.tile, 
                       self.block,
                       settings)
        
        return settings.CoarseDelay
    
    def delay_apply_update(self):
        """
        Trigger a delay update event from the RFDC software driver.
        """

        self.RFDC_call_checked("UpdateEvent", 
                       self.converter_type(), self.tile, self.block,
                       self.RFDC_def("XRFDC_EVENT_CRSE_DLY"))
        
    def frequency_to_nco_tuning_word(self, frequency):
        """
        Converts a frequency in Hz to the nearest integer tuning word for the
        NCO.

        :param frequency: Frequency in Hz
        :type frequency: float
        :return: NCO tuning word corresponding to the provided frequency
        :rtype: int
        """
        
        if not hasattr(self, "analog_sample_frequency"):
            raise ValueError("Channel missing sample rate information."
                             " Make sure that `configure_rfdc` was"
                             " called on the `Acadia` instance that produced"
                             " this `Channel` object.")
            
        # If we're using IMR mode, the NCO frequency is half
        nco_sample_frequency = self.analog_sample_frequency if self.analog_sample_frequency < 7e9 else self.analog_sample_frequency / 2
            
        word = frequency / nco_sample_frequency
        
        # Move the desired NCO frequency into the proper Nyquist zone
        # while word > 0.5:
        #     word -= 1
        # while word < -0.5:
        #     word += 1
        
        # We can just mask the appropriate bits of the word after multiplying    
        return int(round(word * (2**48))) & ((1 << 48)-1)
        
    def update_nco_frequency_registers(self, frequency_word, low=True, mid=True, high=True):
        """
        Configure some or all NCO settings. The three 16-bit registers for
        the frequency tuning word may be individually updated, allowing
        for lower latency when less precise changes are acceptable.

        :param frequency: Frequency in Hz
        :type frequency: float
        :param low: Indicates whether the low bits of the frequency tuning word
            are to be updated
        :type low: bool, optional
        :param mid: Indiciates whether the middle bits of the frequency tuning
            word are to be updated
        :type mid: bool, optional
        :param high: Indicates whether the high bits of the frequency tuning
            word are to be updated
        :type high: bool, optional
        """   
        
        if low:
            self.RFDC_call("WriteReg16Wrapper", 
                            self.register_base_address(), 
                            self.RFDC_def("XRFDC_ADC_NCO_FQWD_LOW_OFFSET"), 
                            frequency_word & 0xFFFF)
        if mid:
            self.RFDC_call("WriteReg16Wrapper", 
                            self.register_base_address(), 
                            self.RFDC_def("XRFDC_ADC_NCO_FQWD_MID_OFFSET"), 
                            (frequency_word >> 16) & 0xFFFF)
        if high:
            self.RFDC_call("WriteReg16Wrapper", 
                            self.register_base_address(), 
                            self.RFDC_def("XRFDC_ADC_NCO_FQWD_UPP_OFFSET"),
                            (frequency_word >> 32) & 0xFFFF)
            
    def read_nco_frequency_registers(self):
        """
        Read the current setting in the NCO frequency registers
        """
        low = self.RFDC_call("ReadReg16Wrapper", 
                            self.register_base_address(), 
                            self.RFDC_def("XRFDC_ADC_NCO_FQWD_LOW_OFFSET")) & 0xFFFF
        mid = self.RFDC_call("ReadReg16Wrapper", 
                            self.register_base_address(), 
                            self.RFDC_def("XRFDC_ADC_NCO_FQWD_MID_OFFSET")) & 0xFFFF
        high = self.RFDC_call("ReadReg16Wrapper", 
                            self.register_base_address(), 
                            self.RFDC_def("XRFDC_ADC_NCO_FQWD_UPP_OFFSET")) & 0xFFFF
        
        return (high << 32) | (mid << 16) | low
    
    def set_nco_update_source(self, source_string):
        if (source_string is not None 
              and source_string.upper() not in ["IMMEDIATE", "SLICE", "TILE", "SYSREF", "PL", "MARKER"]):
            raise ValueError(f"Invalid source {source_string}.")
        
        self.RFDC_call("ClrSetReg",
                        self.register_base_address(), 
                        self.RFDC_def("XRFDC_NCO_UPDT_OFFSET"), 
                        self.RFDC_def("XRFDC_NCO_UPDT_MODE_MASK"),
                        self.RFDC_def(f"XRFDC_EVNT_SRC_{source_string.upper()}"))
    
    def get_nco_update_source(self):
        EventSource = self.RFDC_call("RDReg", 
                                     self.register_base_address(), 
                                     self.RFDC_def("XRFDC_NCO_UPDT_OFFSET"), 
                                     self.RFDC_def("XRFDC_NCO_UPDT_MODE_MASK"))
        for source_string in ["IMMEDIATE", "SLICE", "TILE", "SYSREF", "MARKER", "PL"]:
            if EventSource == self.RFDC_def(f"XRFDC_EVNT_SRC_{source_string}"):
                return source_string.lower()
            
        raise ValueError(f"Invalid event source {EventSource}")
    
    def trigger_immediate_nco_update(self):
        self.RFDC_call("ClrSetReg",
                        self.register_base_address(), 
                        self.RFDC_def(f"XRFDC_{'DAC' if self.is_dac else 'ADC'}_UPDATE_DYN_OFFSET"), 
                        self.RFDC_def("XRFDC_UPDT_EVNT_MASK"),
                        self.RFDC_def("XRFDC_UPDT_EVNT_NCO_MASK"))
                
    def update_nco_phase_registers(self, phase, low=True, high=True):
        """
        Set the NCO phase offset to the given word.

        :param phase: Phase tuning word
        :type phase: int
        :param low: If ``True``, the lower 16 bits will be set.
        :type low: bool, optional
        :param high: If ``True``, the upper 2 bits will be set.
        :type high: bool, optional
        """

        if low:
            self.RFDC_call("WriteReg16Wrapper", 
                            self.register_base_address(), 
                            self.RFDC_def("XRFDC_NCO_PHASE_LOW_OFFSET"), 
                            phase & 0xFFFF)

        if high:
            self.RFDC_call("WriteReg16Wrapper", 
                            self.register_base_address(), 
                            self.RFDC_def("XRFDC_NCO_PHASE_UPP_OFFSET"),
                            (phase >> 16) & 0x3)
            
            
        
    def reset_nco_phase(self):
        """
        Reset the value of the NCO phase accumulator.
        """

        self.RFDC_call_checked("ResetNCOPhase", 
                               self.converter_type(), 
                               self.tile, 
                               self.block)
        
    def nco_apply_update(self):
        """
        Trigger an NCO update event from the RFDC software driver.
        """

        self.RFDC_call_checked("UpdateEvent", 
                       self.converter_type(), self.tile, self.block,
                       self.RFDC_def("XRFDC_EVENT_MIXER"))
        
    def set_vop(self, vop):
        """
        Sets the variable output power (VOP) of a DAC channel.

        :param vop: VOP output current setting in uA
        :type vop: int
        """

        if not self.is_dac:
            raise TypeError("VOP can only be set on DAC channels.")
         
        proc = Processor.active_processor()
        if proc is None:
            self.RFDC_call_checked("SetDACVOP", self.tile, self.block, vop)
                
        elif isinstance(proc, Sequencer):
            vop_reg = Firmware.rfdc_rts_regs.address().value() + 0x70 + self.num
            proc.bus_write(address=vop_reg, data=vop)
        
        else:
            raise TypeError(f"DAC VOP can only be set in"
                            f" `PythonProcessor` or `Sequencer` contexts"
                            f" (detected {proc}).")
            
    def get_vop(self):
        """
        :return: The output current in mA.
        :rtype: int
        """

        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetOutputCurr", self.tile, self.block, n)
        return n[0]
    
    def set_dsa(self, dsa):
        """
        Sets the digital step attenuator (DSA).

        :param dsa: Attenuation in dB
        :type dsa: float
        """

        if self.is_dac:
            raise TypeError("DSA can only be set on ADC channels.")
            
        proc = Processor.active_processor()
        if proc is None:
            settings = self.RFDC_struct("XRFdc_DSA_Settings*", [0, dsa])
            self.RFDC_call_checked("SetDSA", self.tile, self.block, settings)
                
        elif isinstance(proc, Sequencer):
            # Do nothing, the synchronizer will manage writing the codes
            # into the registers
            pass
        else:    
            raise TypeError("ADC DSA can only be set in"
                            " `PythonProcessor` or `Sequencer` contexts.")
            
    def get_dsa(self):
        """
        Gets the value of the digital step attenuator (DSA).
        """

        if self.is_dac:
            raise TypeError("DSA can only be read on ADC channels.")
            
        proc = Processor.active_processor()
        if proc is None:
            settings = self.RFDC_struct("XRFdc_DSA_Settings*")
            self.RFDC_call_checked("GetDSA", self.tile, self.block, settings)
            return settings
        
        raise TypeError("ADC DSA can only be set in"
                        " `PythonProcessor` or `Sequencer` contexts.")
    
    def set_tdd_mode(self, mode):
        """
        Set time-division duplexing (TDD) mode. Note that in the current version
        of the firmware, this will only apply for DACs.
        """

        # Do nothing. the synchronizer will calculate the register value and
        # write it
        pass

    def set_nyquist_zone(self, nz):
        """
        Sets the Nyquist zone setting of the channel to the specified number.

        :param nz: Nyquist zone
        :type nz: int
        """ 

        reg_value = self.RFDC_def(f"XRFDC_{'EVEN' if nz % 2 == 0 else 'ODD'}_NYQUIST_ZONE")
        
        self.RFDC_call_checked("SetNyquistZone", 
                       self.converter_type(), self.tile, self.block, reg_value)
        
    def get_nyquist_zone(self):
        """
        :return: The Nyquist zone configured for the channel.
        :rtype: int
        """

        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetNyquistZone", self.tile, self.block, n)
        return n[0]

    def set_decoder_mode(self, mode):
        """
        Sets the DAC decoder mode.

        :param mode: One of "low noise" or "high linearity"
        :type mode: str
        """

        if not self.is_dac:
            raise TypeError("Decoder mode may only be set for DACs.")
            
        if mode.lower() == "low noise":
            reg_value = self.RFDC_def(f"XRFDC_DECODER_MAX_SNR_MODE")
        elif mode.lower() == "high linearity":
            reg_value = self.RFDC_def(f"XRFDC_DECODER_MAX_LINEARITY_MODE")
        else:
            raise ValueError(f"Invalid decoder mode {mode}.")
        
        self.RFDC_call_checked("SetDecoderMode", self.tile, self.block, reg_value)
        
    def get_decoder_mode(self):
        """
        :return: The Nyquist zone configured for the channel.
        :rtype: int
        """

        if not self.is_dac:
            raise TypeError("Decoder mode may only be set for DACs.")
            
        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetDecoderMode", self.tile, self.block, n)
        if n[0] == self.RFDC_def(f"XRFDC_DECODER_MAX_SNR_MODE"):
            return "low noise"
        elif n[0] == self.RFDC_def(f"XRFDC_DECODER_MAX_LINEARITY_MODE"):
            return "high linearity"
        
        raise ValueError(f"Unexpected decoder response {n}")
        
    def set_inv_sinc_FIR(self, mode):
        """
        Sets the mode of the inverse-sinc FIR filter.
        
        :param mode: Filter mode. May be 0 (disable), 1 (first Nyquist zone),
            or 2 (second Nyquist zone)
        :type mode: int
        """

        if not self.is_dac:
            raise TypeError("InvSincFIR may only be set for DACs.")
            
        if mode not in [0, 1, 2]:
            raise ValueError(f"InvSincFIR mode must be 0, 1, or 2; received {mode}.")
            
        self.RFDC_call_checked("SetInvSincFIR", self.tile, self.block, mode)   
        
    def get_inv_sinc_FIR(self):
        """
        :return: The band for which the inverse-sinc FIR filter is programmed
            (see the definitions of return values in :meth:`set_inv_sinc_FIR`).
        :rtype: int
        """

        if not self.is_dac:
            raise TypeError("InvSincFIR may only be set for DACs.")
            
        n = xrfdc.ffi.new("unsigned short*")
        self.RFDC_call_checked("GetInvSincFIR", self.tile, self.block, n)
        return n[0]

    def set_dither(self, mode):
        """
        Enables or disables ADC dithering.

        :param mode: If ``True``, dithering is enabled; otherwise, it is disabled.
        :type mode: bool
        """

        if self.is_dac:
            raise TypeError("Dithering may only be set for ADCs.")
            
        self.RFDC_call_checked("SetDither", self.tile, self.block, bool(mode))
        
    def get_dither(self):
        """
        :return: ``True`` if dithering is enabled.
        :rtype: bool
        """

        if self.is_dac:
            raise TypeError("Dithering may only be set for ADCs.")
            
        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetDither", self.tile, self.block, n)
        return bool(n[0])
    
    def get_clk_source(self):
        """
        :return: Clock source for a tile
        :rtype: str
        """

        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetClockSource", self.converter_type(), self.tile, n)
        sources = [f"DAC{i}" for i in range(4)] + [f"ADC{i}" for i in range(4)]
        return sources[n[0]]
        
    def configure_PLL(self, source, ref_clk_frequency, sample_rate):
        """
        Configures the PLL and enables switching between internal and external
        clocking.

        :param source: One of "external" or "internal"
        :type source: str
        :param ref_clk_frequency: Frequency of the reference clock in MHz
        :type ref_clk_frequency: float
        :param sample_rate: Sample rate in MHz
        """ 

        # if self.block is not None:
        #     raise ValueError("Clocking can only be configured for tiles; block must be None.")
            
        if source == "internal":
            source_value = self.RFDC_def("XRFDC_INTERNAL_PLL_CLK")
        elif source == "external":
            source_value = self.RFDC_def("XRFDC_EXTERNAL_CLK")
        else:
            raise ValueError(f"Invalid PLL source {source}.")
            
        self.RFDC_call_checked("DynamicPLLConfig",
                        self.converter_type(), self.tile, 
                        source_value, ref_clk_frequency, sample_rate)
        
    def is_PLL_enabled(self):
        """
        :return: ``True`` if the tile PLL is enabled.
        :rtype: bool
        """

        settings = self.RFDC_struct("XRFdc_PLL_Settings*")
        self.RFDC_call_checked("GetPLLConfig",
                       self.converter_type(), 
                       self.tile, 
                       settings)
        
        return settings.Enabled
    
    def get_PLL_ref_clk(self):
        """
        :return: The programmed reference clock of the PLL.
        :rtype: float
        """

        settings = self.RFDC_struct("XRFdc_PLL_Settings*")
        self.RFDC_call_checked("GetPLLConfig",
                       self.converter_type(), 
                       self.tile, 
                       settings)
        
        return settings.RefClkFreq
    
    def get_PLL_sample_clk(self):
        """
        :return: The programmed sample clock of the PLL.
        :rtype: float
        """

        settings = self.RFDC_struct("XRFdc_PLL_Settings*")
        self.RFDC_call_checked("GetPLLConfig",
                       self.converter_type(), 
                       self.tile, 
                       settings)
        
        return settings.SampleRate
        
    def is_PLL_locked(self):
        """
        :return: ``True`` if tile PLL is locked.
        :rtype: bool
        """

        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetPLLLockStatus", self.tile, self.block, n)
        return n[0]

    def set_imr_passband(self, mode):
        """
        Sets the passband for a DAC NCO IMR filter, when enabled.

        :param mode: One of "lowpass" or "highpass"
        :type mode: str
        """

        if not self.is_dac:
            raise TypeError("IMR passband can only be set on DAC channels.")
            
        if mode.lower() in ["lowpass", "highpass"]:
            reg_value = self.RFDC_def(f"XRFDC_DAC_IMR_MODE_{mode.upper()}")
        else:
            raise ValueError(f"Invalid mode {mode}.")
        
        self.RFDC_call_checked("SetIMRPassMode", self.tile, self.block, reg_value)
        
    def get_imr_passband(self):
        """
        :return: The IMR passband
        :rtype: str
        """

        if not self.is_dac:
            raise TypeError("IMR passband can only be set on DAC channels.")
            
        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetIMRPassMode", self.tile, self.block, n)
            
        if n[0] == self.RFDC_def(f"XRFDC_DAC_IMR_MODE_LOWPASS"):
            return "lowpass"
        elif n[0] == self.RFDC_def(f"XRFDC_DAC_IMR_MODE_HIGHPASS"):
            return "highpass"
        
        raise ValueError(f"Received unexpected IMR setting {n}")
        
    def set_datapath_mode(self, mode):
        """
        Sets the datapath mode for DACs.

        :param mode: Datapath mode. Must be one of:
            - "Full-bandwidth NCO"
            - "Half-bandwidth NCO (lowpass)"
            - "Half-bandwidth NCO (highpass)"
            - "Bypass NCO"
        """

        if not self.is_dac:
            raise TypeError("Datapath mode can only be set on DAC channels.")
            
        if mode == "Full-bandwidth NCO":
            const = self.RFDC_def(f"XRFDC_DATAPATH_MODE_DUC_0_FSDIVTWO")
        elif mode == "Half-bandwidth NCO (lowpass)":
            const = self.RFDC_def(f"XRFDC_DATAPATH_MODE_DUC_0_FSDIVFOUR")
        elif mode == "Half-bandwidth NCO (highpass)":
            const = self.RFDC_def(f"XRFDC_DATAPATH_MODE_FSDIVFOUR_FSDIVTWO")
        elif mode == "Bypass NCO":
            const = self.RFDC_def(f"XRFDC_DATAPATH_MODE_NODUC_0_FSDIVTWO")
        else:
            raise ValueError(f"Invalid datapath mode \"{mode}\"")
        
        self.RFDC_call_checked("SetDataPathMode", self.tile, self.block, const)
        
    def get_datapath_mode(self):
        """
        :return: The datapath mode for the DAC
        :rtype: str
        """

        if not self.is_dac:
            raise TypeError("Datapath mode can only be set on DAC channels.")
            
        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetDataPathMode", self.tile, self.block, n)
            
        if n[0] == self.RFDC_def(f"XRFDC_DATAPATH_MODE_DUC_0_FSDIVTWO"):
            return "Full-bandwidth NCO"
        elif n[0] == self.RFDC_def(f"XRFDC_DATAPATH_MODE_DUC_0_FSDIVFOUR"):
            return "Half-bandwidth NCO (lowpass)"
        elif n[0] == self.RFDC_def(f"XRFDC_DATAPATH_MODE_FSDIVFOUR_FSDIVTWO"):
            return "Half-bandwidth NCO (highpass)"
        elif n[0] == self.RFDC_def(f"XRFDC_DATAPATH_MODE_NODUC_0_FSDIVTWO"):
            return "Bypass NCO"
        else:
            raise ValueError(f"Got unexpected datapath mode \"{n[0]}\"")
                
    def setup_fifo(self, enable):
        """
        Enables or disables the interface FIFO to a DAC or ADC tile.

        :param enable: If ``True``, the FIFO is enabled.
        :type enable: bool
        """ 

        self.RFDC_call_checked("SetupFIFO", self.converter_type(), self.tile, enable)
            
    def set_interpolation(self, factor):
        """
        Sets the interpolation factor for a DAC tile. The fabric write width
        is maintained at 128 bits with the understanding that the external 
        stream clock rate will be adjusted accordingly.

        :param factor: Interpolation factor
        :type factor: int
        """

        if not self.is_dac:
            raise TypeError("Interpolation can only be set on DAC channels.")

        if factor not in [1,2,3,4,5,6,8,10,12,16,20,24,40]:
            raise ValueError(f"Invalid interpolation factor {factor}.")
            
        self.RFDC_call_checked("SetInterpolationFactor", self.tile, self.block, factor)
                
        # Reconfigure the interface width to 128 bits
        self.RFDC_call_checked("SetFabWrVldWords", self.tile, self.block, 128 // 16)
        
    def get_interpolation(self):
        """
        :return: The interpolation factor set for the DAC channel.
        :rtype: int
        """

        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetInterpolationFactor", self.tile, self.block, n)
        return n[0]
        
    def set_decimation(self, factor):
        """
        Sets the decimation factor for an ADC tile. The fabric read width
        is maintained at 128 bits with the understanding that the external 
        stream clock rate will be adjusted accordingly.

        :param factor: Decimation factor
        :type factor: int
        """

        if self.is_dac:
            raise TypeError("Decimation can only be set on ADC channels.")
            
        if factor not in [0,1,2,3,4,5,6,8,10,12,16,20,24,40]:
            raise ValueError(f"Invalid decimation factor {factor}.")
            
        self.RFDC_call_checked("SetDecimationFactor", self.tile, self.block, factor)
                
        # Reconfigure the interface width to 128 bits
        self.RFDC_call_checked("SetFabRdVldWords", self.tile, self.block, 128 // 16)
        
    def get_decimation(self):
        """
        :return: The decimation factor set for the ADC channel.
        :rtype: int
        """

        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked("GetDecimationFactor", self.tile, self.block, n)
        return n[0]
    
    def get_interface_width(self):
        """
        :return: The width of the interface in bits.
        :rtype: int
        """

        n = xrfdc.ffi.new("unsigned int*")
        self.RFDC_call_checked(f"GetFab{'Wr' if self.is_dac else 'Rd'}VldWords", 
                                self.converter_type(),
                                self.tile, 
                                self.block, 
                                n)
        return n[0]*16
    
    def is_data_complex(self):
        return self.RFDC_call("GetDataType",
                                self.converter_type(), 
                                self.tile, 
                                self.block)

    @classmethod
    def set_sysref_enabled(cls, en):
        """
        Enable or disable analog SYSREF capture.
        """

        cls.RFDC_call_checked("MTS_Sysref_Config", 
                              cls.dac_mts_config, 
                              cls.adc_mts_config,
                              en)

    @classmethod    
    def MTS_init(cls):
        cls.DAC_MTS_config = cls.RFDC_struct("XRFdc_MultiConverter_Sync_Config*")
        xrfdc.lib.XRFdc_MultiConverter_Init(cls.DAC_MTS_config, xrfdc.ffi.NULL, xrfdc.ffi.NULL, 0)
        cls.ADC_MTS_config = cls.RFDC_struct("XRFdc_MultiConverter_Sync_Config*")
        xrfdc.lib.XRFdc_MultiConverter_Init(cls.ADC_MTS_config, xrfdc.ffi.NULL, xrfdc.ffi.NULL, 0)

    @classmethod
    def MTS_sync(cls):
        """
        Run multi-tile synchronization.
        """

        cls.ADC_MTS_config.RefTile = 0
        cls.ADC_MTS_config.Tiles = 0xF
        cls.ADC_MTS_config.Target_Latency = -1
        cls.ADC_MTS_config.SysRef_Enable = 1 # Disable SYSREF capture after the measurement

        for dc in ["DAC", "ADC"]:
            config = getattr(cls, f"{dc}_MTS_config")
            config.RefTile = 0
            config.Tiles = 0xF
            config.Target_Latency = -1
            config.SysRef_Enable = 1 # Disable SYSREF capture after the measurement
            
            for run in ["pre", "post"]:
                status = cls.RFDC_call("MultiConverter_Sync", 
                                        getattr(xrfdc.lib, f"XRFDC_{dc}_TILE"),
                                        config)
                
                if status != xrfdc.lib.XRFDC_MTS_OK:
                    raise ValueError(f"Call to `MultiConverter_Sync` ({dc} {run}) failed with"
                                    f" return value {status}.")
                
                result = {}
                for tile in range(4):
                    interpolation = cls(tile, 0, is_dac=(dc == "DAC")).get_interpolation()
                    result[f"{dc}_tile{tile}_interpolation_{run}"] = interpolation
                    result[f"{dc}_tile{tile}_latency_{run}"] = config.Latency[tile]
                    result[f"{dc}_tile{tile}_adjusted_delay_{run}"] = config.Offset[tile]

                # Find the longest latency
                latencies = [result[f"{dc}_tile{tile}_latency_{run}"] for tile in range(4)]
                result[f"{dc}_max_latency_{run}"] = max(latencies)

                # Set the target value and reiterate
                config.Target_Latency = result[f"{dc}_max_latency_{run}"] + 16

        return result
    
    def samples_to_bytes(self, samples):
        """
        :param samples: Number of samples
        :type samples: int
        :return: The amount of memory in bytes consumed by the given number of
            samples
        :rtype: int
        """

        return samples*4 
    
    def bytes_to_samples(self, num_bytes):
        """
        :param num_bytes: Amount of memory in bytes
        :type num_bytes: int
        :return: The number of samples resulting from interpreting the memory
            as an array of samples
        :rtype: int
        """
            
        # if self.complex_samples:
        if int(round(num_bytes/4, 3)) != num_bytes // 4:
            raise ValueError(f"Number of bytes ({num_bytes}) must be a"
                                " multiple of 4.")
        return num_bytes // 4
    
    def seconds_to_samples(self, duration):
        """
        :param duration: Duration in seconds to convert to a number of samples
        :type duration: float
        :return: The number of samples corresponding to the given time interval
        :rtype: int
        """

        if (not hasattr(self, "interface_sample_frequency")
            or not hasattr(self, "interface_width_bytes")):
            raise ValueError("Channel missing sample rate information."
                             " Make sure that `configure_rfdc` was"
                             " called on the `Acadia` instance that produced"
                             " this `Channel` object.")
        # Make sure that the requested duration is an integer number of samples
        duration_samples = int(round(duration * self.interface_sample_frequency))
        if abs(duration * self.interface_sample_frequency - duration_samples) > 1e-6:
            raise ValueError("Duration must be equivalent to an integer number of"
                             f" samples; found {duration * self.interface_sample_frequency} samples.")

        # Make sure that the number of samples in the pulse results in a valid 
        # number of cycles
        clock_speed = self.interface_sample_frequency / (self.interface_width_bytes // 4)
        duration_cycles = int(round(duration * clock_speed))
        if abs(duration * clock_speed - duration_cycles) > 1e-6:
            raise ValueError("Duration must be an integer number of cycles;"
                             f" found {duration * clock_speed} cycles"
                             f" ({duration_samples} samples).")

        return duration_samples
    
    def samples_to_seconds(self, samples):
        """
        :param samples: Number of samples to convert into a time interval
        :type samples: int
        :return: The duration of time in seconds corresponding to the given
            number of samples
        :rtype: float
        """

        if not hasattr(self, "interface_sample_frequency"):
            raise ValueError("Channel missing sample rate information."
                             " Make sure that `configure_rfdc` was"
                             " called on the `Acadia` instance that produced"
                             " this `Channel` object.")
        # Make sure that the requested duration is an integer number of samples
        return samples / self.interface_sample_frequency
    
    def seconds_to_bytes(self, duration):
        """
        :param duration: Duration in seconds
        :type duration: float
        :return: The amount of memory in bytes occupied by the number of 
            samples corresponding to the given duration
        :rtype: int
        """

        return self.seconds_to_samples(duration)*4 
    
    def bytes_to_seconds(self, num_bytes):
        """
        :param num_bytes: Amount of memory in bytes
        :type num_bytes: int
        :return: The length of time in seconds of the signal produced by 
            interpreting the memory as an array of samples
        :rtype: float
        """

        if not hasattr(self, "interface_sample_frequency"):
            raise ValueError("Channel missing sample rate information."
                             " Make sure that `configure_rfdc` was"
                             " called on the `Acadia` instance that produced"
                             " this `Channel` object.")
        
        return (num_bytes//4) / self.interface_sample_frequency
    