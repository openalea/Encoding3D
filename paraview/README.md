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
   time steps) or a single `frame_XXXXXX.glb`.
2. If ParaView asks which reader to use, choose **encoding3d reader**.
3. Click **Apply** in the *Properties* panel.

Large runs: frames grow with the plants. To look around quickly, open an early `frame_XXXXXX.glb` first. In a
sequence, ParaView reads only the frame of the current time.

## 3. What appears: the layers

When the frames come with a `views.json` (metafspm writes one), its **default configuration** is drawn as soon as
you click Apply, with no macro to run. Each **layer** is drawn its own way: the shoot, the roots (as tubes), the soil
grid (translucent), and the root sections (hidden at first). Each layer has its own colour variable, colour map,
range, opacity and visibility, with its own colour legend.

The layers are the blocks of the reader's item. To see them and change them one by one:

- **View → MultiBlock Inspector** opens a panel that lists the layers by name.
  - The **check box** of a layer shows or hides it, for example the sections.
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

Without a `views.json`, the reader shows one block per data structure (each plant population, the soil), with every
variable as a colouring choice. Colour them like any ParaView item.

## 4. Switch configurations

A `views.json` can hold several configurations, for example "default" or "roots and sections". On the reader's item,
in the *Properties* panel:

- **Configuration**: a drop-down of the configurations in the file (empty: the file's active one). Choose one, then
  click **Apply**. The layers are drawn again as that configuration says.
- **Views**: another views file to use (empty: the `views.json` next to the opened file).

## 5. Save your changes into `views.json`

After you change layers in the MultiBlock Inspector, select the reader's item. In its *Properties* panel:

- **Save Views** writes each layer's display into `views.json`, over the configuration shown: visibility, colour
  variable or solid colour, range (fixed, or following the data), log scale, opacity, and the item's representation.
- To keep the configuration and save a new one instead, type a name in **Save As**, click **Apply**, then
  **Save Views**. The new configuration becomes the file's active one, so it opens next time, and the
  **Configuration** drop-down shows it.

A colour map's preset name is not read back from ParaView, so a saved layer keeps its `colormap`.

## 6. Select a plant, an axis, an organ, a segment

1. In the render view's toolbar, click **Select Cells On (s)** (or press `s`), then drag a small rectangle over a
   part of the view (a root, a leaf). The picked cells are highlighted.
2. With the reader's item still active in the *Pipeline Browser*, choose **Filters → encoding3d → encoding3d Select at
   scale** (or **Filters → Alphabetical**, or Ctrl+Space and type "Select at scale"), then **Apply**.
3. In the filter's *Properties*, choose the **Scale**: `Plant` (the default), `Axis`, `Organ`, `SubOrgan`, ...
   `Compartment`. Click **Apply**. The selection is the picked element's whole plant, axis, organ or segment, with
   everything it contains at finer scales, in every layer, the hidden ones included (a segment's section comes with
   it).
4. Play the time steps: the selection follows the same plant or organ as it grows.

The selection's item is drawn like the layers (the same colour maps). Its *Properties* panel has three buttons:

- **Isolate**: the active view shows only the selection; the other items are hidden.
- **Show In Panel**: a new view opens beside the active one with the selection alone, its camera fitted to it; the
  first view is not changed.
- **Put Back**: one step back. The items that Isolate hid are shown again, or the panel is closed.

To narrow a selection (an axis of the plant shown), pick on the selection's item in the view or panel, apply another
*encoding3d Select at scale* to it, then click its **Isolate**. Its **Put Back** returns to the plant.

To drop a selection, click **Put Back** first, then delete the filter (*Pipeline Browser*, Delete key). To pick
another element with the same filter, make the new selection, then click **Copy Active Selection** in the filter's
*Properties* and click **Apply**.

A Scale finer than the picked element (a `Compartment` of a leaf drawn without sections) is reported in **View →
Output Messages**.

## Limits

- One representation draws all layers. Wireframe or Points apply to the whole item; a layer's own `representation`
  is kept in `views.json` but not drawn separately.
- The buttons (**Save Views**, **Isolate**, **Show In Panel**, **Put Back**) work with ParaView's built-in server,
  which is the default. With a remote server (*File → Connect*), the layers are still drawn and the filter works,
  but the buttons do nothing (a message in Output Messages).
- Items made from the reader by other filters (*Clip*, *Slice*) are drawn by ParaView in the usual way, not as the
  layers.

## For developers

- `pvpython paraview/check_in_paraview.py conformance` checks the plugin on the conformance files (the Python tests
  run it when `ENCODING3D_PVPYTHON` names a `pvpython`).
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
