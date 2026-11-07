# encoding3d 0.4 specification

Status: draft (2026-11-06). 0.4 adds instances of shared templates, linear derived fields, shared parts and sequence
archives to 0.3 (see "Changes from 0.3" at the end); a 0.1, 0.2 or 0.3 file is a valid 0.4 file. The key words MUST, SHOULD and MAY are to be read as in RFC 2119 (https://www.rfc-editor.org/rfc/rfc2119).

encoding3d is an exchange format for whole functional-structural plant model scenes: multiscale plant graphs, their
variables and parameters, their geometry, and the environment's grids, at successive time steps. A **frame** (one
time step) is one glTF 2.0 binary file (GLB). A **sequence** of frames is a folder of GLB files with an index, or that
folder packed into one archive.

The language-neutral files of this version are part of the specification:

| File | Content |
|---|---|
| `spec/schema/fspm_scene.schema.json` | JSON Schema of the `FSPM_scene` extension (§3), and of a shared part's (§12) |
| `spec/schema/index.schema.json` | JSON Schema of a sequence's index (§8) |
| `spec/schema/views.schema.json` | JSON Schema of a sequence's optional views, `views.json` (§8.1) |
| `spec/vocabulary/standard_names.csv` | the standard names, their canonical units and kinds, and each platform's names for them (§6) |
| `spec/vocabulary/labels.csv` | entity labels, their scales and Plant Ontology terms (§6) |
| `spec/vocabulary/enums.json` | the values of `edge_type`, `kind`, `role`, data structure and grid kinds; the base scales |
| `conformance/` | reference files and their expected values (§9): the specification as test cases |
| `spec/schema/coupling.schema.json` | JSON Schema of a coupling session's messages (§11) |

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
- An **instance set** draws many entities with one shared **template** each: a mesh and its own entity sets, stored
  once, placed by each instance's transform. Each instance has its own variables, and its **derived fields**, fields
  on the template's entities rebuilt by linear operators from the instance's values (§12).
- A **shared part** is a template or an operator, stored once in its own file and referred to by its content key from
  any frame (§12.1).

A frame holding only data structures with parameters, and no geometry, is a **parameter set**.

## 2. The glTF container

A frame MUST be a GLB file (glTF 2.0 binary):

1. All buffer views MUST be in the GLB's binary chunk. No external `.bin` files and no data URIs are allowed in 0.4.
   A frame refers to a shared part by its key through `FSPM_scene` (§12), never through a glTF buffer.
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
 "version": "0.4",
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
               "display": [{"attribute": "_WATER_POTENTIAL", "variable": "water_potential", "entitySet": "SubOrgan"}]}],
   "instanceSets": [{"name": "sections", "propertyTable": 5, "owners": "SubOrgan", "parts": ["<key>", ...],
                     "vectors": [{"name": "ends", "propertyTable": 6}],
                     "derivedFields": [{"name": "water_potential", "entitySet": "Cell", "input": "ends", "terms": 2,
                                        "variable": {"unit": "MPa", "role": "derived"}}]}]
 }],
 "mappings": [{"name": "roots_in_soil", "source": {"dataStructure": "plants", "entitySet": "SubOrgan"},
               "target": {"dataStructure": "soil", "entitySet": "Voxel"}, "method": "overlap", "propertyTable": 4}],
 "parts": {"<key>": {"bufferView": 12}},
 "part": {"kind": "operator", "format": "dense", "rows": 6, "columns": 2, "values": 0},
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
- **Update.** A frame with an `update` object is a partial frame, a coupling session's message (§11.1); a frame
  written as a time step has none.
- **Instances and parts.** A data structure's `instanceSets`, the frame's embedded `parts` and a part file's `part` are
  defined in §12.

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

