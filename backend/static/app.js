// ============================================================
//  State
// ============================================================
let currentDirection = "to_wien";
let currentDays = 30;
let currentTab = "overview";
let currentProductFilter = null;
let currentStatusFilter = null;

// Chart instances
const charts = {};

const COLORS = {
    train:   "#1e3a5f",
    subway:  "#8b2fc9",
    success: "#2d6a4f",
    warning: "#e9c46a",
    danger:  "#e63946",
    light:   "#a8dadc",
    orange:  "#f4a261",
};

const DIST_COLORS = [COLORS.success, COLORS.light, COLORS.warning, COLORS.orange, COLORS.danger];

// ============================================================
//  Tab switching
// ============================================================
function switchTab(tab) {
    currentTab = tab;
    document.getElementById("tab-overview").style.display = tab === "overview" ? "block" : "none";
    document.getElementById("tab-stats").style.display   = tab === "stats"    ? "block" : "none";
    document.querySelectorAll(".tab-btn").forEach((btn, i) => {
        btn.classList.toggle("active", (i === 0 && tab === "overview") || (i === 1 && tab === "stats"));
    });
    if (tab === "overview") loadOverview();
    else refreshStats();
}

// ============================================================
//  Direction / period (stats tab)
// ============================================================
function setDirection(dir) {
    currentDirection = dir;
    document.getElementById("btn-to-wien").classList.toggle("active", dir === "to_wien");
    document.getElementById("btn-to-ternitz").classList.toggle("active", dir === "to_ternitz");
    if (dir === "to_wien") {
        document.getElementById("cjx-title").innerHTML = "Ternitz &rarr; Wien Meidling";
        document.getElementById("u6-title").innerHTML  = "Wien Meidling &rarr; Wien Westbahnhof";
    } else {
        document.getElementById("cjx-title").innerHTML = "Wien Meidling &rarr; Ternitz";
        document.getElementById("u6-title").innerHTML  = "Wien Westbahnhof &rarr; Wien Meidling";
    }
    refreshStats();
}

function setPeriod(days) {
    currentDays = parseInt(days);
    refreshStats();
}

// ============================================================
//  Fetch helper
// ============================================================
async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

