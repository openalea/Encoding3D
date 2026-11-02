"""
A MultiScaleTreeGraph (MTG.jl) as an fspm-TF `graph` data structure, and back:

| fspm-TF | MultiScaleTreeGraph |
|---|---|
| one entity set per scale ≥ 1, `rank` the scale | the nodes of that scale |
| `id` | `node_id` |
| `label` | the node's `symbol` |
| `complex` | its first ancestor at a smaller scale (none for the scene) |
| `parent`, `edge_type` | its parent, when at the same scale and linked by `<` (successor) or `+` (branch) |
| relation `bearer` | its parent otherwise, when it is not its complex linked by `/` (e.g. an axis borne by an internode) |
| `mtg_index` | the node's `index` |
| variables | its attributes |
| scalars | the scene's (the scale 0 root's) attributes |

What fspm-TF 0.1 cannot say is kept in the data structure's `extras["MultiScaleTreeGraph"]`, so that `to_mtg` rebuilds
the same MTG: the attributes a node does not have (fspm-TF columns have a value on every row; the missing value
written is NaN, `false`, 0 or ""), the types written as text (dates), the scene's node and its MTG metadata
(`symbols`, `scales`, `description`), and the order of children when it is not the order of their ids.
"""
module FspmTFMultiScaleTreeGraphExt

using Dates
using FspmTF
using FspmTF: Columns, Declarations, json_object, check_identifier
using MultiScaleTreeGraph
using OrderedCollections: OrderedDict

const PLATFORM = "MultiScaleTreeGraph"
const METADATA_ATTRIBUTES = (:symbols, :scales, :description)
# MTG.jl's node ids start at 1 and size its attribute store (an id of 2^32 allocates 2^32 rows), fspm-TF's start at 0
# and may be sparse (CPlantBox's segments: 2^32 + node id). to_mtg then numbers the nodes 1, 2, ... in the order of
# their ids, each keeping its id in this attribute; from_mtg writes it back as the id.
const ID_ATTRIBUTE = :fspm_tf_id
# An entity whose parent (same scale) is in another complex, e.g. the first segment of a lateral root, whose parent
# segment is in the bearing root: MTG.jl takes a node's complex from its ancestors, so the node stays under its complex
# (by '/') and keeps its parent and edge type in these attributes.
const PARENT_ATTRIBUTE = :fspm_tf_parent
const EDGE_TYPE_ATTRIBUTE = :fspm_tf_edge_type
const OWN_ATTRIBUTES = (ID_ATTRIBUTE, PARENT_ATTRIBUTE, EDGE_TYPE_ATTRIBUTE)
const LINK_NAMES = Dict(:< => "successor", :+ => "branch", :/ => "decomposition")
const LINKS = Dict(name => link for (link, name) in LINK_NAMES)
const TEXT_TYPES = Dict("Date" => Date, "DateTime" => DateTime, "Time" => Time)
const INDEX_COLUMN = "mtg_index"
const INDEX_VARIABLE = Variable(unit = "1", kind = "descriptor", role = "state",
                                description = "the node's index in its MTG code (1 in Internode1)")

parent_node(node) = isroot(node) ? nothing : parent(node)

"""The nodes of the MTG in depth-first order, children in their order."""
function preorder(root)
    nodes, stack = Any[], Any[root]
    while !isempty(stack)
        node = pop!(stack)
        push!(nodes, node)
        append!(stack, reverse(children(node)))
    end
    return nodes
end

"""The first ancestor of `node` at a smaller scale than its own, or nothing."""
function complex_node(node)
    ancestor = parent_node(node)
    while ancestor !== nothing && scale(ancestor) >= scale(node)
        ancestor = parent_node(ancestor)
    end
    return ancestor
end

default_set_name(scale_number, symbols) =
    length(symbols) == 1 && occursin(r"^[a-zA-Z_][a-zA-Z0-9_]*$", symbols[1]) ? symbols[1] : "Scale$scale_number"

# ── Attributes as columns ───────────────────────────────────────────────

const TextType = Union{Date,DateTime,Time}

"""A column of `values` (`nothing` where a node has no such attribute): the column, its missing rows (0-based),
the type written as text (or nothing); nothing for values fspm-TF cannot hold."""
function attribute_column(values::Vector)
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

