# Reading and writing frames as GLB files. Tables are EXT_structural_metadata property tables (one class per table),
# meshes carry EXT_mesh_features feature IDs, and the FSPM_scene root extension holds what these two cannot: data
# structures, entity sets and their ranks, relations, grids, mappings, the frame's time, and the variables' units,
# standard names, kinds and roles.

const EXTENSION = "FSPM_scene"
const METADATA = "EXT_structural_metadata"
const FEATURES = "EXT_mesh_features"
const EDGE_TYPE_ENUM = "FSPM_edge_type"
const IDENTIFIER = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
const ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
const FLOAT, UNSIGNED_INT, UNSIGNED_SHORT, UNSIGNED_BYTE = 5126, 5125, 5123, 5121
const MAX_FLOAT_FEATURE = 2^24                     # feature rows are stored as Float32 vertex attributes
# The scene's frame is z up (metres); glTF viewers expect y up: the root node turns the scene for them (-90° about
# x, column-major). Readers of the tables use the scene's frame, not this node.
const Z_UP_TO_Y_UP = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

const COMPONENT_TYPES = Dict{DataType,String}(T => uppercase(string(T)) for T in COLUMN_TYPES)
const TYPES_OF_COMPONENTS = Dict{String,DataType}(name => T for (T, name) in COMPONENT_TYPES)
# EXT_structural_metadata forbids NaN and infinities: NaN is written as noData, the most negative finite value; +Inf
# and -Inf as the largest finite value and the next one after the most negative, declared in the property's extras
# (FSPM_infinity).
no_data_float(::Type{T}) where {T<:AbstractFloat} = -floatmax(T)
infinity_stand_ins(::Type{T}) where {T<:AbstractFloat} = (positive = floatmax(T), negative = nextfloat(-floatmax(T)))

json_object(pairs...) = OrderedDict{String,Any}(pairs...)

# ── Writing ──────────────────────────────────────────────────────────────

"""
    to_bytes(frame; embed_parts=false) -> Vector{UInt8}

The GLB file of `frame`; `embed_parts`: the parts its instance sets use in it (one self-contained file), else referred
to by key only (`write_frame` writes them to parts/).
"""
to_bytes(frame::Frame; embed_parts::Bool = false) = encode_frame(frame; embed_parts)

