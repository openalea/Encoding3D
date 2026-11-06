"""
The encoding3d data model in Python: plain dataclasses holding numpy columns::

    Frame                one time step of a scene
      DataStructure      one plant population's graph, or one environment model's grid
        EntitySet        the entities of one scale (or a grid's cells): a table of columns
        Relation         an edge table between entity sets (cell adjacency, plasmodesmata, ...)
        Table            the data structure's scalars: a table of one row
        Grid             a regular or adaptive grid's layout
        Mesh             triangles, each vertex carrying the row of its entity in one or several entity sets
        InstanceSet      instances of shared templates: one row per instance (its template, transform, owner,
                         own variables), its per-instance vectors (Ragged) and its derived fields (DerivedField)
      Mapping            source entity ↔ target entity weights between two data structures
      Update             a partial frame's sender and removed entities (a coupling session's message)
    Template, Operator   shared parts (specification §12): a template mesh and its entity sets; a linear operator

Every table holds columns of equal length (its rows), and declarations (Variable) for its variables. The columns
reserved by the specification (RESERVED) are the structure: ids, the MTG relations, a relation's or a mapping's ends.

Missing values: NaN in float columns; elsewhere a numpy masked array (np.ma, the masked rows missing) for integers and
booleans, None in a text column.
"""
from collections.abc import MutableMapping, MutableSequence
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
    "instance_set": ("id", "owner", "template", "transform"),
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


class LazyColumns(MutableMapping):
    """A table's columns read lazily (codec.read(path, lazy=True)): their names known, each column decoded from the
    file on first access, then kept. Setting or deleting a column works as on a dict."""

    def __init__(self, loaders: dict, count: int):
        self._loaders = dict(loaders)                  # name: a function decoding the column
        self._values = {}
        self._order = list(loaders)
        self.count = count

    def __getitem__(self, name):
        if name not in self._values:
            if name not in self._loaders:
                raise KeyError(name)
            self._values[name] = self._loaders.pop(name)()
        return self._values[name]

    def __setitem__(self, name, values):
        if name not in self._order:
            self._order.append(name)
        self._loaders.pop(name, None)
        self._values[name] = _as_column(name, values)

    def __delitem__(self, name):
        if name not in self._order:
            raise KeyError(name)
        self._order.remove(name)
        self._loaders.pop(name, None)
        self._values.pop(name, None)

    def __contains__(self, name):                    # without decoding it
        return name in self._order

    def __iter__(self):
        return iter(list(self._order))

    def __len__(self):
        return len(self._order)

    def decoded(self) -> list:
        """The names of the columns decoded so far."""
        return [name for name in self._order if name in self._values]


class LazyList(MutableSequence):
    """A list whose items (a data structure's meshes, read lazily) are decoded on first access."""

    def __init__(self, loaders=()):
        self._items = [(False, loader) for loader in loaders]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[position] for position in range(*index.indices(len(self)))]
        done, item = self._items[index]
        if not done:
            item = item()
            self._items[index] = (True, item)
        return item

    def __setitem__(self, index, value):
        self._items[index] = (True, value)

    def __delitem__(self, index):
        del self._items[index]

    def __len__(self):
        return len(self._items)

    def insert(self, index, value):
        self._items.insert(index, (True, value))


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
        if isinstance(self.columns, LazyColumns):        # read lazily: each column checked as it is decoded
            return
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
        if isinstance(self.columns, LazyColumns):
            return self.columns.count
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
    instance_sets: list = field(default_factory=list)

    def __post_init__(self):
        self.origin = np.asarray(self.origin, dtype=np.float64).reshape(4, 4)

    def entity_set(self, name: str) -> EntitySet:
        for entity_set in self.entity_sets:
            if entity_set.name == name:
                return entity_set
        raise KeyError(f"data structure '{self.id}' has no entity set '{name}'")

    def instance_set(self, name: str) -> "InstanceSet":
        for instance_set in self.instance_sets:
            if instance_set.name == name:
                return instance_set
        raise KeyError(f"data structure '{self.id}' has no instance set '{name}'")


@dataclass
class Mapping(Table):
    """Weights between the entities of two data structures: source and target ids, weight, the *method* that built
    them. *source* and *target*: (data structure id, entity set name)."""
    source: tuple = ("", "")
    target: tuple = ("", "")
    method: Optional[str] = None

    table_kind = "mapping"


# ── Shared parts, instances and derived fields (specification §12) ───────

