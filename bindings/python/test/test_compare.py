"""Comparing a codec's dumps with the conformance files' expected values (encoding3d compare, compare-all)."""
import json
import os
import shutil

import pytest

from conftest import CONFORMANCE
from openalea.encoding3d.cli import main
from openalea.encoding3d.compare import compare, compare_all


@pytest.mark.parametrize("actual, expected, equal", [
    ({"a": [1, 2.5, None, "Infinity"]}, {"a": [1., 2.5, None, "Infinity"]}, True),     # 1 and 1.0 are equal
    ({"a": 1}, {"a": 1.0000000000000002}, False),                                     # floats exactly
    ({"a": True}, {"a": 1}, False),                                                   # a boolean is not a number
    ({"a": [1, 2]}, {"a": [2, 1]}, False),                                            # arrays in order
    ({"b": 1, "a": 2}, {"a": 2, "b": 1}, True),                                       # objects by key
    ({"a": 1}, {"a": 1, "b": 2}, False),
    ({"a": "-Infinity"}, {"a": "Infinity"}, False),
])
def test_compare(actual, expected, equal):
    assert (compare(actual, expected) == []) is equal


def test_the_differences_say_where():
    differences = compare({"x": {"y": [1, 2, 4]}, "z": 1}, {"x": {"y": [1, 2, 3]}, "w": 1})
    assert "$.x.y[2]: 4, 3 expected" in differences
    assert "$: missing key 'w'" in differences and "$: unexpected key 'z'" in differences


def test_compare_all(tmp_path):
    dumps = tmp_path / "dumps"
    for folder, _, files in os.walk(CONFORMANCE):
        for name in files:
            if name.endswith(".expected.json"):
                relative = os.path.relpath(os.path.join(folder, name), CONFORMANCE)
                target = dumps / (relative[:-len(".expected.json")] + ".json")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(os.path.join(folder, name), target)
    results = compare_all(str(dumps), CONFORMANCE, instances=False)
    assert len(results) == 10 and not any(results.values())
    assert main(["compare-all", str(dumps), CONFORMANCE, "--skip-instances"]) == 0
    assert main(["compare-all", str(dumps), CONFORMANCE]) == 1             # no dumps of the instances
    with open(dumps / "root_system.json") as file:
        dump = json.load(file)
    dump["step"] = 1
    with open(dumps / "root_system.json", "w") as file:
        json.dump(dump, file)
    (dumps / "wheat_shoot.json").unlink()
    results = compare_all(str(dumps), CONFORMANCE, instances=False)
    assert results["root_system.expected.json"] == ["$.step: 1, 0 expected"]
    assert results["wheat_shoot.expected.json"] == ["no dump wheat_shoot.json"]
    assert main(["compare-all", str(dumps), CONFORMANCE, "--skip-instances"]) == 1


def test_compare_all_the_instances_and_archives(tmp_path):
    """The Python codec's conformance run gives every dump the instances and archives checks ask for; evaluated
    values within the relative tolerance only."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "conformance_run", os.path.join(os.path.dirname(CONFORMANCE), "bindings", "python", "conformance_run.py"))
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    assert run.main(CONFORMANCE, str(tmp_path)) == 0
    dumps = str(tmp_path / "dumps")
    results = compare_all(dumps, CONFORMANCE)
    assert not any(results.values()), {name: found for name, found in results.items() if found}
    checked = [name for name in results if name.startswith(("instances/", "archives/"))]
    assert len(checked) == 2 * 2 + 2 + 5 + 4 * 2 * 2              # frames, embedded, parts, 4 archives' frames
    path = tmp_path / "dumps" / "instances" / "frame_000000.evaluated.json"
    with open(path) as file:
        values = json.load(file)
    field = next(iter(values))
    values[field][0][0] *= 1 + 1e-13
    with open(path, "w") as file:
        json.dump(values, file)
    assert not compare_all(dumps, CONFORMANCE)["instances/frame_000000.evaluated.json"]
    values[field][0][0] *= 1 + 1e-10
    with open(path, "w") as file:
        json.dump(values, file)
    assert compare_all(dumps, CONFORMANCE)["instances/frame_000000.evaluated.json"]
    written = [os.path.join(folder, file) for folder, _, files in os.walk(tmp_path / "written") for file in files
               if file.endswith((".glb", ".fspm.zip"))]
    assert main(["validate"] + written) == 0


def test_compare_a_glb_with_its_expected_values():
    glb = os.path.join(CONFORMANCE, "section_cells.glb")
    assert main(["compare", glb, glb.replace(".glb", ".expected.json")]) == 0
