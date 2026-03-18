"""Ingredient text normalization and parsing.

Handles the different ingredient formats across stores:
- TJ's: UPPERCASE, space-delimited at top level, commas inside parens
- Wegmans/Target/FtP: mixed case, comma-separated

Also handles:
- Allergen suffix stripping
- Enrichment vitamin removal (context-aware)
- Serving size gram extraction
- "Contains 2% or less of" markers
"""

import re


# ---------------------------------------------------------------------------
# Enrichment handling
# ---------------------------------------------------------------------------

# Tokens that appear inside enriched-flour parentheses and should be removed
# before scanning. These are fortification vitamins, not processing markers.
_ENRICHMENT_TOKENS = [
    r"niacin",
    r"riboflavin",
    r"thiamine?\s+mononitrate",
    r"folic\s+acid",
    r"reduced\s+iron",
    r"vitamin\s+a\s+palmitate",
    r"vitamin\s+d3?",
    r"pyridoxine(?:\s+hydrochloride)?",
    r"cyanocobalamin",
    r"enzyme",
    r"iron",  # only removed in enriched context
]

# Build a regex that finds "enriched ... (" then removes enrichment tokens
# inside the following parentheses
_ENRICHMENT_TOKEN_RE = re.compile(
    r"\b(?:" + "|".join(_ENRICHMENT_TOKENS) + r")\b",
    re.IGNORECASE,
)


