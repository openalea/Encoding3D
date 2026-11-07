package org.openalea.encoding3d;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.TreeSet;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Sequences: a folder of frames (one GLB each), the shared parts they use (parts/&lt;key&gt;.glb) and their index,
 * scene.fspm.json; or the same packed into an archive (x.fspm.zip, {@link Archives}).
 */
public final class Sequences {
    public static final String INDEX_FILE = "scene.fspm.json";

    /** One frame of a sequence's index; path: its file's absolute path, when read. */
    public record Entry(double time, long step, String file, Path path) {}

    /** A sequence's index: its frames, in time order, and the keys of the parts they use (listed as parts/&lt;key&gt;.glb). */
    public record Index(String version, String timeUnit, List<Entry> frames, List<String> parts) {
        public Index(String version, String timeUnit, List<Entry> frames) {
            this(version, timeUnit, frames, List.of());
        }
    }

    private Sequences() {}

    public static void writeIndex(Path path, Index index) throws IOException {
        ObjectNode document = Glb.MAPPER.createObjectNode().put("fspmIndex", index.version()).put("timeUnit", index.timeUnit());
        ArrayNode frames = document.putArray("frames");
        for (Entry entry : index.frames()) frames.addObject().put("time", entry.time()).put("step", entry.step()).put("file", entry.file());
        if (!index.parts().isEmpty()) {
            ObjectNode parts = document.putObject("parts");
            for (String key : new TreeSet<>(index.parts())) parts.put(key, Parts.FOLDER + "/" + key + ".glb");
        }
        Files.writeString(path, Glb.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(document) + "\n",
                StandardCharsets.UTF_8);
    }

    /** The index of a sequence (its file, its folder, or an archive x.fspm.zip), each frame with the path of its file. */
    public static Index readIndex(Path path) throws IOException {
        if (Files.isDirectory(path) || (path.toString().endsWith(Archives.SUFFIX) && Files.isRegularFile(path)))
            path = path.resolve(INDEX_FILE);                   // a folder's index, or an archive's
        JsonNode document = Glb.MAPPER.readTree(Archives.readBytes(path));
        Path directory = path.toAbsolutePath().getParent();
        List<String> parts = new ArrayList<>();
        document.path("parts").fieldNames().forEachRemaining(parts::add);
        List<Entry> frames = new ArrayList<>();
        for (JsonNode item : document.path("frames"))
            frames.add(new Entry(item.get("time").asDouble(), item.get("step").asLong(), item.get("file").asText(),
                    directory.resolve(item.get("file").asText())));
        return new Index(document.path("fspmIndex").asText(Codec.SPECIFICATION_VERSION), document.path("timeUnit").asText("d"), frames,
                parts);
    }

    /**
     * Writes frames to {@code directory}, one GLB each (name_000000.glb, ...), their parts (parts/&lt;key&gt;.glb), and their
     * index; the index's path.
     */
    public static Path writeSequence(Path directory, List<Frame> frames, String name) throws IOException {
        Files.createDirectories(directory);
        List<Entry> entries = new ArrayList<>();
        TreeSet<String> timeUnits = new TreeSet<>(), keys = new TreeSet<>();
        for (int number = 0; number < frames.size(); number++) {
            String file = String.format("%s_%06d.glb", name, number);
            keys.addAll(Codec.write(directory.resolve(file), frames.get(number)));
            entries.add(new Entry(frames.get(number).time, frames.get(number).step, file, null));
            timeUnits.add(frames.get(number).timeUnit);
        }
        if (timeUnits.size() > 1) throw new Encoding3dException("the frames' times are in several units: " + timeUnits);
        Path index = directory.resolve(INDEX_FILE);
        writeIndex(index, new Index(Codec.SPECIFICATION_VERSION, timeUnits.isEmpty() ? "d" : timeUnits.first(), entries,
                new ArrayList<>(keys)));
        return index;
    }

    public static Path writeSequence(Path directory, List<Frame> frames) throws IOException {
        return writeSequence(directory, frames, "frame");
    }

    /** The frames of the sequence whose index is {@code path}. */
    public static List<Frame> readSequence(Path path) throws IOException {
        List<Frame> frames = new ArrayList<>();
        for (Entry entry : readIndex(path).frames()) frames.add(Codec.read(entry.path()));
        return frames;
    }
}
