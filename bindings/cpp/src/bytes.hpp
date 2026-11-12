// Little-endian values in byte buffers, whatever the machine's byte order.
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "encoding3d/model.hpp"

namespace encoding3d::detail {

inline bool machine_is_little_endian() {
    const std::uint16_t probe = 1;
    std::uint8_t first;
    std::memcpy(&first, &probe, 1);
    return first == 1;
}

/// Appends `count` values of type T, little-endian.
template <typename T> void append_values(std::vector<std::uint8_t> &bytes, const T *values, std::size_t count) {
    const std::size_t start = bytes.size();
    bytes.resize(start + count * sizeof(T));
    if (count == 0) return;
    std::memcpy(bytes.data() + start, values, count * sizeof(T));
    if (!machine_is_little_endian() && sizeof(T) > 1)
        for (std::size_t item = 0; item < count; ++item)
            std::reverse(bytes.begin() + start + item * sizeof(T), bytes.begin() + start + (item + 1) * sizeof(T));
}

/// The `count` values of type T stored little-endian in `bytes` (of `available` bytes) from byte `offset`.
template <typename T>
std::vector<T> read_values(const std::uint8_t *bytes, std::size_t available, std::size_t count,
                           std::size_t offset = 0) {
    if (offset + count * sizeof(T) > available)
        throw Error("a buffer view holds " + std::to_string(available) + " bytes, " +
                    std::to_string(offset + count * sizeof(T)) + " needed");
    std::vector<T> values(count);
    if (count == 0) return values;
    std::memcpy(values.data(), bytes + offset, count * sizeof(T));
    if (!machine_is_little_endian() && sizeof(T) > 1)
        for (auto &value : values) {
            auto raw = reinterpret_cast<std::uint8_t *>(&value);
            std::reverse(raw, raw + sizeof(T));
        }
    return values;
}

inline std::uint32_t read_word(const std::vector<std::uint8_t> &data, std::size_t offset) {
    return read_values<std::uint32_t>(data.data(), data.size(), 1, offset)[0];
}

inline std::size_t padding(std::size_t length) { return (8 - length % 8) % 8; }

} // namespace encoding3d::detail
