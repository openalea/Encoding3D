# Reading the specification

This page is for a platform's developers, before they read the specification itself. It explains:

- what the `spec/` folder holds;
- in which order to read it;
- how a file is built;
- what each word means;
- how a codec proves that it follows the format.

## What is agreed, and where

Everything the platforms agree on is in the repository's `spec/` folder, together with the conformance files:

| File | What it fixes | How it is checked |
|---|---|---|
| `spec/specification.md` | the rules, in words (MUST, SHOULD, MAY as in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119)) | by the validator, `fspm-tf validate` |
| `spec/schema/fspm_scene.schema.json` | the shape of the `FSPM_scene` JSON (its fields and their types) | by any JSON Schema validator |
| `spec/schema/index.schema.json` | the shape of a sequence's index, `scene.fspm.json` | by any JSON Schema validator |
| `spec/vocabulary/standard_names.csv` | the shared quantities: canonical unit, kind, definition, and each platform's names for them | by the validator (units, kinds) |
| `spec/vocabulary/labels.csv` | the entity labels, with their scale and Plant Ontology term | by the validator (warnings) |
| `spec/vocabulary/enums.json` | the allowed values: edge types, kinds, roles, base scales, formats… | by the schemas and the validator |
| `conformance/` | the specification as test cases: reference files and what a reader must find in them | `fspm-tf compare-all` |

When they disagree, `specification.md` prevails, then the schemas, then the conformance files. A disagreement is a
defect of the lower one. A change of the format is a pull request to `spec/`, with its conformance scene
([Changing the format](governance.md)).

## A reading path

1. **§1, the data model**, all of it: frames, data structures, entity sets, relations, mappings, meshes, variables.
   Everything else describes how these are written.
