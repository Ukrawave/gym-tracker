// sleep.js — sleep score, stage breakdown, body battery + stress.
// Read-only over /api/fitness/sleep. NULL nights are already dropped server-side.

(async () => {
    const $ = (id) => document.getElementById(id);

    const fmtHours = (s) => (s == null ? '—' : (Number(s) / 3600).toFixed(1));

    function chartOpts(extra = {}) {
        return Object.assign({
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#C7D2D0', font: { family: "'Share Tech Mono', monospace" } } },
                tooltip: { bodyFont: { family: "'JetBrains Mono', monospace" } },
            },
            scales: {
                x: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
                y: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
            },
        }, extra);
    }

    function emptyCanvas(id, msg = '[ NO DATA ]') {
        const canvas = $(id);
        if (!canvas) return;
        canvas.replaceWith(Object.assign(document.createElement('div'),
            { className: 'no-data', textContent: msg }));
    }

    function paintSummary(d) {
        const nights = d.nights || [];
        if (!nights.length) return;
        const last = nights[nights.length - 1];
        $('sleep-last-score').textContent = last.score != null ? last.score : '—';
        $('sleep-last-date').textContent = last.date || '/ 100';
        $('sleep-last-dur').textContent = fmtHours(last.duration_s);

        const scores = nights.map(n => n.score).filter(v => v != null);
        const durs = nights.map(n => n.duration_s).filter(v => v != null);
        $('sleep-avg-score').textContent =
            scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : '—';
        $('sleep-nights-count').textContent = `${nights.length} tracked night${nights.length === 1 ? '' : 's'}`;
        $('sleep-avg-dur').textContent =
            durs.length ? (durs.reduce((a, b) => a + b, 0) / durs.length / 3600).toFixed(1) : '—';
    }

    function paintScore(d) {
        const s = d.score_series || [];
        if (!s.length) { emptyCanvas('chart-score', '[ NO SLEEP SCORE DATA ]'); return; }
        new Chart($('chart-score'), {
            type: 'line',
            data: {
                labels: s.map(p => p.date),
                datasets: [{
                    label: 'SLEEP SCORE', data: s.map(p => p.score),
                    borderColor: '#00FF66', backgroundColor: 'rgba(0,255,102,0.12)',
                    fill: true, tension: 0.3, pointRadius: 3, spanGaps: false,
                }],
            },
            options: chartOpts({ scales: {
                x: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
                y: { min: 0, max: 100, ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
            } }),
        });
    }

    function paintStages(d) {
        // Stacked bars of deep/light/REM/awake (hours) for recent tracked nights.
        const nights = (d.nights || []).slice(-14);
        if (!nights.length) { emptyCanvas('chart-stages', '[ NO STAGE DATA ]'); return; }
        const toH = (s) => (s == null ? null : Number(s) / 3600);
        new Chart($('chart-stages'), {
            type: 'bar',
            data: {
                labels: nights.map(n => n.date),
                datasets: [
                    { label: 'DEEP',  data: nights.map(n => toH(n.deep_s)),  backgroundColor: '#00E5FF' },
                    { label: 'LIGHT', data: nights.map(n => toH(n.light_s)), backgroundColor: '#3A7BD5' },
                    { label: 'REM',   data: nights.map(n => toH(n.rem_s)),   backgroundColor: '#00FF66' },
                    { label: 'AWAKE', data: nights.map(n => toH(n.awake_s)), backgroundColor: '#FF9900' },
                ],
            },
            options: chartOpts({
                scales: {
                    x: { stacked: true, ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
                    y: { stacked: true, ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' }, title: { display: true, text: 'hours', color: '#8A9A86' } },
                },
            }),
        });
    }

    function paintBattery(d) {
        const bb = (d.body_battery_series || []).slice(-30);
        if (!bb.length) { emptyCanvas('chart-battery', '[ NO BODY BATTERY DATA ]'); return; }
        new Chart($('chart-battery'), {
            type: 'line',
            data: {
                labels: bb.map(p => p.date),
                datasets: [
                    {
                        label: 'HIGH', data: bb.map(p => p.high),
                        borderColor: '#00FF66', backgroundColor: 'rgba(0,255,102,0.10)',
                        fill: false, tension: 0.3, pointRadius: 2, spanGaps: false,
                    },
                    {
                        label: 'LOW', data: bb.map(p => p.low),
                        borderColor: '#FF9900', backgroundColor: 'rgba(255,153,0,0.10)',
                        fill: false, tension: 0.3, pointRadius: 2, spanGaps: false,
                    },
                ],
            },
            options: chartOpts({ scales: {
                x: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
                y: { min: 0, max: 100, ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
            } }),
        });
    }

    function paintStress(d) {
        const ss = (d.stress_series || []).slice(-30).filter(p => p.value != null);
        if (!ss.length) { emptyCanvas('chart-stress', '[ NO STRESS DATA ]'); return; }
        new Chart($('chart-stress'), {
            type: 'bar',
            data: {
                labels: ss.map(p => p.date),
                datasets: [{
                    label: 'STRESS (AVG)', data: ss.map(p => p.value),
                    backgroundColor: '#C77DFF', borderColor: '#C77DFF', borderWidth: 1,
                }],
            },
            options: chartOpts({ scales: {
                x: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
                y: { min: 0, max: 100, ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
            } }),
        });
    }

    try {
        const d = await api.fitnessSleep();
        paintSummary(d);
        paintScore(d);
        paintStages(d);
        paintBattery(d);
        paintStress(d);
    } catch (e) {
        console.error(e);
        document.querySelector('main').insertAdjacentHTML('afterbegin',
            `<div class="no-data text-danger">[ SLEEP FETCH FAILED: ${e.message} ]</div>`);
    }
})();
