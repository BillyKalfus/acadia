----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 10/28/2022 10:04:09 PM
-- Design Name: 
-- Module Name: bram_write_pipeline - rtl
-- Project Name: 
-- Target Devices: 
-- Tool Versions: 
-- Description: 
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

entity bram_write_pipeline is
    generic (
        DATA_WIDTH : natural := 32;
        ADDR_WIDTH : natural := 32
    );
    port (
        master_din  : in  std_logic_vector(DATA_WIDTH-1 downto 0);
        master_addr : in  std_logic_vector(ADDR_WIDTH-1 downto 0);
        master_wr   : in  std_logic;
        master_en   : in  std_logic;
        master_clk  : in  std_logic;
        
        slave_din  : out std_logic_vector(DATA_WIDTH-1 downto 0);
        slave_addr : out std_logic_vector(ADDR_WIDTH-1 downto 0);
        slave_wr   : out std_logic;
        slave_en   : out std_logic;
        slave_clk  : out std_logic
    );
end bram_write_pipeline;

architecture rtl of bram_write_pipeline is

    ATTRIBUTE X_INTERFACE_INFO : STRING;    
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of master_din:  SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_wr:   SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master WE";
    ATTRIBUTE X_INTERFACE_INFO of master_en:   SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master EN";
    ATTRIBUTE X_INTERFACE_INFO of master_addr: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_clk:  SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master CLK";
    
    ATTRIBUTE X_INTERFACE_INFO of slave_din:  SIGNAL is "xilinx.com:interface:bram_rtl:1.0 slave DIN";
    ATTRIBUTE X_INTERFACE_INFO of slave_wr:   SIGNAL is "xilinx.com:interface:bram_rtl:1.0 slave WE";
    ATTRIBUTE X_INTERFACE_INFO of slave_en:   SIGNAL is "xilinx.com:interface:bram_rtl:1.0 slave EN";
    ATTRIBUTE X_INTERFACE_INFO of slave_addr: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 slave ADDR";
    ATTRIBUTE X_INTERFACE_INFO of slave_clk:  SIGNAL is "xilinx.com:interface:bram_rtl:1.0 slave CLK";
    ATTRIBUTE X_INTERFACE_MODE of slave_din:  SIGNAL is "Master";

begin

    slave_clk <= master_clk;

    delay_proc : process(master_clk) begin
        if rising_edge(master_clk) then
            slave_din  <= master_din;
            slave_addr <= master_addr;
            slave_wr   <= master_wr;
            slave_en   <= master_en;
        end if;
    end process delay_proc;


end rtl;
