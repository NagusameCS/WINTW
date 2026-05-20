"""Simulate the bot against every possible hidden flag; report guess distribution."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from tqdm import tqdm

from flagle.bot import best_guess, filter_candidates
from flagle.flags import CACHE_DIR, load
from flagle.simulator import feedback_mask

MAX_GUESSES = 6


def play_one(all_flags: np.ndarray, solution_idx: int, opener_idx: int) -> int:
    """Return the number of guesses the bot needed (or MAX_GUESSES+1 on failure)."""
    N = all_flags.shape[0]
    candidates = np.arange(N)
    guess_idx = opener_idx
    for turn in range(1, MAX_GUESSES + 1):
        if guess_idx == solution_idx:
            return turn
        mask = feedback_mask(all_flags[guess_idx], all_flags[solution_idx])
        candidates = filter_candidates(all_flags, candidates, guess_idx, mask)
        if len(candidates) == 0:
            return MAX_GUESSES + 1
        move = best_guess(all_flags, candidates, candidate_only=(len(candidates) <= 8))
        guess_idx = move.index
    return MAX_GUESSES + 1


def main() -> None:
    codes, flags, names = load()
    N = flags.shape[0]

    opener_path = CACHE_DIR / "opener.json"
    if opener_path.exists():
        top = json.loads(opener_path.read_text(encoding="utf-8"))
        opener_code = top[0]["code"]
    else:
        # Fallback: compute on the fly
        from flagle.bot import expected_entropy
        scores = np.array([expected_entropy(flags[i], flags) for i in range(N)])
        opener_code = codes[int(np.argmin(scores))]
    opener_idx = codes.index(opener_code)
    print(f"opener: {opener_code} ({names.get(opener_code, '?')})")

    results = Counter()
    failures: list[str] = []
    for s in tqdm(range(N), desc="simulate"):
        g = play_one(flags, s, opener_idx)
        results[g] += 1
        if g > MAX_GUESSES:
            failures.append(codes[s])

    print("\nGuess distribution:")
    for k in sorted(results):
        label = f"{k}" if k <= MAX_GUESSES else "FAIL"
        print(f"  {label:>4}: {results[k]:4d}  ({100*results[k]/N:5.2f}%)")
    mean = sum(k * v for k, v in results.items() if k <= MAX_GUESSES) / max(
        1, sum(v for k, v in results.items() if k <= MAX_GUESSES)
    )
    win_rate = sum(v for k, v in results.items() if k <= MAX_GUESSES) / N
    print(f"\nwin rate: {win_rate*100:.2f}%")
    print(f"mean guesses (on wins): {mean:.3f}")
    if failures:
        print(f"failed on {len(failures)}: {failures[:20]}{'...' if len(failures)>20 else ''}")


if __name__ == "__main__":
    main()
