"""Interactive electrolyte drink comparison — FIS v0.9.1.

The Hydration Spectrum: from salt water to synthetic cocktail.

Generates demos/electrolytes.html

Run:  python analysis/electrolyte_comparison_interactive.py
"""

import plotly.graph_objects as go
import plotly.io as pio
from pathlib import Path

# ---------------------------------------------------------------------------
# Style — dark mode, clean-to-synthetic palette
# ---------------------------------------------------------------------------
BG      = "#0d0d0d"
PANEL   = "#131318"
GRID    = "#1e2028"
TEXT    = "#e0e0e8"
SUBTEXT = "#787888"

# Sub-score colors
C_MDS = "#74651b"   # olive
C_AFS = "#300377"   # dark violet
C_HES = "#474747"   # grey
C_MLS = "#f7ff08"   # neon yellow

# AFS tier colors
C_TIER_A = "#f7ff08"  # neon yellow — highest severity
C_TIER_B = "#163fc7"  # royal blue
C_TIER_C = "#474747"  # grey

CLASS_COLORS = {
    "C0": "#65763c", "C1": "#8da554",
    "P1a": "#b5c45a", "P1b": "#d5c248",
    "P2a": "#d4943a", "P2b": "#c8603a",
    "P3": "#d14136", "P4": "#8b2520",
}

TIER_NAMES = {
    "W": "Whole Food", "Wp": "Whole Prepped",
    "C0": "Clean", "C1": "Clean, Minimal Markers",
    "P1a": "Light Processing", "P1b": "Moderate-Light Processing",
    "P2a": "Moderate Processing", "P2b": "Moderate-Heavy Processing",
    "P3": "Heavy Industrial Formulation", "P4": "Ultra-Formulated",
}

LAYOUT_DEFAULTS = dict(
    paper_bgcolor=BG,
    plot_bgcolor=PANEL,
    font=dict(family="Open Sans, sans-serif", color=TEXT, size=12),
    hoverlabel=dict(
        font=dict(color="white", family="Open Sans, sans-serif", size=13),
        bgcolor="#2a2a3a",
        bordercolor="rgba(0,0,0,0)",
    ),
)

