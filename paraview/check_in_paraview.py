"""
The plugin inside ParaView: loads plugin_encoding3d.py, opens conformance files and a sequence, checks their blocks,
arrays and time steps, and renders a picture of each; then a frame with views (one block per layer, drawn by the
plugin as its layers when shown, the configurations' drop-down, "Save Views"), and selection by scale (the filter
"encoding3d Select at scale", its Scale drop-down, its Isolate and Put Back buttons).

    pvpython paraview/check_in_paraview.py conformance [output folder]

A design check, by hand (no test runs it): a sequence with its views.json (e.g. metafspm's
SceneRecorder(frame_views="default", display_period=...) frames of plants with shoots, roots and sections, and a soil
grid) opened and shown as the GUI's Apply does (each layer its colouring and opacity, with no macro), a configuration
of distinct colour maps added and chosen in the drop-down, the display saved back unchanged and changed (the round
trip, "Save Views" and "Save As"), then selections by the filter "encoding3d Select at scale" (cells picked as a click
would, the filter made with ParaView's selection as the GUI makes it, its Scale switched, the time stepped), shown by
its buttons isolated, in a panel, one over another, and put back; a screenshot of each step in the output folder, to
look at (colours, opacities, tubes, hidden layers, isolation). Run it on a copy of the frames: the views file is put
back as it was, but the check writes it meanwhile.

    pvbatch paraview/check_in_paraview.py --design copy/frames/scene.fspm.json screenshots

An instances check, by hand: the conformance sequence instances/ (specification §12: root segments drawn by sections,
instances of shared templates, with a derived field) copied with a views.json, opened as a folder and as a .fspm.zip
archive; the sections drawn as placed templates with their own fields, a section picked and selected at the scale of
its segment (the filter "encoding3d Select at scale"), its derived field rebuilt and compared with
openalea.encoding3d.evaluate, isolated, shown in a panel, put back; "Evaluate Derived Fields" on the reader; a
screenshot of each step.

    pvbatch paraview/check_in_paraview.py --instances screenshots
"""
import os
import sys

from paraview import servermanager, simple

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGN = len(sys.argv) > 1 and sys.argv[1] == "--design"
INSTANCES = len(sys.argv) > 1 and sys.argv[1] == "--instances"
conformance = sys.argv[1] if not (DESIGN or INSTANCES) else None
pictures = (sys.argv[2] if len(sys.argv) > 2 else None) if INSTANCES else \
    (sys.argv[2 + DESIGN] if len(sys.argv) > 2 + DESIGN else None)
# (not "output": a Programmable Filter removes that name from the main module once it has run)

simple.LoadPlugin(os.path.join(HERE, "plugin_encoding3d.py"), ns=globals())
import encoding3d_displays  # noqa: E402       (on ParaView's path once the plugin is loaded)


def arrays(source) -> set:
    return set(source.PointData.keys()) | set(source.CellData.keys())


def configuration_names(reader) -> list:
    reader.UpdatePropertyInformation()
    return list(reader.GetProperty("ConfigurationNames"))


def blocks(source) -> int:
    return servermanager.Fetch(source).GetNumberOfBlocks()


def block_names(source) -> list:
    """The names of *source*'s blocks, in order (its hierarchy's labels: Fetch renames them)."""
    hierarchy = source.GetDataInformation().DataInformation.GetHierarchy()
    return [hierarchy.GetAttributeOrDefault(node, "label", hierarchy.GetNodeName(node))
            for node in hierarchy.GetChildNodes(hierarchy.GetRootNode(), False)]


def picture(source, name, colour_by, side=False):
    if pictures is None:
        return
    os.makedirs(pictures, exist_ok=True)
    active = simple.GetActiveView()
    view = simple.CreateView("RenderView")
    view.ViewSize = [800, 600]
    display = simple.Show(source, view)
    if colour_by:
        simple.ColorBy(display, ("CELLS", colour_by))
        display.RescaleTransferFunctionToDataRange(True)
    if side:                                            # seen from the side: z up
        view.CameraPosition, view.CameraFocalPoint, view.CameraViewUp = [0., -1., 0.], [0., 0., 0.], [0., 0., 1.]
    view.ResetCamera()
    simple.SaveScreenshot(os.path.join(pictures, f"{name}.png"), view)
    simple.Delete(view)
    if active is not None:
        simple.SetActiveView(active)                    # the view picked on afterwards


