"""
Frame views (specification §8.1): views.json, an optional companion of a sequence or a frame, names configurations of
layers; each layer is a part of a data structure (a mesh, segments or a grid), the entities it selects and how it is
drawn::

    {"fspm_tf_views": 1, "active": "default",
     "configurations": {"default": {"layers": [
       {"name": "roots", "source": {"data_structure": "plants", "kind": "segments", "entity_set": "SubOrgan"},
        "select": {"entity_set": "SubOrgan", "where": {"label": ["RootSegment"], "length": ">0"}},
        "color_by": {"entity_set": "SubOrgan", "variable": "water_potential"}, "colormap": "Viridis (matplotlib)",
        "range": "auto", "log": false, "opacity": 1, "visible": true, "representation": "Surface",
        "tube": {"radius": "radius", "scale": 1}}]}}}

    read_views(path), write_views(path, views)
    views_path(path, views=None)         the views file of a frame or sequence: *views*, else the sibling views.json
    check_views(views, frame=None)       a Report: the schema, and every name against *frame*
    configuration(views, name=None)      (its name, its layers, each with its defaults filled)
    selected(table, where)               the rows of *table* where every condition holds

ParaView's macros (paraview/apply_fspm_tf_views.py, save_fspm_tf_views.py) go through display_settings(layer) (a
layer to its display options) and layer_from_display(layer, display) (back, to save them), plain dicts both ways.
"""
import copy
import json
import os
import re

import jsonschema
import numpy as np

from openalea.fspm_tf import schema as schemas

VIEWS_FILE = "views.json"
FORMAT = 1
DEFAULTS = {"color_by": None, "solid_color": [1., 1., 1.], "colormap": "Viridis (matplotlib)", "range": "auto",
            "log": False, "opacity": 1., "visible": True, "representation": "Surface"}
TUBE_RADIUS = "tube_radius"           # the point data a segments layer's Tube varies its radius by
SEGMENT_ENDS = (("proximal_end_x", "x1"), ("proximal_end_y", "y1"), ("proximal_end_z", "z1"),
                ("distal_end_x", "x2"), ("distal_end_y", "y2"), ("distal_end_z", "z2"))

_CONDITION = re.compile(r"^\s*(<=|>=|==|!=|<|>)\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*$")
_COMPARISONS = {"<": np.less, "<=": np.less_equal, ">": np.greater, ">=": np.greater_equal, "==": np.equal,
                "!=": np.not_equal}


# ── Files ────────────────────────────────────────────────────────────────

def views_path(path: str, views: str = None) -> str:
    """The views file of the frame or sequence *path*: *views* when given (relative to *path*'s folder), else the
    views.json next to it; None when that file does not exist."""
    folder = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
    found = os.path.join(folder, views) if views else os.path.join(folder, VIEWS_FILE)
    return found if os.path.exists(found) else None


def read_views(path: str) -> dict:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def write_views(path: str, views: dict) -> None:
    """Write *views* to *path* (checked against the schema first)."""
    report = check_views(views)
    if not report.ok:
        raise ValueError(str(report))
    temporary = path + ".part"
    with open(temporary, "w", encoding="utf-8", newline="\n") as file:
        json.dump(views, file, indent=1)
        file.write("\n")
    os.replace(temporary, path)                         # a reader never sees half a file


def configuration_names(views: dict) -> list:
    """The configurations' names, the active one first."""
    names = list(views.get("configurations", {}))
    active = views.get("active")
    return ([active] if active in names else []) + [name for name in names if name != active]


def configuration(views: dict, name: str = None) -> tuple:
    """(name, layers) of the configuration *name* (None: the active one, else the first), each layer with its
    defaults filled."""
    names = configuration_names(views)
    if not names:
        raise ValueError("the views have no configuration")
    name = name or names[0]
    if name not in views["configurations"]:
        raise KeyError(f"no configuration '{name}' in the views (configurations: {names})")
    return name, [filled(layer) for layer in views["configurations"][name]["layers"]]


def filled(layer: dict) -> dict:
    """*layer* with the defaults of what it leaves out (a tube's scale: 1)."""
    complete = dict(copy.deepcopy(DEFAULTS), **copy.deepcopy(layer))
    if "tube" in complete:
        complete["tube"].setdefault("scale", 1.)
    return complete


# ── Checks ───────────────────────────────────────────────────────────────

