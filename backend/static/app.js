/* ============================================================
   THE ALPINE LEDGER — JavaScript Logic
   ============================================================ */

/**
 * State Management
 */
const state = {
  direction: 'to_wien', // or 'to_ternitz'
  currentTab: 'heute',
  dateOffset: 0, // 0 = today, -1 = yesterday, etc.
  
  // Filter states
  filter: {
    days: 30,
    dow: [1,2,3,4,5], // Mo-Fr
    times: [], // empty = all
    dateFrom: null,
    dateTo: null
  },
  statsDays: 30,
  
  // Pagination
  journeysPage: 1,
  journeysPerPage: 10,
  journeysTotal: 0,
  
  // Raw Data
  journeysData: [],
  departuresData: [],
  
  // Chart Instances
  charts: {}
};

/**
 * Initialization
 */
document.addEventListener('DOMContentLoaded', () => {
  initClock();
  updateDateDisplay();
  
  // Initial Loads
  loadHeuteData();
  
  // Refresh loop (every 60 seconds)
  setInterval(() => {
    if (state.currentTab === 'heute' && state.dateOffset === 0) {
      loadHeuteData();
    }
  }, 60000);
});

/**
 * Global UI & Navigation
 */
function switchTab(tabId) {
  state.currentTab = tabId;
  
  // Update Nav
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.getElementById(`nav-${tabId}`).classList.add('active');
  if(document.getElementById(`mnav-${tabId}`)) {
    document.getElementById(`mnav-${tabId}`).classList.add('active');
  }
  
  // Update Content
  document.querySelectorAll('.tab-content').forEach(el => {
    el.classList.remove('active');
    el.style.display = 'none';
  });
  const activeTab = document.getElementById(`tab-${tabId}`);
  activeTab.classList.add('active');
  activeTab.style.display = 'block';
  
  // Load specialized data
  if (tabId === 'heute') loadHeuteData();
  if (tabId === 'reisen') loadJourneys();
  if (tabId === 'statistiken') {
    loadStats();
  }
  if (tabId === 'rohdaten') loadDepartures();
  if (tabId === 'umleitungen') loadDiversions();
}

function setDirection(dir) {
  state.direction = dir;
  
  // UI toggle
  document.querySelectorAll('.toggle-btn').forEach(btn => btn.classList.remove('active'));
  document.getElementById(dir === 'to_wien' ? 'dir-to-wien' : 'dir-to-ternitz').classList.add('active');
  if(document.getElementById(dir === 'to_wien' ? 'mdir-wien' : 'mdir-ternitz')) {
    document.getElementById(dir === 'to_wien' ? 'mdir-wien' : 'mdir-ternitz').classList.add('active');
  }
  
  // Update editorial header
  const title = document.getElementById('editorial-route-title');
  title.innerHTML = dir === 'to_wien' ? 'Ternitz ↔ Wien' : 'Wien ↔ Ternitz';
  document.getElementById('route-kicker').innerText = dir === 'to_wien' ? 'Richtung Norden' : 'Richtung Süden';
  
  // Reload current tab
  switchTab(state.currentTab);
}

function toggleMobileMenu() {
  const menu = document.getElementById('mobile-menu');
  if(menu.style.display === 'none') {
    menu.style.display = 'flex';
  } else {
    menu.style.display = 'none';
  }
}

function initClock() {
  const clockEl = document.getElementById('live-clock');
  const dateEl = document.getElementById('live-date');
  
  function tick() {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' });
    dateEl.textContent = now.toLocaleDateString('de-AT', { weekday: 'long', day: 'numeric', month: 'short' });
  }
  tick();
  setInterval(tick, 1000);
}

/**
 * Util: Format duration to min
 */
function fmtDelay(sec) {
  if (!sec || sec <= 0) return '0 min';
  return Math.round(sec / 60) + ' min';
}

/**
 * API Fetch Wrapper
 */
async function fetchAPI(endpoint) {
  try {
    const res = await fetch(endpoint);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('API Error:', endpoint, err);
    return null;
  }
}

