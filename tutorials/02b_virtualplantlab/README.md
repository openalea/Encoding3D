# Tutorial 2b: VirtualPlantLab

**What you learn:** how a VirtualPlantLab plant (a PlantGraphs graph grown by rules, drawn by a turtle) is written as
encoding3d frames with its geometry, how a frame becomes a VirtualPlantLab graph again that keeps growing, and how an
MTG (MultiScaleTreeGraph.jl, used by VirtualPlantLab and PlantSimEngine) goes to and from encoding3d.

**What you need** (not encoding3d's requirements: this folder's own Julia project, `Project.toml`): Julia 1.12 or
later. The project takes encoding3d.jl from this repository and VirtualPlantLab's packages (PlantGraphs,
PlantGeomTurtle, PlantGeomPrimitives) and MultiScaleTreeGraph.jl from Julia's registry; encoding3d.jl's extensions
for them load with them. These extensions are proposals for VirtualPlantLab and MTG.jl
(`bindings/julia/README.md`).

**How to run it:** `./run.sh` (the first time, Julia installs and compiles the packages: a few minutes). It writes its
files in `outputs/`. The script, `virtualplantlab.jl`, is in four parts:

1. **A plant.** Three node types (`Internode`, `Leaf`, `Meristem`), how the turtle draws them (a cylinder, an
   ellipse), and a rule: each step, the meristem makes an internode, two opposite leaves and a new meristem.
2. **A frame per step.** `from_graph` writes the graph's nodes as one entity set, `Organ`, each node a row with its
   type as label and its fields as columns (`length` declared in metres); `add_geometry!` adds the turtle's
   triangles as a mesh, each vertex knowing its node. Five steps make a sequence.
3. **Back into VirtualPlantLab.** `to_graph` rebuilds each row as a node of its type; wrapped in a `Graph` with the
   same rule, the plant grows on from where the file left it.
4. **An MTG.** The conformance root system (written by another platform, three scales) becomes an MTG with
   `to_mtg` (the MTG's scale 0 is its scene, its root), and an encoding3d data structure again with `from_mtg`.

Open `outputs/frames/scene.fspm.json` in ParaView with encoding3d's plugin (tutorial 1) to see the plant grow.

Try it yourself: give the leaves a field `area`, declare it in `cm2`, and colour the leaves by it in a `views.json`.
