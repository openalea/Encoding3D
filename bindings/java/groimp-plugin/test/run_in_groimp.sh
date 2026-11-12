#!/bin/bash
# GroIMP's encoding3d plugin in GroIMP itself, headless: install it (and GroIMP's glTF plugin, which meshes the shapes)
# into a GroIMP 3.0 install, grow one of GroIMP's examples, export its 3D view as an encoding3d frame, and check the file:
# valid encoding3d (encoding3d validate), every triangle with its node. Then GroIMP's log: the example grown again, a frame
# exported after each of four runs, with their index (OUT/log/scene.fspm.json), which a coupling session replays
# (bindings/python/test/test_coupling.py, ENCODING3D_GROIMP_LOG).
#
#   run_in_groimp.sh GROIMP GLTF_PLUGIN ENCODING3D_PLUGIN OUT
#     GROIMP          a GroIMP 3.0 install (the folder holding core.jar and plugins/)
#     GLTF_PLUGIN     GroIMP's glTF plugin's folder (plugin.xml, gltf.jar, ext/)
#     ENCODING3D_PLUGIN   this plugin's folder (target/plugin/encoding3d)
#     OUT             where the frame is written
set -euo pipefail
groimp=$(realpath "$1"); gltf=$(realpath "$2"); encoding3d=$(realpath "$3"); out=$(realpath -m "$4")
mkdir -p "$out" "$groimp/plugins/gltf" "$groimp/plugins/encoding3d" "$out/home"
cp -r "$gltf/." "$groimp/plugins/gltf/"
cp -r "$encoding3d/." "$groimp/plugins/encoding3d/"
frame="$out/rapeseed.glb"
rm -f "$frame"
cd "$groimp"
# the export runs in the background: the commands' input stays open while it writes
(printf '$loadExample simpleRapeseed\nrun\nrun\nrun\nexport3d %s\n' "$frame"; sleep 30; printf 'listFunctions\n') |
  java -Xmx1g -Djava.util.prefs.userRoot="$out/home" -jar core.jar -a cli > "$out/groimp.log" 2>&1
test -s "$frame" || { echo "no frame written"; tail -40 "$out/groimp.log"; exit 1; }
encoding3d validate "$frame"
python - "$frame" <<'PYTHON'
import sys
import numpy as np
from openalea import encoding3d
plants = encoding3d.read(sys.argv[1]).data_structure("plants")
mesh = plants.meshes[0]
rows = mesh.feature_rows[plants.entity_sets[-1].name]
assert len(mesh.positions) > 0 and (rows >= 0).all(), "every vertex carries its node"
assert mesh.positions[:, 2].max() > 0, "the plant stands, z up"
print(f"{len(mesh.positions)} vertices, {len(np.unique(rows))} nodes drawn, of {plants.entity_sets[-1].count}")
PYTHON

# GroIMP's log: a frame after each run
log="$out/log"
mkdir -p "$log"
(printf '$loadExample simpleRapeseed\n'; sleep 10
 for step in 0 1 2 3; do printf 'run\nexport3d %s/frame_%06d.glb\n' "$log" "$step"; sleep 25; done
 printf 'listFunctions\n') |
  java -Xmx1g -Djava.util.prefs.userRoot="$out/home" -jar core.jar -a cli > "$out/groimp_log.log" 2>&1
python - "$log" <<'PYTHON'
import os
import sys
from openalea.encoding3d import read, write, write_index
folder = sys.argv[1]
files = sorted(name for name in os.listdir(folder) if name.endswith(".glb"))
assert len(files) == 4, f"four frames expected, {files}"
for step, name in enumerate(files):        # GroIMP has no simulation clock: the log's time and step, its run count
    frame = read(os.path.join(folder, name))
    frame.time, frame.step = float(step), step
    write(os.path.join(folder, name), frame)
write_index(os.path.join(folder, "scene.fspm.json"),
            [{"time": float(step), "step": step, "file": name} for step, name in enumerate(files)], time_unit="d")
print(f"GroIMP's log: {len(files)} frames in {folder}")
PYTHON
encoding3d validate "$log/scene.fspm.json"
