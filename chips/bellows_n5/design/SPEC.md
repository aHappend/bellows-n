# BELLOWS-N5 implementation contract

## Status and provenance

The admitted work order is the acceptance authority. This document freezes the
design interpretation; it does not report verification, timing closure or
hardware acceptance. The supplied parent sources are in
`furnace_x4_reference/rtl/`. Deliverable copies in `rtl/` retain their interfaces
and hierarchy. `GENERATIONAL_HANDOFF.md` reports no numerical parent Quartus
timing or PPA, and only a connectivity-level physical bridge observation.
Neither constitutes X5 acceptance.

Implementation is in progress. The parent copies and X5 Top-K, reorder,
BF16 multiply/combine, QP table, SACK and packet RX/TX modules are saved.
The integrated MoE router, X5 engine and X5 top are not yet implemented.
These leaves are not a completed or verified subsystem.

Top: `bellows_n5_top`. One `clk`, active-low asynchronous `rst_n`.
Target: Intel Arria 10 GX 10AX115N2F45E1SG, period <=10.0 ns.
The custom X5 packet-spraying profile does not assert universal UEC wire
interoperability. The unchanged parent RoCEv2 port remains available.
External expert computation is outside the subsystem; dispatch, reassembly and
weighted combination are hardware responsibilities. Local transmit completion
does not assert remote reliable delivery. Automatic retransmission is not added.

## Parameters

| Parameter | Default | Legal values |
|---|---:|---|
| DATA_WIDTH | 512 | 64, 512 |
| MAX_PACKET_BYTES | 9216 | 1..9216 (parent datapath only) |
| MAX_SG | 16 | 1..16 |
| QPS | 8 | 1..8 |
| EXPERTS | 8 | 1..16 |
| MAX_K | 4 | 1..min(4,EXPERTS) |
| TOKENS | 4 | 1..8 |
| MAX_TOKEN_ELEMS | 256 | 1..256 |

New packet payload capacity is always 256 bytes. The reorder window is always
256 packets per QP. Remote job capacity is TOKENS*MAX_K. Diagnostic-only port
widths remain at least one for invalid parameters; an illegal generate branch
must terminate simulation nonzero with `PARAMETER ERROR`, not run a clamped
legal implementation. Singleton and non-power-of-two parameters are real
supported configurations.

## Cycle & Degenerate-Boundary Table

All transfers use **pre-edge** valid/ready and the complete associated record.
State and outputs described below are **post-edge**, after nonblocking updates.

| Boundary | Required behavior |
|---|---|
| Asserted reset | All new public outputs, including ready, idle, metadata, data, keep, last and valid, are zero; no acceptance. Legacy reset semantics unchanged. |
| First released edge | No old packet, reservation, context, job or completion reappears. RAM ownership is invalid until reassigned. |
| Stalled output | Valid and every associated field remain unchanged until acceptance. Final acceptance releases ownership at that edge. |
| Single beat | First and last may coincide; final keep is a nonempty contiguous low-bit prefix. Nonfinal keep is full. Invalid output lanes are zero. |
| Singleton storage | Slot zero is valid, explicit wrap returns to zero, no zero-width vectors or empty selection loops. |
| Non-power-of-two storage | Compare against the actual last slot; never wrap by truncated binary address. |
| Both configurations valid | QP configuration has priority; neither commits outside global X5 quiescence. |
| Configure versus traffic | Configuration exclusively owns a quiescent boundary. It cannot change an active reservation or packet endpoint. |
| Reorder decision and commit | A new decision must transfer before commit_ready asserts. Non-new decisions never consume commit. |
| Reorder successful commit | Set one physical bit at Ec. Retire at most one bit at each subsequent edge; no simultaneous scan/retire. |
| Cancelled commit | Do not modify bitmap/base. Snapshot status is 3. |
| Reset versus memory write | Reset invalidates ownership; stale RAM bytes cannot become observable. No bulk RAM reset is required. |

Top-K captures at E0. Each rank scans exactly EXPERTS ascending candidates on
subsequent edges, followed by a separate rank-commit edge. out_valid first
asserts after E[K*(EXPERTS+1)]. Signed score ties choose the smaller ID. Unused
rank outputs are zero.

