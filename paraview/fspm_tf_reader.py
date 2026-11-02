"""
fspm-TF reader for ParaView: opens a frame (.glb) or a sequence (scene.fspm.json, its frames as time steps), with
every variable of every scale as data arrays.

    ParaView ≥ 5.10: Tools > Manage Plugins > Load New..., choose this file (tick "Auto Load" to keep it); then
    File > Open a .glb or a scene.fspm.json and pick "fspm-TF reader".

The reader needs openalea.fspm_tf: found in ParaView's Python when installed there, else in the bindings/python/src
folder of the fspm-TF clone holding this file (nothing to install: the codec needs numpy only, which ParaView ships).

What it shows, one block per data structure:

    mesh <name>     its triangles; cell data: for each entity set the mesh represents (by feature IDs), the entity's
                    id and every numeric variable of it, named "<entity set>.<variable>" (NaN where a triangle has no
                    entity at that scale); point data: the display copies
    <entity set>    for an entity set with segment ends (the standard names proximal_end_x ... distal_end_z, or
      segments      columns x1 ... z2), one line per entity with its variables as cell data (a Tube filter on
                    "radius" draws roots)
    grid            a regular grid as image data (z pointing down when the grid says so), an adaptive grid as
                    hexahedra, the cells' variables as cell data

Labels and other text columns become integer codes ("<entity set>.label_code", the names in the block's field data).
The graph's links (complex, parent, edge_type) and the columns of role "setting" (a platform's own bookkeeping, e.g.
metafspm's MPG links) are left out unless "Show Settings" is ticked.
Data structures are placed by their origin.

frame_to_vtk(frame) builds the output without ParaView (VTK only), e.g. for scripts and tests.
"""
import os
import sys

import numpy as np
from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
from vtkmodules.vtkCommonCore import vtkPoints, vtkStringArray
from vtkmodules.vtkCommonDataModel import (VTK_HEXAHEDRON, vtkCellArray, vtkImageData, vtkMultiBlockDataSet,
                                           vtkPolyData, vtkUnstructuredGrid)
from vtkmodules.vtkCommonExecutionModel import vtkStreamingDemandDrivenPipeline


def _fspm_tf():
    try:
        from openalea import fspm_tf
    except ImportError:
        source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bindings", "python", "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        from openalea import fspm_tf
    return fspm_tf


SEGMENT_ENDS = (("proximal_end_x", "x1"), ("proximal_end_y", "y1"), ("proximal_end_z", "z1"),
                ("distal_end_x", "x2"), ("distal_end_y", "y2"), ("distal_end_z", "z2"))


# ── Frames to VTK data sets ──────────────────────────────────────────────────

def _array(name: str, values: np.ndarray):
    values = np.ascontiguousarray(values)
    array = numpy_to_vtk(values, deep=True)
    array.SetName(name)
    return array


def _numeric(column: np.ndarray) -> bool:
    return column.dtype != object and column.dtype.kind in "fiub"


def _codes(column: np.ndarray) -> tuple:
    """Each text value's code among the column's sorted values; a missing value (None): -1."""
    names = sorted({value for value in column.tolist() if value is not None})
    code_of = {name: code for code, name in enumerate(names)}
    return np.array([code_of.get(value, -1) for value in column.tolist()], dtype=np.int64), names


LINKS = ("complex", "parent", "edge_type")


def _shown(entity_set, name: str, settings: bool) -> bool:
    """Whether column *name* is shown: the variables, the id and the label; the graph's links and the columns of role
    "setting" (a platform's own bookkeeping) only with *settings*."""
    if settings:
        return True
    declared = entity_set.variables.get(name)
    return name not in LINKS and (declared is None or declared.role != "setting")


