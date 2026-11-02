// The GLB container: a 12-byte header (magic, version 2, total length), a JSON chunk padded with spaces, a binary
// chunk padded with zeros, each 8-byte aligned (as EXT_structural_metadata requires). Little-endian throughout.
#include "fspm_tf/fspm_tf.hpp"

#include "bytes.hpp"

namespace fspm_tf {

namespace {
constexpr std::uint32_t GLB_MAGIC = 0x46546C67;     // "glTF"
constexpr std::uint32_t GLB_VERSION = 2;
constexpr std::uint32_t JSON_CHUNK = 0x4E4F534A;    // "JSON"
constexpr std::uint32_t BINARY_CHUNK = 0x004E4942;  // "BIN\0"

void append_word(std::vector<std::uint8_t> &bytes, std::uint32_t value) { detail::append_values(bytes, &value, 1); }
} // namespace

std::vector<std::uint8_t> pack(const json &document, const std::vector<std::uint8_t> &binary) {
    std::string text = document.dump(-1, ' ', false, json::error_handler_t::strict);
    text.append(detail::padding(text.size()), ' ');
    std::vector<std::uint8_t> padded = binary;
    padded.resize(binary.size() + detail::padding(binary.size()), 0);
    const std::size_t total = 12 + 8 + text.size() + (padded.empty() ? 0 : 8 + padded.size());
    if (total > 0xFFFFFFFFull) throw Error("a GLB file is at most 4 GiB");
    std::vector<std::uint8_t> bytes;
    bytes.reserve(total);
    append_word(bytes, GLB_MAGIC);
    append_word(bytes, GLB_VERSION);
    append_word(bytes, static_cast<std::uint32_t>(total));
    append_word(bytes, static_cast<std::uint32_t>(text.size()));
    append_word(bytes, JSON_CHUNK);
    bytes.insert(bytes.end(), text.begin(), text.end());
    if (!padded.empty()) {
        append_word(bytes, static_cast<std::uint32_t>(padded.size()));
        append_word(bytes, BINARY_CHUNK);
        bytes.insert(bytes.end(), padded.begin(), padded.end());
    }
    return bytes;
}

std::pair<json, std::vector<std::uint8_t>> unpack(const std::vector<std::uint8_t> &data) {
    if (data.size() < 20) throw Error("not a GLB file: too short");
    if (detail::read_word(data, 0) != GLB_MAGIC) throw Error("not a GLB file: wrong magic");
    const auto version = detail::read_word(data, 4);
    if (version != GLB_VERSION) throw Error("GLB version " + std::to_string(version) + ", 2 expected");
    const auto total = detail::read_word(data, 8);
    if (total != data.size())
        throw Error("GLB header length " + std::to_string(total) + ", the file holds " + std::to_string(data.size()) +
                    " bytes");
    std::size_t offset = 12;
    bool found_document = false;
    json document;
    std::vector<std::uint8_t> binary;
    while (offset < total) {
        const std::size_t chunk_length = detail::read_word(data, offset);
        const auto chunk_type = detail::read_word(data, offset + 4);
        if (offset + 8 + chunk_length > total) throw Error("a GLB chunk runs past the end of the file");
        const auto begin = data.begin() + static_cast<std::ptrdiff_t>(offset + 8);
        const auto end = begin + static_cast<std::ptrdiff_t>(chunk_length);
        if (chunk_type == JSON_CHUNK) {
            document = json::parse(begin, end);
            found_document = true;
        } else if (chunk_type == BINARY_CHUNK) {
            binary.assign(begin, end);
        }
        offset += 8 + chunk_length;
    }
    if (!found_document) throw Error("GLB file without a JSON chunk");
    return {std::move(document), std::move(binary)};
}

} // namespace fspm_tf
