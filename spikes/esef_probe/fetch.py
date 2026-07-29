"""Stage 1: get some real ESEF filings onto disk.

filings.xbrl.org exposes a JSON:API index of filings lodged with EU officially
appointed mechanisms. If that API has moved or changed shape, this stage is the
one that breaks, and the fallback is deliberate: drop report packages into
work/filings/ by hand and every later stage still works. The probe is about the
XBRL, not about the download.

**There are no German filings in this index.** Measured on 2026-07-29: DE
returns 0 against FR 1176, DK 2126, SE 1415, FI 1168, NO 958, PL 877, IT 872,
BE 706, NL 656, AT 600, ES 542. Germany's officially appointed mechanism is the
Unternehmensregister, which is commercially gated and does not feed the open
index, so the "German issuers" filter in ADR-0003 is not executable.

Austria is used instead. It is German-language, so the compound-noun and
multilingual-embedding argument survives intact, and the ESEF and Inline XBRL
mechanics are identical because they come from an EU regulation rather than a
national one. The country list is a parameter rather than a constant so this
stays easy to widen.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx

from . import FILINGS, TARGET_FILINGS, ensure_dirs

API = "https://filings.xbrl.org/api/filings"
BASE = "https://filings.xbrl.org"

# German-language first, then the larger EU indices if more filings are needed.
COUNTRIES = ("AT",)

# Some reports are a single XHTML of 75 MB or more, with images inlined as
# base64. Rendering one of those is minutes of work for no extra information, so
# the probe skips them and takes the next candidate.
MAX_PACKAGE_BYTES = 40_000_000


def _candidates(limit: int) -> list[dict]:
    """Fetch candidate filings, newest first, across the configured countries."""
    found: list[dict] = []
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for country in COUNTRIES:
            response = client.get(
                API,
                params={
                    "page[size]": str(max(limit * 8, 40)),
                    "filter[country][eq]": country,
                },
            )
            response.raise_for_status()
            rows = response.json().get("data", [])
            print(f"[fetch] {country}: {len(rows)} candidates")
            found.extend(rows)
            if len(found) >= limit * 8:
                break
    return found


def _absolute(url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else f"{BASE}{url}"


def _package_url(entry: dict) -> str | None:
    attributes = entry.get("attributes", {})
    return _absolute(attributes.get("package_url")) or _absolute(attributes.get("report_url"))


def _extract_report(archive: bytes, destination: Path) -> Path | None:
    """Pull the inline XBRL report out of a report package.

    An ESEF package puts the report under reports/ inside the zip. Take the
    largest xhtml file, which is the report itself rather than a stylesheet or
    a fragment. Some entries serve the bare XHTML rather than a package, so a
    non-zip payload is written straight through.
    """
    if archive[:2] != b"PK":
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "report.xhtml"
        target.write_bytes(archive)
        return target

    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        reports = [
            info
            for info in bundle.infolist()
            if info.filename.lower().endswith((".xhtml", ".html")) and not info.is_dir()
        ]
        if not reports:
            return None
        biggest = max(reports, key=lambda info: info.file_size)
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "report.xhtml"
        target.write_bytes(bundle.read(biggest))

        # Stylesheets and images affect layout, so the render needs them too.
        for info in bundle.infolist():
            if info.is_dir() or info is biggest:
                continue
            if info.filename.lower().endswith((".css", ".png", ".jpg", ".jpeg", ".svg", ".woff2")):
                out = destination / Path(info.filename).name
                out.write_bytes(bundle.read(info))
        return target


def run(limit: int = TARGET_FILINGS) -> list[Path]:
    ensure_dirs()

    existing = sorted(p for p in FILINGS.glob("*/report.xhtml"))
    if len(existing) >= limit:
        print(f"[fetch] {len(existing)} filings already present, skipping download")
        return existing[:limit]

    print(f"[fetch] querying {API} for {', '.join(COUNTRIES)} filings")
    fetched: list[Path] = list(existing)
    with httpx.Client(timeout=180.0, follow_redirects=True) as client:
        for entry in _candidates(limit):
            if len(fetched) >= limit:
                break
            url = _package_url(entry)
            if not url:
                continue
            name = entry.get("attributes", {}).get("fxo_id") or entry.get("id") or "filing"
            destination = FILINGS / str(name).replace("/", "_")
            if (destination / "report.xhtml").exists():
                continue
            try:
                head = client.head(url)
                size = int(head.headers.get("content-length") or 0)
                if size > MAX_PACKAGE_BYTES:
                    print(f"[fetch] skipping {name}: {size / 1e6:.0f} MB exceeds the size guard")
                    continue
                print(f"[fetch] downloading {name} ({size / 1e6:.1f} MB)")
                payload = client.get(url).raise_for_status().content
                report = _extract_report(payload, destination)
            except Exception as error:  # a spike logs the failure and moves on
                print(f"[fetch] skipped {name}: {error}")
                continue
            if report:
                fetched.append(report)
                print(f"[fetch] extracted {report.parent.name}")

    if not fetched:
        print(
            "[fetch] nothing downloaded. Drop ESEF report packages into\n"
            f"        {FILINGS}/<name>/report.xhtml and rerun the later stages."
        )
    return fetched[:limit]
