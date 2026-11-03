"""
ParaView macro "Save fspm-TF views": the display options of the items "Apply fspm-TF views" made (visibility,
opacity, representation, colour variable or solid colour, range, log scale) written back into the reader's views
file, over its configuration, or into a new configuration named by CONFIGURATION below (Macros > Edit to set it),
made the active one. A layer without its item keeps what it had.

    Macros > Import new macro..., choose this file; select the fspm-TF reader in the Pipeline Browser, then
    Macros > save_fspm_tf_views.

The colour map's preset is not read back (ParaView does not keep a preset's name): a layer keeps its colormap.
What a display gives back is openalea.fspm_tf.views.layer_from_display(layer, display), tested without ParaView.
"""
from paraview import simple

CONFIGURATION = None              # None: overwrite the reader's configuration; a name: save as that configuration


def _views():
    try:
        from openalea.fspm_tf import views
    except ImportError:
        raise RuntimeError("openalea.fspm_tf is not on ParaView's path: load the fspm-TF reader plugin first (it adds "
                           "its fspm-TF folder), or install openalea.fspm_tf in ParaView's Python") from None
    return views


def display_of(item, view) -> dict:
    """The display options of a pipeline item, as layer_from_display takes them."""
    display = simple.GetDisplayProperties(item, view)
    array = display.ColorArrayName[1] if display.ColorArrayName and display.ColorArrayName[1] else None
    found = {"visible": bool(display.Visibility), "opacity": float(display.Opacity),
             "representation": str(display.Representation), "color_array": array,
             "solid_color": [float(value) for value in display.DiffuseColor]}
    if array:
        colours = simple.GetColorTransferFunction(array)
        points = list(colours.RGBPoints)
        found["range"] = None if colours.AutomaticRescaleRangeMode != "Never" else [points[0], points[-4]]
        found["log"] = bool(colours.UseLogScale)
    return found


def save_views(source=None, view=None, configuration: str = None) -> str:
    """Write the items' display options into the views file of *source* (default: the active one); its path."""
    views = _views()
    source = source or simple.GetActiveSource()
    if source is None or not hasattr(source, "Configuration"):
        raise RuntimeError("select an fspm-TF reader in the Pipeline Browser first")
    file_name = source.FileName if isinstance(source.FileName, str) else source.FileName[0]
    path = views.views_path(file_name, source.Views)
    if path is None:
        raise RuntimeError(f"no views file for {file_name} (a views.json next to it, or the reader's Views)")
    document = views.read_views(path)
    name, _ = views.configuration(document, source.Configuration or None)
    view = view or simple.GetActiveViewOrCreate("RenderView")
    layers = []
    for layer in document["configurations"][name]["layers"]:
        item = simple.FindSource(layer["name"])
        layers.append(views.layer_from_display(layer, display_of(item, view)) if item is not None else layer)
    target = configuration or name
    views.write_views(path, views.save_configuration(document, target, layers))
    if target != name:
        source.UpdatePropertyInformation()                 # the new configuration in the drop-down
        source.Configuration = target
    print(f"fspm-TF views: configuration '{target}' saved in {path}")
    return path


save_views(configuration=CONFIGURATION)
