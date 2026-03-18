"""Interactive nut butter comparison — FIS v0.9.1.

The Nut Butter Ladder: from raw peanuts to sugar-first spreads.

Generates demos/peanut_butter.html

Run:  python analysis/peanut_butter_comparison_interactive.py
"""

import plotly.graph_objects as go
import plotly.io as pio
from pathlib import Path

# ---------------------------------------------------------------------------
# Style — dark mode, earthy-to-synthetic palette
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
# Data — 6 nut butters (v0.9.1 from scored_products.parquet)
# ---------------------------------------------------------------------------
products = [
    {
        "name": "Smucker\u2019s Natural", "sub": "Creamy Peanut Butter",
        "composite": 0, "mds": 0, "afs": 0, "hes": 0, "mls": 0,
        "class": "C0",
        "ingredients": "Peanuts, contains 1% or less of salt",
        "fat_g": 16, "sugar_g": 2, "calories": 190, "protein_g": 8,
        "afs_a": 0, "afs_b": 0, "afs_c": 0,
        "tier_a": [], "tier_b": [], "tier_c": [],
        "flags_plain": "Nothing to flag \u2014 peanuts and salt, that\u2019s it",
        "color": "#c4883a",
    },
    {
        "name": "Justin\u2019s Classic", "sub": "Almond Butter",
        "composite": 0, "mds": 0, "afs": 0, "hes": 0, "mls": 0,
        "class": "C0",
        "ingredients": "Dry roasted almonds, palm oil",
        "fat_g": 19, "sugar_g": 1, "calories": 220, "protein_g": 6,
        "afs_a": 0, "afs_b": 0, "afs_c": 0,
        "tier_a": [], "tier_b": [], "tier_c": [],
        "flags_plain": "Almonds + palm oil \u2014 same clean score as natural peanut butter",
        "color": "#b8a070",
    },
    {
        "name": "Skippy Natural", "sub": "Creamy Peanut Butter",
        "composite": 4, "mds": 0, "afs": 0, "hes": 4, "mls": 0,
        "class": "C1",
        "ingredients": "Roasted peanuts, sugar, palm oil, salt",
        "fat_g": 16, "sugar_g": 3, "calories": 190, "protein_g": 7,
        "afs_a": 0, "afs_b": 0, "afs_c": 0,
        "tier_a": [], "tier_b": [], "tier_c": [],
        "flags_plain": "Sugar + palm oil barely move the needle \u2014 HES=4, no additives",
        "color": "#a07030",
    },
    {
        "name": "Justin\u2019s Honey", "sub": "Almond Butter",
        "composite": 17, "mds": 2, "afs": 0, "hes": 8, "mls": 7,
        "class": "P1a",
        "ingredients": "Dry roasted almonds, palm oil, organic honey, organic powdered sugar (organic cane sugar, organic tapioca starch), sea salt",
        "fat_g": 16, "sugar_g": 4, "calories": 200, "protein_g": 6,
        "afs_a": 0, "afs_b": 0, "afs_c": 0,
        "tier_a": [], "tier_b": [], "tier_c": [],
        "flags_plain": "Honey + powdered sugar = HES 8 + MLS 7 \u2014 still zero additives",
        "color": "#d4a040",
    },
    {
        "name": "Jif Creamy", "sub": "Peanut Butter",
        "composite": 25, "mds": 10, "afs": 6, "hes": 8, "mls": 1,
        "class": "P1b",
        "ingredients": "Roasted peanuts, sugar, contains 2% or less of: molasses, fully hydrogenated vegetable oils (rapeseed and soybean), mono and diglycerides, salt",
        "fat_g": 16, "sugar_g": 3, "calories": 190, "protein_g": 7,
        "afs_a": 6, "afs_b": 0, "afs_c": 0,
        "tier_a": ["mono- and diglycerides"], "tier_b": [], "tier_c": [],
        "flags_plain": "Hydrogenated oils + mono/diglycerides \u2014 first real industrial threshold",
        "color": "#d4943a",
    },
    {
        "name": "Nutella", "sub": "Hazelnut Spread",
        "composite": 34, "mds": 0, "afs": 10, "hes": 10, "mls": 14,
        "class": "P1b",
        "ingredients": "Sugar, palm oil, hazelnuts, skim milk, cocoa, lecithin as emulsifier, vanillin: an artificial flavor",
        "fat_g": 11, "sugar_g": 21, "calories": 200, "protein_g": 2,
        "afs_a": 6, "afs_b": 4, "afs_c": 0,
        "tier_a": ["artificial flavor"], "tier_b": ["lecithin"], "tier_c": [],
        "flags_plain": "Sugar is ingredient #1 \u2014 vanillin (artificial) + lecithin push AFS to 10",
        "color": "#474747",
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
            x=p["name"], y=p["composite"] + 2,
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
            gridcolor=GRID, zeroline=False, range=[0, 44],
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
        '    <tr><td class="axis-name">Product</td>'
        '<td class="axis-name">Ingredients</td>'
        '<td class="axis-name">Class</td>'
        '<td class="axis-name">What FIS Detected</td></tr>\n'
        + "\n".join(rows) + "\n"
        '</table>'
    )


# ---------------------------------------------------------------------------
# Panel 3 — Fat vs. Processing scatter (bubble = sugar grams)
# ---------------------------------------------------------------------------
def chart_scatter():
    fig = go.Figure()

    for p in products:
        hover = (
            f"<b>{p['name']}</b><br>"
            f"{p['fat_g']}g fat  |  {p['sugar_g']}g sugar<br>"
            f"Composite {p['composite']}  ({TIER_NAMES[p['class']]})"
        )
        fig.add_trace(go.Scatter(
            x=[p["fat_g"]], y=[p["composite"]],
            mode="markers+text",
            marker=dict(
                size=max(p["sugar_g"] * 2.5, 18),
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
            text="Fat vs. Processing",
            font=dict(size=14, color=SUBTEXT), x=0.5,
        ),
        xaxis=dict(
            title="Total Fat (g per serving)", gridcolor=GRID, zeroline=False,
            range=[5, 24],
        ),
        yaxis=dict(
            title="Composite Score", gridcolor=GRID, zeroline=False,
            range=[-5, 44],
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
<title>Nut Butter Comparison — The Nut Butter Ladder — FIS v0.9.1</title>
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
<h1>The Nut Butter Ladder</h1>
<div class="subtitle">Food Integrity Scale v0.9.1 &mdash; 6 nut butters and spreads, scores 0 to 34</div>

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
    Six nut butters and spreads, scores 0 to 34. Natural peanut butter and natural almond butter
    both score 0 &mdash; the nut type doesn&rsquo;t matter. It&rsquo;s what you add that counts:
    sweeteners, hydrogenated oils, emulsifiers, and artificial flavors build the ladder rung by rung.
  </p>

  <p style="color:{subtext};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Key Takeaways</p>
  <ul style="padding-left:20px;margin:0 0 20px 0">
    <li>Smucker&rsquo;s Natural (0) and Justin&rsquo;s Classic Almond (0) both score zero &mdash;
        peanut vs. almond makes no difference when the ingredient list is just nuts and oil.</li>
    <li>Skippy Natural (4) adds sugar and palm oil. HES&thinsp;=&thinsp;4 from the added sweetener,
        but still zero additives. The jump from 0 to 4 is minimal.</li>
    <li>Justin&rsquo;s Honey Almond (17) is the surprise: still zero AFS &mdash; no chemical
        additives at all &mdash; but honey + organic powdered sugar push HES to 8 and MLS to 7.
        Clean ingredients can still accumulate processing points through sweetener engineering.</li>
    <li>Jif Creamy (25) crosses the industrial threshold: fully hydrogenated vegetable oils and
        mono/diglycerides push MDS to 10 and trigger the first AFS. That one Tier&nbsp;A additive
        (mono/diglycerides) accounts for all of Jif&rsquo;s AFS&thinsp;=&thinsp;6.</li>
    <li>Nutella (34) &mdash; sugar is ingredient&thinsp;#1, not hazelnuts. Vanillin (an artificial
        flavor) and lecithin give it AFS&thinsp;=&thinsp;10, but the real driver is MLS&thinsp;=&thinsp;14:
        21&thinsp;g of sugar per serving.</li>
  </ul>

  <p style="color:{subtext};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Sub-score Deep Dive</p>
  <ul style="padding-left:20px;margin:0">
    <li>AFS stays at zero for 4 of 6 products. Only Jif (mono/diglycerides) and Nutella (vanillin
        + lecithin) trigger additive detection. Natural nut butters are inherently additive-free.</li>
    <li>MDS drives the Jif jump: MDS&thinsp;=&thinsp;10 from fully hydrogenated vegetable oils is
        the largest single sub-score leap in the lineup. The oils prevent separation but disrupt
        the ingredient matrix.</li>
    <li>HES does more work than expected: Justin&rsquo;s Honey Almond reaches P1a with zero additives,
        purely through sweetener layering (honey + powdered sugar = HES&thinsp;8).</li>
    <li>The scatter shows uniform fat: 5 of 6 products cluster at 16&ndash;19&thinsp;g fat.
        Nutella breaks the pattern &mdash; lower fat (11&thinsp;g) but 21&thinsp;g sugar,
        the only product where sugar dominates the nutrition profile.</li>
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
    out_path = root / "demos" / "peanut_butter.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building peanut butter comparison charts...")
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
