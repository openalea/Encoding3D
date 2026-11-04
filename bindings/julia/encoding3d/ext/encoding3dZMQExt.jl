# The coupling's ZeroMQ transport: a participant's DEALER socket, named after it, connected to the coordinator's
# ROUTER socket; a message is its JSON header and, for turns and updates, a partial frame's GLB bytes.
module encoding3dZMQExt

using encoding3d
using JSON
using ZMQ

mutable struct ZmqChannel <: encoding3d.CouplingChannel
    socket::ZMQ.Socket
end

function encoding3d.zmq_channel(endpoint::String, participant::String)
    socket = ZMQ.Socket(ZMQ.DEALER)
    socket.routing_id = participant
    socket.linger = 1000
    ZMQ.connect(socket, endpoint)
    return ZmqChannel(socket)
end

function encoding3d.send_message(channel::ZmqChannel, header::AbstractDict, payload = nothing)
    parts = payload === nothing ? [JSON.json(header)] : [Vector{UInt8}(codeunits(JSON.json(header))), payload]
    ZMQ.send_multipart(channel.socket, parts)
    return nothing
end

function encoding3d.receive_message(channel::ZmqChannel, timeout = nothing)
    channel.socket.rcvtimeo = timeout === nothing ? -1 : round(Int, 1000 * timeout)
    parts = ZMQ.recv_multipart(channel.socket, Vector{UInt8})
    header = JSON.parse(String(parts[1]))
    return header, length(parts) > 1 ? parts[2] : nothing
end

encoding3d.close_channel(channel::ZmqChannel) = close(channel.socket)

end
