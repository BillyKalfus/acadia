----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/19/2022 11:28:27 PM
-- Design Name: acadia
-- Module Name: nco_port_regs - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 
-- Description: Concatenates, splits, and synchronizes signals in such a way that a useful interface to the HEDGEHOG logic is provided.
-- 
-- Dependencies: 
-- 
-- Revision:
-- Revision 0.01 - File Created
-- Additional Comments:
-- 
----------------------------------------------------------------------------------


library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

library xpm;
use xpm.vcomponents.all;

entity nco_port_regs is
    port (
        -- Clocks
        clk          : in std_logic;
        nrst          : in std_logic;
        nco_dest_clk : in std_logic; -- Should be the AXI-Lite clock of the RFDC

        -- Slave interface
        master_bus_mosi : in  std_logic_vector(31 downto 0);
        master_bus_miso : out std_logic_vector(31 downto 0);
        master_bus_addr : in  std_logic_vector(31 downto 0);
        master_bus_wr   : in  std_logic;
        master_bus_en   : in  std_logic;

        -- Tile interfaces
        rfdac00_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac00_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac00_nco_phase_rst : out std_logic;
        rfdac00_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac01_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac01_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac01_nco_phase_rst : out std_logic;
        rfdac01_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac02_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac02_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac02_nco_phase_rst : out std_logic;
        rfdac02_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac03_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac03_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac03_nco_phase_rst : out std_logic;
        rfdac03_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac_tile0_nco_update_req  : out std_logic;
        rfdac_tile0_nco_update_busy : in std_logic_vector(1 downto 0);
        
        rfdac10_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac10_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac10_nco_phase_rst : out std_logic;
        rfdac10_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac11_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac11_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac11_nco_phase_rst : out std_logic;
        rfdac11_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac12_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac12_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac12_nco_phase_rst : out std_logic;
        rfdac12_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac13_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac13_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac13_nco_phase_rst : out std_logic;
        rfdac13_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac_tile1_nco_update_req  : out std_logic;
        rfdac_tile1_nco_update_busy : in std_logic_vector(1 downto 0);
        
        rfdac20_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac20_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac20_nco_phase_rst : out std_logic;
        rfdac20_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac21_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac21_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac21_nco_phase_rst : out std_logic;
        rfdac21_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac22_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac22_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac22_nco_phase_rst : out std_logic;
        rfdac22_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac23_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac23_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac23_nco_phase_rst : out std_logic;
        rfdac23_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac_tile2_nco_update_req  : out std_logic;
        rfdac_tile2_nco_update_busy : in std_logic_vector(1 downto 0);
        
        rfdac30_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac30_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac30_nco_phase_rst : out std_logic;
        rfdac30_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac31_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac31_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac31_nco_phase_rst : out std_logic;
        rfdac31_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac32_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac32_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac32_nco_phase_rst : out std_logic;
        rfdac32_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac33_nco_freq      : out std_logic_vector(47 downto 0);
        rfdac33_nco_phase     : out std_logic_vector(17 downto 0);
        rfdac33_nco_phase_rst : out std_logic;
        rfdac33_nco_update_en : out std_logic_vector(5 downto 0);
        rfdac_tile3_nco_update_req  : out std_logic;
        rfdac_tile3_nco_update_busy : in std_logic_vector(1 downto 0);
        
        rfadc00_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc00_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc00_nco_phase_rst : out std_logic;
        rfadc00_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc01_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc01_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc01_nco_phase_rst : out std_logic;
        rfadc01_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc02_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc02_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc02_nco_phase_rst : out std_logic;
        rfadc02_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc03_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc03_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc03_nco_phase_rst : out std_logic;
        rfadc03_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc_tile0_nco_update_req  : out std_logic;
        rfadc_tile0_nco_update_busy : in std_logic_vector(1 downto 0);
        
        rfadc10_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc10_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc10_nco_phase_rst : out std_logic;
        rfadc10_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc11_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc11_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc11_nco_phase_rst : out std_logic;
        rfadc11_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc12_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc12_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc12_nco_phase_rst : out std_logic;
        rfadc12_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc13_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc13_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc13_nco_phase_rst : out std_logic;
        rfadc13_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc_tile1_nco_update_req  : out std_logic;
        rfadc_tile1_nco_update_busy : in std_logic_vector(1 downto 0);
        
        rfadc20_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc20_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc20_nco_phase_rst : out std_logic;
        rfadc20_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc21_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc21_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc21_nco_phase_rst : out std_logic;
        rfadc21_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc22_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc22_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc22_nco_phase_rst : out std_logic;
        rfadc22_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc23_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc23_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc23_nco_phase_rst : out std_logic;
        rfadc23_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc_tile2_nco_update_req  : out std_logic;
        rfadc_tile2_nco_update_busy : in std_logic_vector(1 downto 0);
        
        rfadc30_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc30_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc30_nco_phase_rst : out std_logic;
        rfadc30_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc31_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc31_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc31_nco_phase_rst : out std_logic;
        rfadc31_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc32_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc32_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc32_nco_phase_rst : out std_logic;
        rfadc32_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc33_nco_freq      : out std_logic_vector(47 downto 0);
        rfadc33_nco_phase     : out std_logic_vector(17 downto 0);
        rfadc33_nco_phase_rst : out std_logic;
        rfadc33_nco_update_en : out std_logic_vector(5 downto 0);
        rfadc_tile3_nco_update_req  : out std_logic;
        rfadc_tile3_nco_update_busy : in std_logic_vector(1 downto 0)
    );

