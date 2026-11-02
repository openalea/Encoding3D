package org.openalea.fspmtf.groimp;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

import org.openalea.fspmtf.Column;
import org.openalea.fspmtf.ComponentType;
import org.openalea.fspmtf.DataStructure;
import org.openalea.fspmtf.EntitySet;
import org.openalea.fspmtf.FspmTfException;
import org.openalea.fspmtf.Relation;
import org.openalea.fspmtf.Variable;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

import de.grogra.graph.Graph;
import de.grogra.graph.impl.Edge;
import de.grogra.graph.impl.Node;
import de.grogra.persistence.ManageableType;
import de.grogra.reflect.TypeId;

/**
 * A GroIMP graph as an fspm-TF graph, and back.
 *
 * <table>
 * <tr><th>fspm-TF</th><th>GroIMP</th></tr>
 * <tr><td>one entity set per scale (rank: the scale, from 1)</td><td>the nodes at that refinement depth below the
 * root; a node reached by a successor or branch edge has its parent's scale, by a refinement edge one more</td></tr>
 * <tr><td>id</td><td>{@code Node.getId()}</td></tr>
 * <tr><td>label</td><td>the node's class's simple name</td></tr>
 * <tr><td>complex</td><td>the source of its incoming refinement edge, else its parent's complex</td></tr>
 * <tr><td>parent, edge_type</td><td>the source of its incoming successor (successor) or branch (branch) edge at the same
 * scale</td></tr>
 * <tr><td>relations</td><td>the other edge bits between exported nodes (containment, mark, notifies, user edges), one
 * relation per bit and pair of entity sets</td></tr>
 * <tr><td>variables</td><td>the nodes' managed fields declared below {@code Node} (numbers, booleans, chars and Strings;
 * 3-component vecmath tuples as vectors)</td></tr>
 * </table>
 *
 * <p>The graph's root (e.g. an RGG root) is the data structure itself, not an entity. What fspm-TF 0.1 cannot say is
 * kept in {@code extras["groimp"]}: the rows where a node's class has no such field, and the classes' names.</p>
 */
public final class GroImp {
    /** The name of GroIMP's entry in a data structure's extras. */
    public static final String PLATFORM = "groimp";
    private static final int TREE_EDGES = Graph.SUCCESSOR_EDGE | Graph.BRANCH_EDGE | Graph.REFINEMENT_EDGE;
    private static final Map<Integer, String> RELATION_NAMES = Map.of(Graph.CONTAINMENT_EDGE, "containment",
            Graph.CONTAINMENT_END_EDGE, "containment_end", Graph.MARK_EDGE, "mark", Graph.NOTIFIES_EDGE, "notifies");

    /** How a graph is written. */
    public static final class Options {
        /** The data structure's id. */
        public String id = "plants";
        /** The entity set name of each scale (1: the coarsest); by default its nodes' class name when they share one,
         * else {@code Scale<n>}. */
        public final Map<Integer, String> scaleNames = new HashMap<>();
        /** The rank of each scale's entity set (by default its refinement depth); e.g. the vocabulary's base scales'
         * positions (Plant 1, Axis 2, Organ 5, SubOrgan 6). */
        public final Map<Integer, Long> scaleRanks = new HashMap<>();
        /** The declarations of the fields (by name): unit, standard name, kind, role. */
        public final Map<String, Variable> variables = new HashMap<>();
        public String model;
    }

    private GroImp() {}

    /** A node's place in the exported graph. */
    private static final class Entity {
        final Node node;
        final int scale;
        Node complex;
        Node parent;
        String edgeType;

        Entity(Node node, int scale, Node complex, Node parent, String edgeType) {
            this.node = node;
            this.scale = scale;
            this.complex = complex;
            this.parent = parent;
            this.edgeType = edgeType;
        }
    }

