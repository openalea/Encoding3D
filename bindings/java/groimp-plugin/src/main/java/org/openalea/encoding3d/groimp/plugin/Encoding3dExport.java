package org.openalea.encoding3d.groimp.plugin;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.openalea.encoding3d.Codec;
import org.openalea.encoding3d.DataStructure;
import org.openalea.encoding3d.EntitySet;
import org.openalea.encoding3d.Frame;
import org.openalea.encoding3d.Mesh;
import org.openalea.encoding3d.groimp.GroImp;

import de.grogra.gltf.exporter.GLTFExport;
import de.grogra.gltf.exporter.GLTFNodeWrapper;
import de.grogra.graph.Graph;
import de.grogra.graph.impl.Node;
import de.grogra.pf.io.FilterItem;
import de.grogra.pf.io.FilterSource;
import de.javagl.jgltf.model.AccessorData;
import de.javagl.jgltf.model.AccessorFloatData;
import de.javagl.jgltf.model.AccessorIntData;
import de.javagl.jgltf.model.AccessorShortData;
import de.javagl.jgltf.model.AccessorByteData;
import de.javagl.jgltf.model.MeshModel;
import de.javagl.jgltf.model.MeshPrimitiveModel;
import de.javagl.jgltf.model.NodeModel;
import de.javagl.jgltf.model.impl.DefaultNodeModel;

/**
 * The 3D view of a GroIMP project as an encoding3d frame (a .glb file): the graph below the project's root (its scales,
 * topology and fields, by {@link GroImp#toDataStructure}) and the scene's geometry as one mesh, each triangle carrying
 * the rows of its node and of the node's complexes. The shapes are meshed by GroIMP's glTF plugin (its per-shape
 * exporters, as for a .gltf file); this class collects their triangles in the scene's frame (GroIMP's: z up), node by
 * node, instead of writing glTF.
 */
public class Encoding3dExport extends GLTFExport {
    /** The id of no node, for meshes whose node is not an entity (e.g. the scene's ground). */
    private static final long NO_NODE = -1;

    public Encoding3dExport(FilterItem item, FilterSource source) {
        super(item, source);
    }

    @Override
    public void write(File file) throws IOException {
        write();                                                 // the glTF plugin's scene walk: one wrapper per node
        DefaultNodeModel root = assembleTree();
        Node graphRoot = (Node) getGraphState().getGraph().getRoot(Graph.MAIN_GRAPH);
        GroImp.Options options = new GroImp.Options();
        options.id = "plants";
        DataStructure plants = GroImp.toDataStructure(graphRoot, options);

        java.util.Set<Long> entities = new java.util.HashSet<>();
        for (EntitySet set : plants.entitySets) for (long id : set.column("id").longs()) entities.add(id);
        List<Double> positions = new ArrayList<>();
        List<Long> nodes = new ArrayList<>();
        collect(root, identity(), NO_NODE, entities, positions, nodes);
        if (!positions.isEmpty()) plants.meshes.add(mesh(plants, positions, nodes));

        Frame frame = new Frame();
        frame.dataStructures.add(plants);
        frame.writer.put("platform", "GroIMP").put("adapter", "org.openalea.encoding3d.groimp.plugin");
        frame.vocabularyVersion = "0.2";
        Codec.write(file.toPath(), frame);
    }

    /** The glTF plugin's node tree, its wrappers linked as GLTFExport links them (a child under its parent's node). */
    private DefaultNodeModel assembleTree() {
        DefaultNodeModel root = new DefaultNodeModel();
        for (String key : nodeRegistry.getKeys()) {
            GLTFNodeWrapper wrapper = (GLTFNodeWrapper) nodeRegistry.get(key);
            GLTFNodeWrapper parent = wrapper.getParentId() == -1 ? null
                    : (GLTFNodeWrapper) nodeRegistry.get("" + wrapper.getParentId());
            if (parent != null && parent.getOutNode() != null) parent.addChild(wrapper);
            else root.addChild(wrapper.getInNode());
        }
        return root;
    }

