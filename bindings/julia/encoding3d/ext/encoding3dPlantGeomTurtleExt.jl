"""
A VirtualPlantLab graph's geometry (PlantGeomTurtle: each node's `feed!` adds triangles to a turtle's mesh) as a mesh of
its data structure, each vertex carrying the row of the node that made it: the node itself when it is an entity, else
(a turtle's movement) its nearest kept ancestor.

Status: a first proposal for VirtualPlantLab's team to take over, not a part of encoding3d: loaded only when the platform's
package is, encoding3d's requirements and CI do not depend on it; tested by hand (bindings/julia/README.md).
"""
module encoding3dPlantGeomTurtleExt

using encoding3d
using encoding3d: NO_ID
import PlantGeomPrimitives as PGP
import PlantGeomTurtle as PGT
import PlantGraphs as PG

static_of(graph::PG.Graph) = PG.static_graph(graph)
static_of(graph::PG.StaticGraph) = graph
graph_data(graph::PG.Graph) = PG.data(graph)
graph_data(::PG.StaticGraph) = nothing

"""
    add_geometry!(data_structure, graph; entity_set="Organ", turtle=Turtle(Float64), name="plant") -> Mesh

Runs the turtle over the graph as `feed!(turtle, graph)` does (the same order, the same branching states), records
which node made each triangle, and adds the mesh to the data structure (written by `from_graph` from the same graph).
The positions are the turtle's (VPL: metres, z up). The triangles' colours and materials are not written (encoding3d has
no slot for them).
"""
function encoding3d.add_geometry!(data_structure::DataStructure, graph::Union{PG.Graph,PG.StaticGraph};
                              entity_set::AbstractString = "Organ", turtle = PGT.Turtle(Float64),
                              name::AbstractString = "plant")
    static = static_of(graph)
    set = encoding3d.entity_set(data_structure, entity_set)
    row_of = Dict(id => row - 1 for (row, id) in enumerate(set.columns["id"]))
    mesh = PGP.Mesh(turtle)
    vertex_rows = Int64[]
    # As PlantGeomTurtle's feed!(turtle, graph): depth first, the turtle's state saved before each branch
    stack = Tuple{PG.GraphNode,Int64}[(PG.getroot(static), NO_ID)]   # node, its nearest entity's row
    while !isempty(stack)
        node, ancestor_row = pop!(stack)
        before = length(PGP.vertices(mesh))
        PGT.feed!(turtle, PG.data(node), graph_data(graph))
        own = PG.self_id(node) >= 0 ? get(row_of, PG.self_id(node), nothing) : nothing   # SET nodes: id -1
        row = own === nothing ? ancestor_row : own
        append!(vertex_rows, fill(row, length(PGP.vertices(mesh)) - before))
        children = collect(PG.children(node, static))
        if length(children) == 1
            push!(stack, (only(children), row))
        elseif length(children) > 1
            for child in children
                push!(stack, (PG.GraphNode(PGT.SET(to = PGT.pos(turtle), head = PGT.head(turtle),
                                                   up = PGT.up(turtle), arm = PGT.arm(turtle))), row))
                push!(stack, (child, row))
            end
        end
    end
    vertices = PGP.vertices(mesh)
    positions = Matrix{Float64}(undef, length(vertices), 3)
    for (index, vertex) in enumerate(vertices)
        positions[index, :] .= (vertex[1], vertex[2], vertex[3])
    end
    added = Mesh(name; positions = positions, feature_rows = Dict(entity_set => vertex_rows))
    push!(data_structure.meshes, added)
    return added
end

end
