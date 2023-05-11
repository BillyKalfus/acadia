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

entity acadia_rfdc_rts_regs is
    port (
        -- Clocks
        nrst         : in std_logic;
        nco_dest_clk : in std_logic; -- Should be the AXI-Lite clock of the RFDC

        -- Slave interface
        master_bus_mosi : in  std_logic_vector(31 downto 0);
        master_bus_miso : out std_logic_vector(31 downto 0);
        master_bus_addr : in  std_logic_vector(31 downto 0);
        master_bus_wr   : in  std_logic;
        master_bus_en   : in  std_logic;
        master_bus_clk  : in  std_logic;

        -- Tile interfaces
        dac00_nco_freq      : out std_logic_vector(47 downto 0);
        dac00_nco_phase     : out std_logic_vector(17 downto 0);
        dac00_nco_phase_rst : out std_logic;
        dac00_nco_update_en : out std_logic_vector(5 downto 0);
        dac01_nco_freq      : out std_logic_vector(47 downto 0);
        dac01_nco_phase     : out std_logic_vector(17 downto 0);
        dac01_nco_phase_rst : out std_logic;
        dac01_nco_update_en : out std_logic_vector(5 downto 0);
        dac02_nco_freq      : out std_logic_vector(47 downto 0);
        dac02_nco_phase     : out std_logic_vector(17 downto 0);
        dac02_nco_phase_rst : out std_logic;
        dac02_nco_update_en : out std_logic_vector(5 downto 0);
        dac03_nco_freq      : out std_logic_vector(47 downto 0);
        dac03_nco_phase     : out std_logic_vector(17 downto 0);
        dac03_nco_phase_rst : out std_logic;
        dac03_nco_update_en : out std_logic_vector(5 downto 0);
        dac_tile0_nco_update_req  : out std_logic;
        dac_tile0_nco_update_busy : in std_logic_vector(1 downto 0);
        
        dac10_nco_freq      : out std_logic_vector(47 downto 0);
        dac10_nco_phase     : out std_logic_vector(17 downto 0);
        dac10_nco_phase_rst : out std_logic;
        dac10_nco_update_en : out std_logic_vector(5 downto 0);
        dac11_nco_freq      : out std_logic_vector(47 downto 0);
        dac11_nco_phase     : out std_logic_vector(17 downto 0);
        dac11_nco_phase_rst : out std_logic;
        dac11_nco_update_en : out std_logic_vector(5 downto 0);
        dac12_nco_freq      : out std_logic_vector(47 downto 0);
        dac12_nco_phase     : out std_logic_vector(17 downto 0);
        dac12_nco_phase_rst : out std_logic;
        dac12_nco_update_en : out std_logic_vector(5 downto 0);
        dac13_nco_freq      : out std_logic_vector(47 downto 0);
        dac13_nco_phase     : out std_logic_vector(17 downto 0);
        dac13_nco_phase_rst : out std_logic;
        dac13_nco_update_en : out std_logic_vector(5 downto 0);
        dac_tile1_nco_update_req  : out std_logic;
        dac_tile1_nco_update_busy : in std_logic_vector(1 downto 0);
        
        dac20_nco_freq      : out std_logic_vector(47 downto 0);
        dac20_nco_phase     : out std_logic_vector(17 downto 0);
        dac20_nco_phase_rst : out std_logic;
        dac20_nco_update_en : out std_logic_vector(5 downto 0);
        dac21_nco_freq      : out std_logic_vector(47 downto 0);
        dac21_nco_phase     : out std_logic_vector(17 downto 0);
        dac21_nco_phase_rst : out std_logic;
        dac21_nco_update_en : out std_logic_vector(5 downto 0);
        dac22_nco_freq      : out std_logic_vector(47 downto 0);
        dac22_nco_phase     : out std_logic_vector(17 downto 0);
        dac22_nco_phase_rst : out std_logic;
        dac22_nco_update_en : out std_logic_vector(5 downto 0);
        dac23_nco_freq      : out std_logic_vector(47 downto 0);
        dac23_nco_phase     : out std_logic_vector(17 downto 0);
        dac23_nco_phase_rst : out std_logic;
        dac23_nco_update_en : out std_logic_vector(5 downto 0);
        dac_tile2_nco_update_req  : out std_logic;
        dac_tile2_nco_update_busy : in std_logic_vector(1 downto 0);
        
        dac30_nco_freq      : out std_logic_vector(47 downto 0);
        dac30_nco_phase     : out std_logic_vector(17 downto 0);
        dac30_nco_phase_rst : out std_logic;
        dac30_nco_update_en : out std_logic_vector(5 downto 0);
        dac31_nco_freq      : out std_logic_vector(47 downto 0);
        dac31_nco_phase     : out std_logic_vector(17 downto 0);
        dac31_nco_phase_rst : out std_logic;
        dac31_nco_update_en : out std_logic_vector(5 downto 0);
        dac32_nco_freq      : out std_logic_vector(47 downto 0);
        dac32_nco_phase     : out std_logic_vector(17 downto 0);
        dac32_nco_phase_rst : out std_logic;
        dac32_nco_update_en : out std_logic_vector(5 downto 0);
        dac33_nco_freq      : out std_logic_vector(47 downto 0);
        dac33_nco_phase     : out std_logic_vector(17 downto 0);
        dac33_nco_phase_rst : out std_logic;
        dac33_nco_update_en : out std_logic_vector(5 downto 0);
        dac_tile3_nco_update_req  : out std_logic;
        dac_tile3_nco_update_busy : in std_logic_vector(1 downto 0);
        
        adc00_nco_freq      : out std_logic_vector(47 downto 0);
        adc00_nco_phase     : out std_logic_vector(17 downto 0);
        adc00_nco_phase_rst : out std_logic;
        adc00_nco_update_en : out std_logic_vector(5 downto 0);
        adc01_nco_freq      : out std_logic_vector(47 downto 0);
        adc01_nco_phase     : out std_logic_vector(17 downto 0);
        adc01_nco_phase_rst : out std_logic;
        adc01_nco_update_en : out std_logic_vector(5 downto 0);
        adc02_nco_freq      : out std_logic_vector(47 downto 0);
        adc02_nco_phase     : out std_logic_vector(17 downto 0);
        adc02_nco_phase_rst : out std_logic;
        adc02_nco_update_en : out std_logic_vector(5 downto 0);
        adc03_nco_freq      : out std_logic_vector(47 downto 0);
        adc03_nco_phase     : out std_logic_vector(17 downto 0);
        adc03_nco_phase_rst : out std_logic;
        adc03_nco_update_en : out std_logic_vector(5 downto 0);
        adc_tile0_nco_update_req  : out std_logic;
        adc_tile0_nco_update_busy : in std_logic_vector(1 downto 0);
        
        adc10_nco_freq      : out std_logic_vector(47 downto 0);
        adc10_nco_phase     : out std_logic_vector(17 downto 0);
        adc10_nco_phase_rst : out std_logic;
        adc10_nco_update_en : out std_logic_vector(5 downto 0);
        adc11_nco_freq      : out std_logic_vector(47 downto 0);
        adc11_nco_phase     : out std_logic_vector(17 downto 0);
        adc11_nco_phase_rst : out std_logic;
        adc11_nco_update_en : out std_logic_vector(5 downto 0);
        adc12_nco_freq      : out std_logic_vector(47 downto 0);
        adc12_nco_phase     : out std_logic_vector(17 downto 0);
        adc12_nco_phase_rst : out std_logic;
        adc12_nco_update_en : out std_logic_vector(5 downto 0);
        adc13_nco_freq      : out std_logic_vector(47 downto 0);
        adc13_nco_phase     : out std_logic_vector(17 downto 0);
        adc13_nco_phase_rst : out std_logic;
        adc13_nco_update_en : out std_logic_vector(5 downto 0);
        adc_tile1_nco_update_req  : out std_logic;
        adc_tile1_nco_update_busy : in std_logic_vector(1 downto 0);
        
        adc20_nco_freq      : out std_logic_vector(47 downto 0);
        adc20_nco_phase     : out std_logic_vector(17 downto 0);
        adc20_nco_phase_rst : out std_logic;
        adc20_nco_update_en : out std_logic_vector(5 downto 0);
        adc21_nco_freq      : out std_logic_vector(47 downto 0);
        adc21_nco_phase     : out std_logic_vector(17 downto 0);
        adc21_nco_phase_rst : out std_logic;
        adc21_nco_update_en : out std_logic_vector(5 downto 0);
        adc22_nco_freq      : out std_logic_vector(47 downto 0);
        adc22_nco_phase     : out std_logic_vector(17 downto 0);
        adc22_nco_phase_rst : out std_logic;
        adc22_nco_update_en : out std_logic_vector(5 downto 0);
        adc23_nco_freq      : out std_logic_vector(47 downto 0);
        adc23_nco_phase     : out std_logic_vector(17 downto 0);
        adc23_nco_phase_rst : out std_logic;
        adc23_nco_update_en : out std_logic_vector(5 downto 0);
        adc_tile2_nco_update_req  : out std_logic;
        adc_tile2_nco_update_busy : in std_logic_vector(1 downto 0);
        
        adc30_nco_freq      : out std_logic_vector(47 downto 0);
        adc30_nco_phase     : out std_logic_vector(17 downto 0);
        adc30_nco_phase_rst : out std_logic;
        adc30_nco_update_en : out std_logic_vector(5 downto 0);
        adc31_nco_freq      : out std_logic_vector(47 downto 0);
        adc31_nco_phase     : out std_logic_vector(17 downto 0);
        adc31_nco_phase_rst : out std_logic;
        adc31_nco_update_en : out std_logic_vector(5 downto 0);
        adc32_nco_freq      : out std_logic_vector(47 downto 0);
        adc32_nco_phase     : out std_logic_vector(17 downto 0);
        adc32_nco_phase_rst : out std_logic;
        adc32_nco_update_en : out std_logic_vector(5 downto 0);
        adc33_nco_freq      : out std_logic_vector(47 downto 0);
        adc33_nco_phase     : out std_logic_vector(17 downto 0);
        adc33_nco_phase_rst : out std_logic;
        adc33_nco_update_en : out std_logic_vector(5 downto 0);
        adc_tile3_nco_update_req  : out std_logic;
        adc_tile3_nco_update_busy : in std_logic_vector(1 downto 0);
        
        dac00_vop_code   : out std_logic_vector(9 downto 0);
        dac00_update_vop : out std_logic;
        dac00_vop_done   : in std_logic;
        dac01_vop_code   : out std_logic_vector(9 downto 0);
        dac01_update_vop : out std_logic;
        dac01_vop_done   : in std_logic;
        dac02_vop_code   : out std_logic_vector(9 downto 0);
        dac02_update_vop : out std_logic;
        dac02_vop_done   : in std_logic;
        dac03_vop_code   : out std_logic_vector(9 downto 0);
        dac03_update_vop : out std_logic;
        dac03_vop_done   : in std_logic;
        dac_tile0_vop_busy : in std_logic;
        
        dac10_vop_code   : out std_logic_vector(9 downto 0);
        dac10_update_vop : out std_logic;
        dac10_vop_done   : in std_logic;
        dac11_vop_code   : out std_logic_vector(9 downto 0);
        dac11_update_vop : out std_logic;
        dac11_vop_done   : in std_logic;
        dac12_vop_code   : out std_logic_vector(9 downto 0);
        dac12_update_vop : out std_logic;
        dac12_vop_done   : in std_logic;
        dac13_vop_code   : out std_logic_vector(9 downto 0);
        dac13_update_vop : out std_logic;
        dac13_vop_done   : in std_logic;
        dac_tile1_vop_busy : in std_logic;
        
        dac20_vop_code   : out std_logic_vector(9 downto 0);
        dac20_update_vop : out std_logic;
        dac20_vop_done   : in std_logic;
        dac21_vop_code   : out std_logic_vector(9 downto 0);
        dac21_update_vop : out std_logic;
        dac21_vop_done   : in std_logic;
        dac22_vop_code   : out std_logic_vector(9 downto 0);
        dac22_update_vop : out std_logic;
        dac22_vop_done   : in std_logic;
        dac23_vop_code   : out std_logic_vector(9 downto 0);
        dac23_update_vop : out std_logic;
        dac23_vop_done   : in std_logic;
        dac_tile2_vop_busy : in std_logic;
        
        dac30_vop_code   : out std_logic_vector(9 downto 0);
        dac30_update_vop : out std_logic;
        dac30_vop_done   : in std_logic;
        dac31_vop_code   : out std_logic_vector(9 downto 0);
        dac31_update_vop : out std_logic;
        dac31_vop_done   : in std_logic;
        dac32_vop_code   : out std_logic_vector(9 downto 0);
        dac32_update_vop : out std_logic;
        dac32_vop_done   : in std_logic;
        dac33_vop_code   : out std_logic_vector(9 downto 0);
        dac33_update_vop : out std_logic;
        dac33_vop_done   : in std_logic;
        dac_tile3_vop_busy : in std_logic;

        adc00_dsa_code   : out std_logic_vector(4 downto 0);
        adc01_dsa_code   : out std_logic_vector(4 downto 0);
        adc02_dsa_code   : out std_logic_vector(4 downto 0);
        adc03_dsa_code   : out std_logic_vector(4 downto 0);
        adc_tile0_dsa_update   : out std_logic;
        adc10_dsa_code   : out std_logic_vector(4 downto 0);
        adc11_dsa_code   : out std_logic_vector(4 downto 0);
        adc12_dsa_code   : out std_logic_vector(4 downto 0);
        adc13_dsa_code   : out std_logic_vector(4 downto 0);
        adc_tile1_dsa_update   : out std_logic;
        adc20_dsa_code   : out std_logic_vector(4 downto 0);
        adc21_dsa_code   : out std_logic_vector(4 downto 0);
        adc22_dsa_code   : out std_logic_vector(4 downto 0);
        adc23_dsa_code   : out std_logic_vector(4 downto 0);
        adc_tile2_dsa_update   : out std_logic;
        adc30_dsa_code   : out std_logic_vector(4 downto 0);
        adc31_dsa_code   : out std_logic_vector(4 downto 0);
        adc32_dsa_code   : out std_logic_vector(4 downto 0);
        adc33_dsa_code   : out std_logic_vector(4 downto 0);
        adc_tile3_dsa_update   : out std_logic;

        dac00_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac00_pl_event : out std_logic;
        dac01_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac01_pl_event : out std_logic;
        dac02_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac02_pl_event : out std_logic;
        dac03_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac03_pl_event : out std_logic;
        dac10_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac10_pl_event : out std_logic;
        dac11_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac11_pl_event : out std_logic;
        dac12_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac12_pl_event : out std_logic;
        dac13_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac13_pl_event : out std_logic;
        dac20_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac20_pl_event : out std_logic;
        dac21_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac21_pl_event : out std_logic;
        dac22_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac22_pl_event : out std_logic;
        dac23_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac23_pl_event : out std_logic;
        dac30_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac30_pl_event : out std_logic;
        dac31_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac31_pl_event : out std_logic;
        dac32_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac32_pl_event : out std_logic;
        dac33_fast_shutdown   : out std_logic_vector(2 downto 0);
        dac33_pl_event : out std_logic;

        adc00_pl_event : out std_logic;
        adc01_pl_event : out std_logic;
        adc02_pl_event : out std_logic;
        adc03_pl_event : out std_logic;
        adc10_pl_event : out std_logic;
        adc11_pl_event : out std_logic;
        adc12_pl_event : out std_logic;
        adc13_pl_event : out std_logic;
        adc20_pl_event : out std_logic;
        adc21_pl_event : out std_logic;
        adc22_pl_event : out std_logic;
        adc23_pl_event : out std_logic;
        adc30_pl_event : out std_logic;
        adc31_pl_event : out std_logic;
        adc32_pl_event : out std_logic;
        adc33_pl_event : out std_logic;
        
        dac00_tdd_mode : out std_logic;
        dac01_tdd_mode : out std_logic;
        dac02_tdd_mode : out std_logic;
        dac03_tdd_mode : out std_logic;
        dac10_tdd_mode : out std_logic;
        dac11_tdd_mode : out std_logic;
        dac12_tdd_mode : out std_logic;
        dac13_tdd_mode : out std_logic;
        dac20_tdd_mode : out std_logic;
        dac21_tdd_mode : out std_logic;
        dac22_tdd_mode : out std_logic;
        dac23_tdd_mode : out std_logic;
        dac30_tdd_mode : out std_logic;
        dac31_tdd_mode : out std_logic;
        dac32_tdd_mode : out std_logic;
        dac33_tdd_mode : out std_logic;
        adc00_tdd_mode : out std_logic;
        adc01_tdd_mode : out std_logic;
        adc02_tdd_mode : out std_logic;
        adc03_tdd_mode : out std_logic;
        adc10_tdd_mode : out std_logic;
        adc11_tdd_mode : out std_logic;
        adc12_tdd_mode : out std_logic;
        adc13_tdd_mode : out std_logic;
        adc20_tdd_mode : out std_logic;
        adc21_tdd_mode : out std_logic;
        adc22_tdd_mode : out std_logic;
        adc23_tdd_mode : out std_logic;
        adc30_tdd_mode : out std_logic;
        adc31_tdd_mode : out std_logic;
        adc32_tdd_mode : out std_logic;
        adc33_tdd_mode : out std_logic
    );

