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

entity complex_macc is
    port (
        clk                    : in  std_logic;
        accumulator_rst        : in  std_logic;

        -- Accumulator offset input
        offset_re              : in  std_logic_vector(31 downto 0);
        offset_im              : in  std_logic_vector(31 downto 0);   
        
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
        
        -- Multiplied signal output
        product_tdata          : out std_logic_vector(31 downto 0);
        product_tvalid         : out std_logic;
        product_tlast          : out std_logic;
        
        -- Accumulated signal output
        accumulator_tdata      : out std_logic_vector(63 downto 0);
        accumulator_tvalid     : out std_logic;
        accumulator_tlast      : out std_logic
    );
    
    attribute USE_DSP : string;
end complex_macc;

architecture rtl of complex_macc is
    
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
    
    ATTRIBUTE X_INTERFACE_INFO of product_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 PRODUCT TDATA";
    ATTRIBUTE X_INTERFACE_INFO of product_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 PRODUCT TLAST";
    ATTRIBUTE X_INTERFACE_INFO of product_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 PRODUCT TVALID";
    ATTRIBUTE X_INTERFACE_MODE of product_tdata  : SIGNAL is "Master";
    
    ATTRIBUTE X_INTERFACE_INFO of accumulator_tdata  : SIGNAL is "xilinx.com:interface:axis:1.0 ACCUMULATOR TDATA";
    ATTRIBUTE X_INTERFACE_INFO of accumulator_tlast  : SIGNAL is "xilinx.com:interface:axis:1.0 ACCUMULATOR TLAST";
    ATTRIBUTE X_INTERFACE_INFO of accumulator_tvalid : SIGNAL is "xilinx.com:interface:axis:1.0 ACCUMULATOR TVALID";
    ATTRIBUTE X_INTERFACE_MODE of accumulator_tdata  : SIGNAL is "Master";
    
    signal a_re : signed(15 downto 0); -- Sign-extended input
    signal a_im : signed(15 downto 0); -- Sign-extended input
    signal b_re : signed(15 downto 0); -- Sign-extended input
    signal b_im : signed(15 downto 0); -- Sign-extended input
    
    signal a_re_b_re : signed(31 downto 0);
    signal a_im_b_re : signed(31 downto 0);
    signal a_re_b_im : signed(31 downto 0);
    signal a_im_b_im : signed(31 downto 0);
    
    signal a_re_b_re_ext : signed(47 downto 0);
    signal a_im_b_re_ext : signed(47 downto 0);
    signal a_re_b_im_ext : signed(47 downto 0);
    signal a_im_b_im_ext : signed(47 downto 0);
    
    signal product_re : signed(47 downto 0);
    signal product_im : signed(47 downto 0);
    
    signal accumulator_re : signed(47 downto 0);
    signal accumulator_im : signed(47 downto 0);
    
    signal offset_re_int : signed(31 downto 0);
    signal offset_im_int : signed(31 downto 0);
    
    signal kernel_mem_addr_tvalid_d     : std_logic;
    signal kernel_mem_addr_tvalid_dd    : std_logic;
    signal kernel_mem_addr_tvalid_ddd   : std_logic;
    signal kernel_mem_addr_tvalid_dddd  : std_logic;
    signal kernel_mem_addr_tvalid_ddddd : std_logic;
    
    signal kernel_mem_addr_tlast_d     : std_logic;
    signal kernel_mem_addr_tlast_dd    : std_logic;
    signal kernel_mem_addr_tlast_ddd   : std_logic;
    signal kernel_mem_addr_tlast_dddd  : std_logic;
    signal kernel_mem_addr_tlast_ddddd : std_logic;
