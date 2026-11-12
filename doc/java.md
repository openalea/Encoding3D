# Reading and writing in Java, and GroIMP

`bindings/java/` holds the Java codec (Java 17, Maven; dependencies Jackson, and xz-java for the archives' lzma members). It reads and writes encoding3d files and
passes the conformance check. In `bindings/java/groimp/` is GroIMP's adapter. Both have tests, run in
`.github/workflows/java-codec.yml`.

Licence: GPL-3.0-or-later, as GroIMP (the rest of encoding3d is CeCILL-C).

## The format's own tables

```java
import org.openalea.encoding3d.*;

Frame frame = Codec.read(Path.of("scene.glb"));
EntitySet segments = frame.dataStructure("RootPopulation").entitySet("SubOrgan");
double[] length = segments.column("length").doubles();           // one value per segment
String unit = segments.variables.get("length").unit;             // its declared unit, e.g. "m"

EntitySet organs = new EntitySet("Organ", 5L);
organs.set("id", Column.of(1L, 2L)).set("parent", Column.of(-1L, 1L))
      .set("edge_type", Column.of("none", "branch")).set("length", Column.of(0.12, 0.05));
organs.declare("length", new Variable("m", "length", "extensive", "state"));
DataStructure plants = new DataStructure("plants");
plants.entitySets.add(organs);
Frame written = new Frame();
written.dataStructures.add(plants);
Codec.write(Path.of("plants.glb"), written);
```

A `Column` holds a Java array of its type (`long[]`, `double[]`, `boolean[]`, `String[]`, …; unsigned integers in
the array of their width), with a `width` of 2 or more for a fixed-size vector per row, and its missing rows
(`withMissing(...)`, `isMissing(row)`; NaN in a float column). NaN and infinities are written
with the specification's stand-ins and read back as they were.

## Instances, derived fields and archives

The codec reads and writes 0.4's instance sets (specification §12, [Instances](instances.md)): an `InstanceSet` is a
table of one row per instance (`template`, `owner`, `transform`, `id` and its own variables), its `vectors` (`Ragged`)
and `derived` fields (`DerivedField`); its `parts` are keys, found through the frame (embedded, else
`parts/<key>.glb` next to it).

```java
Frame frame = Codec.read(Path.of("run.fspm.zip/frame_000003.glb"));     // a folder's file, or an archive's
InstanceSet sections = frame.dataStructure("RootPopulation").instanceSet("sections");
List<double[]> potentials = Instances.evaluate(frame, "water_potential");   // one array per instance
Part part = Parts.part(frame, sections.parts.get(0));                     // a Template or an Operator

Frame written = new Frame();                                              // writing: parts added by content
String key = Parts.add(written, Operator.dense(4, 2, new double[] {1, 0, 0.75, 0.25, 0.5, 0.5, 0.25, 0.75}));
// ... an InstanceSet whose parts hold key, in a data structure of written
Codec.write(Path.of("frames/frame_000000.glb"), written);                // and frames/parts/<key>.glb, once
Archives.pack(Path.of("frames"), Path.of("run.fspm.zip"));               // deflate, or "stored"
```

Archives are read stored, deflate (`java.util.zip.Inflater`) or lzma (xz-java), and packed stored or deflate
(`java.util.zip.ZipOutputStream`). A `solve` operator is solved by a dense LU factorisation (with partial pivoting),
once per operator and evaluation.

## Coupling with other platforms

`org.openalea.encoding3d.coupling.Participant` is a participant of the coupling sessions encoding3d's coordinator runs
([Coupling platforms](coupling.md)): `new Participant(declaration, endpoint, links, timeout)` joins one (the declaration
as its JSON; a null endpoint, the environment's when launched by the coordinator), `nextTurn()` gives each turn's
inputs until the session stops, `sendUpdate(frame)` answers. Its folder transport needs nothing; its ZeroMQ transport
needs JeroMQ (pure Java, an optional dependency) on the class path. `ConformanceParticipant` is its program for the
conformance sessions.

## GroIMP

```{note}
**A proposal for GroIMP.** This adapter is a first proposal for GroIMP's team to take over; it lives here until
they adopt it, then moves into GroIMP. encoding3d does not depend on it: its requirements and CI never install
GroIMP. To build and test it by hand, see `bindings/java/groimp/README.md`.
```

`GroImp.toDataStructure(root, options)` writes the graph below a GroIMP root:

| encoding3d | GroIMP |
|---|---|
| one entity set per scale | the nodes at one refinement depth (a successor or branch edge keeps the scale, a refinement edge adds one) |
| `id`, `label` | `Node.getId()`, the node's class's simple name |
| `complex` | the source of its incoming refinement edge, else its parent's complex |
| `parent`, `edge_type` | the source of its incoming successor (`successor`) or branch (`branch`) edge at the same scale |
| relations | the other edge bits (containment, mark, notifies, user edges), one relation per bit and pair of sets |
| variables | the managed fields of the model's classes (numbers, booleans, text; vecmath tuples as vectors) |

`options.scaleNames`, `options.scaleRanks` and `options.scaleScales` give each scale its entity set's name, rank and
base scale, e.g. the vocabulary's `Organ`, rank 5. `options.labels` maps the model's class names to the vocabulary's
labels, and `options.variables` declares the fields' units and standard names (GroIMP's fields have no units). A field
that other classes of the same scale lack is missing in their rows.
`GroImp.toGraph(dataStructure, label -> new Internode(), ids)` builds the nodes back: their fields, refinement,
successor and branch edges, and edge bits. It does this for any graph, e.g. metafspm's Plant, Axis and SubOrgan
become three scales linked by refinement edges.

The adapter depends on GroIMP's Graph module only.

## GroIMP's plugin

`bindings/java/groimp-plugin/` is a GroIMP 3.0 plugin. In GroIMP, **File > Export** of the 3D view to a `.glb` file
writes the project as an encoding3d frame, and the CLI's `export3d plant.glb` does the same headless:

- the graph, by the adapter above;
- the scene's geometry as one mesh, each triangle carrying the rows of its node and of its complexes (an instance's
  geometry: the node instantiating it).

GroIMP's glTF plugin, which it requires, meshes the shapes: cylinders, boxes, spheres, cones, frusta, planes,
parallelograms, NURBS, meshes and polygons. Its folder (`target/plugin/encoding3d`) is copied into GroIMP's `plugins/`.
`test/run_in_groimp.sh` installs both plugins in GroIMP 3.0.0, grows GroIMP's `simpleRapeseed` example headless and
exports it (456,900 vertices, each with its node), then checks the frame. It then writes GroIMP's log, a frame after
each of four runs (GroIMP has no simulation clock: each frame's time and step are its run count), which a coupling
session replays. Like the adapter, the plugin is a proposal for GroIMP, run by hand
(`bindings/java/groimp-plugin/README.md`), not by encoding3d's CI.

Not done yet: an import filter (frames into a GroIMP project), and units for GroIMP's fields, which have none.
