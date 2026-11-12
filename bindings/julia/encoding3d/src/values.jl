# Values of a platform's objects (attributes, fields) as columns: what the adapters share.

const TextType = Union{Date,DateTime,Time}
"""The format (a variable's `format`) of each type written as ISO 8601 text."""
const FORMAT_OF = Dict{DataType,String}(Date => "date", DateTime => "date-time", Time => "time")
"""Each format's type, to read its text back."""
const TYPE_OF_FORMAT = Dict{String,DataType}(format => type for (type, format) in FORMAT_OF)

"""
    column_of_values(values) -> (column, format) or nothing

A column of `values`, `nothing` where an object has no such value: missing (NaN in a float column, `missing`
otherwise). `format`: the variable's format when the values are dates or times written as ISO 8601 text, else
nothing. Nothing for values encoding3d cannot hold.
"""
function column_of_values(values::AbstractVector)
    present = [value for value in values if value !== nothing]
    complete = length(present) == length(values)
    column_of(type) = complete ? type[value for value in values] :
                                 Union{Missing,type}[value === nothing ? missing : value for value in values]
    format = nothing
    if all(value -> value isa Bool, present)
        column = column_of(Bool)
    elseif all(value -> value isa Integer && !(value isa Bool), present)
        column = column_of(Int64)
    elseif all(value -> value isa Real && !(value isa Bool), present)
        column = Float64[value === nothing ? NaN : value for value in values]
    elseif all(value -> value isa Union{AbstractString,Symbol}, present)
        column = complete ? String[string(value) for value in values] :
                            Union{Missing,String}[value === nothing ? missing : string(value) for value in values]
    elseif !isempty(present) && all(value -> value isa TextType, present) && length(Set(typeof.(present))) == 1
        format = FORMAT_OF[typeof(first(present))]
        column = complete ? String[string(value) for value in values] :
                            Union{Missing,String}[value === nothing ? missing : string(value) for value in values]
    elseif all(value -> value isa AbstractVector{<:Real}, present) && length(Set(length.(present))) == 1 &&
           length(first(present)) >= 2
        width = length(first(present))
        integer = complete && all(value -> eltype(value) <: Integer && !(eltype(value) <: Bool), present)
        column = integer ? zeros(Int64, length(values), width) : fill(NaN, length(values), width)
        for (row, value) in enumerate(values)
            value === nothing || (column[row, :] .= value)                 # a missing vector: NaN
        end
    else
        return nothing
    end
    return column, format
end

"""A column's value at `row` as a platform reads it back: `missing` stays missing, ISO 8601 text of a `format` its
date or time, a vector row a Vector."""
function value_of(column::AbstractVector, row, format)
    value = column[row]
    ismissing(value) && return missing
    return format === nothing ? value : TYPE_OF_FORMAT[format](value)
end
value_of(column::AbstractMatrix, row, format) = collect(column[row, :])
