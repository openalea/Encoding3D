"""
The encoding3d validator: the checks a file must pass to follow the specification, beyond being valid glTF (which
Khronos' glTF-Validator checks)::

    validate_file(path) -> Report        a .glb frame, or a sequence's scene.fspm.json or .fspm.zip (each frame, the
                                         parts they refer to, and the rules across frames)
    validate_bytes(data) -> Report       a frame's bytes (its parts checked when embedded, or found in *parts_folder*)

A Report lists its issues: errors (the file does not follow the specification) and warnings (it does, but something
is likely wrong or incomplete).
"""
from dataclasses import dataclass, field
import datetime
import json
import os

import numpy as np

from openalea.encoding3d import archive, schema as schemas, ucum, vocabulary
from openalea.encoding3d.codec import (DTYPES, EDGE_TYPE_ENUM, EXTENSION, FEATURES, METADATA, Z_UP_TO_Y_UP,
                                    from_bytes, frame_part_keys, read_part)
from openalea.encoding3d.glb import unpack
from openalea.encoding3d.model import BASE_SCALES, EDGE_TYPES, NO_ID, Operator, Template
from openalea.encoding3d.parts import PARTS_FOLDER, MissingPartError, content_key, part_file


@dataclass
class Issue:
    severity: str                   # "error" or "warning"
    where: str
    message: str

    def __str__(self):
        return f"{self.severity}: {self.where}: {self.message}"


@dataclass
class Report:
    name: str = ""
    issues: list = field(default_factory=list)

    def error(self, where: str, message: str) -> None:
        self.issues.append(Issue("error", where, message))

    def warning(self, where: str, message: str) -> None:
        self.issues.append(Issue("warning", where, message))

    @property
    def errors(self) -> list:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "Report", prefix: str = "") -> None:
        for issue in other.issues:
            self.issues.append(Issue(issue.severity, f"{prefix}{issue.where}", issue.message))

    def __str__(self):
        lines = [f"{self.name}: {len(self.errors)} error(s), {len(self.warnings)} warning(s)"]
        lines += [f"  {issue}" for issue in self.issues]
        return "\n".join(lines)


# ── One frame ────────────────────────────────────────────────────────────

def _jsonschema():
    """jsonschema, imported when a file is validated (the reading code, e.g. ParaView's reader, works without it)."""
    import jsonschema
    return jsonschema


def validate_bytes(data: bytes, name: str = "", parts_folder: str = None, checked_parts: dict = None) -> Report:
    """A frame's (or a part's) issues. The parts its instance sets use are checked too (once each across the calls
    sharing *checked_parts*): embedded, or in *parts_folder*/parts (a frame's folder; without one, the parts not
    embedded are not checked, a warning)."""
    report = Report(name)
    try:
        document, binary = unpack(data)
    except ValueError as error:
        report.error("file", str(error))
        return report
    if not _check_document(document, binary, report):
        return report
    try:
        frame = from_bytes(data, parts_folder=parts_folder)
    except (KeyError, ValueError, TypeError, IndexError) as error:
        report.error("file", f"cannot be read: {error}")
        return report
    _check_frame(frame, document, report)
    _check_part_file(data, document, frame, report)
    _check_instances(frame, report, {} if checked_parts is None else checked_parts)
    return report


# ── Shared parts and instances (specification §12) ───────────────────────

def _check_part_file(data: bytes, document: dict, frame, report) -> None:
    """A part's own rules: a template holds one data structure and no instances; an operator, no data structure and
    arrays of its shape; embedded parts keyed by their hash."""
    scene = document["extensions"][EXTENSION]
    for key, item in scene.get("parts", {}).items():
        if content_key(bytes(frame.parts.embedded[key])) != key:
            report.error(f"parts/{key}", "the embedded part's bytes do not hash to its key")
    described = scene.get("part")
    if described is None:
        return
    if scene.get("parts"):
        report.error("part", "a part embeds no other parts")
    if any(data_structure.instance_sets for data_structure in frame.data_structures):
        report.error("part", "a part holds no instance sets")
    if described["kind"] == "template":
        if len(frame.data_structures) != 1:
            report.error("part", f"a template holds one data structure, not {len(frame.data_structures)}")
        elif not frame.data_structures[0].meshes:
            report.warning("part", "a template without meshes draws nothing")
        return
    if frame.data_structures:
        report.error("part", "an operator holds no data structure")
    try:
        read_part(data)
    except (KeyError, ValueError, TypeError, IndexError) as error:
        report.error("part", f"the operator cannot be read: {error}")


