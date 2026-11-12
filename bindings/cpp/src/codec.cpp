// Reading and writing frames as GLB files. Tables are EXT_structural_metadata property tables (one class per table),
// meshes carry EXT_mesh_features feature IDs, and the FSPM_scene root extension holds what these two cannot: data
// structures, entity sets and their ranks, relations, grids, mappings, the frame's time, and the variables' units,
// standard names, kinds and roles.
#include "encoding3d/encoding3d.hpp"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iterator>
#include <limits>
#include <map>
#include <regex>
#include <set>
#include <type_traits>

#include "bytes.hpp"

namespace encoding3d {

namespace {

const std::string EXTENSION = "FSPM_scene";
const std::string METADATA = "EXT_structural_metadata";
const std::string FEATURES = "EXT_mesh_features";
const std::string EDGE_TYPE_ENUM = "FSPM_edge_type";
const std::vector<std::string> ENUM_COLUMNS = {"label", "edge_type", "relation"};
const std::vector<std::string> ID_COLUMNS = {"id", "complex", "parent", "source", "target", "level", "index",
                                             "sibling_order"};
constexpr std::uint8_t BOOLEAN_NO_DATA = 255;   // a boolean column with missing values: UINT8 0, 1, and 255 missing
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

/// A value of T the column does not hold: its minimum (signed) or maximum (unsigned) first, then inwards.
template <typename T> T free_integer(const std::vector<T> &values, const std::vector<bool> &missing) {
    std::set<T> present;
    for (std::size_t row = 0; row < values.size(); ++row)
        if (missing.empty() || !missing[row]) present.insert(values[row]);
    const T first = std::is_signed_v<T> ? std::numeric_limits<T>::min() : std::numeric_limits<T>::max();
    const T second = std::is_signed_v<T> ? std::numeric_limits<T>::max() : std::numeric_limits<T>::min();
    if (!present.count(first)) return first;
    if (!present.count(second)) return second;
    T candidate = first;
    while (present.count(candidate)) candidate = std::is_signed_v<T> ? T(candidate + 1) : T(candidate - 1);
    return candidate;
}

/// A string the column does not hold: the empty string first, then NUL characters.
std::string free_string(const std::vector<std::string> &values, const std::vector<bool> &missing) {
    std::set<std::string> present;
    for (std::size_t row = 0; row < values.size(); ++row)
        if (missing.empty() || !missing[row]) present.insert(values[row]);
    std::string candidate;
    while (present.count(candidate)) candidate.push_back('\0');
    return candidate;
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
    if (variable.format) declaration["format"] = *variable.format;
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
            std::vector<std::string> strings = column.as<std::string>();
            if (column.has_missing()) {                          // missing text: noData, a string the column lacks
                const std::string no_data = free_string(strings, column.missing);
                property["noData"] = no_data;
                for (std::size_t row = 0; row < strings.size(); ++row)
                    if (column.missing[row]) strings[row] = no_data;
            }
            std::vector<std::uint8_t> text;
            std::vector<std::uint64_t> offsets = {0};
            for (const auto &value : strings) {
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
        } else if (column.holds<bool>() && column.has_missing()) {   // booleans with missing values: UINT8 0, 1, 255
            property["type"] = "SCALAR";
            property["componentType"] = "UINT8";
            property["noData"] = BOOLEAN_NO_DATA;
            property["extras"] = {{"FSPM_boolean", true}};
            const auto &values = column.as<bool>();
            std::vector<std::uint8_t> codes(values.size());
            for (std::size_t row = 0; row < values.size(); ++row)
                codes[row] = column.missing[row] ? BOOLEAN_NO_DATA : std::uint8_t(values[row]);
            stored[name] = {{"values", buffers.add(codes)}};
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
                        if (reserved && (contains(ID_COLUMNS, name) ||       // ids are INT64, whatever the platform's
                                         table.table_kind == TableKind::instance_set)) {   // and template, owner
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
                        for (std::size_t row = 0; row < column.missing.size(); ++row)   // a missing float: NaN
                            if (column.missing[row]) data[row] = std::numeric_limits<T>::quiet_NaN();
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
                    } else if (column.has_missing()) {           // missing integers: noData, a value the column lacks
                        const T no_data = free_integer(data, column.missing);
                        property["noData"] = no_data;
                        for (std::size_t row = 0; row < data.size(); ++row)
                            if (column.missing[row]) data[row] = no_data;
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

/// The FSPM_scene entry of an instance set (specification §12.2), its tables added by `add_table`: the instance table
/// (its columns, each vector's <name>__count, each derived field's <name>__operator and <name>__weight) and one table
/// per vector (its values, the instances' one after the other).
json encode_instance_set(const InstanceSet &instance_set, const DataStructure &data_structure,
                         const std::function<std::int64_t(const Table &, const std::string &)> &add_table) {
    check_identifier(instance_set.name, "instance set name");
    const std::string where = "instance set '" + instance_set.name + "' of '" + data_structure.id + "'";
    if (!instance_set.has_column("template"))
        throw Error(where + ": no 'template' column (each instance's index in its parts)");
    const std::size_t count = instance_set.count();
    Table table = instance_set;                         // its columns, and those of its vectors and derived fields
    json entry = {{"name", instance_set.name}, {"parts", instance_set.parts}};
    if (instance_set.owners) entry["owners"] = *instance_set.owners;
    json vectors = json::array();
    for (const auto &[name, ragged] : instance_set.vectors) {
        check_identifier(name, "vector of " + where);
        ragged.offsets();                               // its counts checked against its values
        if (ragged.size() != count)
            throw Error(where + ": vector '" + name + "' has " + std::to_string(ragged.size()) + " instances, the set " +
                        std::to_string(count));
        table.set(name + "__count", Column(ragged.counts));
        Table values(name);
        values.set("values", Column(ragged.values));
        vectors.push_back({{"name", name},
                           {"propertyTable", add_table(values, data_structure.id + "__" + instance_set.name + "__" + name)}});
    }
    json derived_fields = json::array();
    for (const auto &derived : instance_set.derived) {
        check_identifier(derived.name, "derived field of " + where);
        if (derived.terms == 0 || derived.operators.size() != count * derived.terms ||
            derived.weights.size() != count * derived.terms)
            throw Error(where + ": derived field '" + derived.name + "' has not " + std::to_string(derived.terms) +
                        " operators and weights per instance");
        bool has_input = false;
        for (const auto &item : instance_set.vectors) has_input = has_input || item.first == derived.input;
        if (!has_input)
            throw Error(where + ": derived field '" + derived.name + "' applies to vector '" + derived.input +
                        "', which the set does not have");
        if (!derived.offsets.empty() && derived.offsets.size() != derived.terms)
            throw Error(where + ": derived field '" + derived.name + "' has not one offset per term");
        const std::size_t width = derived.terms == 1 ? 1 : derived.terms;
        table.set(derived.name + "__operator", Column(derived.operators, width));
        table.set(derived.name + "__weight", Column(derived.weights, width));
        json item = {{"name", derived.name}, {"entitySet", derived.entity_set}, {"input", derived.input},
                     {"terms", derived.terms}, {"variable", declaration_json(derived.variable)}};
        if (std::any_of(derived.offsets.begin(), derived.offsets.end(), [](const auto &offset) { return bool(offset); })) {
            json offsets = json::array();
            for (const auto &offset : derived.offsets) offsets.push_back(offset ? json(*offset) : json(nullptr));
            item["offsets"] = offsets;
        }
        if (derived.variable.description) item["description"] = *derived.variable.description;
        derived_fields.push_back(item);
    }
    entry["propertyTable"] = add_table(table, data_structure.id + "__" + instance_set.name);
    if (!vectors.empty()) entry["vectors"] = vectors;
    if (!derived_fields.empty()) entry["derivedFields"] = derived_fields;
    return entry;
}

/// Appends a buffer view to a builder (for the arrays of an operator part).
using PartEntry = std::function<json(BufferBuilder &)>;

std::vector<std::uint8_t> encode_frame(const Frame &frame, bool embed_parts, const PartEntry &part_entry);

} // namespace

// ── Writing ──────────────────────────────────────────────────────────────

std::vector<std::uint8_t> to_bytes(const Frame &frame, bool embed_parts) { return encode_frame(frame, embed_parts, {}); }

namespace {

std::vector<std::uint8_t> encode_frame(const Frame &frame, bool embed_parts, const PartEntry &part_entry) {
    BufferBuilder buffers;
    json edge_values = json::array();
    for (std::size_t value = 0; value < EDGE_TYPES.size(); ++value)
        edge_values.push_back({{"name", EDGE_TYPES[value]}, {"value", value}});
    json schema = {{"id", "fspm_scene"}, {"classes", json::object()},
                   {"enums", {{EDGE_TYPE_ENUM, {{"valueType", "UINT8"}, {"values", edge_values}}}}}};
    json tables = json::array(), variables = json::object();
    json document = {{"asset", {{"version", "2.0"}, {"generator", std::string("encoding3d (C++) ") + SPECIFICATION_VERSION}}},
                     {"scene", 0}, {"scenes", json::array({{{"nodes", json::array({0})}}})},
                     {"nodes", json::array({{{"name", "fspm_scene"}, {"matrix", Z_UP_TO_Y_UP},
                                             {"children", json::array()}}})}};
    json accessors = json::array(), meshes = json::array();

    const std::function<std::int64_t(const Table &, const std::string &)> add_table = [&](const Table &table,
                                                                                           const std::string &class_id) {
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
            if (set.scale) item["scale"] = *set.scale;
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
        if (!data_structure.labels.empty()) {
            json labels = json::object();
            for (const auto &[label, standard] : data_structure.labels) labels[label] = standard;
            entry["labels"] = labels;
        }
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
        if (!data_structure.instance_sets.empty()) {
            json instance_sets = json::array();
            for (const auto &instance_set : data_structure.instance_sets)
                instance_sets.push_back(encode_instance_set(instance_set, data_structure, add_table));
            entry["instanceSets"] = instance_sets;
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

    json update = nullptr;
    if (frame.update) {
        check_identifier(frame.update->participant, "participant");
        update = {{"participant", frame.update->participant}};
        if (!frame.update->removed.empty()) {
            json removed = json::array();
            for (const auto &[key, ids] : frame.update->removed) {
                Table table(key.second + "__removed");
                table.set("id", Column(ids));
                removed.push_back({{"dataStructure", key.first}, {"entitySet", key.second},
                                   {"propertyTable", add_table(table, key.first + "__" + key.second + "__removed")}});
            }
            update["removed"] = removed;
        }
    }

    json scene = {{"version", SPECIFICATION_VERSION},
                  {"frame", {{"time", frame.time}, {"timeUnit", frame.time_unit}, {"step", frame.step}}}};
    if (frame.vocabulary_version) scene["vocabulary"] = *frame.vocabulary_version;
    if (!frame.writer.empty()) scene["writer"] = frame.writer;
    if (!update.is_null()) scene["update"] = update;
    if (part_entry) scene["part"] = part_entry(buffers);
    scene["dataStructures"] = data_structures;
    if (!mappings.empty()) scene["mappings"] = mappings;
    if (!variables.empty()) scene["variables"] = variables;
    const auto keys = frame_part_keys(frame);
    if (embed_parts && !keys.empty()) {
        json embedded = json::object();
        for (const auto &key : keys) embedded[key] = {{"bufferView", buffers.add_bytes(frame_part_bytes(frame, key))}};
        scene["parts"] = embedded;
    }

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
    // a part, or a frame of no data structure: glTF has no empty children
    if (document["nodes"][0]["children"].empty()) document["nodes"][0].erase("children");
    if (!buffers.views.empty()) {
        // the buffer holds the chunk's padding to 8 bytes: glTF-Validator warns of more than 3 bytes beyond it
        buffers.data.resize(buffers.data.size() + detail::padding(buffers.data.size()), 0);
        document["buffers"] = json::array({{{"byteLength", buffers.data.size()}}});
        document["bufferViews"] = buffers.views;
    }
    return pack(document, buffers.data);
}

void write_bytes(const std::filesystem::path &path, const std::vector<std::uint8_t> &bytes) {
    std::ofstream file(path, std::ios::binary);
    if (!file) throw Error("cannot write '" + path.string() + "'");
    file.write(reinterpret_cast<const char *>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!file) throw Error("cannot write '" + path.string() + "'");
}

} // namespace

std::vector<std::string> write_frame(const std::string &path, const Frame &frame, bool embed_parts) {
    write_bytes(path, to_bytes(frame, embed_parts));
    const auto keys = frame_part_keys(frame);
    if (embed_parts) return keys;
    const auto folder = std::filesystem::absolute(std::filesystem::path(path)).parent_path() / "parts";
    for (const auto &key : keys) {
        const auto target = folder / (key + ".glb");
        if (std::filesystem::exists(target)) continue;          // its name is its hash: its content
        std::filesystem::create_directories(folder);
        const auto temporary = folder / (key + ".glb.part");
        write_bytes(temporary, frame_part_bytes(frame, key));
        std::filesystem::rename(temporary, target);             // a reader never sees half a part
    }
    return keys;
}

std::vector<std::string> frame_part_keys(const Frame &frame) {
    std::set<std::string> keys;
    for (const auto &data_structure : frame.data_structures)
        for (const auto &instance_set : data_structure.instance_sets)
            keys.insert(instance_set.parts.begin(), instance_set.parts.end());
    return {keys.begin(), keys.end()};
}

// ── Shared parts ─────────────────────────────────────────────────────────

std::vector<std::uint8_t> part_to_bytes(const Part &part) {
    if (const auto *template_part = std::get_if<Template>(&part)) {
        Frame frame;
        frame.data_structures.push_back(template_part->data_structure);
        for (auto &set : frame.data_structures[0].entity_sets)      // an entity set without ids: its rows
            if (!set.has_column("id") && !set.columns.empty()) {
                std::vector<std::int64_t> ids(set.row_count());
                for (std::size_t row = 0; row < ids.size(); ++row) ids[row] = static_cast<std::int64_t>(row);
                set.columns.insert(set.columns.begin(), {"id", Column(ids)});
            }
        return encode_frame(frame, false, [](BufferBuilder &) { return json{{"kind", "template"}}; });
    }
    const auto &operator_part = std::get<Operator>(part);
    return encode_frame(Frame(), false, [&](BufferBuilder &buffers) {
        json entry = {{"kind", "operator"}, {"format", operator_part.format}, {"rows", operator_part.rows},
                      {"columns", operator_part.columns}};
        auto sparse = [&](const SparseMatrix &matrix) {
            return json{{"indptr", buffers.add(matrix.indptr)}, {"indices", buffers.add(matrix.indices)},
                        {"values", buffers.add(matrix.values)}};
        };
        if (operator_part.format == "dense") {
            if (operator_part.values.size() != operator_part.rows * operator_part.columns)
                throw Error("a dense operator holds rows × columns values");
            entry["values"] = buffers.add(operator_part.values);
        } else if (operator_part.format == "csr") {
            entry.update(sparse(operator_part.sparse));
        } else if (operator_part.format == "solve") {
            entry["system"] = sparse(operator_part.system);
            entry["rightHandSide"] = sparse(operator_part.right_hand_side);
        } else {
            throw Error("operator format '" + operator_part.format + "': dense, csr or solve");
        }
        return entry;
    });
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
        throw Error("encoding3d files keep every buffer view in the GLB binary chunk");
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
    throw Error("component type " + component + " is not part of encoding3d 0.1");
}

std::vector<std::uint64_t> read_unsigned(const std::string &type, const ViewBytes &raw, std::size_t count) {
    std::vector<std::uint64_t> values;
    if (type == "UINT8") for (auto value : read_view<std::uint8_t>(raw, count)) values.push_back(value);
    else if (type == "UINT16") for (auto value : read_view<std::uint16_t>(raw, count)) values.push_back(value);
    else if (type == "UINT32") for (auto value : read_view<std::uint32_t>(raw, count)) values.push_back(value);
    else if (type == "UINT64") values = read_view<std::uint64_t>(raw, count);
    else throw Error("offsets or enum values of type " + type + " are not part of encoding3d 0.1");
    return values;
}

Variable variable_of(const json &declared, const json &description) {
    Variable variable;
    variable.unit = get(declared, "unit", "1").get<std::string>();
    variable.role = get(declared, "role", "state").get<std::string>();
    if (!get(declared, "standardName").is_null()) variable.standard_name = declared["standardName"].get<std::string>();
    if (!get(declared, "kind").is_null()) variable.kind = declared["kind"].get<std::string>();
    if (!description.is_null()) variable.description = description.get<std::string>();
    if (!get(declared, "minimum").is_null()) variable.minimum = declared["minimum"].get<double>();
    if (!get(declared, "maximum").is_null()) variable.maximum = declared["maximum"].get<double>();
    if (!get(declared, "format").is_null()) variable.format = declared["format"].get<std::string>();
    for (const auto &reference : get(declared, "references", json::array()))
        variable.references.push_back(reference.get<std::string>());
    for (const auto &doi : get(declared, "doi", json::array())) variable.doi.push_back(doi.get<std::string>());
    return variable;
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
            std::vector<bool> missing;
            if (property.contains("noData")) {                   // missing text
                const std::string no_data = property["noData"].get<std::string>();
                missing.assign(count, false);
                for (std::size_t row = 0; row < count; ++row)
                    if (text[row] == no_data) {
                        missing[row] = true;
                        text[row].clear();
                    }
                if (std::none_of(missing.begin(), missing.end(), [](bool flag) { return flag; })) missing.clear();
            }
            column = Column(std::move(text));
            column.missing = std::move(missing);
        } else if (type == "BOOLEAN") {
            if (raw.size * 8 < count) throw Error("'" + class_id + "." + name + "': too few bits");
            std::vector<bool> values(count);
            for (std::size_t row = 0; row < count; ++row) values[row] = (raw.data[row / 8] >> (row % 8)) & 1u;
            column = Column(std::move(values));
        } else if (type == "SCALAR") {
            const bool vector = get(property, "array", false).get<bool>();
            if (vector && !property.contains("count"))
                throw Error("'" + class_id + "." + name + "': variable-length arrays are not part of encoding3d 0.1");
            const std::size_t width = vector ? property["count"].get<std::size_t>() : 1;
            const std::string component = property.at("componentType").get<std::string>();
            column = decode_scalar_of(component, raw, property, count, width);
            if (get(get(property, "extras", json::object()), "FSPM_boolean", false).get<bool>()) {
                const auto codes = column.as<std::uint8_t>();        // booleans with missing values
                const auto no_data = get(property, "noData", BOOLEAN_NO_DATA).get<std::uint64_t>();
                std::vector<bool> values(count), missing(count);
                for (std::size_t row = 0; row < count; ++row) {
                    missing[row] = codes[row] == no_data;
                    values[row] = !missing[row] && codes[row] == 1;
                }
                column = Column(std::move(values));
                if (std::any_of(missing.begin(), missing.end(), [](bool flag) { return flag; })) column.missing = missing;
            } else if (width == 1 && component.rfind("FLOAT", 0) != 0 && property.contains("noData") &&
                       name != "complex" && name != "parent") {          // missing integers
                const double no_data = property["noData"].get<double>();
                std::vector<bool> missing(count);
                bool any = false;
                for (std::size_t row = 0; row < count; ++row) {
                    const double value = std::visit([&](const auto &values) -> double {
                        using V = typename std::decay_t<decltype(values)>::value_type;
                        if constexpr (std::is_arithmetic_v<V>) return static_cast<double>(values[row]);
                        else return 0.0;
                    }, column.values);
                    missing[row] = value == no_data;
                    any = any || missing[row];
                }
                if (any) column.missing = missing;
            }
        } else {
            throw Error("'" + class_id + "." + name + "': property type " + type + " is not part of encoding3d 0.1");
        }
        table.columns.emplace_back(name, std::move(column));
        const json declared = get(get(variables, class_id, json::object()), name);
        if (!declared.is_null() || property.contains("description"))
            table.variables[name] = variable_of(declared, get(property, "description"));
    }
}

/// The numbers of a column as doubles, or as int64 (whatever its numeric type).
template <typename T> std::vector<T> numbers_of(const Column &column, const std::string &where) {
    return std::visit([&](const auto &values) -> std::vector<T> {
        using V = typename std::decay_t<decltype(values)>::value_type;
        if constexpr (is_number_v<V>) return std::vector<T>(values.begin(), values.end());
        else throw Error(where + ": numbers expected");
    }, column.values);
}

/// Removes the column `name` from `table`, and its declaration; its values.
Column take_column(Table &table, const std::string &name, const std::string &where) {
    for (auto item = table.columns.begin(); item != table.columns.end(); ++item)
        if (item->first == name) {
            Column column = std::move(item->second);
            table.columns.erase(item);
            table.variables.erase(name);
            return column;
        }
    throw Error(where + ": no column '" + name + "'");
}

InstanceSet decode_instance_set(const json &item, const std::function<void(std::int64_t, Table &)> &table) {
    InstanceSet instance_set(item.at("name").get<std::string>());
    if (!get(item, "owners").is_null()) instance_set.owners = item["owners"].get<std::string>();
    table(item.at("propertyTable").get<std::int64_t>(), instance_set);
    instance_set.name = item.at("name").get<std::string>();
    const std::string where = "instance set '" + instance_set.name + "'";
    for (const auto &key : get(item, "parts", json::array())) instance_set.parts.push_back(key.get<std::string>());
    for (const auto &vector : get(item, "vectors", json::array())) {
        const std::string name = vector.at("name").get<std::string>();
        Table values;
        table(vector.at("propertyTable").get<std::int64_t>(), values);
        Ragged ragged(numbers_of<double>(values.column("values"), where + " vector '" + name + "'"),
                      numbers_of<std::int64_t>(take_column(instance_set, name + "__count", where), where));
        instance_set.vectors.emplace_back(name, std::move(ragged));
    }
    for (const auto &entry : get(item, "derivedFields", json::array())) {
        DerivedField derived;
        derived.name = entry.at("name").get<std::string>();
        derived.entity_set = entry.at("entitySet").get<std::string>();
        derived.input = entry.at("input").get<std::string>();
        derived.terms = get(entry, "terms", 1).get<std::size_t>();
        derived.variable = variable_of(get(entry, "variable", json::object()), get(entry, "description"));
        for (const auto &offset : get(entry, "offsets", json::array()))
            derived.offsets.push_back(offset.is_null() ? std::nullopt : std::optional<std::string>(offset.get<std::string>()));
        if (derived.offsets.empty()) derived.offsets.assign(derived.terms, std::nullopt);
        derived.operators = numbers_of<std::int64_t>(take_column(instance_set, derived.name + "__operator", where), where);
        derived.weights = numbers_of<double>(take_column(instance_set, derived.name + "__weight", where), where);
        if (derived.operators.size() != instance_set.count() * derived.terms ||
            derived.weights.size() != instance_set.count() * derived.terms || derived.offsets.size() != derived.terms)
            throw Error(where + ": derived field '" + derived.name + "' has not " + std::to_string(derived.terms) +
                        " operators, weights and offsets per instance");
        instance_set.derived.push_back(std::move(derived));
    }
    return instance_set;
}

template <typename T>
std::vector<T> accessor_values(const json &document, const std::vector<std::uint8_t> &binary, std::int64_t index,
                               std::size_t &width) {
    const json &accessor = document.at("accessors").at(static_cast<std::size_t>(index));
    const std::string type = accessor.at("type").get<std::string>();
    width = type == "SCALAR" ? 1 : type == "VEC2" ? 2 : type == "VEC3" ? 3 : type == "VEC4" ? 4 : 0;
    if (width == 0) throw Error("accessor type " + type + " is not used by encoding3d");
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
    throw Error("accessor component type " + std::to_string(component) + " is not used by encoding3d");
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

Frame from_bytes(const std::vector<std::uint8_t> &data, const std::string &parts_folder) {
    auto [document, binary] = unpack(data);
    const json extensions = get(document, "extensions", json::object());
    if (!extensions.contains(EXTENSION)) throw Error("not an encoding3d file: no " + EXTENSION + " extension");
    const json &scene = extensions[EXTENSION];
    const json metadata = get(extensions, METADATA, {{"schema", json::object()}, {"propertyTables", json::array()}});
    const json variables = get(scene, "variables", json::object());
    const std::function<void(std::int64_t, Table &)> table = [&](std::int64_t index, Table &target) {
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
        const json labels = get(entry, "labels", json::object());
        for (const auto &item : labels.items())
            data_structure.labels.emplace_back(item.key(), item.value().get<std::string>());
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
            if (!get(item, "scale").is_null()) set.scale = item["scale"].get<std::string>();
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
        for (const auto &item : get(entry, "instanceSets", json::array()))
            data_structure.instance_sets.push_back(decode_instance_set(item, table));
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
    if (scene.contains("update")) {
        Update update;
        update.participant = scene["update"].at("participant").get<std::string>();
        for (const auto &item : get(scene["update"], "removed", json::array())) {
            Table removed;
            table(item.at("propertyTable").get<std::int64_t>(), removed);
            update.removed[{item.at("dataStructure").get<std::string>(), item.at("entitySet").get<std::string>()}] =
                removed.column("id").as<std::int64_t>();
        }
        frame.update = std::move(update);
    }
    json other_extensions = json::object();
    for (const auto &item : extensions.items())
        if (item.key() != METADATA && item.key() != EXTENSION && item.key() != FEATURES)
            other_extensions[item.key()] = item.value();
    if (!other_extensions.empty()) frame.unknown["extensions"] = other_extensions;
    if (document.contains("extras")) frame.unknown["extras"] = document["extras"];
    const json embedded = get(scene, "parts", json::object());
    for (const auto &item : embedded.items()) {                       // embedded parts: a self-contained frame
        const auto raw = view_bytes(document, binary, item.value().at("bufferView").get<std::int64_t>());
        frame.part_bytes[item.key()] = std::vector<std::uint8_t>(raw.data, raw.data + raw.size);
    }
    frame.parts_folder = parts_folder;
    return frame;
}

Frame read_frame(const std::string &path) {
    return from_bytes(read_file_bytes(path), std::filesystem::path(path).parent_path().string());
}

Part read_part(const std::vector<std::uint8_t> &data, const std::string &key) {
    const std::string actual = content_key(data);
    if (!key.empty() && key != actual)
        throw Error("part " + key + ": its bytes hash to " + actual + " (the file is not the part its name says)");
    const auto unpacked = unpack(data);
    const json &document = unpacked.first;
    const std::vector<std::uint8_t> &binary = unpacked.second;
    const json described = get(get(get(document, "extensions", json::object()), EXTENSION, json::object()), "part");
    if (described.is_null()) throw Error("part " + actual + ": not a part (no " + EXTENSION + ".part)");
    const std::string kind = get(described, "kind", "").get<std::string>();
    if (kind == "template") {
        Frame frame = from_bytes(data);
        if (frame.data_structures.size() != 1) throw Error("part " + actual + ": a template holds one data structure");
        Template template_part;
        template_part.data_structure = std::move(frame.data_structures[0]);
        return template_part;
    }
    if (kind != "operator") throw Error("part " + actual + ": kind '" + kind + "' is not template or operator");
    auto array = [&](const json &index, auto tag) {
        using T = decltype(tag);
        const auto raw = view_bytes(document, binary, index.get<std::int64_t>());
        return read_view<T>(raw, raw.size / sizeof(T));
    };
    auto sparse = [&](const json &item) {
        return SparseMatrix{array(item.at("indptr"), std::int64_t{}), array(item.at("indices"), std::int64_t{}),
                            array(item.at("values"), double{})};
    };
    const auto rows = described.at("rows").get<std::size_t>(), columns = described.at("columns").get<std::size_t>();
    const std::string format = described.at("format").get<std::string>();
    if (format == "dense") return Operator::dense(rows, columns, array(described.at("values"), double{}));
    if (format == "csr") return Operator::csr(rows, columns, sparse(described));
    if (format == "solve")
        return Operator::solve(rows, columns, sparse(described.at("system")), sparse(described.at("rightHandSide")));
    throw Error("part " + actual + ": operator format '" + format + "' is not dense, csr or solve");
}

} // namespace encoding3d
