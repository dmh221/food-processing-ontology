# Food Processing Ontology

A domain-specific ontology and deterministic classification system for evaluating food processing, additive formulation, hyperpalatability engineering, and metabolic load across real-world consumer products.

Its core scoring framework, the **Food Integrity Scale (FIS)**, uses multi-axis deterministic rules to classify products from ingredient lists and nutrition panels, extending beyond binary NOVA-style labeling. Built from first principles using large-scale product data from four U.S. grocery retailers (28,000+ products).

<p align="center">
  <img src="docs/fis_hero.png" alt="FIS sub-score decomposition — protein bars and electrolyte drinks" width="900">
</p>

<p align="center">
  <img src="docs/fis_hero_protein_bars.png" alt="Protein bars — protein vs processing scatter and AFS tier breakdown" width="900">
</p>

<p align="center">
  <img src="docs/fis_hero_electrolytes.png" alt="Electrolyte drinks — sodium vs processing scatter and AFS tier breakdown" width="900">
</p>

## The Problem

Existing classification systems (NOVA, EPIC, Siga) share three structural failures:

1. **Binary classification destroys information** — NOVA places Fanta and a yogurt with xanthan gum in the same group. Within what NOVA calls "ultra-processed," FIS scores range from 16 to 97.
2. **Low inter-rater reliability** — Expert agreement on NOVA is ~0.33 Fleiss' kappa — specialists disagree more often than they agree.
3. **Single-axis systems conflate mechanisms** — Nutrient profile, additive load, matrix disruption, and hyperpalatability engineering are four distinct exposures bundled under one label.

## System Architecture

```
Product data (name, ingredients, nutrition, serving size)
    |
    v
Ingredient normalization
    Allergen stripping, enrichment context removal,
    store-aware parsing, nesting depth analysis
    |
    v
Taxonomy classification (11 families, 64 subfamilies)
    LLM classifier (Claude Haiku) + deterministic fallback
    SHA-256 cached to disk, version-gated
    |
    v
Ontology pattern matching (174 regex patterns)
    Tier A/B/C additives, Bucket 2/3 substrates,
    HES sweetener/fat/flavor lists
    |
    v
Four-axis scoring engine
    MDS + AFS + HES + MLS = Composite (0-150)
    |
    v
Classification (10 processing tiers, 6 metabolic tiers)
```

Fully deterministic: same inputs always produce the same score. Inter-rater reliability is 1.0 by construction.

### The Four Axes

| Axis | Range | What It Measures |
|------|-------|-----------------|
| **MDS** (Matrix Disruption) | 0-30 | How far ingredients have been removed from their whole-food origin — fractionated substrates, industrial intermediates, hydrogenated fats |
| **AFS** (Additive/Formulation) | 0-80 | Additive load by both severity (weighted by evidence tier) and density (count of unique additives) |
| **HES** (Hyperpalatability Engineering) | 0-20 | Patterns of ingredient combination that signal engineered hyperpalatability — sweetener stacking, fat-sweetener-flavor formulations |
| **MLS** (Metabolic Load) | 0-20 | Physiological burden from nutrition panel data — added sugars, sodium, saturated fat |

Each axis captures a different dimension of processing that is not redundant with the others. MDS-AFS correlation is 0.56 after double-counting removal.

### Processing Tiers

| Tier | Score | Description |
|------|-------|-------------|
| W | 0 | Whole food (single ingredient, whole-food taxonomy) |
| Wp | 0 | Whole, prepared (ground, dried, frozen — nothing added) |
| C0 | 0 | Clean, zero concerns (multi-ingredient, no markers) |
| C1 | 1-5 | Clean, minimal markers |
| P1a | 6-15 | Light processing |
| P1b | 16-25 | Moderate-light processing |
| P2a | 26-38 | Moderate processing |
| P2b | 39-50 | Moderate-heavy processing |
| P3 | 51-75 | Heavy industrial formulation |
| P4 | 76+ | Ultra-formulated |

