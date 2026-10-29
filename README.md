<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <img src="brand/logo.svg" width="420" alt="Vulcan">
  </picture>
  <h1>Bellows-N · High-Speed Network Packet Transport, L2/L3/L4 Classification & QoS DMA Silicon Series</h1>
  <p><strong>Synthesizable 100 MHz+ 64-Bit Multi-Standard CRC32C/CRC64-NVMe Offload, L2/L3/L4 RSS/TCAM Classifier & 8-Queue DRR/Token-Bucket QoS Packet DMA · Intel Arria 10 GX</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Platform-Intel_Arria_10_GX-0f766e?style=flat-square" alt="Platform">
    <img src="https://img.shields.io/badge/Quartus_17.1_STA-100_MHz%2B_Closed-0f766e?style=flat-square" alt="STA">
    <img src="https://img.shields.io/badge/PCIe_Gen3x8_HIL-100%25_Passed-1d4ed8?style=flat-square" alt="HIL">
    <img src="https://img.shields.io/badge/Author-Sufeng_Guo_(MSRA)-334155?style=flat-square" alt="Author">
    <img src="https://img.shields.io/badge/License-MIT-64748b?style=flat-square" alt="License">
  </p>
  <p>
    <a href="https://ahappend.github.io/vulcan/">Website</a> ·
    <a href="https://github.com/aHappend/vulcan-showcase">Vulcan Showcase</a> ·
    <a href="https://github.com/aHappend/anvil-q">Anvil-Q (LLM)</a> ·
    <a href="https://github.com/aHappend/anvil-e">Anvil-E (Embedding)</a> ·
    <a href="https://github.com/aHappend/billet-t">Billet-T (FFT/DSP)</a> ·
    <a href="https://github.com/aHappend/billet-f">Billet-F (FIR/IIR)</a> ·
    <a href="https://github.com/aHappend/rivet-a">Rivet-A (AES-GCM)</a> ·
    <a href="https://github.com/aHappend/rivet-h">Rivet-H (SHA/HMAC)</a> ·
    <a href="https://github.com/aHappend/swage-s">Swage-S (ISP)</a> ·
    <a href="https://github.com/aHappend/bellows-l">Bellows-L (LZ4)</a> ·
    <a href="https://github.com/aHappend/bellows-n">Bellows-N (Network/Packet)</a> ·
    <a href="https://github.com/aHappend/crucible-g">Crucible-G (3D)</a> ·
    <a href="https://github.com/aHappend/hammer-v">Hammer-V (RISC-V)</a> ·
    <a href="https://github.com/aHappend/furnace-x">Furnace-X (SoC)</a> ·
    <a href="README.zh-CN.md"><strong>中文文档</strong></a>
  </p>
</div>

---

**Bellows-N** is the high-speed network packet transport and smart-NIC offload series within Vulcan's **Bellows** data-movement silicon family, complementing [**Bellows-L** (Streaming LZ4 Compression)](https://github.com/aHappend/bellows-l) with line-rate 64-bit multi-polynomial CRC offload (`BELLOWS-N1`), L2/L3/L4 header parsing + Toeplitz RSS hashing + 64-rule TCAM flow classification (`BELLOWS-N2`), and 8-queue Deficit Round-Robin (DRR) + token-bucket QoS traffic shaping with scatter-gather ring DMA (`BELLOWS-N3`).

## Silicon Signoff Matrix & Dual-Track Publications (`100 MHz+` Baseline)

| Gen | Accelerator | Architecture & Numerical Scope | Quartus 17.1 STA (`10.0 ns`) | Intel Arria 10 GX HIL | Academic & Developer Reports |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Gen-1** | [**BELLOWS-N1**](./bellows-n1/) | 64-bit Line-Rate Multi-Standard CRC32 (Ethernet), CRC32C (iSCSI/RoCE) & CRC64-NVMe Parallel Offload Engine | **Closed (`>= 100 MHz`)** | **Passed (3/3)** | [Academic PDF](./bellows-n1/REPORT.pdf) · [Developer EN](./bellows-n1/SHOWCASE_REPORT.pdf) · [中文版](./bellows-n1/SHOWCASE_REPORT.zh-CN.pdf) |
| **Gen-2** | [**BELLOWS-N2**](./bellows-n2/) | L2/L3/L4 Ethernet/VLAN/IPv4/IPv6/TCP/UDP Packet Parser + 5-Tuple Toeplitz RSS Hash + 64-Rule Priority TCAM Classifier | **Closed (`117.43 MHz`, WNS `+1.484 ns`)** | **Passed (3/3)** | [Academic PDF](./bellows-n2/REPORT.pdf) · [Developer EN](./bellows-n2/SHOWCASE_REPORT.pdf) · [中文版](./bellows-n2/SHOWCASE_REPORT.zh-CN.pdf) |
| **Gen-3** | [**BELLOWS-N3**](./chips/bellows_n3/) | 8-Queue Deficit Round-Robin (DRR) & Dual-Rate Token-Bucket Traffic Shaper + Scatter-Gather Ring Packet DMA Subsystem | Target `>= 100 MHz` | In Verification (`L1 checks`) | *In Progress* |

---
<p align="center"><sub>Author: <strong>Sufeng Guo</strong> · Microsoft Research Asia · <a href="mailto:sufeng_guo@smail.nju.edu.cn">sufeng_guo@smail.nju.edu.cn</a> · <a href="LICENSE">MIT License</a></sub></p>
