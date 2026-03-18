"""Tests for scoring/rules_mls.py — Metabolic Load Score."""

import pytest
from scoring.rules_mls import score_mls


def _nutrition(**kwargs):
    """Build a minimal nutrition dict with sensible defaults."""
    base = {
        "added_sugars_g": 0.0,
        "total_sugars_g": 0.0,
        "sodium_mg": 0.0,
        "saturated_fat_g": 0.0,
        "dietary_fiber_g": 0.0,
        "protein_g": 0.0,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# No nutrition
# ---------------------------------------------------------------------------

class TestNoNutrition:
    def test_none_returns_zero(self):
        r = score_mls(None)
        assert r["score"] == 0
        assert r["has_nutrition"] is False

    def test_empty_dict_returns_zero(self):
        r = score_mls({})
        assert r["score"] == 0
        assert r["has_nutrition"] is False

    def test_none_serving_g_uses_per_serving_thresholds(self):
        r = score_mls(_nutrition(added_sugars_g=10), serving_g=None)
        assert r["mls_basis"] == "per_serving"


# ---------------------------------------------------------------------------
# Sugar scoring
# ---------------------------------------------------------------------------

class TestSugar:
    def test_very_high_added_sugar_per_100g(self):
        # 20g/serving, 100g serving → 20g/100g = exactly at threshold (>20 required)
        r = score_mls(_nutrition(added_sugars_g=21), serving_g=100)
        assert "very_high_added_sugar" in r["flags"]
        assert r["score"] >= 7

    def test_high_added_sugar_per_100g(self):
        r = score_mls(_nutrition(added_sugars_g=11), serving_g=100)
        assert "high_added_sugar" in r["flags"]
        assert r["score"] >= 4

    def test_added_sugar_at_threshold_not_flagged(self):
        # exactly 10g/100g is not >10, so should not trigger high
        r = score_mls(_nutrition(added_sugars_g=10), serving_g=100)
        assert "high_added_sugar" not in r["flags"]
        assert "very_high_added_sugar" not in r["flags"]

    def test_total_sugar_fallback_when_no_added_sugars(self):
        r = score_mls(_nutrition(total_sugars_g=26), serving_g=100)
        assert "very_high_total_sugar" in r["flags"]

    def test_added_sugars_preferred_over_total(self):
        """When added_sugars_g > 0, total_sugars branch is skipped."""
        r = score_mls(_nutrition(added_sugars_g=5, total_sugars_g=30), serving_g=100)
        assert "very_high_total_sugar" not in r["flags"]
        assert "high_total_sugar" not in r["flags"]

    def test_per_serving_thresholds(self):
        # Per-serving threshold for very_high_added_sugar is 8g
        r = score_mls(_nutrition(added_sugars_g=9), serving_g=None)
        assert r["mls_basis"] == "per_serving"
        assert "very_high_added_sugar" in r["flags"]


# ---------------------------------------------------------------------------
# Sodium scoring
# ---------------------------------------------------------------------------

class TestSodium:
    def test_very_high_sodium(self):
        r = score_mls(_nutrition(sodium_mg=801), serving_g=100)
        assert "very_high_sodium" in r["flags"]
        assert r["score"] >= 6

    def test_high_sodium(self):
        r = score_mls(_nutrition(sodium_mg=501), serving_g=100)
        assert "high_sodium" in r["flags"]
        assert r["score"] >= 3

    def test_moderate_sodium_not_flagged(self):
        r = score_mls(_nutrition(sodium_mg=400), serving_g=100)
        assert "high_sodium" not in r["flags"]
        assert "very_high_sodium" not in r["flags"]


# ---------------------------------------------------------------------------
# Saturated fat scoring
# ---------------------------------------------------------------------------

class TestSaturatedFat:
    def test_very_high_sat_fat(self):
        r = score_mls(_nutrition(saturated_fat_g=9), serving_g=100)
        assert "very_high_sat_fat" in r["flags"]
        assert r["score"] >= 5

    def test_high_sat_fat(self):
        r = score_mls(_nutrition(saturated_fat_g=6), serving_g=100)
        assert "high_sat_fat" in r["flags"]
        assert r["score"] >= 3


# ---------------------------------------------------------------------------
# Fiber and protein offsets
# ---------------------------------------------------------------------------

class TestOffsets:
    def test_high_fiber_offsets(self):
        # Very high added sugar (+7) minus high fiber offset (-3) = 4
        r = score_mls(_nutrition(added_sugars_g=25, dietary_fiber_g=5), serving_g=100)
        assert "high_fiber" in r["offsets"]
        assert r["score"] == 4

    def test_moderate_fiber_offsets(self):
        r = score_mls(_nutrition(added_sugars_g=11, dietary_fiber_g=3), serving_g=100)
        assert "moderate_fiber" in r["offsets"]

    def test_high_protein_offsets(self):
        r = score_mls(_nutrition(added_sugars_g=11, protein_g=20), serving_g=100)
        assert "high_protein" in r["offsets"]

    def test_moderate_protein_offsets(self):
        r = score_mls(_nutrition(added_sugars_g=11, protein_g=10), serving_g=100)
        assert "moderate_protein" in r["offsets"]

    def test_score_clamps_to_zero_not_negative(self):
        """Big offsets cannot push score below 0."""
        r = score_mls(_nutrition(dietary_fiber_g=10, protein_g=30), serving_g=100)
        assert r["score"] == 0

    def test_score_cannot_exceed_20(self):
        """Without energy density modifier, max raw = 7+6+5 = 18."""
        r = score_mls(
            _nutrition(added_sugars_g=100, sodium_mg=2000, saturated_fat_g=20),
            serving_g=100,
        )
        assert r["score"] == 18
        assert r["score"] <= 20

    def test_max_with_energy_density_reaches_20(self):
        """With energy density: 7+6+5+2 = 20, clamped at cap."""
        r = score_mls(
            _nutrition(added_sugars_g=100, sodium_mg=2000, saturated_fat_g=20,
                       calories=500),
            serving_g=100,
        )
        assert r["score"] == 20
        assert "energy_dense_sweet" in r["flags"]


# ---------------------------------------------------------------------------
# Serving size scaling
# ---------------------------------------------------------------------------

class TestServingSize:
    def test_serving_g_scales_per_100g(self):
        # 10g added_sugars in a 50g serving → 20g/100g → "high" (>10 per 100g)
        r = score_mls(_nutrition(added_sugars_g=10), serving_g=50)
        assert r["mls_basis"] == "per_100g"
        assert "high_added_sugar" in r["flags"]

    def test_tiny_serving_flag(self):
        r = score_mls(_nutrition(sodium_mg=100), serving_g=10)
        assert r["tiny_serving"] is True

    def test_normal_serving_no_tiny_flag(self):
        r = score_mls(_nutrition(sodium_mg=100), serving_g=30)
        assert r["tiny_serving"] is False

    def test_serving_g_zero_uses_per_serving(self):
        r = score_mls(_nutrition(added_sugars_g=5), serving_g=0)
        assert r["mls_basis"] == "per_serving"


# ---------------------------------------------------------------------------
# NaN / string values from scrapers
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_nan_values_treated_as_zero(self):
        import math
        r = score_mls({"added_sugars_g": float("nan"), "sodium_mg": float("nan")}, serving_g=100)
        assert r["score"] == 0

    def test_string_values_parsed(self):
        r = score_mls({"added_sugars_g": "12g", "sodium_mg": "600mg"}, serving_g=100)
        assert "high_added_sugar" in r["flags"]
        assert "high_sodium" in r["flags"]

    def test_none_values_treated_as_zero(self):
        r = score_mls({"added_sugars_g": None, "sodium_mg": None}, serving_g=100)
        assert r["score"] == 0


# ---------------------------------------------------------------------------
# Energy density modifier
# ---------------------------------------------------------------------------

class TestEnergyDensity:
    """Energy density modifier: +2 MLS when kcal/g > 4.0 AND sugar flag present."""

    # --- Products that should NOT fire ---

    def test_olive_oil_no_fire(self):
        """Olive oil: ~8.8 kcal/g, zero sugar → no fire."""
        r = score_mls(
            _nutrition(calories=120, saturated_fat_g=2),
            serving_g=14,  # 1 tbsp
        )
        assert "energy_dense_sweet" not in r["flags"]
        assert r["energy_density"] == round(120 / 14, 2)

    def test_natural_peanut_butter_no_fire(self):
        """Natural PB: ~6 kcal/g, no added sugar → no fire."""
        r = score_mls(
            _nutrition(calories=190, protein_g=7, saturated_fat_g=3,
                       dietary_fiber_g=2),
            serving_g=32,
        )
        assert "energy_dense_sweet" not in r["flags"]

    def test_almonds_no_fire(self):
        """Almonds: ~5.8 kcal/g, no sugar → no fire."""
        r = score_mls(
            _nutrition(calories=164, protein_g=6, dietary_fiber_g=3.5,
                       saturated_fat_g=1),
            serving_g=28,
        )
        assert "energy_dense_sweet" not in r["flags"]

    def test_cheese_no_fire(self):
        """Cheddar: ~4 kcal/g, no sugar → no fire."""
        r = score_mls(
            _nutrition(calories=113, protein_g=7, saturated_fat_g=6,
                       sodium_mg=180),
            serving_g=28,
        )
        assert "energy_dense_sweet" not in r["flags"]

    def test_jif_peanut_butter_no_fire(self):
        """Jif PB: ~6 kcal/g, ~3g added sugar per 33g serving → ~9g/100g,
        below high threshold (>10) → no sugar flag → no fire."""
        r = score_mls(
            _nutrition(calories=190, added_sugars_g=3, protein_g=7,
                       saturated_fat_g=3),
            serving_g=33,
        )
        assert "energy_dense_sweet" not in r["flags"]

    def test_dried_fruit_below_threshold(self):
        """Dried fruit: ~3.3 kcal/g — below 4.0 threshold even with sugar."""
        r = score_mls(
            _nutrition(calories=130, total_sugars_g=29),
            serving_g=40,
        )
        assert "energy_dense_sweet" not in r["flags"]

    def test_honey_below_threshold(self):
        """Honey: ~3.0 kcal/g — below threshold despite very high sugar."""
        r = score_mls(
            _nutrition(calories=64, added_sugars_g=17),
            serving_g=21,
        )
        assert "energy_dense_sweet" not in r["flags"]

    def test_high_density_no_sugar_flags_no_fire(self):
        """Energy-dense but no sugar → no fire (salted chips case)."""
        r = score_mls(
            _nutrition(calories=160, sodium_mg=170, saturated_fat_g=1),
            serving_g=28,
        )
        assert r["energy_density"] == round(160 / 28, 2)
        assert "energy_dense_sweet" not in r["flags"]

    # --- Products that SHOULD fire ---

    def test_milk_chocolate_fires(self):
        """Milk chocolate: ~5.3 kcal/g + very high sugar → fires."""
        r = score_mls(
            _nutrition(calories=230, added_sugars_g=24, saturated_fat_g=8),
            serving_g=42,
        )
        assert "energy_dense_sweet" in r["flags"]
        assert r["energy_density"] == round(230 / 42, 2)

    def test_cookies_fire(self):
        """Cookies: ~4.8 kcal/g + high added sugar → fires."""
        r = score_mls(
            _nutrition(calories=140, added_sugars_g=9, saturated_fat_g=3.5),
            serving_g=29,
        )
        assert "energy_dense_sweet" in r["flags"]

    def test_granola_bar_fires(self):
        """Granola bar: ~4.3 kcal/g + high sugar → fires."""
        r = score_mls(
            _nutrition(calories=190, added_sugars_g=12, saturated_fat_g=3),
            serving_g=42,
        )
        assert "energy_dense_sweet" in r["flags"]

    def test_candy_bar_fires(self):
        """Candy bar: ~5.0 kcal/g + very high sugar → fires."""
        r = score_mls(
            _nutrition(calories=250, added_sugars_g=28, saturated_fat_g=5),
            serving_g=50,
        )
        assert "energy_dense_sweet" in r["flags"]

    def test_total_sugar_fallback_also_triggers(self):
        """Energy density fires on total sugar flags too (no added sugar data)."""
        r = score_mls(
            _nutrition(calories=250, total_sugars_g=30),
            serving_g=50,
        )
        assert "very_high_total_sugar" in r["flags"]
        assert "energy_dense_sweet" in r["flags"]

    # --- Edge cases ---

    def test_no_calories_no_fire(self):
        """Missing calories field → modifier silently skipped."""
        r = score_mls(
            _nutrition(added_sugars_g=25),
            serving_g=50,
        )
        assert "energy_dense_sweet" not in r["flags"]
        assert "energy_density" not in r

    def test_no_serving_g_no_fire(self):
        """Missing serving_g → modifier silently skipped."""
        r = score_mls(
            _nutrition(calories=250, added_sugars_g=25),
            serving_g=None,
        )
        assert "energy_dense_sweet" not in r["flags"]

    def test_exactly_at_threshold_no_fire(self):
        """Exactly 4.0 kcal/g → does not fire (requires >4.0)."""
        r = score_mls(
            _nutrition(calories=200, added_sugars_g=25),
            serving_g=50,
        )
        assert r["energy_density"] == 4.0
        assert "energy_dense_sweet" not in r["flags"]

    def test_adds_exactly_2_points(self):
        """Verify the modifier adds exactly +2 to the score."""
        # Without calories: score = high_added_sugar(4) = 4
        r_base = score_mls(
            _nutrition(added_sugars_g=12),
            serving_g=100,
        )
        # With energy density: score = 4 + 2 = 6
        r_dense = score_mls(
            _nutrition(added_sugars_g=12, calories=500),
            serving_g=100,
        )
        assert r_dense["score"] == r_base["score"] + 2

    def test_energy_density_value_in_result(self):
        """energy_density key present and correctly computed when data available."""
        r = score_mls(
            _nutrition(calories=250),
            serving_g=50,
        )
        assert r["energy_density"] == 5.0


# ---------------------------------------------------------------------------
# Metabolic class assignment
# ---------------------------------------------------------------------------

class TestMetabolicClass:
    def test_classes(self):
        from scoring.scorer import _assign_metabolic_class
        assert _assign_metabolic_class(0) == "N0"
        assert _assign_metabolic_class(1) == "N0+"
        assert _assign_metabolic_class(3) == "N0+"
        assert _assign_metabolic_class(4) == "N1a"
        assert _assign_metabolic_class(6) == "N1a"
        assert _assign_metabolic_class(7) == "N1b"
        assert _assign_metabolic_class(8) == "N1b"
        assert _assign_metabolic_class(9) == "N2"
        assert _assign_metabolic_class(14) == "N2"
        assert _assign_metabolic_class(15) == "N3"
        assert _assign_metabolic_class(20) == "N3"
