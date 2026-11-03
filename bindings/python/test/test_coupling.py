"""
Coupling sessions (openalea.fspm_tf.coupling): two participants on one plant at two scales, a grower owning the
organs and a function refining them into segments and feeding a supply back, over ZeroMQ and over a folder; the
resolution's checks and the rights; a recorded session replayed as a participant.
"""
import os
import threading

import numpy as np
import pytest

from openalea import fspm_tf
from openalea.fspm_tf.coupling import (Coordinator, CouplingError, Declaration, EntitySetSpec, Link, Participant,
                                       VariableSpec, resolve, stages)
from openalea.fspm_tf.model import NO_ID
from openalea.fspm_tf.validate import validate_sequence

pytest.importorskip("zmq")

# The command running Julia with FspmTF and ZMQ (e.g. "julia --project=env"): the tests with a Julia participant
JULIA = os.environ.get("FSPM_TF_JULIA")
JULIA_FUNCTION = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "julia", "FspmTF", "test", "coupling",
                              "function.jl")

# The session's links: the segments' length is half their organ's (copied from the coarser organs); the organs'
# supply is their segments' sugar (summed, mol to umol)
LINKS = [Link("function", "segment_length", "grower", "length", factor=0.5, aggregation="copy"),
         Link("grower", "supply", "function", "sugar")]


def grower_declaration(name="grower"):
    return Declaration(name, "test", [EntitySetSpec("plant", "Organ", rights="owns")], [
        VariableSpec("plant", "Organ", "length", "provides", "cm", "length", "extensive"),
        VariableSpec("plant", "Organ", "supply", "requires", "umol", kind="extensive")])


def function_declaration(name="function", rights="refines"):
    return Declaration(name, "test", [EntitySetSpec("plant", "Organ"),
                                      EntitySetSpec("plant", "SubOrgan", rights=rights)], [
        VariableSpec("plant", "SubOrgan", "segment_length", "requires", "m", "length"),
        VariableSpec("plant", "SubOrgan", "sugar", "provides", "mol", kind="extensive")])


def organ_frame(name, organs, removed=None):
    """The grower's update: its organs in a chain, each 2 cm longer than the previous one."""
    count = len(organs)
    columns = {"id": np.array(organs, dtype=np.int64), "length": 2. * np.arange(1, count + 1),
               "parent": np.array([NO_ID] + organs[:-1], dtype=np.int64),
               "edge_type": np.array(["none"] + ["successor"] * (count - 1), dtype=object),
               "label": np.array(["Leaf"] * count, dtype=object)}
    return fspm_tf.Frame(data_structures=[fspm_tf.DataStructure("plant", entity_sets=[
        fspm_tf.EntitySet("Organ", rank=5, columns=columns)])], update=fspm_tf.Update(name, removed or {}))


def run_grower(endpoint, log):
    """One organ more each step; the first one removed at step 3. The supply it receives is logged."""
    participant = Participant.connect(grower_declaration(), endpoint, timeout=300)
    organs = []
    for turn in participant.turns():
        organ_set = turn.frame.data_structure("plant").entity_set("Organ") if turn.frame.data_structures else None
        if organ_set is not None and organ_set.count:
            log[turn.step] = dict(zip(organ_set.columns["id"].tolist(),
                                      np.asarray(organ_set.columns["supply"]).tolist()))
        organs.append(participant.id_offset + turn.step)
        removed = {}
        if turn.step == 3:
            removed = {("plant", "Organ"): [organs.pop(0)]}
        participant.send(organ_frame("grower", organs, removed))


