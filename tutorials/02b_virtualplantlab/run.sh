#!/bin/bash
# Runs tutorial 2b (Julia 1.12 or later, with VirtualPlantLab's packages: README.md); its files in outputs/.
set -euo pipefail
cd "$(dirname "$0")"
julia --project=. -e 'using Pkg; Pkg.instantiate()'
julia --project=. virtualplantlab.jl
