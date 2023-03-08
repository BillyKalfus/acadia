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
         clk          : in  std_logic;
         nrst         : in  std_logic;
         
         din          : in  std_logic_vector(WIDTH-1 downto 0);
         wr_en        : in  std_logic;
         
         dout         : out std_logic_vector(WIDTH-1 downto 0);
         rd_en        : in  std_logic;
         
         empty        : out std_logic;
         almost_empty : out std_logic
    
    );
end acadia_dma_fifo;

architecture rtl of acadia_dma_fifo is
    type array_t is array (natural range <>) of std_logic_vector(WIDTH-1 downto 0);
    signal fifo : array_t(DEPTH-1 downto 0);
    
    signal rd_ptr : unsigned(LOG2_DEPTH-1 downto 0);
    signal wr_ptr : unsigned(LOG2_DEPTH-1 downto 0);
    signal full   : std_logic;
begin

    rd_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                rd_ptr <= (others => '0');
            
            -- Decrement the read pointer if we're just reading and not writing
            -- Also make sure that we don't increase the read pointer past the 
            -- write pointer unless they're only equal because we're full
            elsif(rd_en = '1' and wr_en = '0' and (full = '1' or rd_ptr /= wr_ptr)) then
                rd_ptr <= rd_ptr + 1;
            end if;
        end if;
    end process rd_proc;
    
    wr_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                wr_ptr <= (others => '0');
            elsif(wr_en = '1') then
                -- Increment the write pointer if we're not concurrently reading
                -- and if we're not full
                if(rd_en = '0' and full = '0') then
                    wr_ptr <= wr_ptr + 1;
                end if;
                
                -- Actually write the data so long as we're not full or we're 
                -- concurrently reading
                if(full = '0' or rd_en = '1') then
                    fifo(to_integer(wr_ptr)) <= din;
                end if;
            end if;
        end if;
    end process wr_proc;
    
    full_proc: process(clk) begin
        if rising_edge(clk) then
            -- Whenever we read, as long as we're not simultaneously writing
            -- then we cannot be full afterwards
            if(nrst = '0' or (rd_en = '1' and wr_en = '0')) then
                full <= '0';
                
            -- We become full when we write and the write pointer is in the last
            -- available position: right behind the read pointer
            elsif(wr_en = '1' and wr_ptr = rd_ptr-1) then
                full <= '1';
            end if;
        end if;
    end process full_proc;
    
    dout <= fifo(to_integer(rd_ptr));
    empty <= (not full) when wr_ptr = rd_ptr else '0';
    almost_empty <= '1' when wr_ptr = rd_ptr+1 else '0';
end rtl;
