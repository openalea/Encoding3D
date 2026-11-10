"""
encoding3d's ParaView plugin: the "encoding3d reader" opens a frame (.glb) or a sequence (scene.fspm.json, or a
.fspm.zip archive: its frames as time steps), with every variable of every scale as data arrays, and draws its views
(views.json) layer by layer; the filter "encoding3d Select at scale" grows picked cells to their plant, axis, organ ...
and rebuilds the derived fields of the instances it holds (paraview/README.md, the how-to).

    ParaView >= 5.11: Tools > Manage Plugins > Load New..., choose this file (tick "Auto Load" to keep it); then
    File > Open a .glb, a scene.fspm.json or a .fspm.zip and pick "encoding3d reader".

The reader needs openalea.encoding3d: found in ParaView's Python when installed there, else in the bindings/python/src
folder of the encoding3d clone holding this file (nothing to install: the codec needs numpy only, which ParaView ships).

What it shows, one block per data structure:

    mesh <name>     its triangles; cell data: for each entity set the mesh represents (by feature IDs), the entity's
                    id and every numeric variable of it, named "<entity set>.<variable>" (NaN where a triangle has no
                    entity at that scale); point data: the display copies
    <entity set>    for an entity set with segment ends (the standard names proximal_end_x ... distal_end_z, or
      segments      columns x1 ... z2), one line per entity with its variables as cell data (a Tube filter on
                    "radius" draws roots)
    grid            a regular grid as image data (z pointing down when the grid says so), an adaptive grid as
                    hexahedra, the cells' variables as cell data
    instances <name>  an instance set (specification §12): each instance's template meshes placed by its transform;
                    cell data: the ids of its owner and of the entities containing it, its instance's row and its
                    rows in the template's entity sets, and a layer's colour variable ("All Instance Arrays": also
                    the instance's own variables "<instance set>.<variable>", its owner's "<owners>.<variable>", its
                    template's constants "<template entity set>.<variable>"); its derived fields ("<template entity
                    set>.<field>") when "Evaluate Derived Fields" is ticked, else rebuilt by "encoding3d Select at
                    scale" for the instances it selects

Labels and other text columns become integer codes ("<entity set>.label_code", the names in the block's field data).
The graph's links (complex, parent, edge_type) and the columns of role "setting" (a platform's own bookkeeping, e.g.
metafspm's MPG links) are left out unless "Show Settings" is ticked. An array of a declared variable (or a derived
field) holds the variable's unit (UCUM) in its information (vtkDataArray.UNITS_LABEL), which the layers' colour
legends show ("<array> [<unit>]"); an undeclared column (id, label, ...) has none.
Data structures are placed by their origin.

With views (specification §8.1: a views.json next to the file, or the one "Views" names), the output is instead one
block per layer of the chosen "Configuration" (the file's active one by default), named by the layer: only its
selected entities (a mesh's triangles whose rows at the select entity set match, the segments whose rows match, the
grid's cells, the others hidden), its colour variable as the active scalars, a segments layer with a "tube" as tubes
(radius also as point data "tube_radius"); hidden layers are there too (a hidden instances layer as an empty block,
its instances placed by "encoding3d Select at scale" for what it selects, unless "Expand Hidden Instances"), and a
layer whose names a frame lacks is an empty block. The plugin then draws each layer as its block, with its own colour
variable, colour map, range, log scale or solid colour, opacity and visibility (encoding3d_displays.py, next to this
file: it watches the representations ParaView makes, and draws them again when "Configuration" changes, or the arrays
its data holds); the MultiBlock Inspector edits a layer, the reader's "Save Views" button writes the display back into
the views file ("Save As": a new configuration).

Every cell also has the ids of the entities containing its own ("<entity set>.id" at each coarser scale, through the
complex links: a root segment's Organ, Axis and Plant), and every block its data structure (field data
encoding3d_data_structure) and its graph's scales (encoding3d_scales, coarser first). The plugin's filter "encoding3d Select
at scale" (Filters > encoding3d), applied with cells picked on the reader or any item drawn from it, grows them to their
plant, axis, organ ... ("Scale", a drop-down of the scales) with everything it holds at finer scales, in every block
of the reader (every layer, the hidden ones included), the same blocks with their arrays, drawn as the layers; the
picked entities are followed through the time steps. Its buttons Isolate (the other items hidden), Show In Panel (a
render view of its own) and Put Back (one step back) show it, at the Scale applied ("picked", the picked cells' own
scale, until another is chosen and applied). The reader and the filter share the frames open (open_frame).

frame_to_vtk(frame) builds the output without ParaView (VTK only), e.g. for scripts and tests; picked_cells,
grow_selection (grow_entities), rebuild_derived and missing_instances, the filter's.
"""
import collections
import json
import os
import sys

import numpy as np
from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy
from vtkmodules.vtkCommonCore import vtkDataArray, vtkOutputWindow, vtkPoints, vtkStringArray
from vtkmodules.vtkCommonDataModel import (VTK_HEXAHEDRON, vtkCellArray, vtkDataObject, vtkDataObjectTree,
                                           vtkDataSetAttributes, vtkImageData, vtkMultiBlockDataSet, vtkPolyData,
                                           vtkSelection, vtkUnstructuredGrid)
from vtkmodules.vtkCommonExecutionModel import vtkAlgorithm, vtkStreamingDemandDrivenPipeline
from vtkmodules.vtkFiltersCore import vtkThreshold
from vtkmodules.vtkFiltersExtraction import vtkExtractSelection
from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter


def _encoding3d():
    try:
        from openalea import encoding3d
    except ImportError:
        source = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bindings", "python", "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        from openalea import encoding3d
    return encoding3d


def _views():
    _encoding3d()
    from openalea.encoding3d import views
    return views


SEGMENT_ENDS = (("proximal_end_x", "x1"), ("proximal_end_y", "y1"), ("proximal_end_z", "z1"),
                ("distal_end_x", "x2"), ("distal_end_y", "y2"), ("distal_end_z", "z2"))


# ── Frames to VTK data sets ──────────────────────────────────────────────────

def _array(name: str, values: np.ndarray, deep: bool = True, unit: str = None):
    """A VTK array of *values*; *deep* False for values made for it alone (the array then holds them, no copy);
    *unit*: its variable's declared unit (UCUM), in its information (vtkDataArray.UNITS_LABEL; None: none declared)."""
    values = np.ascontiguousarray(values)
    array = numpy_to_vtk(values, deep=deep)
    array.SetName(name)
    if unit is not None:
        array.GetInformation().Set(vtkDataArray.UNITS_LABEL(), str(unit))
    return array


def unit_of(entity_set, name: str):
    """The declared unit of column *name* of *entity_set* (None: the column has no declaration)."""
    declared = entity_set.variables.get(name)
    return declared.unit if declared is not None else None


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


def _add_columns(data, entity_set, rows: np.ndarray, field_data, settings: bool = False, forced=(),
                 only=None) -> None:
    """Cell data of *entity_set*'s columns, one value per cell from *rows* (-1: no entity, NaN); the columns
    *forced* (a layer's colour variable) whatever their role; *only*: those columns alone (and the forced ones)."""
    valid = rows >= 0
    taken = np.where(valid, rows, 0)
    for name, column in entity_set.columns.items():
        if only is not None and name not in only and name not in forced:
            continue
        if not _shown(entity_set, name, settings) and name not in forced:
            continue
        label = f"{entity_set.name}.{name}"
        if column.dtype == object:
            if name not in ("label", "relation") and name not in forced and len(set(column.tolist())) > 64:
                continue                                    # free text: not a colouring
            codes, names = _codes(column)
            values = np.where(valid, codes[taken], -1)
            data.AddArray(_array(f"{label}_code", values, deep=False))
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
        data.AddArray(_array(label, values, deep=False, unit=unit_of(entity_set, name)))


