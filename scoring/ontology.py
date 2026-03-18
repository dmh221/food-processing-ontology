"""Food ingredient ontology — tiers, buckets, and compiled regex patterns.

This is the knowledge base for the Food Integrity Scoring system.
Every additive/ingredient is classified by:
  - tier (A/B/C/culinary) — how strong a UPF marker it is
  - bucket (0-4) — how far from whole-food origin
  - category — functional role (emulsifier, sweetener, dye, etc.)

scan_ingredients() is the main entry point: give it normalized ingredient
text and get back structured match results for all scoring functions.
"""

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Pattern data structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pattern:
    regex: re.Pattern
    label: str
    tier: str          # "A", "B", "C", "culinary", or None
    bucket: int | None  # 0-4 or None
    category: str       # e.g. "dye", "emulsifier", "sweetener", etc.
    weight: int = 0     # AFS weight override (0 = use default for tier)


def _p(pattern: str, label: str, tier: str, bucket: int | None,
       category: str, weight: int = 0) -> Pattern:
    """Shorthand to build a Pattern with word-boundary regex."""
    return Pattern(
        regex=re.compile(pattern, re.IGNORECASE),
        label=label,
        tier=tier,
        bucket=bucket,
        category=category,
        weight=weight,
    )


# ---------------------------------------------------------------------------
# TIER A — Strong UPF markers
# ---------------------------------------------------------------------------

TIER_A: list[Pattern] = [
    # --- Industrial substrates moved to BUCKET_3 (v0.7.0) ---
    # maltodextrin, HFCS, glucose syrup, corn syrup, modified starch,
    # protein isolate, hydrolyzed protein — now scored by MDS only.
    # Removing from AFS eliminates double-counting (MDS r²: 0.857 → 0.764).

    # --- Artificial dyes ---
    _p(r"\bred\s*(?:no\.?\s*)?40\b", "red 40", "A", 4, "dye"),
    _p(r"\bred\s*(?:no\.?\s*)?3\b", "red 3", "A", 4, "dye"),
    _p(r"\byellow\s*(?:no\.?\s*)?5\b", "yellow 5", "A", 4, "dye"),
    _p(r"\byellow\s*(?:no\.?\s*)?6\b", "yellow 6", "A", 4, "dye"),
    _p(r"\bblue\s*(?:no\.?\s*)?1\b", "blue 1", "A", 4, "dye"),
    _p(r"\bblue\s*(?:no\.?\s*)?2\b", "blue 2", "A", 4, "dye"),
    _p(r"\bfd&c\b|fd\s*&\s*c\b", "fd&c dye", "A", 4, "dye"),
    _p(r"\btartrazine\b", "tartrazine", "A", 4, "dye"),
    _p(r"\ballura\s+red\b", "allura red", "A", 4, "dye"),
    _p(r"\bbrilliant\s+blue\b", "brilliant blue", "A", 4, "dye"),
    # caramel color moved to TIER_B (v0.3) — see TIER_B section

    # --- Flavors ---
    _p(r"\bnatural\s+flavou?r(?:s|ing)?\b", "natural flavor", "A", 4, "flavor", weight=2),
    _p(r"\bartificial\s+flavou?r(?:s|ing)?\b", "artificial flavor", "A", 4, "flavor"),
    _p(r"\bmalt\s+flavou?r(?:s|ing)?\b", "malt flavor", "A", 4, "flavor"),

    # --- Emulsifiers (strong markers) ---
    _p(r"\bpolysorbate\s*\d*\b", "polysorbate", "A", 4, "emulsifier"),
    _p(r"\bdatem\b", "DATEM", "A", 4, "emulsifier"),
    _p(r"\bmono[\s-]+and\s+diglycerides\b", "mono- and diglycerides", "A", 4, "emulsifier"),
    _p(r"\bmono[\s-]*diglycerides\b", "mono- and diglycerides", "A", 4, "emulsifier"),
    _p(r"\bsorbitan\s+\w+\b", "sorbitan ester", "A", 4, "emulsifier"),
    _p(r"\bsodium\s+stearoyl\s+lactylate\b", "sodium stearoyl lactylate", "A", 4, "emulsifier"),
    _p(r"\bcalcium\s+stearoyl\s+lactylate\b", "calcium stearoyl lactylate", "A", 4, "emulsifier"),
    _p(r"\bcarboxymethyl\s*cellulose\b", "CMC", "A", 4, "emulsifier"),

    # --- Non-nutritive sweeteners ---
    _p(r"\baspartame\b", "aspartame", "A", 4, "nns"),
    _p(r"\bsucralose\b", "sucralose", "A", 4, "nns"),
    _p(r"\bacesulfame\b", "acesulfame K", "A", 4, "nns"),
    _p(r"\bsaccharin\b", "saccharin", "A", 4, "nns"),
    _p(r"\bneotame\b", "neotame", "A", 4, "nns"),
    _p(r"\badvantame\b", "advantame", "A", 4, "nns"),

    # --- Phosphate emulsifiers / leavening agents (v0.7.1) ---
    # Phosphates are strong UPF markers: processed cheese, deli meats, creamers,
    # commercial baked goods. SAPP is the dominant industrial leavening acid.
    _p(r"\bsodium\s+acid\s+pyrophosphate\b", "SAPP", "A", 4, "phosphate"),
    _p(r"\bsapp\b", "SAPP", "A", 4, "phosphate"),
    _p(r"\bdisodium\s+phosphate\b", "disodium phosphate", "A", 4, "phosphate"),
    _p(r"\btrisodium\s+phosphate\b", "trisodium phosphate", "A", 4, "phosphate"),
    _p(r"\bsodium\s+phosphate[s]?\b", "sodium phosphate", "A", 4, "phosphate"),
    _p(r"\bsodium\s+aluminum\s+phosphate\b", "sodium aluminum phosphate", "A", 4, "phosphate"),
    _p(r"\bsodium\s+hexametaphosphate\b", "sodium hexametaphosphate", "A", 4, "phosphate"),
    _p(r"\btetrasodium\s+pyrophosphate\b", "tetrasodium pyrophosphate", "A", 4, "phosphate"),

    # --- Artificial color catch-all (v0.7.1) ---
    # Catches "artificial color", "artificial colours" when specific dye names
    # (Red 40, Yellow 5, etc.) are not listed. Does NOT match "color added" alone.
    _p(r"\bartificial\s+colou?r(?:s|ing)?\b", "artificial color", "A", 4, "dye"),

    # --- Propylene glycol (v0.7.1) ---
    # Industrial humectant/carrier solvent. Strong UPF marker in frostings,
    # icings, artificial flavors, some beverages. Exclude "alginate" to avoid
    # false match on "propylene glycol alginate" — caught separately if needed.
    _p(r"\bpropylene\s+glycol(?!\s+alginate)\b", "propylene glycol", "A", 4, "humectant"),

    # --- Fat replacers (v0.9.0) ---
    # EPG (esterified propoxylated glycerol): industrial fat replacer used in
    # reduced-fat snacks (e.g. David bars). Enzymatically synthesized from
    # propylene oxide + glycerol; not found in nature. Standard Tier A weight.
    # Labeled variously as full chemical name, abbreviation, or "modified plant fat".
    _p(r"\besterified\s+propoxylated\s+glycerol\b", "EPG", "A", 4, "fat_replacer"),
    _p(r"\bepg\b", "EPG", "A", 4, "fat_replacer"),
    _p(r"\bmodified\s+plant\s+fat\b", "EPG", "A", 4, "fat_replacer"),
]


