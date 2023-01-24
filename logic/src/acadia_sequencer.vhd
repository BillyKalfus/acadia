----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 09/19/2022 12:23:09 PM
-- Design Name: acadia
-- Module Name: acadia_sequencer - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 
-- Description: The Acadia sequencer microarchitecture.
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

library UNISIM;
use UNISIM.vcomponents.all;

library work;
use work.all;

entity acadia_sequencer is
    generic (
        STACK_SIZE      : natural := 32;
        LOG2_STACK_SIZE : natural := 5
    );
    port
    (
        clk                  : in  std_logic;
        run                  : in  std_logic;        
        nrst                 : in  std_logic;
        
        -- Instruction memory interface(s)
        instruction_mem_dout : in  std_logic_vector(95 downto 0);
        instruction_mem_addr : out std_logic_vector(15 downto 0);
        instruction_mem_rst  : out std_logic;
        instruction_mem_en   : out std_logic;
        instruction_mem_clk  : out std_logic;
        
        -- Bus interface
        mem_bus_mosi         : out std_logic_vector(31 downto 0);
        mem_bus_miso         : in  std_logic_vector(31 downto 0);
        mem_bus_addr         : out std_logic_vector(31 downto 0);
        mem_bus_wr           : out std_logic;
        mem_bus_en           : out std_logic;
        mem_bus_clk          : out std_logic;
        
        -- Hedgehog input ports
        hedgehog_flags       : in  std_logic_vector(21 downto 0)
    );
    
end acadia_sequencer;

