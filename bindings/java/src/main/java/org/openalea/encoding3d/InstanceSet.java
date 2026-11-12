package org.openalea.encoding3d;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Instances of shared templates (specification §12.2): one row per instance, its reserved columns {@code template} (the
 * index in {@code parts} of its template, INT64), {@code owner} (the id, in the entity set {@code owners}, of the entity
 * it draws), {@code transform} (16 numbers per row, the column-major 4×4 placing the template; identity when absent) and
 * {@code id}, then its own variables. {@code parts}: the keys of the parts (templates and operators) the instances use;
 * {@code vectors} and {@code derived}: its vectors and derived fields (their columns &lt;vector&gt;__count,
 * &lt;field&gt;__operator and &lt;field&gt;__weight are written from them, not held as columns).
 */
public final class InstanceSet extends Table {
    public String owners;
    public final List<String> parts = new ArrayList<>();
    public final Map<String, Ragged> vectors = new LinkedHashMap<>();
    public final List<DerivedField> derived = new ArrayList<>();

    public InstanceSet(String name, String owners) {
        super(name);
        this.owners = owners;
    }

    public InstanceSet(String name) {
        this(name, null);
    }

    @Override
    public Kind kind() {
        return Kind.INSTANCE_SET;
    }

    public int count() {
        return rowCount();
    }

    public Ragged vector(String vectorName) {
        Ragged ragged = vectors.get(vectorName);
        if (ragged == null) throw new Encoding3dException("instance set '" + name + "' has no vector '" + vectorName + "'");
        return ragged;
    }

    public DerivedField derivedField(String fieldName) {
        for (DerivedField field : derived) if (field.name.equals(fieldName)) return field;
        throw new Encoding3dException("instance set '" + name + "' has no derived field '" + fieldName + "'");
    }

    /** The 4×4 placing instance {@code row}'s template, column-major (identity without a transform column). */
    public double[] transform(int row) {
        if (!has("transform")) return new double[] {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
        double[] matrix = new double[16];
        System.arraycopy(column("transform").doubles(), row * 16, matrix, 0, 16);
        return matrix;
    }
}
