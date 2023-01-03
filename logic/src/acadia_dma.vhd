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

entity dma is
    generic (
        DESCRIPTOR_MEM_ADDR_WIDTH : natural := 16
    );
    port (
        clk                 : in  std_logic;
        
        -- Reset control
        rst                 : in  std_logic;
        rst_en              : in  std_logic;
        
        -- Trigger control
        trig                : in  std_logic;
        trig_en             : in  std_logic;
        
        -- Descriptor memory interface
        descriptor_mem_dout : in  std_logic_vector(63 downto 0);
        descriptor_mem_addr : out std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
        descriptor_mem_clk  : out std_logic;
        
        -- AXI-Stream interface
        addr_tdata          : out std_logic_vector(15 downto 0);
        addr_tdest          : out std_logic_vector(3 downto 0);
        addr_tuser          : out std_logic_vector(15 downto 0);
        addr_tlast          : out std_logic;
        addr_tvalid         : out std_logic;
                
        -- Memory control interface
        mem_control_addr    : out std_logic_vector(15 downto 0);
        mem_control_rst     : out std_logic;
        mem_control_clk     : out std_logic;
                
        seq_start           : in  std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
        seq_end             : in  std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
        seq_continue        : in  std_logic;
        
        descriptor_done     : out std_logic;
        sequence_done       : out std_logic
    );
end dma;

architecture rtl of dma is 

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
    ATTRIBUTE X_INTERFACE_INFO of addr_tdest          : SIGNAL is "xilinx.com:interface:axis:1.0 ADDR TDEST";
    ATTRIBUTE X_INTERFACE_INFO of addr_tuser          : SIGNAL is "xilinx.com:interface:axis:1.0 ADDR TUSER";
    ATTRIBUTE X_INTERFACE_INFO of addr_tvalid         : SIGNAL is "xilinx.com:interface:axis:1.0 ADDR TVALID";
    ATTRIBUTE X_INTERFACE_MODE of addr_tdata          : SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of mem_control_addr    : SIGNAL is "xilinx.com:interface:bram:1.0 MEM_CONTROL ADDR";
    ATTRIBUTE X_INTERFACE_INFO of mem_control_rst     : SIGNAL is "xilinx.com:interface:bram:1.0 MEM_CONTROL RST";
    ATTRIBUTE X_INTERFACE_INFO of mem_control_clk     : SIGNAL is "xilinx.com:interface:bram:1.0 MEM_CONTROL CLK";
    ATTRIBUTE X_INTERFACE_MODE of mem_control_addr    : SIGNAL is "Master";

    -- Run state
    signal running                              : std_logic;

    -- Descriptor fields
    signal desc_lm1                             : std_logic_vector(15 downto 0);
    signal desc_addr                            : std_logic_vector(15 downto 0);
    signal desc_dec                             : std_logic_vector(7 downto 0);
    signal desc_hold                            : std_logic;
    signal desc_dest                            : std_logic_vector(3 downto 0);
    signal desc_user                            : std_logic_vector(15 downto 0);

    -- Register settings
    signal seq_end_int                          : std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
    signal seq_continue_int                     : std_logic;
    
    -- Progress counters
    signal dec_cycle                            : std_logic_vector(7 downto 0);
    signal descriptor_point                     : std_logic_vector(15 downto 0);
    signal descriptor_addr                      : std_logic_vector(DESCRIPTOR_MEM_ADDR_WIDTH-1 downto 0);
    
    -- Signals indicating that settings loading is in progress
    signal seq_load                             : std_logic;
    signal desc_load                            : std_logic;
    
    -- Combinational progress flags
    signal point_first_dec_cycle                : std_logic;
    signal point_last_dec_cycle                 : std_logic;
    signal descriptor_first_point               : std_logic;
    signal descriptor_last_point                : std_logic;
    signal sequence_last_descriptor             : std_logic;
    signal sequence_done_int                    : std_logic;
    signal sequence_last_dec_cycle              : std_logic;
    
    signal before_descriptor_first_cycle        : std_logic;
    signal sequence_last_descriptor_in_progress : std_logic;
         
