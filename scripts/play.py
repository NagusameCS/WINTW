"""Interactive REPL: bot suggests a guess; you report the observed reveal.

Workflow per turn
-----------------
1. Bot prints suggested guess (country code + name).
2. You type the guess into flagle-game.com, observe which pixels are revealed.
3. You enter the *correct* country code corresponding to one of the still-
   possible candidates whose pixels match what you observed — OR you can
   provide the raw mask (advanced).

The lightweight path: you tell the bot the result by replaying the *guessed
flag image* + the revealed pixels. Since you usually can't easily encode a
pixel mask by hand, we offer two modes:

  (a) `solution <code>`  — you already know it (debugging / dry run).
  (b) feedback by image  — you save the Flagle reveal as a PNG (transparent
      where unrevealed) and pass its path; the bot reads the pixel mask.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from flagle.bot import best_guess, filter_candidates
from flagle.flags import CACHE_DIR, FLAG_H, FLAG_W, load
from flagle.simulator import feedback_mask


def _opener_idx(codes: list[str]) -> int:
    p = CACHE_DIR / "opener.json"
    if p.exists():
        top = json.loads(p.read_text(encoding="utf-8"))
        return codes.index(top[0]["code"])
    return 0


def _mask_from_png(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGBA").resize((FLAG_W, FLAG_H), Image.NEAREST)
    arr = np.asarray(img)
    alpha = arr[..., 3].reshape(-1)
    return alpha > 0


def main() -> None:
    codes, flags, names = load()
    N = flags.shape[0]
    candidates = np.arange(N)

    print(f"Flagle bot ready. {N} candidates. Type 'q' to quit.\n")

    opener = _opener_idx(codes)
    suggested = opener
    turn = 1
    while turn <= 6:
        code = codes[suggested]
        print(f"--- guess {turn} ---")
        print(f"  play: {code}  ({names.get(code, '?')})")
        print(f"  candidates remaining: {len(candidates)}")
        line = input(
            "  feedback (`solution <code>` | `mask <png-path>` | `done`): "
        ).strip()
        if line in ("q", "quit"):
            return
        if line == "done":
            print("solved 🎉")
            return
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            print("  ! expected 'solution <code>' or 'mask <path>'")
            continue
        kind, arg = parts
        if kind == "solution":
            if arg not in codes:
                print(f"  ! unknown code {arg!r}")
                continue
            sol_idx = codes.index(arg)
            mask = feedback_mask(flags[suggested], flags[sol_idx])
        elif kind == "mask":
            mask = _mask_from_png(Path(arg))
        else:
            print("  ! unknown command")
            continue

        if suggested in candidates and mask.all():
            print("solved 🎉")
            return

        candidates = filter_candidates(flags, candidates, suggested, mask)
        print(f"  -> {len(candidates)} candidates remain")
        if len(candidates) == 0:
            print("  ! no candidates left — model/quantization mismatch with Flagle's renderer")
            return
        if len(candidates) == 1:
            print(f"  solution must be: {codes[candidates[0]]} ({names.get(codes[candidates[0]], '?')})")
        move = best_guess(flags, candidates, candidate_only=(len(candidates) <= 8))
        suggested = move.index
        turn += 1


if __name__ == "__main__":
    main()
