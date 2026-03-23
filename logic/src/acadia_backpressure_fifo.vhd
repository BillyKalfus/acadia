----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 03/06/2023 04:58:59 PM
-- Design Name: acadia
-- Module Name: acadia_backpressure_fifo - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: A FIFO for bridging an ADC interface with no support for 
-- backpressure to an AXI-Stream interface.
-- Dependencies: 
-- 
-- Revision:
-- Revision 0.01 - File Created
-- Additional Comments:
-- 
----------------------------------------------------------------------------------


library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.STD_LOGIC_MISC.ALL;
use IEEE.NUMERIC_STD.ALL;

library xpm;
use xpm.vcomponents.all;

entity acadia_backpressure_fifo is
    generic (
        WORD_WIDTH    : positive := 32;
        INPUT_WORDS   : positive := 4;
        OUTPUT_WORDS  : positive := 8;
        INPUT_DEPTH   : positive := 512;
        MEMORY_TYPE   : string   := "auto";
        RST_CYCLES    : positive := 8;
        ASYNCHRONOUS  : boolean  := true
    );
    port (
        clk      : in  std_logic;
        rst      : in  std_logic;
        rst_busy : out std_logic;

        -- A port for monitoring the status of the FIFO and resetting it
        -- This port is synchronous to clk
        overflow     : out std_logic;
        output_misaligned : out std_logic;
         
        signal_in_tdata  : in  std_logic_vector(INPUT_WORDS*WORD_WIDTH-1 downto 0);
        signal_in_tvalid : in  std_logic;
        signal_in_tlast  : in  std_logic;
        
        m_axis_aclk      : in std_logic;
        m_axis_tdata     : out std_logic_vector(OUTPUT_WORDS*WORD_WIDTH-1 downto 0);
        m_axis_tvalid    : out std_logic;
        m_axis_tready    : in  std_logic;
        m_axis_tlast     : out std_logic;
        m_axis_tkeep     : out std_logic_vector((OUTPUT_WORDS*WORD_WIDTH/8)-1 downto 0)
    );
end acadia_backpressure_fifo;

architecture rtl of acadia_backpressure_fifo is
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;
    
    ATTRIBUTE X_INTERFACE_PARAMETER of m_axis_aclk   : SIGNAL is "ASSOCIATED_BUSIF M_AXIS";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tdata       : SIGNAL is "xilinx.com:interface:axis:1.0 M_AXIS TDATA";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tvalid      : SIGNAL is "xilinx.com:interface:axis:1.0 M_AXIS TVALID";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tready      : SIGNAL is "xilinx.com:interface:axis:1.0 M_AXIS TREADY";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tlast       : SIGNAL is "xilinx.com:interface:axis:1.0 M_AXIS TLAST";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tkeep       : SIGNAL is "xilinx.com:interface:axis:1.0 M_AXIS TKEEP";
    ATTRIBUTE X_INTERFACE_MODE of m_axis_tdata       : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of m_axis_tdata  : SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WORD_WIDTH*OUTPUT_WORDS/8);

    ATTRIBUTE X_INTERFACE_PARAMETER of clk   : SIGNAL is "ASSOCIATED_BUSIF SIGNAL_IN";
    ATTRIBUTE X_INTERFACE_INFO of signal_in_tdata      : SIGNAL is "xilinx.com:interface:axis:1.0 SIGNAL_IN TDATA";
    ATTRIBUTE X_INTERFACE_INFO of signal_in_tvalid     : SIGNAL is "xilinx.com:interface:axis:1.0 SIGNAL_IN TVALID";
    ATTRIBUTE X_INTERFACE_INFO of signal_in_tlast      : SIGNAL is "xilinx.com:interface:axis:1.0 SIGNAL_IN TLAST";
    ATTRIBUTE X_INTERFACE_PARAMETER of signal_in_tdata : SIGNAL is "HAS_TLAST 1,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 0,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WORD_WIDTH*INPUT_WORDS/8);

    -- Synchronize the reset into the output domain
    signal rst_output_sync : std_logic;

    signal rst_shift_reg : std_logic_vector(RST_CYCLES-1 downto 0);

    signal wr_rst_busy : std_logic;
    signal rd_rst_busy : std_logic;
    signal rd_rst_busy_sync : std_logic;

    -- Error conditions
    signal fifo_overflow      : std_logic;
    signal overflow_latch     : std_logic;
    signal misalignment_latch : std_logic;
    
    -- Need to realign some signals before interfacing to the FIFO or interface port itself
    signal fifo_din          : std_logic_vector(INPUT_WORDS*(WORD_WIDTH+1)-1 downto 0);
    signal fifo_dout         : std_logic_vector(OUTPUT_WORDS*(WORD_WIDTH+1)-1 downto 0);
    signal fifo_tlast_out    : std_logic_vector(OUTPUT_WORDS-1 downto 0);
    signal fifo_valid        : std_logic;

