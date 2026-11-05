using Dates
using encoding3d
using JSON
using Test

const CONFORMANCE = normpath(joinpath(@__DIR__, "..", "..", "..", "..", "conformance"))

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

@testset "encoding3d" begin
    @testset "GLB container: the conformance files' JSON and binary chunks repacked as they were" begin
        for relative in conformance_files()
            data = read(joinpath(CONFORMANCE, relative))
            document, binary = encoding3d.unpack(data)
            again, binary_again = encoding3d.unpack(encoding3d.pack(document, binary))
            @test binary_again == binary
            @test isempty(differences(again, document))
            @test length(binary) % 8 == 0
        end
        @test_throws ArgumentError encoding3d.unpack(UInt8[1, 2, 3])
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
        columns = encoding3d.Columns("id" => Int32[0, 1, 2], "label" => ["Leaf", "Internode", "Leaf"],
                                 "parent" => [-1, 0, 1], "edge_type" => ["none", "successor", "branch"],
                                 "with_nan" => [1.0, NaN, -2.5], "with_infinities" => Float32[Inf, 1, -Inf],
                                 "flag" => [true, false, true], "name" => ["é", "", "a b"],
                                 "position" => [1.0 2.0 3.0; 4.0 5.0 6.0; 7.0 8.0 9.0])
        for T in encoding3d.COLUMN_TYPES
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
        for T in encoding3d.COLUMN_TYPES
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

    @testset "coupling" begin
        # a partial frame: its sender and removed entities kept
        frame = Frame(data_structures = [DataStructure("plant"; entity_sets = [
                          EntitySet("SubOrgan"; rank = 6, columns = encoding3d.Columns(
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
        value = encoding3d.declaration_json(declaration)
        @test [item["name"] for item in value["entitySets"]] == ["SubOrgan", "Organ"]
        @test value["entitySets"][1]["rank"] == 6 && value["entitySets"][2]["rights"] == "follows"
        @test value["variables"][1]["standardName"] == "length"
        # the folder transport: a participant's queues, a message and its payload
        folder = mktempdir()
        participant = encoding3d.FolderChannel(folder, "function")
        encoding3d.send_message(participant, Dict("type" => "update", "step" => 0), to_bytes(frame))
        coordinator = encoding3d.FolderChannel(joinpath(folder, "function", "to_coordinator"), mktempdir(), 0, 0)
        header, payload = encoding3d.receive_message(coordinator, 5)
        @test header["type"] == "update" && from_bytes(payload).update.participant == "vpl"
        @test isfile(joinpath(folder, "function", "to_coordinator", "00000000.glb"))
        @test_throws ErrorException encoding3d.receive_message(coordinator, 0.05)          # nothing more: a timeout
    end
end
