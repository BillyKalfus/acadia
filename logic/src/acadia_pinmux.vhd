----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/27/2024 03:36:24 PM
-- Design Name: acadia
-- Module Name: acadia_pinmux - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 
-- Description: 
--    Module for routing various I/O interfaces from the PS and the 
--    sequencer's bus to physical pins.
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

entity acadia_pinmux is
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

        -- Pinmux masters --

        -- Sequencer GPIO --
        sequencer_gpio_i : out std_logic_vector(31 downto 0);
        sequencer_gpio_o : in  std_logic_vector(31 downto 0);
        sequencer_gpio_t : in  std_logic_vector(31 downto 0);

        -- DMA flags
        dma_flags : in std_logic_vector(31 downto 0);

        -- PS GPIO
        ps_gpio_i : out std_logic_vector(90 downto 0);
        ps_gpio_o : in  std_logic_vector(90 downto 0);
        ps_gpio_t : in  std_logic_vector(90 downto 0);

        -- PS IRQ
        ps_irq0 : out std_logic;
        ps_irq1 : out std_logic;

        -- PS SPI0
        ps_spi0_sck_i  : out std_logic;
        ps_spi0_sck_o  : in  std_logic;
        ps_spi0_sck_t  : in  std_logic;

        ps_spi0_m_i    : out std_logic;
        ps_spi0_m_o    : in  std_logic;
        ps_spi0_mo_t   : in  std_logic;

        ps_spi0_s_i    : out std_logic;
        ps_spi0_s_o    : in  std_logic;
        ps_spi0_so_t   : in  std_logic;

        ps_spi0_ssn_i  : out std_logic;
        ps_spi0_ssn_o  : in  std_logic;
        ps_spi0_ss1n_o : in  std_logic;
        ps_spi0_ssn_t  : in  std_logic;

        -- PS SPI1
        ps_spi1_sck_i  : out std_logic;
        ps_spi1_sck_o  : in  std_logic;
        ps_spi1_sck_t  : in  std_logic;

        ps_spi1_m_i    : out std_logic;
        ps_spi1_m_o    : in  std_logic;
        ps_spi1_mo_t   : in  std_logic;
        
        ps_spi1_s_i    : out std_logic;
        ps_spi1_s_o    : in  std_logic;
        ps_spi1_so_t   : in  std_logic;

        ps_spi1_ssn_i  : out std_logic;
        ps_spi1_ssn_o  : in  std_logic;
        ps_spi1_ss1n_o : in  std_logic;
        ps_spi1_ssn_t  : in  std_logic;


        -- Pinmux slaves
        DDR4_C0_sys_rst      : out std_logic;
        DDR4_C1_sys_rst      : out std_logic;
        DDR4_C0_cal_complete : in  std_logic;
        DDR4_C1_cal_complete : in  std_logic;

        CLK104_sync          : out std_logic;
        CLK104_SPI_sel       : out std_logic_vector(1 downto 0);

        sequencer_nrst       : out std_logic;
        sequencer_done       : in  std_logic;

        -- Physical pins
        ADCIO            : inout std_logic_vector(15 downto 0);
        DACIO            : inout std_logic_vector(15 downto 0);
        IDT_8A34001_GPIO : inout std_logic_vector(15 downto 0);
        PMOD0            : inout std_logic_vector(7 downto 0);
        PMOD1            : inout std_logic_vector(7 downto 0)
    );

end acadia_pinmux;

