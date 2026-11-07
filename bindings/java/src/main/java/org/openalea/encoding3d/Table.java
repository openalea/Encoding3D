package org.openalea.encoding3d;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Columns of equal length, in their order, and the declarations of its variables: a data structure's scalars. */
public class Table {
    /** The kinds of tables, each with its reserved columns. */
    public enum Kind {
        SCALARS(List.of()),
        ENTITY_SET(List.of("id", "label", "complex", "parent", "edge_type", "level", "index", "sibling_order")),
        RELATION(List.of("id", "source", "target", "relation")),
        MAPPING(List.of("source", "target", "weight")),
        INSTANCE_SET(List.of("id", "owner", "template", "transform"));

        public final List<String> reserved;

        Kind(List<String> reserved) {
            this.reserved = reserved;
        }
    }

    public String name;
    public final Map<String, Column> columns = new LinkedHashMap<>();
    public final Map<String, Variable> variables = new LinkedHashMap<>();

    public Table(String name) {
        this.name = name;
    }

    public Kind kind() {
        return Kind.SCALARS;
    }

    /** Sets a column (replacing it, or appending it); returns the table, for chaining. */
    public Table set(String columnName, Column column) {
        columns.put(columnName, column);
        return this;
    }

    public Table declare(String columnName, Variable variable) {
        variables.put(columnName, variable);
        return this;
    }

    public Column column(String columnName) {
        Column column = columns.get(columnName);
        if (column == null) throw new Encoding3dException("table '" + name + "' has no column '" + columnName + "'");
        return column;
    }

    public boolean has(String columnName) {
        return columns.containsKey(columnName);
    }

    public int rowCount() {
        return columns.isEmpty() ? 0 : columns.values().iterator().next().rows();
    }

    public boolean isReserved(String columnName) {
        return kind().reserved.contains(columnName);
    }

    /** The variable columns: all but the reserved ones. */
    public List<String> variableNames() {
        List<String> names = new ArrayList<>();
        for (String columnName : columns.keySet()) if (!isReserved(columnName)) names.add(columnName);
        return names;
    }

    /** Throws when columns have different numbers of rows. */
    public void checkLengths() {
        for (Map.Entry<String, Column> entry : columns.entrySet()) {
            Column column = entry.getValue();
            if (column.hasMissing() && (isReserved(entry.getKey()) || column.width != 1))
                throw new Encoding3dException("column '" + entry.getKey() + "' of '" + name
                        + "': missing values only in variables of one value per row");
            if (column.size() % column.width != 0)
                throw new Encoding3dException("column '" + entry.getKey() + "' of '" + name + "': its values are not whole rows");
            if (column.rows() != rowCount()) throw new Encoding3dException("table '" + name + "': columns of different lengths");
        }
    }
}
