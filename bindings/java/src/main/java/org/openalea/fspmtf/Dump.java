package org.openalea.fspmtf;

import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * A frame as plain JSON values, in the layout of the conformance files' expected values (conformance/README.md), and
 * the comparison {@code fspm-tf compare} makes.
 */
public final class Dump {
    private Dump() {}

    private static void addValue(ArrayNode array, Column column, int index) {
        switch (column.type) {
            case FLOAT32, FLOAT64 -> {
                double value = column.type == ComponentType.FLOAT32 ? column.floats()[index] : column.doubles()[index];
                if (Double.isNaN(value)) array.addNull();
                else if (Double.isInfinite(value)) array.add(value > 0 ? "Infinity" : "-Infinity");
                else array.add(value);
            }
            case BOOLEAN -> array.add(column.booleans()[index]);
            case STRING -> array.add(column.strings()[index]);
            case UINT64 -> array.add(new BigInteger(Long.toUnsignedString(column.longs()[index])));
            case INT64 -> array.add(column.longs()[index]);
            default -> array.add((long) column.doubleAt(index));
        }
    }

    private static ArrayNode columnJson(Column column) {
        ArrayNode items = Glb.MAPPER.createArrayNode();
        if (column.width == 1) {
            for (int index = 0; index < column.size(); index++) addValue(items, column, index);
        } else {
            for (int row = 0; row < column.rows(); row++) {
                ArrayNode vector = items.addArray();
                for (int component = 0; component < column.width; component++) addValue(vector, column, row * column.width + component);
            }
        }
        return items;
    }

    private static ObjectNode tableJson(Table table) {
        ObjectNode entry = Glb.MAPPER.createObjectNode().put("name", table.name).put("count", table.rowCount());
        ObjectNode columns = entry.putObject("columns");
        for (Map.Entry<String, Column> item : table.columns.entrySet()) {
            ObjectNode column = columns.putObject(item.getKey()).put("dtype", item.getValue().type.dtype);
            column.set("values", columnJson(item.getValue()));
        }
        ObjectNode declarations = Glb.MAPPER.createObjectNode();
        for (Map.Entry<String, Variable> item : table.variables.entrySet()) {
            Variable variable = item.getValue();
            ObjectNode declared = declarations.putObject(item.getKey()).put("unit", variable.unit).put("role", variable.role);
            if (variable.standardName != null) declared.put("standard_name", variable.standardName);
            if (variable.kind != null) declared.put("kind", variable.kind);
            if (variable.description != null) declared.put("description", variable.description);
            if (variable.minimum != null) declared.put("minimum", variable.minimum);
            if (variable.maximum != null) declared.put("maximum", variable.maximum);
            if (!variable.references.isEmpty()) variable.references.forEach(declared.putArray("references")::add);
            if (!variable.doi.isEmpty()) variable.doi.forEach(declared.putArray("doi")::add);
        }
        if (!declarations.isEmpty()) entry.set("variables", declarations);
        return entry;
    }

    private static ArrayNode numbers(double[] values) {
        ArrayNode array = Glb.MAPPER.createArrayNode();
        for (double value : values) array.add(value);
        return array;
    }