/* ============================================================
   TAB: HEUTE (LIVE)
   ============================================================ */
function updateDateDisplay() {
  const todayNav = document.getElementById('today-date');
  const resetBtn = document.getElementById('heute-reset');
  const d = new Date();
  d.setDate(d.getDate() + state.dateOffset);
  
  if (state.dateOffset === 0) {
    todayNav.textContent = 'Heute';
    resetBtn.style.display = 'none';
  } else if (state.dateOffset === -1) {
    todayNav.textContent = 'Gestern';
    resetBtn.style.display = 'inline-block';
  } else {
    todayNav.textContent = d.toLocaleDateString('de-AT', { weekday: 'short', day: '2-digit', month: '2-digit' });
    resetBtn.style.display = 'inline-block';
  }
  
  // Update collection status text
  const df = new Intl.DateTimeFormat('de-AT', { dateStyle: 'short' }).format(d);
  document.getElementById('collection-status').textContent = `Datenbestand: ${df}`;
  
  // Enable/disable arrows based on archive limit
  document.getElementById('heute-next').disabled = state.dateOffset >= 0;
  // Let's say archive goes back 90 days
  document.getElementById('heute-prev').disabled = state.dateOffset <= -90; 
}

function navigateDate(delta) {
  state.dateOffset += delta;
  if(state.dateOffset > 0) state.dateOffset = 0;
  updateDateDisplay();
  loadHeuteData();
}

function resetToToday() {
  state.dateOffset = 0;
  updateDateDisplay();
  loadHeuteData();
}

async function loadHeuteData() {
  const d = new Date();
  d.setDate(d.getDate() + state.dateOffset);
  const dateStr = d.toISOString().split('T')[0];
  
  // Build query
  const qStr = `?direction=${state.direction}&date=${dateStr}`;
  
  document.getElementById('today-refresh').textContent = `Letztes Update: ${new Date().toLocaleTimeString('de-AT', {hour:'2-digit', minute:'2-digit'})}`;
  
  // 1. Fetch KPI Stats
  const statsOpts = {
    group_by: "none",
    direction: state.direction,
    date_from: dateStr,
    date_to: dateStr
  };
  const statsRes = await fetchAPI('/api/stats?' + new URLSearchParams(statsOpts));
  
  if (statsRes && statsRes.data && statsRes.data.length > 0) {
    const s = statsRes.data[0];
    const onTimePerc = s.total_trains > 0 ? Math.round((s.on_time_trains / s.total_trains)*100) : 0;
    
    document.getElementById('kpi-ontime').textContent = `${onTimePerc}%`;
    document.getElementById('kpi-avg-delay').textContent = fmtDelay(s.avg_delay_seconds);
    document.getElementById('kpi-cancelled').textContent = s.cancelled_trains;
    document.getElementById('no-data-banner').style.display = 'none';
    document.getElementById('kpi-strip').style.display = 'grid';
  } else {
    // No data
    document.getElementById('no-data-banner').style.display = 'flex';
    document.getElementById('kpi-strip').style.display = 'none';
  }
  
  // 2. Fetch Commute Trips (Primary/Secondary concept)
  // For standard "to_wien" morning is primary. For "to_ternitz" evening is primary.
  const isWien = state.direction === 'to_wien';
  
  document.getElementById('section-primary-title').innerHTML = isWien ? 'Morgenpendel → Wien' : 'Morgenpendel → Ternitz';
  document.getElementById('section-secondary-title').innerHTML = isWien ? 'Abendpendel → Ternitz' : 'Abendpendel → Wien';
  
  // Fetch specific times
  const pTime = isWien ? '07:11' : '07:05'; // Morning
  const sTime = isWien ? '16:05' : '16:11'; // Evening
  
  const endpointPrimary = `/api/commute/trips?date=${dateStr}&time=${pTime}&direction=${isWien ? 'to_wien' : 'to_ternitz'}`;
  const endpointSecondary = `/api/commute/trips?date=${dateStr}&time=${sTime}&direction=${isWien ? 'to_ternitz' : 'to_wien'}`;
  
  const [dataP, dataS] = await Promise.all([ fetchAPI(endpointPrimary), fetchAPI(endpointSecondary) ]);
  
  renderCommuteSection('primary', dataP);
  renderCommuteSection('secondary', dataS);
}

