__all__ = ["RFClk", "PSGPIO", "ZDMA", "AXISSwitch", "get_gpio_base"]

import re
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .compiler import Processor
from .sequencer import Sequencer

import acadia.rfclk as rfclk
    
_DMESG_GPIO_PATTERN = "gpio@(?P<axi_address>[0-9]+)[:,\\ a-z]+(?P<gpio_num>[0-9]+)"
    
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
        
    @classmethod
    def init(cls, gpio):
        """
        Initialize the xrfclk driver.

        :param gpio: The GPIO ID of the SPI mux on the CLK104
        :type gpio: int
        """

        rfclk.init(gpio)
        
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
            rfclk.reset_chip(cls.chip_id())
            
        @classmethod
        def set_config(cls, config_id=1):
            """
            Set a configuration present in the driver on the chip.
            """
            rfclk.set_config_on_one_chip_from_config_id(cls.chip_id(), config_id)
            
        @classmethod
        def read_reg(cls, address):
            """
            Read a register on the chip.
            """
            return rfclk.read_reg(cls.chip_id(), address)
        
        @classmethod
        def write_reg(cls, address, data):
            """
            Write a register on the chip.
            """
            rfclk.write_reg(cls.chip_id(), address, data)
        
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
            return rfclk.CHIP_ID_LMK
        
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
            cls.write_reg(address+1, data & mask & 0xFF)
        
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
        
        @staticmethod
        def get_output_base(output):
            """
            Returns the base register for the settings for a given
            output and its corresponding SDCLK output. Provided
            output should be even-numbered.
            """

            if output % 2 != 0:
                raise ValueError("Must set `output` to an even-numbered channel"
                                 f" (received {output}).")
            return 0x100 + 8*(output // 2)
        
        @classmethod
        def set_output_drive_level_increased(cls, output, en):
            """
            Sets the CLKout_X_Y_ODL field.
            """

            addr = cls.get_output_base(output)
            reg = cls.read_reg(addr)
            if en:
                reg |= (1 << 6)
            else:
                reg &= ~(1 << 6)
            cls.write_reg(addr, reg)

        @classmethod
        def get_output_drive_level_increased(cls, output):
            addr = cls.get_output_base(output)
            reg = cls.read_reg(addr)
            return bool(reg & (1 << 6))
        
        @classmethod
        def set_input_drive_level_increased(cls, output, en):
            """
            Sets the CLKout_X_Y_IDL field.
            """

            addr = cls.get_output_base(output)
            reg = cls.read_reg(addr)
            if en:
                reg |= (1 << 5)
            else:
                reg &= ~(1 << 5)
            cls.write_reg(addr, reg)

        @classmethod
        def get_input_drive_level_increased(cls, output):
            addr = cls.get_output_base(output)
            reg = cls.read_reg(addr)
            return bool(reg & (1 << 5))
        
        @classmethod
        def set_output_divider(cls, output, div):
            """
            Set the value of an output divider on a DCLK output.
            """

            addr = cls.get_output_base(output)
            reg = cls.read_reg(addr)
            reg &= ~0x1F # Clear the bits associated with the field
            if div != 32:
                reg |= div & 0x1F
            cls.write_reg(addr, reg)
            
        @classmethod
        def get_output_divider(cls, output):
            """
            Set the value of an output divider on a DCLK output.
            """

            addr = cls.get_output_base(output)
            reg = cls.read_reg(addr) & 0x1F
            if reg == 0:
                return 32
            return reg
        
        @classmethod
        def set_output_digital_delay(cls, output, count_high, count_low):
            """
            Sets the number of cycles the output is high and low by programming
            the DCLKOUTx_DDLY_CNTH/L registers.
            """

            reg = 0
            if count_high != 16:
                reg |= count_high << 4
            if count_low != 16:
                reg |= count_low
            cls.write_reg(cls.get_output_base(output)+1, reg)

        @classmethod
        def get_output_digital_delay(cls, output):
            reg = cls.read_reg(cls.get_output_base(output)+1)
            cnth = (reg >> 4) & 0xF
            cntl = reg & 0xF
            return ((16 if cntl == 0 else cntl), (16 if cnth == 0 else cnth))
        
        @classmethod
        def set_output_analog_delay(cls, output, delay):
            """
            Configures the analog delay for an output by setting DCLKOUTx_ADLY
            and DCLKOUTx_ADLY_PD. Set ``delay`` to 0 to disable the delay and
            power down the circuitry; otherwise the delay (in ps) must be
            ``500 + k*25``\\, where ``1 <= k <= 23``\\.
            """

            # Power the analog delay up or down depending on the arguments
            pd_addr = cls.get_output_base(output) + 6
            pd_reg = cls.read_reg(pd_addr)
            
            if delay == 0:
                pd_reg |= 1 << 4
            else:
                pd_reg &= ~(1 << 4)
            
            cls.write_reg(pd_addr, pd_reg)

            if ((delay > 1075 or delay < 500) and (delay != 0)) or (delay % 25 != 0):
                raise ValueError(f"Invalid delay value {delay}.")
            
            dly_addr = cls.get_output_base(output) + 3
            dly_reg = cls.read_reg(dly_addr)
            dly_reg &= ~(0x1F << 3)
            dly_reg |= ((delay - 500) // 25) << 3
            cls.write_reg(dly_addr, dly_reg)

        @classmethod
        def get_output_analog_delay(cls, output):
            pd_addr = cls.get_output_base(output) + 6
            pd_reg = cls.read_reg(pd_addr)

            if pd_reg & (1 << 4):
                return 0
            
            dly_addr = cls.get_output_base(output) + 3
            dly_reg = cls.read_reg(dly_addr)
            return ((dly_reg >> 3) & 0x1F)*25 + 500
        
        @classmethod
        def set_output_mux(cls, output, mux):
            """
            Multiplexes a particular output by setting the DCLKOUTx_MUX and 
            DCLKOUTx_ADLY_MUX registers. Note that the output divider must not
            be 1 when ``mux`` is 0; ``mux`` should be set to 1 or 7 when the 
            divider is 1. Valid values are:

            - ``mux=0``: Divider only
            - ``mux=1``: Divider with duty cycle correction and half-step
            - ``mux=2``: Bypass divider
            - ``mux=3``: Analog delay + divider without duty cycle correction or half-step
            - ``mux=7``: Analog delay + divider with duty cycle correction and half-step
            """      

            addr = cls.get_output_base(output) + 3
            reg = cls.read_reg(addr)
            reg &= ~0x7
            reg |= mux
            cls.write_reg(addr, mux)

        @classmethod
        def get_output_mux(cls, output):
            return cls.read_reg(cls.get_output_base(output) + 3) & 0x7
        
        @classmethod
        def set_sdclk_mux(cls, output, mux):
            """
            Sets the input to the SDCLK outputs. Valid values are:

            - ``mux=0``: Device clock output
            - ``mux=1``: SYSREF output
            """

            addr = cls.get_output_base(output-1) + 4
            reg = cls.read_reg(addr)
            if mux:
                reg |= (1 << 5)
            else:
                reg &= ~(1 << 5)
            cls.write_reg(addr, reg)

        @classmethod
        def get_sdclk_mux(cls, output):
            return bool(cls.read_reg(cls.get_output_base(output-1) + 4) & (1 << 5))
        
        @classmethod
        def set_sdclk_digital_delay(cls, output, delay):
            """
            Sets the digital delay of an SDCLK output in units of VCO cycles. 
            Valid values are 0 or 2-11 inclusive.
            """

            addr = cls.get_output_base(output-1) + 4
            reg = cls.read_reg(addr)
            reg &= ~(0xF << 1)
            if delay != 0:
                reg |= (delay-1) << 1
           
            cls.write_reg(addr, reg)

        @classmethod
        def get_sdclk_digital_delay(cls, output):
            addr = cls.get_output_base(output-1) + 4
            reg = cls.read_reg(addr)
            dly = (reg >> 1) & 0xF
            return (0 if dly == 0 else dly+1)

        @classmethod
        def set_sdclk_analog_delay(cls, output, delay, enable=True):
            """
            Enable/disable and set value of analog delay.
            Valid values of ``delay`` (in units of ps) are 0, 600, 750, 900,
            1050, 1200, 1350, 1500, 1650, 1800, 1950, 2100, or 2250.
            """

            reg = 0
            reg |= (enable << 4)
            
            got_delay = False
            for i,d in enumerate([0,600,750,900,1050,1200,1350,1500,1650,1800,1950,2100,2250]):
                if delay == d:
                    reg |= i
                    got_delay = True
                    break
            if not got_delay:
                raise ValueError(f"Invalid analog delay value {delay}.")

            cls.write_reg(cls.get_output_base(output-1) + 5, reg)

        @classmethod
        def get_sdclk_analog_delay(cls, output):
            reg = cls.read_reg(cls.get_output_base(output-1) + 5)
            for i,d in enumerate([0,600,750,900,1050,1200,1350,1500,1650,1800,1950,2100,2250]):
                if reg & 0xF == i:
                    return d
                
            raise ValueError(f"Read invalid analog delay value (reg contains {reg}).")

        @classmethod
        def get_sdclk_analog_delay_enabled(cls, output):
            reg = cls.read_reg(cls.get_output_base(output-1) + 5)
            return bool(reg & (1 << 4))
        
        @classmethod
        def set_output_powerdown_state(cls, 
                                       output,
                                       disable_output=False, 
                                       disable_digital_delay=False, 
                                       disable_glitchless_halfstep=True,
                                       disable_analog_delay_glitchless=True,
                                       disable_analog_delay=True,
                                       disable_sdclk=False):
            """
            Set the power state of various elements on the output path of a 
            given output and its corresponding SDCLK output.
            """

            reg = 0
            reg |= disable_digital_delay << 7
            reg |= disable_glitchless_halfstep << 6
            reg |= disable_analog_delay_glitchless << 5
            reg |= disable_analog_delay << 4
            reg |= disable_output << 3
            reg |= disable_sdclk << 0
            cls.write_reg(cls.get_output_base(output) + 6, reg)

        @classmethod
        def get_output_powerdown_state(cls, output):
            return cls.read_reg(cls.get_output_base(output) + 6)
        
        @staticmethod
        def drive_to_string(drive):
            """
            Get the name of a drive standard from its register bits.
            """

            tmp = None
            if drive & 7 == 0:
                tmp = "Power down"
            elif drive & 7 == 1:
                tmp = "LVDS"
            elif drive & 7 == 2:
                tmp = "HSDS 6 mA"
            elif drive & 7 == 3:
                tmp = "HSDS 8 mA"
            elif drive & 7 == 4:
                tmp = "HSDS 10 mA"
            elif drive & 7 == 5:
                tmp = "LVPECL 1600 mV"
            elif drive & 7 == 6:
                tmp = "LVPECL 2000 mV"
            elif drive & 7 == 7:
                tmp = "LCPECL"

            if drive & 8:
                tmp += ", inverted"

            return tmp
        
        @classmethod
        def set_drive(cls, output, drive):
            """
            Sets the output voltage format and inverter settings for a 
            given output or SDCLK output. Valid values are:

            - ``drive=0``: Power down
            - ``drive=1``: LVDS
            - ``drive=2``: HSDS 6 mA
            - ``drive=3``: HSDS 8 mA
            - ``drive=4``: HSDS 10 mA
            - ``drive=5``: LVPECL 1600 mV
            - ``drive=6``: LVPECL 2000 mV
            - ``drive=7``: LCPECL
            - ``drive=9``: LVDS, inverted
            - ``drive=10``: HSDS 6 mA, inverted
            - ``drive=11``: HSDS 8 mA, inverted
            - ``drive=12``: HSDS 10 mA, inverted
            - ``drive=13``: LVPECL 1600 mV, inverted
            - ``drive=14``: LVPECL 2000 mV, inverted
            - ``drive=15``: LCPECL, inverted
            """

            addr = cls.get_output_base(output - (output % 2)) + 7
            reg = cls.read_reg(addr)
            if output % 2 == 0:
                reg &= ~0xF
                reg |= drive
            else:
                reg &= ~(0xF << 4)
                reg |= drive << 4
            cls.write_reg(addr, reg)

        @classmethod
        def get_drive(cls, output):
            addr = cls.get_output_base(output - (output % 2)) + 7
            reg = cls.read_reg(addr)
            if output % 2 == 1:
                return (reg >> 4) & 0xF
            return reg & 0xF

        @classmethod
        def set_sysref_global_power_state(cls, powerdown):
            """
            Controls the SYSREF_GBL_PD bit.
            """

            reg140 = cls.read_reg(0x140)
            if powerdown:
                reg140 |= (1 << 3)
            else:
                reg140 &= ~(1 << 3)
            cls.write_reg(0x140, reg140)

        @classmethod
        def get_sysref_global_power_state(cls):
            return bool(cls.read_reg(0x140) & (1 << 3))
        
        @classmethod
        def set_sysref_power_state(cls, powerdown):
            """
            Controls the SYSREF_PD bit.
            """

            reg140 = cls.read_reg(0x140)
            if powerdown:
                reg140 |= (1 << 2)
            else:
                reg140 &= ~(1 << 2)
            cls.write_reg(0x140, reg140)

        @classmethod
        def get_sysref_power_state(cls):
            return bool(cls.read_reg(0x140) & (1 << 2))
        
        @classmethod
        def set_sysref_digital_delay_power_state(cls, powerdown):
            """
            Controls the SYSREF_DDLY_PD bit.
            """

            reg140 = cls.read_reg(0x140)
            if powerdown:
                reg140 |= (1 << 1)
            else:
                reg140 &= ~(1 << 1)
            cls.write_reg(0x140, reg140)
        
        @classmethod
        def get_sysref_digital_delay_power_state(cls):
            return bool(cls.read_reg(0x140) & (1 << 1))
        
        @classmethod
        def set_sysref_pulser_power_state(cls, powerdown):
            """
            Controls the SYSREF_PLSR_PD bit.
            """

            reg140 = cls.read_reg(0x140)
            if powerdown:
                reg140 |= (1 << 0)
            else:
                reg140 &= ~(1 << 0)
            cls.write_reg(0x140, reg140)
        
        @classmethod
        def get_sysref_pulser_power_state(cls):
            return bool(cls.read_reg(0x140) & (1 << 0))
        
        @classmethod
        def set_sync_enabled(cls, state):
            """
            Controls the SYNC_EN bit.
            """

            reg143 = cls.read_reg(0x143)
            if state:
                reg143 |= (1 << 4)
            else:
                reg143 &= ~(1 << 4)
            cls.write_reg(0x143, reg143)

        @classmethod
        def get_sync_enabled(cls):
            """
            Determine whether the SYNC_EN bit is set.
            """

            return bool(cls.read_reg(0x143) & (1 << 4))

        @classmethod
        def set_sync_polarity(cls, invert):
            """
            Sets the SYNC polarity to non-inverted \\(``invert=False``\\) or 
            inverted \\(``invert=True``\\).
            """

            reg143 = cls.read_reg(0x143)
            if invert:
                reg143 |= (1 << 5)
            else:
                reg143 &= ~(1 << 5)
            cls.write_reg(0x143, reg143)

        @classmethod
        def get_sync_polarity(cls):
            """
            Determine whether the SYNC polarity is inverted or not.
            """

            return bool(cls.read_reg(0x143) & (1 << 5))
        
        @classmethod
        def set_sysref_clr(cls, clr):
            """
            Resets and arms the SDCLKoutY_DDLY path, allowing local digital 
            delays to take effect after a SYNC event
            """

            reg143 = cls.read_reg(0x143)
            if clr:
                reg143 |= (1 << 7)
            else:
                reg143 &= ~(1 << 7)
            cls.write_reg(0x143, reg143)

        @classmethod
        def get_sysref_clr(cls):
            """
            Determine whether the digital delay paths are armed for 
            synchronization.
            """

            return bool(cls.read_reg(0x143) & (1 << 7))
        
        @classmethod
        def set_sync_mode(cls, mode):
            """
            Sets the SYNC_MODE field. The behavior is:

            - ``mode=0``: SYNC and SYSREF disabled
            - ``mode=1``: SYNC generated by SYNC pin
            - ``mode=2``: SYNC generated by pulser upon transition of SYNC pin
            - ``mode=3``: SYNC generated by pulser when writing to the SYSREF pulse
                count register
            """

            reg143 = cls.read_reg(0x143)
            reg143 &= ~0x3 # Clear the existing setting
            reg143 |= (mode & 0x3)
            cls.write_reg(0x143, reg143)

        @classmethod
        def get_sync_mode(cls):
            """
            Reads the SYNC_MODE field.
            """

            return cls.read_reg(0x143) & 0x3

        @classmethod
        def set_sysref_pulse_count(cls, count):
            """
            Instructs the SYSREF pulser to generate the desired number of 
            pulses. Only values of 1, 2, 4, or 8 are allowed.
            """

            if count == 1:
                v = 0
            elif count == 2:
                v = 1
            elif count == 4:
                v = 2
            elif count == 8:
                v = 3
            else:
                raise ValueError("Only values of 1, 2, 4, or 8 are allowed for"
                                 f" SYSREF pulsing (received {count}).")

            cls.write_reg(0x13E, v)
        
        @classmethod
        def set_output_divider_synchronization_disable(cls, output, disable):
            """
            Sets or clears the SYNC_DIS bit for the provided output.
            """

            reg = cls.read_reg(0x144)
            if disable:
                reg |= (1 << (output // 2))
            else:
                reg &= ~(1 << (output // 2))
            cls.write_reg(0x144, reg)

        @classmethod
        def get_output_divider_synchronization_disable(cls, output):
            """
            Determines whether a particular output will be synchronized
            upon a SYNC event by checking the value of the SYNC_DIS bit.
            """

            return bool(cls.read_reg(0x144) & (1 << (output // 2)))
        
        @classmethod
        def set_sysref_divider_synchronization_disable(cls, disable):
            """
            Enable or disable synchronization of the SYSREF divider upon a
            SYNC event by setting or clearing the SYNC_DISSYSREF bit.
            """

            reg = cls.read_reg(0x144)
            if disable:
                reg |= (1 << 7)
            else:
                reg &= ~(1 << 7)
            cls.write_reg(0x144, reg)

        @classmethod
        def get_sysref_divider_synchronization_disable(cls):
            return bool(cls.read_reg(0x144) & (1 << 7))
        
        @classmethod
        def set_sysref_digital_delay(cls, delay):
            """
            Sets the SYSREF digital delay by programming the SYSREF_DDLY field.
            """

            if not isinstance(delay, int):
                raise TypeError("SYSREF delay must be an integer"
                                f" (received {delay}).")
            if delay < 8 or delay > 8191:
                raise ValueError("SYSREF digital delay must be between 8 and"
                                 f" 8191 inclusive (received {delay}).")
            cls.write_reg16(0x13C, delay, mask=0x1FFF)

        @classmethod
        def get_sysref_digital_delay(cls):
            return cls.read_reg16(0x13C) & 0x1FFF
        
        @classmethod
        def set_sysref_divider(cls, div):
            """
            Sets the SYSREF divider by programming the SYSREF_DIV field.
            """

            if not isinstance(div, int):
                raise TypeError("SYSREF divider value must be an integer"
                                f" (received {div}).")
            if div < 8 or div > 8191:
                raise ValueError("SYSREF divider value must be between 8 and"
                                 f" 8191 inclusive (received {div}).")
            cls.write_reg16(0x13A, div, mask=0x1FFF)

        @classmethod
        def get_sysref_divider(cls):
            return cls.read_reg16(0x13A) & 0x1FFF
        
        @classmethod
        def set_sysref_mux(cls, mux):
            """
            Multiplexes the signal driven on the SYNC/SYSREF path by setting
            the SYSREF_MUX and SYSREF_CLKin0_MUX fields. Valid options are:

            - ``mux=0``: Input from pin/SPI, re-clocked to distribution clock
            - ``mux=1``: Input from pin/SPI, re-clocked to SYSREF clock
            - ``mux=2``: SYSREF pulser
            - ``mux=3``: SYSREF continuous (directly driven by SYSREF clock)
            - ``mux=4``: CLKin0 direct
            """

            # No need to do read-then-write because these are the only bits in
            # the register
            cls.write_reg(0x139, mux)

        @classmethod
        def get_sysref_mux(cls):
            return cls.read_reg(0x139) & 0x7
        
    class LMX(RFClkChip):
        pass
        
    class LMX_ADC(LMX):
        @classmethod
        def chip_id(cls):
            return xrfclk.lib.RFCLK_LMX2594_1
        
    class LMX_DAC(LMX):
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

    @staticmethod
    def sysfs_read(gpio) -> bool:
        with open(f"/sys/class/gpio/gpio{gpio}/value", "r") as f:
            v = f.read()
        return int(v) == 1
        
@dataclass
class ZDMA:
    """
    Configures a channel of the PS ZDMA.
    """

    channel: int = None
    src: int = None
    dst: int = None
    size: int = None
    wr_only: bool = False
    fci_enable: bool = False
    fci_side: str = "read"
    fci_buffer_usage: int = 256
    fci_bus_address: int = None
    
    # Register offsets
    ERR_CTRL = 0
    CH_ISR = 0x100 >> 2
    CH_IMR = 0x104 >> 2
    CH_IEN = 0x108 >> 2
    CH_IDS = 0x10C >> 2
    CH_CTRL0 = 0x110 >> 2
    CH_CTRL1 = 0x114 >> 2
    CH_FCI = 0x118 >> 2
    CH_STATUS = 0x11C >> 2
    CH_DATA_ATTR = 0x120 >> 2
    CH_DSCR_ATTR = 0x124 >> 2
    CH_SRC_DSCR_WORD0 = 0x128 >> 2
    CH_DST_DSCR_WORD0 = 0x138 >> 2
    CH_WR_ONLY_WORD0 = 0x148 >> 2
    CH_SRC_START_LSB = 0x158 >> 2
    CH_SRC_START_MSB = 0x15C >> 2
    CH_DST_START_LSB = 0x160 >> 2
    CH_DST_START_MSB = 0x164 >> 2
    CH_TOTAL_BYTE = 0x188 >> 2
    CH_RATE_CTRL = 0x18C >> 2
    CH_IRQ_SRC_ACCT = 0x190 >> 2
    CH_IRQ_DST_ACCT = 0x194 >> 2
    CH_CTRL2 = 0x200 >> 2
    
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
        
        self._regs[ZDMA.CH_FCI] = ch_fci_value
        
        # Source and destination
        self._regs[ZDMA.CH_SRC_START_LSB] = self.src
        self._regs[ZDMA.CH_DST_START_LSB] = self.dst
        
        # Write the size to the source and destination registers
        self._regs[ZDMA.CH_SRC_DSCR_WORD0+2] = self.size
        self._regs[ZDMA.CH_DST_DSCR_WORD0+2] = self.size
        
    def attach(self, mem):
        """
        Attaches the object to a memory map of the DMA registers.

        :param mem: A memory-mapped numpy array pointing to the DMA registers
        :type mem: numpy.ndarray with dtype np.uint32
        """ 

        self._mem = mem
        
    def configure_hardware(self):
        """
        Writes the internally-stored configuration to the hardware.
        """

        for reg,value in self._regs.items():
            self._mem[reg] = value
    
    def start_transfer(self):
        """
        Starts the configured transfer.
        """

        proc = Processor.active_processor()
        if proc is None:
            self._mem[ZDMA.CH_CTRL2] = 1
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

        count = self._mem[ZDMA.CH_TOTAL_BYTE]
        if clear:
            self._mem[ZDMA.CH_TOTAL_BYTE] = 0
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
            return self._mem[ZDMA.CH_STATUS]
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
        if proc is None:
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
        Attaches the instance to a view of its registers.

        :param mem: A memory-mapped numpy array pointing to the registers
        :type mem: numpy.ndarray with dtype np.uint32
        """

        self._mem = mem
    
    def connect(self, mi, si, commit=True):
        """
        Connect a master interface to a slave interface.

        :param mi: Master interface number
        :type mi: int
        :param si: Slave interface number
        :type si: int
        :param commit: If ``True``, the connection request is committed. 
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
        :param commit: If ``True``, the connection request is committed. 
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
            
class ZCU216Sensors:
    """
    Wrappers for the various on-chip and onboard voltage, current, and 
    temperature sensors of the ZCU216.
    """

    @staticmethod
    def sensors(): 
        keys_list = []
        for d in os.listdir("/sys/devices/platform"):
            if d.startswith("ina226-") and d not in keys_list:
                keys_list.append(d)
        
        for d in os.listdir("/sys/bus/iio/devices/iio:device0"):
            if d.startswith("in_"):
                end = d.rindex("_")
                name = d[len("in_"):end]
                if name not in keys_list:
                    keys_list.append(name)
            
        return keys_list

    @staticmethod
    def measure(*sensors):
        """
        Measure system voltage, current, or temperature as reported by 
        on-chip and on-board sensors. Valid measurement keys are returned by
        :meth:`keys`\\.

        :return: The measurement result
        :rtype: float
        """
        if len(sensors) == 0:
            sensors = ZCU216Sensors.sensors()

        measurements = {}
        for s in sensors:
            if s.startswith("ina226"):
                filedir = f"/sys/devices/platform/{s}/hwmon"
                hwmon_dir = os.listdir(filedir)[0]
                for hwmon_file in os.listdir(os.path.join(filedir, hwmon_dir)):
                    if hwmon_file.endswith("_input"):
                        with open(os.path.join(filedir, hwmon_dir, hwmon_file)) as f:
                            key = f"{s}-{hwmon_file}"
                            if hwmon_file.startswith("in"):
                                key += "-V"
                                scale = 1e-3
                            elif hwmon_file.startswith("curr"):
                                key += "-A"
                                scale = 1e-3
                            elif hwmon_file.startswith("power"):
                                key += "-W"
                                scale = 1e-6
                            else:
                                raise ValueError(f"Unrecognized INA226 file {hwmon_file}")
                            
                            measurements[key] = scale*int(f.read())
            else:
                if "temp" in s:
                    with open(f"/sys/bus/iio/devices/iio:device0/in_{s}_offset", "r") as f:
                        offset = float(f.read())
                else:
                    offset = 0

                with open(f"/sys/bus/iio/devices/iio:device0/in_{s}_scale", "r") as f:
                    scale = float(f.read()) # * (1e-3 if "temp" in s else 1)
                with open(f"/sys/bus/iio/devices/iio:device0/in_{s}_raw", "r") as f:
                    raw = float(f.read())

                key = s + ("-C" if "temp" in s else "-V")
                measurements[key] = 1e-3*(raw + offset)*scale

        return measurements