# ---------------------------------------------------------------------------
# Data — 6 electrolyte drinks (v0.9.1 scores from scored_products.parquet)
# ---------------------------------------------------------------------------
products = [
    {
        "name": "LMNT", "sub": "Sparkling Orange",
        "composite": 4, "mds": 0, "afs": 1, "hes": 3, "mls": 0,
        "class": "C1",
        "ingredients": "Sparkling water, salt (sodium chloride), citric acid, natural orange flavor, magnesium malate, potassium chloride, stevia leaf extract",
        "sugar_g": 0, "calories": 5, "sodium_mg": 500,
        "afs_a": 0, "afs_b": 0, "afs_c": 1,
        "tier_a": [], "tier_b": [], "tier_c": ["citric acid"],
        "flags_plain": "Water + electrolyte salts + stevia — minimal formulation",
        "color": "#8ec8e8",
    },
    {
        "name": "BODYARMOR", "sub": "Fruit Punch 16oz",
        "composite": 23, "mds": 0, "afs": 9, "hes": 7, "mls": 7,
        "class": "P1b",
        "ingredients": "Filtered water, cane sugar, coconut water concentrate, citric acid, electrolyte blend (dipotassium phosphate, magnesium oxide, zinc oxide), fruit and vegetable juice (color), vitamins (niacinamide, D-calcium pantothenate, pyridoxine hydrochloride, alpha-tocopheryl acetate, retinyl palmitate), natural flavors",
        "sugar_g": 25, "calories": 110, "sodium_mg": 25,
        "afs_a": 3, "afs_b": 4, "afs_c": 2,
        "tier_a": ["natural flavor"],
        "tier_b": ["dipotassium phosphate"],
        "tier_c": ["citric acid", "ascorbic acid", "niacinamide", "pyridoxine HCl"],
        "flags_plain": "Coconut water base but 25g sugar — sport drink calories with natural branding",
        "color": "#4aafc7",
    },
    {
        "name": "Prime Hydration", "sub": "Blue Chill",
        "composite": 32, "mds": 0, "afs": 29, "hes": 3, "mls": 0,
        "class": "P2a",
        "ingredients": "Water, coconut water concentrate, citric acid, dipotassium phosphate, trimagnesium citrate, L-isoleucine, L-leucine, L-valine, sucralose, gum arabic, acesulfame potassium, natural flavors, ester gum, retinyl palmitate, D-alpha-tocopheryl acetate, pyridoxine hydrochloride, cyanocobalamin",
        "sugar_g": 1, "calories": 20, "sodium_mg": 20,
        "afs_a": 19, "afs_b": 8, "afs_c": 2,
        "tier_a": ["natural flavor", "sucralose", "acesulfame K"],
        "tier_b": ["dipotassium phosphate", "gum arabic"],
        "tier_c": ["citric acid", "pyridoxine HCl", "vitamin B12"],
        "flags_plain": "3 Tier A hits: two NNS + natural flavor, plus BCAAs and gum arabic",
        "color": "#2d7ab5",
    },
    {
        "name": "Gatorade", "sub": "Lemon Lime",
        "composite": 34, "mds": 3, "afs": 23, "hes": 8, "mls": 0,
        "class": "P2a",
        "ingredients": "Water, sugar, dextrose, citric acid, salt, sodium citrate, monopotassium phosphate, gum arabic, glycerol ester of rosin, natural flavor, yellow 5",
        "sugar_g": 21, "calories": 80, "sodium_mg": 160,
        "afs_a": 9, "afs_b": 12, "afs_c": 2,
        "tier_a": ["yellow 5", "natural flavor"],
        "tier_b": ["sodium citrate", "monopotassium phosphate", "gum arabic"],
        "tier_c": ["citric acid"],
        "flags_plain": "Yellow 5 (artificial color) + dextrose + gum arabic — the 1965 formula, barely changed",
        "color": "#d4943a",
    },
    {
        "name": "Liquid I.V.", "sub": "Strawberry Lemonade",
        "composite": 49, "mds": 3, "afs": 22, "hes": 11, "mls": 13,
        "class": "P2b",
        "ingredients": "Cane sugar, dextrose, citric acid, salt, potassium citrate, sodium citrate, dipotassium phosphate, silicon dioxide, vitamin C (ascorbic acid), stevia leaf extract, natural flavors, B vitamins (niacin, B5, B6, B12)",
        "sugar_g": 10, "calories": 40, "sodium_mg": 500,
        "afs_a": 3, "afs_b": 16, "afs_c": 3,
        "tier_a": ["natural flavor"],
        "tier_b": ["sodium citrate", "potassium citrate", "dipotassium phosphate", "silicon dioxide"],
        "tier_c": ["citric acid", "ascorbic acid", "niacinamide", "pyridoxine HCl"],
        "flags_plain": "4 Tier B hits (silicon dioxide, phosphate, two citrates) + sugar/dextrose drive MLS to 13",
        "color": "#c8603a",
    },
    {
        "name": "Propel", "sub": "Grape Powder",
        "composite": 52, "mds": 8, "afs": 35, "hes": 3, "mls": 6,
        "class": "P3",
        "ingredients": "Citric acid, maltodextrin, sodium citrate, salt, monopotassium phosphate, modified food starch, sucralose, ascorbic acid (vitamin C), silicon dioxide, vitamin E acetate, niacinamide (vitamin B3), acesulfame potassium, calcium pantothenate (vitamin B5), calcium disodium EDTA (to protect flavor), pyridoxine hydrochloride (vitamin B6), natural flavor, cyanocobalamin (vitamin B12)",
        "sugar_g": 0, "calories": 0, "sodium_mg": 220,
        "afs_a": 19, "afs_b": 12, "afs_c": 4,
        "tier_a": ["natural flavor", "sucralose", "acesulfame K"],
        "tier_b": ["sodium citrate", "monopotassium phosphate", "silicon dioxide"],
        "tier_c": ["citric acid", "ascorbic acid", "niacinamide", "pyridoxine HCl", "vitamin B12"],
        "flags_plain": "Maltodextrin + modified food starch drive MDS=8; dual NNS + EDTA push AFS to 35",
        "color": "#9b4dca",
    },
    {
        "name": "Pedialyte Sport", "sub": "Fruit Punch",
        "composite": 62, "mds": 3, "afs": 42, "hes": 7, "mls": 10,
        "class": "P3",
        "ingredients": "Water, dextrose; less than 1% of: galactooligosaccharides, salt, potassium citrate, citric acid, potassium phosphate, natural and artificial flavors, magnesium chloride, sodium citrate, sucralose, acesulfame potassium, and blue 1",
        "sugar_g": 5, "calories": 30, "sodium_mg": 490,
        "afs_a": 28, "afs_b": 12, "afs_c": 2,
        "tier_a": ["blue 1", "artificial flavor", "sucralose", "acesulfame K"],
        "tier_b": ["sodium citrate", "potassium citrate", "potassium phosphate"],
        "tier_c": ["citric acid"],
        "flags_plain": "4 Tier A hits: blue 1, artificial flavor, 2 NNS — medical-grade formulation",
        "color": "#f7ff08",
    },
]


