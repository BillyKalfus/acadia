`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: Yale University
// Engineer: William Kalfus
// 
// Create Date: 11/10/2022 03:24:36 PM
// Design Name: acadia
// Module Name: acadia_tb
// Project Name: acadia
// Target Devices: ZCU216
// Tool Versions: 2020.2
// Description: A testbench intended to verify the functionality of the complete
//              block design, including exposing internal signals to verify 
//              internal signal processing, latencies, and timing relationships.
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////

module tb_instruction_memory (
    input wire         clk,
    input wire [15:0]  addr,
    output reg [127:0] dout
); 
    
    always @(posedge clk) begin
        if(addr == 128'd0) begin
            dout <= {15'd0, 
                     1'b0,   // STP
                     7'd0, 
                     1'b0,   // PUSH_RETURN
                     8'd0,   // SRC1
                     8'd0,   // SRC2
                     8'd0,   // DEST1
                     8'd0,   // DEST2,
                     3'd0, 
                     1'b0,   // DSP_CEP_EN,
                     1'b0, 
                     3'd0,   // DSP_CEP
                     32'd0,  // IMM1
                     32'd0}; // IMM2
        end else if(addr == 128'd1) begin
            // Load DSP0 CFG and store 5 into the branch mask
            dout <= {15'd0, 
                     1'b0,   // STP
                     7'd0, 
                     1'b0,   // PUSH_RETURN
                     8'd16,  // SRC1 = IMM
                     8'd16,   // SRC2 = IMM
                     8'd64,  // DEST1 = DSP0 CFG
                     8'd24,   // DEST2 = MASK,
                     3'd0, 
                     1'b0,   // DSP_CEP_EN,
                     1'b0, 
                     3'd0,   // DSP_CEP
                     32'd41472,  // IMM1 = DSPConfiguration("P+1", dsp_cep="set").value()
                     32'd5}; // IMM2
        end else if(addr == 128'd2) begin
            // Hold while DSP0 P != MASK
            // When done, goto instruction address 3
            dout <= {15'd0, 
                     1'b1,   // STC
                     7'd0, 
                     1'b0,   // PUSH_RETURN
                     8'd16,  // SRC_STVAL = IMM
                     8'd64,  // SRC_TVAL = DSP0 P
                     8'd16,  // DEST_STVAL = HOLD
                     8'd1,   // OP !=,
                     3'd0, 
                     1'b0,   // DSP_CEP_EN,
                     1'b0, 
                     3'd0,   // DSP_CEP
                     32'd3,  // IMM1 = 3
                     32'd0}; // IMM2
        end else if(addr == 128'd3) begin
            // Load R0
            dout <= {15'd0, 
                     1'b0,   // STP
                     7'd0, 
                     1'b0,   // PUSH_RETURN
                     8'd16,  // SRC1 = IMM
                     8'd0,   // SRC2 = R0
                     8'd0,  // DEST1 = R0
                     8'd0,   // DEST2 = R0,
                     3'd0, 
                     1'b0,   // DSP_CEP_EN,
                     1'b0, 
                     3'd0,   // DSP_CEP
                     32'hDEADBEEF,  // IMM1 = DSPConfiguration("P+1", dsp_cep="set").value()
                     32'd0}; // IMM2
        end else if(addr == 128'd4) begin
            // Load R1 and jump to address 20
            dout <= {15'd0, 
                     1'b0,   // STP
                     7'd0, 
                     1'b0,   // PUSH_RETURN
                     8'd16,  // SRC1 = IMM
                     8'd16,   // SRC2 = IMM
                     8'd1,   // DEST1 = R1
                     8'd8,   // DEST2 = PC,
                     3'd0, 
                     1'b0,   // DSP_CEP_EN,
                     1'b0, 
                     3'd0,   // DSP_CEP
                     32'hFACEB00C,  // IMM1 = DSPConfiguration("P+1", dsp_cep="set").value()
                     32'd20}; // IMM2
        end else if(addr == 128'd20) begin
            // Load R2
            dout <= {15'd0, 
                     1'b0,   // STP
                     7'd0, 
                     1'b0,   // PUSH_RETURN
                     8'd16,  // SRC1 = IMM
                     8'd0,   // SRC2 = R0
                     8'd2,   // DEST1 = R2
                     8'd0,   // DEST2 = R0,
                     3'd0, 
                     1'b0,   // DSP_CEP_EN,
                     1'b0, 
                     3'd0,   // DSP_CEP
                     32'hABCDEF89,  // IMM1 = DSPConfiguration("P+1", dsp_cep="set").value()
                     32'd0}; // IMM2
        end else begin
            dout <= 128'd0;
        end
    end
    
endmodule

module sequencer_tb();
    
    // -------------------------- Declare many signals that will be useful for debugging ----------------------------
    
    // DAC clock generated by external source (in this case, manually in the testbench)
    reg           clk;
    reg           run;
    wire  [127:0] instruction_mem_dout;
    wire  [15:0]  instruction_mem_addr;

    initial begin       
        clk = 1'b0;
    end
    
    always begin
        #2 clk = ~clk;
    end

    // -------------------------- Instantiate the sequencer ----------------------------
    acadia_sequencer uut
       (.clk(clk),
        .nrst(run),
        .run(run),
        .instruction_mem_dout(instruction_mem_dout),
        .instruction_mem_addr(instruction_mem_addr),
        .mem_bus_miso(32'd0));
        
        
    tb_instruction_memory mem(
        .clk(clk),
        .addr(instruction_mem_addr),
        .dout(instruction_mem_dout));
    
    // -------------------------- Simulate the PS writing commands to run the testbench ----------------------------
    initial begin
        run = 1'b0;
        
        repeat(100) @(posedge clk);
        
        run = 1'b1;
        
        repeat(100) @(posedge clk);
        
        $finish;
    end
endmodule
