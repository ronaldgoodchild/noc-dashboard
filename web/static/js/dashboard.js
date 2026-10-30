// ─── State ───────────────────────────────────────────────────────────────
let state = { nodes: [], summary: {}, events: [] };
let countdown = 30;
let countdownTimer = null;
let refreshTimer = null;
let collapsedGroups = new Set();

// ─── API Helpers ─────────────────────────────────────────────────────────
async function api(url, opts = {}) {
    const defaults = { headers: { 'Content-Type': 'application/json' } };
    const resp = await fetch(url, { ...defaults, ...opts });
    if (!resp.ok) {
        let errMsg = `HTTP ${resp.status}`;
        try { const e = await resp.json(); errMsg = e.error || errMsg; } catch {}
        throw new Error(errMsg);
    }
    return resp.json();
}

// ─── Toast ───────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// ─── Data Refresh ────────────────────────────────────────────────────────
async function fetchStatus() {
    try {
        const data = await api('/api/status');
        state = data;
        renderCards();
        renderSummary();
        renderLog();
        updateTagFilter();
        countdown = data.summary.scan_interval || 30;
    } catch (e) {
        console.error('Fetch error:', e);
    }
}

function startCountdown() {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
        countdown--;
        document.getElementById('countdown').textContent = `${countdown}s`;
        if (countdown <= 0) {
            countdown = state.summary?.scan_interval || 30;
            fetchStatus();
        }
    }, 1000);
}

async function forceRefresh() {
    toast('🔄 Scan triggered...', 'info');
    await api('/api/refresh', { method: 'POST' });
    setTimeout(fetchStatus, 3000);
    countdown = state.summary?.scan_interval || 30;
}

// ─── Render Summary ──────────────────────────────────────────────────────
function renderSummary() {
    const s = state.summary;
    const active = s.total - s.maintenance;
    const offline = active - s.online;

    const onlineEl  = document.getElementById('hstat-online');
    const offlineEl = document.getElementById('hstat-offline');
    const maintEl   = document.getElementById('hstat-maint');

    if (onlineEl) {
        onlineEl.textContent = `${s.online}/${active}`;
        onlineEl.style.color = s.online === active ? 'var(--green)' : (s.online > 0 ? 'var(--yellow)' : 'var(--red)');
    }
    if (offlineEl) {
        offlineEl.textContent = offline;
        offlineEl.style.color = offline === 0 ? 'var(--green)' : (offline < active ? 'var(--yellow)' : 'var(--red)');
    }
    if (maintEl) {
        maintEl.textContent = s.maintenance || 0;
        maintEl.style.color = s.maintenance > 0 ? 'var(--accent)' : '#4a5568';
    }

    // Status-aware header glow
    const header = document.getElementById('mainHeader');
    if (header) {
        header.classList.remove('health-good', 'health-warn', 'health-bad');
        if (s.online === active)    header.classList.add('health-good');
        else if (s.online > 0)      header.classList.add('health-warn');
        else                        header.classList.add('health-bad');
    }

    document.getElementById('lastCheck').textContent = `Last: ${s.last_scan || 'never'}`;
}

// ─── Render Log ──────────────────────────────────────────────────────────
function renderLog() {
    const el = document.getElementById('logEntries');
    const events = state.events || [];
    el.innerHTML = events.slice().reverse().map(e =>
        `<div class="log-entry"><span class="log-ts">${e.ts}</span> <span class="log-${e.level}">[${e.level}]</span> ${escHtml(e.msg)}</div>`
    ).join('');
}

function clearLogDisplay() {
    document.getElementById('logEntries').innerHTML = '<div style="color:var(--text-dim);padding:1rem;">Log cleared (display only)</div>';
}

function toggleLog() {
    document.getElementById('logPanel').classList.toggle('collapsed');
}

// ─── Group constants ─────────────────────────────────────────────────────
const GROUP_COLORS = [
    '#0d9488','#3b82f6','#6366f1','#a855f7',
    '#f97316','#eab308','#22c55e','#ef4444',
];
const GROUP_ICON_MAP = {
    'nas':'🗄️','storage':'🗄️','nas & storage':'🗄️','nas storage':'🗄️',
    'virtualization':'⚡','virtual':'⚡','proxmox':'⚡',
    'media':'🎬','media services':'🎬',
    'security':'📹','cameras':'📹','security & cameras':'📹','security cameras':'📹',
    'casaos':'📦','casaos apps':'📦','apps':'📦',
    'network':'🌐','networking':'🌐',
    'cloud':'☁️','backup':'💾','database':'🗃️','home':'🏠',
};
function getGroupIcon(name) {
    return GROUP_ICON_MAP[name.toLowerCase()] || '🖥️';
}
function toggleGroup(name) {
    if (collapsedGroups.has(name)) collapsedGroups.delete(name);
    else collapsedGroups.add(name);
    renderGroups();
}

// ─── Render Groups ────────────────────────────────────────────────────────
function renderGroups() {
    const area      = document.getElementById('cardsArea');
    const search    = document.getElementById('searchBox').value.toLowerCase();
    const tagFilter = document.getElementById('tagFilter').value;

    const filtered = state.nodes.filter(n => {
        if (search) {
            const hay = `${n.name} ${n.ip} ${(n.tags||[]).join(' ')} ${n.description||''} ${(n.hosts||[]).map(h=>h.label).join(' ')}`.toLowerCase();
            if (!hay.includes(search)) return false;
        }
        if (tagFilter && !(n.tags||[]).includes(tagFilter)) return false;
        return true;
    });

    // Sort: favorites float to top within each group
    filtered.sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0));

    // Build ordered group map (first-seen order)
    const groupMap = new Map();
    filtered.forEach(n => {
        const g = n.group || 'Ungrouped';
        if (!groupMap.has(g)) groupMap.set(g, []);
        groupMap.get(g).push(n);
    });

    let gi = 0;
    area.innerHTML = [...groupMap.entries()].map(([g, gnodes]) => {
        const color  = GROUP_COLORS[gi++ % GROUP_COLORS.length];
        const icon   = getGroupIcon(g);
        const col    = collapsedGroups.has(g);
        const online = gnodes.filter(n => n.online && !n.in_maintenance).length;
        const total  = gnodes.length;
        const badgeColor = online === total ? 'var(--green)' : online > 0 ? 'var(--yellow)' : 'var(--red)';
        return `
        <div class="group-section" style="border-color:${color}40;">
            <div class="group-header" onclick="toggleGroup('${escHtml(g)}')" style="border-bottom-color:${color}22;">
                <span class="group-chevron">${col ? '▶' : '▼'}</span>
                <span class="group-icon">${icon}</span>
                <span class="group-title" style="color:${color}dd;">${escHtml(g)}</span>
                <span class="group-badge" style="color:${badgeColor};">${online}/${total}</span>
                <button class="btn btn-sm btn-outline group-add-btn"
                        onclick="event.stopPropagation();showAddServer('${escHtml(g)}')"
                        title="Add server to ${escHtml(g)}">➕</button>
            </div>
            <div class="group-cards${col ? ' collapsed' : ''}">
                ${gnodes.map(n => renderMiniCard(n)).join('')}
            </div>
        </div>`;
    }).join('');
}

function renderCards() { renderGroups(); }

