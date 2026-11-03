"""
Frames read lazily (read(path, lazy=True)): the same frame as read whole, each column decoded only when read, the meshes
too, written back the same, and the file released by close() or a with block.
"""
import os

import pytest

from openalea import fspm_tf
from openalea.fspm_tf.dump import frame_to_dict
from openalea.fspm_tf.model import LazyColumns

from conftest import CONFORMANCE

FILES = sorted(os.path.join(folder, name) for folder, _, names in os.walk(CONFORMANCE) for name in names
               if name.endswith(".glb") and "coupling" not in os.path.relpath(folder, CONFORMANCE))


@pytest.mark.parametrize("path", FILES, ids=[os.path.relpath(path, CONFORMANCE) for path in FILES])
def test_read_lazily_the_same(path):
    with fspm_tf.read(path, lazy=True) as frame:
        assert frame_to_dict(frame) == frame_to_dict(fspm_tf.read(path))
        assert fspm_tf.to_bytes(frame) == fspm_tf.to_bytes(fspm_tf.read(path))     # written back the same


def test_only_what_is_read_is_decoded():
    frame = fspm_tf.read(os.path.join(CONFORMANCE, "root_system.glb"), lazy=True)
    segments = frame.data_structure("root_system").entity_set("SubOrgan")
    assert isinstance(segments.columns, LazyColumns)
    assert segments.count == 10 and "length" in segments.columns and segments.columns.decoded() == []
    assert segments.variables["length"].unit == "m"                           # declarations: from the JSON
    lengths = segments.columns["length"]
    assert segments.columns.decoded() == ["length"] and lengths.size == 10
    meshes = frame.data_structure("root_system").meshes
    assert meshes._items[0][0] is False                                          # not decoded until read
    assert len(meshes[0].positions) > 0
    frame.close()
    with pytest.raises(ValueError):                                              # the file released
        segments.columns["radius"]
    assert lengths.sum() > 0                                                     # what was read stays


def test_a_lazy_column_set_and_deleted():
    frame = fspm_tf.read(os.path.join(CONFORMANCE, "root_system.glb"), lazy=True)
    segments = frame.data_structure("root_system").entity_set("SubOrgan")
    segments.columns["doubled"] = 2 * segments.columns["length"]
    del segments.columns["radius"]
    again = fspm_tf.from_bytes(fspm_tf.to_bytes(frame)).data_structure("root_system").entity_set("SubOrgan")
    assert "radius" not in again.columns and (again.columns["doubled"] == 2 * again.columns["length"]).all()
    frame.close()