def _resolved_part(frame, key: str, where: str, report, checked: dict):
    """The part *key* of *frame*, checked once (its file valid, its bytes hashing to its key); None when it is
    missing or invalid (reported once), or not checked (no folder)."""
    if key in checked:
        return checked[key]
    checked[key] = None
    if key not in frame.parts.embedded and frame.parts.folder is None:
        report.warning(where, f"part {key} not checked: the frame's folder is not known")
        return None
    try:
        data = frame.parts.bytes(key)
    except MissingPartError as error:
        report.error(where, str(error))
        return None
    if content_key(data) != key:
        report.error(where, f"part {key}: its bytes do not hash to its key")
        return None
    sub = validate_bytes(data, f"part {key}")
    report.extend(sub, prefix=f"part {key[:12]}: ")
    if not sub.ok:
        return None
    document = unpack(data)[0]
    if "part" not in document["extensions"][EXTENSION]:
        report.error(where, f"part {key}: not a part (no {EXTENSION}.part)")
        return None
    checked[key] = read_part(data, key=key)
    return checked[key]


def _check_instances(frame, report, checked: dict) -> None:
    for data_structure in frame.data_structures:
        sets = {entity_set.name: entity_set for entity_set in data_structure.entity_sets}
        names = [instance_set.name for instance_set in data_structure.instance_sets]
        if len(set(names)) != len(names):
            report.error(data_structure.id, "two instance sets have the same name")
        for instance_set in data_structure.instance_sets:
            _check_instance_set(frame, data_structure, sets, instance_set, report, checked)


def _check_instance_set(frame, data_structure, sets: dict, instance_set, report, checked: dict) -> None:
    where = f"{data_structure.id}/instances {instance_set.name}"
    columns, count = instance_set.columns, instance_set.count
    parts = [_resolved_part(frame, key, where, report, checked) for key in instance_set.parts]
    unknown = [number for number, key in enumerate(instance_set.parts) if key not in checked or checked[key] is None]

    def used(indices, kind, what):
        """Whether *indices* (into the parts, NO_ID: none) are in range and parts of *kind* (those resolved)."""
        indices = np.asarray(indices, dtype=np.int64)
        present = indices[indices != NO_ID] if what != "template" else indices
        if present.size and (present.min() < 0 or present.max() >= len(parts)):
            report.error(f"{where}/{what}", f"indices outside the set's {len(parts)} parts")
            return False
        for index in np.unique(present).tolist():
            if parts[index] is not None and not isinstance(parts[index], kind):
                report.error(f"{where}/{what}", f"part {index} is not {'a template' if kind is Template else 'an operator'}")
                return False
        return True

    if "template" not in columns:
        report.error(where, "no 'template' column")
        return
    templates = np.asarray(columns["template"])
    if templates.dtype != np.int64:
        report.error(f"{where}/template", f"indices are int64, not {templates.dtype}")
    templates_ok = used(templates, Template, "template")
    if instance_set.owners is not None:
        if instance_set.owners not in sets:
            report.error(where, f"owners '{instance_set.owners}' is not an entity set of '{data_structure.id}'")
        elif "owner" not in columns:
            report.error(where, f"no 'owner' column (the ids in '{instance_set.owners}' of the instances' owners)")
        elif frame.update is None:
            _check_references(f"{where}/owner", columns["owner"], set(sets[instance_set.owners].ids().tolist()), report,
                              allow_none=False)
    elif "owner" in columns:
        report.error(where, "an 'owner' column needs the set's 'owners' (the entity set its ids are in)")
    if "transform" in columns and not np.isfinite(columns["transform"]).all():
        report.error(f"{where}/transform", "transforms are finite")
    if "id" in columns:
        ids = np.asarray(columns["id"])
        if (ids < 0).any() or np.unique(ids).size != ids.size:
            report.error(f"{where}/id", "instance ids are non-negative and unique")
    _check_variables(where, instance_set, vocabulary.standard_names(), vocabulary.enums(), report)
    for derived in instance_set.derived:
        field_where = f"{where}/derived {derived.name}"
        if derived.name in columns:
            report.error(field_where, "a derived field has the name of a column of its instance set")
        for name in [derived.input] + [offset for offset in derived.offsets if offset is not None]:
            if name not in instance_set.vectors:
                report.error(field_where, f"no vector '{name}' in the instance set ({sorted(instance_set.vectors)})")
        if not np.isfinite(derived.weights).all():
            report.error(f"{field_where}/weight", "weights are finite")
        if not used(derived.operators, Operator, f"derived {derived.name}/operator") or not templates_ok or                 derived.input not in instance_set.vectors or unknown:
            continue
        try:
            ucum.dimension(derived.variable.unit)
        except ucum.UnitError as error:
            report.error(field_where, f"unit: {error}")
        rows_of = {}
        for index in np.unique(templates).tolist():
            try:
                rows_of[index] = parts[index].entity_set(derived.entity_set).count
            except KeyError:
                report.error(field_where, f"template {index} has no entity set '{derived.entity_set}'")
        if len(rows_of) != np.unique(templates).size:
            continue
        rows = np.array([rows_of[int(index)] for index in templates], dtype=np.int64)
        inputs = instance_set.vectors[derived.input].counts
        for term in range(derived.terms):
            operators = derived.operators[:, term]
            active = operators != NO_ID
            shapes = np.array([parts[int(index)].shape if index != NO_ID else (0, 0) for index in operators],
                              dtype=np.int64).reshape(-1, 2)
            wrong = active & ((shapes[:, 0] != rows) | (shapes[:, 1] != inputs))
            if wrong.any():
                first = int(np.flatnonzero(wrong)[0])
                report.error(field_where, f"{int(wrong.sum())} instance(s) whose operator's shape is not (their "
                                          f"template's '{derived.entity_set}' rows, their '{derived.input}' values), e.g. "
                                          f"instance {first}: {tuple(shapes[first])}, ({rows[first]}, {inputs[first]}) "
                                          "expected")
            offset = derived.offsets[term]
            if offset is not None and offset in instance_set.vectors:
                lengths = instance_set.vectors[offset].counts
                if ((lengths != 0) & ((lengths != rows) | ~active)).any():
                    report.error(field_where, f"offsets '{offset}' of term {term}: of length 0, or the template's "
                                              f"'{derived.entity_set}' rows for an instance with that term")


