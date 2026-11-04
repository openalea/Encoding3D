"""
ParaView macro "Apply encoding3d views": each layer of the selected encoding3d reader's configuration (its "Views" file and
"Configuration", see encoding3d_reader.py) becomes its own pipeline item, named by the layer: an ExtractBlock of the
layer's block, a Tube on "tube_radius" for a segments layer, shown with its colour variable, colour map, range, log
scale, solid colour, opacity, representation and visibility. Applied again, it replaces the items it made, those of
the views' other configurations included (the reader's Configuration changed).

    Macros > Import new macro..., choose this file; select the encoding3d reader in the Pipeline Browser, then
    Macros > apply_encoding3d_views.

What each layer gives is openalea.encoding3d.views.display_settings(layer), tested without ParaView; this file only
hands it to paraview.simple.
"""
from paraview import simple


def _views():
    try:
        from openalea.encoding3d import views
    except ImportError:
        raise RuntimeError("openalea.encoding3d is not on ParaView's path: load the encoding3d reader plugin first (it adds "
                           "its encoding3d folder), or install openalea.encoding3d in ParaView's Python") from None
    return views


def reader_views(source):
    """(views module, the views file's path, its document, the configuration's name, its layers) of the encoding3d
    reader *source*."""
    views = _views()
    if source is None or not hasattr(source, "Configuration"):
        raise RuntimeError("select an encoding3d reader in the Pipeline Browser first")
    file_name = views.property_text(source.FileName)
    path = views.views_path(file_name, views.property_text(source.Views) or None)
    if path is None:
        raise RuntimeError(f"no views file for {file_name} (a views.json next to it, or the reader's Views)")
    document = views.read_views(path)
    name, layers = views.configuration(document, views.property_text(source.Configuration) or None)
    return views, path, document, name, layers


def _cell_arrays(item) -> set:
    return set(item.CellData.keys())


def _apply_preset(colours, colormap: str, views) -> None:
    for name in views.preset_names(colormap):
        try:
            colours.ApplyPreset(name, True)
            return
        except RuntimeError:                               # not a preset of this ParaView
            continue
    print(f"encoding3d views: no colour map preset '{colormap}' in this ParaView, its default kept")


def _remove(name: str) -> None:
    for item_name in (name, f"{name} block"):              # the tube first, then the block it reads
        item = simple.FindSource(item_name)
        if item is not None:
            simple.Delete(item)


def show_layer(source, layer: dict, view, views) -> None:
    _remove(layer["name"])
    settings = views.display_settings(layer)
    tube = settings["tube"]
    block = simple.ExtractBlock(registrationName=f"{layer['name']} block" if tube else layer["name"], Input=source,
                                Selectors=[settings["selector"]])
    item = block
    if tube:
        item = simple.Tube(registrationName=layer["name"], Input=block)
        item.Scalars = ["POINTS", tube["radius_array"]]
        item.VaryRadius = "By Absolute Scalar"
    item.UpdatePipeline()
    settings = views.display_settings(layer, _cell_arrays(item))
    display = simple.Show(item, view)
    display.SetRepresentationType(settings["representation"])
    if settings["color_array"]:
        simple.ColorBy(display, ("CELLS", settings["color_array"]))
        colours = simple.GetColorTransferFunction(settings["color_array"])
        _apply_preset(colours, settings["colormap"], views)
        if settings["range"] is None:
            colours.AutomaticRescaleRangeMode = "Grow and update on 'Apply'"
            display.RescaleTransferFunctionToDataRange(True, False)
        else:
            colours.AutomaticRescaleRangeMode = "Never"
            colours.RescaleTransferFunction(*settings["range"])
        colours.UseLogScale = int(settings["log"])
        display.SetScalarBarVisibility(view, settings["visible"])
    else:
        display.ColorArrayName = ["POINTS", ""]             # a solid colour (ColorBy(display, None) fails in 6.2)
        display.AmbientColor = display.DiffuseColor = settings["solid_color"]
    display.Opacity = settings["opacity"]
    if not settings["visible"]:
        simple.Hide(item, view)


def apply_views(source=None, view=None) -> None:
    source = source or simple.GetActiveSource()
    views, _, document, name, layers = reader_views(source)
    view = view or simple.GetActiveViewOrCreate("RenderView")
    source.UpdatePipeline()
    simple.Hide(source, view)
    for other in views.other_layer_names(document, name):     # another configuration's items, applied before
        _remove(other)
    for layer in layers:
        show_layer(source, layer, view, views)
    if hasattr(simple, "HideUnusedScalarBars"):
        simple.HideUnusedScalarBars(view)
    simple.SetActiveSource(source)
    simple.Render(view)


apply_views()
