"""Among openers with perfect uniqueness, rank by *screenshot robustness*.

For screenshot-based solving, what matters is not just that masks are
unique, but that the discrimination *survives noise*. Concretely:

  robustness(opener) = min over all 197 solutions of (# revealed pixels)

A larger min means even the "least revealing" pair leaves enough signal
to recover. A close runner-up metric is min pairwise Hamming distance —
how many pixels distinguish the two solutions whose masks are most
similar.
"""
from __future__ import annotations

import numpy as np
from tqdm import tqdm

from flagle.flagle_exact import build_cache, reveal_masks_against_all


def main() -> None:
    codes, rgba = build_cache()
    N = len(codes)

    rows = []
    for i in tqdm(range(N), desc="audit"):
        masks = reveal_masks_against_all(rgba[i], rgba)            # (N, H, W)
        flat = masks.reshape(N, -1)
        # uniqueness check
        packed = np.packbits(flat, axis=1)
        view = np.ascontiguousarray(packed).view(
            np.dtype((np.void, packed.shape[1]))
        ).ravel()
        _, counts = np.unique(view, return_counts=True)
        if counts.max() > 1:
            continue                                               # not perfect

        counts_per_sol = flat.sum(axis=1)                          # pixels revealed
        # min pairwise hamming (sample: cheap upper bound via nearest-by-popcount)
        # Exact min hamming on 197×~107K bits in ~0.1s — do it.
        # Hamming(a,b) = popcount(a XOR b). Use packbits → uint8 → bin lookup.
        bits = np.unpackbits(packed, axis=1)  # (N, H*W) uint8, same as flat
        # vectorized pairwise: count differences
        # use float for matrix mult trick: hamming = a+b - 2*a*b for bits
        sums = bits.sum(axis=1).astype(np.int64)                   # (N,)
        # bits @ bits.T -> shared 1s
        inter = bits.astype(np.int32) @ bits.T.astype(np.int32)    # (N, N)
        hamming = sums[:, None] + sums[None, :] - 2 * inter
        np.fill_diagonal(hamming, 10**9)
        min_hamming = int(hamming.min())

        rows.append({
            "code": codes[i],
            "min_reveal": int(counts_per_sol.min()),
            "mean_reveal": float(counts_per_sol.mean()),
            "min_hamming": min_hamming,
        })

    print(f"\nPerfect-uniqueness openers: {len(rows)}/{N}")
    print("\nTop 25 by MIN_HAMMING (screenshot robustness — higher=better):")
    print(f"  {'code':>4}  {'min_ham':>8}  {'min_rev':>8}  {'mean_rev':>9}")
    for r in sorted(rows, key=lambda r: -r["min_hamming"])[:25]:
        print(f"  {r['code']:>4}  {r['min_hamming']:>8}  {r['min_reveal']:>8}  "
              f"{r['mean_reveal']:>9.1f}")

    print("\nTop 25 by MIN_REVEAL (worst-case signal — higher=better):")
    print(f"  {'code':>4}  {'min_rev':>8}  {'min_ham':>8}  {'mean_rev':>9}")
    for r in sorted(rows, key=lambda r: -r["min_reveal"])[:25]:
        print(f"  {r['code']:>4}  {r['min_reveal']:>8}  {r['min_hamming']:>8}  "
              f"{r['mean_reveal']:>9.1f}")

    print("\nBottom 5 (worst openers among the perfect set):")
    for r in sorted(rows, key=lambda r: r["min_hamming"])[:5]:
        print(f"  {r['code']:>4}  min_ham={r['min_hamming']:>6}  "
              f"min_rev={r['min_reveal']:>6}  mean_rev={r['mean_reveal']:>7.1f}")


if __name__ == "__main__":
    main()
