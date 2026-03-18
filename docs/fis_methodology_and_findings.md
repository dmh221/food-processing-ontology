# Food Integrity Scale: A Multi-Axis Continuous Scoring System for Food Processing Classification

## 1. The Problem

The U.S. Food and Drug Administration and U.S. Department of Agriculture issued a joint Request for Information (RFI) in July 2025 seeking public input and evidence to develop a uniform definition of ultra-processed foods (UPFs) applicable to the U.S. food supply. The comment period closed October 23, 2025.

The RFI exists because "ultra-processed" conflates three different claims that are correlated but not identical:

- **Nutrient profile**: A food is high in added sugars, sodium, or saturated fat.
- **Industrial manufacture**: A food is made through industrial techniques such as extrusion, hydrogenation, or interesterification.
- **Cosmetic formulation**: A food contains industrial ingredients or additives — flavors, emulsifiers, colors, stabilizers, non-nutritive sweeteners.

A product can satisfy one criterion without the others. Honey is high in sugar but not ultra-processed. A protein bar may be industrially formulated but nutritionally dense. A canned vegetable with sodium benzoate contains an additive but is otherwise minimally processed. Without a definition that disambiguates these dimensions, the Dietary Guidelines Advisory Committee cannot make UPF-specific recommendations, food labeling cannot reference processing level, and epidemiological studies cannot be reliably compared across datasets.

The most widely used classification system is NOVA, developed by researchers at the University of São Paulo. NOVA classifies all foods into four groups: (1) unprocessed or minimally processed foods, (2) processed culinary ingredients, (3) processed foods, and (4) ultra-processed foods. NOVA is used in approximately 90% of UPF research. When it is the only option, its limitations become the field's limitations.

## 2. Why Existing Systems Fail

A 2025 systematic review identified six systems that explicitly include a "highly processed" or "ultra-processed" category: NOVA, EPIC, IFPRI, UNC, UP3, and Siga. The review concluded that these systems differ materially in what they emphasize, and none fully solves the operational definition problem for all research and policy needs. Three structural failures recur across these systems.

### Failure 1: Binary classification destroys information

NOVA places Fanta and a yogurt with xanthan gum in the same group (Group 4). In the Food Integrity Scale dataset, products classified as moderately processed (P2a) score 26-38 on the composite scale, while the most heavily formulated products (P4) score 76+. That is a 3x difference within what NOVA calls a single category. A 2024 analysis across three large U.S. cohorts found that UPF subgroups show divergent health associations — sugar-sweetened beverages and processed meats were associated with higher cardiovascular risk, while yogurts and cold cereals showed inverse associations. NOVA cannot explain this because it does not differentiate within Group 4.

### Failure 2: Low inter-rater reliability

A large expert survey found low agreement among specialists assigning foods to NOVA groups, with Fleiss' kappa of approximately 0.32-0.34 — meaning experts disagree more often than they agree on borderline classifications. NOVA's criteria are descriptive and interpretive, not algorithmic. Any system that depends on human judgment for classification will suffer from this problem at scale.

### Failure 3: Single-axis systems cannot distinguish mechanisms

The scientific literature identifies at least four distinct exposures bundled under "processing": nutrient profile, additive load, matrix disruption (fractionation and reconstitution of whole foods), and hyperpalatability design (formulation strategies that promote overconsumption). A tightly controlled inpatient crossover trial found that participants consumed approximately 500 kcal/day more on an ultra-processed diet than an unprocessed diet matched on presented calories, sugar, fat, sodium, fiber, and macronutrients — with faster eating rates on the UPF condition. This suggests that processing-related harm involves mechanisms beyond nutrient composition alone. A classification system that collapses these dimensions into a single label cannot identify which dimension is driving risk for a given product or category.

## 3. FIS Architecture

The Food Integrity Scale (FIS) addresses these failures with a multi-axis, continuous, deterministic scoring system. It takes as input a product's name, ingredient list, nutrition panel, and serving size, and produces a composite score from 0 to 110 composed of four independent sub-scores. Products are classified into one of 10 processing tiers and one of 6 metabolic tiers.

The four axes are:

- **Matrix Disruption Score (MDS, 0-30)**: Measures how far ingredients have been removed from their whole-food origin — fractionated substrates, industrial intermediates, hydrogenated fats.
- **Additive/Formulation Score (AFS, 0-40)**: Measures additive load by both severity (weighted by evidence tier) and density (count of unique additives).
- **Hyperpalatability Engineering Score (HES, 0-20)**: Detects patterns of ingredient combination that signal engineered hyperpalatability — sweetener stacking, fat-sweetener-flavor "triple threat" formulations.
- **Metabolic Load Score (MLS, 0-20)**: Measures physiological burden from nutrition panel data — added sugars, sodium, saturated fat, with offsets for fiber and protein.

The composite score is the sum of all four axes. Processing tier is derived from MDS + AFS + HES (the three ingredient-based axes). Metabolic tier is derived from MLS alone.

FIS is fully deterministic: the same ingredient list and nutrition panel always produce the same score. Inter-rater reliability is 1.0 by construction.

## 4. Methodology

### 4.1 Taxonomy Classification

Before scoring, each product is classified into a food identity ontology of 11 families and 64 subfamilies using Claude Haiku, an LLM. The taxonomy describes what a food is — its biological and culinary identity — not how it is stored or sold. A frozen pizza is `composite.pizza`; dried mango is `pantry.dried_fruits_nuts`; ice cream is `desserts.frozen`.

The 11 families are: produce, meat, seafood, plant_protein, dairy_eggs, baked_goods, desserts, drinks, pantry, composite, and non_food.

Products are batched in groups of 20 and sent to the LLM with the product name, brand, ingredients, and category. The LLM returns a family, subfamily, and confidence score capped at 0.90. Results are cached to disk as JSON files keyed by SHA-256 hash incorporating product data and taxonomy version, so any label-set change auto-invalidates the cache.

When the LLM is unavailable, a regex-based fallback assigns taxonomy from product name and category keywords. Fallback classifications receive confidence 0.10. Non-food items (pet supplies, household goods, floral) are excluded from food scoring.

### 4.2 Ingredient Normalization

Raw ingredient text is processed through a store-aware normalization pipeline:

1. **Allergen stripping**: Removes trailing allergen warnings ("ALLERGENS: Contains: wheat..."), which are regulatory disclosures, not ingredients.
2. **Enrichment context removal**: Removes fortification vitamins (niacin, riboflavin, thiamine mononitrate, folic acid, reduced iron) only from within parentheses following the word "enriched." This prevents vitamin labels from being scanned as additives while preserving the "enriched flour" marker itself.
3. **Lowercasing and whitespace collapse.**
4. **Store-aware item parsing**: Standard comma-separated splitting for most stores. Trader Joe's products, which sometimes use ALL-CAPS space-delimited format without commas, are handled with a spine-word heuristic to estimate ingredient count.
5. **Component parsing**: Identifies composed meals (bowls, sushi, prepared foods) by detecting 2+ top-level items with substantial sub-ingredient lists (4+ sub-ingredients each). These are split into components for HES scoring so that ingredients in separate sub-recipes are not falsely combined into hyperpalatability patterns.
6. **Post-normalization empty check**: Text that is non-empty raw but normalizes to empty after allergen stripping (e.g., "ALLERGENS: Contains: wheat and sesame.") is detected and treated as missing ingredients.

**Nesting depth analysis**: For each matched pattern, its parenthetical nesting depth in the ingredient string is computed (depth 0 = top-level, depth 1 = inside one level of parentheses, depth 2+ = deeply nested). This is used throughout scoring to discount ingredients that appear as minor sub-components — for example, maltodextrin as a carrier in "mushroom powder (maltodextrin, mushroom extract)" receives reduced weight.

### 4.3 Ingredient Scanning

The ontology contains approximately 100 regex patterns organized into functional groups. Each pattern has a label, tier, bucket, category, and optional weight override. The scan function runs all patterns against the normalized text and returns structured match results.

**Additive tiers (for AFS):**