"""Columns of `nodes`' attributes, by name in order of first appearance; the missing rows and text types of each.
`skip`: attributes not written; the MTG's root's metadata (MTG.jl's `symbols`, `scales`, `description`) neither."""
function attribute_columns(nodes, set_name, variables, skip = ())
    attribute_of(node, name) =
        isroot(node) && name in METADATA_ATTRIBUTES ? nothing : attribute(node, name; default = nothing)
    names = Symbol[]
    for node in nodes, name in attribute_names(node)
        name in names || name in skip || name in OWN_ATTRIBUTES || (isroot(node) && name in METADATA_ATTRIBUTES) ||
            push!(names, name)
    end
    columns, declarations = Columns(), Declarations()
    missing_rows, text_types = json_object(), json_object()
    for name in names
        values = Any[attribute_of(node, name) for node in nodes]
        converted = attribute_column(values)
        if converted === nothing
            @warn "attribute '$name' of '$set_name' not written: fspm-TF holds numbers, booleans, text, dates " *
                  "and fixed-size numeric vectors"
            continue
        end
        column_name = string(name)
        check_identifier(column_name, "attribute of '$set_name'")
        column, missing_of_column, text_type = converted
        columns[column_name] = column
        isempty(missing_of_column) || (missing_rows[column_name] = missing_of_column)
        text_type === nothing || (text_types[column_name] = text_type)
        haskey(variables, column_name) && (declarations[column_name] = variables[column_name])
    end
    return columns, declarations, missing_rows, text_types
end

# ── MTG → data structure ────────────────────────────────────────────────

