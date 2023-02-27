----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/28/2022 10:04:09 PM
-- Design Name: acadia
-- Module Name: acadia_zdma_controller - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
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
use IEEE.NUMERIC_STD.ALL;

entity acadia_zdma_controller is
    generic (
        DATA_WIDTH    : natural := 32;
        ADDR_WIDTH    : natural := 32;
        NUM_DMA       : natural := 16;
        COUNTER_WIDTH : natural := 5
    );
    port (
        nrst            : in std_logic;
        
        master_bus_din  : out  std_logic_vector(DATA_WIDTH-1 downto 0);
        master_bus_dout : in  std_logic_vector(DATA_WIDTH-1 downto 0);
        master_bus_addr : in  std_logic_vector(ADDR_WIDTH-1 downto 0);
        master_bus_wr   : in  std_logic;
        master_bus_en   : in  std_logic;
        master_bus_clk  : in  std_logic;
        
        cvld            : out std_logic_vector(NUM_DMA-1 downto 0);
        cack            : in  std_logic_vector(NUM_DMA-1 downto 0);
        tvld            : in  std_logic_vector(NUM_DMA-1 downto 0);
        tack            : out std_logic_vector(NUM_DMA-1 downto 0)
    );
end acadia_zdma_controller;

architecture rtl of acadia_zdma_controller is

    ATTRIBUTE X_INTERFACE_INFO : STRING;    
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of master_bus_din:  SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_dout: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_wr:   SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_en:   SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus EN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_clk:  SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus CLK";

    type counter_array_t is array (natural range <>) of unsigned(COUNTER_WIDTH-1 downto 0);
    signal cack_count : counter_array_t(NUM_DMA-1 downto 0);
    signal tvld_count : counter_array_t(NUM_DMA-1 downto 0);
                                   
    signal cvld_int : std_logic_vector(NUM_DMA-1 downto 0);
begin

    cvld <= cvld_int;
                                   
    credit_proc: process(master_bus_clk) begin
        if rising_edge(master_bus_clk) then
            credit_loop: for i in 0 to NUM_DMA-1 loop
                if(nrst = '0') then
                    cvld_int(i) <= '0';
                    cack_count(i) <= (others => '0');
                elsif((master_bus_wr 
                          and master_bus_en 
                          and master_bus_dout(i)) = '1') then
                    if(master_bus_addr(1 downto 0) = "00") then
                        cvld_int(i) <= '1';
                    elsif(master_bus_addr(1 downto 0) = "01") then
                        cack_count(i) <= (others => '0');           
                    end if;
                elsif(cack(i) = '1') then
                    cvld_int(i) <= '0';
                    cack_count(i) <= cack_count(i) + 1;
                end if;
            end loop credit_loop;
        end if;
    end process credit_proc;
                                   
    tvld_proc: process(master_bus_clk) begin
        if rising_edge(master_bus_clk) then
            tvld_loop: for i in 0 to NUM_DMA-1 loop
                if(nrst = '0') then
                    tvld_count(i) <= (others => '0');
                elsif((master_bus_wr 
                          and master_bus_en 
                          and master_bus_dout(i)) = '1'
                          and master_bus_addr(1 downto 0) = "10") then
                    tvld_count(i) <= (others => '0');  
                elsif(tvld(i) = '1') then
                    tvld_count(i) <= tvld_count(i) + 1;
                end if;
            end loop tvld_loop;
        end if;
    end process tvld_proc;
                                   
    tack_proc: process(master_bus_clk) begin
        if rising_edge(master_bus_clk) then
            tack_loop: for i in 0 to NUM_DMA-1 loop
                if(nrst = '0') then
                    tack(i) <= '0';             
                elsif(tvld(i) = '1') then
                    tack(i) <= '1';
                else
                    tack(i) <= '0';
                end if;
            end loop tack_loop;
        end if;
    end process tack_proc;
                                   
    master_bus_din(DATA_WIDTH-1 downto NUM_DMA) <= (others => '0');
                                   
    master_bus_din_proc: process(master_bus_clk) begin
        if rising_edge(master_bus_clk) then
            master_bus_din_loop: for i in 0 to NUM_DMA-1 loop
                -- Maximum NUM_DMA is 32, so we only need to compare the lower 5 bits
                if(to_integer(unsigned(master_bus_addr(4 downto 0))) = i) then
                    if(master_bus_addr(5) = '0') then
                        master_bus_din(NUM_DMA-1 downto 0) <= std_logic_vector(cack_count(i));
                    else
                        master_bus_din(NUM_DMA-1 downto 0) <= std_logic_vector(tvld_count(i));
                    end if;
                end if;
            end loop master_bus_din_loop;
        end if;
    end process master_bus_din_proc;

end rtl;
