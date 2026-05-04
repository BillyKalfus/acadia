----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 09/17/2023 10:36:37 PM
-- Design Name: 
-- Module Name: cmacc_tb - rtl
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

entity cmacc_tb is
end cmacc_tb;

architecture rtl of cmacc_tb is
    signal clk : std_logic := '1';
    signal nrst : std_logic := '0';
    
    signal data_in_tdata  : std_logic_vector(127 downto 0) := (others => '0');
    signal data_in_tvalid : std_logic := '0';
    signal data_in_tready : std_logic := '0';
    signal data_in_tlast  : std_logic := '0';

    signal data_out_tdata  : std_logic_vector(63 downto 0) := (others => '0');
    signal data_out_tvalid : std_logic := '0';
    signal data_out_tready : std_logic := '0';
    signal data_out_tlast  : std_logic := '0';

    signal kernel_memory_din  : std_logic_vector(31 downto 0);
    signal kernel_memory_dout : std_logic_vector(31 downto 0);
    signal kernel_memory_addr : std_logic_vector(10 downto 0);
    signal kernel_memory_we   : std_logic_vector(3 downto 0);
    signal kernel_memory_clk  : std_logic;

    signal registers_miso : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_mosi : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_addr : std_logic_vector(31 downto 0) := (others => '0');
    signal registers_we   : std_logic := '0';
    signal registers_en   : std_logic := '0';