# The GLB file of `frame`; `part_entry`, when given: the frame is a part's file, its FSPM_scene.part
# `part_entry(buffers)`.
function encode_frame(frame::Frame; embed_parts::Bool = false, part_entry = nothing)
    buffers = BufferBuilder()
    schema = json_object("id" => "fspm_scene", "classes" => json_object(), "enums" => json_object(
        EDGE_TYPE_ENUM => json_object("valueType" => "UINT8",
                                      "values" => [json_object("name" => name, "value" => value - 1)
                                                   for (value, name) in enumerate(EDGE_TYPES)])))
    tables, variables = Any[], json_object()
    document = json_object("asset" => json_object("version" => "2.0", "generator" => "encoding3d.jl $SPECIFICATION_VERSION"),
                           "scene" => 0, "scenes" => [json_object("nodes" => [0])],
                           "nodes" => Any[json_object("name" => "fspm_scene", "matrix" => Z_UP_TO_Y_UP,
                                                      "children" => Int[])])
    accessors, meshes = Any[], Any[]

    function add_table(table::AbstractTable, class_id::AbstractString)
        check_identifier(class_id, "class")
        properties, stored = encode_table(table, class_id, buffers, schema)
        schema["classes"][class_id] = json_object("name" => table.name, "properties" => properties)
        push!(tables, json_object("name" => table.name, "class" => class_id, "count" => row_count(table),
                                  "properties" => stored))
        declared = json_object(name => declaration_json(table.variables[name])
                               for name in variable_names(table) if haskey(table.variables, name))
        isempty(declared) || (variables[class_id] = declared)
        return length(tables) - 1
    end

    data_structures = Any[]
    for data_structure in frame.data_structures
        check_identifier(data_structure.id, "data structure id")
        entry = json_object("id" => data_structure.id, "kind" => data_structure.kind)
        data_structure.platform === nothing || (entry["platform"] = data_structure.platform)
        data_structure.model === nothing || (entry["model"] = data_structure.model)
        entry["origin"] = vec(data_structure.origin)          # column-major, as glTF matrices
        entry["entitySets"] = map(data_structure.entity_sets) do set
            set_entry = json_object("name" => set.name, "rank" => set.rank)
            set.scale === nothing || (set_entry["scale"] = set.scale)
            set_entry["propertyTable"] = add_table(set, "$(data_structure.id)__$(set.name)")
            set_entry
        end
        if !isempty(data_structure.relations)
            entry["relations"] = [json_object("name" => relation.name, "sourceSet" => relation.source_set,
                                              "targetSet" => relation.target_set,
                                              "propertyTable" => add_table(relation, "$(data_structure.id)__$(relation.name)"))
                                  for relation in data_structure.relations]
        end
        data_structure.scalars === nothing ||
            (entry["scalars"] = add_table(data_structure.scalars, "$(data_structure.id)__scalars"))
        data_structure.grid === nothing || (entry["grid"] = grid_json(data_structure.grid))
        isempty(data_structure.labels) || (entry["labels"] = data_structure.labels)
        isempty(data_structure.extras) || (entry["extras"] = data_structure.extras)
        node = json_object("name" => data_structure.id)
        data_structure.origin == identity_matrix() || (node["matrix"] = entry["origin"])
        push!(document["nodes"], node)
        push!(document["nodes"][1]["children"], length(document["nodes"]) - 1)
        entry["node"] = length(document["nodes"]) - 1
        if !isempty(data_structure.meshes)
            node["children"], entry["meshes"] = Int[], Any[]
            for mesh in data_structure.meshes
                push!(meshes, encode_mesh(mesh, data_structure, entry, buffers, accessors))
                push!(document["nodes"], json_object("name" => mesh.name, "mesh" => length(meshes) - 1))
                push!(node["children"], length(document["nodes"]) - 1)
                mesh_entry = json_object("name" => mesh.name, "mesh" => length(meshes) - 1)
                if !isempty(mesh.display)
                    mesh_entry["display"] = [json_object("attribute" => display_attribute(name), "variable" => name,
                                                         "entitySet" => get(mesh.display_sources, name, nothing))
                                             for name in keys(mesh.display)]
                end
                push!(entry["meshes"], mesh_entry)
            end
        end
        if !isempty(data_structure.instance_sets)
            entry["instanceSets"] = [encode_instance_set(instance_set, data_structure, add_table)
                                     for instance_set in data_structure.instance_sets]
        end
        push!(data_structures, entry)
    end

    mappings = Any[]
    for mapping in frame.mappings
        check_identifier(mapping.name, "mapping name")
        entry = json_object("name" => mapping.name,
                            "source" => json_object("dataStructure" => mapping.source[1], "entitySet" => mapping.source[2]),
                            "target" => json_object("dataStructure" => mapping.target[1], "entitySet" => mapping.target[2]))
        mapping.method === nothing || (entry["method"] = mapping.method)
        entry["propertyTable"] = add_table(mapping, "mapping__$(mapping.name)")
        push!(mappings, entry)
    end

    update = nothing
    if frame.update !== nothing
        check_identifier(frame.update.participant, "participant")
        update = json_object("participant" => frame.update.participant)
        if !isempty(frame.update.removed)
            update["removed"] = Any[json_object("dataStructure" => key[1], "entitySet" => key[2],
                                                "propertyTable" => add_table(Table("$(key[2])__removed";
                                                    columns = Columns("id" => ids)), "$(key[1])__$(key[2])__removed"))
                                    for (key, ids) in frame.update.removed]
        end
    end

    scene = json_object("version" => SPECIFICATION_VERSION,
                        "frame" => json_object("time" => Float64(frame.time), "timeUnit" => frame.time_unit,
                                               "step" => frame.step))
    frame.vocabulary_version === nothing || (scene["vocabulary"] = frame.vocabulary_version)
    isempty(frame.writer) || (scene["writer"] = frame.writer)
    update === nothing || (scene["update"] = update)
    part_entry === nothing || (scene["part"] = part_entry(buffers))
    scene["dataStructures"] = data_structures
    isempty(mappings) || (scene["mappings"] = mappings)
    isempty(variables) || (scene["variables"] = variables)
    keys_used = frame_part_keys(frame)
    if embed_parts && !isempty(keys_used)
        scene["parts"] = json_object(key => json_object("bufferView" => add!(buffers, frame_part_bytes(frame, key)))
                                     for key in keys_used)
    end

    other_extensions = get(frame.unknown, "extensions", json_object())
    extensions = json_object(METADATA => json_object("schema" => schema, "propertyTables" => tables),
                             EXTENSION => scene)
    merge!(extensions, other_extensions)
    document["extensionsUsed"] = vcat([METADATA, EXTENSION], isempty(meshes) ? String[] : [FEATURES],
                                      collect(String, keys(other_extensions)))
    document["extensions"] = extensions
    haskey(frame.unknown, "extras") && (document["extras"] = frame.unknown["extras"])
    if !isempty(meshes)
        document["meshes"], document["accessors"] = meshes, accessors
    end
    if isempty(document["nodes"][1]["children"])   # a part, or a frame of no data structure: glTF has no empty children
        delete!(document["nodes"][1], "children")
    end
    if !isempty(buffers.views)
        # the buffer holds the chunk's padding to 8 bytes: glTF-Validator warns of more than 3 bytes beyond it
        append!(buffers.data, zeros(UInt8, padding(length(buffers.data))))
        document["buffers"] = [json_object("byteLength" => length(buffers.data))]
        document["bufferViews"] = buffers.views
    end
    return pack(document, buffers.data)
