# encoding3d.jl's participant under test in the coupling conformance sessions (conformance/coupling, specification §9):
# launched by the coordinator as `julia --project=… coupling_conformance.jl SESSION OUT`, it joins with the session's
# subject/declaration.json, writes what it reads from each turn to OUT/turn_<step>.json, and sends
# subject/update_<step>.glb as read and written again by encoding3d.jl.
#
#     encoding3d couple-conformance conformance/coupling --participant "julia --project=env bindings/julia/coupling_conformance.jl"
using encoding3d
using JSON
using ZMQ

function main(session::AbstractString, out::AbstractString)
    mkpath(out)
    declaration = declaration_from_json(JSON.parsefile(joinpath(session, "subject", "declaration.json")))
    participant = Participant(declaration; timeout = 120)
    for turn in turns(participant)
        write_dump(joinpath(out, "turn_$(lpad(turn.step, 4, '0')).json"), turn.frame)
        update = from_bytes(to_bytes(read_frame(joinpath(session, "subject", "update_$(lpad(turn.step, 4, '0')).glb"))))
        send_update(participant, update)
    end
    return 0
end

exit(main(ARGS[1], ARGS[2]))