    /** The graph below {@code root} (not included) as a {@code graph} data structure. */
    public static DataStructure toDataStructure(Node root, Options options) {
        // Depth first along successor, branch and refinement edges, each node once, children in edge order
        Map<Node, Entity> entities = new IdentityHashMap<>();
        List<Entity> order = new ArrayList<>();
        ArrayDeque<Entity> stack = new ArrayDeque<>();
        List<Entity> rootChildren = children(new Entity(root, 0, null, null, "none"), root, true);
        for (int index = rootChildren.size() - 1; index >= 0; index--) stack.push(rootChildren.get(index));
        while (!stack.isEmpty()) {
            Entity entity = stack.pop();
            if (entities.containsKey(entity.node)) continue;
            if (entity.node.getId() < 0)
                throw new FspmTfException("node " + entity.node + " has no id: it is not in a graph");
            entities.put(entity.node, entity);
            order.add(entity);
            List<Entity> next = children(entity, root, false);
            for (int index = next.size() - 1; index >= 0; index--) stack.push(next.get(index));
        }

        // Complex and parent from each node's incoming edges, whichever edge reached it first: a lateral's first
        // component has both a refinement edge from its complex and a branch edge from its bearer
        for (Entity entity : order) {
            Node node = entity.node;
            Node complex = null, parent = null;
            String edgeType = "none";
            for (Edge edge = node.getFirstEdge(); edge != null; edge = edge.getNext(node)) {
                if (edge.getTarget() != node || !entities.containsKey(edge.getSource())) continue;
                int bits = edge.getEdgeBits();
                if ((bits & Graph.REFINEMENT_EDGE) != 0) complex = edge.getSource();
                else if ((bits & (Graph.SUCCESSOR_EDGE | Graph.BRANCH_EDGE)) != 0
                        && entities.get(edge.getSource()).scale == entity.scale) {
                    parent = edge.getSource();
                    edgeType = (bits & Graph.SUCCESSOR_EDGE) != 0 ? "successor" : "branch";
                }
            }
            entity.complex = complex;
            entity.parent = parent;
            entity.edgeType = edgeType;
        }
        for (Entity entity : order) {                         // no refinement edge: its parent's complex (MTG's rule)
            Entity ancestor = entity;
            while (ancestor.complex == null && ancestor.parent != null) ancestor = entities.get(ancestor.parent);
            entity.complex = ancestor.complex;
        }

        Map<Integer, List<Entity>> byScale = new java.util.TreeMap<>();
        for (Entity entity : order) byScale.computeIfAbsent(entity.scale, scale -> new ArrayList<>()).add(entity);
        Map<Integer, String> setNames = new HashMap<>();
        for (Map.Entry<Integer, List<Entity>> item : byScale.entrySet()) {
            Set<String> classes = new LinkedHashSet<>();
            for (Entity entity : item.getValue()) classes.add(entity.node.getClass().getSimpleName());
            setNames.put(item.getKey(), options.scaleNames.getOrDefault(item.getKey(),
                    classes.size() == 1 ? classes.iterator().next() : "Scale" + item.getKey()));
        }

        DataStructure dataStructure = new DataStructure(options.id, "graph");
        dataStructure.platform = "GroIMP";
        dataStructure.model = options.model;
        ObjectNode extras = JsonNodeFactory.instance.objectNode();
        ObjectNode missing = extras.putObject("missing");
        ObjectNode classes = extras.putObject("classes");
        int coarsest = byScale.isEmpty() ? 0 : byScale.keySet().iterator().next();
        for (Map.Entry<Integer, List<Entity>> item : byScale.entrySet()) {
            String setName = setNames.get(item.getKey());
            List<Entity> rows = item.getValue();
            EntitySet set = new EntitySet(setName, options.scaleRanks.getOrDefault(item.getKey(), (long) item.getKey()));
            long[] ids = new long[rows.size()], complexes = new long[rows.size()], parents = new long[rows.size()];
            String[] labels = new String[rows.size()], edgeTypes = new String[rows.size()];
            for (int row = 0; row < rows.size(); row++) {
                Entity entity = rows.get(row);
                ids[row] = entity.node.getId();
                labels[row] = entity.node.getClass().getSimpleName();
                complexes[row] = entity.complex == null ? EntitySet.NO_ID : entity.complex.getId();
                parents[row] = entity.parent == null ? EntitySet.NO_ID : entity.parent.getId();
                edgeTypes[row] = entity.edgeType;
                classes.put(labels[row], entity.node.getClass().getName());
            }
            set.set("id", Column.of(ids)).set("label", Column.of(labels));
            if (item.getKey() != coarsest) set.set("complex", Column.of(complexes));
            set.set("parent", Column.of(parents)).set("edge_type", Column.of(edgeTypes));
            ObjectNode missingOfSet = JsonNodeFactory.instance.objectNode();
            addFields(set, rows, options, missingOfSet);
            if (!missingOfSet.isEmpty()) missing.set(setName, missingOfSet);
            dataStructure.entitySets.add(set);
        }
        if (missing.isEmpty()) extras.remove("missing");
        addRelations(dataStructure, order, entities, setNames);
        dataStructure.extras.set(PLATFORM, extras);
        return dataStructure;
    }