class Ragged:
    """One vector per instance, of varying lengths, stored flat: *values* (the vectors one after the other, float64)
    and *counts* (each vector's length). ragged[row] is the vector of the instance at *row*."""

    def __init__(self, values, counts):
        self.values = np.asarray(values, dtype=np.float64).reshape(-1)
        self.counts = np.asarray(counts, dtype=np.int64).reshape(-1)
        if (self.counts < 0).any() or int(self.counts.sum()) != self.values.size:
            raise ValueError(f"{self.values.size} values for counts summing to {int(self.counts.sum())}")
        self.starts = np.concatenate([[0], np.cumsum(self.counts)[:-1]]).astype(np.int64) if self.counts.size \
            else np.zeros(0, dtype=np.int64)

    @classmethod
    def of(cls, vectors) -> "Ragged":
        """The Ragged of a list of 1-D arrays, one per instance."""
        vectors = [np.asarray(vector, dtype=np.float64).reshape(-1) for vector in vectors]
        return cls(np.concatenate(vectors) if vectors else np.zeros(0), [vector.size for vector in vectors])

    def __len__(self):
        return self.counts.size

    def __getitem__(self, row: int) -> np.ndarray:
        start = self.starts[row]
        return self.values[start:start + self.counts[row]]

    def take(self, rows) -> "Ragged":
        """The vectors of the instances at *rows*, in that order."""
        rows = np.asarray(rows, dtype=np.int64).reshape(-1)
        if not rows.size:
            return Ragged(np.zeros(0), np.zeros(0, dtype=np.int64))
        counts = self.counts[rows]
        positions = np.repeat(self.starts[rows] - np.concatenate([[0], np.cumsum(counts)[:-1]]), counts) \
            + np.arange(int(counts.sum()))
        return Ragged(self.values[positions], counts)


class _Part:
    """A shared part: its content key (the SHA-256 of its GLB bytes, specification §12.1), taken once. A part's
    content must not change once its key is taken."""

    @property
    def key(self) -> str:
        if getattr(self, "_key", None) is None:
            from openalea.encoding3d.codec import part_bytes
            import hashlib
            self._key = hashlib.sha256(part_bytes(self)).hexdigest()
        return self._key


@dataclass(eq=False)
class Template(_Part):
    """A template (a shared part, specification §12.2): meshes drawn by many instances, in the template's own
    coordinates (each instance's transform places them), and the template's own entity sets: the rows its meshes'
    feature rows point to (a section's cells, a coarse cell's sub-cells, ...) with their constant variables. An
    entity set without ids gets its rows as ids. *kind*: "table" (entity sets without ranks) or "graph"."""
    entity_sets: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    relations: list = field(default_factory=list)
    kind: str = "table"
    labels: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    def __post_init__(self):
        for entity_set in self.entity_sets:
            if "id" not in entity_set.columns:
                entity_set.columns = {"id": np.arange(entity_set.count, dtype=np.int64), **entity_set.columns}

    def entity_set(self, name: str) -> EntitySet:
        for entity_set in self.entity_sets:
            if entity_set.name == name:
                return entity_set
        raise KeyError(f"the template has no entity set '{name}' (it has {[s.name for s in self.entity_sets]})")

    def data_structure(self) -> DataStructure:
        """The template as the data structure its part file holds (id "template")."""
        return DataStructure(id="template", kind=self.kind, entity_sets=self.entity_sets, relations=self.relations,
                             meshes=self.meshes, labels=self.labels, extras=self.extras)


OPERATOR_FORMATS = ("dense", "csr", "solve")