- Variable-length arrays and the other glTF metadata types are not part of 0.4 (one array per instance of its own
  length is an instance set's vector, §12.2).
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
| `sibling_order` | INT64, optional | the entity's position, from 0, among the entities that share its parent in the writer's tree (its `parent`, else its bearer, else its `complex`), all entity sets together: for platforms that keep the order of children |
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
{"fspmIndex": "0.4", "timeUnit": "d",
 "frames": [{"time": 0.0, "step": 0, "file": "frame_000000.glb"}, ...],
 "parts": {"<key>": "parts/<key>.glb", ...}}
```

The folder's layout:

| File | Content |
|---|---|
| `scene.fspm.json` | the index |
| `views.json` | the views (§8.1), optional |
| `frame_*.glb` | the frames (any names the index gives) |
| `parts/<key>.glb` | the shared parts the frames use (§12.1), one file each |

- **Frames.** Frames are listed in time order. Each file's `frame.time`, `frame.step` and `timeUnit` MUST equal the
  index's.
- **Ids across frames.** An entity keeps its id from frame to frame. An id whose entity has disappeared MUST NOT be
  given to another entity in a later frame of the same data structure and entity set. Labels and parents MAY change,
  e.g. an apex moved by growth. A platform whose own ids may come back (a counter restarted, a deleted maximum's id
  given again) keeps, across a sequence, a map from its entities to the ids it writes.
- **Ids are not positions.** Ids may be sparse (e.g. offsets keeping them stable as a plant grows). Readers SHOULD
  NOT size arrays by the largest id.
- **Parts.** The index's `parts` SHOULD list every part its frames use, each at `parts/<key>.glb`. A writer writes a
  part only when its key is new, and removes the parts no remaining frame uses when it removes frames.

### 8.1 Views

A sequence (or a frame) MAY come with a companion `views.json`, next to its `scene.fspm.json` (or its GLB), following
`views.schema.json`. It says how to look at the frames, not what they hold: readers MAY ignore it, and a sequence is
valid without it. It is platform-independent; any viewer may apply it.

```text
{"encoding3d_views": 1, "active": "default",
 "configurations": {"default": {"layers": [
   {"name": "roots", "source": {"data_structure": "plants", "kind": "segments", "entity_set": "SubOrgan"},
    "select": {"entity_set": "SubOrgan", "where": {"label": ["RootSegment"], "length": ">0"}},
    "color_by": {"entity_set": "SubOrgan", "variable": "water_potential"}, "colormap": "Viridis (matplotlib)",
    "range": "auto", "log": false, "opacity": 1, "visible": true, "representation": "Surface",
    "tube": {"radius": "radius", "scale": 1}}]}}}
```

- **Configurations.** Named lists of layers; `active` names the one shown first (else the first).
- **A layer** draws one part of a data structure: `source.kind` `mesh` (with the mesh's `name`), `segments` (an entity
  set with segment ends, `entity_set`), `grid` (the grid's cells) or `instances` (an instance set's placed templates,
  `instance_set`, §12). Its name is unique in its configuration.
- **Selection.** `select` keeps the entities whose row in `select.entity_set` holds every condition of `where`: a
  value, a list of values (labels and other text by name), or a comparison (`">=0"`, `"!=2"`); a missing value never
  holds. For a mesh, the entity set is any the mesh represents (a triangle is kept when its feature row in that set
  is); for segments and grids, the source's own set; for instances, the instance set or its `owners` (an instance is
  kept when its row, or its owner's, is).
- **Drawing.** `color_by` names a variable of an entity set the layer's entities are in (as `select`; for instances,
  also a template's entity set, its columns and the derived fields on it), or is null
  (then `solid_color`, RGB in [0, 1]); `colormap` is a colour map's name (ParaView's preset names), `range` `"auto"`
  or `[min, max]`, `log` a log scale; `opacity`, `visible` (when opened), `representation`; `tube` (segments only)
  draws them as tubes of radius the `radius` column times `scale`.
- **Defaults.** `colormap` `"Viridis (matplotlib)"`, `range` `"auto"`, `log` false, `opacity` 1, `visible` true,
  `representation` `"Surface"`, `solid_color` white, a tube's `scale` 1.
- Every name a layer gives (data structure, mesh, entity sets, columns) SHOULD be in the frames it goes with;
  the Python reference implementation checks them (`openalea.encoding3d.views.check_views(views, frame)`). In a frame
  that lacks one (e.g. a mesh drawn from a later frame on), a viewer draws the layer empty.

### 8.2 Archives

A sequence MAY be packed into one file, a **`.fspm.zip`** archive: a ZIP archive (ZIP64 when it needs to be) of the
folder's layout, its members at the same relative paths (`scene.fspm.json`, `views.json`, the frames, `parts/<key>.glb`).

- Each member is an unchanged file of the folder, compressed alone: `stored`, `deflate` or `lzma` (ZIP's methods 0, 8
  and 14), so that a reader reads one frame without the others. Writers SHOULD use deflate, which every ZIP reader
  has; a member holds no other archive.
- A reader opens an archive as it opens the folder. A file inside one is named `<archive>.fspm.zip/<member>`, e.g.
  `run.fspm.zip/frame_000003.glb`.
- An archive is for sharing and keeping a sequence once written. A sequence being written (a run) is a folder, which
  survives a crash and grows frame by frame; a single GLB holding a sequence is not part of 0.4.

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
| `missing_values` | integer, text and boolean columns with missing values; a date column; `unknown` edge types and a `sibling_order` column; a `mixed` entity set; a labels map; bearer relations between two pairs of sets |
| `growing_sequence/` | three frames of a growing root system and their index |
| `instances/` | a sequence of two frames whose root segments are drawn by sections, instances of two templates: transforms, owners, an instance variable, vectors, a derived field of one term (dense, sparse solved) or two weighted terms with an offset; its parts (`parts/`, their expected values in `expected/<key>.json`), each frame's evaluated field (`frame_*.evaluated.json`), and the last frame with its parts embedded (`embedded.glb`) |
| `archives/` | the `instances/` sequence packed into `.fspm.zip` archives: stored, deflate, lzma, and stored with every size and offset in ZIP64 records |

An implementation conforms to 0.4 when two things hold:

- **Reading:** what it reads from every conformance GLB equals the expected JSON. Floats are compared exactly; NaN and
  missing values are null in the JSON, +∞ and −∞ the strings `"Infinity"` and `"-Infinity"`; positions are the
  FLOAT32 values.
- **Writing:** what it writes passes `encoding3d validate` with no error, and Khronos' glTF-Validator with no error.

An implementation reading instances (§12) conforms when it reads `instances/` as expected, each part as its
`expected/<key>.json`, and evaluates each frame's derived fields to its `frame_*.evaluated.json` within a relative
1e-12 (a solved operator's values depend on the solver's rounding); reading archives (§8.2), when it reads each frame
of every archive of `archives/` as the folder's. `conformance/README.md` gives the dumps `encoding3d compare-all`
compares. A codec that reads 0.3 only skips `instances/` and `archives/`, as it skips `coupling/`.

A codec's participant (§11) conforms when it runs every **coupling session** of `conformance/coupling/` as expected,
over both transports. A session's folder holds the coordinator's settings (`session.json`), a peer (a sequence the
coordinator replays), the subject's declaration and the updates it sends (`subject/`), and the expected values
(`expected/turn_<step>.json`: what the subject reads from each turn; `expected/record/frame_<step>.json`: the
session's record). The participant under test is a program run as `COMMAND SESSION OUT`: it joins with the
declaration, writes what it reads from each turn to `OUT/turn_<step>.json` (in the expected values' layout), and sends
`subject/update_<step>.glb` as its codec reads and writes it again. `encoding3d couple-conformance conformance/coupling
--participant COMMAND` runs and compares them all.

| Session | Covers |
|---|---|
| `two_scales` | a subject refining a replayed peer's organs into segments: new entities, removals cascading to the subject's segments, a unit conversion and a factor, a copy to finer entities |
| `two_data_structures` | a subject owning another data structure, linked to the peer's by the mapping it provides: a sum through a mapping, mappings in updates |

## 10. Keeping what one does not read

A reader that writes a file back SHOULD keep the content it does not interpret, as RSML requires. In 0.4 this covers
the glTF root's other extensions and `extras`, when they hold no buffer views.

## 11. Coupling

Platforms couple their models through encoding3d in a **session**: each **participant** is a platform's model running
in its own process, or a recorded sequence (§11.6), and a **coordinator** runs the session. The coordinator holds the
session's shared structure (the entities of every data structure and the values each participant provides), applies
the links between them and sends each participant its inputs. A participant only declares itself, then answers each
of its turns with its outputs. Nothing about a given coupling is fixed in advance: declarations and links are passed
when the session starts.

### 11.1 Partial frames

Turns and updates are **partial frames**: frames whose `FSPM_scene` has an `update` object.

- `update.participant` is the sender's name, or `"coordinator"`.
- `update.removed` lists, per data structure and entity set, a property table of one `id` column: the entities
  removed (by the sender, or since the receiver's last turn).
- Its entity sets hold some rows and some columns only. A row is identified by its `id`.
- `complex` and `parent` MAY refer to entities the frame does not hold, and MAY be absent. Relations and mappings MAY
  likewise refer to absent entities.
- Every other rule of a frame holds. The validator checks partial frames with the reference checks lifted.

### 11.2 Messages

A message is a JSON header and, for a turn or an update, a payload: a partial frame's GLB bytes.

| Message | From | Header | Payload |
|---|---|---|---|
| hello | participant | `type`, `protocol` (`"0.3"`), `declaration`, `links` (the links it proposes, may be empty) | – |
| welcome | coordinator | `type`, `idOffset`, `idCount`, `session` (`start`, `interval`, `timeUnit`, `steps`, `stages`, `participants`, `keepMessages`), `couplings` (its inputs' providers) | – |
| turn | coordinator | `type`, `step`, `phase` (`"init"` at step 0, else `"step"`), `time`, `until` | its inputs |
| update | participant | `type`, `step` | its outputs |
| error | participant | `type`, `message` | – |
| stop | coordinator | `type`, `reason` | – |

**Declaration.**
- `participant`: its name, an identifier.
- `platform`: optional.
- `entitySets`: each entity set it works on, as `dataStructure`, `name`, `rank`, and `rights` on its topology:
  - `owns`: it adds and removes the entities. An entity set has one owner at most.
  - `refines`: it adds entities, and removes the ones it created.
  - `follows`: it reads.
- `variables`: each one with `dataStructure`, `entitySet`, `name`, `direction` (`provides`: an output; `requires`: an
  input), `unit` (UCUM), and optionally `standardName`, `kind`, `optional`.
- `mappings` (optional): the mappings it provides, each with its `name`, `source` and `target` (`dataStructure`,
  `entitySet`). Its updates carry them as the frame's mappings (§1) of those names; each one sent replaces the
  previous.

**Link.** A link names the input it feeds and the output that feeds it:
- the input: `receiver`, `variable`, `entitySet` (when the name is ambiguous);
- the output: `provider`, `source`, `sourceEntitySet`;
- its conversion: `factor` (applied after the unit conversion), `aggregation` and `interpolation` (`hold` or
  `linear`, §11.6);
- `mapping`: between two data structures, the name of a mapping a participant provides, read in either direction.

**Aggregation.** A link may change the scale:
- `sum`, `mean`, `max` or `min` from a finer entity set, through the `complex` chain. The default is `sum` for an
  extensive source, `mean` otherwise.
- `copy` from a coarser one. An extensive source needs `copy` stated explicitly, because copying it to finer entities
  counts it several times.

**Between two data structures**, a link goes through its mapping (weights `w` between source entities `s` and target
entities `t`):
- `sum` (the default for an extensive source) shares each source's value among its targets in proportion to their
  weights: `x_t = Σ_s x_s · w_st / Σ_t' w_st'`. The total amount is kept.
- `mean` (the default otherwise) gives each target the weighted mean of its sources: `x_t = Σ_s w_st · x_s / Σ_s w_st`.
- A target no source reaches has no value.

Formulas are not part of a link: a receiver computes them from its linked inputs.

### 11.3 Resolution

Before the first step, the coordinator gives each required input exactly one provider, in this order:
1. a link given to the coordinator;
2. a link proposed by a participant;
3. the output with the same standard name, preferring one on the same entity set;
4. the output with the same name.

It refuses the session, and stops every participant with the reason, when any of these holds:
- an input that is not optional has no provider, or has several at the same priority;
- the units are not convertible;
- an entity set has two owners;
- a stage holds two participants that change one entity set's topology;
- a link joins two data structures without a mapping, or with a mapping whose ends are not the link's.

### 11.4 Steps and stages

- The session runs `steps` exchange steps of `interval` (in `timeUnit`), from `start`.
- Participants are grouped in **stages**: given to the coordinator, or by default the owners, then the refiners, then
  the others.
- **Initial state (step 0).** Stage by stage, each participant is sent a turn with the entities so far, and answers
  with its initial entities and outputs.
- **Each step k ≥ 1.** Stage by stage:
  1. each participant of the stage is sent a turn from `time` to `until`, holding its inputs and the entities added or
     removed since its last turn;
  2. once all of them answered, their updates are merged, in the stage's order.

  Participants in one stage therefore see the same state, and the next stage sees theirs. The coupling is explicit:
  one pass per step.
- After the last step, every participant is sent `stop`. An error message, or an update the coordinator refuses, also
  stops the session, and every participant gets the reason.

### 11.5 One structure, several participants

- **Ids.** A participant's new entities take ids in `[idOffset, idOffset + idCount)`, so ids never collide.
  Participants keep their own ids, and map them, if they need to.
- **Rights.** A participant may write:
  - only the outputs it declared;
  - the topology columns only of entities it created, or of an entity set it owns.
- **Removal.** Removing an entity removes, down the finer entity sets, the entities whose complex it is. Its successors
  in its own entity set become roots.
- **New entities.** A participant receives new entities with their `parent` and `complex`, and initializes its own
  variables on them. When an entity splits, the participant shares its own extensive quantities and dilutes its own
  concentrations by its rules; the entity's lineage is its `parent`.
- **Labels.** An entity created without a label takes its entity set's name.
- **Scales a participant does not know.** A participant declares only the entity sets it works on. One that grows a
  coarse architecture (say, organs) needs to know nothing of the finer entities another participant refines under
  them (segments, cells): it is never sent them, and when it removes an organ, the coordinator removes the organ's
  segments and tells their refiner.

### 11.6 Transports

Both transports carry the same messages.

- **ZeroMQ** (endpoint `tcp://…` or `ipc://…`).
  - The coordinator binds a ROUTER socket.
  - Each participant connects a DEALER socket whose identity is its name.
  - A message is one or two frames: the header, then the payload.
- **A folder** (endpoint `files:<path>`).
  - Participant `p` has two queues, `<path>/p/to_coordinator/` and `<path>/p/to_participant/`.
  - Message n of a queue is `n.json`, n as 8 digits from `00000000`.
  - Its payload is `n.glb`, named in the header's `payload` key.
  - The payload is written first, and the header is renamed into place last, so a header present means a complete
    message.
  - Its reader deletes a message's files once read, unless the session keeps them (`keepMessages` true in the
    welcome's `session`; absent: kept). A participant applies it from the welcome on, deleting the welcome too; the
    coordinator, from the start. Kept, the folder is the session's log; a session needs a new folder. The usual log of
    a session is its record, a sequence of full frames (§8) the coordinator writes when asked.
- **Launching.** A participant launched by the coordinator finds the endpoint in the environment variable
  `ENCODING3D_ENDPOINT` and its name in `ENCODING3D_PARTICIPANT`.
- **Replay.** A recorded sequence (§8) may be a participant, so a platform's log feeds another platform's inputs without
  the first one running.
  - It owns its entity sets, and provides their variables.
  - Its ids are renumbered within its range.
  - Between two recorded times, its values are those of the last frame at or before the session's time (`hold`), or
    interpolated linearly for links stating `"interpolation": "linear"`.

## 12. Instances, derived fields and shared parts

Many entities of a scene often have the same geometry and the same internal structure: the sections of a plant's
root segments, the cells of a tissue at a coarse scale, the leaves of a canopy drawn by a few shapes. A frame then
stores that geometry once, as a **template**, and one record per entity drawing it, an **instance**. When an
entity's internal field (e.g. the values on a section's cells) is a linear function of a few values the platform
keeps (e.g. those on its boundary), the frame stores the function once, as an **operator**, and the few values per
instance: a reader rebuilds the field of the instances it shows. Templates and operators are **shared parts**, stored
once for a whole sequence. Nothing here depends on the model: any platform whose entities have a declared shape and,
for derived fields, a declared linear recovery, writes them the same way.

