"""Metabolic Load Score (MLS) — 0 to 20 points.

Measures the physiological burden per serving based on nutrition facts.
Independent of ingredient processing — a product can be "clean" ingredients
but still metabolically harsh (e.g., pure honey has high sugar).

When serving_g is available, values are normalized to per-100g and scored
against per-100g thresholds.  When serving_g is unavailable, raw per-serving
values are scored against calibrated per-serving thresholds (derived from
the per-100g thresholds assuming a median ~40g serving).

Energy density modifier (v0.9.1): +2 points when kcal/g > 4.0 AND a sugar
flag is already triggered.  This targets sweet, calorie-packed products
(candy bars, cookies) while leaving energy-dense whole foods (olive oil,
nuts, peanut butter) unaffected — they never trigger sugar flags.
"""

import math


def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert a nutrition value to float.

    Handles int, float, None, and string edge cases.
    Our scrapers already normalize most values, but stores differ:
    - TJ's: floats (calories: 160.0)
    - Wegmans: ints (calories: 120)
    - Target: floats (calories: 140.0)
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if math.isnan(value):
            return default
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().lower()
        for suffix in ("mg", "g", "mcg", "%"):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
# Per-100g thresholds (used when serving_g is available and values are
# normalized).
_T100 = {
    "added_sugar_very_high": 20,
    "added_sugar_high": 10,
    "total_sugar_very_high": 25,
    "total_sugar_high": 15,
    "sodium_very_high": 800,
    "sodium_high": 500,
    "sat_fat_very_high": 8,
    "sat_fat_high": 5,
    "fiber_high": 5,
    "fiber_moderate": 3,
    "protein_high": 20,
    "protein_moderate": 10,
}

# Per-serving thresholds — calibrated from per-100g thresholds assuming a
# median serving of ~40g (threshold_per_serving = threshold_per_100g × 0.40).
# Used when serving_g is unavailable and values remain as-reported.
_TPS = {
    "added_sugar_very_high": 8,
    "added_sugar_high": 4,
    "total_sugar_very_high": 10,
    "total_sugar_high": 6,
    "sodium_very_high": 320,
    "sodium_high": 200,
    "sat_fat_very_high": 3.2,
    "sat_fat_high": 2.0,
    "fiber_high": 2.0,
    "fiber_moderate": 1.2,
    "protein_high": 8,
    "protein_moderate": 4,
}

# Energy density modifier — only fires when BOTH conditions are met:
# (1) energy density > 4.0 kcal/g, AND (2) a sugar MLS flag is present.
# This targets sweet, calorie-packed formulations (candy, cookies, granola
# bars) while protecting energy-dense whole foods (olive oil, nuts, cheese,
# peanut butter) which never trigger sugar flags.
_ENERGY_DENSITY_THRESHOLD = 4.0  # kcal per gram
_ENERGY_DENSITY_POINTS = 2
_SUGAR_FLAGS = frozenset({
    "very_high_added_sugar",
    "high_added_sugar",
    "very_high_total_sugar",
    "high_total_sugar",
})


def score_mls(nutrition: dict | None, serving_g: float | None = None) -> dict:
    """Calculate Metabolic Load Score.

    Args:
        nutrition: Nutrition dict from product data (or None).
        serving_g: Serving size in grams (or None if unparseable).

    Returns:
        {
            "score": int (0-20),
            "has_nutrition": bool,
            "mls_basis": "per_100g" | "per_serving",
            "serving_g_source": "parsed" | "missing",
            "tiny_serving": bool,
            "flags": list[str],
            "offsets": list[str],
        }
    """
    result = {
        "score": 0,
        "has_nutrition": False,
        "mls_basis": "per_serving",
        "serving_g_source": "missing",
        "tiny_serving": False,
        "flags": [],
        "offsets": [],
    }

    if not nutrition:
        return result

    result["has_nutrition"] = True

    # Extract raw values
    added_sugars = _safe_float(nutrition.get("added_sugars_g"))
    total_sugars = _safe_float(nutrition.get("total_sugars_g"))
    sodium = _safe_float(nutrition.get("sodium_mg"))
    sat_fat = _safe_float(nutrition.get("saturated_fat_g"))
    fiber = _safe_float(nutrition.get("dietary_fiber_g"))
    protein = _safe_float(nutrition.get("protein_g"))

    # Choose thresholds based on whether we can normalize to per-100g
    if serving_g and serving_g > 0:
        result["serving_g_source"] = "parsed"
        result["mls_basis"] = "per_100g"
        scale = 100.0 / serving_g
        added_sugars *= scale
        total_sugars *= scale
        sodium *= scale
        sat_fat *= scale
        fiber *= scale
        protein *= scale
        t = _T100

        if serving_g < 15:
            result["tiny_serving"] = True
    else:
        t = _TPS

    score = 0

    # --- Sugar ---
    if added_sugars > 0:
        # Prefer added sugars (more specific)
        if added_sugars > t["added_sugar_very_high"]:
            score += 7
            result["flags"].append("very_high_added_sugar")
        elif added_sugars > t["added_sugar_high"]:
            score += 4
            result["flags"].append("high_added_sugar")
    elif total_sugars > 0:
        # Fallback to total sugars (less specific, higher thresholds)
        if total_sugars > t["total_sugar_very_high"]:
            score += 6
            result["flags"].append("very_high_total_sugar")
        elif total_sugars > t["total_sugar_high"]:
            score += 3
            result["flags"].append("high_total_sugar")

    # --- Sodium ---
    if sodium > t["sodium_very_high"]:
        score += 6
        result["flags"].append("very_high_sodium")
    elif sodium > t["sodium_high"]:
        score += 3
        result["flags"].append("high_sodium")

    # --- Saturated fat ---
    if sat_fat > t["sat_fat_very_high"]:
        score += 5
        result["flags"].append("very_high_sat_fat")
    elif sat_fat > t["sat_fat_high"]:
        score += 3
        result["flags"].append("high_sat_fat")

    # --- Fiber offset ---
    if fiber >= t["fiber_high"]:
        score -= 3
        result["offsets"].append("high_fiber")
    elif fiber >= t["fiber_moderate"]:
        score -= 2
        result["offsets"].append("moderate_fiber")

    # --- Protein offset ---
    if protein >= t["protein_high"]:
        score -= 2
        result["offsets"].append("high_protein")
    elif protein >= t["protein_moderate"]:
        score -= 1
        result["offsets"].append("moderate_protein")

    # --- Energy density modifier ---
    # Requires raw (per-serving) calories and serving_g to compute kcal/g.
    # Only fires when a sugar flag is already present, preventing false
    # positives on energy-dense whole foods (olive oil, nuts, peanut butter).
    calories = _safe_float(nutrition.get("calories"))
    if calories > 0 and serving_g and serving_g > 0:
        energy_density = calories / serving_g
        result["energy_density"] = round(energy_density, 2)
        if energy_density > _ENERGY_DENSITY_THRESHOLD and (
            set(result["flags"]) & _SUGAR_FLAGS
        ):
            score += _ENERGY_DENSITY_POINTS
            result["flags"].append("energy_dense_sweet")

    # Clamp to 0-20
    result["score"] = max(0, min(20, score))
    return result
