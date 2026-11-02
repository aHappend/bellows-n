"""Independent byte-level RoCE and integer-only tensor reference models."""

import struct
import zlib


DEFAULT_RSS_KEY = int(
    "6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa00", 16)


def toeplitz(data, key=DEFAULT_RSS_KEY):
    value = 0
    for offset in range(len(data) * 8):
        if data[offset // 8] & (128 >> (offset & 7)):
            value ^= (key >> (328 - 32 - offset)) & 0xffffffff
    return value


def legacy_header(frame):
    """Decode the documented public 512-bit header record, not parser states."""
    fields = 0

    def put(value, bit):
        nonlocal fields
        fields |= value << bit

    if len(frame) < 14 or len(frame) > 9216:
        return 1 << 441, 0, False
    put(int.from_bytes(frame[:6], "big"), 393)
    put(int.from_bytes(frame[6:12], "big"), 345)
    position = 12
    ether_type = int.from_bytes(frame[position:position + 2], "big")
    tags = []
    while ether_type in (0x8100, 0x88a8) and len(tags) < 2:
        if len(frame) < position + 6:
            return (1 << 441), 0, False
        tags.append(int.from_bytes(frame[position + 2:position + 4], "big") & 4095)
        position += 4
        ether_type = int.from_bytes(frame[position:position + 2], "big")
    put(ether_type, 329)
    put(len(tags), 303)
    for i, tag in enumerate(tags):
        put(tag, 305 + 12 * i)
    ip = position + 2
    unsupported = False
    fragmented = False
    l4 = None
    protocol = 0
    if ether_type == 0x0800:
        if len(frame) < ip + 20:
            return 1 << 441, 0, False
        ihl = (frame[ip] & 15) * 4
        end = ip + int.from_bytes(frame[ip + 2:ip + 4], "big")
        if frame[ip] >> 4 != 4 or ihl < 20 or end > len(frame) or end < ip + ihl:
            return 1 << 441, 0, False
        put(4, 296)
        protocol = frame[ip + 9]
        source = frame[ip + 12:ip + 16]
        dest = frame[ip + 16:ip + 20]
        put(int.from_bytes(source, "big"), 0)
        put(int.from_bytes(dest, "big"), 128)
        fragment = int.from_bytes(frame[ip + 6:ip + 8], "big")
        if fragment & 0x8000:
            return 1 << 441, 0, False
        fragmented = bool(fragment & 0x3fff)
        if not fragment & 0x1fff:
            l4 = ip + ihl
    elif ether_type == 0x86dd:
        if len(frame) < ip + 40 or frame[ip] >> 4 != 6:
            return 1 << 441, 0, False
        end = ip + 40 + int.from_bytes(frame[ip + 4:ip + 6], "big")
        if end > len(frame):
            return 1 << 441, 0, False
        put(6, 296)
        source = frame[ip + 8:ip + 24]
        dest = frame[ip + 24:ip + 40]
        put(int.from_bytes(source, "big"), 0)
        put(int.from_bytes(dest, "big"), 128)
        protocol = frame[ip + 6]
        l4 = ip + 40
        extensions = 0
        while protocol in (0, 43, 44, 51, 60):
            if l4 + 8 > end or extensions >= 8:
                return 1 << 441, 0, False
            next_header = frame[l4]
            length = (8 if protocol == 44 else
                      (frame[l4 + 1] + 2) * 4 if protocol == 51 else
                      (frame[l4 + 1] + 1) * 8)
            if length < 8 or l4 + length > end:
                return 1 << 441, 0, False
            if protocol == 44:
                frag = int.from_bytes(frame[l4 + 2:l4 + 4], "big")
                fragmented = bool(frag & 0xfff9)
                if frag & 0xfff8:
                    l4 = None
                    protocol = next_header
                    break
            l4 += length
            protocol = next_header
            extensions += 1
    else:
        return fields | (1 << 442), 0, False
    put(protocol, 288)
    put(1, 300)
    put(int(fragmented), 302)
    ports = b""
    if l4 is not None and protocol in (6, 17):
        length = 8 if protocol == 17 else 20
        if l4 + length > end:
            return 1 << 441, 0, False
        if protocol == 17:
            udp_bytes = int.from_bytes(frame[l4 + 4:l4 + 6], "big")
            if udp_bytes < 8 or (not fragmented and l4 + udp_bytes > end):
                return 1 << 441, 0, False
        elif (frame[l4 + 12] >> 4) < 5 or l4 + (frame[l4 + 12] >> 4) * 4 > end:
            return 1 << 441, 0, False
        ports = frame[l4:l4 + 4]
        put(int.from_bytes(ports[:2], "big"), 256)
        put(int.from_bytes(ports[2:], "big"), 272)
        put(1, 301)
    elif protocol not in (6, 17) and not (ether_type == 0x86dd and protocol == 59):
        unsupported = True
    put(int(unsupported), 442)
    eligible = bool(ports) and not fragmented and not unsupported
    rss = toeplitz(source + dest + ports + bytes([protocol])) if eligible else 0
    return fields, rss, eligible


def crc_reflected(data, width, polynomial):
    state = (1 << width) - 1
    for octet in data:
        state ^= octet
        for _ in range(8):
            state = (state >> 1) ^ (polynomial if state & 1 else 0)
    return state ^ ((1 << width) - 1)


def internet_checksum(data):
    if len(data) & 1:
        data += b"\0"
    total = sum(int.from_bytes(data[i:i + 2], "big")
                for i in range(0, len(data), 2))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def invariant_crc(ip_packet):
    """IEEE CRC over virtual LRH and invariant IP/UDP/IB octets, without ICRC."""
    data = bytearray(ip_packet)
    version = data[0] >> 4
    if version == 4:
        udp = (data[0] & 15) * 4
        for i in (1, 8, 10, 11):
            data[i] = 255
    elif version == 6:
        udp = 40
        data[0] |= 15
        for i in (1, 2, 3, 7):
            data[i] = 255
    else:
        raise ValueError("IP version")
    data[udp + 6:udp + 8] = b"\xff\xff"
    data[udp + 12] = 255
    return zlib.crc32(b"\xff" * 8 + data).to_bytes(4, "little")


def roce_frame(payload, *, version=4, tags=(), options=b"", opcode=10,
               qpn=0x123456, psn=17, addr=0x1003, rkey=0xabcdef01,
               message_bytes=None, immediate=0x1234abcd, aeth=0,
               trailing=b"", tos=0, ttl=64, source=b"\xc0\x00\x02\x01",
               destination=b"\xc6\x33\x64\x02"):
    if len(options) > 40 or len(options) & 3:
        raise ValueError("IPv4 options length")
    if message_bytes is None:
        message_bytes = len(payload)
    pad = (-len(payload)) & 3
    bth = bytes((opcode, pad << 4)) + b"\xff\xff\0"
    bth += qpn.to_bytes(3, "big") + b"\0" + psn.to_bytes(3, "big")
    extension = b""
    if opcode in (6, 10, 11):
        extension += struct.pack(">QII", addr, rkey, message_bytes)
    if opcode in (9, 11):
        extension += immediate.to_bytes(4, "big")
    if opcode == 17:
        extension += aeth.to_bytes(4, "big")
    ib = bth + extension + payload + bytes(pad)
    udp = struct.pack(">HHHH", 12345, 4791, 8 + len(ib) + 4, 0)
    if version == 4:
        header = bytearray(struct.pack(
            ">BBHHHBBH4s4s", 0x45 + len(options) // 4, tos,
            20 + len(options) + len(udp) + len(ib) + 4,
            0x3210, 0x4000, ttl, 17, 0, source, destination) + options)
        header[10:12] = internet_checksum(bytes(header)).to_bytes(2, "big")
    elif version == 6:
        header = bytearray(struct.pack(">IHBB16s16s", 0x6abc1234,
                                      len(udp) + len(ib) + 4, 17, ttl,
                                      bytes.fromhex("20010db8000000000000000000000001"),
                                      bytes.fromhex("20010db8000000000000000000000002")))
    else:
        raise ValueError("IP version")
    ip = bytes(header) + udp + ib
    ethernet = bytes.fromhex("020000000002020000000001")
    for i, tpid in enumerate(tags):
        ethernet += struct.pack(">HH", tpid, i + 1)
    ethernet += struct.pack(">H", 0x0800 if version == 4 else 0x86dd)
    return ethernet + ip + invariant_crc(ip) + trailing


def round_even(integer, shift):
    if shift <= 0:
        return integer << -shift
    quotient, remainder = divmod(integer, 1 << shift)
    half = 1 << (shift - 1)
    return quotient + int(remainder > half or
                          (remainder == half and quotient & 1))


def numerical(a, b, fmt, op):
    """Correctly rounded binary arithmetic using exact signed integer sums."""
    if fmt == 0:
        if op == 0:
            return (a + b) & 65535
        sa = a - 65536 if a & 32768 else a
        sb = b - 65536 if b & 32768 else b
        return a if (sa >= sb if op == 1 else sa <= sb) else b
    fraction = 7 if fmt == 1 else 23
    sign_bit = 1 << (fraction + 8)
    mask = sign_bit - 1
    fraction_mask = (1 << fraction) - 1
    canonical = (255 << fraction) | (1 << (fraction - 1))

    def decode(x):
        exp = (x >> fraction) & 255
        mantissa = x & fraction_mask
        return bool(x & sign_bit), exp, mantissa

    sa, ea, fa = decode(a)
    sb, eb, fb = decode(b)
    na, nb = ea == 255 and fa != 0, eb == 255 and fb != 0
    if op != 0:
        if na and nb:
            return canonical
        if na:
            return b
        if nb:
            return a
        if (a & mask) == 0 and (b & mask) == 0:
            return sign_bit if (sa and sb if op == 1 else sa or sb) else 0
        if a == b:
            return a
        less = sa if sa != sb else ((a & mask) > (b & mask) if sa
                                   else (a & mask) < (b & mask))
        return (b if less else a) if op == 1 else (a if less else b)
    if na or nb or (ea == eb == 255 and sa != sb):
        return canonical
    if ea == 255:
        return a
    if eb == 255:
        return b
    # A common unit 2**(1-bias-fraction) represents every finite operand
    # exactly, including all subnormals; no host float enters the oracle.
    ma = fa | ((1 << fraction) if ea else 0)
    mb = fb | ((1 << fraction) if eb else 0)
    va = ma << (max(ea, 1) - 1)
    vb = mb << (max(eb, 1) - 1)
    value = (-va if sa else va) + (-vb if sb else vb)
    if value == 0:
        return sign_bit if sa and sb else 0
    sign = sign_bit if value < 0 else 0
    magnitude = abs(value)
    shift = max(0, magnitude.bit_length() - (fraction + 1))
    significand = round_even(magnitude, shift)
    if significand >= 1 << (fraction + 1):
        significand >>= 1
        shift += 1
    if significand < 1 << fraction:
        return sign | significand
    exponent = shift + 1
    if exponent >= 255:
        return sign | (255 << fraction)
    return sign | (exponent << fraction) | (significand & fraction_mask)


def self_check():
    check = b"123456789"
    assert crc_reflected(check, 32, 0x82f63b78) == 0xe3069283
    assert crc_reflected(check, 64, 0x9a6c9329ac4bc9b5) == 0xae8b14860a799888
    assert zlib.crc32(check) == 0xcbf43926
    for fmt, one, infinity, nan, negative_zero in (
            (1, 0x3f80, 0x7f80, 0x7fc0, 0x8000),
            (2, 0x3f800000, 0x7f800000, 0x7fc00000, 0x80000000)):
        assert numerical(one, one, fmt, 0) == one + (1 << (7 if fmt == 1 else 23))
        assert numerical(one, one | negative_zero, fmt, 0) == 0
        assert numerical(infinity, infinity | negative_zero, fmt, 0) == nan
        assert numerical(negative_zero, 0, fmt, 2) == negative_zero
        assert numerical(negative_zero, 0, fmt, 1) == 0
        assert numerical(nan, one, fmt, 1) == one
        assert numerical(1, 1, fmt, 0) == 2
