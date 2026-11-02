"""Integer-oracle arithmetic, public transfer timing, stalls and throughput."""

import json
from pathlib import Path
import random

from reference import numerical


def directed(fmt):
    if fmt == 0:
        values = [0, 1, 0x7fff, 0x8000, 0xffff, 0x4000, 0xc000]
    else:
        f = 7 if fmt == 1 else 23
        sign = 1 << (f + 8)
        values = [0, sign, 1, sign | 1, (1 << f) - 1, 1 << f,
                  (1 << f) + 1, (127 << f), (127 << f) + 1,
                  (128 << f) - 1, (254 << f), (255 << f) - 1,
                  (255 << f), sign | (255 << f), (255 << f) | 1,
                  (255 << f) | (1 << (f - 1))]
        values += [sign | x for x in values if not x & sign]
    pairs = [(a, b) for a in values for b in values]
    if fmt:
        f = 7 if fmt == 1 else 23
        one = 127 << f
        half_ulp = (127 - f - 1) << f
        # Both ties, sticky below/above half, carries and deep cancellation.
        pairs += [(one + odd, half_ulp + delta)
                  for odd in (0, 1, 2, 3)
                  for delta in (-1, 0, 1)]
        pairs += [(one, (one - delta) | (1 << (f + 8)))
                  for delta in (1, 2, 3, 4, 7, 8)]
    return pairs


