"""
The GLB container: a 12-byte header (magic, version 2, total length), a JSON chunk padded with spaces, a binary
chunk padded with zeros, each 8-byte aligned (as EXT_structural_metadata requires). Little-endian throughout.
"""
import json
import struct

import numpy as np

MAGIC, VERSION = 0x46546C67, 2                  # b"glTF"
JSON_CHUNK, BIN_CHUNK = 0x4E4F534A, 0x004E4942  # b"JSON", b"BIN\0"
ALIGNMENT = 8


def pack(document: dict, binary: bytes) -> bytes:
    """A GLB file from its JSON *document* and its *binary* buffer."""
    text = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * (-len(text) % ALIGNMENT)
    binary = bytes(binary) + b"\0" * (-len(binary) % ALIGNMENT)
    chunks = struct.pack("<II", len(text), JSON_CHUNK) + text
    if binary:
        chunks += struct.pack("<II", len(binary), BIN_CHUNK) + binary
    return struct.pack("<III", MAGIC, VERSION, 12 + len(chunks)) + chunks


def unpack(data: bytes) -> tuple:
    """(JSON document, binary buffer) of a GLB file (*data*: bytes, or a memoryview: the binary chunk then a view of
    it, not a copy)."""
    if len(data) < 20:
        raise ValueError("not a GLB file: too short")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != MAGIC:
        raise ValueError("not a GLB file: wrong magic")
    if version != VERSION:
        raise ValueError(f"GLB version {version}, 2 expected")
    if length != len(data):
        raise ValueError(f"GLB header length {length}, the file holds {len(data)} bytes")
    offset, document, binary = 12, None, b""
    while offset < length:
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + chunk_length]
        if chunk_type == JSON_CHUNK:
            document = json.loads(bytes(chunk).decode("utf-8"))
        elif chunk_type == BIN_CHUNK:
            binary = chunk
        offset += 8 + chunk_length
    if document is None:
        raise ValueError("GLB file without a JSON chunk")
    return document, binary


class BufferBuilder:
    """Appends arrays to one binary buffer, each at an 8-byte aligned offset, and records their buffer views."""

    def __init__(self):
        self.parts, self.length, self.views = [], 0, []

    def add(self, data, target: int = None, byte_stride: int = None) -> int:
        """Append *data* (bytes or a numpy array, written little-endian); the index of its buffer view."""
        if isinstance(data, np.ndarray):
            data = np.ascontiguousarray(data.astype(data.dtype.newbyteorder("<"), copy=False)).tobytes()
        padding = -self.length % ALIGNMENT
        if padding:
            self.parts.append(b"\0" * padding)
            self.length += padding
        view = {"buffer": 0, "byteOffset": self.length, "byteLength": len(data)}
        if byte_stride is not None:
            view["byteStride"] = byte_stride
        if target is not None:
            view["target"] = target
        self.parts.append(data)
        self.length += len(data)
        self.views.append(view)
        return len(self.views) - 1

    def binary(self) -> bytes:
        return b"".join(self.parts)


def view_bytes(document: dict, binary: bytes, index: int) -> bytes:
    view = document["bufferViews"][index]
    if view.get("buffer", 0) != 0:
        raise ValueError("encoding3d files keep every buffer view in the GLB binary chunk")
    start = view.get("byteOffset", 0)
    return binary[start:start + view["byteLength"]]
