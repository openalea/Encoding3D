"""
A coupling session's messages (specification §11), as JSON headers, some with a partial frame (GLB bytes) as payload.

Participant to coordinator::

    hello      {"type": "hello", "protocol": "0.3", "declaration": {...}, "links": [...]}
    update     {"type": "update", "step": k}                         + its outputs (a partial frame)
    error      {"type": "error", "message": "..."}

Coordinator to participant::

    welcome    {"type": "welcome", "idOffset": ..., "idCount": ..., "session": {...}, "couplings": [...]}
    turn       {"type": "turn", "step": k, "phase": "init" | "step", "time": t, "until": t'}   + its inputs
    stop       {"type": "stop", "reason": "..."}

A declaration says what a participant works on (its entity sets and its rights on their topology), what it provides
(its outputs) and requires (its inputs). Links say which output feeds which input; the coordinator completes them by
standard name, then by name.
"""
from dataclasses import dataclass, field
from typing import Optional

from openalea.encoding3d.model import BASE_SCALES

PROTOCOL_VERSION = "0.3"
RIGHTS = ("owns", "refines", "follows")
AGGREGATIONS = ("sum", "mean", "max", "min", "copy")
INTERPOLATIONS = ("hold", "linear")
ID_COUNT = 2 ** 32                               # the ids a participant may create: [offset, offset + ID_COUNT)


class CouplingError(RuntimeError):
    """A coupling that cannot run: a declaration, link or update the protocol refuses, or a participant's error."""


@dataclass
class EntitySetSpec:
    """An entity set a participant works on, with its rank (coarser first: a base scale's position by default) and
    its rights on its topology: "owns" (adds and removes its entities), "refines" (adds and removes the entities it
    creates, under others'), "follows" (reads)."""
    data_structure: str
    name: str
    rank: Optional[int] = None
    rights: str = "follows"

    def __post_init__(self):
        if self.rank is None and self.name in BASE_SCALES:
            self.rank = BASE_SCALES.index(self.name) + 1
        if self.rights not in RIGHTS:
            raise CouplingError(f"entity set {self.data_structure}/{self.name}: rights '{self.rights}', one of {RIGHTS}")

    def to_json(self) -> dict:
        return {"dataStructure": self.data_structure, "name": self.name, "rank": self.rank, "rights": self.rights}

    @classmethod
    def from_json(cls, value: dict) -> "EntitySetSpec":
        return cls(value["dataStructure"], value["name"], value.get("rank"), value.get("rights", "follows"))


@dataclass
class VariableSpec:
    """A variable a participant provides (an output) or requires (an input), on one entity set: its name in the
    participant, its unit (UCUM), standard name and kind. An optional input may stay unprovided."""
    data_structure: str
    entity_set: str
    name: str
    direction: str
    unit: str = "1"
    standard_name: Optional[str] = None
    kind: Optional[str] = None
    optional: bool = False

    def __post_init__(self):
        if self.direction not in ("provides", "requires"):
            raise CouplingError(f"variable {self.name}: direction '{self.direction}', 'provides' or 'requires'")

    @property
    def where(self) -> tuple:
        return self.data_structure, self.entity_set

    def to_json(self) -> dict:
        value = {"dataStructure": self.data_structure, "entitySet": self.entity_set, "name": self.name,
                 "direction": self.direction, "unit": self.unit}
        if self.standard_name:
            value["standardName"] = self.standard_name
        if self.kind:
            value["kind"] = self.kind
        if self.optional:
            value["optional"] = True
        return value

    @classmethod
    def from_json(cls, value: dict) -> "VariableSpec":
        return cls(value["dataStructure"], value["entitySet"], value["name"], value["direction"],
                   value.get("unit", "1"), value.get("standardName"), value.get("kind"), value.get("optional", False))


@dataclass
class MappingSpec:
    """A mapping a participant provides (its updates carry it, as a frame's Mapping of that name): weights between the
    entities of *source* and *target*, each (data structure, entity set), for links between two data structures."""
    name: str
    source: tuple
    target: tuple

    def to_json(self) -> dict:
        return {"name": self.name, "source": {"dataStructure": self.source[0], "entitySet": self.source[1]},
                "target": {"dataStructure": self.target[0], "entitySet": self.target[1]}}

    @classmethod
    def from_json(cls, value: dict) -> "MappingSpec":
        return cls(value["name"], (value["source"]["dataStructure"], value["source"]["entitySet"]),
                   (value["target"]["dataStructure"], value["target"]["entitySet"]))


