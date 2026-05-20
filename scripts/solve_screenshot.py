"""Solve a Flagle puzzle from a screenshot of the post-first-guess board.

Assumes the user played the model's optimal opener (Brunei). The vision
pipeline auto-detects the flag widget, extracts the reveal mask, and
ranks candidates by similarity to the precomputed reveal-mask table.

Usage
-----
    python -m scripts.solve_screenshot path/to/screenshot.png
    python -m scripts.solve_screenshot path/to/screenshot.png --bbox 120,300,480,320
    python -m scripts.solve_screenshot path/to/screenshot.png --debug
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from flagle.flags import CACHE_DIR, load
from flagle.vision import OPENER_CODE, solve


def main() -> None:
    p = argparse.ArgumentParser(description="Solve Flagle from a screenshot.")
    p.add_argument("screenshot", type=Path)
    p.add_argument("--bbox", type=str, default=None,
                   help="optional x,y,w,h to override auto-detection")
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--debug", action="store_true",
                   help="dump intermediate images to data/cache/debug/")
    args = p.parse_args()

    bbox = None
    if args.bbox:
        bbox = tuple(int(v) for v in args.bbox.split(","))
        if len(bbox) != 4:
            raise SystemExit("--bbox expects 4 comma-separated ints: x,y,w,h")

    _, _, names = load()
    debug_dir = (CACHE_DIR / "debug") if args.debug else None
    ranked = solve(args.screenshot, bbox=bbox, top_k=args.top_k, debug_dir=debug_dir)

    print(f"opener assumed: {OPENER_CODE} ({names.get(OPENER_CODE, '?')})")
    print(f"screenshot:     {args.screenshot}")
    if debug_dir:
        print(f"debug images:   {debug_dir}")
    print()
    print(f"{'rank':>4}  {'code':>4}  {'country':<30}  {'match':>6}  {'unique':>6}")
    for i, c in enumerate(ranked, 1):
        print(
            f"{i:>4}  {c.code:>4}  {names.get(c.code, c.code):<30}  "
            f"{100*c.score:5.2f}%  {'yes' if c.unique else 'no':>6}"
        )

    top = ranked[0]
    print()
    if top.unique and top.score > 0.97:
        print(f"=> SOLUTION: {top.code} ({names.get(top.code, '?')})  — unique mask, high confidence")
    elif top.unique:
        print(f"=> Likely:   {top.code} ({names.get(top.code, '?')})  — unique reference mask, noisy match")
    else:
        same_mask = [c for c in ranked if c.hamming == top.hamming]
        codes_eq = ", ".join(c.code for c in same_mask)
        print(f"=> Ambiguous (this solution's mask collides with {len(same_mask)} flags): {codes_eq}")
        print("   → second guess required to disambiguate.")


if __name__ == "__main__":
    main()
