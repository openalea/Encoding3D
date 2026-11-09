"""The ParaView reader's conversion (paraview/plugin_encoding3d.py), with VTK alone: meshes with every entity set's
variables as cell data, segments as lines (a views layer's as tubes), grids in VTK's cell order, sequences as time
steps. Run inside ParaView too when ENCODING3D_PVPYTHON gives a pvpython."""
import importlib.util
import os
import subprocess

import numpy as np
import pytest

import generate
from conftest import CONFORMANCE, ROOT

pytest.importorskip("vtkmodules")
from vtkmodules.util.numpy_support import vtk_to_numpy  # noqa: E402

PLUGIN = os.path.join(ROOT, "paraview", "plugin_encoding3d.py")
_specification = importlib.util.spec_from_file_location("plugin_encoding3d", PLUGIN)
reader = importlib.util.module_from_spec(_specification)
_specification.loader.exec_module(reader)


def blocks_of(frame) -> dict:
    output = reader.frame_to_vtk(frame)
    found = {}
    for number in range(output.GetNumberOfBlocks()):
        inner = output.GetBlock(number)
        for position in range(inner.GetNumberOfBlocks()):
            name = (output.GetMetaData(number).Get(output.NAME()), inner.GetMetaData(position).Get(inner.NAME()))
            found[name] = inner.GetBlock(position)
    return found


def cell_array(data_set, name):
    return vtk_to_numpy(data_set.GetCellData().GetArray(name))


def test_a_mesh_carries_every_scale():
    frame = generate.root_system()
    mesh = blocks_of(frame)[("root_system", "mesh roots")]
    source = frame.data_structures[0]
    rows = source.meshes[0].feature_rows
    assert mesh.GetNumberOfCells() == len(source.meshes[0].positions) // 3
    segments = source.entity_set("SubOrgan")
    np.testing.assert_array_equal(cell_array(mesh, "SubOrgan.water_potential"),
                                  segments.columns["water_potential"][rows["SubOrgan"][::3]])
    np.testing.assert_array_equal(cell_array(mesh, "Axis.branching_order"),
                                  source.entity_set("Axis").columns["branching_order"][rows["Axis"][::3]])
    assert set(cell_array(mesh, "Plant.id")) == {1000.}
    assert mesh.GetCellData().GetArray("SubOrgan.parent") is None            # the links: with settings only
    with_settings = reader.frame_to_vtk(frame, settings=True).GetBlock(0).GetBlock(0)
    assert with_settings.GetCellData().GetArray("SubOrgan.parent") is not None
    codes = cell_array(mesh, "SubOrgan.label_code")
    names = mesh.GetFieldData().GetAbstractArray("SubOrgan.label_names")
    assert {names.GetValue(int(code)) for code in codes} == {"RootSegment"}     # apices have no triangles


def test_segments_are_lines():
    frame = generate.root_system()
    lines = blocks_of(frame)[("root_system", "SubOrgan segments")]
    segments = frame.data_structures[0].entity_set("SubOrgan")
    assert lines.GetNumberOfCells() == segments.count
    points = vtk_to_numpy(lines.GetPoints().GetData())
    np.testing.assert_array_equal(points[:segments.count, 2], segments.columns["z1"])
    np.testing.assert_array_equal(points[segments.count:, 2], segments.columns["z2"])
    np.testing.assert_array_equal(cell_array(lines, "SubOrgan.radius"), segments.columns["radius"])


def test_origins_place_the_data_structures():
    frame = generate.wheat_shoot()
    mesh = blocks_of(frame)[("shoot", "mesh leaves")]
    points = vtk_to_numpy(mesh.GetPoints().GetData())
    source = frame.data_structures[0].meshes[0].positions
    np.testing.assert_allclose(points, source + [0.5, 0.25, 0.], rtol=0, atol=1e-12)
    absorbed = cell_array(mesh, "SubOrgan.PARa")
    assert np.isfinite(absorbed).all()                    # the leaf elements drawn all have a value


