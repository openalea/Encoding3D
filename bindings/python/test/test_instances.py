"""Instances of shared templates, linear derived fields and shared parts (specification §12), and sequences packed
into a .fspm.zip archive (§8.2): writing each part once, reading and evaluating, the validator's reference checks,
pack, unpack and prune."""
import hashlib
import json
import os
import shutil
import zipfile

import numpy as np
import pytest

import generate
from conftest import CONFORMANCE
from openalea.encoding3d import (ArchiveCheckError, DataStructure, DerivedField, EntitySet, Frame, InstanceSet,
                                 MissingPartError, NO_ID, Operator, Ragged, archive as archives, column_major,
                                 evaluate, from_bytes, pack, placed_meshes,
                                 prune_parts, read, read_index, read_part, to_bytes, unpack, write, write_index,
                                 write_sequence)
from openalea.encoding3d.cli import main
from openalea.encoding3d.dump import frame_to_dict, part_to_dict
from openalea.encoding3d.validate import validate_file, validate_sequence

INSTANCES = os.path.join(CONFORMANCE, "instances")


def frames():
    return [generate.instanced_roots(3, 0., 0), generate.instanced_roots(4, 1., 24)]


def expected_potential(frame) -> list:
    """The sections' water potential computed here, term by term, with the operators' matrices."""
    sections = frame.data_structures[0].instance_set("sections")
    derived = sections.derived_field("water_potential")
    out = []
    for row in range(sections.count):
        total = None
        for term in range(derived.terms):
            index = derived.operators[row, term]
            if index == NO_ID:
                continue
            matrix = np.asarray(sections.parts[index].matrix().todense() if hasattr(sections.parts[index].matrix(),
                                                                                    "todense")
                                else sections.parts[index].matrix())
            value = matrix @ sections.vectors["ends"][row]
            offset = sections.vectors[derived.offsets[term]][row] if derived.offsets[term] else np.zeros(0)
            value = derived.weights[row, term] * (value + (offset if offset.size else 0.))
            total = value if total is None else total + value
        out.append(total)
    return out


# ── Reading and writing ──────────────────────────────────────────────────

def test_an_instance_set_reads_back(tmp_path):
    frame = frames()[1]
    write_sequence(str(tmp_path), [frame])
    back = read(str(tmp_path / "frame_000000.glb"))
    sections, written = back.data_structures[0].instance_set("sections"), frame.data_structures[0].instance_set(
        "sections")
    assert sections.owners == "SubOrgan" and sections.parts == [part.key for part in written.parts]
    for name in ("id", "owner", "template", "transform", "age"):
        np.testing.assert_array_equal(sections.columns[name], written.columns[name])
    assert sections.variables["age"].unit == "d"
    for name in ("ends", "sources"):
        np.testing.assert_array_equal(sections.vectors[name].values, written.vectors[name].values)
        np.testing.assert_array_equal(sections.vectors[name].counts, written.vectors[name].counts)
    derived = sections.derived_field("water_potential")
    np.testing.assert_array_equal(derived.operators, written.derived[0].operators)
    np.testing.assert_array_equal(derived.weights, written.derived[0].weights)
    assert derived.offsets == ("sources", None) and derived.variable.unit == "MPa"
    assert derived.variable.standard_name == "water_potential"


def test_evaluate_gives_each_instance_its_field():
    for frame in frames():
        values = evaluate(frame, "water_potential")
        for found, expected in zip(values, expected_potential(frame)):
            np.testing.assert_allclose(found, expected, rtol=1e-12, atol=0.)
    frame = frames()[1]
    chosen = evaluate(frame, "water_potential", instances=[3, 1])
    everything = evaluate(frame, "water_potential")
    # the chosen instances are applied as a smaller batch: the BLAS may sum them otherwise (MKL on Windows: 1 ulp)
    np.testing.assert_allclose(chosen[0], everything[3], rtol=1e-12, atol=0.)
    np.testing.assert_allclose(chosen[1], everything[1], rtol=1e-12, atol=0.)
    mask = evaluate(frame, "water_potential", instances=np.array([False, True, False, True]))
    np.testing.assert_allclose(mask[1], everything[3], rtol=1e-12, atol=0.)


