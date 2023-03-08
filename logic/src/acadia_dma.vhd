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
        DESCRIPTOR_MEM_ADDR_WIDTH : natural := 16;
        DESCRIPTOR_FIFO_DEPTH : natural := 16
    );
    port (
        clk                 : in  std_logic;
        nrst                : in  std_logic;
        trigger             : in  std_logic;
        
        -- Descriptor memory interface
        descriptor_mem_dout : in  std_logic_vector(63 downto 0);
        descriptor_mem_addr : out std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
        descriptor_mem_clk  : out std_logic;
        
        -- AXI-Stream interface
        addr_tdata          : out std_logic_vector(15 downto 0);
        addr_tlast          : out std_logic;
        addr_tvalid         : out std_logic;
                
        -- Memory control interface
        mem_control_addr    : out std_logic_vector(15 downto 0);
        mem_control_rst     : out std_logic;
        mem_control_en      : out std_logic;
        mem_control_clk     : out std_logic;
        
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
    
    ATTRIBUTE X_INTERFACE_INFO of clk : SIGNAL is "xilinx.com:signal:clock:1.0 clk clk";
    ATTRIBUTE X_INTERFACE_PARAMETER of clk : SIGNAL is "ASSOCIATED_BUSIF ADDR";
    
    ATTRIBUTE X_INTERFACE_INFO of descriptor_mem_dout : SIGNAL is "xilinx.com:interface:bram:1.0 DESCRIPTOR_MEM DOUT";
    ATTRIBUTE X_INTERFACE_INFO of descriptor_mem_addr : SIGNAL is "xilinx.com:interface:bram:1.0 DESCRIPTOR_MEM ADDR";
    ATTRIBUTE X_INTERFACE_INFO of descriptor_mem_clk  : SIGNAL is "xilinx.com:interface:bram:1.0 DESCRIPTOR_MEM CLK";
    ATTRIBUTE X_INTERFACE_MODE of descriptor_mem_dout : SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of addr_tdata          : SIGNAL is "xilinx.com:interface:axis:1.0 ADDR TDATA";
    ATTRIBUTE X_INTERFACE_INFO of addr_tlast          : SIGNAL is "xilinx.com:interface:axis:1.0 ADDR TLAST";
    ATTRIBUTE X_INTERFACE_INFO of addr_tvalid         : SIGNAL is "xilinx.com:interface:axis:1.0 ADDR TVALID";
    ATTRIBUTE X_INTERFACE_MODE of addr_tdata          : SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of mem_control_addr    : SIGNAL is "xilinx.com:interface:bram:1.0 MEM_CONTROL ADDR";
    ATTRIBUTE X_INTERFACE_INFO of mem_control_rst     : SIGNAL is "xilinx.com:interface:bram:1.0 MEM_CONTROL RST";
    ATTRIBUTE X_INTERFACE_INFO of mem_control_en      : SIGNAL is "xilinx.com:interface:bram:1.0 MEM_CONTROL EN";
    ATTRIBUTE X_INTERFACE_INFO of mem_control_clk     : SIGNAL is "xilinx.com:interface:bram:1.0 MEM_CONTROL CLK";
    ATTRIBUTE X_INTERFACE_MODE of mem_control_addr    : SIGNAL is "Master";

    -- Inverted reset
    signal rst              : std_logic;

    -- Run state
    signal running_int      : std_logic;

    -- Descriptor address FIFO
    signal fifo_empty_int   : std_logic;
    signal fifo_rd_en_int   : std_logic;
                                                
    -- Descriptor fields
    signal descriptor_lm1   : unsigned(31 downto 0);
    signal descriptor_addr  : unsigned(15 downto 0);
    signal descriptor_dec   : unsigned(7 downto 0);
    signal descriptor_blank : std_logic;
    signal descriptor_fixed : std_logic;
    
    -- Progress counters
    signal decimation_count : unsigned(7 downto 0);
    signal descriptor_point : unsigned(15 downto 0);
    
    -- Combinational progress flags
    signal descriptor_done  : std_logic;
    signal decimation_done  : std_logic;
    
begin    
    
    -- Create an active-high reset for the fifo
    rst <= not nrst;
    
    -- Control the interface to descriptor memory
    descriptor_mem_clk  <= clk;
    
    descriptor_address_fifo_inst: entity work.acadia_dma_fifo
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
    fifo_rd_en_int <= trigger or descriptor_done;
    descriptor_address_fifo_empty <= fifo_empty_int;

    -- Establish some progress flags
    -- These should ideally be mapped into the DSP slice pattern detector
    decimation_done <= '1' when decimation_count = descriptor_dec else '0';
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
            if(trigger = '1' or descriptor_done = '1') then
                descriptor_lm1   <= unsigned(descriptor_mem_dout(31 downto 0));
                descriptor_addr  <= unsigned(descriptor_mem_dout(47 downto 32));
                descriptor_dec   <= unsigned(descriptor_mem_dout(55 downto 48));
                descriptor_blank <= descriptor_mem_dout(56);
                descriptor_fixed <= descriptor_mem_dout(57);
            end if;
        end if;
    end process descriptor_field_load_proc;
            
    -- Progress through the descriptor one point at a time
    descriptor_point_proc: process(clk) begin
        if rising_edge(clk) then
            if(trigger = '1' or descriptor_done = '1') then
                descriptor_point <= (others => '0');
            else
                descriptor_point <= descriptor_point + 1;
            end if;
        end if;
    end process descriptor_point_proc;
    
    -- Count cycles for decimation
    decimation_count_proc: process(clk) begin
        if rising_edge(clk) then
            if(trigger = '1' or decimation_done = '1') then
                decimation_count <= (others => '0');
            else
                decimation_count <= decimation_count + 1;
            end if;
        end if;
    end process decimation_count_proc;
        
    -- Drive the output interfaces
    mem_control_clk  <= clk;
      
    output_proc: process(clk) begin
        if rising_edge(clk) then
            -- Stream the address out of the AXI-stream port
            -- Data present on the stream is considered valid when its NOT during decimation
            addr_tvalid <= running_int and decimation_done;
            addr_tlast  <= descriptor_done;
            
            if(descriptor_fixed = '1') then
                addr_tdata <= std_logic_vector(descriptor_addr);
            else
                addr_tdata <= std_logic_vector(descriptor_point + descriptor_addr);
            end if;
            
            -- Control the memory master port
            mem_control_rst <= not running_int or descriptor_blank;
            mem_control_en  <= '1'; -- we'll keep the memory always enabled and use reset to mute the output
        
            if(descriptor_fixed = '1') then
                mem_control_addr <= std_logic_vector(descriptor_addr);
            else
                mem_control_addr <= std_logic_vector(descriptor_point + descriptor_addr);
            end if;
            
        end if;
    end process output_proc;
    
end rtl;
