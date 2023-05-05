----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/25/2022 11:52:49 PM
-- Design Name: acadia
-- Module Name: acadia_sample_adder - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: A module which accepts a 128-bit stream and adds the four 32-bit
-- samples contained within.
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

entity acadia_sample_adder is
    port (
        clk                    : in  std_logic;        
        signal_in              : in  std_logic_vector(127 downto 0);
        signal_out             : out std_logic_vector(31 downto 0)
    );
    
    attribute USE_DSP : string;
end acadia_sample_adder;

architecture rtl of acadia_sample_adder is
    
    attribute USE_DSP of rtl : architecture is "YES";

    signal signal_in0_re : signed(15 downto 0);
    signal signal_in1_re : signed(15 downto 0);
    signal signal_in2_re : signed(15 downto 0);
    signal signal_in3_re : signed(15 downto 0);

    signal signal_in0_im : signed(15 downto 0);
    signal signal_in1_im : signed(15 downto 0);
    signal signal_in2_im : signed(15 downto 0);
    signal signal_in3_im : signed(15 downto 0);
    
begin
    
    signal_in0_re <= signed(signal_in(15 downto 0));
    signal_in0_im <= signed(signal_in(31 downto 16));
    signal_in1_re <= signed(signal_in(47 downto 32));
    signal_in1_im <= signed(signal_in(63 downto 48));
    signal_in2_re <= signed(signal_in(79 downto 64));
    signal_in2_im <= signed(signal_in(95 downto 80));
    signal_in3_re <= signed(signal_in(111 downto 96));
    signal_in3_im <= signed(signal_in(127 downto 112));

    signal_out(15 downto 0)  <= std_logic_vector(signal_in0_re + signal_in1_re + signal_in2_re + signal_in3_re);
    signal_out(31 downto 16) <= std_logic_vector(signal_in0_im + signal_in1_im + signal_in2_im + signal_in3_im);
    
end rtl;