def test_a_regular_grid_in_vtk_cell_order():
    frame = generate.soil_and_roots()
    image = blocks_of(frame)[("soil", "grid")]
    assert image.GetDimensions() == (3, 3, 4)
    values = cell_array(image, "Voxel.soil_water_potential")
    expected = frame.data_structures[1].entity_set("Voxel").columns["soil_water_potential"]
    for i in range(2):
        for j in range(2):
            for k in range(3):
                assert values[i + 2 * (j + 2 * k)] == expected[np.ravel_multi_index((i, j, k), (2, 2, 3))]
    direction = image.GetDirectionMatrix()
    assert direction.GetElement(2, 2) == -1.                 # z pointing down


def test_an_adaptive_grid_as_hexahedra():
    frame = generate.adaptive_soil()
    cells = blocks_of(frame)[("soil", "grid")]
    assert cells.GetNumberOfCells() == 9
    bounds = cells.GetCell(8).GetBounds()                     # the unrefined base cell (1, 0, 0)
    np.testing.assert_allclose(bounds, (0.1, 0.2, 0., 0.1, -0.1, 0.), atol=1e-12)
    bounds = cells.GetCell(0).GetBounds()                     # a level-1 cell (0, 0, 0)
    np.testing.assert_allclose(bounds, (0., 0.05, 0., 0.05, -0.05, 0.), atol=1e-12)


def test_a_sequence_is_time_steps():
    source = reader.Source(os.path.join(CONFORMANCE, "growing_sequence", "scene.fspm.json"))
    assert source.times == [0., 1., 2.]
    assert source.frame_at(1.5).time == 1. and source.frame_at(None).time == 0. and source.frame_at(9.).time == 2.
    # the reader's Time Unit: the times ParaView shows, converted from the files' (days here), the files unchanged
    assert source.time_unit == "d"
    assert source.factor("d") == 1. and source.factor("h") == 24. and source.factor("s") == 86400.
    assert source.factor("") == 1. and source.factor("week") == 1.        # empty or unknown: the files' times


