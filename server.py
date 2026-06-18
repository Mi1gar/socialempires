print (" [+] Loading basics...")
import os
import json
import urllib
if os.name == 'nt':
    os.system("color")
    os.system("title Social Empires Server")
else:
    import sys
    sys.stdout.write("\x1b]2;Social Empires Server\x07")

print (" [+] Loading game config...")
from get_game_config import get_game_config, patch_game_config

print (" [+] Loading players...")
from get_player_info import get_player_info, get_neighbor_info
from sessions import load_saved_villages, all_saves_userid, all_saves_info, save_info, new_village, fb_friends_str
from auth import init_auth_tables, register_user, verify_login, get_all_players, get_player_count, username_exists, create_guest_user, get_guest_by_user_id, get_guest_by_ip
from sessions import session as get_save_session
load_saved_villages()
try:
    init_auth_tables()
except Exception as e:
    print(f"[server] Auth tables init failed (no PostgreSQL?): {e}")

print (" [+] Loading server...")
from flask import Flask, render_template, send_from_directory, request, redirect, session, render_template_string
from flask.debughelpers import attach_enctype_error_multidict
from command import command
from engine import timestamp_now
from version import version_name
from constants import Constant
from quests import get_quest_map
from bundle import ASSETS_DIR, STUB_DIR, TEMPLATES_DIR, BASE_DIR


def get_client_ip() -> str:
    """Return the client's real IP address, accounting for proxy headers (Render)."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


host = '127.0.0.1'
port = 5050

app = Flask(__name__, template_folder=TEMPLATES_DIR)

# Use Render-provided secret key or a dev fallback
app.secret_key = os.environ.get("SECRET_KEY", "social-empires-dev-key-change-me")

# Database URL for PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL", "")

REGISTER_FORM = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Kayit Ol — Social Emperors</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; display: flex; justify-content: center;
            align-items: center; min-height: 100vh; margin: 0;
        }}
        .box {{ background: #16213e; border-radius: 12px; padding: 40px; text-align: center; max-width: 400px; box-shadow: 0 4px 24px rgba(0,0,0,0.3); }}
        h1 {{ margin-top: 0; color: #e94560; }}
        .input {{ width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #333; border-radius: 6px; background: #1a1a2e; color: #eee; font-size: 15px; box-sizing: border-box; }}
        .btn {{ display: block; width: 100%; margin: 12px 0; padding: 14px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; border: none; transition: transform 0.1s; }}
        .btn:hover {{ transform: scale(1.03); }}
        .btn-primary {{ background: #e94560; color: #fff; }}
        .btn-back {{ background: #444; color: #aaa; }}
        .error {{ background: #3d1a1a; color: #e94560; padding: 8px; border-radius: 4px; margin: 8px 0; font-size: 14px; }}
        a {{ color: #e94560; }}
    </style>
</head>
<body>
    <div class="box">
        <h1>✨ Kayit Ol</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST" action="/register">
            <input class="input" type="text" name="username" placeholder="Kullanici adi (en az 3 karakter)" required minlength="3" autocomplete="username">
            <input class="input" type="password" name="password" placeholder="Sifre (en az 4 karakter)" required minlength="4" autocomplete="new-password">
            <input class="input" type="password" name="password_confirm" placeholder="Sifre tekrar" required minlength="4" autocomplete="new-password">
            <button class="btn btn-primary" type="submit">✨ Hesap Olustur</button>
        </form>
        <a class="btn btn-back" href="/">⬅ Geri Don</a>
    </div>
</body>
</html>
"""

print (" [+] Configuring server routes...")

##########
# ROUTES #
##########

## PAGES AND RESOURCES

