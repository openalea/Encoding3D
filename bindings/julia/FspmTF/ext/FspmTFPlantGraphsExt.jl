"""
A VirtualPlantLab graph (PlantGraphs.jl: a `Graph` or a `StaticGraph`) as an fspm-TF `graph` data structure, and back:

| fspm-TF | PlantGraphs |
|---|---|
| one entity set (default `Organ`, rank 5) | the graph's nodes, but the turtle's movements (PlantGeomTurtle: `T`, `RU`, `F`, `SET`, …) |
| `id`, `label` | the node's id, the name of its type (`Internode`, `Leaf`, …) |
| `parent` | its nearest kept ancestor |
| `edge_type` | guessed: PlantGraphs stores none; a node's last kept child follows it (`successor`), the others branch |
| variables | the fields of each node's type (missing in other types: see below) |
| scalars | the graph's data (`data(graph)`), its fields |

PlantGraphs has one scale. What fspm-TF 0.1 cannot say is kept in `extras["VirtualPlantLab"]`: the rows where a
node's type has no such field, the types written as text (dates), each type's field names (to rebuild nodes with
`to_graph`), and that edge types were guessed.
"""
module FspmTFPlantGraphsExt

using FspmTF
using FspmTF: Columns, Declarations, json_object, check_identifier, column_of_values
using OrderedCollections: OrderedDict
import PlantGraphs as PG

const PLATFORM = "VirtualPlantLab"
const IDENTIFIER = r"^[a-zA-Z_][a-zA-Z0-9_]*$"

"""Whether a node is kept: the turtle's movements and state nodes (PlantGeomTurtle's types) are not."""
default_keep(node_data) = nameof(parentmodule(typeof(node_data))) != :PlantGeomTurtle

label_of(node_data) = string(nameof(typeof(node_data)))

field_values(object) = object === nothing ? Pair{Symbol,Any}[] :
    [name => getfield(object, name) for name in fieldnames(typeof(object))]

"""Columns of the objects' fields, by name in order of first appearance; their missing rows and text types."""
function field_columns(objects, set_name, variables)
    names = Symbol[]
    values_of = [Dict{Symbol,Any}(field_values(object)) for object in objects]
    for object in objects, (name, _) in field_values(object)
        name in names || push!(names, name)
    end
    columns, declarations, missing_rows, text_types = Columns(), Declarations(), json_object(), json_object()
    for name in names
        column_name = string(name)
        if !occursin(IDENTIFIER, column_name) || column_name in FspmTF.ENTITY_SET_RESERVED
            @warn "field '$name' of '$set_name' not written: not an identifier, or a reserved column name"
            continue
        end
        converted = column_of_values(Any[get(values, name, nothing) for values in values_of])
        if converted === nothing
            @warn "field '$name' of '$set_name' not written: fspm-TF holds numbers, booleans, text, dates and " *
                  "fixed-size numeric vectors"
            continue
        end
        column, missing_of_column, text_type = converted
        columns[column_name] = column
        isempty(missing_of_column) || (missing_rows[column_name] = missing_of_column)
        text_type === nothing || (text_types[column_name] = text_type)
        haskey(variables, column_name) && (declarations[column_name] = variables[column_name])
    end
    return columns, declarations, missing_rows, text_types
end

static_of(graph::PG.Graph) = PG.static_graph(graph)
static_of(graph::PG.StaticGraph) = graph
graph_data(graph::PG.Graph) = PG.data(graph)
graph_data(::PG.StaticGraph) = nothing

"""The graph's kept nodes in depth-first order (children in their order), each with its nearest kept ancestor's id."""
function kept_nodes(static, keep)
    rows = Tuple{PG.GraphNode,Int}[]                     # node, its kept parent's id (NO_ID: none)
    stack = Tuple{PG.GraphNode,Int}[(PG.getroot(static), NO_ID)]
    while !isempty(stack)
        node, kept_parent = pop!(stack)
        parent_of_children = kept_parent
        if keep(PG.data(node))
            push!(rows, (node, kept_parent))
            parent_of_children = PG.self_id(node)
        end
        for child in reverse(collect(PG.children(node, static)))
            push!(stack, (child, parent_of_children))
        end
    end
    return rows
end

