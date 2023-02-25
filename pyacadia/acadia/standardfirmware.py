__all__ = ["StandardFirmware"]

import os
from dataclasses import dataclass

from .hdl import BusDevice, BusDecoder, BusDataport, BusDataMoverController
from .compiler import ManagedResource, ManagedMemory, Processor
from .firmware import Firmware
from .hardware import LinuxMemory
from .pythonprocessor import PythonProcessor
from .sequencer import Sequencer
from .dma import DMA
from .utils import connect_bd_net, connect_bd_intf_net, create_ip, create_module, create_concatenator, create_slice, set_property, assign_bd_address, exclude_bd_addr_seg, next_highest_power_of_2

class StandardFirmware(Firmware):
    # Designate some addresses for memory slave segments
    # HPC0_QSPI_ADDR = 0x00_C000_0000
    HPC0_LPS_OCM_ADDR = 0x00_FF00_0000

    # HPC1_QSPI_ADDR = 0x01_C000_0000
    HPC1_LPS_OCM_ADDR = 0x01_FF00_0000

    # HP0_QSPI_ADDR = 0x02_C000_0000
    HP0_LPS_OCM_ADDR = 0x02_FF00_0000

    # HP1_QSPI_ADDR = 0x3C_C000_0000
    HP1_LPS_OCM_ADDR = 0x03_FF00_0000
    
    HPC0_DDR_LOW_ADDR = 0x04_0000_0000
    HPC1_DDR_LOW_ADDR = 0x05_0000_0000
    HP0_DDR_LOW_ADDR = 0x06_0000_0000
    HP1_DDR_LOW_ADDR = 0x07_0000_0000
    
    HPC0_DDR_HIGH_ADDR = 0x08_0000_0000
    HPC1_DDR_HIGH_ADDR = 0x18_0000_0000
    HP0_DDR_HIGH_ADDR = 0x28_0000_0000
    HP1_DDR_HIGH_ADDR = 0x38_0000_0000
    
    DDR4_C0_ADDR = 0x40_0000_0000
    DDR4_C1_ADDR = 0x41_0000_0000

    # We"ll manually choose addresses for the AXI HPM1 interface since there are particular alignment requirements
    RFDC_ADDR = 0x00_B000_0000
    CLK_WIZ_ADDR = 0x00_B004_0000
    BRAM_CTRL_MEM_DECODER_ADDR = 0x00_B020_0000
    BRAM_CTRL_DAC_MEM_DECODER_ADDR = 0x00_B040_0000
    BRAM_CTRL_CACHE_ADDR = 0x00_B060_0000
    ADC_AXIS_SWITCH_ADDR = 0x00_B080_0000

    # The sizes of various memories
    CACHE_SIZE_BITS = 2**20
    CMACC_KERNEL_MEM_SIZE_BITS = 2048*128
    DAC_DMA_DESCRIPTOR_MEM_SIZE_BITS = 256*64
    ADC_DMA_DESCRIPTOR_MEM_SIZE_BITS = 256*64
    CMACC_DMA_DESCRIPTOR_MEM_SIZE_BITS = 256*64
    INSTRUCTION_MEM_SIZE_BITS = 128*4096
    DAC_MEM_SIZE_BITS = 128*8192
    ADC_AXIS_FIFO_DEPTH = 256
    CMACC_AXIS_FIFO_DEPTH = 256
    
    NUM_DAC = 16
    NUM_ADC = 4
    NUM_CMACC = 4
    NUM_PS_GPIO = 91
    NUM_PS_IRQ = 2
    NUM_PS_GDMA = 8
    
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
        
        ps_gdma_dataports = []
        ps_gdma_dataports += [{"name": f"cvld",
                                   "direction": BusDataport.OUTPUT,
                                   "offset": 0,
                                   "width": StandardFirmware.NUM_PS_GDMA,
                                   "gate": BusDataport.GATE_REGCE,
                                   "pipeline": 2}]
        ps_gdma_dataports += [{"name": f"tack",
                                   "direction": BusDataport.OUTPUT,
                                   "offset": StandardFirmware.NUM_PS_GDMA,
                                   "width": StandardFirmware.NUM_PS_GDMA,
                                   "gate": BusDataport.GATE_REGCE,
                                   "pipeline": 2}]
        ps_gdma_dataports += [{"name": f"cack",
                                   "direction": BusDataport.INPUT,
                                   "offset": 0,
                                   "width": StandardFirmware.NUM_PS_GDMA,
                                   "pipeline": 2}]
        ps_gdma_dataports += [{"name": f"tvld",
                                   "direction": BusDataport.INPUT,
                                   "offset": StandardFirmware.NUM_PS_GDMA,
                                   "width": StandardFirmware.NUM_PS_GDMA,
                                   "pipeline": 2}]
        ps_gdma = BusDataport(name="ps_gdma", ports=ps_gdma_dataports)
        sequencer_bus_decoder.add(ps_gdma)
        self.add(ps_gdma)    

        # Create a register file for RFDC real-time updates and connect it to the sequencer bus
        rfdc_rts_regs = BusDevice("rfdc_rts_regs", size=256)
        sequencer_bus_decoder.add(rfdc_rts_regs, pipeline=True)
        
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
        cache = BusDevice("cache", size=StandardFirmware.CACHE_SIZE_BITS // 32)
        sequencer_bus_decoder.add(cache)

        datamover_controller = BusDataMoverController("datamover_controller", 
                                                      [f"adc_dm{i}" for i in range(4)] + 
                                                      [f"cmacc_dm{i}" for i in range(4)] + 
                                                      ["cfg_dm_mm2s", "cfg_dm_s2mm"], addr_bits=40)
        sequencer_bus_decoder.add(datamover_controller)
        self.add(datamover_controller)

        # Create a memory bus decoder for the AXI BRAM controller driven by the PS master
        # It will be able to write into the instruction memory, the cache, MACC memory, and the DMA descriptors
        # It has a base address corresponding to the AXI address of the BRAM controller so that the 
        # resulting Symbol addresses correspond to AXI addresses of the various memories
        # However, we can"t use just the normal base AXI address - we need to chop off some low bits, since
        # AXI uses bytewise addressing and all the memories use wordwise addressing
        # The global AXI address is then recovered by just shifting the result back the other way
        mem_decoder = BusDecoder("mem_decoder", bus_data_bits=128, pipeline_miso=True, byte_write=True)
        self.add(mem_decoder)

        for i in range(4):
            mem_decoder.add(BusDevice(f"cmacc{i}_kernel_mem", size=StandardFirmware.CMACC_KERNEL_MEM_SIZE_BITS // 128, bus_data_bits=128), pipeline=True)

        for i in range(16):
            mem_decoder.add(BusDevice(f"dac_dma{i}_descriptor_mem", size=StandardFirmware.DAC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 128, bus_data_bits=128), pipeline=True)

        for i in range(4):
            mem_decoder.add(BusDevice(f"adc_dma{i}_descriptor_mem", size=StandardFirmware.ADC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 128, bus_data_bits=128), pipeline=True)

        for i in range(4):
            mem_decoder.add(BusDevice(f"cmacc_dma{i}_descriptor_mem", size=StandardFirmware.CMACC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 128, bus_data_bits=128), pipeline=True)

        instruction_mem = BusDevice("instruction_mem", size=StandardFirmware.INSTRUCTION_MEM_SIZE_BITS // 128, bus_data_bits=128)
        mem_decoder.add(instruction_mem, pipeline=True)

        # Use a separate decoder for DAC wave memory so that it can be synchronous to the sequencer when using ultraram
        # It will have a base address of the AXI BRAM controller, so that the resulting Symbols
        # will correspond to the AXI addresses of the individual DAC memories
        dac_mem_decoder = BusDecoder("dac_mem_decoder", bus_data_bits=128, pipeline_miso=True)
        self.add(dac_mem_decoder)
        
        for i in range(16):
            dac_mem_decoder.add(BusDevice(f"dac_dma{i}_mem", size=StandardFirmware.DAC_MEM_SIZE_BITS // 128, bus_data_bits=128), pipeline=True)
        
        # Assign decoder addresses
        sequencer_bus_decoder.assign_address(0)
        mem_decoder.assign_address(StandardFirmware.BRAM_CTRL_MEM_DECODER_ADDR // (128 // 8))
        dac_mem_decoder.assign_address(StandardFirmware.BRAM_CTRL_DAC_MEM_DECODER_ADDR // (128 // 8))
            
    def write_hedgehog_tcl(self, filename="hedgehog.tcl"):
        """
        Write a TCL script to populate the HEDGEHOG logic in the standard image. 
        """
        super().write_hedgehog_tcl(filename)
        
        with open(self._hedgehog_tcl_filename, "a") as f:

            # ------------------- Design Initialization -------------------- #  

            # Create a couple of constants that we"ll use a few times
            create_ip(f, name="hedgehog/xlconst_1", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name="hedgehog/xlconst_1", properties={"CONST_WIDTH": 1, "CONST_VAL": 1})
            
            create_ip(f, name="hedgehog/xlconst_0", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name="hedgehog/xlconst_0", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
            
            create_ip(f, name="hedgehog/xlconst_FFFF", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name="hedgehog/xlconst_FFFF", properties={"CONST_WIDTH": 16, "CONST_VAL": 0xFFFF})

            # ------------------- RF Data Converters -------------------- #

            create_ip(f, name="hedgehog/rfdc", vlnv="xilinx.com:ip:usp_rf_data_converter:2.4")
            
            # Auto-generated config string by Vivado
            rfdc_config_string = "CONFIG.ADC0_Clock_Source {6} CONFIG.ADC0_Fabric_Freq {300.000} CONFIG.ADC0_Outclk_Freq {150.000} CONFIG.ADC0_PLL_Enable {true} CONFIG.ADC0_Refclk_Freq {300.000} CONFIG.ADC0_Sampling_Rate {1.2} CONFIG.ADC1_Clock_Source {6} CONFIG.ADC1_Enable {1} CONFIG.ADC1_Fabric_Freq {300.000} CONFIG.ADC1_Outclk_Freq {300.000} CONFIG.ADC1_PLL_Enable {true} CONFIG.ADC1_Refclk_Freq {300.000} CONFIG.ADC1_Sampling_Rate {2.4} CONFIG.ADC2_Clock_Dist {0} CONFIG.ADC2_Clock_Source {6} CONFIG.ADC2_Enable {1} CONFIG.ADC2_Fabric_Freq {300.000} CONFIG.ADC2_Outclk_Freq {300.000} CONFIG.ADC2_PLL_Enable {true} CONFIG.ADC2_Refclk_Freq {300.000} CONFIG.ADC2_Sampling_Rate {2.4} CONFIG.ADC3_Clock_Source {6} CONFIG.ADC3_Enable {1} CONFIG.ADC3_Fabric_Freq {30.000} CONFIG.ADC3_Outclk_Freq {300.000} CONFIG.ADC3_PLL_Enable {true} CONFIG.ADC3_Refclk_Freq {300.000} CONFIG.ADC3_Sampling_Rate {2.4} CONFIG.ADC_Coarse_Mixer_Freq00 {0} CONFIG.ADC_Coarse_Mixer_Freq01 {0} CONFIG.ADC_Coarse_Mixer_Freq02 {0} CONFIG.ADC_Coarse_Mixer_Freq03 {0} CONFIG.ADC_Coarse_Mixer_Freq10 {0} CONFIG.ADC_Coarse_Mixer_Freq11 {0} CONFIG.ADC_Coarse_Mixer_Freq12 {0} CONFIG.ADC_Coarse_Mixer_Freq13 {0} CONFIG.ADC_Coarse_Mixer_Freq20 {0} CONFIG.ADC_Coarse_Mixer_Freq21 {0} CONFIG.ADC_Coarse_Mixer_Freq22 {0} CONFIG.ADC_Coarse_Mixer_Freq23 {0} CONFIG.ADC_Coarse_Mixer_Freq30 {0} CONFIG.ADC_Coarse_Mixer_Freq31 {0} CONFIG.ADC_Coarse_Mixer_Freq32 {0} CONFIG.ADC_Coarse_Mixer_Freq33 {0} CONFIG.ADC_DSA_RTS {false} CONFIG.ADC_Data_Type00 {1} CONFIG.ADC_Data_Type01 {1} CONFIG.ADC_Data_Type02 {1} CONFIG.ADC_Data_Type03 {1} CONFIG.ADC_Data_Type10 {1} CONFIG.ADC_Data_Type11 {1} CONFIG.ADC_Data_Type12 {1} CONFIG.ADC_Data_Type13 {1} CONFIG.ADC_Data_Type20 {1} CONFIG.ADC_Data_Type21 {1} CONFIG.ADC_Data_Type22 {1} CONFIG.ADC_Data_Type23 {1} CONFIG.ADC_Data_Type30 {1} CONFIG.ADC_Data_Type31 {1} CONFIG.ADC_Data_Type32 {1} CONFIG.ADC_Data_Type33 {1} CONFIG.ADC_Data_Width00 {8} CONFIG.ADC_Decimation_Mode01 {1} CONFIG.ADC_Decimation_Mode02 {1} CONFIG.ADC_Decimation_Mode03 {1} CONFIG.ADC_Decimation_Mode10 {2} CONFIG.ADC_Decimation_Mode11 {2} CONFIG.ADC_Decimation_Mode12 {2} CONFIG.ADC_Decimation_Mode13 {2} CONFIG.ADC_Decimation_Mode20 {2} CONFIG.ADC_Decimation_Mode21 {2} CONFIG.ADC_Decimation_Mode22 {2} CONFIG.ADC_Decimation_Mode23 {2} CONFIG.ADC_Decimation_Mode30 {20} CONFIG.ADC_Decimation_Mode31 {20} CONFIG.ADC_Decimation_Mode32 {20} CONFIG.ADC_Decimation_Mode33 {20} CONFIG.ADC_Dither00 {false} CONFIG.ADC_Dither01 {false} CONFIG.ADC_Dither02 {false} CONFIG.ADC_Dither03 {false} CONFIG.ADC_Dither10 {false} CONFIG.ADC_Dither11 {false} CONFIG.ADC_Dither12 {false} CONFIG.ADC_Dither13 {false} CONFIG.ADC_Dither20 {false} CONFIG.ADC_Dither21 {false} CONFIG.ADC_Dither22 {false} CONFIG.ADC_Dither23 {false} CONFIG.ADC_Dither30 {false} CONFIG.ADC_Dither31 {false} CONFIG.ADC_Dither32 {false} CONFIG.ADC_Dither33 {false} CONFIG.ADC_Mixer_Mode00 {0} CONFIG.ADC_Mixer_Mode01 {0} CONFIG.ADC_Mixer_Mode02 {0} CONFIG.ADC_Mixer_Mode03 {0} CONFIG.ADC_Mixer_Mode10 {0} CONFIG.ADC_Mixer_Mode11 {0} CONFIG.ADC_Mixer_Mode12 {0} CONFIG.ADC_Mixer_Mode13 {0} CONFIG.ADC_Mixer_Mode20 {0} CONFIG.ADC_Mixer_Mode21 {0} CONFIG.ADC_Mixer_Mode22 {0} CONFIG.ADC_Mixer_Mode23 {0} CONFIG.ADC_Mixer_Mode30 {0} CONFIG.ADC_Mixer_Mode31 {0} CONFIG.ADC_Mixer_Mode32 {0} CONFIG.ADC_Mixer_Mode33 {0} CONFIG.ADC_Mixer_Type00 {2} CONFIG.ADC_Mixer_Type01 {2} CONFIG.ADC_Mixer_Type02 {2} CONFIG.ADC_Mixer_Type03 {2} CONFIG.ADC_Mixer_Type10 {2} CONFIG.ADC_Mixer_Type11 {2} CONFIG.ADC_Mixer_Type12 {2} CONFIG.ADC_Mixer_Type13 {2} CONFIG.ADC_Mixer_Type20 {2} CONFIG.ADC_Mixer_Type21 {2} CONFIG.ADC_Mixer_Type22 {2} CONFIG.ADC_Mixer_Type23 {2} CONFIG.ADC_Mixer_Type30 {2} CONFIG.ADC_Mixer_Type31 {2} CONFIG.ADC_Mixer_Type32 {2} CONFIG.ADC_Mixer_Type33 {2} CONFIG.ADC_NCO_RTS {true} CONFIG.ADC_OBS03 {false} CONFIG.ADC_OBS11 {false} CONFIG.ADC_OBS12 {false} CONFIG.ADC_OBS13 {false} CONFIG.ADC_OBS21 {false} CONFIG.ADC_OBS22 {false} CONFIG.ADC_OBS23 {false} CONFIG.ADC_OBS31 {false} CONFIG.ADC_OBS32 {false} CONFIG.ADC_OBS33 {false} CONFIG.ADC_RESERVED_1_00 {false} CONFIG.ADC_RESERVED_1_01 {false} CONFIG.ADC_RESERVED_1_02 {false} CONFIG.ADC_RESERVED_1_03 {false} CONFIG.ADC_RESERVED_1_10 {false} CONFIG.ADC_RESERVED_1_11 {false} CONFIG.ADC_RESERVED_1_12 {false} CONFIG.ADC_RESERVED_1_13 {false} CONFIG.ADC_RESERVED_1_20 {false} CONFIG.ADC_RESERVED_1_21 {false} CONFIG.ADC_RESERVED_1_22 {false} CONFIG.ADC_RESERVED_1_23 {false} CONFIG.ADC_RESERVED_1_30 {false} CONFIG.ADC_RESERVED_1_31 {false} CONFIG.ADC_RESERVED_1_32 {false} CONFIG.ADC_RESERVED_1_33 {false} CONFIG.ADC_RTS {false} CONFIG.ADC_Slice01_Enable {true} CONFIG.ADC_Slice02_Enable {true} CONFIG.ADC_Slice03_Enable {true} CONFIG.ADC_Slice10_Enable {true} CONFIG.ADC_Slice11_Enable {true} CONFIG.ADC_Slice12_Enable {true} CONFIG.ADC_Slice13_Enable {true} CONFIG.ADC_Slice20_Enable {true} CONFIG.ADC_Slice21_Enable {true} CONFIG.ADC_Slice22_Enable {true} CONFIG.ADC_Slice23_Enable {true} CONFIG.ADC_Slice30_Enable {true} CONFIG.ADC_Slice31_Enable {true} CONFIG.ADC_Slice32_Enable {true} CONFIG.ADC_Slice33_Enable {true} CONFIG.Axiclk_Freq {250} CONFIG.DAC0_Clock_Source {6} CONFIG.DAC0_Enable {1} CONFIG.DAC0_Fabric_Freq {300.000} CONFIG.DAC0_Outclk_Freq {300.000} CONFIG.DAC0_PLL_Enable {true} CONFIG.DAC0_Refclk_Freq {300.000} CONFIG.DAC0_Sampling_Rate {4.8} CONFIG.DAC1_Clock_Source {6} CONFIG.DAC1_Enable {1} CONFIG.DAC1_Fabric_Freq {300.000} CONFIG.DAC1_Outclk_Freq {300.000} CONFIG.DAC1_PLL_Enable {true} CONFIG.DAC1_Refclk_Freq {300.000} CONFIG.DAC1_Sampling_Rate {4.8} CONFIG.DAC2_Clock_Dist {1} CONFIG.DAC2_Enable {1} CONFIG.DAC2_Fabric_Freq {300.000} CONFIG.DAC2_Outclk_Freq {300.000} CONFIG.DAC2_PLL_Enable {true} CONFIG.DAC2_Refclk_Freq {300.000} CONFIG.DAC2_Sampling_Rate {9.6} CONFIG.DAC2_VOP {40.0} CONFIG.DAC3_Clock_Source {6} CONFIG.DAC3_Enable {1} CONFIG.DAC3_Fabric_Freq {300.000} CONFIG.DAC3_Outclk_Freq {300.000} CONFIG.DAC3_PLL_Enable {true} CONFIG.DAC3_Refclk_Freq {300.000} CONFIG.DAC3_Sampling_Rate {9.6} CONFIG.DAC3_VOP {40.0} CONFIG.DAC_Coarse_Mixer_Freq00 {3} CONFIG.DAC_Coarse_Mixer_Freq01 {3} CONFIG.DAC_Coarse_Mixer_Freq02 {3} CONFIG.DAC_Coarse_Mixer_Freq03 {3} CONFIG.DAC_Coarse_Mixer_Freq10 {3} CONFIG.DAC_Coarse_Mixer_Freq11 {3} CONFIG.DAC_Coarse_Mixer_Freq12 {3} CONFIG.DAC_Coarse_Mixer_Freq13 {3} CONFIG.DAC_Coarse_Mixer_Freq20 {3} CONFIG.DAC_Coarse_Mixer_Freq21 {3} CONFIG.DAC_Coarse_Mixer_Freq22 {3} CONFIG.DAC_Coarse_Mixer_Freq23 {3} CONFIG.DAC_Coarse_Mixer_Freq30 {3} CONFIG.DAC_Coarse_Mixer_Freq31 {3} CONFIG.DAC_Coarse_Mixer_Freq32 {3} CONFIG.DAC_Coarse_Mixer_Freq33 {3} CONFIG.DAC_Data_Width00 {8} CONFIG.DAC_Data_Width01 {8} CONFIG.DAC_Data_Width02 {8} CONFIG.DAC_Data_Width03 {8} CONFIG.DAC_Data_Width10 {8} CONFIG.DAC_Data_Width11 {8} CONFIG.DAC_Data_Width12 {8} CONFIG.DAC_Data_Width13 {8} CONFIG.DAC_Data_Width20 {8} CONFIG.DAC_Data_Width21 {8} CONFIG.DAC_Data_Width22 {8} CONFIG.DAC_Data_Width23 {8} CONFIG.DAC_Data_Width30 {8} CONFIG.DAC_Data_Width31 {8} CONFIG.DAC_Data_Width32 {8} CONFIG.DAC_Data_Width33 {8} CONFIG.DAC_Interpolation_Mode00 {4} CONFIG.DAC_Interpolation_Mode01 {4} CONFIG.DAC_Interpolation_Mode02 {4} CONFIG.DAC_Interpolation_Mode03 {4} CONFIG.DAC_Interpolation_Mode10 {4} CONFIG.DAC_Interpolation_Mode11 {4} CONFIG.DAC_Interpolation_Mode12 {4} CONFIG.DAC_Interpolation_Mode13 {4} CONFIG.DAC_Interpolation_Mode20 {4} CONFIG.DAC_Interpolation_Mode21 {4} CONFIG.DAC_Interpolation_Mode22 {4} CONFIG.DAC_Interpolation_Mode23 {4} CONFIG.DAC_Interpolation_Mode30 {4} CONFIG.DAC_Interpolation_Mode31 {4} CONFIG.DAC_Interpolation_Mode32 {4} CONFIG.DAC_Interpolation_Mode33 {4} CONFIG.DAC_Mixer_Mode00 {0} CONFIG.DAC_Mixer_Mode01 {0} CONFIG.DAC_Mixer_Mode02 {0} CONFIG.DAC_Mixer_Mode03 {0} CONFIG.DAC_Mixer_Mode10 {0} CONFIG.DAC_Mixer_Mode11 {0} CONFIG.DAC_Mixer_Mode12 {0} CONFIG.DAC_Mixer_Mode13 {0} CONFIG.DAC_Mixer_Mode20 {0} CONFIG.DAC_Mixer_Mode21 {0} CONFIG.DAC_Mixer_Mode22 {0} CONFIG.DAC_Mixer_Mode23 {0} CONFIG.DAC_Mixer_Mode30 {0} CONFIG.DAC_Mixer_Mode31 {0} CONFIG.DAC_Mixer_Mode32 {0} CONFIG.DAC_Mixer_Mode33 {0} CONFIG.DAC_Mixer_Type00 {2} CONFIG.DAC_Mixer_Type01 {2} CONFIG.DAC_Mixer_Type02 {2} CONFIG.DAC_Mixer_Type03 {2} CONFIG.DAC_Mixer_Type10 {2} CONFIG.DAC_Mixer_Type11 {2} CONFIG.DAC_Mixer_Type12 {2} CONFIG.DAC_Mixer_Type13 {2} CONFIG.DAC_Mixer_Type20 {2} CONFIG.DAC_Mixer_Type21 {2} CONFIG.DAC_Mixer_Type22 {2} CONFIG.DAC_Mixer_Type23 {2} CONFIG.DAC_Mixer_Type30 {2} CONFIG.DAC_Mixer_Type31 {2} CONFIG.DAC_Mixer_Type32 {2} CONFIG.DAC_Mixer_Type33 {2} CONFIG.DAC_Mode00 {0} CONFIG.DAC_Mode01 {0} CONFIG.DAC_Mode02 {0} CONFIG.DAC_Mode03 {0} CONFIG.DAC_Mode10 {0} CONFIG.DAC_Mode11 {0} CONFIG.DAC_Mode12 {0} CONFIG.DAC_Mode13 {0} CONFIG.DAC_Mode20 {1} CONFIG.DAC_Mode21 {1} CONFIG.DAC_Mode22 {1} CONFIG.DAC_Mode23 {1} CONFIG.DAC_Mode30 {1} CONFIG.DAC_Mode31 {1} CONFIG.DAC_Mode32 {1} CONFIG.DAC_Mode33 {1} CONFIG.DAC_NCO_RTS {true} CONFIG.DAC_Nyquist20 {1} CONFIG.DAC_Nyquist21 {1} CONFIG.DAC_Nyquist22 {1} CONFIG.DAC_Nyquist23 {1} CONFIG.DAC_Nyquist30 {1} CONFIG.DAC_Nyquist31 {1} CONFIG.DAC_Nyquist32 {1} CONFIG.DAC_Nyquist33 {1} CONFIG.DAC_RESERVED_1_00 {false} CONFIG.DAC_RESERVED_1_01 {false} CONFIG.DAC_RESERVED_1_02 {false} CONFIG.DAC_RESERVED_1_03 {false} CONFIG.DAC_RESERVED_1_10 {false} CONFIG.DAC_RESERVED_1_11 {false} CONFIG.DAC_RESERVED_1_12 {false} CONFIG.DAC_RESERVED_1_13 {false} CONFIG.DAC_RESERVED_1_20 {false} CONFIG.DAC_RESERVED_1_21 {false} CONFIG.DAC_RESERVED_1_22 {false} CONFIG.DAC_RESERVED_1_23 {false} CONFIG.DAC_RESERVED_1_30 {false} CONFIG.DAC_RESERVED_1_31 {false} CONFIG.DAC_RESERVED_1_32 {false} CONFIG.DAC_RESERVED_1_33 {false} CONFIG.DAC_RTS {false} CONFIG.DAC_Slice00_Enable {true} CONFIG.DAC_Slice01_Enable {true} CONFIG.DAC_Slice02_Enable {true} CONFIG.DAC_Slice03_Enable {true} CONFIG.DAC_Slice10_Enable {true} CONFIG.DAC_Slice11_Enable {true} CONFIG.DAC_Slice12_Enable {true} CONFIG.DAC_Slice13_Enable {true} CONFIG.DAC_Slice20_Enable {true} CONFIG.DAC_Slice21_Enable {true} CONFIG.DAC_Slice22_Enable {true} CONFIG.DAC_Slice23_Enable {true} CONFIG.DAC_Slice30_Enable {true} CONFIG.DAC_Slice31_Enable {true} CONFIG.DAC_Slice32_Enable {true} CONFIG.DAC_Slice33_Enable {true} CONFIG.DAC_VOP_RTS {false} CONFIG.ADC0_Multi_Tile_Sync {true} CONFIG.DAC0_Multi_Tile_Sync {true} CONFIG.DAC_TDD_RTS00 {1} CONFIG.DAC_TDD_RTS01 {1} CONFIG.DAC_TDD_RTS02 {1} CONFIG.DAC_TDD_RTS03 {1} CONFIG.DAC1_Multi_Tile_Sync {true} CONFIG.DAC_TDD_RTS10 {1} CONFIG.DAC_TDD_RTS11 {1} CONFIG.DAC_TDD_RTS12 {1} CONFIG.DAC_TDD_RTS13 {1} CONFIG.DAC2_Multi_Tile_Sync {true} CONFIG.DAC_TDD_RTS20 {1} CONFIG.DAC_TDD_RTS21 {1} CONFIG.DAC_TDD_RTS22 {1} CONFIG.DAC_TDD_RTS23 {1} CONFIG.DAC3_Multi_Tile_Sync {true} CONFIG.DAC_TDD_RTS30 {1} CONFIG.DAC_TDD_RTS31 {1} CONFIG.DAC_TDD_RTS32 {1} CONFIG.DAC_TDD_RTS33 {1} CONFIG.ADC_RTS {true} CONFIG.DAC_RTS {true} CONFIG.DAC_VOP_RTS {true} CONFIG.ADC_DSA_RTS {true}"
            
            set_property(f, name="hedgehog/rfdc", properties=rfdc_config_string)

            # Connect the analog inputs and outputs to the external ports through the hedgehog logic boundary
            for d in ["out", "in"]:
                for tile in range(4):
                    for block in range(4):
                        connect_bd_intf_net(f, f"hedgehog/rfdc/v{d}{tile}{block}", f"hedgehog/v{d}{tile}{block}")

            # connect_bd_intf_net(f, f"hedgehog/rfdc/adc2_clk", f"hedgehog/adc2_clk")
            connect_bd_intf_net(f, f"hedgehog/rfdc/dac2_clk", f"hedgehog/dac2_clk")
            connect_bd_intf_net(f, f"hedgehog/rfdc/sysref_in", f"hedgehog/sysref_in")

            connect_bd_net(f, f"hedgehog/rfdc/s_axi_aclk", f"hedgehog/PS_clk_250")

            # Add a synchronous reset synchronizer for the AXI lite interface
            create_ip(f, name=f"hedgehog/xpm_cdc_rfdc_s_axi_aresetn", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
            set_property(f, name="hedgehog/xpm_cdc_rfdc_s_axi_aresetn", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
            connect_bd_net(f, f"hedgehog/rfdc/s_axi_aresetn", f"hedgehog/xpm_cdc_rfdc_s_axi_aresetn/dest_rst_out")
            connect_bd_net(f, f"hedgehog/PS_resetn", f"hedgehog/xpm_cdc_rfdc_s_axi_aresetn/src_rst")
            connect_bd_net(f, f"hedgehog/PS_clk_250", f"hedgehog/xpm_cdc_rfdc_s_axi_aresetn/dest_clk")

            # ------------------- Clock Management -------------------- #

            # The RFDAC fabric clocks are at 300 MHz. 
            # The PL clock from the CLK104 is brought in through an HDIO bank, so we need to buffer
            # it with an IBUFDS before feeding it to the MMCM
            # we would technically neet to put in another constraint for the CMT column 
            # (see https://support.xilinx.com/s/question/0D52E00006lLh0DSAS/place-30716-clock-input-driving-mmcmpll-in-hdio-bank-with-bufgce?language=en_US)
            # but we'll see if the clocking wizard does this and applies the correct constraints for us
            # Update: it seems to not, we'll insert our own BUFG and apply the constraint
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
                                        "CONFIG.CLK_OUT1_PORT {clk_300} "
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

            # Connect the clock for the AXI lite interface to the PS clock
            connect_bd_net(f, f"hedgehog/PS_clk_250", f"hedgehog/clk_wiz/s_axi_aclk")

            # Add a synchronous reset synchronizer for the AXI lite interface
            create_ip(f, name="hedgehog/xpm_cdc_aresetn_PS_clk_250", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
            set_property(f, name="hedgehog/xpm_cdc_aresetn_PS_clk_250", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
            connect_bd_net(f, f"hedgehog/clk_wiz/s_axi_aresetn", f"hedgehog/xpm_cdc_aresetn_PS_clk_250/dest_rst_out")
            connect_bd_net(f, f"hedgehog/PS_resetn", f"hedgehog/xpm_cdc_aresetn_PS_clk_250/src_rst")
            connect_bd_net(f, f"hedgehog/PS_clk_250", f"hedgehog/xpm_cdc_aresetn_PS_clk_250/dest_clk")

            # Connect the buffer output to the clock wizard and apply a constraint
            connect_bd_net(f, f"hedgehog/pl_clk_bufg/BUFG_O", f"hedgehog/clk_wiz/clk_in1")
            self._hedgehog_constraints.append("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets acadia_bd_i/hedgehog/pl_clk_bufg_BUFG_O]")
            self._hedgehog_constraints.append("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets acadia_bd_i/hedgehog/clk_wiz/inst/CLK_CORE_DRP_I/clk_inst/clk_in1_acadia_bd_clk_wiz_0]")
            
            f.write("set_property -dict [list CONFIG.FREQ_HZ {300000000}] [get_bd_intf_ports CLK104_PL_CLK]\n")

            # Expose the locked signal to external modules
            connect_bd_net(f, f"hedgehog/clk_locked", f"hedgehog/clk_wiz/locked")

            # Connect the sequencer clock
            connect_bd_net(f, f"hedgehog/seq_clk", f"hedgehog/clk_wiz/clk_300")

            # Connect the RFDC stream clocks and resets
            for i in range(4):
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aclk", f"hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")        
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aclk", f"hedgehog/clk_wiz/clk_{30 if i == 3 else 300}")
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")
                
            # Synchronize the SYSREF signal from the CLK104
            create_module(f, f"hedgehog/pl_sysref_capture", "acadia_sysref_capture")
            connect_bd_intf_net(f, "hedgehog/CLK104_PL_SYSREF", "hedgehog/pl_sysref_capture/sysref")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/clk", "hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/sysref_out", "hedgehog/rfdc/user_sysref_dac")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/sysref_out", "hedgehog/rfdc/user_sysref_adc")
            
            # ------------------- SmartConnects -------------------- #

            # Create a SmartConnect for non-critical transfers
            # 2 Masters: PS AXI Master 1, CFG AXI DataMover S2MM
            # 6 Slaves: RFDC, Clocking, BRAM controller for DMA/instructions, BRAM controller for DAC wave memory, BRAM controller for cache, ADC Axis Switch
            create_ip(f, name="hedgehog/config_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, name="hedgehog/config_smartconnect", properties={"NUM_MI": 6, "NUM_SI": 2, "NUM_CLKS": 2})
            connect_bd_net(f, f"hedgehog/config_smartconnect/aclk", f"hedgehog/PS_clk_250")
            connect_bd_net(f, f"hedgehog/config_smartconnect/aclk1", f"hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/config_smartconnect/aresetn", f"hedgehog/PS_resetn")

            # Connect RFDC to the smartconnect through an AXI register slice and assign address space
            create_ip(f, name="hedgehog/axi_register_slice_rfdc", vlnv="xilinx.com:ip:axi_register_slice:2.1")
            connect_bd_intf_net(f, "hedgehog/axi_register_slice_rfdc/M_AXI", "hedgehog/rfdc/s_axi")
            connect_bd_intf_net(f, "hedgehog/axi_register_slice_rfdc/S_AXI", "hedgehog/config_smartconnect/M00_AXI")
            connect_bd_net(f, "hedgehog/axi_register_slice_rfdc/aclk", "hedgehog/PS_clk_250")
            connect_bd_net(f, "hedgehog/axi_register_slice_rfdc/aresetn", "hedgehog/xpm_cdc_rfdc_s_axi_aresetn/dest_rst_out")
            assign_bd_address(f, target_address_space="/ps/Data", addr_seg="hedgehog/rfdc/s_axi/Reg", offset=StandardFirmware.RFDC_ADDR, range="256K")

            # Connect the clock wizard to the smartconnect and assign it some address space
            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/M01_AXI", f"hedgehog/clk_wiz/s_axi_lite")
            assign_bd_address(f, target_address_space="/ps/Data", addr_seg="hedgehog/clk_wiz/s_axi_lite/Reg", offset=StandardFirmware.CLK_WIZ_ADDR, range="256K")

            # Create a SmartConnect for high-performance transfers
            # 10 Masters: PS AXI Master 0, ADC AXI DataMover 0-3 S2MM, CMACC Signal AXI DataMover 0-3 S2MM, CFG AXI DataMover MM2S
            # 6 Slaves: PS AXI Slave HPC0, PS AXI Slave HPC1, PS AXI Slave HP0, PS AXI Slave HP1, PL DDR C0, PL DDR C1
            create_ip(f, name="hedgehog/memory_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, name="hedgehog/memory_smartconnect", properties={"NUM_MI": 6, "NUM_SI": 10, "NUM_CLKS": 3})
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk", f"hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk1", f"hedgehog/DDR4_C0_ui_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk2", f"hedgehog/DDR4_C1_ui_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aresetn", f"hedgehog/seq_interconnect_aresetn")

            # ------------------- PS AXI Connections -------------------- #

            # Connect the PS AXI ports and associated clocks
            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/S00_AXI", f"hedgehog/PS_M_AXI0")
            connect_bd_net(f, f"hedgehog/PS_M_AXI1_aclk", f"hedgehog/clk_wiz/clk_300")

            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/S00_AXI", f"hedgehog/PS_M_AXI1")
            connect_bd_net(f, f"hedgehog/PS_M_AXI0_aclk", f"hedgehog/clk_wiz/clk_300")

            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M00_AXI", f"hedgehog/PS_S_AXI_HPC0")
            connect_bd_net(f, f"hedgehog/PS_S_AXI_HPC0_aclk", f"hedgehog/clk_wiz/clk_300")

            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M01_AXI", f"hedgehog/PS_S_AXI_HPC1")
            connect_bd_net(f, f"hedgehog/PS_S_AXI_HPC1_aclk", f"hedgehog/clk_wiz/clk_300")

            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M02_AXI", f"hedgehog/PS_S_AXI_HP0")
            connect_bd_net(f, f"hedgehog/PS_S_AXI_HP0_aclk", f"hedgehog/clk_wiz/clk_300")

            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M03_AXI", f"hedgehog/PS_S_AXI_HP1")
            connect_bd_net(f, f"hedgehog/PS_S_AXI_HP1_aclk", f"hedgehog/clk_wiz/clk_300")

            # Because of the SmartConnect topology, there"s a path from the PS masters to the PS slaves. Exclude these addresses
            for idx,port in enumerate(["HPC0", "HPC1", "HP0", "HP1"]):
                for seg in ["DDR_HIGH", "DDR_LOW", "LPS_OCM", "QSPI"]:
                    exclude_bd_addr_seg(f, addr_seg=f"ps/SAXIGP{idx}/{port}_{seg}", target_address_space="ps/Data")
                    
            # ------------------- DDR4 Connections -------------------- #

            connect_bd_intf_net(f, f"hedgehog/DDR4_C0_S_AXI", f"hedgehog/memory_smartconnect/M04_AXI")
            assign_bd_address(f, target_address_space="/ps/Data", offset=StandardFirmware.DDR4_C0_ADDR, range="4G", addr_seg="DDR4_C0_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK")

            connect_bd_intf_net(f, f"hedgehog/DDR4_C1_S_AXI", f"hedgehog/memory_smartconnect/M05_AXI")
            assign_bd_address(f, target_address_space="/ps/Data", offset=StandardFirmware.DDR4_C1_ADDR, range="4G", addr_seg="DDR4_C1_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK")

            # ------------------- Sequencer Bus and Associated Modules -------------------- #

            # Add the sequencer bus decoder and connect it to the sequencer bus
            create_module(f, f"hedgehog/sequencer_bus_decoder", "sequencer_bus_decoder")
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/master_bus", f"hedgehog/sequencer_bus")

            # Create a RFDC real-time port register interface
            create_module(f, f"hedgehog/rfdc_rts_regs", "acadia_rfdc_rts_regs")
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nco_dest_clk", f"hedgehog/PS_clk_250")
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nrst", f"hedgehog/seq_peripheral_aresetn")
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

            # Add all the dataports
            for module in self._modules:
                if isinstance(module, BusDataport):
                    create_module(f, f"hedgehog/{module.name}_dataport", module.name)
                    connect_bd_intf_net(f, f"hedgehog/{module.name}_dataport/master_bus", f"hedgehog/sequencer_bus_decoder/{module.name}")
                    connect_bd_net(f, f"hedgehog/{module.name}_dataport/nrst", f"hedgehog/seq_peripheral_aresetn")
                    
            # Connect the CLK104 sync pin
            connect_bd_net(f, "hedgehog/clk104_sync_in_dataport/sync", "hedgehog/clk104_sync_in")
                    
            # --------------------- PS Memory Loading ----------------------- #
                                        
            # Add the memory decoder for cache and instructions and its AXI BRAM controller
            create_module(f, f"hedgehog/mem_decoder", "mem_decoder")
            create_ip(f, name=f"hedgehog/axi_bram_ctrl_mem_decoder", vlnv="xilinx.com:ip:axi_bram_ctrl:4.1")
            set_property(f, name=f"hedgehog/axi_bram_ctrl_mem_decoder", properties={"SUPPORTS_NARROW_BURST.VALUE_SRC": "USER"})
            set_property(f, name=f"hedgehog/axi_bram_ctrl_mem_decoder", properties={"DATA_WIDTH": 128, "SINGLE_PORT_BRAM": 1, "SUPPORTS_NARROW_BURST": 1, "ECC_TYPE": 0, "READ_LATENCY": 5})
            connect_bd_net(f, f"hedgehog/axi_bram_ctrl_mem_decoder/s_axi_aclk", f"hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/axi_bram_ctrl_mem_decoder/s_axi_aresetn", f"hedgehog/seq_peripheral_aresetn")

            # Connect the memory decoder to the BRAM controller through an address slicer 
            # (to account for the fact that, for some reason, the AXI bram controller uses byte addressing on the BRAM slave port)
            create_module(f, f"hedgehog/axi_bram_ctrl_mem_decoder_addr_slice", "acadia_axi_bram_ctrl_addr_slice")
            connect_bd_intf_net(f, f"hedgehog/axi_bram_ctrl_mem_decoder/BRAM_PORTA", f"hedgehog/axi_bram_ctrl_mem_decoder_addr_slice/BRAM_CTRL")
            connect_bd_intf_net(f, f"hedgehog/axi_bram_ctrl_mem_decoder_addr_slice/SLAVE", f"hedgehog/mem_decoder/master_bus")

            # Connect the memory decoder AXI BRAM controller to the config SmartConnect and assign address space; also configure the address slicer
            connect_bd_intf_net(f, f"hedgehog/axi_bram_ctrl_mem_decoder/S_AXI", f"hedgehog/config_smartconnect/M02_AXI")
            set_property(f, name=f"hedgehog/axi_bram_ctrl_mem_decoder_addr_slice", properties={"DATA_WIDTH": 128, "LOG2_DATA_WIDTH_BYTES": 4, "LOG2_SLAVE_SIZE_BYTES": next_highest_power_of_2(self["mem_decoder"].words(bus_data_bits=8), log=True)})
            assign_bd_address(f, addr_seg=f"hedgehog/axi_bram_ctrl_mem_decoder/S_AXI/Mem0", target_address_space="/ps/Data", offset=StandardFirmware.BRAM_CTRL_MEM_DECODER_ADDR, range=next_highest_power_of_2(self["mem_decoder"].words(bus_data_bits=8)))

            # Add the DAC memory decoder for the PS master and its AXI BRAM controller
            create_module(f, f"hedgehog/dac_mem_decoder", "dac_mem_decoder")
            create_module(f, f"hedgehog/axi_bram_ctrl_dac_mem_decoder_addr_slice", "acadia_axi_bram_ctrl_addr_slice")
            create_ip(f, name=f"hedgehog/axi_bram_ctrl_dac_mem_decoder", vlnv="xilinx.com:ip:axi_bram_ctrl:4.1")
            set_property(f, name=f"hedgehog/axi_bram_ctrl_dac_mem_decoder", properties={"SUPPORTS_NARROW_BURST.VALUE_SRC": "USER"})
            set_property(f, name=f"hedgehog/axi_bram_ctrl_dac_mem_decoder", properties={"DATA_WIDTH": 128, "SINGLE_PORT_BRAM": 1, "SUPPORTS_NARROW_BURST": 1, "ECC_TYPE": 0, "READ_LATENCY": 5})

            # Because the DAC memory is ultraram, it needs to be synchronous to the sequencer clock
            connect_bd_net(f, f"hedgehog/axi_bram_ctrl_dac_mem_decoder/s_axi_aclk", f"hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/axi_bram_ctrl_dac_mem_decoder/s_axi_aresetn", f"hedgehog/seq_peripheral_aresetn")
            connect_bd_intf_net(f, f"hedgehog/axi_bram_ctrl_dac_mem_decoder/BRAM_PORTA", f"hedgehog/axi_bram_ctrl_dac_mem_decoder_addr_slice/BRAM_CTRL")
            connect_bd_intf_net(f, f"hedgehog/axi_bram_ctrl_dac_mem_decoder_addr_slice/SLAVE", f"hedgehog/dac_mem_decoder/master_bus")

            # Connect the DAC memory decoder to the config smartconnect and assign it address space
            connect_bd_intf_net(f, f"hedgehog/axi_bram_ctrl_dac_mem_decoder/S_AXI", f"hedgehog/config_smartconnect/M03_AXI")
            set_property(f, name=f"hedgehog/axi_bram_ctrl_dac_mem_decoder_addr_slice", properties={"DATA_WIDTH": 128, "LOG2_DATA_WIDTH_BYTES": 4, "LOG2_SLAVE_SIZE_BYTES": next_highest_power_of_2(self["dac_mem_decoder"].words(bus_data_bits=8), log=True)})
            assign_bd_address(f, addr_seg=f"hedgehog/axi_bram_ctrl_dac_mem_decoder/S_AXI/Mem0", target_address_space="/ps/Data", offset=StandardFirmware.BRAM_CTRL_DAC_MEM_DECODER_ADDR, range=next_highest_power_of_2(self["dac_mem_decoder"].words(bus_data_bits=8)))

             # ------------------- Sequencer cache -------------------- #

            # Add cache memory and connect it to the sequencer bus decoder
            create_ip(f, name="hedgehog/cache_mem", vlnv="xilinx.com:ip:blk_mem_gen:8.4")
            set_property(f, name="hedgehog/cache_mem",                  
                            properties=f"CONFIG.Memory_Type {{True_Dual_Port_RAM}} "
                                        f"CONFIG.Enable_32bit_Address {{false}} "
                                        f"CONFIG.Use_Byte_Write_Enable {{true}} "
                                        f"CONFIG.Byte_Size {{8}} "
                                        f"CONFIG.Assume_Synchronous_Clk {{true}} "
                                        f"CONFIG.Write_Width_A {{128}} "
                                        f"CONFIG.Write_Depth_A {{{StandardFirmware.CACHE_SIZE_BITS // 128}}} "
                                        f"CONFIG.Read_Width_A {{128}} "
                                        f"CONFIG.Enable_A {{Always_Enabled}} "
                                        f"CONFIG.Write_Width_B {{32}} "
                                        f"CONFIG.Read_Width_B {{32}} "
                                        f"CONFIG.Enable_B {{Always_Enabled}} "
                                        f"CONFIG.Register_PortA_Output_of_Memory_Primitives {{true}} "
                                        f"CONFIG.Register_PortA_Output_of_Memory_Core {{true}} "
                                        f"CONFIG.Register_PortB_Output_of_Memory_Primitives {{false}} "
                                        f"CONFIG.Register_PortB_Output_of_Memory_Core {{true}} "
                                        f"CONFIG.Use_RSTA_Pin {{false}} "
                                        f"CONFIG.Use_RSTB_Pin {{false}} "
                                        f"CONFIG.Use_REGCEA_Pin {{false}} "
                                        f"CONFIG.Port_B_Clock {{100}} "
                                        f"CONFIG.Port_B_Write_Rate {{50}} "
                                        f"CONFIG.Port_B_Enable_Rate {{100}} "
                                        f"CONFIG.use_bram_block {{Stand_Alone}} "
                                        f"CONFIG.EN_SAFETY_CKT {{true}}")
            
            # Connect the cache to the sequencer bus decoder
            # we need to manually connect the interface signals so that we can broadcast the
            # write signals across all the bits of the byte write
            connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cache_clk", f"hedgehog/cache_mem/clkb")
            connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cache_miso", f"hedgehog/cache_mem/doutb")
            connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cache_mosi", f"hedgehog/cache_mem/dinb")
            connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cache_addr", f"hedgehog/cache_mem/addrb")
            
            create_concatenator(f, "hedgehog/xlconcat_cache_we", [1]*4)
            connect_bd_net(f, f"hedgehog/xlconcat_cache_we/dout", f"hedgehog/cache_mem/web")
            for i in range(4):
                connect_bd_net(f, f"hedgehog/xlconcat_cache_we/In{i}", f"hedgehog/sequencer_bus_decoder/cache_wr")
            
            # Create an AXI BRAM controller for the cache
            create_ip(f, name="hedgehog/axi_bram_ctrl_cache", vlnv="xilinx.com:ip:axi_bram_ctrl:4.1")
            set_property(f, name=f"hedgehog/axi_bram_ctrl_cache", properties={"DATA_WIDTH": 128, "SINGLE_PORT_BRAM": 1, "ECC_TYPE": 0, "READ_LATENCY": 3})
            connect_bd_net(f, f"hedgehog/axi_bram_ctrl_cache/s_axi_aclk", f"hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/axi_bram_ctrl_cache/s_axi_aresetn", f"hedgehog/seq_peripheral_aresetn")

            # Connect the cache to the BRAM controller through a slice
            create_module(f, f"hedgehog/axi_bram_cache_ctrl_addr_slice", "acadia_axi_bram_ctrl_addr_slice")
            connect_bd_intf_net(f, f"hedgehog/axi_bram_ctrl_cache/BRAM_PORTA", f"hedgehog/axi_bram_cache_ctrl_addr_slice/BRAM_CTRL")
            connect_bd_intf_net(f, f"hedgehog/axi_bram_cache_ctrl_addr_slice/SLAVE", f"hedgehog/cache_mem/BRAM_PORTA")

            # Connect the cache BRAM controller to the smartconnect and assign it address space
            connect_bd_intf_net(f, f"hedgehog/axi_bram_ctrl_cache/S_AXI", f"hedgehog/config_smartconnect/M04_AXI")
            set_property(f, name=f"hedgehog/axi_bram_cache_ctrl_addr_slice", properties={"DATA_WIDTH": 128, "LOG2_DATA_WIDTH_BYTES": 4, "LOG2_SLAVE_SIZE_BYTES": next_highest_power_of_2(StandardFirmware.CACHE_SIZE_BITS // 8, log=True)})
            assign_bd_address(f, addr_seg="hedgehog/axi_bram_ctrl_cache/S_AXI/Mem0", target_address_space="/ps/Data", offset=StandardFirmware.BRAM_CTRL_CACHE_ADDR, range=next_highest_power_of_2(StandardFirmware.CACHE_SIZE_BITS // 8))

             # ------------------- Sequencer Instruction Memory -------------------- #

            # Create instruction memory for the sequencer and add it to the memory decoder
            create_ip(f, name="hedgehog/instruction_mem", vlnv="xilinx.com:ip:blk_mem_gen:8.4")
            set_property(f, name="hedgehog/instruction_mem", 
                         properties=f"CONFIG.Memory_Type {{True_Dual_Port_RAM}} "
                                    f"CONFIG.Enable_32bit_Address {{false}} "
                                    f"CONFIG.Use_Byte_Write_Enable {{true}} "
                                    f"CONFIG.Byte_Size {{8}} "
                                    f"CONFIG.Assume_Synchronous_Clk {{true}} "
                                    f"CONFIG.Write_Width_A {{128}} "
                                    f"CONFIG.Write_Depth_A {{{StandardFirmware.INSTRUCTION_MEM_SIZE_BITS // 128}}} "
                                    f"CONFIG.Read_Width_A {{128}} "
                                    f"CONFIG.Operating_Mode_A {{READ_FIRST}} "
                                    f"CONFIG.Enable_A {{Always_Enabled}} "
                                    f"CONFIG.Write_Width_B {{128}} "
                                    f"CONFIG.Read_Width_B {{128}} "
                                    f"CONFIG.Operating_Mode_B {{READ_FIRST}} "
                                    f"CONFIG.Enable_B {{Always_Enabled}} "
                                    f"CONFIG.Register_PortA_Output_of_Memory_Primitives {{true}} "
                                    f"CONFIG.Register_PortB_Output_of_Memory_Primitives {{false}} "
                                    f"CONFIG.Register_PortA_Output_of_Memory_Core {{true}} "
                                    f"CONFIG.Register_PortB_Output_of_Memory_Core {{true}} "
                                    f"CONFIG.Reset_Memory_Latch_B {{false}} "
                                    f"CONFIG.Use_RSTA_Pin {{false}} "
                                    f"CONFIG.Use_RSTB_Pin {{true}} "
                                    f"CONFIG.Port_B_Clock {{100}} "
                                    f"CONFIG.Port_B_Enable_Rate {{100}} "
                                    f"CONFIG.use_bram_block {{Stand_Alone}} "
                                    f"CONFIG.EN_SAFETY_CKT {{false}}")
            connect_bd_intf_net(f, f"hedgehog/instruction_mem/BRAM_PORTB", f"hedgehog/sequencer_instruction_mem")
            connect_bd_intf_net(f, f"hedgehog/instruction_mem/BRAM_PORTA", f"hedgehog/mem_decoder/instruction_mem")

            # ------------------- Sequencer flags -------------------- #

            connect_bd_net(f, f"hedgehog/sequencer_flags", f"hedgehog/xlconst_0/Dout")
            
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

            connect_bd_net(f, f"hedgehog/ps_gdma_dataport/cack", f"hedgehog/ps_gdma_cack")
            connect_bd_net(f, f"hedgehog/ps_gdma_dataport/tvld", f"hedgehog/ps_gdma_tvld")
            connect_bd_net(f, f"hedgehog/ps_gdma_dataport/tack", f"hedgehog/ps_gdma_tack")
            connect_bd_net(f, f"hedgehog/ps_gdma_dataport/cvld", f"hedgehog/ps_gdma_cvld")
            connect_bd_net(f, f"hedgehog/ps_irq_dataport/gdma_irq", f"hedgehog/ps_gdma_irq")
            
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

            connect_bd_net(f, f"hedgehog/axis_switch_adc/aclk", f"hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/aresetn", f"hedgehog/seq_peripheral_aresetn")
            
            # Connect the switch to the AXI network and assign it an address in the PS address space
            connect_bd_intf_net(f, f"hedgehog/axis_switch_adc/S_AXI_CTRL", f"hedgehog/config_smartconnect/M05_AXI")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/s_axi_ctrl_aclk", f"hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/s_axi_ctrl_aresetn", f"hedgehog/seq_peripheral_aresetn")
            assign_bd_address(f, addr_seg="hedgehog/axis_switch_adc/S_AXI_CTRL/Reg", target_address_space="/ps/Data", offset=StandardFirmware.ADC_AXIS_SWITCH_ADDR, range="256K")

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
                connect_bd_net(f, f"hedgehog/adc{channel}_register/aclk", f"hedgehog/seq_clk")
                connect_bd_net(f, f"hedgehog/adc{channel}_register/aresetn", f"hedgehog/seq_peripheral_aresetn")
                
                connect_bd_net(f, f"hedgehog/adc{channel}_register/s_axis_tdata", f"hedgehog/rfdc/m{tile}{block}_axis_tdata")
                connect_bd_net(f, f"hedgehog/adc{channel}_register/s_axis_tvalid", f"hedgehog/xlconst_1/Dout")
                
                connect_bd_intf_net(f, f"hedgehog/adc{channel}_register/M_AXIS", 
                                       f"hedgehog/axis_switch_adc/S{channel:02d}_AXIS")

            # ------------------- Configuration DataMover -------------------- #

            # First, create the bus-driven DataMover Controller and connect it to the bus
            create_module(f, f"hedgehog/datamover_controller", "datamover_controller")
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/datamover_controller", f"hedgehog/datamover_controller/master_bus")
            connect_bd_net(f, f"hedgehog/datamover_controller/clk", "hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/datamover_controller/nrst", "hedgehog/seq_peripheral_aresetn")

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
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_mm2s_cmdsts_aclk", "hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_mm2s_cmdsts_aresetn", "hedgehog/seq_peripheral_aresetn")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_s2mm_cmdsts_awclk", "hedgehog/clk_wiz/clk_300")
            connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axis_s2mm_cmdsts_aresetn", "hedgehog/seq_peripheral_aresetn")

            # For this DataMover, we want to connect the MM2S and S2MM streams to each other
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/S_AXIS_S2MM", f"hedgehog/cfg_axi_dm/M_AXIS_MM2S")

            # Connect the MM2S AXI master to the memory smartconnect
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXI_MM2S", f"hedgehog/memory_smartconnect/S09_AXI")

            # Connect the S2MM AXI master to the configuration smartconnect
            connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXI_S2MM", f"hedgehog/config_smartconnect/S01_AXI")

            for direction in ["mm2s","s2mm"]:
                # Connect AXI Master clocks and resets
                connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axi_{direction}_aclk", "hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/cfg_axi_dm/m_axi_{direction}_aresetn", "hedgehog/seq_peripheral_aresetn")

                # Connect the MM2S command and status interfaces to the bus-driven DataMover controller
                connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/S_AXIS_{direction.upper()}_CMD", f"hedgehog/datamover_controller/cfg_dm_{direction}_CMD")
                connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXIS_{direction.upper()}_STS", f"hedgehog/datamover_controller/cfg_dm_{direction}_STS")

                # Connect the error signal to the controller
                connect_bd_net(f, f"hedgehog/cfg_axi_dm/{direction}_err", f"hedgehog/datamover_controller/cfg_dm_{direction}_err")

            # Assign the PS DDR into the AXI DataMover's address space
            assign_bd_address(f, offset=StandardFirmware.HPC0_DDR_LOW_ADDR, range="2G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP0/HPC0_DDR_LOW")
            assign_bd_address(f, offset=StandardFirmware.HPC1_DDR_LOW_ADDR, range="2G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP1/HPC1_DDR_LOW")
            assign_bd_address(f, offset=StandardFirmware.HP0_DDR_LOW_ADDR, range="2G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP2/HP0_DDR_LOW")
            assign_bd_address(f, offset=StandardFirmware.HP1_DDR_LOW_ADDR, range="2G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP3/HP1_DDR_LOW")
            
            assign_bd_address(f, offset=StandardFirmware.HPC0_DDR_HIGH_ADDR, range="32G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP0/HPC0_DDR_HIGH")
            assign_bd_address(f, offset=StandardFirmware.HPC1_DDR_HIGH_ADDR, range="32G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP1/HPC1_DDR_HIGH")
            assign_bd_address(f, offset=StandardFirmware.HP0_DDR_HIGH_ADDR, range="32G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP2/HP0_DDR_HIGH")
            assign_bd_address(f, offset=StandardFirmware.HP1_DDR_HIGH_ADDR, range="32G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP3/HP1_DDR_HIGH")

            # Assign the PS OCM into the AXI DataMover's address space
            assign_bd_address(f, offset=StandardFirmware.HPC0_LPS_OCM_ADDR, range="256K", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP0/HPC0_LPS_OCM")
            assign_bd_address(f, offset=StandardFirmware.HPC1_LPS_OCM_ADDR, range="256K", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP1/HPC1_LPS_OCM")
            assign_bd_address(f, offset=StandardFirmware.HP0_LPS_OCM_ADDR, range="256K", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP2/HP0_LPS_OCM")
            assign_bd_address(f, offset=StandardFirmware.HP1_LPS_OCM_ADDR, range="256K", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="ps/SAXIGP3/HP1_LPS_OCM")

            # Assign the PL DDR into the AXI DataMover's address space
            assign_bd_address(f, offset=StandardFirmware.DDR4_C0_ADDR, range="4G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="DDR4_C0_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK")
            assign_bd_address(f, offset=StandardFirmware.DDR4_C1_ADDR, range="4G", target_address_space="/hedgehog/cfg_axi_dm/Data_MM2S", addr_seg="DDR4_C1_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK")

            # Exclude the QSPI
            for idx,port in enumerate(["HPC0", "HPC1", "HP0", "HP1"]):
                exclude_bd_addr_seg(f, addr_seg=f"ps/SAXIGP{idx}/{port}_QSPI", target_address_space="hedgehog/cfg_axi_dm/Data_MM2S")
            
            # Assign all the other peripherals into the address space of the DataMover
            assign_bd_address(f, target_address_space="hedgehog/cfg_axi_dm/Data_S2MM", offset=StandardFirmware.BRAM_CTRL_MEM_DECODER_ADDR, range=next_highest_power_of_2(self["mem_decoder"].words(bus_data_bits=8)), addr_seg=f"hedgehog/axi_bram_ctrl_mem_decoder/S_AXI/Mem0")
            assign_bd_address(f, target_address_space="hedgehog/cfg_axi_dm/Data_S2MM", offset=StandardFirmware.BRAM_CTRL_DAC_MEM_DECODER_ADDR, range=next_highest_power_of_2(self["dac_mem_decoder"].words(bus_data_bits=8)), addr_seg=f"hedgehog/axi_bram_ctrl_dac_mem_decoder/S_AXI/Mem0")
            assign_bd_address(f, target_address_space="hedgehog/cfg_axi_dm/Data_S2MM", offset=StandardFirmware.RFDC_ADDR, range="256K", addr_seg=f"hedgehog/rfdc/s_axi/Reg")
            assign_bd_address(f, target_address_space="hedgehog/cfg_axi_dm/Data_S2MM", offset=StandardFirmware.CLK_WIZ_ADDR, range="256K", addr_seg=f"hedgehog/clk_wiz/s_axi_lite/Reg")
            assign_bd_address(f, target_address_space="hedgehog/cfg_axi_dm/Data_S2MM", offset=StandardFirmware.BRAM_CTRL_CACHE_ADDR, range=next_highest_power_of_2(StandardFirmware.CACHE_SIZE_BITS // 8), addr_seg=f"hedgehog/axi_bram_ctrl_cache/S_AXI/Mem0")
            assign_bd_address(f, addr_seg="hedgehog/axis_switch_adc/S_AXI_CTRL/Reg", target_address_space="hedgehog/cfg_axi_dm/Data_S2MM", offset=StandardFirmware.ADC_AXIS_SWITCH_ADDR, range="256K")

            # ------------------- ADC DMAs -------------------- #

            for d in range(StandardFirmware.NUM_ADC):

                # ------------------- Real-time DMAs -------------------- #
                create_module(f, f"hedgehog/adc_dma{d}", "acadia_dma")
                connect_bd_net(f, f"hedgehog/adc_dma{d}/clk", f"hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/adc_dma{d}/nrst", f"hedgehog/seq_peripheral_aresetn")

                # Connect the ADC DMA signals to the dataports
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/adc_dma{d}_fifo_mosi", f"hedgehog/adc_dma{d}/descriptor_address_fifo_in")
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/adc_dma{d}_fifo_wr", f"hedgehog/adc_dma{d}/descriptor_address_fifo_wr")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/adc_dma{d}", f"hedgehog/adc_dma{d}/trigger")
                connect_bd_net(f, f"hedgehog/dma_fifo_empty_dataport/adc_dma{d}", f"hedgehog/adc_dma{d}/descriptor_address_fifo_empty")
                connect_bd_net(f, f"hedgehog/dma_fifo_almost_empty_dataport/adc_dma{d}", f"hedgehog/adc_dma{d}/descriptor_address_fifo_almost_empty")
                
                # Create and configure ADC Descriptor BRAMs 
                create_ip(f, name=f"hedgehog/adc_dma{d}_descriptor_mem", vlnv="xilinx.com:ip:blk_mem_gen:8.4")
                set_property(f, name=f"hedgehog/adc_dma{d}_descriptor_mem", 
                                 properties=f"CONFIG.Memory_Type {{True_Dual_Port_RAM}} "
                                            f"CONFIG.Enable_32bit_Address {{false}} "
                                            f"CONFIG.Use_Byte_Write_Enable {{true}} "
                                            f"CONFIG.Byte_Size {{8}} "
                                            f"CONFIG.Assume_Synchronous_Clk {{true}} "
                                            f"CONFIG.Write_Width_A {{128}} "
                                            f"CONFIG.Write_Depth_A {{{StandardFirmware.ADC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 128}}} "
                                            f"CONFIG.Read_Width_A {{128}} "
                                            f"CONFIG.Enable_A {{Always_Enabled}} "
                                            f"CONFIG.Write_Width_B {{64}} "
                                            f"CONFIG.Read_Width_B {{64}} "
                                            f"CONFIG.Enable_B {{Always_Enabled}} "
                                            f"CONFIG.Operating_Mode_B {{READ_FIRST}} "
                                            f"CONFIG.Register_PortA_Output_of_Memory_Primitives {{true}} "
                                            f"CONFIG.Register_PortB_Output_of_Memory_Primitives {{false}} "
                                            f"CONFIG.Register_PortA_Output_of_Memory_Core {{true}} "
                                            f"CONFIG.Register_PortB_Output_of_Memory_Core {{false}} "
                                            f"CONFIG.Use_RSTA_Pin {{false}} "
                                            f"CONFIG.Use_RSTB_Pin {{false}} "
                                            f"CONFIG.Port_B_Clock {{100}} "
                                            f"CONFIG.Port_B_Write_Rate {{50}} "
                                            f"CONFIG.Port_B_Enable_Rate {{100}} "
                                            f"CONFIG.use_bram_block {{Stand_Alone}} "
                                            f"CONFIG.EN_SAFETY_CKT {{true}}")
                connect_bd_intf_net(f, f"hedgehog/adc_dma{d}_descriptor_mem/BRAM_PORTB", f"hedgehog/adc_dma{d}/DESCRIPTOR_MEM")

                # Connect ADC Descriptor BRAMs to the memory controller through a pipeline
                connect_bd_intf_net(f, f"hedgehog/mem_decoder/adc_dma{d}_descriptor_mem", f"hedgehog/adc_dma{d}_descriptor_mem/BRAM_PORTA")

                # ------------------- AXIS Data FIFOs -------------------- #

                create_ip(f, name=f"hedgehog/axis_data_fifo_adc_dm{d}", vlnv="xilinx.com:ip:axis_data_fifo:2.0")
                set_property(f, name=f"hedgehog/axis_data_fifo_adc_dm{d}", properties="CONFIG.TDATA_NUM_BYTES.VALUE_SRC USER CONFIG.HAS_TLAST.VALUE_SRC USER")
                set_property(f, name=f"hedgehog/axis_data_fifo_adc_dm{d}", properties={"TDATA_NUM_BYTES": 16, "FIFO_DEPTH": StandardFirmware.ADC_AXIS_FIFO_DEPTH, "HAS_TLAST": 1, "HAS_AFULL": 1})

                connect_bd_net(f, f"hedgehog/axis_data_fifo_adc_dm{d}/s_axis_aclk", f"hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/axis_data_fifo_adc_dm{d}/s_axis_aresetn", f"hedgehog/seq_peripheral_aresetn")

                # Connect the FIFO stream input to the AXIS Switch output by creating a slice
                create_slice(f, f"hedgehog/xlslice_axis_data_fifo_adc_dm{d}_data", input_width=128*8, input_to=d*128, input_from=d*128 + 127)
                connect_bd_net(f, f"hedgehog/xlslice_axis_data_fifo_adc_dm{d}_data/Din", f"hedgehog/axis_switch_adc/m_axis_tdata")
                connect_bd_net(f, f"hedgehog/axis_data_fifo_adc_dm{d}/s_axis_tdata", f"hedgehog/xlslice_axis_data_fifo_adc_dm{d}_data/Dout")
                
                # Connect the ADC DMA AXIS handshaking signals to the AXIS FIFO handshaking inputs
                connect_bd_net(f, f"hedgehog/adc_dma{d}/addr_tvalid", f"hedgehog/axis_data_fifo_adc_dm{d}/s_axis_tvalid")
                connect_bd_net(f, f"hedgehog/adc_dma{d}/addr_tlast", f"hedgehog/axis_data_fifo_adc_dm{d}/s_axis_tlast")

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
                connect_bd_net(f, f"hedgehog/adc_dm{d}/m_axi_s2mm_aclk", "hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/adc_dm{d}/m_axi_s2mm_aresetn", "hedgehog/seq_peripheral_aresetn")
                connect_bd_net(f, f"hedgehog/adc_dm{d}/m_axis_s2mm_cmdsts_awclk", "hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/adc_dm{d}/m_axis_s2mm_cmdsts_aresetn", "hedgehog/seq_peripheral_aresetn")

                # Connect the S2MM command and status interfaces to the bus-driven DataMover controller
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/S_AXIS_S2MM_CMD", f"hedgehog/datamover_controller/adc_dm{d}_cmd")
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/M_AXIS_S2MM_STS", f"hedgehog/datamover_controller/adc_dm{d}_sts")

                # Connect the error signal to the controller
                connect_bd_net(f, f"hedgehog/adc_dm{d}/s2mm_err", f"hedgehog/datamover_controller/adc_dm{d}_err")

                # Connect the S2MM stream input to the output of the AXIS Data FIFO
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/s_axis_s2mm", f"hedgehog/axis_data_fifo_adc_dm{d}/m_axis")

                # Connect the DMA S2MM master to the memory smartconnect
                connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/S{d+1:02d}_AXI", f"hedgehog/adc_dm{d}/M_AXI_S2MM")

                # Assign the PS DDR into the AXI DataMover's S2MM address space     
                assign_bd_address(f, offset=StandardFirmware.HPC0_DDR_LOW_ADDR, range="2G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP0/HPC0_DDR_LOW")
                assign_bd_address(f, offset=StandardFirmware.HPC1_DDR_LOW_ADDR, range="2G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP1/HPC1_DDR_LOW")
                assign_bd_address(f, offset=StandardFirmware.HP0_DDR_LOW_ADDR, range="2G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP2/HP0_DDR_LOW")
                assign_bd_address(f, offset=StandardFirmware.HP1_DDR_LOW_ADDR, range="2G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP3/HP1_DDR_LOW")
                
                assign_bd_address(f, offset=StandardFirmware.HPC0_DDR_HIGH_ADDR, range="32G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP0/HPC0_DDR_HIGH")
                assign_bd_address(f, offset=StandardFirmware.HPC1_DDR_HIGH_ADDR, range="32G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP1/HPC1_DDR_HIGH")
                assign_bd_address(f, offset=StandardFirmware.HP0_DDR_HIGH_ADDR, range="32G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP2/HP0_DDR_HIGH")
                assign_bd_address(f, offset=StandardFirmware.HP1_DDR_HIGH_ADDR, range="32G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP3/HP1_DDR_HIGH")

                # Assign the PS OCM into the AXI DataMover's address space
                assign_bd_address(f, offset=StandardFirmware.HPC0_LPS_OCM_ADDR, range="256K", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP0/HPC0_LPS_OCM")
                assign_bd_address(f, offset=StandardFirmware.HPC1_LPS_OCM_ADDR, range="256K", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP1/HPC1_LPS_OCM")
                assign_bd_address(f, offset=StandardFirmware.HP0_LPS_OCM_ADDR, range="256K", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP2/HP0_LPS_OCM")
                assign_bd_address(f, offset=StandardFirmware.HP1_LPS_OCM_ADDR, range="256K", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP3/HP1_LPS_OCM")

                # Assign the PL DDR into the AXI DMA's S2MM address space
                assign_bd_address(f, offset=StandardFirmware.DDR4_C0_ADDR, range="4G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="DDR4_C0_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK")
                assign_bd_address(f, offset=StandardFirmware.DDR4_C1_ADDR, range="4G", target_address_space=f"/hedgehog/adc_dm{d}/Data_S2MM", addr_seg="DDR4_C1_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK")

                # Exclude the QSPI
                for idx,port in enumerate(["HPC0", "HPC1", "HP0", "HP1"]):
                    exclude_bd_addr_seg(f, addr_seg=f"ps/SAXIGP{idx}/{port}_QSPI", target_address_space=f"hedgehog/adc_dm{d}/Data_S2MM")

                # Connect the AXI DMA TKEEP input to a constant
                connect_bd_net(f, f"hedgehog/adc_dm{d}/s_axis_s2mm_tkeep", f"hedgehog/xlconst_FFFF/Dout")

            # ------------------- Complex MACCs ------------------- #
            
            for d in range(4):

                # ------------------- The CMACC modules -------------------- #
                create_module(f, f"hedgehog/cmacc{d}", "acadia_fast_complex_macc")
                connect_bd_net(f, f"hedgehog/cmacc{d}/clk", f"hedgehog/clk_wiz/clk_300")

                # Connect the CMACC signal input to the ADC switch through a slice
                create_slice(f, f"hedgehog/xlslice_cmacc{d}", input_width=128*8, input_to=(d+4)*128, input_from=(d+4)*128 + 127)
                connect_bd_net(f, f"hedgehog/axis_switch_adc/m_axis_tdata", f"hedgehog/xlslice_cmacc{d}/Din")
                connect_bd_net(f, f"hedgehog/xlslice_cmacc{d}/Dout", f"hedgehog/cmacc{d}/signal_in")  
                
                # Connect the accumulator reset signal
                connect_bd_net(f, f"hedgehog/cmacc{d}/rst", f"hedgehog/cmacc_reset_dataport/cmacc{d}")

                # ------------------- Kernel BRAMs -------------------- #        
                create_ip(f, name=f"hedgehog/cmacc{d}_kernel_mem", vlnv="xilinx.com:ip:blk_mem_gen:8.4")
                set_property(f, name=f"hedgehog/cmacc{d}_kernel_mem", 
                                 properties=f"CONFIG.Memory_Type {{True_Dual_Port_RAM}} "
                                            f"CONFIG.Enable_32bit_Address {{false}} "
                                            f"CONFIG.Use_Byte_Write_Enable {{true}} "
                                            f"CONFIG.Byte_Size {{8}} "
                                            f"CONFIG.Assume_Synchronous_Clk {{true}} "
                                            f"CONFIG.Write_Width_A {{128}} "
                                            f"CONFIG.Write_Depth_A {{{StandardFirmware.CMACC_KERNEL_MEM_SIZE_BITS // 128}}} "
                                            f"CONFIG.Read_Width_A {{128}} "
                                            f"CONFIG.Operating_Mode_A {{READ_FIRST}} "
                                            f"CONFIG.Enable_A {{Always_Enabled}} "
                                            f"CONFIG.Write_Width_B {{32}} "
                                            f"CONFIG.Read_Width_B {{32}} "
                                            f"CONFIG.Operating_Mode_B {{READ_FIRST}} "
                                            f"CONFIG.Enable_B {{Always_Enabled}} "
                                            f"CONFIG.Register_PortA_Output_of_Memory_Primitives {{false}} "
                                            f"CONFIG.Register_PortB_Output_of_Memory_Primitives {{false}} "
                                            f"CONFIG.Register_PortA_Output_of_Memory_Core {{true}} "
                                            f"CONFIG.Register_PortB_Output_of_Memory_Core {{false}} "
                                            f"CONFIG.Use_RSTA_Pin {{false}} "
                                            f"CONFIG.Use_RSTB_Pin {{true}} "
                                            f"CONFIG.Port_B_Clock {{100}} CONFIG.Port_B_Enable_Rate {{100}} "
                                            f"CONFIG.use_bram_block {{Stand_Alone}} "
                                            f"CONFIG.EN_SAFETY_CKT {{true}}")

                # Connect the kernel BRAM to the CMACC
                connect_bd_intf_net(f, f"hedgehog/cmacc{d}_kernel_mem/BRAM_PORTB", f"hedgehog/cmacc{d}/kernel_mem") 

                # Connect the kernel BRAM to the memory controller
                connect_bd_intf_net(f, f"hedgehog/cmacc{d}_kernel_mem/BRAM_PORTA", f"hedgehog/mem_decoder/cmacc{d}_kernel_mem")

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
                connect_bd_net(f, f"hedgehog/cmacc_dma{d}/clk", f"hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/cmacc_dma{d}/nrst", f"hedgehog/seq_peripheral_aresetn")

                # Connect the DMA signals to the dataports
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cmacc_dma{d}_fifo_mosi", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_in")
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/cmacc_dma{d}_fifo_wr", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_wr")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/trigger")
                connect_bd_net(f, f"hedgehog/dma_fifo_empty_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_empty")
                connect_bd_net(f, f"hedgehog/dma_fifo_almost_empty_dataport/cmacc_dma{d}", f"hedgehog/cmacc_dma{d}/descriptor_address_fifo_almost_empty")

                # Connect the CMACC DMA to the CMACC DMA port
                connect_bd_intf_net(f, f"hedgehog/cmacc_dma{d}/addr", f"hedgehog/cmacc{d}/kernel_mem_addr")

                # Create and configure CMACC Descriptor BRAMs 
                create_ip(f, name=f"hedgehog/cmacc_dma{d}_descriptor_mem", vlnv="xilinx.com:ip:blk_mem_gen:8.4")
                set_property(f, name=f"hedgehog/cmacc_dma{d}_descriptor_mem", 
                                 properties=f"CONFIG.Memory_Type {{True_Dual_Port_RAM}} "
                                            f"CONFIG.Enable_32bit_Address {{false}} "
                                            f"CONFIG.Use_Byte_Write_Enable {{true}} "
                                            f"CONFIG.Byte_Size {{8}} "
                                            f"CONFIG.Assume_Synchronous_Clk {{true}} "
                                            f"CONFIG.Write_Width_A {{128}} "
                                            f"CONFIG.Write_Depth_A {{{StandardFirmware.CMACC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 128}}} "
                                            f"CONFIG.Read_Width_A {{128}} "
                                            f"CONFIG.Enable_A {{Always_Enabled}} "
                                            f"CONFIG.Write_Width_B {{64}} "
                                            f"CONFIG.Read_Width_B {{64}} "
                                            f"CONFIG.Enable_B {{Always_Enabled}} "
                                            f"CONFIG.Operating_Mode_B {{READ_FIRST}} "
                                            f"CONFIG.Register_PortA_Output_of_Memory_Primitives {{true}} "
                                            f"CONFIG.Register_PortB_Output_of_Memory_Primitives {{false}} "
                                            f"CONFIG.Register_PortA_Output_of_Memory_Core {{true}} "
                                            f"CONFIG.Register_PortB_Output_of_Memory_Core {{false}} "
                                            f"CONFIG.Use_RSTA_Pin {{false}} "
                                            f"CONFIG.Use_RSTB_Pin {{false}} "
                                            f"CONFIG.Port_B_Clock {{100}} "
                                            f"CONFIG.Port_B_Write_Rate {{50}} "
                                            f"CONFIG.Port_B_Enable_Rate {{100}} "
                                            f"CONFIG.use_bram_block {{Stand_Alone}} "
                                            f"CONFIG.EN_SAFETY_CKT {{true}}")
                connect_bd_intf_net(f, f"hedgehog/cmacc_dma{d}_descriptor_mem/BRAM_PORTB", f"hedgehog/cmacc_dma{d}/DESCRIPTOR_MEM")

                # Connect CMACC Descriptor BRAMs to the memory controller through a pipeline
                connect_bd_intf_net(f, f"hedgehog/mem_decoder/cmacc_dma{d}_descriptor_mem", f"hedgehog/cmacc_dma{d}_descriptor_mem/BRAM_PORTA")

                # ------------------- AXIS Data FIFOs -------------------- #

                create_ip(f, name=f"hedgehog/axis_data_fifo_cmacc_dm{d}", vlnv="xilinx.com:ip:axis_data_fifo:2.0")
                set_property(f, name=f"hedgehog/axis_data_fifo_cmacc_dm{d}", properties="CONFIG.TDATA_NUM_BYTES.VALUE_SRC USER CONFIG.HAS_TLAST.VALUE_SRC USER")
                set_property(f, name=f"hedgehog/axis_data_fifo_cmacc_dm{d}", properties={"TDATA_NUM_BYTES": 4, "FIFO_DEPTH": StandardFirmware.CMACC_AXIS_FIFO_DEPTH, "HAS_TLAST": 1, "HAS_AFULL": 1})

                connect_bd_net(f, f"hedgehog/axis_data_fifo_cmacc_dm{d}/s_axis_aclk", f"hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/axis_data_fifo_cmacc_dm{d}/s_axis_aresetn", f"hedgehog/clk_wiz/locked")

                # Connect the FIFO stream input to the CMACC signal passthrough
                connect_bd_intf_net(f, f"hedgehog/axis_data_fifo_cmacc_dm{d}/s_axis", f"hedgehog/cmacc{d}/signal_out")

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
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/m_axi_s2mm_aclk", "hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/m_axi_s2mm_aresetn", "hedgehog/seq_peripheral_aresetn")
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/m_axis_s2mm_cmdsts_awclk", "hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/m_axis_s2mm_cmdsts_aresetn", "hedgehog/seq_peripheral_aresetn")

                # Connect the MM2S command and status interfaces to the bus-driven DataMover controller
                connect_bd_intf_net(f, f"hedgehog/cmacc_dm{d}/S_AXIS_S2MM_CMD", f"hedgehog/datamover_controller/cmacc_dm{d}_cmd")
                connect_bd_intf_net(f, f"hedgehog/cmacc_dm{d}/M_AXIS_S2MM_STS", f"hedgehog/datamover_controller/cmacc_dm{d}_sts")

                # Connect the error signal to the controller
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/s2mm_err", f"hedgehog/datamover_controller/cmacc_dm{d}_err")

                # Connect the S2MM stream input to the output of the AXIS Data FIFO
                connect_bd_intf_net(f, f"hedgehog/cmacc_dm{d}/s_axis_s2mm", f"hedgehog/axis_data_fifo_cmacc_dm{d}/m_axis")

                # Connect the S2MM AXI master to the memory smartconnect
                connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/S{d+5:02d}_AXI", f"hedgehog/cmacc_dm{d}/M_AXI_S2MM")

                # Assign the PS DDR into the AXI DataMover's S2MM address space
                assign_bd_address(f, offset=StandardFirmware.HPC0_DDR_LOW_ADDR, range="2G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP0/HPC0_DDR_LOW")
                assign_bd_address(f, offset=StandardFirmware.HPC1_DDR_LOW_ADDR, range="2G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP1/HPC1_DDR_LOW")
                assign_bd_address(f, offset=StandardFirmware.HP0_DDR_LOW_ADDR, range="2G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP2/HP0_DDR_LOW")
                assign_bd_address(f, offset=StandardFirmware.HP1_DDR_LOW_ADDR, range="2G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP3/HP1_DDR_LOW")
                
                assign_bd_address(f, offset=StandardFirmware.HPC0_DDR_HIGH_ADDR, range="32G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP0/HPC0_DDR_HIGH")
                assign_bd_address(f, offset=StandardFirmware.HPC1_DDR_HIGH_ADDR, range="32G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP1/HPC1_DDR_HIGH")
                assign_bd_address(f, offset=StandardFirmware.HP0_DDR_HIGH_ADDR, range="32G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP2/HP0_DDR_HIGH")
                assign_bd_address(f, offset=StandardFirmware.HP1_DDR_HIGH_ADDR, range="32G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP3/HP1_DDR_HIGH")

                # Assign the PS OCM into the AXI DataMover's address space
                assign_bd_address(f, offset=StandardFirmware.HPC0_LPS_OCM_ADDR, range="256K", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP0/HPC0_LPS_OCM")
                assign_bd_address(f, offset=StandardFirmware.HPC1_LPS_OCM_ADDR, range="256K", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP1/HPC1_LPS_OCM")
                assign_bd_address(f, offset=StandardFirmware.HP0_LPS_OCM_ADDR, range="256K", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP2/HP0_LPS_OCM")
                assign_bd_address(f, offset=StandardFirmware.HP1_LPS_OCM_ADDR, range="256K", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="ps/SAXIGP3/HP1_LPS_OCM")

                # Assign the PL DDR into the AXI DMA's S2MM address space
                assign_bd_address(f, offset=StandardFirmware.DDR4_C0_ADDR, range="4G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="DDR4_C0_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK")
                assign_bd_address(f, offset=StandardFirmware.DDR4_C1_ADDR, range="4G", target_address_space=f"/hedgehog/cmacc_dm{d}/Data_S2MM", addr_seg="DDR4_C1_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK")

                # Exclude the QSPI
                for idx,port in enumerate(["HPC0", "HPC1", "HP0", "HP1"]):
                    exclude_bd_addr_seg(f, addr_seg=f"ps/SAXIGP{idx}/{port}_QSPI", target_address_space=f"hedgehog/cmacc_dm{d}/Data_S2MM")

                # Connect the AXI DMA TKEEP input to a constant
                connect_bd_net(f, f"hedgehog/cmacc_dm{d}/s_axis_s2mm_tkeep", f"hedgehog/xlconst_FFFF/Dout")

            # ------------------- DAC channels -------------------- #

            for channel in range(StandardFirmware.NUM_DAC):
                tile = channel // 4
                block = channel % 4
                # Create and configure DAC UltraRAM
                create_ip(f, name=f"hedgehog/dac_dma{channel}_mem", vlnv="xilinx.com:ip:blk_mem_gen:8.4")
                set_property(f, name=f"hedgehog/dac_dma{channel}_mem", 
                                 properties=f"CONFIG.Memory_Type {{True_Dual_Port_RAM}} "
                                            f"CONFIG.PRIM_type_to_Implement {{URAM}} "
                                            f"CONFIG.Enable_32bit_Address {{false}} "
                                            f"CONFIG.Use_RSTB_Pin {{true}} "
                                            f"CONFIG.Use_Byte_Write_Enable {{true}} "
                                            f"CONFIG.Byte_Size {{8}} "
                                            f"CONFIG.Assume_Synchronous_Clk {{true}} "
                                            f"CONFIG.Write_Width_A {{128}} "
                                            f"CONFIG.Read_Width_A {{128}} "
                                            f"CONFIG.Write_Depth_A {{{StandardFirmware.DAC_MEM_SIZE_BITS // 128}}} "
                                            f"CONFIG.Operating_Mode_A {{NO_CHANGE}} "
                                            f"CONFIG.Write_Width_B {{128}} "
                                            f"CONFIG.Read_Width_B {{128}} "
                                            f"CONFIG.Operating_Mode_B {{NO_CHANGE}} "
                                            f"CONFIG.Enable_A {{Always_Enabled}} "
                                            f"CONFIG.Use_RSTA_Pin {{false}} "
                                            f"CONFIG.Port_A_Write_Rate {{50}} "
                                            f"CONFIG.Port_B_Clock {{100}} "
                                            f"CONFIG.Port_B_Write_Rate {{0}} "
                                            f"CONFIG.Port_B_Enable_Rate {{100}} "
                                            f"CONFIG.use_bram_block {{Stand_Alone}} "
                                            f"CONFIG.EN_SAFETY_CKT {{false}} "
                                            f"CONFIG.READ_LATENCY_A {{3}} "
                                            f"CONFIG.READ_LATENCY_B {{2}}")

                # Connect the DAC BRAM to the memory decoder
                connect_bd_intf_net(f, f"hedgehog/dac_dma{channel}_mem/BRAM_PORTA", f"hedgehog/dac_mem_decoder/dac_dma{channel}_mem")

                # Create a DMA for the DAC and connect it to the read port of the BRAM
                create_module(f, f"hedgehog/dac_dma{channel}", "acadia_dma")
                connect_bd_intf_net(f, f"hedgehog/dac_dma{channel}/mem_control", f"hedgehog/dac_dma{channel}_mem/BRAM_PORTB")
                connect_bd_net(f, f"hedgehog/dac_dma{channel}/clk", f"hedgehog/clk_wiz/clk_300")
                connect_bd_net(f, f"hedgehog/dac_dma{channel}/nrst", f"hedgehog/seq_peripheral_aresetn")

                # Connect the DAC memory output to the RFDAC interface
                connect_bd_net(f, f"hedgehog/dac_dma{channel}_mem/doutb", f"hedgehog/rfdc/s{tile}{block}_axis_tdata")

                # Connect the DAC DMA to the registers
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/dac_dma{channel}_fifo_mosi", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_in")
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/dac_dma{channel}_fifo_wr", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_wr")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/trigger")
                connect_bd_net(f, f"hedgehog/dma_fifo_empty_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_empty")
                connect_bd_net(f, f"hedgehog/dma_fifo_almost_empty_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_almost_empty")
                
                # Create and configure DAC Descriptor BRAMs and connect them to the DMA
                create_ip(f, name=f"hedgehog/dac_dma{channel}_descriptor_mem", vlnv="xilinx.com:ip:blk_mem_gen:8.4")
                set_property(f, name=f"hedgehog/dac_dma{channel}_descriptor_mem", 
                                 properties=f"CONFIG.Memory_Type {{True_Dual_Port_RAM}} "
                                            f"CONFIG.Enable_32bit_Address {{false}} "
                                            f"CONFIG.Use_Byte_Write_Enable {{true}} "
                                            f"CONFIG.Byte_Size {{8}} "
                                            f"CONFIG.Assume_Synchronous_Clk {{true}} "
                                            f"CONFIG.Write_Width_A {{128}} "
                                            f"CONFIG.Write_Depth_A {{{StandardFirmware.DAC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 128}}} "
                                            f"CONFIG.Read_Width_A {{128}} "
                                            f"CONFIG.Enable_A {{Always_Enabled}} "
                                            f"CONFIG.Write_Width_B {{64}} "
                                            f"CONFIG.Read_Width_B {{64}} "
                                            f"CONFIG.Enable_B {{Always_Enabled}} "
                                            f"CONFIG.Register_PortA_Output_of_Memory_Primitives {{true}} "
                                            f"CONFIG.Register_PortB_Output_of_Memory_Primitives {{false}} "
                                            f"CONFIG.Register_PortA_Output_of_Memory_Core {{true}} "
                                            f"CONFIG.Register_PortB_Output_of_Memory_Core {{false}} "
                                            f"CONFIG.Use_RSTA_Pin {{false}} "
                                            f"CONFIG.Use_RSTB_Pin {{false}} "
                                            f"CONFIG.Port_B_Clock {{100}} "
                                            f"CONFIG.Port_B_Write_Rate {{50}} "
                                            f"CONFIG.Port_B_Enable_Rate {{100}} "
                                            f"CONFIG.use_bram_block {{Stand_Alone}} "
                                            f"CONFIG.EN_SAFETY_CKT {{true}}")
                connect_bd_intf_net(f, f"hedgehog/dac_dma{channel}_descriptor_mem/BRAM_PORTB", f"hedgehog/dac_dma{channel}/DESCRIPTOR_MEM")

                # Connect the DAC Descriptor BRAMs to the memory controller through a pipeline
                connect_bd_intf_net(f, f"hedgehog/mem_decoder/dac_dma{channel}_descriptor_mem", f"hedgehog/dac_dma{channel}_descriptor_mem/BRAM_PORTA") 
                
class NCOSynchronizer(Synchronizer):
    """
    Synchronizes updates for NCOs.
    """
        
    def __call__(self, *args, **kwargs):
        self._event_source = kwargs.pop("event", "immediate")
        return super().__call__(*args, **kwargs)
        
    def __exit__(self, *args, **kwargs):        
        proc = Processor.active_processor()
        if isinstance(proc, PythonProcessor):
            # Set the event sources
            for (function,channel,args,kwargs) in self._calls.values():
                channel.set_nco_event_source(self._event_source)
                
                if self._event_source == "immediate":
                    offset = proc.call(f"pyxrfdc.lib.XRFDC_{'ADC' if self.is_adc() else 'DAC'}_UPDATE_DYN_OFFSET")
                    proc(proc.call("XRFdc_ClrSetReg", 
                                   proc["rfdc"], 
                                   channel._base_address, 
                                   offset, 
                                   proc.call("pyxrfdc.lib.XRFDC_UPDT_EVNT_MASK"),
                                   proc.call(f"pyxrfdc.lib.XRFDC_UPDT_EVNT_NCO_MASK")))
                    
        elif isinstance(proc, Sequencer):
            if self._event_source not in ["immediate", "pl"]:
                raise ValueError(f"Invalid event source for sequencer-driven"
                                 f" NCO synchronization: {self._event_source}")
            # Aggregate all the update settings
            nco_phase_reset = 0
            update_enables = [0]*8
            update_request = 0
            
            for (function,channel,args,kwargs) in self._calls.values():
                # The bit position for the channel in the update request and 
                # phase reset registers
                bit_position = channel.num
                if channel.is_adc():
                    bit_position += 16
                    
                update_request |= 1 << bit_position
                
                # Which register for setting the update enable pins does this 
                # channel belong to?
                update_enable_reg = 4*channel.tile
                if channel.is_adc():
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
            rts_address = Acadia.firmware["rfdc_rts_regs"].address().value()
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
                raise NotImplemented("PL event synchronization not yet supported")
        else:
            raise TypeError(f"Invalid processor for NCO synchronization: {proc}")
                
class VOPDSASynchronizer(Synchronizer):
    """
    Synchronizes DAC VOP and ADC DSA update signals.
    """
    def __exit__(self, *args, **kwargs):        
        proc = Processor.active_processor()
        if isinstance(proc, Sequencer):
            vop_dsa_update_reg = 0
            
            # The DAC VOP codes each have their own register but the DSA codes
            # are stored together by tile, so we need to aggregate
            tile_dsa_codes = [0]*4
            
            for (function,channel,args,kwargs) in self._calls.values():
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
            for i in range(4):
                if vop_dsa_update_reg & (1 << (16+i)):
                    proc.bus_write(address=rts_address + 0x80, data=tile_dsa_codes[i])

            if vop_dsa_update_reg != 0:
                proc.bus_write(address=rts_address + 0x6D, data=vop_dsa_update_reg)
        else:
            raise TypeError(f"Invalid processor for VOP/DSA synchronization: {proc}")
            
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
            
            for (function,channel,args,kwargs) in self._calls.values():
                # The bit position for the channel in the update request and 
                # phase reset registers
                bit_position = channel.num
                if channel.is_adc():
                    bit_position += 16
                                        
                # Set bits in the enable registers
                if function == "set_tdd_mode":
                    if args[0]:
                        tdd_mode_set_reg |= 1 << bit_position
                    else:
                        tdd_mode_clear_reg |= 1 << bit_position
                else:
                    raise ValueError(f"Unrecognized function {function}.")

            if tdd_mode_set_reg != 0:
                proc.bus_write(address=rts_address + 0x6B, data=tdd_mode_set_reg)
            if tdd_mode_clear_reg != 0:
                proc.bus_write(address=rts_address + 0x6C, data=tdd_mode_clear_reg)
        else:
            raise TypeError(f"Invalid processor for TDD mode synchronization: {proc}")
        
@dataclass(frozen=True)
class Channel:
    num: int = None
    tile: int = None
    block: int = None
    bank: int = None
    converter_type: int = None
    
    nco_synchronizer = NCOSynchronizer()
    vop_dsa_synchronizer = VOPDSASynchronizer()
    tdd_synchronizer = TDDSynchronizer()

    def __post_init__(self):
        self._base_address = None
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

            self.converter_type = xrfdc.XRFDC_DAC_TILE if self.bank > 227 else xrfdc.XRFDC_ADC_TILE
            self.tile = (self.bank - 224) % 4

        if self.block is not None:
            if self.tile is not None:
                self.num = self.tile*4 + self.block

        if self.tile > 4 or self.tile < 0:
            raise ValueError(f"Received invalid tile {self.tile}.")

        if self.block > 4 or self.block < 0:
            raise ValueError(f"Received invalid block {self.block}.")

        if self.converter_type is not None:
            if self.converter_type not in [xrfdc.XRFDC_DAC_TILE, xrfdc.XRFDC_ADC_TILE]:
                raise ValueError(f"Converter type must be `XRFDC_DAC_TILE`"
                                 f" or `XRFDC_ADC_TILE`; received"
                                 f" {self.converter_type}.")

            self.bank = 224 + self.tile
            if self.converter_type == xrfdc.XRFDC_DAC_TILE:
                self.bank += 4    
                
        if (self.converter_type is not None 
                and self.tile is not None 
                and self.block is not None):
            self._base_address = pyxrfdc.lib.DEF_XRFDC_BLOCK_BASE(self.converter_type, self.tile, self.block)
            
    @staticmethod
    def DAC(*args, **kwargs):
        """
        :return: a :class:`Channel` representing a DAC.
        :rtype: :class:`Channel`
        """
        return Channel(*args,
                       converter_type=xrfdc.XRFDC_DAC_TILE, 
                       **kwargs)

    @staticmethod
    def ADC(*args, **kwargs):
        """
        :return: a :class:`Channel` representing an ADC.
        :rtype: :class:`Channel`
        """
        return Channel(*args,
                       converter_type=xrfdc.XRFDC_ADC_TILE, 
                       **kwargs)
    
    def is_dac(self):
        """
        :return: `True` if this channel represents a DAC channel
        :rtype: bool
        """
        return self.converter_type == xrfdc.XRFDC_DAC_TILE
    
    def is_adc(self):
        """
        :return: `True` if this channel represents an ADC channel
        :rtype: bool
        """
        return self.converter_type == xrfdc.XRFDC_ADC_TILE
    
    def set_nco_update_event_source(self, source="immediate"):
        """
        Set the NCO update source.
        :param source: The source of the update event. Must be one of: 
        "immediate", "slice", "tile", "sysref", "marker", "pl"
        :type source: str, optional
        
        """
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("NCO update event source may only be set on the PS.")
            
        if self._base_address is None:
            raise ValueError("Insufficient information provided to"
                                 " `Channel` instance to determine"
                                 " configuration address.")

        if source not in ["immediate", "slice", "tile", "sysref", "marker", "pl"]:
            raise ValueError(f"Invalid source {source}.")
        
        proc(proc.call("XRFdc_ClrSetReg", 
                       proc["rfdc"], 
                       self._base_address, 
                       proc.call("pyxrfdc.lib.XRFDC_NCO_UPDT_OFFSET"), 
                       proc.call("pyxrfdc.lib.XRFDC_NCO_UPDT_MODE_MASK"),
                       proc.call(f"pyxrfdc.lib.XRFDC_EVNT_SRC_{source.upper()}")))
        
    def nco_update_event(self):
        """
        Trigger an NCO update event from the RFDC software driver.
        """
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("Update events may only be triggered by the PS.")
            
        proc(proc.call("XRFdc_UpdateEvent", 
                       proc["rfdc"], 
                       self.converter_type, 
                       self.tile,
                       self.block,
                       proc.call(f"pyxrfdc.lib.XRFDC_EVENT_MIXER")))
    
    @nco_synchronizer.synchronized
    def set_nco_frequency(self, frequency, low=True, mid=True, high=True):
        """
        Configure some or all NCO settings. The three 16-bit registers for
        the frequency tuning word, the two for the phase word, and the single  may be individually enabled, allowing
        for lower latency when less precise changes are acceptable.
        :param frequency_word: Frequency tuning word
        :type frequency_word: int
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
        proc = Processor.active_processor()
        if isinstance(proc, PythonProcessor):
            if self._base_address is None:
                raise ValueError("Insufficient information provided to"
                                 " `Channel` instance to determine"
                                 " configuration address.")
            
            if low:
                proc(proc.call("pyxrfdc.lib.WriteReg16", 
                               proc["rfdc"], 
                               self._base_address, 
                               proc.call("pyxrfdc.lib.XRFDC_ADC_NCO_FQWD_LOW_OFFSET"), 
                               frequency & 0xFFFF))
            if mid:
                proc(proc.call("pyxrfdc.lib.WriteReg16", 
                               proc["rfdc"], 
                               self._base_address, 
                               proc.call("pyxrfdc.lib.XRFDC_ADC_NCO_FQWD_MID_OFFSET"), 
                               (frequency >> 16) & 0xFFFF))
            if high:
                proc(proc.call("pyxrfdc.lib.WriteReg16", 
                               proc["rfdc"], 
                               self._base_address, 
                               proc.call("pyxrfdc.lib.XRFDC_ADC_NCO_FQWD_UPP_OFFSET"),
                               (frequency >> 32) & 0xFFFF))
                
        elif isinstance(proc, Sequencer):
            if (mid and not high) or (high and not mid):
                raise ValueError("High and middle sections of the NCO"
                                 " frequency word must be set together in the"
                                 " sequencer.")
                
            frequency_base_reg = Acadia.firmware["rfdc_rts_regs"].address().value() + self.num*2
            
            if self.is_adc():
                frequency_base_reg += 16*2 
            if high:
                proc.bus_write(address=frequency_base_reg, 
                               data=(frequency >> 16) & 0xFFFFFFFF)
            if low:
                proc.bus_write(address=frequency_base_reg+1, 
                               data=frequency & 0xFFFF)
            
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
        if isinstance(proc, PythonProcessor):
            if self._base_address is None:
                raise ValueError("Insufficient information provided to"
                                 " `Channel` instance to determine"
                                 " configuration address.")
            if low:
                proc(proc.call("pyxrfdc.lib.WriteReg16", 
                               proc["rfdc"], 
                               self._base_address, 
                               proc.call("pyxrfdc.lib.XRFDC_NCO_PHASE_LOW_OFFSET"), 
                               phase & 0xFFFF))

            if high:
                proc(proc.call("pyxrfdc.lib.WriteReg16", 
                               proc["rfdc"], 
                               self._base_address, 
                               proc.call("pyxrfdc.lib.XRFDC_NCO_PHASE_UPP_OFFSET"),
                               (phase >> 16) & 0x3))
                
        elif isinstance(proc, Sequencer):
            phase_reg = Acadia.firmware["rfdc_rts_regs"].address().value() + 0x40 + self.num
            
            if self.is_adc():
                phase_reg += 16
                
            proc.bus_write(address=phase_reg, data=phase & 0x0003FFFF)
            
        raise TypeError("NCO phase can only be set in"
                        " `PythonProcessor` or `Sequencer` contexts.")
            
    @nco_synchronizer.synchronized
    def reset_nco_phase(self):
        """
        Reset the value of the NCO phase accumulator.
        """
        proc = Processor.active_processor()
        if isinstance(proc, PythonProcessor):
            if self._base_address is None:
                raise ValueError("Insufficient information provided to"
                                 " `Channel` instance to determine"
                                 " configuration address.")
            proc(proc["acadia"].RFDC_call(
                           "ResetNCOPhase",
                           self.converter_type, 
                           self.tile, 
                           self.block))
                
        elif isinstance(proc, Sequencer):
            # Do nothing, the synchronizer will set the bit in the register
            pass
            
        raise TypeError("NCO accumulator phase can only be reset in"
                        " `PythonProcessor` or `Sequencer` contexts.")

#     @property
#     def nco_frequency(self):
#         """
#         Get the NCO frequency.
#         """
#         proc = Processor.active_processor()
#         if isinstance(proc, PythonProcessor):
#             proc["mixer_settings"] = proc.call("pyxrfdc.ffi.new", 
#                                                "XRFdc_Mixer_Settings*")
#             proc(proc["acadia"].RFDC_call( 
#                       "GetMixerSettings",
#                        self.converter_type, 
#                        self.tile, 
#                        self.block, 
#                        proc["mixer_settings"]))
#             return proc["mixer_settings"].Freq
        
#         raise TypeError(f"Unable to read NCO frequency in context {proc}.")
        

#     @nco_frequency.setter
#     def nco_frequency(self, frequency):
#         """
#         Set the NCO frequency.
#         :param frequency: NCO frequency in MHz
#         :type frequency: float
#         """
#         proc = Processor.active_processor()
#         if isinstance(proc, PythonProcessor):
#             proc["mixer_settings"] = proc.call("pyxrfdc.ffi.new", 
#                                                "XRFdc_Mixer_Settings*")
#             proc(proc["acadia"].RFDC_call( 
#                       "GetMixerSettings",
#                        self.converter_type, 
#                        self.tile, 
#                        self.block, 
#                        proc["mixer_settings"]))
#             proc["mixer_settings"].Freq = frequency
#             proc(proc["acadia"].RFDC_call( 
#                       "SetMixerSettings",
#                        self.converter_type, 
#                        self.tile, 
#                        self.block, 
#                        proc["mixer_settings"]))
#         else:
#             raise TypeError("NCO frequency can only be set in MHz on the PS.")

    def set_nyquist_zone(self, nz):
        """
        Sets the Nyquist zone setting of the channel to the specified number.
        :param nz: Nyquist zone
        :type nz: int
        """
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("Nyquist zone may only be set on the PS.")
            
        reg_value = proc.call(f"pyxrfdc.lib.XRFDC_{'EVEN' if nz % 2 == 0 else 'ODD'}_NYQUIST_ZONE")
        
        proc(proc["acadia"].RFDC_call( 
                           "SetNyquistZone",
                           self.converter_type, 
                           self.tile, 
                           self.block,
                           reg_value))

    def set_decoder_mode(self, mode):
        """
        Sets the DAC decoder mode.
        :param mode: One of "Low Noise" or "High Linearity"
        :type mode: str
        """
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("Decoder mode may only be set on the PS.")
            
        if not self.is_dac():
            raise TypeError("Decoder mode may only be set for DACs.")
            
        if mode.lower() == "low noise":
            reg_value = proc.call(f"pyxrfdc.lib.XRFDC_DECODER_MAX_SNR_MODE")
        elif mode.lower() == "high linearity":
            reg_value = proc.call(f"pyxrfdc.lib.XRFDC_DECODER_MAX_LINEARITY_MODE")
        else:
            raise ValueError(f"Invalid decoder mode {mode}.")
        
        proc(proc["acadia"].RFDC_call( 
                           "SetDecoderMode",
                           self.tile, 
                           self.block,
                           reg_value))

    def set_coarse_delay(self, delay):
        """
        Sets the coarse delay of an ADC Or DAC channel.
        :param delay: Channel delay in units of the sample clock period.
        :type delay: int
        """
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("InvSincFIR may only be set on the PS.")
        
        # Create a new settings structure and initialize it with the delay
        # and immediate update (a constant which has a value of 0)
        settings = proc.call("pyxrfdc.ffi.new", "XRFdc_Coarse_Delay_Settings*", [delay, 0])
        proc(proc["acadia"].RFDC_call( 
                           "SetCoarseDelaySettings",
                            self.converter_type,
                            self.tile, 
                            self.block,
                            settings))
        
    def set_inv_sinc_FIR(self, mode):
        """
        Sets the mode of the inverse-sinc FIR filter.
        :param mode: Filter mode. May be 0 (disable), 1 (first Nyquist zone),
        or 2 (second Nyquist zone)
        :type mode: int
        """
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("InvSincFIR may only be set on the PS.")
            
        if not self.is_dac():
            raise TypeError("InvSincFIR may only be set for DACs.")
            
        if mode not in [0, 1, 2]:
            raise ValueError(f"InvSincFIR mode must be 0, 1, or 2; received {mode}.")
            
        proc(proc["acadia"].RFDC_call( 
                           "SetInvSincFIR",
                            self.tile, 
                            self.block,
                            mode))    
            

    def set_dither(self, mode):
        """
        Enables or disables ADC dithering.
        :param mode: If `True`, dithering is enabled; otherwise, it is disabled.
        :type mode: bool
        """
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("Dithering may only be set on the PS.")
            
        if not self.is_adc():
            raise TypeError("Dithering may only be set for ADCs.")
            
        proc(proc["acadia"].RFDC_call( 
                           "SetDither",
                            self.tile, 
                            self.block,
                            bool(mode)))  
        
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
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("Dithering may only be set on the PS.")
            
        if self.block is not None:
            raise ValueError("Clocking can only be configured for tiles; block must be None.")
            
        if source == "internal":
            source_value = proc.call("pyxrfdc.lib.XRFDC_INTERNAL_PLL_CLK")
        elif source == "external":
            source_value = proc.call("pyxrfdc.lib.XRFDC_EXTERNAL_CLK")
        else:
            raise ValueError(f"Invalid PLL source {source}.")
            
        proc(proc["acadia"].RFDC_call( 
                           "DynamicPLLConfig",
                            self.converter_type,
                            self.tile, 
                            source_value,
                            ref_clk_frequency,
                            sample_rate))

    def set_imr_passband(self, mode):
        """
        Sets the passband for a DAC NCO IMR filter, when enabled.
        :param mode: One of "lowpass" or "highpass"
        :type mode: str
        """
        if not self.is_dac():
            raise TypeError("IMR passband can only be set on DAC channels.")
            
        proc = Processor.active_processor()
        if not isinstance(proc, PythonProcessor):
            raise TypeError("IMR passband may only be set on the PS.")
            
        if mode.lower() == "lowpass":
            reg_value = proc.call("pyxrfdc.lib.XRFDC_DAC_IMR_MODE_LOWPASS")
        elif mode.lower() == "highpass":
            reg_value = proc.call("pyxrfdc.lib.XRFDC_DAC_IMR_MODE_HIGHPASS")
        else:
            raise ValueError(f"Invalid mode {mode}.")
        
        proc(proc["acadia"].RFDC_call( 
                           "SetIMRPassMode",
                            self.tile, 
                            self.block,
                            reg_value))
    
    @vop_dsa_synchronizer.synchronized
    def set_vop(self, vop):
        """
        Sets the variable output power (VOP) of a DAC channel.
        :param vop: VOP output current setting in uA
        :type vop: int
        """
        if not self.is_dac():
            raise TypeError("VOP can only be set on DAC channels.")
            
        proc = Processor.active_processor()
        if isinstance(proc, PythonProcessor):
            proc(proc["acadia"].RFDC_call( 
                           "SetDACVOP",
                            self.tile, 
                            self.block,
                            vop))
                
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
        if not self.is_adc():
            raise TypeError("DSA can only be set on ADC channels.")
            
        proc = Processor.active_processor()
        if isinstance(proc, PythonProcessor):
            settings = proc.call("pyxrfdc.ffi.new", "XRFdc_DSA_Settings*", [0, dsa])
            proc(proc["acadia"].RFDC_call( 
                               "SetDSA",
                                self.tile, 
                                self.block,
                                settings))
                
        elif isinstance(proc, Sequencer):
            # Do nothing, the synchronizer will manage writing the codes
            # into the registers
            pass
            
        raise TypeError("ADC DSA can only be set in"
                        " `PythonProcessor` or `Sequencer` contexts.")
    
    @tdd_mode_synchronizer.synchronized
    def set_tdd_mode(self, mode):
        """
        Set time-division duplexing (TDD) mode. Note that in the current version
        of the firmware, this will only apply for DACs.
        """
        # Do nothing. the synchronizer will calculate the register value and
        # write it
        pass
    
class PS_GPIO:
    """
    A wrapper for a Python environment running on the Processing Subsystem (PS)
    of the Zynq Ultrascale.
    """
    PS_GPIO3_IN = 0x6C >> 2
    PS_GPIO3_OUT = 0x4C >> 2
    PS_GPIO4_IN = GPIO3_IN + 1
    PS_GPIO4_OUT = GPIO3_OUT + 1
    
    @staticmethod
    def read(port):
        if isinstance(Processor.active_processor(), PythonProcessor):
            pass
        if isinstance(Processor.active_processor(), Sequencer):
            pass
        
    @staticmethod
    def write(port, data):
        if isinstance(Processor.active_processor(), PythonProcessor):
            pass
        if isinstance(Processor.active_processor(), Sequencer):
            pass
        
class PS_ZDMA:
    """
    Configures a channel of the PS ZDMA.
    """
    
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
    
    def __init__(self, mem):
        self._mem = mem
        
    def configure_transfer(self, src, dst, size, wr_only=False, fci=False):
        """
        Configures the DMA for simple transfer with options for flow control
        interface (FCI) enablement and write-only modes.
        :param src: Byte-wise source address, or write data when `wr_only` is
        `True`
        :type src: int
        :param dst: Byte-wise destination address
        :type dst: int
        :param size: Number of bytes to transfer
        :type size: int
        :param wr_only: Enables write-only mode
        :param fci: If `True`, the transfer is carried out by the FCI.
        :type fci: bool, optional
        """
        pass
    
    def start_transfer(self):
        """
        Starts the configured transfer.
        """
        pass
    
    def byte_count(self, clear=False):
        """
        :return: The total number of bytes transferred since the last clear.
        :param clear: Clear the total byte count.
        :type clear: bool, optional
        """
    
    def status(self):
        pass
        
class AXISSwitch:
    """
    Methods for controlling the Xilinx AXIS switch IP over the AXI-Lite
    interface.
    """
    MUX0_REG = 0x40 >> 2
    DISABLE_VALUE = 1 << 31
    
    CONTROL_REG = 0
    COMMIT_VALUE = 1 << 1
    
    def __init__(self, mem):
        self._mem = mem
        
    def reset(self):
        for i in range(16):
            self._mem[AXISSwitch.MUX0_REG + i] = AXISSwitch.DISABLE_VALUE
        self._mem[AXISSwitch.CONTROL_REG] = AXISSwitch.COMMIT_VALUE
            
    def disconnect(self, mi, commit=True):
        self._mem[AXISSwitch.MUX0_REG + mi] = AXISSwitch.DISABLE_VALUE
        if commit:
            self._mem[AXISSwitch.CONTROL_REG] = AXISSwitch.COMMIT_VALUE
        
    def connect(self, mi, si, commit=True):
        self._mem[AXISSwitch.MUX0_REG + mi] = si
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
    firmware = StandardFirmware()

    def __init__(self):
        self.PS = PythonProcessor()
        self.sequencer = Sequencer()
        
        # Make DMAs
        self._dac_dmas = [DMA() for i in range(16)]
        
        self._ADCDMA = ManagedResource("ADCDMA", 
                                         (DMA,), 
                                         {"OPERATORS": []},
                                         allocation_limit=4,
                                         required_parameters=["physical_channel"])
        
        self._CMACCDMA = ManagedResource("CMACCDMA", 
                                         (DMA,), 
                                         {"OPERATORS": []},
                                         allocation_limit=4,
                                         required_parameters=["physical_channel"])
        
        self.PS_GDMA = ManagedResource("PS_GDMA", 
                                         (), 
                                         {"OPERATORS": []},
                                         allocation_limit=8)
        
        self._create_cache()
        self._create_dac_arrays()
        self._create_cmacc_kernel_arrays()
        self._create_pl_ddr_arrays()
        self._create_ps_ddr_arrays()
        self._create_ocm_arrays()
        
    def _create_cache(self):
        def _cache_load(cache_self, src):
            proc = Processor.active_processor()
            if isinstance(proc, PythonProcessor):
                pass
            elif isinstance(proc, Sequencer):
                pass
            raise TypeError("")
            
        def _cache_getitem(cache_self, key):
            proc = Processor.active_processor()
            if isinstance(proc, PythonProcessor):
                pass
            elif isinstance(proc, Sequencer):
                pass
            raise TypeError("")
            
        def _cache_setitem(cache_self, key, value):
            proc = Processor.active_processor()
            if isinstance(proc, PythonProcessor):
                pass
            elif isinstance(proc, Sequencer):
                pass
            raise TypeError("")
            
        
        self.CacheArray = ManagedMemory("CacheArray", (), {},
            word_address_base=self.firmware["sequencer_bus_decoder"]["cache"].address().value(),
            byte_address_base=StandardFirmware.BRAM_CTRL_CACHE_ADDR,
            word_width=32,
            pool_size=StandardFirmware.CACHE_SIZE_BITS // 32,
            getitem_handler=make_memory_handler([PythonProcessor, Sequencer]),
            setitem_handler=make_memory_handler([PythonProcessor, Sequencer]))
        
    def _create_dac_arrays(self):
        def _dac_array_load(cache_self, src):
            proc = Processor.active_processor()
            if isinstance(proc, PythonProcessor):
                pass
            elif isinstance(proc, Sequencer):
                pass
            raise TypeError("")
            
        self.DACArray = [ManagedMemory(f"DAC{i}Array", (), {},
            word_address_base=0,
            byte_address_base=self.firmware["dac_mem_decoder"][f"dac_dma{i}_mem"].address().value()*16,
            word_width=128,
            pool_size=StandardFirmware.DAC_MEM_SIZE_BITS // 128,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor])) for i in range(16)]
        
    def _create_cmacc_kernel_arrays(self):
        self.CMACCKernelArray = [ManagedMemory(f"CMACCKernel{i}Array", (), {},
            word_address_base=0,
            byte_address_base=self.firmware["mem_decoder"][f"cmacc_dma{i}_kernel_mem"].address().value()*16,
            word_width=128,
            pool_size=StandardFirmware.DAC_MEM_SIZE_BITS // 128,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor])) for i in range(16)]
        
    def _create_pl_ddr_arrays(self):
        # PL DDR
        # The two banks of PL DDR are contiguous on the AXI network, so we can 
        # use one ManagedResource for all of the DDR
        # The resource ID refers to the offset in bytes from the start of
        # the PL C0 DDR
        self.PLDDRArray = ManagedMemory(f"PLDDRArray", (), {},
            word_address_base=StandardFirmware.DDR4_C0_ADDR,
            byte_address_base=StandardFirmware.DDR4_C0_ADDR,
            word_width=8,
            pool_size=2**33,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor]))
        
    def _create_ps_ddr_arrays(self):
        # PS DDR
        self.PSDDRArray = ManagedMemory(f"PLDDRArray", (), {},
            word_address_base=0x8_0000_0000,
            byte_address_base=0x8_0000_0000,
            word_width=8,
            pool_size=2**30,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor]))
        
    def _create_ocm_arrays(self):
        self.OCMArray = ManagedMemory(f"OCMArray", (), {},
            word_address_base=0xFFFC_0000,
            byte_address_base=0xFFFC_0000,
            word_width=8,
            pool_size=2**18,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor]))
        
    def attach(self):
        """
        Maps system memory and connects to hardware drivers.
        """        
        self._mem_file = os.open("/dev/mem", os.O_SYNC | os.O_RDWR)
        self._mem_maps = []
        
        self._attach_resource(self.Cache, mem_cast="I")
        
        self._sequencer_instruction_memory = self._attach_memory(
            address=self.firmware["mem_decoder"]["instruction_mem"].address().value()*16,
            size=StandardFirmware.INSTRUCTION_MEM_SIZE_BITS // 8)
        
        self._dac_dma_descriptor_memory = [self._attach_memory(
            address=self.firmware["mem_decoder"][f"dac_dma{i}_descriptor_mem"].address().value()*16,
            size=StandardFirmware.DAC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 64,
            mem_cast='Q') for i in range(16)]
        
        self._adc_dma_descriptor_memory = [self._attach_memory(
            address=self.firmware["mem_decoder"][f"adc_dma{i}_descriptor_mem"].address().value()*16,
            size=StandardFirmware.ADC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 64,
            mem_cast='Q') for i in range(4)]
        
        self._cmacc_dma_descriptor_memory = [self._attach_memory(
            address=self.firmware["mem_decoder"][f"cmacc_dma{i}_descriptor_mem"].address().value()*16,
            size=StandardFirmware.CMACC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 64,
            mem_cast='Q') for i in range(4)]
            
        for dac_mem in self.DACArray:
            self._attach_resource(dac_mem, mem_cast="h")
            
        for cmacc_kernel_mem in self.CMACCKernelArray:
            self._attach_resource(cmacc_kernel_mem, mem_cast="h")
                
        self._attach_resource(self.PLDDRArray)
        self._attach_resource(self.PSDDRArray)
            
        # Provide the PS with access to the Acadia runtime
        self.PS._data["acadia"] = self
            
        # Connect to the RFDC driver and initialize
        self.RFDC_init()
                
        self.PS._data["rfdc"] = self._rfdc
        
        # Connect to the GPIO registers
        self._psio_memory = self._attach_memory(0xFF0A0000, 0x400, mem_cast="I")
        
        # Connect to the ADC AXIS switch
        self._adc_axis_switch_memory = self._attach_memory(
            address=StandardFirmware.ADC_AXIS_SWITCH_ADDR, 
            size=0x1000, 
            mem_cast="I")
        
        self.adc_axis_switch = AXISSwitch(self._axis_switch_memory)
        
        # Connect to the PS GDMA
        self._ps_gdma_memory = [self._attach_memory(
            address=0xFD50_0000 + (i*0x1_0000),
            size=0x1_0000,
            mem_cast="I") for i in range(8)]
            
    def detach(self):
        """
        Unmaps all system memory.
        """
        for m in self._mem_maps:
            m.close()
        
    def _attach_resource(self, resource_manager, mem_cast='c'):
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
        resource_manager._memory = m
        
        for instance in resource_manager.instances:
            start_byte = instance.byte_address() - resource_manager.base_byte_address
            end_byte = start_byte + instance.byte_length()
            instance.memory = memoryview(m)[start_byte:end_byte].cast(mem_cast)
        
    def _attach_memory(self, address, size, mem_cast='c'):
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
            
    @classmethod
    def RFDC_call(func_name, *args, **kwargs):
        if getattr(pyxrfdc.lib, f"XRFdc_{func_name}")(cls._rfdc, *args, **kwargs) != pyxrfdc.lib.XRFDC_SUCCESS:
            raise ValueError(f"XRFdc_{func_name} failed.")
                
    @classmethod
    def RFDC_init(cls):
        """
        Initializes the RFDC library and stores a reference to the initialized
        driver instance internally. This function should only be called on live
        hardware.
        """
        import pyxrfdc as xrfdc
        cls._rfdc = xrfdc.ffi.new("XRFdc*")
        cls._device_ptr = xrfdc.ffi.new("struct metal_device*")
        
        metal_init_params = xrfdc.ffi.new("struct metal_init_params*")
        xrfdc.lib.INITIALIZE_METAL_INIT_DEFAULTS(metal_init_params)
        
        config_ptr = xrfdc.lib.XRFdc_LookupConfig(0)
        if config_ptr is xrfdc.ffi.NULL:
            raise ValueError("XRFdc_LookupConfig failed.")
            
        cls.RFDC_call("RegisterMetal", 0, cls._device_ptr)
        cls.RFDC_call("CfgInitialize", config_ptr)
        
    @classmethod
    def RFDC_status(cls):
        """
        Get the status of the converter. This function should only be called
        on live hardware.
        """
        ip_status = xrfdc.ffi.new("XRFdc_IPStatus*")
        cls.RFDC_call("GetIPStatus", ip_status)
        return ip_status
        
    @classmethod
    def RFDC_channel_status(cls, channel):
        """
        Get the status of the converter. This function should only be called
        on live hardware.
        """
        block_status = xrfdc.ffi.new("XRFdc_BlockStatus*")
        cls.RFDC_call("GetBlockStatus", 
                   channel.converter_type, 
                   channel.tile, 
                   channel.block, 
                   block_status)
        return block_status            
        
    def dma_stream(self, signal, channel):
        """
        Streams a signal from a DMA. 
        """
        # Create a DMA descriptor
        # Instruct the sequencer to write to the DMA's FIFO
        # If this Acadia instance has an active DMA synchronizer, notify it
        # that this was called
        # Otherwise, add an instruction to trigger
        pass
        
        
    