# fspm-TF

**One file format for whole plant-model scenes, shared by the FSPM platforms.**

Functional-structural plant models (FSPM) are written on several platforms: openalea.metafspm (Python), CPlantBox
(C++), GroIMP (Java) and VirtualPlantLab (Julia). fspm-TF lets them exchange what they simulate. A file holds a whole
scene at one time step:

- **the plants:** their organs and elements at every scale, from the plant down to the cell, and how they connect;
- **their variables and parameters**, each with its unit, its kind and a shared standard name;
- **their geometry**, as triangles;
- **the environment:** soil grids, and which soil cells each root element lies in.

A simulation writes one file per time step. Any platform can read them back. ParaView, Blender or any glTF viewer
can display them.

```{image} _static/images/archisimple.png
:alt: An ArchiSimple root system read from an fspm-TF file in ParaView, coloured by root order
:width: 360px
:align: center
```

The files are glTF 2.0 binaries (`.glb`): the 3D format of the web and of most viewers, extended with typed tables.

## Using fspm-TF

For those who run models and want to look at, keep or share their results.

```{toctree}
:maxdepth: 1

fspm-TF in five minutes <overview>
Viewing and checking files <using>
Reading and writing in Python <python>
A notebook: fspm-TF in Python <notebooks/fspm_tf_in_python>
```

## Implementing fspm-TF

For platform developers: how a platform reads and writes the format, and how the format evolves.

```{toctree}
:maxdepth: 1

Implementing a platform <platforms>
Changing the format <governance>
Implementations <implementations>
```

## Reference

The agreement itself, as the platforms discuss it. These pages are built from the files in the repository's
`spec/` folder.

```{toctree}
:maxdepth: 2

Specification <specification>
Vocabulary <vocabulary>
Python API <api>
Design note <design_note>
```
