/* Quorum frontend */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const h = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ICONS = {
  chair: '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
  cfo: '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
  growth: '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
  coo: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  risk: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
};
const AGENT_COLORS = { chair: "#b7862c", cfo: "#12805c", growth: "#d6336c", coo: "#2f6fdf", risk: "#7048e8" };
const ORDER = ["chair", "cfo", "growth", "coo", "risk"];
const OPT_COLORS = { A: "#4f46e5", B: "#e8590c", C: "#0c8599", D: "#9c36b5" };
const PHASES = ["Opening", "Positions", "Stress test", "Rebuttals", "Ruling"];

const SLIDERS = [
  { key: "cac", label: "Customer acquisition cost", owner: "Growth", min: 4000, max: 20000, step: 500, fmt: (v) => money(v) },
  { key: "cac_saturation_spend", label: "Monthly spend where CAC doubles", owner: "Growth", min: 50000, max: 400000, step: 10000, fmt: (v) => money(v) },
  { key: "eng_growth_lift", label: "Growth lift per engineer", owner: "COO", min: 0.001, max: 0.008, step: 0.0005, fmt: (v) => `+${(v * 100).toFixed(2)}% / mo` },
  { key: "eng_ramp_months", label: "Engineer ramp-up", owner: "COO", min: 1, max: 9, step: 1, fmt: (v) => `${v} months` },
  { key: "stress_mrr_shock", label: "Stress test revenue shock", owner: "Risk", min: 0.1, max: 0.5, step: 0.05, fmt: (v) => `−${Math.round(v * 100)}%` },
  { key: "min_stress_runway", label: "Guardrail: runway under stress", owner: "Board", min: 6, max: 24, step: 1, fmt: (v) => `≥ ${v} months` },
];

const S = { sid: null, options: [], qDirty: false, emptyHTML: "", sc: null, agents: {}, facts: {}, metrics: null, overrides: {}, running: false, votes: {}, vetoed: new Set(), winner: null, phase: -1, seen: new Set(), queue: Promise.resolve() };