# ---------------------------------------------------------------------------
# TIER B — Moderate markers (context-dependent)
# ---------------------------------------------------------------------------

TIER_B: list[Pattern] = [
    # --- Hydrocolloid gums ---
    _p(r"\bxanthan\s+gum\b", "xanthan gum", "B", 4, "gum"),
    _p(r"\bguar\s+gum\b", "guar gum", "B", 4, "gum"),
    _p(r"\bgellan\s+gum\b", "gellan gum", "B", 4, "gum"),
    _p(r"\bcarrageenan\b", "carrageenan", "B", 4, "gum"),
    _p(r"\bcellulose\s+gum\b", "cellulose gum", "B", 4, "gum"),
    _p(r"\blocust\s+bean\s+gum\b", "locust bean gum", "B", 4, "gum"),
    _p(r"\btara\s+gum\b", "tara gum", "B", 4, "gum"),

    # --- Emulsifiers (milder) ---
    _p(r"\blecithin\b", "lecithin", "B", 4, "emulsifier"),

    # --- Colorings ---
    _p(r"\bcaramel\s+color\b", "caramel color", "B", 4, "dye"),

    # --- Preservatives ---
    _p(r"\bsorbic\s+acid\b", "sorbic acid", "B", 4, "preservative"),
    _p(r"\bpotassium\s+sorbate\b", "potassium sorbate", "B", 4, "preservative"),
    _p(r"\bsodium\s+benzoate\b", "sodium benzoate", "B", 4, "preservative"),
    _p(r"\bcalcium\s+propionate\b", "calcium propionate", "B", 4, "preservative"),
    _p(r"\bsodium\s+propionate\b", "sodium propionate", "B", 4, "preservative"),
    _p(r"\bsodium\s+nitrite\b", "sodium nitrite", "B", 4, "preservative"),
    _p(r"\bsodium\s+nitrate\b", "sodium nitrate", "B", 4, "preservative"),
    _p(r"\bsodium\s+erythorbate\b", "sodium erythorbate", "B", 4, "preservative"),
    _p(r"\btbhq\b", "TBHQ", "B", 4, "preservative"),
    _p(r"\bbht\b", "BHT", "B", 4, "preservative"),
    _p(r"\bbha\b", "BHA", "B", 4, "preservative"),

    # --- Flavor enhancers (yeast extract gets reduced weight +2) ---
    _p(r"\byeast\s+extract\b", "yeast extract", "B", 4, "flavor_enhancer", weight=2),
    _p(r"\bmonosodium\s+glutamate\b", "MSG", "B", 4, "flavor_enhancer"),
    _p(r"\bmsg\b", "MSG", "B", 4, "flavor_enhancer"),
    _p(r"\bautolyzed\s+yeast\b", "autolyzed yeast", "B", 4, "flavor_enhancer"),
    _p(r"\bdisodium\s+inosinate\b", "disodium inosinate", "B", 4, "flavor_enhancer"),
    _p(r"\bdisodium\s+guanylate\b", "disodium guanylate", "B", 4, "flavor_enhancer"),

    # --- Sugar alcohols ---
    _p(r"\berythritol\b", "erythritol", "B", 4, "sugar_alcohol"),
    _p(r"\bsorbitol\b", "sorbitol", "B", 4, "sugar_alcohol"),
    _p(r"\bxylitol\b", "xylitol", "B", 4, "sugar_alcohol"),
    _p(r"\bmaltitol\b", "maltitol", "B", 4, "sugar_alcohol"),
    _p(r"\bmannitol\b", "mannitol", "B", 4, "sugar_alcohol"),
    _p(r"\bisomalt\b", "isomalt", "B", 4, "sugar_alcohol"),

    # --- Rare sugar analogs (v0.9.0) ---
    # Allulose: C-3 epimer of fructose, enzymatically produced from corn fructose.
    # Near-zero calorie monosaccharide (0.2-0.4 kcal/g); mechanistically distinct
    # from synthetic NNS. Classified as Tier B (formulation marker) rather than
    # Tier A NNS — it IS a sugar, just industrially produced and strategically
    # used to reduce label sugar counts.
    _p(r"\ballulose\b", "allulose", "B", 4, "rare_sugar"),

    # --- Buffering / sequestering agents (v0.7.1) ---
    # Sodium citrate: emulsifying salt in processed cheese, buffer in soft drinks.
    # Not a strong standalone UPF marker but very common in formulated products.
    _p(r"\bsodium\s+citrate\b", "sodium citrate", "B", 4, "buffer"),
    _p(r"\bpotassium\s+citrate\b", "potassium citrate", "B", 4, "buffer"),

    # --- Potassium phosphates (moved from Tier A, v0.9.2) ---
    # Potassium phosphates deliver minerals (electrolyte drinks, oat milks,
    # alkaline waters) — same function as potassium chloride. Sodium phosphates
    # (SAPP, disodium, trisodium, etc.) remain Tier A as industrial emulsifiers.
    _p(r"\bdipotassium\s+phosphate\b", "dipotassium phosphate", "B", 4, "phosphate"),
    _p(r"\bmonopotassium\s+phosphate\b", "monopotassium phosphate", "B", 4, "phosphate"),
    _p(r"\bpotassium\s+phosphate[s]?\b", "potassium phosphate", "B", 4, "phosphate"),

    # --- Hydrocolloid gums (additional, v0.7.1) ---
    _p(r"\bgum\s+arabic\b", "gum arabic", "B", 4, "gum"),
    _p(r"\bacacia\s+gum\b", "gum arabic", "B", 4, "gum"),
    _p(r"\barabic\s+gum\b", "gum arabic", "B", 4, "gum"),
    _p(r"\bmethylcellulose\b", "methylcellulose", "B", 4, "gum"),
    _p(r"\bhydroxypropyl\s+methylcellulose\b", "HPMC", "B", 4, "gum"),
    _p(r"\bhpmc\b", "HPMC", "B", 4, "gum"),

    # --- Coating and glazing agents (v0.7.1) ---
    # Carnauba wax: confectionery glaze (candy shells, fruit coatings). Indicates
    # industrial surface treatment; same class as shellac.
    _p(r"\bcarnauba\s+wax\b", "carnauba wax", "B", 4, "glazing_agent"),
    _p(r"\bshellac\b", "shellac", "B", 4, "glazing_agent"),

    # --- Gelling agents (v0.7.1) ---
    # Gelatin: hydrolyzed collagen. Ancient, but industrially produced and a
    # formulation marker in gummies, marshmallows, aspic, gel-based desserts.
    _p(r"\bgelatin\b", "gelatin", "B", 4, "gelling_agent"),
    _p(r"\bgelatine\b", "gelatin", "B", 4, "gelling_agent"),

    # --- Anti-caking / mineral stabilizers (v0.7.1) ---
    _p(r"\btricalcium\s+phosphate\b", "tricalcium phosphate", "B", 4, "anticaking"),
    _p(r"\bcalcium\s+phosphate\b", "calcium phosphate", "B", 4, "anticaking"),
    _p(r"\bsilicon\s+dioxide\b", "silicon dioxide", "B", 4, "anticaking"),
    _p(r"\bcalcium\s+silicate\b", "calcium silicate", "B", 4, "anticaking"),
]


