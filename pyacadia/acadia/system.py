__all__ = ["Acadia", "ChannelSynchronizer"]

import os
import mmap
import time
import copy
from functools import wraps

import numpy as np

from .compiler import ManagedResource, ManagedMemory, Processor, Synchronizer, Symbol, Operation
from .sequencer import Sequencer
from .dma import DMA
from .channel import Channel
from .peripherals import RFClk, PSGPIO, ZDMA, AXISSwitch
from .firmware import Firmware

class ChannelSynchronizer(Synchronizer):
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

    STREAM = 1
    NCO_FREQUENCY = 2
    NCO_PHASE = 3
    NCO_PHASE_RESET = 4
    VOP = 5
    DSA = 6
    TDD = 7

    def __init__(self, firmware, dma_block_latency, allow_standalone=False):
        self._firmware = firmware
        self._dma_block_latency = dma_block_latency
        super().__init__(allow_standalone)
    
    def __call__(self, *args, **kwargs):
        if not isinstance(Processor.active_processor(), Sequencer):
            raise TypeError("Synchronization is only supported for contexts of"
                            " a `Sequencer` object. Either enter an appropriate"
                            " context to enforce synchronization or call the"
                            " appropriate method to act directly on the"
                            " hardware.")
            
        self._dma_trigger = kwargs.pop("trigger", True)
        self._dma_block = kwargs.pop("block", self._dma_trigger) # don't block if we don't trigger
        self._nco_pl_event = kwargs.pop("nco_pl_event", False)
        return super().__call__(*args, **kwargs)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Get a reference to the Sequencer
        proc = Processor.active_processor()
        
        # Keep track of the aggregate values of all the calls
        dma_mask = 0
        nco_phase_reset = 0
        nco_update_enables = [0]*8
        nco_update_request = 0
        vop_dsa_update_reg = 0
            
        # The DAC VOP codes each have their own register but the DSA codes
        # are stored together by tile, so we need to aggregate
        tile_dsa_codes = [0]*4
        
        tdd_mode_set_reg = 0
        tdd_mode_clear_reg = 0
        
        for call in self._calls:
            function,acadia,args,kwargs = call.values()

            channel = kwargs["channel"] if "channel" in kwargs else args[0]
            if not isinstance(channel, Channel):
                raise TypeError(f"Unable to identify channel (received {channel}).")

            bit_position = channel.num + (16 if not channel.is_dac else 0)
                
            if function == ChannelSynchronizer.STREAM:
                # Figure out which bits will contribute to the mask
                if channel.is_dac:
                    # If it's a DAC, the bit position is just the channel number
                    dma_mask |= 1 << channel.num
                else:
                    # If it's an ADC, the DMA object will be a ManagedResource
                    # with an offset depending on whether it's for an ADC or CMACC
                    dma = channel.dma
                    dma_mask |= 1 << (type(dma).DMA_NUM_OFFSET + dma._resource_id)
                
            elif function == ChannelSynchronizer.NCO_FREQUENCY:
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

            elif function == ChannelSynchronizer.NCO_PHASE:
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

            elif function == ChannelSynchronizer.NCO_PHASE_RESET:
                if isinstance(proc, Sequencer):
                    # The bit position for the channel in the update request and 
                    # phase reset registers
                    nco_update_request |= 1 << ((channel.tile+4) if not channel.is_dac else channel.tile)

                    # Which register for setting the update enable pins does this 
                    # channel belong to?
                    update_enable_reg = 4*channel.tile + (4 if not channel.is_dac else 0)

                    nco_phase_reset |= 1 << bit_position
                    nco_update_enables[update_enable_reg] |= (1 << 5) << (6*channel.block)
                
            elif function == ChannelSynchronizer.VOP:
                if isinstance(proc, Sequencer):
                    vop_dsa_update_reg |= 1 << (4*channel.tile + channel.block)
                
            elif function == ChannelSynchronizer.DSA:
                if isinstance(proc, Sequencer):
                    vop_dsa_update_reg |= 1 << (16 + channel.tile)
                    data = args[0] << (channel.block*5)
                    mask = 0b11111 << (channel.block*5)
                    tile_dsa_codes[channel.tile] = (tile_dsa_codes[channel.tile] & ~mask) | data
                
            elif function == ChannelSynchronizer.TDD:
                if isinstance(proc, Sequencer):
                    if args[0]:
                        tdd_mode_set_reg |= 1 << bit_position
                    else:
                        tdd_mode_clear_reg |= 1 << bit_position
                else:
                    raise TypeError("TDD mode may only be controlled by the"
                                    " Sequencer. Enter the corresponding"
                                    " context to control TDD mode.")
                
        # Store the mask so that if we don't block, we can know which DMAs were triggered
        self.dma_mask = dma_mask
        
        if isinstance(proc, Sequencer):
            rts_address = self._firmware.rfdc_rts_regs.address().value()

            # If any DMAs were triggered, add instructions to do so now
            if dma_mask != 0:
                if self._dma_trigger:
                    # The only parent object that we could have had was an Acadia object,
                    # so we know on which object we should call dma_trigger
                    dma_trigger_device = self._firmware.sequencer_bus_decoder["dma_trigger"]
                    proc.bus_write(address=dma_trigger_device.address().value(),
                                   data=dma_mask,
                                   comment="Trigger DMAs")

                if self._dma_block:
                    # Wait until all the DMAs in the mask have completed
                    dma_running_device = self._firmware.sequencer_bus_decoder["dma_running"]
                    proc.bus_read(dma_running_device.address().value(),
                                latency=self._dma_block_latency)
                    with proc.wait_until(proc.bus_read() & dma_mask == 0):
                        pass

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
                with proc.wait_until(proc.bus_read(rts_address) & (1 << 1) != 0):
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
                with proc.wait_until(proc.bus_read(rts_address) & m == 0):
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
                with proc.wait_until(proc.bus_read(rts_address) & 0xFFFF == 0):
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

        # A dictionary for storing assembled code, which maps memoryviews to
        # the bytes that should be loaded into them
        self._assembled = {}
        
        # Create a list for keeping track of all Sequencer sequences
        self._sequencer_type = ManagedResource("Sequence", (Sequencer,), {})
        
        # We'll adjust the allocation index so that it actually corresponds to
        # locations in instruction memory
        # We'll reserve location 0 for jumping to the start of the defined 
        # sequence
        self._sequencer_type._allocation_index = 0
        
        # When we enter contexts, keep track of the active sequencer
        self._active_sequencer = None

        # Create a synchronizer for channel actions
        self.synchronizer = ChannelSynchronizer(self._firmware, 
                                                self.get_bus_latency("DMA_RUNNING_DATAPORT"),
                                                allow_standalone=True)
                
        # Make DMAs
        DACDMA = type("DACDMA", (DMA,), {"DMA_NUM_OFFSET": 0})
        self._dac_dmas = [DACDMA() for i in range(16)]
        
        # Create DMAs for ADCs and CMACCs
        # Also patch in some attributes for storing the offsets within DMA registers
        # for the bits corresponding to these DMAs
        def dma_init(dma_self, physical_channel):
            dma_self.physical_channel = physical_channel
            super(type(dma_self), dma_self).__init__()
            
        self._ADCDMA = ManagedResource("ADCDMA", (DMA,), {"DMA_NUM_OFFSET": 16, "__init__": dma_init}, allocation_limit=4)
        
        self._CMACCDMA = ManagedResource("CMACCDMA", (DMA,), {"DMA_NUM_OFFSET": 20,
                                                              "parameters": ["physical_channel"],
                                                              "allocation_limit": 4})
        
        def zdma_postinit(zdma_self):
            zdma_self.fci_bus_address = self._firmware.sequencer_bus_decoder["zdma_controller"].address().value()
            zdma_self.channel = zdma_self._resource_id
            super().__post_init__()
        
        self._ZDMA = ManagedResource("ZDMAResource", 
                                         (ZDMA,), 
                                         {"__post_init__": zdma_postinit,
                                          "OPERATORS": []},
                                         allocation_limit=8)
        
        self._ADC_AXIS_switch = AXISSwitch()
        
        # Create channel objects that abstract the channels of this board
        # so that when parameters are updated, everything that depends on
        # the channel receives the update
        self._DAC_channels = []
        self._ADC_channels = []
        for tile in range(4):
            for block in range(4):
                dac_channel = Channel(tile=tile, block=block, is_dac=True)
                dac_channel.analog_sample_frequency = 6e9
                dac_channel.interface_sample_frequency = 1e9
                dac_channel.interface_width_bytes = 16
                
                self._DAC_channels.append(dac_channel)
                
                adc_channel = Channel(tile=tile, block=block, is_dac=False)
                adc_channel.analog_sample_frequency = 2e9
                adc_channel.interface_sample_frequency = 1e9
                adc_channel.interface_width_bytes = 16
                
                self._ADC_channels.append(adc_channel)
                
        self._create_cache()
        self._create_dac_arrays()
        self._create_cmacc_kernel_arrays()
        self._create_pl_ddr_arrays()
        self._create_ps_ddr_arrays()
        self._create_ocm_arrays()
        
    def attach(self):
        """
        Maps system memory and connects to hardware drivers.
        """

        self._mem_file = os.open("/dev/mem", os.O_SYNC | os.O_RDWR)
        self._mem_maps = []
        
        self._attach_resource(self.CacheArray, mem_cast=np.uint32)
        
        self._sequencer_instruction_memory = self._attach_memory(
            address=self._firmware["SEQUENCER_INSTRUCTION_MEMORY"]["ADDRESS"],
            size=self._firmware["SEQUENCER_INSTRUCTION_MEMORY"]["SIZE_BITS"] // 8)  
        
        self._dac_dma_descriptor_memory = [self._attach_memory(
            address=(self._firmware["DAC_DMA_DESCRIPTOR_MEMORY"]["ADDRESS"] 
                    + i*(self._firmware["DAC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 8)),
            size=self._firmware["DAC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 8,
            mem_cast=np.uint64) for i in range(16)]
                
        self._adc_dma_descriptor_memory = [self._attach_memory(
            address=(self._firmware["ADC_DMA_DESCRIPTOR_MEMORY"]["ADDRESS"] 
                    + i*(self._firmware["ADC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 8)),
            size=self._firmware["ADC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 8,
            mem_cast=np.uint64) for i in range(4)]
        
        self._cmacc_dma_descriptor_memory = [self._attach_memory(
            address=(self._firmware["CMACC_DMA_DESCRIPTOR_MEMORY"]["ADDRESS"] 
                    + i*(self._firmware["CMACC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 8)),
            size=self._firmware["CMACC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 8,
            mem_cast=np.uint64) for i in range(4)]
            
        for dac_mem in self.DACArray:
            self._attach_resource(dac_mem)
            
        for cmacc_kernel_mem in self.CMACCKernelArray:
            self._attach_resource(cmacc_kernel_mem)
                
        self._attach_resource(self.PLDDR0Array)
        self._attach_resource(self.PLDDR1Array)
        self._attach_resource(self.PSDDRArray)
            
        # Connect to the RFDC driver and initialize
        Channel.RFDC_init()
        
        RFClk.init(self._firmware["PS_GPIO"]["SYSFS_OFFSET"] + self._firmware["PS_GPIO"]["CLK104_SPI0"])
        
        # Connect to the ADC AXIS switch
        self._ADC_AXIS_switch.attach(self._attach_memory(
            address=self._firmware["ADC_AXIS_SWITCH"]["AXI_ADDRESS"], 
            size=self._firmware["ADC_AXIS_SWITCH"]["AXI_SIZE_BITS"] // 8,
            mem_cast=np.uint32))
        
        # Connect to the PS GDMA
        for instance in self._ZDMA.instances:
            instance.attach(self._attach_memory(
                address=0xFD50_0000 + (instance._resource_id*0x1_0000),
                size=0x1_0000))
            
        # Connect to the GPIO registers and store sequencer bus addresses for the GPIO dataports
        self._psgpio_mem = self._attach_memory(0xFF0A0000, 0x400, mem_cast=np.uint32)

        # Connect to the clock wizard
        # self.clk_wiz = self._attach_memory(address=self._firmware["CLK_WIZ"]["AXI_ADDRESS"], 
        #                                    size=self._firmware["ADC_AXIS_SWITCH"]["AXI_SIZE_BITS"] // 8)  
            
        # Configure and connect to the sysfs interface for various GPIO        
        self._sequencer_gpio = self._firmware["PS_GPIO"]["SYSFS_OFFSET"] + self._firmware["PS_GPIO"]["SEQUENCER_RUN"]
        PSGPIO.sysfs_export(self._sequencer_gpio)
        PSGPIO.sysfs_set_direction(self._sequencer_gpio, "out")
        PSGPIO.sysfs_write(self._sequencer_gpio, 0)
        
        self._sequencer_nrst = self._firmware["PS_GPIO"]["SYSFS_OFFSET"] + self._firmware["PS_GPIO"]["SEQUENCER_NRST"]
        PSGPIO.sysfs_export(self._sequencer_nrst)
        PSGPIO.sysfs_set_direction(self._sequencer_nrst, "out")
        PSGPIO.sysfs_write(self._sequencer_nrst, 0)

        self._ddr4_c0_sys_rst_gpio = self._firmware["PS_GPIO"]["SYSFS_OFFSET"] + self._firmware["PS_GPIO"]["DDR4_C0_SYS_RST"]           
        PSGPIO.sysfs_export(self._ddr4_c0_sys_rst_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c0_sys_rst_gpio, "out")
        PSGPIO.sysfs_write(self._ddr4_c0_sys_rst_gpio, 0)

        self._ddr4_c1_sys_rst_gpio = self._firmware["PS_GPIO"]["SYSFS_OFFSET"] + self._firmware["PS_GPIO"]["DDR4_C1_SYS_RST"]            
        PSGPIO.sysfs_export(self._ddr4_c1_sys_rst_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c1_sys_rst_gpio, "out")
        PSGPIO.sysfs_write(self._ddr4_c1_sys_rst_gpio, 0)

        self._ddr4_c0_cal_cplt_gpio = self._firmware["PS_GPIO"]["SYSFS_OFFSET"] + self._firmware["PS_GPIO"]["DDR4_C0_CAL_CPLT"]           
        PSGPIO.sysfs_export(self._ddr4_c0_cal_cplt_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c0_cal_cplt_gpio, "in")

        self._ddr4_c1_cal_cplt_gpio = self._firmware["PS_GPIO"]["SYSFS_OFFSET"] + self._firmware["PS_GPIO"]["DDR4_C1_CAL_CPLT"]           
        PSGPIO.sysfs_export(self._ddr4_c1_cal_cplt_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c1_cal_cplt_gpio, "in")

        self._clk_wiz_locked = self._firmware["PS_GPIO"]["SYSFS_OFFSET"] + self._firmware["PS_GPIO"]["CLK_WIZ_LOCKED"]           
        PSGPIO.sysfs_export(self._ddr4_c1_cal_cplt_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c1_cal_cplt_gpio, "in")
        
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
        
        # Store this particular Sequencer instance as an instance member of the 
        # Acadia object so that helper functions of the Acadia object know to 
        # use it
        self._active_sequencer = s
        
        # Call the function to populate the sequencer object and compile it
        with s:
            func(self)
            
        self._active_sequencer = None

        s.nop()
        s.halt()
        
        # Because the sequence resource object was created before we knew its 
        # size and because we know that the size won't change from this point,
        # we can update the size of the instance and the allocation index of
        # the sequence resource
        s.size = s.Instruction.usage()
        
        return s
            
    def compile_all(self):
        """
        Compiles the programs for all internally-stored :class:`Processor` 
        objects.
        """

        for s in self._sequencer_type.instances:
            s.compile_all()
        for dma in self._dac_dmas:
            dma.compile_all()
        for dma in self._ADCDMA.instances:
            dma.compile_all()
        for dma in self._CMACCDMA.instances:
            dma.compile_all()
        
    def assemble(self, load=False, sequencer=True, dac_dmas=True, adc_dmas=True, cmacc_dmas=True):
        """
        Assembles and optionally loads instruction memory for some or all 
        internally-stored :class:`Processor` objects.

        :param load: If ``True``, will only assemble and not load memory.
        :type load: bool
        :param sequencer: If ``False``, the sequencer instructions will not be
            assembled or loaded.
        :type sequencer: bool
        :param dac_dmas: If ``False``, the DAC DMA descriptor memory will not be
            assembled or loaded.
        :type dac_dmas: bool
        :param adc_dmas: If ``False``, the ADC DMA descriptor memory will not be
            assembled or loaded.
        :type adc_dmas: bool
        :param cmacc_dmas: If ``False``, the CMACC DMA descriptor memory will not
            be assembled or loaded.
        :type cmacc_dmas: bool
        """
        
        if sequencer:
            for s in self._sequencer_type.instances:
                for idx_instr,instr in enumerate(s._compiled_program):
                    assembled = instr.assemble()
                    if load:
                        address = (s._resource_id + idx_instr)*16
                        self._sequencer_instruction_memory[address : address+16] = np.frombuffer(assembled.to_bytes(16, "little"), dtype=self._sequencer_instruction_memory.dtype)
        
        if dac_dmas:
            for i,dma in enumerate(self._dac_dmas):
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    if load:
                        self._dac_dma_descriptor_memory[i][idx_instr] = assembled
                
        if adc_dmas:
            for dma in self._ADCDMA.instances:
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    if load:
                        self._adc_dma_descriptor_memory[dma._resource_id][idx_instr] = assembled
        
        if cmacc_dmas:
            for dma in self._CMACCDMA.instances:
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    if load:
                        self._cmacc_dma_descriptor_memory[dma._resource_id][idx_instr] = assembled
                        
    def assemble_simulation(self, sequencer=True, dac_dmas=True, adc_dmas=True, cmacc_dmas=True):
        """
        Identical to :meth:`assemble`, but creates a string for loading memory
        in Verilog testbenches connected to the Zynq Ultrascale AXI VIP.
        """

        sim_string = ""
        if sequencer:
            for s in self._sequencer_type.instances:
                for idx_instr,instr in enumerate(s._compiled_program):
                    assembled = instr.assemble()
                    address = (s._resource_id + idx_instr)*16
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{address + self._firmware['SEQUENCER_INSTRUCTION_MEMORY']['ADDRESS']: X}, 16, 128'h{assembled:032X}, resp);\n"
        
        if dac_dmas:
            for i,dma in enumerate(self._dac_dmas):
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{self._firmware['DAC_DMA_DESCRIPTOR_MEMORY']['ADDRESS'] + i*(self._firmware['DAC_DMA_DESCRIPTOR_MEMORY']['SIZE_BITS']//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
                
        if adc_dmas:
            for dma in self._ADCDMA.instances:
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{self._firmware['ADC_DMA_DESCRIPTOR_MEMORY']['ADDRESS'] + dma._resource_id*(self._firmware['ADC_DMA_DESCRIPTOR_MEMORY']['SIZE_BITS']//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
        
        if cmacc_dmas:
            for i,dma in self._CMACCDMA.instances:
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{self._firmware['CMACC_DMA_DESCRIPTOR_MEMORY']['ADDRESS'] + dma._resource_id*(self._firmware['CMACC_DMA_DESCRIPTOR_MEMORY']['ADDRESS']//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
                    
        return sim_string

    def sequencer_pprint(self):
        """
        :return: a "pretty" representation of the programs compiled
            for the sequencer
        :rtype: str
        """

        for idx_seq,s in enumerate(self._sequencer_type.instances):
            print(f"---- Program {s} ----")
            for idx,instr in enumerate(s._compiled_program):
                print(f"{idx:04X}: {instr.pprint()}")
                        
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
    
    @Synchronizer.synchronized(ChannelSynchronizer.NCO_FREQUENCY, "synchronizer")
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
    
    @Synchronizer.synchronized(ChannelSynchronizer.NCO_PHASE, "synchronizer")
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

    @Synchronizer.synchronized(ChannelSynchronizer.NCO_PHASE_RESET, "synchronizer")
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
        # d["clk_wiz_divclk_divide"] = self.clk_wiz[0x200]
        # d["clk_wiz_fbout_mult"] = self.clk_wiz[0x201]
        # d["clk_wiz_fbout_frac"] = int.from_bytes(self.clk_wiz[0x203:0x202], 'little') & (2**10 - 1)
        # d["clk_wiz_vco_frequency_over_input_frequency"] = (d["clk_wiz_fbout_mult"] + 1e-3*d["clk_wiz_fbout_frac"]) / d["clk_wiz_divclk_divide"]
        
        for output in range(7):
            base = 0x208 + output*12
            d[f"clk_wiz_clkout{output}_div"] = self.clk_wiz[base]
            if output == 0:
                d[f"clk_wiz_clkout{output}_frac"] = int.from_bytes(self.clk_wiz[base+2:base+1], 'little') & (2**10 - 1)
            d[f"clk_wiz_clkout{output}_phase"] = int.from_bytes(self.clk_wiz[base+8:base+4], 'little')
        
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
    
    # -------------- ABSTRACTIONS FOR JOINT PS-PL ROUTINES ----------- #
            
    def memcpy(self, src, dst, size=None, block=True, ps_fci=False, ps_fci_side=None):
        """
        Copy memory from one location to another using either the PS or the PL,
        depending on the active processor.

        :param src: Source array
        :type src: CacheArray, PSDDRArray, PLDDRArray, OCMArray, DACArray, 
            CMACCKernelArray, bytes
        :param dst: Destination array
        :type dst: CacheArray, PSDDRArray, PLDDRArray, OCMArray, DACArray,
            CMACCKernelArray
        :param size: Size of memory copy in bytes. If not provided, the size of
            the source array is used if available, and if not, the destination size
            is used. If unavailable, an error is thrown indicating that this 
            argument must be populated.
        :type size: int, optional
        :param block: If ``True``\, the active processor will be instructed to halt
            until the memory copy is completed. Otherwise, the function will return
            immediately after initiating the transfer.
        :param ps_fci: If ``True``\, the transfer is assumed to be carried out by
            the PS using the DMA controlled by its flow control interface (FCI)
            exposed to the PL. The sequencer is then responsible for initiating and
            executing the transaction. When ``True``\, the active processor is ignored.
        :return: If ``ps_fci`` is ``True`` or if the active processor is a 
            :class:`PythonProcessor`, then the :class:`ZDMA` object representing 
            the DMA configuration is returned. If the active processor is a 
            :class:`Sequencer`\, the value used for the DataMover TAG field is 
            returned.
        :type ps_fci: bool, optional
        :param ps_fci_side: The flow-controlled side; either "read" or "write"
        :type ps_fci_side: str
        """

        if size is None:
            if hasattr(src, "byte_length"):
                size = src.byte_length()
            elif hasattr(dst, "byte_length"):
                size = dst.byte_length()
            else:
                raise ValueError("Unable to infer size of memcpy; please"
                                 " please provide `size` argument.")
            
        proc = Processor.active_processor()
        if ((isinstance(src, bytes) 
                 or isinstance(src, Symbol) 
                 or isinstance(src, Operation)
                 or isinstance(src, np.ndarray)) 
                and isinstance(type(dst), ManagedMemory)):
            if size > 2**30:
                raise ValueError(f"Size must be less than 1 GB; received {size}.")
            if not block:
                raise ValueError("Copying a literal must block.")
            if ps_fci:
                raise ValueError("Copying a literal cannot use the FCI.")
            if proc is None:
                if not hasattr(dst, "memory"):
                    raise ValueError("Destination resource not attached.")
                # Loading from virtual memory, can't use DMA
                dst.memory[:size] = src.view(np.uint8) if isinstance(src, np.ndarray) else src
            else:
                raise TypeError(f"Unable to copy literal into memory on"
                                f" processor {proc}.")
        elif hasattr(src, "byte_address") and hasattr(dst, "byte_address"):    
            if proc is None:
                if size > 2**30:
                    raise ValueError(f"Size must be less than 1 GB; received {size}.")
                # Use the DMA for the copy
                dma = self._ZDMA(src=src.byte_address(), 
                                 dst=dst.byte_address(), 
                                 size=size, 
                                 fci_enable=ps_fci, 
                                 fci_side=ps_fci_side)
                dma.start_transfer()
                if block:
                    if proc is None:
                        while not dma.is_complete():
                            pass
                    else:
                        proc.wait_until(dma.is_complete())
                
                return dma
            elif isinstance(proc, Sequencer):
                # Use the AXI DataMover. Because of the arrangement of the AXI
                # master interfaces, memories on the config SmartConnect cannot
                # be sources
                if (isinstance(src, self.CacheArray) 
                        or isinstance(src, self.DACArray) 
                        or isinstance(src, self.CMACCKernelArray)):
                    raise TypeError(f"Unable to use sequencer to copy data from"
                                    f" source of type {type(self)}.")

                # Configure the DataMover controller (the last bus write will 
                # push the complete command into the command FIFO)
                # Configure the S2MM side first so that it is prepared when the
                # MM2S side starts streaming after the command gets pushed in
                self._sequencer_command_dm("cfg_dm_s2mm", src.byte_address(), size)
                self._sequencer_command_dm("cfg_dm_mm2s", dst.byte_address(), size)
                
                if block:
                    # Wait until we get a status from the S2MM
                    # Base latency, +1 because inherent pipelined reads in the datamover controller,
                    # plus any additional decoder port pipelining
                    latency = self._base_bus_latency + 1 + (1 if self._firmware["SEQUENCER_BUS"]["DATAMOVER_CONTROLLER"]["BUS_PIPELINE"] else 0)
                    proc.bus_read(self._firmware.sequencer_bus_decoder["datamover_controller"]["cfg_dm_s2mm"]+1,
                                  latency=latency)
                    with proc.wait_until(proc.bus_read() != 0):
                        pass
                return transfer_tag
            else:
                raise TypeError(f"Unable to copy memory using processor {proc}.")
        else:
            raise TypeError("Memory source and/or destination lack sufficient"
                            " information to execute copy.")
    
    @Synchronizer.synchronized(ChannelSynchronizer.STREAM, "synchronizer")
    @requires_sequencer
    def capture(self, channel, array, length=None, offset=None, integration_kernel=None, datamover_tag=0xB):
        """
        Capture a signal from an ADC into an array. 

        :param channel: Physical channel to capture from.
        :type channel: :class:`Channel` or int
        :param array: The array with which to populate the captured data. Optionally,
            the array may be indexed using slice notation to indicate lengths and/or
            offsets (in units of bytes). Note that negative slice values are NOT supported
            and will result in undefined behavior.
        :type array: :class:`PSDDRArray`, :class:`PLDDR0Array`, 
            :class:`PSDDR1Array`, :class:`self.OCMArray`, or a ``getitem`` operation
            acting on one of these
        :param length: Length (in bytes) of the capture. If not provided,
            the length of the destination array is used.
        :type length: int, optional
        :param offset: Offset (in bytes) in the destination array at which
            the capture should be stored. If not provided, an offset of zero
            is assumed.
        :type offset: int, optional
        :param integration_kernel: If provided, the captured trace will be
            integrated against the kernel given by the array using a CMACC.
            Otherwise, the signal will be captured with a regular ADC DMA.
        :type integration_kernel: :class:`CMACCArray`\, optional
        :param datamover_tag: An arbitrary 4-bit number that will be
            included in the status word returned by the DataMover for this
            transfer.
        :type datamover_tag: int, optional
        """

        if not isinstance(channel, Channel):
            raise TypeError(f"Channel must be of type `Channel`;"
                            f" received {channel}.")
            
        if channel.is_dac:
            raise TypeError(f"Channel must be an ADC;"
                            f" received {channel}.")
        
        if isinstance(array, Operation):
            if length is not None or offset is not None:
                raise TypeError("The `length` and `offset` arguments to"
                                " `capture` must be omitted when providing"
                                " an indexed array.")
            # If the arguments are as we expect, we're slicing the array
            if array._op == "getitem" and (isinstance(array._args[0], self.PSDDRArray)
                                        or isinstance(array._args[0], self.PLDDR0Array)
                                        or isinstance(array._args[0], self.PLDDR1Array)
                                        or isinstance(array._args[0], self.OCMArray)):
                if isinstance(array._args[1], slice):
                    if array._args[1].step is not None:
                        raise ValueError("Array slices must have a slice of 1.")
                    
                    capture_address_base = type(array._args[0]).base_byte_address

                    if array._args[1].stop is not None:
                        if array._args[1].start is not None:
                            capture_length = array._args[1].stop - array._args[1].start
                            capture_address = array._args[0]._resource_id + array._args[1].start                            
                        else:
                            capture_length = array._args[1].stop
                            capture_address = array._args[0]._resource_id
                    else:
                        if array._args[1].start is not None:
                            capture_length = array._args[0].byte_length() - array._args[1].start
                            capture_address = array._args[0]._resource_id + array._args[1].start
                        else:
                            raise ValueError("Received slice with both start"
                                             " and stop of None.")
                else:
                    raise TypeError("Indexed arrays must have `slice` arguments.")

            else:
                raise ValueError("Arrays of type `Operation` must be `getitem`"
                                 " operations acting on a `PSDDRArray`,"
                                 " `PLDDR0Array`, `PLDDR1Array`, or `OCMArray`"
                                 f" (received {array}).")
        elif (isinstance(array, self.PSDDRArray)
                or isinstance(array, self.PLDDR0Array)
                or isinstance(array, self.PLDDR1Array)
                or isinstance(array, self.OCMArray)):
            capture_address_base = type(array).base_byte_address
            capture_address = array._resource_id + offset if offset is not None else array._resource_id
            capture_length = length if length is not None else array.byte_length()
        else:
            raise TypeError(f"Unable to stream captured signal data into"
                            f" array {array}.")
        
        if integration_kernel is not None:
            if not isinstance(integration_kernel, self._CMACCKernelArray):
                raise TypeError(f"If provided, kernel must be a `CMACCKernelArray`;"
                                f" received {integration_kernel}.")
        
            # Integration kernel is always 1 sample wide
            if isinstance(capture_length, int):
                if capture_length % 8 != 0:
                    raise ValueError("Capture length for integration must be"
                                     " a multiple of 8 bytes (received"
                                     f" {capture_length}).")

                if integration_kernel.byte_length() != capture_length:
                    raise ValueError(f"Integration kernel length"
                                    f" ({integration_kernel.byte_length()})"
                                    f" does not match array length ({capture_length}).")
            else:
                print("WARNING: Unable to determine length of capture at compile time."
                      " Make sure that the capture has a valid length and start"
                      " address, or unintentional memory overwriting may occur.")
            
            # See if any DMAs are using the same physical channel as the one we
            # want to use, and if so, use that DMA. If not, request a new one
            # from the resource
            dma = None
            for d in self._CMACCDMA.instances:
                if d.physical_channel == channel and not d._released:
                    dma = d
                    break
            if dma is None:
                dma = self._CMACCDMA(physical_channel=channel)

            fifo_name = f"cmacc_dma{dma._resource_id}_fifo"
            datamover_name = f"cmacc_dm{dma._resource_id}"
            dma_address = integration_kernel.word_address()
            capture_length_cycles = capture_length // channel.interface_width_bytes
        else:
            if isinstance(capture_length, int):
                if capture_length % 16 != 0:
                    raise ValueError(f"An array for ADC capture without integration"
                                    " must have a size that is a multiple of 16"
                                    f" bytes; found {capture_length} bytes.")
            else:
                print("WARNING: Unable to determine length of capture at compile time."
                      " Make sure that the capture has a valid length and start"
                      " address, or unintentional memory overwriting may occur.")
            
            
            # See if any DMAs are using the same physical channel as the one we
            # want to use, and if so, use that DMA. If not, request a new one
            # from the resource
            dma = None
            for d in self._ADCDMA.instances:
                if d.physical_channel == channel and not d._released:
                    dma = d
                    break
            if dma is None:
                dma = self._ADCDMA(physical_channel=channel)

            fifo_name = f"adc_dma{dma._resource_id}_fifo"
            datamover_name = f"adc_dm{dma._resource_id}"
            dma_address = 0
            capture_length_cycles = capture_length // channel.interface_width_bytes
            
        # Store a reference to the DMA chosen in the Channel object
        channel.dma = dma
        
        # Add the descriptor address to the FIFO for the DMA
        descriptor = dma.request_descriptor(dma_address, capture_length_cycles)
        fifo_bus_address = self._firmware.sequencer_bus_decoder[fifo_name].address().value()
        self._active_sequencer.bus_write(address=fifo_bus_address,
                                         data=descriptor,
                                         comment=f"Add descriptor with parameters"
                                                f" {descriptor.kwargs} to DMA FIFO for ADC"
                                                f" switch output {dma._resource_id}"
                                                f" (connected to ADC{channel.num})")
        
        # Configure the DataMover
        self._sequencer_command_dm(datamover_name, 
                                   capture_address, 
                                   capture_length, 
                                   tag=datamover_tag, 
                                   address_base=capture_address_base)
    
    @Synchronizer.synchronized(ChannelSynchronizer.STREAM, "synchronizer")
    @requires_sequencer
    def generate(self, channel, array, decimate=0):
        """
        Generate a pulse on a DAC channel.

        :param channel: Physical channel to capture from.
        :type channel: :class:`Channel` or int
        :param array: The array of samples to stream into the DAC
        :type array: :class:`DACArray`
        :param decimate: Decimation amount
        :type decimate: int, optional
        """

        if not isinstance(channel, Channel):
            raise TypeError(f"Channel must be of type `Channel`;"
                            f" received {channel}.")
            
        if not channel.is_dac:
            raise TypeError(f"Channel must be a DAC;"
                            f" received {channel}.")
            
        dma = self._dac_dmas[channel.num]
        
        # Store a reference to the DMA chosen in the Channel object
        channel.dma = dma
            
        # When we request the descriptor, we need to get the address aligned to
        # 128 bits. We need the word address
        descriptor = dma.request_descriptor(array.word_address(), 
                                            array.byte_length() // channel.interface_width_bytes,
                                            decimate=decimate)
        
        fifo_device = self._firmware.sequencer_bus_decoder[f"dac_dma{channel.num}_fifo"]
        return self._active_sequencer.bus_write(address=fifo_device.address().value(),
                                         data=descriptor, 
                                         comment=f"Add descriptor with parameters {descriptor.kwargs} to FIFO for DAC{channel.num}")

    @Synchronizer.synchronized(ChannelSynchronizer.STREAM, "synchronizer")
    @requires_sequencer
    def generate_blank(self, channel, length):
        """
        Generate a blank pulse on a DAC channel.

        :param channel: Physical channel to capture from.
        :type channel: :class:`Channel` or int
        :param length: Length of the blank pulse in seconds
        :type length: float
        """

        if not isinstance(channel, Channel):
            raise TypeError(f"Channel must be of type `Channel`;"
                            f" received {channel}.")
            
        if not channel.is_dac:
            raise TypeError(f"Channel must be a DAC;"
                            f" received {channel}.")
            
        dma = self._dac_dmas[channel.num]
        
        # Store a reference to the DMA chosen in the Channel object
        channel.dma = dma
            
        # When we request the descriptor, we need to get the address aligned to
        # 128 bits. We need the word address
        descriptor = dma.request_descriptor(0, 
                                            channel.seconds_to_bytes(length) // channel.interface_width_bytes,
                                            blank=True)
        
        fifo_device = self._firmware.sequencer_bus_decoder[f"dac_dma{channel.num}_fifo"]
        return self._active_sequencer.bus_write(address=fifo_device.address().value(),
                                         data=descriptor, 
                                         comment=f"Add descriptor with parameters {descriptor.kwargs} to FIFO for DAC{channel.num}")

    @Synchronizer.synchronized(ChannelSynchronizer.STREAM, "synchronizer")
    @requires_sequencer
    def generate_constant(self, channel, value, length):
        """
        Generate a constant signal on a DAC channel.

        :param channel: Physical channel to capture from.
        :type channel: :class:`Channel` or int
        :param value: The constant value to generate
        :type value: int, float, complex, or a Symbol with value type of int,
            float, or complex
        :param length: The length of the signal in seconds. 
        :type length: float
        """

        if not isinstance(channel, Channel):
            raise TypeError(f"Channel must be of type `Channel`;"
                            f" received {channel}.")
            
        if not channel.is_dac:
            raise TypeError(f"Channel must be a DAC;"
                            f" received {channel}.")
            
        dma = self._dac_dmas[channel.num]
        
        # Store a reference to the DMA chosen in the Channel object
        channel.dma = dma
            
        # Based on the value, determine how we need to allocate
        if (isinstance(value, int) or isinstance(value, float) or isinstance(value, complex)):
            if value == 0:
                descriptor = dma.request_descriptor(0, 
                                                    channel.seconds_to_bytes(length) // channel.interface_width_bytes, 
                                                    fixed=True, 
                                                    blank=True)
            else:
                mem = self.DACArray[channel.num](size=channel.interface_width_bytes)
                self._dac_constants.append((mem,value))
                descriptor = dma.request_descriptor(mem.word_address(), length, fixed=True)
        elif isinstance(value, Symbol) and value.value_type() in [int, float, complex]:
            mem = self.DACArray[channel.num](size=channel.interface_width_bytes)
            self._dac_constants.append((mem,value))
            descriptor = dma.request_descriptor(mem.word_address(), length, fixed=True)
        else:
            raise TypeError("Symbolic constants must be of type `int`,"
                             f" `float`, `complex`, or a `Symbol` with a value"
                             f" type of one of these (received {value}).")
        
        fifo_device = self._firmware.sequencer_bus_decoder[f"dac_dma{channel.num}_fifo"]
        return self._active_sequencer.bus_write(address=fifo_device.address().value(),
                                         data=descriptor, 
                                         comment=(f"Add descriptor with parameters"
                                                  f" {descriptor.kwargs} to FIFO"
                                                  f" for DAC{channel.num}"))

    # -------------- CONVENIENCE FUNCTIONS FOR THE SEQUENCER ----------- #

    def get_bus_latency(self, port):
        """
        Get the latency for a port on the sequencer's bus, taking into account
        any pipeling configured in the firmware.

        :param port: Bus port name. Must either be a key in the 
            ``SEQUENCER_BUS``  section of the firmware configuration, or
            ``cache``\.
        :type port: str
        """
        # One cycle to load the bus registers in the sequencer
        latency = 1 

        if self._firmware["SEQUENCER_BUS"]["DECODER_PIPELINE_MISO"]:
            latency += 1

        # The datamover controller has a read latency of 1 because its MISO is driven
        # in a synchronous process
        if port == "DATAMOVER_CONTROLLER":
            latency += 1

        if port == "cache":
            # One additional cycle minimum because the memory has a read latency of 1
            # even before any pipelining because it's a synchronous memory
            latency += 1 
            latency += self._firmware["SEQUENCER_CACHE_MEMORY"]["BUS_PORT_INPUT_PIPELINE"]
            latency += self._firmware["SEQUENCER_CACHE_MEMORY"]["BUS_PORT_OUTPUT_PIPELINE"]
        elif "PS_GPIO" in port:
            latency += self._firmware[port]["BUS_PIPELINE"]
        elif self._firmware["SEQUENCER_BUS"][port]["BUS_PIPELINE"]:
            latency += 1

        return latency
        

    @requires_sequencer
    def channel_fifos_almost_empty(self, *channels):
        """
        Create a condition that will determine whether the FIFOs of the DMAs
        driving the given :class:`Channel`\s are almost empty.

        :param channels: Channel(s) to check
        :type channels: list of :class:`Channel`
        """

        mask = 0
        for channel in channels:
            dma = channel.dma
            bit_position = channel.num if channel.is_dac else (type(dma).DMA_NUM_OFFSET + dma._resource_id)
            mask |= 1 << bit_position
        bus_address = self._firmware.dma_fifo_almost_empty.address().value()

        self._active_sequencer.bus_read(bus_address, latency=self.get_bus_latency("DMA_FIFO_ALMOST_EMPTY_DATAPORT"))
        return self._active_sequencer.bus_read() & mask != 0
    
    @requires_sequencer
    def channel_fifos_empty(self, *channels):
        """
        Create a condition that will determine whether the FIFOs of the DMAs
        driving the given :class:`Channel`\s are empty.

        :param channels: Channel(s) to check
        :type channels: list of :class:`Channel`
        """

        mask = 0
        for channel in channels:
            dma = channel.dma
            bit_position = channel.num if channel.is_dac else (type(dma).DMA_NUM_OFFSET + dma._resource_id)
            mask |= 1 << bit_position
        bus_address = self._firmware.dma_fifo_empty.address().value()

        self._active_sequencer.bus_read(bus_address, latency=self.get_bus_latency("DMA_FIFO_EMPTY_DATAPORT"))
        return self._active_sequencer.bus_read() & mask != 0
    
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
            dma = channel.dma
            mask |= 1 << (type(dma).DMA_NUM_OFFSET + dma._resource_id)
        
        bus_address = self._firmware.dma_running.address().value()

        self._active_sequencer.bus_read(bus_address, latency=self.get_bus_latency("DMA_RUNNING_DATAPORT"))
        return self._active_sequencer.bus_read() & mask != 0

    @requires_sequencer
    def capture_count(self, channel):
        """
        Retrieve the number of status words produced for the DMA configured
        to receive from the provided channel.

        :param channels: Channel(s) to check
        :type channels: list of :class:`Channel`
        """

        if isinstance(channel.dma, self._CMACCDMA):
            datamover_name = f"cmacc_dm{channel.dma._resource_id}"
        elif isinstance(channel.dma, self._ADCDMA):
            datamover_name = f"adc_dm{channel.dma._resource_id}"
        else:
            raise TypeError(f"Invalid type of DMA {channel.dma}")

        address = self._firmware.sequencer_bus_decoder["datamover_controller"][datamover_name] + 1
        self._active_sequencer.bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status count for {datamover_name}",
                                        latency=self.get_bus_latency("DATAMOVER_CONTROLLER"))
        return self._active_sequencer.bus_read()
    
    @requires_sequencer
    def capture_status(self, channel):
        """
        Retrieve the status of a capture that was completed on a given channel.
        To ensure that the result is valid, this should be called after 
        :meth:`captures_complete` returns ``True`` for the given channel.

        :param channel: Channel to check
        :type channel: :class:`Channel`
        """

        if isinstance(channel.dma, self._CMACCDMA):
            datamover_name = f"cmacc_dm{channel.dma._resource_id}"
        elif isinstance(channel.dma, self._ADCDMA):
            datamover_name = f"adc_dm{channel.dma._resource_id}"
        else:
            raise TypeError(f"Invalid type of DMA {channel.dma}")

        address = self._firmware.sequencer_bus_decoder["datamover_controller"][datamover_name]
        self._active_sequencer.bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status for {datamover_name}",
                                        latency=self.get_bus_latency("DATAMOVER_CONTROLLER"))
        return self._active_sequencer.bus_read()
    
    @requires_sequencer
    def fifo_error_status(self):
        """
        Return a sequencer Source for checking the error status of the
        ADC FIFOs.
        """

        self._active_sequencer.bus_read(address=self._firmware.sequencer_bus_decoder["adc_fifo_control"].address().value(),
                                        latency=self.get_bus_latency("ADC_FIFO_DATAPORT"))
        return self._active_sequencer.bus_read()

    @requires_sequencer
    def reset_fifos(self, *args):
        """
        Resets the FIFOs associated with the given channels. If none are 
        provided, all are reset.
        """

        mask = 0
        if args is None or len(args) == 0:
            mask = 0xFFFFFFFF
        else:
            for channel in args:
                dma = channel.dma
                mask |= 1 << (type(dma).DMA_NUM_OFFSET + dma._resource_id)

        
        self._active_sequencer.bus_write(address=self._firmware.sequencer_bus_decoder["adc_fifo_control"].address().value(), 
                        data=mask,
                        comment="FIFO reset")

    @requires_sequencer     
    def reset_datamover_controller(self, *args):
        """
        Resets the datamover controller channel associated with the given
        signal channels. If none are provided, all are reset.
        """

        mask = 0
        if args is None or len(args) == 0:
            mask = 0xFFFFFFFF
        else:
            for channel in args:
                dma = channel.dma
                offset = type(dma).DMA_NUM_OFFSET - 16 # -16 because no DACs in this register
                mask |= 1 << (offset + dma._resource_id)

        with self.sequencer() as seq:
            # We can reset whichever datamovers we want with the reset register
            # for the first channel
            seq.bus_write(address=self._firmware.sequencer_bus_decoder["datamover_controller"].address().value() + 3, 
                          data=mask)
            
    @requires_sequencer
    def dma_trigger(self, *channels):
        """
        Trigger the DMAs associated with the provided channels.

        :param channels: List of channels
        """
        mask = 0
        for channel in channels:
            dma = channel.dma
            bit_position = channel.num if channel.is_dac else (type(dma).DMA_NUM_OFFSET + dma._resource_id)
            mask |= 1 << bit_position

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
            dma = channel.dma
            bit_position = channel.num if channel.is_dac else (type(dma).DMA_NUM_OFFSET + dma._resource_id)
            mask |= 1 << bit_position

        dma_running_device = self._firmware.sequencer_bus_decoder["dma_running"]
        dma_running = self._active_sequencer.bus_read(address=dma_running_device.address().value(),
                                                      latency=self.get_bus_latency("DMA_RUNNING_DATAPORT"))
        with self._active_sequencer.wait_until(dma_running & mask == 0):
            pass

    # -------------- RUNTIME UTILITIES ----------- #

    def configure(self):
        """
        Configure various settings to prepare for running a program.
        This included loading internally-store constants into memory
        and configuring the ADC switch. 
        """

        # Load DAC constants
        for mem,constant in self._dac_constants:
            mem.memory[:] = Channel.to_samples(np.array([constant]*(len(mem)//4)))

        # Configure the ADC AXIS Switch according to the DMA settings
        # For any DMAs with instructions, connect to the stored physical channel
        self._ADC_AXIS_switch.disconnect()
        for dma in self._ADCDMA.instances:
            if dma.Instruction.usage() > 0:
                self._ADC_AXIS_switch.connect(dma._resource_id, dma.physical_channel.num)
        for dma in self._CMACCDMA.instances:
            if dma.Instruction.usage() > 0:
                self._ADC_AXIS_switch.connect(dma._resource_id+4, dma.physical_channel.num)

    def sequencer_run(self, sequence=None):
        """
        Runs the sequencer by driving its run pin high. If a Sequence resource 
        is provided, the instruction memory will be updated to jump to that
        sequence in instruction memory.
        
        :param sequence: The sequence to run.
        :type sequence: :class:`Sequence`
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
            return proc.bus_read(addr, latency=self.get_bus_latency(f"PS_GPIO{port}"))
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
            
    def _create_cache(self):
        def _cache_getitem(cache_self, key):
            proc = Processor.active_processor()
            if isinstance(proc, Sequencer):
                return proc.bus_read(cache_self.word_address() + key, 
                                     latency=self.get_bus_latency("cache"))
            return Operation("getitem", cache_self, key)
            
        def _cache_setitem(cache_self, key, value):
            proc = Processor.active_processor()
            if proc is None:
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
            base_byte_address=self._firmware["SEQUENCER_CACHE_MEMORY"]["ADDRESS"],
            word_width=32,
            memory_size=self._firmware["SEQUENCER_CACHE_MEMORY"]["SIZE_BITS"] // 8,
            default_getitem=False)
        
    def _create_dac_arrays(self):
        self.DACArray = [ManagedMemory(f"DAC{i}Array", (), {"channel": self.DAC(i)},
            base_word_address=0,
            base_byte_address=(self._firmware[f"DAC_TILE{i // 4}_SAMPLE_MEMORY"]["ADDRESS"] 
                               + (i % 4)*(self._firmware[f"DAC_TILE{i // 4}_SAMPLE_MEMORY"]["SIZE_BITS"] // 8)),
            word_width=128,
            memory_size=self._firmware[f"DAC_TILE{i // 4}_SAMPLE_MEMORY"]["SIZE_BITS"] // 8) for i in range(16)]
        
        # In addition to the arrays themselves, store an internal reference
        # to constants that will be loaded into memory when the program is configured
        self._dac_constants = []
        
    def _create_cmacc_kernel_arrays(self):
        self.CMACCKernelArray = [ManagedMemory(f"CMACCKernel{i}Array", (), {},
            base_word_address=0,
            base_byte_address=(self._firmware["CMACC_KERNEL_MEMORY"]["ADDRESS"] 
                               + i*(self._firmware["CMACC_KERNEL_MEMORY"]["SIZE_BITS"] // 8)),
            word_width=32,
            memory_size=self._firmware["CMACC_KERNEL_MEMORY"]["SIZE_BITS"] // 8) for i in range(4)]
        
    def _create_pl_ddr_arrays(self):
        self.PLDDR0Array = ManagedMemory(f"PLDDR0Array", (), {},
            base_word_address=self._firmware["DDR4_MEMORY"]["DDR4_C0"]["ADDRESS"],
            base_byte_address=self._firmware["DDR4_MEMORY"]["DDR4_C0"]["ADDRESS"],
            word_width=8,
            memory_size=self._firmware["DDR4_MEMORY"]["DDR4_C0"]["SIZE_BITS"] // 8)
        
        self.PLDDR1Array = ManagedMemory(f"PLDDR1Array", (), {},
            base_word_address=self._firmware["DDR4_MEMORY"]["DDR4_C1"]["ADDRESS"],
            base_byte_address=self._firmware["DDR4_MEMORY"]["DDR4_C1"]["ADDRESS"],
            word_width=8,
            memory_size=self._firmware["DDR4_MEMORY"]["DDR4_C1"]["SIZE_BITS"])
        
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
        
    def _attach_resource(self, resource_manager, mem_cast=np.uint8):
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
            instance.memory = np.frombuffer(m, 
                                            dtype=np.uint8, 
                                            offset=start_byte, 
                                            count=instance.byte_length()).view(mem_cast)

        
    def _attach_memory(self, address, size, mem_cast=np.uint8):
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
        
        return np.frombuffer(m, dtype=mem_cast)

    def _sequencer_command_dm(self, datamover_name, address, size, tag=0xA, incr=True, address_base=None):
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
        bus_address_base = self._firmware.sequencer_bus_decoder["datamover_controller"][datamover_name]
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
        