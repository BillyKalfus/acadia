----------------------------------------------------------------------------------
-- Company: 
-- Engineer: 
-- 
-- Create Date: 11/18/2022 12:15:14 PM
-- Design Name: 
-- Module Name: axi_bram_ctrl_addr_slice - rtl
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

-- Uncomment the following library declaration if using
-- arithmetic functions with Signed or Unsigned values
--use IEEE.NUMERIC_STD.ALL;

-- Uncomment the following library declaration if instantiating
-- any Xilinx leaf cells in this code.
--library UNISIM;
--use UNISIM.VComponents.all;

entity acadia_axi_bram_ctrl_addr_slice is
    generic (
        DATA_WIDTH : natural := 32;
        LOG2_DATA_WIDTH_BYTES : natural := 2; -- log2(<data width in bytes>)
        LOG2_SLAVE_SIZE_BYTES : natural := 16 -- log2(<slave address space size in bytes>)
    );
    port (
        bram_ctrl_din  : in  std_logic_vector(DATA_WIDTH-1 downto 0);
        bram_ctrl_dout : out std_logic_vector(DATA_WIDTH-1 downto 0);
        bram_ctrl_addr : in  std_logic_vector(LOG2_SLAVE_SIZE_BYTES-1 downto 0);
        bram_ctrl_clk  : in  std_logic;
        bram_ctrl_we   : in  std_logic_vector((DATA_WIDTH / 8)-1 downto 0);
        bram_ctrl_en   : in  std_logic;
        bram_ctrl_rst  : in  std_logic;
        
        slave_din      : out std_logic_vector(DATA_WIDTH-1 downto 0);
        slave_dout     : in  std_logic_vector(DATA_WIDTH-1 downto 0);
        slave_addr     : out std_logic_vector(LOG2_SLAVE_SIZE_BYTES-LOG2_DATA_WIDTH_BYTES-1 downto 0);
        slave_clk      : out std_logic;
        slave_we       : out std_logic_vector((DATA_WIDTH / 8)-1 downto 0);
        slave_en       : out std_logic;
        slave_rst      : out std_logic
    );
end acadia_axi_bram_ctrl_addr_slice;

architecture rtl of acadia_axi_bram_ctrl_addr_slice is
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of bram_ctrl_din  : SIGNAL is "xilinx.com:interface:bram:1.0 BRAM_CTRL DIN";
    ATTRIBUTE X_INTERFACE_INFO of bram_ctrl_dout : SIGNAL is "xilinx.com:interface:bram:1.0 BRAM_CTRL DOUT";
    ATTRIBUTE X_INTERFACE_INFO of bram_ctrl_addr : SIGNAL is "xilinx.com:interface:bram:1.0 BRAM_CTRL ADDR";
    ATTRIBUTE X_INTERFACE_INFO of bram_ctrl_clk  : SIGNAL is "xilinx.com:interface:bram:1.0 BRAM_CTRL CLK";
    ATTRIBUTE X_INTERFACE_INFO of bram_ctrl_we   : SIGNAL is "xilinx.com:interface:bram:1.0 BRAM_CTRL WE";
    ATTRIBUTE X_INTERFACE_INFO of bram_ctrl_en   : SIGNAL is "xilinx.com:interface:bram:1.0 BRAM_CTRL EN";
    ATTRIBUTE X_INTERFACE_INFO of bram_ctrl_rst  : SIGNAL is "xilinx.com:interface:bram:1.0 BRAM_CTRL RST";
    
    ATTRIBUTE X_INTERFACE_INFO of slave_din  : SIGNAL is "xilinx.com:interface:bram:1.0 SLAVE DIN";
    ATTRIBUTE X_INTERFACE_INFO of slave_dout : SIGNAL is "xilinx.com:interface:bram:1.0 SLAVE DOUT";
    ATTRIBUTE X_INTERFACE_INFO of slave_addr : SIGNAL is "xilinx.com:interface:bram:1.0 SLAVE ADDR";
    ATTRIBUTE X_INTERFACE_INFO of slave_clk  : SIGNAL is "xilinx.com:interface:bram:1.0 SLAVE CLK";
    ATTRIBUTE X_INTERFACE_INFO of slave_we   : SIGNAL is "xilinx.com:interface:bram:1.0 SLAVE WE";
    ATTRIBUTE X_INTERFACE_INFO of slave_en   : SIGNAL is "xilinx.com:interface:bram:1.0 SLAVE EN";
    ATTRIBUTE X_INTERFACE_INFO of slave_rst  : SIGNAL is "xilinx.com:interface:bram:1.0 SLAVE RST";
    
    ATTRIBUTE X_INTERFACE_MODE of slave_din  : SIGNAL is "Master";
begin

    bram_ctrl_dout <= slave_dout;
    slave_din      <= bram_ctrl_din;
    slave_addr     <= bram_ctrl_addr(LOG2_SLAVE_SIZE_BYTES-1 downto LOG2_DATA_WIDTH_BYTES);
    slave_clk      <= bram_ctrl_clk;
    slave_we       <= bram_ctrl_we;
    slave_en       <= bram_ctrl_en;
    slave_rst      <= bram_ctrl_rst;
    
end rtl;
