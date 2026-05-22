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
-- Note that transfers may not cross 32-bit boundaries.
-- 
-- The registers are:
--
--        - 0: ADDRESS_LO (R/W)
--            This register stores the lower 32 bits of the transfer address, 
--            which may be incremented if multiple commands are issued to the DataMover. 
--            Writing to this register also initiates the transfer by sending the first 
--            command to the DataMover. The values of the other command fields are 
--            derived from the values of other internal registers.
--
--         - 1: SIZE (R/W)
--             This register stores the size of the transfer, which may be different from the 
--             size of command issued to the DataMover. The value of this register will be
--             decremented as the transfer progresses.
--
--         - 2: COMMAND_MISC (R/W)
--             This register stores additional miscellaneous bits needed for a
--             DataMover command:
--                 0     : TYPE
--                 1     : EOF
--                 5-2   : TAG
--                 9-6   : xCACHE
--                 13-10 : xUSER
--                 AXI_ADDRESS_WIDTH-32+14-1 - 14 : ADDR high bits
--                
--         - 3: CONTROLLER_STATUS (R/W)
--             Writing any value to this register resets the controller.
-- 
--             Reading this register returns a bitfield with some status signals:
--                 2-0: Dispatch state
--                 3: This bit is a latch driven by the error signal for the
--                    DataMover.
--
--         - 4: COMMAND_STATUS (R)
--             This register contains the most recently received status word from the DataMover. 
--             Writing has no effect.
--
--         - 5: COMMAND_STATUS_COUNT (R/W)
--             This register is a counter that increments each time a status word is received
--              from the DataMover. Writing any value to this register will clear it,
--              and this will take priority over being updated from the receipt of a 
--              status word.
--
--         - 6: TOTAL_BYTES_TRANSFERRED (R/W)
--             This register is a counter that increases each time a status word is received
--              from the DataMover, and is increased by the number of bytes reported by the status 
--              word. The bus master may write to this register to update its value,
--              and such an update will take priority over being updated from the receipt of a 
--              status word.
--
--         - 7: RESERVED
--
--             
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
use IEEE.STD_LOGIC_MISC.ALL;
use IEEE.NUMERIC_STD.ALL;

library XPM;
use XPM.vcomponents.all;