def test_the_conformance_case_evaluates_as_expected():
    for number in (0, 1):
        frame = read(os.path.join(INSTANCES, f"frame_{number:06d}.glb"))
        with open(os.path.join(INSTANCES, f"frame_{number:06d}.evaluated.json"), encoding="utf-8") as file:
            expected = json.load(file)["root_system/sections/water_potential"]
        for found, values in zip(evaluate(frame, "water_potential"), expected):
            np.testing.assert_allclose(found, values, rtol=1e-12, atol=0.)


def test_the_conformance_parts_read_as_expected():
    index = read_index(INSTANCES)
    assert sorted(index["parts"]) == sorted(name[:-4] for name in os.listdir(os.path.join(INSTANCES, "parts")))
    for key in index["parts"]:
        with open(os.path.join(INSTANCES, "parts", f"{key}.glb"), "rb") as file:
            data = file.read()
        assert hashlib.sha256(data).hexdigest() == key
        with open(os.path.join(INSTANCES, "expected", f"{key}.json"), encoding="utf-8") as file:
            assert json.loads(json.dumps(part_to_dict(read_part(data, key=key)))) == json.load(file)


def test_an_embedded_frame_is_self_contained():
    with open(os.path.join(INSTANCES, "embedded.glb"), "rb") as file:
        frame = from_bytes(file.read())                     # no folder: its parts are in it
    with open(os.path.join(INSTANCES, "frame_000001.expected.json"), encoding="utf-8") as file:
        assert json.loads(json.dumps(frame_to_dict(frame))) == json.load(file)
    for found, expected in zip(evaluate(frame, "water_potential"), expected_potential(frames()[1])):
        np.testing.assert_allclose(found, expected, rtol=1e-12)


def test_parts_are_written_once(tmp_path):
    index = write_sequence(str(tmp_path), frames())
    parts = sorted(os.listdir(tmp_path / "parts"))
    assert len(parts) == 5 and sorted(read_index(index)["parts"]) == [name[:-4] for name in parts]
    times = {name: os.stat(tmp_path / "parts" / name).st_mtime_ns for name in parts}
    keys = write(str(tmp_path / "frame_000002.glb"), frames()[1])
    assert sorted(keys) == [name[:-4] for name in parts]
    assert {name: os.stat(tmp_path / "parts" / name).st_mtime_ns for name in parts} == times
    for name in parts:
        with open(tmp_path / "parts" / name, "rb") as file:
            assert hashlib.sha256(file.read()).hexdigest() == name[:-4]


def test_a_frame_read_from_a_file_writes_its_parts_elsewhere(tmp_path):
    frame = read(os.path.join(INSTANCES, "frame_000001.glb"))     # parts as keys, found next to it
    write(str(tmp_path / "copy.glb"), frame)
    copied = read(str(tmp_path / "copy.glb"))
    np.testing.assert_array_equal(np.concatenate(evaluate(copied, "water_potential")),
                                  np.concatenate(evaluate(frame, "water_potential")))


def test_a_missing_part_is_a_clear_error(tmp_path):
    write_sequence(str(tmp_path), frames()[:1])
    key = generate.DIFFUSION.key
    os.remove(tmp_path / "parts" / f"{key}.glb")
    frame = read(str(tmp_path / "frame_000000.glb"))           # the frame reads: its own fields
    assert frame.data_structures[0].instance_set("sections").columns["age"].size == 3
    with pytest.raises(MissingPartError, match=key):
        evaluate(frame, "water_potential")
    np.testing.assert_allclose(evaluate(frame, "water_potential", instances=[0, 1])[1],
                               expected_potential(frames()[0])[1], rtol=1e-12)
    report = validate_file(str(tmp_path / "scene.fspm.json"))
    assert not report.ok and any(key in issue.message and "missing" in issue.message for issue in report.errors)


