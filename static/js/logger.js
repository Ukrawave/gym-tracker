// logger.js — session logger. Creates sessions, adds sets, drives rest timer.

(async () => {
    const $ = (id) => document.getElementById(id);
    const SPLITS = ['Chest-and-Biceps', 'Back-and-Triceps', 'Legs', 'Shoulders', 'Custom'];

    let session = null;            // current session row
    let lineup  = [];              // [{exercise, sets:[{set_index, weight, reps, status, savedId?}]}]
    let timer   = null;
    let exercisesCache = [];

    // --- split picker
    function renderPicker() {
        const wrap = $('split-buttons');
        wrap.innerHTML = SPLITS.map(s => `
            <button class="hud-btn" data-split="${s}">[ ${s.toUpperCase()} ]</button>
        `).join('');
        wrap.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => startSession(btn.dataset.split));
        });
    }

    async function loadActiveSession() {
        try {
            const dash = await api.dashboard();
            if (dash.current_session) {
                const full = await api.getSession(dash.current_session.id);
                session = full;
                hydrateLineupFromSession(full);
                showSession();
                return true;
            }
        } catch (e) { /* ignore */ }
        return false;
    }

    function hydrateLineupFromSession(full) {
        lineup = (full.exercises || []).map(ex => ({
            exercise: {
                id: ex.id, name: ex.name, muscle_group: ex.muscle_group,
                media_slug: ex.media_slug, form_cues: ex.form_cues,
            },
            sets: (ex.sets || []).map(s => ({
                set_index: s.set_index, weight: s.weight, reps: s.reps,
                status: s.entry_status, savedId: s.id,
            })),
        }));
    }

    async function startSession(category) {
        try {
            session = await api.createSession({ category });
            const lu = await api.categoryLineup(category);
            lineup = lu.map(ex => ({ exercise: ex, sets: [{ set_index: 1, weight: '', reps: '', status: 'Completed' }] }));
            showSession();
        } catch (e) { alert('Could not create session: ' + e.message); }
    }

    function showSession() {
        $('picker-panel').style.display = 'none';
        $('session-panel').style.display = '';
        $('active-category').textContent = ` · ${session.category.toUpperCase()}`;
        $('active-session-id').textContent = session.id;
        $('active-start').textContent = session.start_time;
        $('session-notes').value = session.notes || '';
        ensureTimer();
        populateAddExerciseSelect();
        renderLineup();
    }

    function ensureTimer() {
        if (!timer) timer = new RestTimer($('timer-root'));
    }

    async function populateAddExerciseSelect() {
        if (!exercisesCache.length) {
            try { exercisesCache = await api.listExercises(); } catch (e) { exercisesCache = []; }
        }
        const sel = $('add-exercise-select');
        sel.innerHTML = exercisesCache
            .map(e => `<option value="${e.id}">${e.name} · ${e.muscle_group}</option>`)
            .join('');
    }

    function renderLineup() {
        const wrap = $('lineup');
        if (!lineup.length) {
            wrap.innerHTML = `<div class="no-data">[ NO EXERCISES — ADD SOMETHING FROM THE RIGHT PANEL ]</div>`;
            return;
        }
        wrap.innerHTML = lineup.map((row, ridx) => renderExerciseRow(row, ridx)).join('');
        // wire up
        wrap.querySelectorAll('[data-action]').forEach(el => {
            el.addEventListener('click', (e) => onLineupAction(e, el));
        });
        // load last-sets chips
        lineup.forEach((row, ridx) => loadLastChips(row.exercise.id, ridx));
    }

    async function loadLastChips(exId, ridx) {
        try {
            const last = await api.lastSets(exId);
            const el = document.querySelector(`[data-last-chips="${ridx}"]`);
            if (!el) return;
            if (!last.length) {
                el.innerHTML = `<span class="text-muted text-xs uppercase-hud">[ NO HISTORY ]</span>`;
                return;
            }
            el.innerHTML = last.map(s => `
                <span class="chip">${s.weight}KG × ${s.reps}${s.entry_status === 'Warm-up' ? ' WU' : s.entry_status === 'Failure' ? ' F' : ''}</span>
            `).join('');
        } catch (e) { /* ignore */ }
    }

    function renderExerciseRow(row, ridx) {
        const ex = row.exercise;
        const cues = (ex.form_cues || []).slice(0, 2).map(c => `<li>${c}</li>`).join('');
        return `
        <div class="logger-exercise" data-ex-idx="${ridx}">
            <div>
                <video src="${hudUtil.mediaUrl(ex.media_slug, 'mp4')}" autoplay loop muted playsinline
                    onerror="this.replaceWith(Object.assign(document.createElement('img'),{src:'${hudUtil.mediaUrl(ex.media_slug,'gif')}',style:'width:100%;aspect-ratio:1/1;object-fit:cover;background:var(--bg);'}))">
                </video>
                <div class="mt-1">
                    <span class="${hudUtil.muscleTagClass(ex.muscle_group)}">${ex.muscle_group}</span>
                </div>
                <ul class="cues">${cues}</ul>
            </div>
            <div>
                <div class="flex justify-between items-center mb-1">
                    <h3 class="uppercase-hud text-info">${ex.name}</h3>
                    <button class="hud-btn danger" data-action="remove-exercise" data-ex-idx="${ridx}">[ X ]</button>
                </div>
                <div class="hud-label">[ LAST TIME ]</div>
                <div class="last-time-chips" data-last-chips="${ridx}">…</div>
                <div class="hud-label">[ SETS ]</div>
                <div data-sets="${ridx}">
                    ${row.sets.map((s, sidx) => renderSetRow(s, ridx, sidx)).join('')}
                </div>
                <div class="mt-2">
                    <button class="hud-btn" data-action="add-set" data-ex-idx="${ridx}">[ + ADD SET ]</button>
                </div>
            </div>
        </div>
        `;
    }

    function renderSetRow(s, ridx, sidx) {
        const saved = s.savedId ? `<span class="saved-badge">[ SAVED #${s.savedId} ]</span>`
                                : `<button class="hud-btn success" data-action="save-set" data-ex-idx="${ridx}" data-set-idx="${sidx}">[ SAVE ]</button>`;
        return `
        <div class="set-row" data-set-row="${ridx}-${sidx}">
            <div class="idx">${s.set_index}</div>
            <input class="hud-input" type="number" step="0.5" min="0" placeholder="KG"
                value="${s.weight !== '' && s.weight !== null && s.weight !== undefined ? s.weight : ''}"
                data-field="weight" data-ex-idx="${ridx}" data-set-idx="${sidx}"
                ${s.savedId ? 'disabled' : ''}/>
            <input class="hud-input" type="number" step="1" min="0" placeholder="REPS"
                value="${s.reps !== '' && s.reps !== null && s.reps !== undefined ? s.reps : ''}"
                data-field="reps" data-ex-idx="${ridx}" data-set-idx="${sidx}"
                ${s.savedId ? 'disabled' : ''}/>
            <select class="hud-select" data-field="status" data-ex-idx="${ridx}" data-set-idx="${sidx}"
                ${s.savedId ? 'disabled' : ''}>
                ${['Warm-up','Completed','Failure'].map(o =>
                    `<option value="${o}" ${o === s.status ? 'selected' : ''}>${o.toUpperCase()}</option>`).join('')}
            </select>
            <div>${saved}</div>
            ${s.savedId
              ? `<button class="hud-btn danger" data-action="delete-set" data-set-id="${s.savedId}" data-ex-idx="${ridx}" data-set-idx="${sidx}">[ DEL ]</button>`
              : `<button class="hud-btn danger" data-action="drop-row" data-ex-idx="${ridx}" data-set-idx="${sidx}">[ - ]</button>`}
        </div>
        `;
    }

    // wire input changes globally (delegation)
    document.body.addEventListener('input', (e) => {
        const t = e.target;
        if (!t.dataset || !t.dataset.field) return;
        const ridx = parseInt(t.dataset.exIdx, 10);
        const sidx = parseInt(t.dataset.setIdx, 10);
        const row = lineup[ridx];
        if (!row || !row.sets[sidx]) return;
        if (t.dataset.field === 'weight') row.sets[sidx].weight = t.value;
        if (t.dataset.field === 'reps')   row.sets[sidx].reps   = t.value;
    });
    document.body.addEventListener('change', (e) => {
        const t = e.target;
        if (!t.dataset || t.dataset.field !== 'status') return;
        const ridx = parseInt(t.dataset.exIdx, 10);
        const sidx = parseInt(t.dataset.setIdx, 10);
        if (lineup[ridx] && lineup[ridx].sets[sidx]) lineup[ridx].sets[sidx].status = t.value;
    });

    async function onLineupAction(e, el) {
        const action = el.dataset.action;
        const ridx = parseInt(el.dataset.exIdx, 10);
        const row = lineup[ridx];
        if (action === 'add-set') {
            const nextIdx = (row.sets[row.sets.length - 1]?.set_index || 0) + 1;
            row.sets.push({ set_index: nextIdx, weight: '', reps: '', status: 'Completed' });
            renderLineup();
            return;
        }
        if (action === 'drop-row') {
            const sidx = parseInt(el.dataset.setIdx, 10);
            row.sets.splice(sidx, 1);
            renderLineup();
            return;
        }
        if (action === 'save-set') {
            const sidx = parseInt(el.dataset.setIdx, 10);
            const s = row.sets[sidx];
            const w = parseFloat(s.weight);
            const r = parseInt(s.reps, 10);
            if (isNaN(w) || isNaN(r)) { alert('Need weight and reps'); return; }
            try {
                const saved = await api.addSet(session.id, {
                    exercise_id: row.exercise.id,
                    set_index: s.set_index,
                    weight: w, reps: r,
                    entry_status: s.status || 'Completed',
                });
                s.savedId = saved.id;
                if (window.hudAudio) window.hudAudio.tick();
                if (timer) timer.start(120);
                renderLineup();
            } catch (err) { alert('Save failed: ' + err.message); }
            return;
        }
        if (action === 'delete-set') {
            const sid = parseInt(el.dataset.setId, 10);
            const sidx = parseInt(el.dataset.setIdx, 10);
            if (!confirm(`Delete set #${sid}?`)) return;
            try {
                await api.deleteSet(sid);
                row.sets.splice(sidx, 1);
                renderLineup();
            } catch (err) { alert('Delete failed: ' + err.message); }
            return;
        }
        if (action === 'remove-exercise') {
            if (!confirm(`Remove ${row.exercise.name} from this session?`)) return;
            // delete any saved sets for this exercise
            for (const s of row.sets) if (s.savedId) {
                try { await api.deleteSet(s.savedId); } catch (e) { /* ignore */ }
            }
            lineup.splice(ridx, 1);
            renderLineup();
            return;
        }
    }

    $('end-session') && $('end-session').addEventListener('click', async () => {
        if (!session) return;
        const notes = $('session-notes').value;
        try {
            await api.updateSession(session.id, {
                end_time: new Date().toISOString(),
                notes,
            });
            if (window.hudAudio) window.hudAudio.sessionEnd();
            location.href = '/';
        } catch (e) { alert('End-session failed: ' + e.message); }
    });

    $('discard-session') && $('discard-session').addEventListener('click', async () => {
        if (!session) return;
        if (!confirm('Discard this session entirely?')) return;
        try {
            await api.deleteSession(session.id);
            location.href = '/';
        } catch (e) { alert('Discard failed: ' + e.message); }
    });

    $('add-exercise-btn') && $('add-exercise-btn').addEventListener('click', () => {
        const sel = $('add-exercise-select');
        const id = sel.value;
        const ex = exercisesCache.find(e => e.id === id);
        if (!ex) return;
        lineup.push({ exercise: ex, sets: [{ set_index: 1, weight: '', reps: '', status: 'Completed' }] });
        renderLineup();
    });

    renderPicker();
    const resumed = await loadActiveSession();
    if (!resumed) {
        $('picker-panel').style.display = '';
        $('session-panel').style.display = 'none';
    }
})();
