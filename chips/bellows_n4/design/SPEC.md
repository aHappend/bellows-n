# BELLOWS-N4 frozen implementation contract

Status: design specification, not verification or timing evidence. The admitted
work order is authoritative. Top: `bellows_n4_top`; target: Intel Arria 10 GX
10AX115N2F45E1SG, one `clk`, asynchronous active-low `rst_n`, period <=10 ns.
No clock gating, combinational division/remainder, proprietary floating IP, or
host-copy placement is permitted.

## Provenance and delivery

The supplied input is `furnace_x3_reference/rtl/*.sv` (sixteen modules).
No repository intake/source index or `design/GENERATIONAL_HANDOFF.md` was
provided. No historical parent STA or PPA is asserted. Parent reference files
are immutable; deliverable copies retain their behavior and hierarchy.
Independent verification owns `tests/*.py`; the shared runtime owns timing,
hardware gates and the post-acceptance product PDF.

## Interfaces and legality

All parent top-level ports and defaults are retained. `DATA_WIDTH` is 64 or 512
(default 512), `MAX_PACKET_BYTES` is 1..9216 (default 9216), `MAX_SG` is 1..16
(default 16), and `QPS` is 1..8 (default 8). Invalid values produce an explicit
`PARAMETER ERROR`; diagnostic port widths are at least one. Small legal buffers
reject frames they cannot contain. Byte zero is bits 7:0; keep bit zero
qualifies byte zero. Network headers are big-endian; tensor elements are
little-endian. All new outputs, including ready and idle, are zero in reset.

The added top interfaces are the admitted `roce_enable/roce_idle`,
`qp_cfg_*`, `coll_cfg_*`, `wr_*`, `rdma_evt_*`, `ack_*`, and `coll_done_*`
interfaces, with exactly the widths and encodings of the admitted work order.
Configuration and response channels are retained ready/valid transactions.
QP configuration has priority over simultaneous collective configuration;
either has priority over the first beat of a new packet. Pending configuration
responses prevent another configuration. Configuration cannot interrupt receive,
placement, an active collective, or an unconsumed completion.

Enabled QPs have unique full 24-bit local QPNs, positive region length and no
64-bit end-address overflow. Failed configuration preserves the old state.
QP status: 0 OK, 1 index/QPN, 2 region, 3 collective configuration. Collective
status uses 0 OK, 2 invalid address/range, 3 invalid shape/rank/configuration.
Ranks uniquely cover 0..N-1; all participant regions contain the vector.
Disabled collective configuration ends the idle job. Reconfiguration clears
contributor state. `roce_enable` changes only while the whole subsystem is idle.
Disabled mode adds no dependency to the parent data, CRC or metadata paths.

`wr_addr` is the exact byte address of lane zero, including unaligned addresses.
Each accepted keep bit irrevocably writes its byte. Last keep is a nonempty low
prefix. `wr_last` marks the final beat, not an invented PCIe completion.
Every captured frame produces one retained receive event:

| Status | Meaning |
|---|---|
| 0 | ordinary protected placement committed |
| 1 | collective contribution committed |
| 2 | non-RoCE bypass |
| 3 | malformed, truncated or oversize |
| 4 | unsupported opcode/header |
| 5 | unknown/disabled QP |
| 6 | PSN mismatch |
| 7 | protection, RETH or message length |
| 8 | collective job/rank/shape |
| 9 | ICRC |
| 10 | received ACK/NAK |

Absent event fields are zero. Event QPN/PSN are populated only after a bounded,
trusted BTH decode; expected PSN is populated only after QP lookup.
Independent branch acceptance forks the actual legacy payload to the external
stream and receive storage. Neither branch duplicates on a stall. The following
packet waits for receive retirement; CRC and metadata retain their independent
parent handshakes. Oversize frames drain to last without wrapping storage.

## Wire formats and validation

Accept Ethernet II, up to two 8100/88a8 VLAN tags, IPv4 IHL 5..15 without
fragmentation, or fixed-header IPv6 with next-header UDP. UDP destination is
4791. IP and UDP lengths bound parsing; trailing Ethernet padding is ignored.
IPv4 header checksum is validated using a 21-bit unfolded sum of up to thirty
16-bit header words (IHL=15). Fold all five upper carry bits into the low
16 bits, then fold the remaining carry; the result must equal ffff.
The surrounding NIC supplies UDP checksum
validation, including mandatory IPv6 UDP checksum validation; this subsystem
does not claim that ICRC substitutes for a UDP checksum.