# ---------------------------------------------------------------------------
# Panel 1 — Stacked bar chart (hero)
# ---------------------------------------------------------------------------
def chart_stacked_bar():
    fig = go.Figure()
    names = [p["name"] for p in products]

    sub_keys   = ["hes",  "afs",  "mds",  "mls"]
    sub_labels = ["HES",  "AFS",  "MDS",  "MLS"]
    sub_colors = [C_HES,  C_AFS,  C_MDS,  C_MLS]

    for key, label, color in zip(sub_keys, sub_labels, sub_colors):
        vals = [p[key] for p in products]
        hover = [
            f"<b>{p['name']}</b><br>"
            f"{label} = {v}  |  Composite = {p['composite']}"
            for p, v in zip(products, vals)
        ]
        fig.add_trace(go.Bar(
            x=names, y=vals, name=label,
            marker=dict(color=color, line_width=0), opacity=0.92,
            hovertemplate="%{hovertext}<extra></extra>",
            hovertext=hover,
        ))

    for p in products:
        fig.add_annotation(
            x=p["name"], y=p["composite"] + 3,
            text=f"<b>{p['composite']}</b>",
            showarrow=False,
            font=dict(size=15, color=CLASS_COLORS.get(p["class"], TEXT)),
        )

    ticktext = [
        f"<b>{p['name']}</b><br>"
        f"{p['sub']}<br>"
        f"<span style='font-size:10px'>{TIER_NAMES[p['class']]}</span>"
        for p in products
    ]

    fig.update_layout(
        **LAYOUT_DEFAULTS,
        barmode="stack",
        yaxis=dict(
            title="FIS Composite Score",
            gridcolor=GRID, zeroline=False, range=[0, 72],
        ),
        xaxis=dict(
            gridcolor=GRID, tickvals=names, ticktext=ticktext, tickangle=0,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)", borderwidth=0,
            font=dict(size=12), orientation="h",
            yanchor="top", y=-0.22, xanchor="center", x=0.5,
            traceorder="reversed",
        ),
        margin=dict(l=60, r=30, t=20, b=130),
        height=520,
    )
    return fig


