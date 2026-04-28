----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 03/06/2023 04:58:59 PM
-- Design Name: acadia
-- Module Name: acadia_axi_lite_regs - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: A simple module that implements four 32-bit registers that can be 
--    written and read over an AXI-Lite interface. This is not a high-performance
--    module; both reads and writes are state-machine-driven, so there's a minimum
--    latency of two cycles for both. 
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

library xpm;
use xpm.vcomponents.all;

entity acadia_axi_lite_regs is
    generic (
        N_REGS       : positive := 4;
        AXI_ADDRESS_BITS : positive := 32
    );
    port (
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

        -- Register interface
        regs_out      : out std_logic_vector(N_REGS*32 - 1 downto 0);
        regs_in       : in  std_logic_vector(N_REGS*32 - 1 downto 0)
    );
end acadia_axi_lite_regs;

architecture rtl of acadia_axi_lite_regs is
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

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

    signal read_state  : std_logic_vector(0 downto 0);
    signal write_state : std_logic_vector(0 downto 0);

    signal have_write_addr : std_logic;
    signal write_addr : std_logic_vector(s_axi_awaddr'high downto 0);
    signal have_write_data : std_logic;
    signal write_data : std_logic_vector(s_axi_wdata'high downto 0);
    signal write_strb : std_logic_vector(s_axi_wstrb'high downto 0);

begin

    -- Process read requests from the master
    -- State 0 is idling, state 1 is waiting for the master to acknowledge the read
    -- Note that we idle with arready high. this allows us to efficiently clear arready 
    -- and set rvalid at the transition that we detect arvalid high. it'll then stay low
    -- until we detect rready
    read_proc: process(s_axi_aclk) 
        variable reg_idx : integer; 
    begin
        if rising_edge(s_axi_aclk) then
            if(s_axi_aresetn = '0') then
                s_axi_arready <= '1';
                s_axi_rvalid  <= '0';
                s_axi_rdata   <= (others => '0');
                s_axi_rresp   <= (others => '0');
                read_state    <= "0";
            elsif(read_state = "0" and s_axi_arvalid = '1') then
                s_axi_arready <= '0';
                s_axi_rvalid  <= '1';
                read_state    <= "1";
                
                -- Assign s_axi_rdata according to read address
                reg_idx := to_integer(unsigned(s_axi_araddr(s_axi_araddr'high downto 2)));
                s_axi_rdata <= regs_in((32*reg_idx)+31 downto (32*reg_idx));
                        
            elsif(read_state = "1" and s_axi_rready = '1') then
                s_axi_arready <= '1';
                s_axi_rvalid  <= '0';
                read_state    <= "0";
            end if;
        end if;
    end process read_proc;

    -- The write data and write address channels don't have 
    -- any requirements for alignment, so we need to be able 
    -- to accept them in any order. Therefore, we'll make
    -- separate processes for each of them (though they're
    -- nearly identical).
    s_axi_wready <= not have_write_data;
    write_data_proc: process(s_axi_aclk) begin
        if rising_edge(s_axi_aclk) then
            if(s_axi_aresetn = '0') then
                have_write_data <= '0';
                write_data <= (others => '0');
            elsif(have_write_data = '0' and s_axi_wvalid = '1') then
                -- If we don't already have data stored, load it
                -- this will also clear wready
                have_write_data <= '1';
                write_data <= s_axi_wdata;
                write_strb <= s_axi_wstrb;
            elsif(write_state = "1") then
                -- Write state = 1 indicates that we've done the write and 
                -- no longer need the address or data, but we are still waiting 
                -- for the master to accept the response. During this time we can 
                -- accept a new address and data, which will then be used right 
                -- after the master accepts the response from this transaction.
                have_write_data <= '0';
            end if;
        end if;
    end process write_data_proc;

    s_axi_awready <= not have_write_addr;
    write_addr_proc: process(s_axi_aclk) begin
        if rising_edge(s_axi_aclk) then
            if(s_axi_aresetn = '0') then
                have_write_addr <= '0';
                write_addr <= (others => '0');
            elsif(have_write_addr = '0' and s_axi_awvalid = '1') then
                have_write_addr <= '1';
                write_addr <= s_axi_awaddr;
            elsif(write_state = "1") then
                have_write_addr <= '0';
            end if;
        end if;
    end process write_addr_proc;

    -- For the sake of simplicity, we'll assume that the 
    -- master always issues valid transactions so we'll 
    -- only ever respond with "okay"
    s_axi_bresp <= "00";
    write_proc: process(s_axi_aclk) 
        variable reg_idx : integer; 
    begin
        if rising_edge(s_axi_aclk) then
            if(s_axi_aresetn = '0') then
                s_axi_bvalid  <= '0';
                write_state   <= "0";
                regs_out      <= (others => '0');
            elsif(write_state = "0" and have_write_addr = '1' and have_write_data = '1') then
                -- Update regs according to address, data, and strobe
                reg_idx := to_integer(unsigned(write_addr(write_addr'high downto 2)));
                byte_loop: for i in 0 to 3 loop
                    if(write_strb(i) = '1') then
                        regs_out((32*reg_idx)+(i*8)+7 downto (32*reg_idx)+(i*8)) <= write_data((i*8)+7 downto (i*8));
                    end if;
                end loop byte_loop;

                -- Present the write response and wait for it to be accepted
                s_axi_bvalid  <= '1';
                write_state   <= "1";
            elsif(write_state = "1" and s_axi_bready = '1') then
                s_axi_bvalid  <= '0';
                write_state   <= "0";
            end if;
        end if;
    end process write_proc;
    

end rtl;