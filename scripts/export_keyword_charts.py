#!/usr/bin/env python
"""Export publication-quality figures from the Keyword Analysis data.

Renders the same charts shown on the Keyword Analysis page (an overview
distribution plus one breakdown chart per selected top value) as high-resolution
300 DPI PNGs suitable for a thesis / paper.

It reuses the backend's ``analysis_service.compute`` so the numbers match the
web UI exactly. Saved views (``data/05_keyword_analysis/analysis_views.json``)
are rendered automatically; if none exist a few sensible default views are used.

Run with the project virtual environment, e.g.:

    ./.venv/bin/python scripts/export_keyword_charts.py
    ./.venv/bin/python scripts/export_keyword_charts.py --view "My view"
    ./.venv/bin/python scripts/export_keyword_charts.py --dpi 600 --chart pie

Output goes to ``data/05_keyword_analysis/figures/<view-slug>/``.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# --- make the backend importable regardless of CWD --------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend import analysis_service  # noqa: E402

FIG_DIR = PROJECT_ROOT / "data" / "05_keyword_analysis" / "figures"

# A calm, print-friendly qualitative palette (colour-blind aware, muted).
PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860",
    "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD", "#5975A4", "#B47846",
]
ACCENT = "#4C72B0"


# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #
def apply_style(dpi: int) -> None:
    plt.rcParams.update({
        "figure.dpi": dpi,
        "savefig.dpi": dpi,
        "savefig.bbox": "tight",
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial",
                             "DejaVu Sans", "sans-serif"],
        "font.size": 14,
        "axes.titlesize": 17,
        "axes.titleweight": "semibold",
        "axes.labelsize": 14,
        "axes.edgecolor": "#4A4A4A",
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": "#E6E6E6",
        "grid.linewidth": 0.8,
        "xtick.color": "#4A4A4A",
        "ytick.color": "#333333",
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "legend.fontsize": 12,
        "legend.frameon": False,
    })


def _clean_axes(ax) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", str(text)).strip().lower()
    return re.sub(r"[\s_-]+", "-", s) or "value"


# --------------------------------------------------------------------------- #
# Individual chart renderers
# --------------------------------------------------------------------------- #
def _pct(bars, total):
    return [100.0 * b["count"] / total if total else 0 for b in bars]


def hbar(ax, labels, values, *, color, value_fmt="{:.0f}", pad=0.0):
    """A single horizontal bar chart, largest value on top."""
    y = range(len(labels))
    bars = ax.barh(list(y), values, color=color, height=0.72,
                   edgecolor="white", linewidth=0.6)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()  # biggest at top
    _clean_axes(ax)
    ax.xaxis.grid(True)
    ax.yaxis.grid(False)
    vmax = max(values) if values else 1
    for rect, val in zip(bars, values):
        ax.text(rect.get_width() + vmax * 0.012,
                rect.get_y() + rect.get_height() / 2,
                value_fmt.format(val), va="center", ha="left",
                fontsize=12, color="#333333")
    ax.set_xlim(0, vmax * (1.12 + pad))
    return bars


def render_overview(result, meta, out: Path, normalize: bool) -> Path | None:
    bars = result.get("overview", {}).get("dim1_bars", [])
    if not bars:
        return None
    labels = [b["label"] for b in bars]
    total = sum(b["count"] for b in bars)
    if normalize:
        values = _pct(bars, total)
        vfmt, xlabel = "{:.1f}%", "Share of papers (%)"
    else:
        values = [b["count"] for b in bars]
        vfmt, xlabel = "{:.0f}", "Number of papers"

    h = max(2.6, 0.46 * len(labels) + 1.4)
    fig, ax = plt.subplots(figsize=(9, h))
    hbar(ax, labels, values, color=ACCENT, value_fmt=vfmt)
    ax.set_xlabel(xlabel)
    ax.set_title(f"{meta['top_name']} — distribution across {total} tag mentions",
                 loc="left", pad=12)
    fig.tight_layout()
    path = out / "00_overview.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def render_panel_bar(panel, meta, out: Path, idx: int, normalize: bool) -> Path | None:
    bars = panel["bars"]
    if not bars:
        return None
    labels = [b["label"] for b in bars]
    denom = panel.get("paper_count") or 1
    if normalize:
        values = [100.0 * b["count"] / denom for b in bars]
        vfmt, xlabel = "{:.1f}%", f"Share of {panel['value']} papers (%)"
    else:
        values = [b["count"] for b in bars]
        vfmt, xlabel = "{:.0f}", "Number of papers"

    color = PALETTE[idx % len(PALETTE)]
    h = max(2.4, 0.42 * len(labels) + 1.4)
    fig, ax = plt.subplots(figsize=(9, h))
    hbar(ax, labels, values, color=color, value_fmt=vfmt)
    ax.set_xlabel(xlabel)
    ax.set_title(f"{panel['value']}  ·  {panel['paper_count']} papers",
                 loc="left", pad=12)
    fig.text(0.01, 0.005, f"{meta['top_name']} → {meta['brk_name']}",
             fontsize=11, color="#999999", ha="left")
    fig.tight_layout()
    path = out / f"{idx + 1:02d}_{slugify(panel['value'])}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def render_panel_pie(panel, meta, out: Path, idx: int, max_slices: int = 10) -> Path | None:
    bars = sorted(panel["bars"], key=lambda b: b["count"], reverse=True)
    if not bars:
        return None
    if len(bars) > max_slices:
        head = bars[:max_slices]
        other = sum(b["count"] for b in bars[max_slices:])
        data = [(b["label"], b["count"]) for b in head] + [("Other", other)]
    else:
        data = [(b["label"], b["count"]) for b in bars]
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(data))]

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, _ = ax.pie(values, colors=colors, startangle=90,
                       counterclock=False,
                       wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.5))
    ax.axis("equal")
    total = sum(values)
    legend_labels = [f"{lab}  —  {val} ({100 * val / total:.0f}%)"
                     for lab, val in zip(labels, values)]
    ax.legend(wedges, legend_labels, loc="center left",
              bbox_to_anchor=(1.02, 0.5), fontsize=12)
    ax.set_title(f"{panel['value']}  ·  {panel['paper_count']} papers",
                 loc="center", pad=16)
    fig.tight_layout()
    path = out / f"{idx + 1:02d}_{slugify(panel['value'])}_pie.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def render_grid(result, meta, out: Path, normalize: bool, max_bars: int = 10) -> Path | None:
    """Small-multiples grid: one mini bar chart per top value on one figure."""
    panels = [p for p in result["panels"] if p["bars"]]
    if not panels:
        return None
    n = len(panels)
    ncols = 2 if n > 1 else 1
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(7.2 * ncols, 3.2 * nrows),
                             squeeze=False)
    for i, panel in enumerate(panels):
        ax = axes[i // ncols][i % ncols]
        bars = panel["bars"][:max_bars]
        labels = [b["label"] for b in bars]
        denom = panel.get("paper_count") or 1
        values = ([100.0 * b["count"] / denom for b in bars] if normalize
                  else [b["count"] for b in bars])
        hbar(ax, labels, values, color=PALETTE[i % len(PALETTE)],
             value_fmt=("{:.0f}%" if normalize else "{:.0f}"))
        ax.set_title(f"{panel['value']}  ({panel['paper_count']})",
                     loc="left", fontsize=13, pad=6)
        ax.tick_params(labelsize=11)
    # hide any unused axes
    for j in range(n, nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    fig.suptitle(f"{meta['top_name']} → {meta['brk_name']} breakdown",
                 fontsize=18, fontweight="semibold", x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path = out / "grid_small_multiples.png"
    fig.savefig(path)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def dim_name(field: str) -> str:
    for d in analysis_service.dimensions()["dimensions"]:
        if d["field"] == field:
            return d["name"]
    return field


def render_view(name: str, config: dict, *, chart: str, normalize: bool) -> list[Path]:
    result = analysis_service.compute(config)
    if not result.get("panels") and not result.get("overview"):
        print(f"  ! '{name}' produced no data (check the config); skipping")
        return []
    meta = {
        "top_name": dim_name(config["top"]["dimension"]),
        "brk_name": dim_name(config["breakdown"]["dimension"]),
    }
    out = FIG_DIR / slugify(name)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    p = render_overview(result, meta, out, normalize)
    if p:
        written.append(p)
    for i, panel in enumerate(result["panels"]):
        if chart == "pie":
            p = render_panel_pie(panel, meta, out, i)
        else:
            p = render_panel_bar(panel, meta, out, i, normalize)
        if p:
            written.append(p)
    if chart != "pie":
        p = render_grid(result, meta, out, normalize)
        if p:
            written.append(p)
    return written


def default_views() -> list[tuple[str, dict]]:
    dims = analysis_service.dimensions()["dimensions"]
    tag_dims = [d for d in dims if d["type"] == "tag"]
    views: list[tuple[str, dict]] = []
    if len(tag_dims) >= 2:
        a, b = tag_dims[0], tag_dims[1]
        cats = [c["name"] for c in a["categories"]]
        views.append((f"{a['name']} by {b['name']}", {
            "top": {"dimension": a["field"], "unit": "category", "values": cats},
            "breakdown": {"dimension": b["field"], "unit": "category"},
            "options": {"normalize": False, "min_count": 2},
        }))
    if tag_dims:
        a = tag_dims[0]
        cats = [c["name"] for c in a["categories"]]
        views.append((f"{a['name']} by Year", {
            "top": {"dimension": a["field"], "unit": "category", "values": cats},
            "breakdown": {"dimension": "year", "unit": "year"},
            "options": {"normalize": False, "min_count": 1},
        }))
    return views


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--view", help="Render only the saved view with this name or id")
    ap.add_argument("--chart", choices=["bar", "pie"], default="bar",
                    help="Per-value chart type (default: bar)")
    ap.add_argument("--normalize", action="store_true",
                    help="Show percentages instead of raw counts")
    ap.add_argument("--dpi", type=int, default=300, help="Output DPI (default: 300)")
    args = ap.parse_args()

    apply_style(args.dpi)

    saved = analysis_service.list_views()
    if args.view:
        saved = [v for v in saved
                 if v["id"] == args.view or v["name"].lower() == args.view.lower()]
        if not saved:
            sys.exit(f"No saved view matching '{args.view}'.")
        views = [(v["name"], v["config"]) for v in saved]
    elif saved:
        views = [(v["name"], v["config"]) for v in saved]
        print(f"Rendering {len(views)} saved view(s).")
    else:
        views = default_views()
        print(f"No saved views found; rendering {len(views)} default view(s).")

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, config in views:
        # honour a chart type stored in the view, else the CLI default
        chart = (config.get("chart") if isinstance(config, dict) else None) or args.chart
        normalize = args.normalize or bool(config.get("options", {}).get("normalize"))
        print(f"• {name}")
        files = render_view(name, config, chart=chart, normalize=normalize)
        for f in files:
            print(f"   ✓ {f.relative_to(PROJECT_ROOT)}")
        total += len(files)

    print(f"\nDone — {total} figure(s) written under "
          f"{FIG_DIR.relative_to(PROJECT_ROOT)}/ at {args.dpi} DPI.")


if __name__ == "__main__":
    main()
