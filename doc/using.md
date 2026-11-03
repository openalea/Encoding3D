# Viewing and checking files

## Installing

The Python package `openalea.fspm_tf` brings the command line, the validator and the reader used by ParaView's
plugin. Until it is published on the `openalea3` channel, install it from the sources:

```bash
git clone https://github.com/openalea/fspm-TF.git
cd fspm-TF
mamba env create -f conda/environment.yml
mamba activate fspm_tf
```

To use it in another environment, e.g. a model's, install its dependencies there (`mamba install numpy jsonschema`),
then `pip install -e path/to/fspm-TF`.

## In ParaView

fspm-TF comes with a ParaView reader plugin: `paraview/fspm_tf_reader.py`. It works with ParaView 5.10 and later,
and has been checked with 6.0.1 and 6.2.0.

1. In ParaView, open **Tools → Manage Plugins → Load New…**, choose `fspm_tf_reader.py`, and tick **Auto Load** to
   keep it loaded.
2. **File → Open** a frame (`.glb`), or a sequence's `scene.fspm.json` to play its frames as time steps, and choose
   **fspm-TF reader**.

The plugin needs nothing installed in ParaView: it reads files with the code of the fspm-TF folder it comes from.

What you see:

- **One block per plant population or environment model.** Each holds its meshes, its root segments as lines (apply
  a *Tube* filter on `radius` to give them volume), and its grid.
- **Every variable of every scale is a colouring choice**, named `<scale>.<variable>`: `SubOrgan.water_potential`,
  `Axis.branching_order`, `Voxel.soil_water_potential`. Values are at full precision. Where a triangle has no entity
  at a scale, the value is empty (NaN).
- **Labels and other text become integer codes**, `<scale>.label_code`; the names behind the codes are in the
  block's field data.
- **Every cell knows its plant, axis, organ ...**: besides its own entity's `<scale>.id`, a cell has the ids of the
  entities containing it (`Axis.id`, `Plant.id` on a root segment), which selection by scale uses (below).
- **Show Settings**, a reader option, adds the columns a platform keeps for its own bookkeeping, and the tables'
  links (`complex`, `parent`, `edge_type`). They are hidden by default.

```{image} _static/images/root_system.png
:alt: A small root system coloured by water potential
:width: 260px
```

*The conformance root system, coloured by `SubOrgan.water_potential`.*

In a `pvpython` script:

```python
from paraview import simple
simple.LoadPlugin("fspm-TF/paraview/fspm_tf_reader.py", ns=globals())
roots = fspmTFreader(FileName="outputs/frames/scene.fspm.json")
roots.UpdatePipeline(roots.TimestepValues[-1])          # the last frame
```

### Views: layers ready to look at

A sequence may come with a `views.json` next to its `scene.fspm.json` (metafspm writes one with
`SceneRecorder(frame_views="default")`). It names **configurations**, each a list of **layers**: a part of a data
structure (a mesh, root segments, a grid), the entities it keeps (e.g. the root segments, or the cells where the
soil is wet), the variable it is coloured by, its colour map and range, its opacity, whether it is shown at first,
and tubes for segments. The specification describes the file (§8.1).

With a views file, the reader gives **one block per layer** of the chosen configuration instead of one per data
structure: each block holds only the layer's entities, already coloured by its variable. Hidden layers are there too,
so showing one is instant, and a layer is empty in the frames that lack what it shows (a shoot not yet drawn). Two reader options:

- **Views:** the views file (empty: the `views.json` next to the opened file; without one, the blocks are as above).
- **Configuration:** a drop-down of the file's configurations (empty: the file's active one).

Two macros, shipped next to the plugin in `paraview/`, turn the layers into pipeline items and back:

1. Load them once: **Macros → Import new macro…**, choose `paraview/apply_fspm_tf_views.py`, then again for
   `paraview/save_fspm_tf_views.py`. They appear in the **Macros** menu and toolbar, and stay there.
2. Open a sequence with the fspm-TF reader, select the reader in the Pipeline Browser, and run
   **apply_fspm_tf_views**: each layer becomes its own item, named by the layer (an *ExtractBlock*, and a *Tube* for
   segments), shown as the layer says. Toggle the eyes to show or hide layers; play the time steps as usual.
3. Change colours, ranges, opacities, then select the reader again and run **save_fspm_tf_views**: the items' display
   options are written back into `views.json`, over the configuration. To keep the old one, set `CONFIGURATION` at the
   top of the macro (**Macros → Edit…**) to a new name: the views are saved as that configuration, made the active
   one.

