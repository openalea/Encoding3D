"""Writing then reading a frame gives it back: every column bit for bit, declarations, grids, mappings, meshes."""
import io
import json
import struct

import numpy as np
import pytest

import generate
from openalea.encoding3d import (DataStructure, EntitySet, Frame, Mesh, Table, Variable, from_bytes, read_index, read_sequence,
                     to_bytes, write, write_sequence)
from openalea.encoding3d import glb
from openalea.encoding3d.dump import frame_to_dict
from openalea.encoding3d.glb import BufferBuilder, unpack


def same_columns(a, b):
    assert list(a.columns) == list(b.columns)
    for name in a.columns:
        x, y = a.columns[name], b.columns[name]
        assert x.dtype == y.dtype and x.shape == y.shape, name
        assert np.ma.isMaskedArray(x) == np.ma.isMaskedArray(y), name
        if np.ma.isMaskedArray(x):                                    # missing values: the same rows, the same others
            assert np.array_equal(np.ma.getmaskarray(x), np.ma.getmaskarray(y)), name
            assert np.array_equal(x.compressed(), y.compressed()), name
        elif x.dtype.kind == "f":
            assert np.ascontiguousarray(x).tobytes() == np.ascontiguousarray(y).tobytes(), name      # bit for bit
        else:
            assert np.array_equal(x, y), name
    assert a.variables == b.variables


@pytest.mark.parametrize("name", sorted(generate.SCENES))
def test_round_trip(name):
    frame = generate.SCENES[name]()
    again = from_bytes(to_bytes(frame))
    assert (again.time, again.time_unit, again.step) == (frame.time, frame.time_unit, frame.step)
    for written, read in zip(frame.data_structures, again.data_structures):
        assert (written.id, written.kind, written.platform, written.model) == (read.id, read.kind, read.platform,
                                                                               read.model)
        assert np.array_equal(written.origin, read.origin) and written.extras == read.extras
        for a, b in zip(written.entity_sets + written.relations, read.entity_sets + read.relations):
            same_columns(a, b)
        assert [entity_set.rank for entity_set in written.entity_sets] == [s.rank for s in read.entity_sets]
        assert [entity_set.scale for entity_set in written.entity_sets] == [s.scale for s in read.entity_sets]
        assert written.labels == read.labels
        if written.scalars is not None:
            same_columns(written.scalars, read.scalars)
        assert written.grid == read.grid
        for a, b in zip(written.meshes, read.meshes):
            assert np.array_equal(a.positions.astype(np.float32), b.positions)
            assert {k: v.tolist() for k, v in a.feature_rows.items()} == {k: v.tolist() for k, v in b.feature_rows.items()}
    for a, b in zip(frame.mappings, again.mappings):
        same_columns(a, b)
        assert (a.source, a.target, a.method) == (b.source, b.target, b.method)
    assert to_bytes(again) == to_bytes(frame)               # and writing what was read gives the same file


def test_glb_layout():
    data = to_bytes(generate.root_system())
    magic, version, length = struct.unpack_from("<III", data)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    json_length = struct.unpack_from("<I", data, 12)[0]
    assert json_length % 8 == 0 and (len(data) - 12 - 8 - json_length - 8) % 8 == 0
    document, _ = unpack(data)
    assert all(view["byteOffset"] % 8 == 0 for view in document["bufferViews"])
    assert "FSPM_scene" not in document.get("extensionsRequired", [])


def test_buffer_length_holds_the_chunk_padding():
    """A binary chunk of 4 bytes of data is padded to 8: the buffer's byteLength counts the padding, so that the
    chunk is no longer than the buffer (glTF-Validator: BUFFER_GLB_CHUNK_TOO_BIG beyond 3 bytes)."""
    frame = Frame(data_structures=[DataStructure("plants", entity_sets=[
        EntitySet("Plant", columns={"id": np.array([0], dtype=np.int64), "count": np.array([1], dtype=np.int32)},
                  rank=1)])])
    document, binary = unpack(to_bytes(frame))
    assert len(binary) % 8 == 0 and document["buffers"][0]["byteLength"] == len(binary)


@pytest.mark.parametrize("name", sorted(generate.SCENES))
def test_a_written_file_is_to_bytes_file(name, tmp_path):
    """write() streams the GLB piece by piece (the arrays from their own memory, no copy of the binary chunk): the
    same bytes as to_bytes()."""
    frame = generate.SCENES[name]()
    path = tmp_path / "frame.glb"
    write(str(path), frame, embed_parts=True)
    assert path.read_bytes() == to_bytes(frame, embed_parts=True)


