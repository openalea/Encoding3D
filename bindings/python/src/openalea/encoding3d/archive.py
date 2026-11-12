"""
A sequence as one file: a `.fspm.zip` holding the folder's layout (specification §8.2), every member an unchanged
file of it (scene.fspm.json, views.json, frame_*.glb, parts/<key>.glb), compressed member by member, so that each one
is read alone::

    pack(folder, path, compression="deflate", keep_folder=False)
                                                   the sequence of *folder* (or of its scene.fspm.json) as a ZIP64
                                                   archive, checked (check_archive), then the folder removed
    check_archive(path, folder)                    every file of the folder's sequence a member of the archive, of
                                                   the same size and CRC-32 read back, and the archive valid
    unpack(path, folder)                           the archive's members back as a folder; its index's path

A file inside an archive has the path "<archive>.fspm.zip/<member>" (e.g. run.fspm.zip/frame_000003.glb): read,
read_index, read_sequence, validate_file and ParaView's reader take such paths, and the archive itself, as they take
the folder's. read_bytes, exists and listing are the file access the codec uses for both.
"""
import os
import shutil
import zipfile
import zlib

ARCHIVE_SUFFIX = ".fspm.zip"
COMPRESSIONS = {"deflate": zipfile.ZIP_DEFLATED, "lzma": zipfile.ZIP_LZMA, "stored": zipfile.ZIP_STORED}
DEFAULT_COMPRESSION = "deflate"
_OPEN = {}                      # {archive path: (its modification time and size, the open ZipFile)}
_KEPT_OPEN = 4
_BLOCK = 1 << 24


class ArchiveCheckError(ValueError):
    """An archive that does not hold its folder's sequence as it is (a member missing, of another size or CRC-32, or
    unreadable; the archive not valid), or a folder pack would not remove whole: pack keeps the folder."""


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


def _forget(archive: str) -> None:
    """The archive *archive* no longer kept open (written again, moved or removed)."""
    found = _OPEN.pop(archive, None)
    if found is not None:
        found[1].close()


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


def _folder_files(folder: str) -> list:
    """Every file under *folder*, relative to it, with "/" separators."""
    found = []
    for root, _, names in os.walk(folder):
        for name in names:
            found.append(os.path.relpath(os.path.join(root, name), folder).replace(os.sep, "/"))
    return sorted(found)


def _crc_and_size(blocks) -> tuple:
    crc, size = 0, 0
    for block in blocks:
        crc, size = zlib.crc32(block, crc), size + len(block)
    return crc, size


def _file_blocks(path: str):
    if split(path) is not None:
        yield read_bytes(path)
        return
    with open(path, "rb") as file:
        while True:
            block = file.read(_BLOCK)
            if not block:
                return
            yield block


def _member_blocks(opened: zipfile.ZipFile, info: zipfile.ZipInfo):
    with opened.open(info) as source:
        while True:
            block = source.read(_BLOCK)
            if not block:
                return
            yield block


def check_archive(path: str, folder: str) -> None:
    """Check that the archive *path* holds the sequence of *folder* (a folder, or its scene.fspm.json) as it is:
    each of its files a member, and nothing else, of the same size and CRC-32, every member read back (decompressed,
    its CRC-32 computed again); then that the archive passes the validator with no error. ArchiveCheckError when it
    does not."""
    from openalea.encoding3d.validate import validate_sequence
    index_path = index_of(folder)
    base = os.path.dirname(os.path.abspath(index_path))
    members = sequence_members(index_path)
    _forget(path)
    try:
        with zipfile.ZipFile(path) as opened:
            names = opened.namelist()
            if sorted(names) != sorted(members):
                missing, unexpected = sorted(set(members) - set(names)), sorted(set(names) - set(members))
                raise ArchiveCheckError(f"{path}: members differ from the sequence's files of {base} (missing "
                                        f"{missing[:3]}, not of the sequence {unexpected[:3]})")
            for member in members:
                info = opened.getinfo(member)
                crc, size = _crc_and_size(_file_blocks(os.path.join(base, member)))
                if (info.file_size, info.CRC) != (size, crc):
                    raise ArchiveCheckError(f"{path}: member {member} of {info.file_size} bytes, CRC-32 "
                                            f"{info.CRC:08x}; its file {size} bytes, {crc:08x}")
                if _crc_and_size(_member_blocks(opened, info)) != (crc, size):
                    raise ArchiveCheckError(f"{path}: member {member} reads back differently from its file")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, EOFError, OSError, ValueError) as error:
        if isinstance(error, ArchiveCheckError):
            raise
        raise ArchiveCheckError(f"{path}: cannot be read back: {type(error).__name__}: {error}") from error
    report = validate_sequence(path)
    _forget(path)
    if not report.ok:
        raise ArchiveCheckError(f"{path}: {len(report.errors)} validation error(s), e.g. "
                                + "; ".join(str(issue) for issue in report.errors[:3]))


