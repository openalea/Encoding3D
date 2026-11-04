"""
Writes the coupling conformance sessions (specification §9, §11): each session's peer (a recorded sequence), its
subject's declaration and updates, and the expected dumps of what the subject reads and of the session's record
(expected/turn_<step>.json, expected/record/frame_<step>.json: not *.expected.json, which are the frames').

The subject's updates and expected values come from running the session once with a reference subject (the
behaviour each session describes, in Python), over a folder. Every run writes the same bytes.

    python conformance/coupling/generate.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading

import numpy as np

from openalea.encoding3d import (DataStructure, EntitySet, Frame, Mapping, NO_ID, Variable, read, read_index, to_bytes,
                              write_sequence)
from openalea.encoding3d.coupling import (Coordinator, Declaration, EntitySetSpec, Link, MappingSpec, Participant,
                                       VariableSpec)
from openalea.encoding3d.dump import frame_to_dict

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
STEPS = 4
OFFSET = 2 ** 32                       # the subject's id offset: the first participant expected
PEER_OFFSET = 2 * 2 ** 32              # the peer's: the replay, after it


def _json(value) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False) + "\n"


# ── two_scales: the subject refines the peer's organs into segments ──────────────────────────────────────
def two_scales_peer() -> list:
    """The grower: one organ more each step, in a chain, each 2 cm longer than the previous; the first removed at
    step 3."""
    frames, organs, next_id = [], [], 0
    for step in range(STEPS + 1):
        organs.append(next_id)
        next_id += 1
        if step == 3:
            organs.pop(0)
        count = len(organs)
        organ_set = EntitySet("Organ", rank=5, columns={
            "id": np.array(organs, dtype=np.int64), "label": np.array(["Leaf"] * count, dtype=object),
            "parent": np.array([NO_ID] + organs[:-1], dtype=np.int64),
            "edge_type": np.array(["none"] + ["successor"] * (count - 1), dtype=object),
            "length": 2. * np.arange(1, count + 1)},
            variables={"length": Variable(unit="cm", standard_name="length", kind="extensive")})
        frames.append(Frame([DataStructure("plant", entity_sets=[organ_set])], time=float(step), step=step,
                            writer={"platform": "conformance"}))
    return frames


def two_scales_declaration() -> Declaration:
    return Declaration("subject", "conformance", [EntitySetSpec("plant", "Organ"),
                                                  EntitySetSpec("plant", "SubOrgan", rights="refines")], [
        VariableSpec("plant", "SubOrgan", "segment_length", "requires", "m", "length"),
        VariableSpec("plant", "SubOrgan", "sugar", "provides", "mol", kind="extensive")])


def two_scales_subject():
    """Two segments under each new organ; each segment's sugar 1e-6 mol per m of its length."""
    segments = {}

    def answer(turn, offset):
        plant = turn.frame.data_structure("plant")
        for segment in turn.frame.update.removed.get(("plant", "SubOrgan"), np.zeros(0)).tolist():
            segments.pop(segment, None)
        lengths = {}
        if any(item.name == "SubOrgan" for item in plant.entity_sets):
            known = plant.entity_set("SubOrgan")
            lengths = dict(zip(known.columns["id"].tolist(), np.asarray(known.columns["segment_length"]).tolist()))
        with_segments = {organ for organ, _ in segments.values()}
        for organ in plant.entity_set("Organ").columns["id"].tolist():
            if organ not in with_segments:
                first = offset + 1000 * turn.step + len(segments)
                segments[first], segments[first + 1] = (organ, NO_ID), (organ, first)
        ids = list(segments)
        columns = {"id": np.array(ids, dtype=np.int64),
                   "complex": np.array([segments[segment][0] for segment in ids], dtype=np.int64),
                   "parent": np.array([segments[segment][1] for segment in ids], dtype=np.int64),
                   "edge_type": np.array(["none" if segments[segment][1] == NO_ID else "successor"
                                          for segment in ids], dtype=object),
                   "label": np.array(["Segment"] * len(ids), dtype=object),
                   "sugar": np.array([1e-6 * np.nan_to_num(lengths.get(segment, 0.)) for segment in ids])}
        return Frame([DataStructure("plant", entity_sets=[EntitySet("SubOrgan", rank=6, columns=columns)])])
    return answer


# ── two_data_structures: the subject's soil linked to the peer's plant by the mapping it provides ────────────
def two_data_structures_peer() -> list:
    """The plant: two organs, then three from step 2, each taking up 1 mol per step."""
    frames = []
    for step in range(STEPS + 1):
        count = 2 if step < 2 else 3
        organ_set = EntitySet("Organ", rank=5, columns={"id": np.arange(count, dtype=np.int64),
                                                        "uptake": np.ones(count)},
                              variables={"uptake": Variable(unit="mol", kind="extensive")})
        frames.append(Frame([DataStructure("plant", entity_sets=[organ_set])], time=float(step), step=step,
                            writer={"platform": "conformance"}))
    return frames


