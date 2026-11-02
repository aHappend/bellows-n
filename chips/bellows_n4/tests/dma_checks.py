"""Independent descriptor/SG byte memory driving real DMA-to-RoCE top traffic."""

import integrated_checks


DMA_BODY = r"""
reg [7:0] dma_configured=0;
integer producer_seq[0:7];
integer memory_length=0,memory_cursor=0,request_count=0,completion_count=0;
integer segment_count=1,segment_size=0,segment_remainder=0,queue_id=0;
integer memory_fault=0,error_cookie=0,error_status=0;
reg memory_active=0,dma_fire=0,memory_fire=0,completion_fire=0;
reg queue_fire=0,doorbell_fire=0;
reg [63:0] memory_address=0;
reg [7:0] descriptor[0:31],scatter[0:255];
reg [31:0] work_cookie;
reg [95:0] held_completion;
reg completion_blocked=0;

function automatic [7:0] memory_byte;
input [63:0] address;
begin
    if (address>=64'h20000 && address<64'h30000)
        memory_byte=descriptor[(address-64'h20000)&31];
    else if (address>=64'h40000 && address<64'h40100)
        memory_byte=scatter[address-64'h40000];
    else if (address>=64'h50003 && address<64'h50003+frame_length)
        memory_byte=packet[address-64'h50003];
    else begin memory_byte=0; $fatal(1,"DMA_MEMORY_ADDRESS %h",address); end
end
endfunction

task automatic memory_drive;
integer lane;
begin
    dma_rd_ready=(cycles%7>=2); dma_cpl_ready=(cycles%11>=3);
    dma_rsp_valid=memory_active; dma_rsp_data=0; dma_rsp_keep=0;
    dma_rsp_last=(memory_cursor+B>=memory_length);
    dma_rsp_error=(memory_fault==3 && request_count==1);
    for(lane=0;lane<B;lane=lane+1)
        if(memory_active && memory_cursor+lane<memory_length) begin
            dma_rsp_data[lane*8 +:8]=memory_byte(memory_address+memory_cursor+lane);
            dma_rsp_keep[lane]=1;
        end
    if(memory_fault==4 && request_count==1 && memory_cursor==0)
        dma_rsp_keep[0]=0;
end
endtask

task automatic memory_observe;
integer index,length,offset;
reg [63:0] address;
begin
    dma_fire=dma_rd_valid && dma_rd_ready;
    memory_fire=dma_rsp_valid && dma_rsp_ready;
    completion_fire=dma_cpl_valid && dma_cpl_ready;
    queue_fire=q_cfg_valid && q_cfg_ready;
    doorbell_fire=db_valid && db_ready;
    if (completion_blocked && (!dma_cpl_valid ||
        {dma_cpl_queue,dma_cpl_cookie,dma_cpl_status,dma_cpl_bytes} !== held_completion))
        $fatal(1,"DMA_COMPLETION_STABILITY");
    completion_blocked=dma_cpl_valid && !dma_cpl_ready;
    held_completion={dma_cpl_queue,dma_cpl_cookie,dma_cpl_status,dma_cpl_bytes};
    if(dma_cpl_valid) begin
        if ({dma_cpl_queue,dma_cpl_cookie,dma_cpl_status,dma_cpl_bytes} !==
            {3'(queue_id),32'(error_cookie ? 0 : work_cookie),
             3'(error_status),32'(error_status ? 0 : frame_length)})
            $fatal(1,"DMA_COMPLETION_ASSERTION expected=%0d/%h/%0d/%0d observed=%0d/%h/%0d/%0d",
                   queue_id,work_cookie,error_status,error_status?0:frame_length,
                   dma_cpl_queue,dma_cpl_cookie,dma_cpl_status,dma_cpl_bytes);
        if(!error_status && (out_bytes!=frame_length || crcs!=1 || metas!=1))
            $fatal(1,"DMA_COMPLETION_BEFORE_LEGACY_OUTPUT");
        if(completion_fire) begin
            if(completion_count) $fatal(1,"DMA_COMPLETION_DUPLICATE");
            completion_count=completion_count+1;
            producer_seq[queue_id]=producer_seq[queue_id]+1;
        end
    end
    if(dma_fire) begin
        if(memory_active) $fatal(1,"DMA_OVERLAPPING_READ");
        if(request_count==0) begin
            address=64'h20000+queue_id*4096+
                    (producer_seq[queue_id]%((queue_id%3==0)?3:(queue_id%3==1)?1:256))*32;
            length=32;
        end else if(request_count<=segment_count) begin
            address=64'h40000+(request_count-1)*16; length=16;
        end else begin
            index=request_count-segment_count-1;
            if(index>=segment_count) $fatal(1,"DMA_EXCESS_READ");
            offset=index*segment_size+((index<segment_remainder)?index:segment_remainder);
            address=64'h50003+offset; length=segment_size+(index<segment_remainder);
        end
        if({dma_rd_addr,dma_rd_len} !== {address,16'(length)})
            $fatal(1,"DMA_REQUEST_ASSERTION request=%0d expected=%h/%0d observed=%h/%0d",
                   request_count,address,length,dma_rd_addr,dma_rd_len);
        memory_address=address; memory_length=length; memory_cursor=0;
        memory_active=1; request_count=request_count+1;
    end else if(memory_fire) begin
        if(dma_rsp_last) memory_active=0;
        else memory_cursor=memory_cursor+B;
    end
end
endtask

task automatic dma_control_response;
integer progress;
begin
    progress=0; ctl_ready=0;
    while(ctl_valid!==1) begin
        tick(); progress=progress+1;
        if(progress>100) $fatal(1,"DMA_CONTROL_PROGRESS");
    end
    repeat(3) begin
        if({ctl_queue,ctl_code} !== {3'(queue_id),3'b0})
            $fatal(1,"DMA_CONTROL_ASSERTION");
        tick();
    end
    ctl_ready=1; tick(); ctl_ready=0;
end
endtask

task automatic prepare_dma;
input integer length;
integer i,j,offset,size,progress;
reg [63:0] address;
reg [255:0] encoded_descriptor;
reg [127:0] encoded_scatter;
begin
    dma_enable=1; queue_id=frame_id%8;
    segment_count=(frame_id%3==0)?1:(frame_id%3==1)?3:16;
    frame_length=length;
    segment_size=length/segment_count; segment_remainder=length%segment_count;
    request_count=0; completion_count=0;
    memory_active=0; completion_blocked=0;
    work_cookie=32'h12340000+frame_id;
    encoded_descriptor={96'b0,work_cookie,24'b0,8'(memory_fault==1 ? 0 : segment_count),
                        32'(length),64'h40000};
    for(i=0;i<32;i=i+1) descriptor[i]=encoded_descriptor[i*8 +:8];
    for(i=0;i<segment_count;i=i+1) begin
        offset=i*segment_size+((i<segment_remainder)?i:segment_remainder);
        size=segment_size+(i<segment_remainder);
        encoded_scatter={32'b0,32'(memory_fault==2 && i==0 ? 0 : size),64'(64'h50003+offset)};
        for(j=0;j<16;j=j+1) scatter[i*16+j]=encoded_scatter[j*8 +:8];
    end
    if(!dma_configured[queue_id]) begin
        q_cfg_id=queue_id; q_cfg_enable=1;
        q_cfg_ring_base=64'h20000+queue_id*4096;
        q_cfg_ring_entries=(queue_id%3==0)?3:(queue_id%3==1)?1:256;
        q_cfg_quantum=32*(queue_id+1); q_cfg_rate=32'h1000000; q_cfg_burst=1024;
        q_cfg_valid=1; ctl_ready=0; progress=0; queue_fire=0;
        while(!queue_fire) begin
            tick(); progress=progress+1;
            if(progress>200) $fatal(1,"DMA_QUEUE_CONFIG_PROGRESS");
        end
        q_cfg_valid=0; dma_control_response();
        dma_configured[queue_id]=1;
    end
    db_queue=queue_id; db_producer=producer_seq[queue_id]+1; db_valid=1; progress=0;
    doorbell_fire=0;
    while(!doorbell_fire) begin
        tick(); progress=progress+1;
        if(progress>200) $fatal(1,"DMA_DOORBELL_PROGRESS");
    end
    db_valid=0; dma_control_response();
end
endtask

task automatic dma_error;
input integer fault;
integer progress,i;
begin
    frame_id=40+fault; memory_fault=fault; error_status=fault;
    error_cookie=(fault==4);
    active=0; frame_length=120;
    for(i=0;i<frame_length;i=i+1) packet[i]=i;
    prepare_dma(frame_length);
    progress=0;
    while(completion_count!=1 || dma_idle!==1 || roce_idle!==1) begin
        tick(); progress=progress+1;
        if(progress>20000) $fatal(1,"DMA_ERROR_PROGRESS fault=%0d",fault);
    end
    if(memory_active || m_axis_tvalid || wr_valid || rdma_evt_valid)
        $fatal(1,"DMA_ERROR_SIDE_EFFECT");
    memory_fault=0; error_status=0; error_cookie=0;
end
endtask
"""


