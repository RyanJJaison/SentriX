"""Download the original Elliptic Bitcoin CSVs from Kaggle into data/raw/.

The PyG loader can fetch its own preprocessed copy of this dataset, but that
copy has already dropped the original ``txId`` values. Pulling the Kaggle
release keeps the real transaction identifiers, which is what makes the scores
traceable back to actual transactions.

Requires Kaggle API credentials. See the README for setup.

Run with::

    python scripts/fetch_kaggle.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DATA_RAW, KAGGLE_DATASET, RAW_FILES  # noqa: E402

CREDENTIALS_HELP = """\
Kaggle API credentials not found or invalid.

To set them up:
  1. Sign in at https://www.kaggle.com and open Settings -> API.
  2. Click "Create New Token" to download kaggle.json.
  3. Install it:
       mkdir -p ~/.kaggle
       mv ~/Downloads/kaggle.json ~/.kaggle/kaggle.json
       chmod 600 ~/.kaggle/kaggle.json

Alternatively, point KAGGLE_CONFIG_DIR at the directory holding kaggle.json,
or export KAGGLE_USERNAME and KAGGLE_KEY.

You must also accept the dataset's terms once, on its Kaggle page:
  https://www.kaggle.com/datasets/ellipticco/elliptic-data-set
"""


def authenticate():
    """Authenticate against the Kaggle API and return the API client.

    The ``kaggle`` package authenticates at import time and raises on a missing
    credentials file, so the import is deliberately kept inside this function.
    That way the failure surfaces as the actionable message below rather than as
    a traceback from a module-level import.
    """
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi

        api = KaggleApi()
        api.authenticate()
    except Exception as exc:  # noqa: BLE001 - any failure here means "no usable creds"
        raise SystemExit(f"{CREDENTIALS_HELP}\nUnderlying error: {exc}") from exc
    return api


def flatten_into(raw_dir: Path) -> None:
    """Move the expected CSVs up to ``raw_dir`` if the archive nested them.

    The Kaggle archive has shipped the CSVs inside an
    ``elliptic_bitcoin_dataset/`` folder at times. PyG expects them directly in
    ``data/raw/``, so anything found one level down is relocated.
    """
    for name in RAW_FILES:
        target = raw_dir / name
        if target.is_file():
            continue
        for candidate in raw_dir.rglob(name):
            if candidate == target:
                continue
            print(f"Moving {candidate.relative_to(raw_dir)} -> {name}")
            shutil.move(str(candidate), str(target))
            break

    # Clean up any now-empty directories left behind by the archive layout.
    for child in sorted(raw_dir.rglob("*"), reverse=True):
        if child.is_dir() and not any(child.iterdir()):
            child.rmdir()


def report(raw_dir: Path) -> int:
    """Verify the three expected files exist and print their row counts."""
    missing = [name for name in RAW_FILES if not (raw_dir / name).is_file()]
    if missing:
        print(f"ERROR: expected files still missing from {raw_dir}: {', '.join(missing)}")
        return 1

    print(f"\nFiles in {raw_dir}:")
    for name in RAW_FILES:
        path = raw_dir / name
        with path.open("rb") as handle:
            n_lines = sum(1 for _ in handle)
        size_mb = path.stat().st_size / 1e6
        print(f"  {name:<32} {n_lines:>9,} lines  {size_mb:>8.1f} MB")

    print("\nNext step:  python -m src.ppr")
    return 0


def main() -> int:
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    api = authenticate()
    print(f"Downloading {KAGGLE_DATASET} into {DATA_RAW} ...")
    api.dataset_download_files(KAGGLE_DATASET, path=str(DATA_RAW), unzip=True, quiet=False)

    flatten_into(DATA_RAW)
    return report(DATA_RAW)


if __name__ == "__main__":
    sys.exit(main())
