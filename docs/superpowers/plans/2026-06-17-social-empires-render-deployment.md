# Social Emperors – Render.com Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the Social Emperors Flash game on Render.com free tier with PostgreSQL persistence, playable via Ruffle in modern browsers.

**Architecture:** Flask + Gunicorn on Render Web Service, PostgreSQL (free tier) for village saves via psycopg2 with JSONB columns. `sessions.py` persistence layer rewritten to use PostgreSQL instead of filesystem JSON, `command.py` and `engine.py` unchanged. Landing page offers Ruffle (primary) and FlashBrowser (fallback) paths.

**Tech Stack:** Python 3.x, Flask, Gunicorn, psycopg2, PostgreSQL (JSONB), Ruffle (WASM Flash emulator)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `requirements.txt` | Create | Python dependencies for Render build |
| `render.yaml` | Create | Render deployment blueprint |
| `db.py` | Create | PostgreSQL connection pool + query/execute helpers |
| `server.py` | Modify | ENV config, landing page, startup migration hook, Gunicorn compat |
| `sessions.py` | Modify | Replace filesystem I/O with PostgreSQL read/write (UPSERT) |

---

### Task 1: Clone Repository and Install Dependencies

**Files:**
- Clone: `https://github.com/AcidCaos/socialemperors.git`

- [ ] **Step 1: Clone the repo**

```bash
git clone https://github.com/AcidCaos/socialemperors.git D:/apps/socialgame
```

- [ ] **Step 2: Verify clone and explore structure**

```bash
ls D:/apps/socialgame/
```

Expected to see: `server.py`, `engine.py`, `command.py`, `sessions.py`, `templates/`, `mods/`, etc.

- [ ] **Step 3: Check Python version and create virtual environment**

```bash
python --version
cd D:/apps/socialgame
python -m venv venv
```

Expected: Python 3.8+ installed.

- [ ] **Step 4: Activate venv and install current dependencies (if any)**

```bash
source venv/Scripts/activate
pip list
```

Note what's already installed. The original project has no `requirements.txt` — we'll create it in Task 2.

---

### Task 2: Create requirements.txt

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1: Write requirements.txt**

```txt
flask==3.0.*
gunicorn==22.*
psycopg2-binary==2.9.*
```

Place at `D:/apps/socialgame/requirements.txt`.

- [ ] **Step 2: Install and verify**

```bash
pip install -r requirements.txt
python -c "import flask; import gunicorn; import psycopg2; print('All imports OK')"
```

Expected: `All imports OK` without errors.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add requirements.txt with flask, gunicorn, psycopg2"
```

---

### Task 3: Create db.py – PostgreSQL Connection Layer

**Files:**
- Create: `db.py`

- [ ] **Step 1: Write db.py**

```python
"""
PostgreSQL connection with connection pooling.
Reads DATABASE_URL from environment, falls back to local dev defaults.
Uses psycopg2 directly — no ORM needed since we store JSONB.
"""
import os
import json
from contextlib import contextmanager

from psycopg2 import pool


# Module-level pool (lazy init)
_pool = None


def _get_pool():
    """Get or create the connection pool. Singleton pattern."""
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL", "")
        if database_url:
            _pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=4,
                dsn=database_url,
            )
        else:
            # Local dev fallback
            _pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=4,
                host=os.environ.get("DB_HOST", "localhost"),
                port=int(os.environ.get("DB_PORT", "5432")),
                dbname=os.environ.get("DB_NAME", "social_emperors"),
                user=os.environ.get("DB_USER", "postgres"),
                password=os.environ.get("DB_PASSWORD", ""),
            )
    return _pool