BF16 multiplication and inherited BF16 addition each have eight elastic
register stages. An input at E0 reaches stage eight at E7 without stalls.
A global stall freezes arithmetic and validity together.

Reorder accepts at E0, registers modular difference at E1 and publishes a
decision at E2. For a successful new commit at Ec, retire k contiguous bits on
Ec+1..Ec+k, observe the missing bit at Ec+k+1, and sample logical offsets on
Ec+k+2..Ec+k+257. SACK valid first asserts on the last sampling edge.
Duplicate/ahead acceptance at Ed samples Ed+1..Ed+256. Cancellation samples
Ec+1..Ec+256. Snapshots cannot change under backpressure.

With consumers ready, a frame reaches event and generated SACK within 8192
cycles of its final beat, except legitimate remote-job capacity waits.
A token with all valid returned fragments reaches combined final beat and
completion within 512+32*K*element_count cycles, excluding another token's
bounded round-robin service.

## External interface and ownership

Every parent `furnace_x4_top` parameter and port is forwarded unchanged to
`bellows_n5_top.g_legal.legacy_core`. All new channels have the `x5_` prefix.
Network, write payload, activation, expert payload and combined output use
DATA_WIDTH data and DATA_WIDTH>>3 keep lanes, byte lane zero first.

| New channel | Record and semantics |
|---|---|
| rx / tx | tvalid/tready/tdata/tkeep/tlast, complete serialized Ethernet frames |
| qp_cfg | index:3, enable:1, local_qpn/remote_qpn/rx_psn/tx_psn:24, rkey:32, base/length:64, local_mac/remote_mac:48, local_ip/remote_ip:32 |
| qp_cfg_rsp | status:3; 0 committed, 1 index/duplicate enabled local QPN, 2 enabled region zero/overflow, 3 disable of a routed QP |
| expert_cfg | id:16, enable:1, qp:3; response status:2: 0 success, 1 invalid ID, 2 invalid/disabled destination |
| write_cmd | qp:3, addr:64, rkey:32, bytes:16, cookie:32; length 1..65535 |
| write / write_cpl | payload stream; completion cookie:32, status:4: 0 locally transmitted, 5 QP, 7 command, 9 payload |
| mem | valid/ready, addr:64, data/keep/last; last ends a received packet |
| moe_cmd | token_id:32, elems:9, k:3, format:1, scores/weights:16*EXPERTS |
| token | activation stream; accepted malformed payload drains through last without dispatch |
| combine | output stream plus token_id:32; BF16 elements always |
| moe_cpl | token_id:32, status:4: 0 after final combined transfer, 7 command/duplicate active ID, 9 payload |
| expert_req | valid/ready, qp:3, meta:512, then separate req_t* payload stream |
| expert_rsp | valid/ready, qp:3, meta:512, then separate rsp_t* payload stream |
| peer_sack | valid/ready, qp:3, base:24, bitmap:256, status:2 |
| evt | valid/ready, status:4, kind:8, qp:3, token_id:32, psn:24 |
| idle | true only at global X5 quiescence outside reset |

Metadata/payload valid-ready channels are distinct. Invalid commands consume
no payload. Buffer and validate an entire accepted application payload before
emitting its first packet. Drain malformed payloads through last; emit no packet.
Retain local contexts until completion acceptance. Retain remote jobs until
validated response return packets all transfer. Invalid response metadata
consumes no payload and reports an event; malformed accepted responses drain,
emit no packet and leave the job retryable.

Global quiescence excludes active local tokens, remote jobs, partial input,
pending packets, writes, events and responses. Rejected configuration changes
nothing. Disabling an in-range route does not require an enabled destination.
All eight parent queues, 64 rules and inherited CRC/parser/RSS/DMA/RDMA/reduction
behavior remain independent of new-interface stalls.

Every received frame and expert-response outcome generates a retained event:
0 success, 1 duplicate, 2 ahead, 3 malformed framing/header, 4 integrity,
5 unknown/disabled QP or endpoint mismatch, 6 protection, 7 semantic identity,
9 application payload. Untrusted/unavailable identity is zero, never stale.
Exhausted resources backpressure rather than silently drop traffic.

## Frozen wire layout

