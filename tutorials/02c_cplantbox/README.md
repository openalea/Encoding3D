# Tutorial 2c: CPlantBox

**What you learn:** how a CPlantBox plant (shoot and roots) is written as encoding3d frames while it grows, with its
geometry, a soil grid and which soil cell each root segment is in; and how a frame, CPlantBox's or another
platform's, becomes a CPlantBox root system again.

**What you need** (not encoding3d's requirements): a C++17 compiler, CMake, and CPlantBox built as a library. The
adapter it uses (`bindings/cpp/cplantbox/`) is a proposal for CPlantBox, kept in this repository until CPlantBox
adopts it. Build CPlantBox once (the commit the adapter was last tested with):

```bash
git clone https://github.com/Plant-Root-Soil-Interactions-Modelling/CPlantBox.git
git -C CPlantBox checkout 17e1fab617e72fa5e2773dfee723083bdf515053
cmake -S CPlantBox -B CPlantBox-build -DCMAKE_BUILD_TYPE=Release -DCPB_BUILD_PYTHON=OFF -DPIAFMUNCH=OFF \
      -DCPB_BUILD_SHARED=OFF -DCPB_NATIVE_CPU_TUNING=OFF
cmake --build CPlantBox-build --target CPlantBox -j 4
```

**How to run it:** `CPLANTBOX=/path/to/CPlantBox CPLANTBOX_LIBRARY=/path/to/CPlantBox-build/src/libCPlantBox.a ./run.sh`.
It builds the program (`cplantbox_tutorial.cpp`, with encoding3d's C++ codec from this repository), runs it, and
writes its files in `outputs/`. The program is in four parts:

1. **A plant.** CPlantBox's `fspm2023` parameters (a shoot and its roots), grown one day at a time.
2. **A frame a day.** `to_data_structure` writes the plant, its organs and its segments with CPlantBox's variables;
   `add_geometry` adds the shoot's blades and stems as a mesh; `soil_grid` and `segments_in_soil` add a soil grid
   (2 cm cells) and the mapping from root segments to cells; `add_cell_values` puts a soil water potential in the
   cells (a toy gradient, standing for the soil solver CPlantBox would be coupled with). Ten days make a sequence.
3. **Back into CPlantBox.** `to_root_system` rebuilds the last frame's roots as a CPlantBox root system.
4. **Another platform's frame.** The conformance root system (written by another platform, at three scales) becomes a
   CPlantBox root system too: the adapter reads frames by what they hold, not by who wrote them.

Open `outputs/frames/scene.fspm.json` in ParaView with encoding3d's plugin (tutorial 1): the shoot's mesh, the roots
as tubes, the soil cells.

Try it yourself: write CPlantBox's own `age` of each segment in a `views.json` colouring, or grow the plant for 30
days with Anagallis' root parameters (`plant/Anagallis_femina_Leitner_2010.xml`).
