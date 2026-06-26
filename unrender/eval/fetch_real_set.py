"""Source a real-chart eval set from FRED + OWID — run on a machine WITH internet.

Why this exists: the real chart IMAGE and its EXACT values both have to be real.
FRED and OWID each serve, at parallel URLs, the rendered chart PNG *and* the
official data CSV for the same series — so we download both and read the ground
truth straight out of the published CSV. The values are never estimated off the
pixels (that would make the benchmark measure a guess), and nothing is typed by
hand. All charts here are LINE time series with values NOT printed on the chart
(`labels_shown=False`) — i.e. the label-free "measure it off the axis" case the
thesis turns on. (Add bar/pie charts of your own for full type coverage.)

    python -m unrender.eval.fetch_real_set                 # -> data/real_v0/{images,labels}
    python -m unrender.eval.build_real_set --dir data/real_v0   # then build rows

Downloads via curl (robust on macOS; follows redirects). If a PNG comes back as
HTML (a bad slug/param), it's reported and skipped rather than written as a fake.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

from unrender.eval.build_real_set import label_to_chartdata  # validate before writing

# --- curated sources -------------------------------------------------------
# FRED: annual average (fq=Annual&fam=avg) over a date range, so each line has a
# readable ~8-12 yearly points across a spread of value scales (rates ~0-8%,
# indices, $-billions, thousands-of-jobs — good magnitude diversity).
_FRED_RANGE = ("2013-01-01", "2023-01-01")
FRED = [
    # (out_id,            series, title,                              y_label,                 y_unit)
    ("fred_unrate",       "UNRATE",      "US Unemployment Rate",            "Unemployment Rate",        "%"),
    ("fred_fedfunds",     "FEDFUNDS",    "US Federal Funds Effective Rate", "Rate",                     "%"),
    ("fred_dgs10",        "DGS10",       "US 10-Year Treasury Yield",       "Yield",                    "%"),
    ("fred_mortgage30",   "MORTGAGE30US","US 30-Year Fixed Mortgage Rate",  "Rate",                     "%"),
    ("fred_cpi",          "CPIAUCSL",    "US Consumer Price Index",         "CPI (1982-84=100)",        None),
    ("fred_realgdp",      "GDPC1",       "US Real GDP",                     "Real GDP",                 "Billions of chained 2017 $"),
    ("fred_payems",       "PAYEMS",      "US Nonfarm Payroll Employment",   "Employees",                "Thousands"),
    ("fred_houst",        "HOUST",       "US Housing Starts",               "Housing Starts",           "Thousands of units"),
]
# OWID: one country, a line over time. The .csv ignores URL filters (always returns
# every country) so we filter client-side by ISO code; the .png DOES honor the
# country/time/tab state, so it renders just this country's line for this window.
_OWID_COUNTRY, _OWID_LO, _OWID_HI = "USA", 2000, 2023
OWID = [
    # (out_id,           slug,                                       title,                              y_label,                      y_unit)
    ("owid_life_exp",    "life-expectancy",                          "Life Expectancy, United States",   "Life expectancy",            "years"),
    ("owid_population",  "population",                               "Population, United States",        "Population",                 "people"),
    ("owid_gdp_pc",      "gdp-per-capita-worldbank",                 "GDP per Capita, United States",    "GDP per capita",             "international-$"),
    ("owid_co2_pc",      "co-emissions-per-capita",                  "CO2 Emissions per Capita, US",     "CO2 per capita",             "tonnes"),
    ("owid_internet",    "share-of-individuals-using-the-internet",  "Internet Use, United States",      "Share using the Internet",   "%"),
    ("owid_hdi",         "human-development-index",                  "Human Development Index, US",      "HDI",                        None),
    ("owid_energy_pc",   "energy-use-per-capita",                    "Energy Use per Capita, US",        "Energy per capita",          "kWh"),
    ("owid_co2_total",   "annual-co2-emissions-per-country",         "Annual CO2 Emissions, US",         "Annual CO2 emissions",       "tonnes"),
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


def _curl(url: str) -> bytes:
    r = subprocess.run(["curl", "-sL", "--max-time", "40", url], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl failed ({r.returncode}) for {url}: {r.stderr.decode()[:200]}")
    return r.stdout


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
        "series": [{"name": series_name, "points": points}],
    }


def _fetch_one(out_id, png_url, csv_url, parse, title, y_label, y_unit, series_name, source,
               images_dir: Path, labels_dir: Path) -> str | None:
    png = _curl(png_url)
    if not _is_png(png):  # bad slug/param -> an HTML error page; don't write a fake chart
        print(f"  ! {out_id}: PNG endpoint returned non-PNG ({len(png)} bytes) — skipped. URL: {png_url}")
        return None
    points = parse(_curl(csv_url).decode("utf-8", "replace"))
    if len(points) < 3:
        print(f"  ! {out_id}: only {len(points)} data points parsed — skipped. URL: {csv_url}")
        return None
    label = make_line_label(out_id, title, y_label, y_unit, series_name, points, source)
    label_to_chartdata(label, out_id)  # validate now; fail loud on any bad value
    (images_dir / f"{out_id}.png").write_bytes(png)
    (labels_dir / f"{out_id}.json").write_text(json.dumps(label, indent=2))
    print(f"  ✓ {out_id}: {len(points)} pts  ({title})")
    return out_id


def fetch(dirpath: str = "data/real_v0") -> int:
    if shutil.which("curl") is None:
        raise SystemExit("curl not found — install it, or download the charts manually (see README).")
    root = Path(dirpath)
    images_dir, labels_dir = root / "images", root / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    print(f"FRED ({len(FRED)}):")
    for out_id, series, title, ylab, yunit in FRED:
        png_url, csv_url = _fred_urls(series)
        src = f"FRED series {series} (fred.stlouisfed.org/series/{series}); annual avg {_FRED_RANGE[0][:4]}–{_FRED_RANGE[1][:4]}"
        try:
            ok += _fetch_one(out_id, png_url, csv_url, parse_fred_csv, title, ylab, yunit, series, src,
                             images_dir, labels_dir) is not None
        except Exception as e:  # one bad source shouldn't abort the batch
            print(f"  ! {out_id}: {type(e).__name__}: {e}")
    print(f"OWID ({len(OWID)}):")
    for out_id, slug, title, ylab, yunit in OWID:
        png_url, csv_url = _owid_urls(slug)
        src = f"Our World in Data: {slug} (ourworldindata.org/grapher/{slug}), {_OWID_COUNTRY} {_OWID_LO}–{_OWID_HI}"
        try:
            ok += _fetch_one(out_id, png_url, csv_url, parse_owid_csv, title, ylab, yunit, title, src,
                             images_dir, labels_dir) is not None
        except Exception as e:
            print(f"  ! {out_id}: {type(e).__name__}: {e}")

    print(f"\nfetched {ok}/{len(FRED) + len(OWID)} charts -> {root}")
    print(f"next: python -m unrender.eval.build_real_set --dir {root}")
    return ok


def main():
    p = argparse.ArgumentParser(description="Fetch a real-chart eval set from FRED + OWID (needs internet).")
    p.add_argument("--dir", default="data/real_v0")
    fetch(p.parse_args().dir)


if __name__ == "__main__":
    main()
