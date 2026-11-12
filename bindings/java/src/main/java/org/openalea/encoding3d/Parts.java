package org.openalea.encoding3d;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.TreeSet;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Shared parts (specification §12.1): their content key (the SHA-256 of their GLB bytes), their GLB files (a template
 * as a frame of its data structure, an operator as a frame of no data structure, its arrays in the binary chunk,
 * FSPM_scene.part saying which), and where a frame finds them: embedded, else at parts/&lt;key&gt;.glb next to it.
 */
public final class Parts {
    /** The folder of a sequence's parts, next to its frames. */
    public static final String FOLDER = "parts";

    private Parts() {}

    /** A part's key: the SHA-256 of its GLB bytes, in lower-case hexadecimal. */
    public static String contentKey(byte[] data) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("every Java platform has SHA-256", error);
        }
    }

    /** The GLB file of a shared part. */
    public static byte[] toBytes(Part part) {
        if (part instanceof Template template) {
            Frame frame = new Frame();
            DataStructure copy = new DataStructure(template.dataStructure.id, template.dataStructure.kind);
            copy.entitySets.addAll(template.dataStructure.entitySets);
            copy.relations.addAll(template.dataStructure.relations);
            copy.meshes.addAll(template.dataStructure.meshes);
            copy.labels.putAll(template.dataStructure.labels);
            copy.extras = template.dataStructure.extras;
            for (int index = 0; index < copy.entitySets.size(); index++) {      // an entity set without ids: its rows
                EntitySet set = copy.entitySets.get(index);
                if (set.has("id") || set.columns.isEmpty()) continue;
                EntitySet withIds = new EntitySet(set.name, set.rank);
                withIds.scale = set.scale;
                withIds.set("id", Column.of(set.ids()));
                set.columns.forEach(withIds::set);
                withIds.variables.putAll(set.variables);
                copy.entitySets.set(index, withIds);
            }
            frame.dataStructures.add(copy);
            return Codec.encodeFrame(frame, false, buffers -> Glb.MAPPER.createObjectNode().put("kind", "template"));
        }
        Operator operator = (Operator) part;
        return Codec.encodeFrame(new Frame(), false, buffers -> {
            ObjectNode entry = Glb.MAPPER.createObjectNode().put("kind", "operator").put("format", operator.format)
                    .put("rows", operator.rows).put("columns", operator.columns);
            switch (operator.format) {
                case "dense" -> entry.put("values", buffers.add(Codec.bytesOf(Column.of(operator.values))));
                case "csr" -> sparse(entry, operator.sparse, buffers);
                case "solve" -> {
                    sparse(entry.putObject("system"), operator.system, buffers);
                    sparse(entry.putObject("rightHandSide"), operator.rightHandSide, buffers);
                }
                default -> throw new Encoding3dException("operator format '" + operator.format + "': dense, csr or solve");
            }
            return entry;
        });
    }

    private static void sparse(ObjectNode entry, SparseMatrix matrix, Glb.BufferBuilder buffers) {
        entry.put("indptr", buffers.add(Codec.bytesOf(Column.of(matrix.indptr()))))
                .put("indices", buffers.add(Codec.bytesOf(Column.of(matrix.indices()))))
                .put("values", buffers.add(Codec.bytesOf(Column.of(matrix.values()))));
    }

    /** The part of a part's GLB bytes; {@code key}, when not null, checked against the bytes' hash. */
    public static Part read(byte[] data, String key) {
        String actual = contentKey(data);
        if (key != null && !key.equals(actual))
            throw new Encoding3dException("part " + key + ": its bytes hash to " + actual + " (the file is not the part its name says)");
        Glb.Contents contents = Glb.unpack(data);
        JsonNode described = contents.document().path("extensions").path("FSPM_scene").get("part");
        if (described == null) throw new Encoding3dException("part " + actual + ": not a part (no FSPM_scene.part)");
        String kind = described.path("kind").asText("");
        if (kind.equals("template")) {
            Frame frame = Codec.fromBytes(data);
            if (frame.dataStructures.size() != 1)
                throw new Encoding3dException("part " + actual + ": a template holds one data structure");
            Template template = new Template();
            template.dataStructure = frame.dataStructures.get(0);
            return template;
        }
        if (!kind.equals("operator"))
            throw new Encoding3dException("part " + actual + ": kind '" + kind + "' is not template or operator");
        int rows = described.get("rows").asInt(), columns = described.get("columns").asInt();
        String format = described.get("format").asText();
        return switch (format) {
            case "dense" -> Operator.dense(rows, columns, doubles(contents, described.get("values")));
            case "csr" -> Operator.csr(rows, columns, sparse(contents, described));
            case "solve" -> Operator.solve(rows, columns, sparse(contents, described.get("system")),
                    sparse(contents, described.get("rightHandSide")));
            default -> throw new Encoding3dException("part " + actual + ": operator format '" + format + "' is not dense, csr or solve");
        };
    }

    private static ByteBuffer view(Glb.Contents contents, JsonNode index) {
        return Codec.view(contents.document(), contents.binary(), index.asInt()).order(ByteOrder.LITTLE_ENDIAN);
    }

    private static double[] doubles(Glb.Contents contents, JsonNode index) {
        ByteBuffer bytes = view(contents, index);
        double[] values = new double[bytes.remaining() / 8];
        bytes.asDoubleBuffer().get(values);
        return values;
    }

    private static long[] longs(Glb.Contents contents, JsonNode index) {
        ByteBuffer bytes = view(contents, index);
        long[] values = new long[bytes.remaining() / 8];
        bytes.asLongBuffer().get(values);
        return values;
    }

    private static SparseMatrix sparse(Glb.Contents contents, JsonNode item) {
        return new SparseMatrix(longs(contents, item.get("indptr")), longs(contents, item.get("indices")),
                doubles(contents, item.get("values")));
    }

    /** Encodes {@code part} into the frame's partBytes; its key, for an instance set's parts. */
    public static String add(Frame frame, Part part) {
        byte[] bytes = toBytes(part);
        String key = contentKey(bytes);
        frame.partBytes.putIfAbsent(key, bytes);
        return key;
    }

    /**
     * The GLB bytes of the part {@code key} of a frame: embedded or added, else at parts/&lt;key&gt;.glb under its
     * partsFolder; MissingPartException when it is nowhere.
     */
    public static byte[] bytes(Frame frame, String key) {
        byte[] found = frame.partBytes.get(key);
        if (found != null) return found;
        List<String> looked = new ArrayList<>();
        if (!frame.partBytes.isEmpty()) looked.add("the frame (embedded)");
        if (frame.partsFolder != null) {
            Path path = frame.partsFolder.resolve(FOLDER).resolve(key + ".glb");
            try {
                if (Archives.exists(path)) return Archives.readBytes(path);
            } catch (IOException error) {
                throw new UncheckedIOException(error);
            }
            looked.add(path.toString());
        }
        throw new MissingPartException(key, looked);
    }

    /** The part {@code key} of a frame, decoded. */
    public static Part part(Frame frame, String key) {
        return read(bytes(frame, key), key);
    }

    /** The keys of the parts the instance sets of a frame use, sorted. */
    public static List<String> keys(Frame frame) {
        TreeSet<String> keys = new TreeSet<>();
        for (DataStructure dataStructure : frame.dataStructures)
            for (InstanceSet instanceSet : dataStructure.instanceSets) keys.addAll(instanceSet.parts);
        return new ArrayList<>(keys);
    }
}
