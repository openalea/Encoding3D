#include "fspm_tf/cplantbox.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <map>
#include <numeric>
#include <set>

#include "MappedOrganism.h"
#include "Organ.h"
#include "Organism.h"
#include "Plant.h"
#include "PlantVisualiser.h"
#include "Root.h"
#include "Seed.h"
#include "organparameter.h"
#include "rootparameter.h"
#include "tinyxml2.h"

namespace fspm_tf::cplantbox {

namespace {

constexpr double METRES_PER_CENTIMETRE = 0.01;

Variable declared(const std::string &unit, const std::string &kind, const std::string &description,
                  std::optional<std::string> standard_name = std::nullopt, const std::string &role = "state") {
    Variable variable;
    variable.unit = unit;
    variable.kind = kind;
    variable.description = description;
    variable.standard_name = std::move(standard_name);
    variable.role = role;
    return variable;
}

/// The vocabulary's label of a CPlantBox organ type: a root or a stem is a whole axis, a leaf an organ.
std::string organ_label(int organ_type) {
    switch (organ_type) {
    case CPlantBox::Organism::ot_seed: return "Seed";
    case CPlantBox::Organism::ot_root: return "RootAxis";
    case CPlantBox::Organism::ot_stem: return "ShootAxis";
    case CPlantBox::Organism::ot_leaf: return "Leaf";
    default: return "Organ";
    }
}

std::string segment_label(int organ_type) {
    switch (organ_type) {
    case CPlantBox::Organism::ot_root: return "RootSegment";
    case CPlantBox::Organism::ot_stem: return "StemElement";
    case CPlantBox::Organism::ot_leaf: return "LeafElement";
    default: return "SubOrgan";
    }
}

/// The organism's organs, seeds included, parents before their laterals.
std::vector<std::shared_ptr<CPlantBox::Organ>> all_organs(const CPlantBox::Organism &organism) {
    std::vector<std::shared_ptr<CPlantBox::Organ>> organs;
    std::set<const CPlantBox::Organ *> seen;
    std::function<void(const std::shared_ptr<CPlantBox::Organ> &)> visit = [&](const std::shared_ptr<CPlantBox::Organ> &organ) {
        if (!organ || seen.count(organ.get())) return;
        seen.insert(organ.get());
        organs.push_back(organ);
        for (int child = 0; child < organ->getNumberOfChildren(); ++child) visit(organ->getChild(child));
    };
    for (const auto &organ : organism.getOrgans(-1, true)) {        // from each organ's root: its seed, or itself
        auto base = organ;
        while (base->getParent()) base = base->getParent();
        visit(base);
    }
    return organs;
}

/// The organism's parameters as CPlantBox's XML (as Organism::writeParameters writes them, skipping the empty entries
/// a MappedPlant can leave in its parameter map, on which writeParameters fails).
std::string parameters_xml(const CPlantBox::Organism &organism) {
    tinyxml2::XMLDocument document;
    tinyxml2::XMLElement *parameters = document.NewElement("plant");
    for (int organ_type = 0; organ_type <= CPlantBox::Organism::ot_leaf; ++organ_type)
        for (const auto &parameter : organism.getOrganRandomParameter(organ_type))
            if (parameter && (organ_type == CPlantBox::Organism::ot_seed || parameter->subType > 0))
                parameters->InsertEndChild(parameter->writeXML(document, false));
    document.InsertEndChild(parameters);
    tinyxml2::XMLPrinter printer;
    document.Print(&printer);
    return printer.CStr();
}

} // namespace

DataStructure to_data_structure(const CPlantBox::Organism &organism, const Options &options) {
    const auto organs = all_organs(organism);

    // Plant: the organism
    EntitySet plant("Plant", 1);
    plant.scale = "Plant";
    plant.set("id", std::vector<std::int64_t>{0});

    // Organ: one row per organ
    EntitySet organ_set("Organ", 5);
    organ_set.scale = "mixed";                                     // whole root and stem axes, leaves, the seed
    std::vector<std::int64_t> organ_ids, complexes, parents;
    std::vector<std::string> labels, edge_types;
    std::vector<std::int32_t> organ_types, sub_types, orders, parent_node_indices, node_counts;
    std::vector<double> ages, lengths, radii, creation_times;
    std::vector<bool> alive, active;
    for (const auto &organ : organs) {
        const auto parent = organ->getParent();
        organ_ids.push_back(ORGAN_ID_OFFSET + organ->getId());
        complexes.push_back(0);
        parents.push_back(parent ? ORGAN_ID_OFFSET + parent->getId() : NO_ID);
        edge_types.push_back(parent ? "branch" : "none");
        labels.push_back(organ_label(organ->organType()));
        organ_types.push_back(organ->organType());
        sub_types.push_back(static_cast<std::int32_t>(organ->getParameter("subType")));
        orders.push_back(static_cast<std::int32_t>(organ->getParameter("order")));
        parent_node_indices.push_back(organ->getParentNI());
        node_counts.push_back(organ->getNumberOfNodes());
        ages.push_back(organ->getAge());
        lengths.push_back(organ->getLength(true));
        radii.push_back(organ->getParameter("radius"));
        creation_times.push_back(organ->getNumberOfNodes() > 0 ? organ->getNodeCT(0) : std::nan(""));
        alive.push_back(organ->isAlive());
        active.push_back(organ->isActive());
    }
    organ_set.set("id", organ_ids).set("label", Column(labels)).set("complex", complexes).set("parent", parents)
        .set("edge_type", Column(edge_types)).set("organType", organ_types).set("subType", sub_types)
        .set("branching_order", orders).set("age", ages).set("length", lengths).set("radius", radii)
        .set("creationTime", creation_times).set("parentNI", parent_node_indices).set("numberOfNodes", node_counts)
        .set("alive", alive).set("active", active);
    organ_set.declare("organType", declared("1", "descriptor", "CPlantBox's organ type: 1 seed, 2 root, 3 stem, 4 leaf", {}, "setting"))
        .declare("subType", declared("1", "descriptor", "CPlantBox's sub type: the organ's parameter set", {}, "setting"))
        .declare("branching_order", declared("1", "descriptor", "CPlantBox's order: the branching order (0: a base organ)",
                                             "branching_order"))
        .declare("age", declared("d", "intensive", "the organ's age", "age"))
        .declare("length", declared("cm", "extensive", "the organ's realized length", "length"))
        .declare("radius", declared("cm", "intensive", "the organ's radius", "radius", "parameter"))
        .declare("creationTime", declared("d", "descriptor", "the creation time of the organ's first node"))
        .declare("parentNI", declared("1", "descriptor", "the node index, in its parent organ, where it emerges"))
        .declare("numberOfNodes", declared("1", "descriptor", "the number of its nodes"))
        .declare("alive", declared("1", "descriptor", "whether it is alive"))
        .declare("active", declared("1", "descriptor", "whether it still grows"));

    // SubOrgan: one row per segment, its id its distal node's
    std::map<std::int64_t, std::int64_t> segment_ending_at;          // node id -> segment id
    for (const auto &organ : organs)
        for (int node = 1; node < organ->getNumberOfNodes(); ++node)
            segment_ending_at[organ->getNodeId(node)] = SEGMENT_ID_OFFSET + organ->getNodeId(node);
    EntitySet segment_set("SubOrgan", 6);
    segment_set.scale = "SubOrgan";
    std::vector<std::int64_t> segment_ids, segment_complexes, segment_parents;
    std::vector<std::string> segment_labels, segment_edge_types;
    std::vector<std::int32_t> segment_organ_types, segment_sub_types;
    std::vector<double> x1, y1, z1, x2, y2, z2, segment_radii, segment_lengths, segment_creation_times;
    for (std::size_t index = 0; index < organs.size(); ++index) {
        const auto &organ = organs[index];
        const double radius = radii[index];
        for (int node = 1; node < organ->getNumberOfNodes(); ++node) {
            const auto proximal = organ->getNode(node - 1), distal = organ->getNode(node);
            segment_ids.push_back(SEGMENT_ID_OFFSET + organ->getNodeId(node));
            segment_complexes.push_back(organ_ids[index]);
            const auto parent = segment_ending_at.find(organ->getNodeId(node - 1));
            segment_parents.push_back(parent == segment_ending_at.end() ? NO_ID : parent->second);
            segment_edge_types.push_back(parent == segment_ending_at.end() ? "none" : node == 1 ? "branch" : "successor");
            segment_labels.push_back(segment_label(organ->organType()));
            segment_organ_types.push_back(organ->organType());
            segment_sub_types.push_back(sub_types[index]);
            x1.push_back(proximal.x);
            y1.push_back(proximal.y);
            z1.push_back(proximal.z);
            x2.push_back(distal.x);
            y2.push_back(distal.y);
            z2.push_back(distal.z);
            segment_radii.push_back(radius);
            segment_lengths.push_back(distal.minus(proximal).length());
            segment_creation_times.push_back(organ->getNodeCT(node));
        }
    }
    segment_set.set("id", segment_ids).set("label", Column(segment_labels)).set("complex", segment_complexes)
        .set("parent", segment_parents).set("edge_type", Column(segment_edge_types))
        .set("organType", segment_organ_types).set("subType", segment_sub_types)
        .set("x1", x1).set("y1", y1).set("z1", z1).set("x2", x2).set("y2", y2).set("z2", z2)
        .set("radius", segment_radii).set("length", segment_lengths).set("creationTime", segment_creation_times);
    segment_set.declare("organType", declared("1", "descriptor", "CPlantBox's organ type of its organ", {}, "setting"))
        .declare("subType", declared("1", "descriptor", "CPlantBox's sub type of its organ", {}, "setting"))
        .declare("x1", declared("cm", "descriptor", "proximal node, x", "proximal_end_x"))
        .declare("y1", declared("cm", "descriptor", "proximal node, y", "proximal_end_y"))
        .declare("z1", declared("cm", "descriptor", "proximal node, z", "proximal_end_z"))
        .declare("x2", declared("cm", "descriptor", "distal node, x", "distal_end_x"))
        .declare("y2", declared("cm", "descriptor", "distal node, y", "distal_end_y"))
        .declare("z2", declared("cm", "descriptor", "distal node, z", "distal_end_z"))
        .declare("radius", declared("cm", "intensive", "the segment's radius (its organ's)", "radius", "parameter"))
        .declare("length", declared("cm", "extensive", "the segment's length", "length", "derived"))
        .declare("creationTime", declared("d", "descriptor", "the creation time of its distal node"));

    DataStructure data_structure(options.id, "graph");
    data_structure.platform = "CPlantBox";
    data_structure.model = options.model;
    data_structure.entity_sets = {plant, organ_set, segment_set};
    json extras = {{"organ_id_offset", ORGAN_ID_OFFSET}, {"segment_id_offset", SEGMENT_ID_OFFSET},
                   {"length_unit", "cm"}, {"time_unit", "d"}};
    if (options.parameters_in_extras) extras["parameters"] = parameters_xml(organism);
    data_structure.extras = {{PLATFORM, extras}};
    return data_structure;
}

Frame to_frame(const CPlantBox::Organism &organism, const Options &options) {
    Frame frame;
    frame.data_structures.push_back(to_data_structure(organism, options));
    frame.time = organism.getSimTime();
    frame.time_unit = "d";
    frame.writer = {{"platform", "CPlantBox"}, {"adapter", "fspm_tf::cplantbox"}};
    frame.vocabulary_version = "0.1";
    return frame;
}

void add_geometry(DataStructure &data_structure, const std::shared_ptr<CPlantBox::MappedPlant> &plant, int resolution,
                  int leaf_resolution) {
    CPlantBox::PlantVisualiser visualiser(plant);
    visualiser.SetGeometryResolution(resolution);
    visualiser.SetLeafResolution(leaf_resolution);
    visualiser.ComputeGeometry();
    const auto points = visualiser.GetGeometry();                 // x, y, z per vertex, cm
    const auto indices = visualiser.GetGeometryIndices();
    const auto node_ids = visualiser.GetGeometryNodeIds();        // the node each vertex belongs to
    const auto &segments = data_structure.entity_set("SubOrgan");
    const auto &organs = data_structure.entity_set("Organ");
    std::map<std::int64_t, std::int64_t> segment_row, organ_row;
    const auto &segment_ids = segments.column("id").as<std::int64_t>();
    const auto &segment_complexes = segments.column("complex").as<std::int64_t>();
    for (std::size_t row = 0; row < segment_ids.size(); ++row) segment_row[segment_ids[row]] = std::int64_t(row);
    const auto &organ_ids = organs.column("id").as<std::int64_t>();
    for (std::size_t row = 0; row < organ_ids.size(); ++row) organ_row[organ_ids[row]] = std::int64_t(row);
    Mesh mesh;
    mesh.name = "plant";
    mesh.positions.reserve(points.size());
    for (const double value : points) mesh.positions.push_back(value * METRES_PER_CENTIMETRE);
    std::vector<std::int64_t> segment_rows, organ_rows, plant_rows;
    for (std::size_t vertex = 0; vertex < mesh.vertex_count(); ++vertex) {
        const auto node = vertex < node_ids.size() ? node_ids[vertex] : -1;
        const auto found = segment_row.find(SEGMENT_ID_OFFSET + node);
        if (found == segment_row.end()) {                         // a base node: no segment ends there
            segment_rows.push_back(NO_ID);
            organ_rows.push_back(NO_ID);
        } else {
            segment_rows.push_back(found->second);
            organ_rows.push_back(organ_row.at(segment_complexes[static_cast<std::size_t>(found->second)]));
        }
        plant_rows.push_back(0);
    }
    mesh.feature_rows = {{"SubOrgan", segment_rows}, {"Organ", organ_rows}, {"Plant", plant_rows}};
    mesh.indices = std::vector<std::int64_t>(indices.begin(), indices.end());
    data_structure.meshes.push_back(std::move(mesh));
}

DataStructure soil_grid(const CPlantBox::MappedSegments &segments, const std::string &id, const std::string &cells) {
    const auto &minimum = segments.minBound, &maximum = segments.maxBound, &resolution = segments.resolution;
    const std::vector<std::int64_t> shape = {std::int64_t(resolution.x), std::int64_t(resolution.y),
                                             std::int64_t(resolution.z)};
    if (shape[0] <= 0 || shape[1] <= 0 || shape[2] <= 0) throw Error("no rectangular grid set (setRectangularGrid)");
    Grid grid;
    grid.shape = shape;
    grid.origin = {minimum.x * METRES_PER_CENTIMETRE, minimum.y * METRES_PER_CENTIMETRE, minimum.z * METRES_PER_CENTIMETRE};
    grid.spacing = {(maximum.x - minimum.x) / resolution.x * METRES_PER_CENTIMETRE,
                    (maximum.y - minimum.y) / resolution.y * METRES_PER_CENTIMETRE,
                    (maximum.z - minimum.z) / resolution.z * METRES_PER_CENTIMETRE};
    grid.periodic = {false, false, false};
    grid.z_up = true;
    grid.cells = cells;
    EntitySet voxels(cells);
    std::vector<std::int64_t> ids(static_cast<std::size_t>(shape[0] * shape[1] * shape[2]));
    std::iota(ids.begin(), ids.end(), 0);
    voxels.set("id", ids);
    DataStructure soil(id, "regular_grid");
    soil.platform = "CPlantBox";
    soil.grid = grid;
    soil.entity_sets.push_back(voxels);
    return soil;
}

Mapping segments_in_soil(const CPlantBox::MappedSegments &segments, const DataStructure &plant,
                         const DataStructure &soil, const std::string &name) {
    const auto &resolution = segments.resolution;
    const auto nx = std::int64_t(resolution.x), ny = std::int64_t(resolution.y), nz = std::int64_t(resolution.z);
    const auto &segment_set = plant.entity_set("SubOrgan");
    const auto &ids = segment_set.column("id").as<std::int64_t>();
    const std::set<std::int64_t> known(ids.begin(), ids.end());
    std::vector<std::int64_t> sources, targets;
    for (const auto &[segment, cell] : segments.seg2cell) {
        if (cell < 0) continue;                                    // above the soil
        const auto id = SEGMENT_ID_OFFSET + segments.segments.at(static_cast<std::size_t>(segment)).y;
        if (!known.count(id))
            throw Error("segment " + std::to_string(segment) + " of the mapped segments is not in '" + plant.id +
                        "': set the grid without cutting segments");
        // CPlantBox's cell index has x fastest, then y, then z from the bottom: fspm-TF's is C order of (x, y, z)
        const std::int64_t i = cell % nx, j = (cell / nx) % ny, k = cell / (nx * ny);
        sources.push_back(id);
        targets.push_back((i * ny + j) * nz + k);
    }
    Mapping mapping(name, {plant.id, "SubOrgan"}, {soil.id, soil.grid ? soil.grid->cells : "Voxel"}, "containment");
    mapping.set("source", sources).set("target", targets).set("weight", std::vector<double>(sources.size(), 1.0));
    return mapping;
}

// ── A graph as a static root system ──────────────────────────────────────

namespace {

/// The factor converting a length unit to centimetres.
double to_centimetres(const std::string &unit) {
    if (unit == "m") return 100.;
    if (unit == "cm") return 1.;
    if (unit == "mm") return 0.1;
    if (unit == "um") return 1e-4;
    throw Error("length unit '" + unit + "' not converted to cm (m, cm, mm, um)");
}

/// The column of `set` holding the standard name (or, failing that, named `fallback`); nullptr if none.
const std::pair<std::string, Column> *find_variable(const EntitySet &set, const std::string &standard_name,
                                                    const std::string &fallback) {
    for (const auto &item : set.columns) {
        auto declared = set.variables.find(item.first);
        if (declared != set.variables.end() && declared->second.standard_name == standard_name) return &item;
    }
    for (const auto &item : set.columns)
        if (item.first == fallback) return &item;
    return nullptr;
}

std::vector<double> as_doubles(const Column &column) {
    return std::visit([](const auto &values) {
        using T = typename std::decay_t<decltype(values)>::value_type;
        if constexpr (std::is_arithmetic_v<T> && !std::is_same_v<T, bool>)
            return std::vector<double>(values.begin(), values.end());
        else
            throw Error("a numeric column expected");
        return std::vector<double>{};
    }, column.values);
}

std::vector<double> centimetres(const EntitySet &set, const std::pair<std::string, Column> &item) {
    auto values = as_doubles(item.second);
    auto declared = set.variables.find(item.first);
    const double factor = to_centimetres(declared == set.variables.end() ? "m" : declared->second.unit);
    for (auto &value : values) value *= factor;
    return values;
}

} // namespace

std::shared_ptr<CPlantBox::Plant> to_root_system(const DataStructure &data_structure) {
    // The segments: the entity set with the segment ends; the organs: the one their complex points to
    const EntitySet *segments = nullptr;
    const char *ends[6][2] = {{"proximal_end_x", "x1"}, {"proximal_end_y", "y1"}, {"proximal_end_z", "z1"},
                              {"distal_end_x", "x2"}, {"distal_end_y", "y2"}, {"distal_end_z", "z2"}};
    for (const auto &set : data_structure.entity_sets) {
        bool all = set.has_column("id") && set.has_column("complex");
        for (const auto &end : ends) all = all && find_variable(set, end[0], end[1]);
        if (all && (!segments || (set.rank && segments->rank && *set.rank > *segments->rank))) segments = &set;
    }
    if (!segments) throw Error("'" + data_structure.id + "': no entity set with segment ends and complexes");
    std::vector<std::vector<double>> coordinates;
    for (const auto &end : ends) coordinates.push_back(centimetres(*segments, *find_variable(*segments, end[0], end[1])));
    const auto &segment_ids = segments->column("id").as<std::int64_t>();
    const auto &segment_complexes = segments->column("complex").as<std::int64_t>();
    std::vector<std::int64_t> segment_parents(segment_ids.size(), NO_ID);
    if (segments->has_column("parent")) segment_parents = segments->column("parent").as<std::int64_t>();
    std::vector<double> segment_radii(segment_ids.size(), 0.05);
    if (auto radius = find_variable(*segments, "radius", "radius")) segment_radii = centimetres(*segments, *radius);

    const EntitySet *organs = nullptr;
    const std::set<std::int64_t> complex_ids(segment_complexes.begin(), segment_complexes.end());
    for (const auto &set : data_structure.entity_sets) {
        if (&set == segments || !set.has_column("id")) continue;
        const auto &ids = set.column("id").as<std::int64_t>();
        if (std::all_of(complex_ids.begin(), complex_ids.end(),
                        [&](std::int64_t id) { return std::find(ids.begin(), ids.end(), id) != ids.end(); })) {
            organs = &set;
            break;
        }
    }
    std::map<std::int64_t, int> organ_types;                       // CPlantBox's own frames: roots only
    if (organs && organs->has_column("organType")) {
        const auto &ids = organs->column("id").as<std::int64_t>();
        const auto types = as_doubles(organs->column("organType"));
        for (std::size_t row = 0; row < ids.size(); ++row) organ_types[ids[row]] = int(types[row]);
    }

    // Each organ's segments, in order along it (from the one whose parent is outside the organ)
    std::map<std::int64_t, std::size_t> row_of;
    for (std::size_t row = 0; row < segment_ids.size(); ++row) row_of[segment_ids[row]] = row;
    std::map<std::int64_t, std::vector<std::size_t>> rows_of_organ;
    std::map<std::size_t, std::size_t> next_in_organ;
    std::vector<std::int64_t> organ_order;                          // organs, in the order of their first segment
    for (std::size_t row = 0; row < segment_ids.size(); ++row) {
        const auto organ = segment_complexes[row];
        if (organ_types.count(organ) && organ_types[organ] != CPlantBox::Organism::ot_root) continue;
        if (!rows_of_organ.count(organ)) organ_order.push_back(organ);
        rows_of_organ[organ].push_back(row);
        const auto parent = row_of.find(segment_parents[row]);
        if (parent != row_of.end() && segment_complexes[parent->second] == organ) next_in_organ[parent->second] = row;
    }

    auto plant = std::make_shared<CPlantBox::Plant>();
    plant->initializeReader();
    auto seed = std::make_shared<CPlantBox::Seed>(plant);
    plant->addOrgan(seed);
    std::map<std::int64_t, std::shared_ptr<CPlantBox::Organ>> organ_of;
    std::map<std::size_t, std::pair<std::shared_ptr<CPlantBox::Organ>, int>> node_of_segment;  // row -> organ, node
    // Parents first: an organ's first segment's parent belongs to an organ already built
    std::vector<std::int64_t> pending = organ_order, deferred;
    std::size_t progress = 1;
    while (!pending.empty() && progress) {
        progress = 0;
        deferred.clear();
        for (const auto organ : pending) {
            const auto &rows = rows_of_organ[organ];
            std::size_t first = rows.front();
            for (const auto row : rows) {
                const auto parent = row_of.find(segment_parents[row]);
                if (parent == row_of.end() || segment_complexes[parent->second] != organ) {
                    first = row;
                    break;
                }
            }
            const auto parent_segment = row_of.find(segment_parents[first]);
            std::shared_ptr<CPlantBox::Organ> parent_organ = seed;
            int parent_node = 0;
            if (parent_segment != row_of.end()) {
                const auto found = node_of_segment.find(parent_segment->second);
                if (found == node_of_segment.end()) {               // its parent organ is not built yet
                    deferred.push_back(organ);
                    continue;
                }
                parent_organ = found->second.first;
                parent_node = found->second.second;
            }
            std::vector<std::size_t> chain = {first};
            while (next_in_organ.count(chain.back())) chain.push_back(next_in_organ[chain.back()]);
            double length = 0., radius = 0.;
            for (const auto row : chain) {
                length += std::sqrt(std::pow(coordinates[3][row] - coordinates[0][row], 2) +
                                    std::pow(coordinates[4][row] - coordinates[1][row], 2) +
                                    std::pow(coordinates[5][row] - coordinates[2][row], 2));
                radius += segment_radii[row] / double(chain.size());
            }
            auto parameter = std::make_shared<CPlantBox::RootSpecificParameter>(0, 0., length, std::vector<double>{},
                                                                               1e6, radius, 0., 1e6, false);
            auto root = std::make_shared<CPlantBox::StaticRoot>(plant->getOrganIndex(), parameter, length, parent_node);
            root->setOrganism(plant);
            if (parent_segment != row_of.end())
                root->addNode(parent_organ->getNode(parent_node), parent_organ->getNodeId(parent_node), 0.);
            else
                root->addNode(CPlantBox::Vector3d(coordinates[0][first], coordinates[1][first], coordinates[2][first]), 0.);
            for (const auto row : chain) {
                root->addNode(CPlantBox::Vector3d(coordinates[3][row], coordinates[4][row], coordinates[5][row]), 0.);
                node_of_segment[row] = {root, root->getNumberOfNodes() - 1};
            }
            parent_organ->addChild(root);
            organ_of[organ] = root;
            ++progress;
        }
        pending = deferred;
    }
    if (!pending.empty()) throw Error("'" + data_structure.id + "': organs whose parent segments are not found");
    return plant;
}

} // namespace fspm_tf::cplantbox
