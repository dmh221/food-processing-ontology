"""Generate README hero images — protein bars + electrolyte drinks.

Produces four PNGs in docs/:
  fis_hero.png              — stacked bar decomposition (both categories)
  fis_hero_protein_bars.png — scatter + AFS breakdown (protein bars)
  fis_hero_electrolytes.png — scatter + AFS breakdown (electrolyte drinks)
  fis_reference.png         — sub-scores + classification tiers reference

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

# Sub-score colors — brighter for static rendering on dark bg
C_MDS = "#b89e30"
C_AFS = "#7b55d0"
C_HES = "#606070"
C_MLS = "#e8ef10"

# AFS tier colors — brighter for static
C_TIER_A = "#e8ef10"
C_TIER_B = "#3060e0"
C_TIER_C = "#707080"

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
    {"name": "Larabar",   "mds": 0,  "afs": 0,  "hes": 0,  "mls": 4,  "composite": 4,  "class": "C0",
     "protein_g": 4,  "calories": 230, "color": "#4a73c8",
     "afs_a": 0,  "afs_b": 0, "afs_c": 0},
    {"name": "RXBAR",     "mds": 0,  "afs": 3,  "hes": 0,  "mls": 0,  "composite": 3,  "class": "C1",
     "protein_g": 12, "calories": 200, "color": "#6a8fd8",
     "afs_a": 3,  "afs_b": 0, "afs_c": 0},
    {"name": "GoMacro",   "mds": 5,  "afs": 0,  "hes": 0,  "mls": 1,  "composite": 6,  "class": "C1",
     "protein_g": 11, "calories": 260, "color": "#163fc7",
     "afs_a": 0,  "afs_b": 0, "afs_c": 0},
    {"name": "Clif Bar",  "mds": 12, "afs": 9,  "hes": 4,  "mls": 3,  "composite": 28, "class": "P1b",
     "protein_g": 10, "calories": 240, "color": "#042e99",
     "afs_a": 5,  "afs_b": 2, "afs_c": 2},
    {"name": "Kind Bar",  "mds": 10, "afs": 7,  "hes": 14, "mls": 5,  "composite": 36, "class": "P2a",
     "protein_g": 6,  "calories": 200, "color": "#474747",
     "afs_a": 4,  "afs_b": 2, "afs_c": 1},
    {"name": "David Bar", "mds": 18, "afs": 39, "hes": 7,  "mls": 0,  "composite": 64, "class": "P3",
     "protein_g": 28, "calories": 150, "color": "#f7ff08",
     "afs_a": 27, "afs_b": 6, "afs_c": 6},
]

drinks = [
    {"name": "LMNT",        "mds": 0, "afs": 1,  "hes": 3,  "mls": 0,  "composite": 4,  "class": "C1",
     "sodium_mg": 500, "sugar_g": 0,  "color": "#8ec8e8",
     "afs_a": 0,  "afs_b": 0,  "afs_c": 1},
    {"name": "BODYARMOR",   "mds": 0, "afs": 9,  "hes": 7,  "mls": 7,  "composite": 23, "class": "P1b",
     "sodium_mg": 25,  "sugar_g": 25, "color": "#4aafc7",
     "afs_a": 3,  "afs_b": 4,  "afs_c": 2},
    {"name": "Prime",       "mds": 0, "afs": 29, "hes": 3,  "mls": 0,  "composite": 32, "class": "P2a",
     "sodium_mg": 20,  "sugar_g": 1,  "color": "#2d7ab5",
     "afs_a": 19, "afs_b": 8,  "afs_c": 2},
    {"name": "Gatorade",    "mds": 3, "afs": 23, "hes": 8,  "mls": 0,  "composite": 34, "class": "P2a",
     "sodium_mg": 160, "sugar_g": 21, "color": "#d4943a",
     "afs_a": 9,  "afs_b": 12, "afs_c": 2},
    {"name": "Liquid I.V.", "mds": 3, "afs": 22, "hes": 11, "mls": 13, "composite": 49, "class": "P2b",
     "sodium_mg": 500, "sugar_g": 10, "color": "#c8603a",
     "afs_a": 3,  "afs_b": 16, "afs_c": 3},
    {"name": "Propel",      "mds": 8, "afs": 35, "hes": 3,  "mls": 6,  "composite": 52, "class": "P3",
     "sodium_mg": 220, "sugar_g": 0,  "color": "#9b4dca",
     "afs_a": 19, "afs_b": 12, "afs_c": 4},
    {"name": "Pedialyte",   "mds": 3, "afs": 42, "hes": 7,  "mls": 10, "composite": 62, "class": "P3",
     "sodium_mg": 490, "sugar_g": 5,  "color": "#f7ff08",
     "afs_a": 28, "afs_b": 12, "afs_c": 2},
]

SUB_KEYS   = ["mls", "mds", "afs", "hes"]
SUB_LABELS = ["MLS", "MDS", "AFS", "HES"]
SUB_COLORS = [C_MLS, C_MDS, C_AFS, C_HES]


# ── Shared helpers ──────────────────────────────────────────────────────

def _style_ax(ax):
    """Apply dark-theme styling to an axes."""
    ax.set_facecolor(PANEL)
    ax.tick_params(axis="x", colors=SUBTEXT, labelsize=7.5)
    ax.tick_params(axis="y", colors=SUBTEXT, labelsize=7.5, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.5, zorder=1)
    ax.grid(axis="y", color=GRID, linewidth=0.5, zorder=1)


def _save(fig, name):
    out = Path(__file__).resolve().parent.parent / "docs" / name
    fig.savefig(out, dpi=200, bbox_inches="tight",
                facecolor=fig.get_facecolor(), pad_inches=0.3)
    print(f"Saved: {out}  ({out.stat().st_size / 1024:.0f} KB)")
    plt.close(fig)


# ── Panel: horizontal stacked bar ──────────────────────────────────────

def draw_stacked_panel(ax, products, title, x_max):
    """Horizontal stacked bar panel of sub-score decomposition."""
    y_pos = np.arange(len(products))
    bar_h = 0.55

    left = np.zeros(len(products))
    for key, label, color in zip(SUB_KEYS, SUB_LABELS, SUB_COLORS):
        vals = np.array([p[key] for p in products])
        ax.barh(y_pos, vals, bar_h, left=left, color=color,
                edgecolor="none", label=label, zorder=3)
        left += vals

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
    ax.set_yticklabels([p["name"] for p in products], fontsize=9, color=TEXT)
    ax.set_xlim(0, x_max)
    ax.set_ylim(-0.6, len(products) - 0.4)
    ax.invert_yaxis()
    _style_ax(ax)
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=6))
    ax.set_title(title, fontsize=12, color=TEXT, fontweight="600",
                 loc="left", pad=10)


# ── Panel: bubble scatter ──────────────────────────────────────────────

def draw_scatter_panel(ax, products, *, x_key, x_label, x_range, y_range,
                       bubble_fn, title):
    """Bubble scatter: one dimension vs. composite score."""
    for p in products:
        ax.scatter(p[x_key], p["composite"],
                   s=bubble_fn(p), color=p["color"],
                   alpha=0.88, edgecolors="white", linewidths=0.5, zorder=3)
        ax.annotate(p["name"],
                    (p[x_key], p["composite"]),
                    textcoords="offset points", xytext=(0, 10),
                    ha="center", fontsize=8, color=p["color"])

    ax.set_xlim(x_range)
    ax.set_ylim(y_range)
    ax.set_xlabel(x_label, fontsize=8.5, color=SUBTEXT, labelpad=6)
    ax.set_ylabel("Composite Score", fontsize=8.5, color=SUBTEXT, labelpad=6)
    _style_ax(ax)
    ax.set_title(title, fontsize=11, color=SUBTEXT, fontweight="500",
                 loc="center", pad=10)


# ── Panel: AFS tier breakdown ──────────────────────────────────────────

def draw_afs_panel(ax, products, title="AFS Breakdown by Tier"):
    """Horizontal stacked bar chart of AFS tiers."""
    prods_rev = list(reversed(products))
    names = [p["name"] for p in prods_rev]
    y_pos = np.arange(len(prods_rev))
    bar_h = 0.55

    tiers = [
        ("Tier A", "afs_a", C_TIER_A),
        ("Tier B", "afs_b", C_TIER_B),
        ("Tier C", "afs_c", C_TIER_C),
    ]

    left = np.zeros(len(prods_rev))
    for tier_name, key, color in tiers:
        vals = np.array([p[key] for p in prods_rev])
        ax.barh(y_pos, vals, bar_h, left=left, color=color,
                edgecolor="none", label=tier_name, zorder=3)
        left += vals

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=9, color=TEXT)
    ax.set_xlabel("AFS Points", fontsize=8.5, color=SUBTEXT, labelpad=6)
    _style_ax(ax)
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=6))
    ax.set_title(title, fontsize=11, color=SUBTEXT, fontweight="500",
                 loc="center", pad=10)


# ── Image 1: Stacked bar hero (both categories) ───────────────────────

def generate_hero():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 4.5),
                                    gridspec_kw={"wspace": 0.35})
    fig.patch.set_facecolor(BG)

    draw_stacked_panel(ax1, bars,   "Protein Bars",       x_max=78)
    draw_stacked_panel(ax2, drinks, "Electrolyte Drinks",  x_max=78)

    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4,
               fontsize=9, frameon=False,
               labelcolor=TEXT, handlelength=1.2, handletextpad=0.5,
               bbox_to_anchor=(0.5, -0.04))

    _save(fig, "fis_hero.png")


# ── Image 2: Protein bar scatter + AFS ─────────────────────────────────

def generate_bars_detail():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 4.5),
                                    gridspec_kw={"wspace": 0.30,
                                                 "width_ratios": [1, 1]})
    fig.patch.set_facecolor(BG)

    draw_scatter_panel(ax1, bars,
                       x_key="protein_g", x_label="Protein (g)",
                       x_range=[-2, 35], y_range=[-5, 75],
                       bubble_fn=lambda p: p["calories"] / 5.5 * 8,
                       title="Protein vs. Processing")

    draw_afs_panel(ax2, bars, title="AFS Breakdown by Tier")

    handles, labels = ax2.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3,
               fontsize=9, frameon=False,
               labelcolor=TEXT, handlelength=1.2, handletextpad=0.5,
               bbox_to_anchor=(0.5, -0.04))

    _save(fig, "fis_hero_protein_bars.png")


# ── Image 3: Electrolyte scatter + AFS ─────────────────────────────────

def generate_drinks_detail():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 4.5),
                                    gridspec_kw={"wspace": 0.30,
                                                 "width_ratios": [1, 1]})
    fig.patch.set_facecolor(BG)

    draw_scatter_panel(ax1, drinks,
                       x_key="sodium_mg", x_label="Sodium (mg)",
                       x_range=[-30, 580], y_range=[-5, 72],
                       bubble_fn=lambda p: max(p["sugar_g"] * 2.5, 14) * 8,
                       title="Sodium vs. Processing  (bubble = sugar)")

    draw_afs_panel(ax2, drinks, title="AFS Breakdown by Tier")

    handles, labels = ax2.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3,
               fontsize=9, frameon=False,
               labelcolor=TEXT, handlelength=1.2, handletextpad=0.5,
               bbox_to_anchor=(0.5, -0.04))

    _save(fig, "fis_hero_electrolytes.png")


# ── Image 4: Sub-scores + classification tiers reference ──────────────

METAB_COLORS = {
    "N0": "#8ab4d6", "N0+": "#4a73c8", "N1a": "#163fc7",
    "N1b": "#042e99", "N2": "#d5c248", "N3": "#f7ff08",
}

SUB_SCORE_ROWS = [
    ("MLS", C_MLS, "How extreme the nutrition label is \u2014 flagging high sugar, sodium, saturated fat, and energy-dense sweet formulations.", "0\u201320"),
    ("MDS", C_MDS, "How many core ingredients have been replaced by industrial substitutes (modified starches, hydrogenated fats, HFCS, protein isolates).", "0\u201330"),
    ("AFS", C_AFS, "How many chemical additives are stacked in \u2014 emulsifiers, preservatives, artificial colors, flavor enhancers.", "0\u201380"),
    ("HES", C_HES, "How engineered the sweetener system is \u2014 sugar alcohols, non-nutritive sweeteners, and multi-sweetener blending strategies.", "0\u201320"),
]

PROCESSING_TIERS = [
    ("C0",  "Clean",                        "0"),
    ("C1",  "Clean, Minimal Markers",       "1\u20135"),
    ("P1a", "Light Processing",             "6\u201315"),
    ("P1b", "Moderate-Light Processing",    "16\u201325"),
    ("P2a", "Moderate Processing",          "26\u201338"),
    ("P2b", "Moderate-Heavy Processing",    "39\u201350"),
    ("P3",  "Heavy Industrial Formulation", "51\u201375"),
    ("P4",  "Ultra-Formulated",             "76+"),
]

METABOLIC_TIERS = [
    ("N0",  "No Metabolic Load", "0"),
    ("N0+", "Minimal",          "1\u20133"),
    ("N1a", "Low",              "4\u20136"),
    ("N1b", "Low-Moderate",     "7\u20138"),
    ("N2",  "Moderate",         "9\u201314"),
    ("N3",  "High",             "15+"),
]


def generate_reference():
    fig = plt.figure(figsize=(14, 6.8))
    fig.patch.set_facecolor(BG)

    # ── Column positions (figure coords 0-1) ──
    L_LABEL  = 0.05   # sub-score label
    L_DESC   = 0.14   # description start
    R_RANGE  = 0.96   # range right-aligned

    # ── SUB-SCORES section ──
    y = 0.94
    fig.text(0.05, y, "SUB-SCORES", fontsize=9, color=SUBTEXT,
             fontweight="600", fontfamily="monospace",
             transform=fig.transFigure)
    y -= 0.045

    for label, color, desc, rng in SUB_SCORE_ROWS:
        fig.text(L_LABEL, y, label, fontsize=11, color=color,
                 fontweight="700", fontfamily="monospace",
                 transform=fig.transFigure)
        fig.text(L_DESC, y, desc, fontsize=9, color=TEXT,
                 transform=fig.transFigure)
        fig.text(R_RANGE, y, rng, fontsize=9, color=TEXT,
                 ha="right", transform=fig.transFigure)
        y -= 0.040

    # Composite row (bold white)
    fig.text(L_LABEL, y, "Composite", fontsize=11, color=TEXT,
             fontweight="700", fontfamily="monospace",
             transform=fig.transFigure)
    fig.text(L_DESC + 0.03, y,
             "MDS + AFS + HES + MLS. How far a product has moved from recognizable food.",
             fontsize=9, color=TEXT, transform=fig.transFigure)
    fig.text(R_RANGE, y, "0\u2013150", fontsize=9, color=TEXT,
             ha="right", fontweight="700", transform=fig.transFigure)

    # ── Separator line ──
    y -= 0.055
    line_y = y + 0.02
    fig.add_artist(plt.Line2D([0.05, 0.96], [line_y, line_y],
                              color=GRID, linewidth=0.8,
                              transform=fig.transFigure, clip_on=False))

    # ── CLASSIFICATION TIERS header ──
    fig.text(0.05, y, "CLASSIFICATION TIERS", fontsize=9, color=SUBTEXT,
             fontweight="600", fontfamily="monospace",
             transform=fig.transFigure)
    y -= 0.045

    # Left table: Processing class
    PL_LABEL = 0.05
    PL_NAME  = 0.14
    PL_RANGE = 0.48

    fig.text(PL_LABEL, y, "Processing class", fontsize=9.5, color=TEXT,
             fontweight="700", transform=fig.transFigure)
    fig.text(PL_LABEL + 0.165, y, "\u2014 derived from composite score",
             fontsize=8.5, color=SUBTEXT, transform=fig.transFigure)

    # Right table: Metabolic class
    ML_LABEL = 0.54
    ML_NAME  = 0.63
    ML_RANGE = 0.96

    fig.text(ML_LABEL, y, "Metabolic class", fontsize=9.5, color=TEXT,
             fontweight="700", transform=fig.transFigure)
    fig.text(ML_LABEL + 0.155, y, "\u2014 derived from MLS",
             fontsize=8.5, color=SUBTEXT, transform=fig.transFigure)

    y -= 0.045

    # Draw processing tiers (left)
    py = y
    for tier, name, rng in PROCESSING_TIERS:
        cc = CLASS_COLORS.get(tier, TEXT)
        fig.text(PL_LABEL, py, tier, fontsize=10, color=cc,
                 fontweight="700", fontfamily="monospace",
                 transform=fig.transFigure)
        fig.text(PL_NAME, py, name, fontsize=9, color=TEXT,
                 transform=fig.transFigure)
        fig.text(PL_RANGE, py, rng, fontsize=9, color=TEXT,
                 ha="right", transform=fig.transFigure)
        py -= 0.040

    # Draw metabolic tiers (right)
    my = y
    for tier, name, rng in METABOLIC_TIERS:
        mc = METAB_COLORS.get(tier, TEXT)
        fig.text(ML_LABEL, my, tier, fontsize=10, color=mc,
                 fontweight="700", fontfamily="monospace",
                 transform=fig.transFigure)
        fig.text(ML_NAME, my, name, fontsize=9, color=TEXT,
                 transform=fig.transFigure)
        fig.text(ML_RANGE, my, rng, fontsize=9, color=TEXT,
                 ha="right", transform=fig.transFigure)
        my -= 0.040

    _save(fig, "fis_reference.png")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    generate_hero()
    generate_bars_detail()
    generate_drinks_detail()
    generate_reference()


if __name__ == "__main__":
    main()
