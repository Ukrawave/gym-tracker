// nutrition.js - Nutrition (Phase 3): manual intake vs user-set daily targets,
// a logging streak, and a true in-vs-out-vs-net history (calories-out comes from
// already-synced Garmin wellness, surfaced by the API).
// Renders an empty-state setup CTA when GET /api/nutrition -> {configured:false},
// otherwise KPI strip + macro meters + quick-log + history chart + recent table.
// NULL-safe throughout; mirrors plan.js (async IIFE, $ = getElementById,
// Chart.js 4 via the shared CDN, .hidden empty-state toggle, no new plugins).

(async () => {
    const $ = (id) => document.getElementById(id);

    // ---- formatting helpers (NULL-safe; an em dash for "no data") ----
    const DASH = '—';
    const fmtInt = (v) => (v == null ? DASH : Math.round(Number(v)).toLocaleString());
    const fmtSigned = (v) => {
        if (v == null) return DASH;
        const n = Math.round(Number(v));
        return `${n > 0 ? '+' : ''}${n.toLocaleString()}`;
    };
    const fmtPct = (v) => (v == null ? DASH : `${Math.round(Number(v))}%`);

    // Local YYYY-MM-DD (avoids the UTC off-by-one a toISOString() slice gives).
    function todayISO() {
        const d = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    let historyChart = null;

    function chartOpts(extra = {}) {
        return Object.assign({
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: { color: '#C7D2D0', font: { family: "'Share Tech Mono', monospace" } } },
                tooltip: { bodyFont: { family: "'JetBrains Mono', monospace" } },
            },
            scales: {
                x: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
                y: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' }, title: { display: true, text: 'KCAL', color: '#8A9A86', font: { family: "'Share Tech Mono', monospace" } } },
            },
        }, extra);
    }

    // ---- macro meter: set "now / target" text + fill width, flag over-target ----
    function setMeter(barId, nowId, tgtId, now, target, baseClass) {
        const bar = $(barId);
        $(nowId).textContent = (now == null ? 0 : Math.round(Number(now))).toLocaleString();
        $(tgtId).textContent = (target == null ? 0 : Math.round(Number(target))).toLocaleString();
        const t = Number(target);
        const n = Math.max(0, Number(now) || 0);
        const pct = (t > 0) ? (n / t) * 100 : 0;
        const over = t > 0 && n > t;
        // Cap the visible fill at 100% but recolour to danger when over target.
        bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
        bar.className = `macro-fill ${baseClass}` + (over ? ' over' : '');
    }

    function renderKpis(payload) {
        const t = payload.targets || {};
        const today = payload.today || {};
        const calIn = today.calories;
        const calOut = payload.calories_out_today;
        const net = payload.net_today;

        $('kpi-streak').textContent = payload.streak == null ? '0' : String(payload.streak);
        $('kpi-streak-unit').textContent = (payload.streak === 1) ? 'day' : 'days';

        $('kpi-cal-in').textContent = fmtInt(calIn);
        $('kpi-cal-in-sub').textContent = t.target_calories != null
            ? `of ${fmtInt(t.target_calories)}` : 'of target';

        $('kpi-cal-out').textContent = fmtInt(calOut);

        const netEl = $('kpi-net');
        netEl.textContent = fmtSigned(net);
        // Surplus is amber, deficit is green (cutting context is the common case),
        // missing data stays muted - never a guessed zero.
        if (net == null) netEl.style.color = 'var(--muted)';
        else if (Number(net) > 0) netEl.style.color = 'var(--warn)';
        else netEl.style.color = 'var(--hud-green)';

        $('kpi-adherence').textContent = fmtPct(payload.adherence_pct);
        $('kpi-today-date').textContent = today.date || todayISO();
        $('kpi-today-source').textContent = today.source || 'manual';
    }

    function renderMeters(payload) {
        const t = payload.targets || {};
        const today = payload.today || {};
        setMeter('m-cal-bar', 'm-cal-now', 'm-cal-tgt', today.calories, t.target_calories, 'cal');
        setMeter('m-prot-bar', 'm-prot-now', 'm-prot-tgt', today.protein_g, t.target_protein_g, 'prot');
        setMeter('m-carb-bar', 'm-carb-now', 'm-carb-tgt', today.carbs_g, t.target_carbs_g, 'carb');
        setMeter('m-fat-bar', 'm-fat-now', 'm-fat-tgt', today.fat_g, t.target_fat_g, 'fat');
    }

    function renderHistory(payload) {
        const canvas = $('chart-history');
        if (!canvas) return;
        const recent = payload.recent || [];
        const labels = recent.map((r) => r.date);
        const intake = recent.map((r) => (r.calories == null ? null : Number(r.calories)));
        const out = recent.map((r) => (r.calories_out == null ? null : Number(r.calories_out)));
        const net = recent.map((r) => (r.net == null ? null : Number(r.net)));
        const target = recent.map((r) => (r.target_calories == null ? null : Number(r.target_calories)));

        const datasets = [
            {
                label: 'IN', data: intake, borderColor: '#00E5FF',
                backgroundColor: '#00E5FF22', tension: 0.2, pointRadius: 3,
                spanGaps: true, fill: false, order: 1,
            },
            {
                label: 'OUT', data: out, borderColor: '#FF9900',
                backgroundColor: 'transparent', tension: 0.2, pointRadius: 3,
                spanGaps: true, fill: false, order: 2,
            },
            {
                label: 'NET', data: net, borderColor: '#00FF66',
                backgroundColor: '#00FF6622', tension: 0.2, pointRadius: 3,
                spanGaps: true, fill: false, order: 0,
            },
            {
                label: 'TARGET', data: target, borderColor: '#8A9A86',
                backgroundColor: 'transparent', borderDash: [6, 4], tension: 0,
                pointRadius: 0, spanGaps: true, fill: false, order: 3,
            },
        ];

        if (historyChart) historyChart.destroy();
        historyChart = new Chart(canvas, {
            type: 'line',
            data: { labels, datasets },
            options: chartOpts(),
        });
    }

    function renderHistoryTable(payload) {
        const el = $('history-table');
        const rows = (payload.recent || []).slice().reverse(); // newest first
        if (!rows.length) {
            el.innerHTML = `<div class="no-data">[ NO INTAKE LOGGED ]</div>`;
            return;
        }
        el.innerHTML = `
            <table class="pr-table">
                <thead><tr>
                    <th>Date</th>
                    <th style="text-align:right;">In</th>
                    <th style="text-align:right;">Out</th>
                    <th style="text-align:right;">Net</th>
                    <th style="text-align:right;"></th>
                </tr></thead>
                <tbody>
                ${rows.map((r) => {
                    const netCls = r.net == null ? 'text-muted' : (Number(r.net) > 0 ? 'text-warn' : 'text-green');
                    return `
                    <tr>
                        <td>${r.date}</td>
                        <td style="text-align:right;">${fmtInt(r.calories)}</td>
                        <td style="text-align:right;">${fmtInt(r.calories_out)}</td>
                        <td style="text-align:right;" class="${netCls}">${fmtSigned(r.net)}</td>
                        <td style="text-align:right;">
                            <button class="hud-btn icon danger" data-del-date="${r.date}" title="Delete">[ X ]</button>
                        </td>
                    </tr>`;
                }).join('')}
                </tbody>
            </table>`;

        el.querySelectorAll('[data-del-date]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const date = btn.getAttribute('data-del-date');
                const ok = await window.hudConfirm(`Delete the intake log for ${date}?`, { kind: 'danger', confirmText: 'DELETE' });
                if (!ok) return;
                try {
                    await api.deleteNutrition(date);
                    await refresh();
                } catch (e) {
                    window.hudAlert(`Delete failed: ${e.message}`, { kind: 'danger' });
                }
            });
        });
    }

    function prefillTargets(payload) {
        if (payload.configured && payload.targets) {
            const t = payload.targets;
            $('tgt-calories').value = t.target_calories != null ? t.target_calories : '';
            $('tgt-protein').value = t.target_protein_g != null ? t.target_protein_g : '';
            $('tgt-carbs').value = t.target_carbs_g != null ? t.target_carbs_g : '';
            $('tgt-fat').value = t.target_fat_g != null ? t.target_fat_g : '';
            $('targets-meta').textContent = 'Update your goals';
        } else {
            $('targets-meta').textContent = 'Set your goals';
        }
    }

    // ---- top-level render ----
    function render(payload) {
        const configured = !!payload.configured;
        $('empty-state').classList.toggle('hidden', configured);
        $('nutrition-view').classList.toggle('hidden', !configured);

        if (configured) {
            $('nutrition-meta').textContent = '[ INTAKE VS TARGET ]';
            renderKpis(payload);
            renderMeters(payload);
            renderHistory(payload);
            renderHistoryTable(payload);
        } else {
            $('nutrition-meta').textContent = '[ NOT CONFIGURED ]';
        }
        prefillTargets(payload);
    }

    async function refresh() {
        const payload = await api.getNutrition();
        render(payload);
        return payload;
    }

    // ---- actions ----
    async function onSaveTargets() {
        const body = {
            target_calories: parseInt($('tgt-calories').value, 10),
            target_protein_g: parseFloat($('tgt-protein').value),
            target_carbs_g: parseFloat($('tgt-carbs').value),
            target_fat_g: parseFloat($('tgt-fat').value),
        };
        if (![body.target_calories, body.target_protein_g, body.target_carbs_g, body.target_fat_g].every(Number.isFinite)) {
            window.hudAlert('Calories and all three macro targets are required.', { kind: 'warn' });
            return;
        }
        const status = $('targets-status');
        status.textContent = 'Saving…';
        try {
            await api.saveNutritionTargets(body);
            status.textContent = 'Saved.';
            await refresh();
            setTimeout(() => { status.textContent = ''; }, 2000);
        } catch (e) {
            status.textContent = '';
            window.hudAlert(`Save failed: ${e.message}`, { kind: 'danger' });
        }
    }

    async function onLogIntake() {
        const calories = parseInt($('log-calories').value, 10);
        const date = $('log-date').value || todayISO();
        if (!Number.isFinite(calories) || calories < 0) {
            window.hudAlert('Enter calories (0 or more).', { kind: 'warn' });
            return;
        }
        // Macros default to 0 when left blank (mirrors the server-side defaults).
        const numOr0 = (id) => {
            const v = parseFloat($(id).value);
            return Number.isFinite(v) ? v : 0;
        };
        const body = {
            date,
            calories,
            protein_g: numOr0('log-protein'),
            carbs_g: numOr0('log-carbs'),
            fat_g: numOr0('log-fat'),
        };
        const status = $('log-status');
        status.textContent = 'Logging…';
        try {
            await api.logNutrition(body);
            ['log-calories', 'log-protein', 'log-carbs', 'log-fat'].forEach((id) => { $(id).value = ''; });
            status.textContent = 'Logged.';
            await refresh();
            setTimeout(() => { status.textContent = ''; }, 2000);
        } catch (e) {
            status.textContent = '';
            window.hudAlert(`Log failed: ${e.message}`, { kind: 'danger' });
        }
    }

    // ---- wire up ----
    document.addEventListener('DOMContentLoaded', () => {
        const ld = $('log-date');
        if (ld && !ld.value) ld.value = todayISO();
    });
    $('save-targets-btn').addEventListener('click', onSaveTargets);
    $('log-btn').addEventListener('click', onLogIntake);

    try {
        await refresh();
    } catch (e) {
        console.error(e);
        document.querySelector('main').insertAdjacentHTML('afterbegin',
            `<div class="no-data text-danger">[ NUTRITION FETCH FAILED: ${e.message} ]</div>`);
    }
})();
