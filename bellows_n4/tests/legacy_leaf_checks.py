"""Independent Toeplitz bit ordering and all-slot TCAM priority/configuration."""

import json
import random

from reference import DEFAULT_RSS_KEY, toeplitz


def rss_vectors(seed):
    rng = random.Random(seed)
    rows = []
    for bits in (0, 8, 104, 296):
        for enabled in (False, True):
            for _ in range(8):
                data = rng.randbytes(bits // 8)
                key = DEFAULT_RSS_KEY if len(rows) & 1 else rng.getrandbits(328)
                word = int.from_bytes(data, "big") << (296 - bits)
                eligible = enabled and bits != 0
                rows.append((word, bits, int(eligible), key,
                             toeplitz(data, key) if eligible else 0))
    return rows


def tcam_vectors(seed):
    rng = random.Random(seed)
    rules = [None] * 64
    rows = []
    results = []

    def configure(index, value, mask, action, enable=True):
        rules[index] = (value, mask, action) if enable else None
        rows.append((0, index, value, mask, action, int(enable), 0, 0, 0, 0, 0))

    def lookup(key, default):
        hits = [i for i, rule in enumerate(rules)
                if rule is not None and ((key ^ rule[0]) & rule[1]) == 0]
        index = min(hits) if hits else 0
        action = rules[index][2] if hits else default
        rows.append((2, 0, 0, 0, 0, 0, key, int(bool(hits)), index, action, default))
        results.append({"key": f"{key:0128x}", "hit": bool(hits),
                        "index": index, "action": action, "default": default})

    full_mask = (1 << 512) - 1
    keys = [rng.getrandbits(512) for _ in range(64)]
    for i, key in enumerate(keys):
        configure(i, key, full_mask, 0x9000 + i)
    for key in keys:
        lookup(key, 0xeeee)
    lookup(rng.getrandbits(512), 0xa55a)
    for i in range(64):
        configure(i, 0, 0, 0x6000 + i)
    lookup(rng.getrandbits(512), 0xeeee)
    for i in range(32):
        configure(i, 0, 0, 0, False)
    lookup(rng.getrandbits(512), 0xeeee)
    rows.append((1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    rules[:] = [None] * 64
    lookup(rng.getrandbits(512), 0xdeadbeef)
    # Match bits in every 64-bit chunk, not merely the first scanned chunk.
    for i in range(64):
        bit = (i * 73) & 511
        configure(i, 1 << bit, 1 << bit, 0x7000 + i)
    for _ in range(128):
        lookup(rng.getrandbits(512), 0x76543210)
    return rows, results


RSS_BENCH = r"""
`timescale 1ns/1ps
module rss_tb;
reg clk=0;
always #5 clk=~clk;
reg rst_n, in_valid=0, in_eligible=0;
reg [295:0] in_tuple=0;
reg [8:0] in_tuple_bits=0;
reg [327:0] in_key=0;
wire out_valid, out_eligible;
wire [31:0] out_hash;
furnace_rss_toeplitz dut(.*);
integer fd,n,cycles,count=0,reset_sample=0;
reg [31:0] expected;
reg [4095:0] path;
task automatic reset_outputs;
begin
    if ({out_valid,out_eligible,out_hash} !== 0) $fatal(1,"RSS_RESET");
end
endtask
always @(posedge clk) if (!rst_n) reset_outputs();
always @(negedge clk) if (!rst_n) reset_outputs();
always @(reset_sample) if (reset_sample) reset_outputs();
initial begin
    rst_n=0; reset_sample<=1;
    if (!$value$plusargs("vectors=%s",path)) $fatal(1,"RSS_VECTOR_PATH");
    fd=$fopen(path,"r"); if (!fd) $fatal(1,"RSS_VECTOR_OPEN");
    repeat(2) @(negedge clk); rst_n=1;
    while (!$feof(fd)) begin
        n=$fscanf(fd,"%h %h %h %h %h\n",in_tuple,in_tuple_bits,in_eligible,in_key,expected);
        if (n==5) begin
            in_valid=1; @(posedge clk); @(negedge clk); in_valid=0; cycles=0;
            while (out_valid !== 1 && cycles<400) begin @(negedge clk); cycles=cycles+1; end
            if (out_valid !== 1) $fatal(1,"RSS_PROGRESS");
            if ({out_hash,out_eligible} !== {expected,in_eligible})
                $fatal(1,"RSS_ASSERTION id=%0d expected=%h observed=%h",count,expected,out_hash);
            count=count+1;
            @(negedge clk);
            if (out_valid !== 0) $fatal(1,"RSS_DUPLICATE");
        end else if (!(n==0 && $feof(fd))) $fatal(1,"RSS_VECTOR_FORMAT");
    end
    $fclose(fd);
    if (count!=64) $fatal(1,"RSS_COVERAGE");
    $display("SUMMARY rss_compared=%0d",count); $finish;
end
endmodule
"""


TCAM_BENCH = r"""
`timescale 1ns/1ps
module tcam_tb;
reg clk=0;
always #5 clk=~clk;
reg rst_n,cfg_write=0,cfg_clear=0,cfg_enable=0,in_valid=0;
reg [5:0] cfg_index=0;
reg [511:0] cfg_value=0,cfg_mask=0,in_key=0;
reg [31:0] cfg_action=0,in_default_action=0;
wire out_valid,out_hit;
wire [5:0] out_index;
wire [31:0] out_action;
furnace_classifier64 dut(.*);
integer fd,n,kind,cycles,count=0,reset_sample=0;
reg hit;
reg [5:0] index;
reg [31:0] action;
reg [4095:0] path;
task automatic reset_outputs;
begin
    if ({out_valid,out_hit,out_index,out_action} !== 0) $fatal(1,"TCAM_RESET");
end
endtask
always @(posedge clk) if (!rst_n) reset_outputs();
always @(negedge clk) if (!rst_n) reset_outputs();
always @(reset_sample) if (reset_sample) reset_outputs();
initial begin
    rst_n=0; reset_sample<=1;
    if (!$value$plusargs("vectors=%s",path)) $fatal(1,"TCAM_VECTOR_PATH");
    fd=$fopen(path,"r"); if (!fd) $fatal(1,"TCAM_VECTOR_OPEN");
    repeat(2) @(negedge clk); rst_n=1;
    while (!$feof(fd)) begin
        n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h\n",kind,cfg_index,cfg_value,cfg_mask,
                  cfg_action,cfg_enable,in_key,hit,index,action,in_default_action);
        if (n==11) begin
            cfg_write=(kind==0); cfg_clear=(kind==1); in_valid=(kind==2);
            @(posedge clk); @(negedge clk);
            cfg_write=0; cfg_clear=0; in_valid=0;
            if (kind==2) begin
                cycles=0;
                while (out_valid !== 1 && cycles<800) begin @(negedge clk); cycles=cycles+1; end
                if (out_valid !== 1) $fatal(1,"TCAM_PROGRESS");
                if ({out_hit,out_index,out_action} !== {hit,index,action})
                    $fatal(1,"TCAM_ASSERTION id=%0d expected=%b/%0d/%h observed=%b/%0d/%h",
                           count,hit,index,action,out_hit,out_index,out_action);
                count=count+1;
                @(negedge clk);
                if (out_valid !== 0) $fatal(1,"TCAM_DUPLICATE");
            end
        end else if (!(n==0 && $feof(fd))) $fatal(1,"TCAM_VECTOR_FORMAT");
    end
    $fclose(fd);
    if (count!=196) $fatal(1,"TCAM_COVERAGE count=%0d",count);
    $display("SUMMARY tcam_compared=%0d",count); $finish;
end
endmodule
"""


def run(execution, *, seed=17, rtl_root="rtl", prefix="legacy-leaves"):
    folder = execution.folder / prefix
    folder.mkdir(exist_ok=False)
    rel = folder.relative_to(execution.root)
    rss = rss_vectors(seed)
    tcam, expected = tcam_vectors(seed)
    (folder / "rss.hex").write_text("".join(" ".join(f"{x:x}" for x in row) + "\n" for row in rss))
    (folder / "tcam.hex").write_text("".join(" ".join(f"{x:x}" for x in row) + "\n" for row in tcam))
    (folder / "vectors.json").write_text(json.dumps(
        {"seed": seed, "rss_comparisons": len(rss), "tcam": expected}, indent=2) + "\n")
    for name, bench, module, count in (
            ("rss", RSS_BENCH, "furnace_rss_toeplitz", len(rss)),
            ("tcam", TCAM_BENCH, "furnace_classifier64", len(expected))):
        source = folder / f"{name}_tb.sv"
        source.write_text(bench)
        obj = rel / f"{name}-obj"
        code, _, err = execution.run(
            f"{prefix}-{name}-compile",
            ["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
             "--top-module", f"{name}_tb", "--Mdir", obj.as_posix(),
             source.relative_to(execution.root).as_posix(), f"{rtl_root}/{module}.sv"])
        if code:
            raise RuntimeError(f"{name} compile exit {code}: {err[-3000:]}")
        code, out, err = execution.run(
            f"{prefix}-{name}-behavior",
            [(obj / f"V{name}_tb").as_posix(), f"+vectors={(rel / (name + '.hex')).as_posix()}"],
            version_tool="verilator")
        if code:
            raise AssertionError(f"{name} behavior exit {code}: {out[-3000:]} {err[-1000:]}")
        if f"SUMMARY {name}_compared={count}" not in out:
            raise AssertionError(f"{name} comparison coverage missing")
    return {"rss_compared": len(rss), "tcam_compared": len(expected),
            "all_tcam_slots": sorted({entry["index"] for entry in expected[:64] if entry["hit"]}),
            "seed": seed}