// ─── Mini Card ────────────────────────────────────────────────────────────
function renderMiniCard(n) {
    const isMaint  = n.in_maintenance;
    const dotCls   = isMaint ? 'status-maint' : (n.online ? 'status-online'  : 'status-offline');
    const cardGlow = isMaint ? 'card-maint'   : (n.online ? 'card-online'    : 'card-offline');
    const msLabel  = isMaint ? 'MAINT'        : (n.online ? `${n.ms}ms`      : 'OFFLINE');
    const msCls    = isMaint ? 'is-maint'     : (n.online ? 'is-online'      : 'is-offline');

    // Icon
    const iconSlug = (n.icon || '').trim();
    const initial  = (n.name || '?').charAt(0).toUpperCase();
    const iconHtml = iconSlug
        ? `<div class="mini-icon">
               <img src="https://cdn.jsdelivr.net/gh/walkxcode/dashboard-icons@main/png/${escHtml(iconSlug)}.png"
                    alt="" loading="lazy"
                    onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
               <div class="mini-icon-fb" style="display:none;">${initial}</div>
           </div>`
        : `<div class="mini-icon"><div class="mini-icon-fb">${initial}</div></div>`;

    // IP / description subtitle
    const desc   = n.description || '';
    const ipLine = desc ? `${escHtml(desc)} · ${escHtml(n.ip)}` : escHtml(n.ip);

    // Tags
    const tags = (n.tags || []).map(t => `<span class="mini-tag">${escHtml(t)}</span>`).join('');

    // Connection badges
    const conns = (n.connections || []).map(c =>
        `<span class="mini-conn">${c.type}:${c.port}</span>`
    ).join('');

    // Uptime bar
    const upColor = n.uptime_pct >= 95 ? 'var(--green)' : n.uptime_pct >= 80 ? 'var(--yellow)' : 'var(--red)';

    // Sub-hosts
    const hosts = (n.hosts || []).map(h => {
        const dc = h.online ? 'status-online' : 'status-offline';
        const ms = h.online ? `${h.ms}ms` : 'offline';
        return `<div class="mini-host-row">
            <span class="mini-host-dot ${dc}"></span>
            <span>${escHtml(h.label)}</span>
            <span style="color:var(--text-dim);font-family:monospace;font-size:0.65rem;margin-left:0.2rem;">${h.ip}${h.port ? ':'+h.port : ''}</span>
            <span style="margin-left:auto;font-size:0.65rem;color:${h.online ? 'var(--green)' : 'var(--red)'}">${ms}</span>
        </div>`;
    }).join('');

    // Inline stat chips (Plex, Synology, etc.)
    const stats = (n.stats && n.stats.length)
        ? `<div class="mini-stats">${n.stats.map(s =>
            `<div class="mini-stat">
                <div class="mini-stat-val">${escHtml(String(s.val))}</div>
                <div class="mini-stat-lbl">${escHtml(s.lbl)}</div>
             </div>`).join('')}</div>`
        : '';

    // Footer buttons
    const manageBtn = n.manage_url
        ? `<a href="${escHtml(n.manage_url)}" target="_blank" class="btn btn-sm btn-primary" style="text-decoration:none;">🔗 ${escHtml(n.manage_label||'Manage')}</a>`
        : '';
    const wolBtn = n.mac
        ? `<button class="btn btn-sm btn-outline" onclick="wakeOnLan('${escHtml(n.mac)}')">⚡ WOL</button>` : '';
    const sysMon = n.show_sysmon
        ? `<button class="btn btn-sm btn-outline" onclick="showSystemInfo('${escHtml(n.ip)}')" title="CPU · RAM · Disks · Processes">📊 Info</button>` : '';

    // SSH / RDP one-click
    const sshConn = (n.connections || []).find(c => c.type === 'SSH');
    const rdpConn = (n.connections || []).find(c => c.type === 'RDP');
    const sshBtn  = sshConn
        ? `<a href="ssh://${escHtml(n.ip)}:${sshConn.port}" class="btn btn-sm btn-outline" style="text-decoration:none;" title="Open SSH session">🖲️ SSH</a>`
        : '';
    const rdpBtn  = rdpConn
        ? `<button class="btn btn-sm btn-outline" onclick="downloadRdp('${escHtml(n.ip)}')" title="Download RDP file">🖥️ RDP</button>`
        : '';

    // Sparkline (shown when data is available)
    const sparkHtml = (n.sparkline && n.sparkline.length > 3)
        ? `<div class="mini-sparkline">${renderSparkline(n.sparkline)}</div>` : '';

    // Last-seen line for offline nodes
    const lastSeen = (!n.online && !n.in_maintenance && n.last_check && n.last_check !== 'never')
        ? `<div class="mini-lastseen">⏱ Last seen: ${escHtml(n.last_check)}</div>` : '';

    // Notes badge
    const notesBadge = n.notes
        ? `<div class="mini-notes-badge" title="${escAttr(n.notes)}">📝 ${escHtml(n.notes.slice(0,80))}${n.notes.length > 80 ? '…' : ''}</div>` : '';

    // Copy-IP + Ping + Favorite buttons
    const copyBtn = `<button class="btn btn-sm btn-outline" onclick="copyToClipboard('${escHtml(n.ip)}',this)" title="Copy IP">📋</button>`;
    const pingBtn = `<button class="btn btn-sm btn-outline" onclick="livePing('${escHtml(n.ip)}')" title="Live Ping">📡 Ping</button>`;
    const favBtn  = `<span class="mini-fav" onclick="toggleFavorite('${escHtml(n.ip)}')" title="${n.favorite ? 'Unstar' : 'Star this server'}">${n.favorite ? '⭐' : '☆'}</span>`;

    // RustDesk button — always shown, uses rustdesk_id if set else falls back to IP
    const rdTarget  = n.rustdesk_id || n.ip.split(':')[0];
    const rustdeskBtn = `<button class="btn btn-sm btn-rustdesk" onclick="launchRustDesk('${escHtml(rdTarget)}','${escHtml(n.name)}')" title="Open in RustDesk → ${escHtml(rdTarget)}">🖥 RustDesk</button>`;

    // Power control — only for noc-agent tagged servers
    const hasAgent  = (n.tags||[]).some(t => t.toLowerCase() === 'noc-agent');
    const powerBtn  = hasAgent
        ? `<button class="btn btn-sm btn-warning" onclick="showPowerControl('${escHtml(n.ip)}','${escHtml(n.name)}')" title="Remote Power Control">⚡ Power</button>`
        : '';

    // Bulk-select checkbox
    const bulkChk = `<input type="checkbox" class="mini-check" data-ip="${escHtml(n.ip)}"
        onclick="event.stopPropagation();updateBulkCount()" title="Select for bulk action">`;

    // Custom card color override
    const colorStyle = n.card_color
        ? `style="border-color:${escAttr(n.card_color)}60;box-shadow:0 0 0 1px ${escAttr(n.card_color)}30,0 0 18px ${escAttr(n.card_color)}18;"` : '';

    return `<div class="mini-card ${cardGlow}" data-ip="${escHtml(n.ip)}" ${colorStyle}>
        ${bulkChk}
        <span class="mini-dot ${dotCls}" title="${msLabel}"></span>

        <div class="mini-header">
            ${iconHtml}
            <div class="mini-title-block">
                <div class="mini-name">${favBtn} ${escHtml(n.name)}</div>
                <div class="mini-ip">${ipLine}</div>
            </div>
            <span class="mini-ms ${msCls}">${msLabel}</span>
        </div>

        <div class="mini-body">
            ${tags  ? `<div class="mini-tags">${tags}</div>`   : ''}
            ${conns ? `<div class="mini-conns">${conns}</div>` : ''}
            <div class="mini-uptime">
                <span>Uptime: ${n.uptime_pct}%</span>
                <div class="mini-uptrack">
                    <div class="mini-upfill" style="width:${n.uptime_pct}%;background:${upColor}"></div>
                </div>
            </div>
            ${hosts ? `<div class="mini-hosts">${hosts}</div>` : ''}
            ${stats}
            ${sparkHtml}
            ${lastSeen}
            ${notesBadge}
        </div>

        <div class="mini-footer">
            ${manageBtn}
            ${wolBtn}
            ${sshBtn}
            ${rdpBtn}
            ${rustdeskBtn}
            ${sysMon}
            ${powerBtn}
            ${pingBtn}
            <button class="btn btn-sm btn-outline" onclick="showPortScan('${escHtml(n.ip)}')">🔍 Ports</button>
            <button class="btn btn-sm btn-outline" onclick="toggleMaintenance('${escHtml(n.ip)}')">🔧 Maint</button>
            ${copyBtn}
            <button class="btn btn-sm btn-outline" onclick="showEditServer('${escHtml(n.ip)}')">✏️ Edit</button>
            <button class="btn btn-sm btn-danger"  onclick="deleteServer('${escHtml(n.ip)}')">🗑️ Del</button>
        </div>
    </div>`;
}

function renderSparkline(data) {
    if (!data || data.length < 2) return '<svg class="sparkline" viewBox="0 0 300 32"><text x="150" y="20" fill="#94a3b8" text-anchor="middle" font-size="10">Collecting data...</text></svg>';
    const w = 300, h = 32, pad = 2;
    const validMs = data.filter(v => v > 0);
    const maxMs = Math.max(10, ...validMs);
    const step = (w - pad * 2) / (data.length - 1);
    let path = '';
    let dots = '';
    data.forEach((v, i) => {
        if (v < 0) return;  // skip offline points
        const x = pad + i * step;
        const y = h - pad - ((v / maxMs) * (h - pad * 2));
        if (!path) path = `M ${x} ${y}`;
        else path += ` L ${x} ${y}`;
        // Mark offline neighbors
        if (i > 0 && data[i-1] < 0) {
            dots += `<circle cx="${x}" cy="${y}" r="2" fill="var(--yellow)"/>`;
        }
    });
    // Fill area
    const firstValid = data.findIndex(v => v > 0);
    const lastValid = data.length - 1 - [...data].reverse().findIndex(v => v > 0);
    const fillPath = path + ` L ${pad + lastValid * step} ${h - pad} L ${pad + firstValid * step} ${h - pad} Z`;

    // Offline regions
    let offlineRects = '';
    let offStart = -1;
    data.forEach((v, i) => {
        if (v < 0 && offStart === -1) offStart = i;
        if ((v >= 0 || i === data.length - 1) && offStart !== -1) {
            const x1 = pad + offStart * step;
            const x2 = pad + (v < 0 ? i : i - 1) * step;
            offlineRects += `<rect x="${x1}" y="0" width="${Math.max(2, x2-x1)}" height="${h}" fill="rgba(239,68,68,0.1)"/>`;
            offStart = -1;
        }
    });

    return `<svg class="sparkline" viewBox="0 0 ${w} ${h}">
        ${offlineRects}
        <path d="${fillPath}" fill="rgba(59,130,246,0.15)" stroke="none"/>
        <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="1.5"/>
        ${dots}
    </svg>`;
}

// ─── Tag Filter ──────────────────────────────────────────────────────────
function updateTagFilter() {
    const sel = document.getElementById('tagFilter');
    const current = sel.value;
    const tags = new Set();
    state.nodes.forEach(n => (n.tags || []).forEach(t => tags.add(t)));
    sel.innerHTML = '<option value="">All Servers</option>' +
        [...tags].sort().map(t => `<option value="${t}" ${t===current?'selected':''}>${t}</option>`).join('');
}

function filterCards() { renderCards(); }

// ─── View mode ───────────────────────────────────────────────────────────
let _listView = false;
function toggleViewMode() {
    _listView = !_listView;
    const area = document.getElementById('cardsArea');
    const btn  = document.getElementById('viewToggleBtn');
    area.classList.toggle('list-view', _listView);
    btn.textContent  = _listView ? '🃏 Cards' : '📋 List';
    btn.classList.toggle('btn-view-active', _listView);
}

// ─── Bulk actions ────────────────────────────────────────────────────────
let _bulkMode = false;
function toggleBulkMode() {
    _bulkMode = !_bulkMode;
    document.getElementById('cardsArea').classList.toggle('bulk-mode', _bulkMode);
    document.getElementById('bulkBar').classList.toggle('active', _bulkMode);
    document.getElementById('bulkModeBtn').classList.toggle('btn-view-active', _bulkMode);
    if (!_bulkMode) { bulkClear(); }
}
function _selectedIps() {
    return [...document.querySelectorAll('.mini-check:checked')].map(el => el.dataset.ip);
}
function updateBulkCount() {
    document.getElementById('bulkCount').textContent = _selectedIps().length;
}
function bulkClear() {
    document.querySelectorAll('.mini-check').forEach(el => el.checked = false);
    updateBulkCount();
}
function bulkSelectAll() {
    document.querySelectorAll('.mini-check').forEach(el => el.checked = true);
    updateBulkCount();
}
async function bulkMaintenance(action) {
    const ips = _selectedIps();
    if (!ips.length) { toast('No servers selected', 'info'); return; }
    await api('/api/bulk-maintenance', { method:'POST', body:JSON.stringify({ips, action}) });
    toast(`🔧 Maintenance ${action === 'enter' ? 'ON' : 'OFF'} for ${ips.length} servers`, 'success');
    fetchStatus();
}
async function bulkMoveGroup() {
    const ips = _selectedIps();
    if (!ips.length) { toast('No servers selected', 'info'); return; }
    const group = prompt('Move selected servers to group:');
    if (group === null) return;
    await api('/api/bulk-group', { method:'POST', body:JSON.stringify({ips, group: group.trim()}) });
    toast(`📁 Moved ${ips.length} servers to "${group}"`, 'success');
    toggleBulkMode();
    fetchStatus();
}
async function bulkDelete() {
    const ips = _selectedIps();
    if (!ips.length) { toast('No servers selected', 'info'); return; }
    if (!confirm(`Delete ${ips.length} server(s)? This cannot be undone.`)) return;
    await api('/api/bulk-delete', { method:'POST', body:JSON.stringify({ips}) });
    toast(`🗑️ Deleted ${ips.length} servers`, 'success');
    toggleBulkMode();
    fetchStatus();
}

// ─── Favorite toggle ─────────────────────────────────────────────────────
async function toggleFavorite(ip) {
    const data = await api('/api/favorite', { method:'POST', body:JSON.stringify({ip}) });
    // Optimistic local update
    const node = state.nodes.find(n => n.ip === ip);
    if (node) node.favorite = data.favorite;
    renderCards();
}

