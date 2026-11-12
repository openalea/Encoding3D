"""
How encoding3d's ParaView plugin (plugin_encoding3d.py, which loads this file) draws the views' layers and runs its
buttons, in ParaView's client:

    install()               watch the session: each representation ParaView makes of an encoding3d reader with views,
                            or of an "encoding3d Select at scale" drawn from one (Apply, Show, a new view), is drawn
                            as the layers of the reader's configuration, each layer a block with its own colour
                            variable, colour map, range, log scale or solid colour, opacity and visibility; drawn
                            again when the reader's Configuration or its views file changes; each colour legend
                            titled "<array> [<unit>]" when the array holds its variable's unit (the reader puts it
                            in vtkDataArray.UNITS_LABEL), those of the arrays the user colours by too
    save_views(reader)      the reader's "Save Views": the layers' display, as the representation in the active view
                            holds it (after edits in the MultiBlock Inspector), written back into the views file
    isolate(selection)      the "Select at scale" buttons: the selection alone in the active view, the other items
    show_in_panel(...)      hidden; or in a new render view beside it, its camera fit to it, the active view as it was
    put_back()              before the filter (the selection Apply drew there hidden); put_back goes back one step
                            (what a step hid shown again, its panel closed). A selection made on a shown selection (an
                            axis of the plant shown) is shown over it, and going back returns to the plant

What each layer gives is openalea.encoding3d.views.block_displays, read back by displays_from_blocks and
layer_from_display, tested without ParaView; this file only hands them to ParaView's server manager. The buttons run
where the reader runs: in ParaView's built-in server (a remote server has no client to draw in).
"""
import contextlib
import json
import os
import time

READER = "encoding3dReader"                 # the plugin's proxy names
SELECT_AT_SCALE = "encoding3dSelectAtScale"
DRAWN = "encoding3d_layers"                 # a representation's annotation: the views and the arrays it is drawn from
STATE = "encoding3d_selection"              # a view's annotation: [{"selection", "hidden", "panel", ...}]
CELLS = 1                                   # vtkDataObject.CELL, FIELD_ASSOCIATION_CELLS
NEVER, GROW_ON_APPLY = -1, 0                # a colour map's AutomaticRescaleRangeMode (vtkSMTransferFunctionManager)

_session = {"managers": {}, "watched": set(), "legends": set(), "busy": False,
            "connections": False}                   # kept across plugin reloads


def _views():
    from openalea.encoding3d import views
    return views


def _server_manager():
    from paraview.modules import vtkRemotingServerManager
    return vtkRemotingServerManager


def _colour_maps():
    from paraview.modules import vtkRemotingViews
    return vtkRemotingViews


def _proxy_manager():
    """The active session's proxy manager (None: no session, e.g. a server without a client)."""
    manager = _server_manager().vtkSMProxyManager
    if not manager.IsInitialized():
        return None
    return manager.GetProxyManager().GetActiveSessionProxyManager()


def _proxies(group: str) -> list:
    proxy_manager = _proxy_manager()
    if proxy_manager is None:
        return []
    iterator = _server_manager().vtkSMProxyIterator()
    iterator.SetSessionProxyManager(proxy_manager)
    iterator.SetModeToOneGroup()
    found, seen = [], set()
    iterator.Begin(group)
    while not iterator.IsAtEnd():
        proxy = iterator.GetProxy()
        if proxy is not None and proxy.GetGlobalID() not in seen:
            seen.add(proxy.GetGlobalID())
            found.append(proxy)
        iterator.Next()
    return found


def _helper(proxy, name: str):
    return _server_manager().vtkSMPropertyHelper(proxy, name)


def _text(proxy, name: str) -> str:
    helper = _helper(proxy, name)
    return (helper.GetAsString(0) or "") if helper.GetNumberOfElements() else ""


def _strings(proxy, name: str) -> list:
    helper = _helper(proxy, name)
    return [helper.GetAsString(number) for number in range(helper.GetNumberOfElements())]


def _set_strings(proxy, name: str, values: list) -> None:
    helper = _helper(proxy, name)
    helper.SetNumberOfElements(len(values))
    for number, value in enumerate(values):
        helper.Set(number, str(value))


def _represented(view) -> list:
    helper = _helper(view, "Representations")
    return [helper.GetAsProxy(number) for number in range(helper.GetNumberOfElements())]


