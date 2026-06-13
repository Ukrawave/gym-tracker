// progress.js — per-exercise progress charts and PR table.

(async () => {
    const picker = document.getElementById('exercise-picker');
    const metaEl = document.getElementById('exercise-meta');
    const prTable = document.getElementById('pr-table');
    let charts = { weight: null, oneRm: null, volume: null };

    function destroyCharts() {
        Object.values(charts).forEach(c => { if (c) c.destroy(); });
        charts = { weight: null, oneRm: null, volume: null };
    }

    function lineChart(canvas, label, color, labels, values) {
        return new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label, data: values,
                    borderColor: color,
                    backgroundColor: color + '33',
                    fill: true, tension: 0.3, pointRadius: 4,
                    pointBackgroundColor: color,
                }],
            },
            options: chartOpts(),
        });
    }
    function barChart(canvas, label, color, labels, values) {
        return new Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{ label, data: values, backgroundColor: color, borderColor: color, borderWidth: 1 }],
            },
            options: chartOpts(),
        });
    }
    function chartOpts() {
        return {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#C7D2D0', font: { family: "'Share Tech Mono', monospace" } } } },
            scales: {
                x: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
                y: { ticks: { color: '#8A9A86', font: { family: "'JetBrains Mono', monospace" } }, grid: { color: 'rgba(30,41,59,0.6)' } },
            }
        };
    }

    // Replace whatever lives in the chart-wrap with a fresh <canvas id=...>
    // and return that canvas. This is the only way to safely re-render after
    // a no-data placeholder has been swapped in.
    function freshCanvas(id) {
        const wrap = document.querySelector(`.chart-wrap[data-canvas="${id}"]`)
                  || document.getElementById(id)?.closest('.chart-wrap');
        if (!wrap) return null;
        wrap.dataset.canvas = id;
        wrap.innerHTML = '';
        const c = document.createElement('canvas');
        c.id = id;
        wrap.appendChild(c);
        return c;
    }

    // Replace the chart-wrap contents with a no-data placeholder div.
    function emptyCanvas(id, msg = '[ NO DATA ]') {
        const wrap = document.querySelector(`.chart-wrap[data-canvas="${id}"]`)
                  || document.getElementById(id)?.closest('.chart-wrap');
        if (!wrap) return;
        wrap.dataset.canvas = id;
        wrap.innerHTML = '';
        const div = document.createElement('div');
        div.className = 'no-data';
        div.textContent = msg;
        div.style.height = '100%';
        div.style.display = 'flex';
        div.style.alignItems = 'center';
        div.style.justifyContent = 'center';
        wrap.appendChild(div);
    }

    async function load(id) {
        const data = await api.progressForExercise(id);
        const ex = data.exercise;
        metaEl.innerHTML = `[ ${ex.name.toUpperCase()} · ${ex.muscle_group.toUpperCase()} ]`;
        destroyCharts();

        if (!data.series.length) {
            ['chart-weight','chart-1rm','chart-volume'].forEach(cid => emptyCanvas(cid));
        } else {
            const labels = data.series.map(p => p.date);
            const wcv = freshCanvas('chart-weight');
            const rcv = freshCanvas('chart-1rm');
            const vcv = freshCanvas('chart-volume');
            if (wcv) charts.weight = lineChart(wcv, 'MAX WEIGHT (KG)', '#00E5FF',
                labels, data.series.map(p => p.max_weight));
            if (rcv) charts.oneRm = lineChart(rcv, 'EST 1RM (KG)', '#00FF66',
                labels, data.series.map(p => p.est_1rm));
            if (vcv) charts.volume = barChart(vcv, 'SESSION VOLUME (KG)', '#FF9900',
                labels, data.series.map(p => p.total_volume));
        }

        // PR table
        try {
            const prs = await api.exerciseRecords(id);
            if (!prs.length) {
                prTable.innerHTML = `<div class="no-data">[ NO PRs RECORDED ]</div>`;
            } else {
                prTable.innerHTML = `
                <table class="w-full text-sm mono">
                    <thead>
                        <tr class="uppercase-hud text-muted text-xs">
                            <th class="text-left p-1">DATE</th>
                            <th class="text-right p-1">WEIGHT</th>
                            <th class="text-right p-1">REPS</th>
                            <th class="text-right p-1">EST 1RM</th>
                            <th class="text-right p-1">SET ID</th>
                        </tr>
                    </thead>
                    <tbody>
                    ${prs.map((p, i) => `
                        <tr style="border-top: 1px solid var(--border);">
                            <td class="p-1">${p.pr_date} ${i === 0 ? '<span class="led led-green led-pulse"></span>' : ''}</td>
                            <td class="text-right p-1 text-green">${p.set_weight} KG</td>
                            <td class="text-right p-1">${p.set_reps}</td>
                            <td class="text-right p-1 text-info">${Math.round(p.est_1rm)} KG</td>
                            <td class="text-right p-1 text-muted">#${p.set_entry_id}</td>
                        </tr>
                    `).join('')}
                    </tbody>
                </table>`;
            }
        } catch (e) {
            prTable.innerHTML = `<div class="no-data text-danger">[ PR FETCH FAILED ]</div>`;
        }
    }

    try {
        const exs = await api.listExercises();
        // Group by muscle for the dropdown
        const byMuscle = {};
        for (const e of exs) (byMuscle[e.muscle_group] = byMuscle[e.muscle_group] || []).push(e);
        picker.innerHTML = Object.entries(byMuscle).sort().map(([m, list]) =>
            `<optgroup label="${m}">${list.map(e =>
                `<option value="${e.id}">${e.name}</option>`).join('')}</optgroup>`
        ).join('');
        // Preselect if URL hash
        const hash = location.hash.replace('#','');
        if (hash && exs.find(e => e.id === hash)) picker.value = hash;
        picker.addEventListener('change', () => load(picker.value));
        if (picker.value) await load(picker.value);
    } catch (e) {
        document.querySelector('main').insertAdjacentHTML('afterbegin',
            `<div class="no-data text-danger">[ PROGRESS FETCH FAILED: ${e.message} ]</div>`);
    }
})();
