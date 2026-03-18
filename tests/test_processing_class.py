"""Tests for processing class assignment and product type classification.

Covers _assign_processing_class(), _assign_metabolic_class(),
and classify_product_type() from scoring/scorer.py.
"""

import pytest
from scoring.scorer import (
    _assign_processing_class,
    _assign_metabolic_class,
    classify_product_type,
)


# ---------------------------------------------------------------------------
# Processing class thresholds
# ---------------------------------------------------------------------------

class TestProcessingClassThresholds:
    """All 10 tiers + boundary conditions."""

    # --- W / Wp (score=0, item_count<=1, whole-food taxonomy) ---
    def test_whole_food(self):
        r = _assign_processing_class(0, item_count=1, name="Apple", taxonomy_family="produce")
        assert r == "W"

    def test_whole_prepped(self):
        r = _assign_processing_class(0, item_count=1, name="Sliced Apples", taxonomy_family="produce")
        assert r == "Wp"

    def test_whole_prepped_dried(self):
        r = _assign_processing_class(0, item_count=1, name="Dried Mango", taxonomy_family="produce")
        assert r == "Wp"

    def test_single_ingredient_non_whole_taxonomy_gives_c0(self):
        """baked_goods family has processing floor C — never W."""
        r = _assign_processing_class(0, item_count=1, name="Bread", taxonomy_family="baked_goods")
        assert r == "C0"

    def test_juice_forces_c0(self):
        """Juice involves structural transformation — not whole even if 1 ingredient."""
        r = _assign_processing_class(0, item_count=1, name="Orange Juice", taxonomy_family="produce")
        assert r == "C0"

    def test_rice_cake_forces_c0(self):
        r = _assign_processing_class(0, item_count=1, name="Brown Rice Cake", taxonomy_family="pantry")
        assert r == "C0"

    def test_popcorn_forces_c0(self):
        r = _assign_processing_class(0, item_count=1, name="Popcorn", taxonomy_family="pantry")
        assert r == "C0"

    # --- C0 (multi-ingredient, score=0) ---
    def test_c0_multi_ingredient(self):
        r = _assign_processing_class(0, item_count=3, taxonomy_family="pantry")
        assert r == "C0"

    # --- C1 (score 1-5) ---
    def test_c1_score_1(self):
        assert _assign_processing_class(1) == "C1"

    def test_c1_score_5(self):
        assert _assign_processing_class(5) == "C1"

    # --- P1a (score 6-15) ---
    def test_p1a_score_6(self):
        assert _assign_processing_class(6) == "P1a"

    def test_p1a_score_15(self):
        assert _assign_processing_class(15) == "P1a"

    # --- P1b (score 16-25) ---
    def test_p1b_score_16(self):
        assert _assign_processing_class(16) == "P1b"

    def test_p1b_score_25(self):
        assert _assign_processing_class(25) == "P1b"

    # --- P2a (score 26-38) ---
    def test_p2a_score_26(self):
        assert _assign_processing_class(26) == "P2a"

    def test_p2a_score_38(self):
        assert _assign_processing_class(38) == "P2a"

    # --- P2b (score 39-50) ---
    def test_p2b_score_39(self):
        assert _assign_processing_class(39) == "P2b"

    def test_p2b_score_50(self):
        assert _assign_processing_class(50) == "P2b"

    # --- P3 (score 51-75) ---
    def test_p3_score_51(self):
        assert _assign_processing_class(51) == "P3"

    def test_p3_score_75(self):
        assert _assign_processing_class(75) == "P3"

    # --- P4 (score 76+) ---
    def test_p4_score_76(self):
        assert _assign_processing_class(76) == "P4"

    def test_p4_score_90(self):
        assert _assign_processing_class(90) == "P4"

    # --- Strictly increasing ---
    def test_tiers_monotonically_increasing(self):
        """Processing tiers must be strictly increasing with score (no inversions)."""
        scores_and_expected = [
            (0, "W"),    # produce, single ingredient
            (1, "C1"),
            (5, "C1"),
            (6, "P1a"),
            (15, "P1a"),
            (16, "P1b"),
            (25, "P1b"),
            (26, "P2a"),
            (38, "P2a"),
            (39, "P2b"),
            (50, "P2b"),
            (51, "P3"),
            (75, "P3"),
            (76, "P4"),
        ]
        tier_order = ["W", "Wp", "C0", "C1", "P1a", "P1b", "P2a", "P2b", "P3", "P4"]
        prev_idx = -1
        for score, expected_tier in scores_and_expected:
            kw = {"taxonomy_family": "produce"} if score == 0 else {}
            actual = _assign_processing_class(score, item_count=1, **kw)
            idx = tier_order.index(actual)
            assert idx >= prev_idx, f"Score {score} gave {actual} (idx={idx}), less than previous {prev_idx}"
            prev_idx = idx


# ---------------------------------------------------------------------------
# Processing floor enforced by taxonomy
# ---------------------------------------------------------------------------

