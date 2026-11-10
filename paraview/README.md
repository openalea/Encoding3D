# encoding3d in ParaView: how-to

One file to load: **`plugin_encoding3d.py`**, the plugin. There are no macros to add. The other files here are not
plugins, so do not load them:

| file | what it is |
|---|---|
| `plugin_encoding3d.py` | **the plugin**: the *encoding3d reader* and the *encoding3d Select at scale* filter |
| `encoding3d_displays.py` | the plugin's code that draws each layer and runs its buttons (the plugin loads it) |
| `check_in_paraview.py` | a check run with `pvpython` or `pvbatch`, for developers (end of this page) |

Menu names below are ParaView 6.2's. The plugin works with ParaView 5.11 and later.

## 1. Install the plugin (once)

1. **Tools → Manage Plugins...**
2. Under *Local Plugins*, click **Load New ...** and choose `encoding3d/paraview/plugin_encoding3d.py`.
3. Unfold the plugin's line, tick **Auto Load**, and click **Close**. ParaView then loads the plugin each time it
   starts.

You do not need to install anything in ParaView: the plugin reads files with the code of the encoding3d folder it
sits in. Do not move the file out of that folder. A link to it, placed anywhere, works.

## 2. Open a run's frames

1. **File → Open...**, go to the run's `outputs/.../frames/` folder, and choose `scene.fspm.json` (all the frames, as
   time steps) or a single `frame_XXXXXX.glb`. A sequence packed into one file, `run.fspm.zip` (made by
   `encoding3d pack`, or metafspm's recorder at a run's end, which then removes the folder), opens the same way:
   choose the `.fspm.zip` file itself.
2. If ParaView asks which reader to use, choose **encoding3d reader**.
3. Click **Apply** in the *Properties* panel.

**Time Unit** (the reader's *Properties*): the unit of the times ParaView shows in the animation toolbar and the
*Time Inspector*, days by default (`d`, `h`, `min` or `s`). The frames' files keep their own unit (metafspm writes
seconds); only what ParaView shows is converted. To print the time in the view, add **Filters → Annotate Time Filter** on
the reader.

