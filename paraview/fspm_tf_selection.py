"""
Selection by scale in ParaView, the glue of the macros select_at_scale.py and clear_fspm_tf_selection.py: the cells
picked in a view (on any fspm-TF item: a layer that "Apply fspm-TF views" made, or the reader) grown to their entity
at a scale (a plant, an axis, an organ, a segment ...) with everything it contains at finer scales, in every layer of
the same reader (hidden ones too: a segment's section), shown

    "isolate"   in the view, the other items hidden until the selection is cleared;
    "panel"     in a new render view beside it, its camera fit to the selection, the view itself untouched.

Each layer's part is an item "<layer> selection" (a Programmable Filter calling extract below), drawn as its layer.
The view keeps what the selection made and hid (its annotation fspm_tf_selection), for clear_selection.

The plugin (fspm_tf_reader.py) puts this folder and openalea.fspm_tf on ParaView's path. What is selected is
openalea.fspm_tf.views' (picked_entities, selection_mask, isolated), tested without ParaView.
"""
import json

import numpy as np
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from vtkmodules.vtkCommonDataModel import vtkDataObject, vtkDataObjectTree, vtkDataSetAttributes
from vtkmodules.vtkFiltersCore import vtkThreshold

STATE = "fspm_tf_selection"           # the view's annotation: {"items", "hidden", "scalar_bars", "panel", ...}
SUFFIX = " selection"
MARK = "fspm_tf_selected"             # the cell array extract thresholds


def _views():
    from openalea.fspm_tf import views
    return views


def _leaves(data):
    """The data sets of *data*, a data set or a composite one."""
    if data is None:
        return []
    if not isinstance(data, vtkDataObjectTree):
        return [data]
    iterator = data.NewTreeIterator()
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
    cell_data = data_set.GetCellData()
    names = [cell_data.GetArrayName(number) for number in range(cell_data.GetNumberOfArrays())]
    return {name: vtk_to_numpy(cell_data.GetArray(name)) for name in names if name and name.endswith(".id")}


# ── On the server: a layer's selected cells ──────────────────────────────────

def _kept(data_set, chosen: dict, scale: str):
    views = _views()
    data_structure = (_texts(data_set, views.DATA_STRUCTURE_FIELD) or [""])[0]
    mask = views.selection_mask(data_structure, _id_arrays(data_set), chosen, scale)
    if mask.size != data_set.GetNumberOfCells():          # a block without id arrays
        mask = np.zeros(data_set.GetNumberOfCells(), dtype=bool)
    marked = data_set.NewInstance()
    marked.ShallowCopy(data_set)
    marked.GetCellData().RemoveArray(vtkDataSetAttributes.GhostArrayName())   # a grid layer's hidden cells
    marked.GetCellData().AddArray(_named(numpy_to_vtk(mask.astype(np.uint8), deep=True), MARK))
    threshold = vtkThreshold()
    threshold.SetInputData(marked)
    threshold.SetInputArrayToProcess(0, 0, 0, vtkDataObject.FIELD_ASSOCIATION_CELLS, MARK)
    threshold.SetThresholdFunction(vtkThreshold.THRESHOLD_UPPER)
    threshold.SetUpperThreshold(0.5)
    threshold.SetLowerThreshold(0.5)
    threshold.Update()
    output = threshold.GetOutput()
    output.GetCellData().RemoveArray(MARK)
    output.GetFieldData().ShallowCopy(data_set.GetFieldData())
    return output


def _named(array, name: str):
    array.SetName(name)
    return array


def extract(algorithm, chosen: dict, scale: str) -> None:
    """A Programmable Filter's RequestData: its input's cells inside the entities *chosen* at *scale*, in each
    block."""
    source, output = algorithm.GetInputDataObject(0, 0), algorithm.GetOutputDataObject(0)
    if isinstance(source, vtkDataObjectTree):
        output.CopyStructure(source)
        iterator = source.NewTreeIterator()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            output.SetDataSet(iterator, _kept(iterator.GetCurrentDataObject(), chosen, scale))
            iterator.GoToNextItem()
    else:
        output.ShallowCopy(_kept(source, chosen, scale))


