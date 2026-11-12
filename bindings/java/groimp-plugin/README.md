# GroIMP's encoding3d plugin: a proposal for GroIMP

**Status: a first proposal, for GroIMP's team to take over** (listing in GroIMP's plugin manager, an import filter). It
lives here so that it could be built and tested before GroIMP's team is contacted; encoding3d's requirements and CI do
not depend on it.

A GroIMP plugin (`org.openalea.encoding3d`, GroIMP 3.0): **File > Export** of the 3D view to a `.glb` file, or the CLI's
`export3d file.glb`, writes the project as an encoding3d frame:

- the graph below the project's root: its scales, topology and the nodes' fields (`GroImp.toDataStructure`,
  `../groimp`);
- the scene's geometry as one mesh, each triangle carrying the rows of its node and of the node's complexes.

The shapes are meshed by GroIMP's glTF plugin (`de.grogra.gltf`, from GroIMP's plugin manager or
gitlab.com/grogra/groimp-plugins/gltf), which it requires.

```bash
mvn -f bindings/java/pom.xml install && mvn -f bindings/java/groimp/pom.xml install
mvn -f bindings/java/groimp-plugin/pom.xml package       # the plugin's folder: target/plugin/encoding3d
```

To install it, copy `target/plugin/encoding3d` into GroIMP's `plugins/` folder, next to the glTF plugin's.
`test/run_in_groimp.sh` does this in a GroIMP install, grows an example headless, exports it and checks the frame,
then writes GroIMP's log (a frame after each of four runs), which a coupling session replays. To run it by hand
(GroIMP 3.0.0, and GroIMP's glTF plugin at the commit it was last tested with):

```bash
curl -sSL -o groimp.deb https://download.grogra.de/3_0_0/GroIMP-3.0.0-all.deb
echo "b9b35811ff82482dfa676347639e40fe9601c92105f54095361a9a89f7e85dcf  groimp.deb" | sha256sum -c
dpkg-deb -x groimp.deb groimp-install
git clone https://gitlab.com/grogra/groimp-plugins/gltf.git gltf
git -C gltf checkout d093aaebe5197317dfb81fadbe0ef67268bdaf1c
mvn -f gltf/pom.xml install -DskipTests -Dmaven.javadoc.skip=true -Dgroimp.core.version=3.0.0
mkdir -p gltf-plugin/ext
cp gltf/target/gltf.jar gltf/src/main/resources/plugin.xml gltf/src/main/resources/plugin*.properties gltf-plugin/
cp gltf/target/lib/ext/*.jar gltf-plugin/ext/
bash bindings/java/groimp-plugin/test/run_in_groimp.sh groimp-install/usr/share/GroIMP gltf-plugin \
     bindings/java/groimp-plugin/target/plugin/encoding3d out
ENCODING3D_GROIMP_LOG=out/log/scene.fspm.json pytest bindings/python/test/test_coupling.py -k platform_log
```

Licence: GPL-3.0-or-later, as GroIMP.
