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


def _pieces(document: dict, binary) -> list:
    """The GLB file of *document* and *binary* (bytes, or a BufferBuilder: its arrays as they are) as the list of
    its pieces in order: the header, the JSON chunk, the binary chunk's header, its parts and its padding. The
    binary's parts are not copied."""
    text = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * (-len(text) % ALIGNMENT)
    if isinstance(binary, BufferBuilder):
        parts, length = binary.parts, binary.length
    else:
        parts, length = ([memoryview(binary).cast("B")] if len(binary) else []), memoryview(binary).nbytes
    pieces = [struct.pack("<II", len(text), JSON_CHUNK), text]
    if length:
        padding = -length % ALIGNMENT
        pieces += [struct.pack("<II", length + padding, BIN_CHUNK), *parts, b"\0" * padding]
    total = 12 + sum(memoryview(piece).nbytes for piece in pieces)
    return [struct.pack("<III", MAGIC, VERSION, total)] + pieces


def pack(document: dict, binary) -> bytes:
    """A GLB file from its JSON *document* and its *binary* buffer (bytes, or a BufferBuilder)."""
    return b"".join(_pieces(document, binary))


def write(file, document: dict, binary) -> int:
    """The GLB file of *document* and *binary* (bytes, or a BufferBuilder) written to the open binary *file* piece by
    piece, the arrays from their own memory (no copy of the binary chunk); the bytes written. The same bytes as
    pack()'s."""
    written = 0
    for piece in _pieces(document, binary):
        written += file.write(piece)
    return written


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
    """Appends arrays to one binary buffer, each at an 8-byte aligned offset, and records their buffer views. The
    arrays are kept as they are (byte views of their memory), not copied into the buffer: pack() and write() read
    them; *parts* the buffer's pieces in order (the arrays' byte views, the zeros between them), *length* its bytes."""

    def __init__(self):
        self.parts, self.length, self.views = [], 0, []

    def add(self, data, target: int = None, byte_stride: int = None) -> int:
        """Append *data* (bytes or a numpy array, written little-endian); the index of its buffer view. An array is
        not copied (unless it is not contiguous or not little-endian): it must not change before the buffer is
        written."""
        if isinstance(data, np.ndarray):
            data = np.ascontiguousarray(data.astype(data.dtype.newbyteorder("<"), copy=False))
            data = memoryview(data.reshape(-1).view(np.uint8))
        else:
            data = memoryview(data).cast("B")
        self.pad()
        view = {"buffer": 0, "byteOffset": self.length, "byteLength": data.nbytes}
        if byte_stride is not None:
            view["byteStride"] = byte_stride
        if target is not None:
            view["target"] = target
        self.parts.append(data)
        self.length += data.nbytes
        self.views.append(view)
        return len(self.views) - 1

    def pad(self, alignment: int = ALIGNMENT) -> int:
        """Zeros appended up to a multiple of *alignment* bytes; the buffer's length."""
        padding = -self.length % alignment
        if padding:
            self.parts.append(b"\0" * padding)
            self.length += padding
        return self.length

    def binary(self) -> bytes:
        """The buffer as one bytes object (a copy of its parts)."""
        return b"".join(self.parts)


def view_bytes(document: dict, binary: bytes, index: int) -> bytes:
    view = document["bufferViews"][index]
    if view.get("buffer", 0) != 0:
        raise ValueError("encoding3d files keep every buffer view in the GLB binary chunk")
    start = view.get("byteOffset", 0)
    return binary[start:start + view["byteLength"]]


def read_document(path: str) -> dict:
    """The JSON document of the GLB file *path* (in a folder or an archive), its binary chunk not read."""
    from openalea.encoding3d import archive
    inside = archive.split(path)
    if inside is not None:
        stream = archive._zip(inside[0]).open(archive._member(inside[1]))
    else:
        stream = open(path, "rb")
    with stream:
        header = stream.read(20)
        if len(header) < 20:
            raise ValueError(f"{path}: not a GLB file: too short")
        magic, version, _, length, chunk_type = struct.unpack("<IIIII", header)
        if magic != MAGIC or chunk_type != JSON_CHUNK:
            raise ValueError(f"{path}: not a GLB file, or its first chunk is not JSON")
        return json.loads(stream.read(length).decode("utf-8"))
