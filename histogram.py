#!/usr/bin/env python3
"""
histogram.py  –  Professional-quality histogram of a CSV column.

GUI mode  : python histogram.py                       (no arguments)
CLI mode  : python histogram.py <column> <csvfile> [options]

CLI options (key=value, no spaces around =):
    t=<name>      Time column  (auto-detects "t", "time", "t[s]")
    bins=<n>      Number of bins              (default: 20)
    k=<float>     IQR multiplier for outlier removal (default: 0 = off)
    title=<str>   Title for chart and HTML report

When a time column is present each sample is weighted by its Δt duration,
so the y-axis represents "time spent in each amplitude range".
Without a time column, 1 sample/s is assumed (y-axis = count).
"""

import configparser
import csv
import os
import re
import sys

import matplotlib
matplotlib.use("Qt5Agg")
import matplotlib.backends.backend_svg  # explicit import so PyInstaller bundles it
import matplotlib.pyplot as plt
import xhtml2pdf.pisa  # explicit import so PyInstaller bundles xhtml2pdf
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

# ── constants ─────────────────────────────────────────────────────────────────

TIME_DEFAULT_NAMES = {"t", "time", "t[s]"}
AUTO_DETECT_LABEL  = "(auto-detect)"
NONE_LABEL         = "(none)"

APP_VERSION = "1.4.3"
GITHUB_REPO = "marzzelo/histogrammer"


def _version_tuple(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)

# ── CSV helpers ───────────────────────────────────────────────────────────────


