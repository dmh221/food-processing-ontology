"""Interactive yogurt comparison — FIS v0.9.1.

The Diet Yogurt Paradox: the yogurt marketed as "Light" is the most processed.

Generates demos/yogurt.html

Run:  python analysis/yogurt_comparison_interactive.py
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


# ── Custom scatter: Sugar vs. Processing ───────────────────────────────

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
        title=dict(text="Sugar vs. Processing", font=dict(size=14, color=SUBTEXT), x=0.5),
        xaxis=dict(title="Total Sugar (g per serving)", gridcolor=GRID, zeroline=False, range=[0, 24]),
        yaxis=dict(title="Composite Score", gridcolor=GRID, zeroline=False, range=[-5, 60]),
        margin=dict(l=55, r=20, t=40, b=50),
        height=420,
    )
    return fig


# ── Analysis + footer ──────────────────────────────────────────────────

ANALYSIS_HTML = f"""\
  <p style="color:{TEXT};font-weight:600;font-size:1.05em;margin-bottom:16px">
    Six yogurts, scores 0 to 51. The one marketed as &ldquo;Light&rdquo; is the most processed.
    Plain Greek yogurt with 5 ingredients scores 0; Light&thinsp;+&thinsp;Fit &mdash; engineered
    to remove fat and sugar &mdash; needs sucralose, acesulfame&nbsp;K, artificial flavors, modified
    starch, and a preservative to taste like yogurt again.
  </p>

  <p style="color:{SUBTEXT};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">Key Takeaways</p>
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

  <p style="color:{SUBTEXT};font-size:0.88em;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 8px 0">The Paradox in Numbers</p>
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
  </ul>"""

FOOTER_HTML = (
    "  Food Integrity Scale v0.9.1 &middot;\n"
    "  Ingredient lists from public product packaging (Wegmans, Target)<br>\n"
    "  Scores verified against scored_products.parquet. Bubble size = calories per serving."
)


# ── Main ───────────────────────────────────────────────────────────────

def main():
    root = Path(__file__).parent.parent
    out_path = root / "demos" / "yogurt.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building yogurt comparison charts...")
    fig_stacked = build_stacked_bar(products, y_max=62)
    fig_scatter = chart_scatter()
    fig_afs     = build_afs_breakdown(products)

    html = build_page(
        page_title="Yogurt Comparison — The Diet Yogurt Paradox — FIS v0.9.1",
        heading="The Diet Yogurt Paradox",
        subtitle="Food Integrity Scale v0.9.1 &mdash; 6 yogurts, scores 0 to 51",
        stacked_html=pio.to_html(fig_stacked, full_html=False, include_plotlyjs=True),
        table_html=build_ingredient_table(products, "Yogurt"),
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
