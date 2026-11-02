// CPlantBox's adapter: an organism (a Plant, a RootSystem, a MappedPlant) as an fspm-TF graph, its leaves' and
// stems' geometry as a mesh, its soil grid and segment-to-cell mapping; and back, a graph (CPlantBox's, or another
// platform's) as a static CPlantBox root system.
//
// | fspm-TF                          | CPlantBox                                                                 |
// |----------------------------------|---------------------------------------------------------------------------|
// | Plant (rank 1), one row, id 0    | the organism                                                              |
// | Organ (rank 5), id 1 + organ id  | its organs: a seed, a root or a stem (a whole axis), a leaf; complex the  |
// |                                  | plant, parent its parent organ (branch)                                   |
// | SubOrgan (rank 6), id            | its segments: complex its organ, parent the segment ending at its         |
// |   2^32 + distal node id          | proximal node (successor along an organ, branch at a lateral's base)      |
// | positions (proximal_end_*, ...)  | node coordinates, cm converted to metres                                  |
// | other variables                  | CPlantBox's names and units (cm, d), declared with their standard names  |
// | extras["cplantbox"]              | the id offsets, the organism's parameters (its XML)                       |
//
// CPlantBox has two scales below the plant: organs and segments. A frame with more scales (e.g. metafspm's Plant,
// Axis, SubOrgan) is read through the entity set holding the segment ends (proximal_end_*, distal_end_*) and the
// coarser entity set its complex points to, whatever their names and ranks (see to_root_system).
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "fspm_tf/fspm_tf.hpp"

namespace CPlantBox {
class Organism;
class MappedPlant;
class MappedSegments;
class Plant;
} // namespace CPlantBox

namespace fspm_tf::cplantbox {

/// The name of CPlantBox's entry in a data structure's extras, and of its column in the vocabulary.
inline constexpr const char *PLATFORM = "cplantbox";
/// Organ ids are CPlantBox's organ ids plus this offset (the plant is 0).
inline constexpr std::int64_t ORGAN_ID_OFFSET = 1;
/// Segment ids are their distal node's id plus this offset: stable while the plant grows, distinct from organ ids.
inline constexpr std::int64_t SEGMENT_ID_OFFSET = std::int64_t(1) << 32;

struct Options {
    std::string id = "plant";                ///< the data structure's id
    std::optional<std::string> model;        ///< e.g. the parameter file's name
    bool parameters_in_extras = true;        ///< the organism's parameters (XML) in extras, to rebuild it
};

/// The organism as a graph data structure: its plant, organs and segments, with their variables.
DataStructure to_data_structure(const CPlantBox::Organism &organism, const Options &options = {});

/// The organism at its simulation time (days) as a frame of one data structure.
Frame to_frame(const CPlantBox::Organism &organism, const Options &options = {});

/// Adds the plant's geometry (CPlantBox's PlantVisualiser: leaf blades and stems, triangles) to its data structure, as
/// a mesh whose vertices carry their segment, organ and plant rows. resolution: PlantVisualiser's geometry
/// resolution (points around a stem), leaf_resolution: points along a leaf.
void add_geometry(DataStructure &data_structure, const std::shared_ptr<CPlantBox::MappedPlant> &plant,
                  int resolution = 8, int leaf_resolution = 20);

/// The rectangular soil grid of a MappedSegments (set by setRectangularGrid), as a regular_grid data structure of
/// `cells` (cell ids: C-order index of (x, y, z), z pointing up, metres).
DataStructure soil_grid(const CPlantBox::MappedSegments &segments, const std::string &id = "soil",
                        const std::string &cells = "Voxel");

/// The segments' soil cells (MappedSegments::seg2cell) as a mapping from the plant's SubOrgan to the soil's cells,
/// weight 1. The grid must be set without cutting segments (cut = false), so that segments keep CPlantBox's numbering.
Mapping segments_in_soil(const CPlantBox::MappedSegments &segments, const DataStructure &plant,
                         const DataStructure &soil, const std::string &name = "roots_in_soil");

/// A graph as a static CPlantBox root system (StaticRoot organs on a seed, as CPlantBox's StaticPlant builds from
/// RSML): its segments' ends as the organs' nodes, a lateral at its parent's node, each organ's radius the mean of its
/// segments'. The segments: the entity set holding the segment ends (proximal_end_* and distal_end_*, by standard
/// name or by CPlantBox's names); the organs: the entity set their complex points to. Units are converted from those
/// declared (m, cm, mm). Organs that are not roots (CPlantBox's organ_type, when written by CPlantBox) are skipped:
/// CPlantBox has static roots only.
std::shared_ptr<CPlantBox::Plant> to_root_system(const DataStructure &data_structure);

} // namespace fspm_tf::cplantbox