begin

    uut : entity work.acadia_stream_cmacc
         generic map (
            -- Number of quadratures pairs present in the input must be <= 4
            INPUT_WORDS                   => 4,
            DATA_OUTPUT_FIFO_DEPTH        => 512,
            DATA_OUTPUT_FIFO_PRIMITIVE    => "auto",
            DATA_OUTPUT_FIFO_ASYNCHRONOUS => true,

            -- Kernel memory settings
            KERNEL_MEMORY_DEPTH                       => 2048,
            LOG2_KERNEL_MEMORY_DEPTH                  => 11,
            KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH    => 32,
            KERNEL_MEMORY_EXTERNAL_PORT_ADDRESS_WIDTH => 11,
            KERNEL_MEMORY_EXTERNAL_PORT_LATENCY       => 2,
            KERNEL_MEMORY_CLOCK_MODE                  => "independent",
            KERNEL_MEMORY_PRIMITIVE                   => "auto"
        )
        port map(
            clk => clk,
            nrst => nrst,
            
            -- Signal input
            data_in_tdata     => data_in_tdata,
            data_in_tvalid    => data_in_tvalid,
            data_in_tready    => data_in_tready,
            data_in_tlast     => data_in_tlast,
            
            -- Kernel memory interface
            kernel_memory_din  => kernel_memory_din,
            kernel_memory_dout => kernel_memory_dout,
            kernel_memory_addr => kernel_memory_addr,
            kernel_memory_we   => kernel_memory_we,
            kernel_memory_en   => '1',
            kernel_memory_clk  => clk,
                
            -- Output data stream
            data_out_aclk   => clk,
            data_out_tdata  => data_out_tdata,
            data_out_tvalid => data_out_tvalid,
            data_out_tready => '1',
            data_out_tlast  => data_out_tlast,
            data_out_tkeep  => open,

            -- Register access (synchronous to data_clk)
            registers_mosi  => registers_mosi,
            registers_miso  => registers_miso,
            registers_addr  => registers_addr,
            registers_we    => registers_we,
            registers_en    => registers_en
            );

    clk_proc: process begin
        clk <= '1';
        wait for 2 ns;
        clk <= '0';
        wait for 2 ns;
    end process clk_proc;
    
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
    
    kernel_memory_clk <= clk;
    
    stimulus_proc: process begin
        -- Reset
        nrst <= '0';
        wait until rising_edge(clk);
        nrst <= '1';
        wait until rising_edge(clk);
        
        -- Wait a while (it takes a while for the FIFO to reset)
        for i in 0 to 80 loop wait until rising_edge(clk); end loop;
        
        -- Load four samples of kernel memory
        kernel_memory_din <= x"12345678";
        kernel_memory_addr <= "000" & x"00";
        kernel_memory_we <= "1111";

        wait until rising_edge(clk);

        kernel_memory_din <= x"00008FFF";
        kernel_memory_addr <= "000" & x"01";
        kernel_memory_we <= "1111";

        wait until rising_edge(clk);

        kernel_memory_din <= x"FACE0000";
        kernel_memory_addr <= "000" & x"02";
        kernel_memory_we <= "1111";

        wait until rising_edge(clk);

        kernel_memory_din <= x"ABCDB00C";
        kernel_memory_addr <= "000" & x"03";
        kernel_memory_we <= "1111";
        
        wait until rising_edge(clk);

        kernel_memory_din <= x"00000000";
        kernel_memory_addr <= "00000000000";
        kernel_memory_we <= "0000";

        ------------ FIRST TEST: BOXCAR KERNEL ----------------
        
        -- Internal module reset
        wait until rising_edge(clk);
        registers_addr <= x"00000000";
        registers_mosi <= x"10000000";
        registers_we   <= '1';
        registers_en   <= '1';
        
        -- Write to kernel pointer start/end register
        -- both are zero in order to have a single-sample kernel
        wait until rising_edge(clk);
        registers_addr <= x"00000001";
        registers_mosi <= x"00000000";
        registers_we   <= '1';
        registers_en   <= '1';
        
        wait until rising_edge(clk);

        -- Control register
        -- accumulator_update_mode (bits 19-18) = 01 (accumulate after arm), 
        -- accumulator_latch_write (bits 21-20) = 01 (write after last input), 
        -- stream_port_write_mode (bits 28-27) = 01 (write after last input), 
        -- arm_preload (bit 26) = 1, 
        -- kernel_pointer_load (bit 16) = 1
        -- (1 << 18) | (1 << 20) | (1 << 27) | (1 << 26) | (1 << 16) = 0x0C150000
        registers_addr <= x"00000000";
        registers_mosi <= x"0C150000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);

        -- Real preload
        registers_addr <= x"00000004";
        registers_mosi <= x"0000000A";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);

        -- Imag preload
        registers_addr <= x"00000005";
        registers_mosi <= x"0000000C";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);

        registers_addr <= x"00000000";
        registers_mosi <= x"00000000";
        registers_we   <= '0';
        registers_en   <= '0';
        
        -- Wait a bit and then start sending data
        for i in 0 to 9 loop wait until rising_edge(clk); end loop;

        data_in_tvalid <= '1';

        for i in 0 to 17 loop wait until rising_edge(clk); end loop;

        -- Simulate an interrupted input
        data_in_tvalid <= '0';

        wait until rising_edge(clk);

        data_in_tvalid <= '1';

        for i in 0 to 12 loop wait until rising_edge(clk); end loop;

        data_in_tlast <= '1';

        wait until rising_edge(clk);

        data_in_tvalid <= '0';
        data_in_tlast  <= '0';

        for i in 0 to 20 loop wait until rising_edge(clk); end loop;


        ------------ SECOND TEST: FOUR-SAMPLE KERNEL DECIMATION ----------------
        
        -- Internal module reset
        wait until rising_edge(clk);
        registers_addr <= x"00000000";
        registers_mosi <= x"10000000";
        registers_we   <= '1';
        registers_en   <= '1';
        
        -- Write to kernel pointer start/end register
        -- both are zero in order to have a single-sample kernel
        wait until rising_edge(clk);
        registers_addr <= x"00000001";
        registers_mosi <= x"00000000";
        registers_we   <= '1';
        registers_en   <= '1';
        
        wait until rising_edge(clk);

        -- Control register
        -- accumulator_update_mode (bits 19-18) = 01 (accumulate after arm), 
        -- accumulator_latch_write (bits 21-20) = 01 (write after last input), 
        -- stream_port_write_mode (bits 28-27) = 01 (write after last input), 
        -- arm_preload (bit 26) = 1, 
        -- kernel_pointer_load (bit 16) = 1
        -- (1 << 18) | (1 << 20) | (1 << 27) | (1 << 26) | (1 << 16) = 0x0C150000
        registers_addr <= x"00000000";
        registers_mosi <= x"0C150000";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);

        -- Real preload
        registers_addr <= x"00000004";
        registers_mosi <= x"0000000A";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);

        -- Imag preload
        registers_addr <= x"00000005";
        registers_mosi <= x"0000000C";
        registers_we   <= '1';
        registers_en   <= '1';

        wait until rising_edge(clk);

        registers_addr <= x"00000000";
        registers_mosi <= x"00000000";
        registers_we   <= '0';
        registers_en   <= '0';
        
        -- Wait a bit and then start sending data
        for i in 0 to 9 loop wait until rising_edge(clk); end loop;

        data_in_tvalid <= '1';

        for i in 0 to 17 loop wait until rising_edge(clk); end loop;

        -- Simulate an interrupted input
        data_in_tvalid <= '0';

        wait until rising_edge(clk);

        data_in_tvalid <= '1';

        for i in 0 to 12 loop wait until rising_edge(clk); end loop;

        data_in_tlast <= '1';

        wait until rising_edge(clk);

        data_in_tvalid <= '0';
        data_in_tlast  <= '0';

        for i in 0 to 14 loop wait until rising_edge(clk); end loop;

    end process stimulus_proc;

end rtl;
