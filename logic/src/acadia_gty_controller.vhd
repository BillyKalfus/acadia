----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 10/07/2023 03:53:08 PM
-- Design Name: 
-- Module Name: acadia_bus_xcvr - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: A lightweight module for interface GTY transceivers to a 
--    memory bus. 
--    The first four registers implement FIFOs for interacting with the 
--    transceiver user interface, with each FIFO corresponding to a different
--    combination of TXCTRL0/TXCTRL1 or RXCTRL0/RXCTRL1.
--
--    When the 8/10 encoder is enabled, TXCTRL bits control the outgoing
--    disparity as
--        00 = calculated internally
--        01 = invert running disparity
--        10 = force negative running disparity
--        11 = force positive running disparity
--    and RXCTRL bits indicate
--        00 = no disparity error, data character
--        01 = no disparity error, K character
--        10 = disparity error, data character
--        11 = disparity error, K character    
--    
--    When the 8/10 encoder is disabled, these bits indicate the extra two bits
--    appended to the data to fill the datapath width. In this module this 
--    essentially allows for   

--    Register 0: Control and Status signals (all write signals latching)
--        Bit 0: w: gtwiz_userclk_tx_reset
--               r: gtwiz_userclk_tx_active
--        Bit 1: w: gtwiz_userclk_rx_reset
--               r: gtwiz_userclk_rx_active
--        Bit 2: w: gtwiz_buffbypass_tx_reset
--               r: gtwiz_buffbypass_tx_done
--        Bit 3: w: gtwiz_buffbypass_tx_start_user
--               r: gtwiz_buffbypass_tx_error
--        Bit 4: w: gtwiz_buffbypass_rx_reset
--               r: gtwiz_buffbypass_rx_done
--        Bit 5: w: gtwiz_buffbypass_rx_start_user
--               r: gtwiz_buffbypass_rx_error
--        Bit 6: w: gtwiz_reset_all
--               r: gtwiz_reset_rx_cdr_stable
--        Bit 7: w: gtwiz_reset_tx_pll_and_datapath
--               r: txpmaresetdone
--        Bit 8: w: gtwiz_reset_tx_datapath
--               r: gtwiz_reset_tx_done
--        Bit 9: w: gtwiz_reset_rx_pll_and_datapath
--               r: rxpmaresetdone
--        Bit 10: w: gtwiz_reset_rx_datapath
--                r: gtwiz_reset_rx_done
--        Bit 11: w: tx8b10ben
--        Bit 12: w: rx8b10ben
--        Bit 13: w: rxcommadeten
--                r: rxbyteisaligned
--        Bit 14: w: rxmcommaalignen
--                r: gtpowergood
--        Bit 15: w: rxpcommaalignen
--                r: txprgdivresetdone
--        Bit 16: w: rxbyterealign (write 1 to clear, writing 0 has no effect)
--                r: rxbyterealign (current value, latched)
--        Bit 17: w: rxcommadet (write 1 to clear, writing 0 has no effect)
--                r: rxcommadet (current value, latched)
--        Bits 21-18: w: disparity error (write 1 to clear, writing 0 has no effect)
--                    r: disparity error (current value, latched)
--        Bits 25-22: w: invalid data error (write 1 to clear, writing 0 has no effect)
--                    r: invalid data error (current value, latched)
--        Bits 29-26: w: comma detected (write 1 to clear, writing 0 has no effect)
--                    r: comma detected (current value, latched)
--        Bit 31: Controller reset (write 1 to reset, writing 0 does nothing)
--
--    We use a simple link-layer protocol for encoding the validity of data:
--        K characters are used to encode the validity of data. Any K-character
--        for a given byte will not be pushed into the data FIFO, while 
--        while any valid data character is pushed into the corresponding channel's FIFO.
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

entity acadia_gty_controller is
    generic (
        FIFO_DEPTH : positive := 16
    );
    port (
        -- Fabric clocks
        clk : in std_logic;
        tx_clk : out std_logic;
        rx_clk : out std_logic;

        master_bus_mosi  : in  std_logic_vector(31 downto 0);
        master_bus_miso  : out std_logic_vector(31 downto 0);
        master_bus_addr  : in  std_logic_vector(31 downto 0);
        master_bus_we    : in  std_logic;
        master_bus_en    : in  std_logic;

        -- GT physical interface
        gt_tx_p : out std_logic;
        gt_tx_n : out std_logic;
        gt_rx_p : in  std_logic;
        gt_rx_n : in  std_logic;

        gt_refclk00 : in std_logic
    );
end acadia_gty_controller;