# ---------------------------------------------------------------------------
# TIER C — Tracked, conditionally scored
# ---------------------------------------------------------------------------

TIER_C: list[Pattern] = [
    _p(r"\bcitric\s+acid\b", "citric acid", "C", None, "acid"),
    _p(r"\bascorbic\s+acid\b", "ascorbic acid", "C", None, "antioxidant"),
    _p(r"\btocopherols?\b", "tocopherols", "C", None, "antioxidant"),
    _p(r"\brosemary\s+extract\b", "rosemary extract", "C", None, "antioxidant"),
    _p(r"\bpectin\b", "pectin", "C", None, "gum"),
    _p(r"\bannatto\b", "annatto", "C", None, "natural_color"),
    _p(r"\blactic\s+acid\b", "lactic acid", "C", None, "acid"),

    # --- Acidulants (v0.7.1) ---
    # Malic and fumaric acid: used in confectionery, powdered drinks, baked goods.
    # Formulation markers but lower concern than Tier A/B acids like phosphates.
    _p(r"\bmalic\s+acid\b", "malic acid", "C", None, "acid"),
    _p(r"\bfumaric\s+acid\b", "fumaric acid", "C", None, "acid"),
    _p(r"\btartaric\s+acid\b", "tartaric acid", "C", None, "acid"),

    # --- Natural colors (v0.7.1) ---
    # Tracked for completeness; should not carry strong UPF signal.
    # Turmeric: spice-derived, widely used as a natural yellow colorant.
    # Beta carotene: provitamin A, used as orange/yellow color in many products.
    # --- Synthetic fortification markers (v0.7.2) ---
    # Synthetic vitamins/minerals indicate industrial enrichment (NOVA Group 2+).
    # Tracked as Tier C: they signal processing but are low nutritional concern.
    # Without these, enriched rice/cereals can score as "W" (whole food).
    _p(r"\bniacinamide\b", "niacinamide", "C", None, "fortification"),
    _p(r"\bniacin\b", "niacin", "C", None, "fortification"),
    _p(r"\bfolic\s+acid\b", "folic acid", "C", None, "fortification"),
    _p(r"\bpyridoxine\b", "pyridoxine", "C", None, "fortification"),
    _p(r"\bthiamin(?:e)?\s+(?:mono)?nitrate\b", "thiamin", "C", None, "fortification"),
    _p(r"\briboflavin\b", "riboflavin", "C", None, "fortification"),
    _p(r"\bferrous\s+(?:sulfate|fumarate|gluconate)\b", "ferrous compound", "C", None, "fortification"),
    _p(r"\bferric\s+(?:phosphate|orthophosphate)\b", "ferric compound", "C", None, "fortification"),
    _p(r"\bcyanocobalamin\b", "vitamin B12", "C", None, "fortification"),
    _p(r"\bcholecalciferol\b", "vitamin D3", "C", None, "fortification"),
    _p(r"\bsodium\s+ascorbate\b", "sodium ascorbate", "C", None, "fortification"),
    _p(r"\bcalcium\s+carbonate\b", "calcium carbonate", "C", None, "fortification"),
    _p(r"\bzinc\s+(?:oxide|gluconate|sulfate)\b", "zinc compound", "C", None, "fortification"),

    # Natural color patterns — qualifier group is REQUIRED to avoid matching
    # culinary uses like "turmeric powder" (spice) or "beet sugar" (sweetener).
    _p(r"\bturmeric\s+(?:extract|color|colour|oleoresin)\b", "turmeric color", "C", None, "natural_color"),
    _p(r"\bbeta[\s-]carotene\b", "beta carotene", "C", None, "natural_color"),
    _p(r"\bpaprika\s+(?:extract|oleoresin|color|colour)\b", "paprika extract", "C", None, "natural_color"),
    _p(r"\bbeet(?:root)?\s+(?:juice\s+)?(?:extract|powder|color|colour)\b", "beet color", "C", None, "natural_color"),
]