def query(sql, params=None):
    """Run a SELECT query and return results as list of dicts.
    
    Args:
        sql: SQL query string with %s placeholders
        params: List of parameter values
        
    Returns:
        List of dicts, each dict is one row (column_name -> value).
        JSONB columns are already decoded to Python dicts.
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if cur.description is None:
                return []
            columns = [desc[0] for desc in cur.description]
            rows = []
            for row in cur.fetchall():
                d = {}
                for col, val in zip(columns, row):
                    # psycopg2 auto-decodes JSONB -> dict, but only if the value
                    # came from a JSONB column. If it's a plain string (text column
                    # that contains JSON), we decode it manually.
                    if isinstance(val, str) and (val.startswith('{') or val.startswith('[')):
                        try:
                            d[col] = json.loads(val)
                        except (json.JSONDecodeError, ValueError):
                            d[col] = val
                    else:
                        d[col] = val
                rows.append(d)
            return rows
    finally:
        p.putconn(conn)


def execute(sql, params=None):
    """Run an INSERT/UPDATE/DELETE and return affected row count.
    
    Args:
        sql: SQL query string with %s placeholders
        params: List of parameter values
        
    Returns:
        Number of rows affected.
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            conn.commit()
            return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def execute_many(sql, params_list):
    """Run executemany for batch INSERT/UPDATE.
    
    Args:
        sql: SQL query string with %s placeholders
        params_list: List of parameter lists
        
    Returns:
        Number of rows affected (sum across all executions).
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, params_list)
            conn.commit()
            return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def create_tables():
    """Create database tables if they don't exist. Idempotent."""
    execute("""
        CREATE TABLE IF NOT EXISTS player_saves (
            user_id     TEXT PRIMARY KEY,
            save_data   JSONB NOT NULL,
            created_at  TIMESTAMP DEFAULT NOW(),
            updated_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS static_villages (
            pid   TEXT PRIMARY KEY,
            data  JSONB NOT NULL
        )
    """)
```

- [ ] **Step 2: Verify local import**

```bash
python -c "from db import query, execute, create_tables; print('db.py imports OK')"
```

Expected: `db.py imports OK`. Note: won't connect to DB yet (no PostgreSQL running locally), but import should succeed.

- [ ] **Step 3: Commit**

```bash
git add db.py
git commit -m "feat: add db.py PostgreSQL connection layer with JSONB support"
```

---

### Task 4: Rewrite sessions.py – Filesystem → PostgreSQL

**Files:**
- Modify: `sessions.py`

First read the current file to understand exact content, then apply changes.

- [ ] **Step 1: Read current sessions.py**

Read `D:/apps/socialgame/sessions.py` fully to understand the current implementation.

- [ ] **Step 2: Add db import and replace load_saved_villages()**

At the top of `sessions.py`, add:
```python
from db import query, execute, create_tables
import json as _json_module
```

Replace `load_saved_villages()`:

```python
def load_saved_villages():
    """Load all villages from PostgreSQL into in-memory dicts.
    Also creates tables and migrates static villages from disk on first run.
    """
    global __saves, __villages
    __saves = {}
    __villages = {}

    create_tables()
    migrate_static_villages_from_disk()

    try:
        rows = query("SELECT user_id, save_data FROM player_saves")
        for row in rows:
            user_id = row["user_id"]
            save_data = row["save_data"]
            if isinstance(save_data, str):
                save_data = _json_module.loads(save_data)
            __saves[user_id] = save_data
            migrate_loaded_save(__saves[user_id])
    except Exception as e:
        print(f"[sessions] Player saves load failed (DB may not be ready): {e}")

    try:
        rows = query("SELECT pid, data FROM static_villages")
        for row in rows:
            data = row["data"]
            if isinstance(data, str):
                data = _json_module.loads(data)
            __villages[row["pid"]] = data
    except Exception as e:
        print(f"[sessions] Static villages load failed: {e}")