def _instances_module():
    _encoding3d()
    from openalea.encoding3d import instances
    return instances


INSTANCE_SET_FIELD = "encoding3d_instance_set"   # field data of an instances block: its instance set
FRAME_FIELD = "encoding3d_frame"                 # and the file of its frame (where the filter rebuilds derived fields)
UNEXPANDED_FIELD = "encoding3d_unexpanded"       # and, for a hidden layer's block left empty, how to build its part
INSTANCE_ROW = "encoding3d_instance"             # cell data: each cell's instance (its row in the instance set)
TEMPLATE_ROW = "encoding3d_template_row."        # + a template entity set: each cell's row in it


def _merged_template_sets(frame, instance_set, set_name: str, templates: list):
    """One entity set of the rows of *set_name* of every template of *templates* (indices in the set's parts), one
    after the other, the columns of all (missing: NaN, or None for text); and each template's first row in it."""
    model = sys.modules[_encoding3d().EntitySet.__module__]
    tables, offsets, start = [], {}, 0
    for index in templates:
        try:
            table = frame.part(instance_set.parts[index]).entity_set(set_name)
        except KeyError:
            continue
        tables.append(table)
        offsets[index] = start
        start += table.count
    names = list(dict.fromkeys(name for table in tables for name in table.columns))
    columns, variables = {}, {}
    for name in names:
        parts = []
        for table in tables:
            if name in table.columns:
                column = np.ma.filled(table.columns[name], np.nan) if np.ma.isMaskedArray(table.columns[name]) \
                    else table.columns[name]
                parts.append(column.astype(object) if column.dtype == object or any(
                    other.columns.get(name, column).dtype == object for other in tables) else column)
            else:
                text = any(other.columns[name].dtype == object for other in tables if name in other.columns)
                parts.append(np.full(table.count, None, dtype=object) if text else np.full(table.count, np.nan))
        columns[name] = np.concatenate(parts) if parts else np.zeros(0)
        for table in tables:
            if name in table.variables:
                variables[name] = table.variables[name]
    return model.EntitySet(set_name, columns=columns, variables=variables), offsets


def _owner_rows(data_structure, instance_set) -> np.ndarray:
    """Each instance's owner's row in the owners' entity set (-1: none)."""
    if instance_set.owners is None or "owner" not in instance_set.columns:
        return np.full(instance_set.count, -1, dtype=np.int64)
    owners = data_structure.entity_set(instance_set.owners)
    ids = np.asarray(owners.ids(), dtype=np.int64)
    order = np.argsort(ids, kind="stable")
    wanted = np.asarray(instance_set.columns["owner"], dtype=np.int64)
    position = np.searchsorted(ids[order], wanted).clip(0, max(ids.size - 1, 0))
    found = ids.size > 0
    return np.where(found & (ids[order][position] == wanted) if found else np.zeros(wanted.size, dtype=bool),
                    order[position] if found else -1, -1)


def _instances(frame, data_structure, instance_set, settings: bool = False, rows=None, forced: dict = None,
               derived: bool = False, all_arrays: bool = False):
    """The placed template meshes of the instances at *rows* (all for None) of *instance_set*: cell data of the ids of
    their owners and of the entities containing them, each cell's instance and template rows, and of the variables
    *forced* ({entity set: columns}, a layer's colour variable); *all_arrays*: also every other variable of the
    instances, of their owners and of their templates (one value per triangle each: the block's largest part);
    *derived*: its derived fields evaluated too."""
    instances = _instances_module()
    placed = instances.placed_meshes(frame, data_structure, instance_set, instances=rows)
    polydata = vtkPolyData()
    points = vtkPoints()                                # (made for the block: held by VTK, not copied)
    points.SetData(numpy_to_vtk(np.ascontiguousarray(_transform(placed.positions, data_structure.origin)), deep=False))
    polydata.SetPoints(points)
    count = len(placed.triangles)
    cells = vtkCellArray()
    cells.SetData(numpy_to_vtkIdTypeArray(np.arange(0, 3 * count + 1, 3, dtype=np.int64), deep=False),
                  numpy_to_vtkIdTypeArray(np.ascontiguousarray(placed.triangles.reshape(-1), dtype=np.int64),
                                          deep=False))
    polydata.SetPolys(cells)
    forced = forced or {}
    only = None if all_arrays else ()
    cell_data, field_data = polydata.GetCellData(), polydata.GetFieldData()
    own = sys.modules[_encoding3d().Table.__module__].Table(instance_set.name, columns={
        name: column for name, column in instance_set.columns.items() if name not in ("transform", "template")},
        variables=instance_set.variables)
    if own.columns:
        _add_columns(cell_data, own, placed.instance, field_data, settings, forced.get(instance_set.name, ()), only)
    cell_data.AddArray(_array(INSTANCE_ROW, placed.instance.astype(np.int64), deep=False))
    owner_rows = _owner_rows(data_structure, instance_set)[placed.instance] if count else np.zeros(0, dtype=np.int64)
    if instance_set.owners is not None:
        owners = data_structure.entity_set(instance_set.owners)
        _add_columns(cell_data, owners, owner_rows, field_data, settings, forced.get(owners.name, ()),
                     None if all_arrays else ("id",))
        if owners.rank is not None:
            _add_ancestors(polydata, data_structure, owners.name, owner_rows)
    templates = np.unique(placed.template).tolist()
    for set_name, template_rows in placed.template_rows.items():
        if all_arrays or forced.get(set_name):
            merged, offsets = _merged_template_sets(frame, instance_set, set_name, templates)
            start = np.array([offsets.get(index, -1) for index in placed.template], dtype=np.int64)
            merged_rows = np.where((template_rows >= 0) & (start >= 0), start + template_rows, -1)
            if merged.columns:
                _add_columns(cell_data, merged, merged_rows, field_data, settings, forced.get(set_name, ()), only)
        cell_data.AddArray(_array(TEMPLATE_ROW + set_name, template_rows.astype(np.int64), deep=False))
    del placed
    _identify(polydata, data_structure)
    _name_frame(polydata, frame, instance_set)
    if derived and count:
        _add_derived(polydata, frame, data_structure, instance_set)
    return polydata


def _name_frame(data_set, frame, instance_set) -> None:
    """Field data: the instance set of *data_set* (an instances block) and its frame's file."""
    for name, value in ((INSTANCE_SET_FIELD, instance_set.name), (FRAME_FIELD, getattr(frame, "path", "") or "")):
        listed = vtkStringArray()
        listed.SetName(name)
        listed.InsertNextValue(str(value))
        data_set.GetFieldData().AddArray(listed)


def _unexpanded(frame, data_structure, instance_set, layer: dict, settings: bool, all_arrays: bool):
    """The empty block of a hidden instances layer: its instance set, frame, data structure and scales as field data,
    and the layer (UNEXPANDED_FIELD), from which "encoding3d Select at scale" builds the part it selects."""
    polydata = vtkPolyData()
    _identify(polydata, data_structure)
    _name_frame(polydata, frame, instance_set)
    listed = vtkStringArray()
    listed.SetName(UNEXPANDED_FIELD)
    listed.InsertNextValue(json.dumps({"layer": layer, "settings": bool(settings), "all_arrays": bool(all_arrays)}))
    polydata.GetFieldData().AddArray(listed)
    return polydata


