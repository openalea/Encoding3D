"""
encoding3d: an exchange format for whole FSPM scenes. This package is its Python reference implementation: the codec
(openalea.encoding3d.codec), the validator (openalea.encoding3d.validate), the display copies (openalea.encoding3d.display) and the vocabulary
(openalea.encoding3d.vocabulary). See the specification in the repository's spec/ folder.
"""
SPECIFICATION_VERSION = "0.3"

from openalea.encoding3d.model import (DataStructure, EntitySet, Frame, Grid, Mapping, Mesh, NO_ID, Relation,  # noqa: E402
                           Table, Update, Variable)
from openalea.encoding3d.codec import (from_bytes, read, read_index, read_sequence, to_bytes, write,  # noqa: E402
                           write_index, write_sequence)

__all__ = ["SPECIFICATION_VERSION", "DataStructure", "EntitySet", "Frame", "Grid", "Mapping", "Mesh", "NO_ID",
           "Relation", "Table", "Update", "Variable", "from_bytes", "read", "read_index", "read_sequence", "to_bytes", "write",
           "write_index", "write_sequence"]