// ─── RustDesk Launcher ───────────────────────────────────────────────────
async function launchRustDesk(target, name) {
    // Try URL scheme first (works if RustDesk is installed with protocol handler)
    const urlScheme = `rustdesk://connection/new/id=${encodeURIComponent(target)}`;

    openModal(`🖥 RustDesk — ${escHtml(name || target)}`,
    `<div style="text-align:center;padding:1rem 0;">
        <div style="font-size:3rem;margin-bottom:0.75rem;">🖥</div>
        <div style="font-size:1rem;font-weight:600;margin-bottom:0.25rem;">${escHtml(name || target)}</div>
        <div style="font-family:monospace;color:var(--accent);font-size:0.9rem;margin-bottom:1.5rem;">${escHtml(target)}</div>
        <div id="rdStatus" style="color:var(--text-dim);font-size:0.82rem;margin-bottom:1rem;">
            Click a button below to connect.
        </div>
        <div style="display:flex;flex-direction:column;gap:0.6rem;max-width:320px;margin:0 auto;">
            <button class="btn btn-primary" style="padding:0.7rem;"
                    onclick="rdLaunchUrl('${escHtml(urlScheme)}')">
                🚀 Open with RustDesk (URL scheme)
            </button>
            <button class="btn btn-outline" style="padding:0.7rem;"
                    onclick="rdLaunchServer('${escHtml(target)}')">
                🖥 Launch via NOC server
            </button>
        </div>
        <div style="margin-top:1.25rem;font-size:0.72rem;color:var(--text-dim);line-height:1.6;">
            <b>URL scheme</b> opens RustDesk directly in your browser if the app is installed.<br>
            <b>NOC server</b> calls the server machine to launch RustDesk there (useful when the<br>
            dashboard is open on the same PC where RustDesk is installed).
        </div>
        <div style="margin-top:1rem;padding:0.6rem;background:var(--card-border);border-radius:6px;font-size:0.72rem;text-align:left;">
            <b style="color:var(--text-dim);">Target ID / IP:</b>
            <span style="font-family:monospace;color:var(--accent);">${escHtml(target)}</span><br>
            <span style="color:var(--text-dim);">Change the RustDesk ID in ✏️ Edit → RustDesk ID field.</span>
        </div>
     </div>`, []);
}

function rdLaunchUrl(scheme) {
    document.getElementById('rdStatus').innerHTML =
        '<span style="color:var(--green);">✅ Opening RustDesk via URL scheme…</span>';
    window.location.href = scheme;
}

async function rdLaunchServer(target) {
    document.getElementById('rdStatus').innerHTML =
        '<span style="color:var(--accent);">⏳ Launching RustDesk on server…</span>';
    try {
        const data = await api('/api/launch-rustdesk',
            { method:'POST', body: JSON.stringify({ target }) });
        if (data.ok) {
            document.getElementById('rdStatus').innerHTML =
                `<span style="color:var(--green);">✅ RustDesk launched! (${escHtml(data.exe||'')})</span>`;
        } else {
            document.getElementById('rdStatus').innerHTML =
                `<span style="color:var(--red);">❌ ${escHtml(data.error||'Failed')}</span>
                 <div style="font-size:0.7rem;margin-top:0.4rem;color:var(--text-dim);">
                    Install RustDesk on this PC, or use the URL scheme button above.
                 </div>`;
        }
    } catch (e) {
        document.getElementById('rdStatus').innerHTML =
            `<span style="color:var(--red);">❌ ${escHtml(e.message)}</span>`;
    }
}

// ─── Remote Power Control ─────────────────────────────────────────────────
function showPowerControl(ip, name) {
    const actions = [
        { id:'reboot',    icon:'🔄', label:'Reboot',    desc:'Restarts in 10 seconds',    cls:'btn-warning' },
        { id:'shutdown',  icon:'⏹',  label:'Shutdown',  desc:'Powers off in 10 seconds',  cls:'btn-warning' },
        { id:'cancel',    icon:'🚫', label:'Cancel',    desc:'Abort pending shutdown/reboot', cls:'btn-outline' },
        { id:'lock',      icon:'🔒', label:'Lock',      desc:'Lock the screen now',        cls:'btn-outline' },
        { id:'sleep',     icon:'💤', label:'Sleep',     desc:'Put the PC to sleep',        cls:'btn-outline' },
        { id:'hibernate', icon:'❄️', label:'Hibernate', desc:'Hibernate the PC',           cls:'btn-outline' },
        { id:'logoff',    icon:'🚪', label:'Log Off',   desc:'Log off current user',       cls:'btn-outline' },
    ];
    const html = `
        <div style="text-align:center;margin-bottom:1rem;">
            <div style="font-size:0.85rem;color:var(--text-dim);">
                Sending command to <b style="color:var(--text);">${escHtml(name)}</b>
                via NOC Agent &nbsp;·&nbsp;
                <span style="font-family:monospace;color:var(--accent);">${escHtml(ip)}</span>
            </div>
            <div id="pwrStatus" style="margin-top:0.6rem;min-height:1.2rem;font-size:0.82rem;"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;">
            ${actions.map(a => `
            <button class="btn ${a.cls}" style="padding:0.65rem 0.5rem;text-align:left;display:flex;align-items:center;gap:0.5rem;"
                    onclick="sendPowerAction('${escHtml(ip)}','${a.id}','${escHtml(name)}')">
                <span style="font-size:1.2rem;">${a.icon}</span>
                <span>
                    <div style="font-weight:600;font-size:0.85rem;">${a.label}</div>
                    <div style="font-size:0.68rem;opacity:0.7;">${a.desc}</div>
                </span>
            </button>`).join('')}
        </div>
        <div style="margin-top:0.75rem;font-size:0.7rem;color:var(--text-dim);border-top:1px solid var(--card-border);padding-top:0.5rem;">
            ⚠️ Reboot &amp; Shutdown have a 10-second window — click Cancel to abort.
            Requires noc_agent.py running on <b>${escHtml(ip)}</b>.
        </div>`;
    openModal(`⚡ Power Control — ${escHtml(name)}`, html, []);
}

async function sendPowerAction(ip, action, name) {
    document.getElementById('pwrStatus').innerHTML =
        `<span style="color:var(--accent);">⏳ Sending ${action} to ${escHtml(name)}…</span>`;
    try {
        const data = await api('/api/power',
            { method:'POST', body: JSON.stringify({ ip, action }) });
        const ok = data.ok !== false && !data.error;
        document.getElementById('pwrStatus').innerHTML = ok
            ? `<span style="color:var(--green);">✅ ${escHtml(data.msg || action + ' sent')}</span>`
            : `<span style="color:var(--red);">❌ ${escHtml(data.error || 'Failed')}</span>`;
        if (ok) { setTimeout(fetchStatus, 15000); }
    } catch (e) {
        document.getElementById('pwrStatus').innerHTML =
            `<span style="color:var(--red);">❌ ${escHtml(e.message)}</span>`;
    }
}

// ─── Network Discovery ────────────────────────────────────────────────────
async function showNetworkScan() {
    // Auto-detect subnet from first server IP
    let guessSubnet = '10.0.0';
    if (state.nodes && state.nodes.length) {
        const firstIp = (state.nodes[0].ip || '').split(':')[0];
        if (firstIp.match(/^\d+\.\d+\.\d+/)) {
            guessSubnet = firstIp.split('.').slice(0,3).join('.');
        }
    }
    openModal('🔭 Network Discovery', `
        <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;align-items:flex-end;">
            <div style="flex:1;">
                <label style="display:block;font-size:0.8rem;color:var(--text-dim);margin-bottom:0.3rem;">
                    Subnet  (first 3 octets)
                </label>
                <input id="scanSubnet" value="${guessSubnet}"
                       style="width:100%;padding:0.5rem 0.75rem;background:#1e293b;border:1px solid #334155;border-radius:6px;color:var(--text);"
                       placeholder="e.g. 10.0.0">
            </div>
            <button class="btn btn-primary" onclick="runNetworkScan()" style="padding:0.55rem 1rem;">🔍 Scan</button>
        </div>
        <div id="scanStatus" style="font-size:0.8rem;color:var(--text-dim);margin-bottom:0.5rem;">
            Enter a subnet and click Scan. This scans .1–.254 for live hosts.
        </div>
        <div id="scanResults"></div>`, []);
}

async function runNetworkScan() {
    const subnet = document.getElementById('scanSubnet').value.trim();
    if (!subnet) { toast('Enter a subnet first', 'info'); return; }
    document.getElementById('scanStatus').innerHTML =
        `<span style="color:var(--accent);">⏳ Scanning ${escHtml(subnet)}.1–.254 … (may take 20-30s)</span>`;
    document.getElementById('scanResults').innerHTML = '';
    try {
        const data = await api('/api/network-scan',
            { method:'POST', body: JSON.stringify({ subnet }) });
        const hosts = data.hosts || [];
        document.getElementById('scanStatus').innerHTML =
            `<span style="color:var(--green);">✅ Found <b>${hosts.length}</b> live hosts</span>
             &nbsp;·&nbsp; <button class="btn btn-sm btn-success" onclick="addSelectedHosts()">➕ Add Selected to NOC</button>`;

        if (!hosts.length) {
            document.getElementById('scanResults').innerHTML =
                '<div style="color:var(--text-dim);padding:1rem;text-align:center;">No hosts found.</div>';
            return;
        }

        document.getElementById('scanResults').innerHTML = `
        <div style="max-height:380px;overflow-y:auto;margin-top:0.5rem;">
        <table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
            <thead><tr style="background:var(--card-border);">
                <th style="padding:0.4rem 0.5rem;text-align:left;width:32px;"></th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">IP</th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">Hostname</th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">Open Ports</th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">Detected Tags</th>
                <th style="padding:0.4rem 0.5rem;text-align:left;">Status</th>
            </tr></thead>
            <tbody>
            ${hosts.map((h,i) => `
                <tr style="background:${i%2===0?'var(--card-bg)':'#0d1629'};" data-host='${JSON.stringify(h).replace(/'/g,"&#39;")}'>
                    <td style="padding:0.3rem 0.5rem;">
                        ${h.known
                            ? `<span title="Already in NOC" style="color:var(--green);">✅</span>`
                            : `<input type="checkbox" class="scan-pick" data-ip="${escHtml(h.ip)}" data-hostname="${escHtml(h.hostname)}" data-tags="${escHtml((h.tags||[]).join(','))}" style="accent-color:var(--accent);">`
                        }
                    </td>
                    <td style="padding:0.3rem 0.5rem;font-family:monospace;color:var(--accent);">${escHtml(h.ip)}</td>
                    <td style="padding:0.3rem 0.5rem;color:var(--text-dim);">${escHtml(h.hostname||'—')}</td>
                    <td style="padding:0.3rem 0.5rem;font-family:monospace;font-size:0.7rem;color:var(--text-dim);">${(h.ports||[]).join(', ')}</td>
                    <td style="padding:0.3rem 0.5rem;">${(h.tags||[]).map(t=>`<span class="mini-tag">${escHtml(t)}</span>`).join(' ')}</td>
                    <td style="padding:0.3rem 0.5rem;font-size:0.7rem;color:${h.known?'var(--text-dim)':'var(--green)'};">${h.known?'In NOC':'New'}</td>
                </tr>`).join('')}
            </tbody>
        </table>
        </div>`;
    } catch (e) {
        document.getElementById('scanStatus').innerHTML =
            `<span style="color:var(--red);">❌ ${escHtml(e.message)}</span>`;
    }
}

function addSelectedHosts() {
    const picks = [...document.querySelectorAll('.scan-pick:checked')];
    if (!picks.length) { toast('Select at least one host', 'info'); return; }
    picks.forEach(el => {
        const tags = el.dataset.tags ? el.dataset.tags.split(',').filter(Boolean) : [];
        const name = el.dataset.hostname || el.dataset.ip;
        closeModal();
        // Open the Add Server form pre-filled
        const fakeNode = {
            group: '', description: '', name: name,
            ip: el.dataset.ip, tags,
            connections: [{ type: 'HTTP', port: 80 }],
            manage_url: '', manage_label: 'Manage',
            mac: '', api_key: '', icon: '', rustdesk_id: '',
            show_sysmon: tags.includes('noc-agent'),
        };
        const html = serverFormHtml(fakeNode);
        openModal(`➕ Add  ${escHtml(el.dataset.ip)}`, html, [
            { text: '💾 Save', class: 'btn-success', onclick: () => saveServer() },
        ]);
    });
}

