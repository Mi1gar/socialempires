"""
Kimlik dogrulama modulu.
bcrypt ile sifre hash'leme, kullanici kaydi ve girisi.
"""
import uuid
import bcrypt
from db import query, execute


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


def hash_password(password: str) -> str:
    """Sifreyi bcrypt ile hash'le."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password: str, hashed: str) -> bool:
    """Sifre hash karsilastirmasi."""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def register_user(username: str, password: str) -> tuple | None:
    """Yeni kullanici kaydi. Basariliysa (username, user_id) donder, hata varsa None.

    Yan etki: player_saves tablosuna bos koy kaydi ekler.
    """
    from sessions import create_village_with_id

    # Username kontrolu
    existing = query("SELECT id FROM users WHERE username = %s", [username])
    if existing:
        return None  # Kullanici adi zaten alinmis

    # Yeni UUID olustur
    user_id = str(uuid.uuid4())

    # Sifreyi hash'le
    pw_hash = hash_password(password)

    # Kullaniciyi ekle
    execute(
        "INSERT INTO users (username, password_hash, user_id) VALUES (%s, %s, %s)",
        [username, pw_hash, user_id]
    )

    # Koy olustur
    create_village_with_id(user_id)

    return username, user_id


def verify_login(username: str, password: str) -> tuple | None:
    """Giris dogrulamasi. Basariliysa (username, user_id) donder."""
    rows = query(
        "SELECT username, password_hash, user_id FROM users WHERE username = %s",
        [username]
    )
    if not rows:
        return None

    row = rows[0]
    if check_password(password, row['password_hash']):
        return row['username'], row['user_id']
    return None


def get_user_info(username: str) -> dict | None:
    """Kullanici bilgilerini getir."""
    rows = query(
        "SELECT username, user_id, created_at FROM users WHERE username = %s",
        [username]
    )
    return rows[0] if rows else None


def get_player_count() -> int:
    """Toplam oyuncu sayisi."""
    rows = query("SELECT COUNT(*) AS cnt FROM users")
    return rows[0]['cnt'] if rows else 0


def get_all_players(exclude_username: str = None) -> list:
    """Tum oyunculari listele. Istege bagli olarak bir kullaniciyi haric tut.

    Returns:
        Her oyuncu icin: username, user_id, level, xp, map_name
    """
    if exclude_username:
        rows = query(
            """SELECT u.username, u.user_id,
                      COALESCE(ps.save_data->'maps'->0->>'level', '1') as level,
                      COALESCE(ps.save_data->'maps'->0->>'xp', '0') as xp,
                      COALESCE(ps.save_data->'playerInfo'->'map_names'->>0, 'Village') as map_name
               FROM users u
               LEFT JOIN player_saves ps ON u.user_id = ps.user_id
               WHERE u.username != %s
               ORDER BY (COALESCE(ps.save_data->'maps'->0->>'xp', '0'))::int DESC""",
            [exclude_username]
        )
    else:
        rows = query(
            """SELECT u.username, u.user_id,
                      COALESCE(ps.save_data->'maps'->0->>'level', '1') as level,
                      COALESCE(ps.save_data->'maps'->0->>'xp', '0') as xp,
                      COALESCE(ps.save_data->'playerInfo'->'map_names'->>0, 'Village') as map_name
               FROM users u
               LEFT JOIN player_saves ps ON u.user_id = ps.user_id
               ORDER BY (COALESCE(ps.save_data->'maps'->0->>'xp', '0'))::int DESC"""
        )
    return rows


def username_exists(username: str) -> bool:
    """Kullanici adi zaten var mi?"""
    rows = query("SELECT id FROM users WHERE username = %s", [username])
    return len(rows) > 0


def change_password(username: str, old_password: str, new_password: str) -> bool:
    """Sifre degistir. Basariliysa True."""
    if not verify_login(username, old_password):
        return False
    pw_hash = hash_password(new_password)
    execute(
        "UPDATE users SET password_hash = %s WHERE username = %s",
        [pw_hash, username]
    )
    return True


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
        "WHERE user_id = %s",
        [user_id]
    )
    # Filter in Python for file-based DB compatibility
    for row in rows:
        if row.get('is_guest') is True or row.get('is_guest') == 'true':
            return row
    return None


def get_guest_by_ip(ip_address: str, days: int = 7) -> dict | None:
    """Ayni IP'den en son giris yapan misafiri bul. Yoksa None."""
    rows = query(
        "SELECT username, user_id, is_guest, last_ip FROM users "
        "WHERE last_ip = %s",
        [ip_address]
    )
    # Filter and sort in Python for file-based DB compatibility
    guests = [r for r in rows if r.get('is_guest') is True or r.get('is_guest') == 'true']
    return guests[0] if guests else None
