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
                <div class="flex gap-2 mt-2 flex-wrap">
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
        }
    };
})();
