# A Julia participant for the coupling tests (bindings/python/test/test_coupling.py launches it with the Python
# coordinator): the "function" of the two-scale session. It refines each organ it is sent into two segments and
# provides each segment's sugar, 1e-6 mol per m of its length (its input).
using encoding3d
using ZMQ

declaration = Declaration("function"; platform = "julia-test",
    entity_sets = [EntitySetSpec("plant", "Organ"), EntitySetSpec("plant", "SubOrgan"; rights = "refines")],
    variables = [VariableSpec("plant", "SubOrgan", "segment_length", "requires"; unit = "m", standard_name = "length"),
                 VariableSpec("plant", "SubOrgan", "sugar", "provides"; unit = "mol", kind = "extensive")])
participant = Participant(declaration; timeout = 60)

segments = Dict{Int64,Tuple{Int64,Int64}}()          # segment id => (its organ, its parent)
order = Int64[]                                      # the segments in creation order
for turn in turns(participant)
    plant = data_structure(turn.frame, "plant")
    removed = get(turn.frame.update.removed, ("plant", "SubOrgan"), Int64[])
    for segment in removed
        delete!(segments, segment)
    end
    filter!(segment -> haskey(segments, segment), order)
    lengths = Dict{Int64,Float64}()
    if any(set -> set.name == "SubOrgan", plant.entity_sets)
        known = entity_set(plant, "SubOrgan")
        for (identifier, length) in zip(known.columns["id"], known.columns["segment_length"])
            lengths[identifier] = isnan(length) ? 0.0 : length
        end
    end
    with_segments = Set(first(value) for value in values(segments))
    for organ in entity_set(plant, "Organ").columns["id"]
        organ in with_segments && continue
        start = participant.id_offset + length(segments) + 2 * turn.step * 1000
        segments[start] = (organ, NO_ID)
        segments[start+1] = (organ, start)
        push!(order, start, start + 1)
    end
    columns = encoding3d.Columns(
        "id" => order,
        "complex" => [segments[segment][1] for segment in order],
        "parent" => [segments[segment][2] for segment in order],
        "edge_type" => [segments[segment][2] == NO_ID ? "none" : "successor" for segment in order],
        "sugar" => [1e-6 * get(lengths, segment, 0.0) for segment in order])
    send_update(participant, Frame(data_structures = [DataStructure("plant";
        entity_sets = [EntitySet("SubOrgan"; columns = columns, rank = 6)])]))
end