function money(x) {
  const s = x < 0 ? "−" : ""; x = Math.abs(x);
  if (x >= 1e6) return `${s}$${(x / 1e6).toFixed(2)}M`;
  if (x >= 1e3) return `${s}$${Math.round(x / 1e3)}K`;
  return `${s}$${Math.round(x)}`;
}
const mo = (n) => (n >= 36 ? "36+ mo" : `${n} mo`);
const icon = (id) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[id]}</svg>`;
const avatar = (id) => `<div class="avatar" style="--c:${AGENT_COLORS[id]}">${icon(id)}</div>`;

/* ------------------------------------------------------------------ init */
async function init() {
  S.emptyHTML = $("#thread").innerHTML;
  const list = await (await fetch("/api/scenarios")).json();
  const sel = $("#scenario");
  sel.innerHTML = list.map((x) => `<option value="${x.id}">${x.name}</option>`).join("");
  sel.onchange = () => loadScenario(sel.value);

  const q = $("#question");
  q.addEventListener("input", () => { S.qDirty = true; autosize(q); });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); draftOptions(); } });
  $("#convene").onclick = convene;
  $("#draft").onclick = draftOptions;
  $("#reset").onclick = () => { S.overrides = {}; buildSliders(); refreshModel(); };
  window.addEventListener("resize", () => autosize(q));

  const params = new URLSearchParams(location.search);
  const want = list.find((x) => x.id === params.get("company"))?.id || list[0].id;
  sel.value = want;
  await loadScenario(want);
  if (params.has("autorun")) convene();
}

async function loadScenario(id) {
  if (S.running) return;
  const sc = await (await fetch(`/api/scenario?id=${encodeURIComponent(id)}`)).json();
  S.sid = id; S.sc = sc; S.agents = sc.agents; S.overrides = {}; S.qDirty = false;
  S.options = sc.options.map((o) => ({ ...o }));
  S.votes = {}; S.vetoed.clear(); S.winner = null; S.phase = -1;
  const q = $("#question"); q.value = sc.question; autosize(q);
  setDraftStatus("", "Ask about hiring, marketing, pricing, cost cuts or fundraising, then press Enter or Draft options.");
  $("#company-name").textContent = sc.company.name;
  $("#company-meta").textContent = `${sc.company.sector} · ${money(sc.company.cash)} cash · ${money(sc.company.mrr)} MRR · ${sc.company.headcount} people`;
  const pc = $("#provider-chip");
  pc.className = "chip " + (sc.provider === "nicrron" ? "on" : "warn");
  pc.querySelector("span").textContent = sc.provider === "nicrron" ? "Nicrron live" : "Nicrron: scripted";
  pc.title = sc.provider === "nicrron" ? "Agent voices come from Nicrron" : "Set QUORUM_PROVIDER=nicrron to voice agents with Nicrron";
  const pr = $("#prism-chip");
  pr.className = "chip " + (sc.prism ? "on" : "warn");
  pr.querySelector("span").textContent = sc.prism ? "PRISM connected" : "PRISM: local only";
  $("#thread").innerHTML = S.emptyHTML;
  $("#convene-2").onclick = convene;
  $("#board-status").textContent = "5 members";
  $("#convene").textContent = "Convene the board";
  $("#facts").innerHTML = ""; $("#fact-count").textContent = "";
  renderMembers(); renderPhases(); buildSliders();
  await refreshModel();
}

function autosize(t) { t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; }

/* ------------------------------------------------------------------ board */
function renderMembers() {
  const box = $("#members"); box.innerHTML = "";
  for (const id of ORDER) {
    const a = S.agents[id];
    const m = h("div", "member");
    m.id = `m-${id}`; m.style.setProperty("--c", AGENT_COLORS[id]);
    m.innerHTML = `${avatar(id)}<div><div class="member-name">${a.name}</div><div class="member-role">${a.role}</div><div class="member-state"></div></div><div class="stance" title="Current position">–</div>`;
    box.appendChild(m);
  }
}
function setMemberState(id, html) { const el = $(`#m-${id} .member-state`); if (el) el.innerHTML = html; }
function setSpeaking(id) {
  $$(".member").forEach((m) => m.classList.toggle("speaking", m.id === `m-${id}`));
}
function setStance(id, opt) {
  const el = $(`#m-${id} .stance`); const prev = S.votes[id];
  S.votes[id] = opt;
  el.textContent = opt || "–";
  el.classList.toggle("set", !!opt);
  if (opt) el.style.setProperty("--oc", OPT_COLORS[opt]);
  if (prev !== undefined && prev !== opt) { el.classList.remove("changed"); void el.offsetWidth; el.classList.add("changed"); }
  renderTally();
}

function renderPhases() {
  $("#phases").innerHTML = PHASES.map((p, i) => `<li class="${i < S.phase ? "done" : i === S.phase ? "active" : ""}">${p}</li>`).join("");
}
function phaseOf(t) {
  if (t.index === 0) return 0;
  if (t.agent === "risk") return 2;
  if (t.agent === "chair") return 4;
  if (!S.seen.has(t.agent)) return 1;
  return 3;
}

/* ------------------------------------------------------------------ decision panel */
function buildSliders() {
  const box = $("#sliders"); box.innerHTML = "";
  const base = S.sc.assumptions;
  for (const s of SLIDERS) {
    const val = S.overrides[s.key] ?? base[s.key];
    const row = h("div", "slider" + (s.key in S.overrides ? " changed" : ""));
    row.innerHTML = `<label><span>${s.label} <span class="owner">· ${s.owner}</span></span><span class="val">${s.fmt(val)}</span></label><input type="range" min="${s.min}" max="${s.max}" step="${s.step}" value="${val}" aria-label="${s.label}">`;
    const input = row.querySelector("input");
    input.oninput = () => {
      const v = parseFloat(input.value);
      row.querySelector(".val").textContent = s.fmt(v);
      if (Math.abs(v - base[s.key]) < 1e-9) { delete S.overrides[s.key]; row.classList.remove("changed"); }
      else { S.overrides[s.key] = v; row.classList.add("changed"); }
      updateChangedCount();
      clearTimeout(S.t); S.t = setTimeout(refreshModel, 120);
    };
    box.appendChild(row);
  }
  updateChangedCount();
}
function updateChangedCount() {
  const n = Object.keys(S.overrides).length;
  $("#changed-count").textContent = n ? `${n} changed` : "model defaults";
}