// ─── Live Ping ───────────────────────────────────────────────────────────
async function livePing(ip) {
    const host = ip.split(':')[0];
    openModal(`📡 Live Ping — ${host}`,
        `<div id="pingResult" style="text-align:center;padding:2rem;font-family:monospace;">
            Pinging ${escHtml(host)}…
         </div>`, [
        { text: '🔁 Ping Again', class: 'btn-primary', onclick: () => livePing(ip) },
    ]);
    const data = await api('/api/ping', {
        method: 'POST',
        body: JSON.stringify({ host, count: 4 }),
    });
    if (data.error) {
        document.getElementById('pingResult').innerHTML =
            `<div style="color:var(--red);">⚠️ ${escHtml(data.error)}</div>`;
        return;
    }
    const lossColor = data.loss_pct === 0 ? 'var(--green)' : data.loss_pct < 50 ? 'var(--yellow)' : 'var(--red)';
    const rows = (data.results || []).map((ms, i) =>
        `<div style="padding:0.25rem 0;border-bottom:1px solid var(--card-border);">
            Reply ${i+1}: ${ms !== null
                ? `<span style="color:var(--green);">${ms} ms</span>`
                : `<span style="color:var(--red);">Timed out</span>`}
         </div>`
    ).join('');
    document.getElementById('pingResult').innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0.5rem;margin-bottom:1rem;">
            <div style="text-align:center;padding:0.5rem;background:var(--card-border);border-radius:6px;">
                <div style="font-size:1.1rem;font-weight:700;color:var(--green);">${data.min_ms ?? '—'} ms</div>
                <div style="font-size:0.7rem;color:var(--text-dim);">MIN</div>
            </div>
            <div style="text-align:center;padding:0.5rem;background:var(--card-border);border-radius:6px;">
                <div style="font-size:1.1rem;font-weight:700;color:var(--accent);">${data.avg_ms ?? '—'} ms</div>
                <div style="font-size:0.7rem;color:var(--text-dim);">AVG</div>
            </div>
            <div style="text-align:center;padding:0.5rem;background:var(--card-border);border-radius:6px;">
                <div style="font-size:1.1rem;font-weight:700;color:var(--yellow);">${data.max_ms ?? '—'} ms</div>
                <div style="font-size:0.7rem;color:var(--text-dim);">MAX</div>
            </div>
            <div style="text-align:center;padding:0.5rem;background:var(--card-border);border-radius:6px;">
                <div style="font-size:1.1rem;font-weight:700;color:${lossColor};">${data.loss_pct}%</div>
                <div style="font-size:0.7rem;color:var(--text-dim);">LOSS</div>
            </div>
        </div>
        <div style="font-size:0.75rem;color:var(--text-dim);margin-bottom:0.5rem;">
            Sent: ${data.sent}  ·  Received: ${data.received}  ·  Lost: ${data.lost}
        </div>
        <div style="font-family:monospace;font-size:0.82rem;">${rows}</div>`;
}

function toggleAllGroups() {
    const allGroups = [...new Set(state.nodes.map(n => n.group || 'Ungrouped'))];
    const allCollapsed = allGroups.every(g => collapsedGroups.has(g));
    if (allCollapsed) {
        collapsedGroups.clear();
        document.getElementById('collapseAllBtn').textContent = '⊟ Groups';
    } else {
        allGroups.forEach(g => collapsedGroups.add(g));
        document.getElementById('collapseAllBtn').textContent = '⊞ Groups';
    }
    renderGroups();
}

function copyToClipboard(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
        const orig = btn.textContent;
        btn.textContent = '✅';
        btn.style.color = 'var(--green)';
        setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 1500);
    }).catch(() => toast('❌ Copy failed', 'error'));
}

// ─── Actions ─────────────────────────────────────────────────────────────
async function showPortScan(ip) {
    openModal('🔍 Port Scan — ' + ip, '<div id="portResults" style="text-align:center;padding:2rem;">Scanning ports...</div>', []);
    const data = await api('/api/port-scan', { method: 'POST', body: JSON.stringify({ host: ip }) });
    const open = data.results.filter(r => r.open);
    const closed = data.results.filter(r => !r.open);
    document.getElementById('portResults').innerHTML = `
        <div style="margin-bottom:0.5rem;font-size:0.85rem;color:var(--green);">✅ ${open.length} open ports</div>
        <div class="port-results">
            ${open.map(r => `<div class="port-row port-open">✅ <b>${r.port}</b> — ${r.name}</div>`).join('')}
            ${closed.map(r => `<div class="port-row port-closed">❌ ${r.port} — ${r.name}</div>`).join('')}
        </div>`;
}

async function showSystemInfo(ip) {
    openModal('📊 System Info — ' + ip, '<div id="sysInfoContent" style="text-align:center;padding:2rem;">Querying system...</div>', []);
    const data = await api('/api/system-info', { method: 'POST', body: JSON.stringify({ ip }) });
    if (data.error) {
        document.getElementById('sysInfoContent').innerHTML = `<div style="color:var(--red);">⚠️ ${escHtml(data.error)}</div><div style="color:var(--text-dim);font-size:0.8rem;margin-top:0.5rem;">${escHtml(data.details?.error || '')}</div>`;
        return;
    }
    let html = `<div style="font-size:0.8rem;color:var(--text-dim);margin-bottom:1rem;">Type: ${data.type || 'Unknown'}</div>`;
    if (data.cpu_pct !== undefined) {
        const cpuColor = data.cpu_pct < 70 ? 'var(--green)' : (data.cpu_pct < 90 ? 'var(--yellow)' : 'var(--red)');
        html += `<div class="form-row"><label>CPU</label><div style="color:${cpuColor};font-size:1.1rem;font-weight:600;">${data.cpu_pct}%</div></div>`;
    }
    if (data.ram_pct !== undefined) {
        const ramColor = data.ram_pct < 70 ? 'var(--green)' : (data.ram_pct < 90 ? 'var(--yellow)' : 'var(--red)');
        html += `<div class="form-row"><label>RAM</label><div style="color:${ramColor};font-size:1.1rem;font-weight:600;">${data.ram_pct}% — ${data.ram_used_gb||'?'}GB / ${data.ram_total_gb||'?'}GB</div></div>`;
    }
    if (data.volumes && data.volumes.length) {
        html += '<div class="form-row"><label>Storage Volumes</label></div>';
        data.volumes.forEach(v => {
            const color = v.used_pct < 70 ? 'var(--green)' : (v.used_pct < 85 ? 'var(--yellow)' : 'var(--red)');
            html += `<div style="margin-bottom:0.5rem;">
                <div style="font-size:0.8rem;margin-bottom:0.2rem;">${escHtml(v.label)} — ${v.free_gb}GB free / ${v.total_gb}GB</div>
                <div style="background:#1e293b;border-radius:4px;overflow:hidden;height:20px;">
                    <div style="background:${color};height:100%;width:${v.used_pct}%;display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:600;">${v.used_pct}%</div>
                </div>
            </div>`;
        });
    }
    if (data.disks && data.disks.length) {
        html += '<div class="form-row"><label>Physical Disks</label></div>';
        data.disks.forEach(d => {
            const statusColor = d.status === 'normal' ? 'var(--green)' : 'var(--yellow)';
            html += `<div style="font-size:0.8rem;padding:0.2rem 0;">${escHtml(d.name)} — ${escHtml(d.model)} (${d.size_gb}GB) — <span style="color:${statusColor}">${d.status}</span> ${d.temp !== 'N/A' ? '🌡️'+d.temp+'°C' : ''}</div>`;
        });
    }
    // Plex
    if (data.type === 'plex') {
        html += `<div class="form-row"><label>Active Streams</label><div style="color:var(--green);font-size:1.1rem;font-weight:600;">${data.streams ?? 0}</div></div>`;
        if (data.movies !== undefined) html += `<div class="form-row"><label>Movies</label><div>${data.movies.toLocaleString()}</div></div>`;
        if (data.tv_shows !== undefined) html += `<div class="form-row"><label>TV Shows</label><div>${data.tv_shows.toLocaleString()}</div></div>`;
        if (data.music_artists !== undefined) html += `<div class="form-row"><label>Music Artists</label><div>${data.music_artists.toLocaleString()}</div></div>`;
    }
    // Sonarr
    if (data.type === 'sonarr') {
        html += `<div class="form-row"><label>Series</label><div>${data.series_count ?? 0} total, ${data.monitored ?? 0} monitored</div></div>`;
        html += `<div class="form-row"><label>Queue</label><div>${data.queue_count ?? 0} items</div></div>`;
    }
    // Radarr
    if (data.type === 'radarr') {
        html += `<div class="form-row"><label>Movies</label><div>${(data.movie_count ?? 0).toLocaleString()} total — ${data.downloaded ?? 0} downloaded</div></div>`;
        html += `<div class="form-row"><label>Monitored</label><div>${data.monitored ?? 0}</div></div>`;
        html += `<div class="form-row"><label>Queue</label><div>${data.queue_count ?? 0} items</div></div>`;
    }
    // Lidarr
    if (data.type === 'lidarr') {
        html += `<div class="form-row"><label>Artists</label><div>${data.artist_count ?? 0}</div></div>`;
        html += `<div class="form-row"><label>Queue</label><div>${data.queue_count ?? 0} items</div></div>`;
    }
    // SABnzbd
    if (data.type === 'sabnzbd') {
        const statusColor = data.status === 'Downloading' ? 'var(--green)' : 'var(--text-dim)';
        html += `<div class="form-row"><label>Status</label><div style="color:${statusColor};font-weight:600;">${escHtml(data.status ?? 'Unknown')}</div></div>`;
        html += `<div class="form-row"><label>Speed</label><div>${escHtml(data.speed ?? '0')} B/s</div></div>`;
        html += `<div class="form-row"><label>Queue</label><div>${data.queue_count ?? 0} items — ${data.queue_mb ?? 0} MB remaining</div></div>`;
        if (data.eta && data.eta !== 'N/A') html += `<div class="form-row"><label>ETA</label><div>${escHtml(data.eta)}</div></div>`;
    }
    // Immich
    if (data.type === 'immich') {
        html += `<div class="form-row"><label>Photos</label><div>${(data.photos ?? 0).toLocaleString()}</div></div>`;
        html += `<div class="form-row"><label>Videos</label><div>${(data.videos ?? 0).toLocaleString()}</div></div>`;
        html += `<div class="form-row"><label>Storage Used</label><div>${data.usage_gb ?? 0} GB</div></div>`;
    }
    // ── NOC Agent (Windows / Linux PC) ──────────────────────────────────────
    if (data.type === 'noc-agent') {
        html = '';   // reset and build from scratch for the agent

        // Header strip
        const upColor = !data.cpu_pct ? '#94a3b8'
            : data.cpu_pct < 60 ? 'var(--green)' : data.cpu_pct < 85 ? 'var(--yellow)' : 'var(--red)';
        html += `<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:1rem;">
            ${_agentStat(data.cpu_pct?.toFixed(1)+'%','CPU', data.cpu_pct)}
            ${_agentStat(data.ram_pct?.toFixed(1)+'%','RAM', data.ram_pct)}
            ${_agentStat(data.uptime_str||'?','UPTIME', 0)}
            ${_agentStat(data.proc_count||'?','PROCS', 0)}
        </div>`;

        // CPU detail
        html += _agentSection('CPU');
        html += `<div class="form-row"><label>Processor</label><div>${escHtml(data.cpu_name||'?')}</div></div>`;
        html += `<div class="form-row"><label>Cores</label><div>${data.cpu_cores_phys||'?'} physical / ${data.cpu_cores_logi||'?'} logical</div></div>`;
        if (data.cpu_freq_mhz) html += `<div class="form-row"><label>Frequency</label><div>${data.cpu_freq_mhz.toLocaleString()} MHz  (max ${(data.cpu_freq_max||0).toLocaleString()} MHz)</div></div>`;
        html += _agentBar('Overall Usage', data.cpu_pct||0);
        if (data.cpu_temps && data.cpu_temps.length) {
            data.cpu_temps.forEach(t => {
                const c = t.cur < 60 ? 'var(--green)' : t.cur < 80 ? 'var(--yellow)' : 'var(--red)';
                html += `<div class="form-row"><label>${escHtml(t.label)}</label><div style="color:${c}">${t.cur}°C <span style="color:var(--text-dim)">(max ${t.high}°C)</span></div></div>`;
            });
        }

        // RAM
        html += _agentSection('Memory');
        html += _agentBar('RAM Used', data.ram_pct||0, `${data.ram_used_gb||'?'} GB / ${data.ram_total_gb||'?'} GB`);
        html += `<div class="form-row"><label>Available</label><div style="color:var(--green)">${data.ram_free_gb||'?'} GB</div></div>`;
        if ((data.ram_cached_gb||0) > 0)
            html += `<div class="form-row"><label>Cached</label><div>${data.ram_cached_gb} GB</div></div>`;
        if ((data.swap_total_gb||0) > 0)
            html += _agentBar('Swap Used', data.swap_pct||0, `${data.swap_used_gb||'?'} GB / ${data.swap_total_gb||'?'} GB`);

        // Disks
        if (data.volumes && data.volumes.length) {
            html += _agentSection('Storage');
            data.volumes.forEach(v => {
                html += _agentBar(`${escHtml(v.label)} (${escHtml(v.fstype||'')})`,
                    v.used_pct, `${v.used_gb} GB used &nbsp;/&nbsp; ${v.total_gb} GB total &nbsp;·&nbsp; ${v.free_gb} GB free`);
            });
            if (data.disk_read_gb !== undefined)
                html += `<div class="form-row"><label>I/O since boot</label><div>Read ${data.disk_read_gb} GB &nbsp;·&nbsp; Written ${data.disk_write_gb} GB</div></div>`;
        }

        // Network
        if (data.net_ifaces && data.net_ifaces.length) {
            html += _agentSection('Network');
            data.net_ifaces.forEach(i => {
                html += `<div class="form-row"><label>${escHtml(i.name)}</label><div style="font-family:monospace;">${escHtml(i.ipv4)} <span style="color:var(--text-dim)">${i.mask ? '/ '+escHtml(i.mask) : ''}</span></div></div>`;
            });
            if (data.net_sent_gb !== undefined)
                html += `<div class="form-row"><label>Traffic since boot</label><div>Sent ${data.net_sent_gb} GB &nbsp;·&nbsp; Recv ${data.net_recv_gb} GB</div></div>`;
        }

        // Battery
        if (data.battery_pct !== undefined) {
            html += _agentSection('Battery');
            const bc = data.battery_pct > 40 ? 'var(--green)' : data.battery_pct > 20 ? 'var(--yellow)' : 'var(--red)';
            html += _agentBar('Charge', data.battery_pct, data.battery_plugged ? 'Charging' : 'On battery');
            if (!data.battery_plugged && data.battery_secs > 0) {
                const bh = Math.floor(data.battery_secs/3600), bm = Math.floor((data.battery_secs%3600)/60);
                html += `<div class="form-row"><label>Time remaining</label><div style="color:${bc}">${bh}h ${bm}m</div></div>`;
            }
        }

        // System
        html += _agentSection('System');
        html += `<div class="form-row"><label>Hostname</label><div>${escHtml(data.hostname||'?')}</div></div>`;
        html += `<div class="form-row"><label>OS</label><div>${escHtml(data.os||'?')}</div></div>`;
        html += `<div class="form-row"><label>Architecture</label><div>${escHtml(data.arch||'?')}</div></div>`;
        html += `<div class="form-row"><label>Uptime</label><div style="color:var(--green)">${escHtml(data.uptime_str||'?')}</div></div>`;
        html += `<div class="form-row"><label>Boot time</label><div>${escHtml(data.boot_time||'?')}</div></div>`;
        html += `<div class="form-row"><label>Users logged in</label><div>${data.users||0}</div></div>`;
        if (data.load_avg)
            html += `<div class="form-row"><label>Load avg (Linux)</label><div>${data.load_avg.map(v=>v.toFixed(2)).join(' / ')}</div></div>`;

        // Processes table
        if (data.processes && data.processes.length) {
            html += _agentSection(`Top Processes  (${data.proc_count||'?'} total)`);
            html += `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;font-family:monospace;">
                <thead><tr style="background:var(--card-border);color:var(--text);">
                    <th style="padding:0.4rem 0.6rem;text-align:right;">PID</th>
                    <th style="padding:0.4rem 0.6rem;text-align:left;">Process</th>
                    <th style="padding:0.4rem 0.6rem;text-align:right;">CPU%</th>
                    <th style="padding:0.4rem 0.6rem;text-align:right;">MEM%</th>
                    <th style="padding:0.4rem 0.6rem;text-align:right;">RAM</th>
                    <th style="padding:0.4rem 0.6rem;text-align:left;">User</th>
                </tr></thead><tbody>`;
            data.processes.forEach((p, i) => {
                const bg = i % 2 === 0 ? 'var(--card-bg)' : '#0d1629';
                const cpuC = p.cpu_pct > 50 ? 'var(--red)' : p.cpu_pct > 20 ? 'var(--yellow)' : 'var(--text)';
                html += `<tr style="background:${bg};">
                    <td style="padding:0.3rem 0.6rem;text-align:right;color:var(--text-dim);">${p.pid}</td>
                    <td style="padding:0.3rem 0.6rem;">${escHtml(p.name)}</td>
                    <td style="padding:0.3rem 0.6rem;text-align:right;color:${cpuC};font-weight:600;">${p.cpu_pct}%</td>
                    <td style="padding:0.3rem 0.6rem;text-align:right;color:var(--text-dim);">${p.mem_pct}%</td>
                    <td style="padding:0.3rem 0.6rem;text-align:right;color:var(--text-dim);">${p.mem_mb} MB</td>
                    <td style="padding:0.3rem 0.6rem;color:var(--text-dim);">${escHtml(p.user||'')}</td>
                </tr>`;
            });
            html += `</tbody></table>`;
        }
    }

    document.getElementById('sysInfoContent').innerHTML = html;
}

// ── Agent display helpers ─────────────────────────────────────────────────
function _agentStat(val, lbl, pct) {
    const c = pct <= 0 ? 'var(--accent)' : pct < 60 ? 'var(--green)' : pct < 85 ? 'var(--yellow)' : 'var(--red)';
    return `<div style="flex:1;min-width:90px;text-align:center;padding:0.6rem 0.4rem;
                background:var(--card-border);border-radius:8px;">
        <div style="font-size:1.15rem;font-weight:700;color:${c};">${escHtml(String(val??'?'))}</div>
        <div style="font-size:0.65rem;color:var(--text-dim);letter-spacing:0.05em;">${lbl}</div>
    </div>`;
}
function _agentSection(title) {
    return `<div style="margin:0.9rem 0 0.35rem;display:flex;align-items:center;gap:0.6rem;">
        <span style="color:var(--accent);font-weight:700;font-size:0.9rem;">${title}</span>
        <span style="flex:1;height:1px;background:var(--card-border);"></span>
    </div>`;
}
function _agentBar(label, pct, detail) {
    const c = pct < 60 ? 'var(--green)' : pct < 85 ? 'var(--yellow)' : 'var(--red)';
    return `<div style="margin-bottom:0.5rem;">
        <div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:0.2rem;">
            <span style="color:var(--text);">${label}</span>
            <span style="color:var(--text-dim);">${detail||''}</span>
        </div>
        <div style="background:var(--card-border);border-radius:4px;height:18px;overflow:hidden;position:relative;">
            <div style="background:${c};width:${Math.min(pct,100)}%;height:100%;"></div>
            <span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
                         font-size:0.7rem;font-weight:700;color:#fff;">${pct.toFixed(1)}%</span>
        </div>
    </div>`;
}

async function toggleMaintenance(ip) {
    const data = await api('/api/maintenance', { method: 'POST', body: JSON.stringify({ ip, action: 'toggle', duration: 30 }) });
    toast(`🔧 Maintenance ${data.status === 'entered' ? 'ON' : 'OFF'} for ${ip}`, 'success');
    fetchStatus();
}

async function wakeOnLan(mac) {
    const data = await api('/api/wol', { method: 'POST', body: JSON.stringify({ mac }) });
    toast(data.ok ? '⚡ WOL packet sent!' : '❌ ' + data.message, data.ok ? 'success' : 'error');
}

async function deleteServer(ip) {
    const idx = state.nodes.findIndex(n => n.ip === ip);
    const node = state.nodes[idx];
    if (!confirm(`Delete server "${node.name}"?`)) return;
    await api('/api/nodes', { method: 'DELETE', body: JSON.stringify({ index: idx }) });
    toast('🗑️ Server deleted', 'success');
    fetchStatus();
}

// ─── Add/Edit Server ─────────────────────────────────────────────────────
function showAddServer(preGroup) {
    const html = serverFormHtml({ group: preGroup || '' });
    openModal('➕ Add Server', html, [
        { text: '💾 Save', class: 'btn-success', onclick: () => saveServer() },
    ]);
}

function showEditServer(ip) {
    const idx  = state.nodes.findIndex(n => n.ip === ip);
    const node = state.nodes[idx];
    const html = serverFormHtml(node);
    openModal('✏️ Edit Server — ' + node.name, html, [
        { text: '💾 Save',      class: 'btn-success', onclick: () => saveServer(idx) },
        { text: '📋 Duplicate', class: 'btn-outline',  onclick: () => duplicateServer(ip) },
    ]);
}

function duplicateServer(ip) {
    const node = state.nodes.find(n => n.ip === ip);
    if (!node) return;
    // Clone it, clear IP and append "(Copy)" to name
    const copy = JSON.parse(JSON.stringify(node));
    copy.name = (copy.name || '') + ' (Copy)';
    copy.ip   = '';
    copy.mac  = '';
    closeModal();
    const html = serverFormHtml(copy);
    openModal('📋 Duplicate Server', html, [
        { text: '💾 Save as New', class: 'btn-success', onclick: () => saveServer() },
    ]);
}

function serverFormHtml(n) {
    const cred = (n.shares || [])[0] || {};
    return `
        <div class="form-row"><label>Group</label><input id="sf_group" value="${escAttr(n.group||'')}" placeholder="e.g. NAS &amp; Storage, Media Services, Virtualization"></div>
        <div class="form-row"><label>Description</label><input id="sf_desc" value="${escAttr(n.description||'')}" placeholder="e.g. Primary NAS · ZimaOS Management"></div>
        <div class="form-row"><label>Server Name</label><input id="sf_name" value="${escAttr(n.name||'')}"></div>
        <div class="form-row"><label>IP Address / Hostname</label><input id="sf_ip" value="${escAttr(n.ip||'')}"></div>
        <div class="form-row"><label>Connection Type</label>
            <select id="sf_conn_type">
                ${Object.keys(CONNECTION_TYPES).map(t => `<option value="${t}" ${(n.connections||[{}])[0]?.type===t?'selected':''}>${t}</option>`).join('')}
            </select>
        </div>
        <div class="form-row"><label>Primary Port</label><input id="sf_port" type="number" value="${(n.connections||[{}])[0]?.port||''}"></div>
        <div class="form-row"><label>Management URL</label><input id="sf_manage" value="${escAttr(n.manage_url||'')}"></div>
        <div class="form-row"><label>Management Label</label><input id="sf_manage_label" value="${escAttr(n.manage_label||'Manage')}"></div>
        <div class="form-row"><label>Tags (comma separated)</label><input id="sf_tags" value="${escAttr((n.tags||[]).join(', '))}"></div>

        <div style="background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.4);border-radius:8px;padding:0.75rem 1rem;margin-bottom:0.75rem;">
            <label style="display:flex;align-items:center;gap:0.6rem;cursor:pointer;margin:0;">
                <input type="checkbox" id="sf_sysmon" ${n.show_sysmon ? 'checked' : ''}
                       style="width:18px;height:18px;flex-shrink:0;accent-color:#3b82f6;cursor:pointer;">
                <span style="color:#e2e8f0;font-size:0.9rem;font-weight:600;">📊 Enable System Info button on card</span>
            </label>
            <div style="font-size:0.72rem;color:#94a3b8;margin-top:0.35rem;padding-left:1.6rem;line-height:1.5;">
                Adds a <b style="color:#e2e8f0;">📊 Info</b> button to the card footer — shows live CPU, RAM,
                disk volumes &amp; top processes. Works with Synology, ZimaOS, Plex, Sonarr, Radarr, Lidarr, SABnzbd &amp; Immich.
            </div>
        </div>

        <div class="form-row"><label>MAC Address (for WOL)</label><input id="sf_mac" value="${escAttr(n.mac||'')}"></div>
        <div class="form-row"><label>RustDesk ID</label>
            <input id="sf_rustdesk" value="${escAttr(n.rustdesk_id||'')}" placeholder="Peer ID (e.g. 123456789) or leave blank to use IP">
            <div style="font-size:0.68rem;color:var(--text-dim);margin-top:0.2rem;">Used by the 🖥 RustDesk button. If blank, the server IP is used.</div>
        </div>
        <div class="form-row"><label>API Key / Token</label><input id="sf_api_key" value="${escAttr(n.api_key||'')}"></div>
        <div class="form-row"><label>Brand Icon</label>
            <input id="sf_icon" value="${escAttr(n.icon||'')}" placeholder="e.g. plex, sonarr, proxmox, synology-dsm">
            <div style="font-size:0.68rem;color:var(--text-dim);margin-top:0.2rem;">
                Slug from <a href="https://github.com/walkxcode/dashboard-icons" target="_blank" style="color:var(--accent);">dashboard-icons</a>
                — leave blank for letter avatar
            </div>
        </div>
        <div class="form-row"><label>Card Accent Color</label>
            <div style="display:flex;align-items:center;gap:0.6rem;">
                <input type="color" id="sf_color" value="${n.card_color || '#3b82f6'}"
                       style="width:44px;height:32px;padding:2px;border:1px solid var(--card-border);border-radius:6px;background:var(--card-bg);cursor:pointer;">
                <span style="font-size:0.72rem;color:var(--text-dim);">Custom border &amp; glow colour for this card. Leave as-is for the default status colour.</span>
                <button type="button" onclick="document.getElementById('sf_color').value='#3b82f6'"
                        style="font-size:0.7rem;padding:0.2rem 0.5rem;background:var(--card-border);border:none;border-radius:4px;color:var(--text-dim);cursor:pointer;">Reset</button>
            </div>
        </div>
        <div class="form-row"><label>Notes</label>
            <textarea id="sf_notes" rows="3"
                      style="width:100%;padding:0.5rem 0.75rem;background:#1e293b;border:1px solid #334155;border-radius:6px;color:var(--text);font-size:0.85rem;resize:vertical;"
                      placeholder="Any notes about this server — location, purpose, contacts, quirks…">${escHtml(n.notes||'')}</textarea>
        </div>
        <hr style="border-color:var(--card-border);margin:0.5rem 0;">
        <div style="font-size:0.75rem;color:var(--text-dim);margin-bottom:0.4rem;">Login credentials (Synology DSM, ZimaOS, etc.)</div>
        <div class="form-row"><label>Username</label><input id="sf_login_user" value="${escAttr(cred.user||'')}"></div>
        <div class="form-row"><label>Password</label><input id="sf_login_pass" type="password" value="${escAttr(cred.pass||'')}"></div>
    `;
}

const CONNECTION_TYPES = {SMB:{port:445},FTP:{port:21},FTPS:{port:990},RDP:{port:3389},SSH:{port:22},Telnet:{port:23},HTTP:{port:80},HTTPS:{port:443},Plex:{port:32400},Custom:{port:0}};

async function saveServer(idx) {
    const loginUser = document.getElementById('sf_login_user').value.trim();
    const loginPass = document.getElementById('sf_login_pass').value;
    const existingShares = (idx !== undefined ? state.nodes[idx].shares : []) || [];
    let shares;
    if (loginUser) {
        // Replace first share entry with the form credentials; keep any others
        const rest = existingShares.slice(1);
        shares = [{ user: loginUser, pass: loginPass }, ...rest];
    } else {
        shares = existingShares;
    }
    const node = {
        group: document.getElementById('sf_group').value.trim(),
        description: document.getElementById('sf_desc').value.trim(),
        name: document.getElementById('sf_name').value,
        ip: document.getElementById('sf_ip').value,
        connections: [{ type: document.getElementById('sf_conn_type').value, port: parseInt(document.getElementById('sf_port').value) || 80 }],
        manage_url: document.getElementById('sf_manage').value,
        manage_label: document.getElementById('sf_manage_label').value,
        tags: document.getElementById('sf_tags').value.split(',').map(t => t.trim()).filter(Boolean),
        mac: document.getElementById('sf_mac').value,
        api_key: document.getElementById('sf_api_key').value.trim(),
        icon:        document.getElementById('sf_icon').value.trim(),
        show_sysmon: document.getElementById('sf_sysmon').checked,
        card_color:  document.getElementById('sf_color').value,
        notes:       document.getElementById('sf_notes').value.trim(),
        rustdesk_id: document.getElementById('sf_rustdesk').value.trim(),
        favorite:    idx !== undefined ? (state.nodes[idx].favorite || false) : false,
        shares,
        hosts: (idx !== undefined ? state.nodes[idx].hosts : []) || [],
    };
    try {
        if (idx !== undefined) {
            await api('/api/nodes', { method: 'PUT', body: JSON.stringify({ index: idx, node }) });
        } else {
            await api('/api/nodes', { method: 'POST', body: JSON.stringify(node) });
        }
        closeModal();
        toast('💾 Server saved!', 'success');
        fetchStatus();
    } catch (err) {
        toast('❌ Save failed: ' + err.message, 'error');
    }
}

// ─── Notifications ───────────────────────────────────────────────────────

// US carrier → SMS email gateway mapping
const SMS_CARRIER_LIST = [
    { name: 'AT&T',              gateway: 'txt.att.net' },
    { name: 'T-Mobile',          gateway: 'tmomail.net' },
    { name: 'Verizon',           gateway: 'vtext.com' },
    { name: 'Sprint',            gateway: 'messaging.sprintpcs.com' },
    { name: 'Xfinity / Comcast', gateway: 'vtext.com' },
    { name: 'US Cellular',       gateway: 'email.uscc.net' },
    { name: 'Boost Mobile',      gateway: 'sms.myboostmobile.com' },
    { name: 'Cricket',           gateway: 'sms.cricketwireless.net' },
    { name: 'Metro PCS',         gateway: 'mymetropcs.com' },
    { name: 'Google Fi',         gateway: 'msg.fi.google.com' },
    { name: 'Mint Mobile',       gateway: 'tmomail.net' },
    { name: 'Visible',           gateway: 'vtext.com' },
    { name: 'Consumer Cellular', gateway: 'mailmymobile.net' },
    { name: 'Straight Talk',     gateway: 'vtext.com' },
];

function _carrierOptions(selected) {
    return SMS_CARRIER_LIST.map(c =>
        `<option value="${escAttr(c.name)}"${c.name === selected ? ' selected' : ''}>${escHtml(c.name)}</option>`
    ).join('');
}

// Add a new SMS recipient row to the given container element
function addSmsRow(container, r) {
    r = r || {};
    const row = document.createElement('div');
    row.className = 'recip-row';
    row.innerHTML =
        `<input type="text"  class="rn-label"   placeholder="Name"         value="${escAttr(r.label||r.name||'')}">` +
        `<input type="tel"   class="rn-phone"   placeholder="4155551234"   value="${escAttr(r.phone||'')}">` +
        `<select class="rn-carrier"><option value="">-- Carrier --</option>${_carrierOptions(r.carrier||'')}</select>` +
        `<button class="recip-del" title="Remove" onclick="this.closest('.recip-row').remove()">✕</button>`;
    container.appendChild(row);
}

// Add a new email recipient row
function addEmailRow(container, email) {
    const row = document.createElement('div');
    row.className = 'recip-row-email';
    row.innerHTML =
        `<input type="email" placeholder="you@example.com" value="${escAttr(email||'')}">` +
        `<button class="recip-del" title="Remove" onclick="this.closest('.recip-row-email').remove()">✕</button>`;
    container.appendChild(row);
}

// Collect SMS recipients from the DOM rows
function _getSmsRecipients() {
    return [...document.querySelectorAll('#sms_recip_list .recip-row')].map(row => ({
        label:   row.querySelector('.rn-label').value.trim(),
        phone:   row.querySelector('.rn-phone').value.trim().replace(/\D/g, ''),
        carrier: row.querySelector('.rn-carrier').value,
    })).filter(r => r.phone && r.carrier);
}

// Collect email recipients from the DOM rows
function _getEmailRecipients() {
    return [...document.querySelectorAll('#email_recip_list .recip-row-email')]
        .map(row => row.querySelector('input').value.trim())
        .filter(Boolean);
}

async function showNotifications() {
    let cfg = {};
    try { cfg = await api('/api/sms-config'); } catch {}

    const html = `
<!-- ── Gmail / SMTP setup ── -->
<div class="notif-section">
  <div class="notif-section-title">📧 Gmail / SMTP Setup</div>
  <div class="notif-info-box">
    <div class="notif-info-title">📋 How to create a Gmail App Password</div>
    <ol class="notif-info-steps">
      <li>Sign in to your Google Account at
          <a href="https://myaccount.google.com" target="_blank">myaccount.google.com</a></li>
      <li>Click <strong>Security</strong> in the left sidebar</li>
      <li>Under "How you sign in to Google," make sure
          <strong>2-Step Verification is ON</strong>
          — App Passwords will not appear until it is enabled</li>
      <li>In the Security page search bar type <strong>App passwords</strong> or go directly to
          <a href="https://myaccount.google.com/apppasswords" target="_blank">myaccount.google.com/apppasswords</a></li>
      <li>In the name box type <code>NOC Dashboard</code>, then click <strong>Create</strong></li>
      <li>Google shows a <strong>16-character password</strong> (like <code>abcd efgh ijkl mnop</code>) —
          copy it and paste it (with or without spaces) in the App Password field below</li>
      <li>Use your full Gmail address in the Email field (e.g. <code>yourname@gmail.com</code>).
          Leave SMTP Server and Port at their defaults.</li>
    </ol>
    <div class="notif-info-warn">⚠️ Use the App Password — NOT your regular Gmail password.
    If "App passwords" doesn't appear, 2-Step Verification is not yet enabled.</div>
  </div>
  <div class="notif-grid-2">
    <div class="form-row"><label>SMTP Server</label>
      <input id="sms_smtp" value="${escAttr(cfg.smtp_server||'smtp.gmail.com')}" placeholder="smtp.gmail.com">
    </div>
    <div class="form-row"><label>Port</label>
      <input id="sms_port" type="number" value="${cfg.smtp_port||587}">
    </div>
  </div>
  <div class="notif-grid-eq">
    <div class="form-row"><label>Gmail Address</label>
      <input id="sms_user" type="email" value="${escAttr(cfg.smtp_user||'')}" placeholder="yourname@gmail.com">
    </div>
    <div class="form-row"><label>App Password</label>
      <div class="notif-pw-wrap">
        <input id="sms_pass" type="password" value="${escAttr(cfg.smtp_pass||'')}" placeholder="16-char App Password" autocomplete="new-password">
        <button class="notif-pw-eye" onclick="
            var i=document.getElementById('sms_pass');
            i.type=i.type==='password'?'text':'password';
            this.textContent=i.type==='password'?'👁':'🙈';" title="Show/hide">👁</button>
      </div>
    </div>
  </div>
</div>

<!-- ── SMS text alerts ── -->
<div class="notif-section">
  <div class="notif-section-title">📱 SMS Text Alerts</div>
  <label class="notif-toggle-row">
    <input type="checkbox" id="sms_enabled" ${cfg.enabled?'checked':''}>
    <span>Enable SMS text alerts (sends via email-to-SMS gateway)</span>
  </label>
  <div class="recip-col-hdr">
    <span>Name</span><span>Phone Number</span><span>Carrier</span><span></span>
  </div>
  <div class="recip-list" id="sms_recip_list"></div>
  <button class="add-recip-btn" onclick="addSmsRow(document.getElementById('sms_recip_list'))">+ Add Recipient</button>
</div>

<!-- ── Email alerts ── -->
<div class="notif-section">
  <div class="notif-section-title">✉️ Email Alerts</div>
  <label class="notif-toggle-row">
    <input type="checkbox" id="email_enabled" ${cfg.email_enabled?'checked':''}>
    <span>Enable email alerts (uses the same Gmail / SMTP settings above)</span>
  </label>
  <div class="recip-list" id="email_recip_list"></div>
  <button class="add-recip-btn" onclick="addEmailRow(document.getElementById('email_recip_list'))">+ Add Email Address</button>
</div>

<!-- ── Webhooks ── -->
<div class="notif-section">
  <div class="notif-section-title">🔗 Webhook Alerts</div>
  <div class="form-row"><label>Discord Webhook URL</label>
    <input id="discord_webhook" placeholder="https://discord.com/api/webhooks/…" value="${escAttr(cfg.discord_webhook||'')}">
  </div>
  <div class="form-row"><label>Slack Webhook URL</label>
    <input id="slack_webhook" placeholder="https://hooks.slack.com/services/…" value="${escAttr(cfg.slack_webhook||'')}">
  </div>
</div>

<!-- ── Alert triggers ── -->
<div class="notif-section">
  <div class="notif-section-title">🔔 Alert Triggers</div>
  <label class="notif-toggle-row">
    <input type="checkbox" id="sms_offline" ${cfg.alert_offline!==false?'checked':''}>
    <span>Alert when a server goes <strong style="color:var(--red)">OFFLINE</strong></span>
  </label>
  <label class="notif-toggle-row">
    <input type="checkbox" id="sms_online" ${cfg.alert_online!==false?'checked':''}>
    <span>Alert when a server comes back <strong style="color:var(--green)">ONLINE</strong></span>
  </label>
  <div class="form-row" style="max-width:200px;margin-top:0.4rem;">
    <label>Cooldown between repeat alerts (minutes)</label>
    <input id="sms_cooldown" type="number" min="1" max="1440" value="${cfg.cooldown_minutes||5}">
  </div>
</div>`;

    openModal('🔔 Notifications', html, [
        { text: '💾 Save',        class: 'btn-success', onclick: saveNotifications },
        { text: '📱 Test SMS',    class: 'btn-primary',  onclick: sendTestSms },
        { text: '✉️ Test Email',  class: 'btn-primary',  onclick: sendTestEmail },
    ]);

    // Populate recipient rows after modal is in the DOM
    const smsBox   = document.getElementById('sms_recip_list');
    const emailBox = document.getElementById('email_recip_list');
    (cfg.recipients || []).forEach(r => addSmsRow(smsBox, r));
    (cfg.email_recipients || []).forEach(e => addEmailRow(emailBox, e));
    // Ensure at least one empty row each
    if (!smsBox.children.length)   addSmsRow(smsBox);
    if (!emailBox.children.length) addEmailRow(emailBox);
}

async function saveNotifications() {
    const cfg = {
        enabled:          document.getElementById('sms_enabled').checked,
        smtp_server:      document.getElementById('sms_smtp').value.trim(),
        smtp_port:        parseInt(document.getElementById('sms_port').value) || 587,
        smtp_user:        document.getElementById('sms_user').value.trim(),
        smtp_pass:        document.getElementById('sms_pass').value,
        alert_offline:    document.getElementById('sms_offline').checked,
        alert_online:     document.getElementById('sms_online').checked,
        cooldown_minutes: parseInt(document.getElementById('sms_cooldown').value) || 5,
        recipients:       _getSmsRecipients(),
        email_enabled:    document.getElementById('email_enabled').checked,
        email_recipients: _getEmailRecipients(),
        discord_webhook:  document.getElementById('discord_webhook').value.trim(),
        slack_webhook:    document.getElementById('slack_webhook').value.trim(),
    };
    try {
        await api('/api/sms-config', { method: 'POST', body: JSON.stringify(cfg) });
        closeModal();
        toast('💾 Notification settings saved!', 'success');
    } catch (err) {
        toast('❌ Save failed: ' + err.message, 'error');
    }
}

async function sendTestSms() {
    try {
        await api('/api/sms-test', { method: 'POST' });
        toast('📱 Test SMS sent! Check your phone in ~30 seconds.', 'success');
    } catch (err) {
        toast('❌ SMS test failed: ' + err.message, 'error');
    }
}

async function sendTestEmail() {
    try {
        await api('/api/email-test', { method: 'POST' });
        toast('✉️ Test email sent! Check your inbox (and spam folder).', 'success');
    } catch (err) {
        toast('❌ Email test failed: ' + err.message, 'error');
    }
}

// Keep old name as alias so any cached references still work
const showSmsSettings = showNotifications;

// ─── Export/Import ───────────────────────────────────────────────────────
function showExportImport() {
    const html = `
        <div class="form-row">
            <button class="btn btn-primary" onclick="exportConfig()">📥 Export Config</button>
            <span style="font-size:0.8rem;color:var(--text-dim);margin-left:0.5rem;">Download JSON config file</span>
        </div>
        <hr style="border-color:var(--card-border);margin:1rem 0;">
        <div class="form-row"><label>Import Config (paste JSON)</label>
            <textarea id="importJson" rows="8" style="font-family:monospace;font-size:0.75rem;" placeholder='{"version":2,"nodes":[...]}'></textarea>
        </div>`;
    openModal('💾 Config Management', html, [
        { text: '📤 Import', class: 'btn-warning', onclick: importConfig },
    ]);
}

async function exportConfig() {
    const data = await api('/api/config/export');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `noc_config_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    toast('📥 Config exported!', 'success');
}

