using Dates
using FspmTF
using JSON
using MultiScaleTreeGraph
using Test

const CONFORMANCE = normpath(joinpath(@__DIR__, "..", "..", "..", "..", "conformance"))
const MTG_FILES = joinpath(pkgdir(MultiScaleTreeGraph), "test", "files")

conformance_files() = sort([relpath(joinpath(folder, name), CONFORMANCE)
                            for (folder, _, files) in walkdir(CONFORMANCE) for name in files
                            if endswith(name, ".glb") && !startswith(relpath(folder, CONFORMANCE), "coupling")])

"""The differences between two JSON values, as `fspm-tf compare` finds them: objects by key, arrays in order,
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

@testset "FspmTF" begin
    @testset "GLB container: the conformance files' JSON and binary chunks repacked as they were" begin
        for relative in conformance_files()
            data = read(joinpath(CONFORMANCE, relative))
            document, binary = FspmTF.unpack(data)
            again, binary_again = FspmTF.unpack(FspmTF.pack(document, binary))
            @test binary_again == binary
            @test isempty(differences(again, document))
            @test length(binary) % 8 == 0
        end
        @test_throws ArgumentError FspmTF.unpack(UInt8[1, 2, 3])
    end

    @testset "Reading: every conformance file as its expected values ($relative)" for relative in conformance_files()
        frame = read_frame(joinpath(CONFORMANCE, relative))
        @test isempty(differences(as_json(frame), expected_of(relative)))
    end

    @testset "Writing: what is written reads back as the expected values ($relative)" for relative in conformance_files()
        frame = from_bytes(to_bytes(read_frame(joinpath(CONFORMANCE, relative))))
        @test isempty(differences(as_json(frame), expected_of(relative)))
    end

    @testset "Columns of every type, NaN, infinities, vectors, text" begin
        columns = FspmTF.Columns("id" => Int32[0, 1, 2], "label" => ["Leaf", "Internode", "Leaf"],
                                 "parent" => [-1, 0, 1], "edge_type" => ["none", "successor", "branch"],
                                 "with_nan" => [1.0, NaN, -2.5], "with_infinities" => Float32[Inf, 1, -Inf],
                                 "flag" => [true, false, true], "name" => ["é", "", "a b"],
                                 "position" => [1.0 2.0 3.0; 4.0 5.0 6.0; 7.0 8.0 9.0])
        for T in FspmTF.COLUMN_TYPES
            columns["column_$(lowercase(string(T)))"] = T[1, 2, 3]
        end
        frame = Frame(data_structures = [DataStructure("plants"; entity_sets = [
            EntitySet("Organ"; columns = columns, rank = 1,
                      variables = Dict("with_nan" => Variable(unit = "m", standard_name = "length", kind = "extensive",
                                                              description = "a length", minimum = 0,
                                                              references = ["a reference"])))],
            origin = [1.0 0 0 0.5; 0 1 0 0; 0 0 1 -0.1; 0 0 0 1], extras = Dict{String,Any}("platform" => [1, 2]))],
            time = 2.5, time_unit = "h", step = 3)
        read_back = from_bytes(to_bytes(frame))
        organ = entity_set(data_structure(read_back, "plants"), "Organ")
        @test eltype(organ.columns["id"]) == Int64                   # ids are Int64
        @test isequal(organ.columns["with_nan"], [1.0, NaN, -2.5])
        @test organ.columns["with_infinities"] == Float32[Inf, 1, -Inf]
        @test organ.columns["flag"] == [true, false, true]
        @test organ.columns["name"] == ["é", "", "a b"]
        @test organ.columns["position"] == [1.0 2.0 3.0; 4.0 5.0 6.0; 7.0 8.0 9.0]
        @test organ.columns["label"] == ["Leaf", "Internode", "Leaf"]
        for T in FspmTF.COLUMN_TYPES
            @test organ.columns["column_$(lowercase(string(T)))"] == T[1, 2, 3]
            @test eltype(organ.columns["column_$(lowercase(string(T)))"]) == T
        end
        @test organ.variables["with_nan"] == frame.data_structures[1].entity_sets[1].variables["with_nan"]
        @test data_structure(read_back, "plants").origin == frame.data_structures[1].origin
        @test data_structure(read_back, "plants").extras["platform"] == [1, 2]
        @test (read_back.time, read_back.time_unit, read_back.step) == (2.5, "h", 3)
    end

    @testset "Meshes: positions, feature rows (none included), indices, display copies" begin
        set = EntitySet("SubOrgan"; columns = Dict("id" => [10, 11]), rank = 1)
        mesh = Mesh("roots"; positions = [0.0 0 0; 1 0 0; 0 1 0; 0 0 1], feature_rows = Dict("SubOrgan" => [0, 1, 1, -1]),
                    indices = [0, 1, 2, 0, 2, 3], display = Dict("radius" => Float32[1, 2, 2, 0]),
                    display_sources = Dict("radius" => "SubOrgan"))
        frame = Frame(data_structures = [DataStructure("roots"; entity_sets = [set], meshes = [mesh])])
        read_back = from_bytes(to_bytes(frame)).data_structures[1].meshes[1]
        @test read_back.positions == mesh.positions
        @test read_back.feature_rows == mesh.feature_rows
        @test read_back.indices == mesh.indices
        @test read_back.display == mesh.display && read_back.display_sources == mesh.display_sources
    end

    @testset "What the specification forbids is refused" begin
        bad_column = Frame(data_structures = [DataStructure("plants"; entity_sets = [
            EntitySet("Organ"; columns = Dict("id" => [0], "1st" => [1.0]))])])
        @test_throws ArgumentError to_bytes(bad_column)
        @test_throws ArgumentError to_bytes(Frame(data_structures = [DataStructure("bad id")]))
        bad_edge = Frame(data_structures = [DataStructure("plants"; entity_sets = [
            EntitySet("Organ"; columns = Dict("id" => [0], "parent" => [-1], "edge_type" => ["root"]))])])
        @test_throws ArgumentError to_bytes(bad_edge)
        both = Frame(data_structures = [DataStructure("plants"; entity_sets = [
            EntitySet("Organ"; columns = Dict("id" => [0, 1], "x" => [NaN, -floatmax(Float64)]))])])
        @test_throws ArgumentError to_bytes(both)
        @test_throws ArgumentError EntitySet("Organ"; columns = Dict("id" => [0, 1], "x" => [1.0]))
    end

    @testset "Sequences: frames and their index" begin
        folder = mktempdir()
        frames = [Frame(data_structures = [DataStructure("plants"; entity_sets = [
                      EntitySet("Plant"; columns = Dict("id" => [0], "biomass" => [Float64(step)]), rank = 1)])],
                        time = step / 24, time_unit = "d", step = step) for step in 0:2]
        index = write_sequence(folder, frames)
        entries = read_index(index)["frames"]
        @test [entry["step"] for entry in entries] == [0, 1, 2]
        @test [frame.data_structures[1].entity_sets[1].columns["biomass"][1] for frame in read_sequence(index)] ==
              [0.0, 1.0, 2.0]
        read_back = read_index(joinpath(CONFORMANCE, "growing_sequence", "scene.fspm.json"))
        @test all(isfile(entry["path"]) for entry in read_back["frames"])
    end

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
        @test [attribute(node, :fspm_tf_id) for node in nodes] == [0, 1, 2, 2^32 + 9, 2^32 + 5]
        lateral = only(node for node in nodes if attribute(node, :fspm_tf_id) == 2^32 + 9)
        @test attribute(parent(lateral), :fspm_tf_id) == 2 && link(lateral) == :/     # under its own organ
        @test attribute(lateral, :fspm_tf_parent) == 2^32 + 5 && attribute(lateral, :fspm_tf_edge_type) == "branch"
        again = from_mtg(mtg; scales = Dict(1 => "Plant", 5 => "Organ", 6 => "SubOrgan"))
        for name in ("Plant", "Organ", "SubOrgan")                     # the same rows, in the MTG's order
            written, read = entity_set(plants, name), entity_set(again, name)
            order = sortperm(read.columns["id"])
            for column in ("id", "complex", "parent", "edge_type", "length")
                haskey(written.columns, column) || continue
                @test read.columns[column][order] == written.columns[column][sortperm(written.columns["id"])]
            end
        end
        @test !haskey(entity_set(again, "SubOrgan").columns, "fspm_tf_id")
    end

    @testset "MultiScaleTreeGraph: another platform's graph (the conformance root system) as an MTG" begin
        root_system = read_frame(joinpath(CONFORMANCE, "root_system.glb")).data_structures[1]
        mtg = to_mtg(root_system)
        nodes = traverse(mtg, node -> node)
        @test length(nodes) == sum(row_count(set) for set in root_system.entity_sets) + 1        # + the scene
        entity_id(node) = attribute(node, :fspm_tf_id; default = node_id(node))   # ids 10 to 1000: renumbered
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
                @test attribute(node, :fspm_tf_parent) == parent_id && link(node) == :/   # a lateral's first segment
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

    @testset "coupling" begin
        # a partial frame: its sender and removed entities kept
        frame = Frame(data_structures = [DataStructure("plant"; entity_sets = [
                          EntitySet("SubOrgan"; rank = 6, columns = FspmTF.Columns(
                              "id" => Int64[10, 11], "complex" => Int64[3, 3], "parent" => Int64[NO_ID, 10],
                              "edge_type" => ["none", "successor"], "sugar" => [1.0, 2.0]))])],
                      update = Update("vpl"; removed = Dict(("plant", "SubOrgan") => Int64[5])))
        again = from_bytes(to_bytes(frame))
        @test again.update.participant == "vpl"
        @test again.update.removed[("plant", "SubOrgan")] == [5]
        @test entity_set(data_structure(again, "plant"), "SubOrgan").columns["complex"] == [3, 3]
        # a declaration as JSON: an entity set followed for each variable's
        declaration = Declaration("function"; entity_sets = [EntitySetSpec("plant", "SubOrgan"; rights = "refines")],
                                  variables = [VariableSpec("plant", "Organ", "length", "requires"; unit = "m",
                                                            standard_name = "length")])
        value = FspmTF.declaration_json(declaration)
        @test [item["name"] for item in value["entitySets"]] == ["SubOrgan", "Organ"]
        @test value["entitySets"][1]["rank"] == 6 && value["entitySets"][2]["rights"] == "follows"
        @test value["variables"][1]["standardName"] == "length"
        # the folder transport: a participant's queues, a message and its payload
        folder = mktempdir()
        participant = FspmTF.FolderChannel(folder, "function")
        FspmTF.send_message(participant, Dict("type" => "update", "step" => 0), to_bytes(frame))
        coordinator = FspmTF.FolderChannel(joinpath(folder, "function", "to_coordinator"), mktempdir(), 0, 0)
        header, payload = FspmTF.receive_message(coordinator, 5)
        @test header["type"] == "update" && from_bytes(payload).update.participant == "vpl"
        @test isfile(joinpath(folder, "function", "to_coordinator", "00000000.glb"))
        @test_throws ErrorException FspmTF.receive_message(coordinator, 0.05)          # nothing more: a timeout
    end
end
