"""Exhaustive opener audit using the *exact* Flagle matching rules.

For each candidate opener, computes against the 197 actual Flagle countries:
  - expected entropy (lower better)
  - number of unique reveal masks (higher better)
  - worst-case bucket size (lower better)
  - explicit collision groups

If `num_unique == N`, every solution can be locked in on guess #2 — true
single-guess identification (you played opener, observed mask, the mask
maps to exactly one candidate).
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
from tqdm import tqdm

from flagle.flagle_exact import build_cache, reveal_masks_against_all


def score_opener(masks_NHW: np.ndarray) -> dict:
    N, H, W = masks_NHW.shape
    packed = np.packbits(masks_NHW.reshape(N, H * W), axis=1)
    view = np.ascontiguousarray(packed).view(np.dtype((np.void, packed.shape[1]))).ravel()
    _, inv, counts = np.unique(view, return_inverse=True, return_counts=True)
    p = counts / N
    return {
        "entropy": float(np.sum(p * np.log2(counts))),
        "worst_case": int(counts.max()),
        "num_unique": int((counts == 1).sum()),
        "num_buckets": int(len(counts)),
        "inverse": inv,           # bucket id per flag
        "counts": counts,
    }


def main() -> None:
    codes, rgba = build_cache()
    N = len(codes)
    print(f"loaded {N} flags @ {rgba.shape[1]}x{rgba.shape[2]}")

    rows = []
    for i in tqdm(range(N), desc="openers"):
        masks = reveal_masks_against_all(rgba[i], rgba)
        s = score_opener(masks)
        rows.append({
            "code": codes[i],
            "entropy": s["entropy"],
            "worst_case": s["worst_case"],
            "num_unique": s["num_unique"],
            "num_buckets": s["num_buckets"],
        })

    print("\nTop 15 by EXPECTED ENTROPY (lower=better):")
    for r in sorted(rows, key=lambda r: r["entropy"])[:15]:
        print(f"  {r['code']:>4}  H={r['entropy']:6.3f}  worst={r['worst_case']:>3}  "
              f"unique={r['num_unique']:>3}/{N}  buckets={r['num_buckets']:>3}")

    print("\nTop 15 by NUM_UNIQUE (higher=better):")
    for r in sorted(rows, key=lambda r: -r["num_unique"])[:15]:
        print(f"  {r['code']:>4}  unique={r['num_unique']:>3}/{N}  H={r['entropy']:6.3f}  "
              f"worst={r['worst_case']:>3}  buckets={r['num_buckets']:>3}")

    print("\nTop 15 by WORST_CASE bucket (lower=better):")
    for r in sorted(rows, key=lambda r: (r["worst_case"], r["entropy"]))[:15]:
        print(f"  {r['code']:>4}  worst={r['worst_case']:>3}  H={r['entropy']:6.3f}  "
              f"unique={r['num_unique']:>3}/{N}  buckets={r['num_buckets']:>3}")

    # Detailed collision report for the best opener (by entropy)
    best = min(rows, key=lambda r: r["entropy"])
    print(f"\n=== Collision report for top opener: {best['code']} ===")
    best_idx = codes.index(best["code"])
    masks = reveal_masks_against_all(rgba[best_idx], rgba)
    groups: dict[bytes, list[int]] = defaultdict(list)
    for i, m in enumerate(masks):
        groups[np.packbits(m).tobytes()].append(i)
    collisions = sorted(
        [g for g in groups.values() if len(g) > 1],
        key=len, reverse=True,
    )
    if not collisions:
        print("  >>> NO COLLISIONS — every flag has a UNIQUE reveal mask. <<<")
        print("  >>> Single-guess lock-in is achievable with this opener.    <<<")
    else:
        total_in_collisions = sum(len(g) for g in collisions)
        print(f"  collision groups: {len(collisions)}")
        print(f"  flags affected:   {total_in_collisions}/{N}")
        for g in collisions:
            revealed = int(masks[g[0]].sum())
            print(f"    [{len(g)} flags, {revealed:>6} px]: {[codes[i] for i in g]}")


if __name__ == "__main__":
    main()
