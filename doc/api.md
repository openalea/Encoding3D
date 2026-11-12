# Python API

`openalea.encoding3d` is the reference codec: reading and writing frames and sequences, the validator, display copies,
the vocabulary and units.

## Reading and writing

```{eval-rst}
.. automodule:: openalea.encoding3d.codec
   :members: read, write, from_bytes, to_bytes, write_sequence, read_sequence, write_index, read_index,
             write_parts, part_bytes, read_part, frame_part_keys
```

## The data model

```{eval-rst}
.. automodule:: openalea.encoding3d.model
   :members: Frame, DataStructure, EntitySet, Relation, Table, Grid, Mesh, Mapping, Variable, Update, LazyColumns, LazyList,
             InstanceSet, Template, Operator, DerivedField, Ragged, column_major
```

## Validation

```{eval-rst}
.. automodule:: openalea.encoding3d.validate
   :members: validate_file, validate_bytes, validate_sequence, Report, Issue
```

## Display copies

```{eval-rst}
.. automodule:: openalea.encoding3d.display
   :members: add_display, remove_display
```

## Instances, derived fields and shared parts

```{eval-rst}
.. automodule:: openalea.encoding3d.instances
   :members: evaluate, placed_meshes, find_instance_set, PlacedMeshes

.. automodule:: openalea.encoding3d.parts
   :members: Parts, MissingPartError, prune_parts, content_key, part_file
```

## Archives

```{eval-rst}
.. automodule:: openalea.encoding3d.archive
   :members: pack, check_archive, ArchiveCheckError, unpack, read_bytes, exists, split
```

## Views

```{eval-rst}
.. automodule:: openalea.encoding3d.views
   :members: read_views, write_views, views_path, check_views, configuration, configuration_names, selected,
             display_settings, layer_from_display, save_configuration, block_selector
```

## Vocabulary and units

```{eval-rst}
.. automodule:: openalea.encoding3d.vocabulary
   :members: standard_names, platform_names, labels, enums, version

.. automodule:: openalea.encoding3d.ucum
   :members: dimension, is_valid, convertible, conversion_factor
```

## Comparing with expected values

```{eval-rst}
.. automodule:: openalea.encoding3d.compare
   :members: compare, compare_files, compare_all
```

## Expected values

```{eval-rst}
.. automodule:: openalea.encoding3d.dump
   :members: frame_to_dict
```

## Coupling

```{eval-rst}
.. automodule:: openalea.encoding3d.coupling.messages
   :members: Declaration, EntitySetSpec, VariableSpec, Link, CouplingError

.. automodule:: openalea.encoding3d.coupling.participant
   :members: Participant, Turn

.. automodule:: openalea.encoding3d.coupling.coordinator
   :members: Coordinator

.. automodule:: openalea.encoding3d.coupling.resolution
   :members: resolve, stages, Coupling

.. automodule:: openalea.encoding3d.coupling.replay
   :members: Replay

.. automodule:: openalea.encoding3d.coupling.conformance
   :members: run_session, run_all, subject
```

## Command line

```{eval-rst}
.. automodule:: openalea.encoding3d.cli
```
