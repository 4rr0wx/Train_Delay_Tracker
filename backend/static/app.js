let currentDirection = "to_wien";
let currentDays = 30;

// Chart instances
let chartDistribution = null;
let chartTrend = null;
let chartHourly = null;
let chartDaily = null;

const CHART_COLORS = {
    primary: "#1e3a5f",
    accent: "#e63946",
    success: "#2d6a4f",
    warning: "#e9c46a",
    blue: "#457b9d",
    light: "#a8dadc",
};

function setDirection(dir) {
    currentDirection = dir;
    document.getElementById("btn-to-wien").classList.toggle("active", dir === "to_wien");
    document.getElementById("btn-to-ternitz").classList.toggle("active", dir === "to_ternitz");
    refreshAll();
}

function setPeriod(days) {
    currentDays = parseInt(days);
    refreshAll();
}

async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

async function refreshAll() {
    await Promise.all([
        loadStats(),
        loadDistribution(),
        loadTrend(),
        loadHourly(),
        loadDaily(),
        loadDepartures(),
    ]);
}

async function loadStats() {
    try {
        const data = await fetchJSON(`/api/stats?direction=${currentDirection}&days=${currentDays}`);
        document.getElementById("total-trains").textContent = data.total_trains.toLocaleString("de-AT");
        document.getElementById("avg-delay").textContent =
            data.delay_stats.average_minutes > 0
                ? `${data.delay_stats.average_minutes} Min`
                : "0 Min";
        document.getElementById("cancellation-rate").textContent = `${data.cancellation_rate_pct}%`;
        document.getElementById("on-time-rate").textContent = `${data.delay_stats.on_time_pct}%`;

        const emptyState = document.getElementById("empty-state");
        if (data.total_trains === 0) {
            emptyState.style.display = "block";
        } else {
            emptyState.style.display = "none";
        }
    } catch (e) {
        console.error("Failed to load stats:", e);
    }
}

async function loadDistribution() {
    try {
        const data = await fetchJSON(`/api/delays/distribution?direction=${currentDirection}&days=${currentDays}`);
        const labels = data.map((d) => d.bucket);
        const values = data.map((d) => d.count);

        const ctx = document.getElementById("chart-distribution").getContext("2d");
        if (chartDistribution) chartDistribution.destroy();

        chartDistribution = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Anzahl Züge",
                        data: values,
                        backgroundColor: [
                            CHART_COLORS.success,
                            CHART_COLORS.light,
                            CHART_COLORS.warning,
                            "#f4a261",
                            CHART_COLORS.accent,
                        ],
                        borderRadius: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: "Anzahl" } },
                },
            },
        });
    } catch (e) {
        console.error("Failed to load distribution:", e);
    }
}

async function loadTrend() {
    try {
        const data = await fetchJSON(`/api/delays/trend?direction=${currentDirection}&days=${currentDays}`);
        const labels = data.map((d) => d.date);
        const delays = data.map((d) => Math.round(d.avg_delay_seconds / 60 * 10) / 10);
        const cancellations = data.map((d) => d.cancelled_count);

        const ctx = document.getElementById("chart-trend").getContext("2d");
        if (chartTrend) chartTrend.destroy();

        chartTrend = new Chart(ctx, {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        label: "Ø Verspätung (Min)",
                        data: delays,
                        borderColor: CHART_COLORS.primary,
                        backgroundColor: CHART_COLORS.primary + "20",
                        fill: true,
                        tension: 0.3,
                        yAxisID: "y",
                    },
                    {
                        label: "Ausfälle",
                        data: cancellations,
                        borderColor: CHART_COLORS.accent,
                        backgroundColor: CHART_COLORS.accent + "40",
                        type: "bar",
                        yAxisID: "y1",
                    },
                ],
            },
            options: {
                responsive: true,
                interaction: { mode: "index", intersect: false },
                scales: {
                    y: {
                        beginAtZero: true,
                        position: "left",
                        title: { display: true, text: "Verspätung (Min)" },
                    },
                    y1: {
                        beginAtZero: true,
                        position: "right",
                        title: { display: true, text: "Ausfälle" },
                        grid: { drawOnChartArea: false },
                    },
                    x: {
                        ticks: {
                            maxTicksLimit: 10,
                            maxRotation: 45,
                        },
                    },
                },
            },
        });
    } catch (e) {
        console.error("Failed to load trend:", e);
    }
}

