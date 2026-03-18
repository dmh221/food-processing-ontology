"""Micro-label classifier: a 4th taxonomy level added to the clean CSV export.

Assigns a `micro_label` (e.g. "ground_coffee", "tonic_water", "peanut_butter")
and a `micro_label_method` ("regex", "llm", or "fallback") to each product.

Does NOT change scoring, parquet output, or any existing taxonomy columns.
Results are cached in output/micro_label_cache/ by SHA-256 hash of
(version + name + ingredients_norm) — store-agnostic.

Phase 1: Regex rules for ~25 predictable subfamilies.
Phase 2: LLM (Claude Haiku, cached) for ~16 brand-heavy subfamilies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import anthropic


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MICRO_LABEL_VERSION = "v1.0"
_MICRO_CACHE_DIR = Path(__file__).parent.parent / "output" / "micro_label_cache"
_MODEL = "claude-haiku-4-5-20251001"
_BATCH_SIZE = 20
_RATE_LIMIT_DELAY = 0.5  # seconds between LLM batches

# Subfamilies where the taxonomy label itself is the micro_label (no further split needed)
_PASSTHROUGH_SUBFAMILIES: set[str] = {
    "plant_protein.tofu",
    "plant_protein.tempeh",
    "plant_protein.seitan",
}

# Subfamilies that should never receive LLM classification
_NON_FOOD_SUBFAMILIES: set[str] = {
    "non_food.pet",
    "non_food.floral",
    "non_food.household",
}

# ---------------------------------------------------------------------------
# Allowed micro-labels per subfamily (used to validate LLM responses)
# ---------------------------------------------------------------------------

MICRO_LABELS: dict[str, list[str]] = {
    # Drinks
    "drinks.coffee_tea": [
        "ground_coffee", "whole_bean_coffee", "instant_coffee", "coffee_pods",
        "cold_brew", "espresso", "coffee_concentrate", "coffee_powder_mix", "rtd_coffee",
        "loose_leaf_tea", "tea_bags", "tea_pods", "iced_tea_mix",
        "matcha", "herbal_tea", "chai", "other",
    ],
    "drinks.water_seltzers": [
        "still_water", "sparkling_water", "tonic_water", "coconut_water",
        "flavored_water", "other",
    ],
    "drinks.sodas_mixers": [
        "cola", "diet_soda", "ginger_ale", "root_beer", "lemon_lime_soda",
        "orange_soda", "cream_soda", "fruit_soda", "hard_seltzer",
        "tonic_water", "mixer", "soda", "energy_soda", "sparkling_water", "sports_drink", "other",
    ],
    "drinks.juice": [
        "orange_juice", "apple_juice", "cranberry_juice", "grape_juice",
        "vegetable_juice", "mixed_fruit_juice", "juice_blend",
        "juice_concentrate", "cold_pressed_juice", "coconut_water", "other",
    ],
    "drinks.kombucha": ["kombucha", "jun_tea", "probiotic_soda", "other"],
    "drinks.functional": [
        "energy_drink", "sports_drink", "protein_shake", "probiotic_drink",
        "electrolyte_drink", "nootropic_drink", "other",
    ],

    # Dairy & Eggs
    "dairy_eggs.milk_cream": [
        "whole_milk", "reduced_fat_milk", "skim_milk", "heavy_cream",
        "half_and_half", "coffee_creamer", "lactose_free_milk",
        "flavored_milk", "buttermilk", "other",
    ],
    "dairy_eggs.plant_based": [
        "oat_milk", "almond_milk", "soy_milk", "coconut_milk", "cashew_milk",
        "pea_milk", "plant_yogurt", "plant_creamer", "other",
    ],
    "dairy_eggs.cheese": [
        "cheddar", "mozzarella", "parmesan", "swiss_gruyere", "brie_camembert",
        "blue_cheese", "goat_cheese", "cottage_cheese", "cream_cheese",
        "shredded_blend", "sliced_cheese", "specialty_cheese", "other",
    ],
    "dairy_eggs.cultured_dairy": [
        "greek_yogurt", "regular_yogurt", "drinkable_yogurt", "kefir",
        "skyr", "sour_cream", "creme_fraiche", "cottage_cheese", "other",
    ],
    "dairy_eggs.eggs_butter": ["butter", "margarine_spread", "ghee", "eggs", "other"],

    # Baked Goods
    "baked_goods.bread": [
        "sandwich_bread", "sourdough", "whole_grain_bread", "gluten_free_bread",
        "flatbread", "focaccia", "rye_bread", "challah", "other",
    ],
    "baked_goods.bagels_breakfast": [
        "bagel", "english_muffin", "breakfast_biscuit", "breakfast_bar",
        "waffle_pancake", "other",
    ],
    "baked_goods.tortillas": [
        "flour_tortilla", "corn_tortilla", "low_carb_wrap", "egg_wrap", "other",
    ],
    "baked_goods.croissants_pastries": [
        "croissant", "donut", "toaster_pastry", "danish",
        "cinnamon_roll", "rugelach", "puff_pastry",
        "muffin", "scone", "biscuit", "waffle_pastry", "coffee_cake", "other",
    ],
    "baked_goods.breakfast_desserts": [
        "croissant", "donut", "toaster_pastry", "danish",
        "cinnamon_roll", "rugelach", "puff_pastry",
        "muffin", "scone", "biscuit", "waffle_pastry", "coffee_cake", "other",
    ],
    "baked_goods.buns_rolls": [
        "hamburger_bun", "hot_dog_bun", "dinner_roll", "slider_bun",
        "pretzel_bun", "other",
    ],
    "baked_goods.dough": ["pizza_dough", "pie_crust", "biscuit_dough", "other"],
    "baked_goods.gluten_free": [
        "gluten_free_bread", "gluten_free_pasta", "gluten_free_wrap",
        "gluten_free_baked", "other",
    ],

    # Desserts
    "desserts.baked": [
        "cookies", "brownies", "cakes_cupcakes", "cupcakes", "muffins", "pies_tarts",
        "sandwich_cookies", "donuts", "pastries", "other",
    ],
    "desserts.frozen": [
        "ice_cream", "frozen_yogurt", "sorbet", "frozen_novelty",
        "frozen_fruit_bar", "other",
    ],
    "desserts.candy": [
        "gummy_candy", "hard_candy", "sour_candy", "chewy_candy",
        "lollipop", "candy_bar", "licorice", "marshmallow", "candy_coated",
        "gummies", "fruit_snacks", "chocolate", "other",
    ],
    "desserts.chocolate": [
        "dark_chocolate_bar", "milk_chocolate_bar", "chocolate_bar", "chocolate_baking",
        "chocolate_cups", "chocolate_truffles", "chocolate_coated_nuts",
        "white_chocolate", "other",
    ],

    # Meat
    "meat.beef": [
        "ground_beef", "steak", "roast", "burger_patty", "beef_ribs", "stew_beef", "other",
    ],
    "meat.poultry": [
        "chicken_breast", "chicken_thigh", "ground_chicken", "whole_chicken",
        "chicken_wings", "turkey", "duck", "other",
    ],
    "meat.pork": [
        "pork_chop", "pork_tenderloin", "ground_pork", "pork_ribs",
        "pork_roast", "pulled_pork", "other",
    ],
    "meat.lamb_game": ["lamb_chop", "lamb_ground", "lamb_rack", "game_meat", "other"],
    "meat.bacon_sausages": [
        "bacon", "breakfast_sausage", "italian_sausage", "smoked_sausage",
        "pepperoni", "hot_dog", "summer_sausage", "other",
    ],
    "meat.deli_charcuterie": [
        "sliced_turkey", "sliced_chicken", "sliced_ham",
        "salami_prosciutto", "roast_beef", "pate_mousse", "bologna", "other",
    ],

    # Seafood
    "seafood.fish": [
        "salmon", "tuna", "tilapia", "cod", "halibut", "mahi_mahi",
        "trout", "catfish", "other",
    ],
    "seafood.shellfish": ["shrimp", "crab", "lobster", "mussels", "clams", "scallops", "other"],
    "seafood.tinned": [
        "canned_tuna", "canned_salmon", "canned_sardine", "canned_mackerel",
        "canned_anchovy", "canned_shellfish", "other",
    ],
    "seafood.smoked": [
        "smoked_salmon", "smoked_trout", "smoked_mackerel",
        "smoked_sturgeon", "smoked_oysters", "smoked_sardines", "smoked_mussels", "other",
    ],

    # Plant protein (only meat_substitute gets split; others are pass-through)
    "plant_protein.meat_substitute": [
        "plant_burger", "plant_ground", "plant_strips", "plant_nuggets",
        "plant_sausage", "other",
    ],

    # Pantry
    "pantry.pasta_noodles": [
        "white_pasta", "whole_wheat_pasta", "legume_pasta",
        "gluten_free_pasta", "asian_noodles", "egg_noodles", "other",
    ],
    "pantry.grains_beans": [
        "rice", "oats", "quinoa", "lentils", "dried_beans", "couscous", "polenta", "other",
    ],
    "pantry.chips_crackers": [
        "potato_chips", "tortilla_chips", "pretzels", "rice_cakes",
        "crackers", "popcorn", "pork_rinds", "seaweed_snacks", "veggie_chips",
        "cheese_puffs", "snack_mix", "other",
    ],
    "pantry.dried_fruits_nuts": [
        "dried_fruit", "mixed_nuts", "trail_mix", "seeds", "candied_nuts", "other",
    ],
    "pantry.granola_cereals": [
        "cold_cereal", "granola", "instant_oatmeal", "rolled_oats", "muesli",
        "hot_cereal_mix", "other",
    ],
    "pantry.bars": [
        "protein_bar", "granola_bar", "energy_bar",
        "meal_replacement_bar", "fruit_bar", "nut_bar", "other",
    ],
    "pantry.jerky": [
        "beef_jerky", "turkey_jerky", "salmon_jerky", "other_jerky", "other",
    ],
    "pantry.pickled_fermented": [
        "pickles", "olives", "kimchi", "sauerkraut", "other_pickled", "other",
    ],
    "pantry.oil_vinegar_spices": [
        "olive_oil", "vegetable_oil", "vinegar", "spice_single", "spice_blend",
        "salt", "other",
    ],
    "pantry.baking_ingredients": [
        "flour", "sugar", "leavening", "chocolate_chips", "baking_mix",
        "extracts_flavoring", "cocoa_cacao", "cornmeal", "bran_wheat_germ", "other",
    ],
    "pantry.condiments_dressings": [
        "pasta_sauce", "ketchup", "mustard", "hot_sauce", "soy_sauce",
        "salad_dressing", "bbq_sauce", "marinade", "gravy", "alfredo_sauce",
        "pesto", "mayo", "salsa", "chili_sauce", "tahini", "vinegar",
        "syrup_topping", "relish", "cooking_paste", "dipping_sauce", "other",
    ],
    "pantry.honey_syrups": [
        "honey", "maple_syrup", "agave", "chocolate_syrup", "flavored_syrup", "other",
    ],
    "pantry.jams_nut_butters": [
        "peanut_butter", "almond_butter", "cashew_butter", "sunflower_butter",
        "tahini", "hazelnut_spread", "mixed_nut_butter", "seed_butter",
        "jam_jelly", "fruit_spread", "other",
    ],
    "pantry.canned_goods": [
        "canned_beans", "canned_soup", "canned_tomatoes",
        "canned_fruit", "canned_vegetables", "canned_fish", "canned_broth", "other",
    ],
    "pantry.stocks": [
        "chicken_broth", "beef_broth", "vegetable_broth",
        "bone_broth", "bouillon", "dashi", "fish_broth", "seafood_broth", "demi_glace", "other",
    ],

    # Composite
    "composite.meals_entrees": [
        "frozen_entree", "fresh_prepared_entree", "bowl", "burrito",
        "pasta_dish", "soup_entree", "stir_fry", "rotisserie", "ramen", "other",
    ],
    "composite.sides_prepared": [
        "fries_potato", "rice_dish", "pasta_side", "grain_side",
        "soup_side", "noodle_dish", "other",
    ],
    "composite.sandwiches_wraps": [
        "sandwich", "wrap_burrito", "lunchable", "snack_plate", "other",
    ],
    "composite.soups_ready": [
        "tomato_soup", "chicken_soup", "lentil_soup",
        "potato_soup", "bisque", "chili", "other",
    ],
    "composite.salads_prepared": [
        "leafy_greens", "salad_kit", "prepared_salad", "coleslaw", "other",
    ],
    "composite.dips_spreads": [
        "salsa", "hummus", "guacamole", "queso", "tapenade", "bean_dip",
        "spinach_dip", "yogurt_dip", "butter_spread", "chutney", "cream_cheese", "other",
    ],
    "composite.pizza": ["frozen_pizza", "pizza_kit", "mini_pizza", "pizza_pocket", "other"],

    # Produce
    "produce.fruit": ["fresh_fruit", "cut_fruit", "other"],
    "produce.vegetable": ["fresh_vegetable", "cut_vegetable", "other"],
    "produce.herbs_aromatics": ["fresh_herb", "garlic_onion", "other"],
}


# ---------------------------------------------------------------------------
# Regex rules (Phase 1) — first-match-wins per subfamily
# ---------------------------------------------------------------------------

def _r(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# Each entry: (compiled_pattern, micro_label)
# Applied to product name only (ingredients_norm consulted only where noted).
_REGEX_RULES: dict[str, list[tuple[re.Pattern, str]]] = {

    "drinks.water_seltzers": [
        (_r(r"\btonic\b"), "tonic_water"),
        (_r(r"\bcoconut\s+water\b"), "coconut_water"),
        # Named sparkling/seltzer brands
        (_r(r"\bsparkling\b|\bbubbly\b|\beffervescent\b|\bseltzer\b|\bpolar\s+seltzer\b|\bhal.s\b|\bla\s+croix\b|\bbubly\b|\bperrier\b|\bpellegrino\b|\bgerolsteiner\b|\bsparkling\s+mineral\b|\bcarbonated\s+water\b"), "sparkling_water"),
        # Lemon Perfect / fruit-infused / zero-sugar waters
        (_r(r"\blemon\s+perfect\b|\blemon\s+water\b|\bflavored\b|\binfused\b|\bessence\b|\bhint\b|\bzero\s+sugar\s+water\b|\bfruit.*water\b|\bwater.*fruit\b"), "flavored_water"),
        # Water enhancers / powder mixes that land here
        (_r(r"\bwater\s+enhancer\b|\bliquid\s+water\s+enhancer\b|\bdrop\b.*\bwater\b|\bwater\s+drops?\b|\bwater\s+flavoring\b|\bstur\b|\bmio\b|\bcirkul\b|\btrue\s+lemon\b|\btrue\s+lime\b|\btrue\s+orange\b|\bpowder\b.*\bhydrat\b|\bthird\s+wave\s+water\b|\bespresso\s+profile\b|\bcoffee\s+profile\b"), "other"),
        # Named still water brands + alkaline / distilled / purified + brand catch-alls
        (_r(r"\bfiji\b|\bsmartwater\b|\bvolvic\b|\bevian\b|\bdassani\b|\bdaanis\b|\bdasani\b|\baqua\s+panna\b|\bpenta\b|\bcore\s+water\b|\balkaline\b|\balkaline\s+ph\b|\belectrolyte\b.*\bwater\b|\bdistilled\b|\bpurified\b|\bspring\b|\bmineral\s+water\b|\bfiltered\b|\bglacier\b|\bwell\s+water\b|\bstill\b|\bevamor\b|\bartesian\b|\bliquid\s+death\b|\baquafina\b|\bvitaminwater\b|\bvitamin\s+water\b|\bblk\s+water\b|\bwaiakea\b|\bice\s+mountain\b|\bozarka\b|\bzephyrhills\b|\bpoland\s+spring\b|\bsaratoga\b|\bnessel\b|\bpure\s+life\b|\bwater\b"), "still_water"),
    ],

    "drinks.sodas_mixers": [
        # tonic is a hard override — never "mixer"
        (_r(r"\btonic\b"), "tonic_water"),
        # Club soda
        (_r(r"\bclub\s+soda\b"), "sparkling_water"),
        # Cola family
        (_r(r"\bcola\b|coca.cola|pepsi|\bdr\.?\s*pepper\b|\bpibb\b|\bcheerwine\b"), "cola"),
        # Diet/zero soda — check before generic cola
        (_r(r"\bdiet\b.*\bsoda\b|\bsoda\b.*\bdiet\b|\bzero\b.*\bsug|\bsugar.free\b.*\bsoda|\bdiet\s+coke\b"), "diet_soda"),
        # Ginger
        (_r(r"\bginger\s+ale\b|\bginger\s+beer\b"), "ginger_ale"),
        # Root beer
        (_r(r"\broot\s+beer\b"), "root_beer"),
        # Lemon-lime
        (_r(r"\blemon.lime\b|\bsprite\b|\bsierra\s+mist\b|\bstarry\b|\b7.?up\b|\bmtn\s+dew\b|\bmountain\s+dew\b|\bsquirt\b|\bfresca\b"), "lemon_lime_soda"),
        # Orange soda
        (_r(r"\borange\s+soda\b|\bfanta\b|\bsunkist\b|\bmandarin\b.*\bsoda\b|\baranciata\b|\borangeade\b"), "orange_soda"),
        # Cream soda
        (_r(r"\bcream\s+soda\b|\bvanilla\s+cream\b.*\bsoda\b|\bcreme\b.*\bsoda\b"), "cream_soda"),
        # Hard seltzer
        (_r(r"\bhard\s+selt|white\s+claw|truly\s+hard|bon\s+\&\s+viv|press\s+hard\b"), "hard_seltzer"),
        # Non-alcoholic beer/wine/spirits (mocktails, NA beer)
        (_r(r"\bnon.alcoholic\b|\bna\s+beer\b|\bna\s+ipa\b|\balcohol.removed\b|\bzero\s+proof\b|\bmocktail\b|\baperif\b|\bspritz\b|\baperol\b|\bnon.alc\b"), "mixer"),
        # Cocktail mixers
        (_r(r"\bmargarita\s+mix\b|\bbloody\s+mary\b|\bsour\s+mix\b|\bcocktail\s+mix\b|\bdaiquiri\s+mix\b|\bpina\s+colada\s+mix\b|\bgrenadine\b|\bbitters\b|\bcream\s+of\s+coconut\b"), "mixer"),
        # Drink mixes / water enhancers / powders
        (_r(r"\bdrink\s+mix\b|\bwater\s+enhancer\b|\bliquid\s+enhancer\b|\bdrink\s+powder\b|\bkool.aid\b|\bcrystal\s+light\b|\bmio\b|\bstur\b|\btrue\s+lemon\b|\bwyler\b|\bcountry\s+time\b|\bhawaiian\s+punch\b|\bcirkul\b|\b4c\b|\bclear\s+theory\b"), "mixer"),
        # Sparkling water / mineral water that landed in sodas_mixers (Fever-Tree sparkling, Perrier, etc.)
        (_r(r"\bfever.tree\b|\bperrier\b|\bpellegrino\b|\bgerolsteiner\b|\bsparkling\s+(?:mineral\s+)?water\b|\bmineral\s+water\b"), "other"),
        # Energy / functional drinks that landed in sodas_mixers (Red Bull, Monster, Alani Nu, etc.)
        (_r(r"\bred\s+bull\b|\bmonster\s+energy\b|\balani\s+nu\b|\bbang\s+energy\b|\bcellucor\b|\bc4\s+energy\b|\bnos\s+energy\b|\bfull\s+throttle\b|\bamp\s+energy\b|\bmountain\s+dew\s+energy\b|\bgame\s+fuel\b|\bredbull\b|\bmonster\b.*\benergy\b"), "other"),
        # Wine / beer / hard cider that landed in sodas_mixers — leave as other
        (_r(r"\bwine\b|\brosé\b|\brose\s+wine\b|\bchampagne\b|\bprosecco\b|\bcava\b|\bsparkling\s+wine\b|\bstella\s+rosa\b|\bbeer\b|\bale\b|\bipa\b|\blager\b|\bstout\b|\bporter\b|\bwheat\s+beer\b|\bhard\s+cider\b|\bcider\b(?!.*mix)"), "other"),
        # Prebiotic/functional sodas (Olipop, Poppi, Culture Pop, Cove, Slice, Bloom Pop)
        (_r(r"\bprebiotic\s+soda\b|\bolipop\b|\bpoppi\b|\bculture\s+pop\b|\bcove\b.*\bsoda\b|\bslice\b.*\bsoda\b|\bbloom\s+pop\b|\bde\s+la\s+calle\b|\btepache\b"), "fruit_soda"),
        # Generic fruit soda / sparkling juice soda
        (_r(r"\bfruit\s+soda\b|\bjuice\s+soda\b|\bsparkling.*juice\b|\bbubbly.*juice\b|\blemonade\b.*\bsoda\b|\bsparkling\b.*\blemonade\b|\bsanpellegrino\b|\bjarritos\b|\bvirgil\b|\bboylan\b|\bsprecher\b|\bramune\b|\bbawls\b|\bunited\s+soda\b|\bfrizzante\b|\bbelvoir\b|\bgreen\s+bee\b|\bsaranac\b.*\bsoda\b"), "fruit_soda"),
        # Sparkling tea / botanical sparkling (Tost, Ghia)
        (_r(r"\bsparkling\s+(?:white\s+)?tea\b|\bghia\b|\ble\s+fizz\b|\baperiti\b.*\bsparkling\b|\bde\s+soi\b|\bpurple\s+lune\b"), "mixer"),
        # Milkis / Korean cream soda / flavored milk soda
        (_r(r"\bmilkis\b|\blotte\b"), "cream_soda"),
        # Fever-Tree (non-tonic) — sparkling lemon, yuzu, grapefruit
        (_r(r"\bfever.tree\b"), "mixer"),
        # RYZE mushroom coffee sticks misrouted here
        (_r(r"\bryze\b|\bmushroom\s+coffee\b.*\bsticks?\b"), "other"),
        # Dunkin' coffee pods misrouted here
        (_r(r"\bdunkin\b|\bk.?cup\b.*\bcoffee\b|\bcoffee\s+pods?\b.*\bk.?cup\b"), "other"),
        # Wines / champagne / Stella Rosa misrouted
        (_r(r"\bstella\s+rosa\b|\brisata\b|\bmoscato\b|\bwine\b.*\bbottle\b|\bred\s+blend\s+wine\b|\bwine\b.*\bml\b"), "other"),
        # Beer misrouted  
        (_r(r"\bcorona\b.*\blager\b|\bcorona\b.*\bbeer\b"), "other"),
        # Chestnuts / food items misrouted
        (_r(r"\bchestnuts?\b|\bgefen\b"), "other"),
        # Espresso martini mix
        (_r(r"\bespresso\s+martini\b"), "mixer"),
        # A-Sha boba milk tea (Asian tea drinks)
        (_r(r"\ba.?sha\s+foods?\b|\bhello\s+kitty\b.*\bboba\b|\bboba\s+milk\s+tea\b"), "other"),
        # Alani Nu energy drink
        (_r(r"\balani\s+nu\b|\bpink\s+slush\s+energy\b"), "energy_soda"),
        # Canada Dry fruit splash / ginger ale
        (_r(r"\bcanada\s+dry\b.*\bfruit\s+splash\b|\bcanada\s+dry\b.*\bsoda\b"), "soda"),
        # Fonti Di Crodo limonata (Italian sparkling)
        (_r(r"\bfonti\s+di\s+crodo\b|\blimonata\b"), "soda"),
        # Gatorade sports drinks
        (_r(r"\bgatorade\b|\bglacier\s+freeze\b|\bg\s+zero\b|\bgatorade\s+zero\b"), "sports_drink"),
        # Iberia Jamaican kola / Ting grapefruit soda
        (_r(r"\biberia\b.*\bkola\b|\bting\b.*\bgrapefruit\b.*\bsoda\b|\bjamaican\s+kola\b"), "soda"),
        # Mingle Mocktails
        (_r(r"\bmingle\s+mocktails?\b|\bcranberry\s+cosmo\b|\bcucumber\s+melon\s+mojito\b"), "mixer"),
        # Monster Energy
        (_r(r"\bmonster\s+energy\b|\bmonster\b.*\bzero\s+ultra\b"), "energy_soda"),
        # Mott's Yoo-hoo chocolate drink
        (_r(r"\byoo.hoo\b|\bmott.?s\b.*\bstrawberry\s+chocolate\b"), "other"),
        # POWERADE sports drink
        (_r(r"\bpowerade\b"), "sports_drink"),
        # Red Bull energy drinks
        (_r(r"\bred\s+bull\b"), "energy_soda"),
        # Risata moscato d'asti (wine)
        (_r(r"\brisata\b|\bmoscato\s+d.?asti\b"), "other"),
        # Saranac shirley temple / soft drinks
        (_r(r"\bsaranac\b|\bshirley\s+temple\b"), "soda"),
        # Tropical Fantasy / DG Jamaican champagne kola
        (_r(r"\btropical\s+fantasy\b|\bdg\s+jamaican\b|\bjamican\s+champagne\b|\bdg\s+pineapple\b"), "soda"),
        # United Sodas of America
        (_r(r"\bunited\s+sodas?\s+of\s+america\b|\bunited\s+shoes\b.*\bsoda\b"), "soda"),
        # vitaminwater
        (_r(r"\bvitaminwater\b|\bvitamin\s+water\b.*\baçai\b|\bvitamin\s+water\b.*\bpomegranate\b"), "other"),
        # Woodford Reserve bourbon cherries (misrouted)
        (_r(r"\bwoodford\s+reserve\b|\bbourbon\s+cherries?\b"), "other"),
    ],

    "drinks.juice": [
        # Coconut water — appears in juice subfamily (different from water_seltzers)
        (_r(r"\bcoconut\s+water\b|\bcoconut\s+drink\b|\bvita\s+coco\b|\bharmless\s+harvest\b|\bc2o\b|\bonce\s+upon\s+a\s+coconut\b"), "coconut_water"),
        # Lemonade
        (_r(r"\blemonade\b|\blemon\s+juice\b|\blime\s+juice\b"), "mixed_fruit_juice"),
        # Watermelon water (WTRMLN WTR brand + generic)
        (_r(r"\bwtrmln\b|\bwatermelon\s+water\b|\bwatermelon\s+wtr\b"), "mixed_fruit_juice"),
        # Ginger soother / ginger beverage / ginger lemonade
        (_r(r"\bginger\s+soother\b|\bginger\s+lemonade\b|\bgingerade\b|\bginger\s+beverage\b"), "mixed_fruit_juice"),
        # Agua fresca
        (_r(r"\bagua\s+fresca\b|\bagua\s+de\s+\w+\b|\bfresca\b.*\bdrink\b"), "mixed_fruit_juice"),
        # Cold-pressed / green / functional juices (Bolthouse Green Goodness, pressed green)
        (_r(r"\bcold.press\b|\bpressed\s+juice\b|\bgreen\s+juice\b|\bgreens\s+juice\b|\bcelery.*juice\b|\bbeet.*juice\b|\bginger.*juice\b|\bturmeric.*juice\b|\bjuice\s+boost\b|\bgreen\s+goodness\b|\bbolthouse\b|\bgood\s+greens\b"), "cold_pressed_juice"),
        # Tart cherry concentrate / cherry beverage
        (_r(r"\btart\s+cherry\s+(?:bev|concentrate)\b|\bcherry\s+tart\b"), "mixed_fruit_juice"),
        # Single-fruit juices — concentrated/frozen
        (_r(r"\bjuice\s+concentrate\b|\bconcentrated\s+juice\b|\bfrozen\s+concentrated\b"), "juice_concentrate"),
        # Orange
        (_r(r"\borange\s+juice\b|\boj\b|\btangerine\s+juice\b|\bgrapefruit\s+juice\b"), "orange_juice"),
        # Apple / cider
        (_r(r"\bapple\s+juice\b|\bapple\s+cider\b|\bcider\b|\bsparkling\s+cider\b|\bapplesauce\b"), "apple_juice"),
        # Cranberry
        (_r(r"\bcranberry\s+juice\b|\bcranberry.*pomegranate\b"), "cranberry_juice"),
        # Grape
        (_r(r"\bgrape\s+juice\b|\bgrape\b.*\bjuice\b|\bconcord\s+grape\b"), "grape_juice"),
        # Vegetable
        (_r(r"\bvegetable\s+juice\b|\bv8\b|\btomato\s+juice\b|\bcarrot\s+juice\b|\bcarrot\b.*\bjuice\b"), "vegetable_juice"),
        # Prune / tart cherry / single fruit
        (_r(r"\bprune\s+juice\b|\btart\s+cherry\b|\bcherry\s+juice\b|\bpomegranate\s+juice\b|\bblueberry\s+juice\b|\bpineapple\s+juice\b|\bpear\s+juice\b|\bmango.*juice\b|\bpapaya.*juice\b|\bpeach.*juice\b|\bapricot.*juice\b|\bblood\s+orange.*juice\b|\baloe.*juice\b|\belderberry.*juice\b|\bwatermelon.*juice\b"), "mixed_fruit_juice"),
        # Smoothies / smoothie blends
        (_r(r"\bsmoothie\b|\bsmoothie\s+mix\b|\bfruit\s+smoothie\b|\bgreen\s+smoothie\b"), "mixed_fruit_juice"),
        # Nectar (mango nectar, guava nectar, etc.)
        (_r(r"\bnectar\b"), "mixed_fruit_juice"),
        # Juice cocktail / drink (not 100% juice but still juice-family)
        (_r(r"\bjuice\s+cocktail\b|\bjuice\s+drink\b|\bfruit\s+drink\b|\bfruit\s+beverage\b|\bade\b(?!.*lemon)"), "mixed_fruit_juice"),
        # Açaí / exotic fruits
        (_r(r"\ba[çc]a[íi]\b|\bguava\b|\bpassion\s+fruit\b|\bdragon\s+fruit\b|\blychee\b|\btamarind\b"), "mixed_fruit_juice"),
        # Mixed / blend / punch
        (_r(r"\bmixed\s+fruit\b|\bfruit\s+punch\b|\btropical\s+juice\b|\bjuice\s+blend\b|\bblend.*juice\b|\bgreens\b.*\bjuice\b|\bfruit\s+juice\b"), "mixed_fruit_juice"),
        # Fallback: anything with "juice" in the name
        (_r(r"\bjuice\b"), "mixed_fruit_juice"),
        # Limeade / frozen limeade
        (_r(r"\blimeade\b"), "mixed_fruit_juice"),
        # Sicilia squeeze / lemon/lime squeeze bottles
        (_r(r"\bsicilia\b|\bsqueeze\b.*\blemon\b|\blemon\s+squeeze\b|\blime\s+squeeze\b|\bingrilli\b|\borganic\s+ginger\s+squeeze\b"), "mixed_fruit_juice"),
        # GoGo squeez fruitz
        (_r(r"\bgogo\s+squeez\b|\bfruitz\b"), "mixed_fruit_juice"),
        # Concentrated / organic cranberry
        (_r(r"\bcranberry\s+concentrate\b|\blakewood\b.*\bcranberry\b"), "cranberry_juice"),
        # Pricklee cactus water (misrouted to juice)
        (_r(r"\bpricklee\b|\bcactus\s+water\b"), "juice_blend"),
        # Drink&Play spring water (misrouted to juice)
        (_r(r"\bdrink.*play\b|\bspring\s+water\b.*\bdrink\b"), "other"),
        # OLIPOP misrouted to juice (it's a soda)
        (_r(r"\bolipop\b"), "other"),
        # Peach tea / zero sugar tea
        (_r(r"\bpeach\s+tea\b|\bswoon\b.*\btea\b|\bzero\s+sugar\b.*\btea\b"), "other"),
        # Juic'd Right / pressed juice blends (Wegmans brand)
        (_r(r"\bjuic.?d\s+right\b|\bhoneycrisp\b.*\bjuice\b"), "cold_pressed_juice"),
        # good2grow / kids juice
        (_r(r"\bgood2grow\b|\bspouts\b.*\bjuice\b"), "mixed_fruit_juice"),
        # Lemonade / limeade (Wegmans Organic)
        (_r(r"\borganic\s+limeade\b|\borganic\s+lemonade\b"), "mixed_fruit_juice"),
    ],

    "drinks.coffee_tea": [
        # Coffee — most specific first
        (_r(r"\bwhole\s+bean\b"), "whole_bean_coffee"),
        (_r(r"\bcold\s+brew\b"), "cold_brew"),
        (_r(r"\bespresso\b"), "espresso"),
        (_r(r"\bcoffee\s+concentrate\b|\bconcentrated\s+coffee\b"), "coffee_concentrate"),
        (_r(r"\binstant\s+coffee\b|\bcoffee.*instant\b"), "instant_coffee"),
        (_r(r"\bk.cups?\b|\bcoffee\s+pod\b|\bnespresso\b|\bdolce\s+gusto\b|\bpod\b.*\bcoffee\b|\bkeurig\b|\bsingle\s+serve\b|\bsingle.serve\b|\bpods?\b.*\bcoffee\b|\bcoffee\b.*\bpods?\b|\bcoffee\b.*\bcapsules?\b"), "coffee_pods"),
        (_r(r"\bcoffee\s+mix\b|\bflavored\s+coffee\b|\bmocha\s+mix\b|\bcafe\s+mix\b|\blatte\s+mix\b|\bmushroom\s+coffee\b|\bryze\b|\bfour\s+sigmatic\b|\bom\s+mushroom\b|\badaptogen\s+coffee\b|\bcoffee.*\bsticks?\b"), "coffee_powder_mix"),
        # RTD coffee (bottled/canned) — must check for "bottled" or "ready" or "cold" before "ground"
        (_r(r"\bready.to.drink\s+coffee\b|\brtd\s+coffee\b|\bcanned\s+coffee\b|\bbottled\s+coffee\b|\biced\s+coffee\b"), "rtd_coffee"),
        (_r(r"\bground\s+coffee\b|\bcoffee\s+ground\b|\bgrain\s+beverage\b|\bkaffree\b|\bherbal\s+coffee\b|\badaptogen.*coffee\b|\bcoffee\s+alternative\b|\bcoffee\b(?!.*tea)"), "ground_coffee"),
        # Tea
        (_r(r"\bmatcha\b"), "matcha"),
        (_r(r"\bchai\b"), "chai"),
        # Herbal / wellness teas — brand names: Yogi, Tazo, Traditional Medicinals, Taylors, Steven Smith
        (_r(r"\bherbal\s+tea\b|\bherbal\s+blend\b|\bherbal\s+infusion\b|\btissane\b|\btisane\b|\brooibos\b|\bchamomile\b|\bpeppermint\s+tea\b|\bpeppermint\b|\bhibiscus\s+tea\b|\bechinacea\b|\bginger\s+tea\b|\blemon\s+verbena\b|\bstress\s+ease\b|\bstress.*sleep\b|\btraditional\s+medicinals\b|\byogi\b|\btazo\b|\bherb\s+tea\b|\bmint\s+tea\b|\bspearmint\b|\bpassionfruit\s+tea\b|\bevening\s+blend\b|\bwellness\s+tea\b|\bdetox\s+tea\b|\bimmune\s+tea\b|\bcalm\b.*\btea\b|\brelax\b.*\btea\b|\bsleep\b.*\btea\b|\bearl\s+grey\b|\benglish\s+breakfast\b|\bgreen\s+tea\b|\bwhite\s+tea\b|\bblack\s+tea\b|\boolongs?\b|\brose\s+lemonade\s+tea\b|\byorkshire\b|\bscottish\s+breakfast\b|\bpure\s+assam\b|\bsteven\s+smith\b|\btaylors\s+of\s+harrogate\b|\blemon.*ginger\s+tea\b|\blemon.*orange\s+tea\b"), "herbal_tea"),
        (_r(r"\biced\s+tea\s+mix\b|\bsun\s+tea\b|\bsweet\s+tea\s+mix\b"), "iced_tea_mix"),
        (_r(r"\btea\s+pod\b|\btea.*k.cup\b"), "tea_pods"),
        (_r(r"\bloose\s+leaf\b|\bloose.leaf\b"), "loose_leaf_tea"),
        (_r(r"\btea\s+bag\b|\bteabag\b|\btea\b"), "tea_bags"),
    ],

    "drinks.kombucha": [
        (_r(r"\bjun\s+tea\b|\bjun\b"), "jun_tea"),
        (_r(r"\bprobiotic\s+soda\b|\bcultured\s+soda\b"), "probiotic_soda"),
        (_r(r"\bkombucha\b"), "kombucha"),
    ],

    "dairy_eggs.milk_cream": [
        (_r(r"\bbuttermilk\b"), "buttermilk"),
        (_r(r"\bheavy\s+cream\b|\bwhipping\s+cream\b|\bdouble\s+cream\b"), "heavy_cream"),
        (_r(r"\bhalf\s+(?:and|&)\s+half\b|\bhalf.and.half\b"), "half_and_half"),
        (_r(r"\bcoffee\s+creamer\b|\bcreamer\b|\bnon.dairy\s+creamer\b"), "coffee_creamer"),
        (_r(r"\blactose.free\b|\bdairy.free\s+milk\b"), "lactose_free_milk"),
        (_r(r"\bchocolate\s+milk\b|\bflavored\s+milk\b|\bstrawberry\s+milk\b|\bvanilla\s+milk\b"), "flavored_milk"),
        (_r(r"\bskim\s+milk\b|\bfat.free\s+milk\b|\bnonfat\s+milk\b"), "skim_milk"),
        (_r(r"\breduced.fat\s+milk\b|\b1%\b|\b2%\b|\blow.fat\s+milk\b"), "reduced_fat_milk"),
        (_r(r"\bwhole\s+milk\b|\bfull.fat\s+milk\b"), "whole_milk"),
        # Goat milk / A2 milk / specialty milk
        (_r(r"\bgoat\s+milk\b|\bgoat\s+(?:dairy|cream)\b|\ba2\s+milk\b|\ba2\/a2\b|\ba2.a2\b|\brawmilk\b|\braw\s+milk\b|\bshelf.stable\s+milk\b|\bparmalat\b|\bmilk\s+powder\b|\bdried\s+milk\b|\bcoconut\s+cream\s+powder\b|\bcoconut\s+milk\s+powder\b"), "whole_milk"),
        # Protein milk / blended dairy
        (_r(r"\bprotein\b.*\bmilk\b|\bmilk\b.*\bprotein\b|\brockin.*protein\b|\bensure\b|\bboost\b.*\bdrink\b"), "flavored_milk"),
        # Generic milk catch-all
        (_r(r"\bmilk\b"), "whole_milk"),
    ],

    "dairy_eggs.plant_based": [
        # Yogurt alternatives (check before milk to avoid "almond milk yogurt" → almond_milk)
        (_r(r"\byogurt\s+alternative\b|\byogurt\s+alt\b|\bplant.based\s+yogurt\b|\bnon.dairy\s+yogurt\b|\bdairy.free\s+yogurt\b|\bcoconut\s+yogurt\b|\balmond\s+yogurt\b|\bcultured\s+yogurt\s+alternative\b|\bcashew\s+yogurt\b|\boat\s+yogurt\b|\bsoy\s+yogurt\b|\bcultured\s+coconut\b|\bnon.dairy\s+plant.based\b|\bkite\s+hill\b.*\byogurt\b|\bsigg.s\b.*\bnon.dairy\b|\bcocojune\b|\bcoconut\s+blend\b.*\byogurt\b|\bcoconut.*\byogurt\b|\bwhipped.*coconut\b"), "plant_yogurt"),
        # Creamers (before milks — "nutpods almond+coconut" should be plant_creamer)
        (_r(r"\bcoffee\s+creamer\b|\bnon.dairy\s+creamer\b|\bplant.based\s+creamer\b|\boat\s+creamer\b|\balmond\s+creamer\b|\bnutpods\b|\bcoffee.mate\b|\binternational\s+delight\b|\bcashew\s+creamer\b|\bpea\s+creamer\b|\bcoconut\s+creamer\b|\bcreamer\b"), "plant_creamer"),
        # Vegan butter / margarine alternatives
        (_r(r"\bvegan\s+butter\b|\bvegan\s+salted\s+butter\b|\bvegan\s+cultured\s+butter\b|\bmonty.?s\b|\bmiyoko\b|\bearth\s+balance\b|\bcountry\s+crock\s+plant\b"), "other"),
        # Vegan cheese alternatives (blocks, slices, spreads — Conscious Cultures, Greyday, Nuts for Cheese, Spero, Otsego)
        (_r(r"\bcheese\s+alternative\b|\bcheese\s+style\b|\bvegan\s+cheese\b|\bdairy.free\s+cheese\b|\bparmesan.*alternative\b|\bshredded.*alternative\b|\bcream\s+cheese\s+alternative\b|\bvegan\s+cream\s+cheese\b|\bvegan\s+scallion\s+cream\b|\bplant.based\s+(?:mozzarella|cheddar|parmesan|gouda|brie|cheeze|cream\s+cheese|pimento|philly)\b|\bconscious\s+cultures\b|\bgreyday\b|\bcashew\s+cheeze\b|\bnuts\s+for\s+cheese\b|\bcashew\s+cheese\b|\bcashew.*\bcheese\b|\bspero\s+foods\b|\bspero\b.*\bsunflower\b|\botsego\b|\bvegan.*\bcheeze\b|\bsunflower\s+cream\s+cheese\b"), "other"),
        # Oat milk (brand names: Oatly, Planet Oat, Minor Figures, MALK Oat, Califia Oat)
        (_r(r"\boat\s+milk\b|\boatmilk\b|\boat\s+drink\b|\boatly\b|\bplanet\s+oat\b|\bminor\s+figures\b|\boat\s+based\s+milk\b|\boat\s+malk\b|\bmilked\s+oat(?:s)?\b|\bcalifia\b.*\boat\b|\boat\b.*\bcalifia\b"), "oat_milk"),
        # Almond milk (Elmhurst "Milked Almonds", MALK Almond)
        (_r(r"\balmond\s+milk\b|\balmond\s+drink\b|\balmondmilk\b|\balmond\s+breeze\b|\bsimply\s+almond\b|\bmilked\s+almonds?\b|\balmond\s+malk\b|\belmhurst.*almond\b|\bmalk\b.*\balmond\b|\bmalk\b.*\bvanilla\b"), "almond_milk"),
        # Soy milk
        (_r(r"\bsoy\s+milk\b|\bsoy\s+drink\b|\bsoymilk\b|\bsilk\s+soy\b|\bedensoy\b"), "soy_milk"),
        # Coconut milk / beverage (carton — So Delicious Coconutmilk)
        (_r(r"\bcoconut\s*milk\b|\bcoconut\s+drink\b|\bcoconut\s+beverage\b|\bso\s+delicious\b.*\bcoconut\b|\bcoconutmilk\b"), "coconut_milk"),
        # Cashew milk (Elmhurst Milked Cashews)
        (_r(r"\bcashew\s+milk\b|\bcashew\s+drink\b|\bcashewmilk\b|\bmilked\s+cashews?\b|\bcashew\s+malk\b"), "cashew_milk"),
        # Pea milk
        (_r(r"\bpea\s+milk\b|\bripple\b|\bpea.based\s+milk\b"), "pea_milk"),
        # Macadamia / hazelnut / hemp milk (Milkadamia, Elmhurst Milked Hazelnuts)
        (_r(r"\bmacadamia\s+milk\b|\bmilkadamia\b|\bmilked\s+hazelnuts?\b|\bhazelnut\s+milk\b|\bhemp\s+milk\b|\bhemp\s+drink\b|\brice\s+milk\b|\bflax\s+milk\b|\belmhurst\b|\bwesbo?y\b|\beden.*soy\b|\bsoy\s+original\b|\bsoy\s+vanilla\b"), "other"),
        # Vegan ricotta / cream cheese / feta / sliced cheese alternatives
        (_r(r"\bvegan\s+(?:cream\s+cheese|ricotta|feta|cheddar|provolone|mozzarella|parmesan)\b|\bricotta\s+alternative\b|\bdairy.free\s+(?:cream\s+cheese|ricotta|feta)\b|\bkite\s+hill\s+ricotta\b|\bviolife\b|\bvertage\b|\bspero\b|\bnon.dairy\s+cream\s+cheese\b|\bplant.based\s+(?:cream\s+cheese|feta|cheddar|mozzarella)\b"), "other"),
        # Coconut cream / coconut cream powder (canned — cooking ingredient)
        (_r(r"\bcoconut\s+cream\b(?!\s+powder)|\borganic\s+coconut\s+cream\b"), "coconut_milk"),
        # Generic plant milk catch-all
        (_r(r"\bplant\s+milk\b|\bplant.based\s+milk\b|\bnut\s+milk\b|\bmilk\s+alternative\b|\bdairy.free\s+milk\b|\bmilked\b|\bmalk\b"), "other"),
        # Conscious Cultures plant-based maverick cheese
        (_r(r"\bconscious\s+cultures\b|\bmaverick\s+cheese\b"), "other"),
        # Country Crock original spread
        (_r(r"\bcountry\s+crock\b.*\boriginal\s+spread\b|\bcountry\s+crock\b.*\bspread\s+tub\b"), "other"),
        # Earth Balance plant butter spread sticks
        (_r(r"\bearth\s+balance\b|\bplant\s+butter\b.*\bspread\b"), "other"),
        # Eden Foods soy original / ultra soy
        (_r(r"\beden\s+foods\b|\bedensoy\b|\beden.*original.*soy\b|\bultra\s+soy\b"), "soy_milk"),
        # Elmhurst milked hazelnuts / walnuts
        (_r(r"\belmhurst\b.*\bhazelnuts?\b|\belmhurst\b.*\bwalnuts?\b|\bmilked\s+hazelnuts?\b|\bwalnut\s+barista\b"), "other"),
        # Favorite Day coconut whipped topping
        (_r(r"\bfavorite\s+day\b.*\bcoconut\s+whipped\b|\bnon.dairy\s+topping\b|\bcoconut\s+whipped\b"), "other"),
        # Field Roast Chao slices (vegan cheese)
        (_r(r"\bfield\s+roast\b.*\bchao\b|\bchao\s+slices?\b|\bchao\s+cheese\b|\bchao.*creamy\s+original\b"), "other"),
        # Follow Your Heart vegan parmesan shredded
        (_r(r"\bfollow\s+your\s+heart\b.*\bparmesan\b|\bdairy\s+free\b.*\bvegan\b.*\bparmesan\b|\bvegan\b.*\bparmesan.*shredded\b"), "other"),
        # Greyday blue vegan cashew cheeze
        (_r(r"\bgreyday\b|\bblue\s+vegan\s+cashew\b"), "other"),
        # Imperial vegetable oil spread sticks
        (_r(r"\bimperial\b.*\bvegetable\s+oil\s+spread\b"), "other"),
        # Just Egg plant-based (can land in plant_based section)
        (_r(r"\bjust\s+egg\b"), "other"),
        # Kite Hill cream cheese alternatives
        (_r(r"\bkite\s+hill\b.*\bcream\s+cheese\b|\bkite\s+hill\b.*\bchive\b|\bkite\s+hill\b.*\bplain\b"), "other"),
        # Milkadamia macadamia milk (unsweetened / vanilla)
        (_r(r"\bmilkadamia\b|\bmacadamia\s+milk\b"), "other"),
        # Monty's vegan cream cheese / butter / scallion
        (_r(r"\bmonty.?s\b.*\bvegan\b|\bmonty.?s\b.*\bcream\s+cheese\b|\bmonty.?s\b.*\bbutter\b"), "other"),
        # Mooala organic banana drink
        (_r(r"\bmooala\b|\borganic\s+original\s+banana\s+drink\b"), "other"),
        # Original Field Roast Chao cream
        (_r(r"\boriginal\s+field\s+roast\b"), "other"),
        # Oui by Yoplait dairy-free yogurt
        (_r(r"\boui\s+by\s+yoplait\b|\boui.*dairy.free\b|\byoplait\b.*dairy.free\b"), "plant_yogurt"),
        # Pacific Foods ultra soy beverage
        (_r(r"\bpacific\s+foods\b.*\bsoy\b|\bultra\s+soy\b.*\bbeverage\b"), "soy_milk"),
        # Rice Dream beverage
        (_r(r"\brice\s+dream\b|\bdream\b.*\bright\s+calcium\b|\bdream\b.*\bvitamin\s+d\b"), "other"),
        # Silk cold foam cinnamon caramel cream
        (_r(r"\bsilk\b.*\bcold\s+foam\b|\bcold\s+foam\b.*\bcinnamon\b"), "plant_creamer"),
        # Spero Foods sunflower cream cheese
        (_r(r"\bspero\s+foods\b|\boriginal\s+sunflower\s+cream\s+cheese\b"), "other"),
        # Tofutti better than ricotta
        (_r(r"\btofutti\b|\bbetter\s+than\s+ricotta\b"), "other"),
        # Vegan cream cheese alternative
        (_r(r"\bvegan\s+cream\s+cheese\s+alternative\b"), "other"),
        # Vertage vegan mozzarella
        (_r(r"\bvertage\b"), "other"),
        # Violife slices / feta / cream cheese
        (_r(r"\bviolife\b"), "other"),
        # Wegmans 40% vegetable oil spread / vegan parmesan
        (_r(r"\bwegmans\b.*\bvegetable\s+oil\s+spread\b|\bwegmans\b.*\bvegan\b.*\bparmesan\b"), "other"),
    ],

    "dairy_eggs.cultured_dairy": [
        (_r(r"\bskyr\b"), "skyr"),
        (_r(r"\bkefir\b"), "kefir"),
        (_r(r"\bdrinkable\s+yogurt\b|\byogurt\s+drink\b|\byogurt\s+smoothie\b|\bdrinkab"), "drinkable_yogurt"),
        (_r(r"\bgreek\s+yogurt\b|\bgreek.style\s+yogurt\b"), "greek_yogurt"),
        (_r(r"\bcreme\s+fra[iî]che\b|\bcr[eè]me\s+fra[iî]che\b"), "creme_fraiche"),
        (_r(r"\bsour\s+cream\b"), "sour_cream"),
        # Cottage cheese — all fat levels
        (_r(r"\bcottage\s+cheese\b|\bsmall\s+curd\b|\blarge\s+curd\b|\bcottage\b.*\bcurd\b"), "cottage_cheese"),
        # Buttermilk (liquid cultured dairy, not butter)
        (_r(r"\bbuttermilk\b"), "kefir"),
        (_r(r"\byogurt\b|\byoghurt\b"), "regular_yogurt"),
    ],

    "dairy_eggs.eggs_butter": [
        (_r(r"\bghee\b"), "ghee"),
        (_r(r"\bmargarine\b|\bspread\b.*\bbutter\b|\bbutter.spread\b|\bbuttery\s+spread\b"), "margarine_spread"),
        (_r(r"\bbutter\b"), "butter"),
        (_r(r"\begg\b|\beggs\b"), "eggs"),
    ],

    "dairy_eggs.cheese": [
        (_r(r"\bcottage\s+cheese\b"), "cottage_cheese"),
        (_r(r"\bcream\s+cheese\b|\bneufchatel\b"), "cream_cheese"),
        (_r(r"\bparmesan\b|\bpecorino\b|\broma?no\b|\bgrana\s+padano\b|\basiago\b"), "parmesan"),
        (_r(r"\bmozzarella\b|\bbocconcini\b|\bburrata\b|\bfresh\s+mozzarella\b"), "mozzarella"),
        (_r(r"\bcheddar\b"), "cheddar"),
        (_r(r"\bswiss\b|\bgruy[eè]re\b|\bemmental\b|\bjarlsberg\b|\bprovol\b"), "swiss_gruyere"),
        (_r(r"\bbrie\b|\bcamembert\b|\bdelice\b"), "brie_camembert"),
        (_r(r"\bblue\s+cheese\b|\bbleu\s+cheese\b|\bgorgonzola\b|\bstilton\b|\broquefort\b"), "blue_cheese"),
        (_r(r"\bgoat\s+cheese\b|\bch[eè]vre\b|\bfeta\b|\bhalloumi\b"), "goat_cheese"),
        (_r(r"\bshredded\b|\bblend\b.*\bcheese\b|\bcheese\b.*\bblend\b|\bmexi\b|\bitalian\b.*\bblend\b|\bpizza\b.*\bcheese\b|\b4\s*cheese\b|\bfive\s*cheese\b|\bthree\s*cheese\b"), "shredded_blend"),
        (_r(r"\bsliced\b.*\bcheese\b|\bcheese\b.*\bsliced\b|\bamerican\s+cheese\b|\bmuenster\b|\bhavarti\b|\bcolby\b"), "sliced_cheese"),
        (_r(r"\bbabybel\b|\bbel\s+paese\b|\bedam\b|\bgouda\b|\bfontina\b|\btaleggio\b|\bmanchego\b|\bcomte\b|\bepoisses\b|\braclette\b|\blivarot\b|\bappenzeller\b|\bparmigiano\b"), "specialty_cheese"),
        (_r(r"\bstring\s+cheese\b|\bsnack\s+cheese\b|\bstick\s+cheese\b|\bfarmers?\s+cheese\b|\bfarmer\s+cheese\b|\bcurd\b"), "specialty_cheese"),
        (_r(r"\bricotta\b"), "cottage_cheese"),
        # Artisan / unnamed / small-creamery cheeses — catch-all
        (_r(r"\bcheese\b"), "specialty_cheese"),
    ],

    "desserts.chocolate": [
        (_r(r"\bdark\s+chocolate\b|\b70%\b|\b72%\b|\b80%\b|\b85%\b|\b90%\b|\bcacao\s+percentage\b|\bextra\s+dark\b|\bbittersweet\b|\bsemi.?sweet\s+chocolate\b"), "dark_chocolate_bar"),
        (_r(r"\bwhite\s+chocolate\b"), "white_chocolate"),
        (_r(r"\bchocolate\s+truffl\b|\btruffle\b.*\bchocolat\b|\btruffle\s+bar\b|\bbon\s*bon\b|\bganache\b|\bpralin\b|\bhoney\s+mama\b|\bfine\s+&\s+raw\b|\bmixed\s+truffle\b"), "chocolate_truffles"),
        (_r(r"\bchocolate.coated\s+nuts?\b|\bchocolate.covered\s+nuts?\b|\bchocolate.dipped\s+nuts?\b|\balmonds?\b.*\bchocolate\b|\bcashews?\b.*\bchocolate\b"), "chocolate_coated_nuts"),
        (_r(r"\bbaking\s+chocolate\b|\bchocolate\s+chips?\b|\bcocoa\s+powder\b|\bchocolate\s+wafers?\b|\bmelting\s+chocolate\b|\bmorsels\b"), "chocolate_baking"),
        (_r(r"\bpeanut\s+butter\s+cups?\b|\breese.s\b|\bkit\s*kat\b|\bsnickers\b|\btwix\b|\bbounty\b|\bcookies?\s+&\s+cream\b.*\bbar\b|\bcrunch\b.*\bbar\b|\bbar\b.*\bwafer\b|\bwafer\b.*\bbar\b|\bkinder\b"), "milk_chocolate_bar"),
        # Cups / individual pieces (Kisses, squares, discs)
        (_r(r"\bkisses\b|\bchocolate\s+cups?\b|\bchocolate\s+squares?\b|\bchocolate\s+discs?\b|\bchocolate\s+minis?\b|\bchocolate\s+medallion\b"), "chocolate_cups"),
        # Default milk chocolate bar
        (_r(r"\bmilk\s+chocolate\b|\bchocolate\s+bar\b|\bbar\b.*\bchocolat\b|\bchocolat\b.*\bbar\b"), "milk_chocolate_bar"),
        # Coffee toffee / almond toffee / pecan toffee
        (_r(r"\btoffee\b"), "chocolate_truffles"),
        # Chocolate covered fruit (goldenberries, cherries, dried fruit)
        (_r(r"\bchocolate.covered\b|\bchocolate.dipped\b|\bchocolate.coated\b"), "chocolate_coated_nuts"),
        # Artisan / small-batch bars (Lake Champlain, Raaka, TCHO, Beyond Good) — no specific tag above
        (_r(r"\blake\s+champlain\b|\braaka\b|\btcho\b|\bbeyond\s+good\b|\bfruition\b.*\bchocolate\b|\bchocolate\s+works\b"), "dark_chocolate_bar"),
        # Caramel / salted caramel chocolate
        (_r(r"\bsalted\s+caramel\s+chocolate\b|\bchocolate.*salted\s+caramel\b|\bcreamy\s+caramel\b.*\bchocolate\b"), "chocolate_truffles"),
        # Holiday / gift chocolate (assorted boxes, menorah pops, space bar)
        (_r(r"\bassorted\b.*\bchocolate\b|\bgift\b.*\bchocolate\b|\bchocolate\b.*\bgift\b|\bvalentine\b.*\bchocolate\b|\bholiday\b.*\bchocolate\b|\bchocolate\b.*\bbox\b|\bmenorah\b|\bspace\s+bar\b"), "chocolate_cups"),
        # Chocolate filled cups (Sprinkles, single-serve)
        (_r(r"\bsprinkles\s+cup\b|\bchocolate\s+red\s+velvet\b|\bchocolate\s+cup\b"), "chocolate_cups"),
        # Andes crème de menthe / mint chocolate
        (_r(r"\bandes\b.*\bcr[eè]me\s+de\s+menthe\b|\bandes\b.*\bmints?\b"), "chocolate_cups"),
        # Atkins endulge pecan clusters
        (_r(r"\batkins\b.*\bendulge\b|\bpecan\s+caramel\s+clusters?\b"), "chocolate_truffles"),
        # Blume superfood latte / hot cacao (misrouted to chocolate)
        (_r(r"\bblume\b.*\bhot\s+cacao\b|\breishi\s+hot\s+cacao\b|\bsuperfood\s+latte\b.*\bcacao\b"), "other"),
        # Brigadeiros (Brazilian bonbons)
        (_r(r"\bbrigadeiros?\b"), "chocolate_truffles"),
        # Butterfinger / fun size
        (_r(r"\bbutterfinger\b"), "chocolate_bar"),
        # Cadbury Creme Egg
        (_r(r"\bcadbury\b"), "chocolate_cups"),
        # Cocoa truffles
        (_r(r"\bcocoa\s+truffles?\b"), "chocolate_truffles"),
        # Coconut salted caramel candy bar
        (_r(r"\bcoconut\s+salted\s+caramel\s+candy\s+bar\b"), "chocolate_bar"),
        # Dr Browns soda (misrouted to chocolate)
        (_r(r"\bdr\s+browns?\b.*\bsoda\b"), "other"),
        # Fannie May mint meltaways
        (_r(r"\bfannie\s+may\b"), "chocolate_cups"),
        # Favorite Day S'mores mix
        (_r(r"\bfavorite\s+day\b.*\bs.?mores?\b|\bs.?mores?\s+mix\b"), "other"),
        # Feastables MrBeast chocolates
        (_r(r"\bfeastables?\b|\bmrbeast\b"), "chocolate_bar"),
        # Ferrero Collection / Rocher
        (_r(r"\bferrero\b|\bferrero\s+rocher\b|\bferrero\s+collection\b"), "chocolate_cups"),
        # Ghirardelli gift boxes / seasonal
        (_r(r"\bghirardelli\b.*\bcollection\b|\bghirardelli\b.*\bgift\b|\bghirardelli\b.*\bvalentine\b"), "chocolate_cups"),
        # Godiva assorted truffles
        (_r(r"\bgodiva\b"), "chocolate_truffles"),
        # Hershey's seasonal / cookies n creme
        (_r(r"\bhershey.?s\b|\bhersheys?\b"), "chocolate_bar"),
        # Junior Mints
        (_r(r"\bjunior\s+mints?\b"), "chocolate_cups"),
        # Lindt truffles / excellence bars
        (_r(r"\blindt\b"), "chocolate_truffles"),
        # M&Ms milk chocolate
        (_r(r"\bm\s*&\s*m.?s?\b"), "chocolate_bar"),
        # Nutella / Nutella and Go
        (_r(r"\bnutella\b"), "other"),
        # Pocky biscuit sticks in chocolate section
        (_r(r"\bpocky\b"), "other"),
        # Rolling Pin Dubai chocolates
        (_r(r"\brolling\s+pin\b.*\bdubai\b|\bdubai\s+chocolates?\b"), "chocolate_bar"),
        # Russell Stover / Dubai style hearts
        (_r(r"\brussell\s+stover\b|\bdubai\s+style\s+heart\b"), "chocolate_cups"),
        # Teensy candy bars
        (_r(r"\bteensy\s+candy\s+bars?\b"), "chocolate_bar"),
        # Tony's Chocolonely everything bar
        (_r(r"\btony.?s\s+chocolonely\b|\beverything\s+bar\b.*\bchocolate\b"), "chocolate_bar"),
        # Turtles / Demet's
        (_r(r"\bdemet.?s\b|\bturtles\b.*\bcandy\b|\bturtles\b.*\bchocolate\b"), "chocolate_truffles"),
        # York peppermint patties
        (_r(r"\byork\b.*\bpeppermint\b|\bpeppermint\s+patties?\b"), "chocolate_cups"),
        # Catch-all for any chocolate remaining
        (_r(r"\bchocolate\b"), "dark_chocolate_bar"),
    ],

    "desserts.candy": [
        (_r(r"\bgumm[yi]\b|\bgummies\b|\bgummy\s+bear\b|\bgummy\s+worm\b|\bfruit\s+snack\b|\bfruit\s+roll\b|\bfruit\s+strip\b|\bfruit\s+chew\b|\bstarburst\b|\bskittles\b|\bswedish\b|\bbear\s+fruit\b|\bfruit\s+split\b|\bfruit\s+stick\b|\bfruit\s+leather\b|\bfruit\s+dots?\b|\byou\s+love\s+fruit\b|\b\bBEAR\b.*\bfruit\b|\bfruit\s+rolls?\b|\borganic\s+mango\s+fruit\b"), "gummy_candy"),
        (_r(r"\bcrystallized\s+ginger\b|\bgin\s+gins\b|\bcandied\s+ginger\b|\bginger\s+chew\b|\bginger\s+candy\b|\bginger\s+people\b.*\bgin\b|\bthe\s+ginger\s+people\b.*\bgin\b"), "chewy_candy"),
        (_r(r"\bcaramel\b(?!\s+bar|\s+sauce|\s+syrup|\s+latte|\s+popcorn|\s+apple)"), "chewy_candy"),
        (_r(r"\btahini.*(?:chocolate|sweet)\b|\bchocolate.*tahini\b|\bsweet\s+tahini\b|\bsoom.*chocolate\b"), "chewy_candy"),
        (_r(r"\bmarshmallow\b"), "marshmallow"),
        (_r(r"\blollipop\b|\bsucker\b|\bpush\s*pop\b|\bcharms\s+pop\b|\bdrum\s*stick\b|\bpop\s+candy\b"), "lollipop"),
        (_r(r"\bcandy\s+bar\b|\bcaramel\b.*\bbar\b|\bnougat\b|\bsnickers\b|\btwix\b|\bbutterfinger\b|\b100\s*grand\b|\bpayday\b|\bheath\b"), "candy_bar"),
        (_r(r"\blicorice\b|\btwizzler\b|\bred\s+vine\b"), "licorice"),
        (_r(r"\bsour\b.*\bcandy\b|\bsour\b.*\bgumm\b|\bwarhead\b|\bpucker\b|\bsour\s+patch\b|\bsour\s+belt\b|\bsour\s+worm\b"), "sour_candy"),
        (_r(r"\bhard\s+candy\b|\bpeppermint\b|\bmint\b.*\bcandy\b|\bwertherss?\b|\blifesaver\b|\bbuttermint\b|\blemon\s+drop\b|\brock\s+candy\b|\bcough\s+drop\b|\btic\s+tac\b|\bbreath\s+mint\b"), "hard_candy"),
        (_r(r"\bchewy\b.*\bcandy\b|\bcandy\b.*\bchewy\b|\btaffy\b|\bcaramel\s+chew\b|\bstarburst\b|\bair\s*head\b|\blaffy\s+taffy\b|\bnow\s*&\s*later\b|\btootsie\b"), "chewy_candy"),
        (_r(r"\bcandy.coated\b|\bm&m\b|\bm&ms\b|\bjelly\s+bean\b|\bgobstopper\b|\bskittles\b|\bcoated\s+chocolate\b"), "candy_coated"),
        (_r(r"\bgum\b|\bchewing\s+gum\b|\bbubble\s+gum\b|\btrident\b|\bextra\s+gum\b|\borbit\b|\bpur\s+gum\b|\bdentyne\b"), "hard_candy"),
        # Fruit strips / fruit twists (Wegmans Organic, Good & Gather, Pure Organic)
        (_r(r"\bfruit\s+strips?\b|\bfruit\s+twists?\b|\borganic\s+(?:strawberry|raspberry|wildberry|mango|blueberry)\b.*\bstrips?\b|\borganic\b.*\bfruit\b.*\bstrips?\b|\bpomegranate\b.*\bfruit\s+strips?\b"), "gummy_candy"),
        # Halva (sesame candy)
        (_r(r"\bhalva\b|\bseed\s*&?\s*mill\b"), "chewy_candy"),
        # Luxardo cherries (maraschino, cocktail)
        (_r(r"\bluxardo\b|\bmaraschino\s+cherries?\b"), "other"),
        # Fruit Riot frozen candy grapes
        (_r(r"\bfruit\s+riot\b|\bcrunchy\s+candy\s+grapes?\b|\bsour\s+grapes?\b.*\bfrozen\b|\bfrozen.*\bgrapes?\b.*\bcandy\b"), "candy_coated"),
        # Climate Candy / real fruit chews
        (_r(r"\bclimate\s+candy\b|\breal\s+fruit\s+chews?\b"), "chewy_candy"),
        # Simple Mills Sweet Thins (mint chocolate)
        (_r(r"\bsweet\s+thins?\b|\bmint\s+chocolate\s+sweet\b"), "candy_coated"),
        # Dandies vegan marshmallows
        (_r(r"\bdandies\b|\bvegan\s+marshmallows?\b"), "marshmallow"),
        # Annie's peel-a-part / organic gummies
        (_r(r"\bpeel\s*a\s*part\b|\bannies?\b.*\bgumm\b"), "gummy_candy"),
        # Prosperity snack box / gift sets
        (_r(r"\bprosperity\s+snack\b|\bsnack\s+box\b|\bt[eé]\s+company\b"), "other"),
        # Cheese caramels (cheddar, smoked gouda, gruyere — savory)
        (_r(r"\bcheese\s+caramels?\b|\bcheddar\s+caramels?\b|\bgouda\s+caramels?\b|\bgruy[eè]re\s+caramels?\b"), "chewy_candy"),
        # Chimes ginger chews (not matched because "chimes" and "ginger chews" were separate)
        (_r(r"\bchimes\b|\bginger\s+chews?\b|\bpeanut\s+butter\b.*\bginger\b.*\bchews?\b"), "chewy_candy"),
        # Reed's ginger chews
        (_r(r"\breed.?s\b.*\bginger\b|\bfresh\s+ginger\s+chews?\b"), "chewy_candy"),
        # Pure Organic twisted/layered fruit snacks
        (_r(r"\bpure\s+organic\b.*\bfruit\s+snacks?\b|\btwisted\s+fruit\s+snacks?\b|\blayered\s+fruit\s+snacks?\b"), "gummy_candy"),
        # Good & Gather fruit strips / veggie strips
        (_r(r"\bgood\s*&?\s*gather\b.*\bfruit\b.*\bstrips?\b|\bberry\s+blend\s+fruit\b.*\bstrips?\b"), "gummy_candy"),
        # Annie's organic twists / gummy fruit snacks
        (_r(r"\bannies?\b.*\btwists?\b|\bannies?\b.*\bfruit\s+snacks?\b|\bsweet\s*&?\s*sour\s+twists?\b"), "gummy_candy"),
        # De La Rosa mazapan / pulparindo (Mexican candy)
        (_r(r"\bde\s+la\s+rosa\b|\bmazapan\b|\bpulparindo\b"), "chewy_candy"),
        # Rowntree's / Cavendish & Harvey / British candy
        (_r(r"\browntree.?s\b|\bfruit\s+pastilles?\b|\bcavendish\b.*\bharvey\b|\bfruit\s+drops?\b"), "hard_candy"),
        # Teddy Grahams (misrouted to candy — they're actually crackers/cookies)
        (_r(r"\bteddy\s+grahams?\b"), "other"),
        # Magic Straws (milk flavoring straws — not candy)
        (_r(r"\bmagic\s+straws?\b|\bmilk\s+magic\s+straws?\b"), "other"),
        # Sultan Turkish delight
        (_r(r"\bturkish\s+delight\b|\bsultan\b.*\bcandy\b|\blokum\b"), "chewy_candy"),
        # Chai tea mints
        (_r(r"\bchai\s+tea\s+mints?\b"), "hard_candy"),
        # Kanpai freeze-dried candy
        (_r(r"\bkanpai\b|\bfreeze.dried\s+candy\b"), "candy_coated"),
        # Dark chocolate sea salt caramels (Favorite Day)
        (_r(r"\bdark\s+chocolate\s+sea\s+salt\s+caramels?\b|\bfavorite\s+day\b.*\bcaramels?\b"), "chewy_candy"),
        # Red Vines / berry twists licorice
        (_r(r"\bred\s+vines\b|\bberry\s+twists?\b|\bmixed\s+berry\s+twists?\b"), "licorice"),
        # Lollipops (Zolli)
        (_r(r"\bzolli\b|\bzollipops?\b|\blollipops?\b|\bclean\s+teeth\s+candy\b"), "lollipop"),
        # Life Savers mints / breath mints
        (_r(r"\blife\s+savers?\b|\bwint.o.green\b|\bwint.o.mint\b|\bpep\s+o\s+mint\b"), "hard_candy"),
        # Pretzel-filled chocolate / mocha pretzels
        (_r(r"\bmocha\s+latte\s+pretzels?\b|\bpretzel\b.*\bchocolate\b|\bchocolate\b.*\bpretzel\b"), "candy_coated"),
        # Reese's peanut butter pretzels (candy-coated)
        (_r(r"\breese.?s\b.*\bpretzel\b|\bpeanut\s+butter.*\bpretzel\b.*\bfill\b"), "candy_coated"),
        # Heavenly Caramels
        (_r(r"\bheavenly\s+caramels?\b|\bvanilla\s+sea\s+salt\s+caramels?\b"), "chewy_candy"),
        # Unreal Snacks candy gems
        (_r(r"\bunreal\s+snacks?\b|\bcandy\s+gems?\b"), "candy_coated"),
        # Sanding sugar sprinkles (Favorite Day — not candy really)
        (_r(r"\bsanding\s+sugar\b|\bsprinkles?\b.*\bfavorite\s+day\b"), "other"),
        # Ginger rescue lozenges
        (_r(r"\bginger\s+rescue\b|\bginger\s+lozenges?\b|\brescue\s+lozenges?\b"), "hard_candy"),
        # Jordan almonds / dragees
        (_r(r"\bjordan\s+almonds?\b|\bdragees?\b|\bcandied\s+almond\b"), "candy_coated"),
        # Zotz fizz candy
        (_r(r"\bzotz?\b|\bfizz\s+power\b"), "hard_candy"),
        # Bazooka brand
        (_r(r"\bbazooka\b"), "hard_candy"),
        # Luxardo cherries (cocktail garnish)
        (_r(r"\bluxardo\b"), "other"),
        # Airheads brands
        (_r(r"\bairheads?\b|\bxtremes?\b.*\bcandy\b"), "hard_candy"),
        # Annie's organic fruit snacks
        (_r(r"\bannies?\b.*\bfruit\s+snacks?\b|\bannies?\b.*\bbunny\b.*\bfruit\b"), "fruit_snacks"),
        # Betty Crocker fruit snacks
        (_r(r"\bbetty\s+crocker\b.*\bfruit\s+snacks?\b"), "fruit_snacks"),
        # Campfire marshmallows
        (_r(r"\bcampfire\b.*\bmarshmallows?\b"), "marshmallow"),
        # Jet-Puffed marshmallows
        (_r(r"\bjet.?puffed\b|\bmini\s+marshmallows?\b"), "marshmallow"),
        # Good & Gather marshmallows / Wegmans marshmallows
        (_r(r"\bgood\s*&?\s*gather\b.*\bmarshmallows?\b|\bwegmans\b.*\bmarshmallows?\b"), "marshmallow"),
        # Favorite Day holiday candy
        (_r(r"\bfavorite\s+day\b.*\bcandy\b|\bfavorite\s+day\b.*\bcotton\s+candy\b|\bfavorite\s+day\b.*\bcandies\b"), "hard_candy"),
        (_r(r"\bfavorite\s+day\b.*\bsprinkles?\b|\bfavorite\s+day\b.*\bconversation\b"), "other"),
        # Fun Dip / Focus Snacks
        (_r(r"\bfun\s+dip\b|\bfocus\s+snacks?\b"), "hard_candy"),
        # Fruit Gushers
        (_r(r"\bfruit\s+gushers?\b|\bgushers?\b"), "fruit_snacks"),
        # Gumi Yum / novelty gummies
        (_r(r"\bgumi\s+yum\b|\bsurprise\s+wildlife\b"), "gummies"),
        # Haribo gummies / goldbears
        (_r(r"\bharibo\b|\bgoldbears?\b"), "gummies"),
        # Jell-O gelatin snacks (misrouted to candy)
        (_r(r"\bjell.?o\b.*\bgelatin\b|\bgelatin\s+snacks?\b"), "other"),
        # El Leon / Lucas candy (Mexican candy)
        (_r(r"\bel\s+leon\b|\bel\s+super\s+leon\b|\blucas\b.*\bcandy\b|\bsalsagheti\b|\btajin\b.*\bcandy\b|\bsnak\s+club\b"), "hard_candy"),
        # Mentos chewy mints
        (_r(r"\bmentos\b"), "hard_candy"),
        # Mike and Ike
        (_r(r"\bmike\s+and\s+ike\b|\bmike\s*&\s*ike\b"), "gummies"),
        # Oreo (misrouted to candy)
        (_r(r"\boreo\b.*\bsnack\s+packs?\b"), "other"),
        # PEZ / assorted dispensers
        (_r(r"\bpez\b"), "hard_candy"),
        # Reese's holiday shapes
        (_r(r"\breese.?s\b.*\bvalentine\b|\breese.?s\b.*\bhearts?\b|\breese.?s\b.*\beaster\b"), "chocolate"),
        # Rice Krispies Treats (misrouted to candy)
        (_r(r"\brice\s+krispies\s+treats?\b"), "other"),
        # SmartSweets
        (_r(r"\bsmartsweets?\b"), "gummies"),
        # Smarties
        (_r(r"\bsmarties\b"), "hard_candy"),
        # Smood Sweets date candy
        (_r(r"\bsmood\s+sweets?\b|\bsweet\s+berry\s+fish\s+candy\s+dates?\b"), "other"),
        # Snack Pack juicy gels
        (_r(r"\bsnack\s+pack\b.*\bjuicy\s+gels?\b|\bjuicy\s+gels?\b"), "other"),
        # Sour jelly beans / gourmet jelly beans
        (_r(r"\bjelly\s+beans?\b|\bgourmet\s+jelly\b"), "gummies"),
        # Sweethearts / conversation hearts / retro candies
        (_r(r"\bsweethearts?\b|\bconversation\s+hearts?\b"), "hard_candy"),
        # Thrive Brands cotton candy / confetti pops
        (_r(r"\bthrive\s+brands?\b|\bcotton\s+candy\b.*\bvalentine\b|\bconfetti\s+heart\s+pop\b"), "hard_candy"),
        # Trolli gummies / Easter gummies
        (_r(r"\btrolli\b|\bsour\s+brite\s+crawlers?\b"), "gummies"),
        # Twizzlers
        (_r(r"\btwizzlers?\b|\bpull\s*.*\bpeel\b"), "gummies"),
        # Welch's fruit snacks
        (_r(r"\bwelch.?s\b.*\bfruit\s+snacks?\b"), "fruit_snacks"),
        # Wegmans organic fruit snacks
        (_r(r"\bwegmans\b.*\bfruit\s+snacks?\b"), "fruit_snacks"),
        # YumEarth organic pops / fruit snacks
        (_r(r"\byumearth\b|\byum\s*earth\b"), "fruit_snacks"),
        # Albert's assorted fruit chews
        (_r(r"\balbert.?s\b.*\bfruit\s+chews?\b|\bassorted\s+fruit\s+chews?\b"), "gummies"),
        # Enjoy Hawaii lychee candy
        (_r(r"\benjoy\b.*\bhawaii\b|\blychee\s+candy\b|\bpeelerz?\b"), "hard_candy"),
        # Favorite Day nonpareils / sprinkles decorating
        (_r(r"\bfavorite\s+day\b.*\bnonpareils?\b|\bfavorite\s+day\b.*\brainbow\b"), "other"),
        # Fruit by the Foot
        (_r(r"\bfruit\s+by\s+the\s+foot\b|\btie\s+dye\s+fruit\s+snacks?\b"), "fruit_snacks"),
        # FruitBlox fruit snacks
        (_r(r"\bfruitblox\b|\bunspeakable\b.*\bfruit\s+snacks?\b"), "fruit_snacks"),
        # Good & Gather mixed fruit flavored snacks
        (_r(r"\bgood\s*&?\s*gather\b.*\bfruit\s+flavored\s+snacks?\b|\bgood\s*&?\s*gather\b.*\bvalentine.s\b.*\bfruit\b"), "fruit_snacks"),
        # HARIBO Easter / seasonal
        (_r(r"\bharibo\b.*\bhappy\s+chicks?\b|\bharibo\b.*\beaster\b"), "gummies"),
        # Howe butterscotch buttons
        (_r(r"\bhowe\b.*\bbutterscotch\b|\bbutterscotch\s+buttons?\b"), "hard_candy"),
        # Ice Breakers sours / duo mints
        (_r(r"\bice\s+breakers?\b"), "hard_candy"),
        # JOYRIDE sour watermelon wedges
        (_r(r"\bjoyride\b"), "gummies"),
        # Jolly Rancher hard candies
        (_r(r"\bjolly\s+rancher\b"), "hard_candy"),
        # Lemonhead ropes
        (_r(r"\blemonhead\b"), "hard_candy"),
        # Dulces Mara / Mexican candy
        (_r(r"\bdulces?\s+mara\b|\bsandia\s+candy\b|\bwatermelon\s+rings?\s+candy\b"), "hard_candy"),
        # Nature's Garden snacks probiotic yoggies
        (_r(r"\bnature.?s\s+garden\b|\byoggies?\b|\bprobiotic\s+yoggies?\b"), "fruit_snacks"),
        # Nerds Easter candy
        (_r(r"\bnerds?\b.*\beaster\b|\bnerds?\b.*\bcandy\b|\bnerds?\b.*\bbag\b"), "hard_candy"),
        # Reese's pieces
        (_r(r"\breese.?s\b.*\bpieces?\b|\bcrunchy\s+shell\b.*\bpeanut\s+butter\b"), "chocolate"),
        # Rice Krispies Treats (standalone bars)
        (_r(r"\brice\s+krispies\s+treats?\b|\bhomestyle\s+original\b.*\btreats?\b"), "other"),
        # Sable & Rosenfeld tipsy cherries
        (_r(r"\bsable\s*&?\s*rosenfeld\b|\btipsy\s+cherries?\b|\bwhiskey\s+cherries?\b"), "other"),
        # Scandinavian Swimmers
        (_r(r"\bscandinavian\s+swimmers?\b"), "gummies"),
        # Snack Owl watermelon slices
        (_r(r"\bsnack\s+owl\b|\bwatermelon\s+slices?\s+candy\b"), "gummies"),
        # Sour Strips dream berry
        (_r(r"\bsour\s+strips?\b|\bdream\s+berry\b"), "gummies"),
        # Stitch Disney candy plush
        (_r(r"\bstitch\b.*\bdisney\b|\bdisney\b.*\bvalentine\s+candy\b|\bheart\s+box\b.*\bcandy\b"), "other"),
        # Sugarfina bento candy box
        (_r(r"\bsugarfina\b|\bbento\s+candy\b"), "other"),
        # Wiley Wallaby sourrageous drops
        (_r(r"\bwiley\s+wallaby\b|\bsourrageous\b"), "gummies"),
    ],

    "desserts.baked": [
        (_r(r"\bcookie\b|\bshortbread\b|\bbiscotti\b|\bsnap\b.*\bcookie\b|\bchips\s+ahoy\b|\boreo\b|\bnutter\s+butter\b|\bpepperidge\b|\bwalker\b|\bvoortman\b|\bgoldfish\s+grahams?\b|\bgraham\s+cracker\b|\banimal\s+cracker\b|\bfig\s+bar\b|\bginger\s+snap\b|\bbiscoff\b|\blenny\s+&\s+larry\b|\bfinancier\b|\bsesame\s+cookie\b|\bpanettone\b.*\bcookie\b|\bsicilian\s+sesame\b"), "cookies"),
        (_r(r"\bbrownie\b"), "brownies"),
        (_r(r"\bmuffin\b"), "muffins"),
        (_r(r"\bpop.tart\b|\btoaster\s+pastry\b|\btoaster\s+strudel\b"), "other"),
        (_r(r"\bcupcake\b|\bcake\b|\bcoffee\s+cake\b|\bcrumb\s+cake\b|\bpound\s+cake\b|\bchiffon\b|\bsnack\s+cake\b|\btwinkie\b|\bding\s+dong\b|\bho\s+ho\b|\blittle\s+debbie\b|\bhostess\b|\bpanettone\b|\bcrostata\b|\bkey\s+lime\b"), "cakes_cupcakes"),
        (_r(r"\bpie\b|\btart\b|\bcobbler\b|\bclafoutis\b|\bbaklava\b|\bstrudel\b"), "pies_tarts"),
        (_r(r"\bsandwich\s+cookie\b|\bcreme\s+filled\b|\bdouble\s+stuff\b|\boreo\b"), "sandwich_cookies"),
        # Financiers / petits fours / elegant bakery bites
        (_r(r"\bfinancier\b|\bpetit\s+four\b|\bmadeleine\b|\bcanele\b|\bcannele\b"), "cookies"),
        # Tiramisu / panna cotta / banana bread pudding / fruitcake / rice pudding
        (_r(r"\btiramisu\b|\bpanna\s+cotta\b|\bbread\s+pudding\b|\bbanana\s+bread\s+pudding\b|\bfruitcake\b|\bfruit\s+cake\b|\brice\s+pudding\b"), "cakes_cupcakes"),
        # Banana bread / quick breads (as baked goods, not sandwich bread)
        (_r(r"\bbanana\s+bread\b|\bquick\s+bread\b"), "cakes_cupcakes"),
        # Cheesecake
        (_r(r"\bcheesecake\b"), "cakes_cupcakes"),
        # Brittle / bark / biscotti-style
        (_r(r"\bbrittle\b|\bbark\b(?!.*chocolate\s+bar)|\bbiscotti\b"), "cookies"),
        # Emmy's coconut cookies / soft & chewy cookies
        (_r(r"\bcoconut\s+cookies?\b|\bsesame\s+cookies?\b|\blinzer\b|\bsnickerdoodle\b|\bchococonut\b"), "cookies"),
        # Holiday / seasonal baked goods
        (_r(r"\bholiday\s+sweets?\b|\bgingerbread\s+house\b|\bfrosted\s+gingerbread\b|\bholiday\s+cookie\b"), "cookies"),
        # Sourdough cookies
        (_r(r"\bsourdough\b.*\bcookies?\b|\bsourdough\b.*\bchip\b"), "cookies"),
        # Vegan carrot / loaf cakes
        (_r(r"\bcarrot\b.*\bloaf\b|\bvegan\b.*\bloaf\b|\bmini\s+loaf\b"), "cakes_cupcakes"),
        # Gluten-free baked
        (_r(r"\bgluten.free\b.*\bcookies?\b|\bgluten.free\b.*\bbrownie\b|\bgluten.free\b.*\bpumpkin\b.*\bchip\b"), "cookies"),
        # Linzer cookies / raspberry cave cookies
        (_r(r"\braspberry\s+cave\b|\bginger\s+snap\b|\bginger\s+snaps?\b"), "cookies"),
        # Build-your-own kits
        (_r(r"\bbuild.your.own\b|\bpartybus\b"), "cakes_cupcakes"),
        # Rye toast chocolate chip cookies / artisan specialty
        (_r(r"\brye\s+toast\b.*\bcookie\b|\bryan\s+del\s+franco\b"), "cookies"),
        # Walnut banana bread
        (_r(r"\bwalnut\s+banana\b|\bpumpkin\s+chocolate\s+chip\s+cookie\b"), "cookies"),
        # Abe's muffins / gluten-free muffins / wild blueberry muffins  
        (_r(r"\babe.?s\s+muffins?\b|\bapple\s+cider\s+muffins?\b|\bwild\s+blueberry\s+muffins?\b|\bmuffin\s+pack\b"), "muffins"),
        # Oat chocolate chunk / oat cookies
        (_r(r"\boat\s+chocolate\b|\boatmeal\b.*\bcookies?\b|\boat\b.*\bcookies?\b|\boat\b.*\bbites?\b|\balyssa.?s\b"), "cookies"),
        # Chocolate mousse / pot de crème (FTP)
        (_r(r"\bchocolate\s+mousse\b|\bpot\s+de\s+cr[eè]me\b|\bhoney\s+vanilla\s+pot\b"), "other"),
        # Crumble / crisp (Four & Twenty Blackbirds)
        (_r(r"\bcrumble\b|\bpear\s+crumble\b|\bfour.*twenty.*blackbirds\b"), "pies_tarts"),
        # French galettes / butter cookies
        (_r(r"\bgalettes?\b.*\bcookies?\b|\bfrench\s+galettes?\b|\bbuttery\b.*\bcookies?\b|\balmond\s+cookies?\b"), "cookies"),
        # Siete grain-free cookies
        (_r(r"\bsiete\b.*\bcookies?\b"), "cookies"),
        # Maxine's Heavenly / Good Batch / artisan cookies
        (_r(r"\bmaxine.?s\b|\bgood\s+batch\b|\bginger\s+molasses\b|\bbrown\s+butter\b.*\bcookies?\b"), "cookies"),
        # Superfood chocolate chip cookies (Urban Remedy)
        (_r(r"\burban\s+remedy\b|\bsuperfood\b.*\bcookies?\b"), "cookies"),
        # French pudding / pumpkin spice pudding / chocolate pudding
        (_r(r"\blemon\s+french\s+pudding\b|\bpumpkin\s+spice\s+pudding\b|\bpudding\b(?!.*frozen|.*ice\s+cream)"), "other"),
        # Tiny bars / assorted bars (Té Company)
        (_r(r"\btiny\s+bars?\b|\bassorted\s+tiny\b"), "cookies"),
        # Mint chocolate treats not in chocolate category
        (_r(r"\bmint\s+chocolate\s+pudding\b"), "other"),
        # Native Bread and Pastry cookies
        (_r(r"\bnative\s+bread\b.*\bcookies?\b|\bchocolate\s+chunk\s+cookies?\b|\b55%\s+chocolate\b.*\bcookies?\b"), "cookies"),
        # California lemon / pudding cakes
        (_r(r"\bcalifornia\s+lemon\b|\blemon\s+pudding\b"), "cakes_cupcakes"),
        # Knead Love Bakery
        (_r(r"\bknead\s+love\b|\bgluten.free\s+feelings\s+brownies?\b"), "brownies"),
        # Partake cookies (gluten-free/vegan)
        (_r(r"\bpartake\b"), "cookies"),
        # Simple Mills sweet thins (seed & nut flour)
        (_r(r"\bsimple\s+mills\b.*\bsweet\s+thins?\b|\bseed\s*&?\s*nut\s+flour\b.*\bsweet\b"), "cookies"),
        # MadeGood crunchy cookies
        (_r(r"\bmadegood\b|\bmade\s+good\b.*\bcookies?\b"), "cookies"),
        # Legally Addictive cracker cookies
        (_r(r"\blegally\s+addictive\b|\bpeppermint\s+crunch\s+cracker\b"), "cookies"),
        # Salt of the Earth Bakery
        (_r(r"\bsalt\s+of\s+the\s+earth\s+bakery\b|\bchocoholic\b"), "cookies"),
        # Bella Lucia pizzelles
        (_r(r"\bbella\s+lucia\b|\bpizzelles?\b"), "cookies"),
        # Petit Pot French desserts
        (_r(r"\bpetit\s+pot\b|\bcr[eè]me\s+chocolat\b|\bfrench\s+dessert\b"), "other"),
        # Sticky toffee pudding
        (_r(r"\bsticky\s+toffee\s+pudding\b"), "cakes_cupcakes"),
        # Chocolate espresso cookies
        (_r(r"\bchocolate\s+espresso\s+cookies?\b"), "cookies"),
        # La Fermière crème chocolat
        (_r(r"\bla\s+fermi[eè]re\b"), "other"),
        # Veggies Made Great muffins
        (_r(r"\bveggies?\s+made\s+great\b|\bdouble\s+chocolate\s+muffins?\b"), "muffins"),
        # Wegmans graham cookies / animal cookies
        (_r(r"\bhoney\s+bear\s+graham\s+cookies?\b|\borganic\s+animal\s+cookies?\b|\bwegmans\b.*\bcookies?\b"), "cookies"),
        # Schar ladyfingers
        (_r(r"\bschar\b|\bladyfingers?\b"), "cookies"),
        # Wow Baking Company
        (_r(r"\bwow\s+baking\b"), "cookies"),
        # Goya Palmeritas (palm-leaf cookies)
        (_r(r"\bpalmeritas?\b|\bgoya\b.*\bcookies?\b"), "cookies"),
        # Chocolate chip cookies catch-all
        (_r(r"\bchocolate\s+chip\s+cookies?\b|\bchoc\s+chip\b.*\bcookies?\b"), "cookies"),
        # Decadent bites / mini bites
        (_r(r"\bdecadent\s+bites?\b|\bmini\s+bites?\b.*\bdessert\b"), "cookies"),
        # Wegmans mini decadent bites
        (_r(r"\bmini\s+decadent\b"), "cookies"),
        # Abe's cupcakes
        (_r(r"\babe.?s\b.*\bcupcakes?\b|\bschool\s+friendly\b.*\bcupcakes?\b"), "cupcakes"),
        # Bauducco wafers
        (_r(r"\bbauducco\b|\bchocolate\s+wafers?\b"), "cookies"),
        # Daelmans stroopwafels
        (_r(r"\bdaelmans?\b|\bstroopwafels?\b"), "cookies"),
        # Entenmann's little bites / donuts
        (_r(r"\bentenmann.?s\b.*\bdonuts?\b|\bentenmann.?s\b.*\blittle\s+bites?\b"), "donuts"),
        (_r(r"\bentenmann.?s\b.*\bbrownies?\b"), "brownies"),
        # Ethel's Baking turtle bars
        (_r(r"\bethel.?s\s+baking\b|\bturtle\s+dandy\b"), "brownies"),
        # Favorite Day donuts / mini donuts / frosted sugar cookies
        (_r(r"\bfavorite\s+day\b.*\bdonuts?\b|\bfavorite\s+day\b.*\bcupcakes?\b"), "donuts"),
        (_r(r"\bfavorite\s+day\b.*\bsugar\s+cookies?\b|\bfavorite\s+day\b.*\bfrosted\b.*\bcookies?\b"), "cookies"),
        # Goodie Girl animal crackers / magical
        (_r(r"\bgoodie\s+girl\b.*\banimal\s+crackers?\b|\bmagical\s+animal\s+crackers?\b"), "cookies"),
        # Jubilant sprinkle cookies
        (_r(r"\bjubilant\b.*\bcookies?\b|\bsprinkle\s+cookies?\b"), "cookies"),
        # Katz gluten free
        (_r(r"\bkatz\b.*\bgluten\s+free\b|\bkatz\b.*\bcinnamon\s+buns?\b|\bkatz\b.*\brugelech?\b"), "cookies"),
        # Kinnikinnick kinni kritters
        (_r(r"\bkinnikinnick\b|\bkinni\s+kritters?\b"), "cookies"),
        # La Fermière crème dessert
        (_r(r"\bla\s+fermière\b|\bcr[eè]me\s+vanille\b"), "other"),
        # Mother's cookies
        (_r(r"\bmother.?s\s+cookies?\b|\bpuppy\s+love\s+cookies?\b"), "cookies"),
        # Nutella B-Ready wafer / Pocky
        (_r(r"\bnutella\s+b.ready\b|\bcrispy\s+wafer\b"), "cookies"),
        (_r(r"\bpocky\b.*\bbiscuit\b|\bpocky\b.*\bsticks?\b"), "cookies"),
        # Pop-Tarts toaster pastries
        (_r(r"\bpop.?tarts?\b|\btoaster\s+pastries?\b|\bfrosted\s+strawberry\b.*\bpastries?\b"), "pastries"),
        # Quaker rice cakes (baked section)
        (_r(r"\bquaker\b.*\brice\s+cakes?\b|\bapple\s+cinnamon\b.*\brice\s+cakes?\b"), "other"),
        # Steve & Andy's soft cookies
        (_r(r"\bsteve\s*&?\s*andy.?s\b|\boatmeal\s+raisin\b.*\bcookies?\b"), "cookies"),
        # Tate's gluten free cookies
        (_r(r"\btate.?s\b.*\bgluten\s+free\b|\btate.?s\b"), "cookies"),
        # Teddy Grahams
        (_r(r"\bteddy\s+grahams?\b|\bhoney\s+graham\s+snacks?\b"), "cookies"),
        # Mini pies / teeny tiny
        (_r(r"\bteeny\s+tiny\b.*\bpies?\b|\bmini.*\bpies?\b"), "pastries"),
        # Wegmans seasonal bakery items
        (_r(r"\bwegmans\b.*\bmacarons?\b|\bwegmans\b.*\bshortcake\b|\bwegmans\b.*\bred\s+velvet\b|\bwegmans\b.*\bdonut\b"), "other"),
        (_r(r"\bwegmans\b.*\bpeanut\s+butter\s+dippers?\b"), "cookies"),
        # California lemon French pudding / raspberry mousse cakes
        (_r(r"\bcalifornia\s+lemon\b.*\bpudding\b|\braspberry\s+mousse\b|\bfrench\s+pudding\b"), "other"),
        # Eggnog pudding / mint chocolate pudding (pack)
        (_r(r"\beggnog\s+pudding\b|\bmint\s+chocolate\s+pudding\b|\b2.pack\b.*\bpudding\b"), "other"),
        # All the Things Cookies / Aussie-style sandwich cookies
        (_r(r"\ball\s+the\s+things\s+cookies?\b|\baussie.?style\b.*\bcookies?\b|\baussie\b.*\bsandwich\s+cookies?\b"), "cookies"),
        # Back to Nature cookies
        (_r(r"\bback\s+to\s+nature\b.*\bcookies?\b|\bfudge\s+striped\s+cookies?\b|\bpeanut\s+butter\s+creme\b.*\bcookies?\b"), "cookies"),
        # Bonne Maman tartlets
        (_r(r"\bbonne\s+maman\b.*\btartlets?\b|\bchocolate\s+caramel\s+tartlets?\b"), "pastries"),
        # Brookie (brownie + cookie hybrid)
        (_r(r"\bbrookie\b"), "brownies"),
        # Brooklyn babka
        (_r(r"\bbabka\b"), "pastries"),
        # Chobani flip / yogurt (misrouted to baked)
        (_r(r"\bchobani\s+flip\b"), "other"),
        # Entenmann's muffins / pound cakes / pop'ems
        (_r(r"\bentenmann.?s\b.*\bmuffins?\b|\bentenmann.?s\b.*\bpound\s+cakes?\b"), "muffins"),
        (_r(r"\bentenmann.?s\b.*\bpop.?ems\b|\bentenmann.?s\b.*\bglazed\b"), "donuts"),
        # Fage sweet cultured cream dessert (misrouted)
        (_r(r"\bfage\b.*\bsweet\b|\bfage\b.*\bvanilla\b.*\bcultured\b"), "other"),
        # Favorite Day variety cookies / wafer cookies
        (_r(r"\bfavorite\s+day\b.*\bwafer\s+cookies?\b|\bfavorite\s+day\b.*\bvariety\s+cookies?\b"), "cookies"),
        # Glutino chocolate vanilla sandwich cookies
        (_r(r"\bglutino\b"), "cookies"),
        # Goodie Girl sandwich cookies s'mores
        (_r(r"\bgoodie\s+girl\b.*\bsandwich\s+cookies?\b|\bgoodie\s+girl\b.*\bs.?mores?\b"), "cookies"),
        # Honey Maid honey grahams
        (_r(r"\bhoney\s+maid\b|\bhoney\s+grahams?\b"), "cookies"),
        # Jell-O gelatin snacks / dessert (misrouted to baked)
        (_r(r"\bjell.?o\b"), "other"),
        # Katz donut holes
        (_r(r"\bkatz\b.*\bdonut\s+holes?\b|\bglazed\s+chocolate\b.*\bdonut\b"), "donuts"),
        # Keebler E.L. Fudge / cookies
        (_r(r"\bkeebler\b.*\bcookies?\b|\be\.?l\.?\s+fudge\b|\bdouble\s+stuffed\s+cookies?\b"), "cookies"),
        # Kinder Kinderini
        (_r(r"\bkinder\b.*\bkinderini\b|\bkinderini\b"), "cookies"),
        # La Fermière crème chocolat / French dessert
        (_r(r"\bla\s+ferm[iè]re\b|\bcr[eè]me\s+chocolat\b"), "other"),
        # Legendary Foods sweet roll / keto friendly
        (_r(r"\blegendary\s+foods?\b.*\bsweet\s+roll\b|\bketo\b.*\bprotein\s+sweet\s+roll\b"), "pastries"),
        # Maple Leaf Cookies
        (_r(r"\bmaple\s+leaf\s+cookies?\b"), "cookies"),
        # NABISCO classic mix variety pack
        (_r(r"\bnabisco\b.*\bclassic\s+mix\b|\bnabisco\b.*\bvariety\s+pack\b"), "cookies"),
        # Petit Pot vanilla bean French dessert
        (_r(r"\bpetit\s+pot\b"), "other"),
        # Profeel creamy caramel protein pudding
        (_r(r"\bprofeel\b|\bcreamy\s+caramel\s+protein\s+pudding\b"), "other"),
        # Quest brownies bake shop
        (_r(r"\bquest\b.*\bbrownies?\b|\bquest\b.*\bbake\s+shop\b"), "brownies"),
        # Reese's peanut butter cookies
        (_r(r"\breese.?s\b.*\bcookies?\b|\bpeanut\s+butter\s+chocolate\s+cookies?\b"), "cookies"),
        # Wegmans assorted fry cakes / iced dec / cannoli dip tray
        (_r(r"\bwegmans\b.*\bfry\s+cakes?\b|\bwegmans\b.*\biced\s+dec\b"), "other"),
        (_r(r"\bwegmans\b.*\bcannoli\b.*\btray\b|\bwegmans\b.*\bcannoli\b"), "other"),
        # belVita breakfast biscuits
        (_r(r"\bbelvita\b|\bbreakfast\s+biscuits?\b"), "cookies"),
    ],

    "desserts.frozen": [
        (_r(r"\bice\s+cream\b|\bfrozen\s+custard\b|\bgelato\b|\bfrozen\s+dairy\b"), "ice_cream"),
        (_r(r"\bfrozen\s+yogurt\b|\bfroyo\b"), "frozen_yogurt"),
        (_r(r"\bsorbet\b|\bsherbet\b|\bshaved\s+ice\b|\bsnow\s+cone\b"), "sorbet"),
        (_r(r"\bpopsicle\b|\bfruit\s+bar\b|\bfruit\s+pop\b|\bfruit\s+stick\b|\bwater\s+ice\b|\bice\s+pop\b|\bfruit\s+ice\b|\boutshine\b|\bjonny\s*pop\b|\bgood\s+pop\b|\bbonbon\b|\bice\s+lolly\b"), "frozen_fruit_bar"),
        (_r(r"\bfrozen\s+pie\b|\bice\s+cream\s+cake\b|\bice\s+cream\s+sandwich\b|\bice\s+cream\s+bar\b|\bklondike\b|\bdipped\s+bar\b|\bnovelty\b|\bice\s+cream\s+cone\b|\bchoco\s+taco\b|\bdessert\s+bar\b|\bprotein\s+pint\b|\bfrozen\s+dessert\b|\bdairy.free\s+frozen\b|\bfrozen\s+truffle\b|\bfrozen.*banana\b|\bfrozen\s+cookie\s+dough\b|\bcookie\s+dough.*frozen\b|\bchess\s+pie\b|\brice\s+pudding\b|\bfrozen\s+pudding\b|\bchocolate\s+pudding\b|\bpudding\b"), "frozen_novelty"),
        (_r(r"\bfrozen\s+broccoli\b|\bfrozen\s+cauliflower\b|\bfrozen\s+vegetable\b|\bfrozen\s+fruit\b|\boven\s+roaster\b|\broaster.*frozen\b"), "other"),
        # Mochi ice cream
        (_r(r"\bmochi\b"), "frozen_novelty"),
        # Tiramisu / mousse / soufflé cheesecake / creme brulee
        (_r(r"\btiramisu\b|\bmousse\b.*\bdessert\b|\bsouffl[eé]\b.*\bcheesecake\b|\bcheesecake\b.*\bfrozen\b|\bcreme\s+brulee\b|\bcrème\s+brûlée\b"), "frozen_novelty"),
        # Tru Fru / frozen chocolate-covered fruit
        (_r(r"\btru\s+fru\b|\bfrozen\s+banana\b|\bfrozen\s+raspberry\b|\bfrozen\s+blueberr\b|\bfrozen\s+strawberr\b|\bchocolate\s+covered\b.*\bfrozen\b"), "frozen_novelty"),
        # Fruit Riot! / frozen fruit snack (candy-like)
        (_r(r"\bfruit\s+riot\b|\bfrozen\s+sour\b.*\bfruit\b|\bfrozen\s+mango\b|\bsour\s+mango\b"), "frozen_fruit_bar"),
        # Sambazon frozen acai globes / bowls
        (_r(r"\bsambazon\b|\bacai\b.*\bfrozen\b|\bfrozen\b.*\bacai\b"), "sorbet"),
        # Protein pints / high protein frozen desserts
        (_r(r"\bprotein\s+pint\b|\bhigh\s+protein\b.*\bdessert\b|\bprotein\b.*\bfrozen\s+dessert\b"), "frozen_novelty"),
        # Frozen mini desserts / color burst
        (_r(r"\bcolor\s+burst\b|\bcolor\s+burst\s+mini\b|\bfrozen.*mini\b.*\bbar\b|\bsorbetto\b.*\bbar\b"), "frozen_fruit_bar"),
        # Hold The Cone / ice cream cone tips
        (_r(r"\bhold\s+the\s+cone\b|\bcone\s+tips?\b|\bice\s+cream\s+tips?\b"), "frozen_novelty"),
        # Frozen vegetable / soup mix misrouted to desserts.frozen
        (_r(r"\bsoup\s+mix\b|\bvegetable\s+with\s+mushroom\b|\bmatzo\s+ball\b|\boven\s+roast\b"), "other"),
        # Japanese / Korean frozen sweets
        (_r(r"\bjapanese\b.*\bdessert\b|\bjapanese\b.*\bsweet\b|\bkumo\b|\bgone\s+berry\b"), "frozen_novelty"),
        # Frozen yogurt bars / dipped bars (Haagen-Dazs bars)
        (_r(r"\bhaagen.dazs\b.*\bbar\b|\bfrozen\b.*\bdipped\s+bar\b|\bvanilla\s+milk\s+chocolate\s+almond\s+bar\b"), "frozen_novelty"),
        # Frozen mango / fruit bars (Good & Gather fruit bars)
        (_r(r"\bfrozen\s+mango\s+fruit\s+bar\b|\bfrozen\s+fruit\s+bar\b"), "frozen_fruit_bar"),
        # Talenti sorbetto / dairy-free sorbetto
        (_r(r"\btalenti\b.*\bsorbetto\b|\bsorbetto\b.*\btalenti\b|\btalenti\b.*\bfrozen\b|\bmini\s+sorbetto\b"), "sorbet"),
        # JonnyPops fruit bars / water pops
        (_r(r"\bjonnypops?\b|\bjonny\s+pops?\b|\bstrawberries\s*&\s*cream\s+frozen\b|\bwatermelon\s+frozen\s+water\s+pop\b|\bcotton\s+candy\s+cloud\b"), "frozen_fruit_bar"),
        # Jeni's Darkest Chocolate / Jeni's ice cream
        (_r(r"\bjeni.?s\b"), "ice_cream"),
        # Gone Bananas! (chocolate-covered frozen)
        (_r(r"\bgone\s+bananas?\b"), "frozen_novelty"),
        # Nelly's Organics dark chocolate coconut
        (_r(r"\bnelly.?s\b.*\bdark\s+chocolate\b|\bnelly.?s\b.*\bfrozen\b|\bdark\s+chocolate\s+coconut\b.*\bcashew\b"), "frozen_novelty"),
        # Haagen-Dazs frozen bars
        (_r(r"\bhaagen.dazs\b|\bvanilla\s+milk\s+chocolate\s+almond\b.*\bbar\b"), "frozen_novelty"),
        # Favorite Day frozen cookie dough / frozen croissant
        (_r(r"\bfavorite\s+day\b.*\bfrozen\b|\bfrozen\b.*\bcookie\s+dough\s+snacks?\b|\bfrozen\b.*\bcroissant\b"), "frozen_novelty"),
        # Manischewitz soup mix / Birds Eye frozen veggies misrouted
        (_r(r"\bmanischewitz\b|\bbirds?\s+eye\b.*\boven\s+roasters?\b|\boven\s+roasters?\b.*\bfrozen\b"), "other"),
        # Mini chocolate mousse desserts
        (_r(r"\bmini\s+chocolate\s+mousse\b"), "frozen_novelty"),
        # Soufflé cheesecakes (Japanese)
        (_r(r"\bjapanese\s+souffl[eé]\b|\bsouffl[eé]\s+cheesecake\b"), "frozen_novelty"),
        # Ben & Jerry's sundaes
        (_r(r"\bben\s*&?\s*jerry.?s\b|\bcookie\s+vermont.?ster\b|\bphish\s+food\b|\bcherry\s+garcia\b"), "ice_cream"),
        # Boba Bam frozen boba packs
        (_r(r"\bboba\s*bam\b|\bfrozen\s+instant\s+boba\b|\bbobabam\b"), "other"),
        # Bomb Pop
        (_r(r"\bbomb\s+pop\b"), "frozen_fruit_bar"),
        # Breyers non-dairy
        (_r(r"\bbreyers?\b"), "ice_cream"),
        # Clio yogurt bars mini (frozen section)
        (_r(r"\bclio\b.*\byogurt\s+bars?\b.*\bmini\b|\bclio\b.*\bmini\b.*\byogurt\b"), "frozen_yogurt"),
        # Dally mango gel / boba gel snack
        (_r(r"\bdally\b.*\bgel\b|\bmango\s+gel\s+snack\b"), "other"),
        # Delizza Belgian custard eclairs
        (_r(r"\bdelizza\b|\bbelgian\s+custard\b|\bmini\s+eclairs?\b"), "frozen_novelty"),
        # Doughlicious frozen cookie dough
        (_r(r"\bdoughlicious\b|\bfrozen\s+salted\s+caramel\s+cookie\s+dough\b"), "frozen_novelty"),
        # Drumstick cones
        (_r(r"\bdrumstick\b.*\bcone\b|\bcrunch\s+dipped\b"), "ice_cream"),
        # Fage banana cultured cream dessert
        (_r(r"\bfage\b.*\bdessert\b|\bcultured\s+cream\s+dessert\b"), "frozen_yogurt"),
        # Good & Gather frozen fruit bars
        (_r(r"\bgood\s*&?\s*gather\b.*\bfrozen\s+strawberry\s+fruit\s+bars?\b|\bgood\s*&?\s*gather\b.*\bfruit\s+bars?\b"), "frozen_fruit_bar"),
        # GoodPop Disney / licensed ice pops
        (_r(r"\bgoodpop\b|\bdisney\b.*\bice\s+pop\b|\bmickey\s+mouse\b.*\bpops?\b"), "frozen_fruit_bar"),
        # JonnyPops strawberry chocolate
        (_r(r"\bjonnypops?\b"), "frozen_fruit_bar"),
        # Junior's cheesecake
        (_r(r"\bjunior.?s\b.*\bcheesecake\b"), "frozen_novelty"),
        # Just the Fun Part / Dubai cones
        (_r(r"\bjust\s+the\s+fun\s+part\b|\bdubai\s+cones?\b|\bkadaifi\b"), "frozen_novelty"),
        # KIND frozen bars
        (_r(r"\bkind\b.*\bfrozen\b|\bkind\b.*\bplant\s+based\s+frozen\b"), "frozen_novelty"),
        # Luigi's Italian ice
        (_r(r"\bluigi.?s\b.*\bitalian\s+ice\b|\bitalian\s+ice\b"), "sorbet"),
        # Marie Callender's frozen pie
        (_r(r"\bmarie\s+callender.?s\b|\bdutch\s+apple\s+pie\b.*\bfrozen\b"), "frozen_novelty"),
        # Nestle Oreo frozen bites
        (_r(r"\bnestle\b.*\boreo\b.*\bfrozen\b|\boreo\s+frozen\s+bites?\b"), "frozen_novelty"),
        # Nick's cookies & cream / Swedish frozen
        (_r(r"\bnick.?s\b.*\bcookies?\s*&?\s*cream\b"), "ice_cream"),
        # Skinny Cow sandwiches
        (_r(r"\bskinny\s+cow\b"), "frozen_novelty"),
        # Trolli frozen pops (misrouted)
        (_r(r"\btrolli\b.*\bfrozen\s+pop\b|\bgummi\s+frozen\s+pop\b"), "other"),
        # Wegmans fudge bars / mousse cup
        (_r(r"\bwegmans\b.*\bfudge\s+bars?\b|\bwegmans\b.*\bmousse\s+cup\b"), "frozen_novelty"),
        # Yasso Greek yogurt bars
        (_r(r"\byasso\b"), "frozen_yogurt"),
    ],

    "pantry.chips_crackers": [
        (_r(r"\bpopcorn\b"), "popcorn"),
        (_r(r"\bpretzel\b"), "pretzels"),
        (_r(r"\bpork\s+rind\b|\bchicharr\b|\bpork\s+crackling\b"), "pork_rinds"),
        (_r(r"\bseaweed\b|\bnori\s+snack\b|\broasted\s+seaweed\b"), "seaweed_snacks"),
        (_r(r"\brice\s+cake\b|\brice\s+crisp\b|\brice\s+thins?\b|\brice\s+cracker\b|\bpuffed\s+rice\b|\bcorn\s+cake\b|\bpopped\s+rice\b|\bbrown\s+rice\s+snap\b|\brice\s+snap\b"), "rice_cakes"),
        (_r(r"\bveggie\s+chip\b|\bveggie\s+straw\b|\bvegetable\s+chip\b|\bkale\s+chip\b|\bbeet\s+chip\b|\bsweet\s+potato\s+chip\b|\bcarrot\s+chip\b|\bparsnip\s+chip\b|\btaro\s+chip\b|\blentil\s+chip\b|\bchickpea\s+chip\b|\bpea\s+snack\b|\bpea\s+puff\b|\bedamame\s+chip\b|\bcassava\s+chip\b|\bplantain\s+chip\b|\bbean\s+chip\b"), "veggie_chips"),
        (_r(r"\btortilla\s+chip\b|\btortilla\s+crisp\b|\bnacho\s+chip\b|\bnacho\b.*\btortilla\b|\bcorn\s+chip\b|\bfritos?\b|\btostito\b|\bdoritos?\b|\bmission\s+chip\b|\bblue\s+corn\s+chip\b|\btriangle\s+chip\b"), "tortilla_chips"),
        (_r(r"\bpotato\s+chip\b|\bkettle\s+chip\b|\bkettle\s+cooked\b|\blay.s\b|\bpringles\b|\bruffles\b|\bwaves?\b.*\bchip\b|\bcrisp\b.*\bpotato\b|\bpotato\s+crisp\b|\bcheddar\s+&\s+sour\s+cream\s+potato\b"), "potato_chips"),
        # Crackers / crisps catch-all (must come after chips)
        (_r(r"\bcracker\b|\bcrisp\b|\bmatzo\b|\bmatza\b|\bgrahams?\b(?!\s+cracker\s+crust)|\bwasa\b|\bwoven\s+wheat\b|\btriscuit\b|\britz\b|\btown\s+house\b|\bgoldfish\b|\bcheez.it\b|\bcheez\s+it\b|\bwheat\s+thin\b|\brice\s+thin\b|\bpapadum\b|\blavash\s+cracker\b|\bcrostini\b|\bflatbread\s+cracker\b|\bseed\s+cracker\b|\bfirehook\b|\btop\s+seedz\b|\bmary.s\s+gone\b|\bsnap\s+pea\s+crisp\b|\bsnap\s+peas\b.*\bcrisp\b"), "crackers"),
        # Bare name products — single-word snack names that are clearly chips/crackers
        (_r(r"^crispy\s+\w+$|^crunchy\s+\w+$"), "crackers"),
        # Sweet potato chips (not caught by veggie_chips above because no "sweet potato chip")
        (_r(r"\bsweet\s+potato\b.*\bchips?\b|\bchips?\b.*\bsweet\s+potato\b|\bjackson.?s\b"), "veggie_chips"),
        # Siete branded chips (grain-free, cassava) — family name chips
        (_r(r"\bsiete\b"), "tortilla_chips"),
        # Xochitl / MASA / Tostitos Simply — corn/tortilla chips
        (_r(r"\bxochitl\b|\bmasa\b.*\bchip\b|\btostitos\s+simply\b|\bsimply\s+tostitos\b|\blate\s+july\b"), "tortilla_chips"),
        # Lundberg / Real Foods / brown rice / corn thin snacks
        (_r(r"\blundberg\b|\breal\s+foods\s+corn\s+thins?\b|\bcorn\s+thins?\b|\bbrown\s+rice\s+snaps?\b|\brice\s+snaps?\b"), "rice_cakes"),
        # Boulder Canyon / avocado oil chips
        (_r(r"\bboulder\s+canyon\b|\bavocado\s+oil\b.*\bchips?\b|\bchips?\b.*\bavocado\s+oil\b"), "potato_chips"),
        # Orville Redenbacher's kernels (popcorn, but listed as "kernels")
        (_r(r"\borville\b|\bpopping\s+kernels?\b|\bpop\s+kernels?\b"), "popcorn"),
        # Nordic crisps / multi-seed crisps
        (_r(r"\bnordic\s+crisps?\b|\bmulti.?seed\b.*\bcrisps?\b|\bseeds?\b.*\bcrisps?\b|\bsesame\s+citrus\b"), "crackers"),
        # Chifles / plantain snacks
        (_r(r"\bchifles\b|\bplantain\s+snack\b"), "veggie_chips"),
        # Crunchsters mung beans / similar protein snacks
        (_r(r"\bcrunchsters?\b|\bmung\s+beans?\b.*\bcrunch\b|\bsnack\b.*\bmung\b"), "veggie_chips"),
        # Hungry Bird Eats / seedy Nordic crisps
        (_r(r"\bhungry\s+bird\b"), "crackers"),
        # Popcorn that didn't match above
        (_r(r"\bpopped\b.*\bcakes?\b|\bwhole\s+grain\s+popped\b"), "rice_cakes"),
        # Parmesan / cheese crisps (not a traditional chip)
        (_r(r"\bparmesan\s+crisp\b|\bcheese\s+crisp\b|\bparm\s+crisp\b|\bcheese\s+snacker\b|\bcheese\s+bites?\b|\bunexpected\s+cheddar\b"), "crackers"),
        # Quaker rice cakes (not caught because "lightly salted" precedes "rice cakes" but pattern requires "rice cake" together)
        (_r(r"\bquaker\b.*\brice\s+cakes?\b|\bquaker\b.*\brice\b|\blightly\s+salted\b.*\brice\b"), "rice_cakes"),
        # MASA tortilla chips brand
        (_r(r"\bmasa\b.*\btortilla\b|\btraditional\s+tortilla\s+chips?\b"), "tortilla_chips"),
        # Norwegian knekkebrod / crispbread
        (_r(r"\bknekkebrod\b|\bknekkebrød\b|\bnorwegian\s+baked\b|\bcrispbread\b"), "crackers"),
        # Uncle Jerry's pretzels
        (_r(r"\buncle\s+jerry.?s\b"), "pretzels"),
        # Plantain crisps / crispy plantain
        (_r(r"\bplantain\s+crisps?\b|\bplantain\s+chips?\b|\bcrispy\s+plantain\b"), "veggie_chips"),
        # Crispy jalapeño pieces
        (_r(r"\bcrispy\s+jalap\b|\bjalap.*\bcrisps?\b|\bjalap.*\bpieces?\b"), "veggie_chips"),
        # Papadums / lentil & chickpea crisps
        (_r(r"\bpapadum\b|\bpapadoms?\b|\blentil\b.*\bchickpea\b.*\bcrisps?\b"), "crackers"),
        # Bruschette toasts / melba toast / crostini
        (_r(r"\bbruschette?\b|\bmelba\b|\btoasts?\b(?!.*avocado|.*cheese)"), "crackers"),
        # Healing Home Foods raw crackers
        (_r(r"\bhealing\s+home\b|\braw\s+crackers?\b"), "crackers"),
        # Goya chicharrones
        (_r(r"\bgoya\b.*\bchicharron\b|\bchicharrones?\b"), "pork_rinds"),
        # Pork rinds not matched above
        (_r(r"\bpork\s+rinds?\b|\bsea\s+salt\s+pork\b"), "pork_rinds"),
        # Mac's pork skins
        (_r(r"\bmac.?s\b.*\bpork\s+skins?\b|\bpork\s+skins?\b"), "pork_rinds"),
        # Vegetable root chips
        (_r(r"\broot\s+chips?\b|\bvegetable\s+root\s+chips?\b|\bmulti.root\b|\broot\s+vegetable\s+chips?\b"), "veggie_chips"),
        # Bamba peanut snacks / peanut puffs (Osem)
        (_r(r"\bbamba\b|\bosem\b.*\bpeanut\b|\bpeanut\s+puffs?\b|\bpeanut\s+snacks?\b"), "veggie_chips"),
        # Every Body Eat thins
        (_r(r"\bevery\s+body\s+eat\b|\bevery\s*body\s*eat\b"), "crackers"),
        # Good Thins rice snacks
        (_r(r"\bgood\s+thins?\b|\brice\s+snacks?\b.*\bgluten.?free\b"), "rice_cakes"),
        # Cape Cod chips (not previously matched because no "potato chip" keyword)
        (_r(r"\bcape\s+cod\b"), "potato_chips"),
        # Wegmans restaurant-style tortilla chips
        (_r(r"\brestaurant.style\b.*\btortilla\b|\bwhite\s+corn\b.*\bsea\s+salt\b.*\btortilla\b|\bblue\s+corn\b.*\btortilla\b"), "tortilla_chips"),
        # Cauliflower tortilla chips / grain-free tortilla chips
        (_r(r"\bcauliflower\b.*\btortilla\b.*\bchips?\b|\bgrain.?free\b.*\btortilla\b|\bvista\s+hermosa\b"), "tortilla_chips"),
        # Kim's Deli Pop / popcorn (deli)
        (_r(r"\bkim.?s\s+deli\s+pop\b"), "popcorn"),
        # Tostitos (various: Scoops, Cantina, Rounds, Baked, multigrain)
        (_r(r"\btostitos\b"), "tortilla_chips"),
        # Plant crisps / BBQ plant crisps
        (_r(r"\bplant\s+crisps?\b|\bplant.based\s+crisps?\b"), "crackers"),
        # Raisin rosemary crisps / flavored crisps
        (_r(r"\braisin\s+rosemary\s+crisps?\b|\brosemary\b.*\bcrisps?\b"), "crackers"),
        # Wegmans get dippin' corn chips / tortilla chips
        (_r(r"\bget\s+dippin\b|\bwegmans\b.*\btortilla\b|\bwegmans\b.*\bcorn\s+chips?\b"), "tortilla_chips"),
        # Santitas white corn chips
        (_r(r"\bsantitas\b"), "tortilla_chips"),
        # Tortilla strips (fresh gourmet)
        (_r(r"\btortilla\s+strips?\b|\btri.color\s+tortilla\b"), "tortilla_chips"),
        # Wegmans peanut butter puffs
        (_r(r"\bwegmans\b.*\bpeanut\s+butter\s+puffs?\b|\bpeanut\s+butter\s+puffs?\b"), "veggie_chips"),
        # PopCorners / Popcorners — popped corn chips
        (_r(r"\bpopcorners?\b|\bpopped.corn\s+snacks?\b"), "popcorn"),
        # PopChips / Popchips
        (_r(r"\bpopchips?\b|\bpopped\s+sea\s+salt\s+potato\b"), "potato_chips"),
        # Simple Mills rosemary / almond flour crackers
        (_r(r"\bsimple\s+mills\b"), "crackers"),
        # Good & Gather rice crackers / veggie tortilla chips / French fried onions
        (_r(r"\bgood\s*&?\s*gather\b.*\brice\s+crackers?\b|\bmulti.grain.*\bflax\b.*\bcrackers?\b"), "crackers"),
        (_r(r"\bgood\s*&?\s*gather\b.*\bveggie\s+tortilla\b|\borganic\s+veggie\s+tortilla\b"), "tortilla_chips"),
        (_r(r"\bfrench\s+fried\s+onions?\b|\bgood\s*&?\s*gather\b.*\bonions?\b"), "other"),
        # Osem mandel croutons
        (_r(r"\bosem\b.*\bcroutons?\b|\bmandel\s+croutons?\b"), "crackers"),
        # North Fork potato chips / small brand chips
        (_r(r"\bnorth\s+fork\b|\bsalted\s+potato\s+chips?\b"), "potato_chips"),
        # All Souls Tortilleria / Juantonio's / artisan corn chips
        (_r(r"\ball\s+souls\b|\bjuantonio.?s\b|\bheirloom\s+corn\s+tortilla\b"), "tortilla_chips"),
        # Onesto / gluten-free sea salt crackers
        (_r(r"\bonesto\b"), "crackers"),
        # New York Chips brand
        (_r(r"\bnew\s+york\s+chips?\b"), "potato_chips"),
        # From the Ground Up cauliflower stalks / pretzels
        (_r(r"\bfrom\s+the\s+ground\s+up\b|\bcauliflower\s+stalks?\b|\bcauliflower\s+pretzels?\b"), "veggie_chips"),
        # Biena crispy roasted edamame / chickpeas
        (_r(r"\bbiena\b|\bcrispy\s+roasted\b.*\bedamame\b|\bcrispy\s+roasted\b.*\bchickpea\b"), "veggie_chips"),
        # LesserEvil puffs / space balls / onion chips
        (_r(r"\blesserevil\b|\bspaceballs?\b|\bmoonoions?\b|\bintergalactic\b.*\bonion\b"), "veggie_chips"),
        # Market Pantry chips (Target)
        (_r(r"\bmarket\s+pantry\b.*\bchips?\b|\bwavy\s+potato\s+chips?\b|\bclassic\s+potato\s+chips?\b"), "potato_chips"),
        # Carr's table water crackers
        (_r(r"\bcarr.?s\b|\btable\s+water\s+crackers?\b"), "crackers"),
        # Unique Snacks pretzels
        (_r(r"\bunique\s+snacks?\b"), "pretzels"),
        # Wasabi coated green peas
        (_r(r"\bwasabi\b.*\bpeas?\b|\bwasabi\s+coated\b|\bgreen\s+peas?\b.*\bwasabi\b|\bcoated\s+green\s+peas?\b"), "veggie_chips"),
        # Snyder's of Hanover pretzels
        (_r(r"\bsnyder.?s\b|\bhanover\b.*\bpretzel\b"), "pretzels"),
        (_r(r"\bcheetos?\b|\bcheesy\s+puffs?\b|\bcheez\s+puffs?\b"), "cheese_puffs"),
        (_r(r"\bchex\s+mix\b|\bsnack\s+mix\b(?!.*chips?)|\bmunchies\b"), "snack_mix"),
        (_r(r"\bannies?\b.*\bbunnies\b|\bcheddar\s+bunnies\b|\bgoldfish\b"), "cheese_puffs"),
        (_r(r"\bharvest\s+snaps?\b|\bgreen\s+pea\s+snacks?\b|\bsnap\s+peas?\s+crisps?\b"), "veggie_chips"),
        (_r(r"\bwheat\s+thins?\b|\btriscuits?\b"), "crackers"),
        (_r(r"\bpremium\s+saltines?\b|\bsaltine\s+crackers?\b|\boyster\s+crackers?\b"), "crackers"),
        (_r(r"\bpepperidge\s+farm\b.*\bcrackers?\b|\btrio\b.*\bcrackers?\b"), "crackers"),
        (_r(r"\bstacy.?s\b.*\bpita\b|\bpita\s+chips?\b"), "tortilla_chips"),
        (_r(r"\bsun\s*chips?\b"), "tortilla_chips"),
        (_r(r"\btakis?\b|\bextreme\s+fuego\b"), "tortilla_chips"),
        (_r(r"\bkeebler\b.*\bcrackers?\b|\bsandwich\s+crackers?\b"), "crackers"),
        (_r(r"\bquest\b.*\bprotein\s+chips?\b|\bprotein\s+chips?\b"), "veggie_chips"),
        (_r(r"\bmi\s+nina\b|\bon\s+the\s+border\b"), "tortilla_chips"),
        (_r(r"\bwegmans\b.*\bpita\s+crackers?\b|\bsesame\s+seed\s+water\s+crackers?\b"), "crackers"),
        (_r(r"\bwegmans\b.*\bveggie\s+sticks?\b|\bveggie\s+sticks?\b"), "veggie_chips"),
        (_r(r"\bwegmans\b.*\balmond\b.*\bcrackers?\b"), "crackers"),
        (_r(r"\bwegmans\b.*\bhard\s+sourdough\s+pretzels?\b"), "pretzels"),
        (_r(r"\bpatagonia\b.*\bcrackers?\b"), "crackers"),
        (_r(r"\bcombos?\b.*\bpretzel\b|\bbaked\s+pretzels?\b.*\bcombos?\b"), "pretzels"),
        (_r(r"\bdots?\s+homestyle\s+pretzels?\b|\bhoney\s+mustard\s+twists?\b"), "pretzels"),
        (_r(r"\bgratify\b.*\bpretzels?\b|\bgluten\s+free.*\bpretzels?\b.*\bthins?\b"), "pretzels"),
        (_r(r"\bfit\s*joy\b|\bgrain\s+free.*\bcrackers?\b"), "crackers"),
        (_r(r"\bcalbee\b|\btakoyaki\b.*\bcorn\s+snacks?\b"), "veggie_chips"),
        (_r(r"\byolele\b|\bfonio\s+chips?\b"), "tortilla_chips"),
        (_r(r"\bpirates?\s+booty\b|\baged\s+white\s+cheddar\b.*\bpuffs?\b"), "cheese_puffs"),
        (_r(r"\bwilde\b.*\bprotein\s+chips?\b|\bchicken\s+skin\s+crisps?\b|\bflock\b.*\bcrisps?\b"), "veggie_chips"),
        (_r(r"\bcrunchmaster\b|\b5.seed\b.*\bcrackers?\b"), "crackers"),
        (_r(r"\bchicken\s+in\s+a\s+biskit\b"), "crackers"),
        (_r(r"\bosem\b.*\bbissli\b|\bbissli\b"), "veggie_chips"),
        (_r(r"\bmission\b.*\btortilla\s+chips?\b|\bmission\b.*\bstrips?\b.*\bcorn\b"), "tortilla_chips"),
        (_r(r"\butz\b.*\bcheese\s+balls?\b|\bmini\s+cheese\s+balls?\b"), "cheese_puffs"),
        (_r(r"\btom\s+yum\b.*\bsnack\s+mix\b|\bseasoned\s+snack\s+mix\b"), "snack_mix"),
        # Back to Nature crackers
        (_r(r"\bback\s+to\s+nature\b.*\bcrackers?\b|\bclassic\s+round\b.*\bcrackers?\b"), "crackers"),
        # Baked in Brooklyn flatbread crisps
        (_r(r"\bbaked\s+in\s+brooklyn\b|\bflatbread\s+crisps?\b"), "crackers"),
        # Calidad tortilla chips
        (_r(r"\bcalidad\b"), "tortilla_chips"),
        # Chester's fries / flamin hot fries
        (_r(r"\bchester.?s\b|\bchester.?s\s+fries?\b|\bflamin.?\s+hot\s+fries?\b"), "veggie_chips"),
        # Drizzilicious bites (snack context)
        (_r(r"\bdrizzilicious\b"), "other"),
        # Funyuns onion rings
        (_r(r"\bfunyuns?\b|\bonion\s+(?:flavored\s+)?rings?\b"), "veggie_chips"),
        # Golden Rounds crackers
        (_r(r"\bgolden\s+rounds?\b|\bround\s+crackers?\b"), "crackers"),
        # Good & Gather everything crackers / cheddar puffs / onion strings / trail mix
        (_r(r"\bgood\s*&?\s*gather\b.*\beverything\s+crackers?\b"), "crackers"),
        (_r(r"\bgood\s*&?\s*gather\b.*\bcheddar\s+puffs?\b|\borganic\s+white\s+cheddar\s+puffs?\b"), "cheese_puffs"),
        (_r(r"\bgood\s*&?\s*gather\b.*\bonion\s+strings?\b|\bgarlic\s+pepper\s+crispy\s+onion\b|\bfrench\s+fried\s+onions?\b"), "other"),
        (_r(r"\bgood\s*&?\s*gather\b.*\btrail\s+mix\b|\bzen\s+party\s+trail\s+mix\b"), "snack_mix"),
        # Hippeas cheddar puffs
        (_r(r"\bhippeas?\b|\bcheddar\s+pops?\b"), "cheese_puffs"),
        # Kettle Brand potato chips
        (_r(r"\bkettle\s+brand\b|\bkettle\b.*\bpotato\s+chips?\b|\bjalape[nñ]o\b.*\bpotato\s+chips?\b"), "potato_chips"),
        # Market Pantry croutons (salad topper)
        (_r(r"\bmarket\s+pantry\b.*\bcroutons?\b|\bseasoned\s+croutons?\b"), "other"),
        # McVitie's digestive biscuits
        (_r(r"\bmcvitie.?s\b|\bdigestive\s+biscuits?\b"), "crackers"),
        # Nabisco Better Cheddars / Sociables
        (_r(r"\bnabisco\b.*\bbetter\s+cheddars?\b|\bbetter\s+cheddars?\b|\bsociables?\b"), "crackers"),
        # Organic Cacio e Pepe puffs / artisan puffs
        (_r(r"\bcacio\s+e\s+pepe\s+puffs?\b|\bpip.?s\s+heirloom\b|\breal\s+cheddar\s+cheese\s+balls?\b"), "cheese_puffs"),
        # Rold Gold pretzels
        (_r(r"\brold\s+gold\b|\btiny\s+twists?\b"), "pretzels"),
        # Rosemary croissant croutons
        (_r(r"\brosemary\s+croissant\s+croutons?\b|\bcroissant\s+croutons?\b"), "other"),
        # Samyang buldak potato chips
        (_r(r"\bsamyang\b|\bbuldak\b.*\bpotato\b"), "potato_chips"),
        # Sensible Portions veggie straws / garden veggie straws
        (_r(r"\bsensible\s+portions?\b|\bgarden\s+veggie\s+straws?\b|\bveggie\s+straws?\b|\bpotato\s+and\s+vegetable\s+snack\b"), "veggie_chips"),
        # Terra real vegetable chips
        (_r(r"\bterra\b.*\bvegetable\s+chips?\b|\breal\s+vegetable\s+chips?\b"), "veggie_chips"),
        # Toasteds crackers
        (_r(r"\btoasteds?\b.*\bcrackers?\b|\bsea\s+salt.*\bolive\s+oil.*\bcrackers?\b"), "crackers"),
        # Wegmans specific chip/cracker items
        (_r(r"\bwegmans\b.*\brice\s+crackers?\b|\bwegmans\b.*\bancient\s+grains\b.*\bcrackers?\b"), "crackers"),
        (_r(r"\bwegmans\b.*\bcheddar\b.*\bcrunchies?\b|\bwegmans\b.*\bcheese\s+puffs?\b|\bwegmans\b.*\bbaked.*\bcheddar\b"), "cheese_puffs"),
        (_r(r"\bwegmans\b.*\bchickpea\s+snacks?\b|\bsea\s+salt\s+chickpea\b"), "veggie_chips"),
        (_r(r"\bwegmans\b.*\bsea\s+salt\b.*\bvinegar\b.*\bpotato\b|\bwegmans\b.*\bpink\s+himalayan\b.*\bpotato\b"), "potato_chips"),
        # YULU boba (misrouted)
        (_r(r"\byulu\b"), "other"),
        # Chips in a Pickle / pickle chips
        (_r(r"\bchips\s+in\s+a\s+pickle\b|\bpickle\s+chips?\b"), "potato_chips"),
        # Vegan cracklins / barbeque cracklins
        (_r(r"\bvegan\s+cracklins?\b|\bbarbeque.*cracklins?\b"), "veggie_chips"),
    ],

    "pantry.granola_cereals": [
        (_r(r"\binstant\s+oat\b|\binstant\s+oatmeal\b|\bquick\s+oat\b|\bsteelcut\b|\bsteel.cut\b|\bsteel\s+cut\b|\boatmeal\s+packet\b|\bovernight\s+oat\b|\bready.to.eat\s+oat\b|\bmush\b.*\boat\b|\boat\b.*\bmush\b|\boatmeal\b"), "instant_oatmeal"),
        (_r(r"\brolled\s+oat\b|\bwhole\s+rolled\b|\bold\s+fashion\s+oat\b|\bwhole\s+oat\b|\bflaked\s+oat\b"), "rolled_oats"),
        (_r(r"\bmuesli\b|\balpen\b"), "muesli"),
        (_r(r"\bgranola\b"), "granola"),
        (_r(r"\bcream\s+of\s+wheat\b|\bcream\s+of\s+rice\b|\bfarina\b|\bgrits\b|\bpolenta\b.*\bbreakfast\b|\bhot\s+cereal\b|\bmultigrain\s+hot\b|\bporridge\b"), "hot_cereal_mix"),
        # Cold cereal — everything else
        (_r(r"\bcereal\b|\bcheerios\b|\bspecial\s+k\b|\bfrosted\s+flakes\b|\bfroot\s+loops\b|\bcorn\s+pops\b|\bkix\b|\blife\s+cereal\b|\bhoney\s+bunches\b|\bcap.n\s+crunch\b|\bcaptain\s+crunch\b|\bcocoa\s+puffs\b|\blucky\s+charms\b|\bkashi\b|\bnature.s\s+path\b|\bnature\s+valley\b.*\bcereal\b|\bpost\s+cereal\b|\bkellogg\b|\bgeneral\s+mills\b.*\bcereal\b|\bshredded\s+wheat\b|\bcorn\s+flakes\b|\brice\s+krispies\b|\bfrosted\s+mini\b|\bhoney\s+smacks\b"), "cold_cereal"),
        # Old-fashioned / rolled oats that didn't match "rolled oat" pattern above
        (_r(r"\bold.fashioned\s+oats?\b|\bold\s+fashioned\s+oats?\b|\boven\s+toasted\b.*\boats?\b|\bwhole\s+grain\b.*\boats?\b|\bgluten.free\b.*\boats?\b|\bprotein\s+oats?\b|\bquick\s+oats?\b|\bbob.?s\s+red\s+mill\b.*\boats?\b"), "rolled_oats"),
        # Quinoa flakes
        (_r(r"\bquinoa\s+flakes?\b|\bquinoa\s+puffs?\b"), "other"),
        # Buckwheat / sprouted buckwheat crunch (Lil Bucks)
        (_r(r"\bsprouted\s+buckwheat\b|\bbuckwheat\s+crunch\b|\blil\s+bucks\b"), "other"),
        # Baby puffs (misrouted to granola_cereals)
        (_r(r"\bbaby\s+puffs?\b|\bbanana\s+pitaya\b.*\bpuffs?\b|\borganic\b.*\bpuffs?\b.*\bbaby\b"), "other"),
    ],

    "pantry.bars": [
        (_r(r"\bmeal\s+replacement\b|\bmeal\s+bar\b|\bcomplete\s+nutrition\b|\bsoylent\b|\bhuel\b"), "meal_replacement_bar"),
        (_r(r"\bprotein\s+bar\b|\bprotein\s+puff\b|\bprotein\s+donut\b|\bhigh\s+protein\b|\bprotein\b.*\bbar\b|\bbar\b.*\bprotein\b|\brxbar\b|\bquest\s+bar\b|\bone\s+bar\b|\bno\s+cow\b|\bbuilt\s+bar\b|\bthink\s*!\b|\bthinkThin\b|\bclif\s+builder\b|\bpowerbar\b|\bkind\s+protein\b|\blarabar\s+protein\b|\bepic\s+bar\b|\bgni\s+bar\b|\blegendary\s+foods\b"), "protein_bar"),
        (_r(r"\bfruit\s+bar\b|\bfruit\s+&\s+nut\b|\bfruit\s+and\s+nut\b|\blarabar\b|\bthat.s\s+it\b|\bbear\s+naked\b.*\bbar\b|\bjust\s+fruit\b|\bdried\s+fruit\s+bar\b|\bdate\s+bar\b"), "fruit_bar"),
        (_r(r"\bnut\s+bar\b|\bnut\s+&\s+seed\b|\bnut\s+and\s+seed\b|\balmond\s+bar\b|\bkind\s+bar\b|\bkind\b(?!\s+protein)|\bnature\s+valley\b|\bclif\s+nut\b|\bpropel\s+bar\b|\bnuts?\b.*\bbar\b"), "nut_bar"),
        (_r(r"\bgranola\s+bar\b|\bchewy\s+bar\b|\bsoft\s+baked\s+bar\b|\bquaker\b|\bnutri.grain\b|\bgranola\b.*\bbar\b|\bbar\b.*\bgranola\b|\bmade\s*good\b|\bnature.s\s+bakery\b"), "granola_bar"),
        (_r(r"\benergy\s+bar\b|\bclif\s+bar\b|\bclif\b(?!\s+builder|\s+nut)|\bLaRAbar\b|\bkind\s+energy\b|\bpure\s+organic\b.*\bbar\b|\bpowerbar\b"), "energy_bar"),
        (_r(r"\bbreakfast\s+bar\b|\bover\s+easy\b|\bdino\s+bar\b|\bbaby\s+puff\b|\btoddler\s+bar\b|\bkids?\s+bar\b|\bnutrition\s+bar\b"), "granola_bar"),
        # Savory bars (Slow Up brand)
        (_r(r"\bslow\s+up\b|\bsavory\s+bar\b|\bpoblano\b.*\bbar\b|\bpesto\b.*\bbar\b|\bcurry\b.*\bbar\b|\bcalabrian\b.*\bbar\b|\bmapel\s+pecan\s+bar\b"), "energy_bar"),
        # Fruit sauce / fruit squeeze (GoGo Squeez, crushers — misrouted)
        (_r(r"\bfruit\s+sauce\s+crusher\b|\bapplesauce\s+crusher\b|\bfruit\s+crushers?\b|\borganic\s+apple.*fruit\s+sauce\b|\bfruit\s+squeeze\b"), "other"),
        # Bob's Red Mill bars
        (_r(r"\bbob.?s\s+red\s+mill\b.*\bbar\b|\bbob.s\s+bar\b"), "granola_bar"),
        # Cloudy Lane Bakery chocolate ganache bars (baked goods, not bars)
        (_r(r"\bcloudy\s+lane\b|\bganache\s+bar\b|\bchocolate\s+ganache\s+bar\b"), "other"),
        # Baby/toddler puffs (Little Spoon puffs misrouted to bars)
        (_r(r"\bbaby\s+puffs?\b|\btoddler\s+puffs?\b|\bkale.*puffs?\b|\bapple.*puffs?\b|\bcurl\s+puffs?\b|\bbanana.*puffs?\b"), "other"),
        # Maca / superfood energy bars
        (_r(r"\bmaca\b.*\bbar\b|\bsuperfood\b.*\bbar\b|\benergy\s+bars?\b"), "energy_bar"),
        # Perfect Bar (refrigerated nut butter bars)
        (_r(r"\bperfect\s+bar\b|\borganic\s+peanut\s+butter\s+bar\b"), "nut_bar"),
        # Taos Bakes / toasted coconut bars
        (_r(r"\btaos\s+bakes?\b|\btoasted\s+coconut\b.*\bbar\b|\bcoconut.*vanilla.*bar\b"), "energy_bar"),
        # Nelly's / peanut butter coconut bars
        (_r(r"\bnelly.?s\b.*\bbar\b|\bpeanut\s+butter\s+coconut\b.*\bbar\b"), "granola_bar"),
        # Date & nut bars (Good & Gather)
        (_r(r"\bdate\s+and\s+nut\b|\bdate\s+&\s+nut\b|\bcookie\s+dough\s+bar\b"), "fruit_bar"),
        # Toddler biscuits (Good & Gather Organic Beetroot Biscuit)
        (_r(r"\bbeetroot\s+biscuit\b|\btoddler\s+biscuit\b|\bbaby\s+biscuit\b"), "other"),
        # Once Upon a Farm snack bars (oat bars)
        (_r(r"\bonce\s+upon\s+a\s+farm\b.*\bbar\b|\bonce\s+upon\s+a\s+farm\b.*\boat\b|\bonce\s+upon\s+a\s+farm\s+bars?\b|\bfarm\b.*\bsnack\s+bars?\b.*\boat\b|\bsoft.baked\b.*\bbanana\b|\bfarm\b.*\bbanana\s+choc\s+chip\b"), "granola_bar"),
        # Good & Gather nutrition bars (cashew cookie, apple pie)
        (_r(r"\bgood\s*&?\s*gather\b.*\bnutrition\s+bars?\b|\bcashew\s+cookie\s+nutrition\b|\bapple\s+pie\s+nutrition\b"), "nut_bar"),
        # IQBAR protein bars
        (_r(r"\biqbar\b"), "protein_bar"),
        # Epic bars / uncured bacon bar
        (_r(r"\bepic\b.*\bbar\b|\buncured\s+bacon\b.*\bbar\b|\bbison\s+bar\b"), "protein_bar"),
        # Alyssa's chocobites / healthy bites
        (_r(r"\balyssa.?s\b.*\bchocobites?\b|\balyssa.?s\b.*\bbites?\b|\bchocobites?\b"), "granola_bar"),
        # Nelly's Organics bars
        (_r(r"\bnelly.?s\s+organics?\b.*\bbar\b|\bpeanut\s+butter\s+coconut\b.*\bbar\b"), "granola_bar"),
        # Fruit sauce crushers / applesauce pouches (misrouted)
        (_r(r"\bfruit\s+sauce\s+crushers?\b|\bapple\s+cinnamon\s+fruit\s+sauce\b|\bapple\s+banana\s+fruit\s+sauce\b|\borganic\s+apple\s+(?:cinnamon|banana)\b.*\bcrusher\b"), "other"),
        # Aloha protein bars
        (_r(r"\baloha\b.*\bprotein\b|\baloha\b.*\bbar\b"), "protein_bar"),
        # Atkins bars / endulge
        (_r(r"\batkins\b.*\bbar\b|\batkins\b.*\bendulge\b|\batkins\b.*\bsnack\b"), "protein_bar"),
        # Barebells nutrition bars
        (_r(r"\bbarebells?\b"), "protein_bar"),
        # Bobo's PB&J / oat bars
        (_r(r"\bbobos?\b|\bpb&j\b.*\boat\b|\bgrape\s+pb.*\bj\b"), "granola_bar"),
        # Clio yogurt bars (snack bar format)
        (_r(r"\bclio\s+snacks?\b|\bclio\b.*\byogurt\b.*\bbar\b"), "protein_bar"),
        # David bar / peanut butter chocolate chunk
        (_r(r"\bdavid\b.*\bpeanut\s+butter\b.*\bbar\b"), "protein_bar"),
        # Fiber One soft-baked bars
        (_r(r"\bfiber\s+one\b.*\bbar\b|\bsoft.baked\s+bars?\b.*\bfiber\b"), "granola_bar"),
        # Genius Gourmet keto bars
        (_r(r"\bgenius\s+gourmet\b.*\bbar\b|\bketo\s+bar\b"), "protein_bar"),
        # GoMacro MacroBar
        (_r(r"\bgomacro\b|\bmacrobar\b"), "protein_bar"),
        # Goodie Girl breakfast biscuits
        (_r(r"\bgoodie\s+girl\b.*\bbiscuits?\b|\bbreakfast\s+biscuits?\b"), "granola_bar"),
        # Hillshire snacking deli kits (misrouted to bars)
        (_r(r"\bhillshire\b.*\bsnacking\b|\buncured\s+pepperoni\b.*\bwhite\s+cheddar\b"), "other"),
        # Kodiak breakfast bars / granola bars
        (_r(r"\bkodiak\b.*\bbar\b|\bkodiak\b.*\bgranola\b"), "granola_bar"),
        # Lenny & Larry's cookie-fied bar
        (_r(r"\blenny\s*&?\s*larry.?s\b|\bcookie.?fied\s+bar\b"), "protein_bar"),
        # Luna bars
        (_r(r"\bluna\b.*\bbar\b|\bluna\b.*\bsnack\b"), "protein_bar"),
        # Magic Spoon cereal bars
        (_r(r"\bmagic\s+spoon\b.*\bbar\b|\bcereal\s+bars?\b.*\bmagic\b"), "granola_bar"),
        # Nature's Bakery fig bars
        (_r(r"\bnatures?\s+bakery\b|\bfig\s+bar\b"), "granola_bar"),
        # NuGo nutrition bars
        (_r(r"\bnugo\b"), "protein_bar"),
        # Olyra baked bites
        (_r(r"\bolyra\b|\bsoft\s+baked\s+bites?\b.*\borganic\b"), "granola_bar"),
        # Pamela's oat bars
        (_r(r"\bpamela.?s\b.*\bbar\b|\bwhenever\s+bars?\b"), "granola_bar"),
        # Quest cookies (cookie-bar hybrid)
        (_r(r"\bquest\b.*\bcookies?\b|\bquest\b.*\bprotein\s+cookie\b"), "protein_bar"),
        # Simple Mills soft baked bars
        (_r(r"\bsimple\s+mills\b.*\bbar\b|\bsoft\s+baked.*\balmond\s+flour\b.*\bbar\b"), "granola_bar"),
        # Special K protein bars
        (_r(r"\bspecial\s+k\b.*\bprotein\b|\bspecial\s+k\b.*\bbar\b"), "protein_bar"),
        # Wegmans granola bars / fruit & grain bars
        (_r(r"\bwegmans\b.*\bgranola\s+bars?\b|\bwegmans\b.*\bfruit\s*&?\s*grain\b|\bwegmans\b.*\bwholesum\b"), "granola_bar"),
        # Zbar organic granola bars
        (_r(r"\bzbar\b"), "granola_bar"),
        # Annie's chewy granola bars
        (_r(r"\bannies?\b.*\bchewy\b|\bannies?\b.*\bgranola\b"), "granola_bar"),
        # Oats Overnight bars/balls
        (_r(r"\boats\s+overnight\b.*\bbar\b|\bsimplyfuel\b|\bwhey\s+protein\s+balls?\b"), "protein_bar"),
        # Good & Gather whole grain baked bars / toddler snacks
        (_r(r"\bgood\s*&?\s*gather\b.*\bgrain\b.*\bbar\b|\bgood\s*&?\s*gather\b.*\btoddler\s+snacks?\b"), "granola_bar"),
        # Drizzilicious rice cakes (misrouted to bars)
        (_r(r"\bdrizzilicious\b.*\brice\s+cake\b|\bdrizzled\b.*\brice\s+cake\b"), "other"),
        # Oats Overnight shake (misrouted to bars)
        (_r(r"\boats\s+overnight\b.*\bshake\b"), "other"),
        # Raspberry oat bites / protein balls catch-all
        (_r(r"\bprotein\s+balls?\b|\boat\s+bites?\b.*\bberry\b|\braspberry\s+oat\b"), "protein_bar"),
        # 88 Acres seed + oat bars
        (_r(r"\b88\s+acres?\b|\bseed\s*\+\s*oat\s+bars?\b"), "protein_bar"),
        # Atkins protein cookies (bar context)
        (_r(r"\batkins\b.*\bprotein\s+cookies?\b|\batkins\b.*\bclusters?\b"), "protein_bar"),
        # Blake's Seed Based crispy treats
        (_r(r"\bblake.?s\s+seed\s+based\b|\bcrispy\s+treats?\b.*\bseed\b"), "granola_bar"),
        # Cloudy Lane blondie / ganache bars
        (_r(r"\bcloudy\s+lane\b"), "granola_bar"),
        # Drizzilicious (misrouted from chips/baked to bars)
        (_r(r"\bdrizzilicious\b"), "other"),
        # FITCRUNCH whey snack bars
        (_r(r"\bfitcrunch\b|\bbaked\s+whey\s+snack\s+bars?\b"), "protein_bar"),
        # Five Seed Almond Bars
        (_r(r"\bfive\s+seed\b.*\balmond\b|\bfive\s+seed\s+almond\s+bars?\b"), "protein_bar"),
        # Good & Gather confetti cake muffin bars / apple cinnamon fruit & grain bars
        (_r(r"\bgood\s*&?\s*gather\b.*\bconfetti\s+cake\b.*\bbar\b|\bgood\s*&?\s*gather\b.*\bmuffin\s+bars?\b"), "granola_bar"),
        (_r(r"\bgood\s*&?\s*gather\b.*\bapple\s+cinnamon\b.*\bfruit\s*&?\s*grain\b"), "granola_bar"),
        # Hail Merry key lime pie cups (raw dessert)
        (_r(r"\bhail\s+merry\b|\bkey\s+lime\s+pie\s+cups?\b"), "other"),
        # Honey Stinger waffles
        (_r(r"\bhoney\s+stinger\b|\benergy\s+waffle\b|\bwaffle\b.*\bhoney\b"), "granola_bar"),
        # Kodiak s'mores chewy bars / power cups
        (_r(r"\bkodiak\b.*\bpower\s+cups?\b|\bkodiak\b.*\bchewy\s+bars?\b|\bkodiak\b.*\bs.?mores?\b"), "granola_bar"),
        # Market Pantry breakfast bars / granola bars
        (_r(r"\bmarket\s+pantry\b.*\bbreakfast\s+bars?\b|\bmarket\s+pantry\b.*\bgranola\s+bars?\b|\bmarket\s+pantry\b.*\bsoft\s+baked\b"), "granola_bar"),
        # Misfits Health plant based protein bars
        (_r(r"\bmisfits\s+health\b|\bplant\s+based.*\bprotein\s+bars?\b.*\bvegan\b"), "protein_bar"),
        # Protein One bars
        (_r(r"\bprotein\s+one\b|\bprotein\s+1\b"), "protein_bar"),
        # Pure Protein bars
        (_r(r"\bpure\s+protein\b"), "protein_bar"),
        # Quest muffins bake shop
        (_r(r"\bquest\b.*\bmuffins?\b"), "granola_bar"),
        # Special K pastry crisps
        (_r(r"\bspecial\s+k\b.*\bpastry\s+crisps?\b|\bpastry\s+crisps?\b"), "granola_bar"),
        # belVita fruit bakes / breakfast bars
        (_r(r"\bbelvita\b.*\bfruit\s+bakes?\b|\bbelvita\b.*\bbreakfast\s+bars?\b"), "granola_bar"),
    ],

    "pantry.condiments_dressings": [
        # Named-label rules come FIRST to avoid being shadowed by broad catch-alls
        # Mayonnaise brands
        (_r(r"\bhellmann.?s\b|\bbest\s+foods?\b.*\bmayo\b|\bbest\s+foods\b.*\bmayonnaise\b"), "mayo"),
        (_r(r"\bkewpie\b"), "mayo"),
        (_r(r"\bdukes?\s+mayo\b|\bduke.?s\b.*\bmayo\b|\bduke.?s\b.*\bmayonnaise\b"), "mayo"),
        (_r(r"\bsir\s+kensington.?s\b.*\bmayo\b|\bsir\s+kensington\b.*\bvegenaise\b|\bsir\s+kensington\b"), "mayo"),
        (_r(r"\bfollow\s+your\s+heart\b.*\bvegenaise\b|\bvegenaise\b|\bfollow\s+your\s+heart\b.*\bmayo\b"), "mayo"),
        (_r(r"\bprimal\s+kitchen\b.*\bmayo\b|\bchosen\s+foods?\b.*\bmayo\b|\bfabalish\b"), "mayo"),
        (_r(r"\bayoh?!?\b|\bsando\s+sauce\b"), "mayo"),
        (_r(r"\bwegmans\b.*\bmayo\b|\bwegmans\b.*\bmayonnaise\b|\bwegmans\b.*\bvegenaise\b"), "mayo"),
        (_r(r"\bcadia\b.*\bmayo\b|\borganic\s+mayo\b|\breal\s+mayo\b|\blight\s+mayo\b|\bsqueeze.*\bmayo\b|\bmarket\s+pantry\b.*\bmayo\b"), "mayo"),
        (_r(r"\btruff\b.*\bmayo\b|\btruff\s+mayonnaise\b|\btruffle.*\bmayo\b"), "mayo"),
        (_r(r"\baioli\b(?!.*garlic\s+mustard)"), "mayo"),
        (_r(r"\bmayo\b|\bmayonnaise\b|\bvegan\s+mayo\b|\bplant.based\s+mayo\b"), "mayo"),
        # Tahini
        (_r(r"\bcava\b.*\btahini\b|\blemon\s+herb\s+tahini\b"), "tahini"),
        (_r(r"\btahini\b(?!.*dip)|\bsesame\s+paste\b|\bsweet\s+tahini\b|\bgolden\s+tahini\b|\blemon.*tahini\b|\btahini.*lemon\b"), "tahini"),
        # Salsa brands (named)
        (_r(r"\bherdez\b|\bcasera\b.*\bsalsa\b|\btaqueria\b.*\bsauce\b"), "salsa"),
        (_r(r"\bpace\b(?!.*picante)|\bpace\b.*\bsalsa\b|\bpicante\s+sauce\b"), "salsa"),
        (_r(r"\bxochitl\b.*\bsalsa\b|\bxochitl\s+salsa\b"), "salsa"),
        (_r(r"\bsantitas\b.*\bsalsa\b"), "salsa"),
        (_r(r"\bortega\b.*\btaco\s+sauce\b|\bla\s+victoria\b.*\btaco\s+sauce\b|\bortega\b.*\bsalsa\b"), "salsa"),
        (_r(r"\btostitos\b.*\bsalsa\b"), "salsa"),
        (_r(r"\bcholula\b.*\bsalsa\b"), "salsa"),
        (_r(r"\bwegmans\b.*\bsalsa\b"), "salsa"),
        (_r(r"\bgood\s*&?\s*gather\b.*\bsalsa\b"), "salsa"),
        (_r(r"\bsalsa\b"), "salsa"),
        # Horseradish
        (_r(r"\bhorserad\b|\bprepared\s+horserad\b|\bba.tampte\b|\bholy\s+schmitt.?s\b|\bbeet\s+horseradish\b|\bgold.?s\b.*\bhorseradish\b|\bkelchner.?s\b.*\bhorseradish\b|\bwoeber.?s\b.*\bhorseradish\b"), "mustard"),
        (_r(r"\btomato\s+paste\b|\bdouble\s+concentrated\s+tomato\b|\bconcentrated\s+tomato\b"), "pasta_sauce"),
        (_r(r"\bpizza\s+sauce\b|\bsmooth\s+pizza\b|\bamore\s+pizza\b"), "pasta_sauce"),
        (_r(r"\blemon\s+juice\b|\blime\s+juice\b|\bsicilian\s+lemon\b|\bcitrus\s+juice\b.*\bcooking\b"), "other"),
        (_r(r"\bcooking\s+sauce\b|\bsimmer\s+sauce\b|\btagine\b|\bshakshuka\b|\bcurry\s+sauce\b|\btikka\s+masala\s+sauce\b|\bmole\b|\bstir.fry\s+sauce\b|\bteriyaki\s+cooking\b|\bkorea\b.*\bsauce\b"), "marinade"),
        # Turkey brine / marinating kits
        (_r(r"\bbrine\s+kit\b|\bbrining\s+kit\b|\bturkey\s+brine\b|\bmarinate\s+kit\b|\bherb\s+and\s+brine\b"), "marinade"),
        (_r(r"\bpasta\s+sauce\b|\bmarinara\b|\barrabbiata\b|\bbolognese\b|\bpomodoro\b|\btomato\s+sauce\b|\bspaghetti\s+sauce\b|\bputtanesca\b|\bamatriciana\b|\bcacio\s+e\s+pepe\b|\bvodka\s+sauce\b|\brao.s\b|\brao\b|\bcarbone\s+sauce\b|\btomato\s+basil\s+sauce\b|\broasted\s+garlic\s+sauce\b"), "pasta_sauce"),
        (_r(r"\balfredo\b|\bcarbonara\s+sauce\b|\bcream\s+sauce\b.*\bpasta\b"), "alfredo_sauce"),
        (_r(r"\bpesto\b"), "pesto"),
        (_r(r"\bbarbecue\s+sauce\b|\bbbq\s+sauce\b|\bbbq\b.*\bsauce\b|\bsauce\b.*\bbbq\b"), "bbq_sauce"),
        (_r(r"\bhot\s+sauce\b|\bsriracha\b|\btabasco\b|\bfranka?\b.*\bred\s+hot\b|\bcrystal\s+hot\b|\bcholula\b|\bvalentina\b|\bbuffalo\s+sauce\b|\bchili\s+garlic\s+sauce\b|\bsambal\b|\bgochujang\b|\bharissa\b"), "hot_sauce"),
        (_r(r"\bketchup\b|\bcatsup\b"), "ketchup"),
        (_r(r"\bmustard\b(?!\s+powder|\s+seed)"), "mustard"),
        (_r(r"\bsoy\s+sauce\b|\btamari\b|\bteriyaki\s+sauce\b|\bponzu\b|\bmirin\b|\bfish\s+sauce\b|\bhoisin\b|\boyster\s+sauce\b|\bworcestershire\b|\bumami\s+sauce\b|\bshoyu\b"), "soy_sauce"),
        (_r(r"\bmarinade\b|\binjection\b.*\bsauce\b|\bsauce\b.*\binjection\b|\bglaze\b|\brub\b.*\bwet\b|\blemon\s+pepper\s+sauce\b|\bfajita\s+sauce\b|\bteriyaki\s+marinade\b"), "marinade"),
        (_r(r"\bgravy\b|\bau\s+jus\b"), "gravy"),
        (_r(r"\bsalad\s+dressing\b|\bdressing\b|\bvinaigrette\b|\branch\b|\bcaesar\b|\bblue\s+cheese\s+dressing\b|\bthousand\s+island\b|\bitalian\s+dressing\b|\bbalsamic\b.*\bdressing\b|\bgreen\s+goddess\s+dressing\b"), "salad_dressing"),
        # Pico de gallo / salsa variants not caught above
        (_r(r"\bpico\b"), "salsa"),
        # Kimchi paste / kimchi sauce
        (_r(r"\bkimchi\s+paste\b|\bkimchi\s+sauce\b"), "other"),
        # Preserved lemons / lemon paste
        (_r(r"\bpreserved\s+lemon\b|\blemon\s+paste\b"), "other"),
        # Cranberry sauce / apple sauce (condiment context)
        (_r(r"\bcranberry\s+sauce\b|\bapplesauce\b|\bapple\s+sauce\b"), "other"),
        # Liquid aminos / bragg
        (_r(r"\bliquid\s+aminos?\b|\bbragg\b.*\bamino\b|\bamino\s+acid\b"), "soy_sauce"),
        # Rose water / flower waters (Persian/Middle Eastern)
        (_r(r"\brose\s+water\b|\bfloral\s+water\b|\borange\s+blossom\s+water\b"), "other"),
        # Kombucha vinegar (Yesfolk)
        (_r(r"\bkombucha\s+vinegar\b|\byesfolk\b|\bblack\s+dragon\s+kombucha\b|\bmixto\s+kombucha\b"), "vinegar"),
        # Pasta (misrouted to condiments)
        (_r(r"\belbows?\b.*\bpasta\b|\bbarilla\b.*\bpasta\b|\brotini\b|\bmacaroni\b.*\bpasta\b"), "other"),
        # Pickle juice
        (_r(r"\bpickle\s+juice\b"), "other"),
        # Kentuckyaki / teriyaki-style sauces not caught above
        (_r(r"\bkentuckyaki\b|\bteriyaki\b"), "marinade"),
        # Bacon marmalade / fruit + meat condiment
        (_r(r"\bbacon\s+marmalade\b|\bonion\s+marmalade\b|\bpancetta\b.*\bjam\b"), "other"),
        # Curry paste (Thai, Indian)
        (_r(r"\bcurry\s+paste\b|\bred\s+curry\s+paste\b|\bgreen\s+curry\s+paste\b|\byellow\s+curry\s+paste\b"), "marinade"),
        # Pumfu / specialty condiment items misrouted here
        (_r(r"\bpumfu\b|\bfoodies\b"), "other"),
        # Chipotle salsa / roasted salsa / Pace salsa — covered by salsa rules above
        # Horseradish catch (covered by earlier rule, keep as safety)
        (_r(r"\bba.tampte\b|\bholy\s+schmitt.?s\b|\bprepared\s+horseradish\b|\bbeet\s+horseradish\b"), "mustard"),
        # Cocktail sauce (tomato + horseradish)
        (_r(r"\bcocktail\s+sauce\b"), "ketchup"),
        # Frank's RedHot (original cayenne pepper sauce)
        (_r(r"\bfrank.?s\s+redhot\b|\bcayenne\s+pepper\s+sauce\b"), "hot_sauce"),
        # Ghostly Louisiana pepper sauce
        (_r(r"\bghostly\b.*\bpepper\s+sauce\b|\blouis\w*\s+pepper\s+sauce\b"), "hot_sauce"),
        # Carbone tomato basil sauce
        (_r(r"\bcarbone\b.*\btomato\b|\bcarbone\b.*\bsauce\b"), "pasta_sauce"),
        # First Field cranberry sauce
        (_r(r"\bfirst\s+field\b|\bcranberry\s+sauce\b"), "other"),
        # Sicilian lemon juice (cooking use)
        (_r(r"\bsicilian\s+lemon\s+juice\b|\b100%\s+sicilian\s+lemon\b"), "other"),
        # Cava tahini now handled by earlier rule
        # Miso paste (white, red)
        (_r(r"\bhikari\s+miso\b|\bmiso\s+paste\b|\bwhite\s+miso\b|\bred\s+miso\b"), "soy_sauce"),
        # Chili kit / Texas chili
        (_r(r"\bcarroll\s+shelby.?s\b|\btexas\s+chili\b|\bchili\s+kit\b"), "other"),
        # Kikkoman fish sauce / umami joy
        (_r(r"\bkikkoman\b.*\bfish\s+sauce\b|\bumami\s+joy\b"), "soy_sauce"),
        # Enchilada sauce (Siete brand)
        (_r(r"\benchilada\s+sauce\b|\bsiete\b.*\benchilada\b"), "marinade"),
        # Quince paste / membrillo
        (_r(r"\bmembrillo\b|\bquince\s+paste\b"), "other"),
        # Pace / Xochitl / Good&Gather salsa — covered above
        # Coconut aminos / soy-free seasoning sauces
        (_r(r"\bcoconut\s+aminos?\b|\bcoconut\s+secret\b|\bsoy.free\s+seasoning\b"), "soy_sauce"),
        # Mayo brands (avocado oil etc) — covered above
        # Hot Ones hot sauce
        (_r(r"\bhot\s+ones\b|\blos\s+calientes\b"), "hot_sauce"),
        # Achaar / Indian pickle / chutney condiments (Brooklyn Delhi)
        (_r(r"\bachaar\b|\bbrooklyn\s+delhi\b|\bpatak.?s\b|\bmajor\s+grey\b|\bchutney\b"), "other"),
        # Minced garlic in water (Wegmans Italian Classics)
        (_r(r"\bminced\s+garlic\s+in\s+water\b|\bgarlic\b.*\bin\s+water\b"), "other"),
        # Dijon mustard
        (_r(r"\bdijon\b|\bamerican\s+dijon\b"), "mustard"),
        # Tomato purée / heirloom tomato purée
        (_r(r"\bheirloom\s+tomato\s+pur[ée]e\b|\bsun\s+sprout\b"), "pasta_sauce"),
        # Fresh tomato & basil sauce (La Trafila)
        (_r(r"\bfresh\s+tomato\s*&\s*basil\s+sauce\b|\bla\s+trafila\b"), "pasta_sauce"),
        # Spicy tomato oil / spicy oil condiments
        (_r(r"\bspicy\s+tomato\s+oil\b|\bchili\s+oil\b|\bspicy\s+oil\b"), "hot_sauce"),
        # Salsa verde / roja
        (_r(r"\bsalsa\s+roja\b|\bla\s+esquina\b|\bsalsa\s+diablo\b|\bcharred\s+hot\s+salsa\b|\bhabanero\s+ghost\s+pepper\s+salsa\b"), "other"),
        # Sofrito (Eleven Madison Home)
        (_r(r"\beleven\s+madison\b|\bspicy\s+tomato\s+sofrito\b"), "other"),
        # Chimichurri sauce
        (_r(r"\bherby\s+chimichurri\b|\bchimichurri\s+sauce\b"), "other"),
        # Crunchy Asian hot topping
        (_r(r"\bcrunchy\s+asian\b|\bhot\s+topping\s+blend\b"), "other"),
        # Mayonnaise brands
        (_r(r"\bhellmann.?s\b.*\bmayo\b|\bbest\s+foods\b.*\bmayo\b|\bhellmann.?s\b.*\bmayonnaise\b|\bbest\s+foods\b.*\bmayonnaise\b"), "mayo"),
        (_r(r"\bchosen\s+foods\b.*\bmayo\b|\bfabalish\b|\bplant.based\s+mayo\b|\bvegan\s+mayo\b"), "mayo"),
        (_r(r"\bayoh?!?\b.*\bmayo\b|\bwegmans\b.*\bmayo\b|\borganic\s+mayo\b|\breal\s+mayo\b|\blight\s+mayo\b|\bmayo\s+sando\b"), "mayo"),
        (_r(r"\bmiracle\s+whip\b|\bmike.?s\s+amazing\s+mayo\b|\bcadia\b.*\bmayo\b"), "mayo"),
        (_r(r"\bmarket\s+pantry\b.*\bmayo\b|\bsqueeze\b.*\bmayo\b"), "mayo"),
        (_r(r"\bfollow\s+your\s+heart\b.*\bvegenaise\b|\bvegenaise\b"), "mayo"),
        # Sweet sauces / syrups
        (_r(r"\bsmucker.?s\b.*\bsyrup\b|\bsmucker.?s\b.*\bfudge\b|\bsmucker.?s\b.*\bmarshmal\b|\bsmucker.?s\b.*\btopping\b"), "other"),
        (_r(r"\bkaro\b.*\bcorn\s+syrup\b|\blight\s+corn\s+syrup\b"), "other"),
        # Chili crisp / hot oil
        (_r(r"\bfly\s+by\s+jing\b|\bsichuan\s+chili\s+crisp\b|\bchili\s+crisp\b|\bchili\s+crunch\b|\bmomofuku\b.*\bchili\b"), "chili_sauce"),
        # Relish / sweet relish / dill relish
        (_r(r"\borganic\s+sweet\s+relish\b|\borganic\s+dill\s+relish\b|\bsweet\s+relish\b|\bdill\s+relish\b"), "relish"),
        # Sweet Thai chili / spicy chili sauces
        (_r(r"\bsweet\s+thai\s+chili\b|\bsweet\s+chili\s+sauce\b|\bspicy\s+orange\s+sauce\b|\bspicy\s+szechuan\b|\bthai\s+coconut\s+sauce\b"), "chili_sauce"),
        # Panda Express sauces
        (_r(r"\bpanda\s+express\b"), "dipping_sauce"),
        # Manwich / sloppy joe
        (_r(r"\bmanwich\b|\bsloppy\s+joe\s+sauce\b|\bsloppy\s+joes?\s+seasoning\b|\bmccormick\b.*\bsloppy\b"), "cooking_paste"),
        # Tahini sauces / golden turmeric tahini
        (_r(r"\bgolden\s+turmeric\s+tahini\b"), "tahini"),
        # DeLallo bruschetta
        (_r(r"\bdelallo\b.*\bbruschetta\b"), "other"),
        # Asian sauces — unagi / kikkoman
        (_r(r"\bkikkoman\b.*\bunagi\b|\bunagi\s+sauce\b"), "other"),
        # Quince paste / membrillo
        (_r(r"\bmitica\b.*\bmembrillo\b|\bquince\s+paste\b|\bmembrillo\b"), "other"),
        # Bacon marmalade / savory jams
        (_r(r"\bbacon\s+marmalade\b|\bsavory\s+jam\b"), "other"),
        # Ortega / La Victoria / Pace sauces (already have salsa pattern, these are cooking sauces)
        (_r(r"\bortega\b.*\btaco\s+sauce\b|\bla\s+victoria\b.*\btaco\s+sauce\b|\bpace\b.*\bpicante\b"), "salsa"),
        # Chick-fil-a sauces
        (_r(r"\bchick.?fil.?a\b"), "dipping_sauce"),
        # Laxmi garlic paste / curry pastes
        (_r(r"\blaxmi\b.*\bpaste\b|\bgarlic\s+paste\b"), "cooking_paste"),
        # Lemongrass BBQ starter / cooking sauce
        (_r(r"\blemongrass\s+bbq\b|\bbbq\s+starter\b"), "bbq_sauce"),
        # Hollandaise / morel / lemon butter — now handled by gravy/alfredo rules below
        (_r(r"\bhollandaise\s+sauce\b|\bmorel\s+sauce\b"), "gravy"),
        # Kevin's Natural Foods sauce
        (_r(r"\bkevin.?s\s+natural\s+foods\b.*\bsauce\b|\bkevin.?s\b.*\bsauce\b"), "marinade"),
        # Badia minced garlic in oil
        (_r(r"\bbadia\b.*\bgarlic\b|\bminced\s+garlic\s+in\s+oil\b"), "cooking_paste"),
        # Buffalo Wild Wings sauce / wing sauces
        (_r(r"\bbuffalo\s+wild\s+wings?\b|\bparmesan\s+garlic\s+sauce\b|\bwing\s+sauce\b"), "hot_sauce"),
        # Charleston Bloody Mary mix
        (_r(r"\bcharleston\b.*\bbloody\s+mary\b|\bbloody\s+mary\s+mix\b"), "dipping_sauce"),
        # Colgin liquid smoke
        (_r(r"\bcolgin\b|\bliquid\s+smoke\b"), "marinade"),
        # Daiya cheese sauce (condiment context)
        (_r(r"\bdaiya\b.*\bcheese\s+sauce\b|\bdairy.free\b.*\bcheddar\s+sauce\b"), "alfredo_sauce"),
        # El Yucateco extra hot habanero
        (_r(r"\bel\s+yucateco\b"), "hot_sauce"),
        # Foodies pumfu (misrouted)
        (_r(r"\bfoodies\b.*\bpumfu\b|\bpumfu\b"), "other"),
        # Good & Gather thai peanut sauce
        (_r(r"\bthai\s+peanut\s+sauce\b|\bpeanut\s+sauce\b"), "other"),
        # Herdez taqueria street sauce / salsa
        (_r(r"\bherdez\b|\bcasera\b.*\bsalsa\b|\btaqueria\b.*\bsauce\b"), "salsa"),
        # Italian bomba hot pepper sauce
        (_r(r"\bitalian\s+bomba\b|\bhot\s+pepper\s+sauce\b"), "hot_sauce"),
        # Kelchner's tartar sauce — handled below by dipping_sauce rules
        # Kewpie mayonnaise — handled above
        # Kikkoman sweet & sour sauce
        (_r(r"\bkikkoman\b.*\bsweet\b.*\bsour\b|\bsweet\s*&?\s*sour\s+sauce\b"), "dipping_sauce"),
        # Lee Kum Kee sriracha mayo — handled above
        # Lipton onion soup mix (dip context)
        (_r(r"\blipton\b.*\bonion\s+soup\b|\bonion\s+soup.*\bdip\s+mix\b"), "cooking_paste"),
        # Mrs. Richardson's / dessert sauces — handled below
        # Panda Express mandarin sauce — handled above
        # Smucker's toppings — handled below
        # TORANI / Walden Farms — handled below
        # Wasabi condiment
        (_r(r"\bsushi\s+wasabi\b|\bwasabi\s+paste\b|\bculinary.*wasabi\b|\bs\s*&\s*b\s+wasabi\b|\bwasabi\b"), "dipping_sauce"),
        # Wegmans condiment items — handled by newer rules below
        # Spicy dynamite sauce (general catch)
        (_r(r"\bspicy\s+dynamite\b|\bdynamite\s+sauce\b"), "dipping_sauce"),
        # A.1. / steak sauces
        (_r(r"\ba\.?1\.?\b.*\bsauce\b|\bsteak\s+sauce\b|\bpeter\s+luger\b"), "marinade"),
        # Bachan's / dipping sauces
        (_r(r"\bbashan.?s\b|\bbackyard\s+barbecue\b|\bboss\s+sauce\b|\bcapital\s+city\b.*\bsauce\b|\bmambo\s+sauce\b"), "bbq_sauce"),
        # Bertolli / Classico / Ragu cheese/rose sauce
        (_r(r"\bbertolli\b.*\bsauce\b|\bclassico\b.*\brose\b|\bclassico\b.*\bsauce\b|\bragu\b.*\bcheese\s+sauce\b|\bragu\b.*\bparmesan\b"), "alfredo_sauce"),
        # Ragu Old World Style (pasta sauce)
        (_r(r"\bragu\b.*\bold\s+world\b|\bragu\b.*\btraditional\b"), "pasta_sauce"),
        # Sriracha mayo / Wegmans sriracha mayo
        (_r(r"\bsriracha\s+mayo\b|\bwegmans\b.*\bsriracha\s+mayo\b"), "mayo"),
        # Wegmans mayo / vegan mayo
        (_r(r"\bwegmans\b.*\bvegan\s+mayo\b|\bwegmans\b.*\bmayo\b"), "mayo"),
        # Wegmans misc sauces not yet caught
        (_r(r"\bwegmans\b.*\bsteak\s+sauce\b|\bwegmans\b.*\bbuffalo\b"), "marinade"),
        (_r(r"\bwegmans\b.*\btartar\b|\bwegmans\b.*\bremoulade\b|\bwegmans\b.*\byum\s+yum\b"), "other"),
        (_r(r"\bwegmans\b.*\bchili\s+sauce\b|\bwegmans\b.*\bcheddar\b|\bwegmans\b.*\bbearnaise\b"), "other"),
        (_r(r"\bwegmans\b.*\bdipping\s+sauce\b|\bwegmans\b.*\bsummer\s+roll\b|\bwegmans\b.*\bpoke\s+sauce\b"), "other"),
        (_r(r"\bwegmans\b.*\bmorel\s+sauce\b|\bwegmans\b.*\bmushroom\s+sauce\b|\bwegmans\b.*\bpeppercorn\b"), "gravy"),
        (_r(r"\bwegmans\b.*\bamore\b|\bwegmans\b.*\blemon\s+butter\b|\bwegmans\b.*\bvodka\s+blush\b"), "alfredo_sauce"),
        (_r(r"\bwegmans\b.*\bgeneral\s+tso\b|\bwegmans\b.*\bsesame\s+garlic\b|\bwegmans\b.*\bsweet\s*&?\s*sour\b"), "marinade"),
        (_r(r"\bwegmans\b.*\borganic\b.*\btaco\s+sauce\b|\bwegmans\b.*\btropical.*\bsalsa\b"), "salsa"),
        (_r(r"\bwegmans\b.*\bcorn\s+salsa\b|\bwegmans\b.*\bchutney\b"), "salsa"),
        (_r(r"\bwegmans\b.*\bsubmarine\b|\bwegmans\b.*\bsubmarine\b.*\boil\b"), "salad_dressing"),
        # Sweet Baby Ray's / Stubb's BBQ
        (_r(r"\bsweet\s+baby\s+ray.?s\b|\bstubbs?\b"), "bbq_sauce"),
        # EZ Bombs seasoning / Omsom starters
        (_r(r"\bez\s+bombs?\b|\bomsom\b|\blarb\s+starter\b|\bspicy\s+bulgogi\b|\byuzu\s+misoyaki\b"), "marinade"),
        # Yangnyeom / Zhong dumpling sauce / Summer roll sauce
        (_r(r"\byangnyeom\b|\bzhong\b.*\bdumpling\b|\bdumpling\s+dipping\b|\bsummer\s+roll\s+sauce\b"), "other"),
        # CLEVELAND Kitchen / Blue Dragon / P.F. Chang's sauce
        (_r(r"\bcleveland\s+kitchen\b|\bblue\s+dragon\b.*\bsauce\b|\bpf\s+chang.?s\b.*\bsauce\b"), "marinade"),
        # Goya sofrito / tomato cooking base
        (_r(r"\bgoya\b.*\bsofrito\b|\bsofrito\b.*\btomato\b"), "pasta_sauce"),
        # Loisa sofrito
        (_r(r"\bloisa\b.*\bsofrito\b|\bsofrito\b"), "pasta_sauce"),
        # Fever-Tree / Zing Zang bloody mary mix
        (_r(r"\bfever.tree\b.*\bbloody\b|\bzing\s+zang\b"), "other"),
        # Angostura / Fee Brothers bitters
        (_r(r"\bangostura\b|\bfee\s+brothers?\b|\bbitters?\b|\baromatic\s+bitters\b"), "other"),
        # Nutty Lemongrass / peri peri / Soyaki / Yum Yum sauce
        (_r(r"\bnutty\s+lemongrass\b|\bperi\s+peri\b|\bsoyaki\b|\byum\s+yum\s+sauce\b|\bterry\s+ho.?s\b"), "other"),
        # Reese's / dessert toppings
        (_r(r"\breese.?s\b.*\btopping\b|\bcaramel\s+topping\b|\bchocolate\s+sauce\b|\bcapricio\b"), "other"),
        # Bosco / Ghirardelli chocolate sauce (condiment context)
        (_r(r"\bbosco\b.*\bchocolate\b|\bghirardelli\b.*\bsauce\b|\bghirardelli\b.*\bpremium\s+sauce\b"), "other"),
        # Red Pepper Romesco sauce
        (_r(r"\bromesco\b"), "other"),
        # Concord Foods guacamole mix
        (_r(r"\bconcord\s+foods?\b.*\bguacamole\b"), "other"),
        # Salsa macha / Mexican specialty salsas
        (_r(r"\bsalsa\s+macha\b|\bsalsa\s+taquera\b|\bsalsa\s+verde\b|\bsalsa\s+diablo\b"), "salsa"),
        # Valentina / Cholula (named brand)
        (_r(r"\bvalentina\b|\bcholula\b"), "hot_sauce"),
        # Nutpods creamer (misrouted to condiments)
        (_r(r"\bnutpods\b"), "other"),
        # Skinny Mixes / Jordan's syrup / TORANI / Walden Farms (sweet syrups)
        (_r(r"\bskinny\s+mixes?\b|\bjordan.?s\s+skinny\b|\btorani\b|\bwalden\s+farms?\b.*\bsyrup\b|\bflavoring\s+syrup\b"), "syrup_topping"),
        # Woodford Reserve cocktail syrup / cocktail syrups
        (_r(r"\bwoodford\s+reserve\b|\bcocktail\s+syrup\b|\bold\s+fashioned\s+syrup\b"), "syrup_topping"),
        # Smucker's syrups / ice cream toppings / sundae syrups
        (_r(r"\bsmucker.?s\b.*\bsyrup\b|\bsmucker.?s\b.*\btopping\b|\bsmucker.?s\b.*\bfudge\b|\bsmucker.?s\b.*\bmarshmal\b"), "syrup_topping"),
        (_r(r"\bsmucker.?s\b|\bkaro\b.*\bcorn\s+syrup\b|\blight\s+corn\s+syrup\b|\bhershey.?s\b.*\btopping\b|\bbosco\b.*\bchocolate\b"), "syrup_topping"),
        # Mrs. Richardson's / dessert sauces (ice cream toppings)
        (_r(r"\bmrs\.?\s+richardson.?s?\b|\bdessert\s+sauce\b|\bghirardelli\b.*\bsauce\b|\bghirardelli\b.*\bpremium\b"), "syrup_topping"),
        # Relish / sweet relish / dill relish / Rick's Picks
        (_r(r"\bsweet\s+relish\b|\bdill\s+relish\b|\bwith\s+relish\b|\brick.?s\s+picks?\b.*\brelish\b|\brelish\b"), "relish"),
        (_r(r"\bheinz\b.*\brelish\b|\bwegmans\b.*\brelish\b|\bmarket\s+pantry\b.*\brelish\b"), "relish"),
        # Angostura / Fee Brothers bitters
        (_r(r"\bangostura\b|\bfee\s+brothers?\b|\bbitters?\b|\baromatic\s+bitters\b|\bfee\s+foam\b"), "dipping_sauce"),
        # Fever-Tree / Zing Zang bloody mary mix
        (_r(r"\bfever.tree\b|\bzing\s+zang\b|\bbloody\s+mary\s+mix\b"), "dipping_sauce"),
        # Cooking pastes (McCormick seasoning mixes, Gourmet Garden, Laxmi)
        (_r(r"\bmccormick\b.*\bseasoning\s+mix\b|\bmccormick\b.*\bslow\s+cooker\b|\bmccormick\b.*\bstew\b|\bmccormick\b.*\bchili\b"), "cooking_paste"),
        (_r(r"\bmccormick\b.*\bguacamole\b|\bmccormick\b.*\bmeat\s+loaf\b|\bmccormick\b.*\bchicken\b.*\bbag\b"), "cooking_paste"),
        (_r(r"\bsimply\s+organic\b.*\bseasoning\s+mix\b|\bsimply\s+organic\b.*\bchili\b"), "cooking_paste"),
        (_r(r"\bgourmet\s+garden\b|\bstir.in\s+paste\b|\blaxmi\b.*\bpaste\b|\bgarlic\s+paste\b"), "cooking_paste"),
        # McCormick generic catch
        (_r(r"\bmccormick\b"), "cooking_paste"),
        # Knorr sauce mix (hollandaise, bearnaise)
        (_r(r"\bknorr\b.*\bsauce\s+mix\b|\bknorr\b"), "cooking_paste"),
        # Wegmans hollandaise / bearnaise / specialty sauces
        (_r(r"\bwegmans\b.*\bhollandaise\b|\bwegmans\b.*\bbearnaise\b"), "gravy"),
        (_r(r"\bwegmans\b.*\bmorel\s+sauce\b|\bwegmans\b.*\bmushroom\s+sauce\b|\bwegmans\b.*\bpeppercorn\b|\bwegmans\b.*\bsauce\s+flavored\b"), "gravy"),
        (_r(r"\bwegmans\b.*\btartar\b|\bwegmans\b.*\bremoulade\b|\bwegmans\b.*\bcreamy\s+horseradish\b"), "dipping_sauce"),
        (_r(r"\bwegmans\b.*\bdipping\s+sauce\b|\bwegmans\b.*\bsummer\s+roll\b|\bwegmans\b.*\bpoke\s+sauce\b|\bwegmans\b.*\bdumpling\b"), "dipping_sauce"),
        (_r(r"\bwegmans\b.*\bamore\b|\bwegmans\b.*\blemon\s+butter\b|\bwegmans\b.*\bvodka\s+blush\b|\bwegmans\b.*\bsubmarine\b"), "alfredo_sauce"),
        (_r(r"\bwegmans\b.*\bdanny.?s\b|\bwegmans\b.*\bcheddar\s+cheese\b|\bwegmans\b.*\bgrandpa.?s\b|\bwegmans\b.*\bborn\s+in\s+buffalo\b"), "dipping_sauce"),
        (_r(r"\bwegmans\b.*\bgarlic\b|\bwegmans\b.*\bitalian\s+classics\b|\bwegmans\b.*\bbruschetta\b|\bwegmans\b.*\bolive\b"), "dipping_sauce"),
        (_r(r"\bwegmans\b.*\bchutney\b|\bwegmans\b.*\bcranberry\b|\bwegmans\b.*\btropical\b"), "salsa"),
        (_r(r"\bwegmans\b.*\bchili\s+sauce\b|\bwegmans\b.*\btaco\s+sauce\b"), "hot_sauce"),
        # Tartar sauce (general) / kelchner's
        (_r(r"\btartar\s+sauce\b|\bkelchner\b.*\btartar\b|\blouisiana\b.*\btartar\b|\bmarket\s+pantry\b.*\btartar\b"), "dipping_sauce"),
        # Gourmet Garden stir-in paste — covered above
        # Fody taco sauce / Organic taco sauce
        (_r(r"\bfody\b.*\btaco\b|\borganic\s+spicy\s+taco\s+sauce\b|\btaco\s+sauce\b"), "salsa"),
        # Arriba! taco / enchilada seasoning sauce
        (_r(r"\barriba\b"), "marinade"),
        # Bachan's Japanese BBQ sauce
        (_r(r"\bbackhan.?s\b|\bbachan.?s\b"), "bbq_sauce"),
        # Try Me Tiger Sauce / thick red sauce
        (_r(r"\btry\s+me\s+tiger\b|\bthick\b.*\bspicy\b.*\bred\s+sauce\b"), "other"),
    ],

    "baked_goods.bread": [
        (_r(r"\bsourdough\b"), "sourdough"),
        (_r(r"\bchallah\b"), "challah"),
        (_r(r"\bfocaccia\b|\bfougasse\b"), "focaccia"),
        (_r(r"\brye\s+bread\b|\bdark\s+rye\b|\bpumpernickel\b|\bporridge\s+bread\b|\bsimit\b"), "rye_bread"),
        (_r(r"\bflatbread\b|\blavash\b|\bnaan\b|\bpita\b|\bpita\s+bread\b|\bbaguette\b|\bciabatta\b|\bfocaccia\s+loaf\b"), "flatbread"),
        (_r(r"\bgluten.free\s+bread\b|\bgf\s+bread\b"), "gluten_free_bread"),
        (_r(r"\bwhole\s+grain\b|\bwhole\s+wheat\b|\bmultigrain\b|\bwhole\s+wheat\s+bread\b|\bsprouted\b|\bseeds?\s+bread\b|\bgrains\s+&\s+seeds\b|\bseeded\s+bread\b|\bharvest\s+grain\b|\bseeds\s+of\s+life\b|\bseedy\b.*\bbread\b|\bseed\s+loaf\b|\bezekiel\b|\bflourless\b|\bnine\s+(?:grain|mixed)\b|\bpeasant\s+bread\b|\bmestemacher\b|\bbread\s+alone\b|\borganic\s+bread\b|\bvolkorn\b|\bwhole\s+rye\b"), "whole_grain_bread"),
        # Garlic bread — frozen or fresh
        (_r(r"\bgarlic\s+bread\b|\bgarlic\s+toast\b|\bgarlic\s+loaf\b|\bcheese\s+garlic\s+toast\b"), "other"),
        # Specialty / artisan loaves that don't fit above
        (_r(r"\bcornbread\b|\bcorn\s+bread\b|\bjalapen\b.*\bcorn\b|\bcorn\s+muffin\b"), "other"),
        (_r(r"\bgarlic\s+bread\b|\bgarlic\s+toast\b|\bgarlic\s+loaf\b|\bgarlic\s+roll\b|\bgarlic\s+knot\b|\bcheese\s+garlic\b"), "other"),
        (_r(r"\bbrioche\b"), "sandwich_bread"),
        (_r(r"\bbatard\b|\bboule\b|\bloaf\b|\bcountry\s+loaf\b|\bartisan\b.*\bbread\b|\bswirl\s+bread\b|\bcinnamon\s+swirl\b"), "sandwich_bread"),
        (_r(r"\bsandwich\s+bread\b|\bwhite\s+bread\b|\bclassic\s+bread\b|\bsliced\s+bread\b|\btoast\s+bread\b|\bpullman\b|\bmilk\s+bread\b|\bbrioche\s+loaf\b|\bolive\s+pocket\b|\bpita\s+pocket\b|\bbrazilian\s+cheese\b|\bpao\s+de\s+queijo\b|\bdemi\s+baguette\b|\bfrench\s+demi\b|\btake\s+and\s+bake\b|\btake\s*&\s*bake\b"), "sandwich_bread"),
        # Dave's Killer Bread abbreviated SKU names — all whole grain
        (_r(r"\bdave.s\s+killer\b|\bdave.s\b.*\bbread\b"), "whole_grain_bread"),
        # Rye variants not caught above
        (_r(r"\brussian\s+rye\b|\bblack\s+caraway\b|\bbrown\s+bread\b|\bpumpernickel\b|\bpumpkinickel\b"), "rye_bread"),
        # Honey wheat / soft wheat / natural wheat — sandwich loaves
        (_r(r"\bhoney\s+wheat\b|\bsoft\s+wheat\b|\bnatural\s+wheat\b|\bwheat\s+bread\b|\bhealth\s+nut\b|\bartesano\b|\bsara\s+lee\b|\bbrownberry\b|\bmarathon\s+bread\b|\bsixseed\b|\b1st\s+grain\b|\bfirst\s+grain\b|\bsemolina\b|\bolive\s+oil\s+crostini\b|\bcrostini\b"), "sandwich_bread"),
        # Italian / olive oil / artisan loaves with no better match
        (_r(r"\bpane\b|\bitalian\s+bread\b|\bolive\s+oil\s+bread\b|\btuscan\b.*\bbread\b|\bsemita\b|\bsweet\s+bread\b|\bolive\s+pocket\b"), "sandwich_bread"),
        # Catch-all: anything with "bread" in the name
        (_r(r"\bbread\b"), "sandwich_bread"),
    ],

    "baked_goods.dough": [
        # Pizza dough / crust
        (_r(r"\bpizza\s+(?:dough|crust)\b|\bfrozen\s+pizza\s+crust\b|\bgluten.free\s+pizza\s+(?:dough|crust)\b"), "pizza_dough"),
        # Pie crusts / shells
        (_r(r"\bpie\s+crust\b|\bpie\s+shell\b|\bgrahams?\s+crust\b|\bready\s+crust\b|\bchocolate\s+crust\b|\bshortbread\s+crust\b"), "pie_crust"),
        # Cookie dough / brownie dough
        (_r(r"\bcookie\s+dough\b|\bbrownie\s+dough\b|\bchocolate\s+chip\s+dough\b|\bsugar\s+cookie\s+dough\b"), "biscuit_dough"),
        # Empanada wrappers / spring roll wrappers / wontons / rice paper
        (_r(r"\bempanada\b|\bwonton\s+wrapp\b|\begg\s+roll\s+wrapp\b|\bspring\s+roll\s+wrapp\b|\brice\s+paper\b|\bfillo\b|\bphyllo\b|\bpastry\s+sheet\b"), "other"),
        # Biscuit / baking dough / flapjack mix
        (_r(r"\bbiscuit\s+dough\b|\bflap\s*jack\b|\bkodiak\b"), "biscuit_dough"),
    ],

    "baked_goods.gluten_free": [
        # GF bread / rolls / buns
        (_r(r"\bgluten.free\b.*\b(?:bread|baguette|roll|buns?)\b|\b(?:bread|baguette|roll|buns?)\b.*\bgluten.free\b"), "gluten_free_bread"),
        # GF pasta / spaghetti
        (_r(r"\bgluten.free\b.*\bpasta\b|\bgluten.free\b.*\bspaghetti\b|\brice\s+spaghetti\b|\bgluten.free\b.*\bnoodles?\b"), "gluten_free_pasta"),
        # GF wraps / tortillas
        (_r(r"\bgluten.free\b.*\b(?:wrap|tortilla|flatbread)\b"), "gluten_free_wrap"),
        # GF baked goods (muffins, waffles, cookies, cornbread mix, crackers)
        (_r(r"\bgluten.free\b.*\b(?:muffin|waffle|cookie|crackers?|cornbread|matzo|bagel|scone|brownie|cake|pastry|pancake)\b"), "gluten_free_baked"),
        # Generic GF catch-all
        (_r(r"\bgluten.free\b|\bgluten\s+free\b|\bgf\b"), "gluten_free_baked"),
    ],

    "baked_goods.tortillas": [
        (_r(r"\begg\s+wraps?\b|\begg\s+tortillas?\b|\begg.based\s+wrap\b"), "egg_wrap"),
        (_r(r"\blow.carb\s+wraps?\b|\blow\s+carb\s+tortillas?\b|\bcarb\s+balance\b|\bprotein\s+wraps?\b|\bcarb\s+savvy\b"), "low_carb_wrap"),
        # Corn: taco shells, corn tortillas, stone-ground corn, tostadas
        (_r(r"\bcorn\s+tortillas?\b|\bmaize\s+tortillas?\b|\btaco\s+shells?\b|\bstone\s+ground.*corn\b|\bstoneground.*corn\b|\byellow\s+corn\s+taco\b|\bwhite\s+corn\b|\bblue\s+corn\s+tortilla\b|\btostadas?\b|\bgrain\s+free\s+taco\b"), "corn_tortilla"),
        # Flour: all flour-based wraps, gordita, burrito, fajita, street taco sizes
        (_r(r"\bflour\s+tortillas?\b|\bgordita\b|\bburrito\s+tortillas?\b|\bfajita\s+tortillas?\b|\bstreet\s+tacos?\b|\bsonora\b|\bsoft\s+tacos?\b|\bwraps?\b|\btortillas?\b"), "flour_tortilla"),
    ],

    "baked_goods.bagels_breakfast": [
        # Waffles & pancakes — includes french toast sticks, flapjack puffs
        (_r(r"\bwaffles?\b|\bpancakes?\b|\bgriddle\s+cakes?\b|\bdutch\s+griddle\b|\bpoffertjes?\b|\bsilver\s+dollar\b|\bfrench\s+toast\b|\bflapjack\s+puffs?\b|\bkodiak\b.*\bpuffs?\b"), "waffle_pancake"),
        (_r(r"\benglish\s+muffins?\b"), "english_muffin"),
        # Protein pastries / toaster pastries / pop-tarts
        (_r(r"\bprotein\s+pastries?\b|\btoaster\s+pastries?\b|\bpop.tarts?\b|\blegendary\s+foods\b.*\bpastry\b|\bmagic\s+spoon\b.*\bpastry\b"), "breakfast_biscuit"),
        # belVita and branded breakfast biscuits / scones / biscuits
        (_r(r"\bbelvita\b|\bbreakfast\s+biscuits?\b|\bbiscuits?\b"), "breakfast_biscuit"),
        (_r(r"\bbreakfast\s+bars?\b|\bcereal\s+bars?\b"), "breakfast_bar"),
        # Blinis / crepes
        (_r(r"\bblinis?\b|\bcrepes?\b"), "waffle_pancake"),
        # Corn cakes (Thomas' etc.)
        (_r(r"\bcorn\s+cakes?\b"), "english_muffin"),
        # Flapjack mixes (Kodiak dry mix)
        (_r(r"\bflapjacks?\b|\bkodiak\b.*\bflapjack\b|\bkodiak\b.*\bpower\b"), "waffle_pancake"),
        # Pizza bagels — plural-safe
        (_r(r"\bpizza\s+bagels?\b|\bcheese\s+pizza\s+bagels?\b|\bpepperoni.*bagels?\b"), "bagel"),
        (_r(r"\bbagels?\b"), "bagel"),
    ],

    "baked_goods.croissants_pastries": [
        (_r(r"\bcroissants?\b"), "croissant"),
        (_r(r"\bdonuts?\b|\bdoughnuts?\b|\bdoughnut\s+holes?\b|\bdonut\s+holes?\b"), "donut"),
        (_r(r"\btoaster\s+pastries?\b|\bpop.tarts?\b|\btoaster\s+strudel\b"), "toaster_pastry"),
        (_r(r"\bdanish\b"), "danish"),
        (_r(r"\bcinnamon\s+rolls?\b|\bcinnamon\s+buns?\b|\bmorning\s+buns?\b|\bhot\s+cross\s+buns?\b|\bsticky\s+buns?\b|\bpecan\s+rolls?\b"), "cinnamon_roll"),
        (_r(r"\brugelach\b"), "rugelach"),
        (_r(r"\bpuff\s+pastry\b|\bpastry\s+puff\b|\bpastry\s+bites?\b|\bpastries\b|\btortas?\b|\bpanettone\b"), "puff_pastry"),
        # Muffins (not english muffins)
        (_r(r"\bmuffins?\b(?!.*english)"), "muffin"),
        # Scones
        (_r(r"\bscones?\b"), "scone"),
        # Biscuits (savory drop biscuits, cheddar biscuits — not breakfast biscuit bars)
        (_r(r"\bbiscuit\s+bites?\b|\bcheddar\s+biscuit\b|\bcheesy\s+biscuit\b|\bsavory\s+biscuits?\b|\bcrescents?\b|\bbiscuits?\b"), "biscuit"),
        # Coffee cake / crumb cake / olive oil cake / upside-down cake in pastry context
        (_r(r"\bcoffee\s+cake\b|\bcrumb\s+cake\b|\bolive\s+oil\s+cake\b|\bupside.down\s+cake\b|\bcrostata\b|\bturnover\b|\bpain\s+au\b|\bbrioche\s+style\b|\bsweet\s+bread\b|\bhonduran\b"), "coffee_cake"),
        # Waffles — liège, artisan waffles landing in pastry section
        (_r(r"\blièg\b|\bliege\b|\bwaffles?\b"), "waffle_pastry"),
        # Fig bars / flatbreads / breakfast items that land here
        (_r(r"\bfig\s+bars?\b|\bflatbread\b(?!.*pizza)|\bbreakfast\s+cake\b"), "other"),
        # Ice cream cones / waffle cones (non-food adjacent)
        (_r(r"\bsugar\s+cones?\b|\bwaffle\s+cones?\b|\bice\s+cream\s+cups?\b|\bice\s+cream\s+cones?\b|\bfritter\b|\bbabka\b"), "other"),
    ],

    # breakfast_desserts is the renamed successor to croissants_pastries (taxonomy v2.4)
    # Same product types, same vocabulary — rules are an exact copy.
    "baked_goods.breakfast_desserts": [
        (_r(r"\bcroissants?\b"), "croissant"),
        (_r(r"\bdonuts?\b|\bdoughnuts?\b|\bdoughnut\s+holes?\b|\bdonut\s+holes?\b"), "donut"),
        (_r(r"\btoaster\s+pastries?\b|\bpop.tarts?\b|\btoaster\s+strudel\b"), "toaster_pastry"),
        (_r(r"\bdanish\b"), "danish"),
        (_r(r"\bcinnamon\s+rolls?\b|\bcinnamon\s+buns?\b|\bmorning\s+buns?\b|\bhot\s+cross\s+buns?\b|\bsticky\s+buns?\b|\bpecan\s+rolls?\b"), "cinnamon_roll"),
        (_r(r"\brugelach\b"), "rugelach"),
        (_r(r"\bpuff\s+pastry\b|\bpastry\s+puff\b|\bpastry\s+bites?\b|\bpastries\b|\btortas?\b|\bpanettone\b"), "puff_pastry"),
        # Muffins (not english muffins)
        (_r(r"\bmuffins?\b(?!.*english)"), "muffin"),
        # Scones
        (_r(r"\bscones?\b"), "scone"),
        # Biscuits (savory drop biscuits, cheddar biscuits — not breakfast biscuit bars)
        (_r(r"\bbiscuit\s+bites?\b|\bcheddar\s+biscuit\b|\bcheesy\s+biscuit\b|\bsavory\s+biscuits?\b|\bcrescents?\b|\bbiscuits?\b"), "biscuit"),
        # Coffee cake / crumb cake / olive oil cake / upside-down cake in pastry context
        (_r(r"\bcoffee\s+cake\b|\bcrumb\s+cake\b|\bolive\s+oil\s+cake\b|\bupside.down\s+cake\b|\bcrostata\b|\bturnover\b|\bpain\s+au\b|\bbrioche\s+style\b|\bsweet\s+bread\b|\bhonduran\b"), "coffee_cake"),
        # Waffles — liège, artisan waffles landing in pastry section
        (_r(r"\blièg\b|\bliege\b|\bwaffles?\b"), "waffle_pastry"),
        # Fig bars / flatbreads / breakfast items that land here
        (_r(r"\bfig\s+bars?\b|\bflatbread\b(?!.*pizza)|\bbreakfast\s+cake\b"), "other"),
        # Ice cream cones / waffle cones (non-food adjacent)
        (_r(r"\bsugar\s+cones?\b|\bwaffle\s+cones?\b|\bice\s+cream\s+cups?\b|\bice\s+cream\s+cones?\b|\bfritter\b|\bbabka\b"), "other"),
    ],

    "baked_goods.buns_rolls": [
        # Pretzel products — soft pretzel sticks, twists, buns
        (_r(r"\bpretzel\s+buns?\b|\bpretzel\s+rolls?\b|\bpretzel\s+twists?\b|\bpretzel\s+sticks?\b|\bsoft\s+pretzel\b"), "pretzel_bun"),
        (_r(r"\bpretzel\b"), "other"),
        # Hot dog buns
        (_r(r"\bhot\s+dog\s+buns?\b|\bfrankfurter\s+rolls?\b|\bhot\s+dog\s+rolls?\b|\bbrioche\s+hot\s+dog\b"), "hot_dog_bun"),
        # Slider / mini bun
        (_r(r"\bslider\s+buns?\b|\bmini\s+buns?\b|\bslider\s+rolls?\b"), "slider_bun"),
        # Hamburger / brioche / potato buns
        (_r(r"\bhamburger\s+buns?\b|\bburger\s+buns?\b|\bbrioche\s+buns?\b|\bpotato\s+buns?\b|\bpotato\s+rolls?\b"), "hamburger_bun"),
        # Dinner / crescent / sweet / aloha / hawaiian / ciabatta / sandwich rolls
        (_r(r"\bdinner\s+rolls?\b|\bcrescent\s+rolls?\b|\bsweet\s+rolls?\b|\baloha\s+rolls?\b|\bhawaiian\s+rolls?\b|\bpull.apart\b|\bciabatta\s+rolls?\b|\bsandwich\s+rolls?\b|\bhoagie\s+rolls?\b|\bsub\s+rolls?\b|\bciabatta\b|\bfocaccia\s+rolls?\b|\bbreakfast\s+rolls?\b"), "dinner_roll"),
        # Garlic bread
        (_r(r"\bgarlic\s+bread\b|\bgarlic\s+rolls?\b|\bgarlic\s+knots?\b|\bgarlic\s+buns?\b"), "other"),
        # Generic roll/bun fallback — plural-safe (s? after word char)
        (_r(r"\brolls?\b|\bbuns?\b"), "dinner_roll"),
        # Biscuits
        (_r(r"\bbiscuits?\b"), "other"),
        # Sandwich starters
        (_r(r"\bsandwich\s+starter\b"), "hamburger_bun"),
    ],

    "meat.beef": [
        (_r(r"\bground\s+beef\b|\bbeef\s+mince\b"), "ground_beef"),
        (_r(r"\bbeef\s+rib\b|\brib\s+roast\b|\bprime\s+rib\b|\bback\s+rib\b|\bshort\s+rib\b"), "beef_ribs"),
        (_r(r"\bburger\s+patty\b|\bbeef\s+patty\b|\bhamburger\s+patty\b"), "burger_patty"),
        (_r(r"\bstew\s+beef\b|\bbeef\s+stew\b|\bbeef\s+chunk\b|\bchuck\s+roast\b"), "stew_beef"),
        (_r(r"\broast\b|\bpot\s+roast\b|\bbeef\s+roast\b|\bround\b|\bbrisket\b"), "roast"),
        (_r(r"\bsteak\b|\bsirloin\b|\bribeye\b|\bstrip\b|\btenderloin\b|\bflank\b|\bskirt\b|\bt.bone\b|\bporterhouse\b"), "steak"),
    ],

    "meat.poultry": [
        (_r(r"\bwhole\s+chicken\b|\brotisserie\b|\bchicken\s+whole\b|\bspatchcock\b|\bhalf\s+chicken\b|\bbutterfly\b.*\bchicken\b"), "whole_chicken"),
        # Wings — Buffalo style wings land here
        (_r(r"\bchicken\s+wings?\b|\bwings?\b(?!.*plant|.*meatless|.*plant.based)"), "chicken_wings"),
        (_r(r"\bground\s+chicken\b|\bchicken\s+mince\b|\ball\s+natural\s+ground\s+chicken\b"), "ground_chicken"),
        # Chicken breast — includes breaded tenders, fillets, cutlets, patties
        (_r(r"\bchicken\s+breast\b|\bbreast\b.*\bchicken\b|\bchicken\s+tenders?\b|\bchicken\s+tender\b|\bchicken\s+strips?\b|\bchicken\s+cutlets?\b|\bchicken\s+fillets?\b|\bchicken\s+patties?\b(?!.*plant|.*meatless)|\bbreaded.*\bchicken\b|\bchicken.*\bbreaded\b"), "chicken_breast"),
        # Chicken thighs / legs / drumsticks
        (_r(r"\bchicken\s+thighs?\b|\bthighs?\b.*\bchicken\b|\bdrum\b|\bchicken\s+legs?\b|\bchicken\s+drumsticks?\b"), "chicken_thigh"),
        # Turkey — all cuts, including patties, roast, deli
        (_r(r"\bturkey\b(?!.*jerky|.*deli|.*pastrami)"), "turkey"),
        (_r(r"\bduck\b"), "duck"),
    ],

    "meat.pork": [
        (_r(r"\bground\s+pork\b|\bpork\s+mince\b"), "ground_pork"),
        (_r(r"\bpork\s+rib\b|\bbaby\s+back\b|\bspare\s+rib\b"), "pork_ribs"),
        (_r(r"\bpork\s+tenderloin\b"), "pork_tenderloin"),
        (_r(r"\bpulled\s+pork\b"), "pulled_pork"),
        (_r(r"\bpork\s+roast\b|\bpork\s+shoulder\b|\bpork\s+butt\b|\bpork\s+loin\b"), "pork_roast"),
        (_r(r"\bpork\s+chop\b|\bchop\b.*\bpork\b"), "pork_chop"),
    ],

    "meat.bacon_sausages": [
        (_r(r"\bbacon\b"), "bacon"),
        (_r(r"\bpepperoni\b|\bsalami\s+stick\b|\bmini.*salami\b|\buncured\s+salami\b"), "pepperoni"),
        # Hot dogs — uncured, beef franks, kosher franks, grass-fed, NY-style
        (_r(r"\bhot\s+dog\b|\bfrankfurter\b|\bwiener\b|\bbeef\s+frank\b|\bbeef\s+franks\b|\buncured.*\bfrankfurter\b|\bcockail\s+frank\b|\bcocktail\s+frank\b|\bsabrett\b|\bnathan\b.*\bfrank\b|\bhebrew\s+national\b|\buncured.*hot\s+dog\b|\bny\s+style.*hot\s+dog\b|\bny.style.*hot\s+dog\b|\bgrassfed.*hot\s+dog\b|\bgrassfed.*frank\b"), "hot_dog"),
        # Diced / cured pancetta (not sliced)
        (_r(r"\bdiced.*pancetta\b|\bpancetta\b"), "breakfast_sausage"),
        (_r(r"\bsummer\s+sausage\b|\blandj[ae]ger\b|\bgenoa\s+salami\b|\bhard\s+salami\b|\bdry.cured\s+sausage\b|\bdelallo\b|\bdry\s+sausage\b|\buncured\s+dry\b"), "summer_sausage"),
        # Breakfast sausage — chicken, turkey, pork, maple, sage flavored
        (_r(r"\bbreakfast\s+sausage\b|\bpork\s+sausage\b|\bsausage\s+link\b|\bsausage\s+patty\b|\bchicken\s+sausage\b|\bturkey\s+sausage\b|\bmerguez\b|\blamb\s+sausage\b|\bchicken\s+garlic\s+sausage\b|\bchicken.*\bsausage\b|\bmaple\s+sausage\b|\bsage\s+sausage\b|\bsalt\s+(?:&|and)\s+pepper\s+sausage\b|\blancaster\b.*\bsausage\b|\bbreakfast\s+links?\b"), "breakfast_sausage"),
        (_r(r"\bitalian\s+sausage\b|\bsweet\s+italian\b|\bspicy\s+italian\b"), "italian_sausage"),
        (_r(r"\bsmoked\s+sausage\b|\bkielbasa\b|\banduille\b|\bandouille\b|\bchorizo\b|\bbrat\b|\bbratwurst\b|\bnapolitana\b|\bnapoli\s+sausage\b"), "smoked_sausage"),
        # Pickled sausages / shelf-stable sausages
        (_r(r"\bpickled\s+sausage\b|\bpickled.*sausage\b|\bhannah.?s\b|\bbig\s+pickled\b"), "other"),
        # Bologna / loaf meats
        (_r(r"\bbologna\b|\blocado\b|\bmeat\s+loaf\b|\bbeef\s+loaf\b"), "hot_dog"),
        # Spam
        (_r(r"\bspam\b"), "hot_dog"),
        # Meatballs (chicken, turkey, pork)
        (_r(r"\bmeatballs?\b|\bchicken\s+meatballs?\b|\bturkey\s+meatballs?\b|\bpork\s+meatballs?\b"), "breakfast_sausage"),
        # Amylu chicken meatballs / caramelized onion sausage
        (_r(r"\bamylu\b|\bcamelized\s+onion\b.*\bchicken\b|\bwhite\s+cheddar\s+chicken\b"), "breakfast_sausage"),
        # Duck sausage / duck fennel
        (_r(r"\bduck\b.*\bsausage\b|\bduck\s+fennel\b|\bduck\s+armagnac\b|\bd.artagnan\b.*\bsausage\b"), "smoked_sausage"),
        # Sausage catch-all for named sausages not matched above
        (_r(r"\bserrano\s+cheddar\b|\bdolce\s+beet\b|\bla\s+dolce\b"), "smoked_sausage"),
    ],

    "meat.deli_charcuterie": [
        # Turkey — oven roasted, smoked, pastrami turkey, etc.
        (_r(r"\bsliced\s+turkey\b|\bturkey\s+breast\b|\boven\s+roasted\s+turkey\b|\bsmoked\s+turkey\b|\bturkey\s+pastrami\b|\bturkey\s+bologna\b|\bturkey\s+salami\b|\bturkey\b.*\bdeli\b"), "sliced_turkey"),
        # Chicken deli
        (_r(r"\bsliced\s+chicken\b|\bchicken\s+breast\b.*\bdeli\b|\boven\s+roasted\s+chicken\b|\bchicken\s+bologna\b"), "sliced_chicken"),
        # Ham and pork deli
        (_r(r"\bham\b|\bprosciutto.*ham\b|\bhoney\s+ham\b|\bblack\s+forest\s+ham\b|\bvirginia\s+ham\b|\bserrano\b|\bculatello\b"), "sliced_ham"),
        # Salami / cured meats / charcuterie boards
        (_r(r"\bsalami\b|\bprosciutto\b|\bcapicola\b|\bcapicollo\b|\bmortadella\b|\bsoppressata\b|\bpancetta\b|\bpepperoni\b.*\bdeli\b|\buncured\s+pepperoni\b|\bcharcuterie\b|\bcharcuteria\b|\bgenoa\b|\bpastrami\b|\bcorned\s+beef\b|\bgyro\b|\bspam\b"), "salami_prosciutto"),
        # Roast beef / beef deli
        (_r(r"\broast\s+beef\b|\bbeef\b.*\bdeli\b|\bbeef\s+frank\b|\bfrankfurter\b(?!.*sausage)"), "roast_beef"),
        # Deli duo / combo packs — treat as salami_prosciutto
        (_r(r"\bdeli\s+duo\b|\bdeli\s+combo\b|\bcharcuteri\b|\bcollection\b.*\bdeli\b"), "salami_prosciutto"),
        # Jamón ibérico / Spanish lomo / Mercado Famous brand
        (_r(r"\bjam[oó]n\b|\biberico\b|\bib[eé]rico\b|\blomo\b|\bserrano\b.*\bham\b|\bmercado\s+famous\b"), "sliced_ham"),
        # Pâté / mousse / foie gras / rillettes / terrine
        (_r(r"\bpat[eé]\b|\bterrine\b|\bfoie\s+gras\b|\brillettes\b|\bmousse\b.*\bpat[eé]\b|\bpat[eé]\b.*\bmousse\b|\blouis\s+trois\b|\bles\s+trois\b|\bgoose\s+liver\b|\bduck\s+liver\b|\btruffle\s+mousse\b|\bsauternes\b|\bsalam[eé]\b|\bsalami\b.*\bcotto\b|\bguanciale\b|\bnduja\b"), "pate_mousse"),
        # Bresaola / finocchiona / chorizo sliced
        (_r(r"\bbresaola\b|\bfinocchiona\b|\bchorizo\b.*\bsliced\b|\bsliced\s+chorizo\b"), "salami_prosciutto"),
        # Sliced chicken / organic chicken sliced
        (_r(r"\borganic\s+sliced\b.*\bchicken\b|\bnuna\b"), "sliced_chicken"),
        # Bologna (uncured)
        (_r(r"\bbologna\b|\buncured\s+bologna\b"), "bologna"),
        # Single-serve deli snack packs (True Story)
        (_r(r"\btrue\s+story\b|\bsingle\s+serve\s+deli\b"), "sliced_turkey"),
    ],

    "seafood.fish": [
        (_r(r"\bsalmon\b(?!.*smoked|.*canned|.*tinned)"), "salmon"),
        (_r(r"\btuna\b(?!.*canned|.*tinned)"), "tuna"),
        (_r(r"\btilapia\b"), "tilapia"),
        (_r(r"\bcod\b|\bhaddock\b|\bpollock\b"), "cod"),
        (_r(r"\bhalibut\b"), "halibut"),
        (_r(r"\bmahi.mahi\b|\bdolphinfish\b"), "mahi_mahi"),
        (_r(r"\btrout\b"), "trout"),
        (_r(r"\bcatfish\b"), "catfish"),
    ],

    "seafood.shellfish": [
        (_r(r"\bshrimp\b|\bprawns\b"), "shrimp"),
        (_r(r"\bcrab\b|\bkingcrab\b"), "crab"),
        (_r(r"\blobster\b"), "lobster"),
        (_r(r"\bmussels\b"), "mussels"),
        (_r(r"\bclams\b|\bclam\b"), "clams"),
        (_r(r"\bscallops\b|\bscallop\b"), "scallops"),
    ],

    "seafood.tinned": [
        # Tuna — match bare "tuna" since the subfamily already confirms it's tinned
        (_r(r"\balbacore\b|\byellowfin\b|\bskipjack\b|\bsolid\s+white\b|\bchunk\s+white\b|\bchunk\s+light\b|\bsolid\s+light\b|\bcanned\s+tuna\b|\btuna.*\bcan\b|\btuna.*pouch\b|\btuna\b"), "canned_tuna"),
        # Salmon
        (_r(r"\bcanned\s+salmon\b|\bsalmon.*\bcan\b|\bsalmon.*pouch\b|\bsalmon\b"), "canned_salmon"),
        # Sardines
        (_r(r"\bsardines?\b"), "canned_sardine"),
        # Mackerel
        (_r(r"\bmackerel\b"), "canned_mackerel"),
        # Anchovies
        (_r(r"\banchov"), "canned_anchovy"),
        # Shellfish (shellfish, surimi, imitation crab/lobster, calamari, oysters, mussels, lobster, crab)
        (_r(r"\bcanned\s+shrimp\b|\bcanned\s+crab\b|\bcanned\s+clam\b|\bcanned\s+oysters?\b|\boysters?\b|\bsurimi\b|\bimitation\s+(?:crab|lobster)\b|\bcalamari\b|\bsquid\b|\bclams?\b|\bshrimp\b|\bmussels?\b|\blocrab\b|\blump\s+crab\b|\bcrabmeat\b|\bcrab\s+meat\b|\blobster\b"), "canned_shellfish"),
        # Herring / kipper
        (_r(r"\bherring\b|\bkippers?\b"), "other"),
        # Cod liver / roe items
        (_r(r"\bcod\s+liver\b|\bcod\b"), "other"),
        # Caviar / roe / premium chicken (mis-classified into tinned)
        (_r(r"\bcaviar\b|\broe\b|\bchicken\b"), "other"),
    ],

    "seafood.smoked": [
        (_r(r"\bsmoked\s+salmon\b|\blox\b|\bgravlax\b"), "smoked_salmon"),
        (_r(r"\bsmoked\s+trout\b"), "smoked_trout"),
        (_r(r"\bsmoked\s+mackerel\b"), "smoked_mackerel"),
    ],

    "plant_protein.meat_substitute": [
        # Burgers / patties — plural-safe
        (_r(r"\bplant.based\s+burgers?\b|\bbeyond\s+burgers?\b|\bimpossible\s+burgers?\b|\bplant\s+burgers?\b|\bveggie\s+burgers?\b|\bquinoa\s+.*burgers?\b|\bblack\s+bean\s+burgers?\b|\bportobello\s+burgers?\b|\bimpossible\s+foods\b|\bgrillers\s+prime\b|\bspicy\s+black\s+bean\b"), "plant_burger"),
        # Ground / crumbles (MorningStar Grillers Vegan Crumbles)
        (_r(r"\bplant.based\s+ground\b|\bbeyond\s+beef\b|\bimpossible\s+beef\b|\bground.*\bplant\b|\btvp\b|\btextured\s+vegetable\s+protein\b|\bplant.based\s+crumble\b|\blite\s+ground\b.*\bplant\b|\bgrillers\b.*\bcrumble\b|\bvegan\s+crumble\b|\bcrumbles?\b.*\bmeatless\b"), "plant_ground"),
        # Sausages — expanded to catch "Beyond Breakfast Sausage" (word between brand & type)
        (_r(r"\bplant.based\s+sausages?\b|\bbeyond\b.*\bsausages?\b|\bimpossible\b.*\bsausages?\b|\bplant\s+sausages?\b|\bveggie\s+sausages?\b|\bmeatless\s+sausages?\b|\bmeatless\s+breakfast\s+sausage\b|\bsausage\s+patties?\b.*\bmeatless\b|\bsoy\s+chorizo\b|\bfield\s+roast.*sausage\b|\bmorningstar\b.*\bsausage\b|\bbreakfast\s+sausage\s+patties?\b"), "plant_sausage"),
        # Plant-based bacon strips
        (_r(r"\bplant.based\s+bacons?\b|\bvegan\s+bacons?\b|\bmeatless\s+bacons?\b|\bplant\s+bacons?\b|\bbacon\s+strips?\b.*\bplant\b|\bbakon\b"), "plant_strips"),
        # Strips / wings / tenders / filets / chick'n (Gardein Chick'n, Blackbird Wings)
        (_r(r"\bplant.based\s+strips?\b|\bchik.n\b|\bchick.n\b|\bgardein.*strips?\b|\bplant\s+strips?\b|\bbuffalo\s+wings?\b.*\bplant\b|\bfield\s+roast.*wings?\b|\bplant.based\s+wings?\b|\bchicken.less\b|\bchickn\b|\bplant\s+chicken\b|\bdaring\s+plant\b|\bchicken\s+pieces?\b.*\bplant\b|\bdon.t\s+be\s+chicken\b|\bmeatless.*chicken\b|\bblackbird.*wings?\b|\bgardein.*filet\b|\bgardein.*tenders?\b|\bgardein.*crispy\b|\bplant.based.*tenders?\b|\bquorn\b"), "plant_strips"),
        # Nuggets / corn dogs — plural-safe
        (_r(r"\bnuggets?\b|\bchik.n\s+nuggets?\b|\bplant.based\s+nuggets?\b|\bcorn\s+dogs?\b|\bvegan\s+corn\s+dogs?\b|\bmeatless.*nuggets?\b|\bchickenless\s+nuggets?\b"), "plant_nuggets"),
        # Plant-based egg (Just Egg, JUST Egg Folded)
        (_r(r"\bjust\s+egg\b|\bplant.based\s+egg\b|\begg\s+alternative\b|\begg\s+substitute\b|\bvegan\s+egg\b"), "other"),
        # Plant-based fish / seafood-style
        (_r(r"\bgardein.*fish\b|\bplant.based.*fish\b|\bplant.based.*seafood\b|\bvegan.*fish\b|\bno\s+fish\b|\bgolden\s+fish\b|\bcrispy\s+fish\b.*\bplant\b"), "other"),
        # Steak bites / roast / deli slices / pepperoni (Beyond Steak, Field Roast Pepperoni)
        (_r(r"\bsteak\s+bites?\b|\bseared\s+tips?\b|\bplant.based\s+steak\b|\bbeyond\s+steak\b|\bimpossible\s+steak\b|\bpepperoni\s+slices?\b|\bfield\s+roast.*pepperoni\b|\bplant.based.*pepperoni\b|\bmeatballs?\b"), "other"),
        # Jamaican / ethnic plant patties
        (_r(r"\bplant.based\s+patties?\b|\bpatties?\b.*\bplant\b|\bturnover.*plant\b"), "plant_burger"),
        # Falafel (plant-protein balls)
        (_r(r"\bfalafel\b"), "plant_nuggets"),
        # Jackfruit (shredded / pulled — as meat sub)
        (_r(r"\bjackfruit\b"), "other"),
        # No Evil Foods brand (vegan Italian sausage, chorizo crumble, etc.)
        (_r(r"\bno\s+evil\s+foods\b|\bno\s+evil\b"), "plant_sausage"),
        # Abbot's brand (plant-rich ground, chick'n)
        (_r(r"\babbot.?s\b"), "other"),
        # Generic meatless / plant-based catch-all (Beyond brand without specific match above)
        (_r(r"\bmeatless\b|\bplant.based\b|\bplant\s+based\b|\bvegan\s+(?!egg|corn)|\bbeyond\s+meat\b|\bbeyond\b.*\bplant\b"), "other"),
        # Big Mountain mushroom burger
        (_r(r"\bbig\s+mountain\b|\bmushroom\s+burger\b"), "plant_burger"),
        # Dr. Praeger's all american drive-thru burger
        (_r(r"\bdr\.?\s+praeger.?s\b.*\bburger\b|\ball\s+american\s+drive.thru\b"), "plant_burger"),
        # Field Roast deli slices / sausage / hot dogs
        (_r(r"\bfield\s+roast\b.*\bdeli\b|\bfield\s+roast\b.*\bsausage\b|\bfield\s+roast\b.*\bhot\s+dogs?\b|\blentil.*sage.*slices?\b|\bmushroom.*balsamic.*slices?\b"), "plant_strips"),
        # Foodies Pumfu sausage crumble
        (_r(r"\bpumfu\b.*\bsausage\b"), "plant_sausage"),
        # Gardein ground be'f
        (_r(r"\bgardein\b.*\bground\b"), "plant_ground"),
        # Hari & Co veggie balls
        (_r(r"\bhari\s*&?\s*co\.?\b|\bveggie\s+balls?\b"), "plant_nuggets"),
        # Lightlife deli slices / smart bacon
        (_r(r"\blightlife\b.*\bdeli\b|\blightlife\b.*\bslices?\b|\blightlife\b.*\bbacon\b"), "plant_strips"),
        # MyFOREST Foods mycelium bacon
        (_r(r"\bmyforest\b|\bmycelium\s+bacon\b"), "plant_strips"),
        # Nasoya Plantspired steak
        (_r(r"\bnasoya\b.*\bplantspired\b|\bnasoya\b.*\bsteak\b"), "other"),
        # SoyBoy Not Dogs
        (_r(r"\bsoyboy\b|\bnot\s+dogs?\b"), "plant_sausage"),
        # Tofurky plant-based deli slices / sausage
        (_r(r"\btofurky\b.*\bdeli\b|\btofurky\b.*\bpeppered\b|\btofurky\b.*\bham\b"), "plant_strips"),
        # Unreal Deli slices
        (_r(r"\bunreal\s+deli\b|\bunreal\b.*\bbacon\b|\bunreal\b.*\bturk.y\b"), "plant_strips"),
        # Upton's Naturals jackfruit
        (_r(r"\bupton.?s\s+naturals?\b"), "other"),
        # Wunder Eggs plant-based
        (_r(r"\bwunder\s+eggs?\b"), "other"),
    ],

    "pantry.pasta_noodles": [
        # GF pasta — also catches rice pasta, corn pasta, organic GF pasta
        (_r(r"\bgluten.free\s+pasta\b|\bgf\s+pasta\b|\brice\s+pasta\b|\bcorn\s+pasta\b|\bgluten.free.*\bpasta\b|\bpasta.*\bgluten.free\b|\bgluten\s+free\b.*\bpasta\b"), "gluten_free_pasta"),
        # Legume pasta — chickpea, lentil, black bean, edamame, red lentil, yellow lentil
        (_r(r"\blegume\s+pasta\b|\blentil\s+pasta\b|\bchickpea\s+(?:pasta|fusilli|penne)\b|\bblack\s+bean\s+pasta\b|\bedamame\s+pasta\b|\bred\s+lentil\s+pasta\b|\bred\s+lentil.*\bpasta\b|\bchickpea.*\bpasta\b|\byellow\s+lentil\b.*\bpasta\b|\byellow\s+lentil\b.*\bcasarecce\b|\blentil\b.*\bcasarecce\b|\blentil\b.*\bpasta\b"), "legume_pasta"),
        # Whole wheat pasta
        (_r(r"\bwhole\s+wheat\s+pasta\b|\bwhole.grain\s+pasta\b|\bwhole\s+wheat\s+spaghetti\b|\bbrown\s+rice.*pasta\b|\bbrown\s+rice.*\bquinoa\b.*pasta\b"), "whole_wheat_pasta"),
        # Pasta sauces that ended up in pasta subfamily — leave as other
        (_r(r"\bpasta\s+sauce\b|\bmarinara\b|\barrabbiata\b|\bbolognese\b|\balfredo\b|\bpesto\b.*\bsauce\b|\bpomodoro\b|\bcarbonara\s+sauce\b|\bcarbone\b.*\bsauce\b|\bsauce\b.*\bpasta\b"), "other"),
        # Kelp / shirataki / glass / specialty noodles
        (_r(r"\bkelp\s+noodles?\b|\bshipataki\b|\bshirataki\b|\bkonjac\s+noodles?\b|\bglass\s+noodles?\b|\bmung\s+bean\s+noodles?\b|\bkasha\b|\bbuckwheat\s+groats?\b|\bsomen\b"), "asian_noodles"),
        # Asian noodles — includes Thai wheat noodles, knife cut noodles, spicy noodles
        (_r(r"\budon\b|\bsoba\b|\bramen\b|\brice\s+noodles?\b|\bpad\s+thai\s+noodle\b|\blo\s+mein\b|\bchow\s+mein\b|\bvermicelli\b|\bbean\s+thread\b|\bthai\s+wheat\s+noodles?\b|\bknife\s+cut\s+noodles?\b|\bspicy\s+squiggly\b|\bsquiggly\s+noodles?\b|\bkorean\s+noodles?\b|\bchina\s+mein\b|\bhot\s+sauce\s+noodles?\b|\binstant\s+noodles?\b"), "asian_noodles"),
        # Egg noodles
        (_r(r"\begg\s+noodles?\b|\bnoodle.*egg\b|\bgluten.free\s+egg\s+fettuccine\b"), "egg_noodles"),
        # Fresh/filled pasta — tortellini, ravioli, gnocchi
        (_r(r"\btortellini\b|\bravioli\b|\btortelloni\b|\bagnolotti\b|\bfresh\s+pasta\b|\bfresh.*\bgnocchi\b|\bpotato\s+gnocchi\b|\bcauliflower\s+gnocchi\b"), "white_pasta"),
        # Generic pasta — pappardelle, barilotti, fusilli corti bucati, pearled couscous, lasagne
        (_r(r"\bpasta\b|\bspaghetti\b|\bpenne\b|\bfusilli\b|\bfarfalle\b|\brigatoni\b|\bfettuccine\b|\borganic\s+pasta\b|\blinguine\b|\borzo\b|\bmacaroni\b|\bgnocchi\b|\bpappardelle\b|\bbarilotti\b|\bconchiglie\b|\brotini\b|\bziti\b|\bsedanini\b|\bgemelli\b|\bcavatappi\b|\bcellentani\b|\bditalini\b|\bcouscous\b|\bpearled\s+couscous\b|\blasagne\b|\blasagna\b|\bangle\s+hair\b|\bangel\s+hair\b|\btag?liatelle\b|\bpappardelle\b"), "white_pasta"),
    ],

    "pantry.grains_beans": [
        (_r(r"\bquinoa\b"), "quinoa"),
        (_r(r"\bcouscous\b"), "couscous"),
        (_r(r"\bpolenta\b|\bgrits\b"), "polenta"),
        (_r(r"\blentils?\b"), "lentils"),
        (_r(r"\bdried\s+beans?\b|\bblack\s+beans?\b|\bkidney\s+beans?\b|\bpinto\s+beans?\b|\bcannellini\b|\bchickpeas?\b|\bgarbanzo\b|\bwhite\s+beans?\b|\bnavy\s+beans?\b|\blima\s+beans?\b|\bfava\b|\bedamame\b|\bblack.eyed\s+peas?\b|\bsplit\s+peas?\b"), "dried_beans"),
        (_r(r"\boats\b|\boat\s+groat\b|\bsteel.cut\b"), "oats"),
        (_r(r"\bfarro\b|\bmillet\b|\bbulgur\b|\bbarley\b|\bamaranth\b|\bteff\b|\bwheat\s+berr\b|\bspelt\b|\bkamut\b|\bsorghum\b|\bbuckwheat\b|\bfreekeh\b|\bwheatberr\b"), "oats"),
        (_r(r"\bwild\s+rice\b|\brice\s+blend\b|\brice\b|\bbasmati\b|\bjasmine\s+rice\b|\bbrown\s+rice\b"), "rice"),
    ],

    "pantry.honey_syrups": [
        (_r(r"\bhoney\b"), "honey"),
        (_r(r"\bmaple\s+syrup\b|\bmaple\b"), "maple_syrup"),
        (_r(r"\bagave\b|\bagave\s+nectar\b"), "agave"),
        (_r(r"\bchocolate\s+syrup\b|\bhershey.*syrup\b"), "chocolate_syrup"),
        (_r(r"\bsyrup\b|\bflavored\s+syrup\b|\bpancake\s+syrup\b|\bmonin\b|\btorani\b"), "flavored_syrup"),
    ],

    "pantry.oil_vinegar_spices": [
        (_r(r"\bolive\s+oil\b|\bextra\s+virgin\b|\bevoo\b"), "olive_oil"),
        # Oils — expanded to include truffle, spray, avocado spray
        (_r(r"\bvegetable\s+oil\b|\bcanola\s+oil\b|\bsunflower\s+oil\b|\bsafflower\s+oil\b|\bcoconut\s+oil\b|\bavocado\s+(?:oil|spray\s+oil)\b|\bsesame\s+oil\b|\btruffle\s+oil\b|\bpumpkin\s+seed\s+oil\b|\bwalnut\s+oil\b|\bhazelnut\s+oil\b|\bgrapeseed\s+oil\b|\bflaxseed\s+oil\b|\bspray\s+oil\b|\bcooking\s+oil\b"), "vegetable_oil"),
        # Vinegar — expanded to include balsamico, glazes
        (_r(r"\bvinegar\b|\bbalsamic\b|\bbalsamico\b|\bapple\s+cider\s+vinegar\b|\bred\s+wine\s+vinegar\b|\bglaze\b|\brice\s+vinegar\b|\bwhite\s+wine\s+vinegar\b|\bsherry\s+vinegar\b|\bchampaign\s+vinegar\b"), "vinegar"),
        (_r(r"\bsalt\b(?!.*seasoning|.*blend)"), "salt"),
        (_r(r"\bspice\s+blend\b|\bseasoning\s+blend\b|\btaco\s+seasoning\b|\bbbq\s+rub\b|\bcajun\b|\bherb\s+blend\b|\bitalian\s+season\b|\beverything\s+bagel\b|\bza[']?atar\b|\bdukkah\b|\bras\s+el\s+hanout\b|\bherbes\s+de\s+provence\b|\bfines\s+herbes\b|\bpickling\s+spice\b|\bpoultry\s+seasoning\b|\bsteak\s+seasoning\b|\bfish\s+seasoning\b|\bblackening\b|\bchicken\s+rub\b|\bbrisket\s+rub\b|\bmontreal\b|\bold\s+bay\b|\blemon\s+pepper\b|\bseasoning\b"), "spice_blend"),
        # Spices — expanded to include peppercorns (singular and plural), parsley, bay, flakes, bare herb names
        (_r(r"\bspice\b|\bpepper\b|\bpeppercorns?\b|\bblack\s+peppercorns?\b|\bpeppercorn\s+medley\b|\bgarlic\s+powder\b|\bonion\s+powder\b|\bcumin\b|\bpaprika\b|\bcinnamon\b|\bturmeric\b|\borgano\b|\boregano\b|\bbasil\b|\bthyme\b|\brosemary\b|\bchili\s+powder\b|\bcayenne\b|\bcoriander\b|\bcardamom\b|\bnutmeg\b|\bcloves?\b|\ballspice\b|\bginger\b|\bsumac\b|\bfenugreek\b|\bchaat\b|\bgaram\s+masala\b|\bcurry\s+powder\b|\bsaffron\b|\bvanilla\s+powder\b|\bsmoked\s+paprika\b|\bwhite\s+pepper\b|\bblack\s+pepper\b|\bparsley\s+flakes?\b|\bparsley\b|\bbay\s+leaves?\b|\bdill\s+weed\b|\bdill\b(?!.*pickle)|\bsesame\s+seeds?\b|\bfennel\s+seeds?\b|\bcaraway\s+seeds?\b|\bmustard\s+seeds?\b|\banise\s+seeds?\b|\bfermented\s+black\s+garlic\b|\bblack\s+garlic\b|\bminced\s+garlic\b|\bgarlic.*water\b|\bsage\b|\bcelery\s+seeds?\b|\bcelery\s+salt\b|\bmustard\s+powder\b|\bdry\s+mustard\b|\bpowder\s+mustard\b|\bchives?\b|\btarragon\b|\bmarjoram\b|\blavender\b|\bherbs?\b(?!.*blend|.*season)|\bspice\s+jar\b|\bground\s+(?:cinnamon|cumin|ginger|nutmeg|turmeric|cloves?|cardamom|coriander|allspice|mustard|pepper)\b"), "spice_single"),
        # Nutritional yeast / flakes
        (_r(r"\bnutritional\s+yeast\b|\bnooch\b|\byeast\s+flake\b"), "spice_single"),
        # Additional individual spices not in main pattern
        (_r(r"\bpoppy\s+seeds?\b|\blemon\s+peel\b|\borange\s+peel\b|\bvanilla\s+beans?\b|\bstar\s+anise\b|\bred\s+(?:pepper\s+)?flakes?\b|\bchili\s+flakes?\b|\bcrushed\s+red\s+pepper\b|\bpaprika\b|\bsmoked\s+paprika\b|\bbay\s+leaves?\b|\bcrystal\s+hot\b|\bcream\s+of\s+tartar\b"), "spice_single"),
        # Animal fats / cooking sprays not caught by oil patterns
        (_r(r"\btallow\b|\blard\b|\bbeef\s+fat\b|\bwagyu.*fat\b"), "vegetable_oil"),
        # Popcorn / non-spice items that land here
        (_r(r"\bpopcorn\b"), "other"),
        # Badia spice brand
        (_r(r"\bbadia\b.*\bpaprika\b|\bbadia\b.*\bspice\b"), "spice_single"),
        # Bourbon smoked Japanese togarashi
        (_r(r"\bbourbon\s+smoked\b|\btogarashi\b"), "spice_blend"),
        # Burlap & Barrel specialty spices
        (_r(r"\bburlap\s*&?\s*barrel\b.*\bchili\b|\bburlap\s*&?\s*barrel\b.*\blime\b|\bburlap\s*&?\s*barrel\b.*\bgrilling\s+rub\b|\bburlap\s*&?\s*barrel\b.*\btaco\b"), "spice_blend"),
        # Cento garlic paste
        (_r(r"\bcento\b.*\bgarlic\s+paste\b"), "spice_single"),
        # Crisco shortening
        (_r(r"\bcrisco\b|\ball.vegetable\s+shortening\b"), "vegetable_oil"),
        # Empire Kosher rendered chicken fat / schmaltz
        (_r(r"\bempire\s+kosher\b.*\bchicken\s+fat\b|\brendered\s+chicken\s+fat\b|\bschmaltz\b"), "vegetable_oil"),
        # GOYA sazon / achiote
        (_r(r"\bgoya\b.*\bsaz[oó]n\b|\bsaz[oó]n\b.*\bculantro\b|\bsaz[oó]n\b.*\bazafr[aá]n\b|\bachiote\b"), "spice_blend"),
        # Good Seasons Italian dressing & recipe mix
        (_r(r"\bgood\s+seasons?\b|\bitalian\s+salad\s+dressing\s*&\s*recipe\s+mix\b"), "spice_blend"),
        # Hemani rose water
        (_r(r"\bhemani\b|\brose\s+water\b"), "other"),
        # JFC furikake Japanese seasoning
        (_r(r"\bjfc\b.*\bfurikake\b|\bfurikake\b|\bnori.*fumi\b|\bkatsuo.*fumi\b"), "spice_blend"),
        # Kinder's buttery steakhouse rub
        (_r(r"\bkinder.?s\b.*\brub\b|\bbuttery\s+steakhouse\b"), "spice_blend"),
        # London Pub malt beverage (non-food misrouted)
        (_r(r"\blondon\s+pub\b.*\bmalt\b|\btraditional\s+british\b.*\bmalt\b"), "other"),
        # McCormick tenderizer / seasoning (not already caught)
        (_r(r"\bmccormick\b.*\btenderizer\b|\bseasoned\s+meat\s+tenderizer\b"), "spice_blend"),
        # Muso furikake / Japanese seasoning
        (_r(r"\bmuso\b.*\bfurikake\b|\bmuso\b.*\bnori\b|\bmuso\b.*\byuzu\b|\bgreen\s+nori\s+seaweed\b"), "spice_blend"),
        # Organic sunflower seed oil
        (_r(r"\borganic\s+sunflower\s+seed\s+oil\b"), "vegetable_oil"),
        # Simply Organic individual herbs
        (_r(r"\bsimply\s+organic\b.*\bbay\s+leaf\b|\bsimply\s+organic\b.*\bonion\b"), "spice_single"),
        # Spiceology Greek Freak blend
        (_r(r"\bspiceology\b|\bgreek\s+freak\b|\bmediterranean\s+blend\b"), "spice_blend"),
        # Traditional ghee
        (_r(r"\btraditional\s+ghee\b|\bghee\b"), "vegetable_oil"),
        # Wegmans fleur de sel / cooking wine / tahini / popcorn
        (_r(r"\bwegmans\b.*\bfleur\s+de\s+sel\b|\bwegmans\b.*\bcooking\s+wine\b|\bwegmans\b.*\bmarsala\b|\bwegmans\b.*\bsherry\s+cooking\b"), "other"),
        (_r(r"\bwegmans\b.*\btahini\b"), "other"),
        (_r(r"\bwegmans\b.*\bpopcorn\b"), "other"),
        # Yamaroku soy sauce
        (_r(r"\byamaroku\b|\bjapanese\s+soy\s+sauce\b"), "other"),
        # Zatarain's crab boil / crawfish boil
        (_r(r"\bzatarain.?s\b.*\bcrab\s+boil\b|\bzatarain.?s\b.*\bshrimp\b|\bcrawfish.*\bcrab\b.*\bboil\b"), "spice_blend"),
    ],

    "pantry.jams_nut_butters": [
        # Nut/seed butters — specific before generic
        (_r(r"\btahini\b|\bsesame\s+(?:paste|butter)\b"), "tahini"),
        (_r(r"\bsunflower\s+(?:seed\s+)?butter\b|\bsunbutter\b"), "sunflower_butter"),
        (_r(r"\bcashew\s+butter\b"), "cashew_butter"),
        (_r(r"\bhazelnut\s+(?:spread|butter|cream)\b|\bnutella\b"), "hazelnut_spread"),
        (_r(r"\balmond\s+butter\b"), "almond_butter"),
        (_r(r"\bpeanut\s+butter\b|\bpb\s+&\s+j\b|\bpb\b.*\bspread\b"), "peanut_butter"),
        (_r(r"\bmixed\s+nut\s+butter\b|\bnut\s+butter\s+blend\b"), "mixed_nut_butter"),
        (_r(r"\b(?:walnut|pecan|macadamia|pistachio|hemp|pumpkin)\s+butter\b|\bseed\s+butter\b|\bsunflower\s+seed\s+butter\b"), "seed_butter"),
        # Coconut butter / coconut manna
        (_r(r"\bcoconut\s+butter\b|\bcoconut\s+manna\b|\bcoconut\s+cream\s+concentrate\b"), "seed_butter"),
        # Jams/spreads
        (_r(r"\bjam\b|\bjelly\b|\bpreserve\b|\bmarmalade\b|\bspreadable\s+fruit\b|\bsarabeh\b|\bsarabeth\b|\bfig\b.*\bpreserve\b|\bfig\b.*\bspread\b|\bhoney\b|\bkaya\b|\bpandan\b|\bcurd\b.*\bspread\b"), "jam_jelly"),
        (_r(r"\bfruit\s+spread\b|\bfruit\s+butter\b|\bapple\s+butter\b"), "fruit_spread"),
        # Flavored nut butters (chai spice, cashew coconut ghee, almond ginger, coconut chocolate)
        (_r(r"\bchai\s+spice\b.*\bnut\s+butter\b|\bcashew\s+coconut\b.*\bnut\s+butter\b|\balmond\s+ginger\b.*\bnut\s+butter\b|\bcoconut\s+chocolate\s+spread\b|\bginger\s+nut\s+butter\b|\bspiced\s+nut\s+butter\b|\bnut\s+butter\b"), "mixed_nut_butter"),
        # Applesauce (sometimes lands here instead of canned_goods)
        (_r(r"\bapplesauce\b|\bapple\s+sauce\b"), "fruit_spread"),
        # Preserves / confiture / conserves by specialty brands
        (_r(r"\bpreserves?\b|\bconfiture\b|\bconserve\b|\bcompote\b|\bblood\s+orange\b.*\bjam\b|\bjosephine.?s\b|\bblake\s+hill\b|\bcasa\s+forcello\b|\bsolebury\b|\bfarm\s+to\s+people\b.*\bpreserve\b|\bpear\s+butter\b|\bpumpkin\s+maple\b.*\bbutter\b"), "jam_jelly"),
        # Fig butter / pumpkin butter / specialty fruit butters
        (_r(r"\bfig\s+butter\b|\bpumpkin\s+butter\b"), "fruit_spread"),
    ],

    "pantry.jerky": [
        # Beef jerky / beef sticks
        (_r(r"\bbeef\s+jerky\b|\bjerky.*beef\b|\bbeef\s+sticks?\b|\bbeef\s+snack\s+sticks?\b"), "beef_jerky"),
        # Turkey jerky / turkey sticks
        (_r(r"\bturkey\s+jerky\b|\bturkey\s+sticks?\b|\bturkey\s+snack\s+sticks?\b"), "turkey_jerky"),
        # Salmon / fish jerky
        (_r(r"\bsalmon\s+jerky\b|\bfish\s+jerky\b"), "salmon_jerky"),
        # Chicken sticks / chicken jerky
        (_r(r"\bchicken\s+jerky\b|\bchicken\s+sticks?\b"), "other_jerky"),
        # Pork / salami sticks / slim jim
        (_r(r"\bpork\s+sticks?\b|\bsalami\s+sticks?\b|\bslim\s+jim\b|\bsnack\s+sticks?\b|\bsummer\s+sausage\s+sticks?\b"), "other_jerky"),
        # Generic jerky / meat sticks catch-all
        (_r(r"\bjerky\b|\bsticks?\b|\bsnack\s+sticks?\b|\bmeat\s+snacks?\b"), "other_jerky"),
    ],

    "pantry.pickled_fermented": [
        (_r(r"\bpickle\b|\bpickled\s+cucumber\b|\bdill\b.*\bpickle\b|\bpickled\s+jalapen\b|\bpickled\s+peppers?\b|\bpickled\s+ginger\b|\bgari\b|\bpickled\s+beet\b|\bpickled\s+onion\b|\bpickled\s+veggie\b|\bpickled\s+carrot\b|\bcurtido\b|\bkosher\s+dill\b|\bhamburger\s+dill\b|\bdill\s+slice\b|\bdill\b"), "pickles"),
        (_r(r"\bolives?\b|\bkalamata\b|\bcastelvetrano\b|\bpicholine\b|\bnicoise\b|\balfonso\b|\bchalkidiki\b|\bstuffed\s+olive\b|\bblue\s+cheese.*olive\b"), "olives"),
        (_r(r"\bkimchi\b"), "kimchi"),
        (_r(r"\bsauerkraut\b|\bferm.*\bcabbage\b|\bsilver\s+floss\b"), "sauerkraut"),
        # Capers / banana peppers / pepperoncini / jalapeños / marinated items
        (_r(r"\bcaper\b|\bbanana\s+pepper\b|\bpepperoncini\b|\bjalap[eé]n\b|\bsun.dried\s+tomato\b|\bmarinated\b|\btipsy\s+onion\b|\bcocktail\s+onion\b|\bmaraschino\b|\bcornichon\b|\bcherry\s+pepper\b|\broasted\s+(?:red\s+)?pepper\b|\bartichoke\s+heart\b(?!.*canned)|\bpickled\b|\bgrape\s+leaves?\b|\bdolmas?\b|\bginger(?:ed)?\s+(?:carrot|beet)\b|\bgingered\b|\bscapes?\b|\bslaw\b.*\bferm\b|\bferm.*\bslaw\b|\bsliced\s+jalap\b|\bjalap.*\bring\b"), "other_pickled"),
        (_r(r"\bfermented\b|\bmiso\b|\bnatto\b|\btempeh\b(?!.*protein)|\bkombine\b|\bsesame\s+slaw\b|\bfermented\s+slaw\b|\bsundried\b|\bsun\s+dried\b|\bsun.dried\b"), "other_pickled"),
    ],

    "pantry.dried_fruits_nuts": [
        (_r(r"\btrail\s+mix\b|\bsnack\s+mix\b.*\bnut\b|\bhike\s+mix\b"), "trail_mix"),
        (_r(r"\bcandied\s+(?:nut|almond|pecan|walnut)\b|\bpraline\b|\bhoney\s+roasted\b|\bchocolate.covered\b.*\bnut\b|\bchoco.*\bnut\b|\braisinets\b"), "candied_nuts"),
        (_r(r"\bseed\b|\bpumpkin\s+seed\b|\bsunflower\s+seed\b|\bchia\b|\bflax\b|\bhemp\s+seed\b|\bsesame\s+seeds?\b|\bpoppy\s+seed\b|\bsesame\s+seed\b|\bshelled\s+hemp\b|\bgo\s+raw\b|\bdavid\s+sunflower\b"), "seeds"),
        # Peanuts specifically (often sold alone as "Virginia Peanuts", "Salted Peanuts")
        (_r(r"\bpeanuts?\b"), "mixed_nuts"),
        (_r(r"\bmixed\s+nut\b|\bnut\s+mix\b|\bnut\s+medley\b|\balmonds?\b|\bcashews?\b|\bwalnuts?\b|\bpistachios?\b|\bmacadamia\b|\bpecans?\b|\bhazelnuts?\b|\bbrazil\s+nut\b|\bpine\s+nuts?\b|\bchestnuts?\b|\bspanish\s+peanuts?\b|\bvirginia\s+peanuts?\b|\bsalted\s+nuts?\b|\broasted\s+nuts?\b|\bdry\s+roasted\b"), "mixed_nuts"),
        # Crystallized / candied ginger
        (_r(r"\bcrystallized\s+ginger\b|\bcandied\s+ginger\b|\bginger\s+chunks?\b"), "dried_fruit"),
        # Fruit leather / dried fruit snacks
        (_r(r"\bfruit\s+leather\b|\bfruit\s+wrap\b|\bfruit\s+strip\b|\bfruit\s+roll\b|\bfruit\s+snack\b|\bfruit\s+dots?\b"), "dried_fruit"),
        # Additional dried fruit varieties
        (_r(r"\bdried\s+(?:apple|mango|cranberr|apricot|cherry|fig|date|raisin|blueberr|strawberr|banana|pineapple|papaya|coconut|goji|goldenberr|currant)\b|\bapple\s+rings?\b|\bdried\s+rings?\b|\bocean\s+spray.*dried\b|\bdried.*cranberr\b"), "dried_fruit"),
        # Freeze-dried fruit / fruit crisps / baked fruit chips
        (_r(r"\bfreeze.dried\b|\bfreeze\s+dried\b|\bfruit\s+crisps?\b|\bfruit\s+chips?\b|\bbaked.*\bapple\s+chips?\b|\bcrunchy\s+(?:apple|mango|banana)\b"), "dried_fruit"),
        (_r(r"\bdried\s+fruit\b|\braisins?\b|\bdried\s+mango\b|\bdried\s+apricots?\b|\bdried\s+cranberr\b|\bdried\s+cherr\b|\bdried\s+blueberr\b|\bdried\s+strawberr\b|\bdates?\b|\bfigs?\b|\bprunes?\b|\bcalifornia\s+apricots?\b|\bslab\s+apricots?\b|\bmango\s+slices\b|\bjust\s+mango\b|\bjust\s+fruit\b|\bdried\s+pineapple\b|\bdried\s+papaya\b|\bgoji\b|\bgolden\s+berries\b|\bgolden\s+berry\b|\bsea\s+buckthorn\b|\bmulberr|\bcurrants?\b|\bfruit\s+jerky\b|\bsolely\b.*\bjerky\b|\bsolely\b.*\bfruit\b|\bcoconut\b.*\bunsweetened\b|\bunsweetened\s+coconut\b|\bflaked\s+coconut\b|\bcoconut\s+flakes\b"), "dried_fruit"),
        # Dried mushrooms / dried chili peppers / specialty pantry
        (_r(r"\bdried\s+mushrooms?\b|\bdried\s+porcini\b|\bdried\s+morel\b|\bdried\s+shiitake\b|\bmushroom\b.*\bdried\b|\bshiitake\b.*\bdried\b|\bdried\s+(?:ancho|guajillo|chipotle|pasilla|chil[ie])\b|\bchili\s+pepper\b.*\bdried\b"), "other"),
        # Honey / bee products (sometimes land in dried_fruits_nuts)
        (_r(r"\bhoney\b|\braw\s+honey\b|\bmanuka\b|\bbee\s+pollen\b|\bpollen\b|\bagave\b|\bmaple\s+syrup\b|\bbirch\s+syrup\b"), "other"),
        # Bee pollen / superfoods (pantry health items)
        (_r(r"\bbee\s+pollen\b|\bpollen\b|\bsuperfoods?\b.*\bpowder\b|\bspirulina\b|\bchlorella\b|\bwheatgrass\b"), "other"),
        # Fried shallots / crispy onions (pantry snack)
        (_r(r"\bfried\s+shallot\b|\bcrispy\s+shallot\b|\bfried\s+onion\b"), "other"),
        # Baobest baobab berry chews
        (_r(r"\bbaobest\b|\bbaobab\s+snacks?\b|\bberry\s+chews?\b.*\bbaobab\b"), "other"),
        # Boxford Bakehouse organic triple C mix
        (_r(r"\bboxford\s+bakehouse\b|\btriple\s+c\s+mix\b"), "trail_mix"),
        # Dried ancho / chipotle / kitchen garden chili
        (_r(r"\bdried\s+ancho\b|\bdried\s+chipotle\b|\bkitchen\s+garden\s+farm\b|\bdried\s+chipotle\s+chili\b"), "other"),
        # Everything But the Bagel nut duo
        (_r(r"\beverything\s+but\s+the\s+bagel\b.*\bnut\b|\bnut\s+duo\b"), "mixed_nuts"),
        # Favorite Day keto nutty chocolate cherry
        (_r(r"\bfavorite\s+day\b.*\bketo\b|\bnutty\s+chocolate\s+cherry\b"), "candied_nuts"),
        # Fisher ice cream toppers / nut topping
        (_r(r"\bfisher\b.*\bice\s+cream\s+toppers?\b|\bnut\s+topping\b"), "mixed_nuts"),
        # Fried shallots
        (_r(r"\bfried\s+shallots?\b"), "other"),
        # Good & Gather mixed nuts / raw mixed nuts / dried mangos / applesauce pouches
        (_r(r"\bgood\s*&?\s*gather\b.*\bmixed\s+nuts?\b|\bgood\s*&?\s*gather\b.*\braw\s+mixed\s+nuts?\b"), "mixed_nuts"),
        (_r(r"\bgood\s*&?\s*gather\b.*\bdried\s+(?:sweetened\s+)?mangos?\b"), "dried_fruit"),
        (_r(r"\bgood\s*&?\s*gather\b.*\bapplesauce\s+pouches?\b|\bgood\s*&?\s*gather\b.*\bfruit\s+pur[eé]e\b|\bgood\s*&?\s*gather\b.*\bfruit\s+pouch\b"), "other"),
        # GoGo squeez (misrouted to dried_fruits_nuts)
        (_r(r"\bgogo\s+squeez\b|\bgogosqueez\b|\bno\s+sugar\s+added\s+applesauce\b"), "other"),
        # Mauna Loa chocolate covered macadamias
        (_r(r"\bmauna\s+loa\b|\bchocolate\s+covered\b.*\bmacadamia\b"), "candied_nuts"),
        # Melissa's dried morel / shiitake mushrooms
        (_r(r"\bmelissa.?s\b.*\bdried\b|\bdried\s+morel\b|\bdried\s+shiitake\b"), "other"),
        # NA mushroom dried sliced
        (_r(r"\bna\s+mushroom\b|\bshiitake.*dried.*sliced\b"), "other"),
        # Nuts About Rosemary Mix / olive herb mix
        (_r(r"\bnuts\s+about\s+rosemary\b|\brosemary\s+mix\b.*\bnut\b|\bolive\s*&?\s*herbs\b.*\bnut\b"), "mixed_nuts"),
        # Nutty & Fruity / Soft & Juicy mango
        (_r(r"\bnutty\s*&?\s*fruity\b|\bsoft\s*&?\s*juicy\s+mango\b|\bsoft\s+and\s+juicy\s+mango\b"), "dried_fruit"),
        # Ocean Spray reduced sugar Craisins
        (_r(r"\bocean\s+spray\b.*\bcraisins?\b|\breduced\s+sugar\s+craisins?\b"), "dried_fruit"),
        # Planters mixed nuts / lightly salted
        (_r(r"\bplanters?\b|\blightly\s+salted\b.*\bmixed\s+nuts?\b"), "mixed_nuts"),
        # Stony Brook pepitas
        (_r(r"\bstony\s+brook\b|\bpepitas?\b"), "seeds"),
        # Sweet Cheeks Farm bee pollen
        (_r(r"\bsweet\s+cheeks\s+farm\b|\bnew\s+jersey\s+bee\s+pollen\b"), "other"),
        # Wegmans mountain mix / dried berries / apple bars
        (_r(r"\bwegmans\b.*\bmountain\s+mix\b"), "trail_mix"),
        (_r(r"\bwegmans\b.*\bdried\s+blueberries?\b|\bwegmans\b.*\bdried\s+cherries?\b|\bwegmans\b.*\bdried\s+cranberries?\b"), "dried_fruit"),
        (_r(r"\bwegmans\b.*\bapple\s+wholesum\b|\bwegmans\b.*\bfruit\s*&?\s*nut\s+bars?\b"), "trail_mix"),
        # Wegmans pure vanilla extract (misrouted to nuts)
        (_r(r"\bwegmans\b.*\bvanilla\s+extract\b"), "other"),
    ],

    "pantry.stocks": [
        (_r(r"\bbone\s+broth\b"), "bone_broth"),
        (_r(r"\bbouillon\b|\bbase\b.*\bstock\b|\bbroth\s+concentrate\b|\bsoup\s+base\b"), "bouillon"),
        (_r(r"\bdashi\b"), "dashi"),
        (_r(r"\bchicken\s+broth\b|\bchicken\s+stock\b"), "chicken_broth"),
        (_r(r"\bbeef\s+broth\b|\bbeef\s+stock\b"), "beef_broth"),
        (_r(r"\bvegetable\s+broth\b|\bvegetable\s+stock\b|\bveggie\s+broth\b"), "vegetable_broth"),
    ],

    "pantry.canned_goods": [
        # Canned soup (check first — "Amy's Lentil Soup" shouldn't become canned_beans)
        (_r(r"\bsoup\b|\bcampbell\b"), "canned_soup"),
        # Canned fish / seafood / meat
        (_r(r"\bcanned\s+(?:fish|tuna|salmon|sardine|mackerel|anchov|shrimp|crab|oyster|clam)\b|\bchunk\s+(?:light|white)\s+tuna\b|\bchunk\s+chicken\b|\bcanned\s+(?:chicken|turkey|ham)\b"), "canned_fish"),
        # Canned beans / legumes — match standalone (no "canned" needed); incl. cowboy/great northern/navy/black-eyed peas
        (_r(r"\bblack\s+beans?\b|\bkidney\s+beans?\b|\bpinto\s+beans?\b|\bcannellini\b|\bchickpeas?\b|\bgarbanzo\b|\bwhite\s+beans?\b|\brefried\s+beans?\b|\bbaked\s+beans?\b|\blima\s+beans?\b|\bwax\s+beans?\b|\bfava\s+beans?\b|\bbroad\s+beans?\b|\blenticchie\b|\bpink\s+beans?\b|\bthree\s+bean\b|\b3\s+bean\b|\bbean\s+blend\b|\blentil\b(?!.*soup)|\bjackfruit\b|\bgreat\s+northern\b|\bnavy\s+beans?\b|\bblack.eyed\s+peas?\b|\bcowboy\s+beans?\b|\bmexican\s+cowboy\b|\bpinto\b|\bsmall\s+red\s+beans?\b"), "canned_beans"),
        # Canned tomatoes — whole, diced, crushed, paste, puree, passata, san marzano, tomato sauce
        (_r(r"\btomatoes?\b|\bpassata\b|\bsan\s+marzano\b|\bpomi\b|\btomato\s+puree\b|\btomato\s+paste\b|\btomato\s+sauce\b|\bfire.roasted\b|\bpeeled\s+tomato\b"), "canned_tomatoes"),
        # Canned fruit / applesauce / pumpkin / ackee / tropical
        (_r(r"\bapplesauce\b|\bapple\s+sauce\b|\bapples\s+sauce\b|\bunsweetened\s+apples\b"), "canned_fruit"),
        (_r(r"\bcanned\s+fruit\b|\bpeach\b.*\b(?:slices?|halves?|juice|syrup)\b|\bpeach\s+slices?\b|\bold.fashioned\s+peach\b|\bpears?\b.*\b(?:juice|syrup|can)\b|\bpineapple\b|\bmandarin\b|\bfruit\s+cocktail\b|\bapricot\b.*\bcan\b|\bpumpkin\s+puree\b|\b100%\s+pure\s+pumpkin\b|\bpumpkin\b.*\bcan\b|\backee\b|\bcanned\s+lychee\b|\bcanned\s+mango\b|\bcanned\s+guava\b|\byellow\s+cling\b|\bfruit\s+sauce\b|\bfruitz?\b|\bgogo\s+squeez\b|\bapplesauce\s+pouch\b|\bfruit\s+pouch\b|\bfruit\s+squeeze\b|\bfruit\s+crushers?\b"), "canned_fruit"),
        # Canned coconut milk / cream
        (_r(r"\bcoconut\s+(?:milk|cream|cream\s+of\s+coconut)\b"), "canned_fruit"),
        # Canned vegetables — corn, peas, green beans, beets, carrots, asparagus, spinach, mushrooms, artichokes, hominy, etc.
        (_r(r"\bwhole\s+kernel\s+corn\b|\bsweet\s+corn\b|\bkern.*\bcorn\b|\bsweet\s+peas?\b|\bcut\s+green\s+beans?\b|\bfrench\s+(?:style\s+)?green\s+beans?\b|\bsliced\s+beets?\b|\bwhole\s+beets?\b|\bsliced\s+carrots?\b|\basparagus\s+spears?\b|\bchopped\s+spinach\b|\bwhole\s+potatoes?\b|\bsliced\s+potatoes?\b|\bsweet\s+potatoes?\b.*\bcan\b|\byams?\b.*\bcan\b|\bmixed\s+vegetables?\b|\blima\b|\bbaby\s+corn\b|\bwax\s+beans?\b|\bgreen\s+beans?\b|\bpeas\b|\bbeets?\b|\bcarrots?\b|\basparagus\b|\bspinach\b|\bcorn\b(?!.*soup)|\bpotatoes?\b.*\bcan\b|\bmushrooms?\b|\bartichokes?\b|\bsunchokes?\b|\bhominy\b|\bnopal\b|\bjicama\b|\bbamboo\s+shoots?\b|\bwater\s+chestnuts?\b|\bcauliflower\b|\bzucchini\b|\bsquash\b|\bvegetable\s+medley\b|\bpeppers?\b.*\bcan\b|\broasted\s+(?:\w+\s+)?peppers?\b|\bjalapen\b.*\bcan\b|\bjalapen\b|\bgreen\s+chil(?:es?|i)\b|\bdiced\s+chil(?:es?|i)\b|\bchil(?:es?|i)\b.*\bcan\b|\bhatch\s+chil\b|\bmexicorn\b|\bvacuum\s+pack\b.*\bcorn\b|\bcut.*\byams?\b|\bsweet\s+potatoes?\b.*\bsyrup\b|\bpimiento\b|\bhearts\s+of\s+palm\b|\bsliced\s+pears\b|\bpickled.*can\b"), "canned_vegetables"),
        # Pizza sauce (sometimes lands in canned_goods instead of condiments)
        (_r(r"\bpizza\s+sauce\b|\bsmooth\s+pizza\s+sauce\b|\bamore\s+pizza\b|\bcarbone\s+pizza\b"), "canned_tomatoes"),
        # Pasta (misrouted products — label as other)
        (_r(r"\bpasta\b|\belbows?\b|\bspaghetti\b|\bpenne\b|\brigatoni\b|\bfettuccine\b"), "other"),
    ],

    "pantry.baking_ingredients": [
        # Chocolate chips / baking chips / cocoa
        (_r(r"\bchocolate\s+chips?\b|\bchoco\s+chips?\b|\bcacao\s+chips?\b|\bdark\s+chocolate\s+chips?\b|\bcaramel\b.*\bbaking\s+chips?\b|\bpeanut\s+butter\s+chips?\b|\bmini\s+chips?\b.*\bchocolate\b|\bsemi.sweet\b.*\bchocolate\b|\bsemi.sweet\b.*\bchips?\b|\bbittersweet\s+chips?\b|\bwhite\s+chocolate\s+chips?\b"), "chocolate_chips"),
        (_r(r"\bcocoa\s+powder\b|\bcacao\s+powder\b|\bchocolate\s+powder\b|\bunsweetened\s+cocoa\b|\bunsweetened\s+chocolate\b|\bbaking\s+(?:bar|chocolate)\b|\b100%\s+cacao\b|\bcacao\s+nibs?\b|\bcacao\s+wafers?\b|\bcocoa\s+nibs?\b|\bghirardelli\b.*\bbaking\b|\bhot\s+cacao\b|\bsuper(?:food)?\s+latte\s+powder\b"), "cocoa_cacao"),
        # Baking mixes (cornbread, pancake, cake, etc.)
        (_r(r"\bbaking\s+mix\b|\bpancake\s+mix\b|\bwaffle\s+mix\b|\bcake\s+mix\b|\bbrownie\s+mix\b|\bmuffin\s+mix\b|\bbread\s+mix\b|\bscone\s+mix\b|\bcookie\s+mix\b|\bbiscuit\s+mix\b|\bpie\s+mix\b|\bprotein\s+baking\s+mix\b|\bcornbread\s+mix\b|\bcorn\s+muffin\s+mix\b|\bcorn\s+bread\s+mix\b|\bgingerbread\s+mix\b|\bquick\s+bread\s+mix\b|\bfritter\s+mix\b"), "baking_mix"),
        # Bread crumbs / panko
        (_r(r"\bbread\s+crumbs?\b|\bpanko\b|\bseasoned\s+crumbs?\b|\bplain\s+crumbs?\b|\bgluten.free\s+crumbs?\b"), "baking_mix"),
        # Shortening / ghee / lard / fats used in baking
        (_r(r"\bshortening\b|\blard\b|\bghee\b|\bclarified\s+butter\b"), "extracts_flavoring"),
        # Seeds / nuts used for baking (flaxseed, chia, hemp)
        (_r(r"\bflax\s+seeds?\b|\bflaxseed\b|\bflax\s+meal\b|\bground\s+flax\b|\bmilled\s+flax\b|\bchia\s+seeds?\b|\bhemp\s+seeds?\b|\bpoppy\s+seeds?\b|\bsesame\s+seeds?\b|\bsunflower\s+seeds?\b.*\bbak\b"), "extracts_flavoring"),
        # Coconut milk / coconut cream (baking context)
        (_r(r"\bcoconut\s+milk\b|\bcoconut\s+cream\b|\bcoconut\s+flakes?\b|\bshredded\s+coconut\b|\bdesiccated\s+coconut\b|\bsweet\s+coconut\b"), "extracts_flavoring"),
        # Coffee filters / ice / water-profile products / non-food that lands here
        (_r(r"\bcoffee\s+filters?\b|\bcone\s+filters?\b|\bbasket\s+filters?\b|\bwrap\s+filters?\b|\bpaper\s+filters?\b|\bice\s+bag\b|\bcraft\s+ice\b|\bpremium\s+ice\b|\bglacier\s+ice\b|\barctic\s+glacier\b|\bthird\s+wave\s+water\b|\bespresso\s+profile\b|\bcoffee\s+profile\b"), "other"),
        # Fried onions / toppings
        (_r(r"\bfried\s+onion\b|\bgourmet\s+fried\b|\bcrispy\s+onion\b"), "other"),
        # Almond paste / marzipan / extracts
        (_r(r"\balmond\s+paste\b|\bmarzipan\b"), "extracts_flavoring"),
        (_r(r"\bextract\b|\bvanilla\b|\bflavoring\b|\bfood\s+color\b|\bfood\s+colouring\b|\bnatural\s+flavor\b|\bspray\b.*\bcoating\b|\bcooking\s+spray\b|\bbaking\s+spray\b"), "extracts_flavoring"),
        (_r(r"\bbaking\s+powder\b|\bbaking\s+soda\b|\byeast\b|\bcream\s+of\s+tartar\b|\bgelatin\b|\bpectin\b|\bagar\b"), "leavening"),
        (_r(r"\bsugar\b|\bpowdered\s+sugar\b|\bconfectioner\b|\bbrown\s+sugar\b|\bcane\s+sugar\b|\bcoconut\s+sugar\b|\bdate\s+sugar\b|\bmonk\s+fruit\s+sweetener\b|\berythritol\b|\bstevia\b.*\bbaking\b|\bxylitol\b|\ballulose\b"), "sugar"),
        (_r(r"\bcornmeal\b|\bpolenta\b(?!\s+.*breakfast)|\bcorn\s+meal\b|\bmasarepa\b|\bpre.cooked.*corn\s+meal\b|\bmatzo\s+meal\b|\bmatzo\s+mix\b|\bmatzo\s+ball\b"), "cornmeal"),
        (_r(r"\bwheat\s+bran\b|\bbran\b|\bwheat\s+germ\b|\bpsyllium\b|\bflaxseed\s+meal\b|\bflax\s+meal\b"), "bran_wheat_germ"),
        (_r(r"\btapioca\b|\bsago\b|\bsabudana\b|\barrowroot\b|\bcornstarch\b|\bpotato\s+starch\b|\bxanthan\s+gum\b|\bguar\s+gum\b"), "flour"),
        (_r(r"\bflour\b|\ball.purpose\b|\bbread\s+flour\b|\bcake\s+flour\b|\bwhole\s+wheat\s+flour\b|\balmond\s+flour\b|\bcoconut\s+flour\b|\boat\s+flour\b|\bspelt\s+flour\b|\bgluten.free\s+flour\b|\brice\s+flour\b|\bchickpea\s+flour\b|\btapioca\s+flour\b|\bsemolina\b"), "flour"),
        # Pumpkin puree / solid pack (baking context — not canned_goods)
        (_r(r"\bpumpkin\b|\bsolid\s+pack\b|\bpie\s+filling\b|\bapple\s+pie\s+filling\b|\bfruit\s+filling\b|\bcherry\s+pie\b"), "extracts_flavoring"),
        # Zero-cal sweeteners / stevia packets
        (_r(r"\bsplenda\b|\bstevia\b|\bmonk\s+fruit\b|\bsweetener\s+packets?\b|\bsugar\s+substitute\b|\bsaccharin\b|\baspartame\b|\bsucralose\b|\bzero\s+calorie\s+sweetener\b|\bnatural\s+sweetener\b"), "sugar"),
        # Betty Crocker / Pillsbury frosting
        (_r(r"\bbetty\s+crocker\b.*\bfrosting\b|\bpillsbury\b.*\bfrosting\b|\brich.*frosting\b|\bfunfetti\b.*\bfrosting\b"), "extracts_flavoring"),
        # Bob's Red Mill specialty mixes / egg replacer / pie crust mix
        (_r(r"\bbob.?s\s+red\s+mill\b.*\bpie\s+crust\b|\bbob.?s\s+red\s+mill\b.*\begg\s+replacer\b|\begg\s+replacer\b"), "baking_mix"),
        # Shake N Bake / seafood fry / coating mixes
        (_r(r"\bshake\s*.?n.?\s*bake\b|\bfish\s+fry\b|\bseafood\s+fry\b|\bcoating\s+mix\b"), "baking_mix"),
        # Toll House morsels (already covered by chocolate_chips but add brand)
        (_r(r"\btoll\s+house\b.*\bmorsels?\b|\btoll\s+house\b.*\bpremium\b"), "chocolate_chips"),
        # Wagyu beef tallow / cooking fat
        (_r(r"\bwagyu\b.*\btallow\b|\bbeef\s+tallow\b|\bcooking\s+fat\b.*\btallow\b"), "other"),
        # Melitta coffee filters (non-food, catch here)
        (_r(r"\bmelitta\b"), "other"),
        # Wilton sprinkles / nonpareils / food coloring
        (_r(r"\bwilton\b|\bsprinkles?\b|\bnonpareils?\b|\bjimmies?\b"), "extracts_flavoring"),
        (_r(r"\bfood\s+coloring\b|\begg\s+dye\b|\bwatkins\b.*\bfood\s+color\b"), "extracts_flavoring"),
        # Stonewall Kitchen crepe mix / specialty mixes
        (_r(r"\bstonewall\s+kitchen\b.*\bmix\b|\bcr[eê]pe\s+mix\b"), "baking_mix"),
        # Kodiak power cup flapjack (baking mix context)
        (_r(r"\bkodiak\b.*\bpower\s+cup\b|\bkodiak\b.*\bflapjack\b"), "baking_mix"),
        # Krusteaz bar mix / lemon bar mix
        (_r(r"\bkrusteaz\b|\blemon\s+bar\b.*\bmix\b"), "baking_mix"),
        # Ghirardelli melting wafers
        (_r(r"\bghirardelli\b.*\bmelting\s+wafers?\b|\bmelting\s+wafers?\b"), "chocolate_chips"),
        # Corn starch (Good & Gather)
        (_r(r"\bcorn\s+starch\b|\bgood\s*&?\s*gather\b.*\bcorn\s+starch\b"), "flour"),
        # Good & Gather chocolate morsels
        (_r(r"\bgood\s*&?\s*gather\b.*\bmorsels?\b"), "chocolate_chips"),
        # Abstract / craft ice (non-food misrouted)
        (_r(r"\bcraft\s+ice\s+rock\b|\bice\s+rock\b"), "other"),
        # Sweetened flaked coconut (Wegmans)
        (_r(r"\bsweetened\s+flaked\s+coconut\b|\bsweetened.*\bcoconut\b.*\bflakes?\b"), "extracts_flavoring"),
        # Ovaltine hot chocolate mix
        (_r(r"\bovaltine\b|\brich\s+chocolate\s+mix\b"), "cocoa_cacao"),
        # Lake Champlain hot chocolate / organic peppermint hot chocolate
        (_r(r"\blake\s+champlain\b.*\bhot\s+chocolate\b|\borganic\s+peppermint\s+hot\s+chocolate\b"), "cocoa_cacao"),
        # Diamond / gluten free pie crust
        (_r(r"\bdiamond\b.*\bpie\s+crust\b|\bgluten\s+free.*\bpie\s+crust\b|\bchocolate\s+nut\b.*\bpie\s+crust\b"), "baking_mix"),
        # El Guapo corn husks (tamale making)
        (_r(r"\bel\s+guapo\b|\bcorn\s+husks?\b.*\bshell\b"), "other"),
        # Frozen lemon juice (baking use)
        (_r(r"\bfrozen\s+lemon\s+juice\b"), "extracts_flavoring"),
        # Conza sourdough breadcrumb topping
        (_r(r"\bconza\b|\bsourdough\s+breadcrumb\b|\bbreadcrumb\b.*\btopping\b"), "baking_mix"),
        # Burlap & Barrel cacao
        (_r(r"\bburlap\s*&?\s*barrel\b.*\bcacao\b"), "cocoa_cacao"),
        # Yulu popping boba (non-food baking-adjacent)
        (_r(r"\byulu\b|\bpopping\s+bursting\b|\bboba\s+fruit\s+bubbles?\b"), "other"),
        # South Chicago Packing (already wagyu tallow above)
        (_r(r"\bsouth\s+chicago\s+packing\b"), "other"),
    ],

    "composite.pizza": [
        (_r(r"\bpizza\s+kit\b|\bmake.your.own\s+pizza\b"), "pizza_kit"),
        (_r(r"\bmini\s+pizza\b|\bpersonal\s+pizza\b"), "mini_pizza"),
        (_r(r"\bpizza\s+pocket\b|\bpizza\s+roll\b|\bcalzone\b|\bstromboli\b"), "pizza_pocket"),
        (_r(r"\bfrozen\s+pizza\b|\bpizza\b"), "frozen_pizza"),
    ],

    "composite.dips_spreads": [
        (_r(r"\bhummus\b|\bhommus\b"), "hummus"),
        (_r(r"\bguacamole\b|\bguac\b|\bguacasalsa\b|\bavocado\s+(?:mash|dip|spread|crema)\b"), "guacamole"),
        (_r(r"\bqueso\b|\bcheese\s+dip\b|\bnacho\s+cheese\b"), "queso"),
        # Pesto (all styles — basil, kale, cashew, vegan)
        (_r(r"\bpesto\b"), "tapenade"),
        (_r(r"\btapenade\b|\bantipasto\b|\bpesto\s+spread\b|\bbruschetta\b|\bsun.dried\s+tomato\s+spread\b|\beggplant\b.*\bspread\b|\bgarlic\s+spread\b|\beggplant\b.*\bdip\b|\bbaba\s+ghanoush\b|\bbaba\s+ganoush\b|\btzatziki\b"), "tapenade"),
        (_r(r"\bbean\s+dip\b|\brefried\s+bean\b"), "bean_dip"),
        (_r(r"\bspinach\s+(?:and\s+)?artichoke\s+dip\b|\bspinach.*artichoke\s+dip\b|\bspinach\s+dip\b|\bkale\s+dip\b|\bspinach.*kale.*dip\b|\bgreek\s+yogurt\s+dip\b|\breduced\s+guilt.*dip\b"), "spinach_dip"),
        (_r(r"\bsalsa\b"), "salsa"),
        # Butter / compound butter / herb butter
        (_r(r"\bherb\s+butter\b|\bgarlic\s+butter\b|\bcompound\s+butter\b|\bvegan\s+butter\b|\bnon.dairy\s+butter\b|\bplant.based\s+butter\b|\bnduja\b|\bspreads?\b.*\bspicy\b|\bspicy\s+spread\b"), "butter_spread"),
        # Yogurt-based dips / tzatziki / labneh / ranch dip / creamy dips
        (_r(r"\btzatziki\b|\blabneh\b|\byogurt\s+dip\b|\bdaisy\s+dip\b|\branch\s+dip\b|\bcreamy\s+ranch\s+dip\b|\bsour\s+cream\s+dip\b|\bonion\s+dip\b|\bfarm\s+dip\b|\bveggie\s+dip\b|\bvegetable\s+dip\b|\bcreamy\s+dill\b|\bchipotle\s+dip\b|\bdipping\s+sauce\b"), "yogurt_dip"),
        # Chutneys / tamarind / coconut cilantro / mango chutney
        (_r(r"\bchutney\b|\btamarind\b|\bcoconut\s+cilantro\b|\bmango\s+sauce\b|\bdate\s+sauce\b"), "chutney"),
        # Sofrito / recaito — cooking bases
        (_r(r"\bsofrito\b|\brecaito\b|\bsazon\b"), "other"),
        # Avocado chunks / diced avocado (not guacamole/mash)
        (_r(r"\bdiced\s+avocado\b|\bchunky\s+avocado\b|\bwholly\s+avocado\b|\bperfectly\s+ripe\b.*\bavocado\b|\bavocado\b.*\bdiced\b"), "guacamole"),
        # Nut-based dips / cashew dips / almond dips (Bitchin' Sauce, Nuts for Cheese)
        (_r(r"\bcashew\s+dip\b|\bcashew\s+cheese\b|\bbitchin\b|\balmond\s+dip\b|\bnut.based\s+dip\b|\bsauce\b.*\balmond\b|\balmond\s+sauce\b"), "other"),
        # Cheese spreads / cream cheese dips
        (_r(r"\bcheese\s+spread\b|\bfeta\s+dip\b|\bcream\s+cheese\s+dip\b|\bcannoli\s+dip\b|\bricotta\s+dip\b|\bolive.*dip\b|\bstuffed.*olive\b"), "other"),
        # Blue cheese / Caesar / other dips
        (_r(r"\bblue\s+cheese\s+(?:dressing\s+)?(?:&\s+)?dip\b|\bcaesar.*dip\b|\bred\s+pepper.*dip\b|\bcranberry.*dip\b|\bwalnut.*dip\b|\bblack\s+bean\s+pepita\b|\bguasacaca\b|\bbuffalo\s+chicken\s+dip\b"), "other"),
        # Appetizers / stuffed snacks / kombucha misrouted here
        (_r(r"\bmozzarella\s+sticks?\b|\bcrispy\s+wontons?\b|\bfritter\b|\bfried\s+olive\b|\bwonton\b|\bkombucha\b"), "other"),
        # Bitchin' Sauce almond dips (various flavors)
        (_r(r"\bbitchin.?\s+sauce\b|\bbitchin\b"), "other"),
        # Treeline cashew cheese (dairy-free)
        (_r(r"\btreeline\b|\bcashew\s+cheese\b.*\bherb\b|\bfrench.style\b.*\bcashew\b"), "other"),
        # Nuts for Cheese artichoke dip
        (_r(r"\bnuts\s+for\s+cheese\b"), "other"),
        # Cocojune yogurt dip
        (_r(r"\bcocojune\b|\bdairy.free\b.*\byogurt.dip\b"), "yogurt_dip"),
        # Loisa sofrito / recaito
        (_r(r"\bloisa\b"), "other"),
        # Health-Ade kombucha misrouted here
        (_r(r"\bhealth.ade\b|\bkombucha\b"), "other"),
        # Farm to People pantry starter kit
        (_r(r"\bpantry\s+starter\b"), "other"),
        # Chimichurri / spicy chimichurri
        (_r(r"\bchimichurri\b|\bspicy\s+chimichurri\b"), "other"),
        # Red pepper romesco sauce
        (_r(r"\bromesco\b|\bred\s+pepper\s+romesco\b"), "tapenade"),
        # Guasacaca (Venezuelan avocado sauce)
        (_r(r"\bguasacaca\b"), "guacamole"),
        # Black bean pepita dip / buffalo chicken dip (FTP)
        (_r(r"\bblack\s+bean\s+pepita\s+dip\b|\bpepita\s+dip\b|\bbuffalo\s+chicken\s+dip\b"), "other"),
        # Chunky avocado (Wegmans — not guacamole)
        (_r(r"\bwegmans\b.*\bavocado\b.*\bchunky\b|\bchunky\b.*\bavocado\b"), "guacamole"),
        # Gotham Greens green goddess dip
        (_r(r"\bgotham\s+greens\b|\bgreen\s+goddess\s+dip\b"), "yogurt_dip"),
        # Zhoug sauce (Middle Eastern)
        (_r(r"\bzhoug\b"), "tapenade"),
        # Baba ghanoush (in case not caught above)
        (_r(r"\bbaba\s+ghanoush\b|\bbaba\s+ganouj\b"), "tapenade"),
        # Cranberry sauce (if misrouted to dips_spreads)
        (_r(r"\bcranberry\s+sauce\b|\bfarm\s+to\s+people\b.*\bcranberry\b"), "other"),
        # Wegmans baba ghanouj
        (_r(r"\bwegmans\b.*\bbaba\b|\bbaba\s+ghanouj\b"), "tapenade"),
        # Dolmas (stuffed grape leaves) — misrouted to dips
        (_r(r"\bdolmas?\b|\bstuffed\s+grape\s+leaves?\b"), "other"),
        # Farm to People sauces / spreads
        (_r(r"\bspicy\s+chimichurri\b|\bchimichurri\b|\bromesco\s+sauce\b"), "tapenade"),
        # Bitchin' Sauce almond dip varieties
        (_r(r"\bbitchin.?s?\s+sauce\b"), "other"),
        # Bolthouse Farms yogurt dressing / dip
        (_r(r"\bbolthouse\s+farms?\b.*\bdip\b|\bolthouse\s+farms?\b.*\bdressing\b"), "yogurt_dip"),
        # Good & Gather buffalo dip / taco dip
        (_r(r"\bgood\s*&?\s*gather\b.*\bbuffalo.?style\b.*\bdip\b|\bgood\s*&?\s*gather\b.*\btaco\s+dip\b"), "other"),
        # Herdez taqueria avocado / verde sauce (misrouted from condiments)
        (_r(r"\bherdez\b.*\bavocado\b|\bherdez\b.*\bverde\b"), "guacamole"),
        # Hillshire Snacking dips & spreads / small plates (misrouted from deli)
        (_r(r"\bhillshire\b.*\bdips?\b|\bhillshire\b.*\bspreads?\b|\bhillshire\b.*\bgenoa\b|\bhillshire\b.*\bpepperoni\b.*\bgarlic\b"), "other"),
        # Krinos taramosalata (Greek fish roe dip)
        (_r(r"\bkrinos\b|\btaramosalata\b"), "other"),
        # Marie's chunky blue cheese dressing + dip
        (_r(r"\bmarie.?s\b.*\bdressing\b|\bmarie.?s\b.*\bdip\b|\bblue\s+cheese\s+dressing\b.*\bdip\b"), "other"),
        # Market Pantry meat & cheese snack tray (misrouted)
        (_r(r"\bmarket\s+pantry\b.*\bsnack\s+tray\b|\bmeat\s*&?\s*cheese\s+snack\s+tray\b"), "other"),
        # P3 portable protein pack (misrouted from bars/meals)
        (_r(r"\bp3\b.*\bportable\b|\bportable.*\bprotein.*\bpack\b"), "other"),
        # Sargento balanced breaks / crackers combo
        (_r(r"\bsargento\b.*\bbalanced\s+breaks?\b|\bbalanced\s+breaks?\b.*\bcrackers?\b"), "other"),
        # Taco Bell crunchwrap dip
        (_r(r"\btaco\s+bell\b.*\bdip\b|\bcrunchwrap\s+dip\b"), "other"),
        # TOOM garlic dip
        (_r(r"\btoom\b|\boriginal\s+garlic\s+dip\b"), "other"),
        # Taste of the South jalapeno popper dip
        (_r(r"\btaste\s+of\s+the\s+south\b|\bjalapeno\s+popper\s+dip\b|\bjal[aá]pe[nñ]o\s+popper\s+dip\b"), "other"),
        # Tostitos jalapeno popper dip
        (_r(r"\btostitos\b.*\bjalapeno\b.*\bdip\b|\btostitos\b.*\bpopper\s+dip\b"), "other"),
        # Wegmans cheese spreads / dips / specialty
        (_r(r"\bwegmans\b.*\bcheese\s+spread\b|\bwegmans\b.*\barthichoke\s+asiago\b|\bwegmans\b.*\bbuffalo.?style.*cheddar\b"), "cream_cheese"),
        (_r(r"\bwegmans\b.*\bgarlic\s+and\s+herb\s+cheese\b|\bwegmans\b.*\bhoney\s+pecan\s+cream\s+cheese\b|\bwegmans\b.*\bvegetable\s+cream\s+cheese\b"), "cream_cheese"),
        (_r(r"\bwegmans\b.*\bremoulade\b|\bwegmans\b.*\bsalted\s+caramel\s+cannoli\s+dip\b"), "other"),
        (_r(r"\bwegmans\b.*\bprovolini\b|\bwegmans\b.*\bantipasti\b|\bwegmans\b.*\bolive\s+salad\b"), "tapenade"),
        (_r(r"\bwegmans\b.*\bgame\s+day\b"), "other"),
        # essi x FTP tyrokafteri
        (_r(r"\bessi\b.*\btyrokafteri\b|\btyrokafteri\b"), "yogurt_dip"),
        # Veggie cream cheese spread catch-all
        (_r(r"\bcream\s+cheese\s+spread\b|\bflavored\s+cream\s+cheese\b"), "cream_cheese"),
    ],

    "composite.salads_prepared": [
        (_r(r"\bsalad\s+kit\b|\bkitchen\s+salad\s+kit\b|\bchopped\s+salad\s+kit\b"), "salad_kit"),
        (_r(r"\bcoleslaw\b|\bcole\s+slaw\b|\bbroccolini\s+slaw\b|\bbroccoli\s+slaw\b"), "coleslaw"),
        (_r(r"\bprepared\s+salad\b|\bchicken\s+salad\b|\btuna\s+salad\b|\bmacaroni\s+salad\b|\bpotato\s+salad\b|\bpasta\s+salad\b|\bbean\s+salad\b|\bcobb\s+salad\b|\bcaesar\s+salad\b|\bgreek\s+salad\b|\bkale\s+salad\b|\bgrain\s+salad\b|\bfarro\s+salad\b|\bquinoa\s+salad\b|\btabouli\b|\btabbouleh\b"), "prepared_salad"),
        (_r(r"\bslaw\b|\bshredded\s+cabbage\b|\bcoleslaw\s+mix\b|\brain?bow\s+slaw\b|\basin\s+slaw\b|\bcabbage\b.*\bshredded\b|\bshredded\b.*\bcabbage\b"), "coleslaw"),
        (_r(r"\bsalad\s+topper\b|\btopper\b.*\bsalad\b|\bshrimp.*topper\b|\bsalmon.*topper\b|\begg.*topper\b|\begg\s+salad\b|\bcouscous\s+salad\b|\bapple\b.*\bgrape\b.*\bcheese\b|\bfruit.*cheese.*bites\b"), "prepared_salad"),
        (_r(r"\bgreens\b|\blettuce\b|\bspinach\b|\barugula\b|\bmixed\s+greens\b|\bbaby\s+greens\b|\bromaine\b|\bspring\s+mix\b|\bmesclun\b|\bradicchio\b|\bendive\b|\bwatercress\b|\biceberg\b|\bbutterhead\b|\bbibb\b|\bfield\s+greens\b|\bsuperfood\s+greens\b|\bpower\s+greens\b|\bkale\b|\bblend\b|\bitalian\s+blend\b|\bbold\s+mix\b|\bgarden\s+salad\b|\bamerican\s+blend\b|\bescarole\b|\bcabbage\b"), "leafy_greens"),
        # Fruit & cheese bites / apples grapes & cheese  
        (_r(r"\bapples?\b.*\bgrapes?\b.*\bcheese\b|\bgrapes?\b.*\bcheese\b.*\bbites?\b|\bfruit\b.*\bcheese\b.*\bbites?\b"), "prepared_salad"),
        # Chickpea salad / 'un-tuna' salad / tarragon turkey salad
        (_r(r"\bchickpea\b.*\bsalad\b|\bun.tuna\b|\bturkey\s+salad\b|\blobster\s+salad\b|\bshrimp\s+salad\b|\bneptune\s+salad\b|\bfiesta\s+salad\b|\bgreen\s+goddess\s+salad\b|\bacme\b.*\bsalad\b|\bsalmon\s+salad\b"), "prepared_salad"),
        # Poke / sushi salad
        (_r(r"\bpoke\b|\bseaweed\s+salad\b|\bazuma\b|\bsushi\b.*\bsalad\b"), "prepared_salad"),
        # Gigandes / bean salads / caviar salad
        (_r(r"\bgigandes?\b|\btexas\s+style\s+caviar\b|\bvinaigrette\b.*\bbeans?\b"), "prepared_salad"),
        # Noodle salads
        (_r(r"\bnoodle\s+salad\b|\bthai\s+peanut\s+noodle\b|\bpeanut\s+udon\b|\budon\s+salad\b"), "prepared_salad"),
        # Mezze platter / harvest salad / carry-out salad
        (_r(r"\bmezze\s+platter\b|\bharvest\s+salad\b"), "prepared_salad"),
        # Carrots & grapes with pretzels — snack pack style
        (_r(r"\bcarrots?\b.*\bgrapes?\b.*\bpretzel\b|\bpretzels?\b.*\bcheese\b.*\bcarrot\b"), "prepared_salad"),
        # Vegetable roll
        (_r(r"\bvegetable\s+roll\b"), "prepared_salad"),
    ],

    "composite.soups_ready": [
        (_r(r"\btomato\s+soup\b|\btomato\s+bisque\b|\btomato\s+basil\s+soup\b"), "tomato_soup"),
        (_r(r"\bchicken\s+(?:noodle\s+)?soup\b|\bchicken\s+soup\b|\bchicken\s+tortilla\s+soup\b|\bchicken\s+and\s+rice\s+soup\b|\bchicken\s+with\b.*\bsoup\b"), "chicken_soup"),
        (_r(r"\blentil\s+soup\b|\bsplit\s+pea\b|\bpea\s+soup\b|\bblack\s+bean\s+soup\b|\bminestrone\b|\bvegetable\s+soup\b|\bveggie\s+soup\b|\bonion\s+soup\b|\bmushroom\s+soup\b|\bmiso\s+soup\b|\bramen\s+soup\b|\bitalian\s+wedding\b|\btuscan\b.*\bsoup\b|\btortellini\s+soup\b|\bwhite\s+bean\s+soup\b|\bkale\s+soup\b"), "lentil_soup"),
        (_r(r"\bpotato\s+soup\b|\bclam\s+chowder\b|\bchowder\b|\bcorn\s+chowder\b|\blobster\s+bisque\b|\bcrab\s+bisque\b|\bsquash\s+soup\b|\bbutternut\b.*\bsoup\b|\bcarrot\s+soup\b|\bcauliflower\s+soup\b|\bbaked\s+potato\s+soup\b"), "potato_soup"),
        (_r(r"\bbisque\b"), "bisque"),
        (_r(r"\bchili\b"), "chili"),
    ],

    "composite.sandwiches_wraps": [
        (_r(r"\blunchable\b|\blunch\s+kit\b"), "lunchable"),
        # Charcuterie / meat+cheese snack packs (Olli, Good & Gather, Hillshire, Columbus panino)
        (_r(r"\bsnack\s+pack\b|\bsnack\s+plate\b|\bsnack\s+tray\b|\bpanino\b|\bprosciutto\b.*\bmozzarella\b|\bpepperoni\b.*\bcheese\b|\bsalami\b.*\bcheese\b|\bsopressata\b.*\bchedd\b|\bgenoa\b.*\bfontina\b|\bsmall\s+plates?\b|\bprotein\s+combo\b|\bprotein\s+snacker\b"), "snack_plate"),
        (_r(r"\btacos?\b|\bchimichurri\s+taco\b|\btaquito\b"), "wrap_burrito"),
        (_r(r"\bwrap\b|\bburrito\b|\bpocket\s+sandwich\b|\bpb&j\b|\bpeanut\s+butter.*jelly\s+sandwich\b|\bcrustless\b.*\bsandwich\b|\bpbj\b"), "sandwich"),
        (_r(r"\bsandwich\b|\bsub\b|\bhoagie\b|\btoast\b.*\bavocado\b|\bavocado\s+toast\b"), "sandwich"),
    ],

    "composite.sides_prepared": [
        # Fries / potato sides (expanded — hashbrowns, scallopini, wedges, mashed, gnocchi)
        (_r(r"\bfries\b|\bfrench\s+fr\b|\bwaffle\s+fry\b|\btater\s+tots?\b|\bhash\s+browns?\b|\bhashbrowns?\b|\bhashed\s+browns?\b|\bonion\s+rings?\b|\bpotato\s+puffs?\b|\bpotato\s+skins?\b|\bore.ida\b|\balexia\b.*\bpotat\b|\bpotato\s+wedges?\b|\bpotato\s+latkes?\b|\blatkes?\b|\bpotato\s+pancakes?\b|\bpotato\s+gratin\b|\bscalloped\s+potatoes?\b|\bmashed\s+potatoes?\b|\bwhipped\s+potatoes?\b|\bpotato\s+bites?\b|\bpierogi\b|\bpierog\b|\bherbes?\s+de\s+provence\b.*\bpotato\b|\bscallopini\s+potatoes?\b|\bpotato\s+croquette\b|\bpotato\s+dumpling\b|\bsweet\s+potatoes?\b|\bmashed\s+sweet\b|\bsweet\s+potato\s+(?:fries|puffs|tots)\b|\byam\b|\bgnocchi\b"), "fries_potato"),
        # Fried / breaded appetizer sides (mozzarella sticks, cheddar curds, etc.)
        (_r(r"\bmozzarella\s+sticks?\b|\bcheddar\s+curds?\b|\bcheese\s+curds?\b|\bbrie\s+bites?\b|\bcheese\s+bites?\b|\bbreaded\b.*\bcheese\b|\bfried\b.*\bcheese\b"), "other"),
        # Vegetable bird's nests / ethnic side dishes
        (_r(r"\bbird'?s?\s+nests?\b|\bonion\s+flowers?\b|\bcorn\s+ribs?\b|\bvegetable\s+bird\b"), "other"),
        # Mac & cheese / pasta sides (expanded — 3-cheese pasta, Annie's, gluten-free mac)
        (_r(r"\bmac\s+(?:and|&|n)\s+cheese\b|\bmacaroni\s+(?:and|&|&)\s+(?:cheese|cheddar)\b|\bmac\s+cheese\b|\bshells\s+(?:and|&)\s+cheese\b|\bpasta\s+(?:and|&)\s+(?:cheese|cheddar)\b|\bpasta\s+shells\b.*\bsauce\b|\bpasta\s+side\b|\bknorr\s+pasta\b|\bpasta\s+salad\b|\bmac\b.*\b(?:cheese|cheddar)\b|\bgoodles\b|\bvelveeta\b.*\bshell\b|\bcheese\s+pasta\b|\bspinach\s+(?:&|and)?\s+artichoke\s+pasta\b|\b3\s*-?\s*cheese\b.*\bpasta\b|\bthree\s+cheese\b.*\bpasta\b|\bcheesy\s+pasta\b|\bpasta\s+(?:bake|casserole)\b|\bmacaroni\b.*\bcheddar\b|\brice\s+pasta\b.*\bcheese\b|\brice\s+pasta\b.*\bcheddar\b"), "pasta_side"),
        # Noodle dishes (ramen, lo mein, pad thai, squiggly knife cut noodles)
        (_r(r"\bnoodle\s+dish\b|\bnoodle\s+bowl\b|\binstant\s+noodle\b|\bramen\s+cup\b|\bcup\s+noodle\b|\bpad\s+thai\b|\blo\s+mein\b|\bmomofuku\b|\bnoodle\s+kit\b|\bstir\s+fry.*\bnoodle\b|\bsquiggly\b.*\bnoodle\b|\bknife\s+cut\b.*\bnoodle\b|\bcut\s+style\s+noodles?\b|\bnoodles?\b"), "noodle_dish"),
        # Broth-cooked rice (A Dozen Cousins, etc.)
        (_r(r"\bbroth\s+rice\b|\brice\b.*\bbone\s+broth\b|\bcooked\s+in\s+(?:bone\s+)?broth\b|\ba\s+dozen\s+cousins\b.*\brice\b|\bdozen\s+cousins\b.*\brice\b"), "rice_dish"),
        # Rice dishes
        (_r(r"\brice\s+pilaf\b|\brice.a.roni\b|\bfried\s+rice\b|\brice\s+bowl\b|\brice\s+mix\b|\brice\s+dish\b|\bspanish.style\s+rice\b|\bspanish\s+rice\b|\byellow\s+rice\b|\bjasmine\s+rice\b.*\bready\b|\bbasmati\s+rice\b.*\bready\b|\bready\s+rice\b|\bben\s*s\s+original\b|\bstreamables.*\brice\b|\bsteamables\b.*\brice\b|\bsteamables\b|\bstreamables\b|\brice\s+blend\b|\bbrown\s+rice\b.*\bready\b|\bcilantro\s+lime\s+rice\b|\bzatarain\b|\bjambalaya\b|\bnear\s+east\b|\btortilla\s+española\b|\bspanish\s+omelette\b"), "rice_dish"),
        # Grain / quinoa / couscous sides (bare "Couscous", "Quinoa", steamable quinoa)
        (_r(r"\bgrain\s+blend\b|\bquinoa\b|\bcouscous\b|\bancient\s+grain\b|\bgrain\s+side\b|\bseeds\s+of\s+change\b|\blentil\s+blend\b|\bwhole\s+grain\s+blend\b|\bgreek\s+chickpeas?\b|\bchickpeas?\b.*\bcumin\b|\bchickpeas?\b.*\bpars\b|\bwhole\s+grain\b|\blentils?\b.*\bquinoa\b"), "grain_side"),
        # Soup sides (packaged soup cups/cups, not ready-to-eat)
        (_r(r"\bsoup\s+side\b|\binstant\s+soup\b|\bsoup\s+mix\b|\bmiso\s+soup\b|\bsoup\s+packet\b"), "soup_side"),
        # Pancakes (Thai coconut, potato, etc.) when in sides context
        (_r(r"\bcoconut\s+pancakes?\b|\bkanom\s+krok\b|\bthai\b.*\bpancakes?\b"), "other"),
        # Frozen vegetable blends (fajita blend, kale & spinach, fire-roasted mixes)
        (_r(r"\bfajita\s+blend\b|\bfire.roasted\s+fajita\b|\bspecial\s+blend\b|\bkale\b.*\bspinach\b|\bgreen\s+mix\b|\bfrozen\s+(?:vegetable|veggie)\s+blend\b|\bfrozen\s+(?:kale|spinach|broccoli|green)\b"), "grain_side"),
        # A Dozen Cousins beans (ready-to-eat seasoned beans — sides context)
        (_r(r"\ba\s+dozen\s+cousins\b|\bdozen\s+cousins\b"), "grain_side"),
        # Golden Jewel Blend / grain-veggie medley blends
        (_r(r"\bjewel\s+blend\b|\bmediterranean\s+grain\b|\bmediterranean.*blend\b|\bspecial\s+blends?\b"), "grain_side"),
        # Vegetable sides / veggie bowls / roasted veg / stuffed vegetables
        (_r(r"\bveggie\s+bowl\b|\bvegetable\s+bowl\b|\broasted\s+vegetable\b|\bvegetable\s+blend\b|\bveggie\s+blend\b|\bvegetable\s+hash\b|\bvegetable\s+stir.fry\b|\bgreen\s+beans?\b.*\bside\b|\bgarlic\b.*\bgreen\s+beans?\b|\bcreamed\s+spinach\b|\broasted\s+broccoli\b|\broasted\s+asparagus\b|\broasted\s+carrot\b|\broasted\s+brussels\b|\broasted\s+sweet\s+potato\b|\broasted\s+cauliflower\b|\briced\s+cauliflower\b|\bcauliflower\s+rice\b|\bveggie\s+tots\b|\bvegetable\s+tots\b|\bveggie\s+cakes\b|\bfalafel\b|\bdolmas\b|\beggplant\b|\bplantain\b|\bfried\s+plantain\b|\bchickpea\b.*\bside\b|\blentil\b.*\bside\b|\bmoroccan\b.*\bchickpea\b|\bmina\b.*\bchickpea\b|\bstuffing\b|\bstuffed\s+pepper\b|\bstuffed\s+squash\b|\bstuffed\s+cabbage\b|\bstuffed\s+mushroom\b|\bvegetable\s+side\b|\bveggie\s+side\b|\bside\s+dish\b|\bgreen\s+beans?\b|\bbrussels\b|\basparagus\b|\bbroccolini\b|\bbok\s+choy\b|\bzucchini\b|\bsquash\b|\bkabocha\b|\bdelicata\b|\bacorn\s+squash\b|\bbutternut\b|\bpurée\b.*\bvegetable\b|\bveg\s+curry\b|\bsaag\b|\bpalak\b|\baloo\b|\bchana\b|\bdal\b|\bpaneer\b|\bshiitake\b|\bseasoned\s+corn\b"), "grain_side"),
        # Matzoh balls (sides context)
        (_r(r"\bmatzo\s+balls?\b|\bmatzoh\s+balls?\b"), "other"),
        # Frozen sticky rice / InnovAsian
        (_r(r"\binnovasian\b|\bsticky\s+(?:white\s+)?rice\b"), "rice_dish"),
        # Barilla ready pasta rotini
        (_r(r"\bbarilla\b.*\bready\s+pasta\b|\bready\s+pasta\b"), "pasta_side"),
        # Wegmans roasted potatoes (tuscan, herbed)
        (_r(r"\btuscan\s+roasted\s+potatoes?\b|\broasted\s+herbed\s+potatoes?\b|\broasted\s+potatoes?\b"), "fries_potato"),
        # Buttery broccoli / cauliflower puree
        (_r(r"\bbuttery\s+broccoli\b|\bcauliflower\s+puree\b|\bcauliflower\s+veggie\s+puree\b"), "grain_side"),
        # Palmini mashed hearts of palm
        (_r(r"\bpalmini\b"), "other"),
        # Wegmans Gold Pan
        (_r(r"\bgold\s+pan\b"), "grain_side"),
        # Country-style frozen potatoes
        (_r(r"\bcountry.style\s+potatoes?\b"), "fries_potato"),
        # Dr. Praeger's
        (_r(r"\bdr\.?\s+praeger.?s\b"), "grain_side"),
        # Moroccan chickpeas/lentils (Mina brand)
        (_r(r"\bmoroccan\b.*\b(?:lentil|chickpea)\b|\bmina\b.*\b(?:lentil|chickpea)\b"), "grain_side"),
        # SOMOS foods
        (_r(r"\bsomos\b"), "rice_dish"),
        # Jasberry rice
        (_r(r"\bjasberry\b"), "rice_dish"),
        # Dill roasted carrots (Wegmans)
        (_r(r"\bdill\s+roasted\s+carrots?\b"), "grain_side"),
        # Broccoletti with pesto (Wegmans)
        (_r(r"\bbroccoletti\b"), "grain_side"),
        # Tuscan cannellini beans (Wegmans)
        (_r(r"\btuscan\s+cannellini\b"), "grain_side"),
        # Birds Eye stir fry
        (_r(r"\bbirds?\s+eye\b.*\bstir.fry\b|\bbroccoli\s+stir.fry\b"), "grain_side"),
        # Potato dumplings
        (_r(r"\bpotato\s+dumpling\b"), "fries_potato"),
        # Ben's Original rice varieties
        (_r(r"\bben.?s\s+original\b|\blong\s+grain\b.*\bwild\s+rice\b|\bwild\s+rice\b.*\bseasoned\b"), "rice_dish"),
        # Betty Crocker au gratin / casserole potatoes
        (_r(r"\bbetty\s+crocker\b.*\bpotat\b|\bau\s+gratin\b.*\bpotat\b|\bcasserole\s+potatoes?\b"), "fries_potato"),
        # Birds Eye cauliflower / frozen veg dishes
        (_r(r"\bbirds?\s+eye\b.*\bcauliflower\b.*\bmashed\b|\bbirds?\s+eye\b.*\bcauliflower\s+wings?\b|\bbirds?\s+eye\b.*\bcheesy\s+broccoli\b"), "grain_side"),
        # Devour loaded cheesy potatoes
        (_r(r"\bdevour\b|\bloaded\s+cheesy\s+potatoes?\b"), "fries_potato"),
        # Feel Good Foods gluten free jalapeno bites
        (_r(r"\bfeel\s+good\s+foods?\b|\bgluten\s+free\s+crispy\s+jalape[nñ]o\s+bites?\b"), "other"),
        # Golden potato pancakes
        (_r(r"\bgolden\s+pancakes?\b.*\bpotato\b"), "fries_potato"),
        # Good & Gather basmati rice / chimichurri potatoes / elbow mac
        (_r(r"\bgood\s*&?\s*gather\b.*\bbasmati\s+rice\b|\bgood\s*&?\s*gather\b.*\bspiced\s+basmati\b|\bgood\s*&?\s*gather\b.*\b90\s+second\b.*\brice\b"), "rice_dish"),
        (_r(r"\bgood\s*&?\s*gather\b.*\bchimichurri\b.*\bpotatoes?\b|\bgood\s*&?\s*gather\b.*\bmini\s+creamer\s+potatoes?\b"), "fries_potato"),
        (_r(r"\bgood\s*&?\s*gather\b.*\belbow.*\bcheddar\b|\bgood\s*&?\s*gather\b.*\bmacaroni.*cheese\b"), "pasta_side"),
        # Goya mexican rice / chicken rice
        (_r(r"\bgoya\b.*\brice\b|\bmexican\s+rice\b.*\bchicken\b"), "rice_dish"),
        # Hamburger Helper beef stroganoff
        (_r(r"\bhamburger\s+helper\b|\bbeef\s+stroganoff\b.*\bpasta\b|\bpasta\s+meal\s+kit\b"), "pasta_side"),
        # Idahoan mash potatoes
        (_r(r"\bidahoan\b|\bbuttery\s+homestyle\s+mash\b"), "fries_potato"),
        # Jovial organic gluten free mac
        (_r(r"\bjovial\b.*\bmac\b|\bgluten\s+free.*\bmac\b|\bdairy\s+free.*\bmac\b"), "pasta_side"),
        # Mac and cheese bites
        (_r(r"\bmac\s+and\s+cheese\s+bites?\b|\bmacaroni.*cheese.*bites?\b"), "other"),
        # Market Pantry frozen mozzarella sticks / mac bites
        (_r(r"\bmarket\s+pantry\b.*\bmozzarella\s+sticks?\b|\bmarket\s+pantry\b.*\bmac.*bites?\b"), "other"),
        # Mina Moroccan chickpeas
        (_r(r"\bmina\b.*\bmoroccan\s+chickpeas?\b|\bmoroccan\s+chickpeas?\b"), "grain_side"),
        # Onion flowers
        (_r(r"\bonion\s+flowers?\b"), "other"),
        # Sargento balanced breaks (misrouted from dips to sides)
        (_r(r"\bsargento\b.*\bbalanced\s+breaks?\b"), "other"),
        # Wegmans chicken tenders (prepared chicken in sides)
        (_r(r"\bwegmans\b.*\bchicken\s+tenders?\b"), "other"),
        # Wegmans frozen chicken dumpling bites / vegetable gyoza
        (_r(r"\bwegmans\b.*\bdumpling\s+bites?\b|\bwegmans\b.*\bgyoza\b"), "grain_side"),
        # Wegmans frozen french-style potatoes / tater puffs
        (_r(r"\bwegmans\b.*\bfrench.style\s+potatoes?\b|\bwegmans\b.*\btater\s+puffs?\b"), "fries_potato"),
        # Wegmans frozen jalapeno pierogies / white cheddar / wild mushroom
        (_r(r"\bwegmans\b.*\bpierogies?\b"), "fries_potato"),
        # Wegmans frozen mozzarella sticks / fried mozzarella sticks
        (_r(r"\bwegmans\b.*\bmozzarella\s+sticks?\b"), "other"),
        # Wegmans frozen mac & cheese bites
        (_r(r"\bwegmans\b.*\bmac.*cheese.*bites?\b|\bwegmans\b.*\bfrozen\s+mac\b"), "other"),
        # Wegmans frozen uncured beef franks in pastry
        (_r(r"\bwegmans\b.*\bbeef\s+franks?\b.*\bpastry\b|\bwegmans\b.*\buncured\b.*\bpastry\b"), "other"),
        # Wegmans mediterranean grain blends
        (_r(r"\bwegmans\b.*\bmediterranean\s+style\s+grain\b|\bwegmans\b.*\bgrain\s+blends?\b"), "grain_side"),
    ],

    "produce.fruit": [
        (_r(r"\bcut\s+fruit\b|\bfresh.cut\b|\bsliced\b.*\bfruit\b|\bfruit\s+tray\b|\bfruit\s+cup\b|\bfruit\s+bowl\b|\bfruit\s+salad\b"), "cut_fruit"),
        # Smoothie blends in produce section
        (_r(r"\bsmoothie\s+blend\b|\bfrozen.*\bfruit\b|\bfruit.*\bblend\b|\bfruits.*\bgreens\b|\bgreens.*\bfruit\b"), "cut_fruit"),
        # Named fruits — stems without trailing \b to handle plurals (strawberr→strawberry/berries)
        (_r(r"\bfruit\b|\bapple(?:s)?\b|\bbanana(?:s)?\b|\bgrape(?:s)?\b|\bstrawberr|\bblueberr|\braspberr|\bwatermelon\b|\bpeach(?:es)?\b|\bpear(?:s)?\b|\bplum(?:s)?\b|\bmango(?:es)?\b|\bpineapple\b|\bcantaloupe\b|\bhoneydew\b|\bkiwi\b|\borange(?:s)?\b|\blemon(?:s)?\b|\blime(?:s)?\b|\bcherry\b|\bcherries\b|\bavocado(?:s)?\b|\bgrapefruit\b|\bclementine(?:s)?\b|\btangerine\b|\bmandarin(?:s)?\b|\bnectarine(?:s)?\b|\bapricot(?:s)?\b|\bfig(?:s)?\b|\bpomelo\b|\bsumo\s+citrus\b|\bsumo\b|\bpersimmon(?:s)?\b|\bpassion\s+fruit\b|\bdragon\s+fruit\b|\bguava\b|\bpapaya\b|\blychee\b|\bgooseberr|\bblackberr|\belderberr|\bcranberr|\bmelon(?:s)?\b|\bcoconut\b|\bplantain(?:s)?\b|\bfeijoa\b|\bdurian\b|\btamarind\b|\bjackfruit\b|\bstar\s+fruit\b|\bcarambola\b|\baca[íi]\b|\bpomegranate\b|\baril(?:s)?\b|\bpom\s+wonderful\b|\bgolden\s+berr|\bgoji\s+berr|\bgoji\b|\bcurrant(?:s)?\b|\bquince\b|\bpluot(?:s)?\b|\bfruit\s+medley\b|\bfruitful\b|\byellow\s+cling\b|\bcling\s+peach\b"), "fresh_fruit"),
    ],

    "produce.vegetable": [
        # Mixed / blended / cut vegetable packs
        (_r(r"\bcut\s+veg\b|\bfresh.cut\b.*\bveg\b|\bstir.fry\s+(mix|blend|veggie)\b|\bstir\s+fry\s+veggie\b|\bveg.*\bmix\b|\bvegetable\s+tray\b|\bvegetable\s+medley\b|\bvegetable\s+blend\b|\bfrozen\s+(?:mixed\s+)?vegetable(?:s)?\b|\bchopped\s+salad\s+blend\b|\bsalad\s+blend\b|\bcoleslaw\s+mix\b|\bmirepoix\b|\bcruciferious\b|\bcruciferous\b|\bready\s+veggie(?:s)?\b|\bveggie\s+blend\b|\bpetite\s+potato\s+medley\b|\bpotato\s+medley\b"), "cut_vegetable"),
        # Named vegetables — extended list including bare produce names
        (_r(r"\bveg\b|\bcarrot(?:s)?\b|\bbroccoli\b|\bcauliflower\b|\bzucchini\b|\bbell\s+pepper\b|\btomato(?:es)?\b|\bonion(?:s)?\b|\bcelery\b|\bcucumber(?:s)?\b|\bcorn\b|\bpotato(?:es)?\b|\bsweet\s+potato(?:es)?\b|\byam(?:s)?\b|\bkale\b|\bspinach\b|\bbeet(?:s)?\b|\bradish(?:es)?\b|\basparagus\b|\bgreen\s+bean(?:s)?\b|\bbean(?:s)?\b|\bpeas\b|\bbrussels\b|\bleek(?:s)?\b|\bparsnip(?:s)?\b|\bturnip(?:s)?\b|\bsquash\b|\bpumpkin\b|\beaubergine\b|\beggplant\b|\bpepper(?:s)?\b|\bmushroom(?:s)?\b|\bartichoke(?:s)?\b|\bfennel\b|\bbok\s+choy\b|\bcabbage\b|\bbroccolini\b|\bbroccoletti\b|\bkohlrabi\b|\bjicama\b|\bsunchoke(?:s)?\b|\brhubarb\b|\btaro\b|\bcassava\b|\byucca\b|\bwatercress\b|\bendive\b|\bradicchio\b|\bchive(?:s)?\b|\bshallot(?:s)?\b|\bscallion(?:s)?\b|\bgarlic\b|\bdaikon\b|\bbok\b|\bnapa\b|\bswiss\s+chard\b|\bcollard\b|\bsorrel\b|\barugula\b|\blettuce\b|\bromaine\b|\bedamame\b|\bbamboo\s+shoot(?:s)?\b|\bwater\s+chestnut(?:s)?\b|\bheart(?:s)?\s+of\s+palm\b|\bchayote\b|\bbitter\s+melon\b|\blotus\s+root\b|\bcelery\s+root\b|\bceleriac\b|\bparsley\s+root\b|\bsunchoke\b|\bgreen\s+leaf\b|\bbibb\b|\bbutterhead\b|\biceberg\b|\bspring\s+mix\b|\bmesclun\b|\bfield\s+greens\b|\bmixed\s+greens\b|\bbaby\s+greens\b|\bpower\s+greens\b|\bokra\b|\bavocado(?:s)?\b|\bfresh\s+ginger\b|\bginger\s+root\b|\brusset\b|\bbaking\s+potato\b|\bgold\s+potato\b|\bred\s+potato\b|\bfava\s+bean(?:s)?\b|\bsnow\s+pea(?:s)?\b|\bsnap\s+pea(?:s)?\b|\bsugar\s+snap\b|\bhabanero\b|\bjalapen\b|\bpoblano\b|\bmukimame\b|\bfiddlehead\b|\bbaby\s+bok\b|\blemongrass\b|\btomatillo\b|\brapini\b|\bdandelion\s+greens\b|\balfalfa\s+sprout(?:s)?\b|\bsprout(?:s)?\b|\bturmeric\s+root\b|\bcauletti\b|\bnappa\b|\bchile(?:s)?\b|\bjalape\b|\bbutternut\b|\bthai\s+chil|\bginger\b"), "fresh_vegetable"),
    ],

    "produce.herbs_aromatics": [
        (_r(r"\bgarlic\b|\bonion\b|\bshallot\b|\bscallion\b|\bgreen\s+onion\b|\bleek\b"), "garlic_onion"),
        (_r(r"\bherb\b|\bbasil\b|\bparsley\b|\bcilantro\b|\bmint\b|\bthyme\b|\brosemary\b|\bdill\b|\bsage\b|\borgano\b|\btarragon\b|\bchive\b"), "fresh_herb"),
    ],

    "drinks.functional": [
        (_r(r"\benergy\s+drink\b|\benergy\s+can\b|\bred\s+bull\b|\bmonster\b|\bcelsius\b|\bryse\b|\balani\b|\bbang\s+energy\b|\bnocco\b|\bzoa\b|\bc4\s+energy\b|\bghoul\s+fuel\b|\bvenom\s+energy\b|\brock\s+star\b|\bnos\s+energy\b|\bfull\s+throttle\b|\bamp\s+energy\b"), "energy_drink"),
        (_r(r"\bprotein\s+shake\b|\bprotein\s+drink\b|\bprotein\s+smoothie\b|\bprotein\s+milk\b|\bhigh\s+protein\s+drink\b|\bcore\s+power\b|\borgain\b|\bpremier\s+protein\b|\bisopure\b|\bboost\s+protein\b|\bensure\s+protein\b|\bcarnation\b.*\bprotein\b|\bbreakfast\s+essentials\b|\bonest\s+protein\b|\bremedy\s+organics\b"), "protein_shake"),
        (_r(r"\bsports\s+drink\b|\bgatorade\b|\bpowerade\b|\bbodyarmor\b|\bbody\s+armor\b|\bpropel\b|\bpedialyte\b|\bliquid\s+i\.?v\b|\bnuun\b|\bdrip\s+drop\b|\brecharge\b.*\bdrink\b|\belectrolyte\s+drink\b|\belectrolyte\s+water\b|\bhydration\s+drink\b|\bsports\s+hydration\b"), "sports_drink"),
        (_r(r"\bwellness\s+shot\b|\bimmunity\s+shot\b|\bshot\b.*\bwellness\b|\bshot\b.*\bimmunity\b|\bginger\s+shot\b|\bturmeric\s+shot\b|\bvive\s+organic\b|\bjuice\s+shot\b|\bwheatgrass\s+shot\b|\bshots?\b.*\bprobiotic\b|\bfire\s+cider\b|\bbragg\b.*\bshot\b"), "probiotic_drink"),
        (_r(r"\bprobiotic\s+drink\b|\bprobiotic\s+smoothie\b|\bkefir\s+drink\b|\bfermented\s+drink\b|\bgut\s+health\s+drink\b|\bonce\s+upon\s+a\s+farm\b.*\bsmoothie\b|\bsmoothie\b.*\bprobiotic\b"), "probiotic_drink"),
        (_r(r"\belectrolyte\b|\bhydration\s+mix\b|\bhydration\s+packet\b|\belectrolyte\s+mix\b|\boath\s+nutrition\b|\bliquid\s+iv\b|\bpedialyte\s+powder\b|\bdrip\s+drop\b|\bnuun\b|\bhydrant\b"), "electrolyte_drink"),
        (_r(r"\bnootropic\b|\bfocus\s+drink\b|\bcogniti\b|\bbrain\s+drink\b|\balpha\s+brain\b|\bobvi\b|\bkado\b|\bom\s+mushroom\b|\bmushroom\s+drink\b|\blion.s\s+mane\s+drink\b|\breishi\s+drink\b|\badapto\b|\bfunctional\s+drink\b|\bsuperfood\s+latte\b|\bmatcha\s+latte\b.*\bfunctional\b"), "nootropic_drink"),
        # Coconut water appearing in functional
        (_r(r"\bcoconut\s+water\b"), "electrolyte_drink"),
        # Vitaminwater / enhanced waters in functional
        (_r(r"\bvitaminwater\b|\bvitamin\s+water\b"), "sports_drink"),
        # Alkaline water with electrolytes (Good & Gather)
        (_r(r"\balkaline\s+water\b|\balkaline.*electrolyte\b|\bwater.*electrolyte\b|\belectrolyte.*water\b"), "electrolyte_drink"),
        # Watermelon water / cactus water
        (_r(r"\bwtrmln\b|\bwatermelon\s+w(?:a|t)r\b|\bwatermelon\s+water\b|\bwatermelon\s+blend\b|\bcactus\s+water\b|\bpricklee\b|\bwtr\b.*\bhydration\b"), "electrolyte_drink"),
        # Probiotic shots (So Good So You, ginger shots, elixirs)
        (_r(r"\bso\s+good\s+so\s+you\b|\bprobiotic\s+shot\b|\bginger\s+elixir\b|\bturmeric\s+elixir\b|\belixir\b|\bbija\s+bhar\b|\binstant\s+turmeric\b"), "probiotic_drink"),
        # Kids' fruit/veggie pouches (Once Upon a Farm) — not a drink per se
        (_r(r"\bonce\s+upon\s+a\s+farm\b|\bkids.\s*snack\b|\bfruit\s*&\s*veggie\b|\bfruit.*veggie\s+pouch\b|\bimmunity\s+blend\s+pouch\b|\bveggie\s+blend\s+pouch\b|\bsnack\s+pouch\b|\bfruit\s*&\s*veggie\s+blend\b|\borganic\s+berry\s+bundle\b|\borganic\s+immunity\s+blends?\b|\bgreen\s+kale\s+&\s+apples?\b|\borganic\s+kids?\b.*\bsnack\b|\bfarm\b.*\bpouch\b|\bgogo\s+squeez\b.*\bfruit\b|\bgutzy\b|\bprebiotic\s+gut\s+health\b"), "other"),
        # Sparkling water misrouted here (Ardor, Hi-Ball sparkling water)
        (_r(r"\bardor\b|\bhi.ball\b.*\bsparkling\b|\bsparkling\s+water\b.*\bfunctional\b|\bchlorophyll\s+water\b"), "other"),
        # Ginger lime shots / wellness shots
        (_r(r"\bginger\s+lime\s+shot\b|\bturmeric\s+relieve\b|\bsuperfruit\b.*\bshot\b|\bcold\s+crusher\s+juice\b|\burban\s+remedy\b.*\bshot\b|\btom.?s\s+juice\b"), "probiotic_drink"),
        # Pickle juice shot (electrolyte-like)
        (_r(r"\bpickle\s+juice\b.*\bshot\b|\bpickle\s+juice\b.*\bstrength\b|\bpickle\s+sport\b"), "electrolyte_drink"),
        # Kencko powdered smoothies
        (_r(r"\bkencko\b|\bpowdered\s+drink\s+mix\b.*\bsmoothie\b"), "protein_shake"),
        # Immorel sparkling lion's mane tea
        (_r(r"\bimmorel\b|\blion.s\s+mane\b.*\btea\b|\bsparkling\b.*\blion.s\s+mane\b"), "nootropic_drink"),
        # Tropicana OJ misrouted to functional
        (_r(r"\btropicana\b"), "other"),
        # Smoothies / blended drinks
        (_r(r"\bsmoothie\b|\bblended\s+drink\b|\bfruit\s+blend\s+drink\b|\borganic\s+smoothie\b"), "protein_shake"),
        # 5 Hour Energy / energy shots
        (_r(r"\b5\s*hour\s+energy\b|\benergy\s+shots?\b|\bextra\s+strength\s+shot\b"), "energy_drink"),
        # BLOOM NUTRITION stick packs
        (_r(r"\bbloom\s+nutrition\b|\bnatural\s+energy\s+stick\s+packs?\b"), "energy_drink"),
        # 4C energy / hydration mix packs
        (_r(r"\b4c\s+energy\b|\bhydration\s*\+\s*electrolytes?\b.*\bmix\b|\bdrink\s+mix\b.*\belectrolytes?\b"), "electrolyte_drink"),
        # LMNT electrolyte packets
        (_r(r"\blmnt\b|\bzero.sugar\s+electrolytes?\b"), "electrolyte_drink"),
        # Lifeway kefir
        (_r(r"\blifeway\b.*\bkefir\b|\borganic\s+kefir\b|\bunsweetened.*\bkefir\b"), "probiotic_drink"),
        # Halfday prebiotic tea
        (_r(r"\bhalfday\b|\bprebiotic\s+lemon\s+iced\s+tea\b"), "probiotic_drink"),
        # Activia probiotic dailies
        (_r(r"\bactivia\b.*\bprobiotic\b|\bprobiotic\s+dailies?\b|\byogurt\s+drink\b.*\bprobiotic\b"), "probiotic_drink"),
        # DANIMALS smoothies
        (_r(r"\bdanimals?\b"), "protein_shake"),
        # Bolthouse Farms protein/nut butter shakes
        (_r(r"\bbolthouse\s+farms?\b"), "protein_shake"),
        # OWYN non-dairy / protein shakes
        (_r(r"\bowyn\b"), "protein_shake"),
        # OIKOS protein shakes
        (_r(r"\boikos\b.*\bshake\b|\bcasein\s+protein\s+shake\b"), "protein_shake"),
        # Genius Gourmet / Spylt / Quest milkshake protein
        (_r(r"\bgenius\s+gourmet\b.*\bshake\b|\bspylt\b.*\bshake\b|\bquest\b.*\bmilkshake\b|\bquest\b.*\bprotein\s+shake\b"), "protein_shake"),
        # Clean Simple Eats clear protein water
        (_r(r"\bclean\s+simple\s+eats\b|\bclear\b.*\bprotein\s+water\b"), "protein_shake"),
        # Protein2O protein water
        (_r(r"\bprotein2o\b|\bclear\s+whey\s+protein\b.*\bwater\b"), "protein_shake"),
        # OLIPOP / Poppi prebiotic soda (misrouted to functional)
        (_r(r"\bolipop\b|\bpoppi\b.*\bprebiotic\b|\bsparkling\s+tonic\b"), "probiotic_drink"),
        # Wildwonder prebiotic + probiotic sparkling
        (_r(r"\bwildwonder\b|\bwild\s*wonder\b"), "probiotic_drink"),
        # Recess mood sparkling / magnesium drinks
        (_r(r"\brecess\b|\bmagnesium\s+l.threonate\b|\bmood\b.*\bsparkling\b"), "nootropic_drink"),
        # ZYN turmeric wellness drink
        (_r(r"\bzyn\b.*\bwellness\b|\bturmeric\s+wellness\b"), "nootropic_drink"),
        # Goldthread plant tonic
        (_r(r"\bgoldthread\b"), "nootropic_drink"),
        # Mamma Chia squeeze pouches
        (_r(r"\bmamma\s+chia\b|\bchia\s+squeeze\b"), "other"),
        # Noka superfood smoothies
        (_r(r"\bnoka\b.*\bsuperfood\b|\bsuperfood\s+smoothies?\b"), "protein_shake"),
        # Urban Remedy probiotic tea tonic
        (_r(r"\burban\s+remedy\b"), "probiotic_drink"),
        # Be Amazing greens RTD
        (_r(r"\bbe\s+amazing\b.*\bgreens?\b"), "protein_shake"),
        # Liquid Death sparkling energy
        (_r(r"\bliquid\s+death\b.*\benergy\b|\bsparkling\s+energy\b"), "energy_drink"),
        # Oats Overnight (standalone shakes, not pouch meals)
        (_r(r"\boats\s+overnight\b"), "protein_shake"),
        # Starbucks Refreshers concentrate
        (_r(r"\bstarbucks\b.*\brefreshers?\b|\brefreshers?\b.*\bconcentrate\b"), "energy_drink"),
        # Pressed Juicery functional
        (_r(r"\bpressed\s+juicery\b.*\blemonade\b|\bmango\s+turmeric\s+lemonade\b"), "other"),
        # Once Upon a Farm squeeze pouches (kids functional)
        (_r(r"\bonce\s+upon\s+a\s+farm\b.*\bpouch\b|\bonce\s+upon\s+a\s+farm\b.*\bkids?\b"), "other"),
        # Sainsa traditional corn drinks
        (_r(r"\bsainsa\b|\bchilate\b|\batol\b"), "other"),
        # Oikos Pro cultured dairy drink
        (_r(r"\boikos\s+pro\b.*\bcultured\b|\bcultured\s+dairy\s+drink\b"), "probiotic_drink"),
        # Alo aloe vera juice drink
        (_r(r"\balo\b.*\baloe\b|\baloe\s+vera\b.*\bjuice\s+drink\b|\bwheatgrass\b.*\bjuice\b"), "other"),
        # Bai beverages (antioxidant)
        (_r(r"\bbai\b.*\bbeverage\b|\bbai\b.*\bclementine\b|\bbai\b.*\bcoconut\b"), "other"),
        # Barebells vanilla milk drink
        (_r(r"\bbarebells?\b.*\bmilk\s+drink\b|\bbarebells?\b.*\bdrink\b"), "protein_shake"),
        # Chobani protein yogurt drink
        (_r(r"\bchobani\b.*\bprotein\b.*\bdrink\b|\bchobani\b.*\byogurt\s+drink\b"), "protein_shake"),
        # Ensure nutrition shake
        (_r(r"\bensure\b.*\bshake\b|\bensure\b.*\bnutrition\b"), "protein_shake"),
        # HOP WTR hop sparkling water
        (_r(r"\bhop\s+wtr\b|\bhop\s+sparkling\b"), "other"),
        # Huel RTD greens / meal replacement
        (_r(r"\bhuel\b"), "protein_shake"),
        # J-Basket boba kit (misrouted)
        (_r(r"\bj.basket\b.*\bboba\b|\binstant.*\bmatcha\b.*\bboba\b"), "other"),
        # Just Ingredients electrolytes mix
        (_r(r"\bjust\s+ingredients\b|\belectrolytes?\s+drink\s+mix\s+packs?\b"), "electrolyte_drink"),
        # KeVita sparkling prebiotic lemonade
        (_r(r"\bkevita\b|\bsparkling\s+prebiotic\s+lemonade\b"), "probiotic_drink"),
        # Ketone-IQ energy drinks
        (_r(r"\bketone.iq\b|\bketone\s+energy\b"), "energy_drink"),
        # Koia plant protein shakes
        (_r(r"\bkoia\b"), "protein_shake"),
        # Machu Picchu yerba mate
        (_r(r"\bmachu\s+picchu\b|\byerba\s+mate\b"), "energy_drink"),
        # MiO liquid water enhancer
        (_r(r"\bmio\b.*\bwater\s+enhancer\b|\bliquid\s+water\s+enhancer\b"), "other"),
        # More Labs morning recovery
        (_r(r"\bmore\s+labs?\b|\bmorning\s+recovery\b"), "nootropic_drink"),
        # Nesquik protein power
        (_r(r"\bnesquik\b.*\bprotein\b|\bprotein\s+power\b.*\bshake\b"), "protein_shake"),
        # Once Upon a Farm organic veggie blend (pouches misrouted)
        (_r(r"\bonce\s+upon\s+a\s+farm\b.*\borganic\b|\bonce\s+upon\s+a\s+farm\b"), "other"),
        # PediaSure
        (_r(r"\bpediasure\b"), "protein_shake"),
        # Poppi prebiotic soda (not yet caught)
        (_r(r"\bpoppi\b"), "probiotic_drink"),
        # Protein Pop flavoured water
        (_r(r"\bprotein\s+pop\b|\bprotein\s+flavoured\s+water\b"), "protein_shake"),
        # The Spare Food Co. blueberry ginger tonic
        (_r(r"\bspare\s+food\s+co\b|\bspare\s+tonic\b"), "probiotic_drink"),
        # Wegmans Zero vitamin water
        (_r(r"\bwegmans\b.*\bzero\b.*\bvitamin\b|\bvitamin\s+infused\s+water\b"), "other"),
    ],

    "composite.meals_entrees": [
        # Frozen entrees — check first
        (_r(r"\bfrozen\s+(?:meal|entree|dinner|breakfast|burrito|pizza|bowl)\b|\bfrozen\b.*\b(?:entree|meal|dinner)\b|\blean\s+cuisine\b|\bswanson\b|\bmarie\s+callender\b|\bdevour\b|\bevol\b|\bhealthy\s+choice\b|\bstouffer\b|\btattooed\s+chef\b"), "frozen_entree"),
        (_r(r"\bfrozen\b.*\b(?:chicken|beef|pork|turkey|salmon|shrimp|fish)\b.*\b(?:patty|patties|strip|strips|nugget|burger|tender|fillet)\b|\bbreaded\s+chicken\b|\bchicken\s+patty\b|\bchicken\s+strip\b|\bchicken\s+tender\b|\bsalmon\s+burger\b|\bpremium.*burger\b"), "frozen_entree"),
        # Bowl format
        (_r(r"\bbowl\b(?!\s+of\b)|\bnoodle\s+bowl\b|\brice\s+bowl\b|\bgrain\s+bowl\b"), "bowl"),
        # Burrito / wrap entrees
        (_r(r"\bburrito\b|\bwrap\b.*\bentree\b|\bbreakfast\s+burrito\b|\bjust\s+egg\b.*\bburrito\b"), "burrito"),
        # Pasta dishes
        (_r(r"\bravioli\b|\btortellini\b|\bpasta\b.*\bdish\b|\blasagna\b|\bmacaroni\b|\bfettuccine\b.*\bentree\b|\bpad\s+thai\b|\bnoodle\s+dish\b|\bpenne\b.*\bentree\b|\bpasta\b.*\bchicken\b|\bpasta\b.*\bbeef\b|\bpasta\b.*\bshrimp\b"), "pasta_dish"),
        # Soup entrees
        (_r(r"\bsoup\b.*\bentree\b|\bstew\b(?!\s+beef|\s+lamb|\s+pork|\s+chicken\s+stew)|\bchili\s+entree\b|\bwhite\s+bean\s+stew\b|\blentil\s+stew\b|\bchickpea\s+stew\b|\bmina\s+stew\b|\bmoroccan\s+stew\b"), "soup_entree"),
        # Sushi / raw fish
        (_r(r"\bsushi\b|\bsashimi\b|\broll\b.*\braw\b|\btuna\b.*\bcombo\b|\bsalmon\b.*\bcombo\b|\bpoke\b|\bahi\s+tuna\b|\bsalmon\b.*\bsamp"), "fresh_prepared_entree"),
        # Rotisserie / whole bird
        (_r(r"\brotisserie\b|\bwhole\s+roasted\s+chicken\b|\broasted\s+chicken\b.*\bcold\b|\bbbq\s+roasted\s+chicken\b"), "rotisserie"),
        # Stir fry
        (_r(r"\bstir.fry\b|\bfried\s+rice\b|\bpad\s+thai\b|\blo\s+mein\b|\bchow\s+mein\b|\bpork\s+fried\s+rice\b|\bbao\s+bun\b|\bdumpling\b|\bpotsticker\b|\bgym\s+sha\b|\bdim\s+sum\b"), "stir_fry"),
        # General fresh prepared (deli, refrigerated)
        (_r(r"\bprepared\b|\bready.to.eat\b|\brefrigerated\s+entree\b|\bwings\b|\bmeatball\b|\bempanada\b|\btamale\b|\bpot\s+pie\b|\bseasoned\b.*\bchicken\b|\bgrilled\s+chicken\b|\bchicken\s+strips\b|\bpork\b.*\bbbq\b|\bkeyword\b|\bpolenta\b.*\bwith\b|\bpasta\b.*\bwith\b"), "fresh_prepared_entree"),
        # Overnight oats / ready-to-eat oats (Mush, MUSH brand)
        (_r(r"\bovernight\s+oats?\b|\bready.to.eat\s+oats?\b|\bmush\b.*\boats?\b|\boats?\b.*\bmush\b|\bpeanut\s+butter\s+overnight\b|\bvanilla\s+overnight\b|\bdark\s+chocolate\s+overnight\b"), "bowl"),
        # Baby food pouches (Happy Baby, Serenity Kids, Little Spoon)
        (_r(r"\bbaby\s+food\b|\bstage\s+[12]\b|\bserenity\s+kids\b|\bhappy\s+baby\b|\bhappybaby\b|\blittle\s+spoon\b.*\bkids\b|\binfant\b|\btoddler\b.*\bmeal\b|\bbaby\b.*\bpouch\b|\bkids.?\s+food\b"), "fresh_prepared_entree"),
        # Kids sliders / chicken veggie sliders
        (_r(r"\bchicken\s+veggie\s+sliders?\b|\bkids\b.*\bsliders?\b|\bfrozen\s+kids\b.*\bfood\b"), "frozen_entree"),
        # Gumbo / cajun / pozole / ratatouille / specific entrees
        (_r(r"\bgumbo\b|\bpozole\b|\bratatouille\b|\bbolognese\b.*\bdinner\b|\bragu\b|\bmapo\s+tofu\b|\bbraised\b|\bdinette\b|\bchicken\s+pozole\b|\bprovencal\b|\bethiopian\s+greens?\b|\bbucatini\b|\bwild\s+boar\b|\bjerk\b.*\bentree\b|\bcajun\b.*\bpeas?\b"), "fresh_prepared_entree"),
        # Variety boxes / meal kits (ButcherBox)
        (_r(r"\bvariety\s+box\b|\bbutcherbox\b|\bmeal\s+prep\b.*\bbox\b|\bcuts?\s+variety\b"), "fresh_prepared_entree"),
        # Pulled chicken / slow-roasted / steam pot (Wegmans Gold Pan)
        (_r(r"\bpulled\s+chicken\b|\bslow\s+roasted\b.*\bchicken\b|\brosemary\s+roasted\s+chicken\b|\bsteam\s+pot\b|\bsteam\s+pot\b.*\bshrimp\b|\bcrab\b.*\bsteam\b|\btofu\s+scramble\b"), "fresh_prepared_entree"),
        # Stuffed corn tortillas / goya entrees
        (_r(r"\bstuffed\s+corn\s+tortilla\b|\bstuffed\s+tortilla\b"), "fresh_prepared_entree"),
        # Black-eyed peas / dinner kits
        (_r(r"\bblack\s+eyed\s+peas?\b.*\bdinner\b|\bblack\s+bean\b.*\bentree\b"), "fresh_prepared_entree"),
        # Risotto / mushroom risotto (Amy's)
        (_r(r"\brisotto\b"), "bowl"),
        # Chia pudding / dessert items misrouted
        (_r(r"\bchia\s+pudding\b"), "fresh_prepared_entree"),
        # Turkey breast roulade / glazed turkey drumsticks
        (_r(r"\btурkey\s+breast\s+roulade\b|\bturkey\s+drumstick\b|\bturkey\s+roulade\b|\bglazed\s+turkey\b"), "fresh_prepared_entree"),
        # Chili (beef/pork/vegan)
        (_r(r"\bchili\b"), "soup_entree"),
        # Beef bourguignon / beef stew entrees
        (_r(r"\bbourguignon\b|\bbeef\s+stew\b.*\bentree\b|\bbeef\s+stew\b.*\brefrig\b"), "fresh_prepared_entree"),
        # Enchiladas / tamales / quesadillas / tinga
        (_r(r"\benchilada\b|\bquesadilla\b|\btinga\b|\bsalsa\s+roja\b|\bsalsa\s+verde\b.*\bchicken\b"), "fresh_prepared_entree"),
        # Quiche / pot pie
        (_r(r"\bquiche\b|\bpot\s+pie\b|\bpotpie\b"), "fresh_prepared_entree"),
        # Eggplant marinara / mac + greens
        (_r(r"\beggplant\s+marinara\b|\bmac\s+\+\s+greens\b|\bautumn\s+mac\b"), "fresh_prepared_entree"),
        # Salmon burger / shrimp burger
        (_r(r"\bsalmon\s+burgers?\b|\bshrimp\s+burgers?\b|\bwild\s+caught\b.*\bburgers?\b"), "frozen_entree"),
        # Stuffed corn tortillas (Goya)
        (_r(r"\bstuffed\s+corn\s+tortillas?\b"), "fresh_prepared_entree"),
        # Tortelloni / fresh pasta dishes
        (_r(r"\btortelloni\b"), "pasta_dish"),
        # Korean ramen kit / spicy ramen kit
        (_r(r"\bramen\s+kit\b|\bspicy\s+korean\s+ramen\b|\bmiso\s+soup\b.*\bramen\b|\blotus\s+foods\b.*\bramen\b"), "stir_fry"),
        # Miracle Noodle / ramen / noodle meals
        (_r(r"\bmiracle\s+noodle\b|\brte\s+meal\b|\bjapan\s+curry\s+noodle\b"), "stir_fry"),
        # Cookout essentials / meal kits (FTP)
        (_r(r"\bcookout\s+essentials?\b|\bsummer\s+cookout\b|\bplant.based\s+cookout\b"), "fresh_prepared_entree"),
        # Roasted chicken / hot roasted / cold roasted (Wegmans)
        (_r(r"\bplain\s+roasted\s+chicken\b|\bhot\s+roasted\s+chicken\b|\broasted\s+chicken\b.*\bhot\b|\brosemary\s+roasted\b.*\bchicken\b|\borganic\s+plain\s+roasted\b|\boven.roasted\s+chicken\b|\borganic\s+roasted\s+chicken\b"), "rotisserie"),
        # Del Real barbacoa / birria / Mexican meals
        (_r(r"\bdel\s+real\b|\bbarbacoa\b|\bbirria\b"), "fresh_prepared_entree"),
        # Pizza poppers / cheese pizza snacks
        (_r(r"\bpizza\s+poppers?\b|\bcheese\b.*\bpizza\s+poppers?\b|\bagainst\s+the\s+grain\b"), "frozen_entree"),
        # Mac & cheese entrees
        (_r(r"\brice\s+mac\s*&\s*cheese\b|\bgluten.free\b.*\bmac\s*&\s*cheese\b|\bfrozen\b.*\bfettuccine\s+alfredo\b|\bfrozen\b.*\bgnocchi\b|\bfour\s+cheese\s+gnocchi\b"), "pasta_dish"),
        # Turkey burgers / salmon burgers (frozen patties)
        (_r(r"\bturkey\s+burger\s+patt\b|\ball\s+natural\s+turkey\s+burger\b"), "frozen_entree"),
        # Chickpea turmeric curry / tasty bite
        (_r(r"\btasty\s+bite\b|\bcoconut\s+chickpea\b.*\bcurry\b|\bchickpea\s+turmeric\s+curry\b"), "fresh_prepared_entree"),
        # Cacio e pepe / cheese pasta
        (_r(r"\bcacio\s+e\s+pepe\b.*\bpasta\b|\bbeecher.?s\b.*\bpasta\b"), "pasta_dish"),
        # Mini oven-baked meatballs / meatballs with sauce
        (_r(r"\bmeatballs?\b.*\bsauce\b|\bmini\s+oven.baked\s+meatballs?\b|\bgold\s+pan\s+meatballs?\b"), "fresh_prepared_entree"),
        # Dumplings (frozen)
        (_r(r"\bdumplings?\b|\bpotstickers?\b|\bfrozen\b.*\bdumplings?\b|\borganic\s+frozen\b.*\bdumplings?\b"), "stir_fry"),
        # Falafel (frozen)
        (_r(r"\bfalafel\b.*\bballs?\b|\bamnons?\b"), "fresh_prepared_entree"),
        # Thai red curry / Indian curry / coconut curry dishes
        (_r(r"\bthai\s+red\s+curry\b|\bthai\s+curry\b|\bgold\s+pan\b.*\bcurry\b"), "fresh_prepared_entree"),
        # Root vegetables + chickpeas tub (Good & Gather — side dish/bowl)
        (_r(r"\broot\s+vegetables?\b.*\bchickpeas?\b|\bfood\s+tub\b"), "bowl"),
        # Fettuccine alfredo frozen
        (_r(r"\bfettuccine\s+alfredo\b"), "pasta_dish"),
        # Organic roasted chicken (Wegmans plain)
        (_r(r"\bwegmans\b.*\broasted\b.*\bchicken\b|\bwegmans\b.*\bchicken\b.*\broasted\b"), "rotisserie"),
        # Indian meals / dal / biryani / masala / curry
        (_r(r"\bdal\b|\bbharta\b|\bbaingan\b|\bkitchari\b|\brajma\b|\bmasala\b.*\bmeal\b|\bbiryani\b|\btikka\s+masala\b|\bmujaddara\b|\bnebbiolo\b.*\bpolenta\b"), "fresh_prepared_entree"),
        # Maya Kaimal / Saffron Road / Chef Bombay brands
        (_r(r"\bmaya\s+kaimal\b|\bsaffron\s+road\b|\bchef\s+bombay\b|\bbrooklyn\s+delhi\b"), "fresh_prepared_entree"),
        # Ipsa brand (Ipsa — all entrees)
        (_r(r"\bipsa\b"), "fresh_prepared_entree"),
        # Rao's Made for Home
        (_r(r"\brao.?s\s+made\s+for\s+home\b|\brao.?s\b.*\bchicken\b"), "fresh_prepared_entree"),
        # Paella bundle / Farm to People meal kits
        (_r(r"\bpaella\b|\beleven\s+madison\b"), "fresh_prepared_entree"),
        # Corned beef hash (Hormel)
        (_r(r"\bhormel\b|\bcorned\s+beef\s+hash\b"), "fresh_prepared_entree"),
        # Egg rolls (Wegmans frozen)
        (_r(r"\begg\s+rolls?\b"), "stir_fry"),
        # Chicken curry with basmati rice
        (_r(r"\bchicken\s+curry\b.*\brice\b|\bcharlie.?s\s+chicken\b"), "fresh_prepared_entree"),
        # Chicken parmesan
        (_r(r"\bchicken\s+parmesan\b|\bchicken\s+parm\b"), "fresh_prepared_entree"),
        # Meatballs (frozen — Italian-style, Good & Gather)
        (_r(r"\bitalian.style\s+chicken\s+meatballs?\b|\bchicken\s+meatballs?\b.*\bfrozen\b|\bfrozen\b.*\bmeatballs?\b"), "frozen_entree"),
        # Chicken breast cutlet (fresh, not entree per se)
        (_r(r"\bchicken\s+breast\s+cutlets?\b|\blemon\s+garlic\s+pepper\s+chicken\b"), "fresh_prepared_entree"),
        # Game day wing bundle / chicken wings
        (_r(r"\bgame\s+day\s+wing\b|\bwing\s+bundle\b"), "fresh_prepared_entree"),
        # Meatballs by size/style (Wegmans Amore, Italian, turkey)
        (_r(r"\boven.baked\s+meatballs?\b|\bbeef\s+meatballs?\b|\bturkey\s+meatballs?\b|\bchicken\s+meatballs?\b|\bromano\s+cheese\b.*\bmeatballs?\b|\bitalian\s+style\s+meatballs?\b"), "fresh_prepared_entree"),
        # Shrimp scampi / scallops / seafood entrees
        (_r(r"\bshrimp\s+scampi\b|\bscallops?\b.*\bready\b|\bscallops?\b.*\bwrapped\b|\bbertolli\b|\bshrimp\s+&\s+linguine\b"), "fresh_prepared_entree"),
        # Egg bites (Wegmans cheese & mushroom)
        (_r(r"\begg\s+bites?\b|\bcheese\s*&?\s*mushroom\s+egg\b|\bpork\s+sausage\s*&?\s*cheese\s+egg\b"), "fresh_prepared_entree"),
        # Walking tamales / FILLO'S
        (_r(r"\bfillo.?s\b|\bwalking\s+tamales?\b|\bbean\s+salsa\s+verde\b"), "fresh_prepared_entree"),
        # Stuffed gnocchi / ravioloni / sacchetti / pasta entrees
        (_r(r"\bstuffed\s+gnocchi\b|\bravioloni\b|\bsacchetti\b|\bparmesan\s*&?\s*prosciutto\s+sacchetti\b"), "pasta_dish"),
        # Tyson frozen chicken tenderloins
        (_r(r"\btyson\b|\bsouthern\s+breast\s+tenderloins?\b|\ball\s+natural\b.*\btenderloins?\b"), "frozen_entree"),
        # Korean short ribs / beef short ribs
        (_r(r"\bkorean\s+style\s+beef\b|\bbeef\s+short\s+ribs?\b"), "fresh_prepared_entree"),
        # Avocado summer roll / shrimp noodle rolls
        (_r(r"\bsummer\s+roll\b|\bspring\s+roll\b|\bnoodle\s+rolls?\b|\bshrimp\s+noodle\s+rolls?\b"), "stir_fry"),
        # Deep Indian Kitchen paneer / frozen Indian
        (_r(r"\bdeep\s+indian\s+kitchen\b|\bspinach\s+paneer\b"), "fresh_prepared_entree"),
        # Kidfresh chicken nuggets & pasta
        (_r(r"\bkidfresh\b|\bchicken\s+nuggets?\b.*\bpasta\b"), "fresh_prepared_entree"),
        # Mini beef tacos / chicken cilantro wontons
        (_r(r"\bmini\s+beef\s+tacos?\b|\bchicken\s+cilantro\b.*\bwontons?\b|\bmini\s+wontons?\b"), "stir_fry"),
        # Savvy Snax snacker pack
        (_r(r"\bsavvy\s+snax\b|\bsnacker\s+pack\b"), "fresh_prepared_entree"),
        # Beef short ribs / Korean BBQ
        (_r(r"\bshort\s+ribs?\b"), "fresh_prepared_entree"),
        # Pastry wrapped mini hot dogs (pigs in blanket style)
        (_r(r"\bpastry\s+wrapped\b.*\bhot\s+dogs?\b|\bmini\s+uncured\b.*\bhot\s+dogs?\b"), "frozen_entree"),
        # Gabila's potato pancakes (latkes)
        (_r(r"\bgabila.?s\b|\bpotato\s+pancakes?\b"), "fresh_prepared_entree"),
        # Chana masala / madras lentils (Good & Gather Indian ready-to-eat)
        (_r(r"\bchana\s+masala\b|\bmadras\s+lentils?\b|\bvegetarian\s+chana\b|\bvegetarian\s+madras\b"), "fresh_prepared_entree"),
        # Italian tomato & burrata (filled pasta)
        (_r(r"\bburrata\s+ravioloni\b|\bburrata\b.*\bravioli\b|\bomato\b.*\bburrata\b"), "pasta_dish"),
        # Amy's frozen meals
        (_r(r"\bamy.?s\b.*\bbowls?\b|\bamy.?s\b.*\bfrozen\b|\bamy.?s\b.*\bmattar\s+paneer\b|\bamy.?s\b.*\bnoodles?\b"), "frozen_entree"),
        # Annie's pasta
        (_r(r"\bannies?\b.*\bpasta\b|\bberni[eo].?s?\b.*\bpasta\b|\ball\s+stars?\b.*\bpasta\b"), "pasta_dish"),
        # P.F. Chang's
        (_r(r"\bp\.?f\.?\s+chang.?s?\b|\bbeef\s+and\s+broccoli\b"), "frozen_entree"),
        # Lunchables / Lunchly
        (_r(r"\blunchables?\b|\blunchly\b"), "fresh_prepared_entree"),
        # Hot Pockets / Sandwich Bros
        (_r(r"\bhot\s+pockets?\b|\bsandwich\s+bros?\b"), "frozen_entree"),
        # El Monterey / Jose Ole / Old El Paso taquitos/tacos
        (_r(r"\bel\s+monterey\b|\bjose\s+ole?\b|\bold\s+el\s+paso\b"), "frozen_entree"),
        # Oats Overnight (pouches in meals_entrees)
        (_r(r"\boats\s+overnight\b.*\bshake\b|\boats\s+overnight\b.*\bpouch\b"), "fresh_prepared_entree"),
        # Good & Gather frozen entrees
        (_r(r"\bgood\s*&?\s*gather\b.*\bchicken\s+bites?\b|\bgood\s*&?\s*gather\b.*\blobster\s+mac\b|\bgood\s*&?\s*gather\b.*\bfajita\b|\bgood\s*&?\s*gather\b.*\blunch\s+kit\b"), "frozen_entree"),
        # Birds Eye pasta
        (_r(r"\bbirds?\s+eye\b.*\bpasta\b|\bbirds?\s+eye\b.*\balfredo\b"), "pasta_dish"),
        # Kevin's Natural Foods
        (_r(r"\bkevin.?s\s+natural\b|\blemongrass\s+chicken\b"), "frozen_entree"),
        # Lucky Foods spring rolls / veg spring rolls / bao buns
        (_r(r"\blucky\s+foods\b|\bveggie\s+spring\s+rolls?\b|\bvegetable\s+spring\s+rolls?\b|\bwegmans\b.*\bspring\s+rolls?\b|\bwegmans\b.*\beggrolls?\b|\bpork\s+eggrolls?\b"), "stir_fry"),
        (_r(r"\bbao\s+buns?\b|\bwow\s+bao\b|\bteriyaki.*\bbao\b|\bbbq\s+pork\b.*\bbao\b"), "stir_fry"),
        # Pad See Ew / Tteokbokki / Korean pancake
        (_r(r"\bpad\s+see\s+ew\b|\bpho\b.*\bkit\b|\bkorean\s+pancake\b|\bjayone\b.*\bpancake\b|\btteok\s*bok?\s*ki?\b"), "stir_fry"),
        # Farm Rich / mozzarella sticks
        (_r(r"\bfarm\s+rich\b|\bmozzarella\s+sticks?\b"), "frozen_entree"),
        # Jackfruit Company
        (_r(r"\bjackfruit\s+company\b|\bpulled\b.*\bjackfruit\b|\bbbq\b.*\bjackfruit\b"), "frozen_entree"),
        # Seafood entrees (sea cuisine)
        (_r(r"\bsea\s+cuisine\b|\bpotato\s+&\s+herb\s+cod\b"), "fresh_prepared_entree"),
        # Sous vide / turkey tenderloin
        (_r(r"\bsous\s+vide\b.*\bturkey\b|\bturkey\s+breast\s+tenderloins?\b.*\bsous\b"), "fresh_prepared_entree"),
        # Finger Food / chicken logs
        (_r(r"\bfinger\s+food\b.*\bchicken\b|\bchicken\s+logs?\b"), "frozen_entree"),
        # Boomerang's pastry
        (_r(r"\bboomerang.?s?\b"), "frozen_entree"),
        # Market pantry corn dogs
        (_r(r"\bcorn\s+dogs?\b|\bmini\s+corn\s+dogs?\b"), "frozen_entree"),
        # Protein pancakes / Jimmy Dean pancake combos
        (_r(r"\bprotein\s+pancakes?\b|\bjimmy\s+dean\b.*\bpancake\b"), "frozen_entree"),
        # Butter chicken / basmati
        (_r(r"\bbutter\s+chicken\b|\bbasmati\s+rice\b.*\bentr[eé]e\b"), "fresh_prepared_entree"),
        # Carne asada burritos / papas rellenas
        (_r(r"\bcarne\s+asada\s+burritos?\b|\bpapas?\s+rellenas?\b"), "fresh_prepared_entree"),
        # Chicken Shu Mai / shu mai
        (_r(r"\bshu\s+mai\b|\bdumplings?\b.*\bshu\b"), "stir_fry"),
        # Wegmans Gold Pan
        (_r(r"\bwegmans\b.*\bgold\s+pan\b.*\balfredo\b|\bwegmans\b.*\bpenne\s+alfredo\b"), "pasta_dish"),
        # Wegmans stuffed peppers / fajita / jambalaya / roasted turkey
        (_r(r"\bwegmans\b.*\bstuffed\s+peppers?\b|\bwegmans\b.*\bjambalaya\b"), "fresh_prepared_entree"),
        (_r(r"\bwegmans\b.*\broasted\s+turkey\b|\bwegmans\b.*\bturkey\s+breast\b|\bwegmans\b.*\bturkey\s+meal\b"), "fresh_prepared_entree"),
        (_r(r"\bwegmans\b.*\bfajita\b|\bwegmans\b.*\bcalamari\b|\bwegmans\b.*\bfalafel\b"), "fresh_prepared_entree"),
        # Wegmans mushroom & inari roll / sushi
        (_r(r"\bwegmans\b.*\binari\b|\bwegmans\b.*\bsushi\b|\bwegmans\b.*\broll\s*\("), "fresh_prepared_entree"),
        (_r(r"\bmai\b.*\bshrimp\s+tempura\b|\bshrimp\s+tempura\s+crunch\s+roll\b"), "fresh_prepared_entree"),
        # Akua kelp burgers
        (_r(r"\bkelp\s+burgers?\b|\bakua\b"), "fresh_prepared_entree"),
        # Rana protein pasta
        (_r(r"\brana\b.*\bprotein\b|\bpulled\s+pork\b.*\bpasta\b"), "pasta_dish"),
        # Banquet mega bowls
        (_r(r"\bbanquet\b|\bmega\s+bowls?\b"), "frozen_entree"),
        # Bibigo japchae noodles / frozen Korean
        (_r(r"\bbibigo\b|\bjapchae\b|\bkimchi\s+fried\s+rice\b"), "stir_fry"),
        # Chef Boyardee
        (_r(r"\bchef\s+boyardee\b|\bbeefaroni\b"), "frozen_entree"),
        # Foster Farms popcorn chicken
        (_r(r"\bfoster\s+farms?\b|\bpopcorn\s+chicken\b"), "frozen_entree"),
        # Golden Krust patties
        (_r(r"\bgolden\s+krust\b|\bjamaican\s+patty\b|\bpatty\b.*\bchicken\b.*\bpack\b"), "frozen_entree"),
        # Hillshire snacking small plates (misrouted)
        (_r(r"\bhillshire\b.*\bsnacking\b.*\bprotein\b|\bhillshire\b.*\bsmall\s+plates?\b|\bhillshire\b.*\bitalian\s+dry\b"), "other"),
        # JFC shumai / shrimp shumai
        (_r(r"\bjfc\b.*\bshumai\b|\bshrimp\s+shumai\b"), "stir_fry"),
        # Jimmy Dean breakfast items
        (_r(r"\bjimmy\s+dean\b"), "frozen_entree"),
        # MorningStar Farms plant based pancake sausage stick
        (_r(r"\bmorningstar\s+farms?\b.*\bpancake\b|\bplant\s+based\b.*\bpancake\b.*\bsausage\b"), "frozen_entree"),
        # P3 portable protein pack (misrouted)
        (_r(r"\bp3\s+portable\b|\bportable\s+protein\s+pack\b|\bportable\s+protein\s+snack\b"), "other"),
        # Spring Valley beef franks in pastry
        (_r(r"\bspring\s+valley\b.*\bbeef\s+franks?\b|\bwrapped.*\bpuff\s+pastry\b|\bcocktail\b.*\bfranks?\b"), "frozen_entree"),
        # StarKist lunch to-go
        (_r(r"\bstarkist\b.*\blunch.*go\b|\blunch.*go\b.*\btuna\b"), "other"),
        # Stryker Farm pulled pork
        (_r(r"\bstryker\s+farm\b|\bpulled\s+pork\b"), "fresh_prepared_entree"),
        # Taco Bell kits
        (_r(r"\btaco\s+bell\b"), "frozen_entree"),
        # Wegmans Gold Pan seafood / chicken / entrees
        (_r(r"\bwegmans\b.*\bgold\s+pan\b"), "fresh_prepared_entree"),
        (_r(r"\bwegmans\b.*\bbbq\s+pulled\s+pork\b|\bwegmans\b.*\bfully\s+cooked\b.*\bpork\b"), "fresh_prepared_entree"),
        (_r(r"\bwegmans\b.*\bperuvian\b.*\bchicken\b|\bwegmans\b.*\bfried\s+chicken\b|\bwegmans\b.*\bgeneral\s+tso\b"), "fresh_prepared_entree"),
        (_r(r"\bwegmans\b.*\bpopcorn\s+shrimp\b|\bwegmans\b.*\boshizushi\b|\bwegmans\b.*\bentertainment\s+collection\b"), "fresh_prepared_entree"),
        (_r(r"\bwegmans\b.*\bscallops?\b|\bwegmans\b.*\bcrab\s+cakes?\b|\bwegmans\b.*\bsalmon\b.*\bcakes?\b"), "fresh_prepared_entree"),
        # immi ramen packets
        (_r(r"\bimmi\b.*\bramen\b|\bblack\s+garlic\b.*\bramen\b|\bcreamy\b.*\bramen\b"), "ramen"),
        # Farm to People pantry gift bundle (misrouted)
        (_r(r"\bpantry\s+gift\s+bundle\b|\bgift\s+bundle\b"), "other"),
        # battered fish nuggets / fish cakes
        (_r(r"\bbattered\s+fish\b|\bfish\s+nuggets?\b"), "fresh_prepared_entree"),
        # Cheese & green chile tamales
        (_r(r"\bcheese\b.*\bgreen\s+chile\s+tamales?\b|\btamales?\b"), "fresh_prepared_entree"),
        # Pad Thai / Thai basil spring rolls
        (_r(r"\bthai\s+basil\s+spring\s+rolls?\b|\bgood.*gather.*thai.*spring\b"), "stir_fry"),
    ],
}

# LLM classification removed — all subfamilies now handled by regex.
_LLM_SUBFAMILIES: set[str] = set()


# ---------------------------------------------------------------------------
# Cache helpers (mirrors product_taxonomy.py pattern)
# ---------------------------------------------------------------------------

def _norm(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    if s == "nan" or s == "None":
        return ""
    return s


def _cache_key(name: str, ingredients_norm: str) -> str:
    key_str = "|".join([_MICRO_LABEL_VERSION, _norm(name), _norm(ingredients_norm)])
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    return _MICRO_CACHE_DIR / f"{key}.json"


def _load_cached(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if "micro_label" not in data:
            return None
        return data
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _save_cached(key: str, micro_label: str) -> None:
    _MICRO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(key), "w") as f:
        json.dump({"micro_label": micro_label}, f)


# ---------------------------------------------------------------------------
# Regex classifier
# ---------------------------------------------------------------------------

def _regex_classify(name: str, subfamily: str) -> str:
    """Return first regex match for this subfamily, or 'other' if no match."""
    rules = _REGEX_RULES.get(subfamily, [])
    for pattern, label in rules:
        if pattern.search(name):
            return label
    return "other"


# ---------------------------------------------------------------------------
# LLM classifier (batched, with cache)
# ---------------------------------------------------------------------------

def _build_llm_prompt(subfamily: str, products: list[dict]) -> str:
    """Build a user-turn message for a batch of products in one subfamily."""
    allowed = MICRO_LABELS.get(subfamily, ["other"])
    allowed_str = ", ".join(allowed)

    lines = [
        f"Subfamily: {subfamily}",
        f"Allowed micro-labels: {allowed_str}",
        "",
        "Products (one per line, tab-separated: INDEX<TAB>NAME<TAB>INGREDIENTS_FIRST_200):",
    ]
    for i, p in enumerate(products):
        name = _norm(p.get("name"))
        ingr = _norm(p.get("ingredients_norm"))[:200]
        lines.append(f"{i}\t{name}\t{ingr}")

    lines += [
        "",
        'Respond with a JSON array of objects, one per product, in the same order.',
        'Each object must have exactly one key: "micro_label".',
        'Choose from the allowed list only. Use "other" if unsure.',
        "Example: [{\"micro_label\": \"protein_bar\"}, {\"micro_label\": \"granola_bar\"}]",
    ]
    return "\n".join(lines)


def _call_llm_batch(subfamily: str, products: list[dict]) -> list[str]:
    """Call Claude Haiku for a batch of products. Returns one label per product."""
    allowed_set = set(MICRO_LABELS.get(subfamily, ["other"]))
    fallback = ["other"] * len(products)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback

    client = anthropic.Anthropic(api_key=api_key)

    system = (
        "You are a grocery product micro-label classifier. "
        "You will be given a batch of products from the same product subfamily. "
        "For each product, return exactly one micro-label from the allowed list. "
        "Respond ONLY with a valid JSON array — no markdown, no explanation."
    )
    user = _build_llm_prompt(subfamily, products)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": user}],
            system=system,
        )
        raw = response.content[0].text.strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or len(parsed) != len(products):
            return fallback
        results = []
        for item in parsed:
            label = item.get("micro_label", "other")
            results.append(label if label in allowed_set else "other")
        return results
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Core classification logic
# ---------------------------------------------------------------------------

def _classify_one_regex(name: str, subfamily: str) -> tuple[str, str]:
    """Try regex classification. Returns (label, method)."""
    if not subfamily or _norm(subfamily) == "":
        return "other", "fallback"
    if subfamily in _NON_FOOD_SUBFAMILIES:
        return "n/a", "fallback"
    if subfamily in _PASSTHROUGH_SUBFAMILIES:
        return subfamily.split(".")[-1], "fallback"

    label = _regex_classify(name, subfamily)
    if label != "other":
        return label, "regex"
    return "other", "fallback"


def classify_batch(
    rows: list[dict],
    use_llm: bool = True,
) -> list[tuple[str, str]]:
    """Classify a list of products into (micro_label, method) tuples.

    Args:
        rows: list of dicts, each with keys: name, taxonomy_subfamily, ingredients_norm
        use_llm: if True, unmatched products for LLM subfamilies will be looked
                 up in cache or sent to Claude Haiku. If False, regex only.

    Returns:
        list of (micro_label, method) tuples, same length as rows.
        method is one of: "regex", "llm", "fallback"
    """
    results: list[tuple[str, str]] = [("other", "fallback")] * len(rows)

    # Pass 1: regex for all rows
    for i, row in enumerate(rows):
        name = _norm(row.get("name"))
        subfamily = _norm(row.get("taxonomy_subfamily"))
        label, method = _classify_one_regex(name, subfamily)
        results[i] = (label, method)

    if not use_llm:
        return results

    # Pass 2: LLM for rows still at ("other", "fallback") in LLM subfamilies,
    # or for any subfamily that had no regex rules.
    # Group by subfamily to batch efficiently.
    pending: dict[str, list[int]] = {}  # subfamily → list of original row indices
    for i, row in enumerate(rows):
        label, method = results[i]
        if method == "regex":
            continue  # already classified by regex
        subfamily = _norm(row.get("taxonomy_subfamily"))
        if not subfamily or subfamily in _NON_FOOD_SUBFAMILIES or subfamily in _PASSTHROUGH_SUBFAMILIES:
            continue
        # Only send to LLM if this subfamily is in the LLM set
        if subfamily not in _LLM_SUBFAMILIES:
            continue

        # Check cache first
        name = _norm(row.get("name"))
        ingr = _norm(row.get("ingredients_norm"))
        key = _cache_key(name, ingr)
        cached = _load_cached(key)
        if cached:
            results[i] = (cached["micro_label"], "llm")
            continue

        # Queue for LLM call
        if subfamily not in pending:
            pending[subfamily] = []
        pending[subfamily].append(i)

    # Process LLM queue in batches per subfamily
    for subfamily, indices in pending.items():
        for batch_start in range(0, len(indices), _BATCH_SIZE):
            batch_indices = indices[batch_start : batch_start + _BATCH_SIZE]
            batch_rows = [rows[i] for i in batch_indices]
            labels = _call_llm_batch(subfamily, batch_rows)

            for i, label in zip(batch_indices, labels):
                results[i] = (label, "llm")
                # Cache the result
                name = _norm(rows[i].get("name"))
                ingr = _norm(rows[i].get("ingredients_norm"))
                _save_cached(_cache_key(name, ingr), label)

            if batch_start + _BATCH_SIZE < len(indices):
                time.sleep(_RATE_LIMIT_DELAY)

    return results
