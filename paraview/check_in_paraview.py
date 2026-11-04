"""
The reader inside ParaView: loads the plugin, opens conformance files and a sequence, checks their blocks, arrays and
time steps, and renders a picture of each; then a frame with views (one block per layer, the configurations'
drop-down), the macros applying and saving them, and selection by scale (the filter "encoding3d Select at scale", its
Scale drop-down, the macro showing it isolated, then going back).

    pvpython paraview/check_in_paraview.py conformance [output folder]

A design check, by hand (no test runs it): a sequence with its views.json (e.g. metafspm's
SceneRecorder(frame_views="default", display_period=...) frames of plants with shoots, roots and sections, and a soil
grid) opened, each configuration applied, saved back unchanged and changed (the round trip), then selections by the
filter "encoding3d Select at scale" (cells picked as a click would, the filter made with ParaView's selection as the GUI
makes it, its Scale switched, the time stepped), shown by the macro isolated, in a panel, one over another, and put
back; a screenshot of each step in the output folder, to look at (colours, opacities, tubes, hidden layers,
isolation). The views file is put back as it was.

    pvbatch paraview/check_in_paraview.py --design outputs/frames/scene.fspm.json screenshots
"""
import os
import runpy
import sys

from paraview import servermanager, simple

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGN = len(sys.argv) > 1 and sys.argv[1] == "--design"
conformance = sys.argv[1] if not DESIGN else None
pictures = sys.argv[2 + DESIGN] if len(sys.argv) > 2 + DESIGN else None
# (not "output": a Programmable Filter removes that name from the main module once it has run)

simple.LoadPlugin(os.path.join(HERE, "encoding3d_reader.py"), ns=globals())


def arrays(source) -> set:
    return set(source.PointData.keys()) | set(source.CellData.keys())


def configuration_names(reader) -> list:
    reader.UpdatePropertyInformation()
    return list(reader.GetProperty("ConfigurationNames"))


def blocks(source) -> int:
    return servermanager.Fetch(source).GetNumberOfBlocks()


def run_macro(name: str, source) -> None:
    simple.SetActiveSource(source)
    runpy.run_path(os.path.join(HERE, name))


def picture(source, name, colour_by, side=False):
    if pictures is None:
        return
    os.makedirs(pictures, exist_ok=True)
    view = simple.CreateView("RenderView")
    view.ViewSize = [800, 600]
    display = simple.Show(source, view)
    simple.ColorBy(display, ("CELLS", colour_by))
    display.RescaleTransferFunctionToDataRange(True)
    if side:                                            # seen from the side: z up
        view.CameraPosition, view.CameraFocalPoint, view.CameraViewUp = [0., -1., 0.], [0., 0., 0.], [0., 0., 1.]
    view.ResetCamera()
    simple.SaveScreenshot(os.path.join(pictures, f"{name}.png"), view)
    simple.Delete(view)


