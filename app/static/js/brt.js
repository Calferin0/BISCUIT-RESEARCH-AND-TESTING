// BRT: progressive enhancement only. Every page works without this file.
"use strict";

// Celebration: a shower of biscuit crumbs after a "celebrate" flash message.
function crumbShower() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const bits = ["🍪", "🍪", "🍪", "🟤", "✨"];
  for (let i = 0; i < 38; i++) {
    const s = document.createElement("span");
    s.className = "crumb";
    s.textContent = bits[i % bits.length];
    s.style.left = Math.random() * 100 + "vw";
    s.style.fontSize = 12 + Math.random() * 24 + "px";
    s.style.setProperty("--delay", Math.random() * 0.7 + "s");
    s.style.setProperty("--dur", 1.8 + Math.random() * 1.7 + "s");
    s.style.setProperty("--drift", Math.random() * 140 - 70 + "px");
    s.style.setProperty("--spin", Math.random() * 900 - 450 + "deg");
    s.addEventListener("animationend", () => s.remove());
    document.body.appendChild(s);
  }
}
if (document.body.hasAttribute("data-celebrate")) crumbShower();

// Rating form: live provisional score while tapping biscuits.
const rateForm = document.querySelector("[data-rate-form]");
if (rateForm) {
  const out = rateForm.querySelector("[data-preview]");
  const purist = rateForm.querySelector("[data-purist]");
  const skippable = [...rateForm.querySelectorAll("fieldset.rate.skippable input[type=radio]")];
  const update = () => {
    const dry = purist && purist.checked;
    // Dry Land Purists don't have to score the dunk pair: drop `required` so the browser lets them submit.
    skippable.forEach((i) => { i.required = !dry; });
    const live = dry ? "fieldset.rate:not(.skippable)" : "fieldset.rate";
    const total = rateForm.querySelectorAll(live).length;
    const vals = [...rateForm.querySelectorAll(`${live} input[type=radio]:checked`)].map((i) => Number(i.value));
    if (!vals.length) { out.textContent = ""; return; }
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    out.textContent = `Provisional score: ${avg.toFixed(1)} / 5` +
      (vals.length < total ? `  (${total - vals.length} categor${total - vals.length === 1 ? "y" : "ies"} to go)` : "  ✓ ready to file");
  };
  rateForm.addEventListener("change", update);
  update();
}

