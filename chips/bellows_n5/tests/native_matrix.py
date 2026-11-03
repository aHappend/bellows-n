"""Compiled two-peer public-interface experiment and independent trace oracle."""

import json
from pathlib import Path
import random
import re
import shutil

from oracle import combine, ethernet_frame, x5_header


GEOMETRIES = {
    "tiny64": (64, 1, 1, 1, 1, 1, 1, 1),
    "tiny512": (512, 1, 1, 1, 1, 1, 1, 1),
    "odd": (64, 511, 3, 3, 3, 3, 3, 65),
    "default64": (64, 9216, 16, 8, 8, 4, 4, 256),
    "default512": (512, 9216, 16, 8, 8, 4, 4, 256),
    "upper": (512, 9216, 16, 8, 16, 4, 8, 256),
}
PARAMETERS = ("DATA_WIDTH", "MAX_PACKET_BYTES", "MAX_SG", "QPS",
              "EXPERTS", "MAX_K", "TOKENS", "MAX_TOKEN_ELEMS")


def build(run, geometry, rtl_root=None, label=None):
    root = rtl_root or run.root
    directory = run.output / ("native-" + (label or geometry))
    directory.mkdir()
    values = GEOMETRIES[geometry]
    top = (root / "rtl/bellows_n5_top.sv").read_text()
    header = top.split(") (", 1)[1].split("\n);", 1)[0]
    inputs = []
    for line in header.splitlines():
        match = re.fullmatch(r"\s*input wire\s*(\[[^]]+\])?\s*(.*?)\s*,?\s*", line)
        if match:
            inputs.extend(name.strip() for name in match[2].rstrip(",").split(","))
    (directory / "geometry.h").write_text(
        "\n".join(f"#define X5_{name} {value}" for name, value in zip(PARAMETERS, values)) +
        "\ntemplate<class T> void clear_inputs(T& m) {\n" +
        "\n".join(f"    put(m.{name}, {{0}});" for name in inputs) + "\n}\n")
    obj = directory / "compile-obj"
    command = ["verilator", "--cc", "--exe", "--build", "-j", "4", "-Wno-fatal",
               "--top-module", "bellows_n5_top", "--Mdir", run.relative(obj),
               "-CFLAGS", f"-I{directory.resolve()}",
               *["-G" + name + "=" + str(value)
                 for name, value in zip(PARAMETERS, values)],
               *[str(p.relative_to(run.root)) for p in sorted((root / "rtl").glob("*.sv"))],
               str((run.root / "tests/fabric.cpp").resolve())]
    run.command(command)
    executable = directory / "fabric"
    shutil.copyfile(obj / "Vbellows_n5_top", executable)
    executable.chmod(0o755)
    shutil.rmtree(obj)
    return executable


