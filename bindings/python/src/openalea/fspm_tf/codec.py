"""
Reading and writing fspm-TF frames as GLB files, and sequences of frames with their index::

    write(path, frame)           a Frame to a .glb file          to_bytes(frame) -> bytes
    read(path) -> Frame          a .glb file to a Frame          from_bytes(data) -> Frame
    write_sequence(directory, frames)    one .glb per frame and the index scene.fspm.json
    read_index(path) -> dict             the index: its frames' times, steps and files

Tables are EXT_structural_metadata property tables (one class per table), meshes carry EXT_mesh_features feature
IDs, and the FSPM_scene root extension holds what these two cannot: data structures, entity sets and their ranks,
relations, grids, mappings, the frame's time, and the variables' units, standard names, kinds and roles.
"""
import itertools
import json
import os
import re

import numpy as np

from openalea.fspm_tf import SPECIFICATION_VERSION
from openalea.fspm_tf.glb import BufferBuilder, pack, unpack, view_bytes
from openalea.fspm_tf.model import (DataStructure, EDGE_TYPES, ENUM_COLUMNS, EntitySet, Frame, Grid, Mapping, Mesh, NO_ID,
                           Relation, Table, Update, Variable)

EXTENSION = "FSPM_scene"
METADATA = "EXT_structural_metadata"
FEATURES = "EXT_mesh_features"
EDGE_TYPE_ENUM = "FSPM_edge_type"
INDEX_FILE = "scene.fspm.json"
IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
FLOAT, UNSIGNED_INT = 5126, 5125
MAX_FLOAT_FEATURE = 2 ** 24                     # feature rows are stored as float32 vertex attributes
# The scene's frame is z up (metres); glTF viewers expect y up: the root node turns the scene for them (-90° about x,
# column-major). Readers of the tables use the scene's frame, not this node.
Z_UP_TO_Y_UP = [1., 0., 0., 0., 0., 0., -1., 0., 0., 1., 0., 0., 0., 0., 0., 1.]

COMPONENT_TYPES = {np.dtype(name): name.upper() for name in (
    "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float32", "float64")}
DTYPES = {code: dtype for dtype, code in COMPONENT_TYPES.items()}
# EXT_structural_metadata forbids NaN and infinities: NaN is written as noData, the most negative finite value;
# +inf and -inf as the largest finite value and the next one after the most negative, declared in the property's
# extras (FSPM_infinity)
NO_DATA_FLOAT = {np.dtype("float64"): float(np.finfo(np.float64).min),
                 np.dtype("float32"): float(np.finfo(np.float32).min)}
INFINITY_FLOAT = {dtype: {"positive": float(np.finfo(dtype).max),
                          "negative": float(np.nextafter(np.finfo(dtype).min, dtype.type(0)))}
                  for dtype in (np.dtype("float64"), np.dtype("float32"))}


# ── Writing ──────────────────────────────────────────────────────────────