def check_views(views: dict, frame=None):
    """A validate.Report of *views*: the schema, an active configuration that exists, unique layer names, and with
    *frame* every name a layer gives (data structure, mesh, entity sets, columns) found in it."""
    from openalea.fspm_tf.validate import Report
    report = Report("views")
    for error in jsonschema.Draft202012Validator(schemas.load("views")).iter_errors(views):
        report.error(f"views/{'/'.join(str(part) for part in error.absolute_path)}", error.message)
    if not report.ok:
        return report
    if "active" in views and views["active"] not in views["configurations"]:
        report.error("views/active", f"no configuration '{views['active']}'")
    for name, content in views["configurations"].items():
        seen = set()
        for number, layer in enumerate(content["layers"]):
            where = f"{name}/layers/{number} ({layer['name']})"
            if layer["name"] in seen:
                report.error(where, "another layer of the configuration has this name")
            seen.add(layer["name"])
            if frame is not None:
                _check_layer(layer, frame, where, report)
    return report


def segment_columns(entity_set) -> list:
    """The six segment-end columns of *entity_set* (by standard name, else x1 ... z2), or [] when it has none."""
    by_standard = {variable.standard_name: name for name, variable in entity_set.variables.items()
                   if variable.standard_name}
    found = []
    for standard, plain in SEGMENT_ENDS:
        name = by_standard.get(standard, plain)
        column = entity_set.columns.get(name)
        if column is None or column.dtype == object or column.dtype.kind not in "fiu":
            return []
        found.append(name)
    return found


def _sets_of(data_structure, layer: dict, where: str, report) -> tuple:
    """(the entity sets the layer may select and colour by, the name of the set its entities are in), or None."""
    source = layer["source"]
    sets = {entity_set.name: entity_set for entity_set in data_structure.entity_sets}
    if source["kind"] == "mesh":
        meshes = {mesh.name: mesh for mesh in data_structure.meshes}
        if source["mesh"] not in meshes:
            report.error(where, f"no mesh '{source['mesh']}' in '{data_structure.id}' (meshes: {sorted(meshes)})")
            return None
        return {name: sets[name] for name in meshes[source["mesh"]].feature_rows if name in sets}, None
    if source["kind"] == "segments":
        entity_set = sets.get(source["entity_set"])
        if entity_set is None:
            report.error(where, f"no entity set '{source['entity_set']}' in '{data_structure.id}'")
            return None
        if not segment_columns(entity_set):
            report.error(where, f"'{entity_set.name}' has no segment ends (proximal_end_x ... distal_end_z, or x1 ... "
                                "z2)")
            return None
        return {entity_set.name: entity_set}, entity_set.name
    if data_structure.grid is None:
        report.error(where, f"'{data_structure.id}' has no grid")
        return None
    return {data_structure.grid.cells: sets[data_structure.grid.cells]}, data_structure.grid.cells


def _check_layer(layer: dict, frame, where: str, report) -> None:
    source = layer["source"]
    found = {data_structure.id: data_structure for data_structure in frame.data_structures}
    data_structure = found.get(source["data_structure"])
    if data_structure is None:
        report.error(where, f"no data structure '{source['data_structure']}' in the frame (data structures: "
                            f"{sorted(found)})")
        return
    usable = _sets_of(data_structure, layer, where, report)
    if usable is None:
        return
    sets, _ = usable
    for part, columns in (("select", list(layer.get("select", {}).get("where", {}))),
                          ("color_by", [(layer.get("color_by") or {}).get("variable")]),
                          ("tube", [layer.get("tube", {}).get("radius")])):
        names = [column for column in columns if column]
        if not names:
            continue
        set_name = (layer[part].get("entity_set") if part != "tube" else source.get("entity_set"))
        if set_name not in sets:
            report.error(f"{where}/{part}", f"'{set_name}' is not an entity set this layer's entities are in "
                                            f"({sorted(sets)})")
            continue
        for column in names:
            if column not in sets[set_name].columns:
                report.error(f"{where}/{part}", f"no column '{column}' in '{data_structure.id}/{set_name}'")
    if layer.get("tube") is not None and source["kind"] != "segments":
        report.error(f"{where}/tube", "a tube is for segments")


# ── Selection ────────────────────────────────────────────────────────────