end

"""
    write_frame(path, frame; embed_parts=false) -> Vector{String}

Write `frame` to the GLB file `path`, and each part its instance sets use to parts/<key>.glb next to it, when not
there yet (`embed_parts`: into the frame instead); the keys of those parts, sorted.
"""
function write_frame(path::AbstractString, frame::Frame; embed_parts::Bool = false)
    write(path, to_bytes(frame; embed_parts))
    keys_used = frame_part_keys(frame)
    embed_parts && return keys_used
    folder = joinpath(dirname(abspath(path)), PARTS_FOLDER)
    for key in keys_used
        target = joinpath(folder, "$key.glb")
        isfile(target) && continue                         # its name is its hash: its content
        mkpath(folder)
        temporary = "$target.part"
        write(temporary, frame_part_bytes(frame, key))
        mv(temporary, target; force = true)                # a reader never sees half a part
    end
    return keys_used
end

"""The keys of the parts the instance sets of a frame use, sorted."""
frame_part_keys(frame::Frame) =
    sort(unique(String[key for data_structure in frame.data_structures
                       for instance_set in data_structure.instance_sets for key in instance_set.parts]))

# The FSPM_scene entry of an instance set (specification §12.2), its tables added: the instance table (its columns,
# each vector's <name>__count, each derived field's <name>__operator and <name>__weight) and one table per vector (its
# values, the instances' one after the other).
function encode_instance_set(instance_set::InstanceSet, data_structure::DataStructure, add_table)
    check_identifier(instance_set.name, "instance set name")
    where_ = "instance set '$(instance_set.name)' of '$(data_structure.id)'"
    haskey(instance_set.columns, "template") ||
        throw(ArgumentError("$where_: no 'template' column (each instance's index in its parts)"))
    count = row_count(instance_set)
    columns = Columns(instance_set.columns)
    entry = json_object("name" => instance_set.name, "parts" => instance_set.parts)
    instance_set.owners === nothing || (entry["owners"] = instance_set.owners)
    vectors = Any[]
    for (name, ragged) in instance_set.vectors
        check_identifier(name, "vector of $where_")
        offsets(ragged)                                     # its counts checked against its values
        length(ragged) == count ||
            throw(ArgumentError("$where_: vector '$name' has $(length(ragged)) instances, the set $count"))
        columns["$(name)__count"] = ragged.counts
        values = Table(name; columns = Columns("values" => ragged.values))
        push!(vectors, json_object("name" => name, "propertyTable" =>
                                   add_table(values, "$(data_structure.id)__$(instance_set.name)__$name")))
    end
    derived_fields = Any[]
    for derived in instance_set.derived
        check_identifier(derived.name, "derived field of $where_")
        size(derived.operators, 1) == count ||
            throw(ArgumentError("$where_: derived field '$(derived.name)' has $(size(derived.operators, 1)) rows of " *
                                "operators, the set $count instances"))
        haskey(instance_set.vectors, derived.input) ||
            throw(ArgumentError("$where_: derived field '$(derived.name)' applies to vector '$(derived.input)', " *
                                "which the set does not have"))
        single = terms(derived) == 1
        columns["$(derived.name)__operator"] = single ? derived.operators[:, 1] : derived.operators
        columns["$(derived.name)__weight"] = single ? derived.weights[:, 1] : derived.weights
        item = json_object("name" => derived.name, "entitySet" => derived.entity_set, "input" => derived.input,
                           "terms" => terms(derived), "variable" => declaration_json(derived.variable))
        any(offset -> offset !== nothing, derived.offsets) && (item["offsets"] = derived.offsets)
        derived.variable.description === nothing || (item["description"] = derived.variable.description)
        push!(derived_fields, item)
    end
    table = InstanceSet(instance_set.name, columns, instance_set.variables, instance_set.owners, instance_set.parts,
                        OrderedDict{String,Ragged}(), DerivedField[])
    entry["propertyTable"] = add_table(table, "$(data_structure.id)__$(instance_set.name)")
    isempty(vectors) || (entry["vectors"] = vectors)
    isempty(derived_fields) || (entry["derivedFields"] = derived_fields)
    return entry
end

check_identifier(name, what) = (name isa AbstractString && occursin(IDENTIFIER, name)) ||
    throw(ArgumentError("$what '$name' must be an identifier (letters, digits, '_'; not starting with a digit)"))

