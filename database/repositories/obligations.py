from __future__ import annotations

from dataclasses import dataclass

from database.connection import Database


@dataclass(slots=True, frozen=True)
class ObligationTypeRecord:
    id: int
    code: str
    name: str
    category: str
    source_kind: str  # GIB/SGK/SYSTEM
    schedule_kind: str  # SEEDED/RULE_ENGINE/EVENT_DRIVEN
    description: str | None
    is_active: bool


@dataclass(slots=True, frozen=True)
class CompanyObligationRecord:
    id: int
    company_id: int
    obligation_type_id: int
    code: str
    name: str
    category: str
    source_kind: str
    schedule_kind: str
    is_active: bool
    enabled_from: str | None
    enabled_until: str | None


class ObligationTypeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_all(self, only_active: bool = False) -> list[ObligationTypeRecord]:
        where = "WHERE is_active = 1" if only_active else ""
        with self.database.session() as connection:
            rows = connection.execute(
                f"SELECT id, code, name, category, source_kind, schedule_kind, description, is_active "
                f"FROM obligation_types {where} ORDER BY category, name COLLATE NOCASE"
            ).fetchall()
        return [
            ObligationTypeRecord(
                id=r["id"],
                code=r["code"],
                name=r["name"],
                category=r["category"],
                source_kind=r["source_kind"],
                schedule_kind=r["schedule_kind"],
                description=r["description"],
                is_active=bool(r["is_active"]),
            )
            for r in rows
        ]

    def list_active(self) -> list[ObligationTypeRecord]:
        return self.list_all(only_active=True)

    def get_by_id(self, oid: int) -> ObligationTypeRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT id, code, name, category, source_kind, schedule_kind, description, is_active FROM obligation_types WHERE id = ?",
                (oid,),
            ).fetchone()
        if row is None:
            return None
        return ObligationTypeRecord(
            id=row["id"],
            code=row["code"],
            name=row["name"],
            category=row["category"],
            source_kind=row["source_kind"],
            schedule_kind=row["schedule_kind"],
            description=row["description"],
            is_active=bool(row["is_active"]),
        )

    def get_by_code(self, code: str) -> ObligationTypeRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT id, code, name, category, source_kind, schedule_kind, description, is_active FROM obligation_types WHERE code = ?",
                (code.strip().upper(),),
            ).fetchone()
        if row is None:
            return None
        return ObligationTypeRecord(
            id=row["id"],
            code=row["code"],
            name=row["name"],
            category=row["category"],
            source_kind=row["source_kind"],
            schedule_kind=row["schedule_kind"],
            description=row["description"],
            is_active=bool(row["is_active"]),
        )

    def grouped_by_category(self, only_active: bool = True) -> dict[str, list[ObligationTypeRecord]]:
        all_types = self.list_all(only_active=only_active)
        grouped: dict[str, list[ObligationTypeRecord]] = {}
        for t in all_types:
            grouped.setdefault(t.category, []).append(t)
        return grouped


class CompanyObligationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_for_company(self, company_id: int) -> list[CompanyObligationRecord]:
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT co.id, co.company_id, co.obligation_type_id, co.enabled_from, co.enabled_until, co.is_active,
                       ot.code, ot.name, ot.category, ot.source_kind, ot.schedule_kind
                FROM company_obligations co
                JOIN obligation_types ot ON ot.id = co.obligation_type_id
                WHERE co.company_id = ?
                ORDER BY ot.category, ot.name COLLATE NOCASE
                """,
                (company_id,),
            ).fetchall()
        return [
            CompanyObligationRecord(
                id=r["id"],
                company_id=r["company_id"],
                obligation_type_id=r["obligation_type_id"],
                code=r["code"],
                name=r["name"],
                category=r["category"],
                source_kind=r["source_kind"],
                schedule_kind=r["schedule_kind"],
                is_active=bool(r["is_active"]),
                enabled_from=r["enabled_from"],
                enabled_until=r["enabled_until"],
            )
            for r in rows
        ]

    def list_active_for_company(self, company_id: int) -> list[CompanyObligationRecord]:
        return [r for r in self.list_for_company(company_id) if r.is_active]

    def is_assigned(self, company_id: int, obligation_type_id: int) -> bool:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT 1 FROM company_obligations WHERE company_id = ? AND obligation_type_id = ? AND is_active = 1",
                (company_id, obligation_type_id),
            ).fetchone()
            return row is not None

    def set_for_company(self, company_id: int, obligation_type_ids: list[int]) -> None:
        """Replace company's obligations with given set. Inactive ones are deactivated, new ones activated."""
        # deduplicate
        desired = set(int(x) for x in obligation_type_ids)
        with self.database.session() as connection:
            # validate company exists
            crow = connection.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone()
            if crow is None:
                raise ValueError(f"Şirket bulunamadı: {company_id}")
            # validate obligation ids exist
            if desired:
                placeholders = ",".join("?" for _ in desired)
                rows = connection.execute(
                    f"SELECT id FROM obligation_types WHERE id IN ({placeholders})", tuple(desired)
                ).fetchall()
                found = {r["id"] for r in rows}
                missing = desired - found
                if missing:
                    raise ValueError(f"Yükümlülük türleri bulunamadı: {missing}")

            existing = {
                r["obligation_type_id"]: r["is_active"]
                for r in connection.execute(
                    "SELECT obligation_type_id, is_active FROM company_obligations WHERE company_id = ?", (company_id,)
                ).fetchall()
            }

            # Deactivate those not in desired but existing active
            for ot_id, active in existing.items():
                if ot_id not in desired and active:
                    connection.execute(
                        "UPDATE company_obligations SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE company_id = ? AND obligation_type_id = ?",
                        (company_id, ot_id),
                    )
                elif ot_id in desired and not active:
                    # reactivate
                    connection.execute(
                        "UPDATE company_obligations SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE company_id = ? AND obligation_type_id = ?",
                        (company_id, ot_id),
                    )

            # Insert new ones
            for ot_id in desired:
                if ot_id not in existing:
                    connection.execute(
                        "INSERT INTO company_obligations(company_id, obligation_type_id, is_active) VALUES (?, ?, 1)",
                        (company_id, ot_id),
                    )

    def add(self, company_id: int, obligation_type_id: int) -> int:
        with self.database.session() as connection:
            # upsert reactivate
            row = connection.execute(
                "SELECT id, is_active FROM company_obligations WHERE company_id = ? AND obligation_type_id = ?",
                (company_id, obligation_type_id),
            ).fetchone()
            if row:
                if not row["is_active"]:
                    connection.execute(
                        "UPDATE company_obligations SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (row["id"],),
                    )
                return int(row["id"])
            cursor = connection.execute(
                "INSERT INTO company_obligations(company_id, obligation_type_id) VALUES (?, ?)",
                (company_id, obligation_type_id),
            )
            return int(cursor.lastrowid)

    def remove(self, company_id: int, obligation_type_id: int) -> bool:
        with self.database.session() as connection:
            cursor = connection.execute(
                "UPDATE company_obligations SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE company_id = ? AND obligation_type_id = ? AND is_active = 1",
                (company_id, obligation_type_id),
            )
            return cursor.rowcount > 0

    def replace_profile(
        self,
        company_id: int,
        obligation_type_ids: list[int],
        settings_by_type_id: dict[int, str | None] | None = None,
        enabled_from: str | None = None,
    ) -> None:
        """Atomically replace a company's obligation set AND its per-obligation profile.

        Everything happens in one transaction so a profile can never be written
        before (or without) the company_obligations row it belongs to.

        - obligation_type_ids: the obligations the company is subject to
        - settings_by_type_id: settings_json payload per obligation type id
          (e.g. KDV variants, SGK wage period). Types missing from this map keep
          whatever settings they already had.
        - enabled_from: ISO date stamped on newly activated obligations so official
          events from before the company was onboarded are not reported as overdue.
        """
        desired = {int(x) for x in obligation_type_ids}
        settings_by_type_id = settings_by_type_id or {}

        with self.database.session() as connection:
            if connection.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone() is None:
                raise ValueError(f"Şirket bulunamadı: {company_id}")

            if desired:
                placeholders = ",".join("?" for _ in desired)
                found = {
                    r["id"]
                    for r in connection.execute(
                        f"SELECT id FROM obligation_types WHERE id IN ({placeholders})", tuple(desired)
                    ).fetchall()
                }
                missing = desired - found
                if missing:
                    raise ValueError(f"Yükümlülük türleri bulunamadı: {sorted(missing)}")

            existing = {
                r["obligation_type_id"]: r
                for r in connection.execute(
                    "SELECT obligation_type_id, is_active, enabled_from FROM company_obligations WHERE company_id = ?",
                    (company_id,),
                ).fetchall()
            }

            for ot_id, row in existing.items():
                if ot_id not in desired and row["is_active"]:
                    connection.execute(
                        "UPDATE company_obligations SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
                        "WHERE company_id = ? AND obligation_type_id = ?",
                        (company_id, ot_id),
                    )
                elif ot_id in desired and not row["is_active"]:
                    connection.execute(
                        "UPDATE company_obligations SET is_active = 1, enabled_from = COALESCE(enabled_from, ?), "
                        "updated_at = CURRENT_TIMESTAMP WHERE company_id = ? AND obligation_type_id = ?",
                        (enabled_from, company_id, ot_id),
                    )

            for ot_id in sorted(desired - set(existing)):
                connection.execute(
                    "INSERT INTO company_obligations(company_id, obligation_type_id, is_active, enabled_from) "
                    "VALUES (?, ?, 1, ?)",
                    (company_id, ot_id, enabled_from),
                )

            for ot_id, payload in settings_by_type_id.items():
                if int(ot_id) not in desired:
                    continue
                connection.execute(
                    "UPDATE company_obligations SET settings_json = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE company_id = ? AND obligation_type_id = ?",
                    (payload, company_id, int(ot_id)),
                )

    def get_settings_json(self, company_id: int, obligation_code: str) -> str | None:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT co.settings_json
                FROM company_obligations co
                JOIN obligation_types ot ON ot.id = co.obligation_type_id
                WHERE co.company_id = ? AND ot.code = ? AND co.is_active = 1
                """,
                (company_id, obligation_code),
            ).fetchone()
            return row["settings_json"] if row else None

    def get_assigned_ids(self, company_id: int) -> set[int]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT obligation_type_id FROM company_obligations WHERE company_id = ? AND is_active = 1",
                (company_id,),
            ).fetchall()
            return {r["obligation_type_id"] for r in rows}

    def count_for_company(self, company_id: int) -> int:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT COUNT(*) as c FROM company_obligations WHERE company_id = ? AND is_active = 1", (company_id,)
            ).fetchone()
            return int(row["c"]) if row else 0
