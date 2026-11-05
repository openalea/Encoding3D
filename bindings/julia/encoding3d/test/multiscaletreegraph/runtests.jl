# encoding3d's MultiScaleTreeGraph.jl extension (an MTG as a data structure, and back): a proposal for MTG.jl's users
# (VirtualPlantLab, PlantSimEngine), tested by hand in its own project, so that encoding3d's tests and CI depend on no
# platform:
#
#     julia --project=bindings/julia/encoding3d/test/multiscaletreegraph -e 'using Pkg; Pkg.develop(path="bindings/julia/encoding3d"); Pkg.instantiate()'
#     julia --project=bindings/julia/encoding3d/test/multiscaletreegraph bindings/julia/encoding3d/test/multiscaletreegraph/runtests.jl
using Dates
using encoding3d
using JSON
using MultiScaleTreeGraph
using Test

const CONFORMANCE = normpath(joinpath(@__DIR__, "..", "..", "..", "..", "..", "conformance"))
const MTG_FILES = joinpath(pkgdir(MultiScaleTreeGraph), "test", "files")

conformance_files() = sort([relpath(joinpath(folder, name), CONFORMANCE)
                            for (folder, _, files) in walkdir(CONFORMANCE) for name in files
                            if endswith(name, ".glb") && !startswith(relpath(folder, CONFORMANCE), "coupling")])

"""The differences between two JSON values, as `encoding3d compare` finds them: objects by key, arrays in order,
numbers exactly (1 and 1.0 equal)."""
function differences(actual, expected, path = "\$")
    if expected isa AbstractDict
        actual isa AbstractDict || return ["$path: an object expected"]
        found = ["$path: missing key '$key'" for key in keys(expected) if !haskey(actual, key)]
        append!(found, ["$path: unexpected key '$key'" for key in keys(actual) if !haskey(expected, key)])
        for key in keys(expected)
            haskey(actual, key) && append!(found, differences(actual[key], expected[key], "$path.$key"))
        end
        return found
    elseif expected isa AbstractVector
        actual isa AbstractVector || return ["$path: an array expected"]
        length(actual) == length(expected) || return ["$path: $(length(actual)) items, $(length(expected)) expected"]
        return reduce(vcat, [differences(left, right, "$path[$index]")
                             for (index, (left, right)) in enumerate(zip(actual, expected))]; init = String[])
    elseif expected isa Number && !(expected isa Bool)
        actual isa Number && !(actual isa Bool) && Float64(actual) == Float64(expected) && return String[]
        return ["$path: $actual, $expected expected"]
    end
    isequal(actual, expected) && typeof(actual) == typeof(expected) && return String[]
    return ["$path: $(repr(actual)), $(repr(expected)) expected"]
end

as_json(frame) = JSON.parse(JSON.json(frame_to_dict(frame)))
expected_of(relative) = JSON.parse(read(joinpath(CONFORMANCE, relative[1:end-4] * ".expected.json"), String))


