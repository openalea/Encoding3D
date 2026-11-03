# Changelog

## Unreleased: frame views (specification §8.1, draft for 0.3)

- Views, an optional companion of a sequence (`views.json`, `spec/schema/views.schema.json`): named configurations
  of layers, each a mesh's, segments' or grid's entities selected by `where` conditions, coloured by a variable (or a
  solid colour), with a colour map, range, log scale, opacity, visibility, representation, and tubes for segments.
- `openalea.fspm_tf.views`: reading, writing and checking views (the schema, and every name against a frame), the
  selection, and the display options the ParaView macros apply and save back.
- The ParaView reader: "Views" and "Configuration" (a drop-down), one block per layer holding only its entities;
  `frame_to_vtk(frame, views=, configuration=)`, unchanged without views. The macros `apply_fspm_tf_views.py` (each
  layer its own pipeline item) and `save_fspm_tf_views.py` (the items' display options back into `views.json`).
- Selection by scale in ParaView: the plugin's filter "fspm-TF Select at scale" (Filters → fspm-TF) takes ParaView's
  selection and grows the picked cells to their entity at its **Scale** (a drop-down of the frames' scales) with
  everything it contains, in every layer of the reader, hidden ones included, following the picked entities through
  the time steps; the macro `show_fspm_tf_selection.py` shows it as its layers, isolated in the view or in a panel of
  its own, one selection over another, run again to go back. Each cell carries the ids of the entities containing it
  (`<scale>.id`), each block its data structure and scales.

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
- Coupling conformance sessions (`conformance/coupling/`, written by its `generate.py`), `fspm-tf couple-conformance`,
  and a participant's program in each codec; partial frames (`update`) in every codec's dump.
- The C++ participant (`fspm_tf/coupling.hpp`; ZeroMQ with libzmq) and the Java one (`org.openalea.fspmtf.coupling`;
  ZeroMQ with JeroMQ, optional); partial frames in both codecs.
- CPlantBox's and GroIMP's logs (the adapter's tests, the plugin's headless run) replayed in coupling sessions.
- The coordinator's lookups by id vectorized, and the Python codec's enum and text columns encoded without per-row
  loops: a step of 100,000 segments takes 99 ms instead of 230 ms.

- Coupling sessions: platforms' models run together, each in its own process, through fspm-TF. Partial frames
  (`FSPM_scene.update`: the sender, removed entities); the messages (`spec/schema/coupling.schema.json`): a
  participant's declaration (its entity sets and rights, `owns`, `refines`, `follows`; its outputs and inputs), links
  (factors, units, a change of scale), turns and updates; stages; one shared structure with id ranges and removals
  down the scales; two transports, ZeroMQ and a folder of messages; a recorded sequence as a participant (replay,
  held or interpolated linearly).
- The reference coordinator and participant (`openalea.fspm_tf.coupling`, `fspm-tf couple`), unit conversion factors
  (`ucum.conversion_factor`); FspmTF.jl's participant (`Participant`, `turns`, `send_update`; ZeroMQ through the
  `FspmTFZMQExt` extension), tested against the coordinator over both transports.
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
- `openalea.fspm_tf`, the Python reference codec (`bindings/python/`): reading and writing frames and sequences, the
  validator, display copies, the comparison with expected values, the `fspm-tf` command line.
- The conformance files (`conformance/`), their expected values, and the GitHub action checking a codec against them.
- The ParaView reader plugin (`paraview/`).
- FspmTF.jl, the Julia codec (`bindings/julia/FspmTF/`): conformant reading and writing, sequences, and a
  MultiScaleTreeGraph.jl package extension (`from_mtg`, `to_mtg`); its CI, `.github/workflows/julia-codec.yml`.
- The C++ codec (`bindings/cpp/`): conformant reading and writing, sequences, a CMake package; CPlantBox's adapter
  (`bindings/cpp/cplantbox/`: organisms with their geometry, soil grid and mapping; static root systems from any graph
  with segment ends); its CI, `.github/workflows/cpp-codec.yml`.
- The Java codec (`bindings/java/`): conformant reading and writing, sequences; GroIMP's adapter (`bindings/java/groimp/`:
  scales from refinement edges, topology, edge bits as relations, managed fields; graphs back into the model's node
  classes); its CI, `.github/workflows/java-codec.yml`.
- GroIMP's plugin (`bindings/java/groimp-plugin/`): the 3D view exported as an fspm-TF frame from GroIMP 3.0 (File >
  Export, CLI `export3d`), its geometry meshed by GroIMP's glTF plugin, each triangle with its node; tested headless in
  GroIMP 3.0.0 in CI.
- FspmTF.jl: VirtualPlantLab's graphs (PlantGraphs: `from_graph`, `to_graph`) and their turtle geometry
  (PlantGeomTurtle: `add_geometry!`), as package extensions.
- FspmTF.jl: MTGs from graphs with ids from 0 or sparse (numbered 1, 2, ..., ids kept in `fspm_tf_id`), and parents
  in another complex kept (`fspm_tf_parent`).
- The documentation (`doc/`), with a notebook; the design note (`doc/design_note.md`).