- **Tier A — Strong UPF markers (26 patterns)**: Artificial dyes (red 40, yellow 5, blue 1, etc.), artificial and natural flavors, strong emulsifiers (polysorbate, DATEM, mono- and diglycerides, sorbitan esters, sodium stearoyl lactylate, CMC), and non-nutritive sweeteners (aspartame, sucralose, acesulfame K, saccharin, neotame, advantame).
- **Tier B — Moderate markers (32 patterns)**: Hydrocolloid gums (xanthan, guar, gellan, carrageenan, cellulose gum, locust bean, tara), lecithin, caramel color, preservatives (sorbic acid, potassium sorbate, sodium benzoate, calcium/sodium propionate, sodium nitrite/nitrate, sodium erythorbate, TBHQ, BHT, BHA), flavor enhancers (yeast extract, MSG, autolyzed yeast, disodium inosinate/guanylate), and sugar alcohols (erythritol, sorbitol, xylitol, maltitol, mannitol, isomalt).
- **Tier C — Tracked, conditionally scored (7 patterns)**: Citric acid, ascorbic acid, tocopherols, rosemary extract, pectin, annatto, lactic acid. These are scored only when an industrial context exists — at least 1 Tier A/B match, or 3+ total unique additive matches. This prevents citric acid in a simple salad dressing from contributing to AFS.
- **Culinary — Tracked, zero AFS weight (6 patterns)**: Baking soda, baking powder, calcium chloride, cream of tartar, vanilla extract.

**Matrix disruption buckets (for MDS):**

- **Bucket 2 — Refined but not extreme (35 patterns)**: Starches (corn, tapioca, potato, rice), refined seed oils (canola, soybean, vegetable, sunflower, safflower, corn, cottonseed, rapeseed), enriched/bleached flour, fiber isolates (oat, pea, bamboo, powdered cellulose, inulin, chicory fiber), concentrates (juice, protein), dairy powders (whey, milk powder, nonfat milk, milk solids), dextrose, rice/brown rice syrup, glycerin, polydextrose, corn syrup solids, egg powder.
- **Bucket 3 — Industrial substrates (13 patterns)**: Maltodextrin, HFCS, glucose-fructose, glucose syrup, corn syrup, modified starch, protein isolate, hydrolyzed protein, hydrogenated fat, interesterified fat, partially hydrogenated fat. These were moved from Tier A to Bucket 3 in v0.7.0 to eliminate double-counting between MDS and AFS. They are now scored by MDS only.

**HES pattern lists (for hyperpalatability detection):**

- **Caloric sweeteners (19 patterns)**: Sugar, cane/brown/powdered sugar, honey, maple syrup, molasses, agave, corn syrup, HFCS, glucose syrup, rice syrup, dextrose, maltose, fructose, invert sugar, turbinado, coconut sugar, date syrup.
- **Non-nutritive sweeteners (11 patterns)**: Aspartame, sucralose, acesulfame K, saccharin, neotame, advantame, stevia, steviol glycosides, monk fruit, erythritol, allulose.
- **Flavor ingredients (4 patterns)**: Natural/artificial flavors, smoke flavor, vanillin.
- **Flavor enhancers (6 patterns)**: Yeast extract, MSG, autolyzed yeast, disodium inosinate/guanylate.
- **Coating fats (5 patterns)**: Palm oil, palm kernel oil, hydrogenated fat, interesterified fat, shortening. Cocoa butter and coconut oil are excluded as culinary fats.

### 4.4 Scoring Rules

#### Matrix Disruption Score (MDS, 0-30)

MDS measures how far ingredients have traveled from their whole-food origin.

Bucket 2 contribution: First match = 3 points, each subsequent = 2 points. Items sorted by nesting depth ascending (shallowest first). Depth discounts: depth 0 = 1.0x, depth 1 = 0.5x, depth 2+ = 0.25x. Capped at 10 points.

Bucket 3 contribution: First match = 5 points, each subsequent = 3 points. Depth discounts: depth 0 = 1.0x, depth 1 = 0.75x, depth 2+ = 0.4x. Capped at 20 points.

Hydrogenated fat bonus: +5 points if any hydrogenated, partially hydrogenated, or interesterified fat is detected, depth-discounted at the shallowest match depth.

Total: Bucket 2 + Bucket 3 + hydrogenated bonus, rounded and capped at 30.

#### Additive/Formulation Score (AFS, 0-40)

AFS measures additive load through two components summed together.

