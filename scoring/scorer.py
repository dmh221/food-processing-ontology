"""Food Integrity Scoring orchestrator.

Loads product data from all stores into a single pandas DataFrame,
runs the 4-axis scoring pipeline, assigns processing and metabolic classes,
and writes output to parquet + CSV.
"""

import json
import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from scoring.normalize import normalize_ingredients, parse_serving_grams, annotate_nesting_depths
from scoring.ontology import scan_ingredients
from scoring.product_taxonomy import classify_taxonomy
from scoring.rules_mds import score_mds
from scoring.rules_afs import score_afs
from scoring.rules_hes import score_hes
from scoring.rules_mls import score_mls

SCORE_VERSION = "v0.9.1"


# ---------------------------------------------------------------------------
# Taxonomy-based product type + processing floor mappings (v0.5.0)
# ---------------------------------------------------------------------------

# Taxonomy label -> product_type.
# Checked by exact subfamily match, then family-level default.
_SUBFAMILY_PRODUCT_TYPE: dict[str, str] = {
    "drinks.sodas_mixers": "beverage",
    "drinks.kombucha": "beverage",
    "drinks.water_seltzers": "beverage",
    "drinks.juice": "beverage",
    "drinks.functional": "beverage",
    "drinks.coffee_tea": "mixed",  # dry goods vs. RTD — resolved by name regex
    "pantry.oil_vinegar_spices": "pantry_staple",
    "non_food.pet": "non_food",
    "non_food.floral": "non_food",
    "non_food.household": "non_food",
}

_FAMILY_PRODUCT_TYPE: dict[str, str] = {
    "drinks": "beverage",    # fallback for unmapped drinks subfamilies
    "non_food": "non_food",
}
# Everything not in either dict defaults to "food".

# Taxonomy family -> minimum processing class.
# "W" = can be whole food; "C" = at least clean-processed; None = let score decide.
_FAMILY_PROCESSING_FLOOR: dict[str, str | None] = {
    "produce": "W",
    "meat": "W",
    "seafood": "W",
    "dairy_eggs": None,
    "plant_protein": None,
    "baked_goods": "C",
    "desserts": "C",
    "drinks": None,
    "pantry": None,
    "composite": "C",
    "non_food": None,
}

# Subfamily overrides for families with floor=None.
_SUBFAMILY_PROCESSING_FLOOR: dict[str, str | None] = {
    # dairy_eggs
    "dairy_eggs.eggs_butter": "W",
    "dairy_eggs.milk_cream": "W",
    "dairy_eggs.cheese": "C",
    "dairy_eggs.cultured_dairy": "C",
    "dairy_eggs.plant_based": "C",
    # plant_protein
    "plant_protein.tofu": "C",
    "plant_protein.tempeh": "C",
    "plant_protein.seitan": "C",
    "plant_protein.meat_substitute": "C",
    # drinks
    "drinks.water_seltzers": "W",
    "drinks.juice": "C",
    "drinks.sodas_mixers": "C",
    "drinks.kombucha": "C",
    "drinks.functional": "C",
    "drinks.coffee_tea": None,  # ground coffee=Wp, RTD=C+; resolved by name
    # pantry
    "pantry.oil_vinegar_spices": "W",
    "pantry.grains_beans": "W",
    "pantry.dried_fruits_nuts": "W",
    "pantry.noodles": "C",
    "pantry.chips_crackers": "C",
    "pantry.granola_cereals": "C",
    "pantry.bars": "C",
    "pantry.jerky": "C",
    "pantry.pickled_fermented": "C",
    "pantry.baking_ingredients": None,  # flour=Wp, baking mix=C+
    "pantry.condiments_dressings": "C",
    "pantry.honey_syrups": "W",
    "pantry.jams_nut_butters": "C",
    "pantry.canned_goods": "C",
    "pantry.stocks": "C",
}

# Families/subfamilies where W/Wp is structurally possible.
_CAN_BE_WHOLE_FAMILIES: set[str] = {"produce", "meat", "seafood"}

