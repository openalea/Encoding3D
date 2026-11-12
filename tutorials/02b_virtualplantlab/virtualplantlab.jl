# Tutorial 2b: VirtualPlantLab writes and reads encoding3d (README.md explains each part).
#
#     julia --project=. -e 'using Pkg; Pkg.instantiate()'      # once
#     julia --project=. virtualplantlab.jl
using encoding3d
import MultiScaleTreeGraph as MTG                 # MTG.jl: its names qualified (PlantGraphs has some too)
using PlantGeomPrimitives
using PlantGeomTurtle
using PlantGraphs

const OUTPUTS = joinpath(@__DIR__, "outputs")
mkpath(OUTPUTS)

# ── 1. A VirtualPlantLab plant: its node types, how they are drawn, how it grows ─────────────────────────
struct Internode <: PlantGraphs.Node
    length::Float64
    width::Float64
end
struct Leaf <: PlantGraphs.Node
    length::Float64
    width::Float64
end
struct Meristem <: PlantGraphs.Node end

# the turtle draws an internode as a cylinder (and moves to its end), a leaf as an ellipse
PlantGeomTurtle.feed!(turtle::Turtle, node::Internode, data) =
    HollowCylinder!(turtle; length = node.length, width = node.width, height = node.width, move = true)
PlantGeomTurtle.feed!(turtle::Turtle, node::Leaf, data) = Ellipse!(turtle; length = node.length, width = node.width, move = false)

# each step, the meristem makes an internode, two opposite leaves, and a meristem above them
grow = Rule(Meristem, rhs = meristem -> Internode(0.04, 0.004) + (RU(60.0) + Leaf(0.06, 0.02), RU(-60.0) + Leaf(0.06, 0.02)) +
                                       RH(90.0) + Meristem())
plant = Graph(axiom = Internode(0.04, 0.004) + Meristem(), rules = grow)

# ── 2. A frame per step: the graph's nodes as an entity set, its geometry as a mesh ─────────────────────
length_declaration = Dict("length" => Variable(unit = "m", standard_name = "length", kind = "extensive"),
                          "width" => Variable(unit = "m", kind = "descriptor"))
frames = Frame[]
for step in 0:4
    step > 0 && rewrite!(plant)
    data_structure = from_graph(plant; id = "plant", variables = length_declaration)   # one entity set, "Organ"
    add_geometry!(data_structure, plant)                                              # the turtle's triangles
    push!(frames, Frame(data_structures = [data_structure], time = Float64(step), time_unit = "d", step = step))
end
index = write_sequence(joinpath(OUTPUTS, "frames"), frames)
organs = entity_set(frames[end].data_structures[1], "Organ")
println("written: ", index)
println("last frame: ", row_count(organs), " organs (", join(unique(organs.columns["label"]), ", "), "), ",
        size(frames[end].data_structures[1].meshes[1].positions, 1), " mesh vertices")

# ── 3. Back into a VirtualPlantLab graph: each row rebuilt as a node of its type ───────────────────────
last_frame = read_frame(joinpath(OUTPUTS, "frames", "frame_000004.glb"))
graph, ids = to_graph(last_frame.data_structures[1];
                      types = Dict("Internode" => Internode, "Leaf" => Leaf, "Meristem" => Meristem))
rebuilt = Graph(axiom = graph, rules = grow)          # a full VirtualPlantLab graph again, with its growth rule
leaves = apply(rebuilt, Query(Leaf))
println("rebuilt: ", length(leaves), " leaves, total leaf length ", round(sum(leaf.length for leaf in leaves); digits = 3), " m")
rewrite!(rebuilt)                                      # and it grows on from where the file left it
println("one more step: ", length(apply(rebuilt, Query(Leaf))), " leaves")

# ── 4. MTG.jl: another platform's root system (the conformance file) as an MTG, and back ──────────────
conformance = joinpath(@__DIR__, "..", "..", "conformance", "root_system.glb")
roots = read_frame(conformance).data_structures[1]
mtg = to_mtg(roots)
println("as an MTG: ", length(MTG.traverse(mtg, node -> node)), " nodes, scales ",
        sort(unique(Int[MTG.scale(node) for node in MTG.traverse(mtg, node -> node)])))
again = from_mtg(mtg; id = "root_system", scales = Dict(1 => "Plant", 2 => "Axis", 6 => "SubOrgan"))
println("and back: ", [string(set.name, " ", row_count(set)) for set in again.entity_sets])
