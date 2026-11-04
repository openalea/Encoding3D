# encoding3d (Java)

The Java codec of encoding3d (Java 17, Maven): reading and writing frames and sequences (spec 0.3), with one dependency,
Jackson. GroIMP's adapter is in `groimp/`.

- `src/main/java/org/openalea/encoding3d/`: the data model (`Frame`, `DataStructure`, `EntitySet`, `Column`, …), the GLB
  container (`Glb`), reading and writing (`Codec`), sequences (`Sequences`), the conformance dump (`Dump`) and tool
  (`ConformanceRun`).
- `src/test/`: the tests, the conformance files included.
- `groimp/`: GroIMP's adapter (`org.openalea.encoding3d.groimp.GroImp`, Java 21), on GroIMP's Graph module.

```bash
mvn -f bindings/java/pom.xml verify
```

`org.openalea.encoding3d.coupling` is a participant of coupling sessions (its ZeroMQ transport with JeroMQ, an optional
dependency).

Licence: GPL-3.0-or-later (`LICENSE`), as GroIMP; the rest of encoding3d is CeCILL-C. See
[the documentation](../../doc/java.md).
