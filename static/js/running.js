// running.js — VO2max trend, race predictions, deduped recent runs.
// Read-only over /api/fitness/running. NULL-safe: gaps lines, never plots 0.

(async () => {
    const $ = (id) => document.getElementById(id);

    // ---- formatting helpers (local; mirror hudUtil style) ----
    const fmtKm = (m) => (m == null ? '—' : (Number(m) / 1000).toFixed(2) + ' km');
    const fmtPace = (sPerKm) => {
        if (sPerKm == null || !isFinite(sPerKm)) return '—';
        const s = Math.round(sPerKm);
        const mm = Math.floor(s / 60), ss = s % 60;
        return `${mm}:${String(ss).padStart(2, '0')}`;
    };
    const fmtHr = (v) => (v == null ? '—' : `${v}`);

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

    function lineChart(id, label, color, labels, values, { stepped = false } = {}) {
        const canvas = $(id);
        if (!canvas) return;
        new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label, data: values,
                    borderColor: color, backgroundColor: color + '22',
                    fill: true, tension: stepped ? 0 : 0.3, stepped,
                    pointRadius: 3, pointBackgroundColor: color,
                    spanGaps: false, // gap NULL points rather than interpolate over them
                }],
            },
            options: chartOpts(),
        });
    }

    function paintSummary(d) {
        const runs = d.runs || [];
        const series = d.vo2max_series || [];
        if (series.length) {
            const last = series[series.length - 1];
            $('run-vo2max').textContent = last.value;
            $('run-vo2max-date').textContent = `as of ${last.date}`;
        }
        if (runs.length) {
            const r = runs[0];
            $('run-last-dist').textContent = fmtKm(r.distance_m);
            $('run-last-date').textContent = r.date || 'last run';
            $('run-last-pace').textContent = fmtPace(r.pace_s_per_km);
            $('run-last-hr').textContent = fmtHr(r.avg_hr);

            // 30-day rollup from the most recent run date.
            const anchor = new Date((r.start_time || r.date) + (/[zZ]/.test(r.start_time || '') ? '' : 'Z'));
            const cutoff = new Date(anchor.getTime() - 30 * 86400000);
            const recent = runs.filter(x => {
                const t = new Date((x.start_time || x.date) + (/[zZ]/.test(x.start_time || '') ? '' : 'Z'));
                return !isNaN(t) && t >= cutoff;
            });
            const totalM = recent.reduce((a, x) => a + (x.distance_m || 0), 0);
            const totalS = recent.reduce((a, x) => a + (x.duration_s || 0), 0);
            $('run-30d-dist').textContent = (totalM / 1000).toFixed(1) + ' km';
            $('run-30d-count').textContent = `${recent.length} run${recent.length === 1 ? '' : 's'}`;
            $('run-30d-pace').textContent = totalM > 0 ? fmtPace(totalS / (totalM / 1000)) : '—';
        }
    }

    function paintPredictions(d) {
        const el = $('pred-table');
        const preds = d.race_predictions || [];
        if (!preds.length) {
            el.innerHTML = `<div class="no-data">[ NO RECENT RUN TO PREDICT FROM ]</div>`;
            return;
        }
        if (d.prediction_basis) {
            const b = d.prediction_basis;
            $('pred-basis').textContent = `Riegel · from ${fmtKm(b.distance_m)} @ ${fmtPace(b.pace_s_per_km)}/km`;
        }
        el.innerHTML = `
            <table class="pr-table">
                <thead><tr><th>Distance</th><th style="text-align:right;">Predicted</th></tr></thead>
                <tbody>
                ${preds.map(p => `
                    <tr>
                        <td>${p.distance}</td>
                        <td style="text-align:right;" class="text-green">${p.time}</td>
                    </tr>`).join('')}
                </tbody>
            </table>`;
    }

    function paintRuns(d) {
        const el = $('runs-table');
        const runs = (d.runs || []).slice(0, 12);
        if (!runs.length) {
            el.innerHTML = `<div class="no-data">[ NO RUNS RECORDED ]</div>`;
            return;
        }
        el.innerHTML = `
            <table class="pr-table">
                <thead><tr>
                    <th>Date</th>
                    <th style="text-align:right;">Dist</th>
                    <th style="text-align:right;">Pace</th>
                    <th style="text-align:right;">HR</th>
                    <th style="text-align:right;">Src</th>
                </tr></thead>
                <tbody>
                ${runs.map(r => `
                    <tr>
                        <td>${r.date || '—'}</td>
                        <td style="text-align:right;">${fmtKm(r.distance_m)}</td>
                        <td style="text-align:right;" class="text-info">${fmtPace(r.pace_s_per_km)}</td>
                        <td style="text-align:right;">${fmtHr(r.avg_hr)}</td>
                        <td style="text-align:right;" class="text-muted">${(r.source || '').slice(0, 3).toUpperCase()}</td>
                    </tr>`).join('')}
                </tbody>
            </table>`;
    }

    try {
        const d = await api.fitnessRunning();
        paintSummary(d);
        paintPredictions(d);
        paintRuns(d);

        const series = d.vo2max_series || [];
        if (!series.length) {
            emptyCanvas('chart-vo2max', '[ NO VO2MAX DATA ]');
        } else {
            // Step chart: VO2max only changes after a qualifying run — that flat
            // step shape is the correct representation, not interpolated noise.
            lineChart('chart-vo2max', 'VO2MAX', '#00FF66',
                series.map(p => p.date), series.map(p => p.value), { stepped: true });
        }
    } catch (e) {
        console.error(e);
        document.querySelector('main').insertAdjacentHTML('afterbegin',
            `<div class="no-data text-danger">[ RUNNING FETCH FAILED: ${e.message} ]</div>`);
    }
})();
