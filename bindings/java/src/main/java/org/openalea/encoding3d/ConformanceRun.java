package org.openalea.encoding3d;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.TreeSet;
import java.util.stream.Stream;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * The Java codec's run of the conformance check, as every codec does it in its CI: read each conformance GLB and dump it
 * as JSON (OUT/dumps/x.json for x.glb), and write the conformance scenes again as GLB files (OUT/written/x.glb). The
 * instances (0.4, conformance/README.md): each frame's derived fields evaluated too (OUT/dumps/instances/x.evaluated.json),
 * each part dumped (OUT/dumps/instances/parts/&lt;key&gt;.json), each frame of each archive dumped and evaluated
 * (OUT/dumps/archives/&lt;name&gt;/frame_n.json); the instances written again with their parts encoded by this codec, as
 * a sequence with its index (OUT/written/instances), and packed (OUT/written/archives/instances.fspm.zip). Then
 * .github/actions/conformance compares the dumps with the expected values and validates the written files.
 *
 * <pre>java -jar encoding3d.jar CONFORMANCE OUT</pre>
 */
public final class ConformanceRun {
    private ConformanceRun() {}

    private static void dump(Path path, JsonNode value) throws IOException {
        Files.createDirectories(path.getParent());
        Files.writeString(path, Glb.MAPPER.writeValueAsString(value) + "\n");
    }

    /** {"&lt;data structure&gt;/&lt;instance set&gt;/&lt;field&gt;": one list of values per instance} of every derived field. */
    static ObjectNode evaluated(Frame frame) {
        ObjectNode out = Glb.MAPPER.createObjectNode();
        for (DataStructure dataStructure : frame.dataStructures)
            for (InstanceSet instanceSet : dataStructure.instanceSets)
                for (DerivedField derived : instanceSet.derived) {
                    ArrayNode instances = out.putArray(dataStructure.id + "/" + instanceSet.name + "/" + derived.name);
                    for (double[] values : Instances.evaluate(frame, derived.name, dataStructure.id, instanceSet.name, null)) {
                        ArrayNode items = instances.addArray();
                        for (double value : values) if (Double.isNaN(value)) items.addNull(); else items.add(value);
                    }
                }
        return out;
    }

    /** The frame with each part of its instance sets decoded and encoded again by this codec (new keys). */
    static Frame withPartsEncodedAgain(Frame frame) {
        Frame copy = Codec.fromBytes(Codec.toBytes(frame), frame.partsFolder);
        copy.partBytes.clear();
        for (DataStructure dataStructure : copy.dataStructures)
            for (InstanceSet instanceSet : dataStructure.instanceSets)
                instanceSet.parts.replaceAll(key -> Parts.add(copy, Parts.part(frame, key)));
        return copy;
    }

    public static void main(String[] arguments) throws IOException {
        if (arguments.length != 2) {
            System.err.println("usage: java -jar encoding3d.jar CONFORMANCE OUT");
            System.exit(2);
        }
        Path conformance = Path.of(arguments[0]), out = Path.of(arguments[1]);
        List<Path> files;
        try (Stream<Path> paths = Files.walk(conformance)) {
            files = paths.filter(path -> path.toString().endsWith(".glb"))
                    .filter(path -> !conformance.relativize(path).startsWith("coupling"))      // sessions: their own run
                    .filter(path -> !conformance.relativize(path).startsWith("archives"))      // below
                    .sorted().toList();
        }
        List<Sequences.Entry> instancesFrames = new ArrayList<>();
        TreeSet<String> instancesParts = new TreeSet<>();
        for (Path file : files) {
            Path relative = conformance.relativize(file);
            String name = relative.toString();
            Path dump = out.resolve("dumps").resolve(name.substring(0, name.length() - ".glb".length()) + ".json");
            boolean instances = relative.startsWith("instances");
            if (instances && file.getParent().getFileName().toString().equals(Parts.FOLDER)) {
                String fileName = file.getFileName().toString();
                dump(dump, Dump.partToJson(Parts.read(Files.readAllBytes(file), fileName.substring(0, fileName.length() - 4))));
                continue;
            }
            Frame frame = Codec.read(file);
            dump(dump, Dump.frameToJson(frame));
            Path written = out.resolve("written").resolve(relative);
            Files.createDirectories(written.getParent());
            if (!instances) {
                Codec.write(written, frame);                                  // written again from what was read
                continue;
            }
            dump(Path.of(dump.toString().replaceAll("\\.json$", ".evaluated.json")), evaluated(frame));
            boolean embedded = file.getFileName().toString().equals("embedded.glb");
            List<String> keys = Codec.write(written, withPartsEncodedAgain(frame), embedded);
            if (!embedded) {
                instancesFrames.add(new Sequences.Entry(frame.time, frame.step, file.getFileName().toString(), null));
                instancesParts.addAll(keys);
            }
        }
        Path index = conformance.resolve("growing_sequence").resolve(Sequences.INDEX_FILE);
        if (Files.exists(index))
            Files.copy(index, out.resolve("written").resolve("growing_sequence").resolve(Sequences.INDEX_FILE),
                    StandardCopyOption.REPLACE_EXISTING);
        Path archives = conformance.resolve("archives");
        List<Path> names = new ArrayList<>();
        if (Files.isDirectory(archives))
            try (Stream<Path> paths = Files.list(archives)) {
                names = paths.filter(path -> path.getFileName().toString().endsWith(Archives.SUFFIX)).sorted().toList();
            }
        for (Path archive : names) {
            String name = archive.getFileName().toString();
            String stem = name.substring(0, name.length() - Archives.SUFFIX.length());
            for (Sequences.Entry entry : Sequences.readIndex(archive).frames()) {
                Frame frame = Codec.read(entry.path());                       // x.fspm.zip/frame_n.glb
                String frameStem = entry.file().substring(0, entry.file().length() - ".glb".length());
                Path base = out.resolve("dumps").resolve("archives").resolve(stem);
                dump(base.resolve(frameStem + ".json"), Dump.frameToJson(frame));
                dump(base.resolve(frameStem + ".evaluated.json"), evaluated(frame));
            }
        }
        if (!instancesFrames.isEmpty()) {                  // the instances again as a sequence, then packed
            instancesFrames.sort(Comparator.comparingDouble(Sequences.Entry::time));
            Path folder = out.resolve("written").resolve("instances");
            Sequences.writeIndex(folder.resolve(Sequences.INDEX_FILE),
                    new Sequences.Index(Codec.SPECIFICATION_VERSION, "d", instancesFrames, new ArrayList<>(instancesParts)));
            Files.createDirectories(out.resolve("written").resolve("archives"));
            Archives.pack(folder, out.resolve("written").resolve("archives").resolve("instances" + Archives.SUFFIX));
        }
    }
}
