----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 09/17/2023 10:36:37 PM
-- Design Name: 
-- Module Name: adder_tb - rtl
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

entity adder_tb is
end adder_tb;

architecture rtl of adder_tb is
    signal clk : std_logic := '1';
    
    signal a_tdata  : std_logic_vector(127 downto 0) := (others => '0');
    signal a_tvalid : std_logic := '0';
    signal a_tready : std_logic := '0';
    signal a_tlast  : std_logic := '0';
    signal a_tkeep  : std_logic_vector(15 downto 0) := (others => '0');

    signal b_tdata  : std_logic_vector(255 downto 0) := (others => '0');
    signal b_tvalid : std_logic := '0';
    signal b_tready : std_logic := '0';
    signal b_tlast  : std_logic := '0';
    signal b_tkeep  : std_logic_vector(31 downto 0) := (others => '0');
            
    signal sum_tdata  : std_logic_vector(255 downto 0) := (others => '0');
    signal sum_tvalid : std_logic := '0';
    signal sum_tready : std_logic := '0';
    signal sum_tlast  : std_logic := '0';
    signal sum_tkeep  : std_logic_vector(31 downto 0) := (others => '0');

    signal registers_miso : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_mosi : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_addr : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_we   : std_logic := '0';
    signal registers_en   : std_logic := '0';
begin

    uut : entity work.acadia_stream_adder
        port map(
            clk => clk,
            
            a_tdata  => a_tdata, 
            a_tvalid => a_tvalid,
            a_tready => a_tready,
            a_tlast  => a_tlast,
            a_tkeep  => a_tkeep,

            b_tdata  => b_tdata,
            b_tvalid => b_tvalid,
            b_tready => b_tready,
            b_tlast  => b_tlast,
            b_tkeep  => b_tkeep,
                
            sum_tdata  => sum_tdata,
            sum_tvalid => sum_tvalid,
            sum_tready => sum_tready,
            sum_tlast  => sum_tlast,
            sum_tkeep  => sum_tkeep,
            
            registers_mosi => registers_mosi,
            registers_miso => registers_miso,
            registers_addr => registers_addr,
            registers_we => registers_we,
            registers_en => registers_en
        );

    clk_proc: process begin
        clk <= '1';
        wait for 2 ns;
        clk <= '0';
        wait for 2 ns;
    end process clk_proc;
    
    data_in_proc: process(clk) 
        variable a_counter : unsigned(15 downto 0) := (others => '0');
        variable b_counter : unsigned(15 downto 0) := (others => '0');
    begin
        if rising_edge(clk) then
            for i in 0 to 7 loop
                a_tdata(i*16 + 15 downto i*16) <= std_logic_vector(a_counter + to_unsigned(i, a_counter'length));
                b_tdata(i*16 + 15 downto i*16) <= std_logic_vector(b_counter + to_unsigned(i, b_counter'length));
            end loop;
            a_counter := a_counter + 1;
            b_counter := b_counter + 7;
        end if;
    end process data_in_proc;
    
    stimulus_proc: process 
        variable data_counter : unsigned(15 downto 0) := (others => '0');
    begin
        -- Reset
        wait until rising_edge(clk);
        registers_mosi <= x"00000004";
        registers_we   <= '1';
        registers_en   <= '1';
        
        wait until rising_edge(clk);        
        registers_mosi <= x"00000000";
        registers_we   <= '0';
        registers_en   <= '0';

        -- Provide some data properly
        for i in 0 to 7 loop wait until rising_edge(clk); end loop;

        a_tvalid <= '1';
        b_tvalid <= '1';
        sum_tready <= '1';

        for i in 0 to 7 loop wait until rising_edge(clk); end loop;

        sum_tready <= '0';

        wait until rising_edge(clk);

        sum_tready <= '1';

        for i in 0 to 7 loop wait until rising_edge(clk); end loop;

        a_tvalid <= '0';
        b_tvalid <= '1';

        for i in 0 to 3 loop wait until rising_edge(clk); end loop;

        a_tvalid <= '1';
        b_tvalid <= '1';

        for i in 0 to 7 loop wait until rising_edge(clk); end loop;

        sum_tready <= '0';

        for i in 0 to 7 loop wait until rising_edge(clk); end loop;

        sum_tready <= '1';

        for i in 0 to 7 loop wait until rising_edge(clk); end loop;

        a_tlast <= '1';
        b_tlast <= '1';

        wait until rising_edge(clk);

        a_tvalid <= '0';
        b_tvalid <= '0';
        a_tlast <= '0';
        b_tlast <= '0';
    
    end process stimulus_proc;

end rtl;
