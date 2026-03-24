// ============================================================
//  Global State
// ============================================================

const filterState = {
  dateFrom: null,
  dateTo: null,
  presetDays: 7,
  daysOfWeek: [1, 2, 3, 4, 5],  // Mon–Fri default
  direction: "to_wien",
  product: null,
  departureTimes: [],            // e.g. ["07:11", "07:40"]
};

let currentTab = "heute";
let statsDays = 30;
let journeyPage = 0;
let journeyPageSize = 50;
let journeyTotalCount = 0;

let todayViewDate = null;       // null = heute; "YYYY-MM-DD" = historische Ansicht
let todayEarliestDate = null;   // frühestes verfügbares Datum (Backend-Abfrage)

// Flexible commute state (Gleitzeit)
let todayTripsData = null;      // cached response from /api/commute/trips
let morningSelectedIdx = 0;     // index into todayTripsData.morning
let eveningSelectedIdx = 0;     // index into todayTripsData.evening

const charts = {};

// ÖBB-inspired color palette
const C = {
  red:    "#E2001A",
  dark:   "#1C1C1C",
  purple: "#8B2FC9",
  green:  "#00A550",
  orange: "#F5A623",
  grey:   "#D0D0D0",
  greenT: "rgba(0,165,80,0.15)",
  redT:   "rgba(226,0,26,0.15)",
  orangeT:"rgba(245,166,35,0.15)",
  darkT:  "rgba(28,28,28,0.08)",
};

const DIST_COLORS = [C.green, "#5BC8A0", C.orange, "#F08020", C.red];

Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 12;

// ============================================================
//  Utilities
// ============================================================

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function fmtDelay(minutes) {
  if (minutes === null || minutes === undefined) return "—";
  if (minutes === 0) return "0 Min";
  const sign = minutes > 0 ? "+" : "";
  return `${sign}${minutes} Min`;
}

function delayClass(seconds) {
  if (seconds === null || seconds === undefined) return "none";
  if (seconds < 60)  return "ok";
  if (seconds < 300) return "warn";
  return "bad";
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("de-AT", { hour: "2-digit", minute: "2-digit" });
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("de-AT", { weekday: "short", day: "numeric", month: "numeric" });
}

function fmtDateLong(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("de-AT", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

function buildFilterParams(extra = {}) {
  const p = new URLSearchParams();
  if (filterState.dateFrom) p.set("date_from", filterState.dateFrom);
  if (filterState.dateTo)   p.set("date_to", filterState.dateTo);
  if (!filterState.dateFrom && !filterState.dateTo) {
    p.set("days", String(filterState.presetDays));
  }
  if (filterState.daysOfWeek.length > 0 && filterState.daysOfWeek.length < 7) {
    p.set("days_of_week", filterState.daysOfWeek.join(","));
  }
  if (filterState.direction) p.set("direction", filterState.direction);
  if (filterState.product)   p.set("product", filterState.product);
  if (filterState.departureTimes.length > 0) {
    p.set("departure_times", filterState.departureTimes.join(","));
  }
  Object.entries(extra).forEach(([k, v]) => v !== null && v !== undefined && p.set(k, String(v)));
  return p;
}

function setRefreshLoading(loading) {
  const dot = document.getElementById("refresh-indicator");
  const lbl = document.getElementById("refresh-label");
  if (loading) {
    dot.classList.add("loading");
    lbl.textContent = "Lädt…";
  } else {
    dot.classList.remove("loading");
    lbl.textContent = "Live";
  }
}

// ============================================================
//  Tab switching
// ============================================================

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".bottom-nav-btn").forEach(el => el.classList.remove("active"));

  const content = document.getElementById(`tab-${tab}`);
  if (content) content.classList.add("active");
  const navBtn = document.getElementById(`nav-${tab}`);
  if (navBtn) navBtn.classList.add("active");
  const bnavBtn = document.getElementById(`bnav-${tab}`);
  if (bnavBtn) bnavBtn.classList.add("active");

  if (tab === "heute")       loadToday();
  else if (tab === "reisen") { journeyPage = 0; loadJourneys(); }
  else if (tab === "statistiken") loadStatistics();
  else if (tab === "umleitungen") loadDiversions();
}

// ============================================================
//  Filter controls
// ============================================================

function toggleFilter() {
  const body = document.getElementById("filter-body");
  const arrow = document.getElementById("filter-arrow");
  const isOpen = body.classList.contains("open");
  body.classList.toggle("open", !isOpen);
  arrow.classList.toggle("open", !isOpen);
}

function updateFilterBadge() {
  const badge = document.getElementById("filter-badge");
  const hasCustom = filterState.departureTimes.length > 0
    || filterState.product !== null
    || filterState.daysOfWeek.length !== 5
    || filterState.presetDays !== 7
    || filterState.dateFrom || filterState.dateTo;
  badge.style.display = hasCustom ? "inline" : "none";
}

function setPresetDays(days) {
  filterState.presetDays = days;
  filterState.dateFrom = null;
  filterState.dateTo = null;
  document.getElementById("filter-date-from").value = "";
  document.getElementById("filter-date-to").value = "";
  ["7", "30", "90"].forEach(d => {
    document.getElementById(`preset-${d}`).classList.toggle("active", String(days) === d);
  });
  updateFilterBadge();
  refreshCurrentTab();
}

function onCustomDate() {
  const from = document.getElementById("filter-date-from").value;
  const to   = document.getElementById("filter-date-to").value;
  filterState.dateFrom = from || null;
  filterState.dateTo   = to || null;
  ["7", "30", "90"].forEach(d => document.getElementById(`preset-${d}`).classList.remove("active"));
  updateFilterBadge();
  refreshCurrentTab();
}

