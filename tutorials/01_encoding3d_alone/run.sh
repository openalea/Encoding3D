#!/bin/bash
# Runs tutorial 1 from start to end (as encoding3d's CI does): every cell of the notebook, its files in outputs/.
set -euo pipefail
cd "$(dirname "$0")"
python -m pytest --nbmake encoding3d_alone.ipynb
