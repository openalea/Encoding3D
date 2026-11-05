# Tutorial 3: metafspm and VirtualPlantLab, one plant

**What you learn:** how two platforms, each in its own language and process, work on the same plant and exchange
their values at each step through encoding3d: a coupling session.

- **metafspm** (Python) grows the roots: each tip elongates as fast as its sugar allows (structural: it creates the
  segments).
- **VirtualPlantLab** (Julia, `carbon.jl`) is the carbon model: it splits each segment into two tissue layers, grown
  by a PlantGraphs rule, and computes their sugar from the segment's mass (functional, adding entities of its own at
  a finer scale).
- encoding3d's **coordinator** runs the session: it keeps the shared plant, passes each model the values it needs
  (converting grams to milligrams, copying a segment's mass to its layers, averaging the layers' sugar back to their
  segment), and tells each model when to run.

Both models are toys: the tutorial shows the coupling, not plant science.

**What you need** (not encoding3d's requirements): metafspm's environment, as in tutorial 2a, and Julia 1.12 or later
for VirtualPlantLab's side (this folder's `Project.toml`: encoding3d.jl from this repository, PlantGraphs, ZMQ).

**How to run it:** `./run.sh` (`JULIA=/path/to/julia ./run.sh` if Julia is not on the path). It prepares the Julia
project, then runs `coupling.ipynb`, which starts the coordinator, launches `carbon.jl` and runs metafspm's scene.
Its files are in `outputs/`: the coordinator's record of the shared plant (`record/`) and metafspm's own frames
(`metafspm/`). The notebook explains:

1. metafspm's root growth, with its sugar as an input;
2. VirtualPlantLab's model seen from metafspm: a `RemoteComponent`, computing nothing, whose state variables are the
   other model's outputs, with metafspm's rights on the plant's scales and the links between their names;
3. the session: the coordinator, VirtualPlantLab's model launched, metafspm's scene run;
4. what happened, from the coordinator's record.

Open `outputs/metafspm/frames/scene.fspm.json` in ParaView with encoding3d's plugin (tutorial 1) and colour the roots
by `C_hexose_root`.
