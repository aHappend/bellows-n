# BELLOWS-N4 implementation architecture

The design extends, rather than replaces, the supplied X3 hierarchy.
`bellows_n4_top.legacy_core` is `furnace_x3_top`, preserving its CRC, parser,
RSS, classifier, scheduler, shaping, descriptor and DMA instances. A two-branch
transaction fork tracks external-payload and receive-buffer acceptance
independently. Disabled RoCE mode bypasses the fork's receive dependency.
Both external and DMA-originated traffic therefore use the same receive path.

`bellows_n4_top.roce_rx` owns bounded packet capture, configuration and transaction
retirement. Its substantive children are `parser`, `psn_tracker`, `dmp_engine`
and `collective_engine`; the latter instantiates `reduce_alu`.

| Resource | Producer / consumer | Release and protection |
|---|---|---|
| Packet byte banks | legacy payload / parser and payload replay | next frame only after required outputs retire |
| QP configuration/state | configuration / tracker | disabled validity at reset; atomic failed-write preservation |
| Collective accumulator | accepted rank / next rank ALU replay | previous rank drains before next rank, completion before reconfiguration |
| Placement beat | validated payload / fault-free memory | stable until write handshake |
| ACK and event slots | committed transaction / external consumer | independently retained until accepted |

Capture stores at most `MAX_PACKET_BYTES`; overflow saturates/drains without
address wrap. Full-frame ICRC and header validation prevents a corrupt packet
from producing irrevocable writes. Packet storage is on-chip validation
storage, not a software or host bounce buffer. Multibyte protected-address
calculations include overflow bits before any write is issued.

Ordinary packet placement streams real decoded payload. Segmented transport
retains initial address, length and committed offset per QP. Collective replay
uses full-width beats and banked synchronous accumulator storage. A rank barrier
drains the arithmetic pipeline before a dependent rank can reuse its addresses;
short and single-beat vectors do not rely on vector length exceeding latency.
Rank zero copies the source encoding exactly; later ranks pass both operands
through the eight-stage SIMD ALU.

At W=512 a beat carries 32 INT16/BF16 or 16 FP32 lanes; at W=64 it carries
4 INT16/BF16 or 2 FP32 lanes. At an assumed 100 MHz, a one-beat-per-cycle
payload datapath corresponds to 6.4 GB/s or 0.8 GB/s respectively. These are
architectural ceilings, not measured throughput. Parent packet serialization,
byte-scanning validation, fill/drain and response stalls are separate overheads.
No end-to-end wire-rate packet-initiation or full distributed collective control
plane is claimed. Host distribution uses the retained NIC/DMA path.

All floating operators use explicit integer significands, sticky alignment,
bounded leading-zero decisions, normalization and RNE rounding registers.
BF16 uses the same exponent range as FP32 with its own rounding boundary.
No proprietary IP or nonsynthesizable real-valued arithmetic is used.
The exact wire masks, numerical edge rules and stage boundaries are frozen
in `design/SPEC.md`; independent verification derives its expected results
from the protocol and arithmetic rules, not this implementation.

There is no supplied generational handoff or parent STA/PPA evidence.
Current synthesis, timing, hardware measurements and independent acceptance
remain pending. Product report generation belongs to the shared runtime only
after engineering acceptance.
