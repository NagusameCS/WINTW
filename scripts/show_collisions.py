"""Print the explicit collision groups against Brunei at the hi-res config.

Two flags collide if (Brunei == flag_A) == (Brunei == flag_B) as boolean
arrays. Within a collision group, NO algorithm can distinguish members from
a single reveal mask — the screenshot is provably identical.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from flagle.flags import load
from flagle.vision import OPENER_CODE, build_hires_cache


def main() -> None:
    codes, rgb, masks = build_hires_cache()
    _, _, names = load()
    opener_idx = codes.index(OPENER_CODE)
    # masks[i] is already (opener == flag_i)
    groups: dict[bytes, list[int]] = defaultdict(list)
    for i, m in enumerate(masks):
        key = np.packbits(m).tobytes()
        groups[key].append(i)

    collisions = [g for g in groups.values() if len(g) > 1]
    collisions.sort(key=len, reverse=True)

    total_unresolvable = sum(len(g) for g in collisions)
    print(f"opener: {OPENER_CODE} ({names.get(OPENER_CODE, '?')})")
    print(f"distinct reveal masks: {len(groups)} (out of {len(codes)} flags)")
    print(f"collision groups: {len(collisions)}")
    print(f"flags affected by collisions: {total_unresolvable}/{len(codes)}\n")

    for g in collisions:
        revealed = int(masks[g[0]].sum())
        print(f"  group of {len(g)} flags  ({revealed:>5} revealed pixels):")
        for i in g:
            print(f"      {codes[i]:>4}  {names.get(codes[i], codes[i])}")
        print()

    # Show one collision pair in detail so we can SEE why they can't be
    # distinguished from the screenshot alone.
    if collisions:
        g = collisions[0]
        print(f"Detail of largest collision group ({len(g)} flags share an identical mask):")
        print(f"  These flags ALL produce the same {int(masks[g[0]].sum())} revealed pixels")
        print(f"  against Brunei. No algorithm, human or machine, can distinguish")
        print(f"  them from just the post-guess screenshot — they look identical.")


if __name__ == "__main__":
    main()