# ── Watching the session ─────────────────────────────────────────────────────

def install() -> None:
    """Watch the active session (once per session): its representations drawn as layers (see the module's doc)."""
    if not _session["connections"]:                 # a session made later (Edit > Reset Session, Connect)
        from paraview.modules.vtkRemotingCore import vtkProcessModule
        process = vtkProcessModule.GetProcessModule()
        if process is not None:
            process.AddObserver("ConnectionCreatedEvent", lambda *arguments: install())
            _session["connections"] = True
    proxy_manager = _proxy_manager()
    if proxy_manager is None:
        return
    key = proxy_manager.GetAddressAsString("vtkObject")
    if key in _session["managers"]:
        return
    tag = proxy_manager.AddObserver("RegisterEvent", _registered)
    _session["managers"][key] = (proxy_manager, tag)  # kept: its address not reused by a later session's
    _registered()


def _registered(*arguments) -> None:
    """A proxy registered: watch the plugin's new items, draw the new representations of them."""
    if _session["busy"]:
        return
    _session["busy"] = True
    try:
        for proxy in _proxies("sources"):
            if proxy.GetXMLName() in (READER, SELECT_AT_SCALE) and proxy.GetGlobalID() not in _session["watched"]:
                proxy.AddObserver("UpdateDataEvent", _updated)
                _session["watched"].add(proxy.GetGlobalID())
        for representation in _proxies("representations"):
            if not representation.HasAnnotation(DRAWN) and _drawable(representation):
                draw(representation)
        for legend in _proxies("scalar_bars"):           # (ParaView's own legends too: the user's colourings)
            if legend.GetGlobalID() not in _session.setdefault("legends", set()):
                _watch_legend(legend)
    except Exception as error:
        _warn(f"layers not drawn ({error})")
    finally:
        _session["busy"] = False


def _updated(source, event=None) -> None:
    """The plugin's item updated (a time step, another Configuration, the views file changed): its representations
    drawn again when their views changed, or the cell arrays their data holds (a layer empty at one time step and
    filled at the next, a selection without the shoot)."""
    if _session["busy"]:
        return
    _session["busy"] = True
    try:
        reader = reader_of(source)
        if reader is not None:
            for representation in representations_of(source):
                if _annotation(representation) != _drawn_signature(representation, reader):
                    draw(representation)
    except Exception as error:
        _warn(f"layers not drawn ({error})")
    finally:
        _session["busy"] = False


@contextlib.contextmanager
def _quiet():
    """VTK's warnings off (ParaView would show them in its Output Messages)."""
    from vtkmodules.vtkCommonCore import vtkObject
    shown = vtkObject.GetGlobalWarningDisplay()
    vtkObject.GlobalWarningDisplayOff()
    try:
        yield
    finally:
        vtkObject.SetGlobalWarningDisplay(shown)


def _warn(message: str) -> None:
    from vtkmodules.vtkCommonCore import vtkOutputWindow
    vtkOutputWindow.GetInstance().DisplayWarningText(f"encoding3d: {message}\n")


def _annotation(proxy) -> str:
    return proxy.GetAnnotation(DRAWN) if proxy.HasAnnotation(DRAWN) else None


def _input(proxy):
    """The proxy feeding *proxy*'s Input (None: none)."""
    if proxy is None or proxy.GetProperty("Input") is None:
        return None
    helper = _helper(proxy, "Input")
    return helper.GetAsProxy(0) if helper.GetNumberOfElements() else None


def _drawable(representation) -> bool:
    source = _input(representation)
    return (representation.GetProperty("BlockColorArrayNames") is not None and source is not None
            and source.GetXMLName() in (READER, SELECT_AT_SCALE))


def reader_of(proxy):
    """The encoding3d reader *proxy* is (or is drawn from, through each item's Input); None: none."""
    while proxy is not None:
        if proxy.GetXMLName() == READER:
            return proxy
        proxy = _input(proxy)
    return None


def representations_of(source) -> list:
    """The representations (render views') of *source*."""
    found = []
    for number in range(source.GetNumberOfConsumers()):
        consumer = source.GetConsumerProxy(number)
        if (consumer is not None and consumer.GetXMLGroup() == "representations"
                and consumer.GetProperty("BlockColorArrayNames") is not None and _input(consumer) is source
                and consumer not in found):
            found.append(consumer)
    return found