@dataclass(eq=False)
class Operator(_Part):
    """A linear operator of derived fields (a shared part, specification §12.3), *shape* (rows, columns), float64:

        dense    values: the (rows, columns) matrix
        csr      indptr, indices, values: the matrix in compressed sparse rows
        solve    S^-1 R, solved when evaluated: system (S, rows x rows) and right_hand_side (R, rows x columns), each
                 an (indptr, indices, values) triple

    Made with Operator.dense(matrix), Operator.sparse(matrix), Operator.solve(system, right_hand_side), or
    Operator.of_system(system, right_hand_side, max_dense=): S^-1 R computed and stored dense when it holds at most
    *max_dense* values, else the system stored. A sparse matrix is a scipy.sparse matrix (or a dense array, its
    non-zeros kept)."""
    format: str
    shape: tuple
    values: Optional[np.ndarray] = None
    indptr: Optional[np.ndarray] = None
    indices: Optional[np.ndarray] = None
    system: Optional[tuple] = None
    right_hand_side: Optional[tuple] = None

    def __post_init__(self):
        if self.format not in OPERATOR_FORMATS:
            raise ValueError(f"operator format '{self.format}': one of {OPERATOR_FORMATS}")
        self.shape = tuple(int(n) for n in self.shape)
        if len(self.shape) != 2:
            raise ValueError(f"an operator's shape is (rows, columns), not {self.shape}")
        rows, columns = self.shape
        if self.format == "dense":
            self.values = np.asarray(self.values, dtype=np.float64).reshape(rows, columns)
        elif self.format == "csr":
            self.indptr, self.indices, self.values = _csr_arrays((self.indptr, self.indices, self.values), rows,
                                                                 columns)
        else:
            self.system = _csr_arrays(self.system, rows, rows)
            self.right_hand_side = _csr_arrays(self.right_hand_side, rows, columns)
        self._factor = None

    @classmethod
    def dense(cls, matrix) -> "Operator":
        matrix = np.asarray(matrix.toarray() if hasattr(matrix, "toarray") else matrix, dtype=np.float64)
        return cls("dense", matrix.shape, values=matrix)

    @classmethod
    def sparse(cls, matrix) -> "Operator":
        indptr, indices, values, shape = _as_csr(matrix)
        return cls("csr", shape, values=values, indptr=indptr, indices=indices)

    @classmethod
    def solve(cls, system, right_hand_side) -> "Operator":
        system_csr, right_csr = _as_csr(system), _as_csr(right_hand_side)
        if system_csr[3][0] != system_csr[3][1] or right_csr[3][0] != system_csr[3][0]:
            raise ValueError(f"a solve operator: a square system ({system_csr[3]}) and a right-hand side of as many "
                             f"rows ({right_csr[3]})")
        return cls("solve", right_csr[3], system=system_csr[:3], right_hand_side=right_csr[:3])

    @classmethod
    def of_system(cls, system, right_hand_side, max_dense: int = 1 << 20) -> "Operator":
        """S^-1 R: dense when it holds at most *max_dense* values (computed now), else the system, solved when
        evaluated."""
        rows, columns = _as_csr(right_hand_side)[3]
        if rows * columns > max_dense:
            return cls.solve(system, right_hand_side)
        operator = cls.solve(system, right_hand_side)
        return cls.dense(operator.apply(np.eye(columns)))

    def matrix(self):
        """The operator as a matrix: a numpy array (dense), a scipy.sparse CSR matrix (csr); solve: S^-1 R dense."""
        if self.format == "dense":
            return self.values
        if self.format == "csr":
            from scipy import sparse
            return sparse.csr_matrix((self.values, self.indices, self.indptr), shape=self.shape)
        return self.apply(np.eye(self.shape[1]))

    def apply(self, vectors: np.ndarray) -> np.ndarray:
        """The operator applied to *vectors*: (columns,) -> (rows,), or (columns, k) -> (rows, k)."""
        vectors = np.asarray(vectors, dtype=np.float64)
        if vectors.shape[0] != self.shape[1]:
            raise ValueError(f"an operator of shape {self.shape} applied to {vectors.shape[0]} values")
        if self.format == "dense":
            return self.values @ vectors
        if self.format == "csr":
            return _csr_product((self.indptr, self.indices, self.values), self.shape[0], vectors)
        right = _csr_product(self.right_hand_side, self.shape[0], vectors)
        if self._factor is None:
            self._factor = _factorised(self.system, self.shape[0])
        return self._factor(right)


def _as_csr(matrix) -> tuple:
    """(indptr, indices, values, shape) of a scipy.sparse matrix, a dense array (its non-zeros) or such a triple
    with its shape."""
    if isinstance(matrix, tuple) and len(matrix) == 4:
        return matrix
    if hasattr(matrix, "tocsr"):
        csr = matrix.tocsr()
        csr.sum_duplicates()
        return (csr.indptr.astype(np.int64), csr.indices.astype(np.int64), csr.data.astype(np.float64), csr.shape)
    dense = np.asarray(matrix, dtype=np.float64)
    rows, columns = np.nonzero(dense)
    indptr = np.concatenate([[0], np.cumsum(np.bincount(rows, minlength=dense.shape[0]))]).astype(np.int64)
    return indptr, columns.astype(np.int64), dense[rows, columns], dense.shape


