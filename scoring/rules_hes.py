"""Hyperpalatability Engineering Score (HES) — 0 to 20 points.

This is the most novel axis. It doesn't measure individual ingredients
but *patterns of combination* that signal engineered hyperpalatability:

- Flavor + sweetener = taste engineering
- Multiple sweeteners = label sugar masking
- Non-nutritive sweetener = decoupled reward signaling
- Coating fat + sweetener = the candy/bar texture formula
- Flavor enhancer stacking = savory engineering
- Triple threat (fat + sweet + flavor) = the classic "can't stop eating" design

v0.2 changes:
  - Component-aware scoring: for composed meals (bowls, sushi, prepared
    meals), patterns are evaluated WITHIN each component rather than across
    the entire flat ingredient string. The final score is the MAX of any
    single component's score.
  - This prevents a bowl with sugar in its soy sauce, yeast extract in its
    mushroom powder, and hydrogenated oil in its beef marinade from
    triggering "triple_threat" when those ingredients are in separate
    sub-recipes and aren't working together for hyperpalatability.
  - For simple products (single component), behavior is unchanged.
"""

from scoring.ontology import (
    scan_ingredients,
    CALORIC_SWEETENERS,
    NON_NUTRITIVE_SWEETENERS,
    FLAVOR_INGREDIENTS,
    FLAVOR_ENHANCERS,
    COATING_FATS,
    _find_unique_matches,
)


def _score_single_text(scan_results: dict) -> tuple[int, list[str]]:
    """Score a single text blob for hyperpalatability patterns.

    Returns (score, patterns_detected).
    """
    flavors = scan_results.get("flavors", {})
    flavor_enhancers = scan_results.get("flavor_enhancers", {})
    caloric_sweeteners = scan_results.get("caloric_sweeteners", {})
    nns = scan_results.get("nns", {})
    coating_fats = scan_results.get("coating_fats", {})

    has_flavor = len(flavors) > 0
    has_enhancer = len(flavor_enhancers) > 0
    has_caloric_sweet = len(caloric_sweeteners) > 0
    has_nns = len(nns) > 0
    has_coating_fat = len(coating_fats) > 0
    sweetener_type_count = len(caloric_sweeteners)

    score = 0
    patterns = []

    # Pattern 1: Flavor ingredient + caloric sweetener (+4)
    if has_flavor and has_caloric_sweet:
        score += 4
        patterns.append("flavor_plus_sweetener")

    # Pattern 2: Multiple caloric sweetener types (+4)
    if sweetener_type_count >= 2:
        score += 4
        patterns.append("multiple_sweeteners")

    # Pattern 3: Non-nutritive sweetener present (+3)
    if has_nns:
        score += 3
        patterns.append("non_nutritive_sweetener")

    # Pattern 4: Coating fat + sweetener (+4)
    if has_coating_fat and (has_caloric_sweet or has_nns):
        score += 4
        patterns.append("coating_fat_plus_sweetener")

    # Pattern 5: Flavor enhancer stacking (+3)
    if has_enhancer and (has_flavor or len(flavor_enhancers) >= 2):
        score += 3
        patterns.append("flavor_enhancer_stacking")

    # Pattern 6: Triple threat (+2)
    if has_coating_fat and (has_caloric_sweet or has_nns) and (has_flavor or has_enhancer):
        score += 2
        patterns.append("triple_threat")

    score = min(20, score)
    return score, patterns


def _scan_component_for_hes(component_text: str) -> dict:
    """Run a lightweight HES-only scan on a single component string."""
    return {
        "caloric_sweeteners": _find_unique_matches(CALORIC_SWEETENERS, component_text),
        "nns": _find_unique_matches(NON_NUTRITIVE_SWEETENERS, component_text),
        "flavors": _find_unique_matches(FLAVOR_INGREDIENTS, component_text),
        "flavor_enhancers": _find_unique_matches(FLAVOR_ENHANCERS, component_text),
        "coating_fats": _find_unique_matches(COATING_FATS, component_text),
    }


def score_hes(scan_results: dict, components: list[str] | None = None) -> dict:
    """Calculate Hyperpalatability Engineering Score.

    Args:
        scan_results: Output from ontology.scan_ingredients() (full product).
        components: List of top-level component strings from normalize.
                    If provided and len > 1, patterns are evaluated per-component
                    and the max component score is used.
                    If None or single component, uses the full scan_results.

    Returns:
        {
            "score": int (0-20),
            "patterns_detected": list[str],
        }
    """
    # For single-component or simple products, use the original flat approach
    if not components or len(components) <= 1:
        score, patterns = _score_single_text(scan_results)
        return {"score": score, "patterns_detected": patterns}

    # For multi-component products: score each component independently,
    # then take the MAX score. This prevents cross-component pattern triggers.
    best_score = 0
    best_patterns = []

    for comp_text in components:
        comp_scan = _scan_component_for_hes(comp_text)
        comp_score, comp_patterns = _score_single_text(comp_scan)
        if comp_score > best_score:
            best_score = comp_score
            best_patterns = comp_patterns

    return {
        "score": best_score,
        "patterns_detected": best_patterns,
    }
