# CPlantBox's adapter: a proposal for CPlantBox

**Status: a first proposal, for CPlantBox's team to take over.** It lives here so that the C++ binding could be built
and tested before CPlantBox's team is contacted. Once they adopt it, it moves into CPlantBox, with its tests and CI.
encoding3d itself does not depend on it: the C++ codec builds without it, and encoding3d's CI does not run it.

What it does (`encoding3d/cplantbox.hpp`, namespace `encoding3d::cplantbox`):

- `to_data_structure`, `to_frame`: a CPlantBox organism (plant, organs, segments, their variables) as an encoding3d
  graph data structure, its ids stable while the plant grows;
- `add_geometry`: the plant's geometry (CPlantBox's PlantVisualiser) as a mesh;
- `soil_grid`, `segments_in_soil`, `add_cell_values`, `add_segment_values`, `add_node_values`: the soil grid, which
  cell each segment is in, and a solver's or CPlantBox's hydraulic values;
- `to_root_system`: any platform's graph back as a static CPlantBox root system.

## Building and testing it by hand

It needs CPlantBox's sources and its built library. The commit it was last tested with:
`17e1fab617e72fa5e2773dfee723083bdf515053`.

```bash
# CPlantBox's library (no Python bindings, no PiafMunch)
git clone https://github.com/Plant-Root-Soil-Interactions-Modelling/CPlantBox.git cplantbox
git -C cplantbox checkout 17e1fab617e72fa5e2773dfee723083bdf515053
cmake -S cplantbox -B cplantbox-build -DCMAKE_BUILD_TYPE=Release -DCPB_BUILD_PYTHON=OFF -DPIAFMUNCH=OFF \
      -DCPB_BUILD_SHARED=OFF -DCPB_NATIVE_CPU_TUNING=OFF
cmake --build cplantbox-build --target CPlantBox -j 4

# the codec and the adapter, from encoding3d's root
cmake -S bindings/cpp -B build -DCMAKE_BUILD_TYPE=Release -DENCODING3D_CPLANTBOX_SOURCE_DIR="$PWD/cplantbox" \
      -DENCODING3D_CPLANTBOX_LIBRARY="$PWD/cplantbox-build/src/libCPlantBox.a"
cmake --build build -j 4
ctest --test-dir build --output-on-failure

# what it wrote is valid encoding3d; its growing log replayed in a coupling session
encoding3d validate build/cplantbox/cplantbox_out/*.glb
ENCODING3D_CPLANTBOX_LOG=build/cplantbox/cplantbox_out/anagallis_log/scene.fspm.json \
  pytest bindings/python/test/test_coupling.py -k platform_log
```

The tests (`test/test_cplantbox.cpp`) export a simulated root system and a plant with its geometry, soil grid and
mapping, read them back, rebuild a root system from another platform's frame, and write a growing log (a frame a day
for six days).

Licence: GPL-3.0, as CPlantBox.
