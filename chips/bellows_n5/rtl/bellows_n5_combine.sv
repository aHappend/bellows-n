`default_nettype none
module bellows_n5_combine #(
    parameter integer MAX_K=4,
    parameter integer MAX_TOKEN_ELEMS=256
) (
    input wire clk, rst_n,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [31:0] cmd_token_id,
    input wire [8:0] cmd_elems,
    input wire [2:0] cmd_k,
    input wire cmd_format,
    input wire [16*((MAX_K>0)?MAX_K:1)-1:0] cmd_weights,
    output wire read_valid,
    input wire read_ready,
    output wire [1:0] read_rank,
    output wire [7:0] read_elem,
    input wire sample_valid,
    output wire sample_ready,
    input wire [15:0] sample_data,
    output wire out_valid,
    input wire out_ready,
    output wire [15:0] out_data,
    output wire [31:0] out_token_id,
    output wire [7:0] out_elem,
    output wire out_last,
    output wire idle
);
    generate if (MAX_K>=1 && MAX_K<=4 &&
                 MAX_TOKEN_ELEMS>=1 && MAX_TOKEN_ELEMS<=256) begin : g_legal
        localparam IDLE=0, READ_REQ=1, READ_WAIT=2, MUL_ISSUE=3, MUL_WAIT=4,
                   ADD_ISSUE=5, ADD_WAIT=6, OUTPUT=7;
        reg [2:0] state;
        reg [31:0] token_id;
        reg [8:0] elems;
        reg [2:0] count;
        reg format;
        reg [16*MAX_K-1:0] weights;
        reg [1:0] rank;
        reg [7:0] elem;
        reg [15:0] sample, product, accumulator;
        reg [15:0] decoded_fp8;
        reg [7:0] fp8_exp;
        always @* begin
            decoded_fp8={sample_data[7],15'b0};
            fp8_exp=0;
            if (sample_data[6:3]==15 && sample_data[2:0]==7)
                decoded_fp8=16'h7fc0;
            else if (sample_data[6:3]!=0) begin
                fp8_exp={4'b0,sample_data[6:3]}+8'd120;
                decoded_fp8={sample_data[7],fp8_exp,sample_data[2:0],4'b0};
            end else if (sample_data[2]) begin
                decoded_fp8={sample_data[7],8'd120,sample_data[1:0],5'b0};
            end else if (sample_data[1]) begin
                decoded_fp8={sample_data[7],8'd119,sample_data[0],6'b0};
            end else if (sample_data[0])
                decoded_fp8={sample_data[7],8'd118,7'b0};
        end
        wire mul_ready, mul_valid;
        wire [15:0] mul_result;
        bellows_n5_bf16_mul gate_mul (
            .clk(clk), .rst_n(rst_n),
            .in_valid(rst_n && state==MUL_ISSUE), .in_ready(mul_ready),
            .a(weights[16*rank +:16]), .b(sample),
            .out_valid(mul_valid), .out_ready(state==MUL_WAIT),
            .result(mul_result)
        );
        wire add_ready, add_valid;
        wire [63:0] add_data;
        wire [7:0] add_keep;
        wire add_last;
        furnace_reduce_alu #(.DATA_WIDTH(64)) gate_sum (
            .clk(clk), .rst_n(rst_n), .in_valid(rst_n && state==ADD_ISSUE),
            .in_a({48'b0,accumulator}), .in_b({48'b0,product}),
            .in_keep(8'h03), .in_format(2'd1), .in_op(2'd0), .in_last(1'b1),
            .in_ready(add_ready), .out_valid(add_valid), .out_data(add_data),
            .out_keep(add_keep), .out_last(add_last), .out_ready(state==ADD_WAIT)
        );
        assign cmd_ready=rst_n && state==IDLE;
        assign read_valid=rst_n && state==READ_REQ;
        assign read_rank=rst_n ? rank : 2'b0;
        assign read_elem=rst_n ? elem : 8'b0;
        assign sample_ready=rst_n && state==READ_WAIT;
        assign out_valid=rst_n && state==OUTPUT;
        assign out_data=(rst_n && state==OUTPUT) ? accumulator : 16'b0;
        assign out_token_id=rst_n ? token_id : 32'b0;
        assign out_elem=rst_n ? elem : 8'b0;
        assign out_last=rst_n && state==OUTPUT && {1'b0,elem}+9'd1==elems;
        assign idle=rst_n && state==IDLE;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; token_id<=0; elems<=0; count<=0; format<=0;
                weights<=0; rank<=0; elem<=0; sample<=0; product<=0; accumulator<=0;
            end else case (state)
                IDLE: if (cmd_valid) begin
                    token_id<=cmd_token_id; elems<=cmd_elems; count<=cmd_k;
                    format<=cmd_format; weights<=cmd_weights;
                    rank<=0; elem<=0; accumulator<=0; state<=READ_REQ;
                end
                READ_REQ: if (read_ready) state<=READ_WAIT;
                READ_WAIT: if (sample_valid) begin
                    sample<=format ? sample_data : decoded_fp8; state<=MUL_ISSUE;
                end
                MUL_ISSUE: if (mul_ready) state<=MUL_WAIT;
                MUL_WAIT: if (mul_valid) begin product<=mul_result; state<=ADD_ISSUE; end
                ADD_ISSUE: if (add_ready) state<=ADD_WAIT;
                ADD_WAIT: if (add_valid) begin
                    accumulator<=add_data[15:0];
                    if ({1'b0,rank}+3'd1==count) state<=OUTPUT;
                    else begin rank<=rank+1'b1; state<=READ_REQ; end
                end
                OUTPUT: if (out_ready) begin
                    if ({1'b0,elem}+9'd1==elems) state<=IDLE;
                    else begin
                        elem<=elem+1'b1; rank<=0; accumulator<=0; state<=READ_REQ;
                    end
                end
                default: state<=IDLE;
            endcase
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: combine MAX_K=1..4, MAX_TOKEN_ELEMS=1..256");
        assign cmd_ready=0; assign read_valid=0; assign read_rank=0; assign read_elem=0;
        assign sample_ready=0; assign out_valid=0; assign out_data=0;
        assign out_token_id=0; assign out_elem=0; assign out_last=0; assign idle=0;
    end endgenerate
endmodule
`default_nettype wire
