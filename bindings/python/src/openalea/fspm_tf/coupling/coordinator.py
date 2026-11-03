"""
The coordinator: it runs a session between participants it launches (commands) or that connect to it, and replayed
sequences.

1. Each participant sends its hello (its declaration, and links it proposes); the session's links are those given to
   the coordinator and those proposed, the given ones first.
2. Resolution (resolution.resolve, resolution.stages): each input's provider, the stages. Each participant is
   welcomed with its id range and its couplings, or the session stops with the reason.
3. Initial state: stage by stage, each participant is sent a turn of step 0 (the entities so far and its inputs) and
   answers with its initial outputs and entities.
4. Steps 1 … steps: stage by stage, the participants of a stage are sent their turn (time t → t + interval: their
   inputs, the entities added or removed since their last turn), and their updates are merged once all of them
   answered (so within a stage they see the same state, and the next stage sees theirs).
5. Stop. A participant's error, or its update the store refuses, stops the session: every participant is told why.

*record*: a folder where the session is written as a sequence of full frames (every entity set and output), after the
initial state and each step.
"""
import os
import subprocess
import sys
import time as clock

from openalea.fspm_tf.codec import from_bytes, to_bytes, write, write_index
from openalea.fspm_tf.coupling.channels import (ChannelTimeout, ENDPOINT_VARIABLE, PARTICIPANT_VARIABLE,
                                                coordinator_channel)
from openalea.fspm_tf.coupling.messages import (ID_COUNT, PROTOCOL_VERSION, CouplingError, Declaration, Link)
from openalea.fspm_tf.coupling.replay import Replay
from openalea.fspm_tf.coupling.resolution import ranks, resolve, stages
from openalea.fspm_tf.coupling.store import SessionStore


