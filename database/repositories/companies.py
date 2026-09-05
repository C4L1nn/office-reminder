from __future__ import annotations

from dataclasses import dataclass

from database.connection import Database


@dataclass(slots=True, frozen=True)
class CompanyRecord:
    id: int
    name: str
    tax_number: str | None
    is_active: bool
    notes: str | None = None
    created_at: str | None = None


class CompanyRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_active(self) -> list[CompanyRecord]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT id, name, tax_number, is_active, notes, created_at FROM companies "
                "WHERE is_active = 1 ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [
            CompanyRecord(
                id=row["id"],
                name=row["name"],
                tax_number=row["tax_number"],
                is_active=bool(row["is_active"]),
                notes=row["notes"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def list_all(self) -> list[CompanyRecord]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT id, name, tax_number, is_active, notes, created_at FROM companies ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [
            CompanyRecord(
                id=row["id"],
                name=row["name"],
                tax_number=row["tax_number"],
                is_active=bool(row["is_active"]),
                notes=row["notes"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_by_id(self, company_id: int) -> CompanyRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT id, name, tax_number, is_active, notes, created_at FROM companies WHERE id = ?", (company_id,)
            ).fetchone()
        if row is None:
            return None
        return CompanyRecord(
            id=row["id"],
            name=row["name"],
            tax_number=row["tax_number"],
            is_active=bool(row["is_active"]),
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def create(self, name: str, tax_number: str | None = None, notes: str | None = None) -> int:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Şirket adı boş olamaz.")

        with self.database.session() as connection:
            cursor = connection.execute(
                "INSERT INTO companies(name, tax_number, notes) VALUES (?, ?, ?)",
                (clean_name, tax_number.strip() if tax_number and tax_number.strip() else None, notes),
            )
            return int(cursor.lastrowid)

    def update(
        self, company_id: int, *, name: str | None = None, tax_number: str | None = None, notes: str | None = None
    ) -> bool:
        existing = self.get_by_id(company_id)
        if existing is None:
            return False
        new_name = name.strip() if name is not None else existing.name
        if not new_name:
            raise ValueError("Şirket adı boş olamaz.")
        new_tax = tax_number.strip() if tax_number is not None and tax_number.strip() != "" else None
        if tax_number is None:
            new_tax = existing.tax_number
        with self.database.session() as connection:
            cursor = connection.execute(
                "UPDATE companies SET name = ?, tax_number = ?, notes = COALESCE(?, notes), updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_name, new_tax, notes, company_id),
            )
            return cursor.rowcount > 0

    def set_active(self, company_id: int, is_active: bool) -> bool:
        with self.database.session() as connection:
            cursor = connection.execute(
                "UPDATE companies SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if is_active else 0, company_id),
            )
            return cursor.rowcount > 0
