----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 08/11/2022 03:36:24 PM
-- Design Name: acadia
-- Module Name: dma - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 
-- Description: DMA module for streaming DAC and ADC data.
--    The DMA is controlled by issuing commands over its register interface.
--    The command format is as follows:
--    Register 0: incrementing stream from most recent address for length
--      Bits 15 - 0: length-1
--      Bits 31 - 16: ignored
--    Register 1: incrementing stream from address for length
--      Bits 15 - 0: length-1
--      Bits 16+ADDRESS_WIDTH-1 - 16: address
--      Bits 31 to 16+ADDRESS_WIDTH: ignored
--    Register 2: fixed stream from most recent address for length
--      Bits COUNTER_WIDTH-1 - 0: length-1
--    Register 3: dwell for length
--      Bits COUNTER_WIDTH-1 - 0: length-1
--    Register 4:
--      Writing any value to this address resets the DMA.
--    
--    Reading from any register yields the following status flags:
--      Bit 0: running
--      Bit 1: FIFO empty
--      Bit 2: FIFO full
--      Bit 3: FIFO almost empty
--      Bit 4: FIFO almost full
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

library XPM;
use XPM.vcomponents.all;

entity acadia_dma is
    generic (
        DATA_WIDTH                 : positive := 32;
        ADDRESS_WIDTH              : positive := 16;
        COUNTER_WIDTH              : positive := 32;
        DESCRIPTOR_FIFO_DEPTH      : positive := 32
    );
    port (
        clk                 : in  std_logic;
        nrst                : in  std_logic;
        
        -- data input stream
        data_in             : in  std_logic_vector(DATA_WIDTH-1 downto 0);

        -- outputs with sideband signals
        data_out_tdata  : out std_logic_vector(DATA_WIDTH-1 downto 0);
        data_out_tvalid : out std_logic;
        data_out_tlast  : out std_logic;

        address_out_tdata  : out std_logic_vector(ADDRESS_WIDTH-1 downto 0);
        address_out_tvalid : out std_logic;
        address_out_tlast  : out std_logic;

        data_address_invalid : out std_logic;
        
        -- Register access
        master_bus_mosi : in  std_logic_vector(31 downto 0);
        master_bus_miso : out std_logic_vector(31 downto 0);
        master_bus_addr : in  std_logic_vector(31 downto 0);
        master_bus_we   : in  std_logic;
        master_bus_en   : in  std_logic;

        -- Auxiliary signals
        trigger        : in  std_logic;
        running        : out std_logic
    );

end acadia_dma;

architecture rtl of acadia_dma is 
     
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of clk      : SIGNAL is "xilinx.com:signal:clock:1.0 clk clk";
    ATTRIBUTE X_INTERFACE_PARAMETER of clk : SIGNAL is "ASSOCIATED_BUSIF data_out:address_out:master_bus";

    ATTRIBUTE X_INTERFACE_INFO of data_out_tdata      : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TDATA";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tvalid     : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TVALID";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tlast      : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TLAST";
    ATTRIBUTE X_INTERFACE_MODE of data_out_tdata      : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of data_out_tdata : SIGNAL is "HAS_TLAST 1,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 0,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(DATA_WIDTH/8);

    ATTRIBUTE X_INTERFACE_INFO of address_out_tdata      : SIGNAL is "xilinx.com:interface:axis:1.0 address_out TDATA";
    ATTRIBUTE X_INTERFACE_INFO of address_out_tvalid     : SIGNAL is "xilinx.com:interface:axis:1.0 address_out TVALID";
    ATTRIBUTE X_INTERFACE_INFO of address_out_tlast      : SIGNAL is "xilinx.com:interface:axis:1.0 address_out TLAST";
    ATTRIBUTE X_INTERFACE_MODE of address_out_tdata      : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of address_out_tdata : SIGNAL is "HAS_TLAST 1,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 0,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(ADDRESS_WIDTH/8);

    ATTRIBUTE X_INTERFACE_INFO of master_bus_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_miso: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_addr: SIGNAL is "xilinx.com:interface:bram:1.0 master_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_we  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of master_bus_en  : SIGNAL is "xilinx.com:interface:bram:1.0 master_bus EN";

    signal rst_int : std_logic;
    signal data_out_p : std_logic_vector(DATA_WIDTH-1 downto 0);
    signal address_out_p : std_logic_vector(ADDRESS_WIDTH-1 downto 0);

    -- Run state
    signal running_int      : std_logic;

    -- Descriptor FIFO signals
    signal fifo_dout: std_logic_vector(33 downto 0);
    signal fifo_rd   : std_logic;
    signal fifo_wr   : std_logic;
    signal fifo_full    : std_logic;
    signal fifo_empty   : std_logic;
    signal fifo_almost_full : std_logic;
    signal fifo_almost_empty : std_logic;
                                                
    -- Descriptor fields
    signal descriptor_lm1   : std_logic_vector(COUNTER_WIDTH-1 downto 0);
    signal descriptor_addr  : std_logic_vector(ADDRESS_WIDTH-1 downto 0);
    signal descriptor_fixed : std_logic;
    signal descriptor_blank : std_logic;
        
    -- Combinational progress flags
    signal descriptor_done  : std_logic;

    -- Internal drivers for sideband signals
    signal valid_int : std_logic;
    signal last_int  : std_logic;

    signal address_next : unsigned(ADDRESS_WIDTH-1 downto 0);
    