**Severity**: Weighted sum of matched additives, depth-discounted. Depth discounts: depth 0 = 1.0x, depth 1 = 0.6x, depth 2+ = 0.3x.
- Tier A: +5 per match (natural flavor and yeast extract override to +2, reflecting weaker UPF signal relative to synthetic dyes or emulsifiers).
- Tier B: +3 per match (yeast extract overrides to +2).
- Graduated bonus for top-level (depth 0) Tier A count: 3-4 matches = +4, 5-7 = +8, 8+ = +12.
- Tier C: +1 per match, scored only conditionally — requires at least 1 Tier A/B match, or 3+ total unique A+B+C matches.
- Severity capped at 40.

**Density**: Depth-discounted count of all unique additive labels (A+B+C). Each label contributes 1.0 multiplied by depth factor. Capped at 10.

Total: severity + density, rounded and capped at 40.

#### Hyperpalatability Engineering Score (HES, 0-20)

HES detects patterns of ingredient combination that signal engineered hyperpalatability. It scores ingredient relationships, not individual ingredients.

Six patterns, evaluated within each component for composed meals (maximum component score used):

| Pattern | Condition | Points |
|---------|-----------|--------|
| Flavor + sweetener | Any flavor ingredient AND any caloric sweetener | +4 |
| Multiple sweeteners | 2+ distinct caloric sweetener types | +4 |
| Non-nutritive sweetener | Any NNS present | +3 |
| Coating fat + sweetener | Any coating fat AND any sweetener (caloric or NNS) | +4 |
| Flavor enhancer stacking | Any enhancer AND (any flavor OR 2+ enhancers) | +3 |
| Triple threat | Coating fat + sweetener + (flavor or enhancer) | +2 |

Patterns are cumulative. Capped at 20.

For composed meals with 2+ substantial sub-recipes, each component's ingredient text is scanned and scored independently. The final HES score is the maximum of any single component. This prevents a bowl with sugar in its sauce, yeast extract in its mushroom powder, and palm oil in its marinade from triggering "triple threat" — those ingredients are in separate sub-recipes and are not working together for hyperpalatability.

#### Metabolic Load Score (MLS, 0-20)

MLS measures physiological burden from nutrition panel data, independent of ingredient processing.

When serving size in grams is parseable, all nutrient values are normalized to per-100g and scored against per-100g thresholds. When serving size is unavailable, raw per-serving values are scored against calibrated per-serving thresholds derived from per-100g assuming a median serving of approximately 40g.

Penalties:
- Sugar: Prefers added sugars when available (more specific). Very high added sugar (>20g/100g) = +7; high (>10g) = +4. Fallback to total sugars: very high (>25g) = +6; high (>15g) = +3.
- Sodium: Very high (>800mg/100g) = +6; high (>500mg) = +3.
- Saturated fat: Very high (>8g/100g) = +5; high (>5g) = +3.

Offsets:
- Fiber: High (≥5g/100g) = -3; moderate (≥3g) = -2.
- Protein: High (≥20g/100g) = -2; moderate (≥10g) = -1.

Clamped to 0-20.

### 4.5 Classification

**Processing score** = MDS + AFS + HES (0-90 theoretical maximum).

**Composite score** = processing score + MLS (0-110 theoretical maximum).

#### Processing Tiers (10 tiers)

| Tier | Score Range | Description |
|------|-------------|-------------|
| W | 0, single ingredient, whole-food taxonomy | Whole food |
| Wp | 0, single ingredient, preparation keyword in name | Whole, prepared |
| C0 | 0, multi-ingredient or non-whole taxonomy | Clean, zero concerns |
| C1 | 1-5 | Clean, minimal markers |
| P1a | 6-15 | Light processing |
| P1b | 16-25 | Moderate-light processing |
| P2a | 26-38 | Moderate processing |
| P2b | 39-50 | Moderate-heavy processing |
| P3 | 51-75 | Heavy industrial formulation |
| P4 | 76+ | Ultra-formulated |

**Taxonomy-based processing floors**: Each family and subfamily defines a minimum processing class. Produce, meat, and seafood can be W. Baked goods, desserts, and composite meals are at minimum C. Specific subfamilies override family defaults — for example, `dairy_eggs.cheese` has a C floor while `dairy_eggs.eggs_butter` has a W floor. The score can raise the class above the floor but never lower it below.

**W/Wp eligibility**: Only products in whole-food-eligible families or subfamilies (produce, meat, seafood, eggs/butter, milk/cream, water/seltzers, oils/vinegar/spices, grains/beans, dried fruits/nuts, honey/syrups, baking ingredients) can receive W or Wp. Juice, rice cakes, and popcorn are excluded from W/Wp by name regex — structural transformation puts them at C minimum.