def drawn(display) -> dict:
    """The block properties of a display, as the plugin set them."""
    return {name: [str(value) for value in display.GetProperty(name)]
            for name in ("BlockSelectors", "BlockColorArrayNames", "BlockColors", "BlockOpacities")}


def pairs(values: list, size: int) -> dict:
    return {values[start]: values[start + 1:start + size] for start in range(0, len(values), size)}


def check_drawn(display, layers: list, selection: bool = False) -> None:
    """*display* drawn as *layers* say: shown blocks, colourings, solid colours, opacities."""
    from openalea.encoding3d import views
    found = drawn(display)
    if selection:
        layers = [dict(layer, visible=True) for layer in layers]
    expected = views.block_displays(layers, set(display.Input.CellData.keys()))
    assert found["BlockSelectors"] == expected["selectors"], (found, expected)
    colourings = {selector: values[1] for selector, values in pairs(found["BlockColorArrayNames"], 3).items()}
    assert colourings == dict(expected["colourings"]), (colourings, expected)
    opacities = {selector: float(values[0]) for selector, values in pairs(found["BlockOpacities"], 2).items()}
    assert opacities == dict(expected["opacities"]), (opacities, expected)
    assert set(pairs(found["BlockColors"], 4)) == {selector for selector, _ in expected["solid_colours"]}
    if expected["main_array"]:
        assert display.ColorArrayName[1] == expected["main_array"], display.ColorArrayName


def flat_index(source, name: str) -> int:
    """The flat index of the reader's (or a selection's) block *name* (the root is 0)."""
    return block_names(source).index(name) + 1


def pick(item, block: str, array: str, value: float) -> int:
    """Pick (select) the first cell of *item*'s *block* whose *array* is *value*, as a click would; its index."""
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    data = servermanager.Fetch(item)
    leaf = data.GetBlock(block_names(item).index(block))
    cell = int(np.flatnonzero(vtk_to_numpy(leaf.GetCellData().GetArray(array)) == value)[0])
    simple.SelectCompositeDataIDs(IDs=[flat_index(item, block), 0, cell], FieldType="CELL", Source=item)
    return cell


def cells(source, block: str) -> int:
    data = servermanager.Fetch(source)
    return data.GetBlock(block_names(source).index(block)).GetNumberOfCells()


def scale_names(selection) -> list:
    selection.UpdatePropertyInformation()
    return list(selection.GetProperty("ScaleNames"))


def visible(item, view) -> bool:
    return bool(simple.GetDisplayProperties(item, view).Visibility)


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
    counts = []
    for time in sequence.TimestepValues:
        sequence.UpdatePipeline(time)
        counts.append(sequence.GetDataInformation().GetNumberOfCells())
    assert counts[0] < counts[1] < counts[2], counts             # the root system grows
    print("cells per time step", counts)
    sequence.TimeUnit = "h"                                       # the times shown in hours: the files' days
    sequence.UpdatePipelineInformation()
    assert list(sequence.TimestepValues) == [0., 24., 48.], list(sequence.TimestepValues)
    sequence.UpdatePipeline(24.)
    assert sequence.GetDataInformation().GetNumberOfCells() == counts[1]
    sequence.TimeUnit = "d"

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

    # Views: a views.json next to the frame gives one block per layer, each drawn as its layer when shown; "Save
    # Views" writes the display back; a picked segment grows to its axis, isolated, then put back
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
        assert block_names(viewed) == ["roots", "mesh"], block_names(viewed)
        view = simple.GetActiveViewOrCreate("RenderView")
        display = simple.Show(viewed, view)                   # as the GUI's Apply: drawn as its layers
        check_drawn(display, views.configuration(views.read_views(path))[1])
        display.BlockOpacities = [views.block_selector("roots"), "0.5"]
        viewed.InvokeCommand("SaveViews")                     # the reader's button
        assert views.read_views(path)["configurations"]["default"]["layers"][0]["opacity"] == 0.5
        picture(viewed, "root_system_views", None, side=True)

        lateral = pick(viewed, "roots", "Axis.id", 101.)
        selection = encoding3dSelectatscale(Input=viewed)  # noqa: F821       (ParaView's selection, as the GUI takes it)
        assert selection.Selection is not None
        assert scale_names(selection) == ["Plant", "Axis", "SubOrgan"], scale_names(selection)
        assert selection.Scale == "Plant"                              # the drop-down's first, the coarsest
        selection.Scale = "Axis"
        selection.UpdatePipeline()
        grown = servermanager.Fetch(selection)
        assert grown.GetNumberOfBlocks() == 2                         # the layers, the hidden one too
        assert set(grown.GetBlock(0).GetCellData().GetArray("Axis.id").GetRange()) == {101.}, lateral
        assert 0 < grown.GetBlock(1).GetNumberOfCells() < servermanager.Fetch(viewed).GetBlock(1).GetNumberOfCells()
        selection_display = simple.Show(selection, view)              # as the GUI's Apply: drawn as the layers
        check_drawn(selection_display, views.configuration(views.read_views(path))[1], selection=True)
        legend = simple.GetScalarBar(simple.GetDisplayProperties(viewed, view).LookupTable, view)
        legend.Visibility = 1                                         # a legend shown, as the GUI's Apply does
        selection.InvokeCommand("Isolate")
        assert not visible(viewed, view) and visible(selection, view)
        selection.InvokeCommand("PutBack")
        assert visible(viewed, view) and not visible(selection, view)
        assert legend.Visibility                                      # put back with what Isolate hid
        selection.InvokeCommand("Isolate")
        selection.InvokeCommand("ShowInPanel")                        # puts the isolation back first
        assert visible(viewed, view) and legend.Visibility
        selection.InvokeCommand("PutBack")
        simple.Delete(selection)                                      # the selection dropped
        viewed.Configuration = "mesh only"                            # the drop-down: drawn again
        simple.Render(view)
        assert block_names(viewed) == ["mesh"]
        check_drawn(display, views.configuration(views.read_views(path), "mesh only")[1])


