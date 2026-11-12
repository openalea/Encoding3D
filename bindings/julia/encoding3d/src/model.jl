# The encoding3d data model: a frame's data structures, their tables (columns of equal length), grids and meshes.
#
#     Frame              one time step of a scene
#       DataStructure    one plant population's graph, or one environment model's grid
#         EntitySet      the entities of one scale (or a grid's cells): a table of columns
#         Relation       an edge table between entity sets (cell adjacency, a branch's bearer, ...)
#         Table          the data structure's scalars: a table of one row
#         Grid           a regular or adaptive grid's layout
#         Mesh           triangles, each vertex carrying the row of its entity in one or several entity sets
#         InstanceSet    instances of shared templates (specification §12): a table of one row per instance, its
#                        vectors (Ragged) and derived fields (DerivedField)
#       Mapping          source entity ↔ target entity weights between two data structures
#     Template, Operator the shared parts instance sets use, kept once per sequence and found by their key
#
# A column is a Vector (one value per row: numbers, Bool, String) or a Matrix (one row per entity, one column per
# component: a fixed-size vector per entity). Missing values: NaN in float columns; `missing` elsewhere (a
# Vector{Union{Missing,T}} of integers, booleans or text).

"""The id of no entity: the `complex` or `parent` of an entity that has none, the feature row of a vertex with none."""
const NO_ID = -1
"""The values of `edge_type`: the root of its scale, MTG `<`, MTG `+`."""
const EDGE_TYPES = ("none", "successor", "branch", "unknown")
const ENUM_COLUMNS = ("label", "edge_type", "relation")
const ID_COLUMNS = ("id", "complex", "parent", "source", "target", "level", "index", "sibling_order")
"""The vocabulary's base scales: an entity set's `scale` is one of them, or `"mixed"`."""
const BASE_SCALES = ("Plant", "Axis", "GrowthUnit", "Phytomer", "Organ", "SubOrgan", "Layer", "Cell", "Compartment",
                     "Connection")
"""The formats of a text variable holding ISO 8601 dates or times."""
const FORMATS = ("date", "date-time", "time")
const DATA_STRUCTURE_KINDS = ("graph", "regular_grid", "adaptive_grid", "table")
const ROLES = ("state", "input", "parameter", "derived", "setting")
const COLUMN_TYPES = (Int8, UInt8, Int16, UInt16, Int32, UInt32, Int64, UInt64, Float32, Float64)

"""
    Variable(; unit="1", standard_name=nothing, kind=nothing, role="state", description=nothing,
             minimum=nothing, maximum=nothing, references=String[], doi=String[])

The declaration of a variable (a column): its unit (a UCUM code), its standard name in the vocabulary, its kind
(`extensive`, `intensive`, ...: how it maps between scales and grids), its role and its provenance; the `format` of
a text column holding dates or times (`"date"`, `"date-time"`, `"time"`).
"""
Base.@kwdef mutable struct Variable
    unit::String = "1"
    standard_name::Union{Nothing,String} = nothing
    kind::Union{Nothing,String} = nothing
    role::String = "state"
    description::Union{Nothing,String} = nothing
    minimum::Union{Nothing,Real} = nothing
    maximum::Union{Nothing,Real} = nothing
    references::Vector{String} = String[]
    doi::Vector{String} = String[]
    format::Union{Nothing,String} = nothing
end

function Base.:(==)(left::Variable, right::Variable)
    all(isequal(getfield(left, name), getfield(right, name)) for name in fieldnames(Variable))
end

const Columns = OrderedDict{String,AbstractArray}
const Declarations = OrderedDict{String,Variable}
const JSONObject = AbstractDict{String,Any}

"""The tables of a frame: `Table` (scalars), `EntitySet`, `Relation`, `Mapping`. Each has `name`, `columns` and
`variables`."""
abstract type AbstractTable end

