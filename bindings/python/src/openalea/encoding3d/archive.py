"""
A sequence as one file: a `.fspm.zip` holding the folder's layout (specification §8.2), every member an unchanged
file of it (scene.fspm.json, views.json, frame_*.glb, parts/<key>.glb), compressed member by member, so that each one
is read alone::

    pack(folder, path, compression="deflate")      the sequence of *folder* (or of its scene.fspm.json) as a ZIP64 archive
    unpack(path, folder)                           the archive's members back as a folder; its index's path

A file inside an archive has the path "<archive>.fspm.zip/<member>" (e.g. run.fspm.zip/frame_000003.glb): read,
read_index, read_sequence, validate_file and ParaView's reader take such paths, and the archive itself, as they take
the folder's. read_bytes, exists and listing are the file access the codec uses for both.
"""
import os
import zipfile

ARCHIVE_SUFFIX = ".fspm.zip"
COMPRESSIONS = {"deflate": zipfile.ZIP_DEFLATED, "lzma": zipfile.ZIP_LZMA, "stored": zipfile.ZIP_STORED}
DEFAULT_COMPRESSION = "deflate"
_OPEN = {}                      # {archive path: (its modification time and size, the open ZipFile)}
_KEPT_OPEN = 4


def split(path: str):
    """(archive, member) when *path* is an archive ("x.fspm.zip": its index) or a file inside one
    ("x.fspm.zip/frame_000000.glb"), else None."""
    path = os.fspath(path)
    normalised = path.replace(os.sep, "/")
    position = normalised.find(ARCHIVE_SUFFIX + "/")
    if normalised.endswith(ARCHIVE_SUFFIX) and os.path.isfile(path):
        return path, "scene.fspm.json"
    while position >= 0:
        archive = path[:position + len(ARCHIVE_SUFFIX)]
        if os.path.isfile(archive):
            return archive, normalised[position + len(ARCHIVE_SUFFIX) + 1:]
        position = normalised.find(ARCHIVE_SUFFIX + "/", position + 1)
    return None


def _zip(archive: str) -> zipfile.ZipFile:
    status = os.stat(archive)
    stamp = (status.st_mtime_ns, status.st_size)
    found = _OPEN.get(archive)
    if found is not None and found[0] == stamp:
        return found[1]
    if found is not None:
        found[1].close()
    while len(_OPEN) >= _KEPT_OPEN:
        _OPEN.pop(next(iter(_OPEN)))[1].close()
    opened = zipfile.ZipFile(archive)
    _OPEN[archive] = (stamp, opened)
    return opened


def _member(member: str) -> str:
    parts = [part for part in member.replace("\\", "/").split("/") if part not in ("", ".")]
    if ".." in parts:
        raise ValueError(f"member '{member}': no '..' in an archive's paths")
    return "/".join(parts)


def read_bytes(path: str) -> bytes:
    """The bytes of the file *path*, in a folder or in an archive."""
    inside = split(path)
    if inside is None:
        with open(path, "rb") as file:
            return file.read()
    archive, member = inside
    try:
        return _zip(archive).read(_member(member))
    except KeyError:
        raise FileNotFoundError(f"{archive} holds no '{member}'") from None


def exists(path: str) -> bool:
    inside = split(path)
    if inside is None:
        return os.path.exists(path)
    archive, member = inside
    try:
        _zip(archive).getinfo(_member(member))
        return True
    except KeyError:
        return False


def listing(folder: str) -> list:
    """The names of the files directly in *folder* (in a folder or in an archive); [] when there is none."""
    inside = split(folder.rstrip("/") + "/")
    if inside is None:
        return sorted(name for name in os.listdir(folder) if os.path.isfile(os.path.join(folder, name))) \
            if os.path.isdir(folder) else []
    archive, member = inside
    prefix = _member(member)
    prefix = prefix + "/" if prefix else ""
    return sorted(name[len(prefix):] for name in _zip(archive).namelist()
                  if name.startswith(prefix) and "/" not in name[len(prefix):])


def index_of(path: str) -> str:
    """The index of the sequence *path*: an archive's (x.fspm.zip/scene.fspm.json), a folder's, or *path* itself."""
    from openalea.encoding3d.codec import INDEX_FILE
    if os.path.isdir(path):
        return os.path.join(path, INDEX_FILE)
    if os.fspath(path).endswith(ARCHIVE_SUFFIX) and os.path.isfile(path):
        return os.path.join(path, INDEX_FILE)
    return path


def sequence_members(index_path: str) -> list:
    """The files of the sequence of *index_path*, relative to its folder: the index, views.json when there is one,
    each frame, and each part its frames or its index refer to."""
    from openalea.encoding3d.codec import INDEX_FILE, frame_part_keys, part_file
    from openalea.encoding3d.views import VIEWS_FILE
    import json
    folder = os.path.dirname(os.path.abspath(index_path))
    index = json.loads(read_bytes(index_path).decode("utf-8"))
    members = [INDEX_FILE] + ([VIEWS_FILE] if exists(os.path.join(folder, VIEWS_FILE)) else [])
    keys = set(index.get("parts", {}))
    for entry in index["frames"]:
        members.append(entry["file"])
        keys |= set(frame_part_keys(os.path.join(folder, entry["file"])))
    return members + [part_file(key) for key in sorted(keys)]


def pack(folder: str, path: str, compression: str = DEFAULT_COMPRESSION, level: int = None) -> str:
    """The sequence of *folder* (a folder, or its scene.fspm.json) packed into the ZIP64 archive *path*
    (x.fspm.zip): the index, views.json, the frames and the parts they refer to, unchanged, each compressed alone
    (*compression*: "deflate", "lzma" or "stored"; *level*: deflate's 0-9). Written next to *path* first, then moved
    into place. Returns *path*."""
    if compression not in COMPRESSIONS:
        raise ValueError(f"compression '{compression}': one of {sorted(COMPRESSIONS)}")
    if not os.fspath(path).endswith(ARCHIVE_SUFFIX):
        raise ValueError(f"'{path}': an archive's name ends in {ARCHIVE_SUFFIX}")
    index_path = index_of(folder)
    base = os.path.dirname(os.path.abspath(index_path))
    members = sequence_members(index_path)
    missing = [member for member in members if not exists(os.path.join(base, member))]
    if missing:
        from openalea.encoding3d.parts import MissingPartError
        raise MissingPartError(missing[0], [base]) if missing[0].startswith("parts/") else \
            FileNotFoundError(f"{os.path.join(base, missing[0])} does not exist")
    temporary = os.fspath(path) + ".part"
    options = {"compresslevel": level} if level is not None and compression == "deflate" else {}
    with zipfile.ZipFile(temporary, "w", compression=COMPRESSIONS[compression], allowZip64=True, **options) as out:
        for member in members:
            source = os.path.join(base, member)
            if split(source) is None:
                out.write(source, member)
            else:
                out.writestr(member, read_bytes(source))
    os.replace(temporary, path)
    return path


def unpack(path: str, folder: str) -> str:
    """The members of the archive *path* written into *folder* (made if needed); the path of its index."""
    from openalea.encoding3d.codec import INDEX_FILE
    os.makedirs(folder, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            member = _member(info.filename)
            if not member or info.is_dir():
                continue
            target = os.path.join(folder, *member.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as out:
                while True:
                    block = source.read(1 << 24)
                    if not block:
                        break
                    out.write(block)
    return os.path.join(folder, INDEX_FILE)
