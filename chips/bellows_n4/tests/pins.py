"""Frozen public top-level port declarations shared only by testbench generators."""


INPUTS = {
    "clk": "1", "rst_n": "1", "s_axis_tdata": "W", "s_axis_tkeep": "B",
    "s_axis_tvalid": "1", "s_axis_tlast": "1", "s_check_enable": "2",
    "s_expected_crc32c": "32", "s_expected_crc64_nvme": "64",
    "m_axis_tready": "1", "m_crc_ready": "1", "cfg_valid": "1", "cfg_op": "2",
    "cfg_index": "6", "cfg_value": "512", "cfg_mask": "512",
    "cfg_action": "32", "cfg_enable": "1", "cfg_rss_key": "328",
    "m_meta_ready": "1", "dma_enable": "1", "q_cfg_valid": "1", "q_cfg_id": "3",
    "q_cfg_enable": "1", "q_cfg_ring_base": "64", "q_cfg_ring_entries": "9",
    "q_cfg_quantum": "16", "q_cfg_rate": "32", "q_cfg_burst": "16",
    "db_valid": "1", "db_queue": "3", "db_producer": "32", "ctl_ready": "1",
    "dma_rd_ready": "1", "dma_rsp_valid": "1", "dma_rsp_data": "W",
    "dma_rsp_keep": "B", "dma_rsp_last": "1", "dma_rsp_error": "1",
    "dma_cpl_ready": "1", "roce_enable": "1", "qp_cfg_valid": "1",
    "qp_cfg_enable": "1", "qp_cfg_index": "3", "qp_cfg_local_qpn": "24",
    "qp_cfg_remote_qpn": "24", "qp_cfg_expected_psn": "24", "qp_cfg_rkey": "32",
    "qp_cfg_base": "64", "qp_cfg_length": "64", "qp_cfg_rank": "3",
    "qp_cfg_rsp_ready": "1", "coll_cfg_valid": "1", "coll_cfg_enable": "1",
    "coll_cfg_job": "16", "coll_cfg_format": "2", "coll_cfg_op": "2",
    "coll_cfg_participants": "4", "coll_cfg_bytes": "32", "coll_cfg_addr": "64",
    "coll_cfg_rsp_ready": "1", "wr_ready": "1", "rdma_evt_ready": "1",
    "ack_ready": "1", "coll_done_ready": "1",
}

OUTPUTS = {
    "s_axis_tready": "1", "m_axis_tdata": "W", "m_axis_tkeep": "B",
    "m_axis_tvalid": "1", "m_axis_tlast": "1", "m_crc_valid": "1",
    "m_crc32c": "32", "m_crc64_nvme": "64", "m_crc_mismatch": "2",
    "m_crc_protocol_error": "1", "cfg_ready": "1", "m_meta_valid": "1",
    "m_header": "512", "m_packet_bytes": "32", "m_rss_hash": "32",
    "m_rss_valid": "1", "m_rule_hit": "1", "m_rule_index": "6", "m_action": "32",
    "q_cfg_ready": "1", "db_ready": "1", "ctl_valid": "1", "ctl_queue": "3",
    "ctl_code": "3", "dma_rd_valid": "1", "dma_rd_addr": "64", "dma_rd_len": "16",
    "dma_rsp_ready": "1", "dma_cpl_valid": "1", "dma_cpl_queue": "3",
    "dma_cpl_cookie": "32", "dma_cpl_status": "3", "dma_cpl_bytes": "32",
    "dma_idle": "1", "roce_idle": "1", "qp_cfg_ready": "1",
    "qp_cfg_rsp_valid": "1", "qp_cfg_rsp_status": "3", "coll_cfg_ready": "1",
    "coll_cfg_rsp_valid": "1", "coll_cfg_rsp_status": "3", "wr_valid": "1",
    "wr_addr": "64", "wr_data": "W", "wr_keep": "B", "wr_last": "1",
    "rdma_evt_valid": "1", "rdma_evt_status": "4", "rdma_evt_qpn": "24",
    "rdma_evt_psn": "24", "rdma_evt_expected_psn": "24", "rdma_evt_bytes": "32",
    "rdma_evt_addr": "64", "ack_valid": "1", "ack_data": "128",
    "ack_local_qpn": "24", "ack_remote_qpn": "24", "ack_psn": "24",
    "coll_done_valid": "1", "coll_done_job": "16", "coll_done_bytes": "32",
}


def declarations():
    return "\n".join(
        f"{kind} " + ("" if width == "1" else f"[{width}-1:0] ") +
        name + ("=0;" if kind == "reg" and name != "rst_n" else ";")
        for kind, ports in (("reg", INPUTS), ("wire", OUTPUTS))
        for name, width in ports.items())
