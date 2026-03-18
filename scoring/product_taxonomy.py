"""Food identity taxonomy classifier using LLM (Claude Haiku) with caching.

This module classifies grocery products into a food identity ontology -- a
taxonomy that describes WHAT a food IS, not how it is stored, sold, or
temperature-managed.  A frozen pizza is still "composite.pizza", dried
mango is "pantry.dried_fruits_nuts", and ice cream is "desserts.frozen"
regardless of the retail aisle it sits in.

The ontology has 11 families and 68 subfamilies.  Every product receives:
    taxonomy_family      one of the 10 families
    taxonomy_subfamily   one of the 60 subfamilies
    taxonomy_label       "{family}.{subfamily}" combined string
    taxonomy_confidence  0.0-1.0 (capped at 0.90 for LLM results)
    taxonomy_source      "llm" or "fallback"

Classification is done via Claude Haiku in batches of 20 products.  Results
are cached to disk as JSON keyed by a SHA-256 hash that incorporates a
taxonomy version string, so any label-set changes auto-invalidate the cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Taxonomy constants
# ---------------------------------------------------------------------------

FAMILIES: set[str] = {
    "produce", "meat", "seafood", "plant_protein", "dairy_eggs",
    "baked_goods", "desserts", "drinks", "pantry", "composite",
    "non_food",
}

CANONICAL_LABELS: list[str] = [
    # Produce
    "produce.fruit",
    "produce.vegetable",
    "produce.herbs_aromatics",

    # Meat
    "meat.poultry",
    "meat.beef",
    "meat.pork",
    "meat.lamb_game",
    "meat.deli_charcuterie",
    "meat.bacon_sausages",

    # Seafood
    "seafood.fish",
    "seafood.shellfish",
    "seafood.smoked",
    "seafood.tinned",

    # Plant Protein
    "plant_protein.tofu",
    "plant_protein.tempeh",
    "plant_protein.seitan",
    "plant_protein.meat_substitute",

    # Dairy & Eggs
    "dairy_eggs.milk_cream",
    "dairy_eggs.creamers",    # coffee creamers (dairy and non-dairy) — previously in dairy_eggs.milk_cream
    "dairy_eggs.eggs_butter",
    "dairy_eggs.cheese",
    "dairy_eggs.cultured_dairy",
    "dairy_eggs.plant_based",

    # Baked Goods
    "baked_goods.bread",
    "baked_goods.buns_rolls",
    "baked_goods.bagels",              # bagels only
    "baked_goods.breakfast",           # waffles, french toast, breakfast biscuits, toaster items
    "baked_goods.breakfast_desserts",  # muffins, donuts, croissants, scones, cinnamon rolls, danishes
    "baked_goods.flatbreads",          # tortillas, naan, pita, lavash, wraps
    "baked_goods.dough",
    "baked_goods.gluten_free",

    # Desserts
    "desserts.baked",
    "desserts.frozen",
    "desserts.candy",
    "desserts.chocolate",

    # Drinks
    "drinks.coffee_tea",
    "drinks.sodas_mixers",
    "drinks.kombucha",
    "drinks.water_seltzers",
    "drinks.juice",
    "drinks.functional",
    "drinks.alcohol",  # beer, wine, spirits, hard cider — previously forced into sodas_mixers/water_seltzers

    # Pantry
    "pantry.noodles",
    "pantry.grains_beans",
    "pantry.chips_crackers",
    "pantry.dried_fruits_nuts",
    "pantry.granola_cereals",
    "pantry.bars",
    "pantry.jerky",
    "pantry.pickled_fermented",
    "pantry.oil_vinegar_spices",
    "pantry.baking_ingredients",  # raw ingredients: flour, sugar, chocolate chips, vanilla, baking powder
    "pantry.baking_mixes",        # ready-to-make mixes: pancake mix, cake mix, brownie mix, muffin mix
    "pantry.condiments_dressings",
    "pantry.honey_syrups",
    "pantry.jams_nut_butters",
    "pantry.canned_goods",
    "pantry.stocks",

    # Composite
    "composite.meals_entrees",
    "composite.sides_prepared",
    "composite.sandwiches_wraps",
    "composite.soups_ready",
    "composite.salads_prepared",
    "composite.dips_spreads",
    "composite.pizza",

    # Non-Food
    "non_food.pet",
    "non_food.floral",
    "non_food.household",
]

CANONICAL_LABEL_SET: set[str] = set(CANONICAL_LABELS)

# Version string embedded in every cache key.  Bump this whenever the
# label set or classification rules change to auto-invalidate old caches.
_TAXONOMY_VERSION = "v2.4"

# Disk cache lives alongside the scored output.
_CACHE_DIR = Path(__file__).parent.parent / "output" / "taxonomy_cache"

# Audit log: every invented label is appended here for taxonomy review.
_INVENTED_LOG = Path(__file__).parent.parent / "output" / "taxonomy_cache" / "invented_labels.jsonl"

# LLM settings
_MODEL = "claude-haiku-4-5-20251001"
_BATCH_SIZE = 50
_RATE_LIMIT_DELAY = 0.1  # seconds between batches
_MAX_CONFIDENCE = 0.90   # cap LLM-reported confidence


# ---------------------------------------------------------------------------
# TaxonomyResult
# ---------------------------------------------------------------------------

@dataclass
class TaxonomyResult:
    """Structured taxonomy classification for a single product."""

    family: str
    subfamily: str
    confidence: float
    source: str  # "llm" or "fallback"

    @property
    def label(self) -> str:
        return f"{self.family}.{self.subfamily}"

    def to_dict(self) -> dict:
        return {
            "taxonomy_label": self.label,
            "taxonomy_family": self.family,
            "taxonomy_subfamily": self.subfamily,
            "taxonomy_confidence": self.confidence,
            "taxonomy_source": self.source,
        }


def _default_result() -> TaxonomyResult:
    """Return a safe fallback when classification fails or is disabled."""
    return TaxonomyResult(
        family="pantry",
        subfamily="noodles",
        confidence=0.0,
        source="fallback",
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _norm(val: Any) -> str:
    """Normalize a field value for cache key hashing.

    Ensures None, NaN, and empty string all map to the same representation.
    """
    if val is None:
        return ""
    s = str(val)
    if s == "nan" or s == "None":
        return ""
    return s


def _cache_key(row: dict) -> str:
    """Deterministic hash for a product, incorporating taxonomy version.

    Changing _TAXONOMY_VERSION, store, name, category, or subcategory will
    produce a different key, forcing re-classification.
    """
    key_str = "|".join([
        _TAXONOMY_VERSION,
        _norm(row.get("store")),
        _norm(row.get("name")),
        _norm(row.get("category")),
        _norm(row.get("subcategory")),
    ])
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    """Return the file path for a given cache key."""
    return _CACHE_DIR / f"{key}.json"


def _load_cached(key: str) -> TaxonomyResult | None:
    """Load a cached result from disk if it exists."""
    import os

    path = _cache_path(key)
    if not path.exists():
        return None

    try:
        with open(path, "r") as f:
            data = json.load(f)
        family = data["family"]
        subfamily = data["subfamily"]
        if not family or not subfamily or family not in FAMILIES:
            return None  # structurally invalid cache entry
        return TaxonomyResult(
            family=family,
            subfamily=subfamily,
            confidence=float(data["confidence"]),
            source=str(data.get("source", "llm")),
        )
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        # Remove corrupted file so it doesn't block future runs
        path.unlink(missing_ok=True)
        return None


def _save_cached(key: str, result: TaxonomyResult) -> None:
    """Persist a classification result to disk."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "family": result.family,
        "subfamily": result.subfamily,
        "confidence": result.confidence,
        "source": result.source,
    }
    with open(_cache_path(key), "w") as f:
        json.dump(payload, f)


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""\
You are a grocery product taxonomy classifier.  Your job is to assign each
product to the best matching taxonomy label.