def _csr_arrays(triple, rows: int, columns: int) -> tuple:
    indptr, indices, values = (np.asarray(triple[0], dtype=np.int64).reshape(-1),
                               np.asarray(triple[1], dtype=np.int64).reshape(-1),
                               np.asarray(triple[2], dtype=np.float64).reshape(-1))
    if indptr.size != rows + 1 or indptr[0] != 0 or (np.diff(indptr) < 0).any() or indptr[-1] != indices.size \
            or indices.size != values.size:
        raise ValueError(f"not a compressed sparse row matrix of {rows} rows")
    if indices.size and (indices.min() < 0 or indices.max() >= columns):
        raise ValueError(f"column indices outside the {columns} columns")
    return indptr, indices, values


def _csr_product(triple, rows: int, vectors: np.ndarray) -> np.ndarray:
    indptr, indices, values = triple
    try:
        from scipy import sparse
    except ImportError:
        products = values.reshape((-1,) + (1,) * (vectors.ndim - 1)) * vectors[indices]
        out = np.zeros((rows,) + vectors.shape[1:])
        np.add.at(out, np.repeat(np.arange(rows), np.diff(indptr)), products)
        return out
    return sparse.csr_matrix((values, indices, indptr), shape=(rows, vectors.shape[0])) @ vectors


def _factorised(triple, rows: int):
    """A function solving S x = b, S the sparse *triple* (rows x rows): scipy's LU, else numpy's dense solve."""
    indptr, indices, values = triple
    try:
        from scipy import sparse
        from scipy.sparse.linalg import splu
    except ImportError:
        dense = np.zeros((rows, rows))
        np.add.at(dense, (np.repeat(np.arange(rows), np.diff(indptr)), indices), values)
        return lambda right: np.linalg.solve(dense, right)
    factor = splu(sparse.csr_matrix((values, indices, indptr), shape=(rows, rows)).tocsc())
    return factor.solve


@dataclass
class DerivedField:
    """A field on a template's entity set rebuilt from each instance's values (specification §12.3): for the instance
    at row i, f_i = sum over its terms k of weights[i, k] * (A · v_i + b_ik), A the operator at parts[operators[i, k]]
    of the instance set (NO_ID: no term), v_i its vector *input*, b_ik its vector offsets[k] (None, or a vector of
    length 0 for that instance: no offset). One row per instance in *operators* and *weights* ((N, K), or (N,) for
    one term; weights None: 1). Its values are on the rows of *entity_set* of the instance's template."""
    name: str
    entity_set: str
    input: str
    operators: np.ndarray
    weights: Optional[np.ndarray] = None
    offsets: tuple = ()
    variable: Variable = field(default_factory=Variable)

    def __post_init__(self):
        self.operators = np.asarray(self.operators, dtype=np.int64)
        if self.operators.ndim == 1:
            self.operators = self.operators[:, None]
        self.weights = np.ones(self.operators.shape) if self.weights is None else \
            np.asarray(self.weights, dtype=np.float64).reshape(self.operators.shape)
        self.offsets = tuple(self.offsets) if self.offsets else (None,) * self.terms
        if len(self.offsets) != self.terms:
            raise ValueError(f"derived field '{self.name}': {len(self.offsets)} offsets for {self.terms} terms")

    @property
    def terms(self) -> int:
        return int(self.operators.shape[1])


