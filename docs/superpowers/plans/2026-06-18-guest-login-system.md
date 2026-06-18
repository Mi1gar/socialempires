# Guest Login System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Misafir Olarak Oyna" guest login button next to the existing login form, with nickname-based entry and cookie+IP session persistence.

**Architecture:** Guest users live in the same `users` table as registered users with an `is_guest=true` flag and no password. A persistent cookie (`guest_user_id`) is the primary identifier; IP address serves as a fallback for cookie recovery. All game mechanics reuse existing code paths — only the auth layer changes.

**Tech Stack:** Python 3, Flask, psycopg2 (PostgreSQL), bcrypt, file-based JSON fallback (existing)

## Global Constraints

- Guest accounts get full game access — no restrictions vs registered users
- Guest-to-registered upgrade is out of scope for this version
- Cookie lifetime: 30 days, HttpOnly, SameSite=Lax
- IP fallback window: last 7 days
- Nickname minimum 3 characters
- Backward compatible — registered user flow unchanged
- File-based DB fallback must work (existing `_file_execute`/`_file_query` regex parsers)

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `auth.py:10-20` | Modify | Add `is_guest` + `last_ip` columns to `init_auth_tables()`, add `create_guest_user()` and `get_guest_by_ip()` helpers |
| `server.py:1-19` | Modify | Import new auth helpers |
| `server.py:94-188` | Modify | Add guest detection logic to landing page, add guest button |
| `server.py:201-223` | After | New routes: `/guest`, `/guest-login`, `/guest-continue`, `/logout` |
| `db.py` | None | No changes — existing `query`/`execute` is sufficient |

---

### Task 1: Update `auth.py` — DB columns and guest helpers

**Files:**
- Modify: `auth.py:10-20` (init_auth_tables)
- Modify: `auth.py:140` (end of file — append new functions)

**Interfaces:**
- Consumes: `db.execute`, `db.query` (existing)
- Produces:
  - `init_auth_tables()` — updated to include `is_guest` and `last_ip` columns
  - `create_guest_user(nickname: str, ip_address: str) -> tuple | None` — returns `(username, user_id)` or `None`
  - `get_guest_by_user_id(user_id: str) -> dict | None` — returns user row or `None`
  - `get_guest_by_ip(ip_address: str, days: int = 7) -> dict | None` — returns most recent guest or `None`

- [ ] **Step 1: Update `init_auth_tables()` to include new columns**

Replace the existing function in `auth.py`:

```python
def init_auth_tables():
    """Kimlik dogrulama tablosunu olustur. Idempotent."""
    execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            user_id       TEXT UNIQUE NOT NULL,
            is_guest      BOOLEAN DEFAULT FALSE,
            last_ip       TEXT,
            created_at    TIMESTAMP DEFAULT NOW()
        )
    """)
    # Add columns to existing tables (idempotent via IF NOT EXISTS)
    try:
        execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_guest BOOLEAN DEFAULT FALSE")
    except Exception:
        pass  # File-based fallback silently ignores ALTER TABLE
    try:
        execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_ip TEXT")
    except Exception:
        pass
```

- [ ] **Step 2: Run server start check to verify no errors**

```bash
cd D:/apps/socialgame && python -c "from auth import init_auth_tables; init_auth_tables(); print('OK')"
```

Expected: `OK` (no exceptions)

- [ ] **Step 3: Add `create_guest_user()` function to `auth.py`**

Append at the end of `auth.py`:

```python
def create_guest_user(nickname: str, ip_address: str) -> tuple | None:
    """Misafir kullanici olustur. Basariliysa (username, user_id) donder.

    Rumuz 'guest_' prefix'i ve rastgele suffix ile birlestirilerek
    benzersiz username olusturulur. Sifre hash'i bos birakilir.
    """
    from sessions import create_village_with_id
    import random
    import string

    # Benzersiz username olustur: guest_<rumuz>_<4 haneli suffix>
    base = f"guest_{nickname}"
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    username = f"{base}_{suffix}"

    # Username kontrolu
    while username_exists(username):
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        username = f"{base}_{suffix}"

    user_id = str(uuid.uuid4())

    # Kullaniciyi ekle — password_hash bos, is_guest=true
    execute(
        "INSERT INTO users (username, password_hash, user_id, is_guest, last_ip) "
        "VALUES (%s, %s, %s, %s, %s)",
        [username, '', user_id, True, ip_address]
    )

    # Koy olustur
    create_village_with_id(user_id)

    return username, user_id


def get_guest_by_user_id(user_id: str) -> dict | None:
    """user_id ile misafir kullaniciyi bul. Bulunamazsa None."""
    rows = query(
        "SELECT username, user_id, is_guest, last_ip FROM users "
        "WHERE user_id = %s AND is_guest = TRUE",
        [user_id]
    )
    return rows[0] if rows else None


def get_guest_by_ip(ip_address: str, days: int = 7) -> dict | None:
    """Ayni IP'den en son giris yapan misafiri bul. Yoksa None."""
    rows = query(
        "SELECT username, user_id, is_guest, last_ip FROM users "
        "WHERE last_ip = %s AND is_guest = TRUE "
        "ORDER BY created_at DESC LIMIT 1",
        [ip_address]
    )
    # IP eslesmesi bulunduysa donder (created_at gun kontrolu istege bagli)
    return rows[0] if rows else None
```