#### Metabolic Tiers (6 tiers)

| Tier | MLS Range | Description |
|------|-----------|-------------|
| N0 | 0 | No metabolic load detected |
| N0+ | 1-3 | Minimal |
| N1a | 4-6 | Low |
| N1b | 7-8 | Low-moderate |
| N2 | 9-14 | Moderate |
| N3 | 15+ | High |

### 4.6 Handling Missing Data

- **No ingredients**: If the product's taxonomy is whole-food-eligible, it is classified as W or Wp with zero processing scores. Otherwise it receives processing class "unknown" and NaN composite. Products in structurally multi-ingredient categories (baked goods, desserts, composite, chips, condiments, etc.) with missing ingredients are flagged as suspect.
- **No nutrition data**: MLS = 0. The product is still scored on all processing axes.
- **Disclaimer text**: Strings matching patterns like "vary by region" or "review packaging" are treated as missing ingredients.
- **Allergen-only text**: Raw text that normalizes to empty after allergen stripping is treated as missing ingredients.

## 5. Processing Tier Definitions and Examples

### W — Whole Food
A food sold in its natural state with no added substances.
- **Food**: Chicken drumsticks, shishito peppers, frozen tart cherries, extra virgin olive oil
- **Beverage**: Spring water, Topo Chico sparkling mineral water

### Wp — Whole, Prepared
A whole food that has been mechanically transformed — cut, ground, dried, peeled — but with nothing added.
- **Food**: Ground cumin, frozen broccoli florets, shaved beef steak, dried mango
- **Beverage**: Rare. Most prepared single-ingredient beverages involve extraction (juicing), which pushes them to C0.

### C0 — Clean, Zero Concerns
Multiple recognizable ingredients combined with no additives, refined substrates, or industrial markers. These are products a home cook could replicate.
- **Food**: Sourdough bread (flour, water, salt, starter), garbanzo beans (chickpeas, water, salt), roasted salmon
- **Beverage**: Fresh-pressed beet-ginger-turmeric juice, sparkling apple cider

### C1 — Clean, Minimal Markers
A trace processing signal — typically one Tier C additive, a single refined ingredient, or a minor MLS flag. Nothing that signals industrial formulation.
- **Food**: Ricotta cheese, mozzarella slices, granola, corn starch
- **Beverage**: Kombucha, flavored sparkling water with citric acid

### P1a — Light Processing
One or two Tier A/B markers (natural flavor, a gum, a preservative) or a couple of Bucket 2 refined ingredients. Recognizable as food with minor industrial touches.
- **Food**: Dark chocolate, waffle fries, ham, instant oatmeal, BBQ sauce
- **Beverage**: Snapple, Olipop, agua fresca, protein energy drinks

### P1b — Moderate-Light Processing
A clear additive stack or multiple refined substrates working together. The formulation is evidently industrial but not aggressive.
- **Food**: Annie's Bunny Grahams, Honey Smacks cereal, cookie mix, yogurt with stabilizers
- **Beverage**: Diet Coke, Gatorade Lower Sugar, Poppi, La Colombe canned latte

### P2a — Moderate Processing
Substantial additive loads and/or industrial substrate use. Multiple Tier A markers, Bucket 3 substrates, and often the first HES pattern triggers. Unambiguously industrially formulated.
- **Food**: Frozen mozzarella sticks, LUNA protein bar, ramen kits, coconut shrimp
- **Beverage**: Canada Dry ginger ale, Diet Dr Pepper, Pepsi Zero

### P2b — Moderate-Heavy Processing
Heavy additive stacking across multiple functional categories. AFS typically 25-35, meaningful MDS contribution, and common HES patterns. Engineered for shelf stability, palatability, and cost efficiency.
- **Food**: Birds Eye Cheesy Broccoli, Reese's Hearts, cookie dough bites, hot dog buns with HFCS
- **Beverage**: Arizona Arnold Palmer, Mountain Dew Zero, Premier Protein shake

### P3 — Heavy Industrial Formulation
AFS near or at the 40-point cap. Multiple Bucket 3 substrates. Triple threat HES pattern common. Industrial ingredients stacked across all functional categories.
- **Food**: Skittles, Dot's Pretzels, Frito Lay party mix, Utz Pub Mix, cinnamon buns
- **Beverage**: Crystal Light drink mixes, SunnyD (composite 74 — the highest-scoring beverage in the dataset)

