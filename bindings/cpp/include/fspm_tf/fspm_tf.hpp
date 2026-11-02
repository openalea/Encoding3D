// Reading and writing fspm-TF files in C++: whole functional-structural plant model scenes (multiscale plant graphs,
// their variables and parameters, their geometry, the environment's grids) at successive time steps, one glTF 2.0
// binary (GLB) file per time step. The specification is spec/specification.md in the fspm-TF repository.
//
//     read_frame(path) -> Frame             write_frame(path, frame)
//     from_bytes(data) -> Frame             to_bytes(frame) -> bytes
//     read_index(path), read_sequence(path) write_sequence(directory, frames)
//     frame_to_json(frame)                  the layout of the conformance files' expected values
#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "fspm_tf/model.hpp"

namespace fspm_tf {

// ── The GLB container ─────────────────────────────────────────────────────

/// The bytes of a GLB file from its JSON document and its binary buffer (both padded to 8 bytes).
std::vector<std::uint8_t> pack(const json &document, const std::vector<std::uint8_t> &binary);
/// The JSON document (keys in their order) and the binary buffer of a GLB file's bytes.
std::pair<json, std::vector<std::uint8_t>> unpack(const std::vector<std::uint8_t> &data);

// ── Frames ────────────────────────────────────────────────────────────────

/// The GLB file of a frame.
std::vector<std::uint8_t> to_bytes(const Frame &frame);
/// The frame of a GLB file's bytes.
Frame from_bytes(const std::vector<std::uint8_t> &data);
/// Writes a frame to the GLB file `path`.
void write_frame(const std::string &path, const Frame &frame);
/// The frame of the GLB file `path`.
Frame read_frame(const std::string &path);

// ── Sequences ─────────────────────────────────────────────────────────────

/// The name of a sequence's index file.
inline constexpr const char *INDEX_FILE = "scene.fspm.json";

/// One frame of a sequence's index.
struct IndexEntry {
    double time = 0.0;
    std::int64_t step = 0;
    std::string file;
    std::string path; ///< the file's absolute path (when read)
};

/// A sequence's index: its frames, in time order.
struct Index {
    std::string version = SPECIFICATION_VERSION;
    std::string time_unit = "d";
    std::vector<IndexEntry> frames;
};

/// Writes the index of a sequence.
void write_index(const std::string &path, const Index &index);
/// The index of a sequence, each frame with the absolute path of its file.
Index read_index(const std::string &path);
/// Writes frames to `directory`, one GLB each (name_000000.glb, ...), and their index; the index's path.
std::string write_sequence(const std::string &directory, const std::vector<Frame> &frames,
                           const std::string &name = "frame");
/// The frames of the sequence whose index is `path`.
std::vector<Frame> read_sequence(const std::string &path);

// ── The conformance files' layout ─────────────────────────────────────────

/// A frame as plain JSON values, in the layout of the conformance files' expected values (conformance/README.md):
/// every table's columns as lists, NaN as null, ±∞ as "Infinity" / "-Infinity", positions as their float values.
json frame_to_json(const Frame &frame);
/// The differences between two JSON values, as `fspm-tf compare` finds them: objects by key, arrays in order,
/// numbers exactly (1 and 1.0 equal), as "path: what differs" lines (none when equal).
std::vector<std::string> compare(const json &actual, const json &expected, const std::string &path = "$");

} // namespace fspm_tf
