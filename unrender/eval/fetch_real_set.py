"""Collect chart PNGs, source CSV bytes and DRAFT labels from FRED/OWID.

Downloaded CSV values do not prove that visible metadata, chart/data versions,
units or recoverable precision match. Drafts are explicitly unreviewed and cannot
enter new evaluation until the source-backed review in data/real_v0/README.md.
Original CSV bytes are retained alongside images for that review. Existing
curated title/axis/series strings are suggestions, not verified ground truth.

    python -m unrender.eval.fetch_real_set --dir data/real_dev_v1

Downloads through the same local/cloud collector; rejects responses without a
PNG signature. This is not a complete image-content or scientific-validity check.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import urllib.request
from pathlib import Path

from unrender.eval.build_real_set import label_to_chartdata  # validate before writing

# --- curated sources -------------------------------------------------------
# FRED: annual average (fq=Annual&fam=avg) over a date range, so each line has a
# readable ~8-12 yearly points across a spread of value scales (rates ~0-8%,
# indices, $-billions, thousands-of-jobs — good magnitude diversity).
_FRED_RANGE = ("2013-01-01", "2023-01-01")
FRED = [
    # (out_id, series, title, y_label, y_unit)
    ("fred_unrate", "UNRATE", "US Unemployment Rate", "Unemployment Rate", "%"),
    ("fred_fedfunds", "FEDFUNDS", "US Federal Funds Effective Rate", "Rate", "%"),
    ("fred_dgs10", "DGS10", "US 10-Year Treasury Yield", "Yield", "%"),
    ("fred_mortgage30", "MORTGAGE30US", "US 30-Year Fixed Mortgage Rate", "Rate", "%"),
    ("fred_cpi", "CPIAUCSL", "US Consumer Price Index", "CPI (1982-84=100)", None),
    ("fred_realgdp", "GDPC1", "US Real GDP", "Real GDP", "Billions of chained 2017 $"),
    ("fred_payems", "PAYEMS", "US Nonfarm Payroll Employment", "Employees", "Thousands"),
    ("fred_houst", "HOUST", "US Housing Starts", "Housing Starts", "Thousands of units"),
]
# OWID: one country, a line over time. The .csv ignores URL filters (always returns
# every country) so we filter client-side by ISO code; the .png DOES honor the
# country/time/tab state, so it renders just this country's line for this window.
_OWID_COUNTRY, _OWID_LO, _OWID_HI = "USA", 2000, 2023
OWID = [
    # (out_id, slug, title, y_label, y_unit)
    (
        "owid_life_exp",
        "life-expectancy",
        "Life Expectancy, United States",
        "Life expectancy",
        "years",
    ),
    ("owid_population", "population", "Population, United States", "Population", "people"),
    (
        "owid_gdp_pc",
        "gdp-per-capita-worldbank",
        "GDP per Capita, United States",
        "GDP per capita",
        "international-$",
    ),
    (
        "owid_co2_pc",
        "co-emissions-per-capita",
        "CO2 Emissions per Capita, US",
        "CO2 per capita",
        "tonnes",
    ),
    (
        "owid_internet",
        "share-of-individuals-using-the-internet",
        "Internet Use, United States",
        "Share using the Internet",
        "%",
    ),
    ("owid_hdi", "human-development-index", "Human Development Index, US", "HDI", None),
    (
        "owid_energy_pc",
        "energy-use-per-capita",
        "Energy Use per Capita, US",
        "Energy per capita",
        "kWh",
    ),
    (
        "owid_co2_total",
        "annual-co2-emissions-per-country",
        "Annual CO2 Emissions, US",
        "Annual CO2 emissions",
        "tonnes",
    ),
]


def _fred_urls(series: str):
    cosd, coed = _FRED_RANGE
    q = f"id={series}&cosd={cosd}&coed={coed}&fq=Annual&fam=avg"
    base = "https://fredgraph.stlouisfed.org/fredgraph"
    return f"{base}.png?{q}", f"{base}.csv?{q}"


def _owid_urls(slug: str):
    # tab=chart forces the line view (not the map default); country/time select the
    # single entity + window the .png renders (the .csv ignores these — we filter it).
    params = f"country=~{_OWID_COUNTRY}&time={_OWID_LO}..{_OWID_HI}&tab=chart"
    base = f"https://ourworldindata.org/grapher/{slug}"
    return f"{base}.png?{params}", f"{base}.csv?{params}"


def parse_fred_csv(text: str):
    """FRED CSV -> [[year, value], ...]. Col 0 is the date (YYYY-..; annual => the
    year), col 1 the value; '.' marks a missing observation (skipped)."""
    pts = []
    for i, parts in enumerate(csv.reader(io.StringIO(text))):
        if i == 0 or len(parts) < 2:  # header / blank
            continue
        date, val = parts[0].strip(), parts[1].strip()
        if val in (".", "", "NA", "NaN"):
            continue
        pts.append([date[:4], round(float(val), 4)])
    return pts


def parse_owid_csv(text: str, code: str = _OWID_COUNTRY, lo: int = _OWID_LO, hi: int = _OWID_HI):
    """OWID grapher CSV (Entity,Code,Year,<value>[,extra...]) -> [[year, value], ...]
    for ONE entity (by ISO `code`), within [lo, hi]. The value is column index 3 (the
    first data column after Year) — NOT the last column, which on some indicators is a
    region/annotation string."""
    pts = []
    for i, parts in enumerate(csv.reader(io.StringIO(text))):
        if i == 0 or len(parts) < 4 or parts[1].strip() != code:
            continue
        y = parts[2].strip()
        if not y.lstrip("-").isdigit() or not (lo <= int(y) <= hi):
            continue
        val = parts[3].strip()
        if val in ("", "NA", "NaN"):
            continue
        pts.append([y, round(float(val), 4)])
    return sorted(pts, key=lambda p: int(p[0]))


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Unrender source review"})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read()


def _is_png(b: bytes) -> bool:
    return b[:8] == b"\x89PNG\r\n\x1a\n"


def make_line_label(out_id, title, y_label, y_unit, series_name, points, source) -> dict:
    """The canonical hand-label dict for a fetched LINE time series (the exact shape
    build_real_set.label_to_chartdata validates). One builder, so this local fetcher and
    the Modal fetcher (modal_train.fetch_real_data) can't drift on the ground-truth schema."""
    return {
        "image": f"{out_id}.png",
        "chart_type": "line",
        "title": title,
        "x_axis": {"label": "Year", "unit": None},
        "y_axis": {"label": y_label, "unit": y_unit},
        "labels_shown": False,  # FRED/OWID line charts don't print point values
        "source": source,
        "ground_truth_review": {"status": "needs_visual_review"},
        "series": [{"name": series_name, "points": points}],
    }