    /** A frame as plain JSON values: NaN as null, ±∞ as "Infinity" / "-Infinity", positions as their float values. */
    public static ObjectNode frameToJson(Frame frame) {
        ObjectNode dump = Glb.MAPPER.createObjectNode().put("time", frame.time).put("time_unit", frame.timeUnit).put("step", frame.step);
        ArrayNode dataStructures = dump.putArray("data_structures");
        for (DataStructure dataStructure : frame.dataStructures) {
            ObjectNode entry = dataStructures.addObject().put("id", dataStructure.id).put("kind", dataStructure.kind);
            ArrayNode origin = entry.putArray("origin");
            for (int row = 0; row < 4; row++) {
                ArrayNode values = origin.addArray();
                for (int column = 0; column < 4; column++) values.add(dataStructure.origin[row * 4 + column]);
            }
            ArrayNode sets = entry.putArray("entity_sets");
            for (EntitySet set : dataStructure.entitySets) {
                ObjectNode item = tableJson(set);
                if (set.rank == null) item.putNull("rank"); else item.put("rank", set.rank);
                sets.add(item);
            }
            if (dataStructure.platform != null) entry.put("platform", dataStructure.platform);
            if (dataStructure.model != null) entry.put("model", dataStructure.model);
            if (!dataStructure.extras.isEmpty()) entry.set("extras", dataStructure.extras);
            if (!dataStructure.relations.isEmpty()) {
                ArrayNode relations = entry.putArray("relations");
                for (Relation relation : dataStructure.relations)
                    relations.add(tableJson(relation).put("source_set", relation.sourceSet).put("target_set", relation.targetSet));
            }
            if (dataStructure.scalars != null) entry.set("scalars", tableJson(dataStructure.scalars));
            if (dataStructure.grid != null) {
                Grid grid = dataStructure.grid;
                ObjectNode item = entry.putObject("grid").put("kind", grid.kind);
                ArrayNode shape = item.putArray("shape");
                for (long size : grid.shape) shape.add(size);
                item.set("origin", numbers(grid.origin));
                item.set("spacing", numbers(grid.spacing));
                grid.axes.forEach(item.putArray("axes")::add);
                ArrayNode periodic = item.putArray("periodic");
                for (boolean value : grid.periodic) periodic.add(value);
                item.put("z_up", grid.zUp).put("max_level", grid.maxLevel).put("cells", grid.cells);
            }
            if (!dataStructure.meshes.isEmpty()) {
                ArrayNode meshes = entry.putArray("meshes");
                for (Mesh mesh : dataStructure.meshes) {
                    ObjectNode item = meshes.addObject().put("name", mesh.name);
                    ArrayNode positions = item.putArray("positions_float32");
                    for (int vertex = 0; vertex < mesh.vertexCount(); vertex++) {
                        ArrayNode position = positions.addArray();
                        for (int axis = 0; axis < 3; axis++) position.add((double) (float) mesh.positions[vertex * 3 + axis]);
                    }
                    ObjectNode featureRows = item.putObject("feature_rows");
                    for (Map.Entry<String, long[]> rows : mesh.featureRows.entrySet()) {
                        ArrayNode values = featureRows.putArray(rows.getKey());
                        for (long row : rows.getValue()) values.add(row);
                    }
                    if (mesh.indices != null) {
                        ArrayNode indices = item.putArray("indices");
                        for (long index : mesh.indices) indices.add(index);
                    }
                    if (!mesh.display.isEmpty()) {
                        ObjectNode display = item.putObject("display");
                        for (Map.Entry<String, float[]> values : mesh.display.entrySet())
                            display.set(values.getKey(), columnJson(new Column(ComponentType.FLOAT32, values.getValue())));
                    }
                }
            }
        }
        ArrayNode mappings = dump.putArray("mappings");
        for (Mapping mapping : frame.mappings) {
            ObjectNode item = tableJson(mapping);
            item.putArray("source").add(mapping.sourceDataStructure).add(mapping.sourceSet);
            item.putArray("target").add(mapping.targetDataStructure).add(mapping.targetSet);
            if (mapping.method == null) item.putNull("method"); else item.put("method", mapping.method);
            mappings.add(item);
        }
        return dump;
    }

    /**
     * The differences between two JSON values, as {@code fspm-tf compare} finds them: objects by key, arrays in order,
     * numbers exactly (1 and 1.0 equal), as "path: what differs" lines (none when equal).
     */
    public static List<String> compare(JsonNode actual, JsonNode expected, String path) {
        List<String> found = new ArrayList<>();
        if (expected.isObject()) {
            if (!actual.isObject()) return List.of(path + ": an object expected");
            for (Iterator<String> names = expected.fieldNames(); names.hasNext(); ) {
                String name = names.next();
                if (!actual.has(name)) found.add(path + ": missing key '" + name + "'");
                else found.addAll(compare(actual.get(name), expected.get(name), path + "." + name));
            }
            for (Iterator<String> names = actual.fieldNames(); names.hasNext(); ) {
                String name = names.next();
                if (!expected.has(name)) found.add(path + ": unexpected key '" + name + "'");
            }
            return found;
        }
        if (expected.isArray()) {
            if (!actual.isArray()) return List.of(path + ": an array expected");
            if (actual.size() != expected.size())
                return List.of(path + ": " + actual.size() + " items, " + expected.size() + " expected");
            for (int index = 0; index < expected.size(); index++)
                found.addAll(compare(actual.get(index), expected.get(index), path + "[" + index + "]"));
            return found;
        }
        if (expected.isNumber()) {
            if (actual.isNumber() && actual.asDouble() == expected.asDouble()) return found;
            return List.of(path + ": " + actual + ", " + expected + " expected");
        }
        if (!actual.equals(expected)) return List.of(path + ": " + actual + ", " + expected + " expected");
        return found;
    }

    public static List<String> compare(JsonNode actual, JsonNode expected) {
        return compare(actual, expected, "$");
    }
}
