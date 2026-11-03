"""Public leaf tests: abstract DRR service order and fixed-point token accounting."""

import json
import random


def grants():
    """Classical deficit-round-robin on eight permanently backlogged queues."""
    order = []
    for _ in range(4):
        for queue in range(8):
            order.extend([queue] * (queue + 1))
    return order


DRR_BENCH = r"""
`timescale 1ns/1ps
module drr_tb;
reg clk=0,rst_n;
always #5 clk=~clk;
reg decision_allow=1,cfg_commit=0,cfg_commit_enable=0;
reg [2:0] cfg_commit_queue=0;
reg [15:0] cfg_commit_quantum=0,cfg_commit_burst=0;
reg [31:0] cfg_commit_rate=0;
reg [7:0] q_enabled=255,q_pending=255,head_valid=255;
reg [255:0] head_seq=0,head_bytes=0;
reg [23:0] head_status=0;
reg [127:0] q_quantum=0;
reg [383:0] token_balance={384{1'b1}};
wire grant_valid,decision_busy,scheduler_idle;
wire [2:0] grant_queue;
wire [31:0] grant_seq,grant_bytes;
reg grant_ready=0,reserve_fire=0,refund_fire=0,retire_fire=0,retire_reserved=1;
reg [2:0] evt_queue=0;
reg [31:0] evt_seq=0,evt_bytes=0;
furnace_drr_scheduler dut(.*);
reg [4095:0] path;
integer fd,n,q,expected,count=0,progress,reset_sample=0;
reg [66:0] held;
task automatic tick;
begin @(posedge clk); #1; @(negedge clk); end
endtask
always @(posedge clk) if (!rst_n && {grant_valid,grant_queue,grant_seq,grant_bytes,
                                    decision_busy,scheduler_idle} !== 0)
    $fatal(1,"DRR_RESET");
always @(negedge clk) if (!rst_n && {grant_valid,grant_queue,grant_seq,grant_bytes,
                                    decision_busy,scheduler_idle} !== 0)
    $fatal(1,"DRR_RESET");
initial begin
    rst_n=0;
    if (!$value$plusargs("vectors=%s",path)) $fatal(1,"DRR_VECTOR_PATH");
    fd=$fopen(path,"r"); if (!fd) $fatal(1,"DRR_VECTOR_OPEN");
    for(q=0;q<8;q=q+1) begin
        head_bytes[q*32 +:32]=8; q_quantum[q*16 +:16]=(q+1)*8;
    end
    repeat(2) @(negedge clk); rst_n=1;
    while (!$feof(fd)) begin
        n=$fscanf(fd,"%d\n",expected);
        if (n==1) begin
            progress=0;
            while (grant_valid !== 1) begin
                tick(); progress=progress+1;
                if(progress>300) $fatal(1,"DRR_PROGRESS");
            end
            if ({grant_queue,grant_seq,grant_bytes} !==
                {3'(expected),head_seq[expected*32 +:32],32'd8})
                $fatal(1,"DRR_ASSERTION id=%0d expected_queue=%0d observed=%0d",count,expected,grant_queue);
            held={grant_queue,grant_seq,grant_bytes};
            repeat(3) begin
                tick();
                if(grant_valid !== 1 || {grant_queue,grant_seq,grant_bytes} !== held)
                    $fatal(1,"DRR_STABILITY");
            end
            evt_queue=grant_queue; evt_seq=grant_seq; evt_bytes=grant_bytes;
            reserve_fire=1; grant_ready=1; tick(); reserve_fire=0; grant_ready=0;
            if(grant_valid !== 0) $fatal(1,"DRR_GRANT_DUPLICATE");
            retire_fire=1; tick(); retire_fire=0;
            head_seq[expected*32 +:32]=head_seq[expected*32 +:32]+1;
            count=count+1;
        end else if (!(n==0 && $feof(fd))) $fatal(1,"DRR_VECTOR_FORMAT");
    end
    $fclose(fd);
    if(count!=144) $fatal(1,"DRR_COVERAGE");
    $display("SUMMARY drr_compared=%0d",count); $finish;
end
endmodule
"""


