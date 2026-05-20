// Flagle One-Shot Solver — client-side MLE template matching.
//
// Algorithm (mirrors flagle/mle_solver.py):
//  - For opener=sz, we have a precomputed reveal mask per candidate (197 total).
//  - Input screenshot → autocrop to non-bg bbox → resize to 400×267.
//  - Detect bg color from canvas border (mode RGB).
//  - For each candidate i, predicted pixel = mask[i] ? flag[i].rgb : bg.
//  - Score = mean squared error vs the cropped input.
//  - argmin → answer. Margin to runner-up = confidence.
//
// Flag PNGs are fetched lazily from flagcdn.com (cached by browser).

const W = 400, H = 267, P = W * H;
const DEFAULT_OPENER = "sz";
const FLAG_URL = (code) => `https://flagcdn.com/w320/${code}.png`;
// Flagle's exact match rule (see flagle/flagle_exact.py):
//   dist_sq = (dr)^2 + (dg)^2 + (db)^2 < THRESHOLD_DIST_SQ  AND both alphas > 127
//   THRESHOLD_DIST_SQ = (18/100)^2 * (3 * 255^2)
const THRESHOLD_DIST_SQ = (18 / 100) ** 2 * (3 * 255 * 255);
const ALPHA_HI = 127;

const $ = (id) => document.getElementById(id);

let CODES = [];           // ["ad","ae",...]  length 197
let COUNTRIES = {};       // {code: {name, region, subregion, official}}
let OPENERS = [];         // [{code, name, unique, min_hamming, rank}, ...]
let MASKS = null;         // Uint8Array, length 197*P (unpacked bits, 0/1) — for current OPENER
let CURRENT_OPENER = DEFAULT_OPENER;
let FLAG_RGB = [];        // Array of Uint8ClampedArray(P*4) RGBA per candidate
let FLAGS_LOADED = 0;
let SOLVE_ENABLED = false;

// ---------- bootstrap ----------

async function init() {
  showLoading("Loading reveal-mask database (2.6 MB)…", 0);
  const [codesRes, countriesRes, openersRes, masksRes] = await Promise.all([
    fetch("data/codes.json").then(r => r.json()),
    fetch("data/countries.json").then(r => r.json()),
    fetch("data/openers.json").then(r => r.json()),
    fetch("data/masks_sz.bin").then(r => r.arrayBuffer()),
  ]);
  CODES = codesRes;
  COUNTRIES = countriesRes;
  OPENERS = openersRes;
  MASKS = unpackBits(new Uint8Array(masksRes), CODES.length * P);
  showLoading("Fetching 197 flag images (cached after first load)…", 5);
  FLAG_RGB = new Array(CODES.length);
  let done = 0;
  await Promise.all(CODES.map(async (code, i) => {
    FLAG_RGB[i] = await loadFlag(code);
    done++;
    showLoading(`Loaded ${done}/${CODES.length} flags…`, 5 + 95 * done / CODES.length);
  }));
  FLAGS_LOADED = CODES.length;
  SOLVE_ENABLED = true;
  // Restore opener preference (if any)
  const saved = localStorage.getItem("flagle_opener");
  if (saved && CODES.includes(saved) && saved !== DEFAULT_OPENER) {
    setOpener(saved);
  }
  setupOpenerPicker();
  hideLoading();
  setupDropzone();
  setupPaste();
}

function unpackBits(packed, totalBits) {
  const out = new Uint8Array(totalBits);
  for (let i = 0; i < totalBits; i++) {
    const byte = packed[i >> 3];
    out[i] = (byte >> (7 - (i & 7))) & 1;
  }
  return out;
}

async function loadFlag(code) {
  const img = await new Promise((resolve, reject) => {
    const im = new Image();
    im.crossOrigin = "anonymous";
    im.onload = () => resolve(im);
    im.onerror = () => reject(new Error(`Failed to load ${code}`));
    im.src = FLAG_URL(code);
  });
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const ctx = c.getContext("2d");
  ctx.drawImage(img, 0, 0, W, H);
  return ctx.getImageData(0, 0, W, H).data; // RGBA Uint8ClampedArray
}

// ---------- opener picker ----------

