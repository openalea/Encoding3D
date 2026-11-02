# Implementations

| Platform | Language | Where | Reads | Writes | Specification version |
|---|---|---|---|---|---|
| openalea.fspm_tf (reference codec) | Python | this repository, `bindings/python/` | yes | yes | 0.1 |
| openalea.metafspm | Python | `openalea.metafspm.io.fspm_tf` (branch release2026) | yes: its own frames, rebuilt bit for bit | yes | 0.1 |
| CPlantBox | C++ / Python | planned (phase P4) | | | |
| GroIMP | Java | | | | |
| FspmTF.jl (Julia codec) | Julia | this repository, `bindings/julia/FspmTF/` | yes | yes | 0.1 |
| MultiScaleTreeGraph.jl (VirtualPlantLab, PlantSimEngine) | Julia | FspmTF.jl's package extension: `from_mtg`, `to_mtg` | yes: any graph as an MTG; its own MTGs rebuilt as they were | yes | 0.1 |
| VirtualPlantLab (PlantGraphs) | Julia | planned (FspmTF.jl extensions: PlantGeom meshes, PlantGraphs) | | | |

Codecs (a language's reading and writing of the format) live in this repository, in `bindings/<language>/`; adapters
(a platform's model to and from the codec's tables) in the platforms' repositories, or as a codec's optional
extension when the platform's library is a plain dependency (Julia's package extensions). An implementation is listed with
the version it passes: it reads every conformance file as expected, and writes
files that the validator accepts (specification, §9).
