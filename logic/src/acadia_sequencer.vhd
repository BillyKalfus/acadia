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
        LOG2_STACK_SIZE : natural := 5;
        NUM_DSP         : natural := 8;
        WORD_SIZE       : natural := 32
    );
    port
    (
        clk                  : in  std_logic;
        run                  : in  std_logic;        
        nrst                 : in  std_logic;
        
        -- Instruction memory interface(s)
        instruction_mem_dout : in  std_logic_vector(127 downto 0);
        instruction_mem_addr : out std_logic_vector(15 downto 0);
        instruction_mem_rst  : out std_logic;
        instruction_mem_clk  : out std_logic;
        
        -- Bus interface
        mem_bus_mosi         : out std_logic_vector(WORD_SIZE-1 downto 0);
        mem_bus_miso         : in  std_logic_vector(WORD_SIZE-1 downto 0);
        mem_bus_addr         : out std_logic_vector(WORD_SIZE-1 downto 0);
        mem_bus_wr           : out std_logic;
        mem_bus_en           : out std_logic;
        mem_bus_clk          : out std_logic;
        
        -- Hedgehog input ports
        hedgehog_flags       : in  std_logic_vector(WORD_SIZE-1 downto 0)
    );
    
end acadia_sequencer;

architecture rtl of acadia_sequencer is

    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_dout : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem DOUT";
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_addr : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem ADDR";
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_rst  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem RST";
    ATTRIBUTE X_INTERFACE_INFO of instruction_mem_clk  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 instruction_mem CLK";
    ATTRIBUTE X_INTERFACE_MODE of instruction_mem_dout : SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_mosi         : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus DIN";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_miso         : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus DOUT";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_wr           : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus WE";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_addr         : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus ADDR";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_en           : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus EN";
    ATTRIBUTE X_INTERFACE_INFO of mem_bus_clk          : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 mem_bus CLK";
    ATTRIBUTE X_INTERFACE_MODE of mem_bus_mosi         : SIGNAL is "Master";

    -- Some constants that will encode source and destination IDs (except for the last three bits)
    constant SRC_REG         : natural := 0;
    constant SRC_PC          : natural := 1;
    constant SRC_IMM         : natural := 2;
    constant SRC_TEST        : natural := 3;
    constant SRC_FLAGS       : natural := 4;
    constant SRC_STACK       : natural := 5;
    constant SRC_BUS_DATA    : natural := 6;
    constant SRC_DSP_PATTERN : natural := 7;
    constant SRC_DSP_DATA    : natural := 8;
    
    constant DEST_REG        : natural := 0;
    constant DEST_PC         : natural := 1;
    constant DEST_HOLD       : natural := 2;
    constant DEST_MASK       : natural := 3;
    constant DEST_FLAGS      : natural := 4;
    constant DEST_STACK      : natural := 5;
    constant DEST_BUS_ADDR   : natural := 6;
    constant DEST_BUS_DATA   : natural := 7;
    constant DEST_DSP_CFG    : natural := 8;
    constant DEST_DSP_AB     : natural := 9;
    constant DEST_DSP_C      : natural := 10;

    constant OPCODE_STP      : std_logic_vector(0 downto 0) := "0";
    constant OPCODE_STC      : std_logic_vector(0 downto 0) := "1";

    -- General type for array of words
    type word_array is array (natural range <>) of std_logic_vector(WORD_SIZE-1 downto 0);
                              
    -- General type for 48-bit DSP interface signals
    type dsp_array is array (natural range <>) of std_logic_vector(47 downto 0);

    -- General-purpose registers
    signal r                 : word_array(0 to 7);
    
    -- bus addressing
    signal bus_addr_reg      : std_logic_vector(WORD_SIZE-1 downto 0);
    signal bus_data_reg      : std_logic_vector(WORD_SIZE-1 downto 0);
    signal bus_wr_reg        : std_logic;
    signal bus_en_reg        : std_logic;
    
    -- Program counter
    signal pc                : std_logic_vector(15 downto 0);
    
    -- Data sources
    signal src1              : std_logic_vector(WORD_SIZE-1 downto 0);
    signal src2              : std_logic_vector(WORD_SIZE-1 downto 0);
    
    -- Decoded instruction fields
    signal dest1_en          : std_logic;
    signal dest2_en          : std_logic;
    
    -- Conditionality testing signals
    signal test_val          : std_logic_vector(WORD_SIZE-1 downto 0);
    signal test_val_d        : std_logic_vector(WORD_SIZE-1 downto 0);
    signal mask              : std_logic_vector(WORD_SIZE-1 downto 0);
    signal cond_val          : std_logic_vector(WORD_SIZE-1 downto 0);
    signal cond_satisfied    : std_logic;
    
    -- Instruction control signals
    signal instruction       : std_logic_vector(127 downto 0);
    
    signal instruction_rst   : std_logic;
    signal instruction_en    : std_logic;
    signal instruction_en_d  : std_logic;
    
    -- Instruction fields
    signal instr_opcode      : std_logic_vector(0 downto 0);
    signal instr_src1        : std_logic_vector(7 downto 0);
    signal instr_src2        : std_logic_vector(7 downto 0);  
    signal instr_dest1       : std_logic_vector(7 downto 0);
    signal instr_dest2       : std_logic_vector(7 downto 0);  
    signal instr_imm1        : std_logic_vector(WORD_SIZE-1 downto 0);
    signal instr_imm2        : std_logic_vector(WORD_SIZE-1 downto 0);
    signal instr_dsp_cep     : std_logic_vector(2 downto 0);
    signal instr_dsp_cep_en  : std_logic;
    signal instr_push_return : std_logic;
    signal instr_op_sel      : std_logic_vector(2 downto 0);
                             
    -- Instruction subfields
    signal instr_src1_maj    : natural range 0 to 15;
    signal instr_src2_maj    : natural range 0 to 15;
    signal instr_src1_sub    : natural range 0 to 7;
    signal instr_src2_sub    : natural range 0 to 7;
    signal instr_dest1_maj   : natural range 0 to 15;
    signal instr_dest2_maj   : natural range 0 to 15;
    signal instr_dest1_sub   : natural range 0 to 7;
    signal instr_dest2_sub   : natural range 0 to 7;
        
    -- Stack                          
    signal stack             : word_array(0 to STACK_SIZE-1);
    signal stack_wr_addr     : std_logic_vector(LOG2_STACK_SIZE-1 downto 0);
    signal stack_rd_addr     : std_logic_vector(LOG2_STACK_SIZE-1 downto 0);
    signal stack_rd_data     : std_logic_vector(WORD_SIZE-1 downto 0);
    signal stack_pop         : std_logic;
    signal stack_push        : std_logic;
    signal stack_overflow    : std_logic;
    signal stack_underflow   : std_logic;
                              
    -- DSP slice signals and control registers
    signal dsp_cep_reg       : std_logic_vector(NUM_DSP-1 downto 0);                             
    signal dsp_ab_reg        : dsp_array(0 to NUM_DSP-1);
    signal dsp_c_reg         : dsp_array(0 to NUM_DSP-1);
    signal dsp_cfg_reg       : word_array(0 to NUM_DSP-1);
                             
    signal dsp_rstp          : std_logic_vector(NUM_DSP-1 downto 0);
    signal dsp_p             : dsp_array(0 to NUM_DSP-1);
    signal dsp_p_reg         : word_array(0 to NUM_DSP-1);
                             
    -- DSP pattern detector signals
    signal dsp_patterndetect     : std_logic_vector(NUM_DSP-1 downto 0);
    signal dsp_patterndetectpast : std_logic_vector(NUM_DSP-1 downto 0);
                              
    -- DSP cascade
    signal dsp_pcout         : dsp_array(0 to NUM_DSP-1);
    signal dsp_pcin          : dsp_array(0 to NUM_DSP-1);
