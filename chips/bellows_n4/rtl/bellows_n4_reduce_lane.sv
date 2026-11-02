`default_nettype none
module furnace_reduce_lane #(
    parameter integer HALF = 0
) (
    input wire clk, rst_n, advance,
    input wire [31:0] a, b,
    input wire active, integer_mode,
    input wire [1:0] op,
    output reg [31:0] result
);
    reg [31:0] a1, b1;
    reg [7:0] ea1, eb1;
    reg [23:0] ma1, mb1;
    reg active1, int1;
    reg [1:0] op1;
    wire [31:0] ua = HALF ? {a[15:0],16'b0} : a;
    wire [31:0] ub = HALF ? {b[15:0],16'b0} : b;

    reg [26:0] big2, small2;
    reg [7:0] exponent2, distance2;
    reg sign2, subtract2, bypass2;
    reg [31:0] selected2;
    reg [15:0] ia2, ib2;
    reg int2;
    reg select2, choose_a2;
    reg [31:0] operand_a2, operand_b2;
    reg [1:0] op2;
    reg [26:0] big3, aligned3;
    reg [7:0] exponent3;
    reg sign3, subtract3, bypass3, int3;
    reg [31:0] selected3;
    reg [15:0] ia3, ib3;
    reg [1:0] op3;
    reg select3, choose_a3;
    reg [31:0] operand_a3, operand_b3;
    reg [27:0] sum4;
    reg [7:0] exponent4;
    reg sign4, bypass4;
    reg [31:0] selected4;
    reg [27:0] sum5;
    reg [7:0] exponent5;
    reg [4:0] shift5;
    reg sign5, bypass5;
    reg [31:0] selected5;
    reg [26:0] normalized6;
    reg [8:0] exponent6;
    reg sign6, bypass6;
    reg [31:0] selected6;
    reg [31:0] packed7;

    wire nan_a = (&a1[30:23]) && (|a1[22:0]);
    wire nan_b = (&b1[30:23]) && (|b1[22:0]);
    wire inf_a = (&a1[30:23]) && !(|a1[22:0]);
    wire inf_b = (&b1[30:23]) && !(|b1[22:0]);
    wire zero_a = !(|a1[30:0]);
    wire zero_b = !(|b1[30:0]);
    wire mag_a_ge = a1[30:0] >= b1[30:0];
    wire a_less = (a1[31] != b1[31]) ? a1[31] :
                  (a1[31] ? a1[30:0] > b1[30:0] :
                            a1[30:0] < b1[30:0]);
    reg [31:0] selected_next;
    reg bypass_next, select_next, choose_a_next;
    always @* begin
        selected_next=0;
        bypass_next=0;
        select_next=0; choose_a_next=1;
        if (!active1) begin
            bypass_next=1;
        end else if (int1) begin
            bypass_next=1;
            if (op1!=0) begin
                select_next=1;
                if (a1[15:0]==b1[15:0]) choose_a_next=1;
                else if (op1==1)
                    choose_a_next=$signed(a1[15:0])>$signed(b1[15:0]);
                else choose_a_next=$signed(a1[15:0])<$signed(b1[15:0]);
            end
        end else if (op1!=0) begin
            bypass_next=1;
            if (nan_a && nan_b) selected_next=32'h7fc00000;
            else if (nan_a) begin select_next=1; choose_a_next=0; end
            else if (nan_b) begin select_next=1; choose_a_next=1; end
            else if (zero_a && zero_b)
                selected_next={(op1==2 ? (a1[31]|b1[31]) :
                                                       (a1[31]&b1[31])),31'b0};
            else begin
                select_next=1;
                if (a1==b1) choose_a_next=1;
                else if (op1==1) choose_a_next=!a_less;
                else choose_a_next=a_less;
            end
        end else if (nan_a || nan_b ||
                     (inf_a && inf_b && a1[31]!=b1[31])) begin
            bypass_next=1; selected_next=32'h7fc00000;
        end else if (inf_a || inf_b) begin
            bypass_next=1; selected_next=inf_a ? a1 : b1;
        end else if (zero_a && zero_b) begin
            bypass_next=1; selected_next={a1[31]&b1[31],31'b0};
        end
    end

    function automatic [26:0] shift_jam;
        input [26:0] value;
        input [7:0] amount;
        reg [26:0] shifted;
        reg lost;
        integer j;
        begin
            shifted=0; lost=0;
            if (amount>=27) begin
                shifted=0; lost=|value;
            end else begin
                shifted=value>>amount;
                for (j=0;j<27;j=j+1)
                    if (j<amount) lost=lost|value[j];
            end
            shift_jam=shifted|{26'b0,lost};
        end
    endfunction

    function automatic [4:0] leading_shift;
        input [26:0] value;
        reg [31:0] tree;
        reg [4:0] count;
        begin
            tree={value,5'b0}; count=0;
            if (tree[31:16]==0) begin tree=tree<<16; count=count+16; end
            if (tree[31:24]==0) begin tree=tree<<8; count=count+8; end
            if (tree[31:28]==0) begin tree=tree<<4; count=count+4; end
            if (tree[31:30]==0) begin tree=tree<<2; count=count+2; end
            if (!tree[31]) count=count+1'b1;
            leading_shift=(value==0) ? 5'd26 : count;
        end
    endfunction

    wire [26:0] alignment_next=shift_jam(small2,distance2);
    wire [27:0] arithmetic_next=subtract3 ?
              ({1'b0,big3}-{1'b0,aligned3}) :
              ({1'b0,big3}+{1'b0,aligned3});
    wire [15:0] integer_sum=ia3+ib3;
    wire [4:0] leading_next=leading_shift(sum4[26:0]);
    wire [7:0] max_left=exponent5-1'b1;
    wire [4:0] left_amount=(max_left<{3'b0,shift5}) ? max_left[4:0] : shift5;
    wire [26:0] normalize_next=sum5[27] ?
             (sum5[27:1]|{26'b0,sum5[0]}) : (sum5[26:0]<<left_amount);
    wire [8:0] normalize_exp=sum5[27] ? ({1'b0,exponent5}+9'd1) :
                                      ({1'b0,exponent5}-{4'b0,left_amount});
    wire round_up=HALF ?
         (normalized6[18] && ((|normalized6[17:0]) || normalized6[19])) :
         (normalized6[2] && ((|normalized6[1:0]) || normalized6[3]));
    wire [24:0] rounded=HALF ?
         ({17'b0,normalized6[26:19]}+{{24{1'b0}},round_up}) :
         ({1'b0,normalized6[26:3]}+{{24{1'b0}},round_up});
    wire carry_round=HALF ? rounded[8] : rounded[24];
    wire [8:0] rounded_exp=exponent6+{8'b0,carry_round};
    wire [23:0] rounded_mant=HALF ?
             { (carry_round ? rounded[8:1] : rounded[7:0]),16'b0 } :
             (carry_round ? rounded[24:1] : rounded[23:0]);
    reg [31:0] rounded_next;
    always @* begin
        if (bypass6) rounded_next=selected6;
        else if (normalized6==0) rounded_next=0;
        else if (rounded_exp>=255) rounded_next={sign6,8'hff,23'b0};
        else if (!rounded_mant[23])
            rounded_next={sign6,8'b0,rounded_mant[22:0]};
        else rounded_next={sign6,rounded_exp[7:0],rounded_mant[22:0]};
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a1<=0; b1<=0; ea1<=0; eb1<=0; ma1<=0; mb1<=0;
            active1<=0; int1<=0; op1<=0;
            big2<=0; small2<=0; exponent2<=0; distance2<=0;
            sign2<=0; subtract2<=0; bypass2<=0; selected2<=0;
            ia2<=0; ib2<=0; int2<=0; op2<=0;
            select2<=0; choose_a2<=0; operand_a2<=0; operand_b2<=0;
            big3<=0; aligned3<=0; exponent3<=0; sign3<=0;
            subtract3<=0; bypass3<=0; selected3<=0;
            ia3<=0; ib3<=0; int3<=0; op3<=0;
            select3<=0; choose_a3<=0; operand_a3<=0; operand_b3<=0;
            sum4<=0; exponent4<=0; sign4<=0; bypass4<=0; selected4<=0;
            sum5<=0; exponent5<=0; shift5<=0; sign5<=0;
            bypass5<=0; selected5<=0;
            normalized6<=0; exponent6<=0; sign6<=0;
            bypass6<=0; selected6<=0; packed7<=0; result<=0;
        end else if (advance) begin
            a1<=integer_mode ? a : ua; b1<=integer_mode ? b : ub;
            ea1<=(ua[30:23]==0) ? 8'd1 : ua[30:23];
            eb1<=(ub[30:23]==0) ? 8'd1 : ub[30:23];
            ma1<={|ua[30:23],ua[22:0]}; mb1<={|ub[30:23],ub[22:0]};
            active1<=active; int1<=integer_mode; op1<=op;

            big2<=mag_a_ge ? {ma1,3'b0} : {mb1,3'b0};
            small2<=mag_a_ge ? {mb1,3'b0} : {ma1,3'b0};
            exponent2<=mag_a_ge ? ea1 : eb1;
            distance2<=mag_a_ge ? (ea1-eb1) : (eb1-ea1);
            sign2<=mag_a_ge ? a1[31] : b1[31];
            subtract2<=a1[31]^b1[31];
            bypass2<=bypass_next; selected2<=selected_next;
            ia2<=a1[15:0]; ib2<=b1[15:0]; int2<=int1 && active1; op2<=op1;
            select2<=select_next; choose_a2<=choose_a_next;
            operand_a2<=a1; operand_b2<=b1;

            big3<=big2; aligned3<=alignment_next; exponent3<=exponent2;
            sign3<=sign2; subtract3<=subtract2; bypass3<=bypass2;
            selected3<=selected2; ia3<=ia2; ib3<=ib2; int3<=int2; op3<=op2;
            select3<=select2; choose_a3<=choose_a2;
            operand_a3<=operand_a2; operand_b3<=operand_b2;

            sum4<=arithmetic_next; exponent4<=exponent3;
            sign4<=sign3; bypass4<=bypass3;
            selected4<=(int3 && op3==0) ? {16'b0,integer_sum} :
                       select3 ? (choose_a3 ? operand_a3 : operand_b3) : selected3;

            sum5<=sum4; exponent5<=exponent4; shift5<=leading_next;
            sign5<=sign4; bypass5<=bypass4; selected5<=selected4;

            normalized6<=normalize_next; exponent6<=normalize_exp;
            sign6<=sign5; bypass6<=bypass5; selected6<=selected5;

            packed7<=rounded_next;
            result<=packed7;
        end
    end
endmodule
`default_nettype wire
