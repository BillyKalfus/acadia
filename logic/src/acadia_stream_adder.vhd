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
-- Description: A module which sums two input AXI-Stream signals.
--    A module that adds every 16-bit word in an input stream to 
--    the corresponding word of another stream driven by a 
--    dedicated DataMover. The width of this dedicated DataMover
--    must be greater than or equal to that of the input stream
--    width, and this width is also that which is used for the 
--    DataMover writing the output to memory.
--    
--    This module has only one register with the following bitfield:
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

entity acadia_stream_adder is
    generic (
        WORDS : positive := 8;

        -- We require that A_WORD_WIDTH <= B_WORD_WIDTH
        -- the output width is B_WORD_WIDTH
        A_WORD_WIDTH    : positive := 16;
        B_WORD_WIDTH    : positive := 32
    );
    port (
        clk : in std_logic;

        a_tdata  : in  std_logic_vector((WORDS*A_WORD_WIDTH)-1 downto 0);
        a_tvalid : in  std_logic;
        a_tready : out std_logic;
        a_tlast  : in  std_logic;
        a_tkeep  : in  std_logic_vector((WORDS*A_WORD_WIDTH/8)-1 downto 0);

        b_tdata  : in  std_logic_vector((WORDS*B_WORD_WIDTH)-1 downto 0);
        b_tvalid : in  std_logic;
        b_tready : out std_logic;
        b_tlast  : in  std_logic;
        b_tkeep  : in  std_logic_vector((WORDS*B_WORD_WIDTH/8)-1 downto 0);
            
        sum_tdata  : out std_logic_vector((WORDS*B_WORD_WIDTH)-1 downto 0);
        sum_tvalid : out std_logic;
        sum_tready : in  std_logic;
        sum_tlast  : out std_logic;
        sum_tkeep  : out std_logic_vector((WORDS*B_WORD_WIDTH/8)-1 downto 0);

        -- Register access
        registers_clk   : in  std_logic;
        registers_mosi  : in  std_logic_vector(31 downto 0);
        registers_miso  : out std_logic_vector(31 downto 0);
        registers_addr  : in  std_logic_vector(31 downto 0);
        registers_we    : in  std_logic;
        registers_en    : in  std_logic        
    );
    
    attribute USE_DSP : string;
end acadia_stream_adder;

architecture rtl of acadia_stream_adder is
    
    attribute USE_DSP of rtl : architecture is "YES";
    
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_PARAMETER of clk: SIGNAL is "ASSOCIATED_BUSIF a:b:sum";

    ATTRIBUTE X_INTERFACE_INFO of a_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 a TDATA";
    ATTRIBUTE X_INTERFACE_INFO of a_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 a TLAST";
    ATTRIBUTE X_INTERFACE_INFO of a_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 a TVALID";
    ATTRIBUTE X_INTERFACE_INFO of a_tready : SIGNAL is "xilinx.com:interface:axis:1.0 a TREADY";
    ATTRIBUTE X_INTERFACE_INFO of a_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 a TKEEP";
    ATTRIBUTE X_INTERFACE_PARAMETER of a_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WORDS*A_WORD_WIDTH/8);
    
    ATTRIBUTE X_INTERFACE_INFO of b_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 b TDATA";
    ATTRIBUTE X_INTERFACE_INFO of b_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 b TLAST";
    ATTRIBUTE X_INTERFACE_INFO of b_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 b TVALID";
    ATTRIBUTE X_INTERFACE_INFO of b_tready : SIGNAL is "xilinx.com:interface:axis:1.0 b TREADY";
    ATTRIBUTE X_INTERFACE_INFO of b_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 b TKEEP";
    ATTRIBUTE X_INTERFACE_PARAMETER of b_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WORDS*B_WORD_WIDTH/8);
    
    ATTRIBUTE X_INTERFACE_INFO of sum_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 sum TDATA";
    ATTRIBUTE X_INTERFACE_INFO of sum_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 sum TLAST";
    ATTRIBUTE X_INTERFACE_INFO of sum_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 sum TVALID";
    ATTRIBUTE X_INTERFACE_INFO of sum_tready : SIGNAL is "xilinx.com:interface:axis:1.0 sum TREADY";
    ATTRIBUTE X_INTERFACE_INFO of sum_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 sum TKEEP";
    ATTRIBUTE X_INTERFACE_MODE of sum_tdata  : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of sum_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WORDS*B_WORD_WIDTH/8);
    
    ATTRIBUTE X_INTERFACE_INFO of registers_clk : SIGNAL is "xilinx.com:interface:bram:1.0 registers CLK";
    ATTRIBUTE X_INTERFACE_INFO of registers_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 registers DIN";
    ATTRIBUTE X_INTERFACE_INFO of registers_miso: SIGNAL is "xilinx.com:interface:bram:1.0 registers DOUT";
    ATTRIBUTE X_INTERFACE_INFO of registers_addr: SIGNAL is "xilinx.com:interface:bram:1.0 registers ADDR";
    ATTRIBUTE X_INTERFACE_INFO of registers_we  : SIGNAL is "xilinx.com:interface:bram:1.0 registers WE";
    ATTRIBUTE X_INTERFACE_INFO of registers_en  : SIGNAL is "xilinx.com:interface:bram:1.0 registers EN";


    signal a_tdata_se   : std_logic_vector((WORDS*B_WORD_WIDTH)-1 downto 0);
    signal buffer_valid : std_logic;


    signal rst       : std_logic;
    signal rst_ext   : std_logic;
    signal tlast_err : std_logic;
    signal range_err : std_logic;