def test_placed_meshes_move_each_template():
    frame = frames()[1]
    sections = frame.data_structures[0].instance_set("sections")
    placed = placed_meshes(frame, "root_system", "sections", instances=[2])
    hexagon = generate.HEXAGON.meshes[0]
    matrix = sections.transforms()[2]
    np.testing.assert_allclose(placed.positions, hexagon.positions @ matrix[:3, :3].T + matrix[:3, 3])
    assert placed.triangles.shape == (6, 3) and (placed.instance == 2).all()
    np.testing.assert_array_equal(placed.template_rows["Cell"], np.arange(6))
    every = placed_meshes(frame, "root_system", "sections")
    assert sorted(set(every.instance.tolist())) == [0, 1, 2, 3] and len(every.triangles) == 4 + 4 + 6 + 6


def test_operators():
    rng = np.random.default_rng(1)
    system = np.diag(rng.uniform(2., 3., 5)) + 0.1 * np.eye(5, k=1)
    right = rng.uniform(size=(5, 3))
    solved = Operator.solve(system, right)
    np.testing.assert_allclose(solved.apply(np.ones(3)), np.linalg.solve(system, right @ np.ones(3)))
    dense = Operator.of_system(system, right, max_dense=15)
    assert dense.format == "dense"
    np.testing.assert_allclose(dense.values, np.linalg.solve(system, right))
    assert Operator.of_system(system, right, max_dense=14).format == "solve"
    sparse = Operator.sparse(np.array([[0., 2.], [3., 0.], [0., 0.]]))
    np.testing.assert_array_equal(sparse.apply(np.array([1., 10.])), [20., 3., 0.])
    for operator in (solved, dense, sparse):
        back = read_part(generate.part_bytes(operator), key=operator.key)
        assert back.format == operator.format and back.shape == operator.shape
        vector = np.arange(operator.shape[1], dtype=float)
        np.testing.assert_allclose(back.apply(vector), operator.apply(vector), rtol=1e-14)
    with pytest.raises(ValueError, match="hash"):
        read_part(generate.part_bytes(sparse), key="0" * 64)


def test_ragged():
    vectors = Ragged.of([[1., 2.], [], [3., 4., 5.]])
    np.testing.assert_array_equal(vectors[2], [3., 4., 5.])
    taken = vectors.take([2, 0, 1])
    np.testing.assert_array_equal(taken.values, [3., 4., 5., 1., 2.])
    np.testing.assert_array_equal(taken.counts, [3, 2, 0])
    with pytest.raises(ValueError):
        Ragged([1., 2.], [3])


# ── The validator's checks ───────────────────────────────────────────────

def broken(change) -> list:
    frame = frames()[0]
    change(frame.data_structures[0].instance_set("sections"))
    from openalea.encoding3d.validate import validate_bytes
    return [str(issue) for issue in validate_bytes(to_bytes(frame, embed_parts=True)).errors]


def test_the_validator_checks_the_references():
    assert broken(lambda sections: None) == []

    def wrong_shape(sections):
        sections.vectors["ends"] = Ragged.of([[1., 2., 3.], [1., 2.], [1., 2.]])
    assert any("shape" in error for error in broken(wrong_shape))

    def wrong_template(sections):
        sections.columns["template"] = np.array([0, 2, 1], dtype=np.int64)      # part 2 is an operator
    assert any("not a template" in error for error in broken(wrong_template))

    def wrong_owner(sections):
        sections.columns["owner"] = np.array([10, 11, 99], dtype=np.int64)
    assert any("owner" in error and "99" in error for error in broken(wrong_owner))

    def wrong_operator(sections):
        sections.derived[0].operators[0, 0] = 9
    assert any("outside" in error for error in broken(wrong_operator))

    def wrong_offset(sections):
        sections.vectors["sources"] = Ragged.of([[1.], [], [0.] * 6])
    assert any("offsets" in error for error in broken(wrong_offset))


def test_a_part_whose_bytes_are_not_its_key_is_an_error(tmp_path):
    write_sequence(str(tmp_path), frames()[:1])
    key = generate.SQUARE.key
    with open(tmp_path / "parts" / f"{key}.glb", "wb") as file:
        file.write(generate.part_bytes(generate.HEXAGON))
    report = validate_file(str(tmp_path))
    assert any(key in issue.message and "hash" in issue.message for issue in report.errors)


