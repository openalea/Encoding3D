package org.openalea.encoding3d;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.function.Function;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Reading and writing frames as GLB files. Tables are EXT_structural_metadata property tables (one class per table),
 * meshes carry EXT_mesh_features feature IDs, and the FSPM_scene root extension holds what these two cannot: data
 * structures, entity sets and their ranks, relations, grids, mappings, the frame's time, and the variables' units,
 * standard names, kinds and roles.
 */
public final class Codec {
    /** The version of the specification this library reads and writes. */
    public static final String SPECIFICATION_VERSION = "0.4";
    public static final List<String> EDGE_TYPES = List.of("none", "successor", "branch", "unknown");

    private static final String EXTENSION = "FSPM_scene", METADATA = "EXT_structural_metadata",
            FEATURES = "EXT_mesh_features", EDGE_TYPE_ENUM = "FSPM_edge_type";
    private static final List<String> ENUM_COLUMNS = List.of("label", "edge_type", "relation");
    private static final List<String> ID_COLUMNS = List.of("id", "complex", "parent", "source", "target", "level", "index",
            "sibling_order");
    private static final int BOOLEAN_NO_DATA = 255;   // a boolean column with missing values: UINT8 0, 1, and 255 missing
    private static final int ARRAY_BUFFER = 34962, ELEMENT_ARRAY_BUFFER = 34963;
    private static final int FLOAT = 5126, UNSIGNED_INT = 5125, UNSIGNED_SHORT = 5123, UNSIGNED_BYTE = 5121;
    private static final long MAX_FLOAT_FEATURE = 1L << 24;    // feature rows are float vertex attributes
    private static final Pattern IDENTIFIER = Pattern.compile("^[a-zA-Z_][a-zA-Z0-9_]*$");
    // The scene's frame is z up (metres); glTF viewers expect y up: the root node turns the scene for them (-90° about
    // x, column-major). Readers of the tables use the scene's frame, not this node.
    private static final double[] Z_UP_TO_Y_UP = {1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1};

    private Codec() {}

    // ── Writing ──────────────────────────────────────────────────────────

    /** The GLB file of a frame; its instance sets' parts referred to by key only ({@link #write} writes them to parts/). */
    public static byte[] toBytes(Frame frame) {
        return encodeFrame(frame, false, null);
    }

    /**
     * The GLB file of a frame; {@code embedParts}: the parts its instance sets use in it (one self-contained file), else
     * referred to by key only.
     */
    public static byte[] toBytes(Frame frame, boolean embedParts) {
        return encodeFrame(frame, embedParts, null);
    }

    /** The GLB file of a frame; {@code partEntry}, when not null: the frame is a part's file, its FSPM_scene.part that. */
    static byte[] encodeFrame(Frame frame, boolean embedParts, Function<Glb.BufferBuilder, ObjectNode> partEntry) {
        Glb.BufferBuilder buffers = new Glb.BufferBuilder();
        ObjectNode schema = Glb.MAPPER.createObjectNode().put("id", "fspm_scene");
        schema.putObject("classes");
        ObjectNode edgeEnum = schema.putObject("enums").putObject(EDGE_TYPE_ENUM).put("valueType", "UINT8");
        ArrayNode edgeValues = edgeEnum.putArray("values");
        for (int value = 0; value < EDGE_TYPES.size(); value++)
            edgeValues.addObject().put("name", EDGE_TYPES.get(value)).put("value", value);
        ArrayNode tables = Glb.MAPPER.createArrayNode();
        ObjectNode variables = Glb.MAPPER.createObjectNode();
        ObjectNode document = Glb.MAPPER.createObjectNode();
        document.putObject("asset").put("version", "2.0").put("generator", "encoding3d (Java) " + SPECIFICATION_VERSION);
        document.put("scene", 0);
        document.putArray("scenes").addObject().putArray("nodes").add(0);
        ArrayNode nodes = document.putArray("nodes");
        ObjectNode sceneNode = nodes.addObject().put("name", "fspm_scene");
        putNumbers(sceneNode.putArray("matrix"), Z_UP_TO_Y_UP);
        sceneNode.putArray("children");
        ArrayNode accessors = Glb.MAPPER.createArrayNode(), meshes = Glb.MAPPER.createArrayNode();

        ArrayNode dataStructures = Glb.MAPPER.createArrayNode();
        for (DataStructure dataStructure : frame.dataStructures) {
            checkIdentifier(dataStructure.id, "data structure id");
            ObjectNode entry = dataStructures.addObject().put("id", dataStructure.id).put("kind", dataStructure.kind);
            if (dataStructure.platform != null) entry.put("platform", dataStructure.platform);
            if (dataStructure.model != null) entry.put("model", dataStructure.model);
            double[] columnMajor = columnMajor(dataStructure.origin);
            putNumbers(entry.putArray("origin"), columnMajor);       // column-major, as glTF matrices
            ArrayNode sets = entry.putArray("entitySets");
            for (EntitySet set : dataStructure.entitySets) {
                ObjectNode item = sets.addObject().put("name", set.name);
                if (set.rank == null) item.putNull("rank"); else item.put("rank", set.rank);
                if (set.scale != null) item.put("scale", set.scale);
                item.put("propertyTable", addTable(set, dataStructure.id + "__" + set.name, buffers, schema, tables, variables));
            }
            if (!dataStructure.relations.isEmpty()) {
                ArrayNode relations = entry.putArray("relations");
                for (Relation relation : dataStructure.relations)
                    relations.addObject().put("name", relation.name).put("sourceSet", relation.sourceSet)
                            .put("targetSet", relation.targetSet).put("propertyTable",
                                    addTable(relation, dataStructure.id + "__" + relation.name, buffers, schema, tables, variables));
            }
            if (dataStructure.scalars != null)
                entry.put("scalars", addTable(dataStructure.scalars, dataStructure.id + "__scalars", buffers, schema, tables, variables));
            if (dataStructure.grid != null) entry.set("grid", gridJson(dataStructure.grid));
            if (!dataStructure.labels.isEmpty()) {
                ObjectNode labels = entry.putObject("labels");
                dataStructure.labels.forEach(labels::put);
            }
            if (!dataStructure.extras.isEmpty()) entry.set("extras", dataStructure.extras);
            ObjectNode node = nodes.addObject().put("name", dataStructure.id);
            if (!isIdentity(dataStructure.origin)) putNumbers(node.putArray("matrix"), columnMajor);
            int nodeIndex = nodes.size() - 1;
            ((ArrayNode) sceneNode.get("children")).add(nodeIndex);
            entry.put("node", nodeIndex);
            if (!dataStructure.meshes.isEmpty()) {
                ArrayNode children = node.putArray("children");
                ArrayNode meshEntries = entry.putArray("meshes");
                for (Mesh mesh : dataStructure.meshes) {
                    meshes.add(encodeMesh(mesh, dataStructure, entry, buffers, accessors));
                    nodes.addObject().put("name", mesh.name).put("mesh", meshes.size() - 1);
                    children.add(nodes.size() - 1);
                    ObjectNode meshEntry = meshEntries.addObject().put("name", mesh.name).put("mesh", meshes.size() - 1);
                    if (!mesh.display.isEmpty()) {
                        ArrayNode display = meshEntry.putArray("display");
                        for (String variable : mesh.display.keySet()) {
                            ObjectNode item = display.addObject().put("attribute", displayAttribute(variable))
                                    .put("variable", variable);
                            String source = mesh.displaySources.get(variable);
                            if (source == null) item.putNull("entitySet"); else item.put("entitySet", source);
                        }
                    }
                }
            }
            if (!dataStructure.instanceSets.isEmpty()) {
                ArrayNode instanceSets = entry.putArray("instanceSets");
                for (InstanceSet instanceSet : dataStructure.instanceSets)
                    instanceSets.add(encodeInstanceSet(instanceSet, dataStructure, buffers, schema, tables, variables));
            }
        }

        ArrayNode mappings = Glb.MAPPER.createArrayNode();
        for (Mapping mapping : frame.mappings) {
            checkIdentifier(mapping.name, "mapping name");
            ObjectNode entry = mappings.addObject().put("name", mapping.name);
            entry.putObject("source").put("dataStructure", mapping.sourceDataStructure).put("entitySet", mapping.sourceSet);
            entry.putObject("target").put("dataStructure", mapping.targetDataStructure).put("entitySet", mapping.targetSet);
            if (mapping.method != null) entry.put("method", mapping.method);
            entry.put("propertyTable", addTable(mapping, "mapping__" + mapping.name, buffers, schema, tables, variables));
        }

        ObjectNode update = null;
        if (frame.update != null) {
            checkIdentifier(frame.update.participant, "participant");
            update = Glb.MAPPER.createObjectNode().put("participant", frame.update.participant);
            if (!frame.update.removed.isEmpty()) {
                ArrayNode removed = update.putArray("removed");
                for (Map.Entry<String, long[]> item : frame.update.removed.entrySet()) {
                    String[] key = item.getKey().split("/", 2);
                    Table table = new Table(key[1] + "__removed");
                    table.set("id", Column.of(item.getValue()));
                    removed.addObject().put("dataStructure", key[0]).put("entitySet", key[1]).put("propertyTable",
                            addTable(table, key[0] + "__" + key[1] + "__removed", buffers, schema, tables, variables));
                }
            }
        }
        ObjectNode scene = Glb.MAPPER.createObjectNode().put("version", SPECIFICATION_VERSION);
        scene.putObject("frame").put("time", frame.time).put("timeUnit", frame.timeUnit).put("step", frame.step);
        if (frame.vocabularyVersion != null) scene.put("vocabulary", frame.vocabularyVersion);
        if (!frame.writer.isEmpty()) scene.set("writer", frame.writer);
        if (update != null) scene.set("update", update);
        if (partEntry != null) scene.set("part", partEntry.apply(buffers));
        scene.set("dataStructures", dataStructures);
        if (!mappings.isEmpty()) scene.set("mappings", mappings);
        if (!variables.isEmpty()) scene.set("variables", variables);
        List<String> keys = Parts.keys(frame);
        if (embedParts && !keys.isEmpty()) {
            ObjectNode embedded = scene.putObject("parts");
            for (String key : keys) embedded.putObject(key).put("bufferView", buffers.add(Parts.bytes(frame, key)));
        }

        ObjectNode extensions = Glb.MAPPER.createObjectNode();
        ObjectNode metadata = extensions.putObject(METADATA);
        metadata.set("schema", schema);
        metadata.set("propertyTables", tables);
        extensions.set(EXTENSION, scene);
        ArrayNode used = document.putArray("extensionsUsed").add(METADATA).add(EXTENSION);
        if (!meshes.isEmpty()) used.add(FEATURES);
        JsonNode others = frame.unknown.get("extensions");
        if (others != null)
            for (Iterator<Map.Entry<String, JsonNode>> items = others.fields(); items.hasNext(); ) {
                Map.Entry<String, JsonNode> item = items.next();
                extensions.set(item.getKey(), item.getValue());
                used.add(item.getKey());
            }
        document.set("extensions", extensions);
        if (frame.unknown.has("extras")) document.set("extras", frame.unknown.get("extras"));
        if (!meshes.isEmpty()) {
            document.set("meshes", meshes);
            document.set("accessors", accessors);
        }
        byte[] binary = buffers.data.toByteArray();
        if (!buffers.views.isEmpty()) {
            // the buffer holds the chunk's padding to 8 bytes: glTF-Validator warns of more than 3 bytes beyond it
            binary = java.util.Arrays.copyOf(binary, binary.length + Glb.padding(binary.length));
            document.putArray("buffers").addObject().put("byteLength", binary.length);
            document.set("bufferViews", buffers.views);
        }
        return Glb.pack(document, binary);
    }

