"""Tests for scoring/ontology.py — pattern matching and scan_ingredients()."""

import pytest
from scoring.ontology import scan_ingredients, CALORIC_SWEETENERS, _find_unique_matches


# ---------------------------------------------------------------------------
# scan_ingredients: empty / None input
# ---------------------------------------------------------------------------

class TestScanIngredientsEmpty:
    def test_empty_string_returns_all_empty_dicts(self):
        result = scan_ingredients("")
        expected_keys = {
            "tier_a", "tier_b", "tier_c", "culinary",
            "bucket_2", "bucket_3",
            "hits_a", "hits_b", "hits_c",
            "caloric_sweeteners", "nns", "flavors",
            "flavor_enhancers", "coating_fats",
        }
        assert set(result.keys()) == expected_keys
        for key in expected_keys:
            assert result[key] == {}, f"Expected {key} to be empty, got {result[key]}"

    def test_none_returns_all_empty_dicts(self):
        # normalize_ingredients will always pass a string; test the guard anyway
        result = scan_ingredients(None)
        assert result["tier_a"] == {}
        assert result["caloric_sweeteners"] == {}


# ---------------------------------------------------------------------------
# Tier A — strong UPF markers
# ---------------------------------------------------------------------------

class TestTierA:
    def test_red_40(self):
        r = scan_ingredients("red 40, yellow 5")
        assert "red 40" in r["tier_a"]
        assert "yellow 5" in r["tier_a"]

    def test_fd_c_dye(self):
        r = scan_ingredients("fd&c red no. 40")
        assert "fd&c dye" in r["tier_a"]

    def test_polysorbate_80(self):
        r = scan_ingredients("polysorbate 80")
        assert "polysorbate" in r["tier_a"]

    def test_mono_and_diglycerides(self):
        r = scan_ingredients("mono- and diglycerides of fatty acids")
        assert "mono- and diglycerides" in r["tier_a"]

    def test_natural_flavor(self):
        r = scan_ingredients("natural flavor, water")
        assert "natural flavor" in r["tier_a"]

    def test_artificial_flavor(self):
        r = scan_ingredients("artificial flavoring")
        assert "artificial flavor" in r["tier_a"]

    def test_malt_flavor(self):
        """Frosted Flakes-style: malt flavor must register as Tier A."""
        r = scan_ingredients("whole grain corn, sugar, malt flavor, salt")
        assert "malt flavor" in r["tier_a"], "malt flavor should be Tier A"

    def test_sapp(self):
        r = scan_ingredients("sodium acid pyrophosphate, baking soda")
        assert "SAPP" in r["tier_a"]

    def test_disodium_phosphate(self):
        r = scan_ingredients("disodium phosphate")
        assert "disodium phosphate" in r["tier_a"]

    def test_artificial_color_catchall(self):
        r = scan_ingredients("artificial colors")
        assert "artificial color" in r["tier_a"]

    def test_propylene_glycol(self):
        r = scan_ingredients("propylene glycol, water")
        assert "propylene glycol" in r["tier_a"]

    def test_propylene_glycol_alginate_no_match(self):
        """propylene glycol alginate should NOT match propylene glycol."""
        r = scan_ingredients("propylene glycol alginate")
        assert "propylene glycol" not in r["tier_a"]

    def test_epg_full_name(self):
        r = scan_ingredients("esterified propoxylated glycerol")
        assert "EPG" in r["tier_a"]
        assert r["tier_a"]["EPG"].category == "fat_replacer"

    def test_epg_abbreviation(self):
        r = scan_ingredients("modified plant fat [epg]")
        assert "EPG" in r["tier_a"]

    def test_epg_in_bucket3(self):
        r = scan_ingredients("esterified propoxylated glycerol")
        assert "EPG" in r["bucket_3"]

    def test_modified_plant_fat(self):
        r = scan_ingredients("modified plant fat, sugar, cocoa butter")
        assert "EPG" in r["tier_a"]


# ---------------------------------------------------------------------------
# Tier B — moderate markers
# ---------------------------------------------------------------------------