def _reader_views(reader) -> tuple:
    """(views file path or None, configuration name, layers) of *reader*."""
    views = _views()
    path = views.views_path(_text(reader, "FileName"), _text(reader, "Views") or None)
    if path is None:
        return None, None, []
    name, layers = views.configuration(views.read_views(path), _text(reader, "Configuration") or None)
    return path, name, layers


def _modified(path: str) -> float:
    """When the views file *path* last changed (one inside a .fspm.zip archive: the archive's)."""
    _views()
    from openalea.encoding3d import archive
    inside = archive.split(path)
    return os.path.getmtime(inside[0] if inside is not None else path)


def _signature(reader) -> str:
    path, name, _ = _reader_views(reader)
    return json.dumps([path, name, _modified(path) if path else None])


def _port(representation) -> int:
    connection = _helper(representation, "Input")
    return connection.GetOutputPort(0) if connection.GetNumberOfElements() else 0


def _drawn_signature(representation, reader) -> str:
    """What *representation* is drawn from: its reader's views (_signature) and the cell arrays of its data."""
    return json.dumps([_signature(reader), sorted(_cell_arrays(_input(representation), _port(representation)))])


def _cell_arrays(source, port: int = 0) -> set:
    information = source.GetDataInformation(port).GetAttributeInformation(CELLS)
    return {information.GetArrayInformation(number).GetName() for number in range(information.GetNumberOfArrays())}


# ── The layers drawn ─────────────────────────────────────────────────────────

def _colour_map(array: str):
    """The colour map (lookup table proxy) ParaView shares among the items coloured by *array*."""
    manager = _colour_maps().vtkSMTransferFunctionManager()
    return manager.GetColorTransferFunction(array, _proxy_manager())


def _apply_preset(colour_map, colormap: str) -> None:
    presets = _colour_maps().vtkSMTransferFunctionPresets.GetInstance()
    for name in _views().preset_names(colormap):
        if presets.HasPreset(name):
            colour_map.ApplyPreset(name, True)
            return
    _warn(f"no colour map preset '{colormap}' in this ParaView, its default kept")


def draw(representation, rescale: bool = None) -> bool:
    """*representation* (of an encoding3d reader with views, or of a selection drawn from one) drawn as the layers of
    the reader's configuration, each layer its block; whether it was. A colour map following the data is fitted to it
    (not for a selection, unless *rescale*: the scene's range kept)."""
    source = _input(representation)
    reader = reader_of(source)
    if reader is None:
        return False
    path, _, layers = _reader_views(reader)
    representation.SetAnnotation(DRAWN, _drawn_signature(representation, reader))
    if path is None:                                    # no views: ParaView's own display
        return False
    if source.GetXMLName() == SELECT_AT_SCALE:          # a selection: every layer's part, the hidden ones too (a
        layers = [dict(layer, visible=True) for layer in layers]   # segment's section)
    views = _views()
    port = _port(representation)
    present = _cell_arrays(source, port)
    displays = views.block_displays(layers, present)    # (coloured by arrays present only: no "Could not determine
    #                                                     array range" for a layer missing at this time step)
    for key in ("colourings", "solid_colours", "opacities"):  # by selector, as ParaView's block editors keep them
        displays[key] = sorted(displays[key])            # (BlockLookupTables follows BlockColorArrayNames' order)
    colour_maps = {array: _colour_map(array) for array in displays["colour_maps"]}
    _set_strings(representation, "BlockSelectors", displays["selectors"])
    if displays["main_array"]:                          # the representation coloured: then its blocks can be
        _helper(representation, "ColorArrayName").SetInputArrayToProcess(CELLS, displays["main_array"])
        _helper(representation, "LookupTable").Set(colour_maps[displays["main_array"]])
    else:                                               # no layer's array in the data: not coloured by a missing one
        _helper(representation, "ColorArrayName").SetInputArrayToProcess(CELLS, "")
    _set_strings(representation, "BlockColorArrayNames",     # (set as properties, not by the colour map helper:
                 [value for selector, array in displays["colourings"]   # it fails while the view updates)
                  for value in (selector, CELLS, array)])
    tables = _helper(representation, "BlockLookupTables")
    tables.RemoveAllValues()
    for _, array in displays["colourings"]:
        tables.Add(colour_maps[array])
    _set_strings(representation, "BlockUseSeparateColorMaps",
                 [value for selector, _ in displays["colourings"] for value in (selector, 0)])
    _set_strings(representation, "BlockColors",
                 [value for selector, colour in displays["solid_colours"] for value in [selector] + list(colour)])
    _set_strings(representation, "BlockOpacities",
                 [value for selector, opacity in displays["opacities"] for value in (selector, opacity)])
    if representation.GetProperty("Representation") is not None:
        _helper(representation, "Representation").Set(displays["representation"])
    representation.UpdateVTKObjects()
    if rescale is None:
        rescale = source.GetXMLName() == READER
    information = source.GetDataInformation(port)
    for array, colour in displays["colour_maps"].items():
        colour_map = colour_maps[array]
        _apply_preset(colour_map, colour["colormap"])
        if colour["range"] is None:
            _helper(colour_map, "AutomaticRescaleRangeMode").Set(GROW_ON_APPLY)
            found = information.GetArrayInformation(array, CELLS)
            if rescale and found is not None:           # (a layer empty at this time step: not yet)
                low, high = found.GetComponentRange(-1 if found.GetNumberOfComponents() > 1 else 0)
                colour_map.RescaleTransferFunction(low, high if high > low else low + 1e-12 * max(1., abs(low)))
        else:
            _helper(colour_map, "AutomaticRescaleRangeMode").Set(NEVER)
            colour_map.RescaleTransferFunction(*colour["range"])
        _helper(colour_map, "UseLogScale").Set(int(colour["log"]))
        colour_map.UpdateVTKObjects()
    for view in _views_of(representation):
        show_scalar_bars(representation, view, displays, present)
    return True


