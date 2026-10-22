import hashlib
import os
import re
import shutil
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from backend_app.integrations.import_files.errors import ImportFileError

MAX_SOURCE_BYTES = 10 * 1024 * 1024
_KEY = re.compile(r"[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*")


@dataclass(frozen=True)
class StoredObject:
    key: str
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class StorageEntry:
    key: str
    modified_at: float


class LocalImportStorage:
    """Immutable private objects, atomically published without replacing an existing key."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise ValueError("Import storage root must not contain symbolic links")
        os.chmod(self.root, 0o700)

    def path(self, key: str) -> Path:
        if not _KEY.fullmatch(key) or any(p in {".", ".."} for p in key.split("/")):
            raise ImportFileError()
        target = self.root / key
        if target.resolve().is_relative_to(self.root) is False:
            raise ImportFileError()
        for parent in (target, *target.parents):
            if parent == self.root:
                break
            if parent.is_symlink():
                raise ImportFileError()
        return target

    def write(
        self,
        key: str,
        source: BinaryIO | Iterable[bytes],
        *,
        max_bytes: int = MAX_SOURCE_BYTES,
    ) -> StoredObject:
        if max_bytes < 1:
            raise ValueError("Invalid file bound")
        target = self.path(key)
        digest = hashlib.sha256()
        size = 0
        temporary: Path | None = None
        try:
            if shutil.disk_usage(self.root).free < max_bytes:
                raise ImportFileError()
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=target.parent, prefix=".pending-", delete=False) as output:
                temporary = Path(output.name)
                os.fchmod(output.fileno(), 0o600)
                chunks = (
                    iter(lambda: source.read(64 * 1024), b"")
                    if hasattr(source, "read")
                    else iter(source)
                )
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise ImportFileError()
                    size += len(chunk)
                    if size > max_bytes:
                        raise ImportFileError("import.file_too_large")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            stored = StoredObject(key, digest.hexdigest(), size)
            try:
                # Hard-link publication is atomic and fails instead of overwriting a winner.
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError:
                self.verify(key, expected_sha256=stored.sha256, expected_size=size)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return stored
        except OSError:
            raise ImportFileError() from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # A bounded orphan scan can retry removal of the unreferenced private object.
                    pass

    def verify(
        self,
        key: str,
        *,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
    ) -> StoredObject:
        digest = hashlib.sha256()
        size = 0
        with self.open(key) as source:
            for chunk in iter(lambda: source.read(64 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        if (expected_size is not None and size != expected_size) or (
            expected_sha256 is not None and digest.hexdigest() != expected_sha256
        ):
            raise ImportFileError()
        return StoredObject(key, digest.hexdigest(), size)

    @contextmanager
    def open(self, key: str) -> Iterator[BinaryIO]:
        try:
            descriptor = os.open(self.path(key), os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as source:
                yield source
        except OSError as error:
            raise ImportFileError() from error

    def delete(self, key: str) -> None:
        try:
            self.path(key).unlink(missing_ok=True)
        except OSError:
            raise ImportFileError() from None

    def list_objects(
        self, *, limit: int = 1000, after_key: str | None = None
    ) -> tuple[StorageEntry, ...]:
        if not 1 <= limit <= 10000:
            raise ValueError("Invalid scan bound")
        entries: list[StorageEntry] = []
        for root, directories, files in os.walk(self.root, followlinks=False):
            directories[:] = sorted(d for d in directories if not (Path(root) / d).is_symlink())
            for name in sorted(files):
                path = Path(root) / name
                key = str(path.relative_to(self.root))
                if not path.is_symlink() and (after_key is None or key > after_key):
                    try:
                        entries.append(StorageEntry(key, path.stat().st_mtime))
                    except FileNotFoundError:
                        continue
                    # Retain only one bounded page while traversing a large private directory.
                    entries.sort(key=lambda entry: entry.key)
                    if len(entries) > limit:
                        entries.pop()
        return tuple(entries)

    def iter_objects(self) -> Generator[StorageEntry]:
        """Stream a scan without materializing directory contents; restart after exhaustion."""
        yield from self._walk_objects(self.root)

    def _walk_objects(self, directory: Path) -> Generator[StorageEntry]:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        yield from self._walk_objects(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        yield StorageEntry(
                            str(Path(entry.path).relative_to(self.root)),
                            entry.stat(follow_symlinks=False).st_mtime,
                        )
                except FileNotFoundError:
                    # Another idempotent cleaner may already have removed this entry.
                    continue


def safe_download_name(name: str, *, default: str = "import.csv") -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f/\\\";]", "_", name).strip(". ")
    return cleaned[:200] or default


def safe_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text