def _add_columns(data, entity_set, rows: np.ndarray, field_data, settings: bool = False) -> None:
    """Cell data of *entity_set*'s columns, one value per cell from *rows* (-1: no entity, NaN)."""
    valid = rows >= 0
    taken = np.where(valid, rows, 0)
    for name, column in entity_set.columns.items():
        if not _shown(entity_set, name, settings):
            continue
        label = f"{entity_set.name}.{name}"
        if column.dtype == object:
            if name not in ("label", "relation") and len(set(column.tolist())) > 64:
                continue                                    # free text: not a colouring
            codes, names = _codes(column)
            values = np.where(valid, codes[taken], -1)
            data.AddArray(_array(f"{label}_code", values))
            listed = vtkStringArray()
            listed.SetName(f"{label}_names")
            for item in names:
                listed.InsertNextValue(str(item))
            field_data.AddArray(listed)
            continue
        if not _numeric(column):
            continue
        values = column[taken].astype(np.float64)                       # float64: NaN where no entity
        if np.ma.isMaskedArray(values):
            values = values.filled(np.nan)                              # and where a value is missing
        values = np.where(valid.reshape((-1,) + (1,) * (values.ndim - 1)), values, np.nan)
        data.AddArray(_array(label, values))


def _transform(points: np.ndarray, origin: np.ndarray) -> np.ndarray:
    if np.array_equal(origin, np.eye(4)):
        return points
    return points @ origin[:3, :3].T + origin[:3, 3]


def _mesh(mesh, data_structure, settings: bool = False):
    polydata = vtkPolyData()
    points = vtkPoints()
    points.SetData(numpy_to_vtk(np.ascontiguousarray(_transform(mesh.positions, data_structure.origin)), deep=True))
    polydata.SetPoints(points)
    corners = mesh.indices if mesh.indices is not None else np.arange(len(mesh.positions))
    triangles = corners.reshape(-1, 3)
    offsets = np.arange(0, 3 * len(triangles) + 1, 3, dtype=np.int64)
    cells = vtkCellArray()
    cells.SetData(numpy_to_vtkIdTypeArray(offsets, deep=True),
                  numpy_to_vtkIdTypeArray(np.ascontiguousarray(triangles.reshape(-1), dtype=np.int64), deep=True))
    polydata.SetPolys(cells)
    for set_name, rows in mesh.feature_rows.items():
        _add_columns(polydata.GetCellData(), data_structure.entity_set(set_name), rows[triangles[:, 0]],
                     polydata.GetFieldData(), settings)
    for name, values in mesh.display.items():
        polydata.GetPointData().AddArray(_array(f"display.{name}", np.asarray(values, dtype=np.float32)))
    return polydata


def _segment_columns(entity_set) -> list:
    by_standard = {variable.standard_name: name for name, variable in entity_set.variables.items()
                   if variable.standard_name}
    found = []
    for standard, plain in SEGMENT_ENDS:
        name = by_standard.get(standard, plain)
        if name not in entity_set.columns or not _numeric(entity_set.columns[name]):
            return []
        found.append(name)
    return found


def _segments(entity_set, columns: list, data_structure, settings: bool = False):
    ends = np.stack([entity_set.columns[name].astype(np.float64) for name in columns], axis=1)
    count = entity_set.count
    points_array = _transform(np.concatenate([ends[:, :3], ends[:, 3:]]), data_structure.origin)
    polydata = vtkPolyData()
    points = vtkPoints()
    points.SetData(numpy_to_vtk(np.ascontiguousarray(points_array), deep=True))
    polydata.SetPoints(points)
    connectivity = np.stack([np.arange(count), np.arange(count) + count], axis=1).reshape(-1).astype(np.int64)
    cells = vtkCellArray()
    cells.SetData(numpy_to_vtkIdTypeArray(np.arange(0, 2 * count + 1, 2, dtype=np.int64), deep=True),
                  numpy_to_vtkIdTypeArray(connectivity, deep=True))
    polydata.SetLines(cells)
    _add_columns(polydata.GetCellData(), entity_set, np.arange(count), polydata.GetFieldData(), settings)
    return polydata


