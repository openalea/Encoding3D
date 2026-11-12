#!/bin/bash
# Runs tutorial 4 (README.md): builds the CPlantBox and GroIMP participants, prepares the Julia project, then runs the
# session. Needs: CPLANTBOX and CPLANTBOX_LIBRARY (as tutorial 2c), Java 21 and Maven, Julia 1.12 (JULIA, default
# julia), and metafspm's environment active (its python runs the coordinator and metafspm's side).
set -euo pipefail
cd "$(dirname "$0")"
: "${CPLANTBOX:?set CPLANTBOX to the CPlantBox source folder}" "${CPLANTBOX_LIBRARY:?set CPLANTBOX_LIBRARY to libCPlantBox.a}"
cmake -S cplantbox -B cplantbox/build -DCMAKE_BUILD_TYPE=Release -DCPLANTBOX_SOURCE_DIR="$CPLANTBOX" \
      -DCPLANTBOX_LIBRARY="$CPLANTBOX_LIBRARY" > /dev/null
cmake --build cplantbox/build -j 4 > /dev/null
mvn -q -f ../../bindings/java/pom.xml install -DskipTests
mvn -q -f ../../bindings/java/groimp/pom.xml install -DskipTests
mvn -q -f groimp/pom.xml package dependency:copy-dependencies -DincludeScope=runtime
"${JULIA:-julia}" --project=virtualplantlab -e 'using Pkg; Pkg.resolve(); Pkg.instantiate(); using encoding3d, PlantGraphs, ZMQ'
python session.py "$PWD/cplantbox/build/roots" "$PWD/groimp/target/classes:$PWD/groimp/target/dependency/*" \
       "${JULIA:-julia}" "$(command -v python)"
if command -v encoding3d > /dev/null; then encoding3d validate outputs/record/scene.fspm.json | head -1; fi