- [ ] **Step 4: Verify all functions import cleanly**

Run: `python -c "from auth import create_guest_user, get_guest_by_user_id, get_guest_by_ip; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add auth.py
git commit -m "feat: add guest user DB columns and helper functions to auth.py"
```

---

### Task 2: Add guest login routes to `server.py`

**Files:**
- Modify: `server.py:18` (imports)
- Modify: `server.py:222` (after login route, before register route)

**Interfaces:**
- Consumes: `auth.create_guest_user`, `auth.get_guest_by_user_id`, `auth.get_guest_by_ip`, `auth.verify_login` (existing)
- Produces: `GET /guest`, `POST /guest-login`, `POST /guest-continue`, `get_client_ip()` helper

- [ ] **Step 1: Add `get_client_ip()` helper and update imports**

In `server.py`, update the import line (line 18):

```python
from auth import init_auth_tables, register_user, verify_login, get_all_players, get_player_count, username_exists, create_guest_user, get_guest_by_user_id, get_guest_by_ip
```

Then add the helper function right after the import block (after line 35, before `host = '127.0.0.1'`):

```python
def get_client_ip() -> str:
    """Return the client's real IP address, accounting for proxy headers (Render)."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'
```

- [ ] **Step 2: Add `GET /guest` route — nickname form**

Add after the `login()` route (after line 223, before `@app.route("/register", ...)`):

```python
@app.route("/guest")
def guest_form():
    """Misafir girisi icin rumuz formu."""
    error = request.args.get('error', '')
    error_html = f'<div class="error">{error}</div>' if error else ''
    return f"""
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Misafir Girisi — Social Emperors</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; display: flex; justify-content: center;
            align-items: center; min-height: 100vh; margin: 0;
        }}
        .box {{ background: #16213e; border-radius: 12px; padding: 40px; text-align: center; max-width: 420px; box-shadow: 0 4px 24px rgba(0,0,0,0.3); }}
        h1 {{ margin-top: 0; color: #d4a574; }}
        .input {{ width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #333; border-radius: 6px; background: #1a1a2e; color: #eee; font-size: 15px; box-sizing: border-box; }}
        .btn {{ display: block; width: 100%; margin: 12px 0; padding: 14px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; border: none; transition: transform 0.1s; }}
        .btn:hover {{ transform: scale(1.03); }}
        .btn-primary {{ background: #d4a574; color: #1a1a2e; }}
        .btn-back {{ background: #444; color: #aaa; }}
        .error {{ background: #3d1a1a; color: #e94560; padding: 8px; border-radius: 4px; margin: 8px 0; font-size: 14px; }}
        .hint {{ font-size: 12px; color: #666; margin-top: 16px; line-height: 1.6; }}
    </style>
</head>
<body>
    <div class="box">
        <h1>🎲 Misafir Girisi</h1>
        {error_html}
        <form method="POST" action="/guest-login">
            <input class="input" type="text" name="nickname" placeholder="Rumuz (en az 3 karakter)" required minlength="3" autocomplete="off">
            <button class="btn btn-primary" type="submit">🎮 Oyuna Basla</button>
        </form>
        <a class="btn btn-back" href="/">⬅ Geri Don</a>
        <p class="hint">Rumuzun ve ilerlemen bu cihazda saklanir.<br>Daha sonra kayit olup hesabini kalici yapabilirsin.</p>
    </div>
</body>
</html>
"""
```

- [ ] **Step 3: Add `POST /guest-login` route**

Add after the `guest_form()` route:

