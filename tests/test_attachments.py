"""Files attached to a record.

The copy lives in the runtime folder, never in the database, and the office
must not be able to lose a file by deleting a different record that happens to
carry the same document.
"""

from __future__ import annotations

import pytest

from services.attachment_service import (
    MAX_BYTES,
    AttachmentError,
    AttachmentService,
    human_size,
)


@pytest.fixture()
def service(migrated_db, tmp_path) -> AttachmentService:
    return AttachmentService(migrated_db, root=tmp_path / "attachments")


@pytest.fixture()
def a_pdf(tmp_path):
    path = tmp_path / "tahakkuk fişi.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"x" * 500)
    return path


def test_attaching_copies_the_file_into_the_runtime_folder(service, a_pdf) -> None:
    attachment = service.attach("MANUAL", 1, a_pdf)
    assert attachment.exists
    assert attachment.path != a_pdf, "özgün dosyaya bağlanılmamalı"
    assert service.root in attachment.path.parents
    # The name the user recognises survives, even though the copy is a digest.
    assert attachment.display_name == "tahakkuk fişi.pdf"


def test_the_original_can_go_away(service, a_pdf) -> None:
    """A receipt in Downloads is gone by the time anyone looks again."""
    attachment = service.attach("MANUAL", 1, a_pdf)
    a_pdf.unlink()
    assert attachment.exists


def test_listing_is_per_record(service, a_pdf) -> None:
    service.attach("MANUAL", 1, a_pdf)
    assert len(service.list_for("MANUAL", 1)) == 1
    assert service.list_for("MANUAL", 2) == []
    assert service.count_for("MANUAL", 1) == 1


def test_attaching_the_same_file_twice_is_one_attachment(service, a_pdf) -> None:
    first = service.attach("MANUAL", 1, a_pdf)
    second = service.attach("MANUAL", 1, a_pdf)
    assert first.id == second.id
    assert service.count_for("MANUAL", 1) == 1


def test_each_record_owns_its_own_copy(service, a_pdf) -> None:
    """The same document on two records is stored twice on purpose: deleting
    one record can then never take a file out from under the other."""
    first = service.attach("MANUAL", 1, a_pdf)
    second = service.attach("MANUAL", 2, a_pdf)
    assert first.path != second.path

    service.remove(first.id)
    assert service.count_for("MANUAL", 1) == 0
    assert not first.path.exists()
    assert second.path.exists(), "diğer kaydın dosyası silinmemeliydi"


def test_removing_everything_for_a_record(service, a_pdf, tmp_path) -> None:
    other = tmp_path / "ikinci.png"
    other.write_bytes(b"\x89PNG\r\n" + b"y" * 100)
    service.attach("MANUAL", 7, a_pdf)
    service.attach("MANUAL", 7, other)
    assert service.remove_all_for("MANUAL", 7) == 2
    assert service.count_for("MANUAL", 7) == 0


def test_an_executable_is_refused(service, tmp_path) -> None:
    """The app must never become a way to carry a program between machines."""
    bad = tmp_path / "kurulum.exe"
    bad.write_bytes(b"MZ" + b"z" * 100)
    with pytest.raises(AttachmentError) as error:
        service.attach("MANUAL", 1, bad)
    assert "eklenemez" in str(error.value)


def test_an_oversized_file_is_refused_with_its_size(service, tmp_path) -> None:
    big = tmp_path / "kocaman.pdf"
    big.write_bytes(b"%PDF" + b"0" * (MAX_BYTES + 1))
    with pytest.raises(AttachmentError) as error:
        service.attach("MANUAL", 1, big)
    assert "çok büyük" in str(error.value)


def test_an_empty_file_is_refused(service, tmp_path) -> None:
    empty = tmp_path / "bos.pdf"
    empty.write_bytes(b"")
    with pytest.raises(AttachmentError):
        service.attach("MANUAL", 1, empty)


def test_a_missing_file_is_refused(service, tmp_path) -> None:
    with pytest.raises(AttachmentError):
        service.attach("MANUAL", 1, tmp_path / "yok.pdf")


def test_an_unknown_source_kind_is_refused(service, a_pdf) -> None:
    with pytest.raises(ValueError):
        service.attach("NOTE", 1, a_pdf)


def test_the_database_stores_a_path_not_the_bytes(service, a_pdf, migrated_db) -> None:
    service.attach("MANUAL", 1, a_pdf)
    with migrated_db.session() as connection:
        row = connection.execute("SELECT * FROM attachments").fetchone()
    assert row["relative_path"].endswith(".pdf")
    assert len(row["sha256"]) == 64
    assert "bytes" not in row.keys()


def test_human_size_reads_naturally() -> None:
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2 KB"
    assert human_size(5 * 1024 * 1024) == "5.0 MB"


# --------------------------------------------------------------- integration
def test_deleting_a_reminder_takes_its_files(migrated_db, tmp_path) -> None:
    """Nothing cascades a file away, so the reminder has to do it itself.

    The service is built without a `root` here, exactly as `delete_manual`
    builds it, so the file the cascade removes is the file this test wrote.
    """
    from datetime import date, timedelta

    from services.company_service import CompanyService
    from services.reminder_service import ReminderService

    source = tmp_path / "fis.pdf"
    source.write_bytes(b"%PDF-1.4\n" + b"x" * 200)

    companies = CompanyService(migrated_db)
    reminders = ReminderService(migrated_db)
    company_id = companies.create(name="EK LTD.", tax_number="4444444444")
    reminder_id = reminders.create_manual(
        title="Ekli kayıt",
        due_date=date.today() + timedelta(days=3),
        company_id=company_id,
        category="OTHER",
    )

    service = AttachmentService(migrated_db)  # default runtime root
    attachment = service.attach("MANUAL", reminder_id, source)
    assert attachment.exists

    reminders.delete_manual(reminder_id)

    assert service.count_for("MANUAL", reminder_id) == 0
    assert not attachment.path.exists(), "kayıt silindi, dosya diskte kaldı"


def test_ids_with_attachments_is_one_query(service, a_pdf, tmp_path) -> None:
    other = tmp_path / "ikinci.pdf"
    other.write_bytes(b"%PDF-1.4\n" + b"z" * 300)
    service.attach("MANUAL", 3, a_pdf)
    service.attach("MANUAL", 9, other)
    service.attach("VEHICLE", 3, a_pdf)

    assert service.ids_with_attachments("MANUAL") == {3, 9}
    assert service.ids_with_attachments("VEHICLE") == {3}
    assert service.ids_with_attachments("COMPANY") == set()
