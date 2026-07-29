"""Stage 1: get some real ESEF filings onto disk.

filings.xbrl.org exposes a JSON:API index of filings lodged with EU officially
appointed mechanisms. If that API has moved or changed shape, this stage is the
one that breaks, and the fallback is deliberate: drop report packages into
work/filings/ by hand and every later stage still works. The probe is about the
XBRL, not about the download.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx

from . import FILINGS, TARGET_FILINGS, ensure_dirs

API = "https://filings.xbrl.org/api/filings"
COUNTRY = "DE"


def _candidates(limit: int) -> list[dict]:
    params = {
        "page[size]": str(limit * 4),
        "filter[country]": COUNTRY,
        "sort": "-date_added",
    }
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(API, params=params)
        response.raise_for_status()
        return response.json().get("data", [])


def _package_url(entry: dict) -> str | None:
    url = entry.get("attributes", {}).get("package_url")
    if not url:
        return None
    return url if url.startswith("http") else f"https://filings.xbrl.org{url}"


def _extract_report(archive: bytes, destination: Path) -> Path | None:
    """Pull the inline XBRL report out of a report package.

    An ESEF package puts the report under reports/ inside the zip. Take the
    largest xhtml file, which is the report itself rather than a stylesheet or
    a fragment.
    """
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        reports = [
            info
            for info in bundle.infolist()
            if info.filename.lower().endswith((".xhtml", ".html"))
            and not info.is_dir()
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

    print(f"[fetch] querying {API} for {COUNTRY} filings")
    fetched: list[Path] = list(existing)
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        for entry in _candidates(limit):
            if len(fetched) >= limit:
                break
            url = _package_url(entry)
            if not url:
                continue
            name = entry.get("id") or url.rsplit("/", 1)[-1]
            destination = FILINGS / str(name).replace("/", "_")
            if (destination / "report.xhtml").exists():
                continue
            print(f"[fetch] downloading {url}")
            try:
                payload = client.get(url).raise_for_status().content
                report = _extract_report(payload, destination)
            except Exception as error:  # a spike logs the failure and moves on
                print(f"[fetch] skipped {name}: {error}")
                continue
            if report:
                fetched.append(report)
                print(f"[fetch] extracted {report}")

    if not fetched:
        print(
            "[fetch] nothing downloaded. Drop ESEF report packages into\n"
            f"        {FILINGS}/<name>/report.xhtml and rerun the later stages."
        )
    return fetched[:limit]
