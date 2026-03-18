"""Interactive protein bar comparison — FIS v0.9.0.

Generates demos/protein_bars.html

Run:  python analysis/bar_comparison_interactive.py
"""

import plotly.graph_objects as go
import plotly.io as pio
from pathlib import Path

# ---------------------------------------------------------------------------
# Style — dark mode, blue + gold palette
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

# Per-bar: sequential navy→blue→grey→yellow
BAR_COLORS = {
    3:  "#6a8fd8",  # RXBAR — light blue
    4:  "#4a73c8",  # Larabar — medium blue
    6:  "#163fc7",  # GoMacro — royal blue
    28: "#042e99",  # Clif — deep navy
    36: "#474747",  # Kind — grey
    64: "#f7ff08",  # David — neon yellow
}

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
# Data — 6 bars (v0.9.0: EPG in Tier A + Bucket 3, allulose in Tier B)
# ---------------------------------------------------------------------------
bars = [
    {
        "name": "Larabar", "sub": "Cashew Cookie",
        "composite": 4, "mds": 0, "afs": 0, "hes": 0, "mls": 4,
        "class": "C0",
        "ingredients": "dates, cashews",
        "protein_g": 4, "calories": 230,
        "afs_a": 0, "afs_b": 0, "afs_c": 0,
        "tier_a": [], "tier_b": [], "tier_c": [],
        "flags_plain": "High total sugar (from dates only)",
    },
    {
        "name": "RXBAR", "sub": "Chocolate Sea Salt",
        "composite": 3, "mds": 0, "afs": 3, "hes": 0, "mls": 0,
        "class": "C1",
        "ingredients": "dates, egg whites, cashews, almonds, chocolate, cocoa, sea salt, natural flavors",
        "protein_g": 12, "calories": 200,
        "afs_a": 3, "afs_b": 0, "afs_c": 0,
        "tier_a": ["natural flavor"], "tier_b": [], "tier_c": [],
        "flags_plain": "1 formulation marker (natural flavors)",
    },
    {
        "name": "GoMacro", "sub": "Protein Paradise",
        "composite": 6, "mds": 5, "afs": 0, "hes": 0, "mls": 1,
        "class": "C1",
        "ingredients": "organic brown rice syrup, organic pea protein, organic almonds, organic cashew butter, organic sunflower seeds, organic tapioca syrup, organic coconut oil, organic puffed brown rice, organic vanilla, sea salt",
        "protein_g": 11, "calories": 260,
        "afs_a": 0, "afs_b": 0, "afs_c": 0,
        "tier_a": [], "tier_b": [], "tier_c": [],
        "flags_plain": "Protein isolate + brown rice syrup (matrix disruption only)",
    },
    {
        "name": "Clif Bar", "sub": "Chocolate Chip",
        "composite": 28, "mds": 12, "afs": 9, "hes": 4, "mls": 3,
        "class": "P1b",
        "ingredients": "organic rolled oats, organic brown rice syrup, soy protein isolate, cane syrup, oat fiber, soy flour, unsweetened chocolate, cocoa, soy lecithin, natural flavors, salt, mixed tocopherols",
        "protein_g": 10, "calories": 240,
        "afs_a": 5, "afs_b": 2, "afs_c": 2,
        "tier_a": ["natural flavor"], "tier_b": ["soy lecithin"], "tier_c": ["citric acid"],
        "flags_plain": "Protein isolate, soy lecithin, natural flavors, sweetener stacking",
    },
    {
        "name": "Kind Bar", "sub": "Dark Choc Nuts & Sea Salt",
        "composite": 36, "mds": 10, "afs": 7, "hes": 14, "mls": 5,
        "class": "P2a",
        "ingredients": "almonds, peanuts, chicory root fiber, honey, palm kernel oil, sugar, glucose syrup, dark chocolate, vegetable glycerin, rice flour, sea salt, soy lecithin, natural flavor",
        "protein_g": 6, "calories": 200,
        "afs_a": 4, "afs_b": 2, "afs_c": 1,
        "tier_a": ["natural flavor"], "tier_b": ["soy lecithin"], "tier_c": ["vegetable glycerin"],
        "flags_plain": "Coating fat + sweetener stacking = confection pattern, highest HES",
    },
    {
        "name": "David Bar", "sub": "Choc Chip Cookie Dough",
        "composite": 64, "mds": 18, "afs": 39, "hes": 7, "mls": 0,
        "class": "P3",
        "ingredients": "milk protein isolate, soluble corn fiber, collagen, soy lecithin, erythritol, EPG, maltitol, peanut flour, egg white, natural flavor, allulose, sucralose, acesulfame K",
        "protein_g": 28, "calories": 150,
        "afs_a": 27, "afs_b": 6, "afs_c": 6,
        "tier_a": ["natural flavor", "sucralose", "acesulfame potassium", "EPG"],
        "tier_b": ["soy lecithin", "allulose"],
        "tier_c": ["erythritol", "maltitol"],
        "flags_plain": "4 Tier A additives incl. EPG, 3 sweetener types, protein isolate + collagen",
    },
]