async function refreshModel() {
  const r = await fetch("/api/evaluate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: S.sid, options: S.options, overrides: S.overrides }) });
  S.metrics = await r.json();
  S.options.forEach((o) => (o.label = S.metrics.labels[o.id]));
  if (!S.running) { S.vetoed.clear(); S.winner = null; }
  renderOptions(); renderChart(); renderTally();
}

function renderOptions() {
  const m = S.metrics; if (!m) return;
  const g = m.assumptions.min_stress_runway;
  $("#rule").textContent = `Must survive −${Math.round(m.assumptions.stress_mrr_shock * 100)}% revenue with ≥ ${g} mo`;
  $("#options").innerHTML = m.options.map((o) => {
    const win = S.winner === o.id, vetoed = S.vetoed.has(o.id);
    const status = win ? '<span class="status win">Approved</span>' : vetoed ? '<span class="status fail">Vetoed</span>' : o.passes_guardrail ? '<span class="status pass">Passes</span>' : '<span class="status fail">Fails stress</span>';
    return `<div class="opt${o.passes_guardrail ? "" : " fails"}${vetoed ? " vetoed" : ""}${win ? " winner" : ""}" style="--oc:${OPT_COLORS[o.id]}">
      <div class="opt-top"><div class="opt-letter">${o.id}</div><div class="opt-label">${o.label}</div>${status}</div>
      <div class="opt-grid">
        <div><div class="k">Net value</div><div class="v">${money(o.net_value)}</div></div>
        <div><div class="k">+MRR, mo 24</div><div class="v">${money(o.inc_mrr_24)}</div></div>
        <div><div class="k">${o.cost_24 < 0 ? "Saves, 24 mo" : "Net cost, 24 mo"}</div><div class="v">${money(Math.abs(o.cost_24))}</div></div>
      </div>
      ${leverRow(o)}
      <div class="runway">
        <div class="runway-bar"><div class="runway-fill" style="width:${Math.min(100, (o.stress_runway / 36) * 100)}%"></div><div class="runway-tick" style="left:${(g / 36) * 100}%" title="Guardrail"></div></div>
        <div class="runway-cap"><span>Runway under stress <b>${mo(o.stress_runway)}</b></span><span>guardrail ${g} mo</span></div>
      </div></div>`;
  }).join("");
  $$("#options .lever button").forEach((b) => (b.onclick = () => nudge(b.dataset.o, b.dataset.k, +b.dataset.d)));
  $$("#options .add-lever").forEach((sel) => (sel.onchange = () => { if (sel.value) nudge(sel.dataset.o, sel.value, 1); }));
}

function shortMoney(x) {
  if (x >= 1e6) return `$${(x / 1e6).toFixed(2).replace(/\.?0+$/, "")}M`;
  if (x >= 1e3) return `$${Math.round(x / 1e3)}K`;
  return `$${Math.round(x)}`;
}
const LEVERS = {
  engineers: { name: "Eng.", full: "Hire engineers", step: 1, min: 0, max: 20, always: true, fmt: (v) => String(v) },
  marketing_budget: { name: "Mktg", full: "Marketing spend", step: 50000, min: 0, max: 3000000, always: true, fmt: (v) => shortMoney(v) },
  price_change: { name: "Price", full: "Change prices", step: 0.05, min: -0.3, max: 0.5, fmt: (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.round(Math.abs(v) * 100)}%` },
  cost_cut: { name: "Cut/mo", full: "Cut costs", step: 10000, min: 0, max: 250000, fmt: (v) => shortMoney(v) },
  fundraise: { name: "Raise", full: "Raise money", step: 250000, min: 0, max: 20000000, fmt: (v) => shortMoney(v) },
};
function leverRow(o) {
  const keys = Object.keys(LEVERS);
  const shown = keys.filter((k) => LEVERS[k].always || Math.abs(o[k] || 0) > 1e-9);
  const hidden = keys.filter((k) => !shown.includes(k));
  const dis = S.running ? " disabled" : "";
  const add = hidden.length ? `<select class="add-lever" data-o="${o.id}" aria-label="Add a lever to option ${o.id}"${dis}>
      <option value="">+ Add lever</option>${hidden.map((k) => `<option value="${k}">${LEVERS[k].full}</option>`).join("")}</select>` : "";
  return `<div class="levers">${shown.map((k) => lever(o.id, k, o[k] || 0)).join("")}${add}</div>`;
}
function lever(id, key, val) {
  const L = LEVERS[key], dis = S.running ? " disabled" : "";
  return `<span class="lever" title="${L.full}"><span class="lk">${L.name}</span>
    <button data-o="${id}" data-k="${key}" data-d="-1" aria-label="Decrease ${L.full.toLowerCase()} for option ${id}"${val <= L.min + 1e-9 || dis ? " disabled" : ""}>−</button>
    <span class="lv">${L.fmt(val)}</span>
    <button data-o="${id}" data-k="${key}" data-d="1" aria-label="Increase ${L.full.toLowerCase()} for option ${id}"${val >= L.max - 1e-9 || dis ? " disabled" : ""}>+</button></span>`;
}
function nudge(id, key, dir) {
  if (S.running) return;
  const o = S.options.find((x) => x.id === id), L = LEVERS[key];
  const next = Math.max(L.min, Math.min(L.max, (o[key] || 0) + dir * L.step));
  o[key] = Math.round(next / L.step) * L.step;
  if (key === "price_change") o[key] = Math.round(o[key] * 100) / 100;
  S.winner = null; S.vetoed.clear();
  clearTimeout(S.t2); S.t2 = setTimeout(async () => {
    await refreshModel();
    if (!S.qDirty) { const q = $("#question"); q.value = autoQuestion(); autosize(q); }
  }, 100);
}
function setDraftStatus(cls, text) { const el = $("#draft-status"); el.className = "draft-status " + cls; el.textContent = text; }

async function draftOptions() {
  if (S.running || S.drafting) return;
  const question = $("#question").value.trim();
  if (!question) { setDraftStatus("err", "Type a question first."); return; }
  S.drafting = true;
  const btn = $("#draft"); btn.disabled = true; btn.textContent = "Drafting…";
  setDraftStatus("busy", "Nicrron is reading the question…");
  try {
    const r = await fetch("/api/draft-options", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: S.sid, question }) });
    const d = await r.json();
    if (!d.ok) { setDraftStatus("err", d.reason); return; }
    S.options = d.options.map((o) => ({ ...o }));
    S.qDirty = true; S.winner = null; S.vetoed.clear(); S.votes = {};
    await refreshModel();
    setDraftStatus("ok", `${d.options.length} options drafted${d.note ? `: ${d.note}` : ""} Check them on the right, then convene.`);
  } catch (e) {
    setDraftStatus("err", `Couldn't draft options: ${e.message}`);
  } finally {
    S.drafting = false; btn.disabled = false; btn.textContent = "Draft options";
  }
}

function autoQuestion() {
  const phrase = (o) => {
    const p = [];
    if (o.engineers) p.push(`hire ${o.engineers} engineer${o.engineers === 1 ? "" : "s"}`);
    if (o.marketing_budget) p.push(`spend ${money(o.marketing_budget)} on marketing`);
    if (o.price_change) p.push(`${o.price_change > 0 ? "raise" : "cut"} prices ${Math.round(Math.abs(o.price_change) * 100)}%`);
    if (o.cost_cut) p.push(`cut costs by ${money(o.cost_cut)} a month`);
    if (o.fundraise) p.push(`raise ${money(o.fundraise)}`);
    return p.length ? p.join(" and ") : "keep the cash";
  };
  const ls = S.options.map(phrase);
  return `Should we ${ls.slice(0, -1).join(", ")}, or ${ls[ls.length - 1]}?`;
}

function renderTally() {
  const m = S.metrics; if (!m) return;
  const ids = m.options.map((o) => o.id);
  const cast = Object.keys(S.votes).length;
  $("#tally").innerHTML = ids.map((id) => {
    const voters = ORDER.filter((a) => S.votes[a] === id);
    return `<div class="tally-row"><div class="opt-letter" style="--oc:${OPT_COLORS[id]}">${id}</div>
      <div class="tally-track">${voters.map((a) => `<div class="tally-seg" style="background:${AGENT_COLORS[a]};color:#fff" title="${S.agents[a].name}">${icon(a)}</div>`).join("")}</div>
      <div class="n">${voters.length}</div></div>`;
  }).join("");
  const top = ids.map((id) => [id, ORDER.filter((a) => S.votes[a] === id).length]).sort((a, b) => b[1] - a[1])[0];
  $("#vote-summary").textContent = !cast ? "Not yet cast" : top[1] === 0 ? "All abstained" : `${top[0]} leads, ${top[1]} of 5`;
}

function renderChart(hl) {
  const m = S.metrics; if (!m) return;
  const W = 340, H = 170, L = 44, R = 6, T = 8, B = 22;
  const series = [{ id: "0", label: "Do nothing", color: "#a39f98", data: m.baseline.cash_curve, dash: "4 4" }]
    .concat(m.options.map((o) => ({ id: o.id, label: `Option ${o.id}`, color: OPT_COLORS[o.id], data: o.cash_curve })));
  const all = series.flatMap((s) => s.data);
  const lo = Math.min(0, ...all), hi = Math.max(...all);
  const x = (i) => L + (i / 23) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  let out = "";
  for (let k = 0; k <= 4; k++) {
    const v = lo + ((hi - lo) * k) / 4;
    out += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 3}" text-anchor="end">${money(Math.round(v / 1e4) * 1e4)}</text>`;
  }
  if (lo < 0) out += `<line class="zero" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>`;
  [0, 5, 11, 17, 23].forEach((i) => (out += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">Mo ${i + 1}</text>`));
  for (const s of series) {
    const d = s.data.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const cls = hl ? (s.id === hl ? "curve hl" : "curve dim") : "curve";
    out += `<path class="${cls}" d="${d}" stroke="${s.color}"${s.dash ? ` stroke-dasharray="${s.dash}"` : ""}/>`;
  }
  $("#chart").innerHTML = out;
  $("#legend").innerHTML = series.map((s) => `<span><i style="background:${s.color}"></i>${s.label}</span>`).join("");
}

function renderFacts(facts) {
  S.facts = Object.fromEntries(facts.map((f) => [f.id, f]));
  $("#facts").innerHTML = facts.map((f) => `<li id="f-${f.id}"><span class="fid">${f.id}</span><span>${f.text}</span><span class="fv">${f.value}</span></li>`).join("");
  $("#fact-count").textContent = `${facts.length} figures`;
}

/* ------------------------------------------------------------------ meeting */
async function convene() {
  if (S.running) return;
  Object.assign(S, { running: true, votes: {}, winner: null, phase: -1, seen: new Set(), queue: Promise.resolve() });
  S.vetoed.clear();
  const btn = $("#convene"); btn.disabled = true; btn.textContent = "In session…";
  $("#scenario").disabled = true;
  $("#draft").disabled = true;
  $("#thread").innerHTML = "";
  $("#board-status").textContent = "In session";
  ORDER.forEach((id) => { const s = $(`#m-${id} .stance`); s.textContent = "–"; s.className = "stance"; setMemberState(id, ""); });
  renderPhases(); renderOptions(); renderTally();

  try {
    const resp = await fetch("/api/deliberate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario: S.sid, options: S.options, question: $("#question").value, ceo_note: $("#ceo-note").value, overrides: S.overrides, guardrails: $("#guardrails").checked }),
    });
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = /^event: (.*)$/m.exec(chunk)?.[1]; const data = /^data: (.*)$/m.exec(chunk)?.[1];
        if (ev) handle(ev, data ? JSON.parse(data) : {});
      }
    }
  } catch (e) {
    enqueue(async () => $("#thread").appendChild(h("div", "phase-divider", `Connection lost: ${e.message}`)));
  }
  enqueue(async () => {
    S.running = false; btn.disabled = false; btn.textContent = "Reconvene";
    $("#scenario").disabled = false; $("#draft").disabled = false; renderOptions();
    $("#board-status").textContent = "Adjourned";
    setSpeaking(null);
  });
}
const enqueue = (fn) => (S.queue = S.queue.then(fn).catch(console.error));

