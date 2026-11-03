"""Public-pin parser checks with synchronous byte-memory stimulus."""

from pathlib import Path
import json

from reference import internet_checksum, roce_frame


def cases():
    payload = bytes.fromhex("0102030405060708")
    result = []
    for version in (4, 6):
        for tags in ((), (0x8100,), (0x88a8, 0x8100)):
            frame = roce_frame(payload, version=version, tags=tags)
            result.append((f"ipv{version}-tags{len(tags)}", frame, 0,
                           14 + 4 * len(tags) + (20 if version == 4 else 40) + 36))
    # NOP options are legal. Their raw one's-complement sum must be folded,
    # never truncated to the width of a single word plus two carry bits.
    for ihl in range(6, 16):
        frame = roce_frame(payload, options=b"\x01" * (4 * (ihl - 5)),
                           source=b"\xff\xfe\xff\xfe",
                           destination=b"\xff\xfe\xff\xfe")
        assert internet_checksum(frame[14:14 + ihl * 4]) == 0
        result.append((f"ipv4-ihl{ihl}-checksum-carries", frame, 0,
                       14 + ihl * 4 + 36))
    for ihl in (5, 15):
        for high_addresses in (False, True):
            addresses = ({"source": b"\xff\xfe\xff\xfe",
                          "destination": b"\xff\xfe\xff\xfe"}
                         if high_addresses else {})
            frame = roce_frame(payload, options=b"\x01" * (4 * (ihl - 5)),
                               **addresses)
            assert internet_checksum(frame[14:14 + ihl * 4]) == 0
            result.append((f"carry-isolation-ihl{ihl}-high{int(high_addresses)}",
                           frame, 0, 14 + ihl * 4 + 36))
    good = roce_frame(payload)
    bad = bytearray(good)
    bad[-5] ^= 1
    result.append(("bad-payload-icrc", bytes(bad), 9, 0))
    bad = bytearray(good)
    bad[-1] ^= 1
    result.append(("bad-icrc", bytes(bad), 9, 0))
    bad = bytearray(good)
    bad[24] ^= 1
    result.append(("bad-ipv4-checksum", bytes(bad), 3, 0))
    result.append(("truncated", good[:-1], 3, 0))
    result.append(("ethernet-padding", good + b"\0" * 20, 0, 70))
    return result


