"""Units, vocabulary, display copies and the command line."""
import numpy as np
import pytest

import generate
from openalea.encoding3d import from_bytes, read, to_bytes, ucum, vocabulary, write
from openalea.encoding3d.cli import main
from openalea.encoding3d.display import add_display, remove_display


@pytest.mark.parametrize("code, other", [("mm3/(s.MPa)", "m3/(s.Pa)"), ("cm4/(hPa.d)", "m4/(s.Pa)"),
                                         ("umol/(m2.s)", "mol.m-2.s-1"), ("Cel", "K"), ("m3/m3", "1"),
                                         ("{leaf}", "1"), ("K.d", "s.K"), ("%", "1"), ("cm[H2O]", "hPa"),
                                         ("mm[Hg]", "Pa"), ("cm[H2O]/d", "Pa/s")])
def test_convertible(code, other):
    assert ucum.convertible(code, other)


@pytest.mark.parametrize("code", ["metre", "mm 2", "Cel.d", "Cel2", "m/(s", "", "°C", "3.m"])
def test_not_units(code):
    assert not ucum.is_valid(code)


def test_vocabulary():
    names = vocabulary.standard_names()
    assert all(ucum.is_valid(row["canonical_unit"]) for row in names.values())
    kinds = vocabulary.enums()["kind"]
    assert all(row["kind"] in kinds for row in names.values())
    scales = vocabulary.enums()["scales"]
    assert all(row["scale"] in scales for row in vocabulary.labels().values())
    assert all(row["plant_ontology"] == "" or row["plant_ontology"].startswith("PO:")
               for row in vocabulary.labels().values())


def test_each_platform_name_maps_to_one_standard_name():
    for platform in vocabulary.PLATFORMS:
        listed = [name.strip() for row in vocabulary.standard_names().values()
                  for name in (row[platform] or "").split(";") if name.strip()]
        assert len(listed) == len(set(listed)), platform
    assert vocabulary.platform_names("metafspm")["x1"] == "proximal_end_x"
    with pytest.raises(ValueError):
        vocabulary.platform_names("unknown")


def test_display_copies():
    frame = add_display(generate.root_system(), ["water_potential", "branching_order"])
    mesh = frame.data_structures[0].meshes[0]
    segments = frame.data_structures[0].entity_set("SubOrgan")
    rows = mesh.feature_rows["SubOrgan"]
    assert np.array_equal(mesh.display["water_potential"],
                          segments.columns["water_potential"][rows].astype(np.float32))
    assert mesh.display_sources == {"water_potential": "SubOrgan", "branching_order": "Axis"}
    again = from_bytes(to_bytes(frame))
    assert set(again.data_structures[0].meshes[0].display) == {"water_potential", "branching_order"}
    assert not remove_display(again).data_structures[0].meshes[0].display


def test_command_line(tmp_path, capsys):
    path = str(tmp_path / "roots.glb")
    write(path, generate.root_system())
    assert main(["validate", path]) == 0
    assert main(["display", path, "radius"]) == 0
    assert "radius" in read(path).data_structures[0].meshes[0].display
    assert main(["info", path]) == 0
    assert "SubOrgan rank 6: 10 entities" in capsys.readouterr().out
    assert main(["display", path, "--remove"]) == 0
    assert not read(path).data_structures[0].meshes[0].display
    with open(path, "r+b") as file:
        file.write(b"nope")
    assert main(["validate", path]) == 1
