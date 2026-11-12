# Viewing and checking files

## Installing

The Python package `openalea.encoding3d` brings the command line, the validator and the reader used by ParaView's
plugin. Until it is published on the `openalea3` channel, install it from the sources:

```bash
git clone https://github.com/openalea/encoding3d.git
cd encoding3d
mamba env create -f conda/environment.yml
mamba activate encoding3d
```

To use it in another environment, e.g. a model's, install its dependencies there (`mamba install numpy jsonschema`),
then `pip install -e path/to/encoding3d`.

## In ParaView

encoding3d comes with a ParaView plugin, one file to load: `paraview/plugin_encoding3d.py` (the *encoding3d reader*
and the *encoding3d Select at scale* filter; no macros). It works with ParaView 5.11 and later, and has been checked
with 6.2.0. `paraview/README.md` is the step-by-step how-to, with ParaView 6.2's menu names.

1. In ParaView, open **Tools → Manage Plugins...**, click **Load New ...**, choose `plugin_encoding3d.py`, and tick
   **Auto Load** to keep it loaded.
2. **File → Open...** a frame (`.glb`), or a sequence's `scene.fspm.json` to play its frames as time steps, choose
   **encoding3d reader** if ParaView asks, and click **Apply**.

The plugin needs nothing installed in ParaView: it reads files with the code of the encoding3d folder it comes from.

What you see:

- **One block per plant population or environment model** (without a views file, below). Each holds its meshes, its
  root segments as lines (apply a *Tube* filter on `radius` to give them volume), and its grid.
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
simple.LoadPlugin("encoding3d/paraview/plugin_encoding3d.py", ns=globals())
roots = encoding3dreader(FileName="outputs/frames/scene.fspm.json")
roots.UpdatePipeline(roots.TimestepValues[-1])          # the last frame
```

### Views: layers ready to look at

A sequence may come with a `views.json` next to its `scene.fspm.json` (metafspm writes one with
`SceneRecorder(frame_views="default")`). It names **configurations**, each a list of **layers**: a part of a data
structure (a mesh, root segments, a grid), the entities it keeps (e.g. the root segments, or the cells where the
soil is wet), the variable it is coloured by, its colour map and range, its opacity, whether it is shown at first,
and tubes for segments. The specification describes the file (§8.1).

With a views file, the reader gives **one block per layer** of the chosen configuration instead of one per data
structure: each block holds only the layer's entities, already coloured by its variable, a segments layer with a
`tube` as tubes. Hidden layers are there too, so showing one is instant, and a layer is empty in the frames that lack
what it shows (a shoot not yet drawn). Two reader options:

- **Views:** the views file (empty: the `views.json` next to the opened file; without one, the blocks are as above).
- **Configuration:** a drop-down of the file's configurations (empty: the file's active one).

The plugin draws the layers itself, with no macro: when you click **Apply** (or change the Configuration and Apply),
each layer is drawn as its block with its own colour variable, colour map, range, log scale or solid colour,
opacity and visibility, with its own colour legend. The soil can be translucent while the roots and the shoot have
their own colour maps.

- **View → MultiBlock Inspector** lists the layers by name: tick one to show or hide it, click one to change its
  colouring (*Block Coloring*: the variable, the colour map, *Rescale to Data Range*, *Use Separate Color Map*) or its
  *Opacity*. In the view, right-click a layer for *Hide Block*, *Show Only Block*, *Set Block Opacity*.
- **Save Views** (a button of the reader) writes the layers' display back into `views.json`, over the configuration
  shown; with a name in **Save As** (then Apply), as a new configuration, made the active one.

A colour map's preset name is not read back from ParaView, so a saved layer keeps its `colormap`; layers coloured by
the same variable share one colour map (*Use Separate Color Map* gives a layer its own). One representation draws
all layers: a layer's own `representation` is kept in the file, not drawn apart.

```{image} _static/images/views_layers.png
:alt: A wheat seedling and its root system in a translucent soil grid, each layer with its own colour map
:width: 420px
```

*metafspm's use case 1 (day 8), as the plugin draws it on Apply, no macro: the soil grid translucent
(`pressure_head`, Viridis), the roots (`type`, Inferno) and the shoot (`organ_rank`, Cool to Warm), a configuration
giving each its own colour map.*

In a script, the same views without ParaView: `frame_to_vtk(frame, views="views.json", configuration="default")` from
`paraview/plugin_encoding3d.py`, and `openalea.encoding3d.views` to read, check and write views:

```python
from openalea import encoding3d
from openalea.encoding3d import views

