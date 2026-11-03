"""
A recorded sequence as a participant: a platform's log (a sequence of full frames) providing its variables to a
session without the platform running. It owns its entity sets' topology: an entity appearing between two recorded
frames is added, one disappearing is removed. Between recorded times its values are those of the last frame at or
before the session's time ("hold"), or interpolated linearly for the variables linked with interpolation "linear".
"""
import numpy as np

from openalea.fspm_tf.codec import read, read_index
from openalea.fspm_tf.coupling.messages import Declaration, EntitySetSpec, VariableSpec
from openalea.fspm_tf.model import NO_ID, DataStructure, EntitySet, Frame, Update
from openalea.fspm_tf.ucum import conversion_factor

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
        self.sent = {}                            # (data structure, entity set): ids sent at the last turn
        self.id_map = {}                          # recorded id: session id
        self.declaration = self._declare(self._frame(0))

    def _frame(self, position: int) -> Frame:
        if position not in self._cache:
            self._cache = {position: read(self.paths[position])}     # one frame kept
        return self._cache[position]

    def _declare(self, frame: Frame) -> Declaration:
        declaration = Declaration(self.name, platform=frame.writer.get("platform", "replay"))
        for data_structure in frame.data_structures:
            for entity_set in data_structure.entity_sets:
                declaration.entity_sets.append(EntitySetSpec(data_structure.id, entity_set.name, entity_set.rank,
                                                             "owns"))
                for name in entity_set.variable_names():
                    variable = entity_set.declaration(name)
                    declaration.variables.append(VariableSpec(data_structure.id, entity_set.name, name, "provides",
                                                              variable.unit, variable.standard_name, variable.kind))
        return declaration

    def update(self, time: float, time_unit: str) -> Frame:
        """The update at the session's *time* (in *time_unit*): the recorded entities and values then."""
        recorded_time = time * conversion_factor(time_unit, self.time_unit)
        position = int(np.searchsorted(self.times, recorded_time, side="right")) - 1
        position = max(position, 0)
        frame = self._frame(position)
        following = None
        if self.linear and position + 1 < len(self.times) and recorded_time > self.times[position]:
            following = read(self.paths[position + 1])
            weight = (recorded_time - self.times[position]) / (self.times[position + 1] - self.times[position])
        structures, removed = [], {}
        for data_structure in frame.data_structures:
            out = DataStructure(data_structure.id)
            for entity_set in data_structure.entity_sets:
                columns = {}
                for name, values in entity_set.columns.items():
                    if name in _ID_COLUMNS:
                        values = np.array([self._session_id(int(value)) for value in np.asarray(values).tolist()],
                                          dtype=np.int64)
                    columns[name] = values
                if following is not None:
                    self._interpolate(data_structure.id, entity_set, following, weight, columns)
                out.entity_sets.append(EntitySet(entity_set.name, columns=columns, rank=entity_set.rank,
                                                 variables=dict(entity_set.variables)))
                key = (data_structure.id, entity_set.name)
                ids = set(columns["id"].tolist()) if "id" in columns else set()
                gone = self.sent.get(key, set()) - ids
                if gone:
                    removed[key] = np.array(sorted(gone), dtype=np.int64)
                self.sent[key] = ids
            structures.append(out)
        return Frame(data_structures=structures, update=Update(self.name, removed))

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
            if (data_structure_id, entity_set.name, name) not in self.linear or name not in later.columns:
                continue
            values = np.asarray(columns[name])
            if values.dtype.kind != "f":
                continue
            values = values.copy()
            values[found] = (1 - weight) * values[found] + weight * np.asarray(later.columns[name])[rows[found]]
            columns[name] = values