### 12.1 Shared parts

- **A part is a GLB file** following every rule of §2, whose `FSPM_scene` has a `part` object; its `frame` is
  `{"time": 0, "timeUnit": "d", "step": 0}` and it has no `writer`. Its kind is `template` or `operator`:
  - a **template** holds one data structure, `template` (kind `table`, or `graph` with ranks): its entity sets (the
    template's own entities, e.g. a section's cells, with ids of their own and their constant variables) and its
    meshes, in the template's coordinates. A template is a valid frame, so any reader opens one alone.
  - an **operator** holds no data structure; `part` gives its `format`, `rows` and `columns`, and the buffer views of
    its arrays (little-endian; FLOAT64 values, INT64 indices):

    | `format` | Arrays | The operator A |
    |---|---|---|
    | `dense` | `values`: rows × columns, row by row | the matrix |
    | `csr` | `indptr` (rows + 1), `indices`, `values`: compressed sparse rows | the matrix |
    | `solve` | `system` (rows × rows) and `rightHandSide` (rows × columns), each `{indptr, indices, values}` | S⁻¹ R, S the system (invertible), R the right-hand side |

    A writer stores a large operator whose matrix would be dense (e.g. the inverse of a sparse system) as `solve`; the
    reader then solves S x = R v, once per evaluation.
