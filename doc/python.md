# Reading and writing in Python

## From a platform

A platform writes and reads its own simulations through its adapter. In openalea.metafspm:

```python
from openalea.metafspm.io.fspm_tf import export_scene, import_frame

export_scene("scene.glb", scene)                       # the scene now
data_structures = import_frame("scene.glb")            # metafspm's DataStructures, rebuilt bit for bit

scene = Scene(planting, ..., output_dirpath="outputs", frame_period=24)    # a frame every 24 steps
```

See [metafspm's documentation](https://github.com/openalea/metafspm) for the options.

## The format's own tables

`openalea.fspm_tf` reads any fspm-TF file, whichever platform wrote it, into plain Python objects holding numpy arrays.

```python
from openalea import fspm_tf

frame = fspm_tf.read("scene.glb")
print(frame.time, frame.time_unit, frame.step)

roots = frame.data_structure("RootPopulation")
segments = roots.entity_set("SubOrgan")
segments.columns["length"]                      # a numpy array, one value per segment
segments.variables["length"]                    # Variable(unit='m', standard_name='length', kind='extensive', ...)
segments.columns["parent"]                      # the predecessor's id (-1: none)

for mesh in roots.meshes:
    mesh.positions                              # (vertices, 3)
    mesh.feature_rows["SubOrgan"]               # each vertex's row in the SubOrgan table
```

A frame is made of:

| Object | Holds |
|---|---|
| `Frame` | time, step, data structures, mappings |
| `DataStructure` | one population or grid: entity sets, relations, scalars, grid, meshes, origin |
| `EntitySet` | the entities of one scale: columns and their declarations (`Variable`) |
| `Relation` | an edge table between entity sets |
| `Mapping` | weights between the entities of two data structures |
| `Mesh` | triangles, each vertex linked to its entities |

Writing builds the same objects:

```python
import numpy as np
from openalea import fspm_tf

segments = fspm_tf.EntitySet("SubOrgan", rank=6, columns=dict(
    id=np.array([1, 2, 3]), label=np.array(["RootSegment"] * 3, dtype=object),
    parent=np.array([-1, 1, 2]), edge_type=np.array(["none", "successor", "successor"], dtype=object),
    length=np.array([0.01, 0.01, 0.004])),
    variables={"length": fspm_tf.Variable(unit="m", standard_name="length", kind="extensive")})
plant = fspm_tf.DataStructure("roots", entity_sets=[segments])
fspm_tf.write("roots.glb", fspm_tf.Frame([plant], time=0., time_unit="d"))
```

A sequence is a folder of frames with its index:

```python
fspm_tf.write_sequence("outputs/frames", frames)       # frame_000000.glb, ..., scene.fspm.json
for frame in fspm_tf.read_sequence("outputs/frames/scene.fspm.json"):
    ...
```

## The vocabulary

```python
from openalea.fspm_tf import vocabulary

vocabulary.standard_names()["water_potential"]          # its unit, kind, definition, platform names
vocabulary.platform_names("metafspm")                   # {"water_potential": "water_potential", "x1": "proximal_end_x", ...}
```

The full API is in the [Python API reference](api.md).