def _layer_instance_rows(data_structure, instance_set, select) -> np.ndarray:
    """The rows of *instance_set* a layer's *select* keeps (by the instances' own columns or by their owners'); None
    without one: all."""
    if not select:
        return None
    views = _views()
    if select["entity_set"] == instance_set.name:
        return np.flatnonzero(views.selected(instance_set, select["where"]))
    matching = views.selected(data_structure.entity_set(select["entity_set"]), select["where"])
    owners = _owner_rows(data_structure, instance_set)
    return np.flatnonzero((owners >= 0) & matching[np.where(owners >= 0, owners, 0)])


def instance_rows_at(data_structure, instance_set, ids, scale: str) -> np.ndarray:
    """The rows of the instances of *instance_set* whose owner is, or is inside, one of the entities *ids* at
    *scale* (its owners' set, or a coarser scale of theirs)."""
    if instance_set.owners is None:
        return np.zeros(0, dtype=np.int64)
    owners = data_structure.entity_set(instance_set.owners)
    owner_rows = _owner_rows(data_structure, instance_set)
    if scale == owners.name:
        found = np.where(owner_rows >= 0, np.asarray(owners.columns["id"], dtype=np.int64)[np.maximum(owner_rows, 0)],
                         -1)
    else:
        found = _views().ancestor_ids(data_structure, owners.name, owner_rows).get(scale)
        if found is None:
            return np.zeros(0, dtype=np.int64)
    return np.flatnonzero((owner_rows >= 0) & np.isin(found, np.asarray(list(ids), dtype=np.int64)))


def _add_derived(data_set, frame, data_structure, instance_set) -> None:
    """Cell data "<template entity set>.<field>" of each derived field of *instance_set*, for the instances *data_set*'s
    cells are in (their INSTANCE_ROW), evaluated now (NaN where a cell has no row in the field's entity set)."""
    cell_data = data_set.GetCellData()
    rows_array = cell_data.GetArray(INSTANCE_ROW)
    if rows_array is None or not data_set.GetNumberOfCells():
        return
    cell_instances = vtk_to_numpy(rows_array).astype(np.int64)
    chosen = np.unique(cell_instances)
    position_of = np.full(instance_set.count, -1, dtype=np.int64)
    position_of[chosen] = np.arange(chosen.size)
    for derived in instance_set.derived:
        template_rows = cell_data.GetArray(TEMPLATE_ROW + derived.entity_set)
        if template_rows is None:
            continue
        values = _evaluated(frame, data_structure, instance_set, derived.name, chosen)
        lengths = np.array([value.size for value in values], dtype=np.int64)
        flat = np.concatenate(values) if values else np.zeros(0)
        starts = np.concatenate([[0], np.cumsum(lengths)[:-1]]).astype(np.int64)
        rows = vtk_to_numpy(template_rows).astype(np.int64)
        position = position_of[cell_instances]
        valid = (rows >= 0) & (rows < lengths[position])
        out = np.full(rows.size, np.nan)
        out[valid] = flat[starts[position[valid]] + rows[valid]]
        cell_data.AddArray(_array(f"{derived.entity_set}.{derived.name}", out, deep=False,
                                  unit=derived.variable.unit if derived.variable is not None else None))


_DERIVED = {}       # {(frame file, data structure, instance set, field): {instance row: values}} of the frames open


def _evaluated(frame, data_structure, instance_set, field: str, rows: np.ndarray) -> list:
    """The derived field *field* of the instances at *rows*, evaluated once per frame open (open_frame): a selection
    switched back to a scale, or a time step seen again while its frame is open, is not evaluated again."""
    path = getattr(frame, "path", "") or ""
    if _FRAMES.get(path) is not frame:                  # a frame not shared: evaluated, not kept
        return _instances_module().evaluate(frame, field, instances=rows, data_structure=data_structure.id,
                                            instance_set=instance_set.name)
    known = _DERIVED.setdefault((path, data_structure.id, instance_set.name, field), {})
    missing = np.array([row for row in rows.tolist() if row not in known], dtype=np.int64)
    if missing.size:
        values = _instances_module().evaluate(frame, field, instances=missing, data_structure=data_structure.id,
                                              instance_set=instance_set.name)
        known.update(zip(missing.tolist(), values))
    return [known[row] for row in rows.tolist()]


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
    ranks = {name: data_structure.entity_set(name).rank for name in mesh.feature_rows}
    ranked = [name for name in ranks if ranks[name] is not None]
    if ranked:                                 # the finest scale's containing entities, where the mesh lacks them
        finest = max(ranked, key=ranks.get)
        _add_ancestors(polydata, data_structure, finest, mesh.feature_rows[finest][triangles[:, 0]])
    _identify(polydata, data_structure)
    for name, values in mesh.display.items():
        polydata.GetPointData().AddArray(_array(f"display.{name}", np.asarray(values, dtype=np.float32)))
    return polydata


def _add_ancestors(data_set, data_structure, set_name: str, rows: np.ndarray) -> None:
    """Cell data "<entity set>.id" of the entities containing each cell's entity (at *rows* of *set_name*), for the
    coarser scales the cells have no array of yet: what selection by scale grows a picked cell to."""
    cell_data = data_set.GetCellData()
    for name, ids in _views().ancestor_ids(data_structure, set_name, rows).items():
        label = _views().id_array(name)
        if not cell_data.HasArray(label):
            cell_data.AddArray(_array(label, np.where(ids >= 0, ids, np.nan).astype(np.float64), deep=False))


def _identify(data_set, data_structure) -> None:
    """Field data: the block's data structure, and its graph's scales (coarser first)."""
    views = _views()
    for name, values in ((views.DATA_STRUCTURE_FIELD, [data_structure.id]),
                         (views.SCALES_FIELD, views.ranked_sets(data_structure))):
        listed = vtkStringArray()
        listed.SetName(name)
        for value in values:
            listed.InsertNextValue(str(value))
        data_set.GetFieldData().AddArray(listed)


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
    _add_ancestors(polydata, data_structure, entity_set.name, rows)
    _identify(polydata, data_structure)
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
    _identify(image, data_structure)
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
    _identify(unstructured, data_structure)
    return unstructured


def _named(blocks: vtkMultiBlockDataSet, data_set, name: str) -> None:
    number = blocks.GetNumberOfBlocks()
    blocks.SetBlock(number, data_set)
    blocks.GetMetaData(number).Set(vtkMultiBlockDataSet.NAME(), name)


TUBE_SIDES = 8


