# Conformance files

The specification as test cases for every codec. Each scene is a frame (`x.glb`) and its expected values
(`x.expected.json`); `growing_sequence/` is a sequence with its index. `generate.py` writes them all from fixed
numbers, the same bytes on every run; the CI checks that the committed files are what it writes.

| Scene | Covers |
|---|---|
| `root_system` | Plant, Axis and SubOrgan scales, MTG relations, segment variables, a mesh representing three scales, scalars |
| `wheat_shoot` | Plant, Axis, Organ and SubOrgan scales, leaf quads, NaN through `noData`, a translated origin |
| `section_cells` | a cell network: an entity set and a relation with ids, labels and conductances; text and vector columns; extras |
| `soil_and_roots` | a root system, a regular soil grid with z pointing down, and their mapping |
| `adaptive_soil` | an adaptive grid's leaf cells (`level`, `index`) |
| `parameter_set` | a `table` data structure: parameters per plant and in the scalars, references, an infinite value |
| `missing_values` | integer, text, boolean and float columns with missing values; a date column (`format`); `unknown` edge types and a `sibling_order` column; a `mixed` entity set; a labels map; a parent in another axis; bearer relations between two pairs of sets |
| `growing_sequence/` | three frames of a growing root system, ids kept, and their index |
| `instances/` | 0.4: a sequence whose root segments are drawn by sections, instances of shared templates, with a derived field (below) |
| `archives/` | 0.4: the `instances/` sequence packed into `.fspm.zip` archives, stored, deflate, lzma, and with every ZIP64 record (below) |

## Instances (0.4)

`instances/` (specification §12) is a sequence of two frames (`frame_00000n.glb`, `scene.fspm.json`, its parts in
`parts/<key>.glb`). Its root segments are drawn by sections: instances of two templates (a square and a hexagon of
cells), placed by their transforms, owned by the segments, with an instance variable (`age`), two vectors (`ends`,
`sources`) and the derived field `water_potential` on the templates' cells: one dense term, two weighted terms (a
dense and a sparse operator), or one term solved (`solve`) with an offset. The expected values:

- `frame_00000n.expected.json`: the frame as read, the instance sets dumped by `frame_to_dict` (`instance_sets`: the
  table, the parts' keys, the vectors' values and counts, the derived fields' operators, weights and offsets);
- `expected/<key>.json`: each part as read (`openalea.encoding3d.dump.part_to_dict`);
- `frame_00000n.evaluated.json`: each instance's derived field, compared within a relative 1e-12;
- `embedded.glb`: the second frame with its parts embedded, read as `frame_000001.expected.json`.

`archives/` holds the same sequence (its index, frames and parts, unchanged) packed into `.fspm.zip` archives
(specification §8.2): `instances_stored`, `instances_deflate` and `instances_lzma` (ZIP's methods 0, 8 and 14, as
Python's `zipfile` writes them), and `instances_zip64` (stored, every size and offset in ZIP64 records: the local and
central headers' ZIP64 extra fields, the ZIP64 end of central directory and its locator, as a sequence over 4 GB or
65,535 files has them). A reader reads each frame from `instances_x.fspm.zip/frame_00000n.glb`, its parts from the
archive, as from the folder. An archive's compressed bytes depend on the compressor's version, so `generate.py`
rewrites an archive only when its members (their names, methods and bytes once read) change.

What a codec reading instances dumps, besides the frames' dumps (`DUMPS/instances/frame_00000n.json`, against
`frame_00000n.expected.json`):

| Dump | Against |
|---|---|
| `instances/frame_00000n.evaluated.json`: each derived field evaluated, `{"<data structure>/<instance set>/<field>": [values per instance]}` | `frame_00000n.evaluated.json`, within a relative 1e-12 |
| `instances/embedded.json`, `instances/embedded.evaluated.json` | the last frame's `.expected.json` and `.evaluated.json` |
| `instances/parts/<key>.json`: the part `parts/<key>.glb` read | `expected/<key>.json` |
| `archives/<name>/frame_00000n.json` and `.evaluated.json`: each frame of `archives/<name>.fspm.zip` | `instances/frame_00000n.expected.json` and `.evaluated.json` |

