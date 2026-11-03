`default_nettype none
module bellows_n5_topk #(
    parameter integer EXPERTS=8,
    parameter integer MAX_K=4
) (
    input wire clk, rst_n,
    input wire in_valid,
    output wire in_ready,
    input wire [16*((EXPERTS>0)?EXPERTS:1)-1:0] scores,
    input wire [((EXPERTS>0)?EXPERTS:1)-1:0] enabled,
    input wire [2:0] k,
    output wire out_valid,
    input wire out_ready,
    output wire [16*((MAX_K>0)?MAX_K:1)-1:0] ids
);
    generate if (EXPERTS>=1 && EXPERTS<=16 &&
                 MAX_K>=1 && MAX_K<=4 && MAX_K<=EXPERTS) begin : g_legal
        localparam IDLE=0, SCAN=1, COMMIT=2, OUTPUT=3;
        reg [1:0] state;
        reg [16*EXPERTS-1:0] held_scores;
        reg [EXPERTS-1:0] eligible;
        reg [2:0] count, rank;
        reg [4:0] cursor;
        reg best_valid;
        reg signed [15:0] best_score;
        reg [15:0] best_id;
        reg [16*MAX_K-1:0] selected;
        wire signed [15:0] candidate=held_scores[16*cursor +:16];
        assign in_ready=rst_n && state==IDLE;
        assign out_valid=rst_n && state==OUTPUT;
        assign ids=rst_n ? selected : {16*MAX_K{1'b0}};
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                state<=IDLE; held_scores<=0; eligible<=0;
                count<=0; rank<=0; cursor<=0; best_valid<=0;
                best_score<=0; best_id<=0; selected<=0;
            end else begin
                case (state)
                    IDLE: if (in_valid) begin
                        held_scores<=scores; eligible<=enabled; count<=k;
                        selected<=0; rank<=0; cursor<=0; best_valid<=0;
                        best_score<=0; best_id<=0; state<=SCAN;
                    end
                    SCAN: begin
                        if (eligible[cursor] &&
                            (!best_valid || candidate>best_score)) begin
                            best_valid<=1; best_score<=candidate;
                            best_id<={11'b0,cursor};
                        end
                        if (cursor==EXPERTS-1) state<=COMMIT;
                        else cursor<=cursor+1'b1;
                    end
                    COMMIT: begin
                        selected[16*rank +:16]<=best_id;
                        eligible[best_id]<=0;
                        if (rank+3'd1==count) state<=OUTPUT;
                        else begin
                            rank<=rank+1'b1; cursor<=0;
                            best_valid<=0; best_score<=0; best_id<=0;
                            state<=SCAN;
                        end
                    end
                    OUTPUT: if (out_ready) state<=IDLE;
                    default: state<=IDLE;
                endcase
            end
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: EXPERTS=1..16, MAX_K=1..min(4,EXPERTS)");
        assign in_ready=0; assign out_valid=0; assign ids=0;
    end endgenerate
endmodule
`default_nettype wire
