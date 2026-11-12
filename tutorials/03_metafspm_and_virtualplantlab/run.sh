#!/bin/bash
# Runs tutorial 3 (README.md): metafspm's environment, and Julia 1.12 (JULIA, default julia) for VirtualPlantLab's side.
set -euo pipefail
cd "$(dirname "$0")"
"${JULIA:-julia}" --project=. -e 'using Pkg; Pkg.resolve(); Pkg.instantiate(); using encoding3d, PlantGraphs, ZMQ'
python -m pytest --nbmake coupling.ipynb
