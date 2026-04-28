----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/25/2022 11:52:49 PM
-- Design Name: acadia
-- Module Name: acadia_stream_cmacc - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: 
--     A module which multiplies a continuous incoming data stream
--     against a kernel stored in a BRAM. Input streams are 
--     interpreted as packed 32-bit complex numbers (with two 
--     16-bit quadratures) and multiplied against a second stream
--     of complex numbers driven by a dedicated block RAM. The
--     result is accumulated internally as a 96-bit complex number
--     and exposed to the sequencer via a register. The status 
--     signals allow fast access to the completion state of the 
--     accumulator as well as the most significant bit of the 
--     accumulator value. By loading the accumulator with an 
--     initial offset, one can threshold the accumulator value 
--     against an arbitrary value.
--     
--     This module uses the following registers:
--         Address 0: Control/Status
--             Bits 15-0 (R): Kernel Memory Pointer
--                 These bits contain the current value of the kernel memory pointer.
--
--             Bit 16 (W): Kernel Memory Pointer Load
--                  Writing 1 to this bit loads the kernel memory pointer with the value stored in the
--                  kernel memory start address register.
--
--             Bit 17 (R): Accumulator Range Error
--                 The accumulator has underflowed or overflowed. After being set, this signal is latched
--                 until the module is reset.
--
--             Bit 19-18 (RW): Accumulator Update Mode
--                 When 00, the accumulator never updates, and computes input+preload for every sample.
--                 When 01, the accumulator loads input+preload for the first input sample after arm_preload = '1', 
--                          and accum+input for every following sample.
--                 When 10, the accumulator loads input+preload for the first point of each kernel, 
--                          and accum+input for every following point.
--                 When 11, the accumulator never updates, and computes input+preload for every sample.
--
--             Bits 21-20 (RW): Accumulator Latch Register Write Mode
--                 When 00, nothing is latched.
--                 When 01, the latch is written only after the last input value.
--                 When 10, the latch is written when the kernel completes.
--                 When 11, the latch is written after processing every valid input.
--             
--             Bit 22 (RW): Accumulator Latch Register Valid
--                 When read as 1, updated accumulation results are available at the latch register. 
--                 Writing 1 to this bit clears it and writing 0 has no effect. The latch is only updated when this bit is 0.
--                 Writing to it takes priority over any internal logic that may attempt to simultaneously update it.
--
--             Bit 23 (R): Accumulator Latch Real MSB
--                 The most significant bit of the current real latch value.
--
--             Bit 24 (R): Accumulator Latch Imaginary MSB
--                 The most significant bit of the current imaginary latch value.
--
--             Bit 25 (RW): Output Data Selection
--                When 0, the lower 32 bits of the accumulator value are selected for output to both the latch and the stream port.
--                When 1, the upper 32 bits of the accumulator are selected.                
--
--             Bit 26 (W): Arm Preload
--                 When this is set to 1 and accumulator_mode = "01", the next valid sample to appear at the accumulator input is
--                 considered the "first" sample, so the accumulator will load input+preload. This bit is automatically cleared.
--                  This bit has no effect for all other accumulator modes.
--
--             Bits 28-27 (RW): Stream port write mode
--                 When 00, nothing is written to the stream port.
--                 When 01, the stream port is written only after the last input value.
--                 When 10, the stream port is written each time the kernel completes.
--                 When 11, the stream port is written after processing every valid input.
--                 
--             Bit 29 (R): Stream port FIFO Overflow
--                 Returns 1 if the FIFO has overflowed. 
--
--             Bit 30 (RW): Stream port FIFO Reset
--                 Write 1 to this register to trigger a reset of the stream FIFO. 
--                 Reading from this register returns 1 if the FIFO is still in reset 
--                 and is unable to be used.
--
--             Bit 31 (W): Internal reset
--                 Writing 1 to this register triggers an internal reset of the module.
--                 Reading from this register returns 1 if the module is still in reset 
--                 and is unable to be used.
--
--         Address 1: 
--             Bits 15-0 (RW): Kernel Memory Address Start
--                 The first address of the kernel in memory.
--             Bits 31-16 (RW): Kernel Memory Address End
--                 The final address of the kernel in memory.
--
--         Address 2: Accumulator Latch Real
--             Bits 31-0 (R): This register contains the value of the 
--             real accumulator latch.
--             
--         Address 3: Accumulator Latch Imaginary
--             Bits 31-0 (R): Identical to address 0, but for the imaginary 
--             accumulator.
--
--         Address 4: Accumulator Real Preload
--             Writing to this address loads the upper 32 bits of the real accumulator preload register
--             with the provided value. The lower bits are cleared.
--             Reading from this address returns the upper 32 bits of the 
--             real accumulator preload register.
--             
--         Address 5: Accumulator Imaginary Preload
--             Identical to address 4, but for the imaginary 
--             accumulator.
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

