package org.openalea.encoding3d;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Triangles: positions (3 per vertex, in the data structure's frame), three consecutive vertices per triangle, or
 * indices (3 per triangle, from 0) into them; featureRows: per entity set, the row (from 0) of each vertex's entity in
 * that set, NO_ID for none; display: per variable, its float copy per vertex, from the entity set displaySources.
 */
public final class Mesh {
    public String name;
    public double[] positions;
    public final Map<String, long[]> featureRows = new LinkedHashMap<>();
    public long[] indices;
    public final Map<String, float[]> display = new LinkedHashMap<>();
    public final Map<String, String> displaySources = new HashMap<>();

    public Mesh(String name, double[] positions) {
        this.name = name;
        this.positions = positions;
    }

    public int vertexCount() {
        return positions.length / 3;
    }
}
