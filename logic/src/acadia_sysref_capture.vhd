----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 08/11/2022 03:36:24 PM
-- Design Name: acadia
-- Module Name: sysref_capture - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 
-- Description: Simple flip-flop for capturing SYSREF signals.
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

library UNISIM;
use UNISIM.vcomponents.all;

entity acadia_sysref_capture is
    port (
        clk        : in  std_logic;
        
        sysref_p   : in std_logic;
        sysref_n   : in std_logic;
        
        sysref_out : out std_logic
    );

end acadia_sysref_capture;

architecture rtl of acadia_sysref_capture is 
    
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of sysref_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 sysref CLK_P";
    ATTRIBUTE X_INTERFACE_INFO of sysref_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 sysref CLK_N";

    signal sysref_single : std_logic;
    
begin    
    
    sysref_ibufds : IBUFDS port map(I => sysref_p, IB => sysref_n, O => sysref_single);
        
    capture_proc: process(clk) begin
        if rising_edge(clk) then
            sysref_out <= sysref_single;
        end if;
    end process capture_proc;
    
end rtl;
