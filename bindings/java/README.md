# encoding3d (Java)

The Java codec of encoding3d (Java 17, Maven): reading and writing frames and sequences (spec 0.4: instance sets, derived
fields evaluated, shared parts, `.fspm.zip` archives read and packed). GroIMP's adapter is in `groimp/`.

- `src/main/java/org/openalea/encoding3d/`: the data model (`Frame`, `DataStructure`, `EntitySet`, `Column`, …), the GLB
  container (`Glb`), reading and writing (`Codec`), sequences (`Sequences`), instance sets (`InstanceSet`, `Ragged`,
  `DerivedField`), shared parts (`Template`, `Operator`, `Parts`), derived fields evaluated (`Instances`), archives
  (`Archives`), the conformance dump (`Dump`) and tool (`ConformanceRun`).
- `src/test/`: the tests, the conformance files included.
- `groimp/`: GroIMP's adapter (`org.openalea.encoding3d.groimp.GroImp`, Java 21), on GroIMP's Graph module.

```bash
mvn -f bindings/java/pom.xml verify
```

`org.openalea.encoding3d.coupling` is a participant of coupling sessions (its ZeroMQ transport with JeroMQ, an optional
dependency).

Dependencies: Jackson (JSON); xz-java (`org.tukaani:xz`, public domain), for the archives' lzma members (ZIP's method
14). The archives' ZIP64 central directory is read by `Archives`, deflate through `java.util.zip.Inflater`; packing uses
`java.util.zip.ZipOutputStream` (stored or deflate; ZIP64 when needed). Archives are packed stored or deflate; lzma ones
are read only.

Licence: GPL-3.0-or-later (`LICENSE`), as GroIMP; the rest of encoding3d is CeCILL-C. See
[the documentation](../../doc/java.md).
