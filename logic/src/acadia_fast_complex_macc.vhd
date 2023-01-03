----------------------------------------------------------------------------------
-- Company: Yale University
-- Engineer: William Kalfus
-- 
-- Create Date: 10/25/2022 11:52:49 PM
-- Design Name: acadia
-- Module Name: complex_macc - rtl
-- Project Name: acadia
-- Target Devices: ZCU216
-- Tool Versions: 2020.2
-- Description: A module which multiplies a continuous incoming data stream
-- against a kernel stored in a BRAM. The kernel address is provided by an
-- AXI-stream input, and the handshaking signals of this stream control the 
-- operation (and reset) of the accumulator, along with the final accumulator 
-- value being latched.
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

entity acadia_fast_complex_macc is
    port (
        clk                    : in  std_logic;

        -- Accumulator offset input
        offset_re              : in  std_logic_vector(31 downto 0);
        offset_re_wr           : in  std_logic;
        offset_im              : in  std_logic_vector(31 downto 0);   
        offset_im_wr           : in  std_logic;
        
         -- Continuous signal input
        signal_in              : in  std_logic_vector(31 downto 0);
        
        -- Kernel memory read interface
        kernel_mem_dout        : in  std_logic_vector(31 downto 0);
        kernel_mem_addr        : out std_logic_vector(15 downto 0);
        kernel_mem_clk         : out std_logic;
        kernel_mem_rst         : out std_logic;
        
        -- Kernel memory address control from DMA
        kernel_mem_addr_tdata  : in  std_logic_vector(15 downto 0);
        kernel_mem_addr_tvalid : in  std_logic;
        kernel_mem_addr_tlast  : in  std_logic; 
            
        -- Input signal passthrough
        signal_out_tdata       : out std_logic_vector(31 downto 0);
        signal_out_tvalid      : out std_logic;
        signal_out_tlast       : out std_logic;
        
        -- Accumulated signal output
        accumulator_tdata      : out std_logic_vector(63 downto 0);
        accumulator_tvalid     : out std_logic;
        accumulator_tlast      : out std_logic
    );
    
    attribute USE_DSP : string;
end acadia_fast_complex_macc;

architecture rtl of acadia_fast_complex_macc is
    
    attribute USE_DSP of rtl : architecture is "YES";
    
    ATTRIBUTE X_INTERFACE_INFO : STRING;
    ATTRIBUTE X_INTERFACE_MODE : STRING;
    
    ATTRIBUTE X_INTERFACE_INFO of kernel_mem_dout: SIGNAL is "xilinx.com:interface:bram:1.0 KERNEL_MEM DOUT";
    ATTRIBUTE X_INTERFACE_INFO of kernel_mem_addr: SIGNAL is "xilinx.com:interface:bram:1.0 KERNEL_MEM ADDR";
    ATTRIBUTE X_INTERFACE_INFO of kernel_mem_clk : SIGNAL is "xilinx.com:interface:bram:1.0 KERNEL_MEM CLK";
    ATTRIBUTE X_INTERFACE_INFO of kernel_mem_rst : SIGNAL is "xilinx.com:interface:bram:1.0 KERNEL_MEM RST";
    ATTRIBUTE X_INTERFACE_MODE of kernel_mem_dout: SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of kernel_mem_addr_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 KERNEL_MEM_ADDR TDATA";
    ATTRIBUTE X_INTERFACE_INFO of kernel_mem_addr_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 KERNEL_MEM_ADDR TLAST";
    ATTRIBUTE X_INTERFACE_INFO of kernel_mem_addr_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 KERNEL_MEM_ADDR TVALID";

    ATTRIBUTE X_INTERFACE_INFO of signal_out_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 SIGNAL_OUT TDATA";
    ATTRIBUTE X_INTERFACE_INFO of signal_out_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 SIGNAL_OUT TLAST";
    ATTRIBUTE X_INTERFACE_INFO of signal_out_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 SIGNAL_OUT TVALID";
    ATTRIBUTE X_INTERFACE_MODE of signal_out_tdata  : SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of accumulator_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 ACCUMULATOR TDATA";
    ATTRIBUTE X_INTERFACE_INFO of accumulator_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 ACCUMULATOR TLAST";
    ATTRIBUTE X_INTERFACE_INFO of accumulator_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 ACCUMULATOR TVALID";
    ATTRIBUTE X_INTERFACE_MODE of accumulator_tdata  : SIGNAL is "Master";
    
    -- First stage: input loading
    signal a_re : signed(15 downto 0);
    signal a_im : signed(15 downto 0);
    signal b_re : signed(15 downto 0);
    signal b_im : signed(15 downto 0);
    
    -- Second stage: multiplication
    signal a_re_b_re : signed(31 downto 0);
    signal a_im_b_re : signed(31 downto 0);
    signal a_re_b_im : signed(31 downto 0);
    signal a_im_b_im : signed(31 downto 0);
    
    -- Third stage: accumulator with load
    signal accumulator_re : signed(47 downto 0);
    signal accumulator_im : signed(47 downto 0);
    
    signal offset_re_int : signed(31 downto 0);
    signal offset_im_int : signed(31 downto 0);
    
    -- Pipeline progress flags
    signal input_valid   : std_logic;
    signal input_last    : std_logic;
    signal product_valid : std_logic;
    signal product_last  : std_logic;
    