# ── Archives ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("compression", ["deflate", "lzma", "stored"])
def test_an_archive_reads_as_its_folder(tmp_path, compression):
    archive = str(tmp_path / "run.fspm.zip")
    pack(INSTANCES, archive, compression=compression, keep_folder=True)
    with zipfile.ZipFile(archive) as opened:
        names = opened.namelist()
        kinds = {info.compress_type for info in opened.infolist()}
    assert {zipfile.ZIP_DEFLATED: "deflate", zipfile.ZIP_LZMA: "lzma", zipfile.ZIP_STORED: "stored"}[kinds.pop()] \
        == compression and not kinds
    assert "scene.fspm.json" in names and "frame_000001.glb" in names
    assert sum(name.startswith("parts/") for name in names) == 5 and "embedded.glb" not in names
    index = read_index(archive)
    assert [entry["file"] for entry in index["frames"]] == ["frame_000000.glb", "frame_000001.glb"]
    for lazy in (False, True):
        frame = read(index["frames"][1]["path"], lazy=lazy)
        folder_frame = read(os.path.join(INSTANCES, "frame_000001.glb"))
        assert json.dumps(frame_to_dict(frame)) == json.dumps(frame_to_dict(folder_frame))
        np.testing.assert_array_equal(np.concatenate(evaluate(frame, "water_potential")),
                                      np.concatenate(evaluate(folder_frame, "water_potential")))
    report = validate_file(archive)
    assert report.ok and not report.warnings, str(report)


def test_unpack_gives_the_folder_back(tmp_path):
    archive = str(tmp_path / "run.fspm.zip")
    pack(os.path.join(INSTANCES, "scene.fspm.json"), archive, keep_folder=True)
    index = unpack(archive, str(tmp_path / "back"))
    for relative in ["scene.fspm.json", "frame_000000.glb", "frame_000001.glb"] + \
            [f"parts/{name}" for name in os.listdir(os.path.join(INSTANCES, "parts"))]:
        with open(os.path.join(INSTANCES, relative), "rb") as original, \
                open(os.path.join(tmp_path, "back", relative), "rb") as copy:
            assert original.read() == copy.read(), relative
    assert validate_file(index).ok


def test_pack_refuses_a_sequence_missing_a_part(tmp_path):
    shutil.copytree(INSTANCES, tmp_path / "frames")
    os.remove(tmp_path / "frames" / "parts" / f"{generate.SQUARE.key}.glb")
    with pytest.raises(MissingPartError):
        pack(str(tmp_path / "frames"), str(tmp_path / "run.fspm.zip"))
    assert not os.path.exists(tmp_path / "run.fspm.zip")


def a_sequence(tmp_path) -> str:
    """The instances' two frames written in tmp_path/frames, with a views file: their folder."""
    folder = str(tmp_path / "frames")
    write_sequence(folder, frames())
    with open(os.path.join(folder, "views.json"), "w", encoding="utf-8") as file:
        json.dump({"encoding3d_views": 1, "configurations": {"default": {"layers": []}}}, file)
    return folder


def files_of(folder: str) -> dict:
    found = {}
    for root, _, names in os.walk(folder):
        for name in names:
            with open(os.path.join(root, name), "rb") as file:
                found[os.path.relpath(os.path.join(root, name), folder)] = file.read()
    return found


def test_pack_checks_the_archive_then_removes_the_folder(tmp_path):
    folder = a_sequence(tmp_path)
    written = files_of(folder)
    archive = pack(folder, str(tmp_path / "run.fspm.zip"))
    assert not os.path.exists(folder) and sorted(os.listdir(tmp_path)) == ["run.fspm.zip"]
    with zipfile.ZipFile(archive) as opened:
        assert sorted(opened.namelist()) == sorted(name.replace(os.sep, "/") for name in written)
        for name, content in written.items():
            assert opened.read(name.replace(os.sep, "/")) == content, name
    assert validate_file(archive).ok
    back = unpack(archive, folder)
    assert files_of(folder) == written and validate_file(back).ok


def test_pack_keeps_the_folder_when_asked(tmp_path):
    folder = a_sequence(tmp_path)
    written = files_of(folder)
    archive = pack(folder, str(tmp_path / "run.fspm.zip"), keep_folder=True)
    assert files_of(folder) == written and validate_file(archive).ok


