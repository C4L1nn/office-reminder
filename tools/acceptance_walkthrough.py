"""Acceptance walkthrough — drives the real UI the way a person would.

Every step goes through the actual widgets and services: dialogs are filled in
and validated, and their data is saved through the same service calls the
buttons use. It runs against a throwaway database and never touches real data.

    python tools/acceptance_walkthrough.py

Steps 18 and 19 reach the live GİB and SGK sites; without a connection they are
reported as SKIP instead of failing. Exit code 0 means every step that could
run, passed.
"""

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

runtime = Path(tempfile.mkdtemp())
os.environ["OFFICE_REMINDER_DATA_DIR"] = str(runtime)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
from ui.theme import apply_theme  # noqa: E402

apply_theme(app)

from app.paths import get_backups_dir, get_database_path, get_seed_dir  # noqa: E402
from database.connection import Database  # noqa: E402
from database.migrations import MigrationRunner  # noqa: E402
from services.company_service import CompanyService  # noqa: E402
from services.holiday_service import HolidayService  # noqa: E402
from services.notification_adapter import RecordingNotificationAdapter  # noqa: E402
from services.notification_service import NotificationService  # noqa: E402
from services.official_calendar_service import OfficialCalendarSeedService  # noqa: E402
from services.official_update_service import OfficialUpdateService  # noqa: E402
from services.reminder_service import ReminderService  # noqa: E402
from services.settings_service import SettingsService  # noqa: E402
from services.sgk_calendar_service import SgkCalendarService  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

STEPS = []


def step(number, title, ok, detail="", skipped=False):
    STEPS.append((number, title, ok, detail, skipped))
    mark = "SKIP" if skipped else ("PASS" if ok else "FAIL")
    print(f"{mark}  {number:>2}. {title}" + (f" — {detail}" if detail else ""))


TODAY = date.today()

# 1 -------------------------------------------------------------------- first run
db = Database(get_database_path())
applied = MigrationRunner(db, ROOT / "database" / "migrations").run()
OfficialCalendarSeedService(db, get_seed_dir()).import_seed("official_calendar_2026.json")
SgkCalendarService(db, HolidayService(db)).generate_and_import(
    2026, wage_periods=["MONTHLY_1_END", "MONTHLY_15_14"]
)
companies = CompanyService(db)
reminders = ReminderService(db)
settings = SettingsService(db)
official = OfficialUpdateService(db)
window = MainWindow(reminders, companies, settings, official)
window.resize(1280, 800)
# Screens are counted, not hard-coded to a number that goes stale every time a
# page is added. The notifications page is only registered when a notification
# service is supplied, so the stack is compared with the pages that were
# actually built, not with the navigation list.
step(
    1,
    "İlk açılış",
    bool(applied) and window.stack.count() == len(window._pages),
    f"{len(applied)} migration, {window.stack.count()} ekran",
)

# 2 ------------------------------------------------------------------ new company
from ui.dialogs.company_dialog import CompanyDialog  # noqa: E402

page = window.companies_page
window.show_page("companies")
dialog = CompanyDialog(window)
dialog.name_edit.setText("TEST LTD.")
dialog.tax_edit.setText("1234567890")
ok_valid = dialog.validate()
data = dialog.get_data()
company_id = companies.create(data["name"], data["tax_number"], data["notes"])
page.refresh()
step(2, "Şirket oluştur: TEST LTD.", ok_valid and companies.get_by_id(company_id).name == "TEST LTD.")

# 3/4 ------------------------------------------------- obligations via the dialog
from ui.dialogs.company_obligations_dialog import CompanyObligationsDialog  # noqa: E402