    /**
     * Writes a frame to the GLB file {@code path}, and each part its instance sets use to parts/&lt;key&gt;.glb next to
     * it, when not there yet; the keys of those parts, sorted.
     */
    public static List<String> write(Path path, Frame frame) throws IOException {
        return write(path, frame, false);
    }

    /** As {@link #write(Path, Frame)}; {@code embedParts}: the parts in the frame instead (one self-contained file). */
    public static List<String> write(Path path, Frame frame, boolean embedParts) throws IOException {
        Files.write(path, toBytes(frame, embedParts));
        List<String> keys = Parts.keys(frame);
        if (embedParts) return keys;
        Path folder = path.toAbsolutePath().getParent().resolve(Parts.FOLDER);
        for (String key : keys) {
            Path target = folder.resolve(key + ".glb");
            if (Files.exists(target)) continue;                  // its name is its hash: its content
            Files.createDirectories(folder);
            Path temporary = folder.resolve(key + ".glb.part");
            Files.write(temporary, Parts.bytes(frame, key));
            Files.move(temporary, target, java.nio.file.StandardCopyOption.REPLACE_EXISTING);   // never half a part
        }
        return keys;
    }

    /**
     * The FSPM_scene entry of an instance set (specification §12.2), its tables added: the instance table (its columns,
     * each vector's &lt;name&gt;__count, each derived field's &lt;name&gt;__operator and &lt;name&gt;__weight) and one
     * table per vector (its values, the instances' one after the other).
     */
    private static ObjectNode encodeInstanceSet(InstanceSet instanceSet, DataStructure dataStructure, Glb.BufferBuilder buffers,
                                                ObjectNode schema, ArrayNode tables, ObjectNode variables) {
        checkIdentifier(instanceSet.name, "instance set name");
        String where = "instance set '" + instanceSet.name + "' of '" + dataStructure.id + "'";
        if (!instanceSet.has("template"))
            throw new Encoding3dException(where + ": no 'template' column (each instance's index in its parts)");
        int count = instanceSet.count();
        InstanceSet table = new InstanceSet(instanceSet.name);    // its columns, and those of its vectors and fields
        instanceSet.columns.forEach(table::set);
        table.variables.putAll(instanceSet.variables);
        ObjectNode entry = Glb.MAPPER.createObjectNode().put("name", instanceSet.name);
        instanceSet.parts.forEach(entry.putArray("parts")::add);
        if (instanceSet.owners != null) entry.put("owners", instanceSet.owners);
        ArrayNode vectors = Glb.MAPPER.createArrayNode();
        for (Map.Entry<String, Ragged> item : instanceSet.vectors.entrySet()) {
            String name = item.getKey();
            Ragged ragged = item.getValue();
            checkIdentifier(name, "vector of " + where);
            ragged.offsets();                                   // its counts checked against its values
            if (ragged.size() != count)
                throw new Encoding3dException(where + ": vector '" + name + "' has " + ragged.size() + " instances, the set " + count);
            table.set(name + "__count", Column.of(ragged.counts));
            Table values = new Table(name).set("values", Column.of(ragged.values));
            vectors.addObject().put("name", name).put("propertyTable",
                    addTable(values, dataStructure.id + "__" + instanceSet.name + "__" + name, buffers, schema, tables, variables));
        }
        ArrayNode derivedFields = Glb.MAPPER.createArrayNode();
        for (DerivedField derived : instanceSet.derived) {
            checkIdentifier(derived.name, "derived field of " + where);
            if (derived.terms < 1 || derived.operators.length != count * derived.terms || derived.weights.length != count * derived.terms)
                throw new Encoding3dException(where + ": derived field '" + derived.name + "' has not " + derived.terms
                        + " operators and weights per instance");
            if (!instanceSet.vectors.containsKey(derived.input))
                throw new Encoding3dException(where + ": derived field '" + derived.name + "' applies to vector '" + derived.input
                        + "', which the set does not have");
            if (derived.offsets.length != derived.terms)
                throw new Encoding3dException(where + ": derived field '" + derived.name + "' has not one offset per term");
            table.set(derived.name + "__operator", new Column(ComponentType.INT64, derived.operators, derived.terms));
            table.set(derived.name + "__weight", new Column(ComponentType.FLOAT64, derived.weights, derived.terms));
            ObjectNode item = derivedFields.addObject().put("name", derived.name).put("entitySet", derived.entitySet)
                    .put("input", derived.input).put("terms", derived.terms);
            item.set("variable", declarationJson(derived.variable));
            boolean anyOffset = false;
            for (String offset : derived.offsets) anyOffset |= offset != null;
            if (anyOffset) {
                ArrayNode offsets = item.putArray("offsets");
                for (String offset : derived.offsets) if (offset == null) offsets.addNull(); else offsets.add(offset);
            }
            if (derived.variable.description != null) item.put("description", derived.variable.description);
        }
        entry.put("propertyTable", addTable(table, dataStructure.id + "__" + instanceSet.name, buffers, schema, tables, variables));
        if (!vectors.isEmpty()) entry.set("vectors", vectors);
        if (!derivedFields.isEmpty()) entry.set("derivedFields", derivedFields);
        return entry;
    }

