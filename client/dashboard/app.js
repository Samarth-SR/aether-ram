/**
 * Cloud RAM Dashboard — App Logic
 * WebSocket real-time updates, Chart.js gauges, benchmark, decision display
 */

// ── Config ────────────────────────────────────────────────────────────────────
const MONITOR_API = 'http://localhost:8001';
const CLOUD_API = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws';

// ── State ─────────────────────────────────────────────────────────────────────
let ws = null;
let sessionId = null;
let cloudRamAllocated = 0;
let statsPoller = null;
let wsHeartbeat = null;
let ramHistory = new Array(30).fill(0);
let cpuHistory = new Array(30).fill(0);

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ── Charts ────────────────────────────────────────────────────────────────────
let ramGauge, cpuGauge, ramLineChart, cpuLineChart;
const CHARTSJS_AVAILABLE = typeof Chart !== 'undefined';

function initCharts() {
    if (!CHARTSJS_AVAILABLE) {
        console.warn('Chart.js not loaded (no internet?). Gauge charts disabled, text-only mode.');
        document.querySelectorAll('.gauge-container canvas, .chart-history canvas').forEach(c => {
            c.style.display = 'none';
        });
        return;
    }
    const gaugeOpts = (color1, color2) => ({
        type: 'doughnut',
        data: {
            datasets: [{
                data: [0, 100],
                backgroundColor: [
                    { type: 'gradient', stops: [[0, color1], [1, color2]] },
                    'rgba(255,255,255,0.04)',
                ],
                borderWidth: 0,
                cutout: '78%',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            rotation: -110,
            circumference: 220,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            animation: { duration: 600, easing: 'easeInOutQuart' },
        },
    });

    // Apply gradient manually after creation
    function makeGradient(ctx, color1, color2) {
        const grad = ctx.createLinearGradient(0, 0, 200, 200);
        grad.addColorStop(0, color1);
        grad.addColorStop(1, color2);
        return grad;
    }

    const ramCtx = $('ramGauge').getContext('2d');
    ramGauge = new Chart(ramCtx, {
        type: 'doughnut',
        data: {
            datasets: [{
                data: [0, 100],
                backgroundColor: [makeGradient(ramCtx, '#00d4ff', '#7c3aed'), 'rgba(255,255,255,0.04)'],
                borderWidth: 0,
                cutout: '78%',
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: true, rotation: -110, circumference: 220,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            animation: { duration: 600, easing: 'easeInOutQuart' }
        },
    });

    const cpuCtx = $('cpuGauge').getContext('2d');
    cpuGauge = new Chart(cpuCtx, {
        type: 'doughnut',
        data: {
            datasets: [{
                data: [0, 100],
                backgroundColor: [makeGradient(cpuCtx, '#a855f7', '#ec4899'), 'rgba(255,255,255,0.04)'],
                borderWidth: 0,
                cutout: '78%',
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: true, rotation: -110, circumference: 220,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            animation: { duration: 600, easing: 'easeInOutQuart' }
        },
    });

    // Line charts
    const lineOpts = (color) => ({
        type: 'line',
        data: {
            labels: Array(30).fill(''),
            datasets: [{
                data: Array(30).fill(0), borderColor: color, borderWidth: 1.5,
                fill: true, backgroundColor: color.replace(')', ',0.08)').replace('rgb', 'rgba'),
                tension: 0.4, pointRadius: 0
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
                x: { display: false },
                y: { display: false, min: 0, max: 100 },
            },
        },
    });

    ramLineChart = new Chart($('ramLine').getContext('2d'), lineOpts('rgb(0,212,255)'));
    cpuLineChart = new Chart($('cpuLine').getContext('2d'), lineOpts('rgb(168,85,247)'));
}

function updateGauges(ramPct, cpuPct, stats) {
    // RAM gauge
    ramGauge.data.datasets[0].data = [ramPct, 100 - ramPct];
    ramGauge.update('none');
    $('ramPct').textContent = Math.round(ramPct) + '%';
    $('ramDetail').textContent = `${stats.ram.used_gb} / ${stats.ram.total_gb} GB`;

    // CPU gauge
    cpuGauge.data.datasets[0].data = [cpuPct, 100 - cpuPct];
    cpuGauge.update('none');
    $('cpuPct').textContent = Math.round(cpuPct) + '%';
    $('cpuDetail').textContent = `${stats.cpu.cores} cores`;

    // History
    ramHistory.push(ramPct); ramHistory.shift();
    cpuHistory.push(cpuPct); cpuHistory.shift();
    ramLineChart.data.datasets[0].data = [...ramHistory];
    cpuLineChart.data.datasets[0].data = [...cpuHistory];
    ramLineChart.update('none');
    cpuLineChart.update('none');

    // Color hint on high usage
    const ramColor = ramPct > 85 ? '#ff4757' : ramPct > 70 ? '#ff6b35' : '#00d4ff';
    $('ramPct').style.background = `linear-gradient(135deg, ${ramColor}, #a855f7)`;
    $('ramPct').style.webkitBackgroundClip = 'text';
    $('ramPct').style.webkitTextFillColor = 'transparent';
}

// ── Stats poller ──────────────────────────────────────────────────────────────
async function pollStats() {
    try {
        const res = await fetch(`${MONITOR_API}/stats`, { signal: AbortSignal.timeout(2000) });
        const data = await res.json();

        updateGauges(data.ram.percent, data.cpu.percent, data);

        // Mini stats
        $('diskPct').textContent = data.disk.percent + '%';
        $('availRam').textContent = data.ram.available_gb + ' GB';
        $('cpuCores').textContent = data.cpu.cores;

        // Top processes
        const tbody = $('procTable');
        tbody.innerHTML = data.top_processes.map(p =>
            `<tr><td>${p.pid}</td><td>${p.name}</td><td>${p.mem_pct}%</td></tr>`
        ).join('');

        setMonitorStatus(true);
    } catch (e) {
        setMonitorStatus(false);
    }
}

function setMonitorStatus(online) {
    const dot = $('monitorDot');
    const text = $('monitorText');
    dot.className = 'status-dot ' + (online ? 'online' : 'offline');
    text.textContent = online ? 'Monitor Online' : 'Monitor Offline';
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connectWS() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        log('Connected to cloud backend', 'info');
        setCloudStatus(true);
        wsHeartbeat = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send('ping');
        }, 15000);
    };

    ws.onmessage = (evt) => {
        try { handleWsMessage(JSON.parse(evt.data)); }
        catch (e) { /* ignore non-JSON */ }
    };

    ws.onclose = () => {
        setCloudStatus(false);
        log('Lost cloud connection — reconnecting in 3s...', 'warn');
        clearInterval(wsHeartbeat);
        setTimeout(connectWS, 3000);
    };

    ws.onerror = () => {
        setCloudStatus(false);
    };
}

function setCloudStatus(online) {
    const dot = $('cloudDot');
    const text = $('cloudText');
    dot.className = 'status-dot ' + (online ? 'online' : 'offline');
    text.textContent = online ? 'Cloud Online' : 'Cloud Offline';
}

function handleWsMessage(msg) {
    switch (msg.type) {
        case 'allocation':
            cloudRamAllocated = msg.ram_mb;
            $('cloudRamNumber').textContent = formatRam(msg.ram_mb);
            $('allocBadge').style.display = 'inline-flex';
            $('sessionInfo').textContent = msg.session_id;
            $('workerInfo').textContent = msg.worker_id;
            setWorkerActive(msg.worker_id);
            log(`☁  Cloud RAM allocated: ${formatRam(msg.ram_mb)} MB — Session ${msg.session_id}`, 'success');
            break;

        case 'task_update':
            updateTaskStatus(msg.task_id, msg.status, msg.task_type, msg.message);
            if (msg.status === 'running') {
                log(`⚙  Task running: ${msg.task_type} [${msg.task_id}]${msg.attempt > 1 ? ` (attempt ${msg.attempt})` : ''}`, 'info');
            } else if (msg.status === 'retrying') {
                log(`↺  Retrying: ${msg.message || msg.task_id}`, 'warn');
            } else if (msg.status === 'failed' || msg.status === 'dead_letter') {
                log(`✗  Task ${msg.status}: ${msg.task_id}`, 'error');
            } else if (msg.status === 'queued') {
                log(`✦  Task queued: ${msg.task_type} [${msg.task_id}]`, 'info');
            }
            break;

        case 'task_result':
            handleTaskResult(msg);
            break;

        case 'release':
            log(`⬆  ${msg.message}`, 'info');
            cloudRamAllocated = 0;
            $('cloudRamNumber').textContent = '0';
            $('allocBadge').style.display = 'none';
            break;

        case 'system_event':
            const icons = { worker_crash: '⚠', worker_recovered: '✓', network_drop: '⚠', network_recovered: '✓' };
            const types = { worker_crash: 'warn', worker_recovered: 'success', network_drop: 'warn', network_recovered: 'success' };
            log(`${icons[msg.event] || '•'} ${msg.message}`, types[msg.event] || 'system');
            if (msg.event === 'worker_crash') setWorkerDead('w-02');
            if (msg.event === 'worker_recovered') setWorkerActive('w-03');
            break;
    }
}

function updateTaskStatus(taskId, status, taskType, message) {
    const el = $('taskStatus');
    if (!el) return;
    const icons = { queued: '⏳', running: '⚙', completed: '✓', retrying: '↺', failed: '✗', dead_letter: '☠', timeout: '⏱' };
    const classes = { completed: 'chip-green', running: 'chip-cyan', failed: 'chip-orange', retrying: 'chip-orange', dead_letter: 'chip-orange', queued: 'chip-purple' };
    el.innerHTML = `<span class="chip ${classes[status] || 'chip-cyan'}">${icons[status] || '•'} ${status}${taskType ? ' — ' + taskType.replace('_', ' ') : ''}</span>`;
}

function handleTaskResult(msg) {
    const result = msg.result || {};
    log(`✓  Task completed: ${msg.task_type} in ${result.duration_ms}ms (cloud RAM: ${result.cloud_ram_mb} MB)`, 'success');

    $('taskResultBox').style.display = 'block';
    const display = Object.fromEntries(
        Object.entries(result).filter(([k]) => !['image_b64', 'task_id'].includes(k))
    );
    $('taskResultPre').textContent = JSON.stringify(display, null, 2);

    // Show image if image_filter task
    if (result.image_b64) {
        const img = $('resultImage');
        img.src = 'data:image/png;base64,' + result.image_b64;
        img.style.display = 'block';
    } else {
        $('resultImage').style.display = 'none';
    }

    updateTaskStatus(msg.task_id, 'completed', msg.task_type);

    // Update cloud stats
    $('tasksRun').textContent = (parseInt($('tasksRun').textContent) || 0) + 1;
    if (result.duration_ms) {
        $('lastTaskTime').textContent = result.duration_ms + ' ms';
    }
}

// ── Download More RAM ─────────────────────────────────────────────────────────
async function downloadMoreRAM() {
    const ramMb = parseInt($('ramSlider').value) * 1024;
    const btn = $('downloadBtn');

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Allocating...';

    showProgress(0, 'Connecting to cloud...');

    // Run decision engine first
    try {
        const decRes = await fetch(`${MONITOR_API}/decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_type: 'matrix_multiply', params: { n: 1000 } }),
        });
        const dec = await decRes.json();
        showDecisionBanner(dec);
    } catch (e) { /* monitor offline, skip */ }

    // Animate progress
    const steps = [
        [10, 'Negotiating with cloud provider...'],
        [30, 'Reserving warm worker pool slot...'],
        [55, 'Allocating memory blocks...'],
        [75, 'Establishing secure channel...'],
        [90, 'Mapping virtual address space...'],
    ];
    for (const [pct, msg] of steps) {
        await sleep(350);
        showProgress(pct, msg);
    }

    try {
        const res = await fetch(`${CLOUD_API}/allocate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: 'dashboard-user',
                requested_ram_mb: ramMb,
                keep_warm_minutes: 10,
            }),
        });

        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        sessionId = data.session_id;

        await sleep(300);
        showProgress(100, '✓ Done!');

        await sleep(500);
        hideProgress();

        // Glow the cloud card
        $('cloudCard').classList.add('glow-active');
        setTimeout(() => $('cloudCard').classList.remove('glow-active'), 4000);

    } catch (e) {
        log('✗ Cloud backend not reachable: ' + e.message, 'error');
        showProgress(0, '');
        hideProgress();
    }

    btn.disabled = false;
    btn.innerHTML = '⬇ Download More RAM';
}

// ── Task Offload ──────────────────────────────────────────────────────────────
async function offloadTask() {
    if (!sessionId) {
        log('⚠ No active session — click "Download More RAM" first!', 'warn');
        return;
    }

    const taskType = $('taskType').value;
    const params = buildParams(taskType);

    // Get decision
    try {
        const decRes = await fetch(`${MONITOR_API}/decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_type: taskType, params }),
        });
        showDecisionBanner(await decRes.json());
    } catch (e) { /* skip */ }

    $('offloadBtn').disabled = true;
    $('offloadBtn').innerHTML = '<span class="spinner"></span> Offloading...';
    $('taskResultBox').style.display = 'none';

    try {
        const res = await fetch(`${CLOUD_API}/offload`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, task_type: taskType, params }),
        });
        const data = await res.json();
        log(`↑  Task offloaded: ${taskType} [${data.task_id}]`, 'info');
    } catch (e) {
        log('✗ Offload failed: ' + e.message, 'error');
    }

    $('offloadBtn').disabled = false;
    $('offloadBtn').innerHTML = '☁ Offload to Cloud';
}

function buildParams(taskType) {
    const val = p => parseInt($('paramValue')?.value) || undefined;
    const defaults = {
        matrix_multiply: { n: 1000 },
        image_filter: { width: 512, height: 512, filter_type: $('filterType')?.value || 'blur' },
        csv_aggregate: { rows: 50000 },
        compress: { size_mb: 5 },
    };
    const base = defaults[taskType] || {};
    const customN = $('paramN')?.value;
    if (customN) base.n = parseInt(customN);
    return base;
}

// ── Benchmark ─────────────────────────────────────────────────────────────────
async function runBenchmark() {
    const taskType = $('benchTask').value;
    const btn = $('benchBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Running...';

    log(`⧗  Benchmark started: ${taskType} (local + cloud)`, 'info');

    // Run local
    let local = {};
    try {
        const lRes = await fetch(`${MONITOR_API}/benchmark/local`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_type: taskType, params: {} }),
        });
        local = await lRes.json();
        log(`  Local  — ${local.duration_ms}ms | RAM Δ ${local.ram_delta_mb} MB | CPU ${local.cpu_pct}%`, 'info');
    } catch (e) {
        log('✗ Local benchmark failed: ' + e.message, 'error');
    }

    // Run cloud
    let cloud = {};
    if (!sessionId) {
        // Auto-allocate for benchmark
        try {
            const aRes = await fetch(`${CLOUD_API}/allocate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: 'bench-user', requested_ram_mb: 2048 }),
            });
            const a = await aRes.json();
            sessionId = a.session_id;
        } catch (e) { }
    }

    if (sessionId) {
        const t0 = performance.now();
        try {
            const oRes = await fetch(`${CLOUD_API}/offload`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, task_type: taskType, params: {} }),
            });
            const { task_id } = await oRes.json();

            // Poll result
            const result = await pollTaskResult(task_id);
            const rtt = Math.round(performance.now() - t0);
            cloud = { duration_ms: result?.duration_ms, total_rtt_ms: rtt, cloud_ram_mb: result?.cloud_ram_mb, cpu_pct: result?.cpu_pct };
            log(`  Cloud  — ${cloud.duration_ms}ms task | ${cloud.total_rtt_ms}ms RTT | ${cloud.cloud_ram_mb} MB used`, 'success');
        } catch (e) {
            log('✗ Cloud benchmark failed: ' + e.message, 'error');
        }
    } else {
        log('⚠  No cloud session for benchmark', 'warn');
    }

    renderBenchTable(taskType, local, cloud);
    btn.disabled = false;
    btn.innerHTML = '▶ Run Benchmark';
}