def _fetch_one(
    out_id,
    png_url,
    csv_url,
    parse,
    title,
    y_label,
    y_unit,
    series_name,
    source,
    images_dir: Path,
    labels_dir: Path,
) -> str | None:
    for path in (
        images_dir / f"{out_id}.png",
        labels_dir / f"{out_id}.json",
        images_dir.parent / "sources" / f"{out_id}.csv",
    ):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite draft artifact: {path}")
    png = _download(png_url)
    if not _is_png(png):  # bad slug/param -> an HTML error page; don't write a fake chart
        raise ValueError(f"non-PNG response for {out_id}")
    source_bytes = _download(csv_url)
    points = parse(source_bytes.decode("utf-8", "replace"))
    if len(points) < 3:
        raise ValueError(f"fewer than three source points for {out_id}")
    label = make_line_label(out_id, title, y_label, y_unit, series_name, points, source)
    source_dir = images_dir.parent / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_file = source_dir / f"{out_id}.csv"
    source_file.write_bytes(source_bytes)
    label["source_data_file"] = f"sources/{out_id}.csv"
    label_to_chartdata(label, out_id)  # validate now; fail loud on any bad value
    (images_dir / f"{out_id}.png").write_bytes(png)
    (labels_dir / f"{out_id}.json").write_text(json.dumps(label, indent=2))
    print(f"  ✓ {out_id}: {len(points)} pts  ({title})")
    return out_id


def fetch(dirpath: str, *, sources: str = "all") -> int:
    """Create one exclusive draft attempt, including a durable complete schedule.

    Existing directories are never reused, including interrupted drafts. The
    pending/in-flight states remain visible after a crash. No test split is
    created here; independent review and build_real_set publication are required.
    """
    from unrender.eval.ledger import atomic_text

    if sources not in {"all", "fred", "owid"}:
        raise ValueError("sources must be all, fred or owid")
    root = Path(dirpath)
    root.mkdir(parents=True, exist_ok=False)
    images_dir, labels_dir = root / "images", root / "labels"
    images_dir.mkdir()
    labels_dir.mkdir()
    jobs = []
    if sources in {"all", "fred"}:
        for out_id, series, title, ylab, yunit in FRED:
            png_url, csv_url = _fred_urls(series)
            src = (
                f"FRED series {series} (fred.stlouisfed.org/series/{series}); "
                f"annual avg {_FRED_RANGE[0][:4]}–{_FRED_RANGE[1][:4]}"
            )
            jobs.append((out_id, png_url, csv_url, parse_fred_csv, title, ylab, yunit, series, src))
    if sources in {"all", "owid"}:
        for out_id, slug, title, ylab, yunit in OWID:
            png_url, csv_url = _owid_urls(slug)
            src = (
                f"Our World in Data: {slug} (ourworldindata.org/grapher/{slug}), "
                f"{_OWID_COUNTRY} {_OWID_LO}–{_OWID_HI}"
            )
            jobs.append((out_id, png_url, csv_url, parse_owid_csv, title, ylab, yunit, title, src))
    receipt = {
        "contract": "real-source-collection-v1",
        "status": "collecting",
        "attempts": [
            {"id": j[0], "image_url": j[1], "source_url": j[2], "state": "pending"} for j in jobs
        ],
    }

    def save():
        atomic_text(root / "collection.json", json.dumps(receipt, indent=2) + "\n")

    save()
    ok = 0
    for job, attempt in zip(jobs, receipt["attempts"], strict=True):
        attempt["state"] = "in_flight"
        save()
        try:
            _fetch_one(*job, images_dir, labels_dir)
            # Flush downloaded artifacts before recording completion.
            for path in (
                images_dir / f"{job[0]}.png",
                labels_dir / f"{job[0]}.json",
                root / "sources" / f"{job[0]}.csv",
            ):
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            attempt["state"] = "collected"
            ok += 1
        except Exception as exc:
            attempt.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        save()
    receipt["status"] = "complete" if ok == len(jobs) else "incomplete"
    save()
    print(f"Collected {ok}/{len(jobs)} draft sources; review required: {root}")
    return ok


def main():
    p = argparse.ArgumentParser(
        description="Fetch a real-chart eval set from FRED + OWID (needs internet)."
    )
    p.add_argument("--dir", required=True, help="new draft directory; must not exist")
    p.add_argument("--sources", choices=["all", "fred", "owid"], default="all")
    args = p.parse_args()
    fetch(args.dir, sources=args.sources)


if __name__ == "__main__":
    main()