function toggleDow(dow) {
  const idx = filterState.daysOfWeek.indexOf(dow);
  if (idx >= 0) {
    filterState.daysOfWeek.splice(idx, 1);
  } else {
    filterState.daysOfWeek.push(dow);
    filterState.daysOfWeek.sort();
  }
  document.getElementById(`dow-${dow}`).classList.toggle("active", filterState.daysOfWeek.includes(dow));
  updateFilterBadge();
  refreshCurrentTab();
}

function setDirection(dir) {
  filterState.direction = dir;
  document.getElementById("dir-wien").classList.toggle("active", dir === "to_wien");
  document.getElementById("dir-ternitz").classList.toggle("active", dir === "to_ternitz");
  updateFilterBadge();
  refreshCurrentTab();
}

function toggleTime(time) {
  const idx = filterState.departureTimes.indexOf(time);
  if (idx >= 0) {
    filterState.departureTimes.splice(idx, 1);
  } else {
    filterState.departureTimes.push(time);
  }
  document.getElementById("time-0711").classList.toggle("active", filterState.departureTimes.includes("07:11"));
  document.getElementById("time-0740").classList.toggle("active", filterState.departureTimes.includes("07:40"));
  document.getElementById("time-all").classList.toggle("active", filterState.departureTimes.length === 0);
  updateFilterBadge();
  refreshCurrentTab();
}

function clearTimes() {
  filterState.departureTimes = [];
  document.getElementById("time-0711").classList.remove("active");
  document.getElementById("time-0740").classList.remove("active");
  document.getElementById("time-all").classList.add("active");
  updateFilterBadge();
  refreshCurrentTab();
}

function setProduct(product) {
  filterState.product = product;
  document.getElementById("prod-cjx").classList.toggle("active", product === "regional");
  document.getElementById("prod-u6").classList.toggle("active", product === "subway");
  document.getElementById("prod-all").classList.toggle("active", product === null);
  updateFilterBadge();
  refreshCurrentTab();
}

function setStatsDays(days) {
  statsDays = days;
  ["7", "30", "90"].forEach(d => {
    document.getElementById(`sdays-${d}`).classList.toggle("active", String(days) === d);
  });
  loadStatistics();
}

function refreshCurrentTab() {
  if (currentTab === "heute")         loadToday();
  else if (currentTab === "reisen")   { journeyPage = 0; loadJourneys(); }
  else if (currentTab === "statistiken") loadStatistics();
  else if (currentTab === "umleitungen") loadDiversions();
}

// ============================================================
//  TODAY TAB
// ============================================================

function _todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function _isViewingToday() {
  return !todayViewDate || todayViewDate === _todayStr();
}

function navigateTodayDate(delta) {
  const base = todayViewDate
    ? new Date(todayViewDate + "T00:00:00")
    : new Date();
  base.setDate(base.getDate() + delta);
  const newStr = base.toISOString().slice(0, 10);
  todayViewDate = newStr >= _todayStr() ? null : newStr;
  loadToday();
}

function resetToToday() {
  todayViewDate = null;
  loadToday();
}

function updateTodayNavButtons() {
  const isToday = _isViewingToday();
  const viewStr = todayViewDate || _todayStr();

  const prevBtn = document.getElementById("heute-prev");
  const nextBtn = document.getElementById("heute-next");
  const resetBtn = document.getElementById("heute-reset");

  nextBtn.disabled = isToday;
  resetBtn.style.display = isToday ? "none" : "";

  if (todayEarliestDate) {
    prevBtn.disabled = viewStr <= todayEarliestDate;
  } else {
    prevBtn.disabled = false;
  }
}

async function loadToday() {
  const isToday = _isViewingToday();

  const displayDate = todayViewDate
    ? new Date(todayViewDate + "T00:00:00")
    : new Date();
  document.getElementById("today-date").textContent = fmtDateLong(displayDate.toISOString());

  const refreshEl = document.getElementById("today-refresh");
  if (isToday) {
    const now = new Date();
    refreshEl.textContent =
      "Automatisch aktualisiert um " + now.toLocaleTimeString("de-AT", { hour: "2-digit", minute: "2-digit" });
  } else {
    refreshEl.textContent = "Historische Ansicht – keine automatische Aktualisierung";
  }

  updateTodayNavButtons();
  setRefreshLoading(true);
  try {
    const url = todayViewDate
      ? `/api/commute/trips?date=${todayViewDate}`
      : "/api/commute/trips";
    const data = await fetchJSON(url);
    todayTripsData = data;

    // When loading fresh data, pick smart defaults only for today's view
    if (isToday) {
      morningSelectedIdx = _smartMorningIndex(data.morning);
      eveningSelectedIdx = _smartEveningIndex(data.evening);
    } else {
      // Historical: keep selection clamped to valid range
      morningSelectedIdx = Math.min(morningSelectedIdx, Math.max(0, data.morning.length - 1));
      eveningSelectedIdx = Math.min(eveningSelectedIdx, Math.max(0, data.evening.length - 1));
    }

    _buildTripDropdown("morning", data.morning, morningSelectedIdx);
    _buildTripDropdown("evening", data.evening, eveningSelectedIdx);
    renderMorningTrip();
    renderEveningTrip();

    const allUnseen = data.morning.length === 0 && data.evening.length === 0;
    const noDataBanner = document.getElementById("no-data-banner");
    if (noDataBanner) noDataBanner.style.display = allUnseen ? "flex" : "none";
  } catch (e) {
    console.error("Today load failed:", e);
  } finally {
    setRefreshLoading(false);
  }
}

/** Return the index of the train closest to the current time (for morning). */
function _smartMorningIndex(trips) {
  if (!trips || trips.length === 0) return 0;
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  // Prefer the next upcoming train, fallback to the latest past one
  let bestIdx = 0;
  let bestDiff = Infinity;
  trips.forEach((t, i) => {
    const [h, m] = t.cjx_dep.split(":").map(Number);
    const diff = h * 60 + m - nowMin;
    // Weight: upcoming trains slightly preferred; past trains OK too
    const score = diff >= 0 ? diff : -diff + 1000;
    if (score < bestDiff) { bestDiff = score; bestIdx = i; }
  });
  return bestIdx;
}

