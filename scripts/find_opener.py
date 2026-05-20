"""Find the optimal opening guess by exhaustive entropy search.

For each flag g, compute the expected remaining entropy (in bits) of the
posterior after guessing g, under a uniform prior over all candidates.
The minimizer is the optimal opener.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from tqdm import tqdm

from flagle.bot import expected_entropy
from flagle.flags import CACHE_DIR, load


def main() -> None:
    codes, flags, names = load()
    N = flags.shape[0]
    print(f"evaluating {N} possible openers against {N} candidates...")

    scores = np.empty(N, dtype=np.float64)
    for i in tqdm(range(N), desc="opener"):
        scores[i] = expected_entropy(flags[i], flags)

    order = np.argsort(scores)
    out_path = CACHE_DIR / "opener.json"
    top = [
        {
            "code": codes[i],
            "country": names.get(codes[i], codes[i]),
            "expected_entropy_bits": float(scores[i]),
        }
        for i in order[:25]
    ]
    out_path.write_text(json.dumps(top, indent=2), encoding="utf-8")

    print("\nTop 15 openers (lower expected entropy = better):")
    for row in top[:15]:
        print(f"  {row['code']:>4}  {row['country']:<30}  {row['expected_entropy_bits']:.3f} bits")
    print(f"\nsaved → {out_path}")


if __name__ == "__main__":
    main()
