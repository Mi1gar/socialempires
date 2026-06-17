# Social Emperors – Kullanıcı Giriş Sistemi Tasarımı

**Date:** 2026-06-17
**Status:** Awaiting user review
**Goal:** Oyuna username/password tabanlı kullanıcı giriş sistemi eklemek. Her oyuncu hesap oluşturup giriş yapabilir, diğer oyuncuların köylerini görebilir ve saldırabilir.

## Kararlar

| Karar | Seçim |
|-------|-------|
| Auth yöntemi | Username + şifre (bcrypt) |
| Hesap-köy ilişkisi | 1 hesap = 1 köy |
| Sosyal kapsam | Köyleri görme + saldırma (arkadaş/mesaj/sıralama YOK) |
| Teknoloji | bcrypt + PostgreSQL (psycopg2 direkt), Flask session |

## Mimari

```
Tarayıcı → Flask server.py (routes) → auth.py (bcrypt, register/login) → PostgreSQL (users + player_saves)
```

## Veritabanı

### Yeni tablo: `users`

```sql
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    user_id       TEXT UNIQUE NOT NULL,   -- FK → player_saves.user_id
    created_at    TIMESTAMP DEFAULT NOW()
);
```

`users.user_id` → `player_saves.user_id` birebir eşleşme. Kayıt olunca her iki tabloya da kayıt eklenir.

### Mevcut tablo: `player_saves` (değişiklik yok)

## Route'lar

| Route | Method | Değişiklik | Açıklama |
|-------|--------|-----------|----------|
| `/` | GET | **Değişecek** | Giriş yapmamışsa login/kayıt formu + oyuncu listesi linki. Giriş yapmışsa "Hoş geldin X" + oyuna devam butonları |
| `/login` | POST | **Yeni** | Giriş formunu işler, session'a username+GAMEVERSION yazar, /play.html'e yönlendirir |
| `/register` | GET, POST | **Yeni** | GET: kayıt formu. POST: hesap + köy oluşturur, otomatik giriş yapar |
| `/logout` | GET | **Yeni** | Session'ı temizler, `/`'a yönlendirir |
| `/players` | GET | **Yeni** | Tüm oyuncuları listeler (isim, level, xp). "Ziyaret Et" butonu |
| `/new.html` | GET | Mevcut | Sadece manuel köy oluşturma (debug için). Normal akışta `/register` kullanılır |
| `/play.html` | GET | **Değişecek** | `username` session kontrolü eklenecek. `?visit=USERID` ile başkasının köyü ziyaret edilebilecek |
| `/ruffle.html` | GET | **Değişecek** | `username` session kontrolü eklenecek |

### Session

Mevcut: `USERID`, `GAMEVERSION`
Yeni: `username` (ek), `USERID`, `GAMEVERSION`

### Kullanıcı Akışı

```
İlk gelen:  / → "Kayıt Ol" → /register → username+password → hesap + köy oluştur → /play.html
Dönen:      / → "Giriş Yap" → POST /login → /play.html
Oyuncular:  / → "Oyuncu Listesi" → /players → isim/level/xp → [Ziyaret Et]
```

## Dosya Değişiklikleri

| Dosya | İşlem | Sorumluluk |
|-------|-------|-----------|
| `auth.py` | **Yeni** | bcrypt hash, register_user(), verify_login(), get_all_players(), change_password() |
| `server.py` | Değiştir | Landing page yeniden, `/login` `/register` `/logout` `/players` route'ları, `username` session kontrolü |
| `sessions.py` | Değiştir | `create_village_with_id(user_id)` eklenecek |
| `requirements.txt` | Değiştir | `bcrypt==4.*` eklenecek |
| `db.py` | Değişiklik yok | - |
| `command.py` | Değişiklik yok | - |
| `engine.py` | Değişiklik yok | - |

## auth.py API

```python
init_auth_tables()                              # Tablo oluştur (idempotent)
register_user(username, password) → (str, str) | None  # Başarılı: (username, user_id)
verify_login(username, password) → (str, str) | None   # Başarılı: (username, user_id)
get_all_players(exclude_username=None) → list[dict]     # Tüm oyuncular
change_password(username, old_pw, new_pw) → bool        # Şifre değiştir
```

## sessions.py ekleme

```python
def create_village_with_id(user_id: str) -> str:
    """Verilen user_id ile yeni köy oluştur. initial.json'dan kopyalar."""
```

Mevcut `new_village()` kendi UUID'sini oluşturur. `create_village_with_id()` dışarıdan verilen user_id ile çalışır (auth sistemi UUID'yi önce oluşturup sonra köyü kurar).

## Bağımlılıklar

```
bcrypt==4.*  (requirements.txt'ye eklenecek)
```

## Riskler

| Risk | Olasılık | Çözüm |
|------|----------|-------|
| Aynı username çakışması | Orta | `users.username UNIQUE` constraint, kayıt sırasında kontrol |
| Session çalınması | Düşük | Render HTTPS zorunlu, Flask session signed cookie |
| bcrypt hash yavaşlığı | Çok düşük | Sadece login/register'da çalışır, oyun içinde değil |
| Eski UUID'li kayıtlar (önceden oynayanlar) | Orta | Migration gerekmez — eski oyuncular yeni hesap oluşturur. İstenirse `/claim` route'u ile eski UUID'yi yeni hesaba bağlama eklenebilir |

## Success Criteria

- [ ] Kullanıcı `/register` ile hesap oluşturabilir
- [ ] Kullanıcı `/login` ile giriş yapabilir
- [ ] Giriş yapan kullanıcı kendi köyüne gider
- [ ] `/players` sayfasında tüm oyuncular listelenir
- [ ] Bir oyuncu diğerinin köyünü ziyaret edebilir (`?visit=USERID`)
- [ ] Saldırı sistemi çalışır (mevcut PVP mekaniği)
- [ ] Çıkış yapıp farklı hesapla giriş yapılabilir
- [ ] Yanlış şifre ile giriş reddedilir