entity acadia_datamover_controller is
    generic (
        STATUS_COUNT_WIDTH : positive := 16;
        AXI_ADDRESS_WIDTH  : positive := 40;
        LOG2_MAX_COMMAND_SIZE  : positive := 22;
        ERR_ASYNCHRONOUS : boolean := true
    );
    port (
        clk  : in  std_logic;

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
    
    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_we  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 master_bus EN";

    signal rst             : std_logic;
            
    signal dispatch_state  : std_logic_vector(2 downto 0); 
    signal address_lo      : std_logic_vector(31 downto 0);
    signal address_hi      : std_logic_vector(AXI_ADDRESS_WIDTH-32-1 downto 0);

    signal cmd_addr        : std_logic_vector(AXI_ADDRESS_WIDTH-1 downto 0);
    signal cmd_btt         : std_logic_vector(22 downto 0);
    signal cmd_tag         : std_logic_vector(3 downto 0);
    signal cmd_user        : std_logic_vector(3 downto 0);
    signal cmd_cache       : std_logic_vector(3 downto 0);
    signal cmd_eof         : std_logic;
    signal cmd_type        : std_logic;

    -- The big command size is chosen to be a power of 2 so that we only need to do arithmetic on 
    -- some of the upper bits of the size register. If the big command size is written as (1 << x), 
    -- then the number of big commands we need is contained in size(31 downto x), so this
    -- makes it efficient to keep track of the number of big commands by just aliasing these bits of
    -- the size register 
    -- Example: Suppose the big command size is 16. 16 = (1 << 4), LOG2_MAX_COMMAND_SIZE = 4
    --  number of big commands = size(31 downto 4) remainder: size(3 downto 0)

    constant BIG_COMMAND_SIZE : std_logic_vector(cmd_btt'high downto 0) := (LOG2_MAX_COMMAND_SIZE => '1', others => '0');

    signal size            : std_logic_vector(31 downto 0);
    alias num_big_cmds     : std_logic_vector(32-LOG2_MAX_COMMAND_SIZE-1 downto 0) is size(31 downto LOG2_MAX_COMMAND_SIZE);
    alias small_cmd_size   : std_logic_vector(LOG2_MAX_COMMAND_SIZE-1 downto 0) is size(LOG2_MAX_COMMAND_SIZE-1 downto 0);
    
    -- Do we still have big or small commands to issue?
    signal issue_big_cmd   : std_logic;
    signal issue_small_cmd : std_logic;

    signal err_sync                  : std_logic;
    signal sts                       : std_logic_vector(31 downto 0);
    signal sts_d                     : std_logic_vector(31 downto 0);
    signal sts_cnt                   : std_logic_vector(STATUS_COUNT_WIDTH-1 downto 0);
    signal sts_cnt_d                 : std_logic_vector(STATUS_COUNT_WIDTH-1 downto 0);
    signal total_bytes_transferred   : std_logic_vector(31 downto 0);
    signal total_bytes_transferred_d : std_logic_vector(31 downto 0);

begin

    -- Connect the output interface signals to various internal registers
    cmd_tdata  <= cmd_user 
                & cmd_cache 
                & "0000" -- reserved
                & cmd_tag
                & address_hi & address_lo
                & "0" -- DRR
                & cmd_eof
                & "000000" -- DSA
                & cmd_type
                & cmd_btt; 

    command_dispatch_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                dispatch_state         <= (others => '0');
                cmd_tvalid             <= '0';
            elsif(master_bus_en = '1' and master_bus_we = '1' and master_bus_addr(2 downto 0) = "001") then
                -- Load total transfer size
                size <= master_bus_mosi;
                dispatch_state <= "001";
            elsif(master_bus_en = '1' and master_bus_we = '1' and master_bus_addr(2 downto 0) = "000" and dispatch_state = "001") then
                -- The transfer size was written in the previous state, 
                -- so now we can load the address and determine whether this is the 
                -- final command of the transfer or whether additional transfers are needed
                address_lo     <= master_bus_mosi;
                
                -- Check whether we have any big or small commands
                -- It's possible to have big commands but no small commands if the total
                -- transfer size is an integer number of big commands
                issue_big_cmd <= or_reduce(num_big_cmds);
                issue_small_cmd <= or_reduce(small_cmd_size);

                -- Move to next state
                dispatch_state <= "010";
            elsif(dispatch_state = "010") then
                -- If we still have commands to issue, assign the fields of the command
                -- and update the remaining size
                if(issue_big_cmd = '1') then
                    -- We still have a big command to issue
                    -- Mark the command as valid and wait for it to be accepted by the DataMover command FIFO
                    dispatch_state <= "011";
                    cmd_tvalid     <= '1';
                    cmd_btt        <= BIG_COMMAND_SIZE;
                    num_big_cmds   <= std_logic_vector(unsigned(num_big_cmds) - 1);
                elsif(issue_small_cmd = '1') then
                    -- No more big commands but there is a small command for the remainder
                    -- Mark the command as valid and wait for it to be accepted by the DataMover command FIFO
                    dispatch_state <= "011";
                    cmd_tvalid     <= '1';
                    cmd_btt(cmd_btt'high downto LOG2_MAX_COMMAND_SIZE) <= (others => '0');
                    cmd_btt(LOG2_MAX_COMMAND_SIZE-1 downto 0)          <= small_cmd_size;
                    size           <= (others => '0');
                else
                    -- All commands done, enter completed state
                    dispatch_state <= "100";
                end if;
            elsif(dispatch_state = "011" and cmd_tready = '1') then
                -- A command we issued has been accepted by the DataMover
                -- Deassert the command valid signal so that we only issue it once
                cmd_tvalid     <= '0';

                -- Decide whether we need to issue another command
                issue_big_cmd  <= or_reduce(num_big_cmds);
                issue_small_cmd <= or_reduce(small_cmd_size);

                -- Increment our internal address register by the size of the transfer that was just accepted
                -- so that if we issue another one, it starts from the correct address
                address_lo <= std_logic_vector(unsigned(address_lo) + unsigned(cmd_btt));

                -- Return to the "issue command if there is one" state
                dispatch_state <= "010";
            end if;
        end if;
    end process command_dispatch_proc;

    -- Use a process for writing to the misc register
    misc_reg_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                rst        <= '0';
                address_hi <= (others => '0');
                cmd_user   <= (others => '0');
                cmd_cache  <= (others => '0');
                cmd_tag    <= (others => '0');
                cmd_eof    <= '0';
                cmd_type   <= '0';
            elsif(master_bus_en = '1' and master_bus_we = '1') then
                if(master_bus_addr(2 downto 0) = "010") then
                    address_hi <= master_bus_mosi(AXI_ADDRESS_WIDTH-32+14-1 downto 14);
                    cmd_user  <= master_bus_mosi(13 downto 10);
                    cmd_cache <= master_bus_mosi(9 downto 6);
                    cmd_tag   <= master_bus_mosi(5 downto 2);
                    cmd_eof   <= master_bus_mosi(1);
                    cmd_type  <= master_bus_mosi(0);
                elsif(master_bus_addr(2 downto 0) = "011") then
                    rst <= '1';
                end if;
            end if;
        end if;
    end process misc_reg_proc;
        
    -- Make a process for reading registers  
    rd_proc: process(clk) begin
        if rising_edge(clk) then
            case master_bus_addr(2 downto 0) is
                when "000" =>
                    master_bus_miso <= address_lo;
                when "001" =>
                    master_bus_miso <= size;
                when "010" =>
                    master_bus_miso(AXI_ADDRESS_WIDTH-32+14-1 downto 14) <= address_hi;
                    master_bus_miso(13 downto 10) <= cmd_user;
                    master_bus_miso(9 downto 6) <= cmd_cache;
                    master_bus_miso(5 downto 2) <= cmd_tag;
                    master_bus_miso(1) <= cmd_eof;
                    master_bus_miso(0) <= cmd_type;
                when "011" => 
                    master_bus_miso(2 downto 0)  <= dispatch_state;
                    master_bus_miso(3)           <= err_sync;
                    master_bus_miso(31 downto 3) <= (others => '0');
                when "100" =>
                    master_bus_miso <= sts_d;
                when "101" =>
                    master_bus_miso(31 downto STATUS_COUNT_WIDTH)  <= (others => '0');
                    master_bus_miso(STATUS_COUNT_WIDTH-1 downto 0) <= sts_cnt_d;
                when "110" =>
                    master_bus_miso <= total_bytes_transferred_d;
                
                when others =>
                    master_bus_miso <= (others => '0');
                end case;
        end if;
    end process rd_proc;

    -- Process for receiving the status from the DataMover
    sts_tready <= not rst;
    
    sts_proc: process(clk) begin 
        if rising_edge(clk) then
            -- Pipeline the status signals
            sts_d <= sts;

            if(rst = '1') then
                sts <= (others => '0');
            elsif(sts_tvalid = '1') then
                sts <= sts_tdata;
            end if;

        end if;
    end process sts_proc; 

    sts_cnt_proc: process(clk) begin 
        if rising_edge(clk) then
            sts_cnt_d <= sts_cnt;

            if(rst = '1') then
                sts_cnt <= (others => '0');
            elsif(master_bus_en = '1' and master_bus_we = '1' and master_bus_addr(2 downto 0) = "101") then
                sts_cnt <= (others => '0');
            elsif(sts_tvalid = '1') then
                sts_cnt <= std_logic_vector(unsigned(sts_cnt) + 1);
            end if;

        end if;
    end process sts_cnt_proc; 

    total_bytes_transferred_proc: process(clk) begin
        if rising_edge(clk) then
            total_bytes_transferred_d <= total_bytes_transferred;

            if(rst = '1') then
                total_bytes_transferred <= (others => '0');
            elsif(master_bus_en = '1' and master_bus_we = '1' and master_bus_addr(2 downto 0) = "110") then
                total_bytes_transferred <= master_bus_mosi;
            elsif(sts_tvalid = '1') then
                total_bytes_transferred <= std_logic_vector(unsigned(total_bytes_transferred) 
                                                          + unsigned(sts_tdata(30 downto 8)));
            end if;
            
        end if;
    end process total_bytes_transferred_proc;

    -- Synchronize the latched error signal from the datamover if necessary

    err_async_gen: if ERR_ASYNCHRONOUS = true generate
        xpm_cdc_err_inst : xpm_cdc_sync_rst
            generic map (
                DEST_SYNC_FF => 4,   
                INIT_SYNC_FF => 0,   
                SIM_ASSERT_CHK => 0
            )
            port map (
                dest_rst => err_sync, 
                dest_clk => clk, 
                src_rst => err
            );
    end generate err_async_gen;

    err_sync_gen: if ERR_ASYNCHRONOUS = false generate
        err_sync <= err;
    end generate err_sync_gen;

end rtl;
