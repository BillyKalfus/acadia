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

--    Register 0: Data FIFO interfaces
--        Bits 31-0: w: Push data to FIFO 
--                   r: Read data from FIFO
-- 
--    
--    Register 1: Control and Status signals (all write signals latching)
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
--               r: 
--        Bit 8: w: gtwiz_reset_tx_datapath
--               r: gtwiz_reset_tx_done
--        Bit 9: w: gtwiz_reset_rx_pll_and_datapath
--               r: 
--        Bit 10: w: gtwiz_reset_rx_datapath
--                r: gtwiz_reset_rx_done
--        Bit 11: w: tx8b10ben
--        Bit 12: w: rx8b10ben
--        Bit 13: w: rxcommadeten
--                r: rxbyteisaligned
--        Bit 14: w: rxmcommaalignen
--                r: 
--        Bit 15: w: rxpcommaalignen
--                r:
--        Bit 16: w: rxbyterealign (write 1 to clear, writing 0 has no effect)
--                r: rxbyterealign (current value, latched)
--        Bit 17: w: rxcommadet (write 1 to clear, writing 0 has no effect)
--                r: rxcommadet (current value, latched)
--        Bits 21-18: w: disparity error (write 1 to clear, writing 0 has no effect)
--                    r: disparity error (current value, latched)
--        Bits 25-22: w: invalid data error (write 1 to clear, writing 0 has no effect)
--                    r: invalid data error (current value, latched)

--    Register 2: Encoder/Decoder control bits

--        When the 8/10 encoder is disabled, these bits extend the width of 
--        the interface.
--        Bit 0: TXCTRL0[0]
--        Bit 1: TXCTRL1[0]
--        Bit 2: TXCTRL0[1]
--        Bit 3: TXCTRL1[1]
--        Bit 4: TXCTRL0[2]
--        Bit 5: TXCTRL1[2]
--        Bit 6: TXCTRL0[3]
--        Bit 7: TXCTRL1[3]
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

entity acadia_bus_xcvr is
    port (
        clk : in std_logic;

        master_bus_mosi  : in  std_logic_vector(31 downto 0);
        master_bus_miso  : out std_logic_vector(31 downto 0);
        master_bus_addr  : in  std_logic_vector(31 downto 0);
        master_bus_we    : in  std_logic;
        master_bus_en    : in  std_logic        
    );
end acadia_bus_xcvr;

architecture rtl of acadia_bus_xcvr is

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

begin

    rst_proc: process(clk) begin
        if rising_edge(clk) then

        end if;
    end process rst_proc;

    gty_inst : gtwizard_ultrascale_0
        port map (
          
        );

    


end rtl;
