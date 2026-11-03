"""
A frame as plain JSON values: every table's columns as lists, declarations, grids, mappings, meshes. The
conformance files' expected values (``*.expected.json``) are written with it, so that a reader in any language can
compare what it reads with them::

    frame_to_dict(frame) -> dict        NaN and missing values as null, ±∞ as "Infinity" / "-Infinity"; floats as
                                        the shortest decimal giving the same double
"""
import math

import numpy as np

from openalea.fspm_tf.model import Frame, Table


def _value(value):
    if isinstance(value, (float, np.floating)):
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"         # standard JSON has no infinities
        return None if math.isnan(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _column(values: np.ndarray):
    if np.ma.isMaskedArray(values):                      # missing values: null
        missing = np.ma.getmaskarray(values)
        if values.ndim == 2:
            return [[None if gone else _value(item) for item, gone in zip(row, row_missing)]
                    for row, row_missing in zip(values.data, missing)]
        return [None if gone else _value(item) for item, gone in zip(values.data, missing)]
    if values.ndim == 2:
        return [[_value(item) for item in row] for row in values]
    return [_value(item) for item in values]


def _table(table: Table) -> dict:
    entry = {"name": table.name, "count": table.count,
             "columns": {name: {"dtype": "string" if values.dtype == object else str(values.dtype),
                                "values": _column(values)} for name, values in table.columns.items()}}
    declarations = {}
    for name, variable in table.variables.items():
        declaration = {"unit": variable.unit, "role": variable.role}
        for key in ("standard_name", "kind", "description", "minimum", "maximum"):
            if getattr(variable, key) is not None:
                declaration[key] = getattr(variable, key)
        for key in ("references", "doi"):
            if getattr(variable, key):
                declaration[key] = list(getattr(variable, key))
        if variable.format is not None:
            declaration["format"] = variable.format
        declarations[name] = declaration
    if declarations:
        entry["variables"] = declarations
    return entry


def frame_to_dict(frame: Frame) -> dict:
    data_structures = []
    for data_structure in frame.data_structures:
        entry = {"id": data_structure.id, "kind": data_structure.kind,
                 "origin": data_structure.origin.tolist(),
                 "entity_sets": [dict(_table(entity_set), rank=entity_set.rank,
                                      **({"scale": entity_set.scale} if entity_set.scale is not None else {}))
                                 for entity_set in data_structure.entity_sets]}
        for key in ("platform", "model"):
            if getattr(data_structure, key) is not None:
                entry[key] = getattr(data_structure, key)
        if data_structure.extras:
            entry["extras"] = data_structure.extras
        if data_structure.labels:
            entry["labels"] = dict(data_structure.labels)
        if data_structure.relations:
            entry["relations"] = [dict(_table(relation), source_set=relation.source_set,
                                       target_set=relation.target_set) for relation in data_structure.relations]
        if data_structure.scalars is not None:
            entry["scalars"] = _table(data_structure.scalars)
        if data_structure.grid is not None:
            grid = data_structure.grid
            entry["grid"] = {"kind": grid.kind, "shape": list(grid.shape), "origin": list(grid.origin),
                             "spacing": list(grid.spacing), "axes": list(grid.axes),
                             "periodic": list(grid.periodic), "z_up": grid.z_up, "max_level": grid.max_level,
                             "cells": grid.cells}
        if data_structure.meshes:
            entry["meshes"] = [{
                "name": mesh.name,
                "positions_float32": _column(mesh.positions.astype(np.float32).astype(np.float64)),
                "feature_rows": {name: rows.tolist() for name, rows in mesh.feature_rows.items()},
                **({"indices": mesh.indices.tolist()} if mesh.indices is not None else {}),
                **({"display": {name: _column(np.asarray(values, dtype=np.float32).astype(np.float64))
                                for name, values in mesh.display.items()}} if mesh.display else {})}
                for mesh in data_structure.meshes]
        data_structures.append(entry)
    out = {"time": frame.time, "time_unit": frame.time_unit, "step": frame.step,
           "data_structures": data_structures,
           "mappings": [dict(_table(mapping), source=list(mapping.source), target=list(mapping.target),
                             method=mapping.method) for mapping in frame.mappings]}
    if frame.update is not None:                          # a partial frame: its sender and removed entities
        out["update"] = {"participant": frame.update.participant,
                         "removed": [{"data_structure": key[0], "entity_set": key[1], "ids": ids.tolist()}
                                     for key, ids in sorted(frame.update.removed.items())]}
    return out
