#!/bin/bash
# GroIMP's fspm-TF plugin in GroIMP itself, headless: install it (and GroIMP's glTF plugin, which meshes the shapes)
# into a GroIMP 3.0 install, grow one of GroIMP's examples, export its 3D view as an fspm-TF frame, and check the file:
# valid fspm-TF (fspm-tf validate), every triangle with its node.
#
#   run_in_groimp.sh GROIMP GLTF_PLUGIN FSPMTF_PLUGIN OUT
#     GROIMP          a GroIMP 3.0 install (the folder holding core.jar and plugins/)
#     GLTF_PLUGIN     GroIMP's glTF plugin's folder (plugin.xml, gltf.jar, ext/)
#     FSPMTF_PLUGIN   this plugin's folder (target/plugin/fspmTF)
#     OUT             where the frame is written
set -euo pipefail
groimp=$(realpath "$1"); gltf=$(realpath "$2"); fspmtf=$(realpath "$3"); out=$(realpath -m "$4")
mkdir -p "$out" "$groimp/plugins/gltf" "$groimp/plugins/fspmTF" "$out/home"
cp -r "$gltf/." "$groimp/plugins/gltf/"
cp -r "$fspmtf/." "$groimp/plugins/fspmTF/"
frame="$out/rapeseed.glb"
rm -f "$frame"
cd "$groimp"
# the export runs in the background: the commands' input stays open while it writes
(printf '$loadExample simpleRapeseed\nrun\nrun\nrun\nexport3d %s\n' "$frame"; sleep 30; printf 'listFunctions\n') |
  java -Xmx1g -Djava.util.prefs.userRoot="$out/home" -jar core.jar -a cli > "$out/groimp.log" 2>&1
test -s "$frame" || { echo "no frame written"; tail -40 "$out/groimp.log"; exit 1; }
fspm-tf validate "$frame"
python - "$frame" <<'PYTHON'
import sys
import numpy as np
from openalea import fspm_tf
plants = fspm_tf.read(sys.argv[1]).data_structure("plants")
mesh = plants.meshes[0]
rows = mesh.feature_rows[plants.entity_sets[-1].name]
assert len(mesh.positions) > 0 and (rows >= 0).all(), "every vertex carries its node"
assert mesh.positions[:, 2].max() > 0, "the plant stands, z up"
print(f"{len(mesh.positions)} vertices, {len(np.unique(rows))} nodes drawn, of {plants.entity_sets[-1].count}")
PYTHON
