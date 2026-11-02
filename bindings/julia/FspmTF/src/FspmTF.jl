"""
    FspmTF

Reading and writing fspm-TF files in Julia: whole functional-structural plant model scenes (multiscale plant graphs,
their variables and parameters, their geometry, the environment's grids) at successive time steps, one glTF 2.0
binary (GLB) file per time step. The specification is `spec/specification.md` in the fspm-TF repository.

    read_frame(path) -> Frame             write_frame(path, frame)
    from_bytes(data) -> Frame             to_bytes(frame) -> Vector{UInt8}
    read_index(path), read_sequence(path) write_sequence(directory, frames)
    frame_to_dict(frame), write_dump(path, frame)     the layout of the conformance files' expected values

With MultiScaleTreeGraph loaded, `from_mtg` and `to_mtg` convert an MTG to and from a data structure. With
VirtualPlantLab's PlantGraphs loaded, `from_graph` and `to_graph` convert its graphs; with PlantGeomTurtle too,
`add_geometry!` adds a graph's turtle geometry as a mesh.
"""
module FspmTF

using Dates
using JSON
using OrderedCollections: OrderedDict

"""The version of the specification this package reads and writes."""
const SPECIFICATION_VERSION = "0.2"

include("glb.jl")
include("model.jl")
include("codec.jl")
include("sequence.jl")
include("dump.jl")
include("values.jl")

export Frame, DataStructure, EntitySet, Relation, Table, Mapping, Grid, Mesh, Variable, NO_ID, EDGE_TYPES
export read_frame, write_frame, from_bytes, to_bytes, read_index, read_sequence, write_sequence, write_index
export frame_to_dict, write_dump, row_count, variable_names, entity_ids, entity_set, data_structure
export from_mtg, to_mtg, from_graph, to_graph, add_geometry!

"""
    from_mtg(mtg; id="plants", scales=Dict(), variables=Dict(), platform="MultiScaleTreeGraph", model=nothing)
        -> DataStructure

A MultiScaleTreeGraph (its root node) as a `graph` data structure. Defined when MultiScaleTreeGraph is loaded
(the package extension `FspmTFMultiScaleTreeGraphExt`).
"""
function from_mtg end

"""
    to_mtg(data_structure) -> Node

A `graph` data structure as a MultiScaleTreeGraph (its root node). Defined when MultiScaleTreeGraph is loaded (the
package extension `FspmTFMultiScaleTreeGraphExt`).
"""
function to_mtg end

"""
    from_graph(graph; id="plant", entity_set="Organ", rank=5, variables=Dict(), keep, platform="VirtualPlantLab",
               model=nothing) -> DataStructure

A VirtualPlantLab graph (PlantGraphs: `Graph` or `StaticGraph`) as a `graph` data structure of one entity set.
Defined when PlantGraphs is loaded (the package extension `FspmTFPlantGraphsExt`).
"""
function from_graph end

"""
    to_graph(data_structure; types, entity_set=nothing) -> (StaticGraph, ids)

A data structure's entities as a PlantGraphs `StaticGraph`, each node built from its row by `types[label]`. Defined
when PlantGraphs is loaded (the package extension `FspmTFPlantGraphsExt`).
"""
function to_graph end

"""
    add_geometry!(data_structure, graph; entity_set="Organ", turtle=Turtle(Float64), name="plant") -> Mesh

Adds a VirtualPlantLab graph's turtle geometry to its data structure as a mesh, each vertex carrying its node's row.
Defined when PlantGraphs, PlantGeomTurtle and PlantGeomPrimitives are loaded (`FspmTFPlantGeomTurtleExt`).
"""
function add_geometry! end

end
