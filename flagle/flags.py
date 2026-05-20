"""Download, cache, and normalize flag images from flagcdn.com.

The remote source (https://flagcdn.com/) exposes per-country PNGs at
`https://flagcdn.com/w{width}/{code}.png` where `code` is an ISO 3166-1
alpha-2 lowercase code. We keep only sovereign-country codes (no US states,
no UK subdivisions, no supra-national flags) so the candidate set matches
what Flagle actually uses.

All flags are resized to a common (W, H) — Flagle states "scaled to the
same aspect ratio" — and stored as a uint32 array of packed RGB values,
one row per flag, one column per pixel. With that representation the
match mask between guess g and solution s is simply `flags[g] == flags[s]`.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import requests
from PIL import Image
from tqdm import tqdm

# -------- configuration --------

# Common Flagle render size. Aspect ratio 3:2 matches the majority of
# national flags; outliers (Nepal, Switzerland, Vatican) get squashed,
# which is exactly what Flagle does as well.
FLAG_W, FLAG_H = 60, 40  # 2400 pixels per flag — plenty for entropy work
PIXELS = FLAG_W * FLAG_H

# Color quantization: snap each channel to the top `LEVELS` values.
# This is what makes "pixel matches" robust across rendering pipelines,
# and roughly mirrors how Flagle compares post-scale pixels.
QUANT_LEVELS = 6  # 6^3 = 216 colors

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FLAG_DIR = DATA_DIR / "flags"
CACHE_DIR = DATA_DIR / "cache"
CODES_FILE = DATA_DIR / "codes.json"
ARRAY_FILE = CACHE_DIR / "flags.npz"

FLAGCDN_CODES_URL = "https://flagcdn.com/en/codes.json"
FLAGCDN_IMG_URL = "https://flagcdn.com/w320/{code}.png"

# Codes flagcdn lists that are NOT countries — drop them.
NON_COUNTRY_PREFIXES = ("us-", "gb-")
NON_COUNTRY_EXACT = {"eu", "un"}

# Codes that aren't real sovereign/inhabited countries Flagle actually uses.
# (Antarctica, Bouvet, Heard, etc.) — drop dependencies & uninhabited.
EXCLUDE_TERRITORIES = {
    "aq", "bv", "hm", "tf", "um", "io", "gs", "pn", "sh",  # uninhabited / territories
    "ax", "bl", "bq", "cw", "sx", "mf", "pm", "wf", "yt", "re", "gp", "mq", "gf",
    "nc", "pf", "tk", "nu", "ck", "fk", "ai", "ms", "vg", "vi", "tc", "ky", "bm",
    "as", "gu", "mp", "pr", "fo", "gi", "gg", "je", "im", "sj", "aw", "cx", "cc",
    "nf", "eh",
}


def _all_country_codes() -> list[str]:
    """Return the filtered list of ISO codes used as the candidate pool."""
    if CODES_FILE.exists():
        codes_map = json.loads(CODES_FILE.read_text(encoding="utf-8"))
    else:
        r = requests.get(FLAGCDN_CODES_URL, timeout=30)
        r.raise_for_status()
        codes_map = r.json()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CODES_FILE.write_text(json.dumps(codes_map, indent=2), encoding="utf-8")

    out: list[str] = []
    for code in codes_map:
        if code in NON_COUNTRY_EXACT:
            continue
        if any(code.startswith(p) for p in NON_COUNTRY_PREFIXES):
            continue
        if code in EXCLUDE_TERRITORIES:
            continue
        out.append(code)
    out.sort()
    return out


def download_all(force: bool = False) -> list[str]:
    """Download every needed flag PNG into data/flags/. Returns the code list."""
    FLAG_DIR.mkdir(parents=True, exist_ok=True)
    codes = _all_country_codes()
    for code in tqdm(codes, desc="flags"):
        out = FLAG_DIR / f"{code}.png"
        if out.exists() and not force:
            continue
        url = FLAGCDN_IMG_URL.format(code=code)
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            tqdm.write(f"  ! {code}: HTTP {r.status_code}")
            continue
        out.write_bytes(r.content)
    return codes


# -------- normalization --------

def _quantize(rgb: np.ndarray, levels: int = QUANT_LEVELS) -> np.ndarray:
    """Snap each channel to one of `levels` evenly-spaced values."""
    step = 256 // levels
    q = (rgb // step) * step + step // 2
    return q.astype(np.uint8)


def _load_one(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB").resize((FLAG_W, FLAG_H), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.uint8)            # (H, W, 3)
    arr = _quantize(arr)
    # Pack into uint32 so equality compares all three channels at once.
    packed = (
        arr[..., 0].astype(np.uint32) << 16
        | arr[..., 1].astype(np.uint32) << 8
        | arr[..., 2].astype(np.uint32)
    )
    return packed.reshape(-1)  # (PIXELS,)


def build_array(codes: Iterable[str] | None = None) -> tuple[list[str], np.ndarray]:
    """Build / cache the (N, PIXELS) uint32 array of all flags.

    Returns (codes, array).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if codes is None:
        codes = _all_country_codes()
    codes = list(codes)

    if ARRAY_FILE.exists():
        data = np.load(ARRAY_FILE, allow_pickle=True)
        if list(data["codes"]) == codes:
            return codes, data["flags"]

    rows = []
    keep_codes = []
    for code in tqdm(codes, desc="normalize"):
        p = FLAG_DIR / f"{code}.png"
        if not p.exists():
            continue
        rows.append(_load_one(p))
        keep_codes.append(code)
    flags = np.stack(rows, axis=0)  # (N, PIXELS) uint32
    np.savez_compressed(ARRAY_FILE, codes=np.array(keep_codes), flags=flags)
    return keep_codes, flags


def load() -> tuple[list[str], np.ndarray, dict[str, str]]:
    """Convenience loader: (codes, flags array, code -> country name)."""
    codes_map = json.loads(CODES_FILE.read_text(encoding="utf-8"))
    codes, flags = build_array()
    return codes, flags, codes_map