"""
    Table(name; columns=Columns(), variables=Declarations())

Columns of equal length and the declarations of its variables: a data structure's scalars (one row).
"""
mutable struct Table <: AbstractTable
    name::String
    columns::Columns
    variables::Declarations
end

"""
    EntitySet(name; columns, variables, rank=nothing)

The entities of one scale of a graph (`rank`: the scale's rank, coarser first), or a grid's cells (`rank` nothing).
Reserved columns: `id` (Int64, stable across frames, never reused), `label` (String), `complex` (the id of the
containing entity at a coarser scale, `NO_ID` if none), `parent` (the predecessor's id at the same scale, `NO_ID` if
none), `edge_type` (`"none"`, `"successor"`, `"branch"`, `"unknown"`), `sibling_order` (optional: its position among its tree
parent's children); an adaptive grid's cells: `level` and `index`. `scale`: its base scale (`BASE_SCALES`), or
`"mixed"`.
"""
mutable struct EntitySet <: AbstractTable
    name::String
    columns::Columns
    variables::Declarations
    rank::Union{Nothing,Int}
    scale::Union{Nothing,String}
end

"""
    Relation(name; columns, variables, source_set, target_set)

An edge table: `source` and `target` entity ids (in the entity sets `source_set` and `target_set`), an optional `id`
per edge, an optional `relation` label per edge, and edge variables.
"""
mutable struct Relation <: AbstractTable
    name::String
    columns::Columns
    variables::Declarations
    source_set::String
    target_set::String
end

"""
    Mapping(name; columns, variables, source, target, method=nothing)

Weights between the entities of two data structures: `source` and `target` ids, `weight`. `source` and `target`:
(data structure id, entity set name).
"""
mutable struct Mapping <: AbstractTable
    name::String
    columns::Columns
    variables::Declarations
    source::Tuple{String,String}
    target::Tuple{String,String}
    method::Union{Nothing,String}
end

"""
    Ragged(values, counts)
    Ragged(vectors)

One array of numbers per instance, of each instance's own length (specification §12.2): `values` holds them one after
the other, in the instances' order; `counts` each one's length.
"""
struct Ragged
    values::Vector{Float64}
    counts::Vector{Int64}
end
Ragged(vectors::AbstractVector{<:AbstractVector}) =
    Ragged(Float64[value for vector in vectors for value in vector], Int64[length(vector) for vector in vectors])
Base.length(ragged::Ragged) = length(ragged.counts)
"""Where each instance's values start in `values` (0-based; one more than the instances: the end)."""
function offsets(ragged::Ragged)
    any(<(0), ragged.counts) && throw(ArgumentError("a ragged array's counts are not negative"))
    starts = vcat(0, cumsum(ragged.counts))
    starts[end] == length(ragged.values) ||
        throw(ArgumentError("a ragged array's counts sum to $(starts[end]), it holds $(length(ragged.values)) values"))
    return starts
end
"""The values of the instance at `row` (1-based)."""
function Base.getindex(ragged::Ragged, row::Integer)
    start = sum(view(ragged.counts, 1:row-1); init = 0)
    return ragged.values[start+1:start+ragged.counts[row]]
end

"""
    DerivedField(name; entity_set, input, operators, weights=1, offsets=nothing, variable=Variable(role="derived"))

A derived field (specification §12.3): a field on the entity set `entity_set` of the instances' templates, rebuilt for
each instance i from its vector `input` v as f = Σ_k w_ik (A_ik v + b_ik) over its K terms. `operators` and `weights`:
N×K (an operator is a 0-based index in the instance set's parts, `NO_ID` for none; a vector: one term); `offsets`: K
names of vectors, or `nothing`, each term's offset b.
"""
mutable struct DerivedField
    name::String
    entity_set::String
    input::String
    operators::Matrix{Int64}
    weights::Matrix{Float64}
    offsets::Vector{Union{Nothing,String}}
    variable::Variable
