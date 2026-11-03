"""
ParaView macro "Select at scale": the cells picked in the view (Select Cells On, on any fspm-TF layer or reader) grown
to their entity at SCALE (a plant, an axis, an organ, a segment ...) with everything it contains at finer scales, in
every layer, hidden ones included (a segment's section); shown as MODE says:

    "isolate"   in the view, the other items hidden (Macros > clear_fspm_tf_selection shows them again);
    "panel"     in a new render view beside it, its own camera fit to the selection; the view itself untouched
                (clear_fspm_tf_selection closes the panel).

    Macros > Import new macro..., choose this file (and clear_fspm_tf_selection.py); set SCALE and MODE below
    (Macros > Edit...); load the fspm-TF reader plugin, pick cells, then Macros > select_at_scale.

The scales are the frame's entity sets (Plant, Axis, Organ, SubOrgan, ... Compartment); an unknown one is reported
with the picked elements' scales. The glue is fspm_tf_selection.py (next to the plugin, on ParaView's path once it
is loaded); what is selected, openalea.fspm_tf.views' picked_entities and selection_mask, tested without ParaView.
"""
SCALE = "Plant"
MODE = "isolate"                  # or "panel"

try:
    import fspm_tf_selection
except ImportError:
    raise RuntimeError("fspm_tf_selection is not on ParaView's path: load the fspm-TF reader plugin first") from None

fspm_tf_selection.select_at_scale(SCALE, MODE)
