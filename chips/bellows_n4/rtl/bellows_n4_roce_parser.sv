`default_nettype none
module furnace_roce_parser (
    input wire clk, rst_n,
    input wire start_valid,
    output wire start_ready,
    input wire [13:0] frame_bytes,
    input wire frame_bad,
    output wire mem_req,
    output wire [13:0] mem_addr,
    input wire [7:0] mem_data,
    output wire result_valid,
    input wire result_ready,
    output reg [3:0] status,
    output reg trusted,
    output reg [7:0] opcode,
    output reg [23:0] qpn, psn,
    output reg [63:0] address,
    output reg [31:0] rkey, message_bytes,
    output reg [13:0] payload_start, payload_bytes
);
    localparam IDLE=0, REQUEST=1, CONSUME=2, FINISH=3, RESULT=4;
    reg [2:0] state;
    reg [13:0] size, index;
    reg malformed, unsupported, bypass;
    reg [1:0] tags, version;
    reg [15:0] ether_type;
    reg [13:0] type_end, ip_start, udp_start, bth_start;
    reg [16:0] ip_end, udp_end;
    reg [7:0] ip_header_bytes;
    reg [15:0] ip_length, udp_length, destination_port;
    reg [7:0] high_byte, protocol;
    reg [17:0] checksum;
    reg [1:0] pad;
    reg [31:0] crc, received_crc;
    reg bth_seen, bth_bad;
    wire [16:0] pos={3'b0,index};
    wire [16:0] ip_rel=pos-{3'b0,ip_start};
    wire [16:0] udp_rel=pos-{3'b0,udp_start};
    wire [16:0] bth_rel=pos-{3'b0,bth_start};

    function automatic [31:0] crc_byte;
        input [31:0] previous;
        input [7:0] octet;
        reg [31:0] work;
        integer bit_index;
        begin
            work=previous^{24'b0,octet};
            for (bit_index=0;bit_index<8;bit_index=bit_index+1)
                work=work[0] ? ((work>>1)^32'hedb88320) : (work>>1);
            crc_byte=work;
        end
    endfunction
    function automatic [31:0] virtual_prefix;
        input unused;
        reg [31:0] work;
        integer octet_index;
        begin
            work=32'hffffffff;
            for (octet_index=0;octet_index<8;octet_index=octet_index+1)
                work=crc_byte(work,8'hff);
            virtual_prefix=work;
        end
    endfunction
    reg [7:0] invariant_byte;
    always @* begin
        invariant_byte=mem_data;
        if (version==1 && (ip_rel==1 || ip_rel==8 || ip_rel==10 || ip_rel==11))
            invariant_byte=8'hff;
        if (version==2) begin
            if (ip_rel==0) invariant_byte=mem_data|8'h0f;
            if (ip_rel==1 || ip_rel==2 || ip_rel==3 || ip_rel==7)
                invariant_byte=8'hff;
        end
        if (udp_start!=0 && (udp_rel==6 || udp_rel==7)) invariant_byte=8'hff;
        if (bth_start!=0 && bth_rel==4) invariant_byte=8'hff;
    end
    wire [31:0] crc_next=crc_byte(crc,invariant_byte);
    wire [17:0] checksum_add={2'b0,high_byte,mem_data}+checksum;
    wire [16:0] checksum_fold={1'b0,checksum[15:0]}+{15'b0,checksum[17:16]};
    wire [16:0] checksum_final={1'b0,checksum_fold[15:0]}+{16'b0,checksum_fold[16]};
    wire supported_write=opcode==8'h06 || opcode==8'h07 ||
                         opcode==8'h08 || opcode==8'h09 ||
                         opcode==8'h0a || opcode==8'h0b;
    wire has_reth=opcode==8'h06 || opcode==8'h0a || opcode==8'h0b;
    wire has_immediate=opcode==8'h09 || opcode==8'h0b;
    wire [16:0] header_end={3'b0,bth_start}+17'd12+
                         (has_reth ? 17'd16 : 17'd0)+
                         (has_immediate ? 17'd4 : 17'd0);
    wire [16:0] data_end=udp_end-17'd4-{15'b0,pad};
    assign start_ready=rst_n && state==IDLE;
    assign mem_req=rst_n && state==REQUEST;
    assign mem_addr=rst_n ? index : 14'b0;
    assign result_valid=rst_n && state==RESULT;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; size<=0; index<=0;
            malformed<=0; unsupported<=0; bypass<=0; tags<=0; version<=0;
            ether_type<=0; type_end<=0; ip_start<=0; udp_start<=0; bth_start<=0;
            ip_end<=0; udp_end<=0; ip_header_bytes<=0; ip_length<=0;
            udp_length<=0; destination_port<=0; high_byte<=0; protocol<=0;
            checksum<=0; pad<=0; crc<=0; received_crc<=0;
            bth_seen<=0; bth_bad<=0; status<=0; trusted<=0;
            opcode<=0; qpn<=0; psn<=0; address<=0; rkey<=0;
            message_bytes<=0; payload_start<=0; payload_bytes<=0;
        end else begin
            case (state)
                IDLE: if (start_valid && start_ready) begin
                    size<=frame_bytes; index<=0; malformed<=frame_bad;
                    unsupported<=0; bypass<=0; tags<=0; version<=0;
                    ether_type<=0; type_end<=13; ip_start<=0; udp_start<=0;
                    bth_start<=0; ip_end<=0; udp_end<=0; ip_header_bytes<=0;
                    ip_length<=0; udp_length<=0; destination_port<=0;
                    high_byte<=0; protocol<=0; checksum<=0; pad<=0;
                    crc<=virtual_prefix(1'b0); received_crc<=0;
                    bth_seen<=0; bth_bad<=0; status<=0; trusted<=0;
                    opcode<=0; qpn<=0; psn<=0; address<=0; rkey<=0;
                    message_bytes<=0; payload_start<=0; payload_bytes<=0;
                    if (frame_bytes<14 || frame_bad) begin
                        malformed<=1; state<=FINISH;
                    end else state<=REQUEST;
                end
                REQUEST: state<=CONSUME;
                CONSUME: begin
                    if (index+14'd1>=size) state<=FINISH;
                    else begin index<=index+1'b1; state<=REQUEST; end
                    if (index+14'd1==type_end) high_byte<=mem_data;
                    if (index==type_end) begin
                        ether_type<={high_byte,mem_data};
                        if ({high_byte,mem_data}==16'h8100 ||
                            {high_byte,mem_data}==16'h88a8) begin
                            if (tags==2) begin unsupported<=1; bypass<=1; end
                            else begin tags<=tags+1'b1; type_end<=type_end+14'd4; end
                        end else begin
                            ip_start<=index+1'b1;
                            if ({high_byte,mem_data}==16'h0800) version<=1;
                            else if ({high_byte,mem_data}==16'h86dd) begin
                                version<=2; ip_header_bytes<=40;
                                udp_start<=index+14'd41;
                            end else begin bypass<=1; state<=FINISH; end
                        end
                    end
                    if (version!=0 && index>=ip_start) begin
                        if (ip_end==0 || pos<ip_end-17'd4) crc<=crc_next;
                        if (ip_end!=0 && pos==ip_end-17'd4) received_crc[7:0]<=mem_data;
                        if (ip_end!=0 && pos==ip_end-17'd3) received_crc[15:8]<=mem_data;
                        if (ip_end!=0 && pos==ip_end-17'd2) received_crc[23:16]<=mem_data;
                        if (ip_end!=0 && pos==ip_end-17'd1) received_crc[31:24]<=mem_data;
                        if (version==1) begin
                            if (ip_rel==0) begin
                                if (mem_data[7:4]!=4 || mem_data[3:0]<5) malformed<=1;
                                ip_header_bytes<={2'b0,mem_data[3:0],2'b0};
                                udp_start<=ip_start+{8'b0,mem_data[3:0],2'b0};
                            end
                            if (ip_rel<ip_header_bytes || ip_rel==0) begin
                                if (!ip_rel[0]) high_byte<=mem_data;
                                else checksum<=checksum_add;
                            end
                            if (ip_rel==2) high_byte<=mem_data;
                            if (ip_rel==3) begin
                                ip_length<={high_byte,mem_data};
                                ip_end<={3'b0,ip_start}+{1'b0,high_byte,mem_data};
                            end
                            if (ip_rel==6 && (mem_data & 8'hbf)!=0) unsupported<=1;
                            if (ip_rel==7 && mem_data!=0) unsupported<=1;
                            if (ip_rel==9) begin
                                protocol<=mem_data;
                                if (mem_data!=17) bypass<=1;
                            end
                        end else begin
                            if (ip_rel==0 && mem_data[7:4]!=6) malformed<=1;
                            if (ip_rel==4) high_byte<=mem_data;
                            if (ip_rel==5) begin
                                ip_length<={high_byte,mem_data};
                                ip_end<={3'b0,ip_start}+17'd40+{1'b0,high_byte,mem_data};
                            end
                            if (ip_rel==6) begin
                                protocol<=mem_data;
                                if (mem_data!=17) begin
                                    if (mem_data==0 || mem_data==43 || mem_data==44 ||
                                        mem_data==60 || mem_data==51) unsupported<=1;
                                    else bypass<=1;
                                end
                            end
                        end
                        if (udp_start!=0 && index>=udp_start && protocol==17) begin
                            if (udp_rel==2 || udp_rel==4) high_byte<=mem_data;
                            if (udp_rel==3) begin
                                destination_port<={high_byte,mem_data};
                                if ({high_byte,mem_data}!=16'd4791) bypass<=1;
                            end
                            if (udp_rel==5) begin
                                udp_length<={high_byte,mem_data};
                                udp_end<={3'b0,udp_start}+{1'b0,high_byte,mem_data};
                                bth_start<=udp_start+14'd8;
                            end
                        end
                        if (bth_start!=0 && index>=bth_start && pos<udp_end-17'd4 &&
                            destination_port==4791 && protocol==17) begin
                            if (bth_rel==0) begin opcode<=mem_data; bth_seen<=1; end
                            if (bth_rel==1) begin
                                pad<=mem_data[5:4];
                                if (mem_data[3:0]!=0) bth_bad<=1;
                            end
                            if ((bth_rel==2 || bth_rel==3) && mem_data!=8'hff) bth_bad<=1;
                            if (bth_rel==4 && mem_data!=0) bth_bad<=1;
                            if (bth_rel>=5 && bth_rel<=7) qpn<={qpn[15:0],mem_data};
                            if (bth_rel==8 && mem_data[6:0]!=0) bth_bad<=1;
                            if (bth_rel>=9 && bth_rel<=11) psn<={psn[15:0],mem_data};
                            if (has_reth) begin
                                if (bth_rel>=12 && bth_rel<=19) address<={address[55:0],mem_data};
                                if (bth_rel>=20 && bth_rel<=23) rkey<={rkey[23:0],mem_data};
                                if (bth_rel>=24 && bth_rel<=27)
                                    message_bytes<={message_bytes[23:0],mem_data};
                            end
                        end
                    end
                end
                FINISH: begin
                    trusted<=0;
                    payload_start<=0; payload_bytes<=0;
                    if (malformed || size<14 ||
                        (version!=0 && (ip_end>{3'b0,size} ||
                         ip_end<({3'b0,ip_start}+{9'b0,ip_header_bytes})))) status<=3;
                    else if (bypass) status<=2;
                    else if (unsupported) status<=4;
                    else if (version==0 || udp_length<24 || udp_end!=ip_end ||
                             protocol!=17 || !bth_seen || bth_bad ||
                             (version==1 && checksum_final!=17'h0ffff) ||
                             header_end>data_end || data_end>ip_end ||
                             (opcode==8'h11 &&
                              udp_end!=({3'b0,bth_start}+17'd20))) status<=3;
                    else if (received_crc!=~crc) status<=9;
                    else begin
                        trusted<=1;
                        if (opcode==8'h11) status<=10;
                        else if (!supported_write) status<=4;
                        else begin
                            status<=0;
                            payload_start<=header_end[13:0];
                            payload_bytes<=data_end[13:0]-header_end[13:0];
                        end
                    end
                    if (!bth_seen) begin qpn<=0; psn<=0; address<=0; end
                    state<=RESULT;
                end
                RESULT: if (result_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
