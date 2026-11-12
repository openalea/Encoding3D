// Shared parts (specification §12.1): their content key (SHA-256, FIPS 180-4), where a frame finds them (embedded,
// else parts/<key>.glb next to it), and derived fields evaluated from them (§12.3).
#include "encoding3d/encoding3d.hpp"

#include <array>
#include <cmath>
#include <filesystem>
#include <limits>
#include <map>

namespace encoding3d {

namespace {

constexpr std::array<std::uint32_t, 64> ROUND_CONSTANTS = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98,
    0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8,
    0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2};

std::uint32_t rotate_right(std::uint32_t value, int bits) { return (value >> bits) | (value << (32 - bits)); }

void compress_block(std::array<std::uint32_t, 8> &state, const std::uint8_t *block) {
    std::array<std::uint32_t, 64> schedule{};
    for (int word = 0; word < 16; ++word)
        schedule[word] = (std::uint32_t(block[word * 4]) << 24) | (std::uint32_t(block[word * 4 + 1]) << 16) |
                         (std::uint32_t(block[word * 4 + 2]) << 8) | std::uint32_t(block[word * 4 + 3]);
    for (int word = 16; word < 64; ++word) {
        const auto first = rotate_right(schedule[word - 15], 7) ^ rotate_right(schedule[word - 15], 18) ^
                           (schedule[word - 15] >> 3);
        const auto second = rotate_right(schedule[word - 2], 17) ^ rotate_right(schedule[word - 2], 19) ^
                            (schedule[word - 2] >> 10);
        schedule[word] = schedule[word - 16] + first + schedule[word - 7] + second;
    }
    auto working = state;
    for (int round = 0; round < 64; ++round) {
        const auto sum_e = rotate_right(working[4], 6) ^ rotate_right(working[4], 11) ^ rotate_right(working[4], 25);
        const auto choice = (working[4] & working[5]) ^ (~working[4] & working[6]);
        const auto first = working[7] + sum_e + choice + ROUND_CONSTANTS[round] + schedule[round];
        const auto sum_a = rotate_right(working[0], 2) ^ rotate_right(working[0], 13) ^ rotate_right(working[0], 22);
        const auto majority = (working[0] & working[1]) ^ (working[0] & working[2]) ^ (working[1] & working[2]);
        const auto second = sum_a + majority;
        working = {first + second, working[0], working[1], working[2], working[3] + first, working[4], working[5],
                   working[6]};
    }
    for (int word = 0; word < 8; ++word) state[word] += working[word];
}

/// A dense LU factorisation with partial pivoting of a square system, solved for many right-hand sides.
struct Factorisation {
    std::size_t size = 0;
    std::vector<double> lower_upper;
    std::vector<std::size_t> pivots;

    explicit Factorisation(const SparseMatrix &system, std::size_t rows) : size(rows), lower_upper(rows * rows, 0.0),
                                                                         pivots(rows) {
        for (std::size_t row = 0; row < rows; ++row)
            for (auto entry = system.indptr[row]; entry < system.indptr[row + 1]; ++entry)
                lower_upper[row * rows + static_cast<std::size_t>(system.indices[static_cast<std::size_t>(entry)])] +=
                    system.values[static_cast<std::size_t>(entry)];
        for (std::size_t column = 0; column < rows; ++column) {
            std::size_t pivot = column;
            for (std::size_t row = column + 1; row < rows; ++row)
                if (std::abs(lower_upper[row * rows + column]) > std::abs(lower_upper[pivot * rows + column])) pivot = row;
            if (lower_upper[pivot * rows + column] == 0.0) throw Error("a solve operator's system is singular");
            pivots[column] = pivot;
            if (pivot != column)
                for (std::size_t item = 0; item < rows; ++item)
                    std::swap(lower_upper[pivot * rows + item], lower_upper[column * rows + item]);
            for (std::size_t row = column + 1; row < rows; ++row) {
                const double factor = lower_upper[row * rows + column] / lower_upper[column * rows + column];
                lower_upper[row * rows + column] = factor;
                for (std::size_t item = column + 1; item < rows; ++item)
                    lower_upper[row * rows + item] -= factor * lower_upper[column * rows + item];
            }
        }
    }