- **Content key.** A part's key is the SHA-256 of its file's bytes, in lower-case hexadecimal (64 characters). A writer
  computes it from the bytes it writes, so the same part always has the same key and is written once; a reader MAY
  check it, the validator does.
- **Where a part is.** A frame refers to a part by its key only. A reader looks for it, in this order:
  1. in the frame: `FSPM_scene.parts` maps a key to a buffer view of the frame holding the part's bytes (a
     self-contained frame);
  2. at `parts/<key>.glb` in the frame's folder (a sequence's folder, an archive, or the folder of a frame written
     alone).

  A reader that needs a part it does not find MUST report an error naming its key. A reader that does not read
  instances needs no part.

### 12.2 Instance sets

A data structure's `instanceSets` lists its instance sets. Each one has:

- `name`: an identifier, unique among the data structure's instance sets;
- `parts`: the keys of the parts its instances use; the instance table's indices point into this list;
- `owners` (optional): the entity set of the data structure whose entities the instances draw;
- `propertyTable`: the **instance table**, one row per instance;
- `vectors` (optional): its vectors (below), each `{name, propertyTable}`;
- `derivedFields` (optional): its derived fields (§12.3).

The instance table's reserved columns:

| Column | Type | Meaning |
|---|---|---|
| `template` | INT64, required | the index in `parts` of the instance's template |
| `owner` | INT64 | the id, in `owners`, of the entity the instance draws; required with `owners` |
| `transform` | FLOAT64 vector of 16, optional | the column-major 4×4 matrix placing the template's coordinates in the data structure's (identity when absent) |
| `id` | INT64, optional | the instance's id: non-negative, unique in the set, kept across frames like entity ids |
| `<vector>__count` | INT64 | the length of the instance's vector `<vector>` |
| `<field>__operator` | INT64 (a vector of K for K terms ≥ 2) | for each term of the derived field `<field>`, the index in `parts` of its operator, −1 for none |
| `<field>__weight` | FLOAT64 (a vector of K for K terms ≥ 2) | each term's weight |