def _views_of(representation) -> list:
    return [view for view in _proxies("views")
            if view.GetProperty("Representations") is not None and representation in _represented(view)]


def show_scalar_bars(representation, view, displays: dict = None, present: set = None) -> None:
    """The colour legends of the visible coloured layers of *representation* shown in *view* (those whose array its
    data holds, *present*), titled with their units (_watch_legend)."""
    if present is None:
        present = _cell_arrays(_input(representation))
    if displays is None:
        displays = _views().block_displays(_reader_views(reader_of(_input(representation)))[2], present)
    shown = [selector for selector, array in displays["colourings"]
             if selector in displays["selectors"] and array in present]
    with _quiet():                                      # (a layer empty at this time step: no legend yet)
        for selector in shown:
            _colour_maps().vtkSMColorMapEditorHelper.SetBlocksScalarBarVisibility(representation, view, [selector],
                                                                                    True)
    manager = _colour_maps().vtkSMTransferFunctionManager()
    for array in dict.fromkeys(array for selector, array in displays["colourings"] if selector in shown):
        legend = manager.GetScalarBarRepresentation(_colour_map(array), view)
        if legend is not None:
            _watch_legend(legend)


def legend_title(array: str, unit: str = None) -> str:
    """The colour legend's title of *array*: "<array> [<unit>]", the array alone without a unit or for "1"."""
    return f"{array} [{unit}]" if unit and unit != "1" else array


def _watch_legend(legend) -> None:
    """*legend* (a scalar bar) titled with its array's unit now and whenever ParaView titles it again by the array's
    name (a layer's legend shown, or the user colouring by another array: _titled)."""
    watched = _session.setdefault("legends", set())
    if legend.GetGlobalID() not in watched:
        legend.AddObserver("PropertyModifiedEvent", _titled)
        watched.add(legend.GetGlobalID())
    _titled(legend)


def _titled(legend, event=None) -> None:
    """*legend*'s title "<array> [<unit>]" (legend_title) when it is the bare name of an array of the plugin's items
    that holds a unit; any other title (one the user typed, an array without a unit, of another item) kept."""
    if legend.GetProperty("Title") is None:
        return
    title = _text(legend, "Title")
    if not title or title.endswith("]"):
        return
    units = {}
    for source in _proxies("sources"):
        if source.GetXMLName() in (READER, SELECT_AT_SCALE):
            for array, unit in _units(source).items():
                units.setdefault(array, unit)
    titled = legend_title(title, units.get(title))
    if titled != title:
        _helper(legend, "Title").Set(titled)
        legend.UpdateVTKObjects()