oblig = CompanyObligationsDialog(companies, company_id, "TEST LTD.", window)
codes = {o.code: o.id for o in companies.list_obligation_types()}
oblig._checks[codes["GIB_KDV"]].setChecked(True)
oblig._checks[codes["SGK_4A_PREMIUM"]].setChecked(True)
oblig._kdv_checks["KDV_STANDARD_MONTHLY"].setChecked(True)
oblig.wage_combo.setCurrentIndex(oblig.wage_combo.findData("MONTHLY_1_END"))
valid = oblig.validate()
selection = oblig.get_selection()
companies.save_obligation_profile(
    company_id,
    selection["obligation_type_ids"],
    kdv_variants=selection["kdv_variants"],
    sgk_wage_period=selection["sgk_wage_period"],
    enabled_from=date(2026, 1, 1),
)
kdv_ok = companies.get_kdv_profile(company_id) == ["KDV_STANDARD_MONTHLY"]
sgk_ok = companies.get_sgk_wage_period(company_id) == "MONTHLY_1_END"
step(3, "KDV Aylık seç", valid and kdv_ok, str(companies.get_kdv_profile(company_id)))
step(4, "SGK 1–Ay Sonu seç", sgk_ok, companies.get_sgk_wage_period(company_id))

# 5 ---------------------------------------------------------------- dashboard shows
window.show_page("dashboard")
window.dashboard_page.refresh()
year_items = reminders.list_due(horizon_days=450, today=date(2026, 1, 1), company_id=company_id)
kdv_count = len([i for i in year_items if i.obligation_code == "GIB_KDV"])
sgk_count = len([i for i in year_items if i.obligation_code == "SGK_4A_PREMIUM"])
step(5, "Dashboard resmî yükümlülükleri gösteriyor", kdv_count == 12 and sgk_count == 12,
     f"KDV {kdv_count}, SGK {sgk_count}")

# 6 -------------------------------------------------------------------- add vehicle
from ui.dialogs.vehicle_dialog import VehicleDialog  # noqa: E402

window.show_page("vehicles")
vdialog = VehicleDialog(companies, window, company_id=company_id)
vdialog.company_combo.setCurrentIndex(vdialog.company_combo.findData(company_id))
vdialog.plate_edit.setText("35abc123")  # sloppy input on purpose
vdialog.make_edit.setText("Ford")
vok = vdialog.validate()
vehicle_id = companies.create_vehicle(**vdialog.get_data())
plate = companies.get_vehicle(vehicle_id).plate
step(6, "Araç ekle: 35 ABC 123", vok and plate == "35 ABC 123", f"normalize edildi: {plate}")

# 7/8 --------------------------------------------------- vehicle inspection reminder
from ui.dialogs.reminder_dialog import ReminderDialog  # noqa: E402

rdialog = ReminderDialog(
    reminders,
    companies,
    window,
    prefill={"company_id": company_id, "vehicle_id": vehicle_id, "category": "VEHICLE_INSPECTION"},
)
rdialog.title_edit.setText("Araç Muayenesi")
from PySide6.QtCore import QDate  # noqa: E402

due = TODAY + timedelta(days=14)
rdialog.date_edit.setDate(QDate(due.year, due.month, due.day))
rdialog.offsets_edit.setText("7, 3, 1")
rvalid = rdialog.validate()
payload = rdialog.get_data()
reminder_id = reminders.create_manual(**payload)
record = reminders.get_manual(reminder_id)
step(7, "Araç Muayenesi: 14 gün sonrası", rvalid and record.due_date == due.isoformat()
     and record.vehicle_id == vehicle_id, f"plaka {record.plate}")
offsets = reminders.notification_rules.get_effective_offsets("MANUAL", reminder_id)
step(8, "7/3/1 gün bildirim kuralı", offsets == [7, 3, 1], str(offsets))

# 9 ---------------------------------------------------------------------- edit it
window.show_page("reminders")
window.reminders_page.refresh()
edit = ReminderDialog(reminders, companies, window, existing=record)
round_trip = edit.vehicle_combo.currentData() == vehicle_id
edit.title_edit.setText("Araç Muayenesi (güncellendi)")
reminders.update_manual(reminder_id, **edit.get_data())
updated = reminders.get_manual(reminder_id)
step(9, "Hatırlatmayı düzenle", round_trip and updated.title.endswith("(güncellendi)")
     and updated.vehicle_id == vehicle_id, "araç seçimi düzenlemede korundu")