// Photo picker: search Open Food Facts via our server, tap a pack shot to choose it.
// Built with textContent/attributes only (no innerHTML), so product names can't inject markup.
document.querySelectorAll("[data-photo-picker]").forEach((picker) => {
  const form = picker.closest("form");
  const q = picker.querySelector("[data-search-q]");
  const go = picker.querySelector("[data-search-go]");
  const status = picker.querySelector("[data-search-status]");
  const results = picker.querySelector("[data-search-results]");
  const file = picker.querySelector("input[type=file]");

  const search = async () => {
    const nameField = form.querySelector("input[name=name]");
    const term = (q.value || (nameField && nameField.value) || form.dataset.nameHint || "").trim();
    if (term.length < 2) { status.textContent = "Type a biscuit name to search for."; return; }
    q.value = term;
    status.textContent = "Searching Open Food Facts…";
    results.replaceChildren();
    try {
      const resp = await fetch(`${picker.dataset.searchUrl}?q=${encodeURIComponent(term)}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Search failed.");
      if (!data.results.length) { status.textContent = "No pack shots found. Try a simpler name, or upload your own."; return; }
      status.textContent = "Tap a photo to use it.";
      for (const r of data.results) {
        const label = document.createElement("label");
        label.className = "web-result";
        const input = Object.assign(document.createElement("input"), { type: "radio", name: "web_image", value: r.image });
        const img = Object.assign(document.createElement("img"), {
          src: `${picker.dataset.thumbUrl}?u=${encodeURIComponent(r.thumb)}`, alt: r.name || "Pack shot", loading: "lazy",
        });
        const cap = document.createElement("span");
        cap.textContent = [r.name, r.brand].filter(Boolean).join(" · ");
        label.append(input, img, cap);
        results.append(label);
      }
    } catch (err) {
      status.textContent = err.message || "Search failed.";
    }
  };
  go.addEventListener("click", search);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
  // One photo source at a time: picking a web photo clears the file, and vice versa.
  picker.addEventListener("change", (e) => {
    if (e.target.name === "web_image" && file) file.value = "";
    if (e.target === file) picker.querySelectorAll("input[name=web_image]").forEach((i) => { i.checked = false; });
  });
});

// Add-specimen: live "is this already on file?" check while typing (debounced).
const addForm = document.querySelector("[data-add-form]");
if (addForm) {
  const box = addForm.querySelector("[data-dupes]");
  const list = addForm.querySelector("[data-dupes-list]");
  const confirmLabel = addForm.querySelector("[data-dupes-confirm]");
  const { name, brand } = addForm.elements;
  let timer;
  const check = async () => {
    const n = name.value.trim();
    if (n.length < 3) { box.hidden = true; return; }
    try {
      const url = `${addForm.dataset.similarUrl}?name=${encodeURIComponent(n)}&brand=${encodeURIComponent(brand.value.trim())}`;
      const { matches } = await (await fetch(url)).json();
      list.replaceChildren(...matches.map((m) => {
        const li = document.createElement("li");
        const a = Object.assign(document.createElement("a"), { href: m.url, textContent: m.name });
        li.append(a);
        if (m.brand) li.append(` · ${m.brand}`);
        if (m.exact) li.append(" ", Object.assign(document.createElement("span"), { className: "tag", textContent: "same biscuit" }));
        return li;
      }));
      const exact = matches.some((m) => m.exact);
      box.hidden = matches.length === 0;
      box.classList.toggle("exact", exact);
      confirmLabel.hidden = exact;
    } catch { /* the server re-checks on submit anyway */ }
  };
  const schedule = () => { clearTimeout(timer); timer = setTimeout(check, 300); };
  name.addEventListener("input", schedule);
  brand.addEventListener("input", schedule);
}

// Presence heartbeat: tells the control room this agent is here, and whether they have
// unsaved input in a form ("mid-review"), so CF doesn't shut the server down on them.
const pingUrl = document.body.dataset.pingUrl;
if (pingUrl) {
  let editing = false;
  const ping = () => {
    if (document.visibilityState !== "visible") return;
    fetch(pingUrl, {
      method: "POST", headers: { "Content-Type": "application/json" }, keepalive: true,
      body: JSON.stringify({ path: location.pathname, editing }),
    }).catch(() => { /* server down: nothing useful to do */ });
  };
  document.querySelectorAll("main form").forEach((f) => {
    const mark = () => { if (!editing) { editing = true; ping(); } };  // report promptly on first edit
    f.addEventListener("input", mark);
    f.addEventListener("change", mark);
    f.addEventListener("submit", () => { editing = false; });
  });
  setInterval(ping, 25000);
  document.addEventListener("visibilitychange", ping);  // back on the tab: say hello straight away
}

// Admin: live-presence panel refresh.
const livePanel = document.querySelector("[data-live-panel]");
if (livePanel) {
  const list = livePanel.querySelector("[data-live-list]");
  const countEl = livePanel.querySelector("[data-live-count]");
  const summary = livePanel.querySelector("[data-live-summary]");
  const refresh = async () => {
    try {
      const data = await (await fetch(livePanel.dataset.liveUrl)).json();
      countEl.textContent = `(${data.count})`;
      summary.textContent = data.count === 0 ? "Nobody's on BRT right now. Safe to shut down."
        : data.editing ? "⚠️ Someone is mid-review. Hold off shutting down."
        : "People are browsing, but nobody's halfway through a form.";
      list.replaceChildren(...data.agents.map((a) => {
        const li = document.createElement("li");
        if (a.editing) li.className = "editing";
        li.append(`${a.avatar} `, Object.assign(document.createElement("strong"), { textContent: a.name }), ` · ${a.where}`);
        if (a.editing) li.append(" ", Object.assign(document.createElement("span"), { className: "tag", textContent: "✏️ mid-review" }));
        li.append(" ", Object.assign(document.createElement("span"), { className: "muted small", textContent: `${a.seconds_ago}s ago` }));
        return li;
      }));
    } catch { /* keep showing the last good state */ }
  };
  setInterval(refresh, 15000);
}

// E-STOP: swap BRT for a fake work screen. Press again (or Esc) to come back.
const estop = document.querySelector("[data-estop]");
if (estop) {
  const stealth = document.querySelector("[data-stealth]");
  const img = stealth.querySelector("[data-stealth-img]");
  const fallback = stealth.querySelector("[data-stealth-fallback]");
  let shots = [];
  try { shots = JSON.parse(estop.dataset.shots || "[]"); } catch { /* use the fallback screen */ }
  const realTitle = document.title;
  let on = false;
  const setStealth = (value) => {
    on = value;
    if (on) {
      if (shots.length) {
        img.src = shots[Math.floor(Math.random() * shots.length)];
        img.hidden = false; fallback.hidden = true;
      } else {
        img.hidden = true; fallback.hidden = false;
      }
      document.title = "CM7 - µVision";  // the browser tab gives the game away otherwise
    } else {
      document.title = realTitle;
    }
    stealth.hidden = !on;
    document.body.classList.toggle("stealthed", on);
    estop.setAttribute("aria-pressed", String(on));
  };
  estop.addEventListener("click", () => setStealth(!on));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && on) setStealth(false); });
}

// Dashboard scouting report: loaded after the page so a slow Open Food Facts never blocks it.
const scouting = document.querySelector("[data-scouting]");
if (scouting) {
  const status = scouting.querySelector("[data-scouting-status]");
  const list = scouting.querySelector("[data-scouting-list]");
  const reroll = scouting.querySelector("[data-scouting-reroll]");
  const load = async () => {
    status.textContent = "Scanning the shelves…";
    reroll.disabled = true;
    try {
      const resp = await fetch(scouting.dataset.url);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Scouting failed.");
      if (!data.items.length) { status.textContent = "Nothing new found. The team has tried everything (or the search came up dry)."; list.replaceChildren(); return; }
      status.textContent = "";
      list.replaceChildren(...data.items.map((it) => {
        const li = document.createElement("li");
        const card = Object.assign(document.createElement("a"), { className: "pick-card", href: it.log_url, title: "Log it as a specimen" });
        const photo = Object.assign(document.createElement("div"), { className: "pick-photo pick-photo-white" });
        photo.append(Object.assign(document.createElement("img"), { src: it.thumb_url, alt: "", loading: "lazy" }));
        const body = document.createElement("div");
        body.append(Object.assign(document.createElement("strong"), { textContent: it.name }));
        body.append(Object.assign(document.createElement("p"), { className: "muted small", textContent: [it.brand, it.reason].filter(Boolean).join(" · ") }));
        body.append(Object.assign(document.createElement("span"), { className: "pick-cta small", textContent: "+ Log it" }));
        card.append(photo, body);
        li.append(card);
        return li;
      }));
    } catch (err) {
      status.textContent = `${err.message || "Scouting failed."} Try a reroll in a minute.`;
    } finally {
      reroll.disabled = false;
    }
  };
  reroll.addEventListener("click", load);
  load();
}

// Mystery Tin: shake the tin for a beat before submitting, for drama. (No effect on the odds:
// the server rolls when the form arrives.)
const tinForm = document.querySelector("[data-tin-form]");
if (tinForm) {
  tinForm.addEventListener("submit", (e) => {
    if (tinForm.dataset.go) return;
    e.preventDefault();
    tinForm.closest(".tin-panel").classList.add("opening");
    tinForm.querySelector("button").disabled = true;
    setTimeout(() => { tinForm.dataset.go = "1"; tinForm.submit(); }, 900);
  });
}
const revealEl = document.querySelector("[data-reveal]");
if (revealEl && /rarity-(rare|epic|legendary)/.test(revealEl.className)) crumbShower();

// Dunk-O-Meter: one button. DUNK starts the clock, SPLAT stops it and submits.
const dunkForm = document.querySelector("[data-dunk-form]");
if (dunkForm) {
  const btn = dunkForm.querySelector("[data-dunk-btn]");
  const display = dunkForm.querySelector("[data-dunk-display]");
  const biscuitEl = dunkForm.querySelector("[data-dunk-biscuit]");
  const panel = dunkForm.closest("[data-dunk]");
  let started = 0, timer = 0;
  const show = (s) => { display.firstChild.textContent = s.toFixed(1); };
  btn.addEventListener("click", () => {
    if (!dunkForm.reportValidity()) return;          // pick a biscuit first
    if (!started) {
      started = performance.now();
      panel.classList.add("dunking");
      btn.textContent = "💦 SPLAT!";
      timer = setInterval(() => show((performance.now() - started) / 1000), 100);
    } else {
      const secs = (performance.now() - started) / 1000;
      clearInterval(timer);
      show(secs);
      panel.classList.remove("dunking");
      panel.classList.add("splat");
      biscuitEl.textContent = "💥";
      dunkForm.querySelector("[data-dunk-seconds]").value = secs.toFixed(2);
      btn.disabled = true;
      setTimeout(() => dunkForm.submit(), 700);
    }
  });
}

// Phone nav: if the tabs overflow, fade the edge (CSS) and bring the current tab into view.
const navEl = document.querySelector(".nav");
if (navEl) {
  const mark = () => {
    navEl.classList.toggle("scrolls", navEl.scrollWidth > navEl.clientWidth + 2);
    navEl.classList.toggle("at-end", navEl.scrollLeft + navEl.clientWidth >= navEl.scrollWidth - 2);
  };
  const current = navEl.querySelector("[aria-current]");
  if (current && navEl.scrollWidth > navEl.clientWidth) current.scrollIntoView({ inline: "center", block: "nearest" });
  navEl.addEventListener("scroll", mark, { passive: true });
  window.addEventListener("resize", mark);
  mark();
}

// Admin: copy join links, and confirm destructive-ish actions.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  const input = btn.parentElement.querySelector("[data-copy-src]");
  try {
    await navigator.clipboard.writeText(input.value);
  } catch {
    input.select();
    document.execCommand("copy");  // fallback for non-secure contexts
  }
  btn.textContent = "Copied!";
  setTimeout(() => { btn.textContent = "Copy"; }, 1500);
});

document.addEventListener("submit", (e) => {
  const msg = e.target.dataset.confirm;
  if (msg && !confirm(msg)) e.preventDefault();
});
