// The fspm-TF data model: a frame's data structures, their tables (columns of equal length), grids and meshes.
//
//     Frame              one time step of a scene
//       DataStructure    one plant population's graph, or one environment model's grid
//         EntitySet      the entities of one scale (or a grid's cells): a table of columns
//         Relation       an edge table between entity sets (cell adjacency, a branch's bearer, ...)
//         Table          the data structure's scalars: a table of one row
//         Grid           a regular or adaptive grid's layout
//         Mesh           triangles, each vertex carrying the row of its entity in one or several entity sets
//       Mapping          source entity <-> target entity weights between two data structures
//
// A column holds one value per row (numbers, booleans, text), or a fixed-size vector per row (`width` values per
// row, row after row).
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include <nlohmann/json.hpp>

namespace fspm_tf {

using json = nlohmann::ordered_json;

/// The version of the specification this library reads and writes.
inline constexpr const char *SPECIFICATION_VERSION = "0.1";
/// The id of no entity: the complex or parent of an entity that has none, the feature row of a vertex with none.
inline constexpr std::int64_t NO_ID = -1;
/// The values of edge_type: the root of its scale, MTG '<', MTG '+'.
inline const std::vector<std::string> EDGE_TYPES = {"none", "successor", "branch"};

/// What the specification forbids, or a file that is not fspm-TF.
struct Error : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// The values of a column: one vector per element type. Booleans are std::vector<bool>; text, labels and edge types
/// std::vector<std::string>.
using ColumnValues = std::variant<std::vector<std::int8_t>, std::vector<std::uint8_t>, std::vector<std::int16_t>,
                                  std::vector<std::uint16_t>, std::vector<std::int32_t>, std::vector<std::uint32_t>,
                                  std::vector<std::int64_t>, std::vector<std::uint64_t>, std::vector<float>,
                                  std::vector<double>, std::vector<bool>, std::vector<std::string>>;

/// A column: its values, `width` per row (1: one value per row; >= 2: a fixed-size vector per row).
struct Column {
    ColumnValues values;
    std::size_t width = 1;

    Column() : values(std::vector<double>{}) {}
    template <typename T> Column(std::vector<T> column_values, std::size_t width = 1)
        : values(std::move(column_values)), width(width) {}
    Column(std::initializer_list<const char *> text) : values(std::vector<std::string>(text.begin(), text.end())) {}

    /// The number of values (rows × width).
    std::size_t size() const;
    /// The number of rows.
    std::size_t rows() const { return width == 0 ? 0 : size() / width; }
    /// The values as a vector of T (throws Error when the column holds another type).
    template <typename T> const std::vector<T> &as() const {
        if (auto found = std::get_if<std::vector<T>>(&values)) return *found;
        throw Error("a column of another type than the one asked for");
    }
    template <typename T> std::vector<T> &as() {
        if (auto found = std::get_if<std::vector<T>>(&values)) return *found;
        throw Error("a column of another type than the one asked for");
    }
    template <typename T> bool holds() const { return std::holds_alternative<std::vector<T>>(values); }
    /// The column's type name in the conformance files' expected values: numpy's (float64, int64, bool...), or
    /// "string".
    std::string dtype() const;
};

/// The declaration of a variable (a column): its unit (a UCUM code), its standard name in the vocabulary, its kind
/// (extensive, intensive, ...: how it maps between scales and grids), its role and its provenance.
struct Variable {
    std::string unit = "1";
    std::optional<std::string> standard_name;
    std::optional<std::string> kind;
    std::string role = "state";
    std::optional<std::string> description;
    std::optional<double> minimum;
    std::optional<double> maximum;
    std::vector<std::string> references;
    std::vector<std::string> doi;

    bool operator==(const Variable &other) const;
};

enum class TableKind { scalars, entity_set, relation, mapping };

/// Columns of equal length, in their order, and the declarations of its variables.
struct Table {
    std::string name;
    std::vector<std::pair<std::string, Column>> columns;
    std::map<std::string, Variable> variables;
    TableKind table_kind = TableKind::scalars;

    Table() = default;
    explicit Table(std::string name, TableKind kind = TableKind::scalars) : name(std::move(name)), table_kind(kind) {}

    /// The number of rows (0 without columns).
    std::size_t row_count() const;
    bool has_column(const std::string &column_name) const;
    const Column &column(const std::string &column_name) const;
    Column &column(const std::string &column_name);
    /// Sets the column `column_name`, replacing it or appending it; returns the table, for chaining.
    Table &set(const std::string &column_name, Column values);
    /// Declares the variable `column_name`.
    Table &declare(const std::string &column_name, Variable variable);
    /// The columns whose meaning the specification fixes, for this kind of table.
    const std::vector<std::string> &reserved() const;
    bool is_reserved(const std::string &column_name) const;
    /// The names of the variable columns (the columns but the reserved ones).
    std::vector<std::string> variable_names() const;
    /// Throws Error when columns have different numbers of rows.
    void check_lengths() const;
};

/// The entities of one scale of a graph (rank: the scale's rank, coarser first), or a grid's cells (no rank).
/// Reserved columns: id (int64, stable across frames, never reused), label (text), complex (the id of the containing
/// entity at a coarser scale, NO_ID if none), parent (the predecessor's id at the same scale, NO_ID if none),
/// edge_type ("none", "successor", "branch"); an adaptive grid's cells: level and index.
struct EntitySet : Table {
    std::optional<std::int64_t> rank;

