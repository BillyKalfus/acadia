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
        DATA_WIDTH                : natural := 32;
        ADDRESS_WIDTH             : natural := 16;
        ADDRESS_COUNTER_WIDTH     : natural := 32;
        DESCRIPTOR_MEM_ADDR_WIDTH : natural := 16;
        DESCRIPTOR_FIFO_DEPTH     : natural := 16
    );
    port (
        clk                 : in  std_logic;
        nrst                : in  std_logic;

        trigger             : in  std_logic;

        -- Descriptor memory interface
        descriptor_mem_dout : in  std_logic_vector(63 downto 0);
        descriptor_mem_addr : out std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
        descriptor_mem_clk  : out std_logic;
        
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
        
        -- Descriptor FIFO interface
        descriptor_address_fifo_in           : in  std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
        descriptor_address_fifo_wr           : in  std_logic;
        descriptor_address_fifo_almost_empty : out std_logic;
        descriptor_address_fifo_empty        : out std_logic;
        
        running        : out std_logic
    );

    -- attribute USE_DSP : string;

end acadia_dma;

architecture rtl of acadia_dma is 
    
    -- attribute USE_DSP of rtl : architecture is "YES";

    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of clk      : SIGNAL is "xilinx.com:signal:clock:1.0 clk clk";
    ATTRIBUTE X_INTERFACE_PARAMETER of clk : SIGNAL is "ASSOCIATED_BUSIF data_out:address_out:descriptor_mem";

    ATTRIBUTE X_INTERFACE_INFO of descriptor_mem_dout : SIGNAL is "xilinx.com:interface:bram:1.0 descriptor_mem DOUT";
    ATTRIBUTE X_INTERFACE_INFO of descriptor_mem_addr : SIGNAL is "xilinx.com:interface:bram:1.0 descriptor_mem ADDR";
    ATTRIBUTE X_INTERFACE_INFO of descriptor_mem_clk  : SIGNAL is "xilinx.com:interface:bram:1.0 descriptor_mem CLK";
    ATTRIBUTE X_INTERFACE_MODE of descriptor_mem_dout : SIGNAL is "Master";

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

    -- Inverted reset
    signal rst              : std_logic;

    -- Run state
    signal running_int      : std_logic;

    -- Descriptor address FIFO
    signal fifo_empty_int   : std_logic;
    signal fifo_rd_en_int   : std_logic;
                                                
    -- Descriptor fields
    signal descriptor_lm1   : unsigned(ADDRESS_COUNTER_WIDTH-1 downto 0);
    signal descriptor_addr  : unsigned(ADDRESS_WIDTH-1 downto 0);
    signal descriptor_dec   : std_logic_vector(1 downto 0);
    signal descriptor_fixed : std_logic;
    signal descriptor_blank : std_logic;
    
    -- Progress counters
    signal descriptor_point : unsigned(ADDRESS_COUNTER_WIDTH-1 downto 0);
    
    -- Combinational progress flags
    signal decimation_valid : std_logic;
    signal descriptor_done  : std_logic;

    -- Internal drivers for sideband signals
    signal valid_int : std_logic;
    signal last_int  : std_logic;
    