function declaration_json(variable::Variable)
    declaration = json_object("unit" => variable.unit, "role" => variable.role)
    variable.standard_name === nothing || (declaration["standardName"] = variable.standard_name)
    variable.kind === nothing || (declaration["kind"] = variable.kind)
    variable.minimum === nothing || (declaration["minimum"] = variable.minimum)
    variable.maximum === nothing || (declaration["maximum"] = variable.maximum)
    isempty(variable.references) || (declaration["references"] = variable.references)
    isempty(variable.doi) || (declaration["doi"] = variable.doi)
    variable.format === nothing || (declaration["format"] = variable.format)
    return declaration
end

"""Row-major values of a column: a vector column's rows one after the other."""
row_major(column::AbstractVector) = column
row_major(column::AbstractMatrix) = vec(permutedims(column))

function encode_table(table::AbstractTable, class_id::AbstractString, buffers::BufferBuilder, schema)
    properties, stored = json_object(), json_object()
    reserved_names = reserved(table)
    for (name, column) in table.columns
        check_identifier(name, "column of '$(table.name)'")
        description = declaration(table, name).description
        property = json_object()
        description === nothing || (property["description"] = description)
        element = nonmissingtype(eltype(column))
        has_missing = Missing <: eltype(column) && any(ismissing, column)
        if name in ENUM_COLUMNS && name in reserved_names
            enum_name, codes = enum_codes(name, column, class_id, schema)
            property["type"], property["enumType"] = "ENUM", enum_name
            stored[name] = json_object("values" => add!(buffers, codes))
        elseif element <: AbstractString
            column isa AbstractVector ||
                throw(ArgumentError("column '$name' of '$(table.name)': text vectors are not supported"))
            property["type"] = "STRING"
            if has_missing                                   # missing text: noData, a string the column lacks
                no_data = free_string(column)
                property["noData"] = no_data
                column = String[ismissing(value) ? no_data : value for value in column]
            end
            encoded = [Vector{UInt8}(codeunits(value)) for value in column]
            offsets = vcat(0, cumsum(Int64[length(value) for value in encoded]))
            offset_type = offsets[end] < 2^32 ? UInt32 : UInt64
            stored[name] = json_object("values" => add!(buffers, reduce(vcat, encoded; init = UInt8[])),
                                       "stringOffsets" => add!(buffers, offset_type.(offsets)),
                                       "stringOffsetType" => uppercase(string(offset_type)))
        elseif element === Bool && has_missing           # booleans with missing values: UINT8 0, 1, 255 missing
            column isa AbstractVector ||
                throw(ArgumentError("column '$name' of '$(table.name)': boolean vectors are not supported"))
            property["type"], property["componentType"] = "SCALAR", "UINT8"
            property["noData"] = BOOLEAN_NO_DATA
            property["extras"] = json_object("FSPM_boolean" => true)
            stored[name] = json_object("values" => add!(buffers, UInt8[ismissing(value) ? BOOLEAN_NO_DATA : UInt8(value)
                                                                         for value in column]))
        elseif element === Bool
            column isa AbstractVector ||
                throw(ArgumentError("column '$name' of '$(table.name)': boolean vectors are not supported"))
            property["type"] = "BOOLEAN"
            packed = zeros(UInt8, cld(length(column), 8))
            for (row, value) in enumerate(column)
                value && (packed[(row-1)÷8+1] |= UInt8(1) << ((row - 1) % 8))     # bit order: little
            end
            stored[name] = json_object("values" => add!(buffers, packed))
        else
            haskey(COMPONENT_TYPES, element) ||
                throw(ArgumentError("column '$name' of '$(table.name)': type $element is not supported"))
            property["type"], property["componentType"] = "SCALAR", COMPONENT_TYPES[element]
            if column isa AbstractMatrix
                size(column, 2) >= 2 ||
                    throw(ArgumentError("column '$name' of '$(table.name)': vectors have at least 2 components"))
                property["array"], property["count"] = true, size(column, 2)
            end
            data = column
            if element <: AbstractFloat
                if any(isinf, column)
                    stand_ins = infinity_stand_ins(element)
                    any(value -> value == stand_ins.positive || value == stand_ins.negative, column) &&
                        throw(ArgumentError("column '$name' of '$(table.name)' holds both infinities and the values " *
                                            "standing for them ($stand_ins)"))
                    property["extras"] = json_object("FSPM_infinity" => json_object(
                        "positive" => Float64(stand_ins.positive), "negative" => Float64(stand_ins.negative)))
                    data = map(value -> value == Inf ? stand_ins.positive :
                                        value == -Inf ? stand_ins.negative : value, data)
                end
                if any(isnan, data)
                    no_data = no_data_float(element)
                    any(==(no_data), data) &&
                        throw(ArgumentError("column '$name' of '$(table.name)' holds both NaN and $no_data, the " *
                                            "value standing for NaN"))
                    property["noData"] = Float64(no_data)
                    data = map(value -> isnan(value) ? no_data : value, data)
                end
            elseif name in ("complex", "parent") && name in reserved_names
                property["noData"] = NO_ID
            elseif has_missing                               # missing integers: noData, a value the column lacks
                no_data = free_integer(element, column)
                property["noData"] = no_data
                data = element[ismissing(value) ? no_data : value for value in column]
            end
            stored[name] = json_object("values" => add!(buffers, row_major(data)))
        end
        name == "id" && table isa EntitySet && (property["required"] = true)
        properties[name] = property
    end
    return properties, stored
