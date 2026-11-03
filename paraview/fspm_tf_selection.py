"""
The glue of the macro show_fspm_tf_selection.py: an "fspm-TF Select at scale" item (the plugin's filter: the cells
picked in a view grown to their entity at a scale, in every layer of the reader upstream, hidden ones included) shown
as its layers, each part an item drawn as its layer (the same colour map, solid colour, opacity, representation, a
Tube for segments), and

    "isolate"   in the view, the other items hidden until it is put back;
    "panel"     in a new render view beside it, its camera fit to the selection, the view itself untouched.

Run again, the macro goes back one step: the items it made removed, its panel closed, what it hid shown again. A
selection made on a shown selection's items (picking an axis of the plant shown) is shown over it, and going back
returns to the plant. The view keeps what each step made and hid (its annotation fspm_tf_selection).

The plugin (fspm_tf_reader.py) puts this folder and openalea.fspm_tf on ParaView's path. Which items to hide is
openalea.fspm_tf.views.isolated, tested without ParaView; which cells are selected, the filter's.
"""
import json
import time

STATE = "fspm_tf_selection"           # the view's annotation: [{"selection", "items", "hidden", "panel", ...}]
SUFFIX = " selection"
SELECT_AT_SCALE = "fspmTFSelectAtScale"   # the filter's proxy name (fspm_tf_reader.SELECT_AT_SCALE)


def _views():
    from openalea.fspm_tf import views
    return views


def _simple():
    from paraview import simple
    return simple


def _name_of(item) -> str:
    from paraview import servermanager
    return servermanager.ProxyManager().GetProxyName("sources", item)


def is_selection(item) -> bool:
    """Whether *item* is an "fspm-TF Select at scale" item."""
    return item is not None and item.SMProxy.GetXMLName() == SELECT_AT_SCALE


def upstream(item) -> list:
    """The items *item* is drawn from, nearest first (through each one's Input)."""
    found = []
    while item is not None and "Input" in item.ListProperties():
        item = item.Input[0] if isinstance(item.Input, (list, tuple)) else item.Input
        if item is not None:
            found.append(item)
    return found


def reader_of(item):
    """The fspm-TF reader *item* is drawn from (None: none)."""
    return next((proxy for proxy in [item] + upstream(item) if "ConfigurationNames" in proxy.ListProperties()), None)


def layers_of(reader) -> list:
    """The layers of *reader*'s configuration ([]: a reader without views)."""
    views = _views()
    path = views.views_path(views.property_text(reader.FileName), views.property_text(reader.Views) or None)
    if path is None:
        return []
    return views.configuration(views.read_views(path), views.property_text(reader.Configuration) or None)[1]


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


def _named_views() -> dict:
    """{registration name: view} of the session's views."""
    from paraview import servermanager
    return {name: view for (name, _), view in servermanager.ProxyManager().GetProxiesInGroup("views").items()}


def _view_name(view) -> str:
    return next(name for name, proxy in _named_views().items() if proxy.SMProxy is view.SMProxy)


def _steps(view) -> list:
    proxy = view.SMProxy
    return json.loads(proxy.GetAnnotation(STATE)) if proxy.HasAnnotation(STATE) else []


def _keep_steps(view, steps: list) -> None:
    if steps:
        view.SMProxy.SetAnnotation(STATE, json.dumps(steps))
    elif view.SMProxy.HasAnnotation(STATE):
        view.SMProxy.RemoveAnnotation(STATE)


def shown_steps() -> list:
    """[(view, step)] of every selection shown, the last shown last."""
    found = [(view, step) for view in _named_views().values() for step in _steps(view)]
    return sorted(found, key=lambda pair: pair[1]["order"])


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


def _draw_as_layer(display, layer: dict, arrays: set) -> bool:
    """*display* drawn as *layer* says, for a layer without its item (the views not applied); whether coloured."""
    simple, settings = _simple(), _views().display_settings(layer, arrays)
    display.SetRepresentationType(settings["representation"])
    display.Opacity = settings["opacity"]
    if settings["color_array"]:
        display.ColorArrayName = ["CELLS", settings["color_array"]]
        display.LookupTable = simple.GetColorTransferFunction(settings["color_array"])
        return True
    display.ColorArrayName = ["POINTS", ""]
    display.AmbientColor = display.DiffuseColor = settings["solid_color"]
    return False


def _part(selection, layer: dict, name: str, made: list):
    """The item of *layer*'s part of *selection*: an ExtractBlock of its block, and a Tube for a segments layer."""
    simple, settings = _simple(), _views().display_settings(layer)
    tube = settings["tube"]
    block = simple.ExtractBlock(registrationName=f"{name} block" if tube else name, Input=selection,
                                Selectors=[settings["selector"]])
    made.append(f"{name} block" if tube else name)
    if not tube:
        return block
    item = simple.Tube(registrationName=name, Input=block)
    item.Scalars = ["POINTS", tube["radius_array"]]
    item.VaryRadius = "By Absolute Scalar"
    made.append(name)
    return item


