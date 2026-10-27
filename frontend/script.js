/* TripWise frontend. All planning logic lives in the Python backend;
   this file only collects input, calls the API and draws the response. */
"use strict";

// When Flask serves this page we use relative URLs (works on any Flask port).
// With VS Code Live Server (ports 5500-5502) or a file:// page we call Flask at port 5000.
// If your Flask server uses another port, change the number below.
const FLASK_URL = "http://127.0.0.1:5000";
const NOT_FLASK = window.location.protocol === "file:" || ["5500", "5501", "5502"].includes(window.location.port);
const API_BASE = NOT_FLASK ? FLASK_URL : "";

const $ = (id) => document.getElementById(id);
const rupees = (n) => "\u20B9" + Number(n).toLocaleString("en-IN");
const titleCase = (s) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const CATEGORY_COLORS = {
  nature: ["#0d7c80", "#17b3a8"], beach: ["#1f6fb2", "#4cc3d9"], historical: ["#a2553a", "#e0a96d"],
  adventure: ["#c0562b", "#f2a65a"], spiritual: ["#6a4c93", "#c9a0dc"], wildlife: ["#2f6b3a", "#9ccc65"],
};

let options = null;
let loadingTimer = null;
const imageCache = new Map();

/* Small DOM helper: builds elements with textContent only (no innerHTML),
   so text from the API can never inject HTML. */
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

/* ------------------------------------------------------------ startup */
document.addEventListener("DOMContentLoaded", async () => {
  $("trip-form").addEventListener("submit", onSubmit);
  $("clear-btn").addEventListener("click", resetForm);
  $("plan-again").addEventListener("click", planAgain);
  await checkServer();
  await loadOptions();
});

async function checkServer() {
  const pill = $("server-status");
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) throw new Error("bad status");
    const data = await res.json();
    pill.className = "status online";
    pill.lastElementChild.textContent = `Backend online \u00B7 ${data.destinations} destinations`;
  } catch {
    pill.className = "status offline";
    pill.lastElementChild.textContent = "Backend offline";
  }
}

async function loadOptions() {
  try {
    const res = await fetch(`${API_BASE}/api/options`);
    if (!res.ok) throw new Error("bad status");
    options = await res.json();
    buildForm(options);
  } catch {
    showFormError(["Cannot reach the TripWise server at " + (API_BASE || window.location.origin) +
      ". Start the backend (python app.py inside the backend folder) and reload this page."]);
  }
}

/* ------------------------------------------------------- build the form */
function radio(name, value, labelNodes, checked, cls) {
  const input = el("input", { type: "radio", name, value });
  if (checked) input.checked = true;
  return el("label", { class: cls }, input, el("span", {}, labelNodes));
}

function buildForm(opts) {
  $("city-list").replaceChildren(...opts.cities.map((c) => el("option", { value: c })));

  const cats = [{ id: "any", label: "Any type", emoji: "\uD83E\uDDED" }, ...opts.categories];
  $("category-options").replaceChildren(...cats.map((c, i) =>
    radio("category", c.id, [el("span", { class: "emoji", text: c.emoji }), c.label], i === 0, "tile")));

  $("transport-options").replaceChildren(...opts.transport_modes.map((m, i) =>
    radio("transport", m.id, m.label, i === 0, "seg")));

  const stays = [{ id: "any", label: "Any" }, ...opts.accommodation_tiers];
  $("accommodation-options").replaceChildren(...stays.map((t, i) =>
    radio("accommodation", t.id, t.label, i === 0, "seg")));

  $("interest-options").replaceChildren(...opts.interests.map((i) => {
    const input = el("input", { type: "checkbox", name: "interests", value: i.id });
    return el("label", { class: "chip" }, input, el("span", { text: i.label }));
  }));

  if (window.lucide) window.lucide.createIcons();
}

/* ----------------------------------------------------------- form logic */
function readForm() {
  const form = $("trip-form");
  const checked = (name) => form.querySelector(`input[name="${name}"]:checked`);
  return {
    starting_city: $("city").value.trim(),
    budget: $("budget").value === "" ? null : Number($("budget").value),
    days: $("days").value === "" ? null : Number($("days").value),
    travelers: $("travelers").value === "" ? null : Number($("travelers").value),
    category: checked("category") ? checked("category").value : "any",
    transport: checked("transport") ? checked("transport").value : "auto",
    accommodation: checked("accommodation") ? checked("accommodation").value : "any",
    interests: [...form.querySelectorAll('input[name="interests"]:checked')].map((i) => i.value),
  };
}

