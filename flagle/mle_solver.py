"""Maximum-likelihood Flagle screenshot solver.

Instead of extracting a binary reveal mask (which is ambiguous when the
solution's color matches the page background), we directly compare the
observed screenshot against the predicted screenshot under each of the
197 hypotheses, and pick the closest match.

Predicted screenshot under hypothesis k:
    revealed_mask = match(opener, candidate_k)        (precomputed)
    predicted_pixel = candidate_k_rgb  if revealed else bg

Loss = sum of squared per-pixel RGB error.

This handles every edge case correctly:
- bg = white  → white-on-white pixels are ambiguous for the *mask*, but
  the MLE solver uses the surrounding non-ambiguous pixels to disambiguate.
- JPEG / scaling noise → squared-error loss is naturally robust.
- Any background color (dark, light, paper) works without re-tuning.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from flagle.flagle_exact import (
    CANVAS_H, CANVAS_W, _load_rgba, build_cache, reveal_masks_against_all,
)
from flagle.solver_exact import OPTIMAL_OPENER

_BASE_CACHE: tuple[list[str], np.ndarray, np.ndarray] | None = None  # (codes, sol_rgb int16, masks bool)
_PRED_CACHE: dict[tuple[int, int, int], np.ndarray] = {}


def _base() -> tuple[list[str], np.ndarray, np.ndarray]:
    """Load once: opener reveal masks + solution RGBs."""
    global _BASE_CACHE
    if _BASE_CACHE is not None:
        return _BASE_CACHE
    codes, rgba = build_cache()
    opener_idx = codes.index(OPTIMAL_OPENER)
    masks = reveal_masks_against_all(rgba[opener_idx], rgba)        # (N, H, W) bool
    sol_rgb = rgba[..., :3].astype(np.int16)                        # (N, H, W, 3) int16
    _BASE_CACHE = (codes, sol_rgb, masks)
    return _BASE_CACHE


def _build_predictions(bg: tuple[int, int, int]) -> tuple[list[str], np.ndarray]:
    """Materialize the (N, H, W, 3) predicted-screenshot tensor for given bg."""
    bg_key = tuple(int(x) for x in bg)
    codes, sol_rgb, masks = _base()
    if bg_key in _PRED_CACHE:
        return codes, _PRED_CACHE[bg_key]
    bg_arr = np.array(bg_key, dtype=np.int16)                       # (3,)
    # vectorized over N: where mask → sol pixel else bg
    preds = np.where(masks[..., None], sol_rgb, bg_arr)             # (N, H, W, 3)
    _PRED_CACHE[bg_key] = preds
    return codes, preds


def _detect_bg(rgb: np.ndarray) -> tuple[int, int, int]:
    """Mode color via coarse quantization. Robust to lossy compression."""
    coarse = ((rgb.astype(np.int32) // 8) * 8 + 4).reshape(-1, 3)
    keys = coarse[:, 0] * 65536 + coarse[:, 1] * 256 + coarse[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    k = int(vals[counts.argmax()])
    return (k // 65536, (k // 256) % 256, k % 256)


def solve_screenshot(image_path: str | Path) -> tuple[str, float, float]:
    """Returns (code, best_loss, margin_to_runner_up)."""
    img = Image.open(image_path).convert("RGB").resize(
        (CANVAS_W, CANVAS_H), Image.BILINEAR
    )
    rgb = np.asarray(img, dtype=np.int16)
    bg = _detect_bg(rgb)
    codes, preds = _build_predictions(bg)
    diff = preds - rgb[None]                                        # (N, H, W, 3)
    loss = (diff.astype(np.int32) ** 2).sum(axis=(1, 2, 3))         # (N,)
    order = np.argsort(loss)
    best, second = int(order[0]), int(order[1])
    return codes[best], float(loss[best]), float(loss[second] - loss[best])


# ----------------------------- tests ---------------------------------------

def synthesize(solution_code: str, bg=(18, 18, 18)) -> Image.Image:
    sol = _load_rgba(solution_code)
    opener = _load_rgba(OPTIMAL_OPENER)
    from flagle.flagle_exact import reveal_mask
    m = reveal_mask(opener, sol)
    out = np.full((CANVAS_H, CANVAS_W, 3), bg, dtype=np.uint8)
    out[m] = sol[m, :3]
    return Image.fromarray(out, "RGB")


def run_suite(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    codes, _ = build_cache()

    def trial(name: str, render):
        correct = total = 0
        misses = []
        for c in codes:
            path = render(c)
            pred, loss, margin = solve_screenshot(path)
            total += 1
            if pred == c:
                correct += 1
            else:
                misses.append((c, pred, margin))
        print(f"  {name:<28} {correct}/{total}  "
              f"({100 * correct / total:5.2f}%)")
        for m in misses[:5]:
            print(f"     miss: true={m[0]:<3} pred={m[1]:<3} margin={m[2]:.0f}")

    print("MLE solver — end-to-end accuracy")

    for label, bg in [
        ("clean dark (18,18,18)",   (18, 18, 18)),
        ("clean light (255,255,255)", (255, 255, 255)),
        ("clean mid (128,128,128)",  (128, 128, 128)),
        ("clean paper (245,245,245)", (245, 245, 245)),
    ]:
        def make(c, _bg=bg, _label=label):
            p = tmp / f"{c}_{_label.split()[0]}.png"
            synthesize(c, _bg).save(p)
            return p
        trial(label, make)

    def make_jpeg(c, q=70):
        p = tmp / f"{c}_q{q}.jpg"
        synthesize(c).save(p, quality=q)
        return p
    trial("JPEG q=70", lambda c: make_jpeg(c, 70))
    trial("JPEG q=40", lambda c: make_jpeg(c, 40))

    def make_resize(c, scale=2.7):
        p = tmp / f"{c}_x{scale}.png"
        synthesize(c).resize(
            (int(CANVAS_W * scale), int(CANVAS_H * scale)), Image.LANCZOS
        ).save(p)
        return p
    trial("Lanczos 2.7x then back",  lambda c: make_resize(c, 2.7))
    trial("Lanczos 0.7x then back",  lambda c: make_resize(c, 0.7))


if __name__ == "__main__":
    run_suite(Path("data/cache/screenshots"))
