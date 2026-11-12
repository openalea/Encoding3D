#!/bin/bash
# Runs tutorial 2a from start to end, in an environment with metafspm (README.md); its files in outputs/.
set -euo pipefail
cd "$(dirname "$0")"
python -m pytest --nbmake metafspm.ipynb