_CAN_BE_WHOLE_SUBFAMILIES: set[str] = {
    "dairy_eggs.eggs_butter",
    "dairy_eggs.milk_cream",
    "drinks.water_seltzers",
    "pantry.oil_vinegar_spices",
    "pantry.grains_beans",
    "pantry.dried_fruits_nuts",
    "pantry.honey_syrups",
    "pantry.baking_ingredients",  # flour, cocoa powder
}

# Taxonomy families/subfamilies where missing ingredients are suspect —
# these products structurally require multiple ingredients.
_STRUCTURALLY_MULTI_INGREDIENT: set[str] = {
    # Families
    "baked_goods", "desserts", "composite",
    # Subfamilies
    "pantry.chips_crackers", "pantry.granola_cereals", "pantry.bars",
    "pantry.condiments_dressings", "pantry.jams_nut_butters",
    "pantry.canned_goods", "pantry.stocks", "pantry.pickled_fermented",
    "plant_protein.meat_substitute",
    "dairy_eggs.plant_based", "dairy_eggs.cultured_dairy", "dairy_eggs.cheese",
}

# Name patterns for drinks.coffee_tea split (dry goods vs. RTD beverages).
# Retained from v0.4 — only applied for the coffee_tea subfamily.
_PANTRY_STAPLE_NAME_RE = re.compile(
    r"\b(?:"
    r"ground\s+coffee|whole\s+bean|coffee\s+bean"
    r"|roast(?:ed)?\b.*\bcoffee"
    r"|k-cup|k\s+cup|coffee\s+pod|coffee\s+capsule"
    r"|instant\s+coffee|nescafe"
    r"|tea\s+bag|tea\s+sachet|loose[\s-]leaf"
    r"|pyramid\s+sachet"
    r"|herbal\s+tea|green\s+tea|black\s+tea|oolong\s+tea"
    r"|white\s+tea|chai\s+tea"
    r"|matcha\s+powder|ceremonial\s+matcha"
    r"|rooibos|chamomile|peppermint\s+tea"
    r"|earl\s+grey|english\s+breakfast"
    r"|ground\s+(?:cumin|cinnamon|turmeric|paprika|pepper|ginger|nutmeg|cardamom)"
    r"|chili\s+powder|garlic\s+powder|onion\s+powder|curry\s+powder"
    r"|seasoning\s+blend|spice\s+blend"
    r"|sea\s+salt|black\s+pepper(?:corn)?|white\s+pepper"
    r")\b",
    re.IGNORECASE,
)

_TEA_BAG_BRANDS_RE = re.compile(
    r"\b(?:bigelow|celestial\s+seasonings|traditional\s+medicinals"
    r"|tazo|twinings|harney|rishi|yogi|clipper|vahdam"
    r"|republic\s+of\s+tea|steven\s+smith|paromi|ito\s+en"
    r"|lipton\s+(?:black\s+tea|green\s+tea|decaf))"
    r"\b",
    re.IGNORECASE,
)

_BEVERAGE_NAME_RE = re.compile(
    r"\b(?:"
    r"cold\s+brew|iced\s+(?:tea|coffee)|ready\s+to\s+drink"
    r"|latte|frappuccino|cappuccino"
    r"|juice|lemonade|limeade|smoothie"
    r"|soda|seltzer|sparkling\s+water|tonic\s+water|club\s+soda"
    r"|kombucha|energy\s+drink|protein\s+shake"
    r"|coconut\s+water"
    r"|(?:oat|almond|soy|coconut)\s*milk"
    r")\b",
    re.IGNORECASE,
)


