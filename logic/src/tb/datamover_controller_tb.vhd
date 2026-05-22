----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 09/17/2023 10:36:37 PM
-- Design Name: 
-- Module Name: datamover_controller_tb - rtl
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

entity datamover_controller_tb is
end datamover_controller_tb;

architecture rtl of datamover_controller_tb is
    signal clk : std_logic := '1';
    signal nrst : std_logic := '0';

    signal master_bus_mosi : std_logic_vector(31 downto 0);
    signal master_bus_miso : std_logic_vector(31 downto 0);
    signal master_bus_addr : std_logic_vector(31 downto 0);
    signal master_bus_we   : std_logic;
    signal master_bus_en   : std_logic;

    signal err : std_logic;

    signal cmd_tdata  : std_logic_vector(87 downto 0);
    signal cmd_tvalid : std_logic;
    signal cmd_tready : std_logic;

    signal sts_tdata  : std_logic_vector(31 downto 0);
    signal sts_tvalid : std_logic;
    signal sts_tready : std_logic;
    
    
begin

    uut : entity work.acadia_datamover_controller
        port map(
            clk => clk,

            -- Register access
            master_bus_mosi => master_bus_mosi,
            master_bus_miso => master_bus_miso,
            master_bus_addr => master_bus_addr,
            master_bus_we   => master_bus_we,
            master_bus_en   => master_bus_en,

            -- Datamover interface
            err        => err,
            
            cmd_tdata  => cmd_tdata,
            cmd_tvalid => cmd_tvalid,
            cmd_tready => cmd_tready,

            sts_tdata  => sts_tdata,
            sts_tvalid => sts_tvalid,
            sts_tready => sts_tready
        );

    clk_proc: process begin
        clk <= '1';
        wait for 2 ns;
        clk <= '0';
        wait for 2 ns;
    end process clk_proc;

    sts_tvalid <= '0';
    err <= '0';
    
    stimulus_proc: process begin

        cmd_tready <= '0';

        ------------ FIRST TEST: one small 4kb transfer ----------------
        
        -- Internal module reset
        wait until rising_edge(clk);
        master_bus_addr <= x"00000003";
        master_bus_mosi <= x"00000000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';

        wait until rising_edge(clk);

        master_bus_we   <= '0';
        master_bus_en   <= '0';

        -- Wait a bit
        for i in 0 to 9 loop wait until rising_edge(clk); end loop;
        
        -- Write to size register
        wait until rising_edge(clk);
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"00001000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';
        
        -- Write to address register
        wait until rising_edge(clk);
        master_bus_addr <= x"00000000";
        master_bus_mosi <= x"10000000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';

        -- Simultaneously accept the transfer
        cmd_tready <= '1';
        
        wait until rising_edge(clk);

        master_bus_we   <= '0';
        master_bus_en   <= '0';

        for i in 0 to 10 loop wait until rising_edge(clk); end loop;

        cmd_tready <= '0';
    

        for i in 0 to 20 loop wait until rising_edge(clk); end loop;

        ------------ SECOND TEST: 4 big transfers (2^22 * 4 bytes) ----------------
        
        -- Internal module reset
        wait until rising_edge(clk);
        master_bus_addr <= x"00000003";
        master_bus_mosi <= x"00000000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';

        wait until rising_edge(clk);

        master_bus_we   <= '0';
        master_bus_en   <= '0';

        -- Wait a bit
        for i in 0 to 9 loop wait until rising_edge(clk); end loop;
        
        -- Write to size register
        wait until rising_edge(clk);
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"01000000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';
        
        -- Write to address register
        wait until rising_edge(clk);
        master_bus_addr <= x"00000000";
        master_bus_mosi <= x"10000000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';

        -- Simultaneously accept the transfer
        cmd_tready <= '1';
        
        wait until rising_edge(clk);

        master_bus_we   <= '0';
        master_bus_en   <= '0';

        for i in 0 to 10 loop wait until rising_edge(clk); end loop;

        cmd_tready <= '0';
    

        for i in 0 to 20 loop wait until rising_edge(clk); end loop;

        ------------ THIRD TEST: 4 big transfers (2^23 * 4 bytes) and one small (4 kb) test----------------
        
        -- Internal module reset
        wait until rising_edge(clk);
        master_bus_addr <= x"00000003";
        master_bus_mosi <= x"00000000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';

        wait until rising_edge(clk);

        master_bus_we   <= '0';
        master_bus_en   <= '0';

        -- Wait a bit
        for i in 0 to 9 loop wait until rising_edge(clk); end loop;
        
        -- Write to size register
        wait until rising_edge(clk);
        master_bus_addr <= x"00000001";
        master_bus_mosi <= x"02001000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';
        
        -- Write to address register
        wait until rising_edge(clk);
        master_bus_addr <= x"00000000";
        master_bus_mosi <= x"10000000";
        master_bus_we   <= '1';
        master_bus_en   <= '1';
        
        wait until rising_edge(clk);

        master_bus_we   <= '0';
        master_bus_en   <= '0';

        -- For the first few commands, accept the transfers one at a time
        for i in 0 to 10 loop wait until rising_edge(clk); end loop;
        
        cmd_tready <= '1';
        wait until rising_edge(clk);
        cmd_tready <= '0';

        for i in 0 to 10 loop wait until rising_edge(clk); end loop;

        cmd_tready <= '1';
        wait until rising_edge(clk);
        cmd_tready <= '0';

        for i in 0 to 10 loop wait until rising_edge(clk); end loop;

        -- Now accept all the remaining transfers consecutively
        cmd_tready <= '1';
        for i in 0 to 20 loop wait until rising_edge(clk); end loop;
        cmd_tready <= '0';
    

        for i in 0 to 100 loop wait until rising_edge(clk); end loop;

    end process stimulus_proc;

end rtl;
