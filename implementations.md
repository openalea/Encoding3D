# Implementations

| Platform | Language | Where | Reads | Writes | Specification version |
|---|---|---|---|---|---|
| openalea.encoding3d (reference codec) | Python | this repository, `bindings/python/` | yes | yes | 0.4 |
| openalea.metafspm | Python | `openalea.metafspm.io.encoding3d` (branch release2026) | yes: its own frames, rebuilt bit for bit | yes | 0.4 (through openalea.encoding3d) |
| encoding3d (C++ codec) | C++ | this repository, `bindings/cpp/` | yes | yes | 0.4 |
| CPlantBox | C++ | `bindings/cpp/cplantbox/` (`encoding3d::cplantbox`), to move into CPlantBox | yes: static root systems, from any graph with segment ends | yes: organs, segments, geometry, soil grid, mapping | 0.3 |
| encoding3d (Java codec) | Java | this repository, `bindings/java/` | yes | yes | 0.4 |
| GroIMP | Java | `bindings/java/groimp/` (`GroImp`) and `bindings/java/groimp-plugin/` (a GroIMP 3.0 plugin: File > Export to `.glb`, CLI `export3d`) | yes: graphs and fields into the model's node classes (adapter) | yes: scales, topology, edge bits, managed fields, the scene's geometry by node | 0.3 |
| encoding3d.jl (Julia codec) | Julia | this repository, `bindings/julia/encoding3d/` | yes | yes | 0.4 |
| MultiScaleTreeGraph.jl (VirtualPlantLab, PlantSimEngine) | Julia | encoding3d.jl's package extension: `from_mtg`, `to_mtg` | yes: any graph as an MTG; its own MTGs rebuilt as they were | yes | 0.3 |
| VirtualPlantLab (PlantGraphs, PlantGeomTurtle) | Julia | encoding3d.jl's package extensions: `from_graph`, `to_graph`, `add_geometry!` | yes: nodes rebuilt from their fields | yes: nodes, fields, turtle geometry | 0.3 |

0.4's instances, derived fields, shared parts and archives (specification §12, §8.2), per codec: all four read and
write instance sets and their parts (embedded, or `parts/<key>.glb`), evaluate derived fields (dense, `csr` and `solve`
operators), read `.fspm.zip` archives (ZIP64; stored, deflate and lzma members) and pass the conformance cases
`instances/` and `archives/`. They pack archives with: Python, stored, deflate or lzma (`zipfile`); C++, stored,
deflate or lzma (minizip-ng); Java, stored or deflate (`java.util.zip`; lzma read with xz-java); Julia, stored or
deflate (ZipArchives.jl; lzma read with liblzma). Python alone draws instances (`placed_meshes`, ParaView) and prunes
parts. The platform adapters write no instance sets yet (0.3 content).

A data structure's `extras` (specification §3) are the writing platform's own, which other readers do not need and
keep as JSON. metafspm's (`extras.metafspm`) hold what it rebuilds its MPG from: since 2026-11-09 its properties'
missing values as row ranges (`absent_rows`, `none_rows`: flat `[start, stop, ...]` lists of half-open ranges over the
scale's rows, about 60 times smaller than the former vid lists on use case 1's last frame). Only metafspm reads them:
the Python, C++, Java and Julia codecs, the validator, ParaView and the conformance cases do not, so the specification
and the conformance files are unchanged.

Coupling sessions (specification §11): the Python package holds the coordinator and a participant; encoding3d.jl, the C++
and the Java codecs a participant each. All four pass the coupling conformance sessions over both transports (ZeroMQ:
pyzmq, ZMQ.jl, libzmq, JeroMQ). metafspm's `RemoteComponent` (`openalea.metafspm.io.coupling`) stands for another
platform's model in a metafspm model, tested with a VirtualPlantLab model (PlantGraphs). CPlantBox's and GroIMP's logs
are replayed as participants when their adapters are tested by hand.

The platform adapters kept in this repository (CPlantBox's, GroIMP's adapter and plugin, the MTG.jl and VirtualPlantLab
extensions) are **first proposals for those platforms' teams**: they move into the platforms once adopted. encoding3d's
requirements and CI do not depend on any platform; each adapter's README says how to build and test it by hand.

Codecs (a language's reading and writing of the format) live in this repository, in `bindings/<language>/`; adapters
(a platform's model to and from the codec's tables) in the platforms' repositories, or as a codec's optional
extension when the platform's library is a plain dependency (Julia's package extensions). An implementation is listed with
the version it passes: it reads every conformance file as expected, and writes
files that the validator accepts (specification, §9).
