# fspm-TF in five minutes

This page explains, in plain words, what an fspm-TF file contains. No programming is needed to follow it.

## A scene, one time step at a time

A simulation runs a **scene**: plants growing in an environment (soil, light, weather), step after step. fspm-TF saves
the scene as it is at one step: a **frame**. A simulation saves a frame every so many steps, so a run gives a
**sequence** of frames:

```
outputs/frames/
  frame_000000.glb        the scene at the start
  frame_000024.glb        after 24 steps (one day, with hourly steps)
  frame_000048.glb        ...
  scene.fspm.json         the index: each frame's time and file
```

Each frame is complete on its own: it can be opened, shared or given to another platform without the others.

## Plants: elements at every scale

A plant model describes a plant at several **scales**, each finer than the one before. A whole plant is made of
axes; an axis of organs; an organ of elements (root segments, leaf pieces); in anatomical models, an element of cells.
In a file, each scale is a **table**, one row per entity:

| Column | What it says |
|---|---|
| `id` | the entity's number, the same in every frame |
| `label` | what it is: a root segment, a leaf blade, an epidermis cell |
| `complex` | the entity it belongs to, one scale up (a segment's root axis) |
| `parent` | the entity it follows at its own scale (the previous segment), and how: in line, or as a branch |
| *variables* | one column each: length, radius, water potential, sugar concentration... |

Other connections, such as the walls and plasmodesmata between cells, are tables of pairs.

## Variables that mean the same everywhere

Each variable column comes with a declaration:

- its **unit**, written in a standard notation (UCUM): `m`, `MPa`, `umol/(m2.s)`;
- its **kind**, which says how values combine. An *extensive* value, like a mass, is summed when elements are merged.
  An *intensive* one, like a temperature, is averaged.
- its **role:** a state the model computes, an input it receives, or a parameter;
- where possible, a **standard name** from the shared vocabulary, such as `water_potential` or `root_water_uptake`.

The standard name is what lets two platforms recognise the same quantity, whatever each calls it internally. The
vocabulary lists the names, and for each one, the name each platform uses.

## Geometry and environment

- **Geometry.** The organs' shapes are triangles. Each triangle knows which element, organ and plant it belongs to,
  so a viewer can colour it by any variable at any scale.
- **Soil.** Soil grids are tables of cells, with their own variables.
- **Mappings.** A table of weights says which soil cells each root element lies in.

```{image} _static/images/granap_section.png
:alt: A root's cross-section, its cells coloured by tissue
:width: 300px
```
```{image} _static/images/mecha_section.png
:alt: The same section coloured by water potential
:width: 300px
```

*A root's cross-section, saved by metafspm with GRANAP and MECHA, and opened in ParaView: its cells coloured by
tissue (left) and by water potential (right).*

## Where to go next

- [Viewing and checking files](using.md): open them in ParaView, check them, inspect them.
- [Reading and writing in Python](python.md): save a scene, read its tables.
- [Specification](specification.md): the exact rules.