async function pollTaskResult(taskId, timeout = 30000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        await sleep(500);
        try {
            const r = await fetch(`${CLOUD_API}/results/${taskId}`);
            const d = await r.json();
            if (d.status === 'completed') return d.result;
            if (d.status === 'failed' || d.status === 'dead_letter') return null;
        } catch (e) { }
    }
    return null;
}

function renderBenchTable(taskType, local, cloud) {
    const lMs = local.duration_ms || 0;
    const cMs = cloud.duration_ms || 0;
    const rttMs = cloud.total_rtt_ms || cMs;
    const speedup = lMs > 0 && cMs > 0 ? (lMs / cMs).toFixed(1) : '—';
    const winner = cMs > 0 && lMs > cMs ? 'cloud' : 'local';

    const f = (v, unit = '') => v != null ? `${v}${unit}` : '—';

    $('benchTable').innerHTML = `
    <tr>
      <th>Metric</th>
      <th>🖥 Local</th>
      <th>☁ Cloud</th>
    </tr>
    <tr>
      <td class="label-col">Task Type</td>
      <td colspan="2" style="color:var(--text-200)">${taskType.replace(/_/g, ' ')}</td>
    </tr>
    <tr>
      <td class="label-col">Exec Time</td>
      <td class="${winner === 'local' ? 'winner' : 'loser'}">${f(lMs, ' ms')}</td>
      <td class="${winner === 'cloud' ? 'winner' : 'loser'}">${f(cMs, ' ms')}</td>
    </tr>
    <tr>
      <td class="label-col">Round-trip</td>
      <td>—</td>
      <td>${f(rttMs, ' ms')}</td>
    </tr>
    <tr>
      <td class="label-col">Cloud RAM</td>
      <td>—</td>
      <td>${f(cloud.cloud_ram_mb, ' MB')}</td>
    </tr>
    <tr>
      <td class="label-col">CPU Load</td>
      <td>${f(local.cpu_pct, '%')}</td>
      <td>${f(cloud.cpu_pct, '%')}</td>
    </tr>
    <tr>
      <td class="label-col">Speed gain</td>
      <td colspan="2" class="${winner === 'cloud' ? 'winner' : ''}">${speedup !== '—' ? `☁ Cloud ${speedup}× ${parseFloat(speedup) > 1 ? 'faster' : 'slower'}` : 'N/A'}</td>
    </tr>
  `;
}

