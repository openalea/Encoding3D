"""
The Python codec's run of the conformance check, as every codec does it in its CI: read each conformance GLB and dump
it as JSON (OUT/dumps/x.json for x.glb), and write the conformance scenes again as GLB files (OUT/written/x.glb).
Then .github/actions/conformance compares the dumps with the expected values and validates the written files.

    python bindings/python/conformance_run.py CONFORMANCE OUT
"""
import json
import os
import shutil
import sys

from openalea import encoding3d
from openalea.encoding3d.dump import frame_to_dict


def main(conformance: str, out: str) -> int:
    for folder, _, files in os.walk(conformance):
        if os.path.relpath(folder, conformance).split(os.sep)[0] in ("coupling", "instances"):
            continue                                            # the coupling sessions, 0.4's instances: their own checks
        for name in sorted(files):
            if not name.endswith(".glb"):
                continue
            relative = os.path.relpath(os.path.join(folder, name), conformance)
            frame = encoding3d.read(os.path.join(conformance, relative))
            dump = os.path.join(out, "dumps", relative[:-len(".glb")] + ".json")
            written = os.path.join(out, "written", relative)
            for path in (dump, written):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(dump, "w", encoding="utf-8") as file:
                json.dump(frame_to_dict(frame), file, indent=1)
            encoding3d.write(written, frame)                       # written again from what was read
    index = os.path.join(conformance, "growing_sequence", "scene.fspm.json")
    if os.path.exists(index):
        shutil.copy(index, os.path.join(out, "written", "growing_sequence", "scene.fspm.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
