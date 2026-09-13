# Office Reminder

Office Reminder is a Windows desktop application for managing recurring business obligations,
official due dates and local reminders. It is built with **Python, PySide6 and SQLite** and is
designed to remain useful even when the computer is offline.

The application ships with a normalized 2026 GIB tax calendar and can process SGK notices while
preserving source provenance. Company-specific reminders such as vehicle inspection, insurance,
rent and contract dates can be added manually.

> This project is not legal, tax or accounting advice. Official dates can change. Users should
> verify critical deadlines against the relevant official authority.

## Highlights

- Local-first Windows desktop application
- PySide6 + SQLite, no hosted backend required
- GIB and SGK official-source processing with provenance
- Fail-closed handling of ambiguous official data
- Company-specific reminders and recurring schedules
- In-app and Windows notifications
- System tray support and optional always-on-top mini counter
- Automatic local backups
- Self-test mode for packaged builds
- Signed-by-hash style update verification with rollback-friendly install flow
- Offline test suite using archived public-source fixtures

## Quick start

Requirements:

- Windows
- Python 3.11+

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

On first launch, migrations are applied automatically and the bundled official calendar seed is
loaded.

### Command-line options

| Command | Purpose |
|---|---|
| `python main.py` | Start normally |
| `python main.py --background` | Start directly in the system tray |
| `python main.py --selftest` | Validate storage and packaged resources, then exit |
| `python main.py --version` | Print the application version |

## Data location

The packaged application stores mutable runtime data under:

`%LOCALAPPDATA%\OfficeReminder\`

When running from source, development data is stored below the repository's local `data/`
directory.

Runtime databases, backups, logs and exports are intentionally excluded from version control.

## Testing

```powershell
pytest -q
```

The test suite is designed to run without network access. SGK parser tests use archived public
pages and documents stored under `tests/fixtures/sgk/`.

The current release checklist records **457 passing tests** for version 1.1.0.

## Building

Build from a clean virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean office_reminder.spec
```

Then validate the packaged application:

```powershell
dist\OfficeReminder\OfficeReminder.exe --selftest
```

## Architecture

```
UI -> Service -> Repository -> SQLite
```

The UI layer does not issue SQL directly. Business rules live in services, and persistence is
isolated in repositories. Published migrations are treated as immutable.

Additional engineering context:

- `AGENTS.md` - architecture and development invariants
- `RELEASE_CHECKLIST.md` - release verification
- `FINAL_AUDIT.md` - detailed technical audit
- `PLAN.md` - product and implementation decisions

## Official data and attribution

The repository contains normalized or archived material derived from public official sources,
including GIB and SGK, for application functionality and offline testing. Source URLs and
acquisition metadata are preserved where practical.

Third-party/public-source material remains subject to its original terms and is not relicensed
by the MIT license covering this project's original source code.

## Privacy and security

Office Reminder is local-first. Before contributing, please read [SECURITY.md](SECURITY.md).

Never commit real company databases, exports, backups, credentials or private documents.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Original project source code is licensed under the [MIT License](LICENSE).

Government/public-source fixtures and datasets included for provenance or testing are subject to
their original source terms.