@testset "encoding3d and MultiScaleTreeGraph" begin
    @testset "MultiScaleTreeGraph: $name, exported, written, read and rebuilt as it was" for name in
            ("simple_plant.mtg", "palm.mtg", "simple_plant-P1U1.mtg")
        mtg = read_mtg(joinpath(MTG_FILES, name))
        variables = Dict("Length" => Variable(unit = "m", standard_name = "length", kind = "extensive"))
        data_structure_of_mtg = from_mtg(mtg; id = "plant", variables = variables)
        frame = from_bytes(to_bytes(Frame(data_structures = [data_structure_of_mtg])))
        rebuilt = to_mtg(frame.data_structures[1])
        nodes, rebuilt_nodes = traverse(mtg, node -> node), traverse(rebuilt, node -> node)
        @test length(nodes) == length(rebuilt_nodes)
        for (node, rebuilt_node) in zip(nodes, rebuilt_nodes)
            @test node_id(node) == node_id(rebuilt_node)
            @test (isroot(node) ? nothing : node_id(parent(node))) ==
                  (isroot(rebuilt_node) ? nothing : node_id(parent(rebuilt_node)))
            @test node_mtg(node) == node_mtg(rebuilt_node)
            @test [node_id(child) for child in children(node)] == [node_id(child) for child in children(rebuilt_node)]
            attributes = Dict(pairs(node_attributes(node)))
            rebuilt_attributes = Dict(pairs(node_attributes(rebuilt_node)))
            if isroot(node)
                for key in (:symbols, :scales)
                    @test string.(attributes[key]) == string.(rebuilt_attributes[key])
                end
                description, rebuilt_description = attributes[:description], rebuilt_attributes[:description]
                if description === nothing
                    @test rebuilt_description === nothing
                else
                    @test names(description) == names(rebuilt_description)
                    @test all(isequal(getproperty(description, column), getproperty(rebuilt_description, column))
                              for column in names(description))
                end
                filter!(item -> !(item.first in (:symbols, :scales, :description)), attributes)
                filter!(item -> !(item.first in (:symbols, :scales, :description)), rebuilt_attributes)
            end
            @test isequal(attributes, rebuilt_attributes)
        end
    end

    @testset "MultiScaleTreeGraph: missing attributes, dates, the order of children, MTG.jl's extras" begin
        mtg = read_mtg(joinpath(MTG_FILES, "simple_plant.mtg"))
        written = from_mtg(mtg; scales = Dict(3 => "Organ"), ranks = Dict(3 => 5))
        organs = entity_set(written, "Organ")
        @test organs.rank == 5                                           # the vocabulary's position
        @test isequal(organs.columns["isAlive"], [missing, false, true, true])   # Internode, Leaf, Internode, Leaf
        @test organs.variables["dateDeath"].format == "date"
        @test isequal(organs.columns["dateDeath"], [missing, "2022-08-24", missing, missing])
        @test organs.columns["sibling_order"] == [0, 0, 1, 0]                    # the leaf before the next internode
        @test organs.variables["mtg_index"].standard_name == "mtg_index"
        @test Set(keys(written.extras["virtualplantlab"])) == Set(["model", "scales", "metadata", "scene"])
        rebuilt = to_mtg(from_bytes(to_bytes(Frame(data_structures = [written]))).data_structures[1])
        @test scale(get_node(rebuilt, 4)) == 3                           # its MTG scale, not its rank
        @test attribute(get_node(rebuilt, 5), :dateDeath) == Date(2022, 8, 24)
        @test !(:isAlive in attribute_names(get_node(rebuilt, 4)))     # missing: no attribute
    end

    @testset "MultiScaleTreeGraph: the bearer of a branch at another scale" begin
        scene = Node(1, MutableNodeMTG(:/, :Scene, 0, 0), Dict{Symbol,Any}())
        plant = Node(2, scene, MutableNodeMTG(:/, :Plant, 1, 1), Dict{Symbol,Any}())
        axis = Node(3, plant, MutableNodeMTG(:/, :Axis, 1, 2), Dict{Symbol,Any}())
        internode = Node(4, axis, MutableNodeMTG(:/, :Internode, 1, 3), Dict{Symbol,Any}(:length => 0.1))
        branch = Node(5, internode, MutableNodeMTG(:+, :Axis, 2, 2), Dict{Symbol,Any}())      # borne by an internode
        Node(6, branch, MutableNodeMTG(:/, :Internode, 1, 3), Dict{Symbol,Any}(:length => 0.2))
        written = from_mtg(scene; scales = Dict(1 => "Plant", 2 => "Axis", 3 => "SubOrgan"))
        @test only(written.relations).name == "bearer"
        @test only(written.relations).columns["source"] == [5] && only(written.relations).columns["target"] == [4]
        axes = entity_set(written, "Axis")
        @test axes.columns["parent"] == [-1, -1] && axes.columns["complex"] == [2, 2]
        rebuilt = to_mtg(from_bytes(to_bytes(Frame(data_structures = [written]))).data_structures[1])
        rebuilt_branch = get_node(rebuilt, 5)
        @test node_id(parent(rebuilt_branch)) == 4 && link(rebuilt_branch) == :+
        @test attribute(get_node(rebuilt, 6), :length) == 0.2
    end

    @testset "MultiScaleTreeGraph: ids from 0 and sparse (MTG.jl's: from 1, dense), numbered and written back" begin
        plants = DataStructure("plant"; entity_sets = [
            EntitySet("Plant"; columns = Dict("id" => [0]), rank = 1),
            EntitySet("Organ"; rank = 5, columns = Dict("id" => [1, 2], "complex" => [0, 0], "parent" => [-1, 1],
                                                        "edge_type" => ["none", "branch"], "length" => [1.0, 2.0])),
            EntitySet("SubOrgan"; rank = 6, columns = Dict("id" => [2^32 + 5, 2^32 + 9], "complex" => [1, 2],
                                                           "parent" => [-1, 2^32 + 5], "edge_type" => ["none", "branch"]))])
        mtg = to_mtg(plants)
        nodes = traverse(mtg, node -> node)
        @test sort(node_id.(nodes)) == 1:5                              # dense, from 1
        @test [attribute(node, :encoding3d_id) for node in nodes] == [0, 1, 2, 2^32 + 9, 2^32 + 5]
        lateral = only(node for node in nodes if attribute(node, :encoding3d_id) == 2^32 + 9)
        @test attribute(parent(lateral), :encoding3d_id) == 2 && link(lateral) == :/     # under its own organ
        @test attribute(lateral, :encoding3d_parent) == 2^32 + 5 && attribute(lateral, :encoding3d_edge_type) == "branch"
        again = from_mtg(mtg; scales = Dict(1 => "Plant", 5 => "Organ", 6 => "SubOrgan"))
        for name in ("Plant", "Organ", "SubOrgan")                     # the same rows, in the MTG's order
            written, read = entity_set(plants, name), entity_set(again, name)
            order = sortperm(read.columns["id"])
            for column in ("id", "complex", "parent", "edge_type", "length")
                haskey(written.columns, column) || continue
                @test read.columns[column][order] == written.columns[column][sortperm(written.columns["id"])]
            end
        end
        @test !haskey(entity_set(again, "SubOrgan").columns, "encoding3d_id")
    end

    @testset "MultiScaleTreeGraph: another platform's graph (the conformance root system) as an MTG" begin
        root_system = read_frame(joinpath(CONFORMANCE, "root_system.glb")).data_structures[1]
        mtg = to_mtg(root_system)
        nodes = traverse(mtg, node -> node)
        @test length(nodes) == sum(row_count(set) for set in root_system.entity_sets) + 1        # + the scene
        entity_id(node) = attribute(node, :encoding3d_id; default = node_id(node))   # ids 10 to 1000: renumbered
        node_of = Dict(entity_id(node) => node for node in nodes if !isroot(node))
        segments = entity_set(root_system, "SubOrgan")
        complex_of = Dict(zip(segments.columns["id"], segments.columns["complex"]))
        for (id, parent_id) in zip(segments.columns["id"], segments.columns["parent"])
            node = node_of[id]
            @test entity_id(parent(node)) == complex_of[id] || entity_id(parent(node)) == parent_id
            parent_id == NO_ID && continue
            if complex_of[parent_id] == complex_of[id]
                @test entity_id(parent(node)) == parent_id && link(node) == :<    # along its axis
            else
                @test attribute(node, :encoding3d_parent) == parent_id && link(node) == :/   # a lateral's first segment
            end
        end
        @test attribute(node_of[segments.columns["id"][1]], :length) == segments.columns["length"][1]
        again = from_mtg(mtg; scales = Dict(1 => "Plant", 2 => "Axis", 6 => "SubOrgan"))      # and back: the same graph
        for set in root_system.entity_sets
            read = entity_set(again, set.name)
            order, written_order = sortperm(read.columns["id"]), sortperm(set.columns["id"])
            for column in ("id", "complex", "parent", "edge_type", "length")
                haskey(set.columns, column) || continue
                @test isequal(read.columns[column][order], set.columns[column][written_order])
            end
        end
    end

end