# ---------------------------------------------------------------------------
# Panel 2 — Ingredient & flags table
# ---------------------------------------------------------------------------
def build_table_html():
    rows = []
    for p in products:
        class_color = CLASS_COLORS.get(p["class"], TEXT)
        rows.append(
            f'    <tr>'
            f'<td class="axis-name">'
            f'{p["name"]}<br><span style="font-weight:400">{p["sub"]}</span></td>'
            f'<td>{p["ingredients"]}</td>'
            f'<td style="color:{class_color};font-weight:600">{TIER_NAMES[p["class"]]}</td>'
            f'<td>{p["flags_plain"]}</td>'
            f'</tr>'
        )
    return (
        '<table class="key-table">\n'
        '<colgroup><col style="width:110px"><col style="width:360px">'
        '<col style="width:200px"><col style="width:280px"></colgroup>\n'
        '    <tr><td class="axis-name">Drink</td>'
        '<td class="axis-name">Ingredients</td>'
        '<td class="axis-name">Class</td>'
        '<td class="axis-name">What FIS Detected</td></tr>\n'
        + "\n".join(rows) + "\n"
        '</table>'
    )


# ---------------------------------------------------------------------------
# Panel 3 — Sodium vs. Processing scatter (bubble = sugar grams)
# ---------------------------------------------------------------------------
def chart_scatter():
    fig = go.Figure()

    for p in products:
        # Bubble size: sugar_g scaled, with a min for zero-sugar products
        bub = max(p["sugar_g"] * 2.5, 14)
        hover = (
            f"<b>{p['name']}</b><br>"
            f"{p['sodium_mg']}mg sodium  |  {p['sugar_g']}g sugar<br>"
            f"Composite {p['composite']}  ({TIER_NAMES[p['class']]})"
        )
        fig.add_trace(go.Scatter(
            x=[p["sodium_mg"]], y=[p["composite"]],
            mode="markers+text",
            marker=dict(
                size=bub,
                color=p["color"],
                opacity=0.90,
                line=dict(color="rgba(255,255,255,0.35)", width=1.5),
            ),
            text=[p["name"]],
            textposition="top center",
            textfont=dict(size=11, color=p["color"]),
            hovertemplate="%{hovertext}<extra></extra>",
            hovertext=[hover],
            showlegend=False,
        ))

    fig.update_layout(
        **LAYOUT_DEFAULTS,
        title=dict(
            text="Sodium vs. Processing  (bubble = sugar grams)",
            font=dict(size=14, color=SUBTEXT), x=0.5,
        ),
        xaxis=dict(
            title="Sodium (mg per serving)", gridcolor=GRID, zeroline=False,
            range=[-30, 580],
        ),
        yaxis=dict(
            title="Composite Score", gridcolor=GRID, zeroline=False,
            range=[-5, 72],
        ),
        margin=dict(l=55, r=20, t=40, b=50),
        height=420,
    )
    return fig


