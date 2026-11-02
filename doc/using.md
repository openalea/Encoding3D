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
and has been checked with 6.0.1.

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