Respond ONLY with a JSON array.  Each element must be an object with these
keys: "family", "subfamily", "confidence", "notes".

Preferred labels (family.subfamily) — use these when they fit:
{chr(10).join("  - " + lbl for lbl in CANONICAL_LABELS)}

If a product fits one of the preferred labels, use it.
If NONE of the preferred labels fit well, invent a new one using the same
family.subfamily format — pick the most appropriate existing family and create
a descriptive snake_case subfamily (e.g. "drinks.alcohol", "pantry.baking_mixes",
"non_food.household").  Set confidence lower (0.5–0.7) for invented labels.
Do NOT force a bad fit just to stay within the preferred list.
In your "notes" field, explain why you invented the label and which preferred
label was the closest match that still didn't fit.

IMPORTANT GUIDELINES -- this is an IDENTITY taxonomy.  Classify by what the
food IS, not by where it is stored or what temperature it needs.

=== CORE IDENTITY RULES ===
  - Dried fruit (raisins, dried mango, etc.) -> pantry.dried_fruits_nuts
  - Ice cream / gelato / sorbet -> desserts.frozen
  - Candy -> desserts.candy
  - Chocolate bars / truffles -> desserts.chocolate
  - Tofu -> plant_protein.tofu
  - Tempeh -> plant_protein.tempeh
  - Seitan -> plant_protein.seitan
  - Beyond / Impossible / Gardein etc. -> plant_protein.meat_substitute
  - Fresh salsa / hummus / guacamole -> composite.dips_spreads
  - Shelf-stable salsa / hot sauce -> pantry.condiments_dressings
  - Canned soups -> pantry.canned_goods (NOT composite)
  - Broth / stock / bouillon / concentrate / soup base -> pantry.stocks
  - Sour cream -> dairy_eggs.cultured_dairy
  - Oat milk / almond milk / soy milk -> dairy_eggs.plant_based
  - Coffee (ground / beans / K-cups) AND RTD coffee -> drinks.coffee_tea
  - Tea (bags / loose leaf) AND RTD tea -> drinks.coffee_tea
  - Protein bars / energy bars -> pantry.bars
  - Jerky (including beef jerky) -> pantry.jerky (NOT meat)
  - Chips / crackers / pretzels / popcorn -> pantry.chips_crackers
  - Beer / wine / spirits / hard cider / hard seltzer (alcoholic) -> drinks.alcohol
  - Pancake mix / cake mix / brownie mix / muffin mix / bread mix -> pantry.baking_mixes
  - Flour / sugar / baking powder / chocolate chips / vanilla extract -> pantry.baking_ingredients
  - Coffee creamer (dairy or non-dairy, liquid or powder) -> dairy_eggs.creamers
  - Bagels (plain, everything, sesame, etc.) -> baked_goods.bagels
  - Waffles / french toast / toaster strudel / breakfast biscuits -> baked_goods.breakfast
  - Tortillas / naan / pita / lavash / flatbread wraps -> baked_goods.flatbreads
  - Pasta / spaghetti / penne / ramen / rice noodles / udon -> pantry.noodles
  - Marshmallows / gum / fruit snacks -> desserts.candy
  - Frozen pizza -> composite.pizza