def _units(source, port: int = 0) -> dict:
    """{cell array: its unit} of *source*'s data, the units the reader put in the arrays' information
    (vtkDataArray.UNITS_LABEL); empty when the data is not in this process (a remote server)."""
    from vtkmodules.vtkCommonCore import vtkDataArray
    from vtkmodules.vtkCommonDataModel import vtkCompositeDataSet
    algorithm = source.GetClientSideObject() if source is not None else None
    data = algorithm.GetOutputDataObject(port) if algorithm is not None and hasattr(
        algorithm, "GetOutputDataObject") else None
    if data is None:
        return {}
    leaves = []
    if isinstance(data, vtkCompositeDataSet):
        iterator = data.NewIterator()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            leaves.append(iterator.GetCurrentDataObject())
            iterator.GoToNextItem()
    else:
        leaves.append(data)
    key, units = vtkDataArray.UNITS_LABEL(), {}
    for leaf in leaves:
        cell_data = leaf.GetCellData() if hasattr(leaf, "GetCellData") else None
        for number in range(cell_data.GetNumberOfArrays() if cell_data is not None else 0):
            array = cell_data.GetAbstractArray(number)
            information = array.GetInformation() if array is not None else None
            if information is not None and information.Has(key):
                units.setdefault(array.GetName(), information.Get(key))
    return units


# ── Saving the views ─────────────────────────────────────────────────────────

def _proxy_of(algorithm):
    """The pipeline item (source proxy) whose server object is *algorithm* (the built-in server's)."""
    if hasattr(algorithm, "GetXMLName"):                # a proxy already
        return algorithm
    address = algorithm.GetAddressAsString("vtkObject")
    for proxy in _proxies("sources"):
        found = proxy.GetClientSideObject()
        if found is not None and found.GetAddressAsString("vtkObject") == address:
            return proxy
    raise RuntimeError("its item is not in this session (a remote server: the buttons need ParaView's built-in one)")


def _active_view():
    proxy_manager = _proxy_manager()
    selection = proxy_manager.GetSelectionModel("ActiveView") if proxy_manager is not None else None
    return selection.GetCurrentProxy() if selection is not None else None


def _representation_in(source, view):
    """*source*'s representation in *view* (else its first one; None: none)."""
    found = representations_of(source)
    in_view = [representation for representation in found if view is not None and representation in _represented(view)]
    return (in_view or found or [None])[0]


def representation_state(representation) -> dict:
    """The properties displays_from_blocks reads, from *representation*."""
    state = {name: _strings(representation, name)
             for name in ("BlockSelectors", "BlockColorArrayNames", "BlockColors", "BlockOpacities")}
    state["ColorArrayName"] = _helper(representation, "ColorArrayName").GetInputArrayNameToProcess() or None
    diffuse = _helper(representation, "DiffuseColor")
    state["DiffuseColor"] = [diffuse.GetAsDouble(number) for number in range(3)]
    state["Opacity"] = _helper(representation, "Opacity").GetAsDouble(0)
    state["Representation"] = _text(representation, "Representation") or None
    named = state["BlockColorArrayNames"]
    arrays = [named[start + 2] for start in range(0, len(named) - 2, 3) if named[start + 2]]
    tables = _helper(representation, "BlockLookupTables")
    own = {array: tables.GetAsProxy(number) for number, array in enumerate(arrays)} \
        if tables.GetNumberOfElements() == len(arrays) else {}
    state["colour_maps"] = {}
    for array in arrays + ([state["ColorArrayName"]] if state["ColorArrayName"] else []):
        colour_map = own.get(array) or _colour_map(array)
        points = _helper(colour_map, "RGBPoints")
        values = [points.GetAsDouble(number) for number in range(points.GetNumberOfElements())]
        follows = _helper(colour_map, "AutomaticRescaleRangeMode").GetAsInt(0) != NEVER
        state["colour_maps"][array] = (None if follows or len(values) < 8 else [values[0], values[-4]],
                                       bool(_helper(colour_map, "UseLogScale").GetAsInt(0)))
    return state


