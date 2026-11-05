// Tutorial 4, CPlantBox's side: the root architecture (structural). CPlantBox grows a root system by its own rules;
// each turn, the plant, its root organs and their segments are sent to the session (CPlantBox's adapter writes them,
// their ids renumbered in this participant's range), with each segment's length, radius and ends.
#include <cstdint>
#include <iostream>
#include <map>

#include "encoding3d/coupling.hpp"
#include "encoding3d/cplantbox.hpp"
#include "encoding3d/encoding3d.hpp"

#include "Plant.h"

using namespace encoding3d;

namespace {

/// The declaration: CPlantBox owns the plant, its organs and segments, and provides the segments' sizes and ends.
json declaration() {
    json variables = json::array();
    auto provides = [&](const char *name, const char *unit, const char *standard_name, const char *kind) {
        variables.push_back({{"dataStructure", "plant"}, {"entitySet", "SubOrgan"}, {"name", name},
                             {"direction", "provides"}, {"unit", unit}, {"standardName", standard_name},
                             {"kind", kind}});
    };
    provides("length", "cm", "length", "extensive");
    provides("radius", "cm", "radius", "intensive");
    for (const auto &[name, standard_name] : {std::pair{"x1", "proximal_end_x"}, {"y1", "proximal_end_y"},
                                              {"z1", "proximal_end_z"}, {"x2", "distal_end_x"},
                                              {"y2", "distal_end_y"}, {"z2", "distal_end_z"}})
        provides(name, "cm", standard_name, "descriptor");
    json sets = json::array();
    for (const auto &[name, rank] : {std::pair{"Plant", 1}, {"Organ", 5}, {"SubOrgan", 6}})
        sets.push_back({{"dataStructure", "plant"}, {"name", name}, {"rank", rank}, {"rights", "owns"}});
    return {{"participant", "cplantbox"}, {"platform", "CPlantBox"}, {"entitySets", sets}, {"variables", variables}};
}

/// The session's id of an adapter's id: this participant's range, in order of appearance (stable while it grows).
std::int64_t session_id(std::map<std::int64_t, std::int64_t> &ids, std::int64_t offset, std::int64_t adapter) {
    if (adapter == NO_ID) return NO_ID;
    auto found = ids.find(adapter);
    if (found == ids.end()) found = ids.emplace(adapter, offset + std::int64_t(ids.size())).first;
    return found->second;
}

/// An entity set of the adapter's as the session's: its ids renumbered, its topology, the variables in *keep*.
EntitySet renumbered(const EntitySet &set, std::map<std::int64_t, std::int64_t> &ids, std::int64_t offset,
                     const std::vector<std::string> &keep) {
    EntitySet out(set.name, set.rank);
    for (const char *name : {"id", "complex", "parent"}) {
        if (!set.has_column(name)) continue;
        std::vector<std::int64_t> values;
        for (const auto value : set.column(name).as<std::int64_t>()) values.push_back(session_id(ids, offset, value));
        out.set(name, Column(values));
    }
    for (const char *name : {"label", "edge_type"})
        if (set.has_column(name)) out.set(name, set.column(name));
    for (const auto &name : keep)
        if (set.has_column(name)) out.set(name, set.column(name));
    return out;
}

} // namespace

int main() {
    auto plant = std::make_shared<CPlantBox::Plant>(1);
    plant->readParameters(std::string(CPLANTBOX_PARAMETERS) + "/plant/Anagallis_femina_Leitner_2010.xml", "plant",
                          true, false);
    plant->initialize(false);
    plant->simulate(3., false);                        // a young root system to start from

    coupling::Participant participant(declaration(), "", json::array(), 600.0);
    std::map<std::int64_t, std::int64_t> ids;
    while (auto turn = participant.next_turn()) {
        if (turn->phase == "step") plant->simulate(turn->until - turn->time, false);   // days, the session's unit
        const auto written = cplantbox::to_data_structure(*plant);
        DataStructure update("plant");
        update.entity_sets.push_back(renumbered(written.entity_set("Plant"), ids, participant.id_offset, {}));
        update.entity_sets.push_back(renumbered(written.entity_set("Organ"), ids, participant.id_offset, {}));
        update.entity_sets.push_back(renumbered(written.entity_set("SubOrgan"), ids, participant.id_offset,
                                                {"length", "radius", "x1", "y1", "z1", "x2", "y2", "z2"}));
        Frame frame;
        frame.data_structures.push_back(update);
        participant.send_update(frame);
        std::cout << "cplantbox: day " << plant->getSimTime() << ", " << plant->getNumberOfSegments() << " segments"
                  << std::endl;
    }
    std::cout << "cplantbox: the session ended (" << participant.stopped.value_or("") << ")" << std::endl;
    return 0;
}
