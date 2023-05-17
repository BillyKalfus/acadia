----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 03/06/2023 04:58:59 PM
-- Design Name: acadia
-- Module Name: acadia_adc_fifo - rtl
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
use IEEE.NUMERIC_STD.ALL;

library xpm;
use xpm.vcomponents.all;

entity acadia_adc_fifo is
    generic (
        WIDTH         : positive := 128;
        DEPTH         : positive := 512;
        TKEEP_WIDTH   : positive := 16
    );
    port (
        clk           : in  std_logic;
        nrst          : in  std_logic;
        
        overflow      : out std_logic;
         
        din           : in  std_logic_vector(WIDTH-1 downto 0);
        wr_en         : in  std_logic;
        
        m_axis_tdata  : out std_logic_vector(WIDTH-1 downto 0);
        m_axis_tvalid : out std_logic;
        m_axis_tready : in  std_logic;
        m_axis_tlast  : out std_logic;
        m_axis_tkeep  : out std_logic_vector(TKEEP_WIDTH-1 downto 0)
    );
end acadia_adc_fifo;

architecture rtl of acadia_adc_fifo is
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TDATA";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TVALID";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tready : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TREADY";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TLAST";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TKEEP";
    ATTRIBUTE X_INTERFACE_MODE of m_axis_tdata  : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of m_axis_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(WIDTH/8);

    ATTRIBUTE X_INTERFACE_PARAMETER of clk: SIGNAL is "ASSOCIATED_BUSIF m_axis";
        
    signal rst          : std_logic;
    signal overflow_int : std_logic;
begin
    
    rst          <= not nrst;
    m_axis_tlast <= '0';
    m_axis_tkeep <= (others => '1');

    -- Latch the overflow signal so that we can know if it happened at any point during the capture
    overflow_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                overflow <= '0';
            elsif(overflow_int = '1') then
                overflow <= '1';
            end if;
        end if;
    end process overflow_proc;

    fifo_inst : xpm_fifo_sync
        generic map (
            CASCADE_HEIGHT      => 0,
            DOUT_RESET_VALUE    => "0",
            ECC_MODE            => "no_ecc",
            FIFO_MEMORY_TYPE    => "auto",
            FIFO_READ_LATENCY   => 1,
            FIFO_WRITE_DEPTH    => DEPTH,
            FULL_RESET_VALUE    => 0,
            PROG_EMPTY_THRESH   => 10,
            PROG_FULL_THRESH    => 10,
            RD_DATA_COUNT_WIDTH => 1,
            READ_DATA_WIDTH     => WIDTH,
            READ_MODE           => "fwft",
            SIM_ASSERT_CHK      => 0,      -- DECIMAL; 0=disable simulation messages, 1=enable simulation messages
            USE_ADV_FEATURES    => "1001", -- Use only the data_valid and overflow signal
            WAKEUP_TIME         => 0,
            WRITE_DATA_WIDTH    => WIDTH,
            WR_DATA_COUNT_WIDTH => 1
        )
        port map (
            wr_clk        => clk,
            rst           => rst,
            
            overflow      => overflow_int,
            
            din           => din,
            wr_en         => wr_en,

            dout          => m_axis_tdata,
            data_valid    => m_axis_tvalid,
            rd_en         => m_axis_tready,
            
            almost_empty  => open,
            almost_full   => open,
            dbiterr       => open,
            empty         => open,
            full          => open,
            prog_empty    => open,
            prog_full     => open,
            rd_data_count => open,
            rd_rst_busy   => open,
            sbiterr       => open,
            underflow     => open,
            wr_ack        => open,
            wr_data_count => open,
            wr_rst_busy   => open,
            injectdbiterr => '0',
            injectsbiterr => '0',
            sleep         => '0'   
        );
    
end rtl;