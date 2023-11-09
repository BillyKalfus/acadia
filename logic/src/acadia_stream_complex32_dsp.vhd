----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/25/2022 11:52:49 PM
-- Design Name: acadia
-- Module Name: acadia_complex_dsp - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description:
--     An input stream is interpreted as packed complex numbers with
--     a firmware-specified quadrature width. A runtime-configurable 
--     amount of these numbers are processed with a DSP slice, before being 
--     streamed out of the module through an internal buffer FIFO.
--
--     Based on the width of the stream and the specified quadrature
--     width, more than one complex number may be present at the 
--     input each clock cycle; these are always added together. 
--     By configuring the internal DSP slice, the module is 
--     configured at runtime to process this decimated stream as it arrives.
--    
--     Data is processed in AXI-stream packets, which is a sequence of valid
--     data terminating in a cycle of valid data with a last signal. During a
--     packet, a counter is continually running and is incremented by 1 for each
--     valid data beat present at the input. The counter is reset when it overflows 
--     (determined by a programmable overflow value) and when the packet ends.
--     DSP behavior can be specified independently for the following events:
--         Packet start: This configuration is applied for only the first cycle of the packet.
--         Counter start: This configuration is applied after the counter overflows (that is, 
--                        the first cycle of a new counter period but not the first of the packet).
--         Counter running: This configuration is applied when the counter is running, but only when
--                           it's not the first cycle of a packet and when it's not the first cycle 
--                           after a counter overflow.
--                          
--     
--     The counter output is connected to the PCIN cascade input of the main DSP slice.
--     
--     This module has the following configuration registers:
--         Address 0: General settings
--             Bit 0: Real Overflow (latched, write 1 to clear, writing 0 has no effect)
--             Bit 1: Real Underflow (latched, write 1 to clear, writing 0 has no effect)
--             Bit 2: Imag Overflow (latched, write 1 to clear, writing 0 has no effect)
--             Bit 3: Imag Underflow (latched, write 1 to clear, writing 0 has no effect)
--             Bit 4: Internal reset
--             Bit 5: Update packet DSP mode
--         Address 1: Real scale factor
--             Bits 17-0: Connected to input B[17:0] of the real DSP (read/write)
--         Address 2: Real pre-add quantity
--             Bits 16-0: Connected to input D[16:0] of the real DSP (read/write)
--         Address 3: Real post-op/pattern (low)
--             Bits 31-16: Connected to input C[15:0] of the real DSP (read/write)
--         Address 4: Real post-op/pattern (high)
--             Bits 31-0: Connected to input C[47:16] of the real DSP (read/write)
--         Address 5: Imaginary scale factor
--             Bits 17-0: Connected to input B[17:0] of the imaginary DSP (read/write)
--         Address 6: Imaginary pre-add quantity
--             Bits 16-0: Connected to input D[16:0] of the imaginary DSP (read/write)
--         Address 7: Imaginary post-op/pattern (low)
--             Bits 31-16: Connected to input C[15:0] of the imaginary DSP (read/write)
--         Address 8: Imaginary post-op/pattern (high)
--             Bits 31-0: Connected to input C[47:16] of the imaginary DSP (read/write)
--         Address 9: Packet start DSP config (loaded into DSP mode registers for the first cycle in a packet)
--             Bits 3-0: ALUMODE
--             Bits 12-4: OPMODE
--             Bits 13: CIN
--         Address 10: Counter start DSP config
--             Values for the DSP config registers applied for only the first cycle after the counter overflows
--         Address 11: Default run DSP config
--             Values for the DSP config registers during regular operation (valid data, not the first cycle 
--             in a packet, not the first cycle of the counter)
--         Address 12: Counter period (low)
--             Bits 31-16: Low bits of counter period (connected to counter DSP C[15:0])
--         Address 13: Counter period (high)
--             Bits 31-0: High bits of counter period (connected to counter DSP C[47:16])
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

entity acadia_stream_complex32_dsp is
    generic (
        -- Number of quadratures pairs present in the input must be <= 4
        INPUT_WORDS                   : positive := 4; 
        DATA_OUTPUT_FIFO_DEPTH        : positive := 1024;
        DATA_OUTPUT_FIFO_PRIMITIVE    : string := "auto";
        DATA_OUTPUT_FIFO_ASYNCHRONOUS : boolean := true
    );
    port (
        clk              : in  std_logic;
            
        data_in_tdata    : in  std_logic_vector((INPUT_WORDS*32)-1 downto 0);
        data_in_tvalid   : in  std_logic;
        data_in_tready   : out std_logic;
        data_in_tlast    : in  std_logic;
        
        data_out_aclk    : in  std_logic;
        data_out_tdata   : out std_logic_vector(63 downto 0);
        data_out_tvalid  : out std_logic;
        data_out_tready  : in  std_logic;
        data_out_tlast   : out std_logic;
        data_out_tkeep   : out std_logic_vector(7 downto 0);

        registers_mosi   : in  std_logic_vector(31 downto 0);
        registers_miso   : out std_logic_vector(31 downto 0);
        registers_addr   : in  std_logic_vector(31 downto 0);
        registers_we     : in  std_logic;
        registers_en     : in  std_logic
    );
    
    attribute USE_DSP : string;