begin
                
    -- Assign instruction subfields
    instr_src1_maj <= to_integer(unsigned(instr_src1(6 downto 3)));
    instr_src1_sub <= to_integer(unsigned(instr_src1(2 downto 0)));
    instr_src2_maj <= to_integer(unsigned(instr_src2(6 downto 3)));
    instr_src2_sub <= to_integer(unsigned(instr_src2(2 downto 0)));
    instr_dest1_maj <= to_integer(unsigned(instr_dest1(6 downto 3)));
    instr_dest1_sub <= to_integer(unsigned(instr_dest1(2 downto 0)));
    instr_dest2_maj <= to_integer(unsigned(instr_dest2(6 downto 3)));
    instr_dest2_sub <= to_integer(unsigned(instr_dest2(2 downto 0)));
                             
    -- Instruction memory interface and loading
    instruction_en   <= '0' when (instr_dest1_maj = DEST_HOLD and dest1_en = '1') 
                              or (instr_dest2_maj = DEST_HOLD and dest2_en = '1')
                        else '1';
        
    -- We have to reset the instruction memory output any time we jump or come out of a hold
    instruction_rst  <= '1' when (instr_dest1_maj = DEST_PC and dest1_en = '1')
                                 or (instr_dest2_maj = DEST_PC and dest2_en = '1')
                                 or (instruction_en = '1' and instruction_en_d = '0') 
                                 or (run = '0') 
                             else '0';
    
    instruction_mem_addr <= pc;
    instruction_mem_clk  <= clk;
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
    instr_opcode   <= instruction(112 downto 112);
    instr_push_return  <= instruction(104);
    instr_src1     <= instruction(103 downto 96);
    instr_src2     <= instruction(95 downto 88);
    instr_dest1    <= instruction(87 downto 80);
    instr_dest2    <= instruction(79 downto 72);
    instr_dsp_cep_en <= instruction(68);
    instr_dsp_cep  <= instruction(66 downto 64);
    instr_imm1     <= instruction(63 downto 32);
    instr_imm2     <= instruction(31 downto 0);
    instr_op_sel   <= instruction(74 downto 72);
    
    -- Enable or disable the destination decoders depending on the instruction opcode and the condition satisfaction
    dest1_en <= cond_satisfied when instr_opcode = OPCODE_STC else '1';
    dest2_en <= '0' when instr_opcode = OPCODE_STC else '1';
                            
    -- Multiplex the input source according to the instruction field
    src1 <= r(instr_src1_sub)         when instr_src1_maj = SRC_REG      else
            x"0000" & pc              when instr_src1_maj = SRC_PC       else
            instr_imm1                when instr_src1_maj = SRC_IMM      else
            -- test_val_d                when instr_src1_maj = SRC_TEST     else
            hedgehog_flags            when instr_src1_maj = SRC_FLAGS    else
            stack_rd_data             when instr_src1_maj = SRC_STACK    else
            mem_bus_miso              when instr_src1_maj = SRC_BUS_DATA else
            dsp_p_reg(instr_src1_sub) when instr_src1_maj = SRC_DSP_DATA else
            (others => '0');
            
    src2 <= r(instr_src2_sub)         when instr_src2_maj = SRC_REG      else
            x"0000" & pc              when instr_src2_maj = SRC_PC       else
            instr_imm2                when instr_src2_maj = SRC_IMM      else
            -- test_val_d                when instr_src2_maj = SRC_TEST     else
            hedgehog_flags            when instr_src2_maj = SRC_FLAGS    else
            stack_rd_data             when instr_src2_maj = SRC_STACK    else
            mem_bus_miso              when instr_src2_maj = SRC_BUS_DATA else
            dsp_p_reg(instr_src2_sub) when instr_src2_maj = SRC_DSP_DATA else
            (others => '0');
            
    -- Make general-purpose registers
    reg_proc: process(clk) begin
        if(rising_edge(clk)) then        
            if(nrst = '0') then
                r <= (others => (others => '0'));
            elsif(instr_dest1_maj = DEST_REG and dest1_en = '1') then
                r(instr_dest1_sub) <= src1;
            elsif(instr_dest2_maj = DEST_REG and dest2_en = '1') then
                r(instr_dest2_sub) <= src2;
            end if;
        end if;
    end process reg_proc;
    
    -- Load the test value register when we are issuing a conditional operation
