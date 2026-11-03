"""
fspm-TF: an exchange format for whole FSPM scenes. This package is its Python reference implementation: the codec
(openalea.fspm_tf.codec), the validator (openalea.fspm_tf.validate), the display copies (openalea.fspm_tf.display) and the vocabulary
(openalea.fspm_tf.vocabulary). See the specification in the repository's spec/ folder.
"""
SPECIFICATION_VERSION = "0.2"

from openalea.fspm_tf.model import (DataStructure, EntitySet, Frame, Grid, Mapping, Mesh, NO_ID, Relation,  # noqa: E402
                           Table, Update, Variable)
from openalea.fspm_tf.codec import (from_bytes, read, read_index, read_sequence, to_bytes, write,  # noqa: E402
                           write_index, write_sequence)

__all__ = ["SPECIFICATION_VERSION", "DataStructure", "EntitySet", "Frame", "Grid", "Mapping", "Mesh", "NO_ID",
           "Relation", "Table", "Update", "Variable", "from_bytes", "read", "read_index", "read_sequence", "to_bytes", "write",
           "write_index", "write_sequence"]