function renderCommuteSection(slot, data) {
  const container = document.getElementById(`${slot}-cards`);
  const diversionEl = document.getElementById(`${slot}-diversion`);
  container.innerHTML = '';
  
  if (!data || !data.trips || data.trips.length === 0) {
    container.innerHTML = `<div class="editorial-empty body-md text-secondary">Keine Fahrten im ausgewählten Zeitfenster.</div>`;
    diversionEl.style.display = 'none';
    return;
  }
  
  let hasDiversion = false;
  
  // For simplicity, take the first trip
  const trip = data.trips[0];
  
  if (trip.cjx_diversion) hasDiversion = true;
  diversionEl.style.display = hasDiversion ? 'flex' : 'none';
  
  // Render CJX Part
  container.insertAdjacentHTML('beforeend', createScheduleCardHTML(trip.cjx_part, 'CJX9', 'Regionalexpress'));
  
  // Render U6 Part (if to Wien)
  if (trip.u6_part) {
    container.insertAdjacentHTML('beforeend', createScheduleCardHTML(trip.u6_part, 'U6', 'U-Bahn'));
  }
  
  // Connection logic
  const connEl = document.getElementById(`${slot}-connection`);
  if (trip.connection_status) {
    connEl.style.display = 'block';
    
    // The No-Border Rule: Use text weight/color instead of boxes
    if (trip.connection_status === 'OK') {
      connEl.innerHTML = `<strong>Anschluss:</strong> Erreicht. Umsteigezeit: ${fmtDelay(trip.transfer_time_seconds)}`;
      connEl.className = 'connection-status body-sm text-secondary mt-4';
    } else {
      connEl.innerHTML = `<strong>Anschluss Warnung:</strong> Umsteigen knapp oder verpasst.`;
      connEl.className = 'connection-status body-sm text-primary mt-4';
    }
  } else {
    connEl.style.display = 'none';
  }
}

function createScheduleCardHTML(part, lineType, desc) {
  if (!part) return '';
  const isDelayed = part.delay_seconds > 180;
  const isCancelled = part.status === 'cancelled';
  
  let statusText = 'PÜNKTLICH';
  let statusClass = 'ontime';
  if (isCancelled) { statusText = 'AUSFALL'; statusClass = 'delayed'; }
  else if (isDelayed) { statusText = `+${Math.round(part.delay_seconds/60)} MIN`; statusClass = 'delayed'; }
  
  const tArr = part.planned_arrival ? part.planned_arrival.substring(11, 16) : '--:--';
  const dest = part.to_station || 'Wien';
  const plat = part.platform || '-';
  
  const chipClass = lineType.startsWith('U') ? 'u6' : 'cjx';

  return `
    <div class="schedule-card ${isDelayed || isCancelled ? 'delayed' : ''} ${isCancelled ? 'sc-cancelled' : ''}">
      <div class="sc-time-col">
        <span class="sc-time">${tArr}</span>
        <span class="sc-status ${statusClass}">${statusText}</span>
      </div>
      <div class="sc-train-col">
        <span class="chip-line ${chipClass}">${lineType}</span>
      </div>
      <div class="sc-dest-col">
        <span class="sc-dest">${dest}</span>
        <span class="sc-via">${desc}</span>
      </div>
      <div class="sc-platform-col">
        <span class="sc-platform">${plat}</span>
        <span class="sc-plat-label">Gleis</span>
      </div>
      <div class="sc-action-col">
        <button class="btn-tertiary">View Details</button>
      </div>
    </div>
  `;
}

/* ============================================================
   TAB: REISEVERLAUF
   ============================================================ */