def _tubes(lines):
    """The *lines* (a segments layer's: the first ends, then the second ends) as tubes of radius "tube_radius" (point
    data), one closed triangle strip per line holding its cell data: the layer is drawn as tubes with no Tube filter,
    and picked as such, an entity a cell."""
    count = lines.GetNumberOfCells()
    points = vtk_to_numpy(lines.GetPoints().GetData()).astype(np.float64)
    first, second = points[:count], points[count:]
    radius = vtk_to_numpy(lines.GetPointData().GetArray(_views().TUBE_RADIUS)).astype(np.float64)[:count]
    direction = second - first
    length = np.linalg.norm(direction, axis=1)
    axis = np.where(length[:, None] > 0, direction / np.where(length > 0, length, 1.)[:, None], [0., 0., 1.])
    helper = np.where((np.abs(axis[:, 0]) > 0.9)[:, None], [0., 1., 0.], [1., 0., 0.])
    across = np.cross(axis, helper)
    across /= np.linalg.norm(across, axis=1)[:, None]
    other = np.cross(axis, across)
    angles = 2. * np.pi * np.arange(TUBE_SIDES) / TUBE_SIDES
    normals = np.cos(angles)[None, :, None] * across[:, None, :] + np.sin(angles)[None, :, None] * other[:, None, :]
    rings = np.stack([first[:, None, :] + radius[:, None, None] * normals,
                      second[:, None, :] + radius[:, None, None] * normals], axis=2)    # segment, side, end, xyz
    tubes = vtkPolyData()
    tube_points = vtkPoints()
    tube_points.SetData(numpy_to_vtk(np.ascontiguousarray(rings.reshape(-1, 3)), deep=True))
    tubes.SetPoints(tube_points)
    per_tube = 2 * TUBE_SIDES                                    # around the tube, back to its first side
    corners = np.concatenate([np.arange(per_tube), [0, 1]])
    connectivity = (np.arange(count)[:, None] * per_tube + corners[None, :]).reshape(-1).astype(np.int64)
    strips = vtkCellArray()
    strips.SetData(numpy_to_vtkIdTypeArray(np.arange(0, len(corners) * count + 1, len(corners), dtype=np.int64),
                                           deep=True), numpy_to_vtkIdTypeArray(connectivity, deep=True))
    tubes.SetStrips(strips)
    tubes.GetCellData().ShallowCopy(lines.GetCellData())
    tubes.GetFieldData().ShallowCopy(lines.GetFieldData())
    tubes.GetPointData().AddArray(_array(_views().TUBE_RADIUS, np.repeat(radius, per_tube)))
    point_normals = _array("Normals", np.repeat(normals, 2, axis=1).reshape(-1, 3).astype(np.float32))
    tubes.GetPointData().SetNormals(point_normals)
    return tubes


def _layer(frame, layer: dict, settings: bool = False, derived: bool = False, expand_hidden: bool = False,
           all_arrays: bool = False):
    """The data set of a layer (views.configuration's, its defaults filled): its selected entities only, its colour
    variable as the active scalars; empty when the frame lacks a name it gives (e.g. a mesh drawn from a later frame
    on), so that every frame of a sequence has the same blocks. A hidden instances layer of a frame read from a file
    is left empty unless *expand_hidden* (_unexpanded: "encoding3d Select at scale" builds the part it selects);
    *all_arrays*: an instances layer's every variable (_instances)."""
    views = _views()
    report = views.check_views({"encoding3d_views": views.FORMAT, "configurations": {"layer": {"layers": [layer]}}}, frame)
    if not report.ok:
        empty = vtkPolyData()
        if layer["source"]["kind"] == "instances":        # (named: the filter says the frame has none of them)
            for name, value in ((INSTANCE_SET_FIELD, layer["source"]["instance_set"]),
                                (FRAME_FIELD, getattr(frame, "path", "") or ""),
                                (views.DATA_STRUCTURE_FIELD, layer["source"]["data_structure"])):
                listed = vtkStringArray()
                listed.SetName(name)
                listed.InsertNextValue(str(value))
                empty.GetFieldData().AddArray(listed)
        return empty
    source = layer["source"]
    data_structure = frame.data_structure(source["data_structure"])
    select = layer.get("select")
    chosen = None
    if select:
        table = next((instance_set for instance_set in data_structure.instance_sets
                      if instance_set.name == select["entity_set"]), None) if source["kind"] == "instances" else None
        chosen = (table if table is not None else data_structure.entity_set(select["entity_set"]), select["where"])
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
    elif source["kind"] == "instances":
        instance_set = data_structure.instance_set(source["instance_set"])
        if not layer.get("visible", True) and not expand_hidden and getattr(frame, "path", ""):
            return _unexpanded(frame, data_structure, instance_set, layer, settings, all_arrays)
        rows = _layer_instance_rows(data_structure, instance_set, select)
        data_set = _instances(frame, data_structure, instance_set, settings, rows, forced, derived, all_arrays)
    elif source["kind"] == "segments":
        entity_set = data_structure.entity_set(source["entity_set"])
        rows = np.flatnonzero(views.selected(*chosen)) if chosen is not None else None
        tube = layer.get("tube")
        radius = None
        if tube:                                                         # a missing radius: none (no NaN points)
            radius = np.ma.filled(np.ma.asarray(entity_set.columns[tube["radius"]], dtype=np.float64), np.nan)
            radius = np.nan_to_num(radius * float(tube.get("scale", 1.)), nan=0.)
        data_set = _segments(entity_set, _segment_columns(entity_set), data_structure, settings, rows,
                             forced.get(entity_set.name, ()), radius)
        if tube:
            data_set = _tubes(data_set)
    else:
        kept = views.selected(*chosen) if chosen is not None else None
        build = _regular_grid if data_structure.grid.kind == "regular" else _adaptive_grid
        data_set = build(data_structure, settings, kept, forced.get(data_structure.grid.cells, ()))
    array = views.colour_array(layer, {data_set.GetCellData().GetArrayName(number)
                                       for number in range(data_set.GetCellData().GetNumberOfArrays())})
    if array is not None:
        data_set.GetCellData().SetActiveScalars(array)
    return data_set


def frame_to_vtk(frame, settings: bool = False, views=None, configuration: str = None, derived: bool = False,
                 expand_hidden: bool = False, all_arrays: bool = False) -> vtkMultiBlockDataSet:
    """The frame as a multiblock data set: one block per data structure, holding its meshes, its entity sets with
    segment ends as lines, its grid and its instance sets (their placed templates). *settings*: also the graph's links
    (complex, parent, edge_type) and the columns of role "setting". *derived*: the instances' derived fields
    evaluated (all of them: for small scenes; the Select at scale filter rebuilds those of the instances it holds).

    *all_arrays*: an instance set's every variable, one value per triangle (else the ids, rows and colour variables
    only: see _instances).

    *views* (a views document, or the path of a views.json): instead, one block per layer of the *configuration*
    (None: the active one), named by the layer, hidden layers included (see _layer: a hidden instances layer is left
    empty unless *expand_hidden*)."""
    if views is not None:
        views_module = _views()
        document = views_module.read_views(views) if isinstance(views, (str, os.PathLike)) else views
        report = views_module.check_views(document)
        if not report.ok:
            raise ValueError(str(report))
        output = vtkMultiBlockDataSet()
        for layer in views_module.configuration(document, configuration)[1]:
            _named(output, _layer(frame, layer, settings, derived, expand_hidden, all_arrays), layer["name"])
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
        for instance_set in data_structure.instance_sets:
            _named(blocks, _instances(frame, data_structure, instance_set, settings, derived=derived,
                                      all_arrays=all_arrays), f"instances {instance_set.name}")
        if blocks.GetNumberOfBlocks():
            _named(output, blocks, data_structure.id)
    return output


TIME_UNITS = {"s": 1., "min": 60., "h": 3600., "d": 86400.}    # in seconds: the reader's Time Unit choices

_FRAMES = collections.OrderedDict()     # the frames open, by file: the reader's and the filter's, one read for both
FRAMES_KEPT = 2                         # (the last two used: a time step and the one before, or two files)


def open_frame(path: str):
    """The frame of *path*, read lazily once and shared: by the reader (Source.frame_at) and by "encoding3d Select
    at scale" (the instances it builds, the derived fields it rebuilds); the least recently used closed beyond
    FRAMES_KEPT, its rebuilt derived fields dropped."""
    if path in _FRAMES:
        _FRAMES.move_to_end(path)
        return _FRAMES[path]
    while len(_FRAMES) >= FRAMES_KEPT:
        closed, frame = _FRAMES.popitem(last=False)
        frame.close()
        for key in [key for key in _DERIVED if key[0] == closed]:
            del _DERIVED[key]
    _FRAMES[path] = _encoding3d().read(path, lazy=True)         # lazily: only what is drawn is decoded
    return _FRAMES[path]


