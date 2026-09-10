"""Office Reminder entry point.

    python main.py                     start normally
    python main.py --background        start into the tray without showing the window
    python main.py --selftest          verify storage and bundled resources, then exit
    python main.py --data-dir=PATH     use PATH as the runtime root instead of
                                       %LOCALAPPDATA%\\OfficeReminder

`--selftest` exists so a packaged build can be checked without a desktop
session: it applies migrations, loads the bundled calendar and prints a short
report, which is exactly what the release checklist runs after building.

`--data-dir` exists for the update gate. Before a downloaded build replaces the
installed one it is made to prove itself with `--selftest`, and that must not
touch the office's real database — a new version may carry migrations, and
running them before the user has committed to the update would leave the old
build facing a schema it does not know.
"""

from __future__ import annotations

import os
import sys

_DATA_DIR_FLAG = "--data-dir="


def _options(flags: set[str]) -> dict[str, str]:
    """`--key=value` flags as a plain mapping; bare flags are ignored here."""
    found: dict[str, str] = {}
    for flag in flags:
        if "=" not in flag:
            continue
        key, _, value = flag[2:].partition("=")
        found[key] = value.strip().strip('"')
    return found


def main(argv: list[str]) -> int:
    flags = {arg for arg in argv[1:] if arg.startswith("--")}
    # Qt must not see our own flags.
    sys.argv = [argv[0]] + [arg for arg in argv[1:] if arg not in flags]

    for flag in flags:
        if flag.startswith(_DATA_DIR_FLAG):
            path = flag[len(_DATA_DIR_FLAG):].strip().strip('"')
            if not path:
                print("--data-dir boş olamaz", file=sys.stderr)
                return 2
            # app.paths reads this when it resolves the runtime root, so it has
            # to be in place before anything imports it.
            os.environ["OFFICE_REMINDER_DATA_DIR"] = path

    apply = [flag for flag in flags if flag.startswith("--apply-update")]
    if apply:
        from app.update_installer import apply_update

        options = _options(flags)
        missing = [key for key in ("target", "staging", "update-root") if key not in options]
        if missing:
            print(f"--apply-update eksik argüman: {', '.join(missing)}", file=sys.stderr)
            return 2
        return apply_update(
            target=options["target"],
            staging=options["staging"],
            update_root=options["update-root"],
            wait_pid=int(options["wait-pid"]) if options.get("wait-pid") else None,
            version=options.get("version", ""),
        )

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