BTH byte layout: opcode, solicited/migration/pad/version, P_Key (ffff),
reserved-high/destination-QPN, ACK-request/reserved/PSN. Transport version and
reserved bits must be zero. Support 06 FIRST, 07 MIDDLE, 08 LAST, 09 LAST+IMM,
0a ONLY, 0b ONLY+IMM, and 11 ACK. FIRST/ONLY RETH is VA64/R_Key32/length32,
big-endian. Immediate is four bytes following BTH/RETH and before payload.
ACK is BTH+AETH, with no placement or receive-PSN modification.
IB padding (BTH bits 5:4) is excluded from tensor and placement lengths.
Unrecognized forms receive explicit errors, never guessed payload offsets.

### Frozen RoCE invariant CRC

ICRC uses reflected IEEE CRC32, polynomial `32'hedb88320`, register initialized
to all ones, bits of each byte processed least-significant first, final bitwise
complement. Feed eight virtual ff LRH octets, then the IP header through the
last IB padding octet. Do not feed Ethernet/VLAN or the four received ICRC
octets. The received ICRC is the complemented register transmitted least
significant octet first. These masks apply only to CRC calculation, not parsing:

| Field | Substituted octets/bits |
|---|---|
| IPv4 TOS (IP+1), TTL (+8), checksum (+10,+11) | ff |
| IPv6 first four octets | first = original OR 0f; next three = ff |
| IPv6 hop limit (+7) | ff |
| UDP checksum (UDP+6,+7) | ff |
| BTH reserved destination-QPN high octet (BTH+4) | ff |

All other bytes, including IP version/IHL, lengths, IPv6 next-header, UDP ports,
BTH opcode, PSN, RETH, immediate, payload and IB pad, are fed unchanged.
ICRC validation precedes any state mutation or irreversible write. Legacy
CRC32C and CRC64-NVME are separate computations.

## Transport commitment

QP lookup compares all QPN bits. Expected PSN is explicitly seeded by config;
accepted packet commitment advances it once modulo 2^24. Previous-PSN duplicates
are sequence events and may repeat the prior ACK, but never write/update again.
Other mismatches produce sequence NAK at the expected PSN.
FIRST opens a message only if none is open; MIDDLE/LAST require one; ONLY
requires none. Retain initial RETH and committed offset. Validate widened
address arithmetic, key, region, entire packet length and message accounting
before writes. LAST exactly finishes the declared message; earlier valid
segments survive a later rejection. Rejected packets leave state unchanged.
For MIDDLE/LAST (including LAST+IMM), the event address is the retained initial
RETH address plus committed offset only while a message is open. Without an
open message, reject with status 7 and report address zero, never a stale
address from a completed message. Open-message addresses, protection checks,
PSN/state commitment and ACK/NAK behavior are unchanged.

ACK output is the actual sixteen-byte BTH+AETH, byte zero in bits 7:0:
opcode 11, flags/version zero, P_Key ffff, reserved zero, remote QPN,
ACK-request/reserved zero, PSN, syndrome, 24-bit MSN, all multibyte fields
network order. Syndrome 00 ACK, 60 sequence NAK, 61 invalid request,
62 remote access error. MSN increments per completed successful message,
not per segment. ACK PSN is accepted PSN; sequence NAK PSN is expected PSN.
No ACK precedes required final write acceptance. Unknown or untrusted headers
do not generate a misdirected ACK. Received ACK/NAK never elicits an ACK.

## Collective numerical contract

One job consumes rank-ordered unique contributors 0..N-1, N=1..8, using
WRITE_ONLY or ONLY+IMM at the configured address and exact vector length.
Other addresses use ordinary placement. Segmented writes at the collective
address, wrong rank/shape and duplicate contributors with a new PSN are rejected.
The first contributor is copied bit-exactly, not reduced against an implicit
zero. Subsequent contributors round after each rank. Only the final contributor
writes the complete vector; N=1 copies and completes. Completion follows final
write acceptance and is held until consumed. No partial host results.

Formats 0/1/2 = INT16/BF16/FP32; operations 0/1/2 = SUM/MAX/MIN.
Encoding 3 is invalid. Byte length is positive, an element multiple, and fits
one legal WRITE_ONLY frame within the buffer (minimum Ethernet/IPv4 envelope
is 74 bytes plus IB pad). Incomplete elements are shape errors.
INT16 sum wraps modulo 65536; comparisons are signed.
BF16/FP32 sum is IEEE RNE with gradual underflow and signed infinity overflow.
BF16 rounds at each contribution. Any NaN or opposite infinities in SUM yields
canonical 7fc0/7fc00000. Exact cancellation is +0; -0+-0 is -0.
MIN/MAX are minimumNumber/maximumNumber: a lone NaN returns the other operand
unchanged; two NaNs return canonical NaN. Zero ties yield -0 MIN, +0 MAX.
Equal nonzero operands select left. Inactive lane data/keep is zero.

