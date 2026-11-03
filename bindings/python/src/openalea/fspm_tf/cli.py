"""
The fspm-tf command line::

    fspm-tf validate FILE...                    check .glb frames or sequences (scene.fspm.json); exit 1 on errors
    fspm-tf info FILE                           what a frame holds
    fspm-tf display FILE NAME... [-o OUT]       add display copies of variables (in place, or to OUT)
    fspm-tf display FILE --remove [-o OUT]      remove them
    fspm-tf compare ACTUAL EXPECTED             a codec's JSON dump (or a .glb) against expected values; exit 1 if they
                                                differ
    fspm-tf compare-all DUMPS CONFORMANCE       every conformance file's expected values against the dump at the same
                                                path (x.expected.json: DUMPS/x.json); exit 1 if any differ
    fspm-tf couple --steps N --interval DT [--participant NAME=COMMAND]... [--expect NAME]...
                   [--replay NAME=INDEX]... [--links LINKS.json] [--stages A,B;C] [--endpoint E] [--record DIR]
                                                run a coupling session (specification §11): launch the participants'
                                                commands, wait for the expected ones, replay sequences; exit 1 if it
                                                stops on an error
    fspm-tf couple-conformance SESSIONS --participant COMMAND [--out DIR] [--transport zmq|files]
                                                run the coupling conformance sessions (conformance/coupling) with
                                                COMMAND SESSION OUT as the participant under test; exit 1 if what it
                                                read, or the session's record, differs from the expected values
"""
import argparse
import sys

from openalea.fspm_tf import read, write
from openalea.fspm_tf.display import add_display, remove_display
from openalea.fspm_tf.validate import validate_file


def _validate(arguments) -> int:
    failed = False
    for path in arguments.files:
        report = validate_file(path)
        print(report)
        failed = failed or not report.ok
    return 1 if failed else 0


def _info(arguments) -> int:
    frame = read(arguments.file)
    print(f"{arguments.file}: time {frame.time} {frame.time_unit}, step {frame.step}, writer {frame.writer or '-'}")
    for data_structure in frame.data_structures:
        print(f"  {data_structure.id} ({data_structure.kind}{', ' + data_structure.model if data_structure.model else ''})")
        for entity_set in data_structure.entity_sets:
            rank = "" if entity_set.rank is None else f" rank {entity_set.rank}"
            print(f"    {entity_set.name}{rank}: {entity_set.count} entities, variables "
                  f"{', '.join(entity_set.variable_names()) or '-'}")
        for relation in data_structure.relations:
            print(f"    relation {relation.name} ({relation.source_set} -> {relation.target_set}): {relation.count}")
        if data_structure.scalars is not None:
            print(f"    scalars: {', '.join(data_structure.scalars.columns)}")
        for mesh in data_structure.meshes:
            print(f"    mesh {mesh.name}: {len(mesh.positions)} vertices, entity sets {', '.join(mesh.feature_rows)}"
                  f"{', display ' + ', '.join(mesh.display) if mesh.display else ''}")
    for mapping in frame.mappings:
        print(f"  mapping {mapping.name}: {mapping.source[0]}/{mapping.source[1]} -> "
              f"{mapping.target[0]}/{mapping.target[1]}, {mapping.count} pairs")
    return 0


def _display(arguments) -> int:
    frame = read(arguments.file)
    if arguments.remove:
        remove_display(frame, arguments.names or None)
    else:
        if not arguments.names:
            print("give the names of the variables to copy, or --remove", file=sys.stderr)
            return 2
        add_display(frame, arguments.names, entity_set=arguments.entity_set)
    write(arguments.output or arguments.file, frame)
    return 0


def _print_differences(name: str, differences: list, shown: int = 20) -> None:
    print(f"{name}: {'equal' if not differences else f'{len(differences)} difference(s)'}")
    for line in differences[:shown]:
        print(f"  {line}")
    if len(differences) > shown:
        print(f"  ... {len(differences) - shown} more")


def _compare(arguments) -> int:
    from openalea.fspm_tf.compare import compare_files
    differences = compare_files(arguments.actual, arguments.expected)
    _print_differences(arguments.actual, differences)
    return 1 if differences else 0


def _compare_all(arguments) -> int:
    from openalea.fspm_tf.compare import compare_all
    results = compare_all(arguments.dumps, arguments.conformance)
    for name, differences in results.items():
        _print_differences(name, differences)
    failed = sum(1 for differences in results.values() if differences)
    print(f"{len(results) - failed} of {len(results)} conformance files read as expected")
    return 1 if failed or not results else 0


def _pairs(values, what: str) -> dict:
    pairs = {}
    for value in values or []:
        name, separator, rest = value.partition("=")
        if not separator or not name or not rest:
            raise SystemExit(f"--{what} {value}: NAME=VALUE expected")
        pairs[name] = rest
    return pairs