# ── The design check, by hand ────────────────────────────────────────────────

def screenshot(view, name: str) -> None:
    if pictures is None:
        return
    os.makedirs(pictures, exist_ok=True)
    path = os.path.join(pictures, f"{name}.png")
    simple.SaveScreenshot(path, view, ImageResolution=[900, 700])
    print("screenshot", path)


def layout_screenshot(layout, name: str) -> None:
    if pictures is None:
        return
    os.makedirs(pictures, exist_ok=True)
    path = os.path.join(pictures, f"{name}.png")
    simple.SaveScreenshot(path, layout, ImageResolution=[1600, 700])
    print("screenshot", path)


def side_view(view) -> None:
    """Seen from the side and a little above: z up."""
    view.CameraPosition, view.CameraFocalPoint, view.CameraViewUp = [0.3, -1., 0.35], [0., 0., 0.], [0., 0., 1.]
    view.ResetCamera()


def display_mesh(layer: dict) -> bool:
    """Whether *layer* shows a component's display mesh (e.g. sections: a mesh other than the shoot's triangles),
    whatever its name ("<population> <component>")."""
    source = layer["source"]
    return source["kind"] == "mesh" and source.get("mesh") != "triangles"


def check_design(index_path: str) -> None:
    """The plugin's layers and selection by scale on a sequence with its views.json, screenshots in *pictures*."""
    import json
    import shutil

    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy

    from openalea.encoding3d import views

    views_file = os.path.join(os.path.dirname(os.path.abspath(index_path)), views.VIEWS_FILE)
    shutil.copy(views_file, views_file + ".before_check")
    try:
        document = views.read_views(views_file)
        name, layers = views.configuration(document)
        shoot = next(layer["name"] for layer in layers if layer["name"].endswith("shoot"))
        roots = next(layer["name"] for layer in layers if layer["name"].endswith("roots"))
        sections = next(layer["name"] for layer in layers if display_mesh(layer))
        grids = [layer["name"] for layer in layers if layer["source"]["kind"] == "grid"]
        maps = {shoot: "Cool to Warm", roots: "Inferno (matplotlib)"}         # a configuration of distinct maps
        distinct = [dict(layer, colormap=maps.get(layer["name"], layer["colormap"])) for layer in layers]
        roots_only = [dict(layer, visible=True) for layer in layers if layer["name"] in (roots, sections)]
        for layer in roots_only:                              # and one of the roots by radius, a range, a log scale
            if layer.get("tube"):
                layer.update(color_by={"entity_set": "SubOrgan", "variable": "radius"}, range=[0.0002, 0.002],
                             log=True, colormap="Inferno (matplotlib)")
        document = views.save_configuration(document, "distinct colour maps", distinct, active=False)
        views.write_views(views_file, views.save_configuration(document, "roots and sections", roots_only,
                                                               active=False))
        reader = encoding3dreader(FileName=os.path.abspath(index_path))  # noqa: F821
        names = configuration_names(reader)
        print("configurations", names)
        assert names == [name, "distinct colour maps", "roots and sections"], names
        domain = reader.GetProperty("Configuration").SMProperty.GetDomain("list")
        assert [domain.GetString(number) for number in range(domain.GetNumberOfStrings())] == names
        reader.UpdatePipelineInformation()
        last = list(reader.TimestepValues)[-1] if reader.TimestepValues else None
        view = simple.GetActiveViewOrCreate("RenderView")
        view.ViewSize = [900, 700]
        view.ViewTime = last if last is not None else 0.
        reader.UpdatePipeline(last)
        assert blocks(reader) == len(layers)

        display = simple.Show(reader, view)                   # as the GUI's Apply: no macro, drawn as the layers
        check_drawn(display, layers)
        print("drawn", json.dumps(drawn(display)))
        encoding3d_displays.show_scalar_bars(display.SMProxy, view.SMProxy)   # (the GUI's Apply shows them)
        side_view(view)
        screenshot(view, "1_default_configuration")

        reader.Configuration = "distinct colour maps"         # the drop-down, Apply: drawn again
        simple.Render(view)
        check_drawn(display, distinct)
        encoding3d_displays.show_scalar_bars(display.SMProxy, view.SMProxy)
        colourings = views.block_displays(distinct, set(reader.CellData.keys()))["colourings"]
        firsts = {array: tuple(list(simple.GetColorTransferFunction(array).RGBPoints)[1:4]) for _, array in colourings}
        print("first colour of each layer's map", firsts)
        assert len(set(firsts.values())) == len(firsts), firsts
        screenshot(view, "2_distinct_colour_maps")

        reader.InvokeCommand("SaveViews")                     # saved unchanged: the same configuration
        saved = views.configuration(views.read_views(views_file), "distinct colour maps")[1]
        assert saved == [views.filled(layer) for layer in distinct], (saved, distinct)
        display.BlockOpacities = [views.block_selector(grids[0]), "0.15", views.block_selector(shoot), "0.6"]
        reader.SaveAs = "faded"                               # changed, saved as another configuration
        reader.InvokeCommand("SaveViews")
        faded = views.configuration(views.read_views(views_file), "faded")[1]
        assert [layer["opacity"] for layer in faded if layer["name"] in (shoot, grids[0])] == [0.6, 0.15], faded
        assert views.read_views(views_file)["active"] == "faded" and reader.Configuration == "faded"
        reader.SaveAs = ""
        simple.Render(view)
        screenshot(view, "3_faded_saved")

        reader.Configuration = name                           # back to the default
        simple.Render(view)
        check_drawn(display, layers)
        data = servermanager.Fetch(reader)
        tubes = data.GetBlock(block_names(reader).index(roots))
        axes = vtk_to_numpy(tubes.GetCellData().GetArray("Axis.id"))
        lateral = float(axes.max())                           # the last axis: a lateral root
        pick(reader, roots, "Axis.id", lateral)
        selection = encoding3dSelectatscale(Input=reader)  # noqa: F821   (the GUI's Filters > encoding3d, Apply)
        scales = scale_names(selection)
        print("scales", scales)
        assert scales[0] == "Plant" and "Axis" in scales and "Compartment" in scales, scales
        selection.Scale = "Axis"
        selection_display = simple.Show(selection, view)      # Apply shows it, drawn as the layers
        check_drawn(selection_display, layers, selection=True)
        selection.InvokeCommand("Isolate")
        assert not visible(reader, view) and visible(selection, view)
        screenshot(view, "4_isolate_axis")
        assert set(servermanager.Fetch(selection).GetBlock(block_names(selection).index(roots)).GetCellData()
                   .GetArray("Axis.id").GetRange()) == {lateral}
        axis_cells = cells(selection, roots)
        selection.Scale = "Plant"                             # the drop-down changed, Apply: re-grown
        simple.Render(view)
        assert cells(selection, roots) > axis_cells, (cells(selection, roots), axis_cells)
        screenshot(view, "5_isolate_scale_switched_to_plant")
        if reader.TimestepValues:                             # stepping in time: the same plant followed
            view.ViewTime = list(reader.TimestepValues)[0]
            simple.Render(view)
            screenshot(view, "6_isolate_plant_first_time_step")
            view.ViewTime = last
            simple.Render(view)
        selection.InvokeCommand("PutBack")
        assert visible(reader, view) and not visible(selection, view)
        simple.Delete(selection)                              # the selection dropped
        screenshot(view, "7_put_back")

        segment = float(vtk_to_numpy(tubes.GetCellData().GetArray("SubOrgan.id"))[np.flatnonzero(axes == lateral)[0]])
        pick(reader, roots, "SubOrgan.id", segment)
        selection = encoding3dSelectatscale(Input=reader, Scale="SubOrgan")  # noqa: F821
        simple.Show(selection, view)
        selection.InvokeCommand("Isolate")
        assert cells(selection, sections) > 0                 # the hidden layer's part: the segment's section
        assert views.block_selector(sections) in drawn(simple.GetDisplayProperties(selection, view))["BlockSelectors"]
        view.ResetCamera()
        screenshot(view, "8_isolate_segment_with_its_section")
        selection.InvokeCommand("PutBack")
        simple.Delete(selection)
        side_view(view)

        shoot_data = data.GetBlock(block_names(reader).index(shoot))
        plant = float(vtk_to_numpy(shoot_data.GetCellData().GetArray("Plant.id"))[0])
        pick(reader, shoot, "Plant.id", plant)
        plant_selection = encoding3dSelectatscale(Input=reader)  # noqa: F821   (Scale: Plant, the first)
        plant_selection.InvokeCommand("ShowInPanel")
        layout = simple.GetLayout(view)
        layout.SetSize(1600, 700)
        layout_screenshot(layout, "9_panel_plant")
        assert visible(reader, view)                          # the view untouched
        panel = [proxy for proxy in simple.GetViews() if proxy.SMProxy is not view.SMProxy][0]
        simple.SetActiveView(panel)                           # an axis of the plant, picked in the panel
        plant_axes = vtk_to_numpy(servermanager.Fetch(plant_selection).GetBlock(
            block_names(plant_selection).index(roots)).GetCellData().GetArray("Axis.id"))
        pick(plant_selection, roots, "Axis.id", float(plant_axes.max()))
        axis_selection = encoding3dSelectatscale(Input=plant_selection, Scale="Axis")  # noqa: F821
        simple.Show(axis_selection, panel)
        axis_selection.InvokeCommand("Isolate")               # in the active view: the panel
        assert not visible(plant_selection, panel) and visible(axis_selection, panel)
        layout_screenshot(layout, "10_panel_an_axis_of_the_plant")
        axis_selection.InvokeCommand("PutBack")               # back to the plant in the panel
        assert visible(plant_selection, panel)
        simple.Delete(axis_selection)
        plant_selection.InvokeCommand("PutBack")              # the panel closed
        assert len(simple.GetViews()) == 1, simple.GetViews()
        simple.Delete(plant_selection)
        simple.SetActiveView(view)
        view.ViewSize = [900, 700]
        screenshot(view, "11_panel_closed")

        reader.Configuration = "roots and sections"           # the drop-down
        simple.Render(view)
        check_drawn(display, roots_only)
        colours = simple.GetColorTransferFunction("SubOrgan.radius")
        points = list(colours.RGBPoints)
        assert colours.UseLogScale and abs(points[0] - 0.0002) < 1e-12 and abs(points[-4] - 0.002) < 1e-12, points
        side_view(view)
        screenshot(view, "12_configuration_roots_and_sections")
        reader.InvokeCommand("SaveViews")                     # its range and log scale read back
        saved = views.configuration(views.read_views(views_file), "roots and sections")[1]
        assert saved == [views.filled(layer) for layer in roots_only], (saved, roots_only)
    finally:
        shutil.move(views_file + ".before_check", views_file)
    print("encoding3d design check: done, look at the screenshots in", pictures)


