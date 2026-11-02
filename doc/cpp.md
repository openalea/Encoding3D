# Reading and writing in C++, and CPlantBox

`bindings/cpp/` holds the C++ codec (C++17). It reads and writes fspm-TF files and passes the conformance check. In
`bindings/cpp/cplantbox/` is CPlantBox's adapter. Both have tests, run in `.github/workflows/cpp-codec.yml` on
Linux, macOS and Windows.

Licence: GPL-3.0, as CPlantBox (the rest of fspm-TF is CeCILL-C).

## Building

```bash
cmake -S bindings/cpp -B build && cmake --build build && ctest --test-dir build
cmake --install build --prefix /some/prefix         # then: find_package(fspm_tf), fspm_tf::fspm_tf
```

The one dependency, nlohmann_json, is used when installed and fetched otherwise.

## The format's own tables

```cpp
#include <fspm_tf/fspm_tf.hpp>

auto frame = fspm_tf::read_frame("scene.glb");
const auto &segments = frame.data_structure("RootPopulation").entity_set("SubOrgan");
const auto &length = segments.column("length").as<double>();     // one value per segment
const auto unit = segments.variables.at("length").unit;          // its declared unit, e.g. "m"

fspm_tf::EntitySet organs("Organ", 5);
organs.set("id", std::vector<std::int64_t>{1, 2})
    .set("parent", std::vector<std::int64_t>{-1, 1})
    .set("edge_type", {"none", "branch"})
    .set("length", std::vector<double>{0.12, 0.05});
fspm_tf::Variable declaration;
declaration.unit = "m";
declaration.standard_name = "length";
organs.declare("length", declaration);
fspm_tf::DataStructure plants("plants");
plants.entity_sets.push_back(organs);
fspm_tf::Frame written;
written.data_structures.push_back(plants);
fspm_tf::write_frame("plants.glb", written);
```

A column holds a vector of numbers (any integer or float type), `bool` or `std::string`. With a `width` of 2 or
more, it holds a fixed-size vector per row. NaN and infinities are written with the specification's stand-ins and
read back as they were.

## CPlantBox

Build the adapter against CPlantBox's sources and its library:

```bash
cmake -S CPlantBox -B cpb -DCPB_BUILD_PYTHON=OFF -DPIAFMUNCH=OFF -DCPB_BUILD_SHARED=OFF && cmake --build cpb --target CPlantBox
cmake -S bindings/cpp -B build -DFSPM_TF_CPLANTBOX_SOURCE_DIR=$PWD/CPlantBox \
      -DFSPM_TF_CPLANTBOX_LIBRARY=$PWD/cpb/src/libCPlantBox.a
```

```cpp
#include <fspm_tf/cplantbox.hpp>

auto plant = std::make_shared<CPlantBox::MappedPlant>(1);
plant->readParameters("fspm2023.xml");
plant->initialize();
plant->simulate(28., false);

auto frame = fspm_tf::cplantbox::to_frame(*plant);              // Plant, Organ, SubOrgan; time in days
fspm_tf::cplantbox::add_geometry(frame.data_structures[0], plant);   // leaves and stems, triangles
plant->setRectangularGrid({-10, -10, -40}, {10, 10, 0}, {4, 4, 8}, false);
auto soil = fspm_tf::cplantbox::soil_grid(*plant);
frame.mappings.push_back(fspm_tf::cplantbox::segments_in_soil(*plant, frame.data_structures[0], soil));
frame.data_structures.push_back(soil);
fspm_tf::write_frame("plant.glb", frame);

// A soil solver's values per cell (DuMux, or Python), CPlantBox's hydraulics per node and per segment
// (PlantHydraulicModel: rx, radial fluxes), each declared with its unit and standard name
fspm_tf::Variable potential;
potential.unit = "cm[H2O]";
potential.standard_name = "soil_water_potential";
fspm_tf::cplantbox::add_cell_values(soil, *plant, {{"soil_water_potential", sx, potential}});
potential.standard_name = "water_potential";
fspm_tf::cplantbox::add_node_values(frame.data_structures[0], *plant, {{"xylem_potential", rx, potential}});
fspm_tf::Variable uptake;
uptake.unit = "cm3/d";
uptake.standard_name = "root_water_uptake";
fspm_tf::cplantbox::add_segment_values(frame.data_structures[0], *plant, {{"radial_flux", fluxes, uptake}});

// A frame (CPlantBox's, or another platform's) as a static CPlantBox root system
auto roots = fspm_tf::cplantbox::to_root_system(fspm_tf::read_frame("roots.glb").data_structures[0]);
```

| fspm-TF | CPlantBox |
|---|---|
| Plant (rank 1), id 0 | the organism |
| Organ (rank 5, scale `mixed`), id 1 + organ id | a seed, a root or a stem (labelled `RootAxis`, `ShootAxis`: a whole axis), a leaf |
| SubOrgan (rank 6), id 2^32 + distal node id | a segment; its parent is the segment ending at its proximal node |
| `x1` … `z2` (`proximal_end_*`, `distal_end_*`) | the segment's nodes, in cm (declared; readers convert, so a rebuilt root system has them bit for bit) |
| other variables | CPlantBox's names and units (`length` in cm, `age` in d, `order`, `subType`, …), with their standard names |
| `extras["cplantbox"]` | the id offsets, the organism's parameters as CPlantBox's XML |

CPlantBox's core has no soil model: the soil's values come from a solver outside it, which hands them to CPlantBox
per cell. `add_cell_values` writes them in the soil grid's cells, reordered from CPlantBox's cell order (x fastest) to
fspm-TF's (C order of x, y, z). `add_node_values` gives each segment its distal node's value.

CPlantBox has two scales below the plant. `to_root_system` reads frames with more scales by what they hold: the
segments are the entity set with segment ends, and the organs are the set their `complex` points to. For example,
metafspm's Plant, Axis and SubOrgan become CPlantBox root organs. CPlantBox has static roots only, so stems and
leaves are not rebuilt.
