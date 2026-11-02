package org.openalea.fspmtf.groimp;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.openalea.fspmtf.Codec;
import org.openalea.fspmtf.DataStructure;
import org.openalea.fspmtf.EntitySet;
import org.openalea.fspmtf.Frame;
import org.openalea.fspmtf.Variable;

import de.grogra.graph.Graph;
import de.grogra.graph.impl.GraphManager;
import de.grogra.graph.impl.Node;
import de.grogra.persistence.ServerConnection;

/** GroIMP's adapter: a multiscale GroIMP graph (plant, internodes and leaves) exported, written, read and rebuilt. */
class GroImpTest {
    static final Path OUT = Path.of(System.getProperty("fspmtf.out", "target/groimp_out"));

    /** root -> Plant /-> Internode < Internode, each internode bearing a leaf (+); a mark edge from a leaf to the plant. */
    static Node plant(GraphManager graph) {
        Node root = new Node();
        Organs.Plant plant = new Organs.Plant();
        plant.species = "Wheat";
        root.addEdgeBitsTo(plant, Graph.BRANCH_EDGE, null);
        Organs.Internode first = new Organs.Internode(), second = new Organs.Internode();
        first.length = 0.12; first.radius = 0.004f; first.rank = 1;
        second.length = 0.08; second.radius = 0.003f; second.rank = 2;
        Organs.Leaf firstLeaf = new Organs.Leaf(), secondLeaf = new Organs.Leaf();
        firstLeaf.length = 0.2; secondLeaf.length = 0.15; secondLeaf.alive = false;
        plant.addEdgeBitsTo(first, Graph.REFINEMENT_EDGE, null);
        first.addEdgeBitsTo(second, Graph.SUCCESSOR_EDGE, null);
        first.addEdgeBitsTo(firstLeaf, Graph.BRANCH_EDGE, null);
        second.addEdgeBitsTo(secondLeaf, Graph.BRANCH_EDGE, null);
        firstLeaf.addEdgeBitsTo(plant, Graph.MARK_EDGE, null);
        graph.setRoot(Graph.MAIN_GRAPH, root);
        return root;
    }

    static GraphManager newGraph() {
        return new GraphManager(new ServerConnection(null), "test", false, false);
    }

    @Test
    void exportedWrittenAndRebuilt() throws IOException {
        Node root = plant(newGraph());
        GroImp.Options options = new GroImp.Options();
        options.scaleNames.put(2, "Organ");
        options.scaleRanks.put(2, 5L);                                   // the vocabulary's Organ
        options.variables.put("length", new Variable("m", "length", "extensive", "state"));
        DataStructure written = GroImp.toDataStructure(root, options);

        assertEquals(List.of("Plant", "Organ"), written.entitySets.stream().map(set -> set.name).toList());
        EntitySet plants = written.entitySet("Plant"), organs = written.entitySet("Organ");
        assertArrayEquals(new String[] {"Wheat"}, plants.column("species").strings());
        assertEquals(5L, organs.rank);
        assertArrayEquals(new String[] {"Internode", "Internode", "Leaf", "Leaf"}, organs.column("label").strings());
        long[] ids = organs.column("id").longs();
        long plantId = plants.column("id").longs()[0];
        assertArrayEquals(new long[] {plantId, plantId, plantId, plantId}, organs.column("complex").longs());
        assertArrayEquals(new long[] {-1, ids[0], ids[1], ids[0]}, organs.column("parent").longs());
        assertArrayEquals(new String[] {"none", "successor", "branch", "branch"}, organs.column("edge_type").strings());
        double[] lengths = organs.column("length").doubles();
        assertArrayEquals(new double[] {0.12, 0.08, 0.15, 0.2}, lengths);
        assertTrue(Float.isNaN(organs.column("radius").floats()[2]));          // leaves have no radius
        assertArrayEquals(new boolean[] {false, false, false, true}, organs.column("alive").booleans());
        assertEquals("mark", written.relations.get(0).name);
        assertArrayEquals(new long[] {ids[3]}, written.relations.get(0).column("source").longs());
        assertEquals(List.of(0, 1), List.of(written.extras.get("groimp").get("missing").get("Organ").get("alive").get(0).asInt(),
                written.extras.get("groimp").get("missing").get("Organ").get("alive").get(1).asInt()));

        Files.createDirectories(OUT);
        Frame frame = new Frame();
        frame.dataStructures.add(written);
        Codec.write(OUT.resolve("groimp_plant.glb"), frame);
        DataStructure readBack = Codec.read(OUT.resolve("groimp_plant.glb")).dataStructures.get(0);

        Map<Long, Node> nodes = new HashMap<>();
        Map<String, java.util.function.Supplier<Node>> classes = Map.of("Plant", Organs.Plant::new,
                "Internode", Organs.Internode::new, "Leaf", Organs.Leaf::new);
        Node rebuilt = GroImp.toGraph(readBack, label -> classes.get(label).get(), nodes);
        newGraph().setRoot(Graph.MAIN_GRAPH, rebuilt);
        DataStructure again = GroImp.toDataStructure(rebuilt, options);
        EntitySet againOrgans = again.entitySet("Organ");
        assertArrayEquals(organs.column("label").strings(), againOrgans.column("label").strings());
        assertArrayEquals(lengths, againOrgans.column("length").doubles());
        assertArrayEquals(organs.column("edge_type").strings(), againOrgans.column("edge_type").strings());
        assertArrayEquals(organs.column("alive").booleans(), againOrgans.column("alive").booleans());
        assertEquals(0.004f, ((Organs.Internode) nodes.get(ids[0])).radius);
        assertEquals("Wheat", ((Organs.Plant) nodes.get(plantId)).species);
        assertEquals(1, again.relations.size());
        assertNull(again.entitySet("Plant").has("complex") ? "complex" : null);
    }

    @Test
    void anotherPlatformsGraph() throws IOException {
        // The conformance root system (metafspm: Plant, Axis, SubOrgan) as GroIMP nodes: three scales by refinement
        Path conformance = Path.of(System.getProperty("fspmtf.conformance", "../../../conformance"));
        DataStructure roots = Codec.read(conformance.resolve("root_system.glb")).dataStructures.get(0);
        Node root = GroImp.toGraph(roots, label -> new Node(), new HashMap<>());
        newGraph().setRoot(Graph.MAIN_GRAPH, root);
        DataStructure again = GroImp.toDataStructure(root, new GroImp.Options());
        assertEquals(3, again.entitySets.size());
        for (int scale = 0; scale < 3; scale++) {
            EntitySet written = roots.entitySets.get(scale), read = again.entitySets.get(scale);
            assertEquals(written.rowCount(), read.rowCount(), written.name);
            if (written.has("edge_type"))
                assertEquals(List.of(written.column("edge_type").strings()).stream().sorted().toList(),
                        List.of(read.column("edge_type").strings()).stream().sorted().toList(), written.name);
        }
    }
}