end acadia_stream_complex32_dsp;

architecture rtl of acadia_stream_complex32_dsp is
    
    attribute USE_DSP of rtl : architecture is "YES";
    
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_PARAMETER of clk: SIGNAL is "ASSOCIATED_BUSIF data_in:registers";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TDATA";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TVALID";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tready : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TREADY";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TLAST";
    ATTRIBUTE X_INTERFACE_PARAMETER of data_in_tdata : SIGNAL is "HAS_TLAST 1,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(INPUT_WORDS*4/8);

    ATTRIBUTE X_INTERFACE_PARAMETER of data_out_aclk: SIGNAL is "ASSOCIATED_BUSIF data_out";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TDATA";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TLAST";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TVALID";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tready : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TREADY";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TKEEP";
    ATTRIBUTE X_INTERFACE_MODE of data_out_tdata  : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of data_out_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES 8";
    
    ATTRIBUTE X_INTERFACE_INFO of registers_mosi: SIGNAL is "xilinx.com:interface:bram:1.0 registers DIN";
    ATTRIBUTE X_INTERFACE_INFO of registers_miso: SIGNAL is "xilinx.com:interface:bram:1.0 registers DOUT";
    ATTRIBUTE X_INTERFACE_INFO of registers_addr: SIGNAL is "xilinx.com:interface:bram:1.0 registers ADDR";
    ATTRIBUTE X_INTERFACE_INFO of registers_we  : SIGNAL is "xilinx.com:interface:bram:1.0 registers WE";
    ATTRIBUTE X_INTERFACE_INFO of registers_en  : SIGNAL is "xilinx.com:interface:bram:1.0 registers EN";

    -- not a typo, accumulator is 47 not 48 bits
    constant ACCUMULATOR_QUAD_WIDTH : positive := 47;
    
    -- Internal reset signal
    signal rst : std_logic;

    -- Data input narrowing register
    signal data_in_re_narrowed    : std_logic_vector(18 downto 0); 
    signal data_in_re_narrowed_se : std_logic_vector(29 downto 0); 
    signal data_in_im_narrowed    : std_logic_vector(18 downto 0); 
    signal data_in_im_narrowed_se : std_logic_vector(29 downto 0); 
    signal data_in_narrowed_valid : std_logic;

    signal data_in_narrowed_last      : std_logic;
    signal data_in_narrowed_last_d    : std_logic;
    signal data_in_narrowed_last_dd   : std_logic;
    signal data_in_narrowed_last_ddd  : std_logic;
    signal data_in_narrowed_last_dddd : std_logic;

    -- Register-driven direct inputs
    signal dsp_b_re_reg : std_logic_vector(17 downto 0);
    signal dsp_c_re_reg : std_logic_vector(47 downto 0);
    signal dsp_d_re_reg : std_logic_vector(26 downto 0);
    signal dsp_b_im_reg : std_logic_vector(17 downto 0);
    signal dsp_c_im_reg : std_logic_vector(47 downto 0);
    signal dsp_d_im_reg : std_logic_vector(26 downto 0);
    
    -- Mode control inputs to the DSP (concatenation of CIN, OPMODE, ALUMODE)
    signal dsp_cfg_reg    : std_logic_vector(13 downto 0); -- CIN & OPMODE & ALUMODE
    signal dsp_cfg_reg_d  : std_logic_vector(13 downto 0); -- CIN & OPMODE & ALUMODE
    signal dsp_cfg_reg_dd : std_logic_vector(13 downto 0); -- CIN & OPMODE & ALUMODE

    signal mode_counter_first : std_logic_vector(13 downto 0);
    signal mode_default       : std_logic_vector(13 downto 0);
    signal mode_packet_first  : std_logic_vector(13 downto 0);

    -- Direct connections to DSP slice status signals
    signal errors      : std_logic_vector(4 downto 0);
    signal error_latch : std_logic_vector(4 downto 0);    

    -- Cascade signals
    signal counter_pcout     : std_logic_vector(47 downto 0);
    signal dsp_re_pcout      : std_logic_vector(47 downto 0);

    -- Counter signals
    signal counter_c_reg      : std_logic_vector(47 downto 0);
    signal counter_mode       : std_logic_vector(8 downto 0);
    signal counter_match      : std_logic;

    -- DSP outputs
    signal dsp_re_output     : std_logic_vector(47 downto 0);
    signal dsp_im_output     : std_logic_vector(47 downto 0);
    signal dsp_output_valid  : std_logic;
    signal dsp_output_valid_p   : std_logic;
    signal dsp_output_valid_pp  : std_logic;
    signal dsp_output_valid_ppp : std_logic;

    signal dsp_output_last     : std_logic;
    signal dsp_output_last_p   : std_logic;
    signal dsp_output_last_pp  : std_logic;
    signal dsp_output_last_ppp : std_logic;

