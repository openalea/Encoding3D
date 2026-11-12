package org.openalea.encoding3d;

/**
 * The entities of one scale of a graph (rank: the scale's rank, coarser first), or a grid's cells (no rank). Reserved
 * columns: id (INT64, stable across frames, never reused), label (text), complex (the id of the containing entity at a
 * coarser scale, NO_ID if none), parent (the predecessor's id at the same scale, NO_ID if none), edge_type ("none",
 * "successor", "branch"); an adaptive grid's cells: level and index.
 */
public class EntitySet extends Table {
    /** The id of no entity. */
    public static final long NO_ID = -1;

    public Long rank;
    /** Its base scale (Plant, Axis, ..., Connection), or "mixed". */
    public String scale;

    public EntitySet(String name, Long rank) {
        super(name);
        this.rank = rank;
    }

    public EntitySet(String name) {
        this(name, null);
    }

    @Override
    public Kind kind() {
        return Kind.ENTITY_SET;
    }

    /** The ids of its entities: its id column, or a grid's row numbers (from 0) when it has none. */
    public long[] ids() {
        if (has("id")) return column("id").longs();
        long[] rows = new long[rowCount()];
        for (int row = 0; row < rows.length; row++) rows[row] = row;
        return rows;
    }
}