### P4 — Ultra-Formulated
Simultaneous saturation across all four axes. AFS at or near cap (37-40), MDS 19-30, HES 14-20 (triple threat plus additional patterns), MLS high (very high added sugar, sodium, and saturated fat). Only 23 products out of 26,074 reach this tier.
- **Food**: Pillsbury Grands! Cinnamon Rolls (97), Hostess Frosted Cupcakes (93), Carvel Double Crunch Ice Cream Cake (92), Nerds Candy, Entenmann's Donuts
- **Beverage**: None. No beverage reaches P4 because the scale requires simultaneous saturation of all four axes, and beverages structurally lack the capacity to maximize MDS and HES. Beverages have limited matrix disruption opportunity — no fractionated solids to stack, no enriched flours, no hydrogenated fats. They also have narrower HES reach — no coating fats means no coating-fat-plus-sweetener or triple-threat patterns. A beverage's processing signal comes almost entirely from AFS and MLS. Even SunnyD, the most processed beverage at composite 74, maxes out AFS but cannot push MDS or HES high enough to cross into P4.

## 6. Empirical Findings

### 6.1 Dataset

The current dataset comprises 27,941 products from four U.S. retailers:

| Store | Products | Description |
|-------|----------|-------------|
| Target | 12,154 | Mass-market grocery |
| Wegmans | 12,058 | Full-service supermarket |
| Farm to People (FTP) | 2,622 | Curated clean-food retailer |
| Trader Joe's | 1,107 | Private-label specialty |

After excluding non-food items (251) and products with unknown processing class (1,802 — primarily due to missing ingredient data), 26,074 food products have complete processing classifications.

### 6.2 Cross-Store Processing Gradient

The four stores form a consistent gradient from least to most processed:

| Store | Mean Composite | Median | P2a+ (Strict UPF) | P1b+ (Broad UPF) | W+Wp (Whole Food) |
|-------|---------------|--------|-------|-------|------|
| Farm to People | 2.9 | 0.0 | 0.4% | 2.9% | 16.9% |
| Trader Joe's | 11.5 | 9.0 | 4.7% | 22.8% | 12.4% |
| Wegmans | 16.2 | 12.0 | 19.0% | 34.6% | 11.7% |
| Target | 21.0 | 17.0 | 27.6% | 45.3% | 6.4% |

This ordering holds within nearly every taxonomy family — produce, meat, dairy, pantry, desserts, plant protein — not just in aggregate. The one exception is drinks, where Wegmans (13.8) slightly exceeds Target (13.0). The consistency of this gradient across food categories suggests it reflects genuine differences in product formulation and curation, not an artifact of assortment mix.

### 6.3 What Drives the Gap: AFS, Not MDS

The sub-score breakdown reveals that additive load (AFS) is the primary differentiator between stores, not matrix disruption.

| Store | MDS (of composite) | AFS (of composite) | HES (of composite) | MLS (of composite) |
|-------|-----|-----|-----|-----|
| Farm to People | 1.0 (36%) | 0.7 (24%) | 1.2 (41%) | 0.0 (0%) |
| Trader Joe's | 3.2 (28%) | 2.5 (21%) | 2.7 (23%) | 3.1 (27%) |
| Wegmans | 4.1 (25%) | 5.9 (36%) | 3.2 (20%) | 3.1 (19%) |
| Target | 4.8 (23%) | 8.6 (41%) | 4.0 (19%) | 3.6 (17%) |

Target's mean AFS is 8.6/40 — 3.4x Trader Joe's (2.5) and 1.5x Wegmans (5.9). MDS is more compressed across stores: Target 4.8 vs. TJ's 3.2 vs. Wegmans 4.1. All conventional grocery stores sell products built from similar refined base ingredients (enriched flour, refined oils, whey), but Target's products layer significantly more additives on top of that base.

Farm to People's MLS is 0.0 because no nutrition data was scraped for that store. This is an accepted limitation — FTP's value in the dataset is as a processing-axis validation anchor, not for metabolic analysis.

### 6.4 Trader Joe's: Zero Artificial Dyes, Zero HFCS

