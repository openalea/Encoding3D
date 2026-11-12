#!/bin/bash
# Runs tutorial 2c (README.md): CPLANTBOX (CPlantBox's source folder) and CPLANTBOX_LIBRARY (its libCPlantBox.a) set,
# its files in outputs/.
set -euo pipefail
cd "$(dirname "$0")"
: "${CPLANTBOX:?set CPLANTBOX to the CPlantBox source folder}" "${CPLANTBOX_LIBRARY:?set CPLANTBOX_LIBRARY to libCPlantBox.a}"
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCPLANTBOX_SOURCE_DIR="$CPLANTBOX" -DCPLANTBOX_LIBRARY="$CPLANTBOX_LIBRARY"
cmake --build build -j 4
./build/cplantbox_tutorial "$CPLANTBOX/modelparameter/structural" outputs
if command -v encoding3d > /dev/null; then encoding3d validate outputs/frames/scene.fspm.json | head -1; fi
