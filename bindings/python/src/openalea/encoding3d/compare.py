"""
Comparing what a codec reads with the conformance files' expected values (``*.expected.json``), whatever the codec's
language: the codec dumps each GLB it reads as JSON (the layout of encoding3d.dump), and this compares the dumps::

    compare(actual, expected) -> [differences]         two JSON values: objects by key, arrays in order, numbers
                                                       exactly (1 and 1.0 equal), null, "Infinity", "-Infinity", text
    compare_all(dumps, conformance, instances=True) -> {file: [differences]}
                                                       every *.expected.json of the conformance folder against the
                                                       dump at the same relative path (x.expected.json: x.json); the
                                                       instances (0.4) and their archives as conformance/README.md says

The derived fields a codec evaluates (*.evaluated.json) are compared within a relative RELATIVE_TOLERANCE (a solved
operator's values depend on the solver's rounding), every other number exactly.
"""
import json
import math
import os

from openalea.encoding3d.dump import frame_to_dict


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


RELATIVE_TOLERANCE = 1e-12


def compare(actual, expected, path: str = "$", relative_tolerance: float = 0.) -> list:
    """The differences between two JSON values, as "path: what differs" lines (none when equal); numbers exactly, or
    within *relative_tolerance* of the expected ones."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: an object expected, got {type(actual).__name__}"]
        found = [f"{path}: missing key '{key}'" for key in expected if key not in actual]
        found += [f"{path}: unexpected key '{key}'" for key in actual if key not in expected]
        for key in expected:
            if key in actual:
                found += compare(actual[key], expected[key], f"{path}.{key}", relative_tolerance)
        return found
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: an array expected, got {type(actual).__name__}"]
        if len(actual) != len(expected):
            return [f"{path}: {len(actual)} items, {len(expected)} expected"]
        found = []
        for index, (left, right) in enumerate(zip(actual, expected)):
            found += compare(left, right, f"{path}[{index}]", relative_tolerance)
        return found
    if _number(expected):
        if not _number(actual) or math.isnan(float(actual)) or \
                abs(float(actual) - float(expected)) > relative_tolerance * abs(float(expected)):
            return [f"{path}: {actual!r}, {expected!r} expected"]
        return []
    if actual != expected or type(actual) is not type(expected):
        return [f"{path}: {actual!r}, {expected!r} expected"]
    return []


def load(path: str):
    """A JSON dump, or a GLB read by this package and dumped (to check this package itself)."""
    if path.endswith(".glb"):
        from openalea.encoding3d import read
        return json.loads(json.dumps(frame_to_dict(read(path))))
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def compare_files(actual_path: str, expected_path: str, relative_tolerance: float = 0.) -> list:
    return compare(load(actual_path), load(expected_path), relative_tolerance=relative_tolerance)


SKIPPED = ("coupling", "instances", "archives")   # the coupling sessions (their own run); instances: below
INSTANCES, ARCHIVES, ARCHIVE_SUFFIX = "instances", "archives", ".fspm.zip"


def instance_checks(conformance: str) -> list:
    """(dump, expected file, relative tolerance) of the instances case (specification §12) and its archives (§8.2),
    relative to the dumps' and the conformance folders:

    - instances/frame_n.json and frame_n.evaluated.json: each frame read (its instance sets), and its derived fields
      evaluated, against frame_n.expected.json and frame_n.evaluated.json (within RELATIVE_TOLERANCE);
    - instances/embedded.json and embedded.evaluated.json: the frame whose parts are embedded, against the last frame's;
    - instances/parts/<key>.json: each part read, against instances/expected/<key>.json;
    - archives/<name>/frame_n.json and frame_n.evaluated.json: each frame read from archives/<name>.fspm.zip (its
      parts from the archive), against the instances' frame_n.expected.json and frame_n.evaluated.json."""
    folder = os.path.join(conformance, INSTANCES)
    if not os.path.isdir(folder):
        return []
    frames = sorted(name[:-len(".expected.json")] for name in os.listdir(folder) if name.endswith(".expected.json"))
    checks = []

    def frame_checks(dump_folder: str, dump_name: str, frame: str) -> None:
        checks.append((f"{dump_folder}/{dump_name}.json", f"{INSTANCES}/{frame}.expected.json", 0.))
        checks.append((f"{dump_folder}/{dump_name}.evaluated.json", f"{INSTANCES}/{frame}.evaluated.json",
                       RELATIVE_TOLERANCE))
    for frame in frames:
        frame_checks(INSTANCES, frame, frame)
    if os.path.exists(os.path.join(folder, "embedded.glb")) and frames:
        frame_checks(INSTANCES, "embedded", frames[-1])
    for name in sorted(os.listdir(os.path.join(folder, "expected"))):
        checks.append((f"{INSTANCES}/parts/{name}", f"{INSTANCES}/expected/{name}", 0.))
    archives = os.path.join(conformance, ARCHIVES)
    for name in sorted(os.listdir(archives)) if os.path.isdir(archives) else []:
        if name.endswith(ARCHIVE_SUFFIX):
            for frame in frames:
                frame_checks(f"{ARCHIVES}/{name[:-len(ARCHIVE_SUFFIX)]}", frame, frame)
    return checks


def compare_all(dumps: str, conformance: str, instances: bool = True) -> dict:
    """{expected file (relative): its differences} for every *.expected.json under *conformance* (but its folders
    SKIPPED), against the dump at the same relative path under *dumps* (a missing dump is a difference); with
    *instances*, also {dump (relative): its differences} of each of instance_checks (a codec reading 0.3 only passes
    instances=False)."""
    results = {}
    for folder, _, files in sorted(os.walk(conformance)):
        if os.path.relpath(folder, conformance).split(os.sep)[0] in SKIPPED:
            continue
        for name in sorted(files):
            if not name.endswith(".expected.json"):
                continue
            expected = os.path.join(folder, name)
            relative = os.path.relpath(expected, conformance)
            actual = os.path.join(dumps, relative[:-len(".expected.json")] + ".json")
            if not os.path.exists(actual):
                results[relative] = [f"no dump {os.path.relpath(actual, dumps)}"]
                continue
            results[relative] = compare_files(actual, expected)
    for dump, expected, relative_tolerance in instance_checks(conformance) if instances else []:
        actual = os.path.join(dumps, *dump.split("/"))
        if not os.path.exists(actual):
            results[dump] = [f"no dump {dump}"]
            continue
        results[dump] = compare_files(actual, os.path.join(conformance, *expected.split("/")), relative_tolerance)
    return results
