# Implementations

| Platform | Language | Where | Reads | Writes | Specification version |
|---|---|---|---|---|---|
| openalea.fspm_tf (reference codec) | Python | this repository, `bindings/python/` | yes | yes | 0.3 |
| openalea.metafspm | Python | `openalea.metafspm.io.fspm_tf` (branch release2026) | yes: its own frames, rebuilt bit for bit | yes | 0.3 (through openalea.fspm_tf) |
| fspm_tf (C++ codec) | C++ | this repository, `bindings/cpp/` | yes | yes | 0.3 |
| CPlantBox | C++ | `bindings/cpp/cplantbox/` (`fspm_tf::cplantbox`), to move into CPlantBox | yes: static root systems, from any graph with segment ends | yes: organs, segments, geometry, soil grid, mapping | 0.3 |
| fspm-tf (Java codec) | Java | this repository, `bindings/java/` | yes | yes | 0.3 |
| GroIMP | Java | `bindings/java/groimp/` (`GroImp`) and `bindings/java/groimp-plugin/` (a GroIMP 3.0 plugin: File > Export to `.glb`, CLI `export3d`) | yes: graphs and fields into the model's node classes (adapter) | yes: scales, topology, edge bits, managed fields, the scene's geometry by node | 0.3 |
| FspmTF.jl (Julia codec) | Julia | this repository, `bindings/julia/FspmTF/` | yes | yes | 0.3 |
| MultiScaleTreeGraph.jl (VirtualPlantLab, PlantSimEngine) | Julia | FspmTF.jl's package extension: `from_mtg`, `to_mtg` | yes: any graph as an MTG; its own MTGs rebuilt as they were | yes | 0.3 |
| VirtualPlantLab (PlantGraphs, PlantGeomTurtle) | Julia | FspmTF.jl's package extensions: `from_graph`, `to_graph`, `add_geometry!` | yes: nodes rebuilt from their fields | yes: nodes, fields, turtle geometry | 0.3 |

Coupling sessions (specification §11): the Python package holds the coordinator and a participant; FspmTF.jl, the C++
and the Java codecs a participant each. All four pass the coupling conformance sessions over both transports (ZeroMQ:
pyzmq, ZMQ.jl, libzmq, JeroMQ). metafspm's `RemoteComponent` (`openalea.metafspm.io.coupling`) stands for another
platform's model in a metafspm model, tested with a VirtualPlantLab model (PlantGraphs). CPlantBox's and GroIMP's logs
are replayed as participants in their CI jobs.

Codecs (a language's reading and writing of the format) live in this repository, in `bindings/<language>/`; adapters
(a platform's model to and from the codec's tables) in the platforms' repositories, or as a codec's optional
extension when the platform's library is a plain dependency (Julia's package extensions). An implementation is listed with
the version it passes: it reads every conformance file as expected, and writes
files that the validator accepts (specification, §9).