def to_bytes(frame: Frame) -> bytes:
    """The GLB file of *frame*."""
    buffers = BufferBuilder()
    schema = {"id": "fspm_scene", "classes": {}, "enums": {
        EDGE_TYPE_ENUM: {"valueType": "UINT8", "values": [{"name": name, "value": value}
                                                         for value, name in enumerate(EDGE_TYPES)]}}}
    tables, variables = [], {}
    document = {"asset": {"version": "2.0", "generator": f"fspm-tf {SPECIFICATION_VERSION}"},
                "scene": 0, "scenes": [{"nodes": [0]}],
                "nodes": [{"name": "fspm_scene", "matrix": Z_UP_TO_Y_UP, "children": []}]}
    accessors, meshes = [], []

    def add_table(table: Table, class_id: str) -> int:
        _check_identifier(class_id, "class")
        properties, values = _encode_table(table, class_id, buffers, schema)
        schema["classes"][class_id] = {"name": table.name, "properties": properties}
        tables.append({"name": table.name, "class": class_id, "count": table.count, "properties": values})
        declared = {name: _declaration_json(table.variables[name]) for name in table.variable_names()
                    if name in table.variables}
        if declared:
            variables[class_id] = declared
        return len(tables) - 1

    data_structures = []
    for data_structure in frame.data_structures:
        _check_identifier(data_structure.id, "data structure id")
        entry = {"id": data_structure.id, "kind": data_structure.kind}
        for key in ("platform", "model"):
            if getattr(data_structure, key) is not None:
                entry[key] = getattr(data_structure, key)
        entry["origin"] = data_structure.origin.T.reshape(-1).tolist()      # column-major, as glTF matrices
        entry["entitySets"] = []
        for entity_set in data_structure.entity_sets:
            set_entry = {"name": entity_set.name, "rank": entity_set.rank}
            if entity_set.scale is not None:
                set_entry["scale"] = entity_set.scale
            set_entry["propertyTable"] = add_table(entity_set, f"{data_structure.id}__{entity_set.name}")
            entry["entitySets"].append(set_entry)
        if data_structure.relations:
            entry["relations"] = [
                {"name": relation.name, "sourceSet": relation.source_set, "targetSet": relation.target_set,
                 "propertyTable": add_table(relation, f"{data_structure.id}__{relation.name}")}
                for relation in data_structure.relations]
        if data_structure.scalars is not None:
            entry["scalars"] = add_table(data_structure.scalars, f"{data_structure.id}__scalars")
        if data_structure.grid is not None:
            entry["grid"] = _grid_json(data_structure.grid)
        if data_structure.labels:
            entry["labels"] = dict(data_structure.labels)
        if data_structure.extras:
            entry["extras"] = data_structure.extras
        node = {"name": data_structure.id}
        if not np.array_equal(data_structure.origin, np.eye(4)):
            node["matrix"] = entry["origin"]
        document["nodes"].append(node)
        document["nodes"][0]["children"].append(len(document["nodes"]) - 1)
        entry["node"] = len(document["nodes"]) - 1
        if data_structure.meshes:
            node["children"], entry["meshes"] = [], []
            for mesh in data_structure.meshes:
                meshes.append(_encode_mesh(mesh, data_structure, entry, buffers, accessors))
                document["nodes"].append({"name": mesh.name, "mesh": len(meshes) - 1})
                node["children"].append(len(document["nodes"]) - 1)
                mesh_entry = {"name": mesh.name, "mesh": len(meshes) - 1}
                if mesh.display:
                    mesh_entry["display"] = [{"attribute": _display_attribute(name), "variable": name,
                                              "entitySet": mesh.display_sources.get(name)}
                                             for name in mesh.display]
                entry["meshes"].append(mesh_entry)
        data_structures.append(entry)

    mappings = []
    for mapping in frame.mappings:
        _check_identifier(mapping.name, "mapping name")
        mappings.append({"name": mapping.name,
                         "source": {"dataStructure": mapping.source[0], "entitySet": mapping.source[1]},
                         "target": {"dataStructure": mapping.target[0], "entitySet": mapping.target[1]},
                         **({"method": mapping.method} if mapping.method else {}),
                         "propertyTable": add_table(mapping, f"mapping__{mapping.name}")})

    update = None
    if frame.update is not None:
        _check_identifier(frame.update.participant, "participant")
        update = {"participant": frame.update.participant}
        if frame.update.removed:
            update["removed"] = [
                {"dataStructure": data_structure_id, "entitySet": set_name,
                 "propertyTable": add_table(Table(f"{set_name}__removed", columns={"id": ids}),
                                            f"{data_structure_id}__{set_name}__removed")}
                for (data_structure_id, set_name), ids in frame.update.removed.items()]

    scene = {"version": SPECIFICATION_VERSION,
             "frame": {"time": float(frame.time), "timeUnit": frame.time_unit, "step": int(frame.step)}}
    if frame.vocabulary_version:
        scene["vocabulary"] = frame.vocabulary_version
    if frame.writer:
        scene["writer"] = dict(frame.writer)
    if update is not None:
        scene["update"] = update
    scene["dataStructures"] = data_structures
    if mappings:
        scene["mappings"] = mappings
    if variables:
        scene["variables"] = variables

    extensions = {METADATA: {"schema": schema, "propertyTables": tables}, EXTENSION: scene}
    extensions.update(frame.unknown.get("extensions", {}))
    used = [METADATA, EXTENSION] + ([FEATURES] if meshes else []) + list(frame.unknown.get("extensions", {}))
    document["extensionsUsed"] = used
    document["extensions"] = extensions
    if "extras" in frame.unknown:
        document["extras"] = frame.unknown["extras"]
    if meshes:
        document["meshes"], document["accessors"] = meshes, accessors
    binary = buffers.binary()
    if buffers.views:
        # the buffer holds the chunk's padding to 8 bytes: glTF-Validator warns of more than 3 bytes beyond it
        binary += b"\0" * (-len(binary) % 8)
        document["buffers"] = [{"byteLength": len(binary)}]
        document["bufferViews"] = buffers.views
    return pack(document, binary)


