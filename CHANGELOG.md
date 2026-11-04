# Changelog

## Unreleased: frame views (specification §8.1, draft for 0.3)

- Views, an optional companion of a sequence (`views.json`, `spec/schema/views.schema.json`): named configurations
  of layers, each a mesh's, segments' or grid's entities selected by `where` conditions, coloured by a variable (or a
  solid colour), with a colour map, range, log scale, opacity, visibility, representation, and tubes for segments.
- `openalea.encoding3d.views`: reading, writing and checking views (the schema, and every name against a frame), the
  selection, and the display options ParaView's plugin draws and saves back (`block_displays`,
  `displays_from_blocks`, `layer_from_display`).
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
