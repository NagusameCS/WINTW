"""Exhaustive opener audit across multiple metrics and resolutions.

For each candidate opener g, against the full candidate set under several
(resolution, quantization) configurations, compute:

  * expected_entropy   = sum_b (|b|/K) * log2(|b|)   — what find_opener uses
  * worst_case         = max bucket size after the guess
  * num_unique         = # of candidates that land alone in a singleton bucket
  * mean_bucket        = average bucket size weighted by membership

Lower is better for entropy / worst_case / mean_bucket; higher is better for
num_unique. We print the top-10 by each metric for each config so you can
see whether the entropy-optimal opener coincides with the
identification-optimal opener.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
from PIL import Image
from tqdm import tqdm

from flagle.flags import FLAG_DIR, _all_country_codes


def _packed(size: tuple[int, int], levels: int) -> tuple[list[str], np.ndarray]:
    codes = [c for c in _all_country_codes() if (FLAG_DIR / f"{c}.png").exists()]
    step = 256 // levels
    rows = []
    for c in codes:
        img = Image.open(FLAG_DIR / f"{c}.png").convert("RGB").resize(size, Image.BILINEAR)
        a = np.asarray(img, dtype=np.uint8)
        a = (a // step) * step + step // 2
        rows.append(
            (a[..., 0].astype(np.uint32) << 16
             | a[..., 1].astype(np.uint32) << 8
             | a[..., 2].astype(np.uint32)).reshape(-1)
        )
    return codes, np.stack(rows)


def score_opener(opener_row: np.ndarray, flags: np.ndarray) -> dict:
    masks = flags == opener_row[None, :]
    packed = np.packbits(masks, axis=1)
    view = np.ascontiguousarray(packed).view(np.dtype((np.void, packed.shape[1]))).ravel()
    _, inv, counts = np.unique(view, return_inverse=True, return_counts=True)
    K = len(opener_row)  # unused
    K = masks.shape[0]
    p = counts / K
    entropy = float(np.sum(p * np.log2(counts)))
    return {
        "entropy": entropy,
        "worst_case": int(counts.max()),
        "num_unique": int((counts == 1).sum()),
        "mean_bucket": float((counts * counts).sum() / K),  # E[bucket size | I'm in it]
        "num_buckets": int(len(counts)),
    }


def run_config(size: tuple[int, int], levels: int) -> None:
    print(f"\n=== config: size={size}  levels={levels} ===")
    codes, flags = _packed(size, levels)
    N = len(codes)
    rows = []
    for i in tqdm(range(N), desc=f"{size} L{levels}"):
        s = score_opener(flags[i], flags)
        s["code"] = codes[i]
        rows.append(s)

    print(f"\nTop 10 by EXPECTED ENTROPY (lower=better):")
    for r in sorted(rows, key=lambda r: r["entropy"])[:10]:
        print(f"  {r['code']:>4}  H={r['entropy']:.3f}  worst={r['worst_case']:>3}  "
              f"unique={r['num_unique']:>3}/{N}  buckets={r['num_buckets']:>3}  "
              f"mean_bkt={r['mean_bucket']:5.2f}")

    print(f"\nTop 10 by NUM_UNIQUE (higher=better):")
    for r in sorted(rows, key=lambda r: -r["num_unique"])[:10]:
        print(f"  {r['code']:>4}  unique={r['num_unique']:>3}/{N}  H={r['entropy']:.3f}  "
              f"worst={r['worst_case']:>3}  buckets={r['num_buckets']:>3}")

    print(f"\nTop 10 by WORST_CASE bucket size (lower=better):")
    for r in sorted(rows, key=lambda r: (r["worst_case"], r["entropy"]))[:10]:
        print(f"  {r['code']:>4}  worst={r['worst_case']:>3}  H={r['entropy']:.3f}  "
              f"unique={r['num_unique']:>3}/{N}  buckets={r['num_buckets']:>3}")


def main() -> None:
    configs = [
        ((60, 40), 6),     # the original opener-search config
        ((120, 80), 8),
        ((240, 160), 8),   # the screenshot-solver config
    ]
    for size, lv in configs:
        run_config(size, lv)


if __name__ == "__main__":
    main()