// ── Decision Banner ───────────────────────────────────────────────────────────
function showDecisionBanner(dec) {
    const el = $('decisionBanner');
    el.className = 'decision-banner visible ' + (dec.should_offload ? 'offload' : 'local');
    const icon = dec.should_offload ? '☁' : '🖥';
    el.innerHTML = `
    <span style="font-size:1.1em;flex-shrink:0">${icon}</span>
    <div>
      <strong>${dec.should_offload ? 'OFFLOAD' : 'RUN LOCAL'}</strong>
      — Rule: <strong>${dec.triggered_rule}</strong> (${Math.round(dec.confidence * 100)}% confidence)<br>
      <span style="opacity:0.8">${dec.reason}</span>
    </div>
  `;
}

// ── Fault Tolerance Demos ─────────────────────────────────────────────────────
async function simulateCrash() {
    log('⚠ Simulating worker crash...', 'warn');
    try { await fetch(`${CLOUD_API}/simulate/crash`, { method: 'POST' }); }
    catch (e) { log('✗ Need cloud backend running', 'error'); }
}

async function simulateNetworkDrop() {
    log('⚠ Simulating network instability...', 'warn');
    try { await fetch(`${CLOUD_API}/simulate/network_drop`, { method: 'POST' }); }
    catch (e) { log('✗ Need cloud backend running', 'error'); }
}

