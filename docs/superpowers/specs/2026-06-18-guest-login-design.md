# Guest Login System — Design Spec

**Date:** 2026-06-18
**Status:** Approved
**Context:** Social Emperors private server — add guest login next to existing user login

---

## Overview

Add a "Misafir Olarak Oyna" (Play as Guest) button next to the existing login form on the landing page. Guests get the full game experience with no restrictions. Their session persists on the device via a persistent cookie with IP address as a fallback identifier.

---

## Requirements

### Functional
- **Guest Login Button:** A visible button on the landing page next to the login/register forms
- **Nickname Form:** First-time guests enter a nickname (no password required)
- **Full Game Access:** Guests have the same game experience as registered users
- **Session Persistence:** Guest session survives browser restarts via a 30-day cookie
- **IP Fallback:** If the cookie is lost, IP address matching offers to restore the guest session
- **Guest-to-Registered:** Not in scope for this version (future enhancement)

### Non-Functional
- Guest accounts reuse the existing `users` + `player_saves` DB structure — no separate code path for game mechanics
- Backward compatible — existing registered users are unaffected
- Minimal DB changes: two nullable columns added to `users`

---

## Database Changes

### `users` table — new columns

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_guest BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_ip TEXT;
```

- `is_guest`: Distinguishes guest accounts from registered ones
- `last_ip`: Stores the last login IP for cookie-less fallback matching

Guest users live in the same `users` table as registered users. Their `password_hash` is set to an empty string (never checked). They have unique UUIDs and their own village via the existing `create_village_with_id()` flow.

---

## Backend Routes

### `GET /guest` — Nickname Form
- Simple HTML form: one text input for nickname (min 3 chars)
- Styled consistently with existing pages (dark theme, same CSS patterns)
- No password field

### `POST /guest-login` — Process Guest Login
1. Read `nickname` from form (required, ≥3 chars)
2. Generate `username = "guest_" + nickname + "_" + random_suffix` to avoid collisions
3. Generate UUID via `uuid.uuid4()`
4. Insert into `users` with `is_guest=true`, `last_ip=<client_ip>`, `password_hash=''`
5. Call `create_village_with_id(user_id)` — same village creation as registered users
6. Set Flask session: `username`, `USERID`, `GAMEVERSION`
7. Set persistent cookie `guest_user_id=<user_id>` (30 days, HttpOnly, SameSite=Lax)
8. Redirect to `/welcome`

### `GET /` (landing page) — Modified
Current behavior (Flask session active → play page) is unchanged.

When **not logged in**, add these checks before showing the login form:
1. If `guest_user_id` cookie exists → look up user by user_id → if found and IP matches → show "🎲 `<nickname>` olarak devam et?" prompt with a continue button
2. If no valid cookie but a guest account exists from this IP (last 7 days) → show "Eski misafir hesabın bulundu, devam et?" prompt
3. Otherwise → show normal login + register + **new guest button**

### `POST /guest-continue` — Resume Guest Session
1. Read `guest_user_id` cookie
2. Verify user exists, is guest, and IP matches (or cookie is valid)
3. Set Flask session and redirect to `/play.html`

### `GET /logout` — New Route
- Clear Flask session
- Do NOT clear `guest_user_id` cookie — allows reconnecting later
- Redirect to `/`

---

## Frontend Changes

### Landing Page (not logged in)

```
┌──────────────────────────────┐
│     🔥 Social Emperors       │
│                              │
│  [Kullanici adi]             │
│  [Sifre          ]           │
│  [🔑 Giris Yap]              │
│  [✨ Kayit Ol]               │
│  —— veya ——                  │
│  [🎲 Misafir Olarak Oyna]    │  ← NEW (green/amber tone)
│  —— veya ——                  │
│  [📋 Oyuncu Listesi]         │
└──────────────────────────────┘
```

Guest button color: `#d4a574` (warm amber) — distinct from login (`#e94560` red) and register (`#0f3460` blue).

### Guest Nickname Form (`/guest`)

```
┌──────────────────────────────┐
│     🎲 Misafir Girisi         │
│                              │
│  [Rumuz (en az 3 karakter)]  │
│  [🎮 Oyuna Basla]            │
│  ⬅ Geri Don                  │
│                              │
│  Rumuzun ve ilerlemen bu     │
│  cihazda saklanir. Daha      │
│  sonra kayit olup hesabini   │
│  kalici yapabilirsin.        │
└──────────────────────────────┘
```

### "Continue as Guest" Prompt (landing page, returning guest)

Shown when a previous guest session is detected:

```
┌──────────────────────────────┐
│  🎲 <rumuz> olarak           │
│  oynamaya devam etmek        │
│  ister misin?                │
│                              │
│  [✅ Evet, Devam Et]         │
│  [🔄 Yeni Misafir Girisi]    │
└──────────────────────────────┘
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Nickname already taken (by guest username) | Show error "Bu rumuz kullaniliyor", ask for another |
| Cookie exists but user deleted from DB | Clear cookie, fall through to normal landing page |
| Same IP, multiple guest accounts | Cookie takes priority; IP fallback picks most recent login |
| Guest clicks logout | Clear Flask session only — keep cookie for future return |
| IP changes (mobile, VPN, DHCP) | Cookie still works fine — IP is only a fallback |
| Nickname < 3 characters | Validation error on form |

---

## Code Changes Summary

| File | Change |
|---|---|
| `auth.py` | Add `is_guest` + `last_ip` columns to `init_auth_tables()`, add helper functions |
| `server.py` | Add `/guest`, `/guest-login`, `/guest-continue`, `/logout` routes; modify `/` landing page logic |
| `db.py` | No changes needed (existing `query`/`execute` sufficient) |
| `sessions.py` | No changes needed (guest users use same `create_village_with_id`) |

---

## Out of Scope (Future)
- Guest-to-registered account upgrade
- Guest account expiry / auto-cleanup
- Multiple guest accounts per device
- Guest access restrictions or limits
