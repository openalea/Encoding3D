# fspm-tf (Java)

The Java codec of fspm-TF (Java 17, Maven): reading and writing frames and sequences (spec 0.1), with one dependency,
Jackson. GroIMP's adapter is in `groimp/`.

- `src/main/java/org/openalea/fspmtf/`: the data model (`Frame`, `DataStructure`, `EntitySet`, `Column`, …), the GLB
  container (`Glb`), reading and writing (`Codec`), sequences (`Sequences`), the conformance dump (`Dump`) and tool
  (`ConformanceRun`).
- `src/test/`: the tests, the conformance files included.
- `groimp/`: GroIMP's adapter (`org.openalea.fspmtf.groimp.GroImp`, Java 21), on GroIMP's Graph module.

```bash
mvn -f bindings/java/pom.xml verify
```

See [the documentation](../../doc/java.md).
