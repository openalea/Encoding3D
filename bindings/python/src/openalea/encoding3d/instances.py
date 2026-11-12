"""
Instances of shared templates and their derived fields (specification §12), for readers::

    evaluate(frame, field, instances=None) -> [values per instance]     a derived field rebuilt (numpy; scipy for
                                                                         sparse operators when installed)
    placed_meshes(frame, data_structure, instance_set, instances=None)  the instances' template meshes, placed
    find_instance_set(frame, name=None, data_structure=None)            (data structure, instance set)

A derived field is evaluated one operator at a time over every instance using it (one matrix product per operator,
not per instance), so that rebuilding many instances of few templates stays cheap.
"""
from dataclasses import dataclass

import numpy as np

from openalea.encoding3d.model import NO_ID, Template


def find_instance_set(frame, name: str = None, data_structure: str = None, field: str = None) -> tuple:
    """(data structure, instance set) of *frame*: the one named *name* (in *data_structure* when given), or the one
    holding the derived field *field*; a KeyError when there is none, a ValueError when several match."""
    found = []
    for candidate in frame.data_structures:
        if data_structure is not None and candidate.id != data_structure:
            continue
        for instance_set in candidate.instance_sets:
            if name is not None and instance_set.name != name:
                continue
            if field is not None and field not in [derived.name for derived in instance_set.derived]:
                continue
            found.append((candidate, instance_set))
    what = " ".join(part for part in (f"'{name}'" if name else "", f"with the derived field '{field}'" if field
                                      else "", f"in '{data_structure}'" if data_structure else "") if part)
    if not found:
        raise KeyError(f"the frame has no instance set {what}".rstrip())
    if len(found) > 1:
        raise ValueError(f"several instance sets {what}: {[(ds.id, s.name) for ds, s in found]}; name the data "
                         "structure or the instance set")
    return found[0]


def _rows(instance_set, instances) -> np.ndarray:
    if instances is None:
        return np.arange(instance_set.count, dtype=np.int64)
    instances = np.asarray(instances)
    if instances.dtype == bool:
        return np.flatnonzero(instances)
    rows = instances.astype(np.int64).reshape(-1)
    if rows.size and (rows.min() < 0 or rows.max() >= instance_set.count):
        raise IndexError(f"instance rows outside the {instance_set.count} instances of '{instance_set.name}'")
    return rows


def evaluate(frame, field: str, instances=None, data_structure: str = None, instance_set: str = None) -> list:
    """The derived field *field* of the instances at *instances* (rows of their instance set, a boolean mask, or None:
    all), one float64 array each, on the rows of the field's entity set in the instance's template: the sum over the
    instance's terms of weight · (operator · input + offset). An instance with no term: NaN. *data_structure*,
    *instance_set*: where the field is, when several instance sets have one of that name. The parts are found
    through the frame (Frame.part)."""
    _, found = find_instance_set(frame, instance_set, data_structure, field=field)
    derived = found.derived_field(field)
    rows = _rows(found, instances)
    templates = found.columns["template"]
    inputs = found.vectors[derived.input]
    sizes = {}

    def size(template_index: int) -> int:
        if template_index not in sizes:
            template = frame.part(found.parts[template_index])
            if not isinstance(template, Template):
                raise ValueError(f"'{found.name}': part {template_index} is not a template")
            sizes[template_index] = template.entity_set(derived.entity_set).count
        return sizes[template_index]

    out = [np.full(size(int(templates[row])), np.nan) for row in rows]
    started = np.zeros(rows.size, dtype=bool)
    for term in range(derived.terms):
        operator_of = derived.operators[rows, term]
        weight_of = derived.weights[rows, term]
        offsets = found.vectors[derived.offsets[term]] if derived.offsets[term] is not None else None
        for operator_index in np.unique(operator_of[operator_of != NO_ID]).tolist():
            positions = np.flatnonzero(operator_of == operator_index)
            operator = frame.part(found.parts[operator_index])
            if not hasattr(operator, "apply"):
                raise ValueError(f"'{found.name}': part {operator_index} is not an operator")
            chosen = rows[positions]
            counts = inputs.counts[chosen]
            if (counts != operator.shape[1]).any():
                bad = int(chosen[np.flatnonzero(counts != operator.shape[1])[0]])
                raise ValueError(f"'{found.name}' instance {bad}: {int(inputs.counts[bad])} values of "
                                 f"'{derived.input}', its operator takes {operator.shape[1]}")
            stacked = inputs.take(chosen).values.reshape(positions.size, operator.shape[1]).T
            values = operator.apply(stacked).T * weight_of[positions][:, None]       # (instances, rows)
            for number, position in enumerate(positions.tolist()):
                result = values[number]
                if result.size != out[position].size:
                    raise ValueError(f"'{found.name}' instance {int(rows[position])}: operator {operator_index} has "
                                     f"{result.size} rows, its template's '{derived.entity_set}' {out[position].size}")
                if offsets is not None and offsets.counts[rows[position]]:
                    result = result + weight_of[position] * offsets[rows[position]]
                out[position] = result if not started[position] else out[position] + result
                started[position] = True
    return out


