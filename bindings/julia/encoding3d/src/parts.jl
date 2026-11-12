# Shared parts (specification §12.1): their content key (the SHA-256 of their GLB bytes), their GLB files (a template as
# a frame of its data structure, an operator as a frame of no data structure, its arrays in the binary chunk,
# FSPM_scene.part saying which), where a frame finds them (embedded, else parts/<key>.glb next to it), and derived
# fields evaluated from them (§12.3).

"""The folder of a sequence's parts, next to its frames."""
const PARTS_FOLDER = "parts"

"""
    content_key(data) -> String

A part's key: the SHA-256 of its GLB bytes, in lower-case hexadecimal.
"""
content_key(data::AbstractVector{UInt8}) = bytes2hex(SHA.sha256(data))

"""
    part_to_bytes(part) -> Vector{UInt8}

The GLB file of a shared part (a `Template` or an `Operator`).
"""
function part_to_bytes(part::Template)
    source = part.data_structure
    sets = map(source.entity_sets) do set                   # an entity set without ids: its rows
        (haskey(set.columns, "id") || isempty(set.columns)) && return set
        columns = Columns("id" => collect(Int64, 0:row_count(set)-1))
        merge!(columns, set.columns)
        EntitySet(set.name, columns, set.variables, set.rank, set.scale)
    end
    held = DataStructure(source.id; kind = source.kind, entity_sets = sets, relations = source.relations,
                         meshes = source.meshes, labels = source.labels, extras = source.extras)
    return encode_frame(Frame(data_structures = [held]); part_entry = buffers -> json_object("kind" => "template"))
end
function part_to_bytes(part::Operator)
    sparse(matrix, buffers) = json_object("indptr" => add!(buffers, matrix.indptr),
                                          "indices" => add!(buffers, matrix.indices),
                                          "values" => add!(buffers, matrix.values))
    return encode_frame(Frame(); part_entry = function (buffers)
        entry = json_object("kind" => "operator", "format" => part.format, "rows" => part.rows,
                            "columns" => part.columns)
        if part.format == "dense"
            entry["values"] = add!(buffers, vec(permutedims(part.values)))       # row by row
        elseif part.format == "csr"
            merge!(entry, sparse(part.sparse, buffers))
        elseif part.format == "solve"
            entry["system"] = sparse(part.system, buffers)
            entry["rightHandSide"] = sparse(part.right_hand_side, buffers)
        else
            throw(ArgumentError("operator format '$(part.format)': dense, csr or solve"))
        end
        entry
    end)
end

"""
    read_part(data; key=nothing) -> Template | Operator

The part of a part's GLB bytes; `key`, when given, checked against the bytes' hash.
"""
function read_part(data::AbstractVector{UInt8}; key::Union{Nothing,AbstractString} = nothing)
    actual = content_key(data)
    key === nothing || key == actual ||
        throw(ArgumentError("part $key: its bytes hash to $actual (the file is not the part its name says)"))
    document, binary = unpack(data)
    described = get(get(get(document, "extensions", json_object()), EXTENSION, json_object()), "part", nothing)
    described === nothing && throw(ArgumentError("part $actual: not a part (no $EXTENSION.part)"))
    kind = get(described, "kind", "")
    if kind == "template"
        frame = from_bytes(data)
        length(frame.data_structures) == 1 || throw(ArgumentError("part $actual: a template holds one data structure"))
        return Template(frame.data_structures[1])
    end
    kind == "operator" || throw(ArgumentError("part $actual: kind '$kind' is not template or operator"))
    function array(::Type{T}, index) where {T}
        bytes = view_bytes(document, binary, index)
        return read_values(T, bytes, length(bytes) ÷ sizeof(T))
    end
    sparse(item) = CompressedRows(array(Int64, item["indptr"]), array(Int64, item["indices"]),
                                  array(Float64, item["values"]))
    rows, columns, format = Int(described["rows"]), Int(described["columns"]), described["format"]
    format == "dense" && return dense_operator(permutedims(reshape(array(Float64, described["values"]), columns, rows)))
    format == "csr" && return sparse_operator(rows, columns, sparse(described))
    format == "solve" && return solve_operator(rows, columns, sparse(described["system"]),
                                               sparse(described["rightHandSide"]))
    throw(ArgumentError("part $actual: operator format '$format' is not dense, csr or solve"))
end

"""
    add_part!(frame, part) -> String

Encodes `part` into the frame's `part_bytes`; its key, for an instance set's parts.
"""
function add_part!(frame::Frame, part::Part)
    bytes = part_to_bytes(part)
    key = content_key(bytes)
    haskey(frame.part_bytes, key) || (frame.part_bytes[key] = bytes)
    return key
end

