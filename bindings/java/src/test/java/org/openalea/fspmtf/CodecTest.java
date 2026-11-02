package org.openalea.fspmtf;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

import com.fasterxml.jackson.databind.JsonNode;

/** The Java codec: the conformance files read as their expected values, written and read back the same, every column type, meshes, sequences, and what the specification forbids refused. */
class CodecTest {
    static final Path CONFORMANCE = Path.of(System.getProperty("fspmtf.conformance", "../../conformance"));

    static Stream<Path> conformanceFiles() throws IOException {
        try (Stream<Path> paths = Files.walk(CONFORMANCE)) {
            return paths.filter(path -> path.toString().endsWith(".glb")).sorted().toList().stream();
        }
    }

    static JsonNode expectedOf(Path glb) throws IOException {
        String name = glb.getFileName().toString();
        return Glb.MAPPER.readTree(glb.resolveSibling(name.substring(0, name.length() - 4) + ".expected.json").toFile());
    }

    /** The dump as it is written and read as JSON (numbers as JSON numbers). */
    static JsonNode asJson(Frame frame) throws IOException {
        return Glb.MAPPER.readTree(Glb.MAPPER.writeValueAsString(Dump.frameToJson(frame)));
    }

    @Test
    void nineConformanceFiles() throws IOException {
        assertEquals(9, conformanceFiles().count());
    }

    @ParameterizedTest
    @MethodSource("conformanceFiles")
    void glbRepackedAsItWas(Path file) throws IOException {
        Glb.Contents contents = Glb.unpack(Files.readAllBytes(file));
        Glb.Contents again = Glb.unpack(Glb.pack(contents.document(), contents.binary()));
        assertArrayEquals(contents.binary(), again.binary());
        assertEquals(contents.document(), again.document());
        assertEquals(0, contents.binary().length % 8);
    }

    @ParameterizedTest
    @MethodSource("conformanceFiles")
    void readAsExpected(Path file) throws IOException {
        List<String> differences = Dump.compare(asJson(Codec.read(file)), expectedOf(file));
        assertTrue(differences.isEmpty(), () -> String.join("\n", differences.subList(0, Math.min(5, differences.size()))));
    }

    @ParameterizedTest
    @MethodSource("conformanceFiles")
    void writtenAndReadBack(Path file) throws IOException {
        Frame frame = Codec.fromBytes(Codec.toBytes(Codec.read(file)));
        List<String> differences = Dump.compare(asJson(frame), expectedOf(file));
        assertTrue(differences.isEmpty(), () -> String.join("\n", differences.subList(0, Math.min(5, differences.size()))));
    }

    @Test
    void columnsOfEveryType() {
        EntitySet organs = new EntitySet("Organ", 1L);
        organs.set("id", Column.of(0, 1, 2)).set("label", Column.of("Leaf", "Internode", "Leaf"))
                .set("parent", Column.of(-1L, 0L, 1L)).set("edge_type", Column.of("none", "successor", "branch"))
                .set("with_nan", Column.of(1.0, Double.NaN, -2.5))
                .set("with_infinities", Column.of(Float.POSITIVE_INFINITY, 1f, Float.NEGATIVE_INFINITY))
                .set("flag", Column.of(true, false, true)).set("name", Column.of("é", "", "a b"))
                .set("position", Column.vectors(3, 1, 2, 3, 4, 5, 6, 7, 8, 9))
                .set("column_int8", new Column(ComponentType.INT8, new byte[] {1, 2, -3}))
                .set("column_uint8", new Column(ComponentType.UINT8, new byte[] {1, 2, (byte) 255}))
                .set("column_int16", new Column(ComponentType.INT16, new short[] {1, 2, 3}))
                .set("column_uint16", new Column(ComponentType.UINT16, new short[] {1, 2, (short) 65535}))
                .set("column_uint32", new Column(ComponentType.UINT32, new int[] {1, 2, -1}))
                .set("column_uint64", new Column(ComponentType.UINT64, new long[] {1, 2, -1}));
        Variable length = new Variable("m", "length", "extensive", "state");
        length.description = "a length";
        length.minimum = 0.0;
        length.references.add("a reference");
        organs.declare("with_nan", length);
        DataStructure plants = new DataStructure("plants");
        plants.entitySets.add(organs);
        plants.origin = new double[] {1, 0, 0, 0.5, 0, 1, 0, 0, 0, 0, 1, -0.1, 0, 0, 0, 1};
        plants.extras.putArray("platform").add(1).add(2);
        Frame frame = new Frame();
        frame.dataStructures.add(plants);
        frame.time = 2.5;
        frame.timeUnit = "h";
        frame.step = 3;

        Frame readBack = Codec.fromBytes(Codec.toBytes(frame));
        EntitySet set = readBack.dataStructure("plants").entitySet("Organ");
        assertEquals(ComponentType.INT64, set.column("id").type);                        // ids are INT64
        assertArrayEquals(new double[] {1.0, Double.NaN, -2.5}, set.column("with_nan").doubles());
        assertArrayEquals(new float[] {Float.POSITIVE_INFINITY, 1f, Float.NEGATIVE_INFINITY}, set.column("with_infinities").floats());
        assertArrayEquals(new boolean[] {true, false, true}, set.column("flag").booleans());
        assertArrayEquals(new String[] {"é", "", "a b"}, set.column("name").strings());
        assertEquals(3, set.column("position").width);
        assertArrayEquals(new double[] {1, 2, 3, 4, 5, 6, 7, 8, 9}, set.column("position").doubles());
        assertArrayEquals(new String[] {"Leaf", "Internode", "Leaf"}, set.column("label").strings());
        for (String name : List.of("column_int8", "column_uint8", "column_int16", "column_uint16", "column_uint32", "column_uint64"))
            assertEquals(organs.column(name), set.column(name), name);
        assertEquals(255.0, set.column("column_uint8").doubleAt(2));
        assertEquals(length, set.variables.get("with_nan"));
        assertArrayEquals(plants.origin, readBack.dataStructure("plants").origin);
        assertEquals(plants.extras, readBack.dataStructure("plants").extras);
        assertEquals(2.5, readBack.time);
        assertEquals("h", readBack.timeUnit);
        assertEquals(3, readBack.step);
    }