def vectors(path, width, seed, *, compact=False):
    rng = random.Random(seed)
    records = []
    coverage = []
    for fmt in range(3):
        element_bytes = 4 if fmt == 2 else 2
        lanes = width // (element_bytes * 8)
        for op in range(3):
            pairs = directed(fmt)
            if compact:
                pairs = pairs[:8] + pairs[-8:]
                random_count = 0
            else:
                random_count = 4096
                pairs += [(rng.getrandbits(element_bytes * 8),
                           rng.getrandbits(element_bytes * 8))
                          for _ in range(random_count)]
            for offset in range(0, len(pairs), lanes):
                a_word = b_word = expected = keep = 0
                group = pairs[offset:offset + lanes]
                for lane, (a, b) in enumerate(group):
                    shift = lane * element_bytes * 8
                    a_word |= a << shift
                    b_word |= b << shift
                    expected |= numerical(a, b, fmt, op) << shift
                    keep |= ((1 << element_bytes) - 1) << (lane * element_bytes)
                records.append((a_word, b_word, keep, fmt, op,
                                int(offset + lanes >= len(pairs)), expected, keep))
            coverage.append({"format": fmt, "op": op,
                             "random_active_lanes": random_count,
                             "directed_active_lanes": len(pairs) - random_count})
    # Irregular keeps must zero incomplete and inactive elements, not leak data.
    for fmt in range(3):
        size = 4 if fmt == 2 else 2
        for op in range(3):
            for _ in range(8):
                a = rng.getrandbits(width)
                b = rng.getrandbits(width)
                keep = rng.getrandbits(width // 8)
                effective = expected = 0
                for lane in range(width // (size * 8)):
                    mask = (1 << size) - 1
                    if (keep >> (lane * size)) & mask == mask:
                        effective |= mask << (lane * size)
                        bit = lane * size * 8
                        value_mask = (1 << (size * 8)) - 1
                        expected |= numerical((a >> bit) & value_mask,
                                              (b >> bit) & value_mask, fmt, op) << bit
                records.append((a, b, keep, fmt, op, 1, expected, effective))
    path.write_text("".join(" ".join(f"{x:x}" for x in row) + "\n"
                            for row in records))
    return {"width": width, "seed": seed, "beats": len(records),
            "numerical_combinations": coverage}


BENCH = r"""
`timescale 1ns/1ps
module alu_tb;
parameter W=64;
localparam B=W/8;
reg clk=0;
always #5 clk=~clk;
reg rst_n, in_valid=0, in_last=0, out_ready=0;
reg [W-1:0] in_a=0, in_b=0;
reg [B-1:0] in_keep=0;
reg [1:0] in_format=0, in_op=0;
wire in_ready, out_valid, out_last;
wire [W-1:0] out_data;
wire [B-1:0] out_keep;
furnace_reduce_alu #(.DATA_WIDTH(W)) dut(.*);
localparam LIMIT=30000;
reg [W-1:0] a[0:LIMIT-1], b[0:LIMIT-1], expected[0:LIMIT-1];
reg [B-1:0] keep[0:LIMIT-1], expected_keep[0:LIMIT-1];
reg [1:0] fmt[0:LIMIT-1], op[0:LIMIT-1];
reg last[0:LIMIT-1];
integer due[0:LIMIT-1];
integer count=0, head=0, tail=0, advances=0, cycles=0, compared=0;
integer fd, n, seed, sent=0, streak_in=0, streak_out=0, max_in=0, max_out=0;
integer random_state, reset_sample=0;
integer group_start=0, key_in=-1, key_out=-1, full_in=0, full_out=0, key, k;
integer max_full_in[0:8], max_full_out[0:8];
reg [4095:0] filename;
reg blocked=0;
reg [W+B:0] held;
task automatic reset_outputs;
begin
    if ({in_ready,out_valid,out_data,out_keep,out_last} !== 0)
        $fatal(1,"ALU_RESET_X_OR_NONZERO");
end
endtask
always @(posedge clk) if (!rst_n) reset_outputs();
always @(negedge clk) if (!rst_n) reset_outputs();
always @(reset_sample) if (reset_sample) reset_outputs();
task automatic observe;
reg expected_valid;
begin
    expected_valid=(head<tail && due[head]==advances);
    if (out_valid !== expected_valid)
        $fatal(1,"ALU_LATENCY cycle=%0d advances=%0d head=%0d expected_valid=%0d observed=%b",
               cycles,advances,head,expected_valid,out_valid);
    if (expected_valid) begin
        if ({out_data,out_keep,out_last} !==
            {expected[head],expected_keep[head],last[head]})
            $fatal(1,"NUMERICAL_ASSERTION id=%0d fmt=%0d op=%0d a=%h b=%h expected=%h observed=%h keep=%h",
                   head,fmt[head],op[head],a[head],b[head],expected[head],out_data,out_keep);
    end else if ({out_data,out_keep,out_last} !== 0)
        $fatal(1,"ALU_INACTIVE_DATA");
end
endtask
initial begin
    rst_n=0;
    reset_sample<=1;
    if (!$value$plusargs("vectors=%s",filename)) $fatal(1,"VECTORS_REQUIRED");
    if (!$value$plusargs("seed=%d",seed)) seed=17;
    random_state=seed;
    for (k=0;k<9;k=k+1) begin max_full_in[k]=0; max_full_out[k]=0; end
    fd=$fopen(filename,"r");
    if (!fd) $fatal(1,"VECTOR_OPEN");
    while (!$feof(fd)) begin
        if (count>=LIMIT) $fatal(1,"VECTOR_LIMIT");
        n=$fscanf(fd,"%h %h %h %h %h %h %h %h\n",
                  a[count],b[count],keep[count],fmt[count],op[count],last[count],
                  expected[count],expected_keep[count]);
        if (n==8) count=count+1;
        else if (!(n==0 && $feof(fd))) $fatal(1,"VECTOR_FORMAT n=%0d",n);
    end
    $fclose(fd);
    if (count<1) $fatal(1,"NO_COMPARISONS");
    repeat(2) @(negedge clk);
    rst_n=1;
    while (head<count) begin
        // The initial uninterrupted window measures input and output II=1.
        if (sent<count && (sent==0 || fmt[sent]!=fmt[sent-1] || op[sent]!=op[sent-1]))
            group_start=sent;
        out_ready=(sent-group_start<144 || (($random(random_state)&7)!=0));
        if (sent<count) begin
            in_valid=1; in_a=a[sent]; in_b=b[sent]; in_keep=keep[sent];
            in_format=fmt[sent]; in_op=op[sent]; in_last=last[sent];
        end else in_valid=0;
        @(posedge clk);
        cycles=cycles+1;
        if (cycles>count*8+100) $fatal(1,"ALU_PROGRESS");
        observe();
        if (in_ready !== (!out_valid || out_ready)) $fatal(1,"ALU_ADVANCE");
        if (blocked && {out_data,out_keep,out_last} !== held)
            $fatal(1,"ALU_STALL_STABILITY");
        blocked=out_valid && !out_ready;
        held={out_data,out_keep,out_last};
        if (out_valid && out_ready) begin
            key=fmt[head]*3+op[head];
            full_out=(key==key_out && (&out_keep)) ? full_out+1 :
                     (&out_keep) ? 1 : 0;
            key_out=key;
            if (full_out>max_full_out[key]) max_full_out[key]=full_out;
            head=head+1; compared=compared+1; streak_out=streak_out+1;
        end else begin streak_out=0; full_out=0; end
        if (streak_out>max_out) max_out=streak_out;
        if (in_ready) begin
            advances=advances+1;
            if (in_valid) begin
                key=in_format*3+in_op;
                full_in=(key==key_in && (&in_keep)) ? full_in+1 :
                        (&in_keep) ? 1 : 0;
                key_in=key;
                if (full_in>max_full_in[key]) max_full_in[key]=full_in;
                due[tail]=advances+7;
                tail=tail+1; sent=sent+1; streak_in=streak_in+1;
            end else begin streak_in=0; full_in=0; end
        end else begin streak_in=0; full_in=0; end
        if (streak_in>max_in) max_in=streak_in;
        #1;
        observe();
        @(negedge clk);
    end
    in_valid=0; out_ready=1;
    repeat(10) begin
        @(posedge clk); #1;
        if (out_valid !== 0) $fatal(1,"ALU_EXTRA_OUTPUT");
        @(negedge clk);
    end
    if (compared!=count || sent!=count) $fatal(1,"ALU_CONSERVATION");
    if (count>=256 && (max_in<128 || max_out<128)) $fatal(1,"ALU_LINE_RATE");
    if (count>=256) for (k=0;k<9;k=k+1) begin
        if (max_full_in[k]<128 || max_full_out[k]<128)
            $fatal(1,"ALU_COMBINATION_LINE_RATE combination=%0d input=%0d output=%0d",
                   k,max_full_in[k],max_full_out[k]);
        $display("THROUGHPUT combination=%0d full_input_burst=%0d full_output_burst=%0d",
                 k,max_full_in[k],max_full_out[k]);
    end
    $display("SUMMARY beats=%0d compared=%0d cycles=%0d max_input_burst=%0d max_output_burst=%0d",
             count,compared,cycles,max_in,max_out);
    $finish;
end
endmodule
"""


def compile_bench(execution, width, *, simulator="verilator", rtl_root="rtl",
                  label=None):
    label = label or f"alu-w{width}-{simulator}"
    folder = execution.folder / label
    folder.mkdir(exist_ok=False)
    rel = folder.relative_to(execution.root)
    source = folder / "alu_tb.sv"
    source.write_text(BENCH)
    sources = [(rel / "alu_tb.sv").as_posix(),
               f"{rtl_root}/furnace_reduce_alu.sv",
               f"{rtl_root}/furnace_reduce_lane.sv"]
    if simulator == "iverilog":
        binary = rel / "alu.vvp"
        argv = ["iverilog", "-g2012", "-Wall", "-s", "alu_tb",
                f"-Palu_tb.W={width}", "-o", binary.as_posix(), *sources]
        run_argv = ["vvp", binary.as_posix()]
    else:
        obj = rel / "alu-obj"
        argv = ["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
                "--top-module", "alu_tb", f"-GW={width}",
                "--Mdir", obj.as_posix(), *sources]
        run_argv = [(obj / "Valu_tb").as_posix()]
    code, _, err = execution.run(f"{label}-compile", argv)
    if code:
        raise RuntimeError(f"{label} compile exit {code}: {err[-3000:]}")
    return folder, run_argv


def run(execution, *, widths=(64, 512), seeds=(17, 89, 203),
        simulator="verilator", compact=False):
    coverage = []
    for width in widths:
        folder, argv = compile_bench(execution, width, simulator=simulator)
        for seed in seeds:
            path = folder / f"vectors-{seed}.hex"
            entry = vectors(path, width, seed, compact=compact)
            (folder / f"vectors-{seed}.json").write_text(json.dumps(entry, indent=2) + "\n")
            code, out, err = execution.run(
                f"alu-w{width}-{simulator}-seed{seed}",
                [*argv, f"+vectors={path.relative_to(execution.root).as_posix()}",
                 f"+seed={seed}"], version_tool=simulator if simulator == "verilator" else "vvp")
            if code:
                raise AssertionError(f"ALU behavior exit {code}: {out[-3000:]} {err[-1000:]}")
            if f"SUMMARY beats={entry['beats']} compared={entry['beats']}" not in out:
                raise AssertionError("ALU comparison coverage missing")
            entry["measurement"] = out.strip()
            coverage.append(entry)
    return {"alu_runs": coverage}
