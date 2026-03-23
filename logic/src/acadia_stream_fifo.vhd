----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/25/2022 11:52:49 PM
-- Design Name: acadia
-- Module Name: acadia_stream_fifo - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: 
--     A module wrapping the acadia_backpressure_fifo and providing a register interface for monitoring.
--     
--     This module uses the following registers:
--         
--         Address 0: Control/Status
--             
--             Bits 27-0:  Reserved
--                 Writing has no effect and will always be read as 0.
--             
--             Bit 29 (R): FIFO Overflow
--                 Returns 1 if the FIFO has overflowed. 
--
--             Bit 30 (RW): FIFO Reset
--                 Write 1 to this register to trigger a reset of the FIFO. 
--                 Reading from this register returns 1 if the FIFO is still in reset 
--                 and is unable to be used.
--
--             Bit 31 (W): Internal reset
--                 Writing 1 to this register triggers an internal reset of the module.
--                 Reading from this register returns 1 if the module is still in reset 
--                 and is unable to be used.
--
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

entity acadia_stream_fifo is
    generic (
        WORDS        : positive := 4;
        DEPTH        : positive := 1024;
        PRIMITIVE    : string   := "auto";
        ASYNCHRONOUS : boolean  := true
    );
    port (
        clk                : in  std_logic;
        nrst               : in  std_logic;

        -- Signal input
        data_in_tdata      : in  std_logic_vector((WORDS*32)-1 downto 0);
        data_in_tvalid     : in  std_logic;
        data_in_tready     : out std_logic;
        data_in_tlast      : in  std_logic;
            
        -- Output data stream
        data_out_aclk   : in  std_logic;
        data_out_tdata  : out std_logic_vector((WORDS*32)-1 downto 0);
        data_out_tvalid : out std_logic;
        data_out_tready : in  std_logic;
        data_out_tlast  : out std_logic;
        data_out_tkeep  : out std_logic_vector((WORDS*4)-1 downto 0);

        -- Register access (synchronous to clk)
        registers_mosi  : in  std_logic_vector(31 downto 0);
        registers_miso  : out std_logic_vector(31 downto 0);
        registers_addr  : in  std_logic_vector(31 downto 0);
        registers_we    : in  std_logic;
        registers_en    : in  std_logic
    );
    
    attribute USE_DSP : string;
end acadia_stream_fifo;

architecture rtl of acadia_stream_fifo is
    
    attribute USE_DSP of rtl : architecture is "YES";
    
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_PARAMETER of clk: SIGNAL is "ASSOCIATED_BUSIF data_in:registers";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TDATA";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TLAST";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TVALID";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tready : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TREADY";
    ATTRIBUTE X_INTERFACE_PARAMETER of data_in_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WORDS*4/8);
    
    ATTRIBUTE X_INTERFACE_PARAMETER of data_out_aclk: SIGNAL is "ASSOCIATED_BUSIF data_out";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TDATA";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TLAST";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TVALID";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tready : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TREADY";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TKEEP";
    ATTRIBUTE X_INTERFACE_MODE of data_out_tdata  : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of data_out_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WORDS*4/8);
    
    ATTRIBUTE X_INTERFACE_INFO of registers_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 registers DIN";
    ATTRIBUTE X_INTERFACE_INFO of registers_miso: SIGNAL is "xilinx.com:interface:bram:1.0 registers DOUT";
    ATTRIBUTE X_INTERFACE_INFO of registers_addr: SIGNAL is "xilinx.com:interface:bram:1.0 registers ADDR";
    ATTRIBUTE X_INTERFACE_INFO of registers_we  : SIGNAL is "xilinx.com:interface:bram:1.0 registers WE";
    ATTRIBUTE X_INTERFACE_INFO of registers_en  : SIGNAL is "xilinx.com:interface:bram:1.0 registers EN";

    signal fifo_rst_busy : std_logic;
    signal fifo_rst : std_logic;
    signal fifo_overflow : std_logic;
    
begin

    registers_wr_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                fifo_rst <= '1';
            elsif(registers_en = '1' and registers_we = '1') then
                fifo_rst <= registers_mosi(30) or registers_mosi(31);
            else
                fifo_rst <= '0';
            end if;
        end if;
    end process registers_wr_proc;

    registers_miso <= (29 => fifo_overflow, 30 => fifo_rst_busy, 31 => fifo_rst_busy, others => '0');
    
    -- The FIFO itself
    -- Connect the input and output streams directly to the backpressure FIFO
    data_in_tready <= '1';

    output_fifo: entity work.acadia_backpressure_fifo
        generic map (
            WORD_WIDTH   => 32,
            INPUT_WORDS  => WORDS,
            OUTPUT_WORDS => WORDS,
            INPUT_DEPTH  => DEPTH,
            MEMORY_TYPE  => PRIMITIVE,
            ASYNCHRONOUS => ASYNCHRONOUS
        )
        port map (
            clk => clk,
            rst => fifo_rst,
            rst_busy => fifo_rst_busy,

            overflow          => fifo_overflow,
            output_misaligned => open,
            
            signal_in_tdata  => data_in_tdata,
            signal_in_tvalid => data_in_tvalid,
            signal_in_tlast  => data_in_tlast,
            
            m_axis_aclk      => data_out_aclk,
            m_axis_tdata     => data_out_tdata,
            m_axis_tvalid    => data_out_tvalid,
            m_axis_tready    => data_out_tready,
            m_axis_tlast     => data_out_tlast,
            m_axis_tkeep     => data_out_tkeep
        );

end rtl;