end acadia_rfdc_rts_regs;

architecture rtl of acadia_rfdc_rts_regs is
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_wr  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_clk : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus CLK";
    
    ATTRIBUTE X_INTERFACE_INFO of dac00_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac00_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac00_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac00_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac01_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac01_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac01_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac01_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac02_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac02_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac02_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac02_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac03_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac03_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac03_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac03_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile0_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile0_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac0_nco NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of dac00_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of dac10_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac10_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac10_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac10_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac11_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac11_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac11_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac11_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac12_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac12_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac12_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac12_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac13_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac13_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac13_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac13_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile1_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile1_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac1_nco NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of dac10_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of dac20_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac20_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac20_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac20_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac21_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac21_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac21_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac21_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac22_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac22_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac22_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac22_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac23_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac23_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac23_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac23_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile2_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile2_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac2_nco NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of dac20_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of dac30_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac30_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac30_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac30_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac31_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac31_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac31_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac31_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac32_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac32_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac32_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac32_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac33_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of dac33_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of dac33_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of dac33_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile3_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile3_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 dac3_nco NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of dac30_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of adc00_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc00_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc00_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc00_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc01_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc01_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc01_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc01_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc02_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc02_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc02_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc02_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc03_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc03_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc03_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc03_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile0_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile0_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc0_nco NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of adc00_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of adc10_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc10_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc10_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc10_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc11_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc11_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc11_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc11_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc12_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc12_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc12_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc12_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc13_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc13_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc13_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc13_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile1_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile1_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc1_nco NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of adc10_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of adc20_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc20_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc20_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc20_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc21_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc21_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc21_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc21_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc22_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc22_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc22_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc22_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc23_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc23_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc23_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc23_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile2_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile2_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc2_nco NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of adc20_nco_freq: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of adc30_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER0_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc30_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER0_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc30_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER0_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc30_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER0_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc31_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER1_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc31_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER1_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc31_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER1_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc31_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER1_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc32_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER2_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc32_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER2_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc32_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER2_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc32_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER2_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc33_nco_freq      : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER3_NCO_FREQ";
    ATTRIBUTE X_INTERFACE_INFO of adc33_nco_phase     : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER3_NCO_PHASE";
    ATTRIBUTE X_INTERFACE_INFO of adc33_nco_phase_rst : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER3_PHASE_RESET";
    ATTRIBUTE X_INTERFACE_INFO of adc33_nco_update_en : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco CONVERTER3_UPDATE_EN";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile3_nco_update_req  : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco NCO_UPDATE_REQUEST";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile3_nco_update_busy : SIGNAL is "xilinx.com:interface:rfdc_nco_pins_rtl:1.0 adc3_nco NCO_UPDATE_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of adc30_nco_freq: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of dac00_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER0_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac00_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER0_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac00_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER0_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac01_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER1_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac01_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER1_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac01_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER1_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac02_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER2_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac02_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER2_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac02_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER2_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac03_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER3_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac03_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER3_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac03_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts CONVERTER3_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile0_vop_busy : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac0_vop_rts VOP_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of dac00_vop_code: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of dac10_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER0_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac10_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER0_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac10_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER0_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac11_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER1_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac11_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER1_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac11_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER1_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac12_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER2_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac12_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER2_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac12_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER2_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac13_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER3_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac13_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER3_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac13_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts CONVERTER3_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile1_vop_busy : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac1_vop_rts VOP_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of dac10_vop_code: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of dac20_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER0_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac20_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER0_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac20_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER0_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac21_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER1_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac21_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER1_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac21_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER1_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac22_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER2_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac22_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER2_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac22_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER2_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac23_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER3_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac23_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER3_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac23_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts CONVERTER3_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile2_vop_busy : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac2_vop_rts VOP_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of dac20_vop_code: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of dac30_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER0_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac30_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER0_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac30_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER0_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac31_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER1_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac31_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER1_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac31_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER1_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac32_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER2_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac32_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER2_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac32_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER2_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac33_vop_code   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER3_VOP_CODE";
    ATTRIBUTE X_INTERFACE_INFO of dac33_update_vop : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER3_UPDATE_VOP";
    ATTRIBUTE X_INTERFACE_INFO of dac33_vop_done   : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts CONVERTER3_VOP_DONE";
    ATTRIBUTE X_INTERFACE_INFO of dac_tile3_vop_busy : SIGNAL is "xilinx.com:interface:rfdc_vop_rts_pins_rtl:1.0 dac3_vop_rts VOP_BUSY";
    ATTRIBUTE X_INTERFACE_MODE of dac30_vop_code: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of adc00_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc0_dsa_rts CONVERTER0_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc01_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc0_dsa_rts CONVERTER1_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc02_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc0_dsa_rts CONVERTER2_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc03_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc0_dsa_rts CONVERTER3_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile0_dsa_update : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc0_dsa_rts DSA_UPDATE";
    ATTRIBUTE X_INTERFACE_MODE of adc00_dsa_code: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of adc10_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc1_dsa_rts CONVERTER0_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc11_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc1_dsa_rts CONVERTER1_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc12_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc1_dsa_rts CONVERTER2_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc13_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc1_dsa_rts CONVERTER3_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile1_dsa_update : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc1_dsa_rts DSA_UPDATE";
    ATTRIBUTE X_INTERFACE_MODE of adc10_dsa_code: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of adc20_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc2_dsa_rts CONVERTER0_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc21_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc2_dsa_rts CONVERTER1_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc22_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc2_dsa_rts CONVERTER2_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc23_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc2_dsa_rts CONVERTER3_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile2_dsa_update : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc2_dsa_rts DSA_UPDATE";
    ATTRIBUTE X_INTERFACE_MODE of adc20_dsa_code: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of adc30_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc3_dsa_rts CONVERTER0_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc31_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc3_dsa_rts CONVERTER1_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc32_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc3_dsa_rts CONVERTER2_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc33_dsa_code   : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc3_dsa_rts CONVERTER3_DSA_CODE";
    ATTRIBUTE X_INTERFACE_INFO of adc_tile3_dsa_update : SIGNAL is "xilinx.com:interface:rfdc_dsa_rts_pins_rtl:1.0 adc3_dsa_rts DSA_UPDATE";
    ATTRIBUTE X_INTERFACE_MODE of adc30_dsa_code: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of dac00_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac0_rts CONVERTER0_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac00_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac0_rts CONVERTER0_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac01_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac0_rts CONVERTER1_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac01_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac0_rts CONVERTER1_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac02_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac0_rts CONVERTER2_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac02_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac0_rts CONVERTER2_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac03_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac0_rts CONVERTER3_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac03_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac0_rts CONVERTER3_PL_EVENT";
    ATTRIBUTE X_INTERFACE_MODE of dac00_fast_shutdown: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of dac10_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac1_rts CONVERTER0_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac10_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac1_rts CONVERTER0_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac11_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac1_rts CONVERTER1_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac11_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac1_rts CONVERTER1_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac12_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac1_rts CONVERTER2_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac12_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac1_rts CONVERTER2_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac13_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac1_rts CONVERTER3_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac13_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac1_rts CONVERTER3_PL_EVENT";
    ATTRIBUTE X_INTERFACE_MODE of dac10_fast_shutdown: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of dac20_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac2_rts CONVERTER0_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac20_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac2_rts CONVERTER0_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac21_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac2_rts CONVERTER1_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac21_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac2_rts CONVERTER1_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac22_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac2_rts CONVERTER2_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac22_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac2_rts CONVERTER2_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac23_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac2_rts CONVERTER3_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac23_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac2_rts CONVERTER3_PL_EVENT";
    ATTRIBUTE X_INTERFACE_MODE of dac20_fast_shutdown: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of dac30_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac3_rts CONVERTER0_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac30_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac3_rts CONVERTER0_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac31_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac3_rts CONVERTER1_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac31_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac3_rts CONVERTER1_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac32_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac3_rts CONVERTER2_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac32_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac3_rts CONVERTER2_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of dac33_fast_shutdown : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac3_rts CONVERTER3_FAST_SHUTDOWN";
    ATTRIBUTE X_INTERFACE_INFO of dac33_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 dac3_rts CONVERTER3_PL_EVENT";
    ATTRIBUTE X_INTERFACE_MODE of dac30_fast_shutdown: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of adc00_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc0_rts CONVERTER0_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc01_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc0_rts CONVERTER1_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc02_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc0_rts CONVERTER2_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc03_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc0_rts CONVERTER3_PL_EVENT";
    ATTRIBUTE X_INTERFACE_MODE of adc00_pl_event: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of adc10_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc1_rts CONVERTER0_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc11_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc1_rts CONVERTER1_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc12_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc1_rts CONVERTER2_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc13_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc1_rts CONVERTER3_PL_EVENT";
    ATTRIBUTE X_INTERFACE_MODE of adc10_pl_event: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of adc20_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc2_rts CONVERTER0_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc21_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc2_rts CONVERTER1_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc22_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc2_rts CONVERTER2_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc23_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc2_rts CONVERTER3_PL_EVENT";
    ATTRIBUTE X_INTERFACE_MODE of adc20_pl_event: SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of adc30_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc3_rts CONVERTER0_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc31_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc3_rts CONVERTER1_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc32_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc3_rts CONVERTER2_PL_EVENT";
    ATTRIBUTE X_INTERFACE_INFO of adc33_pl_event      : SIGNAL is "xilinx.com:interface:rfdc_rts_pins_rtl:1.0 adc3_rts CONVERTER3_PL_EVENT";
    ATTRIBUTE X_INTERFACE_MODE of adc30_pl_event: SIGNAL is "Master";
    
    signal dac00_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac00_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac01_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac01_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac02_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac02_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac03_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac03_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal dac_tile0_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal dac10_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac10_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac11_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac11_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac12_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac12_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac13_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac13_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal dac_tile1_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal dac20_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac20_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac21_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac21_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac22_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac22_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac23_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac23_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal dac_tile2_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal dac30_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac30_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac31_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac31_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac32_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac32_nco_phase_reg : std_logic_vector(17 downto 0);
    signal dac33_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal dac33_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal dac_tile3_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal adc00_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc00_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc01_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc01_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc02_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc02_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc03_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc03_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal adc_tile0_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal adc10_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc10_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc11_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc11_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc12_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc12_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc13_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc13_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal adc_tile1_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal adc20_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc20_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc21_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc21_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc22_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc22_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc23_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc23_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal adc_tile2_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal adc30_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc30_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc31_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc31_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc32_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc32_nco_phase_reg : std_logic_vector(17 downto 0);
    signal adc33_nco_freq_reg  : std_logic_vector(47 downto 0);
    signal adc33_nco_phase_reg : std_logic_vector(17 downto 0);
    
    signal adc_tile3_nco_update_en_reg : std_logic_vector(23 downto 0);
    
    signal nco_update_req_reg : std_logic_vector(7 downto 0);
    signal nco_phase_rst_reg  : std_logic_vector(31 downto 0);
    signal tdd_mode_reg       : std_logic_vector(31 downto 0);

    signal dac00_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac01_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac02_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac03_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac10_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac11_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac12_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac13_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac20_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac21_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac22_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac23_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac30_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac31_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac32_vop_code_reg : std_logic_vector(9 downto 0);
    signal dac33_vop_code_reg : std_logic_vector(9 downto 0);

    signal dac_tile0_fast_shutdown_reg : std_logic_vector((3*4)-1 downto 0);
    signal dac_tile1_fast_shutdown_reg : std_logic_vector((3*4)-1 downto 0);
    signal dac_tile2_fast_shutdown_reg : std_logic_vector((3*4)-1 downto 0);
    signal dac_tile3_fast_shutdown_reg : std_logic_vector((3*4)-1 downto 0);

    signal adc_tile0_dsa_code_reg : std_logic_vector((5*4)-1 downto 0);
    signal adc_tile1_dsa_code_reg : std_logic_vector((5*4)-1 downto 0);
    signal adc_tile2_dsa_code_reg : std_logic_vector((5*4)-1 downto 0);
    signal adc_tile3_dsa_code_reg : std_logic_vector((5*4)-1 downto 0);

    signal update_vop_dsa_reg : std_logic_vector(16+4-1 downto 0);
    signal pl_event_reg       : std_logic_vector(31 downto 0);
    
    -- Pipeline registers
    signal master_bus_en_d  : std_logic;
    signal master_bus_en_dd : std_logic;
            
    signal master_bus_wr_d  : std_logic;
    signal master_bus_wr_dd : std_logic;
    
    signal master_bus_addr_d  : std_logic_vector(7 downto 0);
    signal master_bus_addr_dd : std_logic_vector(7 downto 0);
            
    signal master_bus_mosi_d  : std_logic_vector(31 downto 0);
    signal master_bus_mosi_dd : std_logic_vector(31 downto 0);
            
    signal nrst_d  : std_logic;
    signal nrst_dd : std_logic;
    
    signal zero : std_logic;