async function releaseSession() {
    if (!sessionId) { log('⚠ No active session to release', 'warn'); return; }
    try {
        await fetch(`${CLOUD_API}/release/${sessionId}`, { method: 'POST' });
        sessionId = null;
        log('⬆ Session released, worker returned to pool', 'info');
    } catch (e) {
        log('✗ Release failed: ' + e.message, 'error');
    }
}

// ── Workers display ───────────────────────────────────────────────────────────
function setWorkerActive(id) {
    const el = document.querySelector(`[data-worker="${id}"]`);
    if (el) { el.classList.remove('busy', 'dead'); el.classList.add('active'); }
}
function setWorkerDead(id) {
    const el = document.querySelector(`[data-worker="${id}"]`);
    if (el) { el.classList.remove('active', 'busy'); el.classList.add('dead'); }
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function showProgress(pct, msg) {
    $('progressWrap').classList.add('visible');
    $('progressFill').style.width = pct + '%';
    $('progressText').textContent = msg;
}
function hideProgress() {
    $('progressWrap').classList.remove('visible');
}

// ── Activity Log ──────────────────────────────────────────────────────────────
function log(msg, type = 'info') {
    const container = $('activityLog');
    const now = new Date().toTimeString().slice(0, 8);
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `<span class="log-time">${now}</span><span class="log-msg ${type}">${msg}</span>`;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;

    // Trim to 200 entries
    while (container.children.length > 200) container.removeChild(container.firstChild);
}

// ── RAM slider ────────────────────────────────────────────────────────────────
function onSliderChange() {
    const val = parseInt($('ramSlider').value);
    $('ramAmountLabel').textContent = val + ' GB';
}

// ── Task type param UI ────────────────────────────────────────────────────────
function onTaskTypeChange() {
    const type = $('taskType').value;
    $('paramN').closest('.form-group').style.display = type === 'matrix_multiply' ? 'flex' : 'none';
    $('filterType').closest('.form-group').style.display = type === 'image_filter' ? 'flex' : 'none';
}

// ── Utils ─────────────────────────────────────────────────────────────────────
const sleep = ms => new Promise(r => setTimeout(r, ms));
const formatRam = mb => mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB';

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
    // Show offline banner after 3s if neither server is reachable
    let serversOnline = false;
    setTimeout(() => {
        if (!serversOnline) {
            const banner = document.getElementById('serverOfflineBanner');
            if (banner) banner.style.display = 'flex';
        }
    }, 3000);

    initCharts();
    connectWS();

    statsPoller = setInterval(pollStats, 1500);
    pollStats();

    // Trigger initial decision on load
    setTimeout(async () => {
        try {
            const r = await fetch(`${MONITOR_API}/decision`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_type: 'matrix_multiply', params: { n: 1000 } }),
            });
            showDecisionBanner(await r.json());
        } catch (e) { }
    }, 2000);

    // Log start
    log('Dashboard initialized', 'success');
    log(`Monitor API: ${MONITOR_API}`, 'info');
    log(`Cloud API:   ${CLOUD_API}`, 'info');
    log('Waiting for cloud connection...', 'info');

    onTaskTypeChange();
});