function toggleFilter() {
  const body = document.getElementById('filter-body');
  const icon = document.getElementById('filter-chevron');
  if(body.style.display === 'none') {
    body.style.display = 'block';
    icon.style.transform = 'rotate(180deg)';
  } else {
    body.style.display = 'none';
    icon.style.transform = 'rotate(0deg)';
  }
}

function setPresetDays(days) {
  state.filter.days = days;
  state.filter.dateFrom = null;
  state.filter.dateTo = null;
  
  ['preset-7', 'preset-30', 'preset-90'].forEach(id => document.getElementById(id).classList.remove('active'));
  document.getElementById(`preset-${days}`).classList.add('active');
  
  document.getElementById('filter-date-from').value = '';
  document.getElementById('filter-date-to').value = '';
  
  state.journeysPage = 1;
  loadJourneys();
}

function onCustomDate() {
  const from = document.getElementById('filter-date-from').value;
  const to = document.getElementById('filter-date-to').value;
  if(from && to) {
    state.filter.dateFrom = from;
    state.filter.dateTo = to;
    ['preset-7', 'preset-30', 'preset-90'].forEach(id => document.getElementById(id).classList.remove('active'));
    state.journeysPage = 1;
    loadJourneys();
  }
}

function toggleDow(day) {
  const idx = state.filter.dow.indexOf(day);
  const btn = document.getElementById(`dow-${day}`);
  if(idx > -1) {
    state.filter.dow.splice(idx, 1);
    btn.classList.remove('active');
  } else {
    state.filter.dow.push(day);
    btn.classList.add('active');
  }
  state.journeysPage = 1;
  loadJourneys();
}

function toggleTime(timeStr) {
  const idx = state.filter.times.indexOf(timeStr);
  const btn = document.getElementById(`time-${timeStr.replace(':','')}`);
  document.getElementById('time-all').classList.remove('active');
  
  if(idx > -1) {
    state.filter.times.splice(idx, 1);
    btn.classList.remove('active');
    if(state.filter.times.length === 0) clearTimes();
  } else {
    state.filter.times.push(timeStr);
    btn.classList.add('active');
  }
  state.journeysPage = 1;
  loadJourneys();
}

function clearTimes() {
  state.filter.times = [];
  document.querySelectorAll('[id^="time-"]').forEach(el => el.classList.remove('active'));
  document.getElementById('time-all').classList.add('active');
  state.journeysPage = 1;
  loadJourneys();
}

async function loadJourneys() {
  let url = `/api/journeys?page=${state.journeysPage}&limit=${state.journeysPerPage}&direction=${state.direction}`;
  
  if (state.filter.dateFrom && state.filter.dateTo) {
    url += `&date_from=${state.filter.dateFrom}&date_to=${state.filter.dateTo}`;
  } else if (state.filter.days) {
    const d = new Date();
    d.setDate(d.getDate() - state.filter.days);
    url += `&date_from=${d.toISOString().split('T')[0]}`;
  }
  
  if (state.filter.dow.length > 0) {
    url += `&dow=${state.filter.dow.join(',')}`;
  }
  if (state.filter.times.length > 0) {
    url += `&times=${state.filter.times.join(',')}`;
  }
  
  const res = await fetchAPI(url);
  if (!res) return;
  
  state.journeysTotal = res.total;
  
  document.getElementById('journey-count').textContent = res.total;
  document.getElementById('page-indicator').textContent = `Seite ${res.page} von ${res.pages}`;
  
  document.getElementById('btn-prev').disabled = res.page <= 1;
  document.getElementById('btn-next').disabled = res.page >= res.pages;
  
  renderJourneysList(res.data);
}

function prevPage() { if(state.journeysPage > 1) { state.journeysPage--; loadJourneys(); } }
function nextPage() { state.journeysPage++; loadJourneys(); }

