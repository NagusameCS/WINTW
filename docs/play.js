// Flagle — true implementation.
//
// Pixel-perfect 400×267 canvas. No clipping, no scaling distortion.
// Match rule (verbatim from flagle/flagle_exact.py):
//   per pixel: dist² = (dr)² + (dg)² + (db)²
//   reveal iff dist² < (18/100)² * (3*255²)  AND  guess.alpha > 127  AND  sol.alpha > 127

const W = 400, H = 267, P = W * H;
const MAX_GUESSES = 6;
const FLAG_URL = (code) => `https://flagcdn.com/w320/${code}.png`;
const THRESHOLD_DIST_SQ = (18 / 100) ** 2 * (3 * 255 * 255);
const ALPHA_HI = 127;

const $ = (id) => document.getElementById(id);

let CODES = [];
let COUNTRIES = {};
let FLAG_RGBA = {};       // {code: Uint8ClampedArray(P*4)}
let SOLUTION_CODE = null;
let SOLUTION_RGBA = null;
let SOLUTION_ALPHA_COUNT = 0;
let REVEALED = null;      // Uint8Array(P) — accumulated reveal mask
let GUESSES = [];         // [{code, pct}, ...]

const DIR_ARROWS = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"];

async function init() {
  const [codesRes, countriesRes] = await Promise.all([
    fetch("data/codes.json").then(r => r.json()),
    fetch("data/countries.json").then(r => r.json()),
  ]);
  CODES = codesRes;
  COUNTRIES = countriesRes;
  showLoading("Fetching 197 flag images (cached after first load)…", 0);
  let done = 0;
  await Promise.all(CODES.map(async (code) => {
    FLAG_RGBA[code] = await loadFlag(code);
    done++;
    showLoading(`Loaded ${done}/${CODES.length} flags…`, 100 * done / CODES.length);
  }));
  hideLoading();
  $("game").classList.remove("hidden");
  $("guess-max").textContent = MAX_GUESSES;
  newGame();
  setupForm();
}

function showLoading(msg, pct) {
  $("loading").classList.remove("hidden");
  $("loading-msg").textContent = msg;
  $("loading-bar").value = pct;
}
function hideLoading() { $("loading").classList.add("hidden"); }

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
  return ctx.getImageData(0, 0, W, H).data;
}

// ---------- game state ----------

function newGame() {
  SOLUTION_CODE = CODES[Math.floor(Math.random() * CODES.length)];
  SOLUTION_RGBA = FLAG_RGBA[SOLUTION_CODE];
  SOLUTION_ALPHA_COUNT = 0;
  for (let p = 0; p < P; p++) {
    if (SOLUTION_RGBA[p * 4 + 3] > ALPHA_HI) SOLUTION_ALPHA_COUNT++;
  }
  REVEALED = new Uint8Array(P);
  GUESSES = [];
  $("guess-log").innerHTML = "";
  $("end-screen").classList.add("hidden");
  $("end-screen").classList.remove("win", "lose");
  $("guess-input").disabled = false;
  $("guess-input").value = "";
  $("guess-input").focus();
  updateGuessNum();
  drawCanvas();
  updatePct();
}

function computeRevealMask(guessRGBA) {
  const out = new Uint8Array(P);
  for (let p = 0; p < P; p++) {
    const i = p * 4;
    const dr = guessRGBA[i] - SOLUTION_RGBA[i];
    const dg = guessRGBA[i + 1] - SOLUTION_RGBA[i + 1];
    const db = guessRGBA[i + 2] - SOLUTION_RGBA[i + 2];
    const dist2 = dr * dr + dg * dg + db * db;
    const alphaOk = guessRGBA[i + 3] > ALPHA_HI && SOLUTION_RGBA[i + 3] > ALPHA_HI;
    if (dist2 < THRESHOLD_DIST_SQ && alphaOk) out[p] = 1;
  }
  return out;
}