begin

    -- Address the kernel memory
    kernel_mem_addr <= kernel_mem_addr_tdata;
    kernel_mem_rst  <= not kernel_mem_addr_tvalid;
    kernel_mem_clk  <= clk;

    -- First pipeline stage:
    -- Load the input registers using the RT DMA handshaking signals
    input_proc: process(clk) begin
        if rising_edge(clk) then
            input_valid <= kernel_mem_addr_tvalid;
            input_last  <= kernel_mem_addr_tlast;
            
            if(rst = '1') then
                a_re <= (others => '0');
                a_im <= (others => '0');
                b_re <= (others => '0');
                b_im <= (others => '0');
            elsif(kernel_mem_addr_tvalid = '1') then
                a_re <= signed(signal_in(15 downto 0));
                a_im <= signed(signal_in(31 downto 16));
                b_re <= signed(kernel_mem_dout(15 downto 0));
                b_im <= signed(kernel_mem_dout(31 downto 16));
            end if;
        end if;
    end process input_proc;
        
    -- Simultaneously, duplicate the signal input
    signal_out_proc: process(clk) begin
        if rising_edge(clk) then
            signal_out_tdata  <= signal_in;
            signal_out_tvalid <= kernel_mem_addr_tvalid;
            signal_out_tlast  <= kernel_mem_addr_tlast;
        end if;
    end process signal_out_proc;
        
    -- Second pipeline stage: multiplication
    product_proc: process(clk) begin
        if rising_edge(clk) then
            product_valid <= input_valid;
            product_last  <= input_last;
            
            if(rst = '1') then
                a_re_b_re <= (others => '0');
                a_im_b_re <= (others => '0');
                a_re_b_im <= (others => '0');
                a_im_b_im <= (others => '0');
            else
                a_re_b_re <= a_re * b_re;
                a_im_b_re <= a_im * b_re;
                a_re_b_im <= a_re * b_im;
                a_im_b_im <= a_im * b_im;
            end if;
        end if;
    end process product_proc;
            
    -- Third pipeline stage: accumulate
    accumulator_proc: process(clk) begin
        if rising_edge(clk) then
            -- Pipeline the offset input
            offset_re_int <= signed(offset_re);
            offset_im_int <= signed(offset_im);
                
            accumulator_tvalid <= product_valid;
            accumulator_tlast  <= product_last;
                
            if(offset_re_wr = '1') then
                accumulator_re(31 downto 0)  <= offset_re_int;
                accumulator_re(47 downto 32) <= (others => offset_re_int(31));
            else 
                accumulator_re <= accumulator_re + a_re_b_re - a_im_b_im;
            end if;
                
            if(offset_im_wr = '1') then
                accumulator_im(31 downto 0)  <= offset_im_int;
                accumulator_im(47 downto 32) <= (others => offset_im_int(31));
            else
                accumulator_im <= accumulator_im + a_re_b_im + a_im_b_re; 
            end if;
        end if;
    end process accumulator_proc;
            
    -- Connect the output data accordingly
    accumulator_tdata  <= std_logic_vector(accumulator_im(47 downto 16)) & std_logic_vector(accumulator_re(47 downto 16));
    
end rtl;
