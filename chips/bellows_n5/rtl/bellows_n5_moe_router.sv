`default_nettype none
module bellows_n5_moe_router #(
    parameter integer DATA_WIDTH=512, QPS=8, EXPERTS=8, MAX_K=4,
    parameter integer TOKENS=4, MAX_TOKEN_ELEMS=256
) (
    input wire clk, rst_n, idle_allow,
    input wire [7:0] qp_enabled,
    input wire [191:0] local_qpns, remote_qpns,
    input wire x5_expert_cfg_valid,
    output wire x5_expert_cfg_ready,
    input wire [15:0] x5_expert_cfg_id,
    input wire x5_expert_cfg_enable,
    input wire [2:0] x5_expert_cfg_qp,
    output wire x5_expert_cfg_rsp_valid,
    input wire x5_expert_cfg_rsp_ready,
    output wire [1:0] x5_expert_cfg_rsp_status,
    output reg [7:0] route_qps,
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
    input wire rx_cmd_valid,
    output wire rx_cmd_ready,
    input wire [2:0] rx_cmd_qp,
    input wire [511:0] rx_cmd_meta,
    input wire rx_payload_tvalid,
    output wire rx_payload_tready,
    input wire [DATA_WIDTH-1:0] rx_payload_tdata,
    input wire [(DATA_WIDTH>>3)-1:0] rx_payload_tkeep,
    input wire rx_payload_tlast,
    output wire rx_done_valid,
    input wire rx_done_ready,
    output wire rx_done_ok,
    output wire dispatch_cmd_valid,
    input wire dispatch_cmd_ready,
    output wire [2:0] dispatch_cmd_qp,
    output wire [511:0] dispatch_cmd_meta,
    output wire dispatch_payload_tvalid,
    input wire dispatch_payload_tready,
    output wire [DATA_WIDTH-1:0] dispatch_payload_tdata,
    output wire [(DATA_WIDTH>>3)-1:0] dispatch_payload_tkeep,
    output wire dispatch_payload_tlast,
    input wire dispatch_done,
    output wire return_cmd_valid,
    input wire return_cmd_ready,
    output wire [2:0] return_cmd_qp,
    output wire [511:0] return_cmd_meta,
    output wire return_payload_tvalid,
    input wire return_payload_tready,
    output wire [DATA_WIDTH-1:0] return_payload_tdata,
    output wire [(DATA_WIDTH>>3)-1:0] return_payload_tkeep,
    output wire return_payload_tlast,
    input wire return_done,
    output wire evt_valid,
    input wire evt_ready,
    output wire [3:0] evt_status,
    output wire [2:0] evt_qp,
    output wire [31:0] evt_token_id,
    output wire [23:0] evt_psn,
    output wire idle
);
    localparam integer B=DATA_WIDTH>>3, SHIFT=(DATA_WIDTH==512)?6:3;
    localparam integer JOBS=TOKENS*MAX_K;
    reg [EXPERTS-1:0] routes;
    reg [2:0] route_qp [0:EXPERTS-1];
    reg cfg_pending;
    reg [1:0] cfg_status;
    reg [TOKENS-1:0] active, activation_ready, dispatched, combining, completed;
    reg [31:0] token_id [0:TOKENS-1];
    reg [8:0] elems [0:TOKENS-1];
    reg [2:0] count_k [0:TOKENS-1];
    reg formats [0:TOKENS-1];
    reg [16*MAX_K-1:0] ids [0:TOKENS-1], weights [0:TOKENS-1];
    reg [3*MAX_K-1:0] destinations [0:TOKENS-1];
    reg [2*MAX_K-1:0] returned [0:TOKENS-1];
    reg [3:0] completion_status [0:TOKENS-1];
    reg [JOBS-1:0] job_active, job_presented, job_response;
    reg [511:0] job_meta [0:JOBS-1];
    reg [2:0] job_qp [0:JOBS-1];
    reg [1:0] job_fragments [0:JOBS-1];

    reg free_found, duplicate_id;
    reg [2:0] free_slot;
    reg [4:0] enabled_count;
    integer i, j;
    always @* begin
        free_found=0; free_slot=0; duplicate_id=0; enabled_count=0; route_qps=0;
        for (i=0;i<TOKENS;i=i+1) begin
            if (!active[i] && !free_found) begin free_found=1; free_slot=i; end
            if (active[i] && token_id[i]==x5_moe_cmd_token_id) duplicate_id=1;
        end
        for (i=0;i<EXPERTS;i=i+1) begin
            if (routes[i]) begin
                enabled_count=enabled_count+1'b1;
                if (rst_n) route_qps[route_qp[i]]=1;
            end
        end
    end
    wire invalid_cmd=x5_moe_cmd_elems==0 || x5_moe_cmd_elems>MAX_TOKEN_ELEMS ||
        x5_moe_cmd_k==0 || x5_moe_cmd_k>MAX_K ||
        x5_moe_cmd_k>enabled_count || duplicate_id;
    localparam A_IDLE=0, A_TOPK=1, A_PAYLOAD=2;
    reg [1:0] astate;
    reg [2:0] aslot;
    reg [16*EXPERTS-1:0] input_weights;
    reg [9:0] activation_bytes;
    reg [16:0] activation_offset;
    reg activation_bad;
    reg rejected_pending;
    reg [31:0] rejected_id;
    wire tk_in_ready, tk_out_valid;
    wire [16*MAX_K-1:0] tk_ids;
    wire command_fire=x5_moe_cmd_valid && x5_moe_cmd_ready;
    bellows_n5_topk #(.EXPERTS(EXPERTS),.MAX_K(MAX_K)) topk (
        .clk(clk),.rst_n(rst_n),.in_valid(command_fire && !invalid_cmd),
        .in_ready(tk_in_ready),.scores(x5_moe_cmd_scores),.enabled(routes),
        .k(x5_moe_cmd_k),.out_valid(tk_out_valid),.out_ready(astate==A_TOPK),
        .ids(tk_ids)
    );
    assign x5_moe_cmd_ready=rst_n && !idle_allow && astate==A_IDLE &&
        !rejected_pending && tk_in_ready && (invalid_cmd || free_found);
    assign x5_token_tready=rst_n && astate==A_PAYLOAD;
    assign x5_expert_cfg_ready=rst_n && idle_allow && !cfg_pending;
    assign x5_expert_cfg_rsp_valid=rst_n && cfg_pending;
    assign x5_expert_cfg_rsp_status=rst_n ? cfg_status : 2'b0;

    reg [6:0] activation_beat_bytes, response_beat_bytes;
    reg activation_keep_bad, response_keep_bad, gap_a, gap_r;
    always @* begin
        activation_beat_bytes=0; response_beat_bytes=0;
        activation_keep_bad=0; response_keep_bad=0; gap_a=0; gap_r=0;
        for (j=0;j<B;j=j+1) begin
            if (x5_token_tkeep[j]) begin
                activation_beat_bytes=activation_beat_bytes+1'b1;
                if (gap_a) activation_keep_bad=1;
            end else gap_a=1;
            if (x5_expert_rsp_tkeep[j]) begin
                response_beat_bytes=response_beat_bytes+1'b1;
                if (gap_r) response_keep_bad=1;
            end else gap_r=1;
        end
        if (activation_beat_bytes==0 || (!x5_token_tlast && !(&x5_token_tkeep)))
            activation_keep_bad=1;
        if (response_beat_bytes==0 || (!x5_expert_rsp_tlast && !(&x5_expert_rsp_tkeep)))
            response_keep_bad=1;
    end
    wire [17:0] activation_end={1'b0,activation_offset}+activation_beat_bytes;
    wire activation_violation=activation_keep_bad ||
        activation_end>{8'b0,activation_bytes} ||
        (x5_token_tlast && activation_end!={8'b0,activation_bytes}) ||
        (!x5_token_tlast && activation_end>={8'b0,activation_bytes});

    function automatic [511:0] normalized;
        input [511:0] m;
        reg [511:0] n;
        reg [15:0] total;
        begin
            n=m;
            total={m[8*28 +:8],m[8*29 +:8]};
            if (m[8*6 +:8]==1) total=total<<1;
            n[8*7 +:8]=1; n[8*12 +:32]=0;
            n[8*30 +:16]=0;
            n[8*32 +:8]=total[15:8]; n[8*33 +:8]=total[7:0];
            normalized=n;
        end
    endfunction
    wire [511:0] normalized_rx=normalized(rx_cmd_meta);
    reg [511:0] rx_meta_hold, rx_normal_hold, rx_lookup_meta;
    reg [2:0] rx_qp_hold, rx_lookup_qp;
    reg [4:0] rx_cursor, rx_free_slot;
    reg rx_free_seen;
    wire [31:0] rx_token={rx_meta_hold[8*20 +:8],rx_meta_hold[8*21 +:8],
                         rx_meta_hold[8*22 +:8],rx_meta_hold[8*23 +:8]};
    wire [15:0] rx_expert={rx_meta_hold[8*24 +:8],rx_meta_hold[8*25 +:8]};
    wire [7:0] rx_rank=rx_meta_hold[8*26 +:8];
    wire [15:0] rx_elems={rx_meta_hold[8*28 +:8],rx_meta_hold[8*29 +:8]};
    wire [15:0] rx_weight={rx_meta_hold[8*48 +:8],rx_meta_hold[8*49 +:8]};
    wire [15:0] rx_element_offset={rx_cmd_meta[8*30 +:8],rx_cmd_meta[8*31 +:8]};
    wire [15:0] rx_byte_offset=(rx_cmd_meta[8*6 +:8]==1) ?
                              rx_element_offset<<1 : rx_element_offset;
    wire rx_fragment=rx_byte_offset[8];
    reg rx_match, rx_free, rx_semantic;
    reg [4:0] rx_job;
    reg [2:0] rx_slot;
    integer s;
    always @* begin
        rx_match=0; rx_free=0; rx_semantic=0; rx_job=0; rx_slot=0;
        if (rx_meta_hold[8*5 +:8]==2) begin
            rx_job=rx_cursor;
            rx_match=job_active[rx_cursor] && rx_lookup_qp==rx_qp_hold &&
                rx_lookup_meta[8*20 +:32]==rx_meta_hold[8*20 +:32] &&
                rx_lookup_meta[8*24 +:24]==rx_meta_hold[8*24 +:24];
            rx_free=!job_active[rx_cursor];
            if (rx_match) begin
                if (rx_lookup_meta!=rx_normal_hold ||
                    job_fragments[rx_job][rx_frag_hold] ||
                    job_presented[rx_job]) rx_semantic=1;
            end
        end else begin
            for (s=0;s<TOKENS;s=s+1)
                if (active[s] && activation_ready[s] && token_id[s]==rx_token) begin
                    rx_match=1; rx_slot=s;
                end
            if (!rx_match) rx_semantic=1;
            else if (rx_rank>=count_k[rx_slot] || rx_rank>=MAX_K) rx_semantic=1;
            else if (destinations[rx_slot][3*rx_rank +:3]!=rx_qp_hold ||
                ids[rx_slot][16*rx_rank +:16]!=rx_expert ||
                weights[rx_slot][16*rx_rank +:16]!=rx_weight ||
                count_k[rx_slot]!=rx_meta_hold[8*27 +:8] ||
                elems[rx_slot]!=rx_elems ||
                formats[rx_slot]!=rx_meta_hold[8*6 +:8] ||
                returned[rx_slot][2*rx_rank+rx_frag_hold]) rx_semantic=1;
        end
    end
    localparam RX_IDLE=0, RX_PAYLOAD=1, RX_DONE=2, RX_FETCH=3, RX_CHECK=4;
    reg [2:0] rx_state;
    reg rx_ok, rx_dispatch, rx_frag_hold;
    reg [4:0] rx_job_hold;
    reg [2:0] rx_slot_hold;
    reg [1:0] rx_rank_hold;
    reg [9:0] rx_offset;
    assign rx_cmd_ready=rst_n && rx_state==RX_IDLE;
    assign rx_payload_tready=rst_n && rx_state==RX_PAYLOAD;
    assign rx_done_valid=rst_n && rx_state==RX_DONE;
    assign rx_done_ok=rst_n && rx_ok;
    wire rx_store=rx_payload_tvalid && rx_payload_tready && rx_ok;

    localparam P_IDLE=0, P_COMMAND=1, P_FETCH=2, P_CAPTURE=3, P_SEND=4, P_WAIT=5,
               P_PREPARE=6;
    reg [2:0] dstate, tstate, qstate;
    reg [2:0] dslot, dispatch_cursor;
    reg [1:0] drank;
    reg [4:0] tjob, qjob;
    reg [5:0] return_cursor, request_cursor;
    reg [9:0] doffset, toffset, qoffset, dlimit, tlimit;
    reg [511:0] dmeta, tmeta, tbase, qmeta;
    reg [DATA_WIDTH-1:0] ddata, tdata, qdata;
    reg [B-1:0] dkeep, tkeep, qkeep;
    reg d_found, t_found, q_found;
    reg [2:0] d_choice;
    reg [4:0] t_choice, q_choice;
    always @* begin
        d_choice=dispatch_cursor;
        d_found=active[dispatch_cursor] && activation_ready[dispatch_cursor] &&
                !dispatched[dispatch_cursor];
        t_choice=return_cursor[4:0];
        t_found=job_active[return_cursor] && job_response[return_cursor];
        q_choice=request_cursor[4:0];
        q_found=job_active[request_cursor] && !job_presented[request_cursor] &&
            (job_fragments[request_cursor]==3 ||
             (job_fragments[request_cursor][0] &&
              {job_meta[request_cursor][8*32 +:8],job_meta[request_cursor][8*33 +:8]}<=256));
    end
    wire [9:0] dtotal=formats[dslot] ? {elems[dslot],1'b0} : {1'b0,elems[dslot]};
    wire [9:0] ttotal={tbase[8*32 +:8],tbase[8*33 +:8]};
    wire [9:0] qtotal={qmeta[8*32 +:8],qmeta[8*33 +:8]};
    wire [9:0] dpacket_bytes=dlimit-(doffset & 10'h300);
    wire [9:0] tpacket_bytes=tlimit-(toffset & 10'h300);
    reg [511:0] dispatch_header, return_header;
    reg [15:0] fragment_elements;
    always @* begin
        dispatch_header=0; return_header=tbase; fragment_elements=0;
        dispatch_header[0 +:32]=32'h21355846;
        dispatch_header[8*4 +:8]=1; dispatch_header[8*5 +:8]=2;
        dispatch_header[8*6 +:8]={7'b0,formats[dslot]};
        dispatch_header[8*7 +:8]=(dlimit==dtotal)?1:0;
        dispatch_header[8*8 +:8]=remote_qpns[24*destinations[dslot][3*drank +:3]+16 +:8];
        dispatch_header[8*9 +:8]=remote_qpns[24*destinations[dslot][3*drank +:3]+8 +:8];
        dispatch_header[8*10 +:8]=remote_qpns[24*destinations[dslot][3*drank +:3] +:8];
        dispatch_header[8*16 +:8]=local_qpns[24*destinations[dslot][3*drank +:3]+16 +:8];
        dispatch_header[8*17 +:8]=local_qpns[24*destinations[dslot][3*drank +:3]+8 +:8];
        dispatch_header[8*18 +:8]=local_qpns[24*destinations[dslot][3*drank +:3] +:8];
        dispatch_header[8*20 +:8]=token_id[dslot][31:24];
        dispatch_header[8*21 +:8]=token_id[dslot][23:16];
        dispatch_header[8*22 +:8]=token_id[dslot][15:8];
        dispatch_header[8*23 +:8]=token_id[dslot][7:0];
        dispatch_header[8*24 +:8]=ids[dslot][16*drank+8 +:8];
        dispatch_header[8*25 +:8]=ids[dslot][16*drank +:8];
        dispatch_header[8*26 +:8]={6'b0,drank};
        dispatch_header[8*27 +:8]={5'b0,count_k[dslot]};
        dispatch_header[8*28 +:8]={7'b0,elems[dslot][8]};
        dispatch_header[8*29 +:8]=elems[dslot][7:0];
        fragment_elements=formats[dslot] ? (doffset>>1) : doffset;
        dispatch_header[8*30 +:8]=fragment_elements[15:8];
        dispatch_header[8*31 +:8]=fragment_elements[7:0];
        dispatch_header[8*32 +:8]={6'b0,dpacket_bytes[9:8]};
        dispatch_header[8*33 +:8]=dpacket_bytes[7:0];
        dispatch_header[8*48 +:8]=weights[dslot][16*drank+8 +:8];
        dispatch_header[8*49 +:8]=weights[dslot][16*drank +:8];
        return_header[8*5 +:8]=3;
        return_header[8*8 +:24]=tbase[8*16 +:24];
        return_header[8*16 +:24]=tbase[8*8 +:24];
        return_header[8*7 +:8]=(tlimit==ttotal)?1:0;
        fragment_elements=(tbase[8*6 +:8]==1) ? (toffset>>1) : toffset;
        return_header[8*30 +:8]=fragment_elements[15:8];
        return_header[8*31 +:8]=fragment_elements[7:0];
        return_header[8*32 +:8]={6'b0,tpacket_bytes[9:8]};
        return_header[8*33 +:8]=tpacket_bytes[7:0];
    end
    assign dispatch_cmd_valid=rst_n && dstate==P_COMMAND;
    assign dispatch_cmd_qp=rst_n ? destinations[dslot][3*drank +:3] : 3'b0;
    assign dispatch_cmd_meta=rst_n ? dmeta : 512'b0;
    assign dispatch_payload_tvalid=rst_n && dstate==P_SEND;
    assign dispatch_payload_tdata=dispatch_payload_tvalid ? ddata : {DATA_WIDTH{1'b0}};
    assign dispatch_payload_tkeep=dispatch_payload_tvalid ? dkeep : {B{1'b0}};
    assign dispatch_payload_tlast=dispatch_payload_tvalid && doffset+B>=dlimit;
    assign return_cmd_valid=rst_n && tstate==P_COMMAND;
    assign return_cmd_qp=rst_n ? job_qp[tjob] : 3'b0;
    assign return_cmd_meta=rst_n ? tmeta : 512'b0;
    assign return_payload_tvalid=rst_n && tstate==P_SEND;
    assign return_payload_tdata=return_payload_tvalid ? tdata : {DATA_WIDTH{1'b0}};
    assign return_payload_tkeep=return_payload_tvalid ? tkeep : {B{1'b0}};
    assign return_payload_tlast=return_payload_tvalid && toffset+B>=tlimit;
    assign x5_expert_req_valid=rst_n && qstate==P_COMMAND;
    assign x5_expert_req_qp=rst_n ? job_qp[qjob] : 3'b0;
    assign x5_expert_req_meta=rst_n ? qmeta : 512'b0;
    assign x5_expert_req_tvalid=rst_n && qstate==P_SEND;
    assign x5_expert_req_tdata=x5_expert_req_tvalid ? qdata : {DATA_WIDTH{1'b0}};
    assign x5_expert_req_tkeep=x5_expert_req_tvalid ? qkeep : {B{1'b0}};
    assign x5_expert_req_tlast=x5_expert_req_tvalid && qoffset+B>=qtotal;

    localparam R_IDLE=0, R_PAYLOAD=1, R_EVENT=2, R_FETCH=3, R_CHECK=4;
    reg [2:0] rstate;
    reg [4:0] rjob;
    reg [16:0] response_offset;
    reg [9:0] response_bytes;
    reg response_bad, response_identity;
    reg [3:0] response_status;
    reg [2:0] response_qp;
    reg [31:0] response_token;
    reg [23:0] response_psn;
    reg [511:0] response_meta, response_lookup_meta;
    reg [2:0] response_lookup_qp;
    reg [4:0] response_cursor;
    wire response_match=job_active[response_cursor] && job_presented[response_cursor] &&
        !job_response[response_cursor] && response_lookup_qp==response_qp &&
        response_lookup_meta==response_meta;
    wire [17:0] response_end={1'b0,response_offset}+response_beat_bytes;
    wire response_violation=response_keep_bad || response_end>{8'b0,response_bytes} ||
        (x5_expert_rsp_tlast && response_end!={8'b0,response_bytes}) ||
        (!x5_expert_rsp_tlast && response_end>={8'b0,response_bytes});
    assign x5_expert_rsp_ready=rst_n && rstate==R_IDLE;
    assign x5_expert_rsp_tready=rst_n && rstate==R_PAYLOAD;
    assign evt_valid=rst_n && rstate==R_EVENT;
    assign evt_status=rst_n ? response_status : 4'b0;
    assign evt_qp=(rst_n && response_identity) ? response_qp : 3'b0;
    assign evt_token_id=(rst_n && response_identity) ? response_token : 32'b0;
    assign evt_psn=(rst_n && response_identity) ? response_psn : 24'b0;

    localparam C_IDLE=0, C_COMMAND=1, C_RUN=2, C_FINAL=3;
    reg [1:0] cstate;
    reg [2:0] cslot, combine_cursor;
    reg c_found;
    reg [2:0] c_choice;
    integer cs, cr, cc;
    reg context_complete;
    always @* begin
        c_found=0; c_choice=0; context_complete=0; cc=0;
        for (cs=0;cs<TOKENS;cs=cs+1) begin
            cc=combine_cursor+cs;
            if (cc>=TOKENS) cc=cc-TOKENS;
            context_complete=active[cc] && dispatched[cc] && !combining[cc] && !completed[cc];
            for (cr=0;cr<MAX_K;cr=cr+1)
                if (cr<count_k[cc] &&
                    (returned[cc][2*cr +:2] != ((formats[cc] && elems[cc]>128)?2'b11:2'b01)))
                    context_complete=0;
            if (context_complete && !c_found) begin c_found=1; c_choice=cc; end
        end
    end
    wire comb_cmd_ready, comb_read_valid, comb_sample_ready, comb_valid, comb_last, comb_idle;
    wire [1:0] comb_rank;
    wire [7:0] comb_elem, comb_out_elem;
    wire [15:0] comb_data;
    wire [31:0] comb_token;
    reg sample_pending;
    reg [5:0] sample_lane;
    wire [DATA_WIDTH-1:0] activation_q, return_q, job_q, response_q;
    wire [15:0] sample_word=return_q>>(8*sample_lane);
    reg [DATA_WIDTH-1:0] combine_data;
    reg [B-1:0] combine_keep;
    reg [6:0] combine_lane;
    reg combine_valid, combine_last;
    wire comb_ready=!combine_valid;
    bellows_n5_combine #(.MAX_K(MAX_K),.MAX_TOKEN_ELEMS(MAX_TOKEN_ELEMS)) combiner (
        .clk(clk),.rst_n(rst_n),.cmd_valid(rst_n && cstate==C_COMMAND),
        .cmd_ready(comb_cmd_ready),.cmd_token_id(token_id[cslot]),
        .cmd_elems(elems[cslot]),.cmd_k(count_k[cslot]),.cmd_format(formats[cslot]),
        .cmd_weights(weights[cslot]),.read_valid(comb_read_valid),
        .read_ready(!sample_pending),.read_rank(comb_rank),.read_elem(comb_elem),
        .sample_valid(sample_pending),.sample_ready(comb_sample_ready),
        .sample_data(sample_word),.out_valid(comb_valid),.out_ready(comb_ready),
        .out_data(comb_data),.out_token_id(comb_token),.out_elem(comb_out_elem),
        .out_last(comb_last),.idle(comb_idle)
    );
    wire [15:0] sample_addr=((cslot*MAX_K+comb_rank)<<9) +
        (formats[cslot] ? ({8'b0,comb_elem}<<1) : {8'b0,comb_elem});
    wire [15:0] activation_waddr=({13'b0,aslot}<<9)+activation_offset[15:0];
    wire [15:0] activation_raddr=({13'b0,dslot}<<9)+doffset;
    wire [15:0] return_waddr=((rx_slot_hold*MAX_K+rx_rank_hold)<<9)+rx_offset;
    wire [15:0] job_waddr=({11'b0,rx_job_hold}<<9)+rx_offset;
    wire [15:0] job_raddr=({11'b0,qjob}<<9)+qoffset;
    wire [15:0] response_waddr=({11'b0,rjob}<<9)+response_offset[15:0];
    wire [15:0] response_raddr=({11'b0,tjob}<<9)+toffset;
    bellows_n5_payload_ram #(.DATA_WIDTH(DATA_WIDTH),.BYTES(TOKENS*512)) activation_ram (
        .clk(clk),.we(x5_token_tvalid && x5_token_tready && !activation_bad &&
                    !activation_violation),
        .waddr(activation_waddr),
        .wdata(x5_token_tdata),.wkeep(x5_token_tkeep),
        .re(dstate==P_FETCH),.raddr(activation_raddr),
        .rdata(activation_q)
    );
    bellows_n5_payload_ram #(.DATA_WIDTH(DATA_WIDTH),.BYTES(TOKENS*MAX_K*512)) return_ram (
        .clk(clk),.we(rx_store && !rx_dispatch),
        .waddr(return_waddr),
        .wdata(rx_payload_tdata),.wkeep(rx_payload_tkeep),
        .re(comb_read_valid && !sample_pending),.raddr(sample_addr),.rdata(return_q)
    );
    bellows_n5_payload_ram #(.DATA_WIDTH(DATA_WIDTH),.BYTES(JOBS*512)) job_ram (
        .clk(clk),.we(rx_store && rx_dispatch),
        .waddr(job_waddr),
        .wdata(rx_payload_tdata),.wkeep(rx_payload_tkeep),
        .re(qstate==P_FETCH),.raddr(job_raddr),.rdata(job_q)
    );
    bellows_n5_payload_ram #(.DATA_WIDTH(DATA_WIDTH),.BYTES(JOBS*512)) response_ram (
        .clk(clk),.we(x5_expert_rsp_tvalid && x5_expert_rsp_tready &&
                      !response_bad && !response_violation),
        .waddr(response_waddr),
        .wdata(x5_expert_rsp_tdata),.wkeep(x5_expert_rsp_tkeep),
        .re(tstate==P_FETCH),.raddr(response_raddr),.rdata(response_q)
    );
    assign x5_combine_tvalid=rst_n && combine_valid;
    assign x5_combine_tdata=x5_combine_tvalid ? combine_data : {DATA_WIDTH{1'b0}};
    assign x5_combine_tkeep=x5_combine_tvalid ? combine_keep : {B{1'b0}};
    assign x5_combine_tlast=x5_combine_tvalid && combine_last;
    assign x5_combine_token_id=rst_n ? token_id[cslot] : 32'b0;
    reg cpl_pending, cpl_reject, cpl_turn;
    reg [2:0] cpl_slot, cpl_cursor;
    reg [31:0] cpl_id;
    reg [3:0] cpl_status;
    reg completed_found;
    reg [2:0] completed_slot;
    integer cp, cpl_candidate;
    always @* begin
        completed_found=0; completed_slot=0; cpl_candidate=0;
        for (cp=0;cp<TOKENS;cp=cp+1) begin
            cpl_candidate=cpl_cursor+cp;
            if (cpl_candidate>=TOKENS) cpl_candidate=cpl_candidate-TOKENS;
            if (completed[cpl_candidate] && !completed_found) begin
                completed_found=1; completed_slot=cpl_candidate;
            end
        end
    end
    assign x5_moe_cpl_valid=rst_n && cpl_pending;
    assign x5_moe_cpl_token_id=rst_n ? cpl_id : 32'b0;
    assign x5_moe_cpl_status=rst_n ? cpl_status : 4'b0;
    assign idle=rst_n && active==0 && job_active==0 && astate==A_IDLE &&
        rx_state==RX_IDLE && rstate==R_IDLE && dstate==P_IDLE && tstate==P_IDLE &&
        qstate==P_IDLE && cstate==C_IDLE && !combine_valid &&
        !rejected_pending && !cpl_pending && !cfg_pending;
    integer n, k, lane;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            routes<=0; cfg_pending<=0; cfg_status<=0;
            active<=0; activation_ready<=0; dispatched<=0; combining<=0; completed<=0;
            job_active<=0; job_presented<=0; job_response<=0;
            astate<=A_IDLE; aslot<=0; input_weights<=0; activation_bytes<=0;
            activation_offset<=0; activation_bad<=0; rejected_pending<=0; rejected_id<=0;
            rx_state<=RX_IDLE; rx_ok<=0; rx_dispatch<=0; rx_frag_hold<=0;
            rx_job_hold<=0; rx_slot_hold<=0; rx_rank_hold<=0; rx_offset<=0;
            rx_meta_hold<=0; rx_normal_hold<=0; rx_lookup_meta<=0; rx_lookup_qp<=0;
            rx_qp_hold<=0; rx_cursor<=0; rx_free_slot<=0; rx_free_seen<=0;
            dstate<=P_IDLE; tstate<=P_IDLE; qstate<=P_IDLE;
            dslot<=0; dispatch_cursor<=0; drank<=0; tjob<=0; qjob<=0;
            return_cursor<=0; request_cursor<=0; doffset<=0; toffset<=0; qoffset<=0;
            dlimit<=0; tlimit<=0; dmeta<=0; tmeta<=0; tbase<=0; qmeta<=0;
            ddata<=0; tdata<=0; qdata<=0;
            dkeep<=0; tkeep<=0; qkeep<=0;
            rstate<=R_IDLE; rjob<=0; response_offset<=0; response_bytes<=0;
            response_bad<=0; response_identity<=0; response_status<=0;
            response_qp<=0; response_token<=0; response_psn<=0;
            response_meta<=0; response_lookup_meta<=0; response_lookup_qp<=0;
            response_cursor<=0;
            cstate<=C_IDLE; cslot<=0; combine_cursor<=0; sample_pending<=0;
            sample_lane<=0; combine_data<=0; combine_keep<=0; combine_lane<=0;
            combine_valid<=0; combine_last<=0;
            cpl_pending<=0; cpl_reject<=0; cpl_turn<=0; cpl_slot<=0; cpl_cursor<=0;
            cpl_id<=0; cpl_status<=0;
            for (n=0;n<EXPERTS;n=n+1) route_qp[n]<=0;
            for (n=0;n<TOKENS;n=n+1) begin
                token_id[n]<=0; elems[n]<=0; count_k[n]<=0; formats[n]<=0;
                ids[n]<=0; weights[n]<=0; destinations[n]<=0; returned[n]<=0;
                completion_status[n]<=0;
            end
            for (n=0;n<JOBS;n=n+1) begin job_meta[n]<=0; job_qp[n]<=0; job_fragments[n]<=0; end
        end else begin
            if (cfg_pending && x5_expert_cfg_rsp_ready) cfg_pending<=0;
            if (x5_expert_cfg_valid && x5_expert_cfg_ready) begin
                cfg_pending<=1;
                if (x5_expert_cfg_id>=EXPERTS) cfg_status<=1;
                else if (x5_expert_cfg_enable &&
                    (x5_expert_cfg_qp>=QPS || !qp_enabled[x5_expert_cfg_qp])) cfg_status<=2;
                else begin
                    cfg_status<=0; routes[x5_expert_cfg_id]<=x5_expert_cfg_enable;
                    route_qp[x5_expert_cfg_id]<=x5_expert_cfg_qp;
                end
            end
            if (command_fire) begin
                if (invalid_cmd) begin rejected_pending<=1; rejected_id<=x5_moe_cmd_token_id; end
                else begin
                    aslot<=free_slot; active[free_slot]<=1; activation_ready[free_slot]<=0;
                    dispatched[free_slot]<=0; combining[free_slot]<=0; completed[free_slot]<=0;
                    returned[free_slot]<=0; token_id[free_slot]<=x5_moe_cmd_token_id;
                    elems[free_slot]<=x5_moe_cmd_elems; count_k[free_slot]<=x5_moe_cmd_k;
                    formats[free_slot]<=x5_moe_cmd_format; input_weights<=x5_moe_cmd_weights;
                    activation_bytes<=x5_moe_cmd_format ?
                        {x5_moe_cmd_elems,1'b0} : {1'b0,x5_moe_cmd_elems};
                    activation_offset<=0; activation_bad<=0; astate<=A_TOPK;
                end
            end
            if (astate==A_TOPK && tk_out_valid) begin
                ids[aslot]<=tk_ids; weights[aslot]<=0; destinations[aslot]<=0;
                for (k=0;k<MAX_K;k=k+1)
                    if (k<count_k[aslot]) begin
                        weights[aslot][16*k +:16]<=input_weights[16*tk_ids[16*k +:16] +:16];
                        destinations[aslot][3*k +:3]<=route_qp[tk_ids[16*k +:16]];
                    end
                astate<=A_PAYLOAD;
            end
            if (x5_token_tvalid && x5_token_tready) begin
                if (activation_violation) activation_bad<=1;
                if (activation_end>65535) activation_offset<=65536;
                else activation_offset<=activation_end[16:0];
                if (x5_token_tlast) begin
                    astate<=A_IDLE;
                    if (activation_bad || activation_violation) begin
                        completed[aslot]<=1; completion_status[aslot]<=9;
                    end else activation_ready[aslot]<=1;
                end
            end
            if (rx_cmd_valid && rx_cmd_ready) begin
                rx_meta_hold<=rx_cmd_meta; rx_normal_hold<=normalized_rx;
                rx_qp_hold<=rx_cmd_qp; rx_cursor<=0; rx_free_seen<=0;
                rx_dispatch<=rx_cmd_meta[8*5 +:8]==2;
                rx_frag_hold<=rx_fragment; rx_offset<=rx_byte_offset[9:0];
                rx_state<=RX_FETCH;
            end
            if (rx_state==RX_FETCH) begin
                rx_lookup_meta<=job_meta[rx_cursor]; rx_lookup_qp<=job_qp[rx_cursor];
                rx_state<=RX_CHECK;
            end
            if (rx_state==RX_CHECK) begin
                if (!rx_dispatch || rx_match) begin
                    rx_ok<=!rx_semantic; rx_job_hold<=rx_job;
                    rx_slot_hold<=rx_slot; rx_rank_hold<=rx_rank[1:0]; rx_state<=RX_PAYLOAD;
                end else if (rx_cursor==JOBS-1) begin
                    if (rx_free_seen || rx_free) begin
                        rx_job_hold<=rx_free_seen ? rx_free_slot : rx_cursor;
                        rx_ok<=1; rx_state<=RX_PAYLOAD;
                        if (rx_free_seen) begin
                            job_active[rx_free_slot]<=1; job_presented[rx_free_slot]<=0;
                            job_response[rx_free_slot]<=0; job_meta[rx_free_slot]<=rx_normal_hold;
                            job_qp[rx_free_slot]<=rx_qp_hold; job_fragments[rx_free_slot]<=0;
                        end else begin
                            job_active[rx_cursor]<=1; job_presented[rx_cursor]<=0;
                            job_response[rx_cursor]<=0; job_meta[rx_cursor]<=rx_normal_hold;
                            job_qp[rx_cursor]<=rx_qp_hold; job_fragments[rx_cursor]<=0;
                        end
                    end else begin rx_cursor<=0; rx_free_seen<=0; rx_state<=RX_FETCH; end
                end else begin
                    if (rx_free && !rx_free_seen) begin rx_free_seen<=1; rx_free_slot<=rx_cursor; end
                    rx_cursor<=rx_cursor+1'b1; rx_state<=RX_FETCH;
                end
            end
            if (rx_payload_tvalid && rx_payload_tready) begin
                rx_offset<=rx_offset+B;
                if (rx_payload_tlast) begin
                    rx_state<=RX_DONE;
                    if (rx_ok) begin
                        if (rx_dispatch) job_fragments[rx_job_hold][rx_frag_hold]<=1;
                        else returned[rx_slot_hold][2*rx_rank_hold+rx_frag_hold]<=1;
                    end
                end
            end
            if (rx_done_valid && rx_done_ready) rx_state<=RX_IDLE;

            case (dstate)
                P_IDLE: if (d_found) begin
                    dslot<=d_choice; drank<=0; doffset<=0; dstate<=P_PREPARE;
                    dlimit<=(formats[d_choice] && elems[d_choice]>128) ? 256 :
                        (formats[d_choice] ? {elems[d_choice],1'b0} : {1'b0,elems[d_choice]});
                end else dispatch_cursor<=(dispatch_cursor==TOKENS-1)?0:dispatch_cursor+1'b1;
                P_PREPARE: begin dmeta<=dispatch_header; dstate<=P_COMMAND; end
                P_COMMAND: if (dispatch_cmd_ready) dstate<=P_FETCH;
                P_FETCH: dstate<=P_CAPTURE;
                P_CAPTURE: begin
                    ddata<=0; dkeep<=0;
                    for (lane=0;lane<B;lane=lane+1)
                        if (doffset+lane<dlimit) begin
                            ddata[8*lane +:8]<=activation_q[8*lane +:8]; dkeep[lane]<=1;
                        end
                    dstate<=P_SEND;
                end
                P_SEND: if (dispatch_payload_tready) begin
                    if (doffset+B>=dlimit) dstate<=P_WAIT;
                    else begin doffset<=doffset+B; dstate<=P_FETCH; end
                end
                P_WAIT: if (dispatch_done) begin
                    if (dlimit<dtotal) begin doffset<=256; dlimit<=dtotal; dstate<=P_PREPARE; end
                    else if ({1'b0,drank}+3'd1<count_k[dslot]) begin
                        drank<=drank+1'b1; doffset<=0;
                        dlimit<=(dtotal>256)?256:dtotal; dstate<=P_PREPARE;
                    end else begin
                        dispatched[dslot]<=1; dstate<=P_IDLE;
                        dispatch_cursor<=(dslot==TOKENS-1)?0:dslot+1'b1;
                    end
                end
                default: dstate<=P_IDLE;
            endcase
            case (tstate)
                P_IDLE: if (t_found) begin
                    tjob<=t_choice; toffset<=0; tstate<=P_PREPARE;
                    tbase<=job_meta[t_choice];
                    tlimit<=({job_meta[t_choice][8*32 +:8],job_meta[t_choice][8*33 +:8]}>256) ?
                        256 : {job_meta[t_choice][8*32 +:8],job_meta[t_choice][8*33 +:8]};
                end else return_cursor<=(return_cursor==JOBS-1)?0:return_cursor+1'b1;
                P_PREPARE: begin tmeta<=return_header; tstate<=P_COMMAND; end
                P_COMMAND: if (return_cmd_ready) tstate<=P_FETCH;
                P_FETCH: tstate<=P_CAPTURE;
                P_CAPTURE: begin
                    tdata<=0; tkeep<=0;
                    for (lane=0;lane<B;lane=lane+1)
                        if (toffset+lane<tlimit) begin
                            tdata[8*lane +:8]<=response_q[8*lane +:8]; tkeep[lane]<=1;
                        end
                    tstate<=P_SEND;
                end
                P_SEND: if (return_payload_tready) begin
                    if (toffset+B>=tlimit) tstate<=P_WAIT;
                    else begin toffset<=toffset+B; tstate<=P_FETCH; end
                end
                P_WAIT: if (return_done) begin
                    if (tlimit<ttotal) begin toffset<=256; tlimit<=ttotal; tstate<=P_PREPARE; end
                    else begin
                        job_active[tjob]<=0; job_response[tjob]<=0; job_presented[tjob]<=0;
                        tstate<=P_IDLE; return_cursor<=(tjob==JOBS-1)?0:tjob+1'b1;
                    end
                end
                default: tstate<=P_IDLE;
            endcase
            case (qstate)
                P_IDLE: if (q_found) begin qjob<=q_choice; qoffset<=0; qstate<=P_PREPARE; end
                    else request_cursor<=(request_cursor==JOBS-1)?0:request_cursor+1'b1;
                P_PREPARE: begin qmeta<=job_meta[qjob]; qstate<=P_COMMAND; end
                P_COMMAND: if (x5_expert_req_ready) qstate<=P_FETCH;
                P_FETCH: qstate<=P_CAPTURE;
                P_CAPTURE: begin
                    qdata<=0; qkeep<=0;
                    for (lane=0;lane<B;lane=lane+1)
                        if (qoffset+lane<qtotal) begin
                            qdata[8*lane +:8]<=job_q[8*lane +:8]; qkeep[lane]<=1;
                        end
                    qstate<=P_SEND;
                end
                P_SEND: if (x5_expert_req_tready) begin
                    if (qoffset+B>=qtotal) begin
                        job_presented[qjob]<=1; qstate<=P_IDLE;
                        request_cursor<=(qjob==JOBS-1)?0:qjob+1'b1;
                    end else begin qoffset<=qoffset+B; qstate<=P_FETCH; end
                end
                default: qstate<=P_IDLE;
            endcase
            case (rstate)
                R_IDLE: if (x5_expert_rsp_valid && x5_expert_rsp_ready) begin
                    response_identity<=0; response_offset<=0; response_bad<=0;
                    response_meta<=x5_expert_rsp_meta; response_qp<=x5_expert_rsp_qp;
                    response_cursor<=0; rstate<=R_FETCH;
                end
                R_FETCH: begin
                    response_lookup_meta<=job_meta[response_cursor];
                    response_lookup_qp<=job_qp[response_cursor]; rstate<=R_CHECK;
                end
                R_CHECK: begin
                    if (response_match) begin
                        rjob<=response_cursor; response_identity<=1;
                        response_token<={response_meta[8*20 +:8],response_meta[8*21 +:8],
                            response_meta[8*22 +:8],response_meta[8*23 +:8]};
                        response_psn<=0;
                        response_bytes<={response_meta[8*32 +:8],response_meta[8*33 +:8]};
                        rstate<=R_PAYLOAD;
                    end else if (response_cursor==JOBS-1) begin response_status<=7; rstate<=R_EVENT; end
                    else begin response_cursor<=response_cursor+1'b1; rstate<=R_FETCH; end
                end
                R_PAYLOAD: if (x5_expert_rsp_tvalid) begin
                    if (response_violation) response_bad<=1;
                    if (response_end>65535) response_offset<=65536;
                    else response_offset<=response_end[16:0];
                    if (x5_expert_rsp_tlast) begin
                        rstate<=R_EVENT;
                        if (response_bad || response_violation) response_status<=9;
                        else begin response_status<=0; job_response[rjob]<=1; end
                    end
                end
                R_EVENT: if (evt_ready) rstate<=R_IDLE;
                default: rstate<=R_IDLE;
            endcase
            if (comb_read_valid && !sample_pending) begin
                sample_pending<=1; sample_lane<=sample_addr & (B-1);
            end else if (sample_pending && comb_sample_ready) sample_pending<=0;
            case (cstate)
                C_IDLE: if (c_found) begin
                    cslot<=c_choice; combining[c_choice]<=1; cstate<=C_COMMAND;
                    combine_data<=0; combine_keep<=0; combine_lane<=0;
                end
                C_COMMAND: if (comb_cmd_ready) cstate<=C_RUN;
                C_RUN: if (comb_valid && comb_ready) begin
                    combine_data[8*combine_lane +:16]<=comb_data;
                    combine_keep[combine_lane +:2]<=2'b11;
                    if (combine_lane==B-2 || comb_last) begin
                        combine_valid<=1; combine_last<=comb_last;
                        if (comb_last) cstate<=C_FINAL;
                    end else combine_lane<=combine_lane+2;
                end
                C_FINAL: if (combine_valid && x5_combine_tready) begin
                    completed[cslot]<=1; completion_status[cslot]<=0;
                    cstate<=C_IDLE; combine_cursor<=(cslot==TOKENS-1)?0:cslot+1'b1;
                end
                default: cstate<=C_IDLE;
            endcase
            if (combine_valid && x5_combine_tready) begin
                combine_valid<=0; combine_data<=0; combine_keep<=0; combine_lane<=0;
            end
            if (!cpl_pending) begin
                if (rejected_pending && (!completed_found || cpl_turn)) begin
                    cpl_pending<=1; cpl_reject<=1; cpl_id<=rejected_id; cpl_status<=7;
                    rejected_pending<=0; cpl_turn<=0;
                end else if (completed_found) begin
                    cpl_pending<=1; cpl_reject<=0; cpl_slot<=completed_slot;
                    cpl_id<=token_id[completed_slot]; cpl_status<=completion_status[completed_slot];
                    cpl_turn<=1;
                end
            end else if (x5_moe_cpl_ready) begin
                cpl_pending<=0;
                if (!cpl_reject) begin
                    active[cpl_slot]<=0; completed[cpl_slot]<=0; combining[cpl_slot]<=0;
                    activation_ready[cpl_slot]<=0; dispatched[cpl_slot]<=0;
                    cpl_cursor<=(cpl_slot==TOKENS-1)?0:cpl_slot+1'b1;
                end
            end
        end
    end
endmodule
`default_nettype wire
