# Social Emperors – Render.com Deployment Design

**Date:** 2026-06-17
**Status:** Awaiting user review
**Goal:** Deploy `socialemperors` (Social Empires Flash game) on Render.com free tier with PostgreSQL-backed persistence, playable via Ruffle emulator in modern browsers.

## Context

The [socialemperors](https://github.com/AcidCaos/socialemperors) repo is a preservation project for the Facebook Flash game *Social Empires*. It currently runs as a local Flask server on `127.0.0.1:5050`. This spec covers deploying it to Render.com for a small private group (3–5 players), using Ruffle (WebAssembly Flash emulator) to run in modern browsers with no extra software. Fallback to FlashBrowser if Ruffle proves incompatible.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  Browser (modern Chrome/Firefox/Safari)              │
│  → Ruffle (WASM Flash emulator)                      │
│  → /ruffle.html loads the game SWFs                  │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────────┐
│  Render.com Web Service (Flask + Gunicorn)           │
│  → All existing Flask endpoints (server.py)          │
│  → Jinja2 templates + static SWF assets              │
│  → Config via ENV (12-factor-app)                    │
└──────────────────────┬──────────────────────────────┘
                       │ psycopg2
                       ▼
┌─────────────────────────────────────────────────────┐
│  Render PostgreSQL (256MB free tier)                 │
│  → player_saves  (user_id TEXT PK, save_data JSONB)  │
│  → static_villages (pid TEXT PK, data JSONB)          │
└─────────────────────────────────────────────────────┘
```

Key design decisions:
- **psycopg2 directly** — no ORM. The codebase manipulates Python dicts; storing them as JSONB requires no changes to `command.py` or `engine.py`.
- **Gunicorn, 1 worker** — Render free tier has 512MB RAM. 1 worker + Flask + psycopg2 fits comfortably (~150-200MB).
- **No code changes to game logic** — only `server.py` (config) and `sessions.py` (persistence layer) are touched.

## Database Design

```sql
CREATE TABLE player_saves (
    user_id     TEXT PRIMARY KEY,
    save_data   JSONB NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE static_villages (
    pid     TEXT PRIMARY KEY,
    data    JSONB NOT NULL
);
```

- `player_saves` replaces the filesystem `SAVES_DIR/*.save.json` pattern. Each row is one player village.
- `static_villages` replaces `VILLAGES_DIR/*.json` static neighbor data. Populated once via startup migration, idempotent.
- JSONB is used so the dict-manipulation code in `command.py`/`engine.py` needs zero changes. `sessions.py` handles the json.loads/json.dumps at the boundary.

### Data Flow

```
Read:  session(USERID) → SELECT save_data FROM player_saves WHERE user_id=%s → dict
Write: save_session(USERID) → INSERT ... ON CONFLICT (user_id) DO UPDATE (UPSERT)
```

In-memory `__saves` and `__villages` dicts remain as a read-through cache (they are the game's working state). Writes are immediate (UPSERT on every `save_session` call, which fires after every command batch).

## Code Changes

### New Files

| File | Purpose |
|------|---------|
| `requirements.txt` | Flask, gunicorn, psycopg2-binary |
| `render.yaml` | Render deployment blueprint (web service + PostgreSQL DB) |
| `db.py` | PostgreSQL connection pool and helper functions (`query()`, `execute()`) |

### Modified Files

| File | Changes |
|------|---------|
| `server.py` | `SECRET_KEY` from env, `DATABASE_URL` from env, landing page (`/`) with Ruffle/FlashBrowser choice, call `migrate_from_disk_if_needed()` on startup, gunicorn compatibility |
| `sessions.py` | `load_saved_villages()` reads from PostgreSQL instead of disk JSON files. `save_session()` does UPSERT instead of file write. `new_village()` INSERTs into PostgreSQL. `migrate_loaded_save()` behavior unchanged. |

### sessions.py Change Detail

**Before:**
```python
def load_saved_villages():
    for filename in os.listdir(SAVES_DIR):
        with open(...) as f:
            __saves[user_id] = json.load(f)
```

**After:**
```python
def load_saved_villages():
    rows = db.query("SELECT user_id, save_data FROM player_saves")
    for row in rows:
        __saves[row['user_id']] = row['save_data']
    rows = db.query("SELECT pid, data FROM static_villages")
    for row in rows:
        __villages[row['pid']] = row['data']
```

**Before:**
```python
def save_session(USERID):
    with open(f"{SAVES_DIR}/{USERID}.save.json", "w") as f:
        json.dump(__saves[USERID], f, indent=4)
```

**After:**
```python
def save_session(USERID):
    data = json.dumps(__saves[USERID])
    db.execute(
        "INSERT INTO player_saves (user_id, save_data, updated_at) "
        "VALUES (%s, %s, NOW()) ON CONFLICT (user_id) "
        "DO UPDATE SET save_data = %s, updated_at = NOW()",
        [USERID, data, data]
    )
```

### Landing Page (`/`)

Simple HTML with two options:
- **"Tarayıcıda Oyna (Ruffle)"** → `/ruffle.html`
- **"FlashBrowser ile Oyna"** → instructions + `/play.html` link

## Deployment Configuration

### render.yaml

```yaml
services:
  - type: web
    name: social-emperors
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn server:app --bind 0.0.0.0:$PORT --workers 1
    envVars:
      - key: SECRET_KEY
        generateValue: true
      - key: DATABASE_URL
        fromDatabase:
          name: social-emperors-db
          property: connectionString
      - key: FLASH_ASSET_CDN
        value: https://default01.static.socialpointgames.com/static/socialempires/

databases:
  - name: social-emperors-db
    plan: free
```

### requirements.txt

```
flask==3.0.*
gunicorn==22.*
psycopg2-binary==2.9.*
```

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Ruffle doesn't fully support the game | Medium | Landing page offers both Ruffle and FlashBrowser paths. If Ruffle fails on specific features, players use FlashBrowser. |
| PostgreSQL 90-day expiry (free tier) | Certain | Export/import before day 85. Reminder set. |
| socialpointgames.com CDN goes down | Low-Medium | Existing fallback in `server.py` caches missing assets on first request. Pre-load all assets into repo as alternative. |
| Free tier 15min sleep on inactivity | Certain | First request wakes server (30-50s cold start). Inform players. Optionally set up UptimeRobot (free, 5min ping) to keep alive. |
| 1 Gunicorn worker bottleneck | Low | 3-5 players won't saturate. Gunicorn queues requests (default 2048). |
| Race condition on concurrent writes | Very Low | Single worker serializes requests. Plus player saves are per-user, not shared. |
| Hardcoded secret key in source | Fixed | `SECRET_KEY` generated by Render at deploy time, never in code. |

## Implementation Steps

1. **Local prep & test** (~20min) — `requirements.txt`, `db.py`, PostgreSQL setup, `sessions.py` DB wiring, local verification
2. **server.py updates** (~15min) — ENV-based config, landing page, Gunicorn compatibility
3. **Ruffle integration check** (~15min) — Verify `/ruffle.html` works, SWF serving, feature compatibility
4. **Deployment files** (~10min) — Final `render.yaml`, `.gitignore`, Dockerfile if needed
5. **Render deploy** (~15min) — Push to GitHub, connect repo, monitor first deploy
6. **Live test** (~20min) — Connect via Ruffle, create village, verify persistence across restarts
7. **Polish** (~15min) — UptimeRobot, player instructions, PostgreSQL expiry reminder

**Total estimate:** ~2 hours

### Dependency Chain

```
Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Step 6 → Step 7
```

All steps are sequential (they touch the same files).

## Success Criteria

- [ ] Player opens Render URL in modern browser, sees landing page
- [ ] Clicks "Ruffle ile Oyna" → game loads and is playable
- [ ] Creates a village, performs actions (buy, collect, move)
- [ ] Closes browser, reopens → village state is intact
- [ ] Render restart (via dashboard) → villages persist
- [ ] FlashBrowser fallback works if Ruffle fails