def check_conformance() -> None:
    roots = encoding3dreader(FileName=os.path.join(conformance, "soil_and_roots.glb"))  # noqa: F821
    roots.UpdatePipeline()
    found = arrays(roots)
    for name in ("SubOrgan.water_potential", "Axis.branching_order", "Voxel.soil_water_potential"):
        assert name in found, (name, sorted(found))
    roots_only = encoding3dreader(FileName=os.path.join(conformance, "root_system.glb"))  # noqa: F821
    picture(roots_only, "root_system", "SubOrgan.water_potential", side=True)

    shoot = encoding3dreader(FileName=os.path.join(conformance, "wheat_shoot.glb"))  # noqa: F821
    shoot.UpdatePipeline()
    assert "SubOrgan.PARa" in arrays(shoot)
    picture(shoot, "wheat_shoot", "SubOrgan.PARa")

    sequence = encoding3dreader(FileName=os.path.join(conformance, "growing_sequence", "scene.fspm.json"))  # noqa: F821
    sequence.UpdatePipelineInformation()
    assert list(sequence.TimestepValues) == [0., 1., 2.], list(sequence.TimestepValues)
    cells = []
    for time in sequence.TimestepValues:
        sequence.UpdatePipeline(time)
        cells.append(sequence.GetDataInformation().GetNumberOfCells())
    assert cells[0] < cells[1] < cells[2], cells                # the root system grows
    print("cells per time step", cells)

    # Without the plugin: ParaView's own glTF reader shows the geometry and the display copies (float32 point data)
    import tempfile

    from openalea import encoding3d
    from openalea.encoding3d.display import add_display

    with tempfile.TemporaryDirectory() as directory:
        copied = os.path.join(directory, "roots_display.glb")
        encoding3d.write(copied, add_display(encoding3d.read(os.path.join(conformance, "root_system.glb")),
                                          ["water_potential"]))
        plain = simple.glTFReader(FileName=copied)          # ParaView's own reader, not the plugin
        plain.UpdatePipeline()
        names = set(plain.PointData.keys())
        print("glTF reader", type(plain).__name__, "point data", sorted(names))
        assert any("WATER_POTENTIAL" in name for name in names), sorted(names)

    # Views: a views.json next to the frame gives one block per layer; the macros make and save the layers' items;
    # a picked segment grows to its axis, isolated, then cleared
    import shutil

    from openalea.encoding3d import views

    with tempfile.TemporaryDirectory() as directory:
        shutil.copy(os.path.join(conformance, "root_system.glb"), directory)
        layers = [{"name": "roots",
                   "source": {"data_structure": "root_system", "kind": "segments", "entity_set": "SubOrgan"},
                   "color_by": {"entity_set": "SubOrgan", "variable": "water_potential"}, "tube": {"radius": "radius"}},
                  {"name": "mesh", "source": {"data_structure": "root_system", "kind": "mesh", "mesh": "roots"},
                   "color_by": None, "opacity": 0.3, "visible": False}]
        path = os.path.join(directory, views.VIEWS_FILE)
        views.write_views(path, {"encoding3d_views": 1, "active": "default",
                                 "configurations": {"default": {"layers": layers},
                                                    "mesh only": {"layers": layers[1:]}}})
        viewed = encoding3dreader(FileName=os.path.join(directory, "root_system.glb"))  # noqa: F821
        assert configuration_names(viewed) == ["default", "mesh only"], configuration_names(viewed)
        viewed.UpdatePipeline()
        assert blocks(viewed) == 2
        simple.GetActiveViewOrCreate("RenderView")
        run_macro("apply_encoding3d_views.py", viewed)
        tube = simple.FindSource("roots")
        assert tube is not None and simple.FindSource("mesh") is not None
        simple.GetDisplayProperties(tube).Opacity = 0.5
        run_macro("save_encoding3d_views.py", viewed)
        assert views.read_views(path)["configurations"]["default"]["layers"][0]["opacity"] == 0.5
        picture(tube, "root_system_views", "SubOrgan.water_potential", side=True)

        import encoding3d_selection
        lateral = pick(tube, "Axis.id", 101.)
        selection = encoding3dSelectatscale(Input=tube)  # noqa: F821       (ParaView's selection, as the GUI takes it)
        assert selection.Selection is not None
        assert scale_names(selection) == ["Plant", "Axis", "SubOrgan"], scale_names(selection)
        assert selection.Scale == "Plant"                              # the drop-down's first, the coarsest
        selection.Scale = "Axis"
        selection.UpdatePipeline()
        grown = servermanager.Fetch(selection)
        assert grown.GetNumberOfBlocks() == 2                         # the layers, the hidden one too
        assert set(grown.GetBlock(0).GetCellData().GetArray("Axis.id").GetRange()) == {101.}, lateral
        assert 0 < grown.GetBlock(1).GetNumberOfCells() < servermanager.Fetch(viewed).GetBlock(1).GetNumberOfCells()
        made = encoding3d_selection.show_selection(selection, "isolate")
        assert sorted(made) == ["mesh selection", "roots selection", "roots selection block"], made
        assert not simple.GetDisplayProperties(tube).Visibility
        assert encoding3d_selection.back()
        assert simple.GetDisplayProperties(tube).Visibility and simple.FindSource("roots selection") is None
        simple.Delete(selection)                                      # the selection dropped
        viewed.Configuration = "mesh only"
        viewed.UpdatePipeline()
        assert blocks(viewed) == 1


