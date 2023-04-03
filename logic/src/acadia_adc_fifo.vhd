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
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TDATA";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TVALID";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tready : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TREADY";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TLAST";
    ATTRIBUTE X_INTERFACE_INFO of m_axis_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 m_axis TKEEP";
    ATTRIBUTE X_INTERFACE_MODE of m_axis_tdata  : SIGNAL is "Master";

    signal rst : std_logic;
begin
    
    rst          <= not nrst;
    m_axis_tlast <= '0';
    m_axis_tkeep <= (others => '1');

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
            USE_ADV_FEATURES    => "1000", -- Use only the data_valid signal
            WAKEUP_TIME         => 0,
            WRITE_DATA_WIDTH    => WIDTH,
            WR_DATA_COUNT_WIDTH => 1
        )
        port map (
            wr_clk        => clk,
            rst           => rst,
            
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
            overflow      => open,
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