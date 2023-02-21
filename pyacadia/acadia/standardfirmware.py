__all__ = ["StandardFirmware"]

import os

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
                                   "offset": StandardFirmware.NUM_PS_GDMA ,
                                   "width": StandardFirmware.NUM_PS_GDMA,
                                   "pipeline": 2}]
        ps_gdma = BusDataport(name="ps_gdma", ports=ps_gdma_dataports)
        sequencer_bus_decoder.add(ps_gdma)
        self.add(ps_gdma)    

        # Create a register file for RFDC real-time updates and connect it to the sequencer bus
        rfdc_rts_regs = BusDevice("rfdc_rts_regs", size=256)
        sequencer_bus_decoder.add(rfdc_rts_regs, pipeline=True)

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
            create_ip(f, name="hedgehog/pl_sysref_ibufds", vlnv="xilinx.com:ip:util_ds_buf:2.1")
            set_property(f, name="hedgehog/pl_sysref_ibufds", properties={"C_SIZE": 1, "C_BUF_TYPE": "IBUFDS"})
            connect_bd_intf_net(f, "hedgehog/CLK104_PL_SYSREF", "hedgehog/pl_sysref_ibufds/CLK_IN_D")
            
            # Synchronize the SYSREF IBUFDS output first against the PL_CLK IBUFDS 
            # and then against the MMCM output
            create_ip(f, name="hedgehog/xpm_cdc_pl_sysref", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
            set_property(f, name="hedgehog/xpm_cdc_pl_sysref", properties={"CDC_TYPE": "xpm_cdc_single", "DEST_SYNC_FF": 2})
            
            connect_bd_net(f, "hedgehog/pl_clk_ibufds/IBUF_OUT", "hedgehog/xpm_cdc_pl_sysref/src_clk")
            connect_bd_net(f, "hedgehog/clk_wiz/clk_300", "hedgehog/xpm_cdc_pl_sysref/dest_clk")
            
            connect_bd_net(f, "hedgehog/pl_sysref_ibufds/IBUF_OUT", "hedgehog/xpm_cdc_pl_sysref/src_in")
            connect_bd_net(f, "hedgehog/xpm_cdc_pl_sysref/dest_out", "hedgehog/rfdc/user_sysref_dac")
            connect_bd_net(f, "hedgehog/xpm_cdc_pl_sysref/dest_out", "hedgehog/rfdc/user_sysref_adc")
            
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

            # Create an RFDCreal-time port register interface
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
        
class Acadia:
    """
    A class that implements system-wide commands for the Acadia hardware.
    Because of the heteregenous nature of the system, instructions with 
    ambiguous targets (such as writing to the system cache, which could be
    performed by the sequencer or the PS) must be carried out in processor
    contexts.
    """

    def __init__(self):
        # A stack for keeping track of the processor contexts
        # The elements are the processor objects
        self._processor_context = []
        
        # An object for carrying out the synchronization of events
        self._synchronizer = None
        
        class ProcessorContext:
            def __enter__(proc_self):
                self._processor_context.append(proc_self)
                
            def __exit__(proc_self):
                self._processor_context.pop()
        
        self.firmware = StandardFirmware()
        self.PS = type("AcadiaPS", (PythonProcessor,ProcessorContext), {})()
        self.sequencer = type("AcadiaSequencer", (Sequencer,ProcessorContext), {})()
                
        def make_memory_handler(supported_processor_types):
            def _memory_handler(op):
                if not self._processor_context:
                    raise ValueError("Interacting with managed memory outside of"
                                     " a processor context is ambiguous.")
                    
                # For all processors, we'll simply call the processor on the 
                # operation   
                active_processor = self._processor_context[-1]
                for t in supported_processor_types:
                    if isinstance(active_processor, t):
                        return active_processor(op)
                    
                raise TypeError(f"No supported processor found for operation {op}.")
            return _memory_handler
        
        # instruction memory
        self.SequencerInstructionArray = ManagedMemory("SequencerInstructionArray", (), {},
            required_parameters=["assembled_program"],
            word_address_base=0,
            byte_address_base=self.firmware["mem_decoder"]["instruction_mem"].address().value()*16,
            word_width=128,
            pool_size=StandardFirmware.INSTRUCTION_MEM_SIZE_BITS // 128,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor]))
        
        # Cache
        self.CacheArray = ManagedMemory("CacheArray", (), {},
            word_address_base=self.firmware["sequencer_bus_decoder"]["cache"].address().value(),
            byte_address_base=StandardFirmware.BRAM_CTRL_CACHE_ADDR,
            word_width=32,
            pool_size=StandardFirmware.CACHE_SIZE_BITS // 32,
            getitem_handler=make_memory_handler([PythonProcessor, Sequencer]),
            setitem_handler=make_memory_handler([PythonProcessor, Sequencer]))
        
        # DAC interfaces
        self._dac_dmas = [DMA() for i in range(16)]
        
        self.DACDMADescriptorArray = [ManagedMemory(f"DACDMA{i}DescriptorArray", (), {},
            word_address_base=0,
            byte_address_base=self.firmware["mem_decoder"][f"dac_dma{i}_descriptor_mem"].address().value()*16,
            word_width=64,
            pool_size=StandardFirmware.DAC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 64,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor])) for i in range(16)]

        self.DACArray = [ManagedMemory(f"DAC{i}Array", (), {},
            word_address_base=0,
            byte_address_base=self.firmware["dac_mem_decoder"][f"dac_dma{i}_mem"].address().value()*16,
            word_width=128,
            pool_size=StandardFirmware.DAC_MEM_SIZE_BITS // 128,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor])) for i in range(16)]
        
        # The resource id is the index of the DMA
        self._ADCDMA = ManagedResource("ADCDMA", 
                                         (DMA,), 
                                         {"OPERATORS": []},
                                         allocation_limit=4,
                                         required_parameters=["physical_channel"])
        
        self.ADCDMADescriptorArray = [ManagedMemory(f"ADCDMA{i}DescriptorArray", (), {},
            word_address_base=0,
            byte_address_base=self.firmware["mem_decoder"][f"adc_dma{i}_descriptor_mem"].address().value()*16,
            word_width=64,
            pool_size=StandardFirmware.ADC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 64,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor])) for i in range(4)]
            
        # The resource id is the index of the DMA
        self._CMACCDMA = ManagedResource("CMACCDMA", 
                                         (DMA,), 
                                         {"OPERATORS": []},
                                         allocation_limit=4,
                                         required_parameters=["physical_channel"])
        
        self.CMACCDMADescriptorArray = [ManagedMemory(f"CMACCDMA{i}DescriptorArray", (), {},
            word_address_base=0,
            byte_address_base=self.firmware["mem_decoder"][f"cmacc_dma{i}_descriptor_mem"].address().value()*16,
            word_width=64,
            pool_size=StandardFirmware.CMACC_DMA_DESCRIPTOR_MEM_SIZE_BITS // 64,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor])) for i in range(4)]
        
        self.CMACCKernelArray = [ManagedMemory(f"CMACCKernel{i}Array", (), {},
            word_address_base=0,
            byte_address_base=self.firmware["mem_decoder"][f"cmacc_dma{i}_kernel_mem"].address().value()*16,
            word_width=128,
            pool_size=StandardFirmware.DAC_MEM_SIZE_BITS // 128,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor])) for i in range(16)]
        
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
        
        # PS DDR
        self.PSDDRArray = ManagedMemory(f"PLDDRArray", (), {},
            word_address_base=0x8_0000_0000,
            byte_address_base=0x8_0000_0000,
            word_width=8,
            pool_size=2**30,
            getitem_handler=make_memory_handler([PythonProcessor]),
            setitem_handler=make_memory_handler([PythonProcessor]))
        
        # TODO: find a good way to implement single-bit PSIO writes for the 
        # sequencer
        def _PSIO_word_read(self, data):
            """
            Reads data from a PS GPIO port.
            """
            if not self._processor_context:
                raise TypeError("Calling `PSIO_word_read` is ambiguous outside"
                                " of a ProcessorContext.")
            proc = self._processor_context[-1]
            if isinstance(proc, Sequencer):
                # The sequencer reads from the PS GPIO out port
                return proc.bus_read(self.firmware["sequencer_bus_decoder"][f"ps_gpio{3+psio_word_self._resource_id}"])
            if isinstance(proc, PythonProcessor):
                # The PS reads from the PS GPIO in port
                return Operation("getitem", psio_word_self.memory_in, 0)

            raise TypeError(f"PS GPIO word read not defined for processor {proc}.")

        def _PSIO_word_write(psio_word_self, data):
            """
            Writes data to a PS GPIO port.
            """
            if not self._processor_context:
                raise TypeError("Calling `PSIO_word_write` is ambiguous outside"
                                " of a ProcessorContext.")
            proc = self._processor_context[-1]
            if isinstance(proc, Sequencer):
                # The sequencer writes to the PS GPIO in port
                return proc.bus_write(address=self.firmware["sequencer_bus_decoder"][f"ps_gpio{3+psio_word_self._resource_id}"], 
                                      data=data)
            if isinstance(proc, PythonProcessor):
                # The PS writes to the PS GPIO out port
                return proc(Operation("setitem", psio_word_self.memory_out, 0, data))

            raise TypeError(f"PS GPIO word write not defined for processor {proc}.")
            
        self.PSIOWord = ManagedResource(f"PSIOWord", 
                                         (), 
                                         {"OPERATORS": [],
                                          "read": _PSIO_word_read,
                                          "write": _PSIO_word_write},
                                         allocation_limit=2)
        
        @dataclass
        class Channel:
            tile: int = None
            block: int = None
            num: int = None
            bank: int = None
            converter_type: int = None

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

            def configure_nco(self, frequency=None, phase=None, word=False, phase_reset=False):
                """
                Configure the NCO for the channel. If `word` is `True`, the 
                provided values are understood to be integer words intended to be
                written directly to the RFDC registers.
                """
                pass

            def get_nco_settings(self):
                pass

            # Convenience functions
            @property
            def status(self):
                """
                Get the status of the converter.
                """
                pass

            @property
            def nco_frequency(self):
                pass

            @nco_frequency.setter
            def nco_frequency(self, frequency):
                pass

            @property
            def nco_phase(self):
                pass

            @nco_phase.setter
            def nco_phase(self, phase):
                pass

            @property
            def update_event(self):
                pass

            @update_event.setter
            def update_event(self, v):
                pass

            @property
            def nyquist_zone(self):
                pass

            @nyquist_zone.setter
            def nyquist_zone(self, nz):
                pass

            @property
            def decoder_mode(self):
                pass

            @decoder_mode.setter
            def decoder_mode(self):
                pass

            @property
            def current(self):
                pass

            @current.setter
            def current(self, vop):
                pass

            @property
            def attenuation(self):
                pass

            @attenuation.setter
            def attenuation(self, dsa):
                pass

            @property
            def coarse_delay(self):
                pass

            @coarse_delay.setter
            def coarse_delay(self, delay):
                pass

            @property
            def dither(self):
                pass

            @dither.setter
            def dither(self, v):
                pass

            @property
            def imr_passband(self):
                pass

            @imr_passband.setter
            def imr_passband(self, v):
                pass
        
        class DAC(Channel):
            def __init__(dac_self, *args, **kwargs):
                super().__init__(converter_type=xrfdc.XRFDC_DAC_TILE, *args, **kwargs)

        class ADC(Channel):
            def __init__(dac_self, *args, **kwargs):
                super().__init__(converter_type=xrfdc.XRFDC_ADC_TILE, *args, **kwargs)
        
    def attach(self):
        """
        Maps system memory and connects to hardware drivers.
        """        
        self._hardware.attach_resource(self.Cache, mem_cast="I")
        self._hardware.attach_resource(self.SequencerInstructionArray)
            
        for dma_mem in self.DACDMADescriptorMemory:
            self._hardware.attach_resource(dma_mem, mem_cast="Q")
            
        for dac_mem in self.DACArray:
            self._hardware.attach_resource(dma_mem, mem_cast="h")
                
        for dma_mem in self.ADCDMADescriptorMemory:
            self._hardware.attach_resource(dma_mem, mem_cast="Q")
            
        for dma_mem in self.CMACCDMADescriptorMemory:
            self._hardware.attach_resource(dma_mem, mem_cast="Q")
            
        for cmacc_kernel_mem in self.CMACCKernelArray:
            self._hardware.attach_resource(dma_mem, mem_cast="h")
                
        self._hardware.attach_resource(self.PLDDRArray)
        self._hardware.attach_resource(self.PSDDRArray)
            
        # PS GPIO
        self._psio_memory = self._hardware.attach_memory(0xFF0A0000, 0x400, mem_cast="I")
        
        for io in self.PSIOWord.instances:
            # Map the PS GPIO input and output registers
            in_reg = (0x6C >> 2) + io._resource_id
            io.memory_in = self._psio_memory[in_reg:in_reg+1]
            out_reg = (0x4C >> 2) + io._resource_id
            io.memory_out = self._psio_memory[out_reg:out_reg+1]
            
    def deattach(self):
        """
        Unmaps all system memory.
        """
        self.Cache._memory.close()
        self.sequencer._Instruction._memory.close()
        for dac,dma in enumerate(self._dac_dmas):
            dma._Instruction._memory.close()
        for dac,mem in enumerate(self._dac_mem):
            mem._memory.close()
        for adc,dma in enumerate(self._dac_dmas):
            dma._Instruction._memory.close()
        for cmacc,dma in enumerate(self._CMACCDMA.instances):
            dma._Instruction._memory.close()
        for cmacc,mem in enumerate(self._cmacc_kernel_mem):
            mem._memory.close()
        self.DDRMemory._memory.close()
        self._psio_memory.close()
        
        self._mem_file.close()
    
    class Synchronizer:
        """
        A context manager for implementing the synchronization of system events.
        """
        def __new__(cls, *args, **kwargs):
            """
            When new instances are created, they are attached to the 
            :class:`Acadia` instance.
            """
            instance = super().__new__(*args, **kwargs)
            self._synchronizer = instance
            return instance
        
        def __init__(synchronizer_self, blocking=True):
            """
            :param blocking: If `True`, program execution will halt until all
            processes inside the block have completed. This may result in
            differewnt behavior depending on the contents of the block.
            :type blocking: bool, optional
            """
            synchronizer_self._blocking = True
        
        def __enter__(synchronizer_self):
            synchronizer_self._events = []
            
        def __exit__(synchronizer_self):
            # Carry out any closing behavior (e.g., triggering)
            if synchronizer_self._blocking:
                synchronizer_self.await_completion()
        
        def await_completion(synchronizer_self):
            """
            Halts execution until the condition for synchronization has been 
            met. The exact behavior will be determined by the type of captured
            events, as determined by examining the first event and enforcing
            the ability to synchronize with it for the rest of the block.
            """
            pass
        
        def notify(synchronizer_self, event_type, **kwargs):
            """
            Notify the synchronizer that an event relevant to synchronization
            has occurred.
            """
            pass
            
        
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
        
    def configure_nco(self, frequency=None, phase=None, frequency_update=0b111):
        """
        Configures an NCO of the RF data converters.
        """
        pass
        
    