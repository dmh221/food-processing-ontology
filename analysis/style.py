"""FIS visualization design system.

Shared palette, layout defaults, and reusable chart/page builders
for all FIS interactive comparisons.
"""

import plotly.graph_objects as go
import plotly.io as pio

# ── Palette ────────────────────────────────────────────────────────────

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

# Processing class colors (green → red gradient)
CLASS_COLORS = {
    "W": "#4a5a2a", "Wp": "#4a5a2a",
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

# Sub-scores in stack order (bottom → top in vertical bars)
SUB_SCORES = [
    ("hes", "HES", C_HES),
    ("afs", "AFS", C_AFS),
    ("mds", "MDS", C_MDS),
    ("mls", "MLS", C_MLS),
]

# ── Plotly layout defaults ─────────────────────────────────────────────

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


# ── Chart builders ─────────────────────────────────────────────────────

def build_stacked_bar(products, y_max):
    """Vertical stacked bar chart of FIS sub-scores."""
    fig = go.Figure()
    names = [p["name"] for p in products]

    for key, label, color in SUB_SCORES:
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
            x=p["name"], y=p["composite"] + y_max * 0.04,
            text=f"<b>{p['composite']}</b>",
            showarrow=False,
            font=dict(size=15, color=CLASS_COLORS.get(p["class"], TEXT)),
        )

    ticktext = [
        f"<b>{p['name']}</b><br>"
        f"{p.get('sub', '')}<br>"
        f"<span style='font-size:10px'>{TIER_NAMES[p['class']]}</span>"
        for p in products
    ]

    fig.update_layout(
        **LAYOUT_DEFAULTS,
        barmode="stack",
        yaxis=dict(
            title="FIS Composite Score",
            gridcolor=GRID, zeroline=False, range=[0, y_max],
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


def build_afs_breakdown(products):
    """Horizontal stacked bar chart of AFS tiers."""
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


def build_ingredient_table(products, category_label="Product"):
    """HTML table of ingredients and FIS detection flags."""
    rows = []
    for p in products:
        class_color = CLASS_COLORS.get(p["class"], TEXT)
        rows.append(
            f'    <tr>'
            f'<td class="axis-name">'
            f'{p["name"]}<br><span style="font-weight:400">{p.get("sub", "")}</span></td>'
            f'<td>{p["ingredients"]}</td>'
            f'<td style="color:{class_color};font-weight:600">{TIER_NAMES[p["class"]]}</td>'
            f'<td>{p["flags_plain"]}</td>'
            f'</tr>'
        )
    return (
        '<table class="key-table">\n'
        '<colgroup><col style="width:110px"><col style="width:360px">'
        '<col style="width:200px"><col style="width:280px"></colgroup>\n'
        f'    <tr><td class="axis-name">{category_label}</td>'
        '<td class="axis-name">Ingredients</td>'
        '<td class="axis-name">Class</td>'
        '<td class="axis-name">What FIS Detected</td></tr>\n'
        + "\n".join(rows) + "\n"
        '</table>'
    )


# ── Page assembly ──────────────────────────────────────────────────────

def build_page(*, page_title, heading, subtitle, stacked_html, table_html,
               scatter_html, afs_html, analysis_html, footer_html):
    """Assemble a complete FIS comparison HTML page.

    All CSS, sub-score key, and classification tier sections are baked in
    from the shared palette — comparison scripts only supply variable content.
    """
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{page_title}</title>\n'
        '<style>\n'
        f'  body {{\n'
        f'    background: {BG};\n'
        f'    color: {TEXT};\n'
        f'    font-family: "Open Sans", sans-serif;\n'
        f'    margin: 0 auto;\n'
        f'    padding: 40px 48px;\n'
        f'    max-width: 1300px;\n'
        f'  }}\n'
        f'  h1 {{\n'
        f'    text-align: center;\n'
        f'    font-size: 1.5em;\n'
        f'    font-weight: 600;\n'
        f'    margin: 0 0 2px 0;\n'
        f'  }}\n'
        f'  .subtitle {{\n'
        f'    text-align: center;\n'
        f'    color: {SUBTEXT};\n'
        f'    font-size: 0.82em;\n'
        f'    margin-bottom: 28px;\n'
        f'  }}\n'
        f'  .section {{\n'
        f'    margin-bottom: 48px;\n'
        f'  }}\n'
        f'  .section-label {{\n'
        f'    color: {SUBTEXT};\n'
        f'    font-size: 0.75em;\n'
        f'    text-transform: uppercase;\n'
        f'    letter-spacing: 1.5px;\n'
        f'    margin-bottom: 8px;\n'
        f'  }}\n'
        f'  .key-table {{\n'
        f'    width: 100%;\n'
        f'    border-collapse: collapse;\n'
        f'    font-size: 0.82em;\n'
        f'  }}\n'
        f'  .key-table td {{\n'
        f'    padding: 6px 14px;\n'
        f'    border-bottom: 1px solid {GRID};\n'
        f'    vertical-align: top;\n'
        f'  }}\n'
        f'  .key-table .axis-name {{\n'
        f'    font-weight: 600;\n'
        f'    white-space: nowrap;\n'
        f'    width: 120px;\n'
        f'  }}\n'
        f'  .key-table .range {{\n'
        f'    color: {SUBTEXT};\n'
        f'    white-space: nowrap;\n'
        f'    width: 70px;\n'
        f'    text-align: right;\n'
        f'  }}\n'
        f'  .row {{\n'
        f'    display: flex;\n'
        f'    gap: 24px;\n'
        f'  }}\n'
        f'  .row .col {{\n'
        f'    flex: 1;\n'
        f'    min-width: 0;\n'
        f'  }}\n'
        f'  .footer {{\n'
        f'    text-align: center;\n'
        f'    color: {SUBTEXT};\n'
        f'    font-size: 0.72em;\n'
        f'    padding: 20px 0 0 0;\n'
        f'    border-top: 1px solid {GRID};\n'
        f'    line-height: 1.8;\n'
        f'  }}\n'
        '</style>\n</head>\n<body>\n'
        f'<h1>{heading}</h1>\n'
        f'<div class="subtitle">{subtitle}</div>\n\n'
        # ── Sub-score key ──
        '<div class="section">\n'
        '  <div class="section-label">Sub-scores</div>\n'
        '  <table class="key-table">\n'
        f'    <tr>\n'
        f'      <td class="axis-name" style="color:{C_MLS}">MLS</td>\n'
        f'      <td>How extreme the nutrition label is &mdash; flagging high sugar, sodium, saturated fat, and energy-dense sweet formulations.</td>\n'
        f'      <td class="range">0&ndash;20</td>\n'
        f'    </tr>\n'
        f'    <tr>\n'
        f'      <td class="axis-name" style="color:{C_MDS}">MDS</td>\n'
        f'      <td>How many core ingredients have been replaced by industrial substitutes (modified starches, hydrogenated fats, HFCS, protein isolates).</td>\n'
        f'      <td class="range">0&ndash;30</td>\n'
        f'    </tr>\n'
        f'    <tr>\n'
        f'      <td class="axis-name" style="color:{C_AFS}">AFS</td>\n'
        f'      <td>How many chemical additives are stacked in &mdash; emulsifiers, preservatives, artificial colors, flavor enhancers.</td>\n'
        f'      <td class="range">0&ndash;80</td>\n'
        f'    </tr>\n'
        f'    <tr>\n'
        f'      <td class="axis-name" style="color:{C_HES}">HES</td>\n'
        f'      <td>How engineered the sweetener system is &mdash; sugar alcohols, non-nutritive sweeteners, and multi-sweetener blending strategies.</td>\n'
        f'      <td class="range">0&ndash;20</td>\n'
        f'    </tr>\n'
        f'    <tr style="border-top: 1px solid {SUBTEXT}">\n'
        f'      <td class="axis-name">Composite</td>\n'
        f'      <td>MDS + AFS + HES + MLS. How far a product has moved from recognizable food.</td>\n'
        f'      <td class="range">0&ndash;150</td>\n'
        f'    </tr>\n'
        '  </table>\n'
        '</div>\n\n'
        # ── Classification tiers ──
        '<div class="section">\n'
        '  <div class="section-label">Classification tiers</div>\n'
        '  <div class="row" style="gap: 48px">\n'
        '    <div class="col">\n'
        '      <table class="key-table">\n'
        f'        <tr><td colspan="3" style="color:{SUBTEXT};font-size:0.9em;padding-bottom:8px">\n'
        f'          <b style="color:{TEXT}">Processing class</b> &mdash; derived from composite score\n'
        f'        </td></tr>\n'
        f'        <tr><td class="axis-name" style="color:#65763c">C0</td><td>Clean</td><td class="range">0</td></tr>\n'
        f'        <tr><td class="axis-name" style="color:#8da554">C1</td><td>Clean, Minimal Markers</td><td class="range">1&ndash;5</td></tr>\n'
        f'        <tr><td class="axis-name" style="color:#b5c45a">P1a</td><td>Light Processing</td><td class="range">6&ndash;15</td></tr>\n'
        f'        <tr><td class="axis-name" style="color:#d5c248">P1b</td><td>Moderate-Light Processing</td><td class="range">16&ndash;25</td></tr>\n'
        f'        <tr><td class="axis-name" style="color:#d4943a">P2a</td><td>Moderate Processing</td><td class="range">26&ndash;38</td></tr>\n'
        f'        <tr><td class="axis-name" style="color:#c8603a">P2b</td><td>Moderate-Heavy Processing</td><td class="range">39&ndash;50</td></tr>\n'
        f'        <tr><td class="axis-name" style="color:#d14136">P3</td><td>Heavy Industrial Formulation</td><td class="range">51&ndash;75</td></tr>\n'
        f'        <tr><td class="axis-name" style="color:#8b2520">P4</td><td>Ultra-Formulated</td><td class="range">76+</td></tr>\n'
        '      </table>\n'
        '    </div>\n'
        '    <div class="col">\n'
        '      <table class="key-table">\n'
        f'        <tr><td colspan="3" style="color:{SUBTEXT};font-size:0.9em;padding-bottom:8px">\n'
        f'          <b style="color:{TEXT}">Metabolic class</b> &mdash; derived from MLS\n'
        f'        </td></tr>\n'
        '        <tr><td class="axis-name" style="color:#8ab4d6">N0</td><td>No Metabolic Load</td><td class="range">0</td></tr>\n'
        '        <tr><td class="axis-name" style="color:#4a73c8">N0+</td><td>Minimal</td><td class="range">1&ndash;3</td></tr>\n'
        '        <tr><td class="axis-name" style="color:#163fc7">N1a</td><td>Low</td><td class="range">4&ndash;6</td></tr>\n'
        '        <tr><td class="axis-name" style="color:#042e99">N1b</td><td>Low-Moderate</td><td class="range">7&ndash;8</td></tr>\n'
        '        <tr><td class="axis-name" style="color:#d5c248">N2</td><td>Moderate</td><td class="range">9&ndash;14</td></tr>\n'
        '        <tr><td class="axis-name" style="color:#f7ff08">N3</td><td>High</td><td class="range">15+</td></tr>\n'
        '      </table>\n'
        '    </div>\n'
        '  </div>\n'
        '</div>\n\n'
        # ── Charts + content ──
        f'<div class="section">{stacked_html}</div>\n\n'
        '<div class="section">\n'
        '  <div class="section-label">Ingredient detail</div>\n'
        f'  {table_html}\n'
        '</div>\n\n'
        '<div class="section">\n'
        '  <div class="row">\n'
        f'    <div class="col">{scatter_html}</div>\n'
        f'    <div class="col">{afs_html}</div>\n'
        '  </div>\n'
        '</div>\n\n'
        '<div class="section">\n'
        '  <div class="section-label">Analysis</div>\n'
        '  <div style="font-size:0.88em;line-height:1.75;max-width:960px;margin:0 auto">\n'
        f'{analysis_html}\n'
        '  </div>\n'
        '</div>\n\n'
        f'<div class="footer">\n{footer_html}\n</div>\n'
        '</body>\n</html>'
    )
