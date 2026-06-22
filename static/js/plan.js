// plan.js — The Plan (Phase 2): goal-agnostic 24-week glide-path.
// Renders an empty-state setup CTA when GET /api/plan -> {configured:false},
// otherwise the glide-path chart + accountability + milestones + weight log.
// NULL-safe throughout; mirrors running.js (async IIFE, $ = getElementById,
// Chart.js 4 via the shared CDN, no new plugins).

(async () => {
    const $ = (id) => document.getElementById(id);

    // ---- formatting helpers ----
    const fmtKg = (v) => (v == null ? '—' : `${Number(v).toFixed(1)} kg`);
    const fmtRate = (v) => {
        if (v == null) return '—';
        const n = Number(v);
        return `${n > 0 ? '+' : ''}${n.toFixed(2)}`;
    };
    const fmtWeeks = (v) => (v == null ? '—' : Number(v).toFixed(1));
    const VERDICT_LABEL = {
        ahead: 'AHEAD', on_pace: 'ON PACE', behind: 'BEHIND', unknown: '—',
    };
    const VERDICT_COLOR = {
        ahead: 'var(--hud-green)', on_pace: 'var(--info)',
        behind: 'var(--danger)', unknown: 'var(--muted)',
    };
    const DIRECTION_LABEL = { '-1': 'CUT', '1': 'BULK', '0': 'RECOMP' };

    // Local YYYY-MM-DD (avoids the UTC off-by-one a toISOString() slice gives).
    function todayISO() {
        const d = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    let glideChart = null;

    function chartOpts(extra = {}) {
        return Object.assign({
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'nearest', intersect: false },
            plugins: {
                legend: { labels: { color: '#C7D2D0', font: { family: "'Share Tech Mono', monospace" } } },
                tooltip: { bodyFont: { family: "'JetBrains Mono', monospace" } },
            },
            scales: {
                x: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' }, title: { display: true, text: 'WEEK', color: '#8A9A86', font: { family: "'Share Tech Mono', monospace" } } },
                y: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' }, title: { display: true, text: 'KG', color: '#8A9A86', font: { family: "'Share Tech Mono', monospace" } } },
            },
        }, extra);
    }

    // Phase bands as a stacked set of translucent background fills. We keep it
    // simple per the brief — no annotation plugin: each phase is a faint filled
    // area spanning its week range, drawn beneath the data lines.
    function phaseBandDatasets(phases, horizon, yMin, yMax) {
        if (!Array.isArray(phases) || !phases.length) return [];
        const palette = ['rgba(0,229,255,0.06)', 'rgba(0,255,102,0.06)', 'rgba(255,153,0,0.06)', 'rgba(199,125,255,0.06)'];
        return phases.map((p, i) => {
            const s = Math.max(0, Number(p.start_week) || 0);
            const e = Math.min(horizon, Number(p.end_week) || horizon);
            // Two points at the band edges, filled to the x-axis baseline.
            return {
                label: p.name || `Phase ${i + 1}`,
                data: [{ x: s, y: yMax }, { x: e, y: yMax }],
                borderWidth: 0,
                pointRadius: 0,
                fill: 'origin',
                backgroundColor: palette[i % palette.length],
                stepped: true,
                order: 99, // draw behind the lines
            };
        });
    }

    function renderGlide(plan) {
        const canvas = $('chart-glide');
        if (!canvas) return;
        const ideal = plan.ideal_line || [];
        const weighIns = plan.weigh_ins || [];
        const horizon = plan.config ? plan.config.horizon_weeks : (ideal.length ? ideal[ideal.length - 1].week : 24);

        const idealPoints = ideal.map((p) => ({ x: p.week, y: p.weight }));
        const actualPoints = weighIns
            .filter((w) => w.weight_kg != null)
            .map((w) => ({ x: w.week, y: w.weight_kg }));

        // Y range from both series for sane phase-band height.
        const ys = idealPoints.concat(actualPoints).map((p) => p.y).filter((v) => v != null);
        const yMin = ys.length ? Math.min(...ys) - 2 : 0;
        const yMax = ys.length ? Math.max(...ys) + 2 : 100;

        const datasets = [
            ...phaseBandDatasets(plan.phases, horizon, yMin, yMax),
            {
                label: 'IDEAL',
                data: idealPoints,
                borderColor: '#00E5FF',
                backgroundColor: 'transparent',
                borderDash: [6, 4],
                tension: 0,
                pointRadius: 0,
                fill: false,
                order: 1,
            },
            {
                label: 'ACTUAL',
                data: actualPoints,
                borderColor: '#00FF66',
                backgroundColor: '#00FF6622',
                tension: 0.2,
                pointRadius: 4,
                pointBackgroundColor: '#00FF66',
                spanGaps: false,
                fill: false,
                order: 0,
            },
        ];

        if (glideChart) glideChart.destroy();
        glideChart = new Chart(canvas, {
            type: 'line',
            data: { datasets },
            options: chartOpts({
                scales: {
                    x: {
                        type: 'linear', min: 0, max: horizon,
                        ticks: { color: '#8A9A86', stepSize: 4, font: { family: "'JetBrains Mono', monospace" } },
                        grid: { color: 'rgba(30,41,59,0.6)' },
                        title: { display: true, text: 'WEEK', color: '#8A9A86', font: { family: "'Share Tech Mono', monospace" } },
                    },
                    y: {
                        min: yMin, max: yMax,
                        ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } },
                        grid: { color: 'rgba(30,41,59,0.6)' },
                        title: { display: true, text: 'KG', color: '#8A9A86', font: { family: "'Share Tech Mono', monospace" } },
                    },
                },
            }),
        });
    }

    function renderAccountability(plan) {
        const acc = plan.accountability;
        const dirLabel = DIRECTION_LABEL[String(plan.direction)] || '';
        $('plan-meta').textContent = `[ ${dirLabel} · ${plan.config.horizon_weeks}-WEEK GLIDE-PATH ]`;

        if (!acc) {
            // Configured but no weigh-ins yet — prompt the first log.
            $('acc-verdict').textContent = '—';
            $('acc-verdict-sub').textContent = 'log a weigh-in';
            ['acc-kg-target', 'acc-weeks-elapsed', 'acc-current-rate', 'acc-required-rate', 'acc-latest'].forEach((id) => { $(id).textContent = '—'; });
            return;
        }

        const v = acc.verdict || 'unknown';
        const vEl = $('acc-verdict');
        vEl.textContent = VERDICT_LABEL[v] || '—';
        vEl.style.color = VERDICT_COLOR[v] || 'var(--muted)';
        $('acc-verdict-sub').textContent = `ideal now ${fmtKg(acc.ideal_now)}`;

        $('acc-kg-target').textContent = fmtKg(Math.abs(acc.kg_to_target));
        $('acc-weeks-elapsed').textContent = fmtWeeks(acc.weeks_elapsed);
        $('acc-weeks-remaining').textContent = `${fmtWeeks(acc.weeks_remaining)} remaining`;
        $('acc-current-rate').textContent = fmtRate(acc.current_rate);
        $('acc-required-rate').textContent = fmtRate(acc.required_rate);
        $('acc-latest').textContent = fmtKg(acc.latest_weight);
        $('acc-latest-date').textContent = acc.latest_date || 'kg';
    }

    function renderMilestones(plan) {
        const el = $('milestones-table');
        const ms = plan.milestones || [];
        if (!ms.length) {
            el.innerHTML = `<div class="no-data">[ NO MILESTONES ]</div>`;
            return;
        }
        const badge = (s) => {
            if (s === 'hit') return `<span class="text-green">HIT</span>`;
            if (s === 'miss') return `<span class="text-danger">MISS</span>`;
            return `<span class="text-muted">·</span>`;
        };
        el.innerHTML = `
            <table class="pr-table">
                <thead><tr>
                    <th>Wk</th>
                    <th>Date</th>
                    <th style="text-align:right;">Ideal</th>
                    <th style="text-align:right;">Actual</th>
                    <th style="text-align:right;">Status</th>
                </tr></thead>
                <tbody>
                ${ms.map((m) => `
                    <tr>
                        <td>${m.week}</td>
                        <td>${m.date}</td>
                        <td style="text-align:right;">${fmtKg(m.ideal_weight)}</td>
                        <td style="text-align:right;">${m.actual_weight == null ? '—' : fmtKg(m.actual_weight)}</td>
                        <td style="text-align:right;">${badge(m.status)}</td>
                    </tr>`).join('')}
                </tbody>
            </table>`;
    }

    function renderWeightLog(plan) {
        const el = $('weight-log-list');
        const weighIns = (plan.weigh_ins || []).slice().reverse(); // newest first
        if (!weighIns.length) {
            el.innerHTML = `<div class="no-data">[ NO WEIGH-INS LOGGED ]</div>`;
            return;
        }
        el.innerHTML = `
            <table class="pr-table">
                <thead><tr>
                    <th>Date</th>
                    <th style="text-align:right;">Weight</th>
                    <th style="text-align:right;">Δ ideal</th>
                    <th style="text-align:right;"></th>
                </tr></thead>
                <tbody>
                ${weighIns.map((w) => {
                    const delta = (w.weight_kg != null && w.ideal != null) ? (w.weight_kg - w.ideal) : null;
                    const dCls = delta == null ? 'text-muted' : (delta <= 0 ? 'text-green' : 'text-warn');
                    return `
                    <tr>
                        <td>${w.date}</td>
                        <td style="text-align:right;">${fmtKg(w.weight_kg)}</td>
                        <td style="text-align:right;" class="${dCls}">${delta == null ? '—' : (delta > 0 ? '+' : '') + delta.toFixed(1)}</td>
                        <td style="text-align:right;">
                            <button class="hud-btn icon danger" data-del-date="${w.date}" title="Delete">[ X ]</button>
                        </td>
                    </tr>`;
                }).join('')}
                </tbody>
            </table>`;

        el.querySelectorAll('[data-del-date]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const date = btn.getAttribute('data-del-date');
                const ok = await window.hudConfirm(`Delete the weigh-in for ${date}?`, { kind: 'danger', confirmText: 'DELETE' });
                if (!ok) return;
                try {
                    await api.deleteWeight(date);
                    await refresh();
                } catch (e) {
                    window.hudAlert(`Delete failed: ${e.message}`, { kind: 'danger' });
                }
            });
        });
    }

    // ---- phase editor (optional) ----
    function addPhaseRow(phase = { name: '', start_week: '', end_week: '' }) {
        const rows = $('phase-rows');
        const row = document.createElement('div');
        row.className = 'row-tight phase-row';
        row.innerHTML = `
            <input class="hud-input phase-name" placeholder="Phase name" value="${phase.name || ''}" style="flex: 2 1 160px;" />
            <input class="hud-input phase-start" type="number" inputmode="numeric" min="0" max="104" placeholder="from wk" value="${phase.start_week ?? ''}" style="flex: 1 1 90px;" />
            <input class="hud-input phase-end" type="number" inputmode="numeric" min="0" max="104" placeholder="to wk" value="${phase.end_week ?? ''}" style="flex: 1 1 90px;" />
            <button class="hud-btn icon danger phase-del" type="button" title="Remove phase">[ X ]</button>`;
        row.querySelector('.phase-del').addEventListener('click', () => row.remove());
        rows.appendChild(row);
    }

    function collectPhases() {
        const out = [];
        document.querySelectorAll('#phase-rows .phase-row').forEach((row) => {
            const name = row.querySelector('.phase-name').value.trim();
            const s = row.querySelector('.phase-start').value;
            const e = row.querySelector('.phase-end').value;
            if (!name || s === '' || e === '') return; // skip incomplete rows
            out.push({ name, start_week: parseInt(s, 10), end_week: parseInt(e, 10) });
        });
        return out;
    }

    function prefillConfig(plan) {
        if (plan.configured && plan.config) {
            const c = plan.config;
            $('cfg-start-date').value = c.start_date || '';
            $('cfg-start-weight').value = c.start_weight != null ? c.start_weight : '';
            $('cfg-target-weight').value = c.target_weight != null ? c.target_weight : '';
            $('cfg-horizon').value = c.horizon_weeks != null ? c.horizon_weeks : 24;
            $('phase-rows').innerHTML = '';
            (plan.phases || []).forEach((p) => addPhaseRow(p));
            $('setup-meta').textContent = 'Update the plan';
        } else {
            // Empty state — sensible defaults; start date = today.
            if (!$('cfg-start-date').value) $('cfg-start-date').value = todayISO();
            $('setup-meta').textContent = 'Create the plan';
        }
    }

    // ---- top-level render ----
    function render(plan) {
        const configured = !!plan.configured;
        $('empty-state').classList.toggle('hidden', configured);
        $('plan-view').classList.toggle('hidden', !configured);

        if (configured) {
            renderAccountability(plan);
            renderGlide(plan);
            renderMilestones(plan);
            renderWeightLog(plan);
        } else {
            $('plan-meta').textContent = '[ NOT CONFIGURED ]';
        }
        prefillConfig(plan);
    }

    async function refresh() {
        const plan = await api.getPlan();
        render(plan);
        return plan;
    }

    // ---- actions ----
    async function onSaveConfig() {
        const body = {
            start_date: $('cfg-start-date').value,
            start_weight: parseFloat($('cfg-start-weight').value),
            target_weight: parseFloat($('cfg-target-weight').value),
            horizon_weeks: parseInt($('cfg-horizon').value, 10) || 24,
            phases: collectPhases(),
        };
        if (!body.start_date || !isFinite(body.start_weight) || !isFinite(body.target_weight)) {
            window.hudAlert('Start date, start weight and target weight are required.', { kind: 'warn' });
            return;
        }
        const status = $('setup-status');
        status.textContent = 'Saving…';
        try {
            await api.savePlanConfig(body);
            status.textContent = 'Saved.';
            await refresh();
            setTimeout(() => { status.textContent = ''; }, 2000);
        } catch (e) {
            status.textContent = '';
            window.hudAlert(`Save failed: ${e.message}`, { kind: 'danger' });
        }
    }

    async function onLogWeight() {
        const weight = parseFloat($('weight-input').value);
        const date = $('weight-date').value || todayISO();
        if (!isFinite(weight) || weight <= 0) {
            window.hudAlert('Enter a weight greater than 0.', { kind: 'warn' });
            return;
        }
        try {
            await api.logWeight({ date, weight_kg: weight });
            $('weight-input').value = '';
            await refresh();
        } catch (e) {
            window.hudAlert(`Log failed: ${e.message}`, { kind: 'danger' });
        }
    }

    // ---- wire up ----
    document.addEventListener('DOMContentLoaded', () => {
        const wd = $('weight-date');
        if (wd && !wd.value) wd.value = todayISO();
    });
    $('save-config-btn').addEventListener('click', onSaveConfig);
    $('log-today-btn').addEventListener('click', onLogWeight);
    $('add-phase-btn').addEventListener('click', () => addPhaseRow());

    try {
        await refresh();
    } catch (e) {
        console.error(e);
        document.querySelector('main').insertAdjacentHTML('afterbegin',
            `<div class="no-data text-danger">[ PLAN FETCH FAILED: ${e.message} ]</div>`);
    }
})();
