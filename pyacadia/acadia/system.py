__all__ = ["Acadia", "ChannelSynchronizer"]

import os
import mmap
import time
import logging
from dataclasses import dataclass
from functools import wraps

import numpy as np

from .compiler import ManagedResource, ManagedMemory, Processor, Synchronizer, Operation, Symbol
from .sequencer import Sequencer
from .dma import DMA
from .channel import Channel
from .peripherals import RFClk, PSGPIO, ZDMA, AXISSwitch
from .firmware import Firmware

class DMASynchronizer(Synchronizer):
    """
    Synchronizes DMA triggers.
    """
    
    DMA = 1
    BARRIER = 2
    
    def __call__(self, *args, **kwargs):
        if not isinstance(Processor.active_processor(), Sequencer):
            raise TypeError("Synchronization is only supported for contexts of"
                            " a `Sequencer` object. Either enter an appropriate"
                            " context to enforce synchronization or call the"
                            " appropriate method to act directly on the"
                            " hardware.")
            
        self._dma_trigger = kwargs.pop("trigger", True)
        self._dma_block = kwargs.pop("block", self._dma_trigger) # don't block if we don't trigger
        return super().__call__(*args, **kwargs)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Get a reference to the Sequencer
        proc = Processor.active_processor()
        
        # Keep track of the aggregate values of all the calls
        # Store the mask so that if we don't block, we can know which DMAs were triggered
        self._acadia = None
        
        # Keep track of the total runtime for each channel since the last 
        # barrier (or since the start, if there haven't been any barriers 
        # yet) so that when we do add one, we can know where to add it
        channel_lengths = {}
        
        self.dma_mask = 0

        for idx_call,(retval,call) in enumerate(self._calls):
            function,acadia,args,kwargs = call.values()
            
            if self._acadia is None:
                self._acadia = acadia
            elif acadia is not self._acadia:
                raise ValueError(f"Unable to synchronize different instances"
                                 f" of `Acadia`")
                
            if function == DMASynchronizer.DMA:
                if not isinstance(kwargs["channel"], Channel):
                    raise TypeError(f"Unable to identify channel (received"
                                    f" {kwargs['channel']}).")
                
                if kwargs["channel"] in channel_lengths:
                    channel_lengths[kwargs["channel"]] += kwargs["length"]
                else:
                    channel_lengths[kwargs["channel"]] = kwargs["length"]
                    
                self.dma_mask |= acadia.get_dma(kwargs["channel"]).mask
                descriptor = acadia.channel_dma_stream(**kwargs)
                retval.assign(descriptor)
                
            elif function == DMASynchronizer.BARRIER:
                # We first need to figure out the time in the block at which 
                # the barrier exists.
                barrier_time = 0
                for length in channel_lengths.values():
                    if not isinstance(length, int):
                        raise TypeError(f"Received invalid length: {length}")
                    if length > barrier_time:
                        barrier_time = length
                        
                # Then, for every channel that has some action after the 
                # barrier, we need to add a blank so that the next action 
                # starts at the right time
                future_channels = []
                for idx_future_call in range(idx_call+1, len(self._calls)):
                    if (self._calls[idx_future_call]["function"] == DMASynchronizer.DMA 
                            and self._calls[idx_future_call]["kwargs"]["channel"] not in future_channels):
                        future_channels.append(self._calls[idx_future_call]["kwargs"]["channel"])
                
                descriptors = []
                for channel in future_channels:
                    delay_length = barrier_time - (channel_lengths[channel] if channel in channel_lengths else 0)
                    descriptor = acadia.channel_dma_stream(channel=channel,
                                              length=delay_length,
                                              word_address=0,
                                              blank=True)
                    descriptors.append(descriptor)
                retval.assign(descriptors)
                    
                # Reset channel lengths so that when we hit the next barrier 
                # (if any) it only adds delays after this one
                channel_lengths = {}
                
        if self.dma_mask == 0:
            raise ValueError("Empty synchronizer")
        
        # Add instructions to do so now
        if self._dma_trigger:
            # The only parent object that we could have had was an Acadia object,
            # so we know on which object we should call dma_trigger
            dma_trigger_device = self._acadia._firmware.sequencer_bus_decoder["dma_trigger"]
            proc.bus_write(address=dma_trigger_device.address().value(),
                            data=self.dma_mask,
                            comment="Trigger DMAs")

        if self._dma_block:
            # Wait until all the DMAs in the mask have completed
            dma_running_device = self._acadia._firmware.sequencer_bus_decoder["dma_running"]
            bus_op = proc.bus_read(dma_running_device.address().value(),
                        latency=self._acadia.get_bus_latency("dma_running_dataport"))
            with proc.repeat_until(bus_op & self.dma_mask == 0):
                pass

        super().__exit__(exc_type, exc_val, exc_tb)

