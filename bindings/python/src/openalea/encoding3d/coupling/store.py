"""
The session's structure, kept by the coordinator: per data structure and entity set, the entities (their ids and
topology, and which participant created each), and the values each participant provided. Updates are merged into
it, checked against the participants' rights; each participant's inputs are read from it, converted.
"""
import numpy as np

from openalea.encoding3d.coupling.messages import CouplingError, ID_COUNT
from openalea.encoding3d.model import (BASE_SCALES, NO_ID, DataStructure, EntitySet, Frame, Update, Variable)

TOPOLOGY = ("label", "complex", "parent", "edge_type", "sibling_order")


class _Column:
    """A provider's values on an entity set's rows, with the rows it has given a value (*present*)."""

    def __init__(self, values: np.ndarray, size: int):
        values = np.asarray(values)
        if values.dtype.kind in "OUS":
            dtype = object
        elif values.dtype.kind == "b":
            dtype = bool
        elif values.dtype.kind in "iu":
            dtype = np.int64
        else:
            dtype = np.float64
        width = values.shape[1:] if values.ndim > 1 else ()
        self.values = np.zeros((size,) + width, dtype=dtype)
        if dtype == np.float64:
            self.values[:] = np.nan
        self.present = np.zeros(size, dtype=bool)

    def place(self, rows: np.ndarray, values) -> None:
        mask = np.ma.getmaskarray(values) if np.ma.isMaskedArray(values) else None
        data = np.ma.getdata(values) if mask is not None else np.asarray(values)
        if mask is not None and mask.ndim > 1:
            mask = mask.any(axis=tuple(range(1, mask.ndim)))
        if self.values.dtype == np.int64 and data.dtype.kind == "f":
            self.values = self.values.astype(np.float64)        # an integer column now holding floats
        self.values[rows] = data
        self.present[rows] = True if mask is None else ~mask

    def keep(self, keep: np.ndarray) -> None:
        self.values, self.present = self.values[keep], self.present[keep]

    def grow(self, count: int) -> None:
        extra = np.zeros((count,) + self.values.shape[1:], dtype=self.values.dtype)
        if self.values.dtype == np.float64:
            extra[:] = np.nan
        self.values = np.concatenate([self.values, extra])
        self.present = np.concatenate([self.present, np.zeros(count, dtype=bool)])


class EntitySetStore:
    """An entity set's entities (ids, topology, creators) and the values the participants provided on them."""

    def __init__(self, data_structure: str, name: str, rank):
        self.data_structure, self.name, self.rank = data_structure, name, rank
        self.ids = np.zeros(0, dtype=np.int64)
        self._sorted = None                                # (ids sorted, their rows): the lookups by id
        self.topology = {"label": np.zeros(0, dtype=object), "complex": np.zeros(0, dtype=np.int64),
                         "parent": np.zeros(0, dtype=np.int64), "edge_type": np.zeros(0, dtype=object),
                         "sibling_order": np.zeros(0, dtype=np.int64)}
        self.creator = np.zeros(0, dtype=object)
        self.columns = {}                                  # (participant, variable): _Column
        self.declarations = {}                             # (participant, variable): Variable

    def __len__(self):
        return self.ids.size

    def _index(self) -> tuple:
        if self._sorted is None:
            order = np.argsort(self.ids, kind="stable")
            self._sorted = (self.ids[order], order)
        return self._sorted

    def rows(self, ids, strict: bool = True) -> np.ndarray:
        """The rows of *ids* (-1 for an id not here; KeyError if *strict*)."""
        ids = np.asarray(ids, dtype=np.int64).reshape(-1)
        keys, order = self._index()
        if keys.size == 0:
            found, rows = np.zeros(ids.size, dtype=bool), np.full(ids.size, -1, dtype=np.int64)
        else:
            position = np.minimum(np.searchsorted(keys, ids), keys.size - 1)
            found = keys[position] == ids
            rows = np.where(found, order[position], -1)
        if strict and not found.all():
            raise KeyError(f"ids not in {self.data_structure}/{self.name}: {ids[~found][:5].tolist()}")
        return rows

    def contains(self, ids) -> np.ndarray:
        return self.rows(ids, strict=False) >= 0

    def add(self, ids: np.ndarray, topology: dict, creator: str) -> None:
        count = ids.size
        self.ids = np.concatenate([self.ids, ids])
        for name, default in (("label", self.name), ("complex", NO_ID), ("parent", NO_ID), ("edge_type", "none"),
                              ("sibling_order", NO_ID)):        # an entity without a label: its entity set's name
            values = topology.get(name)
            column = self.topology[name]
            added = np.full(count, default, dtype=column.dtype) if values is None else np.asarray(values,
                                                                                                    dtype=column.dtype)
            self.topology[name] = np.concatenate([column, added])
        self.creator = np.concatenate([self.creator, np.full(count, creator, dtype=object)])
        for column in self.columns.values():
            column.grow(count)
        self._sorted = None

    def remove(self, ids) -> None:
        keep = ~np.isin(self.ids, np.asarray(list(ids), dtype=np.int64))
        self.ids = self.ids[keep]
        for name in self.topology:
            self.topology[name] = self.topology[name][keep]
        self.creator = self.creator[keep]
        for column in self.columns.values():
            column.keep(keep)
        self._sorted = None

    def place(self, participant: str, name: str, rows: np.ndarray, values, variable) -> None:
        key = (participant, name)
        if key not in self.columns:
            self.columns[key] = _Column(np.ma.getdata(values) if np.ma.isMaskedArray(values) else values,
                                        self.ids.size)
        if variable is not None:
            self.declarations[key] = variable
        self.columns[key].place(rows, values)


