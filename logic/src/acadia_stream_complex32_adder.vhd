----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/25/2022 11:52:49 PM
-- Design Name: acadia
-- Module Name: acadia_stream_adder - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: 
--    A module that computes sum statistics for a stream of 16-bit SAMPLES.
--    An output stream is produced that contains a 24-bit sum field and a 40-bit 
--    sum-of-squares field for each quadrature. This stream is expected to be fed
--    back into a second input of the module, which will add to the existing stream.
--    
--    This module has only one register with the following bitfields:
--        Bit 0: range error
--        Bit 1: tlast error
--        Bit 2: reset
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

library xpm;
use xpm.vcomponents.all;

entity acadia_stream_complex32_adder is
    generic (
        INPUT_WORDS    : positive := 4;
        SAMPLES_FIFO_DEPTH        : positive := 1024;
        SAMPLES_FIFO_PRIMITIVE    : string   := "auto";
        SAMPLES_FIFO_ASYNCHRONOUS : boolean  := true;
        
        STATS_WIDTH  : positive := 256
    );
    port (
        samples_clk : in std_logic;

        samples_tdata  : in  std_logic_vector((INPUT_WORDS*32)-1 downto 0);
        samples_tvalid : in  std_logic;
        samples_tready : out std_logic;
        samples_tlast  : in  std_logic;

        stats_clk : in std_logic;
        
        stats_in_tdata  : in  std_logic_vector(STATS_WIDTH-1 downto 0);
        stats_in_tvalid : in  std_logic;
        stats_in_tready : out std_logic;
        stats_in_tlast  : in  std_logic;
        stats_in_tkeep  : in  std_logic_vector((STATS_WIDTH/8)-1 downto 0);
            
        stats_out_tdata  : out std_logic_vector(STATS_WIDTH-1 downto 0);
        stats_out_tvalid : out std_logic;
        stats_out_tready : in  std_logic;
        stats_out_tlast  : out std_logic;
        stats_out_tkeep  : out std_logic_vector((STATS_WIDTH/8)-1 downto 0);

        -- Register access        
        registers_mosi  : in  std_logic_vector(31 downto 0);
        registers_miso  : out std_logic_vector(31 downto 0);
        registers_addr  : in  std_logic_vector(31 downto 0);
        registers_we    : in  std_logic;
        registers_en    : in  std_logic        
    );
    
    attribute USE_DSP : string;
end acadia_stream_complex32_adder;

