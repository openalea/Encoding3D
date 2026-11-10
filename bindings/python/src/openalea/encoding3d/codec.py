"""
Reading and writing encoding3d frames as GLB files, and sequences of frames with their index::

    write(path, frame)           a Frame to a .glb file          to_bytes(frame) -> bytes
    read(path) -> Frame          a .glb file to a Frame          from_bytes(data) -> Frame
    write_sequence(directory, frames)    one .glb per frame and the index scene.fspm.json
    read_index(path) -> dict             the index: its frames' times, steps and files

Shared parts (specification §12: the templates and operators of instance sets) are written once each, under
parts/<key>.glb next to the frames (*key*: the SHA-256 of the part's bytes), or embedded in the frame
(write(path, frame, embed_parts=True)); part_bytes(part) and read_part(data) encode and decode one. A path inside a
.fspm.zip archive ("run.fspm.zip/frame_000003.glb", openalea.encoding3d.archive) is read as the folder's file.

Tables are EXT_structural_metadata property tables (one class per table), meshes carry EXT_mesh_features feature
IDs, and the FSPM_scene root extension holds what these two cannot: data structures, entity sets and their ranks,
relations, grids, mappings, the frame's time, and the variables' units, standard names, kinds and roles.
"""
import itertools
import json
import os
import re

import numpy as np

from openalea.encoding3d import SPECIFICATION_VERSION, archive
from openalea.encoding3d.glb import BufferBuilder, pack, unpack, view_bytes
from openalea.encoding3d.glb import write as write_glb
from openalea.encoding3d.model import (DataStructure, DerivedField, EDGE_TYPES, ENUM_COLUMNS, EntitySet, Frame, Grid,
                           ID_COLUMNS, InstanceSet, LazyColumns, LazyList, Mapping, Mesh, NO_ID, Operator, Ragged,
                           Relation, Table, Template, Update, Variable, _as_column)
from openalea.encoding3d.parts import PARTS_FOLDER, Parts, content_key, part_file

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

def to_bytes(frame: Frame, embed_parts: bool = False) -> bytes:
    """The GLB file of *frame*; *embed_parts*: the parts its instance sets use in it (one self-contained file), else
    referred to by key (parts/<key>.glb, written by write)."""
    document, buffers, _ = _encode(frame, embed_parts=embed_parts)
    return pack(document, buffers)