Its other columns are the instances' own variables, declared as any variable (§5).

- **Vectors.** A vector is one array of numbers per instance, of the instance's own length (e.g. the values a derived
  field applies to). Its table has one column, `values` (FLOAT64): the instances' vectors one after the other, in the
  instance table's order. `<vector>__count` gives each one's length; they sum to the table's row count.
- **Drawing.** An instance is drawn as every mesh of its template, its positions moved by its transform, then by the
  data structure's origin. Each triangle has its row in the template's entity sets (the template mesh's feature IDs),
  the instance's row in the instance table, and through `owner` the entity it draws and that entity's containing ones.
- **Readers that do not evaluate derived fields** still read the instance table (its own variables, owners and
  transforms), the vectors, and the templates (their own constant variables) as tables.

### 12.3 Derived fields

A derived field is a field on one entity set of the templates, rebuilt for each instance from its vectors. Its entry:

- `name`: an identifier, not a column of the instance table;
- `entitySet`: the templates' entity set it is on (every template its instances use has it);
- `input`: the vector its operators apply to;
- `terms`: K, its number of terms;
- `offsets` (optional): K names of vectors, or null: each term's offset;
- `variable`: its declaration (§5), usually of role `derived`.

For the instance i, with v its `input` vector, the field is

  f = Σ_k w_k · (A_k · v + b_k),

over its terms k whose operator index is not −1: A_k the operator at that index of `parts`, w_k the term's weight, and
b_k the instance's vector `offsets[k]` (none when null, or of length 0). Then A_k has as many rows as the instance's
template has entities in `entitySet` and as many columns as v has values, and b_k has as many values as rows. f is on
those entities, in their rows' order. An instance without any term has no value (NaN).

- **Several terms** blend operators, e.g. the interpolation between the operators of two templates' classes, with no
  other primitive.
- **An offset linear in the instance's own values** (e.g. a source term) is better folded into the operator: v then
  holds those values too, and the operator one more column per value, so the frame holds no vector of the template's
  size per instance.
- A platform declares a derived field when its model gives the entity's inner values as a linear function of the values
  it keeps: a reduced network's eliminated nodes from its kept ones (x_I = −A_II⁻¹ A_IB x_B, stored as a `solve` or a
  dense operator, the sources as an offset), a coarse cell's sub-cells by a linear recovery from its own values, a
  shape's vertices by blending a few modes.

