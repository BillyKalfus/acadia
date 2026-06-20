----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/27/2024 03:36:24 PM
-- Design Name: acadia
-- Module Name: acadia_clocking - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 
-- Description: 
--    Module for configuring and routing clocks.
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

entity acadia_clocking is
    generic (
        AXI_ADDRESS_BITS : positive := 32
    );
    port (
        -- AXI-lite configuration port
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

        -- CLK104 signals
        clk104_pl_clk_p : in std_logic;
        clk104_pl_clk_n : in std_logic;

        clk104_pl_sysref_p : in std_logic;
        clk104_pl_sysref_n : in std_logic;

        clk104_sfp_rec_clk_p : out std_logic;
        clk104_sfp_rec_clk_n : out std_logic;

        clk104_sync : out std_logic;

        -- 8A34001 clocks
        idt_8a34001_q1_p : in std_logic;
        idt_8a34001_q1_n : in std_logic;

        idt_8a34001_q2_p : in std_logic;
        idt_8a34001_q2_n : in std_logic;

        idt_8a34001_q3_p : in std_logic;
        idt_8a34001_q3_n : in std_logic;

        idt_8a34001_q8_p : in std_logic;
        idt_8a34001_q8_n : in std_logic;

        -- idt_8a34001_clk1_p : out std_logic;
        -- idt_8a34001_clk1_n : out std_logic;

        -- Clock from the FMC
        FMCP_CLK1_M2C_p : in std_logic;
        FMCP_CLK1_M2C_n : in std_logic;

        -- GT clocks
        MGT128_txoutclk : in std_logic;
        MGT128_rxoutclk : in std_logic;
        MGT128_usrclk   : out std_logic;

        -- Internal clocks
        seq_clk    : out std_logic;
        seq_sysref : out std_logic
    );

end acadia_clocking;

architecture rtl of acadia_clocking is 
     
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    -- AXI-lite configuration port
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

    -- CLK104 interface
    ATTRIBUTE X_INTERFACE_INFO of clk104_pl_clk_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 CLK104_PL_CLK clk_p";
    ATTRIBUTE X_INTERFACE_INFO of clk104_pl_clk_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 CLK104_PL_CLK clk_n";

    ATTRIBUTE X_INTERFACE_INFO of clk104_pl_sysref_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 CLK104_PL_SYSREF clk_p";
    ATTRIBUTE X_INTERFACE_INFO of clk104_pl_sysref_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 CLK104_PL_SYSREF clk_n";

    ATTRIBUTE X_INTERFACE_INFO of clk104_sfp_rec_clk_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 CLK104_SFP_REC_CLK clk_p";
    ATTRIBUTE X_INTERFACE_INFO of clk104_sfp_rec_clk_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 CLK104_SFP_REC_CLK clk_n";
    ATTRIBUTE X_INTERFACE_MODE of clk104_sfp_rec_clk_p : SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_q1_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_Q1 clk_p";
    ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_q1_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_Q1 clk_n";

    ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_q2_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_Q2 clk_p";
    ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_q2_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_Q2 clk_n";

    ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_q3_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_Q3 clk_p";
    ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_q3_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_Q3 clk_n";

    ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_q8_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_Q8 clk_p";
    ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_q8_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_Q8 clk_n";

    -- ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_clk1_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_CLK1 clk_p";
    -- ATTRIBUTE X_INTERFACE_INFO of idt_8a34001_clk1_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 IDT_8A34001_CLK1 clk_n";
    -- ATTRIBUTE X_INTERFACE_MODE of idt_8a34001_clk1_p : SIGNAL is "Master";

    ATTRIBUTE X_INTERFACE_INFO of FMCP_CLK1_M2C_p : SIGNAL is "xilinx.com:interface:diff_clock:1.0 FMCP_CLK1_M2C clk_p";
    ATTRIBUTE X_INTERFACE_INFO of FMCP_CLK1_M2C_n : SIGNAL is "xilinx.com:interface:diff_clock:1.0 FMCP_CLK1_M2C clk_n";

    signal clk104_pl_clk_single    : std_logic;
    signal clk104_pl_clk           : std_logic;
    signal clk104_pl_sysref_single : std_logic;
    signal clk104_pl_sysref        : std_logic;
    signal clk104_sfp_rec_clk      : std_logic;

    signal idt_8a34001_q1_single   : std_logic;
    signal idt_8a34001_q1          : std_logic;

    signal idt_8a34001_q2_single   : std_logic;
    signal idt_8a34001_q2          : std_logic;

    signal idt_8a34001_q3_single   : std_logic;
    signal idt_8a34001_q3          : std_logic;

    signal idt_8a34001_q8_single   : std_logic;
    signal idt_8a34001_q8          : std_logic;

    signal axi_regs_out : std_logic_vector(31 downto 0);
    signal axi_regs_in  : std_logic_vector(31 downto 0);
    
