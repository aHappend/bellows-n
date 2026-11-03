`default_nettype none
module bellows_n5_engine #(
    parameter integer DATA_WIDTH=512, MAX_PACKET_BYTES=9216, MAX_SG=16,
    parameter integer QPS=8, EXPERTS=8, MAX_K=4,
    parameter integer TOKENS=4, MAX_TOKEN_ELEMS=256
) (
    input wire clk, rst_n,
    input wire x5_rx_tvalid,
    output wire x5_rx_tready,
    input wire [DATA_WIDTH-1:0] x5_rx_tdata,
    input wire [(DATA_WIDTH>>3)-1:0] x5_rx_tkeep,
    input wire x5_rx_tlast,
    output wire x5_tx_tvalid,
    input wire x5_tx_tready,
    output wire [DATA_WIDTH-1:0] x5_tx_tdata,
    output wire [(DATA_WIDTH>>3)-1:0] x5_tx_tkeep,
    output wire x5_tx_tlast,
    input wire x5_qp_cfg_valid,
    output wire x5_qp_cfg_ready,
    input wire [2:0] x5_qp_cfg_index,
    input wire x5_qp_cfg_enable,
    input wire [23:0] x5_qp_cfg_local_qpn, x5_qp_cfg_remote_qpn,
    input wire [23:0] x5_qp_cfg_rx_psn, x5_qp_cfg_tx_psn,
    input wire [31:0] x5_qp_cfg_rkey,
    input wire [63:0] x5_qp_cfg_base, x5_qp_cfg_length,
    input wire [47:0] x5_qp_cfg_local_mac, x5_qp_cfg_remote_mac,
    input wire [31:0] x5_qp_cfg_local_ip, x5_qp_cfg_remote_ip,
    output wire x5_qp_cfg_rsp_valid,
    input wire x5_qp_cfg_rsp_ready,
    output wire [2:0] x5_qp_cfg_rsp_status,
    input wire x5_expert_cfg_valid,
    output wire x5_expert_cfg_ready,
    input wire [15:0] x5_expert_cfg_id,
    input wire x5_expert_cfg_enable,
    input wire [2:0] x5_expert_cfg_qp,
    output wire x5_expert_cfg_rsp_valid,
    input wire x5_expert_cfg_rsp_ready,
    output wire [1:0] x5_expert_cfg_rsp_status,
    input wire x5_write_cmd_valid,
    output wire x5_write_cmd_ready,
    input wire [2:0] x5_write_cmd_qp,
    input wire [63:0] x5_write_cmd_addr,
    input wire [31:0] x5_write_cmd_rkey,
    input wire [15:0] x5_write_cmd_bytes,
    input wire [31:0] x5_write_cmd_cookie,
    input wire x5_write_tvalid,
    output wire x5_write_tready,
    input wire [DATA_WIDTH-1:0] x5_write_tdata,
    input wire [(DATA_WIDTH>>3)-1:0] x5_write_tkeep,
    input wire x5_write_tlast,
    output wire x5_write_cpl_valid,
    input wire x5_write_cpl_ready,
    output wire [31:0] x5_write_cpl_cookie,
    output wire [3:0] x5_write_cpl_status,
    output wire x5_mem_valid,
    input wire x5_mem_ready,
    output wire [63:0] x5_mem_addr,
    output wire [DATA_WIDTH-1:0] x5_mem_data,
    output wire [(DATA_WIDTH>>3)-1:0] x5_mem_keep,
    output wire x5_mem_last,
    input wire x5_moe_cmd_valid,
    output wire x5_moe_cmd_ready,
    input wire [31:0] x5_moe_cmd_token_id,
    input wire [8:0] x5_moe_cmd_elems,
    input wire [2:0] x5_moe_cmd_k,
    input wire x5_moe_cmd_format,
    input wire [16*EXPERTS-1:0] x5_moe_cmd_scores, x5_moe_cmd_weights,
    input wire x5_token_tvalid,
    output wire x5_token_tready,
    input wire [DATA_WIDTH-1:0] x5_token_tdata,
    input wire [(DATA_WIDTH>>3)-1:0] x5_token_tkeep,
    input wire x5_token_tlast,
    output wire x5_combine_tvalid,
    input wire x5_combine_tready,
    output wire [DATA_WIDTH-1:0] x5_combine_tdata,
    output wire [(DATA_WIDTH>>3)-1:0] x5_combine_tkeep,
    output wire x5_combine_tlast,
    output wire [31:0] x5_combine_token_id,
    output wire x5_moe_cpl_valid,
    input wire x5_moe_cpl_ready,
    output wire [31:0] x5_moe_cpl_token_id,
    output wire [3:0] x5_moe_cpl_status,
    output wire x5_expert_req_valid,
    input wire x5_expert_req_ready,
    output wire [2:0] x5_expert_req_qp,
    output wire [511:0] x5_expert_req_meta,
    output wire x5_expert_req_tvalid,
    input wire x5_expert_req_tready,
    output wire [DATA_WIDTH-1:0] x5_expert_req_tdata,
    output wire [(DATA_WIDTH>>3)-1:0] x5_expert_req_tkeep,
    output wire x5_expert_req_tlast,
    input wire x5_expert_rsp_valid,
    output wire x5_expert_rsp_ready,
    input wire [2:0] x5_expert_rsp_qp,
    input wire [511:0] x5_expert_rsp_meta,
    input wire x5_expert_rsp_tvalid,
    output wire x5_expert_rsp_tready,
    input wire [DATA_WIDTH-1:0] x5_expert_rsp_tdata,
    input wire [(DATA_WIDTH>>3)-1:0] x5_expert_rsp_tkeep,
    input wire x5_expert_rsp_tlast,
    output wire x5_peer_sack_valid,
    input wire x5_peer_sack_ready,
    output wire [2:0] x5_peer_sack_qp,
    output wire [23:0] x5_peer_sack_base,
    output wire [255:0] x5_peer_sack_bitmap,
    output wire [1:0] x5_peer_sack_status,
    output wire x5_evt_valid,
    input wire x5_evt_ready,
    output wire [3:0] x5_evt_status,
    output wire [7:0] x5_evt_kind,
    output wire [2:0] x5_evt_qp,
    output wire [31:0] x5_evt_token_id,
    output wire [23:0] x5_evt_psn,
    output wire x5_idle
);
    localparam integer B=DATA_WIDTH>>3;
    wire [7:0] enabled, route_qps;
    wire [191:0] local_qpns, remote_qpns, rx_psns, tx_psns;
    wire [255:0] rkeys, local_ips, remote_ips;
    wire [511:0] bases, lengths;
    wire [383:0] local_macs, remote_macs;
    wire rx_idle, tx_idle, moe_idle, sack_idle, qp_commit;
    wire tracker_cfg_ready, tracker_cfg_rsp_valid;
    wire [1:0] tracker_cfg_rsp_status;
    wire packet_done, packet_is_sack;
    wire [2:0] packet_qp;
    wire global_idle;
    wire config_boundary=global_idle && (x5_qp_cfg_valid || x5_expert_cfg_valid);
    wire qp_cfg_ready;
    assign x5_qp_cfg_ready=qp_cfg_ready && tracker_cfg_ready;
    bellows_n5_qp_table #(.QPS(QPS)) qp_table (
        .clk(clk),.rst_n(rst_n),.idle_allow(global_idle && tracker_cfg_ready),
        .cfg_valid(x5_qp_cfg_valid),.cfg_ready(qp_cfg_ready),
        .cfg_index(x5_qp_cfg_index),.cfg_enable(x5_qp_cfg_enable),
        .cfg_local_qpn(x5_qp_cfg_local_qpn),.cfg_remote_qpn(x5_qp_cfg_remote_qpn),
        .cfg_rx_psn(x5_qp_cfg_rx_psn),.cfg_tx_psn(x5_qp_cfg_tx_psn),
        .cfg_rkey(x5_qp_cfg_rkey),.cfg_base(x5_qp_cfg_base),.cfg_length(x5_qp_cfg_length),
        .cfg_local_mac(x5_qp_cfg_local_mac),.cfg_remote_mac(x5_qp_cfg_remote_mac),
        .cfg_local_ip(x5_qp_cfg_local_ip),.cfg_remote_ip(x5_qp_cfg_remote_ip),
        .route_qps(route_qps),.cfg_rsp_valid(x5_qp_cfg_rsp_valid),
        .cfg_rsp_ready(x5_qp_cfg_rsp_ready),.cfg_rsp_status(x5_qp_cfg_rsp_status),
        .cfg_commit(qp_commit),.tx_advance(packet_done && !packet_is_sack),
        .tx_qp(packet_qp),.enabled(enabled),.local_qpns(local_qpns),
        .remote_qpns(remote_qpns),.rx_psns(rx_psns),.tx_psns(tx_psns),
        .rkeys(rkeys),.local_ips(local_ips),.remote_ips(remote_ips),
        .bases(bases),.lengths(lengths),.local_macs(local_macs),.remote_macs(remote_macs)
    );
    wire rx_cmd_valid, rx_cmd_ready, rx_payload_valid, rx_payload_ready, rx_payload_last;
    wire [2:0] rx_cmd_qp;
    wire [511:0] rx_cmd_meta;
    wire [DATA_WIDTH-1:0] rx_payload_data;
    wire [B-1:0] rx_payload_keep;
    wire rx_error_valid, rx_error_ready;
    wire [3:0] rx_error_status;
    wire [7:0] rx_error_kind;
    wire [2:0] rx_error_qp;
    wire [31:0] rx_error_token;
    wire [23:0] rx_error_psn;
    wire rx_ready;
    assign x5_rx_tready=rx_ready && !config_boundary;
    bellows_n5_packet_rx #(.DATA_WIDTH(DATA_WIDTH),.QPS(QPS),.EXPERTS(EXPERTS),
        .MAX_K(MAX_K),.MAX_TOKEN_ELEMS(MAX_TOKEN_ELEMS)) packet_rx (
        .clk(clk),.rst_n(rst_n),.rx_tvalid(x5_rx_tvalid && !config_boundary),
        .rx_tready(rx_ready),.rx_tdata(x5_rx_tdata),.rx_tkeep(x5_rx_tkeep),
        .rx_tlast(x5_rx_tlast),.enabled(enabled),.local_qpns(local_qpns),
        .remote_qpns(remote_qpns),.rkeys(rkeys),.local_ips(local_ips),
        .remote_ips(remote_ips),.bases(bases),.lengths(lengths),
        .local_macs(local_macs),.remote_macs(remote_macs),
        .cmd_valid(rx_cmd_valid),.cmd_ready(rx_cmd_ready),.cmd_qp(rx_cmd_qp),
        .cmd_meta(rx_cmd_meta),.payload_tvalid(rx_payload_valid),
        .payload_tready(rx_payload_ready),.payload_tdata(rx_payload_data),
        .payload_tkeep(rx_payload_keep),.payload_tlast(rx_payload_last),
        .error_valid(rx_error_valid),.error_ready(rx_error_ready),
        .error_status(rx_error_status),.error_kind(rx_error_kind),
        .error_qp(rx_error_qp),.error_token_id(rx_error_token),
        .error_psn(rx_error_psn),.idle(rx_idle)
    );
    localparam R_IDLE=0, R_TRACK=1, R_DECIDE=2, R_DRAIN=3, R_WRITE=4,
               R_MOE_COMMAND=5, R_MOE_PAYLOAD=6, R_MOE_DONE=7,
               R_COMMIT=8, R_SNAPSHOT=9, R_EVENT=10, R_PEER=11;
    reg [3:0] rstate;
    reg [511:0] received_meta;
    reg [2:0] received_qp;
    reg [23:0] received_psn;
    reg [31:0] received_token;
    reg [7:0] received_kind;
    reg [3:0] received_status;
    reg received_commit;
    reg [63:0] placement_addr;
    reg [255:0] peer_bitmap;
    reg [5:0] peer_offset;
    wire tracker_req_ready, tracker_decision_valid, tracker_commit_ready, tracker_sack_valid;
    wire [1:0] tracker_decision_status, tracker_sack_status;
    wire [2:0] tracker_decision_qp, tracker_sack_qp;
    wire [23:0] tracker_decision_psn, tracker_sack_base;
    wire [255:0] tracker_sack_bitmap;
    wire tracker_sack_ready;
    bellows_n5_reorder #(.QPS(QPS)) reorder_tracker (
        .clk(clk),.rst_n(rst_n),.cfg_valid(qp_commit),.cfg_ready(tracker_cfg_ready),
        .cfg_index(x5_qp_cfg_index),.cfg_enable(x5_qp_cfg_enable),.cfg_base(x5_qp_cfg_rx_psn),
        .cfg_rsp_valid(tracker_cfg_rsp_valid),.cfg_rsp_ready(1'b1),
        .cfg_rsp_status(tracker_cfg_rsp_status),
        .req_valid(rst_n && rstate==R_TRACK),.req_ready(tracker_req_ready),
        .req_qp(received_qp),.req_psn(received_psn),
        .decision_valid(tracker_decision_valid),.decision_ready(rstate==R_DECIDE),
        .decision_qp(tracker_decision_qp),.decision_psn(tracker_decision_psn),
        .decision_status(tracker_decision_status),
        .commit_valid(rst_n && rstate==R_COMMIT),.commit_ready(tracker_commit_ready),
        .commit_ok(received_commit),.sack_valid(tracker_sack_valid),
        .sack_ready(tracker_sack_ready),.sack_qp(tracker_sack_qp),
        .sack_base(tracker_sack_base),.sack_bitmap(tracker_sack_bitmap),
        .sack_status(tracker_sack_status)
    );
    wire sack_cmd_valid, sack_cmd_ready, sack_payload_valid, sack_payload_ready, sack_payload_last;
    wire [2:0] sack_cmd_qp;
    wire [511:0] sack_cmd_meta;
    wire [DATA_WIDTH-1:0] sack_payload_data;
    wire [B-1:0] sack_payload_keep;
    wire snapshot_ready;
    assign tracker_sack_ready=snapshot_ready && rstate==R_SNAPSHOT;
    bellows_n5_sack #(.DATA_WIDTH(DATA_WIDTH)) sack_generator (
        .clk(clk),.rst_n(rst_n),
        .snapshot_valid(tracker_sack_valid && rstate==R_SNAPSHOT),
        .snapshot_ready(snapshot_ready),.snapshot_qp(tracker_sack_qp),
        .snapshot_psn(received_psn),.snapshot_base(tracker_sack_base),
        .snapshot_bitmap(tracker_sack_bitmap),.snapshot_status(tracker_sack_status),
        .local_qpn(local_qpns[24*received_qp +:24]),
        .remote_qpn(remote_qpns[24*received_qp +:24]),
        .cmd_valid(sack_cmd_valid),.cmd_ready(sack_cmd_ready),.cmd_qp(sack_cmd_qp),
        .cmd_meta(sack_cmd_meta),.payload_tvalid(sack_payload_valid),
        .payload_tready(sack_payload_ready),.payload_tdata(sack_payload_data),
        .payload_tkeep(sack_payload_keep),.payload_tlast(sack_payload_last),.idle(sack_idle)
    );
    wire moe_rx_cmd_ready, moe_rx_payload_ready, moe_rx_done_valid, moe_rx_done_ok;
    wire d_cmd_valid, d_cmd_ready, d_payload_valid, d_payload_ready, d_payload_last;
    wire t_cmd_valid, t_cmd_ready, t_payload_valid, t_payload_ready, t_payload_last;
    wire [2:0] d_cmd_qp, t_cmd_qp;
    wire [511:0] d_cmd_meta, t_cmd_meta;
    wire [DATA_WIDTH-1:0] d_payload_data, t_payload_data;
    wire [B-1:0] d_payload_keep, t_payload_keep;
    wire moe_evt_valid, moe_evt_ready;
    wire [3:0] moe_evt_status;
    wire [2:0] moe_evt_qp;
    wire [31:0] moe_evt_token;
    wire [23:0] moe_evt_psn;
    wire moe_cmd_ready, expert_rsp_ready;
    wire expert_cfg_ready;
    reg [1:0] tx_source, tx_cursor;
    reg [1:0] tx_state;
    localparam T_IDLE=0, T_COMMAND=1, T_PAYLOAD=2, T_WAIT=3;
    assign x5_moe_cmd_ready=moe_cmd_ready && !config_boundary;
    assign x5_expert_rsp_ready=expert_rsp_ready && !config_boundary;
    assign x5_expert_cfg_ready=expert_cfg_ready && !x5_qp_cfg_valid;
    bellows_n5_moe_router #(.DATA_WIDTH(DATA_WIDTH),.QPS(QPS),.EXPERTS(EXPERTS),
        .MAX_K(MAX_K),.TOKENS(TOKENS),.MAX_TOKEN_ELEMS(MAX_TOKEN_ELEMS)) moe_router (
        .clk(clk),.rst_n(rst_n),
        .idle_allow(global_idle && !x5_qp_cfg_valid && x5_expert_cfg_valid),
        .qp_enabled(enabled),.local_qpns(local_qpns),.remote_qpns(remote_qpns),
        .x5_expert_cfg_valid(x5_expert_cfg_valid && !x5_qp_cfg_valid),
        .x5_expert_cfg_ready(expert_cfg_ready),.x5_expert_cfg_id(x5_expert_cfg_id),
        .x5_expert_cfg_enable(x5_expert_cfg_enable),.x5_expert_cfg_qp(x5_expert_cfg_qp),
        .x5_expert_cfg_rsp_valid(x5_expert_cfg_rsp_valid),
        .x5_expert_cfg_rsp_ready(x5_expert_cfg_rsp_ready),
        .x5_expert_cfg_rsp_status(x5_expert_cfg_rsp_status),.route_qps(route_qps),
        .x5_moe_cmd_valid(x5_moe_cmd_valid && !config_boundary),
        .x5_moe_cmd_ready(moe_cmd_ready),.x5_moe_cmd_token_id(x5_moe_cmd_token_id),
        .x5_moe_cmd_elems(x5_moe_cmd_elems),.x5_moe_cmd_k(x5_moe_cmd_k),
        .x5_moe_cmd_format(x5_moe_cmd_format),.x5_moe_cmd_scores(x5_moe_cmd_scores),
        .x5_moe_cmd_weights(x5_moe_cmd_weights),.x5_token_tvalid(x5_token_tvalid),
        .x5_token_tready(x5_token_tready),.x5_token_tdata(x5_token_tdata),
        .x5_token_tkeep(x5_token_tkeep),.x5_token_tlast(x5_token_tlast),
        .x5_combine_tvalid(x5_combine_tvalid),.x5_combine_tready(x5_combine_tready),
        .x5_combine_tdata(x5_combine_tdata),.x5_combine_tkeep(x5_combine_tkeep),
        .x5_combine_tlast(x5_combine_tlast),.x5_combine_token_id(x5_combine_token_id),
        .x5_moe_cpl_valid(x5_moe_cpl_valid),.x5_moe_cpl_ready(x5_moe_cpl_ready),
        .x5_moe_cpl_token_id(x5_moe_cpl_token_id),.x5_moe_cpl_status(x5_moe_cpl_status),
        .x5_expert_req_valid(x5_expert_req_valid),.x5_expert_req_ready(x5_expert_req_ready),
        .x5_expert_req_qp(x5_expert_req_qp),.x5_expert_req_meta(x5_expert_req_meta),
        .x5_expert_req_tvalid(x5_expert_req_tvalid),.x5_expert_req_tready(x5_expert_req_tready),
        .x5_expert_req_tdata(x5_expert_req_tdata),.x5_expert_req_tkeep(x5_expert_req_tkeep),
        .x5_expert_req_tlast(x5_expert_req_tlast),
        .x5_expert_rsp_valid(x5_expert_rsp_valid && !config_boundary),
        .x5_expert_rsp_ready(expert_rsp_ready),.x5_expert_rsp_qp(x5_expert_rsp_qp),
        .x5_expert_rsp_meta(x5_expert_rsp_meta),.x5_expert_rsp_tvalid(x5_expert_rsp_tvalid),
        .x5_expert_rsp_tready(x5_expert_rsp_tready),.x5_expert_rsp_tdata(x5_expert_rsp_tdata),
        .x5_expert_rsp_tkeep(x5_expert_rsp_tkeep),.x5_expert_rsp_tlast(x5_expert_rsp_tlast),
        .rx_cmd_valid(rst_n && rstate==R_MOE_COMMAND),.rx_cmd_ready(moe_rx_cmd_ready),
        .rx_cmd_qp(received_qp),.rx_cmd_meta(received_meta),
        .rx_payload_tvalid(rx_payload_valid && rstate==R_MOE_PAYLOAD),
        .rx_payload_tready(moe_rx_payload_ready),.rx_payload_tdata(rx_payload_data),
        .rx_payload_tkeep(rx_payload_keep),.rx_payload_tlast(rx_payload_last),
        .rx_done_valid(moe_rx_done_valid),.rx_done_ready(rstate==R_MOE_DONE),
        .rx_done_ok(moe_rx_done_ok),
        .dispatch_cmd_valid(d_cmd_valid),.dispatch_cmd_ready(d_cmd_ready),
        .dispatch_cmd_qp(d_cmd_qp),.dispatch_cmd_meta(d_cmd_meta),
        .dispatch_payload_tvalid(d_payload_valid),.dispatch_payload_tready(d_payload_ready),
        .dispatch_payload_tdata(d_payload_data),.dispatch_payload_tkeep(d_payload_keep),
        .dispatch_payload_tlast(d_payload_last),
        .dispatch_done(packet_done && tx_source==2),
        .return_cmd_valid(t_cmd_valid),.return_cmd_ready(t_cmd_ready),
        .return_cmd_qp(t_cmd_qp),.return_cmd_meta(t_cmd_meta),
        .return_payload_tvalid(t_payload_valid),.return_payload_tready(t_payload_ready),
        .return_payload_tdata(t_payload_data),.return_payload_tkeep(t_payload_keep),
        .return_payload_tlast(t_payload_last),.return_done(packet_done && tx_source==3),
        .evt_valid(moe_evt_valid),.evt_ready(moe_evt_ready),.evt_status(moe_evt_status),
        .evt_qp(moe_evt_qp),.evt_token_id(moe_evt_token),.evt_psn(moe_evt_psn),.idle(moe_idle)
    );
    assign rx_cmd_ready=rst_n && rstate==R_IDLE && !peer_valid;
    assign rx_payload_ready=rst_n && (rstate==R_DRAIN || rstate==R_PEER ||
        (rstate==R_WRITE && x5_mem_ready) ||
        (rstate==R_MOE_PAYLOAD && moe_rx_payload_ready));
    assign x5_mem_valid=rst_n && rstate==R_WRITE && rx_payload_valid;
    assign x5_mem_addr=rst_n ? placement_addr : 64'b0;
    assign x5_mem_data=x5_mem_valid ? rx_payload_data : {DATA_WIDTH{1'b0}};
    assign x5_mem_keep=x5_mem_valid ? rx_payload_keep : {B{1'b0}};
    assign x5_mem_last=x5_mem_valid && rx_payload_last;
    reg peer_valid;
    assign x5_peer_sack_valid=rst_n && peer_valid;
    assign x5_peer_sack_qp=rst_n ? received_qp : 3'b0;
    assign x5_peer_sack_base=rst_n ?
        {received_meta[8*52 +:8],received_meta[8*53 +:8],received_meta[8*54 +:8]} : 24'b0;
    assign x5_peer_sack_bitmap=rst_n ? peer_bitmap : 256'b0;
    assign x5_peer_sack_status=rst_n ? received_meta[8*55 +:2] : 2'b0;

    reg event_pending;
    reg [3:0] event_status;
    reg [7:0] event_kind;
    reg [2:0] event_qp;
    reg [31:0] event_token;
    reg [23:0] event_psn;
    reg event_turn;
    wire event_slot=!event_pending;
    wire own_event=rstate==R_EVENT && !peer_valid;
    wire choose_rx_event=(own_event || rx_error_valid) &&
                         (!moe_evt_valid || !event_turn);
    assign rx_error_ready=event_slot && choose_rx_event && !own_event;
    assign moe_evt_ready=event_slot && !choose_rx_event;
    assign x5_evt_valid=rst_n && event_pending;
    assign x5_evt_status=rst_n ? event_status : 4'b0;
    assign x5_evt_kind=rst_n ? event_kind : 8'b0;
    assign x5_evt_qp=rst_n ? event_qp : 3'b0;
    assign x5_evt_token_id=rst_n ? event_token : 32'b0;
    assign x5_evt_psn=rst_n ? event_psn : 24'b0;

    localparam W_IDLE=0, W_INPUT=1, W_PREPARE=2, W_COMMAND=3, W_FETCH=4,
               W_CAPTURE=5, W_SEND=6, W_WAIT=7, W_COMPLETE=8;
    reg [3:0] wstate;
    reg [2:0] write_qp;
    reg [63:0] write_addr;
    reg [31:0] write_key, write_cookie;
    reg [15:0] write_bytes;
    reg [16:0] write_input_offset, write_offset, write_limit;
    reg write_bad;
    reg [3:0] write_status;
    reg [511:0] write_meta;
    reg [DATA_WIDTH-1:0] write_data;
    reg [B-1:0] write_keep;
    wire [DATA_WIDTH-1:0] write_ram_q;
    reg [6:0] write_beat_bytes;
    reg write_keep_bad, write_gap;
    integer wl;
    always @* begin
        write_beat_bytes=0; write_keep_bad=0; write_gap=0;
        for (wl=0;wl<B;wl=wl+1) begin
            if (x5_write_tkeep[wl]) begin
                write_beat_bytes=write_beat_bytes+1'b1;
                if (write_gap) write_keep_bad=1;
            end else write_gap=1;
        end
        if (write_beat_bytes==0 || (!x5_write_tlast && !(&x5_write_tkeep))) write_keep_bad=1;
    end
    wire [17:0] write_input_end={1'b0,write_input_offset}+write_beat_bytes;
    wire write_violation=write_keep_bad || write_input_end>{2'b0,write_bytes} ||
        (x5_write_tlast && write_input_end!={2'b0,write_bytes}) ||
        (!x5_write_tlast && write_input_end>={2'b0,write_bytes});
    wire [64:0] command_end={1'b0,x5_write_cmd_addr}+{49'b0,x5_write_cmd_bytes};
    assign x5_write_cmd_ready=rst_n && wstate==W_IDLE && !config_boundary;
    assign x5_write_tready=rst_n && wstate==W_INPUT;
    assign x5_write_cpl_valid=rst_n && wstate==W_COMPLETE;
    assign x5_write_cpl_cookie=rst_n ? write_cookie : 32'b0;
    assign x5_write_cpl_status=rst_n ? write_status : 4'b0;
    bellows_n5_payload_ram #(.DATA_WIDTH(DATA_WIDTH),.BYTES(65536)) write_ram (
        .clk(clk),.we(x5_write_tvalid && x5_write_tready && !write_bad && !write_violation),
        .waddr(write_input_offset[15:0]),.wdata(x5_write_tdata),.wkeep(x5_write_tkeep),
        .re(wstate==W_FETCH),.raddr(write_offset[15:0]),.rdata(write_ram_q)
    );
    wire [16:0] write_packet_bytes=write_limit-(write_offset & 17'h1ff00);
    reg [511:0] write_header;
    always @* begin
        write_header=0;
        write_header[0 +:32]=32'h21355846; write_header[8*4 +:8]=1;
        write_header[8*5 +:8]=1; write_header[8*6 +:8]=2;
        write_header[8*7 +:8]=(write_limit=={1'b0,write_bytes})?1:0;
        write_header[8*8 +:8]=remote_qpns[24*write_qp+16 +:8];
        write_header[8*9 +:8]=remote_qpns[24*write_qp+8 +:8];
        write_header[8*10 +:8]=remote_qpns[24*write_qp +:8];
        write_header[8*16 +:8]=local_qpns[24*write_qp+16 +:8];
        write_header[8*17 +:8]=local_qpns[24*write_qp+8 +:8];
        write_header[8*18 +:8]=local_qpns[24*write_qp +:8];
        write_header[8*20 +:8]=write_cookie[31:24];
        write_header[8*21 +:8]=write_cookie[23:16];
        write_header[8*22 +:8]=write_cookie[15:8];
        write_header[8*23 +:8]=write_cookie[7:0];
        write_header[8*28 +:8]=write_bytes[15:8];
        write_header[8*29 +:8]=write_bytes[7:0];
        write_header[8*30 +:8]=write_offset[15:8];
        write_header[8*31 +:8]=write_offset[7:0];
        write_header[8*32 +:8]=write_packet_bytes[15:8];
        write_header[8*33 +:8]=write_packet_bytes[7:0];
        write_header[8*36 +:8]=write_addr[63:56];
        write_header[8*37 +:8]=write_addr[55:48];
        write_header[8*38 +:8]=write_addr[47:40];
        write_header[8*39 +:8]=write_addr[39:32];
        write_header[8*40 +:8]=write_addr[31:24];
        write_header[8*41 +:8]=write_addr[23:16];
        write_header[8*42 +:8]=write_addr[15:8];
        write_header[8*43 +:8]=write_addr[7:0];
        write_header[8*44 +:8]=write_key[31:24];
        write_header[8*45 +:8]=write_key[23:16];
        write_header[8*46 +:8]=write_key[15:8];
        write_header[8*47 +:8]=write_key[7:0];
    end

    wire [3:0] source_valid={t_cmd_valid,d_cmd_valid,wstate==W_COMMAND,sack_cmd_valid};
    reg source_found;
    reg [1:0] source_choice;
    integer ts, ti;
    always @* begin
        source_found=0; source_choice=0; ti=0;
        for (ts=0;ts<4;ts=ts+1) begin
            ti=({30'b0,tx_cursor}+ts)&3;
            if (!source_found && source_valid[ti]) begin source_found=1; source_choice=ti; end
        end
    end
    reg [511:0] tx_meta;
    reg [2:0] tx_qp_hold;
    wire tx_cmd_ready, tx_payload_ready;
    reg tx_payload_valid, tx_payload_last;
    reg [DATA_WIDTH-1:0] tx_payload_data;
    reg [B-1:0] tx_payload_keep;
    reg [511:0] selected_meta;
    reg [2:0] selected_qp;
    always @* begin
        case (source_choice)
            0: begin selected_meta=sack_cmd_meta; selected_qp=sack_cmd_qp; end
            1: begin selected_meta=write_meta; selected_qp=write_qp; end
            2: begin selected_meta=d_cmd_meta; selected_qp=d_cmd_qp; end
            default: begin selected_meta=t_cmd_meta; selected_qp=t_cmd_qp; end
        endcase
        if (source_choice!=0) begin
            selected_meta[8*12 +:8]=tx_psns[24*selected_qp+16 +:8];
            selected_meta[8*13 +:8]=tx_psns[24*selected_qp+8 +:8];
            selected_meta[8*14 +:8]=tx_psns[24*selected_qp +:8];
            selected_meta[8*15 +:8]={6'b0,tx_psns[24*selected_qp +:2]};
        end
        tx_payload_valid=0; tx_payload_last=0; tx_payload_data=0; tx_payload_keep=0;
        if (rst_n && tx_state==T_PAYLOAD) case (tx_source)
            0: begin
                tx_payload_valid=sack_payload_valid; tx_payload_last=sack_payload_last;
                tx_payload_data=sack_payload_data; tx_payload_keep=sack_payload_keep;
            end
            1: begin
                tx_payload_valid=wstate==W_SEND; tx_payload_last=write_offset+B>=write_limit;
                tx_payload_data=write_data; tx_payload_keep=write_keep;
            end
            2: begin
                tx_payload_valid=d_payload_valid; tx_payload_last=d_payload_last;
                tx_payload_data=d_payload_data; tx_payload_keep=d_payload_keep;
            end
            3: begin
                tx_payload_valid=t_payload_valid; tx_payload_last=t_payload_last;
                tx_payload_data=t_payload_data; tx_payload_keep=t_payload_keep;
            end
        endcase
    end
    wire select_fire=rst_n && tx_state==T_IDLE && source_found;
    assign sack_cmd_ready=select_fire && source_choice==0;
    wire write_cmd_ready=select_fire && source_choice==1;
    assign d_cmd_ready=select_fire && source_choice==2;
    assign t_cmd_ready=select_fire && source_choice==3;
    assign sack_payload_ready=rst_n && tx_state==T_PAYLOAD && tx_source==0 && tx_payload_ready;
    wire write_payload_ready=rst_n && tx_state==T_PAYLOAD && tx_source==1 && tx_payload_ready;
    assign d_payload_ready=rst_n && tx_state==T_PAYLOAD && tx_source==2 && tx_payload_ready;
    assign t_payload_ready=rst_n && tx_state==T_PAYLOAD && tx_source==3 && tx_payload_ready;
    bellows_n5_packet_tx #(.DATA_WIDTH(DATA_WIDTH)) packet_tx (
        .clk(clk),.rst_n(rst_n),.cmd_valid(rst_n && tx_state==T_COMMAND),
        .cmd_ready(tx_cmd_ready),.cmd_qp(tx_qp_hold),.cmd_meta(tx_meta),
        .payload_tvalid(tx_payload_valid),.payload_tready(tx_payload_ready),
        .payload_tdata(tx_payload_data),.payload_tkeep(tx_payload_keep),
        .payload_tlast(tx_payload_last),.local_macs(local_macs),.remote_macs(remote_macs),
        .local_ips(local_ips),.remote_ips(remote_ips),
        .tx_tvalid(x5_tx_tvalid),.tx_tready(x5_tx_tready),.tx_tdata(x5_tx_tdata),
        .tx_tkeep(x5_tx_tkeep),.tx_tlast(x5_tx_tlast),.packet_done(packet_done),
        .packet_qp(packet_qp),.packet_is_sack(packet_is_sack),.idle(tx_idle)
    );
    assign global_idle=rst_n && rx_idle && tx_idle && moe_idle && sack_idle &&
        rstate==R_IDLE && wstate==W_IDLE && tx_state==T_IDLE &&
        !event_pending && !peer_valid && !x5_qp_cfg_rsp_valid && !tracker_cfg_rsp_valid;
    assign x5_idle=global_idle;
    integer lane;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rstate<=R_IDLE; received_meta<=0; received_qp<=0; received_psn<=0;
            received_token<=0; received_kind<=0; received_status<=0; received_commit<=0;
            placement_addr<=0; peer_bitmap<=0; peer_offset<=0; peer_valid<=0;
            event_pending<=0; event_status<=0; event_kind<=0; event_qp<=0;
            event_token<=0; event_psn<=0; event_turn<=0;
            wstate<=W_IDLE; write_qp<=0; write_addr<=0; write_key<=0; write_cookie<=0;
            write_bytes<=0; write_input_offset<=0; write_offset<=0; write_limit<=0;
            write_bad<=0; write_status<=0; write_meta<=0; write_data<=0; write_keep<=0;
            tx_state<=T_IDLE; tx_source<=0; tx_cursor<=0; tx_meta<=0; tx_qp_hold<=0;
        end else begin
            if (event_pending && x5_evt_ready) event_pending<=0;
            if (peer_valid && x5_peer_sack_ready) peer_valid<=0;
            if (event_slot) begin
                if (choose_rx_event) begin
                    event_pending<=1; event_turn<=1;
                    if (own_event) begin
                        event_status<=received_status; event_kind<=received_kind;
                        event_qp<=received_qp; event_token<=received_token; event_psn<=received_psn;
                    end else begin
                        event_status<=rx_error_status; event_kind<=rx_error_kind;
                        event_qp<=rx_error_qp; event_token<=rx_error_token; event_psn<=rx_error_psn;
                    end
                end else if (moe_evt_valid) begin
                    event_pending<=1; event_turn<=0; event_kind<=3;
                    event_status<=moe_evt_status; event_qp<=moe_evt_qp;
                    event_token<=moe_evt_token; event_psn<=moe_evt_psn;
                end
            end
            case (rstate)
                R_IDLE: if (rx_cmd_valid && rx_cmd_ready) begin
                    received_meta<=rx_cmd_meta; received_qp<=rx_cmd_qp;
                    received_kind<=rx_cmd_meta[8*5 +:8];
                    received_psn<={rx_cmd_meta[8*12 +:8],rx_cmd_meta[8*13 +:8],rx_cmd_meta[8*14 +:8]};
                    received_token<={rx_cmd_meta[8*20 +:8],rx_cmd_meta[8*21 +:8],
                        rx_cmd_meta[8*22 +:8],rx_cmd_meta[8*23 +:8]};
                    placement_addr<={rx_cmd_meta[8*36 +:8],rx_cmd_meta[8*37 +:8],
                        rx_cmd_meta[8*38 +:8],rx_cmd_meta[8*39 +:8],rx_cmd_meta[8*40 +:8],
                        rx_cmd_meta[8*41 +:8],rx_cmd_meta[8*42 +:8],rx_cmd_meta[8*43 +:8]}+
                        {48'b0,rx_cmd_meta[8*30 +:8],rx_cmd_meta[8*31 +:8]};
                    received_status<=0; received_commit<=0;
                    if (rx_cmd_meta[8*5 +:8]==4) begin peer_bitmap<=0; peer_offset<=0; rstate<=R_PEER; end
                    else rstate<=R_TRACK;
                end
                R_TRACK: if (tracker_req_ready) rstate<=R_DECIDE;
                R_DECIDE: if (tracker_decision_valid) begin
                    if (tracker_decision_status==0) begin
                        if (received_kind==1) rstate<=R_WRITE;
                        else rstate<=R_MOE_COMMAND;
                    end else begin
                        received_status<={2'b0,tracker_decision_status}; rstate<=R_DRAIN;
                    end
                end
                R_DRAIN: if (rx_payload_valid && rx_payload_last) rstate<=R_SNAPSHOT;
                R_WRITE: if (rx_payload_valid && x5_mem_ready) begin
                    placement_addr<=placement_addr+B;
                    if (rx_payload_last) begin received_commit<=1; rstate<=R_COMMIT; end
                end
                R_MOE_COMMAND: if (moe_rx_cmd_ready) rstate<=R_MOE_PAYLOAD;
                R_MOE_PAYLOAD: if (rx_payload_valid && moe_rx_payload_ready && rx_payload_last)
                    rstate<=R_MOE_DONE;
                R_MOE_DONE: if (moe_rx_done_valid) begin
                    received_commit<=moe_rx_done_ok;
                    received_status<=moe_rx_done_ok ? 0 : 7; rstate<=R_COMMIT;
                end
                R_COMMIT: if (tracker_commit_ready) rstate<=R_SNAPSHOT;
                R_SNAPSHOT: if (tracker_sack_valid && snapshot_ready) rstate<=R_EVENT;
                R_EVENT: if (event_slot && choose_rx_event && !peer_valid) rstate<=R_IDLE;
                R_PEER: if (rx_payload_valid) begin
                    for (lane=0;lane<B;lane=lane+1)
                        if (rx_payload_keep[lane] && peer_offset+lane<32)
                            peer_bitmap[8*(peer_offset+lane) +:8]<=rx_payload_data[8*lane +:8];
                    peer_offset<=peer_offset+B;
                    if (rx_payload_last) begin peer_valid<=1; rstate<=R_EVENT; end
                end
                default: rstate<=R_IDLE;
            endcase
            case (wstate)
                W_IDLE: if (x5_write_cmd_valid && x5_write_cmd_ready) begin
                    write_qp<=x5_write_cmd_qp; write_addr<=x5_write_cmd_addr;
                    write_key<=x5_write_cmd_rkey; write_cookie<=x5_write_cmd_cookie;
                    write_bytes<=x5_write_cmd_bytes; write_input_offset<=0;
                    write_offset<=0; write_limit<=(x5_write_cmd_bytes>256)?256:{1'b0,x5_write_cmd_bytes};
                    write_bad<=0; write_status<=0;
                    if (x5_write_cmd_qp>=QPS || !enabled[x5_write_cmd_qp]) begin
                        write_status<=5; wstate<=W_COMPLETE;
                    end else if (x5_write_cmd_bytes==0 || command_end[64]) begin
                        write_status<=7; wstate<=W_COMPLETE;
                    end else wstate<=W_INPUT;
                end
                W_INPUT: if (x5_write_tvalid) begin
                    if (write_violation) write_bad<=1;
                    if (write_input_end>65535) write_input_offset<=65536;
                    else write_input_offset<=write_input_end[16:0];
                    if (x5_write_tlast) begin
                        if (write_bad || write_violation) begin write_status<=9; wstate<=W_COMPLETE; end
                        else wstate<=W_PREPARE;
                    end
                end
                W_PREPARE: begin write_meta<=write_header; wstate<=W_COMMAND; end
                W_COMMAND: if (write_cmd_ready) wstate<=W_FETCH;
                W_FETCH: wstate<=W_CAPTURE;
                W_CAPTURE: begin
                    write_data<=0; write_keep<=0;
                    for (lane=0;lane<B;lane=lane+1)
                        if (write_offset+lane<write_limit) begin
                            write_data[8*lane +:8]<=write_ram_q[8*lane +:8]; write_keep[lane]<=1;
                        end
                    wstate<=W_SEND;
                end
                W_SEND: if (write_payload_ready) begin
                    if (write_offset+B>=write_limit) wstate<=W_WAIT;
                    else begin write_offset<=write_offset+B; wstate<=W_FETCH; end
                end
                W_WAIT: if (packet_done && tx_source==1) begin
                    if (write_limit=={1'b0,write_bytes}) wstate<=W_COMPLETE;
                    else begin
                        write_offset<=write_limit;
                        if (write_limit+17'd256>{1'b0,write_bytes}) write_limit<={1'b0,write_bytes};
                        else write_limit<=write_limit+17'd256;
                        wstate<=W_PREPARE;
                    end
                end
                W_COMPLETE: if (x5_write_cpl_ready) wstate<=W_IDLE;
                default: wstate<=W_IDLE;
            endcase
            case (tx_state)
                T_IDLE: if (source_found) begin
                    tx_source<=source_choice; tx_meta<=selected_meta; tx_qp_hold<=selected_qp;
                    tx_state<=T_COMMAND;
                end
                T_COMMAND: if (tx_cmd_ready) tx_state<=T_PAYLOAD;
                T_PAYLOAD: if (tx_payload_valid && tx_payload_ready && tx_payload_last) tx_state<=T_WAIT;
                T_WAIT: if (packet_done) begin tx_state<=T_IDLE; tx_cursor<=tx_source+1'b1; end
            endcase
        end
    end
endmodule
`default_nettype wire