def classify_product_type(row) -> str:
    """Classify a product as 'food', 'beverage', 'pantry_staple', or 'non_food'.

    v0.5: Uses taxonomy labels instead of store-specific subcategory maps.
    Falls back to name heuristics only for drinks.coffee_tea subfamily.
    """
    taxonomy_label = str(row.get("taxonomy_label") or "")
    taxonomy_family = str(row.get("taxonomy_family") or "")
    name = str(row.get("name") or "")

    # Step 1: exact subfamily match
    mapped = _SUBFAMILY_PRODUCT_TYPE.get(taxonomy_label)
    if mapped and mapped != "mixed":
        return mapped

    # Step 2: drinks.coffee_tea split — name heuristics for this one subfamily
    if mapped == "mixed":
        if _PANTRY_STAPLE_NAME_RE.search(name):
            return "pantry_staple"
        if _TEA_BAG_BRANDS_RE.search(name):
            return "pantry_staple"
        if _BEVERAGE_NAME_RE.search(name):
            return "beverage"
        return "pantry_staple"  # majority of coffee_tea products are dry goods

    # Step 3: family-level fallback
    family_mapped = _FAMILY_PRODUCT_TYPE.get(taxonomy_family)
    if family_mapped:
        return family_mapped

    return "food"


# Patterns that indicate the "ingredients" field is actually a disclaimer,
# not real ingredient data. Seen in ~79 Trader Joe's products.
_DISCLAIMER_RE = re.compile(
    r"(?:vary\s+by\s+region|review\s+packaging|packaging\s+(?:will|may)\s+vary)",
    re.IGNORECASE,
)


def _is_disclaimer(text: str) -> bool:
    """Return True if text looks like a store disclaimer rather than ingredients."""
    return bool(_DISCLAIMER_RE.search(text))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_store_data(store_files: dict[str, Path]) -> pd.DataFrame:
    """Load all store JSON files into a single DataFrame."""
    frames = []
    for store_name, path in store_files.items():
        if not path.exists():
            print(f"  Skipping {store_name}: {path} not found")
            continue
        with open(path) as f:
            data = json.load(f)
        df = pd.DataFrame(data)
        df["store"] = store_name
        frames.append(df)
        print(f"  Loaded {store_name}: {len(df):,} products")

    if not frames:
        raise ValueError("No store data found!")

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# No-ingredient classification
# ---------------------------------------------------------------------------

def _is_likely_whole_food(row) -> bool:
    """Check if a product without ingredients is likely a whole food.

    v0.5: Uses taxonomy family/subfamily instead of keyword lists.
    """
    taxonomy_family = str(row.get("taxonomy_family") or "")
    taxonomy_label = str(row.get("taxonomy_label") or "")

    if taxonomy_family in _CAN_BE_WHOLE_FAMILIES:
        return True
    if taxonomy_label in _CAN_BE_WHOLE_SUBFAMILIES:
        return True
    return False


def _is_likely_packaged(row) -> bool:
    """Check if a no-ingredient product is suspect (should have ingredients).

    v0.5: Uses taxonomy to determine if the product's category structurally
    requires multiple ingredients.
    """
    taxonomy_family = str(row.get("taxonomy_family") or "")
    taxonomy_label = str(row.get("taxonomy_label") or "")

    if taxonomy_family in _STRUCTURALLY_MULTI_INGREDIENT:
        return True
    if taxonomy_label in _STRUCTURALLY_MULTI_INGREDIENT:
        return True
    return False


# ---------------------------------------------------------------------------
# Single-product scoring
# ---------------------------------------------------------------------------