# ---------------------------------------------------------------------------
# CULINARY — Tracked as features, zero AFS weight
# ---------------------------------------------------------------------------

CULINARY: list[Pattern] = [
    _p(r"\bbaking\s+soda\b", "baking soda", "culinary", None, "leavener"),
    _p(r"\bsodium\s+bicarbonate\b", "baking soda", "culinary", None, "leavener"),
    _p(r"\bbaking\s+powder\b", "baking powder", "culinary", None, "leavener"),
    _p(r"\bcalcium\s+chloride\b", "calcium chloride", "culinary", None, "mineral"),
    _p(r"\bcream\s+of\s+tartar\b", "cream of tartar", "culinary", None, "acid"),
    _p(r"\bvanilla\s+extract\b", "vanilla extract", "culinary", None, "extract"),
]

ALL_PATTERNS: list[Pattern] = TIER_A + TIER_B + TIER_C + CULINARY


# ---------------------------------------------------------------------------
# MATRIX DISRUPTION — Bucket 2 and Bucket 3 patterns
# Bucket 2: refined but not extreme. Bucket 3: industrial substrates.
# v0.7.0: Bucket 3 substrates are MDS-only (no AFS double-counting).
# ---------------------------------------------------------------------------

BUCKET_2: list[Pattern] = [
    # --- Starches ---
    _p(r"\bcorn\s*starch\b", "corn starch", None, 2, "starch"),
    _p(r"\btapioca\s+starch\b", "tapioca starch", None, 2, "starch"),
    _p(r"\bpotato\s+starch\b", "potato starch", None, 2, "starch"),
    _p(r"\brice\s+starch\b", "rice starch", None, 2, "starch"),

    # --- Refined seed/vegetable oils ---
    # These are solvent-extracted or expeller-pressed industrial oils.
    # NOT included: olive oil, avocado oil, sesame oil, coconut oil
    # (minimally processed culinary staples).
    _p(r"\bcanola\s+oil\b", "canola oil", None, 2, "refined_oil"),
    _p(r"\bsoybean\s+oil\b", "soybean oil", None, 2, "refined_oil"),
    _p(r"\bvegetable\s+oil\b", "vegetable oil", None, 2, "refined_oil"),
    _p(r"\bsunflower\s+(?:seed\s+)?oil\b", "sunflower oil", None, 2, "refined_oil"),
    _p(r"\bsafflower\s+oil\b", "safflower oil", None, 2, "refined_oil"),
    _p(r"\bcorn\s+oil\b", "corn oil", None, 2, "refined_oil"),
    _p(r"\bcottonseed\s+oil\b", "cottonseed oil", None, 2, "refined_oil"),
    _p(r"\brapeseed\s+oil\b", "rapeseed oil", None, 2, "refined_oil"),

    # --- Enriched / refined flours ---
    # "Enriched" means the flour was industrially refined (stripped of bran/germ)
    # and then re-fortified. Plain "wheat flour" without "enriched" is excluded
    # (too broad — would flag artisan bread).
    _p(r"\benriched\s+(?:\w+\s+)*?flour\b", "enriched flour", None, 2, "refined_flour"),
    _p(r"\bbleached\s+(?:\w+\s+)*?flour\b", "bleached flour", None, 2, "refined_flour"),
    # Removed: rice flour — stone-ground from whole rice, not industrially refined.
    # Unlike enriched/bleached wheat flour, rice flour retains its whole-grain origin.

    # --- Fiber isolates ---
    _p(r"\boat\s+fiber\b", "oat fiber", None, 2, "fiber_isolate"),
    _p(r"\bpea\s+fiber\b", "pea fiber", None, 2, "fiber_isolate"),
    _p(r"\bbamboo\s+fiber\b", "bamboo fiber", None, 2, "fiber_isolate"),
    _p(r"\bpowdered\s+cellulose\b", "powdered cellulose", None, 2, "fiber_isolate"),
    _p(r"\binulin\b", "inulin", None, 2, "fiber_isolate"),
    _p(r"\bchicory\s+(?:root\s+)?fiber\b", "chicory fiber", None, 2, "fiber_isolate"),
    _p(r"\bsoluble\s+corn\s+fiber\b", "soluble corn fiber", None, 2, "fiber_isolate"),

    # --- Concentrates ---
    _p(r"\bjuice\s+(?:from\s+)?concentrate\b", "juice concentrate", None, 2, "concentrate"),
    _p(r"\bprotein\s+concentrate\b", "protein concentrate", None, 2, "concentrate"),

    # --- Dairy powders ---
    _p(r"\bwhey\s+powder\b", "whey powder", None, 2, "dairy_powder"),
    _p(r"\bwhey\b(?!\s+protein\s+isolate)", "whey", None, 2, "dairy_powder"),
    _p(r"\bmilk\s+powder\b", "milk powder", None, 2, "dairy_powder"),
    _p(r"\bskim\s+milk\s+powder\b", "skim milk powder", None, 2, "dairy_powder"),
    _p(r"\bnonfat\s+(?:dry\s+)?milk\b", "nonfat milk solids", None, 2, "dairy_powder"),
    _p(r"\bmilk\s+solids\b", "milk solids", None, 2, "dairy_powder"),

    # --- Other ---
    _p(r"\bdextrose\b", "dextrose", None, 2, "sweetener"),
    _p(r"\brice\s+syrup\b", "rice syrup", None, 2, "sweetener"),
    _p(r"\bbrown\s+rice\s+syrup\b", "brown rice syrup", None, 2, "sweetener"),
    _p(r"\bglycerin\b", "glycerin", None, 2, "humectant"),
    _p(r"\bpolydextrose\b", "polydextrose", None, 2, "fiber_isolate"),
    _p(r"\bcorn\s+syrup\s+solids\b", "corn syrup solids", None, 2, "sweetener"),
    _p(r"\begg\s+(?:white\s+)?powder\b", "egg powder", None, 2, "powder"),
]