# ---------------------------------------------------------------------------
# Panel 4 — AFS tier breakdown (stacked horizontal)
# ---------------------------------------------------------------------------
def chart_afs_breakdown():
    fig = go.Figure()

    prods_rev = list(reversed(products))
    names = [p["name"] for p in prods_rev]

    tiers = [
        ("Tier A", "afs_a", "tier_a", C_TIER_A, "industrial/synthetic"),
        ("Tier B", "afs_b", "tier_b", C_TIER_B, "processing aids"),
        ("Tier C", "afs_c", "tier_c", C_TIER_C, "mild/contextual"),
    ]

    for tier_name, val_key, list_key, color, desc in tiers:
        vals = [p[val_key] for p in prods_rev]
        hover = [
            f"<b>{p['name']}</b><br>"
            f"{tier_name}: {p[val_key]}"
            + (f"<br>{', '.join(p[list_key])}" if p[list_key] else "")
            for p in prods_rev
        ]
        fig.add_trace(go.Bar(
            y=names, x=vals,
            name=f"{tier_name} ({desc})",
            orientation="h",
            marker=dict(color=color, line_width=0),
            opacity=0.88,
            hovertemplate="%{hovertext}<extra></extra>",
            hovertext=hover,
        ))

    fig.update_layout(
        **LAYOUT_DEFAULTS,
        barmode="stack",
        title=dict(
            text="AFS Breakdown by Tier",
            font=dict(size=14, color=SUBTEXT), x=0.5,
        ),
        xaxis=dict(title="AFS Points", gridcolor=GRID, zeroline=False),
        yaxis=dict(gridcolor=GRID),
        legend=dict(
            bgcolor="rgba(0,0,0,0)", borderwidth=0,
            font=dict(size=10), orientation="h",
            yanchor="top", y=-0.15, xanchor="center", x=0.5,
        ),
        margin=dict(l=120, r=20, t=40, b=70),
        height=420,
    )
    return fig


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Electrolyte Drinks — The Hydration Spectrum — FIS v0.9.1</title>
<style>
  body {{
    background: {bg};
    color: {text};
    font-family: 'Open Sans', sans-serif;
    margin: 0 auto;
    padding: 40px 48px;
    max-width: 1300px;
  }}
  h1 {{
    text-align: center;
    font-size: 1.5em;
    font-weight: 600;
    margin: 0 0 2px 0;
  }}
  .subtitle {{
    text-align: center;
    color: {subtext};
    font-size: 0.82em;
    margin-bottom: 28px;
  }}
  .section {{
    margin-bottom: 48px;
  }}
  .section-label {{
    color: {subtext};
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    margin-bottom: 8px;
  }}
  .key-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82em;
  }}
  .key-table td {{
    padding: 6px 14px;
    border-bottom: 1px solid {grid};
    vertical-align: top;
  }}
  .key-table .axis-name {{
    font-weight: 600;
    white-space: nowrap;
    width: 120px;
  }}
  .key-table .range {{
    color: {subtext};
    white-space: nowrap;
    width: 70px;
    text-align: right;
  }}
  .row {{
    display: flex;
    gap: 24px;
  }}
  .row .col {{
    flex: 1;
    min-width: 0;
  }}
  .footer {{
    text-align: center;
    color: {subtext};
    font-size: 0.72em;
    padding: 20px 0 0 0;
    border-top: 1px solid {grid};
    line-height: 1.8;
  }}
</style>
</head>
<body>
<h1>The Hydration Spectrum</h1>
<div class="subtitle">Food Integrity Scale v0.9.1 &mdash; 7 electrolyte drinks, scores 4 to 62</div>

<div class="section">
  <div class="section-label">Sub-scores</div>
  <table class="key-table">
    <tr>
      <td class="axis-name" style="color:{c_mls}">MLS</td>
      <td>How extreme the nutrition label is &mdash; flagging high sugar, sodium, saturated fat, and energy-dense sweet formulations.</td>
      <td class="range">0&ndash;20</td>
    </tr>
    <tr>
      <td class="axis-name" style="color:{c_mds}">MDS</td>
      <td>How many core ingredients have been replaced by industrial substitutes (modified starches, hydrogenated fats, HFCS, protein isolates).</td>
      <td class="range">0&ndash;30</td>
    </tr>
    <tr>
      <td class="axis-name" style="color:{c_afs}">AFS</td>
      <td>How many chemical additives are stacked in &mdash; emulsifiers, preservatives, artificial colors, flavor enhancers.</td>
      <td class="range">0&ndash;80</td>
    </tr>
    <tr>
      <td class="axis-name" style="color:{c_hes}">HES</td>
      <td>How engineered the sweetener system is &mdash; sugar alcohols, non-nutritive sweeteners, and multi-sweetener blending strategies.</td>
      <td class="range">0&ndash;20</td>
    </tr>
    <tr style="border-top: 1px solid {subtext}">
      <td class="axis-name">Composite</td>
      <td>MDS + AFS + HES + MLS. How far a product has moved from recognizable food.</td>
      <td class="range">0&ndash;150</td>
    </tr>
  </table>
</div>

