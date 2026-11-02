# Reading and writing in Julia

FspmTF.jl, in `bindings/julia/FspmTF/`, reads and writes fspm-TF files in Julia (1.10 or later). It passes the
conformance check like the Python codec. With MultiScaleTreeGraph.jl loaded, it also turns an MTG into a data
structure, and back. This is the MTG library of VirtualPlantLab's PlantGeom and of PlantSimEngine.

## Installing

FspmTF.jl is not registered yet. Add it from the repository's subfolder:

```julia
using Pkg
Pkg.add(url = "https://github.com/openalea/fspm-TF", subdir = "bindings/julia/FspmTF")
```

## An MTG, written and read back

```julia
using FspmTF, MultiScaleTreeGraph

mtg = read_mtg("plant.mtg")
plants = from_mtg(mtg; id = "plant",
                  scales = Dict(1 => "Plant", 2 => "Axis", 3 => "Organ"),      # entity set names, per scale
                  variables = Dict("Length" => Variable(unit = "cm", standard_name = "length",
                                                        kind = "extensive")))
write_frame("plant.glb", Frame(data_structures = [plants], time = 0.0, time_unit = "d"))

frame = read_frame("plant.glb")
same_mtg = to_mtg(frame.data_structures[1])          # the same ids, symbols, links, attributes and order
```

`to_mtg` also reads a graph another platform wrote, e.g. a root system simulated by metafspm. Its MTG has one scale
per entity set and its variables as attributes, under a `Scene` root that holds the scalars.

| fspm-TF | MultiScaleTreeGraph |
|---|---|
| one entity set per scale ≥ 1, `rank` the scale | the nodes of that scale |
| `id`, `label` | `node_id`, `symbol` |
| `complex` | the first ancestor at a smaller scale |
| `parent`, `edge_type` | the parent, at the same scale, by `<` (successor) or `+` (branch) |
| relation `bearer` | the parent otherwise, e.g. an axis borne by an internode |
| `mtg_index` | the node's `index` |
| variables | the attributes, declared by `variables` (MTG.jl has no units) |
| scalars | the attributes of the scale 0 root (`Scene`) |

Some MTG content has no place in fspm-TF 0.1: missing attributes, dates, the MTG's classes and description, and
the order of children. It is kept in the data structure's `extras["MultiScaleTreeGraph"]`, so that `to_mtg`
rebuilds the MTG exactly. Other readers see the missing values as NaN, `false`, 0 or "".

## The format's own tables

```julia
using FspmTF

frame = read_frame("scene.glb")
frame.time, frame.time_unit, frame.step

roots = data_structure(frame, "RootPopulation")
segments = entity_set(roots, "SubOrgan")
segments.columns["length"]                     # one value per segment
segments.variables["length"].unit              # its declared unit, e.g. "m"
entity_ids(segments)

for frame in read_sequence("outputs/frames/scene.fspm.json")   # a sequence, frame by frame
    println(frame.step)
end
```

Writing builds the same objects:

```julia
segments = EntitySet("SubOrgan"; rank = 6,
                     columns = Dict("id" => [10, 11], "parent" => [-1, 10],
                                    "edge_type" => ["none", "successor"], "length" => [0.01, 0.012]),
                     variables = Dict("length" => Variable(unit = "m", standard_name = "length",
                                                           kind = "extensive")))
write_frame("roots.glb", Frame(data_structures = [DataStructure("roots"; entity_sets = [segments])]))
write_sequence("frames", frames)               # one GLB per frame, and scene.fspm.json
```

A column is a `Vector` (numbers, `Bool`, `String`) or a `Matrix` (one row per entity: a fixed-size vector per
entity). NaN and infinities are written with the specification's stand-ins and read back as they were.

## Checking it

```bash
julia --project=bindings/julia/FspmTF -e 'using Pkg; Pkg.test()'
julia --project=bindings/julia/FspmTF bindings/julia/conformance_run.jl conformance out
fspm-tf compare-all out/dumps conformance && fspm-tf validate out/written/*.glb
```

The workflow `.github/workflows/julia-codec.yml` runs both, on Julia 1.10 and the latest release.