end

const BOOLEAN_NO_DATA = 0xff     # a boolean column with missing values: UINT8 0, 1, and 255 missing

"""A value of type `T` the column does not hold: its minimum (signed) or maximum (unsigned) first, then inwards."""
function free_integer(::Type{T}, column) where {T<:Integer}
    present = Set(value for value in column if !ismissing(value))
    first, second = T <: Signed ? (typemin(T), typemax(T)) : (typemax(T), typemin(T))
    for candidate in (first, second)
        candidate in present || return candidate
    end
    candidate = first
    while candidate in present                          # at most length(present) steps
        candidate = T <: Signed ? candidate + one(T) : candidate - one(T)
    end
    return candidate
end

"""A string the column does not hold: the empty string first, then NUL characters."""
function free_string(column)
    present = Set(value for value in column if !ismissing(value))
    candidate = ""
    while candidate in present
        candidate *= "\0"
    end
    return candidate
end

function enum_codes(name, column, class_id, schema)
    if name == "edge_type"
        unknown = setdiff(Set(column), Set(EDGE_TYPES))
        isempty(unknown) ||
            throw(ArgumentError("edge_type of '$class_id': unknown values $(sort(collect(unknown))) " *
                                "(allowed: $EDGE_TYPES)"))
        return EDGE_TYPE_ENUM, UInt8[findfirst(==(value), EDGE_TYPES) - 1 for value in column]
    end
    names = sort(unique(column))
    enum_name = "$(class_id)__$name"
    value_type = length(names) <= 256 ? UInt8 : UInt16
    schema["enums"][enum_name] = json_object("valueType" => uppercase(string(value_type)),
                                             "values" => [json_object("name" => label, "value" => code - 1)
                                                          for (code, label) in enumerate(names)])
    code_of = Dict(label => code - 1 for (code, label) in enumerate(names))
    return enum_name, value_type[code_of[value] for value in column]
end

function grid_json(grid::Grid)
    entry = json_object("kind" => grid.kind, "shape" => grid.shape, "origin" => grid.origin, "spacing" => grid.spacing,
                        "axes" => grid.axes, "periodic" => grid.periodic, "zUp" => grid.z_up, "cells" => grid.cells)
    grid.kind == "adaptive" && (entry["maxLevel"] = grid.max_level)
    return entry
end

display_attribute(name::AbstractString) = "_" * uppercase(name)

function encode_mesh(mesh::Mesh, data_structure::DataStructure, entry, buffers::BufferBuilder, accessors)
    function accessor(values, accessor_type, component_type, target; bounds = false)
        buffer_view = add!(buffers, row_major(values); target = target)
        item = json_object("bufferView" => buffer_view, "componentType" => component_type,
                           "count" => size(values, 1), "type" => accessor_type)
        if bounds
            item["min"] = Float64.(vec(minimum(values; dims = 1)))
            item["max"] = Float64.(vec(maximum(values; dims = 1)))
        end
        push!(accessors, item)
        return length(accessors) - 1
    end

    positions = Float32.(mesh.positions)
    attributes = json_object("POSITION" => accessor(positions, "VEC3", FLOAT, ARRAY_BUFFER; bounds = true))
    tables = Dict(set_entry["name"] => set_entry["propertyTable"] for set_entry in entry["entitySets"])
    feature_ids = Any[]
    for (set_index, (set_name, rows)) in enumerate(mesh.feature_rows)
        haskey(tables, set_name) ||
            throw(ArgumentError("mesh '$(mesh.name)': no entity set '$set_name' in '$(data_structure.id)'"))
        count = row_count(entity_set(data_structure, set_name))
        count >= MAX_FLOAT_FEATURE &&
            throw(ArgumentError("mesh '$(mesh.name)': $count entities in '$set_name', feature IDs stop at 2^24"))
        any(row -> row < NO_ID || row >= count, rows) &&
            throw(ArgumentError("mesh '$(mesh.name)': feature rows of '$set_name' outside its $count rows"))
        stored = Float32[row == NO_ID ? count : row for row in rows]          # null: one past the last row
        attributes["_FEATURE_ID_$(set_index - 1)"] = accessor(stored, "SCALAR", FLOAT, ARRAY_BUFFER)
        feature = json_object("featureCount" => length(unique(filter(!=(NO_ID), rows))), "attribute" => set_index - 1,
                              "propertyTable" => tables[set_name], "label" => set_name)
        any(==(NO_ID), rows) && (feature["nullFeatureId"] = count)
        push!(feature_ids, feature)
    end
    for (name, values) in mesh.display
        length(values) == size(positions, 1) ||
            throw(ArgumentError("mesh '$(mesh.name)': display copy '$name' has $(length(values)) values, " *
                                "$(size(positions, 1)) vertices"))
        attributes[display_attribute(name)] = accessor(Float32.(values), "SCALAR", FLOAT, ARRAY_BUFFER)
    end
    primitive = json_object("attributes" => attributes, "mode" => 4)
    mesh.indices === nothing ||
        (primitive["indices"] = accessor(UInt32.(mesh.indices), "SCALAR", UNSIGNED_INT, ELEMENT_ARRAY_BUFFER))
    isempty(feature_ids) || (primitive["extensions"] = json_object(FEATURES => json_object("featureIds" => feature_ids)))
    return json_object("name" => mesh.name, "primitives" => [primitive])
