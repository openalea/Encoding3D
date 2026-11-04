"""
The session's transports. A message is a JSON header and, for turns and updates, a payload: a partial frame's GLB
bytes. Both transports carry the same messages:

- ZeroMQ (endpoint "tcp://host:port" or "ipc://path"): the coordinator binds a ROUTER socket, each participant
  connects a DEALER socket whose identity is its name; a message is two parts (header, payload) or one (header).
- a folder (endpoint "files:path"): each participant has a folder <path>/<participant>/ with two message queues,
  to_coordinator/ and to_participant/; message n is n.json (its header) and n.glb (its payload), the payload written
  first and the header renamed into place last (a header present: a complete message). Nothing else is needed than
  files, so any platform can take part. Each message is deleted by its reader once read, unless the session keeps
  them (keepMessages: the folder is then the session's log; a record, Coordinator(record=), is the usual one).

Both sides poll; every wait has a timeout (seconds, None: none).
"""
import json
import os
import time

POLL = 0.005                                         # seconds between two looks at a folder queue
ENDPOINT_VARIABLE = "ENCODING3D_ENDPOINT"               # what a launched participant connects to
PARTICIPANT_VARIABLE = "ENCODING3D_PARTICIPANT"         # its name


class ChannelTimeout(TimeoutError):
    pass


def _header(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))


def _bytes(header: dict) -> bytes:
    return json.dumps(header, separators=(",", ":")).encode("utf-8")


# ── ZeroMQ ───────────────────────────────────────────────────────────────────────
class ZmqCoordinatorChannel:
    def __init__(self, endpoint: str = "tcp://127.0.0.1:*"):
        import zmq
        self._zmq = zmq
        self.context = zmq.Context.instance()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.setsockopt(zmq.LINGER, 1000)
        self.socket.bind(endpoint)
        self.endpoint = self.socket.getsockopt_string(zmq.LAST_ENDPOINT)

    def receive(self, timeout=None):
        """(participant, header, payload or None)."""
        if not self.socket.poll(None if timeout is None else int(timeout * 1000)):
            raise ChannelTimeout(f"no message in {timeout} s")
        parts = self.socket.recv_multipart()
        return parts[0].decode("utf-8"), _header(parts[1]), parts[2] if len(parts) > 2 else None

    def send(self, participant: str, header: dict, payload: bytes = None) -> None:
        parts = [participant.encode("utf-8"), _bytes(header)] + ([payload] if payload is not None else [])
        self.socket.send_multipart(parts)

    def close(self) -> None:
        self.socket.close()


class ZmqParticipantChannel:
    def __init__(self, endpoint: str, participant: str):
        import zmq
        self.context = zmq.Context.instance()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt(zmq.IDENTITY, participant.encode("utf-8"))
        self.socket.setsockopt(zmq.LINGER, 1000)
        self.socket.connect(endpoint)

    def receive(self, timeout=None):
        """(header, payload or None)."""
        if not self.socket.poll(None if timeout is None else int(timeout * 1000)):
            raise ChannelTimeout(f"no message in {timeout} s")
        parts = self.socket.recv_multipart()
        return _header(parts[0]), parts[1] if len(parts) > 1 else None

    def send(self, header: dict, payload: bytes = None) -> None:
        self.socket.send_multipart([_bytes(header)] + ([payload] if payload is not None else []))

    def close(self) -> None:
        self.socket.close()