/* Friendly pre-checks only. The backend repeats and enforces every rule. */
function validate(data) {
  const errors = [];
  const bad = new Set();
  if (!data.starting_city) { errors.push("Enter your starting city."); bad.add("city"); }
  else if (options && !options.cities.some((c) => c.toLowerCase() === data.starting_city.toLowerCase())) {
    errors.push("Pick a starting city from the list (it is used to estimate distances).");
    bad.add("city");
  }
  if (data.budget === null || !(data.budget >= 1000)) { errors.push("Enter a total budget of at least \u20B91,000."); bad.add("budget"); }
  if (data.days === null || !Number.isInteger(data.days) || data.days < 1 || data.days > 30) { errors.push("Trip length must be a whole number from 1 to 30 days."); bad.add("days"); }
  if (data.travelers === null || !Number.isInteger(data.travelers) || data.travelers < 1 || data.travelers > 20) { errors.push("Travelers must be a whole number from 1 to 20."); bad.add("travelers"); }
  for (const id of ["city", "budget", "days", "travelers"]) $(id).classList.toggle("invalid", bad.has(id));
  return errors;
}

function showFormError(messages) {
  const box = $("form-error");
  if (!messages.length) { box.hidden = true; return; }
  box.replaceChildren(
    el("strong", { text: messages.length > 1 ? "Please fix the following:" : "Something needs attention:" }),
    el("ul", {}, messages.map((m) => el("li", { text: m }))));
  box.hidden = false;
}

async function onSubmit(event) {
  event.preventDefault();
  const data = readForm();
  const errors = validate(data);
  showFormError(errors);
  if (errors.length) return;

  setLoading(true);
  $("results").hidden = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const res = await fetch(`${API_BASE}/api/recommend`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data), signal: controller.signal,
    });
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      const msgs = body && body.details ? body.details : [(body && body.error) || `Server returned status ${res.status}.`];
      showFormError(msgs);
      return;
    }
    renderResults(body);
  } catch (err) {
    const where = API_BASE || window.location.origin;
    showFormError([err.name === "AbortError"
      ? "The server took too long to answer. Try again."
      : `Cannot reach the TripWise server at ${where}. Make sure the backend is running (python app.py) and try again.`]);
    checkServer();
  } finally {
    clearTimeout(timeout);
    setLoading(false);
  }
}

const LOADING_STEPS = [
  "Filtering destinations by your constraints\u2026",
  "Exploring trip options with breadth-first search\u2026",
  "Pricing transport, stays and activities\u2026",
  "Scoring and ranking the best matches\u2026",
];

function setLoading(on) {
  $("loading").hidden = !on;
  $("submit-btn").disabled = on;
  clearInterval(loadingTimer);
  if (on) {
    let i = 0;
    $("loading-text").textContent = LOADING_STEPS[0];
    loadingTimer = setInterval(() => { i = (i + 1) % LOADING_STEPS.length; $("loading-text").textContent = LOADING_STEPS[i]; }, 900);
  }
}

function resetForm() {
  $("trip-form").reset();
  $("travelers").value = 2;
  for (const id of ["city", "budget", "days", "travelers"]) $(id).classList.remove("invalid");
  showFormError([]);
}

function planAgain() {
  resetForm();
  $("results").hidden = true;
  $("nav-results").hidden = true;
  $("planner").scrollIntoView({ behavior: "smooth" });
  $("city").focus({ preventScroll: true });
}

/* ------------------------------------------------------------- results */
function renderResults(data) {
  $("results").hidden = false;
  $("nav-results").hidden = false;
  $("results-title").textContent = data.count ? "Your best-matching trips" : "No trips fit yet";
  $("results-message").textContent = data.message;
  $("disclaimer").textContent = data.disclaimer || "";

  $("results-notes").replaceChildren(...(data.notes || []).map((n) => el("div", { class: "alert info", text: n })));
  renderSummary(data);

  const empty = $("empty");
  const cards = $("cards");
  if (!data.count) {
    cards.replaceChildren();
    empty.hidden = false;
    empty.replaceChildren(
      el("h3", { text: "Try adjusting one of these" }),
      el("ul", {}, (data.suggestions || []).map((s) => el("li", { text: s }))),
      el("p", { class: "muted", text: "Changing the budget, trip length or starting city usually opens up options." }));
  } else {
    empty.hidden = true;
    cards.replaceChildren(...data.itineraries.map(renderCard));
  }
  renderEngine(data);
  $("results").scrollIntoView({ behavior: "smooth" });
}