document = views.read_views("outputs/frames/views.json")
report = views.check_views(document, encoding3d.read("outputs/frames/frame_000000.glb"))   # every name in the frame
print(report)
```

### Selecting a plant, an axis, an organ

The plugin has a filter that selects by scale: pick an element, and get its whole plant, axis, organ or segment,
with everything it contains at finer scales, in every layer, hidden ones included (a segment's section drawings, a
hidden layer by default, come with the selection: the reader leaves a hidden layer of instances empty, and the filter
places the instances of what it selects only).

1. Pick cells in the view (**Select Cells On (s)**, or `s`), on the reader's item or a selection shown before. The
   item picked on becomes the active one in the Pipeline Browser.
2. **Filters → encoding3d → encoding3d Select at scale**, then **Apply**. The filter takes ParaView's current selection
   when it is made, as *Extract Selection* does (its **Selection** property: **Copy Active Selection** takes the
   selection made since, on the same item).
3. Choose the **Scale** in its Properties: `picked` at first (the picked cells' own scale, e.g. a root's segment),
   then the frames' scales, coarser first (`Plant`, `Axis`, `Organ`, `SubOrgan`, … `Compartment`). **Apply** grows
   the picked cells again. The buttons below work on the Scale applied: choose a Scale, Apply, then use them.
4. Play the time steps: the picked entities are kept, so the plant or organ is followed as it grows.

The filter's output is one block per layer, named and filled like the reader's, each holding the selection's part
of the layer (empty when it has none), and it is drawn as the layers (the same colour maps), the hidden ones shown.
A scale finer than the picked element (a Compartment of a leaf drawn without sections) is reported in the Output
Messages, with the scales the picked cells have, and so is a time step at which the selection has no sections (a
platform drawing them at some time steps, or for some plants: those which have some are named).

The filter's buttons show it:

- **Isolate**: the active view shows only the selection, the other items hidden.
- **Show In Panel**: a new view beside the active one shows the selection alone, its camera fit to it, the first view
  as it was before the filter (the selection that Apply drew there hidden, shown again by Put Back).
- **Put Back**: one step back, the hidden items shown again or the panel closed. Then delete the filter to drop the
  selection.

To narrow a selection (an axis of the plant shown), pick on it, apply another encoding3d Select at scale to it, and
click its Isolate: it is shown over the first, and its Put Back returns to the plant. The buttons work with
ParaView's built-in server (the default); which cells are selected is `openalea.encoding3d.views.picked_entities`
and `selection_mask`, tested without ParaView.

`paraview/check_in_paraview.py` checks all this inside ParaView. `pvpython paraview/check_in_paraview.py
conformance` runs on the conformance files (the binding tests run it when `ENCODING3D_PVPYTHON` names a `pvpython`);
`pvbatch paraview/check_in_paraview.py --design <copy>/frames/scene.fspm.json <folder>` is a check by hand, on a
copy of a sequence with its `views.json`: it shows the layers as the GUI's Apply does, switches configurations,
saves the views back, selects at several scales with the filter (switching its Scale, stepping in time), shows the
selections isolated, in a panel and one over another, puts them back, and saves a screenshot of each step in the
folder, to look at.

## In other viewers

Any glTF viewer (Blender, a web viewer, ParaView without the plugin) shows the geometry, and ignores the tables.
To colour shapes there by a variable, add a **display copy**: a per-vertex copy of the variable, in single precision,
which viewers read as a colouring attribute.

```bash
encoding3d display scene.glb water_potential               # adds _WATER_POTENTIAL to the meshes
encoding3d display scene.glb --remove                      # removes the display copies
```

Display copies are optional and flagged as such. Readers never take them for the variable itself.

## Checking a file

```bash
encoding3d validate scene.glb                              # one frame (and the parts it refers to)
encoding3d validate outputs/frames/scene.fspm.json         # a sequence: every frame, and the rules between frames
encoding3d validate run.fspm.zip                           # a sequence packed into one file
```

The validator reports **errors** (the file does not follow the specification) and **warnings** (it does, but something
is likely missing, such as a variable without a declared unit). It checks, among other things, that:

- the ids are unique and, in a sequence, never reused;
- every `complex` and `parent` points to an existing entity, and the parents form no cycle;
- the units are valid UCUM codes that convert to their standard names' units;
- the grids and the mappings agree with their entities;
- the binary tables have the length their types imply;
- every shared part a frame refers to (§12: a template, an operator) exists, is valid and hashes to its key, and the
  instances' templates, owners and operators' shapes agree.

The command exits with 1 when a file has errors, so it can run in a CI.

## Sharing a sequence: one file

```bash
encoding3d pack outputs/frames run.fspm.zip                # the folder as one archive (deflate; --compression lzma),
                                                           # checked, then the folder removed (--keep-folder keeps it)
encoding3d unpack run.fspm.zip folder                      # and back
encoding3d prune outputs/frames                            # the parts no frame uses any more, removed
```

ParaView, the validator and `encoding3d.read` open the archive as the folder. See
[Instances, derived fields and archives](instances.md).

## Looking inside a file

```bash
encoding3d info scene.glb
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
