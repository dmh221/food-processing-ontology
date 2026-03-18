"""Tests for scoring/rules_afs.py — Additive/Formulation Score."""

import pytest
from scoring.rules_afs import score_afs
from scoring.ontology import scan_ingredients


def _scan(text):
    return scan_ingredients(text)


# ---------------------------------------------------------------------------
# Zero score cases
# ---------------------------------------------------------------------------

class TestAFSZero:
    def test_no_additives(self):
        r = score_afs(_scan("water, sea salt, apple cider vinegar"))
        assert r["score"] == 0
        assert r["tier_a"] == []
        assert r["tier_b"] == []

    def test_culinary_only_no_score(self):
        r = score_afs(_scan("baking soda, vanilla extract"))
        assert r["score"] == 0

    def test_tier_c_only_no_industrial_context_not_scored(self):
        """Tier C alone (1 item, no A/B) should NOT contribute to severity.
        Density still counts the matched label, so score = density = 1."""
        r = score_afs(_scan("citric acid"))
        assert r["tier_c_scored"] is False
        assert r["severity"] == 0   # no C severity without industrial context
        assert r["density"] == 1    # density counts the label regardless
        assert r["score"] == 1


# ---------------------------------------------------------------------------
# Tier A severity
# ---------------------------------------------------------------------------

class TestAFSTierA:
    def test_single_tier_a(self):
        # red 40 (weight=5) + density 1 = 6
        r = score_afs(_scan("red 40"))
        assert "red 40" in r["tier_a"]
        assert r["severity"] == 5
        assert r["density"] == 1
        assert r["score"] == 6

    def test_two_tier_a(self):
        # red 40 (5) + polysorbate 80 (5) + density 2 = 12
        r = score_afs(_scan("red 40, polysorbate 80"))
        assert r["severity"] == 10
        assert r["density"] == 2
        assert r["score"] == 12

    def test_tier_a_bonus_3_to_4(self):
        # 3 top-level Tier A → +4 bonus
        text = "red 40, polysorbate 80, sodium stearoyl lactylate"
        r = score_afs(_scan(text))
        assert r["severity"] == 5 * 3 + 4  # 15 base + 4 bonus = 19
        assert r["score"] == 19 + 3  # severity 19 + density 3 = 22

    def test_tier_a_bonus_5_to_7(self):
        text = "red 40, polysorbate 80, sodium stearoyl lactylate, datem, mono- and diglycerides"
        r = score_afs(_scan(text))
        # 5 * 5 = 25 + bonus 8 = 33
        assert r["severity"] == 33

    def test_natural_flavor_reduced_weight(self):
        """natural flavor has weight=2, not the default 5."""
        r = score_afs(_scan("natural flavor"))
        assert r["severity"] == 2  # weight override

    def test_tier_c_scored_when_tier_a_present(self):
        r = score_afs(_scan("red 40, citric acid"))
        assert r["tier_c_scored"] is True
        assert "citric acid" in r["tier_c"]


# ---------------------------------------------------------------------------
# Tier B severity
# ---------------------------------------------------------------------------

class TestAFSTierB:
    def test_single_tier_b(self):
        # xanthan gum (weight=3) + density 1 = 4
        r = score_afs(_scan("xanthan gum"))
        assert "xanthan gum" in r["tier_b"]
        assert r["severity"] == 3
        assert r["score"] == 4

    def test_tier_b_triggers_tier_c_scoring(self):
        r = score_afs(_scan("xanthan gum, citric acid"))
        assert r["tier_c_scored"] is True
        assert "citric acid" in r["tier_c"]


# ---------------------------------------------------------------------------
# Tier C conditional scoring
# ---------------------------------------------------------------------------

class TestAFSTierC:
    def test_three_tier_c_items_triggers_scoring(self):
        """≥3 unique items total (all C) triggers tier_c_scored."""
        r = score_afs(_scan("citric acid, malic acid, ascorbic acid"))
        assert r["tier_c_scored"] is True
        assert r["score"] > 0

    def test_two_tier_c_items_no_scoring(self):
        """Only 2 unique items (both C, no A/B) → severity=0, but density=2."""
        r = score_afs(_scan("citric acid, malic acid"))
        assert r["tier_c_scored"] is False
        assert r["severity"] == 0   # no C severity without industrial context
        assert r["score"] == 2      # density=2 contributes even without C scoring


# ---------------------------------------------------------------------------
# Depth discounting
# ---------------------------------------------------------------------------

class TestAFSDepth:
    def test_depth_0_full_weight(self):
        scan = _scan("red 40")
        r_no = score_afs(scan)
        r_0 = score_afs(scan, nesting_depths={"red 40": 0})
        assert r_no["score"] == r_0["score"]

    def test_depth_1_reduced_weight(self):
        scan = _scan("red 40")
        r_full = score_afs(scan, nesting_depths={"red 40": 0})
        r_nested = score_afs(scan, nesting_depths={"red 40": 1})
        assert r_nested["severity"] < r_full["severity"]

    def test_depth_2_further_reduced(self):
        scan = _scan("red 40")
        r_d1 = score_afs(scan, nesting_depths={"red 40": 1})
        r_d2 = score_afs(scan, nesting_depths={"red 40": 2})
        assert r_d2["severity"] <= r_d1["severity"]

    def test_depth1_tier_a_bonus_not_counted(self):
        """Deeply nested Tier A items should not trigger the top-level Tier A bonus."""
        text = "red 40, polysorbate 80, datem"
        scan = _scan(text)
        # All at depth 1: top_level_a = 0, no bonus
        depths = {"red 40": 1, "polysorbate": 1, "DATEM": 1}
        r = score_afs(scan, nesting_depths=depths)
        # Severity = 5*0.6 * 3 = 9 (no bonus since top_level_a=0)
        assert r["severity"] == round(5 * 0.6 * 3)


# ---------------------------------------------------------------------------
# AFS cap at 80 (raised from 40 in v0.8.0)
# ---------------------------------------------------------------------------

class TestAFSCap:
    def test_score_capped_at_80(self):
        # Large number of Tier A items — even extreme cases should not exceed 80
        text = (
            "red 40, yellow 5, blue 1, polysorbate 80, datem, "
            "mono- and diglycerides, sodium stearoyl lactylate, "
            "carboxymethyl cellulose, aspartame, sucralose, acesulfame"
        )
        r = score_afs(_scan(text))
        assert r["score"] <= 80

    def test_score_exceeds_old_cap_of_40(self):
        """v0.8.0: highly additive-laden products now score above 40."""
        text = (
            "red 40, yellow 5, blue 1, polysorbate 80, datem, "
            "mono- and diglycerides, sodium stearoyl lactylate, "
            "carboxymethyl cellulose, aspartame, sucralose, acesulfame, "
            "artificial color, sodium benzoate, potassium sorbate, "
            "propylene glycol, carrageenan, modified corn starch"
        )
        r = score_afs(_scan(text))
        assert r["score"] > 40, f"Expected >40 with many Tier A items, got {r['score']}"
