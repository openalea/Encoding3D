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

With views (specification §8.1: a views.json next to the file, or the one "Views" names), the output is instead one
block per layer of the chosen "Configuration" (the file's active one by default), named by the layer: only its
selected entities (a mesh's triangles whose rows at the select entity set match, the segments whose rows match, the
grid's cells, the others hidden), its colour variable as the active scalars, a segments layer's tube radius as point
data "tube_radius"; hidden layers are there too, and a layer whose names a frame lacks is an empty block. The macros
apply_fspm_tf_views.py and save_fspm_tf_views.py (next to this file; Macros > Import new macro...) make each layer its
own pipeline item, and write the items' display options back into the views file.

frame_to_vtk(frame) builds the output without ParaView (VTK only), e.g. for scripts and tests.
"""
import os
import sys

import numpy as np
from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
from vtkmodules.vtkCommonCore import vtkPoints, vtkStringArray
from vtkmodules.vtkCommonDataModel import (VTK_HEXAHEDRON, vtkCellArray, vtkDataSetAttributes, vtkImageData,
                                           vtkMultiBlockDataSet, vtkPolyData, vtkUnstructuredGrid)
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


def _views():
    _fspm_tf()
    from openalea.fspm_tf import views
    return views


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


def _add_columns(data, entity_set, rows: np.ndarray, field_data, settings: bool = False, forced=()) -> None:
    """Cell data of *entity_set*'s columns, one value per cell from *rows* (-1: no entity, NaN); the columns
    *forced* (a layer's colour variable) whatever their role."""
    valid = rows >= 0
    taken = np.where(valid, rows, 0)
    for name, column in entity_set.columns.items():
        if not _shown(entity_set, name, settings) and name not in forced:
            continue
        label = f"{entity_set.name}.{name}"
        if column.dtype == object:
            if name not in ("label", "relation") and name not in forced and len(set(column.tolist())) > 64:
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


def _mesh(mesh, data_structure, settings: bool = False, kept: np.ndarray = None, forced: dict = None):
    """The mesh's triangles (those *kept*, a mask, when given); *forced*: {entity set: columns}, see _add_columns."""
    polydata = vtkPolyData()
    points = vtkPoints()
    points.SetData(numpy_to_vtk(np.ascontiguousarray(_transform(mesh.positions, data_structure.origin)), deep=True))
    polydata.SetPoints(points)
    corners = mesh.indices if mesh.indices is not None else np.arange(len(mesh.positions))
    triangles = corners.reshape(-1, 3)
    if kept is not None:
        triangles = triangles[kept]
    offsets = np.arange(0, 3 * len(triangles) + 1, 3, dtype=np.int64)
    cells = vtkCellArray()
    cells.SetData(numpy_to_vtkIdTypeArray(offsets, deep=True),
                  numpy_to_vtkIdTypeArray(np.ascontiguousarray(triangles.reshape(-1), dtype=np.int64), deep=True))
    polydata.SetPolys(cells)
    for set_name, rows in mesh.feature_rows.items():
        _add_columns(polydata.GetCellData(), data_structure.entity_set(set_name), rows[triangles[:, 0]],
                     polydata.GetFieldData(), settings, (forced or {}).get(set_name, ()))
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


def _segments(entity_set, columns: list, data_structure, settings: bool = False, rows: np.ndarray = None,
              forced=(), tube_radius: np.ndarray = None):
    """One line per entity (per row of *rows* when given); *tube_radius*: a radius per entity, as point data."""
    rows = np.arange(entity_set.count) if rows is None else rows
    ends = np.stack([entity_set.columns[name].astype(np.float64)[rows] for name in columns], axis=1)
    count = len(rows)
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
    _add_columns(polydata.GetCellData(), entity_set, rows, polydata.GetFieldData(), settings, forced)
    if tube_radius is not None:
        radius = np.asarray(tube_radius, dtype=np.float64)[rows]
        polydata.GetPointData().AddArray(_array(_views().TUBE_RADIUS, np.concatenate([radius, radius])))
    return polydata


def _regular_grid(data_structure, settings: bool = False, kept: np.ndarray = None, forced=()):
    """The grid as image data; the cells not *kept* (a mask over the cells' rows) hidden."""
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
    _add_columns(image.GetCellData(), cells, order, image.GetFieldData(), settings, forced)
    if kept is not None:
        ghosts = np.where(kept[order], 0, vtkDataSetAttributes.HIDDENCELL).astype(np.uint8)
        image.GetCellData().AddArray(_array(vtkDataSetAttributes.GhostArrayName(), ghosts))
    return image


def _adaptive_grid(data_structure, settings: bool = False, kept: np.ndarray = None, forced=()):
    """The grid's leaf cells as hexahedra (those *kept*, a mask, when given)."""
    grid = data_structure.grid
    cells = data_structure.entity_set(grid.cells)
    rows = np.arange(cells.count) if kept is None else np.flatnonzero(kept)
    level = cells.columns["level"].astype(np.int64)[rows]
    index = cells.columns["index"].astype(np.float64)[rows]
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
    count = len(rows)
    cell_array = vtkCellArray()
    cell_array.SetData(numpy_to_vtkIdTypeArray(np.arange(0, 8 * count + 1, 8, dtype=np.int64), deep=True),
                       numpy_to_vtkIdTypeArray(np.arange(8 * count, dtype=np.int64), deep=True))
    unstructured.SetCells(VTK_HEXAHEDRON, cell_array)
    _add_columns(unstructured.GetCellData(), cells, rows, unstructured.GetFieldData(), settings, forced)
    return unstructured


def _named(blocks: vtkMultiBlockDataSet, data_set, name: str) -> None:
    number = blocks.GetNumberOfBlocks()
    blocks.SetBlock(number, data_set)
    blocks.GetMetaData(number).Set(vtkMultiBlockDataSet.NAME(), name)


def _layer(frame, layer: dict, settings: bool = False):
    """The data set of a layer (views.configuration's, its defaults filled): its selected entities only, its colour
    variable as the active scalars; empty when the frame lacks a name it gives (e.g. a mesh drawn from a later frame
    on), so that every frame of a sequence has the same blocks."""
    views = _views()
    report = views.check_views({"fspm_tf_views": views.FORMAT, "configurations": {"layer": {"layers": [layer]}}}, frame)
    if not report.ok:
        return vtkPolyData()
    source = layer["source"]
    data_structure = frame.data_structure(source["data_structure"])
    select = layer.get("select")
    chosen = (data_structure.entity_set(select["entity_set"]), select["where"]) if select else None
    colour = layer.get("color_by")
    forced = {colour["entity_set"]: (colour["variable"],)} if colour else {}
    if source["kind"] == "mesh":
        mesh = next(mesh for mesh in data_structure.meshes if mesh.name == source["mesh"])
        kept = None
        if chosen is not None:
            corners = mesh.indices if mesh.indices is not None else np.arange(len(mesh.positions))
            rows = mesh.feature_rows[chosen[0].name][corners.reshape(-1, 3)[:, 0]]
            matching = views.selected(*chosen)
            kept = (rows >= 0) & matching[np.where(rows >= 0, rows, 0)]
        data_set = _mesh(mesh, data_structure, settings, kept, forced)
    elif source["kind"] == "segments":
        entity_set = data_structure.entity_set(source["entity_set"])
        rows = np.flatnonzero(views.selected(*chosen)) if chosen is not None else None
        tube = layer.get("tube")
        radius = entity_set.columns[tube["radius"]].astype(np.float64) * float(tube.get("scale", 1.)) if tube else None
        data_set = _segments(entity_set, _segment_columns(entity_set), data_structure, settings, rows,
                             forced.get(entity_set.name, ()), radius)
    else:
        kept = views.selected(*chosen) if chosen is not None else None
        build = _regular_grid if data_structure.grid.kind == "regular" else _adaptive_grid
        data_set = build(data_structure, settings, kept, forced.get(data_structure.grid.cells, ()))
    array = views.colour_array(layer, {data_set.GetCellData().GetArrayName(number)
                                       for number in range(data_set.GetCellData().GetNumberOfArrays())})
    if array is not None:
        data_set.GetCellData().SetActiveScalars(array)
    return data_set


def frame_to_vtk(frame, settings: bool = False, views=None, configuration: str = None) -> vtkMultiBlockDataSet:
    """The frame as a multiblock data set: one block per data structure, holding its meshes, its entity sets with
    segment ends as lines, and its grid. *settings*: also the graph's links (complex, parent, edge_type) and the
    columns of role "setting".

    *views* (a views document, or the path of a views.json): instead, one block per layer of the *configuration*
    (None: the active one), named by the layer, hidden layers included (see _layer)."""
    if views is not None:
        views_module = _views()
        document = views_module.read_views(views) if isinstance(views, (str, os.PathLike)) else views
        report = views_module.check_views(document)
        if not report.ok:
            raise ValueError(str(report))
        output = vtkMultiBlockDataSet()
        for layer in views_module.configuration(document, configuration)[1]:
            _named(output, _layer(frame, layer, settings), layer["name"])
        return output
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
            with fspm_tf.read(path, lazy=True) as frame:         # its time, from the file's JSON alone
                self.times = [float(frame.time)]
        self._cache = {}

    def frame_at(self, time: float = None):
        """The frame of the last time not after *time* (the first frame for None or an earlier time)."""
        number = 0
        if time is not None:
            earlier = [n for n, frame_time in enumerate(self.times) if frame_time <= time + 1e-12 * max(1., abs(time))]
            number = earlier[-1] if earlier else 0
        if number not in self._cache:                     # read lazily: only what the display reads is decoded
            for frame in self._cache.values():
                frame.close()
            self._cache = {number: _fspm_tf().read(self.paths[number], lazy=True)}
        return self._cache[number]


# ── The ParaView reader ──────────────────────────────────────────────────────

try:
    from paraview.util.vtkAlgorithm import VTKPythonAlgorithmBase, smdomain, smhint, smproperty, smproxy
except ImportError:                                  # VTK without ParaView: frame_to_vtk and Source only
    VTKPythonAlgorithmBase = None

if VTKPythonAlgorithmBase is not None:
    try:
        _fspm_tf()                                   # on ParaView's path now: the views macros import it too
    except ImportError:
        pass

    @smproxy.reader(name="fspmTFReader", label="fspm-TF reader", extensions="glb json",
                    file_description="fspm-TF frames (.glb) and sequences (scene.fspm.json)")
    class FspmTFReader(VTKPythonAlgorithmBase):
        def __init__(self):
            VTKPythonAlgorithmBase.__init__(self, nInputPorts=0, nOutputPorts=1, outputType="vtkMultiBlockDataSet")
            self._file_name, self._source, self._settings = None, None, False
            self._views, self._configuration = "", ""

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

        @smproperty.stringvector(name="Views", default_values="")
        @smdomain.filelist()
        @smhint.filechooser(extensions="json", file_description="fspm-TF views (views.json)")
        def SetViews(self, name):
            """The views file (empty: the views.json next to the file, when there is one; none: today's blocks)."""
            if (name or "") != self._views:
                self._views = name or ""
                self.Modified()

        def _views_path(self):
            return _views().views_path(self._file_name, self._views) if self._file_name else None

        @smproperty.stringvector(name="ConfigurationNames", information_only="1")
        def GetConfigurationNames(self):
            path = self._views_path()
            return _views().configuration_names(_views().read_views(path)) if path else []

        @smproperty.stringvector(name="Configuration", number_of_elements="1", default_values="")
        @smdomain.xml("""<StringListDomain name="list">
                           <RequiredProperties>
                             <Property name="ConfigurationNames" function="StringInfo"/>
                           </RequiredProperties>
                         </StringListDomain>""")
        def SetConfiguration(self, name):
            """The configuration shown (empty: the views' active one)."""
            if (name or "") != self._configuration:
                self._configuration = name or ""
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
            path = self._views_path()
            output.ShallowCopy(frame_to_vtk(frame, settings=self._settings, views=path,
                                            configuration=self._configuration or None))
            if time is not None:
                output.GetInformation().Set(output.DATA_TIME_STEP(), frame.time)
            return 1