    static void checkIdentifier(String name, String what) {
        if (name == null || !IDENTIFIER.matcher(name).matches())
            throw new Encoding3dException(what + " '" + name + "' must be an identifier (letters, digits, '_'; not starting with a digit)");
    }

    private static void putNumbers(ArrayNode array, double[] values) {
        for (double value : values) array.add(value);
    }

    private static double[] columnMajor(double[] rowMajor) {
        double[] values = new double[16];
        for (int row = 0; row < 4; row++)
            for (int column = 0; column < 4; column++) values[column * 4 + row] = rowMajor[row * 4 + column];
        return values;
    }

    private static boolean isIdentity(double[] origin) {
        for (int row = 0; row < 4; row++)
            for (int column = 0; column < 4; column++)
                if (origin[row * 4 + column] != (row == column ? 1.0 : 0.0)) return false;
        return true;
    }

    private static ObjectNode declarationJson(Variable variable) {
        ObjectNode declaration = Glb.MAPPER.createObjectNode().put("unit", variable.unit).put("role", variable.role);
        if (variable.standardName != null) declaration.put("standardName", variable.standardName);
        if (variable.kind != null) declaration.put("kind", variable.kind);
        if (variable.minimum != null) declaration.put("minimum", variable.minimum);
        if (variable.maximum != null) declaration.put("maximum", variable.maximum);
        if (!variable.references.isEmpty()) variable.references.forEach(declaration.putArray("references")::add);
        if (!variable.doi.isEmpty()) variable.doi.forEach(declaration.putArray("doi")::add);
        if (variable.format != null) declaration.put("format", variable.format);
        return declaration;
    }

    private static int addTable(Table table, String classId, Glb.BufferBuilder buffers, ObjectNode schema, ArrayNode tables,
                                ObjectNode variables) {
        checkIdentifier(classId, "class");
        table.checkLengths();
        ObjectNode properties = Glb.MAPPER.createObjectNode(), stored = Glb.MAPPER.createObjectNode();
        for (Map.Entry<String, Column> item : table.columns.entrySet())
            encodeColumn(table, classId, item.getKey(), item.getValue(), buffers, schema, properties, stored);
        ((ObjectNode) schema.get("classes")).putObject(classId).put("name", table.name).set("properties", properties);
        ObjectNode description = tables.addObject().put("name", table.name).put("class", classId).put("count", table.rowCount());
        description.set("properties", stored);
        ObjectNode declared = Glb.MAPPER.createObjectNode();
        for (String name : table.variableNames())
            if (table.variables.containsKey(name)) declared.set(name, declarationJson(table.variables.get(name)));
        if (!declared.isEmpty()) variables.set(classId, declared);
        return tables.size() - 1;
    }

    private static void encodeColumn(Table table, String classId, String name, Column column, Glb.BufferBuilder buffers,
                                     ObjectNode schema, ObjectNode properties, ObjectNode stored) {
        checkIdentifier(name, "column of '" + table.name + "'");
        String where = "column '" + name + "' of '" + table.name + "'";
        ObjectNode property = properties.putObject(name);
        Variable declared = table.variables.get(name);
        if (declared != null && declared.description != null) property.put("description", declared.description);
        boolean reserved = table.isReserved(name);
        if (reserved && ENUM_COLUMNS.contains(name)) {
            if (column.type != ComponentType.STRING) throw new Encoding3dException(where + ": labels are text");
            property.put("type", "ENUM");
            property.put("enumType", encodeEnum(name, column.strings(), classId, schema, buffers, stored));
        } else if (column.type == ComponentType.STRING) {
            if (column.width != 1) throw new Encoding3dException(where + ": text vectors are not supported");
            property.put("type", "STRING");
            String[] values = column.strings();
            if (column.hasMissing()) {                           // missing text: noData, a string the column lacks
                String noData = freeString(column);
                property.put("noData", noData);
                values = values.clone();
                for (int row = 0; row < values.length; row++) if (column.missing[row]) values[row] = noData;
            }
            byte[][] encoded = new byte[values.length][];
            long[] offsets = new long[values.length + 1];
            for (int row = 0; row < values.length; row++) {
                encoded[row] = values[row].getBytes(StandardCharsets.UTF_8);
                offsets[row + 1] = offsets[row] + encoded[row].length;
            }
            ByteBuffer text = ByteBuffer.allocate((int) offsets[values.length]);
            for (byte[] value : encoded) text.put(value);
            ObjectNode item = stored.putObject(name).put("values", buffers.add(text.array()));
            boolean narrow = offsets[values.length] < (1L << 32);
            ByteBuffer offsetBytes = little(offsets.length * (narrow ? 4 : 8));
            for (long offset : offsets) if (narrow) offsetBytes.putInt((int) offset); else offsetBytes.putLong(offset);
            item.put("stringOffsets", buffers.add(offsetBytes.array())).put("stringOffsetType", narrow ? "UINT32" : "UINT64");
        } else if (column.type == ComponentType.BOOLEAN && column.hasMissing()) {   // UINT8 0, 1, 255 missing
            property.put("type", "SCALAR").put("componentType", "UINT8").put("noData", BOOLEAN_NO_DATA);
            property.putObject("extras").put("FSPM_boolean", true);
            boolean[] values = column.booleans();
            byte[] codes = new byte[values.length];
            for (int row = 0; row < values.length; row++)
                codes[row] = column.missing[row] ? (byte) BOOLEAN_NO_DATA : (byte) (values[row] ? 1 : 0);
            stored.putObject(name).put("values", buffers.add(codes));
        } else if (column.type == ComponentType.BOOLEAN) {
            if (column.width != 1) throw new Encoding3dException(where + ": boolean vectors are not supported");
            property.put("type", "BOOLEAN");
            boolean[] values = column.booleans();
            byte[] packed = new byte[(values.length + 7) / 8];
            for (int row = 0; row < values.length; row++)
                if (values[row]) packed[row / 8] |= (byte) (1 << (row % 8));          // bit order: little
            stored.putObject(name).put("values", buffers.add(packed));
        } else {
            ComponentType type = column.type;
            Column data = column;
            if (reserved && (ID_COLUMNS.contains(name) || table.kind() == Table.Kind.INSTANCE_SET) && !type.isFloat()
                    && type != ComponentType.INT64) {
                long[] ids = new long[column.size()];                       // ids are INT64, whatever the platform's
                for (int index = 0; index < ids.length; index++) ids[index] = (long) column.doubleAt(index);
                data = new Column(ComponentType.INT64, ids, column.width);
                type = ComponentType.INT64;
            }
            property.put("type", "SCALAR").put("componentType", type.name());
            if (column.width != 1) {
                if (column.width < 2) throw new Encoding3dException(where + ": vectors have at least 2 components");
                property.put("array", true).put("count", column.width);
            }
            if (type == ComponentType.FLOAT64) {
                double[] values = data.doubles().clone();
                for (int row = 0; column.missing != null && row < values.length; row++)    // a missing float: NaN
                    if (column.missing[row]) values[row] = Double.NaN;
                data = standIns(values, property, where);
            } else if (type == ComponentType.FLOAT32) {
                float[] values = data.floats().clone();
                for (int row = 0; column.missing != null && row < values.length; row++)
                    if (column.missing[row]) values[row] = Float.NaN;
                data = standIns(values, property, where);
            } else if (reserved && (name.equals("complex") || name.equals("parent"))) {
                property.put("noData", EntitySet.NO_ID);
            } else if (column.hasMissing()) {                // missing integers: noData, a value the column lacks
                long noData = freeInteger(column);
                property.put("noData", noData);
                data = withValueAt(column, noData);
            }
            if (data.width != column.width) data = new Column(data.type, data.values, column.width);
            stored.putObject(name).put("values", buffers.add(bytesOf(data)));
        }
        if (name.equals("id") && table.kind() == Table.Kind.ENTITY_SET) property.put("required", true);
    }

