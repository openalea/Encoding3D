# Vocabulary

The vocabulary (version 0.1) is the shared meaning of the files' variables and entities. These tables are built from
`spec/vocabulary/` at each build of this documentation.

## Standard names

A variable declares a standard name when it is one of these quantities. Its unit may be any unit that converts to the
canonical one (`MPa` for `Pa`, `umol/(m2.s)` for `mol/(m2.s)`).

```{include} _generated/standard_names.md
```

## Each platform's names

Each platform lists its own names for each standard name. Its writer reads its mapping from this column, so the
vocabulary can change without changing the platform's code.

```{include} _generated/platform_names.md
```

## How each name decomposes

Following I-ADOPT, a name breaks down into the property measured, the object it is measured on, the matrix it is
in, and a context.

```{include} _generated/decomposition.md
```

## Labels

Entity labels, with their scale and Plant Ontology term.

```{include} _generated/labels.md
```

## Enumerations

```{include} _generated/enums.md
```
