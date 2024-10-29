----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/27/2024 03:36:24 PM
-- Design Name: acadia
-- Module Name: acadia_spi_io - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 
-- Description: Module for adapting Zynq SPI port to physical bins with tristate buffers.
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

library UNISIM;
use UNISIM.vcomponents.all;

entity acadia_spi_io is
    port (
        zynq_spi_sck_i: out std_logic;
        zynq_spi_sck_o: in std_logic;
        zynq_spi_sck_t: in std_logic;

        zynq_spi_m_i: out std_logic;
        zynq_spi_m_o: in std_logic;
        zynq_spi_mo_t: in std_logic;
        zynq_spi_s_i: out std_logic;
        zynq_spi_s_o: in std_logic;
        zynq_spi_so_t: in std_logic;

        zynq_spi_ssn_i: out std_logic;
        zynq_spi_ssn_o: in std_logic;
        zynq_spi_ss1n_o: in std_logic;
        zynq_spi_ssn_t: in std_logic;

        spi_sck  : inout std_logic;
        spi_mosi : inout std_logic;
        spi_miso : inout std_logic;
        spi_ss   : inout std_logic;
        spi_ss1  : inout std_logic
    );

end acadia_spi_io;

architecture rtl of acadia_spi_io is 
     
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_sck_i : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi SCK_I";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_sck_o : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi SCK_O";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_sck_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi SCK_T";

    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_m_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi IO0_I";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_m_o  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi IO0_O";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_mo_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi IO0_T";

    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_s_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi IO1_I";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_s_o  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi IO1_O";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_so_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi IO1_T";

    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_ssn_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi SS_I";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_ssn_o : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi SS_O";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_ss1n_o : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi SS1_O";
    ATTRIBUTE X_INTERFACE_INFO of zynq_spi_ssn_t  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 zynq_spi SS_T";
    
    ATTRIBUTE X_INTERFACE_MODE of zynq_spi_sck_i : SIGNAL is "Slave";
    
begin    
    
    sck_buf_inst: IOBUF
        port map (
            O => zynq_spi_sck_i,
            I => zynq_spi_sck_o,
            T => zynq_spi_sck_t,
            IO => spi_sck
        );

    mosi_buf_inst: IOBUF
        port map (
            O => zynq_spi_s_i,
            I => zynq_spi_m_o,
            T => zynq_spi_mo_t,
            IO => spi_mosi
        );

    miso_buf_inst: IOBUF
        port map (
            O => zynq_spi_m_i,
            I => zynq_spi_s_o,
            T => zynq_spi_so_t,
            IO => spi_miso
        );

    ss_buf_inst: IOBUF
        port map (
            O => zynq_spi_ssn_i,
            I => zynq_spi_ssn_o,
            T => zynq_spi_ssn_t,
            IO => spi_ss
        );

    ss1_buf_inst: OBUFT
        port map (
            I => zynq_spi_ss1n_o,
            T => zynq_spi_ssn_t,
            O => spi_ss1
        );
    
end rtl;