def run_function(endpoint, log, rights="refines"):
    """Two segments under each new organ; each segment's sugar 1e-6 mol per m of its length."""
    participant = Participant.connect(function_declaration(rights=rights), endpoint, timeout=30)
    segments = {}                                  # segment id: (its organ, its parent)
    for turn in participant.turns():
        plant = turn.frame.data_structure("plant")
        removed = turn.frame.update.removed.get(("plant", "SubOrgan"), np.zeros(0)).tolist()
        log[turn.step] = sorted(removed)
        for segment in removed:
            segments.pop(segment, None)            # removed with their organ by the coordinator
        lengths = {}
        try:
            known = plant.entity_set("SubOrgan")
            lengths = dict(zip(known.columns["id"].tolist(), np.asarray(known.columns["segment_length"]).tolist()))
        except KeyError:
            pass
        with_segments = {organ for organ, _ in segments.values()}
        for organ in plant.entity_set("Organ").columns["id"].tolist():
            if organ not in with_segments:
                first = participant.id_offset + len(segments) + 2 * turn.step * 1000
                segments[first], segments[first + 1] = (organ, NO_ID), (organ, first)
        ids = list(segments)
        columns = {"id": np.array(ids, dtype=np.int64),
                   "complex": np.array([segments[segment][0] for segment in ids], dtype=np.int64),
                   "parent": np.array([segments[segment][1] for segment in ids], dtype=np.int64),
                   "edge_type": np.array(["none" if segments[segment][1] == NO_ID else "successor"
                                          for segment in ids], dtype=object),
                   "sugar": np.array([1e-6 * np.nan_to_num(lengths.get(segment, 0.)) for segment in ids])}
        participant.send(fspm_tf.Frame(data_structures=[fspm_tf.DataStructure("plant", entity_sets=[
            fspm_tf.EntitySet("SubOrgan", rank=6, columns=columns)])]))


def run_session(endpoint, record=None, function=run_function, **options):
    coordinator = Coordinator(endpoint, steps=4, interval=1., expect=["grower", "function"], links=LINKS,
                              record=record, timeout=30, **options)
    logs = {"grower": {}, "function": {}}
    threads = [threading.Thread(target=target, args=(coordinator.endpoint, logs[name]), daemon=True)
               for name, target in (("grower", run_grower), ("function", function))]
    for thread in threads:
        thread.start()
    try:
        store = coordinator.run()
    finally:
        for thread in threads:
            thread.join(30)
    return store, logs


@pytest.fixture(params=["zmq", "folder"])
def endpoint(request, tmp_path):
    return "tcp://127.0.0.1:*" if request.param == "zmq" else f"files:{tmp_path / 'session'}"


def check_session(store, supply, removed, record):
    first, second, third = (2 ** 32 + step for step in range(3))
    # a segment's length: half its organ's (0.5 * 0.01 m/cm); its sugar 1e-6 mol/m of it; summed and in umol:
    # an organ's supply is 0.01 umol per cm of the organ, from the step after its segments were made
    assert supply[1] == pytest.approx({first: 0.})
    assert supply[2] == pytest.approx({first: 0.02, second: 0.})
    assert supply[3] == pytest.approx({first: 0.02, second: 0.04, third: 0.})
    assert set(supply[4]) == {second, third, third + 1}            # the first organ removed at step 3
    assert supply[4][second] == pytest.approx(0.02)                # now the first of the chain: 2 cm
    if removed is not None:
        assert len(removed[3]) == 2                                # its segments, removed with it in the step
        assert removed[4] == []
    organs = store.sets[("plant", "Organ")]
    assert sorted(organs.ids.tolist()) == [second, third, third + 1, third + 2]
    assert len(store.sets[("plant", "SubOrgan")]) == 8
    report = validate_sequence(os.path.join(record, "scene.fspm.json"))
    assert report.ok, report
    last = fspm_tf.read(os.path.join(record, "frame_00004.glb"))
    assert set(last.data_structure("plant").entity_set("SubOrgan").columns) >= {"id", "complex", "sugar"}


def test_two_platforms_on_one_plant_at_two_scales(endpoint, tmp_path):
    store, logs = run_session(endpoint, record=str(tmp_path / "record"))
    check_session(store, logs["grower"], logs["function"], str(tmp_path / "record"))