class Coordinator:
    def __init__(self, endpoint: str = "tcp://127.0.0.1:*", steps: int = 1, interval: float = 1.,
                 time_unit: str = "d", start: float = 0., links=(), stages=None, expect=(), replays=None,
                 record: str = None, timeout: float = 600.):
        self.channel = coordinator_channel(endpoint)
        self.endpoint = self.channel.endpoint
        self.steps, self.interval, self.time_unit, self.start = steps, interval, time_unit, start
        self.links = [link if isinstance(link, Link) else Link.from_json(link) for link in links]
        self.given_stages = stages
        self.expect = list(expect)
        self.replays = {name: Replay(name, path) for name, path in (replays or {}).items()}
        self.record, self.timeout = record, timeout
        self.processes = {}
        self.declarations, self.offsets, self.removed_seen = {}, {}, {}
        self.couplings, self.stages, self.store = [], [], None
        self.recorded = []

    # ── launching ─────────────────────────────────────────────────────────────────
    def launch(self, name: str, command, environment=None, cwd=None) -> None:
        """Start participant *name*: *command* (a list, or a string run by the shell) with FSPM_TF_ENDPOINT and
        FSPM_TF_PARTICIPANT set; the session waits for its hello."""
        environment = dict(os.environ if environment is None else environment)
        environment[ENDPOINT_VARIABLE] = self.endpoint
        environment[PARTICIPANT_VARIABLE] = name
        self.processes[name] = subprocess.Popen(command, env=environment, cwd=cwd, shell=isinstance(command, str))
        self.expect.append(name)

    def _check_processes(self) -> None:
        for name, process in self.processes.items():
            code = process.poll()
            if code not in (None, 0) or (code == 0 and name not in self.finished):
                raise CouplingError(f"participant {name} exited with code {code} during the session")

    def _receive(self):
        """The next message, watching the launched participants and the timeout."""
        deadline = None if self.timeout is None else clock.monotonic() + self.timeout
        while True:
            try:
                return self.channel.receive(0.2)
            except ChannelTimeout:
                self._check_processes()
                if deadline is not None and clock.monotonic() > deadline:
                    raise CouplingError(f"no message in {self.timeout} s") from None

    # ── the session ──────────────────────────────────────────────────────────────
    def run(self) -> SessionStore:
        """Run the session; the session's store at its end."""
        self.finished = set()
        try:
            self._join()
            self._run_steps()
        except Exception as error:
            self._stop(f"{type(error).__name__}: {error}")
            self._wait_processes()
            raise
        self._stop("end of the session")
        self._wait_processes()
        if self.record and self.recorded:
            write_index(os.path.join(self.record, "scene.fspm.json"), self.recorded, time_unit=self.time_unit)
        return self.store

    def _join(self) -> None:
        pending = set(self.expect)
        proposed = []
        for name, replay in self.replays.items():
            self.declarations[name] = replay.declaration
        while pending:
            participant, header, _ = self._receive()
            if header.get("type") == "error":
                raise CouplingError(f"{participant}: {header.get('message')}")
            if header.get("type") != "hello":
                raise CouplingError(f"{participant}: expected its hello, got {header.get('type')}")
            if header.get("protocol") != PROTOCOL_VERSION:
                raise CouplingError(f"{participant}: protocol {header.get('protocol')}, the coordinator's is "
                                    f"{PROTOCOL_VERSION}")
            declaration = Declaration.from_json(header["declaration"])
            if declaration.participant != participant:
                raise CouplingError(f"{participant} declares itself as {declaration.participant}")
            if participant in self.declarations:
                raise CouplingError(f"two participants named {participant}")
            if participant not in pending:
                raise CouplingError(f"{participant} is not expected (expected: {sorted(self.expect)})")
            self.declarations[participant] = declaration
            proposed += [Link.from_json(link) for link in header.get("links", [])]
            pending.discard(participant)
        given = {(link.receiver, link.variable, link.entity_set) for link in self.links}
        links = self.links + [link for link in proposed
                              if (link.receiver, link.variable, link.entity_set) not in given]
        self.couplings = resolve(self.declarations, links)
        self.stages = stages(self.declarations, self.given_stages)
        self.store = SessionStore(ranks(self.declarations))
        order = [name for name in self.expect if name in self.declarations] + list(self.replays)
        for position, name in enumerate(order):                 # deterministic: the expected order, then replays
            self.offsets[name] = (position + 1) * ID_COUNT
            self.removed_seen[name] = 0
        for name, replay in self.replays.items():
            replay.id_offset = self.offsets[name]
            replay.linear = {(coupling.source.data_structure, coupling.source.entity_set, coupling.source.name)
                             for coupling in self.couplings
                             if coupling.provider == name and coupling.interpolation == "linear"}
        session = {"start": self.start, "interval": self.interval, "timeUnit": self.time_unit, "steps": self.steps,
                   "stages": self.stages, "participants": list(self.declarations)}
        for name in self.declarations:
            if name in self.replays:
                continue
            self.channel.send(name, {"type": "welcome", "idOffset": self.offsets[name], "idCount": ID_COUNT,
                                     "session": session,
                                     "couplings": [coupling.to_json() for coupling in self.couplings
                                                   if coupling.receiver == name]})

    def _run_steps(self) -> None:
        for step in range(self.steps + 1):
            time = self.start + max(step - 1, 0) * self.interval
            until = self.start + step * self.interval
            for stage in self.stages:
                updates = {}
                live = [name for name in stage if name not in self.replays]
                for name in live:
                    frame = self.store.inputs(name, self.declarations[name], self.couplings, self.removed_seen[name],
                                              time, self.time_unit, step)
                    self.removed_seen[name] = len(self.store.removed_log)
                    self.channel.send(name, {"type": "turn", "step": step, "phase": "init" if step == 0 else "step",
                                             "time": time, "until": until}, to_bytes(frame))
                for name in stage:
                    if name in self.replays:
                        updates[name] = self.replays[name].update(until, self.time_unit)
                waiting = set(live)
                while waiting:
                    participant, header, payload = self._receive()
                    if header.get("type") == "error":
                        raise CouplingError(f"{participant}: {header.get('message')}")
                    if header.get("type") != "update" or participant not in waiting:
                        raise CouplingError(f"{participant}: unexpected {header.get('type')} at step {step}")
                    if header.get("step") != step:
                        raise CouplingError(f"{participant}: update of step {header.get('step')} at step {step}")
                    updates[participant] = from_bytes(payload)
                    waiting.discard(participant)
                for name in stage:                      # merged in the stage's order, once all answered
                    self.store.merge(name, self.declarations[name], updates[name], self.offsets[name])
            if self.record:
                os.makedirs(self.record, exist_ok=True)
                path = f"frame_{step:05d}.glb"
                write(os.path.join(self.record, path), self.store.frame(until, self.time_unit, step))
                self.recorded.append({"time": until, "step": step, "file": path})

    def _stop(self, reason: str) -> None:
        for name in self.declarations:
            if name in self.replays:
                continue
            try:
                self.channel.send(name, {"type": "stop", "reason": reason})
            except Exception:                            # a participant already gone
                pass
        self.finished = set(self.declarations)

    def _wait_processes(self) -> None:
        for name, process in self.processes.items():
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
        self.channel.close()


def python_command(script: str, *arguments) -> list:
    """The command running a Python *script* with this interpreter."""
    return [sys.executable, script, *map(str, arguments)]