    std::vector<double> solve(std::vector<double> right) const {
        for (std::size_t column = 0; column < size; ++column) std::swap(right[column], right[pivots[column]]);
        for (std::size_t row = 0; row < size; ++row)
            for (std::size_t item = 0; item < row; ++item) right[row] -= lower_upper[row * size + item] * right[item];
        for (std::size_t row = size; row-- > 0;) {
            for (std::size_t item = row + 1; item < size; ++item) right[row] -= lower_upper[row * size + item] * right[item];
            right[row] /= lower_upper[row * size + row];
        }
        return right;
    }
};

std::vector<double> sparse_product(const SparseMatrix &matrix, std::size_t rows, const std::vector<double> &vector) {
    std::vector<double> product(rows, 0.0);
    if (matrix.indptr.size() != rows + 1) throw Error("a sparse operator's indptr holds rows + 1 values");
    for (std::size_t row = 0; row < rows; ++row)
        for (auto entry = matrix.indptr[row]; entry < matrix.indptr[row + 1]; ++entry) {
            const auto column = static_cast<std::size_t>(matrix.indices.at(static_cast<std::size_t>(entry)));
            product[row] += matrix.values.at(static_cast<std::size_t>(entry)) * vector.at(column);
        }
    return product;
}

/// A part decoded once per evaluation, its factorisation (a solve operator's) too.
struct DecodedPart {
    Part part;
    std::optional<Factorisation> factorisation;
};

std::vector<double> apply(DecodedPart &decoded, const std::vector<double> &vector) {
    const auto &operator_part = std::get<Operator>(decoded.part);
    if (operator_part.format == "dense") {
        std::vector<double> product(operator_part.rows, 0.0);
        for (std::size_t row = 0; row < operator_part.rows; ++row)
            for (std::size_t column = 0; column < operator_part.columns; ++column)
                product[row] += operator_part.values[row * operator_part.columns + column] * vector[column];
        return product;
    }
    if (operator_part.format == "csr") return sparse_product(operator_part.sparse, operator_part.rows, vector);
    if (!decoded.factorisation) decoded.factorisation.emplace(operator_part.system, operator_part.rows);
    return decoded.factorisation->solve(sparse_product(operator_part.right_hand_side, operator_part.rows, vector));
}

} // namespace

std::string content_key(const std::vector<std::uint8_t> &data) {
    std::array<std::uint32_t, 8> state = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                          0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    const std::size_t whole = data.size() / 64 * 64;
    for (std::size_t offset = 0; offset < whole; offset += 64) compress_block(state, data.data() + offset);
    std::vector<std::uint8_t> tail(data.begin() + static_cast<std::ptrdiff_t>(whole), data.end());
    tail.push_back(0x80);
    while (tail.size() % 64 != 56) tail.push_back(0);
    const std::uint64_t bits = static_cast<std::uint64_t>(data.size()) * 8;
    for (int byte = 7; byte >= 0; --byte) tail.push_back(static_cast<std::uint8_t>(bits >> (byte * 8)));
    for (std::size_t offset = 0; offset < tail.size(); offset += 64) compress_block(state, tail.data() + offset);
    static const char *digits = "0123456789abcdef";
    std::string key;
    for (const auto word : state)
        for (int shift = 28; shift >= 0; shift -= 4) key.push_back(digits[(word >> shift) & 0xF]);
    return key;
}

std::string add_part(Frame &frame, const Part &part) {
    auto bytes = part_to_bytes(part);
    auto key = content_key(bytes);
    frame.part_bytes.emplace(key, std::move(bytes));
    return key;
}

std::vector<std::uint8_t> frame_part_bytes(const Frame &frame, const std::string &key) {
    const auto found = frame.part_bytes.find(key);
    if (found != frame.part_bytes.end()) return found->second;
    std::vector<std::string> looked;
    if (!frame.part_bytes.empty()) looked.push_back("the frame (embedded)");
    if (!frame.parts_folder.empty()) {
        const auto path = (std::filesystem::path(frame.parts_folder) / "parts" / (key + ".glb")).string();
        if (file_exists(path)) return read_file_bytes(path);
        looked.push_back(path);
    }
    throw MissingPartError(key, looked);
}

Part frame_part(const Frame &frame, const std::string &key) { return read_part(frame_part_bytes(frame, key), key); }