class RFDCSynchronizer(Synchronizer):
    """
    Synchronizes DMA triggers, frequency and phase updates for NCOs, 
    DAC VOP and ADC DSA updates for the analog datapaths, and DAC TDD signals. 
    The constants below indicate how functions should be named in order to
    carry out the correct behavior in the synchronizer. For synchronized 
    functions that don't have the channel to be acted on as a parent, the 
    first positional argument must be the channel (if the channel is not 
    expected to be passed in as a keyword argument; if so, the corresponding
    keyword value will be used).
    """

    NCO_FREQUENCY = 2
    NCO_PHASE = 3
    NCO_PHASE_RESET = 4
    VOP = 5
    DSA = 6
    TDD = 7
    
    def __call__(self, *args, **kwargs):
        if not isinstance(Processor.active_processor(), Sequencer):
            raise TypeError("Synchronization is only supported for contexts of"
                            " a `Sequencer` object. Either enter an appropriate"
                            " context to enforce synchronization or call the"
                            " appropriate method to act directly on the"
                            " hardware.")

        self._nco_pl_event = kwargs.pop("nco_pl_event", False)
        return super().__call__(*args, **kwargs)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Get a reference to the Sequencer
        proc = Processor.active_processor()
        
        # Keep track of the aggregate values of all the calls
        nco_phase_reset = 0
        nco_update_enables = [0]*8
        nco_update_request = 0
        vop_dsa_update_reg = 0
            
        # The DAC VOP codes each have their own register but the DSA codes
        # are stored together by tile, so we need to aggregate
        tile_dsa_codes = [0]*4
        
        tdd_mode_set_reg = 0
        tdd_mode_clear_reg = 0
        
        self._acadia = None
        
        for call in self._calls:
            retval,(function,acadia,args,kwargs) = call.values()
            
            if self._acadia is None:
                self._acadia = acadia
            elif acadia is not self._acadia:
                raise ValueError(f"Unable to synchronize different instances of `Acadia`")

            channel = kwargs["channel"] if "channel" in kwargs else args[0]
            if not isinstance(channel, Channel):
                raise TypeError(f"Unable to identify channel (received {channel}).")
            
            
            rfdc_bit_position = 1 << (channel.num if channel.is_dac else channel.num+16)
                
            if function == RFDCSynchronizer.NCO_FREQUENCY:
                if isinstance(proc, Sequencer):
                    # The bit position for the channel in the update request and 
                    # phase reset registers
                    nco_update_request |= 1 << ((channel.tile+4) if not channel.is_dac else channel.tile)

                    # Which register for setting the update enable pins does this 
                    # channel belong to?
                    update_enable_reg = 4*channel.tile + (4 if not channel.is_dac else 0)

                    # if kwargs["low"]:
                    nco_update_enables[update_enable_reg] |= (1 << 0) << (6*channel.block)
                    # if kwargs["mid"]:
                    nco_update_enables[update_enable_reg] |= (1 << 1) << (6*channel.block)
                    # if kwargs["high"]:
                    nco_update_enables[update_enable_reg] |= (1 << 2) << (6*channel.block)

            elif function == RFDCSynchronizer.NCO_PHASE:
                if isinstance(proc, Sequencer):
                    # The bit position for the channel in the update request and 
                    # phase reset registers
                    nco_update_request |= 1 << ((channel.tile+4) if not channel.is_dac else channel.tile)

                    # Which register for setting the update enable pins does this 
                    # channel belong to?
                    update_enable_reg = 4*channel.tile + (4 if not channel.is_dac else 0)

                    # if kwargs["low"]:
                    nco_update_enables[update_enable_reg] |= (1 << 3) << (6*channel.block)
                    # if kwargs["high"]:
                    nco_update_enables[update_enable_reg] |= (1 << 4) << (6*channel.block)

            elif function == RFDCSynchronizer.NCO_PHASE_RESET:
                if isinstance(proc, Sequencer):
                    # The bit position for the channel in the update request and 
                    # phase reset registers
                    nco_update_request |= 1 << ((channel.tile+4) if not channel.is_dac else channel.tile)

                    # Which register for setting the update enable pins does this 
                    # channel belong to?
                    update_enable_reg = 4*channel.tile + (4 if not channel.is_dac else 0)

                    nco_phase_reset |= rfdc_bit_position
                    nco_update_enables[update_enable_reg] |= (1 << 5) << (6*channel.block)
                
            elif function == RFDCSynchronizer.VOP:
                if isinstance(proc, Sequencer):
                    vop_dsa_update_reg |= 1 << (4*channel.tile + channel.block)
                
            elif function == RFDCSynchronizer.DSA:
                if isinstance(proc, Sequencer):
                    vop_dsa_update_reg |= 1 << (16 + channel.tile)
                    data = args[0] << (channel.block*5)
                    mask = 0b11111 << (channel.block*5)
                    tile_dsa_codes[channel.tile] = (tile_dsa_codes[channel.tile] & ~mask) | data
                
            elif function == RFDCSynchronizer.TDD:
                if isinstance(proc, Sequencer):
                    if args[0]:
                        tdd_mode_set_reg |= rfdc_bit_position
                    else:
                        tdd_mode_clear_reg |= rfdc_bit_position
                else:
                    raise TypeError("TDD mode may only be controlled by the"
                                    " Sequencer. Enter the corresponding"
                                    " context to control TDD mode.")
        
        rts_address = self._acadia._firmware.rfdc_rts_regs.address().value()

        # Generate register writes for all the NCO updates that need to happen
        if nco_update_request != 0:
            for tile in range(8):
                if nco_update_enables[tile] != 0:
                    proc.bus_write(address=rts_address + 0x60 + tile,
                                    data=nco_update_enables[tile], 
                                    comment=f"Set update enable for tile {tile}")

            if nco_phase_reset != 0:
                proc.bus_write(address=rts_address + 0x68, 
                                data=nco_phase_reset,
                                comment="Set phase reset register")

            # Carry out the procedure for a synchronized update with SYSREF
            # We'll assume that the SYSREF is already being generated continuously

            # 1. Set dac0_sysref_int_gating high and pulse dac0_nco_update_req
            proc.bus_write(address=rts_address + 0x69, 
                            data=((1 << 8) | (1 << 0)),
                            comment="Set sysref_gating high and dac0_nco_update_req")
            proc.nop()
            proc.bus_write(address=rts_address + 0x69, 
                            data=(1 << 8),
                            comment="Clear dac0_nco_update_req")

            # 2. Wait until dac0_nco_update_busy[1] goes high, indicating that
            #    SYSREF has been properly gated
            with proc.repeat_until(proc.bus_read(rts_address) & (1 << 1) != 0):
                pass

            # 3. Pulse the rest of the nco_update_req signals if necessary
            #    (and make sure to keep dac0_sysref_int_gating high)
            if (nco_update_request & ~(1 << 0)) != 0:
                proc.bus_write(address=rts_address + 0x69, 
                            data=((1 << 8) | nco_update_request),
                            comment="Set the other nco_update_req signals")
                proc.nop()
                proc.bus_write(address=rts_address + 0x69, 
                                data=(1 << 8),
                                comment="Clear the other nco_update_req signals")

            # 4. Wait until all the busy outputs (except for dac0_nco_update_busy[1])
            #    are low
            m = 0xFFFF & ~(1 << 1)
            with proc.repeat_until(proc.bus_read(rts_address) & m == 0):
                pass

            # 5. Re-enable SYSREF by pulsing dac0_sysref_int_reenable
            proc.bus_write(address=rts_address + 0x69, 
                            data=((1 << 9)|(1 << 8)),
                            comment="Set dac0_sysref_int_reenable")
            proc.nop()
            proc.bus_write(address=rts_address + 0x69, 
                            data=(1 << 8),
                            comment="Clear dac0_sysref_int_reenable")

            # 6. Wait until dac0_nco_update_busy[1] goes low
            with proc.repeat_until(proc.bus_read(rts_address) & 0xFFFF == 0):
                pass

            # Do we ever need to set dac0_nco_sysref_int_gating low? If so, do it here
            proc.bus_write(address=rts_address + 0x69, 
                            data=0,
                            comment="Clear sysref_gating")

            if self._nco_pl_event:
                # Write the PL event register
                # The bit pattern is the same as for the update request register
                # and the blocks we want to drive events for will be the same
                # Pulse it for one cycle
                proc.bus_write(address=rts_address + 0x6C, 
                                data=nco_update_request,
                                comment="Set the pl_event register")
                proc.nop()
                proc.bus_write(address=rts_address + 0x6C, 
                                data=0,
                                comment="Clear the pl_event register")

        # Write any DSA updates
        for i in range(4):
            if vop_dsa_update_reg & (1 << (16+i)):
                proc.bus_write(address=rts_address + 0x80, 
                                data=tile_dsa_codes[i],
                                comment=f"Set DSA register for tile {i}")

        # Update VOP if necessary
        if vop_dsa_update_reg != 0:
            proc.bus_write(address=rts_address + 0x6D, 
                            data=vop_dsa_update_reg,
                            comment=f"Set VOP/DSA update register")

        if tdd_mode_set_reg != 0:
            proc.bus_write(address=rts_address + 0x6B, 
                            data=tdd_mode_set_reg,
                            comment="Write TDD mode set register")
        if tdd_mode_clear_reg != 0:
            proc.bus_write(address=rts_address + 0x6C, 
                            data=tdd_mode_clear_reg,
                            comment="Write TDD mode clear register")
            
        super().__exit__(exc_type, exc_val, exc_tb)
    
