# A frame as plain JSON values, in the layout of the conformance files' expected values (conformance/README.md):
# every table's columns as lists, NaN as null, ±Inf as "Infinity" / "-Infinity", positions as their Float32 values.

json_value(value::AbstractFloat) =
    isnan(value) ? nothing : isinf(value) ? (value > 0 ? "Infinity" : "-Infinity") : Float64(value)
json_value(::Missing) = nothing
json_value(value) = value

json_column(column::AbstractVector) = [json_value(value) for value in column]
json_column(column::AbstractMatrix) = [[json_value(value) for value in row] for row in eachrow(column)]

"""The name of a column's type in the expected values: numpy's (`float64`, `int64`, `uint8`, `bool`...), or
`string`."""
function dtype_name(column::AbstractArray)
    element = nonmissingtype(eltype(column))
    return element <: AbstractString ? "string" : lowercase(string(element))
end

function table_dict(table::AbstractTable)
    entry = json_object("name" => table.name, "count" => row_count(table),
                        "columns" => json_object(name => json_object("dtype" => dtype_name(column),
                                                                     "values" => json_column(column))
                                                 for (name, column) in table.columns))
    declarations = json_object()
    for (name, variable) in table.variables
        declared = json_object("unit" => variable.unit, "role" => variable.role)
        variable.standard_name === nothing || (declared["standard_name"] = variable.standard_name)
        variable.kind === nothing || (declared["kind"] = variable.kind)
        variable.description === nothing || (declared["description"] = variable.description)
        variable.minimum === nothing || (declared["minimum"] = variable.minimum)
        variable.maximum === nothing || (declared["maximum"] = variable.maximum)
        isempty(variable.references) || (declared["references"] = variable.references)
        isempty(variable.doi) || (declared["doi"] = variable.doi)
        variable.format === nothing || (declared["format"] = variable.format)
        declarations[name] = declared
    end
    isempty(declarations) || (entry["variables"] = declarations)
    return entry
end

"""
    frame_to_dict(frame) -> OrderedDict

`frame` as plain JSON values, in the layout of the conformance files' expected values.
"""
function frame_to_dict(frame::Frame)
    data_structures = Any[]
    for data_structure in frame.data_structures
        entry = json_object("id" => data_structure.id, "kind" => data_structure.kind,
                            "origin" => [collect(row) for row in eachrow(data_structure.origin)],
                            "entity_sets" => [merge!(table_dict(set), json_object("rank" => set.rank),
                                                     set.scale === nothing ? json_object() :
                                                     json_object("scale" => set.scale))
                                              for set in data_structure.entity_sets])
        data_structure.platform === nothing || (entry["platform"] = data_structure.platform)
        data_structure.model === nothing || (entry["model"] = data_structure.model)
        isempty(data_structure.extras) || (entry["extras"] = data_structure.extras)
        isempty(data_structure.labels) || (entry["labels"] = data_structure.labels)
        if !isempty(data_structure.relations)
            entry["relations"] = [merge!(table_dict(relation), json_object("source_set" => relation.source_set,
                                                                           "target_set" => relation.target_set))
                                  for relation in data_structure.relations]
        end
        data_structure.scalars === nothing || (entry["scalars"] = table_dict(data_structure.scalars))
        if data_structure.grid !== nothing
            grid = data_structure.grid
            entry["grid"] = json_object("kind" => grid.kind, "shape" => grid.shape, "origin" => grid.origin,
                                        "spacing" => grid.spacing, "axes" => grid.axes, "periodic" => grid.periodic,
                                        "z_up" => grid.z_up, "max_level" => grid.max_level, "cells" => grid.cells)
        end
        if !isempty(data_structure.meshes)
            entry["meshes"] = map(data_structure.meshes) do mesh
                item = json_object("name" => mesh.name,
                                   "positions_float32" => json_column(Float64.(Float32.(mesh.positions))),
                                   "feature_rows" => json_object(name => rows for (name, rows) in mesh.feature_rows))
                mesh.indices === nothing || (item["indices"] = mesh.indices)
                isempty(mesh.display) || (item["display"] = json_object(name => json_column(Float64.(values))
                                                                        for (name, values) in mesh.display))
                item
            end
        end
        push!(data_structures, entry)
    end
    mappings = [merge!(table_dict(mapping), json_object("source" => collect(mapping.source),
                                                        "target" => collect(mapping.target),
                                                        "method" => mapping.method))
                for mapping in frame.mappings]
    out = json_object("time" => frame.time, "time_unit" => frame.time_unit, "step" => frame.step,
                      "data_structures" => data_structures, "mappings" => mappings)
    if frame.update !== nothing                       # a partial frame: its sender and removed entities, sorted
        out["update"] = json_object("participant" => frame.update.participant,
            "removed" => Any[json_object("data_structure" => key[1], "entity_set" => key[2], "ids" => ids)
                             for (key, ids) in sort(collect(frame.update.removed); by = first)])
    end
    return out
end

"""
    write_dump(path, frame)

Write `frame` as JSON in the layout of the conformance files' expected values, for `encoding3d compare`.
"""
function write_dump(path::AbstractString, frame::Frame)
    open(path, "w") do io
        JSON.json(io, frame_to_dict(frame))
    end
    return path
end
