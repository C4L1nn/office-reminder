from __future__ import annotations

from dataclasses import dataclass

from database.connection import Database


@dataclass(slots=True, frozen=True)
class VehicleRecord:
    id: int
    company_id: int
    company_name: str | None
    plate: str
    make: str | None
    model: str | None
    model_year: int | None
    notes: str | None
    is_active: bool


class VehicleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_all(self, company_id: int | None = None, only_active: bool = False) -> list[VehicleRecord]:
        where: list[str] = []
        params: list = []
        if company_id is not None:
            where.append("v.company_id = ?")
            params.append(company_id)
        if only_active:
            where.append("v.is_active = 1")
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        with self.database.session() as connection:
            rows = connection.execute(
                f"""
                SELECT v.id, v.company_id, c.name AS company_name, v.plate, v.make, v.model, v.model_year, v.notes, v.is_active
                FROM vehicles v
                LEFT JOIN companies c ON c.id = v.company_id
                {sql_where}
                ORDER BY c.name COLLATE NOCASE, v.plate COLLATE NOCASE
                """,
                tuple(params),
            ).fetchall()
        return [
            VehicleRecord(
                id=r["id"],
                company_id=r["company_id"],
                company_name=r["company_name"],
                plate=r["plate"],
                make=r["make"],
                model=r["model"],
                model_year=r["model_year"],
                notes=r["notes"],
                is_active=bool(r["is_active"]),
            )
            for r in rows
        ]

    def get_by_id(self, vehicle_id: int) -> VehicleRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT v.id, v.company_id, c.name AS company_name, v.plate, v.make, v.model, v.model_year, v.notes, v.is_active
                FROM vehicles v
                LEFT JOIN companies c ON c.id = v.company_id
                WHERE v.id = ?
                """,
                (vehicle_id,),
            ).fetchone()
        if row is None:
            return None
        return VehicleRecord(
            id=row["id"],
            company_id=row["company_id"],
            company_name=row["company_name"],
            plate=row["plate"],
            make=row["make"],
            model=row["model"],
            model_year=row["model_year"],
            notes=row["notes"],
            is_active=bool(row["is_active"]),
        )

    def get_by_plate(self, plate: str) -> VehicleRecord | None:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT v.id, v.company_id, c.name AS company_name, v.plate, v.make, v.model, v.model_year, v.notes, v.is_active
                FROM vehicles v LEFT JOIN companies c ON c.id=v.company_id WHERE v.plate = ? COLLATE NOCASE
                """,
                (plate.strip(),),
            ).fetchone()
        if row is None:
            return None
        return VehicleRecord(
            id=row["id"],
            company_id=row["company_id"],
            company_name=row["company_name"],
            plate=row["plate"],
            make=row["make"],
            model=row["model"],
            model_year=row["model_year"],
            notes=row["notes"],
            is_active=bool(row["is_active"]),
        )

    def create(
        self,
        *,
        company_id: int,
        plate: str,
        make: str | None = None,
        model: str | None = None,
        model_year: int | None = None,
        notes: str | None = None,
    ) -> int:
        clean_plate = plate.strip().upper()
        if not clean_plate:
            raise ValueError("Plaka boş olamaz.")
        if len(clean_plate) < 4:
            raise ValueError("Plaka çok kısa.")
        # basic Turkish plate validation? Keep simple
        with self.database.session() as connection:
            # company must exist
            crow = connection.execute("SELECT id FROM companies WHERE id = ?", (company_id,)).fetchone()
            if crow is None:
                raise ValueError(f"Şirket bulunamadı: {company_id}")
            # plate unique
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO vehicles(company_id, plate, make, model, model_year, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (company_id, clean_plate, make.strip() if make and make.strip() else None, model.strip() if model and model.strip() else None, model_year, notes),
                )
            except Exception as e:
                if "UNIQUE" in str(e) or "unique" in str(e).lower():
                    raise ValueError(f"Plaka zaten kayıtlı: {clean_plate}") from e
                raise
            return int(cursor.lastrowid)

    def update(
        self,
        vehicle_id: int,
        *,
        plate: str | None = None,
        make: str | None = None,
        model: str | None = None,
        model_year: int | None = None,
        notes: str | None = None,
        company_id: int | None = None,
    ) -> bool:
        existing = self.get_by_id(vehicle_id)
        if existing is None:
            return False
        new_plate = plate.strip().upper() if plate is not None else existing.plate
        if not new_plate:
            raise ValueError("Plaka boş olamaz.")
        new_make = make.strip() if make is not None and make.strip() else existing.make if make is None else None
        new_model = model.strip() if model is not None and model.strip() else existing.model if model is None else None
        new_year = model_year if model_year is not None else existing.model_year
        new_notes = notes if notes is not None else existing.notes
        new_company = company_id if company_id is not None else existing.company_id

        with self.database.session() as connection:
            if company_id is not None:
                crow = connection.execute("SELECT id FROM companies WHERE id = ?", (new_company,)).fetchone()
                if crow is None:
                    raise ValueError(f"Şirket bulunamadı: {new_company}")
            try:
                cursor = connection.execute(
                    """
                    UPDATE vehicles SET plate=?, make=?, model=?, model_year=?, notes=?, company_id=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (new_plate, new_make, new_model, new_year, new_notes, new_company, vehicle_id),
                )
            except Exception as e:
                if "UNIQUE" in str(e):
                    raise ValueError(f"Plaka zaten kayıtlı: {new_plate}") from e
                raise
            return cursor.rowcount > 0

    def set_active(self, vehicle_id: int, is_active: bool) -> bool:
        with self.database.session() as connection:
            cursor = connection.execute(
                "UPDATE vehicles SET is_active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (1 if is_active else 0, vehicle_id)
            )
            return cursor.rowcount > 0

    def delete(self, vehicle_id: int) -> bool:
        with self.database.session() as connection:
            cursor = connection.execute("DELETE FROM vehicles WHERE id=?", (vehicle_id,))
            return cursor.rowcount > 0