    /** A value of the column's integer type that it does not hold: its minimum (signed) or maximum (unsigned) first. */
    private static long freeInteger(Column column) {
        java.util.Set<Long> present = new java.util.HashSet<>();
        for (int row = 0; row < column.size(); row++)
            if (!column.isMissing(row)) present.add(rawLong(column, row));
        long minimum, maximum;
        switch (column.type) {
            case INT8 -> { minimum = Byte.MIN_VALUE; maximum = Byte.MAX_VALUE; }
            case INT16 -> { minimum = Short.MIN_VALUE; maximum = Short.MAX_VALUE; }
            case INT32 -> { minimum = Integer.MIN_VALUE; maximum = Integer.MAX_VALUE; }
            case INT64 -> { minimum = Long.MIN_VALUE; maximum = Long.MAX_VALUE; }
            case UINT8 -> { minimum = 0; maximum = 0xFFL; }
            case UINT16 -> { minimum = 0; maximum = 0xFFFFL; }
            case UINT32 -> { minimum = 0; maximum = 0xFFFFFFFFL; }
            default -> { minimum = 0; maximum = -1; }                       // UINT64: its maximum's bits
        }
        boolean signed = !column.type.isUnsigned();
        long first = signed ? minimum : maximum, second = signed ? maximum : minimum;
        if (!present.contains(first)) return first;
        if (!present.contains(second)) return second;
        long candidate = first;
        while (present.contains(candidate)) candidate = signed ? candidate + 1 : candidate - 1;
        return candidate;
    }

    /** A value's bits as a long, unsigned values as stored (UINT8 255 as 255). */
    private static long rawLong(Column column, int index) {
        return switch (column.type) {
            case INT8 -> ((byte[]) column.values)[index];
            case UINT8 -> Byte.toUnsignedLong(((byte[]) column.values)[index]);
            case INT16 -> ((short[]) column.values)[index];
            case UINT16 -> Short.toUnsignedLong(((short[]) column.values)[index]);
            case INT32 -> ((int[]) column.values)[index];
            case UINT32 -> Integer.toUnsignedLong(((int[]) column.values)[index]);
            case INT64, UINT64 -> ((long[]) column.values)[index];
            default -> throw new Encoding3dException("a " + column.type + " column has no integers");
        };
    }

    /** The column's values with {@code value} at its missing rows. */
    private static Column withValueAt(Column column, long value) {
        Object copy = java.lang.reflect.Array.newInstance(column.values.getClass().getComponentType(), column.size());
        System.arraycopy(column.values, 0, copy, 0, column.size());
        for (int row = 0; row < column.size(); row++)
            if (column.isMissing(row))
                switch (column.type) {
                    case INT8, UINT8 -> ((byte[]) copy)[row] = (byte) value;
                    case INT16, UINT16 -> ((short[]) copy)[row] = (short) value;
                    case INT32, UINT32 -> ((int[]) copy)[row] = (int) value;
                    default -> ((long[]) copy)[row] = value;
                }
        return new Column(column.type, copy, column.width);
    }

    /** A string the column does not hold: the empty string first, then NUL characters. */
    private static String freeString(Column column) {
        java.util.Set<String> present = new java.util.HashSet<>();
        for (int row = 0; row < column.size(); row++) if (!column.isMissing(row)) present.add(column.strings()[row]);
        String candidate = "";
        while (present.contains(candidate)) candidate += "\0";
        return candidate;
    }

    // EXT_structural_metadata forbids NaN and infinities: NaN is written as noData, the most negative finite value;
    // +inf and -inf as the largest finite value and the next one after the most negative, declared in the property's
    // extras (FSPM_infinity).
    private static Column standIns(double[] values, ObjectNode property, String where) {
        double positive = Double.MAX_VALUE, negative = Math.nextUp(-Double.MAX_VALUE), noData = -Double.MAX_VALUE;
        boolean infinite = false, nan = false;
        for (double value : values) {
            infinite |= Double.isInfinite(value);
            nan |= Double.isNaN(value);
        }
        if (infinite) {
            for (double value : values)
                if (value == positive || value == negative)
                    throw new Encoding3dException(where + " holds both infinities and the values standing for them");
            property.putObject("extras").putObject("FSPM_infinity").put("positive", positive).put("negative", negative);
            for (int index = 0; index < values.length; index++)
                if (Double.isInfinite(values[index])) values[index] = values[index] > 0 ? positive : negative;
        }
        if (nan) {
            for (double value : values)
                if (value == noData) throw new Encoding3dException(where + " holds both NaN and the value standing for NaN");
            property.put("noData", noData);
            for (int index = 0; index < values.length; index++) if (Double.isNaN(values[index])) values[index] = noData;
        }
        return new Column(ComponentType.FLOAT64, values);
    }

    private static Column standIns(float[] values, ObjectNode property, String where) {
        float positive = Float.MAX_VALUE, negative = Math.nextUp(-Float.MAX_VALUE), noData = -Float.MAX_VALUE;
        boolean infinite = false, nan = false;
        for (float value : values) {
            infinite |= Float.isInfinite(value);
            nan |= Float.isNaN(value);
        }
        if (infinite) {
            for (float value : values)
                if (value == positive || value == negative)
                    throw new Encoding3dException(where + " holds both infinities and the values standing for them");
            property.putObject("extras").putObject("FSPM_infinity").put("positive", (double) positive)
                    .put("negative", (double) negative);
            for (int index = 0; index < values.length; index++)
                if (Float.isInfinite(values[index])) values[index] = values[index] > 0 ? positive : negative;
        }
        if (nan) {
            for (float value : values)
                if (value == noData) throw new Encoding3dException(where + " holds both NaN and the value standing for NaN");
            property.put("noData", (double) noData);
            for (int index = 0; index < values.length; index++) if (Float.isNaN(values[index])) values[index] = noData;
        }
        return new Column(ComponentType.FLOAT32, values);
    }

    private static String encodeEnum(String name, String[] values, String classId, ObjectNode schema,
                                     Glb.BufferBuilder buffers, ObjectNode stored) {
        if (name.equals("edge_type")) {
            byte[] codes = new byte[values.length];
            for (int row = 0; row < values.length; row++) {
                int code = EDGE_TYPES.indexOf(values[row]);
                if (code < 0)
                    throw new Encoding3dException("edge_type of '" + classId + "': unknown value '" + values[row]
                            + "' (allowed: none, successor, branch)");
                codes[row] = (byte) code;
            }
            stored.putObject(name).put("values", buffers.add(codes));
            return EDGE_TYPE_ENUM;
        }
        List<String> names = new ArrayList<>(new TreeSet<>(List.of(values)));
        String enumName = classId + "__" + name;
        boolean narrow = names.size() <= 256;
        ObjectNode enumeration = ((ObjectNode) schema.get("enums")).putObject(enumName).put("valueType", narrow ? "UINT8" : "UINT16");
        ArrayNode enumValues = enumeration.putArray("values");
        Map<String, Integer> codeOf = new HashMap<>();
        for (int code = 0; code < names.size(); code++) {
            enumValues.addObject().put("name", names.get(code)).put("value", code);
            codeOf.put(names.get(code), code);
        }
        ByteBuffer codes = little(values.length * (narrow ? 1 : 2));
        for (String value : values) if (narrow) codes.put((byte) (int) codeOf.get(value)); else codes.putShort((short) (int) codeOf.get(value));
        stored.putObject(name).put("values", buffers.add(codes.array()));
        return enumName;
    }