architecture rtl of acadia_pinmux is 
     
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

    -- Sequencer GPIO interface
    ATTRIBUTE X_INTERFACE_INFO of sequencer_gpio_i : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 sequencer_gpio TRI_I";
    ATTRIBUTE X_INTERFACE_INFO of sequencer_gpio_o : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 sequencer_gpio TRI_O";
    ATTRIBUTE X_INTERFACE_INFO of sequencer_gpio_t : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 sequencer_gpio TRI_T";
    ATTRIBUTE X_INTERFACE_MODE of sequencer_gpio_i : SIGNAL is "Slave";

    -- PS GPIO interface
    ATTRIBUTE X_INTERFACE_INFO of ps_gpio_i : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 ps_gpio TRI_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_gpio_o : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 ps_gpio TRI_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_gpio_t : SIGNAL is "xilinx.com:interface:gpio_rtl:1.0 ps_gpio TRI_T";
    ATTRIBUTE X_INTERFACE_MODE of ps_gpio_i : SIGNAL is "Slave";

    -- PS SPI0 interface
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_sck_i : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 SCK_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_sck_o : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 SCK_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_sck_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 SCK_T";

    -- MOSI is IO0
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_m_o  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 IO0_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_s_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 IO0_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_mo_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 IO0_T";

    -- MISO is IO1
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_m_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 IO1_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_s_o  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 IO1_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_so_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 IO1_T";

    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_ssn_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 SS_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_ssn_o  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 SS_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_ss1n_o : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 SS1_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi0_ssn_t  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi0 SS_T";
    
    ATTRIBUTE X_INTERFACE_MODE of ps_spi0_sck_i : SIGNAL is "Slave";

    -- PS SPI1
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_sck_i : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 SCK_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_sck_o : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 SCK_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_sck_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 SCK_T";

    -- MOSI is IO0
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_m_o  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 IO0_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_s_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 IO0_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_mo_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 IO0_T";

    -- MISO is IO1
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_m_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 IO1_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_s_o  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 IO1_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_so_t : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 IO1_T";

    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_ssn_i  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 SS_I";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_ssn_o : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 SS_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_ss1n_o : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 SS1_O";
    ATTRIBUTE X_INTERFACE_INFO of ps_spi1_ssn_t  : SIGNAL is "xilinx.com:interface:spi_rtl:1.0 ps_spi1 SS_T";
    
    ATTRIBUTE X_INTERFACE_MODE of ps_spi1_sck_i : SIGNAL is "Slave";

    signal axi_regs_in  : std_logic_vector(63 downto 0);
    signal axi_regs_out : std_logic_vector(63 downto 0);

    -- IOBUF interface signals
    signal adcio_buf_i : std_logic_vector(31 downto 0);
    signal adcio_buf_o : std_logic_vector(31 downto 0);
    signal adcio_buf_t : std_logic_vector(31 downto 0);

    signal dacio_buf_i : std_logic_vector(31 downto 0);
    signal dacio_buf_o : std_logic_vector(31 downto 0);
    signal dacio_buf_t : std_logic_vector(31 downto 0);

    signal pmod0_buf_i : std_logic_vector(7 downto 0);
    signal pmod0_buf_o : std_logic_vector(7 downto 0);
    signal pmod0_buf_t : std_logic_vector(7 downto 0);

    signal pmod1_buf_i : std_logic_vector(7 downto 0);
    signal pmod1_buf_o : std_logic_vector(7 downto 0);
    signal pmod1_buf_t : std_logic_vector(7 downto 0);

    -- multiplexer select signals
    alias adcio_sel0 : std_logic_vector(3 downto 0) is axi_regs_out(3 downto 0);
    alias adcio_sel1 : std_logic_vector(3 downto 0) is axi_regs_out(7 downto 4);
    alias adcio_sel2 : std_logic_vector(3 downto 0) is axi_regs_out(11 downto 8);
    alias adcio_sel3 : std_logic_vector(3 downto 0) is axi_regs_out(15 downto 12);
    alias dacio_sel0 : std_logic_vector(3 downto 0) is axi_regs_out(19 downto 16);
    alias dacio_sel1 : std_logic_vector(3 downto 0) is axi_regs_out(23 downto 20);
    alias dacio_sel2 : std_logic_vector(3 downto 0) is axi_regs_out(27 downto 24);
    alias dacio_sel3 : std_logic_vector(3 downto 0) is axi_regs_out(31 downto 28);
    alias pmod0_sel0 : std_logic_vector(3 downto 0) is axi_regs_out(35 downto 32);
    alias pmod0_sel1 : std_logic_vector(3 downto 0) is axi_regs_out(39 downto 36);
    alias pmod1_sel2 : std_logic_vector(3 downto 0) is axi_regs_out(43 downto 40);
    alias pmod1_sel3 : std_logic_vector(3 downto 0) is axi_regs_out(47 downto 44);

    