    /** The nodes {@code entity}'s outgoing tree edges lead to, as entities. */
    private static List<Entity> children(Entity entity, Node root, boolean fromRoot) {
        List<Entity> found = new ArrayList<>();
        Node node = entity.node;
        for (Edge edge = node.getFirstEdge(); edge != null; edge = edge.getNext(node)) {
            if (edge.getSource() != node) continue;
            int bits = edge.getEdgeBits();
            if ((bits & TREE_EDGES) == 0) continue;
            Node target = edge.getTarget();
            if (target == root) continue;
            if (fromRoot) {                                     // the root's children: the coarsest scale's first nodes
                found.add(new Entity(target, 1, null, null, "none"));
            } else if ((bits & Graph.REFINEMENT_EDGE) != 0) {    // one scale finer: its complex
                found.add(new Entity(target, entity.scale + 1, node, null, "none"));
            } else {                                              // the same scale: its parent
                found.add(new Entity(target, entity.scale, entity.complex, node,
                        (bits & Graph.SUCCESSOR_EDGE) != 0 ? "successor" : "branch"));
            }
        }
        return found;
    }

    private static boolean isOwnField(ManageableType.Field field) {
        return field.getDeclaringType() != Node.$TYPE && (field.getModifiers() & ManageableType.Field.HIDDEN) == 0;
    }

    /** A field's value, as a column value: Double, Float, Long, Integer, Short, Byte, Boolean, String, double[3]; null
     * when not written. */
    private static Object fieldValue(ManageableType.Field field, Node node) {
        return switch (field.getType().getTypeId()) {
            case TypeId.BOOLEAN -> field.getBoolean(node);
            case TypeId.BYTE -> field.getByte(node);
            case TypeId.SHORT -> field.getShort(node);
            case TypeId.CHAR -> String.valueOf(field.getChar(node));
            case TypeId.INT -> field.getInt(node);
            case TypeId.LONG -> field.getLong(node);
            case TypeId.FLOAT -> field.getFloat(node);
            case TypeId.DOUBLE -> field.getDouble(node);
            case TypeId.OBJECT -> objectValue(field.getObject(node));
            default -> null;
        };
    }

    /** Strings as they are, vecmath's Tuple3d and Tuple3f (public x, y, z) as 3 doubles; anything else is not written. */
    private static Object objectValue(Object value) {
        if (value instanceof String) return value;
        if (value == null) return null;
        for (Class<?> type = value.getClass(); type != null; type = type.getSuperclass())
            if (type.getName().equals("javax.vecmath.Tuple3d") || type.getName().equals("javax.vecmath.Tuple3f")) {
                try {
                    double[] vector = new double[3];
                    String[] names = {"x", "y", "z"};
                    for (int axis = 0; axis < 3; axis++)
                        vector[axis] = ((Number) type.getField(names[axis]).get(value)).doubleValue();
                    return vector;
                } catch (ReflectiveOperationException error) {
                    return null;
                }
            }
        return null;
    }