library xpm;
use xpm.vcomponents.all;

entity acadia_stream_cmacc is
    generic (
        -- Number of quadratures pairs present in the input must be <= 4
        INPUT_WORDS                   : positive := 4;
        DATA_OUTPUT_FIFO_DEPTH        : positive := 1024;
        DATA_OUTPUT_FIFO_PRIMITIVE    : string   := "auto";
        DATA_OUTPUT_FIFO_ASYNCHRONOUS : boolean  := true;

        -- Kernel memory settings
        KERNEL_MEMORY_DEPTH                       : positive := 2048; -- memory depth in samples
        LOG2_KERNEL_MEMORY_DEPTH                  : positive := 11;
        KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH    : positive := 32;
        KERNEL_MEMORY_EXTERNAL_PORT_ADDRESS_WIDTH : positive := 11;
        KERNEL_MEMORY_EXTERNAL_PORT_LATENCY       : positive := 2;
        KERNEL_MEMORY_CLOCK_MODE                  : string := "independent";
        KERNEL_MEMORY_PRIMITIVE                   : string := "auto"
    );
    port (
        clk                : in  std_logic;
        nrst               : in  std_logic;

        -- Signal input
        data_in_tdata      : in  std_logic_vector((INPUT_WORDS*32) - 1 downto 0);
        data_in_tvalid     : in  std_logic;
        data_in_tready     : out std_logic;
        data_in_tlast      : in  std_logic;
        
        -- Kernel memory interface
        kernel_memory_din  : in  std_logic_vector(KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH-1 downto 0);
        kernel_memory_dout : out std_logic_vector(KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH-1 downto 0);
        kernel_memory_addr : in  std_logic_vector(KERNEL_MEMORY_EXTERNAL_PORT_ADDRESS_WIDTH-1 downto 0);
        kernel_memory_we   : in  std_logic_vector((KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH/8)-1 downto 0);
        kernel_memory_en   : in  std_logic;
        kernel_memory_clk  : in  std_logic;
            
        -- Output data stream
        data_out_aclk   : in  std_logic;
        data_out_tdata  : out std_logic_vector(63 downto 0);
        data_out_tvalid : out std_logic;
        data_out_tready : in  std_logic;
        data_out_tlast  : out std_logic;
        data_out_tkeep  : out std_logic_vector(7 downto 0);

        -- Register access (synchronous to clk)
        registers_mosi  : in  std_logic_vector(31 downto 0);
        registers_miso  : out std_logic_vector(31 downto 0);
        registers_addr  : in  std_logic_vector(31 downto 0);
        registers_we    : in  std_logic;
        registers_en    : in  std_logic
    );
    
    attribute USE_DSP : string;
end acadia_stream_cmacc;