end
function DerivedField(name::AbstractString; entity_set, input, operators, weights = nothing, offsets = nothing,
                      variable = Variable(role = "derived"))
    operators = Matrix{Int64}(operators isa AbstractVector ? reshape(operators, :, 1) : operators)
    weights = weights === nothing ? ones(Float64, size(operators)) :
              Matrix{Float64}(weights isa AbstractVector ? reshape(weights, :, 1) : weights)
    size(weights) == size(operators) ||
        throw(ArgumentError("derived field '$name': one weight per operator ($(size(weights)), $(size(operators)))"))
    offsets = offsets === nothing ? fill(nothing, size(operators, 2)) :
              Union{Nothing,String}[offset === nothing ? nothing : String(offset) for offset in offsets]
    length(offsets) == size(operators, 2) || throw(ArgumentError("derived field '$name': one offset per term"))
    DerivedField(String(name), String(entity_set), String(input), operators, weights, offsets, variable)
end
"""The number of terms of a derived field."""
terms(derived::DerivedField) = size(derived.operators, 2)

"""
    InstanceSet(name; columns, variables, owners=nothing, parts=String[], vectors=OrderedDict(), derived=DerivedField[])

Instances of shared templates (specification §12.2): one row per instance, its reserved columns `template` (the 0-based
index in `parts` of its template, Int64), `owner` (the id, in the entity set `owners`, of the entity it draws),
`transform` (N×16, each row the column-major 4×4 placing the template; identity when absent) and `id`, then its own
variables. `parts`: the keys of the parts (templates and operators) the instances use; `vectors` and `derived`: its
vectors and derived fields (their columns <vector>__count, <field>__operator and <field>__weight are written from
them, not held as columns).
"""
mutable struct InstanceSet <: AbstractTable
    name::String
    columns::Columns
    variables::Declarations
    owners::Union{Nothing,String}
    parts::Vector{String}
    vectors::OrderedDict{String,Ragged}
    derived::Vector{DerivedField}
end

# The columns whose meaning the specification fixes, per kind of table
const ENTITY_SET_RESERVED = ("id", "label", "complex", "parent", "edge_type", "level", "index", "sibling_order")
const RELATION_RESERVED = ("id", "source", "target", "relation")
const MAPPING_RESERVED = ("source", "target", "weight")
const INSTANCE_SET_RESERVED = ("id", "owner", "template", "transform")
# The reserved integer columns written as Int64: ids, and an instance's owner and template
const INT64_COLUMNS = (ID_COLUMNS..., "owner", "template")
reserved(::Table) = ()
reserved(::EntitySet) = ENTITY_SET_RESERVED
reserved(::Relation) = RELATION_RESERVED
reserved(::Mapping) = MAPPING_RESERVED
reserved(::InstanceSet) = INSTANCE_SET_RESERVED

as_column(name::AbstractString, values::AbstractVector{<:AbstractString}) = Vector{String}(values)
as_column(name::AbstractString, values::AbstractVector{Bool}) = Vector{Bool}(values)
as_column(name::AbstractString, values::AbstractVector{T}) where {T<:Number} = Vector{T}(values)
as_column(name::AbstractString, values::AbstractMatrix{T}) where {T<:Number} = Matrix{T}(values)
as_column(name::AbstractString, values::Number) = [values]
as_column(name::AbstractString, values::AbstractString) = [String(values)]
function as_column(name::AbstractString, values::AbstractVector)
    isempty(values) && return Float64[]
    present = [value for value in values if !ismissing(value)]
    if all(value -> value isa AbstractString, present)
        return length(present) == length(values) ? Vector{String}(values) :
               Union{Missing,String}[ismissing(value) ? missing : String(value) for value in values]
    end
    promoted = isempty(present) ? Float64[] : [present...]          # the narrowest common type
    element = eltype(promoted)
    element <: Union{Number,Bool} ||
        throw(ArgumentError("column '$name': numbers, booleans or strings per row (got $element)"))
    length(present) == length(values) && return promoted
    element <: AbstractFloat && return element[ismissing(value) ? NaN : value for value in values]   # missing: NaN
    return Union{Missing,element}[value for value in values]