class Acadia:
    """
    A class that implements system-wide commands for the Acadia hardware.
    """
    
    def requires_sequencer(func):
        """
        A decorator for functions in the :class:`Acadia` class that must be 
        called in the context of a :class:`Sequencer`\.

        :param func: Function to wrap
        :type func: callable
        """

        @wraps(func)
        def _wrapped(acadia_self, *args, **kwargs):
            if acadia_self._active_sequencer is None:
                raise TypeError(f"Function {func.__name__} must be"
                                " called in the context of a sequencer.")
            return func(acadia_self, *args, **kwargs)
            
        return _wrapped
    
    def __init__(self, firmware=None):    
        self._firmware = Firmware(firmware)
        
        def input_switch_port(res_self):
            return self._firmware.stream_inputs()[res_self.kind][res_self._resource_id]
        
        self._stream_input_resources = {k: ManagedResource(f"{k}StreamInput", 
                                                           (), 
                                                           {"kind": k, 
                                                            "switch_port": input_switch_port}, 
                                                           allocation_limit=len(v)) 
                                        for k,v in self._firmware.stream_inputs().items()}
        
        def module_switch_port(res_self):
            return self._firmware.stream_modules()[res_self.kind][res_self._resource_id]
        
        self._stream_module_resources = {k: ManagedResource(f"{k}Module", 
                                                           (), 
                                                           {"kind": k,
                                                            "switch_port": module_switch_port}, 
                                                           allocation_limit=len(v)) 
                                        for k,v in self._firmware.stream_modules().items()}
        
        # Create various Processors
        # Note that the Processors cannot be ManagedMemory (and therefore, have the
        # Processor objects keep track of their instruction memory usage) 
        # because when Instruction objects are requested, the number of native
        # instruction words that they'll compile into isn't know until ``compile``
        # is actually called, which only happens once all the Instruction
        # resources have been created
        self._sequencer_type = ManagedResource("Sequence", (Sequencer,), {})
                    
        # When we enter contexts, keep track of the active sequencer
        self._active_sequencer = None

        # Create a synchronizer for channel actions
        self.channel_synchronizer = DMASynchronizer(allow_standalone=True)
        self.tile_synchronizer = RFDCSynchronizer(allow_standalone=True)
        
        self._create_dmas()
        self._create_cache()
        self._create_dac_arrays()
        self._create_cmacc_kernel_arrays()
        self._create_pl_ddr_arrays()
        self._create_ps_ddr_arrays()
        self._create_ocm_arrays()
        self._create_zdma()
        self._create_channels()
        self._create_switches()       
        
    def attach(self):
        """
        Maps system memory and connects to hardware drivers.
        """

        self._mem_file = os.open("/dev/mem", os.O_SYNC | os.O_RDWR)
        self._mem_maps = []
        
        self._attach_resource(self.CacheArray, default_dtype=np.uint32)
        self._attach_resource(self.OCMArray, default_dtype=np.uint32)
        
        # Map instruction memory for all of the processors
        self._sequencer_instruction_memory = self._attach_memory(
            address=self._firmware["sequencer_instruction_memory"]["address"],
            size=self._firmware["sequencer_instruction_memory"]["size_bits"] // 8)  
        
        self._dac_dma_descriptor_memory = [self._attach_memory(
            address=(self._firmware["dac_dma_descriptor_memory"]["address"] 
                    + i*(self._firmware["dac_dma_descriptor_memory"]["size_bits"] // 8)),
            size=self._firmware["dac_dma_descriptor_memory"]["size_bits"] // 8) for i in range(self._firmware.NUM_DACS)]
                
        self._adc_dma_descriptor_memory = [self._attach_memory(
            address=(self._firmware["adc_dma_descriptor_memory"]["address"] 
                    + i*(self._firmware["adc_dma_descriptor_memory"]["size_bits"] // 8)),
            size=self._firmware["adc_dma_descriptor_memory"]["size_bits"] // 8) for i in range(self._firmware.NUM_ADCS)]
            
        for dac_mem in self.DACArray:
            self._attach_resource(dac_mem)
            
        for cmacc_kernel_mem in self.CMACCKernelArray:
            self._attach_resource(cmacc_kernel_mem)
                
        self._attach_resource(self.PLDDR0Array)
        self._attach_resource(self.PLDDR1Array)
        self._attach_resource(self.PSDDRArray)
            
        # Connect to the RFDC driver and initialize
        Channel.RFDC_init()
        
        RFClk.init(self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["clk104_spi0"])
        
        # Connect the switches
        self._ADC_input_switch.attach(self._attach_memory(
            address=self._firmware["stream_processing_path"]["adc_input_switch"]["axi_address"], 
            size=self._firmware["stream_processing_path"]["adc_input_switch"]["axi_size_bits"] // 8,
            dtype=np.uint32))
        
        self._stream_processing_path_input_switch.attach(self._attach_memory(
            address=self._firmware["stream_processing_path"]["input_switch"]["axi_address"], 
            size=self._firmware["stream_processing_path"]["input_switch"]["axi_size_bits"] // 8,
            dtype=np.uint32))
        
        # Connect to the PS GDMA
        for instance in self._ZDMA.instances:
            instance.attach(self._attach_memory(
                address=0xFD50_0000 + (instance._resource_id*0x1_0000),
                size=0x1_0000))
            
        # Connect to the GPIO registers and store sequencer bus addresses for the GPIO dataports
        self._psgpio_mem = self._attach_memory(0xFF0A0000, 0x400, dtype=np.uint32)
            
        # Configure and connect to the sysfs interface for various GPIO        
        self._sequencer_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["sequencer_run"]
        PSGPIO.sysfs_export(self._sequencer_gpio)
        PSGPIO.sysfs_set_direction(self._sequencer_gpio, "out")
        PSGPIO.sysfs_write(self._sequencer_gpio, 0)
        
        self._sequencer_nrst = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["sequencer_nrst"]
        PSGPIO.sysfs_export(self._sequencer_nrst)
        PSGPIO.sysfs_set_direction(self._sequencer_nrst, "out")
        PSGPIO.sysfs_write(self._sequencer_nrst, 0)

        self._ddr4_c0_sys_rst_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["ddr4_c0_sys_rst"]           
        PSGPIO.sysfs_export(self._ddr4_c0_sys_rst_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c0_sys_rst_gpio, "out")
        PSGPIO.sysfs_write(self._ddr4_c0_sys_rst_gpio, 0)

        self._ddr4_c1_sys_rst_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["ddr4_c1_sys_rst"]            
        PSGPIO.sysfs_export(self._ddr4_c1_sys_rst_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c1_sys_rst_gpio, "out")
        PSGPIO.sysfs_write(self._ddr4_c1_sys_rst_gpio, 0)

        self._ddr4_c0_cal_cplt_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["ddr4_c0_cal_cplt"]           
        PSGPIO.sysfs_export(self._ddr4_c0_cal_cplt_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c0_cal_cplt_gpio, "in")

        self._ddr4_c1_cal_cplt_gpio = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["ddr4_c1_cal_cplt"]           
        PSGPIO.sysfs_export(self._ddr4_c1_cal_cplt_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c1_cal_cplt_gpio, "in")

        self._clk_wiz_locked = self._firmware["ps_gpio"]["sysfs_offset"] + self._firmware["ps_gpio"]["clk_wiz_locked"]           
        PSGPIO.sysfs_export(self._clk_wiz_locked)
        PSGPIO.sysfs_set_direction(self._clk_wiz_locked, "in")
        
        self._sequencer_done = self._firmware["ps_gpio"]["sysfs_offset"] + 64           
        PSGPIO.sysfs_export(self._sequencer_done)
        PSGPIO.sysfs_set_direction(self._sequencer_done, "in")
        
    def detach(self):
        """
        Unmaps all system memory.
        """

        for m in self._mem_maps:
            m.close()
            
            
    # ---------------- COMPILATION FUNCTIONS ---------------------- #
    
    def sequencer(self):
        """
        Create and store a new sequencer object associated with this system,
        if a sequencer is not already active (in which case, that one is 
        returned).
        """

        if self._active_sequencer is not None:
            return self._active_sequencer
        
        return self._sequencer_type()
    
    def sequence(self, func):
        """
        Compiles a Python functiond as a sequence for the Acadia sequencer. 
        The wrapped function should accept an instance of :class:`Acadia` as
        its sole argument.
        
        :param func: Function to be compiled as a Sequencer sequence.
        :type func: callable with one argument of type :class:`Sequencer`
        :return: A :class:`Sequencer` object containing the compiled sequence
        :rtype: :class:`Sequencer`
        """

        # Get a new sequence resource
        s = self.sequencer()
        
        # Drive the sequencer done pin low
        s.bus_write(address=self._firmware.sequencer_bus_decoder["ps_gpio5"].address(), data=0)
        
        # Store this particular Sequencer instance as an instance member of the 
        # Acadia object so that helper functions of the Acadia object know to 
        # use it
        self._active_sequencer = s
        
        # Call the function to populate the sequencer object and compile it
        with s:
            func(self)
            
        self._active_sequencer = None

        s.nop()
        s.bus_write(address=self._firmware.sequencer_bus_decoder["ps_gpio5"].address(), data=1)
        s.halt()
        
        # Because the sequence resource object was created before we knew its 
        # size and because we know that the size won't change from this point,
        # we can update the size of the instance and the allocation index of
        # the sequence resource
        s.size = s.Instruction.usage()
        
        return s
                        
    # -------------- CLOCKING AND SYNCHRONIZATION ROUTINES ----------- #
    
    def align_tile_latencies(self):
        """
        Align the latencies of all tiles by measuring the latency through
        all interface FIFOs. Delays are then applied so that the total latency
        of all tiles is equal to that of the slowest. This method uses the
        RFDC Multi-Tile Synchronization (MTS) routines.
        """

        # Initialize MTS data structures
        Channel.MTS_init()

        # Enable continuous SYSREF clock
        self.pulse_sysref()

        # Carry out the synchronization
        result = Channel.MTS_sync()

        # Turn off SYSREF
        self.pulse_sysref(0)

        return result
    
    def align_ncos(self, **kwargs):
        """
        Simultaneously reset the internal phase of multiple NCOs.
        By default, all NCOs are reset; to exclude an NCO from this process,
        provide a keyword argument ``DAC<x>=False`` or ``ADC<x>=False``, where
        ``<x>`` is the ADC or DAC number to exclude from the update. Note that
        all included channels must have the same interface frequency. 
        """

        raise NotImplemented
    
    @Synchronizer.synchronized(RFDCSynchronizer.NCO_FREQUENCY, "tile_synchronizer")
    def update_nco_frequency(self, channel, frequency):
        """
        Configure some or all NCO settings. The three 16-bit registers for
        the frequency tuning word may be individually updated, allowing
        for lower latency when less precise changes are acceptable.

        :param frequency: Frequency in Hz
        :type frequency: float
        """     
        
        frequency_word = channel.frequency_to_nco_tuning_word(frequency)
        
        proc = Processor.active_processor()
        if proc is None:
            channel.update_nco_frequency_registers(frequency_word)
                
        elif isinstance(proc, Sequencer):    
            frequency_base_reg = self._firmware.rfdc_rts_regs.address().value() + channel.num*2
            
            if not channel.is_dac:
                frequency_base_reg += 16*2 
            proc.bus_write(address=frequency_base_reg, 
                            data=(frequency_word >> 16) & 0xFFFFFFFF,
                            comment="Write NCO frequency high bits")
            proc.bus_write(address=frequency_base_reg+1, 
                            data=frequency_word & 0xFFFF,
                            comment="Write NCO frequency low bits")
        
        else:
            raise TypeError("NCO frequency can only be set in `Sequencer` contexts.")
    
    @Synchronizer.synchronized(RFDCSynchronizer.NCO_PHASE, "tile_synchronizer")
    def update_nco_phase(self, channel, phase, low=True, high=True):
        """
        Set the NCO phase offset to the given word.

        :param phase: Phase tuning word
        :type phase: int
        :param low: If ``True``, the lower 16 bits will be set.
        :type low: bool, optional
        :param high: If ``True``, the upper 2 bits will be set.
        :type high: bool, optional
        """
        phase_word = int(round((2**18)*phase/(2*np.pi)))
        proc = Processor.active_processor()
        if proc is None:
            channel.update_phase_registers(phase_word)
                
        elif isinstance(proc, Sequencer):
            phase_reg = self._firmware.rfdc_rts_regs.address().value() + 0x40 + channel.num
            
            if not channel.is_dac:
                phase_reg += 16
                
            proc.bus_write(address=phase_reg, 
                           data=phase_word & 0x0003FFFF,
                           comment=f"Write to NCO phase register for {channel}")
            
        else:
            raise TypeError("NCO phase can only be set in `Sequencer` contexts.")

    @Synchronizer.synchronized(RFDCSynchronizer.NCO_PHASE_RESET, "tile_synchronizer")
    def reset_nco_phase(self, channel):
        """
        Reset the value of the NCO phase accumulator.
        """

        proc = Processor.active_processor()
        if proc is None:
            Channel.RFDC_call_checked("ResetNCOPhase",
                           channel.converter_type(), channel.tile, channel.block)
                
        elif isinstance(proc, Sequencer):
            # Do nothing, the synchronizer will set the bit in the register
            pass
            
        else:
            raise TypeError("NCO accumulator phase can only be reset in"
                            " `PythonProcessor` or `Sequencer` contexts.")
    
    def configure_clocks(self, reference="internal"):
        """
        Configures the system clocks. Note that the clocking system will be
        reset and phase relationships among clocks may be reset. Additionally,
        clock dividers and SYSREF divider are synchronized as per the
        requirements for JESD204B (procedure adapted from TI datasheet for
        LMK04828).
        """           

        # Reset chip and load a default config
        RFClk.LMK.reset()
        RFClk.LMK.set_config()

        # Set reference source
        RFClk.LMK.set_input(0 if reference == "external" else 1)

        # Configure manual SYNC
        RFClk.LMK.set_sync_polarity(False)
        RFClk.LMK.set_sync_mode(1)
        RFClk.LMK.set_sysref_mux(0)

        # Set DCLK output dividers to 250 MHz and prepare for SYNC
        for output in [RFClk.LMK.DCLK_PL, 
                       RFClk.LMK.DCLK_RFDC_DAC, 
                       RFClk.LMK.DCLK_RFDC_ADC,
                       RFClk.LMK.SDCLK_RFDC-1]:
            # Set all output multiplexers to the input for the divider
            # with duty cycle correction and half-step
            RFClk.LMK.set_output_mux(output, 1)
            RFClk.LMK.set_output_divider(output, 12)
        
            # Power up parts of the output chain
            RFClk.LMK.set_output_powerdown_state(output,
                                        disable_output=False, 
                                        disable_digital_delay=False, 
                                        disable_glitchless_halfstep=True,
                                        disable_analog_delay_glitchless=True,
                                        disable_analog_delay=True,
                                        disable_sdclk=False)
            
            # Allow the output to be synchronized
            RFClk.LMK.set_output_divider_synchronization_disable(output, False)
            
        # Enable SYNC
        RFClk.LMK.set_sync_enabled(True)

        # Set SYSREF clk to 10 MHz and power up
        RFClk.LMK.set_sysref_divider(300)
        RFClk.LMK.set_sysref_power_state(False)
        RFClk.LMK.set_sysref_digital_delay_power_state(False)
        RFClk.LMK.set_sysref_pulser_power_state(False)
        RFClk.LMK.set_sysref_global_power_state(False)

        # Configure SYSREF to allow synchronization
        RFClk.LMK.set_sysref_divider_synchronization_disable(False)

        # Configure the pulser to generate one pulse. Note: TI procedure uses
        # 2 pulses but this doesn't seem necessary, and if it's really needed
        # then that would mean you're not certain which edge actually performs
        # the reset - I guess we'll see if this ends up being necessary...
        RFClk.LMK.set_sysref_pulse_count(1)

        # Clear the SYSREF digital delay shift register
        RFClk.LMK.set_sysref_clr(True)

        # Set all the digital delay counts (DCLKoutx_DDLY_CNTH/L, SYSREF_DDLY,
        # SDCLKoutx_DDLY)
        # We won't change the default settings, any adjustment to the default
        # delays should be done here

        # Perform the sync by toggling SYNC_POL
        RFClk.LMK.set_sync_polarity(True)
        time.sleep(0.001)
        RFClk.LMK.set_sync_polarity(False)

        # Now that everything is sync'ed, disable synchronization on the 
        # dividers so that future SYNC pulses don't reset them
        RFClk.LMK.set_sysref_divider_synchronization_disable(True)
        for output in [RFClk.LMK.DCLK_PL, 
                       RFClk.LMK.DCLK_RFDC_DAC, 
                       RFClk.LMK.DCLK_RFDC_ADC]:
            RFClk.LMK.set_output_divider_synchronization_disable(output, True)

        # Release the reset for the SYSREF digital delay
        RFClk.LMK.set_sysref_clr(False)

        # Configure SYSREF in pulser mode
        # SYNC_MODE=3: SYNC generated by pulser when writing to the SYSREF
        #              pulse count register
        RFClk.LMK.set_sync_mode(3) 

        # Configure the SYSREF_MUX so that the SYSREF pulser drives the 
        # SYSREF/SYNC path 
        RFClk.LMK.set_sysref_mux(2) 

    def pulse_sysref(self, count=None):
        """
        Pulse the SYSREF of the LMK04828 a given number of times. 
        Valid values for ``count`` are:

        - ``None``: SYSREF_MUX is set so that the SYSREF/SYNC path is driven
            continuously by the SYSREF clock
        - ``0``: SYSREF_MUX is set so that the SYSREF/SYNC path is driven by the
            pulser.
        - ``1, 2, 4, 8``: SYSREF_PULSE_CNT is programmed to produce the given 
            number of pulses
        """

        if count is None:
            RFClk.LMK.set_sysref_mux(3)
        elif count == 0:
            RFClk.LMK.set_sysref_mux(2)
        elif count == 1 or count == 2 or count == 4 or count == 8:
            RFClk.LMK.set_sysref_pulse_count(count)
        else:
            raise ValueError(f"Invalid SYSREF pulse setting {count}.")
        
    def get_clock_status(self, clkin=10e6):
        """
        :param clkin: Frequency of clock provided to CLK104 module in Hz
        :type clkin: float
        :return: A dictionary containing various clocking system parameters.
        """

        d = {}
        d["clock_source"] = "external" if RFClk.LMK.get_input() == 0 else "internal"
        d["PLL1_N"] = RFClk.LMK.get_PLL1_N()
        d["input_R"] = RFClk.LMK.get_input_R(RFClk.LMK.get_input())
        d["PLL2_P"] = RFClk.LMK.get_PLL2_P()
        d["PLL2_N"] = RFClk.LMK.get_PLL2_N()
        d["PLL2_R"] = RFClk.LMK.get_PLL2_R()
        d["PLL1_out_frequency"] = clkin * d["PLL1_N"] / d["input_R"]
        d["PLL2_out_frequency"] = d["PLL1_out_frequency"] * d["PLL2_P"] * d["PLL2_N"] / d["PLL2_R"]

        # SYSREF
        d["SYSREF_power_state"] = RFClk.LMK.get_sysref_power_state()
        d["SYSREF_digital_delay_power_state"] = RFClk.LMK.get_sysref_digital_delay_power_state()
        d["SYSREF_global_power_state"] = RFClk.LMK.get_sysref_global_power_state()
        d["SYSREF_pulser_power_state"] = RFClk.LMK.get_sysref_pulser_power_state()
        d["SYSREF_divider"] = RFClk.LMK.get_sysref_divider()
        d["SYSREF_divider_sync_disabled"] = RFClk.LMK.get_sysref_divider_synchronization_disable()
        d["SYSREF_digital_delay"] = RFClk.LMK.get_sysref_digital_delay()
        d["SYSREF_mux"] = RFClk.LMK.get_sysref_mux()
        d["SYSREF_clr"] = RFClk.LMK.get_sysref_clr()
        
        # SYNC 
        d["SYNC_MODE"] = RFClk.LMK.get_sync_mode()
        d["SYNC_POL"] = RFClk.LMK.get_sync_polarity()
        d["SYNC_EN"] = RFClk.LMK.get_sync_enabled()

        # DCLKout information
        for channel,name in [(RFClk.LMK.DCLK_PL,"PL"), 
                             (RFClk.LMK.DCLK_RFDC_ADC, "ADC_ref"), 
                             (RFClk.LMK.DCLK_RFDC_DAC, "DAC_ref"), 
                             (RFClk.LMK.DCLK_LMX_ADC, "ADC_LMX"), 
                             (RFClk.LMK.DCLK_LMX_DAC, "DAC_LMX"),
                             (RFClk.LMK.SDCLK_RFDC-1, "RFDC")]:
            # Settings shared by the channel and its SDClk
            pd = RFClk.LMK.get_output_powerdown_state(channel)
            d[f"{name}_digital_delay_powerdown"] = bool(pd & (1 << 7))
            d[f"{name}_digital_glitchless_halfstep_powerdown"] = bool(pd & (1 << 6))
            d[f"{name}_analog_glitchless_halfstep_powerdown"] = bool(pd & (1 << 5))
            d[f"{name}_analog_delay_powerdown"] = bool(pd & (1 << 4))
            d[f"{name}_IDL"] = RFClk.LMK.get_input_drive_level_increased(channel)
            d[f"{name}_ODL"] = RFClk.LMK.get_output_drive_level_increased(channel)

            # DCLK channel settings
            d[f"{name}_dclkout_powerdown"] = bool(pd & (1 << 3))
            d[f"{name}_dclk_divider"] = RFClk.LMK.get_output_divider(channel)
            d[f"{name}_dclk_frequency"] = d["PLL2_out_frequency"] / d[f"{name}_dclk_divider"]
            drive = RFClk.LMK.get_drive(channel)
            d[f"{name}_dclk_drive"] = f"{drive} ({RFClk.LMK.drive_to_string(drive)})"
            d[f"{name}_dclk_mux"] = RFClk.LMK.get_output_mux(channel)
            d[f"{name}_dclk_analog_delay"] = RFClk.LMK.get_output_analog_delay(channel)
            d[f"{name}_dclk_digital_delay"] = RFClk.LMK.get_output_digital_delay(channel)
            d[f"{name}_dclk_sync_disabled"] = RFClk.LMK.get_output_divider_synchronization_disable(channel)
            
            # SDCLK channel settings
            d[f"{name}_sdclkout_powerdown"] = bool(pd & (1 << 0))
            d[f"{name}_sdclkout_analog_delay_enabled"] = RFClk.LMK.get_sdclk_analog_delay_enabled(channel+1)
            drive = RFClk.LMK.get_drive(channel+1)
            d[f"{name}_sdclk_drive"] = f"{drive} ({RFClk.LMK.drive_to_string(drive)})"
            d[f"{name}_sdclk_mux"] = RFClk.LMK.get_sdclk_mux(channel+1)
            d[f"{name}_sdclk_analog_delay"] = RFClk.LMK.get_sdclk_analog_delay(channel+1)
            d[f"{name}_sdclk_digital_delay"] = RFClk.LMK.get_sdclk_digital_delay(channel+1)
            
        d["clk_wiz_locked"] = PSGPIO.sysfs_read(self._clk_wiz_locked)
        
        rfdc_status = Channel.RFDC_status()
        for tile,status in rfdc_status.items():
            d[f"{tile}_PLL_locked"] = status["PLL_locked"]
            
        for channel in self._DAC_channels + self._ADC_channels:
            s = channel.status()
            d[f"{channel.name()}_clocks_enabled"] = s["all_required_clocks_enabled"]
            d[f"{channel.name()}_sampling_frequency"] = s["sampling_frequency"]
            
        d["clk_distribution"] = Channel.get_clk_distribution()
            
        return d
    
    # -------------- CHANNEL HELPERS ----------- #

    def DAC(self, num):
        """
        :return: a :class:`Channel` representing a DAC.
        :rtype: :class:`Channel`
        """

        return self._DAC_channels[num]

    def ADC(self, num):
        """
        :return: a :class:`Channel` representing an ADC.
        :rtype: :class:`Channel`
        """

        return self._ADC_channels[num]
    
    def get_dma(self, channel):
        """
        Get the DMA for a given channel.
        
        :param channel: Channel to get the DMA for
        :type channel: :class:`Channel`
        """
        
        return self._dac_dmas[channel.num] if channel.is_dac else self._adc_dmas[channel.num]
    
    # -------------- ABSTRACTIONS FOR JOINT PS-PL ROUTINES ----------- #
    
    @requires_sequencer
    def channel_dma_stream(self, channel, length, word_address, 
                           decimate=0, fixed=False, blank=False):
        """
        Stream data with a channel DMA.

        :param channel: Physical channel to capture from.
        :type channel: :class:`Channel` or int
        :param length: The length of the descriptor in cycles
        :type length: int
        :param word_address: The address of the DMA descriptor
        :type word_address: int
        :param decimate: Decimation amount
        :type decimate: int, optional
        :param fixed: If ``True``, the DMA output address will not increment
        :type fixed: bool
        :param blank: If ``True``, the output of the DMA never becomes valid
            but the DMA runs as normal otherwise
        :return: The descriptor requested for the DMA as returned by the 
            `request_descriptor` instruction for :class:`DMA`.
        :rtype: :class:`ProcessorInstruction`
        """

        if not isinstance(channel, Channel):
            raise TypeError(f"Channel must be of type `Channel`;"
                            f" received {channel}.")
            
        # When we request the descriptor, we need to get the address aligned to
        # 128 bits. We need the word address
        dma = self._dac_dmas[channel.num] if channel.is_dac else self._adc_dmas[channel.num]
        
        descriptor = dma.request_descriptor(
            word_address, 
            length,
            decimate=decimate,
            fixed=fixed,
            blank=blank)
        
        dev_name = f'{"dac" if channel.is_dac else "adc"}{channel.num}_dma'
        device = self._firmware.sequencer_bus_decoder[dev_name]
        
        self._active_sequencer.bus_write(
            address=device.address().value(),
            data=descriptor, 
            comment=f"Add descriptor with parameters {descriptor.kwargs} to"
                    f" FIFO for {'DAC' if channel.is_dac else 'ADC'}{channel.num}")
        
        return descriptor
        
    @requires_sequencer
    def generate(self, signal):
        """
        Stream a signal out of a DAC. If `signal` does not have any attribute
        `_descriptors`, this attribute will be populated with a list of 
        `Symbol` instances. Each `Symbol` will be assigned by the 
        `ChannelSynchronizer` when commands are requested for the DMA, and it
        will be assigned with the return value of :meth:`channel_dma_stream`.
        
        :param channel: Channel to stream
        :type channel: :class:`Channel`
        :param signal: Signal to stream
        :type signal: :class:`self.DACArray` or any type implementing 
            `dma_parameters()` returning a list of `dict`. Each `dict` will 
            result in a sequential call to `channel_dma_stream` whose arguments
            are the key/value pairs in the `dict`. 
        """
        dma_parameters = None
        for i in range(self._firmware.NUM_DACS):
            if isinstance(signal, self.DACArray[i]):
                dma_parameters = [{
                    "channel": self.DAC(i),
                    "length": signal.byte_length() // self.DAC(i).interface_width_bytes,
                    "word_address": signal.word_address()
                }]
                break
            
        if dma_parameters is None and hasattr(signal, "dma_parameters"):
            dma_parameters = signal.dma_parameters()
            
        if dma_parameters is None:
            raise ValueError("Unable to identify DMA parameters"
                             " for `generate`")
        
        # Notify the synchronizer, which will add the DMA command for us
        # Every call to `add` will return a Symbol. When the synchronizer
        # exits, that symbol will get populated with the return value of
        # `channel_dma_stream`. This is a `ProcessorInstruction` representing
        # the descriptor for the DMA
        descriptors = []
        for params in dma_parameters:
            r = self.channel_synchronizer.add({
                "function": DMASynchronizer.DMA, 
                "self": self, 
                "args": (), 
                "kwargs": params})
            descriptors.append(r)
        
        if not hasattr(signal, "_descriptors"):
            signal._descriptors = descriptors
        
    @requires_sequencer
    def capture(self, configuration, dst):
        """
        Capture a waveform on an ADC.
        
        :param configuration:
        """
        # We only need to command the datamover and notify the synchronizer,
        # which will then add the DMA command for us
        self._sequencer_command_datamover(f"module{configuration._input_switch_slave}_s2mm_datamover", 
                                   dst.byte_address(),
                                   dst.byte_length())
        
        self.channel_synchronizer.add({
            "function": DMASynchronizer.DMA, 
            "self": self, 
            "args": (), 
            "kwargs": {
                "channel": configuration.input_source,
                "length": dst.byte_length() // configuration.input_source.interface_width_bytes,
                "word_address": 0
            }})
        
    @requires_sequencer
    def generate_blank(self, channel, length):
        """
        Generate a blank signal on a channel for a given length of time. This
        can be used to insert delays between DMA commands without sequencer 
        intervention.
        
        :param channel: Channel on which to insert a blank command
        :type channel: :class:`Channel`
        :param length: Delay length in seconds
        :type length: float
        """
        length_cycles = self._firmware["clocks"]["generated_clocks"]["seq_clk"]*length
        
        if round(length_cycles,5) != round(length_cycles):
            raise ValueError("DMA blanking length does not result in an"
                             " integer number of cycles (received length"
                             f" {length*1e9} ns = {length_cycles} cycles)") 
        
        self.channel_synchronizer.add({
            "function": DMASynchronizer.DMA, 
            "self": self, 
            "args": (), 
            "kwargs": {
                "channel": channel,
                "length": round(length_cycles),
                "word_address": 0,
                "blank": True
            }})
        
    @DMASynchronizer.synchronized(None, "channel_synchronizer")
    def barrier(self):
        """
        Insert a synchronization barrier. When a barrier is inserted in a 
        synchronization block, the maximum length of all actions before the
        barrier defines the time at which the barrier is inserted. Delays are
        then inserted for every channel that has an action after the barrier
        so that they start at the time of the barrier.
        """
        # Nothing actually needs to be done here, this just notifies the synchronizer
        pass
        
    @requires_sequencer
    def memcpy(self, configuration, src, dst):
        """
        Carry out a memory transfer using the stream processing path.
        
        :param configuration: Stream configuration used for carrying out the transfer
        :type configuration: :class:`StreamConfiguration`
        :param src: Data source
        :type src: PLDDR0Array, PLDDR1Array, CacheArray, DACArray, CMACCKernelArray
        :param dst: Data destination
        :type dst: PLDDR0Array, PLDDR1Array, CacheArray, DACArray, CMACCKernelArray
        """
        
        # TODO: Add some checks to make sure that data from src can get to dst
        # using the provided configuration
        
        self._sequencer_command_datamover(f"module{configuration._input_switch_slave}_s2mm_datamover", 
                                   dst.byte_address(),
                                   src.byte_length())
        self._sequencer_command_datamover(f"input{configuration._input_switch_master}_datamover", 
                                   src.byte_address(),
                                   src.byte_length())

    # -------------- CONVENIENCE FUNCTIONS FOR THE SEQUENCER ----------- #

    def get_bus_latency(self, port):
        """
        Get the latency for a port on the sequencer's bus, taking into account
        any pipelining configured in the firmware.

        :param port: Bus port name. Must either be a key in the 
            ``SEQUENCER_BUS``  section of the firmware configuration, or
            ``cache``\.
        :type port: str
        """
        # One cycle to load the bus registers in the sequencer
        latency = 1 

        if self._firmware["sequencer_bus"]["decoder_pipeline_miso"]:
            latency += 1

        # Datamover controllers have a read latency of 1 because its MISO is driven
        # in a synchronous process
        if "datamover_controller" in port:
            latency += 1
            
        elif "dma" in port:
            # adc<x>_dma or dac<x>_dma
            port_idx = int(port[3:port.index("_")])
            port_idx += 16 if port.startswith("adc") else 0
            latency += 1 if self._firmware["sequencer_bus"]["dma_pipeline"][port_idx] else 0

        elif port == "cache":
            # One additional cycle minimum because the memory has a read latency of 1
            # even before any pipelining because it's a synchronous memory
            latency += 1 
            latency += self._firmware["sequencer_cache_memory"]["bus_port_input_pipeline"]
            latency += self._firmware["sequencer_cache_memory"]["bus_port_output_pipeline"]
        elif "ps_gpio" in port:
            latency += self._firmware[port]["bus_pipeline"]
        elif self._firmware["sequencer_bus"][port]["bus_pipeline"]:
            latency += 1

        return latency
        
    @requires_sequencer
    def dma_fifo_occupancy(self, channel):
        """
        Get the number of commands queued for the DMA of the given channel.

        :param channel: Channel to check
        :type channel: :class:`Channel`
        """

        dev_name = f'{"dac" if channel.is_dac else "adc"}{channel.num}_dma'
        device = self._firmware.sequencer_bus_decoder[dev_name]

        bus_op = self._active_sequencer.bus_read(device.address().value(), 
                                                 latency=self.get_bus_latency(dev_name))
        # Mask away the running bit
        return bus_op & 0b1111 != 0
    
    @requires_sequencer
    def channels_running(self, *channels):
        """
        Create a condition that will determine whether the DMAs
        driving the given :class:`Channel`\s are running.

        :param channels: Channel(s) to check
        :type channels: list of :class:`Channel`
        """

        mask = 0
        for channel in channels:
            mask |= self.get_dma(channel).mask
        
        bus_address = self._firmware.dma_running.address().value()

        return self._active_sequencer.bus_read(bus_address, 
                                               latency=self.get_bus_latency("dma_running_dataport"))

    @requires_sequencer
    def stream_count(self, configuration):
        """
        Retrieve the number of status words produced for the DataMover in the 
        provided stream configuration.

        :param configuration: Configuration to check
        :type configuration: :class:`StreamConfiguration`
        """
        datamover_name = f"module{configuration._input_switch_slave}_s2mm_datamover_controller"
        address = self._firmware.sequencer_bus_decoder[datamover_name] + 1
        return self._active_sequencer.bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status count for {datamover_name}",
                                        latency=self.get_bus_latency(datamover_name))
    
    @requires_sequencer
    def stream_total_bytes_transferred(self, configuration):
        """
        Retrieve the number of status words produced for the DataMover in the 
        provided stream configuration.

        :param configuration: Configuration to check
        :type configuration: :class:`StreamConfiguration`
        """
        datamover_name = f"module{configuration._input_switch_slave}_s2mm_datamover_controller"
        address = self._firmware.sequencer_bus_decoder[datamover_name] + 2
        return self._active_sequencer.bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status count for {datamover_name}",
                                        latency=self.get_bus_latency(datamover_name))  

    @requires_sequencer     
    def stream_reset(self, configuration):
        """
        Resets the stream datamover controllers and modules.
        
        :param configuration: Configuration to reset
        :type configuration: :class:`StreamConfiguration`
        """

        module = configuration._input_switch_slave
        address = self._firmware.sequencer_bus_decoder[f"module{module}_s2mm_datamover_controller"].address().value() + 3
        self._active_sequencer.bus_write(address=address, data=0xFFFFFFFF)
            
    @requires_sequencer
    def dma_trigger(self, *channels):
        """
        Trigger the DMAs associated with the provided channels.

        :param channels: List of channels
        """
        mask = 0
        for channel in channels:
            mask |= self.get_dma(channel).mask

        dma_trigger_device = self._firmware.sequencer_bus_decoder["dma_trigger"]
        self._active_sequencer.bus_write(address=dma_trigger_device.address().value(),
                                 data=mask,
                                 comment="DMA trigger")
        
    @requires_sequencer
    def dma_block(self, *channels):
        """
        Wait until the DMAs for the specified channels are not running.
        """
        mask = 0
        for channel in channels:
            mask |= self.get_dma(channel).mask

        dma_running_device = self._firmware.sequencer_bus_decoder["dma_running"]
        dma_running = self._active_sequencer.bus_read(address=dma_running_device.address().value(),
                                                      latency=self.get_bus_latency("dma_running_dataport"))
        with self._active_sequencer.repeat_until(dma_running & mask == 0):
            pass

    # -------------- RUNTIME UTILITIES ----------- #
    
    def run(self, assemble=True, block=True):
        """
        Assemble, load, and run a sequence on Acadia hardware.
        Significant speedups may be achieved if reassembly is not
        required.
        
        :param block: If `True`, execution will block until the sequencer
            signals completion.
        """
        if assemble:
            self.load(*self.assemble())
        self.sequencer_reset()
        self.sequencer_run()
        
        if block:
            while not self.sequencer_done():
                pass
        
    def sequencer_done(self):
        """
        Determine whether the sequencer has completed.
        """
        return PSGPIO.sysfs_read(self._sequencer_done)

    def configure_stream(self, stream):
        """
        Configure the stream processing path according to a stream description.
        
        :param stream: Stream configuration to apply
        :type stream: :class:`StreamConfiguration`
        """
        self._stream_processing_path_input_switch.connect(stream._input_switch_slave, 
                                                          stream._input_switch_master)
        
        if stream._adc_switch_master is not None:
            self._ADC_input_switch.connect(stream._adc_switch_slave, 
                                           stream._adc_switch_master)
        
    def compile(self, sequence, overwrite=False):
        """
        Compiles the programs for all internally-stored :class:`Processor` 
        objects.
        """
        self.sequence(sequence)
        
        for s in self._sequencer_type.instances:
            s.compile_all(overwrite)
        for dma in self._dac_dmas:
            dma.compile_all(overwrite)
        for dma in self._adc_dmas:
            dma.compile_all(overwrite)

    def assemble(self):
        """
        Assembles instruction memory for the sequencer and all DMAs.
        """
        
        num_sequencer_instructions = sum([len(s._compiled_program) for s in self._sequencer_type.instances])
        logging.debug(f"Assembling sequencer program with {num_sequencer_instructions} instructions")
        
        sequencer_program = np.empty((num_sequencer_instructions, 16), dtype=np.uint8)
        
        idx = 0
        for s in self._sequencer_type.instances:
            for instr in s._compiled_program:
                sequencer_program[idx,:] = np.frombuffer(instr.assemble().to_bytes(16, "little"), dtype=np.uint8)
                idx += 1

        dac_dma_programs = []
        for i,dma in enumerate(self._dac_dmas):
            logging.debug(f"Assembling DAC{i} DMA program with length {len(dma._compiled_program)}")
            dma_program = np.empty((len(dma._compiled_program), 8), dtype=np.uint8)
            for idx,instr in enumerate(dma._compiled_program):
                dma_program[idx,:] = np.frombuffer(instr.assemble().to_bytes(8, "little"), dtype=np.uint8)
            dac_dma_programs.append(dma_program)
            
        adc_dma_programs = []
        for dma in self._adc_dmas:
            logging.debug(f"Assembling ADC{i} DMA program with length {len(dma._compiled_program)}")
            dma_program = np.empty((len(dma._compiled_program), 8), dtype=np.uint8)
            for idx,instr in enumerate(dma._compiled_program):
                dma_program[idx,:] = np.frombuffer(instr.assemble().to_bytes(8, "little"), dtype=np.uint8)  
            adc_dma_programs.append(dma_program)
            
        return sequencer_program, dac_dma_programs, adc_dma_programs
    
    def load(self, sequencer_program=None, dac_dma_programs=None, adc_dma_programs=None):
        """
        Loads assembled data into memory.
        """
        if sequencer_program is not None:
            program_reshaped = memoryview(sequencer_program.reshape((-1,)))
            memoryview(self._sequencer_instruction_memory)[:len(program_reshaped)] = program_reshaped
            
        if dac_dma_programs is not None:
            for idx,program in enumerate(dac_dma_programs):
                if len(program) > 0:
                    logging.debug(f"Loading program of length {len(program)} into DAC{idx} descriptor memory")
                    program_reshaped = memoryview(program.reshape((-1,)))
                    memoryview(self._dac_dma_descriptor_memory[idx])[:len(program_reshaped)] = program_reshaped
                
        if adc_dma_programs is not None:
            for idx,program in enumerate(adc_dma_programs):
                if len(program) > 0:
                    logging.debug(f"Loading program of length {len(program)} into ADC{idx} descriptor memory")
                    program_reshaped = memoryview(program.reshape((-1,)))
                    memoryview(self._adc_dma_descriptor_memory[idx])[:len(program_reshaped)] = program_reshaped
        
                        
    def assemble_simulation(self):
        """
        Identical to :meth:`assemble`, but creates a string for loading memory
        in Verilog testbenches connected to the Zynq Ultrascale AXI VIP.
        """

        sim_string = ""
        for s in self._sequencer_type.instances:
            for idx_instr,instr in enumerate(s._compiled_program):
                assembled = instr.assemble()
                address = (s._resource_id + idx_instr)*16
                sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{address + self._firmware['sequencer_instruction_memory']['address']: X}, 16, 128'h{assembled:032X}, resp);\n"
    
        for i,dma in enumerate(self._dac_dmas):
            for idx_instr,instr in enumerate(dma._compiled_program):
                assembled = instr.assemble()
                sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{self._firmware['dac_dma_descriptor_memory']['address'] + i*(self._firmware['dac_dma_descriptor_memory']['size_bits']//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
            
        for i,dma in enumerate(self._adc_dmas):
            for idx_instr,instr in enumerate(dma._compiled_program):
                assembled = instr.assemble()
                sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{self._firmware['adc_dma_descriptor_memory']['address'] + i*(self._firmware['adc_dma_descriptor_memory']['size_bits']//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"      
            
        return sim_string

    def sequencer_pprint(self):
        """
        :return: a "pretty" representation of the programs compiled
            for the sequencer
        :rtype: str
        """

        idx = 0
        for idx_seq,s in enumerate(self._sequencer_type.instances):
            print(f"---- Program {idx_seq} ----")
            for instr in s._compiled_program:
                print(f"{idx:04X}: {instr.pprint()}")
                idx += 1

    def sequencer_run(self):
        """
        Runs the sequencer by driving its run pin high. 
        """

        PSGPIO.sysfs_write(self._sequencer_nrst, 1)
        PSGPIO.sysfs_write(self._sequencer_gpio, 1)

    def sequencer_halt(self):
        """
        Halts the sequencer by driving its run pin low.
        """

        PSGPIO.sysfs_write(self._sequencer_gpio, 0)
        
    def sequencer_reset(self):
        """
        Resets the sequencer.
        """

        PSGPIO.sysfs_write(self._sequencer_nrst, 0)

    # -------------- SYSTEM UTILITIES ----------- #
            
    def reset_plddr0(self):
        PSGPIO.sysfs_write(self._ddr4_c0_sys_rst_gpio, 1)
        time.sleep(0.001)
        PSGPIO.sysfs_write(self._ddr4_c0_sys_rst_gpio, 0)

    def reset_plddr1(self):
        PSGPIO.sysfs_write(self._ddr4_c1_sys_rst_gpio, 1)
        time.sleep(0.001)
        PSGPIO.sysfs_write(self._ddr4_c1_sys_rst_gpio, 0)

    def is_plddr0_cal_complete(self):
        return PSGPIO.sysfs_read(self._ddr4_c0_cal_cplt_gpio)
    
    def is_plddr1_cal_complete(self):
        return PSGPIO.sysfs_read(self._ddr4_c1_cal_cplt_gpio)
        
    def reset_logic(self):
        """
        Resets the PL logic.
        """

        gpio = 338 + 3*26 + 95
        PSGPIO.sysfs_export(gpio)
        PSGPIO.sysfs_set_direction(gpio, "out")
        PSGPIO.sysfs_write(gpio, 0)
        PSGPIO.sysfs_write(gpio, 1)
        
    def gpio_set_direction(self, port, directions):
        """
        Set the GPIO directions for the signals in a given port.

        :param port: The port number (either 3 or 4).
        :type port: int
        :param directions: Each set bit configures the corresponding
            pin as an output.
        :type directions: int
        """

        proc = Processor.active_processor()
        if proc is None:
            self._psgpio_mem[(PSGPIO.PSGPIO3_DIR_PSREG >> 2) + port - 3] = directions
            self._psgpio_mem[(PSGPIO.PSGPIO3_DIR_PSREG >> 2) + port - 3 + 1] = directions
        else:
            raise TypeError(f"Unable to configure GPIO on processor {proc}.")
        
    def gpio_read(self, port):
        """
        Read the value of a 32-bit GPIO port. 

        :param port: The port number (either 3 or 4).
        :type port: int
        """

        if port not in [3,4]:
            raise ValueError(f"Invalid GPIO port {port}.")
        proc = Processor.active_processor()
        if proc is None:
            return self._psgpio_mem[(PSGPIO.PSGPIO3_IN_PSREG >> 2) + port - 3]
        elif isinstance(proc, Sequencer):
            addr = self._firmware.sequencer_bus_decoder[f"ps_gpio{port}"].address().value()
            return proc.bus_read(addr, latency=self.get_bus_latency(f"ps_gpio{port}"))
        else:
            raise TypeError(f"Unable to access GPIO on processor {proc}.")
        
    def gpio_write(self, port, data):
        """
        Write data to a 32-bit GPIO port. 

        :param port: The port number (either 3 or 4).
        :type port: int
        :param data: The value to write
        :type data: int or bytes
        """

        if port not in [3,4]:
            raise ValueError(f"Invalid GPIO port {port}.")
        proc = Processor.active_processor()
        if proc is None:
            self._psgpio_mem[(PSGPIO.PSGPIO3_OUT_PSREG >> 2) + port - 3] = data
        elif isinstance(proc, Sequencer):
            addr = self._firmware.sequencer_bus_decoder[f"ps_gpio{port}"].address().value()
            return proc.bus_write(address=addr, 
                                  data=data,
                                  comment=f"Write to GPIO port {port}")
        else:
            raise TypeError(f"Unable to access GPIO on processor {proc}.")
        
    
    # -------------- INTERNAL UTILITIES ----------- #
    
    def _create_dmas(self):
        self._dac_dmas = []
        bit_position = 0
        for i in range(self._firmware.NUM_DACS):
            dma = DMA()
            dma.mask = 1 << bit_position
            bit_position += 1
            self._dac_dmas.append(dma)
            
        self._adc_dmas = []
        for i in range(self._firmware.NUM_ADCS):
            dma = DMA()
            dma.mask = 1 << bit_position
            bit_position += 1
            self._adc_dmas.append(dma)
            
    def _create_cache(self):
        def _cache_getitem(cache_self, key):
            proc = Processor.active_processor()
            if proc is None:
                if not hasattr(cache_self, "memory"):
                    raise AttributeError(f"Attempted to get item from unattached memory.")
                return cache_self.memory[key]
            elif isinstance(proc, Sequencer):
                return proc.bus_read(cache_self.word_address() + key, 
                                     latency=self.get_bus_latency("cache"))
            return Operation("getitem", cache_self, key)
            
        def _cache_setitem(cache_self, key, value):
            proc = Processor.active_processor()
            if proc is None:
                if not hasattr(cache_self, "memory"):
                    raise AttributeError(f"Attempted to set item of unattached memory.")
                cache_self.memory[key] = value
            elif isinstance(proc, Sequencer):
                proc.bus_write(address=cache_self.word_address() + key,
                               data=value,
                               comment=f"Write to cache address {key}")
            else:
                raise TypeError(f"Unable to access cache on processor {proc}.")
        
        self.CacheArray = ManagedMemory("CacheArray", 
            (), 
            {"OPERATORS": [], 
             "__getitem__": _cache_getitem, 
             "__setitem__": _cache_setitem},
            base_word_address=self._firmware.sequencer_bus_decoder["cache"].address().value(),
            base_byte_address=self._firmware["sequencer_cache_memory"]["address"],
            word_width=32,
            memory_size=self._firmware["sequencer_cache_memory"]["size_bits"] // 8,
            default_getitem=False)
        
    def _create_dac_arrays(self):
        self.DACArray = [ManagedMemory(f"DAC{i}Array", (), {},
            base_word_address=0,
            base_byte_address=(self._firmware[f"dac_tile{i // 4}_sample_memory"]["address"] 
                               + (i % 4)*(self._firmware[f"dac_tile{i // 4}_sample_memory"]["size_bits"] // 8)),
            word_width=128,
            memory_size=self._firmware[f"dac_tile{i // 4}_sample_memory"]["size_bits"] // 8) for i in range(self._firmware.NUM_DACS)]
        
    def _create_cmacc_kernel_arrays(self):
        self.CMACCKernelArray = [ManagedMemory(f"CMACC{i}KernelArray", (), {},
            base_word_address=0,
            base_byte_address=(self._firmware["stream_processing_path"]["cmacc_kernel_memory_controller"]["base_address"] 
                               + i*(self._firmware._max_cmacc_memory * 32 // 8)),
            word_width=32,
            memory_size=self._firmware._max_cmacc_memory * 32 // 8) for i in range(self._firmware._num_cmaccs)]
        
    def _create_pl_ddr_arrays(self):
        self.PLDDR0Array = ManagedMemory(f"PLDDR0Array", (), {},
            base_word_address=self._firmware["memory"]["ddr4_c0"]["address"],
            base_byte_address=self._firmware["memory"]["ddr4_c0"]["address"],
            word_width=8,
            memory_size=self._firmware["memory"]["ddr4_c0"]["size_bits"] // 8)
        
        self.PLDDR1Array = ManagedMemory(f"PLDDR1Array", (), {},
            base_word_address=self._firmware["memory"]["ddr4_c1"]["address"],
            base_byte_address=self._firmware["memory"]["ddr4_c1"]["address"],
            word_width=8,
            memory_size=self._firmware["memory"]["ddr4_c1"]["size_bits"])
        
    def _create_ps_ddr_arrays(self):
        # PS DDR
        self.PSDDRArray = ManagedMemory(f"PSDDRArray", (), {},
            base_word_address=0x8_0000_0000,
            base_byte_address=0x8_0000_0000,
            word_width=8,
            memory_size=2**30)
        
    def _create_ocm_arrays(self):
        self.OCMArray = ManagedMemory(f"OCMArray", (), {},
            base_word_address=0xFFFC_0000,
            base_byte_address=0xFFFC_0000,
            word_width=8,
            memory_size=2**18)
        
    def _create_zdma(self):
        def zdma_postinit(zdma_self):
            zdma_self.fci_bus_address = self._firmware.sequencer_bus_decoder["zdma_controller"].address().value()
            zdma_self.channel = zdma_self._resource_id
            super(zdma_self).__post_init__()
        
        self._ZDMA = ManagedResource("ZDMAResource", 
                                         (ZDMA,), 
                                         {"__post_init__": zdma_postinit,
                                          "OPERATORS": []},
                                         allocation_limit=8)
        
    def _create_channels(self):
        # Create channel objects that abstract the channels of this board
        # so that when parameters are updated, everything that depends on
        # the channel receives the update
        self._DAC_channels = []
        self._ADC_channels = []
        for tile in range(4):
            for block in range(4):
                dac_channel = Channel(tile=tile, block=block, is_dac=True)
                dac_channel.memory_type = self.DACArray[tile*4 + block]
                dac_channel.analog_sample_frequency = self._firmware["rfdc"]["dac"]["tile_sample_rate_hz"][tile]
                dac_channel.interface_sample_frequency = (self._firmware["clocks"]["generated_clocks"][self._firmware["rfdc"]["dac"]["tile_axis_clocks"][tile]] 
                                                          * self._firmware["rfdc"]["dac"]["channel_interface_width"][tile*4 + block] // 32)
                dac_channel.interface_width_bytes = self._firmware["rfdc"]["dac"]["channel_interface_width"][tile*4 + block] // 8
                
                self._DAC_channels.append(dac_channel)
                
                adc_channel = Channel(tile=tile, block=block, is_dac=False)
                adc_channel.analog_sample_frequency = self._firmware["rfdc"]["adc"]["tile_sample_rate_hz"][tile]
                adc_channel.interface_sample_frequency = (self._firmware["clocks"]["generated_clocks"][self._firmware["rfdc"]["adc"]["tile_axis_clocks"][tile]] 
                                                          * self._firmware["rfdc"]["adc"]["channel_interface_width"][tile*4 + block] // 32)
                adc_channel.interface_width_bytes = self._firmware["rfdc"]["adc"]["channel_interface_width"][tile*4 + block] // 8
                
                self._ADC_channels.append(adc_channel)
                
    def _create_switches(self):
        self._stream_processing_path_input_switch = AXISSwitch()
        self._ADC_input_switch = AXISSwitch()
        
    def _attach_resource(self, resource_manager, default_dtype=np.uint8):
        """
        Maps the memory associated with a managed resource in the physical 
        address space of the hardware. Instances of ``memoryview`` are assigned
        to the resource instances under the attribute ``memory``.
        
        :param resource_manager: Resource with instances to be mapped
        :type resource_manager: :class:`ManagedResource`
        :param mem_cast: The memory type to which the view should be casted,
            as indicated by a ``struct`` format character.
        :type mem_cast: str, optional
        """

        m = mmap.mmap(self._mem_file, 
            resource_manager.memory_size, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            resource_manager.base_byte_address)
        
        self._mem_maps.append(m)
        resource_manager._pool_memory = m
        
        for instance in resource_manager.instances:
            start_byte = instance.byte_address() - resource_manager.base_byte_address
            t = instance._dtype if instance._dtype is not None else default_dtype
            instance.memory = np.frombuffer(m, 
                                            dtype=np.uint8, 
                                            offset=start_byte, 
                                            count=instance.byte_length()).view(t)

        
    def _attach_memory(self, address, size, dtype=np.uint8):
        """
        Maps a region of memory in the physical address space of the hardware.
        
        :param address: Physical address to map
        :type address: int
        :param size: Size of the space to map in bytes
        :type size: int
        """

        m = mmap.mmap(self._mem_file, 
            size, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            address)
        self._mem_maps.append(m)
        
        return np.frombuffer(m, dtype=dtype)

    def _sequencer_command_datamover(self, datamover_name, address, size, tag=0xA, incr=True, address_base=None):
        """
        Configure a DataMover (either MM2S or S2MM).

        :param datamover_name: Name of the DataMover on the sequencer's 
            DataMover controller
        :type datamover_name: str
        :param address: Address for the AXI interface
        :type address: int
        :param size: Transfer size in bytes
        :type size: int
        :param tag: Numeric tag to use in command. Must be between 0 and 15 
            inclusive.
        :type tag: int, optional
        :param incr: If ``True``\, the AXI transaction is in INCR mode.
        :type incr: bool, optional
        :param address_base: If provided, uses the provided value for the upper
            bits of the destination address. This allows the lower 32 bits 
            (provided in ``address``) to be an object on which a bitshift 
            cannot be performed, such as a :class:`Sequencer.Register` or
            :class:`Sequencer.DSP`\.
        :type address_base: int, optional
        """

        if isinstance(size, int) or isinstance(size, float):
            if size > 2**23:
                raise ValueError(f"Size must be less than 8 MB; received {size}.")
        else:
            print("Unable to determine size of transfer;"
                  "ensure that the size is less than 8 MB.")
                
        transfer_type = int(incr) # INCR transaction
        transfer_eof = 0 # TLAST will arrive with the data
        transfer_tag = tag # Arbitrary value that will be included in the status word
        transfer_cache = 0 # not needed for now
        transfer_user = 0 # not needed for now

        misc_reg = ((transfer_user << 10) 
                    | (transfer_cache << 6) 
                    | (transfer_tag << 2) 
                    | (transfer_eof << 1) 
                    | (transfer_type << 0))

        if address_base is not None:
            misc_reg |= (address_base >> 32) << 14
            addr_reg = address
        else:
            misc_reg |= (address >> 32) << 14
            addr_reg = address & 0xFFFFFFFF

        # Configure the DataMover controller (the last bus write will 
        # push the complete command into the command FIFO)
        bus_address_base = self._firmware.sequencer_bus_decoder[f"{datamover_name}_controller"].address()
        self._active_sequencer.bus_write(address=bus_address_base+2, 
                                         data=misc_reg,
                                         comment=f"Configuration for {size}-byte transfer to address"
                                                 f" {str(address_base) + '+' if address_base is not None else ''}"
                                                 f"{address} using DataMover"
                                                 f" {datamover_name}")
        self._active_sequencer.bus_write(address=bus_address_base+1, 
                            data=size)
        self._active_sequencer.bus_write(address=bus_address_base, 
                            data=addr_reg)
            
@dataclass
class StreamConfiguration:
    """
    An abstraction for configurations of the stream processing path.
    
    The ``input_source`` field defines the source of data driving the stream. 
    If ``input_source`` is a 
    :class:`Channel` object (which must be an ADC), then the default behavior 
    will depend on whether the specified ADC is directly connected to the input
    switch. If ``input_source`` is a string, it is understood to specify the 
    kind of input to request.
    
    The ``module`` field indicates which kind of stream processing module to 
    use.
    """
    
    input_source: object
    acadia: Acadia 
    module: str = "memory"
    adc_switch_output_num : int = None
    
    def __post_init__(self):
        
        # Establish some hidden fields for mapping requested inputs and 
        # modules to internal switch port numbers
        self._input_resource = None
        self._module_resource = None
        self._adc_switch_master = None
        self._adc_switch_slave = None
        
        if isinstance(self.input_source, Channel):
            if self.input_source.is_dac:
                raise ValueError("Input source channels must be ADCs.")
            
            # We now need to determine which switch input port to use
            # First, check if the ADC is directly connected to the input switch
            name = f"ADC{self.input_source.num}"
            if name in self.acadia._stream_input_resources:
                self._input_resource = self.acadia._stream_input_resources[name]()
            else:
                self._input_resource = self.acadia._stream_input_resources["ADC_switch"]()                
                self._adc_switch_slave = self._input_resource._resource_id
                
                # Figure out which master for the ADC switch it is
                adc_switch_inputs = list(range(self.acadia._firmware.NUM_ADCS))
                for inp in self.acadia._firmware["stream_processing_path"]["inputs"]:
                    if inp["kind"] == "ADC":
                        adc_switch_inputs.remove(inp["channel"])
                
                # This will raise an exception if it's not in the list
                self._adc_switch_master = adc_switch_inputs.index(self.input_source.num)
            
        elif isinstance(self.input_source, str):
            self._input_resource = self.acadia._stream_input_resources[self.input_source]()
            
        else:
            raise TypeError(f"Invalid type of input source ({type(self.input_source)})")
        
        self._input_switch_master = self._input_resource.switch_port()
        
        # Now determine which module to use
        if not isinstance(self.module, str):            
            raise TypeError(f"Invalid type for specifying module: {type(self.input_source)}")
        
        self._module_resource = self.acadia._stream_module_resources[self.module]()
        self._input_switch_slave = self._module_resource.switch_port()
    
    def reset(self):
        """
        Reset the datamover controller, module, and any associated FIFOs.
        """
        # Reset the DataMover controller
        address = self.acadia._firmware.sequencer_bus_decoder[f"module{self._input_switch_slave}_s2mm_datamover_controller"].address().value()
        self.acadia._active_sequencer.bus_write(address=address+3, data=0)
        
        if self._module_resource.kind == "adder":
            address = self.acadia._firmware.sequencer_bus_decoder[f"module{self._input_switch_slave}_registers"].address().value()
            self.acadia._active_sequencer.bus_write(address=address, data=(1 << 2))
        elif self._module_resource.kind == "dsp":
            address = self.acadia._firmware.sequencer_bus_decoder[f"module{self._input_switch_slave}_registers"].address().value()
            self.acadia._active_sequencer.bus_write(address=address, data=(1 << 4))
        elif self._module_resource.kind == "cmacc":
            address = self.acadia._firmware.sequencer_bus_decoder[f"module{self._input_switch_slave}_registers"].address().value() + 2
            self.acadia._active_sequencer.bus_write(address=address, data=(1 << 24))
            
    def release(self):
        """
        Release the module resources required for the configuration.
        """
        self._input_resource._released = True
        self._module_resource._released = True
            