// Reading and writing frames as GLB files. Tables are EXT_structural_metadata property tables (one class per table),
// meshes carry EXT_mesh_features feature IDs, and the FSPM_scene root extension holds what these two cannot: data
// structures, entity sets and their ranks, relations, grids, mappings, the frame's time, and the variables' units,
// standard names, kinds and roles.
#include "fspm_tf/fspm_tf.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iterator>
#include <limits>
#include <map>
#include <regex>
#include <set>
#include <type_traits>

#include "bytes.hpp"

namespace fspm_tf {

namespace {

const std::string EXTENSION = "FSPM_scene";
const std::string METADATA = "EXT_structural_metadata";
const std::string FEATURES = "EXT_mesh_features";
const std::string EDGE_TYPE_ENUM = "FSPM_edge_type";
const std::vector<std::string> ENUM_COLUMNS = {"label", "edge_type", "relation"};
const std::vector<std::string> ID_COLUMNS = {"id", "complex", "parent", "source", "target", "level", "index"};
constexpr int ARRAY_BUFFER = 34962, ELEMENT_ARRAY_BUFFER = 34963;
constexpr int FLOAT = 5126, UNSIGNED_INT = 5125, UNSIGNED_SHORT = 5123, UNSIGNED_BYTE = 5121;
constexpr std::int64_t MAX_FLOAT_FEATURE = std::int64_t(1) << 24;   // feature rows are float vertex attributes
// The scene's frame is z up (metres); glTF viewers expect y up: the root node turns the scene for them (-90° about
// x, column-major). Readers of the tables use the scene's frame, not this node.
const std::vector<double> Z_UP_TO_Y_UP = {1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1};

bool contains(const std::vector<std::string> &names, const std::string &name) {
    return std::find(names.begin(), names.end(), name) != names.end();
}

void check_identifier(const std::string &name, const std::string &what) {
    static const std::regex identifier("^[a-zA-Z_][a-zA-Z0-9_]*$");
    if (!std::regex_match(name, identifier))
        throw Error(what + " '" + name + "' must be an identifier (letters, digits, '_'; not starting with a digit)");
}

template <typename T> struct Component;
template <> struct Component<std::int8_t> { static constexpr const char *name = "INT8"; };
template <> struct Component<std::uint8_t> { static constexpr const char *name = "UINT8"; };
template <> struct Component<std::int16_t> { static constexpr const char *name = "INT16"; };
template <> struct Component<std::uint16_t> { static constexpr const char *name = "UINT16"; };
template <> struct Component<std::int32_t> { static constexpr const char *name = "INT32"; };
template <> struct Component<std::uint32_t> { static constexpr const char *name = "UINT32"; };
template <> struct Component<std::int64_t> { static constexpr const char *name = "INT64"; };
template <> struct Component<std::uint64_t> { static constexpr const char *name = "UINT64"; };
template <> struct Component<float> { static constexpr const char *name = "FLOAT32"; };
template <> struct Component<double> { static constexpr const char *name = "FLOAT64"; };

template <typename T> constexpr bool is_number_v = std::is_arithmetic_v<T> && !std::is_same_v<T, bool>;

// EXT_structural_metadata forbids NaN and infinities: NaN is written as noData, the most negative finite value; +inf
// and -inf as the largest finite value and the next one after the most negative, declared in the property's extras
// (FSPM_infinity).
template <typename T> T no_data_float() { return std::numeric_limits<T>::lowest(); }
template <typename T> T positive_stand_in() { return std::numeric_limits<T>::max(); }
template <typename T> T negative_stand_in() {
    return std::nextafter(std::numeric_limits<T>::lowest(), T(0));
}

json get(const json &object, const std::string &key, json fallback = nullptr) {
    if (object.is_object()) {
        auto found = object.find(key);
        if (found != object.end()) return *found;
    }
    return fallback;
}

/// Appends arrays to one binary buffer, each at an 8-byte aligned offset, and records their buffer views.
struct BufferBuilder {
    std::vector<std::uint8_t> data;
    json views = json::array();