function renderSummary(data) {
  const q = data.query;
  const facts = [
    ["Route", `${q.starting_city} \u2192 ${data.count ? data.itineraries[0].destination.name : "?"}`],
    ["Travelers", `${q.travelers} \u00B7 ${q.days} day${q.days > 1 ? "s" : ""} / ${Math.max(q.days - 1, 0)} night${q.days - 1 === 1 ? "" : "s"}`],
    ["Your budget", rupees(q.budget)],
  ];
  if (data.count) {
    const top = data.itineraries[0];
    facts[0][0] = "Top pick";
    facts.push(["Estimated cost", rupees(top.budget.total)]);
    facts.push(["Left over", rupees(top.budget.remaining)]);
  }
  $("summary").replaceChildren(...facts.map(([k, v]) => el("div", { class: "fact" }, el("small", { text: k }), el("strong", { text: v }))));
}

function renderEngine(data) {
  const s = data.stats || {};
  const box = $("engine");
  if (s.bfs_nodes_expanded === undefined) { box.hidden = true; return; }
  const rows = [
    `Destinations in knowledge base: ${s.destinations_in_knowledge_base}; after hard filters: ${s.destinations_after_filtering}`,
    `BFS states expanded: ${s.bfs_nodes_expanded}, generated: ${s.bfs_nodes_generated}, pruned early: ${s.bfs_nodes_pruned}`,
    `Complete itineraries scored: ${s.itineraries_evaluated}`,
    `Heuristic weights: ` + Object.entries(data.weights_used).map(([k, v]) => `${titleCase(k)} ${Math.round(v * 100)}%`).join(", "),
  ];
  const filtered = Object.entries(s.filtered_out || {}).filter(([, n]) => n);
  if (filtered.length) rows.push("Removed by hard constraints: " + filtered.map(([k, n]) => `${n} (${k})`).join(", "));
  $("engine-body").replaceChildren(...rows.map((r) => el("p", { text: r })));
  box.hidden = false;
}

function kv(label, value) {
  return el("div", { class: "kv" }, el("span", { text: label }), el("strong", { text: value }));
}

