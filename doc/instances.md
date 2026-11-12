# Instances, derived fields and archives

Some parts of a scene are drawn many times with the same shape: the cross-sections of a plant's root segments, the
cells of a tissue drawn at a coarse scale, the leaves of a canopy drawn by a few shapes. encoding3d stores such a
shape once, as a **template**, and one small record per copy, an **instance**. Their inner values can be stored the
same way: a **derived field** is rebuilt for each instance from a few of its values by a matrix stored once, an
**operator**. Templates and operators are **shared parts**, written once for a whole sequence. The specification's
§12 defines them; this page shows how to read them, how a platform writes them, and how to pack a sequence into one
file to share it.

## Reading instances

A frame's instances are in its data structures' `instance_sets`. Each one is a table, one row per instance, with:

- `template`: which template the instance draws (an index in the set's `parts`);
- `owner`: the id of the entity it draws (in the set's `owners`, e.g. the segments `SubOrgan`);
- `transform`: where it is (a 4×4 matrix, column by column, from the template's coordinates to the data structure's);
- its own variables (e.g. an age), as in any table;
- its **vectors**, one array per instance (`instance_set.vectors["ends"][row]`), and its **derived fields**.

```python
from openalea import encoding3d

frame = encoding3d.read("outputs/frames/frame_000024.glb")      # its parts are found in outputs/frames/parts/
sections = frame.data_structure("roots").instance_set("sections")
sections.columns["owner"], sections.columns["age"]               # the instances' own values: no part needed

values = encoding3d.evaluate(frame, "water_potential", instances=[0, 5])   # the cells' values of two sections
placed = encoding3d.placed_meshes(frame, "roots", "sections", instances=[0, 5])   # their triangles, placed
template = frame.part(sections.parts[0])                         # a Template: its entity sets and meshes
```

`evaluate` rebuilds the field of the instances asked for (all by default), one matrix product per operator over every
instance using it, so rebuilding many instances of a few templates stays cheap. A reader that does not need inner
values reads the instance table and the templates' own constant values only.

**ParaView** draws instance sets as their placed templates, with their own variables, and rebuilds the derived
fields of the instances you select (*encoding3d Select at scale*) or of all of them (*Evaluate Derived Fields*):
see [Viewing and checking files](using.md) and `paraview/README.md`.

**Parts.** A frame refers to each part by a key, the SHA-256 of the part's file. A part is embedded in the frame, or
at `parts/<key>.glb` next to it. When a part is missing, `frame.part`, `evaluate` and the validator name its key
(`encoding3d.MissingPartError`): copy the whole folder of the frames, or share the sequence as an archive.

## Archives: one file to share

A sequence is a folder: the index `scene.fspm.json`, `views.json`, the frames and `parts/`. A run writes it frame by
frame (a folder survives a crash and grows as the run goes). To send or keep it, pack it into one `.fspm.zip` file:

```bash
encoding3d pack outputs/frames run.fspm.zip                 # deflate, the default; checked, then the folder removed
encoding3d pack outputs/frames run.fspm.zip --keep-folder   # the folder kept
encoding3d pack outputs/frames run.fspm.zip --compression lzma   # smaller, slower: for archiving
encoding3d validate run.fspm.zip                            # every frame and part, as for the folder
encoding3d unpack run.fspm.zip folder                       # the folder back
```

`pack` checks the archive once it is written, before it replaces any archive at that path: every file of the
folder's sequence is a member and nothing else, of the same size and CRC-32, each member read back (decompressed,
its CRC-32 computed again), and the archive passes the validator with no error (warnings allowed). Only then is
the folder removed, unless `--keep-folder`. When the check fails, the archive is not written, the folder stays and
the command exits with 1 (Python: `encoding3d.ArchiveCheckError`). A folder holding files that are not its sequence's
(say, notes, or parts no frame uses: `encoding3d prune` removes those) is not removed: `pack` refuses before writing,
and `--keep-folder` packs it, leaving those files out.

Each file is compressed alone, so a reader opens one frame without the others. `encoding3d.read`, `read_index`,
`read_sequence`, the validator and ParaView open an archive as they open the folder; a file inside it is named
`run.fspm.zip/frame_000024.glb`. In Python: `encoding3d.pack(folder, path, compression="deflate",
keep_folder=False)`, `encoding3d.check_archive(path, folder)` (the check alone) and `encoding3d.unpack(path,
folder)`. The C++, Java and Julia codecs read archives as folders too (stored, deflate and lzma
members) and pack them (`pack_archive`, `Archives.pack`; [C++](cpp.md), [Java](java.md), [Julia](julia.md)), and
read, write and evaluate instances.

Measured on a metafspm run's frames (use case 1, 57 frames, 2.6 GB; six frames from 3 MB to 198 MB, 451 MB, packed
one at a time):

| compression | size | packing | reading |
|---|---|---|---|
| `stored` | 100 % | 1,080 MB/s | 1,330 MB/s |
| `deflate` (default) | 11.6 % | 79 MB/s | 540 MB/s |
| `lzma` | 4.1 % | 17 MB/s | 310 MB/s |