def save_views(algorithm, configuration: str = None) -> str:
    """The reader's "Save Views": its layers' display in the active view (else its first representation) written
    into its views file, over its configuration or into *configuration*, made the active one; the file's path."""
    views = _views()
    reader = _proxy_of(algorithm)
    path, name, _ = _reader_views(reader)
    if path is None:
        raise RuntimeError(f"no views file for {_text(reader, 'FileName')} (a views.json next to it, or Views)")
    representation = _representation_in(reader, _active_view())
    if representation is None:
        raise RuntimeError("the reader is shown in no view: nothing to save")
    document = views.read_views(path)
    layers = document["configurations"][name]["layers"]
    displays = views.displays_from_blocks(layers, representation_state(representation))
    saved = [views.layer_from_display(layer, display) for layer, display in zip(layers, displays)]
    target = configuration or name
    views.write_views(path, views.save_configuration(document, target, saved))
    if target != name:
        _helper(reader, "Configuration").Set(target)
        reader.UpdateVTKObjects()
        reader.UpdatePropertyInformation()             # the new configuration in the drop-down
    for source in [reader] + _selections_of(reader):    # drawn as saved: not drawn again
        for drawn in representations_of(source):
            drawn.SetAnnotation(DRAWN, _drawn_signature(drawn, reader))
    print(f"encoding3d views: configuration '{target}' saved in {path}")
    return path


def _selections_of(reader) -> list:
    return [proxy for proxy in _proxies("sources")
            if proxy.GetXMLName() == SELECT_AT_SCALE and reader_of(proxy) is reader]


# ── Showing a selection: isolated, in a panel, put back ──────────────────────

def _simple():
    """paraview.simple, on the active session (the GUI's, when a button runs it)."""
    from paraview import servermanager, simple
    if servermanager.ActiveConnection is None:
        servermanager.SetActiveConnection(servermanager.GetConnectionFromSession(
            _server_manager().vtkSMProxyManager.GetProxyManager().GetActiveSession()))
    return simple


def _python_proxy(proxy):
    from paraview import servermanager
    return servermanager._getPyProxy(proxy)


def _name_of(proxy) -> str:
    return _proxy_manager().GetProxyName("sources", proxy)


def _named_views() -> dict:
    """{registration name: view proxy} of the session's views."""
    proxy_manager = _proxy_manager()
    return {proxy_manager.GetProxyName("views", view): view for view in _proxies("views")}


def _steps(view) -> list:
    return json.loads(view.GetAnnotation(STATE)) if view.HasAnnotation(STATE) else []


def _keep_steps(view, steps: list) -> None:
    if steps:
        view.SetAnnotation(STATE, json.dumps(steps))
    elif view.HasAnnotation(STATE):
        view.RemoveAnnotation(STATE)


def shown_steps() -> list:
    """[(view proxy, step)] of every selection shown, the last shown last."""
    found = [(view, step) for view in _proxies("views") for step in _steps(view)]
    return sorted(found, key=lambda pair: pair[1]["order"])


def _upstream_names(proxy) -> set:
    names = set()
    proxy = _input(proxy)
    while proxy is not None:
        names.add(_name_of(proxy))
        proxy = _input(proxy)
    return names


def _visible_items(view) -> dict:
    """{item name: visible} of the pipeline items drawn in *view*."""
    found = {}
    for representation in _represented(view):
        source = _input(representation) if representation is not None else None
        name = _name_of(source) if source is not None else None
        if name:
            found[name] = found.get(name, False) or bool(_helper(representation, "Visibility").GetAsInt(0))
    return found


def _selection(algorithm):
    proxy = _proxy_of(algorithm)
    if proxy.GetXMLName() != SELECT_AT_SCALE:
        raise RuntimeError("not an 'encoding3d Select at scale' item")
    return proxy


