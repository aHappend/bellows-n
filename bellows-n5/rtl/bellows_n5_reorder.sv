`default_nettype none
module bellows_n5_reorder #(
    parameter integer QPS=8
) (
    input wire clk, rst_n,
    input wire cfg_valid,
    output wire cfg_ready,
    input wire [2:0] cfg_index,
    input wire cfg_enable,
    input wire [23:0] cfg_base,
    output wire cfg_rsp_valid,
    input wire cfg_rsp_ready,
    output wire [1:0] cfg_rsp_status,
    input wire req_valid,
    output wire req_ready,
    input wire [2:0] req_qp,
    input wire [23:0] req_psn,
    output wire decision_valid,
    input wire decision_ready,
    output wire [2:0] decision_qp,
    output wire [23:0] decision_psn,
    output wire [1:0] decision_status,
    input wire commit_valid,
    output wire commit_ready,
    input wire commit_ok,
    output wire sack_valid,
    input wire sack_ready,
    output wire [2:0] sack_qp,
    output wire [23:0] sack_base,
    output wire [255:0] sack_bitmap,
    output wire [1:0] sack_status
);
    generate if (QPS>=1 && QPS<=8) begin : g_legal
        localparam IDLE=0, DIFFERENCE=1, CLASSIFY=2, DECISION=3,
                   COMMIT=4, RETIRE=5, SNAPSHOT=6, OUTPUT=7;
        reg [2:0] state;
        reg [QPS-1:0] enabled;
        reg [23:0] bases [0:QPS-1];
        reg [255:0] bitmap [0:QPS-1];
        reg cfg_pending;
        reg [1:0] cfg_status;
        reg [2:0] qp;
        reg [23:0] psn, base_hold, delta;
        reg present;
        reg [1:0] classification, snapshot_status;
        reg [7:0] cursor;
        reg [23:0] snapshot_base;
        reg [255:0] snapshot_bits;
        wire [7:0] physical_sample=snapshot_base[7:0]+cursor;
        assign cfg_ready=rst_n && state==IDLE && !cfg_pending;
        assign cfg_rsp_valid=rst_n && cfg_pending;
        assign cfg_rsp_status=rst_n ? cfg_status : 2'b0;
        assign req_ready=rst_n && state==IDLE && !cfg_pending && !cfg_valid;
        assign decision_valid=rst_n && state==DECISION;
        assign decision_qp=rst_n ? qp : 3'b0;
        assign decision_psn=rst_n ? psn : 24'b0;
        assign decision_status=rst_n ? classification : 2'b0;
        assign commit_ready=rst_n && state==COMMIT;
        assign sack_valid=rst_n && state==OUTPUT;
        assign sack_qp=rst_n ? qp : 3'b0;
        assign sack_base=rst_n ? snapshot_base : 24'b0;
        assign sack_bitmap=rst_n ? snapshot_bits : 256'b0;
        assign sack_status=rst_n ? snapshot_status : 2'b0;
        integer i;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; enabled<=0; cfg_pending<=0; cfg_status<=0;
                qp<=0; psn<=0; base_hold<=0; delta<=0; present<=0;
                classification<=0; snapshot_status<=0; cursor<=0;
                snapshot_base<=0; snapshot_bits<=0;
                for (i=0;i<QPS;i=i+1) begin bases[i]<=0; bitmap[i]<=0; end
            end else begin
                if (cfg_pending && cfg_rsp_ready) cfg_pending<=0;
                if (cfg_valid && cfg_ready) begin
                    cfg_pending<=1;
                    if (cfg_index>=QPS) cfg_status<=1;
                    else begin
                        cfg_status<=0; enabled[cfg_index]<=cfg_enable;
                        bases[cfg_index]<=cfg_base; bitmap[cfg_index]<=0;
                    end
                end
                case (state)
                    IDLE: if (req_valid && req_ready) begin
                        qp<=req_qp; psn<=req_psn;
                        if (req_qp<QPS) begin
                            base_hold<=bases[req_qp]; present<=enabled[req_qp];
                        end else begin base_hold<=0; present<=0; end
                        state<=DIFFERENCE;
                    end
                    DIFFERENCE: begin delta<=psn-base_hold; state<=CLASSIFY; end
                    CLASSIFY: begin
                        if (!present) classification<=3;
                        else if (delta[23]) classification<=1;
                        else if (delta>=24'd256) classification<=2;
                        else if (bitmap[qp][psn[7:0]]) classification<=1;
                        else classification<=0;
                        state<=DECISION;
                    end
                    DECISION: if (decision_ready) begin
                        if (classification==0) state<=COMMIT;
                        else begin
                            snapshot_status<=classification;
                            snapshot_base<=present ? base_hold : 24'b0;
                            snapshot_bits<=0; cursor<=0; state<=SNAPSHOT;
                        end
                    end
                    COMMIT: if (commit_valid) begin
                        snapshot_bits<=0; cursor<=0;
                        if (commit_ok) begin
                            bitmap[qp][psn[7:0]]<=1;
                            snapshot_status<=0; state<=RETIRE;
                        end else begin
                            snapshot_status<=3; snapshot_base<=base_hold;
                            state<=SNAPSHOT;
                        end
                    end
                    RETIRE: begin
                        if (bitmap[qp][bases[qp][7:0]]) begin
                            bitmap[qp][bases[qp][7:0]]<=0;
                            bases[qp]<=bases[qp]+24'd1;
                        end else begin
                            snapshot_base<=bases[qp]; state<=SNAPSHOT;
                        end
                    end
                    SNAPSHOT: begin
                        if (present) snapshot_bits[cursor]<=bitmap[qp][physical_sample];
                        else snapshot_bits[cursor]<=0;
                        if (cursor==8'd255) state<=OUTPUT;
                        else cursor<=cursor+1'b1;
                    end
                    OUTPUT: if (sack_ready) state<=IDLE;
                    default: state<=IDLE;
                endcase
            end
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: reorder QPS=1..8 required");
        assign cfg_ready=0; assign cfg_rsp_valid=0; assign cfg_rsp_status=0;
        assign req_ready=0; assign decision_valid=0; assign decision_qp=0;
        assign decision_psn=0; assign decision_status=0; assign commit_ready=0;
        assign sack_valid=0; assign sack_qp=0; assign sack_base=0;
        assign sack_bitmap=0; assign sack_status=0;
    end endgenerate
endmodule
`default_nettype wire
