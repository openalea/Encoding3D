# fspm-TF 0.2 specification

Status: draft (2026-11-02). 0.2 adds to 0.1 (see "Changes from 0.1" at the end); a 0.1 file is a valid 0.2 file. The key words MUST, SHOULD and MAY are to be read as in RFC 2119 (https://www.rfc-editor.org/rfc/rfc2119).

fspm-TF is an exchange format for whole functional-structural plant model scenes: multiscale plant graphs, their
variables and parameters, their geometry, and the environment's grids, at successive time steps. A **frame** (one
time step) is one glTF 2.0 binary file (GLB). A **sequence** of frames is a folder of GLB files with an index.

The language-neutral files of this version are part of the specification:

| File | Content |
|---|---|
| `spec/schema/fspm_scene.schema.json` | JSON Schema of the `FSPM_scene` extension (§3) |
| `spec/schema/index.schema.json` | JSON Schema of a sequence's index (§8) |
| `spec/vocabulary/standard_names.csv` | the standard names, their canonical units and kinds, and each platform's names for them (§6) |
| `spec/vocabulary/labels.csv` | entity labels, their scales and Plant Ontology terms (§6) |
| `spec/vocabulary/enums.json` | the values of `edge_type`, `kind`, `role`, data structure and grid kinds; the base scales |
| `conformance/` | reference files and their expected values (§9): the specification as test cases |

When these sources disagree, `specification.md` prevails, then the schemas, then the conformance files; the
disagreement is a defect of the lower one, to be fixed.

The format builds on glTF 2.0 (https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html) and two of its
extensions: `EXT_structural_metadata` for tables
(https://github.com/CesiumGS/glTF/tree/3d-tiles-next/extensions/2.0/Vendor/EXT_structural_metadata) and
`EXT_mesh_features` for feature IDs
(https://github.com/CesiumGS/glTF/tree/3d-tiles-next/extensions/2.0/Vendor/EXT_mesh_features).

## 1. The data model

- A **frame** holds data structures, mappings between them, and its time.
- A **data structure** is one plant population's graph, or one environment model's grid. It has an `id`, a `kind`,
  an origin, entity sets, relations, scalars, a grid and meshes:

  | Kind | Content |
  |---|---|
  | `graph` | one entity set per scale, with the multiscale tree graph's relations |
  | `regular_grid` | a regular grid of cells |
  | `adaptive_grid` | a refined grid of cells |
  | `table` | entity sets without topology, e.g. a parameter set |

  Its `origin` is a 4×4 matrix placing its coordinates in the scene's frame.
- **The scene's frame** is right-handed, in metres, with **z up**: z = 0 at the soil surface, negative below it.
  Meshes, grid origins and grid spacings are in metres. Position columns (e.g. the vocabulary's `proximal_end_*` and
  `distal_end_*`) keep the platform's length unit, declared like any variable's (§5), so that values stay at the
  platform's precision; readers convert them with their declared unit. A platform with other axes (e.g. y up) puts
  the rotation in the data structure's origin.
- An **entity set** is a table: one row per entity, one column per variable. A graph has one entity set per scale,
  with that scale's `rank` (coarser scales have smaller ranks). A grid's cells form one entity set, with no rank.
  - An entity set MAY declare its `scale`: one of the vocabulary's base scales (`enums.json`: Plant, Axis,
    GrowthUnit, Phytomer, Organ, SubOrgan, Layer, Cell, Compartment, Connection), or `mixed` when its rows belong to
    several base scales (e.g. CPlantBox's organs: whole root axes and leaves).
  - The `rank` SHOULD be the position of the set's base scale in that list, from 1 (Plant 1, Axis 2, Organ 5,
    SubOrgan 6), when it has one. Readers MUST NOT assume consecutive ranks.
  - Platforms have different scales. A reader SHOULD find the tables it needs by what they hold (standard names, and
    the `complex` chain between sets), not by their names. For example, the segments are the set holding segment
    ends, and their organs are the set their `complex` points to. Writers SHOULD declare the standard names of
    positions, lengths and radii.
- A **relation** is an edge table between two entity sets of the same data structure. Examples: a cell network, or
  connections between compartments.
- The **scalars** are a one-row table of values for the whole data structure.
- A **mapping** is a table of weights between the entities of two data structures, e.g. root segments and soil
  voxels.
- A **mesh** is a set of triangles. Each vertex carries the row of its entity in one or several entity sets.
- A **variable** is a column with a declaration: its unit, standard name, kind and role (§5).

A frame holding only data structures with parameters, and no geometry, is a **parameter set**.

## 2. The glTF container

A frame MUST be a GLB file (glTF 2.0 binary):

1. All buffer views MUST be in the GLB's binary chunk. No external `.bin` files and no data URIs are allowed in 0.2.
2. Every buffer view holding table values MUST start at a multiple of 8 bytes. The JSON chunk MUST be padded with
   spaces and the binary chunk with zeros to 8 bytes, as `EXT_structural_metadata` requires. The buffer's
   `byteLength` SHOULD be the binary chunk's padded length (glTF-Validator warns of more than 3 bytes of padding
   beyond the buffer).