function handle(ev, d) {
  if (ev === "facts") enqueue(async () => { renderFacts(d.facts); S.metrics = d.metrics; renderOptions(); renderChart(); });
  else if (ev === "thinking") enqueue(async () => showThinking(d.agent));
  else if (ev === "turn") enqueue(() => playTurn(d));
  else if (ev === "verdict") enqueue(() => showVerdict(d));
  else if (ev === "error") enqueue(async () => $("#thread").appendChild(h("div", "phase-divider", `Error: ${d.message}`)));
}

function scrollThread() { const c = $(".col-thread"); c.scrollTo({ top: c.scrollHeight, behavior: "smooth" }); }

function showThinking(id) {
  $("#thinking")?.remove();
  setSpeaking(id);
  ORDER.forEach((a) => setMemberState(a, a === id ? 'thinking<span class="typing"><i></i><i></i><i></i></span>' : ""));
  const row = h("div", "thinking-row", `${avatar(id)}<span><b style="color:${AGENT_COLORS[id]};font-weight:600">${S.agents[id].name}</b> is thinking <span class="typing"><i></i><i></i><i></i></span></span>`);
  row.id = "thinking"; row.style.setProperty("--c", AGENT_COLORS[id]);
  $("#thread").appendChild(row); scrollThread();
}