class SessionStore:
    """The session's data structures (DataStructureStore: {entity set name: EntitySetStore}), which entity set each
    id is in, and the log of removed entities (each participant is sent those removed since its last turn)."""

    def __init__(self, ranks: dict):
        self.ranks = dict(ranks)                         # (data structure, entity set): rank
        self.sets = {}                                   # (data structure, entity set): EntitySetStore
        self.set_of = {}                                 # (data structure, id): entity set name
        self.removed_log = []                            # (data structure, entity set, ids)
        self.removed_ids = set()                         # (data structure, id) of every entity removed
        self.mappings = {}                               # name: the last Mapping its provider sent

    def entity_set(self, data_structure: str, name: str, rank=None) -> EntitySetStore:
        key = (data_structure, name)
        if key not in self.sets:
            rank = self.ranks.get(key, rank)
            if rank is None and name in BASE_SCALES:
                rank = BASE_SCALES.index(name) + 1
            self.ranks[key] = rank
            self.sets[key] = EntitySetStore(data_structure, name, rank)
        return self.sets[key]

    # ── merging a participant's update ─────────────────────────────────────────────
    def merge(self, participant: str, declaration, frame: Frame, id_offset: int) -> None:
        """Merge *participant*'s update: its new entities, topology changes and removals (within its rights), and its
        outputs (only the variables it provides)."""
        where = f"{participant}'s update"
        provided = {(variable.data_structure, variable.entity_set, variable.name): variable
                    for variable in declaration.provides()}
        for data_structure in frame.data_structures:
            for entity_set in sorted(data_structure.entity_sets,
                                     key=lambda item: (item.rank if item.rank is not None else 0)):
                self._merge_set(participant, declaration, data_structure.id, entity_set, provided, id_offset, where)
        declared = {mapping.name: mapping for mapping in getattr(declaration, "mappings", [])}
        for mapping in frame.mappings:
            spec = declared.get(mapping.name)
            if spec is None:
                raise CouplingError(f"{where}: mapping {mapping.name} is not one it declared")
            if (tuple(mapping.source), tuple(mapping.target)) != (spec.source, spec.target):
                raise CouplingError(f"{where}: mapping {mapping.name} joins {mapping.source} and {mapping.target}, "
                                    f"declared {spec.source} and {spec.target}")
            self.mappings[mapping.name] = mapping
        if frame.update is not None:
            for (data_structure, set_name), ids in sorted(frame.update.removed.items(),
                                                          key=lambda item: self.ranks.get(item[0]) or 0):
                self._remove(participant, declaration, data_structure, set_name, ids, where)

    def _merge_set(self, participant, declaration, data_structure, entity_set, provided, id_offset, where):
        key = (data_structure, entity_set.name)
        store = self.entity_set(data_structure, entity_set.name, entity_set.rank)
        if "id" not in entity_set.columns:
            raise CouplingError(f"{where}: {data_structure}/{entity_set.name} has no 'id' column")
        ids = np.asarray(entity_set.columns["id"], dtype=np.int64)
        rights = declaration.rights(*key)
        known = store.contains(ids)
        new = ids[~known]
        if new.size:
            if rights == "follows":
                raise CouplingError(f"{where}: {new.size} new entities in {data_structure}/{entity_set.name}, which "
                                    f"it follows (declare 'owns' or 'refines' to add entities)")
            outside = new[(new < id_offset) | (new >= id_offset + ID_COUNT)]
            if outside.size:
                raise CouplingError(f"{where}: ids {outside[:5].tolist()} outside its range [{id_offset}, "
                                    f"{id_offset + ID_COUNT})")
            elsewhere = [int(identifier) for identifier in new.tolist() if (data_structure, int(identifier))
                         in self.set_of]
            if elsewhere:
                raise CouplingError(f"{where}: ids {elsewhere[:5]} already in another entity set")
            topology = {name: np.asarray(entity_set.columns[name])[~known] for name in TOPOLOGY
                        if name in entity_set.columns}
            store.add(new, topology, participant)
            for identifier in new.tolist():
                self.set_of[(data_structure, identifier)] = entity_set.name
        rows = store.rows(ids)
        changes = [name for name in TOPOLOGY if name in entity_set.columns]
        if known.any() and changes:                       # topology of existing entities: its own, or its set's
            for name in changes:
                given = np.asarray(entity_set.columns[name])[known]
                current = store.topology[name][rows[known]]
                differs = given != current
                if differs.any():
                    allowed = (rights == "owns") | (store.creator[rows[known]] == participant)
                    if (differs & ~allowed).any():
                        raise CouplingError(f"{where}: changes the {name} of entities of {data_structure}/"
                                            f"{entity_set.name} it did not create")
                    store.topology[name][rows[known][differs]] = given[differs].astype(store.topology[name].dtype)
        for name in ("complex", "parent"):
            if name in entity_set.columns:
                values = np.asarray(entity_set.columns[name], dtype=np.int64)
                values = values[values != NO_ID]
                found = np.zeros(values.size, dtype=bool)
                for (other_structure, _), other in self.sets.items():
                    if other_structure == data_structure and values.size:
                        found |= other.contains(values)
                missing = values[~found].tolist()
                if missing:
                    raise CouplingError(f"{where}: {data_structure}/{entity_set.name}.{name} refers to unknown "
                                        f"entities {missing[:5]}")
        for name in entity_set.variable_names():
            variable = provided.get((data_structure, entity_set.name, name))
            if variable is None:
                raise CouplingError(f"{where}: '{name}' on {data_structure}/{entity_set.name} is not one of its "
                                    "declared outputs")
            store.place(participant, name, rows, entity_set.columns[name],
                        Variable(unit=variable.unit, standard_name=variable.standard_name, kind=variable.kind))

    def _remove(self, participant, declaration, data_structure, set_name, ids, where):
        store = self.sets.get((data_structure, set_name))
        ids = [int(identifier) for identifier in np.asarray(ids).tolist()
               if (data_structure, int(identifier)) not in self.removed_ids]     # e.g. with their complex already
        if not ids:
            return
        if store is None or not store.contains(ids).all():
            raise CouplingError(f"{where}: removes entities not in {data_structure}/{set_name}")
        if declaration.rights(data_structure, set_name) != "owns":
            created = store.creator[store.rows(ids)]
            if (created != participant).any():
                raise CouplingError(f"{where}: removes entities of {data_structure}/{set_name} it did not create")
        self.remove(data_structure, set_name, ids)

    def remove(self, data_structure: str, set_name: str, ids) -> None:
        """Remove *ids* and, down the finer entity sets, the entities whose complex is removed."""
        removed = set(ids)
        pending = [(set_name, removed)]
        while pending:
            name, identifiers = pending.pop()
            store = self.sets[(data_structure, name)]
            store.remove(identifiers)
            self.removed_log.append((data_structure, name, np.array(sorted(identifiers), dtype=np.int64)))
            for identifier in identifiers:
                self.set_of.pop((data_structure, identifier), None)
                self.removed_ids.add((data_structure, identifier))
            for (other_structure, other_name), other in self.sets.items():
                if other_structure != data_structure or not len(other):
                    continue
                parent = other.topology["parent"]
                orphans = np.isin(parent, list(identifiers))
                if orphans.any():                         # successors of removed entities become roots
                    parent[orphans] = NO_ID
                    other.topology["edge_type"][orphans] = "none"
                inside = other.ids[np.isin(other.topology["complex"], list(identifiers))]
                if inside.size:
                    pending.append((other_name, set(inside.tolist())))

    # ── a participant's inputs ─────────────────────────────────────────────────────
    def ancestors(self, data_structure: str, ids: np.ndarray, target: str) -> np.ndarray:
        """Each id's complex (or complex's complex, …) in the entity set *target*, NO_ID if none."""
        ids = np.asarray(ids, dtype=np.int64)
        found = np.full(ids.size, NO_ID, dtype=np.int64)
        current, active = ids.copy(), ids != NO_ID
        stores = [(name, store) for (structure, name), store in self.sets.items() if structure == data_structure]
        for _ in range(len(stores) + 1):                  # one scale up per pass
            if not active.any():
                break
            snapshot, moved = current.copy(), np.zeros(ids.size, dtype=bool)
            for name, store in stores:
                rows = store.rows(snapshot, strict=False)
                here = active & (rows >= 0)
                if name == target:
                    found[here] = snapshot[here]
                    active[here] = False
                else:
                    current[here] = store.topology["complex"][rows[here]]
                    moved |= here
            active &= moved & (current != NO_ID)
        return found

    def values(self, coupling) -> tuple:
        """The input of *coupling* on its entity set's rows: (values, missing mask)."""
        variable, source = coupling.variable, coupling.source
        target = self.entity_set(variable.data_structure, variable.entity_set)
        count = len(target)
        origin = self.sets.get((source.data_structure, source.entity_set))
        column = None if origin is None else origin.columns.get((coupling.provider, source.name))
        if column is None:
            return np.full(count, np.nan), np.ones(count, dtype=bool)
        values, present = column.values, column.present
        if coupling.mapping is not None:
            return self._through_mapping(coupling, origin, values, present, target)
        if coupling.aggregation is None:
            rows = origin.rows(target.ids, strict=False)
            found = rows >= 0
            out = _empty(values, count)
            out[found] = values[rows[found]]
            missing = ~found
            missing[found] |= ~present[rows[found]]
        elif coupling.aggregation == "copy":
            above = self.ancestors(variable.data_structure, target.ids, source.entity_set)
            rows = origin.rows(above, strict=False)
            found = rows >= 0
            out = _empty(values, count)
            out[found] = values[rows[found]]
            missing = ~found
            missing[found] |= ~present[rows[found]]
        else:
            if values.dtype.kind not in "fi":
                raise CouplingError(f"{coupling.receiver}.{variable.name}: {coupling.aggregation} of non-numeric "
                                    f"values")
            above = self.ancestors(variable.data_structure, origin.ids, variable.entity_set)
            target_rows = target.rows(above, strict=False)
            used = (target_rows >= 0) & present
            target_rows, x = target_rows[used], values[used].astype(float)
            counts = np.bincount(target_rows, minlength=count)
            missing = counts == 0
            if coupling.aggregation in ("sum", "mean"):
                out = np.bincount(target_rows, weights=x, minlength=count)
                if coupling.aggregation == "mean":
                    out = np.divide(out, counts, out=np.zeros(count), where=counts > 0)
            else:
                start = -np.inf if coupling.aggregation == "max" else np.inf
                out = np.full(count, start)
                (np.maximum if coupling.aggregation == "max" else np.minimum).at(out, target_rows, x)
            out = np.where(missing, np.nan, out)
        if coupling.factor != 1. and out.dtype.kind in "fi":
            out = out.astype(np.float64) * coupling.factor
        return out, missing

    def _through_mapping(self, coupling, origin, values, present, target) -> tuple:
        """An input from another data structure through a mapping: "sum" shares each source's value among its
        targets in proportion to their weights; "mean" gives each target its sources' weighted mean."""
        count = len(target)
        out, missing = np.full(count, np.nan), np.ones(count, dtype=bool)
        mapping = self.mappings.get(coupling.mapping)
        if mapping is None:
            return out, missing
        if values.dtype.kind not in "fi":
            raise CouplingError(f"{coupling.receiver}.{coupling.variable.name}: non-numeric values through a "
                                "mapping")
        sources, targets = np.asarray(mapping.columns["source"]), np.asarray(mapping.columns["target"])
        if coupling.reverse:
            sources, targets = targets, sources
        weights = np.asarray(mapping.columns["weight"], dtype=float)
        source_rows = origin.rows(sources, strict=False)
        target_rows = target.rows(targets, strict=False)
        used = (source_rows >= 0) & (target_rows >= 0)
        used[used] &= present[source_rows[used]]
        source_rows, target_rows, weights = source_rows[used], target_rows[used], weights[used]
        x = values[source_rows].astype(float)
        if coupling.aggregation == "sum":                  # each source's amount shared among its targets
            totals = np.bincount(source_rows, weights=weights, minlength=len(origin))
            shares = np.divide(weights, totals[source_rows], out=np.zeros_like(weights),
                               where=totals[source_rows] > 0)
            out_values = np.bincount(target_rows, weights=x * shares, minlength=count)
        else:                                               # each target's weighted mean
            weighted = np.bincount(target_rows, weights=x * weights, minlength=count)
            totals = np.bincount(target_rows, weights=weights, minlength=count)
            out_values = np.divide(weighted, totals, out=np.full(count, np.nan), where=totals > 0)
        reached = np.bincount(target_rows, minlength=count) > 0
        out[reached], missing[reached] = out_values[reached], False
        return out * coupling.factor, missing

    def inputs(self, receiver: str, declaration, couplings, removed_since: int, time: float, time_unit: str,
               step: int) -> Frame:
        """*receiver*'s turn frame: the entity sets it works on (all their entities and topology) with its inputs,
        and the entities removed since its last turn (the removed log from *removed_since*)."""
        wanted = [(entity_set.data_structure, entity_set.name) for entity_set in declaration.entity_sets]
        structures = {}
        for key in wanted:
            data_structure, name = key
            store = self.sets.get(key)
            if store is None:
                continue
            columns = {"id": store.ids.copy()}
            for column in TOPOLOGY:
                values = store.topology[column]
                if column == "sibling_order" and not (values != NO_ID).any():
                    continue
                columns[column] = values.copy()
            entity_set = EntitySet(name, columns=columns, rank=store.rank,
                                   scale=name if name in BASE_SCALES and store.rank == BASE_SCALES.index(name) + 1
                                   else None)
            for coupling in couplings:
                if coupling.receiver != receiver or coupling.variable.where != key or coupling.source is None:
                    continue
                values, missing = self.values(coupling)
                entity_set.columns[coupling.variable.name] = _with_missing(values, missing)
                entity_set.variables[coupling.variable.name] = Variable(
                    unit=coupling.variable.unit, standard_name=coupling.variable.standard_name,
                    kind=coupling.variable.kind, role="input")
            structures.setdefault(data_structure, DataStructure(data_structure)).entity_sets.append(entity_set)
        removed = {}
        for data_structure, name, ids in self.removed_log[removed_since:]:
            if (data_structure, name) in wanted:
                previous = removed.get((data_structure, name), np.zeros(0, dtype=np.int64))
                removed[(data_structure, name)] = np.union1d(previous, ids)
        return Frame(data_structures=list(structures.values()), time=time, time_unit=time_unit, step=step,
                     update=Update("coordinator", removed))

    def frame(self, time: float, time_unit: str, step: int) -> Frame:
        """The whole session as a frame (its record): every entity set, each participant's outputs (named
        participant__variable when two participants provide one name)."""
        structures = {}
        for (data_structure, name), store in sorted(self.sets.items(), key=lambda item: (item[0][0],
                                                                                       item[1].rank or 0)):
            columns = {"id": store.ids.copy()}
            for column in TOPOLOGY:
                if column == "sibling_order" and not (store.topology[column] != NO_ID).any():
                    continue
                columns[column] = store.topology[column].copy()
            counts = {}
            for _, variable in store.columns:
                counts[variable] = counts.get(variable, 0) + 1
            entity_set = EntitySet(name, columns=columns, rank=store.rank,
                                   scale=name if name in BASE_SCALES and store.rank == BASE_SCALES.index(name) + 1
                                   else None)
            for (participant, variable), column in store.columns.items():
                column_name = variable if counts[variable] == 1 else f"{participant}__{variable}"
                entity_set.columns[column_name] = _with_missing(column.values, ~column.present)
                if (participant, variable) in store.declarations:
                    entity_set.variables[column_name] = store.declarations[(participant, variable)]
            structures.setdefault(data_structure, DataStructure(data_structure)).entity_sets.append(entity_set)
        return Frame(data_structures=list(structures.values()), mappings=list(self.mappings.values()), time=time,
                     time_unit=time_unit, step=step,
                     writer={"platform": "encoding3d", "adapter": "openalea.encoding3d.coupling"})


def _empty(values: np.ndarray, count: int) -> np.ndarray:
    out = np.zeros((count,) + values.shape[1:], dtype=values.dtype)
    if values.dtype.kind == "f":
        out[:] = np.nan
    return out


def _with_missing(values: np.ndarray, missing: np.ndarray):
    """The column of *values*, its *missing* rows as the format writes them: NaN, masked, None."""
    if not missing.any():
        return values
    if values.dtype.kind == "f":
        values = values.copy()
        values[missing] = np.nan
        return values
    if values.dtype == object:
        values = values.copy()
        values[missing] = None
        return values
    mask = np.broadcast_to(missing.reshape((-1,) + (1,) * (values.ndim - 1)), values.shape)
    return np.ma.MaskedArray(values, mask=mask)