def _score_one_product(row: pd.Series) -> dict:
    """Score a single product across all 4 axes.

    Returns a flat dict of scoring columns to add to the DataFrame.
    """
    ingredients_raw = row.get("ingredients")
    if pd.isna(ingredients_raw):
        ingredients_raw = None
    nutrition = row.get("nutrition")
    store = row.get("store", "")
    name = row.get("name", "")

    # --- Classify product type (before scoring) ---
    product_type = classify_product_type(row)

    result = {
        "score_version": SCORE_VERSION,
        "product_type": product_type,
        "ingredients_missing": False,
        "ingredients_missing_suspect": False,
    }

    # --- Detect disclaimer text masquerading as ingredients ---
    if ingredients_raw and _is_disclaimer(str(ingredients_raw)):
        ingredients_raw = None  # treat as missing

    # --- Handle no-ingredient products ---
    if not ingredients_raw or not str(ingredients_raw).strip():
        result["ingredients_missing"] = True
        result["ingredients_norm"] = ""
        result["item_count"] = 0

        if _is_likely_whole_food(row):
            # Whole food — automatic W or Wp
            mls_result = score_mls(nutrition if isinstance(nutrition, dict) else None)
            result.update(_empty_processing_scores())
            result.update(_prefix_mls(mls_result))
            result["processing_score"] = 0
            result["processing_class"] = "Wp" if _has_prep_keyword(name) else "W"
            result["metabolic_class"] = _assign_metabolic_class(mls_result["score"])
            result["composite"] = mls_result["score"]
            return result
        else:
            if _is_likely_packaged(row):
                result["ingredients_missing_suspect"] = True
            # Unknown — can't score processing
            mls_result = score_mls(nutrition if isinstance(nutrition, dict) else None)
            result.update(_empty_processing_scores())
            result.update(_prefix_mls(mls_result))
            result["processing_score"] = float("nan")
            result["processing_class"] = "unknown"
            result["metabolic_class"] = _assign_metabolic_class(mls_result["score"])
            result["composite"] = float("nan")
            return result

    # --- Normalize ingredients ---
    parsed = normalize_ingredients(str(ingredients_raw), store)
    result["ingredients_norm"] = parsed["normalized"]
    result["item_count"] = parsed["item_count"]

    # --- Post-normalization empty check ---
    # Allergen-only text (e.g. "ALLERGENS: Contains: wheat and sesame.") is
    # non-empty raw input that normalizes to "". Treat as missing ingredients.
    if not parsed["normalized"].strip():
        result["ingredients_missing"] = True
        result["item_count"] = 0
        if _is_likely_packaged(row):
            result["ingredients_missing_suspect"] = True
        if _is_likely_whole_food(row):
            mls_result = score_mls(nutrition if isinstance(nutrition, dict) else None)
            result.update(_empty_processing_scores())
            result.update(_prefix_mls(mls_result))
            result["processing_score"] = 0
            result["processing_class"] = "Wp" if _has_prep_keyword(name) else "W"
            result["metabolic_class"] = _assign_metabolic_class(mls_result["score"])
            result["composite"] = mls_result["score"]
            return result
        else:
            mls_result = score_mls(nutrition if isinstance(nutrition, dict) else None)
            result.update(_empty_processing_scores())
            result.update(_prefix_mls(mls_result))
            result["processing_score"] = float("nan")
            result["processing_class"] = "unknown"
            result["metabolic_class"] = _assign_metabolic_class(mls_result["score"])
            result["composite"] = float("nan")
            return result

    components = parsed.get("components", [parsed["normalized"]])

    # --- Extract serving grams ---
    serving_size = None
    if isinstance(nutrition, dict):
        serving_size = nutrition.get("serving_size") or nutrition.get("serving_size_household")
    serving_g = parse_serving_grams(str(serving_size) if serving_size else None)
    result["serving_g"] = serving_g

    # --- Scan ingredients ---
    scan = scan_ingredients(parsed["normalized"])

    # --- Compute nesting depths for all matched patterns ---
    # Merge all pattern dicts so we can get depths for every match
    all_matches = {}
    for key in ("tier_a", "tier_b", "tier_c", "bucket_2", "bucket_3"):
        all_matches.update(scan.get(key, {}))
    nesting = annotate_nesting_depths(parsed["normalized"], all_matches)

    # --- Feature columns ---
    result["has_isolate"] = "protein isolate" in scan["bucket_3"]
    result["has_hfcs"] = "high fructose corn syrup" in scan["bucket_3"]
    result["has_modified_starch"] = "modified starch" in scan["bucket_3"]
    result["has_natural_flavor"] = "natural flavor" in scan["tier_a"]
    result["has_artificial_dye"] = any(
        scan["tier_a"].get(label) and scan["tier_a"][label].category == "dye"
        for label in scan["tier_a"]
    )
    result["has_hydrogenated_fat"] = any(
        label in scan["bucket_3"]
        for label in ("hydrogenated fat", "partially hydrogenated fat", "interesterified fat")
    )
    result["has_nns"] = len(scan["nns"]) > 0
    result["count_unique_tier_a"] = len(scan["tier_a"])
    result["count_unique_tier_b"] = len(scan["tier_b"])
    result["count_unique_tier_c"] = len(scan["tier_c"])
    result["hits_tier_a"] = sum(scan["hits_a"].values())
    result["hits_tier_b"] = sum(scan["hits_b"].values())
    result["hits_tier_c"] = sum(scan["hits_c"].values())
    result["count_sweetener_types"] = len(scan["caloric_sweeteners"])
    result["top_level_tier_a_count"] = sum(
        1 for label in scan["tier_a"] if nesting.get(label, 0) == 0
    )

    # --- Score each axis (with v0.2 nesting + component awareness) ---
    mds_result = score_mds(scan, nesting_depths=nesting)
    afs_result = score_afs(scan, nesting_depths=nesting)
    hes_result = score_hes(scan, components=components)
    mls_result = score_mls(
        nutrition if isinstance(nutrition, dict) else None,
        serving_g,
    )

    # Store scores
    result["mds"] = mds_result["score"]
    result["mds_bucket_2"] = mds_result["bucket_2_items"]
    result["mds_bucket_3"] = mds_result["bucket_3_items"]

    result["afs"] = afs_result["score"]
    result["afs_severity"] = afs_result["severity"]
    result["afs_density"] = afs_result["density"]
    result["afs_tier_a"] = afs_result["tier_a"]
    result["afs_tier_b"] = afs_result["tier_b"]
    result["afs_tier_c"] = afs_result["tier_c"]

    result["hes"] = hes_result["score"]
    result["hes_patterns"] = hes_result["patterns_detected"]

    result.update(_prefix_mls(mls_result))

    # --- Composite ---
    processing_score = mds_result["score"] + afs_result["score"] + hes_result["score"]
    result["processing_score"] = processing_score

    # Subtract fortification vitamins from item_count for processing class
    # assignment. Fortification (niacin, riboflavin, folic acid, etc.) should
    # not inflate ingredient complexity — these are nutritionally beneficial.
    fortification_count = sum(
        1 for label in scan["tier_c"]
        if scan["tier_c"][label].category == "fortification"
    )
    effective_item_count = max(1, parsed["item_count"] - fortification_count)
    result["item_count"] = effective_item_count

    result["processing_class"] = _assign_processing_class(
        processing_score, effective_item_count, name,
        taxonomy_family=row.get("taxonomy_family", ""),
        taxonomy_label=row.get("taxonomy_label", ""),
    )
    result["metabolic_class"] = _assign_metabolic_class(mls_result["score"])
    result["composite"] = processing_score + mls_result["score"]

    return result


