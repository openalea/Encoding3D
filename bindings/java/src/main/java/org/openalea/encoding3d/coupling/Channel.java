package org.openalea.encoding3d.coupling;

import com.fasterxml.jackson.databind.node.ObjectNode;

/** A participant's channel to the coordinator: a message is a JSON header and, for turns and updates, a partial frame's GLB bytes. */
public interface Channel extends AutoCloseable {
    /** A received message: its header, and its payload or null. */
    record Message(ObjectNode header, byte[] payload) {}

    void send(ObjectNode header, byte[] payload);

    /** The next message; Encoding3dException after {@code timeout} seconds without one (null: wait). */
    Message receive(Double timeout);

    /** As the session says (its welcome's keepMessages): keep the messages read, or delete them (the folder transport). */
    default void keepMessages(boolean keep) {}

    @Override
    default void close() {}

    /** A participant's channel to {@code endpoint}: "files:path" (a folder), or a ZeroMQ endpoint (JeroMQ). */
    static Channel of(String endpoint, String participant) {
        if (endpoint.startsWith("files:")) return new FolderChannel(endpoint.substring("files:".length()), participant);
        return new ZmqChannel(endpoint, participant);
    }
}