async function importConfig() {
    try {
        const data = JSON.parse(document.getElementById('importJson').value);
        await api('/api/config/import', { method: 'POST', body: JSON.stringify(data) });
        closeModal();
        toast('📤 Config imported!', 'success');
        fetchStatus();
    } catch (e) {
        toast('❌ Invalid JSON: ' + e.message, 'error');
    }
}

// ─── Modal System ────────────────────────────────────────────────────────
function openModal(title, bodyHtml, buttons = []) {
    const container = document.getElementById('modalContainer');
    container.innerHTML = `<div class="modal-overlay" id="modalOverlay">
        <div class="modal">
            <div class="modal-header"><h2>${title}</h2><button class="modal-close" id="modalCloseX">&times;</button></div>
            <div class="modal-body">${bodyHtml}</div>
            <div class="modal-footer" id="modalFooter"></div>
        </div>
    </div>`;
    // Wire up overlay click-to-close and X button
    document.getElementById('modalOverlay').addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });
    document.getElementById('modalCloseX').addEventListener('click', closeModal);
    // Wire up action buttons using DOM so arrow-function onclicks (with closures) work correctly
    const footer = document.getElementById('modalFooter');
    buttons.forEach(b => {
        const btn = document.createElement('button');
        btn.className = `btn ${b.class || 'btn-primary'}`;
        btn.textContent = b.text;
        btn.addEventListener('click', b.onclick || closeModal);
        footer.appendChild(btn);
    });
    const closeBtn = document.createElement('button');
    closeBtn.className = 'btn btn-outline';
    closeBtn.textContent = 'Close';
    closeBtn.addEventListener('click', closeModal);
    footer.appendChild(closeBtn);
}

