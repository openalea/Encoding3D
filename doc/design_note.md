# encoding3d: design note

*An exchange format for whole FSPM scenes, across platforms and languages.*

Status (2026-10-29; updated 2026-11-03): the decisions of §7 are taken on the metafspm side; P1 to P5 are done (§6).
The specification itself is `spec/specification.md`, now version 0.3, a draft until the partner platforms have
reviewed it. This note keeps
the review of the existing formats and the reasons for the choices; where the two differ, the specification is the
reference. Points marked **[to verify]** have not been checked on real files or code yet.

## 1. Purpose

Functional-structural plant models are written on several platforms, each in its own language:

- openalea.metafspm (Python);
- CPlantBox (C++, with Python bindings);
- GroIMP (Java/XL);
- VirtualPlantLab (VPL, Julia).

These platforms share no common representation of a *scene*: plants with their multiscale structure, their state
variables, their geometry, and their environment (soil grids, light, weather).

encoding3d aims at two uses:

1. **Static exchange:** one file, written by one platform and read by another. It holds a scene, or a sequence of time
   steps of it: a simulation's output, or an initial state given to another model.
2. **Dynamic coupling:** components from different platforms exchanging the same data in memory at each time step.
   The format's data model then serves as the interface.

It also aims to be a basis for **semantic coupling**: a shared, versioned vocabulary of scales and variables, with
units, which each platform maps its own names to.

