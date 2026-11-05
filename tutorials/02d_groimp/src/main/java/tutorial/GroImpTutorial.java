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

    // GroIMP's graph module has no geometry: in the GroIMP application, shape nodes (cylinders...) place the organs in
    // space, and the plugin meshes them. Here each organ keeps its two ends (x1 ... z2), so that viewers draw it.
    public static final class Internode extends Node {
        double length = 0.02;
        float radius = 0.002f;
        double x1, y1, z1, x2, y2, z2 = 0.02;          // m: its lower and upper ends
        public static final NType $TYPE = Managed.type(Internode.class, "length", "radius",
                "x1", "y1", "z1", "x2", "y2", "z2");
        @Override protected NType getNTypeImpl() { return $TYPE; }
        @Override protected Node newInstance() { return new Internode(); }
    }

    public static final class Leaf extends Node {
        double length = 0.01;
        float radius = 0.001f;
        double x1, y1, z1, x2, y2, z2;                 // m: where it leaves its internode, and its tip
        double side = 1;                               // which side it leans to: +1 or -1 (not managed)
        public static final NType $TYPE = Managed.type(Leaf.class, "length", "radius",
                "x1", "y1", "z1", "x2", "y2", "z2");

        /** Its tip, from its base: leaning 45 degrees to its side. */
        void place() {
            x2 = x1 + side * length * Math.sqrt(0.5);
            y2 = y1;
            z2 = z1 + length * Math.sqrt(0.5);
        }
        @Override protected NType getNTypeImpl() { return $TYPE; }
        @Override protected Node newInstance() { return new Leaf(); }
    }

    /** The plant grows as an RGG rule would make it: a new internode bearing a leaf on top, every leaf longer. */
    static Internode grow(Internode top, List<Leaf> leaves) {
        for (Leaf leaf : leaves) {
            leaf.length += 0.02;
            leaf.place();
        }
        Internode next = new Internode();
        next.x1 = top.x2; next.y1 = top.y2; next.z1 = top.z2;            // on top of the previous one
        next.x2 = next.x1; next.y2 = next.y1; next.z2 = next.z1 + next.length;
        Leaf leaf = new Leaf();
        leaf.x1 = next.x2; leaf.y1 = next.y2; leaf.z1 = next.z2;
        leaf.side = leaves.size() % 2 == 0 ? 1 : -1;                     // alternate sides
        leaf.place();
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
        String[] ends = {"x1", "y1", "z1", "x2", "y2", "z2"};
        String[] standardNames = {"proximal_end_x", "proximal_end_y", "proximal_end_z", "distal_end_x", "distal_end_y",
                                  "distal_end_z"};
        for (int index = 0; index < ends.length; index++)
            options.variables.put(ends[index], new Variable("m", standardNames[index], "descriptor", "state"));
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