begin

    sum_tkeep <= b_tkeep;

    -- Sign-extend the input words
    a_se_gen: for i in 0 to WORDS-1 generate
        a_tdata_se((i*B_WORD_WIDTH)+A_WORD_WIDTH-1 downto i*B_WORD_WIDTH) <= a_tdata(i*A_WORD_WIDTH + A_WORD_WIDTH-1 downto i*A_WORD_WIDTH);
        a_tdata_se((i*B_WORD_WIDTH)+B_WORD_WIDTH-1 downto (i*B_WORD_WIDTH)+A_WORD_WIDTH) <= (others => a_tdata(i*A_WORD_WIDTH + A_WORD_WIDTH-1));
    end generate a_se_gen;

    -- Indicate to the input masters when we can load data
    -- Note that this creates a combinatorial path between the master
    -- ready signals and the slave ready signals, so this may need to be
    -- replaced with a more pipelined skid buffer if timing isn't met
    a_tready    <= (not buffer_valid) or sum_tready;
    b_tready    <= (not buffer_valid) or sum_tready;
    sum_tvalid  <= buffer_valid;
    
    adder_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                buffer_valid  <= '0';
                sum_tdata     <= (others => '0');
                range_err     <= '0';
                sum_tlast     <= '0';
            elsif(a_tvalid = '1' and b_tvalid = '1' and 
                    (buffer_valid = '0' or sum_tready = '1')) then
                -- Load buffer with new data
                -- We can load the buffer if it's currently empty or if
                -- it's occupied but being read out
                -- TODO: detect range errors
                range_err     <= '0';
                buffer_valid  <= '1';
                sum_tlast     <= a_tlast and b_tlast; 
                add_loop: for i in 0 to WORDS-1 loop
                    sum_tdata(i*B_WORD_WIDTH + B_WORD_WIDTH-1 downto i*B_WORD_WIDTH) 
                        <= std_logic_vector(signed(a_tdata_se(i*B_WORD_WIDTH + B_WORD_WIDTH-1 downto i*B_WORD_WIDTH)) 
                                          + signed(b_tdata(i*B_WORD_WIDTH + B_WORD_WIDTH-1 downto i*B_WORD_WIDTH)));
                end loop add_loop;
            elsif(buffer_valid = '1' and sum_tready = '1') then
                -- There's data in the buffer and it's being read out by the slave
                -- but it's not being refilled by the masters
                buffer_valid <= '0';
                sum_tdata    <= (others => '0');
                sum_tlast    <= '0';
            end if;
        end if;
    end process adder_proc;

    -- Detect stream misalignment
    tlast_err_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                tlast_err <= '0';
            elsif((a_tlast xor b_tlast) = '1') then
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
            WIDTH          => 32
        )
        port map (
            src_clk   => clk,
            src_in(0) => range_err,
            src_in(1) => tlast_err,
            src_in(31 downto 2) => (others => '0'),

            dest_out => registers_miso,
            dest_clk => registers_clk
        );

    rst_ext <= registers_en and registers_we and registers_mosi(2);

    xpm_cdc_rst : xpm_cdc_single
        generic map (
            DEST_SYNC_FF   => 4,   
            INIT_SYNC_FF   => 0,   
            SIM_ASSERT_CHK => 0,
            SRC_INPUT_REG  => 1 
        )
        port map (
            src_clk  => registers_clk,
            src_in   => rst_ext,
            dest_out => rst,
            dest_clk => clk
        );

end rtl;
