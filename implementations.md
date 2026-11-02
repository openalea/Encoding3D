# Implementations

| Platform | Language | Where | Reads | Writes | Specification version |
|---|---|---|---|---|---|
| openalea.fspm_tf (reference codec) | Python | this repository, `bindings/python/` | yes | yes | 0.2 |
| openalea.metafspm | Python | `openalea.metafspm.io.fspm_tf` (branch release2026) | yes: its own frames, rebuilt bit for bit | yes | 0.2 (through openalea.fspm_tf) |
| fspm_tf (C++ codec) | C++ | this repository, `bindings/cpp/` | yes | yes | 0.2 |
| CPlantBox | C++ | `bindings/cpp/cplantbox/` (`fspm_tf::cplantbox`), to move into CPlantBox | yes: static root systems, from any graph with segment ends | yes: organs, segments, geometry, soil grid, mapping | 0.2 |
| fspm-tf (Java codec) | Java | this repository, `bindings/java/` | yes | yes | 0.1 |
| GroIMP | Java | `bindings/java/groimp/` (`GroImp`), to become a GroIMP plugin | yes: graphs and fields into the model's node classes | yes: scales, topology, edge bits, managed fields | 0.1 |
| FspmTF.jl (Julia codec) | Julia | this repository, `bindings/julia/FspmTF/` | yes | yes | 0.2 |
| MultiScaleTreeGraph.jl (VirtualPlantLab, PlantSimEngine) | Julia | FspmTF.jl's package extension: `from_mtg`, `to_mtg` | yes: any graph as an MTG; its own MTGs rebuilt as they were | yes | 0.2 |
| VirtualPlantLab (PlantGraphs, PlantGeomTurtle) | Julia | FspmTF.jl's package extensions: `from_graph`, `to_graph`, `add_geometry!` | yes: nodes rebuilt from their fields | yes: nodes, fields, turtle geometry | 0.2 |

Codecs (a language's reading and writing of the format) live in this repository, in `bindings/<language>/`; adapters
(a platform's model to and from the codec's tables) in the platforms' repositories, or as a codec's optional
extension when the platform's library is a plain dependency (Julia's package extensions). An implementation is listed with
the version it passes: it reads every conformance file as expected, and writes
files that the validator accepts (specification, §9).