async function playTurn(t) {
  $("#thinking")?.remove();
  const thread = $("#thread"); const a = S.agents[t.agent]; const c = AGENT_COLORS[t.agent];

  const p = phaseOf(t);
  if (p !== S.phase) { S.phase = p; renderPhases(); thread.appendChild(h("div", "phase-divider", PHASES[p])); }
  S.seen.add(t.agent);
  setSpeaking(t.agent);
  ORDER.forEach((id) => setMemberState(id, id === t.agent ? "speaking" : ""));

  const replyTo = t.reply_to != null ? thread.querySelector(`.msg[data-index="${t.reply_to}"]`)?.dataset.agent : null;
  const badges = [];
  if (t.backs && t.tone !== "verdict") badges.push(`<span class="badge backs" style="--oc:${OPT_COLORS[t.backs]}">Backs ${t.backs}</span>`);
  if (t.tone === "alarm") badges.push('<span class="badge veto">Veto</span>');
  if (t.tone === "concede") badges.push('<span class="badge shift">Changes position</span>');
  if (t.tone === "firm") badges.push('<span class="badge firm">Holds the line</span>');
  if (t.grounding_failed) badges.push(`<span class="badge flag" title="The AI's line broke a guardrail (${(t.blocked_reason || "").replace(/"/g, "&quot;")}), so it was replaced with the grounded version.">Guardrail: line replaced</span>`);
  const cites = (t.facts || []).filter((id) => S.facts[id]).map((id) => `<span class="cite" title="${S.facts[id].text}" data-f="${id}">${id} <b>${S.facts[id].value}</b></span>`);

  const msg = h("div", "msg");
  msg.dataset.index = t.index; msg.dataset.agent = t.agent; msg.style.setProperty("--c", c);
  msg.innerHTML = `${avatar(t.agent)}<div>
    <div class="msg-head"><span class="msg-name" style="color:${c}">${a.name}</span><span class="msg-role">${a.role}</span>${replyTo ? `<span class="msg-reply">replying to <b>${S.agents[replyTo].name}</b></span>` : ""}</div>
    <div class="msg-body"><span class="txt"></span><span class="caret"></span></div>
    <div class="msg-meta">${badges.join("")}${cites.join("")}</div></div>`;
  thread.appendChild(msg); scrollThread();

  const txt = msg.querySelector(".txt"); const words = t.text.split(/(\s+)/);
  const per = Math.max(10, Math.min(32, 2800 / words.length));
  for (const w of words) { txt.textContent += w; if (w.trim()) await sleep(per); }
  msg.querySelector(".caret").remove();
  msg.querySelector(".msg-meta").classList.add("show");
  msg.querySelectorAll(".cite").forEach((el) => el.addEventListener("mouseenter", () => flashFact(el.dataset.f)));
  (t.facts || []).forEach((id) => $(`#f-${id}`)?.classList.add("used"));
  scrollThread();

  if (t.agent !== "chair" || t.tone === "verdict") setStance(t.agent, t.backs);
  if (t.agent === "risk" && t.tone === "alarm") S.metrics.options.filter((o) => !o.passes_guardrail).forEach((o) => S.vetoed.add(o.id));
  renderOptions();
  if (t.backs) renderChart(t.backs);
  await sleep(420);
}