architecture rtl of acadia_sequencer is

    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_dout : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem DOUT";
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_addr : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem ADDR";
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_rst  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem RST";
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_en   : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem EN";
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_clk  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem CLK";
    ATTRIBUTE X_INTERFACE_MODE of instruction_mem_dout : SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_mosi         : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_miso         : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_wr           : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_addr         : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_en           : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus EN";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_clk          : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus CLK";
    ATTRIBUTE X_INTERFACE_MODE of mem_bus_mosi         : SIGNAL is "Master";

    -- Some constants that will encode source and destination IDs
    constant SRC_REG       : natural := 0;
    constant SRC_PC        : natural := 8;
    constant SRC_IMM       : natural := 9;
    constant SRC_TEST      : natural := 10;
    constant SRC_FLAGS     : natural := 11;
    constant SRC_STACK     : natural := 12;
    constant SRC_BUS_ADDR  : natural := 13;
    constant SRC_BUS_DATA  : natural := 14;
    constant SRC_BUS_PEEK  : natural := 15;
    constant SRC_DSP_P_LO  : natural := 16;
    constant SRC_DSP_P_HI  : natural := 20;
    
    constant DEST_REG      : natural := 0;
    constant DEST_PC       : natural := 8;
    constant DEST_HOLD     : natural := 9;
    constant DEST_MASK     : natural := 10;
    constant DEST_FLAGS    : natural := 11;
    constant DEST_STACK    : natural := 12;
    constant DEST_BUS_ADDR : natural := 13;
    constant DEST_BUS_DATA : natural := 14;
    constant DEST_DSP_AB   : natural := 16;
    constant DEST_DSP_C_LO : natural := 20;
    constant DEST_DSP_C_HI : natural := 24;
    constant DEST_DSP_CFG  : natural := 28;
    constant DEST_DSP_P_EN : natural := 29;

    -- General type for array of words
    type word_array is array (natural range <>) of std_logic_vector(31 downto 0);
                              
    -- General type for 48-bit DSP interface signals
    type dsp_array is array (natural range <>) of std_logic_vector(47 downto 0);

    -- General-purpose registers
    signal r : word_array(0 to 7);
    
    -- bus addressing
    signal bus_addr_reg             : std_logic_vector(31 downto 0);
    signal bus_data_reg             : std_logic_vector(31 downto 0);
    signal bus_wr_reg               : std_logic;
    
    -- Program counter
    signal pc                       : std_logic_vector(15 downto 0);
    signal pc_jump_address          : std_logic_vector(15 downto 0);
    
    -- System flags
    signal flags                    : std_logic_vector(31 downto 0);
    signal flags_set                : std_logic_vector(31 downto 0);
    
    -- Data sources
    signal src1                     : std_logic_vector(31 downto 0);
    signal src2                     : std_logic_vector(31 downto 0);
    
    -- Decoded instruction fields
    signal src1_dec                 : std_logic_vector(31 downto 0);
    signal src2_dec                 : std_logic_vector(31 downto 0);
    signal dest1_dec                : std_logic_vector(31 downto 0);
    signal dest2_dec                : std_logic_vector(31 downto 0);
    signal dest_dec                 : std_logic_vector(31 downto 0);
    signal dest1_dec_en             : std_logic;
    signal dest2_dec_en             : std_logic;
    
    -- Conditionality testing signals
    signal test_val                 : std_logic_vector(31 downto 0);
    signal test_val_d               : std_logic_vector(31 downto 0);
    signal mask                     : std_logic_vector(31 downto 0);
    signal cond_val                 : std_logic_vector(31 downto 0);
    signal cond_satisfied           : std_logic;
    
    -- Instruction signals
    signal instruction              : std_logic_vector(95 downto 0);
    signal instruction_rst          : std_logic;
    signal instruction_en           : std_logic;
    signal instruction_en_d         : std_logic;
    
    signal instr_src1               : std_logic_vector(4 downto 0);
    signal instr_src2               : std_logic_vector(4 downto 0);
    signal instr_dest1              : std_logic_vector(4 downto 0);
    signal instr_dest2              : std_logic_vector(4 downto 0);
    signal instr_imm1               : std_logic_vector(31 downto 0);
    signal instr_imm2               : std_logic_vector(31 downto 0);
    signal instr_dsp_p_en           : std_logic_vector(3 downto 0);
    signal instr_push_return        : std_logic;
    signal instr_op_sel             : std_logic_vector(2 downto 0);
        
    -- Stack                          
    signal stack                    : word_array(0 to STACK_SIZE-1);
    signal stack_wr_addr            : std_logic_vector(LOG2_STACK_SIZE-1 downto 0);
    signal stack_rd_addr            : std_logic_vector(LOG2_STACK_SIZE-1 downto 0);
    signal stack_pop                : std_logic;
    signal stack_push               : std_logic;
    signal stack_overflow           : std_logic;
    signal stack_underflow          : std_logic;
                              
    -- DSP slice signals and corresponding clock enable pins
    signal dsp_ab                   : dsp_array(0 to 3);
    signal dsp_ab_en                : std_logic_vector(3 downto 0);
    signal dsp_c                    : dsp_array(0 to 3);
    signal dsp_c_lo_src             : word_array(0 to 3);
    signal dsp_c_lo_wr              : std_logic_vector(3 downto 0);
    signal dsp_c_hi_src             : word_array(0 to 3);
    signal dsp_c_hi_wr              : std_logic_vector(3 downto 0);
    signal dsp_c_en                 : std_logic_vector(3 downto 0);
    signal dsp_p                    : dsp_array(0 to 3);
    signal dsp_p_en                 : std_logic_vector(3 downto 0);
    signal dsp_p_en_reg             : std_logic_vector(3 downto 0);                                 
    -- DSP pattern detector signals
    signal dsp_patterndetect        : std_logic_vector(3 downto 0);
    signal dsp_patternbdetect       : std_logic_vector(3 downto 0);
                              
    -- DSP cascade
    signal dsp_pcout                : dsp_array(0 to 3);
    signal dsp_pcin                 : dsp_array(0 to 3);
                              
    -- DSP configuration signals and reset pins
    signal dsp_cfg                  : std_logic;
    signal dsp_cfg_sel              : std_logic_vector(3 downto 0);
    signal dsp_cfg_data             : std_logic_vector(31 downto 0);
    signal dsp_alumode              : std_logic_vector(3 downto 0);
    signal dsp_opmode               : std_logic_vector(8 downto 0);
    signal dsp_rst_ab               : std_logic_vector(3 downto 0);
    signal dsp_rst_c                : std_logic_vector(3 downto 0); 
    signal dsp_rst_p                : std_logic_vector(3 downto 0);
                              