=== MEALS vs SIDES (composite split) ===
  - composite.meals_entrees = complete meals / main dishes eaten as primary dish
    Examples: frozen dinners, meal bowls, burritos, rotisserie chicken,
    entrees, ready pasta dishes, meatball entrees
  - composite.sides_prepared = prepared sides / accompaniments / add-ons
    Examples: fries, onion rings, tater tots, pierogies, mac & cheese cups,
    mashed potatoes (ready-made), Rice-a-Roni, Knorr Pasta Sides,
    seasoned rice mixes, flavored couscous kits, multi-ingredient grain kits
  - Decision rule: if eaten as the primary dish -> meals_entrees;
    if it accompanies a main -> sides_prepared
  - Protein-forward components (meatballs, cooked chicken strips) -> meals_entrees
  - Starch/carb-forward sides (fries, loaded potatoes) -> sides_prepared
  - Plain rice packets / plain microwave grains -> pantry.grains_beans
  - Dried pasta / spaghetti / ramen noodles / rice noodles -> pantry.noodles
  - Seasoned rice/pasta/grain kits with seasoning packets -> composite.sides_prepared

=== EDGE CASE OVERRIDES ===
  1. Sauces that sound like meals (curry simmer sauce, tikka masala sauce,
     mac & cheese sauce pouch): if consumer must add core ingredients ->
     pantry.condiments_dressings (NOT composite)
  2. Nut mixes with coating (chocolate almonds, yogurt raisins, trail mix
     with candy): if nuts/fruit are the structural base -> pantry.dried_fruits_nuts.
     Only if candy/chocolate-forward (truffles, candy assortment) -> desserts.*
  3. Baked goods split:
     - Bagels only -> baked_goods.bagels
     - Waffles, french toast, toaster strudel, breakfast biscuits -> baked_goods.breakfast
     - Muffins, donuts, croissants, scones, cinnamon rolls, danishes -> baked_goods.breakfast_desserts
     - Tortillas, naan, pita, lavash, flatbread wraps -> baked_goods.flatbreads
     - Sweet baked desserts (cakes, cookies, brownies, snack cakes) -> desserts.baked
     - Shelf-stable bar-shaped -> pantry.bars
  4. Frozen fruit vs frozen desserts: plain frozen fruit / smoothie fruit
     packs -> produce.fruit. Sorbet/ice cream/novelties -> desserts.frozen.
     Bottled smoothies -> drinks.functional
  5. Deli salads and salad kits: chicken salad, tuna salad, potato salad,
     coleslaw, Caesar kit, any salad bowl -> composite.salads_prepared
  6. Canned/pouch fish vs smoked fish: shelf-stable fish in can/pouch ->
     seafood.tinned. Smoked fillets -> seafood.smoked. Smoked fish dip/spread
     -> composite.dips_spreads
  7. Cheese vs cheese dip: cream cheese/shredded/cottage -> dairy_eggs.cheese.
     Queso dip / cheese dip / pub cheese -> composite.dips_spreads
  8. Plant protein vs plant meal: protein components (nuggets, patties,
     crumbles, strips) -> plant_protein.meat_substitute. Fully assembled
     plant-based bowl/meal -> composite.meals_entrees
  9. Prepared produce-like sides: spiralized zucchini, cauliflower rice,
     riced veg (sold as ingredient substitute) -> produce.vegetable.
     Mashed potatoes, prepared sides -> composite.sides_prepared
 10. Hummus (any shelf-life) -> composite.dips_spreads.
     Guacamole (any form) -> composite.dips_spreads.
 11. Seasoned grain/pasta kits (Rice-a-Roni, Knorr Pasta Sides, flavored
     couscous, Spanish rice mix): if it includes seasoning packets or
     multiple ingredients forming a flavored dish -> composite.sides_prepared.
     Plain dried pasta / plain rice / plain grains -> pantry.