class TestTierB:
    def test_xanthan_gum(self):
        r = scan_ingredients("xanthan gum")
        assert "xanthan gum" in r["tier_b"]

    def test_carrageenan(self):
        r = scan_ingredients("carrageenan")
        assert "carrageenan" in r["tier_b"]

    def test_sodium_benzoate(self):
        r = scan_ingredients("sodium benzoate")
        assert "sodium benzoate" in r["tier_b"]

    def test_potassium_sorbate(self):
        r = scan_ingredients("potassium sorbate")
        assert "potassium sorbate" in r["tier_b"]

    def test_msg(self):
        r = scan_ingredients("monosodium glutamate")
        assert "MSG" in r["tier_b"]

    def test_lecithin(self):
        r = scan_ingredients("sunflower lecithin")
        assert "lecithin" in r["tier_b"]

    def test_caramel_color(self):
        r = scan_ingredients("caramel color")
        assert "caramel color" in r["tier_b"]

    def test_sodium_citrate(self):
        r = scan_ingredients("sodium citrate")
        assert "sodium citrate" in r["tier_b"]

    def test_gum_arabic_variants(self):
        for text in ("gum arabic", "acacia gum", "arabic gum"):
            r = scan_ingredients(text)
            assert "gum arabic" in r["tier_b"], f"'{text}' should match gum arabic"

    def test_carnauba_wax(self):
        r = scan_ingredients("carnauba wax")
        assert "carnauba wax" in r["tier_b"]

    def test_gelatin(self):
        r = scan_ingredients("gelatin, water, sugar")
        assert "gelatin" in r["tier_b"]

    def test_allulose_in_tier_b(self):
        """v0.9.0: allulose reclassified from NNS to Tier B (rare sugar)."""
        r = scan_ingredients("allulose, water")
        assert "allulose" in r["tier_b"]
        assert r["tier_b"]["allulose"].category == "rare_sugar"

    def test_allulose_not_in_nns(self):
        """v0.9.0: allulose is a monosaccharide, not an NNS."""
        r = scan_ingredients("allulose")
        assert "allulose" not in r["nns"]


# ---------------------------------------------------------------------------
# Tier C — tracked conditionally
# ---------------------------------------------------------------------------

class TestTierC:
    def test_citric_acid(self):
        r = scan_ingredients("citric acid")
        assert "citric acid" in r["tier_c"]

    def test_malic_acid(self):
        r = scan_ingredients("malic acid")
        assert "malic acid" in r["tier_c"]

    # Fortification markers (v0.7.2)
    def test_niacinamide(self):
        r = scan_ingredients("niacinamide")
        assert "niacinamide" in r["tier_c"]
        assert r["tier_c"]["niacinamide"].category == "fortification"

    def test_folic_acid(self):
        r = scan_ingredients("folic acid")
        assert "folic acid" in r["tier_c"]

    def test_riboflavin(self):
        r = scan_ingredients("riboflavin")
        assert "riboflavin" in r["tier_c"]

    def test_ferric_phosphate(self):
        r = scan_ingredients("ferric phosphate")
        assert "ferric compound" in r["tier_c"]

    def test_thiamin_mononitrate(self):
        r = scan_ingredients("thiamin mononitrate")
        assert "thiamin" in r["tier_c"]

    def test_thiamin_nitrate(self):
        r = scan_ingredients("thiamine nitrate")
        assert "thiamin" in r["tier_c"]

    # Natural color false-positive prevention (v0.7.2)
    def test_turmeric_powder_no_match(self):
        """Culinary turmeric (spice) should NOT register as turmeric color."""
        r = scan_ingredients("turmeric powder, black pepper, cumin")
        assert "turmeric color" not in r["tier_c"]

    def test_turmeric_extract_matches(self):
        r = scan_ingredients("turmeric extract")
        assert "turmeric color" in r["tier_c"]

    def test_turmeric_color_matches(self):
        r = scan_ingredients("turmeric color")
        assert "turmeric color" in r["tier_c"]

    def test_paprika_spice_no_match(self):
        """Plain 'paprika' (spice) should NOT match paprika extract."""
        r = scan_ingredients("paprika, garlic, onion")
        assert "paprika extract" not in r["tier_c"]

    def test_paprika_extract_matches(self):
        r = scan_ingredients("paprika extract")
        assert "paprika extract" in r["tier_c"]

    def test_beet_sugar_no_match(self):
        """'beet sugar' is a sweetener, NOT beet color."""
        r = scan_ingredients("beet sugar")
        assert "beet color" not in r["tier_c"]

    def test_beet_color_matches(self):
        r = scan_ingredients("beet juice extract")
        assert "beet color" in r["tier_c"]

    def test_beta_carotene_matches(self):
        r = scan_ingredients("beta-carotene")
        assert "beta carotene" in r["tier_c"]


# ---------------------------------------------------------------------------
# Bucket 2 / Bucket 3
# ---------------------------------------------------------------------------

