__all__ = ["Firmware", "DEFAULT_CONFIG"]

import os
import json

from .hdl import BusDevice, BusDecoder, BusDataport, BusDataMoverController, AXIMemoryArray, connect_bd_net, connect_bd_intf_net, create_ip, create_module, create_concatenator, create_slice, set_property, assign_bd_address, exclude_bd_addr_seg
from .utils import next_highest_power_of_2

class Firmware:
    """
    The standard Acadia firmware. Handcrafted, artisanal FPGA logic with notes
    of silicon and garnished with hedgehog quills.
    """

    NUM_DACS = 16
    NUM_ADCS = 16

    def __init__(self, config=None):
        """
        :param config: Dictionary containing firmware constants
        :type config: dict
        :param directory: Directory in which the project should be created
        :type directory: str
        """
        if config is not None:
            self.config = config
        else:
            from .firmware_configurations import DEFAULT_CONFIG
            self.config = DEFAULT_CONFIG
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
        self.write_hedgehog_tcl(directory,
                                os.path.join(directory, "hedgehog.tcl"),
                                os.path.join(directory, "hedgehog.xdc"))

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

        self.dma_trigger = BusDataport(name="dma_trigger", ports=_dma_trigger_ports)
        self.sequencer_bus_decoder.add(self.dma_trigger, pipeline=self.config["sequencer_bus"]["dma_trigger_dataport"]["bus_pipeline"])
        self._hdl_modules.append(self.dma_trigger)

        self.dma_running = BusDataport(name="dma_running", ports=_dma_running_ports)
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
            # Some modules use both mm2s and s2mm, but we won't necessarily need
            # a separate AXI master since AXI is full duplex
            if module["kind"] == "adder":
                device = BusDevice(f"module{idx}_mm2s_datamover_controller", size=4)
                self._datamover_controllers.append(device)
                self.sequencer_bus_decoder.add(device, pipeline=module["datamover_controller_bus_pipeline"])
            
            if module["kind"] != "memory":
                registers = BusDevice(f"module{idx}_registers", size=16)
                self.sequencer_bus_decoder.add(registers, pipeline=module["registers_bus_pipeline"])
            
            device = BusDevice(f"module{idx}_s2mm_datamover_controller", size=4)
            self._datamover_controllers.append(device)
            self.sequencer_bus_decoder.add(device, pipeline=module["datamover_controller_bus_pipeline"])
            
            self._memory_smartconnect_masters += (2 if module["kind"] == "adder" else 1)
                
        # Create dataports for interacting with the PS GPIO
        for gpio_num in [3,4,5]:
            _ps_gpio_dataports = []

            _ps_gpio_dataports += [{"name": f"gpio_out",
                                    "direction": BusDataport.INPUT,
                                    "offset": 0,
                                    "width": self.config["sequencer_bus"][f"ps_gpio{gpio_num}"]["width"],
                                    "pipeline": self.config["sequencer_bus"][f"ps_gpio{gpio_num}"]["pipeline"]}]
            _ps_gpio_dataports += [{"name": f"gpio_in",
                                    "direction": BusDataport.OUTPUT,
                                    "offset": 0,
                                    "width": self.config["sequencer_bus"][f"ps_gpio{gpio_num}"]["width"],
                                    "gate": BusDataport.GATE_REGCE,
                                    "pipeline": self.config["sequencer_bus"][f"ps_gpio{gpio_num}"]["pipeline"]}]

            _ps_gpio = BusDataport(name=f"ps_gpio{gpio_num}", ports=_ps_gpio_dataports)
            self.sequencer_bus_decoder.add(_ps_gpio, pipeline=self.config["sequencer_bus"][f"ps_gpio{gpio_num}"]["bus_pipeline"])
            self._hdl_modules.append(_ps_gpio)

        _ps_irq_dataports = []
        for irq in range(2):
            _ps_irq_dataports.append(
                {"name": f"irq{irq}",
                "direction": BusDataport.OUTPUT,
                "offset": irq,
                "width": 1,
                "gate": BusDataport.GATE_REGCE,
                "pipeline": self.config["sequencer_bus"]["ps_irq"]["irq_pipeline"]})

        _ps_irq_dataports.append(
            {"name": f"gdma_irq",
            "direction": BusDataport.INPUT,
            "offset": 2,
            "width": 8,
            "pipeline": self.config["sequencer_bus"]["ps_irq"]["gdma_pipeline"]})

        self.ps_irq = BusDataport(name="ps_irq", ports=_ps_irq_dataports)
        self.sequencer_bus_decoder.add(self.ps_irq, pipeline=self.config["sequencer_bus"]["ps_irq"]["bus_pipeline"])
        self._hdl_modules.append(self.ps_irq)

        # Create a register file for RFDC real-time updates and connect it to the sequencer bus
        self.rfdc_rts_regs = BusDevice("rfdc_rts_regs", size=256)
        self.sequencer_bus_decoder.add(self.rfdc_rts_regs, pipeline=self.config["sequencer_bus"]["rfdc_rts"]["bus_pipeline"])
        
        _io_dataports = []
        _io_dataports.append(
            {"name": f"DACIO",
            "direction": BusDataport.OUTPUT,
            "offset": 0,
            "width": 16,
            "pipeline": self.config["sequencer_bus"]["io_dataport"]["DACIO_pipeline"]})
        _io_dataports.append(
            {"name": f"ADCIO",
            "direction": BusDataport.INPUT,
            "offset": 16,
            "width": 16,
            "pipeline": self.config["sequencer_bus"]["io_dataport"]["ADCIO_pipeline"]})
            
        self.rf_io = BusDataport(name="io", ports=_io_dataports)
        self.sequencer_bus_decoder.add(self.rf_io, pipeline=self.config["sequencer_bus"]["io_dataport"]["bus_pipeline"])
        self._hdl_modules.append(self.rf_io)

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

        self.dac_dma_descriptor_memory_controller = AXIMemoryArray(f"dac_dma_descriptor", 
            size_bits=self.config["dac_dma_descriptor_memory"]["size_bits"], 
            width=64, 
            elements=self.NUM_DACS, 
            read_only=True,
            use_rst=False,
            controller_width=self.config["dac_dma_descriptor_memory"]["controller_width"],
            synchronous=self.config["dac_dma_descriptor_memory"]["synchronous"],
            primitive=self.config["dac_dma_descriptor_memory"]["primitive"], 
            controller_port_input_pipeline=self.config["dac_dma_descriptor_memory"]["controller_port_input_pipeline"],
            controller_port_output_pipeline=self.config["dac_dma_descriptor_memory"]["controller_port_output_pipeline"],   
            user_port_input_pipeline=self.config["dac_dma_descriptor_memory"]["dma_port_input_pipeline"],
            user_port_output_pipeline=self.config["dac_dma_descriptor_memory"]["dma_port_output_pipeline"])
        self._hdl_modules.append(self.dac_dma_descriptor_memory_controller)

        self.adc_dma_descriptor_memory_controller = AXIMemoryArray(f"adc_dma_descriptor", 
            size_bits=self.config["adc_dma_descriptor_memory"]["size_bits"], 
            width=64, 
            controller_width=self.config["adc_dma_descriptor_memory"]["controller_width"],
            elements=self.NUM_ADCS, 
            read_only=True,
            use_rst=False,
            synchronous=self.config["adc_dma_descriptor_memory"]["synchronous"],
            primitive=self.config["adc_dma_descriptor_memory"]["primitive"], 
            controller_port_input_pipeline=self.config["adc_dma_descriptor_memory"]["controller_port_input_pipeline"],
            controller_port_output_pipeline=self.config["adc_dma_descriptor_memory"]["controller_port_output_pipeline"],   
            user_port_input_pipeline=self.config["adc_dma_descriptor_memory"]["dma_port_input_pipeline"],
            user_port_output_pipeline=self.config["adc_dma_descriptor_memory"]["dma_port_output_pipeline"])
        self._hdl_modules.append(self.adc_dma_descriptor_memory_controller)
        
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

    def write_hedgehog_tcl(self, ip_directory, tcl_filename="hedgehog.tcl", constraints_filename="hedgehog.xdc"):
        """
        Write a TCL script to populate the HEDGEHOG logic in the standard image. 
        """

        if not hasattr(self, "_hdl_filename"):
            raise ValueError("Call `write_hdl` before `write_hedgehog_tcl`.")
        with open(tcl_filename, "w") as f, open(constraints_filename, "w") as constraints:
            f.write(f"read_vhdl {self._hdl_filename}\n")
            
            # Write the TCL that will generate the IP for the AXI memory controllers
            memory_tcl = self.cache_memory_controller.generate_ip_tcl(ip_directory)
            memory_tcl += self.instruction_memory_controller.generate_ip_tcl(ip_directory)
            memory_tcl += self.dac_dma_descriptor_memory_controller.generate_ip_tcl(ip_directory)
            memory_tcl += self.adc_dma_descriptor_memory_controller.generate_ip_tcl(ip_directory)
            
            if self._num_cmaccs > 0:
                memory_tcl += self.cmacc_kernel_memory_controller.generate_ip_tcl(ip_directory)
            
            for controller in self.dac_tile_memory_controllers:
                memory_tcl += controller.generate_ip_tcl(ip_directory)
            
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
            
            # We'll create an MMCM that will generate all the PL clocks
            create_ip(f, name="hedgehog/clk_wiz", vlnv="xilinx.com:ip:clk_wiz:6.0")
            set_property(f, name="hedgehog/clk_wiz", properties={"PRIM_IN_FREQ.VALUE_SRC": "USER"})
            
            clock_properties = (
                "CONFIG.PRIMITIVE {MMCM} "
                "CONFIG.USE_DYN_RECONFIG {false} "
                "CONFIG.USE_PHASE_ALIGNMENT {true} "
                f"CONFIG.PRIM_SOURCE {{{self.config['clocks']['input_source_type']}}} "
                f"CONFIG.PRIM_IN_FREQ {{{self.config['clocks']['input_freq_hz']*1e-6}}} "
                "CONFIG.FEEDBACK_SOURCE {FDBK_AUTO} "
                "CONFIG.MMCM_DIVCLK_DIVIDE {1} "
                "CONFIG.MMCM_BANDWIDTH {OPTIMIZED} "
                "CONFIG.MMCM_COMPENSATION {AUTO} "
                f"CONFIG.CLKIN1_JITTER_PS {{{self.config['clocks']['input_jitter_ps']}}} "
                "CONFIG.USE_INCLK_SWITCHOVER {false} ")
            
            clock_properties += f"CONFIG.NUM_OUT_CLKS {{{len(self.config['clocks']['generated_clocks'])}}} "
            
            for i,(clk,freq) in enumerate(self.config["clocks"]["generated_clocks"].items()):
                clock_properties += (
                    f"CONFIG.CLKOUT{i+1}_USED {{true}} "
                    f"CONFIG.CLKOUT{i+1}_REQUESTED_OUT_FREQ {{{freq*1e-6}}} "
                    f"CONFIG.CLK_OUT{i+1}_PORT {{{clk}}} "
                    f"CONFIG.CLKOUT{i+1}_DRIVES {{Buffer}} "
                )

            set_property(f, name="hedgehog/clk_wiz", properties=clock_properties)
            
            # Connect the reset
            create_ip(f, name="hedgehog/clk_wiz_reset_inverter", vlnv="xilinx.com:ip:util_vector_logic:2.0")
            set_property(f, name="hedgehog/clk_wiz_reset_inverter", 
                         properties={"C_SIZE": 1, 
                                     "C_OPERATION": "not", 
                                     "LOGO_FILE": "data/sym_notgate.png"})
            connect_bd_net(f, "hedgehog/PS_resetn", "hedgehog/clk_wiz_reset_inverter/Op1")
            connect_bd_net(f, "hedgehog/clk_wiz_reset_inverter/Res", "hedgehog/clk_wiz/reset")

            # Connect the CLK104 PL clock buffer output to the clock wizard and apply a constraint
            connect_bd_net(f, f"hedgehog/pl_clk_bufg/BUFG_O", f"hedgehog/clk_wiz/clk_in1")
            constraints.write("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets -of_objects [get_pins acadia_bd_i/hedgehog/pl_clk_bufg/BUFG_O]]\n")
            constraints.write("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets -of_objects [get_pins acadia_bd_i/hedgehog/clk_wiz/inst/mmcme4_adv_inst/CLKIN1]]\n")

            # constraints.write("set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets acadia_bd_i/hedgehog/clk_wiz/inst/CLK_CORE_DRP_I/clk_inst/clk_in1_acadia_bd_clk_wiz_0]\n")
            f.write(f"set_property -dict [list CONFIG.FREQ_HZ {{{self.config['clk104_pl_clk']['freq_hz']}}}] [get_bd_intf_ports CLK104_PL_CLK]\n")
            
            # Connect the clock from the 8A34001 to the clocking wizard
            # connect_bd_net(f, "hedgehog/clk_8A34001_out3_ibufds/IBUF_OUT", f"hedgehog/clk_wiz/clk_in2")
            f.write(f"set_property -dict [list CONFIG.FREQ_HZ {{{self.config['clk_8A34001_Q3_out']['freq_hz']}}}] [get_bd_intf_ports CLK_8A34001_Q3_OUT]\n")

            # Expose the locked signal to the PS
            connect_bd_net(f, f"hedgehog/clk_wiz_locked", f"hedgehog/clk_wiz/locked")

            # Create resets modules for all of the generated clocks
            for clk in self.config["clocks"]["generated_clocks"].keys():
                create_ip(f, name=f"hedgehog/proc_sys_reset_{clk}", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
                connect_bd_net(f, f"hedgehog/proc_sys_reset_{clk}/slowest_sync_clk", f"hedgehog/clk_wiz/{clk}")
                connect_bd_net(f, f"hedgehog/proc_sys_reset_{clk}/ext_reset_in", f"hedgehog/PS_resetn")
                connect_bd_net(f, f"hedgehog/proc_sys_reset_{clk}/dcm_locked", f"hedgehog/clk_wiz/locked")
            
            # ------------------- PS AXI Clocks -------------------- #
            for ps_clock, clock in self.config["ps_axi_clocks"].items():
                connect_bd_net(f, f"hedgehog/clk_wiz/{clock}", f"hedgehog/{ps_clock}_aclk")

            # ------------------- AXI Interconnects and SmartConnects -------------------- #

            # Create an AXI-lite SmartConnect for simple configuration peripherals
            create_ip(f, name="hedgehog/lite_crossbar", vlnv="xilinx.com:ip:axi_crossbar:2.1")
            
            slaves = 1
            if len([inp for inp in self.config["stream_processing_path"]["inputs"] if inp["kind"] == "ADC_switch"]) > 0:
                slaves += 1
            if self._num_cmaccs > 0:
                slaves += 1
            
            set_property(f, 
                         name="hedgehog/lite_crossbar", 
                         properties={"NUM_MI": slaves, 
                                     "NUM_SI": 1, 
                                     "STRATEGY": 2, # 1 = Minimize area, 2 = maximize performance
                                     "ADDR_WIDTH": 40,
                                     "CONNECTIVITY_MODE": "SAMD",
                                     "R_REGISTER": 1})
            connect_bd_net(f, f"hedgehog/lite_crossbar/aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, 
                           f"hedgehog/lite_crossbar/aresetn", 
                           f"hedgehog/proc_sys_reset_seq_clk/interconnect_aresetn")
            lite_crossbar_slave = 0
            
            # Create an AXI Crossbar for more rapid access to cache and instruction memories
            # 1 Master: PS AXI Master 1 (plus any DataMovers)
            # 2 slaves: cache, instruction memory
            create_ip(f, name="hedgehog/sequencer_memory_crossbar", vlnv="xilinx.com:ip:axi_crossbar:2.1")
            set_property(f, name="hedgehog/sequencer_memory_crossbar", 
                         properties={"NUM_SI": 1,
                                     "NUM_MI": 2,
                                     "STRATEGY": 1,
                                     "CONNECTIVITY_MODE": "SAMD"})
            connect_bd_net(f, 
                           "hedgehog/sequencer_memory_crossbar/aclk", 
                           "hedgehog/clk_wiz/" + self.config["sequencer_memory_crossbar"]["clock"])
            connect_bd_net(f, 
                           "hedgehog/sequencer_memory_crossbar/aresetn", 
                           f"hedgehog/proc_sys_reset_{self.config['sequencer_memory_crossbar']['clock']}/interconnect_aresetn")
            sequencer_memory_crossbar_target_address_spaces = ["/ps/Data"]

            # Connect it to the PS
            connect_bd_intf_net(f, f"hedgehog/sequencer_memory_crossbar/S00_AXI", f"hedgehog/PS_M_AXI1")
            sequencer_memory_crossbar_master = 1
            
            # Create a SmartConnect for most memory in the system
            # Number of masters determined entirely by the stream processing path
            # 10 Slaves: PS AXI Slave HPC0-1, 
            #           PS AXI Slave HP0-1, 
            #           PL DDR C0-1,
            #           DAC Tile 0-3 Memory,
            #           DAC and ADC DMA Descriptor Memory, 
            #           
            create_ip(f, name="hedgehog/memory_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, name="hedgehog/memory_smartconnect", 
                         properties={"NUM_MI": 14, 
                                     "NUM_SI": self._memory_smartconnect_masters, 
                                     "NUM_CLKS": 4})
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk", f"hedgehog/clk_wiz/hs_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk1", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk2", f"hedgehog/DDR4_C0_ui_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aclk3", f"hedgehog/DDR4_C1_ui_clk")
            connect_bd_net(f, f"hedgehog/memory_smartconnect/aresetn", f"hedgehog/proc_sys_reset_hs_clk/interconnect_aresetn")
            memory_smartconnect_target_address_spaces = ["/ps/Data"]

            # Connect it to the PS and various interface ports
            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/S00_AXI", f"hedgehog/PS_M_AXI0")
            memory_smartconnect_master = 1
            
            # Set some pipeline properties in the switchboard
            set_property(f, 
                         "hedgehog/memory_smartconnect", 
                         properties=" CONFIG.ADVANCED_PROPERTIES { __view__ { timing { SW0 { AR_M_PIPE 1 AR_S_PIPE 1 AW_M_PIPE 1 AW_S_PIPE 1 B_M_PIPE 1 B_S_PIPE 1 R_M_PIPE 1 R_S_PIPE 1 W_M_PIPE 1 W_S_PIPE 1 } } }}")
            
            # Connect the lite smartconnect to the memory smartconnect through an axi-lite register slice
            # create_ip(f, "hedgehog/lite_crossbar_reg", "xilinx.com:ip:axi_register_slice:2.1")
            # set_property(f, "hedgehog/lite_crossbar_reg", properties="CONFIG.DATA_WIDTH.VALUE_SRC USER")
            # set_property(f, "hedgehog/lite_crossbar_reg", properties={"DATA_WIDTH": 32})
            # connect_bd_net(f, "hedgehog/lite_crossbar_reg/aclk", "hedgehog/clk_wiz/seq_clk")
            # connect_bd_net(f, "hedgehog/lite_crossbar_reg/aresetn", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            # connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M00_AXI", f"hedgehog/lite_crossbar_reg/S_AXI")
            # connect_bd_intf_net(f, f"hedgehog/lite_crossbar_reg/M_AXI", f"hedgehog/lite_crossbar/S00_AXI")
            connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M00_AXI", f"hedgehog/lite_crossbar/S00_AXI")
            memory_smartconnect_slave = 1
            
            for m in [f"hedgehog/PS_S_AXI_HPC0", 
                      f"hedgehog/PS_S_AXI_HPC1", 
                      f"hedgehog/PS_S_AXI_HP0",
                      f"hedgehog/PS_S_AXI_HP1",
                      f"hedgehog/DDR4_C0_S_AXI",
                      f"hedgehog/DDR4_C1_S_AXI"]:
                connect_bd_intf_net(f, f"hedgehog/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI", m)
                memory_smartconnect_slave += 1
            
            # ------------------- RF Data Converters -------------------- #

            create_ip(f, name="hedgehog/rfdc", vlnv="xilinx.com:ip:usp_rf_data_converter:2.4")
            
            # Auto-generated config string by Vivado
            rfdc_config_string = ("CONFIG.ADC_DSA_RTS {true} "
                                  "CONFIG.DAC_VOP_RTS {true} "
                                  f"CONFIG.Axiclk_Freq {{{self.config['rfdc']['axi_clk_freq_hz']*1e-6}}} ")
            
            for dc in ["adc", "dac"]:
                rfdc_config_string += f"CONFIG.{dc.upper()}_NCO_RTS {{true}} "
                rfdc_config_string += f"CONFIG.{dc.upper()}_RTS {{true}} "
                
                for tile in range(4):               
                    tile_stream_clock = self.config["clocks"]["generated_clocks"][self.config['rfdc'][dc]['tile_axis_clocks'][tile]]    
                    rfdc_config_string += (
                        f"CONFIG.{dc.upper()}{tile}_Clock_Dist {{{self.config['rfdc'][dc]['tile_distribute_clk'][tile]}}} "
                        f"CONFIG.{dc.upper()}{tile}_Clock_Source {{{self.config['rfdc'][dc]['tile_clk_source'][tile]}}} "
                        f"CONFIG.{dc.upper()}{tile}_Enable {{1}} "
                        f"CONFIG.{dc.upper()}{tile}_Fabric_Freq {{{tile_stream_clock*1e-6:.3f}}} "
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

                        scale = self.config['rfdc'][dc]['tile_sample_rate_hz'][tile] * 32 / (interface_width * tile_stream_clock)
                        
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
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aclk", f"hedgehog/clk_wiz/{self.config['rfdc']['dac']['tile_axis_clocks'][i]}")
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")        
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aclk", f"hedgehog/clk_wiz/{self.config['rfdc']['adc']['tile_axis_clocks'][i]}")
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")

            # Connect RFDC to the config smartconnect and assign it address space
            connect_bd_intf_net(f, f"hedgehog/lite_crossbar/M{lite_crossbar_slave:02d}_AXI", "hedgehog/rfdc/s_axi")
            lite_crossbar_slave += 1
            
            assign_bd_address(f, 
                              "/ps/Data", 
                              "hedgehog/rfdc/" + self.config["rfdc"]["axi_segment"], 
                              self.config["rfdc"]["axi_address"], 
                              self.config["rfdc"]["axi_size_bits"] // 8)

            # Synchronize the SYSREF signal from the CLK104 to the stream clock of DAC tile 0
            create_module(f, f"hedgehog/pl_sysref_capture", "acadia_sysref_capture")
            connect_bd_intf_net(f, "hedgehog/CLK104_PL_SYSREF", "hedgehog/pl_sysref_capture/sysref")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/clk", f"hedgehog/clk_wiz/{self.config['rfdc']['dac']['tile_axis_clocks'][0]}")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/sysref_out", "hedgehog/rfdc/user_sysref_dac")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/sysref_out", "hedgehog/rfdc/user_sysref_adc")
            
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
            if self.config["sequencer_bus"]["rfdc_rts"]["nco_clk"] != "seq_clk":
                set_property(f, "hedgehog/rfdc_rts_regs", properties={"SYNCHRONOUS": "false"})
            
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nco_dest_clk", f"hedgehog/clk_wiz/" + self.config["sequencer_bus"]["rfdc_rts"]["nco_clk"])
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
            for module in self._hdl_modules:
                if isinstance(module, BusDataport):
                    create_module(f, f"hedgehog/{module.name}_dataport", module.name)
                    connect_bd_intf_net(f, f"hedgehog/{module.name}_dataport/master_bus", f"hedgehog/sequencer_bus_decoder/{module.name}")
                    connect_bd_net(f, f"hedgehog/{module.name}_dataport/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                    
            # ------------------- Sequencer Cache -------------------- #
            # Add cache memory and connect it to the sequencer bus decoder
            create_module(f, f"hedgehog/cache_memory", f"cache_axi_memory")
            
            # Connect the cache to the smartconnect
            connect_bd_intf_net(f, f"hedgehog/cache_memory/s_axi", f"hedgehog/sequencer_memory_crossbar/M00_AXI")
            connect_bd_net(f, 
                           "hedgehog/cache_memory/s_axi_aclk", 
                           "hedgehog/clk_wiz/" + self.config['sequencer_memory_crossbar']['clock'])
            connect_bd_net(f, 
                           "hedgehog/cache_memory/s_axi_aresetn", 
                           f"hedgehog/proc_sys_reset_{self.config['sequencer_memory_crossbar']['clock']}/peripheral_aresetn")
            
            # Connect the cache to the sequencer bus decoder
            connect_bd_intf_net(f, 
                                f"hedgehog/sequencer_bus_decoder/cache", 
                                f"hedgehog/cache_memory/mem0")
            
            # ------------------- Sequencer Instruction Memory -------------------- #
            create_module(f, "hedgehog/instruction_memory", "instruction_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/instruction_memory/s_axi", f"hedgehog/sequencer_memory_crossbar/M01_AXI")
            connect_bd_net(f, 
                           "hedgehog/instruction_memory/s_axi_aclk", 
                           "hedgehog/clk_wiz/" + self.config['sequencer_memory_crossbar']['clock'])
            connect_bd_net(f, 
                           "hedgehog/instruction_memory/s_axi_aresetn", 
                           f"hedgehog/proc_sys_reset_{self.config['sequencer_memory_crossbar']['clock']}/peripheral_aresetn")
            
            # Connect it to the sequencer
            connect_bd_intf_net(f, f"hedgehog/sequencer/instruction_mem", f"hedgehog/instruction_memory/mem0")
            
            # ------------------- Sequencer Flags -------------------- #
            create_ip(f, name="hedgehog/xlconst_0", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name="hedgehog/xlconst_0", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
            connect_bd_net(f, f"hedgehog/sequencer/ext_in", f"hedgehog/xlconst_0/Dout")
            
            # ------------------- DAC Memory -------------------- #
            for tile in range(4):
                create_module(f, f"hedgehog/dac_tile{tile}_memory", f"dac_tile{tile}_axi_memory")
                connect_bd_intf_net(f, f"hedgehog/dac_tile{tile}_memory/s_axi", f"hedgehog/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI")
                connect_bd_net(f, f"hedgehog/dac_tile{tile}_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/dac_tile{tile}_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                memory_smartconnect_slave += 1
            
            # ------------------- DAC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/dac_dma_descriptor_memory", f"dac_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi", f"hedgehog/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI")
            connect_bd_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            memory_smartconnect_slave += 1
            
            # ------------------- DAC Real-Time DMAs -------------------- #
            for channel in range(self.NUM_DACS):
                tile = channel // 4
                block = channel % 4

                # Create a DMA for the DAC and connect it to the read port of the BRAM
                create_module(f, f"hedgehog/dac{channel}_dma", "acadia_dma")
                set_property(f, 
                             f"hedgehog/dac{channel}_dma", 
                             properties={
                                "ADDRESS_WIDTH": next_highest_power_of_2(
                                                    self.config[f"dac_tile{tile}_sample_memory"]["size_bits"] 
                                                    // self.config[f"rfdc"]["dac"]["channel_interface_width"][channel], 
                                                log=True),
                                "DESCRIPTOR_MEM_ADDR_WIDTH": next_highest_power_of_2(self.config["dac_dma_descriptor_memory"]["size_bits"] // 64, log=True)})
                connect_bd_net(f, f"hedgehog/dac{channel}_dma/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/dac{channel}_dma/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                connect_bd_net(f, f"hedgehog/dac{channel}_dma/address_out_tdata", f"hedgehog/dac_tile{tile}_memory/mem{block}_addr")
                connect_bd_net(f, f"hedgehog/dac{channel}_dma/data_address_invalid", f"hedgehog/dac_tile{tile}_memory/mem{block}_rst")


                # Connect the DAC memory output to the RFDAC interface through a pipeline
                create_module(f, f"hedgehog/dac{channel}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/dac{channel}_pipeline", 
                             properties={"WIDTH": self.config['rfdc']['dac']['channel_interface_width'][channel], 
                                         "STAGES": self.config['rfdc']['dac']['channel_pipeline_stages'][channel]})
                
                connect_bd_net(f, f"hedgehog/dac{channel}_pipeline/clk", f"hedgehog/clk_wiz/" + self.config['rfdc']['dac']['tile_axis_clocks'][tile])
                connect_bd_net(f, f"hedgehog/dac_tile{tile}_memory/mem{block}_dout", f"hedgehog/dac{channel}_pipeline/s_axis_tdata")
                connect_bd_intf_net(f, f"hedgehog/dac{channel}_pipeline/m_axis", f"hedgehog/rfdc/s{tile}{block}_axis")

                # Connect the DAC DMA to the bus and dataports
                connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/dac{channel}_dma", f"hedgehog/dac{channel}_dma/master_bus")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/dac{channel}_dma", f"hedgehog/dac{channel}_dma/trigger")
                connect_bd_net(f, f"hedgehog/dma_running_dataport/dac{channel}_dma", f"hedgehog/dac{channel}_dma/running")
                
                # Connect DAC Descriptor BRAMs and to the DMA                
                connect_bd_intf_net(f, f"hedgehog/dac_dma_descriptor_memory/mem{channel}", f"hedgehog/dac{channel}_dma/DESCRIPTOR_MEM")

                # Connect the data input of the DMA to zeros in order to suppress the
                # critical warning vivado will generate
                create_ip(f, name=f"hedgehog/xlconst_dac{channel}_dma_data_in", vlnv="xilinx.com:ip:xlconstant:1.1")
                set_property(f, name=f"hedgehog/xlconst_dac{channel}_dma_data_in", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
                connect_bd_net(f, f"hedgehog/xlconst_dac{channel}_dma_data_in/dout", f"hedgehog/dac{channel}_dma/data_in")
            
            # ------------------- ADC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/adc_dma_descriptor_memory", f"adc_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi", f"hedgehog/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI")
            connect_bd_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            memory_smartconnect_slave += 1
            
            # ------------------- ADC Real-Time DMAs -------------------- #
            for d in range(self.NUM_ADCS):
                tile = d // 4
                block = d % 4
                create_module(f, f"hedgehog/adc{d}_dma", "acadia_dma")
                set_property(f, 
                             name=f"hedgehog/adc{d}_dma", 
                             properties={"DATA_WIDTH": self.config["stream_processing_path"]["width"],
                                         "DESCRIPTOR_MEM_ADDR_WIDTH": next_highest_power_of_2(self.config["adc_dma_descriptor_memory"]["size_bits"] // 64, log=True)})
                connect_bd_net(f, 
                               f"hedgehog/adc{d}_dma/clk", 
                               f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, 
                               f"hedgehog/adc{d}_dma/nrst", 
                               f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                
                # Connect the data input to the DMA through a pipeline
                create_module(f, f"hedgehog/adc{d}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/adc{d}_pipeline", 
                            properties={"WIDTH": self.config['rfdc']['adc']['channel_interface_width'][d],
                                        "STAGES": self.config['rfdc']['adc']['channel_pipeline_stages'][d]})
                connect_bd_net(f, f"hedgehog/adc{d}_pipeline/clk", "hedgehog/clk_wiz/" + self.config['rfdc']['adc']['tile_axis_clocks'][tile])

                connect_bd_intf_net(f, f"hedgehog/rfdc/m{tile}{block}_axis", 
                                    f"hedgehog/adc{d}_pipeline/S_AXIS")
                
                connect_bd_net(f,
                               f"hedgehog/adc{d}_pipeline/m_axis_tdata",
                               f"hedgehog/adc{d}_dma/data_in")

                # Connect the ADC DMA signals to the bus and dataports
                connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/adc{d}_dma", f"hedgehog/adc{d}_dma/master_bus")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/adc{d}_dma", f"hedgehog/adc{d}_dma/trigger")
                connect_bd_net(f, f"hedgehog/dma_running_dataport/adc{d}_dma", f"hedgehog/adc{d}_dma/running")
                
                # Connect to descriptor memory
                connect_bd_intf_net(f, 
                                    f"hedgehog/adc{d}_dma/descriptor_mem", 
                                    f"hedgehog/adc_dma_descriptor_memory/mem{d}")
            
            # ------------------- Stream Processing Path -------------------- #
            
            # Create an AXI switch for multiplexing the ADC outputs to the stream processing path
            # Some ADCs will be directly connected to the stream input path input switch, and the remainder
            # will have their own switch
            adc_direct_inputs = [inp["channel"] for inp in self.config["stream_processing_path"]["inputs"] if inp["kind"] == "ADC"]
            adc_switch_inputs = [f"ADC{i}" for i in range(self.NUM_ADCS) if i not in adc_direct_inputs]
            num_adc_switch_outputs = len([inp for inp in self.config["stream_processing_path"]["inputs"] if inp["kind"] == "ADC_switch"])
            
            create_ip(f, name="hedgehog/stream_processing_input_switch", vlnv="xilinx.com:ip:axis_switch:1.1")
            set_property(f, name="hedgehog/stream_processing_input_switch", 
                             properties="CONFIG.TDATA_NUM_BYTES.VALUE_SRC USER "
                                        "CONFIG.HAS_TREADY.VALUE_SRC USER "
                                        "CONFIG.HAS_TSTRB.VALUE_SRC USER "
                                        "CONFIG.HAS_TKEEP.VALUE_SRC USER "
                                        "CONFIG.HAS_TLAST.VALUE_SRC USER "
                                        "CONFIG.TID_WIDTH.VALUE_SRC USER "
                                        "CONFIG.TDEST_WIDTH.VALUE_SRC USER "
                                        "CONFIG.TUSER_WIDTH.VALUE_SRC USER")
            set_property(f, name="hedgehog/stream_processing_input_switch", 
                             properties=f"CONFIG.NUM_SI {{{len(self.config['stream_processing_path']['inputs'])}}} "
                                        f"CONFIG.NUM_MI {{{len(self.config['stream_processing_path']['modules'])}}} "
                                        "CONFIG.ROUTING_MODE {1} "
                                        f"CONFIG.TDATA_NUM_BYTES {{{self.config['stream_processing_path']['width'] // 8}}} "
                                        "CONFIG.DECODER_REG {1} "
                                        "CONFIG.OUTPUT_REG {1} "
                                        "CONFIG.HAS_TLAST {1} "
                                        "CONFIG.HAS_TREADY {0} "
                                        "CONFIG.TDEST_WIDTH {0}")
            
            connect_bd_net(f, f"hedgehog/stream_processing_input_switch/aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/stream_processing_input_switch/aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            connect_bd_net(f, 
                            "hedgehog/stream_processing_input_switch/s_axi_ctrl_aclk", 
                            f"hedgehog/clk_wiz/{self.config['stream_processing_path']['input_switch']['axi_clk']}")
                
            connect_bd_net(f, 
                            "hedgehog/stream_processing_input_switch/s_axi_ctrl_aresetn", 
                            f"hedgehog/proc_sys_reset_{self.config['stream_processing_path']['input_switch']['axi_clk']}/peripheral_aresetn")
                
                
            connect_bd_intf_net(f, 
                                f"hedgehog/lite_crossbar/M{lite_crossbar_slave:02d}_AXI", 
                                f"hedgehog/stream_processing_input_switch/S_AXI_CTRL")
            lite_crossbar_slave += 1
            assign_bd_address(f, 
                              "/ps/Data", 
                              "hedgehog/stream_processing_input_switch/" + self.config["stream_processing_path"]["input_switch"]["axi_segment"], 
                              self.config["stream_processing_path"]["input_switch"]["axi_address"], 
                              self.config["stream_processing_path"]["input_switch"]["axi_size_bits"] // 8)
                        
            # ------------------- ADC Input Switch -------------------- #
            if num_adc_switch_outputs > 0:
                
                # Create the switch and connect it to the AXI network
                create_ip(f, name="hedgehog/adc_input_switch", vlnv="xilinx.com:ip:axis_switch:1.1")
                set_property(f, name="hedgehog/adc_input_switch", 
                                properties="CONFIG.TDATA_NUM_BYTES.VALUE_SRC USER "
                                            "CONFIG.HAS_TREADY.VALUE_SRC USER "
                                            "CONFIG.HAS_TSTRB.VALUE_SRC USER "
                                            "CONFIG.HAS_TKEEP.VALUE_SRC USER "
                                            "CONFIG.HAS_TLAST.VALUE_SRC USER "
                                            "CONFIG.TID_WIDTH.VALUE_SRC USER "
                                            "CONFIG.TDEST_WIDTH.VALUE_SRC USER "
                                            "CONFIG.TUSER_WIDTH.VALUE_SRC USER")
                set_property(f, name="hedgehog/adc_input_switch", 
                                properties=f"CONFIG.NUM_SI {{{len(adc_switch_inputs)}}} "
                                            f"CONFIG.NUM_MI {{{num_adc_switch_outputs}}} "
                                            "CONFIG.ROUTING_MODE {1} "
                                            f"CONFIG.TDATA_NUM_BYTES {{{self.config['stream_processing_path']['width'] // 8}}} "
                                            "CONFIG.DECODER_REG {1} "
                                            "CONFIG.OUTPUT_REG {1} "
                                            "CONFIG.HAS_TLAST {0} "
                                            "CONFIG.HAS_TREADY {0} "
                                            "CONFIG.TDEST_WIDTH {0}")

                connect_bd_net(f, f"hedgehog/adc_input_switch/aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/adc_input_switch/aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                
                connect_bd_net(f, 
                               "hedgehog/adc_input_switch/s_axi_ctrl_aclk", 
                               f"hedgehog/clk_wiz/{self.config['stream_processing_path']['adc_input_switch']['axi_clk']}")
                
                connect_bd_net(f, 
                               "hedgehog/adc_input_switch/s_axi_ctrl_aresetn", 
                               f"hedgehog/proc_sys_reset_{self.config['stream_processing_path']['adc_input_switch']['axi_clk']}/peripheral_aresetn")
                
                
                connect_bd_intf_net(f, 
                                f"hedgehog/lite_crossbar/M{lite_crossbar_slave:02d}_AXI", 
                                f"hedgehog/adc_input_switch/S_AXI_CTRL")
                lite_crossbar_slave += 1
                assign_bd_address(f, 
                              "/ps/Data", 
                              "hedgehog/adc_input_switch/" + self.config["stream_processing_path"]["adc_input_switch"]["axi_segment"], 
                              self.config["stream_processing_path"]["adc_input_switch"]["axi_address"], 
                              self.config["stream_processing_path"]["adc_input_switch"]["axi_size_bits"] // 8)
            
            # Connect the ADC DMA outputs to the ADC input switch if they're not directly connected to the input switch
            adc_input_switch_master = 0
            direct_connections = [inp["channel"] for inp in self.config["stream_processing_path"]["inputs"] if inp["kind"] == "ADC"]                
            for channel in range(self.NUM_ADCS):
                if channel not in direct_connections:
                    connect_bd_intf_net(f, f"hedgehog/adc{channel}_dma/data_out", 
                                        f"hedgehog/adc_input_switch/S{adc_input_switch_master:02d}_AXIS")
                    adc_input_switch_master += 1
                    
            # ------------------- DataMover-driven stream processing inputs -------------------- #
            adc_input_switch_slave = 0
            for idx,inp in enumerate(self.config["stream_processing_path"]["inputs"]):
                if inp["kind"] == "ADC":
                    # Connect the corresponding ADC DMA data output directly to the switch
                    connect_bd_intf_net(f, f"hedgehog/adc{inp['channel']}_dma/data_out", 
                                        f"hedgehog/stream_processing_input_switch/S{idx:02d}_AXIS")
                elif inp["kind"] == "ADC_switch":
                    # Connect an output of the ADC switch to the input switch
                    connect_bd_intf_net(f, f"hedgehog/adc_input_switch/M{adc_input_switch_slave:02d}_AXIS", 
                                        f"hedgehog/stream_processing_input_switch/S{idx:02d}_AXIS")
                    adc_input_switch_slave += 1
                elif inp["kind"] == "memory":
                    # First, create the DataMover Controller and connect it to the bus
                    create_module(f, 
                                f"hedgehog/input{idx}_datamover_controller", 
                                "acadia_datamover_controller")
                    connect_bd_net(f, f"hedgehog/input{idx}_datamover_controller/clk", "hedgehog/clk_wiz/seq_clk")
                    connect_bd_intf_net(f, 
                                        f"hedgehog/sequencer_bus_decoder/input{idx}_datamover_controller", 
                                        f"hedgehog/input{idx}_datamover_controller/master_bus")
                    
                     # Create and connect the DataMovers itself
                    create_ip(f, name=f"hedgehog/input{idx}_datamover", vlnv="xilinx.com:ip:axi_datamover:5.1")
                    set_property(f, 
                                 name=f"hedgehog/input{idx}_datamover", 
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
 
                    set_property(f, name=f"hedgehog/input{idx}_datamover", properties=dm_config)                    
                
                    # Connect the AXI masters
                    destination = f"hedgehog/memory_smartconnect/S{memory_smartconnect_master:02d}_AXI"
                    memory_smartconnect_master += 1
                    memory_smartconnect_target_address_spaces.append(f"/hedgehog/input{idx}_datamover/Data_MM2S")
                        
                    connect_bd_intf_net(f, f"hedgehog/input{idx}_datamover/M_AXI_MM2S", destination)

                    # Connect clocks and resets for the command and status ports
                    # (for some reason the clock pins are different between s2mm and mm2s)
                    # These will both connect to the sequencer clock since the command and status ports
                    # are controlled by the bus through the DataMover controller
                    connect_bd_net(f, 
                                    f"hedgehog/input{idx}_datamover/m_axis_mm2s_cmdsts_aclk", 
                                    f"hedgehog/clk_wiz/seq_clk")
                    connect_bd_net(f, 
                                    f"hedgehog/input{idx}_datamover/m_axis_mm2s_cmdsts_aresetn",
                                    f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                    # Connect AXI Master clocks and resets
                    connect_bd_net(f, 
                                    f"hedgehog/input{idx}_datamover/m_axi_mm2s_aclk", 
                                    f"hedgehog/clk_wiz/{inp['AXI_clock']}")
                    connect_bd_net(f, 
                                    f"hedgehog/input{idx}_datamover/m_axi_mm2s_aresetn", 
                                    f"hedgehog/proc_sys_reset_{inp['AXI_clock']}/peripheral_aresetn")

                    # Connect command and status
                    connect_bd_intf_net(f, 
                                        f"hedgehog/input{idx}_datamover_controller/cmd", 
                                        f"hedgehog/input{idx}_datamover/S_AXIS_MM2S_CMD")
                    connect_bd_intf_net(f, 
                                        f"hedgehog/input{idx}_datamover_controller/sts", 
                                        f"hedgehog/input{idx}_datamover/M_AXIS_MM2S_STS")
                    
                    # Connect the error signal through a CDC
                    # TODO: this isn't always necessary
                    create_ip(f, name=f"hedgehog/xpm_cdc_input{idx}_datamover_mm2s_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                    set_property(f, name=f"hedgehog/xpm_cdc_input{idx}_datamover_mm2s_err", properties={"CDC_TYPE": "xpm_cdc_single"})
                    connect_bd_net(f, f"hedgehog/xpm_cdc_input{idx}_datamover_mm2s_err/src_clk", f"hedgehog/clk_wiz/{inp['AXI_clock']}")
                    connect_bd_net(f, f"hedgehog/xpm_cdc_input{idx}_datamover_mm2s_err/src_in", f"hedgehog/input{idx}_datamover/mm2s_err")
                    connect_bd_net(f, f"hedgehog/xpm_cdc_input{idx}_datamover_mm2s_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")
                    connect_bd_net(f, f"hedgehog/xpm_cdc_input{idx}_datamover_mm2s_err/dest_out", f"hedgehog/input{idx}_datamover_controller/err")
                    
                    # Connect the datamover to the switch through a FIFO
                    create_ip(f, f"hedgehog/input{idx}_datamover_fifo", "xilinx.com:ip:axis_data_fifo:2.0")
                    set_property(f, 
                                 f"hedgehog/input{idx}_datamover_fifo",
                                 properties={"IS_ACLK_ASYNC": 1, 
                                             "FIFO_DEPTH": inp["FIFO_depth"]})
                    
                    # Connect clocks and resets for the FIFO
                    connect_bd_net(f, 
                                   f"hedgehog/input{idx}_datamover_fifo/s_axis_aclk", 
                                   f"hedgehog/clk_wiz/{inp['AXI_clock']}")
                    connect_bd_net(f, 
                                f"hedgehog/input{idx}_datamover_fifo/s_axis_aresetn",
                                f"hedgehog/proc_sys_reset_{inp['AXI_clock']}/peripheral_aresetn")
                    connect_bd_net(f, 
                                   f"hedgehog/input{idx}_datamover_fifo/m_axis_aclk", 
                                   f"hedgehog/clk_wiz/{self.config['stream_processing_path']['clock']}")
                    
                    
                    # Connect the DataMover to the FIFO
                    connect_bd_intf_net(f, 
                                        f"hedgehog/input{idx}_datamover/M_AXIS_MM2S", 
                                        f"hedgehog/input{idx}_datamover_fifo/s_axis")
                    
                    # Connect the FIFO output to the switch
                    connect_bd_intf_net(f, 
                                        f"hedgehog/input{idx}_datamover_fifo/m_axis", 
                                        f"hedgehog/stream_processing_input_switch/S{idx:02d}_AXIS")
                    
                else:
                    raise ValueError(f"Unrecognized input kind {inp['kind']}")
                    
                    
            # ------------------- CMACC Kernel Memory (if any) -------------------- #
            if self._num_cmaccs > 0:
                # Create the memory controller
                create_module(f, f"hedgehog/cmacc_kernel_memory", f"cmacc_kernel_axi_memory")
                connect_bd_intf_net(f, f"hedgehog/cmacc_kernel_memory/s_axi", f"hedgehog/memory_smartconnect/M{memory_smartconnect_slave:02d}_AXI")
                memory_smartconnect_slave += 1
                connect_bd_net(f, f"hedgehog/cmacc_kernel_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/cmacc_kernel_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
                    
            # ------------------- Stream Processing Modules -------------------- #
            cmacc_kernel_memory_controller_element = 0
            for idx_module,module in enumerate(self.config["stream_processing_path"]["modules"]):
                # All of the modules will need a datamover
                create_ip(f, name=f"hedgehog/module{idx_module}_datamover", vlnv="xilinx.com:ip:axi_datamover:5.1")
                set_property(f, name=f"hedgehog/module{idx_module}_datamover", 
                                    properties="CONFIG.c_m_axi_s2mm_data_width.VALUE_SRC USER CONFIG.c_s_axis_s2mm_tdata_width.VALUE_SRC USER")
                
                # Connect clocks and resets for the command and status ports
                # (for some reason the clock pins are different between s2mm and mm2s)
                # These will both connect to the sequencer clock since the command and status ports
                # are controlled by the bus through the DataMover controller
                connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_datamover/m_axis_s2mm_cmdsts_awclk", 
                                f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_datamover/m_axis_s2mm_cmdsts_aresetn",
                                f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect AXI Master clocks and resets
                connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_datamover/m_axi_s2mm_aclk", 
                                f"hedgehog/clk_wiz/{module['AXI_clock']}")
                connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_datamover/m_axi_s2mm_aresetn", 
                                f"hedgehog/proc_sys_reset_{module['AXI_clock']}/peripheral_aresetn")

                connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_datamover/m_axi_mm2s_aclk", 
                                f"hedgehog/clk_wiz/{module['AXI_clock']}")
                connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_datamover/m_axi_mm2s_aresetn", 
                                f"hedgehog/proc_sys_reset_{module['AXI_clock']}/peripheral_aresetn")

                # Create a controller
                create_module(f, 
                                f"hedgehog/module{idx_module}_s2mm_datamover_controller", 
                                "acadia_datamover_controller")
                connect_bd_net(f, f"hedgehog/module{idx_module}_s2mm_datamover_controller/clk", "hedgehog/clk_wiz/seq_clk")
                connect_bd_intf_net(f, 
                                    f"hedgehog/module{idx_module}_s2mm_datamover_controller/master_bus",
                                    f"hedgehog/sequencer_bus_decoder/module{idx_module}_s2mm_datamover_controller")

                # Connect command and status
                connect_bd_intf_net(f, 
                                    f"hedgehog/module{idx_module}_s2mm_datamover_controller/cmd", 
                                    f"hedgehog/module{idx_module}_datamover/S_AXIS_S2MM_CMD")
                connect_bd_intf_net(f, 
                                    f"hedgehog/module{idx_module}_s2mm_datamover_controller/sts", 
                                    f"hedgehog/module{idx_module}_datamover/M_AXIS_S2MM_STS")
                
                # Connect the error signal through a CDC
                create_ip(f, name=f"hedgehog/xpm_cdc_module{idx_module}_datamover_s2mm_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                set_property(f, name=f"hedgehog/xpm_cdc_module{idx_module}_datamover_s2mm_err", properties={"CDC_TYPE": "xpm_cdc_single"})
                connect_bd_net(f, f"hedgehog/xpm_cdc_module{idx_module}_datamover_s2mm_err/src_clk", f"hedgehog/clk_wiz/{module['AXI_clock']}")
                connect_bd_net(f, f"hedgehog/xpm_cdc_module{idx_module}_datamover_s2mm_err/src_in", f"hedgehog/module{idx_module}_datamover/s2mm_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_module{idx_module}_datamover_s2mm_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/xpm_cdc_module{idx_module}_datamover_s2mm_err/dest_out", f"hedgehog/module{idx_module}_s2mm_datamover_controller/err")

                if module["kind"] == "memory":
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
                    set_property(f, name=f"hedgehog/module{idx_module}_datamover", properties=datamover_properties)

                    # Connect the output AXI master
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_datamover/M_AXI_S2MM", 
                                        f"hedgehog/memory_smartconnect/S{memory_smartconnect_master:02d}_AXI")
                    memory_smartconnect_master += 1
                    memory_smartconnect_target_address_spaces.append(f"/hedgehog/module{idx_module}_datamover/Data_S2MM")
                    
                    # Create a buffer FIFO
                    create_module(f, f"hedgehog/module{idx_module}_s2mm_datamover_fifo", "acadia_backpressure_fifo_bd")
                    set_property(f, 
                                 f"hedgehog/module{idx_module}_s2mm_datamover_fifo",
                                 properties={"WORD_WIDTH": self.config["stream_processing_path"]["width"], 
                                             "INPUT_WORDS": 1,
                                             "OUTPUT_WORDS": 1,
                                             "INPUT_DEPTH": module["FIFO_depth"]})
                    
                    # Connect clocks and resets for the FIFO
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_s2mm_datamover_fifo/signal_in_clk", 
                                   f"hedgehog/clk_wiz/{self.config['stream_processing_path']['clock']}")
                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_s2mm_datamover_fifo/signal_in_rst",
                                f"hedgehog/module{idx_module}_s2mm_datamover_controller/fifo_rst")
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_s2mm_datamover_fifo/monitor_clk", 
                                   f"hedgehog/clk_wiz/{self.config['stream_processing_path']['clock']}")
                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_s2mm_datamover_fifo/monitor_rst",
                                f"hedgehog/module{idx_module}_s2mm_datamover_controller/fifo_rst")
                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_s2mm_datamover_fifo/monitor_overflow",
                                f"hedgehog/module{idx_module}_s2mm_datamover_controller/fifo_overflow")
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_s2mm_datamover_fifo/m_axis_aclk", 
                                   f"hedgehog/clk_wiz/{module['AXI_clock']}")
                    
                    # Connect the FIFO interfaces
                    connect_bd_intf_net(f, 
                                        f"hedgehog/stream_processing_input_switch/M{idx_module:02d}_AXIS", 
                                        f"hedgehog/module{idx_module}_s2mm_datamover_fifo/signal_in")
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_s2mm_datamover_fifo/m_axis",
                                        f"hedgehog/module{idx_module}_datamover/S_AXIS_S2MM")
                    
                elif module["kind"] == "adder":
                    words = self.config["stream_processing_path"]["width"] // 16
                    
                    # Add a MM2S port and create a single AXI interface
                    # TODO: For some reason, getting the single AXI interface to work only seems to
                    # be possible by going into the GUI, disabling the MM2S and S2MM (or setting them both to Basic),
                    # and setting all the settings to match manually. For now we'll just use the two individual interfaces
                    # but it would be nice to figure this out
                    datamover_properties = {
                        "c_enable_cache_user": "true",
                        "c_enable_s2mm_adv_sig": 0,
                        "c_addr_width": 40,
                        "c_single_interface": 0,
                        
                        "c_enable_s2mm": 1,
                        "c_include_s2mm": "Full",
                        "c_m_axi_s2mm_data_width": module['output_word_width']*words,
                        "c_s_axis_s2mm_tdata_width": module['output_word_width']*words,
                        "c_s2mm_btt_used": 23,
                        "c_s2mm_burst_size": module['datamover_burst_size'],
                        "c_s2mm_support_indet_btt": "true",
                        "c_s2mm_include_sf": "false",
                        
                        "c_enable_mm2s": 1,
                        "c_include_mm2s": "Full",
                        "c_m_axi_mm2s_data_width": module['output_word_width']*words,
                        "c_m_axis_mm2s_tdata_width": module['output_word_width']*words,
                        "c_mm2s_btt_used": 23,
                        "c_mm2s_burst_size": module['datamover_burst_size'],
                        "c_mm2s_include_sf": "false",
                        
                    }

                    set_property(f, name=f"hedgehog/module{idx_module}_datamover", properties=datamover_properties)

                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_datamover/m_axis_mm2s_cmdsts_aclk", 
                                f"hedgehog/clk_wiz/seq_clk")
                    connect_bd_net(f, 
                                    f"hedgehog/module{idx_module}_datamover/m_axis_mm2s_cmdsts_aresetn",
                                    f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                    
                    # Connect the output AXI masters
                    for direction in ["MM2S", "S2MM"]:
                        connect_bd_intf_net(f, f"hedgehog/module{idx_module}_datamover/M_AXI_{direction}", f"hedgehog/memory_smartconnect/S{memory_smartconnect_master:02d}_AXI")
                        memory_smartconnect_master += 1
                        memory_smartconnect_target_address_spaces.append(f"/hedgehog/module{idx_module}_datamover/Data_{direction}")
                        
                    # Create a controller
                    create_module(f, 
                                    f"hedgehog/module{idx_module}_mm2s_datamover_controller", 
                                    "acadia_datamover_controller")
                    connect_bd_net(f, f"hedgehog/module{idx_module}_mm2s_datamover_controller/clk", "hedgehog/clk_wiz/seq_clk")
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_mm2s_datamover_controller/master_bus",
                                        f"hedgehog/sequencer_bus_decoder/module{idx_module}_mm2s_datamover_controller")

                    # Connect command and status
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_mm2s_datamover_controller/cmd", 
                                        f"hedgehog/module{idx_module}_datamover/S_AXIS_MM2S_CMD")
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_mm2s_datamover_controller/sts", 
                                        f"hedgehog/module{idx_module}_datamover/M_AXIS_MM2S_STS")
                    
                    # Connect the error signal through a CDC
                    create_ip(f, name=f"hedgehog/xpm_cdc_module{idx_module}_datamover_mm2s_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                    set_property(f, name=f"hedgehog/xpm_cdc_module{idx_module}_datamover_mm2s_err", properties={"CDC_TYPE": "xpm_cdc_single"})
                    connect_bd_net(f, f"hedgehog/xpm_cdc_module{idx_module}_datamover_mm2s_err/src_clk", f"hedgehog/clk_wiz/{module['AXI_clock']}")
                    connect_bd_net(f, f"hedgehog/xpm_cdc_module{idx_module}_datamover_mm2s_err/src_in", f"hedgehog/module{idx_module}_datamover/mm2s_err")
                    connect_bd_net(f, f"hedgehog/xpm_cdc_module{idx_module}_datamover_mm2s_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")
                    connect_bd_net(f, f"hedgehog/xpm_cdc_module{idx_module}_datamover_mm2s_err/dest_out", f"hedgehog/module{idx_module}_mm2s_datamover_controller/err")
                    
                    # Add FIFOs for the inputs
                    
                    # Create FIFO A (connected to the input path)
                    create_module(f, f"hedgehog/module{idx_module}_inputA_fifo", "acadia_backpressure_fifo_bd")
                    set_property(f, 
                                 f"hedgehog/module{idx_module}_inputA_fifo",
                                 properties={"WORD_WIDTH": self.config["stream_processing_path"]["width"], 
                                             "INPUT_WORDS": 1,
                                             "OUTPUT_WORDS": 1,
                                             "INPUT_DEPTH": module["FIFO_depth"]})     
                                    
                    # Connect clocks and resets for the FIFO
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_inputA_fifo/signal_in_clk", 
                                   f"hedgehog/clk_wiz/{self.config['stream_processing_path']['clock']}")
                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_inputA_fifo/signal_in_rst",
                                f"hedgehog/module{idx_module}_s2mm_datamover_controller/fifo_rst")
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_inputA_fifo/monitor_clk", 
                                   f"hedgehog/clk_wiz/{self.config['stream_processing_path']['clock']}")
                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_inputA_fifo/monitor_rst",
                                f"hedgehog/module{idx_module}_s2mm_datamover_controller/fifo_rst")
                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_inputA_fifo/monitor_overflow",
                                f"hedgehog/module{idx_module}_s2mm_datamover_controller/fifo_overflow")
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_inputA_fifo/m_axis_aclk", 
                                   f"hedgehog/clk_wiz/{module['AXI_clock']}")
                    
                    # Create FIFO B (connected to the datamover)
                    create_ip(f, f"hedgehog/module{idx_module}_inputB_fifo", "xilinx.com:ip:axis_data_fifo:2.0")
                    set_property(f, 
                                f"hedgehog/module{idx_module}_inputB_fifo",
                                properties={"IS_ACLK_ASYNC": 0, 
                                            "FIFO_DEPTH": module["FIFO_depth"]})                        
                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_inputB_fifo/s_axis_aclk", 
                                f"hedgehog/clk_wiz/{module['AXI_clock']}")
                    connect_bd_net(f, 
                                f"hedgehog/module{idx_module}_inputB_fifo/s_axis_aresetn",
                                f"hedgehog/module{idx_module}_s2mm_datamover_controller/fifo_nrst")

                    # Create the adder
                    create_module(f, f"hedgehog/module{idx_module}_adder", "acadia_stream_adder")
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_adder/clk", 
                                   f"hedgehog/clk_wiz/{module['AXI_clock']}")
                    set_property(f, 
                                 f"hedgehog/module{idx_module}_adder",
                                 properties={"WORDS": words})
                    
                    # Connect the adder registers
                    connect_bd_intf_net(f, 
                                        f"hedgehog/sequencer_bus_decoder/module{idx_module}_registers",
                                        f"hedgehog/module{idx_module}_adder/registers")
                    
                    # Connect the interfaces for the first FIFO
                    connect_bd_intf_net(f, 
                                        f"hedgehog/stream_processing_input_switch/M{idx_module:02d}_AXIS", 
                                        f"hedgehog/module{idx_module}_inputA_fifo/signal_in")
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_inputA_fifo/m_axis",
                                        f"hedgehog/module{idx_module}_adder/a")
                    
                    # Connect the interfaces for the second FIFO
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_datamover/M_AXIS_MM2S", 
                                        f"hedgehog/module{idx_module}_inputB_fifo/s_axis")
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_inputB_fifo/m_axis",
                                        f"hedgehog/module{idx_module}_adder/b")
                                        
                    # Connect the output to the DataMover
                    connect_bd_intf_net(f,
                                        f"hedgehog/module{idx_module}_adder/sum",
                                        f"hedgehog/module{idx_module}_datamover/S_AXIS_S2MM")
                    
                elif module["kind"] == "cmacc":
                    # No MM2S needed, just connect to the datamover
                    datamover_properties = {
                        "c_enable_cache_user": "true",
                        "c_enable_s2mm_adv_sig": 0,
                        "c_addr_width": 40,
                        
                        "c_enable_s2mm": 1,
                        "c_include_s2mm": "Full",
                        "c_m_axi_s2mm_data_width": module['AXI_width'],
                        "c_s_axis_s2mm_tdata_width": 32,
                        "c_s2mm_btt_used": 23,
                        "c_s2mm_burst_size": module['datamover_burst_size'],
                        "c_s2mm_support_indet_btt": "true",
                        "c_s2mm_include_sf": "false",
                        
                        "c_enable_mm2s": 0,
                        "c_include_mm2s": "Omit",
                        "c_include_mm2s_stsfifo": "false",
                        "c_mm2s_include_sf": "false",
                    }
                    set_property(f, name=f"hedgehog/module{idx_module}_datamover", properties=datamover_properties)
                
                    # Connect the output AXI master
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_datamover/M_AXI_S2MM", 
                                        f"hedgehog/memory_smartconnect/S{memory_smartconnect_master:02d}_AXI")
                    memory_smartconnect_master += 1
                    memory_smartconnect_target_address_spaces.append(f"/hedgehog/module{idx_module}_datamover/Data_S2MM")
                    
                    # Create the module
                    create_module(f, f"hedgehog/module{idx_module}_cmacc", "acadia_stream_complex32_macc")
                    external_depth = 32 * module["kernel_memory_depth"] / self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_width"]
                    set_property(f, 
                                 f"hedgehog/module{idx_module}_cmacc", 
                                 properties={"INPUT_WORDS": self.config["stream_processing_path"]["width"] // 32,
                                            "KERNEL_MEMORY_DEPTH": module["kernel_memory_depth"],
                                            "LOG2_KERNEL_MEMORY_DEPTH": next_highest_power_of_2(module["kernel_memory_depth"], log=True),
                                            "KERNEL_MEMORY_EXTERNAL_PORT_LATENCY": self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_port_output_pipeline"],
                                            "KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH": self.config["stream_processing_path"]["cmacc_kernel_memory_controller"]["controller_width"],
                                            "KERNEL_MEMORY_EXTERNAL_PORT_ADDRESS_WIDTH": next_highest_power_of_2(external_depth, log=True),
                                            "DATA_OUTPUT_FIFO_DEPTH": module["FIFO_depth"],
                                            "DATA_OUTPUT_FIFO_PRIMITIVE": module["FIFO_primitive"],
                                            "DATA_OUTPUT_FIFO_ASYNCHRONOUS": "false" if module["AXI_clock"] == "seq_clk" else "true"})
                    
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_cmacc/clk", 
                                   f"hedgehog/clk_wiz/{self.config['stream_processing_path']['clock']}")
                    
                    # Connect the register interface
                    connect_bd_intf_net(f, 
                                        f"hedgehog/sequencer_bus_decoder/module{idx_module}_registers",
                                        f"hedgehog/module{idx_module}_cmacc/registers")
                    
                    # Connect the input (unbuffered)
                    connect_bd_intf_net(f, 
                                        f"hedgehog/stream_processing_input_switch/M{idx_module:02d}_AXIS", 
                                        f"hedgehog/module{idx_module}_cmacc/data_in")
                    
                    # Connect the output interface and clock directly to the datamover 
                    # (the output is buffered with a FIFO internally)
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_cmacc/data_out_aclk", 
                                   f"hedgehog/clk_wiz/{module['AXI_clock']}")                    
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_cmacc/data_out", 
                                        f"hedgehog/module{idx_module}_datamover/S_AXIS_S2MM")
            
                    # Connect the kernel memory controller
                    connect_bd_intf_net(f,
                                        f"hedgehog/module{idx_module}_cmacc/kernel_memory",
                                        f"hedgehog/cmacc_kernel_memory/mem{cmacc_kernel_memory_controller_element}")
                    cmacc_kernel_memory_controller_element += 1
                    
                elif module["kind"] == "dsp":
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
                    set_property(f, name=f"hedgehog/module{idx_module}_datamover", properties=datamover_properties)

                    # Connect the output AXI master
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_datamover/M_AXI_S2MM", 
                                        f"hedgehog/memory_smartconnect/S{memory_smartconnect_master:02d}_AXI")
                    memory_smartconnect_master += 1
                    memory_smartconnect_target_address_spaces.append(f"/hedgehog/module{idx_module}_datamover/Data_S2MM")
                    
                    # Create the module
                    create_module(f, f"hedgehog/module{idx_module}_dsp", "acadia_stream_complex32_dsp")
                    set_property(f,
                                 f"hedgehog/module{idx_module}_dsp", 
                                 properties={"INPUT_WORDS": self.config["stream_processing_path"]["width"] // 32,
                                            "DATA_OUTPUT_FIFO_DEPTH": module["FIFO_depth"],
                                            "DATA_OUTPUT_FIFO_PRIMITIVE": module["FIFO_primitive"],
                                            "DATA_OUTPUT_FIFO_ASYNCHRONOUS": "false" if module["AXI_clock"] == "seq_clk" else "true"})
                    
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_dsp/clk", 
                                   f"hedgehog/clk_wiz/{self.config['stream_processing_path']['clock']}")
                    
                    # Connect the register interface
                    connect_bd_intf_net(f, 
                                        f"hedgehog/sequencer_bus_decoder/module{idx_module}_registers",
                                        f"hedgehog/module{idx_module}_dsp/registers")
                    
                    # Connect the input
                    connect_bd_intf_net(f, 
                                        f"hedgehog/stream_processing_input_switch/M{idx_module:02d}_AXIS", 
                                        f"hedgehog/module{idx_module}_dsp/data_in")
                    
                    # Connect the output interface and clock directly to the datamover 
                    # (the output is buffered with a FIFO internally)
                    connect_bd_net(f, 
                                   f"hedgehog/module{idx_module}_dsp/data_out_aclk", 
                                   f"hedgehog/clk_wiz/{module['AXI_clock']}")                    
                    connect_bd_intf_net(f, 
                                        f"hedgehog/module{idx_module}_dsp/data_out", 
                                        f"hedgehog/module{idx_module}_datamover/S_AXIS_S2MM")  
                                        
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
                
            # ------------------- PS GPIO and Interrupt Connections -------------------- #
            # Create a concatenator for the PS inputs
            create_concatenator(f, "hedgehog/xlconcat_ps_gpio_in", 
                                [32, 32, self.config["sequencer_bus"]["ps_gpio5"]["width"]])
            connect_bd_net(f, "hedgehog/xlconcat_ps_gpio_in/dout", "hedgehog/PS_GPIO_IN")
            
            for idx, gpio_port in enumerate([3,4,5]):
                connect_bd_net(f, f"hedgehog/xlconcat_ps_gpio_in/In{idx}", f"hedgehog/ps_gpio{gpio_port}_dataport/gpio_in")
                
                # Slice the PS outputs
                create_slice(f, name=f"hedgehog/xlslice_ps_gpio{gpio_port}_out", 
                                 input_width=64 + self.config["sequencer_bus"]["ps_gpio5"]["width"], 
                                 input_from=(64 + self.config["sequencer_bus"]["ps_gpio5"]["width"] - 1 if gpio_port == 5 else (idx+1)*32-1),
                                 input_to=idx*32)
                connect_bd_net(f, f"hedgehog/xlslice_ps_gpio{gpio_port}_out/Din", f"hedgehog/PS_GPIO_OUT")
                connect_bd_net(f, f"hedgehog/xlslice_ps_gpio{gpio_port}_out/Dout", f"hedgehog/ps_gpio{gpio_port}_dataport/gpio_out")
                
            # IRQ signals
            for i in range(2):
                connect_bd_net(f, f"hedgehog/ps_irq_dataport/irq{i}", f"hedgehog/PS_IRQ{i}")
                
            # ------------------- PS GDMA Connections -------------------- #
            connect_bd_net(f, f"hedgehog/zdma_controller/cack", f"hedgehog/ps_gdma_cack")
            connect_bd_net(f, f"hedgehog/zdma_controller/tvld", f"hedgehog/ps_gdma_tvld")
            connect_bd_net(f, f"hedgehog/zdma_controller/tack", f"hedgehog/ps_gdma_tack")
            connect_bd_net(f, f"hedgehog/zdma_controller/cvld", f"hedgehog/ps_gdma_cvld")
            connect_bd_net(f, f"hedgehog/ps_irq_dataport/gdma_irq", f"hedgehog/ps_gdma_irq")
            
            # Create a concatenator for the clock signals
            create_concatenator(f, "hedgehog/xlconcat_ps_gdma_clk", [1]*8)
            connect_bd_net(f, f"hedgehog/xlconcat_ps_gdma_clk/dout", f"hedgehog/ps_gdma_clk")
            for i in range(8):
                connect_bd_net(f, f"hedgehog/xlconcat_ps_gdma_clk/In{i}", f"hedgehog/clk_wiz/seq_clk")
                
            # ------------------- ADCIO and DACIO -------------------- #
            connect_bd_net(f, "hedgehog/io_dataport/ADCIO", "hedgehog/ADCIO")
            connect_bd_net(f, "hedgehog/io_dataport/DACIO", "hedgehog/DACIO")
                
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
                        addr_seg=f"hedgehog/dac_tile{i}_memory/" + self.config[f"dac_tile{i}_sample_memory"]["segment"])

                if self._num_cmaccs > 0:
                    assign_bd_address(f, 
                        target_address_space=target_address_space, 
                        offset=self.config["stream_processing_path"][f"cmacc_kernel_memory_controller"]["base_address"], 
                        range=self._num_cmaccs*self._max_cmacc_memory*4, 
                        addr_seg=f"hedgehog/cmacc_kernel_memory/" + self.config["stream_processing_path"][f"cmacc_kernel_memory_controller"]["segment"])
                
                for t,count in [("dac", self.NUM_DACS), 
                                ("adc", self.NUM_ADCS)]:
                    assign_bd_address(f, 
                        target_address_space=target_address_space, 
                        offset=self.config[f"{t}_dma_descriptor_memory"]["address"], 
                        range=count*self.config[f"{t}_dma_descriptor_memory"]["size_bits"] // 8, 
                        addr_seg=f"hedgehog/{t}_dma_descriptor_memory/" + self.config[f"{t}_dma_descriptor_memory"]["segment"])
                
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    addr_seg=f"hedgehog/stream_processing_input_switch/" + self.config["stream_processing_path"][f"input_switch"]["axi_segment"], 
                    offset=self.config["stream_processing_path"][f"input_switch"]["axi_address"], 
                    range=self.config["stream_processing_path"][f"input_switch"]["axi_size_bits"] // 8)
                
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    addr_seg=f"hedgehog/adc_input_switch/" + self.config["stream_processing_path"][f"adc_input_switch"]["axi_segment"], 
                    offset=self.config["stream_processing_path"][f"adc_input_switch"]["axi_address"], 
                    range=self.config["stream_processing_path"][f"adc_input_switch"]["axi_size_bits"] // 8)
                    
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    addr_seg="hedgehog/rfdc/" + self.config["rfdc"]["axi_segment"], 
                    offset=self.config["rfdc"]["axi_address"], 
                    range=self.config["rfdc"]["axi_size_bits"] // 8)
                
                # Exclude the QSPI
                for gp in range(4):
                    exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HPC0_QSPI")
                    exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HPC1_QSPI")
                    exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HP0_QSPI")
                    exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HP1_QSPI")            
                    
            for target_address_space in sequencer_memory_crossbar_target_address_spaces:
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    offset=self.config["sequencer_cache_memory"]["address"], 
                    range=self.config["sequencer_cache_memory"]["size_bits"] // 8, 
                    addr_seg=f"hedgehog/cache_memory/" + self.config["sequencer_cache_memory"]["segment"])
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    offset=self.config["sequencer_instruction_memory"]["address"], 
                    range=self.config["sequencer_instruction_memory"]["size_bits"] // 8, 
                    addr_seg=f"hedgehog/instruction_memory/" + self.config["sequencer_instruction_memory"]["segment"])
                
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
        
        modules = {"memory": [], "dsp": [], "adder": [], "cmacc": []}
        for idx,module in enumerate(self.config["stream_processing_path"]['modules']):
            modules[module["kind"]].append(idx)
                
        return modules