"""
    from_graph(graph; id="plant", entity_set="Organ", rank=5, variables=Dict(), keep=default_keep,
               platform="VirtualPlantLab", model=nothing) -> DataStructure

The PlantGraphs graph as a `graph` data structure of one entity set. `variables`: the fields' declarations (name =>
`Variable`). `keep`: which nodes (by their data) are entities; by default all but the turtle's movements.
"""
function FspmTF.from_graph(graph::Union{PG.Graph,PG.StaticGraph}; id::AbstractString = "plant",
                           entity_set::AbstractString = "Organ", rank = 5, variables = Dict{String,Variable}(),
                           keep = default_keep, platform = PLATFORM, model = nothing)
    check_identifier(entity_set, "entity set name")
    variables = Dict{String,Variable}(string(name) => variable for (name, variable) in pairs(variables))
    static = static_of(graph)
    rows = kept_nodes(static, keep)
    ids = Int64[PG.self_id(node) for (node, _) in rows]
    parents = Int64[parent for (_, parent) in rows]
    last_child = Dict{Int64,Int64}()                     # each parent's last kept child
    for (child, parent) in zip(ids, parents)
        parent == NO_ID || (last_child[parent] = child)
    end
    edge_types = String[parent == NO_ID ? "none" : last_child[parent] == child ? "successor" : "branch"
                        for (child, parent) in zip(ids, parents)]
    objects = [PG.data(node) for (node, _) in rows]
    columns = Columns("id" => ids, "label" => String[label_of(object) for object in objects], "parent" => parents,
                      "edge_type" => edge_types)
    fields, declarations, missing_rows, text_types = field_columns(objects, entity_set, variables)
    merge!(columns, fields)
    extras = json_object("edge_types" => "guessed: PlantGraphs stores none; a node's last child follows it, the others branch",
                         "types" => json_object(label_of(object) => string.(fieldnames(typeof(object)))
                                                for object in unique(object -> typeof(object), objects)))
    isempty(missing_rows) || (extras["missing"] = json_object(entity_set => missing_rows))
    isempty(text_types) || (extras["text_types"] = json_object(entity_set => text_types))

    scalars = nothing
    data = graph_data(graph)
    if data !== nothing && !isempty(fieldnames(typeof(data)))
        scalar_columns, scalar_declarations, missing_scalars, text_scalars = field_columns([data], "scalars", variables)
        if !isempty(scalar_columns)
            scalars = Table("scalars"; columns = scalar_columns, variables = scalar_declarations)
            extras["data_type"] = string(nameof(typeof(data)))
            isempty(text_scalars) || (extras["text_types"] = merge(get(extras, "text_types", json_object()),
                                                                   json_object("scalars" => text_scalars)))
        end
    end
    set = EntitySet(entity_set; columns = columns, variables = declarations, rank = rank)
    return DataStructure(id; kind = "graph", entity_sets = [set], scalars = scalars, platform = platform,
                         model = model, extras = json_object(PLATFORM => extras))
end

# ── Data structure → graph ──────────────────────────────────────────────

row_value(column::AbstractVector, row) = column[row]
row_value(column::AbstractMatrix, row) = collect(column[row, :])

"""
    to_graph(data_structure; types, entity_set=nothing) -> (StaticGraph, ids)

The data structure's entities as a PlantGraphs `StaticGraph`, each built as `types[label](fields...)` from its row,
its type's fields in their order (`types`: label => node type, e.g. `Dict("Internode" => Internode)`). `entity_set`:
the set read (by default the finest one with parents). `ids`: the entity ids => their ids in the graph (PlantGraphs
gives new ids). Wrap the graph as VPL does: `Graph(axiom = static_graph, rules = ..., data = ...)`.
"""
function FspmTF.to_graph(data_structure::DataStructure; types::AbstractDict, entity_set = nothing)
    candidates = [set for set in data_structure.entity_sets if haskey(set.columns, "parent")]
    set = entity_set === nothing ?
        (isempty(candidates) ? throw(ArgumentError("'$(data_structure.id)': no entity set with parents")) :
         last(sort(candidates; by = set -> something(set.rank, 0)))) :
        FspmTF.entity_set(data_structure, entity_set)
    extras = get(data_structure.extras, PLATFORM, json_object())
    missing_rows = Dict(name => Set(rows) for (name, rows) in pairs(get(get(extras, "missing", json_object()), set.name, json_object())))
    text_types = get(get(extras, "text_types", json_object()), set.name, json_object())
    labels = set.columns["label"]
    objects = Vector{Any}(undef, row_count(set))
    for row in 1:row_count(set)
        haskey(types, labels[row]) || throw(ArgumentError("no node type given for label '$(labels[row])'"))
        node_type = types[labels[row]]
        arguments = map(fieldnames(node_type)) do field
            name = string(field)
            haskey(set.columns, name) && !((row - 1) in get(missing_rows, name, Set{Int}())) ||
                throw(ArgumentError("'$(labels[row])' row $row: no value for field '$name'"))
            value = row_value(set.columns[name], row)
            haskey(text_types, name) ? FspmTF.TEXT_TYPES[text_types[name]](value) : value
        end
        objects[row] = node_type(arguments...)
    end
    ids, parents = set.columns["id"], set.columns["parent"]
    children_of = Dict{Int64,Vector{Int}}()
    roots = Int[]
    for row in 1:row_count(set)
        parents[row] == NO_ID ? push!(roots, row) : push!(get!(children_of, parents[row], Int[]), row)
    end
    length(roots) == 1 || throw(ArgumentError("'$(set.name)': $(length(roots)) roots, a PlantGraphs graph has one"))
    static = PG.StaticGraph(PG.GraphNode(objects[only(roots)]))
    graph_ids = Dict{Int64,Int}(ids[only(roots)] => PG.self_id(PG.getroot(static)))
    stack = [only(roots)]
    while !isempty(stack)
        row = pop!(stack)
        for child in get(children_of, ids[row], Int[])
            graph_ids[ids[child]] = append!(static, graph_ids[ids[row]], PG.GraphNode(objects[child]))
            push!(stack, child)
        end
    end
    return static, graph_ids
end

end