begin    

    regs_inst: entity work.acadia_axi_lite_regs
        generic map (
            N_REGS => 1,
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

    axi_regs_in <= (others => '0');

    -- The PL clock from the CLK104 is brought in through an HDIO bank, so we need to buffer
    -- it with an IBUFDS before feeding it to the rest of the clocking network
    clk104_pl_clk_ibufds : IBUFDS port map(I => clk104_pl_clk_p, IB => clk104_pl_clk_n, O => clk104_pl_clk_single);
    clk104_pl_clk_bufg : BUFG port map(I => clk104_pl_clk_single, O => clk104_pl_clk);

    -- Synchronize the sysref to the internal clock
    clk104_pl_sysref_ibufds : IBUFDS port map(I => clk104_pl_sysref_p, IB => clk104_pl_sysref_n, O => clk104_pl_sysref_single);
        
    clk104_pl_sysref_capture_proc: process(clk104_pl_clk) begin
        if rising_edge(clk104_pl_clk) then
            clk104_pl_sysref <= clk104_pl_sysref_single;
        end if;
    end process clk104_pl_sysref_capture_proc;

    clk104_sfp_rec_clk_obufds : OBUFDS port map(I => clk104_sfp_rec_clk, O => clk104_sfp_rec_clk_p, OB => clk104_sfp_rec_clk_n);

    -- Input buffers for the IDT clocks
    idt_8a34001_q1_ibufds : IBUFDS port map(I => idt_8a34001_q1_p, IB => idt_8a34001_q1_n, O => idt_8a34001_q1_single);
    idt_8a34001_q1_bufg : BUFG port map(I => idt_8a34001_q1_single, O => idt_8a34001_q1);

    idt_8a34001_q2_ibufds : IBUFDS port map(I => idt_8a34001_q2_p, IB => idt_8a34001_q2_n, O => idt_8a34001_q2_single);
    idt_8a34001_q2_bufg : BUFG port map(I => idt_8a34001_q2_single, O => idt_8a34001_q2);

    idt_8a34001_q3_ibufds : IBUFDS port map(I => idt_8a34001_q3_p, IB => idt_8a34001_q3_n, O => idt_8a34001_q3_single);
    idt_8a34001_q3_bufg : BUFG port map(I => idt_8a34001_q3_single, O => idt_8a34001_q3);

    idt_8a34001_q8_ibufds : IBUFDS port map(I => idt_8a34001_q8_p, IB => idt_8a34001_q8_n, O => idt_8a34001_q8_single);
    idt_8a34001_q8_bufg : BUFG port map(I => idt_8a34001_q8_single, O => idt_8a34001_q8);

    seq_clk    <= clk104_pl_clk;
    seq_sysref <= clk104_pl_sysref;

    clk104_sfp_rec_clk <= idt_8a34001_q8;

    MGT128_usrclk <= clk104_pl_clk;

    
end rtl;