function closeModal() {
    document.getElementById('modalContainer').innerHTML = '';
}

// ─── Helpers ─────────────────────────────────────────────────────────────
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function escAttr(s) { return String(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }

// ─── Dark / Light Theme ───────────────────────────────────────────────────
function initTheme() {
    if (localStorage.getItem('noc_theme') === 'light') {
        document.body.classList.add('light');
        const btn = document.getElementById('themeToggle');
        if (btn) btn.textContent = '☀️';
    }
}
function toggleTheme() {
    const isLight = document.body.classList.toggle('light');
    const btn = document.getElementById('themeToggle');
    if (btn) btn.textContent = isLight ? '☀️' : '🌙';
    localStorage.setItem('noc_theme', isLight ? 'light' : 'dark');
}

// ─── Speed Test ───────────────────────────────────────────────────────────
async function runSpeedTest() {
    openModal('🚀 Speed Test', `
        <div style="text-align:center;padding:1.5rem 0;">
            <div style="font-size:2rem;margin-bottom:0.5rem;">⏳</div>
            <div style="font-size:0.9rem;color:var(--text-dim);">Running speed test — this takes about 20–30 seconds…</div>
        </div>
        <div id="speedResult" style="display:none;">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.75rem;text-align:center;margin-top:0.5rem;">
                <div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;padding:1rem;">
                    <div style="font-size:1.6rem;font-weight:700;color:var(--green);" id="spd_dl">—</div>
                    <div style="font-size:0.72rem;color:var(--text-dim);margin-top:0.2rem;">↓ Download (Mbps)</div>
                </div>
                <div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;padding:1rem;">
                    <div style="font-size:1.6rem;font-weight:700;color:var(--accent);" id="spd_ul">—</div>
                    <div style="font-size:0.72rem;color:var(--text-dim);margin-top:0.2rem;">↑ Upload (Mbps)</div>
                </div>
                <div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:10px;padding:1rem;">
                    <div style="font-size:1.6rem;font-weight:700;color:var(--yellow);" id="spd_ping">—</div>
                    <div style="font-size:0.72rem;color:var(--text-dim);margin-top:0.2rem;">⚡ Ping (ms)</div>
                </div>
            </div>
            <div style="text-align:center;margin-top:0.6rem;font-size:0.75rem;color:var(--text-dim);">
                Test server: <span id="spd_server">—</span>
            </div>
        </div>
        <div id="speedError" style="display:none;color:var(--red);font-size:0.82rem;text-align:center;padding:0.5rem;"></div>`, []);
    try {
        const res = await api('/api/speedtest', { method: 'POST' });
        if (res.error) {
            document.getElementById('speedError').textContent = '❌ ' + res.error;
            document.getElementById('speedError').style.display = 'block';
        } else {
            document.getElementById('spd_dl').textContent   = res.download_mbps;
            document.getElementById('spd_ul').textContent   = res.upload_mbps;
            document.getElementById('spd_ping').textContent = res.ping_ms;
            document.getElementById('spd_server').textContent = res.server;
            document.querySelector('#speedResult').style.display = 'block';
            document.querySelector('.modal-body > div:first-child').style.display = 'none';
        }
    } catch(e) {
        document.getElementById('speedError').textContent = '❌ Speed test failed: ' + e;
        document.getElementById('speedError').style.display = 'block';
    }
}

// ─── RDP One-Click ────────────────────────────────────────────────────────
function downloadRdp(ip) {
    window.location.href = `/api/server/${encodeURIComponent(ip)}/rdp`;
}

// ─── Init ────────────────────────────────────────────────────────────────
initTheme();
fetchStatus();
startCountdown();
setInterval(fetchStatus, (typeof SCAN_INTERVAL !== "undefined" ? SCAN_INTERVAL : 30) * 1000);

// Keyboard shortcuts
document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.key === 'r') { e.preventDefault(); forceRefresh(); }
    if (e.ctrlKey && e.key === 'f') { e.preventDefault(); document.getElementById('searchBox').focus(); }
    if (e.key === 'Escape') { closeModal(); closeSetupMenu(); document.getElementById('searchBox').value = ''; filterCards(); }
});

