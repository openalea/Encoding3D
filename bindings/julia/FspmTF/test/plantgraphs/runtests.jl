# FspmTF.jl's VirtualPlantLab extensions (PlantGraphs, PlantGeomTurtle; Julia 1.12 or later, as PlantGraphs). Their own
# project, so that the package's tests keep running on Julia 1.10:
#
#     julia --project=bindings/julia/FspmTF/test/plantgraphs -e 'using Pkg; Pkg.develop(path="bindings/julia/FspmTF"); Pkg.instantiate()'
#     julia --project=bindings/julia/FspmTF/test/plantgraphs bindings/julia/FspmTF/test/plantgraphs/runtests.jl
using FspmTF
using PlantGeomPrimitives
using PlantGeomTurtle
using PlantGraphs
using Test

# A small VPL plant: internodes as cylinders, leaves as ellipses, the turtle's rotations between them
struct Internode <: PlantGraphs.Node
    length::Float64
    width::Float64
end
struct Leaf <: PlantGraphs.Node
    length::Float64
    width::Float64
    age::Int
end
struct Meristem <: PlantGraphs.Node end
struct Weather
    temperature::Float64
end

PlantGeomTurtle.feed!(turtle::Turtle, node::Internode, data) =
    HollowCylinder!(turtle; length = node.length, width = node.width, height = node.width, move = true)
PlantGeomTurtle.feed!(turtle::Turtle, node::Leaf, data) =
    Ellipse!(turtle; length = node.length, width = node.width, move = false)

plant() = Graph(axiom = Internode(0.1, 0.01) + (RU(30.0) + Leaf(0.05, 0.02, 3), RU(-30.0) + Leaf(0.04, 0.02, 1)) +
                       Internode(0.08, 0.008) + Meristem(),
                data = Weather(20.5))

@testset "FspmTF and VirtualPlantLab" begin
    @testset "A graph as a data structure, written, read and rebuilt" begin
        graph = plant()
        written = from_graph(graph; id = "plant",
                             variables = Dict("length" => Variable(unit = "m", standard_name = "length", kind = "extensive")))
        organs = entity_set(written, "Organ")
        @test organs.columns["label"] == ["Internode", "Leaf", "Leaf", "Internode", "Meristem"]   # no turtle moves
        ids = organs.columns["id"]
        @test organs.columns["parent"] == [-1, ids[1], ids[1], ids[1], ids[4]]       # the leaves on the first internode
        @test organs.columns["edge_type"] == ["none", "unknown", "unknown", "unknown", "unknown"]   # none stored
        @test organs.columns["order"] == [0, 0, 1, 2, 0]                              # the leaves, then the internode
        @test isequal(organs.columns["length"], [0.1, 0.05, 0.04, 0.08, NaN])       # NaN: the meristem has none
        @test isequal(organs.columns["age"], [missing, 3, 1, missing, missing])       # missing where no field
        @test written.extras["virtualplantlab"]["model"] == "PlantGraphs"
        @test written.scalars.columns["temperature"] == [20.5]

        frame = from_bytes(to_bytes(Frame(data_structures = [written])))
        read_back = frame.data_structures[1]
        static, graph_ids = to_graph(read_back; types = Dict("Internode" => Internode, "Leaf" => Leaf,
                                                             "Meristem" => Meristem))
        again = from_graph(static; keep = node -> true)
        again_organs = entity_set(again, "Organ")
        @test again_organs.columns["label"] == organs.columns["label"]
        @test isequal(again_organs.columns["length"], organs.columns["length"])
        @test isequal(again_organs.columns["age"], organs.columns["age"])
        @test again_organs.columns["edge_type"] == organs.columns["edge_type"]
        @test again_organs.columns["parent"] == [-1; [graph_ids[parent] for parent in organs.columns["parent"][2:end]]]
    end

    @testset "Its turtle geometry, each triangle with its node" begin
        graph = plant()
        written = from_graph(graph)
        mesh = add_geometry!(written, graph)
        reference = PlantGeomPrimitives.Mesh(graph)           # VPL's own mesh (both packages export a Mesh)
        @test size(mesh.positions, 1) == length(vertices(reference))
        @test all(mesh.positions[index, :] == collect(vertices(reference)[index]) for index in 1:length(vertices(reference)))
        rows = mesh.feature_rows["Organ"]
        labels = entity_set(written, "Organ").columns["label"]
        @test all(row != NO_ID for row in rows)
        @test Set(labels[row + 1] for row in rows) == Set(["Internode", "Leaf"])   # meristems have no geometry
        path = joinpath(mktempdir(), "vpl_plant.glb")
        write_frame(path, Frame(data_structures = [written]))
        @test read_frame(path).data_structures[1].meshes[1].feature_rows == mesh.feature_rows
    end
end
