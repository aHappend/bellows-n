"""Top-level configuration atomicity and public reset-boundary comparisons."""

import integrated_checks


CONTROL_BODY = r"""
task automatic qp_attempt;
input [2:0] index,rank;
input enable;
input [23:0] qpn;
input [63:0] base,length;
input [2:0] status;
integer progress;
begin
    qp_cfg_index=index; qp_cfg_rank=rank; qp_cfg_enable=enable;
    qp_cfg_local_qpn=qpn; qp_cfg_remote_qpn=24'h340000;
    qp_cfg_expected_psn=17; qp_cfg_rkey=32'habcdef01;
    qp_cfg_base=base; qp_cfg_length=length;
    qp_cfg_valid=1; qp_cfg_rsp_ready=0; qp_fire=0; progress=0;
    while(!qp_fire) begin
        tick(); progress=progress+1;
        if(progress>100) $fatal(1,"QP_ATTEMPT_PROGRESS");
    end
    qp_cfg_valid=0;
    repeat(4) begin
        if(qp_cfg_rsp_valid !== 1 || qp_cfg_rsp_status !== status ||
           qp_cfg_ready !== 0 || coll_cfg_ready !== 0)
            $fatal(1,"QP_ATOMIC_RESPONSE expected=%0d observed=%0d",status,qp_cfg_rsp_status);
        tick();
    end
    qp_cfg_rsp_ready=1; tick(); qp_cfg_rsp_ready=0;
end
endtask

task automatic coll_attempt;
input [1:0] fmt,op;
input [3:0] participants;
input [31:0] size;
input [63:0] address;
input [2:0] status;
integer progress;
begin
    coll_cfg_enable=1; coll_cfg_format=fmt; coll_cfg_op=op;
    coll_cfg_participants=participants; coll_cfg_bytes=size;
    coll_cfg_addr=address; coll_cfg_job=77;
    coll_cfg_valid=1; coll_cfg_rsp_ready=0; coll_fire=0; progress=0;
    while(!coll_fire) begin
        tick(); progress=progress+1;
        if(progress>100) $fatal(1,"COLL_ATTEMPT_PROGRESS");
    end
    coll_cfg_valid=0;
    repeat(4) begin
        if(coll_cfg_rsp_valid !== 1 || coll_cfg_rsp_status !== status ||
           qp_cfg_ready !== 0 || coll_cfg_ready !== 0)
            $fatal(1,"COLL_ATOMIC_RESPONSE expected=%0d observed=%0d",status,coll_cfg_rsp_status);
        tick();
    end
    coll_cfg_rsp_ready=1; tick(); coll_cfg_rsp_ready=0;
end
endtask

task automatic config_cases;
begin
    qp_attempt(1,1,1,24'h120000,64'h1000,64'h10000,1);
    qp_attempt(3,3,1,24'h120300,64'h1000,64'h10000,1);
    qp_attempt(0,0,1,24'h120000,64'h1000,0,2);
    qp_attempt(0,0,1,24'h120000,64'hfffffffffffffffe,4,2);
    coll_attempt(3,0,1,4,64'h2003,3);
    coll_attempt(0,3,1,4,64'h2003,3);
    coll_attempt(0,0,0,4,64'h2003,3);
    coll_attempt(0,0,9,4,64'h2003,3);
    coll_attempt(0,0,1,0,64'h2003,3);
    coll_attempt(0,0,1,3,64'h2003,3);
    coll_attempt(2,0,1,6,64'h2003,3);
    coll_attempt(0,0,1,4,64'hfff,2);
    coll_attempt(0,0,1,4,64'hfffffffffffffffe,2);
    coll_attempt(0,0,2,4,64'h2003,3);
    qp_attempt(1,0,1,24'h120100,64'h1000,64'h10000,0);
    coll_attempt(0,0,2,4,64'h2003,3);
    qp_attempt(1,1,0,24'h120100,64'h1000,64'h10000,0);
    // Simultaneous requests: QP acceptance precedes collective acceptance.
    qp_cfg_valid=1; coll_cfg_valid=1; qp_cfg_index=0; qp_cfg_enable=1;
    qp_cfg_rank=0; qp_cfg_local_qpn=24'h120000; qp_cfg_base=64'h1000;
    qp_cfg_length=64'h10000; coll_cfg_format=3; coll_cfg_participants=1;
    coll_cfg_bytes=4; coll_cfg_addr=64'h2003;
    qp_cfg_rsp_ready=0; coll_cfg_rsp_ready=0; qp_fire=0; coll_fire=0;
    tick();
    if(!qp_fire || coll_fire) $fatal(1,"CONFIG_QP_PRIORITY");
    qp_cfg_valid=0;
    repeat(3) begin
        tick();
        if(coll_fire || !qp_cfg_rsp_valid || qp_cfg_rsp_status !== 0)
            $fatal(1,"CONFIG_PRIORITY_RESPONSE");
    end
    qp_cfg_rsp_ready=1; tick(); qp_cfg_rsp_ready=0;
    coll_fire=0;
    while(!coll_fire) tick();
    coll_cfg_valid=0;
    if(coll_cfg_rsp_status !== 3) $fatal(1,"CONFIG_COLLECTIVE_PRIORITY_RESULT");
    coll_cfg_rsp_ready=1; tick(); coll_cfg_rsp_ready=0;
end
endtask

task automatic reset_epoch;
begin
    #1; rst_n=0;
    #1; reset_outputs();
    repeat(2) @(negedge clk);
    active=0; s_axis_tvalid=0; qp_cfg_valid=0; coll_cfg_valid=0;
    block_axis=0; block_crc=0; block_meta=0; block_write=0;
    block_evt=0; block_ack=0; block_done=0;
    rst_n=1; repeat(3) tick();
    if(roce_idle !== 1) $fatal(1,"RESET_EPOCH_IDLE");
end
endtask
"""