    EntitySet() : Table("", TableKind::entity_set) {}
    explicit EntitySet(std::string name, std::optional<std::int64_t> rank = std::nullopt)
        : Table(std::move(name), TableKind::entity_set), rank(rank) {}
    /// The ids of its entities: its id column, or a grid's row numbers (from 0) when it has none.
    std::vector<std::int64_t> ids() const;
};

/// An edge table: source and target entity ids (in the entity sets source_set and target_set), an optional id per
/// edge, an optional relation label per edge, and edge variables.
struct Relation : Table {
    std::string source_set;
    std::string target_set;

    Relation() : Table("", TableKind::relation) {}
    Relation(std::string name, std::string source_set, std::string target_set)
        : Table(std::move(name), TableKind::relation), source_set(std::move(source_set)),
          target_set(std::move(target_set)) {}
};

/// Weights between the entities of two data structures: source and target ids, weight. source and target: (data
/// structure id, entity set name).
struct Mapping : Table {
    std::pair<std::string, std::string> source;
    std::pair<std::string, std::string> target;
    std::optional<std::string> method;

    Mapping() : Table("", TableKind::mapping) {}
    Mapping(std::string name, std::pair<std::string, std::string> source, std::pair<std::string, std::string> target,
            std::optional<std::string> method = std::nullopt)
        : Table(std::move(name), TableKind::mapping), source(std::move(source)), target(std::move(target)),
          method(std::move(method)) {}
};

/// A grid's layout. Regular: shape cells of size spacing from origin, along axes, periodic per axis, z pointing up or
/// down (z_up). Adaptive: the same for its base level, refined up to max_level, its leaf cells (an entity set with
/// level and index columns) explicit. cells: the name of the cells' entity set.
struct Grid {
    std::string kind = "regular";
    std::vector<std::int64_t> shape;
    std::vector<double> origin;
    std::vector<double> spacing;
    std::vector<std::string> axes = {"x", "y", "z"};
    std::vector<bool> periodic;
    bool z_up = true;
    std::int64_t max_level = 0;
    std::string cells = "Cell";
};

/// Triangles: positions (3 per vertex, in the data structure's frame), three consecutive vertices per triangle, or
/// indices (3 per triangle, from 0) into them; feature_rows: per entity set, the row (from 0) of each vertex's
/// entity in that set, NO_ID for none; display: per variable, its float copy per vertex, from the entity set
/// display_sources[variable].
struct Mesh {
    std::string name;
    std::vector<double> positions;
    std::vector<std::pair<std::string, std::vector<std::int64_t>>> feature_rows;
    std::optional<std::vector<std::int64_t>> indices;
    std::vector<std::pair<std::string, std::vector<float>>> display;
    std::map<std::string, std::string> display_sources;

    std::size_t vertex_count() const { return positions.size() / 3; }
};

/// One plant population's graph, or one environment model's grid. origin: its frame in the scene, a 4×4 matrix row
/// by row. extras: JSON values for the writing platform (e.g. what it needs to rebuild its own data structure);
/// other readers keep them without interpreting them.
struct DataStructure {
    std::string id;
    std::string kind = "graph";
    std::vector<EntitySet> entity_sets;
    std::vector<Relation> relations;
    std::optional<Table> scalars;
    std::optional<Grid> grid;
    std::vector<Mesh> meshes;
    std::array<double, 16> origin = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    std::optional<std::string> platform;
    std::optional<std::string> model;
    json extras = json::object();

    DataStructure() = default;
    explicit DataStructure(std::string id, std::string kind = "graph") : id(std::move(id)), kind(std::move(kind)) {}
    const EntitySet &entity_set(const std::string &name) const;
    EntitySet &entity_set(const std::string &name);
};

/// A scene at one time step (time in time_unit, step), or a parameter set. unknown: the content of a read file this
/// library does not interpret (other root extensions, the root's extras), written back as it was.
struct Frame {
    std::vector<DataStructure> data_structures;
    std::vector<Mapping> mappings;
    double time = 0.0;
    std::string time_unit = "d";
    std::int64_t step = 0;
    json writer = json::object();
    std::optional<std::string> vocabulary_version;
    json unknown = json::object();

    const DataStructure &data_structure(const std::string &id) const;
    DataStructure &data_structure(const std::string &id);
};

} // namespace fspm_tf
