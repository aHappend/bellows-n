`default_nettype none
module bellows_n5_packet_tx #(
    parameter integer DATA_WIDTH=512
) (
    input wire clk, rst_n,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [2:0] cmd_qp,
    input wire [511:0] cmd_meta,
    input wire payload_tvalid,
    output wire payload_tready,
    input wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] payload_tdata,
    input wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] payload_tkeep,
    input wire payload_tlast,
    input wire [383:0] local_macs, remote_macs,
    input wire [255:0] local_ips, remote_ips,
    output wire tx_tvalid,
    input wire tx_tready,
    output wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] tx_tdata,
    output wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] tx_tkeep,
    output wire tx_tlast,
    output wire packet_done,
    output wire [2:0] packet_qp,
    output wire packet_is_sack,
    output wire idle
);
    generate if (DATA_WIDTH==64 || DATA_WIDTH==512) begin : g_legal
        localparam integer B=DATA_WIDTH>>3;
        localparam IDLE=0, PAYLOAD=1, CHECKSUM=2, FOLD=3, BUILD=4,
                   CRC_FETCH=5, CRC_USE=6, TRAILER=7,
                   OUT_FETCH=8, OUT_USE=9, OUT_SEND=10,
                   SUM_PAIRS=11, SUM_TOTAL=12;
        reg [3:0] state;
        reg [2:0] qp;
        reg [511:0] meta;
        reg [47:0] source_mac, dest_mac;
        reg [31:0] source_ip, dest_ip;
        reg [8:0] payload_bytes, input_offset, crc_offset;
        reg [8:0] frame_bytes, output_offset;
        reg [6:0] build_offset;
        reg [1:0] trailer_offset;
        reg [6:0] lane;
        reg [DATA_WIDTH-1:0] output_data;
        reg [B-1:0] output_keep;
        reg [31:0] crc, trailer;
        reg [19:0] checksum_sum;
        reg [16:0] checksum_a, checksum_b, checksum_c, checksum_d;
        reg [17:0] checksum_ab, checksum_cd;
        reg [15:0] checksum;
        (* nomem2reg *) reg [7:0] frame [0:365];
        reg [7:0] frame_q;
        wire [15:0] ip_length=16'd96+{7'b0,payload_bytes};
        wire [15:0] udp_length=16'd76+{7'b0,payload_bytes};
        wire [15:0] source_port=16'hc000+{14'b0,meta[8*15 +:2]};
        wire [16:0] checksum_fold={1'b0,checksum_sum[15:0]}+
                                 {13'b0,checksum_sum[19:16]};
        wire [15:0] checksum_final=checksum_fold[15:0]+{15'b0,checksum_fold[16]};
        function automatic [31:0] crc_byte;
            input [31:0] value;
            input [7:0] byte_value;
            reg [31:0] c;
            integer bit_index;
            begin
                c=value^{24'b0,byte_value};
                for (bit_index=0;bit_index<8;bit_index=bit_index+1)
                    c=c[0] ? ((c>>1)^32'h82f63b78) : (c>>1);
                crc_byte=c;
            end
        endfunction
        reg [7:0] build_byte;
        always @* begin
            build_byte=0;
            if (build_offset<6) build_byte=dest_mac>>(8*(5-build_offset));
            else if (build_offset<12) build_byte=source_mac>>(8*(11-build_offset));
            else case (build_offset)
                12: build_byte=8'h08;
                13: build_byte=0;
                14: build_byte=8'h45;
                15: build_byte=0;
                16: build_byte=ip_length[15:8];
                17: build_byte=ip_length[7:0];
                18,19: build_byte=0;
                20: build_byte=8'h40;
                21: build_byte=0;
                22: build_byte=8'h40;
                23: build_byte=8'h11;
                24: build_byte=checksum[15:8];
                25: build_byte=checksum[7:0];
                26: build_byte=source_ip[31:24];
                27: build_byte=source_ip[23:16];
                28: build_byte=source_ip[15:8];
                29: build_byte=source_ip[7:0];
                30: build_byte=dest_ip[31:24];
                31: build_byte=dest_ip[23:16];
                32: build_byte=dest_ip[15:8];
                33: build_byte=dest_ip[7:0];
                34: build_byte=source_port[15:8];
                35: build_byte=source_port[7:0];
                36: build_byte=8'h12;
                37: build_byte=8'hb8;
                38: build_byte=udp_length[15:8];
                39: build_byte=udp_length[7:0];
                40,41: build_byte=0;
                default: build_byte=meta[8*(build_offset-42) +:8];
            endcase
        end
        wire [31:0] header_crc=crc_byte(crc,build_byte);
        wire [31:0] payload_crc=crc_byte(crc,frame_q);
        integer w;
        always @(posedge clk) begin
            if (rst_n && state==PAYLOAD && payload_tvalid) begin
                for (w=0;w<B;w=w+1)
                    if (payload_tkeep[w] && input_offset+w<payload_bytes)
                        frame[106+input_offset+w]<=payload_tdata[8*w +:8];
            end
            if (rst_n && state==BUILD) frame[build_offset]<=build_byte;
            if (rst_n && state==TRAILER)
                frame[106+payload_bytes+trailer_offset]<=trailer[8*trailer_offset +:8];
            if (state==CRC_FETCH) frame_q<=frame[106+crc_offset];
            if (state==OUT_FETCH) frame_q<=frame[output_offset];
        end
        assign cmd_ready=rst_n && state==IDLE;
        assign payload_tready=rst_n && state==PAYLOAD;
        assign tx_tvalid=rst_n && state==OUT_SEND;
        assign tx_tdata=(rst_n && state==OUT_SEND) ? output_data : {DATA_WIDTH{1'b0}};
        assign tx_tkeep=(rst_n && state==OUT_SEND) ? output_keep : {B{1'b0}};
        assign tx_tlast=rst_n && state==OUT_SEND && output_offset==frame_bytes;
        assign packet_done=tx_tvalid && tx_tready && tx_tlast;
        assign packet_qp=rst_n ? qp : 3'b0;
        assign packet_is_sack=rst_n && meta[8*5 +:8]==4;
        assign idle=rst_n && state==IDLE;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; qp<=0; meta<=0; source_mac<=0; dest_mac<=0;
                source_ip<=0; dest_ip<=0; payload_bytes<=0; input_offset<=0;
                crc_offset<=0; frame_bytes<=0; output_offset<=0; build_offset<=0;
                trailer_offset<=0; lane<=0; output_data<=0; output_keep<=0;
                crc<=0; trailer<=0; checksum_sum<=0; checksum<=0;
                checksum_a<=0; checksum_b<=0; checksum_c<=0; checksum_d<=0;
                checksum_ab<=0; checksum_cd<=0;
            end else case (state)
                IDLE: if (cmd_valid) begin
                    qp<=cmd_qp; meta<=cmd_meta;
                    source_mac<=local_macs[48*cmd_qp +:48];
                    dest_mac<=remote_macs[48*cmd_qp +:48];
                    source_ip<=local_ips[32*cmd_qp +:32];
                    dest_ip<=remote_ips[32*cmd_qp +:32];
                    payload_bytes<={cmd_meta[8*32 +:8],cmd_meta[8*33 +:8]};
                    frame_bytes<=9'd110+{cmd_meta[8*32 +:8],cmd_meta[8*33 +:8]};
                    input_offset<=0; crc_offset<=0; output_offset<=0;
                    build_offset<=0; trailer_offset<=0; lane<=0;
                    output_data<=0; output_keep<=0; crc<=32'hffffffff;
                    state<=PAYLOAD;
                end
                PAYLOAD: if (payload_tvalid) begin
                    if (payload_tlast) state<=CHECKSUM;
                    else input_offset<=input_offset+B;
                end
                CHECKSUM: begin
                    checksum_a<=17'h04500+{1'b0,ip_length};
                    checksum_b<=17'h08011;
                    checksum_c<={1'b0,source_ip[31:16]}+{1'b0,source_ip[15:0]};
                    checksum_d<={1'b0,dest_ip[31:16]}+{1'b0,dest_ip[15:0]};
                    state<=SUM_PAIRS;
                end
                SUM_PAIRS: begin
                    checksum_ab<={1'b0,checksum_a}+{1'b0,checksum_b};
                    checksum_cd<={1'b0,checksum_c}+{1'b0,checksum_d};
                    state<=SUM_TOTAL;
                end
                SUM_TOTAL: begin
                    checksum_sum<={2'b0,checksum_ab}+{2'b0,checksum_cd};
                    state<=FOLD;
                end
                FOLD: begin checksum<=~checksum_final; state<=BUILD; end
                BUILD: begin
                    if (build_offset>=42) crc<=header_crc;
                    if (build_offset==105) state<=CRC_FETCH;
                    else build_offset<=build_offset+1'b1;
                end
                CRC_FETCH: state<=CRC_USE;
                CRC_USE: begin
                    crc<=payload_crc;
                    if (crc_offset+9'd1==payload_bytes) begin
                        trailer<=~payload_crc; state<=TRAILER;
                    end else begin crc_offset<=crc_offset+1'b1; state<=CRC_FETCH; end
                end
                TRAILER: begin
                    if (trailer_offset==3) state<=OUT_FETCH;
                    else trailer_offset<=trailer_offset+1'b1;
                end
                OUT_FETCH: state<=OUT_USE;
                OUT_USE: begin
                    output_data[8*lane +:8]<=frame_q; output_keep[lane]<=1;
                    output_offset<=output_offset+1'b1;
                    if (lane==B-1 || output_offset+9'd1==frame_bytes) state<=OUT_SEND;
                    else begin lane<=lane+1'b1; state<=OUT_FETCH; end
                end
                OUT_SEND: if (tx_tready) begin
                    if (output_offset==frame_bytes) state<=IDLE;
                    else begin
                        output_data<=0; output_keep<=0; lane<=0; state<=OUT_FETCH;
                    end
                end
                default: state<=IDLE;
            endcase
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: packet TX DATA_WIDTH=64/512 required");
        assign cmd_ready=0; assign payload_tready=0;
        assign tx_tvalid=0; assign tx_tdata=0; assign tx_tkeep=0; assign tx_tlast=0;
        assign packet_done=0; assign packet_qp=0; assign packet_is_sack=0; assign idle=0;
    end endgenerate
endmodule
`default_nettype wire