### Metabolic Tiers

| Tier | MLS | Description |
|------|-----|-------------|
| N0 | 0 | No metabolic load |
| N0+ | 1-3 | Minimal |
| N1a | 4-6 | Low |
| N1b | 7-8 | Low-moderate |
| N2 | 9-14 | Moderate |
| N3 | 15+ | High |

<p align="center">
  <img src="docs/fis_subscore_grid.png" alt="Sub-score relationship scatter" width="700">
</p>

## The Ontology

The ingredient classification ontology contains **174 compiled regex patterns** organized into functional groups:

- **Additive tiers (AFS):** 46 Tier A (artificial dyes, strong emulsifiers, NNS), 54 Tier B (gums, preservatives, phosphates), 25 Tier C (conditional — citric acid, pectin, ascorbic acid). Tier C scores only when industrial context exists.
- **Matrix disruption buckets (MDS):** 28 Bucket 2 (refined oils, starches, fiber isolates, dairy powders), 15 Bucket 3 (maltodextrin, HFCS, protein isolate, hydrogenated fats).
- **Hyperpalatability patterns (HES):** 25 caloric sweeteners, 9 NNS, 5 flavor ingredients, 6 flavor enhancers, 5 coating fats. Six detection patterns evaluate ingredient *combinations*, not individual ingredients.

Every pattern includes nesting depth analysis — maltodextrin as a carrier inside "mushroom powder (maltodextrin, mushroom extract)" receives reduced weight versus maltodextrin as a top-level ingredient.

## Example: Two Yogurts

**Fage Total 5% Plain** — Composite: **0** (C0)
```
Ingredients: Grade A pasteurized skimmed milk and cream, live active
yogurt cultures
MDS: 0  |  AFS: 0  |  HES: 0  |  MLS: 0
```

**Dannon Light + Fit Greek Fat Free Banana Cream** — Composite: **51** (P3)
```
Ingredients: Cultured pasteurized non fat milk, water, fructose,
banana puree, natural and artificial flavors, fruit & vegetable juice
concentrate and beta carotene (for color), modified food starch,
pectin, xanthan gum, acesulfame potassium, sucralose, malic acid,
potassium sorbate
MDS: 8  |  AFS: 36  |  HES: 7  |  MLS: 0
```

NOVA classifies both as Group 4. FIS sees a 51-point gap: the "Light" yogurt needs sucralose, acesulfame K, artificial flavors, modified starch, and a preservative to taste like yogurt again. Its MLS is 0 — nothing left to flag metabolically — but it carries more additives than many candy bars.

## Dataset

Built on real-world product data scraped from major U.S. grocery retailers; designed for robustness to inconsistent ingredient lists and labeling formats.

| Store | Products | Description |
|-------|----------|-------------|
| Target | 12,154 | Mass-market grocery |
| Wegmans | 12,058 | Full-service supermarket |
| Farm to People | 2,622 | Curated clean-food retailer |
| Trader Joe's | 1,107 | Private-label specialty |

**27,941 products** total. **26,074** with complete processing classifications after excluding non-food items and products with missing ingredient data.

### Cross-Store Gradient

The four stores form a consistent processing gradient that holds within nearly every food category:

| Store | Mean Composite | Strict UPF (P2a+) | Whole Food (W+Wp) |
|-------|---------------|-------|------|
| Farm to People | 2.9 | 0.4% | 16.9% |
| Trader Joe's | 11.5 | 4.7% | 12.4% |
| Wegmans | 16.2 | 19.0% | 11.7% |
| Target | 21.0 | 27.6% | 6.4% |

Target's mean AFS is 3.4x Trader Joe's. The primary differentiator between stores is additive load, not matrix disruption — all conventional stores sell similar refined base ingredients, but Target layers significantly more additives on top.

## Interactive Demos