def token_vectors(seed=17):
    rng = random.Random(seed)
    balances = [0] * 8
    rates = [0] * 8
    capacities = [0] * 8
    enabled = [False] * 8
    reservation = None
    rows = []

    def step(cfg=0, queue=0, enable=0, rate=0, burst=0,
             reserve=0, refund=0, retire=0, seq=0, size=0):
        nonlocal reservation
        match = reservation is not None and reservation[:2] == (queue, seq)
        for q in range(8):
            if cfg and q == queue:
                enabled[q] = bool(enable)
                rates[q], capacities[q], balances[q] = rate, burst << 16, 0
            elif enabled[q]:
                credit = reservation[2] if refund and match and not reservation[3] and q == queue else 0
                balances[q] = min(capacities[q], balances[q] + rates[q] + credit)
                if reserve and q == queue:
                    if balances[q] < size << 16:
                        raise AssertionError("illegal token test debit")
                    balances[q] -= size << 16
        if cfg:
            reservation = None
        if reserve:
            reservation = (queue, seq, size << 16, False)
        if refund and match and reservation is not None and not reservation[3]:
            reservation = (*reservation[:3], True)
        if retire and match:
            reservation = None
        packed = sum(value << (q * 48) for q, value in enumerate(balances))
        rows.append((cfg, queue, enable, rate, burst, reserve, refund, retire, seq, size, packed))

    for q in range(8):
        step(cfg=1, queue=q, enable=1, rate=(q + 1) * 8192, burst=64 + q)
    for _ in range(100):
        step()
    for seq in range(40):
        q = seq & 7
        step(queue=q, reserve=1, seq=seq, size=8)
        # A mismatched refund must not add credit, and a matching refund is one-shot.
        step(queue=q, refund=1, seq=seq + 1)
        step(queue=q, refund=1, seq=seq)
        step(queue=q, refund=1, seq=seq)
        step(queue=q, retire=1, seq=seq)
        for _ in range(rng.randrange(1, 5)):
            step()
    step(cfg=1, queue=7, enable=0, rate=65536, burst=128)
    for _ in range(20):
        step()
    return rows


TOKEN_BENCH = r"""
`timescale 1ns/1ps
module token_tb;
reg clk=0,rst_n;
always #5 clk=~clk;
reg cfg_commit=0,cfg_commit_enable=0,reserve_fire=0,refund_fire=0,retire_fire=0;
reg retire_reserved=1;
reg [2:0] cfg_commit_queue=0,evt_queue=0;
reg [15:0] cfg_commit_quantum=1,cfg_commit_burst=0;
reg [31:0] cfg_commit_rate=0,evt_seq=0,evt_bytes=0;
wire [383:0] token_balance;
reg [383:0] expected;
furnace_token_bucket8 dut(.*);
integer fd,n,count=0;
reg [4095:0] path;
always @(posedge clk) if (!rst_n && token_balance !== 0) $fatal(1,"TOKEN_RESET");
always @(negedge clk) if (!rst_n && token_balance !== 0) $fatal(1,"TOKEN_RESET");
initial begin
    rst_n=0;
    if (!$value$plusargs("vectors=%s",path)) $fatal(1,"TOKEN_VECTOR_PATH");
    fd=$fopen(path,"r"); if(!fd) $fatal(1,"TOKEN_VECTOR_OPEN");
    repeat(2) @(negedge clk); rst_n=1;
    while(!$feof(fd)) begin
        n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h\n",
                  cfg_commit,cfg_commit_queue,cfg_commit_enable,cfg_commit_rate,
                  cfg_commit_burst,reserve_fire,refund_fire,retire_fire,evt_seq,evt_bytes,expected);
        evt_queue=cfg_commit_queue;
        if(n==11) begin
            @(posedge clk); #1;
            if(token_balance !== expected) $fatal(1,"TOKEN_ASSERTION id=%0d expected=%h observed=%h",
                                                  count,expected,token_balance);
            @(negedge clk); count=count+1;
        end else if (!(n==0 && $feof(fd))) $fatal(1,"TOKEN_VECTOR_FORMAT");
    end
    $fclose(fd);
    if(count<300) $fatal(1,"TOKEN_COVERAGE");
    $display("SUMMARY token_compared=%0d",count); $finish;
end
endmodule
"""


def run(execution, *, rtl_root="rtl", prefix="qos"):
    folder = execution.folder / prefix
    folder.mkdir(exist_ok=False)
    rel = folder.relative_to(execution.root)
    order = grants()
    tokens = token_vectors()
    (folder / "drr.hex").write_text("".join(f"{q}\n" for q in order))
    (folder / "token.hex").write_text("".join(
        " ".join(f"{value:x}" for value in row) + "\n" for row in tokens))
    (folder / "vectors.json").write_text(json.dumps(
        {"drr_grant_order": order, "token_compared": len(tokens)}, indent=2) + "\n")
    for name, bench, module, count in (
            ("drr", DRR_BENCH, "furnace_drr_scheduler", len(order)),
            ("token", TOKEN_BENCH, "furnace_token_bucket8", len(tokens))):
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
        if code or f"SUMMARY {name}_compared={count}" not in out:
            raise AssertionError(f"{name} behavior exit {code}: {out[-3000:]} {err[-1000:]}")
    return {"drr_grants": len(order), "queues": list(range(8)),
            "token_comparisons": len(tokens)}
