// Flagle — true implementation, with mode/setting toggles.
//
// Pixel-perfect 400×267 canvas. No clipping, no scaling distortion.
// Match rule (verbatim from flagle/flagle_exact.py):
//   per pixel: dist² = (dr)² + (dg)² + (db)² < (18/100)² * (3*255²)
//                AND  guess.alpha > 127  AND  sol.alpha > 127

const W = 400, H = 267, P = W * H;
const FLAG_URL = (code) => `https://flagcdn.com/w320/${code}.png`;
const THRESHOLD_DIST_SQ = (18 / 100) ** 2 * (3 * 255 * 255);
const ALPHA_HI = 127;
const BG = [0x0f, 0x14, 0x19];
const FADE_MS = 600;
const DIR_ARROWS = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"];

const $ = (id) => document.getElementById(id);

let CODES = [];
let COUNTRIES = {};
let FLAG_RGBA = {};
let SOLUTION_CODE = null;
let SOLUTION_RGBA = null;
let SOLUTION_ALPHA_COUNT = 0;
let REVEALED = null;             // Uint8Array(P) accumulated
let REVEALED_AT = null;          // Float32Array(P) timestamp pixel was revealed
let GUESSES = [];
let MODE = "classic";
let CONTINENT_LOCK = null;
let CANDIDATE_POOL = [];         // codes eligible as solutions for current mode

// settings (persisted)
const SETTINGS = {
  previews: true,
  distance: true,
  fade: true,
  pct: true,
  mode: "classic",
  continent: "Europe",
};

function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem("flagle_play_settings") || "{}");
    Object.assign(SETTINGS, s);
  } catch {}
}
function saveSettings() {
  localStorage.setItem("flagle_play_settings", JSON.stringify(SETTINGS));
}

function modeMaxGuesses(mode) {
  if (mode === "sudden") return 1;
  if (mode === "marathon") return Infinity;
  return 6;
}

function effectivePreviews() {
  if (MODE === "hard") return false;
  return SETTINGS.previews;
}
function effectiveDistance() {
  if (MODE === "hard") return false;
  return SETTINGS.distance;
}
function effectivePct() {
  if (MODE === "blind") return false;
  return SETTINGS.pct;
}

// ---------- bootstrap ----------