def write(path: str, frame: Frame) -> None:
    """Write *frame* to the GLB file *path*."""
    with open(path, "wb") as file:
        file.write(to_bytes(frame))


def _check_identifier(name: str, what: str) -> None:
    if not isinstance(name, str) or not IDENTIFIER.match(name):
        raise ValueError(f"{what} '{name}' must be an identifier (letters, digits, '_'; not starting with a digit)")


def _declaration_json(variable: Variable) -> dict:
    declaration = {"unit": variable.unit, "role": variable.role}
    for key, json_key in (("standard_name", "standardName"), ("kind", "kind"), ("minimum", "minimum"),
                          ("maximum", "maximum")):
        if getattr(variable, key) is not None:
            declaration[json_key] = getattr(variable, key)
    for key in ("references", "doi"):
        if getattr(variable, key):
            declaration[key] = list(getattr(variable, key))
    if variable.format is not None:
        declaration["format"] = variable.format
    return declaration


def _encode_table(table: Table, class_id: str, buffers: BufferBuilder, schema: dict) -> tuple:
    """The class properties and property table values of *table*'s columns."""
    properties, values = {}, {}
    for name, column in table.columns.items():
        _check_identifier(name, f"column of '{table.name}'")
        declaration = table.declaration(name)
        prop = {}
        if declaration.description:
            prop["description"] = declaration.description
        if name in ENUM_COLUMNS and name in table.reserved:
            names, codes = _enum_codes(name, column, class_id, schema)
            prop.update(type="ENUM", enumType=names)
            values[name] = {"values": buffers.add(codes)}
        elif column.dtype == object:
            prop["type"] = "STRING"
            if any(value is None for value in column):           # missing text: noData, a string the column lacks
                no_data = _free_string(column)
                prop["noData"] = no_data
                column = np.array([no_data if value is None else value for value in column], dtype=object)
            encoded = [value.encode("utf-8") for value in column]
            offsets = np.concatenate([[0], np.cumsum([len(value) for value in encoded])])
            offset_type = "UINT32" if offsets[-1] < 2 ** 32 else "UINT64"
            values[name] = {"values": buffers.add(b"".join(encoded)),
                            "stringOffsets": buffers.add(offsets.astype(offset_type.lower())),
                            "stringOffsetType": offset_type}
        elif column.dtype == bool:
            if column.ndim != 1:
                raise ValueError(f"column '{name}' of '{table.name}': boolean vectors are not supported")
            if np.ma.isMaskedArray(column):                      # booleans with missing values: UINT8 0, 1, 255
                prop.update(type="SCALAR", componentType="UINT8", noData=BOOLEAN_NO_DATA,
                            extras={"FSPM_boolean": True})
                stored = np.where(np.ma.getmaskarray(column), BOOLEAN_NO_DATA,
                                  np.asarray(column.data, dtype=np.uint8)).astype(np.uint8)
                values[name] = {"values": buffers.add(stored)}
            else:
                prop["type"] = "BOOLEAN"
                values[name] = {"values": buffers.add(np.packbits(column, bitorder="little"))}
        else:
            if column.dtype not in COMPONENT_TYPES:
                raise TypeError(f"column '{name}' of '{table.name}': dtype {column.dtype} is not supported")
            prop.update(type="SCALAR", componentType=COMPONENT_TYPES[column.dtype])
            if column.ndim == 2:
                if column.shape[1] < 2:
                    raise ValueError(f"column '{name}' of '{table.name}': vectors have at least 2 components")
                prop.update(array=True, count=int(column.shape[1]))
            data = column
            if column.dtype.kind == "f":
                if np.isinf(column).any():
                    stand_ins = INFINITY_FLOAT[column.dtype]
                    if np.isin(column, list(stand_ins.values())).any():
                        raise ValueError(f"column '{name}' of '{table.name}' holds both infinities and the values "
                                         f"standing for them ({stand_ins})")
                    prop["extras"] = {"FSPM_infinity": stand_ins}
                    data = np.where(column == np.inf, stand_ins["positive"],
                                    np.where(column == -np.inf, stand_ins["negative"], column)).astype(column.dtype)
                    column = data
                if np.isnan(column).any():
                    no_data = NO_DATA_FLOAT[column.dtype]
                    if (column == no_data).any():
                        raise ValueError(f"column '{name}' of '{table.name}' holds both NaN and {no_data}, the "
                                         "value standing for NaN")
                    prop["noData"] = no_data
                    data = np.where(np.isnan(column), no_data, column).astype(column.dtype)
            elif name in ("complex", "parent") and name in table.reserved:
                prop["noData"] = NO_ID
            elif np.ma.isMaskedArray(column):                    # missing integers: noData, a value the column lacks
                no_data = _free_integer(column)
                prop["noData"] = no_data
                data = np.where(np.ma.getmaskarray(column), no_data, np.asarray(column.data)).astype(column.dtype)
            values[name] = {"values": buffers.add(np.asarray(data))}
        if name == "id" and name in table.reserved and table.table_kind == "entity_set":
            prop["required"] = True
        properties[name] = prop
    return properties, values


