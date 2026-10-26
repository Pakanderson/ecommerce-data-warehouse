#!/usr/bin/env python3
"""
scripts/fetch_data.py — downloads the raw Olist CSVs into data/raw/.

The raw dataset (~62MB across 8 files) isn't committed to this repo —
committing large raw data files to git is generally avoided (it bloats
the repo permanently, even after the files are later removed). This
script is the standard alternative: a small, reproducible step that
fetches the data on demand.

The original dataset lives on Kaggle and normally needs a Kaggle account
+ API token to download programmatically:
    https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

To avoid requiring Kaggle credentials just to run this portfolio project,
this script instead clones a public GitHub mirror of the same files. If
you'd rather use the official Kaggle CLI, that works too — just download
the 8 CSVs into data/raw/ yourself and skip this script.

Usage:
    python scripts/fetch_data.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MIRROR_REPO = "https://github.com/spdrio/Brazilian-E-Commerce-Public-Dataset-by-Olist.git"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

EXPECTED_FILES = [
    "olist_customers_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
]


def already_present() -> bool:
    return all((RAW_DIR / f).exists() for f in EXPECTED_FILES)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if already_present():
        print(f"All {len(EXPECTED_FILES)} raw files already present in {RAW_DIR} — nothing to do.")
        return

    print(f"Cloning {MIRROR_REPO} ...")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", MIRROR_REPO, tmp],
                check=True, capture_output=True, text=True,
            )
        except FileNotFoundError:
            sys.exit("git is not installed — install git, or manually download the "
                      "8 CSVs from the Kaggle page linked in this script's docstring "
                      "into data/raw/.")
        except subprocess.CalledProcessError as e:
            sys.exit(f"git clone failed:\n{e.stderr}")

        source_dir = Path(tmp) / "files"
        for filename in EXPECTED_FILES:
            src = source_dir / filename
            if not src.exists():
                sys.exit(f"Expected file not found in mirror: {filename}. "
                          f"The mirror repo layout may have changed — see this "
                          f"script's docstring for the official Kaggle source.")
            shutil.copy(src, RAW_DIR / filename)
            print(f"  {filename}")

    print(f"\nDone. {len(EXPECTED_FILES)} files written to {RAW_DIR}")
    print("Next: python run_pipeline.py")


if __name__ == "__main__":
    main()
