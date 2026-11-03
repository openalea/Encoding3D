"""Frame views (openalea.fspm_tf.views, specification §8.1): the schema, the names checked against a frame, the
selection, the display options ParaView's macros apply and save back, and the macros themselves on a stand-in for
paraview.simple."""
import copy
import os
import sys
import types

import numpy as np
import pytest

import generate
from conftest import ROOT

from openalea.fspm_tf import views


def roots_views() -> dict:
    return {"fspm_tf_views": 1, "active": "default", "configurations": {
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
    report = views.check_views({"fspm_tf_views": 1, "configurations": {"c": {"layers": [layer, grid]}}}, frame)
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
        views.write_views(path, {"fspm_tf_views": 2, "configurations": {}})


def test_display_settings_and_back():
    _, layers = views.configuration(roots_views())
    mesh, segments = (views.display_settings(layer) for layer in layers)
    assert mesh["selector"] == "/Root/first_order" and mesh["tube"] is None and mesh["range"] is None
    assert mesh["color_array"] == "SubOrgan.water_potential" and mesh["visible"]
    assert segments["tube"] == {"radius_array": views.TUBE_RADIUS} and not segments["visible"]
    assert views.display_settings(layers[1], {"SubOrgan.label_code"})["color_array"] == "SubOrgan.label_code"
    assert views.block_selector("2 roots/p0") == "/Root/_2_roots_p0"
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


# ── The macros, on a stand-in for paraview.simple ────────────────────────

class _Item:
    def __init__(self, simple, kind, name, **properties):
        self.kind, self.name, self.simple = kind, name, simple
        self.__dict__.update(properties)
        simple.items[name] = self

    def UpdatePipeline(self, *arguments):
        pass

    def UpdatePropertyInformation(self):
        pass

    def GetDataInformation(self):
        names = ["SubOrgan.water_potential", "SubOrgan.label_code"]

        class Arrays:
            def GetNumberOfArrays(self):
                return len(names)

            def GetArrayInformation(self, number):
                return types.SimpleNamespace(GetName=lambda: names[number])

        return types.SimpleNamespace(GetCellDataInformation=lambda: Arrays())


class _Display:
    def __init__(self):
        self.Visibility, self.Opacity, self.Representation = 1, 1., "Surface"
        self.ColorArrayName, self.DiffuseColor, self.AmbientColor = ["POINTS", ""], [1., 1., 1.], [1., 1., 1.]

    def SetRepresentationType(self, representation):
        self.Representation = representation

    def RescaleTransferFunctionToDataRange(self, *arguments):
        pass

    def SetScalarBarVisibility(self, *arguments):
        pass


class _Colours:
    def __init__(self):
        self.RGBPoints, self.UseLogScale, self.AutomaticRescaleRangeMode = [0., 0, 0, 0, 1., 1, 1, 1], 0, "Never"

    def ApplyPreset(self, name, rescale):
        self.preset = name

    def RescaleTransferFunction(self, low, high):
        self.RGBPoints = [low, 0, 0, 0, high, 1, 1, 1]


def _stand_in(reader):
    simple = types.ModuleType("paraview.simple")
    simple.items, simple.displays, simple.colours = {}, {}, {}
    simple.active = reader(simple)
    simple.GetActiveSource = lambda: simple.active
    simple.SetActiveSource = lambda item: None
    simple.GetActiveViewOrCreate = lambda kind: "view"
    simple.Render = lambda view: None
    simple.FindSource = lambda name: simple.items.get(name)
    simple.Delete = lambda item: simple.items.pop(item.name)
    simple.ExtractBlock = lambda registrationName, Input, Selectors: _Item(simple, "block", registrationName,
                                                                         Input=Input, Selectors=Selectors)
    simple.Tube = lambda registrationName, Input: _Item(simple, "tube", registrationName, Input=Input)

    def show(item, view):
        display = simple.displays.setdefault(item.name, _Display())
        display.Visibility = 1
        return display

    def hide(item, view):
        simple.displays.setdefault(item.name, _Display()).Visibility = 0

    def colour_by(display, value):
        display.ColorArrayName = ["CELLS", value[1]] if value else ["POINTS", ""]

    simple.Show, simple.Hide, simple.ColorBy = show, hide, colour_by
    simple.GetDisplayProperties = lambda item, view: simple.displays[item.name]
    simple.GetColorTransferFunction = lambda name: simple.colours.setdefault(name, _Colours())
    package = types.ModuleType("paraview")
    package.simple = simple
    return package, simple


def _run_macro(name: str, simple_package, monkeypatch):
    monkeypatch.setitem(sys.modules, "paraview", simple_package)
    monkeypatch.setitem(sys.modules, "paraview.simple", simple_package.simple)
    path = os.path.join(ROOT, "paraview", name)
    with open(path, encoding="utf-8") as file:
        exec(compile(file.read(), path, "exec"), {"__name__": "__main__", "__file__": path})


def test_the_macros_apply_and_save_views(tmp_path, monkeypatch):
    path = str(tmp_path / views.VIEWS_FILE)
    views.write_views(path, roots_views())
    package, simple = _stand_in(lambda simple: _Item(simple, "reader", "scene.fspm.json", Configuration="",
                                                     FileName=str(tmp_path / "scene.fspm.json"), Views=""))
    _run_macro("apply_fspm_tf_views.py", package, monkeypatch)
    assert simple.items["first order"].kind == "block" and simple.items["roots"].kind == "tube"
    assert simple.items["roots block"].Selectors == ["/Root/roots"]
    assert simple.items["roots"].Scalars == ["POINTS", views.TUBE_RADIUS]
    assert simple.displays["first order"].ColorArrayName == ["CELLS", "SubOrgan.water_potential"]
    assert simple.displays["roots"].ColorArrayName == ["CELLS", "SubOrgan.label_code"]
    assert simple.displays["roots"].Visibility == 0 and simple.displays["first order"].Visibility == 1
    _run_macro("apply_fspm_tf_views.py", package, monkeypatch)                  # applied again: replaced
    assert sorted(simple.items) == ["first order", "roots", "roots block", "scene.fspm.json"]

    simple.displays["first order"].Opacity = 0.25                               # changed in ParaView, then saved
    simple.displays["roots"].Visibility = 1
    simple.colours["SubOrgan.label_code"].RescaleTransferFunction(0., 3.)
    simple.colours["SubOrgan.label_code"].AutomaticRescaleRangeMode = "Never"
    _run_macro("save_fspm_tf_views.py", package, monkeypatch)
    saved = views.read_views(path)
    first, roots = saved["configurations"]["default"]["layers"]
    assert first["opacity"] == 0.25 and roots["visible"] and roots["range"] == [0., 3.]
    assert roots["color_by"] == {"entity_set": "SubOrgan", "variable": "label"} and roots["tube"]["scale"] == 2
    assert saved["configurations"]["plain"] == roots_views()["configurations"]["plain"]
