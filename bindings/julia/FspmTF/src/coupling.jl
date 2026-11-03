# A participant's side of a coupling session (specification §11): a platform declares what it works on, provides and
# requires, then answers each turn's inputs with its outputs, as partial frames. The coordinator is fspm-TF's
# (Python: `fspm-tf couple`). Transports: a folder ("files:path", here) and ZeroMQ ("tcp://…", "ipc://…": with ZMQ
# loaded, the package extension FspmTFZMQExt).

"""The version of the coupling protocol this package speaks."""
const PROTOCOL_VERSION = "0.3"
const ENDPOINT_VARIABLE = "FSPM_TF_ENDPOINT"
const PARTICIPANT_VARIABLE = "FSPM_TF_PARTICIPANT"

"""
    EntitySetSpec(data_structure, name; rank=nothing, rights="follows")

An entity set a participant works on: its rank (a base scale's position by default) and its rights on its topology,
`"owns"` (adds and removes its entities), `"refines"` (adds and removes the entities it creates, under others'),
`"follows"` (reads).
"""
struct EntitySetSpec
    data_structure::String
    name::String
    rank::Union{Nothing,Int}
    rights::String
end

function EntitySetSpec(data_structure::AbstractString, name::AbstractString; rank = nothing, rights = "follows")
    rights in ("owns", "refines", "follows") || throw(ArgumentError("rights '$rights': owns, refines or follows"))
    if rank === nothing && name in BASE_SCALES
        rank = findfirst(==(name), BASE_SCALES)
    end
    return EntitySetSpec(String(data_structure), String(name), rank, String(rights))
end

"""
    VariableSpec(data_structure, entity_set, name, direction; unit="1", standard_name=nothing, kind=nothing,
                 optional=false)

A variable a participant provides (`direction` `"provides"`: an output) or requires (`"requires"`: an input).
"""
struct VariableSpec
    data_structure::String
    entity_set::String
    name::String
    direction::String
    unit::String
    standard_name::Union{Nothing,String}
    kind::Union{Nothing,String}
    optional::Bool
end

function VariableSpec(data_structure::AbstractString, entity_set::AbstractString, name::AbstractString,
                      direction::AbstractString; unit = "1", standard_name = nothing, kind = nothing, optional = false)
    direction in ("provides", "requires") || throw(ArgumentError("direction '$direction': provides or requires"))
    return VariableSpec(String(data_structure), String(entity_set), String(name), String(direction), String(unit),
                        standard_name, kind, optional)
end

"""
    MappingSpec(name, source, target)

A mapping a participant provides (its updates carry it, as a frame's `Mapping` of that name): `source` and `target`,
each (data structure, entity set), for links between two data structures.
"""
struct MappingSpec
    name::String
    source::Tuple{String,String}
    target::Tuple{String,String}
end

"""
    Declaration(participant; platform=nothing, entity_sets=EntitySetSpec[], variables=VariableSpec[])

A participant's declaration (its name: `FSPM_TF_PARTICIPANT` when empty and launched by the coordinator).
"""
Base.@kwdef mutable struct Declaration
    participant::String = ""
    platform::Union{Nothing,String} = nothing
    entity_sets::Vector{EntitySetSpec} = EntitySetSpec[]
    variables::Vector{VariableSpec} = VariableSpec[]
    mappings::Vector{MappingSpec} = MappingSpec[]
end

Declaration(participant::AbstractString; kwargs...) = Declaration(; participant = String(participant), kwargs...)

function declaration_json(declaration::Declaration)
    entity_sets = [json_object("dataStructure" => item.data_structure, "name" => item.name, "rank" => item.rank,
                               "rights" => item.rights) for item in declaration.entity_sets]
    for variable in declaration.variables            # an entity set for each one its variables are on, followed
        if !any(item -> (item.data_structure, item.name) == (variable.data_structure, variable.entity_set),
                declaration.entity_sets)
            spec = EntitySetSpec(variable.data_structure, variable.entity_set)
            push!(declaration.entity_sets, spec)
            push!(entity_sets, json_object("dataStructure" => spec.data_structure, "name" => spec.name,
                                           "rank" => spec.rank, "rights" => spec.rights))
        end
    end
    variables = Any[]
    for variable in declaration.variables
        entry = json_object("dataStructure" => variable.data_structure, "entitySet" => variable.entity_set,
                            "name" => variable.name, "direction" => variable.direction, "unit" => variable.unit)
        variable.standard_name === nothing || (entry["standardName"] = variable.standard_name)
        variable.kind === nothing || (entry["kind"] = variable.kind)
        variable.optional && (entry["optional"] = true)
        push!(variables, entry)
    end
    value = json_object("participant" => declaration.participant, "entitySets" => entity_sets,
                        "variables" => variables)
    declaration.platform === nothing || (value["platform"] = declaration.platform)
    isempty(declaration.mappings) || (value["mappings"] = Any[
        json_object("name" => item.name,
                    "source" => json_object("dataStructure" => item.source[1], "entitySet" => item.source[2]),
                    "target" => json_object("dataStructure" => item.target[1], "entitySet" => item.target[2]))
        for item in declaration.mappings])
    return value
