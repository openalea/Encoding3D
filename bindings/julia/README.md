# encoding3d.jl

The Julia codec of encoding3d: reading and writing frames and sequences (spec 0.4: instance sets, derived fields
evaluated, shared parts, `.fspm.zip` archives read and packed), a coupling session's participant,
and, as package extensions proposed to their platforms, MultiScaleTreeGraph.jl MTGs and VirtualPlantLab graphs to and
from `graph` data structures.

- `encoding3d/src/`: the GLB container (`glb.jl`), the data model (`model.jl`, instance sets and parts included),
  reading and writing (`codec.jl`), shared parts and derived fields (`parts.jl`), archives (`archive.jl`), sequences
  (`sequence.jl`), the conformance dump (`dump.jl`).
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

Dependencies: JSON.jl and OrderedCollections.jl; ZipArchives.jl (the archives: their ZIP64 records, stored and deflate
members, packing) and XZ_jll (liblzma, whose raw LZMA1 decoder reads lzma members, ZIP's method 14: no Julia package
reads ZIP's lzma, CodecXz only the .xz format); the standard libraries SHA (the parts' keys), SparseArrays and
LinearAlgebra (operators; a `solve` operator by sparse LU), Mmap (an archive mapped, not read whole). Archives are
packed stored or deflate; lzma ones are read only. Licence: MIT (`encoding3d/LICENSE`), as VirtualPlantLab; the rest of
encoding3d is CeCILL-C. See [the documentation](../../doc/julia.md).