architecture rtl of acadia_gty_controller is

    component gtwizard_ultrascale_0
        port (
            gtwiz_userclk_tx_reset_in : in std_logic_vector(0 downto 0);
            gtwiz_userclk_tx_srcclk_out : out std_logic_vector(0 downto 0);
            gtwiz_userclk_tx_usrclk_out : out std_logic_vector(0 downto 0);
            gtwiz_userclk_tx_usrclk2_out : out std_logic_vector(0 downto 0);
            gtwiz_userclk_tx_active_out : out std_logic_vector(0 downto 0);
            gtwiz_userclk_rx_reset_in : in std_logic_vector(0 downto 0);
            gtwiz_userclk_rx_srcclk_out : out std_logic_vector(0 downto 0);
            gtwiz_userclk_rx_usrclk_out : out std_logic_vector(0 downto 0);
            gtwiz_userclk_rx_usrclk2_out : out std_logic_vector(0 downto 0);
            gtwiz_userclk_rx_active_out : out std_logic_vector(0 downto 0);
            gtwiz_buffbypass_tx_reset_in : in std_logic_vector(0 downto 0);
            gtwiz_buffbypass_tx_start_user_in : in std_logic_vector(0 downto 0);
            gtwiz_buffbypass_tx_done_out : out std_logic_vector(0 downto 0);
            gtwiz_buffbypass_tx_error_out : out std_logic_vector(0 downto 0);
            gtwiz_buffbypass_rx_reset_in : in std_logic_vector(0 downto 0);
            gtwiz_buffbypass_rx_start_user_in : in std_logic_vector(0 downto 0);
            gtwiz_buffbypass_rx_done_out : out std_logic_vector(0 downto 0);
            gtwiz_buffbypass_rx_error_out : out std_logic_vector(0 downto 0);
            gtwiz_reset_clk_freerun_in : in std_logic_vector(0 downto 0);
            gtwiz_reset_all_in : in std_logic_vector(0 downto 0);
            gtwiz_reset_tx_pll_and_datapath_in : in std_logic_vector(0 downto 0);
            gtwiz_reset_tx_datapath_in : in std_logic_vector(0 downto 0);
            gtwiz_reset_rx_pll_and_datapath_in : in std_logic_vector(0 downto 0);
            gtwiz_reset_rx_datapath_in : in std_logic_vector(0 downto 0);
            gtwiz_reset_rx_cdr_stable_out : out std_logic_vector(0 downto 0);
            gtwiz_reset_tx_done_out : out std_logic_vector(0 downto 0);
            gtwiz_reset_rx_done_out : out std_logic_vector(0 downto 0);
            gtwiz_userdata_tx_in : in std_logic_vector(31 downto 0);
            gtwiz_userdata_rx_out : out std_logic_vector(31 downto 0);
            gtrefclk00_in : in std_logic_vector(0 downto 0);
            qpll0outclk_out : out std_logic_vector(0 downto 0);
            qpll0outrefclk_out : out std_logic_vector(0 downto 0);
            gtyrxn_in : in std_logic_vector(0 downto 0);
            gtyrxp_in : in std_logic_vector(0 downto 0);
            rx8b10ben_in : in std_logic_vector(0 downto 0);
            tx8b10ben_in : in std_logic_vector(0 downto 0);
            rxcommadeten_in : in std_logic_vector(0 downto 0);
            rxmcommaalignen_in : in std_logic_vector(0 downto 0);
            rxpcommaalignen_in : in std_logic_vector(0 downto 0);
            rxbyteisaligned_out : out std_logic_vector(0 downto 0);
            rxbyterealign_out : out std_logic_vector(0 downto 0);
            rxcommadet_out : out std_logic_vector(0 downto 0);
            txctrl0_in : in std_logic_vector(15 downto 0);
            txctrl1_in : in std_logic_vector(15 downto 0);
            txctrl2_in : in std_logic_vector(7 downto 0);
            gtpowergood_out : out std_logic_vector(0 downto 0);
            gtytxn_out : out std_logic_vector(0 downto 0);
            gtytxp_out : out std_logic_vector(0 downto 0);
            rxctrl0_out : out std_logic_vector(15 downto 0);
            rxctrl1_out : out std_logic_vector(15 downto 0);
            rxctrl2_out : out std_logic_vector(7 downto 0);
            rxctrl3_out : out std_logic_vector(7 downto 0);
            rxpmaresetdone_out : out std_logic_vector(0 downto 0);
            rxrecclkout_out : out std_logic_vector(0 downto 0);
            txpmaresetdone_out : out std_logic_vector(0 downto 0);
            txprgdivresetdone_out : out std_logic_vector(0 downto 0)
        );
    end component;

    signal rst_int : std_logic;

    signal control_latch    : std_logic_vector(15 downto 0);
    signal status           : std_logic_vector(31 downto 0);
    signal status_latch     : std_logic_vector(31 downto 0);
    signal status_latch_set : std_logic_vector(31 downto 0);

    signal tx_is_k_char : std_logic_vector(3 downto 0);
    signal rx_is_k_char : std_logic_vector(3 downto 0);
    signal invalid_data : std_logic_vector(3 downto 0);
    signal disparity_error : std_logic_vector(3 downto 0);
    signal comma_detected : std_logic_vector(3 downto 0);

    signal gt_txdata : std_logic_vector(31 downto 0);
    signal gt_rxdata : std_logic_vector(31 downto 0);

