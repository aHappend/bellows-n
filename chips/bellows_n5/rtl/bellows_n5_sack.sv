`default_nettype none
module bellows_n5_sack #(
    parameter integer DATA_WIDTH=512
) (
    input wire clk, rst_n,
    input wire snapshot_valid,
    output wire snapshot_ready,
    input wire [2:0] snapshot_qp,
    input wire [23:0] snapshot_psn, snapshot_base,
    input wire [255:0] snapshot_bitmap,
    input wire [1:0] snapshot_status,
    input wire [23:0] local_qpn, remote_qpn,
    output wire cmd_valid,
    input wire cmd_ready,
    output wire [2:0] cmd_qp,
    output wire [511:0] cmd_meta,
    output wire payload_tvalid,
    input wire payload_tready,
    output wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] payload_tdata,
    output wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] payload_tkeep,
    output wire payload_tlast,
    output wire idle
);
    generate if (DATA_WIDTH==64 || DATA_WIDTH==512) begin : g_legal
        localparam integer B=DATA_WIDTH>>3;
        localparam IDLE=0, COMMAND=1, PAYLOAD=2;
        reg [1:0] state;
        reg [2:0] qp;
        reg [511:0] meta;
        reg [255:0] bitmap;
        reg [5:0] offset;
        reg [DATA_WIDTH-1:0] data_out;
        reg [B-1:0] keep_out;
        integer lane;
        always @* begin
            data_out=0; keep_out=0;
            if (rst_n && state==PAYLOAD) begin
                for (lane=0;lane<B;lane=lane+1)
                    if (offset+lane<32) begin
                        data_out[8*lane +:8]=bitmap[8*(offset+lane) +:8];
                        keep_out[lane]=1;
                    end
            end
        end
        assign snapshot_ready=rst_n && state==IDLE;
        assign cmd_valid=rst_n && state==COMMAND;
        assign cmd_qp=rst_n ? qp : 3'b0;
        assign cmd_meta=rst_n ? meta : 512'b0;
        assign payload_tvalid=rst_n && state==PAYLOAD;
        assign payload_tdata=data_out;
        assign payload_tkeep=keep_out;
        assign payload_tlast=rst_n && state==PAYLOAD && offset+B>=32;
        assign idle=rst_n && state==IDLE;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin state<=IDLE; qp<=0; meta<=0; bitmap<=0; offset<=0; end
            else case (state)
                IDLE: if (snapshot_valid) begin
                    qp<=snapshot_qp; bitmap<=snapshot_bitmap; offset<=0;
                    meta<=0;
                    meta[0 +:32]<=32'h21355846;
                    meta[8*4 +:8]<=1; meta[8*5 +:8]<=4;
                    meta[8*6 +:8]<=2; meta[8*7 +:8]<=1;
                    meta[8*8 +:8]<=remote_qpn[23:16];
                    meta[8*9 +:8]<=remote_qpn[15:8];
                    meta[8*10 +:8]<=remote_qpn[7:0];
                    meta[8*12 +:8]<=snapshot_psn[23:16];
                    meta[8*13 +:8]<=snapshot_psn[15:8];
                    meta[8*14 +:8]<=snapshot_psn[7:0];
                    meta[8*15 +:8]<={6'b0,snapshot_psn[1:0]};
                    meta[8*16 +:8]<=local_qpn[23:16];
                    meta[8*17 +:8]<=local_qpn[15:8];
                    meta[8*18 +:8]<=local_qpn[7:0];
                    meta[8*33 +:8]<=32;
                    meta[8*52 +:8]<=snapshot_base[23:16];
                    meta[8*53 +:8]<=snapshot_base[15:8];
                    meta[8*54 +:8]<=snapshot_base[7:0];
                    meta[8*55 +:8]<={6'b0,snapshot_status};
                    state<=COMMAND;
                end
                COMMAND: if (cmd_ready) state<=PAYLOAD;
                PAYLOAD: if (payload_tready) begin
                    if (offset+B>=32) state<=IDLE;
                    else offset<=offset+B;
                end
                default: state<=IDLE;
            endcase
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: SACK DATA_WIDTH=64/512 required");
        assign snapshot_ready=0; assign cmd_valid=0; assign cmd_qp=0; assign cmd_meta=0;
        assign payload_tvalid=0; assign payload_tdata=0; assign payload_tkeep=0;
        assign payload_tlast=0; assign idle=0;
    end endgenerate
endmodule
`default_nettype wire