Completed jobs retain their collective address reservation until disabled or
reconfigured; a contributor with a fresh PSN cannot turn into an ordinary
overwrite just because completion was consumed. Configuration is available
again after completion consumption. QP configuration is blocked while a job
is active, including before its first contributor.

Successful receive events report the post-commit expected PSN; sequence/error
events report the unchanged expected PSN. A previous-PSN ACK replay requires
an actual prior commitment since QP configuration, not merely arithmetic
equality with the configured seed minus one. Empty ordinary segments are
permitted when message accounting permits them: no empty-keep write is emitted,
but transport commitment and completion/ACK ordering still apply.

Validation precedence is frame bounds/shape, non-RoCE classification,
unsupported outer header, remaining IP/UDP/BTH shape, ICRC, then transport and
collective checks. Validly authenticated unsupported opcodes retain status 4;
an identified enabled QP may receive invalid-request NAK. IPv4 fragmentation
and IPv6 extension forms are unsupported (status 4), not interpreted as
ordinary UDP RoCE. The UDP length including IB padding is a multiple of four;
received ACK requires zero IB pad and exactly BTH+AETH+ICRC.

## Cycle & degenerate-boundary table

All transfer decisions use pre-edge valid/ready/data. Post-edge state belongs
to the following cycle. Sources retain valid/payload until accepted.

| Boundary | Required behavior |
|---|---|
| Reset asserted | new visible data, status, ready, valid and idle zero |
| First released edge | no phantom transaction; reset-disabled QPs remain disabled |
| QPS=1 or 3 | explicit range check, no low-bit QPN/index alias |
| MAX_PACKET_BYTES=1 | finite capture/drain, no out-of-range RAM access |
| MAX_SG=1, first && last | retained parent single-beat semantics |
| Non-power-of-two lengths | explicit bounds, no binary-mask wrap assumption |
| Configuration and first beat | configuration wins; QP wins over collective |
| Response consume and new config | no overwrite of a pending response |
| Accumulator read/write | synchronous read; drain previous rank before next rank |
| Output stall | payload/sidebands hold; no advance or duplicate commit |
| Reset during work | discard uncommitted state; prior accepted writes irrevocable |
| Final result write and completion | completion becomes visible only after write edge |

### Exact arithmetic stages

`furnace_reduce_alu` has exactly eight globally enabled registered stages.
Global advance is `!out_valid || out_ready`, reset gated. All stages and
sidebands freeze together when false; initiation interval is one whole beat.

| Edge after acceptance E0 | Stage | Work |
|---|---|---|
| E0 | 1 | unpack numerical lanes and effective exponents |
| E1 | 2 | classify special values, order magnitude and select min/max |
| E2 | 3 | align smaller significand with sticky jam |
| E3 | 4 | add/subtract or select |
| E4 | 5 | leading-zero tree and normalization decision |
| E5 | 6 | normalize, retaining gradual subnormal precision |
| E6 | 7 | ties-to-even rounding, overflow and result selection |
| E7 | 8 | packed result and valid |

Earliest consumption is pre-E8. Latency counts advancing edges, not wall-clock
cycles through stalls. Inactive complete lanes remain zero. Integer and min/max
operations traverse the same eight stages. The floating arithmetic is integer
significand/exponent logic, not host-real arithmetic.

Other leaf operations use handshaked variable-latency controllers (parser,
PSN validation/commit, placement, collective replay); they make no fixed
packet-latency claim. Memory reads are synchronous one-edge reads. The byte
scanner and CRC recurrence consume one byte per advancing scan edge, distinct
from full-width tensor replay. A replay read register precedes full-width
ALU input; accumulator output writes occur on ALU output acceptance.

## Acceptance and reproduction ownership

The independent entry point is `python3 tests/verify.py`, from the delivered
root. It owns actual simulation, independent protocol/numerical references,
mutation sensitivity, legacy regressions, parameter matrices, Yosys synthesis
and clean-directory partial reproduction. All admitted matrix sizes and
coverage thresholds remain mandatory; none are replaced by this document.
Designer performs at most static elaboration, not functional or synthesis
verification. Native runtime gates establish timing lint, Quartus 17.1 STA
at <=10 ns and physical Arria 10 PCIe Gen3x8 HIL. No current pass, resource,
throughput or timing measurement is implied by architectural intent.
