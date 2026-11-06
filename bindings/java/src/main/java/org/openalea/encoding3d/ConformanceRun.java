package org.openalea.encoding3d;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.List;
import java.util.stream.Stream;

/**
 * The Java codec's run of the conformance check, as every codec does it in its CI: read each conformance GLB and dump it
 * as JSON (OUT/dumps/x.json for x.glb), and write the conformance scenes again as GLB files (OUT/written/x.glb). Then
 * .github/actions/conformance compares the dumps with the expected values and validates the written files.
 *
 * <pre>java -jar encoding3d.jar CONFORMANCE OUT</pre>
 */
public final class ConformanceRun {
    private ConformanceRun() {}

    public static void main(String[] arguments) throws IOException {
        if (arguments.length != 2) {
            System.err.println("usage: java -jar encoding3d.jar CONFORMANCE OUT");
            System.exit(2);
        }
        Path conformance = Path.of(arguments[0]), out = Path.of(arguments[1]);
        List<Path> files;
        try (Stream<Path> paths = Files.walk(conformance)) {
            files = paths.filter(path -> path.toString().endsWith(".glb"))
                    .filter(path -> !conformance.relativize(path).startsWith("coupling"))      // sessions
                    .filter(path -> !conformance.relativize(path).startsWith("instances"))     // 0.4: the Python codec's
                    .sorted().toList();
        }
        for (Path file : files) {
            Path relative = conformance.relativize(file);
            Frame frame = Codec.read(file);
            String name = relative.toString();
            Path dump = out.resolve("dumps").resolve(name.substring(0, name.length() - ".glb".length()) + ".json");
            Path written = out.resolve("written").resolve(relative);
            Files.createDirectories(dump.getParent());
            Files.createDirectories(written.getParent());
            Files.writeString(dump, Glb.MAPPER.writeValueAsString(Dump.frameToJson(frame)) + "\n");
            Codec.write(written, frame);                                      // written again from what was read
        }
        Path index = conformance.resolve("growing_sequence").resolve(Sequences.INDEX_FILE);
        if (Files.exists(index))
            Files.copy(index, out.resolve("written").resolve("growing_sequence").resolve(Sequences.INDEX_FILE),
                    StandardCopyOption.REPLACE_EXISTING);
    }
}