# Bucket 3: industrial substrates + hydrogenated fats.
# These are scored by MDS only (matrix disruption). Prior to v0.7.0, the
# substrates were also in TIER_A, causing MDS-AFS double-counting.
BUCKET_3: list[Pattern] = [
    # --- Industrial substrates (moved from TIER_A in v0.7.0) ---
    _p(r"\bmaltodextrin\b", "maltodextrin", None, 3, "substrate"),
    _p(r"\bhigh\s+fructose\s+corn\s+syrup\b", "high fructose corn syrup", None, 3, "sweetener"),
    _p(r"\bhfcs\b", "high fructose corn syrup", None, 3, "sweetener"),
    _p(r"\bglucose[\s-]+fructose\b", "glucose-fructose", None, 3, "sweetener"),
    _p(r"\bglucose\s+syrup\b", "glucose syrup", None, 3, "sweetener"),
    # "corn syrup" catch-all.
    # (?<!fructose ) prevents matching inside "high fructose corn syrup"
    # (where "fructose" immediately precedes "corn").
    # (?!\s+solids) prevents matching "corn syrup solids" (Bucket 2).
    _p(r"(?<!fructose )\bcorn\s+syrup\b(?!\s+solids)", "corn syrup", None, 3, "sweetener"),
    _p(r"\bmodified\s+(?:corn\s*|food\s*|tapioca\s*|potato\s*|rice\s*)?starch\b",
       "modified starch", None, 3, "substrate"),
    _p(r"\b\w*\s*protein\s+isolate\b", "protein isolate", None, 3, "substrate"),
    _p(r"\bhydrolyzed\s+\w+(?:\s+\w+)?\s*protein\b", "hydrolyzed protein", None, 3, "substrate"),
    _p(r"\bhydrolysed\s+\w+(?:\s+\w+)?\s*protein\b", "hydrolyzed protein", None, 3, "substrate"),
    # --- Hydrogenated / interesterified fats ---
    # (?<!partially ) prevents the generic "hydrogenated fat" label from also
    # matching inside "partially hydrogenated", which has its own more-specific
    # label below. Both are Bucket 3, but should count as one label per ingredient.
    _p(r"(?<!partially )\bhydrogenated\b", "hydrogenated fat", None, 3, "fat"),
    _p(r"\binteresterified\b", "interesterified fat", None, 3, "fat"),
    _p(r"\bpartially\s+hydrogenated\b", "partially hydrogenated fat", None, 3, "fat"),
    # --- Fat replacers (v0.9.0) ---
    _p(r"\besterified\s+propoxylated\s+glycerol\b", "EPG", None, 3, "fat_replacer"),
    _p(r"\bepg\b", "EPG", None, 3, "fat_replacer"),
    _p(r"\bmodified\s+plant\s+fat\b", "EPG", None, 3, "fat_replacer"),
]


