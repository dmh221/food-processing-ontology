#!/usr/bin/env python3
"""Score grocery products on the Food Integrity Scale (0-150).

Usage:
    python run_scoring.py                     # score all stores
    python run_scoring.py --stores wegmans    # score specific stores
    python run_scoring.py --verbose           # show per-product details
    python run_scoring.py --check-anchors     # run anchor validation

Input:  Place scraped JSON files in data/scraped/ (one per store).
Output: Scored parquet + CSV in data/scored/.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scoring.scorer import score_all, print_summary, SCORE_VERSION


ROOT = Path(__file__).resolve().parent
SCRAPED_DIR = ROOT / "data" / "scraped"
SCORED_DIR = ROOT / "data" / "scored"

# Default store files — add your own scraped JSON here
STORE_FILES = {
    # "trader_joes": SCRAPED_DIR / "traderjoes_products.json",
    # "wegmans": SCRAPED_DIR / "wegmans_products.json",
    # "target": SCRAPED_DIR / "target_products.json",
}

ANCHORS_FILE = Path(__file__).parent / "scoring" / "anchors.csv"
OUTPUT_PARQUET = SCORED_DIR / "scored_products.parquet"
OUTPUT_CSV = SCORED_DIR / "scored_products.csv"


def check_anchors(df):
    """Validate scored products against anchor expectations."""
    if not ANCHORS_FILE.exists():
        print("No anchors.csv found, skipping anchor checks.")
        return

    print(f"\n--- Anchor validation ---")
    with open(ANCHORS_FILE) as f:
        reader = csv.DictReader(f)
        anchors = list(reader)

    p_order = {
        "W": 0, "Wp": 0, "C0": 1, "C1": 2,
        "P1a": 3, "P1b": 4, "P2a": 5, "P2b": 6, "P3": 7, "P4": 8,
    }
    passed = 0
    failed = 0

    for anchor in anchors:
        pattern = anchor["product_name_pattern"].strip().lower()
        expected_min = anchor["expected_class_min"].strip()
        expected_max = anchor["expected_class_max"].strip()
        notes = anchor.get("notes", "").strip()

        # Find matching products
        mask = df["name"].str.lower().str.contains(pattern, na=False)
        matches = df[mask]

        if len(matches) == 0:
            print(f"  ? No products match '{pattern}' — skipped")
            continue

        # Check each match
        for _, row in matches.head(3).iterrows():
            actual = row.get("processing_class", "unknown")
            if actual == "unknown":
                print(f"  ? {row['name'][:50]} — unknown (missing ingredients)")
                continue

            actual_num = p_order.get(actual, -1)
            min_num = p_order.get(expected_min, -1)
            max_num = p_order.get(expected_max, -1)

            if min_num <= actual_num <= max_num:
                print(f"  PASS  {actual}  {row['name'][:50]}  (expected {expected_min}-{expected_max})")
                passed += 1
            else:
                print(
                    f"  FAIL  {actual}  {row['name'][:50]}  "
                    f"(expected {expected_min}-{expected_max}, "
                    f"composite={row.get('composite', '?')}, "
                    f"MDS={row.get('mds', '?')} AFS={row.get('afs', '?')} "
                    f"HES={row.get('hes', '?')} MLS={row.get('mls', '?')})"
                )
                failed += 1

    print(f"\n  Anchors: {passed} passed, {failed} failed")


def check_taxonomy_fallbacks(df, use_llm: bool) -> None:
    """Warn loudly if any products received the fallback taxonomy label.

    The fallback (pantry.pasta_noodles) has a hardcoded 'C' processing floor.
    Products that should be W/Wp (produce, meat, plain water) get mis-scored:
      - Single-ingredient whole foods → C0 instead of W
      - No-ingredient whole foods → processing_class='unknown', composite=NaN
        (excluded from all analysis)
      - Beverages → product_type='food' instead of 'beverage'

    Suppressed when use_llm=False because fallbacks are intentional in that mode.
    """
    if not use_llm:
        return

    fallbacks = df[df["taxonomy_source"] == "fallback"]
    if fallbacks.empty:
        return

    n = len(fallbacks)
    print(f"\n{'!' * 65}")
    print(f"  TAXONOMY FALLBACK WARNING: {n:,} product(s) received the fallback")
    print(f"  taxonomy label (pantry.pasta_noodles) due to LLM classification")
    print(f"  failure. These products are silently mis-scored:")
    print(f"    - Whole foods (produce/meat/plain water): C0 or 'unknown'")
    print(f"      instead of W — may be EXCLUDED from analysis if no ingredients")
    print(f"    - Beverages: product_type='food' instead of 'beverage'")
    print(f"  Fix: re-run after resolving the API/classification failure, or")
    print(f"  inspect with: df[df['taxonomy_source'] == 'fallback']")
    print(f"{'!' * 65}")

    preview = fallbacks[["store", "name", "processing_class", "taxonomy_label"]].head(20)
    print(f"\n  Affected products (first {min(n, 20)} of {n:,}):")
    for _, row in preview.iterrows():
        print(
            f"    [{row.get('processing_class', '?'):>7}]  "
            f"{row.get('store', '?')}: {str(row.get('name', ''))[:50]}"
        )
    if n > 20:
        print(f"    ... and {n - 20:,} more")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Score grocery products on the Food Integrity Scale (0-150)."
    )
    parser.add_argument(
        "--stores",
        nargs="+",
        default=None,
        help=f"Store names to score. Options: {list(STORE_FILES.keys())}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-product scoring details for first 20 products.",
    )
    parser.add_argument(
        "--check-anchors",
        action="store_true",
        default=True,
        help="Run anchor validation (default: on).",
    )
    parser.add_argument(
        "--no-anchors",
        action="store_true",
        help="Skip anchor validation.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM taxonomy classification (all products get fallback labels).",
    )
    args = parser.parse_args()

    # Filter stores if specified
    if args.stores:
        files = {k: v for k, v in STORE_FILES.items() if k in args.stores}
        if not files:
            print(f"No matching stores. Options: {list(STORE_FILES.keys())}")
            sys.exit(1)
    else:
        files = STORE_FILES

    if not files:
        print("No store files configured. Add scraped JSON files to data/scraped/")
        print("and uncomment entries in STORE_FILES in run_scoring.py.")
        sys.exit(1)

    # Run scoring
    df = score_all(files, use_llm=not args.no_llm)

    # Check for taxonomy fallbacks before anything else
    check_taxonomy_fallbacks(df, use_llm=not args.no_llm)

    # Print summary
    print_summary(df)

    # Verbose output
    if args.verbose:
        print(f"\n--- First 20 scored products ---")
        for _, row in df.head(20).iterrows():
            tax_label = row.get("taxonomy_label", "?")
            print(f"  {row.get('processing_class', '?')}/{row.get('metabolic_class', '?')} "
                  f"[{row.get('product_type', '?')}] [{tax_label}] "
                  f"composite={row.get('composite', '?')} | "
                  f"{row.get('store', '?')}: {str(row.get('name', ''))[:45]}")

    # Anchor checks
    if args.check_anchors and not args.no_anchors:
        check_anchors(df)

    # Save output
    SCORED_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving results...")

    # For parquet: convert list columns to strings (parquet doesn't love nested lists)
    df_out = df.copy()
    list_cols = [
        "mds_bucket_2", "mds_bucket_3",
        "afs_tier_a", "afs_tier_b", "afs_tier_c",
        "hes_patterns", "mls_flags", "mls_offsets",
    ]
    for col in list_cols:
        if col in df_out.columns:
            df_out[col] = df_out[col].apply(
                lambda x: json.dumps(x) if isinstance(x, list) else str(x)
            )

    # Handle nutrition dict column for parquet
    if "nutrition" in df_out.columns:
        df_out["nutrition"] = df_out["nutrition"].apply(
            lambda x: json.dumps(x) if isinstance(x, dict) else str(x) if x else ""
        )

    df_out.to_parquet(OUTPUT_PARQUET, index=False)
    df_out.to_csv(OUTPUT_CSV, index=False)
    print(f"  Parquet: {OUTPUT_PARQUET}")
    print(f"  CSV:     {OUTPUT_CSV}")
    print(f"  Version: {SCORE_VERSION}")
    print(f"\nDone! {len(df):,} products scored.")


if __name__ == "__main__":
    main()