/** Return the index of the train closest to the current time (for evening). */
function _smartEveningIndex(trips) {
  if (!trips || trips.length === 0) return 0;
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  let bestIdx = 0;
  let bestDiff = Infinity;
  trips.forEach((t, i) => {
    const [h, m] = t.cjx_dep.split(":").map(Number);
    const diff = h * 60 + m - nowMin;
    const score = diff >= 0 ? diff : -diff + 1000;
    if (score < bestDiff) { bestDiff = score; bestIdx = i; }
  });
  return bestIdx;
}

function _buildTripDropdown(direction, trips, selectedIdx) {
  const rowEl = document.getElementById(`${direction}-selector-row`);
  const selectEl = document.getElementById(`${direction}-trip-select`);
  if (!rowEl || !selectEl) return;

  if (trips.length <= 1) {
    rowEl.style.display = "none";
    return;
  }
  rowEl.style.display = "flex";
  selectEl.innerHTML = trips.map((t, i) => {
    const label = direction === "morning"
      ? `CJX ${t.cjx_dep}${t.u6_dep ? " → U6 " + t.u6_dep : ""}`
      : `CJX ${t.cjx_dep}${t.u6_dep ? " (U6 " + t.u6_dep + ")" : ""}`;
    return `<option value="${i}"${i === selectedIdx ? " selected" : ""}>${label}</option>`;
  }).join("");
}

function selectTrip(direction, idx) {
  if (!todayTripsData) return;
  if (direction === "morning") {
    morningSelectedIdx = idx;
    renderMorningTrip();
  } else {
    eveningSelectedIdx = idx;
    renderEveningTrip();
  }
}

function renderMorningTrip() {
  if (!todayTripsData) return;
  const trips = todayTripsData.morning;
  if (trips.length === 0) {
    document.getElementById("morning-cards").innerHTML =
      `<div class="empty-state">Heute noch keine Morgenfahrten erfasst.</div>`;
    document.getElementById("morning-connection").style.display = "none";
    document.getElementById("morning-diversion-alert").style.display = "none";
    return;
  }
  const j = trips[morningSelectedIdx] || trips[0];
  document.getElementById("morning-cards").innerHTML = journeyCommuteCard(j, false);

  // Diversion alert for selected trip
  const divAlert = document.getElementById("morning-diversion-alert");
  if (divAlert) divAlert.style.display = j.is_diverted ? "" : "none";

  const hint = document.getElementById("morning-connection");
  const warn = j.cjx.today.seen_today && !j.cjx.today.cancelled && (j.cjx.today.delay_minutes || 0) > 4;
  hint.style.display = warn ? "flex" : "none";
  if (warn && j.u6_dep) {
    hint.innerHTML = `<span>&#9888;</span><span>CJX ${j.cjx_dep}: Verspätung – U6-Anschluss ${j.u6_dep} prüfen!</span>`;
  }
}

function renderEveningTrip() {
  if (!todayTripsData) return;
  const trips = todayTripsData.evening;
  if (trips.length === 0) {
    document.getElementById("evening-cards").innerHTML =
      `<div class="empty-state">Heute noch keine Abendfahrten erfasst.</div>`;
    document.getElementById("evening-connection").style.display = "none";
    document.getElementById("evening-diversion-alert").style.display = "none";
    return;
  }
  const j = trips[eveningSelectedIdx] || trips[0];
  document.getElementById("evening-cards").innerHTML = journeyCommuteCard(j, true);

  // Diversion alert for selected trip
  const divAlert = document.getElementById("evening-diversion-alert");
  if (divAlert) divAlert.style.display = j.is_diverted ? "" : "none";

  const hint = document.getElementById("evening-connection");
  const warn = j.u6 && j.u6.today.seen_today && !j.u6.today.cancelled && (j.u6.today.delay_minutes || 0) > 10;
  hint.style.display = warn ? "flex" : "none";
  if (warn) {
    hint.innerHTML = `<span>&#9888;</span><span>U6 stark verspätet – CJX-Anschluss ${j.cjx_dep} möglicherweise gefährdet!</span>`;
  }
}

function stationDelayClass(delaySeconds) {
  if (delaySeconds === null || delaySeconds === undefined) return "unknown";
  if (delaySeconds < 60)  return "ok";
  if (delaySeconds < 300) return "warn";
  return "bad";
}

function delayBadge(today) {
  if (!today.seen_today) return `<span class="delay-badge unknown">Noch nicht erfasst</span>`;
  if (today.cancelled)   return `<span class="delay-badge cancel">AUSFALL</span>`;
  const min = today.delay_minutes || 0;
  if (min < 1)  return `<span class="delay-badge ok">Pünktlich</span>`;
  if (min < 5)  return `<span class="delay-badge warn">+${min} Min</span>`;
  return `<span class="delay-badge bad">+${min} Min</span>`;
}

// Render a single leg (CJX or U6) as a compact sub-card within a journey card
function legCard(train) {
  const isSubway = train.product === "subway";
  const lineClass = isSubway ? "commute-card-line subway" : "commute-card-line";
  const ds = train.today.delay_seconds;
  const h = train.history_30d || {};

  const remarksHtml = (train.remarks && train.remarks.length > 0)
    ? `<div class="trip-remarks">${train.remarks.map(r =>
        `<span class="remark-item">\u26A0\uFE0F ${r.text}</span>`
      ).join("")}</div>`
    : "";

  return `
    <div class="leg-card ${train.today.cancelled ? 'cancelled-leg' : ''}">
      <div class="leg-header">
        <div class="leg-time">${train.planned_departure}</div>
        <span class="${lineClass}">${train.line}</span>
        <div class="leg-route">${train.from_station} &rarr; ${train.to_station}</div>
        <div class="leg-today">${delayBadge(train.today)}</div>
      </div>
      ${remarksHtml}
      <div class="commute-history">
        <span class="hist-item">Ø Verspätung (30T)</span>
        <span class="hist-value">${h.avg_delay_minutes ?? "—"} Min</span>
        <span class="hist-item">Pünktlichkeit</span>
        <span class="hist-value">${h.on_time_pct ?? "—"}%</span>
        <span class="hist-item">Ausfälle</span>
        <span class="hist-value">${h.cancelled_count ?? "—"} (${h.cancellation_rate_pct ?? "—"}%)</span>
        <span class="hist-item">Beobachtungen</span>
        <span class="hist-value">${h.total_observed ?? "—"}</span>
      </div>
    </div>`;
}

