# The coupling's ZeroMQ transport: a participant's DEALER socket, named after it, connected to the coordinator's
# ROUTER socket; a message is its JSON header and, for turns and updates, a partial frame's GLB bytes.
module FspmTFZMQExt

using FspmTF
using JSON
using ZMQ

mutable struct ZmqChannel <: FspmTF.CouplingChannel
    socket::ZMQ.Socket
end

function FspmTF.zmq_channel(endpoint::String, participant::String)
    socket = ZMQ.Socket(ZMQ.DEALER)
    socket.routing_id = participant
    socket.linger = 1000
    ZMQ.connect(socket, endpoint)
    return ZmqChannel(socket)
end

function FspmTF.send_message(channel::ZmqChannel, header::AbstractDict, payload = nothing)
    parts = payload === nothing ? [JSON.json(header)] : [Vector{UInt8}(codeunits(JSON.json(header))), payload]
    ZMQ.send_multipart(channel.socket, parts)
    return nothing
end

function FspmTF.receive_message(channel::ZmqChannel, timeout = nothing)
    channel.socket.rcvtimeo = timeout === nothing ? -1 : round(Int, 1000 * timeout)
    parts = ZMQ.recv_multipart(channel.socket, Vector{UInt8})
    header = JSON.parse(String(parts[1]))
    return header, length(parts) > 1 ? parts[2] : nothing
end

FspmTF.close_channel(channel::ZmqChannel) = close(channel.socket)

end
