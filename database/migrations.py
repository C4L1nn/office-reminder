from __future__ import annotations

import re
from pathlib import Path

from database.connection import Database

# A migration file may legitimately contain PRAGMA statements, but PRAGMAs that
# change persistent settings are no-ops (or errors) inside a transaction. We run
# every migration inside an explicit transaction so a failure never leaves the
# schema half-applied, so those lines are stripped from the executed script.
_PRAGMA_LINE = re.compile(r"^\s*PRAGMA\s+[^;]*;\s*$", re.IGNORECASE | re.MULTILINE)


class MigrationError(RuntimeError):
    def __init__(self, name: str, original: Exception) -> None:
        super().__init__(f"Migration '{name}' başarısız: {original}")
        self.name = name
        self.original = original


class MigrationRunner:
    """Applies pending .sql migrations, each one atomically.

    `sqlite3.executescript` commits any pending transaction and then runs the
    script in autocommit mode, so a script that fails halfway would otherwise
    leave its earlier statements committed while `applied_migrations` stays
    empty — the next start would replay it and crash on e.g. a duplicate
    ALTER TABLE. Wrapping each script plus its bookkeeping row in one explicit
    transaction makes a migration all-or-nothing and the runner idempotent.
    """

    def __init__(self, database: Database, migrations_dir: Path) -> None:
        self.database = database
        self.migrations_dir = Path(migrations_dir)

    def pending(self) -> list[Path]:
        with self.database.session() as connection:
            self._ensure_table(connection)
            existing = {row["name"] for row in connection.execute("SELECT name FROM applied_migrations")}
        return [p for p in sorted(self.migrations_dir.glob("*.sql")) if p.name not in existing]

    def run(self) -> list[str]:
        if not self.migrations_dir.exists():
            raise FileNotFoundError(f"Migration klasörü bulunamadı: {self.migrations_dir}")

        applied: list[str] = []
        connection = self.database.connect()
        try:
            self._ensure_table(connection)
            connection.commit()

            existing = {row["name"] for row in connection.execute("SELECT name FROM applied_migrations")}

            for path in sorted(self.migrations_dir.glob("*.sql")):
                if path.name in existing:
                    continue
                script = _PRAGMA_LINE.sub("", path.read_text(encoding="utf-8"))
                try:
                    connection.executescript(
                        "BEGIN;\n"
                        f"{script}\n"
                        "INSERT INTO applied_migrations(name) VALUES ("
                        f"{_sql_literal(path.name)});\n"
                        "COMMIT;"
                    )
                except Exception as exc:  # noqa: BLE001 - re-raised as MigrationError
                    try:
                        connection.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise MigrationError(path.name, exc) from exc
                applied.append(path.name)
        finally:
            connection.close()

        return applied

    @staticmethod
    def _ensure_table(connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applied_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