def _check_document(document: dict, binary: bytes, report: Report) -> bool:
    """The JSON structure: glTF essentials, FSPM_scene against its schema, tables and buffer views consistent.
    False when the frame cannot be decoded."""
    if document.get("asset", {}).get("version") != "2.0":
        report.error("asset", "glTF version 2.0 expected")
    used = document.get("extensionsUsed", [])
    for name in (EXTENSION, METADATA):
        if name not in used:
            report.error("extensionsUsed", f"must list {name}")
    if EXTENSION in document.get("extensionsRequired", []):
        report.warning("extensionsRequired", f"{EXTENSION} should not be required, so that any viewer opens the file")
    roots = [document.get("nodes", [])[index] for index in document.get("scenes", [{}])[0].get("nodes", [])
             if index < len(document.get("nodes", []))]
    if not any(node.get("name") == "fspm_scene" and node.get("matrix") == Z_UP_TO_Y_UP for node in roots):
        report.warning("scenes", "no root node fspm_scene turning the scene (z up) to glTF's y up: viewers will show it "
                                 "lying down")
    extensions = document.get("extensions", {})
    if EXTENSION not in extensions:
        report.error("extensions", f"no {EXTENSION} extension: not an encoding3d file")
        return False
    scene = extensions[EXTENSION]
    for error in _jsonschema().Draft202012Validator(schemas.load("fspm_scene")).iter_errors(scene):
        report.error(f"{EXTENSION}/{'/'.join(str(part) for part in error.absolute_path)}", error.message)
    metadata = extensions.get(METADATA)
    if metadata is None:
        report.error("extensions", f"no {METADATA} extension")
        return False
    views = document.get("bufferViews", [])
    for index, view in enumerate(views):
        if view.get("byteOffset", 0) + view["byteLength"] > len(binary):
            report.error(f"bufferViews/{index}", "extends beyond the binary chunk")
    tables = metadata.get("propertyTables", [])
    classes = metadata.get("schema", {}).get("classes", {})
    enums = metadata.get("schema", {}).get("enums", {})
    for index, table in enumerate(tables):
        where = f"propertyTables/{index}"
        if table.get("class") not in classes:
            report.error(where, f"class '{table.get('class')}' is not in the schema")
            continue
        properties = classes[table["class"]]["properties"]
        for name, stored in table.get("properties", {}).items():
            if name not in properties:
                report.error(f"{where}/{name}", "not a property of its class")
                continue
            _check_property_storage(f"{where}/{name}", properties[name], stored, table["count"], views, enums,
                                    report)
    referenced = []
    for data_structure in scene.get("dataStructures", []):
        referenced += [item["propertyTable"] for item in data_structure.get("entitySets", [])]
        referenced += [item["propertyTable"] for item in data_structure.get("relations", [])]
        if "scalars" in data_structure:
            referenced.append(data_structure["scalars"])
    referenced += [item["propertyTable"] for item in scene.get("mappings", [])]
    for index in referenced:
        if not 0 <= index < len(tables):
            report.error(EXTENSION, f"property table {index} does not exist")
    if len(set(referenced)) != len(referenced):
        report.error(EXTENSION, "a property table is used by several tables of the scene")
    return report.ok