async function init() {
  loadSettings();
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
  $("settings").classList.remove("hidden");
  $("game").classList.remove("hidden");
  setupSettingsUI();
  applyModeFromSettings();
  newGame();
  setupForm();
  setupBrowseModal();
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

// ---------- settings UI ----------

function setupSettingsUI() {
  $("opt-previews").checked = SETTINGS.previews;
  $("opt-distance").checked = SETTINGS.distance;
  $("opt-fade").checked = SETTINGS.fade;
  $("opt-pct").checked = SETTINGS.pct;
  $("mode-select").value = SETTINGS.mode;

  // populate continents
  const conts = [...new Set(Object.values(COUNTRIES).map(c => c.region).filter(Boolean))].sort();
  $("continent-select").innerHTML = conts.map(c =>
    `<option value="${c}" ${c === SETTINGS.continent ? "selected" : ""}>${c}</option>`
  ).join("");

  $("opt-previews").addEventListener("change", e => { SETTINGS.previews = e.target.checked; saveSettings(); refreshLog(); });
  $("opt-distance").addEventListener("change", e => { SETTINGS.distance = e.target.checked; saveSettings(); refreshLog(); });
  $("opt-fade").addEventListener("change", e => { SETTINGS.fade = e.target.checked; saveSettings(); });
  $("opt-pct").addEventListener("change", e => { SETTINGS.pct = e.target.checked; saveSettings(); updatePct(); });
  $("mode-select").addEventListener("change", e => {
    SETTINGS.mode = e.target.value;
    saveSettings();
    applyModeFromSettings();
    newGame();
  });
  $("continent-select").addEventListener("change", e => {
    SETTINGS.continent = e.target.value;
    saveSettings();
    if (MODE === "continent") { applyModeFromSettings(); newGame(); }
  });
}

function applyModeFromSettings() {
  MODE = SETTINGS.mode;
  $("continent-wrap").hidden = MODE !== "continent";
  CONTINENT_LOCK = MODE === "continent" ? SETTINGS.continent : null;
  CANDIDATE_POOL = CODES.filter(c => {
    if (CONTINENT_LOCK) return (COUNTRIES[c] || {}).region === CONTINENT_LOCK;
    return true;
  });
  if (CANDIDATE_POOL.length === 0) CANDIDATE_POOL = CODES.slice();
  // update guess-max display
  const max = modeMaxGuesses(MODE);
  $("guess-max").textContent = max === Infinity ? "∞" : max;
  // toggle pct visibility on game shell
  document.querySelector(".pct-block").classList.toggle("hidden-blind", !effectivePct());
}

// ---------- game state ----------

function newGame() {
  SOLUTION_CODE = CANDIDATE_POOL[Math.floor(Math.random() * CANDIDATE_POOL.length)];
  SOLUTION_RGBA = FLAG_RGBA[SOLUTION_CODE];
  SOLUTION_ALPHA_COUNT = 0;
  for (let p = 0; p < P; p++) {
    if (SOLUTION_RGBA[p * 4 + 3] > ALPHA_HI) SOLUTION_ALPHA_COUNT++;
  }
  REVEALED = new Uint8Array(P);
  REVEALED_AT = new Float32Array(P);
  GUESSES = [];
  $("guess-log").innerHTML = "";
  $("end-screen").classList.add("hidden");
  $("end-screen").classList.remove("win", "lose");
  $("guess-input").disabled = false;
  $("guess-input").value = "";
  $("guess-input").focus();
  updateGuessNum();
  drawCanvas(performance.now());
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

let _rafPending = false;
function scheduleDraw() {
  if (_rafPending) return;
  _rafPending = true;
  requestAnimationFrame(t => {
    _rafPending = false;
    drawCanvas(t);
    // keep animating if any pixel is still in fade window
    if (SETTINGS.fade) {
      for (let p = 0; p < P; p++) {
        if (REVEALED[p] && t - REVEALED_AT[p] < FADE_MS) { scheduleDraw(); break; }
      }
    }
  });
}

function drawCanvas(now) {
  const canvas = $("play-canvas");
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(W, H);
  const fade = SETTINGS.fade;
  for (let p = 0; p < P; p++) {
    const i = p * 4;
    if (REVEALED[p]) {
      let a = 1;
      if (fade) {
        const t = (now - REVEALED_AT[p]) / FADE_MS;
        a = t < 0 ? 0 : t > 1 ? 1 : t;
        // ease-out cubic
        a = 1 - Math.pow(1 - a, 3);
      }
      img.data[i] = Math.round(BG[0] * (1 - a) + SOLUTION_RGBA[i] * a);
      img.data[i + 1] = Math.round(BG[1] * (1 - a) + SOLUTION_RGBA[i + 1] * a);
      img.data[i + 2] = Math.round(BG[2] * (1 - a) + SOLUTION_RGBA[i + 2] * a);
      img.data[i + 3] = 255;
    } else {
      img.data[i] = BG[0];
      img.data[i + 1] = BG[1];
      img.data[i + 2] = BG[2];
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

function updatePct() {
  let n = 0;
  for (let p = 0; p < P; p++) if (REVEALED[p]) n++;
  const pct = SOLUTION_ALPHA_COUNT > 0 ? (100 * n / SOLUTION_ALPHA_COUNT) : 0;
  if (effectivePct()) {
    $("overlap-pct").textContent = pct.toFixed(1) + "%";
    document.querySelector(".pct-block").classList.remove("hidden-blind");
  } else {
    document.querySelector(".pct-block").classList.add("hidden-blind");
  }
  return pct;
}

function updateGuessNum() {
  const max = modeMaxGuesses(MODE);
  $("guess-num").textContent = max === Infinity ? GUESSES.length + 1
    : Math.min(GUESSES.length + 1, max);
}

// ---------- distance/direction ----------

function bearingArrow(fromCode, toCode) {
  const a = COUNTRIES[fromCode], b = COUNTRIES[toCode];
  if (!a || !b || a.lat == null || b.lat == null) return "";
  const φ1 = a.lat * Math.PI / 180, φ2 = b.lat * Math.PI / 180;
  const Δλ = (b.lng - a.lng) * Math.PI / 180;
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  let θ = Math.atan2(y, x) * 180 / Math.PI;
  θ = (θ + 360) % 360;
  const idx = Math.round(θ / 45) % 8;
  return DIR_ARROWS[idx];
}

function distanceKm(fromCode, toCode) {
  const a = COUNTRIES[fromCode], b = COUNTRIES[toCode];
  if (!a || !b || a.lat == null || b.lat == null) return null;
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
  const now = performance.now();
  let n = 0;
  for (let p = 0; p < P; p++) {
    if (mask[p]) {
      n++;
      if (!REVEALED[p]) {
        REVEALED[p] = 1;
        REVEALED_AT[p] = now;
      }
    }
  }
  const pct = SOLUTION_ALPHA_COUNT > 0 ? (100 * n / SOLUTION_ALPHA_COUNT) : 0;
  GUESSES.push({ code, pct });
  scheduleDraw();
  appendGuessLog(code, pct);
  updatePct();
  updateGuessNum();
  const max = modeMaxGuesses(MODE);
  if (code === SOLUTION_CODE) endGame(true);
  else if (max !== Infinity && GUESSES.length >= max) endGame(false);
}

function logRowHTML(code, pct) {
  const meta = COUNTRIES[code] || { name: code.toUpperCase() };
  const arrow = effectiveDistance() ? bearingArrow(code, SOLUTION_CODE) : "";
  const dist = effectiveDistance() ? distanceKm(code, SOLUTION_CODE) : null;
  const correct = code === SOLUTION_CODE;
  const thumb = effectivePreviews()
    ? `<img src="${FLAG_URL(code)}" alt="">`
    : "";
  const arrowHTML = correct || !effectiveDistance()
    ? ""
    : `<span class="arrow">${dist !== null ? dist + " km " : ""}${arrow}</span>`;
  const pctHTML = effectivePct()
    ? `<span class="pct">${pct.toFixed(1)}%</span>`
    : `<span class="pct">${correct ? "✓" : ""}</span>`;
  return `${thumb}<span>${meta.name}</span>${arrowHTML}${pctHTML}`;
}

function appendGuessLog(code, pct) {
  const li = document.createElement("li");
  li.dataset.code = code;
  li.dataset.pct = pct;
  li.innerHTML = logRowHTML(code, pct);
  $("guess-log").appendChild(li);
}

function refreshLog() {
  // re-render existing log entries when settings change mid-game
  document.querySelectorAll("#guess-log li").forEach(li => {
    li.innerHTML = logRowHTML(li.dataset.code, parseFloat(li.dataset.pct));
  });
}

function endGame(won) {
  $("guess-input").disabled = true;
  $("suggestions").classList.add("hidden");
  const now = performance.now();
  for (let p = 0; p < P; p++) {
    if (SOLUTION_RGBA[p * 4 + 3] > ALPHA_HI && !REVEALED[p]) {
      REVEALED[p] = 1;
      REVEALED_AT[p] = now;
    }
  }
  scheduleDraw();
  // After fade settles, show end screen — but show immediately too
  updatePct();
  const meta = COUNTRIES[SOLUTION_CODE] || { name: SOLUTION_CODE.toUpperCase() };
  const end = $("end-screen");
  end.classList.remove("hidden");
  end.classList.add(won ? "win" : "lose");
  $("end-title").textContent = won ? "You got it!" : "Out of guesses";
  $("end-body").innerHTML = `
    The flag was <b>${meta.name}</b> (${SOLUTION_CODE.toUpperCase()})
    &middot; ${meta.region || ""}${meta.subregion ? " · " + meta.subregion : ""}
    ${MODE === "continent" ? ` · pool: ${CONTINENT_LOCK}` : ""}
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
    const showThumbs = effectivePreviews();
    sugg.innerHTML = matches.map((m, i) =>
      `<div data-code="${m.code}" class="${i === activeIdx ? "active" : ""}">
        ${showThumbs ? `<img src="${FLAG_URL(m.code)}" alt="">` : ""}
        <span>${m.name}</span>
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

// ---------- browse-all-countries modal ----------

function setupBrowseModal() {
  const modal = $("browse-modal");
  const list = $("browse-list");
  const search = $("browse-search");

  function render() {
    const q = (search.value || "").trim().toLowerCase();
    const used = new Set(GUESSES.map(g => g.code));
    const showThumbs = effectivePreviews();
    const sorted = CODES
      .map(c => ({ code: c, name: (COUNTRIES[c] || {}).name || c.toUpperCase() }))
      .sort((a, b) => a.name.localeCompare(b.name))
      .filter(o => !q || o.name.toLowerCase().includes(q) || o.code.startsWith(q));
    list.innerHTML = sorted.map(o => `
      <div class="country-row ${used.has(o.code) ? "used" : ""} ${showThumbs ? "" : "no-thumb"}"
           data-code="${o.code}">
        <img src="${FLAG_URL(o.code)}" alt="">
        <span>${o.name}</span>
      </div>
    `).join("");
    list.querySelectorAll(".country-row").forEach(row => {
      if (row.classList.contains("used")) return;
      row.addEventListener("click", () => {
        submitGuess(row.dataset.code);
        if ($("guess-input").disabled || GUESSES.find(g => g.code === SOLUTION_CODE)) {
          close();
        } else {
          render();
        }
      });
    });
  }

  function open() {
    search.value = "";
    render();
    modal.classList.remove("hidden");
    setTimeout(() => search.focus(), 50);
  }
  function close() { modal.classList.add("hidden"); }

  $("browse-btn").addEventListener("click", open);
  $("browse-close").addEventListener("click", close);
  modal.querySelector(".modal-backdrop").addEventListener("click", close);
  search.addEventListener("input", render);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) close();
  });
}

init();