BOOLEAN_NO_DATA = 255                           # a boolean column with missing values: UINT8 0, 1, and 255 missing


def _free_integer(column: np.ndarray) -> int:
    """A value of the column's integer type that it does not hold: its minimum (signed) or maximum (unsigned) first."""
    info = np.iinfo(column.dtype)
    present = set(np.asarray(column.compressed() if np.ma.isMaskedArray(column) else column).reshape(-1).tolist())
    first, second = (info.min, info.max) if info.min < 0 else (info.max, info.min)
    for candidate in (first, second):
        if candidate not in present:
            return int(candidate)
    step = 1 if info.min < 0 else -1                     # then inwards from the first: at most len(present) tries
    for candidate in itertools.count(first + step, step):
        if candidate not in present:
            return int(candidate)


def _free_string(column: np.ndarray) -> str:
    """A string the column does not hold: the empty string first, then NUL characters."""
    present = {value for value in column if value is not None}
    candidate = ""
    while candidate in present:
        candidate += "\0"
    return candidate


def _enum_codes(name: str, column: np.ndarray, class_id: str, schema: dict) -> tuple:
    values = np.asarray(column, dtype=object).tolist()
    distinct = set(values)                                          # hashed: a few names, however many rows
    if None in distinct:
        raise ValueError(f"{name} of '{class_id}': an enum column has no missing values (give each row a {name})")
    names = sorted(distinct)
    code_of = {label: code for code, label in enumerate(names)}
    codes = np.fromiter(map(code_of.__getitem__, values), dtype=np.int64, count=len(values))
    if name == "edge_type":
        unknown = set(names) - set(EDGE_TYPES)
        if unknown:
            raise ValueError(f"edge_type of '{class_id}': unknown values {sorted(unknown)} (allowed: {EDGE_TYPES})")
        return EDGE_TYPE_ENUM, np.array([EDGE_TYPES.index(value) for value in names], dtype=np.uint8)[codes]
    enum_id = f"{class_id}__{name}"
    value_type = "UINT8" if len(names) <= 256 else "UINT16"
    schema["enums"][enum_id] = {"valueType": value_type,
                                "values": [{"name": label, "value": code} for code, label in enumerate(names)]}
    return enum_id, codes.astype(value_type.lower())