class Source:
    """A .glb frame or a scene.fspm.json sequence: its times, and its frame at a time."""

    def __init__(self, path: str):
        self.path = path
        encoding3d = _encoding3d()
        if path.endswith(".json") or path.endswith(".fspm.zip"):           # a sequence, or its archive
            index = encoding3d.read_index(path)
            self.paths = [entry["path"] for entry in index["frames"]]
            self.times = [float(entry["time"]) for entry in index["frames"]]
            self.time_unit = index.get("timeUnit", "d")
        else:
            self.paths = [path]
            with encoding3d.read(path, lazy=True) as frame:         # its time, from the file's JSON alone
                self.times = [float(frame.time)]
                self.time_unit = frame.time_unit

    def factor(self, unit: str) -> float:
        """The factor from the files' time unit to *unit* (one of TIME_UNITS; empty, or a unit of the files not in
        TIME_UNITS: 1, the files' times)."""
        if not unit or unit not in TIME_UNITS or self.time_unit not in TIME_UNITS:
            return 1.
        return TIME_UNITS[self.time_unit] / TIME_UNITS[unit]

    def frame_at(self, time: float = None):
        """The frame of the last time not after *time* (the first frame for None or an earlier time): open_frame's."""
        number = 0
        if time is not None:
            earlier = [n for n, frame_time in enumerate(self.times) if frame_time <= time + 1e-12 * max(1., abs(time))]
            number = earlier[-1] if earlier else 0
        return open_frame(self.paths[number])


# ── Selection by scale ───────────────────────────────────────────────────────

SELECT_AT_SCALE = "encoding3dSelectAtScale"   # the filter's proxy name
SELECTED = "encoding3d_selected"             # the cell array _kept thresholds


def leaves(data) -> list:
    """The data sets of *data*, a data set or a composite one, in its tree's order."""
    if data is None:
        return []
    if not isinstance(data, vtkDataObjectTree):
        return [data]
    iterator = data.NewTreeIterator()
    iterator.VisitOnlyLeavesOn()
    iterator.InitTraversal()
    found = []
    while not iterator.IsDoneWithTraversal():
        found.append(iterator.GetCurrentDataObject())
        iterator.GoToNextItem()
    return found


def _texts(data_set, name: str) -> list:
    array = data_set.GetFieldData().GetAbstractArray(name)
    return [array.GetValue(number) for number in range(array.GetNumberOfValues())] if array is not None else []


def _id_arrays(data_set) -> dict:
    """{"<scale>.id": values} of a data set's cells."""
    cell_data = data_set.GetCellData()
    names = [cell_data.GetArrayName(number) for number in range(cell_data.GetNumberOfArrays())]
    return {name: vtk_to_numpy(cell_data.GetArray(name)) for name in names if name and name.endswith(".id")}


def encoding3d_data(data) -> bool:
    """Whether *data* holds blocks of the encoding3d reader (their data structure in field data)."""
    return any(_texts(leaf, _views().DATA_STRUCTURE_FIELD) for leaf in leaves(data))


def scales_of(data) -> list:
    """The scales of *data*'s blocks (their field data encoding3d_scales), coarser first."""
    return _views().scale_names([_texts(leaf, _views().SCALES_FIELD) for leaf in leaves(data)])


def picked_cells(data, selection) -> list:
    """[(data structure, {"<scale>.id": values})] of the cells of *data* (the reader's output or an item drawn from
    it: an ExtractBlock, a Tube ...) in *selection* (a vtkSelection: ids, a frustum, a query ...), one entry per block
    holding some."""
    if data is None or selection is None or not selection.GetNumberOfNodes():
        return []
    copied, chosen = data.NewInstance(), vtkSelection()
    copied.ShallowCopy(data)
    chosen.ShallowCopy(selection)
    extraction = vtkExtractSelection()
    extraction.PreserveTopologyOn()                         # the same blocks, each cell marked inside or not
    extraction.SetInputData(0, copied)
    extraction.SetInputData(1, chosen)
    extraction.Update()
    marked_data, found = extraction.GetOutputDataObject(0), []
    if isinstance(data, vtkDataObjectTree):                 # each block and its marks (a block without any: none)
        iterator = data.NewTreeIterator()
        iterator.InitTraversal()
        pairs = []
        while not iterator.IsDoneWithTraversal():
            pairs.append((iterator.GetCurrentDataObject(), marked_data.GetDataSet(iterator)))
            iterator.GoToNextItem()
    else:
        pairs = [(data, marked_data)]
    for leaf, marked in pairs:
        inside = marked.GetCellData().GetArray("vtkInsidedness") if marked is not None else None
        data_structure = _texts(leaf, _views().DATA_STRUCTURE_FIELD)
        if inside is None or not data_structure:
            continue
        cells = vtk_to_numpy(inside).astype(bool)
        if cells.any():
            found.append((data_structure[0], {name: values[cells] for name, values in _id_arrays(leaf).items()}))
    return found


def _kept(data_set, chosen: dict, scale: str):
    """The cells of *data_set* inside the entities *chosen* at *scale* (a grid layer's hidden cells included), its
    field data and active scalars kept; polygonal data stays polygonal (a Tube can follow)."""
    views = _views()
    data_structure = (_texts(data_set, views.DATA_STRUCTURE_FIELD) or [""])[0]
    mask = views.selection_mask(data_structure, _id_arrays(data_set), chosen, scale)
    if mask.size != data_set.GetNumberOfCells() or not mask.any():      # a block without id arrays, or none in it
        empty = data_set.NewInstance()
        empty.GetFieldData().ShallowCopy(data_set.GetFieldData())
        return empty
    marked = data_set.NewInstance()
    marked.ShallowCopy(data_set)
    marked.GetCellData().RemoveArray(vtkDataSetAttributes.GhostArrayName())
    marked.GetCellData().AddArray(_array(SELECTED, mask.astype(np.uint8)))
    threshold = vtkThreshold()
    threshold.SetInputData(marked)
    threshold.SetInputArrayToProcess(0, 0, 0, vtkDataObject.FIELD_ASSOCIATION_CELLS, SELECTED)
    threshold.SetThresholdFunction(vtkThreshold.THRESHOLD_UPPER)
    threshold.SetUpperThreshold(0.5)
    threshold.SetLowerThreshold(0.5)
    last = threshold
    if isinstance(data_set, vtkPolyData):
        last = vtkGeometryFilter()
        last.SetInputConnection(threshold.GetOutputPort())
    last.Update()
    output = last.GetOutput()
    output.GetCellData().RemoveArray(SELECTED)
    scalars = data_set.GetCellData().GetScalars()
    if scalars is not None and scalars.GetName():
        output.GetCellData().SetActiveScalars(scalars.GetName())
    output.GetFieldData().ShallowCopy(data_set.GetFieldData())
    return output


