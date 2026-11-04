# Coupling platforms

encoding3d also runs models of several platforms together, one time step after the other. This is a **session**:

- each platform's model is a **participant**, running in its own process and its own language;
- a **coordinator** (encoding3d's, in Python) starts them, passes each one the values it needs from the others, and
  keeps the plant they share.

Two platforms can work on the same plant: one grows the organs, another splits them into segments and computes a
function on them, a third reads the plant from a recorded run. Each one only says what it works on, what it
provides and what it needs; the coordinator does the rest.

The rules are in the specification's §11 (version 0.3, a draft the other platforms' teams are to review). Python,
Julia, C++ and Java have a participant; the coordinator is Python's.

## What a participant says

A participant **declares**:

- the entity sets it works on (`Organ`, `SubOrgan`, …) and what it may do with their entities: `owns` (it creates
  and removes them), `refines` (it adds its own entities under others', e.g. segments under organs), `follows` (it
  reads them);
- the variables it **provides** (its outputs) and **requires** (its inputs), each with its unit and, if the
  vocabulary has one, its standard name.

A **link** says which output feeds which input, when the names differ: a factor, and a change of scale (a sum or a
mean of finer entities, a copy of a coarser one's value). Without a link, an input is fed by the output with the
same standard name, else the same name. Units are converted.

Two **data structures** (a plant and a soil grid, say) are linked through a **mapping**, the weights between their
entities, which one participant provides with its outputs (declared in its `mappings`, sent as the frame's mapping).
The link names it: `Link("plant", "water", "soil", "water_content", mapping="roots_in_soil")`. Through it, `sum`
shares each source's amount among its targets in proportion to the weights (the total is kept), and `mean` gives each
target the weighted mean of its sources.

A participant declares only what it works on. A model growing the organs needs to know nothing of the segments
another platform refines them into: it is never sent them, and when it removes an organ, the coordinator removes its
segments and tells their refiner.

## A session in Python

A participant needs the encoding3d codec, and nothing else of the other platforms:

```python
from openalea import encoding3d
from openalea.encoding3d.coupling import Declaration, EntitySetSpec, Participant, VariableSpec

declaration = Declaration("function", entity_sets=[EntitySetSpec("plant", "Organ"),
                                                   EntitySetSpec("plant", "SubOrgan", rights="refines")],
                          variables=[VariableSpec("plant", "SubOrgan", "segment_length", "requires", "m", "length"),
                                     VariableSpec("plant", "SubOrgan", "sugar", "provides", "mol")])
participant = Participant.connect(declaration)          # the session's address and its name come from the coordinator
for turn in participant.turns():                         # until the coordinator stops the session
    plant = turn.frame.data_structure("plant")           # the organs and segments, the segments' lengths
    ...                                                  # the model, from turn.time to turn.until
    participant.send(frame)                              # its new segments and their sugar
```

Each turn is a frame holding the participant's entity sets and inputs, and the answer is a frame holding its new
entities and outputs (only those: the coordinator keeps the rest). The entities it creates take ids from
`participant.id_offset`.

## A session in Julia, C++ or Java

The same participant in Julia (encoding3d.jl; ZeroMQ needs `using ZMQ`):

```julia
using encoding3d, ZMQ

participant = Participant(Declaration("function"; entity_sets = [...], variables = [...]))
for turn in turns(participant)
    plant = data_structure(turn.frame, "plant")
    # the model
    send_update(participant, frame)
end
```

In C++ (`encoding3d/coupling.hpp`; ZeroMQ when built with libzmq) and Java (`org.openalea.encoding3d.coupling`; ZeroMQ with
JeroMQ on the class path), the declaration is its JSON:

```cpp
encoding3d::coupling::Participant participant(declaration);         // a JSON declaration (nlohmann)
while (auto turn = participant.next_turn()) {
    // the model, on turn->frame
    participant.send_update(frame);
}
```

```java
try (Participant participant = new Participant(declaration, null, null, null)) {
    for (Turn turn; (turn = participant.nextTurn()) != null; ) {
        // the model, on turn.frame()
        participant.sendUpdate(frame);
    }
}
```

## Running it

The coordinator starts each participant's command, and waits for the ones started otherwise (`--expect`):

```bash
encoding3d couple --steps 30 --interval 1 --time-unit d \
    --participant growth="julia --project=vpl growth.jl" \
    --participant function="python function.py" \
    --links links.json --record run/
```

- `--links`: a JSON list of links, e.g.
  `[{"receiver": "growth", "variable": "supply", "provider": "function", "source": "sugar"}]`.
- `--record`: the whole session written as an ordinary sequence of frames, to read in ParaView or to replay.
- `--replay name=run/scene.fspm.json`: a recorded run takes part as a participant, without its platform running.
  A platform's routine log can thus feed another platform's model. CPlantBox's and GroIMP's logs are tested this way.
- `--endpoint files:folder`: the participants exchange files in a folder instead of ZeroMQ messages. It is slower,
  but needs nothing but a file system. Each message is deleted once read; `--keep-messages` keeps them all, as the
  session's log (a turn of 100,000 segments with five variables is about 5 MB: plan the disk space). The usual log
  is `--record`.
- `--stages "growth;function"`: who runs first in each step (by default, the participants creating entities, then
  the others). Each step, a stage sees what the previous stages did in that step.

In Python, `openalea.encoding3d.coupling.Coordinator` does the same from a script.

## In metafspm

metafspm's `RemoteComponent` (`openalea.metafspm.io.coupling`) stands for another platform's model inside a metafspm
model: a component computing nothing, whose state variables are the other model's outputs and whose inputs are sent
to it. Its tests couple metafspm's root growth to a carbon model written in VirtualPlantLab.

## How fast it is

The exchange's own cost per step, with the coordinator and two participants in separate processes, each sending five
variables on every segment:

| Segments | ZeroMQ | A folder |
|---|---|---|
| 1,000 | 3 ms | 12 ms |
| 10,000 | 9–11 ms | 21 ms |
| 100,000 | 99–108 ms | 110–122 ms |

ZeroMQ here goes through the local network interface (`tcp://127.0.0.1`), its messages held in memory; the folder's
messages are files. The folder costs about 10 ms more per step (its polling and file writes).

Encoding and decoding the frames is about a tenth of it (10 ms for 100,000 segments); the rest is the coordinator's
work on the shared structure, in Python.

## Checking a participant

`conformance/coupling/` holds conformance sessions: a peer the coordinator replays, and what the participant under
test must read and send. `encoding3d couple-conformance conformance/coupling --participant COMMAND` runs them over both
transports; each codec's CI runs its own participant (Python, Julia, C++, Java) this way.

## How it behaves

- The coupling is explicit: a participant's inputs at a step are what the others gave at their previous turn.
- Entities removed by their owner are removed, with their finer entities, from every participant that follows them.
- A participant receiving new entities gives its own variables on them their initial values, and shares its own
  quantities when an entity splits, by its own rules.
- A participant's error stops the session; every participant is told why.