3. `extensionsUsed` MUST list `FSPM_scene` and `EXT_structural_metadata`, plus `EXT_mesh_features` when there are
   meshes. `FSPM_scene` SHOULD NOT be listed in `extensionsRequired`, so that every glTF viewer opens the file.
4. The glTF scene's root node, `fspm_scene`, turns the scene's frame (z up) into glTF's (y up), so that glTF viewers
   show the scene upright: its `matrix` is a rotation of −90° about x (column-major
   `[1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,0,0,1]`). It is for viewers only: readers of the tables, and `FSPM_scene`'s
   origins, use the scene's frame. Under it, one node per data structure, named after its `id`, carries the data
   structure's origin as its `matrix` when the origin is not the identity; that node's children each hold one of the
   data structure's meshes.
5. The file SHOULD be valid glTF for Khronos' glTF-Validator: no errors.

## 3. The `FSPM_scene` extension

The glTF root's `extensions.FSPM_scene` MUST follow `fspm_scene.schema.json`:

```text
{
 "version": "0.2",
 "vocabulary": "0.2",
 "frame": {"time": 1.0, "timeUnit": "d", "step": 24},
 "writer": {"platform": "...", "model": "..."},
 "dataStructures": [{
   "id": "plants", "kind": "graph", "platform": "...", "model": "...",
   "origin": [16 numbers, column-major], "node": 0,
   "entitySets": [{"name": "Plant", "rank": 1, "scale": "Plant", "propertyTable": 0},
                  {"name": "SubOrgan", "rank": 6, "scale": "SubOrgan", "propertyTable": 1}],
   "labels": {"Internode": "StemInternode"},
   "relations": [{"name": "Connection", "sourceSet": "Cell", "targetSet": "Cell", "propertyTable": 2}],
   "scalars": 3,
   "grid": {"kind": "regular", "shape": [..], "origin": [..], "spacing": [..], "axes": [..], "periodic": [..],
            "zUp": false, "cells": "Voxel"},
   "meshes": [{"name": "roots", "mesh": 0,
               "display": [{"attribute": "_WATER_POTENTIAL", "variable": "water_potential", "entitySet": "SubOrgan"}]}]
 }],
 "mappings": [{"name": "roots_in_soil", "source": {"dataStructure": "plants", "entitySet": "SubOrgan"},
               "target": {"dataStructure": "soil", "entitySet": "Voxel"}, "method": "overlap", "propertyTable": 4}],
 "variables": {"<class id>": {"<column>": {"unit": "m", "standardName": "length", "kind": "extensive",
                                            "role": "state", "minimum": 0, "references": [], "doi": [],
                                            "format": "date"}}}
}
```

- **Identifiers.** Data structure ids, entity set, relation and mapping names, and column names MUST be identifiers
  (`^[a-zA-Z_][a-zA-Z0-9_]*$`). Within a frame, data structure ids are unique. Within a data structure, entity set
  names are unique, and so are relation names.