"""
    from_mtg(mtg; id="plants", scales=Dict(), variables=Dict(), platform="MultiScaleTreeGraph", model=nothing)
        -> DataStructure

The MTG whose root is `mtg` as a `graph` data structure `id`. `scales`: the name of each scale's entity set
(scale => name, e.g. `Dict(1 => "Plant", 2 => "Axis", 3 => "Organ")`; by default the scale's symbol when it has
only one, `Scale<n>` otherwise). `variables`: the declarations of the attributes (name => `Variable`: unit, standard
name, kind, role), MTG.jl having no units. A scale 0 root (MTG.jl's `Scene`) is the data structure itself, its
attributes the scalars.
"""
function FspmTF.from_mtg(mtg; id::AbstractString = "plants", scales = Dict{Int,String}(),
                         variables = Dict{String,Variable}(), platform = PLATFORM, model = nothing)
    variables = Dict{String,Variable}(string(name) => variable for (name, variable) in pairs(variables))
    fspm_id(node) = attribute(node, ID_ATTRIBUTE; default = node_id(node))
    nodes = preorder(mtg)
    scene = scale(mtg) == 0 ? mtg : nothing
    extras = json_object()
    by_scale = OrderedDict{Int,Vector{Any}}()
    for node in nodes
        node === scene && continue
        scale(node) >= 1 || throw(ArgumentError("node $(node_id(node)): scale $(scale(node)) below a root's"))
        push!(get!(by_scale, scale(node), Any[]), node)
    end
    sort!(by_scale)
    set_names = Dict{Int,String}()
    for (scale_number, scale_nodes) in by_scale
        name = get(scales, scale_number, nothing)
        name === nothing && (name = default_set_name(scale_number, unique(string.(symbol.(scale_nodes)))))
        check_identifier(name, "the entity set name of scale $scale_number")
        set_names[scale_number] = name
    end

    entity_sets, missing_rows, text_types = EntitySet[], json_object(), json_object()
    bearers = OrderedDict{Tuple{String,String},Vector{Tuple{Int64,Int64,String}}}()
    for (scale_number, scale_nodes) in by_scale
        set_name = set_names[scale_number]
        columns = Columns("id" => Int64[fspm_id(node) for node in scale_nodes],
                          "label" => String[string(symbol(node)) for node in scale_nodes])
        complexes = [complex_node(node) for node in scale_nodes]
        if scale_number != first(keys(by_scale))
            columns["complex"] = Int64[complex === nothing || complex === scene ? NO_ID : fspm_id(complex)
                                       for complex in complexes]
        end
        parents, edge_types = Int64[], String[]
        for (node, complex) in zip(scale_nodes, complexes)
            if PARENT_ATTRIBUTE in attribute_names(node)                 # a parent in another complex (to_mtg)
                push!(parents, attribute(node, PARENT_ATTRIBUTE))
                push!(edge_types, attribute(node, EDGE_TYPE_ATTRIBUTE))
                continue
            end
            tree_parent = parent_node(node)
            if tree_parent !== nothing && scale(tree_parent) == scale(node) && link(node) in (:<, :+)
                push!(parents, fspm_id(tree_parent))
                push!(edge_types, LINK_NAMES[link(node)])
                continue
            end
            push!(parents, NO_ID)
            push!(edge_types, "none")
            tree_parent === nothing && continue
            tree_parent === complex && link(node) == :/ && continue       # its complex, by decomposition
            tree_parent === scene && link(node) == :/ && continue          # the scene's component
            tree_parent === scene &&
                throw(ArgumentError("node $(fspm_id(node)) is linked to the scene by '$(link(node))', not '/'"))
            pair = (set_name, set_names[scale(tree_parent)])
            push!(get!(bearers, pair, Tuple{Int64,Int64,String}[]),
                  (fspm_id(node), fspm_id(tree_parent), LINK_NAMES[link(node)]))
        end
        columns["parent"], columns["edge_type"] = parents, edge_types
        columns[INDEX_COLUMN] = Int64[index(node) for node in scale_nodes]
        attributes, declarations, missing_of_set, text_types_of_set =
            attribute_columns(scale_nodes, set_name, variables, (Symbol(INDEX_COLUMN),))
        merge!(columns, attributes)
        declarations = merge(Declarations(INDEX_COLUMN => INDEX_VARIABLE), declarations)
        isempty(missing_of_set) || (missing_rows[set_name] = missing_of_set)
        isempty(text_types_of_set) || (text_types[set_name] = text_types_of_set)
        push!(entity_sets, EntitySet(set_name; columns = columns, variables = declarations, rank = scale_number))
    end

    relations = Relation[]
    for ((source_set, target_set), edges) in bearers
        name = length(bearers) == 1 ? "bearer" : "bearer_$(source_set)_$(target_set)"
        push!(relations, Relation(name; source_set = source_set, target_set = target_set,
                                  columns = Columns("source" => Int64[edge[1] for edge in edges],
                                                    "target" => Int64[edge[2] for edge in edges],
                                                    "relation" => String[edge[3] for edge in edges])))
    end

    metadata = json_object()                                    # MTG.jl's, on the root
    for name in METADATA_ATTRIBUTES
        name in attribute_names(mtg) || continue
        value = attribute(mtg, name; default = nothing)                        # nothing kept: e.g. no description
        metadata[string(name)] = value isa MultiScaleTreeGraph.ColumnTable ?
            json_object(string(column) => getproperty(value, column) for column in names(value)) : value
    end
    isempty(metadata) || (extras["metadata"] = metadata)
    scalars = nothing
    if scene !== nothing
        extras["scene"] = json_object("id" => fspm_id(scene), "symbol" => string(symbol(scene)),
                                      "index" => index(scene), "link" => string(link(scene)))
        columns, declarations, missing_of_scene, text_types_of_scene =
            attribute_columns([scene], "scalars", variables)
        if !isempty(columns)
            scalars = Table("scalars"; columns = columns, variables = declarations)
            isempty(missing_of_scene) || (missing_rows["scalars"] = missing_of_scene)
            isempty(text_types_of_scene) || (text_types["scalars"] = text_types_of_scene)
        end
    end
    isempty(missing_rows) || (extras["missing"] = missing_rows)
    isempty(text_types) || (extras["text_types"] = text_types)
    order = [fspm_id(node) for node in nodes]
    order == [fspm_id(node) for node in preorder_by_id(nodes)] || (extras["order"] = order)

    return DataStructure(id; kind = "graph", entity_sets = entity_sets, relations = relations, scalars = scalars,
                         platform = platform, model = model, extras = json_object(PLATFORM => extras))
end

"""The depth-first order of the same tree, children sorted by id: the order to_mtg rebuilds without `order`."""
function preorder_by_id(nodes)
    ordered, stack = Any[], Any[first(nodes)]
    while !isempty(stack)
        node = pop!(stack)
        push!(ordered, node)
        append!(stack, sort(children(node); by = node_id, rev = true))
    end
    return ordered
end

# ── Data structure → MTG ────────────────────────────────────────────────

attribute_value(column::AbstractVector, row) = column[row]
attribute_value(column::AbstractMatrix, row) = collect(column[row, :])

function restore(value, text_type)
    text_type === nothing && return value
    return TEXT_TYPES[text_type](value)
