"""Tests for scoring/rules_mds.py — Matrix Disruption Score."""

import pytest
from scoring.rules_mds import score_mds
from scoring.ontology import scan_ingredients


def _scan(text):
    return scan_ingredients(text)


# ---------------------------------------------------------------------------
# Zero score cases
# ---------------------------------------------------------------------------

class TestMDSZero:
    def test_clean_single_ingredient(self):
        r = score_mds(_scan("organic blueberries"))
        assert r["score"] == 0
        assert r["bucket_2_items"] == []
        assert r["bucket_3_items"] == []
        assert r["has_hydrogenated"] is False

    def test_no_additives_whole_food(self):
        r = score_mds(_scan("water, sea salt"))
        assert r["score"] == 0


# ---------------------------------------------------------------------------
# Bucket 2 scoring (refined ingredients, max 10)
# ---------------------------------------------------------------------------

class TestMDSBucket2:
    def test_single_bucket2_first_item_worth_3(self):
        r = score_mds(_scan("canola oil, water"))
        assert "canola oil" in r["bucket_2_items"]
        assert r["score"] == 3

    def test_two_bucket2_items(self):
        # first=3, second=2 → 5
        r = score_mds(_scan("canola oil, corn starch"))
        assert r["score"] == 5

    def test_bucket2_cap_at_10(self):
        # 6 bucket-2 items: 3 + 2*5 = 13, capped at 10
        text = "canola oil, corn starch, tapioca starch, potato starch, soybean oil, inulin"
        r = score_mds(_scan(text))
        assert r["score"] == 10

    def test_bucket2_depth_discount(self):
        """An item at depth 1 gets 50% of its base points."""
        scan = _scan("canola oil")
        depths = {"canola oil": 1}
        r = score_mds(scan, nesting_depths=depths)
        # depth 1, first item: 3 * 0.5 = 1.5 → rounds to 2
        assert r["score"] in (1, 2)


# ---------------------------------------------------------------------------
# Bucket 3 scoring (industrial substrates, max 20)
# ---------------------------------------------------------------------------

class TestMDSBucket3:
    def test_single_bucket3_first_item_worth_5(self):
        r = score_mds(_scan("maltodextrin, water"))
        assert "maltodextrin" in r["bucket_3_items"]
        assert r["score"] == 5

    def test_two_bucket3_items(self):
        # HFCS no longer double-matches "corn syrup" (v0.7.3 fix) → 2 B3 labels
        # maltodextrin (5) + high fructose corn syrup (3) = 8
        r = score_mds(_scan("maltodextrin, high fructose corn syrup"))
        assert r["score"] == 8
        assert len(r["bucket_3_items"]) == 2
        assert "high fructose corn syrup" in r["bucket_3_items"]
        assert "corn syrup" not in r["bucket_3_items"]

    def test_bucket3_cap_at_20(self):
        text = (
            "maltodextrin, high fructose corn syrup, modified corn starch, "
            "glucose syrup, pea protein isolate, hydrolyzed soy protein"
        )
        r = score_mds(_scan(text))
        assert r["score"] <= 30  # capped at 20 for B3 alone, plus any hydrogenated bonus

    def test_maltodextrin_not_in_tier_a(self):
        """v0.7.0: maltodextrin moved from TIER_A to BUCKET_3."""
        scan = _scan("maltodextrin")
        assert "maltodextrin" not in scan["tier_a"]
        assert "maltodextrin" in scan["bucket_3"]

    def test_hfcs_not_in_tier_a(self):
        """v0.7.0: HFCS moved from TIER_A to BUCKET_3."""
        scan = _scan("high fructose corn syrup")
        assert "high fructose corn syrup" not in scan["tier_a"]
        assert "high fructose corn syrup" in scan["bucket_3"]


# ---------------------------------------------------------------------------
# Hydrogenated fat bonus
# ---------------------------------------------------------------------------

class TestHydroBonus:
    def test_hydrogenated_fat_bonus(self):
        # "partially hydrogenated" no longer double-matches "hydrogenated" (v0.7.3 fix)
        # B2: soybean oil (3pts)
        # B3: partially hydrogenated fat only (5pts) — generic "hydrogenated fat" excluded
        # hydro bonus: +5pts → total = 3+5+5 = 13
        r = score_mds(_scan("partially hydrogenated soybean oil"))
        assert r["has_hydrogenated"] is True
        assert r["score"] == 13
        assert "partially hydrogenated fat" in r["bucket_3_items"]
        assert "hydrogenated fat" not in r["bucket_3_items"]

    def test_hydrogenated_fat_pure(self):
        """Pure 'hydrogenated coconut oil' has no soybean oil B2 item:
        B3: hydrogenated fat (5pts) + hydro bonus 5pts = 10."""
        r = score_mds(_scan("hydrogenated coconut oil"))
        assert r["has_hydrogenated"] is True
        assert r["score"] == 10

    def test_interesterified_fat(self):
        r = score_mds(_scan("interesterified palm oil"))
        assert r["has_hydrogenated"] is True

    def test_no_hydrogenated_in_clean_product(self):
        r = score_mds(_scan("oats, honey"))
        assert r["has_hydrogenated"] is False

    def test_hydrogenated_at_depth1_bonus_reduced(self):
        # "partially hydrogenated soybean oil" score at depth 0 = 16
        # Moving only "partially hydrogenated fat" to depth 1 reduces its contribution
        # but "hydrogenated fat" (the generic catch-all) stays at depth 0
        scan = _scan("partially hydrogenated soybean oil")
        r_full = score_mds(scan)
        depths = {"partially hydrogenated fat": 1}
        r_nested = score_mds(scan, nesting_depths=depths)
        assert r_nested["score"] <= r_full["score"]


# ---------------------------------------------------------------------------
# Mixed bucket scoring
# ---------------------------------------------------------------------------

class TestMDSMixed:
    def test_bucket2_and_bucket3_combined(self):
        # canola oil (B2, 3pts) + maltodextrin (B3, 5pts) = 8
        r = score_mds(_scan("canola oil, maltodextrin"))
        assert r["score"] == 8
        assert "canola oil" in r["bucket_2_items"]
        assert "maltodextrin" in r["bucket_3_items"]

    def test_total_cap_at_30(self):
        text = (
            "canola oil, corn starch, tapioca starch, potato starch, "
            "maltodextrin, high fructose corn syrup, modified corn starch, "
            "glucose syrup, pea protein isolate, partially hydrogenated soybean oil"
        )
        r = score_mds(_scan(text))
        assert r["score"] <= 30

    def test_no_depth_vs_depth_nesting(self):
        """Items with no nesting_depths provided behave identically to depth=0."""
        scan = _scan("maltodextrin, canola oil")
        r_nodepth = score_mds(scan)
        r_depth0 = score_mds(scan, nesting_depths={"maltodextrin": 0, "canola oil": 0})
        assert r_nodepth["score"] == r_depth0["score"]
