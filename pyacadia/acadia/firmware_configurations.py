CONFIG_200 = {
    "clocks": {
        # The primary clock rate of the logic
        "CLK104_PL_CLK": 200_000_000,
        "IDT_8A34001_Q1": 128_000_000,
        "IDT_8A34001_Q2": 128_000_000,
        "IDT_8A34001_Q3": 128_000_000,
        "IDT_8A34001_Q8": 128_000_000,
        "IDT_8A34001_Q11": 128_000_000,
        "IDT_8A34001_Q7": 128_000_000,
    },
    
    # Memory segments physically located in the PS
    "memory": {
        "HPC0_LPS_OCM": {
            "address": 0x00_FF00_0000, 
            "size_bits": 8 * 2**18, 
            "segment": "/ps/SAXIGP0/HPC0_LPS_OCM"
        },

        "HPC1_LPS_OCM": {
            "address": 0x01_FF00_0000, 
            "size_bits": 8 * 2**18, 
            "segment": "/ps/SAXIGP1/HPC1_LPS_OCM"
        },

        "HPC0_DDR_LOW": {
            "address": 0x04_0000_0000, 
            "size_bits": 8 * 2**31, 
            "segment": "/ps/SAXIGP0/HPC0_DDR_LOW"
        },

        "HPC1_DDR_LOW": {
            "address": 0x05_0000_0000, 
            "size_bits": 8 * 2**31, 
            "segment": "/ps/SAXIGP1/HPC1_DDR_LOW"
        },

        "HPC0_DDR_HIGH": {
            "address": 0x08_0000_0000, 
            "size_bits": 8 * 2**35, 
            "segment": "/ps/SAXIGP0/HPC0_DDR_HIGH"
        },

        "HPC1_DDR_HIGH": {
            "address": 0x18_0000_0000, 
            "size_bits": 8 * 2**35, 
            "segment": "/ps/SAXIGP1/HPC1_DDR_HIGH"
        },

        "ddr4_c0": {
            "address": 0x40_0000_0000, 
            "size_bits": 8 * 2**32, 
            "segment": "PLDDR/DDR4_C0_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK"
        },

        "ddr4_c1": {
            "address": 0x41_0000_0000, 
            "size_bits": 8 * 2**32, 
            "segment": "PLDDR/DDR4_C1_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK"
        },
    },

    # The clock rate for the sequencer memory crossbar
    "sequencer_memory_crossbar": {
        "clock": "PS_AXI_clk"
    },

    "ps_axi_slaves": [
        "PS_S_AXI_HPC0", 
        "PS_S_AXI_HPC1", 
        # "PS_S_AXI_HP0",
        # "PS_S_AXI_HP1",
        "DDR4_C0_S_AXI",
        "DDR4_C1_S_AXI"
    ],

    "sequencer_cache_memory": {
        "clock": "PS_AXI_clk",
        "reset": f"main/PS_AXI_clk_peripheral_aresetn",
        "axi_master": "PS", # either "PS" or "crossbar"
        "primitive": "block",
        "address": 0x00_B000_0000, 
        "segment": "s_axi/reg0",
        "size_bits": 2**20,
        "bus_pipeline": False,
        "synchronous": False,
        "controller_width": 128,
        "controller_port_input_pipeline": 0,
        "controller_port_output_pipeline": 1,
        "bus_port_input_pipeline": 0,
        "bus_port_output_pipeline": 1
    },

    "sequencer_instruction_memory": {
        "clock": "seq_clk",
        "reset": f"main/proc_sys_reset_seq_clk/peripheral_aresetn",
        "primitive": "block",
        "address": 0x00_A880_0000, 
        "segment": "s_axi/reg0",
        "size_bits": 128*4096,
        "synchronous": False,
        "controller_width": 128,
        "controller_port_input_pipeline": 2,
        "controller_port_output_pipeline": 2,
        "sequencer_port_input_pipeline": 0,
        "sequencer_port_output_pipeline": 0
    },

    "dac_tile0_sample_memory": {
        "primitive": "ultra",
        "interface_width": 128,
        "controller_width": 128,
        "address": 0x00_A800_0000,
        "size_bits": 2**20,
        "segment": "s_axi/reg0",
        "synchronous": True,
        "controller_port_input_pipeline": 2,
        "controller_port_output_pipeline": 2,
        "dac_port_input_pipeline": 1,
        "dac_port_output_pipeline": 2
    },

    "dac_tile1_sample_memory": {
        "primitive": "ultra",
        "interface_width": 128,
        "controller_width": 128,
        "address": 0x00_A808_0000,
        "size_bits": 2**20,
        "segment": "s_axi/reg0",
        "synchronous": True,
        "controller_port_input_pipeline": 2,
        "controller_port_output_pipeline": 2,
        "dac_port_input_pipeline": 1,
        "dac_port_output_pipeline": 2
    },

    "dac_tile2_sample_memory": {
        "primitive": "ultra",
        "interface_width": 128,
        "controller_width": 128,
        "address": 0x00_A810_0000,
        "size_bits": 2**20,
        "segment": "s_axi/reg0",
        "synchronous": True,
        "controller_port_input_pipeline": 2,
        "controller_port_output_pipeline": 2,
        "dac_port_input_pipeline": 1,
        "dac_port_output_pipeline": 2
    },

    "dac_tile3_sample_memory": {
        "primitive": "ultra",
        "interface_width": 128,
        "controller_width": 128,
        "address": 0x00_A818_0000,
        "size_bits": 2**20,
        "segment": "s_axi/reg0",
        "synchronous": True,
        "controller_port_input_pipeline": 2,
        "controller_port_output_pipeline": 2,
        "dac_port_input_pipeline": 1,
        "dac_port_output_pipeline": 2
    },
    
    "stream_processing_path": {
        # The maximum allowed width of inputs to be connected to the stream
        # processing path.
        "width": 128,
            
        # The inputs to the stream processing path. There may be a total of 16 
        # inputs (limited by the number of available inputs on Xilinx's AXIS 
        # switch).
        # 
        # Available inputs are:
        # "ADC": The DMA output of the specified ADC. 
        #     All ADCs not specified here will be connected to a switch, whose
        #     outputs may be specified as capture stream inputs using the 
        #     "ADC_SWITCHx" specifier. 
        # "ADC_switch": An output of the ADC switch. The number of specifiers
        #     included here determines the number of outputs present on the
        #     switch, and if none are specified the switch is omitted and all
        #     ADCs not specified in this list are disconnected
        # "bulk": A MM2S DataMover is added to the bulk memory SmartConnect. 
        #     Note that the total number of processing modules, bulk inputs, and adders
        #     is 15 (limited by the available number of slave ports on the bulk
        #     AXI SmartConnect, with one port reserved for the PS).
        # "config": A MM2S DataMover is added to the config SmartConnect. 
        # "sequencer": A MM2S DataMover is added to the sequencer crossbar
        "inputs": [
            {"kind": "ADC", 
             "channel": 0},
            {"kind": "ADC", 
             "channel": 2},
            {"kind": "ADC", 
             "channel": 4},
            {"kind": "ADC", 
             "channel": 6},
            {"kind": "ADC_switch"},
            {"kind": "ADC_switch"},
            {"kind": "memory",
             "AXI_clock": "PS_AXI_clk",
             "AXI_reset": "main/PS_AXI_clk_peripheral_aresetn",
             "FIFO_depth": 512,
             "datamover_controller_bus_pipeline": True},
            {"kind": "memory",
             "AXI_clock": "PS_AXI_clk",
             "AXI_reset": "main/PS_AXI_clk_peripheral_aresetn",
             "FIFO_depth": 512,
             "datamover_controller_bus_pipeline": True},
        ],
        
        # All of the inputs to the stream processing path pass through an AXIS
        # switch. Some of the inputs to this switch will be driven directly by 
        # an ADC output, but there are too many ADCs to directly connect all of
        # them (and it's unlikely that they'll all be needed at the same time 
        # anyway). Therefore, there is an additional switch that multiplexes 
        # all of the ADCs that are not directly connected to the stream 
        # processing path input switch. It provides a small number of outputs, 
        # which are then connected to the stream processing path input switch. 
        "input_switch": {
            "axi_address": 0x00_A840_0000, 
            "axi_size_bits": 8 * 2**18,
            "axi_segment": "S_AXI_CTRL/Reg",
        },
        
        "adc_input_switch": {
            "axi_address": 0x00_A850_0000, 
            "axi_size_bits": 8 * 2**18,
            "axi_segment": "S_AXI_CTRL/Reg",
        },
        
        # The stream processing modules present in the stream processing path.
        # All of the inputs specified above are connected to a switch, and the 
        # outputs of the switch are connected to the stream inputs of these 
        # modules. All of the modules have their own DataMover at the output 
        # for writing the results to a location on an AXI network. 
        # 
        # Note that the total number of modules is 15 (this is limited by 
        # the available number of slave ports on any SmartConnect, with one
        # slave port reserved for the PS). 
        "modules": [
            {"kind": "fifo",
             "AXI_width": 256,
             "AXI_clock": "PS_AXI_clk",
             "AXI_reset": "main/PS_AXI_clk_peripheral_aresetn",
             "FIFO_depth": 512,
             "FIFO_primitive": "auto",
             "registers_bus_pipeline": True,
             "datamover_burst_size": 128,
             "datamover_controller_bus_pipeline": True}, 
            {"kind": "fifo",
             "AXI_width": 256,
             "AXI_clock": "PS_AXI_clk",
             "AXI_reset": "main/PS_AXI_clk_peripheral_aresetn",
             "FIFO_depth": 512,
             "FIFO_primitive": "auto",
             "registers_bus_pipeline": True,
             "datamover_burst_size": 128,
             "datamover_controller_bus_pipeline": True}, 
            {"kind": "cmacc",
             "AXI_width": 64,
             "AXI_clock": "PS_AXI_clk",
             "AXI_reset": "main/PS_AXI_clk_peripheral_aresetn",
             "FIFO_depth": 512,
             "FIFO_primitive": "auto",
             "registers_bus_pipeline": False,
             "datamover_burst_size": 128,
             "datamover_controller_bus_pipeline": True,
             "kernel_memory_depth": 2048},
            {"kind": "cmacc",
             "AXI_width": 64,
             "AXI_clock": "PS_AXI_clk",
             "AXI_reset": "main/PS_AXI_clk_peripheral_aresetn",
             "FIFO_depth": 512,
             "FIFO_primitive": "auto",
             "registers_bus_pipeline": False,
             "datamover_burst_size": 128,
             "datamover_controller_bus_pipeline": True,
             "kernel_memory_depth": 2048},
            {"kind": "cmacc",
             "AXI_width": 64,
             "AXI_clock": "PS_AXI_clk",
             "AXI_reset": "main/PS_AXI_clk_peripheral_aresetn",
             "FIFO_depth": 512,
             "FIFO_primitive": "auto",
             "registers_bus_pipeline": False,
             "datamover_burst_size": 128,
             "datamover_controller_bus_pipeline": True,
             "kernel_memory_depth": 2048},
            {"kind": "cmacc",
             "AXI_width": 64,
             "AXI_clock": "PS_AXI_clk",
             "AXI_reset": "main/PS_AXI_clk_peripheral_aresetn",
             "FIFO_depth": 512,
             "FIFO_primitive": "auto",
             "registers_bus_pipeline": False,
             "datamover_burst_size": 128,
             "datamover_controller_bus_pipeline": True,
             "kernel_memory_depth": 2048},
        ],
        
        # Some shared settings for any CMACCs used
        # If there are no CMACCs, these are ignored
        "cmacc_kernel_memory_controller": {
            "base_address": 0x00_A860_0000, 
            "segment": "s_axi/reg0",
            "controller_width": 32,
            "controller_port_input_pipeline": 2,
            "controller_port_output_pipeline": 2,
        }
    },

    "pl_sysref_capture": {
        "axi_address": 0x00_A890_0000, 
        "axi_size_bits": 8 * 2**10,
        "axi_segment": "sysref_count/reg0",
    },

    "rfdc": {
        # is the axi config port of the rfdc synchronous to the sequencer?
        "axi_synchronous": True,

        # if axi_synchronous is true then this must be the sequencer clock frequency
        "axi_clk_freq_hz": 200e6,
        
        "axi_address": 0x00_A870_0000, 
        "axi_size_bits": 8 * 2**18,
        "axi_segment": "s_axi/reg",

        "dac": {
            "channel_interface_width": [128]*16,
            "channel_pipeline_stages": [1]*16,
            "channel_nyquist_zone": [1]*16,
            "dma_fifo_depth": [32]*16,
            "dma_fifo_latency": [3]*16,
            "tile_mts": [True]*4,
            "tile_sample_rate_hz": [6.4e9]*4,
            "tile_pll": [True]*4,
            "tile_clk_source": [6]*4,
            "tile_refclk_freq_hz": [200e6]*4,
            "tile_distribute_clk": [0, 0, 1, 0],
            "tile_vop": [20.0]*4,
        },

        "adc": {
            "channel_interface_width": [128]*16,
            "channel_pipeline_stages": [1]*16,
            "channel_dither": [False]*16,
            "dma_fifo_depth": [32]*16,
            "dma_fifo_latency": [3]*16,
            "tile_mts": [True]*4,
            "tile_sample_rate_hz": [2.4e9]*4,
            "tile_pll": [True]*4,
            "tile_clk_source": [2]*4,
            "tile_refclk_freq_hz": [200e6]*4,
            "tile_distribute_clk": [0, 0, 1, 0],
            "tile_dsa": [0]*4
        }    
    },

    "ps_gpio": {
        "sysfs_offset": 334 + 3*26,
        "sequencer_nrst": 89, 
        "sequencer_done": 88, 
        "clk104_sync": 86,
        "clk104_spi1": 85,
        "clk104_spi0": 84,
        "ddr4_c0_sys_rst": 83,
        "ddr4_c1_sys_rst": 82,
        "ddr4_c0_cal_complete": 81,
        "ddr4_c1_cal_complete": 80,
        "sequencer_bus_gpio_in": 64,
        "sequencer_bus_gpio_out": 68,
    },

    "sequencer_bus": {
        "decoder_pipeline_miso": True,

        "dma_pipeline": [True]*32,

        "io_dataport": {
            "bus_pipeline": True,
            "ADCIO_pipeline": 2,
            "DACIO_pipeline": 2
        },

        "dma_running_dataport": {
            "bus_pipeline": True,
            "pipeline": [1]*32,
        },

        "dma_trigger_dataport": {
            "bus_pipeline": False,
            "pipeline": [1]*32,
        },

        "rfdc_rts": {
            "bus_pipeline": True
        },

        "gpio": {
            "bus_pipeline": True
        },

        "sequencer_done_dataport": {
            "bus_pipeline": True,
            "pipeline": 2,
        },

        "ps_gdma_irq_dataport": {
            "bus_pipeline": True,
            "pipeline": 2,
        },

        "zdma_controller": {
            "bus_pipeline": True
        },

        "clk104_sync_dataport": {
            "bus_pipeline": True,
            "pipeline": 2
        }
    }
}
