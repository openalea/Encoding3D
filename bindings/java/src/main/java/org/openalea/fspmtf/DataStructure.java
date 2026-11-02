package org.openalea.fspmtf;

import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * One plant population's graph, or one environment model's grid. origin: its frame in the scene, a 4×4 matrix row by
 * row. extras: JSON values for the writing platform (e.g. what it needs to rebuild its own data structure); other
 * readers keep them without interpreting them.
 */
public final class DataStructure {
    public String id;
    public String kind = "graph";
    public final List<EntitySet> entitySets = new ArrayList<>();
    public final List<Relation> relations = new ArrayList<>();
    public Table scalars;
    public Grid grid;
    public final List<Mesh> meshes = new ArrayList<>();
    public double[] origin = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    public String platform;
    public String model;
    public ObjectNode extras = JsonNodeFactory.instance.objectNode();

    public DataStructure(String id) {
        this.id = id;
    }

    public DataStructure(String id, String kind) {
        this.id = id;
        this.kind = kind;
    }

    public EntitySet entitySet(String name) {
        for (EntitySet set : entitySets) if (set.name.equals(name)) return set;
        throw new FspmTfException("data structure '" + id + "' has no entity set '" + name + "'");
    }
}
