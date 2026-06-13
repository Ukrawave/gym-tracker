// hud.js — shared HUD widgets: clock, status LED, beeper, rest timer, modal helpers.

(function () {
    // ---- Clock ----
    function pad(n) { return String(n).padStart(2, '0'); }
    function tickClock() {
        const utcEl = document.getElementById('clock-utc');
        const locEl = document.getElementById('clock-local');
        if (!utcEl && !locEl) return;
        const now = new Date();
        if (utcEl) utcEl.textContent =
            `${now.getUTCFullYear()}-${pad(now.getUTCMonth()+1)}-${pad(now.getUTCDate())}T${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())}Z`;
        if (locEl) locEl.textContent =
            `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())} LOCAL`;
    }
    setInterval(tickClock, 1000);
    document.addEventListener('DOMContentLoaded', tickClock);

    // ---- Health / DB status LED ----
    async function pingHealth() {
        const led = document.getElementById('db-led');
        const txt = document.getElementById('db-status-text');
        if (!led) return;
        try {
            const res = await fetch('/api/health');
            if (res.ok) {
                led.className = 'led led-green led-pulse';
                if (txt) txt.textContent = 'DB ONLINE';
            } else {
                led.className = 'led led-amber';
                if (txt) txt.textContent = `DB DEGRADED ${res.status}`;
            }
        } catch (e) {
            led.className = 'led led-red';
            if (txt) txt.textContent = 'DB OFFLINE';
        }
    }
    document.addEventListener('DOMContentLoaded', pingHealth);
    setInterval(pingHealth, 15000);

    // ---- Highlight current nav item ----
    document.addEventListener('DOMContentLoaded', () => {
        const path = location.pathname;
        document.querySelectorAll('.hud-topbar nav a').forEach(a => {
            const href = a.getAttribute('href');
            if ((path === '/' || path.endsWith('/index.html')) && href === '/') a.classList.add('active');
            else if (href !== '/' && path.includes(href)) a.classList.add('active');
        });
    });

    // ---- Web Audio API beeper ----
    let _audioCtx = null;
    function ctx() {
        if (!_audioCtx) {
            try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
            catch (e) { return null; }
        }
        if (_audioCtx && _audioCtx.state === 'suspended') _audioCtx.resume();
        return _audioCtx;
    }
    function playBeep(freq = 440, durationMs = 120, type = 'sine', gain = 0.08) {
        const c = ctx();
        if (!c) return;
        const osc = c.createOscillator();
        const g   = c.createGain();
        osc.type = type;
        osc.frequency.value = freq;
        g.gain.setValueAtTime(gain, c.currentTime);
        g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + durationMs/1000);
        osc.connect(g); g.connect(c.destination);
        osc.start();
        osc.stop(c.currentTime + durationMs/1000);
    }
    window.hudAudio = {
        tick: () => playBeep(880, 60, 'square', 0.06),
        timerDone: () => {
            playBeep(660, 120);
            setTimeout(() => playBeep(660, 120), 160);
            setTimeout(() => playBeep(880, 200), 320);
        },
        sessionEnd: () => {
            playBeep(880, 180);
            setTimeout(() => playBeep(440, 280), 200);
        },
    };

    // ---- Rest timer ----
    class RestTimer {
        constructor(rootEl) {
            this.root = rootEl;
            this.seconds = 0;
            this.target  = 0;
            this.timerId = null;
            this.render();
        }
        render() {
            this.root.innerHTML = `
                <div class="timer-ring" id="timer-ring">
                    <div class="seconds" id="timer-seconds">00:00</div>
                    <div class="label">REST</div>
                </div>
                <div class="row-tight" style="margin-top: 0.75rem; justify-content: center;">
                    <button class="hud-btn" data-preset="60">[ 60s ]</button>
                    <button class="hud-btn" data-preset="90">[ 90s ]</button>
                    <button class="hud-btn warn" data-preset="120">[ 120s ]</button>
                    <button class="hud-btn" data-preset="180">[ 180s ]</button>
                    <button class="hud-btn danger" data-action="stop">[ STOP ]</button>
                </div>
            `;
            this.root.querySelectorAll('[data-preset]').forEach(btn => {
                btn.addEventListener('click', () => this.start(parseInt(btn.dataset.preset, 10)));
            });
            this.root.querySelector('[data-action="stop"]').addEventListener('click', () => this.stop());
        }
        format(s) {
            const m = Math.floor(s / 60);
            const sec = s % 60;
            return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
        }
        update() {
            const el = this.root.querySelector('#timer-seconds');
            if (el) el.textContent = this.format(this.seconds);
        }
        start(seconds) {
            this.stop();
            this.seconds = seconds;
            this.target  = seconds;
            this.root.querySelector('#timer-ring').classList.add('running');
            this.update();
            this.timerId = setInterval(() => {
                this.seconds -= 1;
                if (this.seconds <= 0) {
                    this.seconds = 0;
                    this.update();
                    this.stop();
                    if (window.hudAudio) window.hudAudio.timerDone();
                    return;
                }
                this.update();
            }, 1000);
        }
        stop() {
            if (this.timerId) clearInterval(this.timerId);
            this.timerId = null;
            const ring = this.root.querySelector('#timer-ring');
            if (ring) ring.classList.remove('running');
        }
    }
    window.RestTimer = RestTimer;

    // ---- Modal helpers ----
    window.hudModal = {
        open(html) {
            this.close();
            const wrap = document.createElement('div');
            wrap.className = 'hud-modal-backdrop';
            wrap.id = 'hud-modal-root';
            wrap.innerHTML = `<div class="hud-modal">${html}</div>`;
            wrap.addEventListener('click', (e) => { if (e.target === wrap) this.close(); });
            document.body.appendChild(wrap);
        },
        close() {
            const el = document.getElementById('hud-modal-root');
            if (el) el.remove();
        }
    };

    // ---- Common helpers ----
    window.hudUtil = {
        muscleTagClass(group) {
            if (!group) return 'tag';
            return `tag ${group.toLowerCase()}`;
        },
        formatDate(s) { return s || '—'; },
        formatVolume(v) { return `${Math.round(Number(v) || 0).toLocaleString()} KG`; },
        formatNumber(v) { return Number(v || 0).toLocaleString(); },
        debounce(fn, ms = 250) {
            let id;
            return (...args) => { clearTimeout(id); id = setTimeout(() => fn(...args), ms); };
        },
        mediaUrl(slug, kind = 'mp4') {
            if (kind === 'mp4') return `/media/mp4/${slug}.mp4`;
            return `/media/${slug}.gif`;
        },
        // Escape a user/data-supplied string for safe insertion into an
        // HTML *attribute* value (e.g. alt="...", title="...", data-*=...).
        // Use this any time you template-literal a string that came from
        // the API into innerHTML, since the API today happens to be
        // controlled by the same single user but exercises[].name is the
        // kind of field that grows untrusted sources over time (imports,
        // YAML edits, copy-paste). Cheaper than auditing every caller.
        attrEscape(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },
        // Delegated <video> -> <img> fallback for /media/mp4/*.mp4 -> /media/*.gif.
        // Wire it once per container instead of stamping inline `onerror=`
        // attributes that interpolate user data into HTML (XSS surface).
        //
        // Usage:
        //   <video data-fallback-slug="${slug}" data-fallback-alt="${name}" ...></video>
        //   hudUtil.attachVideoFallback(container);
        //
        // The handler fires on the capture phase because <video> 'error'
        // events do not bubble in most browsers.
        attachVideoFallback(container) {
            if (!container || container.__hudFallbackWired) return;
            container.__hudFallbackWired = true;
            container.addEventListener('error', (ev) => {
                const v = ev.target;
                if (!v || v.tagName !== 'VIDEO') return;
                const slug = v.dataset.fallbackSlug;
                if (!slug) return;
                const alt = v.dataset.fallbackAlt || '';
                const cls = v.dataset.fallbackClass || '';
                const img = document.createElement('img');
                img.src = this.mediaUrl(slug, 'gif');
                img.alt = alt;
                if (cls) img.className = cls;
                v.replaceWith(img);
            }, /* useCapture */ true);
        },
        // Pretty-print server timestamps as local clock for humans.
        // Accepts ISO strings ('2026-06-13T11:16:36+00:00' or naïve
        // '2026-06-13T11:16:36'). Returns 'HH:MM // YYYY-MM-DD'.
        // Falls back to the raw value if it can't parse.
        formatTimestamp(s) {
            if (!s) return '—';
            const raw = String(s);
            // sqlite CURRENT_TIMESTAMP is naïve UTC; tag with Z so the Date
            // constructor treats it as UTC instead of local-time-as-UTC.
            const parsed = new Date(/[zZ]|[+\-]\d{2}:?\d{2}$/.test(raw) ? raw : raw + 'Z');
            if (Number.isNaN(parsed.getTime())) return raw;
            const pad = n => String(n).padStart(2, '0');
            const date = `${parsed.getFullYear()}-${pad(parsed.getMonth()+1)}-${pad(parsed.getDate())}`;
            const time = `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
            return `${time} // ${date}`;
        },
    };

    // ---- HUD-styled alert/confirm (replaces native browser dialogs) ----
    // Returns a Promise<boolean> for confirm; alert resolves to true.
    function hudDialog({ title, body, kind = 'info', confirmText = 'OK', cancelText = null }) {
        return new Promise(resolve => {
            const accent = kind === 'danger' ? 'danger' : kind === 'warn' ? 'warn' : 'info';
            const html = `
                <div class="hud-panel-header">
                    <h2 style="color: var(--${accent === 'info' ? 'info' : accent});">${title}</h2>
                    <span class="led led-${accent === 'info' ? 'cyan' : accent === 'danger' ? 'red' : 'amber'} led-pulse"></span>
                </div>
                <div class="hud-value" style="font-size: 1rem; white-space: pre-wrap;">${body}</div>
                <div class="row-tight" style="margin-top: 1rem; justify-content: flex-end;">
                    ${cancelText ? `<button class="hud-btn" data-dlg-action="cancel">[ ${cancelText.toUpperCase()} ]</button>` : ''}
                    <button class="hud-btn ${accent}" data-dlg-action="confirm">[ ${confirmText.toUpperCase()} ]</button>
                </div>
            `;
            window.hudModal.open(html);
            const root = document.getElementById('hud-modal-root');
            const finish = (val) => { window.hudModal.close(); resolve(val); };
            root.querySelector('[data-dlg-action="confirm"]').addEventListener('click', () => finish(true));
            const cancelBtn = root.querySelector('[data-dlg-action="cancel"]');
            if (cancelBtn) cancelBtn.addEventListener('click', () => finish(false));
            // Backdrop click = cancel (or OK if alert-only)
            root.addEventListener('click', (e) => {
                if (e.target === root) finish(cancelText ? false : true);
            });
            // Esc to cancel
            const onKey = (e) => {
                if (e.key === 'Escape') { document.removeEventListener('keydown', onKey); finish(cancelText ? false : true); }
                else if (e.key === 'Enter') { document.removeEventListener('keydown', onKey); finish(true); }
            };
            document.addEventListener('keydown', onKey);
        });
    }
    window.hudAlert = (body, opts = {}) =>
        hudDialog({ title: opts.title || 'NOTICE', body, kind: opts.kind || 'info', confirmText: 'ACK' });
    window.hudConfirm = (body, opts = {}) =>
        hudDialog({
            title: opts.title || 'CONFIRM',
            body,
            kind: opts.kind || 'warn',
            confirmText: opts.confirmText || 'PROCEED',
            cancelText: opts.cancelText || 'ABORT',
        });
})();