<div class="section">
  <div class="section-label">Classification tiers</div>
  <div class="row" style="gap: 48px">
    <div class="col">
      <table class="key-table">
        <tr><td colspan="3" style="color:{subtext};font-size:0.9em;padding-bottom:8px">
          <b style="color:{text}">Processing class</b> &mdash; derived from composite score
        </td></tr>
        <tr><td class="axis-name" style="color:#65763c">C0</td><td>Clean</td><td class="range">0</td></tr>
        <tr><td class="axis-name" style="color:#8da554">C1</td><td>Clean, Minimal Markers</td><td class="range">1&ndash;5</td></tr>
        <tr><td class="axis-name" style="color:#b5c45a">P1a</td><td>Light Processing</td><td class="range">6&ndash;15</td></tr>
        <tr><td class="axis-name" style="color:#d5c248">P1b</td><td>Moderate-Light Processing</td><td class="range">16&ndash;25</td></tr>
        <tr><td class="axis-name" style="color:#d4943a">P2a</td><td>Moderate Processing</td><td class="range">26&ndash;38</td></tr>
        <tr><td class="axis-name" style="color:#c8603a">P2b</td><td>Moderate-Heavy Processing</td><td class="range">39&ndash;50</td></tr>
        <tr><td class="axis-name" style="color:#d14136">P3</td><td>Heavy Industrial Formulation</td><td class="range">51&ndash;75</td></tr>
        <tr><td class="axis-name" style="color:#8b2520">P4</td><td>Ultra-Formulated</td><td class="range">76+</td></tr>
      </table>
    </div>
    <div class="col">
      <table class="key-table">
        <tr><td colspan="3" style="color:{subtext};font-size:0.9em;padding-bottom:8px">
          <b style="color:{text}">Metabolic class</b> &mdash; derived from MLS
        </td></tr>
        <tr><td class="axis-name" style="color:#8ab4d6">N0</td><td>No Metabolic Load</td><td class="range">0</td></tr>
        <tr><td class="axis-name" style="color:#4a73c8">N0+</td><td>Minimal</td><td class="range">1&ndash;3</td></tr>
        <tr><td class="axis-name" style="color:#163fc7">N1a</td><td>Low</td><td class="range">4&ndash;6</td></tr>
        <tr><td class="axis-name" style="color:#042e99">N1b</td><td>Low-Moderate</td><td class="range">7&ndash;8</td></tr>
        <tr><td class="axis-name" style="color:#d5c248">N2</td><td>Moderate</td><td class="range">9&ndash;14</td></tr>
        <tr><td class="axis-name" style="color:#f7ff08">N3</td><td>High</td><td class="range">15+</td></tr>
      </table>
    </div>
  </div>
</div>

<div class="section">{chart_stacked}</div>

<div class="section">
  <div class="section-label">Ingredient detail</div>
  {chart_table}
</div>

<div class="section">
  <div class="row">
    <div class="col">{chart_scatter}</div>
    <div class="col">{chart_afs}</div>
  </div>
</div>

