"""Interactive protein bar comparison — FIS v0.9.0.

Generates demos/protein_bars.html

Run:  python analysis/bar_comparison_interactive.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import plotly.graph_objects as go
import plotly.io as pio

from style import (
    BG, PANEL, GRID, TEXT, SUBTEXT,
    C_MDS, C_AFS, C_HES, C_MLS,
    CLASS_COLORS, TIER_NAMES, LAYOUT_DEFAULTS,
    build_stacked_bar, build_afs_breakdown, build_ingredient_table, build_page,
)

# ── Data ───────────────────────────────────────────────────────────────

# Per-bar colors: sequential navy→blue→grey→yellow
BAR_COLORS = {
    3:  "#6a8fd8",  # RXBAR — light blue
    4:  "#4a73c8",  # Larabar — medium blue
    6:  "#163fc7",  # GoMacro — royal blue
    28: "#042e99",  # Clif — deep navy
    36: "#8a8a9a",  # Kind — light grey
    64: "#f7ff08",  # David — neon yellow
}

products = [
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

for p in products:
    p["color"] = BAR_COLORS[p["composite"]]


# ── Custom scatter: Protein vs. Processing ─────────────────────────────

def chart_scatter():
    fig = go.Figure()
    for p in products:
        hover = (
            f"<b>{p['name']}</b><br>"
            f"{p['protein_g']}g protein  |  {p['calories']} cal<br>"
            f"Composite {p['composite']}  ({TIER_NAMES[p['class']]})"
        )
        fig.add_trace(go.Scatter(
            x=[p["protein_g"]], y=[p["composite"]],
            mode="markers+text",
            marker=dict(
                size=p["calories"] / 5.5,
                color=p["color"],
                opacity=0.85,
                line=dict(color="rgba(255,255,255,0.1)", width=1),
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
        title=dict(text="Protein vs. Processing  (bubble = calories)", font=dict(size=14, color=SUBTEXT), x=0.5),
        xaxis=dict(title="Protein (g)", gridcolor=GRID, zeroline=False, range=[-2, 32]),
        yaxis=dict(title="Composite Score", gridcolor=GRID, zeroline=False, range=[-5, 75]),
        margin=dict(l=60, r=30, t=50, b=55),
        height=440,
    )
    return fig


# ── Analysis + footer ──────────────────────────────────────────────────

ANALYSIS_HTML = f"""\
  <p style="color:{TEXT};font-weight:600;font-size:1.05em;margin-bottom:16px">
    These 6 bars span C0 to P3 &mdash; scores 3 to 64 &mdash; a 20&times; spread among products
    all marketed as &ldquo;protein bars.&rdquo;
  </p>

  <p style="color:{SUBTEXT};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Key Takeaways</p>
  <ul style="padding-left:20px;margin:0 0 20px 0">
    <li>Two bars (Larabar, RXBAR) are essentially clean &mdash; whole ingredients, minimal or no additives.</li>
    <li>The jump from RXBAR (3) to Clif (28) is where industrial formulation begins: protein isolates,
        emulsifiers, sweetener stacking.</li>
    <li>More protein doesn&rsquo;t mean more processing. RXBAR delivers 12&thinsp;g at a score of 3;
        David packs 28&thinsp;g but scores 64.</li>
    <li>David&rsquo;s MLS&thinsp;=&thinsp;0 despite being the most processed &mdash; non-nutritive sweeteners
        and sugar alcohols dodge every metabolic flag while stacking 4 Tier&nbsp;A additives.</li>
  </ul>

  <p style="color:{SUBTEXT};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Sub-score Deep Dive</p>
  <ul style="padding-left:20px;margin:0">
    <li>Each bar&rsquo;s dominant sub-score differs: MLS drives Larabar, MDS drives GoMacro,
        AFS dominates David, HES peaks at Kind.</li>
    <li>Kind&rsquo;s HES&thinsp;=&thinsp;14 (highest) comes from sweetener stacking &mdash;
        honey&thinsp;+&thinsp;sugar&thinsp;+&thinsp;glucose syrup creates a confection pattern.</li>
    <li>David&rsquo;s AFS&thinsp;=&thinsp;39 is extraordinary &mdash; EPG (fat replacer), sucralose,
        acesulfame&nbsp;K, plus natural flavors account for 4 Tier&nbsp;A hits alone.</li>
    <li>GoMacro shows MDS without AFS: organic pea protein isolate and brown rice syrup disrupt the
        ingredient matrix but add zero chemical additives.</li>
  </ul>"""

FOOTER_HTML = (
    "  Food Integrity Scale v0.9.0 &middot;\n"
    "  Ingredient lists from public product packaging<br>\n"
    "  <b>v0.9.0:</b> EPG now Tier A + Bucket 3 (fat replacer).\n"
    "  Allulose reclassified to Tier B rare sugar.\n"
    "  David Bar: 46 &rarr; 64, P2b &rarr; P3.<br>\n"
    "  EPG and allulose are GRAS in U.S.; not authorized EU; not permitted Canada."
)


# ── Main ───────────────────────────────────────────────────────────────

def main():
    root = Path(__file__).parent.parent
    out_path = root / "demos" / "protein_bars.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building charts...")
    fig_stacked = build_stacked_bar(products, y_max=74)
    fig_scatter = chart_scatter()
    fig_afs     = build_afs_breakdown(products)

    html = build_page(
        page_title="Protein Bar Comparison — FIS v0.9.0",
        heading="Protein Bar Comparison",
        subtitle="Food Integrity Scale v0.9.0",
        stacked_html=pio.to_html(fig_stacked, full_html=False, include_plotlyjs="cdn"),
        table_html=build_ingredient_table(products, "Bar"),
        scatter_html=pio.to_html(fig_scatter, full_html=False, include_plotlyjs=False),
        afs_html=pio.to_html(fig_afs, full_html=False, include_plotlyjs=False),
        analysis_html=ANALYSIS_HTML,
        footer_html=FOOTER_HTML,
    )

    out_path.write_text(html, encoding="utf-8")
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"Saved: {out_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
