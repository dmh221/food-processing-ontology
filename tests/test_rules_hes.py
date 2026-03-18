"""Tests for scoring/rules_hes.py — Hyperpalatability Engineering Score."""

import pytest
from scoring.rules_hes import score_hes
from scoring.ontology import scan_ingredients


def _scan(text):
    return scan_ingredients(text)


# ---------------------------------------------------------------------------
# Zero score cases
# ---------------------------------------------------------------------------

class TestHESZero:
    def test_clean_product_no_hes(self):
        r = score_hes(_scan("oats, water, banana"))
        assert r["score"] == 0
        assert r["patterns_detected"] == []

    def test_sweetener_alone_no_pattern(self):
        # Sweetener without flavor/coating fat doesn't trigger any pattern
        r = score_hes(_scan("cane sugar, water"))
        assert r["score"] == 0

    def test_empty_scan_no_score(self):
        r = score_hes(_scan(""))
        assert r["score"] == 0


# ---------------------------------------------------------------------------
# Pattern 1: flavor_plus_sweetener (+4)
# ---------------------------------------------------------------------------

class TestFlavorPlusSweetener:
    def test_natural_flavor_plus_sugar(self):
        r = score_hes(_scan("sugar, natural flavor"))
        assert "flavor_plus_sweetener" in r["patterns_detected"]
        assert r["score"] >= 4

    def test_artificial_flavor_plus_honey(self):
        r = score_hes(_scan("honey, artificial flavor"))
        assert "flavor_plus_sweetener" in r["patterns_detected"]


# ---------------------------------------------------------------------------
# Pattern 2: multiple_sweeteners (+4)
# ---------------------------------------------------------------------------

class TestMultipleSweeteners:
    def test_two_caloric_sweeteners(self):
        r = score_hes(_scan("cane sugar, corn syrup"))
        assert "multiple_sweeteners" in r["patterns_detected"]
        assert r["score"] >= 4

    def test_cane_sugar_alone_no_multiple(self):
        """Critical regression guard: single qualified sugar must not trigger multiple_sweeteners."""
        r = score_hes(_scan("cane sugar"))
        assert "multiple_sweeteners" not in r["patterns_detected"]

    def test_brown_sugar_alone_no_multiple(self):
        r = score_hes(_scan("brown sugar"))
        assert "multiple_sweeteners" not in r["patterns_detected"]

    def test_three_sweeteners(self):
        r = score_hes(_scan("cane sugar, corn syrup, honey"))
        assert "multiple_sweeteners" in r["patterns_detected"]


# ---------------------------------------------------------------------------
# Pattern 3: non_nutritive_sweetener (+3)
# ---------------------------------------------------------------------------

class TestNonNutritiveSweetener:
    def test_sucralose_triggers_nns(self):
        r = score_hes(_scan("water, sucralose"))
        assert "non_nutritive_sweetener" in r["patterns_detected"]
        assert r["score"] >= 3

    def test_stevia_triggers_nns(self):
        r = score_hes(_scan("stevia leaf extract"))
        assert "non_nutritive_sweetener" in r["patterns_detected"]

    def test_aspartame_triggers_nns(self):
        r = score_hes(_scan("aspartame"))
        assert "non_nutritive_sweetener" in r["patterns_detected"]


# ---------------------------------------------------------------------------
# Pattern 4: coating_fat_plus_sweetener (+4)
# ---------------------------------------------------------------------------

class TestCoatingFatPlusSweetener:
    def test_palm_oil_plus_sugar(self):
        r = score_hes(_scan("palm oil, sugar"))
        assert "coating_fat_plus_sweetener" in r["patterns_detected"]
        assert r["score"] >= 4

    def test_hydrogenated_fat_plus_sucralose(self):
        r = score_hes(_scan("partially hydrogenated soybean oil, sucralose"))
        assert "coating_fat_plus_sweetener" in r["patterns_detected"]

    def test_fat_without_sweetener_no_pattern(self):
        r = score_hes(_scan("palm oil, water, salt"))
        assert "coating_fat_plus_sweetener" not in r["patterns_detected"]


# ---------------------------------------------------------------------------
# Pattern 5: flavor_enhancer_stacking (+3)
# ---------------------------------------------------------------------------

class TestFlavorEnhancerStacking:
    def test_yeast_extract_plus_natural_flavor(self):
        r = score_hes(_scan("yeast extract, natural flavor"))
        assert "flavor_enhancer_stacking" in r["patterns_detected"]
        assert r["score"] >= 3

    def test_msg_plus_yeast_extract(self):
        r = score_hes(_scan("monosodium glutamate, yeast extract"))
        assert "flavor_enhancer_stacking" in r["patterns_detected"]

    def test_single_enhancer_without_flavor_no_stacking(self):
        r = score_hes(_scan("yeast extract, water, salt"))
        assert "flavor_enhancer_stacking" not in r["patterns_detected"]


# ---------------------------------------------------------------------------
# Pattern 6: triple_threat (+2)
# ---------------------------------------------------------------------------

class TestTripleThreat:
    def test_fat_plus_sweet_plus_flavor(self):
        r = score_hes(_scan("palm oil, sugar, natural flavor"))
        assert "triple_threat" in r["patterns_detected"]
        # Also fires: flavor_plus_sweetener (+4), coating_fat_plus_sweetener (+4), triple_threat (+2) = 10
        assert r["score"] >= 10

    def test_no_triple_without_all_three(self):
        # fat + sweet but no flavor/enhancer
        r = score_hes(_scan("palm oil, sugar"))
        assert "triple_threat" not in r["patterns_detected"]


# ---------------------------------------------------------------------------
# Score cap
# ---------------------------------------------------------------------------

class TestHESCap:
    def test_score_capped_at_20(self):
        text = "palm oil, sugar, honey, corn syrup, natural flavor, yeast extract, sucralose"
        r = score_hes(_scan(text))
        assert r["score"] <= 20


# ---------------------------------------------------------------------------
# Multi-component behavior (v0.2 component-aware scoring)
# ---------------------------------------------------------------------------

class TestHESComponents:
    def test_single_component_same_as_flat(self):
        scan = _scan("sugar, natural flavor, palm oil")
        r_flat = score_hes(scan, components=None)
        r_single = score_hes(scan, components=["sugar, natural flavor, palm oil"])
        assert r_flat["score"] == r_single["score"]

    def test_cross_component_patterns_not_combined(self):
        """sugar in component 1 + natural flavor in component 2 should NOT
        trigger flavor_plus_sweetener (they're in separate sub-recipes)."""
        scan = _scan("sugar, natural flavor")  # full product has both
        r_multi = score_hes(scan, components=["sugar, water", "natural flavor, salt"])
        assert "flavor_plus_sweetener" not in r_multi["patterns_detected"]

    def test_multi_component_takes_max_score(self):
        """The component with the highest score wins."""
        # Component 1: sugar + natural flavor → flavor_plus_sweetener (4)
        # Component 2: nothing interesting
        scan = _scan("sugar, natural flavor")
        r = score_hes(scan, components=["sugar, natural flavor", "water, salt"])
        assert "flavor_plus_sweetener" in r["patterns_detected"]

    def test_empty_components_falls_back_to_flat(self):
        """Empty components list triggers the same fallback as components=None
        (not components → True), so flat scan_results are used."""
        r_none = score_hes(_scan("sugar, natural flavor"), components=None)
        r_empty = score_hes(_scan("sugar, natural flavor"), components=[])
        assert r_empty["score"] == r_none["score"]
