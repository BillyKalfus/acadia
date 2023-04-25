__all__ = ["StandardFirmware", "Acadia", "Channel", "PSGPIO"]

import os
import re
import mmap
import time
from dataclasses import dataclass
from functools import wraps
from abc import ABC, abstractmethod

import numpy as np

from .hdl import BusDevice, BusDecoder, BusDataport, BusDataMoverController, AXIMemoryArray
from .compiler import ManagedResource, ManagedMemory, Processor, Synchronizer, Symbol, Operation
from .firmware import Firmware
from .sequencer import Sequencer, STP, Destination
from .dma import DMA
from .utils import connect_bd_net, connect_bd_intf_net, create_ip, create_module, create_concatenator, create_slice, set_property, assign_bd_address, exclude_bd_addr_seg, next_highest_power_of_2

try:
    import pyxrfclk as xrfclk
    import pyxrfdc as xrfdc
except ImportError as e:
    print(e)

class StandardFirmware(Firmware):
     # Designate some addresses for memory slave segments
    # HPC0_QSPI_ADDRESS = 0x00_C000_0000
    HPC0_LPS_OCM_ADDRESS = 0x00_FF00_0000

    # HPC1_QSPI_ADDRESS = 0x01_C000_0000
    HPC1_LPS_OCM_ADDRESS = 0x01_FF00_0000

    # HP0_QSPI_ADDRESS = 0x02_C000_0000
    HP0_LPS_OCM_ADDRESS = 0x02_FF00_0000

    # HP1_QSPI_ADDRESS = 0x3C_C000_0000
    HP1_LPS_OCM_ADDRESS = 0x03_FF00_0000
    
    HPC0_DDR_LOW_ADDRESS = 0x04_0000_0000
    HPC1_DDR_LOW_ADDRESS = 0x05_0000_0000
    HP0_DDR_LOW_ADDRESS = 0x06_0000_0000
    HP1_DDR_LOW_ADDRESS = 0x07_0000_0000
    
    HPC0_DDR_HIGH_ADDRESS = 0x08_0000_0000
    HPC1_DDR_HIGH_ADDRESS = 0x18_0000_0000
    HP0_DDR_HIGH_ADDRESS = 0x28_0000_0000
    HP1_DDR_HIGH_ADDRESS = 0x38_0000_0000
    
    DDR4_C0_ADDRESS = 0x40_0000_0000
    DDR4_C1_ADDRESS = 0x41_0000_0000

    # We'll manually choose addresses for the AXI HPM1 interface since there are particular alignment requirements
    RFDC_ADDRESS = 0x00_B000_0000
    CLK_WIZ_ADDRESS = 0x00_B004_0000
    ADC_AXIS_SWITCH_ADDRESS = 0x00_B080_0000
    
    DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS = 1024*64
    DAC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS = 0x00_B010_0000
    
    ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS = 1024*64
    ADC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS = 0x00_B020_0000
    
    CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS = 1024*64
    CMACC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS = 0x00_B030_0000
    
    CACHE_MEMORY_SIZE_BITS = 2**20
    CACHE_MEMORY_ADDRESS = 0x00_B040_0000
    
    INSTRUCTION_MEMORY_SIZE_BITS = 128*4096
    INSTRUCTION_MEMORY_ADDRESS = 0x00_B050_0000
    
    DAC_MEMORY_SIZE_BITS = 128*8192
    DAC_MEMORY_BASE_ADDRESS = 0x00_B100_0000
    
    CMACC_KERNEL_MEMORY_SIZE_BITS = 2048*128
    CMACC_KERNEL_MEMORY_BASE_ADDRESS = 0x00_B200_0000

    ADC_FIFO_DEPTH = 1024
    CMACC_FIFO_DEPTH = 1024
    
    NUM_DAC = 16
    NUM_ADC = 4
    NUM_CMACC = 4
    NUM_PS_GPIO = 91
    NUM_PS_IRQ = 2
    NUM_PS_GDMA = 8
    
    GPIO_SEQUENCER_RUN = 90 # The GPIO bit connected to the sequencer run synchronizer
    
    """
    The standard Acadia firmware. Handcrafted, artisanal FPGA logic with notes of silicon and garnished with hedgehog quills.
    """
    def __init__(self, project_dir=None):
        super().__init__(project_dir)
                
        # Create a primary decoder for the sequencer bus
        sequencer_bus_decoder = BusDecoder("sequencer_bus_decoder", pipeline_miso=True)
        self.add(sequencer_bus_decoder)

        # Create split dataport for triggering and monitoring the DMA and for setting continue signals
        bit = 0
        dma_trigger_ports = []
        dma_fifo_empty_ports = []
        dma_fifo_almost_empty_ports = []
        dma_running_ports = []
        
        for label,count in [("dac", StandardFirmware.NUM_DAC), ("adc", StandardFirmware.NUM_ADC), ("cmacc", StandardFirmware.NUM_CMACC)]:
            for idx in range(count):
                dma_trigger_ports += [{"name": f"{label}_dma{idx}", 
                                          "direction": BusDataport.OUTPUT, 
                                          "offset": bit,
                                          "width": 1,
                                          "gate": BusDataport.GATE_RESET,
                                          "pipeline": 1}]
                
                dma_fifo_empty_ports += [{"name": f"{label}_dma{idx}", 
                                          "direction": BusDataport.INPUT, 
                                          "offset": bit,
                                          "width": 1,
                                          "pipeline": 1}]
                
                dma_fifo_almost_empty_ports += [{"name": f"{label}_dma{idx}", 
                                                  "direction": BusDataport.INPUT, 
                                                  "offset": bit,
                                                  "width": 1,
                                                  "pipeline": 1}]
                
                dma_running_ports += [{"name": f"{label}_dma{idx}", 
                                          "direction": BusDataport.INPUT, 
                                          "offset": bit,
                                          "width": 1,
                                          "pipeline": 1}]
            
                
                bit += 1
                
                fifo_port = BusDevice(name=f"{label}_dma{idx}_fifo", size=1)
                sequencer_bus_decoder.add(fifo_port)
        
        
        dma_trigger = BusDataport(name="dma_trigger", ports=dma_trigger_ports)
        sequencer_bus_decoder.add(dma_trigger)
        self.add(dma_trigger)
        
        dma_fifo_empty = BusDataport(name="dma_fifo_empty", ports=dma_fifo_empty_ports)
        sequencer_bus_decoder.add(dma_fifo_empty)
        self.add(dma_fifo_empty)
        
        dma_fifo_almost_empty = BusDataport(name="dma_fifo_almost_empty", ports=dma_fifo_almost_empty_ports)
        sequencer_bus_decoder.add(dma_fifo_almost_empty)
        self.add(dma_fifo_almost_empty) 
        
        dma_running = BusDataport(name="dma_running", ports=dma_running_ports)
        sequencer_bus_decoder.add(dma_running)
        self.add(dma_running)
            
        # Create dataports for controlling accumulator offsets and output values
        for i in range(StandardFirmware.NUM_CMACC):
            for quad in ["re", "im"]:
                cmacc_dataports = []

                cmacc_dataports += [{"name": f"accumulator",
                                       "direction": BusDataport.INPUT,
                                       "offset": 0,
                                       "width": 32,
                                       "pipeline": 1}]
                cmacc_dataports += [{"name": f"offset",
                                       "direction": BusDataport.OUTPUT,
                                       "offset": 0,
                                       "width": 32,
                                       "gate": BusDataport.GATE_REGCE,
                                       "pipeline": 1}]

                cmacc_port = BusDataport(name=f"cmacc{i}_{quad}", ports=cmacc_dataports)
                sequencer_bus_decoder.add(cmacc_port)
                self.add(cmacc_port)

        # Add a reset port
        cmacc_reset_ports = []
        
        for i in range(StandardFirmware.NUM_CMACC):
            cmacc_reset_ports += [{"name": f"cmacc{i}", 
                                      "direction": BusDataport.OUTPUT, 
                                      "offset": i,
                                      "width": 1,
                                      "gate": BusDataport.GATE_RESET,
                                      "pipeline": 2}]

        cmacc_reset_port = BusDataport(name=f"cmacc_reset", ports=cmacc_reset_ports)
        sequencer_bus_decoder.add(cmacc_reset_port)
        self.add(cmacc_reset_port)
        
        # Create dataports for monitoring the CMACCs for completion
        cmacc_status_dataports = []
        for i in range(StandardFirmware.NUM_CMACC):
            cmacc_status_dataports += [{"name": f"cmacc{i}_valid",
                                       "direction": BusDataport.INPUT,
                                       "offset": i,
                                       "width": 1,
                                       "pipeline": 1}]
            cmacc_status_dataports += [{"name": f"cmacc{i}_last",
                                       "direction": BusDataport.INPUT,
                                       "offset": StandardFirmware.NUM_CMACC + i,
                                       "width": 1,
                                       "pipeline": 1}]
            cmacc_status_dataports += [{"name": f"cmacc{i}_re_msb",
                                       "direction": BusDataport.INPUT,
                                       "offset": 2*StandardFirmware.NUM_CMACC + i,
                                       "width": 1,
                                       "pipeline": 1}]
            
        cmacc_status = BusDataport(name="cmacc_status", ports=cmacc_status_dataports)
        sequencer_bus_decoder.add(cmacc_status)
        self.add(cmacc_status)

        # Create dataports for interacting with the PS GPIO
        for gpio_num, size in [(3, 32), (4, 32), (5, StandardFirmware.NUM_PS_GPIO % 32)]:
            ps_gpio_dataports = []

            ps_gpio_dataports += [{"name": f"gpio_out",
                                       "direction": BusDataport.INPUT,
                                       "offset": 0,
                                       "width": size,
                                       "pipeline": 2}]
            ps_gpio_dataports += [{"name": f"gpio_in",
                                       "direction": BusDataport.OUTPUT,
                                       "offset": 0,
                                       "width": size,
                                       "gate": BusDataport.GATE_REGCE,
                                       "pipeline": 2}]

            ps_gpio = BusDataport(name=f"ps_gpio{gpio_num}", ports=ps_gpio_dataports)
            sequencer_bus_decoder.add(ps_gpio)
            self.add(ps_gpio)
            
        ps_irq_dataports = []
        for i in range(StandardFirmware.NUM_PS_IRQ):
            ps_irq_dataports += [{"name": f"irq{i}",
                                       "direction": BusDataport.OUTPUT,
                                       "offset": i,
                                       "width": 1,
                                       "gate": BusDataport.GATE_REGCE,
                                       "pipeline": 2}]
        
        ps_irq_dataports += [{"name": f"gdma_irq",
                                   "direction": BusDataport.INPUT,
                                   "offset": StandardFirmware.NUM_PS_IRQ + i,
                                   "width": StandardFirmware.NUM_PS_GDMA,
                                   "pipeline": 2}]
        
        ps_irq = BusDataport(name="ps_irq", ports=ps_irq_dataports)
        sequencer_bus_decoder.add(ps_irq)
        self.add(ps_irq)

        # Create a register file for RFDC real-time updates and connect it to the sequencer bus
        rfdc_rts_regs = BusDevice("rfdc_rts_regs", size=256)
        sequencer_bus_decoder.add(rfdc_rts_regs, pipeline=True)
        
        # Create a register file for interacting with the PS GDMA
        zdma_controller = BusDevice("zdma_controller", size=64)
        sequencer_bus_decoder.add(zdma_controller, pipeline=True)
        
        clk104_sync_in_dataports = [{"name": f"sync",
                                       "direction": BusDataport.OUTPUT,
                                       "offset": 0,
                                       "width": 1,
                                       "gate": BusDataport.GATE_REGCE,
                                       "pipeline": 2}]
        
        clk104_sync_in = BusDataport(name="clk104_sync_in", ports=clk104_sync_in_dataports)
        sequencer_bus_decoder.add(clk104_sync_in)
        self.add(clk104_sync_in)

        # Create cache and connect it to the sequencer bus
        cache = BusDevice("cache", size=StandardFirmware.CACHE_MEMORY_SIZE_BITS // 32)
        sequencer_bus_decoder.add(cache)

        datamover_controller = BusDataMoverController("datamover_controller", 
                                                      [f"adc_dm{i}" for i in range(4)] + 
                                                      [f"cmacc_dm{i}" for i in range(4)] + 
                                                      ["cfg_dm_mm2s", "cfg_dm_s2mm"], addr_bits=40)
        sequencer_bus_decoder.add(datamover_controller)
        self.add(datamover_controller)

        # Create AXI-controlled memories
        self._memory_tcl = ""
        # Create an AXI BRAM Controller wrapper for the cache
        cache_controller = AXIMemoryArray("cache", 
            size_bits=StandardFirmware.CACHE_MEMORY_SIZE_BITS, 
            width=32, 
            controller_width=128,
            axi_frequency=300e6, 
            elements=1, 
            read_only=False,
            use_rst=False,
            primitive="block", 
            controller_port_input_pipeline=2,
            controller_port_output_pipeline=2,                              
            user_port_input_pipeline=0,
            user_port_output_pipeline=1)
        self.add(cache_controller)
        self._memory_tcl += cache_controller.generate_ip_tcl(self._project_dir)
        
        instruction_mem_controller = AXIMemoryArray("instruction", 
            size_bits=StandardFirmware.INSTRUCTION_MEMORY_SIZE_BITS, 
            width=128, 
            axi_frequency=300e6, 
            elements=1, 
            read_only=True,
            use_rst=False,
            primitive="block", 
            controller_port_input_pipeline=2,
            controller_port_output_pipeline=2,
            user_port_input_pipeline=0,
            user_port_output_pipeline=0)
        self.add(instruction_mem_controller)
        self._memory_tcl += instruction_mem_controller.generate_ip_tcl(self._project_dir)
        
        controller = AXIMemoryArray(f"dac", 
            size_bits=StandardFirmware.DAC_MEMORY_SIZE_BITS, 
            width=128, 
            axi_frequency=300e6, 
            elements=StandardFirmware.NUM_DAC, 
            read_only=True,
            use_rst=True,
            primitive="ultra", 
            controller_port_input_pipeline=2,
            controller_port_output_pipeline=2,   
            user_port_input_pipeline=1,
            user_port_output_pipeline=2)
        self.add(controller)
        self._memory_tcl += controller.generate_ip_tcl(self._project_dir)
            
        controller = AXIMemoryArray(f"cmacc_kernel", 
            size_bits=StandardFirmware.CMACC_KERNEL_MEMORY_SIZE_BITS, 
            width=64, 
            axi_frequency=300e6, 
            elements=StandardFirmware.NUM_CMACC, 
            read_only=True,
            use_rst=True,
            primitive="block", 
            controller_port_input_pipeline=2,
            controller_port_output_pipeline=2,   
            user_port_input_pipeline=0,
            user_port_output_pipeline=1)
        self.add(controller)
        self._memory_tcl += controller.generate_ip_tcl(self._project_dir)
            
        controller = AXIMemoryArray(f"dac_dma_descriptor", 
            size_bits=StandardFirmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS, 
            width=64, 
            axi_frequency=300e6, 
            elements=StandardFirmware.NUM_DAC, 
            read_only=True,
            use_rst=False,
            primitive="block", 
            controller_port_input_pipeline=2,
            controller_port_output_pipeline=2,   
            user_port_input_pipeline=0,
            user_port_output_pipeline=0)
        self.add(controller)
        self._memory_tcl += controller.generate_ip_tcl(self._project_dir)
            
        controller = AXIMemoryArray(f"adc_dma_descriptor", 
            size_bits=StandardFirmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS, 
            width=64, 
            axi_frequency=300e6, 
            elements=StandardFirmware.NUM_ADC, 
            read_only=True,
            use_rst=False,
            primitive="block", 
            controller_port_input_pipeline=2,
            controller_port_output_pipeline=2,   
            user_port_input_pipeline=0,
            user_port_output_pipeline=0)
        self.add(controller)
        self._memory_tcl += controller.generate_ip_tcl(self._project_dir)
            
        controller = AXIMemoryArray(f"cmacc_dma_descriptor", 
            size_bits=StandardFirmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS, 
            width=64, 
            axi_frequency=300e6, 
            elements=StandardFirmware.NUM_CMACC, 
            read_only=True,
            use_rst=False,
            primitive="block", 
            controller_port_input_pipeline=2,
            controller_port_output_pipeline=2,   
            user_port_input_pipeline=0,
            user_port_output_pipeline=0)
        self.add(controller)
        self._memory_tcl += controller.generate_ip_tcl(self._project_dir)
        
        # Assign decoder addresses
        sequencer_bus_decoder.assign_address(0)
            
    def write_hedgehog_tcl(self, filename="hedgehog.tcl"):
        """
        Write a TCL script to populate the HEDGEHOG logic in the standard image. 
        """
        super().write_hedgehog_tcl(filename)
        
        with open(self._hedgehog_tcl_filename, "a") as f:
            
            # Write the TCL that will generate the IP for the AXI memory controllers
            f.write(self._memory_tcl)
            
            # ------------------- Clock Management -------------------- #

            # The PL clock from the CLK104 is brought in through an HDIO bank, so we need to buffer
            # it with an IBUFDS before feeding it to the MMCM
            create_ip(f, name="hedgehog/pl_clk_ibufds", vlnv="xilinx.com:ip:util_ds_buf:2.1")
            set_property(f, name="hedgehog/pl_clk_ibufds", properties={"C_SIZE": 1, "C_BUF_TYPE": "IBUFDS"})
            
            create_ip(f, name="hedgehog/pl_clk_bufg", vlnv="xilinx.com:ip:util_ds_buf:2.1")
            set_property(f, name="hedgehog/pl_clk_bufg", properties={"C_SIZE": 1, "C_BUF_TYPE": "BUFG"})
            
            connect_bd_intf_net(f, "hedgehog/CLK104_PL_CLK", "hedgehog/pl_clk_ibufds/CLK_IN_D")
            connect_bd_net(f, "hedgehog/pl_clk_ibufds/IBUF_OUT", "hedgehog/pl_clk_bufg/BUFG_I")
            
            # We'll create an MMCM that will generate a 30 MHz clock 
            # for the decimated ADC along with a 300 MHz signal to clock everything else
            # (this is moreso for convenience, since then it"ll have a nice phase 
            # relationship with the 50 MHz clock and the core will automatically create constraints
            # that reflect this)
            create_ip(f, name="hedgehog/clk_wiz", vlnv="xilinx.com:ip:clk_wiz:6.0")
            set_property(f, name="hedgehog/clk_wiz", properties={"PRIM_IN_FREQ.VALUE_SRC": "USER"})
            set_property(f, name="hedgehog/clk_wiz",
                             properties="CONFIG.PRIMITIVE {MMCM} "
                                        "CONFIG.USE_DYN_RECONFIG {true} "
                                        "CONFIG.USE_PHASE_ALIGNMENT {true} "
                                        "CONFIG.PRIM_SOURCE {Global_buffer} "
                                        "CONFIG.PRIM_IN_FREQ {300.000} "
                                        "CONFIG.CLKOUT2_USED {true} "
                                        "CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {300.000} "
                                        "CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {30.000} "
                                        "CONFIG.CLK_OUT1_PORT {seq_clk} "
                                        "CONFIG.CLK_OUT2_PORT {clk_30} "
                                        "CONFIG.CLKIN1_JITTER_PS {33.330000000000005} "
                                        "CONFIG.CLKOUT1_DRIVES {Buffer} "
                                        "CONFIG.CLKOUT2_DRIVES {Buffer} "
                                        "CONFIG.CLKOUT3_DRIVES {Buffer} "
                                        "CONFIG.CLKOUT4_DRIVES {Buffer} "
                                        "CONFIG.CLKOUT5_DRIVES {Buffer} "
                                        "CONFIG.CLKOUT6_DRIVES {Buffer} "
                                        "CONFIG.CLKOUT7_DRIVES {Buffer} "
                                        "CONFIG.FEEDBACK_SOURCE {FDBK_AUTO} "
                                        "CONFIG.MMCM_DIVCLK_DIVIDE {1} "
                                        "CONFIG.MMCM_BANDWIDTH {OPTIMIZED} "
                                        "CONFIG.MMCM_CLKFBOUT_MULT_F {4.000} "
                                        "CONFIG.MMCM_CLKIN1_PERIOD {3.333} "
                                        "CONFIG.MMCM_CLKIN2_PERIOD {10.0} "
                                        "CONFIG.MMCM_COMPENSATION {AUTO} "
                                        "CONFIG.MMCM_CLKOUT0_DIVIDE_F {4.000} "
                                        "CONFIG.MMCM_CLKOUT1_DIVIDE {40} "
                                        "CONFIG.PLL_CLKIN_PERIOD {3.333} "
                                        "CONFIG.NUM_OUT_CLKS {2} "
                                        "CONFIG.CLKOUT1_JITTER {81.814} "
                                        "CONFIG.CLKOUT1_PHASE_ERROR {77.836} "
                                        "CONFIG.CLKOUT2_JITTER {128.977} "
                                        "CONFIG.CLKOUT2_PHASE_ERROR {77.836}")
            
            # Create reset synchronizers for the various clock domains
            create_ip(f, name="hedgehog/proc_sys_reset_PS_clk_250", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_clk_250/slowest_sync_clk", f"hedgehog/PS_clk_250")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_clk_250/ext_reset_in", f"hedgehog/PS_resetn")
            
            create_ip(f, name=f"hedgehog/xlconst_proc_sys_reset_PS_clk_250_locked", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name=f"hedgehog/xlconst_proc_sys_reset_PS_clk_250_locked", properties={"CONST_WIDTH": 1, "CONST_VAL": 1})
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_clk_250/dcm_locked", f"hedgehog/xlconst_proc_sys_reset_PS_clk_250_locked/Dout")
            
            create_ip(f, name="hedgehog/proc_sys_reset_PS_AXI_clk", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_AXI_clk/slowest_sync_clk", f"hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_AXI_clk/ext_reset_in", f"hedgehog/PS_resetn")
            
            create_ip(f, name=f"hedgehog/xlconst_proc_sys_reset_PS_AXI_clk_locked", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name=f"hedgehog/xlconst_proc_sys_reset_PS_AXI_clk_locked", properties={"CONST_WIDTH": 1, "CONST_VAL": 1})
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_AXI_clk/dcm_locked", f"hedgehog/xlconst_proc_sys_reset_PS_AXI_clk_locked/Dout")
            
            create_ip(f, name="hedgehog/proc_sys_reset_seq_clk", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_seq_clk/slowest_sync_clk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_seq_clk/ext_reset_in", f"hedgehog/PS_resetn")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_seq_clk/dcm_locked", f"hedgehog/clk_wiz/locked")

            # Connect the clock for the AXI lite interface to the PS clock
            connect_bd_net(f, f"hedgehog/clk_wiz/s_axi_aclk", f"hedgehog/PS_clk_250")
            connect_bd_net(f, f"hedgehog/clk_wiz/s_axi_aresetn", f"hedgehog/proc_sys_reset_PS_clk_250/peripheral_aresetn")

            # Connect the buffer output to the clock wizard and apply a constraint
            connect_bd_net(f, f"hedgehog/pl_clk_bufg/BUFG_O", f"hedgehog/clk_wiz/clk_in1")
            self._hedgehog_constraints.append("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets acadia_bd_i/hedgehog/pl_clk_bufg_BUFG_O]")
            self._hedgehog_constraints.append("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets acadia_bd_i/hedgehog/clk_wiz/inst/CLK_CORE_DRP_I/clk_inst/clk_in1_acadia_bd_clk_wiz_0]")
            
            f.write("set_property -dict [list CONFIG.FREQ_HZ {300000000}] [get_bd_intf_ports CLK104_PL_CLK]\n")
            
            # ------------------- SmartConnects -------------------- #

            # Create a SmartConnect for configuration memories and peripherals
            # 2 Masters: PS AXI Master 1, CFG AXI DataMover S2MM
            # 10 Slaves: RFDC, Clocking, ADC Axis Switch, cache, instruction memory, ADC DMA descriptors, CMACC DMA descriptors, CMACC kernel memory, DAC memory, DAC DMA descriptor
            create_ip(f, name="hedgehog/config_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, 
                         name="hedgehog/config_smartconnect", 
                         properties={"NUM_MI": 10, 
                                     "NUM_SI": 2, 
                                     "NUM_CLKS": 3})
            connect_bd_net(f, f"hedgehog/config_smartconnect/aclk", f"hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/config_smartconnect/aclk1", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/config_smartconnect/aclk2", f"hedgehog/PS_clk_250")
            connect_bd_net(f, f"hedgehog/config_smartconnect/aresetn", f"hedgehog/proc_sys_reset_PS_AXI_clk/interconnect_aresetn")
            
            # Connect the clock wizard to the smartconnect
            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/M00_AXI", f"hedgehog/clk_wiz/s_axi_lite")
            
            # Create a SmartConnect for high-performance transfers
            # 10 Masters: PS AXI Master 0, ADC AXI DataMover 0-3 S2MM, CMACC Signal AXI DataMover 0-3 S2MM, CFG AXI DataMover MM2S
            # 6 Slaves: PS AXI Slave HPC0, PS AXI Slave HPC1, PS AXI Slave HP0, PS AXI Slave HP1, PL DDR C0, PL DDR C1
            create_ip(f, name="hedgehog/memory_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, name="hedgehog/memory_smartconnect", properties={"NUM_MI": 6, "NUM_SI": 10, "NUM_CLKS": 4})
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk", f"hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk1", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk2", f"hedgehog/DDR4_C0_ui_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk3", f"hedgehog/DDR4_C1_ui_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aresetn", f"hedgehog/proc_sys_reset_PS_AXI_clk/interconnect_aresetn")
            
            # ------------------- Sequencer ----------------------------- #
            
            # Slice the PS GPIO for the sequencer run signal
            create_slice(f, name=f"hedgehog/xlslice_sequencer_run", 
                             input_width=StandardFirmware.NUM_PS_GPIO, 
                             input_from=StandardFirmware.GPIO_SEQUENCER_RUN,
                             input_to=StandardFirmware.GPIO_SEQUENCER_RUN)
            connect_bd_net(f, f"hedgehog/xlslice_sequencer_run/Din", "hedgehog/PS_GPIO_OUT")
            
            # Create synchronizers for the GPIO
            create_ip(f, name=f"hedgehog/xpm_cdc_sequencer_run", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
            set_property(f, name="hedgehog/xpm_cdc_sequencer_run", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
            connect_bd_net(f, f"hedgehog/xpm_cdc_sequencer_run/src_rst", "hedgehog/xlslice_sequencer_run/Dout")
            connect_bd_net(f, f"hedgehog/xpm_cdc_sequencer_run/dest_clk", f"hedgehog/clk_wiz/seq_clk")
            
            create_module(f, f"hedgehog/sequencer", "acadia_sequencer")
            connect_bd_net(f, "hedgehog/sequencer/clk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/sequencer/run", f"hedgehog/xpm_cdc_sequencer_run/dest_rst_out")
            connect_bd_net(f, f"hedgehog/sequencer/nrst", f"hedgehog/xpm_cdc_sequencer_run/dest_rst_out")

            # ------------------- RF Data Converters -------------------- #

            create_ip(f, name="hedgehog/rfdc", vlnv="xilinx.com:ip:usp_rf_data_converter:2.4")
            
            # Auto-generated config string by Vivado
            rfdc_config_string = "CONFIG.ADC0_Clock_Source {2} CONFIG.ADC0_Fabric_Freq {300.000} CONFIG.ADC0_Outclk_Freq {150.000} CONFIG.ADC0_PLL_Enable {true} CONFIG.ADC0_Refclk_Freq {300.000} CONFIG.ADC0_Sampling_Rate {1.2} CONFIG.ADC1_Clock_Source {2} CONFIG.ADC1_Enable {1} CONFIG.ADC1_Fabric_Freq {300.000} CONFIG.ADC1_Outclk_Freq {300.000} CONFIG.ADC1_PLL_Enable {true} CONFIG.ADC1_Refclk_Freq {300.000} CONFIG.ADC1_Sampling_Rate {2.4} CONFIG.ADC2_Clock_Dist {1} CONFIG.ADC2_Clock_Source {2} CONFIG.ADC2_Enable {1} CONFIG.ADC2_Fabric_Freq {300.000} CONFIG.ADC2_Outclk_Freq {300.000} CONFIG.ADC2_PLL_Enable {true} CONFIG.ADC2_Refclk_Freq {300.000} CONFIG.ADC2_Sampling_Rate {2.4} CONFIG.ADC3_Clock_Source {2} CONFIG.ADC3_Enable {1} CONFIG.ADC3_Fabric_Freq {30.000} CONFIG.ADC3_Outclk_Freq {300.000} CONFIG.ADC3_PLL_Enable {true} CONFIG.ADC3_Refclk_Freq {300.000} CONFIG.ADC3_Sampling_Rate {2.4} CONFIG.ADC_Coarse_Mixer_Freq00 {0} CONFIG.ADC_Coarse_Mixer_Freq01 {0} CONFIG.ADC_Coarse_Mixer_Freq02 {0} CONFIG.ADC_Coarse_Mixer_Freq03 {0} CONFIG.ADC_Coarse_Mixer_Freq10 {0} CONFIG.ADC_Coarse_Mixer_Freq11 {0} CONFIG.ADC_Coarse_Mixer_Freq12 {0} CONFIG.ADC_Coarse_Mixer_Freq13 {0} CONFIG.ADC_Coarse_Mixer_Freq20 {0} CONFIG.ADC_Coarse_Mixer_Freq21 {0} CONFIG.ADC_Coarse_Mixer_Freq22 {0} CONFIG.ADC_Coarse_Mixer_Freq23 {0} CONFIG.ADC_Coarse_Mixer_Freq30 {0} CONFIG.ADC_Coarse_Mixer_Freq31 {0} CONFIG.ADC_Coarse_Mixer_Freq32 {0} CONFIG.ADC_Coarse_Mixer_Freq33 {0} CONFIG.ADC_DSA_RTS {false} CONFIG.ADC_Data_Type00 {1} CONFIG.ADC_Data_Type01 {1} CONFIG.ADC_Data_Type02 {1} CONFIG.ADC_Data_Type03 {1} CONFIG.ADC_Data_Type10 {1} CONFIG.ADC_Data_Type11 {1} CONFIG.ADC_Data_Type12 {1} CONFIG.ADC_Data_Type13 {1} CONFIG.ADC_Data_Type20 {1} CONFIG.ADC_Data_Type21 {1} CONFIG.ADC_Data_Type22 {1} CONFIG.ADC_Data_Type23 {1} CONFIG.ADC_Data_Type30 {1} CONFIG.ADC_Data_Type31 {1} CONFIG.ADC_Data_Type32 {1} CONFIG.ADC_Data_Type33 {1} CONFIG.ADC_Data_Width00 {8} CONFIG.ADC_Decimation_Mode01 {1} CONFIG.ADC_Decimation_Mode02 {1} CONFIG.ADC_Decimation_Mode03 {1} CONFIG.ADC_Decimation_Mode10 {2} CONFIG.ADC_Decimation_Mode11 {2} CONFIG.ADC_Decimation_Mode12 {2} CONFIG.ADC_Decimation_Mode13 {2} CONFIG.ADC_Decimation_Mode20 {2} CONFIG.ADC_Decimation_Mode21 {2} CONFIG.ADC_Decimation_Mode22 {2} CONFIG.ADC_Decimation_Mode23 {2} CONFIG.ADC_Decimation_Mode30 {20} CONFIG.ADC_Decimation_Mode31 {20} CONFIG.ADC_Decimation_Mode32 {20} CONFIG.ADC_Decimation_Mode33 {20} CONFIG.ADC_Dither00 {false} CONFIG.ADC_Dither01 {false} CONFIG.ADC_Dither02 {false} CONFIG.ADC_Dither03 {false} CONFIG.ADC_Dither10 {false} CONFIG.ADC_Dither11 {false} CONFIG.ADC_Dither12 {false} CONFIG.ADC_Dither13 {false} CONFIG.ADC_Dither20 {false} CONFIG.ADC_Dither21 {false} CONFIG.ADC_Dither22 {false} CONFIG.ADC_Dither23 {false} CONFIG.ADC_Dither30 {false} CONFIG.ADC_Dither31 {false} CONFIG.ADC_Dither32 {false} CONFIG.ADC_Dither33 {false} CONFIG.ADC_Mixer_Mode00 {0} CONFIG.ADC_Mixer_Mode01 {0} CONFIG.ADC_Mixer_Mode02 {0} CONFIG.ADC_Mixer_Mode03 {0} CONFIG.ADC_Mixer_Mode10 {0} CONFIG.ADC_Mixer_Mode11 {0} CONFIG.ADC_Mixer_Mode12 {0} CONFIG.ADC_Mixer_Mode13 {0} CONFIG.ADC_Mixer_Mode20 {0} CONFIG.ADC_Mixer_Mode21 {0} CONFIG.ADC_Mixer_Mode22 {0} CONFIG.ADC_Mixer_Mode23 {0} CONFIG.ADC_Mixer_Mode30 {0} CONFIG.ADC_Mixer_Mode31 {0} CONFIG.ADC_Mixer_Mode32 {0} CONFIG.ADC_Mixer_Mode33 {0} CONFIG.ADC_Mixer_Type00 {2} CONFIG.ADC_Mixer_Type01 {2} CONFIG.ADC_Mixer_Type02 {2} CONFIG.ADC_Mixer_Type03 {2} CONFIG.ADC_Mixer_Type10 {2} CONFIG.ADC_Mixer_Type11 {2} CONFIG.ADC_Mixer_Type12 {2} CONFIG.ADC_Mixer_Type13 {2} CONFIG.ADC_Mixer_Type20 {2} CONFIG.ADC_Mixer_Type21 {2} CONFIG.ADC_Mixer_Type22 {2} CONFIG.ADC_Mixer_Type23 {2} CONFIG.ADC_Mixer_Type30 {2} CONFIG.ADC_Mixer_Type31 {2} CONFIG.ADC_Mixer_Type32 {2} CONFIG.ADC_Mixer_Type33 {2} CONFIG.ADC_NCO_RTS {true} CONFIG.ADC_OBS03 {false} CONFIG.ADC_OBS11 {false} CONFIG.ADC_OBS12 {false} CONFIG.ADC_OBS13 {false} CONFIG.ADC_OBS21 {false} CONFIG.ADC_OBS22 {false} CONFIG.ADC_OBS23 {false} CONFIG.ADC_OBS31 {false} CONFIG.ADC_OBS32 {false} CONFIG.ADC_OBS33 {false} CONFIG.ADC_RESERVED_1_00 {false} CONFIG.ADC_RESERVED_1_01 {false} CONFIG.ADC_RESERVED_1_02 {false} CONFIG.ADC_RESERVED_1_03 {false} CONFIG.ADC_RESERVED_1_10 {false} CONFIG.ADC_RESERVED_1_11 {false} CONFIG.ADC_RESERVED_1_12 {false} CONFIG.ADC_RESERVED_1_13 {false} CONFIG.ADC_RESERVED_1_20 {false} CONFIG.ADC_RESERVED_1_21 {false} CONFIG.ADC_RESERVED_1_22 {false} CONFIG.ADC_RESERVED_1_23 {false} CONFIG.ADC_RESERVED_1_30 {false} CONFIG.ADC_RESERVED_1_31 {false} CONFIG.ADC_RESERVED_1_32 {false} CONFIG.ADC_RESERVED_1_33 {false} CONFIG.ADC_RTS {false} CONFIG.ADC_Slice01_Enable {true} CONFIG.ADC_Slice02_Enable {true} CONFIG.ADC_Slice03_Enable {true} CONFIG.ADC_Slice10_Enable {true} CONFIG.ADC_Slice11_Enable {true} CONFIG.ADC_Slice12_Enable {true} CONFIG.ADC_Slice13_Enable {true} CONFIG.ADC_Slice20_Enable {true} CONFIG.ADC_Slice21_Enable {true} CONFIG.ADC_Slice22_Enable {true} CONFIG.ADC_Slice23_Enable {true} CONFIG.ADC_Slice30_Enable {true} CONFIG.ADC_Slice31_Enable {true} CONFIG.ADC_Slice32_Enable {true} CONFIG.ADC_Slice33_Enable {true} CONFIG.Axiclk_Freq {250} CONFIG.DAC0_Clock_Source {6} CONFIG.DAC0_Enable {1} CONFIG.DAC0_Fabric_Freq {300.000} CONFIG.DAC0_Outclk_Freq {300.000} CONFIG.DAC0_PLL_Enable {true} CONFIG.DAC0_Refclk_Freq {300.000} CONFIG.DAC0_Sampling_Rate {4.8} CONFIG.DAC1_Clock_Source {6} CONFIG.DAC1_Enable {1} CONFIG.DAC1_Fabric_Freq {300.000} CONFIG.DAC1_Outclk_Freq {300.000} CONFIG.DAC1_PLL_Enable {true} CONFIG.DAC1_Refclk_Freq {300.000} CONFIG.DAC1_Sampling_Rate {4.8} CONFIG.DAC2_Clock_Dist {1} CONFIG.DAC2_Enable {1} CONFIG.DAC2_Fabric_Freq {300.000} CONFIG.DAC2_Outclk_Freq {300.000} CONFIG.DAC2_PLL_Enable {true} CONFIG.DAC2_Refclk_Freq {300.000} CONFIG.DAC2_Sampling_Rate {9.6} CONFIG.DAC2_VOP {40.0} CONFIG.DAC3_Clock_Source {6} CONFIG.DAC3_Enable {1} CONFIG.DAC3_Fabric_Freq {300.000} CONFIG.DAC3_Outclk_Freq {300.000} CONFIG.DAC3_PLL_Enable {true} CONFIG.DAC3_Refclk_Freq {300.000} CONFIG.DAC3_Sampling_Rate {9.6} CONFIG.DAC3_VOP {40.0} CONFIG.DAC_Coarse_Mixer_Freq00 {3} CONFIG.DAC_Coarse_Mixer_Freq01 {3} CONFIG.DAC_Coarse_Mixer_Freq02 {3} CONFIG.DAC_Coarse_Mixer_Freq03 {3} CONFIG.DAC_Coarse_Mixer_Freq10 {3} CONFIG.DAC_Coarse_Mixer_Freq11 {3} CONFIG.DAC_Coarse_Mixer_Freq12 {3} CONFIG.DAC_Coarse_Mixer_Freq13 {3} CONFIG.DAC_Coarse_Mixer_Freq20 {3} CONFIG.DAC_Coarse_Mixer_Freq21 {3} CONFIG.DAC_Coarse_Mixer_Freq22 {3} CONFIG.DAC_Coarse_Mixer_Freq23 {3} CONFIG.DAC_Coarse_Mixer_Freq30 {3} CONFIG.DAC_Coarse_Mixer_Freq31 {3} CONFIG.DAC_Coarse_Mixer_Freq32 {3} CONFIG.DAC_Coarse_Mixer_Freq33 {3} CONFIG.DAC_Data_Width00 {8} CONFIG.DAC_Data_Width01 {8} CONFIG.DAC_Data_Width02 {8} CONFIG.DAC_Data_Width03 {8} CONFIG.DAC_Data_Width10 {8} CONFIG.DAC_Data_Width11 {8} CONFIG.DAC_Data_Width12 {8} CONFIG.DAC_Data_Width13 {8} CONFIG.DAC_Data_Width20 {8} CONFIG.DAC_Data_Width21 {8} CONFIG.DAC_Data_Width22 {8} CONFIG.DAC_Data_Width23 {8} CONFIG.DAC_Data_Width30 {8} CONFIG.DAC_Data_Width31 {8} CONFIG.DAC_Data_Width32 {8} CONFIG.DAC_Data_Width33 {8} CONFIG.DAC_Interpolation_Mode00 {4} CONFIG.DAC_Interpolation_Mode01 {4} CONFIG.DAC_Interpolation_Mode02 {4} CONFIG.DAC_Interpolation_Mode03 {4} CONFIG.DAC_Interpolation_Mode10 {4} CONFIG.DAC_Interpolation_Mode11 {4} CONFIG.DAC_Interpolation_Mode12 {4} CONFIG.DAC_Interpolation_Mode13 {4} CONFIG.DAC_Interpolation_Mode20 {4} CONFIG.DAC_Interpolation_Mode21 {4} CONFIG.DAC_Interpolation_Mode22 {4} CONFIG.DAC_Interpolation_Mode23 {4} CONFIG.DAC_Interpolation_Mode30 {4} CONFIG.DAC_Interpolation_Mode31 {4} CONFIG.DAC_Interpolation_Mode32 {4} CONFIG.DAC_Interpolation_Mode33 {4} CONFIG.DAC_Mixer_Mode00 {0} CONFIG.DAC_Mixer_Mode01 {0} CONFIG.DAC_Mixer_Mode02 {0} CONFIG.DAC_Mixer_Mode03 {0} CONFIG.DAC_Mixer_Mode10 {0} CONFIG.DAC_Mixer_Mode11 {0} CONFIG.DAC_Mixer_Mode12 {0} CONFIG.DAC_Mixer_Mode13 {0} CONFIG.DAC_Mixer_Mode20 {0} CONFIG.DAC_Mixer_Mode21 {0} CONFIG.DAC_Mixer_Mode22 {0} CONFIG.DAC_Mixer_Mode23 {0} CONFIG.DAC_Mixer_Mode30 {0} CONFIG.DAC_Mixer_Mode31 {0} CONFIG.DAC_Mixer_Mode32 {0} CONFIG.DAC_Mixer_Mode33 {0} CONFIG.DAC_Mixer_Type00 {2} CONFIG.DAC_Mixer_Type01 {2} CONFIG.DAC_Mixer_Type02 {2} CONFIG.DAC_Mixer_Type03 {2} CONFIG.DAC_Mixer_Type10 {2} CONFIG.DAC_Mixer_Type11 {2} CONFIG.DAC_Mixer_Type12 {2} CONFIG.DAC_Mixer_Type13 {2} CONFIG.DAC_Mixer_Type20 {2} CONFIG.DAC_Mixer_Type21 {2} CONFIG.DAC_Mixer_Type22 {2} CONFIG.DAC_Mixer_Type23 {2} CONFIG.DAC_Mixer_Type30 {2} CONFIG.DAC_Mixer_Type31 {2} CONFIG.DAC_Mixer_Type32 {2} CONFIG.DAC_Mixer_Type33 {2} CONFIG.DAC_Mode00 {0} CONFIG.DAC_Mode01 {0} CONFIG.DAC_Mode02 {0} CONFIG.DAC_Mode03 {0} CONFIG.DAC_Mode10 {0} CONFIG.DAC_Mode11 {0} CONFIG.DAC_Mode12 {0} CONFIG.DAC_Mode13 {0} CONFIG.DAC_Mode20 {1} CONFIG.DAC_Mode21 {1} CONFIG.DAC_Mode22 {1} CONFIG.DAC_Mode23 {1} CONFIG.DAC_Mode30 {1} CONFIG.DAC_Mode31 {1} CONFIG.DAC_Mode32 {1} CONFIG.DAC_Mode33 {1} CONFIG.DAC_NCO_RTS {true} CONFIG.DAC_Nyquist20 {1} CONFIG.DAC_Nyquist21 {1} CONFIG.DAC_Nyquist22 {1} CONFIG.DAC_Nyquist23 {1} CONFIG.DAC_Nyquist30 {1} CONFIG.DAC_Nyquist31 {1} CONFIG.DAC_Nyquist32 {1} CONFIG.DAC_Nyquist33 {1} CONFIG.DAC_RESERVED_1_00 {false} CONFIG.DAC_RESERVED_1_01 {false} CONFIG.DAC_RESERVED_1_02 {false} CONFIG.DAC_RESERVED_1_03 {false} CONFIG.DAC_RESERVED_1_10 {false} CONFIG.DAC_RESERVED_1_11 {false} CONFIG.DAC_RESERVED_1_12 {false} CONFIG.DAC_RESERVED_1_13 {false} CONFIG.DAC_RESERVED_1_20 {false} CONFIG.DAC_RESERVED_1_21 {false} CONFIG.DAC_RESERVED_1_22 {false} CONFIG.DAC_RESERVED_1_23 {false} CONFIG.DAC_RESERVED_1_30 {false} CONFIG.DAC_RESERVED_1_31 {false} CONFIG.DAC_RESERVED_1_32 {false} CONFIG.DAC_RESERVED_1_33 {false} CONFIG.DAC_RTS {false} CONFIG.DAC_Slice00_Enable {true} CONFIG.DAC_Slice01_Enable {true} CONFIG.DAC_Slice02_Enable {true} CONFIG.DAC_Slice03_Enable {true} CONFIG.DAC_Slice10_Enable {true} CONFIG.DAC_Slice11_Enable {true} CONFIG.DAC_Slice12_Enable {true} CONFIG.DAC_Slice13_Enable {true} CONFIG.DAC_Slice20_Enable {true} CONFIG.DAC_Slice21_Enable {true} CONFIG.DAC_Slice22_Enable {true} CONFIG.DAC_Slice23_Enable {true} CONFIG.DAC_Slice30_Enable {true} CONFIG.DAC_Slice31_Enable {true} CONFIG.DAC_Slice32_Enable {true} CONFIG.DAC_Slice33_Enable {true} CONFIG.DAC_VOP_RTS {false} CONFIG.ADC0_Multi_Tile_Sync {true} CONFIG.DAC0_Multi_Tile_Sync {true} CONFIG.DAC_TDD_RTS00 {1} CONFIG.DAC_TDD_RTS01 {1} CONFIG.DAC_TDD_RTS02 {1} CONFIG.DAC_TDD_RTS03 {1} CONFIG.DAC1_Multi_Tile_Sync {true} CONFIG.DAC_TDD_RTS10 {1} CONFIG.DAC_TDD_RTS11 {1} CONFIG.DAC_TDD_RTS12 {1} CONFIG.DAC_TDD_RTS13 {1} CONFIG.DAC2_Multi_Tile_Sync {true} CONFIG.DAC_TDD_RTS20 {1} CONFIG.DAC_TDD_RTS21 {1} CONFIG.DAC_TDD_RTS22 {1} CONFIG.DAC_TDD_RTS23 {1} CONFIG.DAC3_Multi_Tile_Sync {true} CONFIG.DAC_TDD_RTS30 {1} CONFIG.DAC_TDD_RTS31 {1} CONFIG.DAC_TDD_RTS32 {1} CONFIG.DAC_TDD_RTS33 {1} CONFIG.ADC_RTS {true} CONFIG.DAC_RTS {true} CONFIG.DAC_VOP_RTS {true} CONFIG.ADC_DSA_RTS {true}"
            
            set_property(f, name="hedgehog/rfdc", properties=rfdc_config_string)
            
            connect_bd_net(f, f"hedgehog/rfdc/s_axi_aclk", f"hedgehog/PS_clk_250")            
            connect_bd_net(f, f"hedgehog/rfdc/s_axi_aresetn", f"hedgehog/proc_sys_reset_PS_clk_250/peripheral_aresetn")

            # Connect the analog inputs and outputs to the external ports through the hedgehog logic boundary
            for d in ["out", "in"]:
                for tile in range(4):
                    for block in range(4):
                        connect_bd_intf_net(f, f"hedgehog/rfdc/v{d}{tile}{block}", f"hedgehog/v{d}{tile}{block}")

            connect_bd_intf_net(f, f"hedgehog/rfdc/adc2_clk", f"hedgehog/adc2_clk")
            connect_bd_intf_net(f, f"hedgehog/rfdc/dac2_clk", f"hedgehog/dac2_clk")
            connect_bd_intf_net(f, f"hedgehog/rfdc/sysref_in", f"hedgehog/sysref_in")
            
            # Connect the RFDC stream clocks and resets
            for i in range(4):
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")        
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aclk", f"hedgehog/clk_wiz/{'clk_30' if i == 3 else 'seq_clk'}")
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")

            # Connect RFDC to the smartconnect through an AXI register slice and assign address space
            create_ip(f, name="hedgehog/axi_register_slice_rfdc", vlnv="xilinx.com:ip:axi_register_slice:2.1")
            connect_bd_intf_net(f, "hedgehog/axi_register_slice_rfdc/M_AXI", "hedgehog/rfdc/s_axi")
            connect_bd_intf_net(f, "hedgehog/axi_register_slice_rfdc/S_AXI", "hedgehog/config_smartconnect/M01_AXI")
            connect_bd_net(f, "hedgehog/axi_register_slice_rfdc/aclk", "hedgehog/PS_clk_250")
            connect_bd_net(f, "hedgehog/axi_register_slice_rfdc/aresetn", "hedgehog/proc_sys_reset_PS_clk_250/peripheral_aresetn")
            
            # Synchronize the SYSREF signal from the CLK104
            create_module(f, f"hedgehog/pl_sysref_capture", "acadia_sysref_capture")
            connect_bd_intf_net(f, "hedgehog/CLK104_PL_SYSREF", "hedgehog/pl_sysref_capture/sysref")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/clk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/sysref_out", "hedgehog/rfdc/user_sysref_dac")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/sysref_out", "hedgehog/rfdc/user_sysref_adc")
            
            # ------------------- ADC AXIS Switch -------------------- #

            # Create an AXI switch for multiplexing the ADC outputs to the AXI DMAs
            create_ip(f, name="hedgehog/axis_switch_adc", vlnv="xilinx.com:ip:axis_switch:1.1")
            set_property(f, name="hedgehog/axis_switch_adc", 
                             properties="CONFIG.TDATA_NUM_BYTES.VALUE_SRC USER "
                                        "CONFIG.HAS_TREADY.VALUE_SRC USER "
                                        "CONFIG.HAS_TSTRB.VALUE_SRC USER "
                                        "CONFIG.HAS_TKEEP.VALUE_SRC USER "
                                        "CONFIG.HAS_TLAST.VALUE_SRC USER "
                                        "CONFIG.TID_WIDTH.VALUE_SRC USER "
                                        "CONFIG.TDEST_WIDTH.VALUE_SRC USER "
                                        "CONFIG.TUSER_WIDTH.VALUE_SRC USER")
            set_property(f, name="hedgehog/axis_switch_adc", 
                             properties="CONFIG.NUM_SI {16} "
                                        "CONFIG.NUM_MI {8} "
                                        "CONFIG.ROUTING_MODE {1} "
                                        "CONFIG.TDATA_NUM_BYTES {16} "
                                        "CONFIG.DECODER_REG {1} "
                                        "CONFIG.OUTPUT_REG {1} "
                                        "CONFIG.HAS_TLAST {0} "
                                        "CONFIG.HAS_TREADY {0} "
                                        "CONFIG.TDEST_WIDTH {0}")

            connect_bd_net(f, f"hedgehog/axis_switch_adc/aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # Connect the switch to the AXI network and assign it an address in the PS address space
            connect_bd_intf_net(f, f"hedgehog/axis_switch_adc/S_AXI_CTRL", f"hedgehog/config_smartconnect/M02_AXI")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/s_axi_ctrl_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/s_axi_ctrl_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

            # Connect the ADC interfaces to the AXIS switch through a register
            for channel in range(16):
                tile = channel // 4
                block = channel % 4
                create_ip(f, name=f"hedgehog/adc{channel}_register", vlnv="xilinx.com:ip:axis_register_slice:1.1")
                set_property(f, name=f"hedgehog/adc{channel}_register", 
                                 properties={"HAS_TREADY.VALUE_SRC": "USER", 
                                             "TDATA_NUM_BYTES.VALUE_SRC": "USER"})
                set_property(f, name=f"hedgehog/adc{channel}_register",
                                 properties={"TDATA_NUM_BYTES": 16, 
                                             "HAS_TREADY": 0})
                connect_bd_net(f, f"hedgehog/adc{channel}_register/aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/adc{channel}_register/aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                
                create_ip(f, name=f"hedgehog/xlconst_adc{channel}", vlnv="xilinx.com:ip:xlconstant:1.1")
                set_property(f, name=f"hedgehog/xlconst_adc{channel}", properties={"CONST_WIDTH": 1, "CONST_VAL": 0})
                connect_bd_net(f, f"hedgehog/adc{channel}_register/s_axis_tdata", f"hedgehog/rfdc/m{tile}{block}_axis_tdata")
                connect_bd_net(f, f"hedgehog/adc{channel}_register/s_axis_tvalid", f"hedgehog/xlconst_adc{channel}/Dout")
                
                connect_bd_intf_net(f, f"hedgehog/adc{channel}_register/M_AXIS", 
                                       f"hedgehog/axis_switch_adc/S{channel:02d}_AXIS")

            # ------------------- PS AXI Connections -------------------- #

            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/S00_AXI", f"hedgehog/PS_M_AXI0")
            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/S00_AXI", f"hedgehog/PS_M_AXI1")
            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M00_AXI", f"hedgehog/PS_S_AXI_HPC0")
            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M01_AXI", f"hedgehog/PS_S_AXI_HPC1")
            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M02_AXI", f"hedgehog/PS_S_AXI_HP0")
            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M03_AXI", f"hedgehog/PS_S_AXI_HP1")
                    
            # ------------------- DDR4 Connections -------------------- #

            connect_bd_intf_net(f, f"hedgehog/DDR4_C0_S_AXI", f"hedgehog/memory_smartconnect/M04_AXI")
            connect_bd_intf_net(f, f"hedgehog/DDR4_C1_S_AXI", f"hedgehog/memory_smartconnect/M05_AXI")

            # ------------------- Sequencer Bus and Associated Modules -------------------- #

            # Add the sequencer bus decoder and connect it to the sequencer bus
            create_module(f, f"hedgehog/sequencer_bus_decoder", "sequencer_bus_decoder")
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/master_bus", f"hedgehog/sequencer/mem_bus")

            # Create a RFDC real-time port register interface
            create_module(f, f"hedgehog/rfdc_rts_regs", "acadia_rfdc_rts_regs")
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nco_dest_clk", f"hedgehog/PS_clk_250")
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/rfdc_rts_regs", f"hedgehog/rfdc_rts_regs/master_bus")
                             
            for tile in range(4):
                connect_bd_intf_net(f, f"hedgehog/rfdc/dac{tile}_nco", f"hedgehog/rfdc_rts_regs/dac{tile}_nco")
                connect_bd_intf_net(f, f"hedgehog/rfdc/dac{tile}_rts", f"hedgehog/rfdc_rts_regs/dac{tile}_rts")
                connect_bd_intf_net(f, f"hedgehog/rfdc/dac{tile}_vop_rts", f"hedgehog/rfdc_rts_regs/dac{tile}_vop_rts")
                
                connect_bd_intf_net(f, f"hedgehog/rfdc/adc{tile}_nco", f"hedgehog/rfdc_rts_regs/adc{tile}_nco")
                connect_bd_intf_net(f, f"hedgehog/rfdc/adc{tile}_rts", f"hedgehog/rfdc_rts_regs/adc{tile}_rts")
                connect_bd_intf_net(f, f"hedgehog/rfdc/adc{tile}_dsa_rts", f"hedgehog/rfdc_rts_regs/adc{tile}_dsa_rts")
                
                for block in range(4):
                    # We'll only connect the DAC TDD signals here
                    connect_bd_net(f, f"hedgehog/rfdc/dac{tile}{block}_tdd_mode", f"hedgehog/rfdc_rts_regs/dac{tile}{block}_tdd_mode")
            
            # Create the interface to the PS DMA
            create_module(f, f"hedgehog/zdma_controller", "acadia_zdma_controller")
            connect_bd_net(f, "hedgehog/zdma_controller/nrst", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            connect_bd_intf_net(f, "hedgehog/sequencer_bus_decoder/zdma_controller", "hedgehog/zdma_controller/master_bus")
            
            # Add all the dataports
            for module in self._modules:
                if isinstance(module, BusDataport):
                    create_module(f, f"hedgehog/{module.name}_dataport", module.name)
                    connect_bd_intf_net(f, f"hedgehog/{module.name}_dataport/master_bus", f"hedgehog/sequencer_bus_decoder/{module.name}")
                    connect_bd_net(f, f"hedgehog/{module.name}_dataport/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                    
            # Connect the CLK104 sync pin
            connect_bd_net(f, "hedgehog/clk104_sync_in_dataport/sync", "hedgehog/clk104_sync_in")

            # ------------------- Sequencer cache -------------------- #

            # Add cache memory and connect it to the sequencer bus decoder
            create_module(f, f"hedgehog/cache_memory", f"cache_axi_memory")
            
            # Connect the cache to the smartconnect
            connect_bd_intf_net(f, f"hedgehog/cache_memory/s_axi", f"hedgehog/config_smartconnect/M03_AXI")
            connect_bd_net(f, "hedgehog/cache_memory/s_axi_aclk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, "hedgehog/cache_memory/s_axi_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # Connect the cache to the sequencer bus decoder
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/cache", f"hedgehog/cache_memory/mem0")
            
            # ------------------- Sequencer Instruction Memory -------------------- #

            # Create instruction memory for the sequencer and add it to the memory decoder
            create_module(f, "hedgehog/instruction_memory", "instruction_axi_memory")
            
            connect_bd_intf_net(f, f"hedgehog/instruction_memory/s_axi", f"hedgehog/config_smartconnect/M04_AXI")
            connect_bd_net(f, "hedgehog/instruction_memory/s_axi_aclk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, "hedgehog/instruction_memory/s_axi_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            connect_bd_intf_net(f, f"hedgehog/instruction_memory/mem0", f"hedgehog/sequencer/instruction_mem")

            # ------------------- Sequencer flags -------------------- #

            create_ip(f, name="hedgehog/xlconst_0", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name="hedgehog/xlconst_0", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
            connect_bd_net(f, f"hedgehog/sequencer/ext_in", f"hedgehog/xlconst_0/Dout")
            
            # ------------------- PS GPIO and Interrupt Connections -------------------- #
            
            # Create a concatenator for the PS inputs
            create_concatenator(f, "hedgehog/xlconcat_ps_gpio_in", [32, 32, StandardFirmware.NUM_PS_GPIO % 32])
            connect_bd_net(f, "hedgehog/xlconcat_ps_gpio_in/dout", "hedgehog/PS_GPIO_IN")
            
            for idx, gpio_port in enumerate([3,4,5]):
                connect_bd_net(f, f"hedgehog/xlconcat_ps_gpio_in/In{idx}", f"hedgehog/ps_gpio{gpio_port}_dataport/gpio_in")
                
                # Slice the PS outputs
                create_slice(f, name=f"hedgehog/xlslice_ps_gpio{gpio_port}_out", 
                                 input_width=StandardFirmware.NUM_PS_GPIO, 
                                 input_from=(StandardFirmware.NUM_PS_GPIO-1 if gpio_port == 5 else (idx+1)*32-1),
                                 input_to=idx*32)
                connect_bd_net(f, f"hedgehog/xlslice_ps_gpio{gpio_port}_out/Din", f"hedgehog/PS_GPIO_OUT")
                connect_bd_net(f, f"hedgehog/xlslice_ps_gpio{gpio_port}_out/Dout", f"hedgehog/ps_gpio{gpio_port}_dataport/gpio_out")
                
            # IRQ signals
            for i in range(StandardFirmware.NUM_PS_IRQ):
                connect_bd_net(f, f"hedgehog/ps_irq_dataport/irq{i}", f"hedgehog/PS_IRQ{i}")
                
            # ------------------- PS GDMA Connections -------------------- #

            connect_bd_net(f, f"hedgehog/zdma_controller/cack", f"hedgehog/ps_gdma_cack")
            connect_bd_net(f, f"hedgehog/zdma_controller/tvld", f"hedgehog/ps_gdma_tvld")
            connect_bd_net(f, f"hedgehog/zdma_controller/tack", f"hedgehog/ps_gdma_tack")
            connect_bd_net(f, f"hedgehog/zdma_controller/cvld", f"hedgehog/ps_gdma_cvld")
            connect_bd_net(f, f"hedgehog/ps_irq_dataport/gdma_irq", f"hedgehog/ps_gdma_irq")
            
            # Create a concatenator for the clock signals
            create_concatenator(f, "hedgehog/xlconcat_ps_gdma_clk", [1]*StandardFirmware.NUM_PS_GDMA)
            connect_bd_net(f, f"hedgehog/xlconcat_ps_gdma_clk/dout", f"hedgehog/ps_gdma_clk")
            for i in range(StandardFirmware.NUM_PS_GDMA):
                connect_bd_net(f, f"hedgehog/xlconcat_ps_gdma_clk/In{i}", f"hedgehog/clk_wiz/seq_clk")
            
            # ------------------- DAC Memory -------------------- #
            create_module(f, f"hedgehog/dac_memory", f"dac_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/dac_memory/s_axi", "hedgehog/config_smartconnect/M05_AXI")
            connect_bd_net(f, f"hedgehog/dac_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/dac_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                
            # ------------------- DAC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/dac_dma_descriptor_memory", f"dac_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi", "hedgehog/config_smartconnect/M06_AXI")
            connect_bd_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                
            # ------------------- ADC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/adc_dma_descriptor_memory", f"adc_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi", f"hedgehog/config_smartconnect/M07_AXI")
            connect_bd_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # ------------------- CMACC Kernel Memory -------------------- #
            create_module(f, f"hedgehog/cmacc_kernel_memory", f"cmacc_kernel_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/cmacc_kernel_memory/s_axi", f"hedgehog/config_smartconnect/M08_AXI")
            connect_bd_net(f, f"hedgehog/cmacc_kernel_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/cmacc_kernel_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # ------------------- CMACC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/cmacc_dma_descriptor_memory", f"cmacc_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi", f"hedgehog/config_smartconnect/M09_AXI")
            connect_bd_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

            # ------------------- Configuration DataMover -------------------- #

            # First, create the bus-driven DataMover Controller and connect it to the bus
            create_module(f, f"hedgehog/datamover_controller", "datamover_controller")
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/datamover_controller", f"hedgehog/datamover_controller/master_bus")
            connect_bd_net(f, f"hedgehog/datamover_controller/clk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/datamover_controller/nrst", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

            # Create the DataMover itself
            create_ip(f, name="hedgehog/cfg_axi_dm", vlnv="xilinx.com:ip:axi_datamover:5.1")
            set_property(f, name="hedgehog/cfg_axi_dm", properties={"c_m_axi_s2mm_data_width.VALUE_SRC": "USER", "c_s_axis_s2mm_tdata_width.VALUE_SRC": "USER"})
            set_property(f, name="hedgehog/cfg_axi_dm", 
                             properties="CONFIG.c_m_axi_mm2s_data_width {128} "
                                        "CONFIG.c_m_axis_mm2s_tdata_width {128} "
                                        "CONFIG.c_mm2s_burst_size {256} "
                                        "CONFIG.c_mm2s_btt_used {23} "
                                        "CONFIG.c_include_s2mm {Full} "
                                        "CONFIG.c_m_axi_s2mm_data_width {128} "
                                        "CONFIG.c_s_axis_s2mm_tdata_width {128} "
                                        "CONFIG.c_s2mm_burst_size {256} "
                                        "CONFIG.c_include_s2mm_stsfifo {true} "
                                        "CONFIG.c_s2mm_btt_used {23} "
                                        "CONFIG.c_s2mm_support_indet_btt {true} "
                                        "CONFIG.c_s2mm_addr_pipe_depth {3} "
                                        "CONFIG.c_mm2s_include_sf {false} "
                                        "CONFIG.c_s2mm_include_sf {false} "
                                        "CONFIG.c_m_axi_s2mm_awid {0} "
                                        "CONFIG.c_enable_cache_user {true} "
                                        "CONFIG.c_enable_s2mm {1} "
                                        "CONFIG.c_addr_width {40}")

            # Connect clocks and resets for the command and status port (for some reason the clock pins are different between s2mm and mm2s)
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_mm2s_cmdsts_aclk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_mm2s_cmdsts_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_s2mm_cmdsts_awclk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_s2mm_cmdsts_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

            # For this DataMover, we want to connect the MM2S and S2MM streams to each other
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/S_AXIS_S2MM", f"hedgehog/cfg_axi_dm/M_AXIS_MM2S")

            # Connect the MM2S AXI master to the memory smartconnect
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXI_MM2S", f"hedgehog/memory_smartconnect/S09_AXI")

            # Connect the S2MM AXI master to the configuration smartconnect
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXI_S2MM", f"hedgehog/config_smartconnect/S01_AXI")

            for direction in ["mm2s","s2mm"]:
                # Connect AXI Master clocks and resets
                connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axi_{direction}_aclk", "hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axi_{direction}_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the MM2S command and status interfaces to the bus-driven DataMover controller
                connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/S_AXIS_{direction.upper()}_CMD", f"hedgehog/datamover_controller/cfg_dm_{direction}_CMD")
                connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXIS_{direction.upper()}_STS", f"hedgehog/datamover_controller/cfg_dm_{direction}_STS")

                # Connect the error signal to the controller
                connect_bd_net(f, f"hedgehog/cfg_axi_dm/{direction}_err", f"hedgehog/datamover_controller/cfg_dm_{direction}_err")
            
            # ------------------- ADC DMAs -------------------- #

            for d in range(StandardFirmware.NUM_ADC):

                # ------------------- Real-time DMAs -------------------- #
                create_module(f, f"hedgehog/adc_dma{d}", "acadia_dma")
                connect_bd_net(f, f"hedgehog/adc_dma{d}/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/adc_dma{d}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the ADC DMA signals to the dataports
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/adc_dma{d}_fifo_mosi", f"hedgehog/adc_dma{d}/descriptor_address_fifo_in")
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/adc_dma{d}_fifo_wr", f"hedgehog/adc_dma{d}/descriptor_address_fifo_wr")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/adc_dma{d}", f"hedgehog/adc_dma{d}/trigger")
                connect_bd_net(f, f"hedgehog/dma_running_dataport/adc_dma{d}", f"hedgehog/adc_dma{d}/running")
                connect_bd_net(f, f"hedgehog/dma_fifo_empty_dataport/adc_dma{d}", f"hedgehog/adc_dma{d}/descriptor_address_fifo_empty")
                connect_bd_net(f, f"hedgehog/dma_fifo_almost_empty_dataport/adc_dma{d}", f"hedgehog/adc_dma{d}/descriptor_address_fifo_almost_empty")
                
                # Connect to descriptor memory
                connect_bd_intf_net(f, f"hedgehog/adc_dma{d}/descriptor_mem", f"hedgehog/adc_dma_descriptor_memory/mem{d}")
                
                # ------------------- Stream FIFOs -------------------- #

                create_module(f, f"hedgehog/fifo_adc_dm{d}", "acadia_adc_fifo")
                set_property(f, name=f"hedgehog/fifo_adc_dm{d}", properties={"WIDTH": 128, "TKEEP_WIDTH": 16, "DEPTH": StandardFirmware.ADC_FIFO_DEPTH})

                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the FIFO stream input to the AXIS Switch output by creating a slice
                create_slice(f, f"hedgehog/xlslice_fifo_adc_dm{d}_data", input_width=128*8, input_to=d*128, input_from=d*128 + 127)
                connect_bd_net(f, f"hedgehog/xlslice_fifo_adc_dm{d}_data/Din", f"hedgehog/axis_switch_adc/m_axis_tdata")
                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/din", f"hedgehog/xlslice_fifo_adc_dm{d}_data/Dout")
                
                # Connect the ADC DMA AXIS handshaking signals to the AXIS FIFO handshaking inputs
                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/wr_en", f"hedgehog/adc_dma{d}/addr_tvalid")

                # ------------------- AXI DataMovers -------------------- #

                # Create the DataMover itself
                create_ip(f, name=f"hedgehog/adc_dm{d}", vlnv="xilinx.com:ip:axi_datamover:5.1")
                set_property(f, name=f"hedgehog/adc_dm{d}", 
                                 properties="CONFIG.c_m_axi_s2mm_data_width.VALUE_SRC USER CONFIG.c_s_axis_s2mm_tdata_width.VALUE_SRC USER")
                set_property(f, name=f"hedgehog/adc_dm{d}", 
                                 properties="CONFIG.c_include_mm2s {Omit} "
                                            "CONFIG.c_include_mm2s_stsfifo {false} "
                                            "CONFIG.c_m_axi_s2mm_data_width {128} "
                                            "CONFIG.c_s_axis_s2mm_tdata_width {128} "
                                            "CONFIG.c_s2mm_btt_used {23} "
                                            "CONFIG.c_s2mm_support_indet_btt {true} "
                                            "CONFIG.c_mm2s_include_sf {false} "
                                            "CONFIG.c_s2mm_include_sf {false} "
                                            "CONFIG.c_enable_cache_user {true} "
                                            "CONFIG.c_enable_mm2s {0} "
                                            "CONFIG.c_enable_s2mm_adv_sig {0} "
                                            "CONFIG.c_addr_width {40}")

                # Connect clocks and resets
                connect_bd_net(f, f"hedgehog/adc_dm{d}/m_axi_s2mm_aclk", "hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/adc_dm{d}/m_axi_s2mm_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                connect_bd_net(f, f"hedgehog/adc_dm{d}/m_axis_s2mm_cmdsts_awclk", "hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/adc_dm{d}/m_axis_s2mm_cmdsts_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the S2MM command and status interfaces to the bus-driven DataMover controller
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/S_AXIS_S2MM_CMD", f"hedgehog/datamover_controller/adc_dm{d}_cmd")
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/M_AXIS_S2MM_STS", f"hedgehog/datamover_controller/adc_dm{d}_sts")

                # Connect the error signal to the controller
                connect_bd_net(f, f"hedgehog/adc_dm{d}/s2mm_err", f"hedgehog/datamover_controller/adc_dm{d}_err")

                # Connect the S2MM stream input to the output of the AXIS Data FIFO
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/s_axis_s2mm", f"hedgehog/fifo_adc_dm{d}/m_axis")

                # Connect the DMA S2MM master to the memory smartconnect
                connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/S{d+1:02d}_AXI", f"hedgehog/adc_dm{d}/M_AXI_S2MM")

            # ------------------- Complex MACCs ------------------- #
            
            for d in range(4):

                # ------------------- The CMACC modules -------------------- #
                create_module(f, f"hedgehog/cmacc{d}", "acadia_fast_complex_macc")
                connect_bd_net(f, f"hedgehog/cmacc{d}/clk", f"hedgehog/clk_wiz/seq_clk")

                # Connect the CMACC signal input to the ADC switch through a slice
                create_slice(f, f"hedgehog/xlslice_cmacc{d}", input_width=128*8, input_to=(d+4)*128, input_from=(d+4)*128 + 127)
                connect_bd_net(f, f"hedgehog/axis_switch_adc/m_axis_tdata", f"hedgehog/xlslice_cmacc{d}/Din")
                connect_bd_net(f, f"hedgehog/xlslice_cmacc{d}/Dout", f"hedgehog/cmacc{d}/signal_in")  
                
                # Connect the accumulator reset signal
                connect_bd_net(f, f"hedgehog/cmacc{d}/rst", f"hedgehog/cmacc_reset_dataport/cmacc{d}")
                
                # Connect the kernel memory to the CMACC
                connect_bd_intf_net(f, f"hedgehog/cmacc_kernel_memory/mem{d}", f"hedgehog/cmacc{d}/kernel_mem") 

                for i,q in enumerate(["re", "im"]):
                    # Connect to the offset dataport
                    connect_bd_net(f, f"hedgehog/cmacc{d}/offset_{q}", f"hedgehog/cmacc{d}_{q}_dataport/offset")
                                   
                    # Connect the accumulator data to the dataport through slices
                    create_slice(f, f"hedgehog/xlslice_cmacc{d}_accumulator_{q}", input_width=64, input_to=i*32, input_from=i*32 + 31)
                    connect_bd_net(f, f"hedgehog/cmacc{d}/accumulator_tdata", f"hedgehog/xlslice_cmacc{d}_accumulator_{q}/Din")
                    connect_bd_net(f, f"hedgehog/xlslice_cmacc{d}_accumulator_{q}/Dout", f"hedgehog/cmacc{d}_{q}_dataport/accumulator")

                # Connect the accumulator valid and last and real MSB signals to the dataports
                connect_bd_net(f, f"hedgehog/cmacc_status_dataport/cmacc{d}_valid", f"hedgehog/cmacc{d}/accumulator_tvalid")
                connect_bd_net(f, f"hedgehog/cmacc_status_dataport/cmacc{d}_last", f"hedgehog/cmacc{d}/accumulator_tlast")
                
                create_slice(f, f"hedgehog/xlslice_cmacc{d}_accumulator_re_msb", input_width=64, input_from=31, input_to=31)
                connect_bd_net(f, f"hedgehog/xlslice_cmacc{d}_accumulator_re_msb/Din", f"hedgehog/xlslice_cmacc{d}_accumulator_re/Dout")
                connect_bd_net(f, f"hedgehog/cmacc_status_dataport/cmacc{d}_re_msb", f"hedgehog/xlslice_cmacc{d}_accumulator_re_msb/Dout")

                # ------------------- CMACC Real-time DMAs -------------------- #

                create_module(f, f"hedgehog/cmacc_dma{d}", "acadia_dma")
                connect_bd_net(f, f"hedgehog/cmacc_dma{d}/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/cmacc_dma{d}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the DMA signals to the dataports
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cmacc_dma{d}_fifo_mosi", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_in")
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cmacc_dma{d}_fifo_wr", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_wr")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/trigger")
                connect_bd_net(f, f"hedgehog/dma_running_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/running")
                connect_bd_net(f, f"hedgehog/dma_fifo_empty_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_empty")
                connect_bd_net(f, f"hedgehog/dma_fifo_almost_empty_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_almost_empty")

                # Connect the CMACC DMA to the CMACC DMA port
                connect_bd_intf_net(f, f"hedgehog/cmacc_dma{d}/addr", f"hedgehog/cmacc{d}/kernel_mem_addr")

                # Connect to descriptor memory
                connect_bd_intf_net(f, f"hedgehog/cmacc_dma{d}/descriptor_mem", f"hedgehog/cmacc_dma_descriptor_memory/mem{d}")

                # ------------------- DataMover FIFOs -------------------- #

                create_module(f, f"hedgehog/fifo_cmacc_dm{d}", "acadia_adc_fifo")
                set_property(f, f"hedgehog/fifo_cmacc_dm{d}", properties={"WIDTH": 128, "TKEEP_WIDTH": 16, "DEPTH": StandardFirmware.CMACC_FIFO_DEPTH})

                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the FIFO stream input to the CMACC signal passthrough
                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/din", f"hedgehog/cmacc{d}/signal_out_tdata")
                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/wr_en", f"hedgehog/cmacc{d}/signal_out_tvalid")

                # ------------------- AXI DataMovers -------------------- #

                # Create the DataMover itself
                create_ip(f, name=f"hedgehog/cmacc_dm{d}", vlnv="xilinx.com:ip:axi_datamover:5.1")
                set_property(f, name=f"hedgehog/cmacc_dm{d}", properties="CONFIG.c_m_axi_s2mm_data_width.VALUE_SRC USER CONFIG.c_s_axis_s2mm_tdata_width.VALUE_SRC USER\n")
                set_property(f, name=f"hedgehog/cmacc_dm{d}", 
                                 properties="CONFIG.c_include_mm2s {Omit} "
                                            "CONFIG.c_include_mm2s_stsfifo {false} "
                                            "CONFIG.c_m_axi_s2mm_data_width {128} "
                                            "CONFIG.c_s_axis_s2mm_tdata_width {32} "
                                            "CONFIG.c_s2mm_btt_used {23} "
                                            "CONFIG.c_s2mm_support_indet_btt {true} "
                                            "CONFIG.c_mm2s_include_sf {false} "
                                            "CONFIG.c_s2mm_include_sf {false} "
                                            "CONFIG.c_enable_cache_user {true} "
                                            "CONFIG.c_enable_mm2s {0} "
                                            "CONFIG.c_enable_s2mm_adv_sig {0} "
                                            "CONFIG.c_addr_width {40}")

                # Connect clocks and resets
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/m_axi_s2mm_aclk", "hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/m_axi_s2mm_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/m_axis_s2mm_cmdsts_awclk", "hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/m_axis_s2mm_cmdsts_aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the MM2S command and status interfaces to the bus-driven DataMover controller
                connect_bd_intf_net(f, f"hedgehog/cmacc_dm{d}/S_AXIS_S2MM_CMD", f"hedgehog/datamover_controller/cmacc_dm{d}_cmd")
                connect_bd_intf_net(f, f"hedgehog/cmacc_dm{d}/M_AXIS_S2MM_STS", f"hedgehog/datamover_controller/cmacc_dm{d}_sts")

                # Connect the error signal to the controller
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/s2mm_err", f"hedgehog/datamover_controller/cmacc_dm{d}_err")

                # Connect the S2MM stream input to the output of the AXIS Data FIFO
                connect_bd_intf_net(f, f"hedgehog/cmacc_dm{d}/s_axis_s2mm", f"hedgehog/fifo_cmacc_dm{d}/m_axis")

                # Connect the S2MM AXI master to the memory smartconnect
                connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/S{d+5:02d}_AXI", f"hedgehog/cmacc_dm{d}/M_AXI_S2MM")

            # ------------------- DAC channels -------------------- #

            for channel in range(StandardFirmware.NUM_DAC):
                tile = channel // 4
                block = channel % 4

                # Create a DMA for the DAC and connect it to the read port of the BRAM
                create_module(f, f"hedgehog/dac_dma{channel}", "acadia_dma")
                connect_bd_intf_net(f, f"hedgehog/dac_dma{channel}/mem_control", f"hedgehog/dac_memory/mem{channel}")
                connect_bd_net(f, f"hedgehog/dac_dma{channel}/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/dac_dma{channel}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the DAC memory output to the RFDAC interface
                connect_bd_net(f, f"hedgehog/dac_memory/mem{channel}_dout", f"hedgehog/rfdc/s{tile}{block}_axis_tdata")

                # Connect the DAC DMA to the registers
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/dac_dma{channel}_fifo_mosi", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_in")
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/dac_dma{channel}_fifo_wr", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_wr")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/trigger")
                connect_bd_net(f, f"hedgehog/dma_running_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/running")
                connect_bd_net(f, f"hedgehog/dma_fifo_empty_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_empty")
                connect_bd_net(f, f"hedgehog/dma_fifo_almost_empty_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_almost_empty")
                
                # Connect DAC Descriptor BRAMs and to the DMA                
                connect_bd_intf_net(f, f"hedgehog/dac_dma_descriptor_memory/mem{channel}", f"hedgehog/dac_dma{channel}/DESCRIPTOR_MEM")

            # ------------------- AXI Address Assignment -------------------- #
            
            self.bulk_memory_segments = {
                "HPC0_DDR_LOW": ("ps/SAXIGP0/HPC0_DDR_LOW", StandardFirmware.HPC0_DDR_LOW_ADDRESS, "2G"),
                "HPC1_DDR_LOW": ("ps/SAXIGP1/HPC1_DDR_LOW", StandardFirmware.HPC1_DDR_LOW_ADDRESS, "2G"),
                "HP0_DDR_LOW": ("ps/SAXIGP2/HP0_DDR_LOW", StandardFirmware.HP0_DDR_LOW_ADDRESS, "2G"),
                "HP1_DDR_LOW": ("ps/SAXIGP3/HP1_DDR_LOW", StandardFirmware.HP1_DDR_LOW_ADDRESS, "2G"),
                
                "HPC0_DDR_HIGH": ("ps/SAXIGP0/HPC0_DDR_HIGH", StandardFirmware.HPC0_DDR_HIGH_ADDRESS, "32G"),
                "HPC1_DDR_HIGH": ("ps/SAXIGP1/HPC1_DDR_HIGH", StandardFirmware.HPC1_DDR_HIGH_ADDRESS, "32G"),
                "HP0_DDR_HIGH": ("ps/SAXIGP2/HP0_DDR_HIGH", StandardFirmware.HP0_DDR_HIGH_ADDRESS, "32G"),
                "HP1_DDR_HIGH": ("ps/SAXIGP3/HP1_DDR_HIGH", StandardFirmware.HP1_DDR_HIGH_ADDRESS, "32G"),
                
                "HPC0_LPS_OCM": ("ps/SAXIGP0/HPC0_LPS_OCM", StandardFirmware.HPC0_LPS_OCM_ADDRESS, "256K"),
                "HPC1_LPS_OCM": ("ps/SAXIGP1/HPC1_LPS_OCM", StandardFirmware.HPC1_LPS_OCM_ADDRESS, "256K"),
                "HP0_LPS_OCM": ("ps/SAXIGP2/HP0_LPS_OCM", StandardFirmware.HP0_LPS_OCM_ADDRESS, "256K"),
                "HP1_LPS_OCM": ("ps/SAXIGP3/HP1_LPS_OCM", StandardFirmware.HP1_LPS_OCM_ADDRESS, "256K"),
                
                "DDR4_C0": ("DDR4_C0_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK", StandardFirmware.DDR4_C0_ADDRESS, "4G"),
                "DDR4_C1": ("DDR4_C1_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK", StandardFirmware.DDR4_C1_ADDRESS, "4G")
            }
                 
            self.excluded_segments = ["ps/SAXIGP0/HPC0_QSPI", "ps/SAXIGP1/HPC1_QSPI", "ps/SAXIGP2/HP0_QSPI", "ps/SAXIGP3/HP1_QSPI"]
                        
            self.memory_segments = {
                "adc_axis_switch": ("hedgehog/axis_switch_adc/S_AXI_CTRL/Reg", StandardFirmware.ADC_AXIS_SWITCH_ADDRESS, "256K"),
                "rfdc": ("hedgehog/rfdc/s_axi/Reg", StandardFirmware.RFDC_ADDRESS, "256K"),
                "clk_wiz": ("hedgehog/clk_wiz/s_axi_lite/Reg", StandardFirmware.CLK_WIZ_ADDRESS, "256K"),
                "cache_memory": ("hedgehog/cache_memory/s_axi/reg0", StandardFirmware.CACHE_MEMORY_ADDRESS, StandardFirmware.CACHE_MEMORY_SIZE_BITS // 8),
                "instruction_memory": ("hedgehog/instruction_memory/s_axi/reg0", StandardFirmware.INSTRUCTION_MEMORY_ADDRESS, StandardFirmware.INSTRUCTION_MEMORY_SIZE_BITS // 8)}
            
            self.memory_segments[f"dac_memory"] = (f"hedgehog/dac_memory/s_axi/reg0", 
                                 StandardFirmware.DAC_MEMORY_BASE_ADDRESS, 
                                 StandardFirmware.DAC_MEMORY_SIZE_BITS*StandardFirmware.NUM_DAC//8)
                
            self.memory_segments["cmacc_kernel_memory"] = (f"hedgehog/cmacc_kernel_memory/s_axi/reg0", 
                                     StandardFirmware.CMACC_KERNEL_MEMORY_BASE_ADDRESS, 
                                     StandardFirmware.CMACC_KERNEL_MEMORY_SIZE_BITS*StandardFirmware.NUM_CMACC//8)
            
            self.memory_segments[f"dac_dma_descriptor_memory"] = (f"hedgehog/dac_dma_descriptor_memory/s_axi/reg0", 
                                 StandardFirmware.DAC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS, 
                                 StandardFirmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS*StandardFirmware.NUM_DAC//8)
                
            self.memory_segments["adc_dma_descriptor_memory"] = (f"hedgehog/adc_dma_descriptor_memory/s_axi/reg0", 
                                     StandardFirmware.ADC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS, 
                                     StandardFirmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS*StandardFirmware.NUM_ADC//8)
            
            self.memory_segments[f"cmacc_dma_descriptor_memory"] = (f"hedgehog/cmacc_dma_descriptor_memory/s_axi/reg0", 
                                     StandardFirmware.CMACC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS, 
                                     StandardFirmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS*StandardFirmware.NUM_CMACC//8)
            
            for target_address_space in ["/ps/Data", "hedgehog/cfg_axi_dm/Data_S2MM"]:
                for segment,address,rng in self.memory_segments.values():
                    assign_bd_address(f, target_address_space=target_address_space, offset=address, range=rng, addr_seg=segment)
                    
            bulk_address_spaces = ["/ps/Data", "hedgehog/cfg_axi_dm/Data_MM2S"]
            bulk_address_spaces += [f"/hedgehog/adc_dm{i}/Data_S2MM" for i in range(StandardFirmware.NUM_ADC)]
            bulk_address_spaces += [f"/hedgehog/cmacc_dm{i}/Data_S2MM" for i in range(StandardFirmware.NUM_CMACC)]
            for target_address_space in bulk_address_spaces:
                for segment,address,rng in self.bulk_memory_segments.values():
                    if "SAXIGP" in segment and "/ps" in target_address_space:
                        # Don't map the PS memory into itself
                        exclude_bd_addr_seg(f, addr_seg=segment, target_address_space=target_address_space)
                    else:
                        assign_bd_address(f, target_address_space=target_address_space, offset=address, range=rng, addr_seg=segment)
                for segment in self.excluded_segments:
                    exclude_bd_addr_seg(f, addr_seg=segment, target_address_space=target_address_space)

class DMASynchronizer(Synchronizer):
    """
    Synchronizes DMA triggers.
    """
    def __call__(self, *args, **kwargs):
        self.mask = Symbol(value_type=int)
        self._trigger = kwargs.pop("trigger", True)
        self._block = kwargs.pop("block", self._trigger) # don't block if we don't trigger
        return super().__call__(*args, **kwargs)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        
        mask_tmp = 0
        for call in self._calls:
            function,parent,args,kwargs = call.values()
            
            # The behavior is the same regardless of the kind of DMA we're
            # triggering so we can ignore function
            channel = kwargs["channel"] if "channel" in kwargs else args[0]
            
            # Figure out which bits will contribute to the mask
            if channel.is_dac:
                # If it's a DAC, the bit position is just the channel number
                bit_position = channel.num
            else:
                # If it's an ADC, the DMA object will be a ManagedResource
                # with an offset depending on whether it's for an ADC or CMACC
                dma = channel.dma
                bit_position = type(dma).DMA_NUM_OFFSET + dma._resource_id
                
            mask_tmp |= 1 << bit_position
            
        self.mask.assign(mask_tmp)
                
        if self._trigger:
            # The only parent object that we could have had was an Acadia object,
            # so we know on which object we should call dma_trigger
            parent.dma_trigger(self.mask)
            
        if self._block:
            # Wait until all the DMAs in the mask have completed
            parent.dma_block(self.mask)
            
        super().__exit__(exc_type, exc_val, exc_tb)
            
                
class NCOSynchronizer(Synchronizer):
    """
    Synchronizes updates for NCOs.
    """
        
    def __call__(self, *args, **kwargs):
        self._event_source = kwargs.pop("event", "immediate")
        return super().__call__(*args, **kwargs)
        
    def __exit__(self, exc_type, exc_val, exc_tb):        
        proc = Processor.active_processor()
        if isinstance(proc, Sequencer):
            if self._event_source not in ["immediate", "pl"]:
                raise ValueError(f"Invalid event source for sequencer-driven"
                                 f" NCO synchronization: {self._event_source}")
            # Aggregate all the update settings
            nco_phase_reset = 0
            update_enables = [0]*8
            update_request = 0
            
            for call in self._calls:
                function,channel,args,kwargs = call.values()
                
                # The bit position for the channel in the update request and 
                # phase reset registers
                bit_position = channel.num
                if not channel.is_dac:
                    bit_position += 16
                    
                update_request |= 1 << bit_position
                
                # Which register for setting the update enable pins does this 
                # channel belong to?
                update_enable_reg = 4*channel.tile
                if not channel.is_dac:
                    update_enable_reg += 4
                    
                # Set bits in the enable registers
                if function == "set_nco_frequency":
                    if kwargs["low"]:
                        update_enables[update_enable_reg] |= (1 << 0) << (6*channel.block)
                    if kwargs["mid"]:
                        update_enables[update_enable_reg] |= (1 << 1) << (6*channel.block)
                    if kwargs["high"]:
                        update_enables[update_enable_reg] |= (1 << 2) << (6*channel.block)
                elif function == "set_nco_phase":
                    if kwargs["low"]:
                        update_enables[update_enable_reg] |= (1 << 3) << (6*channel.block)
                    if kwargs["high"]:
                        update_enables[update_enable_reg] |= (1 << 4) << (6*channel.block)
                elif function == "reset_nco_phase":
                    nco_phase_reset |= 1 << bit_position
                    update_enables[update_enable_reg] |= (1 << 5) << (6*channel.block)
                else:
                    raise ValueError(f"Unrecognized function {function}.")
                    
            # Generate register writes for all the updates that need to happen
            rts_address = channel._parent.firmware["rfdc_rts_regs"].address().value()
            for tile in range(8):
                if update_enables[tile] != 0:
                    proc.bus_write(address=rts_address + 0x60 + tile,
                                   data=update_enables[tile])
                    
            if nco_phase_reset != 0:
                proc.bus_write(address=rts_address + 0x68, data=nco_phase_reset)
                
            if nco_update_request != 0:
                # Pulse the update request for one cycle
                proc.bus_write(address=rts_address + 0x69, data=nco_update_request)
                proc.bus_write(address=rts_address + 0x69, data=0)
                
            if self._event_source == "pl":
                # Write the PL event register
                # The bit pattern is the same as for the update request register
                # and the blocks we want to drive events for will be the same
                # Pulse it for one cycle
                proc.bus_write(address=rts_address + 0x6C, data=nco_update_request)
                proc.bus_write(address=rts_address + 0x6C, data=0)
        else:
            for call in self._calls:
                function,channel,args,kwargs = call.values()
                channel.set_nco_update_event_source(self._event_source)
                
                if self._event_source == "immediate":
                    offset = channel.RFDC_def(f"XRFDC_{'DAC' if channel.is_dac else 'ADC'}_UPDATE_DYN_OFFSET")
                    channel.RFDC_voidcall("ClrSetReg", 
                                   channel.register_base_address(), 
                                   offset, 
                                   channel.RFDC_def(f"XRFDC_UPDT_EVNT_MASK"),
                                   channel.RFDC_def(f"XRFDC_UPDT_EVNT_NCO_MASK"))
                    
        super().__exit__(exc_type, exc_val, exc_tb)
                
class VOPDSASynchronizer(Synchronizer):
    """
    Synchronizes DAC VOP and ADC DSA update signals.
    """
    def __exit__(self, exc_type, exc_val, exc_tb):        
        proc = Processor.active_processor()
        if isinstance(proc, Sequencer):
            vop_dsa_update_reg = 0
            
            # The DAC VOP codes each have their own register but the DSA codes
            # are stored together by tile, so we need to aggregate
            tile_dsa_codes = [0]*4
            
            for call in self._calls:
                function,channel,args,kwargs = call.values()
                
                if function == "set_vop":
                    vop_dsa_update_reg |= 1 << channel.num
                elif function == "set_dsa":
                    vop_dsa_update_reg |= 1 << (16 + channel.tile)
                    data = args[0] << (channel.block*5)
                    mask = 0b11111 << (channel.block*5)
                    tile_dsa_codes[channel.tile] = (tile_dsa_codes[channel.tile] & ~mask) | data
                else:
                    raise ValueError(f"Unrecognized function {function}.")
                    
            # Write the ADC DSA registers for the tiles
            rts_address = channel._parent.firmware["rfdc_rts_regs"].address().value()
            for i in range(4):
                if vop_dsa_update_reg & (1 << (16+i)):
                    proc.bus_write(address=rts_address + 0x80, data=tile_dsa_codes[i])

            if vop_dsa_update_reg != 0:
                proc.bus_write(address=rts_address + 0x6D, data=vop_dsa_update_reg)
        else:
            raise TypeError(f"Invalid processor for VOP/DSA synchronization: {proc}")
            
        super().__exit__(exc_type, exc_val, exc_tb)
            
class TDDSynchronizer(Synchronizer):
    """
    Synchronizes TDD signals. Note that in the current version of the firmware,
    this only has an effect on DAC channels.
    """ 
    def __exit__(self, *args, **kwargs):        
        proc = Processor.active_processor()
        if isinstance(proc, Sequencer):
            tdd_mode_set_reg = 0
            tdd_mode_clear_reg = 0
            
            for call in self._calls:
                function,channel,args,kwargs = call.values()
                
                # The bit position for the channel in the update request and 
                # phase reset registers
                bit_position = channel.num
                if not channel.is_dac:
                    bit_position += 16
                                        
                # Set bits in the enable registers
                if function == "set_tdd_mode":
                    if args[0]:
                        tdd_mode_set_reg |= 1 << bit_position
                    else:
                        tdd_mode_clear_reg |= 1 << bit_position
                else:
                    raise ValueError(f"Unrecognized function {function}.")
            
            rts_address = channel._parent.firmware["rfdc_rts_regs"].address().value()
            if tdd_mode_set_reg != 0:
                proc.bus_write(address=rts_address + 0x6B, data=tdd_mode_set_reg)
            if tdd_mode_clear_reg != 0:
                proc.bus_write(address=rts_address + 0x6C, data=tdd_mode_clear_reg)
        else:
            raise TypeError(f"Invalid processor for TDD mode synchronization: {proc}")
        
@dataclass
class Channel:
    num: int = None
    tile: int = None
    block: int = None
    bank: int = None
    is_dac: bool = None
    interface_sample_frequency: float = None
    analog_sample_frequency: float = None
    interface_samples_per_cycle: int = None
    
    nco_synchronizer = NCOSynchronizer()
    vop_dsa_synchronizer = VOPDSASynchronizer()
    tdd_synchronizer = TDDSynchronizer()

    def __post_init__(self):
        if self.num is not None:
            if self.tile is not None or self.block is not None:
                raise ValueError(f"Specify a channel either by channel"
                                 " or by tile and block.")

            if self.num < 0 or self.num > 15:
                raise ValueError(f"Received invalid channel {self.num}.") 

            self.tile = self.num // 4
            self.block = self.num % 4

        if self.bank is not None:
            if self.bank > 231 or self.bank < 224:
                raise ValueError(f"Received invalid bank {self.bank}.")

            self.is_dac = self.bank > 227
            self.tile = (self.bank - 224) % 4

        if self.block is not None:
            if self.tile is not None:
                self.num = self.tile*4 + self.block

        if self.tile > 4 or self.tile < 0:
            raise ValueError(f"Received invalid tile {self.tile}.")

        if self.block > 4 or self.block < 0:
            raise ValueError(f"Received invalid block {self.block}.")
            
    @staticmethod
    def DAC(*args, **kwargs):
        """
        :return: a :class:`Channel` representing a DAC.
        :rtype: :class:`Channel`
        """
        return Channel(*args,
                       is_dac=True, 
                       **kwargs)

    @staticmethod
    def ADC(*args, **kwargs):
        """
        :return: a :class:`Channel` representing an ADC.
        :rtype: :class:`Channel`
        """
        return Channel(*args,
                       is_dac=False, 
                       **kwargs)
    
    def register_base_address(self):
        if self.tile is not None and self.block is not None:
            return xrfdc.lib.def_XRFDC_BLOCK_BASE(self.converter_type(), 
                                                  self.tile, 
                                                  self.block)
        raise ValueError(f"Unable to get register base address for channel {self}.")
    
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

        cls.RFDC_call("RegisterMetal", 0, cls._device_ptr)
        cls.RFDC_call("CfgInitialize", config_ptr)
        
    @classmethod
    def RFDC_call(cls, func_name, *args, **kwargs):
        """
        Call a function in the XRFDC driver. If no Processor is active, it is
        assumed that the code is being run live on hardware and should be 
        executed immediately.
        :param func_name: Name of RFDC function to execute. Omit any "XRFdc_"
        prefix.
        :type func_name: str
        """
        if not hasattr(cls, "_rfdc"):
            raise ValueError("RFDC driver not initialized.")
            
        if getattr(xrfdc.lib, f"XRFdc_{func_name}")(cls._rfdc, *args, **kwargs) != xrfdc.lib.XRFDC_SUCCESS:
            raise ValueError(f"XRFdc_{func_name} failed.")
            
    @classmethod
    def RFDC_voidcall(cls, func_name, *args, **kwargs):
        """
        Call a function in the XRFDC driver. If no Processor is active, it is
        assumed that the code is being run live on hardware and should be 
        executed immediately.
        :param func_name: Name of RFDC function to execute. Omit any "XRFdc_"
        prefix.
        :type func_name: str
        """
        if not hasattr(cls, "_rfdc"):
            raise ValueError("RFDC driver not initialized.")
            
        getattr(xrfdc.lib, f"XRFdc_{func_name}")(cls._rfdc, *args, **kwargs)
            
    @classmethod
    def RFDC_def(cls, name):
        """
        Get a definition from the XRFDC library by name.
        """
        if not hasattr(cls, "_rfdc"):
            raise ValueError("RFDC driver not initialized.")
            
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
    def IP_status(cls):
        """
        Get the status of the RFDC IP. The return value is a CFFI struct with
        members:
        - XRFdc_TileStatus DACTileStatus[4]
        - XRFdc_TileStatus ADCTileStatus[4]
        
        The XRFdc_TileStatus struct contains:
        - u32 IsEnabled
        - u32 TileState
        - u8 BlockStatusMask
        - u32 PowerUpState
        - u32 PLLState
        """
        ip_status = xrfdc.ffi.new("XRFdc_IPStatus*")
        cls.RFDC_call("GetIPStatus", ip_status)
        return ip_status
    
    def status(self):
        """
        Get the status of the converter. The return value is a CFFI struct with
        members:
        - double SamplingFreq
        - u32 AnalogDataPathStatus
        - u32 DigitalDataPathStatus
        - u8 DataPathClocksStatus
        - u8 IsFIFOFlagsEnabled
        - u8 IsFIFOFlagsAsserted
        """
        block_status = xrfdc.ffi.new("XRFdc_BlockStatus*")
        self.RFDC_call("GetBlockStatus", 
                   self.converter_type(), 
                   self.tile, 
                   self.block, 
                   block_status)
        return block_status            
    
    def startup(self):
        self.RFDC_call("StartUp", self.converter_type(), self.tile)
        
    def shutdown(self):
        self.RFDC_call("Shutdown", self.converter_type(), self.tile)
        
    def reset(self):
        self.RFDC_call("Reset", self.converter_type(), self.tile)
        
    @classmethod
    def reset_all(cls):
        cls.RFDC_call("Reset", cls.RFDC_def("XRFDC_DAC_TILE"), -1)
        cls.RFDC_call("Reset", cls.RFDC_def("XRFDC_ADC_TILE"), -1)
    
    @nco_synchronizer.synchronized
    def set_nco_frequency(self, frequency, low=True, mid=True, high=True):
        """
        Configure some or all NCO settings. The three 16-bit registers for
        the frequency tuning word, the two for the phase word, and the single  may be individually enabled, allowing
        for lower latency when less precise changes are acceptable.
        :param frequency: Frequency in GHz
        :type frequency: int
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
        
        frequency_word = self.frequency_to_nco_tuning_word(frequency)
        
        proc = Processor.active_processor()
        if proc is None:
            if low:
                self.RFDC_voidcall("WriteReg16Wrapper", 
                               self.register_base_address(), 
                               self.RFDC_def("XRFDC_ADC_NCO_FQWD_LOW_OFFSET"), 
                               frequency_word & 0xFFFF)
            if mid:
                self.RFDC_voidcall("WriteReg16Wrapper", 
                               self.register_base_address(), 
                               self.RFDC_def("XRFDC_ADC_NCO_FQWD_MID_OFFSET"), 
                               (frequency_word >> 16) & 0xFFFF)
            if high:
                self.RFDC_voidcall("WriteReg16Wrapper", 
                               self.register_base_address(), 
                               self.RFDC_def("XRFDC_ADC_NCO_FQWD_UPP_OFFSET"),
                               (frequency_word >> 32) & 0xFFFF)
                
        elif isinstance(proc, Sequencer):
            if (mid and not high) or (high and not mid):
                raise ValueError("High and middle sections of the NCO"
                                 " frequency word must be set together in the"
                                 " sequencer.")
                
            frequency_base_reg = Acadia.firmware["rfdc_rts_regs"].address().value() + self.num*2
            
            if not self.is_dac:
                frequency_base_reg += 16*2 
            if high:
                proc.bus_write(address=frequency_base_reg, 
                               data=(frequency_word >> 16) & 0xFFFFFFFF)
            if low:
                proc.bus_write(address=frequency_base_reg+1, 
                               data=frequency_word & 0xFFFF)
        
        else:
            raise TypeError("NCO frequency can only be set in"
                            " `PythonProcessor` or `Sequencer` contexts.")
    
    @nco_synchronizer.synchronized
    def set_nco_phase(self, phase, low=True, high=True):
        """
        Set the NCO phase offset to the given word.
        :param phase: Phase tuning word
        :type phase: int
        :param low: If `True`, the lower 16 bits will be set.
        :type low: bool, optional
        :param high: If `True`, the upper 2 bits will be set.
        :type high: bool, optional
        """
        proc = Processor.active_processor()
        if proc is None or isinstance(proc, PythonProcessor):
            if low:
                self.RFDC_voidcall("WriteReg16Wrapper", 
                               self.register_base_address(), 
                               self.RFDC_def("XRFDC_NCO_PHASE_LOW_OFFSET"), 
                               phase & 0xFFFF)

            if high:
                self.RFDC_voidcall("WriteReg16Wrapper", 
                               self.register_base_address(), 
                               self.RFDC_def("XRFDC_NCO_PHASE_UPP_OFFSET"),
                               (phase >> 16) & 0x3)
                
        elif isinstance(proc, Sequencer):
            phase_reg = Acadia.firmware["rfdc_rts_regs"].address().value() + 0x40 + self.num
            
            if not self.is_dac:
                phase_reg += 16
                
            proc.bus_write(address=phase_reg, data=phase & 0x0003FFFF)
            
        else:
            raise TypeError("NCO phase can only be set in"
                            " `PythonProcessor` or `Sequencer` contexts.")

    @nco_synchronizer.synchronized
    def reset_nco_phase(self):
        """
        Reset the value of the NCO phase accumulator.
        """
        proc = Processor.active_processor()
        if proc is None or isinstance(proc, PythonProcessor):
            self.RFDC_call("ResetNCOPhase",
                           self.converter_type(), self.tile, self.block)
                
        elif isinstance(proc, Sequencer):
            # Do nothing, the synchronizer will set the bit in the register
            pass
            
        else:
            raise TypeError("NCO accumulator phase can only be reset in"
                            " `PythonProcessor` or `Sequencer` contexts.")
        
    def set_nco_update_event_source(self, source="immediate"):
        """
        Set the NCO update source.
        :param source: The source of the update event. Must be one of: 
        "immediate", "slice", "tile", "sysref", "marker", "pl"
        :type source: str, optional
        
        """ 
        if source not in ["immediate", "slice", "tile", "sysref", "marker", "pl"]:
            raise ValueError(f"Invalid source {source}.")
        
        self.RFDC_voidcall("ClrSetReg", 
                       self.register_base_address(), 
                       self.RFDC_def("XRFDC_NCO_UPDT_OFFSET"), 
                       self.RFDC_def("XRFDC_NCO_UPDT_MODE_MASK"),
                       self.RFDC_def(f"XRFDC_EVNT_SRC_{source.upper()}"))
    
    def nco_update_event(self):
        """
        Trigger an NCO update event from the RFDC software driver.
        """
        self.RFDC_call("UpdateEvent", 
                       self.converter_type(), self.tile, self.block,
                       self.RFDC_def("XRFDC_EVENT_MIXER"))
        
    @vop_dsa_synchronizer.synchronized
    def set_vop(self, vop):
        """
        Sets the variable output power (VOP) of a DAC channel.
        :param vop: VOP output current setting in uA
        :type vop: int
        """
        if not self.is_dac:
            raise TypeError("VOP can only be set on DAC channels.")
         
        proc = Processor.active_processor()
        if proc is None or isinstance(proc, PythonProcessor):
            self.RFDC_call("SetDACVOP", self.tile, self.block, vop)
                
        elif isinstance(proc, Sequencer):
            vop_reg = Acadia.firmware["rfdc_rts_regs"].address().value() + 0x70 + self.num
            proc.bus_write(address=vop_reg, data=vop)
            
        raise TypeError("DAC VOP can only be set in"
                        " `PythonProcessor` or `Sequencer` contexts.")
    
    @vop_dsa_synchronizer.synchronized
    def set_dsa(self, dsa):
        """
        Sets the digital step attenuator (DSA).
        :param dsa: Attenuation in dB
        :type dsa: float
        """
        if self.is_dac:
            raise TypeError("DSA can only be set on ADC channels.")
            
        proc = Processor.active_processor()
        if proc is None or isinstance(proc, PythonProcessor):
            settings = self.RFDC_struct("XRFdc_DSA_Settings*", [0, dsa])
            self.RFDC_call("SetDSA", self.tile, self.block, settings)
                
        elif isinstance(proc, Sequencer):
            # Do nothing, the synchronizer will manage writing the codes
            # into the registers
            pass
            
        raise TypeError("ADC DSA can only be set in"
                        " `PythonProcessor` or `Sequencer` contexts.")
    
    @tdd_synchronizer.synchronized
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
        
        self.RFDC_call("SetNyquistZone", 
                       self.converter_type(), self.tile, self.block, reg_value)

    def set_decoder_mode(self, mode):
        """
        Sets the DAC decoder mode.
        :param mode: One of "Low Noise" or "High Linearity"
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
        
        self.RFDC_call("SetDecoderMode", self.tile, self.block, reg_value)

    def set_coarse_delay(self, delay):
        """
        Sets the coarse delay of an ADC Or DAC channel.
        :param delay: Channel delay in units of the sample clock period.
        :type delay: int
        """        
        # Create a new settings structure and initialize it with the delay
        # and immediate update (a constant which has a value of 0)
        settings = self.RFDC_struct("XRFdc_Coarse_Delay_Settings*", [delay, 0])
        self.RFDC_call("SetCoarseDelaySettings",
                        self.converter_type(), self.tile, self.block, settings)
        
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
            
        self.RFDC_call("SetInvSincFIR", self.tile, self.block, mode)   

    def set_dither(self, mode):
        """
        Enables or disables ADC dithering.
        :param mode: If `True`, dithering is enabled; otherwise, it is disabled.
        :type mode: bool
        """
        if self.is_dac:
            raise TypeError("Dithering may only be set for ADCs.")
            
        self.RFDC_call("SetDither", self.tile, self.block, bool(mode))
        
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
        if self.block is not None:
            raise ValueError("Clocking can only be configured for tiles; block must be None.")
            
        if source == "internal":
            source_value = self.RFDC_def("XRFDC_INTERNAL_PLL_CLK")
        elif source == "external":
            source_value = self.RFDC_def("XRFDC_EXTERNAL_CLK")
        else:
            raise ValueError(f"Invalid PLL source {source}.")
            
        self.RFDC_call("DynamicPLLConfig",
                        self.converter_type(), self.tile, 
                        source_value, ref_clk_frequency, sample_rate)

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
        
        self.RFDC_call("SetIMRPassMode", self.tile, self.block, reg_value)
        
    def setup_fifo(self, enable):
        """
        Enables or disables the interface FIFO to a DAC or ADC tile.
        :param enable: If `True`, the FIFO is enabled.
        :type enable: bool
        """ 
        self.RFDC_call("SetupFIFO", self.converter_type(), self.tile, enable)
            
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
            
        if self.block is not None:
            raise ValueError("Software only support setting interpolation for"
                             " a full tile, as the interface clock rate will"
                             " be adjusted.")
            
        if factor not in [1,2,3,4,5,6,8,10,12,16,20,24,40]:
            raise ValueError(f"Invalid interpolation factor {factor}.")
            
        self.RFDC_call("SetInterpolationFactor", self.tile, self.block, factor)
                
        # Reconfigure the interface width to 128 bits
        self.RFDC_call("SetFabWrVldWords", self.tile, self.block, 128 // 16)
        
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
            
        if self.block is not None:
            raise ValueError("Software only support setting decimation for"
                             " a full tile, as the interface clock rate will"
                             " be adjusted.")
            
        if factor not in [1,2,3,4,5,6,8,10,12,16,20,24,40]:
            raise ValueError(f"Invalid decimation factor {factor}.")
            
        self.RFDC_call("SetDecimationFactor", self.tile, self.block, factor)
                
        # Reconfigure the interface width to 128 bits
        self.RFDC_call("SetFabRdVldWords", self.tile, self.block, 128 // 16)
        
    def seconds_to_samples(self, duration):
        """
        Convert a length of time into an equivalent number of samples for the 
        given channel.
        :param duration: Pulse duration in seconds
        :type duration: float
        """
        # Make sure that the requested duration is an integer number of samples
        duration_samples = int(round(duration * self.interface_sample_frequency))
        if abs(duration * self.interface_sample_frequency - duration_samples) > 1e-6:
            raise ValueError("Duration must be equivalent to an integer number of"
                             f" samples; found {duration * self.interface_sample_frequency} samples.")

        # Make sure that the number of samples in the pulse results in a valid 
        # number of cycles
        clock_speed = self.interface_sample_frequency / self.interface_samples_per_cycle
        duration_cycles = int(round(duration * clock_speed))
        if abs(duration * clock_speed - duration_cycles) > 1e-6:
            raise ValueError("Array must be an integer number of cycles;"
                             f" found {duration * clock_speed} cycles"
                             f" ({duration_samples} samples).")

        return duration_samples
    
    def frequency_to_nco_tuning_word(self, frequency):
        """
        Converts a frequency in Hz to the nearest integer tuning word for the
        NCO.
        :param frequency: Frequency in Hz
        :type frequency: float
        :return: NCO tuning word corresponding to the provided frequency
        :rtype: int
        """
        
        # If we're using IMR mode, the NCO frequency is half
        nco_sample_frequency = self.analog_sample_frequency if self.analog_sample_frequency < 7e9 else self.analog_sample_frequency / 2
            
        word = frequency / nco_sample_frequency
        
        # Move the desired NCO frequency into the proper Nyquist zone
        while word > 0.5:
            word -= 0.5
        while word < -0.5:
            word += 0.5
            
        return np.int64(round(word * (2**48)))
    
class RFClk:
    """
    A wrapper for the Xilinx XRFClk driver.
    """
    FIRMWARE_SPI_GPIO_ADDRESS = 0x80000000
    
    @staticmethod
    def call(name, *args, **kwargs):
        if getattr(xrfclk.lib, f"XRFClk_{name}")(*args, **kwargs) != xrfclk.lib.XST_SUCCESS:
            raise ValueError(f"Call to {name} failed.")
        
    @classmethod
    def init(cls):
        """
        Initialize the xrfclk driver.
        """
        RFClk.call("Init", Acadia._get_gpio_base(RFClk.FIRMWARE_SPI_GPIO_ADDRESS))
        
    class RFClkChip(ABC):
        """
        Wrapper for operations on a particular chip
        """
        @classmethod
        @abstractmethod
        def chip_id(cls):
            """
            The chip ID, as designated by the XRFClk driver.
            """
            pass
        
        @classmethod
        def reset(cls):
            RFClk.call("ResetChip", cls.chip_id())
            
        @classmethod
        def set_config(cls, config_id=1):
            """
            Set a configuration present in the driver on the chip.
            """
            RFClk.call("SetConfigOnOneChipFromConfigId", cls.chip_id(), config_id)
            
        @classmethod
        def read_reg(cls, address):
            """
            Read a register on the chip.
            """
            value = xrfclk.ffi.new("unsigned int*", address << 8)
            RFClk.call("ReadReg", cls.chip_id(), value)
            return value[0]
        
        @classmethod
        def write_reg(cls, address, data):
            """
            Write a register on the chip.
            """
            RFClk.call("WriteReg", cls.chip_id(), (address << 8) | (data & 0xFF))
        
    class LMK(RFClkChip):
        DCLK_LMX_ADC = 0
        SDCLK_LMX_ADC = 1
        DCLK_LMX_DAC = 4
        SDCLK_LMX_DAC = 5
        DCLK_RFDC_DAC = 6
        DCLK_RFDC_ADC = 12
        SDCLK_RFDC = 3
        DCLK_PL = 8
        SDCLK_PL = 9
        
        @classmethod
        def chip_id(cls):
            return xrfclk.lib.RFCLK_LMK
        
        @classmethod
        def read_reg16(cls, address):
            """
            Read a big-endian 16-bit number.
            """
            regH = cls.read_reg(address)
            regL = cls.read_reg(address+1)
            return (regH << 8) | regL
        
        @classmethod
        def write_reg16(cls, address, data, mask=0xFFFF):
            """
            Write a big-endian 16-bit number.
            """
            cls.write_reg(address, (data >> 8) & (mask >> 8) & 0xFF)
            cls.write_reg(address, data & mask & 0xFF)
        
        @classmethod
        def set_output_divider(cls, output, div):
            """
            Set the value of an output divider on a DCLK output.
            """
            cls.write_reg(0x100 + 4*output, div & 0x1F)
            
        @classmethod
        def get_output_divider(cls, output):
            """
            Set the value of an output divider on a DCLK output.
            """
            reg = cls.read_reg(0x100 + 4*output) & 0x1F
            if reg == 0:
                return 32
            return reg
        
        @classmethod
        def set_input(cls, clkin):
            """
            Set the clock input mux.
            """
            cls.write_reg(0x147, (clkin << 4) | (2 << 2) | (2 << 0))
            
        @classmethod
        def get_input(cls):
            """
            Get the setting of the clock input mux.
            """
            reg = cls.read_reg(0x147) >> 4
            return reg & 0x7
        
        @classmethod
        def set_input_R(cls, clkin, R):
            cls.write_reg16(0x153 + 2*clkin, R, mask=0x3FFF)
        
        @classmethod
        def get_input_R(cls, clkin):
            return cls.read_reg16(0x153 + 2*clkin) & 0x3FFF
        
        @classmethod
        def set_PLL2_R(cls, N):
            cls.write_reg16(0x160, N, mask=0x0FFF)
        
        @classmethod
        def get_PLL2_R(cls):
            return cls.read_reg16(0x160) & 0x0FFF
        
        @classmethod
        def set_PLL1_N(cls, N):
            cls.write_reg16(0x159, N, mask=0x3FFF)
        
        @classmethod
        def get_PLL1_N(cls):
            return cls.read_reg16(0x159) & 0x3FFF
        
        @classmethod
        def set_PLL2_N(cls, N):
            cls.write_reg16(0x167, N)
        
        @classmethod
        def get_PLL2_N(cls):
            return cls.read_reg16(0x167)
        
        @classmethod
        def get_PLL2_P(cls):
            reg = cls.read_reg(0x162)
            reg = (reg >> 5) & 0x7
            
            # This register has a weird encoding, decode it
            if reg == 0:
                return 8
            if reg == 1 or reg == 2:
                return 2
            return reg
        
        
        
    class LMX(RFClkChip):
        pass
        
    class LMX_ADC(LMX):
        @classmethod
        def chip_id(cls):
            return xrfclk.lib.RFCLK_LMX2594_1
        
    class LMX_ADC(LMX):
        @classmethod
        def chip_id(cls):
            return xrfclk.lib.RFCLK_LMX2594_2
    
class PSGPIO:
    """
    An interface to the GPIO pins of the PS exposed to the PL over EMIO.
    """
    PSGPIO3_IN = 0x6C
    PSGPIO3_OUT = 0x4C
    PSGPIO4_IN = PSGPIO3_IN + 1
    PSGPIO4_OUT = PSGPIO3_OUT + 1
    
    @classmethod
    def attach(cls, mem):
        """
        Attach the class to a memory view of the GPIO registers.
        """
        cls._mem = mem.cast("I")
    
    def __init__(self, port):
        # Store relevant register values
        self._port = port
        self._in = (PSGPIO.PSGPIO3_IN >> 2) + port - 3
        self._out = (PSGPIO.PSGPIO3_OUT >> 2) + port - 3
        self._sequencer_address = Acadia.firmware["sequencer_bus_decoder"][f"ps_gpio{port}"].address().value()
    
    def read(self):
        proc = Processor.active_processor()
        if proc is None:
            return self._mem[self._in]
        elif isinstance(proc, PythonProcessor):
            return proc.call("PSGPIO.read", self)
        elif isinstance(proc, Sequencer):
            return proc.bus_read(self._sequencer_address)
        else:
            raise TypeError(f"Unable to access GPIO on processor {proc}.")
        
    def write(self, data):
        proc = Processor.active_processor()
        if proc is None:
            self._mem[self._out] = data
        if isinstance(proc, PythonProcessor):
            return proc(proc.call("PSGPIO.write", self, data))
        if isinstance(proc, Sequencer):
            return proc.bus_write(address=self._sequencer_address, data=data)
        else:
            raise TypeError(f"Unable to access GPIO on processor {proc}.")
    
    @staticmethod
    def sysfs_export(gpio):        
        if f"gpio{gpio}" not in os.listdir("/sys/class/gpio"):
            with open(f"/sys/class/gpio/export", "w") as f:
                f.write(f"{gpio}\n")
    
    @staticmethod
    def sysfs_set_direction(gpio, direction):        
        with open(f"/sys/class/gpio/gpio{gpio}/direction", "w") as f:
            f.write(f"{direction}\n")
        
    @staticmethod
    def sysfs_write(gpio, value):
        with open(f"/sys/class/gpio/gpio{gpio}/value", "w") as f:
            f.write(f"{value}\n")
        
@dataclass
class ZDMA:
    """
    Configures a channel of the PS ZDMA.
    """
    channel: "DMA channel ID" = None
    src: "Address of transaction source or constant for write-only mode" = None
    dst: "Transaction destination" = None
    size: "Transaction size in bytes. If None, source size is used." = None
    wr_only: "Operate the DMA in write-only mode" = False
    fci_enable: "Enable flow control from the PL" = False
    fci_side: "Selects read or write channel for flow control" = "read"
    fci_buffer_usage: "Size of common buffer to use for FCI cache" = 256
    
    # Register offsets
    ERR_CTRL = 0
    CH_ISR = 0x100
    CH_IMR = 0x104
    CH_IEN = 0x108
    CH_IDS = 0x10C
    CH_CTRL0 = 0x110
    CH_CTRL1 = 0x114
    CH_FCI = 0x118
    CH_STATUS = 0x11C
    CH_DATA_ATTR = 0x120
    CH_DSCR_ATTR = 0x124
    CH_SRC_DSCR_WORD0 = 0x128
    CH_DST_DSCR_WORD0 = 0x138
    CH_WR_ONLY_WORD0 = 0x148
    CH_SRC_START_LSB = 0x158
    CH_SRC_START_MSB = 0x15C
    CH_DST_START_LSB = 0x160
    CH_DST_START_MSB = 0x164
    CH_TOTAL_BYTE = 0x188
    CH_RATE_CTRL = 0x18C
    CH_IRQ_SRC_ACCT = 0x190
    CH_IRQ_DST_ACCT = 0x194
    CH_CTRL2 = 0x200
    
    def __post_init__(self):
        self.calculate_registers()
        
    def calculate_registers(self):
        """
        Populate internal fields with configuration values.
        """
        self._regs = {}
        # Settings for ZDMA_CH_CTRL0
        ch_ctrl0_value = 0
        ch_ctrl0_value |= (1 << 7) # bit 7: overfetch
        # bit 6: 0 = simple DMA mode, 1 = scatter-gather
        # bit 5-4: 00 = read and write, 01 = write only, 10 = read only
        ch_ctrl0_value |= (self.wr_only << 4)
        # bit 3: rate control

        self._regs[ZDMA.CH_CTRL0] = ch_ctrl0_value.to_bytes(4, "little")
        
        # Settings for ZDMA_CH_FCI
        ch_fci_value = 0
        # bits 3-2: Number of 128-bit words (or 64-bit for the LPD DMA) from the common buffer to use
        #  00 = use 32+AxLEN
        #  01 = use 64+AxLEN
        #  10 = use 128+AxLEN
        #  11 = use 256
        if buffer_usage == 32:
            pass
        elif buffer_usage == 64:
            ch_fci_value |= 1 << 2
        elif buffer_usage == 128:
            ch_fci_value |= 2 << 2
        elif buffer_usage == 256:
            ch_fci_value |= 3 << 2
        else:
            raise ValueError(f"Invalid buffer usage {buffer_usage}.")
        
        # bit 1: 0 = control the read side, 1 = control the write side
        if side == "read":
            pass
        elif side == "write":
            ch_fci_value |= 1 << 1
        else:
            raise ValueError(f"Invalid FCI side {side}.")
        # bit 0: enable FCI
        ch_fci_value |= enable
        
        self._regs[ZDMA.CH_FCI] = ch_fci_value.to_bytes(4, "little")
        
        # Source and destination
        self._regs[ZDMA.CH_SRC_START_LSB] = src.to_bytes(8, "little")
        self._regs[ZDMA.CH_DST_START_LSB] = dst.to_bytes(8, "little")
        
        # Write the size to the source and destination registers
        self._regs[ZDMA.CH_SRC_DSCR_WORD0+8] = size.to_bytes(4, "little")
        self._regs[ZDMA.CH_DST_DSCR_WORD0+8] = size.to_bytes(4, "little")
        
    def attach(self, mem):
        """
        Attaches the object to a memory map of the DMA registers.
        """ 
        self._mem = mem.cast("B")
        
    def configure_hardware(self):
        """
        Writes the internally-stored configuration to the hardware.
        """
        for reg,value in self._regs.items():
            self._mem[reg:reg+len(value)] = value
    
    def start_transfer(self):
        """
        Starts the configured transfer.
        """
        proc = Processor.active_processor()
        if proc is None:
            self._mem[ZDMA.CH_CTRL2:ZDMA.CH_CTRL2+4] = (1).to_bytes(4, "little")
        if isinstance(proc, PythonProcessor):
            return proc.call("PS_ZDMA.start_transfer", self)
        elif isinstance(proc, Sequencer):
            # Use the flow control interface to start the copy
            return proc.bus_write(address=Acadia.firmware["sequencer_bus_decoder"]["zdma_controller"].address().value(),
                                 data=(1 << self.channel))
        else:
            raise ValueError(f"Unable to start DMA transfer from processor {proc}.")
            
    def byte_count(self, clear=False):
        """
        :return: The total number of bytes transferred since the last clear.
        :rtype: int
        :param clear: Clear the total byte count.
        :type clear: bool, optional
        """
        count = int.from_bytes(self._mem[ZDMA.CH_TOTAL_BYTE:ZDMA.CH_TOTAL_BYTE+4], "little")
        if clear:
            self._mem[ZDMA.CH_TOTAL_BYTE:ZDMA.CH_TOTAL_BYTE+4] = (0).to_bytes(4, "little")
        return count
    
    def status(self):
        """
        Get the status of the DMA. On the PS, this is the value of the STATUS
        bitfield, and on the sequencer this is the value of the credit 
        acknowledgement counter.
        :return: 0 = done without error, 1 = paused without error, 2 = busy 
        transferring, 3 = done with error
        :rtype: int
        """
        proc = Processor.active_processor()
        if proc is None:
            return int.from_bytes(self._mem[ZDMA.CH_STATUS:ZDMA.CH_STATUS+4], "little")
        elif isinstance(proc, PythonProcessor):            
            return proc.call("PS_ZDMA.status", self)
        elif isinstance(proc, Sequencer):
            # Get the internally-stored credit acknowledgement
            return proc.bus_read(Acadia.firmware["sequencer_bus_decoder"]["zdma_controller"].address().value()+self.channel)
        else:
            raise ValueError(f"Unable to query status from processor {proc}.") 
    
    def is_complete(self):
        """
        Read the completion status of the DMA. On the PS, this compares the 
        DMA status value to that associated with successful completion. On the
        sequencer, this returns the transaction acknowledgement counter.
        :return: DMA completion status 
        :rtype: int
        """
        proc = Processor.active_processor()
        if proc is None or isinstance(proc, PythonProcessor):
            status = self.status()
            return (status == 0) or (status == 3)
        elif isinstance(proc, Sequencer):
            # Check the internally-stored transaction acknowledgement
            return proc.bus_read(Acadia.firmware["sequencer_bus_decoder"]["zdma_controller"].address().value()+32+self.channel)
        else:
            raise ValueError(f"Unable to query completion from processor {proc}.")    
            
    def clear_fci_counters(self):
        """
        Clear the counters for managing the FCI in the ZDMA controller.
        """
        proc = Processor.active_processor()
        if isinstance(proc, Sequencer):
            # Clear credit acknowledgement counter
            proc.bus_write(address=Acadia.firmware["sequencer_bus_decoder"]["zdma_controller"].address().value()+1,
                           data=(1 << self.channel))
            
            # Clear transaction valid counter
            proc.bus_write(address=Acadia.firmware["sequencer_bus_decoder"]["zdma_controller"].address().value()+2,
                           data=(1 << self.channel))
        else:
            raise ValueError(f"Unable to clear FCI counters from processor {proc}.")
        
class AXISSwitch:
    """
    Methods for controlling the Xilinx AXIS switch IP over the AXI-Lite
    interface.
    """
    MUX0_REG = 0x40 >> 2
    DISABLE_VALUE = 1 << 31
    
    CONTROL_REG = 0
    COMMIT_VALUE = 1 << 1

    def attach(self, mem):
        """
        Attaches the instance to a view of its registers. The `memoryview`
        """
        self._mem = mem.cast("I")
    
    def connect(self, mi, si, commit=True):
        """
        Connect a master interface to a slave interface.
        :param mi: Master interface number
        :type mi: int
        :param si: Slave interface number
        :type si: int
        :param commit: If `True`, the connection request is committed. 
        Otherwise, only the connection register is updated.
        :type commit: bool, optional
        """ 
        self._mem[AXISSwitch.MUX0_REG + mi] = si
        if commit:
            self._mem[AXISSwitch.CONTROL_REG] = AXISSwitch.COMMIT_VALUE
    
    def disconnect(self, mi=None, commit=True):
        """
        Disconnect a master interface. If not provided, all are disconnected.
        :param mi: Interface number to disconnect.
        :type mi: int or None, optional
        :param commit: If `True`, the connection request is committed. 
        Otherwise, only the connection register is updated.
        :type commit: bool, optional
        """ 
        if mi is not None:
            self._mem[AXISSwitch.MUX0_REG + mi] = AXISSwitch.DISABLE_VALUE
        else:
            for i in range(16):
                self._mem[AXISSwitch.MUX0_REG + i] = AXISSwitch.DISABLE_VALUE
        if commit:
            self._mem[AXISSwitch.CONTROL_REG] = AXISSwitch.COMMIT_VALUE
        
class Acadia:
    """
    A class that implements system-wide commands for the Acadia hardware.
    Because of the heteregenous nature of the system, instructions with 
    ambiguous targets (such as writing to the system cache, which could be
    performed by the sequencer or the PS) must be carried out in processor
    contexts.
    """

    dma_synchronizer = DMASynchronizer()
    def __init__(self):
        self.firmware = StandardFirmware("/tmp")
        
        # A dictionary for storing assembled code, which maps memoryviews to
        # the bytes that should be loaded into them
        self._assembled = {}
        
        # Create a list for keeping track of all Sequencer sequences
        self._sequence = ManagedResource("Sequence", (Sequencer,), {})
        
        # We'll adjust the allocation index so that it actually corresponds to
        # locations in instruction memory
        # We'll reserve location 0 for jumping to the start of the defined 
        # sequence
        self._sequence._allocation_index = 0
                
        # Make DMAs
        self._dac_dmas = [DMA() for i in range(16)]
        
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
        
        self._create_cache()
        self._create_dac_arrays()
        self._create_cmacc_kernel_arrays()
        self._create_pl_ddr_arrays()
        self._create_ps_ddr_arrays()
        self._create_ocm_arrays()
        
        def zdma_postinit(zdma_self):
            zdma_self.channel = zdma_self._resource_id
            super().__post_init__()
        
        self._ZDMA = ManagedResource("ZDMAResource", 
                                         (ZDMA,), 
                                         {"__post_init__": zdma_postinit,
                                          "OPERATORS": []},
                                         allocation_limit=8)
        
        self._ADC_AXIS_switch = AXISSwitch()
        
    def attach(self):
        """
        Maps system memory and connects to hardware drivers.
        """        
        self._mem_file = os.open("/dev/mem", os.O_SYNC | os.O_RDWR)
        self._mem_maps = []
        
        self._attach_resource(self.CacheArray, mem_cast="I")
        
        self._sequencer_instruction_memory = self._attach_memory(
            address=StandardFirmware.INSTRUCTION_MEMORY_ADDRESS,
            size=StandardFirmware.INSTRUCTION_MEMORY_SIZE_BITS // 8)  
        
        self._dac_dma_descriptor_memory = [self._attach_memory(
            address=(StandardFirmware.DAC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS 
                    + i*(StandardFirmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8)),
            size=StandardFirmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8,
            mem_cast='Q') for i in range(16)]
                
        self._adc_dma_descriptor_memory = [self._attach_memory(
            address=(StandardFirmware.ADC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS 
                    + i*(StandardFirmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8)),
            size=StandardFirmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8,
            mem_cast='Q') for i in range(4)]
        
        self._cmacc_dma_descriptor_memory = [self._attach_memory(
            address=(StandardFirmware.CMACC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS 
                    + i*(StandardFirmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8)),
            size=StandardFirmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8,
            mem_cast='Q') for i in range(4)]
            
        for dac_mem in self.DACArray:
            self._attach_resource(dac_mem)
            
        for cmacc_kernel_mem in self.CMACCKernelArray:
            self._attach_resource(cmacc_kernel_mem)
                
        self._attach_resource(self.PLDDR0Array)
        self._attach_resource(self.PLDDR1Array)
        self._attach_resource(self.PSDDRArray)
            
        # Connect to the RFDC driver and initialize
        Channel.RFDC_init()
        
        # Connect to the ADC AXIS switch
        self._ADC_AXIS_switch.attach(self._attach_memory(
            address=StandardFirmware.ADC_AXIS_SWITCH_ADDRESS, 
            size=0x1000))
        
        # Connect to the PS GDMA
        for instance in self._ZDMA.instances:
            instance.attach(self._attach_memory(
                address=0xFD50_0000 + (instance._resource_id*0x1_0000),
                size=0x1_0000))
            
        # Connect to the GPIO registers
        PSGPIO.attach(self._attach_memory(0xFF0A0000, 0x400))
        
        # Connect to the clock wizard
        self.clk_wiz = self._attach_memory(address=StandardFirmware.CLK_WIZ_ADDRESS, size=2**18)  
            
        # Configure and connect to the sysfs interface for various GPIO        
        self._sequencer_gpio = 334 + 3*26 + StandardFirmware.GPIO_SEQUENCER_RUN
        PSGPIO.sysfs_export(self._sequencer_gpio)
        PSGPIO.sysfs_set_direction(self._sequencer_gpio, "out")
        PSGPIO.sysfs_write(self._sequencer_gpio, 0)
            
        self._ddr_gpio_base = Acadia._get_gpio_base(0x8002_0000)
        PSGPIO.sysfs_export(self._ddr_gpio_base)
        PSGPIO.sysfs_set_direction(self._ddr_gpio_base, "out")
        PSGPIO.sysfs_write(self._ddr_gpio_base, 0)
        
    def detach(self):
        """
        Unmaps all system memory.
        """
        for m in self._mem_maps:
            m.close()
            
            
    # ---------------- COMPILATION FUNCTIONS ---------------------- #
    
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
        s = self._sequence()
        
        # Store this particular Sequencer instance as an instance member of the 
        # Acadia object so that helper functions of the Acadia object know to 
        # use it
        self.active_sequencer = s
        
        # Call the function to populate the sequencer object and compile it
        with s:
            func(self)
        
        # Because the sequence resource object was created before we knew its 
        # size and because we know that the size won't change from this point,
        # we can update the size of the instance and the allocation index of
        # the sequence resource
        s.size = s.Instruction.usage()
        
        # -1 because the index was incremented by 1 when the resource was 
        # instantiated
        self._sequence._allocation_index += s.size-1 
        
        return s
            
    def compile_all(self):
        """
        Compiles the programs for all internally-stored :class:`Processor` 
        objects.
        """
        for s in self._sequence.instances:
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
        :param load: If `True`, will only assemble and not load memory.
        :type load: bool
        :param sequencer: If `False`, the sequencer instructions will not be
        assembled or loaded.
        :type sequencer: bool
        :param dac_dmas: If `False`, the DAC DMA descriptor memory will not be
        assembled or loaded.
        :type dac_dmas: bool
        :param adc_dmas: If `False`, the ADC DMA descriptor memory will not be
        assembled or loaded.
        :type adc_dmas: bool
        :param cmacc_dmas: If `False`, the CMACC DMA descriptor memory will not
        be assembled or loaded.
        :type cmacc_dmas: bool
        """
        
        if sequencer:
            for s in self._sequence.instances:
                for idx_instr,instr in enumerate(s._compiled_program):
                    assembled = instr.assemble()
                    if load:
                        address = (s._resource_id + idx_instr)*16
                        self._sequencer_instruction_memory[address : address+16] = assembled.to_bytes(16, "little")
        
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
            for s in self._sequence.instances:
                for idx_instr,instr in enumerate(s._compiled_program):
                    assembled = instr.assemble()
                    address = (s._resource_id + idx_instr)*16
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{address + StandardFirmware.INSTRUCTION_MEMORY_ADDRESS : X}, 16, 128'h{assembled:032X}, resp);\n"
        
        if dac_dmas:
            for i,dma in enumerate(self._dac_dmas):
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{StandardFirmware.DAC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS + i*(StandardFirmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS//8): X}, 8, 64'h{assembled:016X}, resp);\n"
                
        if adc_dmas:
            for dma in self._ADCDMA.instances:
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{StandardFirmware.ADC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS + dma._resource_id*(StandardFirmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
        
        if cmacc_dmas:
            for i,dma in self._CMACCDMA.instances:
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{StandardFirmware.CMACC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS + dma._resource_id*(StandardFirmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
                    
        return sim_string
                        
    # -------------- HIGH-LEVEL JOINT PS-PL ROUTINES ----------- #
    
    def channel(self, *args, **kwargs):
        """
        Get a channel from this Acadia system. All arguments are passed 
        directly to the constructor for :class:`Channel`.
        """
        c = Channel(*args, **kwargs)
        c._parent = self
        return c
        
    def DAC(self, *args, **kwargs):
        """
        :return: a :class:`Channel` representing a DAC.
        :rtype: :class:`Channel`
        """
        c = self.channel(*args, is_dac=True, **kwargs)
        c.interface_sample_frequency = 1.2e9
        c.analog_sample_frequency = 4.8e9 if c.tile == 0 or c.tile == 1 else 9.6e9
        c.interface_samples_per_cycle = 4
        return c

    def ADC(self, *args, **kwargs):
        """
        :return: a :class:`Channel` representing an ADC.
        :rtype: :class:`Channel`
        """
        c = self.channel(*args, is_dac=False, **kwargs)
        c.interface_sample_frequency = 1.2e9
        c.analog_sample_frequency = 1.2e9 if c.tile == 0 else 2.4e9
        c.interface_samples_per_cycle = 4
        return c
            
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
        :param block: If `True`, the active processor will be instructed to halt
        until the memory copy is completed. Otherwise, the function will return
        immediately after initiating the transfer.
        :param ps_fci: If `True`, the transfer is assumed to be carried out by
        the PS using the DMA controlled by its flow control interface (FCI)
        exposed to the PL. The sequencer is then responsible for initiating and
        executing the transaction. When `True`, the active processor is ignored.
        :return: If `ps_fci` is `True` or if the active processor is a 
        :class:`PythonProcessor`, then the :class:`ZDMA` object representing 
        the DMA configuration is returned. If the active processor is a 
        :class:`Sequencer`, the value used for the DataMover TAG field is 
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
                dst.memory.cast("B")[:size] = src.view(np.uint8) if isinstance(src, np.ndarray) else src
            else:
                raise TypeError(f"Unable to copy literal into memory on"
                                f" processor {proc}.")
        elif hasattr(src, "byte_address") and hasattr(dst, "byte_address"):    
            if proc is None or isinstance(proc, PythonProcessor):
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
                    with proc.wait_until(proc.bus_read(self.firmware["sequencer_bus_decoder"]["datamover_controller"]["cfg_dm_s2mm"]+1) != 0):
                        pass
                return transfer_tag
            else:
                raise TypeError(f"Unable to copy memory using processor {proc}.")
        else:
            raise TypeError("Memory source and/or destination lack sufficient"
                            " information to execute copy.")
    
    @dma_synchronizer.synchronized
    def capture(self, channel, array, decimate=0, integration_kernel=None, datamover_tag=0xB):
        """
        Capture a signal from an ADC into an array. 
        :param channel: Physical channel to capture from.
        :type channel: :class:`Channel` or int
        :param array: The array with which to populate the captured data.
        :type array: :class:`PSDDRArray`, :class:`PLDDR0Array`, 
        :class:`PSDDR1Array`, :class:`self.OCMArray`
        :param decimate: Factor by which to decimate the stream of samples
        :type decimate: bool, optional
        :param integration_kernel: If provided, the captured trace will be
        integrated against the kernel given by the array using a CMACC.
        Otherwise, the signal will be captured with a regular ADC DMA.
        """            
        if not isinstance(channel, Channel):
            raise TypeError(f"Channel must be of type `Channel`;"
                            f" received {channel}.")
            
        if channel.is_dac:
            raise TypeError(f"Channel must be an ADC;"
                            f" received {channel}.")
            
        if not (isinstance(array, self.PSDDRArray)
                or isinstance(array, self.PLDDR0Array)
                or isinstance(array, self.PLDDR1Array)
                or isinstance(array, self.OCMArray)):
            raise TypeError(f"Unable to stream captured signal data into"
                            f" array {array}.")
            
        if (integration_kernel is not None 
                and not isinstance(integration_kernel, self._CMACCKernelArray)):
            raise TypeError(f"If provided, kernel must be a `CMACCKernelArray`;"
                            f" received {integration_kernel}.")
            
        # ADC captures are always 128 bits per clock cycle
        if array.byte_length() // 16 != array.byte_length() / 16:
            raise ValueError(f"An array for ADC capture must have a size that"
                             f" is a multiple of 16 bytes; found"
                             f" {array.byte_length()} bytes.")
            
        trace_length = array.byte_length() // 16
        
        if (integration_kernel is not None 
                and (integration_kernel.byte_length() // 16) != trace_length):
            raise ValueError(f"Integration kernel length"
                             f" ({integration_kernel.byte_length() // 16})"
                             f" does not match trace length ({trace_length}).")
        
        # See if any DMAs are using the same physical channel as the one we
        # want to use, and if so, use that DMA. If not, request a new one
        # from the resource
        dma = None
        if integration_kernel is not None:
            for d in self._CMACCDMA.instances:
                if d.physical_channel == channel and not d._released:
                    dma = d
                    break
            if dma is None:
                dma = self._CMACCDMA(physical_channel=channel)
            fifo_name = f"cmacc_dma{dma._resource_id}_fifo"
            datamover_name = f"cmacc_dm{dma._resource_id}"
            trace_address = integration_kernel.word_address()
        else:
            for d in self._ADCDMA.instances:
                if d.physical_channel == channel and not d._released:
                    dma = d
                    break
            if dma is None:
                dma = self._ADCDMA(physical_channel=channel)
            fifo_name = f"adc_dma{dma._resource_id}_fifo"
            datamover_name = f"adc_dm{dma._resource_id}"
            trace_address = 0
            
        # Store a reference to the DMA chosen in the Channel object
        channel.dma = dma
        
        # Add the descriptor address to the FIFO for the DMA
        descriptor = dma.request_descriptor(trace_address, trace_length, decimate)
        self.active_sequencer.bus_write(address=self.firmware["sequencer_bus_decoder"][fifo_name].address().value(),
                                         data=descriptor)
        
        # Configure the DataMover
        self._sequencer_command_dm(datamover_name, 
                                   array.byte_address(), 
                                   array.byte_length(), 
                                   tag=datamover_tag)
    
    @dma_synchronizer.synchronized
    def generate(self, channel, array):
        """
        Generate a pulse on a DAC channel.
        :param channel: Physical channel to capture from.
        :type channel: :class:`Channel` or int
        :param array: The array of samples to stream into the DAC
        :type array: :class:`DACArray`
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
            
        descriptor = dma.request_descriptor(array.word_address(), 
                                            array.word_length())
        
        fifo_device = self.firmware["sequencer_bus_decoder"][f"dac_dma{channel.num}_fifo"]
        return self.active_sequencer.bus_write(address=fifo_device.address().value(),
                                         data=descriptor)
    
    def configure_adc_switch(self):
        """
        Run the encapsulated program on Acadia hardware. 
        """
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
        
        :param sequence: The Sequence resource to run.
        :type sequence: Sequence
        """
        if sequence is not None:
            jump_instruction = STP(src1=sequence._resource_id, 
                                    dest1=Destination.PC).assemble()
            self._sequencer_instruction_memory[0:16] = jump_instruction.to_bytes(16, "little")
            
        with open(f"/sys/class/gpio/gpio{self._sequencer_gpio}/value", "w") as f:
            f.write(f"1\n")

    def sequencer_halt(self):
        """
        Halts the sequencer by driving its run pin low.
        """
        with open(f"/sys/class/gpio/gpio{self._sequencer_gpio}/value", "w") as f:
            f.write(f"0\n")
            
    def reset_plddr0(self):
        PSGPIO.sysfs_write(self._ddr_gpio_base, 1)
        time.sleep(0.2)
        PSGPIO.sysfs_write(self._ddr_gpio_base, 0)
        time.sleep(0.2)
        
    def reset_logic(self):
        """
        Resets the PL logic.
        """
        gpio = 334 + 3*26 + 95
        PSGPIO.sysfs_export(gpio)
        PSGPIO.sysfs_set_direction(gpio, "out")
        PSGPIO.sysfs_write(gpio, 0)
        time.sleep(0.01)
        PSGPIO.sysfs_write(gpio, 1)
        time.sleep(0.01)
        
    def dma_trigger(self, mask):
        """
        Triggers the DMAs according to a provided bitmask.
        """
        dma_trigger_device = self.firmware["sequencer_bus_decoder"]["dma_trigger"]
        self.active_sequencer.bus_write(address=dma_trigger_device.address().value(),
                                 data=mask)
        
    def dma_block(self, mask):
        """
        Wait until the DMAs specified in the mask are not running.
        """
        dma_running_device = self.firmware["sequencer_bus_decoder"]["dma_running"]
        dma_running = self.active_sequencer.bus_read(dma_running_device.address().value())
        with self.active_sequencer.wait_until(dma_running & mask == 0):
            pass
    
    ########################### UTILITY METHODS ##############################
    @classmethod
    def seconds_to_samples(cls, duration, clock_speed=300e6, samples_per_cycle=4):
        """
        Create an array of zeros with the correct size and type given the length of
        time that the array should represent.
        :param duration: Pulse duration in seconds
        :type duration: float
        :param clock_speed: Clock rate at which samples are read from memory in Hz
        :type clock_speed: float
        :param samples_per_cycle: Number of samples read from memory in one cycle
        :type samples_per_cycle: int
        """
        # Make sure that the requested duration is an integer number of samples
        sample_rate = clock_speed * samples_per_cycle
        duration_samples = int(round(duration * sample_rate))
        if abs(duration * sample_rate - duration_samples) > 1e-6:
            raise ValueError("Duration must be equivalent to an integer number of"
                             f" samples; found {duration * sample_rate} samples.")

        # Make sure that the number of samples in the pulse results in a valid 
        # number of cycles
        duration_cycles = int(round(duration * clock_speed))
        if abs(duration * clock_speed - duration_cycles) > 1e-6:
            raise ValueError("Array must be an integer number of cycles;"
                             f" found {duration * clock_speed} cycles"
                             f" ({duration_samples} samples).")

        return duration_samples

    @classmethod
    def to_samples(cls, array):
        """
        Convert arrays of complex numbers ranging from -1 to 1 into samples for
        the RFSoC DACs and ADCs. Note that no length checking is performed, so 
        if the array is expected to be loaded into memory, it is recommended to 
        use :meth:`seconds_to_samples` to create the input array in order to 
        ensure predictable behavior.
        :param array: Input array of numbers to be converted into samples
        :type array: numpy.ndarray
        """

        # Check shape properties
        if array.ndim != 1:
            raise ValueError("Arrays must be 1D.")

        if (array.dtype == np.float32
                or array.dtype == np.float64
                or array.dtype == np.complex128):
            array = array.astype(np.complex64)
        elif array.dtype != np.complex64:
            raise TypeError(f"Numpy array dtype must be `np.complex64`"
                            f" or be able to be casted to `np.complex64`;"
                            f" received {array.dtype}.")

        array *= 2**13 - 1
        array = array.round().view(np.float32).astype(np.int16)
        array <<= 2
        
        return array.view(dtype=np.uint8)
    
    ########################### HELPER METHODS #############################
        
    _DMESG_GPIO_PATTERN = "gpio@(?P<axi_address>[0-9]+)[:,\ a-z]+(?P<gpio_num>[0-9]+)"
    
    @staticmethod
    def _get_gpio_base(axi_address):
        """
        Get the base sysfs GPIO number for a GPIO controller on the AXI network.
        """
        with open("/var/log/dmesg") as f:
            dmesg = f.read()
                
        gpio_matches = re.finditer(Acadia._DMESG_GPIO_PATTERN, dmesg)
        if not gpio_matches:
            raise ValueError("No GPIO found in dmesg output.")
            
        for match in gpio_matches:
            if int(match["axi_address"], 16) == axi_address:
                return int(match["gpio_num"])
                    
        raise ValueError("Unable to extract GPIO base.")
        
    def _create_cache(self):
        def _cache_getitem(cache_self, key):
            proc = Processor.active_processor()
            if proc is None:
                return cache_self.memory[key]
            elif isinstance(proc, PythonProcessor):
                return proc.call("memoryview.__getitem__", cache_self, key)
            elif isinstance(proc, Sequencer):
                return proc.bus_read(self.firmware["sequencer_bus_decoder"]["cache"].address().value() + key)
            raise TypeError(f"Unable to access cache on processor {proc}.")
            
        def _cache_setitem(cache_self, key, value):
            proc = Processor.active_processor()
            if proc is None:
                cache_self.memory[key] = value
            elif isinstance(proc, PythonProcessor):
                proc.call("memoryview.__setitem__", cache_self, key, value)
            elif isinstance(proc, Sequencer):
                proc.bus_write(address=self.firmware["sequencer_bus_decoder"]["cache"].address().value() + key,
                               data=value)
            raise TypeError(f"Unable to access cache on processor {proc}.")
        
        self.CacheArray = ManagedMemory("CacheArray", 
            (), 
            {"OPERATORS": [], 
             "__getitem__": _cache_getitem, 
             "__setitem__": _cache_setitem},
            base_word_address=self.firmware["sequencer_bus_decoder"]["cache"].address().value(),
            base_byte_address=StandardFirmware.CACHE_MEMORY_ADDRESS,
            word_width=32,
            pool_size=StandardFirmware.CACHE_MEMORY_SIZE_BITS // 32)
        
    def _create_dac_arrays(self):
        self.DACArray = [ManagedMemory(f"DAC{i}Array", (), {},
            base_word_address=0,
            base_byte_address=(StandardFirmware.DAC_MEMORY_BASE_ADDRESS 
                               + i*(StandardFirmware.DAC_MEMORY_SIZE_BITS // 8)),
            word_width=128,
            pool_size=StandardFirmware.DAC_MEMORY_SIZE_BITS // 128) for i in range(16)]
        
    def _create_cmacc_kernel_arrays(self):
        self.CMACCKernelArray = [ManagedMemory(f"CMACCKernel{i}Array", (), {},
            base_word_address=0,
            base_byte_address=(StandardFirmware.CMACC_KERNEL_MEMORY_BASE_ADDRESS 
                               + i*(StandardFirmware.CMACC_KERNEL_MEMORY_SIZE_BITS // 8)),
            word_width=128,
            pool_size=StandardFirmware.CMACC_KERNEL_MEMORY_SIZE_BITS // 128) for i in range(4)]
        
    def _create_pl_ddr_arrays(self):
        self.PLDDR0Array = ManagedMemory(f"PLDDR0Array", (), {},
            base_word_address=StandardFirmware.DDR4_C0_ADDRESS,
            base_byte_address=StandardFirmware.DDR4_C0_ADDRESS,
            word_width=8,
            pool_size=2**32)
        
        self.PLDDR1Array = ManagedMemory(f"PLDDR1Array", (), {},
            base_word_address=StandardFirmware.DDR4_C1_ADDRESS,
            base_byte_address=StandardFirmware.DDR4_C1_ADDRESS,
            word_width=8,
            pool_size=2**32)
        
    def _create_ps_ddr_arrays(self):
        # PS DDR
        self.PSDDRArray = ManagedMemory(f"PSDDRArray", (), {},
            base_word_address=0x8_0000_0000,
            base_byte_address=0x8_0000_0000,
            word_width=8,
            pool_size=2**30)
        
    def _create_ocm_arrays(self):
        self.OCMArray = ManagedMemory(f"OCMArray", (), {},
            base_word_address=0xFFFC_0000,
            base_byte_address=0xFFFC_0000,
            word_width=8,
            pool_size=2**18)
        
    def _attach_resource(self, resource_manager, mem_cast='B'):
        """
        Maps the memory associated with a managed resource in the physical 
        address space of the hardware. Instances of `memoryview` are assigned
        to the resource instances under the attribute `memory`.
        
        :param resource_manager: Resource with instances to be mapped
        :type resource_manager: :class:`ManagedResource`
        :param mem_cast: The memory type to which the view should be casted,
        as indicated by a `struct` format character.
        :type mem_cast: str, optional
        """
        m = mmap.mmap(self._mem_file, 
            resource_manager.pool_size * resource_manager.word_width // 8, 
            mmap.MAP_SHARED, 
            mmap.PROT_READ | mmap.PROT_WRITE, 
            0, 
            resource_manager.base_byte_address)
        
        self._mem_maps.append(m)
        resource_manager._pool_memory = m
        
        for instance in resource_manager.instances:
            start_byte = instance.byte_address() - resource_manager.base_byte_address
            end_byte = start_byte + instance.byte_length()
            instance.memory = memoryview(m)[start_byte:end_byte].cast(mem_cast)
        
    def _attach_memory(self, address, size, mem_cast='B'):
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
        
        return memoryview(m).cast(mem_cast)

    def _sequencer_command_dm(self, datamover_name, address, size, tag=0xA, incr=True):
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
        :param incr: If `True`, the AXI transaction is in INCR mode.
        :type incr: bool, optional
        """
        if size > 2**23:
            raise ValueError(f"Size must be less than 8 MB; received {size}.")
                
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

        addr_reg = address & 0xFFFFFFFF
        misc_reg |= (address >> 32) << 14

        # Configure the DataMover controller (the last bus write will 
        # push the complete command into the command FIFO)
        # Configure the S2MM side first so that it is prepared when the
        # MM2S side starts streaming after the command gets pushed in
        self.active_sequencer.bus_write(address=self.firmware["sequencer_bus_decoder"]["datamover_controller"][datamover_name]+2, 
                            data=misc_reg)
        self.active_sequencer.bus_write(address=self.firmware["sequencer_bus_decoder"]["datamover_controller"][datamover_name]+1, 
                            data=size)
        self.active_sequencer.bus_write(address=self.firmware["sequencer_bus_decoder"]["datamover_controller"][datamover_name]+0, 
                            data=addr_reg)
        
    