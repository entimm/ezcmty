from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TextIO

from devtools.seed.config import SeedError

COLUMNS = ("所属批次", "场景", "登录端", "登录名", "显示名称", "密码", "所属物业公司")


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise SeedError("上下文目录不能是符号链接")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, writer: Callable[[TextIO], None]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def save_json(path: Path, value: Any) -> None:
    atomic_write(path, lambda stream: json.dump(value, stream, ensure_ascii=False, indent=2))


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SeedError("该批次或初始化过程正在执行") from None
        yield
    finally:
        os.close(fd)


def run_directory(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{24}", run_id):
        raise SeedError("批次标识格式无效")
    return root / run_id


class State:
    """Durable local intents, results and credentials; never a business database."""

    def __init__(self, directory: Path, *, create: bool = False, initialize: bool = False):
        self.directory = directory
        self.run_id = directory.name
        path = directory / "context.sqlite3"
        if path.is_symlink():
            raise SeedError("上下文文件不能是符号链接")
        if create:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        elif not path.is_file():
            raise SeedError("缺少批次上下文，不能续跑")
        path.chmod(0o600)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA synchronous=FULL")
        if create or initialize:
            self.db.executescript("""
                BEGIN;
                CREATE TABLE IF NOT EXISTS steps (
                    key TEXT PRIMARY KEY, spec TEXT NOT NULL, data TEXT NOT NULL,
                    result TEXT
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    scope TEXT NOT NULL, login TEXT NOT NULL, info TEXT NOT NULL,
                    PRIMARY KEY (scope, login)
                );
                CREATE TABLE IF NOT EXISTS markers (key TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS artifacts (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entities (
                    model TEXT NOT NULL, id TEXT NOT NULL, expected TEXT NOT NULL,
                    PRIMARY KEY (model,id)
                );
                COMMIT;
            """)
            sync_directory(directory)
        if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise SeedError("上下文损坏，不能续跑")

    def close(self) -> None:
        self.db.close()

    def prepare(
        self,
        key: str,
        spec: dict[str, Any],
        factory: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
        encoded = json.dumps(spec, sort_keys=True)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT spec, data, result FROM steps WHERE key=?", (key,)
            ).fetchone()
            if row:
                if row[0] != encoded:
                    raise SeedError(f"步骤定义发生变化：{key}")
                return json.loads(row[1]), json.loads(row[2]) if row[2] else None, True
            data = factory()
            self.db.execute(
                "INSERT INTO steps(key,spec,data) VALUES (?,?,?)", (key, encoded, json.dumps(data))
            )
            return data, None, False

    def complete(
        self, key: str, result: dict[str, Any], account: dict[str, str] | None = None
    ) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE steps SET result=? WHERE key=?", (json.dumps(result), key))
            if result.get("model") and result.get("id"):
                row = self.db.execute(
                    "SELECT expected FROM entities WHERE model=? AND id=?",
                    (result["model"], result["id"]),
                ).fetchone()
                expected = json.loads(row[0]) if row else {}
                expected.update(result.get("expected", {}))
                self.db.execute(
                    "INSERT INTO entities VALUES (?,?,?) ON CONFLICT(model,id) "
                    "DO UPDATE SET expected=excluded.expected",
                    (result["model"], result["id"], json.dumps(expected)),
                )
            if account is not None:
                self.db.execute(
                    "INSERT INTO accounts(scope,login,info) VALUES (?,?,?) "
                    "ON CONFLICT(scope,login) DO UPDATE SET info=excluded.info",
                    (account["登录端"], account["登录名"], json.dumps(account, ensure_ascii=False)),
                )

    def account(self, scope: str, login: str) -> dict[str, str]:
        with self.lock:
            row = self.db.execute(
                "SELECT info FROM accounts WHERE scope=? AND login=?", (scope, login)
            ).fetchone()
        if not row:
            raise SeedError("账号凭据尚未确认")
        return dict(json.loads(row[0]))

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO artifacts VALUES (?,?)", (key, json.dumps(value))
            )

    def get(self, key: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT value FROM artifacts WHERE key=?", (key,)).fetchone()
        return dict(json.loads(row[0])) if row else None

    def mark(self, key: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO markers VALUES (?)", (key,))

    def marked(self, key: str) -> bool:
        with self.lock:
            return (
                self.db.execute("SELECT 1 FROM markers WHERE key=?", (key,)).fetchone() is not None
            )

    def pending(self) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
        cursor = self.db.execute(
            "SELECT key,spec,data FROM steps WHERE result IS NULL ORDER BY rowid"
        )
        for key, spec, data in cursor:
            yield key, json.loads(spec), json.loads(data)

    def entities(self) -> Iterator[tuple[str, str, dict[str, Any]]]:
        last = 0
        while True:
            rows = self.db.execute(
                "SELECT rowid,model,id,expected FROM entities WHERE rowid>? "
                "ORDER BY rowid LIMIT 256",
                (last,),
            ).fetchall()
            if not rows:
                return
            for sequence, model, identifier, expected in rows:
                yield model, identifier, json.loads(expected)
                last = sequence

    def count(self) -> int:
        with self.lock:
            return int(
                self.db.execute("SELECT count(*) FROM steps WHERE result IS NOT NULL").fetchone()[0]
            )

    def export(self) -> None:
        # Export after workers stop. Both files are derived from confirmed credentials.
        def rows() -> Iterator[dict[str, str]]:
            for (info,) in self.db.execute("SELECT info FROM accounts ORDER BY scope,login"):
                yield dict(json.loads(info))

        def write_json(stream: TextIO) -> None:
            stream.write("[\n")
            for index, row in enumerate(rows()):
                if index:
                    stream.write(",\n")
                json.dump(row, stream, ensure_ascii=False)
            stream.write("\n]\n")

        def write_markdown(stream: TextIO) -> None:
            stream.write("| " + " | ".join(COLUMNS) + " |\n")
            stream.write("| " + " | ".join("---" for _ in COLUMNS) + " |\n")
            for row in rows():
                cells = [row[key].replace("|", "\\|").replace("\n", " ") for key in COLUMNS]
                stream.write("| " + " | ".join(cells) + " |\n")

        atomic_write(self.directory / "accounts.json", write_json)
        atomic_write(self.directory / "accounts.md", write_markdown)
