"""
Conformance sessions (specification §9): how a codec proves its participant's side of a coupling session.

A session's folder (conformance/coupling/<session>/) holds:

    session.json                     the coordinator's settings: steps, interval, timeUnit, links, stages
    peer/scene.fspm.json, frames     the other participant, a recorded sequence the coordinator replays ("peer")
    subject/declaration.json         the participant under test's declaration ("subject")
    subject/update_<step>.glb        what it sends at each step (0: its initial state)
    expected/turn_<step>.json        what it must read from each turn (frame_to_dict)
    expected/record/frame_<step>.json   the session's record, once its updates merged

The participant under test is a small program of the codec's language, run as

    <command> SESSION OUT

that joins the session with subject/declaration.json, and at each turn writes what it read (its dump, the
conformance files' layout) to OUT/turn_<step>.json and sends subject/update_<step>.glb as read and written again by
its codec, until the coordinator stops it. `fspm-tf couple-conformance SESSIONS --participant COMMAND` runs every
session over ZeroMQ and over a folder and compares the dumps; this module's `subject` is Python's program
(`python -m openalea.fspm_tf.coupling.conformance subject SESSION OUT`).
"""
import json
import os
import sys

from openalea.fspm_tf.codec import from_bytes, read, read_index, to_bytes
from openalea.fspm_tf.compare import compare
from openalea.fspm_tf.coupling.coordinator import Coordinator
from openalea.fspm_tf.coupling.messages import Declaration, Link
from openalea.fspm_tf.coupling.participant import Participant
from openalea.fspm_tf.dump import frame_to_dict

TRANSPORTS = ("zmq", "files")


def subject(session: str, out: str) -> int:
    """The participant under test, in Python."""
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(session, "subject", "declaration.json"), encoding="utf-8") as file:
        declaration = Declaration.from_json(json.load(file))
    participant = Participant.connect(declaration, timeout=120)
    for turn in participant.turns():
        with open(os.path.join(out, f"turn_{turn.step:04d}.json"), "w", encoding="utf-8") as file:
            json.dump(frame_to_dict(turn.frame), file, indent=1)
        participant.send(from_bytes(to_bytes(read(os.path.join(session, "subject",
                                                                f"update_{turn.step:04d}.glb")))))
    return 0


def _settings(session: str) -> dict:
    with open(os.path.join(session, "session.json"), encoding="utf-8") as file:
        return json.load(file)


def run_session(session: str, command: str, out: str, transport: str = "zmq") -> list:
    """Run one session with *command* as its subject; the differences between what it read (and the record) and
    the expected values, as lines (empty: it conforms)."""
    settings = _settings(session)
    endpoint = "tcp://127.0.0.1:*" if transport == "zmq" else "files:" + os.path.join(out, "messages")
    coordinator = Coordinator(endpoint, steps=settings["steps"], interval=settings["interval"],
                              time_unit=settings.get("timeUnit", "d"), start=settings.get("start", 0.),
                              links=[Link.from_json(link) for link in settings.get("links", [])],
                              stages=settings.get("stages"),
                              replays={"peer": os.path.join(session, "peer", "scene.fspm.json")},
                              record=os.path.join(out, "record"), timeout=settings.get("timeout", 120))
    turns = os.path.join(out, "turns")
    coordinator.launch("subject", f"{command} {session} {turns}")
    coordinator.run()
    differences = []
    expected_folder = os.path.join(session, "expected")
    for name in sorted(os.listdir(expected_folder)):
        if name.startswith("turn_") and name.endswith(".json"):
            differences += _compare(os.path.join(turns, name), os.path.join(expected_folder, name))
    for entry in read_index(os.path.join(out, "record", "scene.fspm.json"))["frames"]:
        expected = os.path.join(expected_folder, "record", entry["file"].replace(".glb", ".json"))
        differences += _compare_values(frame_to_dict(read(entry["path"])), expected, entry["file"])
    return differences


def _compare(actual_path: str, expected_path: str) -> list:
    if not os.path.exists(actual_path):
        return [f"{os.path.basename(actual_path)}: not written"]
    with open(actual_path, encoding="utf-8") as file:
        actual = json.load(file)
    return _compare_values(actual, expected_path, os.path.basename(actual_path))


def _compare_values(actual, expected_path: str, name: str) -> list:
    with open(expected_path, encoding="utf-8") as file:
        expected = json.load(file)
    actual = json.loads(json.dumps(actual))                     # the same JSON types as the expected file's
    return [f"{name}: {line}" for line in compare(actual, expected)]


def run_all(sessions: str, command: str, out: str, transports=TRANSPORTS) -> dict:
    """Every session of the folder *sessions*, over each transport: {(session, transport): differences}."""
    results = {}
    for name in sorted(os.listdir(sessions)):
        session = os.path.join(sessions, name)
        if not os.path.exists(os.path.join(session, "session.json")):
            continue
        for transport in transports:
            results[(name, transport)] = run_session(os.path.abspath(session), command,
                                                     os.path.join(out, name, transport), transport)
    return results


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "subject":
        sys.exit(subject(sys.argv[2], sys.argv[3]))
    print("usage: python -m openalea.fspm_tf.coupling.conformance subject SESSION OUT", file=sys.stderr)
    sys.exit(2)