Ethernet II (EtherType 0800), fixed IPv4 (45, DSCP 0, ID 0, DF 1, offset 0,
TTL 64, protocol 17, validated header checksum), UDP (destination 4792,
source 49152+path, checksum zero), 64-byte X5 header, payload, CRC32C trailer.
No preamble/FCS. Reject VLAN, IPv6, IP options/fragments on this separate profile.
Both MAC/IP endpoints and QPNs must match configured peer/local values.
Integers are network byte order unless explicitly stated.

| X5 byte offset | Meaning |
|---|---|
| 0..3 / 4 | magic 46583521 / version 1 |
| 5 / 6 / 7 | kind WRITE=1, DISPATCH=2, RETURN=3, SACK=4 / FP8=0, BF16=1, raw=2 / final bit0 only |
| 8..10 / 11 | destination QPN / zero |
| 12..14 / 15 | PSN / path 0..3 |
| 16..18 / 19 | source QPN / zero |
| 20..23 | token ID or WRITE cookie |
| 24..25 / 26 / 27 | expert ID / selected rank / K |
| 28..29 / 30..31 | total elements (WRITE bytes) / element offset (WRITE bytes) |
| 32..33 / 34..35 | payload bytes / zero |
| 36..43 / 44..47 | WRITE full-message base address / rkey; otherwise zero |
| 48..49 / 50..51 | BF16 gate weight for DISPATCH/RETURN, otherwise zero / zero |
| 52..54 / 55 | SACK base / SACK status; otherwise zero |
| 56..63 | zero |

Frame length=110+payload bytes, IPv4 length=96+payload bytes, UDP length=76+
payload bytes. Nonfinal fragments contain 256 bytes; final is the exact nonzero
remainder (256 when divisible). Offsets are canonical fragment boundaries and
fit declared total. BF16 payload words are little endian. WRITE is raw and
zeroes expert/rank/K/weight.

CRC32C covers the 64-byte X5 header and payload only, reflected polynomial
82f63b78, initial/final XOR ffffffff; trailer is least-significant byte first.
All validation precedes any payload side effect or commitment.

SACK is raw, final, 32-byte payload, zero count/offset/token/expert/rank/K/
address/rkey/weight. PSN echoes the triggering data PSN. Payload byte j carries
logical bits 8*j..8*j+7 LSB first. A SACK neither consumes receive-window state
nor allocates a transmit data PSN and never generates another SACK.
TX data path=tx_psn[1:0]. Advance each QP's 24-bit PSN once per locally
completed data packet, never while stalled. Packet-boundary round-robin among
SACK, WRITE, DISPATCH and RETURN prevents starvation and byte interleaving.

## Receive tracking and memory protection

d=(PSN-base) modulo 2^24. d<256 is in-window; 256<=d<2^23 is ahead;
d>=2^23 or an already-set bit is duplicate. Physical bitmap indices use PSN
low eight bits. Direct placement is message address+fragment byte offset.
Validate rkey and the entire message against the region using 65-bit overflow
checks. Commit only after the final memory beat transfers, or a full MoE
fragment is stored under valid ownership. Cancel/semantic rejection leaves
base/bitmap unchanged. Old replay recognition precedes retired-context lookup.
New PSNs cannot overwrite an existing MoE fragment.

Every trusted data decision generates an actual immutable post-decision SACK:
0 committed, 1 duplicate, 2 ahead, 3 cancelled/semantic rejection. Integrity,
framing, unknown-QP and protection failures generate events without an
untrusted SACK. QP configuration atomically reloads base and clears bitmap.
Normalized snapshots cannot have bit zero set: fill offsets 1..255 then close
the gap to observe all 256 retirements.

## MoE numerical and identity rules

Select K largest signed two's-complement 16-bit scores over enabled routes;
equal scores choose smaller expert ID. Scores are not weights. Capture selected
expert, configured QP, rank, BF16 weight, format and count with token ownership.
K is 1..MAX_K and no greater than enabled route count. Multiple experts can
share a QP. Retain exact FP8/BF16 activation/result bits when packetizing.

