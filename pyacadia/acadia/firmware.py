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

    def __init__(self, config=None):
        """
        :param config: Dictionary containing firmware constants
        :type config: dict
        :param directory: Directory in which the project should be created
        :type directory: str
        """
        self.config = config if config is not None else DEFAULT_CONFIG
        
        # Set some constants that are determined by the settings in the config
        self._num_dacs = 16 # TODO: is there a situation in which this would ever not be 16?
        self._num_adcs = len(self.config["ADC_CAPTURE_PATH"]["FIFO_DEPTH"])
        self._num_cmaccs = len(self.config["CMACC_CAPTURE_PATH"]["FIFO_DEPTH"])

        self._config_smartconnect_extra_datamovers = 0
        self._bulk_memory_smartconnect_extra_datamovers = 0
        self._sequencer_memory_crossbar_extra_datamovers = 0
        self._datamover_controller_extra_ports = []
        for dm,properties in self.config["DATAMOVERS"].items():
            for direction in ["MM2S", "S2MM"]:
                if properties[f"ENABLE_{direction}"]:
                    self._datamover_controller_extra_ports.append(f"{dm}_{direction.lower()}")
                    if properties[f"{direction}_AXI"] == "config_smartconnect":
                        self._config_smartconnect_extra_datamovers += 1
                    elif properties[f"{direction}_AXI"] == "bulk_memory_smartconnect":
                        self._bulk_memory_smartconnect_extra_datamovers += 1
                    elif properties[f"{direction}_AXI"] == "sequencer_memory_crossbar":
                        self._sequencer_memory_crossbar_extra_datamovers += 1
                    else:
                        raise ValueError(f"Unrecognized interconnect"
                                         f" {properties[f'{direction}_M_AXI']}")

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
                                           pipeline_miso=self.config["SEQUENCER_BUS"]["DECODER_PIPELINE_MISO"])
        self._hdl_modules.append(self.sequencer_bus_decoder)

        # Create split dataport for triggering and monitoring the DMA and for setting continue signals
        _bit = 0
        _dma_trigger_ports = []
        _dma_fifo_empty_ports = []
        _dma_fifo_almost_empty_ports = []
        _dma_running_ports = []
        _adc_fifo_control_ports = []

        for label,count in [("dac", self._num_dacs), 
                            ("adc", self._num_adcs), 
                            ("cmacc", self._num_cmaccs)]:
            for idx in range(count):
                _dma_trigger_ports += [
                    {"name": f"{label}_dma{idx}", 
                    "direction": BusDataport.OUTPUT, 
                    "offset": _bit,
                    "width": 1,
                    "gate": BusDataport.GATE_RESET,
                    "pipeline": self.config["SEQUENCER_BUS"]["DMA_TRIGGER_DATAPORT"]["PIPELINE"][_bit]}]

                _dma_fifo_empty_ports += [
                    {"name": f"{label}_dma{idx}", 
                    "direction": BusDataport.INPUT, 
                    "offset": _bit,
                    "width": 1,
                    "pipeline": self.config["SEQUENCER_BUS"]["DMA_FIFO_EMPTY_DATAPORT"]["PIPELINE"][_bit]}]

                _dma_fifo_almost_empty_ports += [
                    {"name": f"{label}_dma{idx}", 
                    "direction": BusDataport.INPUT, 
                    "offset": _bit,
                    "width": 1,
                    "pipeline": self.config["SEQUENCER_BUS"]["DMA_FIFO_ALMOST_EMPTY_DATAPORT"]["PIPELINE"][_bit]}]

                _dma_running_ports += [
                    {"name": f"{label}_dma{idx}", 
                    "direction": BusDataport.INPUT, 
                    "offset": _bit,
                    "width": 1,
                    "pipeline": self.config["SEQUENCER_BUS"]["DMA_RUNNING_DATAPORT"]["PIPELINE"][_bit]}]

                if label == "adc":
                    _adc_fifo_control_ports += [
                        {"name": f"{label}_dm{idx}_overflow", 
                        "direction": BusDataport.INPUT, 
                        "offset": idx,
                        "width": 1,
                        "pipeline": self.config["SEQUENCER_BUS"]["ADC_FIFO_DATAPORT"]["ADC_OVERFLOW_PIPELINE"][idx]}]
                    
                    _adc_fifo_control_ports += [
                        {"name": f"{label}_dm{idx}_misalignment", 
                        "direction": BusDataport.INPUT, 
                        "offset": idx + self._num_adcs + self._num_cmaccs,
                        "width": 1,
                        "pipeline": self.config["SEQUENCER_BUS"]["ADC_FIFO_DATAPORT"]["ADC_MISALIGNMENT_PIPELINE"][idx]}]
                    
                    _adc_fifo_control_ports += [
                        {"name": f"{label}_dm{idx}_rst", 
                        "direction": BusDataport.OUTPUT, 
                        "offset": idx,
                        "gate": BusDataport.GATE_RESET,
                        "width": 1,
                        "pipeline": self.config["SEQUENCER_BUS"]["ADC_FIFO_DATAPORT"]["ADC_RESET_PIPELINE"][idx]}]
                elif label == "cmacc":
                    _adc_fifo_control_ports += [
                        {"name": f"{label}_dm{idx}_overflow", 
                        "direction": BusDataport.INPUT, 
                        "offset": idx + self._num_adcs,
                        "width": 1,
                        "pipeline": self.config["SEQUENCER_BUS"]["ADC_FIFO_DATAPORT"]["CMACC_OVERFLOW_PIPELINE"][idx]}]
                    
                    _adc_fifo_control_ports += [
                        {"name": f"{label}_dm{idx}_misalignment", 
                        "direction": BusDataport.INPUT, 
                        "offset": idx + self._num_adcs + self._num_cmaccs + self._num_adcs,
                        "width": 1,
                        "pipeline": self.config["SEQUENCER_BUS"]["ADC_FIFO_DATAPORT"]["CMACC_MISALIGNMENT_PIPELINE"][idx]}]
                    
                    _adc_fifo_control_ports += [
                        {"name": f"{label}_dm{idx}_rst", 
                        "direction": BusDataport.OUTPUT, 
                        "offset": idx + self._num_adcs,
                        "gate": BusDataport.GATE_RESET,
                        "width": 1,
                        "pipeline": self.config["SEQUENCER_BUS"]["ADC_FIFO_DATAPORT"]["CMACC_RESET_PIPELINE"][idx]}]

                fifo_port = BusDevice(name=f"{label}_dma{idx}_fifo", 
                                      size=1, 
                                      bus_data_bits=next_highest_power_of_2(self.config[f"{label.upper()}_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 64, log=True))
                self.sequencer_bus_decoder.add(fifo_port, pipeline=self.config["SEQUENCER_BUS"]["DMA_FIFO_DATAPORT_PIPELINE"][_bit])

                _bit += 1

        self.dma_trigger = BusDataport(name="dma_trigger", ports=_dma_trigger_ports)
        self.sequencer_bus_decoder.add(self.dma_trigger, pipeline=self.config["SEQUENCER_BUS"]["DMA_TRIGGER_DATAPORT"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.dma_trigger)
        
        self.dma_fifo_empty = BusDataport(name="dma_fifo_empty", ports=_dma_fifo_empty_ports)
        self.sequencer_bus_decoder.add(self.dma_fifo_empty, pipeline=self.config["SEQUENCER_BUS"]["DMA_FIFO_EMPTY_DATAPORT"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.dma_fifo_empty)

        self.dma_fifo_almost_empty = BusDataport(name="dma_fifo_almost_empty", ports=_dma_fifo_almost_empty_ports)
        self.sequencer_bus_decoder.add(self.dma_fifo_almost_empty, pipeline=self.config["SEQUENCER_BUS"]["DMA_FIFO_ALMOST_EMPTY_DATAPORT"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.dma_fifo_almost_empty) 

        self.dma_running = BusDataport(name="dma_running", ports=_dma_running_ports)
        self.sequencer_bus_decoder.add(self.dma_running, pipeline=self.config["SEQUENCER_BUS"]["DMA_RUNNING_DATAPORT"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.dma_running)
        
        self.adc_fifo_control = BusDataport(name="adc_fifo_control", ports=_adc_fifo_control_ports)
        self.sequencer_bus_decoder.add(self.adc_fifo_control, pipeline=self.config["SEQUENCER_BUS"]["ADC_FIFO_DATAPORT"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.adc_fifo_control)

        # Create dataports for controlling accumulator offsets and output values
        for i in range(self._num_cmaccs):
            for quad in ["re", "im"]:
                _cmacc_dataports = []

                _cmacc_dataports += [
                    {"name": f"accumulator",
                    "direction": BusDataport.INPUT,
                    "offset": 0,
                    "width": 32,
                    "pipeline": self.config["SEQUENCER_BUS"]["CMACC_DATAPORTS"][f"ACCUMULATOR_{quad.upper()}_PIPELINE"][i]}]
                _cmacc_dataports += [
                    {"name": f"offset",
                    "direction": BusDataport.OUTPUT,
                    "offset": 0,
                    "width": 32,
                    "gate": BusDataport.GATE_REGCE,
                    "pipeline": self.config["SEQUENCER_BUS"]["CMACC_DATAPORTS"][f"OFFSET_{quad.upper()}_PIPELINE"][i]}]

                _cmacc_port = BusDataport(name=f"cmacc{i}_{quad}", 
                                          ports=_cmacc_dataports)
                self.sequencer_bus_decoder.add(_cmacc_port, 
                                          pipeline=self.config["SEQUENCER_BUS"]["CMACC_DATAPORTS"][f"DATAPORT_{quad.upper()}_BUS_PIPELINE"][i])
                self._hdl_modules.append(_cmacc_port)

        # Add a reset port
        _cmacc_reset_ports = []

        for i in range(self._num_cmaccs):
            _cmacc_reset_ports += [
                {"name": f"cmacc{i}", 
                "direction": BusDataport.OUTPUT, 
                "offset": i,
                "width": 1,
                "gate": BusDataport.GATE_RESET,
                "pipeline": self.config["SEQUENCER_BUS"]["CMACC_RESET_DATAPORT"]["PIPELINE"][i]}]

        self.cmacc_reset_port = BusDataport(name=f"cmacc_reset", 
                                       ports=_cmacc_reset_ports)
        self.sequencer_bus_decoder.add(self.cmacc_reset_port, 
                                  pipeline=self.config["SEQUENCER_BUS"]["CMACC_RESET_DATAPORT"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.cmacc_reset_port)

        # Create dataports for monitoring the CMACCs for completion
        _cmacc_status_dataports = []
        for i in range(self._num_cmaccs):
            _cmacc_status_dataports += [
                {"name": f"cmacc{i}_valid",
                "direction": BusDataport.INPUT,
                "offset": i,
                "width": 1,
                "pipeline": self.config["SEQUENCER_BUS"]["CMACC_STATUS_DATAPORT"]["VALID_PIPELINE"][i]}]
            _cmacc_status_dataports += [
                {"name": f"cmacc{i}_last",
                "direction": BusDataport.INPUT,
                "offset": self._num_cmaccs + i,
                "width": 1,
                "pipeline": self.config["SEQUENCER_BUS"]["CMACC_STATUS_DATAPORT"]["LAST_PIPELINE"][i]}]
            _cmacc_status_dataports += [
                {"name": f"cmacc{i}_re_msb",
                "direction": BusDataport.INPUT,
                "offset": 2*self._num_cmaccs + i,
                "width": 1,
                "pipeline": self.config["SEQUENCER_BUS"]["CMACC_STATUS_DATAPORT"]["RE_MSB_PIPELINE"][i]}]
            _cmacc_status_dataports += [
                {"name": f"cmacc{i}_im_msb",
                "direction": BusDataport.INPUT,
                "offset": 3*self._num_cmaccs + i,
                "width": 1,
                "pipeline": self.config["SEQUENCER_BUS"]["CMACC_STATUS_DATAPORT"]["IM_MSB_PIPELINE"][i]}]

        self.cmacc_status = BusDataport(name="cmacc_status", 
                                   ports=_cmacc_status_dataports)
        self.sequencer_bus_decoder.add(self.cmacc_status, 
                                  pipeline=self.config["SEQUENCER_BUS"]["CMACC_STATUS_DATAPORT"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.cmacc_status)

        # Create dataports for interacting with the PS GPIO
        for gpio_num in [3,4,5]:
            _ps_gpio_dataports = []

            _ps_gpio_dataports += [{"name": f"gpio_out",
                                    "direction": BusDataport.INPUT,
                                    "offset": 0,
                                    "width": self.config[f"PS_GPIO{gpio_num}"]["WIDTH"],
                                    "pipeline": self.config[f"PS_GPIO{gpio_num}"]["PIPELINE"]}]
            _ps_gpio_dataports += [{"name": f"gpio_in",
                                    "direction": BusDataport.OUTPUT,
                                    "offset": 0,
                                    "width": self.config[f"PS_GPIO{gpio_num}"]["WIDTH"],
                                    "gate": BusDataport.GATE_REGCE,
                                    "pipeline": self.config[f"PS_GPIO{gpio_num}"]["PIPELINE"]}]

            _ps_gpio = BusDataport(name=f"ps_gpio{gpio_num}", ports=_ps_gpio_dataports)
            self.sequencer_bus_decoder.add(_ps_gpio, pipeline=self.config[f"PS_GPIO{gpio_num}"]["BUS_PIPELINE"])
            self._hdl_modules.append(_ps_gpio)

        _ps_irq_dataports = []
        _ps_irq_dataports += [
            {"name": f"irq{i}",
            "direction": BusDataport.OUTPUT,
            "offset": i,
            "width": 1,
            "gate": BusDataport.GATE_REGCE,
            "pipeline": self.config["PS_IRQ"]["IRQ_PIPELINE"]} for i in range(2)]

        _ps_irq_dataports += [{
            "name": f"gdma_irq",
            "direction": BusDataport.INPUT,
            "offset": 2 + i,
            "width": 8,
            "pipeline": self.config["PS_IRQ"]["GDMA_PIPELINE"]}]

        self.ps_irq = BusDataport(name="ps_irq", ports=_ps_irq_dataports)
        self.sequencer_bus_decoder.add(self.ps_irq, pipeline=self.config["PS_IRQ"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.ps_irq)

        # Create a register file for RFDC real-time updates and connect it to the sequencer bus
        self.rfdc_rts_regs = BusDevice("rfdc_rts_regs", size=256)
        self.sequencer_bus_decoder.add(self.rfdc_rts_regs, pipeline=self.config["SEQUENCER_BUS"]["RFDC_RTS"]["BUS_PIPELINE"])

        # Create a register file for interacting with the PS GDMA
        self.zdma_controller = BusDevice("zdma_controller", size=64)
        self.sequencer_bus_decoder.add(self.zdma_controller, 
                                  pipeline=self.config["SEQUENCER_BUS"]["ZDMA_CONTROLLER"]["BUS_PIPELINE"])

        _clk104_sync_in_dataports = [
            {"name": f"sync",
            "direction": BusDataport.OUTPUT,
            "offset": 0,
            "width": 1,
            "gate": BusDataport.GATE_REGCE,
            "pipeline": self.config["SEQUENCER_BUS"]["CLK104_SYNC_DATAPORT"]["PIPELINE"]}]

        self.clk104_sync_in = BusDataport(name="clk104_sync_in", ports=_clk104_sync_in_dataports)
        self.sequencer_bus_decoder.add(self.clk104_sync_in, 
                                  pipeline=self.config["SEQUENCER_BUS"]["CLK104_SYNC_DATAPORT"]["BUS_PIPELINE"])
        self._hdl_modules.append(self.clk104_sync_in)

        # Create cache and connect it to the sequencer bus
        self.cache = BusDevice("cache", size=self.config["SEQUENCER_CACHE_MEMORY"]["SIZE_BITS"] // 32)
        self.sequencer_bus_decoder.add(self.cache, 
                                  pipeline=self.config["SEQUENCER_CACHE_MEMORY"]["BUS_PIPELINE"])

        datamover_controller = BusDataMoverController("datamover_controller", 
            [f"adc_dm{i}" for i in range(4)] + 
            [f"cmacc_dm{i}" for i in range(4)] + 
            self._datamover_controller_extra_ports, addr_bits=40)
        self.sequencer_bus_decoder.add(datamover_controller, 
                                  pipeline=self.config["SEQUENCER_BUS"]["DATAMOVER_CONTROLLER"]["BUS_PIPELINE"])
        self._hdl_modules.append(datamover_controller)
        
        # Assign decoder addresses
        self.sequencer_bus_decoder.assign_address(0)

        # Create AXI-controlled memories

        # Create an AXI BRAM Controller wrapper for the cache
        self.cache_memory_controller = AXIMemoryArray("cache", 
            size_bits=self.config["SEQUENCER_CACHE_MEMORY"]["SIZE_BITS"], 
            width=32, 
            elements=1, 
            axi_id_width=17, # 1 bit needed for AXI crossbar, 16 from PS master
            read_only=False,
            use_rst=False,
            synchronous=self.config["SEQUENCER_CACHE_MEMORY"]["SYNCHRONOUS"],
            primitive=self.config["SEQUENCER_CACHE_MEMORY"]["PRIMITIVE"],
            controller_width=self.config["SEQUENCER_CACHE_MEMORY"]["CONTROLLER_WIDTH"],
            controller_port_input_pipeline=self.config["SEQUENCER_CACHE_MEMORY"]["CONTROLLER_PORT_INPUT_PIPELINE"],
            controller_port_output_pipeline=self.config["SEQUENCER_CACHE_MEMORY"]["CONTROLLER_PORT_OUTPUT_PIPELINE"],                              
            user_port_input_pipeline=self.config["SEQUENCER_CACHE_MEMORY"]["BUS_PORT_INPUT_PIPELINE"],
            user_port_output_pipeline=self.config["SEQUENCER_CACHE_MEMORY"]["BUS_PORT_OUTPUT_PIPELINE"])
        self._hdl_modules.append(self.cache_memory_controller)

        self.instruction_memory_controller = AXIMemoryArray("instruction", 
            size_bits=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["SIZE_BITS"], 
            width=128, 
            elements=1, 
            axi_id_width=17, # 1 bit needed for AXI crossbar, 16 from PS master
            read_only=True,
            use_rst=False,
            primitive=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["PRIMITIVE"], 
            controller_width=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["CONTROLLER_WIDTH"], 
            synchronous=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["SYNCHRONOUS"],
            controller_port_input_pipeline=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["CONTROLLER_PORT_INPUT_PIPELINE"],
            controller_port_output_pipeline=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["CONTROLLER_PORT_OUTPUT_PIPELINE"],
            user_port_input_pipeline=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["BUS_PORT_INPUT_PIPELINE"],
            user_port_output_pipeline=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["BUS_PORT_OUTPUT_PIPELINE"])
        self._hdl_modules.append(self.instruction_memory_controller)

        self.dac_tile_memory_controllers = []
        for i in range(4):
            memory_controller = AXIMemoryArray(f"dac_tile{i}", 
                size_bits=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["SIZE_BITS"], 
                width=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["INTERFACE_WIDTH"],
                elements=4, 
                read_only=True,
                use_rst=True,
                controller_width=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["CONTROLLER_WIDTH"],
                synchronous=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["SYNCHRONOUS"],
                primitive=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["PRIMITIVE"], 
                controller_port_input_pipeline=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["CONTROLLER_PORT_INPUT_PIPELINE"],
                controller_port_output_pipeline=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["CONTROLLER_PORT_OUTPUT_PIPELINE"],   
                user_port_input_pipeline=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["BUS_PORT_INPUT_PIPELINE"],
                user_port_output_pipeline=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["BUS_PORT_OUTPUT_PIPELINE"])
            self._hdl_modules.append(memory_controller)
            self.dac_tile_memory_controllers.append(memory_controller)

        self.cmacc_kernel_memory_controller = AXIMemoryArray(f"cmacc_kernel", 
            size_bits=self.config["CMACC_KERNEL_MEMORY"]["SIZE_BITS"], 
            width=32, 
            elements=self._num_cmaccs, 
            read_only=True,
            use_rst=True,
            controller_width=self.config["CMACC_KERNEL_MEMORY"]["CONTROLLER_WIDTH"],
            synchronous=self.config["CMACC_KERNEL_MEMORY"]["SYNCHRONOUS"],
            primitive=self.config["CMACC_KERNEL_MEMORY"]["PRIMITIVE"], 
            controller_port_input_pipeline=self.config["CMACC_KERNEL_MEMORY"]["CONTROLLER_PORT_INPUT_PIPELINE"],
            controller_port_output_pipeline=self.config["CMACC_KERNEL_MEMORY"]["CONTROLLER_PORT_OUTPUT_PIPELINE"],   
            user_port_input_pipeline=self.config["CMACC_KERNEL_MEMORY"]["BUS_PORT_INPUT_PIPELINE"],
            user_port_output_pipeline=self.config["CMACC_KERNEL_MEMORY"]["BUS_PORT_OUTPUT_PIPELINE"])
        self._hdl_modules.append(self.cmacc_kernel_memory_controller)

        self.dac_dma_descriptor_memory_controller = AXIMemoryArray(f"dac_dma_descriptor", 
            size_bits=self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"], 
            width=64, 
            elements=self._num_dacs, 
            read_only=True,
            use_rst=False,
            controller_width=self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_WIDTH"],
            synchronous=self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["SYNCHRONOUS"],
            primitive=self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["PRIMITIVE"], 
            controller_port_input_pipeline=self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_PORT_INPUT_PIPELINE"],
            controller_port_output_pipeline=self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_PORT_OUTPUT_PIPELINE"],   
            user_port_input_pipeline=self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["BUS_PORT_INPUT_PIPELINE"],
            user_port_output_pipeline=self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["BUS_PORT_OUTPUT_PIPELINE"])
        self._hdl_modules.append(self.dac_dma_descriptor_memory_controller)

        self.adc_dma_descriptor_memory_controller = AXIMemoryArray(f"adc_dma_descriptor", 
            size_bits=self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"], 
            width=64, 
            controller_width=self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_WIDTH"],
            elements=self._num_adcs, 
            read_only=True,
            use_rst=False,
            synchronous=self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["SYNCHRONOUS"],
            primitive=self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["PRIMITIVE"], 
            controller_port_input_pipeline=self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_PORT_INPUT_PIPELINE"],
            controller_port_output_pipeline=self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_PORT_OUTPUT_PIPELINE"],   
            user_port_input_pipeline=self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["BUS_PORT_INPUT_PIPELINE"],
            user_port_output_pipeline=self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["BUS_PORT_OUTPUT_PIPELINE"])
        self._hdl_modules.append(self.adc_dma_descriptor_memory_controller)

        self.cmacc_dma_descriptor_memory_controller = AXIMemoryArray(f"cmacc_dma_descriptor", 
            size_bits=self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"], 
            width=64, 
            controller_width=self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_WIDTH"],
            elements=self._num_cmaccs, 
            read_only=True,
            use_rst=False,
            synchronous=self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["SYNCHRONOUS"],
            primitive=self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["PRIMITIVE"], 
            controller_port_input_pipeline=self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_PORT_INPUT_PIPELINE"],
            controller_port_output_pipeline=self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["CONTROLLER_PORT_OUTPUT_PIPELINE"],   
            user_port_input_pipeline=self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["BUS_PORT_INPUT_PIPELINE"],
            user_port_output_pipeline=self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["BUS_PORT_OUTPUT_PIPELINE"])
        self._hdl_modules.append(self.cmacc_dma_descriptor_memory_controller)
    
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
            memory_tcl += self.cmacc_kernel_memory_controller.generate_ip_tcl(ip_directory)
            memory_tcl += self.dac_dma_descriptor_memory_controller.generate_ip_tcl(ip_directory)
            memory_tcl += self.adc_dma_descriptor_memory_controller.generate_ip_tcl(ip_directory)
            memory_tcl += self.cmacc_dma_descriptor_memory_controller.generate_ip_tcl(ip_directory)
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
                f"CONFIG.PRIM_SOURCE {{{self.config['CLK_WIZ']['INPUT_SOURCE_TYPE']}}} "
                f"CONFIG.PRIM_IN_FREQ {{{self.config['CLK_WIZ']['INPUT_FREQ_HZ']*1e-6}}} "
                "CONFIG.FEEDBACK_SOURCE {FDBK_AUTO} "
                "CONFIG.MMCM_DIVCLK_DIVIDE {1} "
                "CONFIG.MMCM_BANDWIDTH {OPTIMIZED} "
                "CONFIG.MMCM_COMPENSATION {AUTO} "
                f"CONFIG.CLKIN1_JITTER_PS {{{self.config['CLK_WIZ']['INPUT_JITTER_PS']}}} "
                "CONFIG.USE_INCLK_SWITCHOVER {false} ")
            
            clock_properties += f"CONFIG.NUM_OUT_CLKS {{{len(self.config['CLK_WIZ']['GENERATED_CLOCKS'])}}} "
            
            for i,(clk,freq) in enumerate(self.config["CLK_WIZ"]["GENERATED_CLOCKS"].items()):
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
            f.write(f"set_property -dict [list CONFIG.FREQ_HZ {{{self.config['CLK104_PL_CLK']['FREQ_HZ']}}}] [get_bd_intf_ports CLK104_PL_CLK]\n")
            
            # Connect the clock from the 8A34001 to the clocking wizard
            # connect_bd_net(f, "hedgehog/clk_8A34001_out3_ibufds/IBUF_OUT", f"hedgehog/clk_wiz/clk_in2")
            f.write(f"set_property -dict [list CONFIG.FREQ_HZ {{{self.config['CLK_8A34001_Q3_OUT']['FREQ_HZ']}}}] [get_bd_intf_ports CLK_8A34001_Q3_OUT]\n")

            # Expose the locked signal to the PS
            connect_bd_net(f, f"hedgehog/clk_wiz_locked", f"hedgehog/clk_wiz/locked")

            # Create resets modules for all of the generated clocks
            for clk in self.config["CLK_WIZ"]["GENERATED_CLOCKS"].keys():
                create_ip(f, name=f"hedgehog/proc_sys_reset_{clk}", vlnv="xilinx.com:ip:proc_sys_reset:5.0")
                connect_bd_net(f, f"hedgehog/proc_sys_reset_{clk}/slowest_sync_clk", f"hedgehog/clk_wiz/{clk}")
                connect_bd_net(f, f"hedgehog/proc_sys_reset_{clk}/ext_reset_in", f"hedgehog/PS_resetn")
                connect_bd_net(f, f"hedgehog/proc_sys_reset_{clk}/dcm_locked", f"hedgehog/clk_wiz/locked")
            
            # ------------------- PS AXI Clocks -------------------- #
            for ps_clock, clock in self.config["PS_AXI_CLOCKS"].items():
                connect_bd_net(f, f"hedgehog/clk_wiz/{clock}", f"hedgehog/{ps_clock}_aclk")

            # ------------------- AXI Interconnects and SmartConnects -------------------- #

            # Create a SmartConnect for simple configuration peripherals
            # 1 Master: PS AXI LPD Master (plus any DataMovers)
            # 10 Slaves: RFDC, ADC Axis Switch, 
            #            ADC DMA descriptors, CMACC DMA descriptors, DAC DMA descriptor,
            #            CMACC kernel memory, 
            #            DAC Tile 0 memory, DAC Tile 1 memory, DAC Tile 2 memory, DAC Tile 3 memory
            create_ip(f, name="hedgehog/config_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, 
                         name="hedgehog/config_smartconnect", 
                         properties={"NUM_MI": 10, 
                                     "NUM_SI": 1 + self._config_smartconnect_extra_datamovers, 
                                     "NUM_CLKS": len(self.config['CONFIG_SMARTCONNECT']['CLOCKS'])})
            config_smartconnect_datamover_port = 1
            for i,clk in enumerate(self.config['CONFIG_SMARTCONNECT']['CLOCKS']):
                connect_bd_net(f, f"hedgehog/config_smartconnect/aclk{'' if i == 0 else i}", f"hedgehog/clk_wiz/{clk}")
            connect_bd_net(f, 
                           f"hedgehog/config_smartconnect/aresetn", 
                           f"hedgehog/proc_sys_reset_{self.config['CONFIG_SMARTCONNECT']['CLOCKS'][0]}/interconnect_aresetn")
            config_smartconnect_target_address_spaces = ["/ps/Data"]

            # Connect it to the PS
            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/S00_AXI", f"hedgehog/PS_M_AXI_LPD")

            # Create an AXI Crossbar for more rapid access to cache and instruction memories
            # 1 Master: PS AXI Master 1 (plus any DataMovers)
            # 2 slaves: cache, instruction memory
            create_ip(f, name="hedgehog/sequencer_memory_crossbar", vlnv="xilinx.com:ip:axi_crossbar:2.1")
            set_property(f, name="hedgehog/sequencer_memory_crossbar", 
                         properties={"NUM_SI": 1 + self._sequencer_memory_crossbar_extra_datamovers,
                                     "NUM_MI": 2,
                                     "STRATEGY": 1,
                                     "CONNECTIVITY_MODE": "SAMD"})
            sequencer_memory_crossbar_datamover_port = 1        
            connect_bd_net(f, "hedgehog/sequencer_memory_crossbar/aclk", "hedgehog/clk_wiz/" + self.config["SEQUENCER_MEMORY_CROSSBAR"]["CLOCK"])
            connect_bd_net(f, 
                           "hedgehog/sequencer_memory_crossbar/aresetn", 
                           f"hedgehog/proc_sys_reset_{self.config['SEQUENCER_MEMORY_CROSSBAR']['CLOCK']}/interconnect_aresetn")
            sequencer_memory_crossbar_target_address_spaces = ["/ps/Data"]

            # Connect it to the PS
            connect_bd_intf_net(f, f"hedgehog/sequencer_memory_crossbar/S00_AXI", f"hedgehog/PS_M_AXI1")

            # Create a SmartConnect for high-performance bulk transfers
            # 9 Masters: PS AXI Master 0, ADC AXI DataMover 0-3 S2MM, 
            #           CMACC Signal AXI DataMover 0-3 S2MM (plus any extra DataMovers)
            # 6 Slaves: PS AXI Slave HPC0, PS AXI Slave HPC1, PS AXI Slave HP0, PS AXI Slave HP1, PL DDR C0, PL DDR C1
            create_ip(f, name="hedgehog/bulk_smartconnect", vlnv="xilinx.com:ip:smartconnect:1.0")
            set_property(f, name="hedgehog/bulk_smartconnect", 
                         properties={"NUM_MI": 6, 
                                     "NUM_SI": 9 + self._bulk_memory_smartconnect_extra_datamovers, 
                                     "NUM_CLKS": 3})
            bulk_memory_smartconnect_datamover_port = 9
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aclk", f"hedgehog/clk_wiz/hs_clk")
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aclk1", f"hedgehog/DDR4_C0_ui_clk")
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aclk2", f"hedgehog/DDR4_C1_ui_clk")
            connect_bd_net(f, f"hedgehog/bulk_smartconnect/aresetn", f"hedgehog/proc_sys_reset_hs_clk/interconnect_aresetn")
            bulk_memory_smartconnect_target_address_spaces = ["/ps/Data"]

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
            rfdc_config_string = ("CONFIG.ADC_DSA_RTS {true} "
                                  "CONFIG.DAC_VOP_RTS {true} "
                                  f"CONFIG.Axiclk_Freq {{{self.config['RFDC']['AXI_CLK_FREQ_HZ']*1e-6}}} ")
            
            for dc in ["ADC", "DAC"]:
                rfdc_config_string += f"CONFIG.{dc}_NCO_RTS {{true}} "
                rfdc_config_string += f"CONFIG.{dc}_RTS {{true}} "
                
                for tile in range(4):
                    tile_stream_clock = self.config['CLK_WIZ']['GENERATED_CLOCKS'][f'{dc.lower()}_tile3_clk' if tile == 3 else f'{dc.lower()}_clk']
                    tile_sample_rate = self.config['RFDC'][dc]['TILE_SAMPLE_RATE_HZ'][tile]
                    
                    rfdc_config_string += (
                        f"CONFIG.{dc}{tile}_Clock_Dist {{{self.config['RFDC'][dc]['TILE_DISTRIBUTE_CLK'][tile]}}} "
                        f"CONFIG.{dc}{tile}_Clock_Source {{{self.config['RFDC'][dc]['TILE_CLK_SOURCE'][tile]}}} "
                        f"CONFIG.{dc}{tile}_Enable {{1}} "
                        f"CONFIG.{dc}{tile}_Fabric_Freq {{{tile_stream_clock*1e-6:.3f}}} "
                        f"CONFIG.{dc}{tile}_Multi_Tile_Sync {{{str(self.config['RFDC'][dc]['TILE_MTS'][tile]).lower()}}} "
                        f"CONFIG.{dc}{tile}_Outclk_Freq {{{tile_sample_rate*1e-6 / 16:.3f}}} "
                        f"CONFIG.{dc}{tile}_PLL_Enable {{{str(self.config['RFDC'][dc]['TILE_PLL'][tile]).lower()}}} "
                        f"CONFIG.{dc}{tile}_Refclk_Freq {{{self.config['RFDC'][dc]['TILE_REFCLK_FREQ_HZ'][tile]*1e-6:.3f}}} "
                        f"CONFIG.{dc}{tile}_Sampling_Rate {{{tile_sample_rate*1e-9:.3f}}} "
                    )

                    if dc == "DAC":
                        rfdc_config_string += f"CONFIG.DAC{tile}_VOP {{{self.config['RFDC']['DAC']['TILE_VOP'][tile]}}} "

                    for block in range(4):
                        interface_width = self.config['RFDC'][dc]['CHANNEL_INTERFACE_WIDTH'][tile*4 + block]

                        scale = tile_sample_rate * 32 / (interface_width * tile_stream_clock)
                        
                        if round(scale) != round(scale, 6):
                            raise ValueError(f"Invalid scale for {dc}{tile}{block}"
                                            f" ({scale})")
                        
                        scale = round(scale)

                        if scale not in [1,2,3,4,5,6,8,10,12,16,20,24,40]:
                            raise ValueError(f"Invalid scale for {dc}{tile}{block}"
                                            f" ({scale})")
                        
                        
                        rfdc_config_string += f"CONFIG.{dc}_Coarse_Mixer_Freq{tile}{block} {{{0 if dc == 'ADC' else 3}}} "
                        rfdc_config_string += f"CONFIG.{dc}_Data_Width{tile}{block} {{{interface_width // 16}}} "
                        rfdc_config_string += f"CONFIG.{dc}_Mixer_Mode{tile}{block} {{0}} "
                        rfdc_config_string += f"CONFIG.{dc}_Mixer_Type{tile}{block} {{2}} "
                        rfdc_config_string += f"CONFIG.{dc}_RESERVED_1_{tile}{block} {{false}} "
                        rfdc_config_string += f"CONFIG.{dc}_Slice{tile}{block}_Enable {{true}} "
                                    
                        if dc == "ADC":
                            rfdc_config_string += f"CONFIG.ADC_Dither{tile}{block} {{{self.config['RFDC']['ADC']['CHANNEL_DITHER'][tile*4 + block]}}} "
                            rfdc_config_string += f"CONFIG.ADC_Data_Type{tile}{block} {{1}} "
                            rfdc_config_string += f"CONFIG.ADC_OBS{tile}{block} {{false}} "
                            rfdc_config_string += f"CONFIG.ADC_Decimation_Mode{tile}{block} {{{scale}}} "
                        else:
                            rfdc_config_string += f"CONFIG.DAC_Interpolation_Mode{tile}{block} {{{scale}}} "
                            rfdc_config_string += f"CONFIG.DAC_Mode{tile}{block} {{0}} "
                            rfdc_config_string += f"CONFIG.DAC_Nyquist{tile}{block} {{{self.config['RFDC']['DAC']['CHANNEL_NYQUIST_ZONE'][tile*4 + block]}}} "
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
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aclk", f"hedgehog/clk_wiz/{self.config['RFDC']['DAC']['TILE_AXIS_CLOCKS'][i]}")
                connect_bd_net(f, f"hedgehog/rfdc/s{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")        
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aclk", f"hedgehog/clk_wiz/{self.config['RFDC']['ADC']['TILE_AXIS_CLOCKS'][i]}")
                connect_bd_net(f, f"hedgehog/rfdc/m{i}_axis_aresetn", f"hedgehog/clk_wiz/locked")

            # Connect RFDC to the config smartconnect and assign it address space
            connect_bd_intf_net(f, "hedgehog/config_smartconnect/M00_AXI", "hedgehog/rfdc/s_axi")
            assign_bd_address(f, 
                              "/ps/Data", 
                              "hedgehog/rfdc/" + self.config["RFDC"]["AXI_SEGMENT"], 
                              self.config["RFDC"]["AXI_ADDRESS"], 
                              self.config["RFDC"]["AXI_SIZE_BITS"] // 8)
                
            # create_ip(f, name="hedgehog/axi_register_slice_rfdc", vlnv="xilinx.com:ip:axi_register_slice:2.1")
            # connect_bd_intf_net(f, "hedgehog/axi_register_slice_rfdc/M_AXI", "hedgehog/rfdc/s_axi")
            # connect_bd_intf_net(f, "hedgehog/axi_register_slice_rfdc/S_AXI", "hedgehog/config_smartconnect/M01_AXI")
            # connect_bd_net(f, "hedgehog/axi_register_slice_rfdc/aclk", "hedgehog/PS_clk_250")
            # connect_bd_net(f, "hedgehog/axi_register_slice_rfdc/aresetn", "hedgehog/proc_sys_reset_PS_clk_250/peripheral_aresetn")
            
            # Synchronize the SYSREF signal from the CLK104 to the stream clock of DAC tile 0
            create_module(f, f"hedgehog/pl_sysref_capture", "acadia_sysref_capture")
            connect_bd_intf_net(f, "hedgehog/CLK104_PL_SYSREF", "hedgehog/pl_sysref_capture/sysref")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/clk", f"hedgehog/clk_wiz/{self.config['RFDC']['DAC']['TILE_AXIS_CLOCKS'][0]}")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/sysref_out", "hedgehog/rfdc/user_sysref_dac")
            connect_bd_net(f, "hedgehog/pl_sysref_capture/sysref_out", "hedgehog/rfdc/user_sysref_adc")
            
            # ------------------- ADC AXIS Switch -------------------- #

            # Create an AXI switch for multiplexing the ADC outputs to the AXI DMAs
            # TODO: make more compatible with varying ADC widths (TDATA_NUM_BYTES)
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
                                        f"CONFIG.NUM_MI {{{self._num_adcs + self._num_cmaccs}}} "
                                        "CONFIG.ROUTING_MODE {1} "
                                        f"CONFIG.TDATA_NUM_BYTES {{{self.config['ADC_AXIS_SWITCH']['WIDTH'] // 8}}} "
                                        "CONFIG.DECODER_REG {1} "
                                        "CONFIG.OUTPUT_REG {1} "
                                        "CONFIG.HAS_TLAST {0} "
                                        "CONFIG.HAS_TREADY {0} "
                                        "CONFIG.TDEST_WIDTH {0}")

            connect_bd_net(f, f"hedgehog/axis_switch_adc/aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # Connect the switch to the AXI network and assign it an address in the PS address space
            connect_bd_intf_net(f, f"hedgehog/config_smartconnect/M01_AXI", f"hedgehog/axis_switch_adc/S_AXI_CTRL")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/s_axi_ctrl_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/axis_switch_adc/s_axi_ctrl_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            assign_bd_address(f, 
                              "/ps/Data", 
                              "hedgehog/axis_switch_adc/" + self.config["ADC_AXIS_SWITCH"]["AXI_SEGMENT"], 
                              self.config["ADC_AXIS_SWITCH"]["AXI_ADDRESS"], 
                              self.config["ADC_AXIS_SWITCH"]["AXI_SIZE_BITS"] // 8)

            # Connect the ADC interfaces to the AXIS switch
            for channel in range(16):
                tile = channel // 4
                block = channel % 4
                create_module(f, f"hedgehog/adc{channel}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/adc{channel}_pipeline", 
                             properties=f"WIDTH {{{self.config['RFDC']['ADC']['CHANNEL_INTERFACE_WIDTH'][channel]}}} "
                                        f"STAGES {{{self.config['RFDC']['ADC']['CHANNEL_PIPELINE_STAGES'][channel]}}}")
                connect_bd_net(f, f"hedgehog/adc{channel}_pipeline/clk", "hedgehog/clk_wiz/" + self.config['RFDC']['ADC']['TILE_AXIS_CLOCKS'][tile])

                connect_bd_intf_net(f, f"hedgehog/rfdc/m{tile}{block}_axis", 
                                       f"hedgehog/adc{channel}_pipeline/S_AXIS")
                
                connect_bd_intf_net(f, f"hedgehog/adc{channel}_pipeline/M_AXIS", 
                                       f"hedgehog/axis_switch_adc/S{channel:02d}_AXIS")
                
            # ------------------- DAC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/dac_dma_descriptor_memory", f"dac_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi", "hedgehog/config_smartconnect/M02_AXI")
            connect_bd_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/dac_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                
            # ------------------- ADC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/adc_dma_descriptor_memory", f"adc_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi", f"hedgehog/config_smartconnect/M03_AXI")
            connect_bd_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/adc_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # ------------------- CMACC Kernel Memory -------------------- #
            create_module(f, f"hedgehog/cmacc_kernel_memory", f"cmacc_kernel_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/cmacc_kernel_memory/s_axi", f"hedgehog/config_smartconnect/M04_AXI")
            connect_bd_net(f, f"hedgehog/cmacc_kernel_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/cmacc_kernel_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # ------------------- CMACC DMA Descriptor Memory -------------------- #
            create_module(f, f"hedgehog/cmacc_dma_descriptor_memory", f"cmacc_dma_descriptor_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi", f"hedgehog/config_smartconnect/M05_AXI")
            connect_bd_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/cmacc_dma_descriptor_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            
            # ------------------- DAC Memory -------------------- #
            for tile in range(4):
                create_module(f, f"hedgehog/dac_tile{tile}_memory", f"dac_tile{tile}_axi_memory")
                connect_bd_intf_net(f, f"hedgehog/dac_tile{tile}_memory/s_axi", f"hedgehog/config_smartconnect/M{6+tile:02d}_AXI")
                connect_bd_net(f, f"hedgehog/dac_tile{tile}_memory/s_axi_aclk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/dac_tile{tile}_memory/s_axi_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

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
            if self.config["SEQUENCER_BUS"]["RFDC_RTS"]["NCO_CLK"] != "seq_clk":
                set_property(f, "hedgehog/rfdc_rts_regs", properties={"SYNCHRONOUS": "false"})
            
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
            connect_bd_net(f, f"hedgehog/rfdc_rts_regs/nco_dest_clk", f"hedgehog/clk_wiz/" + self.config["SEQUENCER_BUS"]["RFDC_RTS"]["NCO_CLK"])
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
            connect_bd_intf_net(f, f"hedgehog/cache_memory/s_axi", f"hedgehog/sequencer_memory_crossbar/M00_AXI")
            connect_bd_net(f, 
                           "hedgehog/cache_memory/s_axi_aclk", 
                           "hedgehog/clk_wiz/" + self.config['SEQUENCER_MEMORY_CROSSBAR']['CLOCK'])
            connect_bd_net(f, 
                           "hedgehog/cache_memory/s_axi_aresetn", 
                           f"hedgehog/proc_sys_reset_{self.config['SEQUENCER_MEMORY_CROSSBAR']['CLOCK']}/peripheral_aresetn")
            
            # Connect the cache to the sequencer bus decoder
            connect_bd_intf_net(f, 
                                f"hedgehog/sequencer_bus_decoder/cache", 
                                f"hedgehog/cache_memory/mem0")
            
            # ------------------- Sequencer Instruction Memory -------------------- #
            create_module(f, "hedgehog/instruction_memory", "instruction_axi_memory")
            connect_bd_intf_net(f, f"hedgehog/instruction_memory/s_axi", f"hedgehog/sequencer_memory_crossbar/M01_AXI")
            connect_bd_net(f, 
                           "hedgehog/instruction_memory/s_axi_aclk", 
                           "hedgehog/clk_wiz/" + self.config['SEQUENCER_MEMORY_CROSSBAR']['CLOCK'])
            connect_bd_net(f, 
                           "hedgehog/instruction_memory/s_axi_aresetn", 
                           f"hedgehog/proc_sys_reset_{self.config['SEQUENCER_MEMORY_CROSSBAR']['CLOCK']}/peripheral_aresetn")
            
            # Connect it to the sequencer
            connect_bd_intf_net(f, f"hedgehog/sequencer/instruction_mem", f"hedgehog/instruction_memory/mem0")

            # ------------------- Additional DataMovers -------------------- #
            # First, create the DataMover Controller and connect it to the bus
            create_module(f, f"hedgehog/datamover_controller", "datamover_controller")
            connect_bd_intf_net(f, f"hedgehog/sequencer_bus_decoder/datamover_controller", f"hedgehog/datamover_controller/master_bus")
            connect_bd_net(f, f"hedgehog/datamover_controller/datamover_cmd_clk", "hedgehog/clk_wiz/seq_clk")
            connect_bd_net(f, f"hedgehog/datamover_controller/nrst", "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

            # Create and connect the DataMovers itself
            for name,settings in self.config["DATAMOVERS"].items():
                create_ip(f, name=f"hedgehog/{name}", vlnv="xilinx.com:ip:axi_datamover:5.1")
                
                dm_config = ("CONFIG.c_enable_cache_user {true} "
                             "CONFIG.c_addr_width {40} ")

                for direction in ["MM2S", "S2MM"]:
                    if settings[f"ENABLE_{direction}"]:
                        dm_config += f"CONFIG.c_m_axi_{direction.lower()}_data_width {{{settings[f'{direction}_AXI_WIDTH']}}} "
                        dm_config += f"CONFIG.c_{'m' if direction == 'MM2S' else 's'}_axis_{direction.lower()}_tdata_width {{{settings[f'{direction}_AXIS_WIDTH']}}} "
                        dm_config += f"CONFIG.c_{direction.lower()}_burst_size {{256}} "
                        dm_config += f"CONFIG.c_{direction.lower()}_btt_used {{23}} "
                        dm_config += f"CONFIG.c_include_{direction.lower()} {{Full}} "
                        dm_config += f"CONFIG.c_include_{direction.lower()}_stsfifo {{true}} "
                        dm_config += f"CONFIG.c_{direction.lower()}_addr_pipe_depth {{3}} "
                        dm_config += f"CONFIG.c_{direction.lower()}_include_sf {{false}} "
                        dm_config += f"CONFIG.c_enable_{direction.lower()} {{1}} "
                        if direction == "S2MM":
                            dm_config += f"CONFIG.c_m_axi_{direction.lower()}_awid {{0}} "
                            dm_config += f"CONFIG.c_{direction.lower()}_support_indet_btt {{true}} "
                    else:
                        dm_config += f"CONFIG.c_include_{direction.lower()} {{Omit}} "
                        dm_config += f"CONFIG.c_include_{direction.lower()}_stsfifo {{false}} "
                                            
                set_property(f, name=f"hedgehog/{name}", properties={"c_m_axi_s2mm_data_width.VALUE_SRC": "USER", "c_s_axis_s2mm_tdata_width.VALUE_SRC": "USER"})
                set_property(f, name=f"hedgehog/{name}", properties=dm_config)                    

                # Connect the AXI streams
                for stream_port in ["M_AXIS_MM2S", "S_AXIS_S2MM"]:
                    if stream_port in settings:
                        connect_bd_intf_net(f, f"hedgehog/{name}/{stream_port}", "hedgehog/" + settings[stream_port])
                
                for direction in ["MM2S", "S2MM"]:
                    if settings[f"ENABLE_{direction}"]:
                        # Connect the AXI masters
                        if settings[f"{direction}_AXI"] == "config_smartconnect":
                            destination = f"hedgehog/config_smartconnect/S{config_smartconnect_datamover_port:02}_AXI"
                            config_smartconnect_datamover_port += 1
                            config_smartconnect_target_address_spaces.append(f"/hedgehog/{name}/Data_{direction}")
                        elif settings[f"{direction}_AXI"] == "bulk_memory_smartconnect":
                            destination = f"hedgehog/bulk_smartconnect/S{bulk_memory_smartconnect_datamover_port:02}_AXI"
                            bulk_memory_smartconnect_datamover_port += 1
                            bulk_memory_smartconnect_target_address_spaces.append(f"/hedgehog/{name}/Data_{direction}")
                        elif settings[f"{direction}_AXI"] == "sequencer_memory_crossbar":
                            destination = f"hedgehog/sequencer_memory_crossbar/S{sequencer_memory_crossbar_datamover_port:02}_AXI"
                            sequencer_memory_crossbar_datamover_port += 1
                            sequencer_memory_crossbar_target_address_spaces.append(f"/hedgehog/{name}/Data_{direction}")

                        connect_bd_intf_net(f, f"hedgehog/{name}/M_AXI_{direction}", destination)

                        # Connect clocks and resets for the command and status port 
                        # (for some reason the clock pins are different between s2mm and mm2s)
                        # These will both connect to the sequencer clock since the command and status ports
                        # are controlled by the bus through the DataMover controller
                        connect_bd_net(f, 
                                       f"hedgehog/{name}/m_axis_{direction.lower()}_cmdsts_a{'w' if direction == 'S2MM' else ''}clk", 
                                       f"hedgehog/clk_wiz/{settings['CMDSTS_CLOCK']}")
                        connect_bd_net(f, 
                                       f"hedgehog/{name}/m_axis_{direction.lower()}_cmdsts_aresetn",
                                       f"hedgehog/proc_sys_reset_{settings['CMDSTS_CLOCK']}/peripheral_aresetn")

                        # Connect AXI Master clocks and resets
                        connect_bd_net(f, 
                                       f"hedgehog/{name}/m_axi_{direction}_aclk", 
                                       f"hedgehog/clk_wiz/{settings['AXI_CLOCK']}")
                        connect_bd_net(f, 
                                       f"hedgehog/{name}/m_axi_{direction}_aresetn", 
                                       f"hedgehog/proc_sys_reset_{settings['AXI_CLOCK']}/peripheral_aresetn")

                        # Use an AXIS FIFO with independent clocks
                        # create_ip(f, name=f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo", vlnv="xilinx.com:ip:axis_data_fifo:2.0")
                        # set_property(f, name=f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo", properties={"FIFO_DEPTH": 16, "IS_ACLK_ASYNC": 1})
                        # connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/m_axis_aclk", f"hedgehog/PS_AXI_clk")
                        # connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/s_axis_aclk", f"hedgehog/clk_wiz/seq_clk")
                        # connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/s_axis_aresetn", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")
                        # connect_bd_intf_net(f, f"hedgehog/datamover_controller/cfg_dm_{direction}_cmd", f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/S_AXIS")
                        # connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm_{direction}_cmd_fifo/M_AXIS", f"hedgehog/cfg_axi_dm/S_AXIS_{direction.upper()}_CMD")
                        connect_bd_intf_net(f, 
                                            f"hedgehog/datamover_controller/{name}_{direction}_cmd", 
                                            f"hedgehog/{name}/S_AXIS_{direction.upper()}_CMD")
                        
                        # create_ip(f, name=f"hedgehog/cfg_axi_dm_{direction}_sts_fifo", vlnv="xilinx.com:ip:axis_data_fifo:2.0")
                        # set_property(f, name=f"hedgehog/cfg_axi_dm_{direction}_sts_fifo", properties={"FIFO_DEPTH": 16, "IS_ACLK_ASYNC": 1})
                        # connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/m_axis_aclk", f"hedgehog/clk_wiz/seq_clk")
                        # connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/s_axis_aclk", f"hedgehog/PS_AXI_clk")
                        # connect_bd_net(f, f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/s_axis_aresetn", f"hedgehog/proc_sys_reset_PS_AXI_clk/peripheral_aresetn")
                        # connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm/M_AXIS_{direction.upper()}_STS", f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/S_AXIS")
                        # connect_bd_intf_net(f, f"hedgehog/cfg_axi_dm_{direction}_sts_fifo/M_AXIS", f"hedgehog/datamover_controller/cfg_dm_{direction}_sts")
                        connect_bd_intf_net(f, 
                                            f"hedgehog/datamover_controller/{name}_{direction}_sts", 
                                            f"hedgehog/{name}/M_AXIS_{direction.upper()}_STS")

                        # Connect the error signal to the controller through a CDC
                        create_ip(f, name=f"hedgehog/xpm_cdc_{name}_{direction}_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                        set_property(f, name=f"hedgehog/xpm_cdc_{name}_{direction}_err", properties={"CDC_TYPE": "xpm_cdc_single"})
                        connect_bd_net(f, f"hedgehog/xpm_cdc_{name}_{direction}_err/src_in", f"hedgehog/{name}/{direction}_err")
                        connect_bd_net(f, f"hedgehog/xpm_cdc_{name}_{direction}_err/dest_out", f"hedgehog/datamover_controller/{name}_{direction}_err")
                        connect_bd_net(f, f"hedgehog/xpm_cdc_{name}_{direction}_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")
                        connect_bd_net(f, f"hedgehog/xpm_cdc_{name}_{direction}_err/src_clk", f"hedgehog/clk_wiz/{settings['AXI_CLOCK']}")
            
            # ------------------- Sequencer flags -------------------- #
            create_ip(f, name="hedgehog/xlconst_0", vlnv="xilinx.com:ip:xlconstant:1.1")
            set_property(f, name="hedgehog/xlconst_0", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
            connect_bd_net(f, f"hedgehog/sequencer/ext_in", f"hedgehog/xlconst_0/Dout")
            
            # ------------------- PS GPIO and Interrupt Connections -------------------- #
            # Create a concatenator for the PS inputs
            create_concatenator(f, "hedgehog/xlconcat_ps_gpio_in", 
                                [32, 32, self.config["PS_GPIO5"]["WIDTH"]])
            connect_bd_net(f, "hedgehog/xlconcat_ps_gpio_in/dout", "hedgehog/PS_GPIO_IN")
            
            for idx, gpio_port in enumerate([3,4,5]):
                connect_bd_net(f, f"hedgehog/xlconcat_ps_gpio_in/In{idx}", f"hedgehog/ps_gpio{gpio_port}_dataport/gpio_in")
                
                # Slice the PS outputs
                create_slice(f, name=f"hedgehog/xlslice_ps_gpio{gpio_port}_out", 
                                 input_width=64 + self.config["PS_GPIO5"]["WIDTH"], 
                                 input_from=(64 + self.config["PS_GPIO5"]["WIDTH"] - 1 if gpio_port == 5 else (idx+1)*32-1),
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
            
            # ------------------- ADC DMAs -------------------- #

            for d in range(self._num_adcs):

                # ------------------- Real-time DMAs -------------------- #
                create_module(f, f"hedgehog/adc_dma{d}", "acadia_dma")
                set_property(f, 
                             name=f"hedgehog/adc_dma{d}", 
                             properties={"DATA_WIDTH": self.config["ADC_CAPTURE_PATH"]["FIFO_INPUT_WIDTH"][d],
                                         "DESCRIPTOR_MEM_ADDR_WIDTH": next_highest_power_of_2(self.config["ADC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 64, log=True)})
                connect_bd_net(f, 
                               f"hedgehog/adc_dma{d}/clk", 
                               f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, 
                               f"hedgehog/adc_dma{d}/nrst", 
                               f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the ADC DMA signals to the dataports
                connect_bd_net(f, 
                               f"hedgehog/sequencer_bus_decoder/adc_dma{d}_fifo_mosi", 
                               f"hedgehog/adc_dma{d}/descriptor_address_fifo_in")
                connect_bd_net(f, 
                               f"hedgehog/sequencer_bus_decoder/adc_dma{d}_fifo_wr", 
                               f"hedgehog/adc_dma{d}/descriptor_address_fifo_wr")
                connect_bd_net(f, 
                               f"hedgehog/dma_trigger_dataport/adc_dma{d}", 
                               f"hedgehog/adc_dma{d}/trigger")
                connect_bd_net(f, 
                               f"hedgehog/dma_running_dataport/adc_dma{d}", 
                               f"hedgehog/adc_dma{d}/running")
                connect_bd_net(f, 
                               f"hedgehog/dma_fifo_empty_dataport/adc_dma{d}", 
                               f"hedgehog/adc_dma{d}/descriptor_address_fifo_empty")
                connect_bd_net(f, 
                               f"hedgehog/dma_fifo_almost_empty_dataport/adc_dma{d}", 
                               f"hedgehog/adc_dma{d}/descriptor_address_fifo_almost_empty")
                
                # Connect to descriptor memory
                connect_bd_intf_net(f, 
                                    f"hedgehog/adc_dma{d}/descriptor_mem", 
                                    f"hedgehog/adc_dma_descriptor_memory/mem{d}")
                
                # ------------------- Stream FIFOs -------------------- #

                create_module(f, f"hedgehog/fifo_adc_dm{d}", "acadia_adc_fifo")
                set_property(f, 
                             name=f"hedgehog/fifo_adc_dm{d}",
                             properties={"WORD_WIDTH": 32,
                                        "INPUT_WORDS": self.config["ADC_CAPTURE_PATH"]["FIFO_INPUT_WIDTH"][d] // 32,
                                        "OUTPUT_WORDS": self.config["ADC_CAPTURE_PATH"]["FIFO_OUTPUT_WIDTH"][d] // 32, 
                                        "INPUT_DEPTH": self.config["ADC_CAPTURE_PATH"]["FIFO_DEPTH"][d], 
                                        "MEMORY_TYPE": self.config["ADC_CAPTURE_PATH"]["FIFO_PRIMITIVE"][d],
                                        "ASYNCHRONOUS": str(self.config["ADC_CAPTURE_PATH"]["FIFO_ASYNCHRONOUS"][d]).lower(),
                                        "MONITOR_SYNC": str(self.config["ADC_CAPTURE_PATH"]["MONITOR_SYNCHRONOUS"][d]).lower()})

                connect_bd_net(f, 
                               f"hedgehog/fifo_adc_dm{d}/signal_in_clk", 
                               f"hedgehog/clk_wiz/" + self.config["ADC_CAPTURE_PATH"]["FIFO_INPUT_CLOCK"][d])
                connect_bd_net(f, 
                               f"hedgehog/fifo_adc_dm{d}/m_axis_aclk", 
                               f"hedgehog/clk_wiz/" + self.config["ADC_CAPTURE_PATH"]["FIFO_OUTPUT_CLOCK"][d])
                connect_bd_net(f, 
                               f"hedgehog/fifo_adc_dm{d}/signal_in_nrst", 
                               f"hedgehog/proc_sys_reset_{self.config['ADC_CAPTURE_PATH']['FIFO_INPUT_CLOCK'][d]}/peripheral_aresetn")
                
                # Connect the monitor port to the sequencer dataports
                connect_bd_net(f, 
                               f"hedgehog/fifo_adc_dm{d}/monitor_clk", 
                               f"hedgehog/clk_wiz/seq_clk")

                # Connect the error signals through CDC synchronizers
                for s in ["overflow", "misalignment", "rst"]:
                    connect_bd_net(f, 
                                f"hedgehog/fifo_adc_dm{d}/monitor_{s}", 
                                f"hedgehog/adc_fifo_control_dataport/adc_dm{d}_{s}")

                # Create an AXIS pipeline stage and connect it to the switch
                create_module(f, f"hedgehog/adc_dma{d}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/adc_dma{d}_pipeline", 
                             properties=f"WIDTH {{{self.config['ADC_CAPTURE_PATH']['FIFO_OUTPUT_WIDTH'][d]}}} "
                                        f"STAGES {{{self.config['ADC_CAPTURE_PATH']['FIFO_INPUT_PIPELINE'][d]}}}")
                connect_bd_net(f, 
                               f"hedgehog/adc_dma{d}_pipeline/clk", 
                               f"hedgehog/clk_wiz/" + self.config["ADC_CAPTURE_PATH"]["FIFO_INPUT_CLOCK"][d])
                connect_bd_intf_net(f, 
                                    f"hedgehog/axis_switch_adc/M{d:02d}_AXIS", 
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
                                            f"CONFIG.c_m_axi_s2mm_data_width {{{self.config['ADC_CAPTURE_PATH']['DATAMOVER_AXI_WIDTH'][d]}}} "
                                            f"CONFIG.c_s_axis_s2mm_tdata_width {{{self.config['ADC_CAPTURE_PATH']['FIFO_OUTPUT_WIDTH'][d]}}} "
                                            "CONFIG.c_s2mm_btt_used {23} "
                                            f"CONFIG.c_s2mm_burst_size {{{self.config['ADC_CAPTURE_PATH']['DATAMOVER_BURST_SIZE'][d]}}} "
                                            "CONFIG.c_s2mm_support_indet_btt {true} "
                                            "CONFIG.c_mm2s_include_sf {false} "
                                            "CONFIG.c_s2mm_include_sf {false} "
                                            "CONFIG.c_enable_cache_user {true} "
                                            "CONFIG.c_enable_mm2s {0} "
                                            "CONFIG.c_enable_s2mm_adv_sig {0} "
                                            "CONFIG.c_addr_width {40}")

                # Connect clocks and resets
                connect_bd_net(f, 
                               f"hedgehog/adc_dm{d}/m_axi_s2mm_aclk", 
                               f"hedgehog/clk_wiz/{self.config['ADC_CAPTURE_PATH']['FIFO_OUTPUT_CLOCK'][d]}")
                connect_bd_net(f, 
                               f"hedgehog/adc_dm{d}/m_axi_s2mm_aresetn", 
                               f"hedgehog/proc_sys_reset_{self.config['ADC_CAPTURE_PATH']['FIFO_OUTPUT_CLOCK'][d]}/peripheral_aresetn")
                connect_bd_net(f, 
                               f"hedgehog/adc_dm{d}/m_axis_s2mm_cmdsts_awclk", 
                               "hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, 
                               f"hedgehog/adc_dm{d}/m_axis_s2mm_cmdsts_aresetn", 
                               "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the S2MM command and status interfaces to the bus-driven DataMover controller
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/S_AXIS_S2MM_CMD", f"hedgehog/datamover_controller/adc_dm{d}_cmd")
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/M_AXIS_S2MM_STS", f"hedgehog/datamover_controller/adc_dm{d}_sts")

                # Connect the error signal to the controller through a CDC
                create_ip(f, name=f"hedgehog/xpm_cdc_adc_dm{d}_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                set_property(f, name=f"hedgehog/xpm_cdc_adc_dm{d}_err", properties={"CDC_TYPE": "xpm_cdc_single"})
                connect_bd_net(f, f"hedgehog/xpm_cdc_adc_dm{d}_err/src_in", f"hedgehog/adc_dm{d}/s2mm_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_adc_dm{d}_err/dest_out", f"hedgehog/datamover_controller/adc_dm{d}_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_adc_dm{d}_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/xpm_cdc_adc_dm{d}_err/src_clk", f"hedgehog/clk_wiz/{self.config['ADC_CAPTURE_PATH']['FIFO_OUTPUT_CLOCK'][d]}")
            
                # Connect the S2MM stream input to the output of the AXIS Data FIFO
                connect_bd_intf_net(f, f"hedgehog/adc_dm{d}/s_axis_s2mm", f"hedgehog/fifo_adc_dm{d}/M_AXIS")

                # Connect the DMA S2MM master to the bulk memory smartconnect
                connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/S{d+1:02d}_AXI", f"hedgehog/adc_dm{d}/M_AXI_S2MM")

                # Keep track of the address space for this DataMover
                bulk_memory_smartconnect_target_address_spaces.append(f"/hedgehog/adc_dm{d}/Data_S2MM")

            # ------------------- Complex MACCs ------------------- #
            
            for d in range(4):

                # ------------------- The CMACC modules -------------------- #
                create_module(f, f"hedgehog/cmacc{d}", "acadia_complex_macc")
                connect_bd_net(f, f"hedgehog/cmacc{d}/clk", f"hedgehog/clk_wiz/seq_clk")
                
                # Create an AXIS pipeline stage and connect it to the switch
                create_module(f, f"hedgehog/cmacc{d}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/cmacc{d}_pipeline", 
                             properties=f"WIDTH {{{self.config['ADC_AXIS_SWITCH']['WIDTH']}}} "
                                        f"STAGES {{{self.config['CMACC_CAPTURE_PATH']['CMACC_INPUT_PIPELINE'][d]}}}")
                connect_bd_net(f, f"hedgehog/cmacc{d}_pipeline/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_intf_net(f, 
                                    f"hedgehog/axis_switch_adc/M{d+self._num_adcs:02d}_AXIS", 
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
                set_property(f, 
                             name=f"hedgehog/cmacc_dma{d}", 
                             properties={"DATA_WIDTH": 32,
                                         "ADDRESS_WIDTH": next_highest_power_of_2(self.config[f"CMACC_KERNEL_MEMORY"]["SIZE_BITS"] // 32, log=True),
                                         "DESCRIPTOR_MEM_ADDR_WIDTH": next_highest_power_of_2(self.config["CMACC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 64, log=True)})
                connect_bd_net(f, 
                               f"hedgehog/cmacc_dma{d}/clk", 
                               f"hedgehog/clk_wiz/" + self.config['CMACC_CAPTURE_PATH']['FIFO_INPUT_CLOCK'][d])
                connect_bd_net(f, 
                               f"hedgehog/cmacc_dma{d}/nrst", 
                               f"hedgehog/proc_sys_reset_{self.config['CMACC_CAPTURE_PATH']['FIFO_INPUT_CLOCK'][d]}/peripheral_aresetn")

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
                set_property(f, 
                             f"hedgehog/fifo_cmacc_dm{d}", 
                             properties={"WORD_WIDTH": 32,
                                        "INPUT_WORDS": 1,
                                        "OUTPUT_WORDS": self.config["CMACC_CAPTURE_PATH"]["FIFO_OUTPUT_WIDTH"][d] // 32, 
                                        "INPUT_DEPTH": self.config["CMACC_CAPTURE_PATH"]["FIFO_DEPTH"][d], 
                                        "MEMORY_TYPE": self.config["CMACC_CAPTURE_PATH"]["FIFO_PRIMITIVE"][d],
                                        "ASYNCHRONOUS": str(self.config["CMACC_CAPTURE_PATH"]["FIFO_ASYNCHRONOUS"][d]).lower(),
                                        "MONITOR_SYNC": str(self.config["CMACC_CAPTURE_PATH"]["MONITOR_SYNCHRONOUS"][d]).lower()})

                connect_bd_net(f, 
                               f"hedgehog/fifo_cmacc_dm{d}/signal_in_clk", 
                               f"hedgehog/clk_wiz/" + self.config["CMACC_CAPTURE_PATH"]["FIFO_INPUT_CLOCK"][d])
                connect_bd_net(f, 
                               f"hedgehog/fifo_cmacc_dm{d}/m_axis_aclk", 
                               f"hedgehog/clk_wiz/" + self.config["CMACC_CAPTURE_PATH"]["FIFO_OUTPUT_CLOCK"][d])
                connect_bd_net(f, 
                               f"hedgehog/fifo_cmacc_dm{d}/signal_in_nrst", 
                               f"hedgehog/proc_sys_reset_{self.config['CMACC_CAPTURE_PATH']['FIFO_INPUT_CLOCK'][d]}/peripheral_aresetn")
                
                # Connect the monitor port to the sequencer dataports
                connect_bd_net(f, 
                               f"hedgehog/fifo_cmacc_dm{d}/monitor_clk", 
                               f"hedgehog/clk_wiz/seq_clk")

                # Connect the error signals through CDC synchronizers
                for s in ["overflow", "misalignment", "rst"]:
                    connect_bd_net(f, 
                                f"hedgehog/fifo_cmacc_dm{d}/monitor_{s}", 
                                f"hedgehog/adc_fifo_control_dataport/cmacc_dm{d}_{s}")


                # Connect the FIFO stream input to the CMACC signal passthrough
                connect_bd_intf_net(f, f"hedgehog/cmacc{d}/SIGNAL_OUT", f"hedgehog/fifo_cmacc_dm{d}/SIGNAL_IN")

                # ------------------- AXI DataMovers -------------------- #

                # Create the DataMover itself
                create_ip(f, name=f"hedgehog/cmacc_dm{d}", vlnv="xilinx.com:ip:axi_datamover:5.1")
                set_property(f, name=f"hedgehog/cmacc_dm{d}", properties="CONFIG.c_m_axi_s2mm_data_width.VALUE_SRC USER CONFIG.c_s_axis_s2mm_tdata_width.VALUE_SRC USER\n")
                set_property(f, name=f"hedgehog/cmacc_dm{d}", 
                                 properties="CONFIG.c_include_mm2s {Omit} "
                                            "CONFIG.c_include_mm2s_stsfifo {false} "
                                            f"CONFIG.c_m_axi_s2mm_data_width {{{self.config['CMACC_CAPTURE_PATH']['DATAMOVER_AXI_WIDTH'][d]}}} "
                                            f"CONFIG.c_s_axis_s2mm_tdata_width {{{self.config['CMACC_CAPTURE_PATH']['FIFO_OUTPUT_WIDTH'][d]}}} "
                                            "CONFIG.c_s2mm_btt_used {23} "
                                            f"CONFIG.c_s2mm_burst_size {{{self.config['CMACC_CAPTURE_PATH']['DATAMOVER_BURST_SIZE'][d]}}} "
                                            "CONFIG.c_s2mm_support_indet_btt {true} "
                                            "CONFIG.c_mm2s_include_sf {false} "
                                            "CONFIG.c_s2mm_include_sf {false} "
                                            "CONFIG.c_enable_cache_user {true} "
                                            "CONFIG.c_enable_mm2s {0} "
                                            "CONFIG.c_enable_s2mm_adv_sig {0} "
                                            "CONFIG.c_addr_width {40}")

                # Connect clocks and resets
                connect_bd_net(f, 
                               f"hedgehog/cmacc_dm{d}/m_axi_s2mm_aclk", 
                               "hedgehog/clk_wiz/" + self.config['CMACC_CAPTURE_PATH']['FIFO_OUTPUT_CLOCK'][d])
                connect_bd_net(f, 
                               f"hedgehog/cmacc_dm{d}/m_axi_s2mm_aresetn", 
                               f"hedgehog/proc_sys_reset_{self.config['CMACC_CAPTURE_PATH']['FIFO_OUTPUT_CLOCK'][d]}/peripheral_aresetn")
                connect_bd_net(f, 
                               f"hedgehog/cmacc_dm{d}/m_axis_s2mm_cmdsts_awclk", 
                               "hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, 
                               f"hedgehog/cmacc_dm{d}/m_axis_s2mm_cmdsts_aresetn", 
                               "hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the MM2S command and status interfaces to the bus-driven DataMover controller
                connect_bd_intf_net(f, 
                                    f"hedgehog/cmacc_dm{d}/S_AXIS_S2MM_CMD", 
                                    f"hedgehog/datamover_controller/cmacc_dm{d}_cmd")
                connect_bd_intf_net(f, 
                                    f"hedgehog/cmacc_dm{d}/M_AXIS_S2MM_STS", 
                                    f"hedgehog/datamover_controller/cmacc_dm{d}_sts")

                # Connect the error signal to the controller through a CDC
                create_ip(f, name=f"hedgehog/xpm_cdc_cmacc_dm{d}_err", vlnv="xilinx.com:ip:xpm_cdc_gen:1.0")
                set_property(f, name=f"hedgehog/xpm_cdc_cmacc_dm{d}_err", properties={"CDC_TYPE": "xpm_cdc_single"})
                connect_bd_net(f, f"hedgehog/xpm_cdc_cmacc_dm{d}_err/src_in", f"hedgehog/cmacc_dm{d}/s2mm_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_cmacc_dm{d}_err/dest_out", f"hedgehog/datamover_controller/cmacc_dm{d}_err")
                connect_bd_net(f, f"hedgehog/xpm_cdc_cmacc_dm{d}_err/dest_clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/xpm_cdc_cmacc_dm{d}_err/src_clk", "hedgehog/clk_wiz/" + self.config['CMACC_CAPTURE_PATH']['FIFO_OUTPUT_CLOCK'][d])
            
                # Connect the S2MM stream input to the output of the AXIS Data FIFO
                connect_bd_intf_net(f, f"hedgehog/cmacc_dm{d}/s_axis_s2mm", f"hedgehog/fifo_cmacc_dm{d}/M_AXIS")

                # Connect the S2MM AXI master to the bulk memory smartconnect
                connect_bd_intf_net(f, f"hedgehog/bulk_smartconnect/S{d+5:02d}_AXI", f"hedgehog/cmacc_dm{d}/M_AXI_S2MM")

                # Keep track of the address space for this DataMover
                bulk_memory_smartconnect_target_address_spaces.append(f"/hedgehog/cmacc_dm{d}/Data_S2MM")

            # ------------------- DAC channels -------------------- #

            for channel in range(self._num_dacs):
                tile = channel // 4
                block = channel % 4

                # Create a DMA for the DAC and connect it to the read port of the BRAM
                create_module(f, f"hedgehog/dac_dma{channel}", "acadia_dma")
                set_property(f, 
                             f"hedgehog/dac_dma{channel}", 
                             properties={
                                "ADDRESS_WIDTH": next_highest_power_of_2(self.config[f"DAC_TILE{tile}_SAMPLE_MEMORY"]["SIZE_BITS"] // self.config[f"RFDC"]["DAC"]["CHANNEL_INTERFACE_WIDTH"][channel], log=True),
                                "DESCRIPTOR_MEM_ADDR_WIDTH": next_highest_power_of_2(self.config["DAC_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 64, log=True)})
                connect_bd_intf_net(f, f"hedgehog/dac_dma{channel}/mem_control", f"hedgehog/dac_tile{tile}_memory/mem{block}")
                connect_bd_net(f, f"hedgehog/dac_dma{channel}/clk", f"hedgehog/clk_wiz/seq_clk")
                connect_bd_net(f, f"hedgehog/dac_dma{channel}/nrst", f"hedgehog/proc_sys_reset_seq_clk/peripheral_aresetn")

                # Connect the DAC memory output to the RFDAC interface through a pipeline
                create_module(f, f"hedgehog/dac{channel}_pipeline", "acadia_axis_pipeline")
                set_property(f, f"hedgehog/dac{channel}_pipeline", 
                             properties=f"WIDTH {{{self.config['RFDC']['DAC']['CHANNEL_INTERFACE_WIDTH'][channel]}}} "
                                        f"STAGES {{{self.config['RFDC']['DAC']['CHANNEL_PIPELINE_STAGES'][channel]}}}")
                
                connect_bd_net(f, f"hedgehog/dac{channel}_pipeline/clk", f"hedgehog/clk_wiz/" + self.config['RFDC']['DAC']['TILE_AXIS_CLOCKS'][tile])
                connect_bd_net(f, f"hedgehog/dac_tile{tile}_memory/mem{block}_dout", f"hedgehog/dac{channel}_pipeline/s_axis_tdata")
                connect_bd_intf_net(f, f"hedgehog/dac{channel}_pipeline/m_axis", f"hedgehog/rfdc/s{tile}{block}_axis")

                # Connect the DAC DMA to the registers
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/dac_dma{channel}_fifo_mosi", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_in")
                connect_bd_net(f, f"hedgehog/sequencer_bus_decoder/dac_dma{channel}_fifo_wr", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_wr")
                connect_bd_net(f, f"hedgehog/dma_trigger_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/trigger")
                connect_bd_net(f, f"hedgehog/dma_running_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/running")
                connect_bd_net(f, f"hedgehog/dma_fifo_empty_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_empty")
                connect_bd_net(f, f"hedgehog/dma_fifo_almost_empty_dataport/dac_dma{channel}", f"hedgehog/dac_dma{channel}/descriptor_address_fifo_almost_empty")
                
                # Connect DAC Descriptor BRAMs and to the DMA                
                connect_bd_intf_net(f, f"hedgehog/dac_dma_descriptor_memory/mem{channel}", f"hedgehog/dac_dma{channel}/DESCRIPTOR_MEM")

                # Connect the data input of the DMA to zeros in order to suppress the
                # critical warning vivado will generate
                create_ip(f, name=f"hedgehog/xlconst_dac_dma{channel}_din", vlnv="xilinx.com:ip:xlconstant:1.1")
                set_property(f, name=f"hedgehog/xlconst_dac_dma{channel}_din", properties={"CONST_WIDTH": 32, "CONST_VAL": 0})
                connect_bd_net(f, f"hedgehog/xlconst_dac_dma{channel}_din/dout", f"hedgehog/dac_dma{channel}/din")

            # ------------------- AXI Address Assignment -------------------- #
            
            # Paths through the bulk smartconnect
            for target_address_space in bulk_memory_smartconnect_target_address_spaces:
                # Make sure not to map the PS into itself
                segments = list(self.config["DDR4_MEMORY"].values())
                if "ps/Data" not in target_address_space:
                    segments += list(self.config["PS_MEMORY"].values())
                
                for properties in segments:
                    # Prevent the PS from mapping into itself
                    assign_bd_address(f, 
                                      target_address_space=target_address_space,
                                      offset=properties["ADDRESS"], 
                                      range=properties["SIZE_BITS"] // 8, 
                                      addr_seg=properties["SEGMENT"])
                
                # Exclude the QSPI
                for gp in range(4):
                    exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HPC0_QSPI")
                    exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HPC1_QSPI")
                    exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HP0_QSPI")
                    exclude_bd_addr_seg(f, target_address_space, f"/ps/SAXIGP{gp}/HP1_QSPI")

            # Exclude the PS segments from the PS address space
            for properties in self.config["PS_MEMORY"].values():
                exclude_bd_addr_seg(f, "/ps/Data", properties["SEGMENT"])

            for target_address_space in sequencer_memory_crossbar_target_address_spaces:
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    offset=self.config["SEQUENCER_CACHE_MEMORY"]["ADDRESS"], 
                    range=self.config["SEQUENCER_CACHE_MEMORY"]["SIZE_BITS"] // 8, 
                    addr_seg=f"hedgehog/cache_memory/" + self.config["SEQUENCER_CACHE_MEMORY"]["SEGMENT"])
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    offset=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["ADDRESS"], 
                    range=self.config["SEQUENCER_INSTRUCTION_MEMORY"]["SIZE_BITS"] // 8, 
                    addr_seg=f"hedgehog/instruction_memory/" + self.config["SEQUENCER_INSTRUCTION_MEMORY"]["SEGMENT"])
                    
            for target_address_space in config_smartconnect_target_address_spaces:
                for i in range(4):
                    assign_bd_address(f, 
                        target_address_space=target_address_space, 
                        offset=self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["ADDRESS"], 
                        range=4*self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["SIZE_BITS"] // 8, 
                        addr_seg=f"hedgehog/dac_tile{i}_memory/" + self.config[f"DAC_TILE{i}_SAMPLE_MEMORY"]["SEGMENT"])

                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    offset=self.config[f"CMACC_KERNEL_MEMORY"]["ADDRESS"], 
                    range=self._num_cmaccs*self.config[f"CMACC_KERNEL_MEMORY"]["SIZE_BITS"] // 8, 
                    addr_seg=f"hedgehog/cmacc_kernel_memory/" + self.config[f"CMACC_KERNEL_MEMORY"]["SEGMENT"])
                
                for t,count in [("DAC", self._num_dacs), 
                          ("ADC", self._num_adcs), 
                          ("CMACC", self._num_cmaccs)]:
                    assign_bd_address(f, 
                        target_address_space=target_address_space, 
                        offset=self.config[f"{t}_DMA_DESCRIPTOR_MEMORY"]["ADDRESS"], 
                        range=count*self.config[f"{t}_DMA_DESCRIPTOR_MEMORY"]["SIZE_BITS"] // 8, 
                        addr_seg=f"hedgehog/{t}_dma_descriptor_memory/" + self.config[f"{t}_DMA_DESCRIPTOR_MEMORY"]["SEGMENT"])
                
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    addr_seg="hedgehog/axis_switch_adc/" + self.config["ADC_AXIS_SWITCH"]["AXI_SEGMENT"], 
                    offset=self.config["ADC_AXIS_SWITCH"]["AXI_ADDRESS"], 
                    range=self.config["ADC_AXIS_SWITCH"]["AXI_SIZE_BITS"] // 8)
                
                assign_bd_address(f, 
                    target_address_space=target_address_space, 
                    addr_seg="hedgehog/rfdc/" + self.config["RFDC"]["AXI_SEGMENT"], 
                    offset=self.config["RFDC"]["AXI_ADDRESS"], 
                    range=self.config["RFDC"]["AXI_SIZE_BITS"] // 8)

DEFAULT_CONFIG = {
    "CLK104_PL_CLK": {
        "FREQ_HZ": 250_000_000
    },

    "CLK_8A34001_Q3_OUT": {
        "FREQ_HZ": 250_000_000
    },

    "PS_MEMORY": {
        "HPC0_LPS_OCM": {
            "ADDRESS": 0x00_FF00_0000, 
            "SIZE_BITS": 8 * 2**18, 
            "SEGMENT": "/ps/SAXIGP0/HPC0_LPS_OCM"
        },

        "HPC1_LPS_OCM": {
            "ADDRESS": 0x01_FF00_0000, 
            "SIZE_BITS": 8 * 2**18, 
            "SEGMENT": "/ps/SAXIGP1/HPC1_LPS_OCM"
        },

        "HP0_LPS_OCM": {
            "ADDRESS": 0x02_FF00_0000, 
            "SIZE_BITS": 8 * 2 * 2**18, 
            "SEGMENT": "/ps/SAXIGP2/HP0_LPS_OCM"
        },

        "HP1_LPS_OCM": {
            "ADDRESS": 0x03_FF00_0000, 
            "SIZE_BITS": 8 * 2**18, 
            "SEGMENT": "/ps/SAXIGP3/HP1_LPS_OCM"
        },

        "HPC0_DDR_LOW": {
            "ADDRESS": 0x04_0000_0000, 
            "SIZE_BITS": 8 * 2**31, 
            "SEGMENT": "/ps/SAXIGP0/HPC0_DDR_LOW"
        },

        "HPC1_DDR_LOW": {
            "ADDRESS": 0x05_0000_0000, 
            "SIZE_BITS": 8 * 2**31, 
            "SEGMENT": "/ps/SAXIGP1/HPC1_DDR_LOW"
        },

        "HP0_DDR_LOW": {
            "ADDRESS": 0x06_0000_0000, 
            "SIZE_BITS": 8 * 2**31, 
            "SEGMENT": "/ps/SAXIGP2/HP0_DDR_LOW"
        },

        "HP1_DDR_LOW": {
            "ADDRESS": 0x07_0000_0000, 
            "SIZE_BITS": 8 * 2**31, 
            "SEGMENT": "/ps/SAXIGP3/HP1_DDR_LOW"
        },

        "HPC0_DDR_HIGH": {
            "ADDRESS": 0x08_0000_0000, 
            "SIZE_BITS": 8 * 2**35, 
            "SEGMENT": "/ps/SAXIGP0/HPC0_DDR_HIGH"
        },

        "HPC1_DDR_HIGH": {
            "ADDRESS": 0x18_0000_0000, 
            "SIZE_BITS": 8 * 2**35, 
            "SEGMENT": "/ps/SAXIGP1/HPC1_DDR_HIGH"
        },

        "HP0_DDR_HIGH": {
            "ADDRESS": 0x28_0000_0000, 
            "SIZE_BITS": 8 * 2**35, 
            "SEGMENT": "/ps/SAXIGP2/HP0_DDR_HIGH"
        },

        "HP1_DDR_HIGH": {
            "ADDRESS": 0x38_0000_0000, 
            "SIZE_BITS": 8 * 2**35, 
            "SEGMENT": "/ps/SAXIGP3/HP1_DDR_HIGH"
        },
    },

    "DDR4_MEMORY": {
        "DDR4_C0": {
            "ADDRESS": 0x40_0000_0000, 
            "SIZE_BITS": 8 * 2**32, 
            "SEGMENT": "DDR4_C0_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK"
        },

        "DDR4_C1": {
            "ADDRESS": 0x41_0000_0000, 
            "SIZE_BITS": 8 * 2**32, 
            "SEGMENT": "DDR4_C1_MIG/C0_DDR4_MEMORY_MAP/C0_DDR4_ADDRESS_BLOCK"
        },
    },

    "CONFIG_SMARTCONNECT": {
        "CLOCKS": ["seq_clk", "hs_clk"]
    },

    "SEQUENCER_MEMORY_CROSSBAR": {
        "CLOCK": "hs_clk"
    },

    "PS_AXI_CLOCKS": {
        "PS_MAXIHPM0_FPD": "hs_clk",
        "PS_MAXIHPM1_FPD": "hs_clk",
        "PS_MAXIHPM0_LPD": "hs_clk",
        "PS_SAXIHPC0_FPD": "hs_clk",
        "PS_SAXIHP0_FPD": "hs_clk",
        "PS_SAXIHPC1_FPD": "hs_clk",
        "PS_SAXIHP1_FPD": "hs_clk"
    },

    "SEQUENCER_CACHE_MEMORY": {
        "PRIMITIVE": "block",
        "ADDRESS": 0x00_B000_0000, 
        "SEGMENT": "s_axi/reg0",

        "SIZE_BITS": 2**20,
        "BUS_PIPELINE": False,
        "SYNCHRONOUS": False,
        "CONTROLLER_WIDTH": 128,
        "CONTROLLER_PORT_INPUT_PIPELINE": 0,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 1,
        "BUS_PORT_INPUT_PIPELINE": 0,
        "BUS_PORT_OUTPUT_PIPELINE": 1
    },

    "SEQUENCER_INSTRUCTION_MEMORY": {
        "PRIMITIVE": "block",
        "ADDRESS": 0x00_B100_0000, 
        "SEGMENT": "s_axi/reg0",

        "SIZE_BITS": 128*4096,
        "BUS_PIPELINE": False,
        "SYNCHRONOUS": False,
        "CONTROLLER_WIDTH": 128,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 0,
        "BUS_PORT_OUTPUT_PIPELINE": 0
    },

    "DAC_TILE0_SAMPLE_MEMORY": {
        "PRIMITIVE": "ultra",
        "INTERFACE_WIDTH": 128,
        "CONTROLLER_WIDTH": 128,
        "ADDRESS": 0x00_8800_0000,
        "SIZE_BITS": 2**20,
        "SEGMENT": "s_axi/reg0",
        "SYNCHRONOUS": True,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 1,
        "BUS_PORT_OUTPUT_PIPELINE": 2
    },

    "DAC_TILE1_SAMPLE_MEMORY": {
        "PRIMITIVE": "ultra",
        "INTERFACE_WIDTH": 128,
        "CONTROLLER_WIDTH": 128,
        "ADDRESS": 0x00_8808_0000,
        "SIZE_BITS": 2**20,
        "SEGMENT": "s_axi/reg0",
        "SYNCHRONOUS": True,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 1,
        "BUS_PORT_OUTPUT_PIPELINE": 2
    },

    "DAC_TILE2_SAMPLE_MEMORY": {
        "PRIMITIVE": "ultra",
        "INTERFACE_WIDTH": 128,
        "CONTROLLER_WIDTH": 128,
        "ADDRESS": 0x00_8810_0000,
        "SIZE_BITS": 2**20,
        "SEGMENT": "s_axi/reg0",
        "SYNCHRONOUS": True,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 1,
        "BUS_PORT_OUTPUT_PIPELINE": 2
    },

    "DAC_TILE3_SAMPLE_MEMORY": {
        "PRIMITIVE": "ultra",
        "INTERFACE_WIDTH": 128,
        "CONTROLLER_WIDTH": 128,
        "ADDRESS": 0x00_8818_0000,
        "SIZE_BITS": 2**20,
        "SEGMENT": "s_axi/reg0",
        "SYNCHRONOUS": True,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 1,
        "BUS_PORT_OUTPUT_PIPELINE": 2
    },

    "CMACC_KERNEL_MEMORY": {
        "PRIMITIVE": "block",
        "ADDRESS": 0x00_8600_0000, 
        "SIZE_BITS": 2048*32,
        "SEGMENT": "s_axi/reg0",
        "SYNCHRONOUS": True,
        "CONTROLLER_WIDTH": 32,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 0,
        "BUS_PORT_OUTPUT_PIPELINE": 1
    },

    "DAC_DMA_DESCRIPTOR_MEMORY": {
        "PRIMITIVE": "block",
        "ADDRESS": 0x00_8300_0000, 
        "SIZE_BITS": 1024*64,
        "SEGMENT": "s_axi/reg0",
        "SYNCHRONOUS": True,
        "CONTROLLER_WIDTH": 64,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 0,
        "BUS_PORT_OUTPUT_PIPELINE": 2
    },
        
    "ADC_DMA_DESCRIPTOR_MEMORY": {
        "PRIMITIVE": "block",
        "ADDRESS": 0x00_8400_0000, 
        "SIZE_BITS": 1024*64,
        "SEGMENT": "s_axi/reg0",
        "SYNCHRONOUS": True,
        "CONTROLLER_WIDTH": 64,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 0,
        "BUS_PORT_OUTPUT_PIPELINE": 2
    },

    "CMACC_DMA_DESCRIPTOR_MEMORY": {
        "PRIMITIVE": "block",
        "ADDRESS": 0x00_8500_0000, 
        "SIZE_BITS": 1024*64,
        "SEGMENT": "s_axi/reg0",
        "SYNCHRONOUS": True,
        "CONTROLLER_WIDTH": 64,
        "CONTROLLER_PORT_INPUT_PIPELINE": 1,
        "CONTROLLER_PORT_OUTPUT_PIPELINE": 2,
        "BUS_PORT_INPUT_PIPELINE": 0,
        "BUS_PORT_OUTPUT_PIPELINE": 2
    },  
    
    # Configuration for the input to the clocking wizard
    "CLK_WIZ": {
        # "ADDRESS": 0x00_8100_0000, 
        # "SIZE_BITS": 8 * 2**18,
        # "SEGMENT": "s_axi_lite/Reg",

        "INPUT_FREQ_HZ": 250_000_000,
        "INPUT_JITTER_PS": 40.0,
        "INPUT_SOURCE_TYPE": "Global_buffer",
        "MMCM_CLKFBOUT_MULT_F": 5.0,

        "GENERATED_CLOCKS": {
            "seq_clk": 250_000_000,
            "dac_clk": 250_000_000,
            "dac_tile3_clk": 250_000_000,
            "adc_clk": 250_000_000,
            "adc_tile3_clk": 250_000_000,
            "hs_clk": 333_333_333
        },
    },    

    "ADC_AXIS_SWITCH": {
        "AXI_ADDRESS": 0x00_8200_0000, 
        "AXI_SIZE_BITS": 8 * 2**18,
        "AXI_SEGMENT": "S_AXI_CTRL/Reg",
        "WIDTH": 128
    },

    "RFDC": {
        # Is the AXI config port of the RFDC synchronous to the sequencer?
        "AXI_SYNCHRONOUS": True,

        # If AXI_SYNCHRONOUS is True then this must be the sequencer clock frequency
        "AXI_CLK_FREQ_HZ": 250e6,
        
        "AXI_ADDRESS": 0x00_8000_0000, 
        "AXI_SIZE_BITS": 8 * 2**18,
        "AXI_SEGMENT": "s_axi/Reg",

        "DAC": {
            "CHANNEL_INTERFACE_WIDTH": [128]*16,
            "CHANNEL_PIPELINE_STAGES": [1]*16,
            "CHANNEL_NYQUIST_ZONE": [1]*16,
            "TILE_AXIS_CLOCKS": ["dac_clk", "dac_clk", "dac_clk", "dac_tile3_clk"],
            "TILE_MTS": [True]*4,
            "TILE_SAMPLE_RATE_HZ": [6e9]*4,
            "TILE_PLL": [True]*4,
            "TILE_CLK_SOURCE": [6]*4,
            "TILE_REFCLK_FREQ_HZ": [250e6]*4,
            "TILE_DISTRIBUTE_CLK": [0, 0, 1, 0],
            "TILE_VOP": [20.0]*4,
        },

        "ADC": {
            "CHANNEL_INTERFACE_WIDTH": [128]*16,
            "CHANNEL_PIPELINE_STAGES": [1]*16,
            "CHANNEL_DITHER": [False]*16,
            "TILE_AXIS_CLOCKS": ["adc_clk", "adc_clk", "adc_clk", "adc_tile3_clk"],
            "TILE_MTS": [True]*4,
            "TILE_SAMPLE_RATE_HZ": [2e9]*4,
            "TILE_PLL": [True]*4,
            "TILE_CLK_SOURCE": [2]*4,
            "TILE_REFCLK_FREQ_HZ": [250e6]*4,
            "TILE_DISTRIBUTE_CLK": [0, 0, 1, 0],
            "TILE_DSA": [0]*4
        }    
    },

    "PS_GPIO3": {
        "WIDTH": 32,
        "PIPELINE": 2,
        "BUS_PIPELINE": 1
    },

    "PS_GPIO4": {
        "WIDTH": 32,
        "PIPELINE": 2,
        "BUS_PIPELINE": 1
    },

    "PS_GPIO5": {
        "WIDTH": 16,
        "PIPELINE": 2,
        "BUS_PIPELINE": 1
    },

    "PS_IRQ": {
        "IRQ_PIPELINE": 2,
        "GDMA_PIPELINE": 2,
        "BUS_PIPELINE": True
    },

    "ADC_CAPTURE_PATH": {
        "FIFO_INPUT_CLOCK": ["seq_clk"]*4,
        "FIFO_OUTPUT_CLOCK": ["hs_clk"]*4,
        "FIFO_INPUT_WIDTH": [128]*4,
        "FIFO_OUTPUT_WIDTH": [128]*4,
        "FIFO_INPUT_PIPELINE": [0]*4,
        "FIFO_DEPTH": [1024]*4,
        "FIFO_PRIMITIVE": ["auto"]*4,
        "FIFO_ASYNCHRONOUS": [True]*4,
        "MONITOR_SYNCHRONOUS": [True]*4,
        "DATAMOVER_AXI_WIDTH": [128]*4,
        "DATAMOVER_BURST_SIZE": [256]*4
    },

    "CMACC_CAPTURE_PATH": {
        "CMACC_INPUT_PIPELINE": [1]*4,
        "FIFO_INPUT_CLOCK": ["seq_clk"]*4,
        "FIFO_OUTPUT_CLOCK": ["hs_clk"]*4,
        "FIFO_OUTPUT_WIDTH": [32]*4,
        "FIFO_INPUT_PIPELINE": [0]*4,
        "FIFO_DEPTH": [1024]*4,
        "FIFO_PRIMITIVE": ["auto"]*4,
        "FIFO_ASYNCHRONOUS": [True]*4,
        "MONITOR_SYNCHRONOUS": [True]*4,
        "DATAMOVER_AXI_WIDTH": [32]*4,
        "DATAMOVER_BURST_SIZE": [256]*4
    },

    "PS_GPIO": {
        "SYSFS_OFFSET": 338 + 3*26,
        "SEQUENCER_RUN": 90,
        "SEQUENCER_NRST": 89, # The GPIO bit connected to the sequencer run synchronizer
        "CLK104_SYNC": 88,
        "CLK104_SPI1": 87,
        "CLK104_SPI0": 86,
        "DDR4_C0_SYS_RST": 85,
        "DDR4_C1_SYS_RST": 84,
        "CLK_WIZ_LOCKED": 82,
        "DDR4_C0_CAL_CPLT": 81,
        "DDR4_C1_CAL_CPLT": 80,
        "SEQUENCER_BUS3": 0,
        "SEQUENCER_BUS4": 32,
        "SEQUENCER_BUS5": 64
    },

    "DATAMOVERS": {
        "cfg_axi_dm": {
            "CMDSTS_CLOCK": "seq_clk",
            "AXI_CLOCK": "hs_clk",

            "ENABLE_MM2S": True,
            "MM2S_AXI": "config_smartconnect",
            "MM2S_AXI_WIDTH": 128,
            "MM2S_AXIS_WIDTH": 128,

            "M_AXIS_MM2S": "cfg_axi_dm/S_AXIS_S2MM",

            "ENABLE_S2MM": True,
            "S2MM_AXI": "sequencer_memory_crossbar",
            "S2MM_AXI_WIDTH": 128,
            "S2MM_AXIS_WIDTH": 128,
        }
    },

    "SEQUENCER_BUS": {
        "DECODER_PIPELINE_MISO": True,

        "DMA_FIFO_DATAPORT_PIPELINE": [False]*(16 + 4 + 4),

        "DMA_FIFO_EMPTY_DATAPORT": {
            "BUS_PIPELINE": True,
            "PIPELINE": [1]*(16 + 4 + 4),
        },

        "DMA_FIFO_ALMOST_EMPTY_DATAPORT": {
            "BUS_PIPELINE": True,
            "PIPELINE": [1]*(16 + 4 + 4),
        },

        "DMA_RUNNING_DATAPORT": {
            "BUS_PIPELINE": True,
            "PIPELINE": [1]*(16 + 4 + 4),
        },

        "DMA_TRIGGER_DATAPORT": {
            "BUS_PIPELINE": False,
            "PIPELINE": [0]*(16 + 4 + 4),
        },

        "ADC_FIFO_DATAPORT": {
            "BUS_PIPELINE": True,
            "ADC_OVERFLOW_PIPELINE": [1]*4,
            "ADC_MISALIGNMENT_PIPELINE": [1]*4,
            "ADC_RESET_PIPELINE": [1]*4,
            "CMACC_OVERFLOW_PIPELINE": [1]*4,
            "CMACC_MISALIGNMENT_PIPELINE": [1]*4,
            "CMACC_RESET_PIPELINE": [1]*4,
        },

        "CMACC_DATAPORTS": {
            "DATAPORT_RE_BUS_PIPELINE": [True]*4,
            "DATAPORT_IM_BUS_PIPELINE": [True]*4,
            "ACCUMULATOR_RE_PIPELINE": [1]*4,
            "ACCUMULATOR_IM_PIPELINE": [1]*4,
            "OFFSET_RE_PIPELINE": [1]*4,
            "OFFSET_IM_PIPELINE": [1]*4,
        },

        "CMACC_RESET_DATAPORT": {
            "BUS_PIPELINE": True,
            "PIPELINE": [1]*4
        },

        "CMACC_STATUS_DATAPORT": {
            "BUS_PIPELINE": False,
            "VALID_PIPELINE": [1]*4,
            "LAST_PIPELINE": [1]*4,
            "RE_MSB_PIPELINE": [1]*4,
            "IM_MSB_PIPELINE": [1]*4
        },

        "RFDC_RTS": {
            "BUS_PIPELINE": True,
            "NCO_CLK": "seq_clk"
        },

        "ZDMA_CONTROLLER": {
            "BUS_PIPELINE": True
        },

        "DATAMOVER_CONTROLLER": {
            "BUS_PIPELINE": True
        },

        "CLK104_SYNC_DATAPORT": {
            "BUS_PIPELINE": True,
            "PIPELINE": 2
        }
    }

}