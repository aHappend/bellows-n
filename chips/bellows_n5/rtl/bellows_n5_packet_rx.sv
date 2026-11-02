`default_nettype none
module bellows_n5_packet_rx #(
    parameter integer DATA_WIDTH=512,
    parameter integer QPS=8,
    parameter integer EXPERTS=8,
    parameter integer MAX_K=4,
    parameter integer MAX_TOKEN_ELEMS=256
) (
    input wire clk, rst_n,
    input wire rx_tvalid,
    output wire rx_tready,
    input wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] rx_tdata,
    input wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] rx_tkeep,
    input wire rx_tlast,
    input wire [7:0] enabled,
    input wire [191:0] local_qpns, remote_qpns,
    input wire [255:0] rkeys, local_ips, remote_ips,
    input wire [511:0] bases, lengths,
    input wire [383:0] local_macs, remote_macs,
    output wire cmd_valid,
    input wire cmd_ready,
    output wire [2:0] cmd_qp,
    output wire [511:0] cmd_meta,
    output wire payload_tvalid,
    input wire payload_tready,
    output wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] payload_tdata,
    output wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] payload_tkeep,
    output wire payload_tlast,
    output wire error_valid,
    input wire error_ready,
    output wire [3:0] error_status,
    output wire [7:0] error_kind,
    output wire [2:0] error_qp,
    output wire [31:0] error_token_id,
    output wire [23:0] error_psn,
    output wire idle
);
    generate if ((DATA_WIDTH==64 || DATA_WIDTH==512) && QPS>=1 && QPS<=8 &&
                 EXPERTS>=1 && EXPERTS<=16 && MAX_K>=1 && MAX_K<=4 &&
                 MAX_K<=EXPERTS && MAX_TOKEN_ELEMS>=1 && MAX_TOKEN_ELEMS<=256)
    begin : g_legal
        localparam integer B=DATA_WIDTH>>3;
        localparam CAPTURE=0, SCAN_FETCH=1, SCAN_USE=2, CHECK_FRAME=3,
                   LOOKUP=4, ENDPOINTS=5, REGION=6, PROTECT=7,
                   COMMAND=8, PAY_FETCH=9, PAY_USE=10, PAY_SEND=11, ERROR=12;
        reg [3:0] state;
        (* nomem2reg *) reg [7:0] frame [0:365];
        reg [7:0] frame_q;
        reg [8:0] frame_length, scan_offset, payload_offset;
        reg malformed;
        reg [335:0] envelope;
        reg [511:0] meta;
        reg [31:0] crc, received_crc;
        reg [19:0] ip_sum;
        reg [7:0] ip_high;
        reg [2:0] cursor, qp;
        reg [64:0] region_end, message_end;
        reg [63:0] region_base;
        reg [31:0] region_key;
        reg [47:0] local_mac, remote_mac;
        reg [31:0] local_ip, remote_ip;
        reg [23:0] remote_qpn;
        reg [DATA_WIDTH-1:0] output_data;
        reg [B-1:0] output_keep;
        reg [6:0] lane;
        reg [3:0] reject_status;
        reg trusted_identity;
        reg [6:0] beat_count;
        reg bad_keep, keep_gap;
        integer c;
        always @* begin
            beat_count=0; bad_keep=0; keep_gap=0;
            for (c=0;c<B;c=c+1) begin
                if (rx_tkeep[c]) begin
                    beat_count=beat_count+1'b1;
                    if (keep_gap) bad_keep=1;
                end else keep_gap=1;
            end
            if (beat_count==0 || (!rx_tlast && !(&rx_tkeep))) bad_keep=1;
        end
        wire [9:0] capture_length={1'b0,frame_length}+{3'b0,beat_count};
        wire [7:0] kind=meta[8*5 +:8];
        wire [7:0] format=meta[8*6 +:8];
        wire [7:0] flags=meta[8*7 +:8];
        wire [23:0] destination_qpn={meta[8*8 +:8],meta[8*9 +:8],meta[8*10 +:8]};
        wire [23:0] source_qpn={meta[8*16 +:8],meta[8*17 +:8],meta[8*18 +:8]};
        wire [23:0] psn={meta[8*12 +:8],meta[8*13 +:8],meta[8*14 +:8]};
        wire [31:0] token_id={meta[8*20 +:8],meta[8*21 +:8],
                              meta[8*22 +:8],meta[8*23 +:8]};
        wire [15:0] expert_id={meta[8*24 +:8],meta[8*25 +:8]};
        wire [7:0] rank=meta[8*26 +:8];
        wire [7:0] count_k=meta[8*27 +:8];
        wire [15:0] count={meta[8*28 +:8],meta[8*29 +:8]};
        wire [15:0] offset={meta[8*30 +:8],meta[8*31 +:8]};
        wire [15:0] payload_bytes={meta[8*32 +:8],meta[8*33 +:8]};
        wire [63:0] address={meta[8*36 +:8],meta[8*37 +:8],meta[8*38 +:8],
                             meta[8*39 +:8],meta[8*40 +:8],meta[8*41 +:8],
                             meta[8*42 +:8],meta[8*43 +:8]};
        wire [31:0] key={meta[8*44 +:8],meta[8*45 +:8],
                         meta[8*46 +:8],meta[8*47 +:8]};
        wire [15:0] weight={meta[8*48 +:8],meta[8*49 +:8]};
        wire [16:0] total_bytes=(format==1) ? {count,1'b0} : {1'b0,count};
        wire [16:0] offset_bytes=(format==1) ? {offset,1'b0} : {1'b0,offset};
        wire [17:0] fragment_end={1'b0,offset_bytes}+{2'b0,payload_bytes};
        wire [15:0] ip_length={envelope[8*16 +:8],envelope[8*17 +:8]};
        wire [15:0] udp_length={envelope[8*38 +:8],envelope[8*39 +:8]};
        wire [16:0] folded_sum={1'b0,ip_sum[15:0]}+{13'b0,ip_sum[19:16]};
        wire [15:0] final_sum=folded_sum[15:0]+{15'b0,folded_sum[16]};
        wire [47:0] eth_destination={envelope[8*0 +:8],envelope[8*1 +:8],
            envelope[8*2 +:8],envelope[8*3 +:8],envelope[8*4 +:8],envelope[8*5 +:8]};
        wire [47:0] eth_source={envelope[8*6 +:8],envelope[8*7 +:8],
            envelope[8*8 +:8],envelope[8*9 +:8],envelope[8*10 +:8],envelope[8*11 +:8]};
        wire [31:0] ip_source={envelope[8*26 +:8],envelope[8*27 +:8],
                               envelope[8*28 +:8],envelope[8*29 +:8]};
        wire [31:0] ip_destination={envelope[8*30 +:8],envelope[8*31 +:8],
                                    envelope[8*32 +:8],envelope[8*33 +:8]};
        wire reserved_nonzero=meta[8*11 +:8]!=0 || meta[8*19 +:8]!=0 ||
            meta[8*34 +:16]!=0 || meta[8*50 +:16]!=0 || meta[8*56 +:64]!=0;
        reg canonical;
        always @* begin
            canonical=1;
            if (meta[0 +:32]!=32'h21355846 || meta[8*4 +:8]!=1 ||
                kind<1 || kind>4 || flags>1 || meta[8*15 +:8]>3 ||
                reserved_nonzero || payload_bytes==0 || payload_bytes>256)
                canonical=0;
            if (kind==4) begin
                if (format!=2 || flags!=1 || payload_bytes!=32 ||
                    token_id!=0 || expert_id!=0 || rank!=0 || count_k!=0 ||
                    count!=0 || offset!=0 || address!=0 || key!=0 || weight!=0 ||
                    meta[8*55 +:8]>3) canonical=0;
            end else begin
                if (meta[8*52 +:32]!=0 || count==0 || offset_bytes[7:0]!=0 ||
                    fragment_end>{1'b0,total_bytes} ||
                    fragment_end==0 || {1'b0,offset_bytes}>={1'b0,total_bytes} ||
                    (flags[0] && fragment_end!={1'b0,total_bytes}) ||
                    (!flags[0] && (fragment_end>={1'b0,total_bytes} || payload_bytes!=256)))
                    canonical=0;
                if (kind==1) begin
                    if (format!=2 || expert_id!=0 || rank!=0 || count_k!=0 || weight!=0)
                        canonical=0;
                end else if (format>1 || count>MAX_TOKEN_ELEMS ||
                             expert_id>=EXPERTS || count_k==0 || count_k>MAX_K ||
                             rank>=count_k || address!=0 || key!=0)
                    canonical=0;
            end
        end
        wire envelope_ok=envelope[8*12 +:8]==8'h08 && envelope[8*13 +:8]==0 &&
            envelope[8*14 +:8]==8'h45 && envelope[8*15 +:8]==0 &&
            envelope[8*18 +:16]==0 && envelope[8*20 +:8]==8'h40 &&
            envelope[8*21 +:8]==0 && envelope[8*22 +:8]==8'h40 &&
            envelope[8*23 +:8]==8'h11 &&
            envelope[8*34 +:8]==8'hc0 &&
            envelope[8*35 +:8]==meta[8*15 +:8] &&
            envelope[8*36 +:8]==8'h12 && envelope[8*37 +:8]==8'hb8 &&
            envelope[8*40 +:16]==0;
        function automatic [31:0] crc_byte;
            input [31:0] value;
            input [7:0] byte_value;
            reg [31:0] v;
            integer n;
            begin
                v=value^{24'b0,byte_value};
                for (n=0;n<8;n=n+1)
                    v=v[0] ? ((v>>1)^32'h82f63b78) : (v>>1);
                crc_byte=v;
            end
        endfunction
        wire [31:0] crc_next=crc_byte(crc,frame_q);
        integer w;
        always @(posedge clk) begin
            if (rst_n && state==CAPTURE && rx_tvalid)
                for (w=0;w<B;w=w+1)
                    if (rx_tkeep[w] && frame_length+w<366)
                        frame[frame_length+w]<=rx_tdata[8*w +:8];
            if (state==SCAN_FETCH) frame_q<=frame[scan_offset];
            if (state==PAY_FETCH) frame_q<=frame[106+payload_offset];
        end
        assign rx_tready=rst_n && state==CAPTURE;
        assign cmd_valid=rst_n && state==COMMAND;
        assign cmd_qp=rst_n ? qp : 3'b0;
        assign cmd_meta=rst_n ? meta : 512'b0;
        assign payload_tvalid=rst_n && state==PAY_SEND;
        assign payload_tdata=(rst_n && state==PAY_SEND) ? output_data : {DATA_WIDTH{1'b0}};
        assign payload_tkeep=(rst_n && state==PAY_SEND) ? output_keep : {B{1'b0}};
        assign payload_tlast=rst_n && state==PAY_SEND && payload_offset==payload_bytes;
        assign error_valid=rst_n && state==ERROR;
        assign error_status=rst_n ? reject_status : 4'b0;
        assign error_kind=(rst_n && trusted_identity) ? kind : 8'b0;
        assign error_qp=(rst_n && trusted_identity) ? qp : 3'b0;
        assign error_token_id=(rst_n && trusted_identity) ? token_id : 32'b0;
        assign error_psn=(rst_n && trusted_identity) ? psn : 24'b0;
        assign idle=rst_n && state==CAPTURE && frame_length==0;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=CAPTURE; frame_length<=0; scan_offset<=0; payload_offset<=0;
                malformed<=0; envelope<=0; meta<=0; crc<=0; received_crc<=0;
                ip_sum<=0; ip_high<=0; cursor<=0; qp<=0;
                region_end<=0; message_end<=0; region_base<=0; region_key<=0;
                local_mac<=0; remote_mac<=0; local_ip<=0; remote_ip<=0; remote_qpn<=0;
                output_data<=0; output_keep<=0; lane<=0;
                reject_status<=0; trusted_identity<=0;
            end else case (state)
                CAPTURE: if (rx_tvalid) begin
                    if (capture_length>366) begin frame_length<=367; malformed<=1; end
                    else frame_length<=capture_length[8:0];
                    if (bad_keep) malformed<=1;
                    if (rx_tlast) begin
                        trusted_identity<=0; reject_status<=3;
                        if (malformed || bad_keep || capture_length<110 ||
                            capture_length>366) state<=ERROR;
                        else begin
                            envelope<=0; meta<=0; crc<=32'hffffffff; received_crc<=0;
                            ip_sum<=0; ip_high<=0; scan_offset<=0; state<=SCAN_FETCH;
                        end
                    end
                end
                SCAN_FETCH: state<=SCAN_USE;
                SCAN_USE: begin
                    if (scan_offset<42) envelope[8*scan_offset +:8]<=frame_q;
                    else if (scan_offset<106) meta[8*(scan_offset-42) +:8]<=frame_q;
                    if (scan_offset>=14 && scan_offset<34) begin
                        if (!scan_offset[0]) ip_high<=frame_q;
                        else ip_sum<=ip_sum+{4'b0,ip_high,frame_q};
                    end
                    if (scan_offset>=42 && scan_offset<frame_length-9'd4)
                        crc<=crc_next;
                    if (scan_offset>=frame_length-9'd4)
                        received_crc[8*(scan_offset-(frame_length-9'd4)) +:8]<=frame_q;
                    if (scan_offset+9'd1==frame_length) state<=CHECK_FRAME;
                    else begin scan_offset<=scan_offset+1'b1; state<=SCAN_FETCH; end
                end
                CHECK_FRAME: begin
                    if (!canonical || !envelope_ok ||
                        {7'b0,frame_length}!=16'd110+payload_bytes ||
                        ip_length!=16'd96+payload_bytes ||
                        udp_length!=16'd76+payload_bytes) begin
                        reject_status<=3; state<=ERROR;
                    end else if (received_crc!=~crc || final_sum!=16'hffff) begin
                        reject_status<=4; state<=ERROR;
                    end else begin cursor<=0; state<=LOOKUP; end
                end
                LOOKUP: begin
                    if (enabled[cursor] && local_qpns[24*cursor +:24]==destination_qpn) begin
                        qp<=cursor; local_mac<=local_macs[48*cursor +:48];
                        remote_mac<=remote_macs[48*cursor +:48];
                        local_ip<=local_ips[32*cursor +:32]; remote_ip<=remote_ips[32*cursor +:32];
                        remote_qpn<=remote_qpns[24*cursor +:24];
                        region_base<=bases[64*cursor +:64]; region_key<=rkeys[32*cursor +:32];
                        state<=ENDPOINTS;
                    end else if (cursor==QPS-1) begin reject_status<=5; state<=ERROR; end
                    else cursor<=cursor+1'b1;
                end
                ENDPOINTS: begin
                    if (eth_destination!=local_mac || eth_source!=remote_mac ||
                        ip_destination!=local_ip || ip_source!=remote_ip ||
                        source_qpn!=remote_qpn) begin reject_status<=5; state<=ERROR; end
                    else begin trusted_identity<=1; state<=REGION; end
                end
                REGION: begin
                    region_end<={1'b0,region_base}+{1'b0,lengths[64*qp +:64]};
                    message_end<={1'b0,address}+{49'b0,count};
                    state<=PROTECT;
                end
                PROTECT: begin
                    if (kind==1 && (key!=region_key || message_end[64] ||
                        region_end[64] || address<region_base || message_end>region_end)) begin
                        reject_status<=6; state<=ERROR;
                    end else begin
                        output_data<=0; output_keep<=0; lane<=0; payload_offset<=0;
                        state<=COMMAND;
                    end
                end
                COMMAND: if (cmd_ready) state<=PAY_FETCH;
                PAY_FETCH: state<=PAY_USE;
                PAY_USE: begin
                    output_data[8*lane +:8]<=frame_q; output_keep[lane]<=1;
                    payload_offset<=payload_offset+1'b1;
                    if (lane==B-1 || payload_offset+9'd1==payload_bytes) state<=PAY_SEND;
                    else begin lane<=lane+1'b1; state<=PAY_FETCH; end
                end
                PAY_SEND: if (payload_tready) begin
                    if (payload_offset==payload_bytes) begin
                        frame_length<=0; malformed<=0; state<=CAPTURE;
                    end else begin
                        output_data<=0; output_keep<=0; lane<=0; state<=PAY_FETCH;
                    end
                end
                ERROR: if (error_ready) begin
                    frame_length<=0; malformed<=0; state<=CAPTURE;
                end
                default: state<=CAPTURE;
            endcase
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: packet RX geometry outside X5 legal ranges");
        assign rx_tready=0; assign cmd_valid=0; assign cmd_qp=0; assign cmd_meta=0;
        assign payload_tvalid=0; assign payload_tdata=0; assign payload_tkeep=0;
        assign payload_tlast=0; assign error_valid=0; assign error_status=0;
        assign error_kind=0; assign error_qp=0; assign error_token_id=0;
        assign error_psn=0; assign idle=0;
    end endgenerate
endmodule
`default_nettype wire