class TestBuckets:
    def test_maltodextrin_in_bucket3(self):
        r = scan_ingredients("maltodextrin")
        assert "maltodextrin" in r["bucket_3"]
        assert "maltodextrin" not in r["tier_a"]

    def test_hfcs_in_bucket3(self):
        r = scan_ingredients("high fructose corn syrup")
        assert "high fructose corn syrup" in r["bucket_3"]
        assert "high fructose corn syrup" not in r["tier_a"]

    def test_modified_starch_in_bucket3(self):
        r = scan_ingredients("modified corn starch")
        assert "modified starch" in r["bucket_3"]

    def test_protein_isolate_in_bucket3(self):
        r = scan_ingredients("pea protein isolate")
        assert "protein isolate" in r["bucket_3"]

    def test_hydrolyzed_protein_in_bucket3(self):
        r = scan_ingredients("hydrolyzed soy protein")
        assert "hydrolyzed protein" in r["bucket_3"]

    def test_canola_oil_in_bucket2(self):
        r = scan_ingredients("canola oil")
        assert "canola oil" in r["bucket_2"]

    def test_corn_starch_in_bucket2(self):
        r = scan_ingredients("corn starch")
        assert "corn starch" in r["bucket_2"]

    def test_enriched_flour_in_bucket2(self):
        r = scan_ingredients("enriched wheat flour")
        assert "enriched flour" in r["bucket_2"]

    def test_corn_syrup_solids_not_corn_syrup(self):
        """'corn syrup solids' should be Bucket 2, not Bucket 3 corn syrup."""
        r = scan_ingredients("corn syrup solids")
        assert "corn syrup solids" in r["bucket_2"]
        assert "corn syrup" not in r["bucket_3"]

    def test_hydrogenated_fat_in_bucket3(self):
        r = scan_ingredients("partially hydrogenated soybean oil")
        assert "partially hydrogenated fat" in r["bucket_3"]

    def test_soluble_corn_fiber_in_bucket2(self):
        """v0.9.0: soluble corn fiber added alongside inulin/chicory fiber."""
        r = scan_ingredients("soluble corn fiber")
        assert "soluble corn fiber" in r["bucket_2"]
        assert r["bucket_2"]["soluble corn fiber"].category == "fiber_isolate"


# ---------------------------------------------------------------------------
# Caloric sweeteners — double-counting fix (v0.7.2)
# ---------------------------------------------------------------------------

class TestCaloricSweeteners:
    def test_cane_sugar_only_is_one_type(self):
        """The critical HES double-counting bug fix: cane sugar must not also
        match the generic 'sugar' pattern."""
        sw = _find_unique_matches(CALORIC_SWEETENERS, "cane sugar")
        assert list(sw.keys()) == ["cane sugar"], (
            f"Expected only ['cane sugar'], got {list(sw.keys())}"
        )

    def test_brown_sugar_only_is_one_type(self):
        sw = _find_unique_matches(CALORIC_SWEETENERS, "brown sugar")
        assert list(sw.keys()) == ["brown sugar"]

    def test_plain_sugar_matches_generic(self):
        sw = _find_unique_matches(CALORIC_SWEETENERS, "sugar, water")
        assert "sugar" in sw

    def test_sugar_alcohol_not_matched(self):
        """'sugar alcohol' should NOT match the generic sugar pattern."""
        sw = _find_unique_matches(CALORIC_SWEETENERS, "sugar alcohol")
        assert "sugar" not in sw

    def test_cane_plus_brown_sugar_is_two_types(self):
        sw = _find_unique_matches(CALORIC_SWEETENERS, "cane sugar, brown sugar")
        assert len(sw) == 2
        assert "cane sugar" in sw
        assert "brown sugar" in sw

    def test_all_qualified_variants_distinct(self):
        text = "cane sugar, brown sugar, powdered sugar, honey, maple syrup"
        sw = _find_unique_matches(CALORIC_SWEETENERS, text)
        assert len(sw) == 5
        assert "sugar" not in sw  # generic should not fire alongside qualified variants

    def test_honey_matches(self):
        sw = _find_unique_matches(CALORIC_SWEETENERS, "honey")
        assert "honey" in sw

    def test_hfcs_matches(self):
        sw = _find_unique_matches(CALORIC_SWEETENERS, "high fructose corn syrup")
        assert "HFCS" in sw

    def test_dextrose_matches(self):
        sw = _find_unique_matches(CALORIC_SWEETENERS, "dextrose")
        assert "dextrose" in sw

    def test_allulose_in_caloric_sweeteners(self):
        """v0.9.0: allulose is a rare sugar, classified as caloric sweetener."""
        sw = _find_unique_matches(CALORIC_SWEETENERS, "allulose")
        assert "allulose" in sw


# ---------------------------------------------------------------------------
# HES pattern lists (NNS, flavors, coating fats)
# ---------------------------------------------------------------------------

class TestHESPatternLists:
    def test_sucralose_in_nns(self):
        r = scan_ingredients("sucralose")
        assert "sucralose" in r["nns"]

    def test_stevia_in_nns(self):
        r = scan_ingredients("stevia leaf extract")
        assert "stevia" in r["nns"]

    def test_natural_flavor_in_flavors(self):
        r = scan_ingredients("natural flavor")
        assert "natural flavor" in r["flavors"]

    def test_malt_flavor_in_flavors(self):
        r = scan_ingredients("malt flavor")
        assert "malt flavor" in r["flavors"]

    def test_yeast_extract_in_enhancers(self):
        r = scan_ingredients("yeast extract")
        assert "yeast extract" in r["flavor_enhancers"]

    def test_palm_oil_in_coating_fats(self):
        r = scan_ingredients("palm oil")
        assert "palm oil" in r["coating_fats"]

    def test_hydrogenated_in_coating_fats(self):
        r = scan_ingredients("partially hydrogenated soybean oil")
        assert "hydrogenated fat" in r["coating_fats"]