def _regular_grid(data_structure, settings: bool = False):
    grid = data_structure.grid
    cells = data_structure.entity_set(grid.cells)
    dimensions = len(grid.shape)
    shape = tuple(grid.shape) + (1,) * (3 - dimensions)
    spacing = tuple(grid.spacing) + (1.,) * (3 - dimensions)
    origin = tuple(grid.origin) + (0.,) * (3 - dimensions)
    image = vtkImageData()
    image.SetDimensions(*(n + 1 for n in shape))
    image.SetSpacing(*spacing)
    image.SetOrigin(*origin)
    if not grid.z_up and dimensions == 3:
        image.SetDirectionMatrix(1., 0., 0., 0., 1., 0., 0., 0., -1.)      # z pointing down
    order = np.arange(int(np.prod(shape))).reshape(shape).ravel(order="F")   # VTK: the first axis varies fastest
    _add_columns(image.GetCellData(), cells, order, image.GetFieldData(), settings)
    return image


def _adaptive_grid(data_structure, settings: bool = False):
    grid = data_structure.grid
    cells = data_structure.entity_set(grid.cells)
    level = cells.columns["level"].astype(np.int64)
    index = cells.columns["index"].astype(np.float64)
    size = np.asarray(grid.spacing, dtype=np.float64)[None, :] / (2. ** level)[:, None]
    lower = np.asarray(grid.origin, dtype=np.float64)[None, :] + index * size
    upper = lower + size
    if not grid.z_up:
        lower[:, 2], upper[:, 2] = -upper[:, 2], -lower[:, 2]
    corners = []
    for z in (0, 1):
        for y, x in ((0, 0), (0, 1), (1, 1), (1, 0)):                # VTK hexahedron order
            corners.append(np.stack([np.where(x, upper[:, 0], lower[:, 0]), np.where(y, upper[:, 1], lower[:, 1]),
                                     np.where(z, upper[:, 2], lower[:, 2])], axis=1))
    points_array = np.stack(corners, axis=1).reshape(-1, 3)
    unstructured = vtkUnstructuredGrid()
    points = vtkPoints()
    points.SetData(numpy_to_vtk(np.ascontiguousarray(points_array), deep=True))
    unstructured.SetPoints(points)
    count = cells.count
    cell_array = vtkCellArray()
    cell_array.SetData(numpy_to_vtkIdTypeArray(np.arange(0, 8 * count + 1, 8, dtype=np.int64), deep=True),
                       numpy_to_vtkIdTypeArray(np.arange(8 * count, dtype=np.int64), deep=True))
    unstructured.SetCells(VTK_HEXAHEDRON, cell_array)
    _add_columns(unstructured.GetCellData(), cells, np.arange(count), unstructured.GetFieldData(), settings)
    return unstructured


def _named(blocks: vtkMultiBlockDataSet, data_set, name: str) -> None:
    number = blocks.GetNumberOfBlocks()
    blocks.SetBlock(number, data_set)
    blocks.GetMetaData(number).Set(vtkMultiBlockDataSet.NAME(), name)


def frame_to_vtk(frame, settings: bool = False) -> vtkMultiBlockDataSet:
    """The frame as a multiblock data set: one block per data structure, holding its meshes, its entity sets with
    segment ends as lines, and its grid. *settings*: also the graph's links (complex, parent, edge_type) and the
    columns of role "setting"."""
    output = vtkMultiBlockDataSet()
    for data_structure in frame.data_structures:
        blocks = vtkMultiBlockDataSet()
        for mesh in data_structure.meshes:
            _named(blocks, _mesh(mesh, data_structure, settings), f"mesh {mesh.name}")
        for entity_set in data_structure.entity_sets:
            columns = _segment_columns(entity_set)
            if columns:
                _named(blocks, _segments(entity_set, columns, data_structure, settings), f"{entity_set.name} segments")
        if data_structure.grid is not None:
            build = _regular_grid if data_structure.grid.kind == "regular" else _adaptive_grid
            _named(blocks, build(data_structure, settings), "grid")
        if blocks.GetNumberOfBlocks():
            _named(output, blocks, data_structure.id)
    return output