def _check_property_storage(where, prop, stored, count, views, enums, report) -> None:
    def length(key):
        index = stored.get(key)
        if index is None or not 0 <= index < len(views):
            report.error(where, f"'{key}' is not a buffer view")
            return None
        if views[index].get("byteOffset", 0) % 8:
            report.error(where, f"buffer view {index} is not 8-byte aligned")
        return views[index]["byteLength"]

    kind = prop.get("type")
    if prop.get("extras", {}).get("FSPM_boolean") and (kind != "SCALAR" or prop.get("componentType") != "UINT8"
                                                       or prop.get("noData") != 255 or prop.get("array")):
        report.error(where, "a boolean column with missing values is UINT8 (0, 1) with noData 255")
    values_length = length("values")
    if values_length is None:
        return
    if kind == "SCALAR":
        if prop.get("componentType") not in DTYPES:
            report.error(where, f"component type {prop.get('componentType')} is not supported")
            return
        if prop.get("array") and "count" not in prop:
            report.error(where, "variable-length arrays are not part of encoding3d 0.1")
            return
        expected = count * prop.get("count", 1) * DTYPES[prop["componentType"]].itemsize
    elif kind == "BOOLEAN":
        expected = (count + 7) // 8
    elif kind == "ENUM":
        enum = enums.get(prop.get("enumType"))
        if enum is None:
            report.error(where, f"enum '{prop.get('enumType')}' is not in the schema")
            return
        expected = count * np.dtype(enum.get("valueType", "UINT16").lower()).itemsize
    elif kind == "STRING":
        offsets_length = length("stringOffsets")
        offset_size = np.dtype(stored.get("stringOffsetType", "UINT32").lower()).itemsize
        if offsets_length is not None and offsets_length != (count + 1) * offset_size:
            report.error(where, f"{offsets_length} bytes of string offsets, {(count + 1) * offset_size} expected")
        return
    else:
        report.error(where, f"property type {kind} is not part of encoding3d 0.1")
        return
    if values_length != expected:
        report.error(where, f"{values_length} bytes of values, {expected} expected for {count} rows")


def _check_frame(frame, document: dict, report: Report) -> None:
    standard_names, enums = vocabulary.standard_names(), vocabulary.enums()
    for data_structure in frame.data_structures:
        where = f"{data_structure.id}"
        sets = {entity_set.name: entity_set for entity_set in data_structure.entity_sets}
        if len(sets) != len(data_structure.entity_sets):
            report.error(where, "two entity sets have the same name")
        ids = {}
        for entity_set in data_structure.entity_sets:
            ids[entity_set.name] = _check_entity_set(data_structure, entity_set, report)
        for relation in data_structure.relations:
            if "id" in relation.columns:
                ids[f"relation {relation.name}"] = _check_entity_set(data_structure, relation, report)
        explicit = [values for name, values in ids.items()          # a grid's cells may have implicit ids
                    if not (data_structure.grid is not None and name == data_structure.grid.cells)]
        if explicit and sum(len(values) for values in explicit) != len(set().union(*explicit)):
            report.error(where, "ids are unique across the data structure's entity sets and relations")
        partial = frame.update is not None              # a partial frame refers to entities it does not hold
        _check_mtg(data_structure, sets, ids, report, partial=partial)
        for relation in data_structure.relations:
            for end, set_name in (("source", relation.source_set), ("target", relation.target_set)):
                if set_name not in ids:
                    if not partial:
                        report.error(f"{where}/{relation.name}", f"{end} set '{set_name}' does not exist")
                elif end not in relation.columns:
                    report.error(f"{where}/{relation.name}", f"no '{end}' column")
                elif not partial:
                    _check_references(f"{where}/{relation.name}/{end}", relation.columns[end], ids[set_name],
                                      report, allow_none=False)
        names = [relation.name for relation in data_structure.relations]
        if len(set(names)) != len(names):
            report.error(where, "two relations have the same name")
        for relation in data_structure.relations:
            if relation.name.startswith("bearer") and "relation" in relation.columns:
                unknown = set(relation.columns["relation"].tolist()) - set(enums["bearer_relation"])
                if unknown:
                    report.warning(f"{where}/{relation.name}/relation",
                                   f"bearer labels {sorted(unknown)}: expected {sorted(enums['bearer_relation'])}")
        _check_scales_and_labels(data_structure, report)
        for key in data_structure.extras:
            if key != key.lower():
                report.warning(f"{where}/extras", f"key '{key}': the platform's name, in lower case")
        if data_structure.grid is not None:
            _check_grid(data_structure, sets, report)
        elif data_structure.kind in ("regular_grid", "adaptive_grid"):
            report.error(where, f"a {data_structure.kind} needs a grid")
        tables = list(data_structure.entity_sets) + list(data_structure.relations)
        if data_structure.scalars is not None:
            tables.append(data_structure.scalars)
            if data_structure.scalars.count != 1:
                report.error(f"{where}/scalars", f"{data_structure.scalars.count} rows, 1 expected")
        for table in tables:
            _check_variables(f"{where}/{table.name}", table, standard_names, enums, report)
        _check_meshes(data_structure, document, report)
    data_structures = {data_structure.id: data_structure for data_structure in frame.data_structures}
    if len(data_structures) != len(frame.data_structures):
        report.error("dataStructures", "two data structures have the same id")
    if frame.update is not None:
        for (data_structure_id, set_name), removed in frame.update.removed.items():
            if (removed < 0).any():
                report.error(f"update/removed/{data_structure_id}/{set_name}", "ids are non-negative")
    for mapping in frame.mappings:
        if frame.update is not None:
            continue
        where = f"mapping {mapping.name}"
        for end, (data_structure_id, set_name) in (("source", mapping.source), ("target", mapping.target)):
            try:
                entity_set = data_structures[data_structure_id].entity_set(set_name)
            except KeyError:
                report.error(where, f"{end} {data_structure_id}/{set_name} does not exist")
                continue
            if end not in mapping.columns:
                report.error(where, f"no '{end}' column")
                continue
            _check_references(f"{where}/{end}", mapping.columns[end], set(entity_set.ids().tolist()), report,
                              allow_none=False)
        weight = mapping.columns.get("weight")
        if weight is None:
            report.error(where, "no 'weight' column")
        elif not (np.isfinite(weight).all() and (weight >= 0).all()):
            report.error(f"{where}/weight", "weights must be finite and non-negative")
        _check_variables(where, mapping, standard_names, enums, report)