    /** The rows' managed fields as columns (in order of first appearance), the missing rows of each in {@code missing}. */
    private static void addFields(EntitySet set, List<Entity> rows, Options options, ObjectNode missing) {
        Map<String, Object[]> values = new LinkedHashMap<>();
        for (int row = 0; row < rows.size(); row++) {
            Node node = rows.get(row).node;
            ManageableType type = node.getNType();
            for (int index = 0; index < type.getManagedFieldCount(); index++) {
                ManageableType.Field field = type.getManagedField(index);
                if (!isOwnField(field) || set.isReserved(field.getName())) continue;
                Object value = fieldValue(field, node);
                if (value == null) continue;
                values.computeIfAbsent(field.getName(), name -> new Object[rows.size()])[row] = value;
            }
        }
        for (Map.Entry<String, Object[]> item : values.entrySet()) {
            Column column = column(item.getValue());
            if (column == null) continue;                          // values of several kinds: not written
            set.set(item.getKey(), column);
            var absent = JsonNodeFactory.instance.arrayNode();
            for (int row = 0; row < item.getValue().length; row++) if (item.getValue()[row] == null) absent.add(row);
            if (!absent.isEmpty()) missing.set(item.getKey(), absent);
            Variable declared = options.variables.get(item.getKey());
            if (declared != null) set.declare(item.getKey(), declared);
        }
    }

    /** A column of values of one kind (null where a row has none: NaN, 0, false or ""); null for mixed kinds. */
    private static Column column(Object[] values) {
        Class<?> kind = null;
        for (Object value : values)
            if (value != null) {
                if (kind != null && kind != value.getClass()) return null;
                kind = value.getClass();
            }
        int rows = values.length;
        if (kind == Double.class) {
            double[] column = new double[rows];
            for (int row = 0; row < rows; row++) column[row] = values[row] == null ? Double.NaN : (Double) values[row];
            return Column.of(column);
        } else if (kind == Float.class) {
            float[] column = new float[rows];
            for (int row = 0; row < rows; row++) column[row] = values[row] == null ? Float.NaN : (Float) values[row];
            return Column.of(column);
        } else if (kind == Long.class) {
            long[] column = new long[rows];
            for (int row = 0; row < rows; row++) column[row] = values[row] == null ? 0 : (Long) values[row];
            return Column.of(column);
        } else if (kind == Integer.class) {
            int[] column = new int[rows];
            for (int row = 0; row < rows; row++) column[row] = values[row] == null ? 0 : (Integer) values[row];
            return Column.of(column);
        } else if (kind == Short.class) {
            short[] column = new short[rows];
            for (int row = 0; row < rows; row++) column[row] = values[row] == null ? 0 : (Short) values[row];
            return new Column(ComponentType.INT16, column);
        } else if (kind == Byte.class) {
            byte[] column = new byte[rows];
            for (int row = 0; row < rows; row++) column[row] = values[row] == null ? 0 : (Byte) values[row];
            return new Column(ComponentType.INT8, column);
        } else if (kind == Boolean.class) {
            boolean[] column = new boolean[rows];
            for (int row = 0; row < rows; row++) column[row] = values[row] != null && (Boolean) values[row];
            return Column.of(column);
        } else if (kind == String.class) {
            String[] column = new String[rows];
            for (int row = 0; row < rows; row++) column[row] = values[row] == null ? "" : (String) values[row];
            return Column.of(column);
        } else if (kind == double[].class) {
            double[] column = new double[rows * 3];
            for (int row = 0; row < rows; row++)
                for (int axis = 0; axis < 3; axis++)
                    column[row * 3 + axis] = values[row] == null ? Double.NaN : ((double[]) values[row])[axis];
            return Column.vectors(3, column);
        }
        return null;
    }

