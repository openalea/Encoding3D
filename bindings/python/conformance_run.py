"""
The Python codec's run of the conformance check, as every codec does it in its CI: read each conformance GLB and dump
it as JSON (OUT/dumps/x.json for x.glb), and write the conformance scenes again as GLB files (OUT/written/x.glb).
The instances (0.4, conformance/README.md): each frame's derived fields evaluated too (OUT/dumps/instances/
x.evaluated.json), each part dumped (OUT/dumps/instances/parts/<key>.json), each frame of each archive dumped and
evaluated (OUT/dumps/archives/<name>/frame_n.json); the instances written again as a sequence, with its parts and
index (OUT/written/instances), and packed (OUT/written/archives/instances.fspm.zip). Then .github/actions/conformance
compares the dumps with the expected values and validates the written files.

    python bindings/python/conformance_run.py CONFORMANCE OUT
"""
import json
import os
import shutil
import sys

from openalea import encoding3d
from openalea.encoding3d.codec import read_part
from openalea.encoding3d.dump import _column, frame_to_dict, part_to_dict

ARCHIVE_SUFFIX = ".fspm.zip"


def _dump(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(value, file, indent=1)


def evaluated(frame) -> dict:
    """{"<data structure>/<instance set>/<field>": one list of values per instance} of every derived field."""
    return {f"{data_structure.id}/{instance_set.name}/{derived.name}":
            [_column(values) for values in encoding3d.evaluate(frame, derived.name, data_structure=data_structure.id,
                                                               instance_set=instance_set.name)]
            for data_structure in frame.data_structures for instance_set in data_structure.instance_sets
            for derived in instance_set.derived}


def main(conformance: str, out: str) -> int:
    instances_index, instances_parts = [], set()
    for folder, _, files in os.walk(conformance):
        top = os.path.relpath(folder, conformance).split(os.sep)[0]
        if top in ("coupling", "archives"):
            continue                                            # the coupling sessions: their own run; archives: below
        for name in sorted(files):
            if not name.endswith(".glb"):
                continue
            relative = os.path.relpath(os.path.join(folder, name), conformance)
            dump = os.path.join(out, "dumps", relative[:-len(".glb")] + ".json")
            if top == "instances" and os.path.basename(folder) == "parts":
                with open(os.path.join(conformance, relative), "rb") as file:
                    _dump(dump, part_to_dict(read_part(file.read(), key=name[:-len(".glb")])))
                continue
            frame = encoding3d.read(os.path.join(conformance, relative))
            _dump(dump, frame_to_dict(frame))
            written = os.path.join(out, "written", relative)
            os.makedirs(os.path.dirname(written), exist_ok=True)
            if top != "instances":
                encoding3d.write(written, frame)                           # written again from what was read
                continue
            _dump(dump[:-len(".json")] + ".evaluated.json", evaluated(frame))
            embedded = name == "embedded.glb"
            keys = encoding3d.write(written, frame, embed_parts=embedded)  # its parts in it, or under parts/
            if not embedded:
                instances_index.append({"time": frame.time, "step": frame.step, "file": name})
                instances_parts |= set(keys)
    index = os.path.join(conformance, "growing_sequence", "scene.fspm.json")
    if os.path.exists(index):
        shutil.copy(index, os.path.join(out, "written", "growing_sequence", "scene.fspm.json"))
    archives = os.path.join(conformance, "archives")
    for name in sorted(os.listdir(archives)) if os.path.isdir(archives) else []:
        if not name.endswith(ARCHIVE_SUFFIX):
            continue
        for entry in encoding3d.read_index(os.path.join(archives, name))["frames"]:
            frame = encoding3d.read(entry["path"])                         # x.fspm.zip/frame_n.glb
            dump = os.path.join(out, "dumps", "archives", name[:-len(ARCHIVE_SUFFIX)], entry["file"][:-len(".glb")])
            _dump(dump + ".json", frame_to_dict(frame))
            _dump(dump + ".evaluated.json", evaluated(frame))
    if instances_index:                                         # the instances again as a sequence, then packed
        folder = os.path.join(out, "written", "instances")
        encoding3d.write_index(os.path.join(folder, "scene.fspm.json"),
                               sorted(instances_index, key=lambda entry: entry["time"]), time_unit="d",
                               parts=sorted(instances_parts))
        os.makedirs(os.path.join(out, "written", "archives"), exist_ok=True)
        encoding3d.pack(folder, os.path.join(out, "written", "archives", "instances" + ARCHIVE_SUFFIX),
                        keep_folder=True)                     # its frames validated as files too
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