begin
    
    -- We'll create a shift register so that when we trigger a reset, we report being busy for a while
    -- This is mainly to allow time for the rd_rst_busy signal in (possibly) another clock domain
    -- to propagate back to the controller domain
    rst_shift_proc: process(clk) begin
        if rising_edge(clk) then
            rst_shift_reg(rst_shift_reg'high downto 1) <= rst_shift_reg(rst_shift_reg'high-1 downto 0);
            rst_shift_reg(0) <= rst;
        end if;
    end process rst_shift_proc;

    rst_busy <= or_reduce(rst_shift_reg) or wr_rst_busy or rd_rst_busy;

    -- Directly drive some of the AXIS signals
    m_axis_tkeep  <= (others => '1');
    m_axis_tvalid <= fifo_valid;

    -- Latch the overflow signal so that we can know if it happened at any point during the capture
    overflow <= overflow_latch;
    overflow_latch_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                overflow_latch <= '0';
            elsif(fifo_overflow = '1') then
                overflow_latch <= '1';
            end if;
        end if;
    end process overflow_latch_proc;

    -- Separate all of the incoming data words by 1 bit
    -- so that the tlast signal can be inserted and properly aligned
    -- at the output
    fifo_data_input_gen: for i in 0 to INPUT_WORDS-1 generate
        fifo_din(i*(WORD_WIDTH+1) + (WORD_WIDTH-1) downto i*(WORD_WIDTH+1)) <= signal_in_tdata((i*WORD_WIDTH) + (WORD_WIDTH-1) downto i*WORD_WIDTH);
    end generate fifo_data_input_gen;

    -- Clear all bits in between data words at the input, 
    -- except for the highest one which will store tlast
    fifo_din(fifo_din'high) <= signal_in_tlast;
    fifo_tlast_input_gen: for i in 0 to INPUT_WORDS-2 generate
        fifo_din(i*(WORD_WIDTH+1) + WORD_WIDTH) <= '0';
    end generate fifo_tlast_input_gen;
    
    -- Connect the output data signals to the spaced words in the FIFO 
    -- data output
    fifo_data_output_gen: for i in 0 to OUTPUT_WORDS-1 generate
        m_axis_tdata((i*WORD_WIDTH) + (WORD_WIDTH-1) downto (i*WORD_WIDTH)) <= fifo_dout(i*(WORD_WIDTH+1) + (WORD_WIDTH-1) downto i*(WORD_WIDTH+1));
    end generate fifo_data_output_gen;
    
    -- Connect the output "spacer" bits to a vector
    fifo_tlast_output_gen: for i in 0 to OUTPUT_WORDS-1 generate
        fifo_tlast_out(i) <= fifo_dout(i*(WORD_WIDTH+1) + WORD_WIDTH);
    end generate fifo_tlast_output_gen;

    -- Connect the appropriate bit of the output spacer vector
    -- to the output tlast signal
    m_axis_tlast <= fifo_valid and fifo_tlast_out(fifo_tlast_out'high);

    -- Synchronize the reset signal into the output domain
    rst_out_async_gen: if ASYNCHRONOUS = true generate
        xpm_cdc_rst_out_async_inst : xpm_cdc_single
            generic map (
                DEST_SYNC_FF   => 2,
                INIT_SYNC_FF   => 0,
                SIM_ASSERT_CHK => 0,
                SRC_INPUT_REG  => 1
            )
            port map (
                dest_out => rst_output_sync, 
                dest_clk => m_axis_aclk,
                src_clk  => clk,
                src_in   => rst
            );
    end generate rst_out_async_gen;

    rst_out_sync_gen: if ASYNCHRONOUS = false generate
        rst_output_sync <= rst;
    end generate rst_out_sync_gen;

    -- Create a latching error signal in case the tlast signal
    -- appears anywhere except the highest bit of the output
    -- This would correspond to a condition in which the 
    -- stream length was a multiple of INPUT_WORDS but not of 
    -- OUTPUT_WORDS, meaning that the stream could not be popped
    -- from the FIFO in an integer number of cycles
    fifo_misalignment_proc: process(m_axis_aclk) begin
        if rising_edge(m_axis_aclk) then
            if (rst_output_sync = '1') then
                misalignment_latch <= '0';
            elsif (fifo_valid = '1' and or_reduce(fifo_tlast_out(fifo_tlast_out'high downto 0)) = '1') then
                misalignment_latch <= '1';
            end if;
        end if;
    end process fifo_misalignment_proc;

    -- Synchronize the misalignment latch into the monitor domain 
    monitor_sync_fifo_async_gen: if ASYNCHRONOUS = true generate
        xpm_cdc_output_misaligned : xpm_cdc_single
            generic map (
                DEST_SYNC_FF   => 2,
                INIT_SYNC_FF   => 0,
                SIM_ASSERT_CHK => 0,
                SRC_INPUT_REG  => 1
            )
            port map (
                dest_out => output_misaligned, 
                dest_clk => clk,
                src_clk  => m_axis_aclk,
                src_in   => misalignment_latch
            );
    end generate monitor_sync_fifo_async_gen;

    -- Everything is synchronous, no synchronizers necessary
    monitor_sync_fifo_sync_gen: if ASYNCHRONOUS = false generate
        output_misaligned <= misalignment_latch;
    end generate monitor_sync_fifo_sync_gen;

    fifo_gen_async: if ASYNCHRONOUS = true generate
        -- rst synchronous to wr_clk
        -- rd_rst_busy synchronous to rd_clk
        -- overflow synchronous to wr_clk
        -- wr_rst_busy synchronous to wr_clk
        fifo_inst : xpm_fifo_async
            generic map (
                CASCADE_HEIGHT      => 0,
                DOUT_RESET_VALUE    => "0",
                ECC_MODE            => "no_ecc",
                FIFO_MEMORY_TYPE    => MEMORY_TYPE,
                FIFO_READ_LATENCY   => 1,
                FIFO_WRITE_DEPTH    => INPUT_DEPTH,
                FULL_RESET_VALUE    => 0,
                PROG_EMPTY_THRESH   => 10,
                PROG_FULL_THRESH    => 10,
                RD_DATA_COUNT_WIDTH => 1,
                READ_DATA_WIDTH     => OUTPUT_WORDS*(WORD_WIDTH + 1),
                READ_MODE           => "fwft",
                SIM_ASSERT_CHK      => 0, 
                USE_ADV_FEATURES    => "1001", -- Use only the data_valid and overflow signal
                WAKEUP_TIME         => 0,
                WRITE_DATA_WIDTH    => INPUT_WORDS*(WORD_WIDTH + 1),
                WR_DATA_COUNT_WIDTH => 1
            )
            port map (
                rst           => rst,
                
                wr_clk        => clk,
                din           => fifo_din,
                wr_en         => signal_in_tvalid,
                overflow      => fifo_overflow,
                wr_rst_busy   => wr_rst_busy,
    
                rd_clk        => m_axis_aclk,
                dout          => fifo_dout,
                data_valid    => fifo_valid,
                rd_en         => m_axis_tready,
                rd_rst_busy   => rd_rst_busy_sync,
                
                almost_empty  => open,
                almost_full   => open,
                dbiterr       => open,
                empty         => open,
                full          => open,
                prog_empty    => open,
                prog_full     => open,
                rd_data_count => open,
                sbiterr       => open,
                underflow     => open,
                wr_ack        => open,
                wr_data_count => open,
                injectdbiterr => '0',
                injectsbiterr => '0',
                sleep         => '0'   
            );

        xpm_cdc_rd_rst_busy_inst : xpm_cdc_single
            generic map (
                DEST_SYNC_FF => 4,   
                INIT_SYNC_FF => 0,   
                SIM_ASSERT_CHK => 0, 
                SRC_INPUT_REG => 1
            )
            port map (
                dest_out => rd_rst_busy, 
                dest_clk => clk, 
                src_clk => m_axis_aclk, 
                src_in => rd_rst_busy_sync
            );

    end generate fifo_gen_async;
    
    fifo_gen_sync: if ASYNCHRONOUS = false generate
        fifo_inst : xpm_fifo_sync
            generic map (
                CASCADE_HEIGHT      => 0,
                DOUT_RESET_VALUE    => "0",
                ECC_MODE            => "no_ecc",
                FIFO_MEMORY_TYPE    => MEMORY_TYPE,
                FIFO_READ_LATENCY   => 1,
                FIFO_WRITE_DEPTH    => INPUT_DEPTH,
                FULL_RESET_VALUE    => 0,
                PROG_EMPTY_THRESH   => 10,
                PROG_FULL_THRESH    => 10,
                RD_DATA_COUNT_WIDTH => 1,
                READ_DATA_WIDTH     => OUTPUT_WORDS*(WORD_WIDTH + 1),
                READ_MODE           => "fwft",
                SIM_ASSERT_CHK      => 0, 
                USE_ADV_FEATURES    => "1001", -- Use only the data_valid and overflow signal
                WAKEUP_TIME         => 0,
                WRITE_DATA_WIDTH    => INPUT_WORDS*(WORD_WIDTH + 1),
                WR_DATA_COUNT_WIDTH => 1
            )
            port map (
                rst           => rst,
                
                wr_clk        => clk,
                din           => fifo_din,
                wr_en         => signal_in_tvalid,
                overflow      => fifo_overflow,
                wr_rst_busy   => wr_rst_busy,

                dout          => fifo_dout,
                data_valid    => fifo_valid,
                rd_en         => m_axis_tready,
                rd_rst_busy   => rd_rst_busy,
                
                almost_empty  => open,
                almost_full   => open,
                dbiterr       => open,
                empty         => open,
                full          => open,
                prog_empty    => open,
                prog_full     => open,
                rd_data_count => open,
                sbiterr       => open,
                underflow     => open,
                wr_ack        => open,
                wr_data_count => open,
                injectdbiterr => '0',
                injectsbiterr => '0',
                sleep         => '0'   
            );
    end generate fifo_gen_sync;
    
end rtl;