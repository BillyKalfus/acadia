----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 03/06/2023 04:58:59 PM
-- Design Name: acadia
-- Module Name: acadia_dma_fifo - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: A very-low-latency FIFO for the real-time DMA modules.
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

entity acadia_dma_fifo is
    generic (
        WIDTH : positive := 16;
        DEPTH : positive := 8;
        LOG2_DEPTH : positive := 3
    );
    port (
         clk       : in  std_logic;
         rst       : in  std_logic;
         
         din       : in  std_logic_vector(WIDTH-1 downto 0);
         wr_en     : in  std_logic;
         
         dout      : out std_logic_vector(WIDTH-1 downto 0);
         rd_en     : in  std_logic;
         
         occupancy : out std_logic_vector(LOG2_DEPTH downto 0)
    );
end acadia_dma_fifo;

architecture rtl of acadia_dma_fifo is
    type array_t is array (natural range <>) of std_logic_vector(WIDTH-1 downto 0);
    signal fifo : array_t(DEPTH-1 downto 0);
    
    signal rd_ptr : unsigned(LOG2_DEPTH-1 downto 0);
    signal wr_ptr : unsigned(LOG2_DEPTH-1 downto 0);
    
    signal occupancy_int : unsigned(LOG2_DEPTH downto 0);    
begin

    rd_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                rd_ptr <= (others => '0');
            elsif(rd_en = '1' and occupancy_int /= 0) then
                rd_ptr <= rd_ptr + 1;
            end if;
        end if;
    end process rd_proc;
    
    -- There is a slight asymmetry between reading and writing;
    -- if the FIFO isn't empty, we can read and write at the same time 
    wr_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                wr_ptr <= (others => '0');
            elsif(wr_en = '1' and (occupancy_int /= DEPTH or rd_en = '1')) then
                wr_ptr <= wr_ptr + 1;
                fifo(to_integer(wr_ptr)) <= din;
            end if;
        end if;
    end process wr_proc;
    
    occupancy_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                occupancy_int <= (others => '0');
            elsif(rd_en = '1' and wr_en = '0' and occupancy_int /= 0) then
                occupancy_int <= occupancy_int - 1;
            elsif(wr_en = '1' and rd_en = '0' and occupancy_int /= DEPTH) then
                occupancy_int <= occupancy_int + 1;
            end if;
        end if;
    end process occupancy_proc;
    
    dout <= fifo(to_integer(rd_ptr));
    occupancy <= std_logic_vector(occupancy_int);
    
end rtl;