@dataclass
class Declaration:
    """A participant's declaration: its name, platform, entity sets, variables, and the mappings it provides."""
    participant: str
    platform: Optional[str] = None
    entity_sets: list = field(default_factory=list)
    variables: list = field(default_factory=list)
    mappings: list = field(default_factory=list)

    def provides(self) -> list:
        return [variable for variable in self.variables if variable.direction == "provides"]

    def requires(self) -> list:
        return [variable for variable in self.variables if variable.direction == "requires"]

    def entity_set(self, data_structure: str, name: str) -> Optional[EntitySetSpec]:
        for entity_set in self.entity_sets:
            if (entity_set.data_structure, entity_set.name) == (data_structure, name):
                return entity_set
        return None

    def rights(self, data_structure: str, name: str) -> str:
        entity_set = self.entity_set(data_structure, name)
        return entity_set.rights if entity_set is not None else "follows"

    def complete(self) -> "Declaration":
        """The declaration with an entity set (following it) for each one its variables are on and it did not
        list."""
        for variable in self.variables:
            if self.entity_set(*variable.where) is None:
                self.entity_sets.append(EntitySetSpec(variable.data_structure, variable.entity_set))
        return self

    def to_json(self) -> dict:
        value = {"participant": self.participant, "entitySets": [item.to_json() for item in self.entity_sets],
                 "variables": [item.to_json() for item in self.variables]}
        if self.platform:
            value["platform"] = self.platform
        if self.mappings:
            value["mappings"] = [item.to_json() for item in self.mappings]
        return value

    @classmethod
    def from_json(cls, value: dict) -> "Declaration":
        return cls(value["participant"], value.get("platform"),
                   [EntitySetSpec.from_json(item) for item in value.get("entitySets", [])],
                   [VariableSpec.from_json(item) for item in value.get("variables", [])],
                   [MappingSpec.from_json(item) for item in value.get("mappings", [])]).complete()


@dataclass
class Link:
    """An input's provider: the receiver's variable (*entity_set* when its name is ambiguous) fed by the provider's
    *source* variable, times *factor* (after the unit conversion), changed of scale by *aggregation* (sum, mean, max,
    min from a finer entity set; copy from a coarser one), and between a replayed sequence's times by
    *interpolation* (hold, linear). Between two data structures, through the *mapping* a participant provides:
    "sum" shares each source entity's value among its targets in proportion to their weights (an amount is kept),
    "mean" gives each target the weighted mean of its sources."""
    receiver: str
    variable: str
    provider: str
    source: str
    entity_set: Optional[str] = None
    source_entity_set: Optional[str] = None
    factor: float = 1.
    aggregation: Optional[str] = None
    interpolation: str = "hold"
    mapping: Optional[str] = None

    def __post_init__(self):
        if self.aggregation is not None and self.aggregation not in AGGREGATIONS:
            raise CouplingError(f"link {self.receiver}.{self.variable}: aggregation '{self.aggregation}', one of "
                                f"{AGGREGATIONS}")
        if self.interpolation not in INTERPOLATIONS:
            raise CouplingError(f"link {self.receiver}.{self.variable}: interpolation '{self.interpolation}', one "
                                f"of {INTERPOLATIONS}")

    def to_json(self) -> dict:
        value = {"receiver": self.receiver, "variable": self.variable, "provider": self.provider,
                 "source": self.source}
        for key, name in (("entity_set", "entitySet"), ("source_entity_set", "sourceEntitySet"),
                          ("aggregation", "aggregation"), ("mapping", "mapping")):
            if getattr(self, key) is not None:
                value[name] = getattr(self, key)
        if self.factor != 1.:
            value["factor"] = self.factor
        if self.interpolation != "hold":
            value["interpolation"] = self.interpolation
        return value

    @classmethod
    def from_json(cls, value: dict) -> "Link":
        return cls(value["receiver"], value["variable"], value["provider"], value["source"],
                   value.get("entitySet"), value.get("sourceEntitySet"), float(value.get("factor", 1.)),
                   value.get("aggregation"), value.get("interpolation", "hold"), value.get("mapping"))
