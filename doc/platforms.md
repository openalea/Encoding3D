# Implementing a platform

A platform reads and writes fspm-TF through two pieces of code, which live in different places.

| | What it does | Depends on | Lives in |
|---|---|---|---|
| **The codec** | reads and writes the files: the GLB container, the typed tables, sequences and their index, the vocabulary | `spec/` only | this repository, `bindings/<language>/` |
| **The adapter** | turns the codec's tables into the platform's own model, and back | the platform's internals | the platform's repository |

## The codec

The codec is the format in a language. The Python one, `bindings/python/`, is the reference.

What it has to handle:

- **The GLB container:** a 12-byte header (magic `glTF`, version 2, total length), a JSON chunk and a binary chunk,
  both padded to 8 bytes.
- **The JSON:** the glTF document, with two extensions.
  - `EXT_structural_metadata` declares the tables' classes and points to their columns in the binary chunk.
  - `FSPM_scene` describes the scene: its data structures and their entity sets, relations, grids, meshes and
    mappings; the frame's time; the variables' declarations.
- **The tables:** each column is a slice of the binary chunk, little-endian, of its declared type. Booleans are bits;
  text is UTF-8 with offsets; labels are enums; NaN and infinities use the stand-ins the specification gives.
- **Meshes:** float32 positions, and one feature ID attribute per scale a mesh represents.
- **Sequences:** the index `scene.fspm.json`.

This is a few hundred lines in any language. Existing libraries help:

- **C++:** cesium-native reads and writes `EXT_structural_metadata`.
- **Java:** JglTF has its JSON classes.
- **Julia:** a small GLB reader is enough; `GLTF.jl` handles the JSON.

Each codec goes in its own folder, with its usual build files and tests:

```
bindings/
  python/                    the reference (openalea.fspm_tf)
  cpp/                       CMakeLists.txt, include/, src/, test/
  java/                      pom.xml or build.gradle, src/main/, src/test/
  julia/FspmTF/              Project.toml, src/, test/
```

A codec is released by its team on its own channel (conda, Maven, the Julia registry), under its own tag (e.g.
`cpp-v0.1.0`), and states the specification version it implements.

## The adapter

The adapter maps the platform's model onto the format's tables:

- its scales onto entity sets, and its topology onto `complex`, `parent` and `edge_type`;
- its variables onto columns, declared with their units and kinds;
- its geometry onto meshes, and its soil and mappings onto grids and mapping tables.

What the platform needs to rebuild its own model exactly, beyond the shared data model, may go in the data
structure's `extras` (under the platform's name) and in columns of role `setting`. Other readers keep them without
interpreting them.

**Example:** metafspm's adapter, `openalea.metafspm.io.fspm_tf`, rebuilds its multiscale graphs bit for bit from its
own files, and a simulation continues from them exactly as from the original. It reads its standard names from its
column of the vocabulary.

**Standard names.** A platform lists its names for each standard name in its column of
`spec/vocabulary/standard_names.csv`. Its adapter reads its mapping from there, so the vocabulary can change
without changing the platform's code.

## Passing conformance

`conformance/` holds reference scenes: a root system, a wheat shoot, a cell network, soil with roots and their
mapping, an adaptive grid, a parameter set, and a growing sequence. Each GLB comes with its expected values,
`*.expected.json`. A codec conforms to a version of the specification when it passes two checks.

- **Reading:** everything it reads from each conformance GLB equals the expected JSON.
  - Floats are compared exactly.
  - NaN is `null`; infinities are the strings `"Infinity"` and `"-Infinity"`.
  - Positions are the float32 values.
- **Writing:** what it writes, for the same scenes, passes `fspm-tf validate` with no error. It also passes Khronos'
  glTF-Validator with no error, so that every viewer opens it.

`conformance/README.md` gives the layout of the expected JSON. A codec dumps what it reads from each conformance
GLB in that layout (`x.json` for `x.glb`), and writes the same scenes back as GLB files. Then:

```bash
fspm-tf compare-all dumps/ conformance/       # reading: every dump equals its expected values, or the differences
fspm-tf validate written/*.glb                # writing
```

In GitHub Actions, the composite action `.github/actions/conformance` runs both, plus Khronos' glTF-Validator,
after the codec's own steps:

```yaml
- name: Dump and write the conformance scenes
  run: <the codec's command> conformance out          # out/dumps/x.json, out/written/x.glb
- uses: ./.github/actions/conformance
  with:
    dumps: out/dumps
    written: out/written
```

The Python codec does exactly this (`bindings/python/conformance_run.py`, the `python-codec-conformance` job).

A codec that passes is listed in [Implementations](implementations.md) with the version it passes.