def _grid_json(grid: Grid) -> dict:
    entry = {"kind": grid.kind, "shape": [int(n) for n in grid.shape], "origin": [float(x) for x in grid.origin],
             "spacing": [float(x) for x in grid.spacing], "axes": list(grid.axes),
             "periodic": [bool(p) for p in grid.periodic], "zUp": bool(grid.z_up), "cells": grid.cells}
    if grid.kind == "adaptive":
        entry["maxLevel"] = int(grid.max_level)
    return entry


def _display_attribute(name: str) -> str:
    return "_" + name.upper()


def _encode_mesh(mesh: Mesh, data_structure: DataStructure, entry: dict, buffers: BufferBuilder,
                 accessors: list) -> dict:
    def accessor(array, accessor_type, component_type, target, with_bounds=False):
        view = buffers.add(array, target=target)
        item = {"bufferView": view, "componentType": component_type, "count": len(array), "type": accessor_type}
        if with_bounds:
            item["min"] = array.min(axis=0).astype(float).tolist()
            item["max"] = array.max(axis=0).astype(float).tolist()
        accessors.append(item)
        return len(accessors) - 1

    positions = mesh.positions.astype(np.float32)
    attributes = {"POSITION": accessor(positions, "VEC3", FLOAT, ARRAY_BUFFER, with_bounds=True)}
    tables = {set_entry["name"]: set_entry["propertyTable"] for set_entry in entry["entitySets"]}
    feature_ids = []
    for set_index, (set_name, rows) in enumerate(mesh.feature_rows.items()):
        if set_name not in tables:
            raise ValueError(f"mesh '{mesh.name}': no entity set '{set_name}' in '{data_structure.id}'")
        count = data_structure.entity_set(set_name).count
        if count >= MAX_FLOAT_FEATURE:
            raise ValueError(f"mesh '{mesh.name}': {count} entities in '{set_name}', feature IDs stop at 2^24")
        if ((rows < NO_ID) | (rows >= count)).any():
            raise ValueError(f"mesh '{mesh.name}': feature rows of '{set_name}' outside its {count} rows")
        stored = np.where(rows == NO_ID, count, rows).astype(np.float32)       # null: one past the last row
        attributes[f"_FEATURE_ID_{set_index}"] = accessor(stored, "SCALAR", FLOAT, ARRAY_BUFFER)
        feature = {"featureCount": int(np.unique(rows[rows != NO_ID]).size), "attribute": set_index,
                   "propertyTable": tables[set_name], "label": set_name}
        if (rows == NO_ID).any():
            feature["nullFeatureId"] = count
        feature_ids.append(feature)
    for name, values in mesh.display.items():
        values = np.asarray(values, dtype=np.float32).reshape(-1)
        if values.size != len(positions):
            raise ValueError(f"mesh '{mesh.name}': display copy '{name}' has {values.size} values, "
                             f"{len(positions)} vertices")
        attributes[_display_attribute(name)] = accessor(values, "SCALAR", FLOAT, ARRAY_BUFFER)
    primitive = {"attributes": attributes, "mode": 4}
    if mesh.indices is not None:
        primitive["indices"] = accessor(mesh.indices.astype(np.uint32), "SCALAR", UNSIGNED_INT,
                                        ELEMENT_ARRAY_BUFFER)
    if feature_ids:
        primitive["extensions"] = {FEATURES: {"featureIds": feature_ids}}
    return {"name": mesh.name, "primitives": [primitive]}