"""
    frame_part_bytes(frame, key) -> Vector{UInt8}

The GLB bytes of the part `key` of a frame: embedded or added, else at parts/<key>.glb under its `parts_folder`; a
`MissingPartError` when it is nowhere.
"""
function frame_part_bytes(frame::Frame, key::AbstractString)
    haskey(frame.part_bytes, key) && return frame.part_bytes[key]
    looked = isempty(frame.part_bytes) ? String[] : ["the frame (embedded)"]
    if frame.parts_folder !== nothing
        path = joinpath(frame.parts_folder, PARTS_FOLDER, "$key.glb")
        file_exists(path) && return read_file_bytes(path)
        push!(looked, path)
    end
    throw(MissingPartError(String(key), looked))
end

"""
    frame_part(frame, key) -> Template | Operator

The part `key` of a frame, decoded.
"""
frame_part(frame::Frame, key::AbstractString) = read_part(frame_part_bytes(frame, key); key)

compressed_matrix(matrix::CompressedRows, rows::Integer, columns::Integer) =
    SparseArrays.sparse(Int[row for row in 1:rows for _ in matrix.indptr[row]+1:matrix.indptr[row+1]],
                        matrix.indices .+ 1, matrix.values, rows, columns)

"""
    evaluate(frame, field; data_structure=nothing, instance_set=nothing, rows=nothing) -> Vector{Vector{Float64}}

The derived field `field` evaluated for the instances at `rows` (1-based; all when `nothing`) of the instance set
holding it (in `data_structure` and named `instance_set` when given, if several have one of that name): one vector
each, on the rows of the field's entity set in the instance's template, Σ_k w_k (A_k v + b_k) over its terms whose
operator is not `NO_ID`; NaN for an instance without any. Its parts are found through the frame (`frame_part`); a
`solve` operator is factorised once (sparse LU).
"""
function evaluate(frame::Frame, field::AbstractString; data_structure = nothing, instance_set = nothing, rows = nothing)
    found = [set for candidate in frame.data_structures if data_structure === nothing || candidate.id == data_structure
             for set in candidate.instance_sets if (instance_set === nothing || set.name == instance_set) &&
                 any(derived -> derived.name == field, set.derived)]
    isempty(found) && throw(KeyError("the frame has no instance set with the derived field '$field'"))
    length(found) > 1 && throw(ArgumentError("several instance sets with the derived field '$field': name the data " *
                                             "structure or the instance set"))
    holder = only(found)
    derived = only(filter(item -> item.name == field, holder.derived))
    templates = holder.columns["template"]
    input = holder.vectors[derived.input]
    starts = offsets(input)
    decoded = Dict{Int,Any}()
    function part_at(index)
        0 <= index < length(holder.parts) ||
            throw(ArgumentError("'$(holder.name)': part $index outside its parts"))
        get!(decoded, index) do
            part = frame_part(frame, holder.parts[index+1])
            part isa Operator || return part
            part.format == "dense" && return (part, part.values)
            part.format == "csr" && return (part, compressed_matrix(part.sparse, part.rows, part.columns))
            return (part, (LinearAlgebra.lu(compressed_matrix(part.system, part.rows, part.rows)),
                           compressed_matrix(part.right_hand_side, part.rows, part.columns)))
        end
    end
    out = Vector{Vector{Float64}}()
    for row in (rows === nothing ? (1:row_count(holder)) : rows)
        1 <= row <= row_count(holder) || throw(BoundsError(templates, row))
        template = part_at(templates[row])
        template isa Template ||
            throw(ArgumentError("'$(holder.name)': part $(templates[row]) is not a template"))
        size = row_count(entity_set(template, derived.entity_set))
        result = fill(NaN, size)
        vector = input.values[starts[row]+1:starts[row+1]]
        started = false
        for term in 1:terms(derived)
            operator_index = derived.operators[row, term]
            operator_index == NO_ID && continue
            decoded_operator = part_at(operator_index)
            decoded_operator isa Tuple ||
                throw(ArgumentError("'$(holder.name)': part $operator_index is not an operator"))
            operator, matrix = decoded_operator
            length(vector) == operator.columns ||
                throw(ArgumentError("'$(holder.name)' instance $row: $(length(vector)) values of '$(derived.input)', " *
                                    "its operator takes $(operator.columns)"))
            operator.rows == size ||
                throw(ArgumentError("'$(holder.name)' instance $row: operator $operator_index has $(operator.rows) " *
                                    "rows, its template's '$(derived.entity_set)' $size"))
            weight = derived.weights[row, term]
            values = (matrix isa Tuple ? matrix[1] \ Vector(matrix[2] * vector) : matrix * vector) .* weight
            offset_name = derived.offsets[term]
            if offset_name !== nothing
                offset = holder.vectors[offset_name][row]
                if !isempty(offset)
                    length(offset) == size ||
                        throw(ArgumentError("'$(holder.name)' instance $row: offset '$offset_name' has " *
                                            "$(length(offset)) values, $size expected"))
                    values = values .+ weight .* offset
                end
            end
            result = started ? result .+ values : Vector{Float64}(values)
            started = true
        end
        push!(out, result)
    end
    return out
end