function setupOpenerPicker() {
  const sel = $("opener-select");
  sel.innerHTML = "";
  // Group: ranked (unique) first, then non-unique alphabetically
  const ranked = OPENERS.filter(o => o.unique);
  const unranked = OPENERS.filter(o => !o.unique);
  const optGroupRanked = document.createElement("optgroup");
  optGroupRanked.label = `1-guess lock-in (${ranked.length} openers)`;
  for (const o of ranked) {
    const opt = document.createElement("option");
    opt.value = o.code;
    opt.textContent = `#${o.rank} — ${o.name} (${o.code.toUpperCase()})  · margin ${o.min_hamming}px`;
    optGroupRanked.appendChild(opt);
  }
  sel.appendChild(optGroupRanked);
  const optGroupOther = document.createElement("optgroup");
  optGroupOther.label = `Not unique — collisions exist (${unranked.length})`;
  for (const o of unranked) {
    const opt = document.createElement("option");
    opt.value = o.code;
    opt.textContent = `${o.name} (${o.code.toUpperCase()})  · best-effort only`;
    optGroupOther.appendChild(opt);
  }
  sel.appendChild(optGroupOther);
  sel.value = CURRENT_OPENER;
  updateOpenerRankBadge();
  sel.addEventListener("change", () => setOpener(sel.value));
}

function updateOpenerRankBadge() {
  const o = OPENERS.find(x => x.code === CURRENT_OPENER);
  const badge = $("opener-rank");
  if (!o) { badge.textContent = ""; return; }
  if (o.unique) {
    badge.textContent = `Rank #${o.rank} of ${OPENERS.filter(x => x.unique).length}`;
    badge.classList.remove("bad");
  } else {
    badge.textContent = `Not unique — answers may be ambiguous`;
    badge.classList.add("bad");
  }
}

function setOpener(code) {
  if (code === CURRENT_OPENER) return;
  CURRENT_OPENER = code;
  localStorage.setItem("flagle_opener", code);
  // Recompute masks client-side using the Flagle rule
  recomputeMasks();
  updateOpenerRankBadge();
  $("opener-select").value = code;
  // If a result was on screen, re-solve with the new opener
  if (window.__lastInput) {
    const r = solve(window.__lastInput.data, window.__lastInput.bg);
    drawReconstruction(r.bestIdx, window.__lastInput.bg);
    renderResult(r);
  }
}

function recomputeMasks() {
  const openerIdx = CODES.indexOf(CURRENT_OPENER);
  if (openerIdx < 0) return;
  const opener = FLAG_RGB[openerIdx];
  const N = CODES.length;
  MASKS = new Uint8Array(N * P);
  for (let n = 0; n < N; n++) {
    const flag = FLAG_RGB[n];
    const off = n * P;
    for (let p = 0; p < P; p++) {
      const i = p * 4;
      const dr = opener[i] - flag[i];
      const dg = opener[i + 1] - flag[i + 1];
      const db = opener[i + 2] - flag[i + 2];
      const dist2 = dr * dr + dg * dg + db * db;
      const alphaOk = opener[i + 3] > ALPHA_HI && flag[i + 3] > ALPHA_HI;
      MASKS[off + p] = (dist2 < THRESHOLD_DIST_SQ && alphaOk) ? 1 : 0;
    }
  }
}

// ---------- UI loading state ----------

function showLoading(msg, pct) {
  $("loading").classList.remove("hidden");
  $("loading-msg").textContent = msg;
  $("loading-bar").value = pct;
}
function hideLoading() { $("loading").classList.add("hidden"); }

// ---------- input handlers ----------