What it writes: the instances' frames again with their parts (`WRITTEN/instances/`, with an index listing them),
`embedded.glb` with its parts embedded, and, when it packs, that sequence as `WRITTEN/archives/instances.fspm.zip`;
`encoding3d validate` checks every `.glb` and `.fspm.zip`, the parts each frame refers to included.

Codecs reading 0.3 only skip both folders (`encoding3d compare-all --skip-instances`, the action's `instances: "false"`),
as they skip `coupling/`.

## Coupling sessions

`coupling/` holds the coupling conformance sessions (specification §9, §11), which `coupling/generate.py` writes: each
session's peer (a sequence the coordinator replays), its subject's declaration and updates, and the expected values of
what the subject reads (`expected/turn_<step>.json`) and of the session's record (`expected/record/`). A codec's
participant runs them with `encoding3d couple-conformance conformance/coupling --participant COMMAND`. The frame tools
(`compare-all`, each codec's conformance run) leave this folder out.

## The expected values

`x.expected.json` is the frame `x.glb` holds, as plain JSON (written by `openalea.encoding3d.dump.frame_to_dict`):

```text
{"time": 0.0, "time_unit": "d", "step": 0,
 "data_structures": [
   {"id": "...", "kind": "graph", "origin": [[4 numbers] x 4, row by row], "platform": "...", "model": "...",
    "extras": {...},                                                    (when present)
    "labels": {"Internode": "StemInternode", ...},                      (when present)
    "entity_sets": [{"name": "SubOrgan", "rank": 6, "scale": "SubOrgan", "count": 10,       (scale when present)
                     "columns": {"id": {"dtype": "int64", "values": [...]},
                                 "label": {"dtype": "string", "values": [...]},      (labels and enums as their names)
                                 "end": {"dtype": "float64", "values": [[x, y, z], ...]}, ...},
                     "variables": {"length": {"unit": "m", "role": "state", "standard_name": "length",
                                              "kind": "extensive", "description": "...",
                                              "format": "date"}, ...}}],             (format when present)
    "relations": [... like entity sets, with "source_set" and "target_set"],
    "scalars": {... like an entity set, one row},
    "grid": {"kind", "shape", "origin", "spacing", "axes", "periodic", "z_up", "max_level", "cells"},
    "meshes": [{"name": "...", "positions_float32": [[x, y, z], ...], "feature_rows": {"SubOrgan": [...]},
                "indices": [...], "display": {"name": [...]}}]}],
 "mappings": [... like entity sets, with "source", "target" ([data structure, entity set]) and "method"],
 "update": {"participant": "...",                                       (a partial frame only, §11.1)
            "removed": [{"data_structure": "...", "entity_set": "...", "ids": [...]}, ...]}}   (sorted)
```

- **Floats** are the shortest decimals giving the same double, compared exactly.
- **NaN and missing values** are `null`, whatever the column's type; +∞ and −∞ are the strings `"Infinity"` and
  `"-Infinity"`.
- **Positions** are the FLOAT32 values of the file, widened to doubles.
- **`dtype`** is the column's numpy type name (`float64`, `int64`, `uint8`, `bool`...), or `string` for text and enums.
  A boolean column with missing values (stored as UINT8) is `bool`.
- Keys only appear when the frame has them (no `extras`, `labels`, `relations`, `scalars`, `grid`, `meshes`,
  `scale` or `format` when absent).

## Checking a codec

1. The codec reads each `x.glb` and dumps what it read in this layout as `DUMPS/x.json` (same relative path).
2. It writes the same scenes back as GLB files, in `WRITTEN/`.
3. Then:

   ```bash
   encoding3d compare-all DUMPS conformance          # reading: every dump equals its expected values
   encoding3d validate WRITTEN/*.glb ...             # writing: valid encoding3d (and Khronos' glTF-Validator: valid glTF),
                                                     # every .glb and .fspm.zip under WRITTEN
   ```

In GitHub Actions, the composite action `.github/actions/conformance` runs both. The Python codec's own run is
`bindings/python/conformance_run.py`, used by the `python-codec-conformance` job of `.github/workflows/conformance.yml`.
