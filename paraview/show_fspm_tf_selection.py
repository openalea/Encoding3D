"""
ParaView macro "Show fspm-TF selection": the selected "fspm-TF Select at scale" item (Filters > fspm-TF, applied with
cells picked) shown as its layers, each part drawn as its layer (the same colour map, a Tube for segments), as MODE
says:

    "isolate"   in the view, the other items hidden;
    "panel"     in a new render view beside it, its own camera fit to the selection; the view itself untouched.

Run again, it goes back: the items it made removed, the panel closed, the hidden items shown again (then delete the
filter to drop the selection). A selection made on the items shown (an axis of the plant shown) is shown over it, and
going back returns to the plant.

    Macros > Import new macro..., choose this file; set MODE below (Macros > Edit...). Load the fspm-TF reader
    plugin, pick cells, Filters > fspm-TF > fspm-TF Select at scale, Apply, then Macros > show_fspm_tf_selection.

The filter alone needs no macro: its output is the selection, every layer's part as a block. This macro does what a
filter cannot: hide the other items, open a panel. The glue is fspm_tf_selection.py (next to the plugin, on
ParaView's path once it is loaded).
"""
MODE = "isolate"                  # or "panel"

try:
    import fspm_tf_selection
except ImportError:
    raise RuntimeError("fspm_tf_selection is not on ParaView's path: load the fspm-TF reader plugin first") from None

fspm_tf_selection.show_or_back(MODE)
