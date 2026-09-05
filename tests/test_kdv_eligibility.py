from datetime import date
from pathlib import Path

import pytest

from database.connection import Database
from database.migrations import MigrationRunner
from services.company_service import CompanyService
from services.official_calendar_service import OfficialCalendarSeedService
from services.reminder_service import ReminderService
from services.eligibility_service import EligibilityService


@pytest.fixture()
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "kdv.db")
    migrations = Path(__file__).resolve().parents[1] / "database" / "migrations"
    MigrationRunner(db, migrations).run()
    seed_dir = Path(__file__).resolve().parents[1] / "resources" / "seed"
    OfficialCalendarSeedService(db, seed_dir).import_seed("official_calendar_2026.json")
    return db


def test_kdv_distinct_eligibility_tags(database: Database) -> None:
    # Verify KDV has 3 distinct eligibility tag combinations as per real GIB
    with database.session() as conn:
        rows = conn.execute(
            "SELECT eligibility_tags, COUNT(*) as c FROM official_calendar_events WHERE obligation_type_id=(SELECT id FROM obligation_types WHERE code='GIB_KDV') GROUP BY eligibility_tags"
        ).fetchall()
        tags = {r["eligibility_tags"]: r["c"] for r in rows}
        print(tags)
        # Should have 3 variants
        assert len(tags) == 3
        # Check counts
        # Find which tag corresponds to which
        for tag_json, cnt in tags.items():
            import json
            tags_list = json.loads(tag_json) if tag_json else []
            assert len(tags_list) == 1
            tag = tags_list[0]
            if tag == "KDV_STANDARD_MONTHLY":
                assert cnt == 12
            elif tag == "KDV_STANDARD_QUARTERLY":
                assert cnt == 4
            elif tag == "KDV_TEVKIFAT":
                assert cnt == 13
            else:
                assert False, f"Unexpected KDV tag {tag}"


def test_kdv_company_profile_projection(database: Database) -> None:
    cs = CompanyService(database)
    rs = ReminderService(database)
    cid = cs.create("KdvCo")
    kdv_type = next(t for t in cs.list_obligation_types() if t.code == "GIB_KDV")
    cs.set_company_obligations(cid, [kdv_type.id])
    # Without profile, should see 0 KDV (fail-safe)
    due_no_profile = rs.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=cid)
    kdv_no = [d for d in due_no_profile if "Katma" in d.title]
    assert len(kdv_no) == 0, "Without KDV profile, should see 0 (needs_profile)"

    # Check needs_profile reporting
    elig = EligibilityService(database)
    needs = elig.get_needs_profile_events(cid, "GIB_KDV")
    assert len(needs) == 29  # all KDV events need profile

    # Set profile to only STANDARD_MONTHLY
    with database.session() as conn:
        conn.execute(
            "UPDATE company_obligations SET settings_json = ? WHERE company_id = ? AND obligation_type_id = ?",
            ('{"kdv_variants": ["KDV_STANDARD_MONTHLY"]}', cid, kdv_type.id),
        )
    due_monthly = rs.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=cid)
    kdv_monthly = [d for d in due_monthly if "Katma" in d.title]
    # Should see only monthly standard (12), not quarterly nor tevkifat
    assert len(kdv_monthly) == 12
    assert all("Tevkifat" not in d.title for d in kdv_monthly)

    # Set profile to include tevkifat as well
    with database.session() as conn:
        conn.execute(
            "UPDATE company_obligations SET settings_json = ? WHERE company_id = ? AND obligation_type_id = ?",
            ('{"kdv_variants": ["KDV_STANDARD_MONTHLY", "KDV_TEVKIFAT"]}', cid, kdv_type.id),
        )
    due_both = rs.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=cid)
    kdv_both = [d for d in due_both if "Katma" in d.title]
    assert len(kdv_both) == 25  # 12 monthly +13 tevkifat

    # Set to quarterly only
    with database.session() as conn:
        conn.execute(
            "UPDATE company_obligations SET settings_json = ? WHERE company_id = ? AND obligation_type_id = ?",
            ('{"kdv_variants": ["KDV_STANDARD_QUARTERLY"]}', cid, kdv_type.id),
        )
    due_quarterly = rs.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=cid)
    kdv_q = [d for d in due_quarterly if "Katma" in d.title]
    assert len(kdv_q) == 4


def test_kdv_eligibility_generic(database: Database) -> None:
    # Test that non-KDV obligations with no tags still show without profile
    cs = CompanyService(database)
    rs = ReminderService(database)
    cid = cs.create("DamgaCo")
    damga_type = next(t for t in cs.list_obligation_types() if t.code == "GIB_DAMGA")
    cs.set_company_obligations(cid, [damga_type.id])
    # Damga has no required profile (eligibility_tags is ["GIB_DAMGA"] but not in PROFILE_REQUIRED? Actually GIB_DAMGA is not in PROFILE_REQUIRED, so should show without profile
    due = rs.list_due(horizon_days=400, today=date(2026, 1, 1), company_id=cid)
    damga_due = [d for d in due if "Damga" in d.title]
    # Damga has 24 events in 2026, horizon 400 should include many
    assert len(damga_due) >= 10
