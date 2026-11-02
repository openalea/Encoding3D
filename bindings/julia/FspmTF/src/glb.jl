# The GLB container: a 12-byte header (magic, version 2, total length), a JSON chunk padded with spaces, a binary
# chunk padded with zeros, each 8-byte aligned (as EXT_structural_metadata requires). Little-endian throughout.

const GLB_MAGIC = 0x46546C67            # "glTF"
const GLB_VERSION = 0x00000002
const JSON_CHUNK = 0x4E4F534A           # "JSON"
const BINARY_CHUNK = 0x004E4942         # "BIN\0"
const ALIGNMENT = 8

padding(length::Integer) = mod(-length, ALIGNMENT)

function write_word!(io::IO, value::UInt32)
    write(io, htol(value))
end

"""
    pack(document, binary) -> Vector{UInt8}

The bytes of a GLB file from its JSON `document` (any value JSON.jl writes) and its `binary` buffer.
"""
function pack(document, binary::AbstractVector{UInt8})
    text = Vector{UInt8}(codeunits(JSON.json(document)))
    append!(text, fill(UInt8(' '), padding(length(text))))
    binary = vcat(binary, zeros(UInt8, padding(length(binary))))
    total = 12 + 8 + length(text) + (isempty(binary) ? 0 : 8 + length(binary))
    io = IOBuffer(sizehint = total)
    write_word!(io, GLB_MAGIC)
    write_word!(io, GLB_VERSION)
    write_word!(io, UInt32(total))
    write_word!(io, UInt32(length(text)))
    write_word!(io, JSON_CHUNK)
    write(io, text)
    if !isempty(binary)
        write_word!(io, UInt32(length(binary)))
        write_word!(io, BINARY_CHUNK)
        write(io, binary)
    end
    return take!(io)
end

read_word(data::AbstractVector{UInt8}, offset::Integer) = ltoh(reinterpret(UInt32, data[offset+1:offset+4])[1])

"""
    unpack(data) -> (document, binary)

The JSON document (a `JSON.Object`, keys in their order) and the binary buffer of a GLB file's bytes.
"""
function unpack(data::AbstractVector{UInt8})
    length(data) < 20 && throw(ArgumentError("not a GLB file: too short"))
    read_word(data, 0) == GLB_MAGIC || throw(ArgumentError("not a GLB file: wrong magic"))
    version = read_word(data, 4)
    version == GLB_VERSION || throw(ArgumentError("GLB version $(Int(version)), 2 expected"))
    total = read_word(data, 8)
    total == length(data) ||
        throw(ArgumentError("GLB header length $(Int(total)), the file holds $(length(data)) bytes"))
    offset, document, binary = 12, nothing, UInt8[]
    while offset < total
        chunk_length, chunk_type = read_word(data, offset), read_word(data, offset + 4)
        chunk = view(data, offset+9:offset+8+Int(chunk_length))
        if chunk_type == JSON_CHUNK
            document = JSON.parse(String(copy(chunk)))
        elseif chunk_type == BINARY_CHUNK
            binary = Vector{UInt8}(chunk)
        end
        offset += 8 + Int(chunk_length)
    end
    document === nothing && throw(ArgumentError("GLB file without a JSON chunk"))
    return document, binary
end

"""
    BufferBuilder()

Appends arrays to one binary buffer, each at an 8-byte aligned offset, and records their buffer views.
"""
mutable struct BufferBuilder
    data::Vector{UInt8}
    views::Vector{OrderedDict{String,Any}}
end
BufferBuilder() = BufferBuilder(UInt8[], OrderedDict{String,Any}[])

little_endian_bytes(values::AbstractArray{T}) where {T<:Union{Number,Bool}} =
    Vector{UInt8}(reinterpret(UInt8, htol.(vec(collect(values)))))

"""
    add!(buffers, data; target=nothing) -> Int

Append `data` (bytes, or an array of numbers written little-endian) to the buffer; the 0-based index of its buffer
view.
"""
function add!(buffers::BufferBuilder, data::AbstractVector{UInt8}; target = nothing)
    append!(buffers.data, zeros(UInt8, padding(length(buffers.data))))
    buffer_view = OrderedDict{String,Any}("buffer" => 0, "byteOffset" => length(buffers.data),
                                          "byteLength" => length(data))
    target === nothing || (buffer_view["target"] = target)
    append!(buffers.data, data)
    push!(buffers.views, buffer_view)
    return length(buffers.views) - 1
end
add!(buffers::BufferBuilder, data::AbstractArray; target = nothing) =
    add!(buffers, little_endian_bytes(data); target = target)

function view_bytes(document, binary::Vector{UInt8}, index::Integer)
    buffer_view = document["bufferViews"][index+1]
    get(buffer_view, "buffer", 0) == 0 ||
        throw(ArgumentError("fspm-TF files keep every buffer view in the GLB binary chunk"))
    start = get(buffer_view, "byteOffset", 0)
    return view(binary, start+1:start+buffer_view["byteLength"])
end

"""The `count` values of type `T` stored little-endian in `bytes` from byte `offset` (0-based)."""
function read_values(::Type{T}, bytes::AbstractVector{UInt8}, count::Integer, offset::Integer = 0) where {T}
    size = sizeof(T)
    length(bytes) >= offset + count * size ||
        throw(ArgumentError("a buffer view holds $(length(bytes)) bytes, $(offset + count * size) needed"))
    return ltoh.(collect(reinterpret(T, bytes[offset+1:offset+count*size])))
end