<div class="section">
  <div class="section-label">Analysis</div>
  <div style="font-size:0.88em;line-height:1.75;max-width:960px;margin:0 auto">

  <p style="color:{text};font-weight:600;font-size:1.05em;margin-bottom:16px">
    Seven electrolyte drinks, scores 4 to 62. They all promise the same thing &mdash; hydration &mdash;
    but the ingredient lists range from salt water to a synthetic cocktail of artificial colors,
    dual NNS systems, and industrial emulsifiers.
  </p>

  <p style="color:{subtext};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Key Takeaways</p>
  <ul style="padding-left:20px;margin:0 0 20px 0">
    <li>LMNT (4) is the baseline: sparkling water, salt, citric acid, stevia. Seven ingredients,
        one Tier&nbsp;C hit. The electrolytes come from mineral salts, not industrial phosphates.</li>
    <li>BODYARMOR (23) uses coconut water as its base but packs 25&thinsp;g of cane sugar per bottle.
        The &ldquo;natural&rdquo; branding masks a sugar load that rivals Gatorade.</li>
    <li>Prime Hydration (32) has zero sugar but 3 Tier&nbsp;A hits: sucralose, acesulfame&nbsp;K,
        and natural flavor. Dipotassium phosphate (Tier&nbsp;B) and gum arabic add further formulation layers.
        AFS&thinsp;=&thinsp;29 drives most of the score.</li>
    <li>Gatorade (34) is the original &mdash; sugar + dextrose for energy, Yellow&nbsp;5 for color,
        gum arabic for mouthfeel. The 1965 formula, barely changed. MDS&thinsp;=&thinsp;3 from dextrose;
        Yellow&nbsp;5 is the only artificial color in this lineup until Pedialyte.</li>
    <li>Liquid&thinsp;I.V. (49) is the surprise: marketed as premium hydration, it scores highest on MLS
        (13) because it&rsquo;s a powder that concentrates sugar + dextrose + 500&thinsp;mg sodium into
        one stick. Silicon dioxide (anti-caking) and four Tier&nbsp;B salts (two citrates, phosphate, silicon dioxide) push AFS.</li>
    <li>Propel (52) is Gatorade&rsquo;s zero-calorie sibling &mdash; same parent company, very different
        formula. Maltodextrin + modified food starch replace sugar (MDS&thinsp;=&thinsp;8, highest here),
        while sucralose + acesulfame&nbsp;K provide sweetness. Calcium disodium EDTA (a chelating agent)
        is a rare Tier&nbsp;A ingredient that few consumers would recognize.</li>
    <li>Pedialyte Sport (62) is the extreme: 4 Tier&nbsp;A hits including Blue&nbsp;1 and artificial flavor.
        Designed for clinical rehydration, it uses dual NNS (sucralose + acesulfame&nbsp;K) and scores
        like a heavily processed food despite having only 30 calories.</li>
  </ul>

  <p style="color:{subtext};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">The Hydration Trade-off</p>
  <ul style="padding-left:20px;margin:0">
    <li>The scatter chart reveals two clusters: BODYARMOR and Gatorade deliver sodium through sugar-heavy
        formulas (21&ndash;25&thinsp;g); LMNT, Liquid&thinsp;I.V., and Pedialyte deliver high sodium
        (490&ndash;500&thinsp;mg) with minimal sugar. Processing fills the gap.</li>
    <li>AFS dominates this category: every product except LMNT has AFS as its largest sub-score.
        Electrolyte drinks are essentially additive-delivery systems &mdash; phosphate salts, gum
        stabilizers, NNS, and colors.</li>
    <li>Prime and Pedialyte both use sucralose + acesulfame&nbsp;K, but Pedialyte adds Blue&nbsp;1
        and artificial flavor &mdash; pushing AFS from 29 to 42 and composite from 32 to 62.</li>
    <li>The &ldquo;cleanest&rdquo; high-sodium option is LMNT (500&thinsp;mg, score 4). The next
        high-sodium option, Pedialyte (490&thinsp;mg), scores 15&times; higher. Same electrolytes,
        radically different formulation.</li>
  </ul>

  </div>
</div>

<div class="footer">
  Food Integrity Scale v0.9.1 &middot;
  Ingredient lists from public product packaging (Wegmans, Target)<br>
  Scores verified against scored_products.parquet. Bubble size = sugar grams per serving.
</div>
</body>
</html>
"""


def main():
    root = Path(__file__).parent.parent
    out_path = root / "demos" / "electrolytes.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building electrolyte drink comparison charts...")
    fig_stacked = chart_stacked_bar()
    fig_scatter = chart_scatter()
    fig_afs     = chart_afs_breakdown()

    html_stacked = pio.to_html(fig_stacked, full_html=False, include_plotlyjs=True)
    html_table   = build_table_html()
    html_scatter = pio.to_html(fig_scatter,  full_html=False, include_plotlyjs=False)
    html_afs     = pio.to_html(fig_afs,     full_html=False, include_plotlyjs=False)

    html = HTML_TEMPLATE.format(
        bg=BG, text=TEXT, subtext=SUBTEXT, grid=GRID,
        c_mds=C_MDS, c_afs=C_AFS, c_hes=C_HES, c_mls=C_MLS,
        chart_stacked=html_stacked,
        chart_table=html_table,
        chart_scatter=html_scatter,
        chart_afs=html_afs,
    )

    out_path.write_text(html, encoding="utf-8")
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"Saved: {out_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