# ---------------------------------------------------------------------------
# HES — Pattern lists for hyperpalatability detection
# ---------------------------------------------------------------------------

CALORIC_SWEETENERS: list[Pattern] = [
    # Qualified sugar variants FIRST — order matters for _find_unique_matches
    # (which deduplicates by label), but the generic "sugar" pattern below
    # uses negative lookbehind/lookahead to avoid matching inside these.
    _p(r"\bcane\s+sugar\b", "cane sugar", None, 1, "sweetener"),
    _p(r"\bbrown\s+sugar\b", "brown sugar", None, 1, "sweetener"),
    _p(r"\bpowdered\s+sugar\b", "powdered sugar", None, 1, "sweetener"),
    _p(r"\bcoconut\s+sugar\b", "coconut sugar", None, 1, "sweetener"),
    _p(r"\binvert\s+sugar\b", "invert sugar", None, 2, "sweetener"),
    _p(r"\bbeet\s+sugar\b", "beet sugar", None, 1, "sweetener"),
    _p(r"\bdate\s+sugar\b", "date sugar", None, 1, "sweetener"),
    _p(r"\bpalm\s+sugar\b", "palm sugar", None, 1, "sweetener"),
    _p(r"\bmuscovado\s+sugar\b", "muscovado sugar", None, 1, "sweetener"),
    _p(r"\bdemerara\s+sugar\b", "demerara sugar", None, 1, "sweetener"),
    _p(r"\braw\s+sugar\b", "raw sugar", None, 1, "sweetener"),
    _p(r"\bconfectioner(?:'?s)?\s+sugar\b", "confectioners sugar", None, 1, "sweetener"),
    # Generic "sugar" — negative lookbehinds prevent matching inside qualified
    # variants like "cane sugar", "brown sugar", etc.  This avoids the HES
    # double-counting bug where a product with only "cane sugar" triggered
    # the multiple_sweeteners pattern (+4 points).
    _p(r"(?<!\bcane\s)(?<!\bbrown\s)(?<!\bpowdered\s)(?<!\bcoconut\s)(?<!\binvert\s)(?<!\bbeet\s)(?<!\bdate\s)(?<!\bpalm\s)(?<!\bmuscovado\s)(?<!\bdemerara\s)(?<!\braw\s)(?<!\bconfectioners\s)(?<!\bconfectioner.s\s)\bsugar\b(?!\s+(?:cane|beet|alcohol))", "sugar", None, 1, "sweetener"),
    _p(r"\bhoney\b", "honey", None, 1, "sweetener"),
    _p(r"\bmaple\s+syrup\b", "maple syrup", None, 1, "sweetener"),
    _p(r"\bmolasses\b", "molasses", None, 1, "sweetener"),
    _p(r"\bagave\b", "agave", None, 1, "sweetener"),
    _p(r"\bcorn\s+syrup\b", "corn syrup", None, 3, "sweetener"),
    _p(r"\bhigh\s+fructose\s+corn\s+syrup\b", "HFCS", None, 3, "sweetener"),
    _p(r"\bglucose\s+syrup\b", "glucose syrup", None, 3, "sweetener"),
    _p(r"\brice\s+syrup\b", "rice syrup", None, 2, "sweetener"),
    _p(r"\bdextrose\b", "dextrose", None, 2, "sweetener"),
    _p(r"\bmaltose\b", "maltose", None, 2, "sweetener"),
    _p(r"\bfructose\b(?!\s+corn)", "fructose", None, 2, "sweetener"),
    _p(r"\bturbinado\b", "turbinado", None, 1, "sweetener"),
    _p(r"\bdate\s+syrup\b", "date syrup", None, 1, "sweetener"),
    # Allulose: rare sugar analog (v0.9.0). Listed here so HES detects it as a
    # sweetener for pattern triggers (multiple_sweeteners, flavor_plus_sweetener).
    _p(r"\ballulose\b", "allulose", None, 2, "sweetener"),
]

