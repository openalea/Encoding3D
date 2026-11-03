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
   :members: Frame, DataStructure, EntitySet, Relation, Table, Grid, Mesh, Mapping, Variable, Update, LazyColumns, LazyList
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

## Views

```{eval-rst}
.. automodule:: openalea.fspm_tf.views
   :members: read_views, write_views, views_path, check_views, configuration, configuration_names, selected,
             display_settings, layer_from_display, save_configuration, block_selector
```

## Vocabulary and units

```{eval-rst}
.. automodule:: openalea.fspm_tf.vocabulary
   :members: standard_names, platform_names, labels, enums, version

.. automodule:: openalea.fspm_tf.ucum
   :members: dimension, is_valid, convertible, conversion_factor
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

## Coupling

```{eval-rst}
.. automodule:: openalea.fspm_tf.coupling.messages
   :members: Declaration, EntitySetSpec, VariableSpec, Link, CouplingError

.. automodule:: openalea.fspm_tf.coupling.participant
   :members: Participant, Turn

.. automodule:: openalea.fspm_tf.coupling.coordinator
   :members: Coordinator

.. automodule:: openalea.fspm_tf.coupling.resolution
   :members: resolve, stages, Coupling

.. automodule:: openalea.fspm_tf.coupling.replay
   :members: Replay

.. automodule:: openalea.fspm_tf.coupling.conformance
   :members: run_session, run_all, subject
```

## Command line

```{eval-rst}
.. automodule:: openalea.fspm_tf.cli
```
