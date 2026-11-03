"""Independent legacy Ethernet/IP parsing, Toeplitz, TCAM and CRC expectations."""

import json
import struct

from oracle import internet_checksum, reflected_crc


DEFAULT_KEY = int("6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa00", 16)


def toeplitz(tuple_bytes, key):
    value = 0
    for bit in range(len(tuple_bytes) * 8):
        if tuple_bytes[bit // 8] & (128 >> (bit & 7)):
            value ^= (key >> (328 - 32 - bit)) & 0xffffffff
    return value


def packet(*, version=4, protocol=17, port=1000, tags=(), extensions=()):
    payload = b"legacy-independent"
    transport = (struct.pack("!HHHH", port, 4792, 8 + len(payload), 0)
                 if protocol == 17 else
                 struct.pack("!HHIIBBHHH", port, 4792, 0x1234, 0, 0x50, 0x10,
                             1024, 0, 0))
    if protocol == 6:
        transport += payload
    else:
        transport += payload
    if version == 4:
        ip = bytearray(struct.pack("!BBHHHBBH", 0x45, 0, 20 + len(transport),
                                   0, 0x4000, 64, protocol, 0) +
                       bytes.fromhex("0a0102030a040506"))
        ip[10:12] = internet_checksum(bytes(ip)).to_bytes(2, "big")
        body = bytes(ip) + transport
        ethertype = 0x0800
    else:
        extension_bytes = bytearray()
        for index, kind in enumerate(extensions):
            following = extensions[index + 1] if index + 1 < len(extensions) else protocol
            length = 12 if kind == 51 else 8
            extension_bytes.extend(bytes([following, 1 if kind == 51 else 0]) +
                                   bytes(length - 2))
        ip = (struct.pack("!IHBB", 0x60000000, len(extension_bytes) + len(transport),
                          extensions[0] if extensions else protocol, 64) +
              bytes.fromhex("20010db8000000000000000000000001"
                            "20010db8000000000000000000000002"))
        body, ethertype = ip + bytes(extension_bytes) + transport, 0x86dd
    ethernet = bytes.fromhex("02030405060708090a0b0c0d")
    for tag in tags:
        ethernet += struct.pack("!HH", 0x8100, tag)
    return ethernet + ethertype.to_bytes(2, "big") + body


def parse(frame):
    """Decode fields by byte slicing; no simulation or RTL state is an oracle input."""
    header = 0
    unsupported = False
    try:
        if not 14 <= len(frame) <= 9216:
            raise ValueError("Ethernet size")
        header |= int.from_bytes(frame[0:6], "big") << 393
        header |= int.from_bytes(frame[6:12], "big") << 345
        cursor, ethertype, tags = 14, int.from_bytes(frame[12:14], "big"), []
        while ethertype in {0x8100, 0x88a8}:
            if len(tags) == 2:
                unsupported = True
                break
            if cursor + 4 > len(frame):
                raise ValueError("truncated VLAN")
            tags.append(int.from_bytes(frame[cursor:cursor + 2], "big") & 4095)
            ethertype = int.from_bytes(frame[cursor + 2:cursor + 4], "big")
            cursor += 4
        header |= ethertype << 329
        header |= len(tags) << 303
        for index, tag in enumerate(tags):
            header |= tag << (305 + 12 * index)
        if unsupported or ethertype not in {0x0800, 0x86dd}:
            return header | (1 << 442), b"", False
        fragment = False
        if ethertype == 0x0800:
            if cursor + 20 > len(frame) or frame[cursor] >> 4 != 4:
                raise ValueError("IPv4 fixed header")
            ihl = (frame[cursor] & 15) * 4
            length = int.from_bytes(frame[cursor + 2:cursor + 4], "big")
            if ihl < 20 or length < ihl or cursor + length > len(frame):
                raise ValueError("IPv4 length")
            flags = int.from_bytes(frame[cursor + 6:cursor + 8], "big")
            if flags & 0x8000:
                raise ValueError("IPv4 reserved fragment flag")
            fragment = bool(flags & 0x3fff)
            source, destination = frame[cursor + 12:cursor + 16], frame[cursor + 16:cursor + 20]
            protocol = frame[cursor + 9]
            version, end = 4, cursor + length
            header |= int.from_bytes(source, "big")
            header |= int.from_bytes(destination, "big") << 128
            cursor += ihl
            noninitial = bool(flags & 0x1fff)
        else:
            if cursor + 40 > len(frame) or frame[cursor] >> 4 != 6:
                raise ValueError("IPv6 fixed header")
            end = cursor + 40 + int.from_bytes(frame[cursor + 4:cursor + 6], "big")
            if end > len(frame):
                raise ValueError("IPv6 length")
            source, destination = frame[cursor + 8:cursor + 24], frame[cursor + 24:cursor + 40]
            protocol = frame[cursor + 6]
            version = 6
            header |= int.from_bytes(source, "big")
            header |= int.from_bytes(destination, "big") << 128
            cursor += 40
            noninitial, ext_count, fragment_seen = False, 0, False
            while protocol in {0, 43, 60, 44, 51}:
                ext_count += 1
                if ext_count > 8:
                    unsupported = True
                    break
                if cursor + 8 > end:
                    raise ValueError("truncated IPv6 extension")
                length = (8 if protocol == 44 else (frame[cursor + 1] + 2) * 4
                          if protocol == 51 else (frame[cursor + 1] + 1) * 8)
                if length < 8 or cursor + length > end:
                    raise ValueError("IPv6 extension length")
                if protocol == 44:
                    if fragment_seen:
                        raise ValueError("duplicate fragment header")
                    fragment_seen = True
                    fragment_word = int.from_bytes(frame[cursor + 2:cursor + 4], "big")
                    noninitial, fragment = bool(fragment_word & 0xfff8), bool(fragment_word & 0xfff9)
                protocol = frame[cursor]
                cursor += length
                if noninitial:
                    break
        header |= (version << 296) | (1 << 300) | (int(fragment) << 302) | (protocol << 288)
        tuple_bytes = b""
        if not unsupported and not noninitial and protocol in {6, 17}:
            minimum = 20 if protocol == 6 else 8
            if cursor + minimum > end:
                raise ValueError("truncated transport")
            if protocol == 6:
                length = (frame[cursor + 12] >> 4) * 4
                if length < 20 or cursor + length > end:
                    raise ValueError("TCP data offset")
            else:
                length = int.from_bytes(frame[cursor + 4:cursor + 6], "big")
                if length < 8 or (not fragment and cursor + length > end):
                    raise ValueError("UDP length")
            sport, dport = frame[cursor:cursor + 2], frame[cursor + 2:cursor + 4]
            header |= (int.from_bytes(sport, "big") << 256)
            header |= (int.from_bytes(dport, "big") << 272) | (1 << 301)
            if not fragment:
                tuple_bytes = source + destination + sport + dport + bytes([protocol])
        elif protocol not in {6, 17, 59}:
            unsupported = True
        header |= int(unsupported) << 442
        eligible = bool(tuple_bytes) and not unsupported
        return header, tuple_bytes if eligible else b"", eligible
    except ValueError:
        return (1 << 441) | (int(unsupported) << 442), b"", False


def stimulus(directory):
    rules = {}
    rss_key, default_action = DEFAULT_KEY, 0
    operations, expected = [], []

    def configure(op, index=0, value=0, mask=0, action=0, enable=0, key=0):
        nonlocal rss_key, default_action
        operations.append(f"C {op} {index} {value.to_bytes(64,'little').hex()} "
                          f"{mask.to_bytes(64,'little').hex()} {action} {enable} "
                          f"{key.to_bytes(41,'little').hex()}")
        if op == 0:
            rules[index] = (value, mask, action, enable)
        elif op == 1:
            rss_key = key
        elif op == 2:
            rules.clear()
        else:
            default_action = action

    def receive(frame):
        header, tuple_bytes, eligible = parse(frame)
        matches = [(index, action) for index, (value, mask, action, enable) in rules.items()
                   if enable and ((header ^ value) & mask) == 0]
        index, action = min(matches) if matches else (0, default_action)
        operations.append("P " + frame.hex())
        expected.append(dict(frame=frame.hex(), header=header.to_bytes(64, "little").hex(),
                             packet_bytes=len(frame), rss_hash=toeplitz(tuple_bytes, rss_key),
                             eligible=int(eligible), hit=int(bool(matches)), index=index,
                             action=action, crc32=reflected_crc(frame, 32, 0x82f63b78),
                             crc64=reflected_crc(frame, 64, 0x9a6c9329ac4bc9b5)))

    for version in (4, 6):
        for protocol in (6, 17):
            for tags in ((), (3,), (3, 4095)):
                receive(packet(version=version, protocol=protocol, tags=tags))
    for extension in (0, 43, 60, 44, 51):
        receive(packet(version=6, extensions=(extension,)))
    receive(packet(version=6, protocol=6, extensions=(0, 43, 60, 51)))
    configure(1, key=int.from_bytes(bytes(range(41)), "big"))
    receive(packet(version=4))
    receive(packet(version=6))
    receive(packet()[:10])
    malformed = bytearray(packet())
    malformed[14] = 0x64
    receive(bytes(malformed))
    receive(packet()[:-20])
    unsupported = bytearray(packet())
    unsupported[12:14] = b"\x12\x34"
    receive(bytes(unsupported))
    for index in range(64):
        configure(0, index=index, value=(1000 + index) << 256,
                  mask=65535 << 256, action=0x10000000 + index, enable=1)
    for index in range(64):
        receive(packet(port=1000 + index))
    configure(0, index=0, mask=0, action=0xaaaaaaaa, enable=1)
    receive(packet(port=1063))
    configure(0, index=0, enable=0)
    receive(packet(port=1063))
    configure(0, index=63, value=1063 << 256, mask=65535 << 256, action=0xbbbbbbbb, enable=1)
    receive(packet(port=1063))
    configure(0, index=17, value=0xabc0 << 256, mask=0xfff0 << 256, action=0x11111111, enable=1)
    receive(packet(port=0xabc7))
    configure(2)
    configure(3, action=0x87654321)
    receive(packet())
    (directory / "legacy.txt").write_text(str(len(operations)) + "\n" +
                                         "\n".join(operations) + "\n")
    (directory / "legacy-expectations.json").write_text(json.dumps(expected, indent=2) + "\n")
    return expected


def validate(directory, expected):
    observed = [{"PAYLOAD": [], "META": [], "CRC": []} for _ in range(2)]
    concurrent = set()
    for line in (directory / "legacy-trace.txt").read_text().splitlines():
        fields = line.split()
        kind, node = fields[0], int(fields[1])
        if kind == "CONCURRENT":
            concurrent.add(node)
            continue
        observed[node][kind].append(fields[3:])
    if concurrent != {0, 1}:
        raise AssertionError("missing live concurrent legacy/X5 comparisons")
    for node in range(2):
        for kind in observed[node]:
            if len(observed[node][kind]) != len(expected):
                raise AssertionError(f"legacy node{node} missing {kind} comparisons")
        for index, record in enumerate(expected):
            if observed[node]["PAYLOAD"][index] != [record["frame"]]:
                raise AssertionError(f"legacy payload mismatch node{node} packet{index}")
            meta = observed[node]["META"][index]
            expected_meta = [record["header"], *[str(record[field]) for field in
                             ("packet_bytes", "rss_hash", "eligible", "hit", "index", "action")]]
            if meta != expected_meta:
                raise AssertionError(f"legacy metadata mismatch node{node} packet{index}: "
                                     f"{meta} != {expected_meta}")
            crc = [int(value) for value in observed[node]["CRC"][index]]
            if crc != [record["crc32"], record["crc64"], 0, 0]:
                raise AssertionError(f"legacy CRC mismatch node{node} packet{index}")
    return dict(legacy_packets=2 * len(expected), legacy_tcam_indices=64,
                legacy_crc_comparisons=2 * len(expected),
                legacy_rss_comparisons=2 * len(expected))