end

"""The attributes of each row of `table`: Dict(column => value), without the rows' missing ones."""
function row_attributes(table, missing_of_table, text_types_of_table, skip)
    missing_rows = Dict(name => Set(rows) for (name, rows) in pairs(missing_of_table))
    rows = [Dict{Symbol,Any}() for _ in 1:row_count(table)]
    for (name, column) in table.columns
        name in skip && continue
        absent = get(missing_rows, name, Set{Int}())
        text_type = get(text_types_of_table, name, nothing)
        for row in 1:row_count(table)
            (row - 1) in absent && continue
            rows[row][Symbol(name)] = restore(attribute_value(column, row), text_type)
        end
    end
    return rows
end

"""
    to_mtg(data_structure) -> Node

The `graph` data structure as an MTG (its root node). A data structure written by `from_mtg` is rebuilt as it was:
ids, symbols, scales, indices, links, attributes, the order of children. Another one (e.g. from metafspm) becomes an
MTG with one scale per entity set (its rank), each entity's symbol its label (else its entity set's name), its
variables as attributes, under a `Scene` root holding the scalars.
"""
function FspmTF.to_mtg(data_structure::DataStructure)
    data_structure.kind == "graph" ||
        throw(ArgumentError("data structure '$(data_structure.id)' is a $(data_structure.kind), not a graph"))
    extras = get(data_structure.extras, PLATFORM, json_object())
    missing_rows, text_types = get(extras, "missing", json_object()), get(extras, "text_types", json_object())
    entity_sets = [set for set in data_structure.entity_sets if set.rank !== nothing]
    sort!(entity_sets; by = set -> set.rank)

    # Every entity: its scale, symbol, index, attributes; its parent in the tree and the link to it
    encoding, attributes, tree_parent = Dict{Int64,Any}(), Dict{Int64,Dict{Symbol,Any}}(), Dict{Int64,Tuple{Int64,Symbol}}()
    reserved = (FspmTF.ENTITY_SET_RESERVED..., INDEX_COLUMN)
    for set in entity_sets
        ids = set.columns["id"]
        labels = get(set.columns, "label", fill(set.name, row_count(set)))
        indices = get(set.columns, INDEX_COLUMN, zeros(Int64, row_count(set)))
        rows = row_attributes(set, get(missing_rows, set.name, json_object()), get(text_types, set.name, json_object()),
                              reserved)
        for row in 1:row_count(set)
            encoding[ids[row]] = (symbol = labels[row], index = indices[row], scale = set.rank)
            attributes[ids[row]] = rows[row]
        end
        complexes = get(set.columns, "complex", fill(NO_ID, row_count(set)))
        for row in 1:row_count(set)                                    # complex: by decomposition, '/'
            complexes[row] == NO_ID || (tree_parent[ids[row]] = (complexes[row], :/))
        end
    end
    for relation in data_structure.relations                           # bearers: the link of their label
        startswith(relation.name, "bearer") || continue
        labels = get(relation.columns, "relation", fill("branch", row_count(relation)))
        for (source, target, label) in zip(relation.columns["source"], relation.columns["target"], labels)
            tree_parent[source] = (target, LINKS[label])
        end
    end
    complex_of = Dict{Int64,Int64}()
    for set in entity_sets
        haskey(set.columns, "complex") || continue
        for (id, complex) in zip(set.columns["id"], set.columns["complex"])
            complex == NO_ID || (complex_of[id] = complex)
        end
    end
    for set in entity_sets                                             # parents at the same scale, '<' or '+'
        haskey(set.columns, "parent") || continue
        edge_types = set.columns["edge_type"]
        for (id, parent_id, edge_type) in zip(set.columns["id"], set.columns["parent"], edge_types)
            parent_id == NO_ID && continue
            if get(complex_of, id, NO_ID) != get(complex_of, parent_id, NO_ID)    # in another complex: kept aside
                attributes[id][PARENT_ATTRIBUTE] = parent_id
                attributes[id][EDGE_TYPE_ATTRIBUTE] = edge_type
            else
                tree_parent[id] = (parent_id, edge_type == "successor" ? :< : :+)
            end
        end
    end

    # The root: the scene written by from_mtg, or a new scene when there are several roots or scalars
    roots = sort([id for id in keys(encoding) if !haskey(tree_parent, id)])
    scene_entry = get(extras, "scene", nothing)
    scene_attributes = data_structure.scalars === nothing ? Dict{Symbol,Any}() :
        only(row_attributes(data_structure.scalars, get(missing_rows, "scalars", json_object()),
                            get(text_types, "scalars", json_object()), ()))
    # MTG.jl's ids: the entities' own, unless they start below 1 or are sparse; then 1, 2, ... in their order
    all_ids = sort(collect(keys(encoding)))
    renumbered = !isempty(all_ids) && (first(all_ids) < 1 || last(all_ids) > 2 * length(all_ids) + 1)
    number_of = renumbered ? Dict(id => position for (position, id) in enumerate(all_ids)) : nothing
    mtg_id(id) = renumbered ? number_of[id] : Int(id)
    renumbered && foreach(id -> attributes[id][ID_ATTRIBUTE] = id, all_ids)
    if scene_entry === nothing && length(roots) == 1 && isempty(scene_attributes)
        root_id = only(roots)
        root_encoding = encoding[root_id]
        root = Node(mtg_id(root_id), MutableNodeMTG(:/, Symbol(root_encoding.symbol), root_encoding.index,
                                            root_encoding.scale), attributes[root_id])
        roots = Int64[]
    else
        scene_entry === nothing &&
            (scene_entry = json_object("id" => renumbered ? length(all_ids) + 1 : maximum(all_ids; init = 0) + 1,
                                       "symbol" => "Scene", "index" => 0, "link" => "/"))
        root = Node(Int(scene_entry["id"]), MutableNodeMTG(Symbol(scene_entry["link"]), Symbol(scene_entry["symbol"]),
                                                           Int(scene_entry["index"]), 0), scene_attributes)
        root_id = typemin(Int64)                     # the scene's key among the entities: not an entity's id
    end
    entity_of = Dict{Int,Int64}(mtg_id(id) => id for id in all_ids)    # MTG.jl's id -> the entity's
    entity_of[node_id(root)] = root_id
    children_of = Dict{Int64,Vector{Int64}}()
    for (id, (parent_id, _)) in tree_parent
        push!(get!(children_of, parent_id, Int64[]), id)
    end
    isempty(roots) || (children_of[root_id] = vcat(roots, get(children_of, root_id, Int64[])))
    rank_of = haskey(extras, "order") ? Dict(Int64(id) => position for (position, id) in enumerate(extras["order"])) :
              nothing
    for list in values(children_of)
        rank_of === nothing ? sort!(list) : sort!(list; by = id -> get(rank_of, id, typemax(Int)))
    end
    stack = Any[root]
    while !isempty(stack)
        node = pop!(stack)
        created = Any[]
        for id in get(children_of, entity_of[node_id(node)], Int64[])
            child_encoding = encoding[id]
            child_link = haskey(tree_parent, id) ? tree_parent[id][2] : :/
            push!(created, Node(mtg_id(id), node, MutableNodeMTG(child_link, Symbol(child_encoding.symbol),
                                                              child_encoding.index, child_encoding.scale),
                                attributes[id]))
        end
        append!(stack, reverse(created))
    end

    metadata = get(extras, "metadata", nothing)
    if metadata !== nothing
        metadata_values = Pair{Symbol,Any}[]
        haskey(metadata, "symbols") && push!(metadata_values, :symbols => String.(metadata["symbols"]))
        haskey(metadata, "scales") && push!(metadata_values, :scales => Int.(metadata["scales"]))
        if haskey(metadata, "description") && metadata["description"] === nothing
            push!(metadata_values, :description => nothing)
        elseif haskey(metadata, "description")
            description = metadata["description"]
            column_names = Symbol.(collect(keys(description)))
            columns = AbstractVector[column_values(value) for value in values(description)]
            push!(metadata_values, :description => MultiScaleTreeGraph.ColumnTable(column_names, columns))
        end
        append!(root, (; metadata_values...))
    elseif scene_entry !== nothing
        symbols = unique([(encoding[id].symbol, encoding[id].scale) for id in sort(collect(keys(encoding)))])
        append!(root, (symbols = vcat([string(symbol(root))], [string(item[1]) for item in symbols]),
                       scales = vcat([0], [item[2] for item in symbols])))
    end
    return root
end

column_values(value::AbstractVector) =
    all(item -> item isa AbstractVector, value) ? [String.(item) for item in value] :
    all(item -> item isa AbstractString, value) ? String.(value) : collect(value)

end
