__all__ = ["RFClk", "PSGPIO", "ZDMA", "AXISSwitch", "get_gpio_base"]

import re
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .compiler import Processor
from .sequencer import Sequencer

try:
    import pyxrfclk as xrfclk
except ImportError as e:
    print(e)
    
_DMESG_GPIO_PATTERN = "gpio@(?P<axi_address>[0-9]+)[:,\ a-z]+(?P<gpio_num>[0-9]+)"
    
def get_gpio_base(axi_address):
    """
    Get the base sysfs GPIO number for a GPIO controller on the AXI network.
    """
    with open("/var/log/dmesg") as f:
        dmesg = f.read()

    gpio_matches = re.finditer(_DMESG_GPIO_PATTERN, dmesg)
    if not gpio_matches:
        raise ValueError("No GPIO found in dmesg output.")

    for match in gpio_matches:
        if int(match["axi_address"], 16) == axi_address:
            return int(match["gpio_num"])

    raise ValueError("Unable to extract GPIO base.")

class RFClk:
    """
    A wrapper for the Xilinx XRFClk driver.
    """    
    @staticmethod
    def call(name, *args, **kwargs):
        if getattr(xrfclk.lib, f"XRFClk_{name}")(*args, **kwargs) != xrfclk.lib.XST_SUCCESS:
            raise ValueError(f"Call to {name} failed.")
        
    @classmethod
    def init(cls, gpio):
        """
        Initialize the xrfclk driver.
        :param gpio: The GPIO ID of the SPI mux on the CLK104
        :type gpio: int
        """
        RFClk.call("Init", gpio)
        
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
    PSGPIO3_IN_PSREG = 0x6C
    PSGPIO3_OUT_PSREG = 0x4C
    PSGPIO3_DIR_PSREG = 0x2C4
    PSGPIO4_IN_PSREG = PSGPIO3_IN_PSREG + 1
    PSGPIO4_OUT_PSREG = PSGPIO3_OUT_PSREG + 1
    PSGPIO4_DIR_PSREG = PSGPIO3_DIR_PSREG + 1

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
    fci_bus_address: "Sddress for the FCI controller on the sequencer's bus" = None
    
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
        if self.fci_buffer_usage == 32:
            pass
        elif self.fci_buffer_usage == 64:
            ch_fci_value |= 1 << 2
        elif self.fci_buffer_usage == 128:
            ch_fci_value |= 2 << 2
        elif self.fci_buffer_usage == 256:
            ch_fci_value |= 3 << 2
        else:
            raise ValueError(f"Invalid buffer usage {self.fci_buffer_usage}.")
        
        # bit 1: 0 = control the read side, 1 = control the write side
        if self.fci_side == "read":
            pass
        elif self.fci_side == "write":
            ch_fci_value |= 1 << 1
        else:
            raise ValueError(f"Invalid FCI side {self.fci_side}.")
        # bit 0: enable FCI
        ch_fci_value |= self.fci_enable
        
        self._regs[ZDMA.CH_FCI] = ch_fci_value.to_bytes(4, "little")
        
        # Source and destination
        self._regs[ZDMA.CH_SRC_START_LSB] = self.src.to_bytes(8, "little")
        self._regs[ZDMA.CH_DST_START_LSB] = self.dst.to_bytes(8, "little")
        
        # Write the size to the source and destination registers
        self._regs[ZDMA.CH_SRC_DSCR_WORD0+8] = self.size.to_bytes(4, "little")
        self._regs[ZDMA.CH_DST_DSCR_WORD0+8] = self.size.to_bytes(4, "little")
        
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
            return proc.bus_write(address=self.fci_bus_address,
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
            return proc.bus_read(self.bus_address + self.channel)
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
            return proc.bus_read(self.bus_address + 32 + self.channel)
        else:
            raise ValueError(f"Unable to query completion from processor {proc}.")    
            
    def clear_fci_counters(self):
        """
        Clear the counters for managing the FCI in the ZDMA controller.
        """
        proc = Processor.active_processor()
        if isinstance(proc, Sequencer):
            # Clear credit acknowledgement counter
            proc.bus_write(address=self.bus_address + 1,
                           data=(1 << self.channel))
            
            # Clear transaction valid counter
            proc.bus_write(address=self.bus_address + 2,
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