// training.js — training load + resting HR trends, derived readiness LED.
// Read-only over /api/fitness/training. NULL-safe; readiness is clearly DERIVED.

(async () => {
    const $ = (id) => document.getElementById(id);

    function chartOpts() {
        return {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#C7D2D0', font: { family: "'Share Tech Mono', monospace" } } },
                tooltip: { bodyFont: { family: "'JetBrains Mono', monospace" } },
            },
            scales: {
                x: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
                y: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
            },
        };
    }

    function emptyCanvas(id, msg = '[ NO DATA ]') {
        const canvas = $(id);
        if (!canvas) return;
        canvas.replaceWith(Object.assign(document.createElement('div'),
            { className: 'no-data', textContent: msg }));
    }

    // Map readiness state -> LED class + headline colour.
    const READINESS = {
        push: { led: 'led-green', cls: 'text-green', label: 'PUSH' },
        hold: { led: 'led-amber', cls: 'text-warn',  label: 'HOLD' },
        rest: { led: 'led-red',   cls: 'text-danger', label: 'REST' },
    };

    function paintReadiness(d) {
        const r = d.readiness || { state: 'hold', reason: 'no data' };
        const conf = READINESS[r.state] || READINESS.hold;
        const led = $('readiness-led');
        led.className = `led ${conf.led} led-pulse`;
        const stateEl = $('readiness-state');
        stateEl.textContent = conf.label;
        stateEl.className = `readiness-state ${conf.cls}`;
        $('readiness-reason').textContent = r.reason || '';
    }

    function paintInputs(d) {
        const i = d.inputs || {};
        $('train-acute').textContent = i.acute_load != null ? Math.round(i.acute_load) : '—';
        $('train-acute-base').textContent =
            i.load_baseline != null ? `baseline ${Math.round(i.load_baseline)}` : 'no baseline';
        $('train-rhr').textContent = i.rhr_latest != null ? i.rhr_latest : '—';
        $('train-rhr-base').textContent =
            i.rhr_baseline != null ? `baseline ${i.rhr_baseline} bpm` : 'bpm';

        // Latest chronic load from the series (last non-null).
        const ls = d.load_series || [];
        let chronic = null;
        for (let k = ls.length - 1; k >= 0; k--) {
            if (ls[k].chronic != null) { chronic = ls[k].chronic; break; }
        }
        $('train-chronic').textContent = chronic != null ? Math.round(chronic) : '—';
    }

    function paintLoad(d) {
        const ls = d.load_series || [];
        if (!ls.length) { emptyCanvas('chart-load', '[ NO LOAD DATA ]'); return; }
        const canvas = $('chart-load');
        new Chart(canvas, {
            type: 'line',
            data: {
                labels: ls.map(p => p.date),
                datasets: [
                    {
                        label: 'ACUTE', data: ls.map(p => p.acute),
                        borderColor: '#FF9900', backgroundColor: 'rgba(255,153,0,0.15)',
                        fill: true, tension: 0.3, pointRadius: 2, spanGaps: false,
                    },
                    {
                        label: 'CHRONIC', data: ls.map(p => p.chronic),
                        borderColor: '#00E5FF', backgroundColor: 'rgba(0,229,255,0.08)',
                        fill: false, tension: 0.3, pointRadius: 2, spanGaps: false,
                    },
                ],
            },
            options: chartOpts(),
        });
    }

    function paintRhr(d) {
        const rs = (d.resting_hr_series || []).filter(p => p.value != null);
        if (!rs.length) { emptyCanvas('chart-rhr', '[ NO RESTING HR DATA ]'); return; }
        const canvas = $('chart-rhr');
        new Chart(canvas, {
            type: 'line',
            data: {
                labels: rs.map(p => p.date),
                datasets: [{
                    label: 'RESTING HR (BPM)', data: rs.map(p => p.value),
                    borderColor: '#00FF66', backgroundColor: 'rgba(0,255,102,0.12)',
                    fill: true, tension: 0.3, pointRadius: 2, spanGaps: false,
                }],
            },
            options: chartOpts(),
        });
    }

    try {
        const d = await api.fitnessTraining();
        paintReadiness(d);
        paintInputs(d);
        paintLoad(d);
        paintRhr(d);
    } catch (e) {
        console.error(e);
        document.querySelector('main').insertAdjacentHTML('afterbegin',
            `<div class="no-data text-danger">[ TRAINING FETCH FAILED: ${e.message} ]</div>`);
    }
})();