NON_NUTRITIVE_SWEETENERS: list[Pattern] = [
    _p(r"\baspartame\b", "aspartame", None, 4, "nns"),
    _p(r"\bsucralose\b", "sucralose", None, 4, "nns"),
    _p(r"\bacesulfame\b", "acesulfame K", None, 4, "nns"),
    _p(r"\bsaccharin\b", "saccharin", None, 4, "nns"),
    _p(r"\bneotame\b", "neotame", None, 4, "nns"),
    _p(r"\badvantame\b", "advantame", None, 4, "nns"),
    _p(r"\bstevia\b", "stevia", None, 4, "nns"),
    _p(r"\bsteviol\b", "steviol glycosides", None, 4, "nns"),
    _p(r"\bmonk\s+fruit\b", "monk fruit", None, 4, "nns"),
    _p(r"\berythritol\b", "erythritol", None, 4, "nns"),
    # allulose removed in v0.9.0 — reclassified to TIER_B (rare_sugar) and
    # CALORIC_SWEETENERS. It's a monosaccharide, not a non-nutritive sweetener.
]

FLAVOR_INGREDIENTS: list[Pattern] = [
    _p(r"\bnatural\s+flavou?r(?:s|ing)?\b", "natural flavor", None, 4, "flavor"),
    _p(r"\bartificial\s+flavou?r(?:s|ing)?\b", "artificial flavor", None, 4, "flavor"),
    _p(r"\bmalt\s+flavou?r(?:s|ing)?\b", "malt flavor", None, 4, "flavor"),
    _p(r"\bsmoke\s+flavou?r\b", "smoke flavor", None, 4, "flavor"),
    _p(r"\bvanillin\b", "vanillin", None, 4, "flavor"),
]

FLAVOR_ENHANCERS: list[Pattern] = [
    _p(r"\byeast\s+extract\b", "yeast extract", None, 4, "flavor_enhancer"),
    _p(r"\bmonosodium\s+glutamate\b", "MSG", None, 4, "flavor_enhancer"),
    _p(r"\bmsg\b", "MSG", None, 4, "flavor_enhancer"),
    _p(r"\bautolyzed\s+yeast\b", "autolyzed yeast", None, 4, "flavor_enhancer"),
    _p(r"\bdisodium\s+inosinate\b", "disodium inosinate", None, 4, "flavor_enhancer"),
    _p(r"\bdisodium\s+guanylate\b", "disodium guanylate", None, 4, "flavor_enhancer"),
]

