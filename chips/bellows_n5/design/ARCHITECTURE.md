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

The top's legal generate guard validates all eight public parameters before
instantiating either subsystem. Engine/router/RAM are internal implementation
modules instantiated only within that legal geometry; their storage widths
and capacity are derived from those admitted top parameters.

Tracker ports and timing are fixed by `SPEC.md` and the admitted work order.
Requests reserve a QP and PSN until decision, optional explicit commit,
retirement and immutable SACK snapshot acceptance finish. It accepts no second
request/configuration in that interval.

SACK generator additionally captures the triggering PSN and both QPNs with
the snapshot. It emits one raw-format 32-byte packet payload without allocating
a new data PSN.

### Engine sequencing

The receive FSM captures the validated packet metadata before requesting a
tracker reservation. Duplicate/ahead decisions drain the buffered packet without
calling the MoE router or asserting memory valid. A WRITE drives direct placement
and commits only after its final memory transfer. DISPATCH/RETURN metadata is
passed through `rx_cmd_*` to the router, followed by `rx_payload_*`; the router's
retained `rx_done_valid/ready` and `rx_done_ok` authorize successful commit or
cancellation. Snapshot delivery to the SACK generator precedes the retained
receive event. Peer SACK payloads instead fill a 256-bit output record without
entering the tracker or generating another acknowledgement.

The separate WRITE FSM owns one 65536-byte application buffer. It validates
the entire declared message, including keep/last consistency, before publishing
its first packet command. Offset and packet-limit registers advance by 256
bytes between packets. A malformed message drains through last, emits status9
and never enters the packet scheduler.

Four command/payload sources are SACK, WRITE, DISPATCH and RETURN, numbered
0..3. A packet-boundary round-robin arbiter captures one command and its QP,
inserts the current data PSN/path for sources1..3, and exclusively owns TX until
the serialized final beat transfers. Only that transfer advances the QP PSN.
The packet transmitter reads a complete output beat synchronously and holds a
registered output record through stalls; it does not serialize one payload
byte over multiple network beats.

Receive events and expert-response events enter one retained public event
register with alternating arbitration. An invalid receive frame comes directly
from packet RX's error record. Validated SACK records retain their owning
received metadata until the peer-SACK output transfers, preventing a following
frame from changing a stalled acknowledgement record.

### MoE ownership and RAM addressing

Local contexts keep token ID, count, format, selected IDs, captured QPs, gate
weights and two fragment-presence bits per rank. One activation assembler owns
the Top-K transaction and its input stream at a time; other contexts can
dispatch, receive results and combine concurrently. Dispatch visits every
selected rank and each canonical fragment, with exact byte preservation.
No context becomes reusable before its completion transfers.

Remote jobs retain normalized metadata, source QP, two presence bits, request
presentation and response-valid ownership. Incoming DISPATCH lookup scans one
job at a time with a registered metadata read before comparison. A complete
scan must exclude an existing identity before allocating the first free slot.
If none is free, the retained packet command waits and rescans while payload
readiness stays low. RETURNs match active local token and captured selected-rank
identity before writing return RAM. The tracker handles network duplicates
before either lookup, including replays after ownership retirement.

Request, dispatch and return arbiters use explicit wrapping scan cursors, not
power-of-two slot truncation. Expert response metadata is captured once, then
matched by a registered-read job scan. No payload is consumed on an unmatched
response. A matched response uses a separate RAM, allowing malformed payloads
to drain without exposing partial RETURN packets or damaging request data.
Malformed responses preserve job ownership for retry.

Each local activation occupies a 512-byte stride. Each returned rank and each
remote job/response has its own 512-byte stride; the local return index is
`context*MAX_K+rank`, not truncated rank or token-ID bits. `bellows_n5_payload_ram`
banks every stream byte lane into a separate unpacked array with synchronous
registered reads and per-lane write enables. RAM arrays are never reset.
Active/presented/fragment/completion state independently authorizes observations.

### Physical memory-port repair

The original native Quartus attempt timed out in periphery planning, followed
by TimeQuest exit 3 because planning had not completed. Its retained receipt is
`.vulcan/engineering/run-0001/quartus-sta.json`; the corresponding
`quartus_sta_work/top.map.rpt` reports an estimated 433614 ALMs and 528740
registers, not fitted PPA or a measured timing violation. No setup/hold paths
or recognized clocks were extracted. The four portable L1 passes before this
repair describe the earlier source version, not validation of the changes below.

The report's lines 2022..2025 show activation RAM using 16896 registers and
job/response/return RAM each using 66048 registers, with no block-memory bits.
The same payload RAM module's WRITE instance inferred 524288 block-memory bits.
Payload RAM now derives an explicit row-address width from its actual row
count. It range-checks the full shifted byte address before enabling a read or
per-lane write, then indexes the array with only that bounded row address.
This removes unused upper index bits without allowing invalid addresses to
alias live storage. Singleton and non-power-of-two row counts remain supported.
An invalid read holds the previous registered output; an invalid write performs
no update. Existing byte-lane storage and full token/job capacities are retained.

The collective accumulator's uninferred memory is also present in the supplied
parent; this is an inherited physical implementation limitation, not an X5
functional regression. Its prior reads were already clocked. The repair instead
consolidates the branch-specific accesses into one read address/enable and one
write address/data/enable, each range-checked before row-address narrowing.
Seed writes retain priority over reduction writes, and accumulation reads
retain priority over replay reads. Both ports access the array only in the
reset-free clocked memory process. Reads still return the pre-write word after
the accepting edge; disabled reads and replay stalls hold the prior result.
No arithmetic latency, public interface, reset ownership or replay sequencing
is changed. The read-only parent and parallel TCAM arrays are untouched.

These are inference-directed source repairs, not evidence that Quartus now
infers M20K storage or fits the target. Fresh existing L1 checks and runtime
physical gates must establish per-instance M20K utilization, clock recognition,
setup and hold analysis, and eventual board acceptance. The prior virtual-pin
clock warning 15725 requires supported execution-configuration diagnosis;
runtime-owned constraints are not changed here. Packet RX/TX's earlier
93852/51582 combinational ALUT counts remain a resource risk to reassess from
the fresh mapping results; no speculative packet datapath rewrite is included.

The combine arbiter selects complete contexts round-robin, issues the combiner
with captured selected-rank weights, and services its `read_valid/ready`,
`read_rank`, `read_elem` channel from return RAM. A registered sample response
uses `sample_valid/ready/data`; BF16 addresses use a two-byte element stride.
Combined BF16 elements pack low lane first into a retained network-width
output beat. Only the combined final transfer creates the successful token
completion, and completion acceptance releases context ownership.
Completion arbitration alternates command rejections with ready context
completions and scans completed contexts round-robin, so continuous invalid
commands cannot starve successful token retirement.

Router packet-source interfaces are `dispatch_cmd_*`/`dispatch_payload_*` and
`return_cmd_*`/`return_payload_*`, with the same widths and header-byte packing
as packet RX/TX. Their `dispatch_done`/`return_done` inputs denote the matching
serialized network final transfer, not mere command or payload buffering.
The router's retained `evt_*` record reports expert-response outcomes;
kind3 denotes the resulting RETURN operation, and unmatched response identity
fields are zero. `route_qps` is the enabled-route QP reference mask used to
reject an unsafe QP disable.

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

The connected design includes all named instances, local and remote ownership
and the complete legacy forwarding top. The design-owned source inventory and
portable compile/integration commands are in `SPEC.md`. Static elaboration is
advisory only; all functional, synthesis, native timing and physical acceptance
results remain independent work. No such result is claimed by this document.
