// ─── Overview page ────────────────────────────────────────────────────────
let charts = {};
let refreshTimer = null;

// ─── Theme (shares the "noc_theme" setting with the dashboard) ───────────
(function initTheme() {
    try {
        if (localStorage.getItem('noc_theme') === 'light') {
            document.body.classList.add('light');
            const btn = document.getElementById('themeToggle');
            if (btn) btn.textContent = '☀️';
        }
    } catch (e) { /* storage blocked: stay on the default theme */ }
})();

function toggleTheme() {
    const isLight = document.body.classList.toggle('light');
    const btn = document.getElementById('themeToggle');
    if (btn) btn.textContent = isLight ? '☀️' : '🌙';
    try { localStorage.setItem('noc_theme', isLight ? 'light' : 'dark'); } catch (e) {}
    if (window._lastData) buildCharts(window._lastData);   // charts read their colours from the theme
}

function cssVar(name) {
    return getComputedStyle(document.body).getPropertyValue(name).trim();
}

// ─── KPI tiles + health pill ──────────────────────────────────────────────
function renderKpis(s) {
    const set = (id, html, color) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = html;
        el.style.color = color || '';
    };
    const active = (s.total || 0) - (s.maintenance || 0);
    set('kpi-online', `${s.online || 0}<span class="unit">/${active}</span>`,
        s.online === active ? cssVar('--green') : (s.online > 0 ? cssVar('--yellow') : cssVar('--red')));
    set('kpi-offline', s.offline || 0, (s.offline || 0) === 0 ? cssVar('--green') : cssVar('--red'));
    set('kpi-maint', s.maintenance || 0, s.maintenance > 0 ? cssVar('--accent') : '');
    set('kpi-ms', s.avg_ms != null ? `${s.avg_ms}<span class="unit"> ms</span>` : '—');
    set('kpi-total', s.total || 0);

    const pill = document.getElementById('healthPill');
    const txt = document.getElementById('healthPillText');
    if (pill && txt) {
        pill.classList.remove('good', 'warn', 'bad');
        pill.classList.add(s.health || 'good');
        txt.textContent = s.health === 'good'
            ? 'All systems operational'
            : (s.health === 'warn' ? `${s.offline} server${s.offline === 1 ? '' : 's'} down` : 'All servers down');
    }
    const upd = document.getElementById('lastUpdated');
    if (upd) upd.textContent = `Last scan: ${s.last_scan || 'never'}`;
}

// ─── Charts ───────────────────────────────────────────────────────────────
function buildCharts(data) {
    if (typeof Chart === 'undefined') {
        const note = document.getElementById('chartNote');
        if (note) note.hidden = false;
        return;
    }
    Object.values(charts).forEach(c => { try { c.destroy(); } catch (e) {} });
    charts = {};

    const s = data.summary, hist = data.metrics_history || [], nodes = data.nodes || [];
    const green = cssVar('--green'), red = cssVar('--red'), yellow = cssVar('--yellow');
    const accent = cssVar('--accent'), text = cssVar('--text-dim'), grid = cssVar('--card-border');
    Chart.defaults.color = text;
    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
    const axis = { ticks: { color: text }, grid: { color: grid } };

    // 1) Status doughnut
    charts.status = new Chart(document.getElementById('chStatus'), {
        type: 'doughnut',
        data: {
            labels: ['Online', 'Offline', 'Maintenance'],
            datasets: [{ data: [s.online, s.offline, s.maintenance],
                         backgroundColor: [green, red, accent], borderColor: cssVar('--card-bg'), borderWidth: 2 }],
        },
        options: { maintainAspectRatio: false, cutout: '62%', plugins: { legend: { position: 'bottom' } } },
    });

    // 2) Servers online over time
    charts.online = new Chart(document.getElementById('chOnline'), {
        type: 'line',
        data: {
            labels: hist.map(h => h.ts),
            datasets: [
                { label: 'Online',  data: hist.map(h => h.online),  borderColor: green, backgroundColor: green + '33', fill: true, tension: 0.3, pointRadius: 0 },
                { label: 'Offline', data: hist.map(h => h.offline), borderColor: red,   backgroundColor: red + '33',   fill: true, tension: 0.3, pointRadius: 0 },
            ],
        },
        options: {
            maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            scales: { x: { ...axis, ticks: { color: text, maxTicksLimit: 8 } }, y: { ...axis, beginAtZero: true, ticks: { color: text, precision: 0 } } },
            plugins: { legend: { position: 'bottom' } },
        },
    });

    // 3) Response time per server (online only, slowest first, top 15)
    const timed = slowestServers(nodes);
    charts.resp = new Chart(document.getElementById('chResp'), {
        type: 'bar',
        data: {
            labels: timed.map(n => n.name),
            datasets: [{ label: 'ms', data: timed.map(n => n.ms),
                         backgroundColor: timed.map(n => msColour(n.ms)) }],
        },
        options: {
            maintainAspectRatio: false, indexAxis: 'y',
            scales: { x: { ...axis, beginAtZero: true }, y: { ...axis, grid: { display: false } } },
            plugins: { legend: { display: false } },
        },
    });
}

// Online servers only, slowest first, top 15 (shared by the first draw and the in-place update)
function slowestServers(nodes) {
    return nodes.filter(n => n.online && !n.in_maintenance && typeof n.ms === 'number')
                .sort((a, b) => b.ms - a.ms).slice(0, 15);
}
function msColour(ms) {
    return ms > 200 ? cssVar('--red') : ms > 50 ? cssVar('--yellow') : cssVar('--green');
}

// Refresh the existing charts in place. Rebuilding them on every refresh made all three replay their
// grow-in animation every few seconds; this only animates on the first draw.
function updateCharts(data) {
    const s = data.summary, hist = data.metrics_history || [];
    charts.status.data.datasets[0].data = [s.online, s.offline, s.maintenance];

    charts.online.data.labels = hist.map(h => h.ts);
    charts.online.data.datasets[0].data = hist.map(h => h.online);
    charts.online.data.datasets[1].data = hist.map(h => h.offline);

    const timed = slowestServers(data.nodes || []);
    charts.resp.data.labels = timed.map(n => n.name);
    charts.resp.data.datasets[0].data = timed.map(n => n.ms);
    charts.resp.data.datasets[0].backgroundColor = timed.map(n => msColour(n.ms));

    Object.values(charts).forEach(c => c.update('none'));   // 'none' = no animation
}

function renderCharts(data) {
    if (typeof Chart === 'undefined' || !charts.status) { buildCharts(data); return; }   // first draw (or no Chart.js)
    updateCharts(data);
}

// ─── Data refresh ─────────────────────────────────────────────────────────
async function loadOverview() {
    try {
        const resp = await fetch('/api/overview');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        window._lastData = data;
        renderKpis(data.summary);
        renderCharts(data);
    } catch (e) {
        console.error('Overview fetch error:', e);
        const upd = document.getElementById('lastUpdated');
        if (upd) upd.textContent = 'Could not load data - retrying…';
    }
}

loadOverview();
refreshTimer = setInterval(loadOverview, Math.max(10, SCAN_INTERVAL) * 1000);