@pytest.mark.skipif(not JULIA, reason="FSPM_TF_JULIA (the command running Julia with FspmTF and ZMQ) is not set")
def test_a_julia_participant(endpoint, tmp_path):
    """The function participant in Julia (FspmTF.jl), launched by the coordinator."""
    record = str(tmp_path / "record")
    coordinator = Coordinator(endpoint, steps=4, interval=1., expect=["grower"], links=LINKS, record=record,
                              timeout=300)
    coordinator.launch("function", f"{JULIA} {JULIA_FUNCTION}")
    log = {}
    thread = threading.Thread(target=run_grower, args=(coordinator.endpoint, log), daemon=True)
    thread.start()
    store = coordinator.run()
    thread.join(30)
    check_session(store, log, None, record)


def test_the_messages_follow_their_schema(tmp_path):
    """Every message of a session (the folder transport's log: both directions) is valid against
    spec/schema/coupling.schema.json."""
    import glob
    import json
    import jsonschema
    from openalea.fspm_tf.schema import load
    run_session(f"files:{tmp_path / 'session'}", keep_messages=True)
    validator = jsonschema.Draft202012Validator(load("coupling"))
    headers = sorted(glob.glob(str(tmp_path / "session" / "*" / "*" / "*.json")))
    types = set()
    for path in headers:
        with open(path, encoding="utf-8") as file:
            header = json.load(file)
        errors = list(validator.iter_errors(header))
        assert not errors, f"{path}: {errors[0].message}"
        types.add(header["type"])
    assert types == {"hello", "welcome", "turn", "update", "stop"}


def run_follower_adding(endpoint, log):
    run_function(endpoint, log, rights="follows")


def test_a_participant_adding_entities_it_follows_stops_the_session(tmp_path):
    with pytest.raises(CouplingError, match="which it follows"):
        run_session("tcp://127.0.0.1:*", function=run_follower_adding)


def test_resolution():
    declarations = {"grower": grower_declaration(), "function": function_declaration()}
    with pytest.raises(CouplingError, match="extensive variable copied"):
        resolve(declarations, [LINKS[1]])                          # length by standard name, copied to segments
    with pytest.raises(CouplingError, match="no participant provides"):
        resolve(declarations, [LINKS[0]])                          # the supply unlinked
    couplings = {coupling.variable.name: coupling for coupling in resolve(declarations, LINKS)}
    assert couplings["segment_length"].factor == pytest.approx(0.005)
    assert couplings["supply"].aggregation == "sum" and couplings["supply"].factor == pytest.approx(1e6)
    assert stages(declarations) == [["grower"], ["function"]]
    with pytest.raises(CouplingError, match="owned by"):
        resolve({"a": grower_declaration("a"), "b": grower_declaration("b")})
    with pytest.raises(CouplingError, match="not convertible"):
        resolve(declarations, [LINKS[0], Link("grower", "supply", "grower", "length")])
    with pytest.raises(CouplingError, match="both change"):
        stages({"a": function_declaration("a"), "b": function_declaration("b")}, [["a", "b"]])


def run_reader(endpoint, log):
    declaration = Declaration("reader", "test", [EntitySetSpec("plant", "Organ")], [
        VariableSpec("plant", "Organ", "length", "requires", "cm", "length")])
    participant = Participant.connect(declaration, endpoint, timeout=30)
    for turn in participant.turns():
        organs = turn.frame.data_structure("plant").entity_set("Organ") if turn.frame.data_structures else None
        log[turn.until] = [] if organs is None else np.asarray(organs.columns["length"]).tolist()
        participant.send(fspm_tf.Frame())


