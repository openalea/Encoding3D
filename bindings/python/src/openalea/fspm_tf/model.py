"""
The fspm-TF data model in Python: plain dataclasses holding numpy columns::

    Frame                one time step of a scene
      DataStructure      one plant population's graph, or one environment model's grid
        EntitySet        the entities of one scale (or a grid's cells): a table of columns
        Relation         an edge table between entity sets (cell adjacency, plasmodesmata, ...)
        Table            the data structure's scalars: a table of one row
        Grid             a regular or adaptive grid's layout
        Mesh             triangles, each vertex carrying the row of its entity in one or several entity sets
      Mapping            source entity ↔ target entity weights between two data structures

Every table holds columns of equal length (its rows), and declarations (Variable) for its variables. The columns
reserved by the specification (RESERVED) are the structure: ids, the MTG relations, a relation's or a mapping's ends.

Missing values: NaN in float columns; elsewhere a numpy masked array (np.ma, the masked rows missing) for integers and
booleans, None in a text column.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

NO_ID = -1                                      # complex / parent / feature row of no entity

# Columns whose meaning the specification fixes, per kind of table
RESERVED = {
    "entity_set": ("id", "label", "complex", "parent", "edge_type", "level", "index", "sibling_order"),
    "relation": ("id", "source", "target", "relation"),
    "mapping": ("source", "target", "weight"),
    "scalars": (),
}
ID_COLUMNS = ("id", "complex", "parent", "source", "target", "level", "index",
              "sibling_order")      # reserved, int64
EDGE_TYPES = ("none", "successor", "branch", "unknown")    # MTG: root of its scale, '<', '+'; a link not known
BASE_SCALES = ("Plant", "Axis", "GrowthUnit", "Phytomer", "Organ", "SubOrgan", "Layer", "Cell", "Compartment",
               "Connection")                    # an entity set's scale: one of these, or "mixed"
FORMATS = ("date", "date-time", "time")         # a text variable holding ISO 8601 dates or times
ENUM_COLUMNS = ("label", "edge_type", "relation")
DATA_STRUCTURE_KINDS = ("graph", "regular_grid", "adaptive_grid", "table")
ROLES = ("state", "input", "parameter", "derived", "setting")


@dataclass
class Variable:
    """The declaration of a variable (a column): its unit (a UCUM code), its standard name in the vocabulary, its
    kind (extensive, intensive, ...: how it maps between scales and grids), its role and its provenance; the format
    of a text column holding dates or times ("date", "date-time", "time")."""
    unit: str = "1"
    standard_name: Optional[str] = None
    kind: Optional[str] = None
    role: str = "state"
    description: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    references: tuple = ()
    doi: tuple = ()
    format: Optional[str] = None


@dataclass
class Table:
    """Columns of equal length (numpy arrays: one row per entity; a 2-D array is a fixed-size vector per entity) and
    the declarations of the variable columns."""
    name: str
    columns: dict = field(default_factory=dict)
    variables: dict = field(default_factory=dict)

    table_kind = "scalars"

    def __post_init__(self):
        self.columns = {name: _as_column(name, values) for name, values in self.columns.items()}
        for name in set(self.columns) & set(ID_COLUMNS) & set(self.reserved):    # ids are int64, whatever the platform's
            if self.columns[name].dtype.kind in "iu":                            # default integer
                self.columns[name] = self.columns[name].astype(np.int64)
            if np.ma.isMaskedArray(self.columns[name]):
                raise ValueError(f"table '{self.name}': the reserved column '{name}' has no missing values")
        counts = {name: len(values) for name, values in self.columns.items()}
        if len(set(counts.values())) > 1:
            raise ValueError(f"table '{self.name}': columns of different lengths {counts}")

    @property
    def count(self) -> int:
        return len(next(iter(self.columns.values()))) if self.columns else 0

    @property
    def reserved(self) -> tuple:
        return RESERVED[self.table_kind]

    def variable_names(self) -> list:
        return [name for name in self.columns if name not in self.reserved]

    def declaration(self, name: str) -> Variable:
        return self.variables.get(name) or Variable()


@dataclass
class EntitySet(Table):
    """The entities of one scale of a graph (rank: the scale's rank, coarser first), or a grid's cells (rank None).
    Columns: id (int64, stable across frames, never reused), label (str), complex (the id of the containing entity
    at the coarser scale, NO_ID if none), parent (the predecessor's id at the same scale, NO_ID if none), edge_type
    (str: 'none', 'successor', 'branch', 'unknown'); sibling_order (int64, optional: its position among its tree parent's
    children); an adaptive grid's cells: level and index; then the variables. *scale*: its base scale
    (BASE_SCALES), or "mixed"."""
    rank: Optional[int] = None
    scale: Optional[str] = None

    table_kind = "entity_set"

    def ids(self) -> np.ndarray:
        if "id" in self.columns:
            return self.columns["id"]
        return np.arange(self.count, dtype=np.int64)        # a grid's cells: implicit ids, the C-order index


@dataclass
class Relation(Table):
    """An edge table: source and target entity ids (in the entity sets *source_set* and *target_set*), an optional
    id per edge (int64, unique in the data structure), an optional relation label per edge, and edge variables."""
    source_set: str = ""
    target_set: str = ""

    table_kind = "relation"


@dataclass
class Grid:
    """A grid's layout. Regular: *shape* cells of size *spacing* from *origin*, along *axes*, *periodic* per axis,
    z pointing up or down (*z_up*). Adaptive: the same for its base level, refined up to *max_level*, its leaf cells
    (an entity set with level and index columns) explicit. *cells*: the name of the cells' entity set."""
    kind: str = "regular"
    shape: tuple = ()
    origin: tuple = ()
    spacing: tuple = ()
    axes: tuple = ("x", "y", "z")
    periodic: tuple = ()
    z_up: bool = True
    max_level: int = 0
    cells: str = "Cell"


@dataclass
class Mesh:
    """Triangles: *positions* (V, 3) in the data structure's frame, three consecutive vertices per triangle, or
    *indices* (3T,) into them; *feature_rows*: {entity set name: (V,) the row of each vertex's entity in that set,
    NO_ID for none}; *display*: {variable name: (V,) float32 display copy}, with the entity set each comes from in
    *display_sources*."""
    name: str
    positions: np.ndarray
    feature_rows: dict = field(default_factory=dict)
    indices: Optional[np.ndarray] = None
    display: dict = field(default_factory=dict)
    display_sources: dict = field(default_factory=dict)

    def __post_init__(self):
        self.positions = np.asarray(self.positions, dtype=np.float64).reshape(-1, 3)
        self.feature_rows = {name: np.asarray(rows, dtype=np.int64).reshape(-1)
                             for name, rows in self.feature_rows.items()}
        if self.indices is not None:
            self.indices = np.asarray(self.indices, dtype=np.int64).reshape(-1)
        for name, rows in self.feature_rows.items():
            if rows.size != len(self.positions):
                raise ValueError(f"mesh '{self.name}': {rows.size} feature rows for '{name}', "
                                 f"{len(self.positions)} vertices")


@dataclass
class DataStructure:
    """One plant population's graph, or one environment model's grid. *origin*: its frame in the scene (4×4).
    *extras*: JSON values for the writing platform (e.g. what it needs to rebuild its own data structure); other
    readers keep them without interpreting them. *labels*: {the platform's label: the vocabulary's label}."""
    id: str
    kind: str = "graph"
    entity_sets: list = field(default_factory=list)
    relations: list = field(default_factory=list)
    scalars: Optional[Table] = None
    grid: Optional[Grid] = None
    meshes: list = field(default_factory=list)
    origin: np.ndarray = field(default_factory=lambda: np.eye(4))
    platform: Optional[str] = None
    model: Optional[str] = None
    extras: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)

    def __post_init__(self):
        self.origin = np.asarray(self.origin, dtype=np.float64).reshape(4, 4)

    def entity_set(self, name: str) -> EntitySet:
        for entity_set in self.entity_sets:
            if entity_set.name == name:
                return entity_set
        raise KeyError(f"data structure '{self.id}' has no entity set '{name}'")


@dataclass
class Mapping(Table):
    """Weights between the entities of two data structures: source and target ids, weight, the *method* that built
    them. *source* and *target*: (data structure id, entity set name)."""
    source: tuple = ("", "")
    target: tuple = ("", "")
    method: Optional[str] = None

    table_kind = "mapping"


@dataclass
class Frame:
    """A scene at one time step (*time* in *time_unit*, *step*), or a parameter set (data structures holding only
    parameters). *unknown*: content of a read file this package does not interpret, written back as it was."""
    data_structures: list = field(default_factory=list)
    mappings: list = field(default_factory=list)
    time: float = 0.
    time_unit: str = "d"
    step: int = 0
    writer: dict = field(default_factory=dict)
    vocabulary_version: Optional[str] = None
    unknown: dict = field(default_factory=dict)

    def data_structure(self, id: str) -> DataStructure:
        for data_structure in self.data_structures:
            if data_structure.id == id:
                return data_structure
        raise KeyError(f"the frame has no data structure '{id}'")


def _as_column(name: str, values) -> np.ndarray:
    if np.ma.isMaskedArray(values):                     # integers or booleans with missing values
        array = values if np.ma.getmaskarray(values).any() else np.asarray(values.data)
    else:
        array = np.asarray(values)
    if array.ndim == 0:
        array = array.reshape(1)
    if array.dtype.kind in "OU":
        if not all(isinstance(value, str) or value is None for value in array.reshape(-1)):
            raise TypeError(f"column '{name}': object columns must hold strings (None: missing)")
        array = array.astype(object)
    elif np.ma.isMaskedArray(array) and array.dtype.kind == "f":
        array = array.filled(np.nan)                     # missing floats are NaN
    if array.ndim > 2:
        raise ValueError(f"column '{name}': one value or one vector per row (got shape {array.shape})")
    return array
