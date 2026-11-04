"""The validator finds what breaks the specification."""
import json

import numpy as np
import pytest

import generate
from openalea.encoding3d import NO_ID, Variable, to_bytes, write_sequence
from openalea.encoding3d.glb import pack, unpack
from openalea.encoding3d.validate import validate_bytes, validate_sequence


def messages(frame) -> str:
    return str(validate_bytes(to_bytes(frame)))


def segments_of(frame):
    return frame.data_structures[0].entity_set("SubOrgan")


def test_ids():
    frame = generate.root_system()
    segments_of(frame).columns["id"][1] = segments_of(frame).columns["id"][0]
    assert "ids are not unique" in messages(frame)
    frame = generate.root_system()
    segments_of(frame).columns["id"][0] = 100                  # an Axis' id
    assert "ids are unique across the data structure" in messages(frame)


def test_mtg_relations():
    frame = generate.root_system()
    segments_of(frame).columns["parent"][3] = 999
    assert "SubOrgan/parent: 1 id(s) not in the referenced entity set" in messages(frame)
    frame = generate.root_system()
    segments_of(frame).columns["edge_type"][0] = "successor"
    assert "'none' exactly for the entities without a parent" in messages(frame)
    frame = generate.root_system()
    segments_of(frame).columns["complex"][:] = 7
    assert "SubOrgan/complex" in messages(frame)
    frame = generate.root_system()
    ids, parent = segments_of(frame).columns["id"], segments_of(frame).columns["parent"]
    parent[0] = ids[2]
    segments_of(frame).columns["edge_type"][0] = "successor"
    assert "the parents form a cycle" in messages(frame)


def test_declarations():
    frame = generate.root_system()
    variables = segments_of(frame).variables
    variables["length"] = Variable(unit="metre", standard_name="length", kind="extensive")
    variables["radius"] = Variable(unit="m", standard_name="root_radius_typo", kind="intensive")
    variables["struct_mass"] = Variable(unit="m", standard_name="structural_mass", kind="extensive")
    del variables["emerged"]
    text = messages(frame)
    assert "length: unit: unknown unit symbol 'metre'" in text
    assert "'root_radius_typo' is not in the vocabulary" in text
    assert "unit 'm' cannot be converted to 'g'" in text
    assert "warning: root_system/SubOrgan/emerged: not declared" in text
    frame = generate.root_system()
    segments_of(frame).variables["water_potential"] = Variable(unit="MPa", kind="hot")
    assert "water_potential/kind: 'hot' is not one of" in messages(frame)


def test_grid_and_mapping():
    frame = generate.soil_and_roots()
    frame.data_structures[1].grid.shape = (2, 2, 2)
    frame.mappings[0].columns["target"][0] = 99
    frame.mappings[0].columns["weight"][1] = -1.
    text = messages(frame)
    assert "12 cells, 8 expected" in text
    assert "roots_in_soil/target: 1 id(s)" in text
    assert "weights must be finite and non-negative" in text


def test_unflagged_attribute():
    document, binary = unpack(to_bytes(generate.root_system()))
    primitive = document["meshes"][0]["primitives"][0]
    primitive["attributes"]["_SECRET"] = primitive["attributes"]["_FEATURE_ID_0"]
    assert "an application attribute not declared as a display copy" in str(validate_bytes(pack(document, binary)))


def test_schema_and_tables():
    document, binary = unpack(to_bytes(generate.root_system()))
    document["extensions"]["FSPM_scene"]["frame"]["step"] = -1
    document["extensions"]["EXT_structural_metadata"]["propertyTables"][0]["count"] = 5
    text = str(validate_bytes(pack(document, binary)))
    assert "FSPM_scene/frame/step" in text
    assert "bytes of values" in text


def test_ids_never_reused(tmp_path):
    frames = generate.growing_sequence()
    first = segments_of(frames[0])
    shrunk = segments_of(frames[1])
    keep = ~np.isin(shrunk.columns["id"], first.columns["id"][-1:])     # frame 1 loses the lateral's apex
    for name in shrunk.columns:
        shrunk.columns[name] = shrunk.columns[name][keep]
    frames[1].data_structures[0].meshes = []
    index = write_sequence(str(tmp_path), frames)
    report = validate_sequence(index)
    assert "id(s) reused after their entity disappeared" in str(report), str(report)


def test_index_order(tmp_path):
    index = write_sequence(str(tmp_path), generate.growing_sequence())
    with open(index) as file:
        content = json.load(file)
    content["frames"].reverse()
    with open(index, "w") as file:
        json.dump(content, file)
    assert "frames are in time order" in str(validate_sequence(index))


def organs_of(frame):
    return frame.data_structures[0].entity_set("Organ")


def test_missing_values_scene_is_valid():
    report = validate_bytes(to_bytes(generate.missing_values()))
    assert report.ok and not report.warnings, str(report)


def test_rules_of_0_2():
    frame = generate.missing_values()
    organs_of(frame).columns["emergence"][0] = "1 March 2026"
    assert "1 value(s) not ISO 8601 date" in messages(frame)
    frame = generate.missing_values()
    organs_of(frame).columns["edge_type"][0] = "unknown"           # an unknown link needs a parent
    assert "'none' exactly for the entities without a parent" in messages(frame)
    frame = generate.missing_values()
    organs_of(frame).columns["sibling_order"][0] = -1
    assert "positions among siblings are non-negative" in messages(frame)
    frame = generate.missing_values()
    frame.data_structures[0].relations[1].name = "bearer_Axis_Organ"
    assert "two relations have the same name" in messages(frame)
    frame = generate.missing_values()
    frame.data_structures[0].relations[0].columns["relation"][0] = "sideways"
    assert "bearer labels ['sideways']" in messages(frame)
    frame = generate.missing_values()
    organs_of(frame).scale = "Organ"
    organs_of(frame).rank = 3
    assert "rank 3: the base scale Organ's position is 5" in messages(frame)
    frame = generate.missing_values()
    frame.data_structures[0].labels["Petal"] = "Corolla"
    text = messages(frame)
    assert "'Petal' is no entity's label" in text and "'Corolla' is not a label of the vocabulary" in text
    frame = generate.missing_values()
    frame.data_structures[0].extras = {"MyPlatform": {}}
    assert "key 'MyPlatform': the platform's name, in lower case" in messages(frame)


def test_boolean_with_missing_values_is_uint8():
    data = to_bytes(generate.missing_values())
    document, binary = unpack(data)
    classes = document["extensions"]["EXT_structural_metadata"]["schema"]["classes"]
    classes["plant__Organ"]["properties"]["alive"]["noData"] = 2
    assert "a boolean column with missing values is UINT8 (0, 1) with noData 255" in \
        str(validate_bytes(pack(document, binary)))
