"""Additive/Formulation Score (AFS) — 0 to 80 points.

Measures additive load from formulation ingredients (emulsifiers, dyes,
preservatives, gums, NNS, flavors). Industrial substrates (maltodextrin,
HFCS, modified starch, protein isolate, etc.) are scored by MDS only —
removed from AFS in v0.7.0 to eliminate MDS-AFS double-counting.

Two-component scoring:
  severity = depth-discounted weighted sum of additive tier matches
  density  = count of unique additives found (depth-discounted)

AFS = severity + density, capped at 80.

v0.8.0: Cap raised 40 → 80 to restore top-end discrimination.
  At cap=40, 993 products were compressed into a single ceiling value
  despite true uncapped scores ranging 40–143. The cap was previously
  raised from 30 → 40 in v0.3.0 for the same reason. Cap=80 frees
  ~1,495 products and allows the P4 tier to meaningfully discriminate
  the most formulation-engineered products (candy, frozen meals,
  shelf-stable desserts) from merely heavily-processed ones.
"""


# Default AFS weights per tier
_TIER_WEIGHTS = {"A": 5, "B": 3, "C": 1}

# Depth discounts for AFS: additives in sub-ingredients count less
_AFS_DEPTH_DISCOUNT = {0: 1.0, 1: 0.6, 2: 0.3}


def _depth_factor(depth: int) -> float:
    if depth in _AFS_DEPTH_DISCOUNT:
        return _AFS_DEPTH_DISCOUNT[depth]
    return min(_AFS_DEPTH_DISCOUNT.values())


def score_afs(scan_results: dict, nesting_depths: dict | None = None) -> dict:
    """Calculate Additive/Formulation Score.

    Args:
        scan_results: Output from ontology.scan_ingredients().
        nesting_depths: {label: depth} from normalize.annotate_nesting_depths().
                        If None, all treated as depth 0 (no discount).

    Returns:
        {
            "score": int (0-80),
            "severity": int,
            "density": int,
            "tier_a": list[str],
            "tier_b": list[str],
            "tier_c": list[str],
            "tier_c_scored": bool,
        }
    """
    if nesting_depths is None:
        nesting_depths = {}

    tier_a = scan_results.get("tier_a", {})
    tier_b = scan_results.get("tier_b", {})
    tier_c = scan_results.get("tier_c", {})

    a_labels = list(tier_a.keys())
    b_labels = list(tier_b.keys())
    # Exclude fortification-category Tier C from AFS scoring.
    # Fortification vitamins (niacin, riboflavin, folic acid, etc.) are
    # nutritionally beneficial and should not inflate additive scores.
    c_labels = [l for l in tier_c if tier_c[l].category != "fortification"]
    c_labels_all = list(tier_c.keys())  # all Tier C for reporting

    count_a = len(a_labels)
    count_b = len(b_labels)
    count_c = len(c_labels)

    # --- Severity (depth-discounted) ---
    severity = 0.0

    # Tier A: +5 each, discounted by depth
    for label in a_labels:
        pat = tier_a[label]
        w = pat.weight if pat.weight > 0 else _TIER_WEIGHTS["A"]
        depth = nesting_depths.get(label, 0)
        severity += w * _depth_factor(depth)

    # Tier B: +3 each, discounted by depth
    for label in b_labels:
        pat = tier_b[label]
        w = pat.weight if pat.weight > 0 else _TIER_WEIGHTS["B"]
        depth = nesting_depths.get(label, 0)
        severity += w * _depth_factor(depth)

    # Graduated Tier A bonus based on count of TOP-LEVEL (depth 0) Tier A markers
    # This ensures that deeply-nested markers don't inflate the bonus
    top_level_a = sum(1 for l in a_labels if nesting_depths.get(l, 0) == 0)
    if top_level_a >= 8:
        severity += 12
    elif top_level_a >= 5:
        severity += 8
    elif top_level_a >= 3:
        severity += 4

    # Tier C: conditional — only scored if industrial context exists
    total_unique_ab = count_a + count_b
    total_unique_all = count_a + count_b + count_c
    tier_c_scored = total_unique_ab >= 1 or total_unique_all >= 3

    if tier_c_scored:
        for label in c_labels:
            pat = tier_c[label]
            w = pat.weight if pat.weight > 0 else _TIER_WEIGHTS["C"]
            depth = nesting_depths.get(label, 0)
            severity += w * _depth_factor(depth)

    severity = min(severity, 80.0)

    # --- Density ---
    # Count of unique additive labels, with depth-discounted weighting.
    # A deeply-nested additive contributes fractionally to density.
    density = 0.0
    for label in a_labels + b_labels + c_labels:
        depth = nesting_depths.get(label, 0)
        density += _depth_factor(depth)
    density = min(density, 10.0)

    # --- Combine ---
    score = min(80, int(round(severity + density)))

    return {
        "score": score,
        "severity": int(round(severity)),
        "density": int(round(density)),
        "tier_a": a_labels,
        "tier_b": b_labels,
        "tier_c": c_labels_all,
        "tier_c_scored": tier_c_scored,
    }
