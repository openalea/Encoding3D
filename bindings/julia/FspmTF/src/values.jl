# Values of a platform's objects (attributes, fields) as columns: what the adapters share.

const TextType = Union{Date,DateTime,Time}
"""The types written as ISO 8601 text, by name (an adapter records the name to read them back)."""
const TEXT_TYPES = Dict("Date" => Date, "DateTime" => DateTime, "Time" => Time)

"""A column of `values` (`nothing` where a node has no such attribute): the column, its missing rows (0-based),
the type written as text (or nothing); nothing for values fspm-TF cannot hold."""
function column_of_values(values::AbstractVector)
    present = [value for value in values if value !== nothing]
    missing_rows = [row - 1 for (row, value) in enumerate(values) if value === nothing]
    text_type = nothing
    if all(value -> value isa Bool, present)
        column = Bool[value === nothing ? false : value for value in values]
    elseif all(value -> value isa Integer && !(value isa Bool), present)
        column = Int64[value === nothing ? 0 : value for value in values]
    elseif all(value -> value isa Real && !(value isa Bool), present)
        column = Float64[value === nothing ? NaN : value for value in values]
    elseif all(value -> value isa Union{AbstractString,Symbol}, present)
        column = String[value === nothing ? "" : string(value) for value in values]
    elseif !isempty(present) && all(value -> value isa TextType, present) && length(Set(typeof.(present))) == 1
        text_type = string(nameof(typeof(first(present))))
        column = String[value === nothing ? "" : string(value) for value in values]
    elseif all(value -> value isa AbstractVector{<:Real}, present) && length(Set(length.(present))) == 1 &&
           length(first(present)) >= 2
        width = length(first(present))
        integer = all(value -> eltype(value) <: Integer && !(eltype(value) <: Bool), present)
        column = integer ? zeros(Int64, length(values), width) : fill(NaN, length(values), width)
        for (row, value) in enumerate(values)
            value === nothing || (column[row, :] .= value)
        end
    else
        return nothing
    end
    return column, missing_rows, text_type
end