def detect_separator(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = "".join(f.readline() for _ in range(5))
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t |")
        return dialect.delimiter
    except csv.Error:
        return ","


def load_csv(path):
    sep = detect_separator(path)
    df  = pd.read_csv(path, sep=sep, engine="python")
    df.columns = df.columns.str.strip()
    return df


def find_time_col(columns):
    for c in columns:
        if c.strip().lower() in TIME_DEFAULT_NAMES:
            return c
    return None


# ── outlier removal ───────────────────────────────────────────────────────────


def remove_outliers(values, weights, k):
    """Remove samples outside [Q1 - k*IQR, Q3 + k*IQR]. k=0 -> no filtering."""
    if k <= 0:
        return values, weights
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    mask = (values >= lo) & (values <= hi)
    removed = int(np.sum(~mask))
    if removed:
        print(f"  Outlier removal (k={k}): [{lo:.5g}, {hi:.5g}]  -> {removed} sample(s) removed")
    return values[mask], weights[mask]


# ── weighting ─────────────────────────────────────────────────────────────────


def time_weights(df, time_col):
    t = df[time_col].values.astype(float)
    if len(t) < 2:
        return np.ones(len(t))
    dt = np.empty(len(t))
    dt[:-1] = np.diff(t)
    dt[-1]  = dt[-2]
    return np.abs(dt)


# ── formatting ────────────────────────────────────────────────────────────────


def seconds_to_hhmmss(s):
    s = abs(float(s))
    h   = int(s // 3600)
    m   = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


def safe_col_name(col):
    for ch in (" ", "/", "[", "]"):
        col = col.replace(ch, {"[": "", "]": "", " ": "_", "/": "-"}[ch])
    return col


# ── percentile / error chart ──────────────────────────────────────────────────


def build_percentile_chart(values, target, out_stem, save_png=True):
    """Generate CDF-style chart and decile table for |( y(t)-target )*100/target|."""
    e_pct = np.abs((values - target) / target * 100)

    x_ranks  = np.linspace(0, 100, min(600, len(e_pct)))
    y_errors = np.percentile(e_pct, x_ranks)

    decile_pcts = np.arange(0, 101, 10)          # P0, P10, …, P100
    decile_vals = np.percentile(e_pct, decile_pcts)

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(PALETTE["fig_bg"])
    ax.set_facecolor("#FFFFFF")

    ax.fill_between(x_ranks, 0, y_errors, alpha=0.12, color=PALETTE["bar"], zorder=2)
    ax.plot(x_ranks, y_errors, color=PALETTE["bar"], linewidth=2.3, zorder=3,
            label="Percentile curve")
    ax.scatter(decile_pcts, decile_vals, color=PALETTE["bar_peak"],
               s=55, zorder=5, label="Deciles", clip_on=False)

    for p, v in zip(decile_pcts, decile_vals):
        lbl = "Min" if p == 0 else ("Max" if p == 100 else f"D{p//10}")
        ax.annotate(lbl, (p, v), textcoords="offset points",
                    xytext=(5, 3), fontsize=7.5, color=PALETTE["bar_peak"])

    ax.set_xlabel("Percentile [%]", fontsize=11, labelpad=8)
    ax.set_ylabel("| ( y(t) − target ) · 100 / target |  [%]", fontsize=10, labelpad=8)
    ax.set_xlim(-1, 101)
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.4g}%"))
    ax.grid(linestyle="--", linewidth=0.55, alpha=0.5, zorder=1)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_linewidth(0.8)
    ax.tick_params(labelsize=9)
    fig.suptitle("Percentile Distribution of Relative Error", fontsize=12,
                 fontweight="bold", y=0.995)
    ax.set_title(f"target = {target:.5g}  |  samples = {len(values)}",
                 fontsize=9, color="#7F8C8D", pad=6)
    ax.legend(fontsize=9, framealpha=0.9, edgecolor="#CCCCCC", loc="upper left")
    plt.tight_layout(pad=1.5)

    pct_svg = out_stem + "_pct.svg"
    fig.savefig(pct_svg, bbox_inches="tight")
    if save_png:
        fig.savefig(out_stem + "_pct.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Pct chart  -> {pct_svg}")
    return pct_svg, decile_vals


# ── HTML report ───────────────────────────────────────────────────────────────


DEFAULT_SHOW_COLS = {"time_s": True, "time_hms": True, "pct": True, "count": True}


def build_html_report(
    col, csv_path, title, time_source, y_label,
    edges, counts, weights, values,
    w_mean, w_std, p25, p50, p75, v_min, v_max,
    total_weight, nbins, k, n_removed, chart_path,
    show_cols=None, target=None,
    pct_chart_path=None, deciles=None,
):
    def _inline_svg(path):
        """Return the bare <svg>…</svg> content of a file for inline embedding."""
        if not (path and os.path.isfile(path)):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        m = re.search(r"<svg\b", raw, re.IGNORECASE)
        return raw[m.start():] if m else raw

    sc           = {**DEFAULT_SHOW_COLS, **(show_cols or {})}
    n_samples    = len(values)
    raw_counts,_ = np.histogram(values, bins=edges)
    report_title = title or f"Histogram — {col}"
    file_name    = os.path.basename(csv_path)
    chart_svg    = _inline_svg(chart_path)
    has_time     = y_label == "Time [s]"
    peak_idx     = int(np.argmax(counts))

    outlier_note = (
        f'&nbsp;|&nbsp; Outlier filter: <strong>k={k}</strong> '
        f'({n_removed} sample{"s" if n_removed != 1 else ""} removed)'
    ) if k > 0 else ""

    # ── determine visible optional columns ────────────────────────────────────
    # Time group: [s], [hh:mm:ss], % — only available when has_time
    # Samples group: Count
    # Single % column: shows time-weighted % if has_time, else count %
    t_cols = []
    if has_time and sc["time_s"]:   t_cols.append("time_s")
    if has_time and sc["time_hms"]: t_cols.append("time_hms")
    if sc["pct"]:                   t_cols.append("pct")
    s_cols = []
    if sc["count"]:                 s_cols.append("count")

    # ── dynamic header ────────────────────────────────────────────────────────
    grp_row = '<th rowspan="2">#</th><th rowspan="2">Bin range</th>'
    sub_row = ""
    if t_cols:
        grp_label = "Time" if has_time else "Distribution"
        grp_row  += f'<th colspan="{len(t_cols)}" class="grp">{grp_label}</th>'
        for c in t_cols:
            sub_row += {"time_s": "<th>[s]</th>",
                        "time_hms": "<th>[hh:mm:ss]</th>",
                        "pct": "<th>%</th>"}[c]
    if s_cols:
        grp_row += f'<th colspan="{len(s_cols)}" class="grp">Samples</th>'
        for c in s_cols:
            sub_row += {"count": "<th>Count</th>"}[c]

    # ── data rows ─────────────────────────────────────────────────────────────
    def bar_cell(pct, fill_cls):
        return (
            f'<td class="num"><div class="bar-wrap">'
            f'<span class="bar-fill {fill_cls}" style="width:{pct:.1f}%"></span>'
            f'<span class="bar-lbl">{pct:.2f}%</span></div></td>'
        )

    rows = []
    for i, (lo, hi, w, n) in enumerate(zip(edges[:-1], edges[1:], counts, raw_counts)):
        pct_t = 100.0 * w / total_weight if total_weight else 0.0
        pct_s = 100.0 * n / n_samples   if n_samples   else 0.0
        cls   = (' class="peak-row"' if i == peak_idx
                 else (' class="even-row"' if i % 2 == 0 else ""))
        cells = f'<td class="num">{i+1}</td><td class="num">[{lo:.5g},&nbsp;{hi:.5g})</td>'
        for c in t_cols:
            if   c == "time_s":  cells += f'<td class="num">{w:,.2f}</td>'
            elif c == "time_hms":cells += f'<td class="num">{seconds_to_hhmmss(w)}</td>'
            elif c == "pct":     cells += bar_cell(pct_t if has_time else pct_s, "t")
        for c in s_cols:
            if c == "count": cells += f'<td class="num">{n}</td>'
        rows.append(f'<tr{cls}>{cells}</tr>')

    # totals row
    tot_cells = '<td class="num tot" colspan="2">TOTAL</td>'
    for c in t_cols:
        if   c == "time_s":  tot_cells += f'<td class="num tot">{total_weight:,.2f}</td>'
        elif c == "time_hms":tot_cells += f'<td class="num tot">{seconds_to_hhmmss(total_weight)}</td>'
        elif c == "pct":     tot_cells += '<td class="num tot">100.00%</td>'
    for c in s_cols:
        if c == "count": tot_cells += f'<td class="num tot">{n_samples}</td>'
    rows.append(f'<tr class="tot-row">{tot_cells}</tr>')

    # ── stat cards ────────────────────────────────────────────────────────────
    time_card = (
        f'<div class="card" style="border-left:4px solid #1A5276">'
        f'<div class="lbl">Total time</div>'
        f'<div class="val" style="color:#1A5276">{seconds_to_hhmmss(total_weight)}</div></div>'
    ) if has_time else ""
    outlier_card = (
        f'<div class="card" style="border-left:4px solid #D35400">'
        f'<div class="lbl">Outliers removed</div>'
        f'<div class="val" style="color:#D35400">{n_removed}</div></div>'
    ) if k > 0 else ""
    target_card = (
        f'<div class="card" style="border-left:4px solid #8E44AD">'
        f'<div class="lbl">Target</div>'
        f'<div class="val" style="color:#8E44AD">{target:.5g}</div></div>'
    ) if target is not None else ""

    # ── percentile / decile section ───────────────────────────────────────────
    if pct_chart_path and deciles is not None:
        pct_chart_svg = _inline_svg(pct_chart_path)
        dlabels = (["Min (P0)"]
                   + [f"D{i} &nbsp;(P{i*10})" for i in range(1, 10)]
                   + ["Max (P100)"])
        d_rows_list = []
        for i, (lbl, val) in enumerate(zip(dlabels, deciles)):
            cls = "" if i % 2 else ' class="even-row"'
            d_rows_list.append(
                f'<tr{cls}><td class="num">{lbl}</td>'
                f'<td class="pct-d">{val:.5g}%</td></tr>'
            )
        d_rows = "".join(d_rows_list)
        pct_section = f"""
<h2 class="sec-title">Relative Error Analysis &nbsp;&mdash;&nbsp; | (y(t) &minus; target) &middot; 100 / target |</h2>
<div class="chart-wrap">{pct_chart_svg}</div>
<table style="max-width:480px;margin-bottom:1.8rem">
  <thead>
    <tr>
      <th style="width:170px">Decile</th>
      <th>Error&nbsp;&nbsp;|&thinsp;(y(t)&thinsp;&minus;&thinsp;target)&thinsp;&middot;&thinsp;100&thinsp;/&thinsp;target&thinsp;|&nbsp;&nbsp;[%]</th>
    </tr>
  </thead>
  <tbody>{d_rows}</tbody>
</table>"""
    else:
        pct_section = ""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>{report_title}</title>
<style>
:root{{--B:#2E86AB;--BD:#1A5276;--R:#E74C3C;--T:#1ABC9C;--bg:#F5F8FA;
      --card:#FFF;--tx:#1C2833;--mu:#5D6D7E;--br:#D5D8DC}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--tx);padding:2rem}}
header{{border-left:6px solid var(--B);padding:.6rem 1.2rem;margin-bottom:1.6rem;
        background:var(--card);box-shadow:0 1px 4px rgba(0,0,0,.08);border-radius:0 6px 6px 0}}
header h1{{font-size:1.5rem;color:var(--BD)}}
header p{{font-size:.82rem;color:var(--mu);margin-top:.25rem}}
.cards{{display:flex;flex-wrap:wrap;gap:.9rem;margin-bottom:1.8rem}}
.card{{background:var(--card);border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.08);
       padding:.9rem 1.3rem;min-width:130px;flex:1}}
.lbl{{font-size:.72rem;color:var(--mu);text-transform:uppercase;letter-spacing:.06em}}
.val{{font-size:1.25rem;font-weight:700;color:var(--BD);margin-top:.2rem}}
.chart-wrap{{background:var(--card);border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.08);
             padding:1rem;margin-bottom:1.8rem;text-align:center}}
.chart-wrap img{{max-width:100%;border-radius:4px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:8px;
       overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);font-size:.86rem}}