class Source:
    """A .glb frame or a scene.fspm.json sequence: its times, and its frame at a time."""

    def __init__(self, path: str):
        self.path = path
        fspm_tf = _fspm_tf()
        if path.endswith(".json"):
            index = fspm_tf.read_index(path)
            self.paths = [entry["path"] for entry in index["frames"]]
            self.times = [float(entry["time"]) for entry in index["frames"]]
        else:
            self.paths = [path]
            self.times = [float(fspm_tf.read(path).time)]
        self._cache = {}

    def frame_at(self, time: float = None):
        """The frame of the last time not after *time* (the first frame for None or an earlier time)."""
        number = 0
        if time is not None:
            earlier = [n for n, frame_time in enumerate(self.times) if frame_time <= time + 1e-12 * max(1., abs(time))]
            number = earlier[-1] if earlier else 0
        if number not in self._cache:
            self._cache = {number: _fspm_tf().read(self.paths[number])}
        return self._cache[number]


# ── The ParaView reader ──────────────────────────────────────────────────────

try:
    from paraview.util.vtkAlgorithm import VTKPythonAlgorithmBase, smdomain, smhint, smproperty, smproxy
except ImportError:                                  # VTK without ParaView: frame_to_vtk and Source only
    VTKPythonAlgorithmBase = None

if VTKPythonAlgorithmBase is not None:
    @smproxy.reader(name="fspmTFReader", label="fspm-TF reader", extensions="glb json",
                    file_description="fspm-TF frames (.glb) and sequences (scene.fspm.json)")
    class FspmTFReader(VTKPythonAlgorithmBase):
        def __init__(self):
            VTKPythonAlgorithmBase.__init__(self, nInputPorts=0, nOutputPorts=1, outputType="vtkMultiBlockDataSet")
            self._file_name, self._source, self._settings = None, None, False

        @smproperty.stringvector(name="FileName")
        @smdomain.filelist()
        @smhint.filechooser(extensions="glb json", file_description="fspm-TF frames and sequences")
        def SetFileName(self, name):
            if name != self._file_name:
                self._file_name, self._source = name, None
                self.Modified()

        @smproperty.xml("""<IntVectorProperty name="ShowSettings" command="SetShowSettings" number_of_elements="1"
                                              default_values="0">
                             <BooleanDomain name="bool"/>
                             <Documentation>Also the graph's links (complex, parent, edge_type) and the columns of
                             role "setting" (a platform's own bookkeeping).</Documentation>
                           </IntVectorProperty>""")
        def SetShowSettings(self, value):
            if bool(value) != self._settings:
                self._settings = bool(value)
                self.Modified()

        def _opened(self):
            if self._source is None and self._file_name:
                self._source = Source(self._file_name)
            return self._source

        @smproperty.doublevector(name="TimestepValues", information_only="1", si_class="vtkSITimeStepsProperty")
        def GetTimestepValues(self):
            source = self._opened()
            return source.times if source is not None and len(source.times) > 1 else None

        def RequestInformation(self, request, in_info, out_info):
            information = out_info.GetInformationObject(0)
            pipeline = vtkStreamingDemandDrivenPipeline
            information.Remove(pipeline.TIME_STEPS())
            information.Remove(pipeline.TIME_RANGE())
            source = self._opened()
            if source is not None and len(source.times) > 1:
                for time in source.times:
                    information.Append(pipeline.TIME_STEPS(), time)
                information.Append(pipeline.TIME_RANGE(), source.times[0])
                information.Append(pipeline.TIME_RANGE(), source.times[-1])
            return 1

        def RequestData(self, request, in_info, out_info):
            information = out_info.GetInformationObject(0)
            pipeline = vtkStreamingDemandDrivenPipeline
            time = information.Get(pipeline.UPDATE_TIME_STEP()) if information.Has(pipeline.UPDATE_TIME_STEP()) \
                else None
            frame = self._opened().frame_at(time)
            output = vtkMultiBlockDataSet.GetData(out_info, 0)
            output.ShallowCopy(frame_to_vtk(frame, settings=self._settings))
            if time is not None:
                output.GetInformation().Set(output.DATA_TIME_STEP(), frame.time)
            return 1
