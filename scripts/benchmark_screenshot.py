"""Synthesize realistic Flagle screenshots and benchmark the screenshot solver.

For each candidate solution flag:
  1. Compute the true reveal mask m = (Brunei == solution) at hi-res.
  2. Render a fake Flagle widget: hidden tiles use a dark gray; revealed
     pixels are drawn at Brunei's color (since reveal==match).
  3. Embed the widget inside a larger page-like canvas with margins,
     random padding, and JPEG-style additive noise to simulate an
     imperfect screenshot.
  4. Run the screenshot solver and check if it recovers the true code.

Reports top-1 accuracy, top-3 accuracy, and the list of failures.
"""
from __future__ import annotations

import io
import random
from collections import Counter

import numpy as np
from PIL import Image
from tqdm import tqdm

from flagle.flags import load
from flagle.vision import (
    HIRES_H,
    HIRES_W,
    OPENER_CODE,
    build_hires_cache,
    extract_mask,
    rank_candidates,
)

HIDDEN_COLOR = np.array([58, 58, 64], dtype=np.uint8)


def _make_fake_screenshot(reveal_mask: np.ndarray, opener_rgb: np.ndarray,
                          *, scale: int, pad: int, noise: int, seed: int) -> np.ndarray:
    """Build a (H, W, 3) uint8 fake screenshot containing the widget."""
    rng = np.random.default_rng(seed)
    h, w, _ = opener_rgb.shape
    widget = np.where(reveal_mask[..., None], opener_rgb, HIDDEN_COLOR[None, None, :])
    widget = np.asarray(
        Image.fromarray(widget.astype(np.uint8)).resize(
            (w * scale, h * scale), Image.BILINEAR
        ),
        dtype=np.int16,
    )

    # Page chrome: light background with the widget centered + random padding.
    pad_t = pad + rng.integers(0, pad + 1)
    pad_l = pad + rng.integers(0, pad + 1)
    pad_b = pad + rng.integers(0, pad + 1)
    pad_r = pad + rng.integers(0, pad + 1)
    Wh = widget.shape[0] + pad_t + pad_b
    Ww = widget.shape[1] + pad_l + pad_r
    canvas = np.full((Wh, Ww, 3), 245, dtype=np.int16)
    canvas[pad_t : pad_t + widget.shape[0], pad_l : pad_l + widget.shape[1]] = widget

    # Additive noise to mimic JPEG / display compression.
    if noise > 0:
        canvas += rng.integers(-noise, noise + 1, size=canvas.shape, dtype=np.int16)
    canvas = np.clip(canvas, 0, 255).astype(np.uint8)
    return canvas


def main() -> None:
    codes, rgb, masks = build_hires_cache()
    _, _, names = load()
    opener_rgb = rgb[codes.index(OPENER_CODE)]
    N = len(codes)

    top1 = 0
    top3 = 0
    failures: list[tuple[str, list[str]]] = []
    rng = random.Random(0)

    for i in tqdm(range(N), desc="solve"):
        true_code = codes[i]
        screenshot = _make_fake_screenshot(
            masks[i], opener_rgb,
            scale=rng.choice([2, 3, 4]),
            pad=rng.choice([20, 40, 60, 80]),
            noise=rng.choice([0, 4, 8, 12]),
            seed=i,
        )
        observed = extract_mask(screenshot, opener_rgb)
        ranked = rank_candidates(observed, codes, masks)

        guess_codes = [c.code for c in ranked]
        if guess_codes[0] == true_code:
            top1 += 1
        if true_code in guess_codes[:3]:
            top3 += 1
        else:
            failures.append((true_code, guess_codes[:5]))

    print()
    print(f"top-1 accuracy: {top1}/{N} ({100*top1/N:5.2f}%)")
    print(f"top-3 accuracy: {top3}/{N} ({100*top3/N:5.2f}%)")
    if failures:
        print(f"\nfailures ({len(failures)}):")
        for true, guesses in failures[:25]:
            print(f"  {true}  ->  {guesses}")


if __name__ == "__main__":
    main()