architecture rtl of acadia_stream_complex32_adder is
    
    attribute USE_DSP of rtl : architecture is "YES";
    
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_PARAMETER of samples_clk: SIGNAL is "ASSOCIATED_BUSIF samples:registers";

    ATTRIBUTE X_INTERFACE_INFO of samples_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 samples TDATA";
    ATTRIBUTE X_INTERFACE_INFO of samples_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 samples TLAST";
    ATTRIBUTE X_INTERFACE_INFO of samples_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 samples TVALID";
    ATTRIBUTE X_INTERFACE_INFO of samples_tready : SIGNAL is "xilinx.com:interface:axis:1.0 samples TREADY";
    ATTRIBUTE X_INTERFACE_PARAMETER of samples_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(INPUT_WORDS*4);
    
    ATTRIBUTE X_INTERFACE_PARAMETER of stats_clk: SIGNAL is "ASSOCIATED_BUSIF stats_in:stats_out";
    
    ATTRIBUTE X_INTERFACE_INFO of stats_in_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 stats_in TDATA";
    ATTRIBUTE X_INTERFACE_INFO of stats_in_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 stats_in TLAST";
    ATTRIBUTE X_INTERFACE_INFO of stats_in_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 stats_in TVALID";
    ATTRIBUTE X_INTERFACE_INFO of stats_in_tready : SIGNAL is "xilinx.com:interface:axis:1.0 stats_in TREADY";
    ATTRIBUTE X_INTERFACE_INFO of stats_in_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 stats_in TKEEP";
    ATTRIBUTE X_INTERFACE_PARAMETER of stats_in_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(STATS_WIDTH/8);
    
    ATTRIBUTE X_INTERFACE_INFO of stats_out_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 stats_out TDATA";
    ATTRIBUTE X_INTERFACE_INFO of stats_out_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 stats_out TLAST";
    ATTRIBUTE X_INTERFACE_INFO of stats_out_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 stats_out TVALID";
    ATTRIBUTE X_INTERFACE_INFO of stats_out_tready : SIGNAL is "xilinx.com:interface:axis:1.0 stats_out TREADY";
    ATTRIBUTE X_INTERFACE_INFO of stats_out_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 stats_out TKEEP";
    ATTRIBUTE X_INTERFACE_MODE of stats_out_tdata  : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of stats_out_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(STATS_WIDTH/8);
        
    ATTRIBUTE X_INTERFACE_INFO of registers_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 registers DIN";
    ATTRIBUTE X_INTERFACE_INFO of registers_miso: SIGNAL is "xilinx.com:interface:bram:1.0 registers DOUT";
    ATTRIBUTE X_INTERFACE_INFO of registers_addr: SIGNAL is "xilinx.com:interface:bram:1.0 registers ADDR";
    ATTRIBUTE X_INTERFACE_INFO of registers_we  : SIGNAL is "xilinx.com:interface:bram:1.0 registers WE";
    ATTRIBUTE X_INTERFACE_INFO of registers_en  : SIGNAL is "xilinx.com:interface:bram:1.0 registers EN";

    -- We have some extra bits in the statistics fields so that we can accumulate many samples
    -- Each quadrature gets half the data signal width, and each quadrature has both a sum
    -- and a sum-of-squares field. Any leftover bits after accounting for the base widths will be
    -- equally divided among the two fields for each quadrature
    constant EXTRA_BITS       : natural := ((STATS_WIDTH/2) - (18 + 36)) / 2;
    constant SUM_RE_OFFSET    : natural := 0;
    constant SUM_IM_OFFSET    : natural := SUM_RE_OFFSET + 18 + EXTRA_BITS;
    constant SUM_SQ_RE_OFFSET : natural := SUM_IM_OFFSET + 18 + EXTRA_BITS;
    constant SUM_SQ_IM_OFFSET : natural := SUM_SQ_RE_OFFSET + 36 + EXTRA_BITS;

    signal rst       : std_logic;
    signal rst_ext   : std_logic;
    signal tlast_err : std_logic;
    signal range_err : std_logic;
    signal samples_fifo_overflow : std_logic;
    
    signal input_sum_re : signed(17 downto 0);
    signal input_sum_im : signed(17 downto 0);
    signal input_sum_valid : std_logic;
    signal input_sum_last : std_logic;
    
    signal input_sum_buffered_re : std_logic_vector(17 downto 0);
    signal input_sum_buffered_im : std_logic_vector(17 downto 0);
    signal input_sum_buffered_valid : std_logic;
    signal input_sum_buffered_last : std_logic;
    signal input_sum_buffered_ready : std_logic;

    -- Processing pipeline

    -- Stage 1: Register everything
    signal stats_in_sum_re_d       : signed(18 + EXTRA_BITS - 1 downto 0);
    signal stats_in_sum_im_d       : signed(18 + EXTRA_BITS - 1 downto 0);
    signal stats_in_sq_re_d        : signed(36 + EXTRA_BITS - 1 downto 0);
    signal stats_in_sq_im_d        : signed(36 + EXTRA_BITS - 1 downto 0);
    signal input_sum_buffered_re_d : signed(17 downto 0);
    signal input_sum_buffered_im_d : signed(17 downto 0);
    
    signal stage1_valid            : std_logic;
    signal stage1_last             : std_logic;

    -- Stage 2: Register the inputs again and compute the square
    signal stats_in_sum_re_dd       : signed(18 + EXTRA_BITS - 1 downto 0);
    signal stats_in_sum_im_dd       : signed(18 + EXTRA_BITS - 1 downto 0);
    signal stats_in_sq_re_dd        : signed(36 + EXTRA_BITS - 1 downto 0);
    signal stats_in_sq_im_dd        : signed(36 + EXTRA_BITS - 1 downto 0);
    signal input_sum_buffered_re_dd : signed(17 downto 0);
    signal input_sum_buffered_im_dd : signed(17 downto 0);
    signal sq_buffered_re           : signed(35 downto 0);
    signal sq_buffered_im           : signed(35 downto 0);

    signal stage2_valid             : std_logic;
    signal stage2_last              : std_logic;

    -- Pipeline control flags
    signal pipeline_advance : std_logic;
    signal pipeline_output_valid : std_logic;