def run(execution, *, width=64):
    label = f"dma-w{width}"
    folder = execution.folder / label
    folder.mkdir(exist_ok=False)
    rel = folder.relative_to(execution.root)
    scenario = integrated_checks.Scenario(width, 17)
    for q in range(8):
        scenario.qp(q)
    for frame in range(32):
        scenario.packet(f"dma-q{frame % 8}-frame{frame}", frame % 8,
                        scenario.rng.randbytes(67 + frame % 7))
    source_text = integrated_checks.bench(rel, scenario)
    source_text = source_text.replace(
        "task automatic tick;", DMA_BODY + "\ntask automatic tick;")
    source_text = source_text.replace(
        "@(posedge clk); cycles=cycles+1; observe();",
        "memory_drive(); @(posedge clk); cycles=cycles+1; observe(); memory_observe();")
    source_text = source_text.replace(
        "offset=0; progress=0;",
        "prepare_dma(length); offset=length; progress=0;")
    source_text = source_text.replace(
        "if (write_bytes!=tensor_length)",
        'if(request_count!=1+2*segment_count || completion_count!=1) '
        '$fatal(1,"DMA_READ_COMPLETION_CONSERVATION");\n    if (write_bytes!=tensor_length)')
    source_text = source_text.replace(
        "ctl_ready=1; dma_cpl_ready=1;",
        "ctl_ready=0; dma_cpl_ready=1;\n"
        "for(integer q=0;q<8;q=q+1) producer_seq[q]=0;")
    source_text = source_text.replace(
        "execute_commands();",
        "execute_commands();\ndma_error(1); dma_error(2); dma_error(3); dma_error(4);")
    source = folder / "integrated_tb.sv"
    source.write_text(source_text)
    obj = rel / "dma-obj"
    sources = [source.relative_to(execution.root).as_posix(),
               *[p.relative_to(execution.root).as_posix()
                 for p in sorted((execution.root / "rtl").glob("*.sv"))]]
    code, _, err = execution.run(
        label + "-compile",
        ["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
         "--top-module", "integrated_tb", f"-GW={width}", "--Mdir", obj.as_posix(), *sources])
    if code:
        raise RuntimeError(f"DMA compile exit {code}: {err[-4000:]}")
    code, out, err = execution.run(
        label + "-behavior",
        [(obj / "Vintegrated_tb").as_posix(), f"+commands={(rel / 'commands.txt').as_posix()}"],
        version_tool="verilator")
    if code or "SUMMARY frames=32 " not in out:
        raise AssertionError(f"DMA behavior exit {code}: {out[-4000:]} {err[-1000:]}")
    return {"width": width, "dma_roce_frames": 32, "queues": list(range(8)),
            "ring_entries": [1, 3, 256], "scatter_counts": [1, 3, 16],
            "completion_errors": [1, 2, 3, 4], "measurement": out.strip()}
