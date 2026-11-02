`default_nettype none
module bellows_n5_qp_table #(
    parameter integer QPS=8
) (
    input wire clk, rst_n, idle_allow,
    input wire cfg_valid,
    output wire cfg_ready,
    input wire [2:0] cfg_index,
    input wire cfg_enable,
    input wire [23:0] cfg_local_qpn, cfg_remote_qpn, cfg_rx_psn, cfg_tx_psn,
    input wire [31:0] cfg_rkey,
    input wire [63:0] cfg_base, cfg_length,
    input wire [47:0] cfg_local_mac, cfg_remote_mac,
    input wire [31:0] cfg_local_ip, cfg_remote_ip,
    input wire [7:0] route_qps,
    output wire cfg_rsp_valid,
    input wire cfg_rsp_ready,
    output wire [2:0] cfg_rsp_status,
    output wire cfg_commit,
    input wire tx_advance,
    input wire [2:0] tx_qp,
    output wire [7:0] enabled,
    output wire [191:0] local_qpns, remote_qpns, rx_psns, tx_psns,
    output wire [255:0] rkeys, local_ips, remote_ips,
    output wire [511:0] bases, lengths,
    output wire [383:0] local_macs, remote_macs
);
    generate if (QPS>=1 && QPS<=8) begin : g_legal
        reg [QPS-1:0] enable_bits;
        reg [23:0] local_qpn [0:QPS-1], remote_qpn [0:QPS-1];
        reg [23:0] rx_psn [0:QPS-1], tx_psn [0:QPS-1];
        reg [31:0] rkey [0:QPS-1], local_ip [0:QPS-1], remote_ip [0:QPS-1];
        reg [63:0] base [0:QPS-1], length [0:QPS-1];
        reg [47:0] local_mac [0:QPS-1], remote_mac [0:QPS-1];
        reg pending;
        reg [2:0] status;
        reg duplicate;
        reg [2:0] check_status;
        wire [64:0] region_end={1'b0,cfg_base}+{1'b0,cfg_length};
        integer c;
        always @* begin
            duplicate=0;
            for (c=0;c<QPS;c=c+1)
                if (enable_bits[c] && c!=cfg_index && local_qpn[c]==cfg_local_qpn)
                    duplicate=1;
            check_status=0;
            if (cfg_index>=QPS || (cfg_enable && duplicate)) check_status=1;
            else if (cfg_enable && (cfg_length==0 || region_end[64])) check_status=2;
            else if (!cfg_enable && route_qps[cfg_index]) check_status=3;
        end
        assign cfg_ready=rst_n && idle_allow && !pending;
        assign cfg_rsp_valid=rst_n && pending;
        assign cfg_rsp_status=rst_n ? status : 3'b0;
        assign cfg_commit=cfg_valid && cfg_ready && check_status==0;
        genvar q;
        for (q=0;q<8;q=q+1) begin : g_export
            if (q<QPS) begin : g_present
                assign enabled[q]=rst_n && enable_bits[q];
                assign local_qpns[24*q +:24]=rst_n ? local_qpn[q] : 24'b0;
                assign remote_qpns[24*q +:24]=rst_n ? remote_qpn[q] : 24'b0;
                assign rx_psns[24*q +:24]=rst_n ? rx_psn[q] : 24'b0;
                assign tx_psns[24*q +:24]=rst_n ? tx_psn[q] : 24'b0;
                assign rkeys[32*q +:32]=rst_n ? rkey[q] : 32'b0;
                assign bases[64*q +:64]=rst_n ? base[q] : 64'b0;
                assign lengths[64*q +:64]=rst_n ? length[q] : 64'b0;
                assign local_macs[48*q +:48]=rst_n ? local_mac[q] : 48'b0;
                assign remote_macs[48*q +:48]=rst_n ? remote_mac[q] : 48'b0;
                assign local_ips[32*q +:32]=rst_n ? local_ip[q] : 32'b0;
                assign remote_ips[32*q +:32]=rst_n ? remote_ip[q] : 32'b0;
            end else begin : g_absent
                assign enabled[q]=0;
                assign local_qpns[24*q +:24]=0; assign remote_qpns[24*q +:24]=0;
                assign rx_psns[24*q +:24]=0; assign tx_psns[24*q +:24]=0;
                assign rkeys[32*q +:32]=0; assign bases[64*q +:64]=0;
                assign lengths[64*q +:64]=0; assign local_macs[48*q +:48]=0;
                assign remote_macs[48*q +:48]=0; assign local_ips[32*q +:32]=0;
                assign remote_ips[32*q +:32]=0;
            end
        end
        integer i;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                enable_bits<=0; pending<=0; status<=0;
                for (i=0;i<QPS;i=i+1) begin
                    local_qpn[i]<=0; remote_qpn[i]<=0; rx_psn[i]<=0; tx_psn[i]<=0;
                    rkey[i]<=0; base[i]<=0; length[i]<=0;
                    local_mac[i]<=0; remote_mac[i]<=0; local_ip[i]<=0; remote_ip[i]<=0;
                end
            end else begin
                if (pending && cfg_rsp_ready) pending<=0;
                if (cfg_valid && cfg_ready) begin
                    pending<=1; status<=check_status;
                    if (check_status==0) begin
                        enable_bits[cfg_index]<=cfg_enable;
                        local_qpn[cfg_index]<=cfg_local_qpn;
                        remote_qpn[cfg_index]<=cfg_remote_qpn;
                        rx_psn[cfg_index]<=cfg_rx_psn; tx_psn[cfg_index]<=cfg_tx_psn;
                        rkey[cfg_index]<=cfg_rkey; base[cfg_index]<=cfg_base;
                        length[cfg_index]<=cfg_length;
                        local_mac[cfg_index]<=cfg_local_mac; remote_mac[cfg_index]<=cfg_remote_mac;
                        local_ip[cfg_index]<=cfg_local_ip; remote_ip[cfg_index]<=cfg_remote_ip;
                    end
                end else if (tx_advance && tx_qp<QPS && enable_bits[tx_qp])
                    tx_psn[tx_qp]<=tx_psn[tx_qp]+24'd1;
            end
        end
    end else begin : g_illegal
        initial $fatal(1,"PARAMETER ERROR: X5 QPS=1..8 required");
        assign cfg_ready=0; assign cfg_rsp_valid=0; assign cfg_rsp_status=0;
        assign cfg_commit=0; assign enabled=0; assign local_qpns=0;
        assign remote_qpns=0; assign rx_psns=0; assign tx_psns=0;
        assign rkeys=0; assign bases=0; assign lengths=0; assign local_macs=0;
        assign remote_macs=0; assign local_ips=0; assign remote_ips=0;
    end endgenerate
endmodule
`default_nettype wire
