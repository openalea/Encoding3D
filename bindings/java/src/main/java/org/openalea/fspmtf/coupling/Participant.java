package org.openalea.fspmtf.coupling;

import org.openalea.fspmtf.Codec;
import org.openalea.fspmtf.FspmTfException;
import org.openalea.fspmtf.Frame;
import org.openalea.fspmtf.Update;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * A participant's side of a coupling session (specification §11). Joining sends the declaration (its JSON, see
 * spec/schema/coupling.schema.json) and the links it proposes, and waits for the welcome; then
 *
 * <pre>
 *     for (Turn turn; (turn = participant.nextTurn()) != null; ) {   // until the coordinator stops the session
 *         ... turn.frame(): its entity sets, their entities, its inputs
 *         participant.sendUpdate(frame);                             // its outputs and topology changes
 *     }
 * </pre>
 *
 * The ids of the entities it creates are in [idOffset, idOffset + idCount).
 */
public final class Participant implements AutoCloseable {
    public static final String PROTOCOL_VERSION = "0.3";
    public static final String ENDPOINT_VARIABLE = "FSPM_TF_ENDPOINT";
    public static final String PARTICIPANT_VARIABLE = "FSPM_TF_PARTICIPANT";

    public final String name;
    public final long idOffset;
    public final long idCount;
    public final JsonNode session;
    public final JsonNode couplings;
    public String stopped;
    private final Channel channel;
    private final Double timeout;
    private long step = -1;

    /** Joins the session at {@code endpoint} (null: the environment's FSPM_TF_ENDPOINT); the declaration's participant
     * name, if empty, from FSPM_TF_PARTICIPANT; {@code links}: null for none; {@code timeout}: seconds, null to wait. */
    public Participant(ObjectNode declaration, String endpoint, ArrayNode links, Double timeout) {
        this.timeout = timeout;
        if (endpoint == null) endpoint = System.getenv(ENDPOINT_VARIABLE);
        if (endpoint == null || endpoint.isEmpty()) throw new FspmTfException("no endpoint: give one, or set " + ENDPOINT_VARIABLE);
        String own = declaration.path("participant").asText("");
        if (own.isEmpty()) {
            own = System.getenv(PARTICIPANT_VARIABLE);
            declaration.put("participant", own);
        }
        name = own;
        channel = Channel.of(endpoint, name);
        ObjectNode hello = Json.MAPPER.createObjectNode().put("type", "hello").put("protocol", PROTOCOL_VERSION);
        hello.set("declaration", declaration);
        hello.set("links", links == null ? Json.MAPPER.createArrayNode() : links);
        channel.send(hello, null);
        Channel.Message welcome = channel.receive(timeout);
        String type = welcome.header().path("type").asText();
        if (type.equals("stop"))
            throw new FspmTfException("the coordinator refused " + name + ": " + welcome.header().path("reason").asText());
        if (!type.equals("welcome")) throw new FspmTfException("expected a welcome, got " + type);
        idOffset = welcome.header().get("idOffset").asLong();
        idCount = welcome.header().get("idCount").asLong();
        session = welcome.header().get("session");
        couplings = welcome.header().path("couplings");
    }

    /** The next turn, or null when the coordinator stopped the session ({@link #stopped}: its reason). */
    public Turn nextTurn() {
        Channel.Message message = channel.receive(timeout);
        String type = message.header().path("type").asText();
        if (type.equals("stop")) {
            stopped = message.header().path("reason").asText("");
            return null;
        }
        if (!type.equals("turn")) throw new FspmTfException("expected a turn, got " + type);
        JsonNode header = message.header();
        step = header.get("step").asLong();
        return new Turn(step, header.get("phase").asText(), header.get("time").asDouble(), header.get("until").asDouble(),
                Codec.fromBytes(message.payload()));
    }

    /** Sends the turn's outputs: per entity set, the ids and outputs of the rows sent (and the topology columns of the
     * entities it adds or changes); in frame.update.removed, the entities it removed. */
    public void sendUpdate(Frame frame) {
        if (frame.update == null) frame.update = new Update(name);
        frame.update.participant = name;
        channel.send(Json.MAPPER.createObjectNode().put("type", "update").put("step", step), Codec.toBytes(frame));
    }

    /** Tells the coordinator this participant cannot go on (the session stops). */
    public void fail(String message) {
        channel.send(Json.MAPPER.createObjectNode().put("type", "error").put("message", message), null);
    }

    @Override
    public void close() throws Exception {
        channel.close();
    }
}