def _check_entity_set(data_structure, entity_set, report) -> set:
    where = f"{data_structure.id}/{entity_set.name}"
    is_grid = data_structure.grid is not None and entity_set.name == data_structure.grid.cells
    if "id" not in entity_set.columns:
        if not is_grid:
            report.error(where, "no 'id' column (only a grid's cells may have implicit ids)")
        return set(range(entity_set.count))
    ids = entity_set.columns["id"]
    if ids.dtype != np.int64:
        report.error(f"{where}/id", f"ids are int64, not {ids.dtype}")
    if (ids < 0).any():
        report.error(f"{where}/id", "ids are non-negative")
    unique = set(ids.tolist())
    if len(unique) != ids.size:
        report.error(f"{where}/id", "ids are not unique")
    return unique


def _check_references(where, values, ids: set, report, allow_none: bool = True) -> None:
    values = np.asarray(values)
    if values.dtype != np.int64:
        report.error(where, f"ids are int64, not {values.dtype}")
    present = values[values != NO_ID] if allow_none else values
    missing = sorted(set(present.tolist()) - ids)
    if missing:
        report.error(where, f"{len(missing)} id(s) not in the referenced entity set, e.g. {missing[:5]}")


def _check_mtg(data_structure, sets: dict, ids: dict, report, partial: bool = False) -> None:
    """complex points to an entity of a coarser entity set; parent and edge_type agree; parents form no cycle. In a
    partial frame (*partial*), complex and parent may refer to entities it does not hold, and may be absent."""
    ranked = sorted((entity_set for entity_set in data_structure.entity_sets if entity_set.rank is not None),
                    key=lambda entity_set: entity_set.rank)
    for position, entity_set in enumerate(ranked):
        where = f"{data_structure.id}/{entity_set.name}"
        columns = entity_set.columns
        if partial:
            pass
        elif position > 0:
            coarser = ranked[position - 1]
            if "complex" not in columns:
                report.error(where, f"no 'complex' column (its entities belong to {coarser.name})")
            else:
                coarser_ids = set().union(*[ids[other.name] for other in ranked[:position]
                                            if other.rank < entity_set.rank])
                _check_references(f"{where}/complex", columns["complex"], coarser_ids, report)
                if (columns["complex"] == NO_ID).any():
                    report.warning(f"{where}/complex", "entities without a complex at the coarser scale")
        elif "complex" in columns and (columns["complex"] != NO_ID).any():
            report.error(f"{where}/complex", "the coarsest scale has no complex")
        if ("parent" in columns) != ("edge_type" in columns):
            report.error(where, "'parent' and 'edge_type' go together")
            continue
        if "parent" not in columns:
            continue
        parent, edge_type = columns["parent"], columns["edge_type"]
        if not partial:
            _check_references(f"{where}/parent", parent, ids[entity_set.name], report)
        unknown = set(edge_type.tolist()) - set(EDGE_TYPES)
        if unknown:
            report.error(f"{where}/edge_type", f"unknown values {sorted(unknown)}")
        if ((parent == NO_ID) != (edge_type == "none")).any():
            report.error(f"{where}/edge_type", "'none' exactly for the entities without a parent")
        if "id" in columns and not report.errors:
            row_of = {identifier: row for row, identifier in enumerate(columns["id"].tolist())}
            up = np.array([row_of.get(int(value), -1) for value in parent])
            current = np.arange(up.size)
            for _ in range(up.size + 1):
                current = np.where(current >= 0, up[np.maximum(current, 0)], -1)
                if (current < 0).all():
                    break
            else:
                report.error(f"{where}/parent", "the parents form a cycle")


