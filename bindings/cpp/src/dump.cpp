// A frame as plain JSON values, in the layout of the conformance files' expected values (conformance/README.md), and
// the comparison `fspm-tf compare` makes.
#include "fspm_tf/fspm_tf.hpp"

#include <cmath>
#include <type_traits>

namespace fspm_tf {

namespace {

template <typename T> json value_json(T value) {
    if constexpr (std::is_floating_point_v<T>) {
        if (std::isnan(value)) return nullptr;
        if (std::isinf(value)) return value > 0 ? "Infinity" : "-Infinity";
        return static_cast<double>(value);
    } else {
        return value;
    }
}

json column_json(const Column &column) {
    return std::visit([&](const auto &values) {
        json items = json::array();
        if (column.width == 1) {
            for (std::size_t item = 0; item < values.size(); ++item)
                items.push_back(column.is_missing(item) ? json(nullptr) : value_json(values[item]));   // missing: null
            return items;
        }
        for (std::size_t row = 0; row < column.rows(); ++row) {
            json vector = json::array();
            for (std::size_t component = 0; component < column.width; ++component)
                vector.push_back(value_json(values[row * column.width + component]));
            items.push_back(vector);
        }
        return items;
    }, column.values);
}

json table_json(const Table &table) {
    json columns = json::object();
    for (const auto &[name, column] : table.columns)
        columns[name] = {{"dtype", column.dtype()}, {"values", column_json(column)}};
    json entry = {{"name", table.name}, {"count", table.row_count()}, {"columns", columns}};
    json declarations = json::object();
    for (const auto &[name, variable] : table.variables) {
        json declared = {{"unit", variable.unit}, {"role", variable.role}};
        if (variable.standard_name) declared["standard_name"] = *variable.standard_name;
        if (variable.kind) declared["kind"] = *variable.kind;
        if (variable.description) declared["description"] = *variable.description;
        if (variable.minimum) declared["minimum"] = *variable.minimum;
        if (variable.maximum) declared["maximum"] = *variable.maximum;
        if (!variable.references.empty()) declared["references"] = variable.references;
        if (!variable.doi.empty()) declared["doi"] = variable.doi;
        if (variable.format) declared["format"] = *variable.format;
        declarations[name] = declared;
    }
    if (!declarations.empty()) entry["variables"] = declarations;
    return entry;
}

bool is_number(const json &value) { return value.is_number(); }

} // namespace

json frame_to_json(const Frame &frame) {
    json data_structures = json::array();
    for (const auto &data_structure : frame.data_structures) {
        json origin = json::array();
        for (int row = 0; row < 4; ++row)
            origin.push_back({data_structure.origin[row * 4], data_structure.origin[row * 4 + 1],
                              data_structure.origin[row * 4 + 2], data_structure.origin[row * 4 + 3]});
        json sets = json::array();
        for (const auto &set : data_structure.entity_sets) {
            json item = table_json(set);
            item["rank"] = set.rank ? json(*set.rank) : json(nullptr);
            if (set.scale) item["scale"] = *set.scale;
            sets.push_back(item);
        }
        json entry = {{"id", data_structure.id}, {"kind", data_structure.kind}, {"origin", origin},
                      {"entity_sets", sets}};
        if (data_structure.platform) entry["platform"] = *data_structure.platform;
        if (data_structure.model) entry["model"] = *data_structure.model;
        if (!data_structure.extras.empty()) entry["extras"] = data_structure.extras;
        if (!data_structure.labels.empty()) {
            json labels = json::object();
            for (const auto &[label, standard] : data_structure.labels) labels[label] = standard;
            entry["labels"] = labels;
        }
        if (!data_structure.relations.empty()) {
            json relations = json::array();
            for (const auto &relation : data_structure.relations) {
                json item = table_json(relation);
                item["source_set"] = relation.source_set;
                item["target_set"] = relation.target_set;
                relations.push_back(item);
            }
            entry["relations"] = relations;
        }
        if (data_structure.scalars) entry["scalars"] = table_json(*data_structure.scalars);
        if (data_structure.grid) {
            const Grid &grid = *data_structure.grid;
            entry["grid"] = {{"kind", grid.kind}, {"shape", grid.shape}, {"origin", grid.origin},
                             {"spacing", grid.spacing}, {"axes", grid.axes}, {"periodic", grid.periodic},
                             {"z_up", grid.z_up}, {"max_level", grid.max_level}, {"cells", grid.cells}};
        }
        if (!data_structure.meshes.empty()) {
            json meshes = json::array();
            for (const auto &mesh : data_structure.meshes) {
                json positions = json::array();
                for (std::size_t vertex = 0; vertex < mesh.vertex_count(); ++vertex)
                    positions.push_back({static_cast<double>(static_cast<float>(mesh.positions[vertex * 3])),
                                         static_cast<double>(static_cast<float>(mesh.positions[vertex * 3 + 1])),
                                         static_cast<double>(static_cast<float>(mesh.positions[vertex * 3 + 2]))});
                json feature_rows = json::object();
                for (const auto &[name, rows] : mesh.feature_rows) feature_rows[name] = rows;
                json item = {{"name", mesh.name}, {"positions_float32", positions}, {"feature_rows", feature_rows}};
                if (mesh.indices) item["indices"] = *mesh.indices;
                if (!mesh.display.empty()) {
                    json display = json::object();
                    for (const auto &[name, values] : mesh.display) display[name] = column_json(Column(values));
                    item["display"] = display;
                }
                meshes.push_back(item);
            }
            entry["meshes"] = meshes;
        }
        data_structures.push_back(entry);
    }
    json mappings = json::array();
    for (const auto &mapping : frame.mappings) {
        json item = table_json(mapping);
        item["source"] = {mapping.source.first, mapping.source.second};
        item["target"] = {mapping.target.first, mapping.target.second};
        item["method"] = mapping.method ? json(*mapping.method) : json(nullptr);
        mappings.push_back(item);
    }
    return {{"time", frame.time}, {"time_unit", frame.time_unit}, {"step", frame.step},
            {"data_structures", data_structures}, {"mappings", mappings}};
}

std::vector<std::string> compare(const json &actual, const json &expected, const std::string &path) {
    std::vector<std::string> found;
    if (expected.is_object()) {
        if (!actual.is_object()) return {path + ": an object expected"};
        for (const auto &item : expected.items())
            if (!actual.contains(item.key())) found.push_back(path + ": missing key '" + item.key() + "'");
        for (const auto &item : actual.items())
            if (!expected.contains(item.key())) found.push_back(path + ": unexpected key '" + item.key() + "'");
        for (const auto &item : expected.items())
            if (actual.contains(item.key())) {
                auto more = compare(actual[item.key()], item.value(), path + "." + item.key());
                found.insert(found.end(), more.begin(), more.end());
            }
        return found;
    }
    if (expected.is_array()) {
        if (!actual.is_array()) return {path + ": an array expected"};
        if (actual.size() != expected.size())
            return {path + ": " + std::to_string(actual.size()) + " items, " + std::to_string(expected.size()) +
                    " expected"};
        for (std::size_t item = 0; item < expected.size(); ++item) {
            auto more = compare(actual[item], expected[item], path + "[" + std::to_string(item) + "]");
            found.insert(found.end(), more.begin(), more.end());
        }
        return found;
    }
    if (is_number(expected)) {
        if (is_number(actual) && actual.get<double>() == expected.get<double>()) return {};
        return {path + ": " + actual.dump() + ", " + expected.dump() + " expected"};
    }
    if (actual != expected) return {path + ": " + actual.dump() + ", " + expected.dump() + " expected"};
    return {};
}

} // namespace fspm_tf
