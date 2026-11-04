"""Frame views (openalea.encoding3d.views, specification §8.1): the schema, the names checked against a frame, the
selection, and the display options ParaView's plugin draws as blocks and saves back."""
import copy

import numpy as np
import pytest

import generate

from openalea.encoding3d import views


def roots_views() -> dict:
    return {"encoding3d_views": 1, "active": "default", "configurations": {
        "default": {"layers": [
            {"name": "first order", "source": {"data_structure": "root_system", "kind": "mesh", "mesh": "roots"},
             "select": {"entity_set": "Axis", "where": {"branching_order": [1]}},
             "color_by": {"entity_set": "SubOrgan", "variable": "water_potential"}},
            {"name": "roots", "source": {"data_structure": "root_system", "kind": "segments", "entity_set": "SubOrgan"},
             "select": {"entity_set": "SubOrgan", "where": {"label": ["RootSegment"], "length": ">0"}},
             "color_by": {"entity_set": "SubOrgan", "variable": "label"}, "tube": {"radius": "radius", "scale": 2},
             "visible": False}]},
        "plain": {"layers": [
            {"name": "all", "source": {"data_structure": "root_system", "kind": "mesh", "mesh": "roots"},
             "color_by": None, "solid_color": [0.5, 0.4, 0.3], "opacity": 0.3}]}}}


def test_a_views_document_follows_the_schema():
    assert views.check_views(roots_views()).ok
    wrong = roots_views()
    del wrong["configurations"]["default"]["layers"][0]["source"]["mesh"]           # a mesh layer names its mesh
    wrong["configurations"]["plain"]["layers"][0]["range"] = [0.]
    report = views.check_views(wrong)
    assert len(report.errors) == 2, str(report)


def test_the_active_configuration_exists_and_layer_names_are_unique():
    document = roots_views()
    document["active"] = "missing"
    plain = document["configurations"]["plain"]["layers"]
    plain.append(copy.deepcopy(plain[0]))
    report = views.check_views(document)
    assert {issue.where for issue in report.errors} == {"views/active", "plain/layers/1 (all)"}, str(report)


def test_names_are_checked_against_a_frame():
    frame = generate.root_system()
    assert views.check_views(roots_views(), frame).ok
    document = roots_views()
    layers = document["configurations"]["default"]["layers"]
    layers[0]["source"]["mesh"] = "shoots"
    layers[1]["select"]["where"]["width"] = ">0"
    layers[1]["color_by"]["entity_set"] = "Axis"            # segments are coloured by their own entity set
    document["configurations"]["plain"]["layers"][0]["source"]["data_structure"] = "soil"
    messages = [issue.message for issue in views.check_views(document, frame).errors]
    assert len(messages) == 4, messages
    assert any("no mesh 'shoots'" in message for message in messages)
    assert any("no column 'width'" in message for message in messages)
    assert any("'Axis' is not an entity set" in message for message in messages)
    assert any("no data structure 'soil'" in message for message in messages)


def test_a_grid_and_segment_ends_are_needed():
    frame = generate.soil_and_roots()
    layer = {"name": "axes", "source": {"data_structure": "root_system", "kind": "segments", "entity_set": "Axis"}}
    grid = {"name": "soil", "source": {"data_structure": "root_system", "kind": "grid"}}
    report = views.check_views({"encoding3d_views": 1, "configurations": {"c": {"layers": [layer, grid]}}}, frame)
    assert len(report.errors) == 2 and "no segment ends" in report.errors[0].message
    assert "has no grid" in report.errors[1].message


def test_selection_by_values_labels_and_comparisons():
    segments = generate.root_system().data_structures[0].entity_set("SubOrgan")
    count = segments.count
    assert views.selected(segments, {}).all()
    np.testing.assert_array_equal(views.selected(segments, {"label": ["RootSegment"]}),
                                  segments.columns["label"] == "RootSegment")
    np.testing.assert_array_equal(views.selected(segments, {"label": "RootSegment", "length": ">=0.01"}),
                                  (segments.columns["label"] == "RootSegment") & (segments.columns["length"] >= 0.01))
    np.testing.assert_array_equal(views.selected(segments, {"id": [10, 12]}), np.isin(segments.columns["id"], [10, 12]))
    segments.columns["rank"] = np.ma.MaskedArray(np.arange(count), mask=[True] + [False] * (count - 1))
    assert not views.selected(segments, {"rank": "!=5"})[0]                 # a missing value never holds
    assert views.selected(segments, {"rank": "!=5"}).sum() == count - 2


