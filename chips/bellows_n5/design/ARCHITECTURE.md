# BELLOWS-N5 microarchitecture

## Integration boundary

`bellows_n5_top.g_legal.legacy_core` is the supplied `furnace_x4_top` with
unchanged ports, parameters and named descendants. A separate
`g_legal.x5_core:bellows_n5_engine` owns X5 traffic. Idle or stalled X5 channels
cannot gate the parent. See `SPEC.md` for the frozen numerical/wire contract
and cycle/degenerate-boundary table.

The engine's required substantive instances are:

| Instance | Module | Responsibility |
|---|---|---|
| qp_table | bellows_n5_qp_table | Independent X5 endpoint/protection/PSN configuration |
| packet_rx | bellows_n5_packet_rx | Full-frame buffering, canonical checks, checksum/CRC and endpoint validation |
| packet_tx | bellows_n5_packet_tx | Network envelope, byte serialization, checksum and CRC |
| reorder_tracker | bellows_n5_reorder | Reserved decision, commit gating, circular bitmap, serial retirement/snapshot |
| sack_generator | bellows_n5_sack | Trusted immutable snapshot to SACK command/payload |
| moe_router | bellows_n5_moe_router | Local tokens, remote jobs, fragment ownership, packetization and deterministic combine |
| moe_router.topk | bellows_n5_topk | One signed candidate comparison per cycle |
| moe_router.combiner | bellows_n5_combine | Ordered BF16 gated accumulation |
| combiner.gate_mul | bellows_n5_bf16_mul | Eight-stage elastic RNE multiplication |
| combiner.gate_sum | furnace_reduce_alu | Inherited eight-stage BF16 ADD |

Required instances must contain real state/data processing, not constant
wrappers. Structural retention and connectivity are independently inspected.

## Control and storage choices

Packet processing uses bounded registered FSMs. At most one packet is reserved
in the reorder tracker at a time; each QP retains independent base and bitmap.
The physical bitmap is addressed by low PSN bits. Serialized retirement and
logical snapshot generation replace a deep 256-bit prefix/rotation network.
This intentionally trades latency for bounded timing depth; it is not a
line-rate claim.

Top-K captures scores and eligibility once. Each rank scans ascending IDs with
a signed comparator, commits the winner on a separate cycle and removes it
from eligibility. Its selected-ID record is immutable until accepted.

The BF16 multiplier decodes, multiplies 8-bit significands, finds leading
position, computes normalization/subnormal shift, selects guard/sticky bits,
rounds, packs and publishes over eight globally stalled stages. Complex
combinational helpers are evaluated outside sequential processes. Special
values travel alongside arithmetic and are selected before publication.

Bulk payload RAM is byte-lane unpacked storage with synchronous registered
reads and no reset writes. Small resettable valid/ownership records gate every
RAM observation. Accepted command ownership outlives packet/payload output
backpressure and is released only at its specified final transfer.

| Buffer | Writer | Reader | Release boundary |
|---|---|---|---|
| Received frame | Network input | Validator / packet consumer | Fully consumed or explicitly rejected frame |
| WRITE application | Local write payload | WRITE packet source | All locally generated packets completed, or drained failure |
| Local activation | Token input | Per-selected-rank DISPATCH | Context completion accepted |
| Per-rank return | Validated RETURN fragments | Ordered combiner | Context completion accepted |
| Remote expert activation | Validated DISPATCH fragments | Expert request stream | Corresponding validated response RETURN packets completed |
| Remote expert response | Expert response payload | RETURN packet source | Last corresponding packet completed |
| SACK record | Reorder tracker | SACK source | Serialized packet accepted |

No buffer is reset by clearing every payload byte. Configuration uses global
quiescence and excludes all these ownership states and pending events.

## Internal channel definitions

Packet RX/TX command records are `cmd_valid/ready`, `cmd_qp[2:0]`,
`cmd_meta[511:0]`, followed by `payload_tvalid/ready/data/keep/last`.
Data/keep widths match DATA_WIDTH and DATA_WIDTH>>3. Meta byte j is
`meta[8*j+:8]`, exactly the X5 header byte layout. RX publishes only validated
frames; TX regenerates the canonical Ethernet/IPv4/UDP envelope and CRC.

QP table uses `cfg_*` fields matching the public QP bundle, `idle_allow`,
`route_qps[7:0]` (enabled route references), `cfg_rsp_*`, and `cfg_commit`.
Fixed eight-slot packed exports are enabled:8, local_qpns/remote_qpns/
rx_psns/tx_psns:192, rkeys/local_ips/remote_ips:256, bases/lengths:512 and
local_macs/remote_macs:384. Absent QP slots are zero. `tx_advance/tx_qp`
updates one data-packet PSN at local final packet transfer. `cfg_commit`
denotes the accepted successful configuration edge for atomic tracker update;
rejected records never clear tracker state. Engine arbitration prevents
configuration and packet completion from coinciding.

Tracker ports and timing are fixed by `SPEC.md` and the admitted work order.
Requests reserve a QP and PSN until decision, optional explicit commit,
retirement and immutable SACK snapshot acceptance finish. It accepts no second
request/configuration in that interval.

SACK generator additionally captures the triggering PSN and both QPNs with
the snapshot. It emits one raw-format 32-byte packet payload without allocating
a new data PSN.

## Dependency and failure boundaries

| Consumer assumption | Producer guarantee |
|---|---|
| Tracker may classify a packet | RX has validated integrity, canonical fields, endpoints and protection first |
| Memory may expose bytes | Packet validated and new tracker reservation accepted |
| Tracker may set bit | Final memory beat transferred or complete MoE fragment stored under ownership |
| MoE may use returned data | Full expected identity checked before RAM update |
| Arithmetic may accumulate rank r | Captured weights and returned ranks, not arrival order, determine operation |
| TX may advance PSN | One complete non-SACK packet locally transferred |
| Configuration may commit | Engine has no live X5 ownership, assembly or pending output |

Invalid framing/integrity/endpoint/protection has event-only disposition.
Trusted semantic rejection cancels the tracker reservation and produces
status-3 SACK. Duplicate recognition precedes retired-context checks.
Finite resource exhaustion is a readiness stall, not a semantic rejection.

## Evidence and handoff

Only actual fresh receipts establish results. Designer may perform at most
fast static elaboration, never functional/oracle/synthesis self-verification.
Verifier independently authors and runs all `tests/*`. Required portable
commands and claim-to-evidence index are in `SPEC.md`. Native timing/physical
gates and the final independently reviewed report belong to the shared runtime.
The parent timing/PPA limitations in `GENERATIONAL_HANDOFF.md` are preserved.

Current source boundary: parent deliverable copies and the substantive Top-K,
reorder, multiplier, combiner, QP table, SACK, packet RX and packet TX leaves
are present. The required MoE router, integrated engine and X5 top remain
unimplemented. Their required hierarchy and control/storage responsibilities
above describe the frozen integration target, not an existing connected
implementation. No functional, synthesis, timing or physical result is claimed.
