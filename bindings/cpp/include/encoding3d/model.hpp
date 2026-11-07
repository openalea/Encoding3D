// The encoding3d data model: a frame's data structures, their tables (columns of equal length), grids and meshes.
//
//     Frame              one time step of a scene
//       DataStructure    one plant population's graph, or one environment model's grid
//         EntitySet      the entities of one scale (or a grid's cells): a table of columns
//         Relation       an edge table between entity sets (cell adjacency, a branch's bearer, ...)
//         Table          the data structure's scalars: a table of one row
//         Grid           a regular or adaptive grid's layout
//         Mesh           triangles, each vertex carrying the row of its entity in one or several entity sets
//         InstanceSet    instances of shared templates (specification §12): a table of one row per instance, its
//                        vectors (Ragged) and derived fields (DerivedField)
//       Mapping          source entity <-> target entity weights between two data structures
//     Template, Operator the shared parts instance sets use, kept once per sequence and found by their key
//
// A column holds one value per row (numbers, booleans, text), or a fixed-size vector per row (`width` values per
// row, row after row). Missing values: NaN in float columns; elsewhere the column's `missing` mask (one flag per row,
// empty when none is missing).
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

namespace encoding3d {

using json = nlohmann::ordered_json;

/// The version of the specification this library reads and writes.
inline constexpr const char *SPECIFICATION_VERSION = "0.4";
/// The id of no entity: the complex or parent of an entity that has none, the feature row of a vertex with none.
inline constexpr std::int64_t NO_ID = -1;
/// The values of edge_type: the root of its scale, MTG '<', MTG '+'.
inline const std::vector<std::string> EDGE_TYPES = {"none", "successor", "branch", "unknown"};
/// The vocabulary's base scales: an entity set's scale is one of them, or "mixed".
inline const std::vector<std::string> BASE_SCALES = {"Plant", "Axis", "GrowthUnit", "Phytomer", "Organ",
                                                     "SubOrgan", "Layer", "Cell", "Compartment", "Connection"};

/// What the specification forbids, or a file that is not encoding3d.
struct Error : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// A shared part a frame refers to is nowhere it may be (specification §12.1): its key, and where it was looked for.
struct MissingPartError : Error {
    std::string key;
    std::vector<std::string> looked;
    MissingPartError(std::string part_key, std::vector<std::string> looked_at);
};

/// The values of a column: one vector per element type. Booleans are std::vector<bool>; text, labels and edge types
/// std::vector<std::string>.
using ColumnValues = std::variant<std::vector<std::int8_t>, std::vector<std::uint8_t>, std::vector<std::int16_t>,
                                  std::vector<std::uint16_t>, std::vector<std::int32_t>, std::vector<std::uint32_t>,
                                  std::vector<std::int64_t>, std::vector<std::uint64_t>, std::vector<float>,
                                  std::vector<double>, std::vector<bool>, std::vector<std::string>>;

/// A column: its values, `width` per row (1: one value per row; >= 2: a fixed-size vector per row), and which rows are
/// missing (`missing`, one flag per row, empty when none is; NaN in a float column).
struct Column {
    ColumnValues values;
    std::size_t width = 1;
    std::vector<bool> missing;

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
    /// Whether row `row` is missing (by the mask; a float's NaN is read as a value).
    bool is_missing(std::size_t row) const { return !missing.empty() && missing[row]; }
    bool has_missing() const;
    /// Marks rows as missing (one flag per row); returns the column, for chaining.
    Column &with_missing(std::vector<bool> rows) {
        missing = std::move(rows);
        return *this;
    }
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
    std::optional<std::string> format;   ///< a text column of dates or times: "date", "date-time" or "time"

    bool operator==(const Variable &other) const;
};

enum class TableKind { scalars, entity_set, relation, mapping, instance_set };

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
    std::optional<std::string> scale;    ///< a base scale (BASE_SCALES), or "mixed"

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

/// One array of numbers per instance, of each instance's own length (specification §12.2): `values` holds them one
/// after the other, in the instances' order; `counts` each one's length.
struct Ragged {
    std::vector<double> values;
    std::vector<std::int64_t> counts;

    Ragged() = default;
    Ragged(std::vector<double> ragged_values, std::vector<std::int64_t> ragged_counts)
        : values(std::move(ragged_values)), counts(std::move(ragged_counts)) {}
    /// The ragged array of one vector per instance.
    static Ragged of(const std::vector<std::vector<double>> &vectors);
    /// The number of instances.
    std::size_t size() const { return counts.size(); }
    /// Where each instance's values start in `values` (one more than size(): the end).
    std::vector<std::size_t> offsets() const;
    /// The values of instance `row`.
    std::vector<double> at(std::size_t row) const;
};

/// A derived field (specification §12.3): a field on the entity set `entity_set` of the instances' templates, rebuilt
/// for each instance i from its vector `input` v as f = Σ_k w_ik (A_ik v + b_ik) over its `terms` K terms. `operators`
/// and `weights`: K per instance, row by row (instance i's term k at i * K + k); an operator is an index in the
/// instance set's parts, NO_ID for none. `offsets`: K names of vectors, or none, each term's offset b.
struct DerivedField {
    std::string name;
    std::string entity_set;
    std::string input;
    std::size_t terms = 1;
    std::vector<std::int64_t> operators;
    std::vector<double> weights;
    std::vector<std::optional<std::string>> offsets;
    Variable variable;

