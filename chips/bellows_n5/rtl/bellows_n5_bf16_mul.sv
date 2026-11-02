`default_nettype none
module bellows_n5_bf16_mul (
    input wire clk, rst_n,
    input wire in_valid,
    output wire in_ready,
    input wire [15:0] a, b,
    output wire out_valid,
    input wire out_ready,
    output wire [15:0] result
);
    reg [7:0] valid_pipe;
    wire advance=rst_n && (!valid_pipe[7] || out_ready);
    assign in_ready=advance;
    assign out_valid=rst_n && valid_pipe[7];
    reg [7:0] ma1, mb1;
    reg [7:0] ea1, eb1;
    reg sign1, special1;
    reg [15:0] selected1;
    reg [15:0] product2, product3, product4;
    reg signed [10:0] scale2, scale3;
    reg [3:0] leading3;
    reg signed [10:0] shift4;
    reg [8:0] exponent4, exponent5, exponent6;
    reg [16:0] retained5, rounded6;
    reg guard5, sticky5;
    reg sign2, sign3, sign4, sign5, sign6;
    reg special2, special3, special4, special5, special6;
    reg [15:0] selected2, selected3, selected4, selected5, selected6;
    reg [15:0] packed7, result8;
    wire nan_a=(&a[14:7]) && (|a[6:0]);
    wire nan_b=(&b[14:7]) && (|b[6:0]);
    wire inf_a=(&a[14:7]) && !(|a[6:0]);
    wire inf_b=(&b[14:7]) && !(|b[6:0]);
    wire zero_a=!(|a[14:0]);
    wire zero_b=!(|b[14:0]);
    wire invalid=nan_a || nan_b || (inf_a && zero_b) || (inf_b && zero_a);
    wire special_next=invalid || inf_a || inf_b || zero_a || zero_b;
    wire [15:0] selected_next=invalid ? 16'h7fc0 :
        (inf_a || inf_b) ? {a[15]^b[15],8'hff,7'b0} :
                          {a[15]^b[15],15'b0};

    reg [3:0] leading_next;
    reg [15:0] leading_tree;
    always @* begin
        leading_tree=product2; leading_next=0;
        if (|leading_tree[15:8]) begin leading_tree=leading_tree>>8; leading_next=8; end
        if (|leading_tree[7:4]) begin leading_tree=leading_tree>>4; leading_next=leading_next+4; end
        if (|leading_tree[3:2]) begin leading_tree=leading_tree>>2; leading_next=leading_next+2; end
        if (leading_tree[1]) leading_next=leading_next+1'b1;
    end
    wire signed [10:0] exponent_next=scale3+$signed({7'b0,leading3})+11'sd127;
    wire signed [10:0] shift_next=(exponent_next>0) ?
        ($signed({7'b0,leading3})-11'sd7) : (-scale3-11'sd133);
    reg [16:0] retained_next;
    reg guard_next, sticky_next;
    integer j;
    always @* begin
        retained_next=0; guard_next=0; sticky_next=0;
        if (shift4<=0) retained_next={1'b0,product4}<<(-shift4);
        else begin
            if (shift4<16) retained_next={1'b0,product4}>>shift4;
            if (shift4<=16) guard_next=product4[shift4-1'b1];
            for (j=0;j<16;j=j+1)
                if (j<shift4-1) sticky_next=sticky_next|product4[j];
        end
    end
    wire [16:0] rounded_next=retained5+
        {16'b0,(guard5 && (sticky5 || retained5[0]))};
    wire carry6=(exponent6!=0) && rounded6[8];
    wire [9:0] final_exponent={1'b0,exponent6}+{9'b0,carry6};
    reg [15:0] packed_next;
    always @* begin
        if (special6) packed_next=selected6;
        else if (final_exponent>=255) packed_next={sign6,8'hff,7'b0};
        else if (exponent6==0)
            packed_next={sign6,7'b0,rounded6[7:0]};
        else packed_next={sign6,final_exponent[7:0],
                          (carry6 ? rounded6[7:1] : rounded6[6:0])};
    end
    assign result=(rst_n && valid_pipe[7]) ? result8 : 16'b0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_pipe<=0; ma1<=0; mb1<=0; ea1<=0; eb1<=0;
            sign1<=0; special1<=0; selected1<=0;
            product2<=0; product3<=0; product4<=0;
            scale2<=0; scale3<=0; leading3<=0; shift4<=0;
            exponent4<=0; exponent5<=0; exponent6<=0;
            retained5<=0; rounded6<=0; guard5<=0; sticky5<=0;
            sign2<=0; sign3<=0; sign4<=0; sign5<=0; sign6<=0;
            special2<=0; special3<=0; special4<=0; special5<=0; special6<=0;
            selected2<=0; selected3<=0; selected4<=0; selected5<=0; selected6<=0;
            packed7<=0; result8<=0;
        end else if (advance) begin
            valid_pipe<={valid_pipe[6:0],in_valid};
            ma1<={|a[14:7],a[6:0]}; mb1<={|b[14:7],b[6:0]};
            ea1<=(a[14:7]==0) ? 8'd1 : a[14:7];
            eb1<=(b[14:7]==0) ? 8'd1 : b[14:7];
            sign1<=a[15]^b[15]; special1<=special_next; selected1<=selected_next;
            product2<=ma1*mb1;
            scale2<=$signed({3'b0,ea1})+$signed({3'b0,eb1})-11'sd268;
            sign2<=sign1; special2<=special1; selected2<=selected1;
            product3<=product2; scale3<=scale2; leading3<=leading_next;
            sign3<=sign2; special3<=special2; selected3<=selected2;
            product4<=product3; shift4<=shift_next;
            exponent4<=(exponent_next>0) ? exponent_next[8:0] : 9'b0;
            sign4<=sign3; special4<=special3; selected4<=selected3;
            retained5<=retained_next; guard5<=guard_next; sticky5<=sticky_next;
            exponent5<=exponent4; sign5<=sign4; special5<=special4; selected5<=selected4;
            rounded6<=rounded_next; exponent6<=exponent5;
            sign6<=sign5; special6<=special5; selected6<=selected5;
            packed7<=packed_next;
            result8<=packed7;
        end
    end
endmodule
`default_nettype wire