    /** The other edge bits between exported nodes (also on tree edges): one relation per bit and pair of sets. */
    private static void addRelations(DataStructure dataStructure, List<Entity> order, Map<Node, Entity> entities,
                                     Map<Integer, String> setNames) {
        Map<String, List<long[]>> edges = new LinkedHashMap<>();
        Map<String, String[]> ends = new HashMap<>();
        for (Entity entity : order) {
            Node node = entity.node;
            for (Edge edge = node.getFirstEdge(); edge != null; edge = edge.getNext(node)) {
                if (edge.getSource() != node || !entities.containsKey(edge.getTarget())) continue;
                int others = edge.getEdgeBits() & ~TREE_EDGES;
                for (int bit = 1; bit != 0 && others != 0; bit <<= 1) {
                    if ((others & bit) == 0) continue;
                    others &= ~bit;
                    String kind = RELATION_NAMES.getOrDefault(bit, "edge_" + Integer.toHexString(bit));
                    String source = setNames.get(entity.scale), target = setNames.get(entities.get(edge.getTarget()).scale);
                    String key = kind + "|" + source + "|" + target;
                    edges.computeIfAbsent(key, k -> new ArrayList<>()).add(new long[] {node.getId(), edge.getTarget().getId()});
                    ends.put(key, new String[] {kind, source, target});
                }
            }
        }
        Map<String, Integer> kindCount = new HashMap<>();
        for (String[] end : ends.values()) kindCount.merge(end[0], 1, Integer::sum);
        for (Map.Entry<String, List<long[]>> item : edges.entrySet()) {
            String[] end = ends.get(item.getKey());
            String name = kindCount.get(end[0]) == 1 ? end[0] : end[0] + "_" + end[1] + "_" + end[2];
            Relation relation = new Relation(name, end[1], end[2]);
            long[] sources = new long[item.getValue().size()], targets = new long[item.getValue().size()];
            for (int index = 0; index < sources.length; index++) {
                sources[index] = item.getValue().get(index)[0];
                targets[index] = item.getValue().get(index)[1];
            }
            relation.set("source", Column.of(sources)).set("target", Column.of(targets));
            dataStructure.relations.add(relation);
        }
    }

    // ── Data structure → graph ──────────────────────────────────────────

