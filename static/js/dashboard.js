// dashboard.js — fetch /api/dashboard and paint the HUD panels + charts.

(async () => {
    const $ = (id) => document.getElementById(id);

    function paintTelemetry(d) {
        $('tel-total-sessions').textContent = hudUtil.formatNumber(d.total_sessions);
        $('tel-total-volume').textContent   = hudUtil.formatVolume(d.total_volume_kg);
        $('tel-last7').textContent          = hudUtil.formatNumber(d.sessions_last_7_days);
        $('tel-last30').textContent         = hudUtil.formatNumber(d.sessions_last_30_days);
        $('tel-total-sets').textContent     = hudUtil.formatNumber(d.total_sets);
        $('tel-total-reps').textContent     = hudUtil.formatNumber(d.total_reps);
    }

    function paintPRs(d) {
        const ul = $('pr-list');
        if (!d.recent_prs || d.recent_prs.length === 0) {
            ul.innerHTML = `<li class="no-data">[ NO PRs YET ]</li>`;
            return;
        }
        ul.innerHTML = d.recent_prs.map((p, i) => `
            <li class="flex items-center gap-2">
                <span class="led ${i === 0 ? 'led-green led-pulse' : 'led-green'}"></span>
                <span class="text-muted">${p.pr_date}</span>
                <span class="text-info uppercase-hud">${p.exercise_name}</span>
                <span class="text-green">${p.max_weight}KG</span>
                <span class="text-muted">·</span>
                <span class="text-muted">est-1RM ${Math.round(p.est_1rm)}KG</span>
                ${i === 0 ? '<span class="text-warn uppercase-hud">[ PR_LOCKED ]</span>' : ''}
            </li>
        `).join('');
    }

    function paintSessions(d) {
        const ul = $('session-list');
        if (!d.recent_sessions || d.recent_sessions.length === 0) {
            ul.innerHTML = `<li class="no-data">[ NO SESSIONS LOGGED ]</li>`;
            return;
        }
        ul.innerHTML = d.recent_sessions.map((s) => `
            <li class="flex items-center gap-2">
                <span class="led led-cyan"></span>
                <span class="text-muted">${s.date}</span>
                <span class="text-info uppercase-hud">${s.category}</span>
                <span class="text-muted">·</span>
                <span class="text-green">${hudUtil.formatVolume(s.total_volume)}</span>
                <span class="text-muted">${s.total_sets} SETS</span>
            </li>
        `).join('');
    }

    function paintResumeCTA(d) {
        const wrap = $('resume-cta');
        if (!d.current_session) { wrap.style.display = 'none'; return; }
        wrap.style.display = '';
        const cs = d.current_session;
        $('active-session-info').textContent =
            `${cs.category.toUpperCase()} · STARTED ${hudUtil.formatTimestamp(cs.start_time)}`;
    }

    function paintWeekly(d) {
        const canvas = document.getElementById('chart-weekly');
        const labels = (d.weekly_volume || []).map(w => w.week);
        const values = (d.weekly_volume || []).map(w => w.volume);
        if (!labels.length) {
            canvas.replaceWith(Object.assign(document.createElement('div'),
                { className: 'no-data', textContent: '[ NO TRAINING DATA YET ]' }));
            return;
        }
        new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'WEEKLY VOLUME (KG)',
                    data: values,
                    borderColor: '#00E5FF',
                    backgroundColor: 'rgba(0, 229, 255, 0.15)',
                    fill: true,
                    tension: 0.3,
                    pointBackgroundColor: '#00FF66',
                    pointRadius: 4,
                }],
            },
            options: chartOpts(),
        });
    }

    function paintMuscle(d) {
        const canvas = document.getElementById('chart-muscle');
        const entries = Object.entries(d.muscle_distribution || {});
        if (!entries.length) {
            canvas.replaceWith(Object.assign(document.createElement('div'),
                { className: 'no-data', textContent: '[ NO RECENT SET DATA ]' }));
            return;
        }
        const palette = ['#00E5FF','#00FF66','#FF9900','#C77DFF','#FF3333','#8A9A86','#FFD166','#06D6A0'];
        new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: entries.map(([k]) => k.toUpperCase()),
                datasets: [{
                    data: entries.map(([, v]) => v),
                    backgroundColor: entries.map((_, i) => palette[i % palette.length]),
                    borderColor: '#0A0F14',
                    borderWidth: 2,
                }],
            },
            options: {
                ...chartOpts(),
                cutout: '60%',
                plugins: { legend: { position: 'right', labels: { color: '#C7D2D0', font: { family: "'Share Tech Mono', monospace" } } } },
            }
        });
    }

    function chartOpts() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#C7D2D0', font: { family: "'Share Tech Mono', monospace" } } },
                tooltip: { bodyFont: { family: "'JetBrains Mono', monospace" } }
            },
            scales: {
                x: {
                    ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } },
                    grid:  { color: 'rgba(30, 41, 59, 0.6)' },
                },
                y: {
                    ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } },
                    grid:  { color: 'rgba(30, 41, 59, 0.6)' },
                }
            }
        };
    }

    try {
        const d = await api.dashboard();
        paintTelemetry(d);
        paintResumeCTA(d);
        paintPRs(d);
        paintSessions(d);
        paintWeekly(d);
        paintMuscle(d);
    } catch (e) {
        console.error(e);
        document.querySelector('main').insertAdjacentHTML(
            'afterbegin',
            `<div class="no-data text-danger">[ DASHBOARD FETCH FAILED: ${e.message} ]</div>`,
        );
    }
})();
