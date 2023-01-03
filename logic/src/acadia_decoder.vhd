----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 09/19/2022 02:41:13 PM
-- Design Name: 
-- Module Name: decoder - rtl
-- Project Name: 
-- Target Devices: 
-- Tool Versions: 
-- Description: 
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

entity acadia_decoder is
    generic
    (
        INPUTS : natural := 6;
        OUTPUTS : natural := 64
    );
    port
    (
        en   : in std_logic;
        din  : in std_logic_vector(INPUTS-1 downto 0);
        dout : out std_logic_vector(OUTPUTS-1 downto 0)
    );

end acadia_decoder;

architecture rtl of acadia_decoder is

begin

    out_gen: for i in 0 to OUTPUTS-1 generate
        dout(i) <= '1' when ((to_integer(unsigned(din)) = i) and en = '1') else '0';
    end generate out_gen;

end rtl;
