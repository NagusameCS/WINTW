"""Compute opener-quality ranking for all 197 candidates and dump to JSON
for the web frontend.

Output: docs/data/openers.json — list of
  { code, name, unique, min_hamming, min_reveal, mean_reveal, rank }
sorted by rank (1 = best). `unique=False` openers get rank=null and
go to the bottom of the list.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from tqdm import tqdm

from flagle.flagle_exact import build_cache, reveal_masks_against_all

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "openers.json"
COUNTRIES_FILE = ROOT / "docs" / "data" / "countries.json"


def main() -> None:
    codes, rgba = build_cache()
    N = len(codes)
    countries = json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))

    rows = []
    for i in tqdm(range(N), desc="rank openers"):
        masks = reveal_masks_against_all(rgba[i], rgba)
        flat = masks.reshape(N, -1)
        packed = np.packbits(flat, axis=1)
        view = np.ascontiguousarray(packed).view(
            np.dtype((np.void, packed.shape[1]))
        ).ravel()
        _, counts = np.unique(view, return_counts=True)
        unique = bool(counts.max() == 1)

        counts_per_sol = flat.sum(axis=1)
        min_reveal = int(counts_per_sol.min())
        mean_reveal = float(counts_per_sol.mean())

        if unique:
            bits = np.unpackbits(packed, axis=1)
            sums = bits.sum(axis=1).astype(np.int64)
            inter = bits.astype(np.int32) @ bits.T.astype(np.int32)
            hamming = sums[:, None] + sums[None, :] - 2 * inter
            np.fill_diagonal(hamming, 10**9)
            min_hamming = int(hamming.min())
        else:
            min_hamming = 0

        meta = countries.get(codes[i], {})
        rows.append({
            "code": codes[i],
            "name": meta.get("name", codes[i].upper()),
            "unique": unique,
            "min_hamming": min_hamming,
            "min_reveal": min_reveal,
            "mean_reveal": round(mean_reveal, 1),
        })

    # rank: among unique, higher min_hamming = better; tie-break by min_reveal
    unique_rows = [r for r in rows if r["unique"]]
    unique_rows.sort(key=lambda r: (-r["min_hamming"], -r["min_reveal"]))
    for i, r in enumerate(unique_rows):
        r["rank"] = i + 1
    for r in rows:
        if not r["unique"]:
            r["rank"] = None

    # final ordering: by rank (None last), then alpha
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"]))

    OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT} ({len(rows)} openers, {len(unique_rows)} unique)")
    print(f"Top 5: {[(r['code'], r['min_hamming']) for r in rows[:5]]}")


if __name__ == "__main__":
    main()