end

# ── Reading ──────────────────────────────────────────────────────────────

"""
    from_bytes(data; parts_folder=nothing) -> Frame

The frame of a GLB file's bytes; `parts_folder`: the folder its parts/ are in (the file's folder).
"""
function from_bytes(data::AbstractVector{UInt8}; parts_folder::Union{Nothing,AbstractString} = nothing)
    document, binary = unpack(data)
    extensions = get(document, "extensions", json_object())
    haskey(extensions, EXTENSION) || throw(ArgumentError("not an encoding3d file: no $EXTENSION extension"))
    scene = extensions[EXTENSION]
    metadata = get(extensions, METADATA, json_object("schema" => json_object(), "propertyTables" => Any[]))
    variables = get(scene, "variables", json_object())

    function table(index, make)
        description = metadata["propertyTables"][index+1]
        columns, declarations = decode_table(document, binary, description, metadata["schema"], variables)
        return make(String(get(description, "name", description["class"])), columns, declarations)
    end

    frame_entry = get(scene, "frame", json_object())
    frame = Frame(time = Float64(get(frame_entry, "time", 0.0)), time_unit = get(frame_entry, "timeUnit", "d"),
                  step = Int(get(frame_entry, "step", 0)), writer = get(scene, "writer", json_object()),
                  vocabulary_version = get(scene, "vocabulary", nothing))
    for entry in get(scene, "dataStructures", Any[])
        origin = haskey(entry, "origin") ? reshape(Float64.(entry["origin"]), 4, 4) : identity_matrix()
        data_structure = DataStructure(entry["id"]; kind = get(entry, "kind", "graph"),
                                       platform = get(entry, "platform", nothing), model = get(entry, "model", nothing),
                                       extras = get(entry, "extras", json_object()), origin = origin,
                                       labels = get(entry, "labels", json_object()))
        for item in get(entry, "entitySets", Any[])
            rank, scale = get(item, "rank", nothing), get(item, "scale", nothing)
            push!(data_structure.entity_sets,
                  table(item["propertyTable"], (name, columns, declarations) ->
                        EntitySet(name, columns, declarations, rank === nothing ? nothing : Int(rank), scale)))
        end
        for item in get(entry, "relations", Any[])
            push!(data_structure.relations,
                  table(item["propertyTable"], (name, columns, declarations) ->
                        Relation(name, columns, declarations, item["sourceSet"], item["targetSet"])))
        end
        haskey(entry, "scalars") && (data_structure.scalars = table(entry["scalars"], Table))
        if haskey(entry, "grid")
            grid = entry["grid"]
            data_structure.grid = Grid(kind = grid["kind"], shape = Int.(grid["shape"]),
                                       origin = Float64.(grid["origin"]), spacing = Float64.(grid["spacing"]),
                                       axes = String.(grid["axes"]), periodic = Bool.(grid["periodic"]),
                                       z_up = get(grid, "zUp", true), max_level = get(grid, "maxLevel", 0),
                                       cells = grid["cells"])
        end
        tables = Dict(item["propertyTable"] => item["name"] for item in get(entry, "entitySets", Any[]))
        for mesh_entry in get(entry, "meshes", Any[])
            push!(data_structure.meshes, decode_mesh(document, binary, mesh_entry, tables))
        end
        for item in get(entry, "instanceSets", Any[])
            push!(data_structure.instance_sets, decode_instance_set(item, table))
        end
        push!(frame.data_structures, data_structure)
    end
    for entry in get(scene, "mappings", Any[])
        source = (entry["source"]["dataStructure"], entry["source"]["entitySet"])
        target = (entry["target"]["dataStructure"], entry["target"]["entitySet"])
        push!(frame.mappings, table(entry["propertyTable"], (name, columns, declarations) ->
                                    Mapping(name, columns, declarations, source, target, get(entry, "method", nothing))))
    end
    if haskey(scene, "update")
        entry = scene["update"]
        frame.update = Update(entry["participant"]; removed = OrderedDict(
            (item["dataStructure"], item["entitySet"]) => Vector{Int64}(table(item["propertyTable"], Table).columns["id"])
            for item in get(entry, "removed", Any[])))
    end
    other_extensions = json_object(name => value for (name, value) in extensions
                                   if !(name in (METADATA, EXTENSION, FEATURES)))
    isempty(other_extensions) || (frame.unknown["extensions"] = other_extensions)
    haskey(document, "extras") && (frame.unknown["extras"] = document["extras"])
    for (key, item) in get(scene, "parts", json_object())          # embedded parts: a self-contained frame
        frame.part_bytes[String(key)] = Vector{UInt8}(view_bytes(document, binary, item["bufferView"]))
    end
    frame.parts_folder = parts_folder === nothing ? nothing : String(parts_folder)
    return frame
