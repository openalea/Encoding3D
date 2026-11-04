"""
A VirtualPlantLab graph (PlantGraphs.jl: a `Graph` or a `StaticGraph`) as an encoding3d `graph` data structure, and back:

| encoding3d | PlantGraphs |
|---|---|
| one entity set (default `Organ`, rank 5) | the graph's nodes, but the turtle's movements (PlantGeomTurtle: `T`, `RU`, `F`, `SET`, …) |
| `id`, `label` | the node's id, the name of its type (`Internode`, `Leaf`, …) |
| `parent` | its nearest kept ancestor |
| `edge_type` | `unknown`: PlantGraphs stores no edge types |
| `sibling_order` | the node's position among its kept parent's kept children |
| variables | the fields of each node's type: missing where a type has no such field; dates as ISO 8601 text with their `format` |
| scalars | the graph's data (`data(graph)`), its fields |

PlantGraphs has one scale. Each type's field names, to rebuild nodes with `to_graph`, are kept in
`extras["virtualplantlab"]` (with `"model": "PlantGraphs"`).
"""
module encoding3dPlantGraphsExt

using encoding3d
using encoding3d: Columns, Declarations, json_object, check_identifier, column_of_values
using OrderedCollections: OrderedDict
import PlantGraphs as PG

const PLATFORM = "VirtualPlantLab"
const EXTRAS_KEY = "virtualplantlab"                  # the extras key: VirtualPlantLab's name in the vocabulary
const IDENTIFIER = r"^[a-zA-Z_][a-zA-Z0-9_]*$"

"""Whether a node is kept: the turtle's movements and state nodes (PlantGeomTurtle's types) are not."""
default_keep(node_data) = nameof(parentmodule(typeof(node_data))) != :PlantGeomTurtle

label_of(node_data) = string(nameof(typeof(node_data)))

field_values(object) = object === nothing ? Pair{Symbol,Any}[] :
    [name => getfield(object, name) for name in fieldnames(typeof(object))]

"""Columns of the objects' fields (missing where an object has none), by name in order of first appearance, and their
declarations (a date's `format` added)."""
function field_columns(objects, set_name, variables)
    names = Symbol[]
    values_of = [Dict{Symbol,Any}(field_values(object)) for object in objects]
    for object in objects, (name, _) in field_values(object)
        name in names || push!(names, name)
    end
    columns, declarations = Columns(), Declarations()
    for name in names
        column_name = string(name)
        if !occursin(IDENTIFIER, column_name) || column_name in encoding3d.ENTITY_SET_RESERVED
            @warn "field '$name' of '$set_name' not written: not an identifier, or a reserved column name"
            continue
        end
        converted = column_of_values(Any[get(values, name, nothing) for values in values_of])
        if converted === nothing
            @warn "field '$name' of '$set_name' not written: encoding3d holds numbers, booleans, text, dates and " *
                  "fixed-size numeric vectors"
            continue
        end
        column, format = converted
        columns[column_name] = column
        declared = get(variables, column_name, nothing)
        if format !== nothing                                  # dates and times: their format declared
            declared = declared === nothing ? Variable(unit = "1", kind = "descriptor") : deepcopy(declared)
            declared.format = format
        end
        declared === nothing || (declarations[column_name] = declared)
    end
    return columns, declarations
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
    from_graph(graph; id="plant", entity_set="Organ", rank=5, scale=nothing, variables=Dict(), labels=Dict(),
               keep=default_keep, platform="VirtualPlantLab", model=nothing) -> DataStructure