# ── On the client: the macros ────────────────────────────────────────────────

def _simple():
    from paraview import simple
    return simple


def fspm_tf_items() -> dict:
    """{reader: [(name, item)]} of what shows each fspm-TF reader: its layer items when "Apply fspm-TF views" made
    them, else the reader."""
    simple, views = _simple(), _views()
    found = {}
    for (name, _), item in simple.GetSources().items():
        if not (item.ListProperties() and "ConfigurationNames" in item.ListProperties()):
            continue                                        # not an fspm-TF reader
        path = views.views_path(views.property_text(item.FileName), views.property_text(item.Views) or None)
        layers = []
        if path is not None:
            _, configuration = views.configuration(views.read_views(path),
                                                   views.property_text(item.Configuration) or None)
            layers = [(layer["name"], simple.FindSource(layer["name"])) for layer in configuration]
            layers = [(layer, proxy) for layer, proxy in layers if proxy is not None]
        found[name] = layers or [(name, item)]
    return found


def picked(items: list) -> tuple:
    """[(data structure, {"<scale>.id": values})] of the cells picked on *items* ([(name, item)]), one entry per
    block; and the scales they are in."""
    simple = _simple()
    from paraview import servermanager
    found, scales = [], []
    for _, item in items:
        selection = item.SMProxy.GetSelectionInput(0)
        if selection is None:
            continue
        extraction = simple.ExtractSelection(Input=item, Selection=servermanager._getPyProxy(selection))
        data = servermanager.Fetch(extraction)
        simple.Delete(extraction)
        simple.ClearSelection(item)                       # used: the next pick starts afresh
        for leaf in _leaves(data):
            if leaf.GetNumberOfCells():
                views = _views()
                found.append(((_texts(leaf, views.DATA_STRUCTURE_FIELD) or [""])[0], _id_arrays(leaf)))
                scales += [name for name in _texts(leaf, views.SCALES_FIELD) if name not in scales]
    return found, scales


def _shown(view) -> dict:
    """{item name: visible} of the items drawn in *view* (asking a display of the others would make one)."""
    names = {item.SMProxy: name for (name, _), item in _simple().GetSources().items()}
    found = {}
    for display in view.Representations:
        if "Input" not in display.ListProperties():          # a scalar bar, a widget
            continue
        source = display.Input.SMProxy if display.Input is not None else None
        if source in names:
            found[names[source]] = found.get(names[source], False) or bool(display.Visibility)
    return found


def _state(view) -> dict:
    proxy = view.SMProxy
    return json.loads(proxy.GetAnnotation(STATE)) if proxy.HasAnnotation(STATE) else None


def _draw_as(display, layer_display) -> bool:
    """*display* drawn as *layer_display*: its colouring (the same colour map, its range kept: not ColorBy, which
    rescales it to the selection's values), solid colour, opacity, representation; whether it is coloured."""
    array = list(layer_display.ColorArrayName) if layer_display.ColorArrayName else []
    coloured = len(array) == 2 and bool(array[1])
    if coloured:
        display.ColorArrayName = array
        display.LookupTable = layer_display.LookupTable
    else:
        display.ColorArrayName = ["POINTS", ""]
        display.DiffuseColor = list(layer_display.DiffuseColor)
        display.AmbientColor = list(layer_display.AmbientColor)
    display.Opacity = float(layer_display.Opacity)
    display.SetRepresentationType(_views().property_text(layer_display.Representation))
    return coloured