    std::int64_t operator_of(std::size_t row, std::size_t term) const { return operators[row * terms + term]; }
    double weight_of(std::size_t row, std::size_t term) const { return weights[row * terms + term]; }
};

/// Instances of shared templates (specification §12.2): one row per instance, its reserved columns `template` (the
/// index in `parts` of its template, INT64), `owner` (the id, in the entity set `owners`, of the entity it draws),
/// `transform` (16 numbers per row, the column-major 4×4 placing the template; identity when absent) and `id`, then
/// its own variables. `parts`: the keys of the parts (templates and operators) the instances use; `vectors` and
/// `derived`: its vectors and derived fields (their columns <vector>__count, <field>__operator and <field>__weight
/// are written from them, not held as columns).
struct InstanceSet : Table {
    std::optional<std::string> owners;
    std::vector<std::string> parts;
    std::vector<std::pair<std::string, Ragged>> vectors;
    std::vector<DerivedField> derived;

    InstanceSet() : Table("", TableKind::instance_set) {}
    explicit InstanceSet(std::string name, std::optional<std::string> owner_set = std::nullopt)
        : Table(std::move(name), TableKind::instance_set), owners(std::move(owner_set)) {}
    std::size_t count() const { return row_count(); }
    const Ragged &vector(const std::string &vector_name) const;
    const DerivedField &derived_field(const std::string &field_name) const;
    /// The 4×4 placing instance `row`'s template, column-major (identity without a transform column).
    std::array<double, 16> transform(std::size_t row) const;
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
    std::vector<std::pair<std::string, std::string>> labels;   ///< the platform's labels -> the vocabulary's
    std::vector<InstanceSet> instance_sets;

    DataStructure() = default;
    explicit DataStructure(std::string id, std::string kind = "graph") : id(std::move(id)), kind(std::move(kind)) {}
    const EntitySet &entity_set(const std::string &name) const;
    EntitySet &entity_set(const std::string &name);
    const InstanceSet &instance_set(const std::string &name) const;
    InstanceSet &instance_set(const std::string &name);
};

/// A template (a shared part, specification §12.1): the data structure its part file holds (id "template", kind
/// "table", or "graph" with ranks): the template's own entity sets (e.g. a section's cells, their ids and constant
/// variables), relations, and meshes in the template's coordinates. A template is a valid frame of its own.
struct Template {
    DataStructure data_structure{"template", "table"};

    const EntitySet &entity_set(const std::string &name) const { return data_structure.entity_set(name); }
};

/// A matrix in compressed sparse rows: row r's entries are indices[indptr[r] .. indptr[r + 1]) and their values.
struct SparseMatrix {
    std::vector<std::int64_t> indptr;
    std::vector<std::int64_t> indices;
    std::vector<double> values;
};

/// A linear operator of derived fields (a shared part, specification §12.1), rows × columns: `format` "dense"
/// (`values`, row by row), "csr" (`sparse`) or "solve" (S⁻¹ R, S `system`, rows × rows, R `right_hand_side`, rows ×
/// columns, solved when evaluated).
struct Operator {
    std::string format = "dense";
    std::size_t rows = 0;
    std::size_t columns = 0;
    std::vector<double> values;
    SparseMatrix sparse;
    SparseMatrix system;
    SparseMatrix right_hand_side;

    static Operator dense(std::size_t rows, std::size_t columns, std::vector<double> row_by_row);
    static Operator csr(std::size_t rows, std::size_t columns, SparseMatrix matrix);
    static Operator solve(std::size_t rows, std::size_t columns, SparseMatrix system, SparseMatrix right_hand_side);
};

/// A shared part: a template or an operator.
using Part = std::variant<Template, Operator>;

/// What makes a frame partial: a coupling session's message (specification §11). participant: its sender
/// ("coordinator" for a turn's inputs); its tables hold some rows and columns only. removed: (data structure id,
/// entity set name) -> the ids of the entities removed.
struct Update {
    std::string participant;
    std::map<std::pair<std::string, std::string>, std::vector<std::int64_t>> removed;
};

/// A scene at one time step (time in time_unit, step), or a parameter set. update: set for a partial frame, a coupling
/// session's message. unknown: the content of a read file this library does not interpret (other root extensions,
/// the root's extras), written back as it was. The shared parts its instance sets refer to by key (specification
/// §12.1) are found in `part_bytes` (key -> GLB bytes: those embedded in the file read, and those add_part encoded),
/// else at parts/<key>.glb under `parts_folder` (the folder, or the x.fspm.zip archive, the frame was read from).
struct Frame {
    std::vector<DataStructure> data_structures;
    std::vector<Mapping> mappings;
    double time = 0.0;
    std::string time_unit = "d";
    std::int64_t step = 0;
    json writer = json::object();
    std::optional<std::string> vocabulary_version;
    std::optional<Update> update;
    json unknown = json::object();
    std::map<std::string, std::vector<std::uint8_t>> part_bytes;
    std::string parts_folder;

    const DataStructure &data_structure(const std::string &id) const;
    DataStructure &data_structure(const std::string &id);
};

} // namespace encoding3d
