"""The committed conformance files are what generate.py writes, and reading each GLB gives its expected values."""
import json
import os

import pytest

import generate
from conftest import CONFORMANCE
from openalea.encoding3d import from_bytes
from openalea.encoding3d.dump import frame_to_dict
from openalea.encoding3d.validate import validate_file

FILES = generate.files()


@pytest.mark.parametrize("relative", sorted(FILES))
def test_committed_files_are_generated(relative):
    if relative.endswith(".fspm.zip"):                  # an archive: the same members, methods and bytes once read
        assert generate.same_archive(os.path.join(CONFORMANCE, relative), FILES[relative]), \
            f"{relative}: run python conformance/generate.py"
        return
    with open(os.path.join(CONFORMANCE, relative), "rb") as file:
        assert file.read() == FILES[relative], f"{relative}: run python conformance/generate.py"


@pytest.mark.parametrize("relative", sorted(name for name in FILES if name.endswith(".glb")
                                             and not name.startswith(("instances/parts/", "instances/embedded"))))
def test_expected_values(relative):
    with open(os.path.join(CONFORMANCE, relative), "rb") as file:
        frame = from_bytes(file.read())
    with open(os.path.join(CONFORMANCE, relative.replace(".glb", ".expected.json")), encoding="utf-8") as file:
        expected = json.load(file)
    assert json.loads(json.dumps(frame_to_dict(frame))) == expected


@pytest.mark.parametrize("relative", sorted(name for name in FILES
                                             if name.endswith((".glb", "scene.fspm.json", ".fspm.zip"))))
def test_valid(relative):
    report = validate_file(os.path.join(CONFORMANCE, relative))
    assert report.ok and not report.warnings, str(report)
