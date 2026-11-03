package org.openalea.fspmtf.coupling;

import java.nio.charset.StandardCharsets;

import org.openalea.fspmtf.FspmTfException;
import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * A DEALER socket named after the participant (JeroMQ, an optional dependency: needed only for this transport),
 * connected to the coordinator's ROUTER socket; a message is one or two frames, its header then its payload.
 */
public final class ZmqChannel implements Channel {
    private final ZContext context = new ZContext();
    private final ZMQ.Socket socket;

    public ZmqChannel(String endpoint, String participant) {
        socket = context.createSocket(SocketType.DEALER);
        socket.setIdentity(participant.getBytes(StandardCharsets.UTF_8));
        socket.setLinger(1000);
        socket.connect(endpoint);
    }

    @Override
    public void send(ObjectNode header, byte[] payload) {
        byte[] text = header.toString().getBytes(StandardCharsets.UTF_8);
        if (payload == null) socket.send(text, 0);
        else {
            socket.send(text, ZMQ.SNDMORE);
            socket.send(payload, 0);
        }
    }

    @Override
    public Message receive(Double timeout) {
        try (ZMQ.Poller poller = context.createPoller(1)) {
            poller.register(socket, ZMQ.Poller.POLLIN);
            if (poller.poll(timeout == null ? -1 : (long) (timeout * 1000)) <= 0)
                throw new FspmTfException("no message in " + timeout + " s");
        }
        byte[] header = socket.recv(0);
        byte[] payload = socket.hasReceiveMore() ? socket.recv(0) : null;
        try {
            return new Message((ObjectNode) Json.MAPPER.readTree(header), payload);
        } catch (java.io.IOException error) {
            throw new FspmTfException("an unreadable message header: " + error.getMessage());
        }
    }

    @Override
    public void close() {
        context.close();
    }
}
