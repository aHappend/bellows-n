`default_nettype none
module bellows_n5_payload_ram #(
    parameter integer DATA_WIDTH=512,
    parameter integer BYTES=512,
    parameter integer AW=16
) (
    input wire clk,
    input wire we,
    input wire [AW-1:0] waddr,
    input wire [DATA_WIDTH-1:0] wdata,
    input wire [(DATA_WIDTH>>3)-1:0] wkeep,
    input wire re,
    input wire [AW-1:0] raddr,
    output wire [DATA_WIDTH-1:0] rdata
);
    localparam integer B=DATA_WIDTH>>3;
    localparam integer SHIFT=(DATA_WIDTH==512)?6:3;
    localparam integer WORDS=(BYTES+B-1)>>SHIFT;
    localparam integer ROW_AW=(WORDS>1)?$clog2(WORDS):1;
    wire [AW-1:0] write_row_full=waddr>>SHIFT;
    wire [AW-1:0] read_row_full=raddr>>SHIFT;
    wire [ROW_AW-1:0] write_row=write_row_full;
    wire [ROW_AW-1:0] read_row=read_row_full;
    wire write_enable=we && write_row_full<WORDS;
    wire read_enable=re && read_row_full<WORDS;
    genvar lane;
    generate for (lane=0;lane<B;lane=lane+1) begin : g_lane
        (* ramstyle="M20K", nomem2reg *) reg [7:0] bytes [0:WORDS-1];
        reg [7:0] q;
        always @(posedge clk) begin
            if (write_enable && wkeep[lane]) bytes[write_row]<=wdata[8*lane +:8];
            if (read_enable) q<=bytes[read_row];
        end
        assign rdata[8*lane +:8]=q;
    end endgenerate
endmodule
`default_nettype wire