def cells(name: str) -> int:
    return simple.FindSource(name).GetDataInformation().GetNumberOfCells()


def scale_names(selection) -> list:
    selection.UpdatePropertyInformation()
    return list(selection.GetProperty("ScaleNames"))


def pick(item, array: str, value: float) -> int:
    """Pick (select) the first cell of *item* whose *array* is *value*, as a click would; its index."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    data = servermanager.Fetch(item)
    leaf = data.GetBlock(0) if hasattr(data, "GetNumberOfBlocks") else data
    cell = int(np.flatnonzero(vtk_to_numpy(leaf.GetCellData().GetArray(array)) == value)[0])
    simple.SelectIDs(IDs=[0, cell], FieldType="CELL", Source=item)
    return cell


# ── The design check, by hand ────────────────────────────────────────────────

def screenshot(view, name: str) -> None:
    os.makedirs(pictures, exist_ok=True)
    path = os.path.join(pictures, f"{name}.png")
    simple.SaveScreenshot(path, view, ImageResolution=[900, 700])
    print("screenshot", path)


def layout_screenshot(layout, name: str) -> None:
    os.makedirs(pictures, exist_ok=True)
    path = os.path.join(pictures, f"{name}.png")
    simple.SaveScreenshot(path, layout, ImageResolution=[1600, 700])
    print("screenshot", path)


def side_view(view) -> None:
    """Seen from the side and a little above: z up."""
    view.CameraPosition, view.CameraFocalPoint, view.CameraViewUp = [0.3, -1., 0.35], [0., 0., 0.], [0., 0., 1.]
    view.ResetCamera()


def displayed(view, name: str) -> dict:
    display = simple.GetDisplayProperties(simple.FindSource(name), view)
    return {"visible": bool(display.Visibility), "opacity": float(display.Opacity),
            "color_array": display.ColorArrayName[1] or None,
            "representation": display.GetProperty("Representation").GetData()}


def display_mesh(layer: dict) -> bool:
    """Whether *layer* shows a component's display mesh (e.g. sections: a mesh other than the shoot's triangles),
    whatever its name ("<population> <component>")."""
    source = layer["source"]
    return source["kind"] == "mesh" and source.get("mesh") != "triangles"


def check_design(index_path: str) -> None:
    """Views and selection by scale on a sequence with its views.json, screenshots in *pictures*."""
    import json
    import shutil

    from openalea.encoding3d import views
    import encoding3d_selection

    views_file = os.path.join(os.path.dirname(os.path.abspath(index_path)), views.VIEWS_FILE)
    shutil.copy(views_file, views_file + ".before_check")
    try:
        document = views.read_views(views_file)
        name, layers = views.configuration(document)
        roots_only = [dict(layer, visible=True) for layer in layers if "roots" in layer["name"]
                      or display_mesh(layer)]                 # a second configuration: the sections shown, the
        for layer in roots_only:                              # roots by radius, a range, a log scale, a colour map
            if layer.get("tube"):
                layer.update(color_by={"entity_set": "SubOrgan", "variable": "radius"}, range=[0.002, 0.005],
                             log=True, colormap="Inferno (matplotlib)")
        views.write_views(views_file, views.save_configuration(document, "roots and sections", roots_only,
                                                               active=False))
        reader = encoding3dreader(FileName=os.path.abspath(index_path))  # noqa: F821
        names = configuration_names(reader)
        print("configurations", names)
        assert names == [name, "roots and sections"], names
        domain = reader.GetProperty("Configuration").SMProperty.GetDomain("list")
        assert [domain.GetString(number) for number in range(domain.GetNumberOfStrings())] == names
        reader.UpdatePipelineInformation()
        last = list(reader.TimestepValues)[-1] if reader.TimestepValues else None
        view = simple.GetActiveViewOrCreate("RenderView")
        view.ViewSize = [900, 700]
        view.ViewTime = last if last is not None else 0.
        reader.UpdatePipeline(last)
        assert blocks(reader) == len(layers)

        run_macro("apply_encoding3d_views.py", reader)
        side_view(view)
        screenshot(view, "1_views_default")
        before = {layer["name"]: displayed(view, layer["name"]) for layer in layers}
        print("displays", json.dumps(before))
        for layer in layers:                                # the views as the layers say
            settings = views.display_settings(layer)
            assert before[layer["name"]]["visible"] == settings["visible"], layer["name"]
            assert abs(before[layer["name"]]["opacity"] - settings["opacity"]) < 1e-9, layer["name"]

        run_macro("save_encoding3d_views.py", reader)           # saved unchanged: the same configuration
        saved = views.read_views(views_file)
        assert [views.filled(layer) for layer in saved["configurations"][name]["layers"]] == layers, \
            (saved["configurations"][name]["layers"], layers)
        shoot = next(layer["name"] for layer in layers if layer["name"].endswith("shoot"))
        simple.GetDisplayProperties(simple.FindSource(shoot), view).Opacity = 0.3
        run_macro("save_encoding3d_views.py", reader)           # changed, saved, applied again: as changed
        run_macro("apply_encoding3d_views.py", reader)
        assert abs(displayed(view, shoot)["opacity"] - 0.3) < 1e-9
        screenshot(view, "2_views_shoot_opacity_0.3")

        roots = next(layer["name"] for layer in layers if layer["name"].endswith("roots"))
        sections = next(layer["name"] for layer in layers if display_mesh(layer))
        roots_item = simple.FindSource(roots)
        data = servermanager.Fetch(roots_item)
        leaf = data.GetBlock(0) if hasattr(data, "GetNumberOfBlocks") else data
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy
        axes = vtk_to_numpy(leaf.GetCellData().GetArray("Axis.id"))
        lateral = float(axes.max())                           # the last axis: a lateral root
        pick(roots_item, "Axis.id", lateral)
        selection = encoding3dSelectatscale(Input=roots_item)  # noqa: F821   (the GUI's Filters > encoding3d, Apply)
        scales = scale_names(selection)
        print("scales", scales)
        assert scales[0] == "Plant" and "Axis" in scales and "Compartment" in scales, scales
        selection.Scale = "Axis"
        run_macro("show_encoding3d_selection.py", selection)    # the macro, MODE "isolate"
        screenshot(view, "3_isolate_axis")
        assert [layer["name"] for layer in layers if displayed(view, layer["name"])["visible"]] == []
        part = simple.FindSource(f"{roots} selection")
        assert set(servermanager.Fetch(part).GetBlock(0).GetCellData().GetArray("Axis.id").GetRange()) == {lateral}
        axis_cells = cells(f"{roots} selection block")
        selection.Scale = "Plant"                             # the drop-down changed, Apply: re-grown
        simple.Render(view)
        assert cells(f"{roots} selection block") > axis_cells, (cells(f"{roots} selection block"), axis_cells)
        screenshot(view, "4_isolate_scale_switched_to_plant")
        if reader.TimestepValues:                             # stepping in time: the same plant followed
            first = list(reader.TimestepValues)[0]
            view.ViewTime = first
            simple.Render(view)
            plant_ids = servermanager.Fetch(simple.FindSource(f"{roots} selection block")).GetBlock(0)
            print("first time step", first, "plant", plant_ids.GetCellData().GetArray("Plant.id").GetRange())
            screenshot(view, "5_isolate_plant_first_time_step")
            view.ViewTime = last
            simple.Render(view)
        run_macro("show_encoding3d_selection.py", selection)    # run again: put back
        after = {layer["name"]: displayed(view, layer["name"]) for layer in layers}
        before[shoot]["opacity"] = 0.3
        assert after == before, (after, before)                # as they were
        assert simple.FindSource(f"{roots} selection") is None
        simple.Delete(selection)                              # the selection dropped
        screenshot(view, "6_put_back")

        segment = float(vtk_to_numpy(leaf.GetCellData().GetArray("SubOrgan.id"))[
            np.flatnonzero(axes == lateral)[0]])
        pick(roots_item, "SubOrgan.id", segment)
        selection = encoding3dSelectatscale(Input=roots_item, Scale="SubOrgan")  # noqa: F821
        encoding3d_selection.show_selection(selection, "isolate")
        assert cells(f"{sections} selection") > 0             # the hidden layer's part: the segment's section
        assert displayed(view, f"{sections} selection")["visible"]
        view.ResetCamera()
        screenshot(view, "7_isolate_segment_with_its_section")
        encoding3d_selection.back()
        simple.Delete(selection)
        side_view(view)

        shoot_item = simple.FindSource(shoot)
        shoot_data = servermanager.Fetch(shoot_item)
        shoot_leaf = shoot_data.GetBlock(0) if hasattr(shoot_data, "GetNumberOfBlocks") else shoot_data
        plant = float(vtk_to_numpy(shoot_leaf.GetCellData().GetArray("Plant.id"))[0])
        pick(shoot_item, "Plant.id", plant)
        plant_selection = encoding3dSelectatscale(Input=shoot_item)  # noqa: F821   (Scale: Plant, the first)
        encoding3d_selection.show_selection(plant_selection, "panel")
        layout = simple.GetLayout(view)
        layout.SetSize(1600, 700)
        layout_screenshot(layout, "8_panel_plant")
        assert {layer["name"]: displayed(view, layer["name"]) for layer in layers} == before   # the view untouched

        panel = [proxy for proxy in encoding3d_selection._named_views().values() if proxy.SMProxy is not view.SMProxy][0]
        simple.SetActiveView(panel)                           # an axis of the plant, picked in the panel
        plant_roots = simple.FindSource(f"{roots} selection")
        plant_axes = vtk_to_numpy(servermanager.Fetch(plant_roots).GetBlock(0).GetCellData().GetArray("Axis.id"))
        pick(plant_roots, "Axis.id", float(plant_axes.max()))
        axis_selection = encoding3dSelectatscale(Input=plant_roots, Scale="Axis")  # noqa: F821
        made = encoding3d_selection.show_selection(axis_selection, "isolate", panel)
        assert f"{roots} selection 2" in made, made
        assert not displayed(panel, f"{roots} selection")["visible"]
        layout_screenshot(layout, "9_panel_an_axis_of_the_plant")
        assert encoding3d_selection.back()                       # back to the plant in the panel
        assert displayed(panel, f"{roots} selection")["visible"]
        simple.Delete(axis_selection)
        assert encoding3d_selection.back()                       # the panel closed
        simple.Delete(plant_selection)
        simple.SetActiveView(view)
        view.ViewSize = [900, 700]
        screenshot(view, "10_panel_closed")

        reader.Configuration = "roots and sections"           # the drop-down
        reader.UpdatePipeline(last)
        assert blocks(reader) == len(roots_only)
        run_macro("apply_encoding3d_views.py", reader)
        assert simple.FindSource(shoot) is None               # the other configuration's items replaced
        colours = simple.GetColorTransferFunction("SubOrgan.radius")
        points = list(colours.RGBPoints)
        assert colours.UseLogScale and abs(points[0] - 0.002) < 1e-12 and abs(points[-4] - 0.005) < 1e-12, points
        side_view(view)
        screenshot(view, "11_configuration_roots_and_sections")
        run_macro("save_encoding3d_views.py", reader)           # its range and log scale read back
        saved = views.configuration(views.read_views(views_file), "roots and sections")[1]
        assert saved == [views.filled(layer) for layer in roots_only], (saved, roots_only)
    finally:
        shutil.move(views_file + ".before_check", views_file)
    print("encoding3d design check: done, look at the screenshots in", pictures)


if DESIGN:
    check_design(sys.argv[2])
else:
    check_conformance()
print("encoding3d reader: ok")