// Journey card groups two legs (CJX + optional U6) with a full station timeline
// Render a single station stop in the timeline.
// fallbackDs: anchor delay_seconds to show as estimate when station not yet observed.
function _stStop(label, data, forceDelay = null, extraCls = "", fallbackDs = null) {
  const seen = data?.seen;
  const ds = data?.delay_seconds;
  let cls, delayTxt;

  if (!seen && fallbackDs !== null && fallbackDs !== undefined) {
    cls = fallbackDs < 60 ? "ok" : fallbackDs < 300 ? "warn" : "bad";
    const min = Math.round(fallbackDs / 60);
    delayTxt = `~${fallbackDs > 0 ? "+" : ""}${min} Min`;
    extraCls = (extraCls + " st-estimated").trim();
  } else if (!seen) {
    cls = "unknown";
    delayTxt = "—";
  } else if (data.cancelled) {
    cls = "cancel";
    delayTxt = "AUSFALL";
  } else if (ds === null || ds === undefined) {
    cls = "ok";
    delayTxt = "0 Min";
  } else {
    cls = ds < 60 ? "ok" : ds < 300 ? "warn" : "bad";
    delayTxt = `${ds > 0 ? "+" : ""}${Math.round(ds / 60)} Min`;
  }
  if (forceDelay !== null) delayTxt = forceDelay;
  return `<div class="st-stop${extraCls ? " " + extraCls : ""}">
    <div class="st-dot ${cls}"></div>
    <div class="st-label">${label}</div>
    <div class="st-delay ${seen || (fallbackDs !== null && fallbackDs !== undefined) ? cls : ''}">${delayTxt}</div>
  </div>`;
}

/**
 * Determine the current CJX segment index (0-based) for the active train.
 * Returns { segmentIdx } where segmentIdx is the index of the st-line element
 * that is currently active (train is between station[i] and station[i+1]).
 * Returns null if the train is not currently en route.
 */
function _getCurrentCJXSegment(journey, isEvening) {
  if (!_isViewingToday()) return null;
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();

  const rawStations = !isEvening ? [
    { t: journey.cjx_dep },
    { t: journey.wiener_neustadt?.planned_time_local },
    { t: journey.baden?.planned_time_local },
    { t: journey.meidling_cjx?.planned_time_local },
  ] : [
    { t: journey.cjx_dep },
    { t: journey.baden?.planned_time_local },
    { t: journey.wiener_neustadt?.planned_time_local },
    { t: journey.ternitz?.planned_time_local },
  ];

  const pts = rawStations.map((s, i) => {
    if (!s.t) return null;
    const [h, m] = s.t.split(":").map(Number);
    return { idx: i, min: h * 60 + m };
  }).filter(Boolean);

  if (pts.length < 2) return null;
  const first = pts[0], last = pts[pts.length - 1];
  if (nowMin < first.min - 2 || nowMin > last.min + 30) return null;

  for (let i = 0; i < pts.length - 1; i++) {
    if (nowMin >= pts[i].min && nowMin < pts[i + 1].min) {
      // segmentIdx counts st-line elements in the CJX part of the timeline
      return { segmentIdx: pts[i].idx };
    }
  }
  return null;
}

function _stLine(segmentIdx, lineIdx, extraCls = "") {
  const isActive = segmentIdx !== null && lineIdx === segmentIdx;
  const cls = ["st-line", isActive ? "st-line-active" : "", extraCls].filter(Boolean).join(" ");
  return `<div class="${cls}"></div>`;
}

