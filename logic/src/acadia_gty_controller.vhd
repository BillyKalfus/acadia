----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 10/07/2023 03:53:08 PM
-- Design Name: 
-- Module Name: acadia_gty_controller - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2023.2
-- Description: A lightweight module for interface GTY transceivers to a 
--    memory bus. 
--
--
--    AXI control register 0: Reset and initialization settings
--
--        Bit 0: w: gtwiz_userclk_tx_reset
--               r: gtwiz_userclk_tx_active
--
--        Bit 1: w: gtwiz_userclk_rx_reset
--               r: gtwiz_userclk_rx_active
--        
--        Bit 2: w: gtwiz_reset_all
--               r: gtwiz_reset_rx_cdr_stable
--
--        Bit 3: w: gtwiz_reset_tx_pll_and_datapath
--               r: gtwiz_reset_tx_done
--          
--        Bit 4: w: gtwiz_reset_tx_datapath
--               r: txpmaresetdone
--
--        Bit 5: w: gtwiz_reset_rx_pll_and_datapath
--               r: gtwiz_reset_rx_done
--
--        Bit 6: w: gtwiz_reset_rx_datapath
--               r: rxpmaresetdone
--
--        Bit 7: w: no effect
--               r: rxprgdivresetdone
--
--        Bit 8: w: no effect
--               r: gtpowergood
--
--        Bits 30-9: Reserved
--
--        Bit 31: w: Controller reset (write 1 to take controller out of reset)
--                r: 0
--
--    AXI control register 1: PRBS 
--
--        Bits 3-0: w: rxprbssel
--                  r: 0
--
--        Bits 7-4: w: txprbssel
--                  r: 0
--        
--        Bit 8:  w: rxprbserr (write 1 to clear, writing 0 has no effect)
--                r: rxprbserr (latched)
--       
--        Bit 9:  w: no effect
--                r: rxprbslocked
--        
--        Bits 31-10: Reserved
--
--    AXI control register 2: Alignment and FIFO control/status
--
--        Bit 0: w: rxcommadeten
--               r: 0
--
--        Bit 1: w: rxmcommaalignen
--               r: 0
--        
--        Bit 2: w: rxpcommaalignen
--               r: 0
--
--        Bit 3: w: rxcommadet (write 1 to clear, writing 0 has no effect)
--               r: rxcommadet (latched)
-- 
--        Bit 4: w: rxbyterealign (write 1 to clear, writing 0 has no effect)
--               r: rxbyterealign (latched)
--
--        Bit 5: w: no effect
--               r: rxbyteisaligned
--
--        Bit 6: w: Send message with K28.5 header
--               r: Send message with K28.5 header
--
--        Bit 7: Reserved
--
--        Bit 8: w: Channel 0 RX FIFO overflow (write 1 to clear, writing 0 has no effect)
--               r: Channel 0 RX FIFO overflow (latched)
--        
--        Bit 9: w: Channel 0 RX FIFO reset
--               r: Channel 0 RX FIFO reset busy
--
--        Bit 10: w: Channel 0 RX FIFO enable
--                r: Channel 0 RX FIFO enable
--
--        Bit 11: Reserved
--
--        Bit 12: w: Channel 0 TX FIFO overflow (write 1 to clear, writing 0 has no effect)
--                r: Channel 0 TX FIFO overflow (latched)
--        
--        Bit 13: w: Channel 0 TX FIFO reset
--                r: Channel 0 TX FIFO reset busy
--
--        Bit 14: Reserved
--
--        Bit 15: Reserved
--
--        Bit 16: w: Channel 1 RX FIFO overflow (write 1 to clear, writing 0 has no effect)
--                r: Channel 1 RX FIFO overflow (latched)
--        
--        Bit 17: w: Channel 1 RX FIFO reset
--                r: Channel 1 RX FIFO reset busy
--
--        Bit 18: w: Channel 1 RX FIFO enable
--                r: Channel 1 RX FIFO enable
--
--        Bit 19: Reserved
--
--        Bit 20: w: Channel 1 TX FIFO overflow (write 1 to clear, writing 0 has no effect)
--                r: Channel 1 TX FIFO overflow (latched)
--        
--        Bit 21: w: Channel 1 TX FIFO reset
--                r: Channel 1 TX FIFO reset busy
--
--        Bit 22: Reserved
--
--        Bit 23: Reserved
--
--        Bit 24: w: Received K character in invalid location (write 1 to clear, writing 0 has no effect)
--                r: Received K character in invalid location (latched) 
--
--        Bit 25: w: Received message without header K character (write 1 to clear, writing 0 has no effect)
--                r: Received message without header K character (latched) 
--
--        Bit 26: w: Received disparity error (write 1 to clear, writing 0 has no effect)
--                r: Received disparity error (latched) 
--
--        Bit 27: w: Received invalid data (write 1 to clear, writing 0 has no effect)
--                r: Received invalid data (latched) 
--
--        Bits 31-28: Reserved
--
--    AXI control register 3: Channel 1 data interface
--
--        Bits 3-0: w: If writing a value with bit 4 set, then this data is pushed to the Channel 1 TX FIFO.
--                  r: If the read register value has bit 6 set, then these bits are valid data presented at the output of the Channel 1 RX FIFO.
--                     Bit 5 must be written to pop the data from the FIFO and retrieve a new word (if available).
--
--        Bit 4: w: If set, then the data in bits 3-0 are pushed to the Channel 1 TX FIFO. 
--                  This occurs for only one cycle, and a 0 must be written before another word is sent.
--               r: 0
--
--        Bit 5: w: If set, then the data in the Channel 1 RX FIFO are popped. 
--                  This occurs for only one cycle, and a 0 must be written before another word is popped.
--               r: 0
--
--        Bit 6: w: No effect
--               r: If set, there is valid data present at Channel 1 RX FIFO output.
--
--        Bit 7: w: No effect
--               r: Channel 1 TX FIFO full
--
--        Bits 31-8: Reserved
--
--
--
--    Reading from bus address 0 returns a status word with the following bit fields:
--     
--        Bit 0: w: no effect
--               r: RX FIFO empty
--
--        Bit 1: w: no effect
--               r: RX FIFO overflow
--
--        Bit 2: w: no effect
--               r: TX FIFO full
--
--    Data FIFOs are available over the bus: 
--
--        Register 1: w: TX FIFO
--                    r: no effect
--
--        Register 2: w: no effect
--                    r: RX FIFO
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
use IEEE.STD_LOGIC_MISC.ALL;

library xpm;
use xpm.vcomponents.all;

library UNISIM;
use UNISIM.vcomponents.all;

entity acadia_gty_controller is
    generic (
        FIFO_DEPTH   : positive := 16;
        AXI_ADDRESS_BITS : positive := 4
    );
    port (
        -- Fabric clocks
        clk_freerun   : in std_logic;

        -- AXI-Lite configuration port
        s_axi_aclk    : in  std_logic;
        s_axi_aresetn : in  std_logic;
        
        -- AXI write address
        s_axi_awaddr  : in  std_logic_vector(AXI_ADDRESS_BITS-1 downto 0);
        s_axi_awvalid : in  std_logic;
        s_axi_awready : out std_logic; 

        -- AXI write
        s_axi_wdata   : in  std_logic_vector(31 downto 0);
        s_axi_wstrb   : in  std_logic_vector(3 downto 0);
        s_axi_wvalid  : in  std_logic;
        s_axi_wready  : out std_logic;

        -- AXI write response
        s_axi_bresp   : out std_logic_vector(1 downto 0);
        s_axi_bvalid  : out std_logic;
        s_axi_bready  : in  std_logic;

        -- AXI read address
        s_axi_araddr  : in  std_logic_vector(AXI_ADDRESS_BITS-1 downto 0);
        s_axi_arready : out std_logic;
        s_axi_arvalid : in  std_logic;

        -- AXI read
        s_axi_rdata   : out std_logic_vector(31 downto 0);
        s_axi_rresp   : out std_logic_vector(1 downto 0);
        s_axi_rvalid  : out std_logic;
        s_axi_rready  : in  std_logic;

        -- Bus interface for real-time data
        master_bus_clk   : in  std_logic;
        master_bus_mosi  : in  std_logic_vector(31 downto 0);
        master_bus_miso  : out std_logic_vector(31 downto 0);
        master_bus_addr  : in  std_logic_vector(31 downto 0);
        master_bus_we    : in  std_logic;
        master_bus_en    : in  std_logic;

        -- GT physical interface
        MGT128_C0_tx_p : out std_logic;
        MGT128_C0_tx_n : out std_logic;
        MGT128_C0_rx_p : in  std_logic;
        MGT128_C0_rx_n : in  std_logic;

        MGT128_refclk0_p : out std_logic;
        MGT128_refclk0_n : out std_logic;
        MGT128_refclk1_p : in  std_logic;
        MGT128_refclk1_n : in  std_logic;

        -- Clocks produced by the GT
        MGT128_txusrclk2 : out std_logic;
        MGT128_rxusrclk2 : out std_logic
    );