def _check_scales_and_labels(data_structure, report) -> None:
    """Each entity set's scale and rank; its order column; the data structure's label map."""
    used = set()
    for entity_set in data_structure.entity_sets:
        where = f"{data_structure.id}/{entity_set.name}"
        if entity_set.scale in BASE_SCALES and entity_set.rank is not None \
                and entity_set.rank != BASE_SCALES.index(entity_set.scale) + 1:
            report.warning(where, f"rank {entity_set.rank}: the base scale {entity_set.scale}'s position is "
                                  f"{BASE_SCALES.index(entity_set.scale) + 1}")
        if "sibling_order" in entity_set.columns and (np.asarray(entity_set.columns["sibling_order"]) < 0).any():
            report.error(f"{where}/sibling_order", "positions among siblings are non-negative")
        if "label" in entity_set.columns:
            used |= {label for label in entity_set.columns["label"].tolist() if label is not None}
    vocabulary_labels = vocabulary.labels()
    for label, standard in data_structure.labels.items():
        if label not in used:
            report.warning(f"{data_structure.id}/labels", f"'{label}' is no entity's label")
        if standard not in vocabulary_labels:
            report.warning(f"{data_structure.id}/labels", f"'{standard}' is not a label of the vocabulary "
                                                          f"{vocabulary.version()}")


def _check_format(where, values, variable_format, report) -> None:
    """A text column's dates or times, as ISO 8601."""
    if np.asarray(values).dtype != object:
        report.error(where, f"format '{variable_format}' is for text columns")
        return
    parse = {"date": datetime.date.fromisoformat, "date-time": datetime.datetime.fromisoformat,
             "time": datetime.time.fromisoformat}[variable_format]
    bad = []
    for value in values:
        if value is None:
            continue
        try:
            parse(value)
        except ValueError:
            bad.append(value)
    if bad:
        report.error(where, f"{len(bad)} value(s) not ISO 8601 {variable_format}, e.g. {bad[:3]}")


def _check_grid(data_structure, sets: dict, report) -> None:
    grid, where = data_structure.grid, f"{data_structure.id}/grid"
    dimensions = len(grid.shape)
    for name in ("origin", "spacing", "axes", "periodic"):
        if len(getattr(grid, name)) != dimensions:
            report.error(where, f"{name} has {len(getattr(grid, name))} values, the grid {dimensions} dimensions")
    if grid.cells not in sets:
        report.error(where, f"cells '{grid.cells}' is not an entity set")
        return
    cells = sets[grid.cells]
    if grid.kind == "regular":
        if data_structure.kind != "regular_grid":
            report.error(where, f"a regular grid in a '{data_structure.kind}' data structure")
        if cells.count != int(np.prod(grid.shape)):
            report.error(where, f"{cells.count} cells, {int(np.prod(grid.shape))} expected")
        if "id" in cells.columns and not np.array_equal(cells.columns["id"], np.arange(cells.count)):
            report.error(f"{where}/{grid.cells}/id", "a regular grid's cell ids are their C-order index")
    else:
        if data_structure.kind != "adaptive_grid":
            report.error(where, f"an adaptive grid in a '{data_structure.kind}' data structure")
        for name in ("level", "index"):
            if name not in cells.columns:
                report.error(f"{where}/{grid.cells}", f"an adaptive grid's cells have a '{name}' column")
        if "level" in cells.columns and ((cells.columns["level"] < 0) | (cells.columns["level"] > grid.max_level)).any():
            report.error(f"{where}/{grid.cells}/level", f"levels between 0 and {grid.max_level}")
        if "index" in cells.columns and np.shape(cells.columns["index"])[1:] != (dimensions,):
            report.error(f"{where}/{grid.cells}/index", f"one index per dimension ({dimensions})")