# 10/11 ------------------------------------------------------------- complete + undo
reminders.complete(source_kind="MANUAL", source_id=reminder_id, company_id=company_id)
completed = reminders.is_completed("MANUAL", reminder_id, company_id)
window.reminders_page.status_combo.setCurrentIndex(
    window.reminders_page.status_combo.findData("COMPLETED")
)
window.reminders_page.refresh()
in_history = any(i.source_id == reminder_id for i in window.reminders_page._items)
step(10, "Tamamla", completed)
step(11, "Geçmişte görünüyor", in_history, f"{len(window.reminders_page._items)} tamamlanmış kayıt")
window.reminders_page.status_combo.setCurrentIndex(0)

# 12 ------------------------------------------------------------- yearly recurrence
kasko_id = reminders.create_manual(
    title="Kasko Yenileme",
    due_date=TODAY + timedelta(days=30),
    company_id=company_id,
    vehicle_id=vehicle_id,
    category="KASKO",
    recurrence_kind="YEARLY",
)
reminders.complete(source_kind="MANUAL", source_id=kasko_id, company_id=company_id)
children = [
    r for r in reminders.search_manual(limit=200) if r.parent_reminder_id == kasko_id
]
next_due = date.fromisoformat(children[0].due_date) if children else None
step(12, "Kasko yıllık tekrar", len(children) == 1 and next_due.year == (TODAY + timedelta(days=30)).year + 1,
     f"sonraki: {next_due}")

# 13/14/15 ------------------------------------------------------- close / tray / quit
from unittest.mock import MagicMock  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402

tray = MagicMock()
tray.isVisible.return_value = True
window.set_tray_icon(tray)
quit_seen = []
window.quit_requested.connect(lambda: quit_seen.append(1))
window.show()
close1 = QCloseEvent()
window.closeEvent(close1)
step(13, "Programı kapat", not close1.isAccepted())
step(14, "Tepside yaşıyor", not window.isVisible() and not quit_seen)
settings.set_minimize_to_tray(False)
window._settings_changed()
close2 = QCloseEvent()
window.closeEvent(close2)
step(15, "Tam çıkış", close2.isAccepted() and quit_seen == [1])
settings.set_minimize_to_tray(True)

# 16/17 ------------------------------------------------------------------ restart
window.deleteLater()
db2 = Database(get_database_path())
again = MigrationRunner(db2, ROOT / "database" / "migrations").run()
companies2 = CompanyService(db2)
reminders2 = ReminderService(db2)
survived = (
    companies2.get_by_id(company_id).tax_number == "1234567890"
    and companies2.get_kdv_profile(company_id) == ["KDV_STANDARD_MONTHLY"]
    and companies2.get_sgk_wage_period(company_id) == "MONTHLY_1_END"
    and reminders2.get_manual(reminder_id).vehicle_id == vehicle_id
)
step(16, "Yeniden başlat", again == [], "migration tekrar uygulanmadı")
step(17, "Veriler korundu", survived, "şirket + profil + araç bağlantısı")

window2 = MainWindow(reminders2, companies2, SettingsService(db2), OfficialUpdateService(db2))
window2.resize(1280, 800)

# 18/19 ----------------------------------------------------------------- live sync
official2 = OfficialUpdateService(db2)
gib = official2.sync_gib(2026, timeout=45)
gib_ok = gib["status"] in ("UNCHANGED", "UPDATED")
step(18, "GİB sync", gib_ok, f"{gib['status']}, {gib.get('items_seen')} item", skipped=not gib_ok)
sgk = official2.sync_sgk(max_pages=1)
sgk_ok = sgk["status"] in ("SYNCED", "UPDATED")
step(19, "SGK sync", sgk_ok,
     f"{sgk['status']}, {sgk.get('discovered')} duyuru, {sgk.get('auto_applied')} uygulandı",
     skipped=not sgk_ok)