2. **§4.2, the reserved columns.** `id`, `label`, `complex`, `parent`, `edge_type` and `sibling_order` carry the plant's
   topology (an MTG's decomposition `/`, successor `<` and branch `+`).
3. **§5 and §6, variables and the vocabulary**: units, kinds, roles, standard names. This is what lets two platforms
   recognise the same quantity.
4. **§2, §3, §4.1, §7, the encoding.** These come with the example below; a codec's writer needs them in full.
5. **§8 and §9, sequences and conformance.**

## The three layers of a file

A frame is a standard glTF 2.0 binary file (`.glb`): a JSON part and a binary part. Any glTF viewer opens it. Three
layers hold the scene:

| Layer | Defined by | Holds |
|---|---|---|
| Property tables | the glTF extension [`EXT_structural_metadata`](https://github.com/CesiumGS/glTF/tree/3d-tiles-next/extensions/2.0/Vendor/EXT_structural_metadata) | every table: one column per variable, with its values in the binary part |
| Feature IDs | the glTF extension [`EXT_mesh_features`](https://github.com/CesiumGS/glTF/tree/3d-tiles-next/extensions/2.0/Vendor/EXT_mesh_features) | for each vertex of a mesh, the row of its entity in one or several tables |
| `FSPM_scene` | fspm-TF (`spec/schema/fspm_scene.schema.json`) | what glTF cannot say: the time, the data structures, which table is which scale, relations, grids, mappings, the variables' units and standard names |

Here is the JSON part of `conformance/root_system.glb`, abridged:

```text
"extensions": {
  "FSPM_scene": {
    "version": "0.2", "vocabulary": "0.2",
    "frame": {"time": 0.0, "timeUnit": "d", "step": 0},
    "dataStructures": [{
      "id": "root_system", "kind": "graph", "origin": [1, 0, 0, 0, ...],     a 4×4 matrix, column by column
      "entitySets": [{"name": "Plant",    "rank": 1, "propertyTable": 0},    one table per scale
                     {"name": "Axis",     "rank": 2, "propertyTable": 1},
                     {"name": "SubOrgan", "rank": 6, "propertyTable": 2}],
      "scalars": 3,                                                         a one-row table for the whole plant
      "meshes": [{"name": "roots", "mesh": 0}]}],
    "variables": {"root_system__SubOrgan": {
      "length": {"unit": "m", "standardName": "length", "kind": "extensive", "role": "state"}, ...}}},
  "EXT_structural_metadata": {
    "schema": {"classes": {"root_system__SubOrgan": {"properties": {
      "id":        {"type": "SCALAR", "componentType": "INT64", "required": true},
      "label":     {"type": "ENUM", "enumType": "root_system__SubOrgan__label"},
      "complex":   {"type": "SCALAR", "componentType": "INT64", "noData": -1},       the axis it belongs to
      "parent":    {"type": "SCALAR", "componentType": "INT64", "noData": -1},       the segment it follows
      "edge_type": {"type": "ENUM", "enumType": "FSPM_edge_type"},                   none, successor, branch, unknown
      "length":    {"type": "SCALAR", "componentType": "FLOAT64"}, ...}}}},
    "propertyTables": [..., {"class": "root_system__SubOrgan", "count": 10,
                             "properties": {"id": {"values": 9}, "length": {"values": 14}, ...}}]}}   buffer views
"meshes": [{"primitives": [{"attributes": {"POSITION": 0, "_FEATURE_ID_0": 1, "_FEATURE_ID_1": 2, "_FEATURE_ID_2": 3},
            "extensions": {"EXT_mesh_features": {"featureIds": [
              {"attribute": 0, "propertyTable": 2, "label": "SubOrgan"},       each vertex's segment,
              {"attribute": 1, "propertyTable": 1, "label": "Axis"},           its axis,
              {"attribute": 2, "propertyTable": 0, "label": "Plant"}]}}}]}]   and its plant
```

To read the segments' lengths, a reader:

1. finds the `SubOrgan` entity set in `FSPM_scene`, and its `propertyTable` (2);
2. finds that table's `length` property and its buffer view (14);
3. reads `count` (10) FLOAT64 values from the binary part;
4. finds their unit (`m`) and standard name in `variables`.

`fspm-tf info file.glb` lists what a frame holds: its data structures, their tables and their variables.

## Words

| Word | Meaning |
|---|---|
| **frame** | the scene at one time step: one `.glb` file |
| **sequence** | a folder of frames and their index, `scene.fspm.json` |
| **data structure** | one plant population's graph, or one environment model's grid (metafspm's word). Not glTF's *node*: each data structure has a glTF node, which only places it for viewers. |
| **entity set** | a table of entities of one kind: the entities of one scale of a graph, or a grid's cells |
| **scale** | a level of description: plant, axis, organ, segment, cell… The vocabulary lists base scales (`enums.json`); an entity set may declare its own (`scale`). |
| **rank** | an entity set's order among the scales, coarser first. It SHOULD be the base scale's position: Plant 1, Axis 2, Organ 5, SubOrgan 6. |
| **entity** | one row of an entity set: a plant, a root axis, a segment, a cell |
| **relation** | an edge table between two entity sets: a cell network, a branch's bearer |
| **mapping** | weights between the entities of two data structures, e.g. root segments and soil voxels |
| **class** | `EXT_structural_metadata`'s word for a table's type: its columns. fspm-TF names them `<data structure>__<table>`. |
| **variable** | a column that is not reserved, with its declaration: unit, standard name, kind, role |
| **standard name** | the vocabulary's name for a quantity, the same on every platform (`length`, `water_potential`) |
| **codec** | a language's reading and writing of the format (`bindings/<language>/`) |
| **adapter** | a platform's model to and from the codec's tables |

## How a codec proves it follows the format

`conformance/` holds reference scenes, each a GLB with what a reader must find in it (`*.expected.json`, in the layout
of [the conformance files](conformance.md)). A codec:

1. reads each GLB and writes what it read as JSON, in that layout;
2. writes the same scenes back as GLB files.

`fspm-tf compare-all` then compares its JSON with the expected values, exactly. `fspm-tf validate` and Khronos'
[glTF-Validator](https://github.com/KhronosGroup/glTF-Validator) check what it wrote. In GitHub Actions, the
composite action `.github/actions/conformance` runs these checks. The Python, Julia, C++ and Java codecs all pass them
([Implementations](implementations.md)).

## Standards it builds on

- glTF 2.0: <https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html>
- `EXT_structural_metadata` and `EXT_mesh_features`: the links above (Cesium's 3D Tiles vendor extensions)
- UCUM, the units: <https://ucum.org>
- I-ADOPT, the decomposition of the vocabulary's names: <https://i-adopt.github.io>
- the Plant Ontology, the labels' terms: <https://planteome.org>
- RFC 2119, MUST and SHOULD: <https://www.rfc-editor.org/rfc/rfc2119>