--    test_val_proc: process(clk) begin
--        if rising_edge(clk) then
--            test_val_d <= test_val;
--            if(nrst = '0') then
--                test_val <= (others => '0');
--            elsif(instr_opcode = OPCODE_STC) then
--                test_val <= src2;
--            end if;
--        end if;
--    end process test_val_proc;
    
    -- Manage the bus registers
    bus_regs_proc: process(clk) begin
        if(rising_edge(clk)) then
            if(nrst = '0') then
                bus_addr_reg <= (others => '0');
                bus_data_reg <= (others => '0');
                bus_wr_reg   <= '0';
                bus_en_reg   <= '0';
            else
                if(instr_dest1_maj = DEST_BUS_ADDR and dest1_en = '1') then
                    bus_addr_reg <= src1;
                elsif(instr_dest2_maj = DEST_BUS_ADDR and dest2_en = '1') then
                    bus_addr_reg <= src2;
                end if;
                
                if(instr_dest1_maj = DEST_BUS_DATA and dest1_en = '1') then
                    bus_data_reg <= src1;
                elsif(instr_dest2_maj = DEST_BUS_DATA and dest2_en = '1') then
                    bus_data_reg <= src2;
                end if;
                
                if((instr_dest1_maj = DEST_BUS_DATA and dest1_en = '1') 
                       or (instr_dest2_maj = DEST_BUS_DATA and dest2_en = '1')) then
                    bus_wr_reg <= '1';
                else
                    bus_wr_reg <= '0';
                end if;
                       
                if(((instr_dest1_maj = DEST_BUS_DATA or instr_src1_maj = SRC_BUS_DATA) and dest1_en = '1') 
                       or ((instr_dest2_maj = DEST_BUS_DATA or instr_src2_maj = SRC_BUS_DATA) and dest2_en = '1')) then 
                    bus_en_reg <= '1';
                else
                    bus_en_reg <= '0';
                end if;
                
            end if;
        end if;
    end process bus_regs_proc;
    
    -- Assign the bus address output
    mem_bus_addr <= bus_addr_reg; 
    mem_bus_mosi <= bus_data_reg;
    mem_bus_wr   <= bus_wr_reg;
    mem_bus_en   <= bus_en_reg;
    mem_bus_clk  <= clk;
    
    -- Program counter
    pc_proc: process(clk) begin
        if(rising_edge(clk)) then
            if(nrst = '0' or run = '0') then
                pc <= (others => '0');
            elsif(dest1_en = '1' and (instr_dest1_maj = DEST_PC or instr_dest1_maj = DEST_HOLD)) then
                pc <= src1(15 downto 0);
            elsif(dest2_en = '1' and (instr_dest2_maj = DEST_PC or instr_dest2_maj = DEST_HOLD)) then
                pc <= src2(15 downto 0);
            elsif(instruction_rst = '0') then
                pc <= std_logic_vector(unsigned(pc) + 1);
            end if;
        end if;
    end process pc_proc;
    
    -- Process for conditional operation mask register
    mask_proc: process(clk) begin
        if(rising_edge(clk)) then
            if(nrst = '0') then
                mask <= (others => '0');
            elsif(instr_dest1_maj = DEST_MASK and dest1_en = '1') then
                mask <= src1;
            elsif(instr_dest2_maj = DEST_MASK and dest2_en = '1') then
                mask <= src2;
            end if;
        end if;
    end process mask_proc;
    
    cond_val <= src2 and mask when instr_op_sel(1 downto 0) = "00" else
                src2 xor mask when instr_op_sel(1 downto 0) = "01" else
                (not src2) and mask when instr_op_sel(1 downto 0) = "10" else
                src2;
                
    cond_satisfied <= or_reduce(cond_val) xor instr_op_sel(2);
   
    -- Implement the stack
    -- Assign some various combinational signals
    stack_pop       <= '1' when (instr_src1_maj = SRC_STACK and dest1_en = '1') 
                             or (instr_src2_maj = SRC_STACK and dest2_en = '1') else '0';
                   
    stack_push      <= '1' when (instr_dest1_maj = DEST_STACK and dest1_en = '1') 
                             or (instr_dest2_maj = DEST_STACK and dest2_en = '1') 
                             or instr_push_return = '1'
                        else '0';
                             
    stack_overflow  <= '1' when to_integer(unsigned(stack_wr_addr)) = STACK_SIZE-1 and stack_push = '1' else '0';
    stack_underflow <= '1' when to_integer(unsigned(stack_wr_addr)) = 0 and stack_pop = '1' else '0';

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
            if(instr_dest1_maj = DEST_STACK and dest1_en = '1') then
                stack(to_integer(unsigned(stack_wr_addr))) <= src1;
            elsif(instr_dest2_maj = DEST_STACK and dest2_en = '1') then
                stack(to_integer(unsigned(stack_wr_addr))) <= src2;
            elsif(instr_push_return = '1') then
                -- Minus 1 because we lose 2 instructions due to instruction memory latency
                stack(to_integer(unsigned(stack_wr_addr))) <= x"0000" & std_logic_vector(unsigned(pc) - 1);
            end if;
        end if;
    end process stack_wr_proc;
           
    -- Control reading from the stack
    stack_rd_proc: process(clk) begin
        if rising_edge(clk) then
            stack_rd_data <= stack(to_integer(unsigned(stack_rd_addr)));
        end if;
    end process stack_rd_proc;
    
    -- DSP slices
         
    -- Generate the cascade signals
    -- only go up to NUM_DSP-2 because of the +1 in the loop
    dsp_pcin(0) <= (others => '0');
    dsp_pc_gen: for i in 0 to NUM_DSP-2 generate
        dsp_pcin(i+1) <= dsp_pcout(i);
    end generate dsp_pc_gen;    
        
    -- Pipeline the configuration inputs
    dsp_cfg_reg_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                dsp_cfg_reg <= (others => (others => '0'));
            elsif(instr_dest1_maj = DEST_DSP_CFG and dest1_en = '1') then
                dsp_cfg_reg(instr_dest1_sub) <= src1;
            elsif(instr_dest2_maj = DEST_DSP_CFG and dest2_en = '1') then
                dsp_cfg_reg(instr_dest2_sub) <= src2;
            end if;
        end if;
    end process dsp_cfg_reg_proc;
                   
    dsp_rstp_gen: for i in 0 to NUM_DSP-1 generate
        dsp_rstp(i) <= src1(14) when instr_dest1_maj = DEST_DSP_CFG and dest1_en = '1' and instr_dest1_sub = i else
                       src2(14) when instr_dest2_maj = DEST_DSP_CFG and dest2_en = '1' and instr_dest2_sub = i else
                       '0';
    end generate dsp_rstp_gen;
                             
    instr_dsp_cep_reg_proc: process(clk) begin
        if rising_edge(clk) then
            dsp_cep_reg_loop: for i in 0 to NUM_DSP-1 loop
                if(nrst = '0') then
                    dsp_cep_reg(i) <= '0';
                elsif(instr_dsp_cep_en = '1' and to_integer(unsigned(instr_dsp_cep)) = i) then
                    dsp_cep_reg(i) <= '1';
                elsif(dsp_cfg_reg(i)(21) = '1') then
                    dsp_cep_reg(i) <= '0';
                end if;
            end loop dsp_cep_reg_loop;
        end if;
    end process instr_dsp_cep_reg_proc;
                             
    -- Pipeline the AB inputs
    dsp_ab_reg_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                dsp_ab_reg <= (others => (others => '0'));
            elsif(instr_dest1_maj = DEST_DSP_AB and dest1_en = '1') then
                dsp_ab_reg(instr_dest1_sub)(31 downto 0)  <= src1;
                dsp_ab_reg(instr_dest1_sub)(47 downto 32) <= (others => src1(31));
            elsif(instr_dest2_maj = DEST_DSP_AB and dest2_en = '1') then
                dsp_ab_reg(instr_dest2_sub)(31 downto 0)  <= src2;
                dsp_ab_reg(instr_dest2_sub)(47 downto 32) <= (others => src2(31));
            end if;
        end if;
    end process dsp_ab_reg_proc;
                             
    -- Pipeline the C input
    dsp_c_reg_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                dsp_c_reg <= (others => (others => '0'));
            elsif(instr_dest1_maj = DEST_DSP_C and dest1_en = '1') then
                dsp_c_reg(instr_dest1_sub)(31 downto 0)  <= src1;
                dsp_c_reg(instr_dest1_sub)(47 downto 32) <= (others => src1(31));
            elsif(instr_dest2_maj = DEST_DSP_C and dest2_en = '1') then
                dsp_c_reg(instr_dest2_sub)(31 downto 0)  <= src2;
                dsp_c_reg(instr_dest2_sub)(47 downto 32) <= (others => src2(31));
            end if;
        end if;
    end process dsp_c_reg_proc;
                             
    -- Pipeline the P register output
    dsp_p_reg_proc: process(clk) begin
        if rising_edge(clk) then
            dsp_p_reg_loop: for i in 0 to NUM_DSP-1 loop
                dsp_p_reg(i) <= dsp_p(i)(WORD_SIZE-1 downto 0);
            end loop dsp_p_reg_loop;
        end if;
    end process dsp_p_reg_proc;
    
    -- Instantiate the DSP slices
    dsp_gen: for i in 0 to NUM_DSP-1 generate        
        DSP_inst : DSP48E2
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
                MREG                      => 0,               -- Multiplier pipeline stages (0-1)
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
                PATTERNBDETECT => open,                    -- 1-bit output: Pattern bar detect
                PATTERNDETECT  => dsp_patterndetect(i),    -- 1-bit output: Pattern detect
                UNDERFLOW      => open,                    -- 1-bit output: Underflow in add/acc
                
                -- Data outputs: Data Ports
                CARRYOUT       => open,                    -- 4-bit output: Carry
                P              => dsp_p(i),                -- 48-bit output: Primary data
                XOROUT         => open,                    -- 8-bit output: XOR data
                
                -- Cascade inputs: Cascade Ports
                ACIN           => "000000000000000000000000000000",  -- 30-bit input: A cascade data
                BCIN           => "000000000000000000",              -- 18-bit input: B cascade
                CARRYCASCIN    => '0',                     -- 1-bit input: Cascade carry
                MULTSIGNIN     => '0',                     -- 1-bit input: Multiplier sign cascade
                PCIN           => dsp_pcin(i),             -- 48-bit input: P cascade
                
                -- Control inputs: Control Inputs/Status Bits
                ALUMODE        => dsp_cfg_reg(i)(3 downto 0),  -- 4-bit input: ALU control
                CARRYINSEL     => "000",                       -- 3-bit input: Carry select
                CLK            => clk,                         -- 1-bit input: Clock
                INMODE         => "00000",                     -- 5-bit input: INMODE control
                OPMODE         => dsp_cfg_reg(i)(12 downto 4), -- 9-bit input: Operation mode
                
                -- Data inputs: Data Ports
                A              => dsp_ab_reg(i)(47 downto 18),   -- 30-bit input: A data
                B              => dsp_ab_reg(i)(17 downto 0),    -- 18-bit input: B data
                C              => dsp_c_reg(i),                  -- 48-bit input: C data
                CARRYIN        => dsp_cfg_reg(i)(13),            -- 1-bit input: Carry-in
                D              => "000000000000000000000000000", -- 27-bit input: D data 
                
                -- Reset/Clock Enable inputs: Reset/Clock Enable Inputs
                CEA1           => '1',            -- 1-bit input: Clock enable for 1st stage AREG
                CEA2           => '1',            -- 1-bit input: Clock enable for 2nd stage AREG
                CEAD           => '0',            -- 1-bit input: Clock enable for ADREG
                CEALUMODE      => '1',            -- 1-bit input: Clock enable for ALUMODE
                CEB1           => '1',            -- 1-bit input: Clock enable for 1st stage BREG
                CEB2           => '1',            -- 1-bit input: Clock enable for 2nd stage BREG
                CEC            => '1',            -- 1-bit input: Clock enable for CREG
                CECARRYIN      => '1',            -- 1-bit input: Clock enable for CARRYINREG
                CECTRL         => '1',            -- 1-bit input: Clock enable for OPMODEREG and CARRYINSELREG
                CED            => '1',            -- 1-bit input: Clock enable for DREG
                CEINMODE       => '1',            -- 1-bit input: Clock enable for INMODEREG
                CEM            => '0',            -- 1-bit input: Clock enable for MREG
                CEP            => dsp_cep_reg(i), -- 1-bit input: Clock enable for PREG
                RSTA           => '0',            -- 1-bit input: Reset for AREG
                RSTALLCARRYIN  => '0',            -- 1-bit input: Reset for CARRYINREG
                RSTALUMODE     => '0',            -- 1-bit input: Reset for ALUMODEREG
                RSTB           => '0',            -- 1-bit input: Reset for BREG
                RSTC           => '0',            -- 1-bit input: Reset for CREG
                RSTCTRL        => '0',            -- 1-bit input: Reset for OPMODEREG and CARRYINSELREG
                RSTD           => '1',            -- 1-bit input: Reset for DREG and ADREG
                RSTINMODE      => '1',            -- 1-bit input: Reset for INMODEREG
                RSTM           => '1',            -- 1-bit input: Reset for MREG
                RSTP           => dsp_rstp(i)     -- 1-bit input: Reset for PREG
            );
    end generate dsp_gen;

end rtl;
