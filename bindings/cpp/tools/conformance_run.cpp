// The C++ codec's run of the conformance check, as every codec does it in its CI: read each conformance GLB and dump
// it as JSON (OUT/dumps/x.json for x.glb), and write the conformance scenes again as GLB files (OUT/written/x.glb).
// Then .github/actions/conformance compares the dumps with the expected values and validates the written files.
//
//     fspm_tf_conformance_run CONFORMANCE OUT
#include <filesystem>
#include <fstream>
#include <iostream>

#include "fspm_tf/fspm_tf.hpp"

namespace filesystem = std::filesystem;

int main(int argument_count, char **arguments) {
    if (argument_count != 3) {
        std::cerr << "usage: fspm_tf_conformance_run CONFORMANCE OUT\n";
        return 2;
    }
    const filesystem::path conformance = arguments[1], out = arguments[2];
    for (const auto &entry : filesystem::recursive_directory_iterator(conformance)) {
        if (!entry.is_regular_file() || entry.path().extension() != ".glb") continue;
        const auto relative = filesystem::relative(entry.path(), conformance);
        const auto frame = fspm_tf::read_frame(entry.path().string());
        auto dump = out / "dumps" / relative;
        dump.replace_extension(".json");
        const auto written = out / "written" / relative;
        filesystem::create_directories(dump.parent_path());
        filesystem::create_directories(written.parent_path());
        std::ofstream(dump, std::ios::binary) << fspm_tf::frame_to_json(frame).dump(1) << "\n";
        fspm_tf::write_frame(written.string(), frame);                 // written again from what was read
    }
    const auto index = conformance / "growing_sequence" / fspm_tf::INDEX_FILE;
    if (filesystem::exists(index))
        filesystem::copy_file(index, out / "written" / "growing_sequence" / fspm_tf::INDEX_FILE,
                              filesystem::copy_options::overwrite_existing);
    return 0;
}