=== STORE CATEGORY WARNING ===
  The "category" field is a STORE AISLE name, NOT the product identity.
  For example, Wegmans uses "Produce & Floral" for ALL produce AND flowers.
  A banana with category "Produce & Floral" is produce.fruit, NOT non_food.
  ALWAYS classify based on the PRODUCT NAME and ingredients, never the
  store category alone.  Specific traps to avoid:
  - "Produce & Floral" category: most products are fruits, vegetables,
    herbs, salads, juice, etc.  Only actual flowers/bouquets/plants are
    non_food.floral.
  - "Sunflower" in a product name (seeds, oil, butter, cereal) is a FOOD,
    not a flower.  Classify by what the product IS (seeds -> dried_fruits_nuts,
    oil -> oil_vinegar_spices, butter -> jams_nut_butters, cereal -> granola_cereals).
  - "Carnation" is a BRAND name (Nestlé dairy products), not a flower.
    Classify Carnation products by what they are (milk, drink mix, etc.).
  - "Flower" in tea names (elderflower, butterfly pea flower) -> drinks.coffee_tea.
  - Chocolate shaped like flowers/tulips/roses -> desserts.chocolate or desserts.candy.

=== NON-FOOD ITEMS ===
  Products that are NOT human food or drink get family "non_food":
  - Pet food, pet treats, pet supplies (dog food, cat food, cat litter,
    dog treats, Freshpet, Blue Buffalo, Fancy Feast, Purina, etc.)
    -> non_food.pet
  - Flowers, bouquets, plants, floral arrangements, potted plants,
    decorative gourds (ONLY actual ornamental items, NOT edible produce)
    -> non_food.floral
  - Candles, cleaning supplies, paper goods, or any other household item
    -> non_food.household
  IMPORTANT: non_food.floral is ONLY for actual ornamental flowers/plants.
  If the product name is a fruit, vegetable, herb, seed, oil, or any
  edible item, it is NOT non_food even if the store category says "Floral".
  Use LOW confidence (0.10) for non-food items.

