# encoding3d (C++)

The C++ codec of encoding3d (C++17, CMake): reading and writing frames and sequences (spec 0.4: instance sets, derived
fields evaluated, shared parts, `.fspm.zip` archives read and packed). In `cplantbox/` is
CPlantBox's adapter, which turns an organism into a graph with its geometry, soil grid and segment-to-cell mapping,
and turns a graph into a static CPlantBox root system.

- `include/encoding3d/`: the data model (`model.hpp`) and the codec (`encoding3d.hpp`).
- `src/`: the GLB container, reading and writing, sequences, shared parts and derived fields (`parts.cpp`, SHA-256
  included), archives (`archive.cpp`), the conformance dump.
- `tools/conformance_run.cpp`: the codec's dumps of the conformance files and its written scenes, for
  `.github/actions/conformance`.
- `test/`: the tests, the conformance files included.
- `cplantbox/`: the adapter (`encoding3d::cplantbox`), built when `ENCODING3D_CPLANTBOX_SOURCE_DIR` and
  `ENCODING3D_CPLANTBOX_LIBRARY` are given.

```bash
cmake -S bindings/cpp -B build && cmake --build build && ctest --test-dir build
```

`encoding3d/coupling.hpp` is a participant of coupling sessions (its ZeroMQ transport built when libzmq is found).

Its dependencies, each found installed or fetched by CMake:

- nlohmann_json (header-only, MIT);
- minizip-ng 4 (zlib licence), for the archives: ZIP64, deflate through zlib, lzma (ZIP's method 14) through liblzma.
  It is found as the package `minizip-ng`, or `minizip` (conda-forge's build, with its compatibility layer); else
  4.0.10 is fetched and built static with deflate and lzma only (zlib and liblzma found, or fetched by it).

It installs as a CMake package: `find_package(encoding3d)`, then `target_link_libraries(... encoding3d::encoding3d)`;
an installed encoding3d needs an installed minizip-ng (a fetched one is for building in the tree). See [the documentation](../../doc/cpp.md).

Licence: GPL-3.0 (`LICENSE`), as CPlantBox; the rest of encoding3d is CeCILL-C.
