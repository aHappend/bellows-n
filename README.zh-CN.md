<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <img src="brand/logo.svg" width="420" alt="Vulcan">
  </picture>
  <h1>Bellows-N · 高速网络包传输、L2/L3/L4 流表分类与 QoS 流量整形 DMA 芯片系列</h1>
  <p><strong>可综合 100 MHz+ 64位线速多标准 CRC32C/CRC64-NVMe 卸载、L2/L3/L4 RSS/TCAM 分类器与 8队列 DRR/令牌桶 QoS 环状包 DMA · Intel Arria 10 GX</strong></p>
  <p>
    <a href="README.md"><strong>English Documentation</strong></a> ·
    <a href="https://github.com/aHappend/bellows-l">Bellows-L (LZ4 压缩)</a> ·
    <a href="https://github.com/aHappend/furnace-x">Furnace-X (异构 SoC)</a>
  </p>
</div>

---

**Bellows-N** 是 Vulcan **Bellows（数据流与传输家族）** 下的高速网络包处理与智能网卡（SmartNIC）卸载芯片子系列，与 [**Bellows-L**（流式 LZ4 压缩/解压系列）](https://github.com/aHappend/bellows-l) 形成“链路层无损压缩 + 网络层协议卸载”双子星：涵盖 64-bit 线速多标准 CRC32/CRC32C/CRC64-NVMe 卸载核（`BELLOWS-N1`）、L2/L3/L4 协议头解析 + Toeplitz RSS 哈希 + 64 规则优先级 TCAM 流分类引擎（`BELLOWS-N2`），以及 8 队列 DRR 令牌桶流量整形与环状描述符散聚 DMA 子系统（`BELLOWS-N3`）。

## 硅签核矩阵与双轨报告（`100 MHz+` 基线）

| 代际 | 芯片代号 | 架构与数值验证范围 | Quartus 17.1 STA (`10.0 ns`) | Intel Arria 10 GX 物理上板 | 学术与开发者报告 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **第一代** | [**BELLOWS-N1**](./bellows-n1/) | 64-bit 线速多标准 CRC32 / CRC32C / CRC64-NVMe 并行校验卸载核 | **已收敛 (`>= 100 MHz`)** | **通过 (3/3)** | [学术版 PDF](./bellows-n1/REPORT.pdf) · [英文版](./bellows-n1/SHOWCASE_REPORT.pdf) · [中文版](./bellows-n1/SHOWCASE_REPORT.zh-CN.pdf) |
| **第二代** | [**BELLOWS-N2**](./bellows-n2/) | L2/L3/L4 协议包头解析 + 五元组 Toeplitz RSS 哈希 + 64 规则优先级 TCAM 流表分类器 | **已收敛 (`117.43 MHz`, WNS `+1.484 ns`)** | **通过 (3/3)** | [学术版 PDF](./bellows-n2/REPORT.pdf) · [英文版](./bellows-n2/SHOWCASE_REPORT.pdf) · [中文版](./bellows-n2/SHOWCASE_REPORT.zh-CN.pdf) |
| **第三代** | [**BELLOWS-N3**](./chips/bellows_n3/) | 8 队列赤字轮询 (DRR) 与令牌桶流量整形 + 环状描述符包 DMA 子系统 | 目标 `>= 100 MHz` | 验证冲刺中 (`L1 checks`) | *生成中* |