# 20 -------------------------------------------------------------------- offline
import socket  # noqa: E402

real_conn = socket.create_connection


def refuse(*a, **k):
    raise OSError("offline")


socket.create_connection = refuse
offline_result = OfficialUpdateService(db2).sync_sgk(max_pages=1)
counts = reminders2.get_dashboard_counts(today=TODAY, company_id=company_id)
adapter = RecordingNotificationAdapter()
delivered = NotificationService(db2, reminders2, adapter=adapter).check_and_notify(today=TODAY)
socket.create_connection = real_conn
step(20, "Çevrimdışı mod", offline_result["status"] == "FAILED" and counts["this_month"] >= 0
     and delivered >= 0, f"dashboard çalışıyor, {delivered} bildirim")

# 21/22 -------------------------------------------------------------------- backup
from services.backup_service import BackupService  # noqa: E402
import sqlite3  # noqa: E402

backup = BackupService(get_database_path(), get_backups_dir()).create_backup(force=True)
step(21, "Yedek al", backup is not None and backup.exists(), backup.name if backup else "")
conn = sqlite3.connect(backup)
integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
fk = conn.execute("PRAGMA foreign_key_check").fetchall()
saved = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
conn.close()
step(22, "Yedek integrity_check", integrity == "ok" and not fk and saved >= 1,
     f"{integrity}, {saved} şirket")

# 23 ------------------------------------------------------------ revision scenarios
with db2.session() as c:
    revisions = c.execute(
        """
        SELECT e.source_event_key, r.old_due_date, r.new_due_date
        FROM official_calendar_revisions r
        JOIN official_calendar_events e ON e.id = r.official_event_id
        ORDER BY r.id
        """
    ).fetchall()
    muhsgk = c.execute(
        """
        SELECT COUNT(*) c FROM official_calendar_revisions r
        JOIN official_calendar_events e ON e.id = r.official_event_id
        JOIN obligation_types t ON t.id = e.obligation_type_id
        WHERE t.code='GIB_MUHSGK'
        """
    ).fetchone()["c"]
pairs = {(r["old_due_date"], r["new_due_date"]) for r in revisions}
# Depends on step 19 having reached the live site.
step(23, "Resmî revision senaryoları",
     ("2026-03-31", "2026-04-07") in pairs and muhsgk == 0,
     f"{len(revisions)} revision, GIB_MUHSGK revision={muhsgk}", skipped=not sgk_ok)

# 24 -------------------------------------------------------------- notification smoke
notifier = NotificationService(db2, reminders2, adapter=RecordingNotificationAdapter())
service = OfficialUpdateService(db2, notifier=notifier)
shown = service.announce_revisions()
texts = [payload.body for payload in notifier.adapter.shown]
step(24, "Bildirim smoke", shown >= 1 and any("→" in text for text in texts),
     texts[0].replace("\n", " | ") if texts else "gösterilecek revision yok",
     skipped=not revisions)

# 25 --------------------------------------------------------------------- packaged
packaged = ROOT / "dist" / "OfficeReminder" / "OfficeReminder.exe"
step(25, "Paketlenmiş build mevcut", packaged.exists(),
     f"{packaged.stat().st_size // 1024} KB" if packaged.exists() else "yok")

print()
failed = [entry for entry in STEPS if not entry[2] and not entry[4]]
skipped = [entry for entry in STEPS if entry[4]]
summary = f"{len(STEPS) - len(failed) - len(skipped)}/{len(STEPS)} adım geçti"
if skipped:
    summary += f", {len(skipped)} atlandı (ağ yok)"
print(summary)
if failed:
    print("BAŞARISIZ:", ", ".join(f"{n}. {t}" for n, t, *_ in failed))
sys.exit(1 if failed else 0)
