# Gym Tracker — Mission Control HUD

A single-user, self-hostable gym-tracking web app with a NASA-style mission-control aesthetic.
FastAPI + SQLite backend, vanilla HTML/CSS/JS frontend served straight from the same FastAPI
process. **No npm, no node_modules, no build step.** Clone, `pip install`, run.

> Built for a personal homelab — log workouts on your phone at the gym, see your evolution
> on a dashboard at home, all behind your own Traefik / reverse proxy of choice.

```
[ SYSTEM_STATUS: NOMINAL ]   GYM-OPS // MISSION CONTROL   [ OPERATOR: HUGO ]
```

## Features

- **Exercise catalog** — 26 seeded exercises, autoplaying MP4 demo loops, filter by muscle
  group, full-text search, click for detail modal with form cues and current PR.
- **Session logger** — pick a training split (Chest-and-Biceps / Back-and-Triceps / Legs /
  Shoulders / Custom), exercise lineup pre-populated, per-set save, "last time you lifted
  this" chips, neon rest timer with Web Audio API beep on zero, PR-likely indicator on the fly.
- **Progress charts** — per-exercise time series for max weight, Brzycki est-1RM, and total
  volume per session. PR table below.
- **Dashboard HUD** — telemetry counters (total sessions, total volume, weekly cadence),
  weekly-volume trend line, muscle-distribution doughnut, recent PRs, recent sessions,
  resume-active-session CTA, ticking real-time UTC + local clocks.
- **Mission-control aesthetic** — dark theme, monospace typography, neon LEDs, panel chrome
  with corner ticks, status indicators, bracketed uppercase labels. Mobile-first responsive.
  A modular type scale (`--fs-2xs`…`--fs-2xl`, with `clamp()` hero numerics) drives a clear
  glance-first hierarchy; each page carries a real `<h1>` masthead.
- **Built for one-handed gym use** — every control meets a ≥44px tap target, inputs render at
  16px to suppress iOS zoom-on-focus, and notched phones get safe-area insets. The logger's
  set-row is an "instrument console": large tabular weight/reps inputs, an unmistakable
  full-width `[ LOG ]` action, and cyan-ready / green-logged status edges per set.
- **Accessible** — global `:focus-visible` ring, `prefers-reduced-motion` support, labeled
  inputs, and keyboard-operable catalog cards (`role=button`, Enter/Space to open).
- **PR engine** — Brzycki 1RM with reps clamped to [1, 36]; re-walks the per-exercise
  timeline on every set write and on session close to stamp new PRs (or invalidate them
  if you edit history downward).

## Tech stack

| Layer       | Choice                                                  | Why                                  |
|-------------|---------------------------------------------------------|--------------------------------------|
| Backend     | FastAPI + stdlib `sqlite3` + Pydantic                   | Minimal deps, fast, single binary    |
| Database    | SQLite (one file, foreign keys ON)                      | Single-user, zero admin              |
| Frontend    | Vanilla HTML5 / ES2020 / self-hosted CSS / Share Tech Mono | No build step, no Tailwind, fully static |
| Charts      | Chart.js (CDN)                                          | Canvas-based, fits the HUD theme     |
| Media       | Read-only volume mount of an exercise-GIF directory     | Works offline at the gym             |

## Quickstart — local Python