def _built(data_set, chosen: dict, scale: str):
    """The part of a hidden instances layer's empty block (_unexpanded) inside the entities *chosen* at *scale*:
    the placed templates of those instances alone, built from the frame (open_frame), drawn as the layer."""
    views = _views()
    empty = data_set.NewInstance()
    empty.GetFieldData().ShallowCopy(data_set.GetFieldData())
    data_structure_id = (_texts(data_set, views.DATA_STRUCTURE_FIELD) or [""])[0]
    path = (_texts(data_set, FRAME_FIELD) or [""])[0]
    if data_structure_id not in chosen or not path:
        return empty
    built = json.loads(_texts(data_set, UNEXPANDED_FIELD)[0])
    layer = built["layer"]
    data_structure = open_frame(path).data_structure(data_structure_id)
    instance_set = data_structure.instance_set(_texts(data_set, INSTANCE_SET_FIELD)[0])
    rows = instance_rows_at(data_structure, instance_set, chosen[data_structure_id], scale)
    kept = _layer_instance_rows(data_structure, instance_set, layer.get("select"))
    if kept is not None:
        rows = np.intersect1d(rows, kept)
    if not rows.size:
        return empty
    colour = layer.get("color_by")
    forced = {colour["entity_set"]: (colour["variable"],)} if colour else {}
    part = _instances(open_frame(path), data_structure, instance_set, built["settings"], rows, forced,
                      all_arrays=built["all_arrays"])
    array = views.colour_array(layer, {part.GetCellData().GetArrayName(number)
                                       for number in range(part.GetCellData().GetNumberOfArrays())})
    if array is not None and part.GetCellData().HasArray(array):
        part.GetCellData().SetActiveScalars(array)
    part.GetFieldData().AddArray(data_set.GetFieldData().GetAbstractArray(UNEXPANDED_FIELD))   # (its layer)
    return part


def _grown(data_set, chosen: dict, scale: str):
    if _texts(data_set, UNEXPANDED_FIELD) and not data_set.GetNumberOfCells():     # a hidden layer's empty block
        return _built(data_set, chosen, scale)
    return _kept(data_set, chosen, scale)


def grow_entities(frame_data, chosen: dict, scale: str) -> vtkMultiBlockDataSet:
    """The cells of *frame_data* (the reader's output: its blocks, a layer's hidden ones included) inside the
    entities *chosen* ({data structure id: ids at *scale*}, views.picked_entities'), with everything they contain at
    finer scales: the same blocks, named alike, each holding its part (empty when none); a hidden instances layer's
    part built from its frame (those instances alone)."""
    output = vtkMultiBlockDataSet()
    if isinstance(frame_data, vtkDataObjectTree):
        output.CopyStructure(frame_data)
        iterator = frame_data.NewTreeIterator()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            output.SetDataSet(iterator, _grown(iterator.GetCurrentDataObject(), chosen, scale))
            iterator.GoToNextItem()
    elif frame_data is not None:
        output.SetBlock(0, _grown(frame_data, chosen, scale))
    return output


def grow_selection(frame_data, picked: list, scale: str) -> vtkMultiBlockDataSet:
    """grow_entities of the entities at *scale* containing the *picked* cells (picked_cells'). A ValueError when no
    picked cell has an entity at *scale*."""
    return grow_entities(frame_data, _views().picked_entities(picked, scale), scale)


def missing_instances(frame_data, grown, chosen: dict, scale: str) -> list:
    """Why the instances blocks of *grown* (grow_entities' of *frame_data*) hold nothing for the entities *chosen* at
    *scale*, one message per block: the frame has no instance in that set (e.g. a platform drawing its sections at
    some time steps only), or none owned by those entities (it draws them for some plants only: the plants which
    have some are named)."""
    views = _views()
    messages = []
    for leaf, part in zip(leaves(frame_data), leaves(grown)):
        names, files = _texts(leaf, INSTANCE_SET_FIELD), _texts(leaf, FRAME_FIELD)
        data_structure_id = (_texts(leaf, views.DATA_STRUCTURE_FIELD) or [""])[0]
        if not names or not files or not files[0] or part is None or part.GetNumberOfCells() \
                or data_structure_id not in chosen:
            continue
        frame = open_frame(files[0])
        wanted = f"the selected {scale} {sorted(chosen[data_structure_id])}"
        when = f"t = {frame.time:g} {frame.time_unit}"
        try:
            data_structure = frame.data_structure(data_structure_id)
            instance_set = data_structure.instance_set(names[0])
        except KeyError:                                # not in this frame (drawn at some time steps only)
            instance_set = None
        if instance_set is None or not instance_set.count:
            messages.append(f"no '{names[0]}' instance drawn for {wanted} at {when}: the frame holds none")
            continue
        coarsest = views.ranked_sets(data_structure)[0] if views.ranked_sets(data_structure) else None
        owner_rows = _owner_rows(data_structure, instance_set)
        holders = []
        if coarsest is not None and instance_set.owners is not None:
            if coarsest == instance_set.owners:
                ids = np.asarray(data_structure.entity_set(coarsest).columns["id"], dtype=np.int64)[
                    owner_rows[owner_rows >= 0]]
            else:
                ids = views.ancestor_ids(data_structure, instance_set.owners, owner_rows).get(coarsest,
                                                                                               np.zeros(0))
            holders = sorted({int(value) for value in np.asarray(ids).tolist() if value >= 0})
        messages.append(f"no '{instance_set.name}' instance drawn for {wanted} at {when}: the frame's "
                        f"{instance_set.count} instances are owned by {coarsest} {holders}" if holders else
                        f"no '{instance_set.name}' instance drawn for {wanted} at {when}: none of the frame's "
                        f"{instance_set.count} instances is inside them")
    return messages


def rebuild_derived(data) -> None:
    """In place: the derived fields of the instances each instances block of *data* holds (a selection's: few
    instances), evaluated from their frame's file (its parts found next to it), once per frame open (open_frame); a
    block without its frame's file, or without cells, unchanged. A hidden layer's part coloured by a derived field
    gets it as its active scalars."""
    for leaf in leaves(data):
        names, files = _texts(leaf, INSTANCE_SET_FIELD), _texts(leaf, FRAME_FIELD)
        data_structure = _texts(leaf, _views().DATA_STRUCTURE_FIELD)
        if not names or not files or not files[0] or not data_structure or not leaf.GetNumberOfCells():
            continue
        frame = open_frame(files[0])
        found = frame.data_structure(data_structure[0])
        _add_derived(leaf, frame, found, found.instance_set(names[0]))
        built = _texts(leaf, UNEXPANDED_FIELD)
        if built:
            array = _views().colour_array(json.loads(built[0])["layer"])
            if array is not None and leaf.GetCellData().HasArray(array):
                leaf.GetCellData().SetActiveScalars(array)


def frame_upstream(algorithm, port: int = 0):
    """The output of the encoding3d reader upstream of *algorithm*'s input *port*, through the items drawn from it (the
    farthest output holding encoding3d blocks): where selection by scale grows, in every layer, the hidden ones included;
    None when there is none."""
    found = None
    while algorithm.GetNumberOfInputPorts() > port and algorithm.GetNumberOfInputConnections(port):
        connection = algorithm.GetInputConnection(port, 0)
        producer = connection.GetProducer()
        data = producer.GetOutputDataObject(connection.GetIndex())
        if encoding3d_data(data):
            found = data
        algorithm, port = producer, 0
    return found


# ── The ParaView reader ──────────────────────────────────────────────────────

try:
    from paraview.util.vtkAlgorithm import VTKPythonAlgorithmBase, smdomain, smhint, smproperty, smproxy
except ImportError:                                  # VTK without ParaView: frame_to_vtk and Source only
    VTKPythonAlgorithmBase = None

def _displays():
    """encoding3d_displays (next to this file): how the reader's representations draw the layers, the buttons' work."""
    import encoding3d_displays
    return encoding3d_displays


