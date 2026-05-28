__all__ = ["Firmware"]

import os
import json

from .hdl import BusDevice, BusDecoder, BusDataport, AXIMemoryArray, connect_bd_net, connect_bd_intf_net, create_ip, create_module, create_concatenator, create_slice, set_property, assign_bd_address, exclude_bd_addr_seg
from acadia.utils import next_highest_power_of_2

class Firmware:
    """
    The standard Acadia firmware. Handcrafted, artisanal FPGA logic with notes
    of silicon and garnished with main quills.
    """

    NUM_DACS = 16
    NUM_ADCS = 16

    def __init__(self, config):
        """
        :param config: Dictionary containing firmware constants
        :type config: dict
        :param directory: Directory in which the project should be created
        :type directory: str
        """
        self.config = config
        self._populate()

    def __getitem__(self, key):
        return self.config.__getitem__(key)

    def write(self, directory):
        """
        Create the HDL and TCL scripts from the internal configuration.
        
        :param directory: The target directory, which will be created if it 
            does not exist.
        :type directory: str
        """

        if not os.path.exists(directory):
            os.mkdir(directory)

        print("Generating HDL...")

        self._hdl_filename = os.path.join(directory, "python_modules.vhd")
        with open(self._hdl_filename, "w") as f:
            for module in self._hdl_modules:
                f.write(module.generate_hdl() + '\n')

        print("Generating TCL...")
        self.write_main_tcl(directory,
                                os.path.join(directory, "main.tcl"),
                                os.path.join(directory, "main.xdc"))

        library_dir = "/" + os.path.join(*(os.path.abspath(__file__).split("/")[:-3]))

        project_cmd = (f"vivado -mode tcl"
            f" -source {os.path.join(library_dir, 'logic', 'make_project.tcl')}"
            f" -tclargs"
            f" --project_dir {directory}"
            f" --origin_dir {os.path.join(library_dir, 'logic', 'src')}")
        
        print("Writing JSON configuration file...")

        with open(os.path.join(directory, "firmware_config.json"), "w") as f:
            json.dump(self.config, f)

        print("Execute the following command to create a Vivado project:\n"
              f"   {project_cmd}")


    def _populate(self):
        """
        Create objects abstracting HDL modules.
        """    
        
        self._hdl_modules = []
        
        # Create a primary decoder for the sequencer bus
        self.sequencer_bus_decoder = BusDecoder("sequencer_bus_decoder", 
                                           pipeline_miso=self.config["sequencer_bus"]["decoder_pipeline_miso"])
        self._hdl_modules.append(self.sequencer_bus_decoder)

        # Create split dataport for triggering and monitoring the DMA and for setting continue signals
        _bit = 0
        _dma_trigger_ports = []
        _dma_running_ports = []

        for label,count in [("dac", self.NUM_DACS), ("adc", self.NUM_ADCS)]:
            for idx in range(count):
                _dma_trigger_ports += [
                    {"name": f"{label}{idx}_dma", 
                    "direction": BusDataport.OUTPUT, 
                    "offset": _bit,
                    "width": 1,
                    "gate": BusDataport.GATE_RESET,
                    "pipeline": self.config["sequencer_bus"]["dma_trigger_dataport"]["pipeline"][_bit]}]

                _dma_running_ports += [
                    {"name": f"{label}{idx}_dma", 
                    "direction": BusDataport.INPUT, 
                    "offset": _bit,
                    "width": 1,
                    "pipeline": self.config["sequencer_bus"]["dma_running_dataport"]["pipeline"][_bit]}]
                
                regs_port = BusDevice(name=f"{label}{idx}_dma", size=2)
                self.sequencer_bus_decoder.add(regs_port, pipeline=self.config["sequencer_bus"]["dma_pipeline"][_bit])

                _bit += 1

        self.dma_trigger = BusDataport(name="dma_trigger_dataport", ports=_dma_trigger_ports)
        self.sequencer_bus_decoder.add(self.dma_trigger, pipeline=self.config["sequencer_bus"]["dma_trigger_dataport"]["bus_pipeline"])
        self._hdl_modules.append(self.dma_trigger)

        self.dma_running = BusDataport(name="dma_running_dataport", ports=_dma_running_ports)
        self.sequencer_bus_decoder.add(self.dma_running, pipeline=self.config["sequencer_bus"]["dma_running_dataport"]["bus_pipeline"])
        self._hdl_modules.append(self.dma_running)
        
        # Parse the input path in order to determine how things get written
        self._memory_smartconnect_masters = 1
        
        # At the same time, we'll create DataMover controllers
        self._datamover_controllers = []
        for idx,inp in enumerate(self.config["stream_processing_path"]["inputs"]):
            if inp["kind"] == "memory":
                device = BusDevice(f"input{idx}_datamover_controller", size=4)
                self._datamover_controllers.append(device)
                self.sequencer_bus_decoder.add(device, pipeline=inp["datamover_controller_bus_pipeline"])
                self._memory_smartconnect_masters += 1
                
        for idx,module in enumerate(self.config["stream_processing_path"]["modules"]):
            # TODO: add a way to make modules that need more than 16 registers
            registers = BusDevice(f"module{idx}_registers", size=16)
            self.sequencer_bus_decoder.add(registers, pipeline=module["registers_bus_pipeline"])
            
            device = BusDevice(f"module{idx}_s2mm_datamover_controller", size=4)
            self._datamover_controllers.append(device)
            self.sequencer_bus_decoder.add(device, pipeline=module["datamover_controller_bus_pipeline"])
            
            self._memory_smartconnect_masters += 1
                
        # Create a register file for GPIO
        self.gpio = BusDevice("gpio", size=4)
        self.sequencer_bus_decoder.add(self.gpio, pipeline=self.config["sequencer_bus"]["gpio"]["bus_pipeline"])

        sequencer_done_dataport = [{
            "name": f"done",
            "direction": BusDataport.OUTPUT,
            "offset": 0,
            "width": 1,
            "gate": BusDataport.GATE_REGCE,
            "pipeline": self.config["sequencer_bus"][f"sequencer_done_dataport"]["pipeline"]
        }]

        self.sequencer_done_dataport = BusDataport(name=f"sequencer_done_dataport", ports=sequencer_done_dataport)
        self.sequencer_bus_decoder.add(self.sequencer_done_dataport, pipeline=self.config["sequencer_bus"][f"sequencer_done_dataport"]["bus_pipeline"])
        self._hdl_modules.append(self.sequencer_done_dataport)

        _ps_gdma_irq_dataports = [{
            "name": f"gdma_irq",
            "direction": BusDataport.INPUT,
            "offset": 0,
            "width": 8,
            "pipeline": self.config["sequencer_bus"]["ps_gdma_irq_dataport"]["pipeline"]
        }]

        self.ps_gdma_irq = BusDataport(name="ps_gdma_irq_dataport", ports=_ps_gdma_irq_dataports)
        self.sequencer_bus_decoder.add(self.ps_gdma_irq, pipeline=self.config["sequencer_bus"]["ps_gdma_irq_dataport"]["bus_pipeline"])
        self._hdl_modules.append(self.ps_gdma_irq)

        # Create a register file for RFDC real-time updates and connect it to the sequencer bus
        self.rfdc_rts_regs = BusDevice("rfdc_rts_regs", size=256)
        self.sequencer_bus_decoder.add(self.rfdc_rts_regs, pipeline=self.config["sequencer_bus"]["rfdc_rts"]["bus_pipeline"])

        # Create a register file for interacting with the PS GDMA
        self.zdma_controller = BusDevice("zdma_controller", size=64)
        self.sequencer_bus_decoder.add(self.zdma_controller, 
                                  pipeline=self.config["sequencer_bus"]["zdma_controller"]["bus_pipeline"])

        _clk104_sync_in_dataports = [
            {"name": f"sync",
            "direction": BusDataport.OUTPUT,
            "offset": 0,
            "width": 1,
            "gate": BusDataport.GATE_REGCE,
            "pipeline": self.config["sequencer_bus"]["clk104_sync_dataport"]["pipeline"]}]

        self.clk104_sync_in = BusDataport(name="clk104_sync_in", ports=_clk104_sync_in_dataports)
        self.sequencer_bus_decoder.add(self.clk104_sync_in, 
                                  pipeline=self.config["sequencer_bus"]["clk104_sync_dataport"]["bus_pipeline"])
        self._hdl_modules.append(self.clk104_sync_in)

        # Create cache and connect it to the sequencer bus
        self.cache = BusDevice("cache", size=self.config["sequencer_cache_memory"]["size_bits"] // 32)
        self.sequencer_bus_decoder.add(self.cache, 
                                  pipeline=self.config["sequencer_cache_memory"]["bus_pipeline"])
        
        # Add GTY controller
        self.gty_controller = BusDevice("gty_controller", size=16)
        self.sequencer_bus_decoder.add(self.gty_controller, pipeline=True)

        # Assign decoder addresses
        self.sequencer_bus_decoder.assign_address(0)

        # Create AXI-controlled memories

        # Create an AXI BRAM Controller wrapper for the cache
        self.cache_memory_controller = AXIMemoryArray("cache", 
            size_bits=self.config["sequencer_cache_memory"]["size_bits"], 
            width=32, 
            elements=1, 
            axi_id_width=17, # 1 bit needed for AXI crossbar, 16 from PS master
            read_only=False,
            use_rst=False,
            synchronous=self.config["sequencer_cache_memory"]["synchronous"],
            primitive=self.config["sequencer_cache_memory"]["primitive"],
            controller_width=self.config["sequencer_cache_memory"]["controller_width"],
            controller_port_input_pipeline=self.config["sequencer_cache_memory"]["controller_port_input_pipeline"],
            controller_port_output_pipeline=self.config["sequencer_cache_memory"]["controller_port_output_pipeline"],                              
            user_port_input_pipeline=self.config["sequencer_cache_memory"]["bus_port_input_pipeline"],
            user_port_output_pipeline=self.config["sequencer_cache_memory"]["bus_port_output_pipeline"])
        self._hdl_modules.append(self.cache_memory_controller)

        self.instruction_memory_controller = AXIMemoryArray("instruction", 
            size_bits=self.config["sequencer_instruction_memory"]["size_bits"], 
            width=128, 
            elements=1, 
            axi_id_width=17, # 1 bit needed for AXI crossbar, 16 from PS master
            read_only=True,
            use_rst=False,
            primitive=self.config["sequencer_instruction_memory"]["primitive"], 
            controller_width=self.config["sequencer_instruction_memory"]["controller_width"], 
            synchronous=self.config["sequencer_instruction_memory"]["synchronous"],
            controller_port_input_pipeline=self.config["sequencer_instruction_memory"]["controller_port_input_pipeline"],
            controller_port_output_pipeline=self.config["sequencer_instruction_memory"]["controller_port_output_pipeline"],
            user_port_input_pipeline=self.config["sequencer_instruction_memory"]["sequencer_port_input_pipeline"],
            user_port_output_pipeline=self.config["sequencer_instruction_memory"]["sequencer_port_output_pipeline"])
        self._hdl_modules.append(self.instruction_memory_controller)

        self.dac_tile_memory_controllers = []
        for i in range(4):
            memory_controller = AXIMemoryArray(f"dac_tile{i}", 
                size_bits=self.config[f"dac_tile{i}_sample_memory"]["size_bits"], 
                width=self.config[f"dac_tile{i}_sample_memory"]["interface_width"],
                elements=4, 
                read_only=True,
                use_rst=True,
                controller_width=self.config[f"dac_tile{i}_sample_memory"]["controller_width"],
                synchronous=self.config[f"dac_tile{i}_sample_memory"]["synchronous"],
                primitive=self.config[f"dac_tile{i}_sample_memory"]["primitive"], 
                controller_port_input_pipeline=self.config[f"dac_tile{i}_sample_memory"]["controller_port_input_pipeline"],
                controller_port_output_pipeline=self.config[f"dac_tile{i}_sample_memory"]["controller_port_output_pipeline"],   
                user_port_input_pipeline=self.config[f"dac_tile{i}_sample_memory"]["dac_port_input_pipeline"],
                user_port_output_pipeline=self.config[f"dac_tile{i}_sample_memory"]["dac_port_output_pipeline"])
            self._hdl_modules.append(memory_controller)
            self.dac_tile_memory_controllers.append(memory_controller)
        
        # If we have any CMACCs, make a memory controller for the kernel ports
        self._max_cmacc_memory = 0
        self._num_cmaccs = 0
        for m in self.config["stream_processing_path"]["modules"]:
            if m["kind"] == "cmacc":
                self._num_cmaccs += 1
                if m["kernel_memory_depth"] > self._max_cmacc_memory:
                    self._max_cmacc_memory = m["kernel_memory_depth"]
                    
        if self._num_cmaccs > 0:
            self._max_cmacc_memory = self._max_cmacc_memory
            self.cmacc_kernel_memory_controller = AXIMemoryArray(f"cmacc_kernel", 
                instantiate_memories=False,
                size_bits=self._max_cmacc_memory*32, 
                width=self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_width"], 
                controller_width=self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_width"],
                elements=self._num_cmaccs, 
                read_only=False,
                use_rst=False,
                synchronous=False,
                primitive="auto",  # We're not including the memory here, but it will throw an error if we don't give this a valid entry
                controller_port_input_pipeline=0,
                controller_port_output_pipeline=self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_port_output_pipeline"],   
                user_port_input_pipeline=None,
                user_port_output_pipeline=None)
            self._hdl_modules.append(self.cmacc_kernel_memory_controller)

    def write_main_tcl(self, ip_directory, tcl_filename="main.tcl", constraints_filename="main.xdc"):
        """
        Write a TCL script to populate the main logic in the standard image. 
        """

        if not hasattr(self, "_hdl_filename"):
            raise ValueError("Call `write_hdl` before `write_main_tcl`.")
        with open(tcl_filename, "w") as f, open(constraints_filename, "w") as constraints:
            f.write(f"read_vhdl {self._hdl_filename}\n")
            
            # Write the TCL that will generate the IP for the AXI memory controllers
            memory_tcl = self.cache_memory_controller.generate_ip_tcl(ip_directory)
            memory_tcl += self.instruction_memory_controller.generate_ip_tcl(ip_directory)
            
            if self._num_cmaccs > 0:
                memory_tcl += self.cmacc_kernel_memory_controller.generate_ip_tcl(ip_directory)
            
            for controller in self.dac_tile_memory_controllers:
                memory_tcl += controller.generate_ip_tcl(ip_directory)
            
            f.write(memory_tcl)
            
            # ------------------- Clock Management -------------------- #
            
            seq_clk_pin = "main/seq_clk"
            seq_clk_freq = self.config["clocks"]['CLK104_PL_CLK']

            # Create clocks and apply timing constraints
            for clk,freq in self.config["clocks"].items():
                f.write(f"set_property -dict [list CONFIG.FREQ_HZ {{{freq}}}] [get_bd_intf_ports {clk}]\n")
                constraints.write(f"create_clock -period {round(1e9/freq, 4)} -name {clk} [get_ports {clk}_clk_p]\n")
            constraints.write("\n")

            # Set multicycle path constraints on internal signals to the RF data converter 
            # (this comes from the example design and I'm not entirely sure why it's needed but timing seems to fail without it)
            constraints.write("set_multicycle_path -to [get_pins -filter {REF_PIN_NAME== D} -of [get_cells -hier -filter {name =~ acadia_bd_i/main/rfdc/inst/IP2Bus_Data_reg*}]] -setup 2\n")
            constraints.write("set_multicycle_path -to [get_pins -filter {REF_PIN_NAME== D} -of [get_cells -hier -filter {name =~ acadia_bd_i/main/rfdc/inst/IP2Bus_Data_reg*}]] -hold 1\n")
            constraints.write("\n")

            # Add a max delay constraint between the PL clock and those generated by the RF tile
            # These clocks are technically synchronous but the RF tile doesn't know this
            constraints.write(f"set_max_delay {round(1e9/seq_clk_freq, 4)} -from [get_clocks -include_generated_clocks CLK104_PL_CLK] -to [get_clocks -include_generated_clocks [get_clocks -filter {{name =~ RF*_CLK}}]] -datapath_only\n")
            constraints.write(f"set_max_delay {round(1e9/seq_clk_freq, 4)} -from [get_clocks -include_generated_clocks [get_clocks -filter {{name =~ RF*_CLK}}]] -to [get_clocks -include_generated_clocks CLK104_PL_CLK] -datapath_only\n")
            constraints.write("\n")
            
            # Create reset module for the PL clock
            create_ip(f, name=f"main/proc_sys_reset_seq_clk", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
            connect_bd_net(f, f"main/proc_sys_reset_seq_clk/slowest_sync_clk", seq_clk_pin)
            connect_bd_net(f, f"main/proc_sys_reset_seq_clk/ext_reset_in", f"main/PS_async_resetn")
            seq_clk_peripheral_aresetn = "main/proc_sys_reset_seq_clk/peripheral_aresetn"

            # The PS AXI clock has an external reset module
            PS_AXI_clk_peripheral_aresetn = "main/PS_AXI_clk_peripheral_aresetn"
            PS_AXI_clk_pin = f"main/PS_AXI_clk"

            # ------------------- AXI Interconnects and SmartConnects -------------------- #

            # Create an AXI-lite SmartConnect for simple configuration peripherals
            create_ip(f, name="main/lite_crossbar", vlnv="xilinx.com:ip:axi_crossbar:2.1")
            
            # First slave is the RFDC IP
            slaves = 1

            # Add a slave if there's an ADC input switch to the stream processing path
            if len([inp for inp in self.config["stream_processing_path"]["inputs"] if inp["kind"] == "ADC_switch"]) > 0:
                slaves += 1

            # Add a slave for the stream processing path input switch
            slaves += 1 
            
            set_property(f, 
                         name="main/lite_crossbar", 
                         properties={"NUM_MI": slaves, 
                                     "NUM_SI": 1, 
                                     "STRATEGY": 2, # 1 = Minimize area, 2 = maximize performance
                                     "ADDR_WIDTH": 40,
                                     "CONNECTIVITY_MODE": "SAMD",
                                     "R_REGISTER": 1})
            connect_bd_net(f, f"main/lite_crossbar/aclk", seq_clk_pin)
            connect_bd_net(f, f"main/lite_crossbar/aresetn", seq_clk_peripheral_aresetn)
            lite_crossbar_slave = 0
            
            sequencer_memory_target_address_spaces = ["/ps/Data"]
            if self.config["sequencer_cache_memory"]["axi_master"] == "crossbar":
                # Create an AXI Crossbar for more rapid access to cache and instruction memories
                # 1 Master: PS AXI Master 1 (plus any DataMovers)
                # 2 slaves: cache, instruction memory
                create_ip(f, name="main/sequencer_memory_crossbar", vlnv="xilinx.com:ip:axi_crossbar:2.1")
                set_property(f, name="main/sequencer_memory_crossbar", 
                            properties={"NUM_SI": 1,
                                        "NUM_MI": 2,
                                        "STRATEGY": 1,
                                        "CONNECTIVITY_MODE": "SAMD"})
                connect_bd_net(f, "main/sequencer_memory_crossbar/aclk", seq_clk_pin)
                connect_bd_net(f, "main/sequencer_memory_crossbar/aresetn", seq_clk_peripheral_aresetn)
                
                sequencer_memory_crossbar_master = 0
                sequencer_memory_crossbar_slave = 0

                # Connect it to the PS
                connect_bd_intf_net(f, f"main/sequencer_memory_crossbar/S{sequencer_memory_crossbar_master:02d}_AXI", f"main/PS_M_AXI1")
                sequencer_memory_crossbar_master += 1
            elif self.config["sequencer_cache_memory"]["axi_master"] != "PS":
                raise ValueError(f'Unrecognized cache master {self.config["sequencer_cache_memory"]["axi_master"]}')
            
            # Create a SmartConnect for most memory in the system
            # Number of masters determined entirely by the stream processing path
            # 10 Slaves: PS AXI Slave HPC0-1, 
            #           PS AXI Slave HP0-1, 
            #           PL DDR C0-1,
            #           DAC Tile 0-3 Memory,
            #           
            create_ip(f, name="main/memory_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, name="main/memory_smartconnect", 
                         properties={"NUM_MI": 11, 
                                     "NUM_SI": self._memory_smartconnect_masters, 
                                     "NUM_CLKS": 4})
            connect_bd_net(f, f"main/memory_smartconnect/aclk", f"main/PS_AXI_clk")
            connect_bd_net(f, f"main/memory_smartconnect/aclk1", seq_clk_pin)
            connect_bd_net(f, f"main/memory_smartconnect/aclk2", f"main/DDR4_C0_ui_clk")
            connect_bd_net(f, f"main/memory_smartconnect/aclk3", f"main/DDR4_C1_ui_clk")
            connect_bd_net(f, f"main/memory_smartconnect/aresetn", f"main/PS_AXI_clk_interconnect_aresetn")
            memory_smartconnect_target_address_spaces = ["/ps/Data"]

            # Connect it to the PS and various interface ports
            connect_bd_intf_net(f, f"main/memory_smartconnect/S00_AXI", f"main/PS_M_AXI0")
            memory_smartconnect_master = 1
            
            # Set some pipeline properties in the switchboard
            set_property(f, 
                         "main/memory_smartconnect", 
                         properties=" CONFIG.ADVANCED_PROPERTIES { __view__ { timing { SW0 { AR_M_PIPE 1 AR_S_PIPE 1 AW_M_PIPE 1 AW_S_PIPE 1 B_M_PIPE 1 B_S_PIPE 1 R_M_PIPE 1 R_S_PIPE 1 W_M_PIPE 1 W_S_PIPE 1 } } }}")
            
            # Connect the lite smartconnect to the memory smartconnect
            connect_bd_intf_net(f, f"main/memory_smartconnect/M00_AXI", f"main/lite_crossbar/S00_AXI")
            memory_smartconnect_slave = 1
            
            for m in self.config["ps_axi_slaves"]:
                connect_bd_intf_net(f, f"main/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI", f"main/{m}")
                memory_smartconnect_slave += 1
            
            # ------------------- RF Data Converters -------------------- #

            create_ip(f, name="main/rfdc", vlnv="xilinx.com:ip:usp_rf_data_converter:2.6")
            
            # Auto-generated config string by Vivado
            rfdc_config_string = ("CONFIG.ADC_DSA_RTS {true} "
                                  "CONFIG.DAC_VOP_RTS {true} "
                                  f"CONFIG.Axiclk_Freq {{{seq_clk_freq*1e-6}}} ")
            
            for dc in ["adc", "dac"]:
                rfdc_config_string += f"CONFIG.{dc.upper()}_NCO_RTS {{true}} "
                rfdc_config_string += f"CONFIG.{dc.upper()}_RTS {{true}} "
                
                for tile in range(4):               
                    rfdc_config_string += (
                        f"CONFIG.{dc.upper()}{tile}_Clock_Dist {{{self.config['rfdc'][dc]['tile_distribute_clk'][tile]}}} "
                        f"CONFIG.{dc.upper()}{tile}_Clock_Source {{{self.config['rfdc'][dc]['tile_clk_source'][tile]}}} "
                        f"CONFIG.{dc.upper()}{tile}_Enable {{1}} "
                        f"CONFIG.{dc.upper()}{tile}_Fabric_Freq {{{seq_clk_freq*1e-6:.3f}}} "
                        f"CONFIG.{dc.upper()}{tile}_Multi_Tile_Sync {{{str(self.config['rfdc'][dc]['tile_mts'][tile]).lower()}}} "
                        f"CONFIG.{dc.upper()}{tile}_Outclk_Freq {{{self.config['rfdc'][dc]['tile_sample_rate_hz'][tile]*1e-6 / 16:.3f}}} "
                        f"CONFIG.{dc.upper()}{tile}_PLL_Enable {{{str(self.config['rfdc'][dc]['tile_pll'][tile]).lower()}}} "
                        f"CONFIG.{dc.upper()}{tile}_Refclk_Freq {{{self.config['rfdc'][dc]['tile_refclk_freq_hz'][tile]*1e-6:.3f}}} "
                        f"CONFIG.{dc.upper()}{tile}_Sampling_Rate {{{self.config['rfdc'][dc]['tile_sample_rate_hz'][tile]*1e-9:.3f}}} "
                    )

                    if dc == "dac":
                        rfdc_config_string += f"CONFIG.DAC{tile}_VOP {{{self.config['rfdc']['dac']['tile_vop'][tile]}}} "

                    for block in range(4):
                        interface_width = self.config['rfdc'][dc]['channel_interface_width'][tile*4 + block]

                        scale = self.config['rfdc'][dc]['tile_sample_rate_hz'][tile] * 32 / (interface_width * seq_clk_freq)
                        
                        if round(scale) != round(scale, 6):
                            raise ValueError(f"Invalid scale for {dc}{tile}{block}"
                                            f" ({scale})")
                        
                        scale = round(scale)

                        if scale not in [1,2,3,4,5,6,8,10,12,16,20,24,40]:
                            raise ValueError(f"Invalid scale for {dc}{tile}{block}"
                                            f" ({scale})")
                        
                        rfdc_config_string += f"CONFIG.{dc.upper()}_Coarse_Mixer_Freq{tile}{block} {{{0 if dc == 'adc' else 3}}} "
                        rfdc_config_string += f"CONFIG.{dc.upper()}_Data_Width{tile}{block} {{{interface_width // 16}}} "
                        rfdc_config_string += f"CONFIG.{dc.upper()}_Mixer_Mode{tile}{block} {{0}} "
                        rfdc_config_string += f"CONFIG.{dc.upper()}_Mixer_Type{tile}{block} {{2}} "
                        rfdc_config_string += f"CONFIG.{dc.upper()}_RESERVED_1_{tile}{block} {{false}} "
                        rfdc_config_string += f"CONFIG.{dc.upper()}_Slice{tile}{block}_Enable {{true}} "
                                    
                        if dc == "adc":
                            rfdc_config_string += f"CONFIG.ADC_Dither{tile}{block} {{{self.config['rfdc']['adc']['channel_dither'][tile*4 + block]}}} "
                            rfdc_config_string += f"CONFIG.ADC_Data_Type{tile}{block} {{1}} "
                            rfdc_config_string += f"CONFIG.ADC_OBS{tile}{block} {{false}} "
                            rfdc_config_string += f"CONFIG.ADC_Decimation_Mode{tile}{block} {{{scale}}} "
                        else:
                            rfdc_config_string += f"CONFIG.DAC_Interpolation_Mode{tile}{block} {{{scale}}} "
                            rfdc_config_string += f"CONFIG.DAC_Mode{tile}{block} {{0}} "
                            rfdc_config_string += f"CONFIG.DAC_Nyquist{tile}{block} {{{self.config['rfdc']['dac']['channel_nyquist_zone'][tile*4 + block]}}} "
                            rfdc_config_string += f"CONFIG.DAC_TDD_RTS{tile}{block} {{1}} "
            
            set_property(f, name="main/rfdc", properties=rfdc_config_string)
            
            connect_bd_net(f, f"main/rfdc/s_axi_aclk", seq_clk_pin)            
            connect_bd_net(f, f"main/rfdc/s_axi_aresetn", seq_clk_peripheral_aresetn)

            # Connect the analog inputs and outputs to the external ports through the main logic boundary
            for d in ["out", "in"]:
                for tile in range(4):
                    for block in range(4):
                        connect_bd_intf_net(f, f"main/rfdc/v{d}{tile}{block}", f"main/v{d}{tile}{block}")

            connect_bd_intf_net(f, f"main/rfdc/adc2_clk", f"main/adc2_clk")
            connect_bd_intf_net(f, f"main/rfdc/dac2_clk", f"main/dac2_clk")
            connect_bd_intf_net(f, f"main/rfdc/sysref_in", f"main/rfdc_sysref")
            
            # Connect the RFDC stream clocks and resets
            for i in range(4):
                connect_bd_net(f, f"main/rfdc/s{i}_axis_aclk", seq_clk_pin)
                connect_bd_net(f, f"main/rfdc/s{i}_axis_aresetn", seq_clk_peripheral_aresetn)        
                connect_bd_net(f, f"main/rfdc/m{i}_axis_aclk", seq_clk_pin)
                connect_bd_net(f, f"main/rfdc/m{i}_axis_aresetn", seq_clk_peripheral_aresetn)

            # Connect RFDC to the config smartconnect and assign it address space
            connect_bd_intf_net(f, f"main/lite_crossbar/M{lite_crossbar_slave:02d}_AXI", "main/rfdc/s_axi")
            lite_crossbar_slave += 1
            
            assign_bd_address(f, 
                              "/ps/Data", 
                              "main/rfdc/" + self.config["rfdc"]["axi_segment"], 
                              self.config["rfdc"]["axi_address"], 
                              self.config["rfdc"]["axi_size_bits"] // 8)

            # Synchronize the SYSREF signal from the CLK104 to the stream clock of DAC tile 0
            connect_bd_net(f, "main/seq_sysref", "main/rfdc/user_sysref_dac")
            connect_bd_net(f, "main/seq_sysref", "main/rfdc/user_sysref_adc")
            
            # ------------------- Sequencer ----------------------------- #
            
            # Create synchronizers for the GPIO
            create_ip(f, name=f"main/xpm_cdc_sequencer_nrst", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
            set_property(f, name="main/xpm_cdc_sequencer_nrst", properties={"CDC_TYPE": "xpm_cdc_sync_rst"})
            connect_bd_net(f, f"main/xpm_cdc_sequencer_nrst/src_rst", "main/sequencer_nrst")
            connect_bd_net(f, f"main/xpm_cdc_sequencer_nrst/dest_clk", seq_clk_pin)
            
            create_module(f, f"main/sequencer", "acadia_sequencer")
            connect_bd_net(f, "main/sequencer/clk", seq_clk_pin)
            connect_bd_net(f, f"main/sequencer/nrst", f"main/xpm_cdc_sequencer_nrst/dest_rst_out")

            # ------------------- Sequencer Bus and Associated Modules -------------------- #

            # Add the sequencer bus decoder and connect it to the sequencer bus
            create_module(f, f"main/sequencer_bus_decoder", "sequencer_bus_decoder")
            connect_bd_intf_net(f, f"main/sequencer_bus_decoder/master_bus", f"main/sequencer/mem_bus")

            # Create a RFDC real-time port register interface
            create_module(f, f"main/rfdc_rts_regs", "acadia_rfdc_rts_regs")
            set_property(f, "main/rfdc_rts_regs", properties={"SYNCHRONOUS": "true"})
            
            connect_bd_net(f, f"main/rfdc_rts_regs/nrst", seq_clk_peripheral_aresetn)
            connect_bd_net(f, f"main/rfdc_rts_regs/nco_dest_clk", seq_clk_pin)
            connect_bd_intf_net(f, f"main/sequencer_bus_decoder/rfdc_rts_regs", f"main/rfdc_rts_regs/master_bus")
                             
            for tile in range(4):
                connect_bd_intf_net(f, f"main/rfdc/dac{tile}_nco", f"main/rfdc_rts_regs/dac{tile}_nco")
                connect_bd_intf_net(f, f"main/rfdc/dac{tile}_rts", f"main/rfdc_rts_regs/dac{tile}_rts")
                connect_bd_intf_net(f, f"main/rfdc/dac{tile}_vop_rts", f"main/rfdc_rts_regs/dac{tile}_vop_rts")
                
                connect_bd_intf_net(f, f"main/rfdc/adc{tile}_nco", f"main/rfdc_rts_regs/adc{tile}_nco")
                connect_bd_intf_net(f, f"main/rfdc/adc{tile}_rts", f"main/rfdc_rts_regs/adc{tile}_rts")
                connect_bd_intf_net(f, f"main/rfdc/adc{tile}_dsa_rts", f"main/rfdc_rts_regs/adc{tile}_dsa_rts")
                
                for block in range(4):
                    # We'll only connect the DAC TDD signals here
                    connect_bd_net(f, f"main/rfdc/dac{tile}{block}_tdd_mode", f"main/rfdc_rts_regs/dac{tile}{block}_tdd_mode")
            
            # Create the interface to the PS DMA
            create_module(f, f"main/zdma_controller", "acadia_zdma_controller")
            set_property(f, name=f"main/zdma_controller", properties={"NUM_DMA": 8})
            connect_bd_net(f, "main/zdma_controller/nrst", seq_clk_peripheral_aresetn)
            connect_bd_intf_net(f, "main/sequencer_bus_decoder/zdma_controller", "main/zdma_controller/master_bus")
            
            # Add the GPIO controller
            create_module(f, f"main/sequencer_bus_gpio", "acadia_bus_gpio")
            connect_bd_net(f, "main/sequencer_bus_gpio/nrst", seq_clk_peripheral_aresetn)
            connect_bd_net(f, "main/sequencer_bus_gpio/clk", seq_clk_pin)
            connect_bd_intf_net(f, f"main/sequencer_bus_gpio/master_bus", f"main/sequencer_bus_decoder/gpio")
            connect_bd_intf_net(f, f"main/sequencer_bus_gpio/gpio", f"main/sequencer_gpio")

            # Add all the dataports
            for module in self._hdl_modules:
                if isinstance(module, BusDataport):
                    create_module(f, f"main/{module.name}", module.name)
                    connect_bd_intf_net(f, f"main/{module.name}/master_bus", f"main/sequencer_bus_decoder/{module.name}")
                    connect_bd_net(f, f"main/{module.name}/nrst", seq_clk_peripheral_aresetn)

            # Connect to the gty controller
            connect_bd_intf_net(f, f"main/gty_controller", f"main/sequencer_bus_decoder/gty_controller")

            # Now that the dataport exists, connect the sequencer done signal     
            connect_bd_net(f, f"main/sequencer_done_dataport/done", f"main/sequencer_done")

            # ------------------- Sequencer Cache -------------------- #
            # Add cache memory and connect it to the sequencer bus decoder
            create_module(f, f"main/cache_memory", f"cache_axi_memory")
            
            connect_bd_net(f, 
                           "main/cache_memory/s_axi_aclk", 
                           eval(self.config['sequencer_cache_memory']['clock'] + "_pin"))
            connect_bd_net(f, 
                           "main/cache_memory/s_axi_aresetn", 
                           self.config['sequencer_cache_memory']['reset'])
            
            # Connect the cache to its designated master
            if self.config['sequencer_cache_memory']['axi_master'] == 'PS':
                # Connect through a register slice
                create_ip(f, "main/cache_memory_reg", "xilinx.com:ip:axi_register_slice:2.1")
                connect_bd_net(f, 
                               f"main/cache_memory_reg/aclk", 
                               eval(self.config['sequencer_cache_memory']['clock'] + "_pin"))
                connect_bd_net(f, 
                               f"main/cache_memory_reg/aresetn", 
                               self.config['sequencer_cache_memory']['reset'])
                connect_bd_intf_net(f, 
                                    f"main/PS_M_AXI1" , 
                                    f"main/cache_memory_reg/S_AXI")
                connect_bd_intf_net(f, 
                                    f"main/cache_memory_reg/M_AXI", 
                                    f"main/cache_memory/s_axi")
                
            elif self.config['sequencer_cache_memory']['axi_master'] == 'crossbar':
                connect_bd_intf_net(f, 
                                    f"main/cache_memory/s_axi", 
                                    f"main/sequencer_memory_crossbar/M{sequencer_memory_crossbar_slave:02d}_AXI")
                sequencer_memory_crossbar_slave += 1
            else:
                raise ValueError(f"Unrecognized cache master {self.config['sequencer_cache_memory']['axi_master']}")
            
            # Connect the cache to the sequencer bus decoder
            connect_bd_intf_net(f, 
                                f"main/sequencer_bus_decoder/cache", 
                                f"main/cache_memory/mem0")
            
            # ------------------- Sequencer Instruction Memory -------------------- #
            create_module(f, "main/instruction_memory", "instruction_axi_memory")
            connect_bd_net(f, 
                           "main/instruction_memory/s_axi_aclk", 
                           eval(self.config['sequencer_instruction_memory']['clock'] + "_pin"))
            connect_bd_net(f, 
                           "main/instruction_memory/s_axi_aresetn", 
                           f"main/proc_sys_reset_{self.config['sequencer_instruction_memory']['clock']}/peripheral_aresetn")
            
            # Connect it to the smartconnect through a register slice
            # Connect through a register slice
            create_ip(f, "main/instruction_memory_reg", "xilinx.com:ip:axi_register_slice:2.1")
            connect_bd_net(f, 
                            f"main/instruction_memory_reg/aclk", 
                            eval(self.config['sequencer_instruction_memory']['clock'] + "_pin"))
            connect_bd_net(f, 
                            f"main/instruction_memory_reg/aresetn", 
                            f"main/proc_sys_reset_{self.config['sequencer_instruction_memory']['clock']}/peripheral_aresetn")
            connect_bd_intf_net(f, 
                                f"main/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI", 
                                f"main/instruction_memory_reg/S_AXI")
            connect_bd_intf_net(f, 
                                f"main/instruction_memory_reg/M_AXI", 
                                f"main/instruction_memory/s_axi")
            memory_smartconnect_slave += 1
            
            # Connect it to the sequencer
            connect_bd_intf_net(f, f"main/sequencer/instruction_mem", f"main/instruction_memory/mem0")
            
            # ------------------- Sequencer Flags -------------------- #
            create_ip(f, name="main/xlconst_0", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name="main/xlconst_0", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
            connect_bd_net(f, f"main/sequencer/ext_in", f"main/xlconst_0/Dout")
            
            # ------------------- DAC Memory -------------------- #
            for tile in range(4):
                create_module(f, f"main/dac_tile{tile}_memory", f"dac_tile{tile}_axi_memory")
                connect_bd_intf_net(f, f"main/dac_tile{tile}_memory/s_axi", f"main/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI")
                connect_bd_net(f, f"main/dac_tile{tile}_memory/s_axi_aclk", seq_clk_pin)
                connect_bd_net(f, f"main/dac_tile{tile}_memory/s_axi_aresetn", seq_clk_peripheral_aresetn)
                memory_smartconnect_slave += 1
            
            # ------------------- DAC Real-Time DMAs -------------------- #
            for channel in range(self.NUM_DACS):
                tile = channel // 4
                block = channel % 4

                # Create a DMA for the DAC and connect it to the read port of the BRAM
                create_module(f, f"main/dac{channel}_dma", "acadia_dma")
                set_property(f, 
                             f"main/dac{channel}_dma", 
                             properties={
                                "ADDRESS_WIDTH": next_highest_power_of_2(
                                                    self.config[f"dac_tile{tile}_sample_memory"]["size_bits"] 
                                                    // self.config[f"rfdc"]["dac"]["channel_interface_width"][channel], 
                                                log=True),
                                "DESCRIPTOR_FIFO_DEPTH": self.config[f"rfdc"]["dac"]["dma_fifo_depth"][channel]})
                connect_bd_net(f, f"main/dac{channel}_dma/clk", seq_clk_pin)
                connect_bd_net(f, f"main/dac{channel}_dma/nrst", seq_clk_peripheral_aresetn)

                connect_bd_net(f, f"main/dac{channel}_dma/address_out_tdata", f"main/dac_tile{tile}_memory/mem{block}_addr")
                connect_bd_net(f, f"main/dac{channel}_dma/data_address_invalid", f"main/dac_tile{tile}_memory/mem{block}_rst")


                # Connect the DAC memory output to the RFDAC interface through a pipeline
                create_module(f, f"main/dac{channel}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"main/dac{channel}_pipeline", 
                             properties={"WIDTH": self.config['rfdc']['dac']['channel_interface_width'][channel], 
                                         "STAGES": self.config['rfdc']['dac']['channel_pipeline_stages'][channel]})
                
                connect_bd_net(f, f"main/dac{channel}_pipeline/clk", seq_clk_pin)
                connect_bd_net(f, f"main/dac_tile{tile}_memory/mem{block}_dout", f"main/dac{channel}_pipeline/s_axis_tdata")
                connect_bd_intf_net(f, f"main/dac{channel}_pipeline/m_axis", f"main/rfdc/s{tile}{block}_axis")

                # Connect the DAC DMA to the bus and dataports
                connect_bd_intf_net(f, f"main/sequencer_bus_decoder/dac{channel}_dma", f"main/dac{channel}_dma/master_bus")
                connect_bd_net(f, f"main/dma_trigger_dataport/dac{channel}_dma", f"main/dac{channel}_dma/trigger")
                connect_bd_net(f, f"main/dma_running_dataport/dac{channel}_dma", f"main/dac{channel}_dma/running")
                
                # Connect the data input of the DMA to zeros in order to suppress the
                # critical warning vivado will generate
                create_ip(f, name=f"main/xlconst_dac{channel}_dma_data_in", vlnv="xilinx.com:ip:xlconstant:1.1")
                set_property(f, name=f"main/xlconst_dac{channel}_dma_data_in", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
                connect_bd_net(f, f"main/xlconst_dac{channel}_dma_data_in/dout", f"main/dac{channel}_dma/data_in")
            
            # ------------------- ADC Real-Time DMAs -------------------- #
            for d in range(self.NUM_ADCS):
                tile = d // 4
                block = d % 4
                create_module(f, f"main/adc{d}_dma", "acadia_dma")
                set_property(f, 
                             name=f"main/adc{d}_dma", 
                             properties={
                                "DATA_WIDTH": self.config["stream_processing_path"]["width"],
                                "DESCRIPTOR_FIFO_DEPTH": self.config[f"rfdc"]["adc"]["dma_fifo_depth"][channel]})
                connect_bd_net(f, f"main/adc{d}_dma/clk", seq_clk_pin)
                connect_bd_net(f, f"main/adc{d}_dma/nrst", seq_clk_peripheral_aresetn)
                
                # Connect the data input to the DMA through a pipeline
                create_module(f, f"main/adc{d}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"main/adc{d}_pipeline", 
                            properties={"WIDTH": self.config['rfdc']['adc']['channel_interface_width'][d],
                                        "STAGES": self.config['rfdc']['adc']['channel_pipeline_stages'][d]})
                connect_bd_net(f, f"main/adc{d}_pipeline/clk", seq_clk_pin)

                connect_bd_intf_net(f, f"main/rfdc/m{tile}{block}_axis", 
                                    f"main/adc{d}_pipeline/S_AXIS")
                
                connect_bd_net(f,
                               f"main/adc{d}_pipeline/m_axis_tdata",
                               f"main/adc{d}_dma/data_in")

                # Connect the ADC DMA signals to the bus and dataports
                connect_bd_intf_net(f, f"main/sequencer_bus_decoder/adc{d}_dma", f"main/adc{d}_dma/master_bus")
                connect_bd_net(f, f"main/dma_trigger_dataport/adc{d}_dma", f"main/adc{d}_dma/trigger")
                connect_bd_net(f, f"main/dma_running_dataport/adc{d}_dma", f"main/adc{d}_dma/running")
            
            # ------------------- DMA flags -------------------- #

            # Create a concatenator for the clock signals
            create_concatenator(f, "main/dma_flag_concat", [1]*(self.NUM_ADCS + self.NUM_DACS))
            connect_bd_net(f, f"main/dma_flag_concat/dout", f"main/dma_flags")
            for i in range(self.NUM_DACS):
                connect_bd_net(f, f"main/dma_flag_concat/In{i}", f"main/dac{i}_dma/flag")
            for i in range(self.NUM_ADCS):
                connect_bd_net(f, f"main/dma_flag_concat/In{i+self.NUM_DACS}", f"main/adc{i}_dma/flag")

            # ------------------- Stream Processing Path -------------------- #
            
            # Some ADCs will be directly connected to the stream input path input switch, and the remainder
            # will have their own switch
            # Determine these quantities so that we know how many ports the stream processing path input switch will need
            adc_direct_inputs = [inp["channel"] for inp in self.config["stream_processing_path"]["inputs"] if inp["kind"] == "ADC"]
            adc_switch_inputs = [f"ADC{i}" for i in range(self.NUM_ADCS) if i not in adc_direct_inputs]
            num_adc_switch_outputs = len([inp for inp in self.config["stream_processing_path"]["inputs"] if inp["kind"] == "ADC_switch"])
            
            # Now create the input switch itself
            create_ip(f, name="main/stream_processing_input_switch", vlnv="xilinx.com:ip:axis_switch:1.1")
            set_property(f, name="main/stream_processing_input_switch", 
                             properties="CONFIG.TDATA_NUM_BYTES.VALUE_SRC USER "
                                        "CONFIG.HAS_TREADY.VALUE_SRC USER "
                                        "CONFIG.HAS_TSTRB.VALUE_SRC USER "
                                        "CONFIG.HAS_TKEEP.VALUE_SRC USER "
                                        "CONFIG.HAS_TLAST.VALUE_SRC USER "
                                        "CONFIG.TID_WIDTH.VALUE_SRC USER "
                                        "CONFIG.TDEST_WIDTH.VALUE_SRC USER "
                                        "CONFIG.TUSER_WIDTH.VALUE_SRC USER")
            set_property(f, name="main/stream_processing_input_switch", 
                             properties=f"CONFIG.NUM_SI {{{len(self.config['stream_processing_path']['inputs'])}}} "
                                        f"CONFIG.NUM_MI {{{len(self.config['stream_processing_path']['modules'])}}} "
                                        "CONFIG.ROUTING_MODE {1} "
                                        f"CONFIG.TDATA_NUM_BYTES {{{self.config['stream_processing_path']['width'] // 8}}} "
                                        "CONFIG.DECODER_REG {1} "
                                        "CONFIG.OUTPUT_REG {1} "
                                        "CONFIG.HAS_TLAST {1} "
                                        "CONFIG.HAS_TREADY {0} "
                                        "CONFIG.TDEST_WIDTH {0}")
            
            connect_bd_net(f, f"main/stream_processing_input_switch/aclk", seq_clk_pin)
            connect_bd_net(f, f"main/stream_processing_input_switch/aresetn", seq_clk_peripheral_aresetn)
            connect_bd_net(f, f"main/stream_processing_input_switch/s_axi_ctrl_aclk", seq_clk_pin)
            connect_bd_net(f, f"main/stream_processing_input_switch/s_axi_ctrl_aresetn", seq_clk_peripheral_aresetn)
                
            # Connect the switch's control port to the lite crossbar and assign addresses
            connect_bd_intf_net(f, 
                                f"main/lite_crossbar/M{lite_crossbar_slave:02d}_AXI", 
                                f"main/stream_processing_input_switch/S_AXI_CTRL")
            lite_crossbar_slave += 1
            assign_bd_address(f, 
                              "/ps/Data", 
                              "main/stream_processing_input_switch/" + self.config["stream_processing_path"]["input_switch"]["axi_segment"], 
                              self.config["stream_processing_path"]["input_switch"]["axi_address"], 
                              self.config["stream_processing_path"]["input_switch"]["axi_size_bits"] // 8)
                        
            # ------------------- ADC Input Switch -------------------- #
            if num_adc_switch_outputs > 0:
                
                # Create a switch for the remaining ADCs not directly connected to the input switch
                create_ip(f, name="main/adc_input_switch", vlnv="xilinx.com:ip:axis_switch:1.1")
                set_property(f, name="main/adc_input_switch", 
                                properties="CONFIG.TDATA_NUM_BYTES.VALUE_SRC USER "
                                            "CONFIG.HAS_TREADY.VALUE_SRC USER "
                                            "CONFIG.HAS_TSTRB.VALUE_SRC USER "
                                            "CONFIG.HAS_TKEEP.VALUE_SRC USER "
                                            "CONFIG.HAS_TLAST.VALUE_SRC USER "
                                            "CONFIG.TID_WIDTH.VALUE_SRC USER "
                                            "CONFIG.TDEST_WIDTH.VALUE_SRC USER "
                                            "CONFIG.TUSER_WIDTH.VALUE_SRC USER")
                set_property(f, name="main/adc_input_switch", 
                                properties=f"CONFIG.NUM_SI {{{len(adc_switch_inputs)}}} "
                                            f"CONFIG.NUM_MI {{{num_adc_switch_outputs}}} "
                                            "CONFIG.ROUTING_MODE {1} "
                                            f"CONFIG.TDATA_NUM_BYTES {{{self.config['stream_processing_path']['width'] // 8}}} "
                                            "CONFIG.DECODER_REG {1} "
                                            "CONFIG.OUTPUT_REG {1} "
                                            "CONFIG.HAS_TLAST {1} "
                                            "CONFIG.HAS_TREADY {0} "
                                            "CONFIG.TDEST_WIDTH {0}")

                connect_bd_net(f, f"main/adc_input_switch/aclk", seq_clk_pin)
                connect_bd_net(f, f"main/adc_input_switch/aresetn", seq_clk_peripheral_aresetn)
                connect_bd_net(f, f"main/adc_input_switch/s_axi_ctrl_aclk", seq_clk_pin)
                connect_bd_net(f, f"main/adc_input_switch/s_axi_ctrl_aresetn", seq_clk_peripheral_aresetn)
                
                # Connect the switch's control port to the lite crossbar
                connect_bd_intf_net(f, 
                                f"main/lite_crossbar/M{lite_crossbar_slave:02d}_AXI", 
                                f"main/adc_input_switch/S_AXI_CTRL")
                lite_crossbar_slave += 1
                assign_bd_address(f, 
                              "/ps/Data", 
                              "main/adc_input_switch/" + self.config["stream_processing_path"]["adc_input_switch"]["axi_segment"], 
                              self.config["stream_processing_path"]["adc_input_switch"]["axi_address"], 
                              self.config["stream_processing_path"]["adc_input_switch"]["axi_size_bits"] // 8)
            
            # Connect the ADC DMA outputs to the ADC switch if they're not directly connected to the main input switch
            adc_input_switch_master = 0
            direct_connections = [inp["channel"] for inp in self.config["stream_processing_path"]["inputs"] if inp["kind"] == "ADC"]                
            for channel in range(self.NUM_ADCS):
                if channel not in direct_connections:
                    connect_bd_intf_net(f, f"main/adc{channel}_dma/data_out", 
                                        f"main/adc_input_switch/S{adc_input_switch_master:02d}_AXIS")
                    adc_input_switch_master += 1
                    
            # ------------------- DataMover-driven stream processing inputs -------------------- #
            adc_input_switch_slave = 0
            for idx,inp in enumerate(self.config["stream_processing_path"]["inputs"]):
                if inp["kind"] == "ADC":
                    # Connect the corresponding ADC DMA data output directly to the switch
                    connect_bd_intf_net(f, f"main/adc{inp['channel']}_dma/data_out", 
                                        f"main/stream_processing_input_switch/S{idx:02d}_AXIS")
                elif inp["kind"] == "ADC_switch":
                    # Connect an output of the ADC switch to the input switch
                    connect_bd_intf_net(f, f"main/adc_input_switch/M{adc_input_switch_slave:02d}_AXIS", 
                                        f"main/stream_processing_input_switch/S{idx:02d}_AXIS")
                    adc_input_switch_slave += 1
                elif inp["kind"] == "memory":
                    # First, create the DataMover Controller and connect it to the bus
                    create_module(f, f"main/input{idx}_datamover_controller", "acadia_datamover_controller")
                    connect_bd_net(f, f"main/input{idx}_datamover_controller/clk", seq_clk_pin)
                    connect_bd_intf_net(f, 
                                        f"main/sequencer_bus_decoder/input{idx}_datamover_controller", 
                                        f"main/input{idx}_datamover_controller/master_bus")
                    
                     # Create and connect the DataMovers itself
                    create_ip(f, name=f"main/input{idx}_datamover", vlnv="xilinx.com:ip:axi_datamover:5.1")
                    set_property(f, 
                                 name=f"main/input{idx}_datamover", 
                                 properties={"c_m_axi_s2mm_data_width.VALUE_SRC": "USER", 
                                            "c_s_axis_s2mm_tdata_width.VALUE_SRC": "USER"})

                    dm_config = "CONFIG.c_enable_cache_user {true} "
                    dm_config += "CONFIG.c_addr_width {40} "
                    dm_config += f"CONFIG.c_enable_s2mm {{0}} "
                    dm_config += f"CONFIG.c_include_s2mm {{Omit}} "
                    dm_config += f"CONFIG.c_include_s2mm_stsfifo {{false}} "
                    dm_config += f"CONFIG.c_s2mm_include_sf {{false}} "
                    
                    dm_config += f"CONFIG.c_m_axi_mm2s_data_width {{{self.config[f'stream_processing_path']['width']}}} "
                    dm_config += f"CONFIG.c_m_axis_mm2s_tdata_width {{{self.config[f'stream_processing_path']['width']}}} "
                    dm_config += f"CONFIG.c_mm2s_burst_size {{256}} "
                    dm_config += f"CONFIG.c_mm2s_btt_used {{23}} "
                    dm_config += f"CONFIG.c_include_mm2s {{Full}} "
                    dm_config += f"CONFIG.c_include_mm2s_stsfifo {{true}} "
                    dm_config += f"CONFIG.c_mm2s_addr_pipe_depth {{3}} "
                    dm_config += f"CONFIG.c_mm2s_include_sf {{false}} "
                    dm_config += f"CONFIG.c_enable_mm2s {{1}} "
 
                    set_property(f, name=f"main/input{idx}_datamover", properties=dm_config)                    
                
                    # Connect the AXI masters
                    destination = f"main/memory_smartconnect/S{memory_smartconnect_master:02d}_AXI"
                    memory_smartconnect_master += 1
                    memory_smartconnect_target_address_spaces.append(f"/main/input{idx}_datamover/Data_MM2S")
                        
                    connect_bd_intf_net(f, f"main/input{idx}_datamover/M_AXI_MM2S", destination)

                    # Connect clocks and resets for the command and status ports
                    # (for some reason the clock pins are different between s2mm and mm2s)
                    # These will both connect to the sequencer clock since the command and status ports
                    # are controlled by the bus through the DataMover controller
                    connect_bd_net(f, f"main/input{idx}_datamover/m_axis_mm2s_cmdsts_aclk", seq_clk_pin)
                    connect_bd_net(f, f"main/input{idx}_datamover/m_axis_mm2s_cmdsts_aresetn", seq_clk_peripheral_aresetn)

                    # Connect AXI Master clocks and resets
                    connect_bd_net(f, 
                                    f"main/input{idx}_datamover/m_axi_mm2s_aclk", 
                                    eval(inp['AXI_clock'] + "_pin"))
                    connect_bd_net(f, 
                                    f"main/input{idx}_datamover/m_axi_mm2s_aresetn", 
                                    inp['AXI_reset'])

                    # Connect command and status
                    connect_bd_intf_net(f, 
                                        f"main/input{idx}_datamover_controller/cmd", 
                                        f"main/input{idx}_datamover/S_AXIS_MM2S_CMD")
                    connect_bd_intf_net(f, 
                                        f"main/input{idx}_datamover_controller/sts", 
                                        f"main/input{idx}_datamover/M_AXIS_MM2S_STS")
                    
                    # Connect the error signal
                    connect_bd_net(f, f"main/input{idx}_datamover/mm2s_err", f"main/input{idx}_datamover_controller/err")
                    
                    # Connect the datamover to the switch through a FIFO
                    create_ip(f, f"main/input{idx}_datamover_fifo", "xilinx.com:ip:axis_data_fifo:2.0")
                    set_property(f, 
                                 f"main/input{idx}_datamover_fifo",
                                 properties={"IS_ACLK_ASYNC": 1, 
                                             "FIFO_DEPTH": inp["FIFO_depth"]})
                    
                    # Connect clocks and resets for the FIFO
                    connect_bd_net(f, 
                                   f"main/input{idx}_datamover_fifo/s_axis_aclk", 
                                   eval(inp['AXI_clock'] + "_pin"))
                    connect_bd_net(f, 
                                f"main/input{idx}_datamover_fifo/s_axis_aresetn",
                                inp['AXI_reset'])
                    connect_bd_net(f, 
                                   f"main/input{idx}_datamover_fifo/m_axis_aclk", 
                                   seq_clk_pin)
                    
                    
                    # Connect the DataMover to the FIFO
                    connect_bd_intf_net(f, 
                                        f"main/input{idx}_datamover/M_AXIS_MM2S", 
                                        f"main/input{idx}_datamover_fifo/s_axis")
                    
                    # Connect the FIFO output to the switch
                    connect_bd_intf_net(f, 
                                        f"main/input{idx}_datamover_fifo/m_axis", 
                                        f"main/stream_processing_input_switch/S{idx:02d}_AXIS")
                    
                else:
                    raise ValueError(f"Unrecognized input kind {inp['kind']}")
                    
                    
            # ------------------- CMACC Kernel Memory (if any) -------------------- #
            if self._num_cmaccs > 0:
                # Create the memory controller
                create_module(f, f"main/cmacc_kernel_memory", f"cmacc_kernel_axi_memory")
                connect_bd_intf_net(f, f"main/cmacc_kernel_memory/s_axi", f"main/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI")
                memory_smartconnect_slave += 1
                connect_bd_net(f, f"main/cmacc_kernel_memory/s_axi_aclk", seq_clk_pin)
                connect_bd_net(f, f"main/cmacc_kernel_memory/s_axi_aresetn", seq_clk_peripheral_aresetn)
            
                    
            # ------------------- Stream Processing Modules -------------------- #
            cmacc_kernel_memory_controller_element = 0
            for idx_module,module in enumerate(self.config["stream_processing_path"]["modules"]):
                # All of the modules will need a datamover
                create_ip(f, name=f"main/module{idx_module}_datamover", vlnv="xilinx.com:ip:axi_datamover:5.1")
                set_property(f, name=f"main/module{idx_module}_datamover", 
                                    properties="CONFIG.c_m_axi_s2mm_data_width.VALUE_SRC USER CONFIG.c_s_axis_s2mm_tdata_width.VALUE_SRC USER")
                
                # Connect clocks and resets for the command and status ports
                # (for some reason the clock pins are different between s2mm and mm2s)
                # These will both connect to the sequencer clock since the command and status ports
                # are controlled by the bus through the DataMover controller
                connect_bd_net(f, 
                                f"main/module{idx_module}_datamover/m_axis_s2mm_cmdsts_awclk", 
                                seq_clk_pin)
                connect_bd_net(f, 
                                f"main/module{idx_module}_datamover/m_axis_s2mm_cmdsts_aresetn",
                                seq_clk_peripheral_aresetn)

                # Connect AXI Master clocks and resets
                connect_bd_net(f, 
                                f"main/module{idx_module}_datamover/m_axi_s2mm_aclk", 
                                eval(module['AXI_clock'] + "_pin"))
                connect_bd_net(f, 
                                f"main/module{idx_module}_datamover/m_axi_s2mm_aresetn", 
                                module['AXI_reset'])

                connect_bd_net(f, 
                                f"main/module{idx_module}_datamover/m_axi_mm2s_aclk", 
                                eval(module['AXI_clock'] + "_pin"))
                connect_bd_net(f, 
                                f"main/module{idx_module}_datamover/m_axi_mm2s_aresetn", 
                                module['AXI_reset'])

                # Create a controller
                create_module(f, 
                                f"main/module{idx_module}_s2mm_datamover_controller", 
                                "acadia_datamover_controller")
                connect_bd_net(f, f"main/module{idx_module}_s2mm_datamover_controller/clk", seq_clk_pin)
                connect_bd_intf_net(f, 
                                    f"main/module{idx_module}_s2mm_datamover_controller/master_bus",
                                    f"main/sequencer_bus_decoder/module{idx_module}_s2mm_datamover_controller")

                # Connect command and status
                connect_bd_intf_net(f, 
                                    f"main/module{idx_module}_s2mm_datamover_controller/cmd", 
                                    f"main/module{idx_module}_datamover/S_AXIS_S2MM_CMD")
                connect_bd_intf_net(f, 
                                    f"main/module{idx_module}_s2mm_datamover_controller/sts", 
                                    f"main/module{idx_module}_datamover/M_AXIS_S2MM_STS")
                
                # Connect the error signal
                connect_bd_net(f, f"main/module{idx_module}_datamover/s2mm_err", f"main/module{idx_module}_s2mm_datamover_controller/err")

                if module["kind"] == "fifo":
                    # No MM2S needed, just connect to the datamover (through a FIFO)
                    datamover_properties = {
                        "c_enable_cache_user": "true",
                        "c_enable_s2mm_adv_sig": 0,
                        "c_addr_width": 40,
                        
                        "c_enable_s2mm": 1,
                        "c_include_s2mm": "Full",
                        "c_m_axi_s2mm_data_width": module['AXI_width'],
                        "c_s_axis_s2mm_tdata_width": self.config["stream_processing_path"]["width"],
                        "c_s2mm_btt_used": 23,
                        "c_s2mm_burst_size": module['datamover_burst_size'],
                        "c_s2mm_support_indet_btt": "true",
                        "c_s2mm_include_sf": "false",
                        
                        "c_enable_mm2s": 0,
                        "c_include_mm2s": "Omit",
                        "c_include_mm2s_stsfifo": "false",
                        "c_mm2s_include_sf": "false",
                    }
                    set_property(f, name=f"main/module{idx_module}_datamover", properties=datamover_properties)

                    # Connect the output AXI master
                    connect_bd_intf_net(f, 
                                        f"main/module{idx_module}_datamover/M_AXI_S2MM", 
                                        f"main/memory_smartconnect/S{memory_smartconnect_master:02d}_AXI")
                    memory_smartconnect_master += 1
                    memory_smartconnect_target_address_spaces.append(f"/main/module{idx_module}_datamover/Data_S2MM")
                    
                    # Create a buffer FIFO
                    create_module(f, f"main/module{idx_module}_fifo", "acadia_stream_fifo")
                    set_property(f, 
                                 f"main/module{idx_module}_fifo",
                                 properties={"INPUT_WORDS": self.config["stream_processing_path"]["width"] // 32,
                                            "DATA_OUTPUT_FIFO_DEPTH": module["FIFO_depth"],
                                            "DATA_OUTPUT_FIFO_PRIMITIVE": module["FIFO_primitive"],
                                            "DATA_OUTPUT_FIFO_ASYNCHRONOUS": "false" if module["AXI_clock"] == "seq_clk" else "true"})
                    
                    # Connect clocks and resets for the FIFO
                    connect_bd_net(f, 
                                   f"main/module{idx_module}_fifo/clk", 
                                   seq_clk_pin)
                    connect_bd_net(f, 
                                f"main/module{idx_module}_fifo/nrst",
                                seq_clk_peripheral_aresetn)
 
                    connect_bd_net(f, 
                                   f"main/module{idx_module}_fifo/data_out_aclk", 
                                   eval(module['AXI_clock'] + "_pin"))
                    
                    # Connect the FIFO interfaces
                    connect_bd_intf_net(f, 
                                        f"main/stream_processing_input_switch/M{idx_module:02d}_AXIS", 
                                        f"main/module{idx_module}_fifo/data_in")
                    connect_bd_intf_net(f, 
                                        f"main/module{idx_module}_fifo/data_out",
                                        f"main/module{idx_module}_datamover/S_AXIS_S2MM")

                    # Connect the register interface to the bus
                    connect_bd_intf_net(f, 
                                        f"main/sequencer_bus_decoder/module{idx_module}_registers",
                                        f"main/module{idx_module}_fifo/registers")
                    
                    
                elif module["kind"] == "cmacc":
                    # No MM2S needed, just connect to the datamover
                    datamover_properties = {
                        "c_enable_cache_user": "true",
                        "c_enable_s2mm_adv_sig": 0,
                        "c_addr_width": 40,
                        
                        "c_enable_s2mm": 1,
                        "c_include_s2mm": "Full",
                        "c_m_axi_s2mm_data_width": module['AXI_width'],
                        "c_s_axis_s2mm_tdata_width": 64,
                        "c_s2mm_btt_used": 23,
                        "c_s2mm_burst_size": module['datamover_burst_size'],
                        "c_s2mm_support_indet_btt": "true",
                        "c_s2mm_include_sf": "false",
                        
                        "c_enable_mm2s": 0,
                        "c_include_mm2s": "Omit",
                        "c_include_mm2s_stsfifo": "false",
                        "c_mm2s_include_sf": "false",
                    }
                    set_property(f, name=f"main/module{idx_module}_datamover", properties=datamover_properties)
                
                    # Connect the output AXI master
                    connect_bd_intf_net(f, 
                                        f"main/module{idx_module}_datamover/M_AXI_S2MM", 
                                        f"main/memory_smartconnect/S{memory_smartconnect_master:02d}_AXI")
                    memory_smartconnect_master += 1
                    memory_smartconnect_target_address_spaces.append(f"/main/module{idx_module}_datamover/Data_S2MM")
                    
                    # Create the module
                    create_module(f, f"main/module{idx_module}_cmacc", "acadia_stream_cmacc")
                    external_depth = 32 * module["kernel_memory_depth"] // self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_width"]
                    set_property(f, 
                                 f"main/module{idx_module}_cmacc", 
                                 properties={"INPUT_WORDS": self.config["stream_processing_path"]["width"] // 32,
                                            "KERNEL_MEMORY_DEPTH": module["kernel_memory_depth"],
                                            "LOG2_KERNEL_MEMORY_DEPTH": next_highest_power_of_2(module["kernel_memory_depth"], log=True),
                                            "KERNEL_MEMORY_EXTERNAL_PORT_LATENCY": self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_port_output_pipeline"],
                                            "KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH": self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_width"],
                                            "KERNEL_MEMORY_EXTERNAL_PORT_ADDRESS_WIDTH": next_highest_power_of_2(external_depth, log=True),
                                            "DATA_OUTPUT_FIFO_DEPTH": module["FIFO_depth"],
                                            "DATA_OUTPUT_FIFO_PRIMITIVE": module["FIFO_primitive"],
                                            "DATA_OUTPUT_FIFO_ASYNCHRONOUS": "false" if module["AXI_clock"] == "seq_clk" else "true"})
                    
                    connect_bd_net(f, f"main/module{idx_module}_cmacc/clk", seq_clk_pin)
                    connect_bd_net(f, f"main/module{idx_module}_cmacc/nrst", seq_clk_peripheral_aresetn)
                    
                    # Connect the register interface to the bus
                    connect_bd_intf_net(f, 
                                        f"main/sequencer_bus_decoder/module{idx_module}_registers",
                                        f"main/module{idx_module}_cmacc/registers")
                    
                    # Connect the input (unbuffered)
                    connect_bd_intf_net(f, 
                                        f"main/stream_processing_input_switch/M{idx_module:02d}_AXIS", 
                                        f"main/module{idx_module}_cmacc/data_in")
                    
                    # Connect the output interface and clock directly to the datamover 
                    # (the output is buffered with a FIFO internally)
                    connect_bd_net(f, 
                                   f"main/module{idx_module}_cmacc/data_out_aclk", 
                                   eval(module['AXI_clock'] + "_pin"))                    
                    connect_bd_intf_net(f, 
                                        f"main/module{idx_module}_cmacc/data_out", 
                                        f"main/module{idx_module}_datamover/S_AXIS_S2MM")
            
                    # Connect the kernel memory controller
                    connect_bd_intf_net(f,
                                        f"main/module{idx_module}_cmacc/kernel_memory",
                                        f"main/cmacc_kernel_memory/mem{cmacc_kernel_memory_controller_element}")
                    cmacc_kernel_memory_controller_element += 1
                                        
                elif module["kind"] == "fft":
                    #create_bd_cell -type ip -vlnv xilinx.com:ip:xfft:9.1 xfft_0
                    properties = {"transform_length": 65536,
                                  "implementation_options": "pipelined_streaming_io",
                                  "scaling_options": "unscaled",
                                  "rounding_modes": "convergent_rounding",
                                  "output_ordering": "natural_order",
                                  "complex_mult_type": "use_mults_performance",
                                  "butterfly_type": "use_xtremedsp_slices",
                                  "number_of_stages_using_block_ram_for_data_and_phase_factors": 9}

                    raise NotImplemented()
                else:
                    raise ValueError(f"Unrecognized module {module['kind']}")
                    
                
            # ------------------- PS GDMA Connections -------------------- #
            connect_bd_net(f, f"main/zdma_controller/cack", f"main/ps_gdma_cack")
            connect_bd_net(f, f"main/zdma_controller/tvld", f"main/ps_gdma_tvld")
            connect_bd_net(f, f"main/zdma_controller/tack", f"main/ps_gdma_tack")
            connect_bd_net(f, f"main/zdma_controller/cvld", f"main/ps_gdma_cvld")
            connect_bd_net(f, f"main/ps_gdma_irq_dataport/gdma_irq", f"main/ps_gdma_irq")
            
            # Create a concatenator for the clock signals
            create_concatenator(f, "main/xlconcat_ps_gdma_clk", [1]*8)
            connect_bd_net(f, f"main/xlconcat_ps_gdma_clk/dout", f"main/ps_gdma_clk")
            for i in range(8):
                connect_bd_net(f, f"main/xlconcat_ps_gdma_clk/In{i}", seq_clk_pin)
            
                
            # ------------------- AXI Address Assignment -------------------- #
            
            # Paths through the memory smartconnect
            for target_address_space in memory_smartconnect_target_address_spaces:          
                for properties in self.config["memory"].values():
                    # Make sure not to map the PS into itself     
                    if "ps/Data" in target_address_space and properties["segment"].startswith("/ps/"):
                        exclude_bd_addr_seg(f, target_address_space, properties["segment"])
                    else:
                        assign_bd_address(f, 
                                        target_address_space=target_address_space,
                                        offset=properties["address"], 
                                        range=properties["size_bits"] // 8, 
                                        addr_seg=properties["segment"])
                
                for i in range(4):
                    assign_bd_address(f, 
                        target_address_space=target_address_space, 
                        offset=self.config[f"dac_tile{i}_sample_memory"]["address"], 
                        range=4*self.config[f"dac_tile{i}_sample_memory"]["size_bits"] // 8, 
                        addr_seg=f"main/dac_tile{i}_memory/" + self.config[f"dac_tile{i}_sample_memory"]["segment"])

                if self._num_cmaccs > 0:
                    assign_bd_address(f, 
                        target_address_space=target_address_space, 
                        offset=self.config["stream_processing_path"][f"cmacc_kernel_memory_controller"]["base_address"], 
                        range=self._num_cmaccs*self._max_cmacc_memory*4, 
                        addr_seg=f"main/cmacc_kernel_memory/" + self.config["stream_processing_path"][f"cmacc_kernel_memory_controller"]["segment"])
                
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    addr_seg=f"main/stream_processing_input_switch/" + self.config["stream_processing_path"][f"input_switch"]["axi_segment"], 
                    offset=self.config["stream_processing_path"][f"input_switch"]["axi_address"], 
                    range=self.config["stream_processing_path"][f"input_switch"]["axi_size_bits"] // 8)
                
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    addr_seg=f"main/adc_input_switch/" + self.config["stream_processing_path"][f"adc_input_switch"]["axi_segment"], 
                    offset=self.config["stream_processing_path"][f"adc_input_switch"]["axi_address"], 
                    range=self.config["stream_processing_path"][f"adc_input_switch"]["axi_size_bits"] // 8)
                    
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    addr_seg="main/rfdc/" + self.config["rfdc"]["axi_segment"], 
                    offset=self.config["rfdc"]["axi_address"], 
                    range=self.config["rfdc"]["axi_size_bits"] // 8)
                
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    offset=self.config["sequencer_instruction_memory"]["address"], 
                    range=self.config["sequencer_instruction_memory"]["size_bits"] // 8, 
                    addr_seg=f"main/instruction_memory/" + self.config["sequencer_instruction_memory"]["segment"])
                
                # Exclude the QSPI
                for gp in range(4):
                    if "PS_S_AXI_HPC0" in self.config["ps_axi_slaves"]:
                        exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HPC0_QSPI")
                    if "PS_S_AXI_HPC1" in self.config["ps_axi_slaves"]:
                        exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HPC1_QSPI")
                    if "PS_S_AXI_HP0" in self.config["ps_axi_slaves"]:
                        exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HP0_QSPI")
                    if "PS_S_AXI_HP1" in self.config["ps_axi_slaves"]:
                        exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HP1_QSPI")            
                    
            for target_address_space in sequencer_memory_target_address_spaces:
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    offset=self.config["sequencer_cache_memory"]["address"], 
                    range=self.config["sequencer_cache_memory"]["size_bits"] // 8, 
                    addr_seg=f"main/cache_memory/" + self.config["sequencer_cache_memory"]["segment"])
                
    def stream_inputs(self):
        """
        Create lists of input port numbers for the input types available.
        This function can be used when you know you want to use an input of a
        particular kind, but do not know which port numbers will provide that
        input.
        
        :return: A ``dict`` whose keys are input kinds and whose values are 
            lists, whose elements are port numbers for inputs of the kind
            specified by the key
        """
        
        memory_ports = {"memory": [], "ADC_switch": []}
        for idx,inp in enumerate(self.config["stream_processing_path"]["inputs"]):
            if inp["kind"] == "memory" or inp["kind"] == "ADC_switch":
                memory_ports[inp["kind"]].append(idx)
            elif inp["kind"] == "ADC":
                memory_ports[f"ADC{inp['channel']}"] = [idx]
            else:
                raise ValueError(f"Unexpected input kind in firmware: {inp['kind']}")
        return memory_ports
    
    def stream_modules(self):
        """
        Create lists of module numbers for the module types available. This
        function can be used when you know you want to process a stream with
        a particular kind of module, but do not know which module number to 
        use.
        
        :return: A ``dict`` whose keys are module kinds and whose values are 
            lists, the elements of which are port numbers for modules of the 
            kind specified by the corresponding key.
        """
        
        modules = {"fifo": [], "cmacc": []}
        for idx,module in enumerate(self.config["stream_processing_path"]['modules']):
            modules[module["kind"]].append(idx)
                
        return modules
    
        