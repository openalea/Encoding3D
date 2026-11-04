# encoding3d.jl

The Julia codec of encoding3d: reading and writing frames and sequences (spec 0.3), and, as a package extension, a
MultiScaleTreeGraph.jl MTG to and from a `graph` data structure (`from_mtg`, `to_mtg`).

- `encoding3d/src/`: the GLB container (`glb.jl`), the data model (`model.jl`), reading and writing (`codec.jl`),
  sequences (`sequence.jl`), the conformance dump (`dump.jl`).
- `encoding3d/ext/encoding3dMultiScaleTreeGraphExt.jl`: the MTG adapter, loaded with MultiScaleTreeGraph (PlantSimEngine's,
  PlantGeom's graphs).
- `encoding3d/ext/encoding3dPlantGraphsExt.jl`, `encoding3dPlantGeomTurtleExt.jl`: VirtualPlantLab's graphs and their turtle
  geometry, loaded with PlantGraphs (and PlantGeomTurtle, PlantGeomPrimitives).
- `encoding3d/test/`: the tests, the conformance files included; `test/plantgraphs/`: VirtualPlantLab's (Julia ≥ 1.12).
- `conformance_run.jl`: the codec's dumps of the conformance files and its written scenes, for
  `.github/actions/conformance`.

Dependencies: JSON.jl and OrderedCollections.jl. Licence: MIT (`encoding3d/LICENSE`), as VirtualPlantLab; the rest of
encoding3d is CeCILL-C. See [the documentation](../../doc/julia.md).