Deflate is the default: every ZIP reader has it, it packs a run's 2.6 GB in about half a minute and reads a 200 MB
frame in 0.4 s. lzma makes archives 2.8 times smaller again, for keeping runs, at 4.6 times the packing time.

## Writing instances: for platforms

A platform writes instances when it draws many entities with one shape. It builds the templates and operators once
(they are immutable: their key is taken from their content the first time it is needed), and each frame's instance
sets refer to them.

```python
import numpy as np
from openalea import encoding3d

cells = encoding3d.EntitySet("Cell", columns={"label": labels, "area": areas})        # the template's own entities
section = encoding3d.Template(entity_sets=[cells], meshes=[encoding3d.Mesh(
    "section", positions=vertices, indices=triangles, feature_rows={"Cell": cell_of_vertex})])
recovery = encoding3d.Operator.dense(matrix)            # (cells, kept values); or .sparse(m), .solve(S, R)

sections = encoding3d.InstanceSet(
    "sections", owners="SubOrgan", parts=[section, recovery],
    columns={"owner": segment_ids, "template": np.zeros(count, dtype=np.int64),
             "transform": encoding3d.column_major(placements),            # (count, 4, 4) -> (count, 16)
             "age": ages},
    variables={"age": encoding3d.Variable(unit="d")},
    vectors={"kept": encoding3d.Ragged.of(kept_values)},                  # one array per instance
    derived=[encoding3d.DerivedField("water_potential", entity_set="Cell", input="kept",
                                     operators=np.ones(count, dtype=np.int64),      # parts[1] for every instance
                                     variable=encoding3d.Variable(unit="MPa", role="derived"))])
data_structure.instance_sets = [sections]

keys = encoding3d.write("frames/frame_000024.glb", frame)   # parts/<key>.glb written when new; their keys
encoding3d.write_index("frames/scene.fspm.json", entries, time_unit="s", parts=all_keys)
```

- **The field.** For an instance with vector v, a derived field is Σ_k w_k · (A_k · v + b_k) over its terms: `operators`
  and `weights` have one row per instance and one column per term (−1: no term), `offsets` names a vector per term (or
  None). Its values are on the rows of `entity_set` in the instance's template.
- **Several terms** blend operators: an instance between two classes of a model (two templates' operators, say a
  short and a long segment's) takes both, weighted.
- **The operator's format.** `Operator.dense(X)` stores X; `Operator.sparse(X)` its non-zeros;
  `Operator.solve(S, R)` stores a sparse system and its right-hand side, the reader solving S x = R v when it
  evaluates. `Operator.of_system(S, R, max_dense=n)` chooses: S⁻¹R computed and stored dense when it holds at most n
  values, else the system (S⁻¹R is dense even when S is sparse).
- **Each part once.** `write` writes a part only when `parts/<key>.glb` does not exist, and returns the keys the frame
  uses; list them in the index (`write_index(..., parts=)`). When a writer removes frames (a run restarted from a
  checkpoint), `encoding3d.prune_parts(index)` removes the parts no remaining frame uses and lists the others in the
  index (`encoding3d prune` from a terminal).
- **One self-contained frame.** `encoding3d.write(path, frame, embed_parts=True)` puts the frame's parts inside it.

### Example: a reduced network, its eliminated nodes recovered

A platform that reduces a linear network A x = f (a hydraulic network, a diffusion between compartments) to its kept
nodes B by eliminating the inner nodes I (a Kron reduction, or static condensation) solves only for x_B. The inner
values follow linearly:

  x_I = A_II⁻¹ (f_I − A_IB x_B)

so each reduced entity is an instance: its template is the full entity's mesh, its vector is [x_B, f_I], and its
operator is `Operator.solve(A_II, [−A_IB | I])` (or `Operator.of_system(...)` to store A_II⁻¹[−A_IB | I] dense when
small). The sources f_I sit in the vector, so the frame holds no array of the full size per instance. The whole
field (kept and inner nodes) is one operator when the template's rows are all nodes: stack the identity rows of the
kept nodes over the recovery.

```python
kept, inner = template_kept_rows, template_inner_rows
system = A[np.ix_(inner, inner)]
right = np.hstack([-A[np.ix_(inner, kept)], np.eye(inner.size)])
operator = encoding3d.Operator.of_system(system, right, max_dense=1 << 20)
vector = np.concatenate([x_kept, f_inner])                       # per instance
```

### Example: a coarse cell whose interior is a linear recovery

A grid model at a coarse scale (a soil voxel, a tissue's coarse cell) may know how its value is distributed inside
(a value and a gradient, a few modes). Its sub-cells are a template (their geometry, their positions p_k relative to
the cell's centre), the instance's vector holds the cell's value u and gradient g, and the operator's row k is
[1, p_k]: u_k = u + g · p_k. Every coarse cell of the same shape shares the template and the operator, whatever its
size (its transform scales it).

```python
operator = encoding3d.Operator.dense(np.c_[np.ones(len(centres)), centres])   # (sub-cells, 4)
vectors = encoding3d.Ragged.of(np.c_[values, gradients])                       # (cells, 4)
```

Nothing in either example depends on the model: any platform whose entities have a declared shape and a declared
linear recovery writes them this way, at any scale.