end
as_column(name::AbstractString, values) =
    throw(ArgumentError("column '$name': a vector, or a matrix of one row per entity (got $(typeof(values)))"))

function prepare_columns(table_name::AbstractString, columns, reserved_names)
    prepared = Columns()
    for (name, values) in pairs(columns)
        name = String(name)
        column = as_column(name, values)
        if name in INT64_COLUMNS && name in reserved_names && eltype(column) <: Integer && !(eltype(column) <: Bool)
            column = convert(Array{Int64}, column)          # ids are Int64, whatever the platform's integers
        end
        name in reserved_names && Missing <: eltype(column) &&
            throw(ArgumentError("table '$table_name': the reserved column '$name' has no missing values"))
        prepared[name] = column
    end
    counts = Dict(name => size(column, 1) for (name, column) in prepared)
    length(Set(values(counts))) > 1 &&
        throw(ArgumentError("table '$table_name': columns of different lengths $counts"))
    return prepared
end

prepare_variables(variables) = Declarations(String(name) => variable for (name, variable) in pairs(variables))

Table(name::AbstractString; columns = Columns(), variables = Declarations()) =
    Table(String(name), prepare_columns(name, columns, ()), prepare_variables(variables))
EntitySet(name::AbstractString; columns = Columns(), variables = Declarations(), rank = nothing, scale = nothing) =
    EntitySet(String(name), prepare_columns(name, columns, ENTITY_SET_RESERVED), prepare_variables(variables), rank,
              scale)
Relation(name::AbstractString; columns = Columns(), variables = Declarations(), source_set = "", target_set = "") =
    Relation(String(name), prepare_columns(name, columns, RELATION_RESERVED), prepare_variables(variables),
             String(source_set), String(target_set))
Mapping(name::AbstractString; columns = Columns(), variables = Declarations(), source = ("", ""),
        target = ("", ""), method = nothing) =
    Mapping(String(name), prepare_columns(name, columns, MAPPING_RESERVED), prepare_variables(variables),
            (String(source[1]), String(source[2])), (String(target[1]), String(target[2])), method)

InstanceSet(name::AbstractString; columns = Columns(), variables = Declarations(), owners = nothing, parts = String[],
            vectors = OrderedDict{String,Ragged}(), derived = DerivedField[]) =
    InstanceSet(String(name), prepare_columns(name, columns, INSTANCE_SET_RESERVED), prepare_variables(variables),
                owners === nothing ? nothing : String(owners), String.(collect(parts)),
                OrderedDict{String,Ragged}(String(key) => value isa Ragged ? value : Ragged(value)
                                          for (key, value) in pairs(vectors)), collect(DerivedField, derived))

"""The number of rows of a table."""
row_count(table::AbstractTable) = isempty(table.columns) ? 0 : size(first(values(table.columns)), 1)

"""The names of a table's variable columns (its columns but the reserved ones)."""
variable_names(table::AbstractTable) = [name for name in keys(table.columns) if !(name in reserved(table))]

"""The declaration of a column (an undeclared one: unit "1", role "state")."""
declaration(table::AbstractTable, name::AbstractString) = get(table.variables, name, Variable())

"""The ids of an entity set's entities: its `id` column, or a grid's row numbers (from 0) when it has none."""
entity_ids(entity_set::EntitySet) =
    haskey(entity_set.columns, "id") ? entity_set.columns["id"] : collect(Int64, 0:row_count(entity_set)-1)

