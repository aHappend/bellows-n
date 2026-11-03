`default_nettype none
module furnace_reduce_alu #(
    parameter integer DATA_WIDTH=512
) (
    input wire clk, rst_n, in_valid,
    input wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] in_a, in_b,
    input wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] in_keep,
    input wire [1:0] in_format, in_op,
    input wire in_last,
    output wire in_ready, out_valid,
    output wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] out_data,
    output wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] out_keep,
    output wire out_last,
    input wire out_ready
);
    generate if (DATA_WIDTH==64 || DATA_WIDTH==512) begin : g_legal
        localparam integer B=DATA_WIDTH>>3;
        reg [7:0] valid_pipe, last_pipe;
        reg [B-1:0] keep_pipe [0:7];
        reg [1:0] format_pipe [0:7];
        wire advance=rst_n && (!valid_pipe[7] || out_ready);
        assign in_ready=advance;
        assign out_valid=rst_n && valid_pipe[7];
        assign out_last=rst_n && valid_pipe[7] && last_pipe[7];
        assign out_keep=(rst_n && valid_pipe[7]) ? keep_pipe[7] : {B{1'b0}};
        wire [B-1:0] legal_keep;
        genvar word, half;
        for (word=0;word<(DATA_WIDTH>>5);word=word+1) begin : g_word
            wire [31:0] full_result;
            furnace_reduce_lane #(.HALF(0)) full_lane (
                .clk(clk), .rst_n(rst_n), .advance(advance),
                .a(in_a[word*32 +:32]), .b(in_b[word*32 +:32]),
                .active(in_valid && in_format==2 && (&in_keep[word*4 +:4])),
                .integer_mode(1'b0), .op(in_op), .result(full_result)
            );
            for (half=0;half<2;half=half+1) begin : g_half
                wire [31:0] half_result;
                wire pair_active=&in_keep[word*4+half*2 +:2];
                furnace_reduce_lane #(.HALF(1)) half_lane (
                    .clk(clk), .rst_n(rst_n), .advance(advance),
                    .a({16'b0,in_a[word*32+half*16 +:16]}),
                    .b({16'b0,in_b[word*32+half*16 +:16]}),
                    .active(in_valid && in_format<2 && pair_active),
                    .integer_mode(in_format==0), .op(in_op), .result(half_result)
                );
                assign legal_keep[word*4+half*2 +:2]=
                    (in_format==2) ? {2{&in_keep[word*4 +:4]}} :
                    (in_format<2) ? {2{pair_active}} : 2'b0;
                assign out_data[word*32+half*16 +:16]=
                    (!rst_n || !valid_pipe[7] ||
                     !keep_pipe[7][word*4+half*2]) ? 16'b0 :
                    (format_pipe[7]==2) ? full_result[half*16 +:16] :
                    (format_pipe[7]==1) ? half_result[31:16] : half_result[15:0];
            end
        end
        integer s;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                valid_pipe<=0; last_pipe<=0;
                for (s=0;s<8;s=s+1) begin keep_pipe[s]<=0; format_pipe[s]<=0; end
            end else if (advance) begin
                valid_pipe<={valid_pipe[6:0],in_valid};
                last_pipe<={last_pipe[6:0],in_last};
                keep_pipe[0]<=legal_keep; format_pipe[0]<=in_format;
                for (s=1;s<8;s=s+1) begin
                    keep_pipe[s]<=keep_pipe[s-1]; format_pipe[s]<=format_pipe[s-1];
                end
            end
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: reduce DATA_WIDTH must be 64 or 512");
        assign in_ready=0; assign out_valid=0; assign out_data=0;
        assign out_keep=0; assign out_last=0;
    end endgenerate
endmodule
`default_nettype wire