function setupDropzone() {
  const z = $("drop-zone");
  z.addEventListener("click", () => $("file").click());
  $("file").addEventListener("change", e => {
    if (e.target.files[0]) handleImageFile(e.target.files[0]);
  });
  ["dragenter", "dragover"].forEach(ev => z.addEventListener(ev, e => {
    e.preventDefault(); z.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach(ev => z.addEventListener(ev, e => {
    e.preventDefault(); z.classList.remove("dragover");
  }));
  z.addEventListener("drop", e => {
    const f = e.dataTransfer.files[0];
    if (f) handleImageFile(f);
  });
}

function setupPaste() {
  document.addEventListener("paste", e => {
    for (const item of e.clipboardData.items) {
      if (item.type.startsWith("image/")) {
        handleImageFile(item.getAsFile());
        e.preventDefault();
        return;
      }
    }
  });
}

async function handleImageFile(file) {
  if (!SOLVE_ENABLED) { alert("Database still loading…"); return; }
  const img = await new Promise((resolve, reject) => {
    const im = new Image();
    im.onload = () => resolve(im);
    im.onerror = reject;
    im.src = URL.createObjectURL(file);
  });
  const { cropped, bg } = preprocess(img);
  $("input-canvas").getContext("2d").putImageData(cropped, 0, 0);
  $("preview").classList.remove("hidden");
  window.__lastInput = { data: cropped.data, bg };
  const result = solve(cropped.data, bg);
  drawReconstruction(result.bestIdx, bg);
  renderResult(result);
}

// ---------- preprocessing ----------

function preprocess(img) {
  // 1. Draw to large canvas at native size
  const c = document.createElement("canvas");
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  c.getContext("2d").drawImage(img, 0, 0);
  const full = c.getContext("2d").getImageData(0, 0, c.width, c.height);
  // 2. Detect bg = border mode color
  const bg = borderMode(full);
  // 3. Find bbox of non-bg pixels. With sparse reveal masks the bbox can be
  //    much narrower than the real 400x267 game canvas, so we MUST NOT just
  //    stretch it — that destroys the flag's 3:2 aspect ratio and the MLE
  //    template match will pick the wrong country (e.g. Chad vs Romania).
  let { x0, y0, x1, y1 } = bboxNonBg(full, bg, 20);
  let bw = x1 - x0, bh = y1 - y0;
  const targetAspect = W / H; // 400/267 ≈ 1.498
  if (bw / bh > targetAspect) {
    // bbox is too wide: expand height symmetrically with bg padding
    const newH = bw / targetAspect;
    const pad = (newH - bh) / 2;
    y0 -= pad; y1 += pad; bh = newH;
  } else {
    // bbox is too tall: expand width symmetrically
    const newW = bh * targetAspect;
    const pad = (newW - bw) / 2;
    x0 -= pad; x1 += pad; bw = newW;
  }
  // 4. Draw into W×H canvas with bg fill for any out-of-source area
  const cropC = document.createElement("canvas");
  cropC.width = W; cropC.height = H;
  const cctx = cropC.getContext("2d");
  cctx.fillStyle = `rgb(${bg[0]},${bg[1]},${bg[2]})`;
  cctx.fillRect(0, 0, W, H);
  // Compute the source rect clipped to the image and the matching dest rect.
  const sx = Math.max(0, x0);
  const sy = Math.max(0, y0);
  const sw = Math.min(c.width, x1) - sx;
  const sh = Math.min(c.height, y1) - sy;
  if (sw > 0 && sh > 0) {
    const scaleX = W / bw, scaleY = H / bh;
    const dx = (sx - x0) * scaleX;
    const dy = (sy - y0) * scaleY;
    const dw = sw * scaleX;
    const dh = sh * scaleY;
    cctx.drawImage(c, sx, sy, sw, sh, dx, dy, dw, dh);
  }
  return { cropped: cctx.getImageData(0, 0, W, H), bg, bbox: { x0, y0, x1, y1 } };
}

function borderMode(img) {
  const { data, width: w, height: h } = img;
  const thick = 4;
  const counts = new Map();
  const sample = (x, y) => {
    const i = (y * w + x) * 4;
    const k = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2];
    counts.set(k, (counts.get(k) || 0) + 1);
  };
  for (let y = 0; y < thick; y++) for (let x = 0; x < w; x++) { sample(x, y); sample(x, h - 1 - y); }
  for (let x = 0; x < thick; x++) for (let y = 0; y < h; y++) { sample(x, y); sample(w - 1 - x, y); }
  let best = 0, bestC = 0;
  for (const [k, c] of counts) if (c > bestC) { bestC = c; best = k; }
  return [(best >> 16) & 0xff, (best >> 8) & 0xff, best & 0xff];
}

function bboxNonBg(img, bg, tol) {
  const { data, width: w, height: h } = img;
  let x0 = w, y0 = h, x1 = 0, y1 = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      const d = Math.max(
        Math.abs(data[i] - bg[0]),
        Math.abs(data[i + 1] - bg[1]),
        Math.abs(data[i + 2] - bg[2]),
      );
      if (d > tol) {
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    }
  }
  if (x1 < x0 || y1 < y0) return { x0: 0, y0: 0, x1: w, y1: h };
  return { x0, y0, x1: x1 + 1, y1: y1 + 1 };
}

// ---------- solver ----------

function solve(targetRGBA, bg) {
  // Precompute per-pixel err vs bg: sum((target - bg)^2) over RGB
  const errBg = new Float32Array(P);
  let sumErrBg = 0;
  for (let p = 0; p < P; p++) {
    const i = p * 4;
    const dr = targetRGBA[i] - bg[0];
    const dg = targetRGBA[i + 1] - bg[1];
    const db = targetRGBA[i + 2] - bg[2];
    const e = dr * dr + dg * dg + db * db;
    errBg[p] = e;
    sumErrBg += e;
  }
  const N = CODES.length;
  const scores = new Float64Array(N);
  for (let n = 0; n < N; n++) {
    const flag = FLAG_RGB[n];
    const maskOffset = n * P;
    let delta = 0;
    for (let p = 0; p < P; p++) {
      if (MASKS[maskOffset + p]) {
        const i = p * 4;
        const dr = flag[i] - targetRGBA[i];
        const dg = flag[i + 1] - targetRGBA[i + 1];
        const db = flag[i + 2] - targetRGBA[i + 2];
        delta += dr * dr + dg * dg + db * db - errBg[p];
      }
    }
    scores[n] = sumErrBg + delta;
  }
  const ranked = Array.from({ length: N }, (_, i) => i)
    .sort((a, b) => scores[a] - scores[b]);
  const best = ranked[0];
  const second = ranked[1];
  const denom = P * 3;
  return {
    bestIdx: best,
    bestCode: CODES[best],
    score: scores[best] / denom,
    runnerUp: CODES[second],
    margin: (scores[second] - scores[best]) / denom,
    ranked: ranked.slice(0, 10),
    scores: ranked.slice(0, 10).map(i => ({ code: CODES[i], score: scores[i] / denom })),
  };
}

function drawReconstruction(idx, bg) {
  const out = new ImageData(W, H);
  const flag = FLAG_RGB[idx];
  for (let p = 0; p < P; p++) {
    const i = p * 4;
    if (MASKS[idx * P + p]) {
      out.data[i] = flag[i];
      out.data[i + 1] = flag[i + 1];
      out.data[i + 2] = flag[i + 2];
    } else {
      out.data[i] = bg[0];
      out.data[i + 1] = bg[1];
      out.data[i + 2] = bg[2];
    }
    out.data[i + 3] = 255;
  }
  $("recon-canvas").getContext("2d").putImageData(out, 0, 0);
}

// ---------- result rendering ----------

function getMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

document.addEventListener("change", e => {
  if (e.target.name === "mode" && window.__lastResult) {
    renderResult(window.__lastResult);
  }
});

function renderResult(result) {
  window.__lastResult = result;
  const meta = COUNTRIES[result.bestCode] || { name: result.bestCode.toUpperCase() };
  const confClass = result.margin > 50 ? "high" : result.margin > 10 ? "" : "low";
  if (getMode() === "reveal") {
    $("result").innerHTML = `
      <h2>Answer</h2>
      <div class="flag-row">
        <img src="${FLAG_URL(result.bestCode)}" alt="${meta.name}">
        <div class="info">
          <p class="name">${meta.name}</p>
          <p class="sub">
            <span class="continent-badge">${meta.region}</span>
            ${meta.subregion}
          </p>
        </div>
      </div>
      <p class="confidence ${confClass}">
        Code: <b>${result.bestCode.toUpperCase()}</b> &middot;
        Score: ${result.score.toFixed(1)} &middot;
        Margin to runner-up (${result.runnerUp.toUpperCase()}): ${result.margin.toFixed(1)}
      </p>
      <details class="top-candidates">
        <summary>Top 5 candidates (click to expand)</summary>
        <ol>
          ${result.scores.slice(0, 5).map(s => {
            const m = COUNTRIES[s.code] || { name: s.code.toUpperCase() };
            return `<li>
              <img src="${FLAG_URL(s.code)}" alt="" style="height:18px;vertical-align:middle;margin-right:6px">
              <b>${s.code.toUpperCase()}</b> ${m.name} — score ${s.score.toFixed(2)}
            </li>`;
          }).join("")}
        </ol>
        <p style="font-size:0.8em;opacity:0.7">Wrong answer? The crop may be off. Try a tighter screenshot of just the game canvas.</p>
      </details>
    `;
  } else {
    renderHelperMode(result);
  }
  $("result").classList.remove("hidden");
}

// ---------- helper mode (progressive hints) ----------

function renderHelperMode(result) {
  const meta = COUNTRIES[result.bestCode];
  const stage = window.__helperStage || 0;
  let html = `<h2>Helper mode</h2>`;

  // Stage 0: continent only
  html += `
    <div class="hint-step">
      <h3>Hint 1 &middot; Continent</h3>
      <div class="value">${meta.region}</div>
    </div>`;

  if (stage >= 1) {
    html += `
      <div class="hint-step">
        <h3>Hint 2 &middot; Subregion</h3>
        <div class="value">${meta.subregion || "(unspecified)"}</div>
      </div>`;
  }
  if (stage >= 2) {
    html += `
      <div class="hint-step">
        <h3>Hint 3 &middot; First letter</h3>
        <div class="value">${meta.name[0]}…</div>
      </div>`;
  }
  if (stage >= 3) {
    html += `
      <div class="hint-step">
        <h3>Answer revealed</h3>
        <div class="flag-row">
          <img src="${FLAG_URL(result.bestCode)}" alt="${meta.name}">
          <div class="info">
            <p class="name">${meta.name}</p>
            <p class="sub">${meta.official}</p>
          </div>
        </div>
      </div>`;
  } else {
    // Show clickable list of candidates from the current narrowed pool
    let pool = Object.entries(COUNTRIES).filter(([c, m]) => {
      if (stage === 0) return m.region === meta.region;
      if (stage === 1) return m.subregion === meta.subregion;
      if (stage === 2) return m.subregion === meta.subregion
        && m.name[0].toLowerCase() === meta.name[0].toLowerCase();
      return false;
    });
    pool.sort((a, b) => a[1].name.localeCompare(b[1].name));
    html += `<p>Pick the country you think it is:</p><div class="country-grid">`;
    for (const [code, m] of pool) {
      html += `<button class="country-btn" data-code="${code}">
        <img src="${FLAG_URL(code)}" alt="">
        <span>${m.name}</span>
      </button>`;
    }
    html += `</div>`;
    html += `<button class="btn secondary" id="give-up">Show next hint</button>`;
  }

  if (stage > 0 || (window.__wrongPicks && window.__wrongPicks.length)) {
    html += `<button class="btn secondary" id="restart-helper" style="margin-left:8px">Start over</button>`;
  }

  $("result").innerHTML = html;

  // wire buttons
  $("result").querySelectorAll(".country-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const code = btn.dataset.code;
      if (code === result.bestCode) {
        btn.classList.add("correct");
        setTimeout(() => {
          window.__helperStage = 3;
          renderHelperMode(result);
        }, 500);
      } else {
        btn.classList.add("wrong");
        btn.disabled = true;
        window.__wrongPicks = window.__wrongPicks || [];
        window.__wrongPicks.push(code);
        // Advance to next hint after wrong guess
        setTimeout(() => {
          window.__helperStage = Math.min(3, (window.__helperStage || 0) + 1);
          renderHelperMode(result);
        }, 600);
      }
    });
  });
  const giveUp = $("give-up");
  if (giveUp) giveUp.addEventListener("click", () => {
    window.__helperStage = Math.min(3, (window.__helperStage || 0) + 1);
    renderHelperMode(result);
  });
  const restart = $("restart-helper");
  if (restart) restart.addEventListener("click", () => {
    window.__helperStage = 0;
    window.__wrongPicks = [];
    renderHelperMode(result);
  });
}

// reset helper stage on new image
const _origHandle = handleImageFile;
handleImageFile = async function(f) {
  window.__helperStage = 0;
  window.__wrongPicks = [];
  return _origHandle(f);
};

init().catch(err => {
  console.error(err);
  $("loading-msg").textContent = "Error loading database: " + err.message;
});
