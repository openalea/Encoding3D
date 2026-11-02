"""The ParaView reader's conversion (paraview/fspm_tf_reader.py), with VTK alone: meshes with every entity set's
variables as cell data, segments as lines, grids in VTK's cell order, sequences as time steps. Run inside ParaView
too when FSPM_TF_PVPYTHON gives a pvpython."""
import importlib.util
import os
import subprocess

import numpy as np
import pytest

import generate
from conftest import CONFORMANCE, ROOT

pytest.importorskip("vtkmodules")
from vtkmodules.util.numpy_support import vtk_to_numpy  # noqa: E402

PLUGIN = os.path.join(ROOT, "paraview", "fspm_tf_reader.py")
_specification = importlib.util.spec_from_file_location("fspm_tf_reader", PLUGIN)
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
    pvpython = os.environ.get("FSPM_TF_PVPYTHON")
    if not pvpython:
        pytest.skip("FSPM_TF_PVPYTHON (a pvpython) not given")
    script = os.path.join(ROOT, "paraview", "check_in_paraview.py")
    result = subprocess.run([pvpython, script, CONFORMANCE], capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fspm-TF reader: ok" in result.stdout


def test_missing_values_are_nan_and_code_minus_one():
    frame = generate.root_system()
    segments = frame.data_structures[0].entity_set("SubOrgan")
    count = segments.count
    segments.columns["tissue"] = np.array([None] + ["cortex"] * (count - 1), dtype=object)
    segments.columns["rank"] = np.ma.MaskedArray(np.arange(count, dtype=np.int32), mask=[True] + [False] * (count - 1))
    lines = blocks_of(frame)[("root_system", "SubOrgan segments")]
    assert np.isnan(cell_array(lines, "SubOrgan.rank")[0]) and cell_array(lines, "SubOrgan.rank")[1] == 1.
    assert cell_array(lines, "SubOrgan.tissue_code")[0] == -1 and cell_array(lines, "SubOrgan.tissue_code")[1] == 0