The PlantGraphs graph as a `graph` data structure of one entity set. `scale`: its base scale (e.g. `"Organ"`), or
`"mixed"`. `variables`: the fields' declarations (name => `Variable`). `labels`: the node types' names => the
vocabulary's labels (e.g. `Dict("Internode" => "StemInternode")`). `keep`: which nodes (by their data) are entities;
by default all but the turtle's movements.
"""
function encoding3d.from_graph(graph::Union{PG.Graph,PG.StaticGraph}; id::AbstractString = "plant",
                           entity_set::AbstractString = "Organ", rank = 5, scale = nothing,
                           variables = Dict{String,Variable}(), labels = Dict{String,String}(), keep = default_keep,
                           platform = PLATFORM, model = nothing)
    check_identifier(entity_set, "entity set name")
    variables = Dict{String,Variable}(string(name) => variable for (name, variable) in pairs(variables))
    static = static_of(graph)
    rows = kept_nodes(static, keep)
    ids = Int64[PG.self_id(node) for (node, _) in rows]
    parents = Int64[parent for (_, parent) in rows]
    siblings_seen = Dict{Int64,Int64}()                  # each parent's kept children so far
    order = Int64[parent == NO_ID ? 0 : (siblings_seen[parent] = get(siblings_seen, parent, -1) + 1)
                  for parent in parents]
    edge_types = String[parent == NO_ID ? "none" : "unknown" for parent in parents]   # PlantGraphs stores none
    objects = [PG.data(node) for (node, _) in rows]
    columns = Columns("id" => ids, "label" => String[label_of(object) for object in objects], "parent" => parents,
                      "edge_type" => edge_types, "sibling_order" => order)
    fields, declarations = field_columns(objects, entity_set, variables)
    merge!(columns, fields)
    extras = json_object("model" => "PlantGraphs",
                         "types" => json_object(label_of(object) => string.(fieldnames(typeof(object)))
                                                for object in unique(object -> typeof(object), objects)))

    scalars = nothing
    data = graph_data(graph)
    if data !== nothing && !isempty(fieldnames(typeof(data)))
        scalar_columns, scalar_declarations = field_columns([data], "scalars", variables)
        if !isempty(scalar_columns)
            scalars = Table("scalars"; columns = scalar_columns, variables = scalar_declarations)
            extras["data_type"] = string(nameof(typeof(data)))
        end
    end
    set = EntitySet(entity_set; columns = columns, variables = declarations, rank = rank, scale = scale)
    return DataStructure(id; kind = "graph", entity_sets = [set], scalars = scalars, platform = platform,
                         model = model, extras = json_object(EXTRAS_KEY => extras), labels = labels)
end

# ── Data structure → graph ──────────────────────────────────────────────


"""
    to_graph(data_structure; types, entity_set=nothing) -> (StaticGraph, ids)

The data structure's entities as a PlantGraphs `StaticGraph`, each built as `types[label](fields...)` from its row,
its type's fields in their order (`types`: label => node type, e.g. `Dict("Internode" => Internode)`). `entity_set`:
the set read (by default the finest one with parents). `ids`: the entity ids => their ids in the graph (PlantGraphs
gives new ids). Wrap the graph as VPL does: `Graph(axiom = static_graph, rules = ..., data = ...)`.
"""
function encoding3d.to_graph(data_structure::DataStructure; types::AbstractDict, entity_set = nothing)
    candidates = [set for set in data_structure.entity_sets if haskey(set.columns, "parent")]
    set = entity_set === nothing ?
        (isempty(candidates) ? throw(ArgumentError("'$(data_structure.id)': no entity set with parents")) :
         last(sort(candidates; by = set -> something(set.rank, 0)))) :
        encoding3d.entity_set(data_structure, entity_set)
    labels = set.columns["label"]
    objects = Vector{Any}(undef, row_count(set))
    for row in 1:row_count(set)
        haskey(types, labels[row]) || throw(ArgumentError("no node type given for label '$(labels[row])'"))
        node_type = types[labels[row]]
        arguments = map(fieldnames(node_type)) do field
            name = string(field)
            format = haskey(set.variables, name) ? set.variables[name].format : nothing
            value = haskey(set.columns, name) ? encoding3d.value_of(set.columns[name], row, format) : missing
            ismissing(value) && throw(ArgumentError("'$(labels[row])' row $row: no value for field '$name'"))
            value
        end
        objects[row] = node_type(arguments...)
    end
    ids, parents = set.columns["id"], set.columns["parent"]
    children_of = Dict{Int64,Vector{Int}}()
    roots = Int[]
    for row in 1:row_count(set)
        parents[row] == NO_ID ? push!(roots, row) : push!(get!(children_of, parents[row], Int[]), row)
    end
    if haskey(set.columns, "sibling_order")                       # children in their order, else in their rows'
        foreach(list -> sort!(list; by = row -> set.columns["sibling_order"][row]), values(children_of))
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