function journeyCommuteCard(journey, isEvening = false) {
  const cjx = journey.cjx;
  const u6  = journey.u6;  // may be null when no U6 connection was found

  const cjxDs = cjx.today.delay_seconds;
  const u6Ds  = u6 ? u6.today.delay_seconds : null;

  // Station data objects
  const ternitzData        = { seen: cjx.today.seen_today, delay_seconds: cjxDs, cancelled: cjx.today.cancelled };
  const westbhfData        = u6 ? { seen: u6.today.seen_today, delay_seconds: u6Ds, cancelled: u6.today.cancelled } : { seen: false };
  const meidlingData       = journey.meidling_cjx || { seen: false };
  const wnData             = journey.wiener_neustadt || { seen: false };
  const badenData          = journey.baden || { seen: false };
  const ternitzArrData     = journey.ternitz || ternitzData;

  // Fallback: show anchor delay as estimate at unobserved intermediate stations
  const anchorDs = cjx.today.seen_today ? cjxDs : null;

  // Detect current train position (returns null or {segmentIdx})
  const pos = _getCurrentCJXSegment(journey, isEvening);
  const seg = pos ? pos.segmentIdx : null;

  let timeline;
  if (!isEvening) {
    // Morning: Ternitz(0) → Wr.Neustadt(1) → Baden(2) → Meidling(3) → Westbhf(U6)
    // CJX segment lines: 0=Ternitz→WN, 1=WN→Baden, 2=Baden→Meidling
    const meidlingStop = _stStop("Meidling", meidlingData, u6 ? "Umstieg" : null,
      u6 ? "st-transfer" : "", meidlingData.seen ? null : anchorDs);
    const u6Part = u6 ? `
        ${_stLine(null, -1, "st-line-transfer")}
        ${_stStop("Westbhf", westbhfData)}` : "";
    timeline = `
      <div class="station-timeline">
        ${_stStop("Ternitz", ternitzData)}
        ${_stLine(seg, 0)}
        ${_stStop("Wr. Neustadt", wnData, null, "", wnData.seen ? null : anchorDs)}
        ${_stLine(seg, 1)}
        ${_stStop("Baden", badenData, null, "", badenData.seen ? null : anchorDs)}
        ${_stLine(seg, 2)}
        ${meidlingStop}
        ${u6Part}
      </div>`;
  } else {
    // Evening: (Westbhf U6) → Meidling(0) → Baden(1) → Wr.Neustadt(2) → Ternitz(3)
    // CJX segment lines: 0=Meidling→Baden, 1=Baden→WN, 2=WN→Ternitz
    const cjxAnchorAtMeidling = { seen: cjx.today.seen_today, delay_seconds: cjxDs, cancelled: cjx.today.cancelled };
    const u6Part = u6 ? `
        ${_stStop("Westbhf", westbhfData)}
        <div class="st-line"></div>` : "";
    const meidlingEvening = _stStop("Meidling", cjxAnchorAtMeidling, u6 ? "Umstieg" : null,
      u6 ? "st-transfer" : "");
    timeline = `
      <div class="station-timeline">
        ${u6Part}
        ${meidlingEvening}
        ${_stLine(seg, 0, u6 ? "st-line-transfer" : "")}
        ${_stStop("Baden", badenData, null, "", badenData.seen ? null : anchorDs)}
        ${_stLine(seg, 1)}
        ${_stStop("Wr. Neustadt", wnData, null, "", wnData.seen ? null : anchorDs)}
        ${_stLine(seg, 2)}
        ${_stStop("Ternitz", ternitzArrData, null, "", ternitzArrData.seen ? null : anchorDs)}
      </div>`;
  }

  const legParts = isEvening
    ? (u6 ? legCard(u6) + legCard(cjx) : legCard(cjx))
    : (u6 ? legCard(cjx) + legCard(u6) : legCard(cjx));

  return `
    <div class="commute-journey-card">
      ${timeline}
      <div class="commute-legs">
        ${legParts}
      </div>
    </div>`;
}

// ============================================================
//  JOURNEY LIST TAB
// ============================================================

async function loadJourneys() {
  setRefreshLoading(true);
  const list = document.getElementById("journey-list");
  list.innerHTML = `<div class="empty-state">Lade Reisedaten…</div>`;

  try {
    const params = buildFilterParams({ limit: journeyPageSize, offset: journeyPage * journeyPageSize });
    const data = await fetchJSON(`/api/journeys?${params}`);

    journeyTotalCount = data.total;
    const totalPages = Math.ceil(journeyTotalCount / journeyPageSize);
    document.getElementById("journey-count").textContent = journeyTotalCount.toLocaleString("de-AT");
    document.getElementById("page-indicator").textContent = `Seite ${journeyPage + 1} / ${Math.max(1, totalPages)}`;
    document.getElementById("btn-prev").disabled = journeyPage === 0;
    document.getElementById("btn-next").disabled = journeyPage >= totalPages - 1 || totalPages === 0;

    if (data.journeys.length === 0) {
      list.innerHTML = `<div class="empty-state">Keine Reisen für den gewählten Zeitraum gefunden.</div>`;
      return;
    }

    list.innerHTML = renderJourneyTable(data.journeys, filterState.direction || "to_wien");
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Fehler beim Laden der Daten.</div>`;
    console.error("Journeys load failed:", e);
  } finally {
    setRefreshLoading(false);
  }
}

function prevPage() { if (journeyPage > 0) { journeyPage--; loadJourneys(); } }
function nextPage() {
  if ((journeyPage + 1) * journeyPageSize < journeyTotalCount) { journeyPage++; loadJourneys(); }
}

// Station columns per direction
const JOURNEY_COLS = {
  to_wien:    ["ternitz", "wiener_neustadt", "baden", "wien_meidling"],
  to_ternitz: ["wien_meidling", "baden", "wiener_neustadt", "ternitz"],
};
const JOURNEY_COL_LABELS = {
  ternitz: "Ternitz", wiener_neustadt: "Wr. Neustadt",
  baden: "Baden", wien_meidling: "Meidling",
};

function _journeyDelayCellHtml(s) {
  if (!s || s.observed === false) return `<td class="delay-cell skipped">—</td>`;
  if (s.cancelled) return `<td class="delay-cell cancel">Ausfall</td>`;
  const ds = s.delay_seconds;
  if (ds === null || ds === undefined) return `<td class="delay-cell ok">0 Min</td>`;
  const min = Math.round(ds / 60);
  const cls = ds < 0 ? "recover" : ds < 60 ? "ok" : ds < 300 ? "warn" : "bad";
  return `<td class="delay-cell ${cls}">${ds > 0 ? "+" : ""}${min} Min</td>`;
}

function renderJourneyTable(journeys, direction) {
  const cols = JOURNEY_COLS[direction] || JOURNEY_COLS.to_wien;

  const thead = `<thead><tr>
    <th>Datum</th>
    <th>Abfahrt</th>
    <th>Linie</th>
    ${cols.map(c => `<th>${JOURNEY_COL_LABELS[c]}</th>`).join("")}
    <th>Status</th>
  </tr></thead>`;

  const rows = journeys.map(j => {
    const firstData = j.stations[cols[0]];
    const lastData  = j.stations[cols[cols.length - 1]];
    const depTime = firstData?.planned ? fmtTime(firstData.planned) : "—";
    const depDate = firstData?.planned ? fmtDate(firstData.planned) : "—";

    // Final status: based on last station's delay
    const anyCancelled = Object.values(j.stations).some(s => s?.cancelled);
    const lastDelay = lastData?.delay_seconds;
    let sCls = "ok", sTxt = "Pünktlich";
    if (anyCancelled)         { sCls = "cancel"; sTxt = "AUSFALL"; }
    else if (lastDelay >= 300){ sCls = "bad";    sTxt = `+${Math.round(lastDelay / 60)} Min`; }
    else if (lastDelay >= 60) { sCls = "warn";   sTxt = `+${Math.round(lastDelay / 60)} Min`; }

    const delayCells = cols.map(key => _journeyDelayCellHtml(j.stations[key])).join("");
    const divBadge = j.was_diverted
      ? `<span class="diversion-badge" title="Umleitung – kein Halt in Baden">&#9888;</span> ` : "";

    return `<tr class="${anyCancelled ? "row-cancelled" : ""}">
      <td class="col-date">${depDate}</td>
      <td class="col-time">${depTime}</td>
      <td>${divBadge}<span class="line-cjx">${j.line_name || "CJX"}</span></td>
      ${delayCells}
      <td><span class="status-badge ${sCls}">${sTxt}</span></td>
    </tr>`;
  }).join("");

  return `<table class="journey-data-table">${thead}<tbody>${rows}</tbody></table>`;
}