    @Test
    void meshes() {
        EntitySet segments = new EntitySet("SubOrgan", 6L);
        segments.set("id", Column.of(10L, 11L));
        Mesh mesh = new Mesh("roots", new double[] {0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1});
        mesh.featureRows.put("SubOrgan", new long[] {0, 1, 1, -1});
        mesh.indices = new long[] {0, 1, 2, 0, 2, 3};
        mesh.display.put("radius", new float[] {1, 2, 2, 0});
        mesh.displaySources.put("radius", "SubOrgan");
        DataStructure roots = new DataStructure("roots");
        roots.entitySets.add(segments);
        roots.meshes.add(mesh);
        Frame frame = new Frame();
        frame.dataStructures.add(roots);
        Mesh readBack = Codec.fromBytes(Codec.toBytes(frame)).dataStructures.get(0).meshes.get(0);
        assertArrayEquals(mesh.positions, readBack.positions);
        assertArrayEquals(mesh.featureRows.get("SubOrgan"), readBack.featureRows.get("SubOrgan"));
        assertArrayEquals(mesh.indices, readBack.indices);
        assertArrayEquals(mesh.display.get("radius"), readBack.display.get("radius"));
        assertEquals(mesh.displaySources, readBack.displaySources);
    }

    static Frame frameWith(EntitySet set) {
        DataStructure plants = new DataStructure("plants");
        plants.entitySets.add(set);
        Frame frame = new Frame();
        frame.dataStructures.add(plants);
        return frame;
    }

    @Test
    void refused() {
        EntitySet badColumn = new EntitySet("Organ");
        badColumn.set("id", Column.of(0L)).set("1st", Column.of(1.0));
        assertThrows(FspmTfException.class, () -> Codec.toBytes(frameWith(badColumn)));
        Frame badId = new Frame();
        badId.dataStructures.add(new DataStructure("bad id"));
        assertThrows(FspmTfException.class, () -> Codec.toBytes(badId));
        EntitySet badEdge = new EntitySet("Organ");
        badEdge.set("id", Column.of(0L)).set("parent", Column.of(-1L)).set("edge_type", Column.of("root"));
        assertThrows(FspmTfException.class, () -> Codec.toBytes(frameWith(badEdge)));
        EntitySet both = new EntitySet("Organ");
        both.set("id", Column.of(0L, 1L)).set("x", Column.of(Double.NaN, -Double.MAX_VALUE));
        assertThrows(FspmTfException.class, () -> Codec.toBytes(frameWith(both)));
        EntitySet lengths = new EntitySet("Organ");
        lengths.set("id", Column.of(0L, 1L)).set("x", Column.of(1.0));
        assertThrows(FspmTfException.class, () -> Codec.toBytes(frameWith(lengths)));
        assertThrows(FspmTfException.class, () -> Glb.unpack(new byte[] {1, 2, 3}));
        assertThrows(FspmTfException.class, () -> new Column(ComponentType.INT64, new double[] {1.0}));
    }

    @Test
    void sequences(@TempDir Path folder) throws IOException {
        List<Frame> frames = new ArrayList<>();
        for (int step = 0; step < 3; step++) {
            EntitySet plant = new EntitySet("Plant", 1L);
            plant.set("id", Column.of(0L)).set("biomass", Column.of((double) step));
            Frame frame = frameWith(plant);
            frame.time = step / 24.0;
            frame.step = step;
            frames.add(frame);
        }
        Path index = Sequences.writeSequence(folder, frames);
        assertEquals(2, Sequences.readIndex(index).frames().get(2).step());
        List<Frame> readBack = Sequences.readSequence(index);
        assertEquals(2.0, readBack.get(2).dataStructures.get(0).entitySets.get(0).column("biomass").doubles()[0]);
        for (Sequences.Entry entry : Sequences.readIndex(CONFORMANCE.resolve("growing_sequence").resolve(Sequences.INDEX_FILE)).frames())
            assertTrue(Files.exists(entry.path()));
    }
}
