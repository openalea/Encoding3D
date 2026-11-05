// Tutorial 2c: CPlantBox writes and reads encoding3d (README.md explains each part).
//
//     cplantbox_tutorial MODELPARAMETER OUT       MODELPARAMETER: CPlantBox's modelparameter/structural folder
#include <cmath>
#include <filesystem>
#include <iostream>
#include <numeric>

#include "encoding3d/cplantbox.hpp"
#include "encoding3d/encoding3d.hpp"

#include "MappedOrganism.h"
#include "Plant.h"

namespace filesystem = std::filesystem;
using namespace encoding3d;

int main(int count, char **arguments) {
    if (count != 3) {
        std::cerr << "usage: cplantbox_tutorial MODELPARAMETER OUT\n";
        return 2;
    }
    const filesystem::path parameters = arguments[1], out = arguments[2];
    filesystem::create_directories(out);

    // ── 1. A CPlantBox plant (shoot and roots), grown day by day ───────────────────────────────────────
    auto plant = std::make_shared<CPlantBox::MappedPlant>(1);
    plant->readParameters((parameters / "plant" / "fspm2023.xml").string(), "plant", true, false);
    plant->initialize(false);

    // ── 2. A frame a day: the plant with its geometry, a soil grid, which cell each segment is in ─────────
    std::vector<Frame> frames;
    for (int day = 1; day <= 10; ++day) {
        plant->simulate(1., false);
        auto data_structure = cplantbox::to_data_structure(*plant);        // plant, organs, segments
        cplantbox::add_geometry(data_structure, plant);                    // the shoot's blades and stems
        plant->setRectangularGrid(CPlantBox::Vector3d(-10, -10, -30), CPlantBox::Vector3d(10, 10, 0),
                                  CPlantBox::Vector3d(10, 10, 15), false);   // cm: 2 cm cells, segments not cut
        auto soil = cplantbox::soil_grid(*plant);
        const auto mapping = cplantbox::segments_in_soil(*plant, data_structure, soil);

        // a soil water potential per cell, from a solver CPlantBox would be coupled with: here a toy gradient
        std::vector<double> potential;
        for (int z = 0; z < 15; ++z)                                         // CPlantBox's cell order: x fastest
            for (int y = 0; y < 10; ++y)
                for (int x = 0; x < 10; ++x) potential.push_back(-300. + 10. * z);
        Variable declaration;
        declaration.unit = "cm[H2O]";
        declaration.standard_name = "soil_water_potential";
        declaration.description = "a toy gradient, wetter with depth";
        cplantbox::add_cell_values(soil, *plant, {{"soil_water_potential", potential, declaration}});

        Frame frame;
        frame.time = plant->getSimTime();
        frame.time_unit = "d";
        frame.step = day;
        frame.data_structures = {data_structure, soil};
        frame.mappings = {mapping};
        frames.push_back(frame);
        std::cout << "day " << day << ": " << data_structure.entity_set("Organ").row_count() << " organs, "
                  << data_structure.entity_set("SubOrgan").row_count() << " segments, "
                  << mapping.row_count() << " in the soil\n";
    }
    const auto index = write_sequence((out / "frames").string(), frames);
    std::cout << "written: " << index << "\n";

    // ── 3. A frame back as a CPlantBox root system ───────────────────────────────────────────────────────
    const auto last = read_frame((out / "frames" / "frame_000009.glb").string());
    auto roots = cplantbox::to_root_system(last.data_structure("plant"));
    const auto lengths = roots->getParameter("length");
    std::cout << "read back as CPlantBox roots: " << roots->getOrgans(CPlantBox::Organism::ot_root).size()
              << " roots, " << std::accumulate(lengths.begin(), lengths.end(), 0.) << " cm long in all\n";

    // ── 4. Another platform's frame (the conformance root system) as a CPlantBox root system ────────────
    const filesystem::path conformance = filesystem::path(__FILE__).parent_path() / ".." / ".." / "conformance";
    const auto other = read_frame((conformance / "root_system.glb").string());
    auto rebuilt = cplantbox::to_root_system(other.data_structures[0]);
    std::cout << "another platform's root system in CPlantBox: " << rebuilt->getOrgans().size() << " organs, "
              << rebuilt->getNumberOfSegments() << " segments\n";
    return 0;
}
