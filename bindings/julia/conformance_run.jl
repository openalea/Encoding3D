# The Julia codec's run of the conformance check, as every codec does it in its CI: read each conformance GLB and dump
# it as JSON (OUT/dumps/x.json for x.glb), and write the conformance scenes again as GLB files (OUT/written/x.glb).
# The instances (0.4, conformance/README.md): each frame's derived fields evaluated too (OUT/dumps/instances/
# x.evaluated.json), each part dumped (OUT/dumps/instances/parts/<key>.json), each frame of each archive dumped and
# evaluated (OUT/dumps/archives/<name>/frame_n.json); the instances written again with their parts encoded by this
# codec, as a sequence with its index (OUT/written/instances), and packed (OUT/written/archives/instances.fspm.zip).
# Then .github/actions/conformance compares the dumps with the expected values and validates the written files.
#
#     julia --project=bindings/julia/encoding3d bindings/julia/conformance_run.jl CONFORMANCE OUT

using encoding3d
using JSON

function dump_json(path::AbstractString, value)
    mkpath(dirname(path))
    open(io -> JSON.json(io, value), path, "w")
end

"""{"<data structure>/<instance set>/<field>": one list of values per instance} of every derived field of a frame."""
evaluated(frame::Frame) =
    Dict("$(data_structure.id)/$(instance_set.name)/$(derived.name)" =>
         [[isnan(value) ? nothing : value for value in values]
          for values in evaluate(frame, derived.name; data_structure = data_structure.id,
                                 instance_set = instance_set.name)]
         for data_structure in frame.data_structures for instance_set in data_structure.instance_sets
         for derived in instance_set.derived)

"""The frame with each part of its instance sets decoded and encoded again by this codec (new keys)."""
function with_parts_encoded_again(frame::Frame)
    copy = from_bytes(to_bytes(frame); parts_folder = frame.parts_folder)
    for data_structure in copy.data_structures, instance_set in data_structure.instance_sets
        instance_set.parts = [add_part!(copy, frame_part(frame, key)) for key in instance_set.parts]
    end
    return copy
end

function main(conformance::AbstractString, out::AbstractString)
    instances_frames, instances_parts = NamedTuple[], Set{String}()
    for (folder, _, files) in walkdir(conformance)
        top = first(splitpath(relpath(folder, conformance)))
        top in ("coupling", "archives") && continue             # the sessions: their own run; archives: below
        for name in sort(files)
            endswith(name, ".glb") || continue
            relative = relpath(joinpath(folder, name), conformance)
            dump = joinpath(out, "dumps", relative[1:end-length(".glb")] * ".json")
            if top == "instances" && basename(folder) == "parts"
                dump_json(dump, part_to_dict(read_part(read(joinpath(folder, name)); key = name[1:end-length(".glb")])))
                continue
            end
            frame = read_frame(joinpath(conformance, relative))
            mkpath(dirname(dump))
            write_dump(dump, frame)
            written = joinpath(out, "written", relative)
            mkpath(dirname(written))
            if top != "instances"
                write_frame(written, frame)                     # written again from what was read
                continue
            end
            dump_json(dump[1:end-length(".json")] * ".evaluated.json", evaluated(frame))
            embedded = name == "embedded.glb"
            keys_used = write_frame(written, with_parts_encoded_again(frame); embed_parts = embedded)
            if !embedded
                push!(instances_frames, (time = frame.time, step = frame.step, file = name))
                union!(instances_parts, keys_used)
            end
        end
    end
    index = joinpath(conformance, "growing_sequence", "scene.fspm.json")
    isfile(index) && cp(index, joinpath(out, "written", "growing_sequence", "scene.fspm.json"); force = true)
    archives = joinpath(conformance, "archives")
    for name in (isdir(archives) ? sort(readdir(archives)) : String[])
        endswith(name, ARCHIVE_SUFFIX) || continue
        stem = name[1:end-length(ARCHIVE_SUFFIX)]
        for entry in read_index(joinpath(archives, name))["frames"]
            frame = read_frame(entry["path"])                   # x.fspm.zip/frame_n.glb
            base = joinpath(out, "dumps", "archives", stem, entry["file"][1:end-length(".glb")])
            mkpath(dirname(base))
            write_dump(base * ".json", frame)
            dump_json(base * ".evaluated.json", evaluated(frame))
        end
    end
    if !isempty(instances_frames)                               # the instances again as a sequence, then packed
        folder = joinpath(out, "written", "instances")
        write_index(joinpath(folder, "scene.fspm.json"), sort(instances_frames; by = entry -> entry.time);
                    time_unit = "d", parts = collect(instances_parts))
        mkpath(joinpath(out, "written", "archives"))
        pack_archive(folder, joinpath(out, "written", "archives", "instances" * ARCHIVE_SUFFIX))
    end
    return 0
end

main(ARGS[1], ARGS[2])
