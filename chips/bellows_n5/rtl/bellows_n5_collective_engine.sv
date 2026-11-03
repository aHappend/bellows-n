`default_nettype none
module furnace_collective_engine #(
    parameter integer DATA_WIDTH=512,
    parameter integer MAX_PACKET_BYTES=9216
) (
    input wire clk, rst_n, idle_allow,
    input wire cfg_valid,
    output wire cfg_ready,
    input wire cfg_enable,
    input wire [15:0] cfg_job,
    input wire [1:0] cfg_format, cfg_op,
    input wire [3:0] cfg_participants,
    input wire [31:0] cfg_bytes,
    input wire [63:0] cfg_addr,
    output wire cfg_rsp_valid,
    input wire cfg_rsp_ready,
    output reg [2:0] cfg_rsp_status,
    input wire [7:0] qp_enabled,
    input wire [23:0] qp_ranks,
    input wire [511:0] qp_bases, qp_lengths,
    output wire job_enabled, job_active, busy,
    output wire [63:0] job_addr,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [7:0] cmd_opcode,
    input wire [2:0] cmd_rank,
    input wire [13:0] cmd_bytes,
    output wire cmd_error,
    input wire in_valid,
    output wire in_ready,
    input wire [DATA_WIDTH-1:0] in_data,
    input wire [(DATA_WIDTH>>3)-1:0] in_keep,
    input wire in_last,
    output wire wr_valid,
    input wire wr_ready,
    output wire [63:0] wr_addr,
    output wire [DATA_WIDTH-1:0] wr_data,
    output wire [(DATA_WIDTH>>3)-1:0] wr_keep,
    output wire wr_last,
    output wire done_valid,
    input wire done_ready,
    output reg [3:0] done_status,
    output wire coll_done_valid,
    input wire coll_done_ready,
    output wire [15:0] coll_done_job,
    output wire [31:0] coll_done_bytes
);
    localparam integer B=DATA_WIDTH>>3;
    localparam integer SHIFT=(DATA_WIDTH==64) ? 3 : 6;
    localparam integer ROWS=(MAX_PACKET_BYTES+B-1)>>SHIFT;
    localparam integer ROW_AW=(ROWS>1)?$clog2(ROWS):1;
    localparam IDLE=0, STREAM=1, DRAIN=2, REPLAY=3, DONE=4, COMPLETION=5;
    reg [2:0] state;
    reg enabled, cfg_pending, completion_pending;
    reg [15:0] job;
    reg [1:0] format, operation;
    reg [3:0] participants, next_rank;
    reg [31:0] bytes;
    reg [63:0] address;
    reg [13:0] input_row, output_row, replay_row;
    reg input_pending;
    reg [DATA_WIDTH-1:0] input_data;
    reg [B-1:0] input_keep;
    reg input_last;
    (* ramstyle = "M20K", nomem2reg *) reg [DATA_WIDTH-1:0] accumulator [0:ROWS-1];
    reg [DATA_WIDTH-1:0] accumulator_q;
    wire alu_in_ready, alu_valid, alu_last;
    wire [DATA_WIDTH-1:0] alu_data;
    wire [B-1:0] alu_keep;
    reg replay_valid, replay_last, replay_issued_last;
    reg [63:0] replay_address;
    reg [31:0] replay_remaining;
    reg [B-1:0] replay_keep;

    reg [7:0] seen_ranks;
    reg invalid_ranks, invalid_region;
    reg [64:0] candidate_region_end;
    wire [64:0] vector_end={1'b0,cfg_addr}+{33'b0,cfg_bytes};
    wire [32:0] wire_size={1'b0,cfg_bytes}+33'd74+
                           {31'b0,((2'd0-cfg_bytes[1:0]) & 2'd3)};
    integer q;
    always @* begin
        seen_ranks=0; invalid_ranks=0; invalid_region=vector_end[64];
        candidate_region_end=0;
        for (q=0;q<8;q=q+1) begin
            if (qp_enabled[q]) begin
                if ({1'b0,qp_ranks[q*3 +:3]}>=cfg_participants ||
                    seen_ranks[qp_ranks[q*3 +:3]]) invalid_ranks=1;
                seen_ranks[qp_ranks[q*3 +:3]]=1;
                candidate_region_end={1'b0,qp_bases[q*64 +:64]}+
                                     {1'b0,qp_lengths[q*64 +:64]};
                if (cfg_addr<qp_bases[q*64 +:64] ||
                    vector_end>candidate_region_end || candidate_region_end[64])
                    invalid_region=1;
            end
        end
        for (q=0;q<8;q=q+1)
            if (q<cfg_participants && !seen_ranks[q]) invalid_ranks=1;
    end
    assign job_enabled=rst_n && enabled;
    assign job_active=rst_n && enabled && (next_rank<participants || completion_pending);
    assign job_addr=rst_n ? address : 64'b0;
    assign busy=rst_n && (state!=IDLE || completion_pending);
    assign cfg_ready=rst_n && idle_allow && state==IDLE &&
                     (next_rank==0 || next_rank==participants) &&
                     !cfg_pending && !completion_pending;
    assign cfg_rsp_valid=rst_n && cfg_pending;
    assign cmd_ready=rst_n && state==IDLE && enabled && !cfg_pending &&
                     !completion_pending && !cfg_valid;
    assign cmd_error={1'b0,cmd_rank}!=next_rank ||
                     (cmd_opcode!=8'h0a && cmd_opcode!=8'h0b) ||
                     {18'b0,cmd_bytes}!=bytes;
    assign in_ready=rst_n && state==STREAM &&
                    (next_rank==0 || !input_pending || alu_in_ready);
    wire input_fire=in_valid && in_ready;
    wire alu_fire=alu_valid;
    wire seed_write=input_fire && next_rank==0;
    wire reduced_write=alu_fire && (state==STREAM || state==DRAIN);
    wire replay_advance=state==REPLAY && (!replay_valid || wr_ready);
    wire replay_read=replay_advance && !replay_issued_last;
    wire accumulation_read=input_fire && next_rank!=0;
    wire [13:0] memory_write_row_full=seed_write ? input_row : output_row;
    wire [13:0] memory_read_row_full=accumulation_read ? input_row : replay_row;
    wire [ROW_AW-1:0] memory_write_row=memory_write_row_full;
    wire [ROW_AW-1:0] memory_read_row=memory_read_row_full;
    wire [DATA_WIDTH-1:0] memory_write_data=seed_write ? in_data : alu_data;
    wire memory_write_enable=(seed_write || reduced_write) &&
                             memory_write_row_full<ROWS;
    wire memory_read_enable=(accumulation_read || replay_read) &&
                            memory_read_row_full<ROWS;

    always @(posedge clk) begin
        if (memory_write_enable) accumulator[memory_write_row]<=memory_write_data;
        if (memory_read_enable) accumulator_q<=accumulator[memory_read_row];
    end
    furnace_reduce_alu #(.DATA_WIDTH(DATA_WIDTH)) reduce_alu (
        .clk(clk), .rst_n(rst_n), .in_valid(input_pending),
        .in_a(accumulator_q), .in_b(input_data), .in_keep(input_keep),
        .in_format(format), .in_op(operation), .in_last(input_last),
        .in_ready(alu_in_ready), .out_valid(alu_valid), .out_data(alu_data),
        .out_keep(alu_keep), .out_last(alu_last), .out_ready(1'b1)
    );
    assign wr_valid=rst_n && state==REPLAY && replay_valid;
    assign wr_addr=rst_n ? replay_address : 64'b0;
    assign wr_keep=(rst_n && replay_valid) ? replay_keep : {B{1'b0}};
    assign wr_last=rst_n && replay_valid && replay_last;
    genvar lane;
    generate for (lane=0;lane<B;lane=lane+1) begin : g_write_lanes
        assign wr_data[lane*8 +:8]=wr_keep[lane] ? accumulator_q[lane*8 +:8] : 8'b0;
    end endgenerate
    assign done_valid=rst_n && state==DONE;
    assign coll_done_valid=rst_n && completion_pending;
    assign coll_done_job=rst_n ? job : 16'b0;
    assign coll_done_bytes=rst_n ? bytes : 32'b0;

    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; enabled<=0; cfg_pending<=0; completion_pending<=0;
            job<=0; format<=0; operation<=0; participants<=0; next_rank<=0;
            bytes<=0; address<=0; cfg_rsp_status<=0; done_status<=0;
            input_row<=0; output_row<=0; replay_row<=0;
            input_pending<=0; input_data<=0; input_keep<=0; input_last<=0;
            replay_valid<=0; replay_last<=0; replay_issued_last<=0;
            replay_address<=0; replay_remaining<=0; replay_keep<=0;
        end else begin
            if (cfg_pending && cfg_rsp_ready) cfg_pending<=0;
            if (completion_pending && coll_done_ready) completion_pending<=0;
            if (cfg_valid && cfg_ready) begin
                cfg_pending<=1;
                if (!cfg_enable) begin
                    cfg_rsp_status<=0; enabled<=0; next_rank<=0;
                end else if (invalid_region) cfg_rsp_status<=2;
                else if (cfg_format==3 || cfg_op==3 || cfg_participants<1 ||
                         cfg_participants>8 || cfg_bytes==0 ||
                         (cfg_format==2 ? (cfg_bytes[1:0]!=0) : cfg_bytes[0]) ||
                         wire_size>MAX_PACKET_BYTES || invalid_ranks)
                    cfg_rsp_status<=3;
                else begin
                    cfg_rsp_status<=0; enabled<=1; next_rank<=0;
                    job<=cfg_job; format<=cfg_format; operation<=cfg_op;
                    participants<=cfg_participants; bytes<=cfg_bytes; address<=cfg_addr;
                end
            end
            if (input_pending && alu_in_ready) input_pending<=0;
            if (input_fire) begin
                input_row<=input_row+1'b1;
                if (next_rank!=0) begin
                    input_pending<=1; input_data<=in_data;
                    input_keep<=in_keep; input_last<=in_last;
                end
                if (in_last) begin
                    if (next_rank==0) begin
                        if (participants==1) begin
                            state<=REPLAY; replay_row<=0; replay_valid<=0;
                            replay_issued_last<=0; replay_remaining<=bytes;
                            replay_address<=address;
                        end else begin
                            next_rank<=next_rank+1'b1; done_status<=1; state<=DONE;
                        end
                    end else state<=DRAIN;
                end
            end
            if (reduced_write) begin
                output_row<=output_row+1'b1;
                if (alu_last) begin
                    if (next_rank+4'd1==participants) begin
                        state<=REPLAY; replay_row<=0; replay_valid<=0;
                        replay_issued_last<=0; replay_remaining<=bytes;
                        replay_address<=address;
                    end else begin
                        next_rank<=next_rank+1'b1; done_status<=1; state<=DONE;
                    end
                end
            end
            case (state)
                IDLE: if (cmd_valid && cmd_ready) begin
                    if (cmd_error) begin done_status<=8; state<=DONE; end
                    else begin
                        input_row<=0; output_row<=0; input_pending<=0;
                        state<=STREAM;
                    end
                end
                REPLAY: begin
                    if (replay_advance) begin
                        replay_valid<=replay_read;
                        if (replay_read) begin
                            replay_row<=replay_row+1'b1;
                            replay_last<=replay_remaining<=B;
                            if (replay_valid) replay_address<=replay_address+B;
                            for (k=0;k<B;k=k+1) replay_keep[k]<=k<replay_remaining;
                            if (replay_remaining<=B) begin
                                replay_issued_last<=1; replay_remaining<=0;
                            end else replay_remaining<=replay_remaining-B;
                        end
                    end
                    if (wr_valid && wr_ready && wr_last) begin
                        completion_pending<=1;
                        done_status<=1; state<=DONE; next_rank<=participants;
                    end
                end
                DONE: if (done_ready) begin
                    if (completion_pending && !coll_done_ready) state<=COMPLETION;
                    else state<=IDLE;
                end
                COMPLETION: if (!completion_pending || coll_done_ready) state<=IDLE;
                default: begin end
            endcase
        end
    end
endmodule
`default_nettype wire
