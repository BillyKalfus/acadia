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
        generic map (DESCRIPTOR_FIFO_DEPTH => 8)
        port map(
            clk => clk,
            nrst => nrst,

            trigger => trigger,
            running => running,
            
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
    
    stimulus_proc: process begin
        -- Reset
        wait until rising_edge(clk);
        nrst <= '0';
        
        wait until rising_edge(clk);
        nrst <= '1';
        
        for i in 0 to 10 loop wait until rising_edge(clk); end loop;
        
        -- Play some pulses
        for k in 0 to 2 loop 
        
            master_bus_addr <= x"00000001";
            master_bus_mosi <= x"00A00010";
            master_bus_we <= '1';
            master_bus_en <= '1';
            wait until rising_edge(clk);
    
            master_bus_addr <= x"00000001";
            master_bus_mosi <= x"000B0003";
            master_bus_we <= '1';
            master_bus_en <= '1';
            wait until rising_edge(clk);
    
            master_bus_addr <= x"00000001";
            master_bus_mosi <= x"000C0008";
            master_bus_we <= '1';
            master_bus_en <= '1';
            wait until rising_edge(clk);
    
            master_bus_we <= '0';
            master_bus_en <= '0';
            
            for i in 0 to 3 loop wait until rising_edge(clk); end loop;
            trigger <= '1';
            wait until rising_edge(clk);
            trigger <= '0';
            
            for i in 0 to 99 loop wait until rising_edge(clk); end loop;
        end loop;

        -- Play an arbitrary pulse followed by a stretch and then another arbitrary
        -- Do it twice with a dwell in between
        
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000D0003";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000002";
        master_bus_mosi <= x"00000009";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000000";
        master_bus_mosi <= x"00000003";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000003";
        master_bus_mosi <= x"00000007";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000D0003";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000002";
        master_bus_mosi <= x"00000009";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000000";
        master_bus_mosi <= x"00000003";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_we <= '0';
        master_bus_en <= '0';
        wait until rising_edge(clk);


        -- Trigger and wait until it finishes
        for i in 0 to 3 loop wait until rising_edge(clk); end loop;
        trigger <= '1';
        wait until rising_edge(clk);
        trigger <= '0';

        for i in 0 to 59 loop wait until rising_edge(clk); end loop;

        -- Trigger while a sequence is playing
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000E0010";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_we <= '0';
        master_bus_en <= '0';

        -- Trigger
        for i in 0 to 3 loop wait until rising_edge(clk); end loop;
        trigger <= '1';
        wait until rising_edge(clk);
        trigger <= '0';

        -- Wait 4 cycles and trigger again
        for i in 0 to 3 loop wait until rising_edge(clk); end loop;
        trigger <= '1';
        wait until rising_edge(clk);
        trigger <= '0';

        -- Wait for the sequence to finish
        for i in 0 to 19 loop wait until rising_edge(clk); end loop;

        -- Overflow the FIFO
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00010005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00020005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00030005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00040005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00050005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00060005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00070005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00080005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00090005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000A0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000B0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000C0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000D0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000E0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000F0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00100005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_we <= '0';
        master_bus_en <= '0';

        -- Now we'll trigger, and then keep pushing to the FIFO to see what 
        -- happens when we read and write to the FIFO at the same time
        for i in 0 to 3 loop wait until rising_edge(clk); end loop;
        trigger <= '1';
        wait until rising_edge(clk);
        trigger <= '0';

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00010005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00020005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00030005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00040005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00050005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00060005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00070005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00080005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00090005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000A0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000B0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000C0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000D0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000E0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000F0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00100005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_we <= '0';
        master_bus_en <= '0';

        -- Wait for the sequence to finish
        for i in 0 to 199 loop wait until rising_edge(clk); end loop;
        
        -- Do some very short pulses
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00030001";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000D0000";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);

        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"000A0005";
        master_bus_we <= '1';
        master_bus_en <= '1';
        wait until rising_edge(clk);
        
        master_bus_we <= '0';
        master_bus_en <= '0';
        
        for i in 0 to 3 loop wait until rising_edge(clk); end loop;
        trigger <= '1';
        wait until rising_edge(clk);
        trigger <= '0';

        -- Wait for the sequence to finish
        for i in 0 to 19 loop wait until rising_edge(clk); end loop;

    end process stimulus_proc;

end rtl;