def test_inside_paraview():
    pvpython = os.environ.get("ENCODING3D_PVPYTHON")
    if not pvpython:
        pytest.skip("ENCODING3D_PVPYTHON (a pvpython) not given")
    script = os.path.join(ROOT, "paraview", "check_in_paraview.py")
    result = subprocess.run([pvpython, script, CONFORMANCE], capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "encoding3d reader: ok" in result.stdout


def test_missing_values_are_nan_and_code_minus_one():
    frame = generate.root_system()
    segments = frame.data_structures[0].entity_set("SubOrgan")
    count = segments.count
    segments.columns["tissue"] = np.array([None] + ["cortex"] * (count - 1), dtype=object)
    segments.columns["rank"] = np.ma.MaskedArray(np.arange(count, dtype=np.int32), mask=[True] + [False] * (count - 1))
    lines = blocks_of(frame)[("root_system", "SubOrgan segments")]
    assert np.isnan(cell_array(lines, "SubOrgan.rank")[0]) and cell_array(lines, "SubOrgan.rank")[1] == 1.
    assert cell_array(lines, "SubOrgan.tissue_code")[0] == -1 and cell_array(lines, "SubOrgan.tissue_code")[1] == 0


# ── Views: one block per layer ───────────────────────────────────────────

def layers_of(frame, views, configuration=None) -> dict:
    output = reader.frame_to_vtk(frame, views=views, configuration=configuration)
    return {output.GetMetaData(number).Get(output.NAME()): output.GetBlock(number)
            for number in range(output.GetNumberOfBlocks())}


def views_module():
    from openalea.encoding3d import views
    return views


def test_views_give_a_block_per_layer_with_its_entities_only():
    from test_views import roots_views
    frame = generate.root_system()
    source = frame.data_structures[0]
    blocks = layers_of(frame, roots_views())
    assert list(blocks) == ["first order", "roots"]                       # the hidden layer too
    mesh = blocks["first order"]
    triangles = source.meshes[0].feature_rows["Axis"][::3]
    first_order = source.entity_set("Axis").columns["branching_order"][triangles] == 1
    assert 0 < mesh.GetNumberOfCells() == first_order.sum() < len(triangles)
    assert set(cell_array(mesh, "Axis.branching_order")) == {1.}
    assert mesh.GetCellData().GetScalars().GetName() == "SubOrgan.water_potential"
    segments = source.entity_set("SubOrgan")
    tubes = blocks["roots"]                                                # a "tube": drawn as tubes
    kept = (segments.columns["label"] == "RootSegment") & (segments.columns["length"] > 0)
    assert tubes.GetNumberOfCells() == tubes.GetNumberOfStrips() == kept.sum()     # a strip per segment
    assert tubes.GetNumberOfPoints() == 2 * reader.TUBE_SIDES * kept.sum()
    ring = vtk_to_numpy(tubes.GetPoints().GetData())[:2 * reader.TUBE_SIDES:2]   # the first tube's first end
    start = np.array([segments.columns[name][kept][0] for name in ("x1", "y1", "z1")])
    np.testing.assert_allclose(np.linalg.norm(ring - start, axis=1), 2 * segments.columns["radius"][kept][0])
    np.testing.assert_array_equal(cell_array(tubes, "SubOrgan.radius"), segments.columns["radius"][kept])
    radius = vtk_to_numpy(tubes.GetPointData().GetArray("tube_radius"))
    np.testing.assert_allclose(np.unique(radius), np.unique(segments.columns["radius"][kept] * 2))   # its scale
    bounds = np.array(tubes.GetBounds()).reshape(3, 2)
    ends = np.stack([segments.columns[name][kept] for name in ("x1", "y1", "z1")], axis=1)
    assert (bounds[:, 0] <= ends.min(axis=0)).all() and (bounds[:, 1] >= ends.max(axis=0)).all()
    assert tubes.GetCellData().GetScalars().GetName() == "SubOrgan.label_code"     # text: its codes
    assert tubes.GetFieldData().GetAbstractArray(views_module().DATA_STRUCTURE_FIELD) is not None
    plain = layers_of(frame, roots_views(), "plain")["all"]
    assert plain.GetNumberOfCells() == len(triangles) and plain.GetCellData().GetScalars() is None


def test_grid_layers_hide_the_cells_not_selected():
    frame = generate.soil_and_roots()
    layer = {"name": "wet", "source": {"data_structure": "soil", "kind": "grid"},
             "select": {"entity_set": "Voxel", "where": {"soil_water_potential": ">=-15000"}},
             "color_by": {"entity_set": "Voxel", "variable": "soil_water_potential"}, "opacity": 0.3}
    image = layers_of(frame, {"encoding3d_views": 1, "configurations": {"soil": {"layers": [layer]}}})["wet"]
    ghosts = vtk_to_numpy(image.GetCellData().GetArray("vtkGhostType"))
    voxels = frame.data_structures[1].entity_set("Voxel")
    order = np.arange(12).reshape((2, 2, 3)).ravel(order="F")
    np.testing.assert_array_equal(ghosts == 0, voxels.columns["soil_water_potential"][order] >= -15000)
    assert 0 < (ghosts == 0).sum() < 12
    assert image.GetCellData().GetScalars().GetName() == "Voxel.soil_water_potential"
    adaptive = generate.adaptive_soil()
    layer = {"name": "fine", "source": {"data_structure": "soil", "kind": "grid"},
             "select": {"entity_set": "Cell", "where": {"level": ">0"}}}
    cells = layers_of(adaptive, {"encoding3d_views": 1, "configurations": {"soil": {"layers": [layer]}}})["fine"]
    assert cells.GetNumberOfCells() == (adaptive.data_structures[0].entity_set("Cell").columns["level"] > 0).sum()


def test_views_from_a_file_and_wrong_names(tmp_path):
    from openalea.encoding3d import views
    from test_views import roots_views
    path = str(tmp_path / "views.json")
    views.write_views(path, roots_views())
    assert list(layers_of(generate.root_system(), path)) == ["first order", "roots"]
    empty = layers_of(generate.wheat_shoot(), path)                       # names the frame lacks: empty blocks
    assert list(empty) == ["first order", "roots"] and all(block.GetNumberOfCells() == 0 for block in empty.values())
    with pytest.raises(ValueError, match="encoding3d_views"):
        reader.frame_to_vtk(generate.root_system(), views={"encoding3d_views": 2, "configurations": {}})
    assert reader.frame_to_vtk(generate.root_system()).GetNumberOfBlocks() == 1          # no views: as before


def test_cells_carry_the_ids_of_the_entities_containing_theirs():
    """What selection by scale reads: each cell the ids of its entity's containing ones, each block its data
    structure and scales."""
    from openalea.encoding3d import views
    frame = generate.root_system()
    blocks = blocks_of(frame)
    lines = blocks[("root_system", "SubOrgan segments")]
    segments = frame.data_structures[0].entity_set("SubOrgan")
    np.testing.assert_array_equal(cell_array(lines, "Axis.id"), segments.columns["complex"])
    assert set(cell_array(lines, "Plant.id")) == {1000.}
    fields = lines.GetFieldData()
    assert fields.GetAbstractArray(views.DATA_STRUCTURE_FIELD).GetValue(0) == "root_system"
    scales = fields.GetAbstractArray(views.SCALES_FIELD)
    assert [scales.GetValue(number) for number in range(scales.GetNumberOfValues())] == ["Plant", "Axis", "SubOrgan"]
    mesh = blocks[("root_system", "mesh roots")]
    arrays = {name: cell_array(mesh, name) for name in ("Plant.id", "Axis.id", "SubOrgan.id")}
    chosen = views.picked_entities([("root_system", {"Axis.id": np.array([101.])})], "Axis")
    lateral = views.selection_mask("root_system", arrays, chosen, "Axis")
    assert 0 < lateral.sum() < mesh.GetNumberOfCells()
    assert set(arrays["SubOrgan.id"][lateral]) == {60., 61.}                 # the lateral's segments, not its apex
    soil = blocks_of(generate.soil_and_roots())[("soil", "grid")]
    assert soil.GetFieldData().GetAbstractArray(views.DATA_STRUCTURE_FIELD).GetValue(0) == "soil"


def test_select_at_scale_grows_picked_cells_in_every_layer():
    """The "Select at scale" filter's work: the cells picked on a layer (a vtkSelection, as ParaView's) grown to their
    axis or plant in every layer, the hidden one too, the same blocks, polygonal data kept polygonal; the frame found
    upstream of items drawn from the reader."""
    from vtkmodules.vtkCommonCore import vtkIdTypeArray
    from vtkmodules.vtkCommonDataModel import vtkPolyData, vtkSelection, vtkSelectionNode
    from vtkmodules.vtkCommonExecutionModel import vtkTrivialProducer
    from vtkmodules.vtkFiltersCore import vtkPassThrough
    from test_views import roots_views
    frame = generate.root_system()
    data = reader.frame_to_vtk(frame, views=roots_views())                # layers "first order", "roots" (hidden)
    lines = data.GetBlock(1)
    cell = int(np.flatnonzero(cell_array(lines, "Axis.id") == 101.)[0])
    node = vtkSelectionNode()
    node.SetFieldType(vtkSelectionNode.CELL)
    node.SetContentType(vtkSelectionNode.INDICES)
    ids = vtkIdTypeArray()
    ids.InsertNextValue(cell)
    node.SetSelectionList(ids)
    node.GetProperties().Set(vtkSelectionNode.COMPOSITE_INDEX(), 2)    # the roots block (flat index 2)
    selection = vtkSelection()
    selection.AddNode(node)
    picked = reader.picked_cells(data, selection)
    assert [data_structure for data_structure, _ in picked] == ["root_system"]
    assert set(picked[0][1]["Axis.id"]) == {101.}
    assert reader.scales_of(data) == ["Plant", "Axis", "SubOrgan"]
    grown = reader.grow_selection(data, picked, "Axis")
    assert [grown.GetMetaData(number).Get(grown.NAME()) for number in range(2)] == ["first order", "roots"]
    axis_lines = grown.GetBlock(1)
    assert isinstance(axis_lines, vtkPolyData) and set(cell_array(axis_lines, "Axis.id")) == {101.}
    assert axis_lines.GetNumberOfCells() == (cell_array(lines, "Axis.id") == 101.).sum()
    assert axis_lines.GetCellData().GetScalars().GetName() == "SubOrgan.label_code"     # the layer's colouring
    assert axis_lines.GetNumberOfStrips() == axis_lines.GetNumberOfCells()              # tubes still
    first_order = grown.GetBlock(0)
    assert first_order.GetNumberOfCells() == 0                    # the lateral is not of the first order
    plant = reader.grow_selection(data, picked, "Plant")
    assert plant.GetBlock(0).GetNumberOfCells() == data.GetBlock(0).GetNumberOfCells()
    assert plant.GetBlock(1).GetNumberOfCells() == lines.GetNumberOfCells()
    with pytest.raises(ValueError, match="Compartment"):
        reader.grow_selection(data, picked, "Compartment")
    assert reader.picked_cells(data, vtkSelection()) == []
    producer = vtkTrivialProducer()                                 # the reader, an item drawn from it, the filter
    producer.SetOutput(data)
    item, filter_algorithm = vtkPassThrough(), vtkPassThrough()
    item.SetInputConnection(producer.GetOutputPort())
    filter_algorithm.SetInputConnection(item.GetOutputPort())
    filter_algorithm.Update()
    assert reader.frame_upstream(filter_algorithm) is data
    assert reader.frame_upstream(producer) is None


# ── Instances (specification §12) ────────────────────────────────────────

INSTANCES = os.path.join(CONFORMANCE, "instances")


def instance_block(output, name="instances sections"):
    inner = output.GetBlock(0)
    names = [inner.GetMetaData(number).Get(inner.NAME()) for number in range(inner.GetNumberOfBlocks())]
    return inner.GetBlock(names.index(name))


def test_instances_are_placed_templates_with_their_own_fields():
    from openalea.encoding3d import evaluate, read
    frame = read(os.path.join(INSTANCES, "frame_000001.glb"))
    slim = instance_block(reader.frame_to_vtk(frame))             # by default the ids and rows selection needs
    assert arrays_of(slim) == {reader.INSTANCE_ROW, reader.TEMPLATE_ROW + "Cell", "SubOrgan.id", "Axis.id",
                               "Plant.id"}, arrays_of(slim)
    block = instance_block(reader.frame_to_vtk(frame, all_arrays=True))      # with every variable
    assert block.GetNumberOfCells() == slim.GetNumberOfCells() == 4 + 4 + 6 + 6
    instance = cell_array(block, reader.INSTANCE_ROW)
    np.testing.assert_array_equal(instance, np.repeat([0, 1, 2, 3], [4, 4, 6, 6]))
    np.testing.assert_array_equal(cell_array(block, "sections.age"), [1., 1., 1., 1., .5, .5, .5, .5] + [0.] * 6
                                  + [-.5] * 6)
    owners = frame.data_structures[0].instance_set("sections").columns["owner"]
    np.testing.assert_array_equal(cell_array(block, "SubOrgan.id"), owners[instance])
    assert set(cell_array(block, "Axis.id")) == {100.} and set(cell_array(block, "Plant.id")) == {1000.}
    np.testing.assert_array_equal(cell_array(block, "Cell.area")[:4], np.full(4, 0.5))
    assert "Cell.water_potential" not in arrays_of(block)              # derived fields: on demand
    evaluated = instance_block(reader.frame_to_vtk(frame, derived=True))
    expected = np.concatenate(evaluate(frame, "water_potential"))
    np.testing.assert_allclose(cell_array(evaluated, "Cell.water_potential"), expected, rtol=1e-12)
    assert vtk_to_numpy(block.GetPoints().GetData()).shape == (3 * 20, 3)


def arrays_of(data_set) -> set:
    cell_data = data_set.GetCellData()
    return {cell_data.GetArrayName(number) for number in range(cell_data.GetNumberOfArrays())}


def test_select_at_scale_rebuilds_the_selected_instances_derived_fields():
    from openalea.encoding3d import evaluate, read
    path = os.path.join(INSTANCES, "frame_000001.glb")
    frame = read(path)
    data = reader.frame_to_vtk(frame)
    owners = frame.data_structures[0].instance_set("sections").columns["owner"]
    picked = [("root_system", {"SubOrgan.id": np.array([float(owners[2])]), "Axis.id": np.array([100.]),
                               "Plant.id": np.array([1000.])})]
    grown = reader.grow_selection(data, picked, "SubOrgan")
    block = instance_block(grown)
    assert set(cell_array(block, reader.INSTANCE_ROW)) == {2}
    reader.rebuild_derived(grown)
    np.testing.assert_allclose(cell_array(block, "Cell.water_potential"), evaluate(frame, "water_potential",
                                                                                   instances=[2])[0], rtol=1e-12)


def test_an_archive_opens_as_its_folder(tmp_path):
    from openalea.encoding3d import pack
    archive = pack(INSTANCES, str(tmp_path / "run.fspm.zip"), keep_folder=True)
    source = reader.Source(archive)
    assert source.times == [0., 1.]
    block = instance_block(reader.frame_to_vtk(source.frame_at(1.), derived=True))
    assert block.GetNumberOfCells() == 20 and "Cell.water_potential" in arrays_of(block)


def test_an_instances_layer():
    from openalea.encoding3d import read
    frame = read(os.path.join(INSTANCES, "frame_000001.glb"))
    views = {"encoding3d_views": 1, "configurations": {"default": {"layers": [
        {"name": "sections", "source": {"data_structure": "root_system", "kind": "instances", "instance_set": "sections"},
         "select": {"entity_set": "sections", "where": {"age": ">0"}},
         "color_by": {"entity_set": "Cell", "variable": "water_potential"}},
        {"name": "old", "source": {"data_structure": "root_system", "kind": "instances", "instance_set": "sections"},
         "select": {"entity_set": "SubOrgan", "where": {"water_potential": ">-0.105"}},
         "color_by": {"entity_set": "sections", "variable": "age"}}]}}}
    from openalea.encoding3d.views import check_views
    assert check_views(views, frame).ok, str(check_views(views, frame))
    output = reader.frame_to_vtk(frame, views=views, derived=True)
    sections, old = output.GetBlock(0), output.GetBlock(1)
    assert set(cell_array(sections, reader.INSTANCE_ROW)) == {0, 1}
    assert sections.GetCellData().GetScalars().GetName() == "Cell.water_potential"
    assert set(cell_array(old, reader.INSTANCE_ROW)) == {0}
    wrong = {"encoding3d_views": 1, "configurations": {"default": {"layers": [
        {"name": "x", "source": {"data_structure": "root_system", "kind": "instances", "instance_set": "sections"},
         "color_by": {"entity_set": "Cell", "variable": "nothing"}}]}}}
    assert not check_views(wrong, frame).ok


HIDDEN_SECTIONS = {"encoding3d_views": 1, "configurations": {"default": {"layers": [
    {"name": "roots", "source": {"data_structure": "root_system", "kind": "segments", "entity_set": "SubOrgan"},
     "color_by": {"entity_set": "SubOrgan", "variable": "water_potential"}},
    {"name": "sections", "source": {"data_structure": "root_system", "kind": "instances", "instance_set": "sections"},
     "color_by": {"entity_set": "Cell", "variable": "water_potential"}, "visible": False}]}}}


def test_a_hidden_instances_layer_is_built_by_the_selection_alone(monkeypatch):
    """A hidden instances layer of a frame read from a file is an empty block (its instances not placed); Select at
    scale builds the placed templates of the instances it selects only, from the frame the reader opened (one read
    for both), and their derived fields are evaluated once per open frame; Expand Hidden Instances draws them all."""
    from openalea.encoding3d import evaluate, instances
    path = os.path.join(INSTANCES, "frame_000001.glb")
    frame = reader.open_frame(path)
    assert reader.Source(os.path.join(INSTANCES, "scene.fspm.json")).frame_at(1.) is reader.open_frame(path) is frame
    data = reader.frame_to_vtk(frame, views=HIDDEN_SECTIONS)
    sections = data.GetBlock(1)
    assert sections.GetNumberOfCells() == 0 and sections.GetFieldData().GetAbstractArray(reader.UNEXPANDED_FIELD)
    owners = frame.data_structures[0].instance_set("sections").columns["owner"]
    picked = [("root_system", {"SubOrgan.id": np.array([float(owners[2])]), "Axis.id": np.array([100.]),
                               "Plant.id": np.array([1000.])})]
    assert reader.instance_rows_at(frame.data_structures[0], frame.data_structures[0].instance_set("sections"),
                                   [100], "Axis").tolist() == [0, 1, 2, 3]
    calls = []
    reader._DERIVED.clear()                                         # (an earlier test's rebuild of this frame)
    evaluated = instances.evaluate
    monkeypatch.setattr(instances, "evaluate", lambda *arguments, **options: calls.append(options["instances"])
                        or evaluated(*arguments, **options))
    for _ in range(2):                                              # the second time from the open frame's cache
        grown = reader.grow_selection(data, picked, "SubOrgan")
        block = grown.GetBlock(1)
        assert set(cell_array(block, reader.INSTANCE_ROW)) == {2} and block.GetNumberOfCells() == 6
        assert block.GetFieldData().GetAbstractArray(reader.FRAME_FIELD).GetValue(0) == path
        reader.rebuild_derived(grown)
        np.testing.assert_allclose(cell_array(block, "Cell.water_potential"),
                                   evaluated(frame, "water_potential", instances=[2])[0], rtol=1e-12)
        assert block.GetCellData().GetScalars().GetName() == "Cell.water_potential"
    assert [rows.tolist() for rows in calls] == [[2]]
    axis = reader.grow_selection(data, picked, "Axis")
    assert set(cell_array(axis.GetBlock(1), reader.INSTANCE_ROW)) == {0, 1, 2, 3}
    reader.rebuild_derived(axis)
    assert [rows.tolist() for rows in calls] == [[2], [0, 1, 3]]
    np.testing.assert_allclose(cell_array(axis.GetBlock(1), "Cell.water_potential"),
                               np.concatenate(evaluate(frame, "water_potential")), rtol=1e-12)
    expanded = reader.frame_to_vtk(frame, views=HIDDEN_SECTIONS, expand_hidden=True)
    assert expanded.GetBlock(1).GetNumberOfCells() == 20


def test_a_selection_without_instances_says_which_plants_have_some():
    path = os.path.join(INSTANCES, "frame_000001.glb")
    frame = reader.open_frame(path)
    data = reader.frame_to_vtk(frame, views=HIDDEN_SECTIONS)
    lateral = [("root_system", {"SubOrgan.id": np.array([60.]), "Axis.id": np.array([101.]),
                                "Plant.id": np.array([1000.])})]
    chosen = reader._views().picked_entities(lateral, "Axis")
    grown = reader.grow_entities(data, chosen, "Axis")
    assert grown.GetBlock(0).GetNumberOfCells() == 3 and grown.GetBlock(1).GetNumberOfCells() == 0
    messages = reader.missing_instances(data, grown, chosen, "Axis")
    assert messages == ["no 'sections' instance drawn for the selected Axis [101] at t = 1 d: the frame's 4 "
                        "instances are owned by Plant [1000]"], messages
    whole = reader.grow_entities(data, reader._views().picked_entities(lateral, "Plant"), "Plant")
    assert reader.missing_instances(data, whole, {"root_system": [1000]}, "Plant") == []
    absent = {"encoding3d_views": 1, "configurations": {"default": {"layers": [          # a frame without them
        {"name": "other", "source": {"data_structure": "root_system", "kind": "instances", "instance_set": "other"}}]}}}
    without = reader.frame_to_vtk(frame, views=absent)
    assert without.GetBlock(0).GetNumberOfCells() == 0
    grown = reader.grow_entities(without, {"root_system": [1000]}, "Plant")
    assert reader.missing_instances(without, grown, {"root_system": [1000]}, "Plant") == [
        "no 'other' instance drawn for the selected Plant [1000] at t = 1 d: the frame holds none"]


def test_instance_arrays_made_for_vtk_are_held_by_it():
    """The instances block's arrays are handed to VTK without a copy: they outlive the numpy arrays' names."""
    import gc
    from openalea.encoding3d import read
    frame = read(os.path.join(INSTANCES, "frame_000001.glb"))
    block = instance_block(reader.frame_to_vtk(frame, derived=True))
    gc.collect()
    np.testing.assert_array_equal(cell_array(block, reader.INSTANCE_ROW), np.repeat([0, 1, 2, 3], [4, 4, 6, 6]))
    assert np.isfinite(cell_array(block, "Cell.water_potential")).all()
    assert vtk_to_numpy(block.GetPoints().GetData()).shape == (60, 3)
