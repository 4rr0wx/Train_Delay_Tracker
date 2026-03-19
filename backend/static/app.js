let currentDirection = "to_wien";
let currentDays = 30;

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

// ---- Direction / period ----

function setDirection(dir) {
    currentDirection = dir;
    document.getElementById("btn-to-wien").classList.toggle("active", dir === "to_wien");
    document.getElementById("btn-to-ternitz").classList.toggle("active", dir === "to_ternitz");

    // Update leg titles
    if (dir === "to_wien") {
        document.getElementById("cjx-title").innerHTML = "Ternitz &rarr; Wien Meidling";
        document.getElementById("u6-title").innerHTML = "Wien Meidling &rarr; Wien Westbahnhof";
    } else {
        document.getElementById("cjx-title").innerHTML = "Wien Meidling &rarr; Ternitz";
        document.getElementById("u6-title").innerHTML = "Wien Westbahnhof &rarr; Wien Meidling";
    }
    refreshAll();
}

function setPeriod(days) {
    currentDays = parseInt(days);
    refreshAll();
}

// ---- Fetch ----

async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

function statsUrl(product) {
    return `/api/stats?direction=${currentDirection}&days=${currentDays}&product=${product}`;
}

function distUrl(product) {
    return `/api/delays/distribution?direction=${currentDirection}&days=${currentDays}&product=${product}`;
}

function trendUrl(product) {
    return `/api/delays/trend?direction=${currentDirection}&days=${currentDays}&product=${product}`;
}

function hourlyUrl(product) {
    return `/api/delays/hourly?direction=${currentDirection}&days=${currentDays}&product=${product}`;
}

function dailyUrl(product) {
    return `/api/delays/daily?direction=${currentDirection}&days=${currentDays}&product=${product}`;
}

// ---- Refresh ----

async function refreshAll() {
    await Promise.all([
        loadStats("regional", "cjx"),
        loadStats("subway", "u6"),
        loadDistribution("regional", "chart-dist-cjx", COLORS.train),
        loadDistribution("subway", "chart-dist-u6", COLORS.subway),
        loadTrend("regional", "chart-trend-cjx", COLORS.train),
        loadTrend("subway", "chart-trend-u6", COLORS.subway),
        loadHourly("regional", "chart-hourly-cjx", COLORS.train),
        loadDaily("regional", "chart-daily-cjx", COLORS.train),
        loadDepartures(),
    ]);
}

// ---- Stats cards ----

async function loadStats(product, prefix) {
    try {
        const data = await fetchJSON(statsUrl(product));
        const avgMin = data.delay_stats.average_minutes;

        document.getElementById(`${prefix}-total`).textContent = data.total_trains.toLocaleString("de-AT");
        document.getElementById(`${prefix}-avg-delay`).textContent =
            avgMin > 0 ? `${avgMin} Min` : "0 Min";
        document.getElementById(`${prefix}-cancelled`).textContent =
            `${data.cancelled_count} (${data.cancellation_rate_pct}%)`;
        document.getElementById(`${prefix}-on-time`).textContent =
            `${data.delay_stats.on_time_pct}%`;

        if (prefix === "cjx") {
            document.getElementById("empty-state").style.display =
                data.total_trains === 0 ? "block" : "none";
        }
    } catch (e) {
        console.error(`Failed to load stats (${product}):`, e);
    }
}

// ---- Charts ----

function destroyChart(id) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

async function loadDistribution(product, canvasId, color) {
    try {
        const data = await fetchJSON(distUrl(product));
        const ctx = document.getElementById(canvasId).getContext("2d");
        destroyChart(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: "bar",
            data: {
                labels: data.map(d => d.bucket),
                datasets: [{
                    data: data.map(d => d.count),
                    backgroundColor: DIST_COLORS,
                    borderRadius: 4,
                }],
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
        const data = await fetchJSON(trendUrl(product));
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
                        borderColor: color,
                        backgroundColor: color + "20",
                        fill: true,
                        tension: 0.3,
                        yAxisID: "y",
                    },
                    {
                        label: "Ausfälle",
                        data: data.map(d => d.cancelled_count),
                        borderColor: COLORS.danger,
                        backgroundColor: COLORS.danger + "40",
                        type: "bar",
                        yAxisID: "y1",
                    },
                ],
            },
            options: {
                responsive: true,
                interaction: { mode: "index", intersect: false },
                scales: {
                    y: { beginAtZero: true, position: "left", title: { display: true, text: "Verspätung (Min)" } },
                    y1: { beginAtZero: true, position: "right", title: { display: true, text: "Ausfälle" }, grid: { drawOnChartArea: false } },
                    x: { ticks: { maxTicksLimit: 10, maxRotation: 45 } },
                },
            },
        });
    } catch (e) { console.error(`Trend (${product}):`, e); }
}

async function loadHourly(product, canvasId, color) {
    try {
        const data = await fetchJSON(hourlyUrl(product));
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
                    backgroundColor: color,
                    borderRadius: 3,
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
        const data = await fetchJSON(dailyUrl(product));
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
                    backgroundColor: color,
                    borderRadius: 3,
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

// ---- Departures table ----

async function loadDepartures() {
    try {
        const data = await fetchJSON(`/api/departures?direction=${currentDirection}&limit=30`);
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
                statusClass = "status-cancelled";
                statusText = "Ausfall";
            } else if (d.delay_seconds >= 60) {
                statusClass = "status-delayed";
                statusText = `+${d.delay_minutes} Min`;
            } else {
                statusClass = "status-on-time";
                statusText = "Pünktlich";
            }

            tr.innerHTML = `
                <td>${time}</td>
                <td>${tag}</td>
                <td>${isSubway ? "U-Bahn" : "Zug"}</td>
                <td>${d.destination || "–"}</td>
                <td>${d.cancelled ? "–" : (d.delay_minutes > 0 ? `${d.delay_minutes} Min` : "0 Min")}</td>
                <td class="${statusClass}">${statusText}</td>
                <td>${d.platform || "–"}</td>
            `;
            tbody.appendChild(tr);
        }
    } catch (e) {
        console.error("Failed to load departures:", e);
    }
}

// Auto-refresh every 60 seconds
setInterval(refreshAll, 60000);

// Initial load
refreshAll();