begin

    rst_proc: process(clk) begin
        if rising_edge(clk) then
            rst_int <= master_bus_we and master_bus_en and master_bus_mosi(31);
        end if;
    end process rst_proc;

    -- Latch some of the signals from the bus so that they stay asserted at
    -- the GTY interface
    control_latch_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst_int = '1') then
                control_latch <= (others => '0');
            elsif(master_bus_en = '1' and master_bus_we = '1') then
                control_latch <= master_bus_mosi(control_latch'high downto 0);
            end if;
        end if;
    end process control_latch_proc;

    -- Make status latches and signals
    status_latch_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst_int = '1') then
                status_latch <= (others => '0');
            else
                status_latch <= status_latch or status_latch_set;
            end if;
        end if;
    end process status_latch_proc;

    -- Report status
    master_bus_miso <= status or status_latch;

    -- Make FIFOs for the data

    gty_inst : gtwizard_ultrascale_0
        port map (
            -- Latched control signals
            gtwiz_userclk_tx_reset_in          => control_latch(0),
            gtwiz_userclk_rx_reset_in          => control_latch(1),
            gtwiz_buffbypass_tx_reset_in       => control_latch(2),
            gtwiz_buffbypass_tx_start_user_in  => control_latch(3),
            gtwiz_buffbypass_rx_reset_in       => control_latch(4),
            gtwiz_buffbypass_rx_start_user_in  => control_latch(5),
            gtwiz_reset_all_in                 => control_latch(6),
            gtwiz_reset_tx_pll_and_datapath_in => control_latch(7),
            gtwiz_reset_tx_datapath_in         => control_latch(8),
            gtwiz_reset_rx_pll_and_datapath_in => control_latch(9),
            gtwiz_reset_rx_datapath_in         => control_latch(10),
            rx8b10ben_in                       => control_latch(11),
            tx8b10ben_in                       => control_latch(12),
            rxcommadeten_in                    => control_latch(13),
            rxmcommaalignen_in                 => control_latch(14),
            rxpcommaalignen_in                 => control_latch(15),

            -- Non-latched status signals
            gtwiz_userclk_tx_active_out   => status(0),
            gtwiz_userclk_rx_active_out   => status(1),
            gtwiz_buffbypass_tx_done_out  => status(2),
            gtwiz_buffbypass_tx_error_out => status(3),
            gtwiz_buffbypass_rx_done_out  => status(4),
            gtwiz_buffbypass_rx_error_out => status(5),
            gtwiz_reset_rx_cdr_stable_out => status(6),
            txpmaresetdone_out            => status(7),
            gtwiz_reset_tx_done_out       => status(8),
            rxpmaresetdone_out            => status(9),
            gtwiz_reset_rx_done_out       => status(10),
            rxbyteisaligned_out           => status(13),
            gtpowergood_out               => status(14),
            txprgdivresetdone_out         => status(15),

            -- Latched status signals
            rxbyterealign_out             => status_latch_set(16),
            rxcommadet_out                => status_latch_set(17),
            rxctrl0_out(3 downto 0)       => rx_is_k_char,
            rxctrl1_out(3 downto 0)       => disparity_error,
            rxctrl2_out(3 downto 0)       => comma_detected,
            rxctrl3_out(3 downto 0)       => invalid_data,

            -- Output disparity control (internally-controlled)
            txctrl0_in => x"0000",
            txctrl1_in => x"0000",

            -- TX K-character control
            txctrl2_in(3 downto 0) => tx_is_k_char;
            txctrl2_in(7 downto 4) => x"0";

            -- Fabric-accessible clocks
            gtwiz_userclk_tx_srcclk_out  : out std_logic_vector(0 downto 0);
            gtwiz_userclk_tx_usrclk_out  : out std_logic_vector(0 downto 0);
            gtwiz_userclk_tx_usrclk2_out => tx_clk
            gtwiz_userclk_rx_srcclk_out  : out std_logic_vector(0 downto 0);
            gtwiz_userclk_rx_usrclk_out  : out std_logic_vector(0 downto 0);
            gtwiz_userclk_rx_usrclk2_out : out std_logic_vector(0 downto 0);
            gtwiz_reset_clk_freerun_in   => clk,
            
            qpll0outclk_out              : out std_logic_vector(0 downto 0);
            qpll0outrefclk_out           : out std_logic_vector(0 downto 0);
            rxrecclkout_out              : out std_logic_vector(0 downto 0);
            
            -- Data interface
            gtwiz_userdata_tx_in  => gt_txdata,
            gtwiz_userdata_rx_out => gt_rxdata,
            
            -- Physical connections
            gtyrxn_in     => gt_rx_n,
            gtyrxp_in     => gt_rx_p,
            gtytxn_out    => gt_tx_n,
            gtytxp_out    => gt_tx_p,
            gtrefclk00_in => gt_refclk00
        );

        status_latch_set(25 downto 22) <= invalid_data;
        status_latch_set(21 downto 18) <= disparity_error;
        status_latch_set(29 downto 26) <= comma_detected;
    


end rtl;
