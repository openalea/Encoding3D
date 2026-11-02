# Changing the format

## What is agreed, and where

Everything the platforms agree on is in the repository's `spec/` folder:

| File | Content |
|---|---|
| `spec/specification.md` | the rules: data model, glTF layout, tables, variables, meshes, sequences, conformance |
| `spec/schema/` | the JSON Schemas of the `FSPM_scene` extension and of a sequence's index |
| `spec/vocabulary/standard_names.csv` | the standard names, with each platform's names for them |
| `spec/vocabulary/labels.csv` | the entity labels, with their Plant Ontology terms |
| `spec/vocabulary/enums.json` | the values of the enumerations (kinds, roles, edge types...) |

The rest of the repository implements, checks or displays what `spec/` says.

## Proposing a change

A change is a pull request touching `spec/`, together with:

- the conformance scene showing it (`conformance/generate.py`, and the files it writes);
- the validator check enforcing it;
- the reference codec's update.

The CI then runs every codec against the new conformance files, and shows which ones follow.

**Kinds of change:**

| Change | Version |
|---|---|
| a new standard name, label or platform name | the vocabulary's version: no codec changes |
| a new optional field or table | a minor version (0.1 → 0.2): old files stay valid |
| a field changed or removed | a major version, once 1.0 is out; before 1.0, a minor one |

**Rules:**

- **Readers keep what they do not understand.** A platform rewriting a file keeps the other platforms' `extras` and
  the extensions it does not read.
- **Vocabulary review:** a standard name comes with its definition, canonical unit and kind, and is agreed by at
  least two platforms.
- **One file, one version:** each file states the specification and vocabulary versions it follows (`FSPM_scene`'s
  `version` and `vocabulary`).

## Status

Version 0.1 is a draft. It was written with metafspm as the first platform; its partners' reviews come next. Until
0.1 is released, the draft may still change in ways that make earlier files invalid.