function renderCard(it) {
  const d = it.destination;
  const media = el("div", { class: "trip-media" },
    el("span", { class: "badge", text: `#${it.rank} match` }),
    el("span", { class: "cat", text: d.category_label }));
  applyImage(media, d);

  const head = el("div", { class: "trip-head" },
    el("div", {},
      el("h3", { text: d.name }),
      el("p", { class: "where", text: d.state })),
    el("div", { class: "ring", style: `--pct:${Math.round(it.score)}`, role: "img", "aria-label": `Match score ${Math.round(it.score)} out of 100` },
      el("div", {}, el("span", {}, el("span", { text: String(Math.round(it.score)) }), el("small", { text: "of 100" })))));

  const why = el("div", { class: "block wide" },
    el("h4", { text: "Why TripWise picked this" }),
    el("ul", {}, it.reasons.map((r) => el("li", { text: r }))),
    el("div", { class: "bars", style: "margin-top:0.8rem" }, it.score_breakdown.map((c) =>
      el("div", { class: "bar-row", title: `Weight ${Math.round(c.weight * 100)}% \u00D7 score ${c.raw}` },
        el("span", { text: c.label }),
        el("div", { class: "bar" }, el("i", { style: `width:${Math.round(c.raw * 100)}%` })),
        el("b", { text: `${c.points} pts` })))));

  const t = it.transport;
  const transport = el("div", { class: "block" },
    el("h4", { text: "Getting there" }),
    kv("Mode", t.label),
    kv("Distance (approx.)", `${t.distance_km} km`),
    kv("Travel time one way", `~${t.one_way_hours} h`),
    kv("Round-trip fare / person", rupees(t.fare_per_person_round_trip)),
    kv(`Total for ${it.budget.budget ? "your group" : ""}`, rupees(t.total)),
    el("div", { class: "table-wrap" }, el("table", { class: "alt" },
      el("thead", {}, el("tr", {}, ["Option", "Hours", "Fare / person"].map((h) => el("th", { text: h })))),
      el("tbody", {}, t.alternatives.map((a) => el("tr", { class: a.selected ? "sel" : "" },
        el("td", { text: a.label + (a.selected ? " (chosen)" : a.fits_time_rule ? "" : " (too slow)") }),
        el("td", { text: String(a.one_way_hours) }),
        el("td", { text: rupees(a.fare_pp_round_trip) })))))));

  const a = it.accommodation;
  const stay = el("div", { class: "block" },
    el("h4", { text: "Where you stay" }),
    kv("Category", titleCase(a.tier)),
    kv("Rooms", `${a.rooms} room${a.rooms > 1 ? "s" : ""}`),
    kv("Nights", String(a.nights)),
    kv("Rate per room per night", rupees(a.rate_per_room_night)),
    kv("Stay total", rupees(a.total)),
    el("p", { class: "small", text: a.pricing_note }));

  const acts = el("div", { class: "block wide" },
    el("h4", { text: "Suggested activities" }),
    it.activities.length
      ? el("ul", { class: "plain acts" }, it.activities.map((x) => el("li", {},
          el("span", { text: x.name }), el("span", { text: x.cost_pp ? `${rupees(x.cost_pp)} / person` : "Free" }))))
      : el("p", { class: "small", text: "No paid activities were added to this plan. Free sightseeing is always possible." }));

  const b = it.budget;
  const lines = [["Transport", b.transport], ["Accommodation", b.accommodation], ["Food", b.food],
                 ["Local transport", b.local_transport], ["Activities", b.activities]];
  const level = b.percent_used > 95 ? "edge" : b.percent_used > 80 ? "tight" : "";
  const budget = el("div", { class: "block wide" },
    el("h4", { text: "Budget breakdown (estimates)" }),
    el("div", { class: "budget-table" }, lines.map(([label, amount]) =>
      el("div", { class: "budget-line" },
        el("span", { text: label }),
        el("div", { class: "bar" }, el("i", { style: `width:${b.total ? Math.round((amount / b.total) * 100) : 0}%` })),
        el("b", { text: rupees(amount) })))),
    el("div", { class: "budget-total" }, el("span", { text: "Estimated total" }), el("span", { text: rupees(b.total) })),
    el("div", { class: "remaining" },
      el("div", { class: "remaining-text" },
        el("span", { text: `Budget used: ${b.percent_used}% of ${rupees(b.budget)}` }),
        el("strong", { text: `Remaining: ${rupees(b.remaining)}` })),
      el("div", { class: `meter ${level}`, role: "img", "aria-label": `${b.percent_used}% of budget used` },
        el("i", { style: `width:${Math.min(b.percent_used, 100)}%` }))));

  return el("article", { class: "card trip" }, media,
    el("div", { class: "trip-main" },
      head,
      el("p", { class: "desc", text: d.description }),
      d.best_season ? el("p", { class: "season", text: `Best season: ${d.best_season}` }) : null,
      el("div", { class: "trip-cols" }, why, transport, stay, acts, budget)));
}

/* ------------------------------------------------------ destination photos */
function applyImage(media, d) {
  const colors = CATEGORY_COLORS[d.category] || CATEGORY_COLORS.nature;
  const emoji = options ? (options.categories.find((c) => c.id === d.category) || {}).emoji : "";
  media.style.background = `linear-gradient(135deg, ${colors[0]}, ${colors[1]})`;
  media.classList.add("fallback");
  media.append(el("span", { "aria-hidden": "true", text: emoji || "" }));
  if (!d.wiki_title) return;

  fetchImageUrl(d.wiki_title).then((url) => {
    if (!url) return;
    const probe = new Image();
    probe.onload = () => {
      media.style.background = `center / cover no-repeat url("${url}")`;
      media.classList.remove("fallback");
      media.lastElementChild.textContent = "";
      media.setAttribute("role", "img");
      media.setAttribute("aria-label", `Photo of ${d.name}`);
    };
    probe.src = url;                       // if this fails, the gradient stays
  });
}

async function fetchImageUrl(title) {
  if (imageCache.has(title)) return imageCache.get(title);
  let url = null;
  try {
    const res = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}`);
    if (res.ok) {
      const info = await res.json();
      if (info.thumbnail && info.thumbnail.source) url = info.thumbnail.source.replace(/\/\d+px-/, "/640px-");
    }
  } catch { /* offline or blocked: keep the gradient fallback */ }
  imageCache.set(title, url);
  return url;
}