"""
    Grid(; kind="regular", shape, origin, spacing, axes=["x","y","z"], periodic, z_up=true, max_level=0,
         cells="Cell")

A grid's layout. Regular: `shape` cells of size `spacing` from `origin`, along `axes`, `periodic` per axis, z
pointing up or down (`z_up`). Adaptive: the same for its base level, refined up to `max_level`, its leaf cells (an
entity set with `level` and `index` columns) explicit. `cells`: the name of the cells' entity set.
"""
Base.@kwdef mutable struct Grid
    kind::String = "regular"
    shape::Vector{Int} = Int[]
    origin::Vector{Float64} = Float64[]
    spacing::Vector{Float64} = Float64[]
    axes::Vector{String} = ["x", "y", "z"]
    periodic::Vector{Bool} = Bool[]
    z_up::Bool = true
    max_level::Int = 0
    cells::String = "Cell"
end

"""
    Mesh(name; positions, feature_rows=OrderedDict(), indices=nothing, display=OrderedDict(),
         display_sources=Dict())

Triangles: `positions` (V×3, in the data structure's frame), three consecutive vertices per triangle, or `indices`
(3T, 0-based) into them; `feature_rows`: entity set name => the row (0-based) of each vertex's entity in that set,
`NO_ID` for none; `display`: variable name => its Float32 copy per vertex, from the entity set `display_sources[name]`.
"""
mutable struct Mesh
    name::String
    positions::Matrix{Float64}
    feature_rows::OrderedDict{String,Vector{Int64}}
    indices::Union{Nothing,Vector{Int64}}
    display::OrderedDict{String,Vector{Float32}}
    display_sources::Dict{String,String}
end

function Mesh(name::AbstractString; positions, feature_rows = OrderedDict{String,Vector{Int64}}(),
              indices = nothing, display = OrderedDict{String,Vector{Float32}}(),
              display_sources = Dict{String,String}())
    positions = Matrix{Float64}(positions isa AbstractVector ? permutedims(reshape(positions, 3, :)) : positions)
    size(positions, 2) == 3 || throw(ArgumentError("mesh '$name': positions are V×3"))
    rows = OrderedDict{String,Vector{Int64}}(String(set) => Vector{Int64}(vec(values)) for (set, values) in pairs(feature_rows))
    for (set, values) in rows
        length(values) == size(positions, 1) ||
            throw(ArgumentError("mesh '$name': $(length(values)) feature rows for '$set', $(size(positions, 1)) vertices"))
    end
    Mesh(String(name), positions, rows, indices === nothing ? nothing : Vector{Int64}(vec(indices)),
         OrderedDict{String,Vector{Float32}}(String(variable) => Vector{Float32}(vec(values))
                                             for (variable, values) in pairs(display)),
         Dict{String,String}(String(variable) => String(set) for (variable, set) in pairs(display_sources)))
end

"""
    DataStructure(id; kind="graph", entity_sets=EntitySet[], relations=Relation[], scalars=nothing, grid=nothing,
                  meshes=Mesh[], origin=identity, platform=nothing, model=nothing, extras=OrderedDict())

One plant population's graph, or one environment model's grid. `origin`: its frame in the scene (a 4×4 matrix,
`origin[row, column]`, or 16 numbers row by row). `extras`: JSON values for the writing platform (e.g. what it needs
to rebuild its own data structure); other readers keep them without interpreting them. `labels`: the platform's
labels => the vocabulary's.
"""
mutable struct DataStructure
    id::String
    kind::String
    entity_sets::Vector{EntitySet}
    relations::Vector{Relation}
    scalars::Union{Nothing,Table}
    grid::Union{Nothing,Grid}
    meshes::Vector{Mesh}
    origin::Matrix{Float64}
    platform::Union{Nothing,String}
    model::Union{Nothing,String}
    extras::AbstractDict{String,Any}
    labels::AbstractDict{String,String}
    instance_sets::Vector{InstanceSet}
end

identity_matrix() = Matrix{Float64}([i == j for i in 1:4, j in 1:4])