def test_a_recorded_session_replayed(tmp_path):
    run_session("tcp://127.0.0.1:*", record=str(tmp_path / "record"))
    # the recorded organ lengths: 0 d [2], 1 d [2, 4], 2 d [2, 4, 6], 3 d [2, 4, 6] (the first removed, the chain
    # renumbered), 4 d [2, 4, 6, 8]
    for interpolation, expected in (("hold", [2., 4., 6.]), ("linear", [2., 3., 5.])):
        coordinator = Coordinator("tcp://127.0.0.1:*", steps=8, interval=0.5, expect=["reader"], timeout=30,
                                  replays={"recorded": str(tmp_path / "record" / "scene.fspm.json")},
                                  links=[Link("reader", "length", "recorded", "length", interpolation=interpolation)])
        log = {}
        thread = threading.Thread(target=run_reader, args=(coordinator.endpoint, log), daemon=True)
        thread.start()
        coordinator.run()
        thread.join(30)
        assert log[0.] == [2.]
        assert log[1.5] == pytest.approx([2., 4.])
        assert log[2.5] == pytest.approx(expected)                  # between 2 d and 3 d
        assert log[3.] == pytest.approx([2., 4., 6.])               # after the removal
        assert len(log[4.]) == 4


READER_SCRIPT = """
import numpy as np
from openalea import fspm_tf
from openalea.fspm_tf.coupling import Declaration, EntitySetSpec, Participant, VariableSpec
declaration = Declaration("", "test", [EntitySetSpec("plant", "Organ")],
                          [VariableSpec("plant", "Organ", "length", "requires", "m", "length")])
participant = Participant.connect(declaration, timeout=60)
for turn in participant.turns():
    participant.send(fspm_tf.Frame())
"""


def test_the_command_line(tmp_path):
    """fspm-tf couple: a launched participant (its name and endpoint from the environment) and a replay, over a
    folder, recorded."""
    import sys
    from openalea.fspm_tf.cli import main
    run_session("tcp://127.0.0.1:*", record=str(tmp_path / "record"))
    script = tmp_path / "reader.py"
    script.write_text(READER_SCRIPT)
    code = main(["couple", "--steps", "3", "--interval", "1", "--endpoint", f"files:{tmp_path / 'session'}",
                 "--replay", f"recorded={tmp_path / 'record' / 'scene.fspm.json'}",
                 "--participant", f"reader={sys.executable} {script}", "--record", str(tmp_path / "again"),
                 "--timeout", "60"])
    assert code == 0
    assert validate_sequence(str(tmp_path / "again" / "scene.fspm.json")).ok
    assert not list((tmp_path / "session" / "reader" / "to_coordinator").iterdir())   # each message read, deleted


WATER = np.array([0.1, 0.2, 0.3])                   # the soil's three cells


def run_plant(endpoint, log):
    """Two organs, then three; each takes up 1 mol per step and logs the water it receives from the soil."""
    from openalea.fspm_tf.coupling import Declaration as D
    declaration = D("plant", "test", [EntitySetSpec("plant", "Organ", rights="owns")], [
        VariableSpec("plant", "Organ", "uptake", "provides", "mol", kind="extensive"),
        VariableSpec("plant", "Organ", "water", "requires", "m3/m3", kind="intensive")])
    participant = Participant.connect(declaration, endpoint, timeout=60)
    for turn in participant.turns():
        organs = turn.frame.data_structure("plant").entity_set("Organ") if turn.frame.data_structures else None
        if organs is not None and organs.count:
            log[turn.step] = dict(zip(organs.columns["id"].tolist(), np.asarray(organs.columns["water"]).tolist()))
        count = 2 if turn.step < 2 else 3
        ids = participant.id_offset + np.arange(count)
        participant.send(fspm_tf.Frame(data_structures=[fspm_tf.DataStructure("plant", entity_sets=[
            fspm_tf.EntitySet("Organ", rank=5, columns={"id": ids, "uptake": np.ones(count)})])]))