begin    

    -- Establish some progress flags
    -- Note that these signals are defined combinationally and depend
    -- on the instantaneous value of a memory output,
    -- so for reliable timing they should only be evaluated synchronously
    point_first_dec_cycle    <= '1' when to_integer(unsigned(dec_cycle)) = 0 and desc_load = '0'        else '0';
    point_last_dec_cycle     <= '1' when dec_cycle = desc_dec                                           else '0';
    descriptor_first_point   <= '1' when to_integer(unsigned(descriptor_point)) = 0 and desc_load = '0' else '0';
    descriptor_last_point    <= '1' when descriptor_point = desc_lm1                                    else '0';
    sequence_last_descriptor <= '1' when descriptor_addr = seq_end_int                                  else '0';
    
    before_descriptor_first_cycle <= desc_load or (descriptor_last_point and point_last_dec_cycle);
    sequence_last_dec_cycle  <= sequence_last_descriptor_in_progress and descriptor_last_point and point_last_dec_cycle;

    running_proc: process(clk) begin
        if rising_edge(clk) then
            if((rst = '1' and rst_en = '1') or (sequence_last_dec_cycle = '1' and seq_continue_int = '0')) then
                running <= '0';
            elsif(trig = '1' and trig_en = '1') then
                running <= '1';
            end if;
        end if;
    end process running_proc;

    -- Manage when sequence settings are loaded
    -- This will also automatically clear sequence_done_int if we are continuing
    -- since sequence_done_int is reset when seq_load is set
    seq_load_proc: process(clk) begin
        if rising_edge(clk) then
            if(running = '0') then
                seq_load <= '1';
            else
                seq_load <= seq_continue_int and sequence_last_dec_cycle;
            end if;
        end if;
    end process seq_load_proc;
    
    -- Load sequence settings from external input
    sequence_settings_load_proc: process(clk) begin
        if rising_edge(clk) then
            if(seq_load = '1') then
                seq_end_int      <= seq_end;
                seq_continue_int <= seq_continue;
                desc_load        <= '1';
            else
                desc_load <= '0';
            end if;    
        end if;
    end process sequence_settings_load_proc;
            
    -- Assign signals from descriptor fields
    descriptor_field_load_proc: process(clk) begin
        if rising_edge(clk) then
            if(desc_load = '1' or (descriptor_last_point and point_last_dec_cycle) = '1') then
                desc_lm1  <= descriptor_mem_dout(15 downto 0);
                desc_addr <= descriptor_mem_dout(31 downto 16);
                desc_dec  <= descriptor_mem_dout(39 downto 32);
                desc_hold <= descriptor_mem_dout(40);
                desc_dest <= descriptor_mem_dout(47 downto 44);
                desc_user <= descriptor_mem_dout(63 downto 48);
            end if;
        end if;
    end process descriptor_field_load_proc;
    
    -- Count cycles for decimation
    dec_count_proc: process(clk) begin
        if rising_edge(clk) then
            if((point_last_dec_cycle or seq_load or desc_load) = '1') then
                dec_cycle <= (others => '0');
            else
                dec_cycle <= std_logic_vector(unsigned(dec_cycle) + 1);
            end if;
        end if;
    end process dec_count_proc;
        
    -- Progress through the descriptor one point at a time
    descriptor_point_proc: process(clk) begin
        if rising_edge(clk) then
            if(desc_load = '1') then
                descriptor_point <= (others => '0');
            elsif(point_last_dec_cycle = '1') then
                if(descriptor_last_point = '1') then
                    descriptor_point <= (others => '0');
                else
                    descriptor_point <= std_logic_vector(unsigned(descriptor_point)+1);
                end if;
            end if;
        end if;
    end process descriptor_point_proc;
    
    -- Since new descriptor fields are loaded at the last cycle of the current descriptor
    -- and since descriptors must be at least 2 cycles long,
    -- we can load in the next address to the descriptor memory at the first cycle of the .
    descriptor_addr_proc: process(clk) begin
        if rising_edge(clk) then
            if(seq_load = '1') then
                descriptor_addr <= seq_start;
            elsif((descriptor_first_point and point_first_dec_cycle) = '1') then
                descriptor_addr <= std_logic_vector(unsigned(descriptor_addr)+1);
            end if;
        end if;
    end process descriptor_addr_proc;
    
    -- Detect when we're in the last descriptor so that we can properly signal when we're done
    -- The following elsif condition will be satisfied when in the last cycle of 
    -- the second-to-last descriptor because the descriptor address will be loaded one cycle early.
    -- In case the sequence is one descriptor long, also use desc_load.
    -- Therefore sequence_last_descriptor_in_progress will go high
    -- as the first cycle of the last descriptor starts
    sequence_last_descriptor_in_progress_proc: process(clk) begin
        if rising_edge(clk) then
            if(seq_load = '1') then
                sequence_last_descriptor_in_progress <= '0';
            elsif((sequence_last_descriptor and before_descriptor_first_cycle) = '1') then
                sequence_last_descriptor_in_progress <= '1';
            end if;
        end if;
    end process sequence_last_descriptor_in_progress_proc;
    
    -- Latch an internal signal when we've completed the sequence
    -- Since all descriptors must be a minimum of 2 cycles long and sequence_last_descriptor_in_progress
    -- will be high during the first cycle of the last descriptor, we can just check sequence_last_dec_cycle
    -- (which depends on sequence_last_descriptor_in_progress)
    sequence_done_int_proc: process(clk) begin
        if rising_edge(clk) then
            if(seq_load = '1') then
                sequence_done_int <= '0';
            elsif(sequence_last_dec_cycle = '1') then
                sequence_done_int <= '1';
            end if;
        end if;
    end process sequence_done_int_proc;  
    
    -- Expose this signal to other modules
    sequence_done <= sequence_done_int;  
    
    -- Control the interface to descriptor memory
    descriptor_mem_addr <= descriptor_addr;
    descriptor_mem_clk  <= clk;
    
    -- Drive the output interfaces
    mem_control_clk  <= clk;
      
    output_proc: process(clk) begin
        if rising_edge(clk) then
            -- Stream the address out of the AXI-stream port
            -- Data present on the stream is considered valid when its NOT during decimation
            addr_tvalid <= (not sequence_done_int) and (not seq_load) and point_first_dec_cycle;
            addr_tdata  <= std_logic_vector(unsigned(descriptor_point) + unsigned(desc_addr));
            addr_tlast  <= descriptor_last_point and point_first_dec_cycle;
            addr_tdest  <= desc_dest;
            addr_tuser  <= desc_user;
            
            -- Control the memory master port
            -- Memory will be accessed at the beginning of decimation, after which the enable
            -- pin will be deasserted
            -- The memory interface will be reset either when de-triggered, or when the sequence is complete 
            mem_control_addr <= std_logic_vector(unsigned(descriptor_point) + unsigned(desc_addr));
            mem_control_rst  <= seq_load or sequence_done_int;
            
            -- Expose some progress signals
            descriptor_done <= descriptor_last_point and point_last_dec_cycle and (not seq_load) and (not desc_load);
        end if;
    end process output_proc;
    
end rtl;