The macros import `openalea.fspm_tf`, which the plugin puts on ParaView's path: load the plugin before running them.
A colour map's preset name is not read back from ParaView, so a saved layer keeps its `colormap`; layers coloured by
the same variable share one colour map in ParaView.

In a script, the same views without ParaView: `frame_to_vtk(frame, views="views.json", configuration="default")` from
`paraview/fspm_tf_reader.py`, and `openalea.fspm_tf.views` to read, check and write views:

```python
from openalea import fspm_tf
from openalea.fspm_tf import views

document = views.read_views("outputs/frames/views.json")
report = views.check_views(document, fspm_tf.read("outputs/frames/frame_000000.glb"))   # every name in the frame
print(report)
```

### Selecting a plant, an axis, an organ

Two more macros in `paraview/` select by scale: pick an element, and see its whole plant, axis, organ or segment,
with everything it contains at finer scales, in every layer, hidden ones included (a segment's section drawings, a
hidden layer by default, show for the selection only).

1. Load them once like the others: **Macros → Import new macro…**, `paraview/select_at_scale.py`, then
   `paraview/clear_fspm_tf_selection.py`. At the top of `select_at_scale` (**Macros → Edit…**), set `SCALE` (an
   entity set of the frames: `Plant`, `Axis`, `Organ`, `SubOrgan`, … `Compartment`) and `MODE`.
2. Pick cells in the view (**Select Cells On**, or `s`), on any layer: a leaf, a root segment.
3. Run **select_at_scale**. With `MODE = "isolate"`, the view shows only the selection, the other items hidden;
   with `MODE = "panel"`, a new view opens beside it with the selection alone, its camera fit to it, the first view
   untouched. Each layer's part is an item named `<layer> selection`, drawn as its layer (the same colour map).
   Picking again on the selection and running the macro again selects anew (e.g. an axis of the plant shown).
4. Run **clear_fspm_tf_selection**: the selection's items and panel are removed, the hidden items shown again.

A scale finer than the picked element (a Compartment of a leaf drawn without sections) is reported with the scales
the picked cells have. The macros need the plugin loaded (it puts their code, `paraview/fspm_tf_selection.py`, on
ParaView's path); which cells are selected is `openalea.fspm_tf.views.picked_entities` and `selection_mask`, tested
without ParaView.

`paraview/check_in_paraview.py` checks all this inside ParaView. `pvpython paraview/check_in_paraview.py
conformance` runs on the conformance files (the binding tests run it when `FSPM_TF_PVPYTHON` names a `pvpython`);
`pvbatch paraview/check_in_paraview.py --design <scene.fspm.json> <folder>` is a check by hand, on a sequence with
its `views.json`: it applies and saves the views, selects at several scales, isolated and in a panel, clears, and
saves a screenshot of each step in the folder, to look at.

## In other viewers

Any glTF viewer (Blender, a web viewer, ParaView without the plugin) shows the geometry, and ignores the tables.
To colour shapes there by a variable, add a **display copy**: a per-vertex copy of the variable, in single precision,
which viewers read as a colouring attribute.

```bash
fspm-tf display scene.glb water_potential               # adds _WATER_POTENTIAL to the meshes
fspm-tf display scene.glb --remove                      # removes the display copies
```

Display copies are optional and flagged as such. Readers never take them for the variable itself.

## Checking a file

```bash
fspm-tf validate scene.glb                              # one frame
fspm-tf validate outputs/frames/scene.fspm.json         # a sequence: every frame, and the rules between frames
```

The validator reports **errors** (the file does not follow the specification) and **warnings** (it does, but something
is likely missing, such as a variable without a declared unit). It checks, among other things, that:

- the ids are unique and, in a sequence, never reused;
- every `complex` and `parent` points to an existing entity, and the parents form no cycle;
- the units are valid UCUM codes that convert to their standard names' units;
- the grids and the mappings agree with their entities;
- the binary tables have the length their types imply.

The command exits with 1 when a file has errors, so it can run in a CI.

## Looking inside a file

```bash
fspm-tf info scene.glb
```

For example, for a frame of a metafspm scene with roots in a soil grid:

```
scene.glb: time 86400.0 s, step 24, writer {'platform': 'openalea.metafspm'}
  RootPopulation (graph, MPGDataStructure)
    Plant rank 1: 3 entities, variables x, y, z, ...
    SubOrgan rank 6: 412 entities, variables length, radius, struct_mass, ...
    mesh triangles: 9888 vertices, entity sets SubOrgan, Axis, Plant
  Soil (regular_grid, ArrayDataStructure)
    cell: 1024 entities, variables water_content, soil_temperature, ...
  mapping RootPopulation_to_Soil: RootPopulation/SubOrgan -> Soil/cell, 530 pairs
```