def test_a_corrupted_member_keeps_the_folder(tmp_path, monkeypatch):
    folder = a_sequence(tmp_path)
    written = files_of(folder)
    original = archives._write

    def corrupted(base, members, path, compression, level):         # a byte of the last frame's data flipped
        original(base, members, path, compression, level)
        with zipfile.ZipFile(path) as opened:
            info = opened.getinfo("frame_000001.glb")
        with open(path, "r+b") as file:
            file.seek(info.header_offset + 26)
            name_length, extra_length = np.frombuffer(file.read(4), dtype="<u2")
            file.seek(info.header_offset + 30 + int(name_length) + int(extra_length) + 100)
            byte = file.read(1)
            file.seek(-1, os.SEEK_CUR)
            file.write(bytes([byte[0] ^ 0xFF]))
    monkeypatch.setattr(archives, "_write", corrupted)
    with pytest.raises(ArchiveCheckError, match="frame_000001.glb"):
        pack(folder, str(tmp_path / "run.fspm.zip"), compression="stored")
    assert files_of(folder) == written
    assert sorted(os.listdir(tmp_path)) == ["frames"]                 # neither the archive nor its temporary file


def test_an_invalid_sequence_is_not_packed(tmp_path):
    folder = a_sequence(tmp_path)
    with open(os.path.join(folder, "scene.fspm.json")) as file:
        index = json.load(file)
    index["frames"].reverse()                                         # out of time order: not valid
    with open(os.path.join(folder, "scene.fspm.json"), "w") as file:
        json.dump(index, file)
    written = files_of(folder)
    with pytest.raises(ArchiveCheckError, match="time order"):
        pack(folder, str(tmp_path / "run.fspm.zip"))
    assert files_of(folder) == written and sorted(os.listdir(tmp_path)) == ["frames"]


def test_a_folder_with_other_files_is_not_removed(tmp_path):
    folder = a_sequence(tmp_path)
    with open(os.path.join(folder, "notes.txt"), "w") as file:
        file.write("not a file of the sequence")
    with pytest.raises(ArchiveCheckError, match="notes.txt"):
        pack(folder, str(tmp_path / "run.fspm.zip"))
    assert os.path.exists(os.path.join(folder, "notes.txt")) and not os.path.exists(tmp_path / "run.fspm.zip")
    with pytest.raises(ValueError, match="inside the folder"):
        pack(folder, os.path.join(folder, "run.fspm.zip"))
    assert validate_file(pack(folder, str(tmp_path / "run.fspm.zip"), keep_folder=True)).ok
    assert os.path.exists(os.path.join(folder, "notes.txt"))


def test_an_archive_with_parts_validates_as_its_folder(tmp_path):
    folder = a_sequence(tmp_path)
    archive = pack(folder, str(tmp_path / "run.fspm.zip"), keep_folder=True)
    for path in (archive, os.path.join(archive, "scene.fspm.json")):
        for report in (validate_file(path), validate_sequence(path)):
            assert report.ok and not report.warnings, str(report)
    key = generate.SQUARE.key                                          # a part not hashing to its key, in the archive
    with open(os.path.join(folder, "parts", f"{key}.glb"), "wb") as file:
        file.write(generate.part_bytes(generate.HEXAGON))
    broken = str(tmp_path / "broken.fspm.zip")
    archives._write(folder, archives.sequence_members(os.path.join(folder, "scene.fspm.json")), broken, "deflate",
                    None)
    for report in (validate_file(broken), validate_sequence(broken)):
        assert any(key in issue.message and "hash" in issue.message for issue in report.errors), str(report)
        assert not any("does not exist" in issue.message for issue in report.issues), str(report)
    with zipfile.ZipFile(archive) as opened, zipfile.ZipFile(broken, "w") as out:     # a part missing from it
        for name in opened.namelist():
            if name != f"parts/{key}.glb":
                out.writestr(name, opened.read(name))
    report = validate_sequence(broken)
    assert any(key in issue.message and "does not exist" in issue.message for issue in report.errors), str(report)


