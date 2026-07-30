"""Fetch ESEF report packages to build a corpus from.

    uv run python -m disclosure_rag.labels.fetch --out data/filings --count 8

filings.xbrl.org indexes filings lodged with EU officially appointed mechanisms.
A report package is a zip holding the Inline XBRL report and its taxonomy, and
both halves are needed: the report carries the tagged figures, and the label
linkbase carries the German label each concept was declared with.

Germany is not available here. Its officially appointed mechanism is the
Unternehmensregister, which does not publish into this index, so the default
country is Austria: also German-language, and ESEF mechanics are identical
because they come from an EU regulation rather than a national one.
"""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path
from typing import Any

import httpx

API = "https://filings.xbrl.org/api/filings"
BASE = "https://filings.xbrl.org"

DEFAULT_COUNTRIES = ("AT",)

# The index returns JSON:API objects; only a couple of attributes are used.
Filing = dict[str, Any]

# Some filings are a single XHTML of 75 MB or more with images inlined as base64.
# Rendering one costs minutes for no extra tagged facts, so they are skipped.
MAX_PACKAGE_BYTES = 40_000_000

# Files worth keeping from a package: the report, whatever affects its layout,
# and the taxonomy, because the label linkbase supplies the concept labels.
KEEP_SUFFIXES = (".css", ".png", ".jpg", ".jpeg", ".svg", ".woff2", ".xml", ".xsd")


def list_candidates(
    countries: tuple[str, ...] = DEFAULT_COUNTRIES, page_size: int = 60
) -> list[Filing]:
    """Candidate filings, newest first, across the given countries."""
    found: list[Filing] = []
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for country in countries:
            response = client.get(
                API, params={"page[size]": str(page_size), "filter[country][eq]": country}
            )
            response.raise_for_status()
            found.extend(response.json().get("data", []))
    return found


def _absolute(url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else f"{BASE}{url}"


def package_url(entry: Filing) -> str | None:
    attributes = entry.get("attributes", {})
    return _absolute(attributes.get("package_url")) or _absolute(attributes.get("report_url"))


def extract_package(archive: bytes, destination: Path) -> Path | None:
    """Write the report and its taxonomy out of a package.

    Some entries serve the bare XHTML rather than a zip, so a non-zip payload is
    written straight through.
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

        # The largest XHTML is the report; the rest are fragments or stylesheets.
        biggest = max(reports, key=lambda info: info.file_size)
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "report.xhtml"
        target.write_bytes(bundle.read(biggest))

        for info in bundle.infolist():
            if info.is_dir() or info is biggest:
                continue
            if info.filename.lower().endswith(KEEP_SUFFIXES):
                (destination / Path(info.filename).name).write_bytes(bundle.read(info))
        return target


def fetch(
    out_dir: Path, count: int = 8, countries: tuple[str, ...] = DEFAULT_COUNTRIES
) -> list[Path]:
    """Download report packages until ``count`` filings are on disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fetched = sorted(path for path in out_dir.glob("*/report.xhtml"))
    if len(fetched) >= count:
        print(f"[fetch] {len(fetched)} filings already present")
        return fetched[:count]

    print(f"[fetch] querying {API} for {', '.join(countries)}")
    with httpx.Client(timeout=180.0, follow_redirects=True) as client:
        for entry in list_candidates(countries):
            if len(fetched) >= count:
                break
            url = package_url(entry)
            if not url:
                continue
            name = str(entry.get("attributes", {}).get("fxo_id") or entry.get("id") or "filing")
            destination = out_dir / name.replace("/", "_")
            if (destination / "report.xhtml").exists():
                continue
            try:
                size = int(client.head(url).headers.get("content-length") or 0)
                if size > MAX_PACKAGE_BYTES:
                    print(f"[fetch] skipping {name}: {size / 1e6:.0f} MB")
                    continue
                print(f"[fetch] {name} ({size / 1e6:.1f} MB)")
                report = extract_package(client.get(url).raise_for_status().content, destination)
            except Exception as error:  # one bad package must not stop the corpus
                print(f"[fetch] skipped {name}: {error}")
                continue
            if report:
                fetched.append(report)

    print(f"[fetch] {len(fetched)} filings in {out_dir}")
    return fetched[:count]


def main() -> int:
    parser = argparse.ArgumentParser(prog="disclosure_rag.labels.fetch", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument(
        "--countries",
        default=",".join(DEFAULT_COUNTRIES),
        help="comma-separated ISO country codes. DE returns nothing, see the module docstring",
    )
    args = parser.parse_args()

    countries = tuple(code.strip().upper() for code in args.countries.split(",") if code.strip())
    return 0 if fetch(args.out, args.count, countries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