def _show(selection, mode: str, view=None) -> None:
    simple, views = _simple(), _views()
    view = view or _active_view()
    if view is None:
        raise RuntimeError("no active view")
    above = _upstream_names(selection)
    while shown_steps() and shown_steps()[-1][1]["selection"] not in above:
        put_back()                                     # not drawn from the last selection shown: put it back
    selection_item, view_item = _python_proxy(selection), _python_proxy(view)
    picked_on = _input(selection)
    if picked_on is not None:
        simple.ClearSelection(_python_proxy(picked_on))  # the picked cells' highlight (the filter keeps a copy)
    hidden, bars, panel, shown_by_apply = [], [], None, False
    if mode == "isolate":
        simple.Show(selection_item, view_item)
        hidden = views.isolated(_visible_items(view), [_name_of(selection)])
        for name in hidden:
            item = simple.FindSource(name)
            display = simple.GetDisplayProperties(item, view_item)
            if display.LookupTable is not None and simple.GetScalarBar(display.LookupTable, view_item).Visibility:
                bars.append(name)
            simple.Hide(item, view_item)
        simple.HideUnusedScalarBars(view_item)
    else:
        drawn = [representation for representation in representations_of(selection)
                 if representation in _represented(view)]
        own_step = any(step["selection"] == _name_of(selection) for step in _steps(view))
        if not own_step and any(_helper(representation, "Visibility").GetAsInt(0) for representation in drawn):
            simple.Hide(selection_item, view_item)     # drawn there by Apply: the view as it was before the filter
            shown_by_apply = True                      # (shown again by Put Back)
        panel = _panel(view_item)
        display = simple.Show(selection_item, panel)
        show_scalar_bars(display.SMProxy, panel.SMProxy)
        panel.ResetCamera()
        simple.Render(panel)
    step = {"selection": _name_of(selection), "hidden": hidden, "scalar_bars": bars,
            "panel": None if panel is None else _proxy_manager().GetProxyName("views", panel.SMProxy),
            "shown_by_apply": shown_by_apply, "order": time.time()}
    _keep_steps(view, _steps(view) + [step])
    simple.SetActiveView(view_item)
    simple.Render(view_item)
    print(f"encoding3d selection shown ({mode}): {_name_of(selection)}, scale {_text(selection, 'Scale')}")


def isolate(algorithm, view=None) -> None:
    """The selection ("Select at scale" item, or its server object) alone in *view* (the active one)."""
    _show(_selection(algorithm), "isolate", view)


def show_in_panel(algorithm, view=None) -> None:
    """The selection in a new render view beside *view* (the active one)."""
    _show(_selection(algorithm), "panel", view)


def _panel(view):
    """A new render view beside *view*, at its time, its camera to start with."""
    simple = _simple()
    panel = simple.CreateView("RenderView")
    layout = simple.GetLayout(view)
    if layout is None:
        layout = simple.CreateLayout("encoding3d")
        layout.AssignView(0, view)
    location = layout.GetViewLocation(view)
    layout.SplitHorizontal(location, 0.5)
    layout.AssignView(2 * location + 2, panel)
    panel.ViewSize = list(view.ViewSize)
    panel.CameraPosition, panel.CameraFocalPoint = list(view.CameraPosition), list(view.CameraFocalPoint)
    panel.CameraViewUp = list(view.CameraViewUp)
    panel.ViewTime = view.ViewTime
    return panel


def put_back(algorithm=None) -> bool:
    """One step back: the last selection shown put back (hidden, or its panel closed), what it hid shown again;
    whether there was one."""
    simple = _simple()
    steps = shown_steps()
    if not steps:
        return False
    view, step = steps[-1]
    view_item = _python_proxy(view)
    for name in step["hidden"]:
        item = simple.FindSource(name)
        if item is not None:
            display = simple.Show(item, view_item)
            if name in step.get("scalar_bars", []) and display.LookupTable is not None:
                simple.GetScalarBar(display.LookupTable, view_item).Visibility = 1   # its legend, as Isolate found it
    selection = simple.FindSource(step["selection"])
    if step["panel"]:
        panel = _named_views().get(step["panel"])
        if panel is not None:
            panel_item = _python_proxy(panel)
            layout = simple.GetLayout(panel_item)
            if layout is not None:
                location = layout.GetViewLocation(panel_item)
                layout.RemoveView(panel_item)
                if location > 0:
                    layout.Collapse(location)
            simple.Delete(panel_item)
        if step.get("shown_by_apply") and selection is not None:
            simple.Show(selection, view_item)          # as Apply had drawn it
    elif selection is not None:
        simple.Hide(selection, view_item)
    _keep_steps(view, [kept for kept in _steps(view) if kept["order"] != step["order"]])
    simple.Render(view_item)
    print(f"encoding3d selection put back: {step['selection']}")
    return True
