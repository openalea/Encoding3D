# Reading and writing in Julia

encoding3d.jl, in `bindings/julia/encoding3d/`, reads and writes encoding3d files in Julia (1.10 or later). It passes the
conformance check like the Python codec. Two VirtualPlantLab models are covered:

- with MultiScaleTreeGraph.jl loaded, it turns an MTG into a data structure, and back. This is the multiscale graph
  of PlantSimEngine and PlantGeom;
- with PlantGraphs.jl loaded, it does the same for VPL's own graphs, and with PlantGeomTurtle for their geometry.

## Installing

encoding3d.jl is MIT-licensed, as VirtualPlantLab (the rest of encoding3d is CeCILL-C). It is not registered yet. Add it from the repository's subfolder:

```julia
using Pkg
Pkg.add(url = "https://github.com/openalea/encoding3d", subdir = "bindings/julia/encoding3d")
```

## An MTG, written and read back

```{note}
**A proposal for MTG.jl.** This adapter is a first proposal for MTG.jl's team to take over; it lives here until
they adopt it, then moves to MTG.jl's packages. encoding3d does not depend on it: its requirements and CI never install
MTG.jl. To build and test it by hand, see `bindings/julia/README.md`.
```

```julia
using encoding3d, MultiScaleTreeGraph

mtg = read_mtg("plant.mtg")
plants = from_mtg(mtg; id = "plant",
                  scales = Dict(1 => "Plant", 2 => "Axis", 3 => "Organ"),      # entity set names, per scale
                  variables = Dict("Length" => Variable(unit = "cm", standard_name = "length",
                                                        kind = "extensive")))
write_frame("plant.glb", Frame(data_structures = [plants], time = 0.0, time_unit = "d"))

frame = read_frame("plant.glb")
same_mtg = to_mtg(frame.data_structures[1])          # the same ids, symbols, links, attributes and order
```

`to_mtg` also reads a graph another platform wrote, e.g. a root system simulated by metafspm or a CPlantBox plant.
Its MTG has one scale per entity set and its variables as attributes, under a `Scene` root that holds the scalars.
Two things differ from the other platform's graph, and are undone by `from_mtg`:

- **Ids.** MTG.jl's node ids start at 1 and size its attribute store. When ids start at 0 or are sparse (CPlantBox's
  segments: 2^32 + node id), the nodes are numbered 1, 2, … in id order, and each keeps its id in the attribute
  `encoding3d_id`.
- **A parent in another complex**, such as a lateral root's first segment. MTG.jl takes a node's complex from its
  ancestors, so the node stays under its own axis (`/`) and keeps its parent in the attributes `encoding3d_parent` and
  `encoding3d_edge_type`.

| encoding3d | MultiScaleTreeGraph |
|---|---|
| one entity set per scale ≥ 1, `rank` the scale | the nodes of that scale |
| `id`, `label` | `node_id`, `symbol` |
| `complex` | the first ancestor at a smaller scale |
| `parent`, `edge_type` | the parent, at the same scale, by `<` (successor) or `+` (branch) |
| relation `bearer` | the parent otherwise, e.g. an axis borne by an internode |
| `sibling_order` | the node's position among its parent's children |
| `mtg_index` (standard name `mtg_index`) | the node's `index` |
| variables | the attributes, declared by `variables` (MTG.jl has no units); missing where a node has no such attribute; dates and times as ISO 8601 text with their `format` |
| scalars | the attributes of the scale 0 root (`Scene`) |

`ranks` gives a scale another rank than its number, e.g. the vocabulary's (Organ 5), and `labels` maps the
symbols to the vocabulary's labels. MTG.jl's own metadata (its classes and description, the scene node, each set's
MTG scale) is kept in the data structure's `extras["virtualplantlab"]`, so that `to_mtg` rebuilds the MTG exactly.
A float attribute a node lacks is NaN in its column, so `to_mtg` reads a NaN as no attribute.

## A VirtualPlantLab graph

```{note}
**A proposal for VirtualPlantLab.** This adapter is a first proposal for VirtualPlantLab's team to take over; it lives here until
they adopt it, then moves into VirtualPlantLab. encoding3d does not depend on it: its requirements and CI never install
VirtualPlantLab. To build and test it by hand, see `bindings/julia/README.md`.
```

