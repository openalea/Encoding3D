"""
Comparing what a codec reads with the conformance files' expected values (``*.expected.json``), whatever the codec's
language: the codec dumps each GLB it reads as JSON (the layout of encoding3d.dump), and this compares the dumps::

    compare(actual, expected) -> [differences]         two JSON values: objects by key, arrays in order, numbers
                                                       exactly (1 and 1.0 equal), null, "Infinity", "-Infinity", text
    compare_all(dumps, conformance) -> {file: [differences]}
                                                       every *.expected.json of the conformance folder against the
                                                       dump at the same relative path (x.expected.json: x.json)
"""
import json
import math
import os

from openalea.encoding3d.dump import frame_to_dict


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compare(actual, expected, path: str = "$") -> list:
    """The differences between two JSON values, as "path: what differs" lines (none when equal)."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: an object expected, got {type(actual).__name__}"]
        found = [f"{path}: missing key '{key}'" for key in expected if key not in actual]
        found += [f"{path}: unexpected key '{key}'" for key in actual if key not in expected]
        for key in expected:
            if key in actual:
                found += compare(actual[key], expected[key], f"{path}.{key}")
        return found
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: an array expected, got {type(actual).__name__}"]
        if len(actual) != len(expected):
            return [f"{path}: {len(actual)} items, {len(expected)} expected"]
        found = []
        for index, (left, right) in enumerate(zip(actual, expected)):
            found += compare(left, right, f"{path}[{index}]")
        return found
    if _number(expected):
        if not _number(actual) or float(actual) != float(expected) or (math.isnan(float(actual))):
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


def compare_files(actual_path: str, expected_path: str) -> list:
    return compare(load(actual_path), load(expected_path))


def compare_all(dumps: str, conformance: str) -> dict:
    """{expected file (relative): its differences} for every *.expected.json under *conformance*, against the dump at
    the same relative path under *dumps* (a missing dump is a difference)."""
    results = {}
    for folder, _, files in sorted(os.walk(conformance)):
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
    return results