// ─── Setup Dropdown ────────────────────────────────────────────────────────
function toggleSetupMenu(e) {
    e.stopPropagation();
    document.getElementById('setupMenu').classList.toggle('open');
}
function closeSetupMenu() {
    document.getElementById('setupMenu').classList.remove('open');
}
document.addEventListener('click', function(e) {
    const menu = document.getElementById('setupMenu');
    if (menu && !menu.closest('.setup-dropdown').contains(e.target)) {
        menu.classList.remove('open');
    }
});

// ─── Backup & Restore ─────────────────────────────────────────────────────
function formatBackupName(filename) {
    // backup_20260521_143022_pre-edit.zip  →  May 21 2026 02:30:22 PM  (pre-edit)
    const m = filename.match(/^backup_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(.+)\.zip$/);
    if (!m) return filename;
    const [,yr,mo,dy,hh,mm,ss,reason] = m;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const h = parseInt(hh), ampm = h >= 12 ? 'PM' : 'AM', h12 = h % 12 || 12;
    return `${months[parseInt(mo)-1]} ${dy} ${yr}  ${h12}:${mm}:${ss} ${ampm}  <span style="color:var(--text-dim)">(${reason})</span>`;
}
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
    return (bytes/1048576).toFixed(1) + ' MB';
}