```

- [ ] **Step 3: Add migrate_static_villages_from_disk() function**

Add this new function to `sessions.py`:

```python
def migrate_static_villages_from_disk():
    """One-time migration: load static villages from JSON files into PostgreSQL.
    Idempotent — skips if static_villages table already has data.
    """
    try:
        count_rows = query("SELECT COUNT(*) AS cnt FROM static_villages")
        if count_rows and count_rows[0]["cnt"] > 0:
            return  # Already migrated
    except Exception:
        pass  # Table might not exist yet

    if not os.path.exists(VILLAGES_DIR):
        return

    for filename in os.listdir(VILLAGES_DIR):
        if not filename.endswith(".json") or filename == "initial.json":
            continue
        filepath = os.path.join(VILLAGES_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = _json_module.load(f)
            pid = data.get("playerInfo", {}).get("pid", filename.replace(".json", ""))
            execute(
                "INSERT INTO static_villages (pid, data) VALUES (%s, %s) "
                "ON CONFLICT (pid) DO NOTHING",
                [pid, _json_module.dumps(data)],
            )
        except Exception as e:
            print(f"[sessions] Failed to migrate {filename}: {e}")
```

- [ ] **Step 4: Replace save_session()**

Replace the file-based `save_session()` with PostgreSQL UPSERT:

```python
def save_session(USERID):
    """Save a player village to PostgreSQL via UPSERT."""
    if USERID not in __saves:
        print(f"[sessions] WARNING: save_session called for unknown USERID={USERID}")
        return
    data_json = _json_module.dumps(__saves[USERID])
    try:
        execute(
            "INSERT INTO player_saves (user_id, save_data, updated_at) "
            "VALUES (%s, %s, NOW()) ON CONFLICT (user_id) "
            "DO UPDATE SET save_data = EXCLUDED.save_data, "
            "updated_at = NOW()",
            [USERID, data_json],
        )
    except Exception as e:
        print(f"[sessions] Failed to save session for {USERID}: {e}")
```

- [ ] **Step 5: Replace new_village() persistence**

Find the part of `new_village()` that writes the initial save to disk (typically at the end of the function). Replace the file-write lines with:

```python
    # Save to PostgreSQL
    data_json = _json_module.dumps(__saves[USERID])
    execute(
        "INSERT INTO player_saves (user_id, save_data) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET save_data = EXCLUDED.save_data",
        [USERID, data_json],
    )
```

- [ ] **Step 6: Verify no remaining filesystem I/O in sessions.py**

Search `sessions.py` for any remaining `open(` calls or `os.path.join(SAVES_DIR` references that write/read JSON files. Reading `initial.json` (the village template) should remain file-based since it's static. Only save/load operations should be migrated.

- [ ] **Step 7: Commit**

```bash
git add sessions.py
git commit -m "feat: migrate sessions.py from filesystem JSON to PostgreSQL JSONB"
```

---

### Task 5: Update server.py – ENV Config + Landing Page + Gunicorn

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Read current server.py**

Read `D:/apps/socialgame/server.py` fully to understand the current implementation.

- [ ] **Step 2: Add ENV-based configuration**

At the top of `server.py`, after imports and `app = Flask(__name__)`:

```python
import os

# Use Render-provided secret key or a dev fallback
app.secret_key = os.environ.get("SECRET_KEY", "social-empires-dev-key-change-me")

# Database URL for PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Ensure sessions module loads villages on startup
# (called before first request in existing code — keep that pattern)
```

- [ ] **Step 3: Add landing page route**

Add a new route at `/` that replaces the current login page with a choice screen:

```python
import os as _os_module


@app.route("/")
def index():
    """Landing page: choose between Ruffle (modern browser) and FlashBrowser."""
    return """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Social Emperors</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }
        .box {
            background: #16213e;
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            max-width: 500px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.3);
        }
        h1 { margin-top: 0; color: #e94560; }
        .btn {
            display: block;
            margin: 16px auto;
            padding: 14px 32px;
            border-radius: 8px;
            text-decoration: none;
            font-size: 16px;
            font-weight: 600;
            transition: transform 0.1s, box-shadow 0.1s;
        }
        .btn:hover { transform: scale(1.03); }
        .btn-primary { background: #e94560; color: #fff; }
        .btn-secondary { background: #0f3460; color: #ccc; border: 1px solid #333; }
        .note { font-size: 13px; color: #888; margin-top: 24px; }
    </style>
</head>
<body>
    <div class="box">
        <h1>🔥 Social Emperors</h1>
        <p>Tarayıcında oyna — hiçbir şey indirmene gerek yok.</p>
        <a class="btn btn-primary" href="/ruffle.html">🎮 Tarayıcıda Oyna (Ruffle)</a>
        <a class="btn btn-secondary" href="/play.html">💾 FlashBrowser ile Oyna</a>
        <p class="note">
            ⚠️ Ruffle ile oynarken bazı özellikler çalışmayabilir.<br>
            Sorun yaşarsan FlashBrowser indirip ikinci seçeneği kullan.
        </p>
    </div>
</body>
</html>
"""
```

- [ ] **Step 4: Add startup migration call**

Find where the server initializes (usually near `if __name__ == "__main__"` or in a `before_first_request` hook). Add a call to create tables on startup. The simplest approach: add an import and call at module load time, right after the `sessions` import already in server.py.

In `server.py`, find the line that calls `load_saved_villages()` and ensure it stays. The `load_saved_villages()` function already calls `create_tables()` (added in Task 4), so the migration runs automatically.

- [ ] **Step 5: Ensure Gunicorn compatibility**

Find the `if __name__ == "__main__":` block at the bottom of `server.py`. It likely looks like:
```python
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
```

Wrap it so it only runs when executed directly (not under Gunicorn):
```python
if __name__ == "__main__":
    # Dev server only — Render uses Gunicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5050"))
    app.run(host=host, port=port, debug=False)
```

The Flask `app` object must be module-level (no changes needed — the existing code already has `app = Flask(__name__)` at the top).

- [ ] **Step 6: Verify the `app` variable name**

Gunicorn needs `server:app` — confirm `server.py` has `app = Flask(__name__)` at module level. If the variable is named differently, note it for `render.yaml` start command.

- [ ] **Step 7: Commit**

```bash
git add server.py
git commit -m "feat: add ENV config, landing page, Gunicorn compatibility"
```

---

### Task 6: Create render.yaml

**Files:**
- Create: `render.yaml`

- [ ] **Step 1: Write render.yaml**

```yaml
services:
  - type: web
    name: social-emperors
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
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

Place at `D:/apps/socialgame/render.yaml`.

The `--timeout 120` is important — some game requests (especially asset downloads from CDN fallback) can take longer than Gunicorn's default 30s.

- [ ] **Step 2: Commit**

```bash
git add render.yaml
git commit -m "chore: add render.yaml deployment config"
```

---

### Task 7: Create .gitignore and Prepare for GitHub Push

**Files:**
- Create/Modify: `.gitignore`

- [ ] **Step 1: Check if .gitignore exists**

```bash
cat D:/apps/socialgame/.gitignore 2>/dev/null || echo "No .gitignore found"
```

- [ ] **Step 2: Add/update .gitignore entries**

Ensure these entries exist in `.gitignore`:
```
# Python
__pycache__/
*.py[cod]
*.pyo
venv/
.env

# IDE
.vscode/
.idea/

# Game saves (local dev only — on Render these go to PostgreSQL)
SAVES_DIR/
*.save.json

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 3: Verify git remote**

```bash
cd D:/apps/socialgame
git remote -v
```

If the origin is still `https://github.com/AcidCaos/socialemperors`, we need to fork or create a new repo. For deployment, you push to YOUR GitHub account, then connect Render to that repo.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: update .gitignore for Render deployment"
```

---

### Task 8: Local PostgreSQL Setup and Integration Test

- [ ] **Step 1: Start local PostgreSQL (Docker)**

If Docker is available:
```bash
docker run -d --name social-emperors-pg \
    -e POSTGRES_PASSWORD=password \
    -e POSTGRES_DB=social_emperors \
    -p 5432:5432 \
    postgres:15-alpine
```

If Docker is not available, install PostgreSQL locally and create a database named `social_emperors`.

- [ ] **Step 2: Set environment variables for local test**

```bash
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=social_emperors
export DB_USER=postgres
export DB_PASSWORD=password
export SECRET_KEY=test-secret-key
```

- [ ] **Step 3: Start the Flask server locally**

```bash
cd D:/apps/socialgame
source venv/Scripts/activate
python server.py
```

Expected: Server starts on `http://127.0.0.1:5050/`.

- [ ] **Step 4: Test landing page**

Open `http://127.0.0.1:5050/` in a browser. Expected: landing page with two buttons.

- [ ] **Step 5: Test village creation**

Click "Tarayıcıda Oyna (Ruffle)" → Expected: `/ruffle.html` loads. Create a new village via `/new.html`. Verify the game screen appears.

- [ ] **Step 6: Test persistence**

Close the browser, reopen `http://127.0.0.1:5050/play.html`. Expected: village state loads from PostgreSQL (not from disk).

- [ ] **Step 7: Test restart persistence**

Stop the Flask server (Ctrl+C), restart it. Reopen the browser. Expected: village still persists (loaded from PostgreSQL, not filesystem).

- [ ] **Step 8: Verify PostgreSQL data directly**

```bash
docker exec -it social-emperors-pg psql -U postgres -d social_emperors -c "SELECT user_id, updated_at FROM player_saves;"
```

Expected: One or more rows with UUIDs and timestamps.

---

### Task 9: Push to GitHub and Deploy on Render

- [ ] **Step 1: Create a new GitHub repo for deployment**

Go to `https://github.com/new` and create a new repo (e.g., `social-emperors-render`). Do NOT fork — we want our own repo with the modified code.

- [ ] **Step 2: Update remote and push**

```bash
cd D:/apps/socialgame
git remote set-url origin https://github.com/YOUR_USERNAME/social-emperors-render.git
git branch -M main
git push -u origin main
```

- [ ] **Step 3: Connect Render to the repo**

1. Go to `https://dashboard.render.com`
2. Click "New +" → "Web Service"
3. Connect GitHub account if not already connected
4. Select the `social-emperors-render` repo
5. Render auto-detects `render.yaml` → click "Apply"
6. Wait for the first deploy (~3-5 minutes)

- [ ] **Step 4: Monitor deploy logs**

In Render dashboard → `social-emperors` → Logs tab. Watch for:
- `pip install` completing successfully
- `gunicorn` starting
- No import errors or missing module errors

If deploy fails, check the log for specific errors.

- [ ] **Step 5: Get the deploy URL**

Render assigns a URL like `https://social-emperors.onrender.com`. Note this URL.

---

### Task 10: Live Smoke Test on Render

- [ ] **Step 1: Test landing page**

Open `https://social-emperors.onrender.com/` in a modern browser. Expected: landing page with two buttons. First load may take 30-50 seconds (cold start from free tier sleep).

- [ ] **Step 2: Test Ruffle game load**

Click "Tarayıcıda Oyna (Ruffle)". Expected: Ruffle loads and the game SWF begins loading. Note any Ruffle compatibility warnings in the browser console.

- [ ] **Step 3: Test village creation and gameplay**

Create a new village. Perform basic actions:
- Place a building (buy)
- Collect resources
- Verify the action completes

- [ ] **Step 4: Test persistence**

Close browser completely. Reopen and go to `https://social-emperors.onrender.com/play.html`. Expected: village is still there with all progress.

- [ ] **Step 5: Test Render restart persistence**

In Render dashboard, click "Manual Deploy" → "Restart Service". Wait for restart. Reopen the game. Expected: village persists.

- [ ] **Step 6: Test FlashBrowser fallback (optional)**

If Ruffle has issues, test the `/play.html` route with FlashBrowser to confirm the fallback works.

---

### Task 11: Polish – UptimeRobot + Player Instructions

- [ ] **Step 1: Set up UptimeRobot (free tier)**

1. Go to `https://uptimerobot.com`
2. Create free account
3. Add new monitor:
   - Type: HTTP(s)
   - URL: `https://social-emperors.onrender.com/`
   - Monitoring interval: 5 minutes
4. This keeps the Render free tier from sleeping (5min ping < 15min sleep threshold)

- [ ] **Step 2: Write player instructions**

Create a short message for players (can be a simple text file or added to the landing page):

```
🔥 Social Emperors — Nasıl Bağlanılır?

1. Modern bir tarayıcı aç (Chrome/Firefox/Edge)
2. https://social-emperors.onrender.com adresine git
3. "Tarayıcıda Oyna (Ruffle)" butonuna tıkla
4. İlk yükleme biraz sürebilir (sunucu uyanıyor) — sabırlı ol :)

Sorun yaşarsan:
- Sayfayı yenile (F5)
- Hala çalışmazsa FlashBrowser indirip "FlashBrowser ile Oyna" seçeneğini kullan

Not: Oyun kayıtların sunucuda saklanır, tarayıcıyı kapatsan da kalır.
```

- [ ] **Step 3: Set PostgreSQL 90-day expiry reminder**

Create a calendar reminder or TODO for ~85 days from now: "Export Render PostgreSQL (social-emperors-db) and migrate to new DB before expiry."

Export command (for when the time comes):
```bash
# From Render dashboard → social-emperors-db → Connect → get connection string
pg_dump $RENDER_DATABASE_URL > social_emperors_backup_$(date +%Y%m%d).sql
```

---

## Execution Order

```
Task 1 (clone) → Task 2 (requirements) → Task 3 (db.py) → Task 4 (sessions.py)
                                                              ↓
Task 5 (server.py) ←──────────────────────────────────────────┘
     ↓
Task 6 (render.yaml) → Task 7 (gitignore) → Task 8 (local test)
                                                ↓
Task 9 (GitHub push + Render deploy) → Task 10 (live test) → Task 11 (polish)
```

Tasks 1-7 are code changes. Task 8 is local integration test. Tasks 9-11 are deployment and polish.
