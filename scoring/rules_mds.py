"""Matrix Disruption Score (MDS) — 0 to 30 points.

Measures how far ingredients have been taken from their whole-food origin.
Products made from isolates, modified starches, and industrial substrates
score high. Products using only whole foods and culinary ingredients score 0.

v0.2 changes:
  - Nesting-depth awareness: ingredients buried inside sub-ingredient
    parentheses (e.g., "maltodextrin" as a carrier in "mushroom powder
    (maltodextrin, mushroom extract)") are discounted. Depth >= 2 gets
    half weight; depth >= 1 gets 75% weight for bucket-2 items.
  - This prevents composed meals (bowls, sushi) from inflating MDS simply
    because many sub-components each have a minor functional ingredient.
"""


# Depth discount factors: how much to multiply the point contribution
# based on how deeply nested the ingredient is in the parenthetical structure.
_DEPTH_DISCOUNT_B2 = {0: 1.0, 1: 0.5, 2: 0.25}  # bucket 2: generous discount
_DEPTH_DISCOUNT_B3 = {0: 1.0, 1: 0.75, 2: 0.4}   # bucket 3: still counts but reduced


def _depth_factor(depth: int, discount_table: dict) -> float:
    """Get the discount factor for a given nesting depth."""
    if depth in discount_table:
        return discount_table[depth]
    # Deeper than tracked: use the deepest known discount
    return min(discount_table.values())


def score_mds(scan_results: dict, nesting_depths: dict | None = None) -> dict:
    """Calculate Matrix Disruption Score.

    Args:
        scan_results: Output from ontology.scan_ingredients().
        nesting_depths: {label: depth} from normalize.annotate_nesting_depths().
                        If None, all ingredients are treated as depth 0 (no discount).

    Returns:
        {
            "score": int (0-30),
            "bucket_2_items": list[str],
            "bucket_3_items": list[str],
            "has_hydrogenated": bool,
        }
    """
    if nesting_depths is None:
        nesting_depths = {}

    bucket_2 = scan_results.get("bucket_2", {})
    bucket_3 = scan_results.get("bucket_3", {})

    b2_labels = list(bucket_2.keys())
    b3_labels = list(bucket_3.keys())

    # --- Bucket 2 contribution (diminishing returns + depth discount) ---
    # Sort by depth ascending so top-level items count first (higher weight)
    b2_sorted = sorted(b2_labels, key=lambda l: nesting_depths.get(l, 0))
    b2_score = 0.0
    for i, label in enumerate(b2_sorted):
        depth = nesting_depths.get(label, 0)
        factor = _depth_factor(depth, _DEPTH_DISCOUNT_B2)
        base = 3.0 if i == 0 else 2.0
        b2_score += base * factor
    b2_score = min(b2_score, 10.0)

    # --- Bucket 3 contribution (diminishing returns + depth discount) ---
    b3_sorted = sorted(b3_labels, key=lambda l: nesting_depths.get(l, 0))
    b3_score = 0.0
    for i, label in enumerate(b3_sorted):
        depth = nesting_depths.get(label, 0)
        factor = _depth_factor(depth, _DEPTH_DISCOUNT_B3)
        base = 5.0 if i == 0 else 3.0
        b3_score += base * factor
    b3_score = min(b3_score, 20.0)

    # --- Hydrogenated/interesterified fat bonus ---
    # Also depth-aware: if the hydrogenated fat is deeply nested (e.g., in a
    # vegetable oil blend sub-ingredient), reduce the bonus.
    has_hydro = any(
        label in ("hydrogenated fat", "partially hydrogenated fat", "interesterified fat")
        for label in b3_labels
    )
    hydro_bonus = 0.0
    if has_hydro:
        # Find the shallowest depth among hydrogenated fat matches
        hydro_depths = [
            nesting_depths.get(label, 0)
            for label in b3_labels
            if label in ("hydrogenated fat", "partially hydrogenated fat", "interesterified fat")
        ]
        min_depth = min(hydro_depths) if hydro_depths else 0
        hydro_bonus = 5.0 * _depth_factor(min_depth, _DEPTH_DISCOUNT_B3)

    total = min(30, int(round(b2_score + b3_score + hydro_bonus)))

    return {
        "score": total,
        "bucket_2_items": b2_labels,
        "bucket_3_items": b3_labels,
        "has_hydrogenated": has_hydro,
    }
