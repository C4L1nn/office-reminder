"""Office Reminder entry point.

    python main.py               start normally
    python main.py --background  start into the tray without showing the window
    python main.py --selftest    verify storage and bundled resources, then exit

`--selftest` exists so a packaged build can be checked without a desktop
session: it applies migrations, loads the bundled calendar and prints a short
report, which is exactly what the release checklist runs after building.
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    flags = {arg for arg in argv[1:] if arg.startswith("--")}
    # Qt must not see our own flags.
    sys.argv = [argv[0]] + [arg for arg in argv[1:] if arg not in flags]

    if "--selftest" in flags:
        from app.selftest import run_selftest

        return run_selftest()

    if "--version" in flags:
        from app.version import APP_NAME, APP_VERSION

        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    from app.application import OfficeReminderApplication

    return OfficeReminderApplication(background="--background" in flags).run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
