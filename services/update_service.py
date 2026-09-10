"""Finding out whether a newer build exists, and fetching it without trusting it.

The office runs this program in several locations with nobody technical
nearby, so carrying a new version out by hand does not scale. The rule that
shapes everything here: an update is *offered*, never applied on its own, and
nothing is unpacked before its sha256 matches what the manifest promised.

The manifest lives in a separate public repository so the source repository can
stay private and no credential has to be baked into the executable. It is read
straight from raw.githubusercontent.com — no GitHub API, no authentication, no
hourly request limit.

Network access is injected as a `fetch(url, timeout) -> (bytes, headers)`
callable, the same shape the GİB and SGK services use, so tests never go
online.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger("office_reminder.update")

#: Manifest layout this client understands. A manifest that declares a higher
#: number is refused rather than guessed at: the field exists precisely so a
#: future format can be introduced without old clients mis-reading it.
SCHEMA = 1

MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "C4L1nn/office-reminder-releases/main/latest.json"
)

USER_AGENT = "OfficeReminder-Updater/1.0"

#: Packages may only be downloaded from these hosts. The manifest itself comes
#: from a fixed HTTPS address we control, but this stops a manifest that has
#: been tampered with from pointing the downloader at somewhere else entirely.
ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "raw.githubusercontent.com",
    }
)

#: A sanity ceiling, not a product limit: the full package is ~43 MB, so
#: anything approaching this means the manifest is wrong and the disk should
#: not be filled finding out.
MAX_PACKAGE_BYTES = 500 * 1024 * 1024

_CHUNK = 256 * 1024


class UpdateError(Exception):
    """Anything that makes an update unsafe to continue with."""


@dataclass(frozen=True, slots=True)
class Package:
    """One downloadable artefact and the digest it must match."""

    kind: str  # "full" | "delta"
    url: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class Release:
    """A published version, as described by the manifest."""

    version: tuple[int, int, int]
    version_text: str
    notes: str
    released: str | None
    full: Package
    #: Present only when the publisher built a difference package, and only
    #: usable by someone running exactly `delta_from`.
    delta: Package | None
    delta_from: tuple[int, int, int] | None
    #: Below this, the jump is not supported and the user installs by hand.
    min_version: tuple[int, int, int]


def parse_version(text: str) -> tuple[int, int, int]:
    """"1.2.3" as a comparable tuple. Anything else is an error, not a guess."""
    if not isinstance(text, str):
        raise UpdateError(f"Sürüm numarası metin değil: {text!r}")
    parts = text.strip().split(".")
    if len(parts) != 3:
        raise UpdateError(f"Sürüm numarası 'x.y.z' biçiminde değil: {text!r}")
    try:
        numbers = tuple(int(part) for part in parts)
    except ValueError:
        raise UpdateError(f"Sürüm numarası sayı içermiyor: {text!r}") from None
    if any(number < 0 for number in numbers):
        raise UpdateError(f"Sürüm numarası negatif: {text!r}")
    return numbers  # type: ignore[return-value]


def _require(mapping: dict, key: str, kind: type):
    if key not in mapping:
        raise UpdateError(f"Manifestte '{key}' alanı yok")
    value = mapping[key]
    if not isinstance(value, kind):
        raise UpdateError(f"Manifestte '{key}' alanı beklenen türde değil")
    return value


def _check_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise UpdateError(f"Paket adresi HTTPS değil: {url}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise UpdateError(f"Paket adresi izin verilen sunucularda değil: {parsed.hostname}")
    return url


def _check_digest(value: str) -> str:
    digest = value.strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise UpdateError("sha256 özeti 64 haneli onaltılık bir sayı değil")
    return digest


def _parse_package(raw: dict, kind: str) -> Package:
    size = _require(raw, "size", int)
    if size <= 0 or size > MAX_PACKAGE_BYTES:
        raise UpdateError(f"Paket boyutu makul aralıkta değil: {size}")
    return Package(
        kind=kind,
        url=_check_url(_require(raw, "url", str)),
        sha256=_check_digest(_require(raw, "sha256", str)),
        size=size,
    )


def parse_manifest(payload: bytes) -> Release:
    """Turn the published manifest into a Release, or refuse it.

    Every field is checked here rather than at the point of use: by the time
    anything is downloaded the description must already be trustworthy.
    """
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Manifest okunamadı: {exc}") from exc
    if not isinstance(raw, dict):
        raise UpdateError("Manifest bir nesne değil")

    schema = _require(raw, "schema", int)
    if schema > SCHEMA:
        raise UpdateError(
            f"Manifest bu sürümün anlamadığı bir biçimde (schema {schema}). "
            "Güncellemeyi elle kurun."
        )

    version_text = _require(raw, "version", str)
    full = _parse_package(_require(raw, "full", dict), "full")

    delta = None
    delta_from = None
    if "delta" in raw and raw["delta"] is not None:
        delta_raw = _require(raw, "delta", dict)
        delta = _parse_package(delta_raw, "delta")
        delta_from = parse_version(_require(delta_raw, "from", str))

    min_version = parse_version(raw.get("min_version") or "0.0.0")

    return Release(
        version=parse_version(version_text),
        version_text=version_text.strip(),
        notes=str(raw.get("notes") or "").strip(),
        released=(str(raw["released"]).strip() if raw.get("released") else None),
        full=full,
        delta=delta,
        delta_from=delta_from,
        min_version=min_version,
    )


def _http_get(url: str, timeout: int = 20) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise urllib.error.HTTPError(
                url, response.status, "unexpected status", response.headers, None
            )
        return response.read(), dict(response.headers)


def manifest_fetcher(mapping: dict[str, bytes]):
    """Fetcher backed by fixed payloads, so tests never reach the network."""

    def fetch(url: str, timeout: int = 20) -> tuple[bytes, dict]:
        if url not in mapping:
            raise urllib.error.URLError(f"no payload for {url}")
        return mapping[url], {"content-type": "application/octet-stream"}

    return fetch


class UpdateService:
    """Reads the manifest, decides whether it is worth offering, fetches it."""

    def __init__(
        self,
        current_version: str,
        fetch: Callable[..., tuple[bytes, dict]] | None = None,
        manifest_url: str = MANIFEST_URL,
        open_url: Callable[..., object] | None = None,
    ) -> None:
        self.current = parse_version(current_version)
        self.current_text = current_version
        self.fetch = fetch or _http_get
        self.manifest_url = manifest_url
        # The manifest is small enough to read in one go, but a package is
        # tens of megabytes and has to stream so the progress bar means
        # something — hence a second, separately injectable entry point.
        self.open_url = open_url or urllib.request.urlopen

    # ------------------------------------------------------------------ check
    def check(self) -> Release | None:
        """The published release when it is newer than this build, else None.

        Returning None for "same version" matters: the caller shows nothing at
        all rather than a banner offering the version already running.
        """
        payload, _ = self.fetch(self.manifest_url, timeout=15)
        release = parse_manifest(payload)
        if release.version <= self.current:
            return None
        return release

    def supported(self, release: Release) -> bool:
        """False when this build is too old for the published package."""
        return self.current >= release.min_version

    def choose(self, release: Release) -> Package:
        """The difference package when it fits this exact build, else the full one.

        A delta is only valid for the version it was built against; offering it
        to anyone else would produce a folder that is part one version and part
        another.
        """
        if release.delta is not None and release.delta_from == self.current:
            return release.delta
        return release.full

    # --------------------------------------------------------------- download
    def download(
        self,
        package: Package,
        destination: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Fetch a package and hand it back only if its digest matches.

        Written to a `.part` file first: an interrupted download must never be
        mistaken for a finished one on the next attempt.
        """
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        digest = hashlib.sha256()
        written = 0

        request = urllib.request.Request(package.url, headers={"User-Agent": USER_AGENT})
        try:
            with self.open_url(request, timeout=60) as response:
                if response.status != 200:
                    raise UpdateError(f"İndirme başarısız: HTTP {response.status}")
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > package.size:
                            raise UpdateError("Paket bildirilen boyuttan büyük")
                        digest.update(chunk)
                        handle.write(chunk)
                        if progress is not None:
                            progress(written, package.size)
        except UpdateError:
            partial.unlink(missing_ok=True)
            raise
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError(f"İndirme başarısız: {exc}") from exc

        if written != package.size:
            partial.unlink(missing_ok=True)
            raise UpdateError(
                f"Paket eksik indi: {written} bayt, beklenen {package.size}"
            )
        if digest.hexdigest() != package.sha256:
            partial.unlink(missing_ok=True)
            raise UpdateError(
                "Paketin sha256 özeti manifesttekiyle uyuşmuyor; kurulum yapılmadı."
            )

        destination.unlink(missing_ok=True)
        partial.replace(destination)
        logger.info("Update package verified: %s (%s bayt)", destination.name, written)
        return destination


def update_dir(root: Path | None = None) -> Path:
    """Where downloads and staged folders live: outside the program folder.

    The helper that swaps the program folder cannot live inside the folder it
    is replacing, and neither can the files it copies from.
    """
    if root is None:
        from app.paths import get_runtime_root

        root = get_runtime_root() / "update"
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


__all__ = [
    "ALLOWED_HOSTS",
    "MANIFEST_URL",
    "MAX_PACKAGE_BYTES",
    "Package",
    "Release",
    "SCHEMA",
    "UpdateError",
    "UpdateService",
    "manifest_fetcher",
    "parse_manifest",
    "parse_version",
    "update_dir",
]
