"""
Display copies: float32 per-vertex copies of variables, for viewers that do not read the property tables
(ParaView without the encoding3d plugin, Blender, three.js). They are added from the tables, flagged in FSPM_scene,
and never read as state::

    add_display(frame, ["water_potential"])     each mesh gets a _WATER_POTENTIAL attribute
    remove_display(frame)                       every display copy removed
"""
import numpy as np

from openalea.encoding3d.model import Frame, NO_ID


def add_display(frame: Frame, names, entity_set: str = None) -> Frame:
    """Add display copies of the variables *names* to every mesh holding them: each vertex takes the value of its
    entity in the entity set holding the variable (*entity_set*, or the first of the mesh's feature sets that has
    it); vertices without an entity there take NaN. Returns *frame*, changed in place."""
    for data_structure in frame.data_structures:
        for mesh in data_structure.meshes:
            for name in names:
                candidates = [entity_set] if entity_set else list(mesh.feature_rows)
                source = next((set_name for set_name in candidates if set_name in mesh.feature_rows
                               and name in data_structure.entity_set(set_name).columns), None)
                if source is None:
                    continue
                values = np.asarray(data_structure.entity_set(source).columns[name], dtype=np.float64)
                if values.ndim != 1:
                    raise ValueError(f"'{name}' is a vector: display copies are scalars")
                rows = mesh.feature_rows[source]
                copy = np.full(rows.size, np.nan)
                copy[rows != NO_ID] = values[rows[rows != NO_ID]]
                mesh.display[name] = copy.astype(np.float32)
                mesh.display_sources[name] = source
    return frame


def remove_display(frame: Frame, names=None) -> Frame:
    """Remove the display copies of *names* (all of them by default). Returns *frame*, changed in place."""
    for data_structure in frame.data_structures:
        for mesh in data_structure.meshes:
            for name in list(mesh.display if names is None else names):
                mesh.display.pop(name, None)
                mesh.display_sources.pop(name, None)
    return frame