function renderJourneysList(data) {
  const container = document.getElementById('journey-list');
  container.innerHTML = '';
  
  if(data.length === 0) {
    container.innerHTML = '<div class="editorial-empty body-md text-secondary">Keine Reisen gefunden.</div>';
    return;
  }
  
  data.forEach(trip => {
    // We treat each trip like a mini schedule card from the design system
    const dObj = new Date(trip.date);
    const dateStr = dObj.toLocaleDateString('de-AT', { weekday:'short', day:'2-digit', month:'2-digit', year:'numeric' });
    
    // Simplification for the 'Alpine Ledger' list:
    let isDelayed = false;
    let isCancelled = false;
    let totalDelay = 0;
    
    trip.legs.forEach(leg => {
      if(leg.status === 'cancelled') isCancelled = true;
      if(leg.delay_seconds > 180) isDelayed = true;
      totalDelay += (leg.delay_seconds || 0);
    });
    
    const div = document.createElement('div');
    div.className = `schedule-card ${isDelayed ? 'delayed' : ''} ${trip.has_diversion ? 'border-left-accent' : ''}`;
    
    let statusText = isCancelled ? 'AUSFALL' : (isDelayed ? `+${Math.round(totalDelay/60)} MIN` : 'PÜNKTLICH');
    let statusClass = isDelayed || isCancelled ? 'delayed' : 'ontime';
    
    // Assemble quick stops string
    const stopsStr = trip.legs.map(l => l.station_name).join(' → ');
    
    div.innerHTML = `
      <div class="sc-time-col" style="width: 100px;">
        <span class="sc-time body-md bold">${dateStr}</span>
        <span class="sc-status ${statusClass}">${statusText}</span>
      </div>
      <div class="sc-dest-col" style="grid-column: span 3;">
        <span class="sc-dest headline-sm">${trip.trip_name}</span>
        <span class="sc-via">${stopsStr}</span>
        ${trip.has_diversion ? '<span class="body-sm text-primary mt-2 flex align-center gap-2"><span class="material-symbols-outlined" style="font-size:16px;">alt_route</span> Umgeleitet (Kein Halt in Baden)</span>' : ''}
      </div>
      <div class="sc-action-col">
        <button class="btn-tertiary">Log >></button>
      </div>
    `;
    
    container.appendChild(div);
  });
}

/* ============================================================
   TAB: STATISTIKEN & CHARTS
   ============================================================ */
function setStatsDays(days) {
  state.statsDays = days;
  ['sdays-7', 'sdays-30', 'sdays-90'].forEach(id => document.getElementById(id).classList.remove('active'));
  document.getElementById(`sdays-${days}`).classList.add('active');
  loadStats();
}

// Chart defaults for Alpine Ledger Theme
const chStyle = {
  primary: '#b5000b',
  secondary: '#545f73',
  tertiary: '#0059a8',
  surface: '#f8f9ff',
  onSurface: '#0d1c2f',
  gridLine: 'rgba(13, 28, 47, 0.08)',
  font: 'Inter'
};

Chart.defaults.color = chStyle.secondary;
Chart.defaults.font.family = chStyle.font;
Chart.defaults.scale.grid.color = chStyle.gridLine;

async function loadStats() {
  const d = new Date();
  d.setDate(d.getDate() - state.statsDays);
  const fromStr = d.toISOString().split('T')[0];
  
  const baseParams = `?direction=${state.direction}&date_from=${fromStr}`;
  
  // 1. KPI Aggregation
  const aggRes = await fetchAPI('/api/stats' + baseParams + '&group_by=none');
  if (aggRes && aggRes.data && aggRes.data.length > 0) {
    const s = aggRes.data[0];
    document.getElementById('stat-total').textContent = s.total_trains;
    document.getElementById('stat-avg-delay').textContent = fmtDelay(s.avg_delay_seconds);
    document.getElementById('stat-on-time').textContent = s.on_time_trains;
    document.getElementById('stat-cancelled').textContent = s.cancelled_trains;
  }
  
  // 2. Load Charts
  await Promise.all([
    renderTrendChart(baseParams)
  ]);
}

function setupChart(id, config) {
  if (state.charts[id]) state.charts[id].destroy();
  const ctx = document.getElementById(id).getContext('2d');
  state.charts[id] = new Chart(ctx, config);
}