function DataStructure(id::AbstractString; kind = "graph", entity_sets = EntitySet[], relations = Relation[],
                       scalars = nothing, grid = nothing, meshes = Mesh[], origin = identity_matrix(),
                       platform = nothing, model = nothing, extras = OrderedDict{String,Any}(),
                       labels = OrderedDict{String,String}(), instance_sets = InstanceSet[])
    origin = Matrix{Float64}(origin isa AbstractVector ? permutedims(reshape(origin, 4, 4)) : origin)
    size(origin) == (4, 4) || throw(ArgumentError("data structure '$id': the origin is a 4×4 matrix"))
    DataStructure(String(id), String(kind), collect(EntitySet, entity_sets), collect(Relation, relations), scalars,
                  grid, collect(Mesh, meshes), origin, platform, model, extras,
                  OrderedDict{String,String}(String(key) => String(value) for (key, value) in pairs(labels)),
                  collect(InstanceSet, instance_sets))
end

"""The entity set `name` of a data structure."""
function entity_set(data_structure::DataStructure, name::AbstractString)
    for candidate in data_structure.entity_sets
        candidate.name == name && return candidate
    end
    throw(KeyError("data structure '$(data_structure.id)' has no entity set '$name'"))
end

"""The instance set `name` of a data structure."""
function instance_set(data_structure::DataStructure, name::AbstractString)
    for candidate in data_structure.instance_sets
        candidate.name == name && return candidate
    end
    throw(KeyError("data structure '$(data_structure.id)' has no instance set '$name'"))
end

"""
    Template(; entity_sets=EntitySet[], meshes=Mesh[], relations=Relation[], kind="table", labels, extras)

A template (a shared part, specification §12.1): the data structure its part file holds (id "template", kind "table",
or "graph" with ranks): the template's own entity sets (e.g. a section's cells, their ids and constant variables),
relations, and meshes in the template's coordinates. A template is a valid frame of its own.
"""
struct Template
    data_structure::DataStructure
end
Template(; entity_sets = EntitySet[], meshes = Mesh[], relations = Relation[], kind = "table",
         labels = OrderedDict{String,String}(), extras = OrderedDict{String,Any}()) =
    Template(DataStructure("template"; kind, entity_sets, meshes, relations, labels, extras))
entity_set(template::Template, name::AbstractString) = entity_set(template.data_structure, name)

"""A matrix in compressed sparse rows: row r's entries (0-based) are `indices[indptr[r]+1:indptr[r+1]]`, and their
`values`."""
struct CompressedRows
    indptr::Vector{Int64}
    indices::Vector{Int64}
    values::Vector{Float64}
end
function CompressedRows(matrix::AbstractMatrix)
    indptr, indices, values = Int64[0], Int64[], Float64[]
    for row in 1:size(matrix, 1)
        for column in 1:size(matrix, 2)
            matrix[row, column] == 0 && continue
            push!(indices, column - 1)
            push!(values, matrix[row, column])
        end
        push!(indptr, length(indices))
    end
    return CompressedRows(indptr, indices, values)
end

"""
    dense_operator(matrix), sparse_operator(matrix), solve_operator(system, right_hand_side)

A linear operator of derived fields (a shared part, specification §12.1), rows × columns: `format` "dense" (`values`,
the matrix), "csr" (`sparse`, its non-zero values) or "solve" (S⁻¹ R, S `system`, rows × rows, R `right_hand_side`,
rows × columns, each as compressed sparse rows, solved when evaluated).
"""
struct Operator
    format::String
    rows::Int
    columns::Int
    values::Matrix{Float64}
    sparse::Union{Nothing,CompressedRows}
    system::Union{Nothing,CompressedRows}
    right_hand_side::Union{Nothing,CompressedRows}
end
dense_operator(matrix::AbstractMatrix) =
    Operator("dense", size(matrix, 1), size(matrix, 2), Matrix{Float64}(matrix), nothing, nothing, nothing)
sparse_operator(matrix::AbstractMatrix) =
    Operator("csr", size(matrix, 1), size(matrix, 2), zeros(0, 0), CompressedRows(matrix), nothing, nothing)
