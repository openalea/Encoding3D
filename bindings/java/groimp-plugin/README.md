# GroIMP's fspm-TF plugin

A GroIMP plugin (`org.openalea.fspmtf`, GroIMP 3.0): **File > Export** of the 3D view to a `.glb` file, or the CLI's
`export3d file.glb`, writes the project as an fspm-TF frame:

- the graph below the project's root: its scales, topology and the nodes' fields (`GroImp.toDataStructure`,
  `../groimp`);
- the scene's geometry as one mesh, each triangle carrying the rows of its node and of the node's complexes.

The shapes are meshed by GroIMP's glTF plugin (`de.grogra.gltf`, from GroIMP's plugin manager or
gitlab.com/grogra/groimp-plugins/gltf), which it requires.

```bash
mvn -f bindings/java/pom.xml install && mvn -f bindings/java/groimp/pom.xml install
mvn -f bindings/java/groimp-plugin/pom.xml package       # the plugin's folder: target/plugin/fspmTF
```

To install it, copy `target/plugin/fspmTF` into GroIMP's `plugins/` folder, next to the glTF plugin's.
`test/run_in_groimp.sh` does this in a GroIMP install, grows an example headless, exports it and checks the frame. It
is run by the `groimp-plugin` job of `.github/workflows/java-codec.yml`.

Licence: GPL-3.0-or-later, as GroIMP.
