`default_nettype none
module furnace_roce_rx #(
    parameter integer DATA_WIDTH=512,
    parameter integer MAX_PACKET_BYTES=9216,
    parameter integer QPS=8
) (
    input wire clk, rst_n, enable,
    output wire idle,
    input wire s_valid,
    output wire s_ready,
    input wire [DATA_WIDTH-1:0] s_data,
    input wire [(DATA_WIDTH>>3)-1:0] s_keep,
    input wire s_last,
    input wire qp_cfg_valid,
    output wire qp_cfg_ready,
    input wire qp_cfg_enable,
    input wire [2:0] qp_cfg_index,
    input wire [23:0] qp_cfg_local_qpn, qp_cfg_remote_qpn, qp_cfg_expected_psn,
    input wire [31:0] qp_cfg_rkey,
    input wire [63:0] qp_cfg_base, qp_cfg_length,
    input wire [2:0] qp_cfg_rank,
    output wire qp_cfg_rsp_valid,
    input wire qp_cfg_rsp_ready,
    output wire [2:0] qp_cfg_rsp_status,
    input wire coll_cfg_valid,
    output wire coll_cfg_ready,
    input wire coll_cfg_enable,
    input wire [15:0] coll_cfg_job,
    input wire [1:0] coll_cfg_format, coll_cfg_op,
    input wire [3:0] coll_cfg_participants,
    input wire [31:0] coll_cfg_bytes,
    input wire [63:0] coll_cfg_addr,
    output wire coll_cfg_rsp_valid,
    input wire coll_cfg_rsp_ready,
    output wire [2:0] coll_cfg_rsp_status,
    output wire wr_valid,
    input wire wr_ready,
    output wire [63:0] wr_addr,
    output wire [DATA_WIDTH-1:0] wr_data,
    output wire [(DATA_WIDTH>>3)-1:0] wr_keep,
    output wire wr_last,
    output wire rdma_evt_valid,
    input wire rdma_evt_ready,
    output wire [3:0] rdma_evt_status,
    output wire [23:0] rdma_evt_qpn, rdma_evt_psn, rdma_evt_expected_psn,
    output wire [31:0] rdma_evt_bytes,
    output wire [63:0] rdma_evt_addr,
    output wire ack_valid,
    input wire ack_ready,
    output wire [127:0] ack_data,
    output wire [23:0] ack_local_qpn, ack_remote_qpn, ack_psn,
    output wire coll_done_valid,
    input wire coll_done_ready,
    output wire [15:0] coll_done_job,
    output wire [31:0] coll_done_bytes
);
    localparam integer B=DATA_WIDTH>>3;
    localparam integer SHIFT=(DATA_WIDTH==64) ? 3 : 6;
    localparam integer ROWS=(MAX_PACKET_BYTES+B-1)>>SHIFT;
    localparam CAPTURE=0, PARSE_START=1, PARSE_WAIT=2, TRACK_START=3,
               TRACK_WAIT=4, DMP_CMD=5, COLL_CMD=6, WORK_DMP=7,
               WORK_COLL=8, EMIT=9, RETIRE=10;
    reg [3:0] state;
    reg [13:0] capture_base, captured_bytes;
    reg capture_bad;
    wire [6:0] count_tree [0:126];
    wire [B-1:0] keep_violations;
    genvar lane;
    generate
        for (lane=0;lane<64;lane=lane+1) begin : g_count
            if (lane<B) begin : g_present
                assign count_tree[63+lane]={6'b0,s_keep[lane]};
            end else begin : g_absent
                assign count_tree[63+lane]=0;
            end
        end
        for (lane=0;lane<63;lane=lane+1) begin : g_count_sum
            assign count_tree[lane]=count_tree[2*lane+1]+count_tree[2*lane+2];
        end
        for (lane=0;lane<B;lane=lane+1) begin : g_keep
            if (lane==0) assign keep_violations[lane]=0;
            else assign keep_violations[lane]=s_keep[lane] && !s_keep[lane-1];
        end
    endgenerate
    wire bad_keep=(s_last ? ((|keep_violations) || !(|s_keep)) : !(&s_keep));
    wire [14:0] capture_end={1'b0,capture_base}+{8'b0,count_tree[0]};
    wire [14:0] next_capture_base={1'b0,capture_base}+B;
    wire capture_fire=s_valid && s_ready;

    wire parser_req, parser_start_ready, parser_valid, parser_trusted;
    wire [13:0] parser_mem_addr, parser_payload_start, parser_payload_bytes;
    wire [7:0] parser_opcode;
    wire [3:0] parser_status;
    wire [23:0] parser_qpn, parser_psn;
    wire [63:0] parser_address;
    wire [31:0] parser_rkey, parser_message_bytes;
    reg [SHIFT-1:0] parser_bank;
    wire [7:0] bank_q [0:B-1];

    reg replay_valid, replay_last, replay_issued_last, collective_rejected;
    reg [13:0] replay_pointer, replay_remaining;
    reg [SHIFT-1:0] replay_rotation;
    reg [B-1:0] replay_keep;
    wire [DATA_WIDTH-1:0] replay_data;
    wire dmp_in_ready, coll_in_ready;
    wire replay_consumer_ready=(state==WORK_COLL) ? coll_in_ready : dmp_in_ready;
    wire replay_read=((state==WORK_DMP) ||
                      (state==WORK_COLL && !collective_rejected)) &&
                     !replay_issued_last && (!replay_valid || replay_consumer_ready);
    generate for (lane=0;lane<B;lane=lane+1) begin : g_packet_banks
        (* ramstyle = "M20K", nomem2reg *) reg [7:0] bytes [0:ROWS-1];
        reg [7:0] read_q;
        wire [14:0] bank_capture_addr={1'b0,capture_base}+lane;
        wire [14:0] replay_row=({1'b0,replay_pointer}>>SHIFT)+
                                    (lane<replay_pointer[SHIFT-1:0] ? 15'd1 : 15'd0);
        always @(posedge clk) begin
            if (capture_fire && bank_capture_addr<MAX_PACKET_BYTES && s_keep[lane])
                bytes[capture_base>>SHIFT]<=s_data[lane*8 +:8];
            if (parser_req && (parser_mem_addr>>SHIFT)<ROWS)
                read_q<=bytes[parser_mem_addr>>SHIFT];
            else if (replay_read) begin
                if (replay_row<ROWS) read_q<=bytes[replay_row];
                else read_q<=0;
            end
        end
        assign bank_q[lane]=read_q;
        wire [SHIFT-1:0] source_bank=replay_rotation+lane;
        assign replay_data[lane*8 +:8]=
            replay_keep[lane] ? bank_q[source_bank] : 8'b0;
    end endgenerate

    furnace_roce_parser parser (
        .clk(clk), .rst_n(rst_n), .start_valid(state==PARSE_START),
        .start_ready(parser_start_ready), .frame_bytes(captured_bytes),
        .frame_bad(capture_bad), .mem_req(parser_req), .mem_addr(parser_mem_addr),
        .mem_data(bank_q[parser_bank]), .result_valid(parser_valid),
        .result_ready(state==PARSE_WAIT), .status(parser_status), .trusted(parser_trusted),
        .opcode(parser_opcode), .qpn(parser_qpn), .psn(parser_psn),
        .address(parser_address), .rkey(parser_rkey), .message_bytes(parser_message_bytes),
        .payload_start(parser_payload_start), .payload_bytes(parser_payload_bytes)
    );
    wire [7:0] qp_enabled;
    wire [23:0] qp_ranks;
    wire [511:0] qp_bases, qp_lengths;
    wire collective_enabled, collective_busy;
    wire [63:0] collective_address;
    wire configuration_boundary=enable && state==CAPTURE && capture_base==0 &&
                                !collective_busy && !qp_cfg_rsp_valid && !coll_cfg_rsp_valid;
    wire tracker_cfg_ready, collective_cfg_ready;
    assign qp_cfg_ready=tracker_cfg_ready;
    assign coll_cfg_ready=collective_cfg_ready && !qp_cfg_valid;
    wire cfg_priority=(qp_cfg_valid && qp_cfg_ready) || (coll_cfg_valid && coll_cfg_ready);
    assign s_ready=rst_n && enable && state==CAPTURE &&
                   (capture_base!=0 || (!cfg_priority &&
                    !qp_cfg_rsp_valid && !coll_cfg_rsp_valid && !collective_busy));
    assign idle=rst_n && state==CAPTURE && capture_base==0 &&
                !collective_busy && !qp_cfg_rsp_valid && !coll_cfg_rsp_valid;

    wire tracker_request_ready, tracker_valid;
    wire [3:0] tracker_status;
    wire [2:0] tracker_index, tracker_rank;
    wire [23:0] tracker_expected, tracker_remote, tracker_msn;
    wire [63:0] tracker_address;
    wire tracker_complete, tracker_duplicate, tracker_found;
    wire [7:0] tracker_syndrome;
    wire dmp_done, collective_done;
    wire [3:0] collective_status;
    wire committed=(state==WORK_DMP && dmp_done) ||
                   (state==WORK_COLL && collective_done && collective_status==1);
    wire canceled=state==WORK_COLL && collective_done && collective_status!=1;
    furnace_psn_tracker #(.QPS(QPS)) psn_tracker (
        .clk(clk), .rst_n(rst_n),
        .idle_allow(configuration_boundary && !collective_enabled),
        .cfg_valid(qp_cfg_valid && configuration_boundary),
        .cfg_ready(tracker_cfg_ready), .cfg_enable(qp_cfg_enable), .cfg_index(qp_cfg_index),
        .cfg_local_qpn(qp_cfg_local_qpn), .cfg_remote_qpn(qp_cfg_remote_qpn),
        .cfg_expected_psn(qp_cfg_expected_psn), .cfg_rkey(qp_cfg_rkey),
        .cfg_base(qp_cfg_base), .cfg_length(qp_cfg_length), .cfg_rank(qp_cfg_rank),
        .cfg_rsp_valid(qp_cfg_rsp_valid), .cfg_rsp_ready(qp_cfg_rsp_ready),
        .cfg_rsp_status(qp_cfg_rsp_status), .enabled(qp_enabled), .ranks(qp_ranks),
        .bases(qp_bases), .lengths(qp_lengths),
        .request_valid(state==TRACK_START), .request_ready(tracker_request_ready),
        .request_opcode(parser_opcode), .request_qpn(parser_qpn), .request_psn(parser_psn),
        .request_addr(parser_address), .request_rkey(parser_rkey),
        .request_message_bytes(parser_message_bytes), .request_payload_bytes(parser_payload_bytes),
        .result_valid(tracker_valid), .result_ready(state==TRACK_WAIT),
        .result_status(tracker_status), .result_index(tracker_index), .result_rank(tracker_rank),
        .result_expected(tracker_expected), .result_remote_qpn(tracker_remote),
        .result_msn(tracker_msn), .result_address(tracker_address),
        .result_complete(tracker_complete), .result_duplicate(tracker_duplicate),
        .result_found(tracker_found), .result_syndrome(tracker_syndrome),
        .commit(committed), .cancel(canceled)
    );

    wire dmp_cmd_ready, collective_cmd_ready, collective_cmd_error;
    wire dmp_wr_valid, dmp_wr_last, coll_wr_valid, coll_wr_last;
    wire [63:0] dmp_wr_addr, coll_wr_addr;
    wire [DATA_WIDTH-1:0] dmp_wr_data, coll_wr_data;
    wire [B-1:0] dmp_wr_keep, coll_wr_keep;
    reg [63:0] placement_address;
    furnace_dmp_engine #(.DATA_WIDTH(DATA_WIDTH)) dmp_engine (
        .clk(clk), .rst_n(rst_n), .cmd_valid(state==DMP_CMD), .cmd_ready(dmp_cmd_ready),
        .cmd_addr(placement_address), .cmd_bytes(parser_payload_bytes),
        .in_valid(state==WORK_DMP && replay_valid), .in_ready(dmp_in_ready),
        .in_data(replay_data), .wr_valid(dmp_wr_valid),
        .wr_ready(wr_ready && state==WORK_DMP), .wr_addr(dmp_wr_addr),
        .wr_data(dmp_wr_data), .wr_keep(dmp_wr_keep), .wr_last(dmp_wr_last),
        .done_valid(dmp_done), .done_ready(state==WORK_DMP)
    );
    furnace_collective_engine #(.DATA_WIDTH(DATA_WIDTH), .MAX_PACKET_BYTES(MAX_PACKET_BYTES))
    collective_engine (
        .clk(clk), .rst_n(rst_n), .idle_allow(configuration_boundary && !qp_cfg_valid),
        .cfg_valid(coll_cfg_valid && configuration_boundary && !qp_cfg_valid),
        .cfg_ready(collective_cfg_ready), .cfg_enable(coll_cfg_enable),
        .cfg_job(coll_cfg_job), .cfg_format(coll_cfg_format), .cfg_op(coll_cfg_op),
        .cfg_participants(coll_cfg_participants), .cfg_bytes(coll_cfg_bytes),
        .cfg_addr(coll_cfg_addr), .cfg_rsp_valid(coll_cfg_rsp_valid),
        .cfg_rsp_ready(coll_cfg_rsp_ready), .cfg_rsp_status(coll_cfg_rsp_status),
        .qp_enabled(qp_enabled), .qp_ranks(qp_ranks), .qp_bases(qp_bases),
        .qp_lengths(qp_lengths), .job_enabled(collective_enabled),
        .busy(collective_busy), .job_addr(collective_address),
        .cmd_valid(state==COLL_CMD), .cmd_ready(collective_cmd_ready),
        .cmd_opcode(parser_opcode), .cmd_rank(tracker_rank),
        .cmd_bytes(parser_payload_bytes), .cmd_error(collective_cmd_error),
        .in_valid(state==WORK_COLL && replay_valid && !collective_rejected),
        .in_ready(coll_in_ready), .in_data(replay_data),
        .in_keep(replay_keep), .in_last(replay_last),
        .wr_valid(coll_wr_valid), .wr_ready(wr_ready && state==WORK_COLL),
        .wr_addr(coll_wr_addr), .wr_data(coll_wr_data), .wr_keep(coll_wr_keep),
        .wr_last(coll_wr_last), .done_valid(collective_done),
        .done_ready(state==WORK_COLL), .done_status(collective_status),
        .coll_done_valid(coll_done_valid), .coll_done_ready(coll_done_ready),
        .coll_done_job(coll_done_job), .coll_done_bytes(coll_done_bytes)
    );
    assign wr_valid=rst_n && ((state==WORK_COLL) ? coll_wr_valid : dmp_wr_valid);
    assign wr_addr=!rst_n ? 64'b0 : (state==WORK_COLL) ? coll_wr_addr : dmp_wr_addr;
    assign wr_data=!rst_n ? {DATA_WIDTH{1'b0}} :
                   (state==WORK_COLL) ? coll_wr_data : dmp_wr_data;
    assign wr_keep=!rst_n ? {B{1'b0}} : (state==WORK_COLL) ? coll_wr_keep : dmp_wr_keep;
    assign wr_last=rst_n && ((state==WORK_COLL) ? coll_wr_last : dmp_wr_last);

    reg evt_pending, ack_pending, want_ack;
    reg [3:0] evt_status;
    reg [23:0] evt_qpn, evt_psn, evt_expected;
    reg [31:0] evt_bytes;
    reg [63:0] evt_addr;
    reg [23:0] response_remote, response_psn, response_msn;
    reg [7:0] response_syndrome;
    reg [23:0] committed_msn;
    assign rdma_evt_valid=rst_n && evt_pending;
    assign rdma_evt_status=rst_n ? evt_status : 4'b0;
    assign rdma_evt_qpn=rst_n ? evt_qpn : 24'b0;
    assign rdma_evt_psn=rst_n ? evt_psn : 24'b0;
    assign rdma_evt_expected_psn=rst_n ? evt_expected : 24'b0;
    assign rdma_evt_bytes=rst_n ? evt_bytes : 32'b0;
    assign rdma_evt_addr=rst_n ? evt_addr : 64'b0;
    assign ack_valid=rst_n && ack_pending;
    assign ack_local_qpn=rst_n ? evt_qpn : 24'b0;
    assign ack_remote_qpn=rst_n ? response_remote : 24'b0;
    assign ack_psn=rst_n ? response_psn : 24'b0;
    assign ack_data=rst_n ?
        {response_msn[7:0],response_msn[15:8],response_msn[23:16],response_syndrome,
         response_psn[7:0],response_psn[15:8],response_psn[23:16],8'h00,
         response_remote[7:0],response_remote[15:8],response_remote[23:16],8'h00,
         16'hffff,8'h00,8'h11} : 128'b0;

    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=CAPTURE; capture_base<=0; captured_bytes<=0; capture_bad<=0;
            parser_bank<=0; replay_valid<=0; replay_last<=0; replay_issued_last<=0;
            collective_rejected<=0; replay_pointer<=0; replay_remaining<=0;
            replay_rotation<=0; replay_keep<=0; placement_address<=0;
            evt_pending<=0; ack_pending<=0; want_ack<=0;
            evt_status<=0; evt_qpn<=0; evt_psn<=0; evt_expected<=0;
            evt_bytes<=0; evt_addr<=0; response_remote<=0; response_psn<=0;
            response_msn<=0; response_syndrome<=0; committed_msn<=0;
        end else begin
            if (parser_req) parser_bank<=parser_mem_addr[SHIFT-1:0];
            if (evt_pending && rdma_evt_ready) evt_pending<=0;
            if (ack_pending && ack_ready) ack_pending<=0;
            if (replay_valid && replay_consumer_ready) replay_valid<=0;
            if (replay_read) begin
                replay_valid<=1; replay_last<=replay_remaining<=B;
                replay_rotation<=replay_pointer[SHIFT-1:0];
                replay_pointer<=replay_pointer+B;
                for (k=0;k<B;k=k+1) replay_keep[k]<=k<replay_remaining;
                if (replay_remaining<=B) begin
                    replay_remaining<=0; replay_issued_last<=1;
                end else replay_remaining<=replay_remaining-B;
            end
            case (state)
                CAPTURE: if (capture_fire) begin
                    if (bad_keep || capture_end>MAX_PACKET_BYTES) capture_bad<=1;
                    if (next_capture_base>MAX_PACKET_BYTES)
                        capture_base<=MAX_PACKET_BYTES+1;
                    else capture_base<=next_capture_base[13:0];
                    if (s_last) begin
                        captured_bytes<=(capture_end>MAX_PACKET_BYTES) ?
                                         MAX_PACKET_BYTES : capture_end[13:0];
                        state<=PARSE_START;
                    end
                end
                PARSE_START: if (parser_start_ready) state<=PARSE_WAIT;
                PARSE_WAIT: if (parser_valid) begin
                    evt_status<=parser_status; evt_qpn<=parser_qpn; evt_psn<=parser_psn;
                    evt_expected<=0; evt_bytes<={18'b0,parser_payload_bytes};
                    evt_addr<=parser_address; want_ack<=0;
                    response_remote<=0; response_psn<=0; response_msn<=0; response_syndrome<=0;
                    if (parser_status==0 && parser_trusted) state<=TRACK_START;
                    else state<=EMIT;
                end
                TRACK_START: if (tracker_request_ready) state<=TRACK_WAIT;
                TRACK_WAIT: if (tracker_valid) begin
                    evt_status<=tracker_status; evt_expected<=tracker_expected;
                    evt_addr<=tracker_address; placement_address<=tracker_address;
                    response_remote<=tracker_remote;
                    committed_msn<=tracker_msn+{23'b0,tracker_complete};
                    response_msn<=tracker_msn;
                    response_psn<=tracker_duplicate ? evt_psn :
                                  (tracker_status==6 ? tracker_expected : evt_psn);
                    response_syndrome<=tracker_duplicate ? 8'h00 : tracker_syndrome;
                    want_ack<=tracker_found;
                    if (tracker_status==0) begin
                        replay_pointer<=parser_payload_start;
                        replay_remaining<=parser_payload_bytes;
                        replay_issued_last<=parser_payload_bytes==0;
                        replay_valid<=0; collective_rejected<=0;
                        if (collective_enabled && tracker_address==collective_address)
                            state<=COLL_CMD;
                        else state<=DMP_CMD;
                    end else state<=EMIT;
                end
                DMP_CMD: if (dmp_cmd_ready) state<=WORK_DMP;
                COLL_CMD: if (collective_cmd_ready) begin
                    collective_rejected<=collective_cmd_error;
                    state<=WORK_COLL;
                end
                WORK_DMP: if (dmp_done) begin
                    evt_status<=0; evt_expected<=evt_expected+24'd1;
                    response_syndrome<=0; response_psn<=evt_psn;
                    response_msn<=committed_msn; state<=EMIT;
                end
                WORK_COLL: if (collective_done) begin
                    evt_status<=collective_status;
                    if (collective_status==1) begin
                        evt_expected<=evt_expected+24'd1; response_syndrome<=0;
                        response_msn<=committed_msn;
                    end else response_syndrome<=8'h61;
                    response_psn<=evt_psn; state<=EMIT;
                end
                EMIT: begin evt_pending<=1; ack_pending<=want_ack; state<=RETIRE; end
                RETIRE: if (!evt_pending && !ack_pending && !collective_busy) begin
                    capture_base<=0; captured_bytes<=0; capture_bad<=0;
                    replay_valid<=0; state<=CAPTURE;
                end
                default: state<=CAPTURE;
            endcase
        end
    end
endmodule
`default_nettype wire
