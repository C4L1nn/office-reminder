"""Text extraction from downloaded announcement attachments.

Some SGK announcements carry an empty HTML body and put the whole text in an
attached PDF, so the analyzer cannot see the dates without reading it. Qt's PDF
module ships with PySide6 and is already bundled, so this needs no extra
dependency. If extraction is not possible the caller gets an empty string and
the notice falls through to NEEDS_REVIEW — never a guess.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("office_reminder.documents")

MAX_PDF_PAGES = 20


def extract_pdf_text(path: Path | str, max_pages: int = MAX_PDF_PAGES) -> str:
    """Plain text of a PDF, or '' when it cannot be read."""
    pdf_path = Path(path)
    if not pdf_path.exists():
        return ""
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtPdf import QPdfDocument
    except Exception:
        logger.info("QtPdf unavailable; attachment text not extracted")
        return ""

    # QPdfDocument needs a Qt application object; inside the running app one
    # already exists, and in a headless context a core application is enough.
    owned = None
    if QCoreApplication.instance() is None:
        owned = QCoreApplication([])

    try:
        document = QPdfDocument()
        status = document.load(str(pdf_path))
        if document.pageCount() <= 0:
            logger.info("PDF %s could not be loaded (%s)", pdf_path.name, status)
            return ""
        pages = []
        for index in range(min(document.pageCount(), max_pages)):
            selection = document.getAllText(index)
            pages.append(selection.text())
        return "\n".join(pages).strip()
    except Exception:
        logger.warning("PDF text extraction failed for %s", pdf_path, exc_info=True)
        return ""
    finally:
        if owned is not None:
            del owned


def is_pdf(filename: str | None, content_type: str | None) -> bool:
    if content_type and "pdf" in content_type.lower():
        return True
    return bool(filename and filename.lower().endswith(".pdf"))