Trader Joe's carries zero products with artificial dyes and zero with HFCS across all 1,107 SKUs, consistent with their published ingredient policies prohibiting synthetic colors and HFCS in private-label products. However, Trader Joe's is not additive-free — 25.4% of its products contain natural flavors and 8.5% contain modified starch. Its processing distribution caps out around P2a (4.5% of classified products), with only two products reaching P3 (Cinnamon Buns at composite 71, Cinnamon Twist Danish at 58) and zero at P4. This suggests a deliberate formulation ceiling: Trader Joe's sells processed food but avoids the most aggressive industrial formulation strategies.

### 6.5 Natural Flavor Is the Dominant Additive

Natural flavor appears in 8,812 products — 35% of the classified food supply and the single most prevalent formulation marker in the dataset. At Target, 47.5% of food products contain a flavoring additive flagged as Tier A. This single ingredient class drives a large share of AFS scores: 81.4% of natural-flavor-containing products land in the P1a-P2a range (composite 6-38). Natural flavor alone contributes +2 to AFS severity (reduced from the default Tier A weight of +5, reflecting that it is a weaker UPF signal than synthetic dyes or emulsifiers), but its sheer prevalence makes it the ingredient most responsible for pushing otherwise moderate products into processed territory.

### 6.6 Wegmans vs. Target Within the Same Food Categories

Comparing the same taxonomy families across stores isolates formulation differences from assortment differences:

| Family | Wegmans | Target | Delta |
|--------|---------|--------|-------|
| Baked goods | 20.8 | 29.4 | +8.5 |
| Meat | 7.8 | 14.4 | +6.6 |
| Composite meals | 16.6 | 22.2 | +5.5 |
| Desserts | 35.3 | 40.7 | +5.3 |
| Pantry | 15.7 | 18.6 | +2.8 |
| Dairy/eggs | 12.5 | 13.9 | +1.3 |
| Drinks | 13.8 | 13.0 | -0.7 |

Target scores higher in every category except drinks. The baked goods gap (+8.5) is the largest, suggesting Target's bread and bakery products carry substantially more preservatives, dough conditioners, and emulsifiers than Wegmans' equivalents. The meat gap (+6.6) likely reflects Target's heavier reliance on processed and cured meat products with nitrites, flavors, and modified starches relative to Wegmans' larger fresh meat selection.

### 6.7 Feature Prevalence by Store

| Feature | FTP | TJ's | Wegmans | Target |
|---------|-----|------|---------|--------|
| Artificial dyes | 0.0% | 0.0% | 3.9% | 9.6% |
| HFCS | 0.0% | 0.0% | 2.4% | 3.3% |
| Natural flavors | 5.5% | 25.4% | 34.8% | 35.2% |
| Non-nutritive sweeteners | 0.7% | 0.2% | 8.0% | 11.8% |
| Hydrogenated fats | 0.0% | 0.1% | 2.3% | 3.5% |
| Protein isolates | 0.1% | 1.0% | 3.9% | 2.9% |
| Modified starch | 0.6% | 8.5% | 8.6% | 9.7% |

### 6.8 Farm to People Validates the Scoring Floor

Farm to People's distribution serves as a ground-truth anchor. 80.6% of its classified products fall in W, C0, or C1 (composite 0-5). Its most processed products are a handful of P2a items — sandwich cookies, apple cider donuts, a ramen kit — scoring 27-28. Zero P2b, P3, or P4 products exist in the catalog. FTP has zero artificial dyes, zero HFCS, zero hydrogenated fats, and near-zero NNS. Its mean AFS is 0.7/40. This confirms that FIS correctly assigns low scores to a retailer whose sourcing philosophy explicitly prioritizes minimally processed, whole-ingredient products.

### 6.9 UPF Prevalence: Shelf Assortment vs. Dietary Intake

Excluding Farm to People (the curated clean retailer), the conventional grocery picture is:

| Metric | Conventional Grocery (TJ + Wegmans + Target) |
|--------|------|
| Strict UPF (P2a+) | 22.3% |
| Broad UPF (P1b+) | 39.0% |
| Whole food (W+Wp) | 9.3% |
| Mean composite | 18.2 |
| Median composite | 14.0 |

