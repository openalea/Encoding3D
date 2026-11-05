# Tutorials

Step by step, from encoding3d on its own to four platforms running one plant together. Each tutorial is a folder with
its explanation (`README.md`), its code, and `run.sh`, which runs it from start to end.

| Tutorial | What it shows | What it needs |
|---|---|---|
| `01_encoding3d_alone` | writing, checking, reading and viewing a growing root system's files, with no platform | Python, `openalea.encoding3d` |
| `02a_metafspm` | a metafspm scene recorded as frames, read by encoding3d alone, logged smaller, rebuilt in metafspm | metafspm's environment |
| `02b_virtualplantlab` | a VirtualPlantLab plant grown by rules, written with its geometry, rebuilt and grown on; an MTG to and from encoding3d | Julia 1.12, VirtualPlantLab's packages, MTG.jl |
| `02c_cplantbox` | a CPlantBox plant written day by day with its geometry, soil grid and mapping; frames back as CPlantBox root systems | C++17, CMake, CPlantBox built |
| `02d_groimp` | a GroIMP graph written step by step and rebuilt as GroIMP nodes; GroIMP's plugin exporting a project with its geometry | Java 21, Maven (GroIMP's Graph module) |

**encoding3d depends on no platform.** Tutorial 1 needs encoding3d only, and encoding3d's CI runs it. The tutorials
using a platform (metafspm, VirtualPlantLab, CPlantBox, GroIMP) list what they need in their own folder, outside
encoding3d's requirements, and are run by hand.