class TestProcessingFloor:
    def test_baked_goods_floor_c(self):
        """baked_goods products can't be W even with 1 ingredient + score=0."""
        r = _assign_processing_class(0, item_count=1, taxonomy_family="baked_goods")
        assert r == "C0"

    def test_desserts_floor_c(self):
        r = _assign_processing_class(0, item_count=1, taxonomy_family="desserts")
        assert r == "C0"

    def test_composite_floor_c(self):
        r = _assign_processing_class(0, item_count=1, taxonomy_family="composite")
        assert r == "C0"

    def test_dairy_eggs_no_floor_allows_w(self):
        """dairy_eggs.eggs_butter has floor W — should allow W."""
        r = _assign_processing_class(
            0, item_count=1, name="Eggs",
            taxonomy_family="dairy_eggs",
            taxonomy_label="dairy_eggs.eggs_butter",
        )
        assert r == "W"

    def test_pantry_noodles_floor_c(self):
        r = _assign_processing_class(
            0, item_count=1,
            taxonomy_family="pantry",
            taxonomy_label="pantry.noodles",
        )
        assert r == "C0"

    def test_pantry_grains_floor_w(self):
        r = _assign_processing_class(
            0, item_count=1, name="Brown Rice",
            taxonomy_family="pantry",
            taxonomy_label="pantry.grains_beans",
        )
        assert r == "W"

    def test_stale_fallback_label_is_noodles(self):
        """Regression: old fallback was pantry.pasta_noodles (wrong), fixed to pantry.noodles."""
        from scoring.product_taxonomy import _default_result
        fb = _default_result()
        assert fb.subfamily == "noodles"
        assert fb.label == "pantry.noodles"
        # pantry.noodles has floor C — confirm it still resolves correctly
        r = _assign_processing_class(
            0, item_count=1,
            taxonomy_family=fb.family,
            taxonomy_label=fb.label,
        )
        assert r == "C0"


# ---------------------------------------------------------------------------
# Metabolic class thresholds
# ---------------------------------------------------------------------------

class TestMetabolicClass:
    def test_n0_score_0(self):
        assert _assign_metabolic_class(0) == "N0"

    def test_n0plus_score_1(self):
        assert _assign_metabolic_class(1) == "N0+"

    def test_n0plus_score_3(self):
        assert _assign_metabolic_class(3) == "N0+"

    def test_n1a_score_4(self):
        assert _assign_metabolic_class(4) == "N1a"

    def test_n1a_score_6(self):
        assert _assign_metabolic_class(6) == "N1a"

    def test_n1b_score_7(self):
        assert _assign_metabolic_class(7) == "N1b"

    def test_n1b_score_8(self):
        assert _assign_metabolic_class(8) == "N1b"

    def test_n2_score_9(self):
        assert _assign_metabolic_class(9) == "N2"

    def test_n2_score_14(self):
        assert _assign_metabolic_class(14) == "N2"

    def test_n3_score_15(self):
        assert _assign_metabolic_class(15) == "N3"

    def test_n3_score_20(self):
        assert _assign_metabolic_class(20) == "N3"


# ---------------------------------------------------------------------------
# classify_product_type
# ---------------------------------------------------------------------------

class TestClassifyProductType:
    def _row(self, taxonomy_label="", taxonomy_family="", name=""):
        return {"taxonomy_label": taxonomy_label, "taxonomy_family": taxonomy_family, "name": name}

    def test_soda_is_beverage(self):
        r = classify_product_type(self._row(taxonomy_label="drinks.sodas_mixers"))
        assert r == "beverage"

    def test_water_seltzer_is_beverage(self):
        r = classify_product_type(self._row(taxonomy_label="drinks.water_seltzers"))
        assert r == "beverage"

    def test_spices_are_pantry_staple(self):
        r = classify_product_type(self._row(taxonomy_label="pantry.oil_vinegar_spices"))
        assert r == "pantry_staple"

    def test_pet_food_is_non_food(self):
        r = classify_product_type(self._row(taxonomy_label="non_food.pet"))
        assert r == "non_food"

    def test_produce_is_food(self):
        r = classify_product_type(self._row(taxonomy_family="produce"))
        assert r == "food"

    def test_baked_goods_is_food(self):
        r = classify_product_type(self._row(taxonomy_family="baked_goods"))
        assert r == "food"

    def test_coffee_tea_dry_ground_coffee_is_pantry(self):
        r = classify_product_type(
            self._row(taxonomy_label="drinks.coffee_tea", name="Ground Coffee Dark Roast")
        )
        assert r == "pantry_staple"

    def test_coffee_tea_iced_latte_is_beverage(self):
        r = classify_product_type(
            self._row(taxonomy_label="drinks.coffee_tea", name="Iced Latte Cold Brew")
        )
        assert r == "beverage"

    def test_coffee_tea_default_is_pantry(self):
        r = classify_product_type(
            self._row(taxonomy_label="drinks.coffee_tea", name="Some Mystery Item")
        )
        assert r == "pantry_staple"
