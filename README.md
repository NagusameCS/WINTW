# WINTW — Optimal Flagle Bot + One-Shot Solver

Solves [flagle-game.com/unlimited](https://flagle-game.com/unlimited) in
**2 guesses, every time**, by reverse-engineering the game's pixel-matching
algorithm and finding an opener whose post-guess reveal mask is unique
across all 197 candidate flags.

## TL;DR

- **Open with `SZ` (Eswatini).**
- Take a screenshot of the canvas after that guess.
- Drop it into the [web solver](https://nagusamecs.github.io/WINTW/) → answer.

## Results

| | Value |
|---|---|
| Mathematical 1-guess lock-in | **197 / 197** (entropy = 0) |
| Min pairwise reveal-mask Hamming margin | 124 px |
| End-to-end screenshot solver, clean PNG | **197 / 197** |
| Under JPEG q40 / 0.7× downscale | 196 / 197 |
| Robustness under 10% random pixel noise | 100 % |

## How the model was built

The original quantized-color model said "Brunei optimal, 89% ceiling". That
was wrong — it didn't match Flagle's real rule.

Reverse-engineering [the Flagle JS bundle](flagle_reference/main.js) revealed:

- Canvas is **400 × 267 RGBA** (33,612 px for Nepal due to its pennant shape).
- Match rule per pixel:
  ```
  d(g, s) = sqrt((dr)^2 + (dg)^2 + (db)^2) / sqrt(195075) * 100
  reveal  = d < 18   AND   alpha_g > 0.5   AND   alpha_s > 0.5
  ```
- 197 country codes (verified against the embedded list).
- No geographic distance / bearing signal — only the pixel mask.

Under this exact rule, **18 openers** achieve full 197-bucket uniqueness.
Ranking those 18 by minimum pairwise Hamming distance (= screenshot
robustness), **`SZ` wins by 1.4x** over the runner-up (`FJ`):

```
sz  124 px   fj  88   za  33   ki  16   sc  14   ...
```

124 pixels of safety margin means every reasonable screenshot-extraction
error still lands on the correct answer.

## Repo layout

```
flagle/
  flagle_exact.py        # exact Flagle engine (canonical match rule)
  solver_exact.py        # mask -> answer (provably 197/197)
  mle_solver.py          # screenshot -> answer (max-likelihood template match)
  screenshot_pipeline.py # DEPRECATED mask-extraction baseline (33/197)
  bot.py, simulator.py, vision.py, flags.py  # earlier toy quantized model

scripts/
  build_web.py                # generates docs/data/ for GH Pages
  analyze_openers_exact.py    # opener entropy / collision audit (real rules)
  rank_openers_robust.py      # robustness ranking among perfect openers
  ...                         # earlier analysis tools

docs/                         # GitHub Pages site (one-shot web solver)
  index.html  app.js  style.css
  data/  masks_sz.bin  codes.json  countries.json

data/                         # generated caches (not committed)
flagle_reference/             # the captured live Flagle JS / HTML
```

## Local usage

```bash
pip install -r requirements.txt

# Bot: prove 1-guess lock-in
python -m scripts.analyze_openers_exact     # opener audit
python -m scripts.rank_openers_robust       # robustness ranking
python -m flagle.solver_exact               # 197/197 clean + noise tests

# Screenshot solver: 100% on clean PNG, any bg color
python -m flagle.mle_solver

# Rebuild the GH Pages data bundle
python -m scripts.build_web
```

## Web solver

The [docs/](docs/) folder is a zero-build static site:

- Loads the 197-flag reveal-mask database (2.6 MB packed bits).
- Fetches flag PNGs from `flagcdn.com` on demand (browser-cached).
- Runs the MLE solver entirely in your browser.
- **Helper mode** reveals hints progressively: continent -> subregion ->
  first letter -> answer, narrowing the candidate list each step.

Enable GitHub Pages: repo Settings -> Pages -> Source = `main` branch,
`/docs` folder.