# Assign colors from sequential scale
for b in bars:
    b["color"] = BAR_COLORS[b["composite"]]


# ---------------------------------------------------------------------------
# Panel 1 — Stacked bar chart (hero)
# ---------------------------------------------------------------------------
def chart_stacked_bar():
    fig = go.Figure()
    names = [b["name"] for b in bars]

    sub_keys   = ["hes",  "afs",  "mds",  "mls"]
    sub_labels = ["HES",  "AFS",  "MDS",  "MLS"]
    sub_colors = [C_HES,  C_AFS,  C_MDS,  C_MLS]

    for key, label, color in zip(sub_keys, sub_labels, sub_colors):
        vals = [b[key] for b in bars]
        hover = [
            f"<b>{b['name']}</b><br>"
            f"{label} = {v}  |  Composite = {b['composite']}"
            for b, v in zip(bars, vals)
        ]
        fig.add_trace(go.Bar(
            x=names, y=vals, name=label,
            marker=dict(color=color, line_width=0), opacity=0.92,
            hovertemplate="%{hovertext}<extra></extra>",
            hovertext=hover,
        ))

    for b in bars:
        fig.add_annotation(
            x=b["name"], y=b["composite"] + 3,
            text=f"<b>{b['composite']}</b>",
            showarrow=False,
            font=dict(size=15, color=CLASS_COLORS.get(b["class"], TEXT)),
        )

    ticktext = [
        f"<b>{b['name']}</b><br>"
        f"{b['sub']}<br>"
        f"<span style='font-size:10px'>{TIER_NAMES[b['class']]}</span>"
        for b in bars
    ]

    fig.update_layout(
        **LAYOUT_DEFAULTS,
        barmode="stack",
        yaxis=dict(
            title="FIS Composite Score",
            gridcolor=GRID, zeroline=False, range=[0, 74],
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
# Panel 2 — Ingredient & flags table (pure HTML to match other tables)
# ---------------------------------------------------------------------------
def build_table_html():
    rows = []
    for b in bars:
        bar_color = b["color"]
        class_color = CLASS_COLORS.get(b["class"], TEXT)
        rows.append(
            f'    <tr>'
            f'<td class="axis-name">'
            f'{b["name"]}<br><span style="font-weight:400">{b["sub"]}</span></td>'
            f'<td>{b["ingredients"]}</td>'
            f'<td style="color:{class_color};font-weight:600">{TIER_NAMES[b["class"]]}</td>'
            f'<td>{b["flags_plain"]}</td>'
            f'</tr>'
        )
    return (
        '<table class="key-table">\n'
        '<colgroup><col style="width:100px"><col style="width:370px">'
        '<col style="width:200px"><col style="width:280px"></colgroup>\n'
        '    <tr><td class="axis-name">Bar</td>'
        '<td class="axis-name">Ingredients</td>'
        '<td class="axis-name">Class</td>'
        '<td class="axis-name">What FIS Detected</td></tr>\n'
        + "\n".join(rows) + "\n"
        '</table>'
    )


# ---------------------------------------------------------------------------
# Panel 3 — Protein vs. Processing scatter
# ---------------------------------------------------------------------------
def chart_scatter():
    fig = go.Figure()

    for b in bars:
        hover = (
            f"<b>{b['name']}</b><br>"
            f"{b['protein_g']}g protein  |  {b['calories']} cal<br>"
            f"Composite {b['composite']}  ({TIER_NAMES[b['class']]})"
        )
        fig.add_trace(go.Scatter(
            x=[b["protein_g"]], y=[b["composite"]],
            mode="markers+text",
            marker=dict(
                size=b["calories"] / 5.5,
                color=b["color"],
                opacity=0.85,
                line=dict(color="rgba(255,255,255,0.1)", width=1),
            ),
            text=[b["name"]],
            textposition="top center",
            textfont=dict(size=11, color=b["color"]),
            hovertemplate="%{hovertext}<extra></extra>",
            hovertext=[hover],
            showlegend=False,
        ))

    fig.update_layout(
        **LAYOUT_DEFAULTS,
        title=dict(
            text="Protein vs. Processing",
            font=dict(size=14, color=SUBTEXT), x=0.5,
        ),
        xaxis=dict(
            title="Protein (g)", gridcolor=GRID, zeroline=False,
            range=[-2, 35],
        ),
        yaxis=dict(
            title="Composite Score", gridcolor=GRID, zeroline=False,
            range=[-5, 75],
        ),
        margin=dict(l=55, r=20, t=40, b=50),
        height=420,
    )
    return fig


# ---------------------------------------------------------------------------
# Panel 4 — AFS tier breakdown (stacked horizontal, highest first)
# ---------------------------------------------------------------------------
def chart_afs_breakdown():
    fig = go.Figure()

    bars_rev = list(reversed(bars))
    names = [b["name"] for b in bars_rev]

    tiers = [
        ("Tier A", "afs_a", "tier_a", C_TIER_A, "industrial/synthetic"),
        ("Tier B", "afs_b", "tier_b", C_TIER_B, "processing aids"),
        ("Tier C", "afs_c", "tier_c", C_TIER_C, "mild/contextual"),
    ]

    for tier_name, val_key, list_key, color, desc in tiers:
        vals = [b[val_key] for b in bars_rev]
        hover = [
            f"<b>{b['name']}</b><br>"
            f"{tier_name}: {b[val_key]}"
            + (f"<br>{', '.join(b[list_key])}" if b[list_key] else "")
            for b in bars_rev
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
        margin=dict(l=80, r=20, t=40, b=70),
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
<title>Protein Bar Comparison — FIS v0.9.0</title>
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
<h1>Protein Bar Comparison</h1>
<div class="subtitle">Food Integrity Scale v0.9.0</div>

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
    These 6 bars span C0 to P3 &mdash; scores 3 to 64 &mdash; a 20&times; spread among products
    all marketed as &ldquo;protein bars.&rdquo;
  </p>

  <p style="color:{subtext};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Key Takeaways</p>
  <ul style="padding-left:20px;margin:0 0 20px 0">
    <li>Two bars (Larabar, RXBAR) are essentially clean &mdash; whole ingredients, minimal or no additives.</li>
    <li>The jump from RXBAR (3) to Clif (28) is where industrial formulation begins: protein isolates,
        emulsifiers, sweetener stacking.</li>
    <li>More protein doesn&rsquo;t mean more processing. RXBAR delivers 12&thinsp;g at a score of 3;
        David packs 28&thinsp;g but scores 64.</li>
    <li>David&rsquo;s MLS&thinsp;=&thinsp;0 despite being the most processed &mdash; non-nutritive sweeteners
        and sugar alcohols dodge every metabolic flag while stacking 4 Tier&nbsp;A additives.</li>
  </ul>

  <p style="color:{subtext};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Sub-score Deep Dive</p>
  <ul style="padding-left:20px;margin:0">
    <li>Each bar&rsquo;s dominant sub-score differs: MLS drives Larabar, MDS drives GoMacro,
        AFS dominates David, HES peaks at Kind.</li>
    <li>Kind&rsquo;s HES&thinsp;=&thinsp;14 (highest) comes from sweetener stacking &mdash;
        honey&thinsp;+&thinsp;sugar&thinsp;+&thinsp;glucose syrup creates a confection pattern.</li>
    <li>David&rsquo;s AFS&thinsp;=&thinsp;39 is extraordinary &mdash; EPG (fat replacer), sucralose,
        acesulfame&nbsp;K, plus natural flavors account for 4 Tier&nbsp;A hits alone.</li>
    <li>GoMacro shows MDS without AFS: organic pea protein isolate and brown rice syrup disrupt the
        ingredient matrix but add zero chemical additives.</li>
  </ul>

  </div>
</div>

<div class="footer">
  Food Integrity Scale v0.9.0 &middot;
  Ingredient lists from public product packaging<br>
  <b>v0.9.0:</b> EPG now Tier A + Bucket 3 (fat replacer).
  Allulose reclassified to Tier B rare sugar.
  David Bar: 46 &rarr; 64, P2b &rarr; P3.<br>
  EPG and allulose are GRAS in U.S.; not authorized EU; not permitted Canada.
</div>
</body>
</html>
"""


def main():
    root = Path(__file__).parent.parent
    out_path = root / "demos" / "protein_bars.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building charts...")
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