def _couple(arguments) -> int:
    import json
    from openalea.fspm_tf.coupling import Coordinator, CouplingError
    links = []
    if arguments.links:
        with open(arguments.links, encoding="utf-8") as file:
            links = json.load(file)
    stages = None if not arguments.stages else [stage.split(",") for stage in arguments.stages.split(";")]
    coordinator = Coordinator(arguments.endpoint, steps=arguments.steps, interval=arguments.interval,
                              time_unit=arguments.time_unit, start=arguments.start, links=links, stages=stages,
                              expect=arguments.expect or [], replays=_pairs(arguments.replay, "replay"),
                              record=arguments.record, timeout=arguments.timeout)
    print(f"coordinator at {coordinator.endpoint}", flush=True)
    for name, command in _pairs(arguments.participant, "participant").items():
        coordinator.launch(name, command)
    try:
        coordinator.run()
    except CouplingError as error:
        print(f"the session stopped: {error}", file=sys.stderr)
        return 1
    for coupling in coordinator.couplings:
        source = "-" if coupling.source is None else f"{coupling.provider}.{coupling.source.name}"
        print(f"  {coupling.receiver}.{coupling.variable.name} <- {source} ({coupling.how}"
              f"{', ' + coupling.aggregation if coupling.aggregation else ''}, factor {coupling.factor:g})")
    print(f"{arguments.steps} steps, stages {coordinator.stages}" +
          (f", recorded in {arguments.record}" if arguments.record else ""))
    return 0


def _couple_conformance(arguments) -> int:
    import tempfile
    from openalea.fspm_tf.coupling.conformance import TRANSPORTS, run_all
    out = arguments.out or tempfile.mkdtemp(prefix="fspm_tf_sessions_")
    transports = [arguments.transport] if arguments.transport else list(TRANSPORTS)
    results = run_all(arguments.sessions, arguments.participant, out, transports)
    for (name, transport), differences in results.items():
        _print_differences(f"{name} ({transport})", differences)
    failed = sum(1 for differences in results.values() if differences)
    print(f"{len(results) - failed} of {len(results)} sessions as expected (outputs in {out})")
    return 1 if failed or not results else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fspm-tf", description="fspm-TF files: validate, inspect, display; couple platforms")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="check frames (.glb) or sequences (scene.fspm.json)")
    validate.add_argument("files", nargs="+")
    validate.set_defaults(run=_validate)
    info = commands.add_parser("info", help="what a frame holds")
    info.add_argument("file")
    info.set_defaults(run=_info)
    display = commands.add_parser("display", help="add or remove display copies of variables")
    display.add_argument("file")
    display.add_argument("names", nargs="*")
    display.add_argument("--entity-set", default=None, help="the entity set the variables come from")
    display.add_argument("--remove", action="store_true", help="remove display copies (all, or the names given)")
    display.add_argument("-o", "--output", default=None, help="write to this file instead of in place")
    display.set_defaults(run=_display)
    compare = commands.add_parser("compare", help="a codec's JSON dump (or a .glb) against expected values")
    compare.add_argument("actual")
    compare.add_argument("expected")
    compare.set_defaults(run=_compare)
    compare_all = commands.add_parser("compare-all", help="dumps of every conformance file against their expected "
                                                          "values")
    compare_all.add_argument("dumps", help="the folder of the codec's dumps (x.json for x.expected.json)")
    compare_all.add_argument("conformance", help="fspm-TF's conformance folder")
    compare_all.set_defaults(run=_compare_all)
    couple = commands.add_parser("couple", help="run a coupling session between platforms")
    couple.add_argument("--steps", type=int, required=True)
    couple.add_argument("--interval", type=float, required=True, help="the exchange interval")
    couple.add_argument("--time-unit", default="d")
    couple.add_argument("--start", type=float, default=0.)
    couple.add_argument("--participant", action="append", help="NAME=COMMAND: a participant to launch")
    couple.add_argument("--expect", action="append", help="NAME: a participant started separately")
    couple.add_argument("--replay", action="append", help="NAME=INDEX: a recorded sequence as a participant")
    couple.add_argument("--links", help="a JSON file: the session's links")
    couple.add_argument("--stages", help="the stages, e.g. 'growth;function,light' (default: owners, refiners, "
                                         "others)")
    couple.add_argument("--endpoint", default="tcp://127.0.0.1:*", help="a ZeroMQ endpoint, or files:FOLDER")
    couple.add_argument("--record", help="a folder: the session recorded as a sequence")
    couple.add_argument("--timeout", type=float, default=600., help="seconds to wait for a message")
    couple.set_defaults(run=_couple)
    sessions = commands.add_parser("couple-conformance", help="a participant's side against the coupling "
                                                              "conformance sessions")
    sessions.add_argument("sessions", help="the sessions' folder (conformance/coupling)")
    sessions.add_argument("--participant", required=True, help="the command of the participant under test; it is "
                                                               "run as COMMAND SESSION OUT")
    sessions.add_argument("--out", help="where the outputs go (default: a new temporary folder)")
    sessions.add_argument("--transport", choices=["zmq", "files"], help="one transport only (default: both)")
    sessions.set_defaults(run=_couple_conformance)
    arguments = parser.parse_args(argv)
    return arguments.run(arguments)


if __name__ == "__main__":
    sys.exit(main())
