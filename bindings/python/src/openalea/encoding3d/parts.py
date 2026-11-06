"""
Where a frame's shared parts are found (specification §12.1), by content key: embedded in the frame, else
parts/<key>.glb in the frame's folder (a sequence's folder or archive)::

    frame.part(key) -> Template | Operator        through frame.parts, a Parts
    prune_parts(index_path) -> [keys]             the parts no frame of the sequence refers to, removed
"""
import hashlib
import os

from openalea.encoding3d import archive

PARTS_FOLDER = "parts"


class MissingPartError(LookupError):
    """A part a frame refers to is nowhere it may be: its key and where it was looked for."""

    def __init__(self, key: str, looked: list):
        self.key, self.looked = key, list(looked)
        super().__init__(f"the shared part {key} is missing (looked for {', '.join(map(str, self.looked)) or '-'}): "
                         "copy the sequence's parts/ folder with its frames, or write the frame with "
                         "embed_parts=True")

    def __reduce__(self):
        return MissingPartError, (self.key, self.looked)


def content_key(data: bytes) -> str:
    """A part's key: the SHA-256 of its GLB bytes, in lower-case hexadecimal."""
    return hashlib.sha256(data).hexdigest()


def part_file(key: str) -> str:
    """The path of a part in a sequence's folder, relative to it: parts/<key>.glb."""
    return f"{PARTS_FOLDER}/{key}.glb"


class Parts:
    """A frame's parts: those embedded in it (*embedded*: {key: GLB bytes}), else parts/<key>.glb under *folder* (the
    frame's folder, or an archive's: x.fspm.zip). Each part is decoded once, then kept."""

    def __init__(self, embedded: dict = None, folder: str = None):
        self.embedded = dict(embedded or {})
        self.folder = folder
        self._decoded = {}

    def path(self, key: str):
        """Where the part *key* is when it is not embedded (None: no folder)."""
        return None if self.folder is None else os.path.join(self.folder, PARTS_FOLDER, f"{key}.glb")

    def looked(self, key: str) -> list:
        return (["the frame (embedded)"] if self.embedded else []) + ([self.path(key)] if self.folder else [])

    def __contains__(self, key: str) -> bool:
        return key in self.embedded or (self.folder is not None and archive.exists(self.path(key)))

    def bytes(self, key: str) -> bytes:
        """The GLB bytes of the part *key*; MissingPartError when it is nowhere."""
        if key in self.embedded:
            return bytes(self.embedded[key])
        path = self.path(key)
        if path is not None and archive.exists(path):
            return archive.read_bytes(path)
        raise MissingPartError(key, self.looked(key))

    def __getitem__(self, key: str):
        if key not in self._decoded:
            from openalea.encoding3d.codec import read_part
            self._decoded[key] = read_part(self.bytes(key), key=key)
        return self._decoded[key]


def prune_parts(index_path: str) -> list:
    """Remove from a sequence's parts/ folder the parts none of its frames (those its index lists) refers to, and
    list in the index the parts they refer to; the keys removed. For a writer that removes frames (a run restarted
    from a checkpoint, frames thinned out)."""
    from openalea.encoding3d.codec import frame_part_keys, read_index, rewrite_index_parts
    index = read_index(index_path)
    referenced = set()
    for entry in index["frames"]:
        referenced |= set(frame_part_keys(entry["path"]))
    folder = os.path.join(os.path.dirname(os.path.abspath(index_path)), PARTS_FOLDER)
    removed = []
    for name in archive.listing(folder):
        key, extension = os.path.splitext(name)
        if extension == ".glb" and key not in referenced:
            os.remove(os.path.join(folder, name))
            removed.append(key)
    present = {key for key in referenced if archive.exists(os.path.join(folder, f"{key}.glb"))}
    rewrite_index_parts(index_path, sorted(present))
    return sorted(removed)