def run_soil(endpoint, log):
    """Three cells; organ i in cells i % 3 (weight 1) and (i + 1) % 3 (weight 3): the mapping it provides."""
    from openalea.fspm_tf.coupling import MappingSpec
    declaration = Declaration("soil", "test", [EntitySetSpec("soil", "Cell", rank=1, rights="owns"),
                                               EntitySetSpec("plant", "Organ")], [
        VariableSpec("soil", "Cell", "water_content", "provides", "m3/m3", kind="intensive"),
        VariableSpec("soil", "Cell", "uptake", "requires", "mol", kind="extensive")],
        mappings=[MappingSpec("organs_in_soil", ("plant", "Organ"), ("soil", "Cell"))])
    participant = Participant.connect(declaration, endpoint, timeout=60)
    cells = participant.id_offset + np.arange(3)
    for turn in participant.turns():
        if turn.frame.data_structures and any(item.id == "soil" for item in turn.frame.data_structures):
            soil = turn.frame.data_structure("soil").entity_set("Cell")
            log[turn.step] = np.asarray(soil.columns["uptake"]).tolist()
        organs = []
        if any(item.id == "plant" for item in turn.frame.data_structures):
            organs = turn.frame.data_structure("plant").entity_set("Organ").columns["id"].tolist()
        source = np.repeat(np.array(organs, dtype=np.int64), 2)
        target = np.array([cells[(i + k) % 3] for i in range(len(organs)) for k in (0, 1)], dtype=np.int64)
        weight = np.tile([1., 3.], len(organs))
        frame = fspm_tf.Frame(data_structures=[fspm_tf.DataStructure("soil", kind="table", entity_sets=[
            fspm_tf.EntitySet("Cell", rank=1, columns={"id": cells, "water_content": WATER})])])
        frame.mappings.append(fspm_tf.Mapping("organs_in_soil", source=("plant", "Organ"), target=("soil", "Cell"),
                                              columns={"source": source, "target": target, "weight": weight}))
        participant.send(frame)


def test_a_link_between_two_data_structures(endpoint, tmp_path):
    """The plant's organs and the soil's cells, two data structures of two participants, linked by the mapping the
    soil provides: the organs' water, the cells' weighted mean; the cells' uptake, the organs' shared by weight."""
    links = [Link("plant", "water", "soil", "water_content", mapping="organs_in_soil"),
             Link("soil", "uptake", "plant", "uptake", mapping="organs_in_soil")]
    coordinator = Coordinator(endpoint, steps=4, interval=1., expect=["plant", "soil"], links=links, timeout=60,
                              record=str(tmp_path / "record"))
    logs = {"plant": {}, "soil": {}}
    threads = [threading.Thread(target=target, args=(coordinator.endpoint, logs[name]), daemon=True)
               for name, target in (("plant", run_plant), ("soil", run_soil))]
    for thread in threads:
        thread.start()
    coordinator.run()
    for thread in threads:
        thread.join(30)
    first = 2 ** 32
    # explicit coupling, the stage [plant, soil]: at step 4 the mapping the soil sent at step 3 (from the plant's
    # three organs of step 2) and the uptake the plant sent at step 3
    water = logs["plant"][4]
    for i in range(3):
        assert water[first + i] == pytest.approx((WATER[i % 3] + 3 * WATER[(i + 1) % 3]) / 4)
    uptake = logs["soil"][4]
    assert uptake == pytest.approx([1., 1., 1.])                   # 1/4 of one organ and 3/4 of another, each
    assert validate_sequence(str(tmp_path / "record" / "scene.fspm.json")).ok
    with pytest.raises(CouplingError, match="need a mapping"):
        resolve({"plant": Declaration.from_json(Declaration("plant", entity_sets=[], variables=[
            VariableSpec("plant", "Organ", "water", "requires", "1")]).to_json()),
                 "soil": Declaration("soil", variables=[VariableSpec("soil", "Cell", "water_content", "provides",
                                                                     "1")]).complete()},
                [Link("plant", "water", "soil", "water_content")])


def test_the_conformance_sessions(tmp_path):
    """Python's participant against conformance/coupling, over both transports (fspm-tf couple-conformance)."""
    import sys
    from openalea.fspm_tf.cli import main
    sessions = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, "conformance", "coupling")
    command = f"{sys.executable} -m openalea.fspm_tf.coupling.conformance subject"
    assert main(["couple-conformance", sessions, "--participant", command, "--out", str(tmp_path)]) == 0


