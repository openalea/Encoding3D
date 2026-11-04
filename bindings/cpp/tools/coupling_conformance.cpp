// The C++ participant under test in the coupling conformance sessions (conformance/coupling, specification §9):
// launched by the coordinator as `encoding3d_coupling_conformance SESSION OUT`, it joins with the session's
// subject/declaration.json, writes what it reads from each turn to OUT/turn_<step>.json, and sends
// subject/update_<step>.glb as read and written again by this library.
//
//     encoding3d couple-conformance conformance/coupling --participant build/encoding3d_coupling_conformance
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>

#include "encoding3d/coupling.hpp"
#include "encoding3d/encoding3d.hpp"

namespace filesystem = std::filesystem;

std::string numbered(std::int64_t step) {
    std::ostringstream text;
    text << std::setw(4) << std::setfill('0') << step;
    return text.str();
}

int main(int count, char **arguments) {
    if (count != 3) {
        std::cerr << "usage: encoding3d_coupling_conformance SESSION OUT\n";
        return 2;
    }
    const filesystem::path session = arguments[1], out = arguments[2];
    filesystem::create_directories(out);
    std::ifstream declaration_file(session / "subject" / "declaration.json");
    encoding3d::coupling::Participant participant(encoding3d::json::parse(declaration_file), "", encoding3d::json::array(),
                                               120.0);
    while (auto turn = participant.next_turn()) {
        std::ofstream dump(out / ("turn_" + numbered(turn->step) + ".json"));
        dump << encoding3d::frame_to_json(turn->frame).dump(1);
        dump.close();
        const auto update = encoding3d::read_frame((session / "subject" / ("update_" + numbered(turn->step) + ".glb")).string());
        participant.send_update(encoding3d::from_bytes(encoding3d::to_bytes(update)));
    }
    return 0;
}