// ============================================================
//  Overview tab
// ============================================================
async function loadOverview() {
    // Show today's date
    const now = new Date();
    document.getElementById("overview-date").textContent = "Heute: " +
        now.toLocaleDateString("de-AT", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

    try {
        const data = await fetchJSON("/api/commute/overview");
        renderMorning(data.morning);
        renderEvening(data.evening);
    } catch (e) {
        console.error("Overview load failed:", e);
    }
}

function delayBadge(train) {
    const today = train.today;
    if (!today.seen_today) {
        return `<span class="delay-badge delay-unknown">Noch nicht erfasst</span>`;
    }
    if (today.cancelled) {
        return `<span class="delay-badge delay-cancelled">Ausfall</span>`;
    }
    const min = today.delay_minutes || 0;
    if (min < 1) {
        return `<span class="delay-badge delay-on-time">Pünktlich</span>`;
    } else if (min < 5) {
        return `<span class="delay-badge delay-slight">+${min} Min</span>`;
    } else {
        return `<span class="delay-badge delay-heavy">+${min} Min</span>`;
    }
}

function commuteCard(train) {
    const isSubway = train.product === "subway";
    const h = train.history_30d;
    const cardClass = train.today.cancelled ? "commute-card cancelled-card" :
                      isSubway ? "commute-card subway" : "commute-card";
    const lineClass = isSubway ? "commute-card-line subway" : "commute-card-line";

    return `
        <div class="${cardClass}">
            <div class="commute-card-time">${train.planned_departure}</div>
            <span class="${lineClass}">${train.line}</span>
            <div class="commute-card-route">${train.from_station} &rarr; ${train.to_station}</div>
            <div class="commute-today">
                <span class="today-label">Heute:</span>
                ${delayBadge(train)}
            </div>
            <div class="commute-history">
                <span class="hist-item">Ø Verspätung (30T)</span>
                <span class="hist-value">${h.avg_delay_minutes} Min</span>
                <span class="hist-item">Pünktlichkeit</span>
                <span class="hist-value">${h.on_time_pct}%</span>
                <span class="hist-item">Ausfälle</span>
                <span class="hist-value">${h.cancelled_count} (${h.cancellation_rate_pct}%)</span>
                <span class="hist-item">Beobachtungen</span>
                <span class="hist-value">${h.total_observed}</span>
            </div>
        </div>
    `;
}

function renderMorning(trains) {
    document.getElementById("morning-cards").innerHTML = trains.map(commuteCard).join("");

    // U6 connection hint
    // CJX 07:11 arrives Meidling ~07:55, next U6 ~08:00 → Westbahnhof ~08:06
    // CJX 07:40 arrives Meidling ~08:24, next U6 ~08:30 → Westbahnhof ~08:36
    const connections = {
        "07:11": { u6dep: "08:01", westbhf: "08:07" },
        "07:40": { u6dep: "08:30", westbhf: "08:36" },
    };

    const parts = trains.map(t => {
        const c = connections[t.planned_departure];
        if (!c) return "";
        const delayed = t.today.seen_today && !t.today.cancelled && t.today.delay_minutes > 4;
        const flag = delayed ? " ⚠ Verspätung – Anschluss prüfen!" : "";
        return `CJX ${t.planned_departure}: U6 ab Wien Meidling ca. ${c.u6dep} → Wien Westbahnhof ${c.westbhf}${flag}`;
    });

    document.getElementById("morning-connection").innerHTML =
        `<span>🔗</span><span><strong>U6-Anschluss:</strong> ${parts.join(" &nbsp;|&nbsp; ")}</span>`;
}

function renderEvening(trains) {
    document.getElementById("evening-cards").innerHTML = trains.map(commuteCard).join("");

    // CJX connection from Meidling after 16:15 U6 (arrives ~16:21) → Ternitz ~17:02
    const conn = "16:21";
    const ternitz = "~17:02";
    const t = trains[0];
    const delayed = t && t.today.seen_today && !t.today.cancelled && t.today.delay_minutes > 5;
    const flag = delayed ? " ⚠ Verspätung – Anschluss prüfen!" : "";

    document.getElementById("evening-connection").innerHTML =
        `<span>🔗</span><span><strong>CJX-Anschluss:</strong> Wien Meidling ab ca. ${conn} &rarr; Ternitz ${ternitz}${flag}</span>`;
}

// ============================================================
//  Stats tab
// ============================================================
async function refreshStats() {
    await Promise.all([
        loadStats("regional", "cjx"),
        loadStats("subway", "u6"),
        loadDistribution("regional", "chart-dist-cjx", COLORS.train),
        loadDistribution("subway",   "chart-dist-u6",  COLORS.subway),
        loadTrend("regional", "chart-trend-cjx", COLORS.train),
        loadTrend("subway",   "chart-trend-u6",  COLORS.subway),
        loadHourly("regional", "chart-hourly-cjx", COLORS.train),
        loadDaily("regional",  "chart-daily-cjx",  COLORS.train),
        loadDepartures(),
    ]);
}

async function loadStats(product, prefix) {
    try {
        const data = await fetchJSON(
            `/api/stats?direction=${currentDirection}&days=${currentDays}&product=${product}`
        );
        document.getElementById(`${prefix}-total`).textContent =
            data.total_trains.toLocaleString("de-AT");
        document.getElementById(`${prefix}-avg-delay`).textContent =
            data.delay_stats.average_minutes > 0 ? `${data.delay_stats.average_minutes} Min` : "0 Min";
        document.getElementById(`${prefix}-cancelled`).textContent =
            `${data.cancelled_count} (${data.cancellation_rate_pct}%)`;
        document.getElementById(`${prefix}-on-time`).textContent =
            `${data.delay_stats.on_time_pct}%`;
        if (prefix === "cjx") {
            document.getElementById("empty-state").style.display =
                data.total_trains === 0 ? "block" : "none";
        }
    } catch (e) { console.error(`Stats (${product}):`, e); }
}

// ---- Charts ----
function destroyChart(id) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

async function loadDistribution(product, canvasId, color) {
    try {
        const data = await fetchJSON(
            `/api/delays/distribution?direction=${currentDirection}&days=${currentDays}&product=${product}`
        );
        const ctx = document.getElementById(canvasId).getContext("2d");
        destroyChart(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: "bar",
            data: {
                labels: data.map(d => d.bucket),
                datasets: [{ data: data.map(d => d.count), backgroundColor: DIST_COLORS, borderRadius: 4 }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, title: { display: true, text: "Anzahl" } } },
            },
        });
    } catch (e) { console.error(`Distribution (${product}):`, e); }
}

async function loadTrend(product, canvasId, color) {
    try {
        const data = await fetchJSON(
            `/api/delays/trend?direction=${currentDirection}&days=${currentDays}&product=${product}`
        );
        const ctx = document.getElementById(canvasId).getContext("2d");
        destroyChart(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: "line",
            data: {
                labels: data.map(d => d.date),
                datasets: [
                    {
                        label: "Ø Verspätung (Min)",
                        data: data.map(d => Math.round(d.avg_delay_seconds / 60 * 10) / 10),
                        borderColor: color, backgroundColor: color + "20",
                        fill: true, tension: 0.3, yAxisID: "y",
                    },
                    {
                        label: "Ausfälle",
                        data: data.map(d => d.cancelled_count),
                        borderColor: COLORS.danger, backgroundColor: COLORS.danger + "40",
                        type: "bar", yAxisID: "y1",
                    },
                ],
            },
            options: {
                responsive: true,
                interaction: { mode: "index", intersect: false },
                scales: {
                    y:  { beginAtZero: true, position: "left",  title: { display: true, text: "Verspätung (Min)" } },
                    y1: { beginAtZero: true, position: "right", title: { display: true, text: "Ausfälle" }, grid: { drawOnChartArea: false } },
                    x:  { ticks: { maxTicksLimit: 10, maxRotation: 45 } },
                },
            },
        });
    } catch (e) { console.error(`Trend (${product}):`, e); }
}