def _check_variables(where, table, standard_names: dict, enums: dict, report) -> None:
    for name in table.columns:
        values = table.columns[name]
    for name in table.variable_names():
        if name not in table.variables:
            report.warning(f"{where}/{name}", "not declared: no unit, kind or role")
            continue
        variable = table.variables[name]
        try:
            ucum.dimension(variable.unit)
        except ucum.UnitError as error:
            report.error(f"{where}/{name}", f"unit: {error}")
            continue
        if variable.kind is not None and variable.kind not in enums["kind"]:
            report.error(f"{where}/{name}", f"kind '{variable.kind}' is not one of {sorted(enums['kind'])}")
        if variable.role not in enums["role"]:
            report.error(f"{where}/{name}", f"role '{variable.role}' is not one of {sorted(enums['role'])}")
        if variable.format is not None:
            _check_format(f"{where}/{name}", table.columns[name], variable.format, report)
        if variable.standard_name is None:
            continue
        entry = standard_names.get(variable.standard_name)
        if entry is None:
            report.error(f"{where}/{name}", f"standard name '{variable.standard_name}' is not in the vocabulary "
                                            f"{vocabulary.version()} (propose it, or leave it out)")
            continue
        if not ucum.convertible(variable.unit, entry["canonical_unit"]):
            report.error(f"{where}/{name}", f"unit '{variable.unit}' cannot be converted to "
                                            f"'{entry['canonical_unit']}', the unit of {variable.standard_name}")
        if variable.kind is not None and variable.kind != entry["kind"]:
            report.warning(f"{where}/{name}", f"kind '{variable.kind}', the vocabulary's is '{entry['kind']}'")


def _check_meshes(data_structure, document: dict, report) -> None:
    scene = document["extensions"][EXTENSION]
    entry = next(item for item in scene["dataStructures"] if item["id"] == data_structure.id)
    for mesh_entry, mesh in zip(entry.get("meshes", []), data_structure.meshes):
        where = f"{data_structure.id}/mesh {mesh.name}"
        primitives = document["meshes"][mesh_entry["mesh"]]["primitives"]
        if len(primitives) != 1:
            report.error(where, "one primitive per mesh")
        primitive = primitives[0]
        if primitive.get("mode", 4) != 4:
            report.error(where, "meshes are TRIANGLES (mode 4)")
        if mesh.indices is None and len(mesh.positions) % 3:
            report.error(where, f"{len(mesh.positions)} vertices without indices: not whole triangles")
        if mesh.indices is not None and (mesh.indices.size % 3 or (mesh.indices >= len(mesh.positions)).any()):
            report.error(where, "indices: not whole triangles, or beyond the vertices")
        for set_name, rows in mesh.feature_rows.items():
            count = data_structure.entity_set(set_name).count
            if ((rows < NO_ID) | (rows >= count)).any():
                report.error(f"{where}/{set_name}", f"feature rows outside the {count} rows of the entity set")
        flagged = {item["attribute"] for item in mesh_entry.get("display", [])}
        for attribute in primitive["attributes"]:
            if attribute.startswith("_") and not attribute.startswith("_FEATURE_ID_") and attribute not in flagged:
                report.error(f"{where}/{attribute}", "an application attribute not declared as a display copy")
        for item in mesh_entry.get("display", []):
            if item["attribute"] not in primitive["attributes"]:
                report.error(f"{where}/{item['attribute']}", "declared display copy missing from the primitive")
        features = primitive.get("extensions", {}).get(FEATURES, {}).get("featureIds", [])
        own = {set_entry["propertyTable"] for set_entry in entry.get("entitySets", [])}
        for feature in features:
            if feature.get("propertyTable") not in own:
                report.error(where, "feature IDs point to a property table of another data structure")


# ── Files and sequences ──────────────────────────────────────────────────

def _adaptive_cells(data_structure, entity_set):
    """{id: (level, index)} of an adaptive grid's leaf cells (the region each id names), None for any other set."""
    grid = data_structure.grid
    if grid is None or grid.kind != "adaptive" or entity_set.name != grid.cells or \
            "level" not in entity_set.columns or "index" not in entity_set.columns:
        return None
    levels = np.asarray(entity_set.columns["level"]).tolist()
    indices = np.asarray(entity_set.columns["index"]).reshape(len(levels), -1).tolist()
    return {identifier: (level, tuple(index)) for identifier, level, index
            in zip(entity_set.columns["id"].tolist(), levels, indices)}