def _empty_processing_scores() -> dict:
    """Return zero-valued processing score columns (for whole foods / unknown)."""
    return {
        "mds": 0, "mds_bucket_2": [], "mds_bucket_3": [],
        "afs": 0, "afs_severity": 0, "afs_density": 0,
        "afs_tier_a": [], "afs_tier_b": [], "afs_tier_c": [],
        "hes": 0, "hes_patterns": [],
        "has_isolate": False, "has_hfcs": False, "has_modified_starch": False,
        "has_natural_flavor": False, "has_artificial_dye": False,
        "has_hydrogenated_fat": False, "has_nns": False,
        "count_unique_tier_a": 0, "count_unique_tier_b": 0, "count_unique_tier_c": 0,
        "top_level_tier_a_count": 0,
        "hits_tier_a": 0, "hits_tier_b": 0, "hits_tier_c": 0,
        "count_sweetener_types": 0,
        "serving_g": None,
    }


def _prefix_mls(mls_result: dict) -> dict:
    """Flatten MLS result into DataFrame-friendly columns."""
    return {
        "mls": mls_result["score"],
        "mls_has_nutrition": mls_result["has_nutrition"],
        "mls_basis": mls_result["mls_basis"],
        "mls_serving_g_source": mls_result["serving_g_source"],
        "mls_tiny_serving": mls_result["tiny_serving"],
        "mls_flags": mls_result["flags"],
        "mls_offsets": mls_result["offsets"],
    }


# ---------------------------------------------------------------------------
# Class assignment
# ---------------------------------------------------------------------------