```bash
git clone <this-repo>
cd gym-tracker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed              # idempotent — safe to re-run
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open <http://localhost:8080/> on any device on your LAN.

OpenAPI / Swagger docs are auto-generated at `/docs`.

### Configuration (env vars)

| Var              | Default              | Effect                              |
|------------------|----------------------|-------------------------------------|
| `GYM_MEDIA_PATH` | `/media`             | Directory served at `/media/...`. The Docker image bakes the demo media in at this path; the bare `pip install` workflow falls back to `/home/hermes/Obsidian Vault/Gym/exercise-gifs` if the env var is unset. |
| `GYM_DB_PATH`    | `data/gym.db` (CWD)  | SQLite database file                |
| `PORT`           | `8080`               | uvicorn bind port (Docker entrypoint reads this) |

If `GYM_MEDIA_PATH` resolves to a missing directory, the app still boots — exercise pages
just show a placeholder instead of demo loops. The startup log line `[media] mounted /media -> <path>`
declares which path actually got mounted. **Bring your own GIFs/MP4s**: the catalog references
files by slug (e.g. `barbell-bench-press.gif` and `mp4/barbell-bench-press.mp4`).
A starter slug list is in `app/seed.py`.

## Quickstart — Docker (local / single host, no proxy)

```bash
docker compose up -d --build
```

The bundled `docker-compose.yml` builds the image from this repo and:

- Persists `./data` → `/app/data` (SQLite database file).
- Exposes port `8080` directly on the host.
- Serves the demo media from the `/media` layer **baked into the image at build time**
  (see `media/` in this repo). To override with a live host directory instead — for
  example to bind-mount your Obsidian vault — uncomment the volume in `docker-compose.yml`
  and edit the source path.

The image ships with a HEALTHCHECK that probes `/api/health` every 30 s.

## Production — Docker behind Traefik

For a homelab / production deployment behind Traefik with TLS, use
`docker-compose.traefik.yml`. It pulls the pre-built image from GHCR
(`ghcr.io/ukrawave/gym-tracker:latest`), attaches to the existing `proxy` network,
and adds Traefik labels for the `https` entrypoint with the `cloudflare` certresolver:

```bash
docker compose -f docker-compose.traefik.yml up -d
```

Prereqs on the host:

1. A Traefik instance already running on the `proxy` external Docker network with a
   `cloudflare` certresolver (DNS-01 wildcard `*.your-domain.com`).
2. DNS for `gym.<your-domain>.com` resolves to the host (CNAME to the wildcard works).
3. A persistent host directory for the SQLite DB. Default in the file:
   `/home/hugo/docker_volumes/gym-tracker/data/`.

Edit the `Host(...)` rule and the volume path to match your environment, then
deploy via `docker compose` or paste the file into a Portainer stack.

### Building & pushing your own image

If you'd rather build the image yourself instead of pulling `ghcr.io/ukrawave/...`,
fork the repo and replace the `media/` directory with your own demo GIFs/MP4s
(same `<slug>.gif` + `mp4/<slug>.mp4` layout — see `media/` for the reference set):

```bash
docker build -t ghcr.io/<you>/gym-tracker:latest .
docker push ghcr.io/<you>/gym-tracker:latest
```

Then edit `docker-compose.traefik.yml` to point at your image.

## REST API

| Method | Path                                  | Purpose                                       |
|--------|---------------------------------------|-----------------------------------------------|
| GET    | `/api/exercises`                      | All catalog exercises                         |
| GET    | `/api/exercises/{id}`                 | Single exercise (slug-id)                     |
| GET    | `/api/exercises/{id}/last`            | Sets from the most recent session             |
| GET    | `/api/exercises/{id}/history`         | Per-session history (weight / 1RM / volume)   |
| GET    | `/api/categories/{cat}/lineup`        | Default ordered exercise lineup for a split   |
| POST   | `/api/sessions`                       | Start a session                               |
| GET    | `/api/sessions`                       | Recent sessions (paginated via limit/offset)  |
| GET    | `/api/sessions/{id}`                  | Full session + nested sets                    |
| PUT    | `/api/sessions/{id}`                  | Update notes / end_time (triggers PR re-eval) |
| DELETE | `/api/sessions/{id}`                  | Cascade delete                                |
| POST   | `/api/sessions/{id}/sets`             | Add a set (triggers PR re-eval)               |
| PUT    | `/api/sets/{id}`                      | Update a set                                  |
| DELETE | `/api/sets/{id}`                      | Remove a set                                  |
| GET    | `/api/records`                        | All PRs, most recent first                    |
| GET    | `/api/records/exercise/{id}`          | PRs for one exercise                          |
| GET    | `/api/progress/exercise/{id}`         | Time series for charts                        |
| GET    | `/api/dashboard`                      | Aggregate telemetry for the home HUD          |
| GET    | `/api/health`                         | Liveness probe                                |

Invalid payloads return `HTTP 422` (Pydantic validation). Missing resources return `HTTP 404`.
Hard CHECK-constraint violations from SQLite are surfaced as `HTTP 400` from the sets endpoint.

## Database schema

`sqlite3` only — no ORM. Schema lives in `app/db.py` and is created on app startup. Foreign
keys are enabled. Tables: `exercises`, `sessions`, `set_entries`, `personal_records`. PRs
are re-evaluated by walking the per-exercise timeline in chronological order and stamping
every non-warmup set that beats the running max weight or max est-1RM (Brzycki).

### History retention rule

History keeps **only sessions that include exercise weights** — i.e. sessions with at least
one row in `set_entries`. Sessions that were started but abandoned before a single set was
logged are swept on every app boot by `app/cleanup.py` (idempotent) and excluded from the
`/api/sessions` list and the dashboard's `recent_sessions` / `total_sessions` /
`sessions_last_*` counters. The dashboard's `current_session` field still surfaces an
in-progress empty session so the user can resume it from the **RESUME** CTA.

Run the sweep manually:

```bash
python -m app.cleanup --dry-run    # show what would be deleted
python -m app.cleanup              # actually delete
```


## Frontend

Four pages, each loads `hud.js` (clock / LEDs / beeper / rest timer / modal) + `api.js`
(fetch wrappers) + its own controller:

- `static/index.html`     dashboard HUD       → `dashboard.js`
- `static/exercises.html` catalog grid        → `exercises.js`
- `static/logger.html`    session logger      → `logger.js`
- `static/progress.html`  per-exercise charts → `progress.js`

There is no CSS framework — `static/css/hud.css` is the single hand-written stylesheet that
owns everything: design tokens (color + a `--fs-*` type scale + spacing), layout primitives,
panel chrome, neon LEDs, timer ring, component states (`:focus-visible`, hover/active), and
HUD typography. All assets are served directly by FastAPI; no build step, no `node_modules`.

### Design tokens

```css
/* Identity colours */
--bg:        #0A0F14   /* deep space */
--panel:     #101820   /* technical panel */
--panel-2:   #14243B   /* hover / accent */
--border:    #1E293B   /* hairline */
--hud-green: #00FF66   /* online / PR / success */
--warn:      #FF9900   /* timer / warmup / pr-likely */
--danger:    #FF3333   /* failure / stop */
--info:      #00E5FF   /* primary metric */
--text:      #C7D2D0
--muted:     #8A9A86