begin    
    
    -- Create an active-high reset for the fifo
    rst <= not nrst;
    
    -- Control the interface to descriptor memory
    descriptor_mem_clk  <= clk;
    
    descriptor_address_fifo_inst: entity work.acadia_dma_fifo
        generic map(
            WIDTH => DESCRIPTOR_MEM_ADDR_WIDTH
        )
        port map(
            clk          => clk, 
            nrst         => nrst, 
            din          => descriptor_address_fifo_in,
            wr_en        => descriptor_address_fifo_wr,
            dout         => descriptor_mem_addr,
            rd_en        => fifo_rd_en_int,
            empty        => fifo_empty_int,
            almost_empty => descriptor_address_fifo_almost_empty);
        
    -- Because the FIFO is FWFT, we can pulse the FIFO read enable
    -- once we've already started the descriptor
    fifo_rd_en_int <= (trigger and not running_int) or descriptor_done;
    descriptor_address_fifo_empty <= fifo_empty_int;

    -- Establish some progress flags
    -- These should ideally be mapped into the DSP slice pattern detector
    descriptor_done <= '1' when descriptor_point = descriptor_lm1 else '0';
                                
    running_int_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0' or (descriptor_done and fifo_empty_int) = '1') then
                running_int <= '0';
            elsif(trigger = '1') then
                running_int <= '1';
            end if;
        end if;
    end process running_int_proc;
        
    running <= running_int;
            
    -- Assign signals from descriptor fields
    -- There are two times we need to load descriptor fields:
    -- - If we just triggered, then the FIFO could have been written 
    --   as late as the previous cycle, which means the descriptor memory output
    --   is presenting its data at the same edge as the rising edge of trigger.
    --   Because this is a synchronous process, we can therefore check trigger
    --   to determine whether we need to load a new descriptor.
    -- - If we're in the last cycle of a descriptor, then we need to load.
    descriptor_field_load_proc: process(clk) begin
        if rising_edge(clk) then
            if((trigger = '1' and running_int = '0') or descriptor_done = '1') then
                descriptor_lm1   <= unsigned(descriptor_mem_dout(ADDRESS_COUNTER_WIDTH-1 downto 0));
                descriptor_addr  <= unsigned(descriptor_mem_dout(ADDRESS_COUNTER_WIDTH + ADDRESS_WIDTH-1 downto ADDRESS_COUNTER_WIDTH));
                descriptor_dec   <= descriptor_mem_dout(descriptor_mem_dout'high-2 downto descriptor_mem_dout'high-3);
                descriptor_fixed <= descriptor_mem_dout(descriptor_mem_dout'high-1);
                descriptor_blank <= descriptor_mem_dout(descriptor_mem_dout'high);
            end if;
        end if;
    end process descriptor_field_load_proc;
            
    -- Progress through the descriptor one point at a time
    descriptor_point_proc: process(clk) begin
        if rising_edge(clk) then
            if((trigger = '1' and running_int = '0') or descriptor_done = '1') then
                descriptor_point <= (others => '0');
            else
                descriptor_point <= descriptor_point + 1;
            end if;
        end if;
    end process descriptor_point_proc;

    -- We'll choose to make the last sample in the decimation the 
    -- valid one solely because then we can condition the "last"
    -- signal on this and descriptor_done
    decimation_valid <= '1' when descriptor_dec = "00" else
                        '1' when (descriptor_dec = "01" and descriptor_point(0) = '1') else
                        '1' when (descriptor_dec = "10" and descriptor_point(1 downto 0) = "11") else
                        '1' when (descriptor_dec = "11" and descriptor_point(2 downto 0) = "111") else
                        '0';
      
    output_proc: process(clk) begin
        if rising_edge(clk) then
            -- Data output gets pipelined so that it's aligned with the handshake signals
            data_out_tdata <= data_in;

            -- Update the address outputs depending on whether the descriptor is fixed or not
            if(descriptor_fixed = '1') then                
                address_out_tdata <= std_logic_vector(descriptor_addr);
            elsif(descriptor_dec = "01") then
                address_out_tdata <= std_logic_vector(descriptor_point(ADDRESS_WIDTH downto 1) + descriptor_addr);
            elsif(descriptor_dec = "10") then
                address_out_tdata <= std_logic_vector(descriptor_point(ADDRESS_WIDTH+1 downto 2) + descriptor_addr);
            elsif(descriptor_dec = "11") then
                address_out_tdata <= std_logic_vector(descriptor_point(ADDRESS_WIDTH+2 downto 3) + descriptor_addr);
            else
                address_out_tdata <= std_logic_vector(descriptor_point(ADDRESS_WIDTH-1 downto 0) + descriptor_addr);
            end if;

            -- Set the valid outputs depending on run state and decimation mode
            valid_int <= running_int and decimation_valid;
            
            -- Set the last outputs depending on run state, decimation mode, and descriptor done
            last_int  <= descriptor_done and running_int and decimation_valid;
        end if;
    end process output_proc;

    data_out_tvalid    <= valid_int;
    data_out_tlast     <= last_int;
    address_out_tvalid <= valid_int;
    address_out_tlast  <= last_int;

    data_address_invalid <= not valid_int;
    
end rtl;