// ============================================================
//  STATISTICS TAB
// ============================================================

async function loadStatistics() {
  setRefreshLoading(true);
  try {
    await Promise.all([
      loadJourneyStats(),
      loadByStation(),
      loadDistribution("regional", "chart-dist-cjx", C.dark),
      loadDistribution("subway",   "chart-dist-u6",  C.purple),
      loadTrend("regional", "chart-trend"),
      loadDaily("regional", "chart-daily"),
      loadHourly("regional", "chart-hourly"),
      loadTrainComparison(),
      loadDepartures(),
    ]);
  } catch (e) {
    console.error("Statistics load failed:", e);
  } finally {
    setRefreshLoading(false);
  }
}

async function loadJourneyStats() {
  try {
    const params = buildFilterParams({ days: statsDays });
    const data = await fetchJSON(`/api/journeys/stats?${params}`);
    document.getElementById("stat-total").textContent = data.total_journeys.toLocaleString("de-AT");
    document.getElementById("stat-avg-delay").textContent =
      data.avg_delay_meidling_minutes > 0 ? `${data.avg_delay_meidling_minutes} Min` : "0 Min";
    document.getElementById("stat-on-time").textContent = `${data.on_time_pct}%`;
    document.getElementById("stat-cancelled").textContent =
      `${data.cancelled_count} (${data.cancellation_rate_pct}%)`;
    document.getElementById("stat-diversions").textContent =
      `${data.diversion_count} (${data.diversion_rate_pct}%)`;
    const added = data.delay_added_en_route_minutes;
    document.getElementById("stat-delay-added").textContent =
      added > 0 ? `+${added} Min` : (added < 0 ? `${added} Min` : "0 Min");
  } catch (e) {
    console.error("Journey stats failed:", e);
  }
}

async function loadByStation() {
  try {
    const p = new URLSearchParams({ direction: filterState.direction, days: statsDays });
    const data = await fetchJSON(`/api/delays/by-station?${p}`);
    const labels = data.map(d => d.station);
    const values = data.map(d => d.avg_delay_minutes);

    const colors = values.map(v => {
      if (v >= 5) return C.red;
      if (v >= 2) return C.orange;
      return C.green;
    });

    renderOrUpdateChart("chart-by-station", "bar", {
      labels,
      datasets: [{
        label: "Ø Verspätung (Min)",
        data: values,
        backgroundColor: colors,
        borderRadius: 4,
      }],
    }, {
      plugins: { legend: { display: false } },
      scales: {
        y: {
          title: { display: true, text: "Minuten" },
          beginAtZero: true,
        },
      },
    });
  } catch (e) {
    console.error("By-station failed:", e);
  }
}

async function loadDistribution(product, canvasId, color) {
  try {
    const p = new URLSearchParams({
      direction: filterState.direction,
      days: statsDays,
      product,
    });
    const data = await fetchJSON(`/api/delays/distribution?${p}`);
    renderOrUpdateChart(canvasId, "bar", {
      labels: data.map(d => d.bucket),
      datasets: [{
        label: "Fahrten",
        data: data.map(d => d.count),
        backgroundColor: DIST_COLORS.slice(0, data.length),
        borderRadius: 4,
      }],
    }, {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, title: { display: true, text: "Fahrten" } } },
    });
  } catch (e) { console.error(`Distribution ${product} failed:`, e); }
}

async function loadTrend(product, canvasId) {
  try {
    const p = new URLSearchParams({ direction: filterState.direction, days: statsDays, product });
    const data = await fetchJSON(`/api/delays/trend?${p}`);
    const labels = data.map(d => d.date);
    renderOrUpdateChart(canvasId, "bar", {
      labels,
      datasets: [
        {
          type: "line",
          label: "Ø Verspätung (Min)",
          data: data.map(d => d.avg_delay_seconds ? (d.avg_delay_seconds / 60).toFixed(1) : 0),
          borderColor: C.red,
          backgroundColor: "transparent",
          borderWidth: 2,
          tension: 0.3,
          pointRadius: 2,
          yAxisID: "y",
        },
        {
          type: "bar",
          label: "Fahrten",
          data: data.map(d => d.train_count),
          backgroundColor: C.darkT,
          borderRadius: 2,
          yAxisID: "y2",
        },
      ],
    }, {
      plugins: { legend: { position: "top" } },
      scales: {
        y:  { beginAtZero: true, title: { display: true, text: "Minuten" }, position: "left" },
        y2: { beginAtZero: true, title: { display: true, text: "Fahrten" }, position: "right", grid: { drawOnChartArea: false } },
        x:  { ticks: { maxTicksLimit: 10, maxRotation: 30 } },
      },
    });
  } catch (e) { console.error(`Trend ${product} failed:`, e); }
}