def _encode(frame: Frame, embed_parts: bool = False, part=None) -> tuple:
    """(the GLB file of *frame*: its JSON document and its binary buffer (a BufferBuilder, its arrays not copied:
    glb.pack gives the bytes, glb.write writes them), {key: the part, its bytes when encoded by this call, or its key
    for a part read from a file} of the parts its instance sets use). *part*: the frame is a part's file, its
    FSPM_scene.part this entry (a function of the buffers for an operator's arrays)."""
    buffers = BufferBuilder()
    used_parts = {}
    schema = {"id": "fspm_scene", "classes": {}, "enums": {
        EDGE_TYPE_ENUM: {"valueType": "UINT8", "values": [{"name": name, "value": value}
                                                         for value, name in enumerate(EDGE_TYPES)]}}}
    tables, variables = [], {}
    document = {"asset": {"version": "2.0", "generator": f"encoding3d {SPECIFICATION_VERSION}"},
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
        if data_structure.instance_sets:
            entry["instanceSets"] = [_instance_set_entry(instance_set, data_structure, add_table, used_parts)
                                     for instance_set in data_structure.instance_sets]
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
    if part is not None:
        scene["part"] = part(buffers) if callable(part) else dict(part)
    if embed_parts and used_parts:
        scene["parts"] = {key: {"bufferView": buffers.add(_part_data(reference, frame))}
                          for key, reference in sorted(used_parts.items())}
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
    if buffers.views:
        # the buffer holds the chunk's padding to 8 bytes: glTF-Validator warns of more than 3 bytes beyond it
        document["buffers"] = [{"byteLength": buffers.pad(8)}]
        document["bufferViews"] = buffers.views
    return document, buffers, used_parts


def write(path: str, frame: Frame, embed_parts: bool = False) -> list:
    """Write *frame* to the GLB file *path*; the keys of the parts its instance sets use. The parts go to
    parts/<key>.glb next to it, each written once (a file already there is its content: its name is its hash); with
    *embed_parts*, into the frame instead (one self-contained file)."""
    document, buffers, used_parts = _encode(frame, embed_parts=embed_parts)
    if not embed_parts:
        write_parts(os.path.dirname(os.path.abspath(path)), used_parts, frame)
    with open(path, "wb") as file:                      # the arrays written from their memory: no copy of the binary
        write_glb(file, document, buffers)
    return sorted(used_parts)


def write_parts(folder: str, used_parts: dict, frame: Frame = None) -> list:
    """Write each part of *used_parts* ({key: part, or key}) not yet in *folder*/parts; the keys written. A part
    given by its key (read from a file) is copied from where *frame* was read."""
    written = []
    for key, reference in sorted(used_parts.items()):
        target = os.path.join(folder, PARTS_FOLDER, f"{key}.glb")
        if os.path.exists(target):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temporary = f"{target}.{os.getpid()}.part"
        with open(temporary, "wb") as file:
            file.write(_part_data(reference, frame))
        os.replace(temporary, target)                   # a reader never sees half a part
        written.append(key)
    return written


def _part_data(reference, frame: Frame = None) -> bytes:
    if isinstance(reference, (bytes, bytearray, memoryview)):
        return bytes(reference)
    if isinstance(reference, str):
        if frame is None or frame.parts is None:
            from openalea.encoding3d.parts import MissingPartError
            raise MissingPartError(reference, ["the frame was not read from a file"])
        return frame.parts.bytes(reference)
    return part_bytes(reference)


def _key_of(reference) -> str:
    if isinstance(reference, str):
        return reference
    if not isinstance(reference, (Template, Operator)):
        raise TypeError(f"an instance set's parts are Templates, Operators or their keys, not {type(reference)}")
    return reference.key


def part_bytes(part) -> bytes:
    """The GLB file of a shared part: a Template (a frame of one data structure, "template", its meshes and entity
    sets) or an Operator (a frame of no data structure, the operator's arrays in its binary chunk); FSPM_scene.part
    says which (specification §12.1)."""
    if isinstance(part, Template):
        return pack(*_encode(Frame(data_structures=[part.data_structure()]), part={"kind": "template"})[:2])
    if not isinstance(part, Operator):
        raise TypeError(f"a part is a Template or an Operator, not {type(part)}")

    def entry(buffers):
        described = {"kind": "operator", "format": part.format, "rows": part.shape[0], "columns": part.shape[1]}

        def sparse(triple):
            return {"indptr": buffers.add(triple[0].astype(np.int64)),
                    "indices": buffers.add(triple[1].astype(np.int64)),
                    "values": buffers.add(triple[2].astype(np.float64))}
        if part.format == "dense":
            described["values"] = buffers.add(np.ascontiguousarray(part.values, dtype=np.float64))
        elif part.format == "csr":
            described.update(sparse((part.indptr, part.indices, part.values)))
        else:
            described["system"], described["rightHandSide"] = sparse(part.system), sparse(part.right_hand_side)
        return described
    return pack(*_encode(Frame(), part=entry)[:2])


def _instance_set_entry(instance_set: InstanceSet, data_structure: DataStructure, add_table, used_parts: dict) -> dict:
    """The FSPM_scene entry of an instance set (specification §12.2), its tables added: the instance table (its
    columns, each vector's <name>__count, each derived field's <name>__operator and <name>__weight) and one table per
    vector (its values, the instances' one after the other)."""
    _check_identifier(instance_set.name, "instance set name")
    where = f"instance set '{instance_set.name}' of '{data_structure.id}'"
    count = instance_set.count
    keys = []
    for reference in instance_set.parts:
        if isinstance(reference, (Template, Operator)) and getattr(reference, "_key", None) is None:
            data = part_bytes(reference)                 # its key taken now: its bytes kept for this write
            reference._key = content_key(data)
            used_parts.setdefault(reference._key, data)
        key = _key_of(reference)
        used_parts.setdefault(key, reference)
        keys.append(key)
    if "template" not in instance_set.columns:
        raise ValueError(f"{where}: no 'template' column (each instance's index in its parts)")
    columns = dict(instance_set.columns)
    entry = {"name": instance_set.name, "parts": keys}
    if instance_set.owners is not None:
        entry["owners"] = instance_set.owners
    vectors = []
    for name, ragged in instance_set.vectors.items():
        _check_identifier(name, f"vector of {where}")
        if not isinstance(ragged, Ragged):
            ragged = Ragged.of(ragged)
        if len(ragged) != count:
            raise ValueError(f"{where}: vector '{name}' has {len(ragged)} instances, the set {count}")
        columns[f"{name}__count"] = ragged.counts
        vectors.append({"name": name, "propertyTable": add_table(Table(name, columns={"values": ragged.values}),
                                                                 f"{data_structure.id}__{instance_set.name}__{name}")})
    derived_fields = []
    for derived in instance_set.derived:
        _check_identifier(derived.name, f"derived field of {where}")
        if derived.operators.shape[0] != count:
            raise ValueError(f"{where}: derived field '{derived.name}' has {derived.operators.shape[0]} rows of "
                             f"operators, the set {count} instances")
        if derived.input not in instance_set.vectors:
            raise ValueError(f"{where}: derived field '{derived.name}' applies to vector '{derived.input}', which "
                             f"the set does not have ({sorted(instance_set.vectors)})")
        single = derived.terms == 1
        columns[f"{derived.name}__operator"] = derived.operators[:, 0] if single else derived.operators
        columns[f"{derived.name}__weight"] = derived.weights[:, 0] if single else derived.weights
        item = {"name": derived.name, "entitySet": derived.entity_set, "input": derived.input,
                "terms": derived.terms, "variable": _declaration_json(derived.variable)}
        if any(offset is not None for offset in derived.offsets):
            item["offsets"] = list(derived.offsets)
        if derived.variable.description:
            item["description"] = derived.variable.description
        derived_fields.append(item)
    entry["propertyTable"] = add_table(Table(instance_set.name, columns=columns, variables=instance_set.variables),
                                       f"{data_structure.id}__{instance_set.name}")
    if vectors:
        entry["vectors"] = vectors
    if derived_fields:
        entry["derivedFields"] = derived_fields
    return entry


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

def from_bytes(data: bytes, parts_folder: str = None) -> Frame:
    """The Frame of a GLB file's bytes; *parts_folder*: the folder its parts/ are in (the file's folder)."""
    document, binary = unpack(data)
    return _frame_of(document, binary, lazy=False, parts_folder=parts_folder)


def _frame_of(document: dict, binary, lazy: bool, parts_folder: str = None) -> Frame:
    extensions = document.get("extensions", {})
    if EXTENSION not in extensions:
        raise ValueError(f"not an encoding3d file: no {EXTENSION} extension")
    scene, metadata = extensions[EXTENSION], extensions.get(METADATA, {"schema": {}, "propertyTables": []})
    variables = scene.get("variables", {})

    def table(index: int, kind, **fields):
        description = metadata["propertyTables"][index]
        class_id = description["class"]
        columns, declarations = _decode_table(document, binary, description, metadata["schema"], variables, lazy)
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
        meshes = [(lambda mesh_entry=mesh_entry, data_structure=data_structure, tables=tables:
                   _decode_mesh(document, binary, mesh_entry, tables, data_structure))
                  for mesh_entry in entry.get("meshes", [])]
        data_structure.meshes = LazyList(meshes) if lazy else [mesh() for mesh in meshes]
        data_structure.instance_sets = [_decode_instance_set(document, binary, metadata, variables, item)
                                        for item in entry.get("instanceSets", [])]
        frame.data_structures.append(data_structure)
    for entry in scene.get("mappings", []):
        frame.mappings.append(table(entry["propertyTable"], Mapping,
                                    source=(entry["source"]["dataStructure"], entry["source"]["entitySet"]),
                                    target=(entry["target"]["dataStructure"], entry["target"]["entitySet"]),
                                    method=entry.get("method")))
    if "update" in scene:
        update = scene["update"]
        frame.update = Update(participant=update["participant"], removed={
            (item["dataStructure"], item["entitySet"]): np.asarray(table(item["propertyTable"], Table).columns["id"])
            for item in update.get("removed", [])})
    frame.parts = Parts({key: view_bytes(document, binary, item["bufferView"])
                         for key, item in scene.get("parts", {}).items()}, parts_folder)
    unknown_extensions = {name: value for name, value in extensions.items()
                          if name not in (METADATA, EXTENSION, FEATURES)}
    if unknown_extensions:
        frame.unknown["extensions"] = unknown_extensions
    if "extras" in document:
        frame.unknown["extras"] = document["extras"]
    return frame


def read(path: str, lazy: bool = False) -> Frame:
    """The Frame of the GLB file *path* (in a folder, or in a .fspm.zip archive: "run.fspm.zip/frame_000003.glb").
    *lazy*: the file is mapped in memory and only its JSON parsed; each column (LazyColumns) and each mesh (LazyList)
    is decoded when first read, so that a reader using a few columns of a large frame decodes only those. A lazy
    frame holds the file open until frame.close() (or the end of a with block). Its parts are found by key
    (frame.part): embedded, or in parts/ next to it."""
    folder = os.path.dirname(os.path.abspath(path))
    if archive.split(path) is not None:                 # in an archive: its member's bytes (decoded lazily if asked)
        data = archive.read_bytes(path)
        document, binary = unpack(memoryview(data) if lazy else data)
        frame = _frame_of(document, binary, lazy=lazy, parts_folder=folder)
        frame.path = path
        return frame
    if not lazy:
        with open(path, "rb") as file:
            frame = from_bytes(file.read(), parts_folder=folder)
        frame.path = path
        return frame
    import mmap
    with open(path, "rb") as file:
        mapped = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ)
    document, binary = unpack(memoryview(mapped))
    frame = _frame_of(document, binary, lazy=True, parts_folder=folder)
    frame._source = (mapped, binary)
    frame.path = path
    return frame


