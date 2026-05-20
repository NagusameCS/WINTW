"""Screenshot-driven solver for Flagle.

Pipeline
--------
1. Load screenshot (PNG/JPG).
2. Auto-detect the bounding box of the Flagle flag widget (or take a user-
   supplied bbox / pre-cropped image).
3. Resize to a high-res standardized grid (240×160) and quantize colors.
4. Classify each pixel as REVEALED vs HIDDEN by comparing distance to the
   opener's (Brunei's) color at that location: revealed pixels in Flagle
   are drawn at exactly the opener's color (because reveal happens where
   guess==solution), so they cluster tightly around the Brunei reference;
   hidden pixels are a uniform dark gray, far from any Brunei color.
5. Compare the observed mask against precomputed reveal masks
   `(Brunei == candidate)` for every candidate flag, ranking by Hamming
   distance. This tolerates screenshot noise (anti-aliasing, JPEG, etc.).

Assumptions
-----------
- The user always opens with the model's optimal opener (Brunei / "bn").
- Screenshot need not be perfectly cropped; auto-detect handles typical
  Flagle UI layouts. A `bbox` override is exposed for hard cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .flags import CACHE_DIR, FLAG_DIR, _all_country_codes

# -------- Hi-res config (only used by the screenshot solver) --------

HIRES_W, HIRES_H = 240, 160
HIRES_LEVELS = 8
HIRES_PIXELS = HIRES_W * HIRES_H

OPENER_CODE = "bn"  # entropy-optimal opener (see scripts/find_opener.py)

# Flagle's hidden-tile color is a dark neutral gray. We detect the widget
# region by looking for clusters of low-saturation, low-brightness pixels
# combined with the opener's distinctive colors.
HIDDEN_MAX_BRIGHTNESS = 120
HIDDEN_MAX_SATURATION = 35
HIDDEN_DEFAULT = np.array([58, 58, 64], dtype=np.int16)

# Bias toward the opener when a pixel is equidistant. Empirically helpful
# because anti-aliased edges between revealed/hidden pixels sit closer to
# the hidden gray than to the opener's vivid color.
OPENER_BIAS = 0.55

HIRES_CACHE = CACHE_DIR / "hires.npz"


# -------- Hi-res cache build --------

def _hires_pixels(code: str) -> np.ndarray:
    """Return (H, W, 3) uint8 quantized hi-res RGB for one flag."""
    p = FLAG_DIR / f"{code}.png"
    img = Image.open(p).convert("RGB").resize((HIRES_W, HIRES_H), Image.BILINEAR)
    a = np.asarray(img, dtype=np.uint8)
    step = 256 // HIRES_LEVELS
    return ((a // step) * step + step // 2).astype(np.uint8)


def build_hires_cache(force: bool = False) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Build / load the hi-res cache.

    Returns
    -------
    codes        : list[str]
    rgb_pixels   : (N, H, W, 3) uint8
    reveal_masks : (N, H, W) bool  — mask[i] = (opener == flag_i) per pixel
    """
    if HIRES_CACHE.exists() and not force:
        z = np.load(HIRES_CACHE, allow_pickle=True)
        return list(z["codes"]), z["rgb"], z["masks"]

    codes = [c for c in _all_country_codes() if (FLAG_DIR / f"{c}.png").exists()]
    rgb = np.stack([_hires_pixels(c) for c in codes], axis=0)  # (N, H, W, 3)
    opener_idx = codes.index(OPENER_CODE)
    opener = rgb[opener_idx]  # (H, W, 3)
    masks = np.all(rgb == opener[None, ...], axis=-1)  # (N, H, W) bool

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        HIRES_CACHE,
        codes=np.array(codes),
        rgb=rgb,
        masks=masks,
    )
    return codes, rgb, masks


# -------- Screenshot analysis --------