async function loadDaily(product, canvasId) {
  try {
    const p = new URLSearchParams({ direction: filterState.direction, days: statsDays, product });
    const data = await fetchJSON(`/api/delays/daily?${p}`);
    renderOrUpdateChart(canvasId, "bar", {
      labels: data.map(d => d.day_name),
      datasets: [{
        label: "Ø Verspätung (Min)",
        data: data.map(d => d.avg_delay_seconds ? (d.avg_delay_seconds / 60).toFixed(1) : 0),
        backgroundColor: C.dark,
        borderRadius: 4,
      }],
    }, {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, title: { display: true, text: "Minuten" } } },
    });
  } catch (e) { console.error("Daily failed:", e); }
}

async function loadHourly(product, canvasId) {
  try {
    const p = new URLSearchParams({ direction: filterState.direction, days: statsDays, product });
    const data = await fetchJSON(`/api/delays/hourly?${p}`);
    renderOrUpdateChart(canvasId, "bar", {
      labels: data.map(d => `${String(d.hour).padStart(2, "0")}:00`),
      datasets: [{
        label: "Ø Verspätung (Min)",
        data: data.map(d => d.avg_delay_seconds ? (d.avg_delay_seconds / 60).toFixed(1) : 0),
        backgroundColor: C.red,
        borderRadius: 4,
      }],
    }, {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, title: { display: true, text: "Minuten" } } },
    });
  } catch (e) { console.error("Hourly failed:", e); }
}

async function loadTrainComparison() {
  try {
    const times = ["07:11", "07:40"];
    const results = await Promise.all(
      times.map(t => fetchJSON(
        `/api/journeys/stats?direction=to_wien&days=30&days_of_week=1,2,3,4,5&departure_times=${t}`
      ))
    );

    renderOrUpdateChart("chart-compare-trains", "bar", {
      labels: times.map(t => `CJX ${t}`),
      datasets: [
        {
          label: "Ø Verspätung Abfahrt Ternitz (Min)",
          data: results.map(r => r.avg_delay_start_minutes),
          backgroundColor: C.dark,
          borderRadius: 4,
        },
        {
          label: "Ø Verspätung Ankunft Meidling (Min)",
          data: results.map(r => r.avg_delay_meidling_minutes),
          backgroundColor: C.red,
          borderRadius: 4,
        },
        {
          label: "Pünktlichkeitsrate (%)",
          data: results.map(r => r.on_time_pct),
          backgroundColor: C.green,
          borderRadius: 4,
          yAxisID: "y2",
        },
      ],
    }, {
      plugins: { legend: { position: "top" } },
      scales: {
        y:  { beginAtZero: true, title: { display: true, text: "Minuten" }, position: "left" },
        y2: { beginAtZero: true, max: 100, title: { display: true, text: "%" }, position: "right", grid: { drawOnChartArea: false } },
      },
    });
  } catch (e) { console.error("Train comparison failed:", e); }
}

async function loadDepartures() {
  const product = document.getElementById("table-product-filter")?.value || "";
  const status  = document.getElementById("table-status-filter")?.value || "";
  const dir = filterState.direction || "to_wien";

  const p = new URLSearchParams({ direction: dir, limit: 50 });
  if (product) p.set("product", product);
  if (status)  p.set("status", status);

  try {
    const data = await fetchJSON(`/api/departures?${p}`);
    const tbody = document.getElementById("departures-tbody");
    if (!tbody) return;
    tbody.innerHTML = data.map(row => {
      const delayMin = row.delay_minutes;
      const isCancelled = row.cancelled;
      const isSubway = row.line_product === "subway";
      let statusCls = "status-ok";
      let statusTxt = "Pünktlich";
      if (isCancelled)       { statusCls = "status-cancel"; statusTxt = "AUSFALL"; }
      else if (delayMin >= 5) { statusCls = "status-bad";    statusTxt = `+${delayMin} Min`; }
      else if (delayMin >= 1) { statusCls = "status-warn";   statusTxt = `+${delayMin} Min`; }

      const lineBadge = isSubway
        ? `<span class="line-u6">${row.line_name}</span>`
        : `<span class="line-cjx">${row.line_name}</span>`;

      return `<tr>
        <td>${row.planned_time ? new Date(row.planned_time).toLocaleTimeString("de-AT",{hour:"2-digit",minute:"2-digit"}) : "—"}</td>
        <td>${lineBadge}</td>
        <td>${row.train_number || "—"}</td>
        <td>${row.station_name || "—"}</td>
        <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis">${row.destination || "—"}</td>
        <td class="${statusCls}">${statusTxt}</td>
        <td class="${statusCls}">${isCancelled ? "Ausfall" : (delayMin < 1 ? "Pünktlich" : "Verspätet")}</td>
        <td>${row.platform || "—"}</td>
      </tr>`;
    }).join("");
  } catch (e) { console.error("Departures failed:", e); }
}

// ============================================================
//  DIVERSIONS TAB
// ============================================================

