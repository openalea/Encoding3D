"""The ParaView reader's conversion (paraview/encoding3d_reader.py), with VTK alone: meshes with every entity set's
variables as cell data, segments as lines, grids in VTK's cell order, sequences as time steps. Run inside ParaView
too when ENCODING3D_PVPYTHON gives a pvpython."""
import importlib.util
import os
import subprocess

import numpy as np
import pytest

import generate
from conftest import CONFORMANCE, ROOT

pytest.importorskip("vtkmodules")
from vtkmodules.util.numpy_support import vtk_to_numpy  # noqa: E402

PLUGIN = os.path.join(ROOT, "paraview", "encoding3d_reader.py")
_specification = importlib.util.spec_from_file_location("encoding3d_reader", PLUGIN)
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
    lines = blocks["roots"]
    kept = (segments.columns["label"] == "RootSegment") & (segments.columns["length"] > 0)
    assert lines.GetNumberOfCells() == kept.sum()
    np.testing.assert_array_equal(cell_array(lines, "SubOrgan.radius"), segments.columns["radius"][kept])
    radius = vtk_to_numpy(lines.GetPointData().GetArray("tube_radius"))
    np.testing.assert_array_equal(radius, np.concatenate([segments.columns["radius"][kept]] * 2) * 2)
    assert lines.GetCellData().GetScalars().GetName() == "SubOrgan.label_code"     # text: its codes
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
    assert axis_lines.GetPointData().GetArray("tube_radius") is not None                 # a Tube can follow
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
