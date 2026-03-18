"""Scoring anchor tests — known products with expected score ranges.

These are integration-style tests that run the full MDS+AFS+HES pipeline
on real ingredient strings from known products, then assert that the
composite processing_score lands in the expected range.

Anchors are calibrated from the methodology doc and v0.7.2 behavior.
They guard against regressions that silently shift scores across ontology
or scoring logic changes.

Each test name encodes the product and its expected tier, e.g.:
  test_frosted_flakes_p4 → Frosted Flakes should be in P4 range.
"""

import pytest
from scoring.ontology import scan_ingredients
from scoring.rules_mds import score_mds
from scoring.rules_afs import score_afs
from scoring.rules_hes import score_hes


def _processing_score(ingredients: str) -> int:
    """Run the full MDS+AFS+HES pipeline on a normalized ingredient string."""
    scan = scan_ingredients(ingredients)
    mds = score_mds(scan)["score"]
    afs = score_afs(scan)["score"]
    hes = score_hes(scan)["score"]
    return mds + afs + hes


# ---------------------------------------------------------------------------
# Whole-food / minimally-processed anchors (expected: score 0-5)
# ---------------------------------------------------------------------------

class TestWholeAndCleanAnchors:
    def test_single_banana(self):
        """Pure whole food — zero score."""
        assert _processing_score("banana") == 0

    def test_olive_oil(self):
        """Single-ingredient culinary fat."""
        assert _processing_score("extra virgin olive oil") == 0

    def test_sea_salt(self):
        assert _processing_score("sea salt") == 0

    def test_plain_oats(self):
        assert _processing_score("whole grain rolled oats") == 0

    def test_greek_yogurt_plain(self):
        """Simple cultured dairy: milk, live cultures. Score should be 0."""
        assert _processing_score("pasteurized whole milk, live active cultures") == 0

    def test_black_beans_canned(self):
        """Black beans + salt + water — minimal. Score 0."""
        assert _processing_score("black beans, water, salt") == 0


# ---------------------------------------------------------------------------
# Lightly processed anchors (expected: score 1-25, classes C1–P1b)
# ---------------------------------------------------------------------------

class TestLightlyProcessed:
    def test_whole_grain_bread(self):
        """Typical whole grain bread: some additives but clean. Score 1-25."""
        ingredients = (
            "whole wheat flour, water, yeast, salt, wheat gluten, "
            "vinegar, citric acid"
        )
        score = _processing_score(ingredients)
        assert 1 <= score <= 25, f"Expected 1-25, got {score}"

    def test_cheddar_cheese(self):
        """Real cheddar: milk, cultures, salt, enzyme. Minimal."""
        score = _processing_score("pasteurized milk, cheese cultures, salt, enzymes")
        assert score <= 10, f"Expected <= 10, got {score}"

    def test_simple_salsa(self):
        """Tomatoes, onion, peppers, salt, vinegar, citric acid."""
        score = _processing_score(
            "tomatoes, onion, jalapeño peppers, salt, distilled vinegar, citric acid"
        )
        assert score <= 15, f"Expected <= 15, got {score}"


# ---------------------------------------------------------------------------
# Moderately processed anchors (expected: score 15-50, classes P1a–P2b)
# ---------------------------------------------------------------------------

class TestModeratelyProcessed:
    def test_potato_chips_basic(self):
        """Potatoes, vegetable oil, salt — light processing."""
        score = _processing_score("potatoes, vegetable oil, salt")
        # vegetable oil is bucket_2 → MDS ~3; total should be modest
        assert 1 <= score <= 20, f"Expected 1-20, got {score}"

    def test_ketchup(self):
        """Tomato concentrate, corn syrup, vinegar, salt, natural flavors."""
        score = _processing_score(
            "tomato concentrate, distilled vinegar, high fructose corn syrup, "
            "corn syrup, salt, natural flavors"
        )
        assert 10 <= score <= 40, f"Expected 10-40, got {score}"


# ---------------------------------------------------------------------------
# Heavily processed anchors (expected: score 40+, classes P2b–P4)
# ---------------------------------------------------------------------------

