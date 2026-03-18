"""Interactive electrolyte drink comparison — FIS v0.9.1.

The Hydration Spectrum: from salt water to synthetic cocktail.

Generates demos/electrolytes.html

Run:  python analysis/electrolyte_comparison_interactive.py
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
        "name": "LMNT", "sub": "Sparkling Orange",
        "composite": 4, "mds": 0, "afs": 1, "hes": 3, "mls": 0,
        "class": "C1",
        "ingredients": "Sparkling water, salt (sodium chloride), citric acid, natural orange flavor, magnesium malate, potassium chloride, stevia leaf extract",
        "sugar_g": 0, "calories": 5, "sodium_mg": 500,
        "afs_a": 0, "afs_b": 0, "afs_c": 1,
        "tier_a": [], "tier_b": [], "tier_c": ["citric acid"],
        "flags_plain": "Water + electrolyte salts + stevia \u2014 minimal formulation",
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
        "flags_plain": "Coconut water base but 25g sugar \u2014 sport drink calories with natural branding",
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
        "flags_plain": "Yellow 5 (artificial color) + dextrose + gum arabic \u2014 the 1965 formula, barely changed",
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
        "flags_plain": "4 Tier A hits: blue 1, artificial flavor, 2 NNS \u2014 medical-grade formulation",
        "color": "#f7ff08",
    },
]


# ── Custom scatter: Sodium vs. Processing ──────────────────────────────

def chart_scatter():
    fig = go.Figure()
    for p in products:
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
        xaxis=dict(title="Sodium (mg per serving)", gridcolor=GRID, zeroline=False, range=[-30, 580]),
        yaxis=dict(title="Composite Score", gridcolor=GRID, zeroline=False, range=[-5, 72]),
        margin=dict(l=60, r=30, t=50, b=55),
        height=440,
    )
    return fig


# ── Analysis + footer ──────────────────────────────────────────────────

ANALYSIS_HTML = f"""\
  <p style="color:{TEXT};font-weight:600;font-size:1.05em;margin-bottom:16px">
    Seven electrolyte drinks, scores 4 to 62. They all promise the same thing &mdash; hydration &mdash;
    but the ingredient lists range from salt water to a synthetic cocktail of artificial colors,
    dual NNS systems, and industrial emulsifiers.
  </p>

  <p style="color:{SUBTEXT};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Key Takeaways</p>
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

  <p style="color:{SUBTEXT};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">The Hydration Trade-off</p>
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
  </ul>"""

FOOTER_HTML = (
    "  Food Integrity Scale v0.9.1 &middot;\n"
    "  Ingredient lists from public product packaging (Wegmans, Target)<br>\n"
    "  Scores verified against scored_products.parquet. Bubble size = sugar grams per serving."
)


# ── Main ───────────────────────────────────────────────────────────────

def main():
    root = Path(__file__).parent.parent
    out_path = root / "demos" / "electrolytes.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building electrolyte drink comparison charts...")
    fig_stacked = build_stacked_bar(products, y_max=72)
    fig_scatter = chart_scatter()
    fig_afs     = build_afs_breakdown(products)

    html = build_page(
        page_title="Electrolyte Drinks — The Hydration Spectrum — FIS v0.9.1",
        heading="The Hydration Spectrum",
        subtitle="Food Integrity Scale v0.9.1 &mdash; 7 electrolyte drinks, scores 4 to 62",
        stacked_html=pio.to_html(fig_stacked, full_html=False, include_plotlyjs="cdn"),
        table_html=build_ingredient_table(products, "Drink"),
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
