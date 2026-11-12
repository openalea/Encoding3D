package org.openalea.encoding3d;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Iterator;
import java.util.List;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import com.fasterxml.jackson.databind.JsonNode;

/** Instances, derived fields, shared parts and archives (specification §12, §8.2): the conformance case, and written here. */
class InstancesTest {
    static final Path INSTANCES = CodecTest.CONFORMANCE.resolve("instances");

    static JsonNode json(Path path) throws IOException {
        return Glb.MAPPER.readTree(path.toFile());
    }

    /** Whether two evaluated fields agree within a relative 1e-12 (a solved operator's values depend on the rounding). */
    static boolean close(JsonNode actual, JsonNode expected) {
        if (expected.isObject()) {
            if (!actual.isObject() || actual.size() != expected.size()) return false;
            for (Iterator<String> names = expected.fieldNames(); names.hasNext(); ) {
                String name = names.next();
                if (!actual.has(name) || !close(actual.get(name), expected.get(name))) return false;
            }
            return true;
        }
        if (expected.isArray()) {
            if (!actual.isArray() || actual.size() != expected.size()) return false;
            for (int index = 0; index < expected.size(); index++) if (!close(actual.get(index), expected.get(index))) return false;
            return true;
        }
        if (expected.isNumber())
            return actual.isNumber() && Math.abs(actual.asDouble() - expected.asDouble()) <= 1e-12 * Math.abs(expected.asDouble());
        return actual.equals(expected);
    }

    static JsonNode asJson(JsonNode value) throws IOException {
        return Glb.MAPPER.readTree(Glb.MAPPER.writeValueAsString(value));
    }

    @ParameterizedTest
    @ValueSource(strings = {"frame_000000", "frame_000001"})
    void readAndEvaluatedAsExpected(String name) throws IOException {
        Frame frame = Codec.read(INSTANCES.resolve(name + ".glb"));
        assertEquals(List.of(), Dump.compare(asJson(Dump.frameToJson(frame)), json(INSTANCES.resolve(name + ".expected.json"))));
        assertTrue(close(asJson(ConformanceRun.evaluated(frame)), json(INSTANCES.resolve(name + ".evaluated.json"))));
        Frame again = Codec.fromBytes(Codec.toBytes(frame), frame.partsFolder);        // written and read: the same keys
        assertEquals(List.of(), Dump.compare(asJson(Dump.frameToJson(again)), json(INSTANCES.resolve(name + ".expected.json"))));
        for (String archive : List.of("instances_stored", "instances_deflate", "instances_lzma", "instances_zip64")) {
            Frame inArchive = Codec.read(CodecTest.CONFORMANCE.resolve("archives").resolve(archive + Archives.SUFFIX).resolve(name + ".glb"));
            assertEquals(List.of(), Dump.compare(asJson(Dump.frameToJson(inArchive)), json(INSTANCES.resolve(name + ".expected.json"))), archive);
            assertTrue(close(asJson(ConformanceRun.evaluated(inArchive)), json(INSTANCES.resolve(name + ".evaluated.json"))), archive);
        }
    }

    @Test
    void embeddedParts() throws IOException {
        Frame frame = Codec.read(INSTANCES.resolve("embedded.glb"));
        assertEquals(5, frame.partBytes.size());
        assertTrue(close(asJson(ConformanceRun.evaluated(frame)), json(INSTANCES.resolve("frame_000001.evaluated.json"))));
    }