end

"""
    declaration_from_json(value) -> Declaration

A declaration from its JSON (e.g. a file's, `JSON.parsefile`).
"""
function declaration_from_json(value)
    entity_sets = [EntitySetSpec(item["dataStructure"], item["name"]; rank = get(item, "rank", nothing),
                                 rights = get(item, "rights", "follows")) for item in get(value, "entitySets", Any[])]
    variables = [VariableSpec(item["dataStructure"], item["entitySet"], item["name"], item["direction"];
                              unit = get(item, "unit", "1"), standard_name = get(item, "standardName", nothing),
                              kind = get(item, "kind", nothing), optional = get(item, "optional", false))
                 for item in get(value, "variables", Any[])]
    mappings = [MappingSpec(item["name"], (item["source"]["dataStructure"], item["source"]["entitySet"]),
                            (item["target"]["dataStructure"], item["target"]["entitySet"]))
                for item in get(value, "mappings", Any[])]
    return Declaration(; participant = String(value["participant"]), platform = get(value, "platform", nothing),
                       entity_sets, variables, mappings)
end

"""
    Link(receiver, variable, provider, source; entity_set=nothing, source_entity_set=nothing, factor=1.0,
         aggregation=nothing, interpolation="hold")

An input's provider, as a participant may propose it to the coordinator (see the Python `Link`).
"""
Base.@kwdef struct Link
    receiver::String
    variable::String
    provider::String
    source::String
    entity_set::Union{Nothing,String} = nothing
    source_entity_set::Union{Nothing,String} = nothing
    factor::Float64 = 1.0
    aggregation::Union{Nothing,String} = nothing
    interpolation::String = "hold"
    mapping::Union{Nothing,String} = nothing
end

Link(receiver, variable, provider, source; kwargs...) =
    Link(; receiver = String(receiver), variable = String(variable), provider = String(provider),
         source = String(source), kwargs...)

function link_json(link::Link)
    value = json_object("receiver" => link.receiver, "variable" => link.variable, "provider" => link.provider,
                        "source" => link.source)
    link.entity_set === nothing || (value["entitySet"] = link.entity_set)
    link.source_entity_set === nothing || (value["sourceEntitySet"] = link.source_entity_set)
    link.aggregation === nothing || (value["aggregation"] = link.aggregation)
    link.factor == 1.0 || (value["factor"] = link.factor)
    link.interpolation == "hold" || (value["interpolation"] = link.interpolation)
    link.mapping === nothing || (value["mapping"] = link.mapping)
    return value
end

# ── transports ───────────────────────────────────────────────────────────────────
"""A participant's channel: `send_message(channel, header, payload)`, `receive_message(channel, timeout)`."""
abstract type CouplingChannel end

"""A participant's folder queues: `<folder>/<participant>/to_coordinator/` and `to_participant/`."""
mutable struct FolderChannel <: CouplingChannel
    incoming::String
    outgoing::String
    next_read::Int
    next_write::Int
    keep::Bool                       # false: a message's files deleted once read
    read_files::Vector{String}       # those of the messages read and kept
end

FolderChannel(incoming, outgoing, next_read, next_write) =
    FolderChannel(incoming, outgoing, next_read, next_write, true, String[])

function FolderChannel(folder::AbstractString, participant::AbstractString)
    incoming = joinpath(folder, participant, "to_participant")
    outgoing = joinpath(folder, participant, "to_coordinator")
    mkpath(incoming)
    mkpath(outgoing)
    return FolderChannel(incoming, outgoing, 0, 0)
end

stem(folder, number) = joinpath(folder, lpad(number, 8, '0'))

function send_message(channel::FolderChannel, header::AbstractDict, payload = nothing)
    path = stem(channel.outgoing, channel.next_write)
    header = copy(header)
    if payload !== nothing
        write(path * ".glb", payload)
        header["payload"] = basename(path) * ".glb"
    end
    write(path * ".json.part", JSON.json(header))
    mv(path * ".json.part", path * ".json"; force = true)
    channel.next_write += 1
    return nothing
end

function receive_message(channel::FolderChannel, timeout = nothing)
    path = stem(channel.incoming, channel.next_read)
    deadline = timeout === nothing ? nothing : time() + timeout
    while !isfile(path * ".json")
        deadline !== nothing && time() > deadline && throw(ErrorException("no message in $timeout s"))
        sleep(0.005)
    end
    header = JSON.parse(read(path * ".json", String))
    files = [path * ".json"]
    payload = nothing
    if haskey(header, "payload")
        push!(files, joinpath(channel.incoming, pop!(header, "payload")))
        payload = read(files[end])
    end
    channel.next_read += 1
    channel.keep ? append!(channel.read_files, files) : foreach(rm, files)
    return header, payload
end

close_channel(::CouplingChannel) = nothing

"""As the session says (its welcome's `keepMessages`): keep the messages read, or delete them, those read so far too."""
keep_messages!(::CouplingChannel, keep::Bool) = nothing
function keep_messages!(channel::FolderChannel, keep::Bool)
    keep && return nothing
    channel.keep = false
    foreach(path -> isfile(path) && rm(path), channel.read_files)
    empty!(channel.read_files)
    return nothing
