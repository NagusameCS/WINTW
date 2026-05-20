"""Probe how unique the opener's reveal-mask is across candidates, at varying resolutions.

Prints, for each (size, quant) combo, how many candidates have a unique mask
vs. how many share a mask with at least one other candidate.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from flagle.flags import FLAG_DIR, _all_country_codes


def _packed(code: str, size: tuple[int, int], levels: int) -> np.ndarray:
    p = FLAG_DIR / f"{code}.png"
    img = Image.open(p).convert("RGB").resize(size, Image.BILINEAR)
    a = np.asarray(img, dtype=np.uint8)
    step = 256 // levels
    a = (a // step) * step + step // 2
    return (
        a[..., 0].astype(np.uint32) << 16
        | a[..., 1].astype(np.uint32) << 8
        | a[..., 2].astype(np.uint32)
    ).reshape(-1)


def probe(size: tuple[int, int], levels: int) -> tuple[int, int]:
    codes = [c for c in _all_country_codes() if (FLAG_DIR / f"{c}.png").exists()]
    flags = np.stack([_packed(c, size, levels) for c in codes])
    opener = codes.index("bn")
    masks = flags == flags[opener][None, :]
    keys = [bytes(np.packbits(m)) for m in masks]
    cnt = Counter(keys)
    unique = sum(1 for k in keys if cnt[k] == 1)
    return unique, len(codes)


def main() -> None:
    configs = [
        ((60, 40), 6),
        ((60, 40), 8),
        ((120, 80), 6),
        ((120, 80), 8),
        ((120, 80), 12),
        ((240, 160), 8),
        ((240, 160), 12),
    ]
    print(f"{'size':>10}  {'levels':>6}  {'unique':>7}  {'%':>6}")
    for size, lv in configs:
        u, n = probe(size, lv)
        print(f"{str(size):>10}  {lv:>6}  {u:>5}/{n}  {100*u/n:5.1f}%")


if __name__ == "__main__":
    main()