The commonly cited statistic that 70-80% of grocery store food is ultra-processed comes from studies using NOVA on dietary intake data — what Americans eat, not what sits on shelves. By product count (shelf assortment), approximately 1 in 5 products is P2a+ and 2 in 5 are P1b+. The distinction matters: conventional grocery stores stock substantial minimally processed food — 9.3% whole food, 14.8% C0, 14.4% C1 — but the consumption-weighted picture is likely very different. Americans disproportionately consume the processed end of the shelf (sodas, chips, frozen meals), so UPF share of calories consumed is much higher than UPF share of SKUs available. If sales volume data were available, the UPF share would likely fall between the shelf-count figure (22%) and the dietary-intake figure (70-80%).

This is a policy-relevant finding: the problem may be less about availability of clean food and more about consumption patterns — price, convenience, marketing, and palatability design driving disproportionate consumption of the most processed products.

### 6.10 The P4 Tier Is Nearly Empty — By Design

Only 23 products across 26,074 classified food items (0.09%) score P4. This is not a bug. The theoretical maximum is 110 (MDS 30 + AFS 40 + HES 20 + MLS 20), but reaching it requires extreme simultaneous saturation across all four axes. Most heavily processed products max out in P2b-P3 because they saturate one or two axes but not all four. The rarity of P4 confirms that the scale has meaningful headroom — it is not artificially compressed at the top.

## 7. Validation

### 7.1 NOVA Concordance

FIS processing tiers align with NOVA groupings: W/Wp maps to NOVA Group 1, C0/C1 to NOVA Groups 2/3, P1b+ to NOVA Group 4. But FIS adds granularity: within what NOVA calls Group 4, products spread across five tiers (P1b through P4) with composite scores ranging from 16 to 97. This seven-tier discrimination within NOVA Group 4 is the core value proposition of FIS — it preserves NOVA's validated epidemiological signal while adding the resolution needed to distinguish a yogurt with one gum from Pillsbury Cinnamon Rolls.

### 7.2 Sensitivity Analysis

All 22 parameter variations tested (AFS tier weights, AFS cap, MDS bucket weights, MDS cap, HES scaling) preserve monotonicity — tier ordering never inverts under any reasonable parameter choice. The most impactful parameter is HES 2.0x scaling (25% composite score change), confirming that hyperpalatability is a significant independent axis. The system is robust to the specific parameter values chosen.

### 7.3 Axis Independence

The v0.7.0 double-counting removal (moving 9 industrial substrates from Tier A to Bucket 3, making them MDS-only) reduced AFS's share of composite from 43.6% to 37.4% and MDS-AFS correlation from 0.705 to 0.560. The four axes are substantially independent — each captures a different dimension of processing that is not redundant with the others.

## 8. Future Work

### ML for Ingredient Normalization

The current regex ontology covers approximately 100 patterns. Real-world ingredient labels have thousands of variations — "partially hydrogenated soybean and/or cottonseed oil," "contains 2% or less of: natural flavors," and complex parenthetical sub-ingredient lists. A machine learning model trained on the existing scored data could map novel ingredient strings to the nearest known ontology pattern, flag unlabeled ingredients for manual review, and reduce the false-negative rate for uncommon additive names.

### FPro Comparison

FPro predicts NOVA class probabilities from nutrient vectors alone, without ingredient text. An FPro-style model could be trained on FIS-scored data to predict processing tier from nutrition panel only, then compared against FIS's ingredient-based scoring. The expected finding: nutrient-only models will broadly separate W/Wp from P3/P4 but will fail to discriminate in the middle tiers (C1 vs. P1a vs. P1b) where ingredient composition diverges from nutrient profile. That gap is the value added by ingredient-based scoring.

### Application to Public Datasets

USDA's FoodData Central (Branded Food Products database) contains approximately 400,000 products with ingredient lists and nutrition panels — exactly the input FIS requires. NHANES dietary recall data linked to FNDDS food codes could be scored if ingredient lists are available. Application to these datasets would allow direct comparison with existing NOVA-based epidemiological findings and enable the consumption-weighted UPF prevalence analysis that shelf-count data alone cannot provide.

### Sales Volume Weighting

The current analysis measures UPF prevalence by product count (shelf assortment). With sales volume or unit-movement data, the same scoring pipeline could produce consumption-weighted prevalence estimates — bridging the gap between the 22% shelf-count figure and the 70-80% dietary-intake figure reported in the literature.
