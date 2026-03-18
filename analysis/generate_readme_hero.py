"""Generate the README hero image — protein bars + electrolyte drinks.

Two side-by-side panels showing FIS sub-score decomposition as horizontal
stacked bars.  Uses matplotlib for reliable static PNG output.

Run:  python analysis/generate_readme_hero.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── Palette (matches style.py) ─────────────────────────────────────────
BG      = "#0d0d0d"
PANEL   = "#131318"
GRID    = "#1e2028"
TEXT    = "#e0e0e8"
SUBTEXT = "#787888"

# Sub-score colors — slightly brighter for static rendering
C_MDS = "#9a8528"
C_AFS = "#5535b0"
C_HES = "#606070"
C_MLS = "#e8ef10"

CLASS_COLORS = {
    "C0": "#65763c", "C1": "#8da554",
    "P1a": "#b5c45a", "P1b": "#d5c248",
    "P2a": "#d4943a", "P2b": "#c8603a",
    "P3": "#d14136", "P4": "#8b2520",
}

TIER_SHORT = {
    "C0": "Clean", "C1": "Clean+",
    "P1a": "Light", "P1b": "Mod-Light",
    "P2a": "Moderate", "P2b": "Mod-Heavy",
    "P3": "Heavy", "P4": "Ultra",
}

# ── Data ────────────────────────────────────────────────────────────────
bars = [
    {"name": "Larabar",   "mds": 0,  "afs": 0,  "hes": 0,  "mls": 4,  "composite": 4,  "class": "C0"},
    {"name": "RXBAR",     "mds": 0,  "afs": 3,  "hes": 0,  "mls": 0,  "composite": 3,  "class": "C1"},
    {"name": "GoMacro",   "mds": 5,  "afs": 0,  "hes": 0,  "mls": 1,  "composite": 6,  "class": "C1"},
    {"name": "Clif Bar",  "mds": 12, "afs": 9,  "hes": 4,  "mls": 3,  "composite": 28, "class": "P1b"},
    {"name": "Kind Bar",  "mds": 10, "afs": 7,  "hes": 14, "mls": 5,  "composite": 36, "class": "P2a"},
    {"name": "David Bar", "mds": 18, "afs": 39, "hes": 7,  "mls": 0,  "composite": 64, "class": "P3"},
]

drinks = [
    {"name": "LMNT",          "mds": 0, "afs": 1,  "hes": 3,  "mls": 0,  "composite": 4,  "class": "C1"},
    {"name": "BODYARMOR",     "mds": 0, "afs": 9,  "hes": 7,  "mls": 7,  "composite": 23, "class": "P1b"},
    {"name": "Prime",         "mds": 0, "afs": 29, "hes": 3,  "mls": 0,  "composite": 32, "class": "P2a"},
    {"name": "Gatorade",      "mds": 3, "afs": 23, "hes": 8,  "mls": 0,  "composite": 34, "class": "P2a"},
    {"name": "Liquid I.V.",   "mds": 3, "afs": 22, "hes": 11, "mls": 13, "composite": 49, "class": "P2b"},
    {"name": "Propel",        "mds": 8, "afs": 35, "hes": 3,  "mls": 6,  "composite": 52, "class": "P3"},
    {"name": "Pedialyte",     "mds": 3, "afs": 42, "hes": 7,  "mls": 10, "composite": 62, "class": "P3"},
]

SUB_KEYS   = ["mls", "mds", "afs", "hes"]
SUB_LABELS = ["MLS", "MDS", "AFS", "HES"]
SUB_COLORS = [C_MLS, C_MDS, C_AFS, C_HES]


def draw_panel(ax, products, title, x_max):
    """Draw a horizontal stacked bar panel on the given axes."""
    names = [p["name"] for p in products]
    y_pos = np.arange(len(products))
    bar_h = 0.55

    left = np.zeros(len(products))
    for key, label, color in zip(SUB_KEYS, SUB_LABELS, SUB_COLORS):
        vals = np.array([p[key] for p in products])
        ax.barh(y_pos, vals, bar_h, left=left, color=color,
                edgecolor="none", label=label, zorder=3)
        left += vals

    # Composite score + tier label at end of each bar
    for i, p in enumerate(products):
        cc = CLASS_COLORS.get(p["class"], TEXT)
        ax.text(p["composite"] + x_max * 0.025, i,
                f'{p["composite"]}',
                va="center", ha="left",
                fontsize=10, fontweight="bold", color=cc)
        ax.text(p["composite"] + x_max * 0.09, i,
                TIER_SHORT[p["class"]],
                va="center", ha="left",
                fontsize=7.5, color=SUBTEXT)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=9, color=TEXT)
    ax.set_xlim(0, x_max)
    ax.set_ylim(-0.6, len(products) - 0.4)
    ax.invert_yaxis()

    ax.set_facecolor(PANEL)
    ax.tick_params(axis="x", colors=SUBTEXT, labelsize=7.5)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=6))

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.5, zorder=1)

    ax.set_title(title, fontsize=12, color=TEXT, fontweight="600",
                 loc="left", pad=10)


def main():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 4.5),
                                    gridspec_kw={"wspace": 0.35})
    fig.patch.set_facecolor(BG)

    draw_panel(ax1, bars,   "Protein Bars",       x_max=78)
    draw_panel(ax2, drinks, "Electrolyte Drinks",  x_max=78)

    # Shared legend at bottom
    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4,
               fontsize=9, frameon=False,
               labelcolor=TEXT, handlelength=1.2, handletextpad=0.5,
               bbox_to_anchor=(0.5, -0.04))

    out = Path(__file__).resolve().parent.parent / "docs" / "fis_hero.png"
    fig.savefig(out, dpi=200, bbox_inches="tight",
                facecolor=fig.get_facecolor(), pad_inches=0.3)
    print(f"Saved: {out}  ({out.stat().st_size / 1024:.0f} KB)")
    plt.close()


if __name__ == "__main__":
    main()
