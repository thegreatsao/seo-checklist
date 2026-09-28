"""An image's format and intrinsic dimensions, read from its first bytes.

Moved out of `favicon_check.py` at 0.108.0, when `image_weight_audit.py` needed the
same reading to tell a large image from an icon. One reader, two callers: a copy would
have been a second place for a defect to live — and moving it found one, in WebP.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET


def _positive_dimensions(width: int, height: int) -> tuple[int, int] | None:
    return (width, height) if width > 0 and height > 0 else None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if (data[:8] != b"\x89PNG\r\n\x1a\n" or data[8:12] != b"\x00\x00\x00\x0d"
            or data[12:16] != b"IHDR" or len(data[:33]) != 33):
        return None
    return _positive_dimensions(*struct.unpack(">II", data[16:24]))


def _ico_dimensions(data: bytes) -> tuple[int, int] | None:
    if data[:4] != b"\x00\x00\x01\x00" or len(data[4:6]) != 2:
        return None
    count = int.from_bytes(data[4:6], "little")
    if count < 1 or len(data) < 6 + count * 16:
        return None
    sizes = []
    for offset in range(6, 6 + count * 16, 16):
        width = data[offset] or 256
        height = data[offset + 1] or 256
        sizes.append((width, height))
    # An ICO is a menu of representations. Clients choose the largest suitable one,
    # so judging only its first (often 16px) entry would reject a usable icon.
    return max(sizes, key=lambda size: (min(size), size[0] * size[1]))


def _gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if data[:6] not in (b"GIF87a", b"GIF89a") or len(data[6:10]) != 4:
        return None
    return _positive_dimensions(*struct.unpack("<HH", data[6:10]))


JPEG_SOF_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if data[:2] != b"\xff\xd8":
        return None
    cursor = 2
    while cursor < len(data):
        while cursor < len(data) and data[cursor] != 0xFF:
            cursor += 1
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            return None
        marker = data[cursor]
        cursor += 1
        if marker in (0x01, 0xD8, 0xD9) or marker in range(0xD0, 0xD8):
            continue
        if cursor + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[cursor:cursor + 2], "big")
        if segment_length < 2 or cursor + segment_length > len(data):
            return None
        if marker in JPEG_SOF_MARKERS:
            if len(data[cursor:cursor + 7]) != 7:
                return None
            height = int.from_bytes(data[cursor + 3:cursor + 5], "big")
            width = int.from_bytes(data[cursor + 5:cursor + 7], "big")
            return _positive_dimensions(width, height)
        cursor += segment_length
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    cursor = 12
    while cursor + 8 <= len(data):
        kind = data[cursor:cursor + 4]
        size = int.from_bytes(data[cursor + 4:cursor + 8], "little")
        payload = cursor + 8
        # The dimensions sit in the first ten bytes of the chunk, and each branch
        # below checks it has them. Requiring the *whole* chunk first was harmless
        # while the only caller read whole favicons; `image_weight_audit.py` reads a
        # prefix, and a lossy WebP past it would never have reported a width.
        if kind == b"VP8X" and len(data[payload:payload + 10]) == 10:
            width = 1 + int.from_bytes(data[payload + 4:payload + 7], "little")
            height = 1 + int.from_bytes(data[payload + 7:payload + 10], "little")
            return _positive_dimensions(width, height)
        if (kind == b"VP8L" and len(data[payload:payload + 5]) == 5
                and data[payload] == 0x2F):
            b1, b2, b3, b4 = data[payload + 1:payload + 5]
            width = 1 + b1 + ((b2 & 0x3F) << 8)
            height = 1 + (b2 >> 6) + (b3 << 2) + ((b4 & 0x0F) << 10)
            return _positive_dimensions(width, height)
        if (kind == b"VP8 " and len(data[payload:payload + 10]) == 10
                and data[payload + 3:payload + 6] == b"\x9d\x01\x2a"):
            width = int.from_bytes(data[payload + 6:payload + 8], "little") & 0x3FFF
            height = int.from_bytes(data[payload + 8:payload + 10], "little") & 0x3FFF
            return _positive_dimensions(width, height)
        if payload + size > len(data):
            return None
        cursor = payload + size + (size % 2)
    return None


def _bmp_dimensions(data: bytes) -> tuple[int, int] | None:
    """The DIB header's size is its version, an identity rather than a bound:
    BITMAPCOREHEADER (12 bytes) carries 16-bit sizes; BITMAPINFOHEADER and every
    later version (V2–V5, OS/2's 64) carry signed 32-bit ones, where a negative
    height is a top-down bitmap."""
    size_field = data[14:18]
    if data[:2] != b"BM" or len(size_field) != 4:
        return None
    header_size = int.from_bytes(size_field, "little")
    if header_size == 12:
        sizes = data[18:22]
        return (_positive_dimensions(*struct.unpack("<HH", sizes))
                if len(sizes) == 4 else None)
    sizes = data[18:26]
    if header_size not in (40, 52, 56, 64, 108, 124) or len(sizes) != 8:
        return None
    width, height = struct.unpack("<ii", sizes)
    return _positive_dimensions(width, abs(height))


def _netpbm_name(magic: bytes) -> str | None:
    return {b"P1": "pbm", b"P2": "pgm", b"P3": "ppm",
            b"P4": "pbm", b"P5": "pgm", b"P6": "ppm"}.get(magic)


def _netpbm_dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height after a Netpbm magic: whitespace-separated ASCII, `#` comments."""
    if _netpbm_name(data[:2]) is None:
        return None
    tokens = []
    for line in data[2:].split(b"\n"):
        for token in line.split(b"#", 1)[0].split():
            tokens.append(token)
            if len(tokens) == 2:
                if not all(token.isdigit() for token in tokens):
                    return None
                return _positive_dimensions(int(tokens[0]), int(tokens[1]))
    return None


def _tiff_dimensions(data: bytes) -> tuple[int, int] | None:
    """ImageWidth (tag 256) and ImageLength (257) from the first IFD, each a SHORT
    (type 3, two bytes) or a LONG (type 4, four), in 12-byte entries."""
    width_tag, length_tag, entry_bytes = 256, 257, 12
    value_bytes = {3: 2, 4: 4}
    byte_order = {b"II*\0": "<", b"MM\0*": ">"}.get(data[:4])
    offset_field = data[4:8]
    if byte_order is None or len(offset_field) != 4:
        return None
    endian = "little" if byte_order == "<" else "big"
    ifd_offset = int.from_bytes(offset_field, endian)
    count_field = data[ifd_offset:ifd_offset + 2]
    if len(count_field) != 2:
        return None
    start = ifd_offset + 2
    entries = data[start:start + int.from_bytes(count_field, endian) * entry_bytes]
    dimensions = {}
    for index in range(0, len(entries) - len(entries) % entry_bytes, entry_bytes):
        tag, value_type, count = struct.unpack(byte_order + "HHI",
                                               entries[index:index + 8])
        size = value_bytes.get(value_type)
        if tag in (width_tag, length_tag) and count == 1 and size:
            dimensions[tag] = int.from_bytes(entries[index + 8:index + 8 + size], endian)
    if width_tag not in dimensions or length_tag not in dimensions:
        return None
    return _positive_dimensions(dimensions[width_tag], dimensions[length_tag])


def _svg_dimensions(root) -> tuple[int, int] | None:
    def pixels(value: str | None) -> int | None:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*", value or "", re.I)
        if not match:
            return None
        number = float(match.group(1))
        return round(number) if number > 0 else None

    width, height = pixels(root.get("width")), pixels(root.get("height"))
    if width and height:
        return width, height
    view_box = re.split(r"[\s,]+", (root.get("viewBox") or "").strip())
    if len(view_box) == 4:
        try:
            return _positive_dimensions(round(float(view_box[2])), round(float(view_box[3])))
        except ValueError:
            pass
    return None


def image_header(data: bytes) -> tuple[str, int | None, int | None] | None:
    """Return a recognised image format and its intrinsic dimensions."""
    probes = (
        ("png", _png_dimensions),
        ("ico", _ico_dimensions),
        ("gif", _gif_dimensions),
        ("jpeg", _jpeg_dimensions),
        ("webp", _webp_dimensions),
        ("bmp", _bmp_dimensions),
        ("netpbm", _netpbm_dimensions),
        ("tiff", _tiff_dimensions),
    )
    for name, probe in probes:
        dimensions = probe(data)
        if dimensions:
            if probe is _netpbm_dimensions:
                name = _netpbm_name(data[:2])
            return name, dimensions[0], dimensions[1]
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError):
        return None
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        return None
    dimensions = _svg_dimensions(root)
    return ("svg", dimensions[0], dimensions[1]) if dimensions else ("svg", None, None)
