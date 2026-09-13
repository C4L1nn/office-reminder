# Contributing

Thanks for considering a contribution to Office Reminder.

## Development setup

Office Reminder targets Windows and Python 3.11+.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```

## Architecture

The application follows:

```
UI -> Service -> Repository -> SQLite
```

Please keep SQL out of the UI layer and avoid direct repository access from widgets.
Published migrations are immutable; every schema change must be introduced as a new migration.

## Pull requests

Before opening a pull request:

1. Run the full test suite with `pytest -q`.
2. Add tests for new business rules or bug fixes.
3. Keep network-dependent behavior injectable and testable offline.
4. Do not commit runtime databases, backups, logs, exports, credentials or private company data.
5. Preserve provenance for official GIB/SGK data and fail closed on ambiguous source data.

## Official-source fixtures

Some tests use archived public pages/documents from official Turkish government sources.
When adding or updating fixtures, document the source URL and acquisition date and avoid
including personal or organization-specific data.

## Security-sensitive changes

For authentication, update, backup, notification delivery, or official-source processing
changes, describe failure modes and rollback behavior in the pull request.
