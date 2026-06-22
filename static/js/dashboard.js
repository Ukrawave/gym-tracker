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
            <li>
                <span class="led ${i === 0 ? 'led-green led-pulse' : 'led-green'}"></span>
                <span class="date">${p.pr_date}</span>
                <span class="name">${p.exercise_name}</span>
                <span class="metric">${p.max_weight} kg</span>
                <span class="sub">est-1RM ${Math.round(p.est_1rm)} kg</span>
                ${i === 0 ? '<span class="text-warn uppercase-hud text-xs">[ PR_LOCKED ]</span>' : ''}
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
            <li>
                <span class="led led-cyan"></span>
                <span class="date">${s.date}</span>
                <span class="name">${s.category}</span>
                <span class="metric">${hudUtil.formatVolume(s.total_volume)}</span>
                <span class="sub">${s.total_sets} sets</span>
            </li>
        `).join('');
    }

    function paintResumeCTA(d) {
        const wrap = $('resume-cta');
        if (!d.current_session) { wrap.classList.add('hidden'); return; }
        wrap.classList.remove('hidden');
        const cs = d.current_session;
        $('active-session-info').textContent =
            `${cs.category.toUpperCase()} · started ${hudUtil.formatTimestamp(cs.start_time)}`;
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
                responsive: true,
                maintainAspectRatio: false,
                cutout: '60%',
                // No x/y axes on a doughnut — explicit override fixes the bug
                // where Chart.js v4 paints stray numeric scale labels.
                scales: { x: { display: false }, y: { display: false } },
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            color: '#C7D2D0',
                            font: { family: "'Share Tech Mono', monospace" },
                            boxWidth: 12,
                            padding: 10,
                        },
                    },
                    tooltip: { bodyFont: { family: "'JetBrains Mono', monospace" } },
                },
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

    // ---- Fitness Overview tiles (Phase 1, Garmin + Strava) -------------------
    // Fetched independently so a fitness-data hiccup never blanks the core
    // training dashboard above.
    function fmtPace(sPerKm) {
        if (sPerKm == null || !isFinite(sPerKm)) return '—';
        const s = Math.round(sPerKm);
        return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    }

    function paintOverview(o) {
        // VO2max
        if (o.vo2max) {
            $('ov-vo2max').textContent = o.vo2max.value;
            $('ov-vo2max-date').textContent = `as of ${o.vo2max.date}`;
        }
        // Last run — distance + pace
        if (o.last_run) {
            const km = o.last_run.distance_m != null ? (o.last_run.distance_m / 1000).toFixed(2) : '—';
            $('ov-run-dist').textContent = `${km} km`;
            $('ov-run-pace').textContent = `${fmtPace(o.last_run.pace_s_per_km)}/km · ${o.last_run.date || ''}`;
        }
        // Resting HR (latest wellness reading)
        if (o.resting_hr) {
            $('ov-rhr').textContent = o.resting_hr.value != null ? o.resting_hr.value : '—';
        }
        // Body Battery high/low
        if (o.body_battery) {
            $('ov-battery').textContent = o.body_battery.high != null ? o.body_battery.high : '—';
            $('ov-battery-date').textContent =
                `high / low ${o.body_battery.low != null ? o.body_battery.low : '—'}`;
        }
        // Last sleep score
        if (o.last_sleep) {
            $('ov-sleep').textContent = o.last_sleep.score != null ? o.last_sleep.score : '—';
            $('ov-sleep-date').textContent = o.last_sleep.date || 'last night';
        }
        // Data freshness LED: green if any source synced, amber if never.
        const led = $('ov-fresh-led');
        const sub = $('ov-fresh-sub');
        const fresh = o.freshness || {};
        if (fresh.last_sync) {
            led.className = 'led led-green led-pulse';
            sub.textContent = `synced ${hudUtil.formatTimestamp(fresh.last_sync)}`;
        } else {
            led.className = 'led led-amber';
            sub.textContent = 'never synced';
        }
    }

    try {
        const o = await api.fitnessOverview();
        paintOverview(o);
    } catch (e) {
        console.warn('fitness overview unavailable:', e.message);
        // Leave the Overview tiles at their '—' placeholders; core dash is fine.
    }
})();