async function loadBackupList() {
    const list = document.getElementById('backupList');
    if (!list) return;
    list.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem;padding:0.5rem 0;">Loading…</div>';
    try {
        const backups = await api('/api/backups');
        if (!backups.length) {
            list.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem;padding:0.5rem 0;">No backups yet. Click <b>Create Backup Now</b> to make one.</div>';
            return;
        }
        list.innerHTML = backups.map(b => `
            <div class="backup-row">
                <div>
                    <div class="backup-name">${formatBackupName(b.filename)}</div>
                    <div class="backup-meta">${formatSize(b.size)}</div>
                </div>
                <button class="btn btn-outline" style="font-size:0.72rem;padding:0.25rem 0.6rem;"
                    onclick="restoreBackup('${b.filename}')">↩ Restore</button>
            </div>`).join('');
    } catch(e) {
        list.innerHTML = '<div style="color:var(--danger);font-size:0.8rem;">Failed to load backups.</div>';
    }
}

async function createBackup() {
    try {
        const res = await api('/api/backup', { method: 'POST', body: JSON.stringify({reason:'manual'}) });
        toast('✅ Backup created! (' + (res.filename || '') + ')', 'success');
        loadBackupList();
    } catch(e) {
        toast('❌ Backup failed', 'danger');
    }
}

async function restoreBackup(filename) {
    if (!confirm('Restore from:\n' + filename + '\n\nThis will overwrite your current server config. Continue?')) return;
    try {
        await api('/api/restore', { method: 'POST', body: JSON.stringify({filename}) });
        toast('✅ Restored from backup!', 'success');
        closeModal();
        fetchStatus();
    } catch(e) {
        toast('❌ Restore failed: ' + (e.message||e), 'danger');
    }
}

// ─── App Settings ─────────────────────────────────────────────────────────
async function showAppSettings() {
    const s = await api('/api/settings');
    const html = `
        <div style="font-size:0.75rem;color:var(--accent);background:rgba(59,130,246,0.1);
                    border:1px solid rgba(59,130,246,0.3);border-radius:8px;
                    padding:0.5rem 0.75rem;margin-bottom:0.85rem;">
            ℹ️ <b>Name, Username, Password, Secret Key,</b> and <b>Port</b> take effect after
            restarting noc_web.py.&nbsp; Scan &amp; Ping intervals apply immediately.
        </div>

        <div class="form-row"><label>Dashboard Name</label>
            <input id="s_title" value="${escAttr(s.title||'REGTeches NOC Web Dashboard')}"></div>

        <hr style="border-color:var(--card-border);margin:0.6rem 0;">
        <div style="font-size:0.78rem;font-weight:600;margin-bottom:0.35rem;color:var(--text-dim);">Login Credentials</div>
        <div class="form-row"><label>Username</label>
            <input id="s_auth_user" value="${escAttr(s.auth_user||'admin')}"></div>
        <div class="form-row"><label>Password</label>
            <input id="s_auth_pass" type="password" value="${escAttr(s.auth_pass||'')}">
            <label style="margin-top:0.3rem;font-size:0.72rem;cursor:pointer;display:flex;align-items:center;gap:0.35rem;">
                <input type="checkbox" onchange="
                    var inp=this.closest('.form-row').querySelector('#s_auth_pass');
                    inp.type=this.checked?'text':'password';">
                Show password</label></div>

        <hr style="border-color:var(--card-border);margin:0.6rem 0;">
        <div style="font-size:0.78rem;font-weight:600;margin-bottom:0.35rem;color:var(--text-dim);">Network</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;">
            <div class="form-row"><label>Server Port</label>
                <input id="s_port" type="number" min="1" max="65535" value="${s.port||8082}"></div>
            <div class="form-row"><label>Scan Interval <span style="font-size:0.68rem;color:var(--text-dim)">(sec)</span></label>
                <input id="s_scan_interval" type="number" min="5" max="3600" value="${s.scan_interval||30}"></div>
            <div class="form-row"><label>Ping Timeout <span style="font-size:0.68rem;color:var(--text-dim)">(sec)</span></label>
                <input id="s_ping_timeout" type="number" min="1" max="30" value="${s.ping_timeout||2}"></div>
        </div>

        <hr style="border-color:var(--card-border);margin:0.6rem 0;">
        <div style="font-size:0.78rem;font-weight:600;margin-bottom:0.35rem;color:var(--text-dim);">Flask Secret Key</div>
        <div class="form-row">
            <input id="s_secret_key" value="${escAttr(s.secret_key||'')}">
            <span style="font-size:0.7rem;color:var(--text-dim);margin-top:0.2rem;">
                Used to sign session cookies. Change this to a long random string.</span></div>`;
    openModal('🛠️ App Settings', html, [
        { text: '💾 Save Settings', class: 'btn-success', onclick: saveAppSettings },
    ]);
}

async function saveAppSettings() {
    const data = {
        title:         document.getElementById('s_title').value.trim(),
        auth_user:     document.getElementById('s_auth_user').value.trim(),
        auth_pass:     document.getElementById('s_auth_pass').value,
        secret_key:    document.getElementById('s_secret_key').value.trim(),
        scan_interval: parseInt(document.getElementById('s_scan_interval').value) || 30,
        ping_timeout:  parseInt(document.getElementById('s_ping_timeout').value) || 2,
        port:          parseInt(document.getElementById('s_port').value) || 8082,
    };
    if (!data.title)     { toast('❌ Dashboard name cannot be empty', 'danger'); return; }
    if (!data.auth_user) { toast('❌ Username cannot be empty', 'danger'); return; }
    if (!data.auth_pass) { toast('❌ Password cannot be empty', 'danger'); return; }
    await api('/api/settings', { method: 'POST', body: JSON.stringify(data) });
    closeModal();
    toast('✅ Settings saved! Restart noc_web.py to apply name / login / port changes.', 'success');
}

async function showBackupRestore() {
    const html = `
        <div style="margin-bottom:0.75rem;display:flex;align-items:center;gap:0.75rem;">
            <button class="btn btn-success" style="font-size:0.82rem;" onclick="createBackup()">➕ Create Backup Now</button>
            <span style="font-size:0.75rem;color:var(--text-dim);">Auto-backup runs before every save.</span>
        </div>
        <div style="font-size:0.78rem;color:var(--text-dim);margin-bottom:0.4rem;">
            Each backup is a <b>ZIP of every file</b> in the NOC folder, stored in
            <code style="background:rgba(0,0,0,0.3);padding:1px 5px;border-radius:4px;">backups/</code>.
            The 5 most recent are kept; the oldest is dropped automatically (first-in, first-out).
        </div>
        <hr style="border-color:var(--card-border);margin:0.6rem 0;">
        <div style="font-size:0.82rem;font-weight:600;margin-bottom:0.4rem;">Saved Backups</div>
        <div id="backupList" style="max-height:320px;overflow-y:auto;"></div>`;
    openModal('💾 Backup &amp; Restore', html, []);
    loadBackupList();
}
