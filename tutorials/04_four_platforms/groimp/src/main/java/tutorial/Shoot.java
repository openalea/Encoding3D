package tutorial;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.openalea.encoding3d.Column;
import org.openalea.encoding3d.DataStructure;
import org.openalea.encoding3d.EntitySet;
import org.openalea.encoding3d.Frame;
import org.openalea.encoding3d.Variable;
import org.openalea.encoding3d.coupling.Participant;
import org.openalea.encoding3d.coupling.Turn;
import org.openalea.encoding3d.groimp.GroImp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import de.grogra.graph.Graph;
import de.grogra.graph.impl.GraphManager;
import de.grogra.graph.impl.Node;
import de.grogra.persistence.ServerConnection;

/**
 * Tutorial 4, GroIMP's side: the shoot architecture (structural). The shoot is a GroIMP graph of phytomers (an
 * internode and its leaf), one on top of the other; a new one grows each time the plant's roots have taken up enough
 * water since the last, and every leaf expands. Each turn, GroIMP's adapter writes the graph, and its phytomers are
 * sent to the session under the plant CPlantBox created.
 */
public final class Shoot {
    private Shoot() {}

    static final double WATER_PER_PHYTOMER = 8.;     // cm3 of water taken up for a new phytomer (a toy)

    /** A phytomer, as an RGG model declares it: its leaf's area and its height, managed by GroIMP. */
    public static final class Phytomer extends Node {
        double area = 1e-4;                            // m2
        double height;                                 // m
        public static final NType $TYPE = Managed.type(Phytomer.class, "area", "height");
        @Override protected NType getNTypeImpl() { return $TYPE; }
        @Override protected Node newInstance() { return new Phytomer(); }
    }

    static ObjectNode declaration(ObjectMapper json) {
        ObjectNode declaration = json.createObjectNode().put("participant", "groimp").put("platform", "GroIMP");
        ArrayNode sets = declaration.putArray("entitySets");
        sets.addObject().put("dataStructure", "plant").put("name", "Plant").put("rank", 1).put("rights", "follows");
        sets.addObject().put("dataStructure", "plant").put("name", "Phytomer").put("rank", 4).put("rights", "owns");
        ArrayNode variables = declaration.putArray("variables");
        variables.addObject().put("dataStructure", "plant").put("entitySet", "Phytomer").put("name", "area")
                .put("direction", "provides").put("unit", "m2").put("kind", "extensive");
        variables.addObject().put("dataStructure", "plant").put("entitySet", "Phytomer").put("name", "height")
                .put("direction", "provides").put("unit", "m").put("kind", "descriptor");
        variables.addObject().put("dataStructure", "plant").put("entitySet", "Plant").put("name", "water_uptake")
                .put("direction", "requires").put("unit", "cm3/d").put("kind", "extensive");
        return declaration;
    }

    static GroImp.Options options() {
        GroImp.Options options = new GroImp.Options();
        options.id = "plant";
        options.scaleNames.put(2, "Phytomer");
        options.scaleRanks.put(2, 4L);
        options.variables.put("area", new Variable("m2", null, "extensive", "state"));
        options.variables.put("height", new Variable("m", null, "descriptor", "state"));
        return options;
    }

    public static void main(String[] arguments) throws Exception {
        ObjectMapper json = new ObjectMapper();
        GraphManager graph = new GraphManager(new ServerConnection(null), "shoot", false, false);
        Node root = new Node();
        Node plant = new Node();                       // the plant node GroIMP's graph hangs the phytomers on
        root.addEdgeBitsTo(plant, Graph.BRANCH_EDGE, null);
        Phytomer top = new Phytomer();
        plant.addEdgeBitsTo(top, Graph.REFINEMENT_EDGE, null);
        graph.setRoot(Graph.MAIN_GRAPH, root);
        List<Phytomer> phytomers = new ArrayList<>(List.of(top));
        Map<Long, Long> ids = new HashMap<>();         // GroIMP node id: session id
        double water = 0;

        try (Participant participant = new Participant(declaration(json), null, null, 600.0)) {
            for (Turn turn; (turn = participant.nextTurn()) != null; ) {
                EntitySet plants = turn.frame().dataStructure("plant").entitySet("Plant");
                long plantId = plants.column("id").longs()[0];                      // CPlantBox's plant
                if (turn.phase().equals("step")) {
                    double uptake = plants.column("water_uptake").doubles()[0];
                    water += Double.isNaN(uptake) ? 0 : uptake * (turn.until() - turn.time());
                    for (Phytomer phytomer : phytomers) phytomer.area *= 1.15;       // the leaves expand
                    while (water >= WATER_PER_PHYTOMER) {                            // a new phytomer on top
                        water -= WATER_PER_PHYTOMER;
                        Phytomer next = new Phytomer();
                        next.height = top.height + 0.03;
                        top.addEdgeBitsTo(next, Graph.SUCCESSOR_EDGE, null);
                        phytomers.add(next);
                        top = next;
                    }
                }
                // the graph written by GroIMP's adapter, its phytomers sent under the session's plant
                DataStructure written = GroImp.toDataStructure(root, options());
                EntitySet set = written.entitySet("Phytomer");
                long[] nodes = set.column("id").longs();
                long[] session = new long[nodes.length], complexes = new long[nodes.length];
                long[] parents = set.column("parent").longs().clone();
                for (int row = 0; row < nodes.length; row++) {
                    final long node = nodes[row];
                    session[row] = ids.computeIfAbsent(node, key -> participant.idOffset + ids.size());
                    complexes[row] = plantId;
                }
                for (int row = 0; row < parents.length; row++) if (parents[row] >= 0) parents[row] = ids.get(parents[row]);
                EntitySet out = new EntitySet("Phytomer", 4L);
                out.set("id", Column.of(session)).set("complex", Column.of(complexes)).set("parent", Column.of(parents))
                        .set("edge_type", set.column("edge_type")).set("label", set.column("label"))
                        .set("area", set.column("area")).set("height", set.column("height"));
                DataStructure update = new DataStructure("plant");
                update.entitySets.add(out);
                Frame frame = new Frame();
                frame.dataStructures.add(update);
                participant.sendUpdate(frame);
                System.out.println("groimp: " + phytomers.size() + " phytomers, water left " + Math.round(water * 1000) / 1000.0
                        + " cm3");
            }
            System.out.println("groimp: the session ended (" + participant.stopped + ")");
        }
    }
}
