# Bellows-N — 网络解析、调度与传输 RTL

[English](README.md) · [简体中文](README.zh-CN.md) · [Repository guide / 文件导航](REPOSITORY_GUIDE.md)

文档更新：2026-11-17。本页对应仓库快照，不是实时作业看板。

## 概览

**Bellows-N**：网络解析、调度与传输 RTL。下方保留芯片技术与报告入口；具体实现范围以所链接目录、规范、测试和结果原件为准。

芯片项目公开；Vulcan 本身保持私有、闭源。今后公开发布仅限芯片技术与公开复现资料，不得包含 Vulcan 内部架构或运作资料。本次更新仅整理文档，并非对全部历史材料进行全面披露审查，也不声称既有仓库树已完成此类清查。

## 范围与证据

按实际目录核对[公开结果索引](REPOSITORY_GUIDE.md)。功能仿真、综合、独立 IP／虚拟引脚时序、板卡桥接探测、工作负载数值读回和系统软件执行是不同层级；一种通过不能替代另一种。现有历史结果保留，不因本次文档更新自动升级或作废。

时钟、资源与性能指标必须读取对应目录的原始记录和适用条件；同名副本不合并为一个数值。此处不宣称全系完成上板、完整模型推理、Linux 实机启动或功耗／能效测量。

## 文件导航

[文件与证据导航](REPOSITORY_GUIDE.md)列出真实存在的源码、约束、测试、报告及结果路径。连字符、下划线和 `chips/` 目录可能是不同发布副本，不自动指定某份为权威，也不移动或删除原件。

公开复现从对应芯片的规范、测试说明和脚本开始；所需工具、输入和板卡条件以该目录为准。文档更新没有重新执行芯片实验。

## 已有芯片目录

| 芯片／变体 | 现存根路径 | 公开交付物 |
| --- | --- | --- |
| BELLOWS-N1 | [`bellows-n1/`](bellows-n1/) · [`bellows_n1/`](bellows_n1/) | [REPORT.md](bellows-n1/REPORT.md) · [REPORT.pdf](bellows-n1/REPORT.pdf) · [SHOWCASE_REPORT.pdf](bellows-n1/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](bellows-n1/SHOWCASE_REPORT.zh-CN.pdf) |
| BELLOWS-N2 | [`bellows-n2/`](bellows-n2/) · [`bellows_n2/`](bellows_n2/) | [REPORT.md](bellows-n2/REPORT.md) · [REPORT.pdf](bellows-n2/REPORT.pdf) · [SHOWCASE_REPORT.pdf](bellows-n2/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](bellows-n2/SHOWCASE_REPORT.zh-CN.pdf) |
| BELLOWS-N3 | [`bellows-n3/`](bellows-n3/) · [`bellows_n3/`](bellows_n3/) | [REPORT.md](bellows-n3/REPORT.md) · [REPORT.pdf](bellows-n3/REPORT.pdf) · [SHOWCASE_REPORT.pdf](bellows-n3/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](bellows-n3/SHOWCASE_REPORT.zh-CN.pdf) |
| BELLOWS-N4 | [`bellows-n4/`](bellows-n4/) · [`bellows_n4/`](bellows_n4/) | [REPORT.md](bellows-n4/REPORT.md) · [REPORT.pdf](bellows-n4/REPORT.pdf) · [SHOWCASE_REPORT.pdf](bellows-n4/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](bellows-n4/SHOWCASE_REPORT.zh-CN.pdf) |
| BELLOWS-N5 | [`bellows-n5/`](bellows-n5/) · [`bellows_n5/`](bellows_n5/) | [REPORT.md](bellows-n5/REPORT.md) · [REPORT.pdf](bellows-n5/REPORT.pdf) · [SHOWCASE_REPORT.pdf](bellows-n5/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](bellows-n5/SHOWCASE_REPORT.zh-CN.pdf) |

## 架构目录与技术报告

| 代际 | 芯片 | 架构／研究范围 | 记录导航 | 报告 |
| --- | --- | --- | --- | --- |
| **第一代** | [**BELLOWS-N1**](./bellows-n1/) | 64-bit 线速多标准 CRC32 / CRC32C / CRC64-NVMe 并行校验卸载核 | [Exact-directory records](REPOSITORY_GUIDE.md) | [学术版 PDF](./bellows-n1/REPORT.pdf) · [英文版](./bellows-n1/SHOWCASE_REPORT.pdf) · [中文版](./bellows-n1/SHOWCASE_REPORT.zh-CN.pdf) |
| **第二代** | [**BELLOWS-N2**](./bellows-n2/) | L2/L3/L4 协议包头解析 + 五元组 Toeplitz RSS 哈希 + 64 规则优先级 TCAM 流表分类器 | [Exact-directory records](REPOSITORY_GUIDE.md) | [学术版 PDF](./bellows-n2/REPORT.pdf) · [英文版](./bellows-n2/SHOWCASE_REPORT.pdf) · [中文版](./bellows-n2/SHOWCASE_REPORT.zh-CN.pdf) |
| **第三代** | [**BELLOWS-N3**](./chips/bellows_n3/) | 8 队列赤字轮询 (DRR) 与令牌桶流量整形 + 环状描述符包 DMA 子系统 | [Exact-directory records](REPOSITORY_GUIDE.md) | *生成中* |

## 关联项目

- AI / embeddings: [Anvil-Q](https://github.com/aHappend/anvil-q), [Anvil-E](https://github.com/aHappend/anvil-e), [Anvil-QN](https://github.com/aHappend/anvil-qn), [Anvil-EN](https://github.com/aHappend/anvil-en), [Anvil-D](https://github.com/aHappend/anvil-d).
- Systems: [Hammer-V](https://github.com/aHappend/hammer-v), [Furnace-X](https://github.com/aHappend/furnace-x).
- DSP / vision: [Billet-F](https://github.com/aHappend/billet-f), [Billet-T](https://github.com/aHappend/billet-t), [Swage-S](https://github.com/aHappend/swage-s).
- Data / security / graphics: [Bellows-L](https://github.com/aHappend/bellows-l), [Bellows-N](https://github.com/aHappend/bellows-n), [Rivet-A](https://github.com/aHappend/rivet-a), [Rivet-H](https://github.com/aHappend/rivet-h), [Crucible-G](https://github.com/aHappend/crucible-g), [SABLE](https://github.com/aHappend/sable).
- [Public fleet catalog](https://github.com/aHappend/vulcan-showcase). Related independent research: [ACE-2](https://github.com/aHappend/ace-2), [ACE-3](https://github.com/aHappend/ace-3); these retain their own provenance and acceptance boundaries.
- DSpark 是研究方向，不代表本仓库已交付对应芯片；此处不虚构实现或仓库链接。