# Keywords in product names that indicate mechanical preparation (peeling,
# cutting, grinding, drying, roasting, etc.). Products matching these are
# single-ingredient but have been physically transformed from their whole state.
#
# Intentionally excluded:
#   "sticks"  — matches pretzel sticks, chicken sticks, butter sticks
#   "cut "    — matches steel cut oats, knife cut noodles
_PREP_KEYWORDS = [
    "peeled", "chopped", "sliced", "diced", "minced", "shredded",
    "cubed", "spiralized", "riced ", "mashed", "shaved", "grated",
    "fresh cut", "pre-cut", "precut", "trimmed",
    "chunks", "spears", "florets", "strips", "pieces",
    "crumbled", "julienne", "matchstick",
    # Dried/dehydrated fruit
    "dried", "dehydrated", "freeze dried", "freeze-dried", "sun dried",
    "sun-dried", "sundried",
]

# More specific patterns that need both a keyword AND a food context
_PREP_PATTERNS = [
    # "ground" for meat, coffee, spices
    re.compile(r"\bground\b", re.IGNORECASE),
    # "cut" only when preceded by a cut style, not "steel cut" or "knife cut"
    re.compile(r"\b(?:fresh|pre)[- ]?cut\b", re.IGNORECASE),
]


def _has_prep_keyword(name: str) -> bool:
    """Check if a product name indicates physical preparation."""
    name_lower = name.lower() if name else ""
    if any(kw in name_lower for kw in _PREP_KEYWORDS):
        return True
    return any(pat.search(name_lower) for pat in _PREP_PATTERNS)


# Products that are never W/Wp even with a single ingredient and zero
# processing score. These involve significant structural transformation
# (juicing, puffing/popping) that puts them in C at minimum.
_NOT_WHOLE_RE = re.compile(
    r"\bjuice\b|\brice\s*cake|\bpopcorn\b",
    re.IGNORECASE,
)


def _assign_processing_class(
    processing_score: int,
    item_count: int = 0,
    name: str = "",
    taxonomy_family: str = "",
    taxonomy_label: str = "",
) -> str:
    """Assign processing tier based on MDS+AFS+HES processing score.

    v0.6: 10-tier system for finer granularity.
    Uses taxonomy-based processing floors. Each family/subfamily
    defines a minimum processing class. The score can only raise the class
    above the floor, never lower it.
    Max theoretical: MDS(30) + AFS(80) + HES(20) = 130.

    Categories:
    - W:   whole food — single ingredient, zero processing markers
    - Wp:  whole prepped — single ingredient, physically transformed
    - C0:  clean, zero concerns — multi-ingredient, score 0
    - C1:  clean, minimal markers — score 1-5
    - P1a: light processing — score 6-15
    - P1b: moderate-light processing — score 16-25
    - P2a: moderate processing — score 26-38
    - P2b: moderate-heavy processing — score 39-50
    - P3:  heavy industrial formulation — score 51-75
    - P4:  ultra-formulated — score 76+
    """
    # Determine processing floor from taxonomy (subfamily overrides family)
    floor = _SUBFAMILY_PROCESSING_FLOOR.get(taxonomy_label)
    if floor is None:
        floor = _FAMILY_PROCESSING_FLOOR.get(taxonomy_family)

    if processing_score <= 5:
        if processing_score == 0 and item_count <= 1:
            # Taxonomy floor: if C, this product can never be W/Wp
            if floor == "C":
                return "C0"

            # Can this product be W/Wp?
            can_be_whole = (
                taxonomy_family in _CAN_BE_WHOLE_FAMILIES
                or taxonomy_label in _CAN_BE_WHOLE_SUBFAMILIES
            )
            if not can_be_whole:
                return "C0"

            # Juice, rice cakes, popcorn: structural transformation -> C minimum
            if _NOT_WHOLE_RE.search(name or ""):
                return "C0"
            if _has_prep_keyword(name):
                return "Wp"
            return "W"
        if processing_score == 0:
            return "C0"
        return "C1"
    elif processing_score <= 15:
        return "P1a"
    elif processing_score <= 25:
        return "P1b"
    elif processing_score <= 38:
        return "P2a"
    elif processing_score <= 50:
        return "P2b"
    elif processing_score <= 75:
        return "P3"
    else:
        return "P4"


