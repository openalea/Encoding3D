// The C++ participant under test in the coupling conformance sessions (conformance/coupling, specification §9):
// launched by the coordinator as `fspm_tf_coupling_conformance SESSION OUT`, it joins with the session's
// subject/declaration.json, writes what it reads from each turn to OUT/turn_<step>.json, and sends
// subject/update_<step>.glb as read and written again by this library.
//
//     fspm-tf couple-conformance conformance/coupling --participant build/fspm_tf_coupling_conformance
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>

#include "fspm_tf/coupling.hpp"
#include "fspm_tf/fspm_tf.hpp"

namespace filesystem = std::filesystem;

std::string numbered(std::int64_t step) {
    std::ostringstream text;
    text << std::setw(4) << std::setfill('0') << step;
    return text.str();
}

int main(int count, char **arguments) {
    if (count != 3) {
        std::cerr << "usage: fspm_tf_coupling_conformance SESSION OUT\n";
        return 2;
    }
    const filesystem::path session = arguments[1], out = arguments[2];
    filesystem::create_directories(out);
    std::ifstream declaration_file(session / "subject" / "declaration.json");
    fspm_tf::coupling::Participant participant(fspm_tf::json::parse(declaration_file), "", fspm_tf::json::array(),
                                               120.0);
    while (auto turn = participant.next_turn()) {
        std::ofstream dump(out / ("turn_" + numbered(turn->step) + ".json"));
        dump << fspm_tf::frame_to_json(turn->frame).dump(1);
        dump.close();
        const auto update = fspm_tf::read_frame((session / "subject" / ("update_" + numbered(turn->step) + ".glb")).string());
        participant.send_update(fspm_tf::from_bytes(fspm_tf::to_bytes(update)));
    }
    return 0;
}
