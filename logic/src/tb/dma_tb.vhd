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
    signal master_bus_mosi : std_logic_vector(31 downto 0) := (others => '0');
    signal master_bus_miso : std_logic_vector(31 downto 0);
    signal master_bus_addr : std_logic_vector(31 downto 0) := (others => '0');
    signal master_bus_we   : std_logic := '0';
    signal master_bus_en   : std_logic := '0';
    
    signal running        :  std_logic;
    
begin

    uut : entity work.acadia_dma
        port map(
            clk => clk,
            nrst => nrst,

            trigger => trigger,
            running => running,

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
            master_bus_mosi => master_bus_mosi,
            master_bus_miso => master_bus_miso,
            master_bus_addr => master_bus_addr,
            master_bus_we   => master_bus_we,
            master_bus_en   => master_bus_en
        );

    clk_proc: process begin
        clk <= '1';
        wait for 2 ns;
        clk <= '0';
        wait for 2 ns;
    end process clk_proc;

    descriptor_mem_proc: process(clk) begin
        if rising_edge(clk) then
            if unsigned(descriptor_mem_addr) = 0 then
                descriptor_mem_dout <= x"000000000000007C";
            elsif unsigned(descriptor_mem_addr) = 1 then
                descriptor_mem_dout <= x"00000000000001F3";
            else
                descriptor_mem_dout <= (others => '0');
            end if;
        end if;
    end process descriptor_mem_proc;
    
    
    stimulus_proc: process begin
        -- Reset
        wait until rising_edge(clk);
        nrst <= '0';
        

        wait until rising_edge(clk);
        nrst <= '1';
        
        for i in 0 to 3 loop wait until rising_edge(clk); end loop;
        
        master_bus_addr <= x"00000000";
        master_bus_mosi <= x"00000000";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000000";
        master_bus_mosi <= x"00000001";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000000";
        master_bus_mosi <= x"00000000";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_we <= '0';
        master_bus_en <= '0';
        
        for i in 0 to 9 loop wait until rising_edge(clk); end loop;
        trigger <= '1';
        wait until rising_edge(clk);
        trigger <= '0';
        
    
        for i in 0 to 1999 loop wait until rising_edge(clk); end loop;

    end process stimulus_proc;

end rtl;
