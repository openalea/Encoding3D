"""
A recorded sequence as a participant: a platform's log (a sequence of full frames) providing its variables to a
session without the platform running. It owns its entity sets' topology: an entity appearing between two recorded
frames is added, one disappearing is removed. Between recorded times its values are those of the last frame at or
before the session's time ("hold"), or interpolated linearly for the variables linked with interpolation "linear".
"""
import numpy as np

from openalea.encoding3d.codec import read, read_index
from openalea.encoding3d.coupling.messages import Declaration, EntitySetSpec, MappingSpec, VariableSpec
from openalea.encoding3d.model import NO_ID, DataStructure, EntitySet, Frame, Mapping, Update
from openalea.encoding3d.ucum import conversion_factor

_ID_COLUMNS = ("id", "complex", "parent")


class Replay:
    """A sequence (its index, scene.fspm.json) replayed as participant *name*."""

    def __init__(self, name: str, index_path: str):
        self.name = name
        index = read_index(index_path)
        self.time_unit = index.get("timeUnit", "d")
        self.entries = sorted(index["frames"], key=lambda entry: entry["time"])
        self.paths = [entry["path"] for entry in self.entries]
        self.times = np.array([entry["time"] for entry in self.entries], dtype=float)
        self._cache = {}
        self.id_offset = 0
        self.linear = set()                       # (data structure, entity set, variable) interpolated
        self.needed = None                        # (data structure, entity set, variable) some link uses (None: all)
        self.sent = {}                            # (data structure, entity set): ids sent at the last turn
        self.id_map = {}                          # recorded id: session id
        self.declaration = self._declare()

    def _frame(self, position: int) -> Frame:
        if position not in self._cache:                  # one frame kept, read lazily: only the columns used
            for frame in self._cache.values():
                frame.close()
            self._cache = {position: read(self.paths[position], lazy=True)}
        return self._cache[position]

    def _declare(self) -> Declaration:
        """Its declaration: every entity set, variable and mapping of its frames (some appear later than others)."""
        declaration = None
        sets, variables, mappings = set(), set(), set()
        self.own = set()
        for position in range(len(self.paths)):
            frame = self._frame(position)
            if declaration is None:
                declaration = Declaration(self.name, platform=frame.writer.get("platform", "replay"))
            for data_structure in frame.data_structures:
                self.own.add(data_structure.id)
                for entity_set in data_structure.entity_sets:
                    if (data_structure.id, entity_set.name) not in sets:
                        sets.add((data_structure.id, entity_set.name))
                        declaration.entity_sets.append(EntitySetSpec(data_structure.id, entity_set.name,
                                                                     entity_set.rank, "owns"))
                    for name in entity_set.variable_names():
                        if (data_structure.id, entity_set.name, name) in variables:
                            continue
                        variables.add((data_structure.id, entity_set.name, name))
                        variable = entity_set.declaration(name)
                        declaration.variables.append(VariableSpec(data_structure.id, entity_set.name, name, "provides",
                                                                  variable.unit, variable.standard_name,
                                                                  variable.kind))
            for mapping in frame.mappings:
                if mapping.name not in mappings:
                    mappings.add(mapping.name)
                    declaration.mappings.append(MappingSpec(mapping.name, tuple(mapping.source),
                                                            tuple(mapping.target)))
        return declaration

    def update(self, time: float, time_unit: str) -> Frame:
        """The update at the session's *time* (in *time_unit*): the recorded entities and values then."""
        recorded_time = time * conversion_factor(time_unit, self.time_unit)
        position = int(np.searchsorted(self.times, recorded_time, side="right")) - 1
        position = max(position, 0)
        frame = self._frame(position)
        following = None
        if self.linear and position + 1 < len(self.times) and recorded_time > self.times[position]:
            following = read(self.paths[position + 1], lazy=True)
            weight = (recorded_time - self.times[position]) / (self.times[position + 1] - self.times[position])
        structures, removed = [], {}
        for data_structure in frame.data_structures:
            out = DataStructure(data_structure.id)
            for entity_set in data_structure.entity_sets:
                columns = {}
                for name in entity_set.columns:
                    if name not in entity_set.reserved and self.needed is not None \
                            and (data_structure.id, entity_set.name, name) not in self.needed:
                        continue                          # a variable no link uses: not decoded
                    values = entity_set.columns[name]
                    if name in _ID_COLUMNS:
                        values = np.array([self._session_id(int(value)) for value in np.asarray(values).tolist()],
                                          dtype=np.int64)
                    columns[name] = values
                if following is not None:
                    self._interpolate(data_structure.id, entity_set, following, weight, columns)
                out.entity_sets.append(EntitySet(entity_set.name, columns=columns, rank=entity_set.rank,
                                                 variables={name: variable for name, variable in
                                                            entity_set.variables.items() if name in columns}))
                key = (data_structure.id, entity_set.name)
                ids = set(columns["id"].tolist()) if "id" in columns else set()
                gone = self.sent.get(key, set()) - ids
                if gone:
                    removed[key] = np.array(sorted(gone), dtype=np.int64)
                self.sent[key] = ids
            structures.append(out)
        mappings = []
        for mapping in frame.mappings:                # ids renumbered at the ends in its own data structures
            columns = dict(mapping.columns)
            for end, (data_structure_id, _) in (("source", mapping.source), ("target", mapping.target)):
                if data_structure_id in self.own:
                    columns[end] = np.array([self._session_id(int(value)) for value in columns[end].tolist()],
                                            dtype=np.int64)
            mappings.append(Mapping(mapping.name, columns=columns, source=mapping.source, target=mapping.target,
                                    method=mapping.method))
        return Frame(data_structures=structures, mappings=mappings, update=Update(self.name, removed))

    def _session_id(self, recorded: int) -> int:
        """The session id of a recorded id: the replay's ids renumbered from its offset, in order of appearance."""
        if recorded == NO_ID:
            return NO_ID
        if recorded not in self.id_map:
            self.id_map[recorded] = self.id_offset + len(self.id_map)
        return self.id_map[recorded]

    def _interpolate(self, data_structure_id, entity_set, following, weight, columns) -> None:
        try:
            later = following.data_structure(data_structure_id).entity_set(entity_set.name)
        except KeyError:
            return
        later_rows = {identifier: row for row, identifier in enumerate(later.columns["id"].tolist())}
        rows = np.array([later_rows.get(identifier, -1) for identifier in entity_set.columns["id"].tolist()])
        found = rows >= 0
        for name in entity_set.variable_names():
            if (data_structure_id, entity_set.name, name) not in self.linear or name not in later.columns \
                    or name not in columns:
                continue
            values = np.asarray(columns[name])
            if values.dtype.kind != "f":
                continue
            values = values.copy()
            values[found] = (1 - weight) * values[found] + weight * np.asarray(later.columns[name])[rows[found]]
            columns[name] = values