def stimulus(directory, geometry, seed, token_count=32):
    _, _, _, qps, experts, max_k, slots, max_elems = GEOMETRIES[geometry]
    rng = random.Random(seed)
    tokens = {}
    with (directory / "tokens.txt").open("x") as stream:
        stream.write(f"{token_count}\n")
        for index in range(token_count):
            token = 0x51200000 + 101 * index + seed * 65536
            fmt = index & 1
            lengths = [1, max_elems, min(max_elems, 128), min(max_elems, 129)]
            count = lengths[(index // 2) % len(lengths)]
            k = max_k if index < slots else 1 + ((index // 2) % max_k)
            scores = [rng.randrange(-32768, 32768) for _ in range(experts)]
            if index % 4 == 0:
                scores = [-5] * experts
            if index >= 16:
                scores = [-1000 - ((e - index) % experts) for e in range(experts)]
            weights = [rng.choice([0, 0x8000, 1, 0x7f, 0x80, 0x3f80,
                                   0xbf80, 0x3f00, 0x3f81, 0x7f80,
                                   0x7fc0, 0x7f7f]) for _ in range(experts)]
            activation = bytes(rng.randrange(256) for _ in range(count << fmt))
            results = [bytes(rng.randrange(256) for _ in range(count << fmt))
                       for _ in range(experts)]
            if index == 5 and max_k >= 3:
                scores = [-5] * experts
                weights = [0x3f80] * experts
                samples = [0x4780, 0xc780, 0x3f80]
                results = [samples[e % 3].to_bytes(2, "little") * count
                           for e in range(experts)]
            ids = sorted(range(experts), key=lambda e: (-scores[e], e))[:k]
            expected = bytearray()
            for j in range(count):
                samples = [int.from_bytes(results[e][j << fmt:(j + 1) << fmt], "little")
                           for e in ids]
                expected.extend(combine([weights[e] for e in ids], samples,
                                        fp8=fmt == 0).to_bytes(2, "little"))
            tokens[token] = dict(format=fmt, count=count, k=k, scores=scores,
                                 weights=weights, activation=activation,
                                 results=results, ids=ids, combined=bytes(expected))
            stream.write(f"{token} {fmt} {count} {k} " +
                         " ".join(f"{v & 65535:x}" for v in scores + weights) + " " +
                         activation.hex() + " " +
                         " ".join(v.hex() for v in results) + "\n")
    return tokens


def packet_stimulus(directory, geometry, seed, compact=False):
    qps = GEOMETRIES[geometry][3]
    bases = [0xffff80] * qps
    committed = [set() for _ in range(qps)]
    rng = random.Random(seed)
    records = []

    def append(qp, psn, *, variant=None):
        psn &= 0xffffff
        payload = bytes([(psn ^ (psn >> 8) ^ seed) & 255])
        header = x5_header(1, destination=2 * qp + 1, source=2 * qp + 2,
                           psn=psn, token=0x5a000000 | psn, count=1,
                           payload_bytes=1, address=0x2000, rkey=0x01020304)
        status = 0
        if variant == "cancel":
            header = x5_header(3, destination=2 * qp + 1, source=2 * qp + 2,
                               psn=psn, token=0x5a000000 | psn, count=1,
                               k=1, payload_bytes=1, format=0, weight=0x3f80)
            status = 7
        if variant == "rkey":
            header = bytearray(header)
            header[47] ^= 1
            status = 6
        if variant == "endpoint":
            header = bytearray(header)
            header[18] ^= 0x80
            status = 5
        if variant == "reserved":
            header = bytearray(header)
            header[11] = 1
            status = 3
        frame = bytearray(ethernet_frame(bytes(header), payload))
        if variant == "crc":
            frame[-1] ^= 1
            status = 4
        if variant == "checksum":
            frame[24] ^= 1
            status = 4
        trusted = variant in {None, "cancel"}
        memory = None
        sack = None
        if trusted:
            distance = (psn - bases[qp]) & 0xffffff
            if distance >= 1 << 23 or psn in committed[qp]:
                status = 1
            elif distance >= 256:
                status = 2
            elif status == 0:
                committed[qp].add(psn)
                memory = payload.hex()
                while bases[qp] in committed[qp]:
                    committed[qp].remove(bases[qp])
                    bases[qp] = (bases[qp] + 1) & 0xffffff
            bitmap = sum(1 << ((p - bases[qp]) & 0xffffff) for p in committed[qp])
            sack_header = x5_header(4, destination=qp * 2 + 2, source=qp * 2 + 1,
                                    psn=psn, payload_bytes=32, sack_base=bases[qp],
                                    sack_status=3 if status == 7 else status)
            sack = ethernet_frame(sack_header, bitmap.to_bytes(32, "little"),
                                  outgoing=True).hex()
        identity = status in {0, 1, 2, 6, 7}
        records.append(dict(frame=bytes(frame).hex(), status=status, qp=qp if identity else 0,
                            kind=header[5] if identity else 0,
                            token=(0x5a000000 | psn) if identity else 0,
                            psn=psn if identity else 0, sack=sack, memory=memory))

    if compact:
        append(0, bases[0] + 1)
        append(0, bases[0] + 1)
        append(0, bases[0] + 256)
    for block in range(0 if compact else 4):
        qp = block % qps
        base = bases[qp]
        offsets = list(range(1, 256))
        rng.shuffle(offsets)
        for offset in offsets:
            append(qp, base + offset)
        append(qp, base)
    for replay in range(0 if compact else 256):
        qp = replay % qps
        append(qp, bases[qp] - 1)
    for qp in range(0 if compact else qps):
        for distance in (256, (1 << 23) - 1, 1 << 23):
            append(qp, bases[qp] + distance)
    if not compact:
        for variant in ("cancel", "rkey", "endpoint", "reserved", "crc", "checksum"):
            append(0, bases[0], variant=variant)
        append(0, bases[0])
    (directory / "packets.txt").write_text(
        str(len(records)) + "\n" + "\n".join(record["frame"] for record in records) + "\n")
    (directory / "packet-expectations.json").write_text(json.dumps(records, indent=2) + "\n")
    return records


def validate_packets(directory, records, thresholds=True):
    expected_events = [(r["status"], r["kind"], r["qp"], r["token"], r["psn"])
                       for r in records]
    expected_sacks = [r["sack"] for r in records if r["sack"] is not None]
    expected_mem = [r["memory"] for r in records if r["memory"] is not None]
    events, sacks, memory = [], [], []
    for line in (directory / "probe-trace.txt").read_text().splitlines():
        fields = line.split()
        kind, node = fields[0], int(fields[1])
        if node != 0:
            continue
        if kind == "EVT":
            events.append(tuple(int(v) for v in fields[3:]))
        elif kind == "TX":
            sacks.append(fields[3])
        elif kind == "MEM":
            if int(fields[3]) != 0x2000:
                raise AssertionError("direct placement address mismatch")
            memory.append(fields[4])
        elif kind not in {"RX"}:
            raise AssertionError(f"unexpected packet-probe record: {line}")
    if events != expected_events:
        mismatch = next((i for i, pair in enumerate(zip(events, expected_events))
                         if pair[0] != pair[1]), min(len(events), len(expected_events)))
        raise AssertionError(f"packet event mismatch index={mismatch}: "
                             f"{events[mismatch:mismatch+1]} != "
                             f"{expected_events[mismatch:mismatch+1]}")
    if sacks != expected_sacks:
        raise AssertionError("serialized SACK mismatch")
    if memory != expected_mem:
        raise AssertionError("direct-placement bytes/multiplicity mismatch")
    counts = dict(committed_packets=len(memory), duplicates=sum(r["status"] == 1 for r in records),
                  ahead=sum(r["status"] == 2 for r in records), compared_sacks=len(sacks),
                  cancelled=sum(r["status"] == 7 for r in records), events=len(events))
    if thresholds and (counts["committed_packets"] < 1024 or counts["duplicates"] < 256):
        raise AssertionError("missing receive-window public comparisons")
    counts["receive_probe_events"] = counts.pop("events")
    return counts


def validate(directory, geometry, tokens, token_count=32):
    """Reconstruct commitments and numeric expectations from complete public records."""
    _, _, _, qps, experts, max_k, slots, _ = GEOMETRIES[geometry]
    receive_base = [[0] * qps for _ in range(2)]
    received = [[set() for _ in range(qps)] for _ in range(2)]
    transmit_psn = [[0] * qps for _ in range(2)]
    expected_sacks = [{}, {}]
    expected_peers = [[], []]
    dispatches, returns, requests, combines, completions = {}, {}, {}, {}, {}
    partial_jobs = {}
    active_contexts, active_jobs = [set(), set()], [set(), set()]
    max_contexts, max_jobs = [0, 0], [0, 0]
    counts = dict(network_packets=0, dispatch_packets=0, return_packets=0,
                  sack_packets=0, events=0, peer_sacks=0, expert_jobs=0,
                  combined_bytes=0, completions=0, invalid_expert_response=0,
                  malformed_expert_response=0)

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    for line_number, line in enumerate((directory / "trace.txt").read_text().splitlines(), 1):
        fields = line.split()
        kind, node, cycle = fields[0], int(fields[1]), int(fields[2])
        context = f"trace line {line_number} {kind} node={node} cycle={cycle}"
        if kind == "CMD":
            token, format, count, k = (int(value) for value in fields[3:])
            check(token in tokens and format == tokens[token]["format"] and
                  count == tokens[token]["count"] and k == tokens[token]["k"],
                  context + ": accepted command")
            check(token not in active_contexts[node], context + ": duplicate command acceptance")
            active_contexts[node].add(token)
            max_contexts[node] = max(max_contexts[node], len(active_contexts[node]))
        elif kind in {"TX", "RX"}:
            frame = bytes.fromhex(fields[3])
            h, payload = frame[42:106], frame[106:-4]
            packet_kind = h[5]
            destination = int.from_bytes(h[8:11], "big")
            source = int.from_bytes(h[16:19], "big")
            qp = ((source if kind == "TX" else destination) - 1) // 2
            check(0 <= qp < qps, context + ": QPN index")
            check(source == 2 * qp + 1 + node if kind == "TX"
                  else destination == 2 * qp + 1 + node, context + ": QPN")
            expected_frame = bytearray(ethernet_frame(h, payload, outgoing=node == 0))
            # Node 1's TX and node 0's RX are incoming to the canonical node-0 oracle.
            if kind == "RX":
                expected_frame = bytearray(ethernet_frame(h, payload, outgoing=node == 1))
            check(frame == bytes(expected_frame), context + ": envelope/checksum/CRC")
            psn = int.from_bytes(h[12:15], "big")
            token = int.from_bytes(h[20:24], "big")
            if kind == "TX":
                counts["network_packets"] += 1
                if packet_kind == 4:
                    key = (qp, psn)
                    check(key in expected_sacks[node], context + ": unsolicited SACK")
                    expected = expected_sacks[node].pop(key)
                    check((int.from_bytes(h[52:55], "big"), int.from_bytes(payload, "little"),
                           h[55]) == expected, context + ": SACK snapshot")
                    counts["sack_packets"] += 1
                    continue
                check(psn == transmit_psn[node][qp], context + ": transmit PSN")
                transmit_psn[node][qp] = (psn + 1) & 0xffffff
                check(h[15] == psn & 3, context + ": path spraying")
                check(token in tokens, context + ": token identity")
                data = tokens[token]
                expert, rank = int.from_bytes(h[24:26], "big"), h[26]
                check(rank < data["k"] and expert == data["ids"][rank],
                      context + ": Top-K identity/tie priority")
                check(qp == expert % qps and h[6] == data["format"] and
                      h[27] == data["k"] and int.from_bytes(h[28:30], "big") == data["count"] and
                      int.from_bytes(h[48:50], "big") == data["weights"][expert],
                      context + ": captured routing/numerical metadata")
                offset = int.from_bytes(h[30:32], "big") << data["format"]
                complete = data["activation"] if packet_kind == 2 else data["results"][expert]
                check(packet_kind in {2, 3} and offset % 256 == 0 and
                      payload == complete[offset:offset + 256] and
                      h[7] == int(offset + len(payload) == len(complete)),
                      context + ": packet payload/stride/final")
                target = dispatches if packet_kind == 2 else returns
                key = (node, token, rank, offset)
                check(key not in target, context + ": duplicate data transmission")
                target[key] = True
                if packet_kind == 3 and h[7]:
                    job_key = (token, rank)
                    check(job_key in active_jobs[node], context + ": early remote-job release")
                    active_jobs[node].remove(job_key)
                counts["dispatch_packets" if packet_kind == 2 else "return_packets"] += 1
            elif packet_kind == 4:
                expected_peers[node].append((qp, int.from_bytes(h[52:55], "big"),
                                             payload.hex(), h[55]))
            else:
                distance = (psn - receive_base[node][qp]) & 0xffffff
                check(distance < 256 and psn not in received[node][qp],
                      context + ": unexpected transport replay/window")
                received[node][qp].add(psn)
                while receive_base[node][qp] in received[node][qp]:
                    received[node][qp].remove(receive_base[node][qp])
                    receive_base[node][qp] = (receive_base[node][qp] + 1) & 0xffffff
                bitmap = sum(1 << ((p - receive_base[node][qp]) & 0xffffff)
                             for p in received[node][qp])
                expected_sacks[node][qp, psn] = (receive_base[node][qp], bitmap, 0)
        elif kind == "REQ":
            qp, meta = int(fields[3]), bytes.fromhex(fields[4])
            token = int.from_bytes(meta[20:24], "big")
            check(token in tokens, context + ": unknown expert token")
            data = tokens[token]
            expert, rank = int.from_bytes(meta[24:26], "big"), meta[26]
            check(rank < data["k"] and expert == data["ids"][rank] and qp == expert % qps,
                  context + ": expert job identity")
            expected = x5_header(2, destination=qp * 2 + 1 + node,
                                 source=qp * 2 + 2 - node, token=token,
                                 expert=expert, rank=rank, k=data["k"], count=data["count"],
                                 payload_bytes=len(data["activation"]), format=data["format"],
                                 weight=data["weights"][expert])
            check(meta == expected, context + ": normalized job metadata")
            check((node, token, rank) not in requests, context + ": repeated expert job")
            requests[node, token, rank] = True
            active_jobs[node].add((token, rank))
            max_jobs[node] = max(max_jobs[node], len(active_jobs[node]))
            partial_jobs[node] = (token, rank, bytearray())
            counts["expert_jobs"] += 1
        elif kind == "JOB":
            payload = bytes.fromhex(fields[3])
            token, rank, _ = partial_jobs.pop(node)
            check(payload == tokens[token]["activation"], context + ": expert activation bytes")
        elif kind == "COMBINE":
            token, payload = int(fields[3]), bytes.fromhex(fields[4])
            check(token in tokens and payload == tokens[token]["combined"],
                  context + ": bit-exact ordered BF16 result")
            check((node, token) not in combines, context + ": repeated combined output")
            combines[node, token] = True
            counts["combined_bytes"] += len(payload)
        elif kind == "CPL":
            token, status = int(fields[3]), int(fields[4])
            check(status == 0 and (node, token) in combines and
                  (node, token) not in completions, context + ": completion multiplicity/order")
            completions[node, token] = True
            check(token in active_contexts[node], context + ": completion without ownership")
            active_contexts[node].remove(token)
            counts["completions"] += 1
        elif kind == "EVT":
            status, packet_kind = int(fields[3]), int(fields[4])
            check((status == 0 and packet_kind in {2, 3, 4}) or
                  (status in {7, 9} and packet_kind == 3),
                  context + ": event outcome")
            if status == 7:
                check(all(int(v) == 0 for v in fields[5:]), context + ": untrusted response identity")
                counts["invalid_expert_response"] += 1
            if status == 9:
                check(int(fields[6]) in tokens and int(fields[7]) == 0,
                      context + ": malformed response identity")
                counts["malformed_expert_response"] += 1
            counts["events"] += 1
        elif kind == "PEER":
            check(bool(expected_peers[node]), context + ": unsolicited peer-SACK output")
            qp, base, bitmap, status = fields[3:]
            check((int(qp), int(base), bitmap, int(status)) == expected_peers[node].pop(0),
                  context + ": decoded peer-SACK fields")
            counts["peer_sacks"] += 1
        else:
            raise AssertionError(context + ": unknown trace record")
    expected_fragments = 2 * sum(t["k"] * ((len(t["activation"]) + 255) // 256)
                                for t in tokens.values())
    check(counts["dispatch_packets"] == counts["return_packets"] == expected_fragments,
          "missing dispatch/return comparisons")
    check(counts["expert_jobs"] == 2 * sum(t["k"] for t in tokens.values()),
          "missing complete expert jobs")
    check(len(completions) == 2 * token_count, "missing token completions")
    check(counts["invalid_expert_response"] == counts["malformed_expert_response"] == 2,
          "missing retryable expert-response failures")
    check(not any(expected_sacks) and counts["peer_sacks"] == counts["sack_packets"] ==
          2 * expected_fragments, "missing SACK/peer comparisons")
    check(not any(expected_peers) and not any(active_contexts) and not any(active_jobs),
          "unreleased public ownership")
    check(counts["events"] == 4 * expected_fragments +
          2 * sum(t["k"] for t in tokens.values()) + 4,
          "missing/duplicated received-frame or expert-response events")
    for node in range(2):
        check(max_contexts[node] == min(slots, token_count), "missing full local context occupancy")
        check(max_jobs[node] >= min(slots, token_count) * max_k,
              "missing full remote expert-job occupancy")
    if token_count >= 32:
        check({e for token in tokens.values() for e in token["ids"]} == set(range(experts)),
              "missing configured expert-route comparisons")
        check({t["k"] for t in tokens.values()} == set(range(1, max_k + 1)),
              "missing dynamic K comparisons")
        check(sum(t["format"] == 0 for t in tokens.values()) >= 16 and
              sum(t["format"] == 1 for t in tokens.values()) >= 16,
              "missing token precision thresholds")
    counts["peak_contexts_per_peer"] = max_contexts
    counts["peak_expert_jobs_per_peer"] = max_jobs
    return counts


def matrix(run, geometries=None, seeds=(17, 89, 203), token_count=32):
    results = []
    for geometry in geometries or GEOMETRIES:
        executable = build(run, geometry)
        for seed in seeds:
            directory = run.output / f"{geometry}-seed-{seed}"
            directory.mkdir()
            tokens = stimulus(directory, geometry, seed, token_count)
            packets = packet_stimulus(directory, geometry, seed)
            from legacy import stimulus as legacy_stimulus, validate as validate_legacy
            legacy_expected = legacy_stimulus(directory)
            run.command([run.relative(executable), run.relative(directory), str(seed)])
            packet_counts = validate_packets(directory, packets)
            counts = validate(directory, geometry, tokens, token_count)
            counts.update(packet_counts)
            counts.update(validate_legacy(directory, legacy_expected))
            result = dict(geometry=geometry, parameters=GEOMETRIES[geometry],
                          seed=seed, comparisons=counts)
            results.append(result)
            run.summary["runs"].append(result)
    return results
