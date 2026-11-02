# fspm_tf (C++)

The C++ codec of fspm-TF (C++17, CMake): reading and writing frames and sequences (spec 0.2). In `cplantbox/` is
CPlantBox's adapter, which turns an organism into a graph with its geometry, soil grid and segment-to-cell mapping,
and turns a graph into a static CPlantBox root system.

- `include/fspm_tf/`: the data model (`model.hpp`) and the codec (`fspm_tf.hpp`).
- `src/`: the GLB container, reading and writing, sequences, the conformance dump.
- `tools/conformance_run.cpp`: the codec's dumps of the conformance files and its written scenes, for
  `.github/actions/conformance`.
- `test/`: the tests, the conformance files included.
- `cplantbox/`: the adapter (`fspm_tf::cplantbox`), built when `FSPM_TF_CPLANTBOX_SOURCE_DIR` and
  `FSPM_TF_CPLANTBOX_LIBRARY` are given.

```bash
cmake -S bindings/cpp -B build && cmake --build build && ctest --test-dir build
```

Its one dependency is nlohmann_json (header-only, MIT), found installed or fetched. It installs as a CMake package:
`find_package(fspm_tf)`, then `target_link_libraries(... fspm_tf::fspm_tf)`. See [the documentation](../../doc/cpp.md).

Licence: GPL-3.0 (`LICENSE`), as CPlantBox; the rest of fspm-TF is CeCILL-C.