def _assign_metabolic_class(mls_score: int, has_nutrition: bool = True) -> str:
    """Assign metabolic tier based on MLS.

    v0.6: 6-tier system for finer granularity.
    - N0:  MLS 0 (no metabolic load detected)
    - N0+: MLS 1-3 (minimal)
    - N1a: MLS 4-6 (low)
    - N1b: MLS 7-8 (low-moderate)
    - N2:  MLS 9-14 (moderate)
    - N3:  MLS 15+ (high)
    """
    if mls_score == 0:
        return "N0"
    elif mls_score <= 3:
        return "N0+"
    elif mls_score <= 6:
        return "N1a"
    elif mls_score <= 8:
        return "N1b"
    elif mls_score <= 14:
        return "N2"
    else:
        return "N3"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def score_all(store_files: dict[str, Path], use_llm: bool = True) -> pd.DataFrame:
    """Score all products from all stores.

    Args:
        store_files: {store_name: Path to JSON file}
        use_llm: Whether to use Claude Haiku for taxonomy classification.

    Returns:
        DataFrame with original product data + taxonomy + all scoring columns.
    """
    print("Loading product data...")
    df = load_store_data(store_files)
    print(f"Total products: {len(df):,}\n")

    # Taxonomy classification (runs before ingredient scoring)
    df = classify_taxonomy(df, use_llm=use_llm)

    print("\nScoring products...")
    tqdm.pandas(desc="Scoring")
    score_rows = df.progress_apply(_score_one_product, axis=1)

    # Convert list of dicts to DataFrame columns
    score_df = pd.DataFrame(score_rows.tolist(), index=df.index)

    # Merge with original data (taxonomy columns already on df)
    result = pd.concat([df, score_df], axis=1)

    return result


