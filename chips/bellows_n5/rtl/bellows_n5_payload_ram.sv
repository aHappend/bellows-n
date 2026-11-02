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
    genvar lane;
    generate for (lane=0;lane<B;lane=lane+1) begin : g_lane
        (* ramstyle="M20K", nomem2reg *) reg [7:0] bytes [0:WORDS-1];
        reg [7:0] q;
        always @(posedge clk) begin
            if (we && wkeep[lane]) bytes[waddr>>SHIFT]<=wdata[8*lane +:8];
            if (re) q<=bytes[raddr>>SHIFT];
        end
        assign rdata[8*lane +:8]=q;
    end endgenerate
endmodule
`default_nettype wire
