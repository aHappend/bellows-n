`default_nettype none
module bellows_n4_top #(
    parameter integer DATA_WIDTH=512,
    parameter integer MAX_PACKET_BYTES=9216,
    parameter integer MAX_SG=16,
    parameter integer QPS=8
) (
    input wire clk, rst_n,
    input wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] s_axis_tdata,
    input wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] s_axis_tkeep,
    input wire s_axis_tvalid, s_axis_tlast,
    output wire s_axis_tready,
    input wire [1:0] s_check_enable,
    input wire [31:0] s_expected_crc32c,
    input wire [63:0] s_expected_crc64_nvme,
    output wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] m_axis_tdata,
    output wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] m_axis_tkeep,
    output wire m_axis_tvalid, m_axis_tlast,
    input wire m_axis_tready,
    output wire m_crc_valid,
    input wire m_crc_ready,
    output wire [31:0] m_crc32c,
    output wire [63:0] m_crc64_nvme,
    output wire [1:0] m_crc_mismatch,
    output wire m_crc_protocol_error,
    input wire cfg_valid,
    input wire [1:0] cfg_op,
    input wire [5:0] cfg_index,
    input wire [511:0] cfg_value, cfg_mask,
    input wire [31:0] cfg_action,
    input wire cfg_enable,
    input wire [327:0] cfg_rss_key,
    output wire cfg_ready,
    output wire m_meta_valid,
    output wire [511:0] m_header,
    output wire [31:0] m_packet_bytes, m_rss_hash,
    output wire m_rss_valid, m_rule_hit,
    output wire [5:0] m_rule_index,
    output wire [31:0] m_action,
    input wire m_meta_ready,
    input wire dma_enable,
    input wire q_cfg_valid,
    input wire [2:0] q_cfg_id,
    input wire q_cfg_enable,
    input wire [63:0] q_cfg_ring_base,
    input wire [8:0] q_cfg_ring_entries,
    input wire [15:0] q_cfg_quantum,
    input wire [31:0] q_cfg_rate,
    input wire [15:0] q_cfg_burst,
    output wire q_cfg_ready,
    input wire db_valid,
    input wire [2:0] db_queue,
    input wire [31:0] db_producer,
    output wire db_ready,
    output wire ctl_valid,
    output wire [2:0] ctl_queue, ctl_code,
    input wire ctl_ready,
    output wire dma_rd_valid,
    output wire [63:0] dma_rd_addr,
    output wire [15:0] dma_rd_len,
    input wire dma_rd_ready,
    input wire dma_rsp_valid,
    input wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] dma_rsp_data,
    input wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] dma_rsp_keep,
    input wire dma_rsp_last, dma_rsp_error,
    output wire dma_rsp_ready,
    output wire dma_cpl_valid,
    output wire [2:0] dma_cpl_queue,
    output wire [31:0] dma_cpl_cookie,
    output wire [2:0] dma_cpl_status,
    output wire [31:0] dma_cpl_bytes,
    input wire dma_cpl_ready,
    output wire dma_idle,
    input wire roce_enable,
    output wire roce_idle,
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
    output wire [((DATA_WIDTH>0)?DATA_WIDTH:1)-1:0] wr_data,
    output wire [((DATA_WIDTH>=8)?(DATA_WIDTH>>3):1)-1:0] wr_keep,
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
    generate if ((DATA_WIDTH==64 || DATA_WIDTH==512) &&
                 MAX_PACKET_BYTES>=1 && MAX_PACKET_BYTES<=9216 &&
                 MAX_SG>=1 && MAX_SG<=16 && QPS>=1 && QPS<=8) begin : g_legal
        wire [DATA_WIDTH-1:0] legacy_data;
        wire [(DATA_WIDTH>>3)-1:0] legacy_keep;
        wire legacy_valid, legacy_last, legacy_ready, receive_ready, receive_idle;
        wire legacy_input_ready;
        wire configuration_fire=roce_enable &&
             ((qp_cfg_valid && qp_cfg_ready) || (coll_cfg_valid && coll_cfg_ready));
        reg external_sent, receive_sent, fork_open;
        assign m_axis_tdata=legacy_data;
        assign s_axis_tready=legacy_input_ready && !configuration_fire;
        assign m_axis_tkeep=legacy_keep;
        assign m_axis_tlast=legacy_last;
        assign m_axis_tvalid=legacy_valid &&
                             (!roce_enable || (fork_open && !external_sent));
        assign legacy_ready=!roce_enable ? m_axis_tready :
                            fork_open && (external_sent || m_axis_tready) &&
                            (receive_sent || receive_ready);
        assign roce_idle=rst_n && receive_idle && !fork_open && !legacy_valid && dma_idle;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin external_sent<=0; receive_sent<=0; fork_open<=0; end
            else if (!roce_enable) begin external_sent<=0; receive_sent<=0; fork_open<=0; end
            else begin
                if (!fork_open && legacy_valid && receive_ready) fork_open<=1;
                if (m_axis_tvalid && m_axis_tready) external_sent<=1;
                if (legacy_valid && fork_open && !receive_sent && receive_ready)
                    receive_sent<=1;
                if (legacy_valid && legacy_ready) begin
                    external_sent<=0; receive_sent<=0;
                    if (legacy_last) fork_open<=0;
                end
            end
        end
        furnace_x3_top #(.DATA_WIDTH(DATA_WIDTH), .MAX_PACKET_BYTES(MAX_PACKET_BYTES),
                         .MAX_SG(MAX_SG)) legacy_core (
            .clk(clk), .rst_n(rst_n), .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
            .s_axis_tvalid(s_axis_tvalid && !configuration_fire), .s_axis_tlast(s_axis_tlast),
            .s_axis_tready(legacy_input_ready),
            .s_check_enable(s_check_enable), .s_expected_crc32c(s_expected_crc32c),
            .s_expected_crc64_nvme(s_expected_crc64_nvme),
            .m_axis_tdata(legacy_data), .m_axis_tkeep(legacy_keep),
            .m_axis_tvalid(legacy_valid), .m_axis_tlast(legacy_last), .m_axis_tready(legacy_ready),
            .m_crc_valid(m_crc_valid), .m_crc_ready(m_crc_ready), .m_crc32c(m_crc32c),
            .m_crc64_nvme(m_crc64_nvme), .m_crc_mismatch(m_crc_mismatch),
            .m_crc_protocol_error(m_crc_protocol_error), .cfg_valid(cfg_valid),
            .cfg_op(cfg_op), .cfg_index(cfg_index), .cfg_value(cfg_value), .cfg_mask(cfg_mask),
            .cfg_action(cfg_action), .cfg_enable(cfg_enable), .cfg_rss_key(cfg_rss_key),
            .cfg_ready(cfg_ready), .m_meta_valid(m_meta_valid), .m_header(m_header),
            .m_packet_bytes(m_packet_bytes), .m_rss_hash(m_rss_hash), .m_rss_valid(m_rss_valid),
            .m_rule_hit(m_rule_hit), .m_rule_index(m_rule_index), .m_action(m_action),
            .m_meta_ready(m_meta_ready), .dma_enable(dma_enable),
            .q_cfg_valid(q_cfg_valid), .q_cfg_id(q_cfg_id), .q_cfg_enable(q_cfg_enable),
            .q_cfg_ring_base(q_cfg_ring_base), .q_cfg_ring_entries(q_cfg_ring_entries),
            .q_cfg_quantum(q_cfg_quantum), .q_cfg_rate(q_cfg_rate), .q_cfg_burst(q_cfg_burst),
            .q_cfg_ready(q_cfg_ready), .db_valid(db_valid), .db_queue(db_queue),
            .db_producer(db_producer), .db_ready(db_ready), .ctl_valid(ctl_valid),
            .ctl_queue(ctl_queue), .ctl_code(ctl_code), .ctl_ready(ctl_ready),
            .dma_rd_valid(dma_rd_valid), .dma_rd_addr(dma_rd_addr), .dma_rd_len(dma_rd_len),
            .dma_rd_ready(dma_rd_ready), .dma_rsp_valid(dma_rsp_valid), .dma_rsp_data(dma_rsp_data),
            .dma_rsp_keep(dma_rsp_keep), .dma_rsp_last(dma_rsp_last), .dma_rsp_error(dma_rsp_error),
            .dma_rsp_ready(dma_rsp_ready), .dma_cpl_valid(dma_cpl_valid),
            .dma_cpl_queue(dma_cpl_queue), .dma_cpl_cookie(dma_cpl_cookie),
            .dma_cpl_status(dma_cpl_status), .dma_cpl_bytes(dma_cpl_bytes),
            .dma_cpl_ready(dma_cpl_ready), .dma_idle(dma_idle)
        );
        furnace_roce_rx #(.DATA_WIDTH(DATA_WIDTH), .MAX_PACKET_BYTES(MAX_PACKET_BYTES),
                         .QPS(QPS)) roce_rx (
            .clk(clk), .rst_n(rst_n), .enable(roce_enable), .idle(receive_idle),
            .boundary_idle(!fork_open && !legacy_valid && dma_idle),
            .s_valid(roce_enable && fork_open && legacy_valid && !receive_sent),
            .s_ready(receive_ready), .s_data(legacy_data), .s_keep(legacy_keep), .s_last(legacy_last),
            .qp_cfg_valid(qp_cfg_valid), .qp_cfg_ready(qp_cfg_ready), .qp_cfg_enable(qp_cfg_enable),
            .qp_cfg_index(qp_cfg_index), .qp_cfg_local_qpn(qp_cfg_local_qpn),
            .qp_cfg_remote_qpn(qp_cfg_remote_qpn), .qp_cfg_expected_psn(qp_cfg_expected_psn),
            .qp_cfg_rkey(qp_cfg_rkey), .qp_cfg_base(qp_cfg_base), .qp_cfg_length(qp_cfg_length),
            .qp_cfg_rank(qp_cfg_rank), .qp_cfg_rsp_valid(qp_cfg_rsp_valid),
            .qp_cfg_rsp_ready(qp_cfg_rsp_ready), .qp_cfg_rsp_status(qp_cfg_rsp_status),
            .coll_cfg_valid(coll_cfg_valid), .coll_cfg_ready(coll_cfg_ready),
            .coll_cfg_enable(coll_cfg_enable), .coll_cfg_job(coll_cfg_job),
            .coll_cfg_format(coll_cfg_format), .coll_cfg_op(coll_cfg_op),
            .coll_cfg_participants(coll_cfg_participants), .coll_cfg_bytes(coll_cfg_bytes),
            .coll_cfg_addr(coll_cfg_addr), .coll_cfg_rsp_valid(coll_cfg_rsp_valid),
            .coll_cfg_rsp_ready(coll_cfg_rsp_ready), .coll_cfg_rsp_status(coll_cfg_rsp_status),
            .wr_valid(wr_valid), .wr_ready(wr_ready), .wr_addr(wr_addr), .wr_data(wr_data),
            .wr_keep(wr_keep), .wr_last(wr_last), .rdma_evt_valid(rdma_evt_valid),
            .rdma_evt_ready(rdma_evt_ready), .rdma_evt_status(rdma_evt_status),
            .rdma_evt_qpn(rdma_evt_qpn), .rdma_evt_psn(rdma_evt_psn),
            .rdma_evt_expected_psn(rdma_evt_expected_psn), .rdma_evt_bytes(rdma_evt_bytes),
            .rdma_evt_addr(rdma_evt_addr), .ack_valid(ack_valid), .ack_ready(ack_ready),
            .ack_data(ack_data), .ack_local_qpn(ack_local_qpn), .ack_remote_qpn(ack_remote_qpn),
            .ack_psn(ack_psn), .coll_done_valid(coll_done_valid),
            .coll_done_ready(coll_done_ready), .coll_done_job(coll_done_job),
            .coll_done_bytes(coll_done_bytes)
        );
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: DATA_WIDTH=64/512, MAX_PACKET_BYTES=1..9216, MAX_SG=1..16, QPS=1..8 required");
        assign s_axis_tready=0; assign cfg_ready=0;
        assign m_axis_tdata=0; assign m_axis_tkeep=0; assign m_axis_tvalid=0;
        assign m_axis_tlast=0; assign m_crc_valid=0; assign m_crc32c=0;
        assign m_crc64_nvme=0; assign m_crc_mismatch=0; assign m_crc_protocol_error=0;
        assign m_meta_valid=0; assign m_header=0; assign m_packet_bytes=0;
        assign m_rss_hash=0; assign m_rss_valid=0; assign m_rule_hit=0;
        assign m_rule_index=0; assign m_action=0;
        assign q_cfg_ready=0; assign db_ready=0; assign ctl_valid=0;
        assign ctl_queue=0; assign ctl_code=0;
        assign dma_rd_valid=0; assign dma_rd_addr=0; assign dma_rd_len=0;
        assign dma_rsp_ready=0; assign dma_cpl_valid=0; assign dma_cpl_queue=0;
        assign dma_cpl_cookie=0; assign dma_cpl_status=0; assign dma_cpl_bytes=0;
        assign dma_idle=0; assign roce_idle=0; assign qp_cfg_ready=0;
        assign qp_cfg_rsp_valid=0; assign qp_cfg_rsp_status=0;
        assign coll_cfg_ready=0; assign coll_cfg_rsp_valid=0; assign coll_cfg_rsp_status=0;
        assign wr_valid=0; assign wr_addr=0; assign wr_data=0; assign wr_keep=0; assign wr_last=0;
        assign rdma_evt_valid=0; assign rdma_evt_status=0; assign rdma_evt_qpn=0;
        assign rdma_evt_psn=0; assign rdma_evt_expected_psn=0;
        assign rdma_evt_bytes=0; assign rdma_evt_addr=0;
        assign ack_valid=0; assign ack_data=0; assign ack_local_qpn=0;
        assign ack_remote_qpn=0; assign ack_psn=0;
        assign coll_done_valid=0; assign coll_done_job=0; assign coll_done_bytes=0;
    end endgenerate
endmodule
`default_nettype wire