def check_instances() -> None:
    """Instances in ParaView (specification §12): see this file's docstring."""
    import json
    import shutil
    import tempfile
    import numpy as np
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from openalea.encoding3d import evaluate, pack, read
    source = os.path.join(HERE, os.pardir, "conformance", "instances")
    folder = tempfile.mkdtemp(prefix="encoding3d_instances_")
    try:
        frames = os.path.join(folder, "frames")
        shutil.copytree(source, frames, ignore=shutil.ignore_patterns("expected", "*.json", "embedded.glb"))
        shutil.copy(os.path.join(source, "scene.fspm.json"), frames)
        layers = [{"name": "roots", "source": {"data_structure": "root_system", "kind": "segments",
                                               "entity_set": "SubOrgan"},
                   "color_by": {"entity_set": "SubOrgan", "variable": "water_potential"}, "opacity": 0.4,
                   "tube": {"radius": "radius", "scale": 1}},
                  {"name": "sections", "source": {"data_structure": "root_system", "kind": "instances",
                                                  "instance_set": "sections"},
                   "color_by": {"entity_set": "Cell", "variable": "area"}}]
        with open(os.path.join(frames, "views.json"), "w", encoding="utf-8") as file:
            json.dump({"encoding3d_views": 1, "configurations": {"default": {"layers": layers}}}, file)
        archive = pack(frames, os.path.join(folder, "run.fspm.zip"))
        view = simple.GetActiveViewOrCreate("RenderView")
        view.ViewSize = [900, 700]
        for name, path in (("folder", os.path.join(frames, "scene.fspm.json")), ("archive", archive)):
            reader = encoding3dreader(FileName=path)  # noqa: F821
            reader.UpdatePipeline()
            assert block_names(reader) == ["roots", "sections"], block_names(reader)
            assert list(reader.TimestepValues) == [0., 1.], list(reader.TimestepValues)
            data = servermanager.Fetch(reader)
            sections = data.GetBlock(1)
            found = {sections.GetCellData().GetArrayName(n) for n in range(sections.GetCellData().GetNumberOfArrays())}
            assert {"Cell.area", "sections.age", "SubOrgan.id", "Axis.id", "encoding3d_instance"} <= found, found
            assert "Cell.water_potential" not in found                # on demand
            display = simple.Show(reader, view)
            side_view(view)
            simple.Render(view)
            screenshot(view, f"instances_{name}_1_opened")
            pick(reader, "sections", "encoding3d_instance", 2.)
            selection = encoding3dSelectatscale(Input=reader, Scale="SubOrgan")  # noqa: F821
            selection.UpdatePipeline()
            grown = servermanager.Fetch(selection)
            block = grown.GetBlock(block_names(selection).index("sections"))
            assert set(vtk_to_numpy(block.GetCellData().GetArray("encoding3d_instance")).tolist()) == {2}
            frame_file = block.GetFieldData().GetAbstractArray("encoding3d_frame").GetValue(0)
            expected = evaluate(read(frame_file), "water_potential", instances=[2])[0]
            rebuilt = vtk_to_numpy(block.GetCellData().GetArray("Cell.water_potential"))
            np.testing.assert_allclose(rebuilt, expected, rtol=1e-12)
            print(name, "derived field rebuilt for the selected section:", rebuilt.tolist())
            assert grown.GetBlock(block_names(selection).index("roots")).GetNumberOfCells() == 1
            simple.Show(selection, view)
            selection.InvokeCommand("Isolate")
            assert not visible(reader, view) and visible(selection, view)
            selection_display = simple.GetDisplayProperties(selection, view)
            simple.ColorBy(selection_display, ("CELLS", "Cell.water_potential"))
            view.ResetCamera()
            screenshot(view, f"instances_{name}_2_isolated_section")
            selection.InvokeCommand("PutBack")
            assert visible(reader, view)
            selection.InvokeCommand("ShowInPanel")
            layout = simple.GetLayout(view)
            layout.SetSize(1600, 700)
            layout_screenshot(layout, f"instances_{name}_3_panel")
            selection.InvokeCommand("PutBack")
            assert len(simple.GetViews()) == 1, simple.GetViews()
            simple.SetActiveView(view)
            simple.Delete(selection)
            reader.EvaluateDerivedFields = 1                          # every instance's derived fields
            reader.UpdatePipeline()
            sections = servermanager.Fetch(reader).GetBlock(1)
            assert sections.GetCellData().GetArray("Cell.water_potential") is not None
            simple.Hide(reader, view)
            shown = simple.Show(reader, view)
            simple.ColorBy(shown, ("CELLS", "Cell.water_potential"))
            shown.RescaleTransferFunctionToDataRange(True)
            side_view(view)
            screenshot(view, f"instances_{name}_4_every_derived_field")
            simple.Delete(reader)
        print("encoding3d instances check: done" + (f", look at the screenshots in {pictures}" if pictures else ""))
    finally:
        shutil.rmtree(folder)


if DESIGN:
    check_design(sys.argv[2])
elif INSTANCES:
    check_instances()
else:
    check_conformance()
print("encoding3d reader: ok")