def _rgb_to_hsv_v_s(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (value, saturation) in [0, 255] from an (H, W, 3) uint8 array."""
    a = arr.astype(np.int16)
    mx = a.max(axis=-1)
    mn = a.min(axis=-1)
    v = mx
    s = np.where(mx == 0, 0, ((mx - mn) * 255) // np.maximum(mx, 1))
    return v.astype(np.int16), s.astype(np.int16)


def detect_flag_bbox(img: np.ndarray) -> tuple[int, int, int, int]:
    """Locate the flag widget in a Flagle screenshot.

    Strategy: find a rectangle dominated by (dark-gray hidden pixels)
    ∪ (vivid opener-color pixels). The Flagle widget's interior is
    almost entirely one of those two; the surrounding page is bright
    near-white. We take the bounding box of the largest such cluster.
    """
    H, W, _ = img.shape
    v, s = _rgb_to_hsv_v_s(img)
    is_hidden = (v < HIDDEN_MAX_BRIGHTNESS) & (s < HIDDEN_MAX_SATURATION)

    # Pixels close to *some* Brunei color (very saturated yellow/red, or pure
    # black/white) — generic "vivid pixel" test, robust across openers.
    is_vivid = (s > 100) | (v < 25) | ((v > 230) & (s < 20))

    interior = is_hidden | is_vivid

    # Row / column projection to find the dominant rectangle.
    row_score = interior.sum(axis=1)
    col_score = interior.sum(axis=0)

    # Threshold at 25% of the max projection — robust to UI clutter.
    r_thresh = max(1, int(row_score.max() * 0.25))
    c_thresh = max(1, int(col_score.max() * 0.25))
    rows = np.where(row_score > r_thresh)[0]
    cols = np.where(col_score > c_thresh)[0]
    if len(rows) == 0 or len(cols) == 0:
        return (0, 0, W, H)
    y0, y1 = int(rows[0]), int(rows[-1])
    x0, x1 = int(cols[0]), int(cols[-1])

    # Snap to 3:2 aspect ratio, centered on the detected box.
    bw = x1 - x0 + 1
    bh = y1 - y0 + 1
    target_ratio = HIRES_W / HIRES_H  # 3:2
    if bw / bh > target_ratio:
        new_h = int(round(bw / target_ratio))
        cy = (y0 + y1) // 2
        y0 = max(0, cy - new_h // 2)
        y1 = min(H - 1, y0 + new_h - 1)
    else:
        new_w = int(round(bh * target_ratio))
        cx = (x0 + x1) // 2
        x0 = max(0, cx - new_w // 2)
        x1 = min(W - 1, x0 + new_w - 1)
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def extract_mask(
    img: np.ndarray,
    opener_rgb: np.ndarray,
    bbox: tuple[int, int, int, int] | None = None,
    debug_dir: Path | None = None,
) -> np.ndarray:
    """Return (H, W) boolean mask of revealed pixels for the screenshot.

    Parameters
    ----------
    img         : (H, W, 3) uint8 — full screenshot or pre-cropped flag.
    opener_rgb  : (HIRES_H, HIRES_W, 3) uint8 — the opener (Brunei) reference.
    bbox        : optional (x, y, w, h) override.
    debug_dir   : optional dir to dump intermediate visuals.
    """
    if bbox is None:
        bbox = detect_flag_bbox(img)
    x, y, w, h = bbox
    crop = img[y : y + h, x : x + w]

    pil = Image.fromarray(crop).resize((HIRES_W, HIRES_H), Image.BILINEAR)
    arr = np.asarray(pil, dtype=np.int16)             # (H, W, 3)
    ref = opener_rgb.astype(np.int16)                  # (H, W, 3)

    # Estimate the hidden-tile color from the image itself: take the mode of
    # low-brightness, low-saturation pixels in the crop. Falls back to a
    # default if the crop has no such pixels (rare).
    v_c, s_c = _rgb_to_hsv_v_s(arr.astype(np.uint8))
    hidden_mask = (v_c < HIDDEN_MAX_BRIGHTNESS) & (s_c < HIDDEN_MAX_SATURATION)
    if hidden_mask.any():
        hidden_color = arr[hidden_mask].mean(axis=0).astype(np.int16)
    else:
        hidden_color = HIDDEN_DEFAULT.copy()

    # Relative classifier: pixel is REVEALED iff it is closer to the opener's
    # color at that location than to the estimated hidden-tile color.
    diff_op = arr - ref
    dist_op = np.sum(diff_op * diff_op, axis=-1).astype(np.float32)
    diff_hi = arr - hidden_color[None, None, :]
    dist_hi = np.sum(diff_hi * diff_hi, axis=-1).astype(np.float32)

    mask = dist_op * OPENER_BIAS < dist_hi

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(crop).save(debug_dir / "01_crop.png")
        Image.fromarray(np.asarray(pil)).save(debug_dir / "02_resized.png")
        Image.fromarray((mask * 255).astype(np.uint8)).save(debug_dir / "03_mask.png")
        # Side-by-side: observed crop next to opener reference
        side = np.concatenate([np.asarray(pil), opener_rgb], axis=1)
        Image.fromarray(side).save(debug_dir / "04_observed_vs_opener.png")

    return mask


# -------- Matching --------

@dataclass
class Candidate:
    code: str
    score: float        # fraction of pixels agreeing (1.0 = perfect)
    hamming: int        # raw # of disagreeing pixels
    unique: bool        # True if this candidate's reference mask is unique


def rank_candidates(
    observed_mask: np.ndarray,
    codes: list[str],
    reference_masks: np.ndarray,
) -> list[Candidate]:
    """Rank all candidates by Hamming distance between observed and reference."""
    obs = observed_mask.reshape(-1)
    refs = reference_masks.reshape(reference_masks.shape[0], -1)
    diffs = refs != obs[None, :]
    hamming = diffs.sum(axis=1)
    total = obs.size

    # Determine which reference masks are unique (for `unique` flag in output).
    packed = np.packbits(refs, axis=1)
    view = np.ascontiguousarray(packed).view(
        np.dtype((np.void, packed.shape[1]))
    ).ravel()
    unique_map: dict[bytes, int] = {}
    for row in view:
        unique_map[bytes(row)] = unique_map.get(bytes(row), 0) + 1
    is_unique = np.array(
        [unique_map[bytes(view[i])] == 1 for i in range(len(codes))], dtype=bool
    )

    order = np.argsort(hamming)
    return [
        Candidate(
            code=codes[i],
            score=1.0 - hamming[i] / total,
            hamming=int(hamming[i]),
            unique=bool(is_unique[i]),
        )
        for i in order
    ]


# -------- High-level entry point --------

def solve(
    screenshot_path: Path,
    bbox: tuple[int, int, int, int] | None = None,
    top_k: int = 5,
    debug_dir: Path | None = None,
) -> list[Candidate]:
    """Identify the hidden flag from a Flagle screenshot.

    The user is assumed to have played the optimal opener (Brunei).
    """
    codes, rgb, masks = build_hires_cache()
    opener_idx = codes.index(OPENER_CODE)
    opener_rgb = rgb[opener_idx]

    img = np.asarray(Image.open(screenshot_path).convert("RGB"), dtype=np.uint8)
    observed = extract_mask(img, opener_rgb, bbox=bbox, debug_dir=debug_dir)

    ranked = rank_candidates(observed, codes, masks)
    return ranked[:top_k]
