// CPlantBox's adapter: a simulated plant exported (organs, segments, variables, geometry, soil and mapping), written
// and read back; a static root system rebuilt from its own frame and from another platform's (the conformance root
// system, three scales).
//
//     fspm_tf_cplantbox_tests CONFORMANCE MODELPARAMETER OUT
#include <algorithm>
#include <cmath>
#include <functional>
#include <filesystem>
#include <iostream>
#include <map>
#include <set>

#include "fspm_tf/cplantbox.hpp"

#include "MappedOrganism.h"
#include "Plant.h"

namespace filesystem = std::filesystem;
using namespace fspm_tf;

namespace {

int failures = 0, checks = 0;

void check(bool condition, const std::string &what) {
    ++checks;
    if (!condition) {
        ++failures;
        std::cerr << "FAILED: " << what << "\n";
    }
}

std::shared_ptr<CPlantBox::Plant> grown_plant(const std::string &parameters, double days) {
    auto plant = std::make_shared<CPlantBox::Plant>(1);
    plant->readParameters(parameters, "plant", true, false);
    plant->initialize(false);
    plant->simulate(days, false);
    return plant;
}

/// The column of an entity set as doubles.
std::vector<double> values(const EntitySet &set, const std::string &name) {
    return std::visit([](const auto &column) {
        using T = typename std::decay_t<decltype(column)>::value_type;
        if constexpr (std::is_arithmetic_v<T> && !std::is_same_v<T, bool>) return std::vector<double>(column.begin(), column.end());
        return std::vector<double>{};
    }, set.column(name).values);
}

/// The topology is valid: ids unique, complexes and parents found, edge types consistent.
void check_topology(const DataStructure &data_structure, const std::string &what) {
    std::set<std::int64_t> all;
    std::size_t total = 0;
    for (const auto &set : data_structure.entity_sets) {
        const auto ids = set.ids();
        all.insert(ids.begin(), ids.end());
        total += ids.size();
    }
    check(all.size() == total, what + ": ids unique across entity sets");
    for (const auto &set : data_structure.entity_sets) {
        const auto ids = set.ids();
        const std::set<std::int64_t> own(ids.begin(), ids.end());
        if (set.has_column("parent")) {
            const auto &parents = set.column("parent").as<std::int64_t>();
            const auto &edges = set.column("edge_type").as<std::string>();
            bool good = true;
            for (std::size_t row = 0; row < parents.size(); ++row)
                good = good && (parents[row] == NO_ID ? edges[row] == "none" : own.count(parents[row]) && edges[row] != "none");
            check(good, what + ": parents of " + set.name + " in their set, with their edge types");
        }
        if (set.has_column("complex")) {
            bool good = true;
            for (const auto complex : set.column("complex").as<std::int64_t>()) good = good && (complex == NO_ID || all.count(complex));
            check(good, what + ": complexes of " + set.name + " found");
        }
    }
}

void test_root_system(const filesystem::path &parameters, const filesystem::path &out) {
    const auto plant = grown_plant((parameters / "plant" / "Anagallis_femina_Leitner_2010.xml").string(), 30.);
    cplantbox::Options options;
    options.model = "Anagallis_femina_Leitner_2010";
    const Frame frame = cplantbox::to_frame(*plant, options);
    const auto &data_structure = frame.data_structures[0];
    const auto &segments = data_structure.entity_set("SubOrgan");
    check(segments.row_count() == std::size_t(plant->getNumberOfSegments()), "one row per CPlantBox segment");
    check(data_structure.entity_set("Organ").row_count() >= plant->getOrgans().size(), "every organ (and the seed)");
    check_topology(data_structure, "root system");
    double total = 0.;
    for (const auto length : values(segments, "length")) total += length;
    double organs_total = 0.;
    for (const auto length : plant->getParameter("length")) organs_total += length;
    check(std::abs(total - organs_total) < 1e-9 * organs_total, "segment lengths sum to the organs' lengths");
    check(frame.time == 30., "the frame's time: the simulation time, days");

    write_frame((out / "anagallis.glb").string(), frame);           // written, read back the same
    const auto read_back = read_frame((out / "anagallis.glb").string());
    check(compare(frame_to_json(read_back), frame_to_json(frame)).empty(), "the root system read back as written");

    // Rebuilt as a static root system (CPlantBox has static roots only: the stem is left out), and exported again:
    // the same root segments (ends to the nanometre)
    const auto rebuilt = cplantbox::to_root_system(read_back.data_structures[0]);
    const auto organ_types = values(segments, "organType");
    const auto root_segments = std::count(organ_types.begin(), organ_types.end(), double(CPlantBox::Organism::ot_root));
    check(rebuilt->getNumberOfSegments() == root_segments,
          "the static root system has every root segment (" + std::to_string(rebuilt->getNumberOfSegments()) + " of " +
              std::to_string(root_segments) + ")");
    const auto again = cplantbox::to_data_structure(*rebuilt);
    const auto &rebuilt_segments = again.entity_set("SubOrgan");
    double root_total = 0., rebuilt_total = 0.;
    const auto lengths = values(segments, "length");
    for (std::size_t row = 0; row < lengths.size(); ++row)
        if (organ_types[row] == CPlantBox::Organism::ot_root) root_total += lengths[row];
    for (const auto length : values(rebuilt_segments, "length")) rebuilt_total += length;
    check(std::abs(rebuilt_total - root_total) < 1e-9 * root_total, "the static root system has the same root length");
    std::multiset<long long> ends, rebuilt_ends;
    for (const char *name : {"x2", "y2", "z2"}) {
        const auto coordinates = values(segments, name);
        for (std::size_t row = 0; row < coordinates.size(); ++row)
            if (organ_types[row] == CPlantBox::Organism::ot_root) ends.insert(std::llround(coordinates[row] * 1e9));
        for (const auto value : values(rebuilt_segments, name)) rebuilt_ends.insert(std::llround(value * 1e9));
    }
    check(ends == rebuilt_ends, "the static root system's segment ends are the same");
}

void test_plant_with_geometry_and_soil(const filesystem::path &parameters, const filesystem::path &out) {
    auto plant = std::make_shared<CPlantBox::MappedPlant>(1);
    plant->readParameters((parameters / "plant" / "fspm2023.xml").string(), "plant", true, false);
    plant->initialize(false);
    plant->simulate(28., false);
    auto data_structure = cplantbox::to_data_structure(*plant);
    cplantbox::add_geometry(data_structure, plant);
    check(data_structure.meshes.size() == 1 && data_structure.meshes[0].vertex_count() > 0, "a mesh of the shoot");
    const auto &rows = data_structure.meshes[0].feature_rows[0].second;
    std::size_t with_segment = 0;
    for (const auto row : rows) with_segment += row != NO_ID;
    check(with_segment > rows.size() / 2, "most vertices carry their segment");
    check_topology(data_structure, "shoot and roots");

    plant->setRectangularGrid(CPlantBox::Vector3d(-10, -10, -40), CPlantBox::Vector3d(10, 10, 0),
                              CPlantBox::Vector3d(4, 4, 8), false);
    const auto soil = cplantbox::soil_grid(*plant);
    const auto mapping = cplantbox::segments_in_soil(*plant, data_structure, soil);
    check(soil.entity_set("Voxel").row_count() == 4 * 4 * 8, "the soil grid's cells");
    check(mapping.row_count() > 0, "segments mapped to soil cells");
    bool inside = true;                                            // each mapped segment's midpoint is in its cell
    const auto &segments = data_structure.entity_set("SubOrgan");
    std::map<std::int64_t, std::size_t> row_of;
    const auto &ids = segments.column("id").as<std::int64_t>();
    for (std::size_t row = 0; row < ids.size(); ++row) row_of[ids[row]] = row;
    const auto x1 = values(segments, "x1"), y1 = values(segments, "y1"), z1 = values(segments, "z1");
    const auto x2 = values(segments, "x2"), y2 = values(segments, "y2"), z2 = values(segments, "z2");
    const auto &grid = *soil.grid;
    const auto &sources = mapping.column("source").as<std::int64_t>();
    const auto &targets = mapping.column("target").as<std::int64_t>();
    for (std::size_t item = 0; item < sources.size(); ++item) {
        const auto row = row_of.at(sources[item]);
        const double middle[3] = {(x1[row] + x2[row]) / 2, (y1[row] + y2[row]) / 2, (z1[row] + z2[row]) / 2};
        std::int64_t index[3];
        for (int axis = 0; axis < 3; ++axis)
            index[axis] = std::int64_t(std::floor((middle[axis] - grid.origin[axis]) / grid.spacing[axis]));
        inside = inside && targets[item] == (index[0] * grid.shape[1] + index[1]) * grid.shape[2] + index[2];
    }
    check(inside, "each mapped segment's midpoint lies in its cell (C order of x, y, z)");

    Frame frame;
    frame.time = plant->getSimTime();
    frame.data_structures = {data_structure, soil};
    frame.mappings = {mapping};
    write_frame((out / "fspm2023.glb").string(), frame);
    const auto read_back = read_frame((out / "fspm2023.glb").string());
    check(compare(frame_to_json(read_back), frame_to_json(frame)).empty(), "the plant, soil and mapping read back");
}

void test_another_platform(const filesystem::path &conformance) {
    // The conformance root system: Plant, Axis and SubOrgan scales (metafspm's layout), segments in metres
    const auto frame = read_frame((conformance / "root_system.glb").string());
    const auto &data_structure = frame.data_structures[0];
    const auto rebuilt = cplantbox::to_root_system(data_structure);
    const auto &segments = data_structure.entity_set("SubOrgan");
    check(rebuilt->getNumberOfSegments() == int(segments.row_count()), "another platform's segments, one each");
    check(int(rebuilt->getOrgans().size()) == int(data_structure.entity_set("Axis").row_count()),
          "another platform's axes as CPlantBox organs");
    double total = 0., rebuilt_total = 0.;
    for (const auto length : values(segments, "length")) total += length * 100.;   // m -> cm
    for (const auto length : rebuilt->getParameter("length")) rebuilt_total += length;
    check(std::abs(total - rebuilt_total) < 1e-6 * total, "another platform's root length, in cm");
}

} // namespace

int main(int argument_count, char **arguments) {
    if (argument_count != 4) {
        std::cerr << "usage: fspm_tf_cplantbox_tests CONFORMANCE MODELPARAMETER OUT\n";
        return 2;
    }
    const filesystem::path conformance = arguments[1], parameters = arguments[2], out = arguments[3];
    filesystem::create_directories(out);
    for (auto test : {std::function<void()>([&] { test_root_system(parameters, out); }),
                      std::function<void()>([&] { test_plant_with_geometry_and_soil(parameters, out); }),
                      std::function<void()>([&] { test_another_platform(conformance); })}) {
        try {
            test();
        } catch (const std::exception &error) {
            check(false, std::string("exception: ") + error.what());
        }
    }
    std::cout << checks - failures << " of " << checks << " checks passed\n";
    return failures == 0 ? 0 : 1;
}