def test_the_conformance_sessions_are_what_their_generator_writes(tmp_path):
    import importlib.util
    folder = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, "conformance", "coupling")
    spec = importlib.util.spec_from_file_location("coupling_generate", os.path.join(folder, "generate.py"))
    generate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generate)
    for name, session in generate.SESSIONS.items():
        generate.generate(name, session, str(tmp_path))
        for root, _, files in os.walk(tmp_path / name):
            for file_name in files:
                written = os.path.join(root, file_name)
                committed = os.path.join(folder, os.path.relpath(written, tmp_path))
                with open(written, "rb") as left, open(committed, "rb") as right:
                    assert left.read() == right.read(), committed


# Platforms' logs replayed (their index, scene.fspm.json): CPlantBox's (bindings/cpp/cplantbox's tests write
# anagallis_log/) and GroIMP's (bindings/java/groimp-plugin/test/run_in_groimp.sh writes log/), in their CI jobs
PLATFORM_LOGS = {"conformance": os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir,
                                             "conformance", "growing_sequence", "scene.fspm.json"),
                 "CPlantBox": os.environ.get("FSPM_TF_CPLANTBOX_LOG"), "GroIMP": os.environ.get("FSPM_TF_GROIMP_LOG")}


def _sorted(values):
    """The values, missing ones (NaN, masked) as None, sorted: to compare a column whatever its rows' order."""
    def plain(value):
        if isinstance(value, list):
            return [plain(item) for item in value]
        return None if value is None or (isinstance(value, float) and value != value) else value
    values = np.ma.filled(np.ma.asarray(values, dtype=object), None).tolist() if np.ma.isMaskedArray(values) \
        else np.asarray(values).tolist()
    return sorted((plain(value) for value in values), key=repr)


@pytest.mark.parametrize("platform", sorted(PLATFORM_LOGS))
def test_a_platform_log_replayed(platform, tmp_path):
    """A platform's log as a participant: a reader following every entity set and requiring every variable gets, at
    each step, the logged entities (renumbered) and values."""
    from openalea.fspm_tf.coupling import Replay
    from openalea.fspm_tf.codec import read_index
    index = PLATFORM_LOGS[platform]
    if not index:
        pytest.skip(f"no {platform} log (FSPM_TF_{platform.upper()}_LOG)")
    entries = read_index(index)["frames"]
    times = [entry["time"] for entry in entries]
    replay = Replay("log", index)                               # its declaration: what the reader requires
    declaration = Declaration("reader", "test", [EntitySetSpec(item.data_structure, item.name, item.rank)
                                                 for item in replay.declaration.entity_sets],
                              [VariableSpec(item.data_structure, item.entity_set, item.name, "requires", item.unit,
                                            kind=item.kind) for item in replay.declaration.variables])
    log = {}

    def reader(endpoint):
        participant = Participant.connect(declaration, endpoint, timeout=120)
        for turn in participant.turns():
            log[turn.step] = {(data_structure.id, entity_set.name): entity_set
                              for data_structure in turn.frame.data_structures
                              for entity_set in data_structure.entity_sets}
            participant.send(fspm_tf.Frame())

    interval = times[1] - times[0] if len(times) > 1 else 1.
    coordinator = Coordinator("tcp://127.0.0.1:*", steps=len(entries) - 1, interval=interval, start=times[0],
                              time_unit=read_index(index).get("timeUnit", "d"), expect=["reader"],
                              replays={"log": index}, timeout=120)
    thread = threading.Thread(target=reader, args=(coordinator.endpoint,), daemon=True)
    thread.start()
    coordinator.run()
    thread.join(60)
    for step, entry in enumerate(entries):
        frame = fspm_tf.read(entry["path"])
        for data_structure in frame.data_structures:
            for entity_set in data_structure.entity_sets:
                received = log[step][(data_structure.id, entity_set.name)]
                assert received.count == entity_set.count, (step, entity_set.name)
                for name in entity_set.variable_names():
                    assert _sorted(received.columns[name]) == _sorted(entity_set.columns[name]), (step, name)