begin

    data_in_tready <= '1';

    input_narrowing_proc: process(clk) 
       variable se     : signed(18 downto 0);
       variable sum_re : signed(18 downto 0); 
       variable sum_im : signed(18 downto 0); 
    begin
        if rising_edge(clk) then
            -- Use variables and a loop to sum all the inputs
            -- We'll use separate loops to do the real and imaginary parts
            -- There's probably a more elegant way to do this with a nested loop but it's unlikely
            -- that this would ever need more than two pairs and this way is clearer so I don't
            -- give a hoot
            sum_re := (others => '0');
            sum_re_loop: for i in 0 to INPUT_WORDS-1 loop
                se(15 downto 0)  := signed(data_in_tdata(i*16 + 15 downto i*16));
                se(18 downto 16) := (others => data_in_tdata(i*16 + 15));
                
                sum_re := sum_re + se;
            end loop sum_re_loop;

            sum_im := (others => '0');
            sum_im_loop: for i in 0 to INPUT_WORDS-1 loop
                se(15 downto 0)  := signed(data_in_tdata(i*16 + 15 downto i*16));
                se(18 downto 16) := (others => data_in_tdata(i*16 + 15));
                
                sum_im := sum_im + se;
            end loop sum_im_loop;

            -- Now update the outputs with the varables
            data_in_re_narrowed    <= std_logic_vector(sum_re);
            data_in_im_narrowed    <= std_logic_vector(sum_im);

            data_in_narrowed_valid <= data_in_tvalid;
            data_in_narrowed_last  <= data_in_tlast;
            data_in_narrowed_last_d <= data_in_narrowed_last;
            data_in_narrowed_last_dd <= data_in_narrowed_last_d;
        end if;
    end process input_narrowing_proc;
    
    -- Sign extend the narrowed data
    data_in_re_narrowed_se(18 downto 0) <= data_in_re_narrowed;
    data_in_re_narrowed_se(29 downto 19) <= (others => data_in_re_narrowed(data_in_re_narrowed'high));
    data_in_im_narrowed_se(18 downto 0) <= data_in_im_narrowed;
    data_in_im_narrowed_se(29 downto 19) <= (others => data_in_im_narrowed(data_in_im_narrowed'high));

    -- Load DSP configurations depending on first cycles
    dsp_cfg_proc: process(clk) begin
        if rising_edge(clk) then
            dsp_cfg_reg_d <= dsp_cfg_reg;
            dsp_cfg_reg_dd <= dsp_cfg_reg_d;
            if(rst = '1' or (registers_we = '1' and registers_en = '1' 
                            and registers_addr(3 downto 0) = x"0" and registers_mosi(5) = '1')) then
                -- Next valid data is packet first (due to reset)
                dsp_cfg_reg <= mode_packet_first;
            elsif(data_in_narrowed_valid = '1') then
                if(data_in_narrowed_last = '1') then
                    -- Next valid data is packet first (due to tlast)
                    dsp_cfg_reg <= mode_packet_first;
                elsif(counter_match = '1') then
                    -- Next valid data is counter first (due to counter overflow)
                    dsp_cfg_reg <= mode_counter_first;
                else
                    -- Default
                    dsp_cfg_reg <= mode_default;
                end if;
            else
                -- When data is invalid we want the contents of the DSP P to not change
                -- P = P
                -- W = 01, Z = 000, Y = 00, X = 00
                -- ALUMODE = 0000 (W + X + Y + Z + CIN)
                dsp_cfg_reg <= "0" & "01" & "000" & "00" & "00" & "0000";
            end if;
        end if;
    end process dsp_cfg_proc;

    -- Create a process for controlling register access
    registers_rd_proc: process(clk) begin
        if rising_edge(clk) then
            case registers_addr(3 downto 0) is
                when x"0" =>
                    registers_miso(errors'high downto 0)    <= errors;
                    registers_miso(31 downto errors'high+1) <= (others => '0');
                when x"1" =>
                    registers_miso(dsp_b_re_reg'high downto 0)     <= dsp_b_re_reg;
                    registers_miso(31 downto dsp_b_re_reg'high+1)  <= (others => dsp_b_re_reg(dsp_b_re_reg'high));
                when x"2" => 
                    registers_miso(dsp_d_re_reg'high downto 0)    <= dsp_d_re_reg;
                    registers_miso(31 downto dsp_d_re_reg'high+1) <= (others => dsp_d_re_reg(dsp_d_re_reg'high));
                when x"3" =>
                    registers_miso(31 downto 16) <= dsp_c_re_reg(15 downto 0);
                    registers_miso(15 downto 0)  <= (others => '0');
                when x"4" =>
                    registers_miso <= dsp_c_re_reg(47 downto 16);
                when x"5" =>
                    registers_miso(dsp_b_im_reg'high downto 0)     <= dsp_b_im_reg;
                    registers_miso(31 downto dsp_b_im_reg'high+1)  <= (others => dsp_b_im_reg(dsp_b_im_reg'high));
                when x"6" => 
                    registers_miso(dsp_d_im_reg'high downto 0)    <= dsp_d_im_reg;
                    registers_miso(31 downto dsp_d_im_reg'high+1) <= (others => dsp_d_im_reg(dsp_d_im_reg'high));
                when x"7" =>
                    registers_miso(31 downto 16) <= dsp_c_im_reg(15 downto 0);
                    registers_miso(15 downto 0)  <= (others => '0');
                when x"8" =>
                    registers_miso <= dsp_c_im_reg(47 downto 16);
                when x"9" => 
                    registers_miso(mode_packet_first'high downto 0)  <= mode_packet_first;
                    registers_miso(31 downto mode_packet_first'high) <= (others => '0');
                when x"A" =>
                    registers_miso(mode_counter_first'high downto 0)  <= mode_counter_first;
                    registers_miso(31 downto mode_counter_first'high) <= (others => '0');
                when x"B" =>
                    registers_miso(mode_default'high downto 0)  <= mode_default;
                    registers_miso(31 downto mode_default'high) <= (others => '0');
                when x"C" =>
                    registers_miso(31 downto 16) <= counter_c_reg(15 downto 0);
                    registers_miso(15 downto 0)  <= (others => '0');
                when x"D" =>
                    registers_miso <= counter_c_reg(47 downto 16);
                when others =>
                    registers_miso <= (others => '0');
            end case;
        end if;
    end process registers_rd_proc;

    -- While some signals will be updated when registers are written and those are
    -- handled in their own processes, some registers behave like normal registers and can simply be updated in a process
    registers_wr_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                dsp_b_re_reg <= (others => '0');
                dsp_d_re_reg <= (others => '0');
                dsp_c_re_reg <= (others => '0');
                dsp_b_im_reg <= (others => '0');
                dsp_d_im_reg <= (others => '0');
                dsp_c_im_reg <= (others => '0');
                mode_counter_first <= (others => '0');
                mode_packet_first <= (others => '0');
                mode_default <= (others => '0');
                counter_c_reg <= (others => '0');
            elsif(registers_we = '1' and registers_en = '1') then
                if(registers_addr(3 downto 0) = x"1") then
                    dsp_b_re_reg <= registers_mosi(dsp_b_re_reg'high downto 0);
                end if;

                if(registers_addr(3 downto 0) = x"2") then
                    dsp_d_re_reg <= registers_mosi(dsp_d_re_reg'high downto 0);
                end if;

                if(registers_addr(3 downto 0) = x"3") then
                    dsp_c_re_reg(15 downto 0) <= registers_mosi(31 downto 16);
                end if;

                if(registers_addr(3 downto 0) = x"4") then
                    dsp_c_re_reg(47 downto 16) <= registers_mosi;
                end if;
                
                if(registers_addr(3 downto 0) = x"5") then
                    dsp_b_im_reg <= registers_mosi(dsp_b_im_reg'high downto 0);
                end if;

                if(registers_addr(3 downto 0) = x"6") then
                    dsp_d_im_reg <= registers_mosi(dsp_d_im_reg'high downto 0);
                end if;

                if(registers_addr(3 downto 0) = x"7") then
                    dsp_c_im_reg(15 downto 0) <= registers_mosi(31 downto 16);
                end if;

                if(registers_addr(3 downto 0) = x"8") then
                    dsp_c_im_reg(47 downto 16) <= registers_mosi;
                end if;

                if(registers_addr(3 downto 0) = x"9") then
                    mode_packet_first <= registers_mosi(mode_packet_first'high downto 0);
                end if;

                if(registers_addr(3 downto 0) = x"A") then
                    mode_counter_first <= registers_mosi(mode_counter_first'high downto 0);
                end if;

                if(registers_addr(3 downto 0) = x"B") then
                    mode_default <= registers_mosi(mode_default'high downto 0);
                end if;

                if(registers_addr(3 downto 0) = x"C") then
                    counter_c_reg(15 downto 0) <= registers_mosi(31 downto 16);
                end if;

                if(registers_addr(3 downto 0) = x"D") then
                    counter_c_reg(47 downto 16) <= registers_mosi;
                end if;
            end if;
        end if;
    end process registers_wr_proc;

    rst_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                rst <= '0';
            elsif(registers_we = '1' and registers_en = '1' and 
                    registers_addr(3 downto 0) = x"0" and registers_mosi(4) = '1') then
                rst <= '1';
            end if;
        end if;
    end process rst_proc;

    -- Latch the DSP status signals
    dsp_latch_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst = '1') then
                error_latch <= (others => '0');
            elsif(registers_we = '1' and registers_en = '1' and 
                    registers_addr(3 downto 0) = x"0") then
                error_latch <= (not registers_mosi(error_latch'high downto 0)) and error_latch;
            else
                error_latch <= error_latch or errors;
            end if;
        end if;
    end process dsp_latch_proc;

    -- When the counter matches it needs to reset P, otherwise increment it by A:B
    -- (which we'll connect to the data valid signal)
    -- Note that we can't use RSTP for this since that resets the pattern detector 
    -- as well, which will fail if we use a pattern of 0
    -- When counter_match = '0': W = P, X = A:B, Y = 0, Z = 0
    --                      '1': 
    counter_mode <= (others => '0') when (counter_match = '1' or rst = '1') else "010000011";

    -- We can't infer the pattern detector, so we'll manually instantiate the DSP 
    counter_inst : DSP48E2
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
            SEL_PATTERN               => "C",             -- Select pattern value (C, PATTERN)
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
            ACASCREG                  => 0,               -- Number of pipeline stages between A/ACIN and ACOUT (0-2)
            ADREG                     => 0,               -- Pipeline stages for pre-adder (0-1)
            ALUMODEREG                => 1,               -- Pipeline stages for ALUMODE (0-1)
            AREG                      => 0,               -- Pipeline stages for A (0-2)
            BCASCREG                  => 0,               -- Number of pipeline stages between B/BCIN and BCOUT (0-2)
            BREG                      => 0,               -- Pipeline stages for B (0-2)
            CARRYINREG                => 1,               -- Pipeline stages for CARRYIN (0-1)
            CARRYINSELREG             => 1,               -- Pipeline stages for CARRYINSEL (0-1)
            CREG                      => 1,               -- Pipeline stages for C (0-1)
            DREG                      => 1,               -- Pipeline stages for D (0-1)
            INMODEREG                 => 1,               -- Pipeline stages for INMODE (0-1)
            MREG                      => 1,               -- Multiplier pipeline stages (0-1)
            OPMODEREG                 => 0,               -- Pipeline stages for OPMODE (0-1)
            PREG                      => 1                -- Number of pipeline stages for P (0-1)
        )
        port map (
            -- Cascade outputs: Cascade Ports
            ACOUT          => open,                    -- 30-bit output: A port cascade
            BCOUT          => open,                    -- 18-bit output: B cascade
            CARRYCASCOUT   => open,                    -- 1-bit output: Cascade carry
            MULTSIGNOUT    => open,                    -- 1-bit output: Multiplier sign cascade
            PCOUT          => counter_pcout,            -- 48-bit output: Cascade output
            
            -- Control outputs: Control Inputs/Status Bits
            OVERFLOW       => open,                    -- 1-bit output: Overflow in add/acc
            PATTERNBDETECT => open,                    -- 1-bit output: Pattern bar detect
            PATTERNDETECT  => counter_match,    -- 1-bit output: Pattern detect
            UNDERFLOW      => open,                    -- 1-bit output: Underflow in add/acc
            
            -- Data outputs: Data Ports
            CARRYOUT       => open,                    -- 4-bit output: Carry
            P              => open,                -- 48-bit output: Primary data
            XOROUT         => open,                    -- 8-bit output: XOR data
            
            -- Cascade inputs: Cascade Ports
            ACIN           => "000000000000000000000000000000",  -- 30-bit input: A cascade data
            BCIN           => "000000000000000000",              -- 18-bit input: B cascade
            CARRYCASCIN    => '0',                     -- 1-bit input: Cascade carry
            MULTSIGNIN     => '0',                     -- 1-bit input: Multiplier sign cascade
            PCIN           => x"000000000000",             -- 48-bit input: P cascade
            
            -- Control inputs: Control Inputs/Status Bits
            ALUMODE        => "0000",  -- Z+X+W+Y+CIN
            CARRYINSEL     => "000",                       -- 3-bit input: Carry select
            CLK            => clk,                         -- 1-bit input: Clock
            INMODE         => "00000",                     -- 5-bit input: INMODE control
            OPMODE         => counter_mode,
            
            -- Data inputs: Data Ports
            A              => "000000000000000000000000000000",   -- 30-bit input: A data
            B(17 downto 1) => "00000000000000000",
            B(0)           => data_in_narrowed_valid,    -- 18-bit input: B data
            C              => counter_c_reg,                  -- 48-bit input: C data
            CARRYIN        => '0',            -- 1-bit input: Carry-in
            D              => "000000000000000000000000000", -- 27-bit input: D data 
            
            -- Reset/Clock Enable inputs: Reset/Clock Enable Inputs
            CEA1           => '1',            -- 1-bit input: Clock enable for 1st stage AREG
            CEA2           => '1',            -- 1-bit input: Clock enable for 2nd stage AREG
            CEAD           => '1',            -- 1-bit input: Clock enable for ADREG
            CEALUMODE      => '1',            -- 1-bit input: Clock enable for ALUMODE
            CEB1           => '1',            -- 1-bit input: Clock enable for 1st stage BREG
            CEB2           => '1',            -- 1-bit input: Clock enable for 2nd stage BREG
            CEC            => '1',            -- 1-bit input: Clock enable for CREG
            CECARRYIN      => '1',            -- 1-bit input: Clock enable for CARRYINREG
            CECTRL         => '1',            -- 1-bit input: Clock enable for OPMODEREG and CARRYINSELREG
            CED            => '1',            -- 1-bit input: Clock enable for DREG
            CEINMODE       => '1',            -- 1-bit input: Clock enable for INMODEREG
            CEM            => '1',            -- 1-bit input: Clock enable for MREG
            CEP            => '1',            -- 1-bit input: Clock enable for PREG
            RSTA           => '0',            -- 1-bit input: Reset for AREG
            RSTALLCARRYIN  => '0',            -- 1-bit input: Reset for CARRYINREG
            RSTALUMODE     => '0',            -- 1-bit input: Reset for ALUMODEREG
            RSTB           => '0',            -- 1-bit input: Reset for BREG
            RSTC           => '0',            -- 1-bit input: Reset for CREG
            RSTCTRL        => '0',            -- 1-bit input: Reset for OPMODEREG and CARRYINSELREG
            RSTD           => '0',            -- 1-bit input: Reset for DREG and ADREG
            RSTINMODE      => '0',            -- 1-bit input: Reset for INMODEREG
            RSTM           => '0',            -- 1-bit input: Reset for MREG
            RSTP           => '0'
        );

    
    -- We can't infer the overflow/underflow detection, so we'll manually instantiate the DSPs
    -- we'll also do this separately rather than in a loop so that we can easily control the cascade behavior
    -- and again there are only two and likely never more, so i still do not give a hoot
    DSP_re_inst : DSP48E2
        generic map (
            -- Feature Control Attributes: Data Path Selection
            AMULTSEL                  => "AD",             -- Selects A input to multiplier (A, AD)
            A_INPUT                   => "DIRECT",        -- Selects A input source, "DIRECT" (A port) or "CASCADE" (ACIN port)
            BMULTSEL                  => "B",             -- Selects B input to multiplier (AD, B)
            B_INPUT                   => "DIRECT",        -- Selects B input source, "DIRECT" (B port) or "CASCADE" (BCIN port)
            PREADDINSEL               => "A",             -- Selects input to pre-adder (A, B)
            RND                       => X"000000000000", -- Rounding Constant
            USE_MULT                  => "MULTIPLY",          -- Select multiplier usage (DYNAMIC, MULTIPLY, NONE)
            USE_SIMD                  => "ONE48",         -- SIMD selection (FOUR12, ONE48, TWO24)
            USE_WIDEXOR               => "FALSE",         -- Use the Wide XOR function (FALSE, TRUE)
            XORSIMD                   => "XOR24_48_96",   -- Mode of operation for the Wide XOR (XOR12, XOR24_48_96)

            -- Pattern Detector Attributes: Pattern Detection Configuration
            AUTORESET_PATDET          => "NO_RESET",      -- NO_RESET, RESET_MATCH, RESET_NOT_MATCH
            AUTORESET_PRIORITY        => "RESET",         -- Priority of AUTORESET vs. CEP (CEP, RESET).
            MASK                      => "0011" & X"FFFFFFFFFFF", -- 48-bit mask value for pattern detect (1=ignore) (configured for underflow/overflow detection)
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
            PCOUT          => dsp_re_pcout,            -- 48-bit output: Cascade output
            
            -- Control outputs: Control Inputs/Status Bits
            OVERFLOW       => errors(0),                    -- 1-bit output: Overflow in add/acc
            PATTERNBDETECT => open,                    -- 1-bit output: Pattern bar detect
            PATTERNDETECT  => open,    -- 1-bit output: Pattern detect
            UNDERFLOW      => errors(1),                    -- 1-bit output: Underflow in add/acc
            
            -- Data outputs: Data Ports
            CARRYOUT       => open,                    -- 4-bit output: Carry
            P              => dsp_re_output,                -- 48-bit output: Primary data
            XOROUT         => open,                    -- 8-bit output: XOR data
            
            -- Cascade inputs: Cascade Ports
            ACIN           => "000000000000000000000000000000",  -- 30-bit input: A cascade data
            BCIN           => "000000000000000000",              -- 18-bit input: B cascade
            CARRYCASCIN    => '0',                     -- 1-bit input: Cascade carry
            MULTSIGNIN     => '0',                     -- 1-bit input: Multiplier sign cascade
            PCIN           => counter_pcout,             -- 48-bit input: P cascade
            
            -- Control inputs: Control Inputs/Status Bits
            ALUMODE        => dsp_cfg_reg_dd(3 downto 0),  -- Z+X+W+Y+CIN
            CARRYINSEL     => "000",                       -- 3-bit input: Carry select
            CLK            => clk,                         -- 1-bit input: Clock
            INMODE         => "10101",                     -- 5-bit input: INMODE control
            OPMODE         => dsp_cfg_reg_dd(12 downto 4), -- W = P, X = 0, Y = 0, Z = 0
            
            -- Data inputs: Data Ports
            A              => data_in_re_narrowed_se,   -- 30-bit input: A data
            B              => dsp_b_re_reg,    -- 18-bit input: B data
            C              => dsp_c_re_reg,                  -- 48-bit input: C data
            CARRYIN        => dsp_cfg_reg_dd(13),            -- 1-bit input: Carry-in
            D              => dsp_d_re_reg, -- 27-bit input: D data 
            
            -- Reset/Clock Enable inputs: Reset/Clock Enable Inputs
            CEA1           => '1',            -- 1-bit input: Clock enable for 1st stage AREG
            CEA2           => '1',            -- 1-bit input: Clock enable for 2nd stage AREG
            CEAD           => '1',            -- 1-bit input: Clock enable for ADREG
            CEALUMODE      => '1',            -- 1-bit input: Clock enable for ALUMODE
            CEB1           => '1',            -- 1-bit input: Clock enable for 1st stage BREG
            CEB2           => '1',            -- 1-bit input: Clock enable for 2nd stage BREG
            CEC            => '1',            -- 1-bit input: Clock enable for CREG
            CECARRYIN      => '1',            -- 1-bit input: Clock enable for CARRYINREG
            CECTRL         => '1',            -- 1-bit input: Clock enable for OPMODEREG and CARRYINSELREG
            CED            => '1',            -- 1-bit input: Clock enable for DREG
            CEINMODE       => '1',            -- 1-bit input: Clock enable for INMODEREG
            CEM            => '1',            -- 1-bit input: Clock enable for MREG
            CEP            => '1',            -- 1-bit input: Clock enable for PREG
            RSTA           => '0',            -- 1-bit input: Reset for AREG
            RSTALLCARRYIN  => '0',            -- 1-bit input: Reset for CARRYINREG
            RSTALUMODE     => '0',            -- 1-bit input: Reset for ALUMODEREG
            RSTB           => '0',            -- 1-bit input: Reset for BREG
            RSTC           => '0',            -- 1-bit input: Reset for CREG
            RSTCTRL        => '0',            -- 1-bit input: Reset for OPMODEREG and CARRYINSELREG
            RSTD           => '0',            -- 1-bit input: Reset for DREG and ADREG
            RSTINMODE      => '0',            -- 1-bit input: Reset for INMODEREG
            RSTM           => '0',            -- 1-bit input: Reset for MREG
            RSTP           => '0'
        );

    DSP_im_inst : DSP48E2
        generic map (
            -- Feature Control Attributes: Data Path Selection
            AMULTSEL                  => "AD",             -- Selects A input to multiplier (A, AD)
            A_INPUT                   => "DIRECT",        -- Selects A input source, "DIRECT" (A port) or "CASCADE" (ACIN port)
            BMULTSEL                  => "B",             -- Selects B input to multiplier (AD, B)
            B_INPUT                   => "DIRECT",        -- Selects B input source, "DIRECT" (B port) or "CASCADE" (BCIN port)
            PREADDINSEL               => "A",             -- Selects input to pre-adder (A, B)
            RND                       => X"000000000000", -- Rounding Constant
            USE_MULT                  => "MULTIPLY",          -- Select multiplier usage (DYNAMIC, MULTIPLY, NONE)
            USE_SIMD                  => "ONE48",         -- SIMD selection (FOUR12, ONE48, TWO24)
            USE_WIDEXOR               => "FALSE",         -- Use the Wide XOR function (FALSE, TRUE)
            XORSIMD                   => "XOR24_48_96",   -- Mode of operation for the Wide XOR (XOR12, XOR24_48_96)

            -- Pattern Detector Attributes: Pattern Detection Configuration
            AUTORESET_PATDET          => "NO_RESET",      -- NO_RESET, RESET_MATCH, RESET_NOT_MATCH
            AUTORESET_PRIORITY        => "RESET",         -- Priority of AUTORESET vs. CEP (CEP, RESET).
            MASK                      => "0011" & X"FFFFFFFFFFF", -- 48-bit mask value for pattern detect (1=ignore) (configured for underflow/overflow detection)
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
            PCOUT          => open,            -- 48-bit output: Cascade output
            
            -- Control outputs: Control Inputs/Status Bits
            OVERFLOW       => errors(2),                    -- 1-bit output: Overflow in add/acc
            PATTERNBDETECT => open,                    -- 1-bit output: Pattern bar detect
            PATTERNDETECT  => open,    -- 1-bit output: Pattern detect
            UNDERFLOW      => errors(3),                    -- 1-bit output: Underflow in add/acc
            
            -- Data outputs: Data Ports
            CARRYOUT       => open,                    -- 4-bit output: Carry
            P              => dsp_im_output,                -- 48-bit output: Primary data
            XOROUT         => open,                    -- 8-bit output: XOR data
            
            -- Cascade inputs: Cascade Ports
            ACIN           => "000000000000000000000000000000",  -- 30-bit input: A cascade data
            BCIN           => "000000000000000000",              -- 18-bit input: B cascade
            CARRYCASCIN    => '0',                     -- 1-bit input: Cascade carry
            MULTSIGNIN     => '0',                     -- 1-bit input: Multiplier sign cascade
            PCIN           => dsp_re_pcout,             -- 48-bit input: P cascade
            
            -- Control inputs: Control Inputs/Status Bits
            ALUMODE        => dsp_cfg_reg_dd(3 downto 0),  -- Z+X+W+Y+CIN
            CARRYINSEL     => "000",                       -- 3-bit input: Carry select
            CLK            => clk,                         -- 1-bit input: Clock
            INMODE         => "10101",                     -- 5-bit input: INMODE control
            OPMODE         => dsp_cfg_reg_dd(12 downto 4), -- W = P, X = 0, Y = 0, Z = 0
            
            -- Data inputs: Data Ports
            A              => data_in_im_narrowed_se,   -- 30-bit input: A data
            B              => dsp_b_im_reg,    -- 18-bit input: B data
            C              => dsp_c_im_reg,                  -- 48-bit input: C data
            CARRYIN        => dsp_cfg_reg_dd(13),            -- 1-bit input: Carry-in
            D              => dsp_d_im_reg, -- 27-bit input: D data 
            
            -- Reset/Clock Enable inputs: Reset/Clock Enable Inputs
            CEA1           => '1',            -- 1-bit input: Clock enable for 1st stage AREG
            CEA2           => '1',            -- 1-bit input: Clock enable for 2nd stage AREG
            CEAD           => '1',            -- 1-bit input: Clock enable for ADREG
            CEALUMODE      => '1',            -- 1-bit input: Clock enable for ALUMODE
            CEB1           => '1',            -- 1-bit input: Clock enable for 1st stage BREG
            CEB2           => '1',            -- 1-bit input: Clock enable for 2nd stage BREG
            CEC            => '1',            -- 1-bit input: Clock enable for CREG
            CECARRYIN      => '1',            -- 1-bit input: Clock enable for CARRYINREG
            CECTRL         => '1',            -- 1-bit input: Clock enable for OPMODEREG and CARRYINSELREG
            CED            => '1',            -- 1-bit input: Clock enable for DREG
            CEINMODE       => '1',            -- 1-bit input: Clock enable for INMODEREG
            CEM            => '1',            -- 1-bit input: Clock enable for MREG
            CEP            => '1',            -- 1-bit input: Clock enable for PREG
            RSTA           => '0',            -- 1-bit input: Reset for AREG
            RSTALLCARRYIN  => '0',            -- 1-bit input: Reset for CARRYINREG
            RSTALUMODE     => '0',            -- 1-bit input: Reset for ALUMODEREG
            RSTB           => '0',            -- 1-bit input: Reset for BREG
            RSTC           => '0',            -- 1-bit input: Reset for CREG
            RSTCTRL        => '0',            -- 1-bit input: Reset for OPMODEREG and CARRYINSELREG
            RSTD           => '0',            -- 1-bit input: Reset for DREG and ADREG
            RSTINMODE      => '0',            -- 1-bit input: Reset for INMODEREG
            RSTM           => '0',            -- 1-bit input: Reset for MREG
            RSTP           => '0'
        );

    -- Pipeline the counter match signal
    -- We need to pipeling this because counter match 
    -- indicates when the last data word of a counter period is presented at the A input of the DSP.
    -- Therefore, we have the following sequence of events:
    -- 1. Counter match goes high and data word is presented at DSP input
    -- 2. A gets loaded with data word
    -- 3. AD register gets loaded with pre-add result
    -- 4. M register gets loaded with product result
    -- 5. P register gets loaded with ALU result
    -- hence, 4 stages of pipelining are needed
    dsp_output_valid_proc: process(clk) begin
        if rising_edge(clk) then
            dsp_output_valid_ppp <= data_in_narrowed_valid and (counter_match or data_in_narrowed_last);
            dsp_output_valid_pp  <= dsp_output_valid_ppp;
            dsp_output_valid_p   <= dsp_output_valid_pp;
            dsp_output_valid     <= dsp_output_valid_p;

            dsp_output_last_ppp <= data_in_narrowed_valid and data_in_narrowed_last;
            dsp_output_last_pp  <= dsp_output_last_ppp;
            dsp_output_last_p   <= dsp_output_last_pp;
            dsp_output_last     <= dsp_output_last_p;
        end if;
    end process dsp_output_valid_proc;
    
    -- Finally, create and connect the output FIFO
    output_fifo: entity work.acadia_backpressure_fifo
        generic map (
            WORD_WIDTH   => 32,
            INPUT_WORDS  => 2,
            OUTPUT_WORDS => 2,
            INPUT_DEPTH  => DATA_OUTPUT_FIFO_DEPTH,
            MEMORY_TYPE  => DATA_OUTPUT_FIFO_PRIMITIVE,
            ASYNCHRONOUS => DATA_OUTPUT_FIFO_ASYNCHRONOUS,
            MONITOR_SYNC => true  -- Set to true if monitor_clk is synchronous to signal_in_clk
        )
        port map (
            signal_in_clk    => clk,
            signal_in_rst    => rst,

            -- A port for monitoring the status of the FIFO and resetting it
            monitor_clk      => clk,
            monitor_rst      => rst,
            monitor_overflow => errors(4),
            monitor_misalignment => open,
            
            signal_in_tdata(63 downto 32)  => dsp_im_output(46 downto 15),
            signal_in_tdata(31 downto 0)   => dsp_re_output(46 downto 15),
            signal_in_tvalid => dsp_output_valid,
            signal_in_tlast  => dsp_output_last,
            
            m_axis_aclk      => data_out_aclk,
            m_axis_tdata     => data_out_tdata,
            m_axis_tvalid    => data_out_tvalid,
            m_axis_tready    => data_out_tready,
            m_axis_tlast     => data_out_tlast,
            m_axis_tkeep     => data_out_tkeep
        );
end rtl;