thead th{{background:var(--BD);color:#fff;padding:.65rem .8rem;text-align:center;
          font-size:.78rem;letter-spacing:.04em;white-space:nowrap}}
thead th.grp{{background:var(--B);font-size:.72rem;padding:.4rem .8rem}}
td{{padding:.45rem .8rem;vertical-align:middle;border-bottom:1px solid var(--br)}}
td.num{{text-align:right;font-family:Consolas,monospace}}
tr.even-row{{background:#F2F6FA}}
tr.peak-row{{background:#FDEDEC}}
tr.peak-row td{{color:var(--R);font-weight:600}}
tr.tot-row{{background:#EBF5FB}}
td.tot{{font-weight:700;color:var(--BD)}}
.bar-wrap{{position:relative;background:#E8EDF2;border-radius:3px;height:18px;
           min-width:80px;overflow:hidden;display:flex;align-items:center}}
.bar-fill{{position:absolute;left:0;top:0;bottom:0;border-radius:3px;opacity:.35}}
.bar-fill.t{{background:var(--B)}}
.bar-lbl{{position:relative;z-index:1;font-size:.78rem;font-weight:600;
          color:var(--tx);padding-left:6px}}
footer{{text-align:center;margin-top:2rem;font-size:.75rem;color:var(--mu);line-height:1.8}}
footer a{{color:var(--mu);text-decoration:none}}
footer a:hover{{text-decoration:underline}}
.sec-title{{font-size:1.05rem;font-weight:700;color:var(--BD);
            margin:2.4rem 0 1rem;padding:.35rem .9rem;
            border-left:4px solid var(--B);background:var(--card);
            border-radius:0 4px 4px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
td.pct-d{{text-align:right;font-family:Consolas,monospace;color:#8E44AD;font-weight:600}}
</style>
</head>
<body>
<header>
  <h1>{report_title}</h1>
  <p>File: <strong>{file_name}</strong> &nbsp;|&nbsp; Column: <strong>{col}</strong>
     &nbsp;|&nbsp; Bins: <strong>{nbins}</strong>
     &nbsp;|&nbsp; Time: <strong>{time_source}</strong>{outlier_note}</p>
</header>
<div class="chart-wrap">{chart_svg}</div>
<table>
  <thead>
    <tr>{grp_row}</tr>
    <tr>{sub_row}</tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<div class="cards" style="margin-top:1.8rem">
  <div class="card" style="border-left:4px solid #2E86AB"><div class="lbl">Samples</div><div class="val" style="color:#2E86AB">{n_samples}</div></div>
  <div class="card" style="border-left:4px solid #1ABC9C"><div class="lbl">Min</div><div class="val" style="color:#1ABC9C">{v_min:.5g}</div></div>
  <div class="card" style="border-left:4px solid #E74C3C"><div class="lbl">Max</div><div class="val" style="color:#E74C3C">{v_max:.5g}</div></div>
  <div class="card" style="border-left:4px solid #F39C12"><div class="lbl">Mean</div><div class="val" style="color:#F39C12">{w_mean:.5g}</div></div>
  <div class="card" style="border-left:4px solid #E67E22"><div class="lbl">Std dev</div><div class="val" style="color:#E67E22">{w_std:.5g}</div></div>
  <div class="card" style="border-left:4px solid #27AE60"><div class="lbl">Median (P50)</div><div class="val" style="color:#27AE60">{p50:.5g}</div></div>
  <div class="card" style="border-left:4px solid #16A085"><div class="lbl">P25 / P75</div><div class="val" style="color:#16A085">{p25:.4g} / {p75:.4g}</div></div>
  {time_card}{outlier_card}{target_card}
</div>
{pct_section}
<footer>
  Generated by histogram.py &nbsp;·&nbsp; {file_name} &nbsp;·&nbsp; Experimental - FAdeA<br>
  bugs: report to <a href="mailto:mvaldez@fadeasa.com.ar">Eng. Marcelo Valdez</a>
</footer>
</body>
</html>"""


# ── core histogram engine ─────────────────────────────────────────────────────

PALETTE = {
    "bar":         "#2E86AB", "bar_edge":   "#1A5276",
    "bar_peak":    "#E74C3C", "peak_edge":  "#922B21",
    "mean_line":   "#F39C12", "kde_line":   "#1ABC9C",
    "target_line": "#8E44AD",
    "stats_bg":    "#EBF5FB", "stats_edge": "#2E86AB",
    "fig_bg":      "#F5F5F5",
}


def make_histogram(col, csv_path, time_col_arg, nbins, title, k=0.0, show_cols=None, out_name=None, target=None, save_png=True, show_plot=True):
    """Core engine — called by both CLI and GUI paths."""
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"File not found: {csv_path}")

    df = load_csv(csv_path)

    if col not in df.columns:
        raise ValueError(
            f"Column {col!r} not found.\nAvailable: {list(df.columns)}"
        )

    # ── time column ───────────────────────────────────────────────────────────
    if time_col_arg and time_col_arg not in (AUTO_DETECT_LABEL, NONE_LABEL):
        if time_col_arg not in df.columns:
            raise ValueError(
                f"Time column {time_col_arg!r} not found.\n"
                f"Available: {list(df.columns)}"
            )
        time_col    = time_col_arg
        time_source = f'"{time_col}" (user-specified)'
    elif time_col_arg == NONE_LABEL:
        time_col    = None
        time_source = "disabled by user"
    else:
        time_col    = find_time_col(df.columns)
        time_source = f'"{time_col}" (auto-detected)' if time_col else "uniform — 1 sample/s assumed"

    # ── data & weights ────────────────────────────────────────────────────────
    valid_mask = df[col].notna()
    values     = df.loc[valid_mask, col].values.astype(float)

    if time_col:
        weights = time_weights(df[valid_mask], time_col)
        y_label = "Time [s]"
    else:
        weights = np.ones(len(values))
        y_label = "Count"

    # ── outlier removal ───────────────────────────────────────────────────────
    n_before  = len(values)
    values, weights = remove_outliers(values, weights, k)
    n_removed = n_before - len(values)

    if len(values) == 0:
        raise ValueError("No data remaining after outlier removal. Lower k.")

    # ── statistics ────────────────────────────────────────────────────────────
    total_weight = weights.sum()
    w_mean = np.average(values, weights=weights)
    w_var  = np.average((values - w_mean) ** 2, weights=weights)
    w_std  = np.sqrt(w_var)
    p25, p50, p75 = np.percentile(values, [25, 50, 75])
    v_min, v_max  = values.min(), values.max()

    # ── histogram ─────────────────────────────────────────────────────────────
    counts, edges = np.histogram(values, bins=nbins, weights=weights)
    centers   = 0.5 * (edges[:-1] + edges[1:])
    bin_width = edges[1] - edges[0]

    # ── chart title ───────────────────────────────────────────────────────────
    k_note = f"   |   Outlier k={k}" if k > 0 else ""
    if title:
        main_title = title
        sub_title  = (
            f"File: {os.path.basename(csv_path)}   |   Column: {col}"
            f"   |   Time: {time_source}{k_note}"
        )
    else:
        main_title = f"Histogram  —  {col}"
        sub_title  = (
            f"File: {os.path.basename(csv_path)}   |   Time: {time_source}{k_note}"
        )

    # ── figure ────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(11, 6.5))
    fig.patch.set_facecolor(PALETTE["fig_bg"])
    ax.set_facecolor("#FFFFFF")

    bars = ax.bar(
        centers, counts, width=bin_width * 0.90,
        color=PALETTE["bar"], edgecolor=PALETTE["bar_edge"],
        linewidth=0.7, zorder=3, label=f"Histogram ({nbins} bins)",
    )
    peak_idx = int(np.argmax(counts))
    bars[peak_idx].set_facecolor(PALETTE["bar_peak"])
    bars[peak_idx].set_edgecolor(PALETTE["peak_edge"])

    ax.axvline(w_mean, color=PALETTE["mean_line"], linewidth=2.0,
               linestyle="--", zorder=4, label=f"Mean = {w_mean:.5g}")
    ax.axvline(w_mean + w_std, color=PALETTE["mean_line"], linewidth=1.2,
               linestyle=":", alpha=0.85, zorder=4, label=f"±1σ = {w_std:.5g}")
    ax.axvline(w_mean - w_std, color=PALETTE["mean_line"], linewidth=1.2,
               linestyle=":", alpha=0.85, zorder=4)
    if target is not None:
        ax.axvline(target, color=PALETTE["target_line"], linewidth=2.2,
                   linestyle="-.", zorder=4, label=f"Target = {target:.5g}")

    if len(np.unique(values)) > 1:
        kde   = gaussian_kde(values, weights=weights, bw_method="scott")
        x_kde = np.linspace(v_min, v_max, 500)
        ax.plot(x_kde, kde(x_kde) * total_weight * bin_width,
                color=PALETTE["kde_line"], linewidth=2.2, zorder=5, label="KDE density")

    ax.set_xlabel(col, fontsize=12, labelpad=8)
    ax.set_ylabel(y_label, fontsize=12, labelpad=8)
    fig.suptitle(main_title, fontsize=13, fontweight="bold", y=0.995)
    ax.set_title(sub_title, fontsize=9, color="#7F8C8D", pad=6)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.1f}"))
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter("%.5g"))
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.55, zorder=1)
    ax.grid(axis="x", linestyle=":",  linewidth=0.5, alpha=0.35, zorder=1)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_linewidth(0.8)
    ax.tick_params(labelsize=9)

    total_label = "Total s" if time_col else "Total"

    def sl(label, val):
        """Fixed-width stat line: label right-aligned (7) + value right-aligned (11)."""
        return f"{label:>7} : {val:>11}"

    removed_line = [sl("Removed", str(n_removed))] if k > 0 else []
    target_line  = [sl("Target",  f"{target:.5g}")] if target is not None else []
    stats_lines = [
        sl("Samples", str(len(values))),
        *removed_line,
        sl("Min",     f"{v_min:.5g}"),
        sl("Max",     f"{v_max:.5g}"),
        sl("Mean",    f"{w_mean:.5g}"),
        *target_line,
        sl("Std dev", f"{w_std:.5g}"),
        sl("P25",     f"{p25:.5g}"),
        sl("Median",  f"{p50:.5g}"),
        sl("P75",     f"{p75:.5g}"),
        sl(total_label, f"{total_weight:.5g}"),
    ]
    ax.text(
        0.977, 0.975, "\n".join(stats_lines),
        transform=ax.transAxes, fontsize=8.5,
        verticalalignment="top", horizontalalignment="right",
        family="monospace",
        bbox=dict(boxstyle="round,pad=0.55",
                  facecolor=PALETTE["stats_bg"], edgecolor=PALETTE["stats_edge"],
                  linewidth=1.0, alpha=0.92),
        zorder=6,
    )
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9, edgecolor="#CCCCCC")
    plt.tight_layout(pad=1.5)

    # ── outputs ───────────────────────────────────────────────────────────────
    if out_name:
        base     = os.path.splitext(out_name)[0]   # strip extension if user added one
        out_stem = os.path.join(os.path.dirname(csv_path), base)
    else:
        out_stem = os.path.splitext(csv_path)[0] + "_hist_" + safe_col_name(col)
    svg_path  = out_stem + ".svg"
    html_path = out_stem + ".html"

    fig.savefig(svg_path, bbox_inches="tight")
    if save_png:
        fig.savefig(out_stem + ".png", dpi=150, bbox_inches="tight")
    print(f"Chart saved  -> {svg_path}")

    pct_chart_path, deciles = (
        build_percentile_chart(values, target, out_stem, save_png=save_png)
        if target is not None else (None, None)
    )

    html = build_html_report(
        col, csv_path, title, time_source, y_label,
        edges, counts, weights, values,
        w_mean, w_std, p25, p50, p75, v_min, v_max,
        total_weight, nbins, k, n_removed, svg_path,
        show_cols=show_cols, target=target,
        pct_chart_path=pct_chart_path, deciles=deciles,
    )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report saved -> {html_path}")

    if show_plot:
        plt.show()
    else:
        plt.close()
    return svg_path, html_path


# ── PDF export ────────────────────────────────────────────────────────────────


def html_to_pdf(html_path):
    """Convert HTML report to PDF (via xhtml2pdf) and open with system viewer."""
    import base64
    import re

    try:
        from xhtml2pdf import pisa
    except ImportError:
        raise ImportError("xhtml2pdf not installed. Run: pip install xhtml2pdf")

    pdf_path = os.path.splitext(html_path)[0] + ".pdf"
    html_dir = os.path.dirname(os.path.abspath(html_path))

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # xhtml2pdf does not support CSS custom properties — expand them first
    root_m = re.search(r':root\{([^}]+)\}', html, re.DOTALL)
    if root_m:
        css_vars = {}
        for m in re.finditer(r'--([\w-]+)\s*:\s*([^;,}]+)', root_m.group(1)):
            css_vars[m.group(1).strip()] = m.group(2).strip()
        html = re.sub(
            r'var\(--([\w-]+)\)',
            lambda m: css_vars.get(m.group(1), m.group(0)),
            html,
        )

    # Replace inline SVG blocks with companion PNG (xhtml2pdf cannot render SVG)
    out_stem    = os.path.splitext(os.path.abspath(html_path))[0]
    png_paths   = [out_stem + ".png", out_stem + "_pct.png"]
    svg_counter = [0]

    def _svg_to_png(m):
        idx = svg_counter[0]
        svg_counter[0] += 1
        if idx < len(png_paths) and os.path.isfile(png_paths[idx]):
            with open(png_paths[idx], "rb") as f:
                data = base64.b64encode(f.read()).decode()
            return f'<img src="data:image/png;base64,{data}" style="max-width:100%">'
        return ""

    html = re.sub(r"<svg\b[^>]*>.*?</svg>", _svg_to_png, html,
                  flags=re.DOTALL | re.IGNORECASE)

    with open(pdf_path, "wb") as out:
        result = pisa.CreatePDF(html, dest=out, encoding="utf-8")

    if result.err:
        raise RuntimeError(f"PDF generation failed ({result.err} error(s)).")

    os.startfile(pdf_path)
    return pdf_path


# ── GUI ───────────────────────────────────────────────────────────────────────


def run_gui():
    import webbrowser

    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QFormLayout, QLabel, QLineEdit, QPushButton, QComboBox,
        QSpinBox, QDoubleSpinBox, QFileDialog, QFrame, QCheckBox, QDialog,
        QMessageBox, QProgressDialog,
    )
    from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
    from PyQt5.QtGui import QFont, QIcon

    CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
    CONFIG_SEC  = "last"

    def _resource_path(rel):
        """Resolve a bundled resource both when running from source and when
        frozen by PyInstaller (which unpacks data files under sys._MEIPASS)."""
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, rel)

    APP_ICON_PATH = _resource_path("histogram_icon.ico")

    def _load_cfg():
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_PATH, encoding="utf-8")
        return cfg[CONFIG_SEC] if cfg.has_section(CONFIG_SEC) else {}

    def _save_cfg(values: dict):
        cfg = configparser.ConfigParser()
        cfg[CONFIG_SEC] = {k: str(v) for k, v in values.items()}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)

    # ── auto-update threads ───────────────────────────────────────────────────

    class UpdaterThread(QThread):
        update_available = pyqtSignal(str, str)  # (new_version, download_url)
        check_error      = pyqtSignal(str)        # error description

        def run(self):
            import json
            import urllib.request
            import urllib.error
            try:
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=1",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": f"HistogramFAdeA/{APP_VERSION}",
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    releases = json.loads(resp.read().decode())
                if not releases:
                    print("[Updater] No releases found on GitHub.")
                    return
                release = releases[0]
                tag    = release.get("tag_name", "").lstrip("v")
                assets = release.get("assets", [])
                print(f"[Updater] tag={tag!r}  assets={len(assets)}  local={APP_VERSION!r}")
                if tag and assets and _version_tuple(tag) > _version_tuple(APP_VERSION):
                    self.update_available.emit(tag, assets[0]["browser_download_url"])
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                print(f"[Updater] ERROR: {msg}", file=sys.stderr)
                self.check_error.emit(msg)

    class DownloadThread(QThread):
        progress = pyqtSignal(int)   # 0-100
        finished = pyqtSignal(str)   # path to downloaded file
        error    = pyqtSignal(str)

        def __init__(self, url, dest_path):
            super().__init__()
            self._url  = url
            self._dest = dest_path

        def run(self):
            import urllib.request
            try:
                req = urllib.request.Request(
                    self._url,
                    headers={"User-Agent": f"HistogramFAdeA/{APP_VERSION}"},
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    total      = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    with open(self._dest, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                self.progress.emit(int(downloaded * 100 / total))
                self.finished.emit(self._dest)
            except Exception as exc:
                self.error.emit(str(exc))

    # ── splash / info dialog ─────────────────────────────────────────────────

    class SplashDialog(QDialog):
        def __init__(self, parent=None, auto_close=False):
            super().__init__(parent, Qt.FramelessWindowHint)
            self.setModal(True)
            self._build_ui()
            # Size to the content's natural width so the large title never
            # clips, regardless of font rendering or display scale factor.
            self.adjustSize()
            self.setFixedSize(max(self.width(), 500), max(self.height(), 330))
            self._center(parent)
            if auto_close:
                QTimer.singleShot(3000, self.accept)

        def _center(self, parent):
            if parent and parent.isVisible():
                geo = parent.frameGeometry()
                self.move(
                    geo.x() + (geo.width()  - self.width())  // 2,
                    geo.y() + (geo.height() - self.height()) // 2,
                )
            else:
                rect = QApplication.primaryScreen().geometry()
                self.move(
                    (rect.width()  - self.width())  // 2,
                    (rect.height() - self.height()) // 2,
                )

        def _build_ui(self):
            self.setStyleSheet("""
                QDialog { background: #1B2A3B; border: 2px solid #2E86AB; }
                QLabel  { background: transparent; }
            """)
            vbox = QVBoxLayout(self)
            vbox.setContentsMargins(48, 34, 48, 24)
            vbox.setSpacing(0)

            lbl_product = QLabel("Histogrammer")
            lbl_product.setStyleSheet(
                "font-family:'Segoe UI'; font-size:38pt; font-weight:bold; color:#FFFFFF;"
            )
            lbl_product.setAlignment(Qt.AlignCenter)
            vbox.addWidget(lbl_product)

            vbox.addSpacing(3)

            lbl_org = QLabel("F  A  d  e  A")
            lbl_org.setStyleSheet(
                "font-family:'Segoe UI'; font-size:18pt; color:#2E86AB;"
            )
            lbl_org.setAlignment(Qt.AlignCenter)
            vbox.addWidget(lbl_org)

            vbox.addSpacing(18)

            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("border: 1px solid #2E6490;")
            vbox.addWidget(sep)

            vbox.addSpacing(18)

            lbl_desc = QLabel(
                "Statistical histogram generator for CSV data.\n"
                "Outlier detection  ·  Time-series support\n"
                "HTML and PDF report export."
            )
            lbl_desc.setStyleSheet(
                "font-family:'Segoe UI'; font-size:10pt; color:#A9CCE3;"
            )
            lbl_desc.setAlignment(Qt.AlignCenter)
            vbox.addWidget(lbl_desc)

            vbox.addSpacing(20)

            lbl_author = QLabel(f"Eng. Marcelo Valdez  ·  v{APP_VERSION}")
            lbl_author.setStyleSheet(
                "font-family:'Segoe UI'; font-size:9pt; color:#5D8AA8;"
            )
            lbl_author.setAlignment(Qt.AlignCenter)
            vbox.addWidget(lbl_author)

            vbox.addSpacing(10)

            lbl_hint = QLabel("click anywhere or press any key to continue")
            lbl_hint.setStyleSheet(
                "font-family:'Segoe UI'; font-size:8pt; color:#FFD700;"
            )
            lbl_hint.setAlignment(Qt.AlignCenter)
            vbox.addWidget(lbl_hint)

        def mousePressEvent(self, _event):
            self.accept()

        def keyPressEvent(self, _event):
            self.accept()

    # ── main window ───────────────────────────────────────────────────────────

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"FAdeA — Histogram Generator  v{APP_VERSION}")
            if os.path.exists(APP_ICON_PATH):
                self.setWindowIcon(QIcon(APP_ICON_PATH))
            self.setMinimumWidth(580)
            self._last_html = None
            self._build_ui()
            self._restore_config()

        def _build_ui(self):
            root = QWidget()
            self.setCentralWidget(root)
            outer = QVBoxLayout(root)
            outer.setContentsMargins(20, 20, 20, 16)
            outer.setSpacing(14)

            # ── header ────────────────────────────────────────────────────────
            hdr = QLabel(f"Histogram Generator  <span style='font-size:16px; font-weight:normal; color:#5D6D7E;'>v{APP_VERSION}</span>")
            hdr.setFont(QFont("Segoe UI", 28, QFont.Bold))
            hdr.setStyleSheet("color:#1A5276;")
            outer.addWidget(hdr)

            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setStyleSheet("color:#D5D8DC;")
            outer.addWidget(line)

            # ── form ──────────────────────────────────────────────────────────
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight)
            form.setSpacing(10)
            outer.addLayout(form)

            # file row
            file_row = QHBoxLayout()
            self.w_file = QLineEdit()
            self.w_file.setPlaceholderText("Select a CSV file…")
            self.w_file.textChanged.connect(self._on_file_changed)
            btn_browse = QPushButton("Browse…")
            btn_browse.setFixedWidth(80)
            btn_browse.clicked.connect(self._browse)
            file_row.addWidget(self.w_file)
            file_row.addWidget(btn_browse)
            form.addRow("Input file:", file_row)

            # column
            self.w_col = QComboBox()
            self.w_col.setEnabled(False)
            form.addRow("Column:", self.w_col)

            # time column
            self.w_time = QComboBox()
            self.w_time.setEnabled(False)
            form.addRow("Time column:", self.w_time)

            # bins
            self.w_bins = QSpinBox()
            self.w_bins.setRange(2, 500)
            self.w_bins.setValue(20)
            self.w_bins.setFixedWidth(80)
            form.addRow("Bins:", self.w_bins)

            # k (IQR)
            k_row = QHBoxLayout()
            self.w_k = QDoubleSpinBox()
            self.w_k.setRange(0.0, 20.0)
            self.w_k.setSingleStep(0.5)
            self.w_k.setDecimals(2)
            self.w_k.setValue(0.0)
            self.w_k.setFixedWidth(80)
            k_note = QLabel("  0 = disabled   (typical: 1.5 mild · 3.0 extreme)")
            k_note.setStyleSheet("color:#5D6D7E; font-size:11px;")
            k_row.addWidget(self.w_k)
            k_row.addWidget(k_note)
            k_row.addStretch()
            form.addRow("k  (IQR outliers):", k_row)

            # title
            self.w_title = QLineEdit()
            self.w_title.setPlaceholderText("Optional chart / report title")
            form.addRow("Title:", self.w_title)

            # target value
            self.w_target = QLineEdit()
            self.w_target.setPlaceholderText("Optional — numeric reference value")
            form.addRow("Target:", self.w_target)

            # output name
            self.w_out = QLineEdit()
            self.w_out.setPlaceholderText("Optional — default: <csv>_hist_<col>.svg/.html")
            form.addRow("Output name:", self.w_out)

            # ── table column checkboxes ────────────────────────────────────────
            ck_row = QHBoxLayout()
            ck_row.setSpacing(14)
            self.ck_time_s   = QCheckBox("Time [s]")
            self.ck_time_hms = QCheckBox("[hh:mm:ss]")
            self.ck_pct      = QCheckBox("%")
            self.ck_count    = QCheckBox("Count")
            for ck in (self.ck_time_s, self.ck_time_hms, self.ck_pct, self.ck_count):
                ck.setChecked(True)
                ck_row.addWidget(ck)
            ck_row.addStretch()
            form.addRow("Table columns:", ck_row)

            # ── separator ─────────────────────────────────────────────────────
            line2 = QFrame()
            line2.setFrameShape(QFrame.HLine)
            line2.setStyleSheet("color:#D5D8DC;")
            outer.addWidget(line2)

            # ── buttons ───────────────────────────────────────────────────────
            btn_style_primary = """
                QPushButton {
                    background:#2E86AB; color:white; border-radius:6px;
                    font-size:13px; font-weight:bold; padding:0 20px;
                }
                QPushButton:hover    { background:#1A5276; }
                QPushButton:disabled { background:#AEB6BF; }
            """
            btn_style_secondary = """
                QPushButton {
                    background:#EBF5FB; color:#1A5276; border:1px solid #2E86AB;
                    border-radius:6px; font-size:12px; padding:0 16px;
                }
                QPushButton:hover    { background:#D6EAF8; }
                QPushButton:disabled { background:#F2F3F4; color:#AEB6BF;
                                       border-color:#AEB6BF; }
            """
            btn_style_quit = """
                QPushButton {
                    background:#F9EBEA; color:#922B21; border:1px solid #E74C3C;
                    border-radius:6px; font-size:12px; padding:0 16px;
                }
                QPushButton:hover { background:#FADBD8; }
            """
            btn_style_info = """
                QPushButton {
                    background:#1B2A3B; color:#2E86AB; border:1px solid #2E86AB;
                    border-radius:6px; font-size:12px; padding:0 16px;
                }
                QPushButton:hover { background:#253D52; }
            """
            btn_style_pdf = """
                QPushButton {
                    background:#EBF9F1; color:#1E8449; border:1px solid #27AE60;
                    border-radius:6px; font-size:12px; padding:0 16px;
                }
                QPushButton:hover    { background:#D5F5E3; }
                QPushButton:disabled { background:#F2F3F4; color:#AEB6BF;
                                       border-color:#AEB6BF; }
            """

            btn_row = QHBoxLayout()
            btn_row.setSpacing(8)

            self.btn_run = QPushButton("Generate")
            self.btn_run.setFixedHeight(34)
            self.btn_run.setEnabled(False)
            self.btn_run.setStyleSheet(btn_style_primary)
            self.btn_run.clicked.connect(self._run)

            self.btn_html = QPushButton("View HTML")
            self.btn_html.setFixedHeight(34)
            self.btn_html.setEnabled(False)
            self.btn_html.setStyleSheet(btn_style_secondary)
            self.btn_html.clicked.connect(self._open_html)

            self.btn_pdf = QPushButton("Export PDF")
            self.btn_pdf.setFixedHeight(34)
            self.btn_pdf.setEnabled(False)
            self.btn_pdf.setStyleSheet(btn_style_pdf)
            self.btn_pdf.clicked.connect(self._open_pdf)

            btn_quit = QPushButton("Quit")
            btn_quit.setFixedHeight(34)
            btn_quit.setStyleSheet(btn_style_quit)
            btn_quit.clicked.connect(self.close)

            btn_info = QPushButton("Info")
            btn_info.setFixedHeight(34)
            btn_info.setFixedWidth(60)
            btn_info.setStyleSheet(btn_style_info)
            btn_info.clicked.connect(self._show_info)

            btn_row.addWidget(self.btn_run)
            btn_row.addWidget(self.btn_html)
            btn_row.addWidget(self.btn_pdf)
            btn_row.addStretch()
            btn_row.addWidget(btn_info)
            btn_row.addWidget(btn_quit)
            outer.addLayout(btn_row)

            # ── status bar ────────────────────────────────────────────────────
            self.w_status = QLabel("● Ready")
            self.w_status.setStyleSheet("color:#5D6D7E; font-size:11px; padding-top:4px;")
            outer.addWidget(self.w_status)

            # ── global stylesheet ─────────────────────────────────────────────
            self.setStyleSheet("""
                QWidget       { background:#F5F8FA; font-family:'Segoe UI',Arial; font-size:12px; }
                QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                    background:white; border:1px solid #D5D8DC; border-radius:4px;
                    padding:4px 6px; min-height:24px;
                }
                QLineEdit:focus, QComboBox:focus,
                QSpinBox:focus, QDoubleSpinBox:focus { border-color:#2E86AB; }
                QLabel      { background:transparent; }
                QCheckBox   { spacing:5px; }
                QCheckBox::indicator { width:14px; height:14px; }
            """)

        # ── slots ─────────────────────────────────────────────────────────────

        def _browse(self):
            path, _ = QFileDialog.getOpenFileName(
                self, "Open CSV file", "", "CSV files (*.csv);;All files (*)"
            )
            if path:
                self.w_file.setText(path)

        def _on_file_changed(self, path):
            self.w_col.clear()
            self.w_time.clear()
            self.w_col.setEnabled(False)
            self.w_time.setEnabled(False)
            self.btn_run.setEnabled(False)
            if not path or not os.path.isfile(path):
                return
            try:
                df = load_csv(path)
                cols = list(df.columns)
                self.w_col.addItems(cols)
                self.w_col.setEnabled(True)

                self.w_time.addItems([AUTO_DETECT_LABEL, NONE_LABEL] + cols)
                # pre-select known time column
                auto = find_time_col(cols)
                if auto:
                    self.w_time.setCurrentText(auto)
                self.w_time.setEnabled(True)

                self.btn_run.setEnabled(True)
                self._set_status(f"Loaded: {len(cols)} columns, {len(df)} rows", "ok")
            except Exception as exc:
                self._set_status(f"Error reading file: {exc}", "err")

        def _restore_config(self):
            cfg = _load_cfg()
            if not cfg:
                return
            path = cfg.get("csv_path", "")
            if path:
                self.w_file.setText(path)          # triggers _on_file_changed
            # column dropdowns are populated by _on_file_changed; set after
            if cfg.get("col") and self.w_col.findText(cfg["col"]) >= 0:
                self.w_col.setCurrentText(cfg["col"])
            if cfg.get("time_col") and self.w_time.findText(cfg["time_col"]) >= 0:
                self.w_time.setCurrentText(cfg["time_col"])
            try:
                self.w_bins.setValue(int(cfg.get("bins", 20)))
            except ValueError:
                pass
            try:
                self.w_k.setValue(float(cfg.get("k", 0.0)))
            except ValueError:
                pass
            self.w_title.setText(cfg.get("title", ""))
            self.w_target.setText(cfg.get("target", ""))
            self.w_out.setText(cfg.get("out_name", ""))
            self.ck_time_s.setChecked(  cfg.get("col_time_s",   "1") != "0")
            self.ck_time_hms.setChecked(cfg.get("col_time_hms", "1") != "0")
            self.ck_pct.setChecked(     cfg.get("col_pct",      "1") != "0")
            self.ck_count.setChecked(   cfg.get("col_count",    "1") != "0")

        def _run(self):
            target_str = self.w_target.text().strip()
            try:
                target = float(target_str) if target_str else None
            except ValueError:
                self._set_status("✖  Target must be a numeric value.", "err")
                return

            _save_cfg({
                "csv_path": self.w_file.text(),
                "col":      self.w_col.currentText(),
                "time_col": self.w_time.currentText(),
                "bins":     self.w_bins.value(),
                "k":        self.w_k.value(),
                "title":    self.w_title.text().strip(),
                "target":   target_str,
                "out_name": self.w_out.text().strip(),
                "col_time_s":   int(self.ck_time_s.isChecked()),
                "col_time_hms": int(self.ck_time_hms.isChecked()),
                "col_pct":      int(self.ck_pct.isChecked()),
                "col_count":    int(self.ck_count.isChecked()),
            })
            self.btn_run.setEnabled(False)
            self._set_status("Generating…", "busy")
            QApplication.processEvents()
            try:
                svg, html = make_histogram(
                    col          = self.w_col.currentText(),
                    csv_path     = self.w_file.text(),
                    time_col_arg = self.w_time.currentText(),
                    nbins        = self.w_bins.value(),
                    title        = self.w_title.text().strip() or None,
                    k            = self.w_k.value(),
                    out_name     = self.w_out.text().strip() or None,
                    target       = target,
                    save_png     = False,
                    show_plot    = False,
                    show_cols    = {
                        "time_s":   self.ck_time_s.isChecked(),
                        "time_hms": self.ck_time_hms.isChecked(),
                        "pct":      self.ck_pct.isChecked(),
                        "count":    self.ck_count.isChecked(),
                    },
                )
                self._last_html = html
                self.btn_html.setEnabled(True)
                self.btn_pdf.setEnabled(True)
                self._set_status(
                    f"✔  Saved -> {os.path.basename(svg)}  |  {os.path.basename(html)}", "ok"
                )
                webbrowser.open(html)
            except (FileNotFoundError, ValueError) as exc:
                self._set_status(f"✖  {exc}", "err")
            finally:
                self.btn_run.setEnabled(True)

        def _open_html(self):
            if self._last_html and os.path.isfile(self._last_html):
                webbrowser.open(self._last_html)

        def _open_pdf(self):
            if not (self._last_html and os.path.isfile(self._last_html)):
                return
            self._set_status("Generating PDF…", "busy")
            QApplication.processEvents()
            try:
                pdf_path = html_to_pdf(self._last_html)
                self._set_status(f"✔  PDF -> {os.path.basename(pdf_path)}", "ok")
            except Exception as exc:
                self._set_status(f"✖  PDF error: {exc}", "err")

        def _set_status(self, msg, kind=""):
            colors = {"ok": "#1ABC9C", "err": "#E74C3C", "busy": "#F39C12"}
            color  = colors.get(kind, "#5D6D7E")
            self.w_status.setStyleSheet(
                f"color:{color}; font-size:11px; padding-top:4px; font-weight:{'bold' if kind else 'normal'};"
            )
            self.w_status.setText(msg)

        def _show_info(self):
            SplashDialog(parent=self, auto_close=False).exec_()

        # ── auto-update slots ─────────────────────────────────────────────────

        def on_update_available(self, new_version, download_url):
            reply = QMessageBox.question(
                self,
                "Nueva versión disponible",
                f"<b>HistogramFAdeA v{new_version}</b> está disponible "
                f"(versión instalada: v{APP_VERSION}).<br><br>"
                "¿Desea descargar e instalar la actualización ahora?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

            import tempfile
            dest = os.path.join(
                tempfile.gettempdir(),
                f"HistogramFAdeA_Setup_v{new_version}.exe",
            )
            self._progress_dlg = QProgressDialog(
                f"Descargando HistogramFAdeA v{new_version}…",
                "Cancelar", 0, 100, self,
            )
            self._progress_dlg.setWindowTitle("Descargando actualización")
            self._progress_dlg.setWindowModality(Qt.WindowModal)
            self._progress_dlg.setMinimumDuration(0)
            self._progress_dlg.setValue(0)

            self._dl_thread = DownloadThread(download_url, dest)
            self._dl_thread.progress.connect(self._progress_dlg.setValue)
            self._dl_thread.finished.connect(self._on_download_finished)
            self._dl_thread.error.connect(self._on_download_error)
            self._progress_dlg.canceled.connect(self._dl_thread.terminate)
            self._dl_thread.start()
            self._progress_dlg.exec_()

        def _on_download_finished(self, path):
            import subprocess
            self._progress_dlg.setValue(100)
            self._progress_dlg.close()
            subprocess.Popen([path])
            QApplication.quit()

        def _on_download_error(self, msg):
            import os as _os
            self._progress_dlg.close()
            dest = getattr(self._dl_thread, "_dest", "")
            if dest and _os.path.isfile(dest):
                try:
                    _os.remove(dest)
                except OSError:
                    pass
            QMessageBox.warning(
                self,
                "Error de descarga",
                f"No se pudo descargar la actualización:\n{msg}\n\n"
                "Puede descargarla manualmente desde GitHub.",
            )

    # ── high-DPI awareness (must precede QApplication creation) ───────────────
    # Without this, geometry stays in physical pixels while point-sized fonts
    # scale with the monitor DPI, so on 4K/scaled displays the window renders
    # tiny and fixed-size widgets clip their text. Enabling these attributes
    # makes Qt honour the OS scale factor for both geometry and fonts.
    if QApplication.instance() is None:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        try:  # smooth fractional scaling (e.g. 150 %); Qt >= 5.14
            QApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        except AttributeError:
            pass

    app = QApplication.instance() or QApplication(sys.argv)
    if os.path.exists(APP_ICON_PATH):
        app.setWindowIcon(QIcon(APP_ICON_PATH))
    splash = SplashDialog(auto_close=True)
    splash.exec_()
    win = MainWindow()
    win.show()
    _updater = UpdaterThread()
    _updater.update_available.connect(win.on_update_available)
    _updater.check_error.connect(
        lambda msg: win._set_status(f"● Update check: {msg}", "err")
    )
    _updater.start()
    sys.exit(app.exec_())


# ── CLI arg parsing ───────────────────────────────────────────────────────────


def parse_cli(argv):
    col      = argv[1]
    csv_path = argv[2]
    if not os.path.splitext(csv_path)[1]:
        csv_path += ".csv"

    time_col_arg = None
    nbins    = 20
    title    = None
    k        = 0.0
    out_name = None
    target   = None

    for token in argv[3:]:
        if "=" not in token:
            sys.exit(f"Unknown argument: {token!r}  — use key=value format.")
        key, val = token.split("=", 1)
        key = key.strip().lower()
        val = val.strip()
        if key == "t":
            time_col_arg = val
        elif key == "bins":
            try:
                nbins = int(val)
                if nbins < 1:
                    raise ValueError
            except ValueError:
                sys.exit("bins= must be a positive integer.")
        elif key == "k":
            try:
                k = float(val)
                if k < 0:
                    raise ValueError
            except ValueError:
                sys.exit("k= must be a non-negative number.")
        elif key == "title":
            title = val
        elif key == "out":
            out_name = val
        elif key == "target":
            try:
                target = float(val)
            except ValueError:
                sys.exit("target= must be a number.")
        else:
            sys.exit(f"Unknown keyword: {key!r}. Supported: t, bins, k, title, out, target.")

    return dict(col=col, csv_path=csv_path, time_col_arg=time_col_arg,
                nbins=nbins, title=title, k=k, out_name=out_name, target=target)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        run_gui()
    else:
        try:
            make_histogram(**parse_cli(sys.argv))
        except (FileNotFoundError, ValueError) as exc:
            sys.exit(str(exc))
