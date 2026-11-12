#include "encoding3d/model.hpp"

#include <algorithm>
#include <numeric>

namespace encoding3d {

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
const std::vector<std::string> ENTITY_SET_RESERVED = {"id",        "label", "complex", "parent", "edge_type",
                                                     "level",     "index", "sibling_order"};
const std::vector<std::string> RELATION_RESERVED = {"id", "source", "target", "relation"};
const std::vector<std::string> MAPPING_RESERVED = {"source", "target", "weight"};
const std::vector<std::string> INSTANCE_SET_RESERVED = {"id", "owner", "template", "transform"};

std::string joined(const std::vector<std::string> &items) {
    std::string text;
    for (const auto &item : items) text += (text.empty() ? "" : ", ") + item;
    return text.empty() ? "-" : text;
}

} // namespace

MissingPartError::MissingPartError(std::string part_key, std::vector<std::string> looked_at)
    : Error("the shared part " + part_key + " is missing (looked for " + joined(looked_at) +
            "): copy the sequence's parts/ folder with its frames, or write the frame with its parts embedded"),
      key(std::move(part_key)), looked(std::move(looked_at)) {}

bool Column::has_missing() const {
    for (const bool flag : missing)
        if (flag) return true;
    return false;
}

std::string Column::dtype() const {
    return std::visit([](const auto &column_values) -> std::string {
        using T = typename std::decay_t<decltype(column_values)>::value_type;
        return TypeName<T>::value;
    }, values);
}

bool Variable::operator==(const Variable &other) const {
    return unit == other.unit && standard_name == other.standard_name && kind == other.kind && role == other.role &&
           description == other.description && minimum == other.minimum && maximum == other.maximum &&
           references == other.references && doi == other.doi && format == other.format;
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
    case TableKind::instance_set: return INSTANCE_SET_RESERVED;
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
        if (!item.second.missing.empty() && item.second.missing.size() != item.second.rows())
            throw Error("column '" + item.first + "' of '" + name + "': one missing flag per row");
        if (item.second.has_missing() && (is_reserved(item.first) || item.second.width != 1))
            throw Error("column '" + item.first + "' of '" + name + "': missing values only in variables of one value "
                        "per row");
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

const InstanceSet &DataStructure::instance_set(const std::string &name) const {
    for (const auto &candidate : instance_sets)
        if (candidate.name == name) return candidate;
    throw Error("data structure '" + id + "' has no instance set '" + name + "'");
}

InstanceSet &DataStructure::instance_set(const std::string &name) {
    return const_cast<InstanceSet &>(static_cast<const DataStructure &>(*this).instance_set(name));
}

Ragged Ragged::of(const std::vector<std::vector<double>> &vectors) {
    Ragged ragged;
    for (const auto &values : vectors) {
        ragged.values.insert(ragged.values.end(), values.begin(), values.end());
        ragged.counts.push_back(static_cast<std::int64_t>(values.size()));
    }
    return ragged;
}

std::vector<std::size_t> Ragged::offsets() const {
    std::vector<std::size_t> starts(counts.size() + 1, 0);
    for (std::size_t row = 0; row < counts.size(); ++row) {
        if (counts[row] < 0) throw Error("a ragged array's counts are not negative");
        starts[row + 1] = starts[row] + static_cast<std::size_t>(counts[row]);
    }
    if (starts.back() != values.size())
        throw Error("a ragged array's counts sum to " + std::to_string(starts.back()) + ", it holds " +
                    std::to_string(values.size()) + " values");
    return starts;
}

std::vector<double> Ragged::at(std::size_t row) const {
    std::size_t start = 0;
    for (std::size_t before = 0; before < row; ++before) start += static_cast<std::size_t>(counts.at(before));
    const auto count = static_cast<std::size_t>(counts.at(row));
    if (start + count > values.size()) throw Error("a ragged array's counts run past its values");
    return {values.begin() + static_cast<std::ptrdiff_t>(start),
            values.begin() + static_cast<std::ptrdiff_t>(start + count)};
}

const Ragged &InstanceSet::vector(const std::string &vector_name) const {
    for (const auto &[candidate, ragged] : vectors)
        if (candidate == vector_name) return ragged;
    throw Error("instance set '" + name + "' has no vector '" + vector_name + "'");
}

const DerivedField &InstanceSet::derived_field(const std::string &field_name) const {
    for (const auto &candidate : derived)
        if (candidate.name == field_name) return candidate;
    throw Error("instance set '" + name + "' has no derived field '" + field_name + "'");
}

std::array<double, 16> InstanceSet::transform(std::size_t row) const {
    std::array<double, 16> matrix = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    if (!has_column("transform")) return matrix;
    const auto &values = column("transform").as<double>();
    for (std::size_t item = 0; item < 16; ++item) matrix[item] = values.at(row * 16 + item);
    return matrix;
}

Operator Operator::dense(std::size_t rows, std::size_t columns, std::vector<double> row_by_row) {
    if (row_by_row.size() != rows * columns) throw Error("a dense operator holds rows × columns values");
    Operator made;
    made.format = "dense";
    made.rows = rows;
    made.columns = columns;
    made.values = std::move(row_by_row);
    return made;
}

Operator Operator::csr(std::size_t rows, std::size_t columns, SparseMatrix matrix) {
    if (matrix.indptr.size() != rows + 1) throw Error("a csr operator's indptr holds rows + 1 values");
    Operator made;
    made.format = "csr";
    made.rows = rows;
    made.columns = columns;
    made.sparse = std::move(matrix);
    return made;
}

Operator Operator::solve(std::size_t rows, std::size_t columns, SparseMatrix system, SparseMatrix right_hand_side) {
    if (system.indptr.size() != rows + 1 || right_hand_side.indptr.size() != rows + 1)
        throw Error("a solve operator's system and right-hand side have rows + 1 indptr values");
    Operator made;
    made.format = "solve";
    made.rows = rows;
    made.columns = columns;
    made.system = std::move(system);
    made.right_hand_side = std::move(right_hand_side);
    return made;
}

} // namespace encoding3d