Precedent: RSML ([openalea/RSML](https://github.com/openalea/RSML), Lobet et al. 2015) did this for root
architectures. It is adopted by about ten tools, including CPlantBox, ArchiSimple, GroIMP's `rsmlreader` and
openalea's `rsml2mtg`. encoding3d extends the idea to whole scenes, all scales, state variables and environments.

## 2. Requirements

| # | Requirement | Why |
|---|---|---|
| R1 | Language-neutral, with readers and writers feasible in Python, C++, Java and Julia | the four platforms |
| R2 | Multiscale plant graphs: decomposition across scales, and succession and branching within a scale (the MTG) | every platform's plant model is an MTG or an equivalent graph (GroIMP's RGG, VPL's graphs) |
| R3 | Other graphs: cell networks (MECHA), voxel neighbourhoods, any typed relation (GroIMP's XEG edge types) | non-tree structures |
| R4 | Per-entity state variables as float64 and int64, bit-exact on a round trip | simulation states must not be degraded |
| R5 | Geometry linked to entities, at any scale; scales without geometry; several overlapping scales with geometry | organs, segments and envelopes |
| R6 | Environment data structures: regular and adaptive grids, and their mappings to the plants' entities | soil-root coupling |
| R7 | Time: a sequence of states whose topology grows (new entities, never-reused ids) | growth |
| R8 | Declared variables: unit, meaning, kind (extensive or intensive), scale, provenance | semantic coupling, and correct mapping between scales |
| R9 | Efficient on disk and in memory: binary columns, no large number lists in JSON or XML | 10⁵–10⁶ entities × tens of variables |
| R10 | Viewable in standard tools without plant-specific code, at least for the geometry and a few variables | inspection, communication |
| R11 | Unknown content kept by readers that re-save, as in RSML's rule | partial readers must not lose data |
| R12 | A small specification, quick to implement | adoption depends on how cheap a first reader is |

## 3. What exists (review)

The details and sources are in Appendix A. In short:

### 3.1 glTF 2.0 and its metadata extensions

- **Core glTF.** JSON plus binary buffers, with a node tree (one parent per node, local transforms), meshes, and
  typed accessors.
  - Accessor component types stop at float32 and uint32: there is no float64 or int64. Proposal PR #2395 is still
    open.
  - Application-specific vertex attributes are allowed if their name starts with `_`.
  - A file may hold several `scenes`, but they carry no meaning of time or sequence.
  - A GLB file is limited to 4 GiB; external `.bin` buffers are not limited.
- **`EXT_structural_metadata` and `EXT_mesh_features`.** Both are drafts at Khronos (PR #2151 is still open). They are
  normative in 3D Tiles 1.1, an OGC Community Standard.
  - They add a schema of classes and enums and stores values in columnar **property tables**, which support FLOAT64,
    INT64, UINT64, strings, enums and variable-length arrays.
  - They also add **feature IDs** on vertices, and a primitive can carry **several feature ID sets**.
  - Property tables do not have to be referenced by a mesh.
  - They have **no reference (foreign key) type** and **no unit field**.
  - FLOAT64 is allowed in property tables only, not in vertex attributes.
- **Libraries.**
  - Full typed support for the metadata extensions exists only in C++ (cesium-native) and JavaScript.
  - Java has JSON classes only (JglTF's generated modules).
  - Python and Julia have only generic glTF libraries (pygltflib, trimesh; GLTF.jl, last pushed 2024, `.gltf` only).
  - Because property tables are plain typed buffers, a hand-written codec is small. Sections 4.2–4.4 keep to a subset
    of the extensions that stays small.
- **Viewers.**
  - The VTK/ParaView glTF reader turns `_` vertex attributes into point-data arrays, always as float32. It ignores
    `extras` and the metadata extensions. It reads one scene at a time, and reads animations as time steps.
  - CesiumJS and 3DTilesRendererJS (three.js) read the metadata extensions.
  - Blender keeps `_` attributes and `extras`.
- **Plant precedents.**
  - **PlantConvert** (openalea-incubator, Apache-2.0, development paused since 2025-05) converts between MTG, OPF,
    glTF and VTK.
    - Its glTF writer makes one glTF node per MTG vertex and one glTF scene per scale.
    - Attributes go in node `extras`, as JSON.
    - It has no extensions and no notion of time.
  - **GroIMP** has a glTF import/export plugin (geometry and transform hierarchy). It does not appear to export node
    attributes **[to verify]**.

### 3.2 Alternatives

| Candidate | As a file | As in-memory transport | Notes |
|---|---|---|---|
| **glTF + structural metadata** | good: typed tables, geometry, a single file, every viewer | possible, but the JSON changes with the topology | no time model, ParaView ignores the metadata |
| **OpenUSD** | very expressive (typed attributes, time samples, schemas) | within one process only | **no Java or Julia bindings**, no open ParaView reader: excluded for R1 |
| **VTKHDF** (HDF5) | very good for geometry, networks and grids over time: per-step offsets let topology grow; ParaView ≥ 6.0 reads it natively | no | no graph semantics for MTG relations (would need side tables); HDF5 dependency |
| **VTK XML** (.vtp/.vtu + .pvd) | simple, mature, one file per step | no | CPlantBox and OpenSimRoot already write it; weak for composites |
| **HDF5 / Zarr v3** | generic containers: every semantic to be specified | no (Zarr: chunked appends) | Zarr v3 is incomplete in Julia |
| **Apache Arrow** (IPC/Feather) | good for tables | **best**: memory-mapped IPC works in all four languages; zero-copy through the C Data Interface in Python, C++ and Java (not Julia) | no geometry model of its own; GeoArrow is a precedent for extension types |
| **OPF** (AMAP, XML) | MTG topology, per-node transforms of shared meshes | no | numbers in XML; no units or time. PlantGeom.jl (VPL) reads and writes it |
| **XEG** (GroIMP, XML) | general typed graph | no | numbers in XML |
| **RSML** (XML) | roots only, polylines only | no | one file per time step; adopted widely |

For coupling interfaces:

- **CSDMS BMI 2.0** has bindings in C, C++, Fortran, Python, Java and Julia. It covers initialise, update, get/set
  values (with `get_value_ptr` for zero-copy), units and grids. It has no multiscale graph, and its grid sizes are
  fixed after initialisation.
- **FMI 3.0** resizes arrays only in configuration modes.
- **preCICE** has no Java binding. **MUSCLE3** has no Java or Julia binding.
- **yggdrasil** (Crops in silico) has no Java binding.
- **GroLink** (GroIMP's HTTP API, JOSS 2025) exchanges files.
- **PlantSimEngine.jl** (VPL) maps models to MTG scales within Julia. It is the closest analogue to metafspm's
  coupling.

For semantics:

- The **CF conventions' standard-name table** (climate science) is the model of a versioned vocabulary with canonical
  units.
- **I-ADOPT** breaks a variable down into property, object of interest, matrix, context and constraint, e.g.
  "concentration / sucrose / phloem / root segment".
- The **Plant Ontology** types organs; RSML already uses `po:accession`.
- **UCUM** gives machine-readable unit codes.

### 3.3 Reading

No single existing format meets R1–R12:

- glTF meets R1, R5, R9, R10 and R12. With property tables it also meets R2–R4, R6 and R8, *by convention*.
- glTF does not meet R7 (time) by itself.
- VTKHDF is better for R7 and for ParaView, but weaker for R2, R5 and R12.
- Arrow is the right tool for in-memory coupling, but not a scene file.

This leads to the layered design below.

## 4. Proposed design

### 4.1 Three layers, one data model

```
             data model  (§4.2: entities, scales, relations, variables, geometry links, frames)
            /                         \
  glTF binding (§4.4)           Arrow binding (§4.6)
  the exchange file             in-memory coupling
            \                         /
             vocabulary (§4.5: standard names, units, kinds, scales)
```

The **specification** is the data model plus the vocabulary. The bindings are how they are written:

- glTF is the normative file binding.
- Arrow is the normative transport binding.

Each binding maps the same tables mechanically, so converting between them is a copy of columns.

### 4.2 The data model

A **scene** holds **frames**: its state at successive times. A frame holds data structures, mappings and geometry.

#### Data structures

A **data structure** is one plant population's graph, or one environment model's grid. Each has:

- `id`, `kind` (`graph`, `regular_grid`, `adaptive_grid`, `table`), and the platform and model that wrote it;
- an **origin transform** (a 4×4 matrix in float64): the frame its coordinates are in, relative to the scene's.

#### Entities

Entities are grouped in **entity sets**, one per scale for a graph (Plant, Axis, Phytomer, Organ, SubOrgan, ...), and
one per cell set for a grid. Each entity set is a table:

| column | type | meaning |
|---|---|---|
| `id` | uint64 | stable across frames, never reused in a data structure (RSML's `unified` ids) |
| `label` | enum | the entity's class: Segment, Apex, Leaf, Internode, ... (Plant Ontology terms in the vocabulary) |
| `complex` | uint64, `noData` = 2⁶⁴−1 | the entity containing it at the coarser scale (MTG `/`) |
| `parent` | uint64, `noData` | its predecessor at the same scale |
| `edge_type` | enum {`successor`, `branch`} | how it follows `parent` (MTG `<`, `+`) |
| *state variables* | float64, int64, enum, string, fixed-size arrays | one column each |

Scale names and ranks are declared per data structure. The vocabulary proposes a base set: metafspm's `ScalesConfig`,
which already spans Plant → Axis → GrowthUnit → Phytomer → Organ → SubOrgan → Layer → Cell.

#### Relations

**Relations** other than the MTG's are edge tables. An edge table holds `source` and `target` (uint64 ids, with the
entity sets they belong to), a `relation` enum (adjacency, plasmodesma, wall, refinement, ...), and edge variables (a
conductance, a flux).

- Cell networks, voxel faces and GroIMP's other edge types are all edge tables.
- metafspm's `edge` location (variables on parent→child junctions) is the edge table of the `successor`/`branch`
  relation, with the child's id as its key, as metafspm does.

#### Grids

A **regular grid** declares `shape`, `origin`, `spacing`, `axes` and `periodic`, plus a `z_up` flag (soil models
often point z down). Its cells are an entity set with implicit ids, the C-order index.

An **adaptive grid** stores its leaf cells explicitly: level, integer index, bounds.

#### Mappings

A **mapping** between two data structures is a table of `source_id`, `target_id`, `weight`, plus the method that
built it:

- metafspm's `CrossMapping` segment ↔ voxel, with `barycentre` or `overlap` and length fractions;
- a plant ↔ light-model mapping.

Mappings are optional: a reader can rebuild them. Writing them makes coupling results reproducible, and nobody
serialises them today (CPlantBox's segment-to-cell map is in memory only).

#### Variables

Each variable column is declared once per data structure, in the schema:

| field | type | meaning |
|---|---|---|
| `name` | string | the platform's own name |
| `standard_name` | string or empty | from the vocabulary (§4.5) |
| `unit` | UCUM code | |
| `kind` | enum | `extensive`, `intensive`, `massic_concentration`, `volumic_concentration`, ... |
| `role` | enum | `state`, `input`, `parameter`, `derived`, `setting` |
| `scale` | string | its entity set |
| `description`, `min`, `max`, `references`, `DOI` | | |

The `kind` field is what lets another platform map a variable between scales and grids correctly: sum an extensive
value, average an intensive one. metafspm's declarations already carry every one of these fields.

#### Scene-level values

**Scalars** are data-structure-level or scene-level values: a table with one row.

#### Geometry

**Geometry** is attached to a data structure as triangle or line meshes. Every vertex carries **one feature ID per
scale it represents**: the row of the entity at that scale. So one root mesh can be selected by element, by axis or by
plant.

- Scales with no geometry have none. A scale with its own geometry (an organ's envelope, a voxel grid's cells) has
  its own mesh.
- Meshes are **triangles** (decided, §7.3), also for segment models such as roots: they are what light models
  need, and what every viewer draws. A writer may keep the segments' exact ends and radii as float64 columns too.
- Repeated shapes (leaves of a template, plants of a stand) may use instancing, as OPF and AMAP do.

#### Parameter sets

A frame may hold only data structures with their declared parameters (role `parameter`) and no entities: a
**parameter set**, exchanged on its own (decided, §7.5).

#### Frames

A **frame** carries its time `t` (float64, unit s or d declared), a step index, and the topology version.

### 4.3 How metafspm maps to it (feasibility check)

| metafspm | data model |
|---|---|
| `MPGDataStructure`, `node` location (finest scale) | the finest entity set; `entity_ids("node")` gives the ids (vids, never reused) |
| coarse scales (`entity_ids("Plant")`, `"Axis"`, ...) | coarser entity sets; `complex` from `up_scale_parent` |
| MTG `edge_type` `<` / `+` | `parent` and `edge_type` columns |
| `edge` location (keyed by child vid) | the edge table of the successor/branch relation |
| anatomy mode (`Compartment`, `Connection`) | a cell entity set plus an edge table of Connections |
| `scalar` location | a one-row table |
| `ArrayDataStructure` (`shape`, `dx`, `origin`, `axes`, `periodic`) | a regular grid |
| `AdaptiveGridDataStructure` (leaves, levels) | an adaptive grid |
| `CrossMapping` (rows, columns, weights; `method`) | a mapping table |
| `Triangles(vertices, owner)` from `ds.triangles()` | a mesh; `owner` is the feature ID at the node scale; coarser feature IDs come from the membership |
| `VariableSpec` (`location`, `scale`, `kind`, `variable_type`, `dtype`, `shape`) and the declaration's `unit`, `description`, `min_value`, `max_value`, `references`, `DOI` | the variable declaration, field for field |
| `Scene` populations, planting table | data structures with origin transforms, scene table |
| `SceneRecorder` every N steps | frames |

`checkpoint()` already writes the same content: arrays by location with their dtype, entity ids, and a manifest. The
exporter is the same walk, with the arrays written into a GLB's binary chunk instead of `arrays.npz`.

The following are **not** exchanged; they stay in metafspm's own checkpoint:

- derivation formulas and mask rules, since these are code;
- the random streams' counters.

**As implemented in P2** (`openalea.metafspm.io.encoding3d`):

- **Every MPG scale holding vertices is an entity set**, Compartments included; the Connections are a relation, with
  their vids as ids. `complex` is the containing entity in any coarser set: a wall Compartment belongs to its
  segment, which is why the specification lets `complex` point past the nearest scale.
- **Every MPG property and every variable is a column.** Object values other than text are JSON text. Infinities use
  the specification's stand-ins.
- **What only metafspm needs to rebuild its MPG exactly** stays metafspm's own, for other platforms to ignore:
  - the raw MPG links, as the `metafspm_complex`, `metafspm_parent` and `metafspm_edge_type` columns;
  - the label codes, the variable metadata and the construction arguments, as `extras["metafspm"]`.
- **Standard names** come from the vocabulary's `metafspm` column.
- **Meshes:** the DataStructure's triangles are a mesh, and so is each component's `display_triangles()`. These are
  shapes for display only, e.g. GRANAP's sections.
- **Result:** the scenes of ArchiSimple, Adel, Caribu, GRANAP and MECHA rebuild bit for bit, and a simulation
  continues from a frame as from the original.

### 4.4 The glTF binding

One glTF asset is **one frame**. The binding uses only:

- core glTF;
- `EXT_structural_metadata`, property tables only: no property textures and no property attributes, because these
  can't hold float64;
- `EXT_mesh_features`, attribute feature IDs only;
- one encoding3d extension, `FSPM_scene` (decided, §7.1), holding what the
  metadata extension cannot hold.

#### Layout

```
asset.extensions.FSPM_scene        version, vocabulary version, frame (t, unit, step), writer
EXT_structural_metadata.schema     one class per entity set, edge table and mapping; enums for labels, edge types,
                                   relations
EXT_structural_metadata.propertyTables
                                   one per entity set, edge table, mapping and scalar table: float64 and uint64
                                   columns, 8-byte aligned
FSPM_scene.data_structures[]       id, kind, platform, origin matrix, scales (name, rank, propertyTable),
                                   relations (propertyTable, source and target sets), grid (shape, origin, spacing,
                                   axes, periodic, z_up)
FSPM_scene.variables{}             per class property: standard_name, unit (UCUM), kind, role, references
                                   (what EXT_structural_metadata lacks)
FSPM_scene.mappings[]              source and target data structures, method, propertyTable
nodes                              scene root → one node per data structure (its origin as a transform) → its meshes
meshes                             TRIANGLES or LINES, POSITION in float32 relative to the data structure's origin;
                                   _FEATURE_ID_0..k, one per represented scale, each pointing at its propertyTable;
                                   optional display copies of variables as _NAME float32 attributes
```

#### Choices and their reasons

- **The node tree stays coarse:** scene → data structure → mesh.
  - One glTF node per entity, as PlantConvert does, puts 10⁵ objects in the JSON. It also holds only one tree, so
    PlantConvert has to duplicate a scene per scale.
  - The MTG's relations are columns instead, where they are compact, typed and complete.
- **The relational columns are uint64 ids** whose meaning is fixed by encoding3d, since the metadata extension has no
  reference type. `FSPM_scene` declares, per column, which entity set the ids point to.
- **float64 state lives in property tables only.**
  - Viewers that ignore the extensions still show the geometry, and the `_NAME` float32 display copies (ParaView
    reads those as point data).
  - Display copies are optional and marked as such, so a reader never takes them for the state.
- **Positions are float32,** as glTF requires. They are written relative to the data structure's origin, so a plant
  in a 100 m field keeps sub-millimetre precision. Exact coordinates, such as metafspm's segment ends x1…z2, are also
  float64 columns when they are state.
- **The extensions are declared in `extensionsUsed`, not in `extensionsRequired`,** so that any glTF viewer opens the
  file.

#### Time sequences (decided, §7.2)

**One GLB per frame, plus an index** (`scene.fspm.json`: frames with t, step and file). This is the `.pvd` pattern.
It is simple, streamable and appendable. Unchanged buffers can be shared through external `.bin` files.

A tool may later pack a sequence into one GLB: per-frame property tables and meshes, with `FSPM_scene.frames[]`
pointing at them, capped at 4 GiB.

#### Viewing

- Any glTF viewer shows the geometry.
- ParaView, with the `openalea.encoding3d` reader plugin, shows every variable at every scale as float64 cell data, with the
  index's frames as time steps (§7.4).
- ParaView without the plugin, and other viewers, show the display copies: float32 per-vertex copies of chosen
  variables. Files have none by default; the writer's `display=` option or the `encoding3d display` tool adds them.
- Cesium and 3DTilesRendererJS show every table.

### 4.5 The vocabulary

A versioned table in the repository, `vocabulary/standard_names.csv`, following the CF model:

| column | content |
|---|---|
| `standard_name` | e.g. `root_segment_length`, `phloem_sucrose_concentration`, `soil_water_potential` |
| `canonical_unit` | UCUM code |
| `kind` | extensive, intensive, ... |
| `I-ADOPT decomposition` | property / object / matrix / context |
| `typical scales` | |
| `definition` | |

Labels map to Plant Ontology terms.

- **Start small:** about 30 names, drafted from the declarations of metafspm and its ported packages (ArchiSimple,
  Adel, Caribu, GRANAP, MECHA), and completed from CPlantBox, GroIMP and VPL where metafspm lacks a domain (decided,
  §7.7). They cover geometry, masses, ages, radii, lengths, water potentials, concentrations of the main solutes,
  temperatures, absorbed radiation and soil water content.
- **Grow it** through pull requests reviewed by the platforms.

### 4.6 Dynamic coupling (the Arrow binding)

Exchanging the glTF itself at each step would mean rebuilding the JSON whenever the topology changes. The binding for
coupling uses the same tables as **Arrow record batches** instead:

- **Column names and field metadata** (standard name, unit, kind) are the glTF schema's.
- **Ids** are uint64 columns, as in the glTF binding.
- **Within one process**, data passes through the Arrow C Data Interface: Python ↔ C++ ↔ Java, with zero copy.
- **Across processes,** the Arrow IPC format goes through memory-mapped files or pipes, in all four languages. Julia's
  Arrow.jl has no C Data Interface but reads and writes IPC.

A coupling **protocol** shaped like BMI:

- functions: `initialize`, `update(dt)`, `get_tables(names)`, `set_tables(...)`, `topology_version()`,
  `standard_names()`;
- extended over BMI with entity sets, scales and growing topology;
- with the table batch as the payload.

This is a later phase (§6). The data model is specified first, so that the coupling inherits it.

**Update (2026-11-03): built differently.** The coupling is the specification's §11. A coordinator (encoding3d's, in
Python) holds the shared structure and applies the links; each platform's participant declares what it works on,
provides and requires, then answers turns with updates. The messages carry **partial frames**, the same GLB as a time
step, not Arrow batches: every codec already reads and writes GLB, Arrow would have been a large new dependency in
all four (heavy in Java and C++), and measurements showed the format is not the cost (encoding 10 ms of a 100 ms step
at 100,000 segments; the rest is the coordinator's work). Transports: ZeroMQ, and a folder of files. A BMI-like
in-process interface is not part of it.

### 4.7 VTKHDF (dropped)

A VTKHDF export was considered for viewing long simulations in ParaView. It is dropped, to keep encoding3d free of an
HDF5 dependency (§7.8). ParaView views the glTF files themselves, through display copies.

### 4.8 Read and write cost in metafspm, and the glTF-backed DataStructure question

metafspm's DataStructures already hold one numpy array per variable and location. In the binding:

- **Export** is about `array.tobytes()` per column, plus a JSON schema built once per topology version.
- **Import** is `np.frombuffer` per column.

For 10⁵ entities × 50 float64 variables (40 MB), both are memory copies, on the order of 10–100 ms. Measured in P2,
everything included (the MPG's links and properties, the geometry, the JSON), on ArchiSimple's 15-day root system
(19,519 nodes, 303k mesh vertices, a 27 MB file):

| Step | Time |
|---|---|
| `scene_to_frame` | 0.47 s |
| writing the GLB | 0.09 s |
| reading it | 0.03 s |
| `from_frame` | 0.25 s |

A DataStructure *backed* by a glTF buffer would have to keep the JSON and the buffer layout consistent through every
`set`, every growth and every `register`. That reimplements what the numpy store does, with no gain in exactness or
speed. **Recommendation: no backing DataStructure.** Provide instead (all done in P2):

- `export_frame(path, data structures)`, `export_scene(path, scene)` and `import_frame(path) -> data structures`, in
  metafspm's `io` module, on top of the `openalea.encoding3d` codec (§5.1);
- a `SceneRecorder` option writing frames every N steps: `Scene(frame_period=N)`;
- the round-trip test as the contract: export → import gives the same ids, topology, values (bit for bit), metadata
  and mappings, for every DataStructure type and location;
- later, `to_arrow()` and `from_arrow()` on the same walk, for coupling.

## 5. Repository and governance

This repository is platform-neutral, separate from metafspm, like RSML.

```
encoding3d/
  README.md
  doc/design_note.md          this note
  spec/                       the agreement, the only folder discussed with the platforms:
    specification.md          the specification
    schema/                   JSON Schema of FSPM_scene and of the index file
    vocabulary/               standard_names.csv (with one column of names per platform), labels.csv, enums.json
  bindings/python/            the Python reference package (§5.1): codec, validator, display tool, command line, and
                              its tests; it reads spec/ and ships it (openalea.encoding3d.spec)
  bindings/<language>/        the other languages' codecs, by their teams (adapters stay in the platforms)
  paraview/                   the ParaView reader plugin
  conformance/                the reference files: a root system, a wheat shoot, a cell network, a soil grid with
                              its mapping, an adaptive grid, a parameter set, a 3-frame growing sequence; each GLB
                              with its expected values as JSON; generate.py writes them
  conda/, pyproject.toml      packaging, as metafspm's
  .github/workflows/          openalea's conda CI; the conformance job (our validator and Khronos' glTF-Validator)
  implementations.md          pointers to each platform's reader and writer, kept in the platforms' own repositories
```

- **The repository holds:** the specification, the schema, the vocabulary, the conformance files, and a small Python
  package, which is generic and knows no platform.
- **Each platform's own mapping lives in that platform:** metafspm's in metafspm, CPlantBox's in CPlantBox, and so on.
- **encoding3d is separate from RSML and PlantConvert** (decided, §7.6). Converters from OPF, `.mtg` or RSML can come
  later, in PlantConvert.
- **Rules:**
  - semantic versioning of the specification;
  - readers keep what they don't understand (RSML's rule);
  - every change comes with a conformance file and a validator check;
  - the vocabulary grows by review from at least two platforms.

### 5.1 Sources, tests, CI, and how metafspm uses the repository

Everything maintained in this repository is Python. The other platforms take part through files and a command line,
not code: no C++, Java or Julia has to be maintained here.

**The Python package `openalea.encoding3d`.** Its only dependencies are numpy and jsonschema; GLB is a 12-byte header plus a JSON
chunk and a binary chunk, so no glTF library is needed. It contains:

- `openalea.encoding3d.codec`:
  - `write(path, frame)` and `read(path) -> frame`, where a frame is plain Python: data structures, entity sets as
    `{column: numpy array}`, variable declarations as dicts, meshes as arrays with feature IDs;
  - `write_index` and `read_index` for sequences.
- `openalea.encoding3d.validate`: JSON Schema checks of `FSPM_scene` and the index; the checks the schema cannot express (ids
  unique and never reused across frames, `complex` and `parent` pointing to existing entities, units parsable as UCUM,
  kinds and standard names in the vocabulary, tables 8-byte aligned, display copies flagged).
- `openalea.encoding3d.display`: adds or removes display copies (§7.4).
- `openalea.encoding3d.vocabulary`: the vocabulary table, shipped as package data.
- A command line: `encoding3d validate file.glb`, `encoding3d display file.glb name ...`, `encoding3d info file.glb`.

**Tests and CI**, the same way as metafspm:

- pytest in `bindings/python/test/`;
- GitHub Actions with openalea's build-publish-anaconda action, publishing a noarch conda package to `openalea3` (and
  PyPI) on each release tag.
- The CI also runs Khronos' glTF-Validator (a standalone binary) on every conformance file, so the files stay valid
  glTF for every viewer.
- The conformance files are generated by a script in the repository, from hand-written frames, and committed. A test
  checks that the script still produces them byte for byte.

**How another platform tests its implementation**, in its own CI:

- **Writing:** it writes the conformance scenes with its own code and runs `encoding3d validate` (conda or pip, or
  a container).
- **Reading:** it reads the conformance GLBs with its own code and compares the values with the expected JSON.

The platform needs nothing else from Python, and its CI shows whether it follows the specification version it
claims.

**How metafspm uses it:**

- `openalea.metafspm.io.encoding3d`, a new module, maps metafspm's DataStructures, mappings and declarations to
  `encoding3d` frames and back (§4.3), and calls the codec. It is the only metafspm code concerned.
- metafspm's environment and recipe add `openalea.encoding3d`, pinned to the specification version it implements
  (`openalea.encoding3d >=0.1,<0.2`).
- During development it is installed with `pip install -e ../encoding3d`, as metafspm itself is in the ported packages.
- metafspm's tests use the round trip (§4.8), `openalea.encoding3d.validate` on what it writes, and the conformance files on
  what it reads.
- A new release of the specification is a new `openalea.encoding3d` version. metafspm moves to it with a pin change, and its
  tests tell what has to follow.

### 5.2 What other languages need

The format's conventions reach other platforms as **files, not code**. Each release of the specification publishes,
in `schema/`, `vocabulary/` and `conformance/` (and as release assets):

| Artefact | Content | Read in C++ / Java / Julia with |
|---|---|---|
| `spec/` | the specification text | — |
| `schema/fspm_scene.schema.json`, `schema/index.schema.json` | the structure of `FSPM_scene` and of the index | any JSON Schema validator: valijson or json-schema-validator (C++), networknt json-schema-validator (Java), JSONSchema.jl (Julia) |
| `vocabulary/standard_names.csv`, `vocabulary/enums.json` | standard names with units and kinds; labels, edge types, relations, kinds, roles | any CSV or JSON reader |
| `conformance/*.glb` with `*.expected.json` | the reference scenes and their values | the platform's own codec, against the JSON |
| `encoding3d validate` | the full checks, as a command line | its CI (conda, pip, or a container image) |

What a platform writes is **its codec**:
- **The GLB container:** a 12-byte header, a JSON chunk and a binary chunk.
- **The property tables:** each column is a slice of the binary chunk, cast to its type.
- **The mapping:** from these tables to its own model.

That is a few hundred lines in any language, and existing libraries can help:
- **C++ (CPlantBox):** cesium-native reads and writes `EXT_structural_metadata` fully. CPlantBox can also begin
  through its Python layer, with `openalea.encoding3d` directly.
- **Java (GroIMP):** JglTF has the extension's JSON classes. GroIMP's existing glTF plugin is the place to extend.
- **Julia (VPL):** GLTF.jl handles `.gltf` JSON only, so a small GLB reader has to be written. That is the part
  above, the header and the two chunks.

These codecs live in the platforms' repositories, maintained by their teams. `implementations.md` lists them with
the specification version each one passes. encoding3d itself maintains only Python.

**Update (2026-11-03): decided otherwise.** The codecs live in this repository (`bindings/<language>/`: Python, Julia,
C++, Java), each passing the conformance files; the adapters (a platform's model to and from the codec's tables)
belong to the platforms, as Julia package extensions where the platform's library is a plain dependency.
`implementations.md` lists them.

## 6. Plan

| Phase | Content | Done when | Status |
|---|---|---|---|
| P0 | This note, discussed with the partner platforms | the [decision] points settled | decisions taken on the metafspm side; review by the partners to come |
| P1 | Specification v0.1: data model, glTF binding, JSON Schema, first vocabulary; the `openalea.encoding3d` package (codec, validator, display tool), the conformance files, CI | the validator and glTF-Validator accept the conformance files | done |
| P2 | metafspm reference implementation: `export_frame` and `import_frame` for MPG, Array and AdaptiveGrid DataStructures, mappings and triangles | round-trip tests bit-exact on the ported models' scenes (ArchiSimple, Adel, Caribu, GRANAP and MECHA, soil) | done, with `Scene(frame_period=)`; the continuation after an import is exact too |
| P3 | The ParaView reader plugin (Python, on the `openalea.encoding3d` codec: every variable as cell data, frames as time steps); viewer checks of display copies: ParaView without the plugin, three.js/3DTilesRenderer, Blender | the example files viewed with their variables | ParaView done (6.0.1, the plugin and ParaView's own glTF reader); three.js and Blender skipped |
| P4 | A second platform: CPlantBox through its Python layer (the easiest), or VPL through PlantGeom.jl | a file written by one platform and read by the other, with the same values | done, and more: the Julia (VirtualPlantLab, MTG.jl), C++ (CPlantBox) and Java (GroIMP) codecs and adapters ([Implementations](implementations.md)) |
| P5 | Arrow binding and coupling protocol; a two-platform coupled run | one component in metafspm and one in another platform exchanging tables at each step | done without Arrow (§4.6's update): the coupling sessions of the specification's §11; metafspm coupled with VirtualPlantLab |

## 7. Open decisions

1. The extension's name and prefix: `FSPM_scene` (unregistered vendor prefix) vs a registered prefix.
answer: FSPM_scene
   → **Decided:** `FSPM_scene`.
2. Time layout: one GLB per frame plus an index (recommended) vs one packed GLB.
answer: yes to Recommendation
   → **Decided:** one GLB per frame plus the index `scene.fspm.json` (§4.4). A tool may pack them later.
3. Root geometry: LINES with radius vs triangles vs both.
answer: triangles
   → **Decided:** triangles only (§4.2).
4. Display copies: which variables, chosen by the writer or by a rule.
answer: I don't understand the question.
   → **Explanation.** The state variables are stored once per entity, in float64 property tables (§4.4). Viewers that
   don't read the metadata extension, ParaView among them, cannot use those tables to colour the geometry. They can
   only colour by a *vertex attribute*: a float32 value repeated on every vertex of every triangle (an attribute
   named `_WATER_POTENTIAL`, say). To see a root system coloured by its water potential in ParaView, the file must
   therefore hold a second, float32, per-vertex copy of that variable: a "display copy".
   - These copies cost space. A segment drawn as a cylinder has about 16 vertices, so a copy takes 16 × 4 = 64 bytes
     per entity, against 8 bytes for the float64 value in the table.
   - Copying every variable would make the file about 8 times larger.
   - The question is which variables get a copy.

   **Proposal:**
   - Files hold no display copies by default: they are exact and lean.
   - The writer takes an option `display=[names]` to add some.
   - The repository's tool also adds them to an existing file afterwards (`encoding3d display file.glb
     water_potential`), computed from the tables. A file can then be prepared for ParaView at any time, and no
     platform has to implement this.
   - Display copies are flagged as such, and readers ignore them as state.

   answer: I agree with the proposal, and for no display copies outputs, is there another viewer better suited for this?

   → **Decided:** display copies as proposed.

   **Viewers for files without display copies.** No existing viewer colours geometry by our tables *and* plays a
   sequence of time steps out of the box:
   - **CesiumJS** and **3DTilesRendererJS** (three.js) read `EXT_structural_metadata`. They can pick an entity and
     show its values, and colour by a property through a custom shader. But they are geospatial and web-graphics
     tools: there is no plot, no filter, and no notion of our index of time steps.

   The best-suited option is a **ParaView reader plugin written in Python**, shipped with `openalea.encoding3d`:
   - ParaView loads Python readers (a `VTKPythonAlgorithmBase` with its decorators, since ParaView 5.6). It runs
     them in its own Python, which has numpy, so the pure-Python `openalea.encoding3d` codec runs inside ParaView.
     (Checked with ParaView 6.0.1: nothing to install, the plugin finds `openalea.encoding3d` in the clone's `bindings/python/src/`.)
   - The plugin reads the GLB (or the index file) and turns each triangle's entity value into float64 *cell data*
     (one value per triangle, from the feature IDs). Every variable, at every scale, becomes available for colouring,
     filters and plots. The index's frames become ParaView's time steps, with a growing topology.
   - Nothing is duplicated on disk, and ParaView's whole analysis toolset applies.
   - This is P3 (§6). Display copies remain for viewers without the plugin: Blender, a web viewer, ParaView without
     the plugin.
5. Whether data-structure-level parameters are exchanged (parameter tables) or only states and inputs.
answer: also parameters, that would enable also to exchange them between platforms.
   → **Decided:** parameters are exchanged.
   - A parameter is a declared variable with role `parameter`, so it carries a unit, a standard name and references.
   - It is stored at the location it applies to:
     - a scene-wide value, in the data structure's one-row table;
     - one value per plant (metafspm's planting scenarios), as a Plant-scale column;
     - one value per entity type, as a column of that scale.
   - A file holding only parameters, with no entities, is valid: a **parameter set** that can be exchanged on its own
     (§4.2).
6. Coordination with PlantConvert and with the RSML maintainers: one family of formats, or encoding3d absorbing RSML's
   use cases.
answer: should be a separated initiative. In this regard, how is the test / source management and CI to be handled, since I am only used to python? In the example of metafspm, how will this repo or its release be used to build metafspm's io?
   → **Decided:** encoding3d is an initiative separate from RSML and PlantConvert. Converters to and from them can come
   later, in PlantConvert. On tests, sources, CI and metafspm's use of the repository: see §5.1. In short:
   - The repository holds the specification and a **Python** package, `openalea.encoding3d`, which depends only on numpy and
     jsonschema. It is the reference codec: it reads and writes GLB files, their property tables and the index, and
     knows nothing of metafspm. It also contains the validator and the conformance files.
   - Other platforms need no Python of yours. They use the conformance files (GLBs plus their expected values as
     JSON) as test fixtures in their own CI, and run the validator on what they write. The validator is installed by
     `pip` or `conda` and run as a command line.
   - metafspm depends on `openalea.encoding3d` like on any package, pinned to a specification version. Its `io` module maps
     DataStructures to the generic model and calls the codec.
     answer: ok for the strategy, I see how the python package will make it easily available in python, but for other languages / platforms what does it imply to make the format's conventions available?

   → See §5.2. In short:
   - The conventions are published as **language-neutral files**: the specification text; the JSON Schema; the
     vocabulary and the enums (labels, edge types, relations, kinds, roles) as JSON and CSV; the conformance files with
     their expected values. Every language reads these with its standard JSON tools, so no platform hard-codes the
     conventions.
   - Each platform writes **its own codec**: GLB's three parts, the property tables, and the mapping to its own model.
   - The validator checks every platform's output from the command line.
   - CPlantBox can also start from its Python layer with `openalea.encoding3d` directly.
7. The first vocabulary: who proposes it, and the 30 names to start from.
The first vocabulary can be inspired from metafspm's current version, but if metafspm lacks some aspects, you can inspire from other platforms.
   → **Decided:** the first vocabulary is drafted from the declarations of metafspm and of its ported packages
   (ArchiSimple, Adel, Caribu, GRANAP, MECHA). It is completed from CPlantBox, GroIMP and VPL where metafspm lacks a
   domain (§4.5).
8. Whether glTF stays the normative file binding, or VTKHDF takes that role. VTKHDF is better on time and ParaView,
   but needs HDF5 and is weaker on graphs. Recommendation: glTF.
answer: stay on glTF, I don't want an extra too complex dependency.
   → **Decided:** glTF only. The VTKHDF export is dropped (§4.7). ParaView views files through display copies (item 4).

## Appendix A: sources (checked 2026-10-29)

**glTF**

- glTF 2.0 specification: https://github.com/KhronosGroup/glTF/blob/main/specification/2.0/Specification.adoc
- Extension registry: https://github.com/KhronosGroup/glTF/blob/main/extensions/README.md
- `EXT_structural_metadata` (draft):
  https://github.com/CesiumGS/glTF/tree/3d-tiles-next/extensions/2.0/Vendor/EXT_structural_metadata
- Khronos PR #2151 (structural metadata): https://github.com/KhronosGroup/glTF/pull/2151
- Khronos PR #2395 (additional accessor types): https://github.com/KhronosGroup/glTF/pull/2395
- 3D Tiles 1.1, OGC 22-025r4: https://docs.ogc.org/cs/22-025r4/22-025r4.pdf
- 3D Metadata Specification: https://github.com/CesiumGS/3d-tiles/tree/main/specification/Metadata
- cesium-native: https://github.com/CesiumGS/cesium-native
- JglTF: https://github.com/javagl/JglTF
- GLTF.jl: https://docs.juliahub.com/General/GLTF/stable/
- VTK glTF reader: https://vtk.org/doc/nightly/html/classvtkGLTFReader.html
- ParaView glTF issue: https://gitlab.kitware.com/paraview/paraview/-/issues/22446

**Alternatives and coupling**

- VTKHDF: https://docs.vtk.org/en/latest/vtk_file_formats/vtkhdf_file_format
- VTKHDF 2025 status update: https://www.kitware.com/vtkhdf-file-format-2025-status-update/
- OpenUSD time samples: https://openusd.org/dev/user_guides/time_and_animated_values.html
- AOUSD Core Specification 1.0:
  https://aousd.org/uncategorized/foundations-of-open-3d-development-introducing-aousd-core-specification-1-0/
- GeoArrow extension types: https://github.com/geoarrow/geoarrow/blob/main/extension-types.md
- Arrow.jl: https://arrow.apache.org/julia/dev/
- Arrow 12.0 release (Plasma removed): https://arrow.apache.org/blog/2023/05/02/12.0.0-release
- BMI grids: https://bmi-spec.readthedocs.io/en/latest/model_grids.html
- FMI 3.0: https://fmi-standard.org/docs/3.0
- preCICE API: https://precice.org/couple-your-code-api
- MUSCLE3: https://muscle3.readthedocs.io/
- yggdrasil: https://cropsinsilico.github.io/yggdrasil/
- PlantSimEngine.jl: https://github.com/VirtualPlantLab/PlantSimEngine.jl
- I-ADOPT: https://w3id.org/iadopt

**Plant formats and platforms**

- RSML specification: https://github.com/RootSystemML/RootSystemML.github.io
- RSML in openalea: https://github.com/openalea/RSML
- OPF format: https://amapstudio.cirad.fr/_export/raw/soft/xplo/private/opf_format
- PlantConvert: https://github.com/openalea-incubator/PlantConvert
- PlantConvert's glTF writer: https://plantconvert.readthedocs.io/en/latest/_modules/openalea/plantconvert/gltf/writer.html
- GroIMP plugins (glTF, XEG, rsmlreader, api): https://gitlab.com/grogra/groimp-plugins
- GroIMP manual: https://manual.grogra.de/
- GroLink (JOSS 2025): https://joss.theoj.org/papers/10.21105/joss.08343
- Long et al. 2018, FSPM interoperability: doi 10.1145/3208854.3208875
- Long, Pradal & Kurth 2020, OpenAlea–GroIMP co-simulation: https://hal-lirmm.ccsd.cnrs.fr/hal-03059527v1
- CPlantBox with DuMux, SOIL 2026: https://soil.copernicus.org/articles/12/371/2026/

Not verified in this session:

- GroIMP's glTF export of node attributes;
- the cost figures of §4.8;
- Draco decoding in ParaView builds.
