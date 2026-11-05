# encoding3d.jl

The Julia codec of encoding3d: reading and writing frames and sequences (spec 0.3), a coupling session's participant,
and, as package extensions proposed to their platforms, MultiScaleTreeGraph.jl MTGs and VirtualPlantLab graphs to and
from `graph` data structures.

- `encoding3d/src/`: the GLB container (`glb.jl`), the data model (`model.jl`), reading and writing (`codec.jl`),
  sequences (`sequence.jl`), the conformance dump (`dump.jl`).
- `encoding3d/ext/encoding3dMultiScaleTreeGraphExt.jl`: the MTG adapter, loaded with MultiScaleTreeGraph (PlantSimEngine's,
  PlantGeom's graphs).
- `encoding3d/ext/encoding3dPlantGraphsExt.jl`, `encoding3dPlantGeomTurtleExt.jl`: VirtualPlantLab's graphs and their turtle
  geometry, loaded with PlantGraphs (and PlantGeomTurtle, PlantGeomPrimitives).
- `encoding3d/test/`: the tests, the conformance files included, depending on no platform.
- `ext/encoding3dZMQExt.jl`: the coupling's ZeroMQ transport, loaded with ZMQ.

## The platform extensions: proposals

The MTG.jl and VirtualPlantLab extensions are **first proposals for those platforms' teams to take over**. They load
only when the platform's package is loaded (weak dependencies), so encoding3d's requirements do not include them, and
encoding3d's CI does not run their tests. To test them by hand, from the repository's root:

```bash
julia --project=bindings/julia/encoding3d/test/multiscaletreegraph -e 'using Pkg; Pkg.develop(path="bindings/julia/encoding3d"); Pkg.instantiate()'
julia --project=bindings/julia/encoding3d/test/multiscaletreegraph bindings/julia/encoding3d/test/multiscaletreegraph/runtests.jl
julia --project=bindings/julia/encoding3d/test/plantgraphs -e 'using Pkg; Pkg.develop(path="bindings/julia/encoding3d"); Pkg.instantiate()'
julia --project=bindings/julia/encoding3d/test/plantgraphs bindings/julia/encoding3d/test/plantgraphs/runtests.jl      # Julia ≥ 1.12
```
- `conformance_run.jl`: the codec's dumps of the conformance files and its written scenes, for
  `.github/actions/conformance`.

Dependencies: JSON.jl and OrderedCollections.jl. Licence: MIT (`encoding3d/LICENSE`), as VirtualPlantLab; the rest of
encoding3d is CeCILL-C. See [the documentation](../../doc/julia.md).