def run(execution, *, width=64):
    label = f"control-w{width}"
    folder = execution.folder / label
    folder.mkdir(exist_ok=False)
    rel = folder.relative_to(execution.root)
    scenario = integrated_checks.Scenario(width, 17)
    scenario.qp(0)
    scenario.packet("failed-config-preserves-QP", 0, b"configuration")
    scenario.packet("disabled-QP-after-config", 0, b"x",
                    unknown_qpn=0x120100, force_status=5)
    scenario.qp(0)
    scenario.packet("reconfigured-expected-PSN", 0, b"reset")
    source_text = integrated_checks.bench(rel, scenario)
    commands = folder / "commands.txt"
    lines = commands.read_text().splitlines()
    lines.insert(1, "4")
    commands.write_text("\n".join(lines) + "\n")
    source_text = source_text.replace("task automatic tick;", CONTROL_BODY + "\ntask automatic tick;")
    source_text = source_text.replace(
        'default: $fatal(1,"INVALID_COMMAND_KIND");',
        '4: config_cases();\n            default: $fatal(1,"INVALID_COMMAND_KIND");')
    source_text = source_text.replace("execute_commands();", "execute_commands();\nreset_epoch();")
    source = folder / "integrated_tb.sv"
    source.write_text(source_text)
    obj = rel / "control-obj"
    sources = [source.relative_to(execution.root).as_posix(),
               *[p.relative_to(execution.root).as_posix()
                 for p in sorted((execution.root / "rtl").glob("*.sv"))]]
    code, _, err = execution.run(
        label + "-compile",
        ["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
         "--top-module", "integrated_tb", f"-GW={width}", "-GQ=3",
         "-GMP=257", "-GMS=3", "--Mdir", obj.as_posix(), *sources])
    if code:
        raise RuntimeError(f"control compile exit {code}: {err[-4000:]}")
    code, out, err = execution.run(
        label + "-behavior",
        [(obj / "Vintegrated_tb").as_posix(), f"+commands={(rel / 'commands.txt').as_posix()}"],
        version_tool="verilator")
    if code or "SUMMARY frames=3 " not in out:
        raise AssertionError(f"control behavior exit {code}: {out[-4000:]} {err[-1000:]}")
    return {"width": width, "failed_configurations": 15,
            "simultaneous_QP_collective_priority": True, "reset_epochs": 2,
            "frames_compared": 3, "measurement": out.strip()}
