# Reading and writing in C++, and CPlantBox

`bindings/cpp/` holds the C++ codec (C++17). It reads and writes encoding3d files and passes the conformance check; its
tests run in `.github/workflows/cpp-codec.yml` on Linux, macOS and Windows. In `bindings/cpp/cplantbox/` is CPlantBox's
adapter, a proposal for CPlantBox, tested by hand (below).

Licence: GPL-3.0, as CPlantBox (the rest of encoding3d is CeCILL-C).

## Building

```bash
cmake -S bindings/cpp -B build && cmake --build build && ctest --test-dir build
cmake --install build --prefix /some/prefix         # then: find_package(encoding3d), encoding3d::encoding3d
```

The dependencies, nlohmann_json and minizip-ng (archives: ZIP64, deflate through zlib, lzma through liblzma), are used
when installed and fetched otherwise (minizip-ng's package `minizip-ng`, or conda-forge's `minizip`; fetched, it is
built static with deflate and lzma only).

## The format's own tables

```cpp
#include <encoding3d/encoding3d.hpp>

auto frame = encoding3d::read_frame("scene.glb");
const auto &segments = frame.data_structure("RootPopulation").entity_set("SubOrgan");
const auto &length = segments.column("length").as<double>();     // one value per segment
const auto unit = segments.variables.at("length").unit;          // its declared unit, e.g. "m"

encoding3d::EntitySet organs("Organ", 5);
organs.set("id", std::vector<std::int64_t>{1, 2})
    .set("parent", std::vector<std::int64_t>{-1, 1})
    .set("edge_type", {"none", "branch"})
    .set("length", std::vector<double>{0.12, 0.05});
encoding3d::Variable declaration;
declaration.unit = "m";
declaration.standard_name = "length";
organs.declare("length", declaration);
encoding3d::DataStructure plants("plants");
plants.entity_sets.push_back(organs);
encoding3d::Frame written;
written.data_structures.push_back(plants);
encoding3d::write_frame("plants.glb", written);
```

A column holds a vector of numbers (any integer or float type), `bool` or `std::string`. With a `width` of 2 or
more, it holds a fixed-size vector per row. NaN and infinities are written with the specification's stand-ins and
read back as they were.

## Instances, derived fields and archives

The codec reads and writes 0.4's instance sets (specification §12, [Instances](instances.md)): an `InstanceSet` is a
table of one row per instance (`template`, `owner`, `transform`, `id` and its own variables), its `vectors` (`Ragged`)
and `derived` fields (`DerivedField`); its `parts` are keys, found through the frame (embedded, else
`parts/<key>.glb` next to it).

```cpp
auto frame = encoding3d::read_frame("run.fspm.zip/frame_000003.glb");    // a folder's file, or an archive's
const auto &sections = frame.data_structure("RootPopulation").instance_set("sections");
auto potentials = encoding3d::evaluate(frame, "water_potential");      // one vector per instance
auto part = encoding3d::frame_part(frame, sections.parts[0]);          // a Template or an Operator

encoding3d::Frame written;                                             // writing: parts added by content
const auto key = encoding3d::add_part(written, encoding3d::Operator::dense(4, 2, {1, 0, 0.75, 0.25, 0.5, 0.5, 0.25, 0.75}));
// ... an InstanceSet whose parts hold key, in a data structure of written
encoding3d::write_frame("frames/frame_000000.glb", written);           // and frames/parts/<key>.glb, once
encoding3d::pack_archive("frames", "run.fspm.zip");                    // deflate; "stored" or "lzma"
```

A `solve` operator is solved by a dense LU factorisation (with partial pivoting), once per operator and evaluation.

## Coupling with other platforms

`encoding3d/coupling.hpp` is a participant of the coupling sessions encoding3d's coordinator runs
([Coupling platforms](coupling.md)): `encoding3d::coupling::Participant(declaration)` joins one (the declaration as its
JSON; the address and name from the environment when launched by the coordinator), `next_turn()` gives each turn's
inputs until the session stops, `send_update(frame)` answers. Its folder transport needs nothing; its ZeroMQ transport
is built when CMake finds libzmq (`ENCODING3D_WITH_ZMQ`, on by default; `has_zeromq()` tells). The tool
`encoding3d_coupling_conformance` is its program for the conformance sessions.

## CPlantBox

