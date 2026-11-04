package org.openalea.encoding3d.coupling;

import java.nio.file.Files;
import java.nio.file.Path;

import org.openalea.encoding3d.Codec;
import org.openalea.encoding3d.Dump;

import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * The Java participant under test in the coupling conformance sessions (conformance/coupling, specification §9):
 * launched by the coordinator as {@code java ... ConformanceParticipant SESSION OUT}, it joins with the session's
 * subject/declaration.json, writes what it reads from each turn to OUT/turn_&lt;step&gt;.json, and sends
 * subject/update_&lt;step&gt;.glb as read and written again by this codec.
 */
public final class ConformanceParticipant {
    private ConformanceParticipant() {}

    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 2) {
            System.err.println("usage: ConformanceParticipant SESSION OUT");
            System.exit(2);
        }
        Path session = Path.of(arguments[0]), out = Path.of(arguments[1]);
        Files.createDirectories(out);
        ObjectNode declaration = (ObjectNode) Json.MAPPER.readTree(session.resolve("subject").resolve("declaration.json").toFile());
        try (Participant participant = new Participant(declaration, null, null, 120.0)) {
            for (Turn turn; (turn = participant.nextTurn()) != null; ) {
                String step = String.format("%04d", turn.step());
                Json.MAPPER.writerWithDefaultPrettyPrinter().writeValue(out.resolve("turn_" + step + ".json").toFile(),
                        Dump.frameToJson(turn.frame()));
                byte[] update = Files.readAllBytes(session.resolve("subject").resolve("update_" + step + ".glb"));
                participant.sendUpdate(Codec.fromBytes(Codec.toBytes(Codec.fromBytes(update))));
            }
        }
    }
}
