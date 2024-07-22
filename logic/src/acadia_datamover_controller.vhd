----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/25/2022 11:52:49 PM
-- Design Name: acadia
-- Module Name: acadia_datamover_controller - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: A module which provides an interface for controlling and 
-- monitoring an AXI DataMover from a memory bus.
-- 
-- The registers are:
--
--        - 0: CMD_ADDR/TRANSFER_STATUS
--            Writing to this register issues a command to the DataMover 
--            command FIFO whose address field is populated with the data
--            written to this register (plus the value of the 
--            CMD_ADDR_OFFSET register). The values of the other fields are 
--            derived from prior writes to other registers (see below).
--            Reading this register pops a word from the status FIFO.
--
--         - 1: CMD_BTT/TRANSFER_STATUS_COUNT
--             This register stores the number of bytes for the DataMover to
--             transfer when its next command is issued. Reading this register 
--             returns the number of status words received by the controller
--             since its last reset.
--
--         - 2: CMD_MISC/TOTAL_BYTES_TRANSFERRED
--             This register stores additional miscellaneous bits needed for a
--             DataMover command:
--                 0     : TYPE
--                 1     : EOF
--                 5-2   : TAG
--                 9-6   : xCACHE
--                 13-10 : xUSER
--                 AXI_ADDRESS_WIDTH-32+14 - 14 : ADDR high bits
--            
--             Writing 1 to bit 31 performs an internal reset. 
--                
--             Reading this register returns the total number of bytes 
--             transferred by the DataMover since the controller was last reset.
--
--         - 3: CMD_ADDR_OFFSET/CONTROLLER_STATUS
--             This register contains an offset that is added to the value 
--             written to CMD_ADDR when issuing to the DataMover itself. 
-- 
--             Reading this register returns a bitfield with some status signals:
--                 0: This bit is set once the DataMover command interface sets 
--                     TREADY after this module sets TVALID, indicating that it 
--                     accepted the command driven by the module (this includes
--                     when TREADY is already set when the command is issued).
--                 1: This bit is a latch driven by the error signal for the
--                    DataMover.

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

entity acadia_datamover_controller is
    generic (
        STATUS_COUNT_WIDTH : positive := 16;
        AXI_ADDRESS_WIDTH  : positive := 40
    );
    port (
        clk  : in  std_logic;

        -- An extra peripheral interface for monitoring attached FIFOs
        fifo_nrst     : out std_logic;
        fifo_rst      : out std_logic;
        fifo_overflow : in  std_logic;

        -- Register access
        master_bus_mosi : in  std_logic_vector(31 downto 0);
        master_bus_miso : out std_logic_vector(31 downto 0);
        master_bus_addr : in  std_logic_vector(31 downto 0);
        master_bus_we   : in  std_logic;
        master_bus_en   : in  std_logic;

        -- Datamover interface
        err        : in  std_logic;
        
        cmd_tdata  : out std_logic_vector(87 downto 0);
        cmd_tvalid : out std_logic;
        cmd_tready : in  std_logic;

        sts_tdata  : in  std_logic_vector(31 downto 0);
        sts_tvalid : in  std_logic;
        sts_tready : out std_logic
    );
    
    attribute USE_DSP : string;
end acadia_datamover_controller;

architecture rtl of acadia_datamover_controller is
    
    attribute USE_DSP of rtl : architecture is "YES";
    
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_INFO of clk      : SIGNAL is "xilinx.com:signal:clock:1.0 clk clk";
    ATTRIBUTE X_INTERFACE_PARAMETER of clk : SIGNAL is "ASSOCIATED_BUSIF master_bus:cmd:sts";
    
    ATTRIBUTE X_INTERFACE_INFO of cmd_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 cmd TDATA";
    ATTRIBUTE X_INTERFACE_INFO of cmd_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 cmd TVALID";
    ATTRIBUTE X_INTERFACE_INFO of cmd_tready : SIGNAL is "xilinx.com:interface:axis:1.0 cmd TREADY";
    ATTRIBUTE X_INTERFACE_MODE of cmd_tdata  : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of cmd_tdata: SIGNAL is "HAS_TLAST 0,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES 11";
    
    ATTRIBUTE X_INTERFACE_INFO of sts_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 sts TDATA";
    ATTRIBUTE X_INTERFACE_INFO of sts_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 sts TVALID";
    ATTRIBUTE X_INTERFACE_INFO of sts_tready : SIGNAL is "xilinx.com:interface:axis:1.0 sts TREADY";
    ATTRIBUTE X_INTERFACE_PARAMETER of sts_tdata: SIGNAL is "HAS_TLAST 0,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES 4";
    
    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_we  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";

    signal rst        : std_logic;

    signal fifo_overflow_d : std_logic;
            
    signal cmd_state               : std_logic_vector(1 downto 0); -- 0 = idle, 1 = dispatch, 2 = waiting, 3 = ack
    signal cmd_addr_offset         : std_logic_vector(AXI_ADDRESS_WIDTH-1 downto 0);
    signal cmd_addr_base           : std_logic_vector(AXI_ADDRESS_WIDTH-1 downto 0);
    signal cmd_addr                : std_logic_vector(AXI_ADDRESS_WIDTH-1 downto 0);

    signal cmd_btt                   : std_logic_vector(22 downto 0);
    signal cmd_tag                   : std_logic_vector(3 downto 0);
    signal cmd_user                  : std_logic_vector(3 downto 0);
    signal cmd_cache                 : std_logic_vector(3 downto 0);
    signal cmd_eof                   : std_logic;
    signal cmd_type                  : std_logic;
    
    signal err_latch                 : std_logic;
    signal sts                       : std_logic_vector(31 downto 0);
    signal sts_d                     : std_logic_vector(31 downto 0);
    signal sts_cnt                   : std_logic_vector(STATUS_COUNT_WIDTH-1 downto 0);
    signal sts_cnt_d                 : std_logic_vector(STATUS_COUNT_WIDTH-1 downto 0);
    signal total_bytes_transferred   : std_logic_vector(31 downto 0);
    signal total_bytes_transferred_d : std_logic_vector(31 downto 0);