begin    

    regs_inst: entity work.acadia_axi_lite_regs
        generic map (
            N_REGS => 2,
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

    -- Static connections to PS GPIO
    sequencer_nrst <= ps_gpio_o(89);
    ps_gpio_i(88) <= sequencer_done;

    CLK104_sync <= ps_gpio_o(86);
    CLK104_SPI_sel <= ps_gpio_o(85 downto 84);
    
    DDR4_C0_sys_rst <= ps_gpio_o(83);
    DDR4_C1_sys_rst <= ps_gpio_o(82);
    ps_gpio_i(81) <= DDR4_C0_cal_complete;
    ps_gpio_i(80) <= DDR4_C1_cal_complete;

    axi_regs_in <= (others => '0');

    -- Output multiplexers
    dacio_buf_i(3 downto 0) <= "0000"                       when dacio_sel0 = x"0" else
                               sequencer_gpio_o(3 downto 0) when dacio_sel0 = x"1" else
                               ps_gpio_o(3 downto 0)        when dacio_sel0 = x"2" else
                               dma_flags(3 downto 0)        when dacio_sel0 = x"8" else 
                               dma_flags(7 downto 4)        when dacio_sel0 = x"9" else 
                               dma_flags(11 downto 8)       when dacio_sel0 = x"A" else 
                               dma_flags(15 downto 12)      when dacio_sel0 = x"B" else 
                               dma_flags(19 downto 16)      when dacio_sel0 = x"C" else 
                               dma_flags(23 downto 20)      when dacio_sel0 = x"D" else 
                               dma_flags(27 downto 24)      when dacio_sel0 = x"E" else 
                               dma_flags(31 downto 28)      when dacio_sel0 = x"F" else 
                               "0000";

    dacio_buf_t(3 downto 0) <= "1111"                       when dacio_sel0 = x"0" else
                               sequencer_gpio_t(3 downto 0) when dacio_sel0 = x"1" else
                               ps_gpio_t(3 downto 0)        when dacio_sel0 = x"2" else
                               "0000"                       when dacio_sel0 = x"8" else
                               "0000"                       when dacio_sel0 = x"9" else
                               "0000"                       when dacio_sel0 = x"A" else
                               "0000"                       when dacio_sel0 = x"B" else
                               "0000"                       when dacio_sel0 = x"C" else
                               "0000"                       when dacio_sel0 = x"D" else
                               "0000"                       when dacio_sel0 = x"E" else
                               "0000"                       when dacio_sel0 = x"F" else
                               "1111";

    sequencer_gpio_i(3 downto 0) <= dacio_buf_o(3 downto 0);
    ps_gpio_i(3 downto 0) <= dacio_buf_o(3 downto 0);


    dacio_buf_i(7 downto 4) <= "0000"                       when dacio_sel1 = x"0" else
                               sequencer_gpio_o(7 downto 4) when dacio_sel1 = x"1" else
                               ps_gpio_o(7 downto 4)        when dacio_sel1 = x"2" else
                               dma_flags(3 downto 0)        when dacio_sel1 = x"8" else 
                               dma_flags(7 downto 4)        when dacio_sel1 = x"9" else 
                               dma_flags(11 downto 8)       when dacio_sel1 = x"A" else 
                               dma_flags(15 downto 12)      when dacio_sel1 = x"B" else 
                               dma_flags(19 downto 16)      when dacio_sel1 = x"C" else 
                               dma_flags(23 downto 20)      when dacio_sel1 = x"D" else 
                               dma_flags(27 downto 24)      when dacio_sel1 = x"E" else 
                               dma_flags(31 downto 28)      when dacio_sel1 = x"F" else  
                               "0000";

    dacio_buf_t(7 downto 4) <= "1111"                       when dacio_sel1 = x"0" else
                               sequencer_gpio_t(7 downto 4) when dacio_sel1 = x"1" else
                               ps_gpio_t(7 downto 4)        when dacio_sel1 = x"2" else
                               "0000"                       when dacio_sel1 = x"8" else
                               "0000"                       when dacio_sel1 = x"9" else
                               "0000"                       when dacio_sel1 = x"A" else
                               "0000"                       when dacio_sel1 = x"B" else
                               "0000"                       when dacio_sel1 = x"C" else
                               "0000"                       when dacio_sel1 = x"D" else
                               "0000"                       when dacio_sel1 = x"E" else
                               "0000"                       when dacio_sel1 = x"F" else
                               "1111";

    sequencer_gpio_i(7 downto 4) <= dacio_buf_o(7 downto 4);
    ps_gpio_i(7 downto 4) <= dacio_buf_o(7 downto 4);


    dacio_buf_i(11 downto 8) <= "0000"                       when dacio_sel2 = x"0" else
                               sequencer_gpio_o(11 downto 8) when dacio_sel2 = x"1" else
                               ps_gpio_o(11 downto 8)        when dacio_sel2 = x"2" else
                               "0000"                        when dacio_sel2 = x"8" else
                               "0000"                        when dacio_sel2 = x"9" else
                               "0000"                        when dacio_sel2 = x"A" else
                               "0000"                        when dacio_sel2 = x"B" else
                               "0000"                        when dacio_sel2 = x"C" else
                               "0000"                        when dacio_sel2 = x"D" else
                               "0000"                        when dacio_sel2 = x"E" else
                               "0000"                        when dacio_sel2 = x"F" else
                               "0000";

    dacio_buf_t(11 downto 8) <= "1111"                       when dacio_sel2 = x"0" else
                               sequencer_gpio_t(11 downto 8) when dacio_sel2 = x"1" else
                               ps_gpio_t(11 downto 8)        when dacio_sel2 = x"2" else
                               "0000"                        when dacio_sel2 = x"3" else 
                               "1111";

    sequencer_gpio_i(11 downto 8) <= dacio_buf_o(11 downto 8);
    ps_gpio_i(11 downto 8) <= dacio_buf_o(11 downto 8);


    dacio_buf_i(15 downto 12) <= "0000"                       when dacio_sel3 = x"0" else
                               sequencer_gpio_o(15 downto 12) when dacio_sel3 = x"1" else
                               ps_gpio_o(15 downto 12)        when dacio_sel3 = x"2" else
                               dma_flags(3 downto 0)          when dacio_sel3 = x"8" else 
                               dma_flags(7 downto 4)          when dacio_sel3 = x"9" else 
                               dma_flags(11 downto 8)         when dacio_sel3 = x"A" else 
                               dma_flags(15 downto 12)        when dacio_sel3 = x"B" else 
                               dma_flags(19 downto 16)        when dacio_sel3 = x"C" else 
                               dma_flags(23 downto 20)        when dacio_sel3 = x"D" else 
                               dma_flags(27 downto 24)        when dacio_sel3 = x"E" else 
                               dma_flags(31 downto 28)        when dacio_sel3 = x"F" else 
                               "0000";

    dacio_buf_t(15 downto 12) <= "1111"                       when dacio_sel3 = x"0" else
                               sequencer_gpio_t(15 downto 12) when dacio_sel3 = x"1" else
                               ps_gpio_t(15 downto 12)        when dacio_sel3 = x"2" else
                               "0000"                         when dacio_sel3 = x"8" else
                               "0000"                         when dacio_sel3 = x"9" else
                               "0000"                         when dacio_sel3 = x"A" else
                               "0000"                         when dacio_sel3 = x"B" else
                               "0000"                         when dacio_sel3 = x"C" else
                               "0000"                         when dacio_sel3 = x"D" else
                               "0000"                         when dacio_sel3 = x"E" else
                               "0000"                         when dacio_sel3 = x"F" else
                               "1111";

    sequencer_gpio_i(15 downto 12) <= dacio_buf_o(15 downto 12);
    ps_gpio_i(15 downto 12) <= dacio_buf_o(15 downto 12);


    adcio_buf_i(3 downto 0) <= "0000"                         when adcio_sel0 = x"0" else
                               sequencer_gpio_o(19 downto 16) when adcio_sel0 = x"1" else
                               ps_gpio_o(19 downto 16)        when adcio_sel0 = x"2" else
                               dma_flags(3 downto 0)          when adcio_sel0 = x"8" else 
                               dma_flags(7 downto 4)          when adcio_sel0 = x"9" else 
                               dma_flags(11 downto 8)         when adcio_sel0 = x"A" else 
                               dma_flags(15 downto 12)        when adcio_sel0 = x"B" else 
                               dma_flags(19 downto 16)        when adcio_sel0 = x"C" else 
                               dma_flags(23 downto 20)        when adcio_sel0 = x"D" else 
                               dma_flags(27 downto 24)        when adcio_sel0 = x"E" else 
                               dma_flags(31 downto 28)        when adcio_sel0 = x"F" else  
                               "0000";

    adcio_buf_t(3 downto 0) <= "1111"                         when adcio_sel0 = x"0" else
                               sequencer_gpio_t(19 downto 16) when adcio_sel0 = x"1" else
                               ps_gpio_t(19 downto 16)        when adcio_sel0 = x"2" else
                               "0000"                         when adcio_sel0 = x"8" else
                               "0000"                         when adcio_sel0 = x"9" else
                               "0000"                         when adcio_sel0 = x"A" else
                               "0000"                         when adcio_sel0 = x"B" else
                               "0000"                         when adcio_sel0 = x"C" else
                               "0000"                         when adcio_sel0 = x"D" else
                               "0000"                         when adcio_sel0 = x"E" else
                               "0000"                         when adcio_sel0 = x"F" else
                               "1111";

    sequencer_gpio_i(19 downto 16) <= adcio_buf_o(3 downto 0);
    ps_gpio_i(19 downto 16) <= adcio_buf_o(3 downto 0);


    adcio_buf_i(7 downto 4) <= "0000"                         when adcio_sel1 = x"0" else
                               sequencer_gpio_o(23 downto 20) when adcio_sel1 = x"1" else
                               ps_gpio_o(23 downto 20)        when adcio_sel1 = x"2" else
                               dma_flags(3 downto 0)          when adcio_sel1 = x"8" else 
                               dma_flags(7 downto 4)          when adcio_sel1 = x"9" else 
                               dma_flags(11 downto 8)         when adcio_sel1 = x"A" else 
                               dma_flags(15 downto 12)        when adcio_sel1 = x"B" else 
                               dma_flags(19 downto 16)        when adcio_sel1 = x"C" else 
                               dma_flags(23 downto 20)        when adcio_sel1 = x"D" else 
                               dma_flags(27 downto 24)        when adcio_sel1 = x"E" else 
                               dma_flags(31 downto 28)        when adcio_sel1 = x"F" else 
                               "0000";

    adcio_buf_t(7 downto 4) <= "1111"                         when adcio_sel1 = x"0" else
                               sequencer_gpio_t(23 downto 20) when adcio_sel1 = x"1" else
                               ps_gpio_t(23 downto 20)        when adcio_sel1 = x"2" else
                               "0000"                         when adcio_sel1 = x"8" else
                               "0000"                         when adcio_sel1 = x"9" else
                               "0000"                         when adcio_sel1 = x"A" else
                               "0000"                         when adcio_sel1 = x"B" else
                               "0000"                         when adcio_sel1 = x"C" else
                               "0000"                         when adcio_sel1 = x"D" else
                               "0000"                         when adcio_sel1 = x"E" else
                               "0000"                         when adcio_sel1 = x"F" else
                               "1111";

    sequencer_gpio_i(23 downto 20) <= adcio_buf_o(7 downto 4);
    ps_gpio_i(23 downto 20) <= adcio_buf_o(7 downto 4);


    adcio_buf_i(11 downto 8) <= "0000"                        when adcio_sel2 = x"0" else
                               sequencer_gpio_o(27 downto 24) when adcio_sel2 = x"1" else
                               ps_gpio_o(27 downto 24)        when adcio_sel2 = x"2" else
                               dma_flags(3 downto 0)          when adcio_sel2 = x"8" else 
                               dma_flags(7 downto 4)          when adcio_sel2 = x"9" else 
                               dma_flags(11 downto 8)         when adcio_sel2 = x"A" else 
                               dma_flags(15 downto 12)        when adcio_sel2 = x"B" else 
                               dma_flags(19 downto 16)        when adcio_sel2 = x"C" else 
                               dma_flags(23 downto 20)        when adcio_sel2 = x"D" else 
                               dma_flags(27 downto 24)        when adcio_sel2 = x"E" else 
                               dma_flags(31 downto 28)        when adcio_sel2 = x"F" else 
                               "0000";

    adcio_buf_t(11 downto 8) <= "1111"                        when adcio_sel2 = x"0" else
                               sequencer_gpio_t(27 downto 24) when adcio_sel2 = x"1" else
                               ps_gpio_t(27 downto 24)        when adcio_sel2 = x"2" else
                               "0000"                         when adcio_sel2 = x"8" else
                               "0000"                         when adcio_sel2 = x"9" else
                               "0000"                         when adcio_sel2 = x"A" else
                               "0000"                         when adcio_sel2 = x"B" else
                               "0000"                         when adcio_sel2 = x"C" else
                               "0000"                         when adcio_sel2 = x"D" else
                               "0000"                         when adcio_sel2 = x"E" else
                               "0000"                         when adcio_sel2 = x"F" else
                               "1111";

    sequencer_gpio_i(27 downto 24) <= adcio_buf_o(11 downto 8);
    ps_gpio_i(27 downto 24) <= adcio_buf_o(11 downto 8);


    adcio_buf_i(15 downto 12) <= "0000"                       when adcio_sel3 = x"0" else
                               sequencer_gpio_o(31 downto 28) when adcio_sel3 = x"1" else
                               ps_gpio_o(31 downto 28)        when adcio_sel3 = x"2" else
                               dma_flags(3 downto 0)          when adcio_sel3 = x"8" else 
                               dma_flags(7 downto 4)          when adcio_sel3 = x"9" else 
                               dma_flags(11 downto 8)         when adcio_sel3 = x"A" else 
                               dma_flags(15 downto 12)        when adcio_sel3 = x"B" else 
                               dma_flags(19 downto 16)        when adcio_sel3 = x"C" else 
                               dma_flags(23 downto 20)        when adcio_sel3 = x"D" else 
                               dma_flags(27 downto 24)        when adcio_sel3 = x"E" else 
                               dma_flags(31 downto 28)        when adcio_sel3 = x"F" else 
                               "0000";

    adcio_buf_t(15 downto 12) <= "1111"                       when adcio_sel3 = x"0" else
                               sequencer_gpio_t(31 downto 28) when adcio_sel3 = x"1" else
                               ps_gpio_t(31 downto 28)        when adcio_sel3 = x"2" else
                               "0000"                         when adcio_sel3 = x"8" else
                               "0000"                         when adcio_sel3 = x"9" else
                               "0000"                         when adcio_sel3 = x"A" else
                               "0000"                         when adcio_sel3 = x"B" else
                               "0000"                         when adcio_sel3 = x"C" else
                               "0000"                         when adcio_sel3 = x"D" else
                               "0000"                         when adcio_sel3 = x"E" else
                               "0000"                         when adcio_sel3 = x"F" else
                               "1111";

    sequencer_gpio_i(31 downto 28) <= adcio_buf_o(15 downto 12);
    ps_gpio_i(31 downto 28) <= adcio_buf_o(15 downto 12);

    
    pmod0_buf_i(3 downto 0) <= "0000"                       when pmod0_sel0 = x"0" else
                               "0000"                       when pmod0_sel0 = x"1" else
                               ps_gpio_o(35 downto 32)      when pmod0_sel0 = x"2" else
                               (ps_spi0_sck_o & ps_spi0_ssn_o & ps_spi0_m_o & ps_spi0_s_o) when pmod0_sel0 = x"3" else 
                               "0000";

    pmod0_buf_t(3 downto 0) <= "1111"                       when pmod0_sel0 = x"0" else
                               "1111"                       when pmod0_sel0 = x"1" else
                               ps_gpio_t(35 downto 32)      when pmod0_sel0 = x"2" else
                               (ps_spi0_sck_t & ps_spi0_ssn_t & ps_spi0_mo_t & ps_spi0_so_t) when pmod0_sel0 = x"3" else 
                               "1111";

    ps_gpio_i(35 downto 32) <= pmod0_buf_o(3 downto 0);
    ps_spi0_sck_i <= pmod0_buf_o(3);
    ps_spi0_ssn_i <= pmod0_buf_o(2);
    ps_spi0_s_i <= pmod0_buf_o(1);
    ps_spi0_m_i <= pmod0_buf_o(0);

    pmod0_buf_i(7 downto 4) <= "0000"                       when pmod0_sel1 = x"0" else
                               "0000"                       when pmod0_sel1 = x"1" else
                               ps_gpio_o(39 downto 36)      when pmod0_sel1 = x"2" else
                               "0000"                       when pmod0_sel1 = x"3" else 
                               "0000";

    pmod0_buf_t(7 downto 4) <= "1111"                       when pmod0_sel1 = x"0" else
                               "1111"                       when pmod0_sel1 = x"1" else
                               ps_gpio_t(39 downto 36)      when pmod0_sel1 = x"2" else
                               "1111"                       when pmod0_sel1 = x"3" else 
                               "1111";


    -- Generate the buffers for the DACIO and the ADCIO
    DACIO_buf_gen: for i in 15 downto 0 generate
        DACIO_buf: IOBUF port map(
            I => dacio_buf_i(i), 
            O => dacio_buf_o(i), 
            T => dacio_buf_t(i), 
            IO => DACIO(i)
        );
    end generate DACIO_buf_gen;

    ADCIO_buf_gen: for i in 15 downto 0 generate
        ADCIO_buf: IOBUF port map(
            I => adcio_buf_i(i), 
            O => adcio_buf_o(i), 
            T => adcio_buf_t(i), 
            IO => ADCIO(i)
        );
    end generate ADCIO_buf_gen;
    
end rtl;