function drawCanvas() {
  const canvas = $("play-canvas");
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(W, H);
  // Fill with bg (#0f1419) for unrevealed pixels
  for (let p = 0; p < P; p++) {
    const i = p * 4;
    if (REVEALED[p]) {
      img.data[i] = SOLUTION_RGBA[i];
      img.data[i + 1] = SOLUTION_RGBA[i + 1];
      img.data[i + 2] = SOLUTION_RGBA[i + 2];
      img.data[i + 3] = 255;
    } else {
      img.data[i] = 0x0f;
      img.data[i + 1] = 0x14;
      img.data[i + 2] = 0x19;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

function updatePct() {
  let n = 0;
  for (let p = 0; p < P; p++) if (REVEALED[p]) n++;
  const pct = SOLUTION_ALPHA_COUNT > 0 ? (100 * n / SOLUTION_ALPHA_COUNT) : 0;
  $("overlap-pct").textContent = pct.toFixed(1) + "%";
  return pct;
}

function updateGuessNum() {
  $("guess-num").textContent = Math.min(GUESSES.length + 1, MAX_GUESSES);
}

// ---------- distance/direction (great-circle) ----------

function bearingArrow(fromCode, toCode) {
  const a = COUNTRIES[fromCode], b = COUNTRIES[toCode];
  if (!a || !b || a.lat === undefined || b.lat === undefined) return "";
  const φ1 = a.lat * Math.PI / 180, φ2 = b.lat * Math.PI / 180;
  const Δλ = (b.lng - a.lng) * Math.PI / 180;
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  let θ = Math.atan2(y, x) * 180 / Math.PI;
  θ = (θ + 360) % 360;
  // bucket to 8 directions, 0=N,1=NE,2=E,...
  const idx = Math.round(θ / 45) % 8;
  return DIR_ARROWS[idx];
}

function distanceKm(fromCode, toCode) {
  const a = COUNTRIES[fromCode], b = COUNTRIES[toCode];
  if (!a || !b || a.lat === undefined || b.lat === undefined) return null;
  const R = 6371;
  const φ1 = a.lat * Math.PI / 180, φ2 = b.lat * Math.PI / 180;
  const Δφ = (b.lat - a.lat) * Math.PI / 180;
  const Δλ = (b.lng - a.lng) * Math.PI / 180;
  const h = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2;
  return Math.round(2 * R * Math.asin(Math.sqrt(h)));
}

// ---------- guess submission ----------

function submitGuess(code) {
  if (!FLAG_RGBA[code]) return;
  if (GUESSES.find(g => g.code === code)) return;
  const guessRGBA = FLAG_RGBA[code];
  const mask = computeRevealMask(guessRGBA);
  for (let p = 0; p < P; p++) if (mask[p]) REVEALED[p] = 1;
  let n = 0;
  for (let p = 0; p < P; p++) if (mask[p]) n++;
  const pct = SOLUTION_ALPHA_COUNT > 0 ? (100 * n / SOLUTION_ALPHA_COUNT) : 0;
  GUESSES.push({ code, pct });
  drawCanvas();
  appendGuessLog(code, pct);
  updatePct();
  updateGuessNum();
  if (code === SOLUTION_CODE) endGame(true);
  else if (GUESSES.length >= MAX_GUESSES) endGame(false);
}

function appendGuessLog(code, pct) {
  const meta = COUNTRIES[code] || { name: code.toUpperCase() };
  const arrow = bearingArrow(code, SOLUTION_CODE);
  const dist = distanceKm(code, SOLUTION_CODE);
  const li = document.createElement("li");
  const correct = code === SOLUTION_CODE;
  li.innerHTML = `
    <img src="${FLAG_URL(code)}" alt="">
    <span>${meta.name}</span>
    ${correct ? "" : `<span class="arrow">${dist !== null ? dist + " km " : ""}${arrow}</span>`}
    <span class="pct">${pct.toFixed(1)}%</span>
  `;
  $("guess-log").appendChild(li);
}

function endGame(won) {
  $("guess-input").disabled = true;
  $("suggestions").classList.add("hidden");
  // Reveal the full flag
  for (let p = 0; p < P; p++) {
    if (SOLUTION_RGBA[p * 4 + 3] > ALPHA_HI) REVEALED[p] = 1;
  }
  drawCanvas();
  updatePct();
  const meta = COUNTRIES[SOLUTION_CODE] || { name: SOLUTION_CODE.toUpperCase() };
  const end = $("end-screen");
  end.classList.remove("hidden");
  end.classList.add(won ? "win" : "lose");
  $("end-title").textContent = won ? "You got it!" : "Out of guesses";
  $("end-body").innerHTML = `
    The flag was <b>${meta.name}</b> (${SOLUTION_CODE.toUpperCase()})
    &middot; ${meta.region || ""}${meta.subregion ? " · " + meta.subregion : ""}
  `;
}

// ---------- input form + autocomplete ----------

function setupForm() {
  const input = $("guess-input");
  const sugg = $("suggestions");
  let activeIdx = -1;

  function renderSuggestions(q) {
    if (!q) { sugg.classList.add("hidden"); return; }
    const ql = q.toLowerCase();
    const used = new Set(GUESSES.map(g => g.code));
    const matches = CODES
      .filter(c => !used.has(c))
      .map(c => ({ code: c, name: (COUNTRIES[c] || {}).name || c.toUpperCase() }))
      .filter(o => o.name.toLowerCase().includes(ql) || o.code.toLowerCase().startsWith(ql))
      .slice(0, 8);
    if (matches.length === 0) { sugg.classList.add("hidden"); return; }
    sugg.innerHTML = matches.map((m, i) =>
      `<div data-code="${m.code}" class="${i === activeIdx ? "active" : ""}">
        <img src="${FLAG_URL(m.code)}" alt=""><span>${m.name}</span>
      </div>`
    ).join("");
    sugg.classList.remove("hidden");
    sugg.querySelectorAll("div").forEach(d => {
      d.addEventListener("mousedown", e => {
        e.preventDefault();
        pickCode(d.dataset.code);
      });
    });
  }

  function pickCode(code) {
    submitGuess(code);
    input.value = "";
    sugg.classList.add("hidden");
    activeIdx = -1;
    if (!input.disabled) input.focus();
  }

  input.addEventListener("input", () => {
    activeIdx = -1;
    renderSuggestions(input.value.trim());
  });
  input.addEventListener("keydown", e => {
    const items = sugg.querySelectorAll("div");
    if (e.key === "ArrowDown" && items.length) {
      activeIdx = (activeIdx + 1) % items.length;
      renderSuggestions(input.value.trim());
      e.preventDefault();
    } else if (e.key === "ArrowUp" && items.length) {
      activeIdx = (activeIdx - 1 + items.length) % items.length;
      renderSuggestions(input.value.trim());
      e.preventDefault();
    } else if (e.key === "Escape") {
      sugg.classList.add("hidden");
    }
  });
  $("guess-form").addEventListener("submit", e => {
    e.preventDefault();
    const items = sugg.querySelectorAll("div");
    if (activeIdx >= 0 && items[activeIdx]) {
      pickCode(items[activeIdx].dataset.code);
      return;
    }
    // resolve text → code
    const q = input.value.trim().toLowerCase();
    if (!q) return;
    const used = new Set(GUESSES.map(g => g.code));
    const exact = CODES.find(c => !used.has(c) && (COUNTRIES[c] || {}).name?.toLowerCase() === q);
    const prefix = CODES.find(c => !used.has(c) && (COUNTRIES[c] || {}).name?.toLowerCase().startsWith(q));
    const codeMatch = CODES.find(c => !used.has(c) && c.toLowerCase() === q);
    const pick = exact || codeMatch || prefix;
    if (pick) pickCode(pick);
  });
  $("play-again").addEventListener("click", newGame);
  document.addEventListener("click", e => {
    if (!$("guess-form").contains(e.target)) sugg.classList.add("hidden");
  });
}

init();