/* Derived tints — same hues at low alpha for washes, hover, focus rings */
--info-dim:  rgba(0,229,255,.12)   --green-dim: rgba(0,255,102,.12)   /* …warn/danger-dim too */

/* Type scale — modular ramp (~1.25); hero numerics use clamp() */
--fs-2xs: .65rem  --fs-xs: .72rem  --fs-sm: .82rem  --fs-base: .95rem  --fs-md: 1.1rem
--fs-lg:  1.35rem  --fs-xl: clamp(1.6rem,1.2rem+2vw,2.1rem)  --fs-2xl: clamp(2rem,1.4rem+3.4vw,3rem)
```

Numbers, inputs, table cells use `JetBrains Mono`. Headers and labels use `Share Tech Mono`,
uppercase, wide letter-spacing. All button labels are bracketed: `[ END SESSION ]`,
`[ + ADD SET ]`, `[ STOP ]`.

## Repo layout

```
.
├── app/
│   ├── __init__.py
│   ├── db.py                    # sqlite3 helper + schema + Brzycki helper
│   ├── main.py                  # FastAPI app, static + media mounts
│   ├── seed.py                  # idempotent exercise catalog seeder
│   └── routes/
│       ├── __init__.py
│       ├── exercises.py
│       ├── sessions.py
│       ├── sets.py
│       ├── progress.py
│       └── records.py
├── static/
│   ├── index.html               # dashboard
│   ├── exercises.html
│   ├── logger.html
│   ├── progress.html
│   ├── css/hud.css
│   └── js/
│       ├── api.js               # fetch wrappers
│       ├── hud.js               # clock, LED, beeper, RestTimer, modal
│       ├── dashboard.js
│       ├── exercises.js
│       ├── logger.js
│       └── progress.js
├── data/.gitkeep                # SQLite lives here at runtime
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── verify.py                    # acceptance harness (urllib smoke tests)
├── LICENSE
└── README.md
```

## Smoke tests

After booting the app on port 8080:

```bash
# Health
curl -s http://localhost:8080/api/health

# Catalog count (expect 26)
curl -s http://localhost:8080/api/exercises | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"

# Default Legs lineup (expect 5 exercises, first is barbell-full-squat)
curl -s http://localhost:8080/api/categories/Legs/lineup | python3 -m json.tool | head -40

# Create + log + close a session round-trip
S=$(curl -s -X POST http://localhost:8080/api/sessions \
    -H 'Content-Type: application/json' \
    -d '{"category":"Chest-and-Biceps"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "session: $S"
curl -s -X POST "http://localhost:8080/api/sessions/$S/sets" \
    -H 'Content-Type: application/json' \
    -d '{"exercise_id":"barbell-bench-press","set_index":1,"weight":60,"reps":10,"entry_status":"Completed"}'
curl -s "http://localhost:8080/api/sessions/$S" | python3 -m json.tool
curl -s -X PUT "http://localhost:8080/api/sessions/$S" \
    -H 'Content-Type: application/json' \
    -d "{\"end_time\":\"$(date -Iseconds)\"}"
```

A more thorough harness is in `verify.py`: `python3 verify.py http://localhost:8080`.

## License

MIT — see `LICENSE`.

## Acknowledgements

Demo GIFs come from [FitnessProgramer](https://www.fitnessprogramer.com/). This is a personal
project, not professional fitness advice — if you have an injury or health condition, check
with a professional before training.