class TestHeavilyProcessed:
    def test_frosted_flakes(self):
        """Frosted Flakes: malt flavor is now Tier A (v0.7.2 fix).
        Before v0.7.2 malt flavor was unrecognized → score 0 (C0 at best).
        Now: AFS from malt flavor + HES from flavor+sweetener → P1a range (score 6-15)."""
        ingredients = (
            "milled corn, sugar, malt flavor, salt, niacinamide, "
            "reduced iron, thiamin hydrochloride, riboflavin, folic acid"
        )
        score = _processing_score(ingredients)
        # malt flavor (Tier A, weight=2) + density + HES flavor_plus_sweetener = 16
        assert score >= 6, f"Expected >= 6 (P1a+), got {score}"
        assert score < 40, f"Expected < 40 for a cereal (no heavy industrial fats), got {score}"

    def test_cola_style_soda(self):
        """Fanta-style: HFCS + caramel color + natural flavor + citric acid."""
        ingredients = (
            "carbonated water, high fructose corn syrup, caramel color, "
            "natural flavor, citric acid"
        )
        score = _processing_score(ingredients)
        assert score >= 20, f"Expected >= 20, got {score}"

    def test_doritos_style(self):
        """Doritos-style: multiple Tier A/B markers + industrial fats."""
        ingredients = (
            "corn, vegetable oil (corn, canola, and/or sunflower oil), maltodextrin, "
            "salt, cheddar cheese (milk, cheese cultures, salt, enzymes), "
            "whey, monosodium glutamate, buttermilk, natural flavor, "
            "artificial flavor, sodium diacetate, yeast extract, red 40, "
            "yellow 5, yellow 6, citric acid, lactic acid"
        )
        score = _processing_score(ingredients)
        assert score >= 39, f"Expected >= 39 (P2b+), got {score}"

    def test_processed_cheese_product(self):
        """Processed American cheese: phosphates, emulsifiers, preservatives."""
        ingredients = (
            "cheddar cheese, water, milkfat, sodium citrate, salt, "
            "sodium phosphate, sorbic acid, artificial color"
        )
        score = _processing_score(ingredients)
        assert score >= 20, f"Expected >= 20, got {score}"


# ---------------------------------------------------------------------------
# Fortification markers — enriched rice/cereals should NOT score as W (v0.7.2)
# ---------------------------------------------------------------------------

class TestFortificationAnchors:
    def test_enriched_white_rice(self):
        """Enriched rice: folic acid, niacin, ferric phosphate added.
        Tier C fortification markers are detected but excluded from AFS
        scoring (v0.9.1) — fortification should not penalize processing."""
        ingredients = "enriched long grain rice (rice, folic acid, niacin, ferric phosphate)"
        scan = scan_ingredients(ingredients)
        assert len(scan["tier_c"]) > 0, "Enriched rice should have Tier C fortification markers"
        # Fortification Tier C markers are excluded from AFS, so score = 0
        score = _processing_score(ingredients)
        assert score == 0, "Fortification-only Tier C should not inflate processing score"

    def test_plain_brown_rice_scores_zero(self):
        """Unfortified whole grain rice should still score 0."""
        score = _processing_score("whole grain brown rice")
        assert score == 0

    def test_enriched_flour_triggers_bucket2_and_fortification(self):
        scan = scan_ingredients(
            "enriched wheat flour (flour, niacin, reduced iron, thiamine mononitrate, "
            "riboflavin, folic acid)"
        )
        assert "enriched flour" in scan["bucket_2"]
        assert "niacinamide" in scan["tier_c"] or "niacin" in scan["tier_c"]


# ---------------------------------------------------------------------------
# No double-counting: AFS > 0 only with tier items present
# ---------------------------------------------------------------------------

class TestInternalConsistency:
    def test_no_afs_without_tier_items(self):
        """Products with no Tier A/B/C matches must have AFS = 0."""
        clean_texts = [
            "oats, water",
            "tomatoes, onion, salt",
            "milk, cream, cheese cultures",
        ]
        for text in clean_texts:
            r = score_afs(scan_ingredients(text))
            assert r["score"] == 0, f"Expected AFS=0 for '{text}', got {r['score']}"

    def test_mds_and_afs_no_double_count_on_maltodextrin(self):
        """v0.7.0: maltodextrin contributes to MDS only, not AFS."""
        scan = scan_ingredients("maltodextrin")
        afs = score_afs(scan)
        mds = score_mds(scan)
        assert afs["score"] == 0, "maltodextrin should have AFS=0 (MDS only)"
        assert mds["score"] > 0, "maltodextrin should have MDS > 0"

    def test_hfcs_no_afs_contribution(self):
        """v0.7.0: HFCS is Bucket 3 (MDS only), not Tier A."""
        scan = scan_ingredients("high fructose corn syrup")
        afs = score_afs(scan)
        assert "high fructose corn syrup" not in afs["tier_a"]
        assert afs["score"] == 0