FP8 is E4M3FN: sign7, exponent6:3, fraction2:0, bias7, exponent-zero
subnormals, finite exponent15 except fraction7, either-sign fraction7 NaN.
Decode finite values exactly to BF16 and preserve signed zero; NaN becomes
7fc0. BF16 has IEEE binary semantics including gradual subnormals and RNE.
For each element, in selected-rank order:

```
p[r] = BF16_RNE(weight[r] * decoded_return[r])
a[0] = +0
a[r+1] = BF16_RNE(a[r] + p[r])
output = a[K]
```

No hidden softmax, normalization, conversion or single-round host sum.
Overflow produces signed infinity. Invalid/NaN results canonicalize to 7fc0.
Zero product sign is XOR. Exact additive cancellation is +0; -0 plus -0 is -0.

RETURN checks active token, expected QP, expert, rank, K, count, format and
weight. Reassemble by full identity and element offset, not arrival order or
slot truncation. DISPATCH accepts fragments in either order and produces one
job after complete assembly. Expert meta[8*j+:8] is header byte j, normalized
to offset=0, payload_bytes=full activation length, final=1, PSN=0, path=0.
Response echoes normalized metadata and QP exactly. RETURN swaps QPNs and
uses new transmit PSNs. Each context's output order is element order;
completed-context arbitration is round robin.

## Verification and claim-to-evidence index

Independent Verifier owns all `tests/*`, including `tests/verify.py`. Required
commands from the delivered root (outputs are new exclusive suffixed runs):

```
python3 tests/verify.py --suite behavior --output-prefix evidence/l1-behavior
python3 tests/verify.py --suite synthesis --output-prefix evidence/l1-synthesis
python3 tests/verify.py --suite mutations --output-prefix evidence/l1-mutations
python3 tests/verify.py --suite portable --output-prefix evidence/l1-portable
```

No arguments runs all L1 suites. Dependencies: Python 3, Icarus/vvp,
Verilator, Yosys; actual versions belong in fresh receipts. No private paths,
local JTAG/BDF settings or final-report prerequisite belongs in these suites.

| Claim | Required independent evidence (not yet established) |
|---|---|
| Bit-exact behavior, framing, resets and legacy compatibility | behavior receipt, independent integer/rational oracle, public-output comparisons |
| Geometry/seed coverage | tiny64, tiny512, odd, default64, default512, upper, each seeds 17/89/203 |
| Tracker coverage | each run >=1024 commits, >=256 duplicates, offsets 0..255, modular boundaries, gap closure, cancel, configuration and serialized SACKs |
| MoE coverage | each run >=32 tokens, >=16 each format, every legal K/route, identity errors, reverse returns, all context slots, two communicating tops |
| Numerical corners | all 256 FP8 codes; BF16 zeros/subnormals/halfway/NaN/inf/overflow/cancellation; exact staged multiply/add |
| Defect detection | eight compiling disposable mutations, observed output mismatches, unchanged oracle and passing controls |
| Synthesizable feature connectivity | real tiny64/default512/upper coarse Yosys, mapped reorder/multiply, complete inspected netlists, no div/mod/latches/multiple drivers |
| Portable reproduction | clean declared-source copy, compact real Icarus/Verilator token+reorder and tiny-top Yosys |
| Target timing | shared runtime native timing lint and Quartus 17.1 STA, setup WNS>=0, valid hold and no unexplained unconstrained datapath |
| Physical bridge | shared runtime native Arria 10 GX PCIe Gen3x8 gate, three consecutive deterministic passes under its stated claim boundary |
| Final product PDF | runtime-authored and independently reviewed only after engineering acceptance |

The admitted matrix, detailed inherited-coverage requirements, illegal-parameter
matrix, cycle bounds and eight mutation definitions remain mandatory; this
index does not replace them. A tool exit alone is not functional or structural
acceptance. All four checks are append-only and self-contained. Retain failed
receipts; repair with a fresh run, not by replacing prior evidence.

Source manifest: `rtl/*.sv`, `design/*.md`, Verifier-owned `tests/*`, and the
explicitly supplied read-only `furnace_x4_reference/rtl/*.sv`. Runtime metadata,
compiler trees and account/session state are not deliverable sources. Fresh
receipts must record content hashes of this manifest and actual artifacts;
there is currently no accepted X5 result to cite.