def two_data_structures_declaration() -> Declaration:
    return Declaration("subject", "conformance", [EntitySetSpec("soil", "Cell", rank=1, rights="owns"),
                                                  EntitySetSpec("plant", "Organ")], [
        VariableSpec("soil", "Cell", "water_content", "provides", "m3/m3", kind="intensive"),
        VariableSpec("soil", "Cell", "uptake", "requires", "mol", kind="extensive")],
        mappings=[MappingSpec("organs_in_soil", ("plant", "Organ"), ("soil", "Cell"))])


def two_data_structures_subject():
    """Three cells; organ i in cells i % 3 (weight 1) and (i + 1) % 3 (weight 3)."""
    water = np.array([0.1, 0.2, 0.3])

    def answer(turn, offset):
        cells = offset + np.arange(3)
        organs = []
        if any(item.id == "plant" for item in turn.frame.data_structures):
            organs = turn.frame.data_structure("plant").entity_set("Organ").columns["id"].tolist()
        frame = Frame([DataStructure("soil", kind="table", entity_sets=[
            EntitySet("Cell", rank=1, columns={"id": cells, "water_content": water})])])
        frame.mappings.append(Mapping("organs_in_soil", source=("plant", "Organ"), target=("soil", "Cell"), columns={
            "source": np.repeat(np.array(organs, dtype=np.int64), 2),
            "target": np.array([cells[(i + k) % 3] for i in range(len(organs)) for k in (0, 1)], dtype=np.int64),
            "weight": np.tile([1., 3.], len(organs))}))
        return frame
    return answer


SESSIONS = {
    "two_scales": dict(
        peer=two_scales_peer, declaration=two_scales_declaration, subject=two_scales_subject,
        links=[Link("subject", "segment_length", "peer", "length", factor=0.5, aggregation="copy")],
        covers="a subject refining a replayed peer's organs into segments: new entities, removals cascading to the "
               "subject's segments, a unit conversion and a factor, a copy to finer entities"),
    "two_data_structures": dict(
        peer=two_data_structures_peer, declaration=two_data_structures_declaration,
        subject=two_data_structures_subject,
        links=[Link("subject", "uptake", "peer", "uptake", mapping="organs_in_soil")],
        covers="a subject owning another data structure, linked to the peer's by the mapping it provides: a sum "
               "through a mapping, the subject's mappings in its updates"),
}


def generate(name: str, spec: dict, directory: str = DIRECTORY) -> None:
    folder = os.path.join(directory, name)
    for part in ("peer", "subject", "expected"):
        if os.path.isdir(os.path.join(folder, part)):
            shutil.rmtree(os.path.join(folder, part))
    os.makedirs(os.path.join(folder, "subject"))
    os.makedirs(os.path.join(folder, "expected", "record"))
    write_sequence(os.path.join(folder, "peer"), spec["peer"]())
    declaration = spec["declaration"]()
    with open(os.path.join(folder, "subject", "declaration.json"), "w", encoding="utf-8") as file:
        file.write(_json(declaration.to_json()))
    settings = {"steps": STEPS, "interval": 1., "timeUnit": "d", "links": [link.to_json() for link in spec["links"]],
                "covers": spec["covers"]}
    with open(os.path.join(folder, "session.json"), "w", encoding="utf-8") as file:
        file.write(_json(settings))

    answer = spec["subject"]()

    def reference(endpoint):
        participant = Participant.connect(spec["declaration"](), endpoint, timeout=60)
        for turn in participant.turns():
            with open(os.path.join(folder, "expected", f"turn_{turn.step:04d}.json"), "w",
                      encoding="utf-8") as file:
                file.write(_json(frame_to_dict(turn.frame)))
            update = answer(turn, participant.id_offset)
            update.update = None
            with open(os.path.join(folder, "subject", f"update_{turn.step:04d}.glb"), "wb") as file:
                file.write(to_bytes(update))
            participant.send(update)

    with tempfile.TemporaryDirectory() as temporary:
        coordinator = Coordinator("files:" + os.path.join(temporary, "messages"), steps=STEPS, interval=1.,
                                  expect=["subject"], links=spec["links"], timeout=60,
                                  replays={"peer": os.path.join(folder, "peer", "scene.fspm.json")},
                                  record=os.path.join(temporary, "record"))
        thread = threading.Thread(target=reference, args=(coordinator.endpoint,), daemon=True)
        thread.start()
        coordinator.run()
        thread.join(60)
        for entry in read_index(os.path.join(temporary, "record", "scene.fspm.json"))["frames"]:
            path = os.path.join(folder, "expected", "record", entry["file"].replace(".glb", ".json"))
            with open(path, "w", encoding="utf-8") as file:
                file.write(_json(frame_to_dict(read(entry["path"]))))
    assert participant_offset_ok(folder)


def participant_offset_ok(folder: str) -> bool:
    """The subject's ids in its updates are in its range (the first participant expected's)."""
    for name in sorted(os.listdir(os.path.join(folder, "subject"))):
        if name.endswith(".glb"):
            frame = read(os.path.join(folder, "subject", name))
            for data_structure in frame.data_structures:
                for entity_set in data_structure.entity_sets:
                    ids = entity_set.columns["id"]
                    if ids.size and not ((ids >= OFFSET) & (ids < OFFSET + 2 ** 32)).all():
                        return False
    return True


def main() -> int:
    for name, spec in SESSIONS.items():
        generate(name, spec)
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