end nco_port_regs;

architecture rtl of nco_port_regs is
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_wr  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";
    
    ATTRIBUTE X_INTERFACE_INFO of rfdac00_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac00_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac00_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac00_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac01_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac01_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac01_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac01_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac02_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac02_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac02_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac02_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac03_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac03_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac03_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac03_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac_tile0_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of rfdac_tile0_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0 NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of rfdac00_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of rfdac10_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac10_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac10_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac10_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac11_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac11_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac11_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac11_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac12_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac12_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac12_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac12_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac13_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac13_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac13_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac13_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac_tile1_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of rfdac_tile1_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1 NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of rfdac10_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of rfdac20_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac20_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac20_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac20_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac21_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac21_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac21_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac21_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac22_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac22_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac22_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac22_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac23_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac23_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac23_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac23_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac_tile2_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of rfdac_tile2_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2 NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of rfdac20_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of rfdac30_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac30_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac30_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac30_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac31_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac31_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac31_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac31_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac32_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac32_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac32_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac32_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac33_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfdac33_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfdac33_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfdac33_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfdac_tile3_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of rfdac_tile3_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3 NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of rfdac30_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of rfadc00_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc00_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc00_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc00_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc01_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc01_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc01_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc01_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc02_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc02_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc02_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc02_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc03_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc03_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc03_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc03_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc_tile0_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of rfadc_tile0_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0 NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of rfadc00_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of rfadc10_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc10_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc10_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc10_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc11_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc11_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc11_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc11_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc12_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc12_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc12_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc12_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc13_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc13_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc13_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc13_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc_tile1_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of rfadc_tile1_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1 NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of rfadc10_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of rfadc20_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc20_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc20_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc20_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc21_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc21_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc21_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc21_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc22_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc22_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc22_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc22_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc23_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc23_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc23_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc23_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc_tile2_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of rfadc_tile2_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2 NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of rfadc20_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of rfadc30_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc30_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc30_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc30_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc31_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc31_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc31_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc31_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc32_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc32_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc32_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc32_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc33_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of rfadc33_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of rfadc33_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of rfadc33_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of rfadc_tile3_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of rfadc_tile3_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3 NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of rfadc30_nco_freq: SIGNAL is "Master";
    
    signal rfdac00_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac00_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac01_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac01_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac02_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac02_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac03_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac03_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal rfdac_tile0_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal rfdac10_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac10_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac11_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac11_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac12_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac12_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac13_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac13_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal rfdac_tile1_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal rfdac20_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac20_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac21_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac21_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac22_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac22_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac23_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac23_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal rfdac_tile2_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal rfdac30_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac30_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac31_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac31_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac32_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac32_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfdac33_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfdac33_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal rfdac_tile3_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal rfadc00_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc00_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc01_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc01_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc02_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc02_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc03_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc03_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal rfadc_tile0_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal rfadc10_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc10_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc11_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc11_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc12_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc12_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc13_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc13_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal rfadc_tile1_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal rfadc20_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc20_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc21_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc21_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc22_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc22_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc23_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc23_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal rfadc_tile2_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal rfadc30_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc30_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc31_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc31_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc32_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc32_nco_phase_reg : std_logic_vector(17 downto 0);
    signal rfadc33_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal rfadc33_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal rfadc_tile3_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal rf_nco_update_req_reg : std_logic_vector(7 downto 0);
    signal rf_nco_phase_rst_reg  : std_logic_vector(31 downto 0);
    
    signal nco_send : std_logic;
    signal nco_rcv  : std_logic;
    
    -- Pipeline registers
    signal master_bus_en_d  : std_logic;
    signal master_bus_en_dd : std_logic;
            
    signal master_bus_wr_d  : std_logic;
    signal master_bus_wr_dd : std_logic;
    
    signal master_bus_addr_d  : std_logic_vector(6 downto 0);
    signal master_bus_addr_dd : std_logic_vector(6 downto 0);
            
    signal master_bus_mosi_d  : std_logic_vector(31 downto 0);
    signal master_bus_mosi_dd : std_logic_vector(31 downto 0);
            
    signal nrst_d  : std_logic;
    signal nrst_dd : std_logic;
    
