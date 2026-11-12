# Archives (specification §8.2): a sequence packed into one .fspm.zip file, a ZIP archive (ZIP64 when it needs to be)
# whose members are the folder's files, each compressed alone (stored, deflate or lzma, ZIP's methods 0, 8 and 14). A
# file inside an archive is named "<archive>.fspm.zip/<member>"; `read_file_bytes` and `file_exists` read such paths as
# they read a folder's files. ZIP through ZipArchives.jl (its ZIP64 records, stored and deflate); lzma members through
# liblzma (XZ_jll), its raw LZMA1 decoder.

"""The end of an archive's name."""
const ARCHIVE_SUFFIX = ".fspm.zip"
const ZIP_LZMA = 14
const LZMA_END_MARKER = 0x0002                  # an lzma member's flag: its data ends with LZMA's end of payload marker
const LZMA_FILTER_LZMA1 = 0x4000000000000001
const LZMA_VLI_UNKNOWN = typemax(UInt64)

# (archive, member) when `path` is a file inside an archive ("x.fspm.zip/frame_000000.glb"), or an archive itself (its
# index); nothing otherwise.
function split_archive(path::AbstractString)
    normalised = replace(String(path), '\\' => '/')
    endswith(normalised, ARCHIVE_SUFFIX) && isfile(path) && return (String(path), INDEX_FILE)
    position = findfirst(ARCHIVE_SUFFIX * "/", normalised)
    while position !== nothing
        archive = normalised[1:last(position)-1]
        if isfile(archive)
            parts = String[]
            for part in split(normalised[last(position)+1:end], '/')
                part == ".." && throw(ArgumentError("member '$normalised': no '..' in an archive's paths"))
                part in ("", ".") || push!(parts, part)
            end
            return (archive, join(parts, "/"))
        end
        position = findnext(ARCHIVE_SUFFIX * "/", normalised, last(position))
    end
    return nothing
end

# The archives last opened: archive => (its modification time and size, its ZipReader on the mapped file)
const OPEN_ARCHIVES = OrderedDict{String,Tuple{Tuple{Float64,Int},Any}}()
const KEPT_OPEN = 4

function archive_reader(archive::AbstractString)
    status = stat(archive)
    stamp = (status.mtime, Int(status.size))
    known = get(OPEN_ARCHIVES, archive, nothing)
    known !== nothing && known[1] == stamp && return known[2]
    while length(OPEN_ARCHIVES) >= KEPT_OPEN
        delete!(OPEN_ARCHIVES, first(keys(OPEN_ARCHIVES)))
    end
    reader = ZipArchives.ZipReader(open(Mmap.mmap, archive))
    OPEN_ARCHIVES[String(archive)] = (stamp, reader)
    return reader
end

"""
    read_file_bytes(path) -> Vector{UInt8}

The bytes of the file `path`, in a folder or in an archive ("x.fspm.zip/member").
"""
function read_file_bytes(path::AbstractString)
    inside = split_archive(path)
    inside === nothing && return read(path)
    archive, member = inside
    reader = archive_reader(archive)
    entry = ZipArchives.zip_findlast_entry(reader, member)
    entry === nothing && throw(ArgumentError("$archive holds no '$member'"))
    ZipArchives.zip_compression_method(reader, entry) == ZIP_LZMA || return ZipArchives.zip_readentry(reader, entry)
    start = ZipArchives.zip_entry_data_offset(reader, entry)
    compressed = view(parent(reader), start+1:start+ZipArchives.zip_compressed_size(reader, entry))
    data = lzma_member(compressed, Int(ZipArchives.zip_uncompressed_size(reader, entry)),
                       ZipArchives.zip_general_purpose_bit_flag(reader, entry) & LZMA_END_MARKER != 0)
    ZipArchives.zip_crc32(data) == ZipArchives.zip_stored_crc32(reader, entry) ||
        throw(ArgumentError("'$member' in $archive is corrupt (its CRC-32 differs)"))
    return data
end

struct LzmaFilter               # liblzma's lzma_filter: a filter's id and its options
    id::UInt64
    options::Ptr{Cvoid}
end