- **[Protein Bars](https://dmh221.github.io/food-processing-ontology/demos/protein_bars.html)** — 6 bars from C0 to P3. More protein doesn't mean more processing.
- **[Yogurt](https://dmh221.github.io/food-processing-ontology/demos/yogurt.html)** — The diet yogurt paradox: the "Light" yogurt is the most processed.
- **[Peanut Butter](https://dmh221.github.io/food-processing-ontology/demos/peanut_butter.html)** — The nut butter ladder: from raw peanuts to sugar-first spreads.
- **[Electrolytes](https://dmh221.github.io/food-processing-ontology/demos/electrolytes.html)** — The hydration spectrum: salt water to synthetic cocktail.

## Key Design Decisions

**Why four axes, not one?** Processing-related harm involves mechanisms beyond nutrient composition — a controlled inpatient crossover trial found ~500 kcal/day overconsumption on ultra-processed diets matched on all macronutrients. Four axes let you see which dimension drives a product's classification.

**Why continuous, not categorical?** Within what NOVA calls Group 4, products score 16-97 in this system. Collapsing that to a binary label discards the signal that distinguishes a yogurt with one gum from Pillsbury Cinnamon Rolls.

**Why deterministic?** The scoring engine is pure regex + arithmetic. No model weights, no training data, no stochastic outputs. The LLM (Claude Haiku) is used only for taxonomy classification (what *kind* of food), not for scoring. Taxonomy results are cached to disk.

**Why nesting depth?** A preservative in a sub-ingredient list (depth 2) signals less about formulation intent than the same preservative at the top level (depth 0). Depth discounting prevents minor components from dominating scores.

## Project Structure

```
scoring/
    ontology.py          Ingredient ontology — 174 patterns, tiers, buckets
    scorer.py            Orchestrator — normalization, scanning, 4-axis scoring
    normalize.py         Store-aware ingredient parsing, allergen stripping
    product_taxonomy.py  LLM taxonomy classifier (11 families, 64 subfamilies)
    rules_mds.py         Matrix Disruption Score
    rules_afs.py         Additive/Formulation Score
    rules_hes.py         Hyperpalatability Engineering Score
    rules_mls.py         Metabolic Load Score
    micro_label.py       Micro-label classifier (regex + LLM, 4th taxonomy level)
analysis/
    generate_comparison.py   Data-driven interactive comparison generator
    style.py                 Shared chart builders (Plotly dark-mode)
    data/                    Product comparison datasets (JSON)
tests/                   280 tests — ontology, scoring rules, anchors, ETL
docs/
    fis_methodology_and_findings.md   Full methodology paper and empirical findings
```

## Quick Start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run tests (no external data needed)
python -m pytest tests/ -v

# Score products
python run_scoring.py

# Generate interactive comparisons
python analysis/generate_comparison.py analysis/data/*.json
```

Taxonomy classification requires an Anthropic API key (`ANTHROPIC_API_KEY` env var) for Claude Haiku. Use `--no-llm` to skip LLM classification.

## Validation

- **NOVA concordance:** W/Wp maps to NOVA Group 1, C0/C1 to Groups 2/3, P1b+ to Group 4. FIS adds 7-tier discrimination within Group 4.
- **Sensitivity analysis:** 22 parameter variations tested. All preserve tier monotonicity. Most impactful: HES 2.0x scaling (25% composite change). [Full analysis](analysis/classification_sensitivity.md)
- **Axis independence:** MDS-AFS correlation 0.56 after double-counting removal. Each axis captures a non-redundant dimension.
- **Farm to People anchor:** 80.6% of FTP products score W/C0/C1. Zero P2b/P3/P4. Confirms the scoring floor works.

## Methodology

See [docs/fis_methodology_and_findings.md](docs/fis_methodology_and_findings.md) for the full methodology paper, including validation against NOVA, sensitivity analysis, and empirical findings from 27,941 products across four U.S. grocery retailers.

## License

[MIT](LICENSE)