## Changes from 0.3

All additions; a 0.3 file is a valid 0.4 file.

- §12: instance sets (`instanceSets`: a template, a transform, an owner and variables per instance; vectors), linear
  derived fields (Σ_k w_k · (A_k · v + b_k), operators dense, sparse, or a sparse system solved when evaluated), shared
  parts (templates and operators as GLB files of their own, `FSPM_scene.part`, keyed by the SHA-256 of their bytes,
  embedded in a frame or at `parts/<key>.glb`); the conformance case `instances/`.
- §8: the folder's layout, the index's `parts`; §8.2: a sequence packed into a `.fspm.zip` archive.
- §8.1: views' `instances` layers.

## Changes from 0.2

All additions; a 0.2 file is a valid 0.3 file.

- §8.1: views, an optional companion of a sequence (`views.json`, `spec/schema/views.schema.json`): configurations of
  layers, each a selection of a mesh's, segments' or grid's entities and how they are drawn.

- §11: coupling sessions: partial frames (`FSPM_scene.update`), the messages (`spec/schema/coupling.schema.json`),
  declarations and rights, links (units, factors, changes of scale, mappings between data structures), stages, the
  shared structure, two transports, replay; conformance sessions (§9).

## Changes from 0.1

All additions; a 0.1 file is a valid 0.2 file.

- Sources: `conformance/` is part of the agreement; the order in which the sources prevail.
- §1: an entity set's `scale`, ranks as base scale positions, reading by content; position columns in their declared
  length unit.
- §2: the buffer's `byteLength` holds the padding.
- §3: unique relation names, a data structure's `labels`, the extras key.
- §4.1: missing values in integer, text and boolean columns.
- §4.2: `edge_type` `unknown`, the `sibling_order` column, a parent in another complex, bearer relations' labels and names.
- §5: a variable's `format`.
- §6: the vocabulary 0.2 (`Seed`, `mtg_index`).
- §8: sparse ids.
- §9: the `missing_values` scene.
