# Sequences: a folder of frames (one GLB each), the shared parts they use (parts/<key>.glb) and their index,
# scene.fspm.json; or the same packed into an archive (x.fspm.zip).

const INDEX_FILE = "scene.fspm.json"

"""
    write_index(path, entries; time_unit="d", parts=String[])

Write the index of a sequence: `entries`, one `(time, step, file)` per frame (a NamedTuple or a dictionary), in time
order; `parts`: the keys of the parts its frames use (listed as parts/<key>.glb).
"""
function write_index(path::AbstractString, entries; time_unit::AbstractString = "d", parts = String[])
    field(entry, name) = entry isa NamedTuple ? getproperty(entry, name) : entry[string(name)]
    frames = [json_object("time" => Float64(field(entry, :time)), "step" => Int(field(entry, :step)),
                          "file" => String(field(entry, :file))) for entry in entries]
    index = json_object("fspmIndex" => SPECIFICATION_VERSION, "timeUnit" => time_unit, "frames" => frames)
    isempty(parts) || (index["parts"] = json_object(key => "$PARTS_FOLDER/$key.glb" for key in sort(unique(parts))))
    open(path, "w") do io
        JSON.json(io, index; pretty = 1)
        write(io, "\n")
    end
    return path
end

"""
    write_sequence(directory, frames; name="frame") -> String

Write `frames` to `directory`, one GLB each (`name_000000.glb`, ...), their parts (parts/<key>.glb), and their index;
the index's path.
"""
function write_sequence(directory::AbstractString, frames; name::AbstractString = "frame")
    mkpath(directory)
    entries, time_units, keys_used = NamedTuple[], Set{String}(), Set{String}()
    for (number, frame) in enumerate(frames)
        file = string(name, "_", lpad(number - 1, 6, '0'), ".glb")
        union!(keys_used, write_frame(joinpath(directory, file), frame))
        push!(entries, (time = frame.time, step = frame.step, file = file))
        push!(time_units, frame.time_unit)
    end
    length(time_units) > 1 &&
        throw(ArgumentError("the frames' times are in several units: $(sort(collect(time_units)))"))
    path = joinpath(directory, INDEX_FILE)
    write_index(path, entries; time_unit = isempty(time_units) ? "d" : first(time_units), parts = collect(keys_used))
    return path
end

"""
    read_index(path) -> JSON.Object

The index of a sequence (its file, its folder, or an archive x.fspm.zip): its frames' times, steps and files, each
frame with the absolute `"path"` of its file, and its `"parts"` when listed.
"""
function read_index(path::AbstractString)
    if isdir(path) || (endswith(path, ARCHIVE_SUFFIX) && isfile(path))
        path = joinpath(path, INDEX_FILE)                   # a folder's index, or an archive's
    end
    index = JSON.parse(String(read_file_bytes(path)))
    directory = dirname(abspath(path))
    for entry in get(index, "frames", Any[])
        entry["path"] = joinpath(directory, entry["file"])
    end
    return index
end

"""
    read_sequence(path)

The frames of the sequence whose index is `path`, read one after the other as they are iterated.
"""
read_sequence(path::AbstractString) = (read_frame(entry["path"]) for entry in read_index(path)["frames"])
