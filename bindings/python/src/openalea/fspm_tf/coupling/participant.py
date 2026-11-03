"""
A participant's side of a session: what a platform calls to take part, whatever its own model is::

    from openalea.fspm_tf.coupling import Declaration, Participant

    participant = Participant.connect(declaration)          # endpoint and name from the environment if launched
    for turn in participant.turns():                         # until the coordinator stops the session
        inputs = turn.frame                                  # its entity sets, their entities and its inputs
        ...                                                  # its model, from turn.time to turn.until
        participant.send(frame)                              # its outputs and topology changes (a partial frame)

The ids of the entities it creates are in [participant.id_offset, participant.id_offset + ID_COUNT).
"""
import os
from dataclasses import dataclass

from openalea.fspm_tf.codec import from_bytes, to_bytes
from openalea.fspm_tf.coupling.channels import (ENDPOINT_VARIABLE, PARTICIPANT_VARIABLE, participant_channel)
from openalea.fspm_tf.coupling.messages import PROTOCOL_VERSION, CouplingError, Declaration, Link
from openalea.fspm_tf.model import Frame, Update


@dataclass
class Turn:
    """A turn: *step* (0: the initial state, "init"), the time it starts from and the time it reaches (*until*;
    equal at init), and the frame of the participant's inputs (its entity sets, their entities, its inputs, and in
    frame.update.removed the entities removed since its last turn)."""
    step: int
    phase: str
    time: float
    until: float
    frame: Frame


class Participant:
    def __init__(self, channel, declaration: Declaration, timeout=None):
        self.channel, self.declaration, self.timeout = channel, declaration, timeout
        self.id_offset = None
        self.session = None
        self.couplings = []
        self.step = None
        self.stopped = None

    @classmethod
    def connect(cls, declaration: Declaration, endpoint: str = None, links=(), timeout=None) -> "Participant":
        """Join the session at *endpoint* (default: the environment's FSPM_TF_ENDPOINT, set by the coordinator
        launching the participant; its name: FSPM_TF_PARTICIPANT if the declaration has none): send the declaration
        (and the *links* it proposes), wait for the welcome."""
        endpoint = endpoint or os.environ.get(ENDPOINT_VARIABLE)
        if not endpoint:
            raise CouplingError(f"no endpoint: give one, or set {ENDPOINT_VARIABLE}")
        if not declaration.participant:
            declaration.participant = os.environ.get(PARTICIPANT_VARIABLE, "")
        participant = cls(participant_channel(endpoint, declaration.participant), declaration.complete(), timeout)
        participant.channel.send({"type": "hello", "protocol": PROTOCOL_VERSION,
                                  "declaration": declaration.to_json(),
                                  "links": [link.to_json() if isinstance(link, Link) else link for link in links]})
        header, _ = participant.channel.receive(timeout)
        if header["type"] == "stop":
            raise CouplingError(f"the coordinator refused {declaration.participant}: {header.get('reason')}")
        if header["type"] != "welcome":
            raise CouplingError(f"expected a welcome, got {header['type']}")
        participant.id_offset = header["idOffset"]
        participant.session = header["session"]
        participant.couplings = header.get("couplings", [])
        return participant

    def turns(self):
        """The turns, until the coordinator stops the session (self.stopped: its reason)."""
        while True:
            header, payload = self.channel.receive(self.timeout)
            if header["type"] == "stop":
                self.stopped = header.get("reason", "")
                self.channel.close()
                return
            if header["type"] != "turn":
                raise CouplingError(f"expected a turn, got {header['type']}")
            self.step = header["step"]
            yield Turn(header["step"], header["phase"], header["time"], header["until"], from_bytes(payload))

    def send(self, frame: Frame) -> None:
        """Send the turn's outputs: *frame* holds, per entity set, the ids and the outputs of the rows sent (and the
        topology columns of the entities it adds or changes); frame.update.removed the entities it removed."""
        if frame.update is None:
            frame.update = Update(self.declaration.participant)
        frame.update.participant = self.declaration.participant
        self.channel.send({"type": "update", "step": self.step}, to_bytes(frame))

    def fail(self, message: str) -> None:
        """Tell the coordinator this participant cannot go on (the session stops)."""
        self.channel.send({"type": "error", "message": message})
