# Tutorials

Step by step, from encoding3d on its own to four platforms running one plant together. Each tutorial is a folder with
its explanation (`README.md`), its code, and `run.sh`, which runs it from start to end.

| Tutorial | What it shows | What it needs |
|---|---|---|
| `01_encoding3d_alone` | writing, checking, reading and viewing a growing root system's files, with no platform | Python, `openalea.encoding3d` |

**encoding3d depends on no platform.** Tutorial 1 needs encoding3d only, and encoding3d's CI runs it. The tutorials
using a platform (metafspm, VirtualPlantLab, CPlantBox, GroIMP) list what they need in their own folder, outside
encoding3d's requirements, and are run by hand.