def print_summary(df: pd.DataFrame) -> None:
    """Print a summary table of scoring results."""
    # Exclude unknown processing class from stats
    scored = df[df["processing_class"] != "unknown"].copy()

    print("\n" + "=" * 75)
    print(f"  FOOD INTEGRITY SCORING RESULTS ({SCORE_VERSION})")
    print("=" * 75)

    # Per-store summary
    classes = ["W", "Wp", "C0", "C1", "P1a", "P1b", "P2a", "P2b", "P3", "P4"]
    header = (
        f"{'Store':<16} {'Tot':>6} {'W':>5} {'Wp':>4} {'C0':>5} {'C1':>5} "
        f"{'P1a':>5} {'P1b':>5} {'P2a':>5} {'P2b':>5} {'P3':>5} {'P4':>4} "
        f"{'Avg':>5} {'Unk':>5}"
    )
    print(header)
    print("-" * 105)

    for store in sorted(df["store"].unique()):
        store_df = df[df["store"] == store]
        store_scored = scored[scored["store"] == store]
        total = len(store_df)
        unknown = len(store_df[store_df["processing_class"] == "unknown"])

        counts = {}
        for pc in classes:
            counts[pc] = len(store_scored[store_scored["processing_class"] == pc])

        avg = store_scored["composite"].mean() if len(store_scored) > 0 else 0

        print(
            f"{store:<16} {total:>6,} {counts['W']:>5} {counts['Wp']:>4} "
            f"{counts['C0']:>5} {counts['C1']:>5} "
            f"{counts['P1a']:>5} {counts['P1b']:>5} {counts['P2a']:>5} "
            f"{counts['P2b']:>5} {counts['P3']:>5} {counts['P4']:>4} "
            f"{avg:>5.1f} {unknown:>5}"
        )

    # Totals
    total = len(df)
    unknown = len(df[df["processing_class"] == "unknown"])
    print("-" * 105)
    counts = {}
    for pc in classes:
        counts[pc] = len(scored[scored["processing_class"] == pc])
    avg = scored["composite"].mean() if len(scored) > 0 else 0
    print(
        f"{'TOTAL':<16} {total:>6,} {counts['W']:>5} {counts['Wp']:>4} "
        f"{counts['C0']:>5} {counts['C1']:>5} "
        f"{counts['P1a']:>5} {counts['P1b']:>5} {counts['P2a']:>5} "
        f"{counts['P2b']:>5} {counts['P3']:>5} {counts['P4']:>4} "
        f"{avg:>5.1f} {unknown:>5}"
    )

    # Top 10 most processed
    print(f"\nTop 10 most processed (highest composite):")
    top = scored.nlargest(10, "composite")[["store", "name", "composite", "processing_class", "mds", "afs", "hes", "mls"]]
    for _, row in top.iterrows():
        print(
            f"  [{row['processing_class']}/{row.get('metabolic_class', '?')}] "
            f"{row['composite']:>3.0f} = MDS:{row['mds']:>2} AFS:{row['afs']:>2} "
            f"HES:{row['hes']:>2} MLS:{row['mls']:>2}  "
            f"{row['store']}: {row['name'][:50]}"
        )

    # Top 10 cleanest (with ingredients) — sampled across stores to avoid
    # tie-breaking bias (thousands of products score 0)
    print(f"\nTop 10 cleanest (lowest composite, with ingredients — sampled across stores):")
    has_ing = scored[~scored["ingredients_missing"]]
    min_composite = has_ing["composite"].min()
    tied_at_min = has_ing[has_ing["composite"] == min_composite]
    # Sample up to 10, stratified by store so we see variety
    if len(tied_at_min) > 10:
        samples = []
        for _, group in tied_at_min.groupby("store"):
            samples.append(group.sample(min(3, len(group)), random_state=42))
        bottom = pd.concat(samples).head(10)
    else:
        bottom = has_ing.nsmallest(10, "composite")
    for _, row in bottom.iterrows():
        print(
            f"  [{row['processing_class']}] "
            f"{row['composite']:>3.0f} = MDS:{row['mds']:>2} AFS:{row['afs']:>2} "
            f"HES:{row['hes']:>2} MLS:{row['mls']:>2}  "
            f"{row['store']}: {row['name'][:50]}"
        )

    # Quick feature stats
    print(f"\n--- Feature highlights ---")
    print(f"  Products with artificial dyes: {scored['has_artificial_dye'].sum():,}")
    print(f"  Products with HFCS: {scored['has_hfcs'].sum():,}")
    print(f"  Products with protein isolates: {scored['has_isolate'].sum():,}")
    print(f"  Products with 'natural flavor': {scored['has_natural_flavor'].sum():,}")
    print(f"  Products with non-nutritive sweeteners: {scored['has_nns'].sum():,}")
    print(f"  Ingredients missing (suspect): {df['ingredients_missing_suspect'].sum():,}")

    # Product type breakdown
    if "product_type" in df.columns:
        print(f"\n--- Product type breakdown ---")
        pt_header = f"{'Store':<20} {'food':>7} {'beverage':>10} {'pantry':>8} {'non_food':>10} {'Total':>7}"
        print(pt_header)
        print("-" * 65)
        for store in sorted(df["store"].unique()):
            store_df = df[df["store"] == store]
            food_n = len(store_df[store_df["product_type"] == "food"])
            bev_n = len(store_df[store_df["product_type"] == "beverage"])
            pantry_n = len(store_df[store_df["product_type"] == "pantry_staple"])
            nf_n = len(store_df[store_df["product_type"] == "non_food"])
            print(f"{store:<20} {food_n:>7,} {bev_n:>10,} {pantry_n:>8,} {nf_n:>10,} {len(store_df):>7,}")
        food_t = len(df[df["product_type"] == "food"])
        bev_t = len(df[df["product_type"] == "beverage"])
        pantry_t = len(df[df["product_type"] == "pantry_staple"])
        nf_t = len(df[df["product_type"] == "non_food"])
        print("-" * 65)
        print(f"{'TOTAL':<20} {food_t:>7,} {bev_t:>10,} {pantry_t:>8,} {nf_t:>10,} {len(df):>7,}")
