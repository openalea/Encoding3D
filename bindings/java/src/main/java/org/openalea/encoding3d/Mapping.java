package org.openalea.encoding3d;

/**
 * Weights between the entities of two data structures: source and target ids, weight. source and target: a data
 * structure's id and an entity set's name.
 */
public class Mapping extends Table {
    public String sourceDataStructure, sourceSet, targetDataStructure, targetSet;
    public String method;

    public Mapping(String name, String sourceDataStructure, String sourceSet, String targetDataStructure,
                   String targetSet, String method) {
        super(name);
        this.sourceDataStructure = sourceDataStructure;
        this.sourceSet = sourceSet;
        this.targetDataStructure = targetDataStructure;
        this.targetSet = targetSet;
        this.method = method;
    }

    @Override
    public Kind kind() {
        return Kind.MAPPING;
    }
}