def read_part(data: bytes, key: str = None):
    """The Template or Operator of a part's GLB bytes (specification §12.1); *key*, when given, checked against the
    bytes' hash."""
    actual = content_key(bytes(data))
    if key is not None and key != actual:
        raise ValueError(f"part {key}: its bytes hash to {actual} (the file is not the part its name says)")
    document, binary = unpack(data)
    scene = document.get("extensions", {}).get(EXTENSION, {})
    described = scene.get("part")
    if described is None:
        raise ValueError(f"part {key or actual}: not a part (no {EXTENSION}.part)")
    if described.get("kind") == "template":
        frame = _frame_of(document, binary, lazy=False)
        if len(frame.data_structures) != 1:
            raise ValueError(f"part {key or actual}: a template holds one data structure")
        held = frame.data_structures[0]
        part = Template(entity_sets=held.entity_sets, meshes=held.meshes, relations=held.relations, kind=held.kind,
                        labels=held.labels, extras=held.extras)
    elif described.get("kind") == "operator":
        def array(index, dtype):
            return np.frombuffer(view_bytes(document, binary, index), dtype=np.dtype(dtype).newbyteorder("<")) \
                .astype(dtype)

        def sparse(item):
            return array(item["indptr"], np.int64), array(item["indices"], np.int64), array(item["values"], np.float64)
        shape = (described["rows"], described["columns"])
        if described["format"] == "dense":
            part = Operator("dense", shape, values=array(described["values"], np.float64))
        elif described["format"] == "csr":
            indptr, indices, values = sparse(described)
            part = Operator("csr", shape, values=values, indptr=indptr, indices=indices)
        else:
            part = Operator("solve", shape, system=sparse(described["system"]),
                            right_hand_side=sparse(described["rightHandSide"]))
    else:
        raise ValueError(f"part {key or actual}: kind '{described.get('kind')}' is not template or operator")
    part._key = actual
    return part