def _strip_enrichment_context(text: str) -> str:
    """Remove enrichment vitamin tokens from parentheses that follow 'enriched'.

    Example:
        "enriched wheat flour (wheat flour, niacin, reduced iron, folic acid)"
        → "enriched wheat flour (wheat flour, , , )"
        → cleaned to "enriched wheat flour (wheat flour)"
    """
    # Find all "enriched ... (" patterns and their matching parens
    result = []
    i = 0
    lower = text.lower()

    while i < len(text):
        # Look for "enriched" keyword
        match = re.search(r"\benriched\b", lower[i:])
        if not match:
            result.append(text[i:])
            break

        # Add everything before "enriched"
        result.append(text[i:i + match.start()])
        enriched_start = i + match.start()

        # Find the next opening paren after "enriched"
        paren_start = text.find("(", enriched_start)
        if paren_start == -1:
            result.append(text[enriched_start:])
            break

        # Add text from "enriched" up to and including "("
        result.append(text[enriched_start:paren_start + 1])

        # Find matching closing paren
        depth = 1
        paren_end = paren_start + 1
        while paren_end < len(text) and depth > 0:
            if text[paren_end] == "(":
                depth += 1
            elif text[paren_end] == ")":
                depth -= 1
            paren_end += 1

        # Extract paren contents and strip enrichment tokens
        paren_contents = text[paren_start + 1:paren_end - 1]
        cleaned = _ENRICHMENT_TOKEN_RE.sub("", paren_contents)
        # Clean up leftover commas and spaces
        cleaned = re.sub(r",\s*,", ",", cleaned)
        cleaned = re.sub(r"^\s*,\s*", "", cleaned)
        cleaned = re.sub(r"\s*,\s*$", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

        result.append(cleaned)
        result.append(")")

        i = paren_end

    text = "".join(result)
    # Remove empty parentheses that might result
    text = re.sub(r"\(\s*\)", "", text)
    return text


# ---------------------------------------------------------------------------
# Allergen stripping
# ---------------------------------------------------------------------------

_ALLERGEN_MARKERS = [
    r"\bALLERGENS?\s*:",
    r"\ballergens?\s*:",
    r"\bAllergens?\s*:",
    r"\bCONTAINS\s*:\s*[A-Z]",  # "CONTAINS: MILK" at end
]
_ALLERGEN_RE = re.compile("|".join(_ALLERGEN_MARKERS))


def _strip_allergens(text: str) -> str:
    """Remove allergen warnings from end of ingredient text."""
    match = _ALLERGEN_RE.search(text)
    if match:
        text = text[:match.start()]
    return text.rstrip(". \t\n")


# ---------------------------------------------------------------------------
# "Contains 2% or less" handling
# ---------------------------------------------------------------------------

_CONTAINS_LESS_RE = re.compile(
    r"\bcontains?\s+(?:less\s+than\s+)?\d+%\s+(?:or\s+less\s+)?of\s*:?\s*",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Comma-at-depth-0 splitting
# ---------------------------------------------------------------------------

def _split_depth0(text: str, delimiter: str = ",") -> list[str]:
    """Split text on delimiter only when outside parentheses/brackets."""
    items = []
    depth = 0
    current: list[str] = []

    for ch in text:
        if ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == delimiter and depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    trailing = "".join(current).strip()
    if trailing:
        items.append(trailing)

    return [item for item in items if item]


# ---------------------------------------------------------------------------
# TJ's format detection
# ---------------------------------------------------------------------------

def _has_top_level_commas(text: str) -> bool:
    """Check if text has commas outside parentheses."""
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            return True
    return False


def _estimate_tj_item_count(normalized: str) -> int:
    """Estimate ingredient count for TJ space-delimited products.

    TJ's ALL-CAPS format uses spaces between top-level ingredients with no
    commas. We can't reliably split into individual items (multi-word
    ingredients like "sea salt" would be broken), but we CAN estimate the
    count by looking at the number of words outside parentheses ("spine words").

    Heuristic based on analysis of 525 TJ no-comma products:
      - 1-2 spine words → likely 1 ingredient (BEEF, SEA SALT, MEDJOOL DATES)
      - 3-4 spine words → likely 2 ingredients (SOCKEYE SALMON SALT)
      - 5+ spine words → almost certainly 3+ ingredients
    """
    # Remove parenthesized content (iteratively for nested parens)
    spine = normalized
    prev = ""
    while prev != spine:
        prev = spine
        spine = re.sub(r"\([^()]*\)", " ", spine)

    # Remove "contains 2% or less of" markers (still ingredient text, not a boundary)
    spine = _CONTAINS_LESS_RE.sub(" ", spine)

    spine = re.sub(r"\s+", " ", spine).strip()
    word_count = len(spine.split()) if spine else 0

    if word_count <= 2:
        return 1
    elif word_count <= 4:
        return 2
    else:
        # Rough estimate: ~2 words per ingredient on average
        return max(3, word_count // 2)


# ---------------------------------------------------------------------------
# Main normalize function
# ---------------------------------------------------------------------------

def normalize_ingredients(raw_text: str | None, store: str) -> dict:
    """Parse a raw ingredient string into normalized form.

    Args:
        raw_text: The raw ingredient string (may be None for whole foods).
        store: Store identifier ("trader_joes", "wegmans", "target", "farm_to_people").

    Returns:
        {
            "normalized": str,      # lowercase, cleaned, ready for regex scanning
            "items": list[str],     # best-effort individual ingredient list
            "item_count": int,      # len(items)
        }
    """
    if not raw_text or not raw_text.strip():
        return {"normalized": "", "items": [], "item_count": 0}

    text = raw_text.strip()

    # Step 1: Strip allergen warnings
    text = _strip_allergens(text)

    # Step 2: Strip enrichment vitamins (context-aware)
    text = _strip_enrichment_context(text)

    # Step 3: Normalize to lowercase and collapse whitespace
    normalized = text.lower()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # Strip trailing period
    normalized = normalized.rstrip(".")

    # Step 4: Parse into items (store-aware)
    if store == "trader_joes":
        # TJ's: if top-level commas exist, use them; otherwise treat as blob
        if _has_top_level_commas(normalized):
            items = _split_depth0(normalized, ",")
        else:
            # Treat as a single blob — can't reliably space-split multi-word
            # ingredients. But estimate the true count for classification.
            items = [normalized]
            estimated_count = _estimate_tj_item_count(normalized)
    else:
        # Standard comma-separated format
        items = _split_depth0(normalized, ",")

    # Clean up items
    items = [item.strip().rstrip(".") for item in items if item.strip()]

    # For TJ no-comma products, use the estimated count instead of len(items)
    # since items=[blob] doesn't reflect actual ingredient count
    if store == "trader_joes" and not _has_top_level_commas(normalized):
        item_count = estimated_count
    else:
        item_count = len(items)

    # Step 5: Parse top-level components (for composed meals like bowls, sushi)
    components = _parse_components(normalized)

    return {
        "normalized": normalized,
        "items": items,
        "item_count": item_count,
        "components": components,
    }


# ---------------------------------------------------------------------------
# Component parsing — for composed meals (bowls, sushi, prepared foods)
# ---------------------------------------------------------------------------

def _parse_components(normalized: str) -> list[str]:
    """Split a normalized ingredient string into top-level components.

    Composed meals list sub-recipes at depth 0 separated by commas, each
    with their own parenthesized sub-ingredients. This function returns
    those top-level chunks so that scoring functions can evaluate patterns
    *within* each component rather than across the entire flat string.

    We distinguish "composed meals" (bowls, sushi, prepared foods) from
    "simple products" (Twinkies, M&Ms) by checking whether the parenthesized
    groups are *substantial sub-recipes* (containing 3+ comma-separated
    sub-ingredients) rather than simple ingredient clarifications like
    "enriched flour (wheat flour, niacin)" or "whey (from milk)".

    Example — composed meal (returns components):
        "quinoa brown rice (water, rice, olive oil, salt), marinated beef (beef, soy sauce, sugar, ...)"
        → ["quinoa brown rice (water, rice, olive oil, salt)",
           "marinated beef (beef, soy sauce, sugar, ...)"]

    Example — simple product (returns [normalized]):
        "sugar, enriched flour (wheat flour), water, hfcs, tallow, dextrose"
        → ["sugar, enriched flour (wheat flour), water, hfcs, tallow, dextrose"]
    """
    # Use depth-0 splitting — same logic as _split_depth0
    parts = _split_depth0(normalized, ",")

    # Build list of parts, tracking which have parens
    components: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        components.append(part)

    # Count "substantial" parenthesized groups: those containing 3+ commas
    # inside their parens, indicating a real sub-recipe rather than a
    # clarification like "(from milk)" or "(wheat flour, niacin)".
    substantial_count = 0
    for comp in components:
        paren_start = comp.find("(")
        if paren_start == -1:
            continue
        # Extract everything inside the outermost parens
        depth = 0
        paren_content = []
        inside = False
        for ch in comp[paren_start:]:
            if ch == "(":
                depth += 1
                if depth == 1:
                    inside = True
                    continue
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            if inside:
                paren_content.append(ch)
        inner = "".join(paren_content)
        # Count depth-1 commas (commas at the first level inside the parens)
        inner_depth = 0
        comma_count = 0
        for ch in inner:
            if ch in "([{":
                inner_depth += 1
            elif ch in ")]}":
                inner_depth = max(0, inner_depth - 1)
            elif ch == "," and inner_depth == 0:
                comma_count += 1
        # 3+ commas means 4+ sub-ingredients → substantial sub-recipe
        if comma_count >= 3:
            substantial_count += 1

    # Only treat as composed meal if there are 2+ substantial sub-recipe groups
    if substantial_count >= 2:
        return components
    return [normalized]


# ---------------------------------------------------------------------------
# Nesting depth analysis
# ---------------------------------------------------------------------------

def get_nesting_depth(text: str, match_start: int) -> int:
    """Return the parenthetical nesting depth at a given position in text.

    Depth 0 = top-level ingredient
    Depth 1 = inside one level of parens (sub-ingredient of a compound)
    Depth 2+ = deeply nested (sub-sub-ingredient, e.g., a carrier in a powder)

    This lets scoring discount ingredients that appear deep in sub-lists.
    """
    depth = 0
    for i in range(min(match_start, len(text))):
        if text[i] in "([{":
            depth += 1
        elif text[i] in ")]}":
            depth = max(0, depth - 1)
    return depth


def annotate_nesting_depths(text: str, matches: dict) -> dict[str, int]:
    """For each matched pattern label, find its nesting depth in the text.

    Args:
        text: The normalized ingredient string.
        matches: {label: Pattern} dict from ontology.scan_ingredients().

    Returns:
        {label: depth} where depth is the parenthetical nesting level.
    """
    depths = {}
    for label, pat in matches.items():
        m = pat.regex.search(text)
        if m:
            depths[label] = get_nesting_depth(text, m.start())
        else:
            depths[label] = 0
    return depths


# ---------------------------------------------------------------------------
# Serving size extraction
# ---------------------------------------------------------------------------

# Ordered by priority: grams first, then oz→g, then mL≈g.
_SERVING_G_RE = re.compile(r"(\d+\.?\d*)\s*g(?:rams?)?\b", re.IGNORECASE)
_SERVING_OZ_RE = re.compile(r"(\d+\.?\d*)\s*oz\b", re.IGNORECASE)
_SERVING_ML_RE = re.compile(r"(\d+\.?\d*)\s*ml\b", re.IGNORECASE)
_SERVING_BARE_RE = re.compile(r"^(\d+\.?\d*)$")

_OZ_TO_G = 28.3495


def parse_serving_grams(serving_size: str | None) -> float | None:
    """Extract gram value from a serving size string.

    Priority: grams > oz (×28.35) > mL (≈g for water-based) > bare number.
    Household measures ("1 cup", "2 Tbsp") return None.

    Examples:
        "1 oz (28g)" → 28.0        (grams wins over oz)
        "28 grams"   → 28.0        (Wegmans format)
        "40g"        → 40.0
        "1 oz"       → 28.35
        "355.0 mL"   → 355.0       (density ≈ 1 for beverages)
        "240"        → 240.0       (bare number, assumed grams)
        "1 cup"      → None
    """
    if not serving_size:
        return None
    s = str(serving_size).strip()

    # 1. Grams (explicit)
    m = _SERVING_G_RE.search(s)
    if m:
        return float(m.group(1))

    # 2. Ounces → grams
    m = _SERVING_OZ_RE.search(s)
    if m:
        return round(float(m.group(1)) * _OZ_TO_G, 1)

    # 3. Milliliters ≈ grams (density ~1 for beverages)
    m = _SERVING_ML_RE.search(s)
    if m:
        return float(m.group(1))

    # 4. Bare number (Wegmans sometimes stores just "240")
    m = _SERVING_BARE_RE.match(s)
    if m:
        return float(m.group(1))

    return None
