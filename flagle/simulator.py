"""Ground-truth feedback function: which pixels match between guess and solution.

The packed-uint32 representation in `flags.py` lets us compute the entire
match mask for a guess against every candidate solution as a single
vectorized numpy comparison.
"""

from __future__ import annotations

import numpy as np


def feedback_mask(guess_row: np.ndarray, solution_row: np.ndarray) -> np.ndarray:
    """Boolean array of shape (PIXELS,): True where pixels match."""
    return guess_row == solution_row


def feedback_against_all(
    guess_row: np.ndarray, all_flags: np.ndarray
) -> np.ndarray:
    """Boolean (N, PIXELS) mask: row i is the feedback if flag i were the solution."""
    return all_flags == guess_row[None, :]
