"""Interactive nut butter comparison — FIS v0.9.1.

The Nut Butter Ladder: from raw peanuts to sugar-first spreads.

Generates demos/peanut_butter.html

Run:  python analysis/peanut_butter_comparison_interactive.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import plotly.graph_objects as go
import plotly.io as pio

from style import (
    BG, PANEL, GRID, TEXT, SUBTEXT,
    CLASS_COLORS, TIER_NAMES, LAYOUT_DEFAULTS,
    build_stacked_bar, build_afs_breakdown, build_ingredient_table, build_page,
)

# ── Data ───────────────────────────────────────────────────────────────

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


# ── Custom scatter: Fat vs. Processing ─────────────────────────────────

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
        title=dict(text="Fat vs. Processing", font=dict(size=14, color=SUBTEXT), x=0.5),
        xaxis=dict(title="Total Fat (g per serving)", gridcolor=GRID, zeroline=False, range=[5, 24]),
        yaxis=dict(title="Composite Score", gridcolor=GRID, zeroline=False, range=[-5, 44]),
        margin=dict(l=55, r=20, t=40, b=50),
        height=420,
    )
    return fig


# ── Analysis + footer ──────────────────────────────────────────────────

ANALYSIS_HTML = f"""\
  <p style="color:{TEXT};font-weight:600;font-size:1.05em;margin-bottom:16px">
    Six nut butters and spreads, scores 0 to 34. Natural peanut butter and natural almond butter
    both score 0 &mdash; the nut type doesn&rsquo;t matter. It&rsquo;s what you add that counts:
    sweeteners, hydrogenated oils, emulsifiers, and artificial flavors build the ladder rung by rung.
  </p>

  <p style="color:{SUBTEXT};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Key Takeaways</p>
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

  <p style="color:{SUBTEXT};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Sub-score Deep Dive</p>
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
  </ul>"""

FOOTER_HTML = (
    "  Food Integrity Scale v0.9.1 &middot;\n"
    "  Ingredient lists from public product packaging (Wegmans, Target)<br>\n"
    "  Scores verified against scored_products.parquet. Bubble size = sugar grams per serving."
)


# ── Main ───────────────────────────────────────────────────────────────

def main():
    root = Path(__file__).parent.parent
    out_path = root / "demos" / "peanut_butter.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building peanut butter comparison charts...")
    fig_stacked = build_stacked_bar(products, y_max=44)
    fig_scatter = chart_scatter()
    fig_afs     = build_afs_breakdown(products)

    html = build_page(
        page_title="Nut Butter Comparison — The Nut Butter Ladder — FIS v0.9.1",
        heading="The Nut Butter Ladder",
        subtitle="Food Integrity Scale v0.9.1 &mdash; 6 nut butters and spreads, scores 0 to 34",
        stacked_html=pio.to_html(fig_stacked, full_html=False, include_plotlyjs="cdn"),
        table_html=build_ingredient_table(products, "Product"),
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
