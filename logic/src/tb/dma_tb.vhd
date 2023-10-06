----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 09/17/2023 10:36:37 PM
-- Design Name: 
-- Module Name: dma_tb - rtl
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

-- Uncomment the following library declaration if using
-- arithmetic functions with Signed or Unsigned values
use IEEE.NUMERIC_STD.ALL;

-- Uncomment the following library declaration if instantiating
-- any Xilinx leaf cells in this code.
--library UNISIM;
--use UNISIM.VComponents.all;

entity dma_tb is
end dma_tb;

architecture rtl of dma_tb is
    signal clk : std_logic := '1';
    signal nrst : std_logic := '0';

    signal trigger : std_logic := '0';

    signal descriptor_mem_dout : std_logic_vector(63 downto 0) := (others => '0');
    signal descriptor_mem_addr : std_logic_vector(15 downto 0);
    signal descriptor_mem_clk  : std_logic := '0';
    
    -- data input stream
    signal data_in             : std_logic_vector(31 downto 0) := (others => '0');

    -- outputs with sideband signals
    signal data_out_tdata      : std_logic_vector(31 downto 0);
    signal data_out_tvalid     : std_logic;
    signal data_out_tlast      : std_logic;

    signal address_out_tdata   : std_logic_vector(15 downto 0);
    signal address_out_tvalid  : std_logic;
    signal address_out_tlast   : std_logic;

    signal data_address_invalid : std_logic;
    
    -- Descriptor FIFO interface
    signal descriptor_address_fifo_in           : std_logic_vector(15 downto 0) := (others => '0');
    signal descriptor_address_fifo_wr           : std_logic := '0';
    signal descriptor_address_fifo_almost_empty : std_logic;
    signal descriptor_address_fifo_empty        : std_logic;
    
    signal running        :  std_logic;
    
    
begin

    uut : entity work.acadia_dma
        port map(
            clk => clk,
            nrst => nrst,

            trigger => trigger,

            -- Descriptor memory interface
            descriptor_mem_dout => descriptor_mem_dout,
            descriptor_mem_addr => descriptor_mem_addr,
            descriptor_mem_clk  => descriptor_mem_clk,
            
            -- data input stream
            data_in             => data_in,

            -- outputs with sideband signals
            data_out_tdata      => data_out_tdata,
            data_out_tvalid     => data_out_tvalid,
            data_out_tlast      => data_out_tlast,

            address_out_tdata  => address_out_tdata,
            address_out_tvalid => address_out_tvalid,
            address_out_tlast  => address_out_tlast,

            data_address_invalid => data_address_invalid,
            
            -- Descriptor FIFO interface
            descriptor_address_fifo_in           => descriptor_address_fifo_in,
            descriptor_address_fifo_wr           => descriptor_address_fifo_wr,
            descriptor_address_fifo_almost_empty => descriptor_address_fifo_almost_empty,
            descriptor_address_fifo_empty        => descriptor_address_fifo_empty,
            
            running        => running
        );

    clk_proc: process begin
        clk <= '1';
        wait for 2 ns;
        clk <= '0';
        wait for 2 ns;
    end process clk_proc;
    
    
    stimulus_proc: process begin
        -- Reset
        wait until rising_edge(clk);
        nrst <= '0';
        descriptor_mem_dout <= x"00000000000004E2";

        wait until rising_edge(clk);
        nrst <= '1';
        
        for i in 0 to 3 loop wait until rising_edge(clk); end loop;
        descriptor_address_fifo_in <= (others => '0');
        descriptor_address_fifo_wr <= '1';

        wait until rising_edge(clk);
        descriptor_address_fifo_wr <= '0';

        for i in 0 to 9 loop wait until rising_edge(clk); end loop;
        trigger <= '1';
        wait until rising_edge(clk);
        trigger <= '0';
        
    
        for i in 0 to 1999 loop wait until rising_edge(clk); end loop;

    end process stimulus_proc;

end rtl;
