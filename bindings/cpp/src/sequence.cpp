// Sequences: a folder of frames (one GLB each), the shared parts they use (parts/<key>.glb) and their index,
// scene.fspm.json; or the same packed into an archive (x.fspm.zip).
#include "encoding3d/encoding3d.hpp"

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>

namespace encoding3d {

void write_index(const std::string &path, const Index &index) {
    json frames = json::array();
    for (const auto &entry : index.frames)
        frames.push_back({{"time", entry.time}, {"step", entry.step}, {"file", entry.file}});
    json document = {{"fspmIndex", index.version}, {"timeUnit", index.time_unit}, {"frames", frames}};
    if (!index.parts.empty()) {
        const std::set<std::string> keys(index.parts.begin(), index.parts.end());
        json parts = json::object();
        for (const auto &key : keys) parts[key] = "parts/" + key + ".glb";
        document["parts"] = parts;
    }
    std::ofstream file(path, std::ios::binary);
    if (!file) throw Error("cannot write '" + path + "'");
    file << document.dump(1) << "\n";
}

Index read_index(const std::string &path) {
    std::filesystem::path index_path(path);
    const std::string suffix = ARCHIVE_SUFFIX;
    if (std::filesystem::is_directory(index_path) ||
        (path.size() >= suffix.size() && path.compare(path.size() - suffix.size(), suffix.size(), suffix) == 0 &&
         std::filesystem::is_regular_file(index_path)))
        index_path /= INDEX_FILE;                         // a folder's index, or an archive's
    const auto bytes = read_file_bytes(index_path.string());
    const json document = json::parse(bytes.begin(), bytes.end());
    Index index;
    index.version = document.value("fspmIndex", std::string(SPECIFICATION_VERSION));
    index.time_unit = document.value("timeUnit", std::string("d"));
    const json parts = document.value("parts", json::object());
    for (const auto &item : parts.items()) index.parts.push_back(item.key());
    const auto directory = std::filesystem::absolute(index_path).parent_path();
    for (const auto &item : document.value("frames", json::array())) {
        IndexEntry entry;
        entry.time = item.at("time").get<double>();
        entry.step = item.at("step").get<std::int64_t>();
        entry.file = item.at("file").get<std::string>();
        entry.path = (directory / entry.file).string();
        index.frames.push_back(entry);
    }
    return index;
}

std::string write_sequence(const std::string &directory, const std::vector<Frame> &frames, const std::string &name) {
    std::filesystem::create_directories(directory);
    Index index;
    std::set<std::string> time_units, keys;
    for (std::size_t number = 0; number < frames.size(); ++number) {
        std::ostringstream file;
        file << name << "_" << std::setw(6) << std::setfill('0') << number << ".glb";
        const auto used = write_frame((std::filesystem::path(directory) / file.str()).string(), frames[number]);
        keys.insert(used.begin(), used.end());
        index.frames.push_back({frames[number].time, frames[number].step, file.str(), ""});
        time_units.insert(frames[number].time_unit);
    }
    if (time_units.size() > 1) throw Error("the frames' times are in several units");
    if (!time_units.empty()) index.time_unit = *time_units.begin();
    index.parts.assign(keys.begin(), keys.end());
    const auto path = (std::filesystem::path(directory) / INDEX_FILE).string();
    write_index(path, index);
    return path;
}

std::vector<Frame> read_sequence(const std::string &path) {
    std::vector<Frame> frames;
    for (const auto &entry : read_index(path).frames) frames.push_back(read_frame(entry.path));
    return frames;
}

} // namespace encoding3d
