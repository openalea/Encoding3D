"""
ParaView macro "Clear fspm-TF selection": removes what select_at_scale made (the "<layer> selection" items, its
panel) and shows again the items it hid.

    Macros > Import new macro..., choose this file; then Macros > clear_fspm_tf_selection.
"""
try:
    import fspm_tf_selection
except ImportError:
    raise RuntimeError("fspm_tf_selection is not on ParaView's path: load the fspm-TF reader plugin first") from None

fspm_tf_selection.clear_selection()