def test_configurations_and_their_defaults(tmp_path):
    document = roots_views()
    assert views.configuration_names(document) == ["default", "plain"]
    name, layers = views.configuration(document)
    assert name == "default" and layers[0]["opacity"] == 1. and layers[0]["colormap"] == views.DEFAULTS["colormap"]
    assert views.configuration(document, "plain")[1][0]["opacity"] == 0.3
    with pytest.raises(KeyError, match="nothing"):
        views.configuration(document, "nothing")
    path = str(tmp_path / views.VIEWS_FILE)
    views.write_views(path, document)
    assert views.read_views(path) == document
    frame_path = str(tmp_path / "frame_000000.glb")
    assert views.views_path(frame_path) == path and views.views_path(frame_path, "other.json") is None
    with pytest.raises(ValueError, match="views"):
        views.write_views(path, {"encoding3d_views": 2, "configurations": {}})


def test_display_settings_and_back():
    _, layers = views.configuration(roots_views())
    mesh, segments = (views.display_settings(layer) for layer in layers)
    assert mesh["selector"] == "/Root/firstorder" and mesh["tube"] is None and mesh["range"] is None
    assert mesh["color_array"] == "SubOrgan.water_potential" and mesh["visible"]
    assert segments["tube"] == {"radius_array": views.TUBE_RADIUS} and not segments["visible"]
    assert views.display_settings(layers[1], {"SubOrgan.label_code"})["color_array"] == "SubOrgan.label_code"
    assert views.block_selector("2 roots/p0") == "/Root/_2rootsp0"                   # as ParaView names blocks
    unchanged = views.layer_from_display(layers[0], {})
    assert unchanged == layers[0]
    saved = views.layer_from_display(layers[1], {"visible": True, "opacity": 0.5, "representation": "Wireframe",
                                                 "color_array": "SubOrgan.label_code", "range": [0., 2.],
                                                 "log": True})
    assert saved["color_by"] == {"entity_set": "SubOrgan", "variable": "label"}
    assert saved["range"] == [0., 2.] and saved["log"] and saved["visible"] and saved["representation"] == "Wireframe"
    assert saved["tube"] == layers[1]["tube"] and saved["select"] == layers[1]["select"]
    solid = views.layer_from_display(layers[0], {"color_array": None, "solid_color": [1., 0., 0.], "range": None})
    assert solid["color_by"] is None and solid["solid_color"] == [1., 0., 0.] and solid["range"] == "auto"
    assert views.display_settings(solid)["color_array"] is None
    document = views.save_configuration(roots_views(), "mine", [saved, solid])
    assert document["active"] == "mine" and views.check_views(document, generate.root_system()).ok
    assert views.configuration(document)[1][0]["opacity"] == 0.5
    assert "mine" not in roots_views()["configurations"]                         # a copy


# ── The layers as the blocks of one representation (ParaView's plugin) ──

def test_layers_become_block_properties():
    _, layers = views.configuration(roots_views())
    layers[0]["opacity"] = 0.4
    displays = views.block_displays(layers, {"SubOrgan.water_potential", "SubOrgan.label_code"})
    assert displays["selectors"] == ["/Root/firstorder"]                       # "roots" hidden
    assert displays["colourings"] == [("/Root/firstorder", "SubOrgan.water_potential"),
                                      ("/Root/roots", "SubOrgan.label_code")]     # text: its codes
    assert displays["solid_colours"] == [] and displays["opacities"] == [("/Root/firstorder", 0.4)]
    assert displays["main_array"] == "SubOrgan.water_potential"
    assert displays["scalar_bars"] == ["SubOrgan.water_potential"] and displays["representation"] == "Surface"
    assert displays["colour_maps"]["SubOrgan.label_code"] == {"colormap": views.DEFAULTS["colormap"], "range": None,
                                                              "log": False}
    plain = views.block_displays(views.configuration(roots_views(), "plain")[1])
    assert plain["solid_colours"] == [("/Root/all", [0.5, 0.4, 0.3])] and plain["main_array"] is None
    assert plain["opacities"] == [("/Root/all", 0.3)]