def select_at_scale(scale: str, mode: str = "isolate", view=None) -> list:
    """Grow the picked cells to their entities at *scale* and show them (mode "isolate" or "panel"); the names of
    the selection's items. A previous selection is cleared first."""
    simple, views = _simple(), _views()
    if mode not in ("isolate", "panel"):
        raise ValueError(f"MODE: 'isolate' or 'panel', not {mode!r}")
    view = view or simple.GetActiveViewOrCreate("RenderView")
    readers = fspm_tf_items()
    previous = _state(view) or {}
    cells, scales, items = [], [], []
    for reader, shown in readers.items():           # the readers picked on (a selection's items: its readers)
        made = [(name, simple.FindSource(f"{name}{SUFFIX}")) for name, _ in shown
                if f"{name}{SUFFIX}" in previous.get("items", [])]
        found, its_scales = picked(shown + [(name, item) for name, item in made if item is not None])
        if found:
            cells += found
            scales += [name for name in its_scales if name not in scales]
            items += shown
    if scales and scale not in scales:
        raise ValueError(f"SCALE '{scale}' is not a scale of the picked elements: {scales}")
    chosen = views.picked_entities(cells, scale)
    clear_selection()
    target = view
    if mode == "panel":
        target = simple.CreateView("RenderView")
        layout = simple.GetLayout(view)
        if layout is None:
            layout = simple.CreateLayout("fspm-TF")
            layout.AssignView(0, view)
        location = layout.GetViewLocation(view)
        layout.SplitHorizontal(location, 0.5)
        layout.AssignView(2 * location + 2, target)
        target.ViewSize = list(view.ViewSize)
        target.CameraPosition, target.CameraFocalPoint = list(view.CameraPosition), list(view.CameraFocalPoint)
        target.CameraViewUp = list(view.CameraViewUp)
        target.ViewTime = view.ViewTime
    made = []
    for name, item in items:
        layer_display = simple.GetDisplayProperties(item, view)
        part = simple.ProgrammableFilter(registrationName=f"{name}{SUFFIX}", Input=item)
        part.OutputDataSetType = "Same as Input"
        part.Script = f"import fspm_tf_selection\nfspm_tf_selection.extract(self, {chosen!r}, {scale!r})"
        part.UpdatePipeline()
        display = simple.Show(part, target)
        coloured = _draw_as(display, layer_display)
        if not part.GetDataInformation().GetNumberOfCells():
            simple.Hide(part, target)                         # nothing of the selection in this layer
        elif coloured and mode == "panel":
            display.SetScalarBarVisibility(target, True)
        made.append(f"{name}{SUFFIX}")
    hidden, bars = [], []
    if mode == "isolate":
        hidden = views.isolated(_shown(view), made)
        for name in hidden:
            display = simple.GetDisplayProperties(simple.FindSource(name), view)
            if display.LookupTable is not None and simple.GetScalarBar(display.LookupTable, view).Visibility:
                bars.append(name)
            simple.Hide(simple.FindSource(name), view)
        simple.HideUnusedScalarBars(view)
    else:
        target.ResetCamera()
        simple.Render(target)
    state = {"items": made, "hidden": hidden, "scalar_bars": bars, "scale": scale, "chosen": chosen,
             "panel": None if mode == "isolate" else _view_name(target)}
    view.SMProxy.SetAnnotation(STATE, json.dumps(state))
    simple.SetActiveView(view)
    simple.Render(view)
    print(f"fspm-TF selection at {scale}: {chosen} ({mode})")
    return made


def _named_views() -> dict:
    """{registration name: view} of the session's views."""
    from paraview import servermanager
    return {name: view for (name, _), view in servermanager.ProxyManager().GetProxiesInGroup("views").items()}


def _view_name(view) -> str:
    return next(name for name, proxy in _named_views().items() if proxy.SMProxy is view.SMProxy)


def clear_selection() -> None:
    """Remove the selection's items and panel, and show again what it hid, in every view holding one."""
    simple = _simple()
    for view in _named_views().values():
        state = _state(view)
        if state is None:
            continue
        for name in state["items"]:
            item = simple.FindSource(name)
            if item is not None:
                simple.Delete(item)
        for name in state["hidden"]:
            item = simple.FindSource(name)
            if item is not None:
                display = simple.Show(item, view)
                if name in state.get("scalar_bars", []):
                    display.SetScalarBarVisibility(view, True)
        if state["panel"]:
            panel = _named_views().get(state["panel"])
            if panel is not None:
                layout = simple.GetLayout(panel)
                if layout is not None:
                    location = layout.GetViewLocation(panel)
                    layout.RemoveView(panel)
                    if location > 0:
                        layout.Collapse(location)
                simple.Delete(panel)
        view.SMProxy.RemoveAnnotation(STATE)
        simple.Render(view)