# ── Reading ──────────────────────────────────────────────────────────────

def from_bytes(data: bytes) -> Frame:
    """The Frame of a GLB file's bytes."""
    document, binary = unpack(data)
    extensions = document.get("extensions", {})
    if EXTENSION not in extensions:
        raise ValueError(f"not an fspm-TF file: no {EXTENSION} extension")
    scene, metadata = extensions[EXTENSION], extensions.get(METADATA, {"schema": {}, "propertyTables": []})
    variables = scene.get("variables", {})

    def table(index: int, kind, **fields):
        description = metadata["propertyTables"][index]
        class_id = description["class"]
        columns, declarations = _decode_table(document, binary, description, metadata["schema"], variables)
        return kind(name=description.get("name", class_id), columns=columns, variables=declarations, **fields)

    frame_info = scene.get("frame", {})
    frame = Frame(time=frame_info.get("time", 0.), time_unit=frame_info.get("timeUnit", "d"),
                  step=frame_info.get("step", 0), writer=scene.get("writer", {}),
                  vocabulary_version=scene.get("vocabulary"))
    for entry in scene.get("dataStructures", []):
        data_structure = DataStructure(
            id=entry["id"], kind=entry.get("kind", "graph"), platform=entry.get("platform"),
            model=entry.get("model"), extras=entry.get("extras", {}), labels=entry.get("labels", {}),
            origin=np.asarray(entry.get("origin", np.eye(4).reshape(-1)), dtype=float).reshape(4, 4).T)
        data_structure.entity_sets = [table(item["propertyTable"], EntitySet, rank=item.get("rank"),
                                            scale=item.get("scale"))
                                      for item in entry.get("entitySets", [])]
        data_structure.relations = [table(item["propertyTable"], Relation, source_set=item["sourceSet"],
                                          target_set=item["targetSet"]) for item in entry.get("relations", [])]
        if "scalars" in entry:
            data_structure.scalars = table(entry["scalars"], Table)
        if "grid" in entry:
            grid = entry["grid"]
            data_structure.grid = Grid(kind=grid["kind"], shape=tuple(grid["shape"]), origin=tuple(grid["origin"]),
                                       spacing=tuple(grid["spacing"]), axes=tuple(grid["axes"]),
                                       periodic=tuple(grid["periodic"]), z_up=grid.get("zUp", True),
                                       max_level=grid.get("maxLevel", 0), cells=grid["cells"])
        tables = {item["propertyTable"]: item["name"] for item in entry.get("entitySets", [])}
        for mesh_entry in entry.get("meshes", []):
            data_structure.meshes.append(_decode_mesh(document, binary, mesh_entry, tables, data_structure))
        frame.data_structures.append(data_structure)
    for entry in scene.get("mappings", []):
        frame.mappings.append(table(entry["propertyTable"], Mapping,
                                    source=(entry["source"]["dataStructure"], entry["source"]["entitySet"]),
                                    target=(entry["target"]["dataStructure"], entry["target"]["entitySet"]),
                                    method=entry.get("method")))
    if "update" in scene:
        update = scene["update"]
        frame.update = Update(participant=update["participant"], removed={
            (item["dataStructure"], item["entitySet"]): table(item["propertyTable"], Table).columns["id"]
            for item in update.get("removed", [])})
    unknown_extensions = {name: value for name, value in extensions.items()
                          if name not in (METADATA, EXTENSION, FEATURES)}
    if unknown_extensions:
        frame.unknown["extensions"] = unknown_extensions
    if "extras" in document:
        frame.unknown["extras"] = document["extras"]
    return frame