@dataclass
class InstanceSet(Table):
    """Instances of shared templates (specification §12.2), one row per instance. Reserved columns: template (int64,
    required: the index in *parts* of the instance's Template), owner (int64: the id of the entity of *owners*, an
    entity set of the data structure, it draws), transform ((N, 16) float64, optional: the column-major 4×4 placing
    the template's coordinates in the data structure's, identity when absent), id (int64, optional); then the
    instances' own variables. *parts*: the Templates and Operators the instances use (their keys, str, once read);
    *vectors*: {name: Ragged}, a vector per instance (e.g. the values a derived field's operators apply to);
    *derived*: its DerivedFields."""
    owners: Optional[str] = None
    parts: list = field(default_factory=list)
    vectors: dict = field(default_factory=dict)
    derived: list = field(default_factory=list)

    table_kind = "instance_set"

    def __post_init__(self):
        super().__post_init__()
        for name in ("id", "owner", "template"):
            if name in self.columns and self.columns[name].dtype.kind in "iu":
                self.columns[name] = self.columns[name].astype(np.int64)
        if "transform" in self.columns:
            transform = np.asarray(self.columns["transform"], dtype=np.float64)
            if transform.shape != (self.count, 16):
                raise ValueError(f"instance set '{self.name}': transform is (instances, 16) (column-major 4×4), not "
                                 f"{transform.shape}")
            self.columns["transform"] = transform

    def transforms(self) -> np.ndarray:
        """(N, 4, 4): each instance's placement (identity without a transform column)."""
        if "transform" not in self.columns:
            return np.broadcast_to(np.eye(4), (self.count, 4, 4)).copy()
        return self.columns["transform"].reshape(-1, 4, 4).transpose(0, 2, 1)

    def derived_field(self, name: str) -> DerivedField:
        for derived in self.derived:
            if derived.name == name:
                return derived
        raise KeyError(f"instance set '{self.name}' has no derived field '{name}'")


def column_major(matrices) -> np.ndarray:
    """(N, 16): 4×4 matrices *matrices* ((N, 4, 4)) as an instance set's transform column."""
    return np.asarray(matrices, dtype=np.float64).reshape(-1, 4, 4).transpose(0, 2, 1).reshape(-1, 16)


@dataclass
class Update:
    """What makes a frame partial: a coupling session's message (specification §11). *participant*: its sender
    ("coordinator" for a turn's inputs). Its tables hold some rows and columns only: the sender's outputs and its
    topology changes, entities referring to others the frame does not hold. *removed*: {(data structure id, entity
    set name): int64 ids} of the entities removed."""
    participant: str
    removed: dict = field(default_factory=dict)

    def __post_init__(self):
        self.removed = {key: np.asarray(ids, dtype=np.int64).reshape(-1) for key, ids in self.removed.items()}


@dataclass
class Frame:
    """A scene at one time step (*time* in *time_unit*, *step*), or a parameter set (data structures holding only
    parameters). *update*: set for a partial frame (Update), a coupling session's message. *unknown*: content of a
    read file this package does not interpret, written back as it was."""
    data_structures: list = field(default_factory=list)
    mappings: list = field(default_factory=list)
    time: float = 0.
    time_unit: str = "d"
    step: int = 0
    writer: dict = field(default_factory=dict)
    vocabulary_version: Optional[str] = None
    update: Optional[Update] = None
    unknown: dict = field(default_factory=dict)
    parts: Optional[object] = None          # read: where its parts are found (parts.Parts), by key

    def part(self, reference):
        """The Template or Operator *reference*: the part itself, or its key, found where the frame was read
        (embedded, or parts/<key>.glb next to it; parts.MissingPartError when it is nowhere)."""
        if not isinstance(reference, str):
            return reference
        if self.parts is None:
            from openalea.encoding3d.parts import MissingPartError
            raise MissingPartError(reference, ["the frame was not read from a file"])
        return self.parts[reference]

    def data_structure(self, id: str) -> DataStructure:
        for data_structure in self.data_structures:
            if data_structure.id == id:
                return data_structure
        raise KeyError(f"the frame has no data structure '{id}'")

    def close(self) -> None:
        """Release the file of a frame read lazily (codec.read(path, lazy=True)); its columns not decoded yet can no
        longer be read. Nothing to do for a frame read whole."""
        source = getattr(self, "_source", None)
        if source is None:
            return
        mapped, binary = source
        self._source = None
        try:
            binary.release()
            mapped.close()
        except BufferError:                  # a view of the file still alive: closed when it goes
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()


def _as_column(name: str, values) -> np.ndarray:
    if np.ma.isMaskedArray(values):                     # integers or booleans with missing values
        array = values if np.ma.getmaskarray(values).any() else np.asarray(values.data)
    else:
        array = np.asarray(values)
    if array.ndim == 0:
        array = array.reshape(1)
    if array.dtype.kind in "OU":
        if not set(map(type, array.reshape(-1).tolist())) <= {str, type(None)}:
            raise TypeError(f"column '{name}': object columns must hold strings (None: missing)")
        array = array.astype(object)
    elif np.ma.isMaskedArray(array) and array.dtype.kind == "f":
        array = array.filled(np.nan)                     # missing floats are NaN
    if array.ndim > 2:
        raise ValueError(f"column '{name}': one value or one vector per row (got shape {array.shape})")
    return array