def test_the_buffer_keeps_its_arrays_without_copying_them():
    """BufferBuilder holds a byte view of a contiguous little-endian array, not a copy: glb.write writes it from the
    array's memory; pack() joins the same pieces."""
    array = np.arange(5, dtype=np.float64)
    buffers = BufferBuilder()
    buffers.add(b"abc")
    index = buffers.add(array)
    view = buffers.parts[-1]
    assert np.shares_memory(np.frombuffer(view, dtype=np.uint8), array)
    assert buffers.views[index]["byteOffset"] == 8 and buffers.length == 48
    stream = io.BytesIO()
    written = glb.write(stream, {"asset": {}}, buffers)
    assert stream.getvalue() == glb.pack({"asset": {}}, buffers) == glb.pack({"asset": {}}, buffers.binary())
    assert written == len(stream.getvalue())
    document, binary = unpack(stream.getvalue())
    assert np.array_equal(np.frombuffer(bytes(binary)[8:48], dtype=np.float64), array)


def test_column_types():
    columns = dict(id=np.arange(3, dtype=np.int64), f64=np.array([0.1, np.nan, -2.5e-300]),
                   infinite=np.array([np.inf, -np.inf, np.nan]), infinite32=np.array([1., np.inf, -np.inf], dtype=np.float32),
                   f32=np.array([1.5, np.nan, 3.], dtype=np.float32), i32=np.array([-1, 0, 7], dtype=np.int32),
                   u8=np.array([0, 255, 3], dtype=np.uint8), flag=np.array([True, False, True]),
                   text=np.array(["", "é", "racine latérale"], dtype=object), vector=np.arange(6.).reshape(3, 2))
    frame = Frame([DataStructure("d", kind="table", entity_sets=[EntitySet("E", columns=columns)])])
    same_columns(frame.data_structures[0].entity_sets[0], from_bytes(to_bytes(frame)).data_structures[0].entity_sets[0])


def test_ids_are_int64_whatever_the_default_integer():
    segments = EntitySet("E", columns=dict(id=np.array([1, 2], dtype=np.int32), parent=np.array([-1, 1], dtype=np.int32),
                                           edge_type=["none", "successor"], value=np.array([3, 4], dtype=np.int32)))
    assert segments.columns["id"].dtype == segments.columns["parent"].dtype == np.int64
    assert segments.columns["value"].dtype == np.int32                     # a variable keeps its type


def test_many_labels_and_empty_tables():
    labels = np.array([f"L{i}" for i in range(300)], dtype=object)
    full = EntitySet("Big", columns=dict(id=np.arange(300, dtype=np.int64), label=labels))
    empty = EntitySet("Empty", columns=dict(id=np.zeros(0, dtype=np.int64), value=np.zeros(0)))
    frame = Frame([DataStructure("d", kind="table", entity_sets=[full, empty])])
    again = from_bytes(to_bytes(frame)).data_structures[0]
    same_columns(full, again.entity_sets[0])
    same_columns(empty, again.entity_sets[1])


def test_values_that_cannot_be_written():
    def frame_with(**columns):
        return Frame([DataStructure("d", kind="table", entity_sets=[EntitySet("E", columns=columns)])])
    with pytest.raises(ValueError, match="infinities and the values"):
        to_bytes(frame_with(x=[np.inf, np.finfo(np.float64).max]))
    with pytest.raises(ValueError, match="standing for NaN"):
        to_bytes(frame_with(x=[np.nan, np.finfo(np.float64).min]))
    with pytest.raises(ValueError, match="identifier"):
        to_bytes(frame_with(**{"bad name": [1.]}))
    with pytest.raises(ValueError, match="edge_type"):
        to_bytes(frame_with(id=np.arange(2), edge_type=["none", "lateral"]))
    entity_set = EntitySet("E", columns=dict(id=np.arange(2)))
    mesh = Mesh("m", positions=np.zeros((3, 3)), feature_rows={"E": [0, 1, 2]})
    with pytest.raises(ValueError, match="outside"):
        to_bytes(Frame([DataStructure("d", entity_sets=[entity_set], meshes=[mesh])]))


def test_unknown_content_is_kept():
    frame = generate.parameter_set()
    frame.unknown = {"extensions": {"VENDOR_thing": {"a": [1, 2]}}, "extras": {"note": "kept"}}
    data = to_bytes(frame)
    again = from_bytes(data)
    assert again.unknown == frame.unknown
    document, _ = unpack(data)
    assert "VENDOR_thing" in document["extensionsUsed"]


def test_sequence(tmp_path):
    frames = generate.growing_sequence()
    index = write_sequence(str(tmp_path), frames)
    entries = read_index(index)["frames"]
    assert [entry["time"] for entry in entries] == [0., 1., 2.]
    for written, read in zip(frames, read_sequence(index)):
        assert frame_to_dict(written) == json.loads(json.dumps(frame_to_dict(read)))