end

"""
    zmq_channel(endpoint, participant) -> CouplingChannel

A participant's ZeroMQ channel (a DEALER socket named after it). Defined when ZMQ is loaded (`FspmTFZMQExt`).
"""
function zmq_channel end

function participant_channel(endpoint::AbstractString, participant::AbstractString)
    startswith(endpoint, "files:") && return FolderChannel(endpoint[length("files:")+1:end], participant)
    hasmethod(zmq_channel, Tuple{String,String}) ||
        throw(ArgumentError("the endpoint $endpoint needs ZeroMQ: `using ZMQ` (or use a folder, \"files:path\")"))
    return zmq_channel(String(endpoint), String(participant))
end

# ── the participant ──────────────────────────────────────────────────────────────
"""
    Turn

A turn: `step` (0: the initial state, phase `"init"`), the time it starts from and the time it reaches (`until`), and
`frame`, the participant's inputs (its entity sets, their entities, its inputs; in `frame.update.removed` the entities
removed since its last turn).
"""
struct Turn
    step::Int
    phase::String
    time::Float64
    until::Float64
    frame::Frame
end

"""
    Participant

A participant in a session (`Participant(declaration; …)` joins it). `id_offset`: the ids of the entities it creates are in
`[id_offset, id_offset + id_count)`.
"""
mutable struct Participant
    channel::CouplingChannel
    declaration::Declaration
    id_offset::Int64
    id_count::Int64
    session::Any
    couplings::Vector{Any}
    step::Int
    stopped::Union{Nothing,String}
    timeout::Union{Nothing,Float64}
end

"""
    Participant(declaration; endpoint=ENV["FSPM_TF_ENDPOINT"], links=Link[], timeout=nothing) -> Participant

Join the session at `endpoint`: send the declaration and the links it proposes, wait for the welcome.
"""
function Participant(declaration::Declaration; endpoint = get(ENV, ENDPOINT_VARIABLE, ""), links = Link[],
                     timeout = nothing)
    isempty(endpoint) && throw(ArgumentError("no endpoint: give one, or set $ENDPOINT_VARIABLE"))
    isempty(declaration.participant) && (declaration.participant = get(ENV, PARTICIPANT_VARIABLE, ""))
    channel = participant_channel(endpoint, declaration.participant)
    send_message(channel, json_object("type" => "hello", "protocol" => PROTOCOL_VERSION,
                                      "declaration" => declaration_json(declaration),
                                      "links" => Any[link_json(link) for link in links]))
    header, _ = receive_message(channel, timeout)
    header["type"] == "stop" && error("the coordinator refused $(declaration.participant): $(get(header, "reason", ""))")
    header["type"] == "welcome" || error("expected a welcome, got $(header["type"])")
    keep_messages!(channel, get(header["session"], "keepMessages", true))
    return Participant(channel, declaration, Int64(header["idOffset"]), Int64(header["idCount"]), header["session"],
                       collect(get(header, "couplings", Any[])), -1, nothing, timeout === nothing ? nothing :
                       Float64(timeout))
end

"""
    next_turn(participant) -> Union{Turn,Nothing}

The next turn, or `nothing` when the coordinator stopped the session (`participant.stopped`: its reason).
"""
function next_turn(participant::Participant)
    header, payload = receive_message(participant.channel, participant.timeout)
    if header["type"] == "stop"
        participant.stopped = String(get(header, "reason", ""))
        close_channel(participant.channel)
        return nothing
    end
    header["type"] == "turn" || error("expected a turn, got $(header["type"])")
    participant.step = Int(header["step"])
    return Turn(Int(header["step"]), String(header["phase"]), Float64(header["time"]), Float64(header["until"]),
                from_bytes(payload))
end

"""Iterate a participant's turns: `for turn in turns(participant) … end`."""
struct Turns
    participant::Participant
end
turns(participant::Participant) = Turns(participant)
Base.IteratorSize(::Type{Turns}) = Base.SizeUnknown()
Base.eltype(::Type{Turns}) = Turn
function Base.iterate(turns::Turns, state = nothing)
    turn = next_turn(turns.participant)
    return turn === nothing ? nothing : (turn, nothing)
end

"""
    send_update(participant, frame)

Send the turn's outputs: per entity set, the ids and outputs of the rows sent (and the topology columns of the
entities it adds or changes); in `frame.update.removed`, the entities it removed.
"""
function send_update(participant::Participant, frame::Frame)
    frame.update === nothing && (frame.update = Update(participant.declaration.participant))
    frame.update.participant = participant.declaration.participant
    send_message(participant.channel, json_object("type" => "update", "step" => participant.step), to_bytes(frame))
    return nothing
end

"""
    fail(participant, message)

Tell the coordinator this participant cannot go on (the session stops).
"""
fail(participant::Participant, message::AbstractString) =
    send_message(participant.channel, json_object("type" => "error", "message" => String(message)))