def _decode_instance_set(document: dict, binary, metadata: dict, variables: dict, item: dict) -> InstanceSet:
    """An instance set (specification §12.2): its own columns, its vectors (Ragged) and derived fields; its parts by
    key (Frame.part finds them)."""
    def table(index):
        description = metadata["propertyTables"][index]
        return _decode_table(document, binary, description, metadata["schema"], variables)

    columns, declarations = table(item["propertyTable"])
    vectors = {}
    for vector in item.get("vectors", []):
        values = table(vector["propertyTable"])[0]["values"]
        vectors[vector["name"]] = Ragged(values, columns.pop(f"{vector['name']}__count"))
    derived = []
    for field_entry in item.get("derivedFields", []):
        name = field_entry["name"]
        variable = _variable_of(field_entry.get("variable", {}), field_entry.get("description"))
        derived.append(DerivedField(name=name, entity_set=field_entry["entitySet"], input=field_entry["input"],
                                    operators=columns.pop(f"{name}__operator"),
                                    weights=columns.pop(f"{name}__weight"),
                                    offsets=tuple(field_entry.get("offsets", ())), variable=variable))
    return InstanceSet(name=item["name"], columns=columns,
                       variables={name: value for name, value in declarations.items() if name in columns},
                       owners=item.get("owners"), parts=list(item.get("parts", [])), vectors=vectors, derived=derived)


