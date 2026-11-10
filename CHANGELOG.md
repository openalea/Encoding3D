# Changelog

## Unreleased: specification 0.4 (draft), instances, derived fields, shared parts and archives

- **A frame written without copies** (Python): `write` streams the GLB piece by piece (`glb.write(file, document,
  buffers)`: the header, the JSON chunk, then each buffer view from its array's own memory and its padding);
  `glb.BufferBuilder` keeps byte views of the arrays instead of their bytes, `glb.pack` joins the same pieces once
  (`to_bytes`, `part_bytes`). The files are byte-identical. The former write copied the binary chunk 4-5 times
  (`tobytes` per array, the join, the padding, the chunks, the header): metafspm's use case 1 at 8 plants, day 12
  (a 39 MB frame) peaks +0.19 → +0.06 GB, with its sections +0.24 → +0.12 GB, 0.24 → 0.19 s and 0.45 → 0.37 s.

- **A checked pack, then the folder removed** (Python): `pack(folder, path, compression=, level=, keep_folder=False)`
  writes the archive next to *path*, checks it (`check_archive(path, folder)`: every file of the sequence a member and
  nothing else, of the same size and CRC-32, each member read back; the archive valid, 0 errors), moves it into
  place, then removes the folder; `keep_folder=True` keeps it. A failed check leaves the folder and any former
  archive as they were and raises `ArchiveCheckError`; a folder holding files that are not its sequence's is refused
  before writing (it would not be removed whole), and so is an archive inside the folder. `encoding3d pack ...
  [--keep-folder]` (exit 1 when the check fails). The conformance run and ParaView's check keep their folders.
- **The validator on archives:** `validate_sequence` takes a sequence's `.fspm.zip` (or its folder) as `validate_file`
  does: its parts are found in the archive (they were reported missing when the archive itself was given).
- **Ids across frames on an adaptive grid** (specification §8): a leaf cell is the region its `level` and `index`
  give, so a cell coarsened away and refined again is the same entity and MAY have its id again; an id that comes back
  MUST have the same `level` and `index`. The validator checks that instead of refusing any id that comes back on an
  adaptive grid's cells (metafspm's adaptive soil, whose ids are a cell's level and corner, gave 3 errors on use case
  1's frames; none now).

- Specification 0.4 (§12, all additions: a 0.3 file is a valid 0.4 file): **instance sets** (a data structure's
  `instanceSets`: one row per instance, its template, transform, owner and own variables; vectors, one array per
  instance), **linear derived fields** (f = Σ_k w_k · (A_k · v + b_k) on a template's entity set: one or several
  weighted terms, offsets; operators `dense`, `csr`, or `solve`, a sparse system solved when evaluated), **shared
  parts** (a template or an operator as a GLB file of its own, `FSPM_scene.part`, keyed by the SHA-256 of its bytes,
  embedded in a frame, `FSPM_scene.parts`, or at `parts/<key>.glb`, listed in the index's `parts`); §8: the folder's
  layout; §8.2: a sequence packed into a `.fspm.zip` archive (ZIP64, each member compressed alone: stored, deflate,
  lzma); §8.1: views' `instances` layers. Platform-neutral: any model's entities of a declared shape and linear
  recovery.
- Python: `Template`, `Operator` (`dense`, `sparse`, `solve`, `of_system`), `InstanceSet`, `DerivedField`, `Ragged`,
  `column_major`; `evaluate(frame, field, instances=)` (one matrix product per operator; scipy when installed, numpy
  otherwise), `placed_meshes`, `Frame.part`; `write(path, frame, embed_parts=)` writing each part once and returning
  the frame's keys, `write_parts`, `write_index(parts=)`, `prune_parts`; `pack`, `unpack`; `read`, `read_index`,
  `read_sequence`, the validator and views reading a `.fspm.zip` like its folder (`run.fspm.zip/frame_000003.glb`);
  `MissingPartError` naming the key. The validator checks every reference (parts present, valid, hashing to their
  keys; templates, owners, operators' shapes, offsets). `encoding3d pack`, `unpack`, `prune`; `validate` and `info`
  on instances and archives. Deflate is the default compression (measured on use case 1's frames: 11.6 % of the size
  at 79 MB/s, lzma 4.1 % at 17 MB/s).
- The conformance case `instances/` (a sequence, its parts and their expected values, the evaluated fields, a frame
  with its parts embedded), and `archives/`: that sequence packed stored, deflate, lzma, and with every ZIP64 record
  (rewritten by `generate.py` only when their members change). `encoding3d compare-all` checks every codec's dumps of
  them (frames, evaluated derived fields within a relative 1e-12, parts, each archive's frames; `--skip-instances` for
  a codec reading 0.3 only, the action's `instances: "false"`), and the action validates written archives. The
  conformance files say 0.4 (their expected values unchanged).
- The C++, Java and Julia codecs on 0.4: instance sets, vectors and derived fields read and written; shared parts
  (templates, operators) encoded, keyed by SHA-256, embedded or under `parts/`, found through the frame (a missing
  part an error naming its key); derived fields evaluated (dense, `csr`, `solve`); the index's `parts`; `.fspm.zip`
  archives read (ZIP64; stored, deflate, lzma) and packed. Their conformance runs dump the instances and archives, and
  write the instances again with parts they encode themselves (sequence, index, archive). Dependencies: C++
  minizip-ng (found or fetched; zlib, liblzma); Java xz-java (lzma; the rest `java.util.zip`); Julia ZipArchives.jl
  and XZ_jll (liblzma's raw decoder), with SHA, SparseArrays, LinearAlgebra and Mmap. Java and Julia pack stored or
  deflate (lzma read only), C++ all three.
- ParaView: instance sets drawn as their placed templates (their own variables, their owners' and the ids containing
  them, their templates' constants), `instances` layers, `.fspm.zip` archives opened as folders; **encoding3d Select at
  scale** rebuilds the derived fields of the instances it selects (Isolate, Show In Panel, Put Back unchanged); the
  reader's **Evaluate Derived Fields** for all; `check_in_paraview.py --instances`, by hand.
- Docs: Instances, derived fields and archives (reading, packing, how a platform writes them: a reduced network's
  eliminated nodes, a coarse cell's linear recovery); tutorial 1's sections 5 (instances) and 6 (an archive).
- ParaView on large frames (2026-11-09): a hidden instances layer (metafspm's sections) is an empty block, its
  instances placed by **encoding3d Select at scale** for the entities it selects only (**Expand Hidden Instances** on
  the reader draws them all); an instances block holds the ids, the instance and template rows and the layers' colour
  variables only, one value per triangle (**All Instance Arrays** for every variable), its arrays handed to VTK
  without copies; the reader and the filter share one read of a frame (`open_frame`, the last two kept) and the
  derived fields rebuilt per open frame. Use case 1 (2 plants, 25 days, pvbatch peak RSS): the frame of day 16 opens
  in 0.87 GB (was 5.69), day 23 in 1.92 GB (was killed at 8 GB; 1 GB of it the frame's JSON, written compactly by
  metafspm since), a root segment selected with its section in 0.72–2.0 GB at any day, its axis in 1.2–4.3 GB.
  `placed_meshes`' `mesh` is the mesh's index in its template (was its name, an object array), its positions placed
  without a 4-component temporary.
- encoding3d Select at scale: its Scale's default is **picked**, the picked cells' own scale (`views.PICKED_SCALE`,
  `views.picked_scale`), so that Isolate and Show In Panel work before any Apply; the buttons work on the Scale applied
  (said in its documentation and the how-to); Show In Panel hides the selection that Apply drew in the view, and Put
  Back shows it again; the filter's `<Visibility replace_input="0"/>` hint (was an unknown `<ReplaceInput>`): Apply
  leaves the reader shown. A time step at which the selection holds no instance is said once per time step, with the
  plants that have some (`missing_instances`: `display_plants`, `display_period`); a derived field that cannot be
  rebuilt is an error (was a warning). `grow_entities`, `instance_rows_at`.
- The plugin colours a layer's representation by an array its data holds only (`views.block_displays`' `main_array`
  among the arrays present, `arrays=None` when not known): no "Could not determine array range" for a selection without
  the shoot; drawn again when the arrays present change between time steps.
- Docs: `doc/python.md`'s recorder example (`frame_period="1 d"`, was 24 steps), metafspm writing 0.4 in
  `implementations.md`, which also says that only metafspm reads its extras (their `absent_rows`, `none_rows`).

## Unreleased: frame views (specification §8.1, draft for 0.3)

- Views, an optional companion of a sequence (`views.json`, `spec/schema/views.schema.json`): named configurations
  of layers, each a mesh's, segments' or grid's entities selected by `where` conditions, coloured by a variable (or a
  solid colour), with a colour map, range, log scale, opacity, visibility, representation, and tubes for segments.
- `openalea.encoding3d.views`: reading, writing and checking views (the schema, and every name against a frame), the
  selection, and the display options ParaView's plugin draws and saves back (`block_displays`,
  `displays_from_blocks`, `layer_from_display`).
- The ParaView reader's **Time Unit** (`d` by default, `h`, `min`, `s`): the times ParaView shows, converted from the
  frames' own unit; the files are unchanged.
- The ParaView plugin is one file, `paraview/plugin_encoding3d.py` (was `encoding3d_reader.py`), with a how-to,
  `paraview/README.md`; no macros (`apply_encoding3d_views.py`, `save_encoding3d_views.py` and
  `show_encoding3d_selection.py` removed, their work in the plugin).
- The ParaView reader: "Views" and "Configuration" (a drop-down), one block per layer holding only its entities, a
  segments layer with a `tube` as tubes (one closed strip per segment); `frame_to_vtk(frame, views=, configuration=)`,
  unchanged without views. The plugin draws each layer as its block when ParaView shows the reader (Apply), with its
  own colour variable, colour map, range, log scale or solid colour, opacity and visibility (the representation's
  block properties, editable in the MultiBlock Inspector), drawn again when the Configuration or the views file
  changes; the reader's "Save Views" button (and "Save As") writes the display back into `views.json`.
- Selection by scale in ParaView: the plugin's filter "encoding3d Select at scale" (Filters → encoding3d) takes ParaView's
  selection and grows the picked cells to their entity at its **Scale** (a drop-down of the frames' scales) with
  everything it contains, in every layer of the reader, hidden ones included, following the picked entities through
  the time steps, drawn as the layers; its buttons Isolate (the other items hidden), Show In Panel (a view of its
  own) and Put Back (one step back), one selection over another. Each cell carries the ids of the entities
  containing it (`<scale>.id`), each block its data structure and scales.

## Unreleased: specification 0.3 (draft), coupling platforms

- Lazy reading (`read(path, lazy=True)`): the file mapped in memory, its JSON parsed, each column and mesh decoded on
  first access (`LazyColumns`, `LazyList`), `frame.close()` or a `with` block; used by the ParaView reader and by
  replays (only the columns links use).
- The folder transport deletes each message once read, unless the session keeps them (`keepMessages`,
  `--keep-messages`); every participant (Python, Julia, C++, Java) applies it, and the conformance sessions check
  that the folder is left empty.

- Specification 0.3: the frames say 0.3 (0.1 and 0.2 files stay valid); "Changes from 0.2"; the conformance files
  regenerated (their expected values unchanged).
- Links between two data structures, through a mapping a participant provides (declared, sent in its updates):
  `sum` shares each source's amount among its targets by weight, `mean` gives each target its sources' weighted mean;
  replayed sequences provide their mappings; a replay declares every entity set and variable of its frames.
- Coupling conformance sessions (`conformance/coupling/`, written by its `generate.py`), `encoding3d couple-conformance`,
  and a participant's program in each codec; partial frames (`update`) in every codec's dump.
- The C++ participant (`encoding3d/coupling.hpp`; ZeroMQ with libzmq) and the Java one (`org.openalea.encoding3d.coupling`;
  ZeroMQ with JeroMQ, optional); partial frames in both codecs.
- CPlantBox's and GroIMP's logs (the adapter's tests, the plugin's headless run) replayed in coupling sessions.
- The coordinator's lookups by id vectorized, and the Python codec's enum and text columns encoded without per-row
  loops: a step of 100,000 segments takes 99 ms instead of 230 ms.

- Coupling sessions: platforms' models run together, each in its own process, through encoding3d. Partial frames
  (`FSPM_scene.update`: the sender, removed entities); the messages (`spec/schema/coupling.schema.json`): a
  participant's declaration (its entity sets and rights, `owns`, `refines`, `follows`; its outputs and inputs), links
  (factors, units, a change of scale), turns and updates; stages; one shared structure with id ranges and removals
  down the scales; two transports, ZeroMQ and a folder of messages; a recorded sequence as a participant (replay,
  held or interpolated linearly).
- The reference coordinator and participant (`openalea.encoding3d.coupling`, `encoding3d couple`), unit conversion factors
  (`ucum.conversion_factor`); encoding3d.jl's participant (`Participant`, `turns`, `send_update`; ZeroMQ through the
  `encoding3dZMQExt` extension), tested against the coordinator over both transports.
- The Python codec refuses enum columns (labels) with missing values instead of writing an unnamed enum value.

## Unreleased: specification 0.2 (draft)

- Specification 0.2, additive (0.1 files stay valid), from the bindings' points (`spec/specification.md`, "Changes
  from 0.1"): missing values in integer, text and boolean columns; an entity set's `scale` and ranks as base scale
  positions; reading by content; position columns in their declared unit; a data structure's `labels`; the extras
  key; `edge_type` `unknown`; the `sibling_order` column; parents in another complex; bearer relations' labels and names;
  dates (`format`); sparse ids; the conformance files' status and the sources' precedence.
- Vocabulary 0.2: `Seed`, `mtg_index`, the new enumerations.
- The reference codec, the validator, the ParaView reader and the conformance files (a new scene, `missing_values`).
- The Julia, C++ and Java codecs on 0.2, and their adapters using it instead of their extras: MTG.jl (missing
  attributes, dates, children's order, `mtg_index`), PlantGraphs (`unknown` edges, children's order), CPlantBox (a
  `mixed` Organ set, segment ends in cm), GroIMP (missing fields, scales, labels); extras keys in
  lower case (`virtualplantlab`, `cplantbox`, `groimp`).

## Specification 0.1 (draft)

- The specification (`spec/specification.md`), its JSON Schemas and the first vocabulary (41 standard names, the
  labels with their Plant Ontology terms, the enumerations, a column of names per platform).
- `openalea.encoding3d`, the Python reference codec (`bindings/python/`): reading and writing frames and sequences, the
  validator, display copies, the comparison with expected values, the `encoding3d` command line.
- The conformance files (`conformance/`), their expected values, and the GitHub action checking a codec against them.
- The ParaView reader plugin (`paraview/`).
- encoding3d.jl, the Julia codec (`bindings/julia/encoding3d/`): conformant reading and writing, sequences, and a
  MultiScaleTreeGraph.jl package extension (`from_mtg`, `to_mtg`); its CI, `.github/workflows/julia-codec.yml`.
- The C++ codec (`bindings/cpp/`): conformant reading and writing, sequences, a CMake package; CPlantBox's adapter
  (`bindings/cpp/cplantbox/`: organisms with their geometry, soil grid and mapping; static root systems from any graph
  with segment ends); its CI, `.github/workflows/cpp-codec.yml`.
- The Java codec (`bindings/java/`): conformant reading and writing, sequences; GroIMP's adapter (`bindings/java/groimp/`:
  scales from refinement edges, topology, edge bits as relations, managed fields; graphs back into the model's node
  classes); its CI, `.github/workflows/java-codec.yml`.
- GroIMP's plugin (`bindings/java/groimp-plugin/`): the 3D view exported as an encoding3d frame from GroIMP 3.0 (File >
  Export, CLI `export3d`), its geometry meshed by GroIMP's glTF plugin, each triangle with its node; tested headless in
  GroIMP 3.0.0 in CI.
- encoding3d.jl: VirtualPlantLab's graphs (PlantGraphs: `from_graph`, `to_graph`) and their turtle geometry
  (PlantGeomTurtle: `add_geometry!`), as package extensions.
- encoding3d.jl: MTGs from graphs with ids from 0 or sparse (numbered 1, 2, ..., ids kept in `encoding3d_id`), and parents
  in another complex kept (`encoding3d_parent`).
- The documentation (`doc/`), with a notebook; the design note (`doc/design_note.md`).