# ── a folder ─────────────────────────────────────────────────────────────────────
class _Queue:
    """A folder of numbered messages, written by one side and read by the other."""

    def __init__(self, folder: str):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.next_read = 0
        self.next_write = 0
        self.keep = True                                # False: a message's files deleted once read
        self.read_files = []                            # those of the messages read and kept

    def discard_read(self) -> None:
        """Delete the files of the messages read so far, and from now on each message once read."""
        self.keep = False
        for path in self.read_files:
            if os.path.exists(path):
                os.remove(path)
        self.read_files = []

    def write(self, header: dict, payload: bytes = None) -> None:
        stem = os.path.join(self.folder, f"{self.next_write:08d}")
        if payload is not None:
            with open(stem + ".glb", "wb") as file:
                file.write(payload)
            header = dict(header, payload=os.path.basename(stem) + ".glb")
        with open(stem + ".json.part", "wb") as file:
            file.write(_bytes(header))
        os.replace(stem + ".json.part", stem + ".json")
        self.next_write += 1

    def read(self):
        """The next message (header, payload or None), or None if not there yet."""
        stem = os.path.join(self.folder, f"{self.next_read:08d}")
        if not os.path.exists(stem + ".json"):
            return None
        with open(stem + ".json", "rb") as file:
            header = _header(file.read())
        payload, files = None, [stem + ".json"]
        if "payload" in header:
            files.append(os.path.join(self.folder, header.pop("payload")))
            with open(files[-1], "rb") as file:
                payload = file.read()
        self.next_read += 1
        if self.keep:
            self.read_files += files
        else:
            for path in files:
                os.remove(path)
        return header, payload


class FolderCoordinatorChannel:
    def __init__(self, folder: str, keep: bool = False):
        self.folder = os.path.abspath(folder)
        os.makedirs(self.folder, exist_ok=True)
        for name in os.listdir(self.folder):            # a session's folder is the log of that session only
            if os.path.exists(os.path.join(self.folder, name, "to_participant", f"{0:08d}.json")):
                raise ValueError(f"{self.folder} holds a previous session ({name}): use a new folder")
        self.endpoint = "files:" + self.folder
        self.keep = keep
        self.incoming, self.outgoing = {}, {}

    def _discover(self) -> None:
        for name in sorted(os.listdir(self.folder)):
            if name not in self.incoming and os.path.isdir(os.path.join(self.folder, name, "to_coordinator")):
                self.incoming[name] = _Queue(os.path.join(self.folder, name, "to_coordinator"))
                if not self.keep:
                    self.incoming[name].discard_read()
                self.outgoing[name] = _Queue(os.path.join(self.folder, name, "to_participant"))

    def receive(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            self._discover()
            for name, queue in self.incoming.items():
                message = queue.read()
                if message is not None:
                    return (name,) + message
            if deadline is not None and time.monotonic() > deadline:
                raise ChannelTimeout(f"no message in {timeout} s")
            time.sleep(POLL)

    def send(self, participant: str, header: dict, payload: bytes = None) -> None:
        self._discover()
        self.outgoing[participant].write(header, payload)

    def close(self) -> None:
        pass


class FolderParticipantChannel:
    def __init__(self, folder: str, participant: str):
        base = os.path.join(folder, participant)
        self.incoming = _Queue(os.path.join(base, "to_participant"))
        self.outgoing = _Queue(os.path.join(base, "to_coordinator"))

    def receive(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            message = self.incoming.read()
            if message is not None:
                return message
            if deadline is not None and time.monotonic() > deadline:
                raise ChannelTimeout(f"no message in {timeout} s")
            time.sleep(POLL)

    def send(self, header: dict, payload: bytes = None) -> None:
        self.outgoing.write(header, payload)

    def keep_messages(self, keep: bool) -> None:
        """As the session says (its welcome): keep the messages read, or delete them (those read so far too)."""
        if not keep:
            self.incoming.discard_read()

    def close(self) -> None:
        pass


def coordinator_channel(endpoint: str, keep_messages: bool = False):
    """The coordinator's side of *endpoint*: "files:path", or a ZeroMQ endpoint to bind ("tcp://127.0.0.1:*": a
    free port). *keep_messages*: the folder transport keeps every message (the session's log)."""
    if endpoint.startswith("files:"):
        return FolderCoordinatorChannel(endpoint[len("files:"):], keep_messages)
    return ZmqCoordinatorChannel(endpoint)


def participant_channel(endpoint: str, participant: str):
    """A participant's side of *endpoint*."""
    if endpoint.startswith("files:"):
        return FolderParticipantChannel(endpoint[len("files:"):], participant)
    return ZmqParticipantChannel(endpoint, participant)