    private static float[] identity() {
        return new float[] {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    }

    /** Column-major 4×4 product a·b. */
    private static float[] multiply(float[] a, float[] b) {
        float[] product = new float[16];
        for (int column = 0; column < 4; column++)
            for (int row = 0; row < 4; row++) {
                float sum = 0;
                for (int k = 0; k < 4; k++) sum += a[k * 4 + row] * b[column * 4 + k];
                product[column * 4 + row] = sum;
            }
        return product;
    }

    /** The GroIMP node id a glTF node stands for ("12" or "12_b"), else NO_NODE. */
    private static long nodeId(NodeModel node) {
        String name = node.getName();
        if (name == null || name.isEmpty()) return NO_NODE;
        try {
            return Long.parseLong(name.endsWith("_b") ? name.substring(0, name.length() - 2) : name);
        } catch (NumberFormatException error) {
            return NO_NODE;
        }
    }

    /** Each triangle of the tree below {@code node}, its vertices in the scene's frame, with the id of its node. A glTF
     * node that is no entity (unnamed, or an instance's, whose id the glTF plugin makes up) takes its nearest ancestor's
     * entity: an instance's geometry, the node instantiating it. */
    private void collect(NodeModel node, float[] parentTransform, long inheritedId, java.util.Set<Long> entities,
                         List<Double> positions, List<Long> nodes) {
        float[] transform = multiply(parentTransform, node.computeLocalTransform(null));
        long own = nodeId(node);
        long id = entities.contains(own) ? own : inheritedId;
        for (MeshModel mesh : node.getMeshModels())
            for (MeshPrimitiveModel primitive : mesh.getMeshPrimitiveModels()) {
                if (primitive.getMode() != 4 || !primitive.getAttributes().containsKey("POSITION")) continue;
                AccessorFloatData points = (AccessorFloatData) primitive.getAttributes().get("POSITION").getAccessorData();
                int[] indices = primitive.getIndices() == null ? null : indices(primitive.getIndices().getAccessorData());
                int count = indices == null ? points.getNumElements() : indices.length;
                for (int corner = 0; corner < count; corner++) {
                    int vertex = indices == null ? corner : indices[corner];
                    float x = points.get(vertex, 0), y = points.get(vertex, 1), z = points.get(vertex, 2);
                    for (int axis = 0; axis < 3; axis++)
                        positions.add((double) (transform[axis] * x + transform[4 + axis] * y + transform[8 + axis] * z
                                + transform[12 + axis]));
                    nodes.add(id);
                }
            }
        for (NodeModel child : node.getChildren()) collect(child, transform, id, entities, positions, nodes);
    }

    private static int[] indices(AccessorData data) {
        int[] values = new int[data.getNumElements()];
        for (int index = 0; index < values.length; index++) {
            if (data instanceof AccessorShortData shorts) values[index] = shorts.getInt(index);
            else if (data instanceof AccessorIntData ints) values[index] = ints.get(index);
            else if (data instanceof AccessorByteData bytes) values[index] = bytes.getInt(index);
            else throw new IllegalArgumentException("indices of type " + data.getComponentType());
        }
        return values;
    }

    /** The triangles as an encoding3d mesh, three vertices each, with each vertex's row in every entity set: its node's,
     * and its node's complexes' up the scales (NO_ID where it has none). */
    private static Mesh mesh(DataStructure plants, List<Double> positions, List<Long> nodes) {
        Map<Long, int[]> where = new HashMap<>();               // id -> (entity set, row)
        Map<Long, Long> complexOf = new HashMap<>();
        for (int setIndex = 0; setIndex < plants.entitySets.size(); setIndex++) {
            EntitySet set = plants.entitySets.get(setIndex);
            long[] ids = set.column("id").longs();
            long[] complexes = set.has("complex") ? set.column("complex").longs() : null;
            for (int row = 0; row < ids.length; row++) {
                where.put(ids[row], new int[] {setIndex, row});
                if (complexes != null && complexes[row] != EntitySet.NO_ID) complexOf.put(ids[row], complexes[row]);
            }
        }
        double[] points = new double[positions.size()];
        for (int index = 0; index < points.length; index++) points[index] = positions.get(index);
        Mesh mesh = new Mesh("scene", points);
        long[][] rows = new long[plants.entitySets.size()][nodes.size()];
        for (long[] setRows : rows) java.util.Arrays.fill(setRows, EntitySet.NO_ID);
        for (int vertex = 0; vertex < nodes.size(); vertex++) {
            Long id = nodes.get(vertex);
            while (id != null && id != NO_NODE && where.containsKey(id)) {   // the node, then its complexes
                int[] place = where.get(id);
                rows[place[0]][vertex] = place[1];
                id = complexOf.get(id);
            }
        }
        for (int setIndex = 0; setIndex < rows.length; setIndex++) {
            boolean any = false;
            for (long row : rows[setIndex]) any |= row != EntitySet.NO_ID;
            if (any) mesh.featureRows.put(plants.entitySets.get(setIndex).name, rows[setIndex]);
        }
        return mesh;
    }
}