def pack(folder: str, path: str, compression: str = DEFAULT_COMPRESSION, level: int = None,
         keep_folder: bool = False) -> str:
    """The sequence of *folder* (a folder, or its scene.fspm.json) packed into the ZIP64 archive *path*
    (x.fspm.zip): the index, views.json, the frames and the parts they refer to, unchanged, each compressed alone
    (*compression*: "deflate", "lzma" or "stored"; *level*: deflate's 0-9). Written next to *path* first, checked
    (check_archive: every file a member, its size and CRC-32 read back, the archive valid), then moved into place;
    then the folder removed, unless *keep_folder*. A folder holding files the sequence does not (encoding3d prune
    removes the parts no frame uses) is not removed: ArchiveCheckError before anything is written. When the check
    fails, nothing is moved to *path*, the folder is kept and ArchiveCheckError is raised. A sequence read from an
    archive is packed again, nothing removed. Returns *path*."""
    if compression not in COMPRESSIONS:
        raise ValueError(f"compression '{compression}': one of {sorted(COMPRESSIONS)}")
    path = os.fspath(path)
    if not path.endswith(ARCHIVE_SUFFIX):
        raise ValueError(f"'{path}': an archive's name ends in {ARCHIVE_SUFFIX}")
    index_path = index_of(folder)
    base = os.path.dirname(os.path.abspath(index_path))
    members = sequence_members(index_path)
    missing = [member for member in members if not exists(os.path.join(base, member))]
    if missing:
        from openalea.encoding3d.parts import MissingPartError
        raise MissingPartError(missing[0], [base]) if missing[0].startswith("parts/") else \
            FileNotFoundError(f"{os.path.join(base, missing[0])} does not exist")
    removed = not keep_folder and split(index_path) is None
    if removed:
        if os.path.commonpath([base, os.path.abspath(path)]) == base:
            raise ValueError(f"'{path}' is inside the folder {base}, which pack removes: put the archive elsewhere, "
                             "or pack(keep_folder=True)")
        others = sorted(set(_folder_files(base)) - set(members))
        if others:
            raise ArchiveCheckError(f"{base} holds {len(others)} file(s) that are not its sequence's, e.g. "
                                    f"{others[:3]} (encoding3d prune removes the parts no frame uses): the folder "
                                    "would not be removed whole; remove them, or pack(keep_folder=True)")
    temporary = path[:-len(ARCHIVE_SUFFIX)] + ".part" + ARCHIVE_SUFFIX
    try:
        _write(base, members, temporary, compression, level)
        check_archive(temporary, index_path)
    except BaseException:
        _forget(temporary)
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    _forget(path)
    os.replace(temporary, path)
    if removed:
        shutil.rmtree(base)
    return path


def _write(base: str, members: list, path: str, compression: str, level: int) -> None:
    """The archive *path* of the files *members* of *base*, each compressed alone."""
    options = {"compresslevel": level} if level is not None and compression == "deflate" else {}
    with zipfile.ZipFile(path, "w", compression=COMPRESSIONS[compression], allowZip64=True, **options) as out:
        for member in members:
            source = os.path.join(base, member)
            if split(source) is None:
                out.write(source, member)
            else:
                out.writestr(member, read_bytes(source))


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
                    block = source.read(_BLOCK)
                    if not block:
                        break
                    out.write(block)
    return os.path.join(folder, INDEX_FILE)