async function renderTrendChart(baseParams) {
  const res = await fetchAPI('/api/stats' + baseParams + '&group_by=date&product=regional');
  if(!res || !res.data) return;
  
  const labels = res.data.map(d => d.date.substring(5,10)); // MM-DD
  const data = res.data.map(d => Math.round(d.avg_delay_seconds / 60));
  
  setupChart('chart-trend', {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Ø Verspätung (min)',
        data,
        borderColor: chStyle.primary,
        backgroundColor: 'rgba(181, 0, 11, 0.1)',
        borderWidth: 2,
        tension: 0.1,
        fill: true,
        pointRadius: 0
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true } }
    }
  });
}


/* ============================================================
   TAB: ROW DATA LEDGER (Departures)
   ============================================================ */
async function loadDepartures() {
  const prod = document.getElementById('table-product-filter').value;
  const stat = document.getElementById('table-status-filter').value;
  
  let url = `/api/departures?limit=50&direction=${state.direction}`;
  if(prod) url += `&product=${prod}`;
  
  const res = await fetchAPI(url);
  if(!res || !res.data) return;
  
  let data = res.data;
  if(stat) {
    data = data.filter(d => {
      if(stat === 'cancelled') return d.status === 'cancelled';
      if(stat === 'delayed') return d.delay_seconds > 180;
      if(stat === 'on_time') return d.delay_seconds <= 180 && d.status !== 'cancelled';
      return true;
    });
  }
  
  renderTable(data);
}

function renderTable(data) {
  const tbody = document.getElementById('departures-tbody');
  tbody.innerHTML = '';
  
  data.forEach(d => {
    const isCancelled = d.status === 'cancelled';
    const isDelayed = d.delay_seconds > 180;
    
    let tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="bold">${d.planned_time.substring(11,16)}</td>
      <td><span class="chip-line ${d.product === 'subway' ? 'u6' : 'cjx'}">${d.line}</span></td>
      <td class="text-secondary">${d.train_number}</td>
      <td>${d.station_name}</td>
      <td class="bold">${d.direction_to}</td>
      <td class="${isDelayed ? 'text-primary bold' : ''}">${isCancelled ? '-' : fmtDelay(d.delay_seconds)}</td>
      <td><span class="chip-action ${isCancelled || isDelayed ? 'active bg-primary border-primary' : ''}" style="${isCancelled || isDelayed ? 'background: var(--primary); color: #fff; border-color: var(--primary);' : ''}">${isCancelled ? 'Ausfall' : (isDelayed ? 'Verspätet' : 'Pünktlich')}</span></td>
      <td class="text-center">${d.platform || '-'}</td>
    `;
    tbody.appendChild(tr);
  });
}


/* ============================================================
   TAB: UMLEITUNGEN
   ============================================================ */
async function loadDiversions() {
  const res = await fetchAPI(`/api/journeys?limit=100&direction=${state.direction}&has_diversion=true`);
  if(!res || !res.data) return;
  
  document.getElementById('diversion-total').textContent = res.total;
  
  const container = document.getElementById('diversion-list');
  container.innerHTML = '';
  
  res.data.forEach(trip => {
    const dObj = new Date(trip.date);
    const dateStr = dObj.toLocaleDateString('de-AT', { weekday:'long', day:'numeric', month:'long' });
    
    // Simplification for the 'Alpine Ledger' list:
    const div = document.createElement('div');
    div.className = `schedule-card border-left-accent`;
    
    div.innerHTML = `
      <div class="sc-time-col" style="width: 140px;">
        <span class="sc-time body-md bold">${dateStr}</span>
        <span class="sc-status delayed">UMLEITUNG</span>
      </div>
      <div class="sc-dest-col" style="grid-column: span 3;">
        <span class="sc-dest headline-sm">${trip.trip_name}</span>
        <span class="sc-via">Planmäßiger Halt in Baden entfallen.</span>
      </div>
      <div class="sc-action-col">
        <button class="btn-tertiary">Log >></button>
      </div>
    `;
    
    container.appendChild(div);
  });
}
