package org.openalea.encoding3d;

/**
 * An edge table: source and target entity ids (in the entity sets sourceSet and targetSet), an optional id per edge,
 * an optional relation label per edge, and edge variables.
 */
public class Relation extends Table {
    public String sourceSet;
    public String targetSet;

    public Relation(String name, String sourceSet, String targetSet) {
        super(name);
        this.sourceSet = sourceSet;
        this.targetSet = targetSet;
    }

    @Override
    public Kind kind() {
        return Kind.RELATION;
    }
}
