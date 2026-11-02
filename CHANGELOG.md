# Changelog

## Unreleased: specification 0.1 (draft)

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
- FspmTF.jl: VirtualPlantLab's graphs (PlantGraphs: `from_graph`, `to_graph`) and their turtle geometry
  (PlantGeomTurtle: `add_geometry!`), as package extensions.
- FspmTF.jl: MTGs from graphs with ids from 0 or sparse (numbered 1, 2, ..., ids kept in `fspm_tf_id`), and parents
  in another complex kept (`fspm_tf_parent`).
- The documentation (`doc/`), with a notebook; the design note (`doc/design_note.md`).