function flashFact(id) {
  const li = $(`#f-${id}`); if (!li) return;
  li.closest("details").open = true;
  li.scrollIntoView({ block: "nearest", behavior: "smooth" });
  li.classList.add("flash"); setTimeout(() => li.classList.remove("flash"), 900);
}

async function showVerdict(v) {
  S.phase = PHASES.length; renderPhases();
  setSpeaking(null); ORDER.forEach((id) => setMemberState(id, ""));
  S.winner = v.winner; renderOptions(); renderChart(v.winner);
  ORDER.forEach((id) => { if (S.votes[id] !== v.votes[id]) setStance(id, v.votes[id]); });

  const o = S.metrics.options.find((x) => x.id === v.winner);
  const n = Object.values(v.votes).filter((x) => x === v.winner).length;
  const card = h("div", "verdict" + (o ? "" : " reject"));
  card.innerHTML = `
    <div class="verdict-top"><div>
      <div class="eyebrow">Resolution of the board</div>
      <h3>${o ? o.label : "Hold the cash"}</h3>
      <div class="verdict-sub">${o ? `Option ${o.id} · carried ${n}–${5 - n}` : "No option survives the stress test"}</div>
    </div><div class="seal">${o ? "APPROVED" : "NO<br>GO"}</div></div>
    ${o ? `<div class="verdict-stats">
      <div class="vstat"><div class="k">Net value</div><div class="v">${money(o.net_value)}</div></div>
      <div class="vstat"><div class="k">Added MRR by month 24</div><div class="v">${money(o.inc_mrr_24)}</div></div>
      <div class="vstat"><div class="k">Runway under stress</div><div class="v">${mo(o.stress_runway)}</div></div></div>` : ""}
    <div class="verdict-votes">${ORDER.map((id) => `<span class="vote-pill">${avatar(id)}${S.agents[id].name} <b style="color:${OPT_COLORS[v.votes[id]] || "var(--muted)"}">${v.votes[id] || "abstain"}</b></span>`).join("")}</div>
    <div class="verdict-foot">
      <span>Trace ${v.trace.trace_id}</span>
      <span>${v.trace.exported_to_prism ? "Sent to PRISM" : "Saved locally"}</span>
      ${v.trace.flags ? `<span class="warn">${v.trace.flags} ungrounded line(s) blocked</span>` : ""}
      ${v.winner !== v.model_winner ? `<span class="warn">Differs from the model’s answer (${v.model_winner || "none"})</span>` : ""}
    </div>`;
  $("#thread").appendChild(card); scrollThread();
  const pc = $("#prism-chip"); pc.classList.add(v.trace.exported_to_prism ? "on" : "warn");
  pc.querySelector("span").textContent = v.trace.exported_to_prism ? "PRISM: trace sent" : "PRISM: local only";
}

init();
