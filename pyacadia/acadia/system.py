__all__ = ["Firmware", "Acadia", "Channel", "PSGPIO"]

import os
import mmap
import time
from functools import wraps

import numpy as np

from .hdl import BusDevice, BusDecoder, BusDataport, BusDataMoverController, AXIMemoryArray, connect_bd_net, connect_bd_intf_net, create_ip, create_module, create_concatenator, create_slice, set_property, assign_bd_address, exclude_bd_addr_seg
from .compiler import ManagedResource, ManagedMemory, Processor, Synchronizer, Symbol, Operation
from .sequencer import Sequencer, STP, Destination
from .dma import DMA
from .channel import Channel
from .peripherals import RFClk, PSGPIO, ZDMA, AXISSwitch, get_gpio_base
from .utils import next_highest_power_of_2

class Firmware:
    """
    The standard Acadia firmware. Handcrafted, artisanal FPGA logic with notes
    of silicon and garnished with hedgehog quills.
    """
    
    # These variables are essentially fixed by the design 
    # and are used more for reference than reconfigurability
    NUM_DAC = 16
    NUM_ADC = 4
    NUM_CMACC = 4
    NUM_PS_GPIO = 80
    NUM_PS_IRQ = 2
    NUM_PS_GDMA = 8
    
    # Set addresses for many system slaves
    HPC0_LPS_OCM_ADDRESS = 0x00_FF00_0000
    HPC1_LPS_OCM_ADDRESS = 0x01_FF00_0000
    HP0_LPS_OCM_ADDRESS = 0x02_FF00_0000
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

    RFDC_ADDRESS = 0x00_8000_0000
    CLK_WIZ_ADDRESS = 0x00_8100_0000
    ADC_AXIS_SWITCH_ADDRESS = 0x00_8200_0000

    DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS = 1024*64
    DAC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS = 0x00_8300_0000
    
    ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS = 1024*64
    ADC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS = 0x00_8400_0000
    
    CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS = 1024*64
    CMACC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS = 0x00_8500_0000

    CMACC_KERNEL_MEMORY_SIZE_BITS = 2048*32
    CMACC_KERNEL_MEMORY_BASE_ADDRESS = 0x00_8600_0000
    
    DAC_MEMORY_SIZE_BITS = 128*8192
    DAC_MEMORY_BASE_ADDRESS = 0x00_8800_0000

    CACHE_MEMORY_SIZE_BITS = 2**20
    CACHE_MEMORY_ADDRESS = 0x00_B000_0000

    INSTRUCTION_MEMORY_SIZE_BITS = 128*4096
    INSTRUCTION_MEMORY_ADDRESS = 0x00_B100_0000

    # depth for the FIFOs at the output of ths AXIS stream switch
    ADC_FIFO_DEPTH = 1024
    ADC_FIFO_PRIMITIVE = "auto"
    CMACC_FIFO_DEPTH = 1024
    CMACC_FIFO_PRIMITIVE = "auto"
    
    # The width of the AXI interface at the output of the DataMovers
    ADC_DM_AXI_WIDTHS = [256]*NUM_ADC
    CMACC_DM_AXI_WIDTHS = [32]*NUM_CMACC
    ADC_DM_AXIS_WIDTHS = [256]*NUM_ADC
    CMACC_DM_AXIS_WIDTHS = [32]*NUM_CMACC
    
    DAC_PIPELINE_STAGES = [1]*NUM_DAC # Pipeline stages between the RFDC and DAC memory
    ADC_PIPELINE_STAGES_BEFORE_SWITCH = [0]*16 # Pipeline stages between RFDC and AXIS switch
    ADC_PIPELINE_STAGES_AFTER_SWITCH = [0]*NUM_ADC # Pipeline stages between switch and FIFO
    CMACC_PIPELINE_STAGES_AFTER_SWITCH = [0]*NUM_CMACC # Pipeline stages between switch and CMACC
    
    GPIO_SEQUENCER_RUN = 90 # The GPIO bit connected to the sequencer run synchronizer
    GPIO_SEQUENCER_NRST = 89 # The GPIO bit connected to the sequencer run synchronizer
    GPIO_CLK104_SYNC = 88
    GPIO_CLK104_SPI1 = 87
    GPIO_CLK104_SPI0 = 86
    GPIO_DDR4_C0_SYS_RST = 85
    GPIO_DDR4_C1_SYS_RST = 84
    GPIO_DDR4_C0_CAL_CPLT = 81
    GPIO_DDR4_C1_CAL_CPLT = 80
        
    CLK_CONFIG_4CLKS_300MHz = ("CONFIG.PRIMITIVE {MMCM} "
                            "CONFIG.USE_DYN_RECONFIG {true} "
                            "CONFIG.USE_PHASE_ALIGNMENT {true} "
                            "CONFIG.PRIM_SOURCE {Global_buffer} "
                            "CONFIG.PRIM_IN_FREQ {300.0} "
                            "CONFIG.FEEDBACK_SOURCE {FDBK_AUTO} "
                            "CONFIG.MMCM_DIVCLK_DIVIDE {1} "
                            "CONFIG.MMCM_BANDWIDTH {OPTIMIZED} "
                            "CONFIG.MMCM_CLKFBOUT_MULT_F {5.000} "
                            "CONFIG.MMCM_CLKIN1_PERIOD {3.333} "
                            "CONFIG.MMCM_COMPENSATION {AUTO} "
                            "CONFIG.PLL_CLKIN_PERIOD {3.333} "
                            "CONFIG.CLKIN1_JITTER_PS {33.330000000000005} "
                            "CONFIG.USE_INCLK_SWITCHOVER {false} "
                            "CONFIG.SECONDARY_IN_FREQ {300.0} "
                            "CONFIG.SECONDARY_SOURCE {Global_buffer} "
                            "CONFIG.CLKIN2_JITTER_PS {33.330000000000005} "
                            "CONFIG.MMCM_CLKIN2_PERIOD {3.333} "

                            "CONFIG.NUM_OUT_CLKS {4} "

                            "CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {300.0} "
                            "CONFIG.CLK_OUT1_PORT {seq_clk} "
                            "CONFIG.CLKOUT1_JITTER {76.789} "
                            "CONFIG.CLKOUT1_PHASE_ERROR {71.599} "
                            "CONFIG.MMCM_CLKOUT0_DIVIDE_F {5.000} "
                            "CONFIG.CLKOUT1_DRIVES {Buffer} "

                            "CONFIG.CLKOUT2_USED {true} "
                            "CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {300.0} "
                            "CONFIG.CLK_OUT2_PORT {adc_tile3_clk} "
                            "CONFIG.CLKOUT2_JITTER {76.789} "
                            "CONFIG.CLKOUT2_PHASE_ERROR {71.599} "
                            "CONFIG.MMCM_CLKOUT1_DIVIDE {5} "
                            "CONFIG.CLKOUT2_DRIVES {Buffer} "

                            "CONFIG.CLKOUT3_USED {true} "
                            "CONFIG.CLKOUT3_REQUESTED_OUT_FREQ {250.0} "
                            "CONFIG.CLK_OUT3_PORT {datamover_axi_clk} "
                            "CONFIG.CLKOUT3_JITTER {79.566} "
                            "CONFIG.CLKOUT3_PHASE_ERROR {71.599} "
                            "CONFIG.MMCM_CLKOUT2_DIVIDE {6} "
                            "CONFIG.CLKOUT3_DRIVES {Buffer} "

                            "CONFIG.CLKOUT4_USED {true} "
                            "CONFIG.CLKOUT4_REQUESTED_OUT_FREQ {150.0} "
                            "CONFIG.CLK_OUT4_PORT {datamover_cmd_clk} "
                            "CONFIG.CLKOUT4_JITTER {87.900} "
                            "CONFIG.CLKOUT4_PHASE_ERROR {71.599} "
                            "CONFIG.MMCM_CLKOUT3_DIVIDE {10} "
                            "CONFIG.CLKOUT4_DRIVES {Buffer}")
    
    CLK_CONFIG_2CLKS_250MHz = ("CONFIG.PRIMITIVE {MMCM} "
                            "CONFIG.USE_DYN_RECONFIG {true} "
                            "CONFIG.USE_PHASE_ALIGNMENT {true} "
                            "CONFIG.PRIM_SOURCE {Global_buffer} "
                            "CONFIG.PRIM_IN_FREQ {250.0} "
                            "CONFIG.FEEDBACK_SOURCE {FDBK_AUTO} "
                            "CONFIG.MMCM_DIVCLK_DIVIDE {1} "
                            "CONFIG.MMCM_BANDWIDTH {OPTIMIZED} "
                            "CONFIG.MMCM_CLKFBOUT_MULT_F {5.000} "
                            "CONFIG.MMCM_CLKIN1_PERIOD {4.0} "
                            "CONFIG.MMCM_COMPENSATION {AUTO} "
                            "CONFIG.PLL_CLKIN_PERIOD {4.0} "
                            "CONFIG.CLKIN1_JITTER_PS {40.0} "
                            "CONFIG.USE_INCLK_SWITCHOVER {false} "
                            "CONFIG.SECONDARY_IN_FREQ {250.0} "
                            "CONFIG.SECONDARY_SOURCE {Global_buffer} "
                            "CONFIG.CLKIN2_JITTER_PS {40.0} "
                            "CONFIG.MMCM_CLKIN2_PERIOD {4.0} "

                            "CONFIG.NUM_OUT_CLKS {2} "

                            "CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {250.0} "
                            "CONFIG.CLK_OUT1_PORT {seq_clk} "
                            "CONFIG.CLKOUT1_JITTER {85.736} "
                            "CONFIG.CLKOUT1_PHASE_ERROR {79.008} "
                            "CONFIG.MMCM_CLKOUT0_DIVIDE_F {5.000} "
                            "CONFIG.CLKOUT1_DRIVES {Buffer} "

                            "CONFIG.CLKOUT2_USED {true} "
                            "CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {250.0} "
                            "CONFIG.CLK_OUT2_PORT {adc_tile3_clk} "
                            "CONFIG.CLKOUT2_JITTER {85.736} "
                            "CONFIG.CLKOUT2_PHASE_ERROR {79.008} "
                            "CONFIG.MMCM_CLKOUT1_DIVIDE {5} "
                            "CONFIG.CLKOUT2_DRIVES {Buffer}")

    CLK_CONFIG_5CLKS_250MHz = ("CONFIG.PRIMITIVE {MMCM} "
                            "CONFIG.USE_DYN_RECONFIG {true} "
                            "CONFIG.USE_PHASE_ALIGNMENT {true} "
                            "CONFIG.PRIM_SOURCE {Global_buffer} "
                            "CONFIG.PRIM_IN_FREQ {250.0} "
                            "CONFIG.FEEDBACK_SOURCE {FDBK_AUTO} "
                            "CONFIG.MMCM_DIVCLK_DIVIDE {1} "
                            "CONFIG.MMCM_BANDWIDTH {OPTIMIZED} "
                            "CONFIG.MMCM_CLKFBOUT_MULT_F {5.000} "
                            "CONFIG.MMCM_CLKIN1_PERIOD {4.0} "
                            "CONFIG.MMCM_COMPENSATION {AUTO} "
                            "CONFIG.PLL_CLKIN_PERIOD {4.0} "
                            "CONFIG.CLKIN1_JITTER_PS {40.0} "
                            "CONFIG.USE_INCLK_SWITCHOVER {false} "
                            "CONFIG.SECONDARY_IN_FREQ {250.0} "
                            "CONFIG.SECONDARY_SOURCE {Global_buffer} "
                            "CONFIG.CLKIN2_JITTER_PS {40.0} "
                            "CONFIG.MMCM_CLKIN2_PERIOD {4.0} "

                            "CONFIG.NUM_OUT_CLKS {5} "

                            "CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {250.0} "
                            "CONFIG.CLK_OUT1_PORT {seq_clk} "
                            "CONFIG.CLKOUT1_JITTER {85.736} "
                            "CONFIG.CLKOUT1_PHASE_ERROR {79.008} "
                            "CONFIG.MMCM_CLKOUT0_DIVIDE_F {5.000} "
                            "CONFIG.CLKOUT1_DRIVES {Buffer} "

                            "CONFIG.CLKOUT2_USED {true} "
                            "CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {250.0} "
                            "CONFIG.CLK_OUT2_PORT {dac_clk} "
                            "CONFIG.CLKOUT2_JITTER {85.736} "
                            "CONFIG.CLKOUT2_PHASE_ERROR {79.008} "
                            "CONFIG.MMCM_CLKOUT1_DIVIDE {5} "
                            "CONFIG.CLKOUT2_DRIVES {Buffer} "

                            "CONFIG.CLKOUT3_USED {true} "
                            "CONFIG.CLKOUT3_REQUESTED_OUT_FREQ {250.0} "
                            "CONFIG.CLK_OUT3_PORT {dac_tile3_clk} "
                            "CONFIG.CLKOUT3_JITTER {85.736} "
                            "CONFIG.CLKOUT3_PHASE_ERROR {79.008} "
                            "CONFIG.MMCM_CLKOUT1_DIVIDE {5} "
                            "CONFIG.CLKOUT3_DRIVES {Buffer} "
                            
                            "CONFIG.CLKOUT4_USED {true} "
                            "CONFIG.CLKOUT4_REQUESTED_OUT_FREQ {250.0} "
                            "CONFIG.CLK_OUT4_PORT {adc_clk} "
                            "CONFIG.CLKOUT4_JITTER {85.736} "
                            "CONFIG.CLKOUT4_PHASE_ERROR {79.008} "
                            "CONFIG.MMCM_CLKOUT1_DIVIDE {5} "
                            "CONFIG.CLKOUT4_DRIVES {Buffer} "
                            
                            "CONFIG.CLKOUT5_USED {true} "
                            "CONFIG.CLKOUT5_REQUESTED_OUT_FREQ {250.0} "
                            "CONFIG.CLK_OUT5_PORT {adc_tile3_clk} "
                            "CONFIG.CLKOUT5_JITTER {85.736} "
                            "CONFIG.CLKOUT5_PHASE_ERROR {79.008} "
                            "CONFIG.MMCM_CLKOUT1_DIVIDE {5} "
                            "CONFIG.CLKOUT5_DRIVES {Buffer}")
    
    
    
    ###########################################################################
    # Create objects abstracting HDL modules
    ###########################################################################
    
    hdl_modules = []
    
    # Create a primary decoder for the sequencer bus
    sequencer_bus_decoder = BusDecoder("sequencer_bus_decoder", pipeline_miso=True)
    hdl_modules.append(sequencer_bus_decoder)

    # Create split dataport for triggering and monitoring the DMA and for setting continue signals
    _bit = 0
    _dma_trigger_ports = []
    _dma_fifo_empty_ports = []
    _dma_fifo_almost_empty_ports = []
    _dma_running_ports = []
    _adc_fifo_control_ports = []

    for label,count in [("dac", NUM_DAC), ("adc", NUM_ADC), ("cmacc", NUM_CMACC)]:
        for idx in range(count):
            _dma_trigger_ports += [{"name": f"{label}_dma{idx}", 
                                      "direction": BusDataport.OUTPUT, 
                                      "offset": _bit,
                                      "width": 1,
                                      "gate": BusDataport.GATE_RESET}]
                                    #   "pipeline": 1}]

            _dma_fifo_empty_ports += [{"name": f"{label}_dma{idx}", 
                                      "direction": BusDataport.INPUT, 
                                      "offset": _bit,
                                      "width": 1,
                                      "pipeline": 1}]

            _dma_fifo_almost_empty_ports += [{"name": f"{label}_dma{idx}", 
                                              "direction": BusDataport.INPUT, 
                                              "offset": _bit,
                                              "width": 1,
                                              "pipeline": 1}]

            _dma_running_ports += [{"name": f"{label}_dma{idx}", 
                                      "direction": BusDataport.INPUT, 
                                      "offset": _bit,
                                      "width": 1}]
                                    #   "pipeline": 1}]
            if label == "adc":
                _adc_fifo_control_ports += [{"name": f"{label}_dm{idx}_overflow", 
                                          "direction": BusDataport.INPUT, 
                                          "offset": idx,
                                          "width": 1,
                                          "pipeline": 1}]
                
                _adc_fifo_control_ports += [{"name": f"{label}_dm{idx}_misalignment", 
                                          "direction": BusDataport.INPUT, 
                                          "offset": idx + NUM_ADC + NUM_CMACC,
                                          "width": 1,
                                          "pipeline": 1}]
                
                _adc_fifo_control_ports += [{"name": f"{label}_dm{idx}_reset", 
                                          "direction": BusDataport.OUTPUT, 
                                          "offset": idx,
                                          "gate": BusDataport.GATE_RESET,
                                          "width": 1,
                                          "pipeline": 1}]
            elif label == "cmacc":
                _adc_fifo_control_ports += [{"name": f"{label}_dm{idx}_overflow", 
                                          "direction": BusDataport.INPUT, 
                                          "offset": idx + NUM_ADC,
                                          "width": 1,
                                          "pipeline": 1}]
                
                _adc_fifo_control_ports += [{"name": f"{label}_dm{idx}_misalignment", 
                                          "direction": BusDataport.INPUT, 
                                          "offset": idx + NUM_ADC + NUM_CMACC + NUM_ADC,
                                          "width": 1,
                                          "pipeline": 1}]
                
                _adc_fifo_control_ports += [{"name": f"{label}_dm{idx}_reset", 
                                          "direction": BusDataport.OUTPUT, 
                                          "offset": idx + NUM_ADC,
                                          "gate": BusDataport.GATE_RESET,
                                          "width": 1,
                                          "pipeline": 1}]
            _bit += 1

            fifo_port = BusDevice(name=f"{label}_dma{idx}_fifo", size=1)
            sequencer_bus_decoder.add(fifo_port)

    dma_trigger = BusDataport(name="dma_trigger", ports=_dma_trigger_ports)
    sequencer_bus_decoder.add(dma_trigger)
    hdl_modules.append(dma_trigger)
    
    dma_fifo_empty = BusDataport(name="dma_fifo_empty", ports=_dma_fifo_empty_ports)
    sequencer_bus_decoder.add(dma_fifo_empty, pipeline=True)
    hdl_modules.append(dma_fifo_empty)

    dma_fifo_almost_empty = BusDataport(name="dma_fifo_almost_empty", ports=_dma_fifo_almost_empty_ports)
    sequencer_bus_decoder.add(dma_fifo_almost_empty, pipeline=True)
    hdl_modules.append(dma_fifo_almost_empty) 

    dma_running = BusDataport(name="dma_running", ports=_dma_running_ports)
    sequencer_bus_decoder.add(dma_running, pipeline=True)
    hdl_modules.append(dma_running)
    
    adc_fifo_control = BusDataport(name="adc_fifo_control", ports=_adc_fifo_control_ports)
    sequencer_bus_decoder.add(adc_fifo_control, pipeline=True)
    hdl_modules.append(adc_fifo_control)

    # Create dataports for controlling accumulator offsets and output values
    for i in range(NUM_CMACC):
        for quad in ["re", "im"]:
            _cmacc_dataports = []

            _cmacc_dataports += [{"name": f"accumulator",
                                   "direction": BusDataport.INPUT,
                                   "offset": 0,
                                   "width": 32,
                                   "pipeline": 1}]
            _cmacc_dataports += [{"name": f"offset",
                                   "direction": BusDataport.OUTPUT,
                                   "offset": 0,
                                   "width": 32,
                                   "gate": BusDataport.GATE_REGCE,
                                   "pipeline": 1}]

            _cmacc_port = BusDataport(name=f"cmacc{i}_{quad}", ports=_cmacc_dataports)
            sequencer_bus_decoder.add(_cmacc_port, pipeline=True)
            hdl_modules.append(_cmacc_port)

    # Add a reset port
    _cmacc_reset_ports = []

    for i in range(NUM_CMACC):
        _cmacc_reset_ports += [{"name": f"cmacc{i}", 
                                  "direction": BusDataport.OUTPUT, 
                                  "offset": i,
                                  "width": 1,
                                  "gate": BusDataport.GATE_RESET,
                                  "pipeline": 1}]

    cmacc_reset_port = BusDataport(name=f"cmacc_reset", ports=_cmacc_reset_ports)
    sequencer_bus_decoder.add(cmacc_reset_port, pipeline=True)
    hdl_modules.append(cmacc_reset_port)

    # Create dataports for monitoring the CMACCs for completion
    _cmacc_status_dataports = []
    for i in range(NUM_CMACC):
        _cmacc_status_dataports += [{"name": f"cmacc{i}_valid",
                                   "direction": BusDataport.INPUT,
                                   "offset": i,
                                   "width": 1,
                                   "pipeline": 1}]
        _cmacc_status_dataports += [{"name": f"cmacc{i}_last",
                                   "direction": BusDataport.INPUT,
                                   "offset": NUM_CMACC + i,
                                   "width": 1,
                                   "pipeline": 1}]
        _cmacc_status_dataports += [{"name": f"cmacc{i}_re_msb",
                                   "direction": BusDataport.INPUT,
                                   "offset": 2*NUM_CMACC + i,
                                   "width": 1,
                                   "pipeline": 1}]
        _cmacc_status_dataports += [{"name": f"cmacc{i}_im_msb",
                                   "direction": BusDataport.INPUT,
                                   "offset": 3*NUM_CMACC + i,
                                   "width": 1,
                                   "pipeline": 1}]

    cmacc_status = BusDataport(name="cmacc_status", ports=_cmacc_status_dataports)
    sequencer_bus_decoder.add(cmacc_status)
    hdl_modules.append(cmacc_status)

    # Create dataports for interacting with the PS GPIO
    for gpio_num, size in [(3, 32), (4, 32), (5, NUM_PS_GPIO % 32)]:
        _ps_gpio_dataports = []

        _ps_gpio_dataports += [{"name": f"gpio_out",
                                   "direction": BusDataport.INPUT,
                                   "offset": 0,
                                   "width": size,
                                   "pipeline": 2}]
        _ps_gpio_dataports += [{"name": f"gpio_in",
                                   "direction": BusDataport.OUTPUT,
                                   "offset": 0,
                                   "width": size,
                                   "gate": BusDataport.GATE_REGCE,
                                   "pipeline": 2}]

        _ps_gpio = BusDataport(name=f"ps_gpio{gpio_num}", ports=_ps_gpio_dataports)
        sequencer_bus_decoder.add(_ps_gpio, pipeline=True)
        hdl_modules.append(_ps_gpio)

    _ps_irq_dataports = []
    for i in range(NUM_PS_IRQ):
        _ps_irq_dataports += [{"name": f"irq{i}",
                               "direction": BusDataport.OUTPUT,
                               "offset": i,
                               "width": 1,
                               "gate": BusDataport.GATE_REGCE,
                               "pipeline": 2}]

    _ps_irq_dataports += [{"name": f"gdma_irq",
                           "direction": BusDataport.INPUT,
                           "offset": NUM_PS_IRQ + i,
                           "width": NUM_PS_GDMA,
                           "pipeline": 2}]

    ps_irq = BusDataport(name="ps_irq", ports=_ps_irq_dataports)
    sequencer_bus_decoder.add(ps_irq, pipeline=True)
    hdl_modules.append(ps_irq)

    # Create a register file for RFDC real-time updates and connect it to the sequencer bus
    rfdc_rts_regs = BusDevice("rfdc_rts_regs", size=256)
    sequencer_bus_decoder.add(rfdc_rts_regs, pipeline=True)

    # Create a register file for interacting with the PS GDMA
    zdma_controller = BusDevice("zdma_controller", size=64)
    sequencer_bus_decoder.add(zdma_controller, pipeline=True)

    _clk104_sync_in_dataports = [{"name": f"sync",
                                   "direction": BusDataport.OUTPUT,
                                   "offset": 0,
                                   "width": 1,
                                   "gate": BusDataport.GATE_REGCE,
                                   "pipeline": 2}]

    clk104_sync_in = BusDataport(name="clk104_sync_in", ports=_clk104_sync_in_dataports)
    sequencer_bus_decoder.add(clk104_sync_in, pipeline=True)
    hdl_modules.append(clk104_sync_in)

    # Create cache and connect it to the sequencer bus
    cache = BusDevice("cache", size=CACHE_MEMORY_SIZE_BITS // 32)
    sequencer_bus_decoder.add(cache)

    datamover_controller = BusDataMoverController("datamover_controller", 
                                                  [f"adc_dm{i}" for i in range(4)] + 
                                                  [f"cmacc_dm{i}" for i in range(4)] + 
                                                  ["cfg_dm_mm2s", "cfg_dm_s2mm"], addr_bits=40)
    sequencer_bus_decoder.add(datamover_controller, pipeline=True)
    hdl_modules.append(datamover_controller)
    
    # Assign decoder addresses
    sequencer_bus_decoder.assign_address(0)

    # Create AXI-controlled memories

    # Create an AXI BRAM Controller wrapper for the cache
    cache_memory_controller = AXIMemoryArray("cache", 
        size_bits=CACHE_MEMORY_SIZE_BITS, 
        width=32, 
        controller_width=128,
        elements=1, 
        axi_id_width=17, # 1 bit needed for AXI crossbar, 16 from PS master
        synchronous=False,
        read_only=False,
        use_rst=False,
        primitive="block", 
        controller_port_input_pipeline=0,
        controller_port_output_pipeline=1,                              
        user_port_input_pipeline=0,
        user_port_output_pipeline=1)
    hdl_modules.append(cache_memory_controller)

    instruction_memory_controller = AXIMemoryArray("instruction", 
        size_bits=INSTRUCTION_MEMORY_SIZE_BITS, 
        width=128, 
        elements=1, 
        axi_id_width=17, # 1 bit needed for AXI crossbar, 16 from PS master
        synchronous=False,
        read_only=True,
        use_rst=False,
        primitive="block", 
        controller_port_input_pipeline=2,
        controller_port_output_pipeline=2,
        user_port_input_pipeline=0,
        user_port_output_pipeline=0)
    hdl_modules.append(instruction_memory_controller)

    dac_memory_controller = AXIMemoryArray(f"dac", 
        size_bits=DAC_MEMORY_SIZE_BITS, 
        width=128, 
        elements=NUM_DAC, 
        read_only=True,
        use_rst=True,
        primitive="ultra", 
        controller_port_input_pipeline=2,
        controller_port_output_pipeline=2,   
        user_port_input_pipeline=1,
        user_port_output_pipeline=2)
    hdl_modules.append(dac_memory_controller)

    cmacc_kernel_memory_controller = AXIMemoryArray(f"cmacc_kernel", 
        size_bits=CMACC_KERNEL_MEMORY_SIZE_BITS, 
        width=32, 
        elements=NUM_CMACC, 
        read_only=True,
        use_rst=True,
        primitive="block", 
        controller_port_input_pipeline=2,
        controller_port_output_pipeline=2,   
        user_port_input_pipeline=0,
        user_port_output_pipeline=1)
    hdl_modules.append(cmacc_kernel_memory_controller)

    dac_dma_descriptor_memory_controller = AXIMemoryArray(f"dac_dma_descriptor", 
        size_bits=DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS, 
        width=64, 
        elements=NUM_DAC, 
        read_only=True,
        use_rst=False,
        primitive="block", 
        controller_port_input_pipeline=2,
        controller_port_output_pipeline=2,   
        user_port_input_pipeline=0,
        user_port_output_pipeline=1)
    hdl_modules.append(dac_dma_descriptor_memory_controller)

    adc_dma_descriptor_memory_controller = AXIMemoryArray(f"adc_dma_descriptor", 
        size_bits=ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS, 
        width=64, 
        elements=NUM_ADC, 
        read_only=True,
        use_rst=False,
        primitive="block", 
        controller_port_input_pipeline=2,
        controller_port_output_pipeline=2,   
        user_port_input_pipeline=0,
        user_port_output_pipeline=1)
    hdl_modules.append(adc_dma_descriptor_memory_controller)

    cmacc_dma_descriptor_memory_controller = AXIMemoryArray(f"cmacc_dma_descriptor", 
        size_bits=CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS, 
        width=64, 
        elements=NUM_CMACC, 
        read_only=True,
        use_rst=False,
        primitive="block", 
        controller_port_input_pipeline=2,
        controller_port_output_pipeline=2,   
        user_port_input_pipeline=0,
        user_port_output_pipeline=1)
    hdl_modules.append(cmacc_dma_descriptor_memory_controller)
    
    @classmethod
    def write_hdl(cls, project_dir, filename="python_modules.vhd"):
        """
        Writes a VHDL file with the modules

        :param filename: The name of the file in the project directory in which
            to write the file.
        :type filename: str, optional
        """

        if not os.path.exists(project_dir):
            os.mkdir(project_dir)
            
        cls._hdl_filename = os.path.join(project_dir, filename)
        with open(cls._hdl_filename, "w") as f:
            for module in cls.hdl_modules:
                f.write(module.generate_hdl() + '\n')
    
    @classmethod
    def write_hedgehog_tcl(cls, project_dir, tcl_filename="hedgehog.tcl", constraints_filename="hedgehog.xdc"):
        """
        Write a TCL script to populate the HEDGEHOG logic in the standard image. 
        """

        if not hasattr(cls, "_hdl_filename"):
            raise ValueError("Call `write_hdl` before `write_hedgehog_tcl`.")
        with open(os.path.join(project_dir, tcl_filename), "w") as f, \
                open(os.path.join(project_dir, constraints_filename), "w") as constraints:
            f.write(f"read_vhdl {cls._hdl_filename}\n")
            
            # Write the TCL that will generate the IP for the AXI memory controllers
            memory_tcl = cls.cache_memory_controller.generate_ip_tcl(project_dir)
            memory_tcl += cls.instruction_memory_controller.generate_ip_tcl(project_dir)
            memory_tcl += cls.dac_memory_controller.generate_ip_tcl(project_dir)
            memory_tcl += cls.cmacc_kernel_memory_controller.generate_ip_tcl(project_dir)
            memory_tcl += cls.dac_dma_descriptor_memory_controller.generate_ip_tcl(project_dir)
            memory_tcl += cls.adc_dma_descriptor_memory_controller.generate_ip_tcl(project_dir)
            memory_tcl += cls.cmacc_dma_descriptor_memory_controller.generate_ip_tcl(project_dir)
            f.write(memory_tcl)
            
            # ------------------- Clock Management -------------------- #

            # The PL clock from the CLK104 is brought in through an HDIO bank, so we need to buffer
            # it with an IBUFDS before feeding it to the MMCM
            create_ip(f, name="hedgehog/pl_clk_ibufds", vlnv="xilinx.com:ip:util_ds_buf:2.1")
            set_property(f, name="hedgehog/pl_clk_ibufds", properties={"C_SIZE": 1, "C_BUF_TYPE": "IBUFDS"})
            
            create_ip(f, name="hedgehog/pl_clk_bufg", vlnv="xilinx.com:ip:util_ds_buf:2.1")
            set_property(f, name="hedgehog/pl_clk_bufg", properties={"C_SIZE": 1, "C_BUF_TYPE": "BUFG"})
            
            connect_bd_intf_net(f, "hedgehog/CLK104_PL_CLK", "hedgehog/pl_clk_ibufds/CLK_IN_D")
            connect_bd_net(f, "hedgehog/pl_clk_ibufds/IBUF_OUT", "hedgehog/pl_clk_bufg/BUFG_I")
            
            # Connect a second input clock to the clocking wizard for the 8A34001
            create_ip(f, name="hedgehog/clk_8A34001_out3_ibufds", vlnv="xilinx.com:ip:util_ds_buf:2.1")
            set_property(f, name="hedgehog/clk_8A34001_out3_ibufds", properties={"C_SIZE": 1, "C_BUF_TYPE": "IBUFDS"})
            connect_bd_intf_net(f, "hedgehog/CLK_8A34001_Q3_OUT", "hedgehog/clk_8A34001_out3_ibufds/CLK_IN_D")
            
            # Create reset synchronizers for the various clock domains
            # create_ip(f, name="hedgehog/proc_sys_reset_PS_clk_250", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
            # connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_clk_250/slowest_sync_clk", f"hedgehog/PS_clk_250")
            # connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_clk_250/ext_reset_in", f"hedgehog/PS_resetn")
            
            # create_ip(f, name=f"hedgehog/xlconst_proc_sys_reset_PS_clk_250_locked", vlnv="xilinx.com:ip:xlconstant:1.1")
            # set_property(f, name=f"hedgehog/xlconst_proc_sys_reset_PS_clk_250_locked", properties={"CONST_WIDTH": 1, "CONST_VAL": 1})
            # connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_clk_250/dcm_locked", f"hedgehog/xlconst_proc_sys_reset_PS_clk_250_locked/Dout")
            
            create_ip(f, name="hedgehog/proc_sys_reset_PS_AXI_clk", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_AXI_clk/slowest_sync_clk", f"hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_AXI_clk/ext_reset_in", f"hedgehog/PS_resetn")
            
            create_ip(f, name=f"hedgehog/xlconst_proc_sys_reset_PS_AXI_clk_locked", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name=f"hedgehog/xlconst_proc_sys_reset_PS_AXI_clk_locked", properties={"CONST_WIDTH": 1, "CONST_VAL": 1})
            connect_bd_net(f, f"hedgehog/proc_sys_reset_PS_AXI_clk/dcm_locked", f"hedgehog/xlconst_proc_sys_reset_PS_AXI_clk_locked/Dout")
            
            # We'll create an MMCM that will generate all the PL clocks
            create_ip(f, name="hedgehog/clk_wiz", vlnv="xilinx.com:ip:clk_wiz:6.0")
            set_property(f, name="hedgehog/clk_wiz", properties={"PRIM_IN_FREQ.VALUE_SRC": "USER"})
            set_property(f, name="hedgehog/clk_wiz", properties=Firmware.CLK_CONFIG_5CLKS_250MHz)
            connect_bd_net(f, f"hedgehog/clk_wiz/s_axi_aclk", f"hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/clk_wiz/s_axi_aresetn", f"hedgehog/proc_sys_reset_PS_AXI_clk/peripheral_aresetn")

            # Connect the CLK104 PL clock buffer output to the clock wizard and apply a constraint
            connect_bd_net(f, f"hedgehog/pl_clk_bufg/BUFG_O", f"hedgehog/clk_wiz/clk_in1")
            constraints.write("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets acadia_bd_i/hedgehog/pl_clk_bufg_BUFG_O]\n")
            constraints.write("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets acadia_bd_i/hedgehog/clk_wiz/inst/CLK_CORE_DRP_I/clk_inst/clk_in1_acadia_bd_clk_wiz_0]\n")
            f.write("set_property -dict [list CONFIG.FREQ_HZ {250000000}] [get_bd_intf_ports CLK104_PL_CLK]\n")
            
            # Connect the clock from the 8A34001 to the clocking wizard
            # connect_bd_net(f, "hedgehog/clk_8A34001_out3_ibufds/IBUF_OUT", f"hedgehog/clk_wiz/clk_in2")
            f.write("set_property -dict [list CONFIG.FREQ_HZ {250000000}] [get_bd_intf_ports CLK_8A34001_Q3_OUT]\n")

            # Create a reset module for the clocking wizard output
            create_ip(f, name="hedgehog/proc_sys_reset_seq_clk", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_seq_clk/slowest_sync_clk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_seq_clk/ext_reset_in", f"hedgehog/PS_resetn")
            connect_bd_net(f, f"hedgehog/proc_sys_reset_seq_clk/dcm_locked", f"hedgehog/clk_wiz/locked")
            
            
            # ------------------- AXI Interconnects and SmartConnects -------------------- #

            # Create a SmartConnect for simple configuration peripherals
            # 1 Master: PS AXI LPD Master
            # 8 Slaves: RFDC, Clocking, ADC Axis Switch, ADC DMA descriptors, CMACC DMA descriptors, CMACC kernel memory, DAC memory, DAC DMA descriptor
            create_ip(f, name="hedgehog/config_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, 
                         name="hedgehog/config_smartconnect", 
                         properties={"NUM_MI": 8, 
                                     "NUM_SI": 1, 
                                     "NUM_CLKS": 2})
            connect_bd_net(f, f"hedgehog/config_smartconnect/aclk", f"hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/config_smartconnect/aclk1", f"hedgehog/clk_wiz/seq_clk")
            # connect_bd_net(f, f"hedgehog/config_smartconnect/aclk2", f"hedgehog/PS_clk_250")
            connect_bd_net(f, f"hedgehog/config_smartconnect/aresetn", f"hedgehog/proc_sys_reset_PS_AXI_clk/interconnect_aresetn")
            
            # Connect it to the PS
            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/S00_AXI", f"hedgehog/PS_M_AXI_LPD")

            # Connect the clock wizard to the smartconnect and assign it address space
            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/M00_AXI", f"hedgehog/clk_wiz/s_axi_lite")
            assign_bd_address(f, "/ps/Data", "hedgehog/clk_wiz/s_axi_lite/Reg", Firmware.CLK_WIZ_ADDRESS, "256K")

            # Create an AXI Crossbar for more rapid access to cache and instruction memories
            # 2 Masters: PS AXI Master 1, CFG AXI DataMover S2MM
            # 2 slaves: cache, instruction memory
            create_ip(f, name="hedgehog/memory_crossbar", vlnv="xilinx.com:ip:axi_crossbar:2.1")
            set_property(f, name="hedgehog/memory_crossbar", 
                         properties={"NUM_SI": 2,
                                     "NUM_MI": 2,
                                     "STRATEGY": 1,
                                     "CONNECTIVITY_MODE": "SAMD"})
                        
            connect_bd_net(f, "hedgehog/memory_crossbar/aclk", "hedgehog/PS_AXI_clk")
            connect_bd_net(f, "hedgehog/memory_crossbar/aresetn", "hedgehog/proc_sys_reset_PS_AXI_clk/interconnect_aresetn")

            # Connect it to the PS
            connect_bd_intf_net(f, f"hedgehog/memory_crossbar/S00_AXI", f"hedgehog/PS_M_AXI1")

            # Changed advanced properties to get:
            # set_property -dict [list CONFIG.ADVANCED_PROPERTIES { __view__ { timing { S00_Buffer { AR_M_SEND_PIPE 0 AW_M_SEND_PIPE 0 W_M_SEND_PIPE 0 } M00_Buffer { B_M_SEND_PIPE 0 R_M_SEND_PIPE 0 } S00_Entry { MMU_REGSLICE 0 TR_REGSLICE 0 } M00_Exit { REGSLICE 0 } SW0 { AR_M_PIPE 0 AW_M_PIPE 0 B_M_PIPE 0 R_M_PIPE 0 W_M_PIPE 0 } } }}] [get_bd_cells hedgehog/memory_interconnect]
            # set_property -dict [list CONFIG.ADVANCED_PROPERTIES {  __view__ { functional { S00_Buffer { AR_SIZE 0 AW_SIZE 0 B_SIZE 0 R_SIZE 0 W_SIZE 0 } M00_Buffer { AR_SIZE 0 AW_SIZE 0 B_SIZE 0 R_SIZE 0 W_SIZE 0 } } timing { S00_Buffer { AR_M_SEND_PIPE 0 AW_M_SEND_PIPE 0 W_M_SEND_PIPE 0 } M00_Buffer { B_M_SEND_PIPE 0 R_M_SEND_PIPE 0 } S00_Entry { MMU_REGSLICE 0 TR_REGSLICE 0 } M00_Exit { REGSLICE 0 } SW0 { AR_M_PIPE 0 AW_M_PIPE 0 B_M_PIPE 0 R_M_PIPE 0 W_M_PIPE 0 } } } }] [get_bd_cells hedgehog/memory_interconnect]


            # Create a SmartConnect for high-performance bulk transfers
            # 10 Masters: PS AXI Master 0, ADC AXI DataMover 0-3 S2MM, CMACC Signal AXI DataMover 0-3 S2MM, CFG AXI DataMover MM2S
            # 6 Slaves: PS AXI Slave HPC0, PS AXI Slave HPC1, PS AXI Slave HP0, PS AXI Slave HP1, PL DDR C0, PL DDR C1
            create_ip(f, name="hedgehog/bulk_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, name="hedgehog/bulk_smartconnect", properties={"NUM_MI": 6, "NUM_SI": 10, "NUM_CLKS": 4})
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aclk", f"hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aclk1", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aclk2", f"hedgehog/DDR4_C0_ui_clk")
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aclk3", f"hedgehog/DDR4_C1_ui_clk")
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aresetn", f"hedgehog/proc_sys_reset_PS_AXI_clk/interconnect_aresetn")

            # Connect it to the PS and various interface ports
            connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/S00_AXI", f"hedgehog/PS_M_AXI0")

            connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/M00_AXI", f"hedgehog/PS_S_AXI_HPC0")
            connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/M01_AXI", f"hedgehog/PS_S_AXI_HPC1")
            connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/M02_AXI", f"hedgehog/PS_S_AXI_HP0")
            connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/M03_AXI", f"hedgehog/PS_S_AXI_HP1")
            connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/M04_AXI", f"hedgehog/DDR4_C0_S_AXI")
            connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/M05_AXI", f"hedgehog/DDR4_C1_S_AXI")
            
            # ------------------- RF Data Converters -------------------- #

            create_ip(f, name="hedgehog/rfdc", vlnv="xilinx.com:ip:usp_rf_data_converter:2.4")
            
            # Auto-generated config string by Vivado
            rfdc_config_string = ("CONFIG.ADC0_Clock_Source {2} "
                                   "CONFIG.ADC0_Fabric_Freq {250.000} "
                                   "CONFIG.ADC0_Multi_Tile_Sync {true} "
                                   "CONFIG.ADC0_Outclk_Freq {250.000} "
                                   "CONFIG.ADC0_PLL_Enable {true} "
                                   "CONFIG.ADC0_Refclk_Freq {250.000} "
                                   "CONFIG.ADC0_Sampling_Rate {2.0} "
                                   "CONFIG.ADC1_Clock_Source {2} "
                                   "CONFIG.ADC1_Enable {1} "
                                   "CONFIG.ADC1_Fabric_Freq {250.000} "
                                   "CONFIG.ADC1_Multi_Tile_Sync {true} "
                                   "CONFIG.ADC1_Outclk_Freq {250.000} "
                                   "CONFIG.ADC1_PLL_Enable {true} "
                                   "CONFIG.ADC1_Refclk_Freq {250.000} "
                                   "CONFIG.ADC1_Sampling_Rate {2.0} "
                                   "CONFIG.ADC2_Clock_Dist {1} "
                                   "CONFIG.ADC2_Clock_Source {2} "
                                   "CONFIG.ADC2_Enable {1} "
                                   "CONFIG.ADC2_Fabric_Freq {250.000} "
                                   "CONFIG.ADC2_Multi_Tile_Sync {true} "
                                   "CONFIG.ADC2_Outclk_Freq {250.000} "
                                   "CONFIG.ADC2_PLL_Enable {true} "
                                   "CONFIG.ADC2_Refclk_Freq {250.000} "
                                   "CONFIG.ADC2_Sampling_Rate {2.0} "
                                   "CONFIG.ADC3_Clock_Source {2} "
                                   "CONFIG.ADC3_Enable {1} "
                                   "CONFIG.ADC3_Fabric_Freq {250.000} "
                                   "CONFIG.ADC3_Multi_Tile_Sync {true} "
                                   "CONFIG.ADC3_Outclk_Freq {250.000} "
                                   "CONFIG.ADC3_PLL_Enable {true} "
                                   "CONFIG.ADC3_Refclk_Freq {250.000} "
                                   "CONFIG.ADC3_Sampling_Rate {2.0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq00 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq01 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq02 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq03 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq10 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq11 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq12 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq13 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq20 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq21 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq22 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq23 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq30 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq31 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq32 {0} "
                                   "CONFIG.ADC_Coarse_Mixer_Freq33 {0} "
                                   "CONFIG.ADC_DSA_RTS {true} "
                                   "CONFIG.ADC_Data_Type00 {1} "
                                   "CONFIG.ADC_Data_Type01 {1} "
                                   "CONFIG.ADC_Data_Type02 {1} "
                                   "CONFIG.ADC_Data_Type03 {1} "
                                   "CONFIG.ADC_Data_Type10 {1} "
                                   "CONFIG.ADC_Data_Type11 {1} "
                                   "CONFIG.ADC_Data_Type12 {1} "
                                   "CONFIG.ADC_Data_Type13 {1} "
                                   "CONFIG.ADC_Data_Type20 {1} "
                                   "CONFIG.ADC_Data_Type21 {1} "
                                   "CONFIG.ADC_Data_Type22 {1} "
                                   "CONFIG.ADC_Data_Type23 {1} "
                                   "CONFIG.ADC_Data_Type30 {1} "
                                   "CONFIG.ADC_Data_Type31 {1} "
                                   "CONFIG.ADC_Data_Type32 {1} "
                                   "CONFIG.ADC_Data_Type33 {1} "
                                   "CONFIG.ADC_Data_Width00 {8} "
                                   "CONFIG.ADC_Decimation_Mode00 {2} "
                                   "CONFIG.ADC_Decimation_Mode01 {2} "
                                   "CONFIG.ADC_Decimation_Mode02 {2} "
                                   "CONFIG.ADC_Decimation_Mode03 {2} "
                                   "CONFIG.ADC_Decimation_Mode10 {2} "
                                   "CONFIG.ADC_Decimation_Mode11 {2} "
                                   "CONFIG.ADC_Decimation_Mode12 {2} "
                                   "CONFIG.ADC_Decimation_Mode13 {2} "
                                   "CONFIG.ADC_Decimation_Mode20 {2} "
                                   "CONFIG.ADC_Decimation_Mode21 {2} "
                                   "CONFIG.ADC_Decimation_Mode22 {2} "
                                   "CONFIG.ADC_Decimation_Mode23 {2} "
                                   "CONFIG.ADC_Decimation_Mode30 {2} "
                                   "CONFIG.ADC_Decimation_Mode31 {2} "
                                   "CONFIG.ADC_Decimation_Mode32 {2} "
                                   "CONFIG.ADC_Decimation_Mode33 {2} "
                                   "CONFIG.ADC_Dither00 {false} "
                                   "CONFIG.ADC_Dither01 {false} "
                                   "CONFIG.ADC_Dither02 {false} "
                                   "CONFIG.ADC_Dither03 {false} "
                                   "CONFIG.ADC_Dither10 {false} "
                                   "CONFIG.ADC_Dither11 {false} "
                                   "CONFIG.ADC_Dither12 {false} "
                                   "CONFIG.ADC_Dither13 {false} "
                                   "CONFIG.ADC_Dither20 {false} "
                                   "CONFIG.ADC_Dither21 {false} "
                                   "CONFIG.ADC_Dither22 {false} "
                                   "CONFIG.ADC_Dither23 {false} "
                                   "CONFIG.ADC_Dither30 {false} "
                                   "CONFIG.ADC_Dither31 {false} "
                                   "CONFIG.ADC_Dither32 {false} "
                                   "CONFIG.ADC_Dither33 {false} "
                                   "CONFIG.ADC_Mixer_Mode00 {0} "
                                   "CONFIG.ADC_Mixer_Mode01 {0} "
                                   "CONFIG.ADC_Mixer_Mode02 {0} "
                                   "CONFIG.ADC_Mixer_Mode03 {0} "
                                   "CONFIG.ADC_Mixer_Mode10 {0} "
                                   "CONFIG.ADC_Mixer_Mode11 {0} "
                                   "CONFIG.ADC_Mixer_Mode12 {0} "
                                   "CONFIG.ADC_Mixer_Mode13 {0} "
                                   "CONFIG.ADC_Mixer_Mode20 {0} "
                                   "CONFIG.ADC_Mixer_Mode21 {0} "
                                   "CONFIG.ADC_Mixer_Mode22 {0} "
                                   "CONFIG.ADC_Mixer_Mode23 {0} "
                                   "CONFIG.ADC_Mixer_Mode30 {0} "
                                   "CONFIG.ADC_Mixer_Mode31 {0} "
                                   "CONFIG.ADC_Mixer_Mode32 {0} "
                                   "CONFIG.ADC_Mixer_Mode33 {0} "
                                   "CONFIG.ADC_Mixer_Type00 {2} "
                                   "CONFIG.ADC_Mixer_Type01 {2} "
                                   "CONFIG.ADC_Mixer_Type02 {2} "
                                   "CONFIG.ADC_Mixer_Type03 {2} "
                                   "CONFIG.ADC_Mixer_Type10 {2} "
                                   "CONFIG.ADC_Mixer_Type11 {2} "
                                   "CONFIG.ADC_Mixer_Type12 {2} "
                                   "CONFIG.ADC_Mixer_Type13 {2} "
                                   "CONFIG.ADC_Mixer_Type20 {2} "
                                   "CONFIG.ADC_Mixer_Type21 {2} "
                                   "CONFIG.ADC_Mixer_Type22 {2} "
                                   "CONFIG.ADC_Mixer_Type23 {2} "
                                   "CONFIG.ADC_Mixer_Type30 {2} "
                                   "CONFIG.ADC_Mixer_Type31 {2} "
                                   "CONFIG.ADC_Mixer_Type32 {2} "
                                   "CONFIG.ADC_Mixer_Type33 {2} "
                                   "CONFIG.ADC_NCO_RTS {true} "
                                   "CONFIG.ADC_OBS03 {false} "
                                   "CONFIG.ADC_OBS11 {false} "
                                   "CONFIG.ADC_OBS12 {false} "
                                   "CONFIG.ADC_OBS13 {false} "
                                   "CONFIG.ADC_OBS21 {false} "
                                   "CONFIG.ADC_OBS22 {false} "
                                   "CONFIG.ADC_OBS23 {false} "
                                   "CONFIG.ADC_OBS31 {false} "
                                   "CONFIG.ADC_OBS32 {false} "
                                   "CONFIG.ADC_OBS33 {false} "
                                   "CONFIG.ADC_RESERVED_1_00 {false} "
                                   "CONFIG.ADC_RESERVED_1_01 {false} "
                                   "CONFIG.ADC_RESERVED_1_02 {false} "
                                   "CONFIG.ADC_RESERVED_1_03 {false} "
                                   "CONFIG.ADC_RESERVED_1_10 {false} "
                                   "CONFIG.ADC_RESERVED_1_11 {false} "
                                   "CONFIG.ADC_RESERVED_1_12 {false} "
                                   "CONFIG.ADC_RESERVED_1_13 {false} "
                                   "CONFIG.ADC_RESERVED_1_20 {false} "
                                   "CONFIG.ADC_RESERVED_1_21 {false} "
                                   "CONFIG.ADC_RESERVED_1_22 {false} "
                                   "CONFIG.ADC_RESERVED_1_23 {false} "
                                   "CONFIG.ADC_RESERVED_1_30 {false} "
                                   "CONFIG.ADC_RESERVED_1_31 {false} "
                                   "CONFIG.ADC_RESERVED_1_32 {false} "
                                   "CONFIG.ADC_RESERVED_1_33 {false} "
                                   "CONFIG.ADC_RTS {true} "
                                   "CONFIG.ADC_Slice01_Enable {true} "
                                   "CONFIG.ADC_Slice02_Enable {true} "
                                   "CONFIG.ADC_Slice03_Enable {true} "
                                   "CONFIG.ADC_Slice10_Enable {true} "
                                   "CONFIG.ADC_Slice11_Enable {true} "
                                   "CONFIG.ADC_Slice12_Enable {true} "
                                   "CONFIG.ADC_Slice13_Enable {true} "
                                   "CONFIG.ADC_Slice20_Enable {true} "
                                   "CONFIG.ADC_Slice21_Enable {true} "
                                   "CONFIG.ADC_Slice22_Enable {true} "
                                   "CONFIG.ADC_Slice23_Enable {true} "
                                   "CONFIG.ADC_Slice30_Enable {true} "
                                   "CONFIG.ADC_Slice31_Enable {true} "
                                   "CONFIG.ADC_Slice32_Enable {true} "
                                   "CONFIG.ADC_Slice33_Enable {true} "
                                   "CONFIG.Axiclk_Freq {250} "
                                   "CONFIG.DAC0_Clock_Source {6} "
                                   "CONFIG.DAC0_Enable {1} "
                                   "CONFIG.DAC0_Fabric_Freq {250.000} "
                                   "CONFIG.DAC0_Multi_Tile_Sync {true} "
                                   "CONFIG.DAC0_Outclk_Freq {375.000} "
                                   "CONFIG.DAC0_PLL_Enable {true} "
                                   "CONFIG.DAC0_Refclk_Freq {250.000} "
                                   "CONFIG.DAC0_Sampling_Rate {6} "
                                   "CONFIG.DAC1_Clock_Source {6} "
                                   "CONFIG.DAC1_Enable {1} "
                                   "CONFIG.DAC1_Fabric_Freq {250.000} "
                                   "CONFIG.DAC1_Multi_Tile_Sync {true} "
                                   "CONFIG.DAC1_Outclk_Freq {375.000} "
                                   "CONFIG.DAC1_PLL_Enable {true} "
                                   "CONFIG.DAC1_Refclk_Freq {250.000} "
                                   "CONFIG.DAC1_Sampling_Rate {6} "
                                   "CONFIG.DAC2_Clock_Dist {1} "
                                   "CONFIG.DAC2_Enable {1} "
                                   "CONFIG.DAC2_Fabric_Freq {250.000} "
                                   "CONFIG.DAC2_Multi_Tile_Sync {true} "
                                   "CONFIG.DAC2_Outclk_Freq {375.000} "
                                   "CONFIG.DAC2_PLL_Enable {true} "
                                   "CONFIG.DAC2_Refclk_Freq {250.000} "
                                   "CONFIG.DAC2_Sampling_Rate {6} "
                                   "CONFIG.DAC2_VOP {40.0} "
                                   "CONFIG.DAC3_Clock_Source {6} "
                                   "CONFIG.DAC3_Enable {1} "
                                   "CONFIG.DAC3_Fabric_Freq {250.000} "
                                   "CONFIG.DAC3_Multi_Tile_Sync {true} "
                                   "CONFIG.DAC3_Outclk_Freq {375.000} "
                                   "CONFIG.DAC3_PLL_Enable {true} "
                                   "CONFIG.DAC3_Refclk_Freq {250.000} "
                                   "CONFIG.DAC3_Sampling_Rate {6} "
                                   "CONFIG.DAC3_VOP {40.0} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq00 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq01 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq02 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq03 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq10 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq11 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq12 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq13 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq20 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq21 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq22 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq23 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq30 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq31 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq32 {3} "
                                   "CONFIG.DAC_Coarse_Mixer_Freq33 {3} "
                                   "CONFIG.DAC_Data_Width00 {8} "
                                   "CONFIG.DAC_Data_Width01 {8} "
                                   "CONFIG.DAC_Data_Width02 {8} "
                                   "CONFIG.DAC_Data_Width03 {8} "
                                   "CONFIG.DAC_Data_Width10 {8} "
                                   "CONFIG.DAC_Data_Width11 {8} "
                                   "CONFIG.DAC_Data_Width12 {8} "
                                   "CONFIG.DAC_Data_Width13 {8} "
                                   "CONFIG.DAC_Data_Width20 {8} "
                                   "CONFIG.DAC_Data_Width21 {8} "
                                   "CONFIG.DAC_Data_Width22 {8} "
                                   "CONFIG.DAC_Data_Width23 {8} "
                                   "CONFIG.DAC_Data_Width30 {8} "
                                   "CONFIG.DAC_Data_Width31 {8} "
                                   "CONFIG.DAC_Data_Width32 {8} "
                                   "CONFIG.DAC_Data_Width33 {8} "
                                   "CONFIG.DAC_Interpolation_Mode00 {6} "
                                   "CONFIG.DAC_Interpolation_Mode01 {6} "
                                   "CONFIG.DAC_Interpolation_Mode02 {6} "
                                   "CONFIG.DAC_Interpolation_Mode03 {6} "
                                   "CONFIG.DAC_Interpolation_Mode10 {6} "
                                   "CONFIG.DAC_Interpolation_Mode11 {6} "
                                   "CONFIG.DAC_Interpolation_Mode12 {6} "
                                   "CONFIG.DAC_Interpolation_Mode13 {6} "
                                   "CONFIG.DAC_Interpolation_Mode20 {6} "
                                   "CONFIG.DAC_Interpolation_Mode21 {6} "
                                   "CONFIG.DAC_Interpolation_Mode22 {6} "
                                   "CONFIG.DAC_Interpolation_Mode23 {6} "
                                   "CONFIG.DAC_Interpolation_Mode30 {6} "
                                   "CONFIG.DAC_Interpolation_Mode31 {6} "
                                   "CONFIG.DAC_Interpolation_Mode32 {6} "
                                   "CONFIG.DAC_Interpolation_Mode33 {6} "
                                   "CONFIG.DAC_Mixer_Mode00 {0} "
                                   "CONFIG.DAC_Mixer_Mode01 {0} "
                                   "CONFIG.DAC_Mixer_Mode02 {0} "
                                   "CONFIG.DAC_Mixer_Mode03 {0} "
                                   "CONFIG.DAC_Mixer_Mode10 {0} "
                                   "CONFIG.DAC_Mixer_Mode11 {0} "
                                   "CONFIG.DAC_Mixer_Mode12 {0} "
                                   "CONFIG.DAC_Mixer_Mode13 {0} "
                                   "CONFIG.DAC_Mixer_Mode20 {0} "
                                   "CONFIG.DAC_Mixer_Mode21 {0} "
                                   "CONFIG.DAC_Mixer_Mode22 {0} "
                                   "CONFIG.DAC_Mixer_Mode23 {0} "
                                   "CONFIG.DAC_Mixer_Mode30 {0} "
                                   "CONFIG.DAC_Mixer_Mode31 {0} "
                                   "CONFIG.DAC_Mixer_Mode32 {0} "
                                   "CONFIG.DAC_Mixer_Mode33 {0} "
                                   "CONFIG.DAC_Mixer_Type00 {2} "
                                   "CONFIG.DAC_Mixer_Type01 {2} "
                                   "CONFIG.DAC_Mixer_Type02 {2} "
                                   "CONFIG.DAC_Mixer_Type03 {2} "
                                   "CONFIG.DAC_Mixer_Type10 {2} "
                                   "CONFIG.DAC_Mixer_Type11 {2} "
                                   "CONFIG.DAC_Mixer_Type12 {2} "
                                   "CONFIG.DAC_Mixer_Type13 {2} "
                                   "CONFIG.DAC_Mixer_Type20 {2} "
                                   "CONFIG.DAC_Mixer_Type21 {2} "
                                   "CONFIG.DAC_Mixer_Type22 {2} "
                                   "CONFIG.DAC_Mixer_Type23 {2} "
                                   "CONFIG.DAC_Mixer_Type30 {2} "
                                   "CONFIG.DAC_Mixer_Type31 {2} "
                                   "CONFIG.DAC_Mixer_Type32 {2} "
                                   "CONFIG.DAC_Mixer_Type33 {2} "
                                   "CONFIG.DAC_Mode00 {0} "
                                   "CONFIG.DAC_Mode01 {0} "
                                   "CONFIG.DAC_Mode02 {0} "
                                   "CONFIG.DAC_Mode03 {0} "
                                   "CONFIG.DAC_Mode10 {0} "
                                   "CONFIG.DAC_Mode11 {0} "
                                   "CONFIG.DAC_Mode12 {0} "
                                   "CONFIG.DAC_Mode13 {0} "
                                   "CONFIG.DAC_Mode20 {0} "
                                   "CONFIG.DAC_Mode21 {0} "
                                   "CONFIG.DAC_Mode22 {0} "
                                   "CONFIG.DAC_Mode23 {0} "
                                   "CONFIG.DAC_Mode30 {0} "
                                   "CONFIG.DAC_Mode31 {0} "
                                   "CONFIG.DAC_Mode32 {0} "
                                   "CONFIG.DAC_Mode33 {0} "
                                   "CONFIG.DAC_NCO_RTS {true} "
                                   "CONFIG.DAC_Nyquist20 {1} "
                                   "CONFIG.DAC_Nyquist21 {1} "
                                   "CONFIG.DAC_Nyquist22 {1} "
                                   "CONFIG.DAC_Nyquist23 {1} "
                                   "CONFIG.DAC_Nyquist30 {1} "
                                   "CONFIG.DAC_Nyquist31 {1} "
                                   "CONFIG.DAC_Nyquist32 {1} "
                                   "CONFIG.DAC_Nyquist33 {1} "
                                   "CONFIG.DAC_RESERVED_1_00 {false} "
                                   "CONFIG.DAC_RESERVED_1_01 {false} "
                                   "CONFIG.DAC_RESERVED_1_02 {false} "
                                   "CONFIG.DAC_RESERVED_1_03 {false} "
                                   "CONFIG.DAC_RESERVED_1_10 {false} "
                                   "CONFIG.DAC_RESERVED_1_11 {false} "
                                   "CONFIG.DAC_RESERVED_1_12 {false} "
                                   "CONFIG.DAC_RESERVED_1_13 {false} "
                                   "CONFIG.DAC_RESERVED_1_20 {false} "
                                   "CONFIG.DAC_RESERVED_1_21 {false} "
                                   "CONFIG.DAC_RESERVED_1_22 {false} "
                                   "CONFIG.DAC_RESERVED_1_23 {false} "
                                   "CONFIG.DAC_RESERVED_1_30 {false} "
                                   "CONFIG.DAC_RESERVED_1_31 {false} "
                                   "CONFIG.DAC_RESERVED_1_32 {false} "
                                   "CONFIG.DAC_RESERVED_1_33 {false} "
                                   "CONFIG.DAC_RTS {true} "
                                   "CONFIG.DAC_Slice00_Enable {true} "
                                   "CONFIG.DAC_Slice01_Enable {true} "
                                   "CONFIG.DAC_Slice02_Enable {true} "
                                   "CONFIG.DAC_Slice03_Enable {true} "
                                   "CONFIG.DAC_Slice10_Enable {true} "
                                   "CONFIG.DAC_Slice11_Enable {true} "
                                   "CONFIG.DAC_Slice12_Enable {true} "
                                   "CONFIG.DAC_Slice13_Enable {true} "
                                   "CONFIG.DAC_Slice20_Enable {true} "
                                   "CONFIG.DAC_Slice21_Enable {true} "
                                   "CONFIG.DAC_Slice22_Enable {true} "
                                   "CONFIG.DAC_Slice23_Enable {true} "
                                   "CONFIG.DAC_Slice30_Enable {true} "
                                   "CONFIG.DAC_Slice31_Enable {true} "
                                   "CONFIG.DAC_Slice32_Enable {true} "
                                   "CONFIG.DAC_Slice33_Enable {true} "
                                   "CONFIG.DAC_TDD_RTS00 {1} "
                                   "CONFIG.DAC_TDD_RTS01 {1} "
                                   "CONFIG.DAC_TDD_RTS02 {1} "
                                   "CONFIG.DAC_TDD_RTS03 {1} "
                                   "CONFIG.DAC_TDD_RTS10 {1} "
                                   "CONFIG.DAC_TDD_RTS11 {1} "
                                   "CONFIG.DAC_TDD_RTS12 {1} "
                                   "CONFIG.DAC_TDD_RTS13 {1} "
                                   "CONFIG.DAC_TDD_RTS20 {1} "
                                   "CONFIG.DAC_TDD_RTS21 {1} "
                                   "CONFIG.DAC_TDD_RTS22 {1} "
                                   "CONFIG.DAC_TDD_RTS23 {1} "
                                   "CONFIG.DAC_TDD_RTS30 {1} "
                                   "CONFIG.DAC_TDD_RTS31 {1} "
                                   "CONFIG.DAC_TDD_RTS32 {1} "
                                   "CONFIG.DAC_TDD_RTS33 {1} "
                                   "CONFIG.DAC_VOP_RTS {true}")
            
            set_property(f, name="hedgehog/rfdc", properties=rfdc_config_string)
            
            # connect_bd_net(f, f"hedgehog/rfdc/s_axi_aclk", f"hedgehog/PS_clk_250")            
            # connect_bd_net(f, f"hedgehog/rfdc/s_axi_aresetn", f"hedgehog/proc_sys_reset_PS_clk_250/peripheral_aresetn")
            connect_bd_net(f, f"hedgehog/rfdc/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")            
            connect_bd_net(f, f"hedgehog/rfdc/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

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
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aclk", f"hedgehog/clk_wiz/{'dac_tile3_clk' if i == 3 else 'dac_clk'}")
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")        
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aclk", f"hedgehog/clk_wiz/{'adc_tile3_clk' if i == 3 else 'adc_clk'}")
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")

            # Connect RFDC to the config smartconnect and assign it address space
            connect_bd_intf_net(f, "hedgehog/config_smartconnect/M01_AXI", "hedgehog/rfdc/s_axi")
            assign_bd_address(f, "/ps/Data", "hedgehog/rfdc/s_axi/Reg", Firmware.RFDC_ADDRESS, "256K")
                
            # create_ip(f, name="hedgehog/axi_register_slice_rfdc", vlnv="xilinx.com:ip:axi_register_slice:2.1")
            # connect_bd_intf_net(f, "hedgehog/axi_register_slice_rfdc/M_AXI", "hedgehog/rfdc/s_axi")
            # connect_bd_intf_net(f, "hedgehog/axi_register_slice_rfdc/S_AXI", "hedgehog/config_smartconnect/M01_AXI")
            # connect_bd_net(f, "hedgehog/axi_register_slice_rfdc/aclk", "hedgehog/PS_clk_250")
            # connect_bd_net(f, "hedgehog/axi_register_slice_rfdc/aresetn", "hedgehog/proc_sys_reset_PS_clk_250/peripheral_aresetn")
            
            # Synchronize the SYSREF signal from the CLK104
            create_module(f, f"hedgehog/pl_sysref_capture", "acadia_sysref_capture")
            connect_bd_intf_net(f, "hedgehog/CLK104_PL_SYSREF", "hedgehog/pl_sysref_capture/sysref")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/clk", "hedgehog/clk_wiz/dac_clk")
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
            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/M02_AXI", f"hedgehog/axis_switch_adc/S_AXI_CTRL")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/s_axi_ctrl_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/s_axi_ctrl_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            assign_bd_address(f, "/ps/Data", "hedgehog/axis_switch_adc/S_AXI_CTRL/Reg", Firmware.ADC_AXIS_SWITCH_ADDRESS, "256K")

            # Connect the ADC interfaces to the AXIS switch
            for channel in range(16):
                tile = channel // 4
                block = channel % 4
                create_module(f, f"hedgehog/adc{channel}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/adc{channel}_pipeline", 
                             properties=f"WIDTH {{{128}}} "
                                        f"STAGES {{{Firmware.ADC_PIPELINE_STAGES_BEFORE_SWITCH[channel]}}}")
                connect_bd_net(f, f"hedgehog/adc{channel}_pipeline/clk", "hedgehog/clk_wiz/seq_clk")

                connect_bd_intf_net(f, f"hedgehog/rfdc/m{tile}{block}_axis", 
                                       f"hedgehog/adc{channel}_pipeline/S_AXIS")
                
                connect_bd_intf_net(f, f"hedgehog/adc{channel}_pipeline/M_AXIS", 
                                       f"hedgehog/axis_switch_adc/S{channel:02d}_AXIS")
                
            # ------------------- DAC Memory -------------------- #
            create_module(f, f"hedgehog/dac_memory", f"dac_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/dac_memory/s_axi", "hedgehog/config_smartconnect/M03_AXI")
            connect_bd_net(f, f"hedgehog/dac_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/dac_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                
            # ------------------- DAC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/dac_dma_descriptor_memory", f"dac_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi", "hedgehog/config_smartconnect/M04_AXI")
            connect_bd_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                
            # ------------------- ADC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/adc_dma_descriptor_memory", f"adc_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi", f"hedgehog/config_smartconnect/M05_AXI")
            connect_bd_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # ------------------- CMACC Kernel Memory -------------------- #
            create_module(f, f"hedgehog/cmacc_kernel_memory", f"cmacc_kernel_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/cmacc_kernel_memory/s_axi", f"hedgehog/config_smartconnect/M06_AXI")
            connect_bd_net(f, f"hedgehog/cmacc_kernel_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/cmacc_kernel_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # ------------------- CMACC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/cmacc_dma_descriptor_memory", f"cmacc_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi", f"hedgehog/config_smartconnect/M07_AXI")
            connect_bd_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # ------------------- Sequencer ----------------------------- #
            
            # Slice the PS GPIO for the sequencer run signal
            create_slice(f, name=f"hedgehog/xlslice_sequencer_run", 
                             input_width=2, 
                             input_from=0,
                             input_to=0)
            connect_bd_net(f, f"hedgehog/xlslice_sequencer_run/Din", "hedgehog/PS_GPIO_SEQUENCER")
            
            # Slice the PS GPIO for the sequencer nrst signal
            create_slice(f, name=f"hedgehog/xlslice_sequencer_nrst", 
                             input_width=2, 
                             input_from=1,
                             input_to=1)
            connect_bd_net(f, f"hedgehog/xlslice_sequencer_nrst/Din", "hedgehog/PS_GPIO_SEQUENCER")
            
            # Create synchronizers for the GPIO
            create_ip(f, name=f"hedgehog/xpm_cdc_sequencer_run", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
            set_property(f, name="hedgehog/xpm_cdc_sequencer_run", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
            connect_bd_net(f, f"hedgehog/xpm_cdc_sequencer_run/src_rst", "hedgehog/xlslice_sequencer_run/Dout")
            connect_bd_net(f, f"hedgehog/xpm_cdc_sequencer_run/dest_clk", f"hedgehog/clk_wiz/seq_clk")
            
            create_ip(f, name=f"hedgehog/xpm_cdc_sequencer_nrst", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
            set_property(f, name="hedgehog/xpm_cdc_sequencer_nrst", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
            connect_bd_net(f, f"hedgehog/xpm_cdc_sequencer_nrst/src_rst", "hedgehog/xlslice_sequencer_nrst/Dout")
            connect_bd_net(f, f"hedgehog/xpm_cdc_sequencer_nrst/dest_clk", f"hedgehog/clk_wiz/seq_clk")
            
            create_module(f, f"hedgehog/sequencer", "acadia_sequencer")
            connect_bd_net(f, "hedgehog/sequencer/clk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/sequencer/run", f"hedgehog/xpm_cdc_sequencer_run/dest_rst_out")
            connect_bd_net(f, f"hedgehog/sequencer/nrst", f"hedgehog/xpm_cdc_sequencer_nrst/dest_rst_out")

            # ------------------- Sequencer Bus and Associated Modules -------------------- #

            # Add the sequencer bus decoder and connect it to the sequencer bus
            create_module(f, f"hedgehog/sequencer_bus_decoder", "sequencer_bus_decoder")
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/master_bus", f"hedgehog/sequencer/mem_bus")

            # Create a RFDC real-time port register interface
            create_module(f, f"hedgehog/rfdc_rts_regs", "acadia_rfdc_rts_regs")
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nco_dest_clk", f"hedgehog/PS_AXI_clk")
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
            set_property(f, name=f"hedgehog/zdma_controller", properties={"NUM_DMA": 8})
            connect_bd_net(f, "hedgehog/zdma_controller/nrst", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            connect_bd_intf_net(f, "hedgehog/sequencer_bus_decoder/zdma_controller", "hedgehog/zdma_controller/master_bus")
            
            # Add all the dataports
            for module in cls.hdl_modules:
                if isinstance(module, BusDataport):
                    create_module(f, f"hedgehog/{module.name}_dataport", module.name)
                    connect_bd_intf_net(f, f"hedgehog/{module.name}_dataport/master_bus", f"hedgehog/sequencer_bus_decoder/{module.name}")
                    connect_bd_net(f, f"hedgehog/{module.name}_dataport/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                    
            # Connect the CLK104 sync pin to the dataport and to the PS GPIO through an OR gate
            # create_slice(f, name="hedgehog/xlslice_clk104_ps_gpio",
            #              input_width=Firmware.NUM_PS_GPIO, 
            #              input_from=Firmware.GPIO_CLK104_SYNC,
            #              input_to=Firmware.GPIO_CLK104_SYNC)
            # connect_bd_net(f, "hedgehog/xlslice_clk104_ps_gpio/Din", "hedgehog/PS_GPIO_OUT")
            
            # create_ip(f, name="hedgehog/clk104_sync_or", vlnv="xilinx.com:ip:util_vector_logic:2.0")
            # set_property(f, name="hedgehog/clk104_sync_or", 
            #              properties={"C_SIZE": 1, 
            #                          "C_OPERATION": "or", 
            #                          "LOGO_FILE": "data/sym_orgate.png"})
            # connect_bd_net(f, "hedgehog/clk104_sync_or/Op1", "hedgehog/xlslice_clk104_ps_gpio/Dout")
            # connect_bd_net(f, "hedgehog/clk104_sync_or/Op2", "hedgehog/clk104_sync_in_dataport/sync")
            # connect_bd_net(f, "hedgehog/clk104_sync_or/Res", "hedgehog/clk104_sync_in")

            # ------------------- Sequencer cache -------------------- #
            # Add cache memory and connect it to the sequencer bus decoder
            create_module(f, f"hedgehog/cache_memory", f"cache_axi_memory")
            
            # Connect the cache to the smartconnect
            connect_bd_intf_net(f, f"hedgehog/cache_memory/s_axi", f"hedgehog/memory_crossbar/M00_AXI")
            connect_bd_net(f, "hedgehog/cache_memory/s_axi_aclk", "hedgehog/PS_AXI_clk")
            connect_bd_net(f, "hedgehog/cache_memory/s_axi_aresetn", "hedgehog/proc_sys_reset_PS_AXI_clk/peripheral_aresetn")
            
            # Connect the cache to the sequencer bus decoder
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/cache", f"hedgehog/cache_memory/mem0")
            
            # ------------------- Sequencer Instruction Memory -------------------- #
            create_module(f, "hedgehog/instruction_memory", "instruction_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/instruction_memory/s_axi", f"hedgehog/memory_crossbar/M01_AXI")
            connect_bd_net(f, "hedgehog/instruction_memory/s_axi_aclk", "hedgehog/PS_AXI_clk")
            connect_bd_net(f, "hedgehog/instruction_memory/s_axi_aresetn", "hedgehog/proc_sys_reset_PS_AXI_clk/peripheral_aresetn")
            
            # Connect it to the sequencer
            connect_bd_intf_net(f, f"hedgehog/sequencer/instruction_mem", f"hedgehog/instruction_memory/mem0")

            # ------------------- Configuration DataMover -------------------- #
            # First, create the bus-driven DataMover Controller and connect it to the bus
            create_module(f, f"hedgehog/datamover_controller", "datamover_controller")
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/datamover_controller", f"hedgehog/datamover_controller/master_bus")
            connect_bd_net(f, f"hedgehog/datamover_controller/datamover_cmd_clk", "hedgehog/clk_wiz/seq_clk")
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

            # Connect clocks and resets for the command and status port 
            # (for some reason the clock pins are different between s2mm and mm2s,
            # otherwise we could do this in the loop below)
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_mm2s_cmdsts_aclk", "hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_mm2s_cmdsts_aresetn", "hedgehog/proc_sys_reset_PS_AXI_clk/peripheral_aresetn")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_s2mm_cmdsts_awclk", "hedgehog/PS_AXI_clk")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_s2mm_cmdsts_aresetn", "hedgehog/proc_sys_reset_PS_AXI_clk/peripheral_aresetn")

            # For this DataMover, we want to connect the MM2S and S2MM streams to each other
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/S_AXIS_S2MM", f"hedgehog/cfg_axi_dm/M_AXIS_MM2S")

            # Connect the MM2S AXI master to the bulk smartconnect
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXI_MM2S", f"hedgehog/bulk_smartconnect/S09_AXI")

            # Connect the S2MM AXI master to the memory crossbar
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXI_S2MM", f"hedgehog/memory_crossbar/S01_AXI")

            for direction in ["mm2s","s2mm"]:
                # Connect AXI Master clocks and resets
                connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axi_{direction}_aclk", "hedgehog/PS_AXI_clk")
                connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axi_{direction}_aresetn", "hedgehog/proc_sys_reset_PS_AXI_clk/peripheral_aresetn")

                # Connect the MM2S command and status interfaces to the bus-driven DataMover controller
                # Use an AXIS FIFO with independent clocks
                create_ip(f, name=f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo", vlnv="xilinx.com:ip:axis_data_fifo:2.0")
                set_property(f, name=f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo", properties={"FIFO_DEPTH": 16, "IS_ACLK_ASYNC": 1})
                connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/m_axis_aclk", f"hedgehog/PS_AXI_clk")
                connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/s_axis_aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/s_axis_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                connect_bd_intf_net(f, f"hedgehog/datamover_controller/cfg_dm_{direction}_cmd", f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/S_AXIS")
                connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/M_AXIS", f"hedgehog/cfg_axi_dm/S_AXIS_{direction.upper()}_CMD")
                
                create_ip(f, name=f"hedgehog/cfg_axi_dm_{direction}_sts_fifo", vlnv="xilinx.com:ip:axis_data_fifo:2.0")
                set_property(f, name=f"hedgehog/cfg_axi_dm_{direction}_sts_fifo", properties={"FIFO_DEPTH": 16, "IS_ACLK_ASYNC": 1})
                connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/m_axis_aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/s_axis_aclk", f"hedgehog/PS_AXI_clk")
                connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/s_axis_aresetn", f"hedgehog/proc_sys_reset_PS_AXI_clk/peripheral_aresetn")
                connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXIS_{direction.upper()}_STS", f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/S_AXIS")
                connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/M_AXIS", f"hedgehog/datamover_controller/cfg_dm_{direction}_sts")

                # Connect the error signal to the controller through a CDC
                create_ip(f, name=f"hedgehog/xpm_cdc_cfg_axi_dm_{direction}_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                set_property(f, name=f"hedgehog/xpm_cdc_cfg_axi_dm_{direction}_err", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
                connect_bd_net(f, f"hedgehog/xpm_cdc_cfg_axi_dm_{direction}_err/src_rst", f"hedgehog/cfg_axi_dm/{direction}_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_cfg_axi_dm_{direction}_err/dest_rst_out", f"hedgehog/datamover_controller/cfg_dm_{direction}_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_cfg_axi_dm_{direction}_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")

            
            # ------------------- Sequencer flags -------------------- #
            create_ip(f, name="hedgehog/xlconst_0", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name="hedgehog/xlconst_0", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
            connect_bd_net(f, f"hedgehog/sequencer/ext_in", f"hedgehog/xlconst_0/Dout")
            
            # ------------------- PS GPIO and Interrupt Connections -------------------- #
            # Create a concatenator for the PS inputs
            create_concatenator(f, "hedgehog/xlconcat_ps_gpio_in", [32, 32, Firmware.NUM_PS_GPIO % 32])
            connect_bd_net(f, "hedgehog/xlconcat_ps_gpio_in/dout", "hedgehog/PS_GPIO_IN")
            
            for idx, gpio_port in enumerate([3,4,5]):
                connect_bd_net(f, f"hedgehog/xlconcat_ps_gpio_in/In{idx}", f"hedgehog/ps_gpio{gpio_port}_dataport/gpio_in")
                
                # Slice the PS outputs
                create_slice(f, name=f"hedgehog/xlslice_ps_gpio{gpio_port}_out", 
                                 input_width=Firmware.NUM_PS_GPIO, 
                                 input_from=(Firmware.NUM_PS_GPIO-1 if gpio_port == 5 else (idx+1)*32-1),
                                 input_to=idx*32)
                connect_bd_net(f, f"hedgehog/xlslice_ps_gpio{gpio_port}_out/Din", f"hedgehog/PS_GPIO_OUT")
                connect_bd_net(f, f"hedgehog/xlslice_ps_gpio{gpio_port}_out/Dout", f"hedgehog/ps_gpio{gpio_port}_dataport/gpio_out")
                
            # IRQ signals
            for i in range(Firmware.NUM_PS_IRQ):
                connect_bd_net(f, f"hedgehog/ps_irq_dataport/irq{i}", f"hedgehog/PS_IRQ{i}")
                
            # ------------------- PS GDMA Connections -------------------- #
            connect_bd_net(f, f"hedgehog/zdma_controller/cack", f"hedgehog/ps_gdma_cack")
            connect_bd_net(f, f"hedgehog/zdma_controller/tvld", f"hedgehog/ps_gdma_tvld")
            connect_bd_net(f, f"hedgehog/zdma_controller/tack", f"hedgehog/ps_gdma_tack")
            connect_bd_net(f, f"hedgehog/zdma_controller/cvld", f"hedgehog/ps_gdma_cvld")
            connect_bd_net(f, f"hedgehog/ps_irq_dataport/gdma_irq", f"hedgehog/ps_gdma_irq")
            
            # Create a concatenator for the clock signals
            create_concatenator(f, "hedgehog/xlconcat_ps_gdma_clk", [1]*Firmware.NUM_PS_GDMA)
            connect_bd_net(f, f"hedgehog/xlconcat_ps_gdma_clk/dout", f"hedgehog/ps_gdma_clk")
            for i in range(Firmware.NUM_PS_GDMA):
                connect_bd_net(f, f"hedgehog/xlconcat_ps_gdma_clk/In{i}", f"hedgehog/clk_wiz/seq_clk")
            
            # ------------------- ADC DMAs -------------------- #

            for d in range(Firmware.NUM_ADC):

                # ------------------- Real-time DMAs -------------------- #
                create_module(f, f"hedgehog/adc_dma{d}", "acadia_dma")
                set_property(f, name=f"hedgehog/adc_dma{d}", properties={"DATA_WIDTH": 128})
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
                set_property(f, name=f"hedgehog/fifo_adc_dm{d}", properties={"WORD_WIDTH": 32,
                                                                             "INPUT_WORDS": 4,
                                                                             "OUTPUT_WORDS": 8, 
                                                                             "INPUT_DEPTH": Firmware.ADC_FIFO_DEPTH, 
                                                                             "MEMORY_TYPE": Firmware.ADC_FIFO_PRIMITIVE,
                                                                             "ASYNCHRONOUS": "false"})

                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/signal_in_clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/m_axis_aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/aux_rst", f"hedgehog/adc_fifo_control_dataport/adc_dm{d}_reset")
                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/overflow", f"hedgehog/adc_fifo_control_dataport/adc_dm{d}_overflow")
                connect_bd_net(f, f"hedgehog/fifo_adc_dm{d}/misalignment", f"hedgehog/adc_fifo_control_dataport/adc_dm{d}_misalignment")

                # Create an AXIS pipeline stage and connect it to the switch
                create_module(f, f"hedgehog/adc_dma{d}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/adc_dma{d}_pipeline", 
                             properties=f"WIDTH {{128}} "
                                        f"STAGES {{{Firmware.ADC_PIPELINE_STAGES_AFTER_SWITCH[d]}}}")
                connect_bd_net(f, f"hedgehog/adc_dma{d}_pipeline/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_intf_net(f, f"hedgehog/axis_switch_adc/M{d:02d}_AXIS", 
                                    f"hedgehog/adc_dma{d}_pipeline/S_AXIS")
                
                # Connect the DMA data input to the output of the pipeline
                connect_bd_net(f, f"hedgehog/adc_dma{d}_pipeline/m_axis_tdata", f"hedgehog/adc_dma{d}/din")
                
                # Connect the ADC DMA data output to the FIFO input
                connect_bd_intf_net(f, f"hedgehog/adc_dma{d}/DATA", f"hedgehog/fifo_adc_dm{d}/SIGNAL_IN")

                # ------------------- AXI DataMovers -------------------- #

                # Create the DataMover itself
                create_ip(f, name=f"hedgehog/adc_dm{d}", vlnv="xilinx.com:ip:axi_datamover:5.1")
                set_property(f, name=f"hedgehog/adc_dm{d}", 
                                 properties="CONFIG.c_m_axi_s2mm_data_width.VALUE_SRC USER CONFIG.c_s_axis_s2mm_tdata_width.VALUE_SRC USER")
                set_property(f, name=f"hedgehog/adc_dm{d}", 
                                 properties="CONFIG.c_include_mm2s {Omit} "
                                            "CONFIG.c_include_mm2s_stsfifo {false} "
                                            f"CONFIG.c_m_axi_s2mm_data_width {{{Firmware.ADC_DM_AXI_WIDTHS[d]}}} "
                                            f"CONFIG.c_s_axis_s2mm_tdata_width {{{Firmware.ADC_DM_AXIS_WIDTHS[d]}}} "
                                            "CONFIG.c_s2mm_btt_used {23} "
                                            f"CONFIG.c_s2mm_burst_size {{{256 if Firmware.ADC_DM_AXI_WIDTHS[d] <= 128 else 256*128//Firmware.ADC_DM_AXI_WIDTHS[d]}}} "
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

                # Connect the error signal to the controller through a CDC
                create_ip(f, name=f"hedgehog/xpm_cdc_adc_dm{d}_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                set_property(f, name=f"hedgehog/xpm_cdc_adc_dm{d}_err", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
                connect_bd_net(f, f"hedgehog/xpm_cdc_adc_dm{d}_err/src_rst", f"hedgehog/adc_dm{d}/s2mm_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_adc_dm{d}_err/dest_rst_out", f"hedgehog/datamover_controller/adc_dm{d}_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_adc_dm{d}_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")
            
                # Connect the S2MM stream input to the output of the AXIS Data FIFO
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/s_axis_s2mm", f"hedgehog/fifo_adc_dm{d}/M_AXIS")

                # Connect the DMA S2MM master to the memory smartconnect
                connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/S{d+1:02d}_AXI", f"hedgehog/adc_dm{d}/M_AXI_S2MM")

            # ------------------- Complex MACCs ------------------- #
            
            for d in range(4):

                # ------------------- The CMACC modules -------------------- #
                create_module(f, f"hedgehog/cmacc{d}", "acadia_complex_macc")
                connect_bd_net(f, f"hedgehog/cmacc{d}/clk", f"hedgehog/clk_wiz/seq_clk")
                
                # Create an AXIS pipeline stage and connect it to the switch
                create_module(f, f"hedgehog/cmacc{d}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/cmacc{d}_pipeline", 
                             properties=f"WIDTH {{32}} "
                                        f"STAGES {{{Firmware.CMACC_PIPELINE_STAGES_AFTER_SWITCH[d]}}}")
                connect_bd_net(f, f"hedgehog/cmacc{d}_pipeline/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_intf_net(f, 
                                    f"hedgehog/axis_switch_adc/M{d+Firmware.NUM_ADC:02d}_AXIS", 
                                    f"hedgehog/cmacc{d}_pipeline/S_AXIS")
                
                # Create a sample adder and connect it to the pipeline module
                create_module(f, f"hedgehog/cmacc_adder{d}", "acadia_sample_adder")
                connect_bd_net(f, f"hedgehog/clk_wiz/seq_clk", f"hedgehog/cmacc_adder{d}/clk") 
                connect_bd_net(f, f"hedgehog/cmacc{d}_pipeline/m_axis_tdata", f"hedgehog/cmacc_adder{d}/signal_in") 
                
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
                connect_bd_net(f, f"hedgehog/cmacc_status_dataport/cmacc{d}_re_msb", f"hedgehog/cmacc{d}/accumulator_re_msb")
                connect_bd_net(f, f"hedgehog/cmacc_status_dataport/cmacc{d}_im_msb", f"hedgehog/cmacc{d}/accumulator_im_msb")

                # ------------------- CMACC Real-time DMAs -------------------- #

                create_module(f, f"hedgehog/cmacc_dma{d}", "acadia_dma")
                set_property(f, name=f"hedgehog/cmacc_dma{d}", properties={"DATA_WIDTH": 32})
                connect_bd_net(f, f"hedgehog/cmacc_dma{d}/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/cmacc_dma{d}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the DMA signals to the dataports
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cmacc_dma{d}_fifo_mosi", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_in")
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cmacc_dma{d}_fifo_wr", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_wr")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/trigger")
                connect_bd_net(f, f"hedgehog/dma_running_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/running")
                connect_bd_net(f, f"hedgehog/dma_fifo_empty_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_empty")
                connect_bd_net(f, f"hedgehog/dma_fifo_almost_empty_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_almost_empty")

                # Connect the CMACC DMA to the CMACC DMA kernel memory address port
                connect_bd_intf_net(f, f"hedgehog/cmacc_dma{d}/ADDRESS", f"hedgehog/cmacc{d}/kernel_mem_addr")

                # Connect the data input and output of the CMACC DMA
                connect_bd_net(f, f"hedgehog/cmacc_adder{d}/signal_out", f"hedgehog/cmacc_dma{d}/din")
                connect_bd_intf_net(f, f"hedgehog/cmacc_dma{d}/DATA", f"hedgehog/cmacc{d}/SIGNAL_IN") 

                # Connect to descriptor memory
                connect_bd_intf_net(f, f"hedgehog/cmacc_dma{d}/descriptor_mem", f"hedgehog/cmacc_dma_descriptor_memory/mem{d}")

                # ------------------- DataMover FIFOs -------------------- #

                create_module(f, f"hedgehog/fifo_cmacc_dm{d}", "acadia_adc_fifo")
                set_property(f, f"hedgehog/fifo_cmacc_dm{d}", properties={"WORD_WIDTH": 32,
                                                                          "INPUT_WORDS": 1,
                                                                          "OUTPUT_WORDS": Firmware.CMACC_DM_AXIS_WIDTHS[d] // 32,
                                                                          "INPUT_DEPTH": Firmware.CMACC_FIFO_DEPTH,
                                                                          "MEMORY_TYPE": Firmware.CMACC_FIFO_PRIMITIVE,
                                                                          "ASYNCHRONOUS": "false"})

                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/signal_in_clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/m_axis_aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/aux_rst", f"hedgehog/adc_fifo_control_dataport/cmacc_dm{d}_reset")
                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/overflow", f"hedgehog/adc_fifo_control_dataport/cmacc_dm{d}_overflow")
                connect_bd_net(f, f"hedgehog/fifo_cmacc_dm{d}/misalignment", f"hedgehog/adc_fifo_control_dataport/cmacc_dm{d}_misalignment")

                # Connect the FIFO stream input to the CMACC signal passthrough
                connect_bd_intf_net(f, f"hedgehog/cmacc{d}/SIGNAL_OUT", f"hedgehog/fifo_cmacc_dm{d}/SIGNAL_IN")

                # ------------------- AXI DataMovers -------------------- #

                # Create the DataMover itself
                create_ip(f, name=f"hedgehog/cmacc_dm{d}", vlnv="xilinx.com:ip:axi_datamover:5.1")
                set_property(f, name=f"hedgehog/cmacc_dm{d}", properties="CONFIG.c_m_axi_s2mm_data_width.VALUE_SRC USER CONFIG.c_s_axis_s2mm_tdata_width.VALUE_SRC USER\n")
                set_property(f, name=f"hedgehog/cmacc_dm{d}", 
                                 properties="CONFIG.c_include_mm2s {Omit} "
                                            "CONFIG.c_include_mm2s_stsfifo {false} "
                                            f"CONFIG.c_m_axi_s2mm_data_width {{{Firmware.CMACC_DM_AXI_WIDTHS[d]}}} "
                                            f"CONFIG.c_s_axis_s2mm_tdata_width {{{Firmware.CMACC_DM_AXIS_WIDTHS[d]}}} "
                                            "CONFIG.c_s2mm_btt_used {23} "
                                            "CONFIG.c_s2mm_burst_size {256} "
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

                # Connect the error signal to the controller through a CDC
                create_ip(f, name=f"hedgehog/xpm_cdc_cmacc_dm{d}_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                set_property(f, name=f"hedgehog/xpm_cdc_cmacc_dm{d}_err", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
                connect_bd_net(f, f"hedgehog/xpm_cdc_cmacc_dm{d}_err/src_rst", f"hedgehog/cmacc_dm{d}/s2mm_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_cmacc_dm{d}_err/dest_rst_out", f"hedgehog/datamover_controller/cmacc_dm{d}_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_cmacc_dm{d}_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")
            
                # Connect the S2MM stream input to the output of the AXIS Data FIFO
                connect_bd_intf_net(f, f"hedgehog/cmacc_dm{d}/s_axis_s2mm", f"hedgehog/fifo_cmacc_dm{d}/M_AXIS")

                # Connect the S2MM AXI master to the memory smartconnect
                connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/S{d+5:02d}_AXI", f"hedgehog/cmacc_dm{d}/M_AXI_S2MM")

            # ------------------- DAC channels -------------------- #

            for channel in range(Firmware.NUM_DAC):
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
            
            bulk_memory_segments = {
                "HPC0_DDR_LOW": ("ps/SAXIGP0/HPC0_DDR_LOW", Firmware.HPC0_DDR_LOW_ADDRESS, "2G"),
                "HPC1_DDR_LOW": ("ps/SAXIGP1/HPC1_DDR_LOW", Firmware.HPC1_DDR_LOW_ADDRESS, "2G"),
                "HP0_DDR_LOW": ("ps/SAXIGP2/HP0_DDR_LOW", Firmware.HP0_DDR_LOW_ADDRESS, "2G"),
                "HP1_DDR_LOW": ("ps/SAXIGP3/HP1_DDR_LOW", Firmware.HP1_DDR_LOW_ADDRESS, "2G"),
                
                "HPC0_DDR_HIGH": ("ps/SAXIGP0/HPC0_DDR_HIGH", Firmware.HPC0_DDR_HIGH_ADDRESS, "32G"),
                "HPC1_DDR_HIGH": ("ps/SAXIGP1/HPC1_DDR_HIGH", Firmware.HPC1_DDR_HIGH_ADDRESS, "32G"),
                "HP0_DDR_HIGH": ("ps/SAXIGP2/HP0_DDR_HIGH", Firmware.HP0_DDR_HIGH_ADDRESS, "32G"),
                "HP1_DDR_HIGH": ("ps/SAXIGP3/HP1_DDR_HIGH", Firmware.HP1_DDR_HIGH_ADDRESS, "32G"),
                
                "HPC0_LPS_OCM": ("ps/SAXIGP0/HPC0_LPS_OCM", Firmware.HPC0_LPS_OCM_ADDRESS, "256K"),
                "HPC1_LPS_OCM": ("ps/SAXIGP1/HPC1_LPS_OCM", Firmware.HPC1_LPS_OCM_ADDRESS, "256K"),
                "HP0_LPS_OCM": ("ps/SAXIGP2/HP0_LPS_OCM", Firmware.HP0_LPS_OCM_ADDRESS, "256K"),
                "HP1_LPS_OCM": ("ps/SAXIGP3/HP1_LPS_OCM", Firmware.HP1_LPS_OCM_ADDRESS, "256K"),
                
                "DDR4_C0": ("DDR4_C0_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK", Firmware.DDR4_C0_ADDRESS, "4G"),
                "DDR4_C1": ("DDR4_C1_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK", Firmware.DDR4_C1_ADDRESS, "4G")
            }
                 
            excluded_segments = ["ps/SAXIGP0/HPC0_QSPI", "ps/SAXIGP1/HPC1_QSPI", "ps/SAXIGP2/HP0_QSPI", "ps/SAXIGP3/HP1_QSPI"]
                        
            memory_segments = {}
                
            memory_segments["cache_memory"] = ("hedgehog/cache_memory/s_axi/reg0", 
                                               Firmware.CACHE_MEMORY_ADDRESS, 
                                               Firmware.CACHE_MEMORY_SIZE_BITS // 8)
            
            memory_segments["instruction_memory"] = ("hedgehog/instruction_memory/s_axi/reg0", 
                                                     Firmware.INSTRUCTION_MEMORY_ADDRESS, 
                                                     Firmware.INSTRUCTION_MEMORY_SIZE_BITS // 8)
            
            memory_segments[f"dac_memory"] = (f"hedgehog/dac_memory/s_axi/reg0", 
                                 Firmware.DAC_MEMORY_BASE_ADDRESS, 
                                 Firmware.DAC_MEMORY_SIZE_BITS*Firmware.NUM_DAC//8)
                
            memory_segments["cmacc_kernel_memory"] = (f"hedgehog/cmacc_kernel_memory/s_axi/reg0", 
                                     Firmware.CMACC_KERNEL_MEMORY_BASE_ADDRESS, 
                                     Firmware.CMACC_KERNEL_MEMORY_SIZE_BITS*Firmware.NUM_CMACC//8)
            
            memory_segments[f"dac_dma_descriptor_memory"] = (f"hedgehog/dac_dma_descriptor_memory/s_axi/reg0", 
                                 Firmware.DAC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS, 
                                 Firmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS*Firmware.NUM_DAC//8)
                
            memory_segments["adc_dma_descriptor_memory"] = (f"hedgehog/adc_dma_descriptor_memory/s_axi/reg0", 
                                     Firmware.ADC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS, 
                                     Firmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS*Firmware.NUM_ADC//8)
            
            memory_segments[f"cmacc_dma_descriptor_memory"] = (f"hedgehog/cmacc_dma_descriptor_memory/s_axi/reg0", 
                                     Firmware.CMACC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS, 
                                     Firmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS*Firmware.NUM_CMACC//8)

            for target_address_space in ["/ps/Data", "hedgehog/cfg_axi_dm/Data_S2MM"]:
                for segment,address,rng in memory_segments.values():
                    assign_bd_address(f, target_address_space=target_address_space, offset=address, range=rng, addr_seg=segment)
                    
            bulk_address_spaces = ["/ps/Data", "hedgehog/cfg_axi_dm/Data_MM2S"]
            bulk_address_spaces += [f"/hedgehog/adc_dm{i}/Data_S2MM" for i in range(Firmware.NUM_ADC)]
            bulk_address_spaces += [f"/hedgehog/cmacc_dm{i}/Data_S2MM" for i in range(Firmware.NUM_CMACC)]
            for target_address_space in bulk_address_spaces:
                for segment,address,rng in bulk_memory_segments.values():
                    if "SAXIGP" in segment and "/ps" in target_address_space:
                        # Don't map the PS memory into itself
                        exclude_bd_addr_seg(f, addr_seg=segment, target_address_space=target_address_space)
                    else:
                        assign_bd_address(f, target_address_space=target_address_space, offset=address, range=rng, addr_seg=segment)
                for segment in excluded_segments:
                    exclude_bd_addr_seg(f, addr_seg=segment, target_address_space=target_address_space)

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
            rts_address = Firmware.rfdc_rts_regs.address().value()

            # If any DMAs were triggered, add instructions to do so now
            if dma_mask != 0:
                if self._dma_trigger:
                    # The only parent object that we could have had was an Acadia object,
                    # so we know on which object we should call dma_trigger
                    dma_trigger_device = Firmware.sequencer_bus_decoder["dma_trigger"]
                    proc.bus_write(address=dma_trigger_device.address().value(),
                                   data=dma_mask,
                                   comment="Trigger DMAs")

                if self._dma_block:
                    # Wait until all the DMAs in the mask have completed
                    dma_running_device = Firmware.sequencer_bus_decoder["dma_running"]
                    with proc.wait_until(proc.bus_read(dma_running_device.address().value()) & dma_mask == 0):
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
    
    def __init__(self):        
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
        self.synchronizer = ChannelSynchronizer(allow_standalone=True)
                
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
            zdma_self.fci_bus_address = Firmware.sequencer_bus_decoder["zdma_controller"].address().value()
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
            address=Firmware.INSTRUCTION_MEMORY_ADDRESS,
            size=Firmware.INSTRUCTION_MEMORY_SIZE_BITS // 8)  
        
        self._dac_dma_descriptor_memory = [self._attach_memory(
            address=(Firmware.DAC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS 
                    + i*(Firmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8)),
            size=Firmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8,
            mem_cast=np.uint64) for i in range(16)]
                
        self._adc_dma_descriptor_memory = [self._attach_memory(
            address=(Firmware.ADC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS 
                    + i*(Firmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8)),
            size=Firmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8,
            mem_cast=np.uint64) for i in range(4)]
        
        self._cmacc_dma_descriptor_memory = [self._attach_memory(
            address=(Firmware.CMACC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS 
                    + i*(Firmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8)),
            size=Firmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS // 8,
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
        
        RFClk.init(338 + 3*26 + Firmware.GPIO_CLK104_SPI0)
        
        # Connect to the ADC AXIS switch
        self._ADC_AXIS_switch.attach(self._attach_memory(
            address=Firmware.ADC_AXIS_SWITCH_ADDRESS, 
            size=0x1000))
        
        # Connect to the PS GDMA
        for instance in self._ZDMA.instances:
            instance.attach(self._attach_memory(
                address=0xFD50_0000 + (instance._resource_id*0x1_0000),
                size=0x1_0000))
            
        # Connect to the GPIO registers and store sequencer bus addresses for the GPIO dataports
        self._psgpio_mem = self._attach_memory(0xFF0A0000, 0x400, mem_cast=np.uint32)

        # Connect to the clock wizard
        self.clk_wiz = self._attach_memory(address=Firmware.CLK_WIZ_ADDRESS, size=2**18)  
            
        # Configure and connect to the sysfs interface for various GPIO        
        self._sequencer_gpio = 338 + 3*26 + Firmware.GPIO_SEQUENCER_RUN
        PSGPIO.sysfs_export(self._sequencer_gpio)
        PSGPIO.sysfs_set_direction(self._sequencer_gpio, "out")
        PSGPIO.sysfs_write(self._sequencer_gpio, 0)
        
        self._sequencer_nrst = 338 + 3*26 + Firmware.GPIO_SEQUENCER_NRST
        PSGPIO.sysfs_export(self._sequencer_nrst)
        PSGPIO.sysfs_set_direction(self._sequencer_nrst, "out")
        PSGPIO.sysfs_write(self._sequencer_nrst, 0)

        self._ddr4_c0_sys_rst_gpio = 338 + 3*26 + Firmware.GPIO_DDR4_C0_SYS_RST            
        PSGPIO.sysfs_export(self._ddr4_c0_sys_rst_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c0_sys_rst_gpio, "out")
        PSGPIO.sysfs_write(self._ddr4_c0_sys_rst_gpio, 0)

        self._ddr4_c1_sys_rst_gpio = 338 + 3*26 + Firmware.GPIO_DDR4_C1_SYS_RST            
        PSGPIO.sysfs_export(self._ddr4_c1_sys_rst_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c1_sys_rst_gpio, "out")
        PSGPIO.sysfs_write(self._ddr4_c1_sys_rst_gpio, 0)

        self._ddr4_c0_cal_cplt_gpio = 338 + 3*26 + Firmware.GPIO_DDR4_C0_CAL_CPLT           
        PSGPIO.sysfs_export(self._ddr4_c0_cal_cplt_gpio)
        PSGPIO.sysfs_set_direction(self._ddr4_c0_cal_cplt_gpio, "in")

        self._ddr4_c1_cal_cplt_gpio = 338 + 3*26 + Firmware.GPIO_DDR4_C1_CAL_CPLT           
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
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{address + Firmware.INSTRUCTION_MEMORY_ADDRESS : X}, 16, 128'h{assembled:032X}, resp);\n"
        
        if dac_dmas:
            for i,dma in enumerate(self._dac_dmas):
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{Firmware.DAC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS + i*(Firmware.DAC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
                
        if adc_dmas:
            for dma in self._ADCDMA.instances:
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{Firmware.ADC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS + dma._resource_id*(Firmware.ADC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
        
        if cmacc_dmas:
            for i,dma in self._CMACCDMA.instances:
                for idx_instr,instr in enumerate(dma._compiled_program):
                    assembled = instr.assemble()
                    sim_string += f"acadia_tb.uut.ps.inst.write_data(32'h{Firmware.CMACC_DMA_DESCRIPTOR_MEMORY_BASE_ADDRESS + dma._resource_id*(Firmware.CMACC_DMA_DESCRIPTOR_MEMORY_SIZE_BITS//8) + idx_instr*8: X}, 8, 64'h{assembled:016X}, resp);\n"
                    
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
            frequency_base_reg = Firmware.rfdc_rts_regs.address().value() + channel.num*2
            
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
            phase_reg = Firmware.rfdc_rts_regs.address().value() + 0x40 + channel.num
            
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
            
        d["clk_wiz_locked"] = self.clk_wiz[4] == 1
        d["clk_wiz_divclk_divide"] = self.clk_wiz[0x200]
        d["clk_wiz_fbout_mult"] = self.clk_wiz[0x201]
        d["clk_wiz_fbout_frac"] = int.from_bytes(self.clk_wiz[0x203:0x202], 'little') & (2**10 - 1)
        d["clk_wiz_vco_frequency_over_input_frequency"] = (d["clk_wiz_fbout_mult"] + 1e-3*d["clk_wiz_fbout_frac"]) / d["clk_wiz_divclk_divide"]
        
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
                    with proc.wait_until(proc.bus_read(Firmware.sequencer_bus_decoder["datamover_controller"]["cfg_dm_s2mm"]+1) != 0):
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
                    
                    if array._args[1].stop is not None:
                        if array._args[1].start is not None:
                            capture_length = array._args[1].stop - array._args[1].start
                            capture_address = array._args[0].byte_address() + array._args[1].start
                        else:
                            capture_length = array._args[1].stop
                            capture_address = array._args[0].byte_address()
                    else:
                        if array._args[1].start is not None:
                            capture_length = array._args[0].byte_length() - array._args[1].start
                            capture_address = array._args[0].byte_address() + array._args[1].start
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
            capture_address = array.byte_address() + offset if offset is not None else array.byte_address()
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
                if integration_kernel.byte_length() // 4 != (capture_length // 16):
                    raise ValueError(f"Integration kernel length"
                                    f" ({integration_kernel.byte_length() // 4})"
                                    f" does not match array length ({capture_length // 16}).")
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
            capture_length_cycles = capture_length // 4
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
            capture_length_cycles = capture_length // 16
            
        # Store a reference to the DMA chosen in the Channel object
        channel.dma = dma
        
        # Add the descriptor address to the FIFO for the DMA
        descriptor = dma.request_descriptor(dma_address, capture_length_cycles)
        fifo_bus_address = Firmware.sequencer_bus_decoder[fifo_name].address().value()
        self._active_sequencer.bus_write(address=fifo_bus_address,
                                         data=descriptor,
                                         comment=f"Add descriptor with parameters"
                                                f" {descriptor.kwargs} to DMA FIFO for ADC"
                                                f" switch output {dma._resource_id}"
                                                f" (connected to ADC{channel.num})")
        
        # Configure the DataMover
        self._sequencer_command_dm(datamover_name, capture_address, capture_length, tag=datamover_tag)
    
    @Synchronizer.synchronized(ChannelSynchronizer.STREAM, "synchronizer")
    @requires_sequencer
    def generate(self, channel, array, decimate=0, blank=False):
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
                                            array.byte_length() // 16,
                                            decimate=decimate, blank=blank)
        
        fifo_device = Firmware.sequencer_bus_decoder[f"dac_dma{channel.num}_fifo"]
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
        :param length: The length of the signal in units of cycles. 
        :type length: int or Symbol
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
                descriptor = dma.request_descriptor(0, length, fixed=True, blank=True)
            else:
                mem = self.DACArray[channel.num](size=16)
                self._dac_constants.append((mem,value))
                descriptor = dma.request_descriptor(mem.word_address(), length, fixed=True)
        elif isinstance(value, Symbol) and value.value_type() in [int, float, complex]:
            mem = self.DACArray[channel.num](size=16)
            self._dac_constants.append((mem,value))
            descriptor = dma.request_descriptor(mem.word_address(), length, fixed=True)
        else:
            raise TypeError("Symbolic constants must be of type `int`,"
                             f" `float`, `complex`, or a `Symbol` with a value"
                             f" type of one of these (received {value}).")
        
        fifo_device = Firmware.sequencer_bus_decoder[f"dac_dma{channel.num}_fifo"]
        return self._active_sequencer.bus_write(address=fifo_device.address().value(),
                                         data=descriptor, 
                                         comment=f"Add descriptor with parameters {descriptor.kwargs} to FIFO for DAC{channel.num}")

    # -------------- CONVENIENCE FUNCTIONS FOR THE SEQUENCER ----------- #

    @requires_sequencer
    def channels_almost_done(self, *channels):
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
        bus_address = Firmware.dma_fifo_almost_empty.address().value()
        return self._active_sequencer.bus_read(bus_address) & mask != 0
    
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
        
        bus_address = Firmware.dma_running.address().value()
        return self._active_sequencer.bus_read(bus_address) & mask != 0

    @requires_sequencer
    def captures_complete(self, *channels):
        """
        Create a condition that will determine whether the datamover 
        transferring captured ADC samples is complete. This check is performed
        by inspecting whether a valid status was provided by the DataMover
        corresponding to that channel and does not examine the status itself.

        :param channels: Channel(s) to check
        :type channels: list of :class:`Channel`
        """

        mask = 0
        for channel in channels:
            dma = channel.dma
            mask |= 1 << ((4 if isinstance(dma, self._CMACCDMA) else 0) + dma._resource_id)
        bus_address = Firmware.datamover_controller.address().value() + 1
        return self._active_sequencer.bus_read(bus_address) & mask != 0
    
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

        address = Firmware.sequencer_bus_decoder["datamover_controller"][datamover_name]
        self._active_sequencer.bus_read(address, 
                                        comment=f"Writing bus address register to"
                                                f" retrieve status for {datamover_name}")
        self._active_sequencer.nop(comment="Pipeline latency for DataMover status")
        self._active_sequencer.nop(comment="Pipeline latency for DataMover status")
        self._active_sequencer.nop(comment="Pipeline latency for DataMover status")
        return self._active_sequencer.bus_read(write_address=False)
    
    @requires_sequencer
    def fifo_error_status(self):
        """
        Return a sequencer Source for checking the error status of the
        ADC FIFOs.
        """

        address = Firmware.sequencer_bus_decoder["adc_fifo_control"].address().value()
        return self._active_sequencer.bus_read(address=address)

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

        
        self._active_sequencer.bus_write(address=Firmware.sequencer_bus_decoder["adc_fifo_control"].address().value(), 
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
            seq.bus_write(address=Firmware.sequencer_bus_decoder["datamover_controller"].address().value() + 3, 
                          data=mask)
            
    @requires_sequencer
    def dma_trigger(self, mask):
        """
        Triggers the DMAs according to a provided bitmask.
        """

        dma_trigger_device = Firmware.sequencer_bus_decoder["dma_trigger"]
        self._active_sequencer.bus_write(address=dma_trigger_device.address().value(),
                                 data=mask,
                                 comment="DMA trigger")
        
    @requires_sequencer
    def dma_block(self, mask):
        """
        Wait until the DMAs specified in the mask are not running.
        """

        dma_running_device = Firmware.sequencer_bus_decoder["dma_running"]
        dma_running = self._active_sequencer.bus_read(dma_running_device.address().value())
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
        # The DAC interface width is 128 bits, which is 4 complex samples
        for mem,constant in self._dac_constants:
            mem.memory[:] = Channel.to_samples(np.array([constant]*4))

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
            addr = Firmware.sequencer_bus_decoder[f"ps_gpio{port}"].address().value()
            return proc.bus_read(addr)
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
            addr = Firmware.sequencer_bus_decoder[f"ps_gpio{port}"].address().value()
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
                return proc.bus_read(cache_self.word_address() + key)
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
            base_word_address=Firmware.sequencer_bus_decoder["cache"].address().value(),
            base_byte_address=Firmware.CACHE_MEMORY_ADDRESS,
            word_width=32,
            memory_size=Firmware.CACHE_MEMORY_SIZE_BITS // 8,
            default_getitem=False)
        
    def _create_dac_arrays(self):
        self.DACArray = [ManagedMemory(f"DAC{i}Array", (), {"channel": self.DAC(i)},
            base_word_address=0,
            base_byte_address=(Firmware.DAC_MEMORY_BASE_ADDRESS 
                               + i*(Firmware.DAC_MEMORY_SIZE_BITS // 8)),
            word_width=128,
            memory_size=Firmware.DAC_MEMORY_SIZE_BITS // 8) for i in range(16)]
        
        # In addition to the arrays themselves, store an internal reference
        # to constants that will be loaded into memory when the program is configured
        self._dac_constants = []
        
    def _create_cmacc_kernel_arrays(self):
        self.CMACCKernelArray = [ManagedMemory(f"CMACCKernel{i}Array", (), {},
            base_word_address=0,
            base_byte_address=(Firmware.CMACC_KERNEL_MEMORY_BASE_ADDRESS 
                               + i*(Firmware.CMACC_KERNEL_MEMORY_SIZE_BITS // 8)),
            word_width=32,
            memory_size=Firmware.CMACC_KERNEL_MEMORY_SIZE_BITS // 8) for i in range(4)]
        
    def _create_pl_ddr_arrays(self):
        self.PLDDR0Array = ManagedMemory(f"PLDDR0Array", (), {},
            base_word_address=Firmware.DDR4_C0_ADDRESS,
            base_byte_address=Firmware.DDR4_C0_ADDRESS,
            word_width=8,
            memory_size=2**32)
        
        self.PLDDR1Array = ManagedMemory(f"PLDDR1Array", (), {},
            base_word_address=Firmware.DDR4_C1_ADDRESS,
            base_byte_address=Firmware.DDR4_C1_ADDRESS,
            word_width=8,
            memory_size=2**32)
        
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
        
        return np.frombuffer(m, dtype=np.uint8).view(mem_cast)

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
        :param incr: If ``True``\, the AXI transaction is in INCR mode.
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
        bus_address_base = Firmware.sequencer_bus_decoder["datamover_controller"][datamover_name]
        self._active_sequencer.bus_write(address=bus_address_base+2, 
                                         data=misc_reg,
                                         comment=f"Configuration for {size}-byte transfer"
                                                 f" to {address:010X} using DataMover"
                                                 f" {datamover_name}")
        self._active_sequencer.bus_write(address=bus_address_base+1, 
                            data=size)
        self._active_sequencer.bus_write(address=bus_address_base, 
                            data=addr_reg)
        