    /**
     * A graph data structure as GroIMP nodes below a new root: each entity a node made by {@code nodes} from its label
     * (e.g. {@code label -> new Internode()}), its fields set from its row, linked by refinement edges from its complex
     * (the first of each complex's components only, as GroIMP's multiscale graphs), successor or branch edges from its
     * parent, and its relations' edge bits. The root's children: the coarsest scale's entities without parent. Returns
     * the root; GroIMP gives the nodes new ids when the root is put in a graph, {@code idsOf} maps each entity's id to
     * its node.
     */
    public static Node toGraph(DataStructure dataStructure, Function<String, Node> nodes, Map<Long, Node> idsOf) {
        List<EntitySet> sets = new ArrayList<>();
        for (EntitySet set : dataStructure.entitySets) if (set.rank != null && set.has("id")) sets.add(set);
        sets.sort((left, right) -> Long.compare(left.rank, right.rank));
        ObjectNode missing = dataStructure.extras.path(PLATFORM).path("missing") instanceof ObjectNode found ? found : null;
        Node root = new Node();
        for (EntitySet set : sets) {
            long[] ids = set.column("id").longs();
            String[] labels = set.has("label") ? set.column("label").strings() : null;
            for (int row = 0; row < ids.length; row++) {
                Node node = nodes.apply(labels == null ? set.name : labels[row]);
                if (node == null) throw new FspmTfException("no node made for label '" + labels[row] + "'");
                setFields(node, set, row, missing != null && missing.get(set.name) instanceof ObjectNode ofSet ? ofSet : null);
                idsOf.put(ids[row], node);
            }
        }
        Set<Long> refined = new java.util.HashSet<>();               // complexes already linked to a first component
        for (EntitySet set : sets) {
            long[] ids = set.column("id").longs();
            long[] parents = set.has("parent") ? set.column("parent").longs() : null;
            String[] edgeTypes = set.has("edge_type") ? set.column("edge_type").strings() : null;
            long[] complexes = set.has("complex") ? set.column("complex").longs() : null;
            for (int row = 0; row < ids.length; row++) {
                Node node = idsOf.get(ids[row]);
                long parent = parents == null ? EntitySet.NO_ID : parents[row];
                long complex = complexes == null ? EntitySet.NO_ID : complexes[row];
                if (parent != EntitySet.NO_ID) {
                    idsOf.get(parent).addEdgeBitsTo(node,
                            "successor".equals(edgeTypes[row]) ? Graph.SUCCESSOR_EDGE : Graph.BRANCH_EDGE, null);
                    Long parentComplex = complexOf(sets, parent);
                    if (complex != EntitySet.NO_ID && (parentComplex == null || parentComplex != complex)
                            && refined.add(complex))                  // the first component of its complex
                        idsOf.get(complex).addEdgeBitsTo(node, Graph.REFINEMENT_EDGE, null);
                } else if (complex != EntitySet.NO_ID) {
                    idsOf.get(complex).addEdgeBitsTo(node, Graph.REFINEMENT_EDGE, null);
                    refined.add(complex);
                } else {
                    root.addEdgeBitsTo(node, Graph.BRANCH_EDGE, null);
                }
            }
        }
        for (Relation relation : dataStructure.relations) {
            int bit = 0;
            for (Map.Entry<Integer, String> item : RELATION_NAMES.entrySet())
                if (relation.name.equals(item.getValue()) || relation.name.startsWith(item.getValue() + "_")) bit = item.getKey();
            if (bit == 0 && relation.name.startsWith("edge_")) {
                String hex = relation.name.substring(5).split("_")[0];
                bit = Integer.parseInt(hex, 16);
            }
            if (bit == 0) continue;                                   // another platform's relation: not an edge bit
            long[] sources = relation.column("source").longs(), targets = relation.column("target").longs();
            for (int index = 0; index < sources.length; index++)
                idsOf.get(sources[index]).addEdgeBitsTo(idsOf.get(targets[index]), bit, null);
        }
        return root;
    }

    private static Long complexOf(List<EntitySet> sets, long id) {
        for (EntitySet set : sets) {
            if (!set.has("complex")) continue;
            long[] ids = set.column("id").longs();
            for (int row = 0; row < ids.length; row++) if (ids[row] == id) return set.column("complex").longs()[row];
        }
        return null;
    }

    private static void setFields(Node node, EntitySet set, int row, ObjectNode missing) {
        ManageableType type = node.getNType();
        for (String name : set.variableNames()) {
            ManageableType.Field field = type.getManagedField(name);
            if (field == null || !isOwnField(field)) continue;
            if (missing != null && missing.has(name)) {
                boolean absent = false;
                for (var absentRow : missing.get(name)) absent |= absentRow.asInt() == row;
                if (absent) continue;
            }
            Column column = set.column(name);
            switch (field.getType().getTypeId()) {
                case TypeId.BOOLEAN -> field.setBoolean(node, column.booleans()[row]);
                case TypeId.BYTE -> field.setByte(node, (byte) column.doubleAt(row));
                case TypeId.SHORT -> field.setShort(node, (short) column.doubleAt(row));
                case TypeId.CHAR -> field.setChar(node, column.strings()[row].charAt(0));
                case TypeId.INT -> field.setInt(node, (int) column.doubleAt(row));
                case TypeId.LONG -> field.setLong(node, (long) column.doubleAt(row));
                case TypeId.FLOAT -> field.setFloat(node, (float) column.doubleAt(row));
                case TypeId.DOUBLE -> field.setDouble(node, column.doubleAt(row));
                case TypeId.OBJECT -> {
                    if (column.type == ComponentType.STRING) field.setObject(node, column.strings()[row]);
                }
                default -> { }
            }
        }
    }
}