def read(path: str) -> Frame:
    """The Frame of the GLB file *path*."""
    with open(path, "rb") as file:
        return from_bytes(file.read())


def _decode_table(document: dict, binary: bytes, description: dict, schema: dict, variables: dict) -> tuple:
    class_id = description["class"]
    properties = schema["classes"][class_id]["properties"]
    count = description["count"]
    columns, declarations = {}, {}
    for name, stored in description["properties"].items():
        prop = properties[name]
        raw = view_bytes(document, binary, stored["values"])
        if prop["type"] == "ENUM":
            enum = schema["enums"][prop["enumType"]]
            codes = np.frombuffer(raw, dtype=enum.get("valueType", "UINT16").lower(), count=count)
            values = np.array([item["value"] for item in enum["values"]], dtype=np.int64)
            names = np.empty(int(values.max()) + 1 if values.size else 0, dtype=object)
            names[values] = [item["name"] for item in enum["values"]]
            column = names[codes.astype(np.int64)] if count else np.zeros(0, dtype=object)
        elif prop["type"] == "STRING":
            offset_type = stored.get("stringOffsetType", "UINT32").lower()
            offsets = np.frombuffer(view_bytes(document, binary, stored["stringOffsets"]), dtype=offset_type,
                                    count=count + 1)
            column = np.array([raw[offsets[i]:offsets[i + 1]].decode("utf-8") for i in range(count)], dtype=object)
            if "noData" in prop:                                 # missing text
                column = np.array([None if value == prop["noData"] else value for value in column], dtype=object)
        elif prop["type"] == "BOOLEAN":
            column = np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder="little", count=count).astype(bool)
        elif prop["type"] == "SCALAR":
            dtype = DTYPES[prop["componentType"]]
            width = prop.get("count", 1) if prop.get("array") else 1
            if prop.get("array") and "count" not in prop:
                raise ValueError(f"'{class_id}.{name}': variable-length arrays are not part of fspm-TF 0.1")
            column = np.frombuffer(raw, dtype=dtype.newbyteorder("<"), count=count * width).astype(dtype)
            if width > 1:
                column = column.reshape(count, width)
            if dtype.kind == "f" and "noData" in prop:
                column = np.where(column == np.asarray(prop["noData"], dtype=dtype), np.nan, column).astype(dtype)
            infinity = prop.get("extras", {}).get("FSPM_infinity")
            if dtype.kind == "f" and infinity:
                column = np.where(column == np.asarray(infinity["positive"], dtype=dtype), np.inf,
                                  np.where(column == np.asarray(infinity["negative"], dtype=dtype), -np.inf, column)
                                  ).astype(dtype)
            if prop.get("extras", {}).get("FSPM_boolean"):         # booleans with missing values
                missing = column == prop.get("noData", BOOLEAN_NO_DATA)
                column = np.ma.MaskedArray(column == 1, mask=missing) if missing.any() else column == 1
            elif dtype.kind in "iu" and "noData" in prop and name not in ("complex", "parent"):   # missing integers
                missing = column == prop["noData"]
                if missing.any():
                    column = np.ma.MaskedArray(column, mask=missing)
        else:
            raise ValueError(f"'{class_id}.{name}': property type {prop['type']} is not part of fspm-TF 0.1")
        columns[name] = column
        declared = variables.get(class_id, {}).get(name)
        if declared is not None or "description" in prop:
            declared = declared or {}
            declarations[name] = Variable(
                unit=declared.get("unit", "1"), standard_name=declared.get("standardName"),
                kind=declared.get("kind"), role=declared.get("role", "state"), description=prop.get("description"),
                minimum=declared.get("minimum"), maximum=declared.get("maximum"),
                references=tuple(declared.get("references", ())), doi=tuple(declared.get("doi", ())),
                format=declared.get("format"))
    return columns, declarations