def _decode_table(document: dict, binary: bytes, description: dict, schema: dict, variables: dict,
                  lazy: bool = False) -> tuple:
    """(columns, declarations) of a property table; *lazy*: the columns a LazyColumns, each decoded when first read."""
    class_id = description["class"]
    count = description["count"]
    if lazy:
        columns = LazyColumns({name: (lambda name=name, stored=stored: _checked(
            name, _decode_column(document, binary, schema, class_id, name, stored, count)))
            for name, stored in description["properties"].items()}, count)
    else:
        columns = {name: _decode_column(document, binary, schema, class_id, name, stored, count)
                   for name, stored in description["properties"].items()}
    return columns, _decode_declarations(schema, class_id, description, variables)


def _checked(name: str, column):
    """A column decoded lazily, as a table checks it (ids int64)."""
    column = _as_column(name, column)
    if name in ID_COLUMNS and column.dtype.kind in "iu" and not np.ma.isMaskedArray(column):
        column = column.astype(np.int64)
    return column


def _decode_declarations(schema: dict, class_id: str, description: dict, variables: dict) -> dict:
    properties = schema["classes"][class_id]["properties"]
    declarations = {}
    for name in description["properties"]:
        prop = properties[name]
        declared = variables.get(class_id, {}).get(name)
        if declared is not None or "description" in prop:
            declarations[name] = _variable_of(declared or {}, prop.get("description"))
    return declarations


def _variable_of(declared: dict, description: str = None) -> Variable:
    return Variable(unit=declared.get("unit", "1"), standard_name=declared.get("standardName"),
                    kind=declared.get("kind"), role=declared.get("role", "state"), description=description,
                    minimum=declared.get("minimum"), maximum=declared.get("maximum"),
                    references=tuple(declared.get("references", ())), doi=tuple(declared.get("doi", ())),
                    format=declared.get("format"))


def _decode_column(document: dict, binary, schema: dict, class_id: str, name: str, stored: dict, count: int):
    """One column of a property table, decoded from the binary chunk (a copy, not a view of it)."""
    prop = schema["classes"][class_id]["properties"][name]
    raw = view_bytes(document, binary, stored["values"])
    if prop["type"] == "ENUM":
        enum = schema["enums"][prop["enumType"]]
        codes = np.frombuffer(raw, dtype=enum.get("valueType", "UINT16").lower(), count=count)
        values = np.array([item["value"] for item in enum["values"]], dtype=np.int64)
        names = np.empty(int(values.max()) + 1 if values.size else 0, dtype=object)
        names[values] = [item["name"] for item in enum["values"]]
        return names[codes.astype(np.int64)] if count else np.zeros(0, dtype=object)
    if prop["type"] == "STRING":
        offset_type = stored.get("stringOffsetType", "UINT32").lower()
        offsets = np.frombuffer(view_bytes(document, binary, stored["stringOffsets"]), dtype=offset_type,
                                count=count + 1)
        raw = bytes(raw)
        column = np.array([raw[offsets[i]:offsets[i + 1]].decode("utf-8") for i in range(count)], dtype=object)
        if "noData" in prop:                                 # missing text
            column = np.array([None if value == prop["noData"] else value for value in column], dtype=object)
        return column
    if prop["type"] == "BOOLEAN":
        return np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder="little", count=count).astype(bool)
    if prop["type"] != "SCALAR":
        raise ValueError(f"'{class_id}.{name}': property type {prop['type']} is not part of encoding3d")
    dtype = DTYPES[prop["componentType"]]
    width = prop.get("count", 1) if prop.get("array") else 1
    if prop.get("array") and "count" not in prop:
        raise ValueError(f"'{class_id}.{name}': variable-length arrays are not part of encoding3d")
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
        return np.ma.MaskedArray(column == 1, mask=missing) if missing.any() else column == 1
    if dtype.kind in "iu" and "noData" in prop and name not in ("complex", "parent"):   # missing integers
        missing = column == prop["noData"]
        if missing.any():
            return np.ma.MaskedArray(column, mask=missing)
    return column


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
        display[item["variable"]] = _accessor_array(document, binary, attributes[item["attribute"]]).copy()
        if item.get("entitySet") is not None:
            sources[item["variable"]] = item["entitySet"]
    indices = (_accessor_array(document, binary, primitive["indices"]).astype(np.int64)
               if "indices" in primitive else None)
    return Mesh(name=mesh_entry["name"], positions=positions, feature_rows=feature_rows, indices=indices,
                display=display, display_sources=sources)


