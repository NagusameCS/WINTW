"""Information-gain bot for Flagle.

Strategy
--------
At every step we hold a posterior set `candidates` of flags still consistent
with all feedback observed so far (uniform over that set). For each possible
guess g (drawn from the full flag pool — the game lets you guess anything)
we partition `candidates` by the feedback mask g would produce against each
candidate. The expected remaining entropy is

    H(g) = Σ_b (|bucket_b| / |C|) * log2(|bucket_b|)

We pick the guess minimizing H(g); ties broken by preferring guesses that
are themselves in `candidates` (so we can still win on the current turn).

The feedback mask is high-dimensional (PIXELS bits), so we hash it with
`np.ndarray.tobytes()` per row — fast and exact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .simulator import feedback_against_all


@dataclass
class Move:
    code: str
    index: int
    expected_entropy_bits: float
    n_candidates_before: int


def _bucket_sizes(masks: np.ndarray) -> np.ndarray:
    """Given (K, PIXELS) bool masks, return sizes of equivalence buckets."""
    # Pack bits to make hashing 8x cheaper.
    packed = np.packbits(masks, axis=1)  # (K, ceil(PIXELS/8)) uint8
    # Hash each row via tobytes — vectorized unique on byte rows.
    view = np.ascontiguousarray(packed).view(
        np.dtype((np.void, packed.shape[1]))
    ).ravel()
    _, counts = np.unique(view, return_counts=True)
    return counts


def expected_entropy(
    guess_row: np.ndarray, candidate_flags: np.ndarray
) -> float:
    """Expected bits of entropy remaining if we play `guess_row`."""
    masks = feedback_against_all(guess_row, candidate_flags)  # (K, PIXELS)
    counts = _bucket_sizes(masks)
    K = counts.sum()
    # H = Σ (c/K) * log2(c)   — equivalent to minimizing log of bucket sizes.
    # (Constant -log2(K) dropped; only relative values matter.)
    p = counts / K
    # log2(c) where c>=1, so safe.
    return float(np.sum(p * np.log2(counts)))


def best_guess(
    all_flags: np.ndarray,
    candidate_indices: np.ndarray,
    *,
    candidate_only: bool = False,
) -> Move:
    """Pick the next guess.

    Parameters
    ----------
    all_flags          : (N, PIXELS) full flag pool (any flag can be guessed).
    candidate_indices  : (K,) indices into all_flags of still-possible solutions.
    candidate_only     : restrict guesses to the candidate set (useful when K is
                         small enough that a "stab" is correct in expectation).
    """
    cand = all_flags[candidate_indices]
    K = len(candidate_indices)

    # Trivial cases
    if K == 1:
        i = int(candidate_indices[0])
        return Move(code="", index=i, expected_entropy_bits=0.0, n_candidates_before=K)

    pool = (
        candidate_indices
        if candidate_only or K <= 2
        else np.arange(all_flags.shape[0])
    )

    best_h = math.inf
    best_idx = int(pool[0])
    cand_set = set(map(int, candidate_indices))
    for gi in pool:
        h = expected_entropy(all_flags[gi], cand)
        # Tie-break: prefer guesses that are still candidates (can win now).
        tie = 0.0 if int(gi) in cand_set else 1e-9
        if h + tie < best_h:
            best_h = h + tie
            best_idx = int(gi)
    return Move(
        code="", index=best_idx, expected_entropy_bits=best_h,
        n_candidates_before=K,
    )


def filter_candidates(
    all_flags: np.ndarray,
    candidate_indices: np.ndarray,
    guess_index: int,
    observed_mask: np.ndarray,
) -> np.ndarray:
    """Return the subset of candidates consistent with the observed mask."""
    guess_row = all_flags[guess_index]
    masks = feedback_against_all(guess_row, all_flags[candidate_indices])
    keep = np.all(masks == observed_mask[None, :], axis=1)
    return candidate_indices[keep]
