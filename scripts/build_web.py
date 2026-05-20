"""Build the static GitHub Pages bundle into docs/data/.

Outputs
-------
- docs/data/masks_sz.bin     : packed bool masks (197 * ceil(400*267/8) bytes)
- docs/data/codes.json       : ordered country code list
- docs/data/countries.json   : {code: {name, region, subregion}} from restcountries

Frontend (docs/app.js) consumes these + fetches flags from flagcdn.com on demand.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from flagle.flagle_exact import (
    CANVAS_H, CANVAS_W, build_cache, reveal_masks_against_all,
)
from flagle.solver_exact import OPTIMAL_OPENER

ROOT = Path(__file__).resolve().parent.parent
DOCS_DATA = ROOT / "docs" / "data"


def write_masks() -> list[str]:
    codes, rgba = build_cache()
    idx = codes.index(OPTIMAL_OPENER)
    masks = reveal_masks_against_all(rgba[idx], rgba)               # (N, H, W) bool
    flat = masks.reshape(len(codes), -1)                             # (N, P)
    packed = np.packbits(flat, axis=1)                               # (N, ceil(P/8))
    out = DOCS_DATA / "masks_sz.bin"
    out.write_bytes(packed.tobytes())
    print(f"wrote {out}  shape={packed.shape}  bytes={packed.nbytes:,}")
    (DOCS_DATA / "codes.json").write_text(json.dumps(codes), encoding="utf-8")
    print(f"wrote codes.json with {len(codes)} entries")
    return codes


def fetch_country_meta(codes: list[str]) -> dict:
    """Hit restcountries.com once, build {code: {name, region, subregion}}."""
    import urllib.request
    url = "https://restcountries.com/v3.1/all?fields=cca2,name,region,subregion"
    print(f"fetching {url} ...")
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read())
    by_code = {}
    for entry in data:
        cc = entry.get("cca2", "").lower()
        if not cc:
            continue
        by_code[cc] = {
            "name":      entry.get("name", {}).get("common", cc.upper()),
            "official":  entry.get("name", {}).get("official", ""),
            "region":    entry.get("region", "Other") or "Other",
            "subregion": entry.get("subregion", "") or "",
        }
    # Fill in any codes missing from restcountries with placeholders
    missing = [c for c in codes if c not in by_code]
    if missing:
        print(f"  WARN: {len(missing)} codes missing from restcountries: {missing}")
        for c in missing:
            by_code[c] = {"name": c.upper(), "official": "",
                          "region": "Other", "subregion": ""}
    out = {c: by_code[c] for c in codes}
    (DOCS_DATA / "countries.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote countries.json ({len(out)} entries)")
    return out


def main() -> None:
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    codes = write_masks()
    fetch_country_meta(codes)
    print("done.")


if __name__ == "__main__":
    main()