def show_selection(selection, mode: str = "isolate", view=None) -> list:
    """Show the "fspm-TF Select at scale" item *selection* as its layers (mode "isolate" or "panel"); the names of the
    items made. Shown selections it is not drawn from are put back first."""
    simple, views = _simple(), _views()
    if mode not in ("isolate", "panel"):
        raise ValueError(f"MODE: 'isolate' or 'panel', not {mode!r}")
    if not is_selection(selection):
        raise RuntimeError("select an 'fspm-TF Select at scale' item in the Pipeline Browser first (pick cells, then "
                           "Filters > fspm-TF > fspm-TF Select at scale, Apply)")
    view = view or simple.GetActiveViewOrCreate("RenderView")
    above = {_name_of(item) for item in upstream(selection)}
    while shown_steps() and not above & set(shown_steps()[-1][1]["items"]):
        back()                                             # not drawn from the last selection shown: put it back
    reader = reader_of(selection)
    if reader is None:
        raise RuntimeError("this selection is not drawn from an fspm-TF reader")
    depth = 1 + len(shown_steps())
    suffix = SUFFIX if depth == 1 else f"{SUFFIX} {depth}"
    selection.UpdatePipeline(view.ViewTime)
    target = _panel(view) if mode == "panel" else view
    simple.Hide(selection, view)                           # its own display (Apply shows it): its layers instead
    simple.ClearSelection(selection.Input)                 # the picked cells' highlight (the filter keeps a copy)
    made, parts = [], []
    layers = layers_of(reader)
    for layer in layers:
        item = _part(selection, layer, f"{layer['name']}{suffix}", made)
        layer_item = simple.FindSource(layer["name"])
        parts.append((item, simple.GetDisplayProperties(layer_item, view) if layer_item is not None else layer))
    if not layers:                                         # the reader without views: drawn as the reader
        item = simple.PassArrays(registrationName=f"{_name_of(reader)}{suffix}", Input=selection)
        made.append(f"{_name_of(reader)}{suffix}")
        parts.append((item, simple.GetDisplayProperties(reader, view)))
    for item, drawn in parts:
        item.UpdatePipeline(view.ViewTime)
        display = simple.Show(item, target)
        if isinstance(drawn, dict):
            coloured = _draw_as_layer(display, drawn, set(item.CellData.keys()))
        else:
            coloured = _draw_as(display, drawn)
        if coloured and mode == "panel" and item.GetDataInformation().GetNumberOfCells():   # (a layer without any
                                                           # of it shown too, empty: its part may come with another
                                                           # Scale or time step)
            display.SetScalarBarVisibility(target, True)
    hidden, bars = [], []
    if mode == "isolate":
        hidden = views.isolated(_shown(view), made + [_name_of(selection)])
        for name in hidden:
            display = simple.GetDisplayProperties(simple.FindSource(name), view)
            if display.LookupTable is not None and simple.GetScalarBar(display.LookupTable, view).Visibility:
                bars.append(name)
            simple.Hide(simple.FindSource(name), view)
        simple.HideUnusedScalarBars(view)
    else:
        target.ResetCamera()
        simple.Render(target)
    step = {"selection": _name_of(selection), "items": made, "hidden": hidden, "scalar_bars": bars,
            "panel": None if mode == "isolate" else _view_name(target), "order": time.time()}
    _keep_steps(view, _steps(view) + [step])
    simple.SetActiveView(view)
    simple.Render(view)
    print(f"fspm-TF selection shown ({mode}): {_name_of(selection)}, scale {views.property_text(selection.Scale)}")
    return made


def _panel(view):
    """A new render view beside *view*, at its time, its camera to start with."""
    simple = _simple()
    panel = simple.CreateView("RenderView")
    layout = simple.GetLayout(view)
    if layout is None:
        layout = simple.CreateLayout("fspm-TF")
        layout.AssignView(0, view)
    location = layout.GetViewLocation(view)
    layout.SplitHorizontal(location, 0.5)
    layout.AssignView(2 * location + 2, panel)
    panel.ViewSize = list(view.ViewSize)
    panel.CameraPosition, panel.CameraFocalPoint = list(view.CameraPosition), list(view.CameraFocalPoint)
    panel.CameraViewUp = list(view.CameraViewUp)
    panel.ViewTime = view.ViewTime
    return panel


def _consumed(item) -> bool:
    """Whether another pipeline item reads *item* (a selection made on it): then it is kept, hidden."""
    proxy = item.SMProxy
    for number in range(proxy.GetNumberOfConsumers()):
        consumer = proxy.GetConsumerProxy(number)
        if consumer is not None and consumer.GetXMLGroup() in ("sources", "filters"):
            return True
    return False


def back() -> bool:
    """Put back the last selection shown: its items removed (kept hidden when a selection was made on them), its
    panel closed, what it hid shown again; whether there was one."""
    simple = _simple()
    steps = shown_steps()
    if not steps:
        return False
    view, step = steps[-1]
    for name in reversed(step["items"]):                   # a tube before the block it reads
        item = simple.FindSource(name)
        if item is None:
            continue
        if _consumed(item):
            for shown in _named_views().values():
                simple.Hide(item, shown)
        else:
            simple.Delete(item)
    for name in step["hidden"]:
        item = simple.FindSource(name)
        if item is not None:
            display = simple.Show(item, view)
            if name in step.get("scalar_bars", []):
                display.SetScalarBarVisibility(view, True)
    if step["panel"]:
        panel = _named_views().get(step["panel"])
        if panel is not None:
            layout = simple.GetLayout(panel)
            if layout is not None:
                location = layout.GetViewLocation(panel)
                layout.RemoveView(panel)
                if location > 0:
                    layout.Collapse(location)
            simple.Delete(panel)
    _keep_steps(view, [kept for kept in _steps(view) if kept["order"] != step["order"]])
    simple.Render(view)
    print(f"fspm-TF selection put back: {step['selection']}")
    return True


def show_or_back(mode: str = "isolate") -> None:
    """The macro: the active item, an "fspm-TF Select at scale" not shown yet, shown; else the last selection shown
    put back."""
    simple = _simple()
    active = simple.GetActiveSource()
    shown = {step["selection"] for _, step in shown_steps()}
    if is_selection(active) and _name_of(active) not in shown:
        show_selection(active, mode)
    elif not back():
        show_selection(active, mode)                       # nothing to put back: says what to select