std::vector<std::vector<double>> evaluate(const Frame &frame, const std::string &field,
                                          const std::string &data_structure, const std::string &instance_set,
                                          const std::vector<std::size_t> &rows) {
    const InstanceSet *found = nullptr;
    for (const auto &candidate : frame.data_structures) {
        if (!data_structure.empty() && candidate.id != data_structure) continue;
        for (const auto &set : candidate.instance_sets) {
            if (!instance_set.empty() && set.name != instance_set) continue;
            bool holds = false;
            for (const auto &derived : set.derived) holds = holds || derived.name == field;
            if (!holds) continue;
            if (found) throw Error("several instance sets with the derived field '" + field + "': name the data "
                                   "structure or the instance set");
            found = &set;
        }
    }
    if (!found) throw Error("the frame has no instance set with the derived field '" + field + "'");
    const auto &derived = found->derived_field(field);
    const auto templates = found->column("template").as<std::int64_t>();
    const auto &input = found->vector(derived.input);
    const auto input_offsets = input.offsets();
    std::vector<std::size_t> chosen = rows;
    if (rows.empty())
        for (std::size_t row = 0; row < found->count(); ++row) chosen.push_back(row);
    std::map<std::int64_t, DecodedPart> decoded;
    auto part_at = [&](std::int64_t index) -> DecodedPart & {
        auto existing = decoded.find(index);
        if (existing != decoded.end()) return existing->second;
        if (index < 0 || static_cast<std::size_t>(index) >= found->parts.size())
            throw Error("'" + found->name + "': part " + std::to_string(index) + " outside its parts");
        return decoded.emplace(index, DecodedPart{frame_part(frame, found->parts[static_cast<std::size_t>(index)]),
                                                  std::nullopt}).first->second;
    };
    std::vector<std::vector<double>> out;
    for (const auto row : chosen) {
        if (row >= found->count()) throw Error("instance row " + std::to_string(row) + " outside '" + found->name + "'");
        auto &template_part = part_at(templates[row]);
        if (!std::holds_alternative<Template>(template_part.part))
            throw Error("'" + found->name + "': part " + std::to_string(templates[row]) + " is not a template");
        const auto size = std::get<Template>(template_part.part).entity_set(derived.entity_set).row_count();
        std::vector<double> result(size, std::numeric_limits<double>::quiet_NaN());
        const std::vector<double> vector(input.values.begin() + static_cast<std::ptrdiff_t>(input_offsets[row]),
                                         input.values.begin() + static_cast<std::ptrdiff_t>(input_offsets[row + 1]));
        bool started = false;
        for (std::size_t term = 0; term < derived.terms; ++term) {
            const auto operator_index = derived.operator_of(row, term);
            if (operator_index == NO_ID) continue;
            auto &operator_part = part_at(operator_index);
            if (!std::holds_alternative<Operator>(operator_part.part))
                throw Error("'" + found->name + "': part " + std::to_string(operator_index) + " is not an operator");
            const auto &matrix = std::get<Operator>(operator_part.part);
            if (vector.size() != matrix.columns)
                throw Error("'" + found->name + "' instance " + std::to_string(row) + ": " +
                            std::to_string(vector.size()) + " values of '" + derived.input + "', its operator takes " +
                            std::to_string(matrix.columns));
            if (matrix.rows != size)
                throw Error("'" + found->name + "' instance " + std::to_string(row) + ": operator " +
                            std::to_string(operator_index) + " has " + std::to_string(matrix.rows) +
                            " rows, its template's '" + derived.entity_set + "' " + std::to_string(size));
            const double weight = derived.weight_of(row, term);
            auto values = apply(operator_part, vector);
            for (auto &value : values) value *= weight;
            if (derived.offsets[term]) {
                const auto offset = found->vector(*derived.offsets[term]).at(row);
                if (!offset.empty()) {
                    if (offset.size() != size)
                        throw Error("'" + found->name + "' instance " + std::to_string(row) + ": offset '" +
                                    *derived.offsets[term] + "' has " + std::to_string(offset.size()) + " values, " +
                                    std::to_string(size) + " expected");
                    for (std::size_t item = 0; item < size; ++item) values[item] += weight * offset[item];
                }
            }
            for (std::size_t item = 0; item < size; ++item) result[item] = started ? result[item] + values[item] : values[item];
            started = true;
        }
        out.push_back(std::move(result));
    }
    return out;
}

} // namespace encoding3d
