# Tutorial 4: four platforms, one plant

**What you learn:** how four platforms, in four languages, run one plant together through encoding3d, each with the
model it is good at, two building the plant's structure and two computing its functions.

| Platform | Its model (a toy) | Kind | In the shared plant | It gives | It needs |
|---|---|---|---|---|---|
| **CPlantBox** (C++, `cplantbox/roots.cpp`) | the root system, grown by CPlantBox's own rules (Anagallis' parameters) | structural | **owns** the plant, its root organs and their segments | each segment's length, radius and ends (cm) | — |
| **GroIMP** (Java, `groimp/.../Shoot.java`) | the shoot, a GroIMP graph of phytomers: a new one each time the roots have taken up 8 cm³ of water | structural | **owns** the phytomers, under CPlantBox's plant | each leaf's area (m²) and height (m) | the plant's water uptake (cm³/d) |
| **metafspm** (Python, `metafspm/uptake.py`) | root water uptake: through each segment's surface, more when the plant has more carbon | functional | **follows** the plant, organs and segments | each segment's uptake (cm³/d) | each segment's length and radius; the plant's assimilation |
| **VirtualPlantLab** (Julia, `virtualplantlab/light.jl`) | light (Beer–Lambert down the canopy) and photosynthesis (a light-use efficiency), on a PlantGraphs graph | functional | **follows** the plant and the phytomers | each leaf's absorbed light and assimilation; the plant's total (µmol/s) | each leaf's area and height |

The loop: the leaves' light → their assimilation → the roots' uptake → the water the shoot has → new leaves → more
light. The models are toys, labelled as such: the tutorial shows how platforms work together, not plant science.

## How they fit together

- **One plant, shared.** The session's data structure, `plant`, holds every platform's entities: CPlantBox's plant,
  root organs and segments, GroIMP's phytomers under the same plant. A platform declares the entity sets it works
  on, and what it may do with them: **own** them (create them), or **follow** them (read them). No platform needs to
  know the others' code or language.
- **Links, made by encoding3d's coordinator** (`session.py`):
  - metafspm's `length` and `radius` are found by their **standard name** among CPlantBox's outputs (the same unit
    here, cm; a different one would be converted);
  - VirtualPlantLab's `area` and `height` by their **name** among GroIMP's;
  - GroIMP's `water_uptake` of the plant is the **sum** of metafspm's uptake over the plant's segments (they are in
    the plant, through their organs);
  - metafspm's `plant_assimilation` of each segment is a **copy** of the plant's, given by VirtualPlantLab.
- **Stages.** At each daily step, CPlantBox grows the roots first, then GroIMP the shoot (it needs the plant
  CPlantBox created), then metafspm and VirtualPlantLab compute together.
- **What each platform does with what it receives:** CPlantBox's adapter writes its plant; GroIMP's writes its graph;
  metafspm builds its own graph from CPlantBox's roots (`RemoteComponent.join`) and computes with a metafspm
  component; VirtualPlantLab rebuilds the phytomers as a PlantGraphs graph (`to_graph`) and queries it.

## What you need

Not encoding3d's requirements: everything tutorials 2a to 2d need. CPlantBox built (tutorial 2c, `CPLANTBOX` and
`CPLANTBOX_LIBRARY`), Java 21 and Maven (tutorial 2d), Julia 1.12 or later (`JULIA` if not on the path), and
metafspm's environment active (tutorial 2a), whose Python runs the coordinator and metafspm's side.

## How to run it

```bash
CPLANTBOX=/path/to/CPlantBox CPLANTBOX_LIBRARY=/path/to/CPlantBox-build/src/libCPlantBox.a ./run.sh
```

It builds CPlantBox's and GroIMP's sides, prepares the Julia project, then runs `session.py`, which launches the four
models, each in its own process, for ten days. Each prints what it does at each step, and the coordinator prints how
it linked them. The whole plant is recorded at each step in `outputs/record/`, with a `views.json` colouring the
roots by uptake: open `outputs/record/scene.fspm.json` in ParaView with encoding3d's plugin (tutorial 1) and press
*Play*.

## Try it yourself

- Make phytomers cheaper (`WATER_PER_PHYTOMER` in `Shoot.java`) and watch the canopy close: assimilation saturates.
- Give metafspm's uptake a soil water potential, from a fifth participant owning a soil grid, linked to the roots
  by a mapping (the coupling documentation, "Coupling platforms").
- Replace one platform by the record of an earlier run: `encoding3d couple --replay` (the coupling documentation).
