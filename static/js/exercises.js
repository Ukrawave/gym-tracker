// exercises.js — exercise catalog view (grid + filter + detail modal).

(async () => {
    const grid = document.getElementById('grid');
    const countEl = document.getElementById('cat-count');
    const search = document.getElementById('search');
    const chipsWrap = document.getElementById('filter-chips');

    let exercises = [];
    let activeMuscle = 'ALL';
    let q = '';

    function muscleGroups(list) {
        const set = new Set(list.map(e => e.muscle_group));
        return ['ALL', ...Array.from(set).sort()];
    }

    function renderChips() {
        const groups = muscleGroups(exercises);
        chipsWrap.innerHTML = groups.map(g => `
            <button class="hud-btn ${g === activeMuscle ? '' : ''}" data-mg="${g}"
                style="${g === activeMuscle ? 'background: var(--info); color: var(--bg);' : ''}">
                [ ${g} ]
            </button>
        `).join('');
        chipsWrap.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => {
                activeMuscle = btn.dataset.mg;
                renderChips();
                renderGrid();
            });
        });
    }

    function renderGrid() {
        const ql = q.trim().toLowerCase();
        const filtered = exercises.filter(e => {
            if (activeMuscle !== 'ALL' && e.muscle_group !== activeMuscle) return false;
            if (ql && !e.name.toLowerCase().includes(ql)) return false;
            return true;
        });
        countEl.textContent = `[ ${filtered.length} / ${exercises.length} UNITS ]`;
        if (!filtered.length) {
            grid.innerHTML = `<div class="no-data col-span-full">[ NO MATCH ]</div>`;
            return;
        }
        grid.innerHTML = filtered.map(ex => `
            <article class="exercise-card" data-id="${ex.id}">
                <video src="${hudUtil.mediaUrl(ex.media_slug, 'mp4')}" autoplay loop muted playsinline
                    poster="${hudUtil.mediaUrl(ex.media_slug, 'gif')}"
                    onerror="this.replaceWith(Object.assign(document.createElement('img'),{src:'${hudUtil.mediaUrl(ex.media_slug,'gif')}',alt:'${ex.name}'}))">
                </video>
                <div class="body">
                    <h3>${ex.name}</h3>
                    <div class="flex justify-between items-center mt-1">
                        <span class="${hudUtil.muscleTagClass(ex.muscle_group)}">${ex.muscle_group}</span>
                        <span class="text-muted text-xs">${ex.id}</span>
                    </div>
                </div>
            </article>
        `).join('');
        grid.querySelectorAll('.exercise-card').forEach(card => {
            card.addEventListener('click', () => openDetail(card.dataset.id));
        });
    }

    async function openDetail(id) {
        const ex = exercises.find(e => e.id === id);
        if (!ex) return;
        let records = [];
        try { records = await api.exerciseRecords(id); } catch (e) { /* ignore */ }
        const cues = (ex.form_cues || []).map(c => `<li>${c}</li>`).join('');
        const prRow = records[0]
            ? `<div class="hud-label mt-2">[ CURRENT PR ]</div>
               <div class="hud-value text-green">${records[0].max_weight} KG · est-1RM ${Math.round(records[0].est_1rm)} KG <span class="text-muted text-sm">(${records[0].pr_date})</span></div>`
            : `<div class="no-data mt-2">[ NO PR LOGGED ]</div>`;
        hudModal.open(`
            <div class="hud-panel-header"><h2>// ${ex.name.toUpperCase()}</h2>
                <button class="hud-btn danger" onclick="hudModal.close()">[ X ]</button>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4">
                <video src="${hudUtil.mediaUrl(ex.media_slug, 'mp4')}" autoplay loop muted playsinline
                    style="width:100%; aspect-ratio:1/1; object-fit:cover; background:var(--bg); border:1px solid var(--border);"
                    onerror="this.replaceWith(Object.assign(document.createElement('img'),{src:'${hudUtil.mediaUrl(ex.media_slug,'gif')}',style:'width:100%;aspect-ratio:1/1;object-fit:cover;background:var(--bg);border:1px solid var(--border);'}))">
                </video>
                <div>
                    <div class="hud-label">[ MUSCLE GROUP ]</div>
                    <div class="hud-value"><span class="${hudUtil.muscleTagClass(ex.muscle_group)}">${ex.muscle_group}</span></div>
                    <div class="hud-label mt-2">[ FORM CUES ]</div>
                    <ul class="cues" style="color: var(--text);">${cues || '<li class="text-muted">no cues</li>'}</ul>
                    ${prRow}
                    <div class="mt-3">
                        <a href="/progress.html#${ex.id}" class="hud-btn">[ VIEW PROGRESS ]</a>
                    </div>
                </div>
            </div>
        `);
    }

    search.addEventListener('input', hudUtil.debounce(() => { q = search.value; renderGrid(); }, 150));

    try {
        exercises = await api.listExercises();
        renderChips();
        renderGrid();
    } catch (e) {
        grid.innerHTML = `<div class="no-data text-danger">[ FETCH FAILED: ${e.message} ]</div>`;
    }
})();
