----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/25/2022 11:52:49 PM
-- Design Name: acadia
-- Module Name: acadia_complex_macc_dedicated_memory - rtl
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
--         Address 0: Accumulator Real
--             Writing to this address loads the real accumulator
--             with the provided value and clears the 
--             "accumulator_done" signal. Reading from this address
--             returns the current value of the real accumulator.
--         Address 1: Accumulator Imaginary
--             Identical to address 0, but for the imaginary 
--             accumulator.
--         Address 2: Control/Status
--             Bit 0 (W) : Kernel Pointer Load Start
--                 When this is 1, the kernel pointer register is loaded
--                 with the value in the start addres register.
--             Bit 16 (R)     : Range Error
--                 An overflow or underflow has occurred in the 
--                 calculation. After being set, this signal is latched
--                 until the module is reset.
--             Bit 17 (R)     : Output FIFO Overflow
--             Bit 18 (RW)    : Accumulator Done
--                 The stream has completed its path through the 
--                 accumulator and the accumulation results are 
--                 available. Writing this value will be necessary
--                 to clear it.
--             Bit 19 (R)     : Accumulator Real MSB
--             Bit 20 (R)     : Accumulator Imaginary MSB
--             Bits 22-21 (RW): Write mode
--                 When 00, nothing is written
--                 When 01, the upper 32 bits of the accumulator value is written
--                 When 10, the lower 32 bits of the accumulator value is written
--                 When 11, the input value is written
--                
--             Bit 23 (RW)    : Write last
--                 When set, only the last value is presented on the output stream.           
--             Bit 24 (W)     : FIFO Reset
--         Address 3: 
--             Bits 15-0: Kernel Memory Address Start
--                 The first address of the kernel in memory.
--             Bits 31-16: Kernel Memory Address End
--                 The final address of the kernel in memory.
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

entity acadia_stream_complex32_macc is
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
        clk             : in  std_logic;

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
        kernel_memory_clk  : in  std_logic;
            
        -- Output data stream
        data_out_aclk   : in  std_logic;
        data_out_tdata  : out std_logic_vector(63 downto 0);
        data_out_tvalid : out std_logic;
        data_out_tready : in  std_logic;
        data_out_tlast  : out std_logic;
        data_out_tkeep  : out std_logic_vector(7 downto 0);

        -- Register access (synchronous to data_clk)
        registers_mosi  : in  std_logic_vector(31 downto 0);
        registers_miso  : out std_logic_vector(31 downto 0);
        registers_addr  : in  std_logic_vector(31 downto 0);
        registers_we    : in  std_logic;
        registers_en    : in  std_logic
    );
    
    attribute USE_DSP : string;
end acadia_stream_complex32_macc;