end acadia_gty_controller;

architecture rtl of acadia_gty_controller is

    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of master_bus_clk : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus CLK";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_we  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";

    ATTRIBUTE X_INTERFACE_INFO of MGT128_C0_tx_p  : SIGNAL is "xilinx.com:interface:gt_rtl:1.0 MGT128_C0 GTX_P";
    ATTRIBUTE X_INTERFACE_INFO of MGT128_C0_tx_n  : SIGNAL is "xilinx.com:interface:gt_rtl:1.0 MGT128_C0 GTX_N";
    ATTRIBUTE X_INTERFACE_INFO of MGT128_C0_rx_p  : SIGNAL is "xilinx.com:interface:gt_rtl:1.0 MGT128_C0 GRX_P";
    ATTRIBUTE X_INTERFACE_INFO of MGT128_C0_rx_n  : SIGNAL is "xilinx.com:interface:gt_rtl:1.0 MGT128_C0 GRX_N";
    ATTRIBUTE X_INTERFACE_MODE of MGT128_C0_tx_p  : SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of MGT128_refclk0_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 MGT128_refclk0 CLK_P";
    ATTRIBUTE X_INTERFACE_INFO of MGT128_refclk0_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 MGT128_refclk0 CLK_N";
    ATTRIBUTE X_INTERFACE_MODE of MGT128_refclk0_p : SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of MGT128_refclk1_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 MGT128_refclk1 CLK_P";
    ATTRIBUTE X_INTERFACE_INFO of MGT128_refclk1_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 MGT128_refclk1 CLK_N";
    ATTRIBUTE X_INTERFACE_MODE of MGT128_refclk1_p : SIGNAL is "Slave";

    ATTRIBUTE X_INTERFACE_INFO of s_axi_aclk      : SIGNAL is "xilinx.com:signal:clock:1.0 s_axi_aclk CLK";
    ATTRIBUTE X_INTERFACE_PARAMETER of s_axi_aclk : SIGNAL is "ASSOCIATED_BUSIF s_axi";
    
    ATTRIBUTE X_INTERFACE_INFO of s_axi_awaddr  : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi AWADDR";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_awvalid : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi AWVALID";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_awready : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi AWREADY";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_wdata   : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi WDATA";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_wstrb   : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi WSTRB";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_wvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi WVALID";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_wready  : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi WREADY";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_bresp   : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi BRESP";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_bvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi BVALID";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_bready  : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi BREADY";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_araddr  : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi ARADDR";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_arvalid : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi ARVALID";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_arready : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi ARREADY";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_rdata   : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi RDATA";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_rresp   : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi RRESP";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_rvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi RVALID";
    ATTRIBUTE X_INTERFACE_INFO of s_axi_rready  : SIGNAL is "xilinx.com:interface:aximm:1.0 s_axi RREADY";
    ATTRIBUTE X_INTERFACE_PARAMETER of s_axi_awaddr: SIGNAL is "PROTOCOL AXI4LITE";

    component gtwizard_ultrascale_128
        port (
            gtwiz_userclk_tx_active_in         : in std_logic_vector(0 downto 0);
            gtwiz_userclk_rx_active_in         : in std_logic_vector(0 downto 0);
            gtwiz_reset_clk_freerun_in         : in std_logic_vector(0 downto 0);
            gtwiz_reset_all_in                 : in std_logic_vector(0 downto 0);
            gtwiz_reset_tx_pll_and_datapath_in : in std_logic_vector(0 downto 0);
            gtwiz_reset_tx_datapath_in         : in std_logic_vector(0 downto 0);
            gtwiz_reset_rx_pll_and_datapath_in : in std_logic_vector(0 downto 0);
            gtwiz_reset_rx_datapath_in         : in std_logic_vector(0 downto 0);
            gtwiz_reset_rx_cdr_stable_out      : out std_logic_vector(0 downto 0);
            gtwiz_reset_tx_done_out            : out std_logic_vector(0 downto 0);
            gtwiz_reset_rx_done_out            : out std_logic_vector(0 downto 0);

            gtwiz_userdata_tx_in  : in std_logic_vector(31 downto 0);
            gtwiz_userdata_rx_out : out std_logic_vector(31 downto 0);

            gtrefclk00_in         : in std_logic_vector(0 downto 0);
            qpll0lockdetclk_in    : in std_logic_vector(0 downto 0);
            qpll0locken_in        : in std_logic_vector(0 downto 0);
            qpll0fbclklost_out    : out std_logic_vector(0 downto 0);
            qpll0lock_out         : out std_logic_vector(0 downto 0);
            qpll0outclk_out       : out std_logic_vector(0 downto 0);
            qpll0outrefclk_out    : out std_logic_vector(0 downto 0);
            qpll0refclklost_out   : out std_logic_vector(0 downto 0);
            gtyrxn_in             : in std_logic_vector(0 downto 0);
            gtyrxp_in             : in std_logic_vector(0 downto 0);
            rx8b10ben_in          : in std_logic_vector(0 downto 0);
            rxcommadeten_in       : in std_logic_vector(0 downto 0);
            rxmcommaalignen_in    : in std_logic_vector(0 downto 0);
            rxpcommaalignen_in    : in std_logic_vector(0 downto 0);
            rxprbscntreset_in     : in std_logic_vector(0 downto 0);
            rxprbssel_in          : in std_logic_vector(3 downto 0);
            rxusrclk_in           : in std_logic_vector(0 downto 0);
            rxusrclk2_in          : in std_logic_vector(0 downto 0);
            tx8b10ben_in          : in std_logic_vector(0 downto 0);
            txctrl0_in            : in std_logic_vector(15 downto 0);
            txctrl1_in            : in std_logic_vector(15 downto 0);
            txctrl2_in            : in std_logic_vector(7 downto 0);
            txprbssel_in          : in std_logic_vector(3 downto 0);
            txusrclk_in           : in std_logic_vector(0 downto 0);
            txusrclk2_in          : in std_logic_vector(0 downto 0);
            gtpowergood_out       : out std_logic_vector(0 downto 0);
            gtytxn_out            : out std_logic_vector(0 downto 0);
            gtytxp_out            : out std_logic_vector(0 downto 0);
            rxbyteisaligned_out   : out std_logic_vector(0 downto 0);
            rxbyterealign_out     : out std_logic_vector(0 downto 0);
            rxcommadet_out        : out std_logic_vector(0 downto 0);
            rxctrl0_out           : out std_logic_vector(15 downto 0);
            rxctrl1_out           : out std_logic_vector(15 downto 0);
            rxctrl2_out           : out std_logic_vector(7 downto 0);
            rxctrl3_out           : out std_logic_vector(7 downto 0);
            rxoutclk_out          : out std_logic_vector(0 downto 0);
            rxpmaresetdone_out    : out std_logic_vector(0 downto 0);
            rxprbserr_out         : out std_logic_vector(0 downto 0);
            rxprbslocked_out      : out std_logic_vector(0 downto 0);
            -- rxprgdivresetdone_out : out std_logic_vector(0 downto 0);
            rxrecclkout_out       : out std_logic_vector(0 downto 0);
            txoutclk_out          : out std_logic_vector(0 downto 0);
            txpmaresetdone_out    : out std_logic_vector(0 downto 0)
        );
    end component;

    signal master_bus_clk_nrst : std_logic;
    signal rxusrclk2_nrst      : std_logic;

    -- Internally-registered control signals and their counterparts 
    -- in the corresponding MGT domain
    signal rxcommadeten_axi    : std_logic;
    signal rxcommadeten_mgt    : std_logic;
    signal rxmcommaalignen_axi : std_logic;
    signal rxmcommaalignen_mgt : std_logic;
    signal rxpcommaalignen_axi : std_logic;
    signal rxpcommaalignen_mgt : std_logic;
    signal rxprbssel_axi       : std_logic_vector(3 downto 0);
    signal rxprbssel_mgt       : std_logic_vector(3 downto 0);
    signal txprbssel_axi       : std_logic_vector(3 downto 0);
    signal txprbssel_mgt       : std_logic_vector(3 downto 0);

    -- Latched status signals
    -- Signals with _axi suffix are in the s_axi_aclk domain, 
    -- signals with the _mgt suffix are in the rx_int_clk domain, 
    -- and signals with the _latch suffix are latches in the rx_int_clk domain
    signal rxcommadet_axi       : std_logic;
    signal rxcommadet_clear_axi : std_logic;
    signal rxcommadet_mgt       : std_logic;
    signal rxcommadet_clear_mgt : std_logic;
    signal rxcommadet_latch     : std_logic;
    
    signal rxbyterealign_axi       : std_logic;
    signal rxbyterealign_clear_axi : std_logic;
    signal rxbyterealign_mgt       : std_logic;
    signal rxbyterealign_clear_mgt : std_logic;
    signal rxbyterealign_latch     : std_logic;
    
    signal rxprbserr_axi       : std_logic;
    signal rxprbserr_clear_axi : std_logic;
    signal rxprbserr_mgt       : std_logic;
    signal rxprbserr_clear_mgt : std_logic;
    signal rxprbserr_latch     : std_logic;

    signal ch0_rx_fifo_overflow_axi       : std_logic;
    signal ch0_rx_fifo_overflow_clear_axi : std_logic;
    signal ch0_rx_fifo_overflow_mgt       : std_logic;
    signal ch0_rx_fifo_overflow_clear_mgt : std_logic;
    signal ch0_rx_fifo_overflow_latch     : std_logic;

    signal ch0_tx_fifo_overflow_axi       : std_logic;
    signal ch0_tx_fifo_overflow_clear_axi : std_logic;
    signal ch0_tx_fifo_overflow_mgt       : std_logic;
    signal ch0_tx_fifo_overflow_clear_mgt : std_logic;
    signal ch0_tx_fifo_overflow_latch     : std_logic;

    signal ch1_rx_fifo_overflow_axi       : std_logic;
    signal ch1_rx_fifo_overflow_clear_axi : std_logic;
    signal ch1_rx_fifo_overflow_mgt       : std_logic;
    signal ch1_rx_fifo_overflow_clear_mgt : std_logic;
    signal ch1_rx_fifo_overflow_latch     : std_logic;

    signal ch1_tx_fifo_overflow_axi       : std_logic;
    signal ch1_tx_fifo_overflow_clear_axi : std_logic;
    signal ch1_tx_fifo_overflow_mgt       : std_logic;
    signal ch1_tx_fifo_overflow_clear_mgt : std_logic;
    signal ch1_tx_fifo_overflow_latch     : std_logic;

    signal rx_k_char_invalid_location_axi       : std_logic;
    signal rx_k_char_invalid_location_clear_axi : std_logic;
    signal rx_k_char_invalid_location_mgt       : std_logic;
    signal rx_k_char_invalid_location_clear_mgt : std_logic;
    signal rx_k_char_invalid_location_latch     : std_logic;

    signal rx_data_without_k_header_axi       : std_logic;
    signal rx_data_without_k_header_clear_axi : std_logic;
    signal rx_data_without_k_header_mgt       : std_logic;
    signal rx_data_without_k_header_clear_mgt : std_logic;
    signal rx_data_without_k_header_latch     : std_logic;

    signal rx_any_disparity_error_axi       : std_logic;
    signal rx_any_disparity_error_clear_axi : std_logic;
    signal rx_any_disparity_error_mgt       : std_logic;
    signal rx_any_disparity_error_clear_mgt : std_logic;
    signal rx_any_disparity_error_latch     : std_logic;

    signal rx_any_invalid_data_axi       : std_logic;
    signal rx_any_invalid_data_clear_axi : std_logic;
    signal rx_any_invalid_data_mgt       : std_logic;
    signal rx_any_invalid_data_clear_mgt : std_logic;
    signal rx_any_invalid_data_latch     : std_logic;
    
    -- K28 contants
    constant K28_0 : std_logic_vector(7 downto 0) := "00011100";
    constant K28_1 : std_logic_vector(7 downto 0) := "00111100";
    constant K28_2 : std_logic_vector(7 downto 0) := "01011100";
    constant K28_3 : std_logic_vector(7 downto 0) := "01111100";
    constant K28_4 : std_logic_vector(7 downto 0) := "10011100";
    constant K28_5 : std_logic_vector(7 downto 0) := "10111100";
    constant K28_6 : std_logic_vector(7 downto 0) := "11011100";
    constant K23_7 : std_logic_vector(7 downto 0) := "11110111";
    constant K27_7 : std_logic_vector(7 downto 0) := "11111011";
    constant K29_7 : std_logic_vector(7 downto 0) := "11111101";
    constant K30_7 : std_logic_vector(7 downto 0) := "11111110";
    
    -- Other register signals
    signal send_k285_axi : std_logic;
    signal send_k285_mgt : std_logic;
    
    signal ch0_rx_fifo_din : std_logic_vector(15 downto 0);
    signal ch0_rx_fifo_dout : std_logic_vector(15 downto 0);
    signal ch0_rx_fifo_rst_axi : std_logic;
    signal ch0_rx_fifo_rst_busy_axi : std_logic;
    signal ch0_rx_fifo_en_axi : std_logic;
    signal ch0_rx_fifo_en_mgt : std_logic;
    signal ch0_rx_fifo_wr_en : std_logic;
    
    signal ch0_tx_fifo_din : std_logic_vector(15 downto 0);
    signal ch0_tx_fifo_dout : std_logic_vector(15 downto 0);
    signal ch0_tx_fifo_rst_axi : std_logic;
    signal ch0_tx_fifo_rst_busy_axi : std_logic;
    signal ch0_tx_fifo_data_valid : std_logic;
    
    signal ch1_rx_fifo_dout : std_logic_vector(3 downto 0);
    signal ch1_rx_fifo_din  : std_logic_vector(3 downto 0);
    signal ch1_rx_fifo_rst_axi : std_logic;
    signal ch1_rx_fifo_rst_mgt : std_logic;
    signal ch1_rx_fifo_rst_busy_axi : std_logic;
    signal ch1_rx_fifo_rd_rst_busy : std_logic;
    signal ch1_rx_fifo_wr_rst_busy_axi : std_logic;
    signal ch1_rx_fifo_wr_rst_busy_mgt : std_logic;
    signal ch1_rx_fifo_en_axi : std_logic;
    signal ch1_rx_fifo_en_mgt : std_logic;
    signal ch1_rx_fifo_wr_en : std_logic;
    signal ch1_rx_fifo_rd_en : std_logic;
    
    signal ch1_tx_fifo_din  : std_logic_vector(3 downto 0);
    signal ch1_tx_fifo_dout  : std_logic_vector(3 downto 0);
    signal ch1_tx_fifo_wr_en : std_logic;
    signal ch1_tx_fifo_rst_axi : std_logic;
    signal ch1_tx_fifo_rst_busy_axi : std_logic;
    signal ch1_tx_fifo_data_valid : std_logic;
    signal ch1_tx_fifo_rd_rst_busy_mgt : std_logic;
    signal ch1_tx_fifo_rd_rst_busy_axi : std_logic;
    signal ch1_tx_fifo_wr_rst_busy : std_logic;
    
    signal ch1_rx_fifo_rd_en_reg : std_logic;
    signal ch1_rx_fifo_rd_en_reg_d : std_logic;
    signal ch1_tx_fifo_wr_en_reg : std_logic;
    signal ch1_tx_fifo_wr_en_reg_d : std_logic;
    
    signal ch1_rx_fifo_data_valid : std_logic;
    signal ch1_tx_fifo_full : std_logic;
    
    -- Message fields
    signal message_header: std_logic_vector(7 downto 0);
    signal valid_message : std_logic;
    signal header_k28 : std_logic;
    signal valid_data_in_message : std_logic;

    -- Non-latched status
    signal rxprbslocked_axi    : std_logic;
    signal rxprbslocked_mgt    : std_logic;
    signal rxbyteisaligned_axi : std_logic;
    signal rxbyteisaligned_mgt : std_logic;

    signal rx_is_k_char          : std_logic_vector(15 downto 0);
    signal rx_disparity_error    : std_logic_vector(15 downto 0);
    signal rx_invalid_data_error : std_logic_vector(7 downto 0);
    signal rx_comma_detected     : std_logic_vector(7 downto 0);

    signal tx_is_k_char          : std_logic_vector(3 downto 0);

    signal gt_txdata : std_logic_vector(31 downto 0);
    signal gt_rxdata : std_logic_vector(31 downto 0);

    signal MGT128_txusrclk2_int  : std_logic;
    signal MGT128_rxusrclk2_int  : std_logic;
    signal MGT128_refclk00       : std_logic;
    signal MGT128_rxrecclkout    : std_logic;
    signal MGT128_rxoutclk       : std_logic;
    signal MGT128_txoutclk       : std_logic;

    signal axi_regs_in  : std_logic_vector(127 downto 0);
    signal axi_regs_out : std_logic_vector(127 downto 0);

    -- Asynchronous outputs from the MGT that connect to the AXI registers
    signal userclk_tx_active_mgt   : std_logic;
    signal userclk_tx_active_axi   : std_logic;
    signal userclk_rx_active_mgt   : std_logic;
    signal userclk_rx_active_axi   : std_logic;
    signal reset_rx_cdr_stable_mgt : std_logic;
    signal reset_rx_cdr_stable_axi : std_logic;
    signal reset_tx_done_mgt       : std_logic;
    signal reset_tx_done_axi       : std_logic;
    signal txpmaresetdone_mgt      : std_logic;
    signal txpmaresetdone_axi      : std_logic;
    signal reset_rx_done_mgt       : std_logic;
    signal reset_rx_done_axi       : std_logic;
    signal rxpmaresetdone_mgt      : std_logic;
    signal rxpmaresetdone_axi      : std_logic;
    -- signal rxprgdivresetdone_mgt   : std_logic;
    -- signal rxprgdivresetdone_axi   : std_logic;
    signal gtpowergood_mgt         : std_logic;
    signal gtpowergood_axi         : std_logic;
    
    signal qpll0fbclklost_mgt : std_logic;
    signal qpll0fbclklost_axi : std_logic;
    signal qpll0lock_mgt : std_logic;
    signal qpll0lock_axi : std_logic;
    signal qpll0refclklost_mgt : std_logic;
    signal qpll0refclklost_axi : std_logic;

    -- Asynchronous inputs to the MGT from the AXI registers
    signal userclk_tx_reset_axi          : std_logic;
    signal userclk_tx_reset_mgt          : std_logic;
    signal userclk_rx_reset_axi          : std_logic;
    signal userclk_rx_reset_mgt          : std_logic;
    signal reset_all_axi                 : std_logic;
    signal reset_all_mgt                 : std_logic;
    signal reset_tx_pll_and_datapath_axi : std_logic;
    signal reset_tx_pll_and_datapath_mgt : std_logic;
    signal reset_tx_datapath_axi         : std_logic;
    signal reset_tx_datapath_mgt         : std_logic;
    signal reset_rx_pll_and_datapath_axi : std_logic;
    signal reset_rx_pll_and_datapath_mgt : std_logic;
    signal reset_rx_datapath_axi         : std_logic;
    signal reset_rx_datapath_mgt         : std_logic;

