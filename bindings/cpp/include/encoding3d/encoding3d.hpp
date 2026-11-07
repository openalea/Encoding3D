// Reading and writing encoding3d files in C++: whole functional-structural plant model scenes (multiscale plant graphs,
// their variables and parameters, their geometry, the environment's grids) at successive time steps, one glTF 2.0
// binary (GLB) file per time step. The specification is spec/specification.md in the encoding3d repository.
//
//     read_frame(path) -> Frame             write_frame(path, frame)
//     from_bytes(data) -> Frame             to_bytes(frame) -> bytes
//     read_index(path), read_sequence(path) write_sequence(directory, frames)
//     add_part(frame, part) -> key          a shared part (Template, Operator) its instance sets refer to by key
//     frame_part(frame, key) -> Part        found embedded, else at parts/<key>.glb next to the frame
//     evaluate(frame, field)                a derived field rebuilt for each instance (specification §12.3)
//     pack_archive(folder, path)            a sequence as one .fspm.zip archive; any path above may be
//                                           "x.fspm.zip/frame_000003.glb", a file inside one (specification §8.2)
//     frame_to_json(frame), part_to_json(part)   the layout of the conformance files' expected values
#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "encoding3d/model.hpp"

namespace encoding3d {

// ── The GLB container ─────────────────────────────────────────────────────

/// The bytes of a GLB file from its JSON document and its binary buffer (both padded to 8 bytes).
std::vector<std::uint8_t> pack(const json &document, const std::vector<std::uint8_t> &binary);
/// The JSON document (keys in their order) and the binary buffer of a GLB file's bytes.
std::pair<json, std::vector<std::uint8_t>> unpack(const std::vector<std::uint8_t> &data);

// ── Frames ────────────────────────────────────────────────────────────────

/// The GLB file of a frame; `embed_parts`: the parts its instance sets use in it (one self-contained file), else
/// referred to by key only (write_frame writes them to parts/).
std::vector<std::uint8_t> to_bytes(const Frame &frame, bool embed_parts = false);
/// The frame of a GLB file's bytes; `parts_folder`: the folder its parts/ are in (the file's folder).
Frame from_bytes(const std::vector<std::uint8_t> &data, const std::string &parts_folder = "");
/// Writes a frame to the GLB file `path`, and each part its instance sets use to parts/<key>.glb next to it, when not
/// there yet (`embed_parts`: into the frame instead); the keys of those parts, sorted.
std::vector<std::string> write_frame(const std::string &path, const Frame &frame, bool embed_parts = false);
/// The frame of the GLB file `path`, in a folder or in an archive ("run.fspm.zip/frame_000003.glb"); its parts are
/// found next to it.
Frame read_frame(const std::string &path);
/// The keys of the parts the instance sets of a frame use, sorted.
std::vector<std::string> frame_part_keys(const Frame &frame);

// ── Instances, derived fields and shared parts (specification §12) ───────

/// A part's key: the SHA-256 of its GLB bytes, in lower-case hexadecimal.
std::string content_key(const std::vector<std::uint8_t> &data);
/// The GLB file of a shared part: a template (a frame of its data structure) or an operator (a frame of no data
/// structure, its arrays in the binary chunk), FSPM_scene.part saying which.
std::vector<std::uint8_t> part_to_bytes(const Part &part);
/// The part of a part's GLB bytes; `key`, when given, checked against the bytes' hash.
Part read_part(const std::vector<std::uint8_t> &data, const std::string &key = "");
/// Encodes `part` into the frame's part_bytes; its key, for an instance set's parts.
std::string add_part(Frame &frame, const Part &part);
/// The GLB bytes of the part `key` of a frame: embedded or added, else at parts/<key>.glb under its parts_folder;
/// MissingPartError when it is nowhere.
std::vector<std::uint8_t> frame_part_bytes(const Frame &frame, const std::string &key);
/// The part `key` of a frame, decoded (frame_part_bytes, then read_part).
Part frame_part(const Frame &frame, const std::string &key);
/// The derived field `field` evaluated for the instances at `rows` (all when empty) of the instance set holding it
/// (in `data_structure` and named `instance_set` when given, if several have one of that name): one vector each, on
/// the rows of the field's entity set in the instance's template, Σ_k w_k (A_k v + b_k) over its terms whose operator
/// is not NO_ID; NaN for an instance without any. Its parts are found through the frame (frame_part).
std::vector<std::vector<double>> evaluate(const Frame &frame, const std::string &field,
                                          const std::string &data_structure = "",
                                          const std::string &instance_set = "",
                                          const std::vector<std::size_t> &rows = {});

// ── Archives (specification §8.2) ─────────────────────────────────────────

/// The end of an archive's name.
inline constexpr const char *ARCHIVE_SUFFIX = ".fspm.zip";
/// The bytes of the file `path`, in a folder or in an archive ("x.fspm.zip/member").
std::vector<std::uint8_t> read_file_bytes(const std::string &path);
/// Whether the file `path` exists, in a folder or in an archive.
bool file_exists(const std::string &path);
/// Packs the sequence of `folder` (a folder, or its index) into the ZIP64 archive `path` (x.fspm.zip): its index,
/// views.json, its frames and the parts they use, unchanged, each compressed alone (`compression`: "deflate",
/// "stored" or "lzma"). Returns `path`.
std::string pack_archive(const std::string &folder, const std::string &path, const std::string &compression = "deflate");

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

/// A sequence's index: its frames, in time order, and the keys of the parts they use (listed as parts/<key>.glb).
struct Index {
    std::string version = SPECIFICATION_VERSION;
    std::string time_unit = "d";
    std::vector<IndexEntry> frames;
    std::vector<std::string> parts;
};

/// Writes the index of a sequence.
void write_index(const std::string &path, const Index &index);
/// The index of a sequence (its file, its folder, or an archive x.fspm.zip), each frame with the path of its file.
Index read_index(const std::string &path);
/// Writes frames to `directory`, one GLB each (name_000000.glb, ...), their parts (parts/<key>.glb), and their index;
/// the index's path.
std::string write_sequence(const std::string &directory, const std::vector<Frame> &frames,
                           const std::string &name = "frame");
/// The frames of the sequence whose index is `path`.
std::vector<Frame> read_sequence(const std::string &path);

// ── The conformance files' layout ─────────────────────────────────────────

/// A frame as plain JSON values, in the layout of the conformance files' expected values (conformance/README.md):
/// every table's columns as lists, NaN as null, ±∞ as "Infinity" / "-Infinity", positions as their float values.
json frame_to_json(const Frame &frame);
/// A shared part as plain JSON values: a template's data structure (as frame_to_json's), an operator's arrays.
json part_to_json(const Part &part);
/// The differences between two JSON values, as `encoding3d compare` finds them: objects by key, arrays in order,
/// numbers exactly (1 and 1.0 equal), as "path: what differs" lines (none when equal).
std::vector<std::string> compare(const json &actual, const json &expected, const std::string &path = "$");

} // namespace encoding3d