@app.route("/")
def index():
    """Landing page: login, register, or continue playing."""
    logged_in = 'username' in session and 'USERID' in session

    error = request.args.get('error', '')
    error_html = f'<div class="error">{error}</div>' if error else ''

    if logged_in:
        username = session['username']
        player_count = get_player_count()
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
        .box {{ background: #16213e; border-radius: 12px; padding: 40px; text-align: center; max-width: 500px; box-shadow: 0 4px 24px rgba(0,0,0,0.3); }}
        h1 {{ margin-top: 0; color: #e94560; }}
        .btn {{ display: block; margin: 12px auto; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: 600; transition: transform 0.1s; }}
        .btn:hover {{ transform: scale(1.03); }}
        .btn-primary {{ background: #e94560; color: #fff; }}
        .btn-secondary {{ background: #0f3460; color: #ccc; border: 1px solid #333; }}
        .btn-players {{ background: #2d6a4f; color: #fff; }}
        .btn-logout {{ background: #444; color: #aaa; font-size: 13px; padding: 8px 20px; }}
        .info {{ font-size: 14px; color: #aaa; margin: 8px 0; }}
        .section {{ margin: 20px 0; border-top: 1px solid #333; padding-top: 16px; }}
    </style>
</head>
<body>
    <div class="box">
        <h1>🔥 Social Emperors</h1>
        <p style="color:#aaa;">Hos geldin, <b>{username}</b>!</p>
        <a class="btn btn-primary" href="/ruffle.html">🎮 Oyuna Devam (Ruffle)</a>
        <a class="btn btn-secondary" href="/play.html">💾 FlashBrowser ile Oyna</a>
        <div class="section">
            <a class="btn btn-players" href="/players">📋 Oyuncu Listesi ({player_count} oyuncu)</a>
        </div>
        <a class="btn btn-logout" href="/logout">🚪 Cikis Yap</a>
    </div>
</body>
</html>
"""
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

def _is_new_player() -> bool:
    """Check if the logged-in player hasn't completed the tutorial yet."""
    try:
        save = get_save_session(session.get('USERID', ''))
        if save and save.get("playerInfo", {}).get("completed_tutorial", 1) == 0:
            return True
    except Exception:
        pass
    return False


@app.route("/login", methods=["POST"])
def login():
    """Handle login form submission."""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    if not username or not password:
        return redirect("/?error=Kullanici+adi+ve+sifre+gerekli")

    result = verify_login(username, password)
    if result is None:
        return redirect("/?error=Hatali+kullanici+adi+veya+sifre")

    session['username'] = result[0]
    session['USERID'] = result[1]
    session['GAMEVERSION'] = "SocialEmpires0926bsec.swf"

    # Reload villages so the new player's village is in memory
    load_saved_villages()

    if _is_new_player():
        return redirect("/welcome")
    return redirect("/play.html")


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


@app.route("/logout")
def logout():
    """Clear session but preserve guest cookie for future return."""
    session.clear()
    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Handle user registration."""
    if request.method == "POST":
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # Validation
        if not username or not password:
            return render_template_string(REGISTER_FORM, error="Tum alanlari doldurun")
        if len(username) < 3:
            return render_template_string(REGISTER_FORM, error="Kullanici adi en az 3 karakter olmali")
        if len(password) < 4:
            return render_template_string(REGISTER_FORM, error="Sifre en az 4 karakter olmali")
        if password != password_confirm:
            return render_template_string(REGISTER_FORM, error="Sifreler eslesmiyor")
        if username_exists(username):
            return render_template_string(REGISTER_FORM, error="Bu kullanici adi zaten alinmis")

        result = register_user(username, password)
        if result is None:
            return render_template_string(REGISTER_FORM, error="Kayit basarisiz. Tekrar deneyin.")

        # Auto-login
        session['username'] = result[0]
        session['USERID'] = result[1]
        session['GAMEVERSION'] = "SocialEmpires0926bsec.swf"
        load_saved_villages()

        return redirect("/welcome")

    # GET — show registration form
    return render_template_string(REGISTER_FORM, error=None)


@app.route("/welcome")
def welcome():
    """Tutorial oncesi hos geldin sayfasi."""
    if 'username' not in session or 'USERID' not in session:
        return redirect("/")

    username = session['username']

    return f"""
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Hos Geldin — Social Emperors</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #1a1a2e; color: #eee; display: flex;
            justify-content: center; align-items: center; min-height: 100vh;
        }}
        .container {{ max-width: 600px; padding: 20px; }}
        .card {{
            background: #16213e; border-radius: 16px; padding: 40px 32px;
            text-align: center; box-shadow: 0 8px 40px rgba(0,0,0,0.4);
            border: 1px solid #2a2a4a;
        }}
        .icon {{ font-size: 64px; margin-bottom: 16px; }}
        h1 {{ color: #e94560; font-size: 28px; margin-bottom: 8px; }}
        .subtitle {{ color: #888; font-size: 14px; margin-bottom: 24px; }}
        .lore {{
            background: #0f1629; border-radius: 10px; padding: 20px;
            text-align: left; margin: 20px 0; line-height: 1.8;
            font-size: 15px; color: #ccc; border-left: 3px solid #e94560;
        }}
        .lore b {{ color: #e94560; }}
        .btn {{
            display: inline-block; margin: 12px 6px; padding: 16px 40px;
            border-radius: 10px; text-decoration: none; font-size: 17px;
            font-weight: 700; cursor: pointer; border: none;
            transition: transform 0.15s, box-shadow 0.15s;
        }}
        .btn:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(233,69,96,0.3); }}
        .btn-start {{
            background: linear-gradient(135deg, #e94560, #c23152);
            color: #fff; font-size: 20px; padding: 18px 60px;
        }}
        .btn-skip {{
            background: #333; color: #888; font-size: 13px; padding: 10px 24px;
        }}
        .footer {{ margin-top: 24px; color: #555; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="icon">🔥</div>
            <h1>Imparatorlugun Seni Bekliyor!</h1>
            <p class="subtitle">Hos geldin, <b>{username}</b></p>

            <div class="lore">
                <p>⚔️ <b>Yil 1024.</b> Kralliklar savas halinde.</p>
                <p style="margin-top:8px;">🏰 Kucuk bir koy ile basliyorsun. Topragini genislet, ordunu kur, dusmanlarini fethet.</p>
                <p style="margin-top:8px;">🐉 <b>Ejderhani sec.</b> Bu senin en buyuk gucun olacak — ates, buz ya da yildirim?</p>
                <p style="margin-top:8px;">👑 <b>Imparatorluga giden yol</b> cesaret ister. Kararlarin kaderini belirleyecek.</p>
            </div>

            <p style="color:#aaa; font-size:14px; margin-top:20px;">
            Oyun sana adim adim rehberlik edecek.<br>Hazir oldugunda basla!
            </p>

            <a class="btn btn-start" href="/play.html">🔥 Oyuna Basla</a>
            <br>
            <a class="btn btn-skip" href="/play.html?skip_tutorial=1">Atlaya Atlaya Gec →</a>
        </div>
        <p class="footer">Social Emperors — Ozel Sunucu</p>
    </div>
</body>
</html>
"""


@app.route("/players")
def players():
    """List all players with their village info."""
    current_user = session.get('username', None)
    all_players = get_all_players(exclude_username=current_user)

    rows_html = ""
    for i, p in enumerate(all_players):
        rows_html += f"""
        <tr>
            <td>{i+1}</td>
            <td>{p['username']}</td>
            <td>{p['map_name']}</td>
            <td>Lv.{p['level']} ({p['xp']} XP)</td>
            <td><a class="btn-visit" href="/play.html?visit={p['user_id']}">🔍 Ziyaret Et</a></td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="5" style="padding:40px;color:#666;">Henuz baska oyuncu yok. Ilk sen katil!</td></tr>'

    player_count = len(all_players)

    return f"""
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Oyuncu Listesi — Social Emperors</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; display: flex; justify-content: center;
            align-items: flex-start; min-height: 100vh; margin: 0; padding-top: 40px;
        }}
        .box {{ background: #16213e; border-radius: 12px; padding: 30px; max-width: 700px; width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.3); }}
        h1 {{ color: #e94560; margin-top: 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
        th {{ text-align: left; padding: 10px; border-bottom: 2px solid #333; color: #aaa; font-size: 13px; }}
        td {{ padding: 10px; border-bottom: 1px solid #222; }}
        .btn-visit {{ background: #2d6a4f; color: #fff; padding: 6px 14px; border-radius: 4px; text-decoration: none; font-size: 13px; font-weight: 600; }}
        .btn-visit:hover {{ background: #3d8a6f; }}
        .btn-back {{ display: inline-block; margin-top: 16px; background: #444; color: #aaa; padding: 10px 24px; border-radius: 6px; text-decoration: none; font-size: 14px; }}
        .info {{ color: #888; font-size: 13px; margin-bottom: 16px; }}
    </style>
</head>
<body>
    <div class="box">
        <h1>📋 Oyuncu Listesi</h1>
        <p class="info">{player_count} oyuncu</p>
        <table>
            <thead><tr><th>#</th><th>Oyuncu</th><th>Koy</th><th>Seviye</th><th></th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        <a class="btn-back" href="/">⬅ Ana Sayfa</a>
    </div>
</body>
</html>
"""

@app.route("/play.html")
def play():
    print(session)

    # Visiting another player's village?
    visit_id = request.args.get('visit', None)

    if 'username' not in session or 'USERID' not in session:
        return redirect("/")
    if 'GAMEVERSION' not in session:
        return redirect("/")

    USERID = visit_id if visit_id else session['USERID']
    GAMEVERSION = session['GAMEVERSION']
    print("[PLAY] USERID:", USERID)
    print("[PLAY] GAMEVERSION:", GAMEVERSION)
    server_host = request.host  # uses the actual host from the request
    return render_template("play.html", save_info=save_info(USERID), serverTime=timestamp_now(), friendsInfo=fb_friends_str(USERID), version=version_name, GAMEVERSION=GAMEVERSION, SERVERIP=server_host)

@app.route("/ruffle.html")
def ruffle():
    print(session)

    # Visiting another player's village?
    visit_id = request.args.get('visit', None)

    if 'username' not in session or 'USERID' not in session:
        return redirect("/")
    if 'GAMEVERSION' not in session:
        return redirect("/")

    USERID = visit_id if visit_id else session['USERID']
    GAMEVERSION = session['GAMEVERSION']
    print("[RUFFLE] USERID:", USERID)
    print("[RUFFLE] GAMEVERSION:", GAMEVERSION)
    server_host = request.host
    return render_template("ruffle.html", save_info=save_info(USERID), serverTime=timestamp_now(), version=version_name, GAMEVERSION=GAMEVERSION, SERVERIP=server_host)


@app.route("/new.html")
def new():
    session['USERID'] = new_village()
    session['GAMEVERSION'] = "SocialEmpires0926bsec.swf"
    mode = request.args.get('mode', 'play')
    return redirect(f"{mode}.html")

@app.route("/crossdomain.xml")
def crossdomain():
    return send_from_directory(STUB_DIR, "crossdomain.xml")

@app.route("/img/<path:path>")
def images(path):
    return send_from_directory(TEMPLATES_DIR + "/img", path)

@app.route("/css/<path:path>")
def css(path):
    return send_from_directory(TEMPLATES_DIR + "/css", path)

## GAME STATIC


@app.route("/default01.static.socialpointgames.com/static/socialempires/swf/05122012_projectiles.swf")
def similar_05122012_projectiles():
    return send_from_directory(ASSETS_DIR + "/swf", "20130417_projectiles.swf")

@app.route("/default01.static.socialpointgames.com/static/socialempires/swf/05122012_magicParticles.swf")
def similar_05122012_magicParticles():
    return send_from_directory(ASSETS_DIR + "/swf", "20131010_magicParticles.swf")

@app.route("/default01.static.socialpointgames.com/static/socialempires/swf/05122012_dynamic.swf")
def similar_05122012_dynamic():
    return send_from_directory(ASSETS_DIR + "/swf", "120608_dynamic.swf")

@app.route("/default01.static.socialpointgames.com/static/socialempires/<path:path>")
def static_assets_loader(path):
    # return send_from_directory(ASSETS_DIR, path)
    if not os.path.exists(ASSETS_DIR + "/"+ path):
        # File does not exists in provided assets
        if not os.path.exists(f"{BASE_DIR}/download_assets/assets/{path}"):
            # Download file from SP's CDN if it doesn't exist

            # Make directory
            directory = os.path.dirname(f"{BASE_DIR}/download_assets/assets/{path}")
            if not os.path.exists(directory):
                os.makedirs(directory)

            # Download File
            URL = f"https://static.socialpointgames.com/static/socialempires/assets/{path}"
            try:
                response = urllib.request.urlretrieve(URL, f"{BASE_DIR}/download_assets/assets/{path}")
            except urllib.error.HTTPError:
                return ("", 404)

            print(f"====== DOWNLOADED ASSET: {URL}")
            return send_from_directory("{BASE_DIR}/download_assets/assets", path)
        else:
            # Use downloaded CDN asset
            print(f"====== USING EXTERNAL: download_assets/assets/{path}")
            return send_from_directory("{BASE_DIR}/download_assets/assets", path)
    else:
        # Use provided asset
        return send_from_directory(ASSETS_DIR, path)

## GAME DYNAMIC

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/track_game_status.php", methods=['POST'])
def track_game_status_response():
    status = request.values['status']
    installId = request.values['installId']
    user_id = request.values['user_id']

    print(f"track_game_status: status={status}, installId={installId}, user_id={user_id}. --", request.values)
    return ("", 200)

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/get_game_config.php", methods=['GET','POST'])
def get_game_config_response():
    spdebug = None

    USERID = request.values['USERID']
    user_key = request.values['user_key']
    if 'spdebug' in request.values:
        spdebug = request.values['spdebug']
    language = request.values['language']

    print(f"get_game_config: USERID: {USERID}. --", request.values)
    return get_game_config()

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/get_player_info.php", methods=['POST'])
def get_player_info_response():

    USERID = request.values['USERID']
    user_key = request.values['user_key']
    spdebug = request.values['spdebug'] if 'spdebug' in request.values else None
    language = request.values['language']
    neighbors = request.values['neighbors'] if 'neighbors' in request.values else None
    client_id = request.values['client_id']
    user = request.values['user'] if 'user' in request.values else None
    map = int(request.values['map']) if 'map' in request.values else None

    print(f"get_player_info: USERID: {USERID}. user: {user} --", request.values)

    # Current Player
    if user is None:
        return (get_player_info(USERID), 200)
    # Arthur
    elif user == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_1 \
    or user == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_2 \
    or user == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_3:
        return (get_neighbor_info(user, map), 200)
    # Quest
    elif user.startswith("100000"): # Dirty but quick
        return get_quest_map(user)
    # Neighbor
    else:
        return (get_neighbor_info(user, map), 200)

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/sync_error_track.php", methods=['POST'])
def sync_error_track_response():
    spdebug = None

    USERID = request.values['USERID']
    user_key = request.values['user_key']
    if 'spdebug' in request.values:
        spdebug = request.values['spdebug']
    language = request.values['language']
    error = request.values['error']
    current_failed = request.values['current_failed']
    tries = request.values['tries'] if 'tries' in request.values else None
    survival = request.values['survival']
    previous_failed = request.values['previous_failed']
    description = request.values['description']
    user_id = request.values['user_id']

    print(f"sync_error_track: USERID: {USERID}. [Error: {error}] tries: {tries}. --", request.values)
    return ("", 200)

@app.route("/null")
def flash_sync_error_response():
    sp_ref_cat = request.values['sp_ref_cat']

    if sp_ref_cat == "flash_sync_error":
        reason = "reload On Sync Error"
    elif sp_ref_cat == "flash_reload_quest":
        reason = "reload On End Quest"
    elif sp_ref_cat == "flash_reload_attack":
        reason = "reload On End Attack"

    print("flash_sync_error", reason, ". --", request.values)
    return redirect("/play.html")

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/command.php", methods=['POST'])
def command_response():
    spdebug = None

    USERID = request.values['USERID']
    user_key = request.values['user_key']
    if 'spdebug' in request.values:
        spdebug = request.values['spdebug']
    language = request.values['language']
    client_id = request.values['client_id']

    print(f"command: USERID: {USERID}. --", request.values)

    data_str = request.values['data']
    data_hash = data_str[:64]
    assert data_str[64] == ';'
    data_payload = data_str[65:]
    data = json.loads(data_payload)

    command(USERID, data)
    
    return ({"result": "success"}, 200)

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/get_continent_ranking.php")
def get_continent_ranking_response():

    USERID = request.values['USERID']
    worldChange = request.values['worldChange']
    if 'spdebug' in request.values:
        spdebug = request.values['spdebug']
    town_id = request.values['map']
    user_key = request.values['user_key']

    # TODO - stub
    response = {
        "world_id": 0,
        "continent": [
            {"posicion": 0, "nivel": 1, "user_id": 1111}, # villages/AcidCaos
            {"posicion": 1, "nivel": 0},
            {"posicion": 2, "nivel": 0},
            {"posicion": 3, "nivel": 0},
            {"posicion": 4, "nivel": 0},
            {"posicion": 5, "nivel": 0},
            {"posicion": 6, "nivel": 0},
            {"posicion": 7, "nivel": 0}
        ]
    }
    return(response)


########
# MAIN #
########

print (" [+] Running server...")

if __name__ == "__main__":
    # Dev server only — Render uses Gunicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5050"))
    app.run(host=host, port=port, debug=False)