def test_the_command_line(tmp_path, capsys):
    archive = str(tmp_path / "run.fspm.zip")
    assert main(["pack", INSTANCES, archive, "--compression", "lzma", "--keep-folder"]) == 0
    assert os.path.exists(os.path.join(INSTANCES, "scene.fspm.json"))
    assert main(["validate", archive]) == 0
    assert main(["unpack", archive, str(tmp_path / "back")]) == 0
    assert main(["info", os.path.join(INSTANCES, "frame_000000.glb")]) == 0
    assert "instances sections of SubOrgan: 3 instances, 5 parts" in capsys.readouterr().out
    assert main(["prune", str(tmp_path / "back")]) == 0
    assert "0 part(s) removed" in capsys.readouterr().out
    assert main(["pack", str(tmp_path / "back"), str(tmp_path / "again.fspm.zip")]) == 0
    assert "checked; the folder removed" in capsys.readouterr().out and not os.path.exists(tmp_path / "back")
    assert main(["pack", INSTANCES, str(tmp_path / "refused.fspm.zip")]) == 1      # its expected values: kept
    assert "not packed, the folder kept" in capsys.readouterr().err
    assert os.path.exists(os.path.join(INSTANCES, "scene.fspm.json"))


# ── Pruning ──────────────────────────────────────────────────────────────

def test_prune_removes_the_parts_no_frame_uses(tmp_path):
    first, second = frames()
    second.data_structures[0].instance_set("sections").parts[4] = Operator.dense(np.ones((6, 2)))
    index = write_sequence(str(tmp_path), [first, second])
    assert len(os.listdir(tmp_path / "parts")) == 6
    entries = read_index(index)["frames"][1:]                    # the first frame removed
    for entry in entries:
        entry.pop("path")
    write_index(index, entries, parts=read_index(index)["parts"])
    removed = prune_parts(index)
    assert removed == [generate.DIFFUSION.key]
    assert sorted(read_index(index)["parts"]) == sorted(name[:-4] for name in os.listdir(tmp_path / "parts"))
    assert validate_file(index).ok and not validate_file(index).warnings


def test_a_frame_without_instances_is_unchanged():
    frame = generate.root_system()
    assert from_bytes(to_bytes(frame)).data_structures[0].instance_sets == []
    assert "instanceSets" not in to_bytes(frame)[:4096].decode("utf-8", "ignore")


def test_an_empty_instance_set(tmp_path):
    data_structure = DataStructure("plants", entity_sets=[EntitySet("Organ", columns={"id": np.zeros(0, np.int64)})],
                                   instance_sets=[InstanceSet("shapes", parts=[generate.SQUARE], columns={
                                       "template": np.zeros(0, np.int64), "transform": column_major(np.zeros((0, 4, 4)))},
                                       vectors={"values": Ragged.of([])},
                                       derived=[DerivedField("value", "Cell", "values", operators=np.zeros((0, 1)))])])
    write(str(tmp_path / "frame.glb"), Frame([data_structure]))
    frame = read(str(tmp_path / "frame.glb"))
    assert evaluate(frame, "value") == []
    assert validate_file(str(tmp_path / "frame.glb")).ok


def test_operators_without_scipy(monkeypatch):
    import sys
    for name in [name for name in sys.modules if name == "scipy" or name.startswith("scipy.")]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "scipy", None)                    # import scipy: ImportError
    monkeypatch.setattr(generate.DIFFUSION, "_factor", None)          # factorised again, by numpy
    frame = frames()[1]
    for found, expected in zip(evaluate(frame, "water_potential"), expected_potential_with_numpy(frame)):
        np.testing.assert_allclose(found, expected, rtol=1e-12)


def expected_potential_with_numpy(frame) -> list:
    sections = frame.data_structures[0].instance_set("sections")
    square = np.array([[1., 0.], [0.75, 0.25], [0.5, 0.5], [0.25, 0.75]])
    alternate = np.array([[1., 0.], [0., 1.], [1., 0.], [0., 1.]])
    hexagon = np.linalg.solve(generate._RING, np.array([[0.5, 0.5], [1., 0.], [0.5, 0.5], [0., 1.], [0.5, 0.5],
                                                         [0.25, 0.75]]))
    ends, sources = sections.vectors["ends"], sections.vectors["sources"]
    return [square @ ends[0], 0.25 * square @ ends[1] + 0.75 * alternate @ ends[1], hexagon @ ends[2] + sources[2],
            hexagon @ ends[3]]
