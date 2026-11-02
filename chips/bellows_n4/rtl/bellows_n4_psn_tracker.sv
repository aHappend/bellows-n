`default_nettype none
module furnace_psn_tracker #(
    parameter integer QPS=8
) (
    input wire clk, rst_n, idle_allow,
    input wire cfg_valid,
    output wire cfg_ready,
    input wire cfg_enable,
    input wire [2:0] cfg_index,
    input wire [23:0] cfg_local_qpn, cfg_remote_qpn, cfg_expected_psn,
    input wire [31:0] cfg_rkey,
    input wire [63:0] cfg_base, cfg_length,
    input wire [2:0] cfg_rank,
    output wire cfg_rsp_valid,
    input wire cfg_rsp_ready,
    output reg [2:0] cfg_rsp_status,
    output wire [7:0] enabled,
    output wire [23:0] ranks,
    output wire [511:0] bases, lengths,
    input wire request_valid,
    output wire request_ready,
    input wire [7:0] request_opcode,
    input wire [23:0] request_qpn, request_psn,
    input wire [63:0] request_addr,
    input wire [31:0] request_rkey, request_message_bytes,
    input wire [13:0] request_payload_bytes,
    output wire result_valid,
    input wire result_ready,
    output reg [3:0] result_status,
    output reg [2:0] result_index, result_rank,
    output reg [23:0] result_expected, result_remote_qpn, result_msn,
    output reg [63:0] result_address,
    output reg result_complete, result_duplicate, result_found,
    output reg [7:0] result_syndrome,
    input wire commit, cancel
);
    localparam integer N=(QPS>=1 && QPS<=8) ? QPS : 1;
    localparam IDLE=0, LOOKUP=1, VALIDATE=2, BOUNDS=3, RESULT=4, WAIT_COMMIT=5;
    reg [2:0] state, cursor;
    reg [N-1:0] enable_bits, message_open, committed_bits;
    reg [23:0] local_qpn [0:N-1], remote_qpn [0:N-1], expected [0:N-1], msn [0:N-1];
    reg [31:0] keys [0:N-1], total [0:N-1], offset [0:N-1];
    reg [63:0] base [0:N-1], length [0:N-1], message_addr [0:N-1];
    reg [2:0] rank [0:N-1];
    reg cfg_pending;
    reg [7:0] op;
    reg [23:0] qpn, psn;
    reg [63:0] addr;
    reg [31:0] key, message_length;
    reg [13:0] payload_length;
    reg next_open;
    reg [31:0] next_total, next_offset;
    reg [63:0] next_message_addr;
    reg [64:0] region_end, message_end, packet_end;
    reg [32:0] offset_end;
    reg cfg_duplicate;
    wire [64:0] cfg_end={1'b0,cfg_base}+{1'b0,cfg_length};
    integer i;
    always @* begin
        cfg_duplicate=0;
        for (i=0;i<N;i=i+1)
            if (enable_bits[i] && i!=cfg_index && local_qpn[i]==cfg_local_qpn)
                cfg_duplicate=1;
    end
    assign cfg_ready=rst_n && idle_allow && state==IDLE && !cfg_pending;
    assign cfg_rsp_valid=rst_n && cfg_pending;
    assign request_ready=rst_n && state==IDLE && !cfg_pending && !cfg_valid;
    assign result_valid=rst_n && state==RESULT;
    genvar q;
    generate for (q=0;q<8;q=q+1) begin : g_export
        if (q<N) begin : g_present
            assign enabled[q]=rst_n && enable_bits[q];
            assign ranks[q*3 +:3]=rst_n ? rank[q] : 3'b0;
            assign bases[q*64 +:64]=rst_n ? base[q] : 64'b0;
            assign lengths[q*64 +:64]=rst_n ? length[q] : 64'b0;
        end else begin : g_absent
            assign enabled[q]=0; assign ranks[q*3 +:3]=0;
            assign bases[q*64 +:64]=0; assign lengths[q*64 +:64]=0;
        end
    end endgenerate
    integer n;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; cursor<=0; enable_bits<=0; message_open<=0; committed_bits<=0;
            cfg_pending<=0; cfg_rsp_status<=0;
            op<=0; qpn<=0; psn<=0; addr<=0; key<=0;
            message_length<=0; payload_length<=0;
            next_open<=0; next_total<=0; next_offset<=0; next_message_addr<=0;
            region_end<=0; message_end<=0; packet_end<=0; offset_end<=0;
            result_status<=0; result_index<=0; result_rank<=0;
            result_expected<=0; result_remote_qpn<=0; result_msn<=0;
            result_address<=0; result_complete<=0; result_duplicate<=0; result_found<=0;
            result_syndrome<=0;
            for (n=0;n<N;n=n+1) begin
                local_qpn[n]<=0; remote_qpn[n]<=0; expected[n]<=0; msn[n]<=0;
                keys[n]<=0; total[n]<=0; offset[n]<=0;
                base[n]<=0; length[n]<=0; message_addr[n]<=0; rank[n]<=0;
            end
        end else begin
            if (cfg_pending && cfg_rsp_ready) cfg_pending<=0;
            if (cfg_valid && cfg_ready) begin
                cfg_pending<=1;
                if (cfg_index>=QPS || (cfg_enable && cfg_duplicate)) cfg_rsp_status<=1;
                else if (cfg_enable && (cfg_length==0 || cfg_end[64])) cfg_rsp_status<=2;
                else begin
                    cfg_rsp_status<=0;
                    enable_bits[cfg_index]<=cfg_enable;
                    local_qpn[cfg_index]<=cfg_local_qpn; remote_qpn[cfg_index]<=cfg_remote_qpn;
                    expected[cfg_index]<=cfg_expected_psn; keys[cfg_index]<=cfg_rkey;
                    base[cfg_index]<=cfg_base; length[cfg_index]<=cfg_length;
                    rank[cfg_index]<=cfg_rank; message_open[cfg_index]<=0;
                    committed_bits[cfg_index]<=0;
                    total[cfg_index]<=0; offset[cfg_index]<=0;
                    message_addr[cfg_index]<=0; msn[cfg_index]<=0;
                end
            end
            case (state)
                IDLE: if (request_valid && request_ready) begin
                    op<=request_opcode; qpn<=request_qpn; psn<=request_psn;
                    addr<=request_addr; key<=request_rkey;
                    message_length<=request_message_bytes; payload_length<=request_payload_bytes;
                    cursor<=0; result_status<=5; result_found<=0;
                    result_index<=0; result_rank<=0; result_expected<=0;
                    result_remote_qpn<=0; result_msn<=0; result_address<=0;
                    result_complete<=0; result_duplicate<=0; state<=LOOKUP;
                    result_syndrome<=8'h61;
                end
                LOOKUP: begin
                    if (enable_bits[cursor] && local_qpn[cursor]==qpn) begin
                        result_found<=1; result_index<=cursor; result_rank<=rank[cursor];
                        result_expected<=expected[cursor]; result_remote_qpn<=remote_qpn[cursor];
                        result_msn<=msn[cursor]; region_end<={1'b0,base[cursor]}+{1'b0,length[cursor]};
                        if (op!=8'h06 && op!=8'h07 && op!=8'h08 &&
                            op!=8'h09 && op!=8'h0a && op!=8'h0b) begin
                            result_status<=4; state<=RESULT;
                        end else if (psn!=expected[cursor]) begin
                            result_status<=6;
                            result_syndrome<=8'h60;
                            result_duplicate<=committed_bits[cursor] &&
                                              psn==(expected[cursor]-24'd1);
                            state<=RESULT;
                        end else begin result_status<=0; state<=VALIDATE; end
                    end else if (cursor==QPS-1) state<=RESULT;
                    else cursor<=cursor+1'b1;
                end
                VALIDATE: begin
                    result_complete<=0;
                    next_open<=message_open[cursor]; next_total<=total[cursor];
                    next_offset<=offset[cursor]; next_message_addr<=message_addr[cursor];
                    if (op==8'h06 || op==8'h0a || op==8'h0b) begin
                        result_address<=addr;
                        message_end<={1'b0,addr}+{33'b0,message_length};
                        packet_end<={1'b0,addr}+{51'b0,payload_length};
                        offset_end<={19'b0,payload_length};
                        next_message_addr<=addr; next_total<=message_length;
                        next_offset<={18'b0,payload_length};
                        if (message_open[cursor] || key!=keys[cursor] ||
                            ((op==8'h06) && {18'b0,payload_length}>message_length) ||
                            ((op!=8'h06) && {18'b0,payload_length}!=message_length))
                            result_status<=7;
                        if (key!=keys[cursor]) result_syndrome<=8'h62;
                        next_open<=op==8'h06;
                        result_complete<=op!=8'h06;
                    end else if (op==8'h07 || op==8'h08 || op==8'h09) begin
                        result_address<=message_open[cursor] ?
                                        message_addr[cursor]+{32'b0,offset[cursor]} : 64'b0;
                        message_end<={1'b0,message_addr[cursor]}+{33'b0,total[cursor]};
                        packet_end<={1'b0,message_addr[cursor]}+
                                    {33'b0,offset[cursor]}+{51'b0,payload_length};
                        offset_end<={1'b0,offset[cursor]}+{19'b0,payload_length};
                        next_offset<=offset[cursor]+{18'b0,payload_length};
                        if (!message_open[cursor] ||
                            ((op==8'h07) &&
                             ({1'b0,offset[cursor]}+{19'b0,payload_length}>{1'b0,total[cursor]})) ||
                            ((op!=8'h07) &&
                             ({1'b0,offset[cursor]}+{19'b0,payload_length}!={1'b0,total[cursor]})))
                            result_status<=7;
                        if (op!=8'h07) begin next_open<=0; result_complete<=1; end
                    end else result_status<=4;
                    state<=BOUNDS;
                end
                BOUNDS: begin
                    if (result_status==0 &&
                        (message_end[64] || packet_end[64] || offset_end[32] ||
                         result_address<base[cursor] || message_end>region_end ||
                         packet_end>message_end)) begin
                        result_status<=7; result_syndrome<=8'h62;
                    end
                    state<=RESULT;
                end
                RESULT: if (result_ready) begin
                    if (result_status==0) state<=WAIT_COMMIT;
                    else state<=IDLE;
                end
                WAIT_COMMIT: begin
                    if (cancel) state<=IDLE;
                    else if (commit) begin
                        expected[result_index]<=expected[result_index]+24'd1;
                        committed_bits[result_index]<=1;
                        message_open[result_index]<=next_open;
                        total[result_index]<=next_total; offset[result_index]<=next_offset;
                        message_addr[result_index]<=next_message_addr;
                        if (result_complete) msn[result_index]<=msn[result_index]+24'd1;
                        state<=IDLE;
                    end
                end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
