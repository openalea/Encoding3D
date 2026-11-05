# Tutorial 2d: GroIMP

**What you learn:** how a GroIMP graph (its nodes, their managed fields, the plant's scales and its `>` and `+`
edges) is written as encoding3d frames, and turned back into GroIMP nodes; and how GroIMP users export a whole
project, with its 3D geometry, from GroIMP itself.

**What you need** (not encoding3d's requirements): Java 21 and Maven. The program uses GroIMP's Graph module, from
GroIMP's package registry (no GroIMP application), and GroIMP's adapter (`bindings/java/groimp/`), a proposal for
GroIMP kept in this repository until GroIMP adopts it.

**How to run it:** `./run.sh`. It installs encoding3d's Java codec and GroIMP's adapter in Maven's local repository,
then compiles and runs the program (`src/main/java/tutorial/`), which writes its files in `outputs/`. It is in three
parts:

1. **A GroIMP plant.** Node classes as an RGG model declares them: a `Plant`, `Internode`s and `Leaf`s, whose fields
   GroIMP manages (`Managed.java` declares them, as GroIMP's XL compiler does for a model's classes). The plant is
   made of its internodes (a `/` edge), each internode followed by the next (`>`) and bearing a leaf (`+`). It grows
   by code standing for an RGG rule: a new internode and leaf on top, every leaf longer.
2. **A frame per step.** `GroImp.toDataStructure` writes the plant and its organs as two entity sets, the edges as
   `parent` and `edge_type`, the managed fields as columns (`length` and `radius` declared in metres). Six steps make
   a sequence.
3. **Back into GroIMP.** `GroImp.toGraph` rebuilds each row as a node of its class, its fields set.

## From GroIMP itself: the plugin

GroIMP's encoding3d plugin (`bindings/java/groimp-plugin/`, also a proposal for GroIMP) exports a GroIMP project with
its geometry: in GroIMP, **File > Export** of the 3D view to a `.glb` file, or headless, the command `export3d
plant.glb`. Its README says how to build and install it; `bindings/java/groimp-plugin/test/run_in_groimp.sh` grows
GroIMP's `simpleRapeseed` example headless and exports a frame after each of four runs, a log other platforms can
replay (tutorial 3).

Try it yourself: add a field `area` to the leaves, manage it, declare it in `m2`, and check it in the frames with
`encoding3d info outputs/frames/frame_000005.glb`.
