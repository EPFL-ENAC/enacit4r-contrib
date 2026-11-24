"""Read a browser upload (loose files, .zip, .tar.gz) into a Bundle.

Threat model: the upload is untrusted, and its paths become paths in a git commit.
"""

import fnmatch
import io
import tarfile
import zipfile
import zlib
from collections.abc import Iterator
from typing import IO

from enacit4r_contrib.issues import Issue
from enacit4r_contrib.pipeline import Bundle

JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
ARCHIVE_ERRORS = (
    zipfile.BadZipFile,
    tarfile.TarError,
    zlib.error,
    OSError,
    EOFError,
    RuntimeError,  # encrypted or unsupported zip member
)


class BundleError(Exception):
    """The whole upload is refused; str(e) is shown to the user."""


def read_upload(
    items: list[tuple[str, bytes]],
    *,
    allow: list[str],
    skip: list[str] = (),
    max_files: int = 500,
    max_file_bytes: int = 50 * 2**20,
    max_total_bytes: int = 200 * 2**20,
    ignore_case: bool = False,
    unexpected: str = "Unexpected file: not part of the template",
) -> tuple[Bundle, list[Issue]]:
    """ignore_case=True: `allow` and `skip` globs match in any case (`*.ply`
    matches `X.PLY`). The bundle keeps the original case of each path."""

    def matches(path: str, globs) -> bool:
        if ignore_case:
            path, globs = path.lower(), [g.lower() for g in globs]
        return any(fnmatch.fnmatchcase(path, glob) for glob in globs)

    files: list[tuple[str, bytes]] = []
    total = 0
    for source, name, stream in _entries(items):
        path = _safe_path(name)
        segments = path.split("/")
        if "__MACOSX" in segments or _is_junk(segments[-1]):
            continue
        if len(files) >= max_files:
            raise BundleError(f"Too many files (max {max_files})")
        # Read one byte past each cap so an oversized file is detected without
        # reading it all, whatever size the archive declares.
        limit = min(max_file_bytes, max_total_bytes - total) + 1
        try:
            data = stream.read(limit)
        except ARCHIVE_ERRORS:
            raise BundleError(f"Could not read archive {source}") from None
        if len(data) > max_file_bytes:
            raise BundleError(f"File too large: {path} (max {max_file_bytes} bytes)")
        total += len(data)
        if total > max_total_bytes:
            raise BundleError(f"Upload too large (max {max_total_bytes} bytes)")
        files.append((path, data))

    files = _strip_top_folder(files)
    bundle: Bundle = {}
    issues: list[Issue] = []
    seen: set[str] = set()
    for path, data in files:
        if path in seen:
            issues.append(Issue("Duplicate file", file=path))
        elif matches(path, skip):
            issues.append(
                Issue(
                    "Skipped: this upload does not take this file",
                    file=path,
                    severity="warning",
                )
            )
        elif not matches(path, allow):
            issues.append(Issue(unexpected, file=path))
        else:
            bundle[path] = data
        seen.add(path)
    if not bundle:
        issues.append(Issue("No files to submit"))
    return bundle, issues


def _entries(
    items: list[tuple[str, bytes]],
) -> Iterator[tuple[str, str, IO[bytes]]]:
    """Yield (item name, file path, stream) for each file, archives expanded."""
    for name, data in items:
        lower = name.lower()
        if lower.endswith(".zip"):
            reader = _zip_entries
        elif lower.endswith((".tar.gz", ".tgz")):
            reader = _tar_entries
        else:
            yield name, name, io.BytesIO(data)
            continue
        try:
            for path, stream in reader(data):
                yield name, path, stream
        except ARCHIVE_ERRORS:
            raise BundleError(f"Could not read archive {name}") from None


def _zip_entries(data: bytes) -> Iterator[tuple[str, IO[bytes]]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if not info.is_dir():
                with zf.open(info) as member:
                    yield info.filename, member


def _tar_entries(data: bytes) -> Iterator[tuple[str, IO[bytes]]]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for info in tf:
            member = tf.extractfile(info) if info.isreg() else None
            if member is not None:
                yield info.name, member


def _safe_path(name: str) -> str:
    path = name.removeprefix("./")
    if (
        path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(seg in ("", ".", "..") for seg in path.split("/"))
    ):
        raise BundleError(f"Unsafe path: {name!r}")
    return path


def _is_junk(basename: str) -> bool:
    return basename in JUNK_NAMES or basename.startswith("._")


def _strip_top_folder(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    parts = [path.split("/", 1) for path, _ in files]
    tops = {p[0] for p in parts}
    if not files or len(tops) != 1 or any(len(p) < 2 for p in parts):
        return files
    return [(p[1], data) for p, (_, data) in zip(parts, files, strict=True)]