confidence should be between 0.0 and 1.0.
"""


def _build_user_prompt(rows: list[dict]) -> str:
    """Build the user message for a batch of products."""
    parts: list[str] = []
    for i, row in enumerate(rows, 1):
        ingredients_raw = str(row.get("ingredients", "") or "")
        ingredients_excerpt = ingredients_raw[:200] if ingredients_raw else ""
        parts.append(
            f"Product {i}:\n"
            f"  store: {row.get('store', '')}\n"
            f"  name: {row.get('name', '')}\n"
            f"  category: {row.get('category', '')}\n"
            f"  subcategory: {row.get('subcategory', '')}\n"
            f"  ingredients (excerpt): {ingredients_excerpt}"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """Extract a JSON array from the LLM response.

    Handles both raw JSON and markdown-fenced code blocks.
    """
    # Try extracting from a markdown code block first.
    match = _JSON_BLOCK_RE.search(text)
    if match:
        text = match.group(1).strip()

    return json.loads(text)


def _log_invented(
    label: str,
    family: str,
    subfamily: str,
    confidence: float,
    notes: str,
    product_name: str,
    store: str,
) -> None:
    """Append an invented label to the audit log (JSONL, one record per line)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "invented_label": label,
        "family": family,
        "subfamily": subfamily,
        "confidence": confidence,
        "notes": notes,
        "product_name": product_name,
        "store": store,
    }
    with open(_INVENTED_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def _parse_one(raw: dict, product_name: str = "", store: str = "") -> TaxonomyResult | None:
    """Validate and convert a single LLM result dict into a TaxonomyResult.

    Accepts both canonical labels and invented family.subfamily labels.
    Invented labels are appended to the audit log for taxonomy review.
    Returns None only if the data is structurally malformed.
    """
    try:
        family = str(raw.get("family", "")).strip()
        subfamily_raw = raw.get("subfamily")
        subfamily = str(subfamily_raw).strip() if subfamily_raw is not None else ""
        conf_raw = raw.get("confidence", 0.0)
        confidence = float(conf_raw) if conf_raw is not None else 0.5
        notes = str(raw.get("notes", "")).strip()
    except (TypeError, ValueError):
        return None

    label = f"{family}.{subfamily}"

    # Handle LLM returning combined "family.subfamily" in the family field
    # with subfamily as null/empty (e.g. family="dairy_eggs.cheese", subfamily="").
    if label not in CANONICAL_LABEL_SET and "." in family and not subfamily:
        label = family
        parts = family.split(".", 1)
        family = parts[0]
        subfamily = parts[1]

    # Handle LLM duplicating subfamily in both fields, producing labels like
    # "drinks.coffee_tea.coffee_tea" or "dairy_eggs.cheese.cheese".
    if label not in CANONICAL_LABEL_SET:
        dot_parts = label.split(".")
        if len(dot_parts) == 3 and dot_parts[1] == dot_parts[2]:
            family = dot_parts[0]
            subfamily = dot_parts[1]
            label = f"{family}.{subfamily}"
        elif len(dot_parts) == 4 and dot_parts[0] == dot_parts[2] and dot_parts[1] == dot_parts[3]:
            family = dot_parts[0]
            subfamily = dot_parts[1]
            label = f"{family}.{subfamily}"
        elif len(dot_parts) >= 3:
            # Handle LLM using a canonical label as the "family" field with
            # an invented sub-subfamily, e.g. family="drinks.sodas_mixers",
            # subfamily="cocktail_mixers" → "drinks.sodas_mixers.cocktail_mixers".
            # Collapse to the canonical parent when the first two parts match.
            candidate = f"{dot_parts[0]}.{dot_parts[1]}"
            if candidate in CANONICAL_LABEL_SET:
                family = dot_parts[0]
                subfamily = dot_parts[1]
                label = candidate

    # Reject structurally malformed labels (empty family/subfamily, or
    # family not in the known set — the LLM invented a whole new family).
    if not family or not subfamily:
        return None
    if family not in FAMILIES:
        print(f"[taxonomy]   REJECTED unknown family '{family}' for '{product_name[:50]}'")
        return None

    # Cap confidence to avoid overconfident LLM outputs.
    confidence = min(confidence, _MAX_CONFIDENCE)

    invented = label not in CANONICAL_LABEL_SET

    if invented:
        # Log for taxonomy audit review.
        _log_invented(label, family, subfamily, confidence, notes, product_name, store)

    return TaxonomyResult(
        family=family,
        subfamily=subfamily,
        confidence=round(confidence, 3),
        source="llm_invented" if invented else "llm",
    )


# ---------------------------------------------------------------------------
# LLM batch classification
# ---------------------------------------------------------------------------

class _FatalAPIError(Exception):
    """Raised for API errors that should stop all further batches."""
    pass


def _classify_batch_llm(rows: list[dict]) -> list[TaxonomyResult | None]:
    """Send a batch of products to Claude Haiku and return parsed results.

    Returns a list parallel to *rows*.  Entries are None when classification
    fails for that product (invalid label, parse error, etc.).

    Raises _FatalAPIError for billing/auth errors that won't resolve by
    retrying (e.g. insufficient credits, invalid API key).
    """
    # Lazy import -- keeps the module usable without anthropic installed,
    # e.g. when running with use_llm=False.
    try:
        import anthropic
    except ImportError:
        print("[taxonomy] anthropic package not installed -- returning None for batch")
        return [None] * len(rows)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[taxonomy] ANTHROPIC_API_KEY not set -- returning None for batch")
        return [None] * len(rows)

    client = anthropic.Anthropic(api_key=api_key)
    user_prompt = _build_user_prompt(rows)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        exc_str = str(exc)
        # Detect non-retryable errors and stop immediately.
        if "credit balance" in exc_str or "authentication" in exc_str.lower() or "invalid.*api.key" in exc_str.lower():
            raise _FatalAPIError(exc_str) from exc
        print(f"[taxonomy] API error: {exc}")
        return [None] * len(rows)

    # Extract text content from the response.
    response_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            response_text += block.text

    # Parse JSON array from response.
    try:
        parsed_list = _extract_json(response_text)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[taxonomy] JSON parse error: {exc}")
        print(f"[taxonomy]   Raw response (first 500 chars): {response_text[:500]}")
        return [None] * len(rows)

    if not isinstance(parsed_list, list):
        print(f"[taxonomy] Expected JSON array from LLM, got {type(parsed_list).__name__}")
        print(f"[taxonomy]   Raw response (first 500 chars): {response_text[:500]}")
        return [None] * len(rows)

    if len(parsed_list) != len(rows):
        print(f"[taxonomy]   LLM returned {len(parsed_list)} results for {len(rows)} products")

    # Align parsed results with input rows.  If the LLM returned fewer
    # items than we sent, pad with None.
    results: list[TaxonomyResult | None] = []
    for i in range(len(rows)):
        if i < len(parsed_list):
            parsed = _parse_one(
                parsed_list[i],
                product_name=rows[i].get("name", ""),
                store=rows[i].get("store", ""),
            )
            if parsed is None:
                raw = parsed_list[i]
                label = f"{raw.get('family', '?')}.{raw.get('subfamily', '?')}"
                print(f"[taxonomy]   REJECTED: {label} for '{rows[i].get('name', '?')[:50]}'")
            results.append(parsed)
        else:
            results.append(None)

    return results


def _classify_all_llm(rows: list[dict]) -> dict[str, TaxonomyResult]:
    """Classify all uncached products via the LLM and update the disk cache.

    Returns a mapping from cache key to TaxonomyResult for every product
    that was successfully classified (cached or newly classified).
    """
    # Determine which products still need classification.
    uncached: list[tuple[int, str, dict]] = []  # (index, cache_key, row)
    results: dict[str, TaxonomyResult] = {}

    for i, row in enumerate(rows):
        key = _cache_key(row)
        cached = _load_cached(key)
        if cached is not None:
            results[key] = cached
        else:
            uncached.append((i, key, row))

    if not uncached:
        return results

    print(f"[taxonomy] {len(results)} cached, {len(uncached)} to classify via LLM")

    # Process in batches.
    retry_queue: list[tuple[int, str, dict]] = []

    for batch_start in range(0, len(uncached), _BATCH_SIZE):
        batch = uncached[batch_start : batch_start + _BATCH_SIZE]
        batch_rows = [item[2] for item in batch]

        try:
            llm_results = _classify_batch_llm(batch_rows)
        except _FatalAPIError as exc:
            print(f"[taxonomy] Fatal API error, stopping: {exc}")
            break

        batch_failed = []
        for (idx, key, row), result in zip(batch, llm_results):
            if result is not None:
                _save_cached(key, result)
                results[key] = result
            else:
                batch_failed.append((idx, key, row))

        if batch_failed:
            retry_queue.extend(batch_failed)

        # Rate limit between batches (skip after the last one).
        remaining = len(uncached) - (batch_start + len(batch))
        if remaining > 0:
            time.sleep(_RATE_LIMIT_DELAY)

    # Retry failed products once (handles transient JSON parse errors).
    if retry_queue:
        print(f"[taxonomy] Retrying {len(retry_queue)} failed products...")
        time.sleep(_RATE_LIMIT_DELAY)
        for retry_start in range(0, len(retry_queue), _BATCH_SIZE):
            batch = retry_queue[retry_start : retry_start + _BATCH_SIZE]
            batch_rows = [item[2] for item in batch]
            try:
                llm_results = _classify_batch_llm(batch_rows)
            except _FatalAPIError:
                break
            for (_, key, _row), result in zip(batch, llm_results):
                if result is not None:
                    _save_cached(key, result)
                    results[key] = result
            remaining = len(retry_queue) - (retry_start + len(batch))
            if remaining > 0:
                time.sleep(_RATE_LIMIT_DELAY)

    newly_classified = sum(
        1 for (_, key, _) in uncached if key in results
    )
    failed = len(uncached) - newly_classified
    print(f"[taxonomy] Classified {newly_classified}, failed {failed}")

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_taxonomy(
    df: pd.DataFrame,
    use_llm: bool = True,
) -> pd.DataFrame:
    """Classify all products in a DataFrame.

    Adds columns: taxonomy_label, taxonomy_family, taxonomy_subfamily,
    taxonomy_confidence, taxonomy_source.

    Args:
        df: Product DataFrame.  Expected columns include at minimum
            ``store`` and ``name``.  ``category``, ``subcategory``, and
            ``ingredients`` are used when available.
        use_llm: When False, every product receives the fallback result
            (pantry.pasta_noodles, confidence=0.0, source="fallback").
            Useful for testing without API access.

    Returns:
        The input DataFrame with five new taxonomy columns appended.
    """
    df = df.copy()

    # Build lightweight row dicts for hashing / prompt construction.
    row_dicts: list[dict] = []
    for _, row in df.iterrows():
        row_dicts.append({
            "store": row.get("store", ""),
            "name": row.get("name", ""),
            "category": row.get("category", ""),
            "subcategory": row.get("subcategory", ""),
            "ingredients": row.get("ingredients", ""),
        })

    if use_llm:
        # Run LLM classification (with caching).
        key_to_result = _classify_all_llm(row_dicts)
    else:
        key_to_result = {}

    # Assign results to each row.
    labels: list[str] = []
    families: list[str] = []
    subfamilies: list[str] = []
    confidences: list[float] = []
    sources: list[str] = []

    llm_count = 0
    fallback_count = 0
    low_confidence_count = 0

    for row_dict in row_dicts:
        key = _cache_key(row_dict)
        result = key_to_result.get(key)

        if result is None:
            result = _default_result()
            fallback_count += 1
        else:
            llm_count += 1
            if result.confidence < 0.5:
                low_confidence_count += 1

        labels.append(result.label)
        families.append(result.family)
        subfamilies.append(result.subfamily)
        confidences.append(result.confidence)
        sources.append(result.source)

    df["taxonomy_label"] = labels
    df["taxonomy_family"] = families
    df["taxonomy_subfamily"] = subfamilies
    df["taxonomy_confidence"] = confidences
    df["taxonomy_source"] = sources

    # Summary statistics.
    total = len(df)
    print(f"\n[taxonomy] Classification summary ({total} products):")
    print(f"  LLM classified : {llm_count}")
    print(f"  Fallback       : {fallback_count}")
    if llm_count > 0:
        print(f"  Low confidence : {low_confidence_count} (< 0.50)")

    return df
