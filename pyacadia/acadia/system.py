import os
import mmap
import time
import logging
import struct
import builtins
import re
import json
from dataclasses import dataclass
from functools import wraps
from typing import Union, Callable
from binascii import hexlify,unhexlify

import numpy as np

from .waveforms import WaveformMemory, ChannelWaveformMemory, FixedChannelWaveformMemory, DecimatedChannelWaveformMemory, WindowedConstantWaveformMemory
from .compiler import ManagedResource, ManagedMemory, Processor, Synchronizer, Operation, Symbol
from .sequencer import Sequencer
from .dma import DMA
from .peripherals import RFClk, PSGPIO, ZDMA, AXISSwitch
from .firmware import Firmware
from .firmware_configurations import CONFIG_200

import acadia.utils as utils
import acadia.rfdc as rfdc
from acadia.rfdc import Channel

__all__ = ["DMASynchronizer", 
           "RFDCSynchronizer", 
           "StreamConfiguration"
           "Acadia"]

logger = logging.getLogger()

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
        
        # Keep track of when every channel in the synchronizer had its first 
        # entry pushed to the FIFO. We need to know this because we'll have a
        # problem if we push to the FIFO too close to when we trigger
        latest_first_call = 0
        channels_used = []
        
        self.dma_mask = 0

        for idx_call,call in enumerate(self._calls):
            function,acadia,args,kwargs,retval = call.values()
            
            if self._acadia is None:
                self._acadia = acadia
            elif acadia is not self._acadia:
                raise ValueError(f"Unable to synchronize different instances"
                                 f" of `Acadia`")
                
            if function == DMASynchronizer.DMA:
                if "channel" not in kwargs:
                    raise KeyError(f"Unable to locate channel in kwargs {kwargs}")
                
                if "length" not in kwargs:
                    raise KeyError(f"Unable to locate length in kwargs {kwargs}")
                
                channel = kwargs['channel']
                length = kwargs["length"]
                
                if not isinstance(channel, Channel):
                    raise TypeError(f"Channel must be of type `Channel` (received"
                                    f" {channel}).")
                
                if not isinstance(length, (int, Symbol, Operation)):
                    raise TypeError(f"Received invalid length: {length}")
                
                if channel in channel_lengths:
                    channel_lengths[channel] += [length]
                else:
                    channel_lengths[channel] = [length]
                    
                self.dma_mask |= acadia.get_dma(channel).mask
                acadia.channel_dma_stream(**kwargs)
                if channel not in channels_used:
                    latest_first_call = idx_call
                    channels_used.append(channel)
                
            elif function == DMASynchronizer.BARRIER:
                # We first need to figure out the time in the block at which 
                # the barrier exists.
                total_channel_lengths = {}
                for channel,lengths in channel_lengths.items():
                    logger.debug(f"Combining lengths for channel {channel}:")
                    total_channel_lengths[channel] = 0
                    for length in lengths:
                        logger.debug(f"\t{length}")
                        total_channel_lengths[channel] = total_channel_lengths[channel] + length

                # Reset channel lengths so that when we hit the next barrier 
                # (if any) it only adds delays after this one
                channel_lengths = {}
                logger.debug(f"Total channel lengths at barrier insertion time: {total_channel_lengths}")
                barrier_time = Operation(builtins.max, list(total_channel_lengths.values()))
                                                
                # Then, for every channel that has some action after the 
                # barrier, we need to add a blank so that the next action 
                # starts at the right time
                future_channels = []
                for call in self._calls[idx_call+1:]:
                    if (call["function"] == DMASynchronizer.DMA 
                            and call["kwargs"]["channel"] not in future_channels):
                        future_channels.append(call["kwargs"]["channel"])
                
                for channel in future_channels:
                    if channel in total_channel_lengths:
                        pre_barrier_delay = barrier_time - total_channel_lengths[channel]
                    else:
                        pre_barrier_delay = barrier_time

                    acadia.channel_dma_stream(channel=channel,
                                                length=pre_barrier_delay,
                                                word_address=0,
                                                fixed=True,
                                                blank=True)
                    
                    if channel not in channels_used:
                        latest_first_call = idx_call
                        channels_used.append(channel)
                
            else:
                raise ValueError(f"Synchronizer called with unrecognized"
                                 f" function code: {function}")
                
        if self.dma_mask == 0:
            raise ValueError("Empty synchronizer")
        
        if self._dma_trigger:
            # There's a certain latency associated with pushing to the DMA FIFO and 
            # before the descriptor actually exits the memory, so we need to wait for this
            required_latency = 0
            
            # Figure out if at least one of the channels in the calls is pipelined;
            # if so, we'll need an extra cycle of trigger latency
            for call in self._calls:
                channel = call["kwargs"]['channel']
                idx = channel.num() + (16 if not channel.is_dac else 0)
                if self._acadia._firmware["sequencer_bus"]["dma_pipeline"][idx]:
                    required_latency += 1
                    break
            
            # 1 cycle for the data to propagate from the FIFO input to output 
            # (this is when the address will appear at the descriptor memory read port)
            required_latency += 1
            
            # Extra cycles for descriptor memory input and output pipeline cycles
            # TODO: make this smarter, but for now we'll use the DAC pipeline latencies
            required_latency += self._acadia._firmware["dac_dma_descriptor_memory"]["dma_port_input_pipeline"]
            required_latency += self._acadia._firmware["dac_dma_descriptor_memory"]["dma_port_output_pipeline"]
            
            # We only need as much latency as is necessary to appropriately separate 
            # the first FIFO push for a given channel and its corresponding trigger. 
            # However, if we write multiple times to a FIFO, this counts as cycles that
            # separate the first push from the trigger, so we don't need to add as many
            # NOPs
            # TODO: pushing to channel FIFOs should be reordered so that the first push
            # to each channel happens as early as possible
            # TODO: what happens if the first push (or more) gets translated into a NOP?
            nops = required_latency - (len(self._calls) - latest_first_call)
            for _ in range(nops):
                proc.nop(comment=f"Trigger latency (latest first call at {latest_first_call},"
                                 f" required latency {required_latency})")
            
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
                        latency=self._acadia._bus_latency("dma_running"))
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
            function,acadia,args,kwargs,retval = call.values()
            
            if self._acadia is None:
                self._acadia = acadia
            elif acadia is not self._acadia:
                raise ValueError(f"Unable to synchronize different instances of `Acadia`")

            channel = kwargs["channel"] if "channel" in kwargs else args[0]
            if not isinstance(channel, Channel):
                raise TypeError(f"Unable to identify channel (received {channel}).")
            
            
            rfdc_bit_position = 1 << (channel.num() if channel.is_dac else channel.num()+16)
                
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
        
@dataclass
class StreamConfiguration:
    """
    An abstraction for configurations of the stream processing path.
    """
    
    input_source: object
    module: str 
    input_resource: object
    module_resource: object
    adc_switch_master: int
    adc_switch_slave: int
    input_switch_master: int
    input_switch_slave: int
    
    def output_datamover(self):
        return f"module{self.input_switch_slave}_s2mm_datamover"
    