Large runs: frames grow with the plants. In a sequence, ParaView reads only the frame of the current time, once for
the reader and its *Select at scale* filters. A layer of instances that the views hide (metafspm's root sections) is
not drawn by the reader: the layer is an empty block, and *Select at scale* draws the sections of what it selects
(section 6). Opening a late frame then costs little more than a glTF viewer needs for its shoot, roots and soil (metafspm's use
case 1, day 23: 1.9 GB, of which 1 GB for the frame's tables in frames written before November 2026).

## 3. What appears: the layers

When the frames come with a `views.json` (metafspm writes one), its **default configuration** is drawn as soon as
you click Apply, with no macro to run. Each **layer** is drawn its own way: the shoot, the roots (as tubes), the soil
grid (translucent), and the root sections (hidden at first). Each layer has its own colour variable, colour map,
range, opacity and visibility, with its own colour legend.

The layers are the blocks of the reader's item. To see them and change them one by one:

- **View → MultiBlock Inspector** opens a panel that lists the layers by name.
  - The **check box** of a layer shows or hides it, for example the soil. A layer of sections hidden by the
    views is empty (section 3b): tick **Expand Hidden Instances** first to fill it.
  - **Click a layer** (Ctrl-click for several) to edit only that layer, in the inspector's lower part:
    - **Block Coloring**: its colour variable (the drop-down), **Rescale to Data Range**, the colour map (the
      *Edit color map* button opens the **Color Map Editor**), **Toggle Color Legend Visibility** and **Use Separate
      Color Map**.
    - **Opacity**: for example 0.2 to make the soil more see-through.
- In the view, **right-click a part** (for example the soil) for **Block 'RichardsSoilModel'** → **Hide Block**,
  **Show Only Block**, **Show All Blocks**, **Set Block Color**, **Set Block Opacity**.

The colouring and opacity in the *Properties* panel apply to the whole item. They do not change a layer that has its
own colouring or opacity, which is every layer at the start. Change a layer in the MultiBlock Inspector instead.

Layers coloured by the same variable share one colour map, as in ParaView in general. Tick **Use Separate Color Map**
to give a layer its own.

A colour legend shows the variable's **unit** when the frame gives one: `SubOrgan.radius [m]`,
`cell.pressure_head [m]`, `Plant.blade_duration [{phyllochron}]`. A variable without a unit (a count, a type, an
id) shows its name alone. This holds for the legends of the layers and for those of a variable you pick yourself
(the layer's drop-down, or the toolbar's). A title you type in the legend's properties is kept.

Without a `views.json`, the reader shows one block per data structure (each plant population, the soil), with every
variable as a colouring choice. Colour them like any ParaView item.

## 3b. Instances: sections and other shapes drawn from a template

Some frames draw many entities with one shape each, stored once: the sections of the root segments, the cells of a
tissue drawn at a coarse scale (specification §12, "instances"). They appear as a layer, or without a `views.json` as a
block named **instances sections** (or another name) in their data structure's block.

- Each instance is drawn where it belongs. Its cells hold the ids of the entity it draws and of the entities containing
  it (`SubOrgan.id`, `Axis.id`, `Plant.id`), the rows of each cell (`encoding3d_instance`,
  `encoding3d_template_row.Cell`) and the layer's colour variable. Tick **All Instance Arrays** in the reader's
  *Properties* for every variable too: the instance's own (for example `sections.age`), the entity's (for example
  `SubOrgan.radius`) and the template's (for example `Cell.label_code`, `Cell.area`). Each is one value per triangle,
  so a large frame needs several times the memory.
- A layer of instances that the views hide is not drawn by the reader: its block is empty, and **encoding3d Select at
  scale** draws the instances of what it selects, from the frame. Tick **Expand Hidden Instances** in the reader's
  *Properties* to draw them all (for small scenes: a late frame of a run can hold millions of triangles of sections).
- Its **inner values** (for example the water potential on each cell of a section, `Cell.water_potential`) are not
  in the file: they are rebuilt from a few values of the instance when you ask for them. Two ways:
  - **Select it** (section 6 below): pick a root segment (or a section, when its layer is shown), apply **encoding3d
    Select at scale** (the default Scale, `picked`, is the segment's own: its section), or at a plant or an axis. The
    selection holds the inner values of every instance it contains, ready to colour by. Its buttons **Isolate**,
    **Show In Panel** and **Put Back** work as for any selection. The values rebuilt are kept while the frame is open:
    switching the Scale back does not compute them again.
  - **All of them**: tick **Evaluate Derived Fields** in the reader's *Properties* (and **Expand Hidden Instances**
    when the views hide their layer), then **Apply**. Every instance's inner values are rebuilt at each time step. Use
    it for small scenes: it is slower than selecting a few.

  A layer coloured by an inner value (in `views.json`) draws its instances in one colour until then; its selection
  is coloured by it.

If ParaView says in **View → Output Messages** that a part is missing, the `parts/` folder was not copied with the
frames: copy the whole `frames/` folder, or send the `.fspm.zip`. The selection's rebuild then stops with that error.

A frame may hold no sections, or none for the plant selected: metafspm draws them every `display_period` and for its
`display_plants` only. The selection is then without sections at that time step, and **View → Output Messages** says
so once per time step, naming the plants that have some, for example: *no 'GranapAnatomy' instance drawn for the
selected Plant [12] at t = 1.2e+06 s: the frame's 911 instances are owned by Plant [11]*.

## 4. Switch configurations

A `views.json` can hold several configurations, for example "default" or "roots and sections". On the reader's item,
in the *Properties* panel:

- **Configuration**: a drop-down of the configurations in the file (empty: the file's active one). Choose one, then
  click **Apply**. The layers are drawn again as that configuration says.
- **Views**: another views file to use (empty: the `views.json` next to the opened file, or the one inside the
  `.fspm.zip`).

## 5. Save your changes into `views.json`

After you change layers in the MultiBlock Inspector, select the reader's item. In its *Properties* panel:

- **Save Views** writes each layer's display into `views.json`, over the configuration shown: visibility, colour
  variable or solid colour, range (fixed, or following the data), log scale, opacity, and the item's representation.
- To keep the configuration and save a new one instead, type a name in **Save As**, click **Apply**, then
  **Save Views**. The new configuration becomes the file's active one, so it opens next time, and the
  **Configuration** drop-down shows it.

A colour map's preset name is not read back from ParaView, so a saved layer keeps its `colormap`. The views inside
a `.fspm.zip` cannot be saved: unpack it first (`encoding3d unpack run.fspm.zip folder`).

## 6. Select a plant, an axis, an organ, a segment

1. In the render view's toolbar, click **Select Cells On (s)** (or press `s`), then drag a small rectangle over a
   part of the view (a root, a leaf). The picked cells are highlighted.
2. With the reader's item still active in the *Pipeline Browser*, choose **Filters → encoding3d → encoding3d Select at
   scale** (or **Filters → Alphabetical**, or Ctrl+Space and type "Select at scale"), then **Apply**.
3. In the filter's *Properties*, choose the **Scale**: `picked` (the default: the picked cells' own scale, a root's
   segment for example), `Plant`, `Axis`, `Organ`, `SubOrgan`, ... `Compartment`. Click **Apply**. The selection is
   the picked element's whole plant, axis, organ or segment, with everything it contains at finer scales, in every
   layer, the hidden ones included (a segment's section comes with it).
4. Play the time steps: the selection follows the same plant or organ as it grows.

**Choose a Scale, click Apply, then use the buttons.** The buttons work on the Scale applied: a Scale chosen in the
drop-down and not yet applied is not seen by them (ParaView sends a property to the filter on Apply only). Right after
the filter is made, they work on the default, `picked`, with no Apply.

Apply draws the selection in the active view, with the reader still shown.

The selection's item is drawn like the layers (the same colour maps). Its *Properties* panel has three buttons:

- **Isolate**: the active view shows only the selection; the other items are hidden.
- **Show In Panel**: a new view opens beside the active one with the selection alone, its camera fitted to it. The
  first view is put back as it was before the filter: the selection that Apply drew there is hidden (Put Back shows it
  again).
- **Put Back**: one step back. The items that Isolate hid are shown again, or the panel is closed.

To narrow a selection (an axis of the plant shown), pick on the selection's item in the view or panel, apply another
*encoding3d Select at scale* to it, then click its **Isolate**. Its **Put Back** returns to the plant.

To drop a selection, click **Put Back** first, then delete the filter (*Pipeline Browser*, Delete key). To pick
another element with the same filter, make the new selection, then click **Copy Active Selection** in the filter's
*Properties* and click **Apply**.

A Scale finer than the picked element (a `Compartment` of a leaf drawn without sections) is reported in **View →
Output Messages**, and so are the time steps at which the selection has no sections (section 3b). A selection at
`Plant` of a late frame holds all of that plant's sections (tens of millions of triangles at day 23 of metafspm's use
case 1): select an axis or a segment there.

## Limits

- One representation draws all layers. Wireframe or Points apply to the whole item; a layer's own `representation`
  is kept in `views.json` but not drawn separately.
- The buttons (**Save Views**, **Isolate**, **Show In Panel**, **Put Back**) work with ParaView's built-in server,
  which is the default. With a remote server (*File → Connect*), the layers are still drawn and the filter works,
  but the buttons do nothing (a message in Output Messages).
- Items made from the reader by other filters (*Clip*, *Slice*) are drawn by ParaView in the usual way, not as the
  layers.
- Units appear in the colour legends only. ParaView 6.2's *Information* panel and *Spreadsheet View* show the
  arrays' names without their units. With the default legend font (Arial), ParaView draws the square brackets of
  `[m]` as round ones; Times or Courier (the legend's *Title Font Properties*) show them square.
- The legends get their units with ParaView's built-in server. With a remote server they show the names alone.

## For developers

- `pvpython paraview/check_in_paraview.py conformance` checks the plugin on the conformance files (the Python tests
  run it when `ENCODING3D_PVPYTHON` names a `pvpython`).
- `pvbatch paraview/check_in_paraview.py --instances <folder>` is a check by hand of instances: the conformance
  sequence `instances/` opened as a folder and as a `.fspm.zip`, a section selected and its derived field rebuilt
  (compared with `openalea.encoding3d.evaluate`), isolated, shown in a panel, put back, then every derived field
  evaluated; a screenshot of each step in `<folder>`. Given a run's index after it
  (`--instances <folder> run/frames/scene.fspm.json`, or its folder or `.fspm.zip`), the same check on that run:
  its last frame with derived fields, three instances spread over the set selected at their owners' scale, each
  rebuilt field compared with `evaluate`, isolated and put back.
- `pvbatch paraview/check_in_paraview.py --design <copy>/frames/scene.fspm.json <folder>` is a check by hand on a
  copy of a run's frames. It draws each configuration, saves the views back, selects at several scales, isolates,
  opens a panel and puts back, and saves a screenshot of each step in `<folder>`.
- In a script: `simple.LoadPlugin("paraview/plugin_encoding3d.py", ns=globals())`, then
  `reader = encoding3dreader(FileName=...)`. `simple.Show(reader)` draws the layers as the GUI's Apply does, and
  `reader.InvokeCommand("SaveViews")` or `selection.InvokeCommand("Isolate")` press the buttons.
- How it works: the plugin watches the session (its `encoding3d_displays.install()`). It draws each new
  representation of a reader with views, or of a selection drawn from one, by setting the representation's block
  properties (`BlockSelectors`, `BlockColorArrayNames`, `BlockLookupTables`, `BlockColors`, `BlockOpacities`). It
  draws them again when the configuration or the views file changes. The block properties come from
  `openalea.encoding3d.views.block_displays`, and `displays_from_blocks` reads them back. Both are tested without
  ParaView.
- Units: each array of a declared variable holds the variable's UCUM unit in its information
  (`vtkDataArray.UNITS_LABEL()`), the derived fields and the instances' own variables too (`_array(..., unit=)`,
  `unit_of`); the undeclared columns (`id`, `label`, the links, the text codes `<set>.<column>_code`) have none.
  The arrays keep their names. `encoding3d_displays` titles each legend `<array> [<unit>]` (`legend_title`; the
  name alone for no unit or `1`), the layers' legends when it shows them and ParaView's own: it watches each scalar
  bar and retitles it when ParaView sets its title to the bare name of an array that has a unit (`_watch_legend`).
- Instances: the reader draws each visible instance set with `openalea.encoding3d.instances.placed_meshes`; each cell
  has its instance's row (`encoding3d_instance`), its rows in the template's entity sets
  (`encoding3d_template_row.<set>`), the ids containing it and the layer's colour variable (every variable with
  `all_arrays`); each block its frame's file (field data `encoding3d_frame`). A hidden layer's block is empty, with its
  layer as field data (`encoding3d_unexpanded`); the filter's `grow_entities` places the instances inside the entities
  it selects (`instance_rows_at`), `rebuild_derived` evaluates the derived fields of the instances its output holds
  (`openalea.encoding3d.evaluate`, one matrix product per operator, kept per open frame), and `missing_instances` says
  why a selection has none. The reader and the filter share the frames open (`open_frame`, the last two).
- `pvbatch paraview/check_in_paraview.py --large <run>/frames.fspm.zip [day]` is a check by hand on a large run: the
  hidden sections layer empty on opening, a root segment selected at `picked`, `Axis` and `Plant` (only those
  sections placed, their derived field equal to `evaluate`'s), the default Scale, the panel leaving the view as it
  was, and the message of a half-day frame without sections; it prints each step's cells and the peak memory.
