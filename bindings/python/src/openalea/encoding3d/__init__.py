"""
encoding3d: an exchange format for whole FSPM scenes. This package is its Python reference implementation: the codec
(openalea.encoding3d.codec), the validator (openalea.encoding3d.validate), the display copies (openalea.encoding3d.display), the vocabulary
(openalea.encoding3d.vocabulary), instances and their derived fields (openalea.encoding3d.instances), shared parts
(openalea.encoding3d.parts) and archives (openalea.encoding3d.archive). See the specification in the repository's spec/ folder.
"""
SPECIFICATION_VERSION = "0.4"

from openalea.encoding3d.model import (DataStructure, DerivedField, EntitySet, Frame, Grid, InstanceSet,  # noqa: E402
                           Mapping, Mesh, NO_ID, Operator, Ragged, Relation, Table, Template, Update, Variable,
                           column_major)
from openalea.encoding3d.codec import (from_bytes, part_bytes, read, read_index, read_part, read_sequence,  # noqa: E402
                           to_bytes, write, write_index, write_parts, write_sequence)
from openalea.encoding3d.parts import MissingPartError, prune_parts  # noqa: E402
from openalea.encoding3d.instances import evaluate, placed_meshes  # noqa: E402
from openalea.encoding3d.archive import ArchiveCheckError, check_archive, pack, unpack  # noqa: E402

__all__ = ["SPECIFICATION_VERSION", "ArchiveCheckError", "DataStructure", "DerivedField", "EntitySet", "Frame", "Grid", "InstanceSet",
           "Mapping", "Mesh", "MissingPartError", "NO_ID", "Operator", "Ragged", "Relation", "Table", "Template",
           "Update", "Variable", "check_archive", "column_major", "evaluate", "from_bytes", "pack", "part_bytes", "placed_meshes",
           "prune_parts", "read", "read_index", "read_part", "read_sequence", "to_bytes", "unpack", "write",
           "write_index", "write_parts", "write_sequence"]