async function loadHourly(product, canvasId, color) {
    try {
        const data = await fetchJSON(
            `/api/delays/hourly?direction=${currentDirection}&days=${currentDays}&product=${product}`
        );
        const allHours = Array.from({ length: 24 }, (_, i) => i);
        const map = Object.fromEntries(data.map(d => [d.hour, d.avg_delay_seconds]));
        const ctx = document.getElementById(canvasId).getContext("2d");
        destroyChart(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: "bar",
            data: {
                labels: allHours.map(h => `${h}:00`),
                datasets: [{
                    label: "Ø Verspätung (Min)",
                    data: allHours.map(h => Math.round((map[h] || 0) / 60 * 10) / 10),
                    backgroundColor: color, borderRadius: 3,
                }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, title: { display: true, text: "Minuten" } } },
            },
        });
    } catch (e) { console.error(`Hourly (${product}):`, e); }
}

async function loadDaily(product, canvasId, color) {
    try {
        const data = await fetchJSON(
            `/api/delays/daily?direction=${currentDirection}&days=${currentDays}&product=${product}`
        );
        const dayOrder = [1, 2, 3, 4, 5, 6, 0];
        const dayNames = { 0: "So", 1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa" };
        const map = Object.fromEntries(data.map(d => [d.day_of_week, d.avg_delay_seconds]));
        const ctx = document.getElementById(canvasId).getContext("2d");
        destroyChart(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: "bar",
            data: {
                labels: dayOrder.map(d => dayNames[d]),
                datasets: [{
                    label: "Ø Verspätung (Min)",
                    data: dayOrder.map(d => Math.round((map[d] || 0) / 60 * 10) / 10),
                    backgroundColor: color, borderRadius: 3,
                }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, title: { display: true, text: "Minuten" } } },
            },
        });
    } catch (e) { console.error(`Daily (${product}):`, e); }
}

const STATION_NAMES = {
    "1131839": "Ternitz",
    "1191201": "Wien Meidling",
    "915006": "Wien Westbahnhof",
};

function setProductFilter(product) {
    currentProductFilter = product;
    _updateFilterButtons(".table-filters .filter-group:first-child", product, [null, "regional", "subway"]);
    loadDepartures();
}

function setStatusFilter(status) {
    currentStatusFilter = status;
    _updateFilterButtons(".table-filters .filter-group:last-child", status, [null, "on_time", "delayed", "cancelled"]);
    loadDepartures();
}

function _updateFilterButtons(selector, activeValue, values) {
    const btns = document.querySelectorAll(`${selector} .filter-btn`);
    btns.forEach((btn, i) => {
        btn.classList.toggle("active", values[i] === activeValue);
    });
}

async function loadDepartures() {
    let url = `/api/departures?direction=${currentDirection}&limit=50`;
    if (currentProductFilter) url += `&product=${currentProductFilter}`;
    if (currentStatusFilter) url += `&status=${currentStatusFilter}`;
    try {
        const data = await fetchJSON(url);
        const tbody = document.getElementById("departures-body");
        tbody.innerHTML = "";
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#6b7280;">Keine Daten vorhanden</td></tr>';
            return;
        }
        for (const d of data) {
            const tr = document.createElement("tr");
            const time = d.planned_time
                ? new Date(d.planned_time).toLocaleString("de-AT", {
                    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
                })
                : "–";
            const isSubway = d.line_product === "subway";
            const tag = isSubway
                ? `<span class="tag-subway">${d.line_name || "U6"}</span>`
                : `<span class="tag-train">${d.line_name || "CJX"}</span>`;
            let statusClass, statusText;
            if (d.cancelled) {
                statusClass = "status-cancelled"; statusText = "Ausfall";
            } else if (d.delay_seconds >= 60) {
                statusClass = "status-delayed"; statusText = `+${d.delay_minutes} Min`;
            } else {
                statusClass = "status-on-time"; statusText = "Pünktlich";
            }
            const station = STATION_NAMES[d.station_id] || d.station_id || "–";
            tr.innerHTML = `
                <td>${time}</td>
                <td>${tag}</td>
                <td>${station}</td>
                <td>${d.destination || "–"}</td>
                <td>${d.cancelled ? "–" : (d.delay_minutes > 0 ? `${d.delay_minutes} Min` : "0 Min")}</td>
                <td class="${statusClass}">${statusText}</td>
                <td>${d.platform || "–"}</td>
            `;
            tbody.appendChild(tr);
        }
    } catch (e) { console.error("Departures:", e); }
}

// ============================================================
//  Auto-refresh + initial load
// ============================================================
setInterval(() => {
    if (currentTab === "overview") loadOverview();
    else refreshStats();
}, 60000);

// Start on overview tab
loadOverview();
