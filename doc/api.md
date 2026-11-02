# Python API

`openalea.fspm_tf` is the reference codec: reading and writing frames and sequences, the validator, display copies,
the vocabulary and units.

## Reading and writing

```{eval-rst}
.. automodule:: openalea.fspm_tf.codec
   :members: read, write, from_bytes, to_bytes, write_sequence, read_sequence, write_index, read_index
```

## The data model

```{eval-rst}
.. automodule:: openalea.fspm_tf.model
   :members: Frame, DataStructure, EntitySet, Relation, Table, Grid, Mesh, Mapping, Variable
```

## Validation

```{eval-rst}
.. automodule:: openalea.fspm_tf.validate
   :members: validate_file, validate_bytes, validate_sequence, Report, Issue
```

## Display copies

```{eval-rst}
.. automodule:: openalea.fspm_tf.display
   :members: add_display, remove_display
```

## Vocabulary and units

```{eval-rst}
.. automodule:: openalea.fspm_tf.vocabulary
   :members: standard_names, platform_names, labels, enums, version

.. automodule:: openalea.fspm_tf.ucum
   :members: dimension, is_valid, convertible
```

## Comparing with expected values

```{eval-rst}
.. automodule:: openalea.fspm_tf.compare
   :members: compare, compare_files, compare_all
```

## Expected values

```{eval-rst}
.. automodule:: openalea.fspm_tf.dump
   :members: frame_to_dict
```

## Command line

```{eval-rst}
.. automodule:: openalea.fspm_tf.cli
```