- **Labels.** A data structure MAY carry `labels`, a map from the labels it uses (e.g. a model's class names) to the
  vocabulary's labels (§6). Readers looking for an entity of the vocabulary (e.g. the leaves) use it; the entities
  keep the platform's labels.
- **Extras.** A data structure MAY carry `extras`, a JSON object for the writing platform, e.g. what it needs to
  rebuild its own data structure exactly. Its keys SHOULD be the platform's name as in the vocabulary's platform
  columns, in lower case (`metafspm`, `cplantbox`, `groimp`, `virtualplantlab`). Other readers MUST NOT need it, and
  SHOULD keep it.
- **Property tables.** Every table of §1 is one `EXT_structural_metadata` property table of its own class, and no
  property table serves two tables. Writers SHOULD name the classes `<data structure>__<table>` (mappings:
  `mapping__<name>`). Readers MUST find tables through the `propertyTable` indices, not through class names.

## 4. Tables

### 4.1 Column types

A column is one property of the table's class:

| Values | Stored as |
|---|---|
| numbers | `SCALAR`, of component type `INT8` to `INT64`, `UINT8` to `UINT64`, `FLOAT32` or `FLOAT64` |
| a fixed-size vector per row | `SCALAR` with `array: true` and `count` ≥ 2 |
| booleans | `BOOLEAN` |
| text | `STRING` |
| labels, edge types and relation labels | `ENUM` (§4.2) |

- Variable-length arrays and the other glTF metadata types are not part of 0.2.
- **NaN.** NaN and infinities are forbidden in property tables. A float column with missing values (NaN) declares
  `noData`: the most negative finite value of its type, −1.7976931348623157e308 for FLOAT64 or
  −3.4028234663852886e38 for FLOAT32, stored where the value is NaN. Readers MUST read `noData` back as NaN. A
  column cannot hold both NaN and that value.
- **Missing values in other columns.** A variable column whose entities do not all have a value (e.g. a field that
  only some of a platform's classes have) declares `noData`, and readers MUST read the rows holding it as missing:
  - an integer column: a value of its type that the column does not hold; writers SHOULD use the type's minimum
    (signed) or maximum (unsigned) when it is free;
  - a text (`STRING`) column: a string the column does not hold; writers SHOULD use the empty string when it is free;
  - booleans: `BOOLEAN` has no `noData`, so a boolean column with missing values is written as `UINT8` (0 false,
    1 true) with `noData` 255, and its class property declares `"extras": {"FSPM_boolean": true}`. Readers read it as
    booleans with missing values.

  The reserved columns' `noData` (−1 in `complex` and `parent`) is not a missing value: it is the id of no entity.
- **Infinities.** A float column holding +∞ or −∞ declares, in its class property's `extras`, `FSPM_infinity`:
  `{"positive": P, "negative": N}`, with P the largest finite value of its type (1.7976931348623157e308 for
  FLOAT64, 3.4028234663852886e38 for FLOAT32) and N the next value after the most negative one
  (−1.7976931348623155e308, −3.4028232635611926e38). P is stored where the value is +∞ and N where it is −∞. Readers
  MUST read them back as infinities. A column cannot hold both infinities and these values.
- **Precision.** Values MUST be stored at the platform's own precision. A FLOAT64 state is not written as FLOAT32.

### 4.2 Reserved columns

These columns have fixed meanings, in the tables where they appear:

**Entity sets**

| Column | Type | Meaning |
|---|---|---|
| `id` | INT64, required | the entity's id: non-negative, unique across the data structure's entity sets and relations (§8 for a sequence) |
| `label` | ENUM | the entity's label (§6) |
| `complex` | INT64, `noData` −1 | the id of the entity containing it, in a coarser entity set of the graph (MTG decomposition `/`); usually the nearest coarser one, but e.g. a cell wall may belong to its segment directly |
| `parent` | INT64, `noData` −1 | the id of its predecessor in the same entity set |
| `edge_type` | ENUM `FSPM_edge_type` | how it follows its parent: `none` (no parent), `successor` (MTG `<`), `branch` (MTG `+`), `unknown` (it has a parent, but the writer does not know how it follows it) |
| `order` | INT64, optional | the entity's position, from 0, among the entities that share its parent in the writer's tree (its `parent`, else its bearer, else its `complex`), all entity sets together: for platforms that keep the order of children |
| `level`, `index` | INT64; INT64 vector, one per dimension | an adaptive grid's leaf cell: its refinement level, and its integer index at that level |

**Relations**

| Column | Type | Meaning |
|---|---|---|
| `id` | INT64, optional | the edge's id, when edges are entities of the writer's model (e.g. metafspm's Connections): unique like entity ids |
| `source`, `target` | INT64 | ids in the relation's `sourceSet` and `targetSet` |
| `relation` | ENUM | an optional label per edge |

**Mappings**

| Column | Type | Meaning |
|---|---|---|
| `source`, `target` | INT64 | ids in the source and target entity sets |
| `weight` | FLOAT64 | finite and non-negative |

Rules on these columns:

- In a graph, every ranked entity set but the coarsest MUST have `complex`. The coarsest MUST NOT point to a
  complex.
- `parent` and `edge_type` go together. `edge_type` is `none` exactly where `parent` is −1. The parents MUST form no
  cycle.
- `parent` MAY be in another complex than the entity's own: the first entity of a branch (e.g. a lateral root's
  first segment, whose parent is a segment of the bearing root) usually is.
- Every id referred to MUST exist in the entity set referred to.
- `parent` links entities of the same scale. When an axis's first entity grows on an entity of another scale (in an
  MTG, a branch axis's first internode, linked to its bearer only through the axes), its `parent` is −1. Its bearer
  MAY be written as a relation named `bearer`, from the entity to the one it is borne on.
  Its `relation` labels say how: `successor`, `branch` or `decomposition` (MTG `<`, `+`, or `/` to an entity that is
  not its complex).
- Other links between entities are relations, one per kind of link. A pair of entities linked in several ways (e.g. a
  successor edge that is also a platform's own edge) appears in each of these relations. A kind of link between
  several pairs of entity sets is one relation per pair, named `<kind>`, or `<kind>_<sourceSet>_<targetSet>` when
  there are several (e.g. `bearer_Axis_Internode`); readers find them by the prefix.
- Each label column or relation column is an `ENUM` of its own, listing the values used. The enum
  `FSPM_edge_type` is fixed: `none` = 0, `successor` = 1, `branch` = 2, `unknown` = 3.
- A grid's cells MAY omit `id`; their ids are then their row numbers. A regular grid's rows are its cells in C order
  of `shape`, the last axis varying fastest, and its ids, if written, MUST be these row numbers.

## 5. Variables

Every other column is a variable. It SHOULD be declared in `FSPM_scene.variables[class][column]`. The column's
`description` goes in its class property.

| Field | Content |
|---|---|
| `unit` | required: a UCUM code (https://ucum.org) from the subset of §5.1 |
| `standardName` | its name in the vocabulary (§6), if it has one. The unit MUST then be convertible to the standard name's canonical unit |
| `kind` | `extensive` (summed when entities are merged, split by weights), `intensive` (averaged), `massic_concentration`, `volumic_concentration`, `descriptor` (not aggregated: positions, angles, codes) |
| `role` | required: `state`, `input`, `parameter`, `derived` or `setting` (enums.json) |
| `minimum`, `maximum` | the variable's plausible range, as documentation (not a constraint on values) |
| `references`, `doi` | its sources |
| `format` | for a text column holding dates or times: `date`, `date-time` or `time`, as ISO 8601 (`2022-08-24`, `2022-08-24T13:00:00`, `13:00:00`) |

Parameters are variables with role `parameter`. A parameter goes in the table it applies to:

- a value for the whole data structure, in the scalars;
- a value per plant, as a `Plant` column;
- a value per entity, as a column of that entity's scale.

### 5.1 Units

Units are UCUM codes, with:

- SI and common atoms (`m`, `g`, `s`, `K`, `mol`, `Pa`, `J`, `W`, `L`, `Cel`, `min`, `h`, `d`, `a`, `deg`, `%`,
  ...);
- metric prefixes on the metric atoms (`mm`, `umol`, `MPa`, `hPa`, ...);
- pressures as heights of water or mercury: `m[H2O]`, `m[Hg]`, with prefixes (`cm[H2O]`, `mm[Hg]`);
- products `.`, quotients `/`, integer exponents (`m2`, `s-1`), parentheses, annotations `{...}`, and `1`.

`Cel` cannot be combined with other units: thermal time is in `K.d`. No spaces are allowed:
`mol/(m2.s)` or `mol.m-2.s-1`, not `mol m-2 s-1`.

## 6. Vocabulary

The vocabulary (version `0.2`) lists standard names. For each, it gives:

- a canonical unit;
- a kind;
- an I-ADOPT-like decomposition: property, object of interest, matrix, context;
- typical scales;
- a definition;
- for each platform (columns `metafspm`, `cplantbox`, `groimp`, `virtualplantlab`), its names for the quantity,
  separated by `;`. A platform's writer reads its mapping from its column, and a name appears in one row of its
  platform's column at most.

Labels are listed with their scale and Plant Ontology term. A frame declares the vocabulary version it uses
(`vocabulary`). Writers SHOULD use the vocabulary's labels for entities that have one.

The vocabulary grows by review: a new name comes with its definition and canonical unit, and is agreed by at least
two platforms.

## 7. Meshes

- **Triangles.** Each mesh has one primitive of mode TRIANGLES (4).
  - `POSITION` is FLOAT32 VEC3, in the data structure's frame, so its origin's transform applies.
  - Without `indices`, every three consecutive vertices are a triangle. With `indices` (UNSIGNED_INT), every three
    indices are.
- **Feature IDs.** Each entity set a mesh represents has one feature ID set, through `EXT_mesh_features`:
  - an attribute `_FEATURE_ID_n` (FLOAT, whole numbers below 2²⁴), giving each vertex's row in that entity set;
  - its `propertyTable`: that entity set's table;
  - its `label`: the entity set's name;
  - `nullFeatureId`: the entity set's row count, for vertices with no entity in it;
  - `featureCount`: the number of distinct rows present.

  A mesh MAY represent several scales of its data structure, e.g. a root mesh by segment, axis and plant. Entity
  sets without geometry have no mesh.
- **Display copies.** These are FLOAT32 SCALAR attributes named `_<VARIABLE>`, upper case: per-vertex copies of a
  variable, for viewers that don't read property tables.
  - Each one MUST be listed in its mesh's `display`, with the variable and entity set it copies.
  - Readers MUST NOT take them for the variable's values.
  - No other application-specific attribute (`_...`) than feature IDs and display copies is allowed.

## 8. Sequences

A sequence is a folder holding one GLB per frame and an index, `scene.fspm.json`, following `index.schema.json`:

```text
{"fspmIndex": "0.2", "timeUnit": "d",
 "frames": [{"time": 0.0, "step": 0, "file": "frame_000000.glb"}, ...]}
```

- **Frames.** Frames are listed in time order. Each file's `frame.time`, `frame.step` and `timeUnit` MUST equal the
  index's.
- **Ids across frames.** An entity keeps its id from frame to frame. An id whose entity has disappeared MUST NOT be
  given to another entity in a later frame of the same data structure and entity set. Labels and parents MAY change,
  e.g. an apex moved by growth. A platform whose own ids may come back (a counter restarted, a deleted maximum's id
  given again) keeps, across a sequence, a map from its entities to the ids it writes.
- **Ids are not positions.** Ids may be sparse (e.g. offsets keeping them stable as a plant grows). Readers SHOULD
  NOT size arrays by the largest id.
- **Packing.** Packing a sequence into one GLB is not part of 0.2.

## 9. Conformance

`conformance/` holds reference scenes, each a GLB with its expected values in `*.expected.json`, and a growing
sequence:

| Scene | Content |
|---|---|
| `root_system` | Plant, Axis and SubOrgan scales with MTG relations; segment variables, NaN-free; a mesh representing three scales; scalars |
| `wheat_shoot` | Plant, Axis, Organ and SubOrgan scales; leaf quads; NaN through `noData`; a translated origin |
| `section_cells` | a cell network: an entity set and a relation with labels and conductances; a string column; vector columns |
| `soil_and_roots` | a root system, a regular soil grid with z pointing down, and their mapping |
| `adaptive_soil` | an adaptive grid's leaf cells (`level`, `index`) |
| `parameter_set` | a `table` data structure with parameters per plant and in the scalars, references and DOIs; an infinite value |
| `missing_values` | integer, text and boolean columns with missing values; a date column; `unknown` edge types and an `order` column; a `mixed` entity set; a labels map; bearer relations between two pairs of sets |
| `growing_sequence/` | three frames of a growing root system and their index |

An implementation conforms to 0.2 when two things hold:

- **Reading:** what it reads from every conformance GLB equals the expected JSON. Floats are compared exactly; NaN and
  missing values are null in the JSON, +∞ and −∞ the strings `"Infinity"` and `"-Infinity"`; positions are the
  FLOAT32 values.
- **Writing:** what it writes passes `fspm-tf validate` with no error, and Khronos' glTF-Validator with no error.

## 10. Keeping what one does not read

A reader that writes a file back SHOULD keep the content it does not interpret, as RSML requires. In 0.2 this covers
the glTF root's other extensions and `extras`, when they hold no buffer views.

## Changes from 0.1

All additions; a 0.1 file is a valid 0.2 file.

- Sources: `conformance/` is part of the agreement; the order in which the sources prevail.
- §1: an entity set's `scale`, ranks as base scale positions, reading by content; position columns in their declared
  length unit.
- §2: the buffer's `byteLength` holds the padding.
- §3: unique relation names, a data structure's `labels`, the extras key.
- §4.1: missing values in integer, text and boolean columns.
- §4.2: `edge_type` `unknown`, the `order` column, a parent in another complex, bearer relations' labels and names.
- §5: a variable's `format`.
- §6: the vocabulary 0.2 (`Seed`, `mtg_index`).
- §8: sparse ids.
- §9: the `missing_values` scene.
