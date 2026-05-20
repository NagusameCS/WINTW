"""Screenshot → answer pipeline for Flagle (opener = sz).

Render model (verified against main.js):
- Canvas is 400x267 RGBA. For every pixel where guess matches solution
  (color distance < 18% AND both alphas > 0.5) the canvas stores the
  *solution's* RGB at full alpha. All other pixels stay at alpha=0.
- The DOM composites this canvas onto `palette.background.canvas`.
- So in a screenshot of the flag area:
    revealed pixel  -> shows solution's flag color
    hidden  pixel   -> shows the page background color (a single solid)

Extraction algorithm:
1. Crop the screenshot to the flag area (or accept a pre-cropped image).
2. Resize to 400x267 bilinear.
3. Identify the background color as the dominant color in the image
   (also confirmed against the 4 corners which are reliably hidden).
4. Pixel is "revealed" iff its color distance from background is > epsilon.
5. Feed the (267, 400) bool mask to flagle.solver_exact.solve_from_mask.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from flagle.flagle_exact import (
    CANVAS_H, CANVAS_W, _load_rgba, reveal_mask,
)
from flagle.solver_exact import (
    OPTIMAL_OPENER, SolveResult, load_database, solve_from_mask,
)

BG_EPSILON = 12          # squared per-channel distance ~ very small
CORNER_PATCH = 8         # px square sampled per corner for bg detection


def _detect_bg(rgb: np.ndarray) -> np.ndarray:
    """Find the page background color via corner sampling + mode fallback."""
    H, W = rgb.shape[:2]
    corners = np.concatenate([
        rgb[:CORNER_PATCH, :CORNER_PATCH].reshape(-1, 3),
        rgb[:CORNER_PATCH, -CORNER_PATCH:].reshape(-1, 3),
        rgb[-CORNER_PATCH:, :CORNER_PATCH].reshape(-1, 3),
        rgb[-CORNER_PATCH:, -CORNER_PATCH:].reshape(-1, 3),
    ], axis=0)
    return np.median(corners, axis=0).astype(np.int16)


def extract_mask(image_path: str | Path) -> np.ndarray:
    """Returns (267, 400) bool. True = pixel revealed."""
    img = Image.open(image_path).convert("RGB").resize(
        (CANVAS_W, CANVAS_H), Image.BILINEAR
    )
    rgb = np.asarray(img, dtype=np.int16)
    bg = _detect_bg(rgb)
    diff = rgb - bg
    dist_sq = (diff * diff).sum(axis=-1)
    return dist_sq > BG_EPSILON * BG_EPSILON


def synthesize_screenshot(
    solution_code: str,
    bg_rgb: tuple[int, int, int] = (18, 18, 18),     # MUI dark canvas
    opener_code: str = OPTIMAL_OPENER,
) -> Image.Image:
    """Render exactly what Flagle shows after guessing `opener_code` for solution."""
    guess = _load_rgba(opener_code)
    sol = _load_rgba(solution_code)
    mask = reveal_mask(guess, sol)
    out = np.full((CANVAS_H, CANVAS_W, 3), bg_rgb, dtype=np.uint8)
    out[mask] = sol[mask, :3]
    return Image.fromarray(out, "RGB")


def solve_screenshot(image_path: str | Path) -> SolveResult:
    return solve_from_mask(extract_mask(image_path))


# ---------------------------------------------------------------- tests ----

def end_to_end_test(tmp_dir: Path) -> None:
    """Synthesize a screenshot for each of 197 solutions, run the full
    pipeline, report accuracy + min margin."""
    codes, flat = load_database()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    correct = 0
    min_margin = 10**9
    failures = []
    for code in codes:
        path = tmp_dir / f"{code}.png"
        synthesize_screenshot(code).save(path)
        res = solve_screenshot(path)
        if res.code == code:
            correct += 1
            min_margin = min(min_margin, res.margin)
        else:
            failures.append((code, res.code, res.hamming, res.margin))
    print(f"end-to-end clean: {correct}/{len(codes)} correct,"
          f" min margin = {min_margin}")
    for f in failures[:10]:
        print(f"  miss: true={f[0]} pred={f[1]} hamming={f[2]} margin={f[3]}")


def end_to_end_noise_test(tmp_dir: Path, jpeg_quality: int = 60) -> None:
    """Round-trip through JPEG to mimic realistic screenshot compression."""
    codes, flat = load_database()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    correct = 0
    for code in codes:
        path = tmp_dir / f"{code}.jpg"
        synthesize_screenshot(code).save(path, quality=jpeg_quality)
        res = solve_screenshot(path)
        if res.code == code:
            correct += 1
    print(f"end-to-end JPEG q{jpeg_quality}: {correct}/{len(codes)} correct")


def end_to_end_resize_test(tmp_dir: Path, scale: float = 2.5) -> None:
    """Render at a larger size (mimics retina/zoomed screenshot)."""
    codes, _ = load_database()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    big_w, big_h = int(CANVAS_W * scale), int(CANVAS_H * scale)
    correct = 0
    for code in codes:
        img = synthesize_screenshot(code).resize((big_w, big_h), Image.LANCZOS)
        path = tmp_dir / f"{code}_x{scale}.png"
        img.save(path)
        res = solve_screenshot(path)
        if res.code == code:
            correct += 1
    print(f"end-to-end {scale}x rescale: {correct}/{len(codes)} correct")


def end_to_end_bg_test(tmp_dir: Path) -> None:
    """Test multiple plausible page backgrounds."""
    codes, _ = load_database()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for label, bg in [
        ("dark", (18, 18, 18)),
        ("light", (255, 255, 255)),
        ("mid",   (128, 128, 128)),
        ("paper", (245, 245, 245)),
    ]:
        correct = 0
        for code in codes:
            path = tmp_dir / f"{code}_{label}.png"
            synthesize_screenshot(code, bg_rgb=bg).save(path)
            res = solve_screenshot(path)
            if res.code == code:
                correct += 1
        print(f"end-to-end bg={label} {bg}: {correct}/{len(codes)} correct")


if __name__ == "__main__":
    out = Path("data/cache/screenshots")
    end_to_end_test(out)
    end_to_end_noise_test(out, jpeg_quality=80)
    end_to_end_noise_test(out, jpeg_quality=50)
    end_to_end_resize_test(out, scale=2.5)
    end_to_end_bg_test(out)
