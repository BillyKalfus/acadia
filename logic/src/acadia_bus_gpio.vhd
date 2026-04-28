----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/27/2024 03:36:24 PM
-- Design Name: acadia
-- Module Name: acadia_clocking - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 
-- Description: 
--    Module for configuring and routing clocks.
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

entity acadia_bus_gpio is
    port (
        clk                 : in  std_logic;
        nrst                : in  std_logic;

        master_bus_mosi : in  std_logic_vector(31 downto 0);
        master_bus_miso : out std_logic_vector(31 downto 0);
        master_bus_addr : in  std_logic_vector(31 downto 0);
        master_bus_we   : in  std_logic;
        master_bus_en   : in  std_logic;

        gpio_i : in  std_logic_vector(31 downto 0);
        gpio_o : out std_logic_vector(31 downto 0);
        gpio_t : out std_logic_vector(31 downto 0)
    );

end acadia_bus_gpio;

architecture rtl of acadia_bus_gpio is 
     
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_INFO of gpio_i : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 gpio TRI_I";
    ATTRIBUTE X_INTERFACE_INFO of gpio_o : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 gpio TRI_O";
    ATTRIBUTE X_INTERFACE_INFO of gpio_t : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 gpio TRI_T";
    ATTRIBUTE X_INTERFACE_MODE of gpio_i : SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_we  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus EN";
    ATTRIBUTE X_INTERFACE_MODE of master_bus_mosi : SIGNAL is "Slave";

    signal gpio_o_int : std_logic_vector(31 downto 0);
    signal gpio_t_int : std_logic_vector(31 downto 0);

begin    

    gpio_o <= gpio_o_int;
    gpio_t <= gpio_t_int;
    
    reg_wr_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                gpio_o_int <= (others => '0');
                gpio_t_int <= (others => '1');
            elsif(master_bus_en = '1' and master_bus_we = '1') then
                if(master_bus_addr(1 downto 0) = "00") then
                    gpio_t_int <= master_bus_mosi;
                elsif(master_bus_addr(1 downto 0) = "01") then
                    gpio_o_int <= master_bus_mosi;
                end if;
            end if;
        end if;
    end process reg_wr_proc;

    reg_rd_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                master_bus_miso <= (others => '0');
            elsif(master_bus_addr(1 downto 0) = "00") then
                master_bus_miso <= gpio_t_int;
            elsif(master_bus_addr(1 downto 0) = "01") then
                master_bus_miso <= gpio_o_int;
            elsif(master_bus_addr(1 downto 0) = "10") then
                master_bus_miso <= gpio_i;
            end if;
        end if;
    end process reg_rd_proc;

end rtl;