begin

    regs_inst: entity work.acadia_axi_lite_regs
        generic map (
            N_REGS => 4,
            AXI_ADDRESS_BITS => AXI_ADDRESS_BITS
        )
        port map (
            s_axi_aclk    => s_axi_aclk,
            s_axi_aresetn => s_axi_aresetn,
            
            s_axi_awaddr  => s_axi_awaddr,
            s_axi_awvalid => s_axi_awvalid,
            s_axi_awready => s_axi_awready,
            s_axi_wdata   => s_axi_wdata,
            s_axi_wstrb   => s_axi_wstrb,
            s_axi_wvalid  => s_axi_wvalid,
            s_axi_wready  => s_axi_wready,
            s_axi_bresp   => s_axi_bresp,
            s_axi_bvalid  => s_axi_bvalid,
            s_axi_bready  => s_axi_bready,
            s_axi_araddr  => s_axi_araddr,
            s_axi_arready => s_axi_arready,
            s_axi_arvalid => s_axi_arvalid,
            s_axi_rdata   => s_axi_rdata,
            s_axi_rresp   => s_axi_rresp,
            s_axi_rvalid  => s_axi_rvalid,
            s_axi_rready  => s_axi_rready,

            -- Register interface
            regs_out      => axi_regs_out,
            regs_in       => axi_regs_in
        );

    -- Assign signals to/from the AXI registers 
    -- Register 0
    userclk_tx_reset_axi          <= axi_regs_out(0);
    userclk_rx_reset_axi          <= axi_regs_out(1);
    reset_all_axi                 <= axi_regs_out(2);
    reset_tx_pll_and_datapath_axi <= axi_regs_out(3);
    reset_tx_datapath_axi         <= axi_regs_out(4);
    reset_rx_pll_and_datapath_axi <= axi_regs_out(5);
    reset_rx_datapath_axi         <= axi_regs_out(6);
            
    axi_regs_in(0) <= userclk_tx_active_axi;
    axi_regs_in(1) <= userclk_rx_active_axi;
    axi_regs_in(2) <= reset_rx_cdr_stable_axi;
    axi_regs_in(3) <= reset_tx_done_axi;
    axi_regs_in(4) <= txpmaresetdone_axi;
    axi_regs_in(5) <= reset_rx_done_axi;
    axi_regs_in(6) <= rxpmaresetdone_axi;
    axi_regs_in(7) <= '0'; --rxprgdivresetdone_axi;
    axi_regs_in(8) <= gtpowergood_axi;
    axi_regs_in(9) <= qpll0lock_axi;
    axi_regs_in(10) <= qpll0refclklost_axi;
    axi_regs_in(11) <= qpll0fbclklost_axi;

    -- Register 1
    rxprbssel_axi <= axi_regs_out(3+32 downto 0+32);
    txprbssel_axi <= axi_regs_out(7+32 downto 4+32);

    axi_regs_in(8+32) <= rxprbserr_axi;
    rxprbserr_clear_axi <= axi_regs_out(8+32);

    axi_regs_in(9+32) <= rxprbslocked_axi;

    -- Register 2
    rxcommadeten_axi    <= axi_regs_out(0+64);
    rxmcommaalignen_axi <= axi_regs_out(1+64);
    rxpcommaalignen_axi <= axi_regs_out(2+64);

    axi_regs_in(3+64) <= rxcommadet_axi;
    rxcommadet_clear_axi <= axi_regs_out(3+64);

    axi_regs_in(4+64) <= rxbyterealign_axi;
    rxbyterealign_clear_axi <= axi_regs_out(4+64);

    axi_regs_in(5+64) <= rxbyteisaligned_axi;

    send_k285_axi <= axi_regs_out(6+64);
    axi_regs_in(6+64) <= send_k285_axi;

    axi_regs_in(8+64) <= ch0_rx_fifo_overflow_axi;
    ch0_rx_fifo_overflow_clear_axi <= axi_regs_out(8+64);

    ch0_rx_fifo_rst_axi <= axi_regs_out(9+64);
    axi_regs_in(9+64) <= ch0_rx_fifo_rst_busy_axi;

    ch0_rx_fifo_en_axi <= axi_regs_out(10+64);
    axi_regs_in(10+64) <= ch0_rx_fifo_en_axi;


    axi_regs_in(12+64) <= ch0_tx_fifo_overflow_axi;
    ch0_tx_fifo_overflow_clear_axi <= axi_regs_out(12+64);

    ch0_tx_fifo_rst_axi <= axi_regs_out(13+64);
    axi_regs_in(13+64) <= ch0_tx_fifo_rst_busy_axi;


    axi_regs_in(16+64) <= ch1_rx_fifo_overflow_axi;
    ch1_rx_fifo_overflow_clear_axi <= axi_regs_out(16+64);

    ch1_rx_fifo_rst_axi <= axi_regs_out(17+64);
    axi_regs_in(17+64) <= ch1_rx_fifo_rst_busy_axi;

    ch1_rx_fifo_en_axi <= axi_regs_out(18+64);
    axi_regs_in(18+64) <= ch1_rx_fifo_en_axi;


    axi_regs_in(20+64) <= ch1_tx_fifo_overflow_axi;
    ch1_tx_fifo_overflow_clear_axi <= axi_regs_out(20+64);

    ch1_tx_fifo_rst_axi <= axi_regs_out(21+64);
    axi_regs_in(21+64) <= ch1_tx_fifo_rst_busy_axi;



    axi_regs_in(24+64) <= rx_k_char_invalid_location_axi;
    rx_k_char_invalid_location_clear_axi <= axi_regs_out(24+64);

    axi_regs_in(25+64) <= rx_data_without_k_header_axi;
    rx_data_without_k_header_clear_axi <= axi_regs_out(25+64);

    axi_regs_in(26+64) <= rx_any_disparity_error_axi;
    rx_any_disparity_error_clear_axi <= axi_regs_out(26+64);

    axi_regs_in(27+64) <= rx_any_invalid_data_axi;
    rx_any_invalid_data_clear_axi <= axi_regs_out(27+64);

    -- Register 3
    axi_regs_in(3+96 downto 0+96) <= ch1_rx_fifo_dout;
    ch1_tx_fifo_din <= axi_regs_out(3+96 downto 0+96);

    ch1_tx_fifo_wr_en_reg <= axi_regs_out(4+96);

    ch1_rx_fifo_rd_en_reg <= axi_regs_out(5+96);

    axi_regs_in(6+96) <= ch1_rx_fifo_data_valid;
    axi_regs_in(7+96) <= ch1_tx_fifo_full;

    -- These signals are asynchronous so they can just be connected
    -- Asynchronous
    reset_all_mgt                 <= reset_all_axi;
    reset_tx_pll_and_datapath_mgt <= reset_tx_pll_and_datapath_axi;
    reset_tx_datapath_mgt         <= reset_tx_datapath_axi;
    reset_rx_pll_and_datapath_mgt <= reset_rx_pll_and_datapath_axi;
    reset_rx_datapath_mgt         <= reset_rx_datapath_axi;

    -- We'll use synchronous reset synchronizers to synchronize the assorted 
    -- asynchronous outputs from the MGT to the AXI clock domain
    -- This is really just a lazy way of making the flip-flop stages in the AXI clock domain
    -- and applying the appropriate constraints

    reset_rx_cdr_stable_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => reset_rx_cdr_stable_mgt, dest_rst => reset_rx_cdr_stable_axi, dest_clk => s_axi_aclk);

    reset_tx_done_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => reset_tx_done_mgt, dest_rst => reset_tx_done_axi, dest_clk => s_axi_aclk);

    txpmaresetdone_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => txpmaresetdone_mgt, dest_rst => txpmaresetdone_axi, dest_clk => s_axi_aclk);

    reset_rx_done_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => reset_rx_done_mgt, dest_rst => reset_rx_done_axi, dest_clk => s_axi_aclk);

    rxpmaresetdone_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => rxpmaresetdone_mgt, dest_rst => rxpmaresetdone_axi, dest_clk => s_axi_aclk);

    --rxprgdivresetdone_sync: xpm_cdc_sync_rst 
        --generic map(SIM_ASSERT_CHK => 1) 
        --port map(src_rst => rxprgdivresetdone_mgt, dest_rst => rxprgdivresetdone_axi, dest_clk => s_axi_aclk);

    gtpowergood_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => gtpowergood_mgt, dest_rst => gtpowergood_axi, dest_clk => s_axi_aclk);
        
    qpll0lock_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => qpll0lock_mgt, dest_rst => qpll0lock_axi, dest_clk => s_axi_aclk);
        
    qpll0refclklost_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => qpll0refclklost_mgt, dest_rst => qpll0refclklost_axi, dest_clk => s_axi_aclk);
        
    qpll0fbclklost_sync: xpm_cdc_sync_rst 
        generic map(SIM_ASSERT_CHK => 1) 
        port map(src_rst => qpll0fbclklost_mgt, dest_rst => qpll0fbclklost_axi, dest_clk => s_axi_aclk);
    
    -- Synchronize signals from the AXI registers into the 
    -- appropriate MGT domains
    control_rxusrclk2_sync: xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF => 4,
            INIT_SYNC_FF => 0,
            SIM_ASSERT_CHK => 1,
            SRC_INPUT_REG => 0,
            WIDTH => 16
        )
        port map (
            src_clk => s_axi_aclk,
            src_in(0) => rxcommadeten_axi,
            src_in(1) => rxmcommaalignen_axi,
            src_in(2) => rxpcommaalignen_axi,
            src_in(6 downto 3) => rxprbssel_axi,
            src_in(7) => rxprbserr_clear_axi,
            src_in(8) => rxbyterealign_clear_axi,
            src_in(9) => rxcommadet_clear_axi,
            src_in(10) => ch0_rx_fifo_overflow_clear_axi,
            src_in(11) => ch1_rx_fifo_overflow_clear_axi,
            src_in(12) => rx_k_char_invalid_location_clear_axi,
            src_in(13) => rx_data_without_k_header_clear_axi,
            src_in(14) => rx_any_disparity_error_clear_axi,
            src_in(15) => rx_any_invalid_data_clear_axi,


            dest_clk => MGT128_rxusrclk2_int,
            dest_out(0) => rxcommadeten_mgt,
            dest_out(1) => rxmcommaalignen_mgt,
            dest_out(2) => rxpcommaalignen_mgt,
            dest_out(6 downto 3) => rxprbssel_mgt,
            dest_out(7) => rxprbserr_clear_mgt,
            dest_out(8) => rxbyterealign_clear_mgt,
            dest_out(9) => rxcommadet_clear_mgt,
            dest_out(10) => ch0_rx_fifo_overflow_clear_mgt,
            dest_out(11) => ch1_rx_fifo_overflow_clear_mgt,
            dest_out(12) => rx_k_char_invalid_location_clear_mgt,
            dest_out(13) => rx_data_without_k_header_clear_mgt,
            dest_out(14) => rx_any_disparity_error_clear_mgt,
            dest_out(15) => rx_any_invalid_data_clear_mgt
        );

    control_txusrclk2_sync: xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF => 4,
            INIT_SYNC_FF => 0,
            SIM_ASSERT_CHK => 1,
            SRC_INPUT_REG => 0,
            WIDTH => 4
        )
        port map (
            src_clk => master_bus_clk,
            src_in(3 downto 0) => txprbssel_axi,

            dest_clk => MGT128_txusrclk2_int,
            dest_out(3 downto 0) => txprbssel_mgt
        );

    -- Set or reset latches in the rxusrclk2 domain
    rxusrclk2_latches_proc: process(MGT128_rxusrclk2_int) begin
        if rising_edge(MGT128_rxusrclk2_int) then
            rxcommadet_latch <= (rxcommadet_latch or rxcommadet_mgt) and not rxcommadet_clear_mgt;
            rxbyterealign_latch <= (rxbyterealign_latch or rxbyterealign_mgt) and not rxbyterealign_clear_mgt;
            rxprbserr_latch <= (rxprbserr_latch or rxprbserr_mgt) and not rxprbserr_clear_mgt;
            ch0_rx_fifo_overflow_latch <= (ch0_rx_fifo_overflow_latch or ch0_rx_fifo_overflow_mgt) and not ch0_rx_fifo_overflow_clear_mgt;
            ch1_rx_fifo_overflow_latch <= (ch1_rx_fifo_overflow_latch or ch1_rx_fifo_overflow_mgt) and not ch1_rx_fifo_overflow_clear_mgt;
            rx_k_char_invalid_location_latch <= (rx_k_char_invalid_location_latch or rx_k_char_invalid_location_mgt) and not rx_k_char_invalid_location_clear_mgt;
            rx_data_without_k_header_latch <= (rx_data_without_k_header_latch or rx_data_without_k_header_mgt) and not rx_data_without_k_header_clear_mgt;
            rx_any_disparity_error_latch <= (rx_any_disparity_error_latch or rx_any_disparity_error_mgt) and not rx_any_disparity_error_clear_mgt;
            rx_any_invalid_data_latch <= (rx_any_invalid_data_latch or rx_any_invalid_data_mgt) and not rx_any_invalid_data_clear_mgt;
        end if;
    end process rxusrclk2_latches_proc;

    -- Transfer the latched status signals back into the AXI domain
    latch_sync: xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF => 4,
            INIT_SYNC_FF => 0,
            SIM_ASSERT_CHK => 1,
            SRC_INPUT_REG => 0,
            WIDTH => 9
        )
        port map (
            src_clk => MGT128_rxusrclk2_int,
            src_in(0) => rxcommadet_latch,
            src_in(1) => rxbyterealign_latch,
            src_in(2) => rxprbserr_latch,
            src_in(3) => ch0_rx_fifo_overflow_latch,
            src_in(4) => ch1_rx_fifo_overflow_latch,
            src_in(5) => rx_k_char_invalid_location_latch,
            src_in(6) => rx_data_without_k_header_latch,
            src_in(7) => rx_any_disparity_error_latch,
            src_in(8) => rx_any_invalid_data_latch,

            dest_clk => s_axi_aclk,
            dest_out(0) => rxcommadet_axi,
            dest_out(1) => rxbyterealign_axi,
            dest_out(2) => rxprbserr_axi,
            dest_out(3) => ch0_rx_fifo_overflow_axi,
            dest_out(4) => ch1_rx_fifo_overflow_axi,
            dest_out(5) => rx_k_char_invalid_location_axi,
            dest_out(6) => rx_data_without_k_header_axi,
            dest_out(7) => rx_any_disparity_error_axi,
            dest_out(8) => rx_any_invalid_data_axi
        );

    -- Transfer non-latched status signals from the gt back into the AXI clock domain
    status_sync: xpm_cdc_array_single
        generic map (
            DEST_SYNC_FF => 4,
            INIT_SYNC_FF => 0,
            SIM_ASSERT_CHK => 1,
            SRC_INPUT_REG => 0,
            WIDTH => 2
        )
        port map (
            src_clk => MGT128_rxusrclk2_int,
            src_in(0) => rxprbslocked_mgt,
            src_in(1) => rxbyteisaligned_mgt,

            dest_clk => s_axi_aclk,
            dest_out(0) => rxprbslocked_axi,
            dest_out(1) => rxbyteisaligned_axi
        );

    -- Clock buffers
    MGT128_refclk1_ibufds: IBUFDS_GTE4 
        port map (
            O => MGT128_refclk00,
            ODIV2 => open,
            CEB => '0',
            I => MGT128_refclk1_p,
            IB => MGT128_refclk1_n
        );

    MGT128_refclk0_obufds: OBUFDS_GTE4
        generic map (
            REFCLK_EN_TX_PATH => '1',
            REFCLK_ICNTL_TX   => "00111"
        )
        port map (
            I   => MGT128_rxrecclkout,
            CEB => '0',
            O   => MGT128_refclk0_p,
            OB  => MGT128_refclk0_n
        );

    -- We denote the clock as being active as long as its BUFG is not held in reset
    -- The CLR input to the BUFG_GT is asynchronous, 
    -- so we can connect it directly to the AXI register
    -- The gtwiz reset controller block needs a "clock active" signal,
    -- and the product guide notes that this port is asynchronous.
    -- This makes sense, since inside the reset helper block, it immediately
    -- enters a synchronizer and gets synchronized to the clk_freerun domain.
    -- Note that the auto-generated clocking block synchronizes 
    -- this signal to the rxusrclk2 domain, which seems unnecessary.


    userclk_rx_active_axi <= not userclk_rx_reset_axi;

    MGT128_rxusrclk_bufg: BUFG_GT
        port map (
            CE => '1',
            CEMASK => '0',
            CLR => userclk_rx_reset_axi,
            CLRMASK => '0',
            DIV => "000",
            I => MGT128_rxoutclk,
            O => MGT128_rxusrclk2_int
        );

    MGT128_rxusrclk2 <= MGT128_rxusrclk2_int;

    
    userclk_tx_active_axi <= not userclk_tx_reset_axi;

    MGT128_txusrclk_bufg: BUFG_GT
        port map (
            CE => '1',
            CEMASK => '0',
            CLR => userclk_tx_reset_axi,
            CLRMASK => '0',
            DIV => "000",
            I => MGT128_txoutclk,
            O => MGT128_txusrclk2_int
        );

    MGT128_txusrclk2 <= MGT128_txusrclk2_int;

    gty_inst : gtwizard_ultrascale_128
        port map (
            -- Clock active signals
            -- Asynchronous
            gtwiz_userclk_tx_active_in(0)         => userclk_tx_active_axi,
            gtwiz_userclk_rx_active_in(0)         => userclk_rx_active_axi,

            -- Free-running clock for the reset helper block
            gtwiz_reset_clk_freerun_in(0)         => clk_freerun,

            -- Triggers for different pathways in the reset helper block
            -- Asynchronous
            gtwiz_reset_all_in(0)                 => reset_all_mgt,
            gtwiz_reset_tx_pll_and_datapath_in(0) => reset_tx_pll_and_datapath_mgt,
            gtwiz_reset_tx_datapath_in(0)         => reset_tx_datapath_mgt,
            gtwiz_reset_rx_pll_and_datapath_in(0) => reset_rx_pll_and_datapath_mgt,
            gtwiz_reset_rx_datapath_in(0)         => reset_rx_datapath_mgt,

            -- 8b10b and comma detection
            -- These connect directly to corresponding ports on the transceiver primitives
            -- Synchronous to TXUSRCLK2
            tx8b10ben_in(0) => '1',
            
            -- These are all synchronous to RXUSRCLK2
            rx8b10ben_in(0)       => '1',
            rxcommadeten_in(0)    => rxcommadeten_mgt,
            rxmcommaalignen_in(0) => rxmcommaalignen_mgt,
            rxpcommaalignen_in(0) => rxpcommaalignen_mgt,
            rxbyterealign_out(0)  => rxbyterealign_mgt,
            rxcommadet_out(0)     => rxcommadet_mgt,

            -- PRBS control and status
            -- These connect directly to corresponding ports on the transceiver primitives
            -- Synchronous to TXUSRCLK2
            txprbssel_in => txprbssel_mgt,

            -- These are all synchronous to RXUSRCLK2
            rxprbscntreset_in(0) => '0',
            rxprbssel_in => rxprbssel_mgt,
            rxprbserr_out(0) => rxprbserr_mgt,
            rxprbslocked_out(0) => rxprbslocked_mgt,
            rxbyteisaligned_out(0) => rxbyteisaligned_mgt,
            

            -- Status signals
            -- Synchronous to gtwiz_reset_clk_freerun_in
            gtwiz_reset_rx_cdr_stable_out(0) => reset_rx_cdr_stable_mgt,
            -- Synchronous to TXUSRCLK2
            gtwiz_reset_tx_done_out(0)       => reset_tx_done_mgt,
            -- Connects to corresponding port on transceiver primitive
            -- Asynchronous
            txpmaresetdone_out(0)            => txpmaresetdone_mgt,
            -- Synchronous to RXUSRCLK2
            gtwiz_reset_rx_done_out(0)       => reset_rx_done_mgt,
            -- Connects to corresponding port on transceiver primitive
            -- Asynchronous
            rxpmaresetdone_out(0)            => rxpmaresetdone_mgt,
            -- Connects to corresponding port on transceiver primitive
            -- Asynchronous
            -- rxprgdivresetdone_out(0)         => rxprgdivresetdone_mgt,
            -- Connects to corresponding port on transceiver primitive
            -- Asynchronous
            gtpowergood_out(0)               => gtpowergood_mgt,

            -- When the 8b10b decoder is enabled, the rxctrl signals behave as follows:
            --   If a valid K character is received, the corresponding bit of rxctrl0 is set.
            --   If positive comma detection is enabled and the positive comma is received, the corresponding bit of rxctrl2 is set. Same for negative comma.
            --   If a valid character with incorrect disparity is received, the corresponding bit of rxctrl1 is set.
            --   If an invalid character is received, the corresponding bit of rxctrl3 is set.
            -- These connect to the corresponding ports of the transceiver
            -- Synchronous to RXUSRCLK2
            rxctrl0_out  => rx_is_k_char,
            rxctrl1_out  => rx_disparity_error,
            rxctrl2_out  => rx_comma_detected,
            rxctrl3_out  => rx_invalid_data_error,

            -- These connect to the corresponding ports of the transceiver
            -- Synchronous to RXUSRCLK2
            txctrl0_in => x"0000",
            txctrl1_in => x"0000",
            txctrl2_in(3 downto 0) => tx_is_k_char,
            txctrl2_in(7 downto 4) => x"0",

            -- QPLL signals
            qpll0lockdetclk_in(0)  => clk_freerun,
            qpll0locken_in         => "1",
            qpll0fbclklost_out(0)  => qpll0fbclklost_mgt,
            qpll0lock_out(0)       => qpll0lock_mgt,
            qpll0outclk_out        => open,
            qpll0outrefclk_out     => open,
            qpll0refclklost_out(0) => qpll0refclklost_mgt,

            -- Clocks
            rxoutclk_out(0)    => MGT128_rxoutclk,
            rxusrclk_in(0)     => MGT128_rxusrclk2_int,
            rxusrclk2_in(0)    => MGT128_rxusrclk2_int,
            rxrecclkout_out(0) => MGT128_rxrecclkout,
            txoutclk_out(0)    => MGT128_txoutclk,
            txusrclk_in(0)     => MGT128_txusrclk2_int,
            txusrclk2_in(0)    => MGT128_txusrclk2_int,

            -- Data interface
            gtwiz_userdata_tx_in  => gt_txdata,
            gtwiz_userdata_rx_out => gt_rxdata,
            
            -- Physical connections
            gtyrxn_in(0)     => MGT128_C0_rx_n,
            gtyrxp_in(0)     => MGT128_C0_rx_p,
            gtytxn_out(0)    => MGT128_C0_tx_n,
            gtytxp_out(0)    => MGT128_C0_tx_p,
            gtrefclk00_in(0) => MGT128_refclk00
        );

        -- Message format:
        --   Bits 7-0: Comma and control
        --       K28.0 - no data valid
        --       K28.1 - channel 0 valid, channel 1 invalid
        --       K28.2 - channel 0 invalid, channel 1 valid
        --       K28.3 - channel 0 valid, channel 1 valid
        --       K28.4 - no data valid
        --       K28.5 - no data valid
        --       K28.6 - no data valid
        --   Bits 23-8: Channel 0 Data
        --   Bits 27-24: Channel 1 Data
        --   Bits 31-28: Reserved
        
        ----------------- RX MESSAGE PROCESSING --------------------
        -- Take the data at the RX interface of the MGT, determine whether there's any
        -- valid data, and if there is, push to the appropriate FIFOs

        -- Signals for aggregating errors
        rx_k_char_invalid_location_mgt <= or_reduce(rx_is_k_char(3 downto 1));
        rx_data_without_k_header_mgt <= not rx_is_k_char(0);
        rx_any_disparity_error_mgt <= or_reduce(rx_disparity_error(3 downto 0));
        rx_any_invalid_data_mgt <= or_reduce(rx_invalid_data_error(3 downto 0));

        -- Partition the data output
        message_header <= gt_rxdata(7 downto 0);
        ch0_rx_fifo_din <= gt_rxdata(23 downto 8);
        ch1_rx_fifo_din <= gt_rxdata(27 downto 24);

        -- Is the data presented at the MGT data output a valid message (according to our format)?
        valid_message <= not (rx_k_char_invalid_location_mgt 
                            or rx_data_without_k_header_mgt 
                            or rx_any_disparity_error_mgt 
                            or rx_any_invalid_data_mgt
                            or (not rxbyteisaligned_mgt));
        header_k28 <= '1' when message_header(4 downto 0) = "11100" else '0';
        valid_data_in_message <= valid_message and header_k28 and not message_header(7);

        -- Create the write signals for the RX FIFOs
        -- First synchronize the FIFO enable signals from the AXI registers
        rx_fifo_en_sync: xpm_cdc_array_single
            generic map (
                DEST_SYNC_FF => 4,
                INIT_SYNC_FF => 0,
                SIM_ASSERT_CHK => 1,
                SRC_INPUT_REG => 0,
                WIDTH => 2
            )
            port map (
                src_clk => s_axi_aclk,
                src_in(0) => ch0_rx_fifo_en_axi,
                src_in(1) => ch1_rx_fifo_en_axi,

                dest_clk => MGT128_rxusrclk2_int,
                dest_out(0) => ch0_rx_fifo_en_mgt,
                dest_out(1) => ch1_rx_fifo_en_mgt
            );

        -- If everything looks good, push the data into the FIFOs
        ch0_rx_fifo_wr_en <= ch0_rx_fifo_en_mgt and message_header(5) and valid_data_in_message;
        ch1_rx_fifo_wr_en <= ch1_rx_fifo_en_mgt and message_header(6) and valid_data_in_message;


        ----------------- TX MESSAGE PREPARATION --------------------
        -- Use the statuses of the channel FIFOs to decide what we're pushing to the MGT TX interface
        send_k285_sync: xpm_cdc_single
            generic map (
                DEST_SYNC_FF => 4,
                INIT_SYNC_FF => 0,
                SIM_ASSERT_CHK => 1,
                SRC_INPUT_REG => 0
            )
            port map (
                src_clk => s_axi_aclk,
                src_in => send_k285_axi,

                dest_clk => MGT128_txusrclk2_int,
                dest_out => send_k285_mgt
            );

        -- Since underflow is non-destructive, we'll pop from the TX fifos every cycle
        -- but only indicate valid data in the header when the FIFO's data_valid signal was high

        gt_txdata(7 downto 0) <= K28_5 when send_k285_mgt = '1' else
                                 K28_1 when (ch1_tx_fifo_data_valid = '0' and ch0_tx_fifo_data_valid = '1') else
                                 K28_2 when (ch1_tx_fifo_data_valid = '1' and ch0_tx_fifo_data_valid = '0') else
                                 K28_3 when (ch1_tx_fifo_data_valid = '1' and ch0_tx_fifo_data_valid = '1') else 
                                 K28_0;

        gt_txdata(23 downto 8)  <= ch0_tx_fifo_dout;
        gt_txdata(27 downto 24) <= ch1_tx_fifo_dout;
        gt_txdata(31 downto 28) <= (others => '0');

        tx_is_k_char <= "0001";

        ----------- Channel 1 RX FIFO ------------

        -- Create and synchronize a reset and reset busy signal for the RX FIFO
        ch1_rx_fifo_rst_sync: xpm_cdc_single
            generic map (
                DEST_SYNC_FF => 4,
                INIT_SYNC_FF => 0,
                SIM_ASSERT_CHK => 1,
                SRC_INPUT_REG => 0
            )
            port map (
                src_clk => s_axi_aclk,
                src_in => ch1_rx_fifo_rst_axi,

                dest_clk => MGT128_rxusrclk2_int,
                dest_out => ch1_rx_fifo_rst_mgt
            );

        ch1_rx_fifo_wr_rst_busy_sync: xpm_cdc_single
            generic map (
                DEST_SYNC_FF => 4,
                INIT_SYNC_FF => 0,
                SIM_ASSERT_CHK => 1,
                SRC_INPUT_REG => 0
            )
            port map (
                src_clk => MGT128_rxusrclk2_int,
                src_in => ch1_rx_fifo_wr_rst_busy_mgt,

                dest_clk => s_axi_aclk,
                dest_out => ch1_rx_fifo_wr_rst_busy_axi
            );

        ch1_rx_fifo_rst_busy_axi <= ch1_rx_fifo_wr_rst_busy_axi or ch1_rx_fifo_rd_rst_busy;

        -- Make a signal for popping from the fifo so that
        -- it only happens on the rising edge of the register signals
        ch1_rx_fifo_rd_en_proc: process(s_axi_aclk) begin
            if rising_edge(s_axi_aclk) then
                ch1_rx_fifo_rd_en_reg_d <= ch1_rx_fifo_rd_en_reg;
                ch1_rx_fifo_rd_en <= ch1_rx_fifo_rd_en_reg and not ch1_rx_fifo_rd_en_reg_d;
            end if;
        end process ch1_rx_fifo_rd_en_proc;

        ch1_rx_fifo : xpm_fifo_async
            generic map (
                CASCADE_HEIGHT      => 0,
                CDC_SYNC_STAGES     => 2,
                DOUT_RESET_VALUE    => "0",
                ECC_MODE            => "no_ecc",
                FIFO_MEMORY_TYPE    => "auto",
                FIFO_READ_LATENCY   => 0,
                FIFO_WRITE_DEPTH    => 16,
                FULL_RESET_VALUE    => 0,
                PROG_EMPTY_THRESH   => 10,
                PROG_FULL_THRESH    => 10,
                RD_DATA_COUNT_WIDTH => 1,
                READ_DATA_WIDTH     => 4,
                READ_MODE           => "fwft",       
                RELATED_CLOCKS      => 0,        
                SIM_ASSERT_CHK      => 1,        
                USE_ADV_FEATURES    => "1001", -- use "data_valid" and "overflow", bits 12 and 0 respectively
                WAKEUP_TIME         => 0,
                WRITE_DATA_WIDTH    => 4,
                WR_DATA_COUNT_WIDTH => 1
            )
            port map (
                -- MGT-facing ports
                wr_clk => MGT128_rxusrclk2_int,
                
                din         => ch1_rx_fifo_din,
                wr_en       => ch1_rx_fifo_wr_en,
                full        => open,
                overflow    => ch1_rx_fifo_overflow_mgt,
                rst         => ch1_rx_fifo_rst_mgt, 
                wr_rst_busy => ch1_rx_fifo_wr_rst_busy_mgt,

                -- output-facing ports
                rd_clk => s_axi_aclk,

                dout        => ch1_rx_fifo_dout,
                rd_en       => ch1_rx_fifo_rd_en,
                data_valid  => ch1_rx_fifo_data_valid, 
                empty       => open,
                rd_rst_busy => ch1_rx_fifo_rd_rst_busy,
                
                -- unused ports
                almost_empty => open,
                almost_full => open,
                dbiterr => open, 
                prog_empty => open, 
                prog_full => open,
                rd_data_count => open,
                sbiterr => open, 
                underflow => open,
                wr_ack => open,
                wr_data_count => open,
                injectdbiterr => '0', 
                injectsbiterr => '0',
                sleep => '0' 
            );


        ----------- Channel 1 TX FIFO ------------

        -- Create and synchronize a reset and reset busy signal for the FIFO
        -- Since the FIFO rst signal is in the write clock domain, we don't need a synchronizer
        -- for the TX fifo

        ch1_tx_fifo_rd_rst_busy_sync: xpm_cdc_single
            generic map (
                DEST_SYNC_FF => 4,
                INIT_SYNC_FF => 0,
                SIM_ASSERT_CHK => 1,
                SRC_INPUT_REG => 0
            )
            port map (
                src_clk => MGT128_txusrclk2_int,
                src_in => ch1_tx_fifo_rd_rst_busy_mgt,

                dest_clk => s_axi_aclk,
                dest_out => ch1_tx_fifo_rd_rst_busy_axi
            );

        ch1_tx_fifo_rst_busy_axi <= ch1_tx_fifo_wr_rst_busy or ch1_tx_fifo_rd_rst_busy_axi;

        -- Make a signal for pushing to the FIFO so that
        -- it only happens on the rising edge of the register signals
        ch1_tx_fifo_wr_en_proc: process(s_axi_aclk) begin
            if rising_edge(s_axi_aclk) then
                ch1_tx_fifo_wr_en_reg_d <= ch1_tx_fifo_wr_en_reg;
                ch1_tx_fifo_wr_en <= ch1_tx_fifo_wr_en_reg and not ch1_tx_fifo_wr_en_reg_d;
            end if;
        end process ch1_tx_fifo_wr_en_proc;

        ch1_tx_fifo : xpm_fifo_async
            generic map (
                CASCADE_HEIGHT      => 0,
                CDC_SYNC_STAGES     => 2,
                DOUT_RESET_VALUE    => "0",
                ECC_MODE            => "no_ecc",
                FIFO_MEMORY_TYPE    => "auto",
                FIFO_READ_LATENCY   => 0,
                FIFO_WRITE_DEPTH    => 16,
                FULL_RESET_VALUE    => 0,
                PROG_EMPTY_THRESH   => 10,
                PROG_FULL_THRESH    => 10,
                RD_DATA_COUNT_WIDTH => 1,
                READ_DATA_WIDTH     => 4,
                READ_MODE           => "fwft",       
                RELATED_CLOCKS      => 0,        
                SIM_ASSERT_CHK      => 1,        
                USE_ADV_FEATURES    => "1001", -- use "data_valid" and "overflow", bits 12 and 0 respectively
                WAKEUP_TIME         => 0,
                WRITE_DATA_WIDTH    => 4,
                WR_DATA_COUNT_WIDTH => 1
            )
            port map (
                -- MGT-facing ports
                wr_clk => s_axi_aclk,
                
                din         => ch1_tx_fifo_din,
                wr_en       => ch1_tx_fifo_wr_en,
                full        => ch1_tx_fifo_full,
                overflow    => open,
                rst         => ch1_tx_fifo_rst_axi, 
                wr_rst_busy => ch1_tx_fifo_wr_rst_busy,

                -- output-facing ports
                -- Since we can read non-destructively even when the FIFO is empty, 
                -- we read every cycle and only change the header to indicate data validity
                rd_clk => MGT128_txusrclk2_int,
                
                dout        => ch1_tx_fifo_dout,
                rd_en       => '1', 
                data_valid  => ch1_tx_fifo_data_valid, 
                empty       => open,
                rd_rst_busy => ch1_tx_fifo_rd_rst_busy_mgt,
                
                -- unused ports
                almost_empty => open,
                almost_full => open,
                dbiterr => open, 
                prog_empty => open, 
                prog_full => open,
                rd_data_count => open,
                sbiterr => open, 
                underflow => open,
                wr_ack => open,
                wr_data_count => open,
                injectdbiterr => '0', 
                injectsbiterr => '0',
                sleep => '0' 
            );

    

end rtl;
