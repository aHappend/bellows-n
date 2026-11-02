"""Public-pin packet/CRC/header/transport and collective transaction comparisons."""

import json
from pathlib import Path
import random
import struct

from pins import declarations, OUTPUTS
from reference import crc_reflected, legacy_header, numerical, roce_frame


def ack_header(remote, psn, syndrome, msn):
    data = (b"\x11\0\xff\xff\0" + remote.to_bytes(3, "big") +
            b"\0" + psn.to_bytes(3, "big") +
            bytes([syndrome]) + msn.to_bytes(3, "big"))
    return int.from_bytes(data, "little")


class Scenario:
    def __init__(self, width, seed):
        self.width = width
        self.rng = random.Random(seed)
        self.steps = []
        self.qps = {}
        self.frames = []
        self.job = None

    def qp(self, index, *, psn=17, enable=True):
        qp = {"qpn": 0x120000 + index * 0x100, "remote": 0x340000 + index,
              "psn": psn, "key": 0xabcdef01, "base": 0x1000,
              "length": 0x10000, "rank": index, "msn": 0,
              "open": None, "committed": False, "enable": enable}
        self.qps[index] = qp
        self.steps.append(("qp", index, dict(qp)))

    def collective(self, fmt, op, participants, size, job):
        self.job = {"format": fmt, "op": op, "participants": participants,
                    "size": size, "job": job, "rank": 0, "value": None}
        self.steps.append(("collective", dict(self.job)))

    def disable_collective(self):
        self.steps.append(("disable_collective",))
        self.job = None

    def raw(self, name, frame, status, *, qpn=0, psn=0, addr=0):
        entry = {"name": name, "frame": frame, "status": status,
                 "qpn": qpn, "psn": psn, "expected": 0, "bytes": 0, "addr": addr,
                 "writes": b"", "write_addr": 0, "ack": None, "done": None}
        self.frames.append(entry)
        self.steps.append(("frame", entry))

    def packet(self, name, index, payload, *, opcode=10, addr=0x1003,
               key=None, length=None, psn=None, version=4, tags=(), options=b"",
               force_status=None, unknown_qpn=None):
        qp = self.qps[index]
        wire_psn = qp["psn"] if psn is None else psn
        key = qp["key"] if key is None else key
        length = len(payload) if length is None else length
        qpn = qp["qpn"] if unknown_qpn is None else unknown_qpn
        frame = roce_frame(payload, opcode=opcode, addr=addr, rkey=key,
                           message_bytes=length, qpn=qpn, psn=wire_psn,
                           version=version, tags=tags, options=options)
        status = 0
        expected = qp["psn"]
        event_addr = 0
        syndrome = 0
        response_psn = wire_psn
        complete = False
        writes = b""
        done = None
        staged_message = qp["open"]
        if unknown_qpn is not None:
            status = 5
            expected = 0
        elif opcode == 17:
            status = 10
            expected = 0
        elif opcode not in (6, 7, 8, 9, 10, 11):
            status = 4
            syndrome = 0x61
        elif wire_psn != qp["psn"]:
            status = 6
            duplicate = qp["committed"] and wire_psn == ((qp["psn"] - 1) & 0xffffff)
            syndrome = 0 if duplicate else 0x60
            response_psn = wire_psn if duplicate else qp["psn"]
        else:
            if opcode in (6, 10, 11):
                event_addr = addr
                if qp["open"] is not None or key != qp["key"] or (
                        len(payload) > length if opcode == 6 else len(payload) != length):
                    status = 7
                    syndrome = 0x62 if key != qp["key"] else 0x61
                elif addr < qp["base"] or addr + length > qp["base"] + qp["length"] or (
                        addr + length >= 1 << 64):
                    status = 7
                    syndrome = 0x62
                complete = opcode != 6
                staged_message = ((addr, length, len(payload)) if opcode == 6 else None)
            else:
                message = qp["open"]
                if message is None:
                    status = 7
                    syndrome = 0x61
                else:
                    first_addr, total, offset = message
                    event_addr = first_addr + offset
                    if (offset + len(payload) > total if opcode == 7
                            else offset + len(payload) != total):
                        status = 7
                        syndrome = 0x61
                    complete = opcode != 7
                    staged_message = (None if complete else
                                      (first_addr, total, offset + len(payload)))
            if status == 0 and self.job is not None and event_addr == 0x2003:
                job = self.job
                if opcode not in (10, 11) or qp["rank"] != job["rank"] or (
                        len(payload) != job["size"]) or job["rank"] >= job["participants"]:
                    status = 8
                    syndrome = 0x61
                else:
                    status = 1
                    if job["rank"] == 0:
                        job["value"] = payload
                    else:
                        size = 4 if job["format"] == 2 else 2
                        job["value"] = b"".join(
                            numerical(int.from_bytes(job["value"][i:i + size], "little"),
                                      int.from_bytes(payload[i:i + size], "little"),
                                      job["format"], job["op"]).to_bytes(size, "little")
                            for i in range(0, len(payload), size))
                    job["rank"] += 1
                    if job["rank"] == job["participants"]:
                        writes = job["value"]
                        done = (job["job"], job["size"])
            elif status == 0:
                writes = payload
            if status in (0, 1):
                qp["psn"] = (qp["psn"] + 1) & 0xffffff
                qp["msn"] = (qp["msn"] + int(complete)) & 0xffffff
                qp["committed"] = True
                qp["open"] = staged_message
                expected = qp["psn"]
        if force_status is not None and status != force_status:
            raise AssertionError(f"stimulus precondition {name}: expected {force_status}, model {status}")
        ack = None if status in (5, 10) else (
            ack_header(qp["remote"], response_psn, syndrome, qp["msn"]),
            qp["qpn"], qp["remote"], response_psn)
        entry = {"name": name, "frame": frame, "status": status, "qpn": qpn,
                 "psn": wire_psn, "expected": expected,
                 "bytes": len(payload) if opcode in (6, 7, 8, 9, 10, 11) else 0,
                 "addr": event_addr, "writes": writes, "write_addr": event_addr,
                 "ack": ack, "done": done}
        self.frames.append(entry)
        self.steps.append(("frame", entry))
        return entry