begin

    bus_delay_proc : process(master_bus_clk) begin
        if rising_edge(master_bus_clk) then
            master_bus_en_d <= master_bus_en;
            master_bus_en_dd <= master_bus_en_d;
            
            master_bus_wr_d <= master_bus_wr;
            master_bus_wr_dd <= master_bus_wr_d;
            
            master_bus_addr_d <= master_bus_addr(7 downto 0);
            master_bus_addr_dd <= master_bus_addr_d;
            
            master_bus_mosi_d <= master_bus_mosi;
            master_bus_mosi_dd <= master_bus_mosi_d;
            
            nrst_d <= nrst;
            nrst_dd <= nrst_d;
        end if;
    end process bus_delay_proc;
       
    regs_proc: process(master_bus_clk) begin
        if rising_edge(master_bus_clk) then
            if(nrst_dd = '0') then
                dac00_nco_freq_reg               <= (others => '0');
                dac00_nco_phase_reg              <= (others => '0');
                dac01_nco_freq_reg               <= (others => '0');
                dac01_nco_phase_reg              <= (others => '0');
                dac02_nco_freq_reg               <= (others => '0');
                dac02_nco_phase_reg              <= (others => '0');
                dac03_nco_freq_reg               <= (others => '0');
                dac03_nco_phase_reg              <= (others => '0');
                dac10_nco_freq_reg               <= (others => '0');
                dac10_nco_phase_reg              <= (others => '0');
                dac11_nco_freq_reg               <= (others => '0');
                dac11_nco_phase_reg              <= (others => '0');
                dac12_nco_freq_reg               <= (others => '0');
                dac12_nco_phase_reg              <= (others => '0');
                dac13_nco_freq_reg               <= (others => '0');
                dac13_nco_phase_reg              <= (others => '0');
                dac20_nco_freq_reg               <= (others => '0');
                dac20_nco_phase_reg              <= (others => '0');
                dac21_nco_freq_reg               <= (others => '0');
                dac21_nco_phase_reg              <= (others => '0');
                dac22_nco_freq_reg               <= (others => '0');
                dac22_nco_phase_reg              <= (others => '0');
                dac23_nco_freq_reg               <= (others => '0');
                dac23_nco_phase_reg              <= (others => '0');
                dac30_nco_freq_reg               <= (others => '0');
                dac30_nco_phase_reg              <= (others => '0');
                dac31_nco_freq_reg               <= (others => '0');
                dac31_nco_phase_reg              <= (others => '0');
                dac32_nco_freq_reg               <= (others => '0');
                dac32_nco_phase_reg              <= (others => '0');
                dac33_nco_freq_reg               <= (others => '0');
                dac33_nco_phase_reg              <= (others => '0');

                dac_tile0_nco_update_en_reg <= (others => '0');
                dac_tile1_nco_update_en_reg <= (others => '0');
                dac_tile2_nco_update_en_reg <= (others => '0');
                dac_tile3_nco_update_en_reg <= (others => '0');
                adc_tile0_nco_update_en_reg <= (others => '0');
                adc_tile1_nco_update_en_reg <= (others => '0');
                adc_tile2_nco_update_en_reg <= (others => '0');
                adc_tile3_nco_update_en_reg <= (others => '0');

                nco_phase_rst_reg  <= (others => '0');
                nco_update_req_reg <= (others => '0');
                tdd_mode_reg       <= (others => '0');
                
                dac00_vop_code_reg <= (others => '0');
                dac01_vop_code_reg <= (others => '0');
                dac02_vop_code_reg <= (others => '0');
                dac03_vop_code_reg <= (others => '0');
                dac10_vop_code_reg <= (others => '0');
                dac11_vop_code_reg <= (others => '0');
                dac12_vop_code_reg <= (others => '0');
                dac13_vop_code_reg <= (others => '0');
                dac20_vop_code_reg <= (others => '0');
                dac21_vop_code_reg <= (others => '0');
                dac22_vop_code_reg <= (others => '0');
                dac23_vop_code_reg <= (others => '0');
                dac30_vop_code_reg <= (others => '0');
                dac31_vop_code_reg <= (others => '0');
                dac32_vop_code_reg <= (others => '0');
                dac33_vop_code_reg <= (others => '0');

                dac_tile0_fast_shutdown_reg <= (others => '0');
                dac_tile1_fast_shutdown_reg <= (others => '0');
                dac_tile2_fast_shutdown_reg <= (others => '0');
                dac_tile3_fast_shutdown_reg <= (others => '0');

                adc_tile0_dsa_code_reg <= (others => '0');
                adc_tile1_dsa_code_reg <= (others => '0');
                adc_tile2_dsa_code_reg <= (others => '0');
                adc_tile3_dsa_code_reg <= (others => '0');

                update_vop_dsa_reg <= (others => '0');
                pl_event_reg       <= (others => '0');

                zero <= '0';

            elsif(master_bus_en_dd = '1' and master_bus_wr_dd = '1') then
                case unsigned(master_bus_addr_dd) is
                    -- Frequency registers
                    when X"00" => dac00_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"01" => dac00_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"02" => dac01_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"03" => dac01_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"04" => dac02_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"05" => dac02_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"06" => dac03_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"07" => dac03_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"08" => dac10_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"09" => dac10_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"0A" => dac11_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"0B" => dac11_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"0C" => dac12_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"0D" => dac12_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"0E" => dac13_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"0F" => dac13_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"10" => dac20_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"11" => dac20_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"12" => dac21_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"13" => dac21_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"14" => dac22_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"15" => dac22_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"16" => dac23_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"17" => dac23_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"18" => dac30_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"19" => dac30_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"1A" => dac31_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"1B" => dac31_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"1C" => dac32_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"1D" => dac32_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"1E" => dac33_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"1F" => dac33_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"20" => adc00_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"21" => adc00_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"22" => adc01_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"23" => adc01_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"24" => adc02_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"25" => adc02_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"26" => adc03_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"27" => adc03_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"28" => adc10_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"29" => adc10_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"2A" => adc11_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"2B" => adc11_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"2C" => adc12_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"2D" => adc12_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"2E" => adc13_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"2F" => adc13_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"30" => adc20_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"31" => adc20_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"32" => adc21_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"33" => adc21_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"34" => adc22_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"35" => adc22_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"36" => adc23_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"37" => adc23_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"38" => adc30_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"39" => adc30_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"3A" => adc31_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"3B" => adc31_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"3C" => adc32_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"3D" => adc32_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                    when X"3E" => adc33_nco_freq_reg(15 downto 0) <= master_bus_mosi_dd(15 downto 0);
                    when X"3F" => adc33_nco_freq_reg(47 downto 16) <= master_bus_mosi_dd;
                  
                    -- Phase registers
                    when X"40" => dac00_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"41" => dac01_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"42" => dac02_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"43" => dac03_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"44" => dac10_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"45" => dac11_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"46" => dac12_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"47" => dac13_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"48" => dac20_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"49" => dac21_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"4A" => dac22_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"4B" => dac23_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"4C" => dac30_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"4D" => dac31_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"4E" => dac32_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"4F" => dac33_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"50" => adc00_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"51" => adc01_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"52" => adc02_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"53" => adc03_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"54" => adc10_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"55" => adc11_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"56" => adc12_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"57" => adc13_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"58" => adc20_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"59" => adc21_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"5A" => adc22_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"5B" => adc23_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"5C" => adc30_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"5D" => adc31_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"5E" => adc32_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                    when X"5F" => adc33_nco_phase_reg <= master_bus_mosi_dd(17 downto 0);
                  
                    -- Update enable registers
                    when X"60" => dac_tile0_nco_update_en_reg <= master_bus_mosi_dd(23 downto 0);
                    when X"61" => dac_tile1_nco_update_en_reg <= master_bus_mosi_dd(23 downto 0);
                    when X"62" => dac_tile2_nco_update_en_reg <= master_bus_mosi_dd(23 downto 0);
                    when X"63" => dac_tile3_nco_update_en_reg <= master_bus_mosi_dd(23 downto 0);
                    when X"64" => adc_tile0_nco_update_en_reg <= master_bus_mosi_dd(23 downto 0);
                    when X"65" => adc_tile1_nco_update_en_reg <= master_bus_mosi_dd(23 downto 0);
                    when X"66" => adc_tile2_nco_update_en_reg <= master_bus_mosi_dd(23 downto 0);
                    when X"67" => adc_tile3_nco_update_en_reg <= master_bus_mosi_dd(23 downto 0);
                  
                    -- Phase reset register
                    when X"68" => nco_phase_rst_reg <= master_bus_mosi_dd;
                  
                    -- Update request register
                    when X"69" => nco_update_req_reg <= master_bus_mosi_dd(7 downto 0);
                  
                    -- TDD mode control register
                    when X"6A" => tdd_mode_reg <= master_bus_mosi_dd;
                    when X"6B" => tdd_mode_reg <= tdd_mode_reg or master_bus_mosi_dd;
                    when X"6C" => tdd_mode_reg <= tdd_mode_reg and not master_bus_mosi_dd;
                  
                    when X"6D" => update_vop_dsa_reg <= master_bus_mosi_dd(19 downto 0);
                    when X"6E" => pl_event_reg       <= master_bus_mosi_dd;

                    when X"70" => dac00_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"71" => dac01_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"72" => dac02_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"73" => dac03_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"74" => dac10_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"75" => dac11_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"76" => dac12_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"77" => dac13_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"78" => dac20_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"79" => dac21_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"7A" => dac22_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"7B" => dac23_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"7C" => dac30_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"7D" => dac31_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"7E" => dac32_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                    when X"7F" => dac33_vop_code_reg <= master_bus_mosi_dd(9 downto 0);
                  
                    when X"80" => adc_tile0_dsa_code_reg <= master_bus_mosi_dd(19 downto 0);
                    when X"81" => adc_tile1_dsa_code_reg <= master_bus_mosi_dd(19 downto 0);
                    when X"82" => adc_tile2_dsa_code_reg <= master_bus_mosi_dd(19 downto 0);
                    when X"83" => adc_tile3_dsa_code_reg <= master_bus_mosi_dd(19 downto 0);

                    when X"90" => dac_tile0_fast_shutdown_reg <= master_bus_mosi_dd(11 downto 0);
                    when X"91" => dac_tile0_fast_shutdown_reg <= dac_tile0_fast_shutdown_reg or master_bus_mosi_dd(11 downto 0);
                    when X"92" => dac_tile0_fast_shutdown_reg <= dac_tile0_fast_shutdown_reg and not master_bus_mosi_dd(11 downto 0);

                    when X"94" => dac_tile1_fast_shutdown_reg <= master_bus_mosi_dd(11 downto 0);
                    when X"95" => dac_tile1_fast_shutdown_reg <= dac_tile1_fast_shutdown_reg or master_bus_mosi_dd(11 downto 0);
                    when X"96" => dac_tile1_fast_shutdown_reg <= dac_tile1_fast_shutdown_reg and not master_bus_mosi_dd(11 downto 0);

                    when X"98" => dac_tile2_fast_shutdown_reg <= master_bus_mosi_dd(11 downto 0);
                    when X"99" => dac_tile2_fast_shutdown_reg <= dac_tile2_fast_shutdown_reg or master_bus_mosi_dd(11 downto 0);
                    when X"9A" => dac_tile2_fast_shutdown_reg <= dac_tile2_fast_shutdown_reg and not master_bus_mosi_dd(11 downto 0);

                    when X"9C" => dac_tile3_fast_shutdown_reg <= master_bus_mosi_dd(11 downto 0);
                    when X"9D" => dac_tile3_fast_shutdown_reg <= dac_tile3_fast_shutdown_reg or master_bus_mosi_dd(11 downto 0);
                    when X"9E" => dac_tile3_fast_shutdown_reg <= dac_tile3_fast_shutdown_reg and not master_bus_mosi_dd(11 downto 0);
                    
                    when others => zero <= '0';
                end case;
            end if;
        end if;
    end process regs_proc;

    xpm_cdc_array_single_dac_nco_freq : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48*16
        )
        port map (
            src_clk                => master_bus_clk, 
            dest_clk               => nco_dest_clk,
            
            src_in(47 downto 0)    => dac00_nco_freq_reg,
            src_in(95 downto 48)   => dac01_nco_freq_reg,
            src_in(143 downto 96)  => dac02_nco_freq_reg,
            src_in(191 downto 144) => dac03_nco_freq_reg,
            src_in(239 downto 192) => dac10_nco_freq_reg,
            src_in(287 downto 240) => dac11_nco_freq_reg,
            src_in(335 downto 288) => dac12_nco_freq_reg,
            src_in(383 downto 336) => dac13_nco_freq_reg,
            src_in(431 downto 384) => dac20_nco_freq_reg,
            src_in(479 downto 432) => dac21_nco_freq_reg,
            src_in(527 downto 480) => dac22_nco_freq_reg,
            src_in(575 downto 528) => dac23_nco_freq_reg,
            src_in(623 downto 576) => dac30_nco_freq_reg,
            src_in(671 downto 624) => dac31_nco_freq_reg,
            src_in(719 downto 672) => dac32_nco_freq_reg,
            src_in(767 downto 720) => dac33_nco_freq_reg,
            
            dest_out(47 downto 0)    => dac00_nco_freq,
            dest_out(95 downto 48)   => dac01_nco_freq,
            dest_out(143 downto 96)  => dac02_nco_freq,
            dest_out(191 downto 144) => dac03_nco_freq,
            dest_out(239 downto 192) => dac10_nco_freq,
            dest_out(287 downto 240) => dac11_nco_freq,
            dest_out(335 downto 288) => dac12_nco_freq,
            dest_out(383 downto 336) => dac13_nco_freq,
            dest_out(431 downto 384) => dac20_nco_freq,
            dest_out(479 downto 432) => dac21_nco_freq,
            dest_out(527 downto 480) => dac22_nco_freq,
            dest_out(575 downto 528) => dac23_nco_freq,
            dest_out(623 downto 576) => dac30_nco_freq,
            dest_out(671 downto 624) => dac31_nco_freq,
            dest_out(719 downto 672) => dac32_nco_freq,
            dest_out(767 downto 720) => dac33_nco_freq
        );
    
                  
    xpm_cdc_array_single_adc_nco_freq : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 48*16
        )
        port map (
            src_clk                => master_bus_clk, 
            dest_clk               => nco_dest_clk,
            
            src_in(47 downto 0)    => adc00_nco_freq_reg,
            src_in(95 downto 48)   => adc01_nco_freq_reg,
            src_in(143 downto 96)  => adc02_nco_freq_reg,
            src_in(191 downto 144) => adc03_nco_freq_reg,
            src_in(239 downto 192) => adc10_nco_freq_reg,
            src_in(287 downto 240) => adc11_nco_freq_reg,
            src_in(335 downto 288) => adc12_nco_freq_reg,
            src_in(383 downto 336) => adc13_nco_freq_reg,
            src_in(431 downto 384) => adc20_nco_freq_reg,
            src_in(479 downto 432) => adc21_nco_freq_reg,
            src_in(527 downto 480) => adc22_nco_freq_reg,
            src_in(575 downto 528) => adc23_nco_freq_reg,
            src_in(623 downto 576) => adc30_nco_freq_reg,
            src_in(671 downto 624) => adc31_nco_freq_reg,
            src_in(719 downto 672) => adc32_nco_freq_reg,
            src_in(767 downto 720) => adc33_nco_freq_reg,
            
            dest_out(47 downto 0)    => adc00_nco_freq,
            dest_out(95 downto 48)   => adc01_nco_freq,
            dest_out(143 downto 96)  => adc02_nco_freq,
            dest_out(191 downto 144) => adc03_nco_freq,
            dest_out(239 downto 192) => adc10_nco_freq,
            dest_out(287 downto 240) => adc11_nco_freq,
            dest_out(335 downto 288) => adc12_nco_freq,
            dest_out(383 downto 336) => adc13_nco_freq,
            dest_out(431 downto 384) => adc20_nco_freq,
            dest_out(479 downto 432) => adc21_nco_freq,
            dest_out(527 downto 480) => adc22_nco_freq,
            dest_out(575 downto 528) => adc23_nco_freq,
            dest_out(623 downto 576) => adc30_nco_freq,
            dest_out(671 downto 624) => adc31_nco_freq,
            dest_out(719 downto 672) => adc32_nco_freq,
            dest_out(767 downto 720) => adc33_nco_freq
        );

    xpm_cdc_array_single_nco_phase : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 18*32
        )
        port map (
            src_clk                => master_bus_clk,  
            dest_clk               => nco_dest_clk,
            
            src_in(17 downto 0)    => dac00_nco_phase_reg,
            src_in(35 downto 18)   => dac01_nco_phase_reg,
            src_in(53 downto 36)   => dac02_nco_phase_reg,
            src_in(71 downto 54)   => dac03_nco_phase_reg,
            src_in(89 downto 72)   => dac10_nco_phase_reg,
            src_in(107 downto 90)  => dac11_nco_phase_reg,
            src_in(125 downto 108) => dac12_nco_phase_reg,
            src_in(143 downto 126) => dac13_nco_phase_reg,
            src_in(161 downto 144) => dac20_nco_phase_reg,
            src_in(179 downto 162) => dac21_nco_phase_reg,
            src_in(197 downto 180) => dac22_nco_phase_reg,
            src_in(215 downto 198) => dac23_nco_phase_reg,
            src_in(233 downto 216) => dac30_nco_phase_reg,
            src_in(251 downto 234) => dac31_nco_phase_reg,
            src_in(269 downto 252) => dac32_nco_phase_reg,
            src_in(287 downto 270) => dac33_nco_phase_reg,
            src_in(305 downto 288) => adc00_nco_phase_reg,
            src_in(323 downto 306) => adc01_nco_phase_reg,
            src_in(341 downto 324) => adc02_nco_phase_reg,
            src_in(359 downto 342) => adc03_nco_phase_reg,
            src_in(377 downto 360) => adc10_nco_phase_reg,
            src_in(395 downto 378) => adc11_nco_phase_reg,
            src_in(413 downto 396) => adc12_nco_phase_reg,
            src_in(431 downto 414) => adc13_nco_phase_reg,
            src_in(449 downto 432) => adc20_nco_phase_reg,
            src_in(467 downto 450) => adc21_nco_phase_reg,
            src_in(485 downto 468) => adc22_nco_phase_reg,
            src_in(503 downto 486) => adc23_nco_phase_reg,
            src_in(521 downto 504) => adc30_nco_phase_reg,
            src_in(539 downto 522) => adc31_nco_phase_reg,
            src_in(557 downto 540) => adc32_nco_phase_reg,
            src_in(575 downto 558) => adc33_nco_phase_reg,
            
            dest_out(17 downto 0)    => dac00_nco_phase,
            dest_out(35 downto 18)   => dac01_nco_phase,
            dest_out(53 downto 36)   => dac02_nco_phase,
            dest_out(71 downto 54)   => dac03_nco_phase,
            dest_out(89 downto 72)   => dac10_nco_phase,
            dest_out(107 downto 90)  => dac11_nco_phase,
            dest_out(125 downto 108) => dac12_nco_phase,
            dest_out(143 downto 126) => dac13_nco_phase,
            dest_out(161 downto 144) => dac20_nco_phase,
            dest_out(179 downto 162) => dac21_nco_phase,
            dest_out(197 downto 180) => dac22_nco_phase,
            dest_out(215 downto 198) => dac23_nco_phase,
            dest_out(233 downto 216) => dac30_nco_phase,
            dest_out(251 downto 234) => dac31_nco_phase,
            dest_out(269 downto 252) => dac32_nco_phase,
            dest_out(287 downto 270) => dac33_nco_phase,
            dest_out(305 downto 288) => adc00_nco_phase,
            dest_out(323 downto 306) => adc01_nco_phase,
            dest_out(341 downto 324) => adc02_nco_phase,
            dest_out(359 downto 342) => adc03_nco_phase,
            dest_out(377 downto 360) => adc10_nco_phase,
            dest_out(395 downto 378) => adc11_nco_phase,
            dest_out(413 downto 396) => adc12_nco_phase,
            dest_out(431 downto 414) => adc13_nco_phase,
            dest_out(449 downto 432) => adc20_nco_phase,
            dest_out(467 downto 450) => adc21_nco_phase,
            dest_out(485 downto 468) => adc22_nco_phase,
            dest_out(503 downto 486) => adc23_nco_phase,
            dest_out(521 downto 504) => adc30_nco_phase,
            dest_out(539 downto 522) => adc31_nco_phase,
            dest_out(557 downto 540) => adc32_nco_phase,
            dest_out(575 downto 558) => adc33_nco_phase
        );

    xpm_cdc_array_single_nco_update_en : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 24*8
        )
        port map (
            src_clk                  => master_bus_clk,  
            dest_clk                 => nco_dest_clk,
            
            src_in(23 downto 0)      => dac_tile0_nco_update_en_reg,
            src_in(47 downto 24)     => dac_tile1_nco_update_en_reg,
            src_in(71 downto 48)     => dac_tile2_nco_update_en_reg,
            src_in(95 downto 72)     => dac_tile3_nco_update_en_reg,
            src_in(119 downto 96)    => adc_tile0_nco_update_en_reg,
            src_in(143 downto 120)   => adc_tile1_nco_update_en_reg,
            src_in(167 downto 144)   => adc_tile2_nco_update_en_reg,
            src_in(191 downto 168)   => adc_tile3_nco_update_en_reg,
            
            dest_out(5 downto 0) => dac00_nco_update_en,
            dest_out(11 downto 6) => dac01_nco_update_en,
            dest_out(17 downto 12) => dac02_nco_update_en,
            dest_out(23 downto 18) => dac03_nco_update_en,
            dest_out(29 downto 24) => dac10_nco_update_en,
            dest_out(35 downto 30) => dac11_nco_update_en,
            dest_out(41 downto 36) => dac12_nco_update_en,
            dest_out(47 downto 42) => dac13_nco_update_en,
            dest_out(53 downto 48) => dac20_nco_update_en,
            dest_out(59 downto 54) => dac21_nco_update_en,
            dest_out(65 downto 60) => dac22_nco_update_en,
            dest_out(71 downto 66) => dac23_nco_update_en,
            dest_out(77 downto 72) => dac30_nco_update_en,
            dest_out(83 downto 78) => dac31_nco_update_en,
            dest_out(89 downto 84) => dac32_nco_update_en,
            dest_out(95 downto 90) => dac33_nco_update_en,
            dest_out(101 downto 96) => adc00_nco_update_en,
            dest_out(107 downto 102) => adc01_nco_update_en,
            dest_out(113 downto 108) => adc02_nco_update_en,
            dest_out(119 downto 114) => adc03_nco_update_en,
            dest_out(125 downto 120) => adc10_nco_update_en,
            dest_out(131 downto 126) => adc11_nco_update_en,
            dest_out(137 downto 132) => adc12_nco_update_en,
            dest_out(143 downto 138) => adc13_nco_update_en,
            dest_out(149 downto 144) => adc20_nco_update_en,
            dest_out(155 downto 150) => adc21_nco_update_en,
            dest_out(161 downto 156) => adc22_nco_update_en,
            dest_out(167 downto 162) => adc23_nco_update_en,
            dest_out(173 downto 168) => adc30_nco_update_en,
            dest_out(179 downto 174) => adc31_nco_update_en,
            dest_out(185 downto 180) => adc32_nco_update_en,
            dest_out(191 downto 186) => adc33_nco_update_en
        );

    xpm_cdc_array_single_nco_phase_rst : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 32
        )
        port map (
            src_clk      => master_bus_clk,  
            dest_clk     => nco_dest_clk,
            
            src_in       => nco_phase_rst_reg,
            
            dest_out(0)  => dac00_nco_phase_rst,
            dest_out(1)  => dac01_nco_phase_rst,
            dest_out(2)  => dac02_nco_phase_rst,
            dest_out(3)  => dac03_nco_phase_rst,
            dest_out(4)  => dac10_nco_phase_rst,
            dest_out(5)  => dac11_nco_phase_rst,
            dest_out(6)  => dac12_nco_phase_rst,
            dest_out(7)  => dac13_nco_phase_rst,
            dest_out(8)  => dac20_nco_phase_rst,
            dest_out(9)  => dac21_nco_phase_rst,
            dest_out(10) => dac22_nco_phase_rst,
            dest_out(11) => dac23_nco_phase_rst,
            dest_out(12) => dac30_nco_phase_rst,
            dest_out(13) => dac31_nco_phase_rst,
            dest_out(14) => dac32_nco_phase_rst,
            dest_out(15) => dac33_nco_phase_rst,
            dest_out(16) => adc00_nco_phase_rst,
            dest_out(17) => adc01_nco_phase_rst,
            dest_out(18) => adc02_nco_phase_rst,
            dest_out(19) => adc03_nco_phase_rst,
            dest_out(20) => adc10_nco_phase_rst,
            dest_out(21) => adc11_nco_phase_rst,
            dest_out(22) => adc12_nco_phase_rst,
            dest_out(23) => adc13_nco_phase_rst,
            dest_out(24) => adc20_nco_phase_rst,
            dest_out(25) => adc21_nco_phase_rst,
            dest_out(26) => adc22_nco_phase_rst,
            dest_out(27) => adc23_nco_phase_rst,
            dest_out(28) => adc30_nco_phase_rst,
            dest_out(29) => adc31_nco_phase_rst,
            dest_out(30) => adc32_nco_phase_rst,
            dest_out(31) => adc33_nco_phase_rst
        );
                  
    xpm_cdc_array_single_tdd_mode : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 32
        )
        port map (
            src_clk      => master_bus_clk,  
            dest_clk     => nco_dest_clk,
            
            src_in       => tdd_mode_reg,
            
            dest_out(0)  => dac00_tdd_mode,
            dest_out(1)  => dac01_tdd_mode,
            dest_out(2)  => dac02_tdd_mode,
            dest_out(3)  => dac03_tdd_mode,
            dest_out(4)  => dac10_tdd_mode,
            dest_out(5)  => dac11_tdd_mode,
            dest_out(6)  => dac12_tdd_mode,
            dest_out(7)  => dac13_tdd_mode,
            dest_out(8)  => dac20_tdd_mode,
            dest_out(9)  => dac21_tdd_mode,
            dest_out(10) => dac22_tdd_mode,
            dest_out(11) => dac23_tdd_mode,
            dest_out(12) => dac30_tdd_mode,
            dest_out(13) => dac31_tdd_mode,
            dest_out(14) => dac32_tdd_mode,
            dest_out(15) => dac33_tdd_mode,
            dest_out(16) => adc00_tdd_mode,
            dest_out(17) => adc01_tdd_mode,
            dest_out(18) => adc02_tdd_mode,
            dest_out(19) => adc03_tdd_mode,
            dest_out(20) => adc10_tdd_mode,
            dest_out(21) => adc11_tdd_mode,
            dest_out(22) => adc12_tdd_mode,
            dest_out(23) => adc13_tdd_mode,
            dest_out(24) => adc20_tdd_mode,
            dest_out(25) => adc21_tdd_mode,
            dest_out(26) => adc22_tdd_mode,
            dest_out(27) => adc23_tdd_mode,
            dest_out(28) => adc30_tdd_mode,
            dest_out(29) => adc31_tdd_mode,
            dest_out(30) => adc32_tdd_mode,
            dest_out(31) => adc33_tdd_mode
        );
                  
    xpm_cdc_array_single_nco_update_req : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 8
        )
        port map (
            src_clk     => master_bus_clk,  
            dest_clk    => nco_dest_clk,
            
            src_in      => nco_update_req_reg,
            
            dest_out(0) => dac_tile0_nco_update_req,
            dest_out(1) => dac_tile1_nco_update_req,
            dest_out(2) => dac_tile2_nco_update_req,
            dest_out(3) => dac_tile3_nco_update_req,
            dest_out(4) => adc_tile0_nco_update_req,
            dest_out(5) => adc_tile1_nco_update_req,
            dest_out(6) => adc_tile2_nco_update_req,
            dest_out(7) => adc_tile3_nco_update_req
        );
                  
    xpm_cdc_array_single_dac_vop_code : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 10*16
        )
        port map (
            src_clk     => master_bus_clk,  
            dest_clk    => nco_dest_clk,
            
            src_in(9 downto 0)     => dac00_vop_code_reg,
            src_in(19 downto 10)   => dac01_vop_code_reg,
            src_in(29 downto 20)   => dac02_vop_code_reg,
            src_in(39 downto 30)   => dac03_vop_code_reg,
            src_in(49 downto 40)   => dac10_vop_code_reg,
            src_in(59 downto 50)   => dac11_vop_code_reg,
            src_in(69 downto 60)   => dac12_vop_code_reg,
            src_in(79 downto 70)   => dac13_vop_code_reg,
            src_in(89 downto 80)   => dac20_vop_code_reg,
            src_in(99 downto 90)   => dac21_vop_code_reg,
            src_in(109 downto 100) => dac22_vop_code_reg,
            src_in(119 downto 110) => dac23_vop_code_reg,
            src_in(129 downto 120) => dac30_vop_code_reg,
            src_in(139 downto 130) => dac31_vop_code_reg,
            src_in(149 downto 140) => dac32_vop_code_reg,
            src_in(159 downto 150) => dac33_vop_code_reg,
            
            dest_out(9 downto 0)     => dac00_vop_code,
            dest_out(19 downto 10)   => dac01_vop_code,
            dest_out(29 downto 20)   => dac02_vop_code,
            dest_out(39 downto 30)   => dac03_vop_code,
            dest_out(49 downto 40)   => dac10_vop_code,
            dest_out(59 downto 50)   => dac11_vop_code,
            dest_out(69 downto 60)   => dac12_vop_code,
            dest_out(79 downto 70)   => dac13_vop_code,
            dest_out(89 downto 80)   => dac20_vop_code,
            dest_out(99 downto 90)   => dac21_vop_code,
            dest_out(109 downto 100) => dac22_vop_code,
            dest_out(119 downto 110) => dac23_vop_code,
            dest_out(129 downto 120) => dac30_vop_code,
            dest_out(139 downto 130) => dac31_vop_code,
            dest_out(149 downto 140) => dac32_vop_code,
            dest_out(159 downto 150) => dac33_vop_code
        );
                  
    xpm_cdc_array_single_dsa_code : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 16*5
        )
        port map (
            src_clk     => master_bus_clk,  
            dest_clk    => nco_dest_clk,
            
            src_in(19 downto 0)    => adc_tile0_dsa_code_reg,
            src_in(39 downto 20)   => adc_tile1_dsa_code_reg,
            src_in(59 downto 40)   => adc_tile2_dsa_code_reg,
            src_in(79 downto 60)   => adc_tile3_dsa_code_reg,
            
            dest_out(4 downto 0)   => adc00_dsa_code,
            dest_out(9 downto 5)   => adc01_dsa_code,
            dest_out(14 downto 10) => adc02_dsa_code,
            dest_out(19 downto 15) => adc03_dsa_code,
            dest_out(24 downto 20) => adc10_dsa_code,
            dest_out(29 downto 25) => adc11_dsa_code,
            dest_out(34 downto 30) => adc12_dsa_code,
            dest_out(39 downto 35) => adc13_dsa_code,
            dest_out(44 downto 40) => adc20_dsa_code,
            dest_out(49 downto 45) => adc21_dsa_code,
            dest_out(54 downto 50) => adc22_dsa_code,
            dest_out(59 downto 55) => adc23_dsa_code,
            dest_out(64 downto 60) => adc30_dsa_code,
            dest_out(69 downto 65) => adc31_dsa_code,
            dest_out(74 downto 70) => adc32_dsa_code,
            dest_out(79 downto 75) => adc33_dsa_code
        );
                  
    xpm_cdc_array_single_update_vop_dsa : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 16 + 4
        )
        port map (
            src_clk     => master_bus_clk,  
            dest_clk    => nco_dest_clk,
            
            src_in       => update_vop_dsa_reg,
            
            dest_out(0)  => dac00_update_vop,
            dest_out(1)  => dac01_update_vop,
            dest_out(2)  => dac02_update_vop,
            dest_out(3)  => dac03_update_vop,
            dest_out(4)  => dac10_update_vop,
            dest_out(5)  => dac11_update_vop,
            dest_out(6)  => dac12_update_vop,
            dest_out(7)  => dac13_update_vop,
            dest_out(8)  => dac20_update_vop,
            dest_out(9)  => dac21_update_vop,
            dest_out(10) => dac22_update_vop,
            dest_out(11) => dac23_update_vop,
            dest_out(12) => dac30_update_vop,
            dest_out(13) => dac31_update_vop,
            dest_out(14) => dac32_update_vop,
            dest_out(15) => dac33_update_vop,
            dest_out(16) => adc_tile0_dsa_update,
            dest_out(17) => adc_tile1_dsa_update,
            dest_out(18) => adc_tile2_dsa_update,
            dest_out(19) => adc_tile3_dsa_update
        );
                  
    xpm_cdc_array_dac_fast_shutdown : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 16*3
        )
        port map (
            src_clk     => master_bus_clk,  
            dest_clk    => nco_dest_clk,
            
            src_in(11 downto 0)    => dac_tile0_fast_shutdown_reg,
            src_in(23 downto 12)   => dac_tile1_fast_shutdown_reg,
            src_in(35 downto 24)   => dac_tile2_fast_shutdown_reg,
            src_in(47 downto 36)   => dac_tile3_fast_shutdown_reg,
            
            dest_out(2 downto 0)   => dac00_fast_shutdown,
            dest_out(5 downto 3)   => dac01_fast_shutdown,
            dest_out(8 downto 6)   => dac02_fast_shutdown,
            dest_out(11 downto 9)  => dac03_fast_shutdown,
            dest_out(14 downto 12) => dac10_fast_shutdown,
            dest_out(17 downto 15) => dac11_fast_shutdown,
            dest_out(20 downto 18) => dac12_fast_shutdown,
            dest_out(23 downto 21) => dac13_fast_shutdown,
            dest_out(26 downto 24) => dac20_fast_shutdown,
            dest_out(29 downto 27) => dac21_fast_shutdown,
            dest_out(32 downto 30) => dac22_fast_shutdown,
            dest_out(35 downto 33) => dac23_fast_shutdown,
            dest_out(38 downto 36) => dac30_fast_shutdown,
            dest_out(41 downto 39) => dac31_fast_shutdown,
            dest_out(44 downto 42) => dac32_fast_shutdown,
            dest_out(47 downto 45) => dac33_fast_shutdown
        );
                  
    xpm_cdc_array_single_pl_event : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 32
        )
        port map (
            src_clk      => master_bus_clk,  
            dest_clk     => nco_dest_clk,
            
            src_in       => pl_event_reg,
            
            dest_out(0)  => dac00_pl_event,
            dest_out(1)  => dac01_pl_event,
            dest_out(2)  => dac02_pl_event,
            dest_out(3)  => dac03_pl_event,
            dest_out(4)  => dac10_pl_event,
            dest_out(5)  => dac11_pl_event,
            dest_out(6)  => dac12_pl_event,
            dest_out(7)  => dac13_pl_event,
            dest_out(8)  => dac20_pl_event,
            dest_out(9)  => dac21_pl_event,
            dest_out(10) => dac22_pl_event,
            dest_out(11) => dac23_pl_event,
            dest_out(12) => dac30_pl_event,
            dest_out(13) => dac31_pl_event,
            dest_out(14) => dac32_pl_event,
            dest_out(15) => dac33_pl_event,
            dest_out(16) => adc00_pl_event,
            dest_out(17) => adc01_pl_event,
            dest_out(18) => adc02_pl_event,
            dest_out(19) => adc03_pl_event,
            dest_out(20) => adc10_pl_event,
            dest_out(21) => adc11_pl_event,
            dest_out(22) => adc12_pl_event,
            dest_out(23) => adc13_pl_event,
            dest_out(24) => adc20_pl_event,
            dest_out(25) => adc21_pl_event,
            dest_out(26) => adc22_pl_event,
            dest_out(27) => adc23_pl_event,
            dest_out(28) => adc30_pl_event,
            dest_out(29) => adc31_pl_event,
            dest_out(30) => adc32_pl_event,
            dest_out(31) => adc33_pl_event
        );
                  
    xpm_cdc_array_single_master_bus_miso : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 3,
            INIT_SYNC_FF   => 0,
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1,
            WIDTH          => 32
        )
        port map (
            src_clk     => nco_dest_clk,  
            dest_clk    => master_bus_clk,
            
            src_in(1 downto 0)   => dac_tile0_nco_update_busy,
            src_in(3 downto 2)   => dac_tile1_nco_update_busy,
            src_in(5 downto 4)   => dac_tile2_nco_update_busy,
            src_in(7 downto 6)   => dac_tile3_nco_update_busy,
            src_in(9 downto 8)   => adc_tile0_nco_update_busy,
            src_in(11 downto 10) => adc_tile1_nco_update_busy,
            src_in(13 downto 12) => adc_tile2_nco_update_busy,
            src_in(15 downto 14) => adc_tile3_nco_update_busy,
            src_in(16)           => dac_tile0_vop_busy,
            src_in(17)           => dac_tile1_vop_busy,
            src_in(18)           => dac_tile2_vop_busy,
            src_in(19)           => dac_tile3_vop_busy,
            src_in(31 downto 20) => "000000000000",
            
            dest_out => master_bus_miso
        );
                
end rtl;