    private static ByteBuffer little(int size) {
        return ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN);
    }

    /** A numeric column's values, little-endian. */
    static byte[] bytesOf(Column column) {
        ByteBuffer bytes = little(column.size() * column.type.size);
        switch (column.type) {
            case INT8, UINT8 -> bytes.put((byte[]) column.values);
            case INT16, UINT16 -> { for (short value : (short[]) column.values) bytes.putShort(value); }
            case INT32, UINT32 -> { for (int value : (int[]) column.values) bytes.putInt(value); }
            case INT64, UINT64 -> { for (long value : (long[]) column.values) bytes.putLong(value); }
            case FLOAT32 -> { for (float value : (float[]) column.values) bytes.putFloat(value); }
            case FLOAT64 -> { for (double value : (double[]) column.values) bytes.putDouble(value); }
            default -> throw new Encoding3dException("a " + column.type + " column has no numbers");
        }
        return bytes.array();
    }

    private static ObjectNode gridJson(Grid grid) {
        ObjectNode entry = Glb.MAPPER.createObjectNode().put("kind", grid.kind);
        ArrayNode shape = entry.putArray("shape");
        for (long size : grid.shape) shape.add(size);
        putNumbers(entry.putArray("origin"), grid.origin);
        putNumbers(entry.putArray("spacing"), grid.spacing);
        grid.axes.forEach(entry.putArray("axes")::add);
        ArrayNode periodic = entry.putArray("periodic");
        for (boolean value : grid.periodic) periodic.add(value);
        entry.put("zUp", grid.zUp).put("cells", grid.cells);
        if (grid.kind.equals("adaptive")) entry.put("maxLevel", grid.maxLevel);
        return entry;
    }

    private static String displayAttribute(String name) {
        return "_" + name.toUpperCase(java.util.Locale.ROOT);
    }

    private static ObjectNode encodeMesh(Mesh mesh, DataStructure dataStructure, ObjectNode entry,
                                         Glb.BufferBuilder buffers, ArrayNode accessors) {
        int vertices = mesh.vertexCount();
        if (mesh.positions.length != vertices * 3) throw new Encoding3dException("mesh '" + mesh.name + "': 3 coordinates per vertex");
        float[] positions = new float[mesh.positions.length];
        for (int index = 0; index < positions.length; index++) positions[index] = (float) mesh.positions[index];
        ObjectNode attributes = Glb.MAPPER.createObjectNode();
        ObjectNode position = accessor(accessors, buffers, bytesOf(new Column(ComponentType.FLOAT32, positions)), "VEC3",
                FLOAT, ARRAY_BUFFER, vertices, attributes, "POSITION");
        if (vertices > 0) {
            double[] minimum = {Double.MAX_VALUE, Double.MAX_VALUE, Double.MAX_VALUE}, maximum = {-Double.MAX_VALUE, -Double.MAX_VALUE, -Double.MAX_VALUE};
            for (int vertex = 0; vertex < vertices; vertex++)
                for (int axis = 0; axis < 3; axis++) {
                    minimum[axis] = Math.min(minimum[axis], positions[vertex * 3 + axis]);
                    maximum[axis] = Math.max(maximum[axis], positions[vertex * 3 + axis]);
                }
            putNumbers(position.putArray("min"), minimum);
            putNumbers(position.putArray("max"), maximum);
        }
        Map<String, Integer> tables = new HashMap<>();
        for (JsonNode set : entry.get("entitySets")) tables.put(set.get("name").asText(), set.get("propertyTable").asInt());
        ArrayNode featureIds = Glb.MAPPER.createArrayNode();
        int setIndex = 0;
        for (Map.Entry<String, long[]> item : mesh.featureRows.entrySet()) {
            String setName = item.getKey();
            long[] rows = item.getValue();
            if (!tables.containsKey(setName))
                throw new Encoding3dException("mesh '" + mesh.name + "': no entity set '" + setName + "' in '" + dataStructure.id + "'");
            if (rows.length != vertices)
                throw new Encoding3dException("mesh '" + mesh.name + "': feature rows of '" + setName + "' are not one per vertex");
            long count = dataStructure.entitySet(setName).rowCount();
            if (count >= MAX_FLOAT_FEATURE)
                throw new Encoding3dException("mesh '" + mesh.name + "': too many entities in '" + setName + "', feature IDs stop at 2^24");
            float[] storedRows = new float[rows.length];
            TreeSet<Long> present = new TreeSet<>();
            boolean hasNull = false;
            for (int vertex = 0; vertex < rows.length; vertex++) {
                long row = rows[vertex];
                if (row < EntitySet.NO_ID || row >= count)
                    throw new Encoding3dException("mesh '" + mesh.name + "': feature rows of '" + setName + "' outside its rows");
                hasNull |= row == EntitySet.NO_ID;
                if (row != EntitySet.NO_ID) present.add(row);
                storedRows[vertex] = row == EntitySet.NO_ID ? count : row;          // null: one past the last row
            }
            accessor(accessors, buffers, bytesOf(new Column(ComponentType.FLOAT32, storedRows)), "SCALAR", FLOAT, ARRAY_BUFFER,
                    vertices, attributes, "_FEATURE_ID_" + setIndex);
            ObjectNode feature = featureIds.addObject().put("featureCount", present.size()).put("attribute", setIndex)
                    .put("propertyTable", tables.get(setName)).put("label", setName);
            if (hasNull) feature.put("nullFeatureId", count);
            setIndex++;
        }
        for (Map.Entry<String, float[]> item : mesh.display.entrySet()) {
            if (item.getValue().length != vertices)
                throw new Encoding3dException("mesh '" + mesh.name + "': display copy '" + item.getKey() + "' is not one value per vertex");
            accessor(accessors, buffers, bytesOf(new Column(ComponentType.FLOAT32, item.getValue())), "SCALAR", FLOAT,
                    ARRAY_BUFFER, vertices, attributes, displayAttribute(item.getKey()));
        }
        ObjectNode primitive = Glb.MAPPER.createObjectNode();
        primitive.set("attributes", attributes);
        primitive.put("mode", 4);
        if (mesh.indices != null) {
            int[] indices = new int[mesh.indices.length];
            for (int index = 0; index < indices.length; index++) indices[index] = (int) mesh.indices[index];
            ObjectNode holder = Glb.MAPPER.createObjectNode();
            accessor(accessors, buffers, bytesOf(new Column(ComponentType.UINT32, indices)), "SCALAR", UNSIGNED_INT,
                    ELEMENT_ARRAY_BUFFER, indices.length, holder, "indices");
            primitive.set("indices", holder.get("indices"));
        }
        if (!featureIds.isEmpty()) primitive.putObject("extensions").putObject(FEATURES).set("featureIds", featureIds);
        ObjectNode encoded = Glb.MAPPER.createObjectNode().put("name", mesh.name);
        encoded.putArray("primitives").add(primitive);
        return encoded;
    }

    private static ObjectNode accessor(ArrayNode accessors, Glb.BufferBuilder buffers, byte[] bytes, String type,
                                       int componentType, int target, int count, ObjectNode attributes, String attribute) {
        ObjectNode item = accessors.addObject().put("bufferView", buffers.add(bytes, target))
                .put("componentType", componentType).put("count", count).put("type", type);
        attributes.put(attribute, accessors.size() - 1);
        return item;
    }

    // ── Reading ──────────────────────────────────────────────────────────

    /** The frame of a GLB file's bytes. */
    public static Frame fromBytes(byte[] data) {
        return fromBytes(data, null);
    }

    /** The frame of a GLB file's bytes; {@code partsFolder}: the folder its parts/ are in (the file's folder). */
    public static Frame fromBytes(byte[] data, Path partsFolder) {
        Glb.Contents contents = Glb.unpack(data);
        JsonNode document = contents.document();
        byte[] binary = contents.binary();
        JsonNode extensions = document.path("extensions");
        if (!extensions.has(EXTENSION)) throw new Encoding3dException("not an encoding3d file: no " + EXTENSION + " extension");
        JsonNode scene = extensions.get(EXTENSION);
        JsonNode metadata = extensions.path(METADATA);
        JsonNode variables = scene.path("variables");

        Frame frame = new Frame();
        JsonNode frameEntry = scene.path("frame");
        frame.time = frameEntry.path("time").asDouble(0.0);
        frame.timeUnit = frameEntry.path("timeUnit").asText("d");
        frame.step = frameEntry.path("step").asLong(0);
        if (scene.get("writer") instanceof ObjectNode writer) frame.writer = writer;
        if (scene.hasNonNull("vocabulary")) frame.vocabularyVersion = scene.get("vocabulary").asText();
        for (JsonNode entry : scene.path("dataStructures")) {
            DataStructure dataStructure = new DataStructure(entry.get("id").asText(), entry.path("kind").asText("graph"));
            if (entry.hasNonNull("platform")) dataStructure.platform = entry.get("platform").asText();
            if (entry.hasNonNull("model")) dataStructure.model = entry.get("model").asText();
            if (entry.get("extras") instanceof ObjectNode extras) dataStructure.extras = extras;
            for (Iterator<Map.Entry<String, JsonNode>> labels = entry.path("labels").fields(); labels.hasNext(); ) {
                Map.Entry<String, JsonNode> label = labels.next();
                dataStructure.labels.put(label.getKey(), label.getValue().asText());
            }
            if (entry.has("origin")) {
                JsonNode origin = entry.get("origin");
                if (origin.size() != 16) throw new Encoding3dException("data structure '" + dataStructure.id + "': an origin of 16 numbers");
                for (int row = 0; row < 4; row++)
                    for (int column = 0; column < 4; column++)
                        dataStructure.origin[row * 4 + column] = origin.get(column * 4 + row).asDouble();
            }
            Map<Integer, String> tableNames = new HashMap<>();
            for (JsonNode item : entry.path("entitySets")) {
                EntitySet set = new EntitySet("", item.hasNonNull("rank") ? item.get("rank").asLong() : null);
                if (item.hasNonNull("scale")) set.scale = item.get("scale").asText();
                decodeTable(document, binary, metadata, variables, item.get("propertyTable").asInt(), set);
                tableNames.put(item.get("propertyTable").asInt(), item.get("name").asText());
                dataStructure.entitySets.add(set);
            }
            for (JsonNode item : entry.path("relations")) {
                Relation relation = new Relation("", item.get("sourceSet").asText(), item.get("targetSet").asText());
                decodeTable(document, binary, metadata, variables, item.get("propertyTable").asInt(), relation);
                dataStructure.relations.add(relation);
            }
            if (entry.has("scalars")) {
                Table scalars = new Table("");
                decodeTable(document, binary, metadata, variables, entry.get("scalars").asInt(), scalars);
                dataStructure.scalars = scalars;
            }
            if (entry.has("grid")) dataStructure.grid = decodeGrid(entry.get("grid"));
            for (JsonNode meshEntry : entry.path("meshes"))
                dataStructure.meshes.add(decodeMesh(document, binary, meshEntry, tableNames));
            for (JsonNode item : entry.path("instanceSets"))
                dataStructure.instanceSets.add(decodeInstanceSet(document, binary, metadata, variables, item));
            frame.dataStructures.add(dataStructure);
        }
        for (JsonNode entry : scene.path("mappings")) {
            Mapping mapping = new Mapping("", entry.get("source").get("dataStructure").asText(),
                    entry.get("source").get("entitySet").asText(), entry.get("target").get("dataStructure").asText(),
                    entry.get("target").get("entitySet").asText(), entry.hasNonNull("method") ? entry.get("method").asText() : null);
            decodeTable(document, binary, metadata, variables, entry.get("propertyTable").asInt(), mapping);
            frame.mappings.add(mapping);
        }
        if (scene.has("update")) {
            JsonNode entry = scene.get("update");
            frame.update = new Update(entry.get("participant").asText());
            for (JsonNode item : entry.path("removed")) {
                Table removed = new Table("");
                decodeTable(document, binary, metadata, variables, item.get("propertyTable").asInt(), removed);
                frame.update.removed.put(Update.key(item.get("dataStructure").asText(), item.get("entitySet").asText()),
                        removed.column("id").longs());
            }
        }
        ObjectNode others = Glb.MAPPER.createObjectNode();
        for (Iterator<Map.Entry<String, JsonNode>> items = extensions.fields(); items.hasNext(); ) {
            Map.Entry<String, JsonNode> item = items.next();
            if (!List.of(METADATA, EXTENSION, FEATURES).contains(item.getKey())) others.set(item.getKey(), item.getValue());
        }
        if (!others.isEmpty()) frame.unknown.set("extensions", others);
        if (document.has("extras")) frame.unknown.set("extras", document.get("extras"));
        for (Iterator<Map.Entry<String, JsonNode>> items = scene.path("parts").fields(); items.hasNext(); ) {
            Map.Entry<String, JsonNode> item = items.next();               // embedded parts: a self-contained frame
            ByteBuffer bytes = view(document, binary, item.getValue().get("bufferView").asInt());
            byte[] part = new byte[bytes.remaining()];
            bytes.get(part);
            frame.partBytes.put(item.getKey(), part);
        }
        frame.partsFolder = partsFolder;
        return frame;
    }

    /**
     * The frame of the GLB file {@code path}, in a folder or in an archive ("run.fspm.zip/frame_000003.glb"); its parts
     * are found next to it.
     */
    public static Frame read(Path path) throws IOException {
        Path folder = path.toAbsolutePath().getParent();
        return fromBytes(Archives.readBytes(path), folder);
    }

    /** An instance set (specification §12.2): its own columns, its vectors and derived fields; its parts by key. */
    private static InstanceSet decodeInstanceSet(JsonNode document, byte[] binary, JsonNode metadata, JsonNode variables,
                                                 JsonNode item) {
        InstanceSet instanceSet = new InstanceSet(item.get("name").asText(),
                item.hasNonNull("owners") ? item.get("owners").asText() : null);
        decodeTable(document, binary, metadata, variables, item.get("propertyTable").asInt(), instanceSet);
        instanceSet.name = item.get("name").asText();
        String where = "instance set '" + instanceSet.name + "'";
        for (JsonNode key : item.path("parts")) instanceSet.parts.add(key.asText());
        for (JsonNode vector : item.path("vectors")) {
            String name = vector.get("name").asText();
            Table values = new Table("");
            decodeTable(document, binary, metadata, variables, vector.get("propertyTable").asInt(), values);
            instanceSet.vectors.put(name, new Ragged(doublesOf(values.column("values")),
                    longsOf(takeColumn(instanceSet, name + "__count", where))));
        }
        for (JsonNode entry : item.path("derivedFields")) {
            String name = entry.get("name").asText();
            int terms = entry.path("terms").asInt(1);
            Variable variable = variableOf(entry.get("variable"), entry.get("description"));
            String[] offsets = new String[terms];
            JsonNode declared = entry.path("offsets");
            if (declared.isArray() && declared.size() != terms)
                throw new Encoding3dException(where + ": derived field '" + name + "' has not one offset per term");
            for (int term = 0; declared.isArray() && term < terms; term++)
                offsets[term] = declared.get(term).isNull() ? null : declared.get(term).asText();
            long[] operators = longsOf(takeColumn(instanceSet, name + "__operator", where));
            double[] weights = doublesOf(takeColumn(instanceSet, name + "__weight", where));
            if (operators.length != instanceSet.count() * terms || weights.length != instanceSet.count() * terms)
                throw new Encoding3dException(where + ": derived field '" + name + "' has not " + terms
                        + " operators and weights per instance");
            instanceSet.derived.add(new DerivedField(name, entry.get("entitySet").asText(), entry.get("input").asText(), terms,
                    operators, weights, offsets, variable));
        }
        return instanceSet;
    }

    private static Column takeColumn(Table table, String name, String where) {
        Column column = table.columns.remove(name);
        if (column == null) throw new Encoding3dException(where + ": no column '" + name + "'");
        table.variables.remove(name);
        return column;
    }

    private static double[] doublesOf(Column column) {
        if (column.type == ComponentType.FLOAT64) return column.doubles();
        double[] values = new double[column.size()];
        for (int index = 0; index < values.length; index++) values[index] = column.doubleAt(index);
        return values;
    }

    private static long[] longsOf(Column column) {
        if (column.type == ComponentType.INT64) return column.longs();
        long[] values = new long[column.size()];
        for (int index = 0; index < values.length; index++) values[index] = (long) column.doubleAt(index);
        return values;
    }

    private static Variable variableOf(JsonNode declared, JsonNode description) {
        Variable variable = new Variable();
        if (declared != null && !declared.isNull()) {
            variable.unit = declared.path("unit").asText("1");
            variable.role = declared.path("role").asText("state");
            if (declared.hasNonNull("standardName")) variable.standardName = declared.get("standardName").asText();
            if (declared.hasNonNull("kind")) variable.kind = declared.get("kind").asText();
            if (declared.hasNonNull("minimum")) variable.minimum = declared.get("minimum").asDouble();
            if (declared.hasNonNull("maximum")) variable.maximum = declared.get("maximum").asDouble();
            for (JsonNode reference : declared.path("references")) variable.references.add(reference.asText());
            for (JsonNode doi : declared.path("doi")) variable.doi.add(doi.asText());
            if (declared.hasNonNull("format")) variable.format = declared.get("format").asText();
        }
        if (description != null && !description.isNull()) variable.description = description.asText();
        return variable;
    }

    static ByteBuffer view(JsonNode document, byte[] binary, int index) {
        JsonNode view = document.get("bufferViews").get(index);
        if (view.path("buffer").asInt(0) != 0) throw new Encoding3dException("encoding3d files keep every buffer view in the GLB binary chunk");
        int start = view.path("byteOffset").asInt(0), length = view.get("byteLength").asInt();
        if (start < 0 || length < 0 || start + (long) length > binary.length) throw new Encoding3dException("a buffer view runs past the binary chunk");
        return ByteBuffer.wrap(binary, start, length).slice().order(ByteOrder.LITTLE_ENDIAN);
    }

    private static long[] unsignedValues(String type, ByteBuffer bytes, int count) {
        long[] values = new long[count];
        for (int index = 0; index < count; index++)
            values[index] = switch (type) {
                case "UINT8" -> Byte.toUnsignedLong(bytes.get(index));
                case "UINT16" -> Short.toUnsignedLong(bytes.getShort(index * 2));
                case "UINT32" -> Integer.toUnsignedLong(bytes.getInt(index * 4));
                case "UINT64" -> bytes.getLong(index * 8);
                default -> throw new Encoding3dException("offsets or enum values of type " + type + " are not part of encoding3d 0.1");
            };
        return values;
    }

    private static Column readScalars(ComponentType type, ByteBuffer bytes, int count, int width) {
        int size = count * width;
        if ((long) size * type.size > bytes.remaining()) throw new Encoding3dException("a buffer view is too short for its values");
        return switch (type) {
            case INT8, UINT8 -> { byte[] values = new byte[size]; bytes.get(values); yield new Column(type, values, width); }
            case INT16, UINT16 -> { short[] values = new short[size]; bytes.asShortBuffer().get(values); yield new Column(type, values, width); }
            case INT32, UINT32 -> { int[] values = new int[size]; bytes.asIntBuffer().get(values); yield new Column(type, values, width); }
            case INT64, UINT64 -> { long[] values = new long[size]; bytes.asLongBuffer().get(values); yield new Column(type, values, width); }
            case FLOAT32 -> { float[] values = new float[size]; bytes.asFloatBuffer().get(values); yield new Column(type, values, width); }
            case FLOAT64 -> { double[] values = new double[size]; bytes.asDoubleBuffer().get(values); yield new Column(type, values, width); }
            default -> throw new Encoding3dException("component type " + type + " is not a number");
        };
    }

    private static void decodeTable(JsonNode document, byte[] binary, JsonNode metadata, JsonNode variables, int index,
                                    Table table) {
        JsonNode description = metadata.get("propertyTables").get(index);
        String classId = description.get("class").asText();
        table.name = description.path("name").asText(classId);
        JsonNode schema = metadata.get("schema");
        JsonNode properties = schema.get("classes").get(classId).get("properties");
        int count = description.get("count").asInt();
        for (Iterator<Map.Entry<String, JsonNode>> items = description.get("properties").fields(); items.hasNext(); ) {
            Map.Entry<String, JsonNode> item = items.next();
            String name = item.getKey();
            JsonNode stored = item.getValue(), property = properties.get(name);
            ByteBuffer raw = view(document, binary, stored.get("values").asInt());
            String type = property.get("type").asText();
            Column column;
            switch (type) {
                case "ENUM" -> {
                    JsonNode enumeration = schema.get("enums").get(property.get("enumType").asText());
                    long[] codes = unsignedValues(enumeration.path("valueType").asText("UINT16"), raw, count);
                    Map<Long, String> nameOf = new HashMap<>();
                    for (JsonNode value : enumeration.get("values")) nameOf.put(value.get("value").asLong(), value.get("name").asText());
                    String[] labels = new String[count];
                    for (int row = 0; row < count; row++) labels[row] = nameOf.get(codes[row]);
                    column = new Column(ComponentType.STRING, labels);
                }
                case "STRING" -> {
                    long[] offsets = unsignedValues(stored.path("stringOffsetType").asText("UINT32"),
                            view(document, binary, stored.get("stringOffsets").asInt()), count + 1);
                    String[] text = new String[count];
                    byte[] bytes = new byte[raw.remaining()];
                    raw.get(bytes);
                    for (int row = 0; row < count; row++) {
                        if (offsets[row + 1] > bytes.length || offsets[row] > offsets[row + 1])
                            throw new Encoding3dException("'" + classId + "." + name + "': string offsets outside its values");
                        text[row] = new String(bytes, (int) offsets[row], (int) (offsets[row + 1] - offsets[row]), StandardCharsets.UTF_8);
                    }
                    column = new Column(ComponentType.STRING, text);
                    if (property.has("noData")) {                // missing text
                        String noData = property.get("noData").asText();
                        boolean[] missing = new boolean[count];
                        boolean any = false;
                        for (int row = 0; row < count; row++)
                            if (text[row].equals(noData)) {
                                missing[row] = any = true;
                                text[row] = "";
                            }
                        if (any) column.missing = missing;
                    }
                }
                case "BOOLEAN" -> {
                    if (raw.remaining() * 8L < count) throw new Encoding3dException("'" + classId + "." + name + "': too few bits");
                    boolean[] values = new boolean[count];
                    for (int row = 0; row < count; row++) values[row] = ((raw.get(row / 8) >> (row % 8)) & 1) == 1;
                    column = new Column(ComponentType.BOOLEAN, values);
                }
                case "SCALAR" -> {
                    boolean vector = property.path("array").asBoolean(false);
                    if (vector && !property.has("count"))
                        throw new Encoding3dException("'" + classId + "." + name + "': variable-length arrays are not part of encoding3d 0.1");
                    int width = vector ? property.get("count").asInt() : 1;
                    ComponentType componentType;
                    try {
                        componentType = ComponentType.valueOf(property.get("componentType").asText());
                    } catch (IllegalArgumentException error) {
                        throw new Encoding3dException("component type " + property.get("componentType") + " is not part of encoding3d 0.1");
                    }
                    column = readScalars(componentType, raw, count, width);
                    restoreStandIns(column, property);
                    if (property.path("extras").path("FSPM_boolean").asBoolean(false)) {    // booleans with missing values
                        long noData = property.path("noData").asLong(BOOLEAN_NO_DATA);
                        boolean[] values = new boolean[count], missing = new boolean[count];
                        boolean any = false;
                        for (int row = 0; row < count; row++) {
                            long code = (long) column.doubleAt(row);
                            missing[row] = code == noData;
                            any |= missing[row];
                            values[row] = !missing[row] && code == 1;
                        }
                        column = new Column(ComponentType.BOOLEAN, values);
                        if (any) column.missing = missing;
                    } else if (width == 1 && !componentType.isFloat() && property.has("noData")
                            && !name.equals("complex") && !name.equals("parent")) {         // missing integers
                        long noData = property.get("noData").asLong();
                        boolean[] missing = new boolean[count];
                        boolean any = false;
                        for (int row = 0; row < count; row++) {
                            missing[row] = rawLong(column, row) == noData;
                            any |= missing[row];
                        }
                        if (any) column.missing = missing;
                    }
                }
                default -> throw new Encoding3dException("'" + classId + "." + name + "': property type " + type + " is not part of encoding3d 0.1");
            }
            table.columns.put(name, column);
            JsonNode declared = variables.path(classId).get(name);
            if (declared != null || property.has("description"))
                table.variables.put(name, variableOf(declared, property.get("description")));
        }
    }

    private static void restoreStandIns(Column column, JsonNode property) {
        JsonNode infinity = property.path("extras").path("FSPM_infinity");
        if (column.type == ComponentType.FLOAT64) {
            double[] values = column.doubles();
            if (property.has("noData")) {
                double noData = property.get("noData").asDouble();
                for (int index = 0; index < values.length; index++) if (values[index] == noData) values[index] = Double.NaN;
            }
            if (!infinity.isMissingNode()) {
                double positive = infinity.get("positive").asDouble(), negative = infinity.get("negative").asDouble();
                for (int index = 0; index < values.length; index++) {
                    if (values[index] == positive) values[index] = Double.POSITIVE_INFINITY;
                    else if (values[index] == negative) values[index] = Double.NEGATIVE_INFINITY;
                }
            }
        } else if (column.type == ComponentType.FLOAT32) {
            float[] values = column.floats();
            if (property.has("noData")) {
                float noData = (float) property.get("noData").asDouble();
                for (int index = 0; index < values.length; index++) if (values[index] == noData) values[index] = Float.NaN;
            }
            if (!infinity.isMissingNode()) {
                float positive = (float) infinity.get("positive").asDouble(), negative = (float) infinity.get("negative").asDouble();
                for (int index = 0; index < values.length; index++) {
                    if (values[index] == positive) values[index] = Float.POSITIVE_INFINITY;
                    else if (values[index] == negative) values[index] = Float.NEGATIVE_INFINITY;
                }
            }
        }
    }

    private static Grid decodeGrid(JsonNode item) {
        Grid grid = new Grid();
        grid.kind = item.get("kind").asText();
        grid.shape = new long[item.get("shape").size()];
        for (int index = 0; index < grid.shape.length; index++) grid.shape[index] = item.get("shape").get(index).asLong();
        grid.origin = doubles(item.get("origin"));
        grid.spacing = doubles(item.get("spacing"));
        List<String> axes = new ArrayList<>();
        for (JsonNode axis : item.get("axes")) axes.add(axis.asText());
        grid.axes = axes;
        grid.periodic = new boolean[item.get("periodic").size()];
        for (int index = 0; index < grid.periodic.length; index++) grid.periodic[index] = item.get("periodic").get(index).asBoolean();
        grid.zUp = item.path("zUp").asBoolean(true);
        grid.maxLevel = item.path("maxLevel").asLong(0);
        grid.cells = item.get("cells").asText();
        return grid;
    }

    private static double[] doubles(JsonNode array) {
        double[] values = new double[array.size()];
        for (int index = 0; index < values.length; index++) values[index] = array.get(index).asDouble();
        return values;
    }

    /** An accessor's values, as doubles, row after row. */
    private static double[] accessorValues(JsonNode document, byte[] binary, int index) {
        JsonNode accessor = document.get("accessors").get(index);
        int width = switch (accessor.get("type").asText()) {
            case "SCALAR" -> 1;
            case "VEC2" -> 2;
            case "VEC3" -> 3;
            case "VEC4" -> 4;
            default -> throw new Encoding3dException("accessor type " + accessor.get("type") + " is not used by encoding3d");
        };
        int componentType = accessor.get("componentType").asInt();
        int size = switch (componentType) {
            case FLOAT, UNSIGNED_INT -> 4;
            case UNSIGNED_SHORT -> 2;
            case UNSIGNED_BYTE -> 1;
            default -> throw new Encoding3dException("accessor component type " + componentType + " is not used by encoding3d");
        };
        int viewIndex = accessor.get("bufferView").asInt();
        ByteBuffer raw = view(document, binary, viewIndex);
        int stride = document.get("bufferViews").get(viewIndex).path("byteStride").asInt(size * width);
        int start = accessor.path("byteOffset").asInt(0), count = accessor.get("count").asInt();
        double[] values = new double[count * width];
        for (int item = 0; item < count; item++)
            for (int component = 0; component < width; component++) {
                int at = start + item * stride + component * size;
                if (at + size > raw.limit()) throw new Encoding3dException("an accessor runs past its buffer view");
                values[item * width + component] = switch (componentType) {
                    case FLOAT -> raw.getFloat(at);
                    case UNSIGNED_INT -> Integer.toUnsignedLong(raw.getInt(at));
                    case UNSIGNED_SHORT -> Short.toUnsignedInt(raw.getShort(at));
                    default -> Byte.toUnsignedInt(raw.get(at));
                };
            }
        return values;
    }

    private static Mesh decodeMesh(JsonNode document, byte[] binary, JsonNode meshEntry, Map<Integer, String> tableNames) {
        JsonNode primitive = document.get("meshes").get(meshEntry.get("mesh").asInt()).get("primitives").get(0);
        JsonNode attributes = primitive.get("attributes");
        Mesh mesh = new Mesh(meshEntry.get("name").asText(), accessorValues(document, binary, attributes.get("POSITION").asInt()));
        for (JsonNode feature : primitive.path("extensions").path(FEATURES).path("featureIds")) {
            double[] stored = accessorValues(document, binary, attributes.get("_FEATURE_ID_" + feature.get("attribute").asInt()).asInt());
            long[] rows = new long[stored.length];
            long nullRow = feature.has("nullFeatureId") ? feature.get("nullFeatureId").asLong() : Long.MIN_VALUE;
            for (int vertex = 0; vertex < rows.length; vertex++)
                rows[vertex] = (long) stored[vertex] == nullRow ? EntitySet.NO_ID : (long) stored[vertex];
            mesh.featureRows.put(tableNames.get(feature.get("propertyTable").asInt()), rows);
        }
        for (JsonNode item : meshEntry.path("display")) {
            double[] stored = accessorValues(document, binary, attributes.get(item.get("attribute").asText()).asInt());
            float[] values = new float[stored.length];
            for (int vertex = 0; vertex < values.length; vertex++) values[vertex] = (float) stored[vertex];
            String variable = item.get("variable").asText();
            mesh.display.put(variable, values);
            if (item.hasNonNull("entitySet")) mesh.displaySources.put(variable, item.get("entitySet").asText());
        }
        if (primitive.has("indices")) {
            double[] stored = accessorValues(document, binary, primitive.get("indices").asInt());
            mesh.indices = new long[stored.length];
            for (int index = 0; index < stored.length; index++) mesh.indices[index] = (long) stored[index];
        }
        return mesh;
    }
}