begin

    fifo_nrst <= not rst;
    fifo_rst <= rst;

    -- Connect the output interface signals to various internal registers
    cmd_tvalid <= '1' when cmd_state = "10" else '0';
    cmd_tdata  <= cmd_user 
                & cmd_cache 
                & "0000" -- reserved
                & cmd_tag
                & cmd_addr
                & "0" -- DRR
                & cmd_eof
                & "000000" -- DSA
                & cmd_type
                & cmd_btt; 

    command_dispatch_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                cmd_state                  <= (others => '0');
                cmd_addr_base(31 downto 0) <= (others => '0');
            elsif(master_bus_en = '1' and master_bus_we = '1' and master_bus_addr(1 downto 0) = "00") then    
                cmd_state                  <= "01";
                cmd_addr_base(31 downto 0) <= master_bus_mosi;
            elsif(cmd_state = "01") then
                cmd_state <= "10";
                cmd_addr  <= std_logic_vector(unsigned(cmd_addr_base) + unsigned(cmd_addr_offset));
            elsif(cmd_state = "10" and cmd_tready = '1') then
                cmd_state <= "11";
            end if;
        end if;
    end process command_dispatch_proc;

    -- Use a process for writing to all the other normal registers
    reg_wr_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                rst       <= '0';
                cmd_btt   <= (others => '0');
                cmd_user  <= (others => '0');
                cmd_cache <= (others => '0');
                cmd_tag   <= (others => '0');
                cmd_eof   <= '0';
                cmd_type  <= '0';
                cmd_addr_base(AXI_ADDRESS_WIDTH-1 downto 32) <= (others => '0');
                cmd_addr_offset <= (others => '0');    
            elsif(master_bus_en = '1' and master_bus_we = '1' and master_bus_addr(1 downto 0) = "01") then
                cmd_btt <= master_bus_mosi(22 downto 0);
            elsif(master_bus_en = '1' and master_bus_we = '1' and master_bus_addr(1 downto 0) = "10") then
                cmd_addr_base(AXI_ADDRESS_WIDTH-1 downto 32) <= master_bus_mosi(AXI_ADDRESS_WIDTH-32+14-1 downto 14);
                cmd_user  <= master_bus_mosi(13 downto 10);
                cmd_cache <= master_bus_mosi(9 downto 6);
                cmd_tag   <= master_bus_mosi(5 downto 2);
                cmd_eof   <= master_bus_mosi(1);
                cmd_type  <= master_bus_mosi(0);
                rst       <= master_bus_mosi(31);
            elsif(master_bus_en = '1' and master_bus_we = '1' and master_bus_addr(1 downto 0) = "11") then
                cmd_addr_offset(31 downto 0) <= master_bus_mosi;
            end if;
        end if;
    end process reg_wr_proc;
        
    -- Make a process for reading registers  
    rd_proc: process(clk) begin
        if rising_edge(clk) then
            fifo_overflow_d <= fifo_overflow;
            case master_bus_addr(1 downto 0) is
                when "00" =>
                    master_bus_miso <= sts_d;
                when "01" =>
                    master_bus_miso(31 downto STATUS_COUNT_WIDTH)  <= (others => '0');
                    master_bus_miso(STATUS_COUNT_WIDTH-1 downto 0) <= sts_cnt_d;
                when "10" =>
                    master_bus_miso <= total_bytes_transferred_d;
                when "11" => 
                    master_bus_miso(1 downto 0)  <= cmd_state;
                    master_bus_miso(2)           <= err_latch;
                    master_bus_miso(3)           <= fifo_overflow_d;
                    master_bus_miso(31 downto 4) <= (others => '0');
                when others =>
                    master_bus_miso <= (others => '0');
                end case;
        end if;
    end process rd_proc;

    -- make a process for reading status words when they're available
    sts_tready <= not rst;
    -- Create a status counter
    datamover_sts_proc: process(clk) begin 
        if rising_edge(clk) then
            -- Pipeline the status signals
            sts_d                     <= sts;
            sts_cnt_d                 <= sts_cnt;
            total_bytes_transferred_d <= total_bytes_transferred;

            if(rst = '1') then
                sts                     <= (others => '0');
                sts_cnt                 <= (others => '0');
                total_bytes_transferred <= (others => '0');
            elsif(sts_tvalid = '1') then
                sts                     <= sts_tdata;
                sts_cnt                 <= std_logic_vector(unsigned(sts_cnt) + 1);
                total_bytes_transferred <= std_logic_vector(unsigned(total_bytes_transferred) 
                                                          + unsigned(sts_tdata(30 downto 8)));
            end if;
        end if;
    end process datamover_sts_proc; 

    -- Create a process for latching the error signal
    err_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                err_latch <= '0';
            elsif(err = '1') then
                err_latch <= '1';
            end if;
        end if;
    end process err_proc;

end rtl;