architecture rtl of acadia_stream_complex32_macc is
    
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

    -- Input quadratures
    signal a_re : signed(17 downto 0);
    signal a_im : signed(17 downto 0);
    signal b_re : signed(15 downto 0);
    signal b_im : signed(15 downto 0);

    -- Accumulator components
    signal accumulator_re : signed(46 downto 0);
    signal accumulator_im : signed(46 downto 0);
    signal accumulator_re_d : std_logic_vector(accumulator_re'high downto 0);
    signal accumulator_im_d : std_logic_vector(accumulator_im'high downto 0);
    
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
    
    -- Kernel memory access signals
    signal kernel_memory_pointer_start : std_logic_vector(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0);
    signal kernel_memory_pointer_end   : std_logic_vector(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0);
    signal kernel_memory_pointer       : std_logic_vector(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0);
    signal kernel_memory_data    : std_logic_vector(31 downto 0);
    
    -- Reset signal (controlled by registers)
    signal fifo_rst  : std_logic;

    -- Output write control
    signal write_mode      : std_logic_vector(1 downto 0);
    signal write_last      : std_logic;
    signal range_err       : std_logic;
    signal buffer_overflow : std_logic;

    -- Output data
    signal output_data  : std_logic_vector(63 downto 0);
    signal output_valid : std_logic;
    signal output_last  : std_logic;

    -- Pipeline progress flags
    signal input_valid          : std_logic;
    signal input_last           : std_logic;
    signal product_valid        : std_logic;
    signal product_last         : std_logic;
    signal accumulator_valid    : std_logic;
    signal accumulator_done_int : std_logic;
    
begin

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
            enb => '1',
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

    -- Process to manage the kernel memory pointer
    kernel_memory_pointer_proc: process(clk) begin
        if rising_edge(clk) then
            if(registers_we = '1' and registers_en = '1' and registers_addr(1 downto 0) = "10" and registers_mosi(0) = '1') then
                kernel_memory_pointer <= kernel_memory_pointer_start;
            elsif(data_in_tvalid = '1') then
                if(kernel_memory_pointer = kernel_memory_pointer_end) then
                    kernel_memory_pointer <= kernel_memory_pointer_start;
                else
                    kernel_memory_pointer <= std_logic_vector(unsigned(kernel_memory_pointer) + 1);
                end if;
            end if;
        end if;
    end process kernel_memory_pointer_proc;

    -- Data input pipelining
    -- To figure out how many pipeline stages are needed on the input
    -- data, we can "simulate" an example sequence of events:
    -- Time Kptr Kmem Data DVld
    -- 0    0    K(0) X    0
    -- 1    0    K(0) D(0) 1
    -- 2    1    K(0) D(1) 1
    -- 3    2    K(1) D(2) 1  
    -- 4    3    K(2) X    0  
    -- 5    3    K(3) D(3) 1
    -- 6    4    K(3) D(4) 1
    -- 7    5    K(4) D(5) 1
    --
    -- Therefore, one stage of pipelining should be sufficient.

    -- We'll always accept data from the input
    data_in_tready <= '1';

    -- Alias the kernel memory output as quadrature values
    b_re  <= signed(kernel_memory_data(15 downto 0));
    b_im  <= signed(kernel_memory_data(31 downto 16));

    -- First pipeline stage: sum the individual components of the input signal
    input_narrowing_proc: process(clk) 
       variable sum_re : signed(a_re'high downto 0); 
       variable sum_im : signed(a_re'high downto 0); 
    begin
        if rising_edge(clk) then
            -- Use variables and a loop to sum all the inputs
            sum_re := (others => '0');
            sum_im := (others => '0');
            sum_loop: for i in 0 to INPUT_WORDS-1 loop
                sum_re := sum_re + resize(signed(data_in_tdata((i*32) + 15 downto (i*32))), sum_re'length);
                sum_im := sum_im + resize(signed(data_in_tdata((i*32) + 31 downto (i*32) + 16)), sum_im'length);
            end loop sum_loop;

            -- Now update the outputs with the varables
            a_re   <= sum_re;
            a_im   <= sum_im;

            input_valid <= data_in_tvalid;
            input_last  <= data_in_tlast;
        end if;
    end process input_narrowing_proc;

    -- Second pipeline stage: multiplication
    product_proc: process(clk) begin
        if rising_edge(clk) then
            product_valid <= input_valid;
            product_last  <= input_last;
            
            a_re_b_re <= a_re * b_re;
            a_im_b_re <= a_im * b_re;
            a_re_b_im <= a_re * b_im;
            a_im_b_im <= a_im * b_im;
        end if;
    end process product_proc;

    -- Sign extend products
    a_re_b_re_sign <= (others => a_re_b_re(a_re_b_re'high));
    a_im_b_re_sign <= (others => a_im_b_re(a_im_b_re'high));
    a_re_b_im_sign <= (others => a_re_b_im(a_re_b_im'high));
    a_im_b_im_sign <= (others => a_im_b_im(a_im_b_im'high));
            
    -- Third pipeline stage: accumulator with register control
    -- The accumulator will also need to be controlled by the register write interface
    accumulator_proc: process(clk) begin
        if rising_edge(clk) then
            accumulator_re_d <= std_logic_vector(accumulator_re);
            accumulator_im_d <= std_logic_vector(accumulator_im);
            accumulator_valid <= product_valid;

            if(registers_en = '1' and registers_we = '1') then
                if(registers_addr(1 downto 0) = "00") then
                    accumulator_re(46 downto 15) <= signed(registers_mosi);
                    accumulator_re(14 downto 0)  <= (others => '0');
                elsif(registers_addr(1 downto 0) = "01") then
                    accumulator_im(46 downto 15) <= signed(registers_mosi);
                    accumulator_im(14 downto 0)  <= (others => '0');
                elsif(registers_addr(1 downto 0) = "10") then
                    accumulator_done_int <= registers_mosi(18);
                end if;
            elsif(product_valid = '1' and accumulator_done_int = '0') then
                accumulator_done_int <= product_last;
                accumulator_re       <= accumulator_re + (a_re_b_re_sign & a_re_b_re) - (a_im_b_im_sign & a_im_b_im);
                accumulator_im       <= accumulator_im + (a_re_b_im_sign & a_re_b_im) + (a_im_b_re_sign & a_im_b_re); 
            end if;  
        end if;
    end process accumulator_proc;

    output_select_proc: process(clk) begin
        if rising_edge(clk) then
            case write_mode is
                when "01" =>
                    output_data(31 downto 0)  <= std_logic_vector(accumulator_re(accumulator_re'high downto accumulator_re'high-31));
                    output_data(63 downto 32) <= std_logic_vector(accumulator_im(accumulator_im'high downto accumulator_im'high-31));
                    output_valid              <= (accumulator_valid and not write_last) or (accumulator_valid and accumulator_done_int and write_last);
                    output_last               <= accumulator_done_int;

                when "10" =>
                    output_data(31 downto 0)  <= std_logic_vector(accumulator_re(31 downto 0));
                    output_data(63 downto 32) <= std_logic_vector(accumulator_im(31 downto 0));
                    output_valid              <= (accumulator_valid and not write_last) or (accumulator_valid and accumulator_done_int and write_last);
                    output_last               <= accumulator_done_int;

                when "11" =>
                    output_data(31 downto 0)  <= std_logic_vector(resize(a_re, 32));
                    output_data(63 downto 32) <= std_logic_vector(resize(a_im, 32));
                    output_valid              <= (input_valid and not write_last) or (input_valid and input_last and write_last);
                    output_last               <= input_last;
                
                when others =>
                    output_data  <= (others => '0');
                    output_valid <= '0';
                    output_last  <= '0';
            end case;
        end if;
    end process output_select_proc;

    output_fifo: entity work.acadia_backpressure_fifo
        generic map (
            WORD_WIDTH   => 64,
            INPUT_WORDS  => 1,
            OUTPUT_WORDS => 1,
            INPUT_DEPTH  => DATA_OUTPUT_FIFO_DEPTH,
            MEMORY_TYPE  => DATA_OUTPUT_FIFO_PRIMITIVE,
            ASYNCHRONOUS => DATA_OUTPUT_FIFO_ASYNCHRONOUS,
            MONITOR_SYNC => true  -- Set to true if monitor_clk is synchronous to signal_in_clk
        )
        port map (
            signal_in_clk    => clk,
            signal_in_rst    => fifo_rst,

            -- A port for monitoring the status of the FIFO and resetting it
            monitor_clk      => clk,
            monitor_rst      => fifo_rst,
            monitor_overflow => buffer_overflow,
            monitor_misalignment => open,
            
            signal_in_tdata  => output_data,
            signal_in_tvalid => output_valid,
            signal_in_tlast  => output_last,
            
            m_axis_aclk      => data_out_aclk,
            m_axis_tdata     => data_out_tdata,
            m_axis_tvalid    => data_out_tvalid,
            m_axis_tready    => data_out_tready,
            m_axis_tlast     => data_out_tlast,
            m_axis_tkeep     => data_out_tkeep
        );

    -- Register read interface
    registers_read_proc: process(clk) begin
        if rising_edge(clk) then
            if(registers_addr(1 downto 0) = "00") then
                registers_miso <= std_logic_vector(accumulator_re_d(46 downto 15));
            elsif(registers_addr(1 downto 0) = "01") then
                registers_miso <= std_logic_vector(accumulator_im_d(46 downto 15));
            elsif(registers_addr(1 downto 0) = "10") then
                registers_miso(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0) <= kernel_memory_pointer;
                registers_miso(15 downto LOG2_KERNEL_MEMORY_DEPTH)  <= (others => '0');
                registers_miso(16)           <= range_err;
                registers_miso(17)           <= buffer_overflow;
                registers_miso(18)           <= accumulator_done_int;
                registers_miso(19)           <= accumulator_re(accumulator_re'high);
                registers_miso(20)           <= accumulator_im(accumulator_im'high);
                registers_miso(22 downto 21) <= write_mode;
                registers_miso(23)           <= write_last;
                registers_miso(31 downto 24) <= (others => '0');
            end if;
        end if;
    end process registers_read_proc;

    -- Process to manage the kernel memory pointer start and end addresses
    kernel_memory_pointer_start_end_proc: process(clk) begin
        if rising_edge(clk) then
            if(registers_we = '1' and registers_en = '1' and registers_addr(1 downto 0) = "11") then
                kernel_memory_pointer_start <= registers_mosi(LOG2_KERNEL_MEMORY_DEPTH-1 downto 0);
                kernel_memory_pointer_end   <= registers_mosi(LOG2_KERNEL_MEMORY_DEPTH-1 + 16 downto 16);
            end if;
        end if;
    end process kernel_memory_pointer_start_end_proc;

    write_mode_proc: process(clk) begin
        if rising_edge(clk) then
            if(registers_en = '1' and registers_we = '1' and registers_addr(1 downto 0) = "10") then
                write_mode <= registers_mosi(22 downto 21);
                write_last <= registers_mosi(23);
            end if;
        end if;
    end process write_mode_proc;

    fifo_rst_proc: process(clk) begin
        if rising_edge(clk) then
            if(fifo_rst = '1') then
                fifo_rst  <= '0';
            elsif(registers_en = '1' and registers_we = '1' and registers_addr(1 downto 0) = "10") then
                fifo_rst  <= registers_mosi(24);
            end if;
        end if;
    end process fifo_rst_proc;

end rtl;
