#include "fspm_tf/model.hpp"

#include <algorithm>
#include <numeric>

namespace fspm_tf {

std::size_t Column::size() const {
    return std::visit([](const auto &column_values) { return column_values.size(); }, values);
}

namespace {

template <typename T> struct TypeName;
template <> struct TypeName<std::int8_t> { static constexpr const char *value = "int8"; };
template <> struct TypeName<std::uint8_t> { static constexpr const char *value = "uint8"; };
template <> struct TypeName<std::int16_t> { static constexpr const char *value = "int16"; };
template <> struct TypeName<std::uint16_t> { static constexpr const char *value = "uint16"; };
template <> struct TypeName<std::int32_t> { static constexpr const char *value = "int32"; };
template <> struct TypeName<std::uint32_t> { static constexpr const char *value = "uint32"; };
template <> struct TypeName<std::int64_t> { static constexpr const char *value = "int64"; };
template <> struct TypeName<std::uint64_t> { static constexpr const char *value = "uint64"; };
template <> struct TypeName<float> { static constexpr const char *value = "float32"; };
template <> struct TypeName<double> { static constexpr const char *value = "float64"; };
template <> struct TypeName<bool> { static constexpr const char *value = "bool"; };
template <> struct TypeName<std::string> { static constexpr const char *value = "string"; };

const std::vector<std::string> NO_RESERVED = {};
const std::vector<std::string> ENTITY_SET_RESERVED = {"id", "label", "complex", "parent", "edge_type", "level", "index"};
const std::vector<std::string> RELATION_RESERVED = {"id", "source", "target", "relation"};
const std::vector<std::string> MAPPING_RESERVED = {"source", "target", "weight"};

} // namespace

std::string Column::dtype() const {
    return std::visit([](const auto &column_values) -> std::string {
        using T = typename std::decay_t<decltype(column_values)>::value_type;
        return TypeName<T>::value;
    }, values);
}

bool Variable::operator==(const Variable &other) const {
    return unit == other.unit && standard_name == other.standard_name && kind == other.kind && role == other.role &&
           description == other.description && minimum == other.minimum && maximum == other.maximum &&
           references == other.references && doi == other.doi;
}

std::size_t Table::row_count() const { return columns.empty() ? 0 : columns.front().second.rows(); }

bool Table::has_column(const std::string &column_name) const {
    return std::any_of(columns.begin(), columns.end(), [&](const auto &item) { return item.first == column_name; });
}

const Column &Table::column(const std::string &column_name) const {
    for (const auto &item : columns)
        if (item.first == column_name) return item.second;
    throw Error("table '" + name + "' has no column '" + column_name + "'");
}

Column &Table::column(const std::string &column_name) {
    return const_cast<Column &>(static_cast<const Table &>(*this).column(column_name));
}

Table &Table::set(const std::string &column_name, Column values) {
    for (auto &item : columns)
        if (item.first == column_name) {
            item.second = std::move(values);
            return *this;
        }
    columns.emplace_back(column_name, std::move(values));
    return *this;
}

Table &Table::declare(const std::string &column_name, Variable variable) {
    variables[column_name] = std::move(variable);
    return *this;
}

const std::vector<std::string> &Table::reserved() const {
    switch (table_kind) {
    case TableKind::entity_set: return ENTITY_SET_RESERVED;
    case TableKind::relation: return RELATION_RESERVED;
    case TableKind::mapping: return MAPPING_RESERVED;
    default: return NO_RESERVED;
    }
}

bool Table::is_reserved(const std::string &column_name) const {
    const auto &names = reserved();
    return std::find(names.begin(), names.end(), column_name) != names.end();
}

std::vector<std::string> Table::variable_names() const {
    std::vector<std::string> names;
    for (const auto &item : columns)
        if (!is_reserved(item.first)) names.push_back(item.first);
    return names;
}

void Table::check_lengths() const {
    for (const auto &item : columns) {
        if (item.second.width == 0 || item.second.size() % item.second.width != 0)
            throw Error("column '" + item.first + "' of '" + name + "': its values are not whole rows");
        if (item.second.rows() != row_count())
            throw Error("table '" + name + "': columns of different lengths");
    }
}

std::vector<std::int64_t> EntitySet::ids() const {
    if (has_column("id")) return column("id").as<std::int64_t>();
    std::vector<std::int64_t> rows(row_count());
    std::iota(rows.begin(), rows.end(), 0);
    return rows;
}

const EntitySet &DataStructure::entity_set(const std::string &name) const {
    for (const auto &candidate : entity_sets)
        if (candidate.name == name) return candidate;
    throw Error("data structure '" + id + "' has no entity set '" + name + "'");
}

EntitySet &DataStructure::entity_set(const std::string &name) {
    return const_cast<EntitySet &>(static_cast<const DataStructure &>(*this).entity_set(name));
}

const DataStructure &Frame::data_structure(const std::string &id) const {
    for (const auto &candidate : data_structures)
        if (candidate.id == id) return candidate;
    throw Error("the frame has no data structure '" + id + "'");
}

DataStructure &Frame::data_structure(const std::string &id) {
    return const_cast<DataStructure &>(static_cast<const Frame &>(*this).data_structure(id));
}

} // namespace fspm_tf