def test_block_properties_read_back_into_layers():
    """What "Save Views" reads from the representation, after edits in ParaView, saved into the layers."""
    _, layers = views.configuration(roots_views())
    representation = {"BlockSelectors": ["/Root/firstorder", "/Root/roots"],          # "roots" shown
                      "BlockColorArrayNames": ["/Root/roots", "1", "SubOrgan.radius"],
                      "BlockColors": ["/Root/firstorder", "1", "0", "0"],             # "first order" solid red
                      "BlockOpacities": ["/Root/roots", "0.5"], "ColorArrayName": "SubOrgan.water_potential",
                      "DiffuseColor": [1., 1., 1.], "Opacity": 1., "Representation": "Surface",
                      "colour_maps": {"SubOrgan.radius": ([0.001, 0.004], True)}}
    first, roots = views.displays_from_blocks(layers, representation)
    assert first == {"visible": True, "opacity": 1., "representation": "Surface", "solid_color": [1., 0., 0.],
                     "color_array": None}
    assert roots == {"visible": True, "opacity": 0.5, "representation": "Surface", "color_array": "SubOrgan.radius",
                     "range": [0.001, 0.004], "log": True}
    saved = [views.layer_from_display(layer, display) for layer, display in zip(layers, (first, roots))]
    assert saved[0]["color_by"] is None and saved[0]["solid_color"] == [1., 0., 0.]
    assert saved[1]["color_by"] == {"entity_set": "SubOrgan", "variable": "radius"} and saved[1]["log"]
    assert saved[1]["tube"] == layers[1]["tube"] and saved[1]["visible"] and saved[1]["opacity"] == 0.5
    inherited = views.displays_from_blocks(layers, {"BlockSelectors": ["/Root"], "ColorArrayName": "SubOrgan.id"})
    assert [display["visible"] for display in inherited] == [True, True]           # "/Root": every block shown
    assert [display["color_array"] for display in inherited] == ["SubOrgan.id"] * 2   # the representation's own
    drawn = views.block_displays(layers)                                           # drawn, then read back as drawn
    state = {"BlockSelectors": drawn["selectors"], "Opacity": 1.,
             "BlockColorArrayNames": [value for selector, array in drawn["colourings"]
                                      for value in (selector, 1, array)],
             "colour_maps": {array: (None, False) for array in drawn["colour_maps"]}}
    unchanged = [views.layer_from_display(layer, display)
                 for layer, display in zip(layers, views.displays_from_blocks(layers, state))]
    assert unchanged == layers


# ── Selection by scale ───────────────────────────────────────────────────

def test_the_entities_containing_others_at_every_coarser_scale():
    frame = generate.root_system()
    source = frame.data_structures[0]
    assert views.ranked_sets(source) == ["Plant", "Axis", "SubOrgan"]
    segments = source.entity_set("SubOrgan")
    rows = np.array([0, segments.count - 1, -1])                    # a tap root segment, the lateral's apex, none
    found = views.ancestor_ids(source, "SubOrgan", rows)
    np.testing.assert_array_equal(found["Axis"], [100, 101, -1])
    np.testing.assert_array_equal(found["Plant"], [1000, 1000, -1])
    assert views.ancestor_ids(source, "Plant", np.array([0])) == {}
    assert views.ancestor_ids(generate.soil_and_roots().data_structures[1], "Voxel", np.array([0])) == {}


def test_picked_cells_grow_to_their_entity_and_what_it_contains():
    picked = [("plants", {"Axis.id": np.array([101., 101.]), "SubOrgan.id": np.array([60., 61.])}),
              ("soil", {"Voxel.id": np.array([3.])})]
    assert views.picked_entities(picked, "Axis") == {"plants": [101]}
    assert views.picked_entities(picked, "SubOrgan") == {"plants": [60, 61]}
    with pytest.raises(ValueError, match="'Compartment'.*Axis"):
        views.picked_entities(picked, "Compartment")
    with pytest.raises(ValueError, match="pick cells"):
        views.picked_entities([], "Axis")
    chosen = {"plants": [101]}
    sections = {"Axis.id": np.array([100., 101., np.nan]), "Compartment.id": np.array([1., 2., 3.])}
    np.testing.assert_array_equal(views.selection_mask("plants", sections, chosen, "Axis"), [False, True, False])
    np.testing.assert_array_equal(views.selection_mask("other", sections, chosen, "Axis"), [False] * 3)
    np.testing.assert_array_equal(views.selection_mask("plants", {"Plant.id": np.ones(2)}, chosen, "Axis"),
                                  [False] * 2)                       # a block without the scale: none of it
    assert views.isolated({"roots": True, "shoot": True, "sections": False, "roots selection": True},
                          ["roots selection"]) == ["roots", "shoot"]
    blocks = [["Plant", "Axis", "SubOrgan"], [], ["Plant", "Axis", "Organ", "SubOrgan", "Compartment"]]
    assert views.scale_names(blocks) == ["Plant", "Axis", "Organ", "SubOrgan", "Compartment"]   # every block's


def test_views_are_checked_without_jsonschema(monkeypatch):
    import builtins
    original = builtins.__import__

    def without_jsonschema(name, *arguments, **keywords):
        if name == "jsonschema":
            raise ImportError(name)
        return original(name, *arguments, **keywords)

    monkeypatch.setattr(builtins, "__import__", without_jsonschema)
    assert views.check_views(roots_views()).ok
    broken = copy.deepcopy(roots_views())
    del broken["configurations"]["plain"]["layers"][0]["source"]["mesh"]
    assert "names its mesh" in str(views.check_views(broken))
    assert not views.check_views({"encoding3d_views": 2, "configurations": {}}).ok
