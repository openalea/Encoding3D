package org.openalea.encoding3d;

/**
 * A template (a shared part, specification §12.1): the data structure its part file holds (id "template", kind "table",
 * or "graph" with ranks): the template's own entity sets (e.g. a section's cells, their ids and constant variables),
 * relations, and meshes in the template's coordinates. A template is a valid frame of its own.
 */
public final class Template implements Part {
    public DataStructure dataStructure = new DataStructure("template", "table");

    public EntitySet entitySet(String name) {
        return dataStructure.entitySet(name);
    }
}
