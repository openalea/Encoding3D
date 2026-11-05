package tutorial;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

import org.openalea.encoding3d.Codec;
import org.openalea.encoding3d.DataStructure;
import org.openalea.encoding3d.EntitySet;
import org.openalea.encoding3d.Frame;
import org.openalea.encoding3d.Sequences;
import org.openalea.encoding3d.Variable;
import org.openalea.encoding3d.groimp.GroImp;

import de.grogra.graph.Graph;
import de.grogra.graph.impl.GraphManager;
import de.grogra.graph.impl.Node;
import de.grogra.persistence.ServerConnection;

/** Tutorial 2d: a GroIMP graph written and read as encoding3d (README.md explains each part). */
public final class GroImpTutorial {
    private GroImpTutorial() {}

    // ── 1. A GroIMP plant: node classes with managed fields, as an RGG model declares them ──────────────────
    public static final class Plant extends Node {
        String species = "Wheat";
        public static final NType $TYPE = Managed.type(Plant.class, "species");
        @Override protected NType getNTypeImpl() { return $TYPE; }
        @Override protected Node newInstance() { return new Plant(); }
    }

    public static final class Internode extends Node {
        double length = 0.02;
        float radius = 0.002f;
        public static final NType $TYPE = Managed.type(Internode.class, "length", "radius");
        @Override protected NType getNTypeImpl() { return $TYPE; }
        @Override protected Node newInstance() { return new Internode(); }
    }

    public static final class Leaf extends Node {
        double length = 0.01;
        public static final NType $TYPE = Managed.type(Leaf.class, "length");
        @Override protected NType getNTypeImpl() { return $TYPE; }
        @Override protected Node newInstance() { return new Leaf(); }
    }

    /** The plant grows as an RGG rule would make it: a new internode bearing a leaf on top, every leaf longer. */
    static Internode grow(Internode top, List<Leaf> leaves) {
        for (Leaf leaf : leaves) leaf.length += 0.02;
        Internode next = new Internode();
        Leaf leaf = new Leaf();
        top.addEdgeBitsTo(next, Graph.SUCCESSOR_EDGE, null);        // GroIMP's '>' edge
        next.addEdgeBitsTo(leaf, Graph.BRANCH_EDGE, null);          // GroIMP's '+' edge
        leaves.add(leaf);
        return next;
    }

    /** How the graph is written: its scale below the plant is the vocabulary's Organ, lengths in metres. */
    static GroImp.Options options() {
        GroImp.Options options = new GroImp.Options();
        options.id = "plant";
        options.scaleNames.put(2, "Organ");
        options.scaleRanks.put(2, 5L);
        options.scaleScales.put(2, "Organ");
        options.labels.put("Internode", "StemInternode");
        options.variables.put("length", new Variable("m", "length", "extensive", "state"));
        options.variables.put("radius", new Variable("m", "radius", "intensive", "state"));
        options.variables.put("species", new Variable("1", null, "descriptor", "parameter"));
        return options;
    }

    public static void main(String[] arguments) throws Exception {
        Path out = Path.of(arguments.length > 0 ? arguments[0] : "outputs");
        GraphManager graph = new GraphManager(new ServerConnection(null), "tutorial", false, false);
        Node root = new Node();
        Plant plant = new Plant();
        root.addEdgeBitsTo(plant, Graph.BRANCH_EDGE, null);
        Internode top = new Internode();
        plant.addEdgeBitsTo(top, Graph.REFINEMENT_EDGE, null);      // GroIMP's '/' edge: the plant is made of them
        graph.setRoot(Graph.MAIN_GRAPH, root);
        List<Leaf> leaves = new ArrayList<>();

        // ── 2. A frame per step ─────────────────────────────────────────────────────────────────────────────
        List<Frame> frames = new ArrayList<>();
        for (int step = 0; step < 6; step++) {
            if (step > 0) top = grow(top, leaves);
            DataStructure written = GroImp.toDataStructure(root, options());
            Frame frame = new Frame();
            frame.dataStructures.add(written);
            frame.time = step;
            frame.step = step;
            frames.add(frame);
            EntitySet organs = written.entitySet("Organ");
            System.out.println("step " + step + ": " + organs.rowCount() + " organs, scales "
                    + written.entitySets.stream().map(set -> set.name).toList());
        }
        Path index = Sequences.writeSequence(out.resolve("frames"), frames);
        System.out.println("written: " + index);

        // ── 3. Back into GroIMP nodes ─────────────────────────────────────────────────────────────────────────
        DataStructure last = Codec.read(out.resolve("frames").resolve("frame_000005.glb")).dataStructures.get(0);
        Map<String, Supplier<Node>> classes = Map.of("Plant", Plant::new, "Internode", Internode::new, "Leaf", Leaf::new);
        Map<Long, Node> nodes = new HashMap<>();
        Node rebuilt = GroImp.toGraph(last, label -> classes.get(label).get(), nodes);
        new GraphManager(new ServerConnection(null), "rebuilt", false, false).setRoot(Graph.MAIN_GRAPH, rebuilt);
        double leafLength = nodes.values().stream().filter(node -> node instanceof Leaf)
                .mapToDouble(node -> ((Leaf) node).length).sum();
        System.out.println("rebuilt as GroIMP nodes: " + nodes.size() + " nodes, leaves " + Math.round(leafLength * 100)
                + " cm long in all");
    }
}
