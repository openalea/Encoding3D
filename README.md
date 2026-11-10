# encoding3d - functional-structural plant model scenes, based on glTF 2.0

[![Anaconda-Server Badge](https://anaconda.org/openalea3/openalea.encoding3d/badges/license.svg)](https://anaconda.org/openalea3/openalea.encoding3d)

[![Build Status](https://github.com/openalea/encoding3d/actions/workflows/conda-build.yml/badge.svg?branch=main)](https://github.com/openalea/encoding3d/actions/workflows/conda-build.yml?query=branch%3Amain)
[![Docs](https://readthedocs.org/projects/encoding3d/badge/?version=latest)](https://encoding3d.readthedocs.io/)

[![Anaconda-Server Badge](https://anaconda.org/openalea3/openalea.encoding3d/badges/version.svg)](https://anaconda.org/openalea3/openalea.encoding3d)
[![Anaconda-Server Badge](https://anaconda.org/openalea3/openalea.encoding3d/badges/platforms.svg)](https://anaconda.org/openalea3/openalea.encoding3d)
[![Python Version](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/downloads/)
[![Downloads](https://anaconda.org/openalea3/openalea.encoding3d/badges/downloads.svg)](https://anaconda.org/openalea3/openalea.encoding3d)

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.1003173.svg)](https://doi.org/10.5281/zenodo.1003173)

An exchange format for whole functional-structural plant model (FSPM) scenes, across platforms and languages
(openalea.metafspm, CPlantBox, GroIMP, VirtualPlantLab). It holds:

- multiscale plant graphs;
- their state variables and parameters;
- their geometry;
- the environment's grids.

Each time step is one glTF file, and the variables share one vocabulary. It also runs models of several platforms
together, step by step (coupling sessions: a coordinator and each platform's participant, over ZeroMQ or a folder).

Status: specification 0.4, draft (0.1, 0.2 and 0.3 files stay valid): 0.3 adds coupling platforms (§11), 0.4
instances of shared templates, linear derived fields, shared parts and `.fspm.zip` archives (§12, §8.2).

- [The documentation](doc/index.md): for users (viewing, checking, Python) and for platform developers
  (implementing a codec, conformance, changing the format), built with Sphinx (`.readthedocs.yml`; locally:
  `python -m sphinx -b html doc doc/_build`)
- [The specification](spec/specification.md)
- [The design note](doc/design_note.md): the review of existing formats and the decisions taken
- [Implementations](implementations.md)

## The repository

**`spec/` is the agreement between the platforms.** It's the only folder discussed with them; a change to the format is a
change there, released as a new version. Everything else implements, checks or displays what it says.

| Folder | Content | Discussed with the platforms |
|---|---|---|
| `spec/specification.md` | the specification: data model, glTF layout, sequences, conformance | **yes** |
| `spec/schema/` | the JSON Schemas of the `FSPM_scene` extension, of a sequence's index and views, and of a coupling session's messages | **yes** |
| `spec/vocabulary/` | the standard names (units, kinds, definitions, and each platform's names for them), the labels with their Plant Ontology terms, the enumerations | **yes** |
| `conformance/` | reference files, each a GLB with its expected values as JSON, written by `generate.py`: the specification as test cases for every platform's code (`conformance/README.md`; checked with `encoding3d compare-all` and the action `.github/actions/conformance`); `coupling/`: the coupling sessions a participant runs (`encoding3d couple-conformance`) | follows `spec/` |
| `bindings/<language>/` | each language's codec and coupling participant, with its own build, tests and release; `bindings/python/`: `openalea.encoding3d`, the reference (codec with lazy reading, validator, display copies, views, the coupling's coordinator, command line), which reads `spec/` and ships it; `bindings/julia/`: encoding3d.jl, the Julia codec, with a ZeroMQ extension and the MultiScaleTreeGraph.jl and VirtualPlantLab extensions (proposals); `bindings/cpp/`: the C++ codec, with CPlantBox's adapter (a proposal); `bindings/java/`: the Java codec, with GroIMP's adapter and plugin (proposals) | no |
| `paraview/` | the ParaView plugin (`plugin_encoding3d.py`), its how-to, and the script checking it in a `pvpython` | no |
| `doc/design_note.md` | how the decisions were reached | no |
| `pyproject.toml`, `conda/` | the Python package's build, at the root next to `spec/`, which it ships | no |

## The Python package

```bash
git clone https://github.com/openalea/encoding3d.git
cd encoding3d
mamba env create -f conda/environment.yml        # numpy and jsonschema from conda-forge, then pip install -e .
mamba activate encoding3d
pytest
```

```python
from openalea import encoding3d

frame = encoding3d.read("scene.glb")                # data structures, entity sets as numpy columns, meshes
encoding3d.write("copy.glb", frame)
```

```bash
encoding3d validate scene.glb                       # or a sequence: encoding3d validate run/scene.fspm.json
encoding3d info scene.glb
encoding3d display scene.glb water_potential        # float32 per-vertex copies, for viewers such as ParaView
```

## Viewing in ParaView

`paraview/plugin_encoding3d.py` is encoding3d's ParaView plugin (ParaView ≥ 5.11), the only file to load: the
*encoding3d reader* and the *encoding3d Select at scale* filter, no macros. `paraview/README.md` is the how-to.

1. In ParaView, open Tools → Manage Plugins..., click Load New ..., and choose the file. Tick "Auto Load" to keep it
   loaded.
2. File → Open... a `.glb` frame or a sequence's `scene.fspm.json`, pick "encoding3d reader", and Apply.

What it shows:

- Each data structure is a block: its meshes, its segments as lines (for a Tube filter on `radius`) and its grid.
- With a `views.json` next to the frames, one block per layer of its configuration instead (a drop-down), drawn at
  Apply as the layer says: its colour variable and colour map, range, opacity, visibility, tubes for roots, each
  layer editable on its own in View → MultiBlock Inspector, and saved back with the reader's "Save Views" button.
- Every variable of every scale is a data array named `<entity set>.<variable>`, at full precision, with no display
  copies needed. A sequence's frames are the time steps.
- Text columns such as labels become integer codes, `<entity set>.<column>_code`; the names behind the codes are in
  the block's field data.
- Filters → encoding3d → encoding3d Select at scale grows picked cells to their plant, axis, organ ... in every layer;
  its buttons isolate the selection, show it in a panel, and put it back.

The plugin finds `openalea.encoding3d` in ParaView's Python if it is installed there, otherwise in this clone's
`bindings/python/src/`. It needs nothing beyond what ParaView ships (numpy). In `pvpython` scripts the reader is
`encoding3dreader(FileName=...)`, after `LoadPlugin("paraview/plugin_encoding3d.py", ns=globals())`. Checked with
ParaView 6.2.0: `pvpython paraview/check_in_paraview.py conformance` (also run by the tests when
`ENCODING3D_PVPYTHON` names a pvpython).

## For another platform

Two pieces of code make a platform read and write encoding3d:

- **A codec** for its language: GLB files, property tables, sequences, the vocabulary. It depends on `spec/` only, so it
  lives here, in `bindings/<language>/` (`cpp/`, `java/`, `julia/`...), with its build files, its tests and its own
  release, maintained by the platform's team. A change to `spec/` then updates every codec in the same pull request,
  and the CI shows which languages follow.
- **An adapter** between the codec's tables and the platform's own model (e.g. `openalea.metafspm.io.encoding3d` for
  metafspm's DataStructures). It depends on the platform, so it lives in the platform's repository.

**encoding3d depends on no platform.** Its requirements and its CI install none (not even metafspm). The adapters for
CPlantBox (`bindings/cpp/cplantbox/`), GroIMP (`bindings/java/groimp/`, `bindings/java/groimp-plugin/`), MTG.jl and
VirtualPlantLab (`bindings/julia/encoding3d/ext/`) are kept here only as **first proposals for those platforms'
teams**: built and tested by hand (each one's README), they move into the platforms once adopted.

Each codec runs the same conformance check in its own tests. It reads the conformance GLBs and compares what it
reads with their `*.expected.json` (0.4's instances and archives included: the four codecs read, write and evaluate
them), and it runs `encoding3d validate` on what it writes. The steps are in the
[specification, §9](spec/specification.md#9-conformance).

Each platform has a column of `spec/vocabulary/standard_names.csv`, listing its own names for each standard name
(`;`-separated). The writers read their mapping from it (`openalea.encoding3d.vocabulary.platform_names("metafspm")`), so
the vocabulary changes without changing the platforms' code.