def _run(action: str, algorithm, *arguments) -> None:
    """A button's *action* of encoding3d_displays on the item of *algorithm*; what goes wrong, in ParaView's output."""
    try:
        getattr(_displays(), action)(algorithm, *arguments)
    except Exception as error:                        # a button: ParaView's Output Messages, not a crash
        vtkOutputWindow.GetInstance().DisplayWarningText(f"encoding3d: {error}\n")


if VTKPythonAlgorithmBase is not None:
    try:
        _encoding3d()                                   # on ParaView's path now
    except ImportError:
        pass
    if os.path.dirname(os.path.realpath(__file__)) not in sys.path:   # and encoding3d_displays (a link: its folder)
        sys.path.append(os.path.dirname(os.path.realpath(__file__)))
    try:
        _displays().install()                           # the layers drawn on each representation ParaView makes
    except Exception as error:                          # (none in a server without a client: nothing to draw)
        vtkOutputWindow.GetInstance().DisplayWarningText(f"encoding3d: layers not drawn ({error})\n")

    @smproxy.reader(name="encoding3dReader", label="encoding3d reader", extensions="glb json zip",
                    file_description="encoding3d frames (.glb) and sequences (scene.fspm.json, .fspm.zip)")
    class Encoding3dReader(VTKPythonAlgorithmBase):
        def __init__(self):
            VTKPythonAlgorithmBase.__init__(self, nInputPorts=0, nOutputPorts=1, outputType="vtkMultiBlockDataSet")
            self._file_name, self._source, self._settings = None, None, False
            self._views, self._configuration, self._save_as = "", "", ""
            self._time_unit = "d"
            self._derived, self._expand_hidden, self._all_arrays = False, False, False

        @smproperty.stringvector(name="FileName")
        @smdomain.filelist()
        @smhint.filechooser(extensions="glb json zip", file_description="encoding3d frames and sequences")
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

        @smproperty.xml("""<IntVectorProperty name="DerivedFields" label="Evaluate Derived Fields"
                                              command="SetDerivedFields" number_of_elements="1" default_values="0">
                             <BooleanDomain name="bool"/>
                             <Documentation>The derived fields of every instance drawn (e.g. the values on each
                             section's cells; a layer the views hide is drawn with "Expand Hidden Instances"),
                             evaluated at each time step: for small scenes. Unticked, "encoding3d Select at scale"
                             rebuilds those of the instances it selects.</Documentation>
                           </IntVectorProperty>""")
        def SetDerivedFields(self, value):
            if bool(value) != self._derived:
                self._derived = bool(value)
                self.Modified()

        @smproperty.xml("""<IntVectorProperty name="ExpandHiddenInstances" label="Expand Hidden Instances"
                                              command="SetExpandHiddenInstances" number_of_elements="1"
                                              default_values="0">
                             <BooleanDomain name="bool"/>
                             <Documentation>Also draw every instance of the instances layers the views hide (e.g. every
                             root section: millions of triangles in a large frame). Unticked, a hidden instances layer
                             is an empty block, and "encoding3d Select at scale" draws the instances of what it
                             selects.</Documentation>
                           </IntVectorProperty>""")
        def SetExpandHiddenInstances(self, value):
            if bool(value) != self._expand_hidden:
                self._expand_hidden = bool(value)
                self.Modified()

        @smproperty.xml("""<IntVectorProperty name="AllInstanceArrays" label="All Instance Arrays"
                                              command="SetAllInstanceArrays" number_of_elements="1"
                                              default_values="0">
                             <BooleanDomain name="bool"/>
                             <Documentation>Every variable of the instances, of their owners and of their templates
                             as cell data of the instances' triangles (one value per triangle each: several times the
                             memory). Unticked: the ids that selection needs, each cell's instance and template rows,
                             and the layers' colour variables.</Documentation>
                           </IntVectorProperty>""")
        def SetAllInstanceArrays(self, value):
            if bool(value) != self._all_arrays:
                self._all_arrays = bool(value)
                self.Modified()

        @smproperty.stringvector(name="TimeUnit", label="Time Unit", number_of_elements="1", default_values="d")
        @smdomain.xml("""<StringListDomain name="list">
                           <String value="d"/><String value="h"/><String value="min"/><String value="s"/>
                         </StringListDomain>""")
        def SetTimeUnit(self, unit):
            """The unit of the times ParaView shows (the animation toolbar, the time inspector): the frames' times
            (in their file's unit) converted, the files unchanged."""
            if (unit or "") != self._time_unit:
                self._time_unit = unit or ""
                self.Modified()

        def _factor(self):
            source = self._opened()
            return source.factor(self._time_unit) if source is not None else 1.

        @smproperty.stringvector(name="Views", default_values="")
        @smdomain.filelist()
        @smhint.filechooser(extensions="json", file_description="encoding3d views (views.json)")
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

        @smproperty.stringvector(name="SaveAs", label="Save As", number_of_elements="1", default_values="")
        def SetSaveAs(self, name):
            """The configuration "Save Views" writes (empty: the one shown)."""
            self._save_as = name or ""                    # not Modified(): the output does not change

        @smproperty.xml("""<Property name="SaveViews" label="Save Views" command="SaveViews"
                                     panel_widget="command_button">
                             <Documentation>Write each layer's display (visibility, colour variable or solid colour,
                             range, log scale, opacity, representation) into the views file: over the configuration
                             shown, or into the one "Save As" names, made the active one.</Documentation>
                           </Property>""")
        def SaveViews(self):
            _run("save_views", self, self._save_as or None)

        def _opened(self):
            if self._source is None and self._file_name:
                self._source = Source(self._file_name)
            return self._source

        @smproperty.doublevector(name="TimestepValues", information_only="1", si_class="vtkSITimeStepsProperty")
        def GetTimestepValues(self):
            source = self._opened()
            factor = self._factor()
            return [time * factor for time in source.times] if source is not None and len(source.times) > 1 else None

        def RequestInformation(self, request, in_info, out_info):
            try:
                _displays().install()                     # a session made after the plugin was loaded
            except Exception:
                pass
            information = out_info.GetInformationObject(0)
            pipeline = vtkStreamingDemandDrivenPipeline
            information.Remove(pipeline.TIME_STEPS())
            information.Remove(pipeline.TIME_RANGE())
            source = self._opened()
            if source is not None and len(source.times) > 1:
                factor = self._factor()
                for time in source.times:
                    information.Append(pipeline.TIME_STEPS(), time * factor)
                information.Append(pipeline.TIME_RANGE(), source.times[0] * factor)
                information.Append(pipeline.TIME_RANGE(), source.times[-1] * factor)
            return 1

        def RequestData(self, request, in_info, out_info):
            information = out_info.GetInformationObject(0)
            pipeline = vtkStreamingDemandDrivenPipeline
            time = information.Get(pipeline.UPDATE_TIME_STEP()) if information.Has(pipeline.UPDATE_TIME_STEP()) \
                else None
            factor = self._factor()
            frame = self._opened().frame_at(None if time is None else time / factor)
            output = vtkMultiBlockDataSet.GetData(out_info, 0)
            path = self._views_path()
            output.ShallowCopy(frame_to_vtk(frame, settings=self._settings, views=path,
                                            configuration=self._configuration or None, derived=self._derived,
                                            expand_hidden=self._expand_hidden, all_arrays=self._all_arrays))
            if time is not None:
                output.GetInformation().Set(output.DATA_TIME_STEP(), frame.time * factor)
            return 1

    @smproxy.filter(name=SELECT_AT_SCALE, label="encoding3d Select at scale")
    @smhint.xml("""<ShowInMenu category="encoding3d"/>""")
    @smhint.xml("""<InitializationHelper class="vtkSMExtractSelectionProxyInitializationHelper"/>""")
    @smhint.xml("""<Visibility replace_input="0"/>""")
    @smproperty.xml("""<InputProperty name="Selection" command="SetInputConnection" port_index="1">
                         <ProxyGroupDomain name="groups">
                           <Group name="sources"/><Group name="filters"/>
                         </ProxyGroupDomain>
                         <DataTypeDomain name="input_type"><DataType value="vtkSelection"/></DataTypeDomain>
                         <Documentation>The cells picked in the view: ParaView's selection when the filter is made
                         ("Copy Active Selection" to take another).</Documentation>
                         <Hints><SelectionInput/></Hints>
                       </InputProperty>""")
    @smproperty.xml("""<InputProperty name="Input" command="SetInputConnection" port_index="0">
                         <ProxyGroupDomain name="groups">
                           <Group name="sources"/><Group name="filters"/>
                         </ProxyGroupDomain>
                         <DataTypeDomain name="input_type"><DataType value="vtkDataObject"/></DataTypeDomain>
                         <Documentation>The item the cells were picked on: the encoding3d reader, a layer, a selection
                         ...</Documentation>
                       </InputProperty>""")
    class Encoding3dSelectAtScale(VTKPythonAlgorithmBase):
        """The cells picked on its input grown to their entity at Scale (a plant, an axis, an organ, a segment ...;
        "picked", the default: the picked cells' own scale) with everything it contains at finer scales, in every block
        of the encoding3d reader upstream (every layer, the hidden ones included: a segment's section, built from the
        frame for the instances selected). The picked entities are kept across time steps (the plant followed as it
        grows) until the selection changes; Scale re-grows them. A time step at which the selection has no instance
        is reported in the Output Messages (the plants that have some named), once per time step; a derived field
        not rebuilt is an error."""

        def __init__(self):
            VTKPythonAlgorithmBase.__init__(self, nInputPorts=2, nOutputPorts=1, outputType="vtkMultiBlockDataSet")
            self._scale, self._scales = "", []
            self._picked, self._picked_from = [], None
            self._reported = set()

        def FillInputPortInformation(self, port, info):
            if port == 1:
                info.Set(vtkAlgorithm.INPUT_REQUIRED_DATA_TYPE(), "vtkSelection")
                info.Set(vtkAlgorithm.INPUT_IS_OPTIONAL(), 1)
            else:
                info.Set(vtkAlgorithm.INPUT_REQUIRED_DATA_TYPE(), "vtkDataObject")
            return 1

        @smproperty.stringvector(name="ScaleNames", information_only="1")
        def GetScaleNames(self):
            return [_views().PICKED_SCALE] + self._scales if self._scales else []

        @smproperty.xml("""<StringVectorProperty name="Scale" command="SetScale" number_of_elements="1"
                                                 default_values="picked">
                             <StringListDomain name="list">
                               <RequiredProperties>
                                 <Property name="ScaleNames" function="StringInfo"/>
                               </RequiredProperties>
                             </StringListDomain>
                             <Documentation>The scale the picked cells grow to: "picked" (the default) is the picked
                             cells' own scale (a root segment, a section's segment); Plant, Axis ... their plant, axis
                             .... Choose a Scale, then Apply: the buttons below work on the Scale applied, not on one
                             chosen in this drop-down and not yet applied.</Documentation>
                           </StringVectorProperty>""")
        def SetScale(self, name):
            """The scale the picked cells grow to (empty or "picked": the picked cells' own)."""
            if (name or "") != self._scale:
                self._scale = name or ""
                self.Modified()

        @smproperty.xml("""<Property name="Isolate" command="Isolate" panel_widget="command_button">
                             <Documentation>Show the selection alone in the active view, the other items hidden
                             (Put Back shows them again). It shows the Scale applied: choose a Scale, Apply, then
                             Isolate.</Documentation>
                           </Property>""")
        def Isolate(self):
            _run("isolate", self)

        @smproperty.xml("""<Property name="ShowInPanel" label="Show In Panel" command="ShowInPanel"
                                     panel_widget="command_button">
                             <Documentation>Show the selection in a new render view beside the active one, its
                             camera fit to it; the view itself as it was before the filter (the selection Apply drew
                             there hidden; Put Back closes the panel and shows it again). It shows the Scale applied:
                             choose a Scale, Apply, then Show In Panel.</Documentation>
                           </Property>""")
        def ShowInPanel(self):
            _run("show_in_panel", self)

        @smproperty.xml("""<Property name="PutBack" label="Put Back" command="PutBack" panel_widget="command_button">
                             <Documentation>One step back: the last selection isolated or shown in a panel put back,
                             the items it hid shown again, its panel closed.</Documentation>
                           </Property>""")
        def PutBack(self):
            _run("put_back", self)

        def RequestInformation(self, request, in_info, out_info):
            frame_data = frame_upstream(self)
            if frame_data is None:
                frame_data = in_info[0].GetInformationObject(0).Get(vtkDataObject.DATA_OBJECT())
            self._scales = scales_of(frame_data)
            return 1

        def RequestData(self, request, in_info, out_info):
            output = vtkMultiBlockDataSet.GetData(out_info, 0)
            source = in_info[0].GetInformationObject(0).Get(vtkDataObject.DATA_OBJECT())
            selection = vtkSelection.GetData(in_info[1], 0) if in_info[1].GetNumberOfInformationObjects() else None
            frame_data = frame_upstream(self) or source
            self._scales = scales_of(frame_data)
            picked_from = (selection.GetMTime() if selection is not None else None,
                           self.GetInputConnection(0, 0).GetProducer().GetAddressAsString("vtkObject"))
            if picked_from != self._picked_from:              # a new selection: its entities picked at this time,
                self._picked = picked_cells(source, selection)  # then followed through the time steps
                self._picked_from = picked_from
            views = _views()
            scale = self._scale if self._scale not in ("", views.PICKED_SCALE) else \
                (views.picked_scale(self._picked, self._scales) or (self._scales[0] if self._scales else ""))
            if source is not None and source.GetInformation().Has(vtkDataObject.DATA_TIME_STEP()):
                output.GetInformation().Set(vtkDataObject.DATA_TIME_STEP(),
                                            source.GetInformation().Get(vtkDataObject.DATA_TIME_STEP()))
            try:
                chosen = views.picked_entities(self._picked, scale)
            except ValueError as error:                       # nothing picked at that scale: an empty selection
                vtkOutputWindow.GetInstance().DisplayWarningText(f"encoding3d Select at scale: {error}\n")
                empty = vtkMultiBlockDataSet()
                if isinstance(frame_data, vtkDataObjectTree):
                    empty.CopyStructure(frame_data)
                output.ShallowCopy(empty)
                return 1
            try:
                grown = grow_entities(frame_data, chosen, scale)
                rebuild_derived(grown)                        # the selected instances' derived fields
            except Exception as error:                        # e.g. a part missing: said, not hidden in a warning
                raise RuntimeError(f"encoding3d Select at scale: the selection at {scale} not built, its instances' "
                                   f"derived fields not rebuilt ({type(error).__name__}: {error})") from error
            for message in missing_instances(frame_data, grown, chosen, scale):
                if message not in self._reported:             # once per time step
                    self._reported.add(message)
                    vtkOutputWindow.GetInstance().DisplayWarningText(f"encoding3d Select at scale: {message}\n")
            output.ShallowCopy(grown)
            return 1
