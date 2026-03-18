"""Interactive yogurt comparison — FIS v0.9.1.

The Diet Yogurt Paradox: the yogurt marketed as "Light" is the most processed.

Generates demos/yogurt.html

Run:  python analysis/yogurt_comparison_interactive.py
"""

import plotly.graph_objects as go
import plotly.io as pio
from pathlib import Path

# ---------------------------------------------------------------------------
# Style — dark mode, creamy-to-synthetic palette
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
# Data — 6 yogurts (v0.9.1 scores from scored_products.parquet)
# ---------------------------------------------------------------------------
products = [
    {
        "name": "Fage Total 5%", "sub": "Plain Greek Yogurt",
        "composite": 0, "mds": 0, "afs": 0, "hes": 0, "mls": 0,
        "class": "C0",
        "ingredients": "Grade A pasteurized skimmed milk and cream, live active yogurt cultures (L. bulgaricus, S. thermophilus, L. acidophilus, Bifidus, L. casei)",
        "sugar_g": 5, "calories": 160, "protein_g": 15,
        "afs_a": 0, "afs_b": 0, "afs_c": 0,
        "tier_a": [], "tier_b": [], "tier_c": [],
        "flags_plain": "Nothing to flag \u2014 milk, cultures, nothing else",
        "color": "#f5e6c8",
    },
    {
        "name": "Siggi\u2019s", "sub": "Lowfat Strawberry Banana",
        "composite": 9, "mds": 0, "afs": 5, "hes": 4, "mls": 0,
        "class": "P1a",
        "ingredients": "Cultured pasteurized skim milk, pasteurized cream, cane sugar, strawberry puree, banana puree, natural flavors, fruit pectin",
        "sugar_g": 11, "calories": 140, "protein_g": 15,
        "afs_a": 4, "afs_b": 0, "afs_c": 1,
        "tier_a": ["natural flavor"], "tier_b": [], "tier_c": ["pectin"],
        "flags_plain": "Natural flavors + fruit pectin \u2014 first formulation step",
        "color": "#c4a35a",
    },
    {
        "name": "Chobani", "sub": "Strawberry on the Bottom",
        "composite": 20, "mds": 3, "afs": 13, "hes": 4, "mls": 0,
        "class": "P1b",
        "ingredients": "Cultured lowfat milk, cane sugar, strawberries, water, bananas, fruit pectin, guar gum, natural flavors, fruit and vegetable juice concentrate (for color), lemon juice concentrate, locust bean gum",
        "sugar_g": 14, "calories": 130, "protein_g": 11,
        "afs_a": 4, "afs_b": 7, "afs_c": 2,
        "tier_a": ["natural flavor"], "tier_b": ["guar gum", "locust bean gum"], "tier_c": ["pectin"],
        "flags_plain": "Fruit prep = juice concentrates, 2 gums, colors \u2014 manufactured component",
        "color": "#d47a5a",
    },
    {
        "name": "Yoplait Original", "sub": "Strawberry",
        "composite": 27, "mds": 8, "afs": 9, "hes": 4, "mls": 6,
        "class": "P1b",
        "ingredients": "Cultured grade A low fat milk, sugar, strawberries, modified food starch, water, kosher gelatin, corn starch, carmine (for color), pectin, natural flavor, vitamin A acetate, vitamin D3",
        "sugar_g": 18, "calories": 140, "protein_g": 5,
        "afs_a": 4, "afs_b": 3, "afs_c": 2,
        "tier_a": ["natural flavor"], "tier_b": ["gelatin"], "tier_c": ["pectin"],
        "flags_plain": "Modified starch + gelatin + carmine \u2014 mainstream formulation",
        "color": "#8b5a8a",
    },
    {
        "name": "Light + Fit", "sub": "Nonfat Strawberry Greek",
        "composite": 40, "mds": 5, "afs": 28, "hes": 7, "mls": 0,
        "class": "P2b",
        "ingredients": "Cultured non fat milk, water, less than 1%: natural & artificial flavors, black carrot juice (for color), modified food starch, acesulfame potassium, sucralose, fructose, malic acid, potassium sorbate, yogurt cultures",
        "sugar_g": 7, "calories": 80, "protein_g": 12,
        "afs_a": 20, "afs_b": 5, "afs_c": 3,
        "tier_a": ["artificial flavor", "sucralose", "acesulfame K"],
        "tier_b": ["potassium sorbate"],
        "tier_c": ["malic acid"],
        "flags_plain": "3 Tier A additives: sucralose, acesulfame K, artificial flavor \u2014 diet paradox begins",
        "color": "#474747",
    },
    {
        "name": "Light + Fit Greek", "sub": "Fat Free Banana Cream",
        "composite": 51, "mds": 8, "afs": 36, "hes": 7, "mls": 0,
        "class": "P3",
        "ingredients": "Cultured pasteurized non fat milk, water, fructose, less than 1%: banana puree, natural and artificial flavors, fruit & vegetable juice concentrate and beta carotene (for color), modified food starch, pectin, xanthan gum, acesulfame potassium, sucralose, malic acid, potassium sorbate",
        "sugar_g": 7, "calories": 80, "protein_g": 12,
        "afs_a": 20, "afs_b": 8, "afs_c": 8,
        "tier_a": ["artificial flavor", "sucralose", "acesulfame K"],
        "tier_b": ["xanthan gum", "potassium sorbate"],
        "tier_c": ["pectin", "malic acid", "beta carotene"],
        "flags_plain": "3 Tier A + 2 Tier B + 3 Tier C \u2014 most additives, lowest sugar, highest AFS",
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
            x=p["name"], y=p["composite"] + 2.5,
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
            gridcolor=GRID, zeroline=False, range=[0, 62],
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
        '    <tr><td class="axis-name">Yogurt</td>'
        '<td class="axis-name">Ingredients</td>'
        '<td class="axis-name">Class</td>'
        '<td class="axis-name">What FIS Detected</td></tr>\n'
        + "\n".join(rows) + "\n"
        '</table>'
    )


# ---------------------------------------------------------------------------
# Panel 3 — Sugar vs. Processing scatter (bubble = calories)
# ---------------------------------------------------------------------------
def chart_scatter():
    fig = go.Figure()

    for p in products:
        hover = (
            f"<b>{p['name']}</b><br>"
            f"{p['sugar_g']}g sugar  |  {p['calories']} cal<br>"
            f"Composite {p['composite']}  ({TIER_NAMES[p['class']]})"
        )
        fig.add_trace(go.Scatter(
            x=[p["sugar_g"]], y=[p["composite"]],
            mode="markers+text",
            marker=dict(
                size=p["calories"] / 3.5,
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
            text="Sugar vs. Processing",
            font=dict(size=14, color=SUBTEXT), x=0.5,
        ),
        xaxis=dict(
            title="Total Sugar (g per serving)", gridcolor=GRID, zeroline=False,
            range=[0, 24],
        ),
        yaxis=dict(
            title="Composite Score", gridcolor=GRID, zeroline=False,
            range=[-5, 60],
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
<title>Yogurt Comparison — The Diet Yogurt Paradox — FIS v0.9.1</title>
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
<h1>The Diet Yogurt Paradox</h1>
<div class="subtitle">Food Integrity Scale v0.9.1 &mdash; 6 yogurts, scores 0 to 51</div>

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
    Six yogurts, scores 0 to 51. The one marketed as &ldquo;Light&rdquo; is the most processed.
    Plain Greek yogurt with 5 ingredients scores 0; Light&thinsp;+&thinsp;Fit &mdash; engineered
    to remove fat and sugar &mdash; needs sucralose, acesulfame&nbsp;K, artificial flavors, modified
    starch, and a preservative to taste like yogurt again.
  </p>

  <p style="color:{subtext};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Key Takeaways</p>
  <ul style="padding-left:20px;margin:0 0 20px 0">
    <li>Fage Total 5% (0) is the baseline &mdash; milk and cultures, nothing else. Whole-milk fat
        is present but the ingredient list is as short as yogurt gets.</li>
    <li>Siggi&rsquo;s (9) introduces the first formulation markers: natural flavors and fruit pectin.
        Still clean by most standards, but FIS detects the step.</li>
    <li>Chobani&rsquo;s &ldquo;fruit on the bottom&rdquo; (20) reveals that the &ldquo;fruit&rdquo;
        is a manufactured component &mdash; juice concentrates, two gums, and colors.</li>
    <li>Yoplait Original (27) is mainstream processing: modified food starch, gelatin, corn starch,
        and carmine (a red colorant from cochineal insects).</li>
    <li>Light&thinsp;+&thinsp;Fit Strawberry (40) is the paradox: 3 Tier&nbsp;A additives
        (sucralose, acesulfame&nbsp;K, artificial flavor) replace the sugar and fat that were removed.
        MLS&thinsp;=&thinsp;0 because there&rsquo;s nothing left to flag metabolically.</li>
    <li>Light&thinsp;+&thinsp;Fit Banana Cream (51) is the extreme: same 3 Tier&nbsp;A hits plus
        xanthan gum, potassium sorbate, pectin, malic acid, and beta carotene. AFS&thinsp;=&thinsp;36
        drives the score into P3.</li>
  </ul>

  <p style="color:{subtext};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">The Paradox in Numbers</p>
  <ul style="padding-left:20px;margin:0">
    <li>The scatter chart tells the story: as sugar drops from 18&thinsp;g (Yoplait) to 7&thinsp;g
        (Light&thinsp;+&thinsp;Fit), processing climbs from 27 to 51. The trade-off is real.</li>
    <li>Metabolic class inverts: Fage (whole milk, 5&thinsp;g sugar) is N0; Yoplait (18&thinsp;g
        sugar) is N1a. But Light&thinsp;+&thinsp;Fit (7&thinsp;g sugar) drops back to N0 &mdash;
        the &ldquo;healthier&rdquo; yogurt has a better metabolic score but 10&times; the processing.</li>
    <li>AFS dominates the diet end: Light&thinsp;+&thinsp;Fit Banana Cream&rsquo;s AFS of 36
        is higher than many candy bars. Fage&rsquo;s AFS is 0.</li>
    <li>MDS drives the mainstream middle: Yoplait&rsquo;s MDS&thinsp;=&thinsp;8 (modified starch,
        corn starch) accounts for most of its score alongside AFS&thinsp;=&thinsp;9.</li>
  </ul>

  </div>
</div>

<div class="footer">
  Food Integrity Scale v0.9.1 &middot;
  Ingredient lists from public product packaging (Wegmans, Target)<br>
  Scores verified against scored_products.parquet. Bubble size = calories per serving.
</div>
</body>
</html>
"""


def main():
    root = Path(__file__).parent.parent
    out_path = root / "demos" / "yogurt.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building yogurt comparison charts...")
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
