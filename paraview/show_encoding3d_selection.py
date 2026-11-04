"""
ParaView macro "Show encoding3d selection": the selected "encoding3d Select at scale" item (Filters > encoding3d, applied with
cells picked) shown as its layers, each part drawn as its layer (the same colour map, a Tube for segments), as MODE
says:

    "isolate"   in the view, the other items hidden;
    "panel"     in a new render view beside it, its own camera fit to the selection; the view itself untouched.

Run again, it goes back: the items it made removed, the panel closed, the hidden items shown again (then delete the
filter to drop the selection). A selection made on the items shown (an axis of the plant shown) is shown over it, and
going back returns to the plant.

    Macros > Import new macro..., choose this file; set MODE below (Macros > Edit...). Load the encoding3d reader
    plugin, pick cells, Filters > encoding3d > encoding3d Select at scale, Apply, then Macros > show_encoding3d_selection.

The filter alone needs no macro: its output is the selection, every layer's part as a block. This macro does what a
filter cannot: hide the other items, open a panel. The glue is encoding3d_selection.py (next to the plugin, on
ParaView's path once it is loaded).
"""
MODE = "isolate"                  # or "panel"

try:
    import encoding3d_selection
except ImportError:
    raise RuntimeError("encoding3d_selection is not on ParaView's path: load the encoding3d reader plugin first") from None

encoding3d_selection.show_or_back(MODE)