sparse_operator(rows::Integer, columns::Integer, matrix::CompressedRows) =
    Operator("csr", rows, columns, zeros(0, 0), matrix, nothing, nothing)
function solve_operator(system::AbstractMatrix, right_hand_side::AbstractMatrix)
    size(system, 1) == size(system, 2) == size(right_hand_side, 1) ||
        throw(ArgumentError("a solve operator: a square system, as many rows as its right-hand side"))
    Operator("solve", size(right_hand_side, 1), size(right_hand_side, 2), zeros(0, 0), nothing,
             CompressedRows(system), CompressedRows(right_hand_side))
end
solve_operator(rows::Integer, columns::Integer, system::CompressedRows, right_hand_side::CompressedRows) =
    Operator("solve", rows, columns, zeros(0, 0), nothing, system, right_hand_side)

"""A shared part: a template or an operator."""
const Part = Union{Template,Operator}

"""
    MissingPartError(key, looked)

A shared part a frame refers to is nowhere it may be (specification §12.1): its key, and where it was looked for.
"""
struct MissingPartError <: Exception
    key::String
    looked::Vector{String}
end
Base.showerror(io::IO, error::MissingPartError) =
    print(io, "the shared part $(error.key) is missing (looked for $(isempty(error.looked) ? "-" : join(error.looked, ", "))): ",
          "copy the sequence's parts/ folder with its frames, or write the frame with its parts embedded")

"""
    Update(participant; removed=OrderedDict())

What makes a frame partial: a coupling session's message (specification §11). `participant`: its sender
(`"coordinator"` for a turn's inputs). Its tables hold some rows and columns only. `removed`: (data structure id,
entity set name) => the ids of the entities removed.
"""
mutable struct Update
    participant::String
    removed::OrderedDict{Tuple{String,String},Vector{Int64}}
end

Update(participant::AbstractString; removed = OrderedDict{Tuple{String,String},Vector{Int64}}()) =
    Update(String(participant), OrderedDict{Tuple{String,String},Vector{Int64}}(
        (String(key[1]), String(key[2])) => Vector{Int64}(ids) for (key, ids) in removed))

"""
    Frame(; data_structures=DataStructure[], mappings=Mapping[], time=0.0, time_unit="d", step=0,
          writer=OrderedDict(), vocabulary_version=nothing, update=nothing, unknown=OrderedDict())

A scene at one time step (`time` in `time_unit`, `step`), or a parameter set. `update`: set for a partial frame
(`Update`), a coupling session's message. `unknown`: the content of a read file this package does not interpret
(other root extensions, the root's `extras`), written back as it was. The shared parts its instance sets refer to by
key (specification §12.1) are found in `part_bytes` (key => GLB bytes: those embedded in the file read, and those
`add_part!` encoded), else at parts/<key>.glb under `parts_folder` (the folder, or the x.fspm.zip archive, the frame was
read from).
"""
Base.@kwdef mutable struct Frame
    data_structures::Vector{DataStructure} = DataStructure[]
    mappings::Vector{Mapping} = Mapping[]
    time::Float64 = 0.0
    time_unit::String = "d"
    step::Int = 0
    writer::AbstractDict{String,Any} = OrderedDict{String,Any}()
    vocabulary_version::Union{Nothing,String} = nothing
    update::Union{Nothing,Update} = nothing
    unknown::AbstractDict{String,Any} = OrderedDict{String,Any}()
    part_bytes::OrderedDict{String,Vector{UInt8}} = OrderedDict{String,Vector{UInt8}}()
    parts_folder::Union{Nothing,String} = nothing
end

"""The data structure `id` of a frame."""
function data_structure(frame::Frame, id::AbstractString)
    for candidate in frame.data_structures
        candidate.id == id && return candidate
    end
    throw(KeyError("the frame has no data structure '$id'"))
end