begin
    stats_out_tkeep <= stats_in_tkeep;
    
    -- Use variables and a loop to sum all the inputs
    input_sum_proc: process(samples_clk)
        variable sum_re : signed(17 downto 0); 
        variable sum_im : signed(17 downto 0); 
    begin
        if rising_edge(samples_clk) then
            sum_re := (others => '0');
            sum_im := (others => '0');
            sum_loop: for i in 0 to INPUT_WORDS-1 loop
                sum_re := sum_re + resize(signed(samples_tdata((i*32) + 15 downto (i*32))), 18);
                sum_im := sum_im + resize(signed(samples_tdata((i*32) + 31 downto (i*32) + 16)), 18);
            end loop sum_loop;

            -- Now update the outputs with the varables
            input_sum_re <= sum_re;
            input_sum_im <= sum_im;
        end if;
    end process input_sum_proc;
    
    samples_fifo: entity work.acadia_backpressure_fifo
        generic map (
            WORD_WIDTH   => 18 + 18,
            INPUT_WORDS  => 1,
            OUTPUT_WORDS => 1,
            INPUT_DEPTH  => SAMPLES_FIFO_DEPTH,
            MEMORY_TYPE  => SAMPLES_FIFO_PRIMITIVE,
            ASYNCHRONOUS => SAMPLES_FIFO_ASYNCHRONOUS,
            MONITOR_SYNC => true  -- Set to true if monitor_clk is synchronous to signal_in_clk
        )
        port map (
            signal_in_clk    => samples_clk,
            signal_in_rst    => rst_ext,

            -- A port for monitoring the status of the FIFO and resetting it
            monitor_clk      => samples_clk,
            monitor_rst      => rst_ext,
            monitor_overflow => samples_fifo_overflow,
            monitor_misalignment => open,
            
            signal_in_tdata(17 downto 0)  => std_logic_vector(input_sum_re),
            signal_in_tdata(35 downto 18) => std_logic_vector(input_sum_im),
            signal_in_tvalid => input_sum_valid,
            signal_in_tlast  => input_sum_last,
            
            m_axis_aclk      => stats_clk,
            m_axis_tdata(17 downto 0)  => input_sum_buffered_re,
            m_axis_tdata(35 downto 18) => input_sum_buffered_im,
            m_axis_tvalid    => input_sum_buffered_valid,
            m_axis_tready    => input_sum_buffered_ready,
            m_axis_tlast     => input_sum_buffered_last,
            m_axis_tkeep     => open
        );

    -- Indicate to the input masters when we can load data
    -- Note that this creates a combinatorial path between the master
    -- ready signals and the slave ready signals, so this may need to be
    -- replaced with a more pipelined skid buffer if timing isn't met
    pipeline_advance <= (not pipeline_output_valid) or stats_out_tready;
    stats_out_tvalid <= pipeline_output_valid;
    
    stats_proc: process(stats_clk) begin
        if rising_edge(stats_clk) then
            if(rst = '1') then
                stage1_valid          <= '0';
                stage1_last           <= '0';
                stage2_valid          <= '0';
                stage2_last           <= '0';
                pipeline_output_valid <= '0';
                stats_out_tlast       <= '0';
            elsif(pipeline_advance <= '1') then
                -- Stage 1: Register everything
                stats_in_sum_re_d       <= signed(stats_in_tdata(SUM_RE_OFFSET + 18 + EXTRA_BITS - 1 downto SUM_RE_OFFSET));
                stats_in_sum_im_d       <= signed(stats_in_tdata(SUM_IM_OFFSET + 18 + EXTRA_BITS - 1 downto SUM_IM_OFFSET));
                stats_in_sq_re_d        <= signed(stats_in_tdata(SUM_SQ_RE_OFFSET + 36 + EXTRA_BITS - 1 downto SUM_SQ_RE_OFFSET));
                stats_in_sq_im_d        <= signed(stats_in_tdata(SUM_SQ_IM_OFFSET + 36 + EXTRA_BITS - 1 downto SUM_SQ_IM_OFFSET));
                input_sum_buffered_re_d <= signed(input_sum_buffered_re);
                input_sum_buffered_im_d <= signed(input_sum_buffered_im);
                
                stage1_valid            <= input_sum_buffered_valid and stats_in_tvalid;
                stage1_last             <= input_sum_buffered_last and stats_in_tlast;

                -- Stage 2: Register the inputs again and compute the square
                stats_in_sum_re_dd       <= stats_in_sum_re_d;
                stats_in_sum_im_dd       <= stats_in_sum_im_d;
                stats_in_sq_re_dd        <= stats_in_sq_re_d;
                stats_in_sq_im_dd        <= stats_in_sq_im_d;
                input_sum_buffered_re_dd <= input_sum_buffered_re_d;
                input_sum_buffered_im_dd <= input_sum_buffered_im_d;
                sq_buffered_re           <= input_sum_buffered_re_d * input_sum_buffered_re_d;
                sq_buffered_im           <= input_sum_buffered_im_d * input_sum_buffered_im_d;

                stage2_valid             <= stage1_valid;
                stage2_last              <= stage1_last;

                -- Stage 3: Add the input statistics to the current sample
                stats_out_tdata(SUM_RE_OFFSET + stats_in_sum_re_dd'length - 1 downto SUM_RE_OFFSET) <= std_logic_vector(stats_in_sum_re_dd + resize(input_sum_buffered_re_dd, stats_in_sum_re_dd'length));
                stats_out_tdata(SUM_IM_OFFSET + stats_in_sum_im_dd'length - 1 downto SUM_IM_OFFSET) <= std_logic_vector(stats_in_sum_im_dd + resize(input_sum_buffered_im_dd, stats_in_sum_im_dd'length));
                stats_out_tdata(SUM_SQ_RE_OFFSET + stats_in_sq_re_dd'length - 1 downto SUM_SQ_RE_OFFSET) <= std_logic_vector(stats_in_sq_re_dd + resize(sq_buffered_re, stats_in_sq_re_dd'length));
                stats_out_tdata(SUM_SQ_IM_OFFSET + stats_in_sq_im_dd'length - 1 downto SUM_SQ_IM_OFFSET) <= std_logic_vector(stats_in_sq_im_dd + resize(sq_buffered_im, stats_in_sq_im_dd'length));
                pipeline_output_valid <= stage2_valid;
                stats_out_tlast  <= stage2_last;
                
                -- TODO: actually detect range errors
                range_err <= '0';
            end if;
        end if;
    end process stats_proc;

    -- Detect stream misalignment
    -- We signal an error if the two streams both have valid data but only one reports
    -- it as last
    tlast_err_proc: process(stats_clk) begin
        if rising_edge(stats_clk) then
            if(rst = '1') then
                tlast_err <= '0';
            elsif((input_sum_buffered_last xor stats_in_tlast) = '1' and input_sum_buffered_valid = '1' and stats_in_tvalid = '1') then
                tlast_err <= '1';
            end if;
        end if;
    end process tlast_err_proc;

    -- Expose the error signals through a CDC
    xpm_cdc_registers_miso : xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF   => 4,   
            INIT_SYNC_FF   => 0,   
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1, 
            WIDTH          => 2
        )
        port map (
            src_clk   => stats_clk,
            src_in(0) => range_err,
            src_in(1) => tlast_err,

            dest_out => registers_miso(1 downto 0),
            dest_clk => samples_clk
        );
        
    registers_miso(2) <= samples_fifo_overflow;
    registers_miso(31 downto 3) <= (others => '0');

    rst_ext <= registers_en and registers_we and registers_mosi(2);

    xpm_cdc_rst : xpm_cdc_single
        generic map (
            DEST_SYNC_FF   => 4,   
            INIT_SYNC_FF   => 0,   
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1 
        )
        port map (
            src_clk  => samples_clk,
            src_in   => rst_ext,
            dest_out => rst,
            dest_clk => stats_clk
        );

end rtl;
