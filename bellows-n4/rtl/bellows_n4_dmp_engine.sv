`default_nettype none
module furnace_dmp_engine #(
    parameter integer DATA_WIDTH=512
) (
    input wire clk, rst_n,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [63:0] cmd_addr,
    input wire [13:0] cmd_bytes,
    input wire in_valid,
    output wire in_ready,
    input wire [DATA_WIDTH-1:0] in_data,
    output wire wr_valid,
    input wire wr_ready,
    output wire [63:0] wr_addr,
    output wire [DATA_WIDTH-1:0] wr_data,
    output wire [(DATA_WIDTH>>3)-1:0] wr_keep,
    output wire wr_last,
    output wire done_valid,
    input wire done_ready
);
    localparam integer B=DATA_WIDTH>>3;
    localparam IDLE=0, ACTIVE=1, DONE=2;
    reg [1:0] state;
    reg [63:0] address;
    reg [13:0] remaining;
    assign cmd_ready=rst_n && state==IDLE;
    assign wr_valid=rst_n && state==ACTIVE && in_valid;
    assign in_ready=rst_n && state==ACTIVE && wr_ready;
    assign wr_addr=rst_n ? address : 64'b0;
    assign wr_last=rst_n && state==ACTIVE && remaining<=B;
    assign done_valid=rst_n && state==DONE;
    genvar lane;
    generate for (lane=0;lane<B;lane=lane+1) begin : g_bytes
        assign wr_keep[lane]=rst_n && state==ACTIVE && lane<remaining;
        assign wr_data[lane*8 +:8]=wr_keep[lane] ? in_data[lane*8 +:8] : 8'b0;
    end endgenerate
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin state<=IDLE; address<=0; remaining<=0; end
        else begin
            case (state)
                IDLE: if (cmd_valid) begin
                    address<=cmd_addr; remaining<=cmd_bytes;
                    if (cmd_bytes==0) state<=DONE;
                    else state<=ACTIVE;
                end
                ACTIVE: if (wr_valid && wr_ready) begin
                    if (remaining<=B) begin remaining<=0; state<=DONE; end
                    else begin remaining<=remaining-B; address<=address+B; end
                end
                DONE: if (done_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
