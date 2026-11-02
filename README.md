# FSPM-TF - Functional Structural Plant Model Transmission Format - based on GLTF 2.0

An exchange format for whole functional-structural plant model (FSPM) scenes, across platforms and languages
(openalea.metafspm, CPlantBox, GroIMP, VirtualPlantLab). It holds:

- multiscale plant graphs;
- their state variables and parameters;
- their geometry;
- the environment's grids.

Each time step is one glTF file, and the variables share one vocabulary. It also aims to serve as an in-memory
interface for coupling components across platforms.

Status: specification 0.1, draft.

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
| `spec/schema/` | the JSON Schemas of the `FSPM_scene` extension and of a sequence's index | **yes** |
| `spec/vocabulary/` | the standard names (units, kinds, definitions, and each platform's names for them), the labels with their Plant Ontology terms, the enumerations | **yes** |
| `conformance/` | reference files, each a GLB with its expected values as JSON, written by `generate.py`: the specification as test cases for every platform's code (`conformance/README.md`; checked with `fspm-tf compare-all` and the action `.github/actions/conformance`) | follows `spec/` |
| `bindings/<language>/` | each language's codec, with its own build, tests and release; `bindings/python/`: `openalea.fspm_tf`, the reference (codec, validator, display copies, command line), which reads `spec/` and ships it; `bindings/julia/`: FspmTF.jl, the Julia codec, with a MultiScaleTreeGraph.jl extension | no |
| `paraview/` | the ParaView reader plugin, and the script checking it in a `pvpython` | no |
| `doc/design_note.md` | how the decisions were reached | no |
| `pyproject.toml`, `conda/` | the Python package's build, at the root next to `spec/`, which it ships | no |

## The Python package

```bash
git clone https://github.com/openalea/fspm-TF.git
cd fspm-TF
mamba env create -f conda/environment.yml        # numpy and jsonschema from conda-forge, then pip install -e .
mamba activate fspm_tf
pytest
```

```python
from openalea import fspm_tf

frame = fspm_tf.read("scene.glb")                # data structures, entity sets as numpy columns, meshes
fspm_tf.write("copy.glb", frame)
```

```bash
fspm-tf validate scene.glb                       # or a sequence: fspm-tf validate run/scene.fspm.json
fspm-tf info scene.glb
fspm-tf display scene.glb water_potential        # float32 per-vertex copies, for viewers such as ParaView
```

## Viewing in ParaView

`paraview/fspm_tf_reader.py` is a ParaView reader plugin (ParaView ≥ 5.10):

1. In ParaView, open Tools → Manage Plugins → Load New…, and choose the file. Tick "Auto Load" to keep it loaded.
2. File → Open a `.glb` frame or a sequence's `scene.fspm.json`, and pick "fspm-TF reader".

What it shows:

- Each data structure is a block: its meshes, its segments as lines (for a Tube filter on `radius`) and its grid.
- Every variable of every scale is a data array named `<entity set>.<variable>`, at full precision, with no display
  copies needed. A sequence's frames are the time steps.
- Text columns such as labels become integer codes, `<entity set>.<column>_code`; the names behind the codes are in
  the block's field data.

The plugin finds `openalea.fspm_tf` in ParaView's Python if it is installed there, otherwise in this clone's `bindings/python/src/`.
It needs nothing beyond what ParaView ships (numpy). In `pvpython` scripts the reader is
`fspmTFreader(FileName=...)`, after `LoadPlugin("paraview/fspm_tf_reader.py", ns=globals())`. Checked with
ParaView 6.0.1: `pvpython paraview/check_in_paraview.py conformance` (also run by the tests when
`FSPM_TF_PVPYTHON` names a pvpython).

## For another platform

Two pieces of code make a platform read and write fspm-TF:

- **A codec** for its language: GLB files, property tables, sequences, the vocabulary. It depends on `spec/` only, so it
  lives here, in `bindings/<language>/` (`cpp/`, `java/`, `julia/`...), with its build files, its tests and its own
  release, maintained by the platform's team. A change to `spec/` then updates every codec in the same pull request,
  and the CI shows which languages follow.
- **An adapter** between the codec's tables and the platform's own model (e.g. `openalea.metafspm.io.fspm_tf` for
  metafspm's DataStructures). It depends on the platform, so it lives in the platform's repository.

Each codec runs the same conformance check in its own tests. It reads the conformance GLBs and compares what it
reads with their `*.expected.json`, and it runs `fspm-tf validate` on what it writes. The steps are in the
[specification, §9](spec/specification.md#9-conformance).

Each platform has a column of `spec/vocabulary/standard_names.csv`, listing its own names for each standard name
(`;`-separated). The writers read their mapping from it (`openalea.fspm_tf.vocabulary.platform_names("metafspm")`), so
the vocabulary changes without changing the platforms' code.