    std::int64_t add_bytes(const std::vector<std::uint8_t> &bytes, int target = 0) {
        data.resize(data.size() + detail::padding(data.size()), 0);
        json view = {{"buffer", 0}, {"byteOffset", data.size()}, {"byteLength", bytes.size()}};
        if (target != 0) view["target"] = target;
        data.insert(data.end(), bytes.begin(), bytes.end());
        views.push_back(view);
        return static_cast<std::int64_t>(views.size()) - 1;
    }
    template <typename T> std::int64_t add(const std::vector<T> &values, int target = 0) {
        std::vector<std::uint8_t> bytes;
        detail::append_values(bytes, values.data(), values.size());
        return add_bytes(bytes, target);
    }
};

json declaration_json(const Variable &variable) {
    json declaration = {{"unit", variable.unit}, {"role", variable.role}};
    if (variable.standard_name) declaration["standardName"] = *variable.standard_name;
    if (variable.kind) declaration["kind"] = *variable.kind;
    if (variable.minimum) declaration["minimum"] = *variable.minimum;
    if (variable.maximum) declaration["maximum"] = *variable.maximum;
    if (!variable.references.empty()) declaration["references"] = variable.references;
    if (!variable.doi.empty()) declaration["doi"] = variable.doi;
    return declaration;
}

std::pair<std::string, std::vector<std::uint8_t>> enum_codes(const std::string &name, const std::vector<std::string> &values,
                                                             const std::string &class_id, json &schema,
                                                             std::string &value_type) {
    if (name == "edge_type") {
        std::vector<std::uint8_t> codes;
        for (const auto &value : values) {
            auto found = std::find(EDGE_TYPES.begin(), EDGE_TYPES.end(), value);
            if (found == EDGE_TYPES.end())
                throw Error("edge_type of '" + class_id + "': unknown value '" + value +
                            "' (allowed: none, successor, branch)");
            codes.push_back(static_cast<std::uint8_t>(found - EDGE_TYPES.begin()));
        }
        value_type = "UINT8";
        return {EDGE_TYPE_ENUM, codes};
    }
    std::set<std::string> sorted(values.begin(), values.end());
    std::vector<std::string> names(sorted.begin(), sorted.end());
    const std::string enum_name = class_id + "__" + name;
    value_type = names.size() <= 256 ? "UINT8" : "UINT16";
    json enum_values = json::array();
    std::map<std::string, std::uint16_t> code_of;
    for (std::size_t code = 0; code < names.size(); ++code) {
        enum_values.push_back({{"name", names[code]}, {"value", code}});
        code_of[names[code]] = static_cast<std::uint16_t>(code);
    }
    schema["enums"][enum_name] = {{"valueType", value_type}, {"values", enum_values}};
    std::vector<std::uint8_t> bytes;
    for (const auto &value : values) {
        const std::uint16_t code = code_of[value];
        if (value_type == "UINT8") {
            const auto narrow = static_cast<std::uint8_t>(code);
            detail::append_values(bytes, &narrow, 1);
        } else {
            detail::append_values(bytes, &code, 1);
        }
    }
    return {enum_name, bytes};
}

/// The class properties and property table values of a table's columns.
std::pair<json, json> encode_table(const Table &table, const std::string &class_id, BufferBuilder &buffers,
                                   json &schema) {
    table.check_lengths();
    json properties = json::object(), stored = json::object();
    for (const auto &[name, column] : table.columns) {
        check_identifier(name, "column of '" + table.name + "'");
        json property = json::object();
        auto declared = table.variables.find(name);
        if (declared != table.variables.end() && declared->second.description)
            property["description"] = *declared->second.description;
        const bool reserved = table.is_reserved(name);
        const std::string where = "column '" + name + "' of '" + table.name + "'";
        if (reserved && contains(ENUM_COLUMNS, name)) {
            if (!column.holds<std::string>()) throw Error(where + ": labels are text");
            std::string value_type;
            auto [enum_name, codes] = enum_codes(name, column.as<std::string>(), class_id, schema, value_type);
            property["type"] = "ENUM";
            property["enumType"] = enum_name;
            stored[name] = {{"values", buffers.add_bytes(codes)}};
        } else if (column.holds<std::string>()) {
            if (column.width != 1) throw Error(where + ": text vectors are not supported");
            property["type"] = "STRING";
            std::vector<std::uint8_t> text;
            std::vector<std::uint64_t> offsets = {0};
            for (const auto &value : column.as<std::string>()) {
                text.insert(text.end(), value.begin(), value.end());
                offsets.push_back(text.size());
            }
            json item = {{"values", buffers.add_bytes(text)}};
            if (offsets.back() < (std::uint64_t(1) << 32)) {
                item["stringOffsets"] = buffers.add(std::vector<std::uint32_t>(offsets.begin(), offsets.end()));
                item["stringOffsetType"] = "UINT32";
            } else {
                item["stringOffsets"] = buffers.add(offsets);
                item["stringOffsetType"] = "UINT64";
            }
            stored[name] = item;
        } else if (column.holds<bool>()) {
            if (column.width != 1) throw Error(where + ": boolean vectors are not supported");
            property["type"] = "BOOLEAN";
            const auto &values = column.as<bool>();
            std::vector<std::uint8_t> packed((values.size() + 7) / 8, 0);
            for (std::size_t row = 0; row < values.size(); ++row)
                if (values[row]) packed[row / 8] |= static_cast<std::uint8_t>(1u << (row % 8));   // bit order: little
            stored[name] = {{"values", buffers.add_bytes(packed)}};
        } else {
            std::visit([&](const auto &values) {
                using T = typename std::decay_t<decltype(values)>::value_type;
                if constexpr (is_number_v<T>) {
                    if constexpr (std::is_integral_v<T> && !std::is_same_v<T, std::int64_t>) {
                        if (reserved && contains(ID_COLUMNS, name)) {      // ids are INT64, whatever the platform's
                            property["type"] = "SCALAR";
                            property["componentType"] = "INT64";
                            if (column.width >= 2) {
                                property["array"] = true;
                                property["count"] = column.width;
                            }
                            if (name == "complex" || name == "parent") property["noData"] = NO_ID;
                            stored[name] = {{"values", buffers.add(std::vector<std::int64_t>(values.begin(), values.end()))}};
                            return;
                        }
                    }
                    property["type"] = "SCALAR";
                    property["componentType"] = Component<T>::name;
                    if (column.width != 1) {
                        if (column.width < 2) throw Error(where + ": vectors have at least 2 components");
                        property["array"] = true;
                        property["count"] = column.width;
                    }
                    std::vector<T> data = values;
                    if constexpr (std::is_floating_point_v<T>) {
                        const bool infinite = std::any_of(data.begin(), data.end(), [](T value) { return std::isinf(value); });
                        if (infinite) {
                            const T positive = positive_stand_in<T>(), negative = negative_stand_in<T>();
                            if (std::any_of(data.begin(), data.end(),
                                            [&](T value) { return value == positive || value == negative; }))
                                throw Error(where + " holds both infinities and the values standing for them");
                            property["extras"] = {{"FSPM_infinity", {{"positive", static_cast<double>(positive)},
                                                                     {"negative", static_cast<double>(negative)}}}};
                            for (auto &value : data)
                                if (std::isinf(value)) value = value > 0 ? positive : negative;
                        }
                        if (std::any_of(data.begin(), data.end(), [](T value) { return std::isnan(value); })) {
                            const T no_data = no_data_float<T>();
                            if (std::any_of(data.begin(), data.end(), [&](T value) { return value == no_data; }))
                                throw Error(where + " holds both NaN and the value standing for NaN");
                            property["noData"] = static_cast<double>(no_data);
                            for (auto &value : data)
                                if (std::isnan(value)) value = no_data;
                        }
                    } else if (reserved && (name == "complex" || name == "parent")) {
                        property["noData"] = NO_ID;
                    }
                    stored[name] = {{"values", buffers.add(data)}};
                }
            }, column.values);
        }
        if (name == "id" && table.table_kind == TableKind::entity_set) property["required"] = true;
        properties[name] = property;
    }
    return {properties, stored};
}

json grid_json(const Grid &grid) {
    json entry = {{"kind", grid.kind}, {"shape", grid.shape}, {"origin", grid.origin}, {"spacing", grid.spacing},
                  {"axes", grid.axes}, {"periodic", grid.periodic}, {"zUp", grid.z_up}, {"cells", grid.cells}};
    if (grid.kind == "adaptive") entry["maxLevel"] = grid.max_level;
    return entry;
}

std::string display_attribute(const std::string &name) {
    std::string attribute = "_" + name;
    std::transform(attribute.begin(), attribute.end(), attribute.begin(),
                   [](unsigned char character) { return static_cast<char>(std::toupper(character)); });
    return attribute;
}

json encode_mesh(const Mesh &mesh, const DataStructure &data_structure, const json &entry, BufferBuilder &buffers,
                 json &accessors) {
    const std::size_t vertices = mesh.vertex_count();
    if (mesh.positions.size() != vertices * 3) throw Error("mesh '" + mesh.name + "': 3 coordinates per vertex");
    auto accessor = [&](auto values, const char *type, int component_type, int target, std::size_t count,
                        bool bounds = false) {
        json item = {{"bufferView", buffers.add(values, target)}, {"componentType", component_type},
                     {"count", count}, {"type", type}};
        if (bounds && count > 0) {
            std::vector<double> minimum(3, std::numeric_limits<double>::infinity()), maximum(3, -minimum[0]);
            for (std::size_t vertex = 0; vertex < count; ++vertex)
                for (int axis = 0; axis < 3; ++axis) {
                    minimum[axis] = std::min(minimum[axis], static_cast<double>(values[vertex * 3 + axis]));
                    maximum[axis] = std::max(maximum[axis], static_cast<double>(values[vertex * 3 + axis]));
                }
            item["min"] = minimum;
            item["max"] = maximum;
        }
        accessors.push_back(item);
        return static_cast<std::int64_t>(accessors.size()) - 1;
    };
    std::vector<float> positions(mesh.positions.begin(), mesh.positions.end());
    json attributes = {{"POSITION", accessor(positions, "VEC3", FLOAT, ARRAY_BUFFER, vertices, true)}};
    std::map<std::string, std::int64_t> tables;
    for (const auto &set_entry : entry["entitySets"])
        tables[set_entry["name"].get<std::string>()] = set_entry["propertyTable"].get<std::int64_t>();
    json feature_ids = json::array();
    for (std::size_t set_index = 0; set_index < mesh.feature_rows.size(); ++set_index) {
        const auto &[set_name, rows] = mesh.feature_rows[set_index];
        if (!tables.count(set_name))
            throw Error("mesh '" + mesh.name + "': no entity set '" + set_name + "' in '" + data_structure.id + "'");
        if (rows.size() != vertices)
            throw Error("mesh '" + mesh.name + "': feature rows of '" + set_name + "' are not one per vertex");
        const auto count = static_cast<std::int64_t>(data_structure.entity_set(set_name).row_count());
        if (count >= MAX_FLOAT_FEATURE)
            throw Error("mesh '" + mesh.name + "': too many entities in '" + set_name + "', feature IDs stop at 2^24");
        std::vector<float> stored;
        std::set<std::int64_t> present;
        bool has_null = false;
        for (const auto row : rows) {
            if (row < NO_ID || row >= count)
                throw Error("mesh '" + mesh.name + "': feature rows of '" + set_name + "' outside its rows");
            has_null = has_null || row == NO_ID;
            if (row != NO_ID) present.insert(row);
            stored.push_back(static_cast<float>(row == NO_ID ? count : row));   // null: one past the last row
        }
        attributes["_FEATURE_ID_" + std::to_string(set_index)] = accessor(stored, "SCALAR", FLOAT, ARRAY_BUFFER, vertices);
        json feature = {{"featureCount", present.size()}, {"attribute", set_index},
                        {"propertyTable", tables[set_name]}, {"label", set_name}};
        if (has_null) feature["nullFeatureId"] = count;
        feature_ids.push_back(feature);
    }
    for (const auto &[name, values] : mesh.display) {
        if (values.size() != vertices)
            throw Error("mesh '" + mesh.name + "': display copy '" + name + "' is not one value per vertex");
        attributes[display_attribute(name)] = accessor(values, "SCALAR", FLOAT, ARRAY_BUFFER, vertices);
    }
    json primitive = {{"attributes", attributes}, {"mode", 4}};
    if (mesh.indices) {
        std::vector<std::uint32_t> indices(mesh.indices->begin(), mesh.indices->end());
        primitive["indices"] = accessor(indices, "SCALAR", UNSIGNED_INT, ELEMENT_ARRAY_BUFFER, indices.size());
    }
    if (!feature_ids.empty()) primitive["extensions"] = {{FEATURES, {{"featureIds", feature_ids}}}};
    return {{"name", mesh.name}, {"primitives", json::array({primitive})}};
}

bool is_identity(const std::array<double, 16> &origin) {
    for (int row = 0; row < 4; ++row)
        for (int column = 0; column < 4; ++column)
            if (origin[row * 4 + column] != (row == column ? 1.0 : 0.0)) return false;
    return true;
}

std::vector<double> column_major(const std::array<double, 16> &origin) {
    std::vector<double> values(16);
    for (int row = 0; row < 4; ++row)
        for (int column = 0; column < 4; ++column) values[column * 4 + row] = origin[row * 4 + column];
    return values;
}

} // namespace

// ── Writing ──────────────────────────────────────────────────────────────

std::vector<std::uint8_t> to_bytes(const Frame &frame) {
    BufferBuilder buffers;
    json edge_values = json::array();
    for (std::size_t value = 0; value < EDGE_TYPES.size(); ++value)
        edge_values.push_back({{"name", EDGE_TYPES[value]}, {"value", value}});
    json schema = {{"id", "fspm_scene"}, {"classes", json::object()},
                   {"enums", {{EDGE_TYPE_ENUM, {{"valueType", "UINT8"}, {"values", edge_values}}}}}};
    json tables = json::array(), variables = json::object();
    json document = {{"asset", {{"version", "2.0"}, {"generator", std::string("fspm_tf (C++) ") + SPECIFICATION_VERSION}}},
                     {"scene", 0}, {"scenes", json::array({{{"nodes", json::array({0})}}})},
                     {"nodes", json::array({{{"name", "fspm_scene"}, {"matrix", Z_UP_TO_Y_UP},
                                             {"children", json::array()}}})}};
    json accessors = json::array(), meshes = json::array();

    auto add_table = [&](const Table &table, const std::string &class_id) {
        check_identifier(class_id, "class");
        auto [properties, stored] = encode_table(table, class_id, buffers, schema);
        schema["classes"][class_id] = {{"name", table.name}, {"properties", properties}};
        tables.push_back({{"name", table.name}, {"class", class_id}, {"count", table.row_count()},
                          {"properties", stored}});
        json declared = json::object();
        for (const auto &name : table.variable_names()) {
            auto found = table.variables.find(name);
            if (found != table.variables.end()) declared[name] = declaration_json(found->second);
        }
        if (!declared.empty()) variables[class_id] = declared;
        return static_cast<std::int64_t>(tables.size()) - 1;
    };

    json data_structures = json::array();
    for (const auto &data_structure : frame.data_structures) {
        check_identifier(data_structure.id, "data structure id");
        json entry = {{"id", data_structure.id}, {"kind", data_structure.kind}};
        if (data_structure.platform) entry["platform"] = *data_structure.platform;
        if (data_structure.model) entry["model"] = *data_structure.model;
        entry["origin"] = column_major(data_structure.origin);       // column-major, as glTF matrices
        json sets = json::array();
        for (const auto &set : data_structure.entity_sets) {
            json item = {{"name", set.name}, {"rank", nullptr}};
            if (set.rank) item["rank"] = *set.rank;
            item["propertyTable"] = add_table(set, data_structure.id + "__" + set.name);
            sets.push_back(item);
        }
        entry["entitySets"] = sets;
        if (!data_structure.relations.empty()) {
            json relations = json::array();
            for (const auto &relation : data_structure.relations)
                relations.push_back({{"name", relation.name}, {"sourceSet", relation.source_set},
                                     {"targetSet", relation.target_set},
                                     {"propertyTable", add_table(relation, data_structure.id + "__" + relation.name)}});
            entry["relations"] = relations;
        }
        if (data_structure.scalars) entry["scalars"] = add_table(*data_structure.scalars, data_structure.id + "__scalars");
        if (data_structure.grid) entry["grid"] = grid_json(*data_structure.grid);
        if (!data_structure.extras.empty()) entry["extras"] = data_structure.extras;
        json node = {{"name", data_structure.id}};
        if (!is_identity(data_structure.origin)) node["matrix"] = entry["origin"];
        document["nodes"].push_back(node);
        const auto node_index = document["nodes"].size() - 1;
        document["nodes"][0]["children"].push_back(node_index);
        entry["node"] = node_index;
        if (!data_structure.meshes.empty()) {
            document["nodes"][node_index]["children"] = json::array();
            entry["meshes"] = json::array();
            for (const auto &mesh : data_structure.meshes) {
                meshes.push_back(encode_mesh(mesh, data_structure, entry, buffers, accessors));
                document["nodes"].push_back({{"name", mesh.name}, {"mesh", meshes.size() - 1}});
                document["nodes"][node_index]["children"].push_back(document["nodes"].size() - 1);
                json mesh_entry = {{"name", mesh.name}, {"mesh", meshes.size() - 1}};
                if (!mesh.display.empty()) {
                    json display = json::array();
                    for (const auto &item : mesh.display) {
                        auto source = mesh.display_sources.find(item.first);
                        display.push_back({{"attribute", display_attribute(item.first)}, {"variable", item.first},
                                           {"entitySet", source == mesh.display_sources.end() ? json(nullptr)
                                                                                              : json(source->second)}});
                    }
                    mesh_entry["display"] = display;
                }
                entry["meshes"].push_back(mesh_entry);
            }
        }
        data_structures.push_back(entry);
    }

    json mappings = json::array();
    for (const auto &mapping : frame.mappings) {
        check_identifier(mapping.name, "mapping name");
        json entry = {{"name", mapping.name},
                      {"source", {{"dataStructure", mapping.source.first}, {"entitySet", mapping.source.second}}},
                      {"target", {{"dataStructure", mapping.target.first}, {"entitySet", mapping.target.second}}}};
        if (mapping.method) entry["method"] = *mapping.method;
        entry["propertyTable"] = add_table(mapping, "mapping__" + mapping.name);
        mappings.push_back(entry);
    }

    json scene = {{"version", SPECIFICATION_VERSION},
                  {"frame", {{"time", frame.time}, {"timeUnit", frame.time_unit}, {"step", frame.step}}}};
    if (frame.vocabulary_version) scene["vocabulary"] = *frame.vocabulary_version;
    if (!frame.writer.empty()) scene["writer"] = frame.writer;
    scene["dataStructures"] = data_structures;
    if (!mappings.empty()) scene["mappings"] = mappings;
    if (!variables.empty()) scene["variables"] = variables;

    const json other_extensions = get(frame.unknown, "extensions", json::object());
    json extensions = {{METADATA, {{"schema", schema}, {"propertyTables", tables}}}, {EXTENSION, scene}};
    json used = json::array({METADATA, EXTENSION});
    if (!meshes.empty()) used.push_back(FEATURES);
    for (const auto &item : other_extensions.items()) {
        extensions[item.key()] = item.value();
        used.push_back(item.key());
    }
    document["extensionsUsed"] = used;
    document["extensions"] = extensions;
    if (frame.unknown.is_object() && frame.unknown.contains("extras")) document["extras"] = frame.unknown["extras"];
    if (!meshes.empty()) {
        document["meshes"] = meshes;
        document["accessors"] = accessors;
    }
    if (!buffers.views.empty()) {
        // the buffer holds the chunk's padding to 8 bytes: glTF-Validator warns of more than 3 bytes beyond it
        buffers.data.resize(buffers.data.size() + detail::padding(buffers.data.size()), 0);
        document["buffers"] = json::array({{{"byteLength", buffers.data.size()}}});
        document["bufferViews"] = buffers.views;
    }
    return pack(document, buffers.data);
}

void write_frame(const std::string &path, const Frame &frame) {
    const auto bytes = to_bytes(frame);
    std::ofstream file(path, std::ios::binary);
    if (!file) throw Error("cannot write '" + path + "'");
    file.write(reinterpret_cast<const char *>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

// ── Reading ──────────────────────────────────────────────────────────────

namespace {

struct ViewBytes {
    const std::uint8_t *data;
    std::size_t size;
};

ViewBytes view_bytes(const json &document, const std::vector<std::uint8_t> &binary, std::int64_t index) {
    const json &view = document.at("bufferViews").at(static_cast<std::size_t>(index));
    if (get(view, "buffer", 0).get<std::int64_t>() != 0)
        throw Error("fspm-TF files keep every buffer view in the GLB binary chunk");
    const auto start = get(view, "byteOffset", 0).get<std::size_t>();
    const auto length = view.at("byteLength").get<std::size_t>();
    if (start + length > binary.size()) throw Error("a buffer view runs past the binary chunk");
    return {binary.data() + start, length};
}

template <typename T> std::vector<T> read_view(const ViewBytes &bytes, std::size_t count, std::size_t offset = 0) {
    return detail::read_values<T>(bytes.data, bytes.size, count, offset);
}

template <typename T>
Column decode_scalar(const ViewBytes &raw, const json &property, std::size_t count, std::size_t width) {
    std::vector<T> values = read_view<T>(raw, count * width);
    if constexpr (std::is_floating_point_v<T>) {
        if (property.contains("noData")) {
            const T no_data = static_cast<T>(property["noData"].get<double>());
            for (auto &value : values)
                if (value == no_data) value = std::numeric_limits<T>::quiet_NaN();
        }
        const json infinity = get(get(property, "extras", json::object()), "FSPM_infinity");
        if (!infinity.is_null()) {
            const T positive = static_cast<T>(infinity["positive"].get<double>());
            const T negative = static_cast<T>(infinity["negative"].get<double>());
            for (auto &value : values) {
                if (value == positive) value = std::numeric_limits<T>::infinity();
                else if (value == negative) value = -std::numeric_limits<T>::infinity();
            }
        }
    }
    return Column(std::move(values), width);
}

Column decode_scalar_of(const std::string &component, const ViewBytes &raw, const json &property, std::size_t count,
                        std::size_t width) {
    if (component == "INT8") return decode_scalar<std::int8_t>(raw, property, count, width);
    if (component == "UINT8") return decode_scalar<std::uint8_t>(raw, property, count, width);
    if (component == "INT16") return decode_scalar<std::int16_t>(raw, property, count, width);
    if (component == "UINT16") return decode_scalar<std::uint16_t>(raw, property, count, width);
    if (component == "INT32") return decode_scalar<std::int32_t>(raw, property, count, width);
    if (component == "UINT32") return decode_scalar<std::uint32_t>(raw, property, count, width);
    if (component == "INT64") return decode_scalar<std::int64_t>(raw, property, count, width);
    if (component == "UINT64") return decode_scalar<std::uint64_t>(raw, property, count, width);
    if (component == "FLOAT32") return decode_scalar<float>(raw, property, count, width);
    if (component == "FLOAT64") return decode_scalar<double>(raw, property, count, width);
    throw Error("component type " + component + " is not part of fspm-TF 0.1");
}

std::vector<std::uint64_t> read_unsigned(const std::string &type, const ViewBytes &raw, std::size_t count) {
    std::vector<std::uint64_t> values;
    if (type == "UINT8") for (auto value : read_view<std::uint8_t>(raw, count)) values.push_back(value);
    else if (type == "UINT16") for (auto value : read_view<std::uint16_t>(raw, count)) values.push_back(value);
    else if (type == "UINT32") for (auto value : read_view<std::uint32_t>(raw, count)) values.push_back(value);
    else if (type == "UINT64") values = read_view<std::uint64_t>(raw, count);
    else throw Error("offsets or enum values of type " + type + " are not part of fspm-TF 0.1");
    return values;
}

void decode_table(const json &document, const std::vector<std::uint8_t> &binary, const json &description,
                  const json &schema, const json &variables, Table &table) {
    const std::string class_id = description.at("class").get<std::string>();
    table.name = get(description, "name", class_id).get<std::string>();
    const json &properties = schema.at("classes").at(class_id).at("properties");
    const auto count = description.at("count").get<std::size_t>();
    for (const auto &item : description.at("properties").items()) {
        const std::string &name = item.key();
        const json &stored = item.value();
        const json &property = properties.at(name);
        const auto raw = view_bytes(document, binary, stored.at("values").get<std::int64_t>());
        const std::string type = property.at("type").get<std::string>();
        Column column;
        if (type == "ENUM") {
            const json &enumeration = schema.at("enums").at(property.at("enumType").get<std::string>());
            const auto codes = read_unsigned(get(enumeration, "valueType", "UINT16").get<std::string>(), raw, count);
            std::map<std::uint64_t, std::string> name_of;
            for (const auto &value : enumeration.at("values"))
                name_of[value.at("value").get<std::uint64_t>()] = value.at("name").get<std::string>();
            std::vector<std::string> labels;
            for (auto code : codes) labels.push_back(name_of.at(code));
            column = Column(std::move(labels));
        } else if (type == "STRING") {
            const auto offsets =
                read_unsigned(get(stored, "stringOffsetType", "UINT32").get<std::string>(),
                              view_bytes(document, binary, stored.at("stringOffsets").get<std::int64_t>()), count + 1);
            std::vector<std::string> text;
            for (std::size_t row = 0; row < count; ++row) {
                if (offsets[row + 1] > raw.size || offsets[row] > offsets[row + 1])
                    throw Error("'" + class_id + "." + name + "': string offsets outside its values");
                text.emplace_back(reinterpret_cast<const char *>(raw.data + offsets[row]), offsets[row + 1] - offsets[row]);
            }
            column = Column(std::move(text));
        } else if (type == "BOOLEAN") {
            if (raw.size * 8 < count) throw Error("'" + class_id + "." + name + "': too few bits");
            std::vector<bool> values(count);
            for (std::size_t row = 0; row < count; ++row) values[row] = (raw.data[row / 8] >> (row % 8)) & 1u;
            column = Column(std::move(values));
        } else if (type == "SCALAR") {
            const bool vector = get(property, "array", false).get<bool>();
            if (vector && !property.contains("count"))
                throw Error("'" + class_id + "." + name + "': variable-length arrays are not part of fspm-TF 0.1");
            const std::size_t width = vector ? property["count"].get<std::size_t>() : 1;
            column = decode_scalar_of(property.at("componentType").get<std::string>(), raw, property, count, width);
        } else {
            throw Error("'" + class_id + "." + name + "': property type " + type + " is not part of fspm-TF 0.1");
        }
        table.columns.emplace_back(name, std::move(column));
        const json declared = get(get(variables, class_id, json::object()), name);
        if (!declared.is_null() || property.contains("description")) {
            Variable variable;
            variable.unit = get(declared, "unit", "1").get<std::string>();
            variable.role = get(declared, "role", "state").get<std::string>();
            if (!get(declared, "standardName").is_null()) variable.standard_name = declared["standardName"].get<std::string>();
            if (!get(declared, "kind").is_null()) variable.kind = declared["kind"].get<std::string>();
            if (property.contains("description")) variable.description = property["description"].get<std::string>();
            if (!get(declared, "minimum").is_null()) variable.minimum = declared["minimum"].get<double>();
            if (!get(declared, "maximum").is_null()) variable.maximum = declared["maximum"].get<double>();
            for (const auto &reference : get(declared, "references", json::array()))
                variable.references.push_back(reference.get<std::string>());
            for (const auto &doi : get(declared, "doi", json::array())) variable.doi.push_back(doi.get<std::string>());
            table.variables[name] = variable;
        }
    }
}

template <typename T>
std::vector<T> accessor_values(const json &document, const std::vector<std::uint8_t> &binary, std::int64_t index,
                               std::size_t &width) {
    const json &accessor = document.at("accessors").at(static_cast<std::size_t>(index));
    const std::string type = accessor.at("type").get<std::string>();
    width = type == "SCALAR" ? 1 : type == "VEC2" ? 2 : type == "VEC3" ? 3 : type == "VEC4" ? 4 : 0;
    if (width == 0) throw Error("accessor type " + type + " is not used by fspm-TF");
    const auto view_index = accessor.at("bufferView").get<std::int64_t>();
    const auto raw = view_bytes(document, binary, view_index);
    const json &view = document["bufferViews"][static_cast<std::size_t>(view_index)];
    const auto count = accessor.at("count").get<std::size_t>();
    const auto start = get(accessor, "byteOffset", 0).get<std::size_t>();
    const auto component = accessor.at("componentType").get<int>();
    auto read = [&](auto tag) {
        using C = decltype(tag);
        const std::size_t item_size = sizeof(C) * width;
        const auto stride = get(view, "byteStride", item_size).template get<std::size_t>();
        std::vector<T> values;
        values.reserve(count * width);
        for (std::size_t item = 0; item < count; ++item)
            for (auto value : read_view<C>(raw, width, start + item * stride)) values.push_back(static_cast<T>(value));
        return values;
    };
    if (component == FLOAT) return read(float{});
    if (component == UNSIGNED_INT) return read(std::uint32_t{});
    if (component == UNSIGNED_SHORT) return read(std::uint16_t{});
    if (component == UNSIGNED_BYTE) return read(std::uint8_t{});
    throw Error("accessor component type " + std::to_string(component) + " is not used by fspm-TF");
}

Mesh decode_mesh(const json &document, const std::vector<std::uint8_t> &binary, const json &mesh_entry,
                 const std::map<std::int64_t, std::string> &tables) {
    const json &primitive = document.at("meshes").at(mesh_entry.at("mesh").get<std::size_t>()).at("primitives").at(0);
    const json &attributes = primitive.at("attributes");
    Mesh mesh;
    mesh.name = mesh_entry.at("name").get<std::string>();
    std::size_t width = 0;
    const auto positions = accessor_values<float>(document, binary, attributes.at("POSITION").get<std::int64_t>(), width);
    mesh.positions.assign(positions.begin(), positions.end());
    const json features = get(get(get(primitive, "extensions", json::object()), FEATURES, json::object()), "featureIds",
                              json::array());
    for (const auto &feature : features) {
        const std::string attribute = "_FEATURE_ID_" + std::to_string(feature.at("attribute").get<std::int64_t>());
        auto rows = accessor_values<std::int64_t>(document, binary, attributes.at(attribute).get<std::int64_t>(), width);
        if (feature.contains("nullFeatureId")) {
            const auto null_row = feature["nullFeatureId"].get<std::int64_t>();
            for (auto &row : rows)
                if (row == null_row) row = NO_ID;
        }
        mesh.feature_rows.emplace_back(tables.at(feature.at("propertyTable").get<std::int64_t>()), std::move(rows));
    }
    for (const auto &item : get(mesh_entry, "display", json::array())) {
        const std::string variable = item.at("variable").get<std::string>();
        mesh.display.emplace_back(variable, accessor_values<float>(
            document, binary, attributes.at(item.at("attribute").get<std::string>()).get<std::int64_t>(), width));
        if (!get(item, "entitySet").is_null()) mesh.display_sources[variable] = item["entitySet"].get<std::string>();
    }
    if (primitive.contains("indices"))
        mesh.indices = accessor_values<std::int64_t>(document, binary, primitive["indices"].get<std::int64_t>(), width);
    return mesh;
}

} // namespace

Frame from_bytes(const std::vector<std::uint8_t> &data) {
    auto [document, binary] = unpack(data);
    const json extensions = get(document, "extensions", json::object());
    if (!extensions.contains(EXTENSION)) throw Error("not an fspm-TF file: no " + EXTENSION + " extension");
    const json &scene = extensions[EXTENSION];
    const json metadata = get(extensions, METADATA, {{"schema", json::object()}, {"propertyTables", json::array()}});
    const json variables = get(scene, "variables", json::object());
    auto table = [&](std::int64_t index, Table &target) {
        decode_table(document, binary, metadata.at("propertyTables").at(static_cast<std::size_t>(index)),
                     metadata.at("schema"), variables, target);
    };

    Frame frame;
    const json frame_entry = get(scene, "frame", json::object());
    frame.time = get(frame_entry, "time", 0.0).get<double>();
    frame.time_unit = get(frame_entry, "timeUnit", "d").get<std::string>();
    frame.step = get(frame_entry, "step", 0).get<std::int64_t>();
    frame.writer = get(scene, "writer", json::object());
    if (!get(scene, "vocabulary").is_null()) frame.vocabulary_version = scene["vocabulary"].get<std::string>();
    for (const auto &entry : get(scene, "dataStructures", json::array())) {
        DataStructure data_structure(entry.at("id").get<std::string>(), get(entry, "kind", "graph").get<std::string>());
        if (!get(entry, "platform").is_null()) data_structure.platform = entry["platform"].get<std::string>();
        if (!get(entry, "model").is_null()) data_structure.model = entry["model"].get<std::string>();
        data_structure.extras = get(entry, "extras", json::object());
        if (entry.contains("origin")) {
            const auto values = entry["origin"].get<std::vector<double>>();
            if (values.size() != 16) throw Error("data structure '" + data_structure.id + "': an origin of 16 numbers");
            for (int row = 0; row < 4; ++row)
                for (int column = 0; column < 4; ++column)
                    data_structure.origin[row * 4 + column] = values[column * 4 + row];
        }
        std::map<std::int64_t, std::string> tables;
        for (const auto &item : get(entry, "entitySets", json::array())) {
            EntitySet set;
            if (!get(item, "rank").is_null()) set.rank = item["rank"].get<std::int64_t>();
            table(item.at("propertyTable").get<std::int64_t>(), set);
            tables[item["propertyTable"].get<std::int64_t>()] = item.at("name").get<std::string>();
            data_structure.entity_sets.push_back(std::move(set));
        }
        for (const auto &item : get(entry, "relations", json::array())) {
            Relation relation("", item.at("sourceSet").get<std::string>(), item.at("targetSet").get<std::string>());
            table(item.at("propertyTable").get<std::int64_t>(), relation);
            data_structure.relations.push_back(std::move(relation));
        }
        if (entry.contains("scalars")) {
            Table scalars;
            table(entry["scalars"].get<std::int64_t>(), scalars);
            data_structure.scalars = std::move(scalars);
        }
        if (entry.contains("grid")) {
            const json &item = entry["grid"];
            Grid grid;
            grid.kind = item.at("kind").get<std::string>();
            grid.shape = item.at("shape").get<std::vector<std::int64_t>>();
            grid.origin = item.at("origin").get<std::vector<double>>();
            grid.spacing = item.at("spacing").get<std::vector<double>>();
            grid.axes = item.at("axes").get<std::vector<std::string>>();
            grid.periodic = item.at("periodic").get<std::vector<bool>>();
            grid.z_up = get(item, "zUp", true).get<bool>();
            grid.max_level = get(item, "maxLevel", 0).get<std::int64_t>();
            grid.cells = item.at("cells").get<std::string>();
            data_structure.grid = std::move(grid);
        }
        for (const auto &mesh_entry : get(entry, "meshes", json::array()))
            data_structure.meshes.push_back(decode_mesh(document, binary, mesh_entry, tables));
        frame.data_structures.push_back(std::move(data_structure));
    }
    for (const auto &entry : get(scene, "mappings", json::array())) {
        Mapping mapping("", {entry.at("source").at("dataStructure").get<std::string>(),
                             entry.at("source").at("entitySet").get<std::string>()},
                        {entry.at("target").at("dataStructure").get<std::string>(),
                         entry.at("target").at("entitySet").get<std::string>()});
        if (!get(entry, "method").is_null()) mapping.method = entry["method"].get<std::string>();
        table(entry.at("propertyTable").get<std::int64_t>(), mapping);
        frame.mappings.push_back(std::move(mapping));
    }
    json other_extensions = json::object();
    for (const auto &item : extensions.items())
        if (item.key() != METADATA && item.key() != EXTENSION && item.key() != FEATURES)
            other_extensions[item.key()] = item.value();
    if (!other_extensions.empty()) frame.unknown["extensions"] = other_extensions;
    if (document.contains("extras")) frame.unknown["extras"] = document["extras"];
    return frame;
}

Frame read_frame(const std::string &path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw Error("cannot read '" + path + "'");
    std::vector<std::uint8_t> data((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    return from_bytes(data);
}

} // namespace fspm_tf
