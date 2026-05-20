"""Find the opener that maximizes UNIQUE-mask candidates (not entropy).

For single-shot screenshot identification we want the opener whose reveal
mask is *unique* for as many possible solutions as possible.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
from PIL import Image
from tqdm import tqdm

from flagle.flags import FLAG_DIR, _all_country_codes


def _packed_all(size: tuple[int, int], levels: int) -> tuple[list[str], np.ndarray]:
    codes = [c for c in _all_country_codes() if (FLAG_DIR / f"{c}.png").exists()]
    rows = []
    step = 256 // levels
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


def uniqueness(opener_row: np.ndarray, flags: np.ndarray) -> int:
    masks = flags == opener_row[None, :]
    packed = np.packbits(masks, axis=1)
    view = np.ascontiguousarray(packed).view(np.dtype((np.void, packed.shape[1]))).ravel()
    _, counts = np.unique(view, return_counts=True)
    # number of singletons
    return int((counts == 1).sum())


def main() -> None:
    size, levels = (240, 160), 8
    codes, flags = _packed_all(size, levels)
    N = len(codes)
    print(f"config: size={size} levels={levels}  N={N}")
    scores = np.empty(N, dtype=np.int32)
    for i in tqdm(range(N), desc="opener"):
        scores[i] = uniqueness(flags[i], flags)
    order = np.argsort(-scores)
    print("\nTop 20 openers by # uniquely-identified candidates:")
    for i in order[:20]:
        print(f"  {codes[i]:>4}  unique={scores[i]:>3}/{N}  ({100*scores[i]/N:5.1f}%)")


if __name__ == "__main__":
    main()
