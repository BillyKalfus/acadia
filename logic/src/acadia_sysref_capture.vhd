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
        clk         : in  std_logic;
        
        sysref_in_p : in  std_logic;
        sysref_in_n : in  std_logic;
        sysref_out  : out std_logic;
  
        sysref_count_awaddr  : in std_logic_vector(31 downto 0);
        sysref_count_awvalid : in std_logic;
        sysref_count_awready : out std_logic; 
        sysref_count_wdata   : in std_logic_vector(31 downto 0);
        sysref_count_wstrb   : in std_logic_vector(3 downto 0);
        sysref_count_wvalid  : in std_logic;
        sysref_count_wready  : out std_logic;
        sysref_count_bresp   : out std_logic_vector(1 downto 0);
        sysref_count_bvalid  : out std_logic;
        sysref_count_bready  : in std_logic;
        sysref_count_araddr  : in std_logic_vector(31 downto 0);
        sysref_count_arready : out std_logic;
        sysref_count_arvalid : in std_logic;
        sysref_count_rdata   : out std_logic_vector(31 downto 0);
        sysref_count_rresp   : out std_logic_vector(1 downto 0);
        sysref_count_rvalid  : out std_logic;
        sysref_count_rready  : in std_logic
    );



end acadia_sysref_capture;

architecture rtl of acadia_sysref_capture is 
    
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_INFO of clk      : SIGNAL is "xilinx.com:signal:clock:1.0 clk CLK";
    ATTRIBUTE X_INTERFACE_PARAMETER of clk : SIGNAL is "ASSOCIATED_BUSIF sysref_count";
    
    ATTRIBUTE X_INTERFACE_INFO of sysref_in_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 sysref_in CLK_P";
    ATTRIBUTE X_INTERFACE_INFO of sysref_in_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 sysref_in CLK_N";
    
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_awaddr  : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count AWADDR";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_awvalid : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count AWVALID";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_awready : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count AWREADY";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_wdata   : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count WDATA";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_wstrb   : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count WSTRB";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_wvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count WVALID";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_wready  : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count WREADY";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_bresp   : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count BRESP";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_bvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count BVALID";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_bready  : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count BREADY";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_araddr  : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count ARADDR";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_arvalid : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count ARVALID";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_arready : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count ARREADY";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_rdata   : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count RDATA";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_rresp   : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count RRESP";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_rvalid  : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count RVALID";
    ATTRIBUTE X_INTERFACE_INFO of sysref_count_rready  : SIGNAL is "xilinx.com:interface:aximm:1.0 sysref_count RREADY";
    ATTRIBUTE X_INTERFACE_PARAMETER of sysref_count_awaddr: SIGNAL is "PROTOCOL AXI4LITE";


    signal sysref_single   : std_logic;
    signal sysref_synced   : std_logic;
    signal sysref_synced_d : std_logic;
    signal sysref_count    : unsigned(7 downto 0);
    
begin    
    
    sysref_ibufds : IBUFDS port map(I => sysref_in_p, IB => sysref_in_n, O => sysref_single);
        
    capture_proc: process(clk) begin
        if rising_edge(clk) then
            sysref_synced   <= sysref_single;
            sysref_synced_d <= sysref_synced;
        end if;
    end process capture_proc;

    sysref_out <= sysref_synced;

    sysref_count_proc: process(clk) begin
        if rising_edge(clk) then
            if(sysref_count_wvalid = '1') then
                sysref_count <= unsigned(sysref_count_wdata(sysref_count'high downto 0));
            elsif(sysref_synced = '1' and sysref_synced_d = '0') then
                sysref_count <= sysref_count + 1;
            end if;
        end if;
    end process sysref_count_proc;
    
    -- Connect signals for the AXILITE interface
    sysref_count_rdata(sysref_count'high downto 0)                         <= std_logic_vector(sysref_count);
    sysref_count_rdata(sysref_count_rdata'high downto sysref_count'high+1) <= (others => '0');
    sysref_count_awready <= '1';
    sysref_count_wready  <= '1';
    sysref_count_bresp   <= "00";
    sysref_count_bvalid  <= '1';
    sysref_count_arready <= '1';
    sysref_count_rresp   <= "00";
    sysref_count_rvalid  <= '1';
    
end rtl;