begin

    -- Address the kernel memory
    kernel_mem_addr <= kernel_mem_addr_tdata;
    kernel_mem_rst  <= not kernel_mem_addr_tvalid;
    kernel_mem_clk  <= clk;

    product_proc: process(clk) begin
        if rising_edge(clk) then
        
            -- Load inputs
            a_re <= signed(signal_in(15 downto 0));
            a_im <= signed(signal_in(31 downto 16));
            b_re <= signed(kernel_mem_dout(15 downto 0));
            b_im <= signed(kernel_mem_dout(31 downto 16));
            
            kernel_mem_addr_tvalid_d <= kernel_mem_addr_tvalid;
            kernel_mem_addr_tlast_d  <= kernel_mem_addr_tlast;

            signal_out_tdata <= signal_in;
            
            -- Perform the multiplication
            a_re_b_re <= a_re * b_re;
            a_im_b_re <= a_im * b_re;
            a_re_b_im <= a_re * b_im;
            a_im_b_im <= a_im * b_im;
            
            kernel_mem_addr_tvalid_dd <= kernel_mem_addr_tvalid_d;
            kernel_mem_addr_tlast_dd  <= kernel_mem_addr_tlast_d;
            
            -- Sign extend the product terms in its own pipeline stage
            a_re_b_re_ext(31 downto 0)  <= a_re_b_re;
            a_re_b_re_ext(47 downto 32) <= (others => a_re_b_re(31));
            a_im_b_re_ext(31 downto 0)  <= a_im_b_re;
            a_im_b_re_ext(47 downto 32) <= (others => a_im_b_re(31));
            a_re_b_im_ext(31 downto 0)  <= a_re_b_im;
            a_re_b_im_ext(47 downto 32) <= (others => a_re_b_im(31));
            a_im_b_im_ext(31 downto 0)  <= a_im_b_im;
            a_im_b_im_ext(47 downto 32) <= (others => a_im_b_im(31));
            
            kernel_mem_addr_tvalid_ddd <= kernel_mem_addr_tvalid_dd;
            kernel_mem_addr_tlast_ddd  <= kernel_mem_addr_tlast_dd;
            
            -- Sum the sign-extended product terms to compute the full complex product
            product_re <= a_re_b_re_ext - a_im_b_im_ext;
            product_im <= a_im_b_re_ext + a_re_b_im_ext;
            
            kernel_mem_addr_tvalid_dddd <= kernel_mem_addr_tvalid_ddd;
            kernel_mem_addr_tlast_dddd <= kernel_mem_addr_tlast_ddd;
        end if;
    end process product_proc;
            
    signal_out_tvalid <= kernel_mem_addr_tvalid_d;
    signal_out_tlast  <= kernel_mem_addr_tlast_d;
    
    -- Connect the product data stream
    product_tdata  <= std_logic_vector(product_im(31 downto 16)) & std_logic_vector(product_re(31 downto 16));
    product_tvalid <= kernel_mem_addr_tvalid_dddd;
    product_tlast  <= kernel_mem_addr_tlast_dddd;

    accum_proc: process(clk) begin
    
        if rising_edge(clk) then
            -- Pipeline the offset input
            -- Note that if timing closure becomes difficult, we could add another pipeline
            -- stage here since this value will generally not change frequently
            offset_re_int <= signed(offset_re);
            offset_im_int <= signed(offset_im);
        
            kernel_mem_addr_tvalid_ddddd <= kernel_mem_addr_tvalid_dddd;
            kernel_mem_addr_tlast_ddddd  <= kernel_mem_addr_tlast_dddd;
                
            if(accumulator_rst = '1') then
                accumulator_re(31 downto 0)  <= offset_re_int;
                accumulator_re(47 downto 32) <= (others => offset_re_int(31));
                accumulator_im(31 downto 0)  <= offset_im_int;
                accumulator_im(47 downto 32) <= (others => offset_im_int(31));
            else 
                accumulator_re <= accumulator_re + product_re;
                accumulator_im <= accumulator_im + product_im; 
            end if;
        end if;
    end process accum_proc;
    
    accumulator_tdata  <= std_logic_vector(accumulator_im(47 downto 16)) & std_logic_vector(accumulator_re(47 downto 16));
    accumulator_tvalid <= kernel_mem_addr_tvalid_ddddd;
    accumulator_tlast  <= kernel_mem_addr_tlast_ddddd;
end rtl;
