package org.openalea.encoding3d.coupling;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

import org.openalea.encoding3d.Encoding3dException;

import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * A participant's folder queues: {@code <folder>/<participant>/to_coordinator/} and {@code to_participant/}. Message n
 * is {@code n.json} (its header, n as 8 digits) and {@code n.glb} (its payload), the payload written first and the
 * header renamed into place last.
 */
public final class FolderChannel implements Channel {
    private final Path incoming, outgoing;
    private long nextRead = 0, nextWrite = 0;
    private boolean keep = true;                                       // false: a message's files deleted once read
    private final java.util.List<Path> readFiles = new java.util.ArrayList<>();   // those read and kept

    public FolderChannel(String folder, String participant) {
        incoming = Path.of(folder, participant, "to_participant");
        outgoing = Path.of(folder, participant, "to_coordinator");
        try {
            Files.createDirectories(incoming);
            Files.createDirectories(outgoing);
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        }
    }

    private static String numbered(long number) {
        return String.format("%08d", number);
    }

    @Override
    public void send(ObjectNode header, byte[] payload) {
        String stem = numbered(nextWrite);
        ObjectNode written = header.deepCopy();
        try {
            if (payload != null) {
                Files.write(outgoing.resolve(stem + ".glb"), payload);
                written.put("payload", stem + ".glb");
            }
            Path part = outgoing.resolve(stem + ".json.part");
            Files.writeString(part, written.toString());
            Files.move(part, outgoing.resolve(stem + ".json"), StandardCopyOption.ATOMIC_MOVE);
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        }
        nextWrite++;
    }

    @Override
    public void keepMessages(boolean keep) {
        if (keep) return;
        this.keep = false;
        try {
            for (Path file : readFiles) Files.deleteIfExists(file);
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        }
        readFiles.clear();
    }

    @Override
    public Message receive(Double timeout) {
        Path header = incoming.resolve(numbered(nextRead) + ".json");
        long start = System.nanoTime();
        try {
            while (!Files.exists(header)) {
                if (timeout != null && (System.nanoTime() - start) / 1e9 > timeout)
                    throw new Encoding3dException("no message in " + timeout + " s");
                Thread.sleep(5);
            }
            ObjectNode read = (ObjectNode) Json.MAPPER.readTree(Files.readString(header));
            java.util.List<Path> files = new java.util.ArrayList<>(java.util.List.of(header));
            byte[] payload = null;
            if (read.has("payload")) {
                files.add(incoming.resolve(read.get("payload").asText()));
                payload = Files.readAllBytes(files.get(1));
                read.remove("payload");
            }
            nextRead++;
            if (keep) readFiles.addAll(files);
            else for (Path file : files) Files.delete(file);
            return new Message(read, payload);
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new Encoding3dException("interrupted while waiting for a message");
        }
    }
}