# An lzma member's data: ZIP's LZMA header (version, the properties' size, the 5 bytes of properties), then raw LZMA1
# data, decoded by liblzma in one call to `size` bytes (up to its end marker when it has one).
function lzma_member(compressed::AbstractVector{UInt8}, size::Int, has_end_marker::Bool)
    length(compressed) >= 9 && compressed[3] == 0x05 && compressed[4] == 0x00 ||
        throw(ArgumentError("an lzma member: LZMA properties of 5 bytes expected"))
    properties = Vector{UInt8}(compressed[5:9])
    payload = Vector{UInt8}(compressed[10:end])
    filters = [LzmaFilter(LZMA_FILTER_LZMA1, C_NULL), LzmaFilter(LZMA_VLI_UNKNOWN, C_NULL)]
    out = Vector{UInt8}(undef, size)
    GC.@preserve filters properties payload out begin
        status = ccall((:lzma_properties_decode, XZ_jll.liblzma), Cint, (Ptr{LzmaFilter}, Ptr{Cvoid}, Ptr{UInt8}, Csize_t),
                       pointer(filters), C_NULL, properties, length(properties))
        status == 0 || throw(ArgumentError("an lzma member: its properties are not LZMA1's (liblzma: $status)"))
        input_position, output_position = Ref{Csize_t}(0), Ref{Csize_t}(0)
        status = ccall((:lzma_raw_buffer_decode, XZ_jll.liblzma), Cint,
                       (Ptr{LzmaFilter}, Ptr{Cvoid}, Ptr{UInt8}, Ref{Csize_t}, Csize_t, Ptr{UInt8}, Ref{Csize_t}, Csize_t),
                       pointer(filters), C_NULL, payload, input_position, length(payload), out, output_position, size)
        Libc.free(filters[1].options)
    end
    # liblzma: 0 done (its end marker read); 10 the output full before any end marker (one without)
    complete = status == 0 || (status == 10 && !has_end_marker)
    complete && output_position[] == size ||
        throw(ArgumentError("an lzma member: its data does not decode to $size bytes (liblzma: $status)"))
    return out
end

"""
    file_exists(path) -> Bool

Whether the file `path` exists, in a folder or in an archive.
"""
function file_exists(path::AbstractString)
    inside = split_archive(path)
    inside === nothing && return isfile(path)
    return ZipArchives.zip_findlast_entry(archive_reader(inside[1]), inside[2]) !== nothing
end

# The keys of the parts a frame file's instance sets use (its JSON chunk only).
function file_part_keys(path::AbstractString)
    document, _ = unpack(read_file_bytes(path))
    scene = get(get(document, "extensions", json_object()), EXTENSION, json_object())
    return Set{String}(String(key) for data_structure in get(scene, "dataStructures", Any[])
                       for instance_set in get(data_structure, "instanceSets", Any[])
                       for key in get(instance_set, "parts", Any[]))
end

"""
    pack_archive(folder, path; compression="deflate") -> String

Packs the sequence of `folder` (a folder, or its index) into the archive `path` (x.fspm.zip, ZIP64 when needed): its
index, views.json, its frames and the parts they use, unchanged, each compressed alone (`compression`: "deflate" or
"stored"). Returns `path`.
"""
function pack_archive(folder::AbstractString, path::AbstractString; compression::AbstractString = "deflate")
    compression in ("deflate", "stored") ||
        throw(ArgumentError("compression '$compression': deflate or stored (lzma: read only, in Julia)"))
    endswith(path, ARCHIVE_SUFFIX) || throw(ArgumentError("'$path': an archive's name ends in $ARCHIVE_SUFFIX"))
    index_path = isdir(folder) ? joinpath(folder, INDEX_FILE) : folder
    base = dirname(abspath(index_path))
    index = read_index(index_path)
    members = String[INDEX_FILE]
    isfile(joinpath(base, "views.json")) && push!(members, "views.json")
    keys_used = Set{String}(String.(collect(keys(get(index, "parts", json_object())))))
    for entry in index["frames"]
        push!(members, entry["file"])
        union!(keys_used, file_part_keys(entry["path"]))
    end
    append!(members, ["$PARTS_FOLDER/$key.glb" for key in sort(collect(keys_used))])
    for member in members
        isfile(joinpath(base, member)) && continue
        startswith(member, "$PARTS_FOLDER/") &&
            throw(MissingPartError(member[length(PARTS_FOLDER)+2:end-4], [joinpath(base, member)]))
        throw(ArgumentError("$(joinpath(base, member)) does not exist"))
    end
    temporary = path * ".part"
    ZipArchives.ZipWriter(temporary) do writer
        for member in members
            ZipArchives.zip_newfile(writer, member; compress = compression == "deflate")
            write(writer, read(joinpath(base, member)))
            ZipArchives.zip_commitfile(writer)
        end
    end
    mv(temporary, path; force = true)
    return path
end