begin
                      
    -- Instruction memory interface and loading
    instruction_en   <= not (dest1_dec(DEST_HOLD) or dest2_dec(DEST_HOLD));
        
    -- We have to reset the instruction memory output any time we jump or come out of a hold
    instruction_rst  <= dest1_dec(DEST_PC) or 
                        dest2_dec(DEST_PC) or 
                        (instruction_en and not instruction_en_d) or 
                        (not run);
    
    instruction_mem_addr <= pc;
    instruction_mem_clk  <= clk;
    instruction_mem_en   <= '1'; -- We should be able to keep the actual memory always enabled as long as we reset the pipeline stages
    instruction_mem_rst  <= instruction_rst;
    
    instruction_en_d_proc: process(clk) begin
        if rising_edge(clk) then
            instruction_en_d <= instruction_en;
        end if;
    end process instruction_en_d_proc;
    
    instruction_proc: process(clk) begin
        if rising_edge(clk) then
            if(instruction_rst = '1') then
                instruction <= (others => '0');
            elsif(instruction_en = '1') then
                instruction <= instruction_mem_dout;
            end if;
        end if;
    end process instruction_proc;
                                                  
    -- Instruction decoding
    instr_push_return  <= instruction(94);
    instr_src1     <= instruction(92 downto 88);
    instr_src2     <= instruction(86 downto 82);
    instr_dest1    <= instruction(81 downto 77);
    instr_dest2    <= instruction(76 downto 72);
    instr_dsp_p_en <= instruction(67 downto 64);
    instr_imm1     <= instruction(63 downto 32);
    instr_imm2     <= instruction(31 downto 0);
    instr_op_sel   <= instruction(74 downto 72);
    
    -- Enable or disable the destination decoders depending on the instruction opcode and the condition satisfaction
    dest1_dec_en <= (cond_satisfied and instruction(95)) or (not instruction(95));
    dest2_dec_en <= not instruction(95);
    
    -- Implement the destination and source decoders
    decoder_dest1_inst: entity work.acadia_decoder 
                            generic map(INPUTS => 5, OUTPUTS => 32)
                            port map(en => dest1_dec_en, din => instr_dest1, dout => dest1_dec);
    decoder_dest2_inst: entity work.acadia_decoder 
                            generic map(INPUTS => 5, OUTPUTS => 32)
                            port map(en => dest2_dec_en, din => instr_dest2, dout => dest2_dec);
    
    dest_dec <= dest1_dec or dest2_dec;
                            
    decoder_src1_inst: entity work.acadia_decoder 
                            generic map(INPUTS => 5, OUTPUTS => 32)
                            port map(en => '1', din => instr_src1, dout => src1_dec);
                            
    decoder_src2_inst: entity work.acadia_decoder 
                            generic map(INPUTS => 5, OUTPUTS => 32)
                            port map(en => '1', din => instr_src2, dout => src2_dec);
                            
    -- Multiplex the input source according to the instruction field
    src1 <= r(0)                                       when to_integer(unsigned(instr_src1)) = SRC_REG+0      else
            r(1)                                       when to_integer(unsigned(instr_src1)) = SRC_REG+1      else
            r(2)                                       when to_integer(unsigned(instr_src1)) = SRC_REG+2      else
            r(3)                                       when to_integer(unsigned(instr_src1)) = SRC_REG+3      else
            r(4)                                       when to_integer(unsigned(instr_src1)) = SRC_REG+4      else
            r(5)                                       when to_integer(unsigned(instr_src1)) = SRC_REG+5      else
            r(6)                                       when to_integer(unsigned(instr_src1)) = SRC_REG+6      else
            r(7)                                       when to_integer(unsigned(instr_src1)) = SRC_REG+7      else
            x"0000" & pc                               when to_integer(unsigned(instr_src1)) = SRC_PC         else
            instr_imm1                                 when to_integer(unsigned(instr_src1)) = SRC_IMM        else
            test_val_d                                 when to_integer(unsigned(instr_src1)) = SRC_TEST       else
            flags                                      when to_integer(unsigned(instr_src1)) = SRC_FLAGS      else
            stack(to_integer(unsigned(stack_rd_addr))) when to_integer(unsigned(instr_src1)) = SRC_STACK      else
            bus_addr_reg                               when to_integer(unsigned(instr_src1)) = SRC_BUS_ADDR   else
            mem_bus_miso                               when to_integer(unsigned(instr_src1)) = SRC_BUS_DATA   else
            mem_bus_miso                               when to_integer(unsigned(instr_src1)) = SRC_BUS_PEEK   else
            dsp_p(0)(31 downto 0)                      when to_integer(unsigned(instr_src1)) = SRC_DSP_P_LO+0 else
            dsp_p(1)(31 downto 0)                      when to_integer(unsigned(instr_src1)) = SRC_DSP_P_LO+1 else
            dsp_p(2)(31 downto 0)                      when to_integer(unsigned(instr_src1)) = SRC_DSP_P_LO+2 else
            dsp_p(3)(31 downto 0)                      when to_integer(unsigned(instr_src1)) = SRC_DSP_P_LO+3 else
            dsp_p(0)(47 downto 16)                     when to_integer(unsigned(instr_src1)) = SRC_DSP_P_HI+0 else
            dsp_p(1)(47 downto 16)                     when to_integer(unsigned(instr_src1)) = SRC_DSP_P_HI+1 else
            dsp_p(2)(47 downto 16)                     when to_integer(unsigned(instr_src1)) = SRC_DSP_P_HI+2 else
            dsp_p(3)(47 downto 16)                     when to_integer(unsigned(instr_src1)) = SRC_DSP_P_HI+3 else
            (others =>'0');
            
    src2 <= r(0)                                       when to_integer(unsigned(instr_src2)) = SRC_REG+0      else
            r(1)                                       when to_integer(unsigned(instr_src2)) = SRC_REG+1      else
            r(2)                                       when to_integer(unsigned(instr_src2)) = SRC_REG+2      else
            r(3)                                       when to_integer(unsigned(instr_src2)) = SRC_REG+3      else
            r(4)                                       when to_integer(unsigned(instr_src2)) = SRC_REG+4      else
            r(5)                                       when to_integer(unsigned(instr_src2)) = SRC_REG+5      else
            r(6)                                       when to_integer(unsigned(instr_src2)) = SRC_REG+6      else
            r(7)                                       when to_integer(unsigned(instr_src2)) = SRC_REG+7      else
            x"0000" & pc                               when to_integer(unsigned(instr_src2)) = SRC_PC         else
            instr_imm2                                 when to_integer(unsigned(instr_src2)) = SRC_IMM        else
            test_val_d                                 when to_integer(unsigned(instr_src2)) = SRC_TEST       else
            flags                                      when to_integer(unsigned(instr_src2)) = SRC_FLAGS      else
            stack(to_integer(unsigned(stack_rd_addr))) when to_integer(unsigned(instr_src2)) = SRC_STACK      else
            bus_addr_reg                               when to_integer(unsigned(instr_src2)) = SRC_BUS_ADDR   else
            mem_bus_miso                               when to_integer(unsigned(instr_src2)) = SRC_BUS_DATA   else
            mem_bus_miso                               when to_integer(unsigned(instr_src2)) = SRC_BUS_PEEK   else
            dsp_p(0)(31 downto 0)                      when to_integer(unsigned(instr_src2)) = SRC_DSP_P_LO+0 else
            dsp_p(1)(31 downto 0)                      when to_integer(unsigned(instr_src2)) = SRC_DSP_P_LO+1 else
            dsp_p(2)(31 downto 0)                      when to_integer(unsigned(instr_src2)) = SRC_DSP_P_LO+2 else
            dsp_p(3)(31 downto 0)                      when to_integer(unsigned(instr_src2)) = SRC_DSP_P_LO+3 else
            dsp_p(0)(47 downto 16)                     when to_integer(unsigned(instr_src2)) = SRC_DSP_P_HI+0 else
            dsp_p(1)(47 downto 16)                     when to_integer(unsigned(instr_src2)) = SRC_DSP_P_HI+1 else
            dsp_p(2)(47 downto 16)                     when to_integer(unsigned(instr_src2)) = SRC_DSP_P_HI+2 else
            dsp_p(3)(47 downto 16)                     when to_integer(unsigned(instr_src2)) = SRC_DSP_P_HI+3 else
            (others =>'0');
            
    -- Make general-purpose registers
    reg_proc: process(clk) begin
        if(rising_edge(clk)) then        
            for i in 0 to 7 loop
                if(nrst = '0') then
                    r(i) <= (others => '0');
                elsif(dest1_dec(DEST_REG+i) = '1') then
                    r(i) <= src1;
                elsif(dest2_dec(DEST_REG+i) = '1') then
                    r(i) <= src2;
                end if;
            end loop;
        end if;
    end process reg_proc;
    
    -- Load the test value register when we are issuing a conditional operation
    test_val_proc: process(clk) begin
        if rising_edge(clk) then
            test_val_d <= test_val;
            if(nrst = '0') then
                test_val <= (others => '0');
            elsif(instruction(95) = '1') then
                test_val <= src2;
            end if;
        end if;
    end process test_val_proc;
    
    -- Manage the bus registers
    bus_regs_proc: process(clk) begin
        if(rising_edge(clk)) then
            if(nrst = '0') then
                bus_addr_reg <= (others => '0');
                bus_data_reg <= (others => '0');
                bus_wr_reg   <= '0';
            else
                if(dest1_dec(DEST_BUS_ADDR) = '1') then
                    bus_addr_reg <= src1;
                elsif(dest2_dec(DEST_BUS_ADDR) = '1') then
                    bus_addr_reg <= src2;
                end if;
                
                if(dest1_dec(DEST_BUS_DATA) = '1') then
                    bus_data_reg <= src1;
                elsif(dest2_dec(DEST_BUS_DATA) = '1') then
                    bus_data_reg <= src2;
                end if;
                
                bus_wr_reg <= dest1_dec(DEST_BUS_DATA) or dest2_dec(DEST_BUS_DATA);
            end if;
        end if;
    end process bus_regs_proc;
    
    -- Assign the bus address output
    mem_bus_addr <= bus_addr_reg; 
    mem_bus_mosi <= bus_data_reg;
    mem_bus_wr   <= bus_wr_reg;
    mem_bus_en   <= bus_wr_reg or src1_dec(14) or src2_dec(14);
    mem_bus_clk  <= clk;
    
    -- Program counter
    pc_proc: process(clk) begin
        if(rising_edge(clk)) then
            if(nrst = '0' or run = '0') then
                pc <= (others => '0');
            elsif(dest1_dec(DEST_PC) = '1' or dest1_dec(DEST_HOLD) = '1') then
                pc <= src1(15 downto 0);
            elsif(dest2_dec(DEST_PC) = '1' or dest2_dec(DEST_HOLD) = '1') then
                pc <= src2(15 downto 0);
            elsif(instruction_rst = '0') then
                pc <= std_logic_vector(unsigned(pc) + 1);
            end if;
        end if;
    end process pc_proc;
    
    -- System flags
    flags_set(3 downto 0)   <= dsp_patterndetect;
    flags_set(7 downto 4)   <= dsp_patternbdetect;
    flags_set(8)            <= stack_overflow;
    flags_set(9)            <= stack_underflow;
    flags_set(31 downto 10) <= hedgehog_flags;
    
    flags_proc: process(clk) begin
        if(rising_edge(clk)) then
            flag_loop: for i in 0 to 31 loop
                if(nrst = '0' or (dest1_dec(DEST_FLAGS) = '1' and src1(i) = '1') or (dest2_dec(DEST_FLAGS) = '1' and src2(i) = '1')) then
                    flags(i) <= '0';
                elsif(flags_set(i) = '1') then
                    flags(i) <= '1';
                end if;
            end loop flag_loop;
        end if;
    end process flags_proc;
    
    -- Process for conditional operation mask register
    mask_proc: process(clk) begin
        if(rising_edge(clk)) then
            if(nrst = '0') then
                mask <= (others => '0');
            elsif(dest1_dec(DEST_MASK) = '1') then
                mask <= src1;
            elsif(dest2_dec(DEST_MASK) = '1') then
                mask <= src2;
            end if;
        end if;
    end process mask_proc;
    
    cond_val <= src2 and mask when instr_op_sel(1 downto 0) = "00" else
                src2 xor mask when instr_op_sel(1 downto 0) = "01" else
                (not src2) or mask when instr_op_sel(1 downto 0) = "10" else
                src2;
                
    cond_satisfied <= or_reduce(cond_val) xor instr_op_sel(2);
   
    -- Implement the stack
    -- Assign some various combinational signals
    stack_pop       <= src1_dec(SRC_STACK) or src2_dec(SRC_STACK);
    stack_push      <= dest1_dec(DEST_STACK) or dest2_dec(DEST_STACK) or instr_push_return;
    stack_overflow  <= and_reduce(stack_wr_addr) and stack_push;
    stack_underflow <= (not or_reduce(stack_wr_addr)) and stack_pop;

    -- Update the stack pointers when pushed or popped (but not both!)
    stack_addr_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                stack_wr_addr <= (others => '0');
                stack_rd_addr <= (others => '1');
            elsif(stack_push = '1' and stack_pop = '0') then
                stack_wr_addr <= std_logic_vector(unsigned(stack_wr_addr) + 1);
                stack_rd_addr <= stack_wr_addr;
            elsif(stack_push = '0' and stack_pop = '1') then
                stack_wr_addr <= stack_rd_addr;
                stack_rd_addr <= std_logic_vector(unsigned(stack_rd_addr) - 1);
            end if;
        end if;
    end process stack_addr_proc;
    
    -- Control writing to the stack
    stack_wr_proc: process(clk) begin
        if rising_edge(clk) then
            if(dest1_dec(DEST_STACK) = '1') then
                stack(to_integer(unsigned(stack_wr_addr))) <= src1;
            elsif(dest2_dec(DEST_STACK) = '1') then
                stack(to_integer(unsigned(stack_wr_addr))) <= src2;
            elsif(instr_push_return = '1') then
                -- Minus 1 because we lose 2 instructions due to instruction memory latency
                stack(to_integer(unsigned(stack_wr_addr))) <= x"0000" & std_logic_vector(unsigned(pc) - 1);
            end if;
        end if;
    end process stack_wr_proc;
    
    -- DSP slices
    -- start with the P_en register
    dsp_p_en_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                dsp_p_en_reg <= (others => '0');
            elsif(dest1_dec(DEST_DSP_P_EN) = '1') then
                dsp_p_en_reg(3 downto 0) <= src1;
            elsif(dest2_dec(DEST_DSP_P_EN) = '1') then
                dsp_p_en_reg(3 downto 0) <= src2;
            end if;
        end if;
    end process dsp_p_en_proc;
                             
    -- Enable the P register if the internal register is set or if the instruction indicates it
    dsp_p_en <= dsp_p_en_reg or instr_dsp_p_en;
                             
    -- Implement the DSP configuration interface
    dsp_cfg     <= dest1_dec(DEST_DSP_CFG) or dest2_dec(DEST_DSP_CFG);
    dsp_cfg_data <= src1 when dest1_dec(DEST_DSP_CFG) = '1' else src2;
                             
    decoder_dsp_inst: entity work.acadia_decoder 
                            generic map(INPUTS => 2, OUTPUTS => 4)
                            port map(en => dsp_cfg, din => dsp_cfg_data(31 downto 30), dout => dsp_cfg_sel);
                             
    dsp_alumode <= dsp_cfg_data(3 downto 0);
    dsp_opmode  <= dsp_cfg_data(12 downto 4);  
         
    -- Generate the cascade signals
    dsp_pc_gen: for i in 0 to 2 generate
        dsp_pcin(i+1) <= dsp_pcout(i);
    end generate dsp_pc_gen;                         
    
    -- Instantiate the DSP slices
    dsp_gen: for i in 0 to 3 generate
        
        -- Gate the reset signals and carry in signals with the configuration selectors
        dsp_rst_ab(i)  <= dsp_cfg_sel(i) and dsp_cfg_data(14);
        dsp_rst_c(i)   <= dsp_cfg_sel(i) and dsp_cfg_data(15);
        dsp_rst_p(i)   <= dsp_cfg_sel(i) and dsp_cfg_data(16);
                             
                             
        -- Multiplex the A and B inputs
        dsp_ab(i) <= (src1 & X"0000") when dest1_dec(DEST_DSP_AB) = '1' else (src2 & X"0000");
        dsp_ab_en(i) <= dest1_dec(DEST_DSP_AB) or dest2_dec(DEST_DSP_AB);
                       
        -- Assign some control signals for determining when and what we're writing to the C register
        dsp_c_lo_src(i) <= src1 when dest1_dec(DEST_DSP_C_LO) = '1' else src2;
        dsp_c_hi_src(i) <= src1 when dest1_dec(DEST_DSP_C_HI) = '1' else src2;
        dsp_c_lo_wr(i)  <= dest1_dec(DEST_DSP_C_LO) or dest2_dec(DEST_DSP_C_LO);
        dsp_c_hi_wr(i)  <= dest1_dec(DEST_DSP_C_HI) or dest2_dec(DEST_DSP_C_HI);
        dsp_c_en(i)     <= dsp_c_lo_wr(i) or dsp_c_hi_wr(i);
                             
        -- Multiplex the three 16-bit sections of the C register depending on what's being written 
        dsp_c(i)(47 downto 32) <= (others => dsp_c_lo_src(i)(31)) 
                                  when dsp_c_hi_wr(i) = '0' and dsp_c_lo_wr(i) = '1' else
                                  dsp_c_hi_src(i)(31 downto 16);
                             
        dsp_c(i)(31 downto 16) <= dsp_c_lo_src(i)(31 downto 16)
                                  when dsp_c_hi_wr(i) = '0' and dsp_c_lo_wr(i) = '1' else
                                  dsp_c_hi_src(i)(15 downto 0);
                             
        dsp_c(i)(15 downto 0)  <= dsp_c_lo_src(i)(15 downto 0)
                                  when dsp_c_lo_wr(i) = '1' else
                                  (others => '0');
        
        DSP48E2_inst : DSP48E2
            generic map (
                -- Feature Control Attributes: Data Path Selection
                AMULTSEL                  => "A",             -- Selects A input to multiplier (A, AD)
                A_INPUT                   => "DIRECT",        -- Selects A input source, "DIRECT" (A port) or "CASCADE" (ACIN port)
                BMULTSEL                  => "B",             -- Selects B input to multiplier (AD, B)
                B_INPUT                   => "DIRECT",        -- Selects B input source, "DIRECT" (B port) or "CASCADE" (BCIN port)
                PREADDINSEL               => "A",             -- Selects input to pre-adder (A, B)
                RND                       => X"000000000000", -- Rounding Constant
                USE_MULT                  => "NONE",          -- Select multiplier usage (DYNAMIC, MULTIPLY, NONE)
                USE_SIMD                  => "ONE48",         -- SIMD selection (FOUR12, ONE48, TWO24)
                USE_WIDEXOR               => "FALSE",         -- Use the Wide XOR function (FALSE, TRUE)
                XORSIMD                   => "XOR24_48_96",   -- Mode of operation for the Wide XOR (XOR12, XOR24_48_96)

                -- Pattern Detector Attributes: Pattern Detection Configuration
                AUTORESET_PATDET          => "NO_RESET",      -- NO_RESET, RESET_MATCH, RESET_NOT_MATCH
                AUTORESET_PRIORITY        => "RESET",         -- Priority of AUTORESET vs. CEP (CEP, RESET).
                MASK                      => X"000000000000", -- 48-bit mask value for pattern detect (1=ignore)
                PATTERN                   => X"000000000000", -- 48-bit pattern match for pattern detect
                SEL_MASK                  => "MASK",          -- C, MASK, ROUNDING_MODE1, ROUNDING_MODE2
                SEL_PATTERN               => "PATTERN",       -- Select pattern value (C, PATTERN)
                USE_PATTERN_DETECT        => "PATDET",        -- Enable pattern detect (NO_PATDET, PATDET)
                
                -- Programmable Inversion Attributes: Specifies built-in programmable inversion on specific pins
                IS_ALUMODE_INVERTED       => "0000",          -- Optional inversion for ALUMODE
                IS_CARRYIN_INVERTED       => '0',             -- Optional inversion for CARRYIN
                IS_CLK_INVERTED           => '0',             -- Optional inversion for CLK
                IS_INMODE_INVERTED        => "00000",         -- Optional inversion for INMODE
                IS_OPMODE_INVERTED        => "000000000",     -- Optional inversion for OPMODE
                IS_RSTALLCARRYIN_INVERTED => '0',             -- Optional inversion for RSTALLCARRYIN
                IS_RSTALUMODE_INVERTED    => '0',             -- Optional inversion for RSTALUMODE
                IS_RSTA_INVERTED          => '0',             -- Optional inversion for RSTA
                IS_RSTB_INVERTED          => '0',             -- Optional inversion for RSTB
                IS_RSTCTRL_INVERTED       => '0',             -- Optional inversion for RSTCTRL
                IS_RSTC_INVERTED          => '0',             -- Optional inversion for RSTC
                IS_RSTD_INVERTED          => '0',             -- Optional inversion for RSTD
                IS_RSTINMODE_INVERTED     => '0',             -- Optional inversion for RSTINMODE
                IS_RSTM_INVERTED          => '0',             -- Optional inversion for RSTM
                IS_RSTP_INVERTED          => '0',             -- Optional inversion for RSTP
                
                -- Register Control Attributes: Pipeline Register Configuration
                ACASCREG                  => 1,               -- Number of pipeline stages between A/ACIN and ACOUT (0-2)
                ADREG                     => 1,               -- Pipeline stages for pre-adder (0-1)
                ALUMODEREG                => 1,               -- Pipeline stages for ALUMODE (0-1)
                AREG                      => 1,               -- Pipeline stages for A (0-2)
                BCASCREG                  => 1,               -- Number of pipeline stages between B/BCIN and BCOUT (0-2)
                BREG                      => 1,               -- Pipeline stages for B (0-2)
                CARRYINREG                => 1,               -- Pipeline stages for CARRYIN (0-1)
                CARRYINSELREG             => 1,               -- Pipeline stages for CARRYINSEL (0-1)
                CREG                      => 1,               -- Pipeline stages for C (0-1)
                DREG                      => 1,               -- Pipeline stages for D (0-1)
                INMODEREG                 => 1,               -- Pipeline stages for INMODE (0-1)
                MREG                      => 1,               -- Multiplier pipeline stages (0-1)
                OPMODEREG                 => 1,               -- Pipeline stages for OPMODE (0-1)
                PREG                      => 1                -- Number of pipeline stages for P (0-1)
            )
            port map (
                -- Cascade outputs: Cascade Ports
                ACOUT          => open,                    -- 30-bit output: A port cascade
                BCOUT          => open,                    -- 18-bit output: B cascade
                CARRYCASCOUT   => open,                    -- 1-bit output: Cascade carry
                MULTSIGNOUT    => open,                    -- 1-bit output: Multiplier sign cascade
                PCOUT          => dsp_pcout(i),            -- 48-bit output: Cascade output
                
                -- Control outputs: Control Inputs/Status Bits
                OVERFLOW       => open,                    -- 1-bit output: Overflow in add/acc
                PATTERNBDETECT => dsp_patternbdetect(i),   -- 1-bit output: Pattern bar detect
                PATTERNDETECT  => dsp_patterndetect(i),    -- 1-bit output: Pattern detect
                UNDERFLOW      => open,                    -- 1-bit output: Underflow in add/acc
                
                -- Data outputs: Data Ports
                CARRYOUT       => open,                    -- 4-bit output: Carry
                P              => dsp_p(i),                -- 48-bit output: Primary data
                XOROUT         => open,                    -- 8-bit output: XOR data
                
                -- Cascade inputs: Cascade Ports
                ACIN           => X"00000000",             -- 30-bit input: A cascade data
                BCIN           => X"00000",                -- 18-bit input: B cascade
                CARRYCASCIN    => '0',                     -- 1-bit input: Cascade carry
                MULTSIGNIN     => '0',                     -- 1-bit input: Multiplier sign cascade
                PCIN           => dsp_pcin(i),          -- 48-bit input: P cascade
                
                -- Control inputs: Control Inputs/Status Bits
                ALUMODE        => dsp_alumode,             -- 4-bit input: ALU control
                CARRYINSEL     => "000",                   -- 3-bit input: Carry select
                CLK            => clk,                     -- 1-bit input: Clock
                INMODE         => "00000",                 -- 5-bit input: INMODE control
                OPMODE         => dsp_opmode,              -- 9-bit input: Operation mode
                
                -- Data inputs: Data Ports
                A              => dsp_ab(i)(47 downto 18), -- 30-bit input: A data
                B              => dsp_ab(i)(17 downto 0),  -- 18-bit input: B data
                C              => dsp_c(i),                -- 48-bit input: C data
                CARRYIN        => dsp_cfg_data(13),        -- 1-bit input: Carry-in
                D              => X"0000000",              -- 27-bit input: D data 
                
                -- Reset/Clock Enable inputs: Reset/Clock Enable Inputs
                CEA1           => dsp_ab_en(i),            -- 1-bit input: Clock enable for 1st stage AREG
                CEA2           => dsp_ab_en(i),            -- 1-bit input: Clock enable for 2nd stage AREG
                CEAD           => '0',                     -- 1-bit input: Clock enable for ADREG
                CEALUMODE      => dsp_cfg_sel(i),          -- 1-bit input: Clock enable for ALUMODE
                CEB1           => dsp_ab_en(i),            -- 1-bit input: Clock enable for 1st stage BREG
                CEB2           => dsp_ab_en(i),            -- 1-bit input: Clock enable for 2nd stage BREG
                CEC            => dsp_c_en(i),             -- 1-bit input: Clock enable for CREG
                CECARRYIN      => dsp_cfg_sel(i),          -- 1-bit input: Clock enable for CARRYINREG
                CECTRL         => dsp_cfg_sel(i),          -- 1-bit input: Clock enable for OPMODEREG and CARRYINSELREG
                CED            => '1',                     -- 1-bit input: Clock enable for DREG
                CEINMODE       => '1',                     -- 1-bit input: Clock enable for INMODEREG
                CEM            => '0',                     -- 1-bit input: Clock enable for MREG
                CEP            => dsp_p_en(i),             -- 1-bit input: Clock enable for PREG
                RSTA           => dsp_rst_ab(i),           -- 1-bit input: Reset for AREG
                RSTALLCARRYIN  => '0',                     -- 1-bit input: Reset for CARRYINREG
                RSTALUMODE     => '0',                     -- 1-bit input: Reset for ALUMODEREG
                RSTB           => dsp_rst_ab(i),           -- 1-bit input: Reset for BREG
                RSTC           => dsp_rst_c(i),            -- 1-bit input: Reset for CREG
                RSTCTRL        => '0',                     -- 1-bit input: Reset for OPMODEREG and CARRYINSELREG
                RSTD           => '1',                     -- 1-bit input: Reset for DREG and ADREG
                RSTINMODE      => '1',                     -- 1-bit input: Reset for INMODEREG
                RSTM           => '1',                     -- 1-bit input: Reset for MREG
                RSTP           => dsp_rst_p(i)             -- 1-bit input: Reset for PREG
            );
    end generate dsp_gen;

end rtl;