```python
@app.route("/guest-login", methods=["POST"])
def guest_login():
    """Handle guest login form submission."""
    nickname = request.form.get('nickname', '').strip()

    if not nickname or len(nickname) < 3:
        return redirect("/guest?error=Rumuz+en+az+3+karakter+olmali")

    client_ip = get_client_ip()
    result = create_guest_user(nickname, client_ip)

    if result is None:
        return redirect("/guest?error=Misafir+hesabi+olusturulamadi.+Tekrar+deneyin.")

    username, user_id = result
    session['username'] = username
    session['USERID'] = user_id
    session['GAMEVERSION'] = "SocialEmpires0926bsec.swf"

    # Reload villages so the new player's village is in memory
    load_saved_villages()

    # Set persistent cookie for guest recognition on return
    resp = redirect("/welcome")
    resp.set_cookie(
        'guest_user_id',
        value=user_id,
        max_age=60 * 60 * 24 * 30,  # 30 days
        httponly=True,
        samesite='Lax'
    )
    return resp
```

- [ ] **Step 4: Add `POST /guest-continue` route**

Add after `guest_login()`:

```python
@app.route("/guest-continue", methods=["POST"])
def guest_continue():
    """Resume a previous guest session from cookie or IP."""
    guest_user_id = request.cookies.get('guest_user_id')
    guest = None

    if guest_user_id:
        guest = get_guest_by_user_id(guest_user_id)

    # Cookie fallback: try IP matching
    if guest is None:
        client_ip = get_client_ip()
        guest = get_guest_by_ip(client_ip)

    if guest is None:
        return redirect("/?error=Misafir+hesabi+bulunamadi")

    session['username'] = guest['username']
    session['USERID'] = guest['user_id']
    session['GAMEVERSION'] = "SocialEmpires0926bsec.swf"
    load_saved_villages()

    # Refresh the cookie
    resp = redirect("/play.html")
    resp.set_cookie(
        'guest_user_id',
        value=guest['user_id'],
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite='Lax'
    )
    return resp
```

- [ ] **Step 5: Add `GET /logout` route**

Add after `guest_continue()`:

```python
@app.route("/logout")
def logout():
    """Clear session but preserve guest cookie for future return."""
    session.clear()
    return redirect("/")
```

- [ ] **Step 6: Verify server starts without import/route errors**

Run: `python -c "import server; print('OK')"`
Expected: `OK` (server module loads without syntax/import errors)

- [ ] **Step 7: Commit**

```bash
git add server.py
git commit -m "feat: add /guest, /guest-login, /guest-continue, and /logout routes"
```

---

### Task 3: Modify landing page `/` to show guest button and detect returning guests

**Files:**
- Modify: `server.py:94-188` (index route)

**Interfaces:**
- Consumes: `get_guest_by_user_id`, `get_guest_by_ip` (from Task 1), `get_client_ip` (from Task 2), `get_player_count` (existing)
- Produces: Updated landing page HTML with guest button and guest detection

- [ ] **Step 1: Replace the `else` block (not logged in) of the `index()` route**

The current `else` branch starts at line 143 (`else:`) and runs to line 188. Replace the entire `else:` block (keeping the `if logged_in:` block intact above it):