VPL's own graphs (PlantGraphs.jl) have one scale, and their nodes are the model's types (`Internode`, `Leaf`, …).
With PlantGraphs loaded (Julia 1.12 or later), `from_graph` writes one entity set, `Organ` by default, with:

- each node's type as its label, and its fields as variables;
- the graph's data as scalars;
- its parent as the nearest kept node.

The turtle's movements (`RU`, `T`, `F`, …) are left out. PlantGraphs stores no edge type, so the edges are written as
`unknown`, and the children's order as the `sibling_order` column. A field a node's type lacks is missing. With
PlantGeomTurtle loaded too, `add_geometry!` adds the graph's turtle mesh, each triangle carrying the row of the node
that made it.

```julia
using encoding3d, PlantGraphs, PlantGeomTurtle, PlantGeomPrimitives

plants = from_graph(graph; id = "plant",
                    variables = Dict("length" => Variable(unit = "m", standard_name = "length")))
add_geometry!(plants, graph)          # the mesh of PlantGeomPrimitives.Mesh(graph), node by node (both export Mesh)
write_frame("plant.glb", Frame(data_structures = [plants]))

static, ids = to_graph(read_frame("plant.glb").data_structures[1];
                       types = Dict("Internode" => Internode, "Leaf" => Leaf))   # nodes rebuilt from their fields
graph = Graph(axiom = static, rules = rules)
```

## The format's own tables

```julia
using encoding3d

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

## Instances, derived fields and archives

encoding3d.jl reads and writes 0.4's instance sets (specification §12, [Instances](instances.md)): an `InstanceSet` is
a table of one row per instance (`template`, `owner`, `transform`, `id` and its own variables), its `vectors`
(`Ragged`) and `derived` fields (`DerivedField`); its `parts` are keys, found through the frame (embedded, else
`parts/<key>.glb` next to it).

```julia
frame = read_frame("run.fspm.zip/frame_000003.glb")          # a folder's file, or an archive's
sections = instance_set(data_structure(frame, "RootPopulation"), "sections")
potentials = evaluate(frame, "water_potential")              # one vector per instance
part = frame_part(frame, sections.parts[1])                  # a Template or an Operator

written = Frame()                                            # writing: parts added by content
key = add_part!(written, dense_operator([1.0 0.0; 0.75 0.25; 0.5 0.5; 0.25 0.75]))
# ... an InstanceSet whose parts hold key, in a data structure of written
write_frame("frames/frame_000000.glb", written)              # and frames/parts/<key>.glb, once
pack_archive("frames", "run.fspm.zip")                       # deflate; compression = "stored"
```

Archives are read stored, deflate (ZipArchives.jl) or lzma (liblzma's raw LZMA1 decoder, through XZ_jll), and packed
stored or deflate. A `solve` operator is factorised once per evaluation (sparse LU).

## Coupling with other platforms

encoding3d.jl takes part in coupling sessions run by encoding3d's coordinator ([Coupling platforms](coupling.md)):
`Participant(declaration)` joins one (its address and name from the environment when the coordinator launches it),
`turns(participant)` gives each turn's inputs, `send_update(participant, frame)` answers with its outputs. The folder
transport needs nothing more; ZeroMQ needs `using ZMQ` (the `encoding3dZMQExt` extension). A declaration can be built
(`Declaration`, `EntitySetSpec`, `VariableSpec`, `MappingSpec`) or read from its JSON (`declaration_from_json`).
`bindings/julia/coupling_conformance.jl` is its program for the conformance sessions.

## Checking it

```bash
julia --project=bindings/julia/encoding3d -e 'using Pkg; Pkg.test()'
julia --project=bindings/julia/encoding3d bindings/julia/conformance_run.jl conformance out
encoding3d compare-all out/dumps conformance          # the instances and archives included
find out/written -name "*.glb" -o -name "*.fspm.zip" | xargs encoding3d validate
```

The workflow `.github/workflows/julia-codec.yml` runs both, on Julia 1.10 and the latest release.
