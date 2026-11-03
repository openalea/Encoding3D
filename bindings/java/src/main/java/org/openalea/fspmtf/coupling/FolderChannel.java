package org.openalea.fspmtf.coupling;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

import org.openalea.fspmtf.FspmTfException;

import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * A participant's folder queues: {@code <folder>/<participant>/to_coordinator/} and {@code to_participant/}. Message n
 * is {@code n.json} (its header, n as 8 digits) and {@code n.glb} (its payload), the payload written first and the
 * header renamed into place last.
 */
public final class FolderChannel implements Channel {
    private final Path incoming, outgoing;
    private long nextRead = 0, nextWrite = 0;

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
    public Message receive(Double timeout) {
        Path header = incoming.resolve(numbered(nextRead) + ".json");
        long start = System.nanoTime();
        try {
            while (!Files.exists(header)) {
                if (timeout != null && (System.nanoTime() - start) / 1e9 > timeout)
                    throw new FspmTfException("no message in " + timeout + " s");
                Thread.sleep(5);
            }
            ObjectNode read = (ObjectNode) Json.MAPPER.readTree(Files.readString(header));
            byte[] payload = null;
            if (read.has("payload")) {
                payload = Files.readAllBytes(incoming.resolve(read.get("payload").asText()));
                read.remove("payload");
            }
            nextRead++;
            return new Message(read, payload);
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new FspmTfException("interrupted while waiting for a message");
        }
    }
}
