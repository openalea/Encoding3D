# GroIMP's adapter: a proposal for GroIMP

**Status: a first proposal, for GroIMP's team to take over.** It lives here so that the Java binding could be built
and tested before GroIMP's team is contacted. Once they adopt it, it moves into GroIMP (or GroIMP's plugins), with its
tests and CI. encoding3d itself does not depend on it: the Java codec (`bindings/java`) builds without it, and
encoding3d's CI does not run it.

`org.openalea.encoding3d.groimp.GroImp`, on GroIMP's Graph module only (no GroIMP application):

- `toDataStructure(root, options)`: a GroIMP graph (its nodes, their scales, successor and branch edges, their fields)
  as an encoding3d graph data structure;
- `toGraph(dataStructure, nodes, idsOf)`: back, each row built as a node of the model's own classes.

GroIMP's plugin, which exports a GroIMP project with its geometry, is in `../groimp-plugin` (its own README).

## Building and testing it by hand

GroIMP's modules (graph, platform, vecmath, …, 3.0.0) come from GroIMP's package registry, declared in `pom.xml`.

```bash
mvn -f bindings/java/pom.xml install -DskipTests      # the codec
mvn -f bindings/java/groimp/pom.xml verify             # the adapter and its tests
encoding3d validate bindings/java/groimp/target/groimp_out/*.glb
```

The tests (`src/test/java/.../GroImpTest.java`) export a small GroIMP plant at several scales, read it back, rebuild it
as GroIMP nodes, and read another platform's frame.

Licence: GPL-3.0-or-later, as GroIMP.
