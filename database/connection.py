from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    #: Paths whose journal mode this process has already set. WAL is recorded
    #: in the database header and survives every later connection, so asking
    #: for it again on each connect costs ~10 ms for nothing — measured, and
    #: it was most of the cost of opening a connection.
    _wal_ready: set[str] = set()

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        # Per-connection settings: these do not persist in the file.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")

        key = str(self.path.resolve())
        if key not in Database._wal_ready:
            connection.execute("PRAGMA journal_mode = WAL")
            Database._wal_ready.add(key)
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