def _accessor_array(document: dict, binary: bytes, index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    dtype = {FLOAT: np.float32, UNSIGNED_INT: np.uint32, 5123: np.uint16, 5121: np.uint8}[accessor["componentType"]]
    raw = view_bytes(document, binary, accessor["bufferView"])
    view = document["bufferViews"][accessor["bufferView"]]
    item_size = np.dtype(dtype).itemsize * width
    stride = view.get("byteStride", item_size)
    start = accessor.get("byteOffset", 0)
    if stride == item_size:
        values = np.frombuffer(raw, dtype=dtype, count=accessor["count"] * width, offset=start)
    else:
        values = np.concatenate([np.frombuffer(raw, dtype=dtype, count=width, offset=start + i * stride)
                                 for i in range(accessor["count"])])
    return values.reshape(-1, width) if width > 1 else values


def _decode_mesh(document: dict, binary: bytes, mesh_entry: dict, tables: dict,
                 data_structure: DataStructure) -> Mesh:
    primitive = document["meshes"][mesh_entry["mesh"]]["primitives"][0]
    attributes = primitive["attributes"]
    positions = _accessor_array(document, binary, attributes["POSITION"]).astype(np.float64)
    feature_rows = {}
    for feature in primitive.get("extensions", {}).get(FEATURES, {}).get("featureIds", []):
        set_name = tables[feature["propertyTable"]]
        rows = _accessor_array(document, binary, attributes[f"_FEATURE_ID_{feature['attribute']}"]).astype(np.int64)
        if "nullFeatureId" in feature:
            rows = np.where(rows == feature["nullFeatureId"], NO_ID, rows)
        feature_rows[set_name] = rows
    display, sources = {}, {}
    for item in mesh_entry.get("display", []):
        display[item["variable"]] = _accessor_array(document, binary, attributes[item["attribute"]])
        if item.get("entitySet") is not None:
            sources[item["variable"]] = item["entitySet"]
    indices = (_accessor_array(document, binary, primitive["indices"]).astype(np.int64)
               if "indices" in primitive else None)
    return Mesh(name=mesh_entry["name"], positions=positions, feature_rows=feature_rows, indices=indices,
                display=display, display_sources=sources)


# ── Sequences ────────────────────────────────────────────────────────────

def write_sequence(directory: str, frames, name: str = "frame") -> str:
    """Write *frames* to *directory*, one GLB each (name_000000.glb, ...), and their index; the index's path."""
    os.makedirs(directory, exist_ok=True)
    entries, time_units = [], set()
    for number, frame in enumerate(frames):
        file_name = f"{name}_{number:06d}.glb"
        write(os.path.join(directory, file_name), frame)
        entries.append({"time": float(frame.time), "step": int(frame.step), "file": file_name})
        time_units.add(frame.time_unit)
    if len(time_units) > 1:
        raise ValueError(f"the frames' times are in several units: {sorted(time_units)}")
    path = os.path.join(directory, INDEX_FILE)
    write_index(path, entries, time_unit=time_units.pop() if time_units else "d")
    return path


def write_index(path: str, entries: list, time_unit: str = "d") -> None:
    """Write the index of a sequence: *entries*, one {time, step, file} per frame, in time order."""
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        json.dump({"fspmIndex": SPECIFICATION_VERSION, "timeUnit": time_unit, "frames": list(entries)}, file,
                  indent=1)
        file.write("\n")


def read_index(path: str) -> dict:
    """The index of a sequence (its frames' times, steps and files, the files' paths made absolute)."""
    with open(path, encoding="utf-8") as file:
        index = json.load(file)
    directory = os.path.dirname(os.path.abspath(path))
    for entry in index.get("frames", []):
        entry["path"] = os.path.join(directory, entry["file"])
    return index


def read_sequence(path: str):
    """The frames of the sequence whose index is *path*, one after the other."""
    for entry in read_index(path)["frames"]:
        yield read(entry["path"])
