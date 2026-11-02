# FspmTF.jl

The Julia codec of fspm-TF: reading and writing frames and sequences (spec 0.1), and, as a package extension, a
MultiScaleTreeGraph.jl MTG to and from a `graph` data structure (`from_mtg`, `to_mtg`).

- `FspmTF/src/`: the GLB container (`glb.jl`), the data model (`model.jl`), reading and writing (`codec.jl`),
  sequences (`sequence.jl`), the conformance dump (`dump.jl`).
- `FspmTF/ext/FspmTFMultiScaleTreeGraphExt.jl`: the MTG adapter, loaded with MultiScaleTreeGraph.
- `FspmTF/test/`: the tests, the conformance files included.
- `conformance_run.jl`: the codec's dumps of the conformance files and its written scenes, for
  `.github/actions/conformance`.

Dependencies: JSON.jl and OrderedCollections.jl. Licence: MIT (`FspmTF/LICENSE`), as VirtualPlantLab; the rest of
fspm-TF is CeCILL-C. See [the documentation](../../doc/julia.md).
