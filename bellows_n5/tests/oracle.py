"""Exact integer reference for the frozen X5 floating-point and CRC formats."""

import random
import struct


def rne_shift(value, shift):
    if shift <= 0:
        return value << -shift
    quotient, remainder = divmod(value, 1 << shift)
    halfway = 1 << (shift - 1)
    return quotient + (remainder > halfway or
                       (remainder == halfway and (quotient & 1)))


def pack_bf16(sign, magnitude, scale):
    """Round magnitude * 2**scale once, without using host floating point."""
    if not magnitude:
        return sign << 15
    leading = magnitude.bit_length() - 1
    exponent = leading + scale + 127
    if exponent <= 0:
        rounded = rne_shift(magnitude, -133 - scale)
        return (sign << 15) | rounded
    rounded = rne_shift(magnitude, leading - 7)
    if rounded == 256:
        rounded = 128
        exponent += 1
    if exponent >= 255:
        return (sign << 15) | 0x7f80
    return (sign << 15) | (exponent << 7) | (rounded & 127)


def decode_bf16(bits):
    sign, exponent, fraction = bits >> 15, (bits >> 7) & 255, bits & 127
    if exponent == 255:
        return sign, "nan" if fraction else "inf", 0
    return sign, (128 + fraction) if exponent else fraction, (
        exponent - 134 if exponent else -133)


def bf16_mul(a, b):
    sa, ma, ea = decode_bf16(a)
    sb, mb, eb = decode_bf16(b)
    if ma == "nan" or mb == "nan":
        return 0x7fc0
    if ma == "inf" or mb == "inf":
        if ma == 0 or mb == 0:
            return 0x7fc0
        return ((sa ^ sb) << 15) | 0x7f80
    return pack_bf16(sa ^ sb, ma * mb, ea + eb)


def bf16_add(a, b):
    sa, ma, ea = decode_bf16(a)
    sb, mb, eb = decode_bf16(b)
    if ma == "nan" or mb == "nan":
        return 0x7fc0
    if ma == "inf" or mb == "inf":
        if ma == mb == "inf" and sa != sb:
            return 0x7fc0
        return a if ma == "inf" else b
    common = min(ea, eb)
    total = (-1 if sa else 1) * (ma << (ea - common))
    total += (-1 if sb else 1) * (mb << (eb - common))
    sign = int(total < 0) if total else int(ma == mb == 0 and sa and sb)
    return pack_bf16(sign, abs(total), common)


def fp8_to_bf16(bits):
    sign, exponent, fraction = bits >> 7, (bits >> 3) & 15, bits & 7
    if exponent == 15 and fraction == 7:
        return 0x7fc0
    return pack_bf16(sign, 8 + fraction if exponent else fraction,
                     exponent - 10 if exponent else -9)


def combine(weights, values, fp8=False):
    accumulator = 0
    for weight, value in zip(weights, values, strict=True):
        decoded = fp8_to_bf16(value) if fp8 else value
        accumulator = bf16_add(accumulator, bf16_mul(weight, decoded))
    return accumulator


def reflected_crc(data, width, polynomial):
    mask = (1 << width) - 1
    accumulator = mask
    for byte in data:
        accumulator ^= byte
        for _ in range(8):
            accumulator = ((accumulator >> 1) ^
                           (polynomial if accumulator & 1 else 0))
    return accumulator ^ mask


def internet_checksum(data):
    padded = data + bytes(len(data) & 1)
    total = sum(int.from_bytes(padded[i:i + 2], "big")
                for i in range(0, len(padded), 2))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return total ^ 65535


def x5_header(kind, *, destination=1, source=2, psn=0, token=0,
              expert=0, rank=0, k=0, count=0, offset=0, payload_bytes=1,
              format=2, final=True, address=0, rkey=0, weight=0,
              sack_base=0, sack_status=0):
    header = bytearray(64)
    header[:8] = b"FX5!\x01" + bytes([kind, format, int(final)])
    for start, width, value in [
            (8, 3, destination), (12, 3, psn), (16, 3, source),
            (20, 4, token), (24, 2, expert), (26, 1, rank), (27, 1, k),
            (28, 2, count), (30, 2, offset), (32, 2, payload_bytes),
            (36, 8, address), (44, 4, rkey), (48, 2, weight),
            (52, 3, sack_base), (55, 1, sack_status)]:
        header[start:start + width] = value.to_bytes(width, "big")
    header[15] = psn & 3
    return bytes(header)


def ethernet_frame(header, payload, *, outgoing=False):
    assert len(header) == 64
    assert int.from_bytes(header[32:34], "big") == len(payload)
    local_mac, remote_mac = bytes.fromhex("020000000001"), bytes.fromhex("020000000002")
    local_ip, remote_ip = bytes([10, 0, 0, 1]), bytes([10, 0, 0, 2])
    source_mac, dest_mac = (local_mac, remote_mac) if outgoing else (remote_mac, local_mac)
    source_ip, dest_ip = (local_ip, remote_ip) if outgoing else (remote_ip, local_ip)
    ip = bytearray(struct.pack("!BBHHHBBH", 0x45, 0, 96 + len(payload),
                               0, 0x4000, 64, 17, 0) + source_ip + dest_ip)
    ip[10:12] = internet_checksum(bytes(ip)).to_bytes(2, "big")
    udp = struct.pack("!HHHH", 49152 + header[15], 4792, 76 + len(payload), 0)
    crc = reflected_crc(header + payload, 32, 0x82f63b78)
    return (dest_mac + source_mac + b"\x08\x00" + bytes(ip) + udp +
            header + payload + crc.to_bytes(4, "little"))


def arithmetic_vectors(seed=17, random_count=20000):
    corners = [0, 0x8000, 1, 2, 0x7e, 0x7f, 0x80, 0x81,
               0x3e80, 0x3f00, 0x3f01, 0x3f7f, 0x3f80, 0x3f81,
               0x3fc0, 0x3fff, 0x4000, 0x7f7e, 0x7f7f,
               0x7f80, 0xff80, 0x7f81, 0x7fc0, 0xffff]
    for a in corners:
        for b in corners:
            yield a, b
            yield a ^ 0x8000, b
    # Exhaust both retained parities and every low significand product.
    for a in range(0x3f00, 0x4000):
        for b in range(0x3f00, 0x4000):
            yield a, b
    rng = random.Random(seed)
    for _ in range(random_count):
        yield rng.randrange(65536), rng.randrange(65536)