def scenarios(width, seed, *, compact=False, stale_address=False):
    scenario = Scenario(width, seed)
    if stale_address:
        scenario.qp(0)
        scenario.packet("only-closes-message", 0, b"abcd", addr=0x1003)
        scenario.packet("middle-without-open-message", 0, b"efgh", opcode=7,
                        force_status=7)
        scenario.packet("unchanged-psn-valid-retry", 0, b"ijkl", addr=0x1013)
        return scenario
    for index in range(2 if compact else 8):
        scenario.qp(index)
    rng = scenario.rng
    if compact:
        scenario.packet("compact-protected-write", 0, bytes(range(33)))
        scenario.collective(0, 0, 2, 18, 1)
        scenario.packet("compact-seed", 0, b"\xff\x7f" * 9, addr=0x2003)
        scenario.packet("compact-result", 1, b"\x01\0" * 9, addr=0x2003)
        scenario.disable_collective()
        return scenario
    for version in (4, 6):
        for tags in ((), (0x8100,), (0x88a8, 0x8100)):
            for size in (1, 2, 3, 4, width // 8, width // 8 + 1):
                scenario.packet(f"ip{version}-tags{len(tags)}-payload{size}", 0,
                                rng.randbytes(size), version=version, tags=tags)
    for ihl in range(5, 16):
        scenario.packet(f"ipv4-options-ihl{ihl}", 0, rng.randbytes(23),
                        options=b"\x01" * (4 * (ihl - 5)))
    # Exact, previous, ahead and behind PSNs have observably distinct ACK/NAK.
    qp = scenario.qps[0]
    for delta in (-1, 1, -3):
        scenario.packet(f"sequence-delta{delta}", 0, b"sequence",
                        psn=(qp["psn"] + delta) & 0xffffff, force_status=6)
    scenario.packet("sequence-retry", 0, b"sequence")
    scenario.qp(2, psn=0xffffff)
    scenario.packet("psn-wrap-ffffff", 2, b"\x12\x34")
    scenario.packet("psn-wrap-zero", 2, b"\x56\x78")
    for name, args in (
            ("rkey-rejected", {"key": 0}),
            ("region-before", {"addr": 0xfff}),
            ("region-after", {"addr": 0x11000}),
            ("address-overflow", {"addr": 0xffffffffffffffff}),
            ("declared-length-short", {"length": 3}),
            ("declared-length-long", {"length": 9})):
        scenario.packet(name, 0, b"\x12\x34\x56\x78", force_status=7, **args)
        scenario.packet(name + "-retry", 0, b"\x12\x34\x56\x78")
    scenario.packet("region-first-byte", 0, b"\x01", addr=0x1000)
    scenario.packet("region-last-byte", 0, b"\x02", addr=0x10fff)
    scenario.packet("full-qpn-alias-miss", 0, b"\x01", unknown_qpn=0x220000,
                    force_status=5)
    scenario.packet("middle-without-first", 0, b"abcd", opcode=7, force_status=7)
    for immediate_last in (False, True):
        scenario.packet("write-first", 0, b"abc", opcode=6, length=12)
        scenario.packet("first-cannot-replace", 0, b"abc", opcode=6, length=12,
                        force_status=7)
        scenario.packet("interleaved-qpn", 1, b"other")
        scenario.packet("write-middle", 0, b"defgh", opcode=7)
        scenario.packet("last-length-rejected", 0, b"bad", opcode=8, force_status=7)
        scenario.packet("write-last-retry", 0, b"ijkl",
                        opcode=9 if immediate_last else 8)
    scenario.packet("write-only-immediate", 0, b"excludes-imm-and-pad", opcode=11)
    scenario.packet("received-ack", 0, b"", opcode=17, force_status=10)
    qpn = scenario.qps[0]["qpn"]
    psn = scenario.qps[0]["psn"]
    nak = roce_frame(b"", opcode=17, qpn=qpn, psn=psn, aeth=0x60000007)
    scenario.raw("received-sequence-nak", nak, 10, qpn=qpn, psn=psn)
    scenario.packet("unsupported-verb", 0, b"", opcode=0x12, force_status=4)
    good = roce_frame(b"abcdefgh", qpn=qpn, psn=psn)
    for name, offset, status in (("bad-payload", -5, 9), ("bad-icrc", -1, 9),
                                 ("bad-ip-checksum", 24, 3)):
        bad = bytearray(good)
        bad[offset] ^= 1
        scenario.raw(name, bytes(bad), status, qpn=qpn, psn=psn, addr=0x1003)
    scenario.raw("truncated-frame", good[:-1], 3, qpn=qpn, psn=psn, addr=0x1003)
    scenario.raw("oversize-drain", good + bytes(9217), 3)
    ordinary = bytes.fromhex("02000000000202000000000188b5") + rng.randbytes(31)
    scenario.raw("non-roce-ethernet", ordinary, 2)
    # No rejected packet may advance sequence or poison the subsequent write.
    scenario.packet("bad-frame-retry", 0, b"abcdefgh")
    for fmt in range(3):
        size = 4 if fmt == 2 else 2
        for op in range(3):
            for participants in (1, 2, 3, 8):
                vector_bytes = (129 * (width // 8) if participants == 8
                                else size * (participants + 1))
                # 512-bit, 129-beat vectors fit the 9216-byte frame bound.
                for rank in range(8):
                    scenario.qp(rank, enable=rank < participants)
                scenario.collective(fmt, op, participants, vector_bytes,
                                    100 + fmt * 12 + op * 4 + participants)
                if participants > 1:
                    scenario.packet("wrong-contributor-rank", 1, bytes(vector_bytes),
                                    addr=0x2003, force_status=8)
                scenario.packet("wrong-contributor-shape", 0, bytes(vector_bytes + size),
                                addr=0x2003, force_status=8)
                scenario.packet("segmented-collective-rejected", 0, bytes(vector_bytes),
                                opcode=6, length=vector_bytes, addr=0x2003, force_status=8)
                for rank in range(participants):
                    tensor = rng.randbytes(vector_bytes)
                    scenario.packet(f"collective-f{fmt}-o{op}-n{participants}-rank{rank}",
                                    rank, tensor, addr=0x2003,
                                    opcode=11 if rank & 1 else 10, force_status=1)
                    if rank < participants - 1:
                        scenario.packet("duplicate-contributor-new-psn", rank, tensor,
                                        addr=0x2003, force_status=8)
                scenario.packet("completed-job-reservation", 0, bytes(vector_bytes),
                                addr=0x2003, force_status=8)
                scenario.disable_collective()
    for rank in range(8):
        scenario.qp(rank)
    while len(scenario.frames) < 220:
        index = rng.randrange(8)
        scenario.packet(f"random-interleaved-{len(scenario.frames)}", index,
                        rng.randbytes(rng.randrange(1, 300)),
                        version=rng.choice((4, 6)))
    return scenario


BODY = r"""
always #5 clk=~clk;
reg initial_reset_sample=0;
reg active=0, input_fire=0, qp_fire=0, coll_fire=0;
integer cycles=0, frame_id=-1, frame_length=0, write_length=0;
integer out_bytes=0, write_bytes=0, crcs=0, metas=0, events=0, acks=0, dones=0;
integer frames_compared=0, last_write_cycle=-1;
integer write_streak=0, max_write_streak=0;
reg [7:0] packet[0:19000], tensor[0:9215];
reg [3:0] expected_status;
reg [23:0] expected_qpn, expected_psn, expected_next, expected_ack_psn;
reg [23:0] expected_ack_local, expected_ack_remote;
reg [31:0] expected_bytes;
reg [63:0] expected_addr, expected_write_addr;
reg [127:0] expected_ack;
reg want_ack, want_done;
reg [15:0] expected_job;
reg [31:0] expected_done_bytes, expected_crc32;
reg [63:0] expected_crc64;
reg [511:0] expected_header;
reg [31:0] expected_rss;
reg expected_rss_valid;
integer random_state;
reg block_axis=0, block_crc=0, block_meta=0, block_write=0, block_evt=0;
reg block_ack=0, block_done=0;
reg [W+B:0] held_axis;
reg [98:0] held_crc;
reg [615:0] held_meta;
reg [W+B+64:0] held_write;
reg [171:0] held_evt;
reg [199:0] held_ack;
reg [47:0] held_done;
integer stalls_axis=0,stalls_crc=0,stalls_meta=0,stalls_write=0;
integer stalls_evt=0,stalls_ack=0,stalls_done=0;

task automatic reset_outputs;
begin
    if (RESET_BUNDLE !== 0) $fatal(1,"TOP_RESET_X_OR_NONZERO");
end
endtask
always @(posedge clk) if (!rst_n) reset_outputs();
always @(negedge clk) if (!rst_n) reset_outputs();
always @(posedge initial_reset_sample) reset_outputs();

task automatic observe;
integer lane, valid_bytes;
begin
    input_fire=s_axis_tvalid && s_axis_tready;
    qp_fire=qp_cfg_valid && qp_cfg_ready;
    coll_fire=coll_cfg_valid && coll_cfg_ready;
    if ((^OUTPUT_BUNDLE) === 1'bx) begin
        XZ_DIAGNOSTICS
        $fatal(1,"TOP_ACTIVE_XZ frame=%0d",frame_id);
    end
    if (block_axis && (!m_axis_tvalid || {m_axis_tdata,m_axis_tkeep,m_axis_tlast} !== held_axis))
        $fatal(1,"LEGACY_PAYLOAD_STABILITY");
    if (block_crc && (!m_crc_valid || {m_crc32c,m_crc64_nvme,m_crc_mismatch,m_crc_protocol_error} !== held_crc))
        $fatal(1,"CRC_STABILITY");
    if (block_meta && (!m_meta_valid || {m_header,m_packet_bytes,m_rss_hash,m_rss_valid,m_rule_hit,m_rule_index,m_action} !== held_meta))
        $fatal(1,"META_STABILITY");
    if (block_write && (!wr_valid || {wr_data,wr_keep,wr_addr,wr_last} !== held_write))
        $fatal(1,"WRITE_STABILITY");
    if (block_evt && (!rdma_evt_valid || {rdma_evt_status,rdma_evt_qpn,rdma_evt_psn,rdma_evt_expected_psn,rdma_evt_bytes,rdma_evt_addr} !== held_evt))
        $fatal(1,"EVENT_STABILITY");
    if (block_ack && (!ack_valid || {ack_data,ack_local_qpn,ack_remote_qpn,ack_psn} !== held_ack))
        $fatal(1,"ACK_STABILITY");
    if (block_done && (!coll_done_valid || {coll_done_job,coll_done_bytes} !== held_done))
        $fatal(1,"COMPLETION_STABILITY");
    block_axis=m_axis_tvalid && !m_axis_tready;
    block_crc=m_crc_valid && !m_crc_ready;
    block_meta=m_meta_valid && !m_meta_ready;
    block_write=wr_valid && !wr_ready;
    block_evt=rdma_evt_valid && !rdma_evt_ready;
    block_ack=ack_valid && !ack_ready;
    block_done=coll_done_valid && !coll_done_ready;
    held_axis={m_axis_tdata,m_axis_tkeep,m_axis_tlast};
    held_crc={m_crc32c,m_crc64_nvme,m_crc_mismatch,m_crc_protocol_error};
    held_meta={m_header,m_packet_bytes,m_rss_hash,m_rss_valid,m_rule_hit,m_rule_index,m_action};
    held_write={wr_data,wr_keep,wr_addr,wr_last};
    held_evt={rdma_evt_status,rdma_evt_qpn,rdma_evt_psn,rdma_evt_expected_psn,rdma_evt_bytes,rdma_evt_addr};
    held_ack={ack_data,ack_local_qpn,ack_remote_qpn,ack_psn};
    held_done={coll_done_job,coll_done_bytes};
    stalls_axis=stalls_axis+block_axis; stalls_crc=stalls_crc+block_crc;
    stalls_meta=stalls_meta+block_meta; stalls_write=stalls_write+block_write;
    stalls_evt=stalls_evt+block_evt; stalls_ack=stalls_ack+block_ack;
    stalls_done=stalls_done+block_done;
    if (!active && (m_axis_tvalid || m_crc_valid || m_meta_valid || wr_valid ||
                    rdma_evt_valid || ack_valid || coll_done_valid))
        $fatal(1,"UNSOLICITED_OUTPUT frame=%0d",frame_id);
    if (active) begin
        if (m_axis_tvalid && m_axis_tready) begin
            valid_bytes=0;
            for (lane=0;lane<B;lane=lane+1) begin
                if (m_axis_tkeep[lane]) begin
                    if (out_bytes+lane>=frame_length ||
                        m_axis_tdata[lane*8 +:8] !== packet[out_bytes+lane])
                        $fatal(1,"PAYLOAD_ASSERTION frame=%0d byte=%0d",frame_id,out_bytes+lane);
                    valid_bytes=valid_bytes+1;
                end
            end
            if (m_axis_tkeep !== ({B{1'b1}} >> (B-valid_bytes)) ||
                m_axis_tlast !== (out_bytes+valid_bytes==frame_length))
                $fatal(1,"PAYLOAD_SHAPE");
            out_bytes=out_bytes+valid_bytes;
        end
        if (m_crc_valid && m_crc_ready) begin
            if (crcs!=0 || {m_crc32c,m_crc64_nvme,m_crc_mismatch,m_crc_protocol_error}
                !== {expected_crc32,expected_crc64,2'b0,1'b0})
                $fatal(1,"CRC_ASSERTION frame=%0d expected=%h/%h observed=%h/%h error=%b",
                       frame_id,expected_crc32,expected_crc64,m_crc32c,m_crc64_nvme,m_crc_protocol_error);
            crcs=crcs+1;
        end
        if (m_meta_valid && m_meta_ready) begin
            if (metas!=0 || {m_header,m_packet_bytes,m_rss_hash,m_rss_valid,m_rule_hit,m_rule_index,m_action}
                !== {expected_header,32'(frame_length),expected_rss,expected_rss_valid,1'b0,6'b0,32'b0})
                $fatal(1,"META_ASSERTION frame=%0d expected_header=%h observed=%h expected_rss=%h observed=%h",
                       frame_id,expected_header,m_header,expected_rss,m_rss_hash);
            metas=metas+1;
        end
        if (ack_valid) begin
            if (!want_ack || write_bytes!=write_length ||
                (write_length!=0 && cycles<=last_write_cycle))
                $fatal(1,"ACK_BEFORE_COMMIT frame=%0d",frame_id);
            if ({ack_data,ack_local_qpn,ack_remote_qpn,ack_psn} !==
                {expected_ack,expected_ack_local,expected_ack_remote,expected_ack_psn})
                $fatal(1,"ACK_ASSERTION frame=%0d expected=%h observed=%h",frame_id,expected_ack,ack_data);
            if (ack_ready) begin
                if (acks!=0) $fatal(1,"ACK_DUPLICATE");
                acks=acks+1;
            end
        end
        if (rdma_evt_valid && rdma_evt_ready) begin
            if (events!=0 || {rdma_evt_status,rdma_evt_qpn,rdma_evt_psn,rdma_evt_expected_psn,rdma_evt_bytes,rdma_evt_addr}
                !== {expected_status,expected_qpn,expected_psn,expected_next,expected_bytes,expected_addr})
                $fatal(1,"EVENT_ASSERTION frame=%0d expected=%h/%h/%h/%h/%h/%h observed=%h/%h/%h/%h/%h/%h",
                       frame_id,expected_status,expected_qpn,expected_psn,expected_next,expected_bytes,expected_addr,
                       rdma_evt_status,rdma_evt_qpn,rdma_evt_psn,rdma_evt_expected_psn,rdma_evt_bytes,rdma_evt_addr);
            if (write_bytes!=write_length) $fatal(1,"EVENT_BEFORE_COMMIT");
            events=events+1;
        end
        if (coll_done_valid) begin
            if (!want_done || write_bytes!=write_length || cycles<=last_write_cycle ||
                {coll_done_job,coll_done_bytes} !== {expected_job,expected_done_bytes})
                $fatal(1,"COLLECTIVE_COMPLETION_ASSERTION");
            if (coll_done_ready) begin
                if (dones!=0) $fatal(1,"COMPLETION_DUPLICATE");
                dones=dones+1;
            end
        end
        if (wr_valid && wr_ready) begin
            if (write_bytes>=write_length || wr_addr !== expected_write_addr+write_bytes)
                $fatal(1,"DMP_ADDRESS_ASSERTION frame=%0d byte=%0d address=%h",frame_id,write_bytes,wr_addr);
            valid_bytes=(write_length-write_bytes<B) ? write_length-write_bytes : B;
            if (wr_keep !== ({B{1'b1}} >> (B-valid_bytes)) ||
                wr_last !== (write_bytes+valid_bytes==write_length))
                $fatal(1,"DMP_KEEP_LAST_ASSERTION");
            for (lane=0;lane<B;lane=lane+1) begin
                if (lane<valid_bytes) begin
                    if (wr_data[lane*8 +:8] !== tensor[write_bytes+lane])
                        $fatal(1,"TENSOR_ASSERTION frame=%0d byte=%0d expected=%h observed=%h",
                               frame_id,write_bytes+lane,tensor[write_bytes+lane],wr_data[lane*8 +:8]);
                end else if (wr_data[lane*8 +:8] !== 0) $fatal(1,"INACTIVE_WRITE_LANE");
            end
            write_bytes=write_bytes+valid_bytes; last_write_cycle=cycles;
            write_streak=write_streak+1;
            if (write_streak>max_write_streak) max_write_streak=write_streak;
        end else write_streak=0;
    end
end
endtask
task automatic tick;
begin
    // Different deterministic schedules independently stall every public sink.
    m_axis_tready=(cycles%11>=2); m_crc_ready=(cycles%13>=3);
    m_meta_ready=(cycles%17>=4);
    wr_ready=(frame_id%2==0 || cycles%7>=2);
    ack_ready=(cycles%19>=5); rdma_evt_ready=(cycles%23>=6);
    coll_done_ready=(cycles%29>=7);
    @(posedge clk); cycles=cycles+1; observe();
    #1; @(negedge clk);
end
endtask
task automatic configure_qp;
input integer index;
input [23:0] qpn, remote, psn;
input [2:0] rank;
input enable;
integer progress;
begin
    qp_cfg_index=index; qp_cfg_local_qpn=qpn; qp_cfg_remote_qpn=remote;
    qp_cfg_expected_psn=psn; qp_cfg_rkey=32'habcdef01; qp_cfg_base=64'h1000;
    qp_cfg_length=64'h10000; qp_cfg_rank=rank; qp_cfg_enable=enable;
    qp_cfg_valid=1; qp_cfg_rsp_ready=0; progress=0;
    qp_fire=0;
    while (!qp_fire) begin
        tick(); progress=progress+1;
        if (progress>50) $fatal(1,"QP_CONFIG_PROGRESS");
    end
    qp_cfg_valid=0;
    while (qp_cfg_rsp_valid!==1) tick();
    repeat(3) begin
        if (qp_cfg_rsp_status !== 0) $fatal(1,"QP_CONFIG_ASSERTION");
        tick();
    end
    qp_cfg_rsp_ready=1; tick(); qp_cfg_rsp_ready=0;
    if (qp_cfg_rsp_valid !== 0) $fatal(1,"QP_CONFIG_RESPONSE_DUPLICATE");
end
endtask
task automatic configure_collective;
input enable;
input [1:0] fmt, op;
input [3:0] participants;
input [31:0] size;
input [15:0] job;
integer progress;
begin
    coll_cfg_enable=enable; coll_cfg_format=fmt; coll_cfg_op=op;
    coll_cfg_participants=participants; coll_cfg_bytes=size;
    coll_cfg_addr=64'h2003; coll_cfg_job=job; coll_cfg_valid=1;
    coll_cfg_rsp_ready=0; progress=0;
    coll_fire=0;
    while (!coll_fire) begin
        tick(); progress=progress+1;
        if (progress>50) $fatal(1,"COLL_CONFIG_PROGRESS");
    end
    coll_cfg_valid=0;
    while (coll_cfg_rsp_valid !== 1) tick();
    repeat(3) begin
        if (coll_cfg_rsp_status !== 0) $fatal(1,"COLL_CONFIG_ASSERTION observed=%0d",coll_cfg_rsp_status);
        tick();
    end
    coll_cfg_rsp_ready=1; tick(); coll_cfg_rsp_ready=0;
    if (coll_cfg_rsp_valid !== 0) $fatal(1,"COLL_CONFIG_RESPONSE_DUPLICATE");
end
endtask
task automatic run_frame;
input integer id, length, tensor_length;
input [4095:0] frame_path, tensor_path;
input [3:0] status;
input [23:0] qpn, psn, next_psn;
input [31:0] bytes;
input [63:0] addr, write_addr;
input has_ack;
input [127:0] ack;
input [23:0] ack_local, ack_remote, ack_sequence;
input has_done;
input [15:0] job;
input [31:0] done_bytes;
input [31:0] crc32;
input [63:0] crc64;
input [511:0] header;
input [31:0] rss;
input rss_valid;
integer offset, lane, progress;
begin
    active=1; frame_id=id; frame_length=length; write_length=tensor_length;
    out_bytes=0; write_bytes=0; crcs=0; metas=0; events=0; acks=0; dones=0;
    expected_status=status; expected_qpn=qpn; expected_psn=psn;
    expected_next=next_psn; expected_bytes=bytes; expected_addr=addr;
    expected_write_addr=write_addr; expected_ack=ack; want_ack=has_ack;
    expected_ack_local=ack_local; expected_ack_remote=ack_remote;
    expected_ack_psn=ack_sequence; want_done=has_done; expected_job=job;
    expected_done_bytes=done_bytes; expected_crc32=crc32; expected_crc64=crc64;
    expected_header=header; expected_rss=rss; expected_rss_valid=rss_valid;
    last_write_cycle=-1;
    $readmemh(frame_path,packet,0,length-1);
    if (tensor_length) $readmemh(tensor_path,tensor,0,tensor_length-1);
    s_check_enable=3; s_expected_crc32c=crc32; s_expected_crc64_nvme=crc64;
    offset=0; progress=0;
    while (offset<length) begin
        s_axis_tdata=0; s_axis_tkeep=0;
        for (lane=0;lane<B;lane=lane+1)
            if (offset+lane<length) begin
                s_axis_tdata[lane*8 +:8]=packet[offset+lane]; s_axis_tkeep[lane]=1;
            end
        s_axis_tlast=(offset+B>=length); s_axis_tvalid=1;
        tick(); progress=progress+1;
        if (input_fire) offset=offset+B;
        if (progress>30000) $fatal(1,"INGRESS_PROGRESS frame=%0d",id);
    end
    s_axis_tvalid=0;
    while (out_bytes!=length || crcs!=1 || metas!=1 || events!=1 ||
           acks!=has_ack || dones!=has_done || roce_idle!==1) begin
        tick(); progress=progress+1;
        if (progress>30000) $fatal(1,"FRAME_PROGRESS frame=%0d out=%0d write=%0d crc=%0d meta=%0d evt=%0d ack=%0d done=%0d",
                                  id,out_bytes,write_bytes,crcs,metas,events,acks,dones);
    end
    if (write_bytes!=tensor_length) $fatal(1,"WRITE_CONSERVATION");
    active=0; frames_compared=frames_compared+1;
    repeat(2) tick();
end
endtask
"""


def bench(folder, scenario):
    rel = folder
    calls = []
    manifest = []
    for step in scenario.steps:
        if step[0] == "qp":
            _, index, qp = step
            calls.append(" ".join(f"{x:x}" for x in
                                  (0, index, qp["qpn"], qp["remote"], qp["psn"],
                                   qp["rank"], int(qp["enable"]))))
        elif step[0] == "collective":
            job = step[1]
            calls.append(" ".join(f"{x:x}" for x in
                                  (1, 1, job["format"], job["op"], job["participants"],
                                   job["size"], job["job"])))
        elif step[0] == "disable_collective":
            calls.append("1 0 0 0 1 0 0")
        else:
            entry = step[1]
            index = len(manifest)
            frame_path = rel / f"packet-{index}.hex"
            tensor_path = rel / f"write-{index}.hex"
            frame_path.write_text("".join(f"{b:02x}\n" for b in entry["frame"]))
            tensor_path.write_text("".join(f"{b:02x}\n" for b in entry["writes"]))
            crc32 = crc_reflected(entry["frame"], 32, 0x82f63b78)
            crc64 = crc_reflected(entry["frame"], 64, 0x9a6c9329ac4bc9b5)
            header, rss, eligible = legacy_header(entry["frame"])
            ack = entry["ack"] or (0, 0, 0, 0)
            done = entry["done"] or (0, 0)
            values = (2, index, len(entry["frame"]), len(entry["writes"]),
                      frame_path.as_posix(), tensor_path.as_posix(), entry["status"],
                      entry["qpn"], entry["psn"], entry["expected"], entry["bytes"],
                      entry["addr"], entry["write_addr"], int(entry["ack"] is not None),
                      *ack, int(entry["done"] is not None), *done,
                      crc32, crc64, header, rss, int(eligible))
            calls.append(" ".join(x if isinstance(x, str) else f"{x:x}" for x in values))
            manifest.append({**{k: v for k, v in entry.items() if k not in ("frame", "writes")},
                             "frame_path": frame_path.as_posix(),
                             "tensor_path": tensor_path.as_posix(),
                             "frame_bytes": len(entry["frame"]),
                             "write_bytes": len(entry["writes"]),
                             "crc32c": crc32, "crc64_nvme": crc64,
                             "header": f"{header:0128x}", "rss": rss})
    (folder / "vectors.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (folder / "commands.txt").write_text("\n".join(calls) + "\n")
    all_outputs = "{" + ",".join(OUTPUTS) + "}"
    body = BODY.replace("RESET_BUNDLE", all_outputs).replace("OUTPUT_BUNDLE", all_outputs)
    body = body.replace("XZ_DIAGNOSTICS", "\n".join(
        f'if ((^{name}) === 1\'bx) $display("UNKNOWN_OUTPUT {name}=%h '
        f'axis=%b wr=%b crc=%b meta=%b", {name},m_axis_tvalid,wr_valid,m_crc_valid,m_meta_valid);'
        for name in OUTPUTS))
    return (
        "`timescale 1ns/1ps\nmodule integrated_tb;\nparameter W=64;\n"
        "parameter MP=9216, MS=16, Q=8;\nlocalparam B=W/8;\n" + declarations() +
        "\nbellows_n4_top #(.DATA_WIDTH(W),.MAX_PACKET_BYTES(MP),.MAX_SG(MS),.QPS(Q)) dut(.*);\n" +
        body + COMMANDS + "\ninitial begin\nrst_n=0; initial_reset_sample<=1;\n"
        "repeat(2) @(negedge clk);\nrst_n=1; roce_enable=1;\n"
        "ctl_ready=1; dma_cpl_ready=1;\nexecute_commands();\n"
        'if (frames_compared<1) $fatal(1,"FRAME_COVERAGE");\n'
        '$display("SUMMARY frames=%0d cycles=%0d max_write_burst=%0d stalls=%0d/%0d/%0d/%0d/%0d/%0d/%0d",'
        "frames_compared,cycles,max_write_streak,stalls_axis,stalls_crc,stalls_meta,"
        "stalls_write,stalls_evt,stalls_ack,stalls_done);\n$finish;\nend\nendmodule\n")


COMMANDS = r"""
task automatic execute_commands;
integer fd,n,kind,id,length,tensor_length;
reg [4095:0] path,frame_path,tensor_path;
reg [3:0] status;
reg [23:0] qpn,psn,next_psn,ack_local,ack_remote,ack_sequence;
reg [31:0] bytes,done_bytes,crc32,rss;
reg [63:0] addr,write_addr,crc64;
reg has_ack,has_done,rss_valid,enable;
reg [127:0] ack;
reg [15:0] job;
reg [511:0] header;
reg [1:0] fmt,op;
reg [3:0] participants;
reg [2:0] rank;
begin
    if (!$value$plusargs("commands=%s",path)) $fatal(1,"COMMAND_PATH_REQUIRED");
    fd=$fopen(path,"r");
    if (!fd) $fatal(1,"COMMAND_OPEN");
    while (!$feof(fd)) begin
        n=$fscanf(fd,"%h",kind);
        if (n!=1) begin
            if (!(n==0 && $feof(fd))) $fatal(1,"COMMAND_KIND_FORMAT");
        end else case(kind)
            0: begin
                n=$fscanf(fd,"%h %h %h %h %h %h\n",id,qpn,ack_remote,psn,rank,enable);
                if (n!=6) $fatal(1,"QP_COMMAND_FORMAT");
                configure_qp(id,qpn,ack_remote,psn,rank,enable);
            end
            1: begin
                n=$fscanf(fd,"%h %h %h %h %h %h\n",enable,fmt,op,participants,bytes,job);
                if (n!=6) $fatal(1,"COLLECTIVE_COMMAND_FORMAT");
                configure_collective(enable,fmt,op,participants,bytes,job);
            end
            2: begin
                n=$fscanf(fd,"%h %h %h %s %s %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                          id,length,tensor_length,frame_path,tensor_path,status,
                          qpn,psn,next_psn,bytes,addr,write_addr,has_ack,ack,
                          ack_local,ack_remote,ack_sequence,has_done,job,done_bytes,
                          crc32,crc64,header,rss,rss_valid);
                if (n!=25) $fatal(1,"FRAME_COMMAND_FORMAT n=%0d",n);
                run_frame(id,length,tensor_length,frame_path,tensor_path,status,
                          qpn,psn,next_psn,bytes,addr,write_addr,has_ack,ack,
                          ack_local,ack_remote,ack_sequence,has_done,job,done_bytes,
                          crc32,crc64,header,rss,rss_valid);
            end
            default: $fatal(1,"INVALID_COMMAND_KIND");
        endcase
    end
    $fclose(fd);
end
endtask
"""


def run(execution, *, width=64, seed=17, compact=False, simulator="verilator",
        stale_address=False):
    label = f"integrated-w{width}-seed{seed}-{simulator}"
    folder = execution.folder / label
    folder.mkdir(exist_ok=False)
    rel = folder.relative_to(execution.root)
    scenario = scenarios(width, seed, compact=compact, stale_address=stale_address)
    source = folder / "integrated_tb.sv"
    source.write_text(bench(rel, scenario))
    sources = [(rel / "integrated_tb.sv").as_posix(),
               *[p.relative_to(execution.root).as_posix()
                 for p in sorted((execution.root / "rtl").glob("*.sv"))]]
    if simulator == "iverilog":
        binary = rel / "integrated.vvp"
        compile_argv = ["iverilog", "-g2012", "-Wall", "-s", "integrated_tb",
                        f"-Pintegrated_tb.W={width}", "-o", binary.as_posix(), *sources]
        run_argv = ["vvp", binary.as_posix()]
    else:
        obj = rel / "integrated-obj"
        compile_argv = ["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
                        "--top-module", "integrated_tb", f"-GW={width}",
                        "--Mdir", obj.as_posix(), *sources]
        run_argv = [(obj / "Vintegrated_tb").as_posix()]
    code, _, err = execution.run(f"{label}-compile", compile_argv)
    if code:
        raise RuntimeError(f"integrated compile exit {code}: {err[-4000:]}")
    code, out, err = execution.run(f"{label}-behavior",
                                  [*run_argv, f"+commands={(rel / 'commands.txt').as_posix()}"],
                                  version_tool="vvp" if simulator == "iverilog" else "verilator")
    if code:
        raise AssertionError(f"integrated behavior exit {code}: {out[-4000:]} {err[-1000:]}")
    if f"SUMMARY frames={len(scenario.frames)} " not in out:
        raise AssertionError("integrated comparison coverage missing")
    return {"width": width, "seed": seed, "frames": len(scenario.frames),
            "measurement": out.strip()}
