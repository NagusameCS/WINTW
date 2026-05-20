"""Exact Flagle game-engine reimplementation.

Reverse-engineered from the production JS bundle (main.b392ca6f.js).

Constants
---------
- Canvas size: 400 × 267 (106,800 pixels). Nepal uses 33,612 due to alpha.
- Color distance is computed as
      d(p, q) = sqrt((dr)^2 + (dg)^2 + (db)^2) / sqrt(255^2 + 255^2 + 255^2) * 100
  i.e. a normalized [0, 100] scale.
- A pixel matches when d < colorThreshold (18) AND both alphas > 0.5.

This file replaces the toy quantized model with the *actual* matching rule
Flagle uses, so opener / collision / uniqueness numbers from here reflect
what the live game produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

# --- canonical Flagle constants ---
CANVAS_W, CANVAS_H = 400, 267
COLOR_THRESHOLD = 18.0                              # Flagle's `colorThreshold`
_MAX_DIST_SQ = 3 * 255 * 255                        # sqrt(195075)
THRESHOLD_DIST_SQ = (COLOR_THRESHOLD / 100.0) ** 2 * _MAX_DIST_SQ
ALPHA_HI = 127                                      # > 0.5 in [0, 255]

# --- paths ---
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FLAG_DIR = DATA_DIR / "flags"
CACHE_DIR = DATA_DIR / "cache"
FLAGLE_CODES_FILE = DATA_DIR / "flagle_codes.json"
EXACT_CACHE = CACHE_DIR / "flagle_exact.npz"


def flagle_codes() -> list[str]:
    """The actual 197-country list Flagle ships."""
    return json.loads(FLAGLE_CODES_FILE.read_text(encoding="utf-8"))


def _load_rgba(code: str) -> np.ndarray:
    img = Image.open(FLAG_DIR / f"{code}.png").convert("RGBA").resize(
        (CANVAS_W, CANVAS_H), Image.BILINEAR
    )
    return np.asarray(img, dtype=np.uint8)  # (H, W, 4)


def build_cache(force: bool = False) -> tuple[list[str], np.ndarray]:
    """Returns (codes, rgba) where rgba is (N, H, W, 4) uint8."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    codes = [c for c in flagle_codes() if (FLAG_DIR / f"{c}.png").exists()]
    if EXACT_CACHE.exists() and not force:
        z = np.load(EXACT_CACHE, allow_pickle=True)
        cached = list(z["codes"])
        if cached == codes:
            return codes, z["rgba"]
    rgba = np.stack([_load_rgba(c) for c in codes], axis=0)
    np.savez_compressed(EXACT_CACHE, codes=np.array(codes), rgba=rgba)
    return codes, rgba


# -------- reveal mask --------

def reveal_mask(guess_rgba: np.ndarray, sol_rgba: np.ndarray) -> np.ndarray:
    """Per-pixel boolean mask of Flagle reveals for one (guess, solution)."""
    g = guess_rgba[..., :3].astype(np.int32)
    s = sol_rgba[..., :3].astype(np.int32)
    d = g - s
    dist_sq = (d * d).sum(axis=-1)
    color_ok = dist_sq < THRESHOLD_DIST_SQ
    alpha_ok = (guess_rgba[..., 3] > ALPHA_HI) & (sol_rgba[..., 3] > ALPHA_HI)
    return color_ok & alpha_ok


def reveal_masks_against_all(
    guess_rgba: np.ndarray, all_rgba: np.ndarray
) -> np.ndarray:
    """Vectorized: (N, H, W) bool — reveal pattern if each flag is the solution.

    Uses chunking to keep peak memory bounded.
    """
    N = all_rgba.shape[0]
    out = np.empty((N, CANVAS_H, CANVAS_W), dtype=bool)
    g_rgb = guess_rgba[..., :3].astype(np.int32)
    g_a = guess_rgba[..., 3] > ALPHA_HI
    CHUNK = 32
    for i in range(0, N, CHUNK):
        chunk = all_rgba[i : i + CHUNK]
        s_rgb = chunk[..., :3].astype(np.int32)
        d = g_rgb[None] - s_rgb
        dist_sq = (d * d).sum(axis=-1)
        color_ok = dist_sq < THRESHOLD_DIST_SQ
        alpha_ok = g_a[None] & (chunk[..., 3] > ALPHA_HI)
        out[i : i + CHUNK] = color_ok & alpha_ok
    return out


def overlap_percentage(guess_rgba: np.ndarray, sol_rgba: np.ndarray) -> float:
    """Flagle's displayed % overlap (n/106800 * 100, or n/33612 for Nepal)."""
    m = reveal_mask(guess_rgba, sol_rgba)
    n = int(m.sum())
    denom = int((sol_rgba[..., 3] > ALPHA_HI).sum())  # non-transparent solution px
    if denom == 0:
        return 0.0
    return 100.0 * n / denom