async function loadHourly() {
    try {
        const data = await fetchJSON(`/api/delays/hourly?direction=${currentDirection}&days=${currentDays}`);
        const allHours = Array.from({ length: 24 }, (_, i) => i);
        const dataMap = Object.fromEntries(data.map((d) => [d.hour, d.avg_delay_seconds]));
        const values = allHours.map((h) => Math.round((dataMap[h] || 0) / 60 * 10) / 10);

        const ctx = document.getElementById("chart-hourly").getContext("2d");
        if (chartHourly) chartHourly.destroy();

        chartHourly = new Chart(ctx, {
            type: "bar",
            data: {
                labels: allHours.map((h) => `${h}:00`),
                datasets: [
                    {
                        label: "Ø Verspätung (Min)",
                        data: values,
                        backgroundColor: CHART_COLORS.blue,
                        borderRadius: 3,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: "Minuten" } },
                },
            },
        });
    } catch (e) {
        console.error("Failed to load hourly:", e);
    }
}

async function loadDaily() {
    try {
        const data = await fetchJSON(`/api/delays/daily?direction=${currentDirection}&days=${currentDays}`);
        const dayOrder = [1, 2, 3, 4, 5, 6, 0]; // Mon-Sun
        const dayNames = {
            0: "So",
            1: "Mo",
            2: "Di",
            3: "Mi",
            4: "Do",
            5: "Fr",
            6: "Sa",
        };
        const dataMap = Object.fromEntries(data.map((d) => [d.day_of_week, d.avg_delay_seconds]));
        const labels = dayOrder.map((d) => dayNames[d]);
        const values = dayOrder.map((d) => Math.round((dataMap[d] || 0) / 60 * 10) / 10);

        const ctx = document.getElementById("chart-daily").getContext("2d");
        if (chartDaily) chartDaily.destroy();

        chartDaily = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Ø Verspätung (Min)",
                        data: values,
                        backgroundColor: CHART_COLORS.blue,
                        borderRadius: 3,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: "Minuten" } },
                },
            },
        });
    } catch (e) {
        console.error("Failed to load daily:", e);
    }
}

async function loadDepartures() {
    try {
        const data = await fetchJSON(`/api/departures?direction=${currentDirection}&limit=20`);
        const tbody = document.getElementById("departures-body");
        tbody.innerHTML = "";

        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#6b7280;">Keine Daten</td></tr>';
            return;
        }

        for (const d of data) {
            const tr = document.createElement("tr");
            const time = d.planned_time ? new Date(d.planned_time).toLocaleString("de-AT", {
                day: "2-digit",
                month: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
            }) : "–";

            let statusClass, statusText;
            if (d.cancelled) {
                statusClass = "status-cancelled";
                statusText = "Ausfall";
            } else if (d.delay_seconds && d.delay_seconds >= 300) {
                statusClass = "status-delayed";
                statusText = `+${d.delay_minutes} Min`;
            } else if (d.delay_seconds && d.delay_seconds >= 60) {
                statusClass = "status-delayed";
                statusText = `+${d.delay_minutes} Min`;
            } else {
                statusClass = "status-on-time";
                statusText = "Pünktlich";
            }

            tr.innerHTML = `
                <td>${time}</td>
                <td>${d.line_name || "–"}</td>
                <td>${d.line_product || "–"}</td>
                <td>${d.destination || "–"}</td>
                <td>${d.cancelled ? "–" : (d.delay_minutes > 0 ? `${d.delay_minutes} Min` : "0")}</td>
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
