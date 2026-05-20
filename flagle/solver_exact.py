"""Exact-Flagle screenshot solver — single-guess lock-in.

Strategy
--------
1. Open with **sz** (Eswatini). Under Flagle's fuzzy match (colorThreshold=18,
   400×267 canvas), every one of the 197 possible solutions produces a UNIQUE
   reveal mask against sz, with a minimum pairwise Hamming distance of 124
   pixels. That margin survives any reasonable screenshot extraction noise.

2. Given a post-first-guess screenshot, extract which pixels were revealed
   (sampled as a boolean grid over the rendered sz flag), then nearest-neighbor
   lookup over the precomputed reveal-mask database. Return the unique answer.

Build the lookup database once with `build_database()`. Solve any screenshot
with `solve_from_mask(mask)`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from flagle.flagle_exact import (
    CANVAS_H, CANVAS_W, CACHE_DIR, build_cache, reveal_masks_against_all,
)

OPTIMAL_OPENER = "sz"
DB_FILE = CACHE_DIR / f"masks_{OPTIMAL_OPENER}.npz"


@dataclass
class SolveResult:
    code: str
    hamming: int
    margin: int          # gap to second-best (>=124 means we're safe)
    safe: bool


def build_database() -> tuple[list[str], np.ndarray]:
    """Precompute the (197, H*W) reveal-mask table for sz vs every solution."""
    codes, rgba = build_cache()
    idx = codes.index(OPTIMAL_OPENER)
    masks = reveal_masks_against_all(rgba[idx], rgba)         # (N, H, W)
    flat = masks.reshape(len(codes), -1)                      # (N, H*W) bool
    packed = np.packbits(flat, axis=1)                        # compact storage
    np.savez_compressed(DB_FILE, codes=np.array(codes), packed=packed)
    return codes, flat


_DB_CACHE: tuple[list[str], np.ndarray] | None = None


def load_database() -> tuple[list[str], np.ndarray]:
    global _DB_CACHE
    if _DB_CACHE is not None:
        return _DB_CACHE
    if not DB_FILE.exists():
        codes, flat = build_database()
    else:
        with open(DB_FILE, "rb") as f:                # avoid OneDrive races
            z = np.load(f, allow_pickle=True)
            codes = list(z["codes"])
            packed = z["packed"]
        flat = np.unpackbits(packed, axis=1)[:, : CANVAS_H * CANVAS_W].astype(bool)
    _DB_CACHE = (codes, flat)
    return _DB_CACHE


def solve_from_mask(observed: np.ndarray) -> SolveResult:
    """observed: (H, W) bool — pixels you believe Flagle revealed."""
    codes, flat = load_database()
    obs = observed.reshape(-1).astype(np.int32)
    db = flat.astype(np.int32)
    # Hamming = sum(obs ^ db) = |obs| + |db| - 2*(obs & db)
    inter = db @ obs
    sums_db = db.sum(axis=1)
    obs_sum = int(obs.sum())
    hamming = sums_db + obs_sum - 2 * inter
    order = np.argsort(hamming)
    best, second = int(order[0]), int(order[1])
    margin = int(hamming[second] - hamming[best])
    return SolveResult(
        code=codes[best],
        hamming=int(hamming[best]),
        margin=margin,
        safe=margin >= 60,           # half of the 124-pixel min margin
    )


def self_test() -> None:
    """Sanity check: every clean ground-truth mask resolves perfectly."""
    codes, flat = load_database()
    correct = 0
    min_margin = 10**9
    for i, c in enumerate(codes):
        res = solve_from_mask(flat[i].reshape(CANVAS_H, CANVAS_W))
        if res.code == c:
            correct += 1
            min_margin = min(min_margin, res.margin)
        else:
            print(f"  FAIL: {c} -> {res.code} (h={res.hamming}, margin={res.margin})")
    print(f"clean self-test: {correct}/{len(codes)}, min margin = {min_margin}")


def noise_test(flip_rate: float = 0.02, trials: int = 5) -> None:
    """Simulate screenshot noise by random bit-flips; measure accuracy.

    Vectorized: compute Hamming for the entire noisy batch at once.
    """
    rng = np.random.default_rng(0)
    codes, flat = load_database()
    N, P = flat.shape
    db_i = flat.astype(np.int32)
    db_sum = db_i.sum(axis=1)                                       # (N,)
    total = correct = 0
    for _ in range(trials):
        noise = rng.random((N, P)) < flip_rate
        noisy = (flat ^ noise).astype(np.int32)                     # (N, P)
        obs_sum = noisy.sum(axis=1)                                 # (N,)
        inter = noisy @ db_i.T                                      # (N, N)
        hamming = obs_sum[:, None] + db_sum[None, :] - 2 * inter
        preds = hamming.argmin(axis=1)
        total += N
        correct += int((preds == np.arange(N)).sum())
    print(f"noise test @ {flip_rate:.1%} bit-flip: {correct}/{total} = "
          f"{100 * correct / total:.2f}%")


if __name__ == "__main__":
    print(f"Building database for opener: {OPTIMAL_OPENER}")
    build_database()
    self_test()
    for r in (0.005, 0.01, 0.02, 0.05, 0.10):
        noise_test(r, trials=3)
