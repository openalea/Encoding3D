# Tutorial 3, VirtualPlantLab's side: a carbon model (a toy) as a participant of an encoding3d coupling session.
# Launched by the coordinator (the notebook), which gives it the session's address. It splits each of metafspm's root
# segments into two layers, grown by a PlantGraphs rule, and gives each layer a sugar (hexose) concentration from its
# segment's structural mass in mg (metafspm sends grams: the coordinator converts): (rank + 1) / (1 + mass), computed
# on the graph by a query.
using encoding3d
using PlantGraphs
using ZMQ                                            # the ZeroMQ transport (a folder works without it)

struct Tissue <: Node end
struct Bud <: Node end
mutable struct Layer <: Node
    segment::Int64                                   # its segment's id in the session
    rank::Int                                        # 0: the outer layer, 1: the inner one
    hexose::Float64
end
const NEW_SEGMENTS = Int64[]                         # the segments to split at the next rewriting

# the rule: the bud adds two layers for each new segment, and stays to add more later
split_segments = Rule(Bud, rhs = bud -> begin
    isempty(NEW_SEGMENTS) ? Bud() : Bud() + Tuple(Layer(segment, 0, 0.0) + Layer(segment, 1, 0.0) for segment in NEW_SEGMENTS)
end)
tissue = Graph(axiom = Tissue() + Bud(), rules = split_segments)

# what it does in the session: it follows metafspm's segments, adds its own layers under them, needs their structural
# mass, gives their hexose concentration
declaration = Declaration("carbon"; platform = "VirtualPlantLab",
    entity_sets = [EntitySetSpec("plant", "SubOrgan"), EntitySetSpec("plant", "Layer"; rights = "refines")],
    variables = [VariableSpec("plant", "Layer", "struct_mass", "requires"; unit = "mg", kind = "extensive"),
                 VariableSpec("plant", "Layer", "hexose", "provides"; unit = "mol.g-1", kind = "massic_concentration")])
participant = Participant(declaration; timeout = 600)
offset = participant.id_offset                       # the ids of the layers it creates start there
split = Set{Int64}()

layers_of(tissue) = entity_set(from_graph(tissue; id = "plant", entity_set = "Layer", rank = 7,
                                          keep = node -> node isa Layer), "Layer")

for turn in turns(participant)
    plant = data_structure(turn.frame, "plant")
    # each segment's structural mass (mg), from its layers (the coordinator copies a segment's mass to its layers)
    mass = Dict{Int64,Float64}()
    if any(set -> set.name == "Layer", plant.entity_sets)
        received, mine = entity_set(plant, "Layer"), layers_of(tissue)
        segment_of = Dict(id + offset => segment for (id, segment) in zip(mine.columns["id"], mine.columns["segment"]))
        for (layer, value) in zip(received.columns["id"], received.columns["struct_mass"])
            isnan(value) || (mass[segment_of[layer]] = value)
        end
    end
    # the new segments split by the rule, then every layer's hexose by a query
    empty!(NEW_SEGMENTS)
    append!(NEW_SEGMENTS, [segment for segment in entity_set(plant, "SubOrgan").columns["id"] if !(segment in split)])
    union!(split, NEW_SEGMENTS)
    rewrite!(tissue)
    for layer in apply(tissue, Query(Layer))
        layer.hexose = (layer.rank + 1) / (1 + get(mass, layer.segment, 0.0))
    end
    # its layers sent: ids in its range, under their segment
    layers = layers_of(tissue)
    columns = encoding3d.Columns(
        "id" => layers.columns["id"] .+ offset,
        "complex" => Vector{Int64}(layers.columns["segment"]),
        "parent" => [parent == NO_ID ? NO_ID : parent + offset for parent in layers.columns["parent"]],
        "edge_type" => layers.columns["edge_type"],
        "label" => layers.columns["label"],
        "hexose" => Vector{Float64}(layers.columns["hexose"]))
    send_update(participant, Frame(data_structures = [DataStructure("plant";
        entity_sets = [EntitySet("Layer"; columns = columns, rank = 7)])]))
end
println("carbon: the session ended (", participant.stopped, ")")