class Acadia:
    """
    A class that implements system-wide commands for the Acadia hardware.
    """
    
    CMACC_QUADRANT_1 = 0
    CMACC_QUADRANT_2 = 1 << 19
    CMACC_QUADRANT_3 = (1 << 19) | (1 << 20)
    CMACC_QUADRANT_4 = 1 << 20
    
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
        self._firmware = Firmware(firmware if firmware is not None else CONFIG_200)
        
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
        
        self._stream_configurations = []
        
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
        self.channel_synchronizer = DMASynchronizer(name="channel_synchronizer", allow_standalone=True)
        self.tile_synchronizer = RFDCSynchronizer(name="tile_synchronizer", allow_standalone=True)
        
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
        
        self._attach_resource(self.CacheArray)
        self._attach_resource(self.OCMArray)
        
        # Map instruction memory for all of the processors
        self._sequencer_instruction_memory = self._attach_memory(
            address=self._firmware["sequencer_instruction_memory"]["address"],
            size=self._firmware["sequencer_instruction_memory"]["size_bits"] // 8,
            return_map=True)  
        
        self._dac_dma_descriptor_memory = [self._attach_memory(
            address=(self._firmware["dac_dma_descriptor_memory"]["address"] 
                    + i*(self._firmware["dac_dma_descriptor_memory"]["size_bits"] // 8)),
            size=self._firmware["dac_dma_descriptor_memory"]["size_bits"] // 8,
            return_map=True) for i in range(self._firmware.NUM_DACS)]
                
        self._adc_dma_descriptor_memory = [self._attach_memory(
            address=(self._firmware["adc_dma_descriptor_memory"]["address"] 
                    + i*(self._firmware["adc_dma_descriptor_memory"]["size_bits"] // 8)),
            size=self._firmware["adc_dma_descriptor_memory"]["size_bits"] // 8,
            return_map=True) for i in range(self._firmware.NUM_ADCS)]
            
        for dac_mem in self.DACArray:
            self._attach_resource(dac_mem)
            
        for cmacc_kernel_mem in self.CMACCKernelArray:
            self._attach_resource(cmacc_kernel_mem)
                
        self._attach_resource(self.PLDDR0Array)
        self._attach_resource(self.PLDDR1Array)
        self._attach_resource(self.PSDDRArray)
            
        # Connect to the RFDC driver and initialize
        rfdc.attach()
        utils.attach()
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
    
    def sequencer(self) -> Sequencer:
        """
        Create and store a new sequencer object associated with this system,
        if a sequencer is not already active (in which case, that one is 
        returned).
        """

        if self._active_sequencer is not None:
            return self._active_sequencer
        
        return self._sequencer_type()
    
    def sequence(self, func: Callable) -> Sequencer:
        """
        Compiles a Python function as a sequence for the Acadia sequencer. 
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
            # Reset all the stream modules
            self.reset_all_streams()

            # Clear the stream offsets
            # Technically this isn't needed because resetting the streams resets 
            # the Datamover controller which clears the address offset register, 
            # but compiling in these instructions makes it easy to update them
            # for module_num,module in enumerate(self._firmware["stream_processing_path"]["modules"]):
            #     datamover_name = f"module{module_num}_s2mm_datamover_controller"
            #     bus_address_base = self._firmware.sequencer_bus_decoder[datamover_name].address().value()
            #     self._active_sequencer.bus_write(address=bus_address_base+3, 
            #                                     data=0,
            #                                     comment=f"Clear offset for"
            #                                             f" {datamover_name}"
            #                                             f" ({module['kind']})")

            retval = func(self)
            
        self._active_sequencer = None

        # Add one instruction buffer between the end of the program and completion reporting,
        # just for sanity (TODO maybe this isn't needed anymore?)
        s.nop()

        # Report to the PS that the sequencer is halted
        s.bus_write(address=self._firmware.sequencer_bus_decoder["ps_gpio5"].address(), data=1)

        s.halt()
        
        # Because the sequence resource object was created before we knew its 
        # size and because we know that the size won't change from this point,
        # we can update the size of the instance and the allocation index of
        # the sequence resource
        s.size = s.Instruction.usage()
        
        return retval
                        
    # -------------- CLOCKING AND SYNCHRONIZATION ROUTINES ----------- #
    
    def align_tile_latencies(self):
        """
        Align the latencies of all tiles by measuring the latency through
        all interface FIFOs. Delays are then applied so that the total latency
        of all tiles is equal to that of the slowest. This method uses the
        RFDC Multi-Tile Synchronization (MTS) routines.
        """

        # Initialize MTS data structures
        rfdc.mts_init()

        # Enable continuous SYSREF clock
        logger.debug("Enabling continuous SYSREF")
        self.pulse_sysref()

        # Carry out the synchronization
        logger.debug("Synchronizing...")
        result = rfdc.mts_sync()
        logger.debug("Synchronization completed")

        # Turn off SYSREF
        self.pulse_sysref(0)
        logger.debug("SYSREF disabled")

        time.sleep(0.2)

        return result
    
    def update_ncos_synchronized(self):
        """
        Synchronously update the frequency and/or phase of multiple NCOs 
        following a series of calls to :meth:`update_nco_frequency`, 
        :meth:`update_nco_phase`, and/or :meth:`reset_nco_phase`.

        Note that before calling this function, the tiles must be aligned by 
        calling ``self.align_tile_latencies`` and each channel passed in must 
        have had its NCO configured for synchronous updates by calling
        ``<channel>.configure_nco(update_source="sysref")``.
        """

        # Carry out a synchronized NCO update
        self.pulse_sysref(1)
            
        # Wait a moment so that the sysref will have actually happened
        # TODO: find a way to check this. if it exists it's not documented
        time.sleep(0.001)

    def update_nco_frequency(self, channel: Channel, frequency: float):
        """
        Update the NCO frequency. If called in a Sequencer context, this will
        update the RFDC through the bus; otherwise, it will be updated via a
        driver call.

        :param channel: Channel to update
        :type channel: :class:`Channel`
        :param frequency: Frequency in Hz
        :type frequency: float
        """     
        
        frequency_word = channel.frequency_to_nco_word(frequency)
        
        proc = Processor.active_processor()
        if proc is None:
            channel.set_nco_frequency_word(frequency_word)
                
        elif isinstance(proc, Sequencer):    
            frequency_base_reg = self._firmware.rfdc_rts_regs.address().value() + channel.num()*2
            
            if not channel.is_dac:
                frequency_base_reg += 16*2 
            proc.bus_write(address=frequency_base_reg, 
                            data=(frequency_word >> 16) & 0xFFFFFFFF,
                            comment="Write NCO frequency high bits")
            proc.bus_write(address=frequency_base_reg+1, 
                            data=frequency_word & 0xFFFF,
                            comment="Write NCO frequency low bits")

            self.tile_synchronizer.add({
                "function": RFDCSynchronizer.NCO_FREQUENCY, 
                "self": self, 
                "args": (channel,), 
                "kwargs": {},
                "retval": None})
        
        else:
            raise TypeError("NCO frequency can only be set in `Sequencer` contexts or on the PS.")
    
    def update_nco_phase(self, channel: Channel, phase: float):
        """
        Set the NCO phase offset to the given value.

        :param phase: Phase in radians
        :type phase: float
        """
        phase_word = channel.phase_to_nco_word(phase)
        proc = Processor.active_processor()
        if proc is None:
            channel.set_nco_phase_word(phase_word)
                
        elif isinstance(proc, Sequencer):
            phase_reg = self._firmware.rfdc_rts_regs.address().value() + 0x40 + channel.num()
            
            if not channel.is_dac:
                phase_reg += 16
                
            proc.bus_write(address=phase_reg, 
                           data=phase_word & 0x0003FFFF,
                           comment=f"Write to NCO phase register for {channel}")

            self.tile_synchronizer.add({
                "function": RFDCSynchronizer.NCO_PHASE, 
                "self": self, 
                "args": (channel,), 
                "kwargs": {},
                "retval": None})
            
        else:
            raise TypeError("NCO phase can only be set in `Sequencer` contexts or on the PS.")

    def reset_nco_phase(self, channel: Channel):
        """
        Reset the value of the NCO phase accumulator.
        """

        proc = Processor.active_processor()
        if proc is None:
            channel.reset_nco_phase()
                
        elif isinstance(proc, Sequencer):
            # Do nothing, the synchronizer will set the bit in the register
            self.tile_synchronizer.add({
                "function": RFDCSynchronizer.NCO_PHASE_RESET, 
                "self": self, 
                "args": (channel,), 
                "kwargs": {},
                "retval": None})
            
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

        # Calculate the divider value that we need for the LMK output channels
        # VCO is configured for 3 GHz
        target_frequency = self._firmware["clk104_pl_clk"]["freq_hz"]
        divider = 3e9 / target_frequency
        if round(divider, 6) != round(divider):
            raise ValueError(f"Required frequency {target_frequency} does not"
                " divide the LMK VCO frequency by an integer.")
        divider = int(round(divider))

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
        # Although the regular channel (non-sync) for the sync channel SDCLK_RFDC
        # isn't connected to anything, it needs to be set up in order for the
        # sync signal to be generated
        for output in [RFClk.LMK.DCLK_PL, 
                       RFClk.LMK.DCLK_RFDC_DAC, 
                       RFClk.LMK.DCLK_RFDC_ADC,
                       RFClk.LMK.SDCLK_RFDC-1]:
            # Set all output multiplexers to the input for the divider
            # with duty cycle correction and half-step
            RFClk.LMK.set_output_mux(output, 1)
            RFClk.LMK.set_output_divider(output, divider)
        
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

        # Wait a bit for everything to lock
        time.sleep(0.5)

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
                        
        return d
    
    # -------------- CHANNEL HELPERS ----------- #

    def DAC(self, num: Union[int, str]) -> Channel:
        """
        :return: a :class:`Channel` representing a DAC.
        :rtype: :class:`Channel`
        """

        return self._DAC_channels[int(num)]

    def ADC(self, num: Union[int, str]) -> Channel:
        """
        :return: a :class:`Channel` representing an ADC.
        :rtype: :class:`Channel`
        """

        return self._ADC_channels[int(num)]
    
    def channel(self, specifier: Union[str, Channel, None]) -> Channel:
        """
        Obtain a channel object via a string specifier of the form "DACxx"
        or "ADCxx".
        """

        if specifier is None or isinstance(specifier, Channel):
            return specifier
        
        if not isinstance(specifier, str):
            raise TypeError(f"Channel specifier must be a string;"
                            f" received {specifier}")
        
        m = re.match("(ADC|DAC)([0-9]+)", specifier)
        if m is None:
            raise ValueError(f"Unable to parse channel specifier {specifier}")
        
        channel_type, num = m.groups()
        if channel_type == "ADC":
            return self.ADC(num)
        
        return self.DAC(num)

    def get_dma(self, channel: Channel):
        """
        Get the DMA for a given channel.
        
        :param channel: Channel to get the DMA for
        :type channel: :class:`Channel`
        """
        
        return self._dac_dmas[channel.num()] if channel.is_dac else self._adc_dmas[channel.num()]
    
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
        
        if isinstance(length, (int, float)) and length == 0:
            return None
            
        # When we request the descriptor, we need to get the address aligned to
        # 128 bits. We need the word address
        dma = self._dac_dmas[channel.num()] if channel.is_dac else self._adc_dmas[channel.num()]
        
        descriptor = dma.request_descriptor(
            word_address, 
            length,
            decimate=decimate,
            fixed=fixed,
            blank=blank)
        
        dev_name = f'{"dac" if channel.is_dac else "adc"}{channel.num()}_dma'
        device = self._firmware.sequencer_bus_decoder[dev_name]
        
        self._active_sequencer.bus_write(
            address=device.address().value(),
            data=descriptor, 
            comment=f"Add descriptor with parameters {descriptor.kwargs} to"
                    f" FIFO for {'DAC' if channel.is_dac else 'ADC'}{channel.num()}")
        
        return descriptor
    
    def memory_region(self, 
                      specifier: Union[Channel, ManagedMemory, np.ndarray, str, StreamConfiguration, None]) -> callable:
        """
        Retrieve a memory region for this instance from a specifier object. The
        returned object will always be a callable that can accept the arguments 
        "shape" and "dtype" in order to allocate memory in the desired region.
        
        Valid options for ``specifier`` and the corresponding returned regions 
        are:

        - A :class:`Channel` object for a DAC: The waveform memory allocator 
            for that channel is returned.

        - A :class:`StreamConfiguration` for a CMACC module: The kernel memory
            for that CMACC module is returned.

        - A string of the form ``"DACxx"``: The waveform memory allocator for that
            channel is returned.

        - ``"plddr"`` or ``"plddr0"``: The memory allocator for channel 0 of
            the PL DDR is returned.

        - ``"plddr1"``: The memory allocator for channel 1 of the PL DDR is 
            returned.

        - ``"cache"``: The memory allocator for the sequencer-PS shared cache
            is returned.

        - ``"ocm"``: The memory allocator for the region of PS on-chip memory
            (OCM) is returned.

        - ``"numpy"``: An allocator that creates a numpy array in the memory
            space of the running process is returned.
        """
        if specifier is None or isinstance(specifier, (ManagedMemory, np.ndarray)):
            return specifier
        
        if isinstance(specifier, Channel) and specifier.is_dac:
            return self.DACArray[specifier.num()]
        
        if isinstance(specifier, StreamConfiguration) and specifier.module == "cmacc":
            return self.CMACCKernelArray[specifier.module_resource._resource_id]
        
        if not isinstance(specifier, str):
            raise TypeError(f"Unable to convert object into memory region: {specifier}")
        
        # Check whether it's a string of a channel
        m = re.match("DAC([0-9]+)", specifier)
        if m is not None:
            channel_num = int(m.groups()[0])
            return self.DACArray[channel_num]
        
        s = str.lower(specifier)
        
        if s == "plddr0" or s == "plddr":
            return self.PLDDR0Array
        
        if s == "plddr1":
            return self.PLDDR1Array
        
        if s == "cache":
            return self.CacheArray
        
        if s == "ocm":
            return self.OCMArray
        
        if s == "numpy":
            return np.empty
        
        raise ValueError(f"Unable to parse memory region specifier string: {specifier}")
    
    def create_waveform_memory(self,
                        channel: Channel,
                        length: Union[int, float, np.ndarray] = 0.0,
                        fixed_length: Union[float, Symbol, Operation] = 0.0,
                        blank: bool = False,
                        decimation: Union[int, None] = 1,
                        region: Union[Channel, ManagedMemory, None, str] = None) -> ChannelWaveformMemory:
        """
        Allocate a waveform. This function allows for a few different signatures; 
        the first argument is always a :class:`Channel` object. 
        argument ``length`` determines the required signature:

        - If a ``float`` or a numpy float dtype, this should contain the length
            of the waveform in seconds.

        - If a numpy array with a complex or float dtype, the waveform is 
            allocated so that the data in the array could be stored after 
            being converted to samples. The shape of the resulting waveform 
            is also extracted from the argument. 

        - If a numpy array with an integer dtype, the argument is assumed to
            contain the sample data that will eventually be stored in the 
            waveform. The last dimension of the array must be of length 2.
            Note that this does not store the sample data in any way; it just
            uses it to determine the shape of aray must be allocated.
            
        :param channel: Channel for the waveform
        :type channel: :class:`Channel`
        :param length: The length of the waveform; see description above
        :type length: float, np.ndarray[complex], np.ndarray[float]
        :param fixed_length: The length of the fixed part of the waveform, if any.
        :type fixed_length: float, Symbol, or Operation
        :param blank: Create a blank waveform. If ``True``, ``region`` must
            be ``None``
        :type blank: bool
        :param decimation: Decimation for ADC waveforms
        :type decimation: int
        :param region: The memory region in which the WaveformMemory is stored
        """
        #################################################################
        # Start by validating the provided parameters
        #################################################################

        channel = self.channel(channel)

        # The region must be determined here
        region = self.memory_region(region)

        # If we couldn't determine the region from the provided parameter
        # and the channel is a DAC, try again to get the channel's dedicated
        # waveform memory region
        if region is None and channel.is_dac:
            region = self.memory_region(channel)

        # By this point we need to have determined a region, so throw an
        # error if we couldn't
        if region is None:    
            raise ValueError(f"Unable to determine memory allocation region.")
        
        if decimation is None:
            decimation = 1
        elif isinstance(decimation, float) and round(decimation) == round(decimation, 1):
            decimation = int(round(decimation))
        elif not isinstance(decimation, int):
            raise TypeError(f"Decimation must be an integer;"
                                    f" received {decimation}")
        
        if channel.is_dac and decimation != 1:
            raise ValueError(f"Decimation must be 1 for DAC channels.")
        
        if decimation != 1 and decimation % 4 != 0:
            raise ValueError(f"Decimation may only be 1 or a multiple of 4"
                             f" (received {decimation})")

        ##############################################################################
        # Convert provided lengths in time units into sample lengths and memory sizes
        ##############################################################################

        # Figure out how many samples will be processed at the channel interface
        # All channels use 32 bits per sample at the FIFO, so we can infer this directly from the tile config        
        if channel.is_dac:
            channel_samples_per_cycle = self._firmware["rfdc"]["dac"]["channel_interface_width"][channel.num()] // 32
        else:
            # The source is either an ADC channel or a location in memory,
            # both of which must have interface widths equal to the path width
            channel_samples_per_cycle = self._firmware["stream_processing_path"]["width"] // 32

        if isinstance(fixed_length, float) and fixed_length >= 0:
            fixed_length_cycles_float = fixed_length * self._firmware["clk104_pl_clk"]["freq_hz"]
            fixed_length_cycles = round(fixed_length_cycles_float)
            if fixed_length_cycles != round(fixed_length_cycles_float, 1):
                raise ValueError(f"Fixed length {fixed_length} seconds"
                                    f" is not an integer number of cycles"
                                    f" ({fixed_length_cycles_float} cycles)")
        elif isinstance(fixed_length, (Symbol, Operation)):
            logger.warning(f"Unable to validate symbolic fixed length;"
                           " please ensure that the value provided is an"
                           " integer number of cycles after being rounded.")
            fixed_length_cycles_float = fixed_length * self._firmware["clk104_pl_clk"]["freq_hz"]
            fixed_length_cycles = Operation(round, fixed_length_cycles_float)
        else:
            raise TypeError(f"Unable to use fixed length {fixed_length}")

        # Given a length and fixed length, determine the number of samples in the array
        # For ADC channels, this is the number of samples after decimation
        # Also determine the number of cycles that the operation will run for
        # These are always directly proportional, but the proportionality
        # constant is dependent on the decimation and the type of channel
        if isinstance(length, float):
            # Length of waveforms in seconds
            length_cycles_float = length * self._firmware["clk104_pl_clk"]["freq_hz"]
            length_cycles = round(length_cycles_float)
            if length_cycles != round(length_cycles_float, 1):
                raise ValueError(f"WaveformMemory length {length} seconds does not"
                                    f" correspond to an integer number of cycles"
                                    f" ({length_cycles_float})")
            
            input_length_samples = length_cycles * channel_samples_per_cycle
            if decimation == 0:
                decimation = input_length_samples

            elif input_length_samples % decimation != 0:
                raise ValueError(f"Number of input samples ({input_length_samples})"
                                 f" is not a multiple of the decimation ({decimation}) ")
            
            length_samples = input_length_samples // decimation

        elif isinstance(length, np.ndarray):
            # When decimation is not 1, we don't have enough information to determine
            # how long in time the waveform is
            if decimation != 1:
                raise ValueError(f"When specifying a waveform size with a numpy"
                                 f" array, decimation must be 1.")

            if length.dtype.kind == 'f' or length.dtype.kind == 'c':
                # Convert float arrays to complex
                length_samples = length.size

            elif length.dtype.kind == 'i':
                if length.shape[-1] != 2:
                    raise ValueError(f"WaveformMemory objects specified by numpy arrays must"
                                    f" have a shape in which the last dimension"
                                    f" is of length 2 (received array with shape"
                                    f" {length.shape})")
                length_samples = length.size // 2
            
            else:
                raise TypeError(f"WaveformMemory objects specified by numpy arrays must have"
                                f" float, complex, or integer dtypes (received"
                                f" dtype {length.dtype})")

            if length_samples % channel_samples_per_cycle != 0:
                raise ValueError(f"Number of waveform samples ({length_samples})"
                                f" is not a multiple of the number of samples per"
                                f" cycle ({channel_samples_per_cycle}) and no"
                                f" decimation is used.")
        
            length_cycles = length_samples // channel_samples_per_cycle

        else:
            raise TypeError(f"WaveformMemory length must be specified as a float"
                            f" or as a numpy array (received {type(length)}).")
        
        ############################################################################################
        # We now know the waveform time in cycles and size in samples, so create the waveform array
        ############################################################################################
        
        if blank:
            return FixedChannelWaveformMemory(
                channel, 
                length_cycles=length_cycles + fixed_length_cycles, 
                blank=True,
                resource_allocator=region) 
        
        if length_cycles == 0:
            if fixed_length_cycles == 0:
                raise ValueError("WaveformMemory has total length zero.")
            
            # Only a fixed length was provided, so create a fixed waveform
            logger.debug(f"Allocating FixedWaveformMemory for channel {channel} with"
                            f" a length of {fixed_length_cycles} cycles"
                            f" ({channel_samples_per_cycle} samples per cycle)")
            
            return FixedChannelWaveformMemory(
                channel, 
                length_cycles=fixed_length_cycles, 
                resource_allocator=region)
            
        if decimation != 1:
            if fixed_length_cycles != 0:
                raise ValueError("Fixed length must be zero for decimated waveforms.")
            
            logger.debug(f"Allocating DecimatedChannelWaveformMemory for channel {channel} with"
                        f" {length_samples} samples, which corresponds to"
                        f" {length_cycles} cycles ({channel_samples_per_cycle}"
                        f" samples per cycle, decimation {decimation})")
            
            return DecimatedChannelWaveformMemory(
                channel, 
                shape=length_samples, 
                decimation=decimation, 
                resource_allocator=region)
        
        if fixed_length_cycles != 0:
            # By this point, decimation is 1 and length_cycles != 0
            logger.debug(f"Allocating WindowedConstantWaveformMemory for channel {channel} with"
                            f" a fixed length of {fixed_length_cycles} cycles and"
                        f" {length_samples} window samples, which corresponds to"
                        f" {length_cycles} cycles ({channel_samples_per_cycle}"
                        f" samples per cycle)")
            
            return WindowedConstantWaveformMemory(
                channel, 
                window_length_samples=length_samples, 
                constant_length_cycles=fixed_length_cycles, 
                resource_allocator=region)

        logger.debug(f"Allocating ChannelWaveformMemory for channel {channel} with"
                        f" {length_samples} samples, which corresponds to"
                        f" {length_cycles} cycles ({channel_samples_per_cycle}"
                        f" samples per cycle)")
        
        return ChannelWaveformMemory(
            channel, 
            shape=length_samples, 
            resource_allocator=region)
        
    @requires_sequencer
    def schedule_waveform(self, waveform: ChannelWaveformMemory):
        """
        Schedule a waveform on a channel's DMA. 
        
        :param channel: Channel to stream
        :type channel: :class:`Channel`
        :param waveform: Signal to stream
        :type waveform: :class:`ChannelWaveformMemory` or any type implementing 
            `dma_parameters()` returning a list of `dict`. Each `dict` will 
            result in a sequential call to `channel_dma_stream` whose arguments
            are the key/value pairs in the `dict`. 
        """
        # Notify the synchronizer, which will add the DMA command for us
        for params in waveform.dma_parameters():
            self.channel_synchronizer.add({
                "function": DMASynchronizer.DMA, 
                "self": self, 
                "args": (), 
                "kwargs": params,
                "retval": None})
        
    @requires_sequencer
    def stream(self, 
                configuration: StreamConfiguration, 
                dst: WaveformMemory, 
                memory_input = None,
                length: Union[int, None] = None,
                offset: int = 0) -> None:
        """
        Stream data from a source to a destination WaveformMemory. 
        
        The source of data can either be a :class:`Channel` representing an 
        ADC, or it can be an array in memory captured by an :class:`Array`
        object. The ``decimation`` property of ``dst`` will be used to 
        determine whether the stream passed directly from the input into memory
        or whether a DSP module will be used for decimating the stream.

        By default, the entirety of ``dst`` is filled. Alternatively, one may
        optionally specify ``length`` (and also optionally ``offset``) to fill
        only a portion of ``dst``.

        :param src: Data source. If a configuration is provided and this is of
            type :class:`Channel`, the channel in the configuration must match.
        :type src: :class:`Channel` or :class:`Array`
        :param dst: Data destination
        :type dst: :class:`ChannelWaveformMemory`
        :param length: Length of data to stream in samples. Note that this
            is the length after any decimation.
        :param offset: Offset within `dst` at which the stream will be written,
            in units of samples. Note that this offset is applied after any 
            decimation.
        :param configuration: Stream configuration to use. If `None`, a new one
            will be requested.
        :type configuration: :class:`StreamConfiguration`
        :return: The configuration used for streaming
        :rtype: :class:`StreamConfiguration`
        """

        if not isinstance(dst, WaveformMemory):
            raise TypeError(f"Stream destination must be a WaveformMemory;"
                            f" received {type(dst)}")

        dst_params = dst.dma_parameters()[0]
        if isinstance(configuration.input_source, Channel):
            if memory_input is not None:
                raise TypeError(f"src_memory must be None when using stream"
                                " configurations with Channel inputs")
            dst_params["channel"] = configuration.input_source

        if length is None:
            # Fill the output
            # The waveform length will already have been validated when the waveform was created
            length = dst.size
        
        input_samples_per_cycle = self._firmware["stream_processing_path"]["width"] // 32

        # Use the value of length to determine parameters for the DataMover
        if isinstance(dst, DecimatedChannelWaveformMemory):
            dst_params["length"] = length * dst.cycles_per_output_sample
        else:
            # When not decimating, the DataMover writes one path-width of data per cycle
            if length % input_samples_per_cycle != 0:
                raise ValueError(f"Stream of length {length} samples does not"
                                 f" produce an integer number of cycles"
                                 f" ({length / input_samples_per_cycle})")
            dst_params["length"] = length // input_samples_per_cycle
                

        output_length_bytes = length * 2*dst.dtype.itemsize
        offset_bytes = offset * 2*dst.dtype.itemsize
        
        logger.debug(f"Stream length {dst_params['length']} cycles, decimation"
                     f" {dst._decimation if isinstance(dst, DecimatedChannelWaveformMemory) else 1},"
                      f" of output size {output_length_bytes} bytes to address"
                      f" 0x{dst.byte_address:010X} + 0x{offset_bytes:X}")

        self._command_datamover(configuration.output_datamover(), 
                                dst.byte_address + offset_bytes,
                                output_length_bytes)

        if isinstance(configuration.input_source, Channel):
            # notify the synchronizer, which will then add the DMA command for us   
            self.channel_synchronizer.add({
                "function": DMASynchronizer.DMA, 
                "self": self, 
                "args": (), 
                "kwargs": dst_params,
                "retval": None})
        else:
            self._command_datamover(f"input{configuration.input_switch_master}_mm2s_datamover", 
                                   memory_input.byte_address,
                                   memory_input.nbytes)
    
    @requires_sequencer
    def configure_dsp(self, 
                    src: Union[Channel, WaveformMemory], 
                    decimation: int = 1,
                    reset: bool = True,
                    configuration: StreamConfiguration = None) -> StreamConfiguration:
        """
        Configure a DSP for streaming data. 
        
        The source of data can either be a :class:`Channel` representing an 
        ADC, or it can be an array in memory captured by an :class:`Array`
        object. The ``decimation`` property of ``dst`` will be used to 
        determine whether the stream passed directly from the input into memory
        or whether a DSP module will be used for decimating the stream.

        :param src: Data source. If a configuration is provided and this is of
            type :class:`Channel`, the channel in the configuration must match.
        :type src: :class:`Channel` or :class:`Array`
        :param decimation: The decimation to use for the DSP. This must either 
            be 1 or a multiple of 4.
        :type decimation: int
        :param configuration: Stream configuration to use. If `None`, a new one
            will be requested.
        :type configuration: :class:`StreamConfiguration`
        :return: The configuration used for streaming
        :rtype: :class:`StreamConfiguration`
        """

        config_src = src if isinstance(src, Channel) else "memory"
        module = "memory" if decimation == 1 else "dsp"
        if configuration is None:
            configuration = self._request_stream_configuration(config_src, module)

        if decimation != 1:
            # Configure the DSP for decimation
            # At packet start and counter start, we'll load in the input value
            # Otherwise, when we receive valid data, we'll add it to P
            dsp_address = self._firmware.sequencer_bus_decoder[f"module{configuration.input_switch_slave}_registers"].address().value()
            logger.debug(f"Configuring DSP module {configuration.input_switch_slave} at bus address 0x{dsp_address:08X}")

            if reset:
                self.sequencer().bus_write(address=dsp_address, data=(1 << 4))
                self.sequencer().nop()
                self.sequencer().nop()
            
            # P = multiplier: CIN = 0, W = 00, Z = 000, Y = 01, X = 01, ALUMODE = 0000 (W+X+Y+Z+CIN)
            self.sequencer().bus_write(address=dsp_address + 9, data=int("00000001010000", 2)) # packet start config
            self.sequencer().bus_write(address=dsp_address + 10, data=int("00000001010000", 2)) # counter start config
            
            # P = multiplier + P: CIN = 0, W = 01, Z = 000, Y = 01, X = 01, ALUMODE = 0000 (W+X+Y+Z+CIN)
            self.sequencer().bus_write(address=dsp_address + 11, data=int("00100001010000", 2)) # counter run config
            
            # The DSP module output is bits 46 to 15 of P, so we'll multiply by 
            # 2^15 for both quadratures
            self.sequencer().bus_write(address=dsp_address + 1, data=(1 << 15))
            self.sequencer().bus_write(address=dsp_address + 5, data=(1 << 15))
            
            # No pre-add to the input stream
            self.sequencer().bus_write(address=dsp_address + 2, data=0)
            self.sequencer().bus_write(address=dsp_address + 6, data=0)
            
            # load packet start config
            self.sequencer().bus_write(address=dsp_address, data=(1 << 5)) 
            
            # Counter period low and high
            input_samples_per_cycle = self._firmware["stream_processing_path"]["width"] // 32
            counter_value = (decimation // input_samples_per_cycle) - 1
            logger.debug(f"Assigning counter value {counter_value} ({input_samples_per_cycle} input samples per cycle, decimation {decimation})")

            self.sequencer().bus_write(address=dsp_address + 12, data=(counter_value & 0xFFFF) << 16) # low
            self.sequencer().bus_write(address=dsp_address + 13, data=(counter_value >> 16) & 0xFFFFFFFF) # high
        
        return configuration
        

    @requires_sequencer
    def configure_cmacc(self, 
                        src: Union[Channel, WaveformMemory],
                        kernel: Union[np.ndarray, float, None] = None,
                        write_mode: Union[str, None] = "upper", 
                        last_only: bool = True, 
                        reset_fifo: bool = False,
                        accumulator_done: bool = False) -> tuple[StreamConfiguration, WaveformMemory]:
        """
        Configure the CMACC.

        :param src: The source of data to be accumulated by the CMACC
        :type src: Channel or WaveformMemory
        :param kernel: The accumulation kernel, or an object that specified its
            size. If this is a numpy array, its values are ignored, and only its 
            shape information is used in order to determine the size of the 
            kernel allocated in kernel memory. If this is a float, this should be
            the length in seconds of the kernel. If None, a single-element kernel
            is allocated to allow for boxcar accumulation.
        :type kernel: np.ndarray, float, None
        """
        
        if isinstance(src, StreamConfiguration):
            if src.module != "cmacc":
                raise TypeError(f"The StreamConfiguration provided to"
                                f" configure_cmacc must represent a"
                                f" CMACC module (received configuration for module"
                                f" type {src.module})")
            configuration = src
        elif isinstance(src, (Channel, str)):
            configuration = self._request_stream_configuration(self.channel(src), "cmacc")
        elif isinstance(src, WaveformMemory) or isinstance(type(src), ManagedResource):
            configuration = self._request_stream_configuration("memory", "cmacc")
        else:
            raise TypeError(f"Unable to create stream with source {src}")
        
        kernel_type = self.CMACCKernelArray[configuration.module_resource._resource_id]
        
        # Determine whether we need to allocate a new kernel or not
        if isinstance(kernel, WaveformMemory) and isinstance(kernel._resource, kernel_type):
            # We already have a kernel and we're good to go, don't allocate a new one
            kernel_length_elements = kernel.size
            logger.debug(f"Using already-allocated kernel WaveformMemory of length {kernel_length_elements} samples")

        else:
            # We don't already have a kernel, so we need to allocate one
            # Figure out how much memory to allocate for the kernel
            if kernel is None:
                # Boxcar kernel
                kernel_length_elements = 1
            elif isinstance(kernel, float):
                # Use a length in seconds given by kernel
                kernel_length_elements = kernel * self._firmware["clk104_pl_clk"]["freq_hz"]
            elif isinstance(kernel, np.ndarray):
                # Allocate enough space to store the numpy array (after converting to samples)
                kernel_length_elements = len(kernel)
            else:
                raise TypeError(f"Invalid CMACC kernel (received {kernel})")
        
            logger.debug(f"Allocating kernel WaveformMemory of length {kernel_length_elements} samples")
            kernel = WaveformMemory(shape=kernel_length_elements, dtype="<i2", resource_allocator=kernel_type)

        registers = self._firmware.sequencer_bus_decoder[f"module{configuration.input_switch_slave}_registers"].address().value()

        # resource id is the byte offset of the memory segment within its region 
        kernel_index = kernel._resource._resource_id // (2*2) 

        # Set the kernel start and end addresses
        # The kernel uses one 32-bit element per cycle
        kernel_reg = kernel_index | ((kernel_index + kernel_length_elements - 1) << 16)
        kernel_reg &= 0xFFFFFFFF
        self.sequencer().bus_write(address=registers+3, data=kernel_reg)
            
        control_reg = 0

        # Load the kernel pointer from its buffer register
        control_reg |= 1 << 0
        
        if accumulator_done:
            control_reg |= 1 << 18
            
        if write_mode == "upper":
            control_reg |= 1 << 21
        elif write_mode == "lower":
            control_reg |= 2 << 21
        elif write_mode == "input":
            control_reg |= 3 << 21
        elif write_mode is None or write_mode == "none":
            pass
        else:
            raise ValueError(f"Unexpected value for write_mode: {write_mode}")
        
        if last_only:
            control_reg |= 1 << 23
            
        if reset_fifo:
            control_reg |= 1 << 24
            
        logger.debug(f"Configured CMACC for kernel at address 0x{kernel_index:04X}"
                     f" of length {kernel_length_elements} and set control register to"
                     f" 0x{control_reg:08X}")
        self.sequencer().bus_write(address=registers+2, data=control_reg)

        return configuration, kernel
        
    
    @requires_sequencer
    def cmacc_done(self, configuration: StreamConfiguration):
        """
        Create a condition to check whether the CMACC accumulation for a given
        stream configuration is done.

        :param configuration: Configuration whose CMACC should be checked
        :type configuration: :class:`StreamConfiguration`
        :return: A condition for checking whether the CMACC for the given
            configuration has completed its accumulation
        """
        if not isinstance(configuration.module_resource, 
                          self._stream_module_resources["cmacc"]):
            raise TypeError(f"CMACC completion can only be checked for stream" 
                            f" configurations that drive CMACC modules"
                            f" (found module resource type"
                            f" {type(configuration.module_resource)})")
            
        module_name = f"module{configuration.input_switch_slave}_registers"
        registers = self._firmware.sequencer_bus_decoder[module_name].address().value()
        
        return self.sequencer().bus_read(registers+2, 
                                         latency=self._bus_latency(module_name)) & (1 << 18)
        
    @requires_sequencer
    def cmacc_get_quadrant(self, 
                           configuration: StreamConfiguration, 
                           wait_for_completion: bool = True):
        """
        Get the quadrant of the CMACC value. By default, we'll wait for the 
        CMACC value to be available and then return the quadrant information
        in a way which optimizes latency (because the bus address for 
        checking completion is the same for checking quadrant, we don't need
        to incur the bus latency overhead a second time). Otherwise, a regular
        bus read will be performed with all typical latency overheads.
        
        A different constant is returned depending on the quadrant; refer to
        the constants Acadia.CMACC_QUADRANT_1/2/3/4 for their values.
        """
        
        if wait_for_completion:
            with self.sequencer().repeat_until(self.cmacc_done(configuration)):
                pass
            
        module_name = f"module{configuration.input_switch_slave}_registers"    
        registers = self._firmware.sequencer_bus_decoder[module_name].address().value()
        latency = 0 if wait_for_completion else self._bus_latency(module_name)
        value = self.sequencer().bus_read(registers+2, latency=latency)
        return value & ((1 << 20) | (1 << 19))
    
    @requires_sequencer
    def cmacc_get_quadrature(self, 
                           configuration: StreamConfiguration, 
                           wait_for_completion: bool = True,
                           imag=False):
        """
        Get a quadrature of the CMACC value. By default, we'll wait for the 
        CMACC value to be available and then return the quadrant information
        in a way which optimizes latency (because the bus address for 
        checking completion is the same for checking quadrant, we don't need
        to incur the bus latency overhead a second time). Otherwise, a regular
        bus read will be performed with all typical latency overheads.
        """
        
        if wait_for_completion:
            with self.sequencer().repeat_until(self.cmacc_done(configuration)):
                pass
            
        module_name = f"module{configuration.input_switch_slave}_registers"    
        registers = self._firmware.sequencer_bus_decoder[module_name].address().value()
        latency = 0 if wait_for_completion else self._bus_latency(module_name)
        return self.sequencer().bus_read(registers+imag, latency=latency)
    
    @requires_sequencer
    def cmacc_load(self, 
                    configuration: StreamConfiguration, 
                    value: complex = 0):
        """
        Load a value into the accumulator of the given CMACC.
        """
        if configuration.module != "cmacc":
            raise TypeError(f"The StreamConfiguration provided to"
                            f" load_cmacc must represent a"
                            f" CMACC module (received configuration for module"
                            f" type {configuration.module})")
        
        module_name = f"module{configuration.input_switch_slave}_registers"    
        registers = self._firmware.sequencer_bus_decoder[module_name].address().value()
        self.sequencer().bus_write(address=registers, data=value.real)
        self.sequencer().bus_write(address=registers+1, data=value.imag)

        
    @DMASynchronizer.synchronized(DMASynchronizer.BARRIER, "channel_synchronizer")
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

    # -------------- CONVENIENCE FUNCTIONS FOR THE SEQUENCER ----------- #

    @requires_sequencer
    def reset_all_streams(self):
        for idx,module_dict in enumerate(self._firmware["stream_processing_path"]["modules"]):
            address = self._firmware.sequencer_bus_decoder[f"module{idx}_s2mm_datamover_controller"].address().value()
            self.sequencer().bus_write(address=address+2, data=0x80000000)
            
            # Reset the module
            if module_dict["kind"] == "adder":
                address = self._firmware.sequencer_bus_decoder[f"module{idx}_registers"].address().value()
                self.sequencer().bus_write(address=address, data=(1 << 2))
            elif module_dict["kind"] == "dsp":
                address = self._firmware.sequencer_bus_decoder[f"module{idx}_registers"].address().value()
                self.sequencer().bus_write(address=address, data=(1 << 4))
            elif module_dict["kind"] == "cmacc":
                address = self._firmware.sequencer_bus_decoder[f"module{idx}_registers"].address().value() + 2
                self.sequencer().bus_write(address=address, data=(1 << 24))

        for i in range(20):
            self.sequencer().nop()
        
    @requires_sequencer
    def stream_reset(self, configuration: StreamConfiguration = None):
        """
        Reset the datamover controller, module, and any associated FIFOs.
        """
        # Reset the DataMover controller
        if configuration is None: 
            configurations = self._stream_configurations
        else:
            configurations = [configuration]
            
        for cfg in configurations:
            address = self._firmware.sequencer_bus_decoder[f"{cfg.output_datamover()}_controller"].address().value()
            self.sequencer().bus_write(address=address+2, data=0x80000000)
            
            # Reset the module
            if cfg.module_resource.kind == "adder":
                address = self._firmware.sequencer_bus_decoder[f"module{cfg.input_switch_slave}_registers"].address().value()
                self.sequencer().bus_write(address=address, data=(1 << 2))
            elif cfg.module_resource.kind == "dsp":
                address = self._firmware.sequencer_bus_decoder[f"module{cfg.input_switch_slave}_registers"].address().value()
                self.sequencer().bus_write(address=address, data=(1 << 4))
            elif cfg.module_resource.kind == "cmacc":
                address = self._firmware.sequencer_bus_decoder[f"module{cfg.input_switch_slave}_registers"].address().value() + 2
                self.sequencer().bus_write(address=address, data=(1 << 24))

    @requires_sequencer
    def stream_count(self, configuration: StreamConfiguration):
        """
        Retrieve the number of status words produced for the DataMover in the 
        provided stream configuration.

        :param configuration: Configuration to check
        :type configuration: :class:`StreamConfiguration`
        """
        datamover_name = configuration.output_datamover() + "_controller"
        address = self._firmware.sequencer_bus_decoder[datamover_name].address().value() + 1
        return self._active_sequencer.bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status count for {datamover_name}",
                                        latency=self._bus_latency(datamover_name))
    
    @requires_sequencer
    def stream_total_bytes_transferred(self, configuration: StreamConfiguration):
        """
        Retrieve the number of status words produced for the DataMover in the 
        provided stream configuration.

        :param configuration: Configuration to check
        :type configuration: :class:`StreamConfiguration`
        """
        datamover_name = configuration.output_datamover() + "_controller"
        address = self._firmware.sequencer_bus_decoder[datamover_name].address().value() + 2
        return self.sequencer().bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status count for {datamover_name}",
                                        latency=self._bus_latency(datamover_name))  
    
    @requires_sequencer
    def stream_set_offset(self, configuration: StreamConfiguration, offset):
        """
        Apply an offset for a DataMover controller.
        """
        datamover_name = f"{configuration.output_datamover()}_controller"
        bus_address_base = self._firmware.sequencer_bus_decoder[datamover_name].address().value()
        self._active_sequencer.bus_write(address=bus_address_base+3, 
                                         data=offset,
                                         comment=f"Set offset for"
                                                 f" {datamover_name}")
                    
    @requires_sequencer
    def channel_trigger(self, *channels):
        """
        Trigger the DMAs associated with the provided channels.

        :param channels: List of channels
        """
        mask = 0
        for channel in channels:
            mask |= self.get_dma(channel).mask

        dma_trigger_device = self._firmware.sequencer_bus_decoder["dma_trigger"]
        self.sequencer().bus_write(address=dma_trigger_device.address().value(),
                                 data=mask,
                                 comment="DMA trigger")
        
    @requires_sequencer
    def channel_block(self, *channels):
        """
        Wait until the DMAs for the specified channels are not running.
        """
        mask = 0
        for channel in channels:
            mask |= self.get_dma(channel).mask

        dma_running_device = self._firmware.sequencer_bus_decoder["dma_running"]
        dma_running = self.sequencer().bus_read(address=dma_running_device.address().value(),
                                                      latency=self._bus_latency("dma_running"))
        with self.sequencer().repeat_until(dma_running & mask == 0):
            pass
        
    @requires_sequencer
    def channel_reset(self, channel):
        """
        Reset the DMAs associated with the provided channel
        """
        dma_name = f"{'dac' if channel.is_dac else 'adc'}{channel.num()}_dma"
        dma_regs_address = self._firmware.sequencer_bus_decoder[dma_name].address().value() + 1
        self.sequencer().bus_write(address=dma_regs_address,
                                 data=0x00000001,
                                 comment=f"Reset DMA {dma_name}")
        
    @requires_sequencer
    def channel_occupancy(self, channel):
        """
        Get the number of commands queued for the DMA of the given channel.

        :param channel: Channel to check
        :type channel: :class:`Channel`
        """

        dev_name = f'{"dac" if channel.is_dac else "adc"}{channel.num()}_dma'
        device = self._firmware.sequencer_bus_decoder[dev_name]

        bus_op = self.sequencer().bus_read(device.address().value(), 
                                                 latency=self._bus_latency(dev_name))
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

        return self.sequencer().bus_read(bus_address, 
                                        latency=self._bus_latency("dma_running"))

    # -------------- RUNTIME UTILITIES ----------- #
    
    def run(self, configure_streams=True, block=True):
        """
        Assemble, load, and run a sequence on Acadia hardware.
        Significant speedups may be achieved if reassembly is not
        required.
        
        :param block: If `True`, execution will block until the sequencer
            signals completion.
        """

        if configure_streams:
            # Disconnect all of the switch ports so that they can be properly assigned
            # (If we don't disconnect a previous connection, it may not be properly applied
            # since assignment priority is determined by master number, not assignment order;
            # see the description of the MI_MUX registers in the AXI4-Stream Switch IP)
            self._stream_processing_path_input_switch.disconnect()
            self._ADC_input_switch.disconnect()
            for cfg in self._stream_configurations:
                # logger.debug(f"Applying stream configuration {cfg}")
                self.configure_stream(cfg)
                
        # logger.debug("Running sequencer")
        
        # self.sequencer_reset()
        # self.sequencer_run()
        utils.sequencer_halt_and_reset()
        utils.sequencer_run()
        
        if block:
            utils.sequencer_complete()
            # logger.debug("Sequencer completed")

    def configure_stream(self, configuration: StreamConfiguration):
        """
        Configure the stream processing path according to a stream description.
        
        :param stream: Stream configuration to apply
        :type stream: :class:`StreamConfiguration`
        """
        self._stream_processing_path_input_switch.connect(configuration.input_switch_slave, 
                                                          configuration.input_switch_master)
        
        if configuration.adc_switch_master is not None:
            self._ADC_input_switch.connect(configuration.adc_switch_slave, 
                                           configuration.adc_switch_master)
        
    def compile(self, sequence, overwrite=False, output_directory: str = None):
        """
        Compiles the programs for all internally-stored :class:`Processor` 
        objects.
        """
        retval = self.sequence(sequence)
        
        for s in self._sequencer_type.instances:
            s.compile_all(overwrite)
        for dma in self._dac_dmas:
            dma.compile_all(overwrite)
        for dma in self._adc_dmas:
            dma.compile_all(overwrite)

        outfilename = os.path.join(output_directory, "compiled.log") if output_directory is not None else "compiled.log"
        with open(outfilename, "w") as outfile:
            outfile.write(self.sequencer_pprint())    

        return retval

    def assemble(self, output_directory: str = None) -> dict[str,list[int]]:
        """
        Assembles instruction memory for the sequencer and all DMAs. A dictionary
        is produced that contains the memory segments for all required memory and
        a byte offset within the region.
        """

        assembled = {}

        for dma_type,dma_list in [("DAC", self._dac_dmas), ("ADC", self._adc_dmas)]:
            for idx_dma,dma in enumerate(dma_list):
                if len(dma._compiled_program) > 0:
                    logger.debug(f"Assembling {dma_type}{idx_dma} DMA program with length {len(dma._compiled_program)}")
                    assembled_bin = bytearray(len(dma._compiled_program) * 8)
                    for idx_instr,instr in enumerate(dma._compiled_program):
                        assembled_bin[idx_instr*8 : (idx_instr+1)*8] = instr.assemble()
                    
                    assembled[f"{dma_type}{idx_dma}@{0:08X}"] = hexlify(assembled_bin).decode("ascii")
            
        # Assemble the sequencer last so that if any DMA descriptors are resolved to have zero length,
        # the instruction driving them will be removed above
        num_sequencer_instructions = sum([len(s._compiled_program) for s in self._sequencer_type.instances])
        logger.debug(f"Assembling sequencer program with {num_sequencer_instructions} instructions")
                
        address = 0
        for s in self._sequencer_type.instances:
            assembled_bin = bytearray(len(s._compiled_program) * 16)
            key = f"seq@{address:08X}"
            for instr in s._compiled_program:
                assembled_bin[address : address+16] = instr.assemble()
                address += 16
            
            assembled[key] = hexlify(assembled_bin).decode("ascii")

        outfilename = os.path.join(output_directory, "assembled.log") if output_directory is not None else "assembled.log"
        with open(outfilename, "w") as outfile:
            json.dump(assembled, outfile, indent=0)
            
        return assembled
    
    def load(self, inp: Union[dict[str,list[int]], str, None] = None) -> None:
        """
        Loads assembled programs into memory. If the input argument is a dict,
        it must have the format as produced by assemble(). If the input is a str,
        an assembled JSON file is loaded from the directory specified by it. 
        If the input is None, the data is loaded from an assembled JSON in the 
        current working directory.
        """

        if inp is None or isinstance(inp, str):
            filename = os.path.join(inp, "assembled.log") if inp is not None else "assembled.log"
            if not os.path.exists(filename):
                raise ValueError(f"Assembled JSON not found at {filename}")
            with open(filename, "r") as file:
                inp = json.load(file)
        elif not isinstance(inp, dict):
            raise TypeError(f"Invalid type of input data {type(inp)}")

        for segment,data in inp.items():
            region_str,offset_str = segment.split("@")
            offset = int(offset_str, base=16)
            if region_str.startswith("ADC"):
                channel = int(region_str[len("ADC"):])
                buffer = self._adc_dma_descriptor_memory[channel]
                buffer_name = f"ADC{channel} descriptor"
            elif region_str.startswith("DAC"):
                channel = int(region_str[len("DAC"):])
                buffer = self._dac_dma_descriptor_memory[channel]
                buffer_name = f"DAC{channel} descriptor"
            elif region_str.startswith("seq"):
                buffer = self._sequencer_instruction_memory
                buffer_name = "sequencer instruction"
            else:
                raise ValueError(f"Unrecognized segment {segment}")
            
            assembled_bin = unhexlify(str.encode(data, "ascii"))
            logger.debug(f"Loading {len(assembled_bin)} bytes into {buffer_name} memory at offset {offset}")
            buffer[offset:offset+len(assembled_bin)] = assembled_bin
                        
    def assemble_simulation(self) -> str:
        """
        Identical to :meth:`assemble`, but creates a string for loading memory
        in Verilog testbenches connected to the Zynq Ultrascale AXI VIP.
        """
        sim_string = ""
        for s in self._sequencer_type.instances:
            for idx_instr,instr in enumerate(s._compiled_program):
                assembled = ''.join(reversed([f'{b:02X}' for b in instr.assemble()]))
                address = (s._resource_id + idx_instr)*16
                sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{address + self._firmware['sequencer_instruction_memory']['address']: X}, 16, 128'h{assembled}, resp);\n"
    
        for i,dma in enumerate(self._dac_dmas):
            for idx_instr,instr in enumerate(dma._compiled_program):
                assembled = f"{instr.assemble():016X}"
                sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{self._firmware['dac_dma_descriptor_memory']['address'] + i*(self._firmware['dac_dma_descriptor_memory']['size_bits']//8) + idx_instr*8: X}, 8, 64'h{assembled}, resp);\n"
            
        for i,dma in enumerate(self._adc_dmas):
            for idx_instr,instr in enumerate(dma._compiled_program):
                assembled = f"{instr.assemble():016X}"
                sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{self._firmware['adc_dma_descriptor_memory']['address'] + i*(self._firmware['adc_dma_descriptor_memory']['size_bits']//8) + idx_instr*8: X}, 8, 64'h{assembled}, resp);\n"      
            
        return sim_string

    def sequencer_pprint(self) -> str:
        """
        :return: a "pretty" representation of the programs compiled
            for the sequencer
        :rtype: str
        """
        idx = 0
        output = ""
        for idx_seq,s in enumerate(self._sequencer_type.instances):
            output += f"---- Program {idx_seq} ----\n"
            for instr in s._compiled_program:
                output += f"{idx:04X}: {instr.pprint()}\n"
                idx += 1
            output += "\n"

        return output

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

        gpio = self._firmware["ps_gpio"]["sysfs_offset"] + 95
        PSGPIO.sysfs_export(gpio)
        PSGPIO.sysfs_set_direction(gpio, "out")
        PSGPIO.sysfs_write(gpio, 0)
        time.sleep(0.1)
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
            return proc.bus_read(addr, latency=self._bus_latency(f"ps_gpio{port}"))
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
                if cache_self.__array_interface__ is None:
                    raise AttributeError(f"Attempted to get item from unattached memory.")
                return cache_self._array[key]
            elif isinstance(proc, Sequencer):
                base_address = self._firmware.sequencer_bus_decoder["cache"].address().value()
                return proc.bus_read(base_address + cache_self.index + key, 
                                     latency=self._bus_latency("cache"))
            return Operation("getitem", cache_self, key)
            
        def _cache_setitem(cache_self, key, value):
            proc = Processor.active_processor()
            if proc is None:
                if cache_self.__array_interface__ is None:
                    raise AttributeError(f"Attempted to set item of unattached memory.")
                cache_self._array[key] = value
            elif isinstance(proc, Sequencer):
                base_address = self._firmware.sequencer_bus_decoder["cache"].address().value()
                proc.bus_write(address=base_address + cache_self.index + key,
                               data=value,
                               comment=f"Write to cache address {key}")
            else:
                raise TypeError(f"Unable to access cache on processor {proc}.")
        
        self.CacheArray = ManagedMemory("CacheArray", 
            (), 
            {"OPERATORS": [], 
             "__getitem__": _cache_getitem, 
             "__setitem__": _cache_setitem},
            base_address=self._firmware["sequencer_cache_memory"]["address"],
            alignment=4,
            memory_size=self._firmware["sequencer_cache_memory"]["size_bits"] // 8,
            getset=None)
        
    def _create_dac_arrays(self):
        self.DACArray = [ManagedMemory(f"DAC{i}Array", 
            (), 
            {"OPERATORS": []},
            base_address=(self._firmware[f"dac_tile{i // 4}_sample_memory"]["address"] 
                               + (i % 4)*(self._firmware[f"dac_tile{i // 4}_sample_memory"]["size_bits"] // 8)),
            alignment=self._firmware["rfdc"]["dac"]["channel_interface_width"][i] // 8,
            memory_size=self._firmware[f"dac_tile{i // 4}_sample_memory"]["size_bits"] // 8,
            getset=None) for i in range(self._firmware.NUM_DACS)]
        
    def _create_cmacc_kernel_arrays(self):
        self.CMACCKernelArray = [ManagedMemory(f"CMACC{i}KernelArray", 
            (), 
            {"OPERATORS": []},
            base_address=(self._firmware["stream_processing_path"]["cmacc_kernel_memory_controller"]["base_address"] 
                               + i*(self._firmware._max_cmacc_memory * 32 // 8)),
            alignment=4,
            memory_size=self._firmware._max_cmacc_memory * 32 // 8) for i in range(self._firmware._num_cmaccs)]
        
    def _create_pl_ddr_arrays(self):            
        self.PLDDR0Array = ManagedMemory(f"PLDDR0Array", 
            (),
            {"OPERATORS": []},
            base_address=self._firmware["memory"]["ddr4_c0"]["address"],
            memory_size=self._firmware["memory"]["ddr4_c0"]["size_bits"] // 8)
        
        self.PLDDR1Array = ManagedMemory(f"PLDDR1Array", 
            (), 
            {"OPERATORS": []},
            base_address=self._firmware["memory"]["ddr4_c1"]["address"],
            memory_size=self._firmware["memory"]["ddr4_c1"]["size_bits"] // 8)
        
    def _create_ps_ddr_arrays(self):
        self.PSDDRArray = ManagedMemory(f"PSDDRArray", 
            (),
            {"OPERATORS": []},
            base_address=0x8_0000_0000,
            memory_size=2**30)
        
    def _create_ocm_arrays(self):
        self.OCMArray = ManagedMemory(f"OCMArray", 
            (), 
            {"OPERATORS": []},
            base_address=0xFFFC_0000,
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
                # By default, the sample rate will be configured to be zero. when we attach it will be read
                dac_channel = Channel(tile=tile, block=block, is_dac=True, 
                    interface_sample_frequency = (self._firmware["clk104_pl_clk"]["freq_hz"]
                                                          * self._firmware["rfdc"]["dac"]["channel_interface_width"][tile*4 + block] // 32),
                    interface_width_bytes = self._firmware["rfdc"]["dac"]["channel_interface_width"][tile*4 + block] // 8)
                self._DAC_channels.append(dac_channel)
                
                adc_channel = Channel(tile=tile, block=block, is_dac=False,
                    interface_sample_frequency = (self._firmware["clk104_pl_clk"]["freq_hz"]
                                                          * self._firmware["rfdc"]["adc"]["channel_interface_width"][tile*4 + block] // 32),
                    interface_width_bytes = self._firmware["rfdc"]["adc"]["channel_interface_width"][tile*4 + block] // 8)
                
                self._ADC_channels.append(adc_channel)
                
    def _create_switches(self):
        self._stream_processing_path_input_switch = AXISSwitch()
        self._ADC_input_switch = AXISSwitch()
        
    def _attach_resource(self, resource_manager: ManagedMemory):
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

        if not isinstance(resource_manager, ManagedMemory):
            raise TypeError(f"Only ManagedMemory objects can be attached; received {resource_manager}")

        logger = logging.getLogger("acadia")
        logger.debug(f"Attaching resource manager {resource_manager} at"
                     f" address 0x{resource_manager._base_address:010X}"
                     f" ({resource_manager._allocation_limit} bytes)")

        m = mmap.mmap(self._mem_file, 
            resource_manager._allocation_limit, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            resource_manager._base_address)
        
        self._mem_maps.append(m)
        resource_manager.attach(m)

        # Also stash some numpy arrays in the instances for easier use later
        for inst in resource_manager.instances:
            array_interface = inst.__array_interface__
            inst._array = np.frombuffer(
                array_interface["data"], 
                dtype=np.dtype(array_interface["typestr"]),
                count=inst.size,
                offset=array_interface["offset"]).reshape(inst.shape)
        
    def _attach_memory(self, address, size, dtype=np.uint8, return_map=False):
        """
        Maps a region of memory in the physical address space of the hardware.
        
        :param address: Physical address to map
        :type address: int
        :param size: Size of the space to map in bytes
        :type size: int
        """

        logging.getLogger("acadia").debug(f"Attaching memory of size {size}"
                                          f" bytes at address 0x{address:010X}"
                                          f" with dtype {dtype}")

        m = mmap.mmap(self._mem_file, 
            size, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            address)
        self._mem_maps.append(m)
        
        if return_map:
            return m
        
        return np.frombuffer(m, dtype=dtype)

    def _command_datamover(self, 
                           datamover_name: str, 
                           address: Union[int, Symbol], 
                           size: Union[int, Symbol], 
                           tag: int = 0xA, 
                           incr: bool = True):
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

        if isinstance(size, int):
            if size > 2**23:
                raise ValueError(f"Size must be less than 8 MB; received {size}.")
        elif isinstance(size, Symbol) and (size.value_type() == int):
            if size.assigned() and size.value() > 2**23:
                raise ValueError(f"Size must be less than 8 MB; received {size}.")
            else:
                logger.warning("Unable to verify size of transfer;"
                                 "ensure that the size is less than 8 MB.") 
        else:
            logger.warning("Unable to verify size of transfer;"
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
        
        # TODO: is there a way to get from the firmware config that the address bus is 40 bits rather than hardcode it?
        misc_reg |= ((address >> 32) & 0xFF) << 14

        # Configure the DataMover controller (the last bus write will 
        # push the complete command into the command FIFO)
        bus_address_base = self._firmware.sequencer_bus_decoder[f"{datamover_name}_controller"].address().value()
        self._active_sequencer.bus_write(address=bus_address_base+2, 
                                         data=misc_reg,
                                         comment=f"Misc configuration for DataMover"
                                                 f" {datamover_name}")
        self._active_sequencer.bus_write(address=bus_address_base+1, 
                            data=size,
                            comment=f"Transfer size for DataMover {datamover_name}")
        self._active_sequencer.bus_write(address=bus_address_base, 
                            data=(address & 0xFFFFFFFF),
                            comment=f"Base address and dispatch for DataMover {datamover_name}")
               
    def _bus_latency(self, port: str) -> int:
        """
        Get the latency for a port on the sequencer's bus, taking into account
        any pipelining configured in the firmware.

        :param port: Bus port name. Must either be a key in the 
            ``SEQUENCER_BUS``  section of the firmware configuration, or
            ``cache``\.
        :type port: str
        """

        if port not in self._firmware.sequencer_bus_decoder:
            raise ValueError(f"Unrecognized bus port {port}")

        # One cycle to load the bus registers in the sequencer
        latency = 1

        # One cycle if the bus decoder itself has a pipelined MISO
        if self._firmware["sequencer_bus"]["decoder_pipeline_miso"]:
            latency += 1
        
        if "datamover_controller" in port:
            # Datamover controllers have a read latency of 1 because its MISO is driven
            # in a synchronous process, in addition to any bus pipelining
            latency += 1
        elif port == "cache":
            # One additional cycle minimum because the memory has a read latency of 1
            # even before any pipelining because it's a synchronous memory
            latency += 1
            latency += self._firmware["sequencer_cache_memory"]["bus_port_input_pipeline"]
            latency += self._firmware["sequencer_cache_memory"]["bus_port_output_pipeline"]

        # If the bus decoder has a pipeline stage for this device, add a stage
        if self._firmware.sequencer_bus_decoder.is_pipelined(port):
            latency += 1
            
        return latency
    
    def _request_stream_configuration(self, 
                                      input_source: Union[Channel, str], 
                                      module: str) -> StreamConfiguration:
        """
        Request configuration parameters for a stream. Streams are uniquely 
        determined by their input source and by the module that processes them.
        The :class:`Acadia` object will store an internal list of all 
        :class:`StreamConfiguration` objects created with this method and will
        reuse them when an identical configuration is requested.
        
        :param input_source: The source of data driving the stream. If this is 
            a :class:`Channel` object (which must be an ADC), then the default
            behavior will depend on whether the specified ADC is directly 
            connected to the input switch. If a string, it is understood to
            specify the kind of input to request.
        :type input_source: :class:`Channel` or str
        :param module: The kind of stream processing module to use. Must be one
            of "adder", "dsp", or "memory".
        :type module: str
        """
        logger.debug(f"Stream requested for input {input_source} with module type {module}")
        for cfg in self._stream_configurations:
            if cfg.input_source == input_source and cfg.module == module:
                logger.debug(f"Reusing existing configuration {cfg}")
                return cfg
            
        # Establish some hidden fields for mapping requested inputs and 
        # modules to internal switch port numbers
        input_resource = None
        module_resource = None
        adc_switch_master = None
        adc_switch_slave = None
        
        if isinstance(input_source, Channel):
            if input_source.is_dac:
                raise ValueError("Input source channels must be ADCs.")
            
            # We now need to determine which switch input port to use
            # First, check if the ADC is directly connected to the input switch
            name = f"ADC{input_source.num()}"
            if name in self._stream_input_resources:
                input_resource = self._stream_input_resources[name]()
            else:
                input_resource = self._stream_input_resources["ADC_switch"]()                
                adc_switch_slave = input_resource._resource_id
                
                # Figure out which master for the ADC switch it is
                adc_switch_inputs = list(range(self._firmware.NUM_ADCS))
                for inp in self._firmware["stream_processing_path"]["inputs"]:
                    if inp["kind"] == "ADC":
                        adc_switch_inputs.remove(inp["channel"])
                
                # This will raise an exception if it's not in the list
                adc_switch_master = adc_switch_inputs.index(input_source.num())
            
        elif isinstance(self.input_source, str):
            input_resource = self._stream_input_resources[input_source]()
            
        else:
            raise TypeError(f"Invalid type of input source ({type(input_source)})")
        
        input_switch_master = input_resource.switch_port()
        
        # Now determine which module to use
        if not isinstance(module, str):            
            raise TypeError(f"Invalid type for specifying module: {type(module)}")
        
        module_resource = self._stream_module_resources[module]()
        input_switch_slave = module_resource.switch_port()
        
        cfg = StreamConfiguration(input_source, 
                                   module, 
                                   input_resource, 
                                   module_resource, 
                                   adc_switch_master, 
                                   adc_switch_slave, 
                                   input_switch_master, 
                                   input_switch_slave)

        logger.debug(f"Allocated stream of type {module}, routing incoming data"
                    f" on input switch master {input_switch_master} to"
                    f" slave {input_switch_slave}.")
        if isinstance(input_source, Channel):
            logger.debug(f"ADC switch set to route incoming data on ADC"
                        f" master {adc_switch_master} (ADC {input_source.num()})"
                        f" to switch output {adc_switch_slave}")
        
        self._stream_configurations.append(cfg)
        
        return cfg
        