def bench(folder):
    tests = cases()
    vectors = []
    manifest = []
    for index, (name, frame, status, offset) in enumerate(tests):
        path = folder / f"frame-{index}.hex"
        path.write_text("\n".join(f"{b:02x}" for b in frame) + "\n")
        # Simulator paths are relative to the delivered root.
        vectors.append(
            f'run_case({index}, "{path.as_posix()}", {len(frame)}, '
            f'{status}, {offset}, "{name}");')
        entry = {"index": index, "name": name, "frame": path.as_posix(),
                 "expected_status": status, "expected_payload_start": offset}
        if "checksum-carries" in name or "carry-isolation" in name:
            header = frame[14:14 + (frame[14] & 15) * 4]
            entry.update(
                ipv4_checksum=internet_checksum(header),
                raw_checksum_sum=sum(int.from_bytes(header[i:i + 2], "big")
                                     for i in range(0, len(header), 2)))
        manifest.append(entry)
    (folder / "vectors.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return r"""
`timescale 1ns/1ps
module parser_tb;
reg clk=0;
always #5 clk=~clk;
reg rst_n;
reg initial_reset_sample=0;
reg start_valid=0, result_ready=0, frame_bad=0;
reg [13:0] frame_bytes=0;
wire start_ready, mem_req, result_valid, trusted;
wire [13:0] mem_addr, payload_start, payload_bytes;
reg [7:0] mem_data=0;
reg [7:0] memory [0:511];
wire [3:0] status;
wire [7:0] opcode;
wire [23:0] qpn, psn;
wire [63:0] address;
wire [31:0] rkey, message_bytes;
integer failures=0, comparisons=0;
furnace_roce_parser dut(.*);
always @(posedge clk) if (mem_req) mem_data <= memory[mem_addr];
task automatic reset_outputs;
begin
    if ({start_ready,mem_req,mem_addr,result_valid,status,trusted,opcode,qpn,
         psn,address,rkey,message_bytes,payload_start,payload_bytes} !== 0)
        $fatal(1,"RESET_X_OR_NONZERO");
end
endtask
always @(posedge clk) if (!rst_n) reset_outputs();
always @(negedge clk) if (!rst_n) reset_outputs();
always @(posedge initial_reset_sample) reset_outputs();
task automatic run_case;
input integer id;
input [4095:0] filename;
input integer length, expected_status, expected_start;
input [511:0] name;
integer cycles, stalls;
reg [216:0] held;
begin
    @(negedge clk);
    $readmemh(filename,memory,0,length-1);
    frame_bytes=length; start_valid=1;
    cycles=0;
    while (!start_ready && cycles<8) begin @(negedge clk); cycles=cycles+1; end
    if (start_ready !== 1) $fatal(1,"START_PROGRESS");
    @(posedge clk);
    @(negedge clk); start_valid=0;
    cycles=0;
    while (result_valid !== 1 && cycles<1100) begin
        @(negedge clk); cycles=cycles+1;
    end
    if (result_valid !== 1) $fatal(1,"RESULT_PROGRESS case=%0d",id);
    if ((^{status,trusted,opcode,qpn,psn,address,rkey,message_bytes,
           payload_start,payload_bytes}) === 1'bx)
        $fatal(1,"ACTIVE_XZ case=%0d",id);
    comparisons=comparisons+1;
    if (status !== expected_status[3:0]) begin
        failures=failures+1;
        $display("MISMATCH case=%0d name=%0s expected_status=%0d observed_status=%0d",
                 id,name,expected_status,status);
    end
    if (expected_status==0) begin
        if ({trusted,opcode,qpn,psn,address,rkey,message_bytes,payload_bytes}
            !== {1'b1,8'h0a,24'h123456,24'd17,64'h1003,32'habcdef01,
                 32'd8,14'd8} || payload_start !== expected_start[13:0]) begin
            failures=failures+1;
            $display("DECODE_MISMATCH case=%0d offset=%0d bytes=%0d",id,
                     payload_start,payload_bytes);
        end
    end else if (trusted !== 0 || payload_start !== 0 || payload_bytes !== 0)
        $fatal(1,"REJECTED_PAYLOAD case=%0d",id);
    held={status,trusted,opcode,qpn,psn,address,rkey,message_bytes,
          payload_start,payload_bytes};
    repeat(3) begin
        @(posedge clk);
        if (result_valid !== 1 ||
            {status,trusted,opcode,qpn,psn,address,rkey,message_bytes,
             payload_start,payload_bytes} !== held)
            $fatal(1,"RESULT_STABILITY case=%0d",id);
    end
    @(negedge clk); result_ready=1;
    @(posedge clk);
    @(negedge clk); result_ready=0;
    if (result_valid !== 0) $fatal(1,"RESULT_DUPLICATE case=%0d",id);
end
endtask
initial begin
    rst_n=0;
    initial_reset_sample<=1;
    repeat(2) @(negedge clk);
    rst_n=1;
""" + "\n".join(vectors) + r"""
    $display("SUMMARY comparisons=%0d failures=%0d",comparisons,failures);
    if (comparisons!=25) $fatal(1,"COVERAGE_COUNT");
    if (failures!=0) $fatal(1,"PROTOCOL_ASSERTION mismatches=%0d",failures);
    $finish;
end
endmodule
"""


def run(execution, *, simulator="iverilog"):
    folder = Path(execution.folder)
    relative_folder = folder.relative_to(execution.root)
    source = folder / "parser_tb.sv"
    source.write_text(bench(relative_folder))
    rtl = "rtl/furnace_roce_parser.sv"
    if simulator == "iverilog":
        binary = relative_folder / "parser.vvp"
        compile_argv = ["iverilog", "-g2012", "-Wall", "-s", "parser_tb",
                        "-o", binary.as_posix(), source.relative_to(execution.root).as_posix(), rtl]
        run_argv = ["vvp", binary.as_posix()]
    else:
        obj = relative_folder / "parser-obj"
        compile_argv = ["verilator", "--binary", "--timing", "-Wno-fatal",
                        "--top-module", "parser_tb", "--Mdir", obj.as_posix(),
                        source.relative_to(execution.root).as_posix(), rtl]
        run_argv = [(obj / "Vparser_tb").as_posix()]
    code, out, err = execution.run(f"{simulator}-parser-compile", compile_argv)
    if code:
        raise RuntimeError(f"parser compile exit {code}: {err[-2000:]}")
    code, out, err = execution.run(f"{simulator}-parser-behavior", run_argv,
                                  version_tool="vvp" if simulator == "iverilog" else "verilator")
    if code:
        raise AssertionError(f"parser behavior exit {code}: {out[-4000:]} {err[-1000:]}")
    if "SUMMARY comparisons=25 failures=0" not in out:
        raise AssertionError("parser comparison coverage missing")
    return {"parser_frames_compared": 25}
