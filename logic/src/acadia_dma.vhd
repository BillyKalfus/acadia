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

library UNISIM;
use UNISIM.vcomponents.all;

entity acadia_dma is
    generic (
        DESCRIPTOR_MEM_ADDR_WIDTH : natural := 16;
        DESCRIPTOR_FIFO_DEPTH : natural := 16;
    );
    port (
        clk                 : in  std_logic;
        rst                 : in  std_logic;
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
        mem_control_clk     : out std_logic;
        
        -- Descriptor FIFO interface
        descriptor_address_fifo_in           : in  std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
        descriptor_address_fifo_wr           : in  std_logic;
        descriptor_address_fifo_almost_empty : out std_logic;
        descriptor_address_fifo_empty : out std_logic;
        
        running        : out std_logic
    );
end acadia_dma;

architecture rtl of acadia_dma is 

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
    ATTRIBUTE X_INTERFACE_INFO of mem_control_clk     : SIGNAL is "xilinx.com:interface:bram:1.0 MEM_CONTROL CLK";
    ATTRIBUTE X_INTERFACE_MODE of mem_control_addr    : SIGNAL is "Master";

    -- Run state
    signal running_int                              : std_logic;

    -- Descriptor address FIFO
    signal descriptor_address_fifo_empty_int    : std_logic;
    signal descriptor_address_fifo_rd           : std_logic;
    signal descriptor_load                      : std_logic;
                                                
    -- Descriptor fields
    signal desc_lm1                             : std_logic_vector(15 downto 0);
    signal desc_addr                            : std_logic_vector(15 downto 0);
    signal desc_dec                             : std_logic_vector(7 downto 0);
    signal desc_hold                            : std_logic;
    
    -- Progress counters
    signal dec_cycle                            : unsigned(7 downto 0);
    signal descriptor_point                     : unsigned(15 downto 0);
    
    -- Combinational progress flags
    signal point_first_dec_cycle                : std_logic;
    signal point_last_dec_cycle                 : std_logic;
    signal descriptor_first_point               : std_logic;
    signal descriptor_last_point                : std_logic;
    
    signal descriptor_first_cycle               : std_logic;
    signal descriptor_last_cycle                : std_logic;
         
begin    
    
    -- Control the interface to descriptor memory
    descriptor_mem_clk  <= clk;

    -- Establish some progress flags
    point_first_dec_cycle  <= '1' when to_integer(dec_cycle) = 0        else '0';
    point_last_dec_cycle   <= '1' when dec_cycle = desc_dec             else '0';
    descriptor_first_point <= '1' when to_integer(descriptor_point) = 0 else '0';
    descriptor_last_point  <= '1' when descriptor_point = desc_lm1      else '0';
    
    descriptor_first_cycle <= descriptor_first_point and point_first_dec_cycle;
    descriptor_last_cycle <= descriptor_last_point and point_last_dec_cycle;

    descriptor_address_fifo_inst : xpm_fifo_sync
        generic map (
            DOUT_RESET_VALUE    => "0",      -- String
            ECC_MODE            => "no_ecc", -- String
            FIFO_MEMORY_TYPE    => "auto",   -- String
            FIFO_READ_LATENCY   => 0,        -- DECIMAL
            FIFO_WRITE_DEPTH    => DESCRIPTOR_FIFO_DEPTH,       -- DECIMAL
            FULL_RESET_VALUE    => 0,        -- DECIMAL
            PROG_EMPTY_THRESH   => 10,       -- DECIMAL
            PROG_FULL_THRESH    => 10,       -- DECIMAL
            RD_DATA_COUNT_WIDTH => 1,        -- DECIMAL
            READ_DATA_WIDTH     => 16,       -- DECIMAL
            READ_MODE           => "fwft",   -- String
            SIM_ASSERT_CHK      => 0,        -- DECIMAL; 0=disable simulation messages, 1=enable simulation messages
            USE_ADV_FEATURES    => "0800",   -- String -- Enable almost_empty, and nothing else. This is bit 11
            WAKEUP_TIME         => 0,        -- DECIMAL
            WRITE_DATA_WIDTH    => 16,       -- DECIMAL
            WR_DATA_COUNT_WIDTH => 1         -- DECIMAL
        )
        port map (
            wr_clk => clk, 
            rst    => rst,
            
            -- The write interface is exposed to the module's port map
            din   => descriptor_address_fifo_in,
            wr_en => descriptor_address_fifo_wr,
            
            -- The output connects directly to the descriptor memory
            dout  => descriptor_mem_addr,
            rd_en => descriptor_address_fifo_rd, 
            
            -- We'll use the empty signal to determine when to stop,
            -- but we don't need the full signal because writing to 
            -- a full FIFO is nondestructive
            empty        => descriptor_address_fifo_empty_int, 
            almost_empty => descriptor_address_fifo_almost_empty,
            full         => open,                  
            
            -- These ports are unused for our purposes
            rd_rst_busy => open,     
            wr_rst_busy => open,
            injectdbiterr => '0',
            injectsbiterr => '0', 
            sleep => '0',
        );
        
    -- Because the FIFO is FWFT, we can pulse the FIFO read enable
    -- once we've already started the descriptor
    descriptor_address_fifo_rd_en <= running_int and descriptor_first_cycle;
    descriptor_address_fifo_empty <= descriptor_address_fifo_empty_int;
                                
    running_int_proc: process(clk) begin
        if rising_edge(clk) then
            running_int_d <= running_int;
            if(rst = '1' or (descriptor_last_cycle and descriptor_address_fifo_empty_int) = '1') then
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
            if((trigger or descriptor_last_cycle) = '1') then
                desc_lm1  <= descriptor_mem_dout(15 downto 0);
                desc_addr <= descriptor_mem_dout(31 downto 16);
                desc_dec  <= descriptor_mem_dout(39 downto 32);
                desc_hold <= descriptor_mem_dout(40);
            end if;
        end if;
    end process descriptor_field_load_proc;
    
    -- Count cycles for decimation
    dec_count_proc: process(clk) begin
        if rising_edge(clk) then
            if(point_last_dec_cycle = '1' or trigger = '1') then
                dec_cycle <= (others => '0');
            else
                dec_cycle <= dec_cycle + 1;
            end if;
        end if;
    end process dec_count_proc;
        
    -- Progress through the descriptor one point at a time
    descriptor_point_proc: process(clk) begin
        if rising_edge(clk) then
            if(trigger = '1' or (point_last_dec_cycle and descriptor_last_point) = '1') then
                descriptor_point <= (others => '0');
            elsif(point_last_dec_cycle = '1') then
                descriptor_point <= descriptor_point + 1;
            end if;
        end if;
    end process descriptor_point_proc;
    
    -- Drive the output interfaces
    mem_control_clk  <= clk;
      
    output_proc: process(clk) begin
        if rising_edge(clk) then
            -- Stream the address out of the AXI-stream port
            -- Data present on the stream is considered valid when its NOT during decimation
            addr_tvalid <= running_int and (not trigger) and point_first_dec_cycle;
            addr_tdata  <= std_logic_vector(descriptor_point + unsigned(desc_addr));
            addr_tlast  <= descriptor_last_point and point_first_dec_cycle;
            
            -- Control the memory master port
            -- Memory will be accessed at the beginning of decimation, after which the enable
            -- pin will be deasserted
            -- The memory interface will be reset either when de-triggered, or when the sequence is complete 
            mem_control_addr <= std_logic_vector(descriptor_point + unsigned(desc_addr));
            mem_control_rst  <= (not running_int) or trigger;
        end if;
    end process output_proc;
    
end rtl;