# ── Sequences ────────────────────────────────────────────────────────────

def write_sequence(directory: str, frames, name: str = "frame", embed_parts: bool = False) -> str:
    """Write *frames* to *directory*, one GLB each (name_000000.glb, ...), the parts they use once each (parts/), and
    their index; the index's path."""
    os.makedirs(directory, exist_ok=True)
    entries, time_units, keys = [], set(), set()
    for number, frame in enumerate(frames):
        file_name = f"{name}_{number:06d}.glb"
        if not embed_parts:
            keys |= set(write(os.path.join(directory, file_name), frame))
        else:
            write(os.path.join(directory, file_name), frame, embed_parts=True)
        entries.append({"time": float(frame.time), "step": int(frame.step), "file": file_name})
        time_units.add(frame.time_unit)
    if len(time_units) > 1:
        raise ValueError(f"the frames' times are in several units: {sorted(time_units)}")
    path = os.path.join(directory, INDEX_FILE)
    write_index(path, entries, time_unit=time_units.pop() if time_units else "d", parts=sorted(keys))
    return path


def write_index(path: str, entries: list, time_unit: str = "d", parts=()) -> None:
    """Write the index of a sequence: *entries*, one {time, step, file} per frame, in time order; *parts*: the keys
    of the parts its frames use (listed as parts/<key>.glb)."""
    index = {"fspmIndex": SPECIFICATION_VERSION, "timeUnit": time_unit, "frames": list(entries)}
    if parts:
        index["parts"] = {key: part_file(key) for key in sorted(parts)}
    _write_json(path, index)


def _write_json(path: str, value: dict) -> None:
    temporary = f"{path}.{os.getpid()}.part"
    with open(temporary, "w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, indent=1)
        file.write("\n")
    os.replace(temporary, path)                         # a reader never sees half an index


def rewrite_index_parts(path: str, parts) -> None:
    """The index *path* listing *parts* (keys) as its parts, its frames unchanged."""
    with open(path, encoding="utf-8") as file:
        index = json.load(file)
    index.pop("parts", None)
    if parts:
        index["parts"] = {key: part_file(key) for key in sorted(parts)}
    _write_json(path, index)


def read_index(path: str) -> dict:
    """The index of a sequence (its frames' times, steps and files, the files' paths made absolute): *path* its
    scene.fspm.json, its folder, or a .fspm.zip archive."""
    path = archive.index_of(path)
    index = json.loads(archive.read_bytes(path).decode("utf-8"))
    directory = os.path.dirname(os.path.abspath(path))
    for entry in index.get("frames", []):
        entry["path"] = os.path.join(directory, entry["file"])
    return index


def read_sequence(path: str):
    """The frames of the sequence whose index is *path* (or its folder, or its archive), one after the other."""
    for entry in read_index(path)["frames"]:
        yield read(entry["path"])


def frame_part_keys(path: str) -> list:
    """The keys of the parts the frame *path* refers to (its instance sets'), from its JSON alone."""
    from openalea.encoding3d.glb import read_document
    scene = read_document(path).get("extensions", {}).get(EXTENSION, {})
    return sorted({key for entry in scene.get("dataStructures", []) for instance_set in entry.get("instanceSets", [])
                   for key in instance_set.get("parts", [])})
