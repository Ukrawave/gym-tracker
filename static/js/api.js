// api.js — thin fetch wrappers around the FastAPI backend.
// Single-user homelab app, no auth surface. Same-origin only.

const API_BASE = '/api';

async function request(method, path, body) {
    const init = {
        method,
        headers: { 'Accept': 'application/json' },
    };
    if (body !== undefined && body !== null) {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(body);
    }
    const res = await fetch(`${API_BASE}${path}`, init);
    if (res.status === 204) return null;
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
        const err = new Error(data?.detail || `HTTP ${res.status}`);
        err.status = res.status;
        err.body = data;
        throw err;
    }
    return data;
}

window.api = {
    listExercises:        ()                     => request('GET',  `/exercises`),
    getExercise:          (id)                   => request('GET',  `/exercises/${id}`),
    lastSets:             (id)                   => request('GET',  `/exercises/${id}/last`),
    exerciseHistory:      (id)                   => request('GET',  `/exercises/${id}/history`),
    categoryLineup:       (category)             => request('GET',  `/categories/${encodeURIComponent(category)}/lineup`),

    createSession:        (body)                 => request('POST', `/sessions`, body),
    listSessions:         ()                     => request('GET',  `/sessions`),
    getSession:           (id)                   => request('GET',  `/sessions/${id}`),
    updateSession:        (id, body)             => request('PUT',  `/sessions/${id}`, body),
    deleteSession:        (id)                   => request('DELETE', `/sessions/${id}`),

    addSet:               (sessionId, body)      => request('POST', `/sessions/${sessionId}/sets`, body),
    updateSet:            (id, body)             => request('PUT',  `/sets/${id}`, body),
    deleteSet:            (id)                   => request('DELETE', `/sets/${id}`),

    listRecords:          ()                     => request('GET',  `/records`),
    exerciseRecords:      (id)                   => request('GET',  `/records/exercise/${id}`),

    progressForExercise:  (id)                   => request('GET',  `/progress/exercise/${id}`),
    dashboard:            ()                     => request('GET',  `/dashboard`),

    // Phase 1 — fitness dashboard (Garmin + Strava), read-only.
    syncStatus:           ()                     => request('GET',  `/sync/status`),
    fitnessOverview:      ()                     => request('GET',  `/fitness/overview`),
    fitnessRunning:       ()                     => request('GET',  `/fitness/running`),
    fitnessTraining:      ()                     => request('GET',  `/fitness/training`),
    fitnessSleep:         ()                     => request('GET',  `/fitness/sleep`),

    // Phase 2 — The Plan (24-week glide-path). First write endpoints beyond
    // the gym logger: config + manual weigh-in log.
    getPlan:              ()                     => request('GET',    `/plan`),
    savePlanConfig:       (body)                 => request('POST',   `/plan/config`, body),
    logWeight:            (body)                 => request('POST',   `/plan/weight`, body),
    deleteWeight:         (date)                 => request('DELETE', `/plan/weight/${encodeURIComponent(date)}`),

    // Phase 3 — Nutrition. Manual intake vs user-set targets; calories-OUT is
    // read server-side from already-synced Garmin wellness (no food sync).
    getNutrition:         ()                     => request('GET',    `/nutrition`),
    saveNutritionTargets: (body)                 => request('POST',   `/nutrition/targets`, body),
    logNutrition:         (body)                 => request('POST',   `/nutrition/log`, body),
    deleteNutrition:      (date)                 => request('DELETE', `/nutrition/log/${encodeURIComponent(date)}`),
};