begin    
    
    rst_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                rst_int <= '1';
            elsif(master_bus_addr(2) = '1'
                    and master_bus_en = '1' 
                    and master_bus_we = '1') then
                rst_int <= master_bus_mosi(0);
            else
                rst_int <= '0';
            end if;
        end if;
    end process rst_proc;

    -- Descriptor FIFO and interface signals
    -- Because the FIFO is FWFT, we can pulse the FIFO read enable
    -- once we've already started the descriptor
    fifo_rd <= (trigger and not running_int) or (descriptor_done and running_int);
    fifo_wr <= master_bus_we and master_bus_en and not master_bus_addr(2);
    
    descriptor_fifo_inst : xpm_fifo_sync
        generic map (
            CASCADE_HEIGHT => 0,            -- DECIMAL
            DOUT_RESET_VALUE => "0",        -- String
            ECC_MODE => "no_ecc",           -- String
            FIFO_MEMORY_TYPE => "auto",     -- String
            FIFO_READ_LATENCY => 0,         -- DECIMAL
            FIFO_WRITE_DEPTH => DESCRIPTOR_FIFO_DEPTH,       -- DECIMAL
            FULL_RESET_VALUE => 0,          -- DECIMAL
            PROG_EMPTY_THRESH => 10,        -- DECIMAL
            PROG_FULL_THRESH => 10,         -- DECIMAL
            RD_DATA_COUNT_WIDTH => 1,       -- DECIMAL
            READ_DATA_WIDTH => 34,          -- DECIMAL
            READ_MODE => "fwft",             -- String
            SIM_ASSERT_CHK => 0,            -- DECIMAL; 0=disable simulation messages, 1=enable simulation messages
            USE_ADV_FEATURES => "0A0A",     -- String bit 1: prog_full, bit 3: almost_full, bit 9: prog_empty, bit 11: almost_empty
            WAKEUP_TIME => 0,               -- DECIMAL
            WRITE_DATA_WIDTH => 34,         -- DECIMAL
            WR_DATA_COUNT_WIDTH => 1        -- DECIMAL
        )
        port map (
            almost_empty => fifo_almost_empty,
            almost_full => fifo_almost_full, 
            data_valid => open,       
            dbiterr => open,
            dout => fifo_dout, 
            empty => fifo_empty,
            full => fifo_full,
            overflow => open,
            prog_empty => open,
            prog_full => open,
            rd_data_count => open,
            rd_rst_busy => open,  
            sbiterr => open, 
            underflow => open, 
            wr_ack => open, 
            wr_data_count => open,
            wr_rst_busy => open, 
            din(33 downto 32) => master_bus_addr(1 downto 0),
            din(31 downto 0) => master_bus_mosi,
            injectdbiterr => '0',
            injectsbiterr => '0',
            rd_en => fifo_rd,
            rst => rst_int, 
            sleep => '0', 
            wr_clk => clk, 
            wr_en => fifo_wr
        );
        
    descriptor_done <= '1' when unsigned(descriptor_lm1) = 0 else '0';
                                
    running_int_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst_int = '1' or (descriptor_done = '1' and fifo_empty = '1')) then
                running_int <= '0';
            elsif(trigger = '1') then
                running_int <= '1';
            end if;
        end if;
    end process running_int_proc;
        
    running <= running_int;
            
    
    descriptor_field_proc: process(clk) begin
        if rising_edge(clk) then
            -- There are two times we need to load descriptor fields:
            --
            -- - If we just triggered, then the FIFO could have been written 
            --   as late as the previous cycle, which means the descriptor FIFO output
            --   is presenting its data at the same edge as the rising edge of trigger.
            --   Because this is a synchronous process, we can therefore check trigger
            --   to determine whether we need to load a new descriptor, rather than taking
            --   an extra cycle to load the descriptor after being triggered.
            -- 
            -- - If we're in the last cycle of a descriptor, then we need to load 
            --   the next one if it exists
            if((trigger = '1' and running_int = '0') or (descriptor_done = '1' and fifo_empty = '0')) then
                -- Load a new address if necessary.
                -- If we're not loading a new address from the command directly, 
                -- then we want the descriptor address to be the one immediately 
                -- following the end of the currently-running descriptor.
                if(fifo_dout(33 downto 32) = "01") then
                    descriptor_addr <= fifo_dout(16+ADDRESS_WIDTH-1 downto 16);
                else
                    descriptor_addr <= std_logic_vector(unsigned(descriptor_addr) + 1);
                end if;
                
                if(fifo_dout(33) = '1') then
                    -- Either a fixed stream or a dwell command
                    -- Use the command bits as a long length and pick up 
                    -- from where the last command left off (we just don't update the address)
                    descriptor_lm1   <= fifo_dout(COUNTER_WIDTH-1 downto 0);
                    descriptor_fixed <= '1';
                    descriptor_blank <= fifo_dout(32);
                else
                    -- Otherwise, it's an arbitrary waveform command, so not fixed or blank
                    descriptor_fixed <= '0';
                    descriptor_blank <= '0';

                    -- The length comes directly from the command bits, but depending on which
                    -- arbitrary command we use, we might be loading a new address
                    descriptor_lm1(15 downto 0)                   <= fifo_dout(15 downto 0);
                    descriptor_lm1(descriptor_lm1'high downto 16) <= (others => '0');
                end if;
            elsif(running_int = '1') then
                -- We're not loading the fields, we're just running normally, 
                -- so decrement the number of remaining cycles.
                descriptor_lm1 <= std_logic_vector(unsigned(descriptor_lm1) - 1);

                -- Increment the address if it's an arbitrary descriptor 
                -- or if we're in the last cycle of a fixed descriptor.
                -- We will only be here in the last cycle if there's nothing left in the FIFO.
                -- TODO: do we actually need this? If there's anything left in the FIFO when 
                -- we're in the last cycle, this will be handled above. Do we actually care 
                -- about preserving the descriptor address and continuing from where we left 
                -- off for the last descriptor in a sequence?
                if(descriptor_fixed = '0' or descriptor_done = '1') then
                    descriptor_addr <= std_logic_vector(unsigned(descriptor_addr) + 1);
                end if;
            end if;
        end if;
    end process descriptor_field_proc;
            
      
    output_proc: process(clk) begin
        if rising_edge(clk) then
            -- Data output gets pipelined so that it's aligned with the handshake signals
            data_out_p <= data_in;
                       
            address_out_p <= std_logic_vector(descriptor_addr);
            
            -- Set the valid outputs depending on run state 
            valid_int <= running_int and (not descriptor_blank);
            
            -- Set the last outputs depending on run state and descriptor done
            last_int  <= running_int and (not descriptor_blank) and descriptor_done;
            
        end if;
    end process output_proc;

    data_out_tdata     <= data_out_p;
    data_out_tvalid    <= valid_int;
    data_out_tlast     <= last_int;
    address_out_tdata <= address_out_p;
    address_out_tvalid <= valid_int;
    address_out_tlast  <= last_int;
    data_address_invalid <= not valid_int;

    bus_miso_proc: process(clk) begin
        if rising_edge(clk) then
            master_bus_miso(0) <= running_int;
            master_bus_miso(1) <= fifo_empty;
            master_bus_miso(2) <= fifo_full;
            master_bus_miso(3) <= fifo_almost_empty;
            master_bus_miso(4) <= fifo_almost_full;
            master_bus_miso(31 downto 5) <= (others => '0');
        end if;
    end process bus_miso_proc;
    
end rtl;
