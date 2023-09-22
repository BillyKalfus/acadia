----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 09/17/2023 10:36:37 PM
-- Design Name: 
-- Module Name: dsp_tb2 - rtl
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

entity dsp_tb2 is
end dsp_tb2;

architecture rtl of dsp_tb2 is
    signal clk : std_logic := '1';
    
    signal data_in_tdata  : std_logic_vector(127 downto 0) := (others => '0');
    signal data_in_tvalid : std_logic := '0';
    signal data_in_tready : std_logic := '0';
    signal data_in_tlast  : std_logic := '0';

    signal data_in_tvalid_dd   : std_logic := '0';
    signal data_in_tvalid_d   : std_logic := '0';

    signal data_out_tdata  : std_logic_vector(63 downto 0) := (others => '0');
    signal data_out_tvalid : std_logic := '0';
    signal data_out_tready : std_logic := '0';
    signal data_out_tlast  : std_logic := '0';

    signal registers_miso : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_mosi : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_addr : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_we   : std_logic := '0';
    signal registers_en   : std_logic := '0';
begin

    uut : entity work.acadia_complex_dsp
        port map(
            clk => clk,
            
            data_in_tdata  => data_in_tdata,
            data_in_tvalid => data_in_tvalid,
            data_in_tready => data_in_tready,
            data_in_tlast => data_in_tlast,
            
            data_out_clk => clk,
            data_out_tdata => data_out_tdata,
            data_out_tvalid => data_out_tvalid,
            data_out_tready => data_out_tready,
            data_out_tlast => data_out_tlast,
            
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
    
    test_proc: process(clk) begin
        if rising_edge(clk) then
            data_in_tvalid_dd <= data_in_tvalid_d;
            data_in_tvalid_d <= data_in_tvalid;
        end if;
    end process test_proc;
    
    data_in_proc: process(clk) 
        variable counter : unsigned(15 downto 0) := (others => '0');
    begin
        if rising_edge(clk) then
            for i in 0 to 7 loop
                data_in_tdata(i*16 + 15 downto i*16) <= std_logic_vector(counter + to_unsigned(i, counter'length));
            end loop;
            counter := counter + 1;
        end if;
    end process data_in_proc;
    
    stimulus_proc: process begin
        -- Reset
        wait until rising_edge(clk);
        registers_addr <= x"00000000";
        registers_mosi <= x"00000010";
        registers_we   <= '1';
        registers_en   <= '1';
        
        wait until rising_edge(clk);
        
        registers_addr <= x"00000000";
        registers_mosi <= x"00000000";
        registers_we   <= '1';
        registers_en   <= '1';

        for i in 0 to 3 loop wait until rising_edge(clk); end loop;
        -- Real scale factor
        registers_addr <= x"00000001";
        registers_mosi <= x"00010000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Real pre-add
        registers_addr <= x"00000002";
        registers_mosi <= x"00000000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Real C(low)
        registers_addr <= x"00000003";
        registers_mosi <= x"00000000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Imag scale factor
        registers_addr <= x"00000005";
        registers_mosi <= x"00000000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Imag pre-add
        registers_addr <= x"00000006";
        registers_mosi <= x"00000000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Imag C(low)
        registers_addr <= x"00000007";
        registers_mosi <= x"00000000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Packet start config
        -- P = C
        -- W = 11, Z = 000, Y = 00, X = 00
        -- ALUMODE = 0000 (W + X + Y + Z + CIN)
        registers_addr <= x"00000009";
        registers_mosi <= "0000000000000000000" & "11" & "000" & "00" & "00" & "0000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Counter start config
        -- P = mult
        -- W = 00, Z = 000, Y = 01, X = 01
        -- ALUMODE = 0000 (W + X + Y + Z + CIN)
        registers_addr <= x"0000000A";
        registers_mosi <= "0000000000000000000" & "00" & "000" & "01" & "01" & "0000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Default config
        -- P = P
        -- W = 01, Z = 000, Y = 00, X = 00
        -- ALUMODE = 0000 (W + X + Y + Z + CIN)
        registers_addr <= x"0000000B";
        registers_mosi <= "0000000000000000000" & "01" & "000" & "00" & "00" & "0000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        -- Counter period low
        registers_addr <= x"0000000C";
        registers_mosi <= x"00050000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        registers_addr <= x"00000000";
        registers_mosi <= x"00000020";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);
        registers_addr <= x"00000000";
        registers_mosi <= x"00000000";
        registers_we   <= '0';
        registers_en   <= '0';

        for i in 0 to 9 loop wait until rising_edge(clk); end loop;

        data_in_tvalid <= '1';

        for i in 0 to 17 loop wait until rising_edge(clk); end loop;

        data_in_tvalid <= '0';

        wait until rising_edge(clk);

        data_in_tvalid <= '1';

        for i in 0 to 12 loop wait until rising_edge(clk); end loop;

        data_in_tlast <= '1';

        wait until rising_edge(clk);

        data_in_tvalid <= '0';
        data_in_tlast  <= '0';

        for i in 0 to 14 loop wait until rising_edge(clk); end loop;

        data_in_tvalid <= '1';

        for i in 0 to 14 loop wait until rising_edge(clk); end loop;

        data_in_tlast <= '1';

        wait until rising_edge(clk);

        data_in_tvalid <= '0';
        data_in_tlast  <= '0';
    
    end process stimulus_proc;

end rtl;