    @Test
    void partsReadAsExpected() throws IOException {
        List<Path> parts;
        try (Stream<Path> paths = Files.list(INSTANCES.resolve(Parts.FOLDER))) {
            parts = paths.sorted().toList();
        }
        assertEquals(5, parts.size());
        for (Path path : parts) {
            String key = path.getFileName().toString().replace(".glb", "");
            byte[] bytes = Files.readAllBytes(path);
            assertEquals(key, Parts.contentKey(bytes));
            assertEquals(List.of(), Dump.compare(asJson(Dump.partToJson(Parts.read(bytes, key))), json(INSTANCES.resolve("expected").resolve(key + ".json"))));
            assertThrows(Encoding3dException.class, () -> Parts.read(bytes, "0".repeat(64)));
        }
        Sequences.Index index = Sequences.readIndex(CodecTest.CONFORMANCE.resolve("archives").resolve("instances_deflate" + Archives.SUFFIX));
        assertEquals(2, index.frames().size());
        assertEquals(5, index.parts().size());
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                Parts.contentKey("abc".getBytes(StandardCharsets.US_ASCII)));
    }

    /** A template of {@code cells} cells (a fan of triangles), its entity set Cell with an area per cell. */
    static Template fan(int cells) {
        Template template = new Template();
        EntitySet set = new EntitySet("Cell");
        double[] area = new double[cells];
        java.util.Arrays.fill(area, 0.5);
        set.set("area", Column.of(area));
        template.dataStructure.entitySets.add(set);
        double[] positions = new double[cells * 9];
        long[] rows = new long[cells * 3];
        for (int cell = 0; cell < cells; cell++) {
            double first = 2 * Math.PI * cell / cells, second = 2 * Math.PI * (cell + 1) / cells;
            double[] corners = {0, 0, 0, Math.cos(first), Math.sin(first), 0, Math.cos(second), Math.sin(second), 0};
            System.arraycopy(corners, 0, positions, cell * 9, 9);
            java.util.Arrays.fill(rows, cell * 3, cell * 3 + 3, cell);
        }
        Mesh mesh = new Mesh("section", positions);
        mesh.featureRows.put("Cell", rows);
        template.dataStructure.meshes.add(mesh);
        return template;
    }

    @Test
    void writtenAndEvaluated(@TempDir Path folder) throws IOException {
        Frame frame = new Frame();
        DataStructure plant = new DataStructure("plant");
        EntitySet segments = new EntitySet("SubOrgan", 0L);
        segments.set("id", Column.of(7L, 8L, 9L));
        plant.entitySets.add(segments);
        InstanceSet sections = new InstanceSet("sections", "SubOrgan");
        sections.parts.add(Parts.add(frame, fan(3)));                                                   // 0: a template
        sections.parts.add(Parts.add(frame, Operator.dense(3, 2, new double[] {1, 0, 0.5, 0.5, 0, 1})));   // 1: dense
        sections.parts.add(Parts.add(frame, Operator.csr(3, 2,
                new SparseMatrix(new long[] {0, 1, 2, 3}, new long[] {0, 1, 0}, new double[] {2, 3, 4}))));  // 2: csr
        sections.parts.add(Parts.add(frame, Operator.solve(3, 2,                                         // 3: diag(2, 4, 8)⁻¹ R
                new SparseMatrix(new long[] {0, 1, 2, 3}, new long[] {0, 1, 2}, new double[] {2, 4, 8}),
                new SparseMatrix(new long[] {0, 2, 3, 4}, new long[] {0, 1, 0, 1}, new double[] {2, 2, 4, 8}))));
        assertEquals(sections.parts.get(1), Parts.add(frame, Operator.dense(3, 2, new double[] {1, 0, 0.5, 0.5, 0, 1})));
        sections.set("template", Column.of(0L, 0L, 0L)).set("owner", Column.of(7L, 8L, 9L)).set("age", Column.of(1.0, 2.0, 3.0))
                .declare("age", new Variable("d", null, null, "state"));
        sections.vectors.put("ends", Ragged.of(List.of(new double[] {1, 2}, new double[] {3, 4}, new double[] {5, 6})));
        sections.vectors.put("sources", Ragged.of(List.of(new double[] {}, new double[] {10, 20, 30}, new double[] {})));
        Variable potential = new Variable("MPa", null, null, "derived");
        sections.derived.add(new DerivedField("water_potential", "Cell", "ends", 2, new long[] {1, -1, 2, 1, 3, -1},
                new double[] {1, 0, 0.5, 0.5, 2, 0}, new String[] {"sources", null}, potential));
        plant.instanceSets.add(sections);
        frame.dataStructures.add(plant);
        double[][] expected = {{1, 1.5, 2}, {0.5 * (6 + 10) + 0.5 * 3, 0.5 * (12 + 20) + 0.5 * 3.5, 0.5 * (12 + 30) + 0.5 * 4},
                {22, 10, 12}};
        List<double[]> evaluated = Instances.evaluate(frame, "water_potential");
        for (int row = 0; row < 3; row++) assertArrayEquals(expected[row], evaluated.get(row), 0.0);
        assertArrayEquals(expected[2], Instances.evaluate(frame, "water_potential", "plant", "sections", new int[] {2}).get(0), 0.0);

        Path index = Sequences.writeSequence(folder.resolve("run"), List.of(frame));
        assertTrue(Files.exists(folder.resolve("run").resolve(Parts.FOLDER).resolve(sections.parts.get(0) + ".glb")));
        assertEquals(4, Sequences.readIndex(index).parts().size());
        Frame again = Codec.read(Sequences.readIndex(index).frames().get(0).path());
        List<double[]> evaluatedAgain = Instances.evaluate(again, "water_potential");
        for (int row = 0; row < 3; row++) assertArrayEquals(expected[row], evaluatedAgain.get(row), 0.0);
        InstanceSet read = again.dataStructure("plant").instanceSet("sections");
        assertEquals("SubOrgan", read.owners);
        assertArrayEquals(new long[] {0, 3, 0}, read.vector("sources").counts);
        assertFalse(read.has("ends__count"));
        assertEquals("d", read.variables.get("age").unit);

        Frame embedded = Codec.fromBytes(Codec.toBytes(frame, true));
        assertEquals(4, embedded.partBytes.size());
        assertArrayEquals(expected[1], Instances.evaluate(embedded, "water_potential").get(1), 0.0);
        for (String compression : List.of("stored", "deflate")) {
            Path archive = folder.resolve("run_" + compression + Archives.SUFFIX);
            Archives.pack(folder.resolve("run"), archive, compression);
            Sequences.Index packed = Sequences.readIndex(archive);
            assertEquals(4, packed.parts().size());
            assertArrayEquals(expected[2], Instances.evaluate(Codec.read(packed.frames().get(0).path()), "water_potential").get(2), 0.0);
        }
        try (Stream<Path> paths = Files.list(folder.resolve("run").resolve(Parts.FOLDER))) {
            for (Path path : paths.toList()) Files.delete(path);
        }
        Frame withoutParts = Codec.read(Sequences.readIndex(index).frames().get(0).path());
        MissingPartException missing = assertThrows(MissingPartException.class, () -> Instances.evaluate(withoutParts, "water_potential"));
        assertEquals(64, missing.key.length());
        assertTrue(missing.getMessage().contains(missing.key));
    }
}