end

"""
    read_frame(path) -> Frame

The frame of the GLB file `path`, in a folder or in an archive ("run.fspm.zip/frame_000003.glb"); its parts are found
next to it.
"""
read_frame(path::AbstractString) = from_bytes(read_file_bytes(path); parts_folder = dirname(abspath(path)))

# An instance set (specification §12.2): its own columns, its vectors and derived fields; its parts by key.
function decode_instance_set(item, table)
    instance_set = table(item["propertyTable"], (name, columns, declarations) ->
                         InstanceSet(String(item["name"]), columns, declarations, get(item, "owners", nothing),
                                     String.(get(item, "parts", String[])), OrderedDict{String,Ragged}(),
                                     DerivedField[]))
    where_ = "instance set '$(instance_set.name)'"
    function take_column(name)
        haskey(instance_set.columns, name) || throw(ArgumentError("$where_: no column '$name'"))
        delete!(instance_set.variables, name)
        return pop!(instance_set.columns, name)
    end
    for vector in get(item, "vectors", Any[])
        values = table(vector["propertyTable"], Table).columns["values"]
        instance_set.vectors[String(vector["name"])] =
            Ragged(Vector{Float64}(values), Vector{Int64}(take_column("$(vector["name"])__count")))
    end
    for entry in get(item, "derivedFields", Any[])
        name, term_count = String(entry["name"]), get(entry, "terms", 1)
        operators, weights = take_column("$(name)__operator"), take_column("$(name)__weight")
        declared = get(entry, "variable", json_object())
        variable = Variable(unit = get(declared, "unit", "1"), standard_name = get(declared, "standardName", nothing),
                            kind = get(declared, "kind", nothing), role = get(declared, "role", "state"),
                            description = get(entry, "description", nothing),
                            minimum = get(declared, "minimum", nothing), maximum = get(declared, "maximum", nothing),
                            references = String.(get(declared, "references", String[])),
                            doi = String.(get(declared, "doi", String[])), format = get(declared, "format", nothing))
        offsets = get(entry, "offsets", fill(nothing, term_count))
        size(operators, 2) == term_count == length(offsets) ||
            throw(ArgumentError("$where_: derived field '$name' has not $term_count operators and offsets per instance"))
        push!(instance_set.derived, DerivedField(name; entity_set = entry["entitySet"], input = entry["input"],
                                                 operators, weights, offsets, variable))
    end
    return instance_set
end