async function loadDiversions() {
  setRefreshLoading(true);
  const list = document.getElementById("diversion-list");
  list.innerHTML = `<div class="empty-state">Lade Umleitungsdaten…</div>`;

  try {
    const data = await fetchJSON("/api/diversions?days=90");

    document.getElementById("diversion-total").textContent = data.total_diversions.toLocaleString("de-AT");
    document.getElementById("diversion-period").textContent = `${data.period_days} Tage`;

    // Also load total journey count for rate calculation
    try {
      const statsData = await fetchJSON("/api/journeys/stats?direction=to_wien&days=90");
      const rate = statsData.diversion_rate_pct;
      document.getElementById("diversion-rate").textContent = `${rate}%`;
    } catch (_) {}

    if (data.diversions.length === 0) {
      list.innerHTML = `<div class="empty-state">Keine Umleitungen im Betrachtungszeitraum erkannt.<br><small>Hinweis: Die Erkennung ist erst ab Aktivierung der Baden-Erfassung möglich.</small></div>`;
      return;
    }

    list.innerHTML = data.diversions.map(d => {
      const dateStr = d.date ? new Date(d.date + "T00:00:00").toLocaleDateString("de-AT", {
        weekday: "long", day: "numeric", month: "long", year: "numeric"
      }) : "—";
      return `
        <div class="diversion-item">
          <div class="diversion-item-meta">
            <div class="diversion-item-date">${dateStr} &mdash; ${d.planned_departure}</div>
            <div class="diversion-item-line">${d.line_name || "CJX"} &bull; Kein Halt in Baden bei Wien</div>
          </div>
          <div class="diversion-item-delays">
            <div class="diversion-delay-item">
              <span class="diversion-delay-label">Ternitz</span>
              <span class="diversion-delay-value">${d.ternitz_delay_minutes > 0 ? '+' : ''}${d.ternitz_delay_minutes} Min</span>
            </div>
            ${d.meidling_delay_minutes !== null ? `
            <div class="diversion-delay-item">
              <span class="diversion-delay-label">Meidling</span>
              <span class="diversion-delay-value">${d.meidling_delay_minutes > 0 ? '+' : ''}${d.meidling_delay_minutes} Min</span>
            </div>` : ""}
          </div>
        </div>
      `;
    }).join("");
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Fehler beim Laden der Umleitungsdaten.</div>`;
    console.error("Diversions failed:", e);
  } finally {
    setRefreshLoading(false);
  }
}

// ============================================================
//  Chart helpers
// ============================================================

function renderOrUpdateChart(canvasId, type, chartData, options = {}) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const baseOptions = {
    responsive: true,
    maintainAspectRatio: true,
    animation: { duration: 300 },
    plugins: {
      legend: { labels: { font: { family: "'Inter', sans-serif", size: 11 } } },
      tooltip: { bodyFont: { family: "'Inter', sans-serif" } },
    },
    scales: {
      x: { ticks: { font: { family: "'Inter', sans-serif", size: 11 } } },
      y: { ticks: { font: { family: "'Inter', sans-serif", size: 11 } } },
    },
  };

  const mergedOptions = deepMerge(baseOptions, options);

  if (charts[canvasId]) {
    charts[canvasId].data = chartData;
    charts[canvasId].options = mergedOptions;
    charts[canvasId].update();
  } else {
    charts[canvasId] = new Chart(canvas, { type, data: chartData, options: mergedOptions });
  }
}

function deepMerge(target, source) {
  const result = { ...target };
  for (const key of Object.keys(source)) {
    if (source[key] && typeof source[key] === "object" && !Array.isArray(source[key])) {
      result[key] = deepMerge(target[key] || {}, source[key]);
    } else {
      result[key] = source[key];
    }
  }
  return result;
}

// ============================================================
//  Connection Stats
// ============================================================

async function loadConnectionStats() {
  try {
    const data = await fetchJSON("/api/commute/connection-stats?days=30");

    function _render(pct, badgeId, valueId) {
      const badge = document.getElementById(badgeId);
      const el    = document.getElementById(valueId);
      if (!badge || !el) return;
      if (pct === null || pct === undefined) return;
      el.textContent = `${pct}%`;
      el.className = `conn-rate-value ${pct >= 85 ? "good" : pct >= 65 ? "warn" : "bad"}`;
      badge.style.display = "";
    }

    _render(data.morning?.connection_made_pct, "conn-rate-morning", "conn-morning-pct");
    _render(data.evening?.connection_made_pct, "conn-rate-evening", "conn-evening-pct");
  } catch (_) {}
}

// ============================================================
//  Collection Health
// ============================================================

async function loadCollectionHealth() {
  try {
    const data = await fetchJSON("/api/health");
    const el = document.getElementById("collection-status");
    if (!el) return;
    const col = data.last_collection;
    if (!col || !col.last_collection_at) {
      el.className = "collection-status warn";
      el.textContent = "Keine Daten";
      el.title = "Noch keine Erfassung abgeschlossen";
      return;
    }
    const ageMs = Date.now() - new Date(col.last_collection_at).getTime();
    const ageMins = Math.round(ageMs / 60000);
    const statusFailed = col.last_collection_status === "failed";
    let cls, label;
    if (statusFailed || ageMins > 60) {
      cls = "old";
      label = statusFailed ? "Erfassung fehlgeschlagen" : `Vor ${ageMins} Min`;
    } else if (ageMins > 15) {
      cls = "warn";
      label = `Vor ${ageMins} Min`;
    } else {
      cls = "ok";
      label = ageMins < 2 ? "Gerade erfasst" : `Vor ${ageMins} Min`;
    }
    el.className = `collection-status ${cls}`;
    el.textContent = label;
    el.title = `Letzte Erfassung: ${new Date(col.last_collection_at).toLocaleTimeString("de-AT", { hour: "2-digit", minute: "2-digit" })} — Status: ${col.last_collection_status}`;
  } catch (_) {}
}

// ============================================================
//  Auto-refresh
// ============================================================

function startAutoRefresh() {
  setInterval(() => {
    if (currentTab === "heute" && _isViewingToday()) loadToday();
    loadCollectionHealth();
  }, 60_000);
}

// ============================================================
//  Init
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
  // Open filter panel by default on desktop
  if (window.innerWidth > 768) {
    document.getElementById("filter-body").classList.add("open");
    document.getElementById("filter-arrow").classList.add("open");
  }

  // Set today's date range defaults in date inputs
  const today = new Date();
  const sevenDaysAgo = new Date(today);
  sevenDaysAgo.setDate(today.getDate() - 7);
  document.getElementById("filter-date-to").value   = today.toISOString().slice(0, 10);
  document.getElementById("filter-date-from").value = sevenDaysAgo.toISOString().slice(0, 10);

  loadToday();
  loadCollectionHealth();
  loadConnectionStats();
  startAutoRefresh();

  // Fetch earliest date once to set back-navigation boundary
  fetchJSON("/api/commute/earliest-date").then(data => {
    todayEarliestDate = data.earliest_date;
    updateTodayNavButtons();
  }).catch(() => {});
});