begin

    nco_handshake_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0' or nco_rcv = '1') then
                nco_send <= '0';
            elsif(nco_rcv = '0' and master_bus_en = '1' and master_bus_wr = '1' and to_integer(unsigned(master_bus_addr)) = 96) then
                nco_send <= '1';
            end if;
        end if;
    end process nco_handshake_proc;

    xpm_cdc_array_single_inst : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF => 4,   -- DECIMAL; range: 2-10
            INIT_SYNC_FF => 0,   -- DECIMAL; 0=disable simulation init values, 1=enable simulation init values
            SIM_ASSERT_CHK => 0, -- DECIMAL; 0=disable simulation messages, 1=enable simulation messages
            SRC_INPUT_REG => 1,  -- DECIMAL; 0=do not register input, 1=register input
            WIDTH => 8           -- DECIMAL; range: 1-1024
        )
        port map (
            src_clk => nco_dest_clk,  
            src_in(0) => rfdac_tile0_nco_update_busy(0),
            src_in(1) => rfdac_tile1_nco_update_busy(0),
            src_in(2) => rfdac_tile2_nco_update_busy(0),
            src_in(3) => rfdac_tile3_nco_update_busy(0),
            src_in(4) => rfadc_tile0_nco_update_busy(0),
            src_in(5) => rfadc_tile1_nco_update_busy(0),
            src_in(6) => rfadc_tile2_nco_update_busy(0),
            src_in(7) => rfadc_tile3_nco_update_busy(0),
            
            dest_out => master_bus_miso(7 downto 0), 
            dest_clk => clk
        );

    xpm_cdc_handshake_inst : xpm_cdc_handshake
        generic map (
            DEST_EXT_HSK   => 0,   -- DECIMAL; 0=internal handshake, 1=external handshake
            DEST_SYNC_FF   => 4,   -- DECIMAL; range: 2-10
            INIT_SYNC_FF   => 0,   -- DECIMAL; 0=disable simulation init values, 1=enable simulation init values
            SIM_ASSERT_CHK => 0, -- DECIMAL; 0=disable simulation messages, 1=enable simulation messages
            SRC_SYNC_FF    => 4,    -- DECIMAL; range: 2-10
            WIDTH          => 24*8 + 8 + 32           -- DECIMAL; range: 1-1024
        )
        port map (
            dest_clk => nco_dest_clk, -- 1-bit input: Destination clock.
            src_clk  => clk,   -- 1-bit input: Source clock.
            
            src_in(23 downto 0)    => rfdac_tile0_nco_update_en_reg,
            src_in(47 downto 24)   => rfdac_tile1_nco_update_en_reg, 
            src_in(71 downto 48)   => rfdac_tile2_nco_update_en_reg,
            src_in(95 downto 72)   => rfdac_tile3_nco_update_en_reg,
            src_in(119 downto 96)  => rfadc_tile0_nco_update_en_reg,
            src_in(143 downto 120) => rfadc_tile1_nco_update_en_reg,
            src_in(167 downto 144) => rfadc_tile2_nco_update_en_reg,
            src_in(191 downto 168) => rfadc_tile3_nco_update_en_reg,
            src_in(199 downto 192) => rf_nco_update_req_reg,
            src_in(231 downto 200) => rf_nco_phase_rst_reg,
            
            dest_out(5 downto 0) => rfdac00_nco_update_en,
            dest_out(11 downto 6) => rfdac01_nco_update_en,
            dest_out(17 downto 12) => rfdac02_nco_update_en,
            dest_out(23 downto 18) => rfdac03_nco_update_en,
            dest_out(29 downto 24) => rfdac10_nco_update_en,
            dest_out(35 downto 30) => rfdac11_nco_update_en,
            dest_out(41 downto 36) => rfdac12_nco_update_en,
            dest_out(47 downto 42) => rfdac13_nco_update_en,
            dest_out(53 downto 48) => rfdac20_nco_update_en,
            dest_out(59 downto 54) => rfdac21_nco_update_en,
            dest_out(65 downto 60) => rfdac22_nco_update_en,
            dest_out(71 downto 66) => rfdac23_nco_update_en,
            dest_out(77 downto 72) => rfdac30_nco_update_en,
            dest_out(83 downto 78) => rfdac31_nco_update_en,
            dest_out(89 downto 84) => rfdac32_nco_update_en,
            dest_out(95 downto 90) => rfdac33_nco_update_en,
            dest_out(101 downto 96) => rfadc00_nco_update_en,
            dest_out(107 downto 102) => rfadc01_nco_update_en,
            dest_out(113 downto 108) => rfadc02_nco_update_en,
            dest_out(119 downto 114) => rfadc03_nco_update_en,
            dest_out(125 downto 120) => rfadc10_nco_update_en,
            dest_out(131 downto 126) => rfadc11_nco_update_en,
            dest_out(137 downto 132) => rfadc12_nco_update_en,
            dest_out(143 downto 138) => rfadc13_nco_update_en,
            dest_out(149 downto 144) => rfadc20_nco_update_en,
            dest_out(155 downto 150) => rfadc21_nco_update_en,
            dest_out(161 downto 156) => rfadc22_nco_update_en,
            dest_out(167 downto 162) => rfadc23_nco_update_en,
            dest_out(173 downto 168) => rfadc30_nco_update_en,
            dest_out(179 downto 174) => rfadc31_nco_update_en,
            dest_out(185 downto 180) => rfadc32_nco_update_en,
            dest_out(191 downto 186) => rfadc33_nco_update_en,
            
            dest_out(192) => rfdac_tile0_nco_update_req,
            dest_out(193) => rfdac_tile1_nco_update_req,
            dest_out(194) => rfdac_tile2_nco_update_req,
            dest_out(195) => rfdac_tile3_nco_update_req,
            dest_out(196) => rfadc_tile0_nco_update_req,
            dest_out(197) => rfadc_tile1_nco_update_req,
            dest_out(198) => rfadc_tile2_nco_update_req,
            dest_out(199) => rfadc_tile3_nco_update_req,
            
            dest_out(200) => rfdac00_nco_phase_rst,
            dest_out(201) => rfdac01_nco_phase_rst,
            dest_out(202) => rfdac02_nco_phase_rst,
            dest_out(203) => rfdac03_nco_phase_rst,
            dest_out(204) => rfdac10_nco_phase_rst,
            dest_out(205) => rfdac11_nco_phase_rst,
            dest_out(206) => rfdac12_nco_phase_rst,
            dest_out(207) => rfdac13_nco_phase_rst,
            dest_out(208) => rfdac20_nco_phase_rst,
            dest_out(209) => rfdac21_nco_phase_rst,
            dest_out(210) => rfdac22_nco_phase_rst,
            dest_out(211) => rfdac23_nco_phase_rst,
            dest_out(212) => rfdac30_nco_phase_rst,
            dest_out(213) => rfdac31_nco_phase_rst,
            dest_out(214) => rfdac32_nco_phase_rst,
            dest_out(215) => rfdac33_nco_phase_rst,
            dest_out(216) => rfadc00_nco_phase_rst,
            dest_out(217) => rfadc01_nco_phase_rst,
            dest_out(218) => rfadc02_nco_phase_rst,
            dest_out(219) => rfadc03_nco_phase_rst,
            dest_out(220) => rfadc10_nco_phase_rst,
            dest_out(221) => rfadc11_nco_phase_rst,
            dest_out(222) => rfadc12_nco_phase_rst,
            dest_out(223) => rfadc13_nco_phase_rst,
            dest_out(224) => rfadc20_nco_phase_rst,
            dest_out(225) => rfadc21_nco_phase_rst,
            dest_out(226) => rfadc22_nco_phase_rst,
            dest_out(227) => rfadc23_nco_phase_rst,
            dest_out(228) => rfadc30_nco_phase_rst,
            dest_out(229) => rfadc31_nco_phase_rst,
            dest_out(230) => rfadc32_nco_phase_rst,
            dest_out(231) => rfadc33_nco_phase_rst,
            
    
            src_rcv => nco_rcv,   -- 1-bit output: Acknowledgement from destination logic that src_in has been
                                -- received. This signal will be deasserted once destination handshake has fully
                                -- completed, thus completing a full data transfer. This output is registered.
    
          
            
    
            src_send => nco_send,  -- 1-bit input: Assertion of this signal allows the src_in bus to be synchronized
                                -- to the destination clock domain. This signal should only be asserted when
                                -- src_rcv is deasserted, indicating that the previous data transfer is complete.
                                -- This signal should only be deasserted once src_rcv is asserted, acknowledging
                                -- that the src_in has been received by the destination logic.
                                
            dest_ack => '0'
    
       );
       
    bus_delay_proc : process(clk) begin
        if rising_edge(clk) then
            master_bus_en_d <= master_bus_en;
            master_bus_en_dd <= master_bus_en_d;
            
            master_bus_wr_d <= master_bus_wr;
            master_bus_wr_dd <= master_bus_wr_d;
            
            master_bus_addr_d <= master_bus_addr(6 downto 0);
            master_bus_addr_dd <= master_bus_addr_d;
            
            master_bus_mosi_d <= master_bus_mosi;
            master_bus_mosi_dd <= master_bus_mosi_d;
            
            nrst_d <= nrst;
            nrst_dd <= nrst_d;
        end if;
    end process bus_delay_proc;
       
    regs_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst_dd = '0') then
                rfdac00_nco_freq_reg               <= (others => '0');
                rfdac00_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 0) then
                rfdac00_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 1) then
                rfdac00_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 2) then
                rfdac00_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac01_nco_freq_reg               <= (others => '0');
                rfdac01_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 3) then
                rfdac01_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 4) then
                rfdac01_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 5) then
                rfdac01_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac02_nco_freq_reg               <= (others => '0');
                rfdac02_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 6) then
                rfdac02_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 7) then
                rfdac02_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 8) then
                rfdac02_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac03_nco_freq_reg               <= (others => '0');
                rfdac03_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 9) then
                rfdac03_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 10) then
                rfdac03_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 11) then
                rfdac03_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac10_nco_freq_reg               <= (others => '0');
                rfdac10_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 12) then
                rfdac10_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 13) then
                rfdac10_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 14) then
                rfdac10_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac11_nco_freq_reg               <= (others => '0');
                rfdac11_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 15) then
                rfdac11_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 16) then
                rfdac11_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 17) then
                rfdac11_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac12_nco_freq_reg               <= (others => '0');
                rfdac12_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 18) then
                rfdac12_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 19) then
                rfdac12_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 20) then
                rfdac12_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac13_nco_freq_reg               <= (others => '0');
                rfdac13_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 21) then
                rfdac13_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 22) then
                rfdac13_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 23) then
                rfdac13_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac20_nco_freq_reg               <= (others => '0');
                rfdac20_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 24) then
                rfdac20_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 25) then
                rfdac20_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 26) then
                rfdac20_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac21_nco_freq_reg               <= (others => '0');
                rfdac21_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 27) then
                rfdac21_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 28) then
                rfdac21_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 29) then
                rfdac21_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac22_nco_freq_reg               <= (others => '0');
                rfdac22_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 30) then
                rfdac22_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 31) then
                rfdac22_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 32) then
                rfdac22_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac23_nco_freq_reg               <= (others => '0');
                rfdac23_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 33) then
                rfdac23_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 34) then
                rfdac23_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 35) then
                rfdac23_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac30_nco_freq_reg               <= (others => '0');
                rfdac30_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 36) then
                rfdac30_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 37) then
                rfdac30_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 38) then
                rfdac30_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac31_nco_freq_reg               <= (others => '0');
                rfdac31_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 39) then
                rfdac31_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 40) then
                rfdac31_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 41) then
                rfdac31_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac32_nco_freq_reg               <= (others => '0');
                rfdac32_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 42) then
                rfdac32_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 43) then
                rfdac32_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 44) then
                rfdac32_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfdac33_nco_freq_reg               <= (others => '0');
                rfdac33_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 45) then
                rfdac33_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 46) then
                rfdac33_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 47) then
                rfdac33_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc00_nco_freq_reg               <= (others => '0');
                rfadc00_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 48) then
                rfadc00_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 49) then
                rfadc00_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 50) then
                rfadc00_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc01_nco_freq_reg               <= (others => '0');
                rfadc01_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 51) then
                rfadc01_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 52) then
                rfadc01_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 53) then
                rfadc01_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc02_nco_freq_reg               <= (others => '0');
                rfadc02_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 54) then
                rfadc02_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 55) then
                rfadc02_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 56) then
                rfadc02_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc03_nco_freq_reg               <= (others => '0');
                rfadc03_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 57) then
                rfadc03_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 58) then
                rfadc03_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 59) then
                rfadc03_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc10_nco_freq_reg               <= (others => '0');
                rfadc10_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 60) then
                rfadc10_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 61) then
                rfadc10_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 62) then
                rfadc10_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc11_nco_freq_reg               <= (others => '0');
                rfadc11_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 63) then
                rfadc11_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 64) then
                rfadc11_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 65) then
                rfadc11_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc12_nco_freq_reg               <= (others => '0');
                rfadc12_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 66) then
                rfadc12_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 67) then
                rfadc12_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 68) then
                rfadc12_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc13_nco_freq_reg               <= (others => '0');
                rfadc13_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 69) then
                rfadc13_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 70) then
                rfadc13_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 71) then
                rfadc13_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc20_nco_freq_reg               <= (others => '0');
                rfadc20_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 72) then
                rfadc20_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 73) then
                rfadc20_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 74) then
                rfadc20_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc21_nco_freq_reg               <= (others => '0');
                rfadc21_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 75) then
                rfadc21_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 76) then
                rfadc21_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 77) then
                rfadc21_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc22_nco_freq_reg               <= (others => '0');
                rfadc22_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 78) then
                rfadc22_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 79) then
                rfadc22_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 80) then
                rfadc22_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc23_nco_freq_reg               <= (others => '0');
                rfadc23_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 81) then
                rfadc23_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 82) then
                rfadc23_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 83) then
                rfadc23_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc30_nco_freq_reg               <= (others => '0');
                rfadc30_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 84) then
                rfadc30_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 85) then
                rfadc30_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 86) then
                rfadc30_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc31_nco_freq_reg               <= (others => '0');
                rfadc31_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 87) then
                rfadc31_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 88) then
                rfadc31_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 89) then
                rfadc31_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc32_nco_freq_reg               <= (others => '0');
                rfadc32_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 90) then
                rfadc32_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 91) then
                rfadc32_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 92) then
                rfadc32_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

            if(nrst_dd = '0') then
                rfadc33_nco_freq_reg               <= (others => '0');
                rfadc33_nco_phase_reg              <= (others => '0');
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 93) then
                rfadc33_nco_freq_reg(15 downto 0)  <= master_bus_mosi_dd(15 downto 0);
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 94) then
                rfadc33_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1' and to_integer(unsigned(master_bus_addr_dd)) = 95) then
                rfadc33_nco_phase_reg              <= master_bus_mosi_dd(17 downto 0);
            end if;

        end if;
    end process regs_proc;

    xpm_cdc_array_single_dac00 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac00_nco_freq_reg,
            src_in(65 downto 48)   => rfdac00_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac00_nco_freq,
            dest_out(65 downto 48) => rfdac00_nco_phase
        );

    xpm_cdc_array_single_dac01 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac01_nco_freq_reg,
            src_in(65 downto 48)   => rfdac01_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac01_nco_freq,
            dest_out(65 downto 48) => rfdac01_nco_phase
        );

    xpm_cdc_array_single_dac02 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac02_nco_freq_reg,
            src_in(65 downto 48)   => rfdac02_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac02_nco_freq,
            dest_out(65 downto 48) => rfdac02_nco_phase
        );

    xpm_cdc_array_single_dac03 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac03_nco_freq_reg,
            src_in(65 downto 48)   => rfdac03_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac03_nco_freq,
            dest_out(65 downto 48) => rfdac03_nco_phase
        );

    xpm_cdc_array_single_dac10 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac10_nco_freq_reg,
            src_in(65 downto 48)   => rfdac10_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac10_nco_freq,
            dest_out(65 downto 48) => rfdac10_nco_phase
        );

    xpm_cdc_array_single_dac11 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac11_nco_freq_reg,
            src_in(65 downto 48)   => rfdac11_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac11_nco_freq,
            dest_out(65 downto 48) => rfdac11_nco_phase
        );

    xpm_cdc_array_single_dac12 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac12_nco_freq_reg,
            src_in(65 downto 48)   => rfdac12_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac12_nco_freq,
            dest_out(65 downto 48) => rfdac12_nco_phase
        );

    xpm_cdc_array_single_dac13 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac13_nco_freq_reg,
            src_in(65 downto 48)   => rfdac13_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac13_nco_freq,
            dest_out(65 downto 48) => rfdac13_nco_phase
        );

    xpm_cdc_array_single_dac20 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac20_nco_freq_reg,
            src_in(65 downto 48)   => rfdac20_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac20_nco_freq,
            dest_out(65 downto 48) => rfdac20_nco_phase
        );

    xpm_cdc_array_single_dac21 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac21_nco_freq_reg,
            src_in(65 downto 48)   => rfdac21_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac21_nco_freq,
            dest_out(65 downto 48) => rfdac21_nco_phase
        );

    xpm_cdc_array_single_dac22 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac22_nco_freq_reg,
            src_in(65 downto 48)   => rfdac22_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac22_nco_freq,
            dest_out(65 downto 48) => rfdac22_nco_phase
        );

    xpm_cdc_array_single_dac23 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac23_nco_freq_reg,
            src_in(65 downto 48)   => rfdac23_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac23_nco_freq,
            dest_out(65 downto 48) => rfdac23_nco_phase
        );

    xpm_cdc_array_single_dac30 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac30_nco_freq_reg,
            src_in(65 downto 48)   => rfdac30_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac30_nco_freq,
            dest_out(65 downto 48) => rfdac30_nco_phase
        );

    xpm_cdc_array_single_dac31 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac31_nco_freq_reg,
            src_in(65 downto 48)   => rfdac31_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac31_nco_freq,
            dest_out(65 downto 48) => rfdac31_nco_phase
        );

    xpm_cdc_array_single_dac32 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac32_nco_freq_reg,
            src_in(65 downto 48)   => rfdac32_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac32_nco_freq,
            dest_out(65 downto 48) => rfdac32_nco_phase
        );

    xpm_cdc_array_single_dac33 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfdac33_nco_freq_reg,
            src_in(65 downto 48)   => rfdac33_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfdac33_nco_freq,
            dest_out(65 downto 48) => rfdac33_nco_phase
        );

    xpm_cdc_array_single_adc00 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc00_nco_freq_reg,
            src_in(65 downto 48)   => rfadc00_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc00_nco_freq,
            dest_out(65 downto 48) => rfadc00_nco_phase
        );

    xpm_cdc_array_single_adc01 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc01_nco_freq_reg,
            src_in(65 downto 48)   => rfadc01_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc01_nco_freq,
            dest_out(65 downto 48) => rfadc01_nco_phase
        );

    xpm_cdc_array_single_adc02 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc02_nco_freq_reg,
            src_in(65 downto 48)   => rfadc02_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc02_nco_freq,
            dest_out(65 downto 48) => rfadc02_nco_phase
        );

    xpm_cdc_array_single_adc03 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc03_nco_freq_reg,
            src_in(65 downto 48)   => rfadc03_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc03_nco_freq,
            dest_out(65 downto 48) => rfadc03_nco_phase
        );

    xpm_cdc_array_single_adc10 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc10_nco_freq_reg,
            src_in(65 downto 48)   => rfadc10_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc10_nco_freq,
            dest_out(65 downto 48) => rfadc10_nco_phase
        );

    xpm_cdc_array_single_adc11 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc11_nco_freq_reg,
            src_in(65 downto 48)   => rfadc11_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc11_nco_freq,
            dest_out(65 downto 48) => rfadc11_nco_phase
        );

    xpm_cdc_array_single_adc12 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc12_nco_freq_reg,
            src_in(65 downto 48)   => rfadc12_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc12_nco_freq,
            dest_out(65 downto 48) => rfadc12_nco_phase
        );

    xpm_cdc_array_single_adc13 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc13_nco_freq_reg,
            src_in(65 downto 48)   => rfadc13_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc13_nco_freq,
            dest_out(65 downto 48) => rfadc13_nco_phase
        );

    xpm_cdc_array_single_adc20 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc20_nco_freq_reg,
            src_in(65 downto 48)   => rfadc20_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc20_nco_freq,
            dest_out(65 downto 48) => rfadc20_nco_phase
        );

    xpm_cdc_array_single_adc21 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc21_nco_freq_reg,
            src_in(65 downto 48)   => rfadc21_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc21_nco_freq,
            dest_out(65 downto 48) => rfadc21_nco_phase
        );

    xpm_cdc_array_single_adc22 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc22_nco_freq_reg,
            src_in(65 downto 48)   => rfadc22_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc22_nco_freq,
            dest_out(65 downto 48) => rfadc22_nco_phase
        );

    xpm_cdc_array_single_adc23 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc23_nco_freq_reg,
            src_in(65 downto 48)   => rfadc23_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc23_nco_freq,
            dest_out(65 downto 48) => rfadc23_nco_phase
        );

    xpm_cdc_array_single_adc30 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc30_nco_freq_reg,
            src_in(65 downto 48)   => rfadc30_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc30_nco_freq,
            dest_out(65 downto 48) => rfadc30_nco_phase
        );

    xpm_cdc_array_single_adc31 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc31_nco_freq_reg,
            src_in(65 downto 48)   => rfadc31_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc31_nco_freq,
            dest_out(65 downto 48) => rfadc31_nco_phase
        );

    xpm_cdc_array_single_adc32 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc32_nco_freq_reg,
            src_in(65 downto 48)   => rfadc32_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc32_nco_freq,
            dest_out(65 downto 48) => rfadc32_nco_phase
        );

    xpm_cdc_array_single_adc33 : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48 + 18
        )
        port map (
            src_clk                => clk,  
            src_in(47 downto 0)    => rfadc33_nco_freq_reg,
            src_in(65 downto 48)   => rfadc33_nco_phase_reg,
            dest_clk               => nco_dest_clk,
            dest_out(47 downto 0)  => rfadc33_nco_freq,
            dest_out(65 downto 48) => rfadc33_nco_phase
        );
end rtl;