architecture rtl of acadia_stream_cmacc is
    
    attribute USE_DSP of rtl : architecture is "YES";
    
    ATTRIBUTE X_INTERFACE_INFO      : STRING;
    ATTRIBUTE X_INTERFACE_MODE      : STRING;
    ATTRIBUTE X_INTERFACE_PARAMETER : STRING;

    ATTRIBUTE X_INTERFACE_PARAMETER of clk: SIGNAL is "ASSOCIATED_BUSIF data_in:registers";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TDATA";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TLAST";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TVALID";
    ATTRIBUTE X_INTERFACE_INFO of data_in_tready : SIGNAL is "xilinx.com:interface:axis:1.0 data_in TREADY";
    ATTRIBUTE X_INTERFACE_PARAMETER of data_in_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 0,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES " & positive'image(INPUT_WORDS*4/8);
    
    ATTRIBUTE X_INTERFACE_PARAMETER of kernel_memory_clk: SIGNAL is "ASSOCIATED_BUSIF kernel_memory";
    ATTRIBUTE X_INTERFACE_INFO of kernel_memory_dout: SIGNAL is "xilinx.com:interface:bram:1.0 kernel_memory DOUT";
    ATTRIBUTE X_INTERFACE_INFO of kernel_memory_din : SIGNAL is "xilinx.com:interface:bram:1.0 kernel_memory DIN";
    ATTRIBUTE X_INTERFACE_INFO of kernel_memory_addr: SIGNAL is "xilinx.com:interface:bram:1.0 kernel_memory ADDR";
    ATTRIBUTE X_INTERFACE_INFO of kernel_memory_we  : SIGNAL is "xilinx.com:interface:bram:1.0 kernel_memory WE";
    ATTRIBUTE X_INTERFACE_INFO of kernel_memory_clk : SIGNAL is "xilinx.com:interface:bram:1.0 kernel_memory CLK";
    ATTRIBUTE X_INTERFACE_INFO of kernel_memory_en  : SIGNAL is "xilinx.com:interface:bram:1.0 kernel_memory EN";
    
    ATTRIBUTE X_INTERFACE_PARAMETER of data_out_aclk: SIGNAL is "ASSOCIATED_BUSIF data_out";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TDATA";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TLAST";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TVALID";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tready : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TREADY";
    ATTRIBUTE X_INTERFACE_INFO of data_out_tkeep  : SIGNAL is "xilinx.com:interface:axis:1.0 data_out TKEEP";
    ATTRIBUTE X_INTERFACE_MODE of data_out_tdata  : SIGNAL is "Master";
    ATTRIBUTE X_INTERFACE_PARAMETER of data_out_tdata: SIGNAL is "HAS_TLAST 1,HAS_TKEEP 1,HAS_TSTRB 0,HAS_TREADY 1,TUSER_WIDTH 0,TID_WIDTH 0,TDEST_WIDTH 0,TDATA_NUM_BYTES 8";
    
    ATTRIBUTE X_INTERFACE_INFO of registers_mosi: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 registers DIN";
    ATTRIBUTE X_INTERFACE_INFO of registers_miso: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 registers DOUT";
    ATTRIBUTE X_INTERFACE_INFO of registers_addr: SIGNAL is "xilinx.com:interface:bram_rtl:1.0 registers ADDR";
    ATTRIBUTE X_INTERFACE_INFO of registers_we  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 registers WE";
    ATTRIBUTE X_INTERFACE_INFO of registers_en  : SIGNAL is "xilinx.com:interface:bram_rtl:1.0 registers EN";

    -- Input quadratures
    signal a_re : signed(17 downto 0);
    signal a_im : signed(17 downto 0);
    signal b_re : signed(15 downto 0);
    signal b_im : signed(15 downto 0);

    -- Accumulator components
    signal accumulator_re : signed(46 downto 0);
    signal accumulator_im : signed(46 downto 0);
    signal accumulator_re_preload : signed(46 downto 0);
    signal accumulator_im_preload : signed(46 downto 0);
    
    -- Products
    signal a_re_b_re : signed(a_re'length + b_re'length - 1 downto 0);
    signal a_im_b_re : signed(a_im'length + b_re'length - 1 downto 0);
    signal a_re_b_im : signed(a_re'length + b_im'length - 1 downto 0);
    signal a_im_b_im : signed(a_im'length + b_im'length - 1 downto 0);

    -- Sign extended products for accumulator
    signal a_re_b_re_sign : signed(accumulator_im'high - a_re_b_re'length downto 0);
    signal a_im_b_re_sign : signed(accumulator_re'high - a_im_b_re'length downto 0);
    signal a_re_b_im_sign : signed(accumulator_re'high - a_re_b_im'length downto 0);
    signal a_im_b_im_sign : signed(accumulator_im'high - a_im_b_im'length downto 0);

    -- Complete product
    signal full_product_re : signed(accumulator_re'high downto 0);
    signal full_product_im : signed(accumulator_im'high downto 0);
    
    -- Kernel memory access signals
    signal kernel_memory_pointer_start : std_logic_vector(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0);
    signal kernel_memory_pointer_end   : std_logic_vector(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0);
    signal kernel_memory_pointer       : std_logic_vector(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0);
    signal kernel_memory_pointer_load  : std_logic;
    signal kernel_memory_data          : std_logic_vector(31 downto 0);

    -- We'll also have some kernel "first" signals. 
    -- Note that this is NOT related to the "last" signals from the input;
    -- the "last" signals are delayed/pipelined versions of the "last" signal of the input.
    -- In contrast, these signals indicate that the data at a given stage in the pipeline results
    -- from the first sample of the kernel. Because the kernel pointer wraps when it reaches the
    -- end, you could get multiple "first" pulses in a long stream. This is particularly useful
    -- when using the CMACC for decimating a stream, since the accumulator can be reset using
    -- the "first" signal. 
    signal kernel_pointer_first : std_logic;
    signal kernel_data_first    : std_logic;
    signal partial_product_kernel_first : std_logic;
    signal full_product_kernel_first : std_logic;
    signal accumulator_kernel_first : std_logic;

    -- We'll also have kernel "last" signals to indicate that the sample being processed is the last of
    -- a given kernel iteration, to be used for decimation mode
    signal kernel_pointer_last : std_logic;
    signal kernel_data_last    : std_logic;
    signal partial_product_kernel_last : std_logic;
    signal full_product_kernel_last : std_logic;
    signal accumulator_kernel_last : std_logic;
    
    -- Reset and FIFO status signals
    signal rst_int   : std_logic;
    signal fifo_rst  : std_logic;
    signal fifo_rst_busy : std_logic;
    signal fifo_overflow : std_logic;

    -- Accumulator update control
    signal accumulator_mode : std_logic_vector(1 downto 0);
    signal arm_preload : std_logic;

    -- Upper/lower output data select
    signal output_select   : std_logic;

    -- Status signals
    signal range_err       : std_logic;

    -- Output data
    signal stream_output_mode  : std_logic_vector(1 downto 0);
    signal stream_output_data  : std_logic_vector(63 downto 0);
    signal stream_output_valid : std_logic;
    signal stream_output_last  : std_logic;

    -- Latch data
    signal latch_output_mode  : std_logic_vector(1 downto 0);
    signal latch_output_data  : std_logic_vector(63 downto 0);
    signal latch_output_valid : std_logic;

    -- Pipelined flags from input
    signal input_valid          : std_logic;
    signal input_last           : std_logic;
    signal partial_product_valid        : std_logic;
    signal partial_product_last         : std_logic;
    signal full_product_valid        : std_logic;
    signal full_product_last         : std_logic;
    signal accumulator_valid    : std_logic;
    signal accumulator_last : std_logic;

    -- A few aliases for saving verbosity
    alias accumulator_re_upper : signed(31 downto 0) is accumulator_re(accumulator_re'high downto accumulator_re'high-31);
    alias accumulator_im_upper : signed(31 downto 0) is accumulator_im(accumulator_im'high downto accumulator_im'high-31);
    alias accumulator_re_lower : signed(31 downto 0) is accumulator_re(31 downto 0);
    alias accumulator_im_lower : signed(31 downto 0) is accumulator_im(31 downto 0);
    alias accumulator_re_preload_upper : signed(31 downto 0) is accumulator_re_preload(accumulator_re_preload'high downto accumulator_re_preload'high-31);
    alias accumulator_im_preload_upper : signed(31 downto 0) is accumulator_im_preload(accumulator_im_preload'high downto accumulator_im_preload'high-31);
    alias accumulator_re_preload_lower : signed(31 downto 0) is accumulator_re_preload(31 downto 0);
    alias accumulator_im_preload_lower : signed(31 downto 0) is accumulator_im_preload(31 downto 0);

    -- Constants for register addresses
    constant REG_ADDR_CTRL_STAT      : std_logic_vector(2 downto 0) := "000";
    constant REG_ADDR_KERNEL_ADDRESS : std_logic_vector(2 downto 0) := "001";
    constant REG_ADDR_LATCH_RE       : std_logic_vector(2 downto 0) := "010";
    constant REG_ADDR_LATCH_IM       : std_logic_vector(2 downto 0) := "011";
    constant REG_ADDR_PRELOAD_RE     : std_logic_vector(2 downto 0) := "100";
    constant REG_ADDR_PRELOAD_IM     : std_logic_vector(2 downto 0) := "101";
begin

    -- Let a register write create a single-cycle pulse for the reset bits
    rst_proc: process(clk) begin
        if rising_edge(clk) then
            if(nrst = '0') then
                fifo_rst <= '1';
                rst_int <= '1';
            elsif(registers_en = '1' and registers_we = '1' and registers_addr(2 downto 0) = REG_ADDR_CTRL_STAT) then
                fifo_rst <= registers_mosi(30);
                rst_int  <= registers_mosi(31);
            else
                fifo_rst <= '0';
                rst_int <= '0';
            end if;
        end if;
    end process rst_proc;


    -- Create the kernel memory
    -- Port A will be used internally, port B will be used for external access
    kernel_memory : xpm_memory_tdpram
        generic map (
            ADDR_WIDTH_A        => LOG2_KERNEL_MEMORY_DEPTH,
            ADDR_WIDTH_B        => KERNEL_MEMORY_EXTERNAL_PORT_ADDRESS_WIDTH,
            AUTO_SLEEP_TIME     => 0,
            BYTE_WRITE_WIDTH_A  => 8,
            BYTE_WRITE_WIDTH_B  => 8,
            CASCADE_HEIGHT      => 0, 
            CLOCKING_MODE       => KERNEL_MEMORY_CLOCK_MODE,
            ECC_MODE            => "no_ecc",
            MEMORY_INIT_FILE    => "none",
            MEMORY_INIT_PARAM   => "0", 
            MEMORY_OPTIMIZATION => "true",
            MEMORY_PRIMITIVE    => KERNEL_MEMORY_PRIMITIVE,
            MEMORY_SIZE         => KERNEL_MEMORY_DEPTH*32, 
            MESSAGE_CONTROL     => 0,
            READ_DATA_WIDTH_A   => 32,
            READ_DATA_WIDTH_B   => KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH,
            READ_LATENCY_A      => 1,  
            READ_LATENCY_B      => KERNEL_MEMORY_EXTERNAL_PORT_LATENCY, 
            READ_RESET_VALUE_A  => "0", 
            READ_RESET_VALUE_B  => "0",
            RST_MODE_A          => "SYNC",
            RST_MODE_B          => "SYNC",
            SIM_ASSERT_CHK      => 1, 
            USE_EMBEDDED_CONSTRAINT => 0,
            USE_MEM_INIT        => 1,
            WAKEUP_TIME         => "disable_sleep",
            WRITE_DATA_WIDTH_A  => 32,
            WRITE_DATA_WIDTH_B  => KERNEL_MEMORY_EXTERNAL_PORT_DATA_WIDTH, 
            WRITE_MODE_A        => "write_first", 
            WRITE_MODE_B        => "write_first"
        )
        port map (
            clka  => clk,
            addra => kernel_memory_pointer,
            douta => kernel_memory_data,
            dina => x"00000000",
            wea => x"0",
            ena => '1',
            rsta => '0',
            regcea => '1',

            clkb => kernel_memory_clk,
            addrb => kernel_memory_addr,
            dinb => kernel_memory_din,
            doutb => kernel_memory_dout,
            web => kernel_memory_we,
            enb => kernel_memory_en,
            rstb => '0',
            regceb => '1',

            dbiterra => open,
            dbiterrb => open,
            sbiterra => open,
            sbiterrb => open,
            injectdbiterra => '0',
            injectdbiterrb => '0',
            injectsbiterra => '0',
            injectsbiterrb => '0',
            sleep => '0'
        );

    -- Process to manage the kernel memory pointer start and end addresses
    kernel_memory_pointer_load_proc: process(clk) begin
        if rising_edge(clk) then
            if(registers_en = '1' and registers_we = '1' and registers_addr(2 downto 0) = REG_ADDR_CTRL_STAT) then
                kernel_memory_pointer_load <= registers_mosi(16);
            else
                kernel_memory_pointer_load <= '0';
            end if;
        end if;
    end process kernel_memory_pointer_load_proc;

    kernel_pointer_last <= '1' when kernel_memory_pointer = kernel_memory_pointer_end else '0';

    -- Process to manage the kernel memory pointer
    kernel_memory_pointer_proc: process(clk) begin
        if rising_edge(clk) then
            if(kernel_memory_pointer_load = '1') then
                kernel_memory_pointer <= kernel_memory_pointer_start;
                kernel_pointer_first <= '1';
            elsif(data_in_tvalid = '1') then
                if(kernel_pointer_last = '1') then
                    kernel_memory_pointer <= kernel_memory_pointer_start;
                    kernel_pointer_first <= '1';
                else
                    kernel_memory_pointer <= std_logic_vector(unsigned(kernel_memory_pointer) + 1);
                    kernel_pointer_first <= '0';
                end if;
            end if;
        end if;
    end process kernel_memory_pointer_proc;

    -- First stage: sum the individual components of the input signal

    -- We'll always accept data from the input
    data_in_tready <= '1';

    -- Alias the kernel memory output as quadrature values
    b_re  <= signed(kernel_memory_data(15 downto 0));
    b_im  <= signed(kernel_memory_data(31 downto 16));

    -- Data input pipelining
    -- To figure out how many pipeline stages are needed on the input
    -- data, we can "simulate" an example sequence of events:
    -- Time Kptr Kptrfrst Kmemout Data DVld
    -- 0    0           1 K(0)    X    0
    -- 1    0           1 K(0)    D(0) 1
    -- 2    1           0 K(0)    D(1) 1
    -- 3    2           0 K(1)    D(2) 1  
    -- 4    3           0 K(2)    X    0  
    -- 5    3           0 K(3)    D(3) 1
    -- 6    4           0 K(3)    D(4) 1
    -- 7    5           0 K(4)    D(5) 1
    --
    -- Therefore, one stage of pipelining should be sufficient. 
    -- We'll amortize the kernel memory read latency with the operation of narrowing the input signal; 
    -- that is, we want to sum all the words of the input, so given that we have at least one cycle
    -- to wait for the kernel sample to be read from memory, we'll use that time to synchronously
    -- sum the input words. We will also delay the "kernel first sample" signal by the same amount. 
    input_narrowing_proc: process(clk) 
       variable sum_re : signed(a_re'high downto 0); 
       variable sum_im : signed(a_im'high downto 0); 
    begin
        if rising_edge(clk) then
            -- Use variables and a loop to sum all the inputs
            sum_re := (others => '0');
            sum_im := (others => '0');
            sum_loop: for i in 0 to INPUT_WORDS-1 loop
                sum_re := sum_re + resize(signed(data_in_tdata((i*32) + 15 downto (i*32))), sum_re'length);
                sum_im := sum_im + resize(signed(data_in_tdata((i*32) + 31 downto (i*32) + 16)), sum_im'length);
            end loop sum_loop;

            -- Now update the outputs with the variables
            a_re   <= sum_re;
            a_im   <= sum_im;

            if(rst_int = '1') then
                input_valid <= '0';
                input_last <= '0';
                kernel_data_first <= '0';
                kernel_data_last <= '0';
            else
                input_valid <= data_in_tvalid;
                input_last  <= data_in_tlast;
                kernel_data_first <= kernel_pointer_first;
                kernel_data_last <= kernel_pointer_last;
            end if;
        end if;
    end process input_narrowing_proc;

    -- Second pipeline stage: multiplication
    -- Do this in one cycle and propagate through all of the valid/last/first flags
    product_proc: process(clk) begin
        if rising_edge(clk) then
            a_re_b_re <= a_re * b_re;
            a_im_b_re <= a_im * b_re;
            a_re_b_im <= a_re * b_im;
            a_im_b_im <= a_im * b_im;

            if(rst_int = '1') then
                partial_product_valid <= '0';
                partial_product_last <= '0';
                partial_product_kernel_first <= '0';
                partial_product_kernel_last <= '0';
            else
                partial_product_valid <= input_valid;
                partial_product_last  <= input_last;
                partial_product_kernel_first <= kernel_data_first;
                partial_product_kernel_last <= kernel_data_last;
            end if;
        end if;
    end process product_proc;

    -- Combine the partial products into a full product
    -- Arguably this should be another pipeline stage for better timing
    -- but given the low design speed and utilization we might be able to get away with
    -- making this addition combinational
    -- Sign extend products
    a_re_b_re_sign <= (others => a_re_b_re(a_re_b_re'high));
    a_im_b_re_sign <= (others => a_im_b_re(a_im_b_re'high));
    a_re_b_im_sign <= (others => a_re_b_im(a_re_b_im'high));
    a_im_b_im_sign <= (others => a_im_b_im(a_im_b_im'high));

    full_product_re <= (a_re_b_re_sign & a_re_b_re) - (a_im_b_im_sign & a_im_b_im);
    full_product_im <= (a_re_b_im_sign & a_re_b_im) + (a_im_b_re_sign & a_im_b_re);
    full_product_valid <= partial_product_valid;
    full_product_last <= partial_product_last;
    full_product_kernel_first <= partial_product_kernel_first;
    full_product_kernel_last <= partial_product_kernel_last;
            
    -- Third pipeline stage: accumulator
    accumulator_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst_int = '1') then
                accumulator_valid <= '0';
                accumulator_last <= '0';
                accumulator_kernel_first <= '0';
                accumulator_kernel_last <= '0';
            else
                accumulator_valid <= full_product_valid;
                accumulator_last <= full_product_last;
                accumulator_kernel_first <= full_product_kernel_first;
                accumulator_kernel_last <= full_product_kernel_last;
            end if;
            

            if(full_product_valid = '1') then
                if(accumulator_mode = "00" or accumulator_mode = "11") then
                    accumulator_re <= accumulator_re_preload + full_product_re;
                    accumulator_im <= accumulator_im_preload + full_product_im; 
                elsif(accumulator_mode = "01") then
                    if(arm_preload = '1') then
                        accumulator_re <= accumulator_re_preload + full_product_re;
                        accumulator_im <= accumulator_im_preload + full_product_im; 
                    else
                        accumulator_re <= accumulator_re + full_product_re;
                        accumulator_im <= accumulator_im + full_product_im; 
                    end if;
                elsif(accumulator_mode = "10") then
                    if(full_product_kernel_first = '1') then
                        accumulator_re <= accumulator_re_preload + full_product_re;
                        accumulator_im <= accumulator_im_preload + full_product_im; 
                    else
                        accumulator_re <= accumulator_re + full_product_re;
                        accumulator_im <= accumulator_im + full_product_im; 
                    end if;
                end if;
            end if;  
        end if;
    end process accumulator_proc;

    -- Stream accumulator values to the output port 
    stream_output_proc: process(clk) begin
        if rising_edge(clk) then

            -- Multiplex output data according to whether the upper or lower 32 bits are selected
            if(output_select = '1') then
                stream_output_data(31 downto 0)  <= std_logic_vector(accumulator_re_upper);
                stream_output_data(63 downto 32) <= std_logic_vector(accumulator_im_upper);
            else
                stream_output_data(31 downto 0)  <= std_logic_vector(accumulator_re_lower);
                stream_output_data(63 downto 32) <= std_logic_vector(accumulator_im_lower);
            end if;

            -- Multiplex output valid signals according to when we choose to write
            if(rst_int = '1') then
                stream_output_valid <= '0';
                stream_output_last  <= '0';
            else
                case stream_output_mode is
                    when "01" =>
                        stream_output_valid <= accumulator_valid and accumulator_last;
                    when "10" =>
                        stream_output_valid <= accumulator_valid and accumulator_kernel_last;
                    when "11" =>
                        stream_output_valid <= accumulator_valid;
                    when others =>
                        stream_output_valid <= '0';
                end case;

                -- The "last" signal is always derived from the input
                stream_output_last <= accumulator_last;
            end if;

            
        end if;
    end process stream_output_proc;

    -- Bus-accessible latch 
    latch_output_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst_int = '1') then
                latch_output_valid <= '0';
            elsif(registers_en = '1' and registers_we = '1' and registers_addr(2 downto 0) = REG_ADDR_CTRL_STAT) then
                -- Writing '1' to the latch valid bit clears it, 0 leaves it alone
                -- valid reg  new_valid
                -- 0     0    0
                -- 0     1    0
                -- 1     0    1
                -- 1     1    0
                -- In other words, the latch output is only valid if it already was and we're not clearing it
                latch_output_valid <= latch_output_valid and not registers_mosi(22);
            elsif(latch_output_valid = '0') then
                -- In constrast to the stream port, we only latch data if there isn't data currently latched.
                -- Multiplex output data according to whether the upper or lower 32 bits are selected
                if(output_select = '1') then
                    latch_output_data(31 downto 0)  <= std_logic_vector(accumulator_re_upper);
                    latch_output_data(63 downto 32) <= std_logic_vector(accumulator_im_upper);
                else
                    latch_output_data(31 downto 0)  <= std_logic_vector(accumulator_re_lower);
                    latch_output_data(63 downto 32) <= std_logic_vector(accumulator_im_lower);
                end if;

                -- Multiplex output valid signals according to when we choose to write
                case latch_output_mode is
                    when "01" =>
                        latch_output_valid <= accumulator_valid and accumulator_last;
                    when "10" =>
                        latch_output_valid <= accumulator_valid and accumulator_kernel_last;
                    when "11" =>
                        latch_output_valid <= accumulator_valid;
                    when others =>
                        latch_output_valid <= '0';
                end case;
            end if;

        end if;
    end process latch_output_proc;

    output_fifo: entity work.acadia_backpressure_fifo
        generic map (
            WORD_WIDTH   => 64,
            INPUT_WORDS  => 1,
            OUTPUT_WORDS => 1,
            INPUT_DEPTH  => DATA_OUTPUT_FIFO_DEPTH,
            MEMORY_TYPE  => DATA_OUTPUT_FIFO_PRIMITIVE,
            ASYNCHRONOUS => DATA_OUTPUT_FIFO_ASYNCHRONOUS
        )
        port map (
            clk      => clk,
            rst      => fifo_rst,
            rst_busy => fifo_rst_busy,

            -- A port for monitoring the status of the FIFO and resetting it
            overflow => fifo_overflow,
            output_misaligned => open,
            
            signal_in_tdata  => stream_output_data,
            signal_in_tvalid => stream_output_valid,
            signal_in_tlast  => stream_output_last,
            
            m_axis_aclk      => data_out_aclk,
            m_axis_tdata     => data_out_tdata,
            m_axis_tvalid    => data_out_tvalid,
            m_axis_tready    => data_out_tready,
            m_axis_tlast     => data_out_tlast,
            m_axis_tkeep     => data_out_tkeep
        );

    -- Register read interface
    registers_rd_proc: process(clk) begin
        if rising_edge(clk) then
            if(registers_addr(2 downto 0) = REG_ADDR_CTRL_STAT) then
                registers_miso(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0) <= kernel_memory_pointer;
                registers_miso(15 downto LOG2_KERNEL_MEMORY_DEPTH)  <= (others => '0');
                registers_miso(16)           <= '0';
                registers_miso(19 downto 18) <= accumulator_mode;
                registers_miso(21 downto 20) <= latch_output_mode;
                registers_miso(22)           <= latch_output_valid;
                registers_miso(23)           <= latch_output_data(31);
                registers_miso(24)           <= latch_output_data(63);
                registers_miso(25)           <= output_select;
                registers_miso(26)           <= arm_preload;
                registers_miso(28 downto 27) <= stream_output_mode;
                registers_miso(29)           <= fifo_overflow;
                registers_miso(30)           <= fifo_rst_busy;
                registers_miso(31)           <= fifo_rst_busy;
            elsif(registers_addr(2 downto 0) = REG_ADDR_KERNEL_ADDRESS) then
                registers_miso(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0)       <= kernel_memory_pointer_start;
                registers_miso(15 downto LOG2_KERNEL_MEMORY_DEPTH)        <= (others => '0');
                registers_miso(LOG2_KERNEL_MEMORY_DEPTH-1 + 16 downto 16) <= kernel_memory_pointer_end;
                registers_miso(31 downto LOG2_KERNEL_MEMORY_DEPTH + 16)   <= (others => '0');
            elsif(registers_addr(2 downto 0) = REG_ADDR_LATCH_RE) then
                registers_miso <= std_logic_vector(latch_output_data(31 downto 0));
            elsif(registers_addr(2 downto 0) = REG_ADDR_LATCH_IM) then
                registers_miso <= std_logic_vector(latch_output_data(63 downto 32));
            elsif(registers_addr(2 downto 0) = REG_ADDR_PRELOAD_RE) then
                registers_miso <= std_logic_vector(accumulator_re_preload_upper);
            elsif(registers_addr(2 downto 0) = REG_ADDR_PRELOAD_IM) then
                registers_miso <= std_logic_vector(accumulator_im_preload_upper);
            end if;
        end if;
    end process registers_rd_proc;

    -- Assorted register-controlled settings with no special behavior (automatic clearing, etc.)
    registers_wr_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst_int = '1') then
                accumulator_mode            <= (others => '0');
                latch_output_mode           <= (others => '0');
                output_select               <= '0';
                stream_output_mode          <= (others => '0');
                kernel_memory_pointer_start <= (others => '0');
                kernel_memory_pointer_end   <= (others => '0');
                accumulator_re_preload      <= (others => '0');
                accumulator_im_preload      <= (others => '0');
            elsif(registers_en = '1' and registers_we = '1') then
                if(registers_addr(2 downto 0) = REG_ADDR_CTRL_STAT) then
                    accumulator_mode <= registers_mosi(19 downto 18);
                    latch_output_mode <= registers_mosi(21 downto 20);
                    output_select <= registers_mosi(25);
                    stream_output_mode <= registers_mosi(28 downto 27);
                elsif(registers_addr(2 downto 0) = REG_ADDR_KERNEL_ADDRESS) then
                    kernel_memory_pointer_start <= registers_mosi(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0);
                    kernel_memory_pointer_end   <= registers_mosi(LOG2_KERNEL_MEMORY_DEPTH-1 + 16 downto 16);
                elsif(registers_addr(2 downto 0) = REG_ADDR_PRELOAD_RE) then
                    accumulator_re_preload_upper <= signed(registers_mosi);
                    accumulator_re_preload(accumulator_re_preload'high-32 downto 0) <= (others => '0');
                elsif(registers_addr(2 downto 0) = REG_ADDR_PRELOAD_IM) then
                    accumulator_im_preload_upper <= signed(registers_mosi);
                    accumulator_im_preload(accumulator_im_preload'high-32 downto 0) <= (others => '0');
                end if;
            end if;
        end if;
    end process registers_wr_proc;

    arm_preload_proc: process(clk) begin
        if rising_edge(clk) then
            if(rst_int = '1') then
                arm_preload <= '0';
            elsif(registers_en = '1' and registers_we = '1' and registers_addr(2 downto 0) = REG_ADDR_CTRL_STAT) then
                arm_preload <= registers_mosi(26);
            elsif(full_product_valid = '1') then
                -- We want arm_preload to be aligned with full_product_valid (i.e., the input to the accumulator).
                -- If full_product_valid reads as high in this synchronous process, that means that it's been high for
                -- exactly one cycle, so we should use this to deassert arm_preload.
                arm_preload <= '0';
            end if;
        end if;
    end process arm_preload_proc;

end rtl;