function decode_table(document, binary, description, schema, variables)
    class_id = description["class"]
    properties = schema["classes"][class_id]["properties"]
    count = Int(description["count"])
    columns, declarations = Columns(), Declarations()
    for (name, stored) in description["properties"]
        property = properties[name]
        raw = view_bytes(document, binary, stored["values"])
        type = property["type"]
        if type == "ENUM"
            enum = schema["enums"][property["enumType"]]
            codes = read_values(TYPES_OF_COMPONENTS[get(enum, "valueType", "UINT16")], raw, count)
            name_of = Dict(Int(item["value"]) => String(item["name"]) for item in enum["values"])
            column = String[name_of[Int(code)] for code in codes]
        elseif type == "STRING"
            offset_type = TYPES_OF_COMPONENTS[get(stored, "stringOffsetType", "UINT32")]
            offsets = read_values(offset_type, view_bytes(document, binary, stored["stringOffsets"]), count + 1)
            column = String[String(raw[offsets[row]+1:offsets[row+1]]) for row in 1:count]
            if haskey(property, "noData") && any(==(property["noData"]), column)     # missing text
                column = Union{Missing,String}[value == property["noData"] ? missing : value for value in column]
            end
        elseif type == "BOOLEAN"
            column = Bool[(raw[(row-1)÷8+1] >> ((row - 1) % 8)) & 0x01 == 0x01 for row in 1:count]
        elseif type == "SCALAR"
            element = TYPES_OF_COMPONENTS[property["componentType"]]
            vector = get(property, "array", false)
            vector && !haskey(property, "count") &&
                throw(ArgumentError("'$class_id.$name': variable-length arrays are not part of encoding3d 0.1"))
            width = vector ? Int(property["count"]) : 1
            values = read_values(element, raw, count * width)
            if element <: AbstractFloat
                if haskey(property, "noData")
                    no_data = element(property["noData"])
                    values = map(value -> value == no_data ? element(NaN) : value, values)
                end
                infinity = get(get(property, "extras", json_object()), "FSPM_infinity", nothing)
                if infinity !== nothing
                    positive, negative = element(infinity["positive"]), element(infinity["negative"])
                    values = map(value -> value == positive ? element(Inf) :
                                          value == negative ? element(-Inf) : value, values)
                end
            end
            column = vector ? permutedims(reshape(values, width, count)) : values
            if get(get(property, "extras", json_object()), "FSPM_boolean", false)    # booleans with missing values
                no_data = get(property, "noData", BOOLEAN_NO_DATA)
                column = any(==(no_data), column) ?
                    Union{Missing,Bool}[value == no_data ? missing : value == 1 for value in column] :
                    Bool[value == 1 for value in column]
            elseif element <: Integer && !vector && haskey(property, "noData") && !(name in ("complex", "parent")) &&
                   any(==(property["noData"]), column)                              # missing integers
                column = Union{Missing,element}[value == property["noData"] ? missing : value for value in column]
            end
        else
            throw(ArgumentError("'$class_id.$name': property type $type is not part of encoding3d 0.1"))
        end
        columns[name] = column
        declared = get(get(variables, class_id, json_object()), name, nothing)
        if declared !== nothing || haskey(property, "description")
            declared = declared === nothing ? json_object() : declared
            declarations[name] = Variable(unit = get(declared, "unit", "1"),
                                          standard_name = get(declared, "standardName", nothing),
                                          kind = get(declared, "kind", nothing), role = get(declared, "role", "state"),
                                          description = get(property, "description", nothing),
                                          minimum = get(declared, "minimum", nothing),
                                          maximum = get(declared, "maximum", nothing),
                                          references = String.(get(declared, "references", String[])),
                                          doi = String.(get(declared, "doi", String[])),
                                          format = get(declared, "format", nothing))
        end
    end
    return columns, declarations
end

function accessor_values(document, binary, index)
    accessor = document["accessors"][index+1]
    width = Dict("SCALAR" => 1, "VEC2" => 2, "VEC3" => 3, "VEC4" => 4)[accessor["type"]]
    element = Dict(FLOAT => Float32, UNSIGNED_INT => UInt32, UNSIGNED_SHORT => UInt16,
                   UNSIGNED_BYTE => UInt8)[accessor["componentType"]]
    raw = view_bytes(document, binary, accessor["bufferView"])
    buffer_view = document["bufferViews"][accessor["bufferView"]+1]
    item_size = sizeof(element) * width
    stride = get(buffer_view, "byteStride", item_size)
    start = get(accessor, "byteOffset", 0)
    count = Int(accessor["count"])
    values = stride == item_size ? read_values(element, raw, count * width, start) :
             reduce(vcat, [read_values(element, raw, width, start + item * stride) for item in 0:count-1];
                    init = element[])
    return width > 1 ? permutedims(reshape(values, width, count)) : values
end

function decode_mesh(document, binary, mesh_entry, tables)
    primitive = document["meshes"][mesh_entry["mesh"]+1]["primitives"][1]
    attributes = primitive["attributes"]
    positions = Float64.(accessor_values(document, binary, attributes["POSITION"]))
    feature_rows = OrderedDict{String,Vector{Int64}}()
    for feature in get(get(get(primitive, "extensions", json_object()), FEATURES, json_object()), "featureIds", Any[])
        rows = Int64.(accessor_values(document, binary, attributes["_FEATURE_ID_$(feature["attribute"])"]))
        if haskey(feature, "nullFeatureId")
            null = feature["nullFeatureId"]
            rows = Int64[row == null ? NO_ID : row for row in rows]
        end
        feature_rows[tables[feature["propertyTable"]]] = rows
    end
    display, sources = OrderedDict{String,Vector{Float32}}(), Dict{String,String}()
    for item in get(mesh_entry, "display", Any[])
        display[item["variable"]] = accessor_values(document, binary, attributes[item["attribute"]])
        get(item, "entitySet", nothing) === nothing || (sources[item["variable"]] = item["entitySet"])
    end
    indices = haskey(primitive, "indices") ? Int64.(accessor_values(document, binary, primitive["indices"])) : nothing
    return Mesh(mesh_entry["name"]; positions = positions, feature_rows = feature_rows, indices = indices,
                display = display, display_sources = sources)
end
