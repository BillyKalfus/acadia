----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 03/06/2023 04:58:59 PM
-- Design Name: acadia
-- Module Name: acadia_axis_pipeline - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: A simple pipeline register for AXI-Stream interfaces without 
-- backpressure support (tvalid and tready are tied high at both ends).
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

entity acadia_axis_pipeline is
    generic (
        WIDTH  : positive := 128;
        STAGES : integer := 1
    );
    port (
        clk           : in  std_logic;

        m_axis_tdata  : out std_logic_vector(WIDTH-1 downto 0);
        m_axis_tvalid : out std_logic;
        
        s_axis_tdata  : in std_logic_vector(WIDTH-1 downto 0);
        s_axis_tready : out  std_logic
    );
end acadia_axis_pipeline;

architecture rtl of acadia_axis_pipeline is
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TDATA";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TVALID";
    ATTRIBUTE X_INTERFACE_MODE of m_axis_tdata  : SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of s_axis_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 s_axis TDATA";
    ATTRIBUTE X_INTERFACE_INFO of s_axis_tready : SIGNAL is "xilinx.com:interface:axis:1.0 s_axis TREADY";

    ATTRIBUTE X_INTERFACE_PARAMETER of m_axis_tdata: SIGNAL is "HAS_TLAST 0,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 0,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WIDTH/8);


    ATTRIBUTE X_INTERFACE_PARAMETER of clk: SIGNAL is "ASSOCIATED_BUSIF m_axis:s_axis";

    -- Use STAGES+1 because we'll pass through this signal even if we don't do
    -- any pipelining
    signal stage_buffer : unsigned(((STAGES+1)*WIDTH)-1 downto 0);

begin
    
    m_axis_tvalid <= '1';
    s_axis_tready <= '1';

    stage_buffer(WIDTH-1 downto 0) <= unsigned(s_axis_tdata);
    m_axis_tdata <= std_logic_vector(stage_buffer((STAGES*WIDTH)+WIDTH-1 downto (STAGES*WIDTH)));
    
    pipeline_proc: process(clk) begin
        if rising_edge(clk) then
            stage_loop: for s in 0 to STAGES-1 loop
                stage_buffer((s+1)*WIDTH + WIDTH-1 downto (s+1)*WIDTH) <= stage_buffer((s*WIDTH) + WIDTH-1 downto s*WIDTH);
            end loop stage_loop;
        end if;
    end process pipeline_proc;
    
end rtl;