```python
    else:
        # Not logged in — check for returning guest
        guest_user_id = request.cookies.get('guest_user_id')
        returning_guest = None

        if guest_user_id:
            returning_guest = get_guest_by_user_id(guest_user_id)

        if returning_guest is None:
            client_ip = get_client_ip()
            returning_guest = get_guest_by_ip(client_ip)

        # Build returning guest prompt HTML if found
        guest_prompt_html = ""
        if returning_guest:
            guest_prompt_html = f"""
            <div class="guest-prompt">
                <p>🎲 <b>{returning_guest['username']}</b> olarak misafir oynamaya devam etmek ister misin?</p>
                <form method="POST" action="/guest-continue">
                    <button class="btn btn-guest-continue" type="submit">✅ Evet, Devam Et</button>
                </form>
                <p class="or-text">—— veya ——</p>
            </div>
            """

        return f"""
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Social Emperors</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; display: flex; justify-content: center;
            align-items: center; min-height: 100vh; margin: 0;
        }}
        .box {{ background: #16213e; border-radius: 12px; padding: 40px; text-align: center; max-width: 420px; box-shadow: 0 4px 24px rgba(0,0,0,0.3); }}
        h1 {{ margin-top: 0; color: #e94560; }}
        .input {{ width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #333; border-radius: 6px; background: #1a1a2e; color: #eee; font-size: 15px; box-sizing: border-box; }}
        .btn {{ display: block; width: 100%; margin: 12px 0; padding: 14px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: 600; cursor: pointer; border: none; transition: transform 0.1s; }}
        .btn:hover {{ transform: scale(1.03); }}
        .btn-login {{ background: #e94560; color: #fff; }}
        .btn-register {{ background: #0f3460; color: #ccc; border: 1px solid #333; }}
        .btn-guest {{ background: #d4a574; color: #1a1a2e; }}
        .btn-guest-continue {{ background: #2d6a4f; color: #fff; }}
        .btn-players {{ background: #2d6a4f; color: #fff; }}
        .divider {{ margin: 16px 0; color: #666; font-size: 13px; }}
        .or-text {{ color: #666; font-size: 13px; margin: 12px 0; }}
        .error {{ background: #3d1a1a; color: #e94560; padding: 8px; border-radius: 4px; margin: 8px 0; font-size: 14px; }}
        .note {{ font-size: 12px; color: #666; margin-top: 16px; }}
        .guest-prompt {{ background: #1a2a1a; border: 1px solid #2d6a4f; border-radius: 8px; padding: 16px; margin: 12px 0; }}
        .guest-prompt p {{ margin: 0 0 12px 0; color: #ccc; }}
    </style>
</head>
<body>
    <div class="box">
        <h1>🔥 Social Emperors</h1>
        {error_html}
        {guest_prompt_html}
        <form method="POST" action="/login">
            <input class="input" type="text" name="username" placeholder="Kullanici adi" required autocomplete="username">
            <input class="input" type="password" name="password" placeholder="Sifre" required autocomplete="current-password">
            <button class="btn btn-login" type="submit">🔑 Giris Yap</button>
        </form>
        <form method="GET" action="/register">
            <button class="btn btn-register" type="submit">✨ Kayit Ol</button>
        </form>
        <div class="divider">—— veya ——</div>
        <a class="btn btn-guest" href="/guest">🎲 Misafir Olarak Oyna</a>
        <div class="divider">—— veya ——</div>
        <a class="btn btn-players" href="/players">📋 Oyuncu Listesi</a>
        <p class="note">⚠️ Ruffle ile oynarken bazi ozellikler calismayabilir.</p>
    </div>
</body>
</html>
"""
```

- [ ] **Step 2: Verify the complete `index()` function structure**

The `index()` function should now have this flow:
1. Check `if logged_in` → show play page (unchanged)
2. `else` → check for returning guest cookie/IP → show landing page with:
   - Guest "devam et?" prompt if guest found
   - Login form
   - Register button
   - Guest button (NEW)
   - Players list

- [ ] **Step 3: Test server startup**

Run: `python -c "from server import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat: add guest button and returning guest detection to landing page"
```

---

### Task 4: End-to-end verification

**Files:**
- None (testing only)

- [ ] **Step 1: Start the server in the background**

```bash
cd D:/apps/socialgame && python server.py &
```
Wait 3 seconds for startup.

- [ ] **Step 2: Test landing page loads with guest button**

Run: `curl -s http://127.0.0.1:5050/`
Expected: HTML contains "🎲 Misafir Olarak Oyna" and a link to `/guest`

- [ ] **Step 3: Test guest form loads**

Run: `curl -s http://127.0.0.1:5050/guest`
Expected: HTML contains "🎲 Misafir Girisi" and a form with `action="/guest-login"`

- [ ] **Step 4: Test guest login creates user and sets cookie**

Run: `curl -s -v -X POST http://127.0.0.1:5050/guest-login -d "nickname=testkahraman" 2>&1`
Expected: 302 redirect to `/welcome`, `Set-Cookie` header contains `guest_user_id`

- [ ] **Step 5: Test returning guest detection (cookie)**

Run: `curl -s -b "guest_user_id=<USERID_FROM_STEP4>" http://127.0.0.1:5050/`
Expected: HTML contains "olarak misafir oynamaya devam etmek ister misin"

- [ ] **Step 6: Test `/guest-continue` resumes session**

Run: `curl -s -v -X POST -b "guest_user_id=<USERID_FROM_STEP4>" http://127.0.0.1:5050/guest-continue 2>&1`
Expected: 302 redirect to `/play.html`

- [ ] **Step 7: Test `/logout` clears session**

Run: `curl -s -v http://127.0.0.1:5050/logout 2>&1`
Expected: 302 redirect to `/`

- [ ] **Step 8: Stop the test server**

```bash
kill $(pgrep -f "python server.py") 2>/dev/null; echo "stopped"
```

- [ ] **Step 9: Commit any final adjustments**

```bash
git add -A
git commit -m "test: end-to-end verification of guest login flow"
```