COATING_FATS: list[Pattern] = [
    _p(r"\bpalm\s+oil\b", "palm oil", None, 1, "fat"),
    _p(r"\bpalm\s+kernel\s+oil\b", "palm kernel oil", None, 1, "fat"),
    _p(r"\bhydrogenated\b", "hydrogenated fat", None, 3, "fat"),
    _p(r"\binteresterified\b", "interesterified fat", None, 3, "fat"),
    _p(r"\bshortening\b", "shortening", None, 2, "fat"),
    # Removed: cocoa butter and coconut oil — culinary fats, not industrial coatings.
    # Their presence alongside sugar (chocolate bars, granola) is not hyperpalatability
    # engineering in the same way as palm kernel oil or shortening coatings.
]


# ---------------------------------------------------------------------------
# WHOLE_FOOD_KEYWORDS and PACKAGED_KEYWORDS were removed in v0.5.0.
# Product type inference is now taxonomy-driven (see scorer.py).


# ---------------------------------------------------------------------------
# SCAN FUNCTION
# ---------------------------------------------------------------------------

def _find_unique_matches(patterns: list[Pattern], text: str) -> dict[str, Pattern]:
    """Find all unique pattern matches in text. Returns {label: Pattern}."""
    matches = {}
    for pat in patterns:
        if pat.regex.search(text) and pat.label not in matches:
            matches[pat.label] = pat
    return matches


def _count_all_hits(patterns: list[Pattern], text: str) -> dict[str, int]:
    """Count total regex hits per label (including duplicates)."""
    hits: dict[str, int] = {}
    for pat in patterns:
        count = len(pat.regex.findall(text))
        if count > 0:
            hits[pat.label] = hits.get(pat.label, 0) + count
    return hits


def scan_ingredients(normalized_text: str) -> dict:
    """Scan normalized ingredient text for all known patterns.

    Args:
        normalized_text: Lowercased, cleaned ingredient text from normalize.py.

    Returns:
        {
            "tier_a": {label: Pattern, ...},      # unique matches
            "tier_b": {label: Pattern, ...},
            "tier_c": {label: Pattern, ...},
            "culinary": {label: Pattern, ...},
            "bucket_2": {label: Pattern, ...},
            "bucket_3": {label: Pattern, ...},    # includes TIER_A bucket-3 + extras
            "hits_a": {label: count, ...},        # raw hit counts
            "hits_b": {label: count, ...},
            "hits_c": {label: count, ...},
            "caloric_sweeteners": {label: Pattern},
            "nns": {label: Pattern},              # non-nutritive sweeteners
            "flavors": {label: Pattern},
            "flavor_enhancers": {label: Pattern},
            "coating_fats": {label: Pattern},
        }
    """
    if not normalized_text:
        empty = {}
        return {
            "tier_a": empty, "tier_b": empty, "tier_c": empty, "culinary": empty,
            "bucket_2": empty, "bucket_3": empty,
            "hits_a": empty, "hits_b": empty, "hits_c": empty,
            "caloric_sweeteners": empty, "nns": empty,
            "flavors": empty, "flavor_enhancers": empty, "coating_fats": empty,
        }

    # Additive tier matches (unique labels)
    tier_a = _find_unique_matches(TIER_A, normalized_text)
    tier_b = _find_unique_matches(TIER_B, normalized_text)
    tier_c = _find_unique_matches(TIER_C, normalized_text)
    culinary = _find_unique_matches(CULINARY, normalized_text)

    # Raw hit counts for debugging
    hits_a = _count_all_hits(TIER_A, normalized_text)
    hits_b = _count_all_hits(TIER_B, normalized_text)
    hits_c = _count_all_hits(TIER_C, normalized_text)

    # Bucket matches for MDS
    bucket_2 = _find_unique_matches(BUCKET_2, normalized_text)
    bucket_3 = _find_unique_matches(BUCKET_3, normalized_text)

    # HES pattern lists
    caloric_sweeteners = _find_unique_matches(CALORIC_SWEETENERS, normalized_text)
    nns = _find_unique_matches(NON_NUTRITIVE_SWEETENERS, normalized_text)
    flavors = _find_unique_matches(FLAVOR_INGREDIENTS, normalized_text)
    flavor_enhancers = _find_unique_matches(FLAVOR_ENHANCERS, normalized_text)
    coating_fats = _find_unique_matches(COATING_FATS, normalized_text)

    return {
        "tier_a": tier_a,
        "tier_b": tier_b,
        "tier_c": tier_c,
        "culinary": culinary,
        "bucket_2": bucket_2,
        "bucket_3": bucket_3,
        "hits_a": hits_a,
        "hits_b": hits_b,
        "hits_c": hits_c,
        "caloric_sweeteners": caloric_sweeteners,
        "nns": nns,
        "flavors": flavors,
        "flavor_enhancers": flavor_enhancers,
        "coating_fats": coating_fats,
    }
