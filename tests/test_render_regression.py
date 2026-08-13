"""The rendered outline must land on the region it was given.

Everything else in this project is measured; the picture was checked once by eye.
That is the weakest link in a system whose whole claim is that a reader can
verify an answer by looking, because a coordinate convention error would produce
confident, precisely-wrong boxes while every number still looked correct.

These tests build a page, render it with a known region outlined, and read the
pixels back, so the geometry is asserted rather than trusted. The page is
constructed here rather than taken from the corpus so the check runs in CI,
where no filings are present.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from disclosure_rag.render import OUTLINE, render_page_with_regions

# Generous, because it has to cover the padding the renderer adds around a tight
# box, the width of the stroke itself, and antialiasing at the edges.
TOLERANCE = 0.03


@pytest.fixture(scope="module")
def page_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A two-page white document with a little text on it."""
    import fitz

    document = fitz.open()
    for number in range(2):
        page = document.new_page(width=595, height=842)  # A4 points
        page.insert_text((72, 100), f"Bilanzsumme {number}", fontsize=11)
    path = tmp_path_factory.mktemp("render") / "page.pdf"
    document.save(path)
    document.close()
    return path


def _outline_pixels(png: bytes) -> tuple[list[float], list[float]]:
    """Normalised x and y of every pixel close to the outline colour.

    Reads the sample buffer rather than calling pixel() per point, which is the
    difference between a test suite that runs in seconds and one people skip.
    """
    import fitz

    pixmap = fitz.Pixmap(io.BytesIO(png))
    red_target, green_target, blue_target = (round(channel * 255) for channel in OUTLINE)
    samples = pixmap.samples
    channels = pixmap.n
    width, height = pixmap.width, pixmap.height

    xs: list[float] = []
    ys: list[float] = []
    for index in range(0, len(samples) - channels + 1, channels):
        red, green, blue = samples[index], samples[index + 1], samples[index + 2]
        if (
            abs(red - red_target) < 60
            and abs(green - green_target) < 60
            and abs(blue - blue_target) < 60
        ):
            point = index // channels
            xs.append((point % width) / width)
            ys.append((point // width) / height)
    return xs, ys


def test_the_outline_is_drawn_where_the_span_says(page_pdf: Path) -> None:
    """The assertion the screenshot in the README stands on."""
    png = render_page_with_regions(page_pdf, 0, "0.20,0.30,0.40,0.35", dpi=72)
    xs, ys = _outline_pixels(png)

    assert xs, "no outline was drawn"
    assert min(xs) == pytest.approx(0.20, abs=TOLERANCE)
    assert max(xs) == pytest.approx(0.40, abs=TOLERANCE)
    assert min(ys) == pytest.approx(0.30, abs=TOLERANCE)
    assert max(ys) == pytest.approx(0.35, abs=TOLERANCE)


def test_the_outline_follows_the_span_down_the_page(page_pdf: Path) -> None:
    """Guards against a renderer that draws in a fixed place regardless of input."""
    _, upper = _outline_pixels(render_page_with_regions(page_pdf, 0, "0.1,0.10,0.3,0.15", dpi=72))
    _, lower = _outline_pixels(render_page_with_regions(page_pdf, 0, "0.1,0.60,0.3,0.65", dpi=72))

    assert upper and lower
    assert max(upper) < min(lower), "the outline did not move with the span"


def test_several_regions_are_all_outlined(page_pdf: Path) -> None:
    """A citation can cover more than one region, and all of them must be drawn."""
    one, _ = _outline_pixels(render_page_with_regions(page_pdf, 0, "0.1,0.1,0.2,0.2", dpi=72))
    two, _ = _outline_pixels(
        render_page_with_regions(page_pdf, 0, "0.1,0.1,0.2,0.2;0.7,0.1,0.8,0.2", dpi=72)
    )
    assert max(two) > max(one) + 0.3, "the second region was not drawn"


def test_no_regions_means_no_outline(page_pdf: Path) -> None:
    """A page with nothing cited renders clean, not with a stray box."""
    xs, _ = _outline_pixels(render_page_with_regions(page_pdf, 0, "", dpi=72))
    assert not xs


def test_a_region_is_rendered_on_the_page_it_names(page_pdf: Path) -> None:
    """Page 1 must not be outlined when the citation is for page 0."""
    first, _ = _outline_pixels(render_page_with_regions(page_pdf, 0, "0.2,0.3,0.4,0.35", dpi=72))
    second, _ = _outline_pixels(render_page_with_regions(page_pdf, 1, "", dpi=72))
    assert first
    assert not second


def test_a_page_outside_the_document_is_rejected(page_pdf: Path) -> None:
    with pytest.raises(IndexError, match="outside"):
        render_page_with_regions(page_pdf, 99, "0.1,0.1,0.2,0.2", dpi=72)