def _holds(column: np.ndarray, condition) -> np.ndarray:
    missing = np.ma.getmaskarray(column) if np.ma.isMaskedArray(column) else np.zeros(len(column), dtype=bool)
    values = np.ma.getdata(column)
    comparison = _CONDITION.match(condition) if isinstance(condition, str) else None
    if comparison is not None and values.dtype != object:
        operator, threshold = comparison.group(1), float(comparison.group(2))
        with np.errstate(invalid="ignore"):
            result = _COMPARISONS[operator](values.astype(np.float64), threshold)
    elif isinstance(condition, (list, tuple)):
        result = np.isin(values, np.asarray(condition, dtype=object if values.dtype == object else None))
    else:
        result = values == condition
    return np.asarray(result, dtype=bool) & ~missing


def selected(table, where: dict) -> np.ndarray:
    """The rows of *table* (an entity set) where every {column: condition} of *where* holds: a condition is a value,
    a list of values (labels and other text by name), or a comparison (">=0", "!=2"); a missing value never holds."""
    result = np.ones(table.count, dtype=bool)
    for column, condition in where.items():
        result &= _holds(table.columns[column], condition)
    return result


# ── Display options (ParaView's macros) ──────────────────────────────────

def block_selector(name: str) -> str:
    """The selector of the reader's block *name* in ParaView's ExtractBlock: /Root/ and the name as ParaView makes it a
    valid node name (vtkDataAssembly::MakeValidNodeName: characters other than letters, digits, '_', '-' and '.'
    replaced by '_', and '_' before a first character that is not a letter or '_')."""
    valid = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
    if not re.match(r"[A-Za-z_]", valid):
        valid = "_" + valid
    return f"/Root/{valid}"


def colour_array(layer: dict, arrays=()) -> str:
    """The cell data array a layer is coloured by: "<entity set>.<variable>", or its codes "<entity set>.<variable>
    _code" when *arrays* (the block's arrays) hold those instead (a text variable); None for a solid colour."""
    colour = layer.get("color_by")
    if not colour:
        return None
    name = f"{colour['entity_set']}.{colour['variable']}"
    if arrays and name not in arrays and f"{name}_code" in arrays:
        return f"{name}_code"
    return name


def display_settings(layer: dict, arrays=()) -> dict:
    """What ParaView's "Apply fspm-TF views" does for *layer*: the block to extract (selector), a Tube on
    TUBE_RADIUS or not, the colouring (a cell array, its colour map, its range: None for the data's), the solid
    colour, the opacity, the visibility and the representation."""
    layer = filled(layer)
    return {"name": layer["name"], "selector": block_selector(layer["name"]),
            "tube": {"radius_array": TUBE_RADIUS} if layer.get("tube") else None,
            "color_array": colour_array(layer, arrays), "colormap": layer["colormap"],
            "range": None if layer["range"] == "auto" else [float(value) for value in layer["range"]],
            "log": bool(layer["log"]), "solid_color": [float(value) for value in layer["solid_color"]],
            "opacity": float(layer["opacity"]), "visible": bool(layer["visible"]),
            "representation": layer["representation"]}


def layer_from_display(layer: dict, display: dict) -> dict:
    """*layer* updated from a ParaView item's display options, as "Save fspm-TF views" reads them: visible,
    opacity, representation, color_array (None: a solid colour), solid_color, range (None: the data's), log and
    colormap, each optional (absent: the layer's own). A "<entity set>.<variable>_code" array is the variable."""
    updated = copy.deepcopy(layer)
    for key in ("visible", "opacity", "representation", "solid_color", "log", "colormap"):
        if display.get(key) is not None:
            updated[key] = display[key]
    if "opacity" in updated:
        updated["opacity"] = float(updated["opacity"])
    if "range" in display:
        updated["range"] = "auto" if display["range"] is None else [float(value) for value in display["range"]]
    if "color_array" in display:
        array = display["color_array"]
        if not array:
            updated["color_by"] = None
        else:
            entity_set, _, variable = array.partition(".")
            previous = layer.get("color_by") or {}
            if variable.endswith("_code") and previous.get("variable") != variable:
                variable = variable[:-len("_code")]
            updated["color_by"] = {"entity_set": entity_set, "variable": variable}
    return updated


def save_configuration(views: dict, name: str, layers: list, active: bool = True) -> dict:
    """A copy of *views* with configuration *name* set to *layers* (overwritten, or added), made active when
    *active*."""
    saved = copy.deepcopy(views)
    saved.setdefault("fspm_tf_views", FORMAT)
    saved.setdefault("configurations", {})[name] = {"layers": copy.deepcopy(list(layers))}
    if active:
        saved["active"] = name
    return saved