```{note}
**A proposal for CPlantBox.** This adapter is a first proposal for CPlantBox's team to take over; it lives here until
they adopt it, then moves into CPlantBox. encoding3d does not depend on it: its requirements and CI never install
CPlantBox. To build and test it by hand, see `bindings/cpp/cplantbox/README.md`.
```

Build the adapter against CPlantBox's sources and its library:

```bash
cmake -S CPlantBox -B cpb -DCPB_BUILD_PYTHON=OFF -DPIAFMUNCH=OFF -DCPB_BUILD_SHARED=OFF && cmake --build cpb --target CPlantBox
cmake -S bindings/cpp -B build -DENCODING3D_CPLANTBOX_SOURCE_DIR=$PWD/CPlantBox \
      -DENCODING3D_CPLANTBOX_LIBRARY=$PWD/cpb/src/libCPlantBox.a
```

```cpp
#include <encoding3d/cplantbox.hpp>

auto plant = std::make_shared<CPlantBox::MappedPlant>(1);
plant->readParameters("fspm2023.xml");
plant->initialize();
plant->simulate(28., false);

auto frame = encoding3d::cplantbox::to_frame(*plant);              // Plant, Organ, SubOrgan; time in days
encoding3d::cplantbox::add_geometry(frame.data_structures[0], plant);   // leaves and stems, triangles
plant->setRectangularGrid({-10, -10, -40}, {10, 10, 0}, {4, 4, 8}, false);
auto soil = encoding3d::cplantbox::soil_grid(*plant);
frame.mappings.push_back(encoding3d::cplantbox::segments_in_soil(*plant, frame.data_structures[0], soil));
frame.data_structures.push_back(soil);
encoding3d::write_frame("plant.glb", frame);

// A soil solver's values per cell (DuMux, or Python), CPlantBox's hydraulics per node and per segment
// (PlantHydraulicModel: rx, radial fluxes), each declared with its unit and standard name
encoding3d::Variable potential;
potential.unit = "cm[H2O]";
potential.standard_name = "soil_water_potential";
encoding3d::cplantbox::add_cell_values(soil, *plant, {{"soil_water_potential", sx, potential}});
potential.standard_name = "water_potential";
encoding3d::cplantbox::add_node_values(frame.data_structures[0], *plant, {{"xylem_potential", rx, potential}});
encoding3d::Variable uptake;
uptake.unit = "cm3/d";
uptake.standard_name = "root_water_uptake";
encoding3d::cplantbox::add_segment_values(frame.data_structures[0], *plant, {{"radial_flux", fluxes, uptake}});

// A frame (CPlantBox's, or another platform's) as a static CPlantBox root system
auto roots = encoding3d::cplantbox::to_root_system(encoding3d::read_frame("roots.glb").data_structures[0]);
```

| encoding3d | CPlantBox |
|---|---|
| Plant (rank 1), id 0 | the organism |
| Organ (rank 5, scale `mixed`), id 1 + organ id | a seed, a root or a stem (labelled `RootAxis`, `ShootAxis`: a whole axis), a leaf |
| SubOrgan (rank 6), id 2^32 + distal node id | a segment; its parent is the segment ending at its proximal node |
| `x1` … `z2` (`proximal_end_*`, `distal_end_*`) | the segment's nodes, in cm (declared; readers convert, so a rebuilt root system has them bit for bit) |
| other variables | CPlantBox's names and units (`length` in cm, `age` in d, `order`, `subType`, …), with their standard names |
| `extras["cplantbox"]` | the id offsets, the organism's parameters as CPlantBox's XML |

CPlantBox's core has no soil model: the soil's values come from a solver outside it, which hands them to CPlantBox
per cell. `add_cell_values` writes them in the soil grid's cells, reordered from CPlantBox's cell order (x fastest) to
encoding3d's (C order of x, y, z). `add_node_values` gives each segment its distal node's value.

CPlantBox has two scales below the plant. `to_root_system` reads frames with more scales by what they hold: the
segments are the entity set with segment ends, and the organs are the set their `complex` points to. For example,
metafspm's Plant, Axis and SubOrgan become CPlantBox root organs. CPlantBox has static roots only, so stems and
leaves are not rebuilt.

The adapter's tests also write CPlantBox's log of a growing root system (`anagallis_log/`: a frame a day for six
days, and its index), which the CI then replays as a participant of a coupling session: a reader receives every
logged segment and value at each step.