def validate_file(path: str) -> Report:
    """Validate a .glb frame (and the parts it refers to, embedded or in parts/ next to it), or a sequence: its
    index, its folder or its .fspm.zip archive (each frame, each part once, and the rules across frames)."""
    path = os.fspath(path)
    if path.endswith(".json") or path.endswith(archive.ARCHIVE_SUFFIX) or os.path.isdir(path):
        return validate_sequence(archive.index_of(path))
    return validate_bytes(archive.read_bytes(path), name=path, parts_folder=os.path.dirname(os.path.abspath(path)))


def validate_sequence(index_path: str) -> Report:
    """A sequence's issues: *index_path* is its scene.fspm.json, its folder or its .fspm.zip archive (each frame,
    each part once, and the rules across frames)."""
    index_path = archive.index_of(index_path)
    report = Report(index_path)
    try:
        index = json.loads(archive.read_bytes(index_path).decode("utf-8"))
    except (OSError, ValueError) as error:
        report.error("index", f"cannot be read: {error}")
        return report
    for error in _jsonschema().Draft202012Validator(schemas.load("index")).iter_errors(index):
        report.error(f"index/{'/'.join(str(part) for part in error.absolute_path)}", error.message)
    if not report.ok:
        return report
    directory = os.path.dirname(os.path.abspath(index_path))
    times = [entry["time"] for entry in index["frames"]]
    if any(later < earlier for earlier, later in zip(times, times[1:])):
        report.error("index/frames", "frames are in time order")
    seen, gone, cells_of, checked_parts, referenced = {}, {}, {}, {}, set()
    listed = index.get("parts", {})
    for key, file_name in listed.items():
        if file_name != part_file(key):
            report.error(f"index/parts/{key}", f"listed as '{file_name}': a part's file is {part_file(key)}")
        elif not archive.exists(os.path.join(directory, file_name)):
            report.error(f"index/parts/{key}", f"{file_name} does not exist")
    for number, entry in enumerate(index["frames"]):
        path = os.path.join(directory, entry["file"])
        if not archive.exists(path):
            report.error(f"frames/{number}", f"{entry['file']} does not exist")
            continue
        data = archive.read_bytes(path)
        frame_report = validate_bytes(data, entry["file"], parts_folder=directory, checked_parts=checked_parts)
        report.extend(frame_report, prefix=f"{entry['file']}: ")
        if not frame_report.ok:
            continue
        frame = from_bytes(data, parts_folder=directory)
        referenced |= set(frame_part_keys(path)) - set(frame.parts.embedded)
        if frame.time != entry["time"] or frame.step != entry["step"]:
            report.error(entry["file"], "time or step differs from the index's")
        if frame.time_unit != index["timeUnit"]:
            report.error(entry["file"], f"time unit '{frame.time_unit}', the index's is '{index['timeUnit']}'")
        for data_structure in frame.data_structures:
            for entity_set in data_structure.entity_sets:
                if "id" not in entity_set.columns:
                    continue
                key = (data_structure.id, entity_set.name)
                current = set(entity_set.columns["id"].tolist())
                reused = current & gone.get(key, set())
                cells = _adaptive_cells(data_structure, entity_set)
                if cells is not None:           # a cell coarsened away and refined again is the same cell (§8)
                    known = cells_of.setdefault(key, {})
                    reused = {identifier for identifier in reused if known.get(identifier) != cells[identifier]}
                    known.update(cells)
                if reused:
                    report.error(f"{entry['file']}: {data_structure.id}/{entity_set.name}/id",
                                 f"{len(reused)} id(s) reused after their entity disappeared, e.g. "
                                 f"{sorted(reused)[:5]}")
                gone[key] = gone.get(key, set()) | (seen.get(key, set()) - current)
                seen[key] = current
    if listed:
        for key in sorted(referenced - set(listed)):
            report.warning("index/parts", f"part {key}, which frames use, is not listed")
        for key in sorted(set(listed) - referenced):
            report.warning("index/parts", f"part {key} is listed but no frame uses it (encoding3d prune removes it)")
    stray = [name for name in archive.listing(os.path.join(directory, PARTS_FOLDER))
             if name.endswith(".glb") and name[:-4] not in referenced and name[:-4] not in listed]
    if stray:
        report.warning(PARTS_FOLDER, f"{len(stray)} part file(s) no frame uses, e.g. {stray[:2]} (encoding3d prune "
                                     "removes them)")
    return report
