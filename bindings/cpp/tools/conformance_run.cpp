// The C++ codec's run of the conformance check, as every codec does it in its CI: read each conformance GLB and dump
// it as JSON (OUT/dumps/x.json for x.glb), and write the conformance scenes again as GLB files (OUT/written/x.glb).
// The instances (0.4, conformance/README.md): each frame's derived fields evaluated too (OUT/dumps/instances/
// x.evaluated.json), each part dumped (OUT/dumps/instances/parts/<key>.json), each frame of each archive dumped and
// evaluated (OUT/dumps/archives/<name>/frame_n.json); the instances written again with their parts encoded by this
// codec, as a sequence with its index (OUT/written/instances), and packed (OUT/written/archives/instances.fspm.zip).
// Then .github/actions/conformance compares the dumps with the expected values and validates the written files.
//
//     encoding3d_conformance_run CONFORMANCE OUT
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>

#include "encoding3d/encoding3d.hpp"

namespace filesystem = std::filesystem;
using encoding3d::json;

namespace {

void dump(const filesystem::path &path, const json &value) {
    filesystem::create_directories(path.parent_path());
    std::ofstream(path, std::ios::binary) << value.dump(1) << "\n";
}

/// {"<data structure>/<instance set>/<field>": one list of values per instance} of every derived field of a frame.
json evaluated(const encoding3d::Frame &frame) {
    json out = json::object();
    for (const auto &data_structure : frame.data_structures)
        for (const auto &instance_set : data_structure.instance_sets)
            for (const auto &derived : instance_set.derived) {
                json instances = json::array();
                for (const auto &values : encoding3d::evaluate(frame, derived.name, data_structure.id, instance_set.name)) {
                    json items = json::array();
                    for (const auto value : values) items.push_back(std::isnan(value) ? json(nullptr) : json(value));
                    instances.push_back(items);
                }
                out[data_structure.id + "/" + instance_set.name + "/" + derived.name] = instances;
            }
    return out;
}

/// The frame with each part of its instance sets decoded and encoded again by this codec (new keys).
encoding3d::Frame with_parts_encoded_again(const encoding3d::Frame &frame) {
    encoding3d::Frame copy = frame;
    copy.part_bytes.clear();
    for (auto &data_structure : copy.data_structures)
        for (auto &instance_set : data_structure.instance_sets)
            for (auto &key : instance_set.parts) key = encoding3d::add_part(copy, encoding3d::frame_part(frame, key));
    return copy;
}

bool is_archive(const std::string &name) {
    const std::string suffix = encoding3d::ARCHIVE_SUFFIX;
    return name.size() > suffix.size() && name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0;
}

} // namespace

int main(int argument_count, char **arguments) {
    if (argument_count != 3) {
        std::cerr << "usage: encoding3d_conformance_run CONFORMANCE OUT\n";
        return 2;
    }
    const filesystem::path conformance = arguments[1], out = arguments[2];
    encoding3d::Index instances_index;
    std::set<std::string> instances_parts;
    for (const auto &entry : filesystem::recursive_directory_iterator(conformance)) {
        if (!entry.is_regular_file() || entry.path().extension() != ".glb") continue;
        const auto relative = filesystem::relative(entry.path(), conformance);
        const auto top = relative.begin()->string();
        if (top == "coupling" || top == "archives") continue;    // the sessions: their own run; archives: below
        auto dump_path = out / "dumps" / relative;
        dump_path.replace_extension(".json");
        if (top == "instances" && entry.path().parent_path().filename() == "parts") {
            const auto bytes = encoding3d::read_file_bytes(entry.path().string());
            dump(dump_path, encoding3d::part_to_json(encoding3d::read_part(bytes, entry.path().stem().string())));
            continue;
        }
        const auto frame = encoding3d::read_frame(entry.path().string());
        dump(dump_path, encoding3d::frame_to_json(frame));
        const auto written = out / "written" / relative;
        filesystem::create_directories(written.parent_path());
        if (top != "instances") {
            encoding3d::write_frame(written.string(), frame);             // written again from what was read
            continue;
        }
        auto evaluated_path = dump_path;
        evaluated_path.replace_extension(".evaluated.json");
        dump(evaluated_path, evaluated(frame));
        const bool embedded = entry.path().filename() == "embedded.glb";
        const auto keys = encoding3d::write_frame(written.string(), with_parts_encoded_again(frame), embedded);
        if (!embedded) {
            instances_index.frames.push_back({frame.time, frame.step, entry.path().filename().string(), ""});
            instances_parts.insert(keys.begin(), keys.end());
        }
    }
    const auto index = conformance / "growing_sequence" / encoding3d::INDEX_FILE;
    if (filesystem::exists(index))
        filesystem::copy_file(index, out / "written" / "growing_sequence" / encoding3d::INDEX_FILE,
                              filesystem::copy_options::overwrite_existing);
    const auto archives = conformance / "archives";
    std::vector<filesystem::path> names;
    if (filesystem::is_directory(archives))
        for (const auto &entry : filesystem::directory_iterator(archives))
            if (is_archive(entry.path().filename().string())) names.push_back(entry.path());
    std::sort(names.begin(), names.end());
    for (const auto &archive : names) {
        const auto name = archive.filename().string();
        const auto stem = name.substr(0, name.size() - std::string(encoding3d::ARCHIVE_SUFFIX).size());
        for (const auto &frame_entry : encoding3d::read_index(archive.string()).frames) {
            const auto frame = encoding3d::read_frame(frame_entry.path);         // x.fspm.zip/frame_n.glb
            const auto base = out / "dumps" / "archives" / stem / filesystem::path(frame_entry.file).stem();
            dump(base.string() + ".json", encoding3d::frame_to_json(frame));
            dump(base.string() + ".evaluated.json", evaluated(frame));
        }
    }
    if (!instances_index.frames.empty()) {                 // the instances again as a sequence, then packed
        std::sort(instances_index.frames.begin(), instances_index.frames.end(),
                  [](const auto &left, const auto &right) { return left.time < right.time; });
        instances_index.parts.assign(instances_parts.begin(), instances_parts.end());
        const auto folder = out / "written" / "instances";
        encoding3d::write_index((folder / encoding3d::INDEX_FILE).string(), instances_index);
        filesystem::create_directories(out / "written" / "archives");
        encoding3d::pack_archive(folder.string(), (out / "written" / "archives" / "instances.fspm.zip").string());
    }
    return 0;
}