@dataclass
class PlacedMeshes:
    """The instances' template meshes, placed: *positions* (V, 3) in the data structure's frame (its origin not
    applied), *triangles* (T, 3) into them, and per triangle: *instance* (its instance's row), *template* (the index
    of its template in the set's parts), *mesh* (the index of its mesh in the template's meshes) and *template_rows*
    ({template entity set: the triangle's row in it, NO_ID for none})."""
    positions: np.ndarray
    triangles: np.ndarray
    instance: np.ndarray
    template: np.ndarray
    mesh: np.ndarray
    template_rows: dict


def placed_meshes(frame, data_structure, instance_set, instances=None) -> PlacedMeshes:
    """Every mesh of the template of each instance at *instances* (rows, a mask, or None: all), its vertices moved by
    the instance's transform (specification §12.2). *data_structure*, *instance_set*: the objects, or their names."""
    if isinstance(data_structure, str):
        data_structure = frame.data_structure(data_structure)
    if isinstance(instance_set, str):
        instance_set = data_structure.instance_set(instance_set)
    rows = _rows(instance_set, instances)
    transforms = instance_set.transforms()
    templates = instance_set.columns["template"]
    positions, triangles, instance, template_of, mesh_indices, set_rows = [], [], [], [], [], []
    vertex_count = 0
    for template_index in np.unique(templates[rows]).tolist():
        template = frame.part(instance_set.parts[template_index])
        chosen = rows[templates[rows] == template_index]
        for mesh_index, mesh in enumerate(template.meshes):
            corners = (mesh.indices if mesh.indices is not None else np.arange(len(mesh.positions))).reshape(-1, 3)
            local = np.c_[mesh.positions, np.ones(len(mesh.positions))]                     # (v, 4)
            placed = np.einsum("nij,vj->nvi", transforms[chosen][:, :3, :], local)            # (n, v, 3)
            positions.append(placed.reshape(-1, 3))
            offsets = vertex_count + np.arange(chosen.size, dtype=np.int64) * len(mesh.positions)
            triangles.append((corners[None, :, :] + offsets[:, None, None]).reshape(-1, 3))
            vertex_count += chosen.size * len(mesh.positions)
            instance.append(np.repeat(chosen, len(corners)))
            template_of.append(np.full(chosen.size * len(corners), template_index, dtype=np.int64))
            mesh_indices.append(np.full(chosen.size * len(corners), mesh_index, dtype=np.int32))
            first = corners[:, 0]
            set_rows.append({name: np.tile(feature_rows[first], chosen.size)
                             for name, feature_rows in mesh.feature_rows.items()})
    count = sum(len(part) for part in instance)
    names = sorted({name for item in set_rows for name in item})
    template_rows = {}
    for name in names:
        template_rows[name] = np.concatenate([item.get(name, np.full(len(part), NO_ID, dtype=np.int64))
                                              for item, part in zip(set_rows, instance)]) if count else \
            np.zeros(0, dtype=np.int64)

    def joined(items, dtype, shape=(0,)):
        return np.concatenate(items) if items else np.zeros(shape, dtype=dtype)
    return PlacedMeshes(positions=joined(positions, np.float64, (0, 3)), triangles=joined(triangles, np.int64, (0, 3)),
                        instance=joined(instance, np.int64), template=joined(template_of, np.int64),
                        mesh=joined(mesh_indices, np.int32), template_rows=template_rows)
