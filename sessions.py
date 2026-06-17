import json
import os
import copy
import uuid
import random
from flask import session
# from flask_session import SqlAlchemySessionInterface, current_app

from version import version_code
from engine import timestamp_now
from version import migrate_loaded_save
from constants import Constant

from bundle import VILLAGES_DIR, SAVES_DIR
from db import query, execute, create_tables
import json as _json_module

__villages = {}  # ALL static neighbors
'''__villages = {
    "USERID_1": {
        "playerInfo": {...},
        "maps": [{...},{...}]
        "privateState": {...}
    },
    "USERID_2": {...}
}'''

__saves = {}  # ALL saved villages
'''__saves = {
    "USERID_1": {
        "playerInfo": {...},
        "maps": [{...},{...}]
        "privateState": {...}
    },
    "USERID_2": {...}
}'''

__initial_village = json.load(open(os.path.join(VILLAGES_DIR, "initial.json")))


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


# Load saved villages

def load_saved_villages():
    """Load all villages from PostgreSQL into in-memory dicts.
    Also creates tables and migrates static villages from disk on first run.
    """
    global __saves, __villages
    __saves = {}
    __villages = {}

    try:
        create_tables()
        migrate_static_villages_from_disk()
    except Exception as e:
        print(f"[sessions] DB setup failed (no PostgreSQL running?): {e}")
        return  # Can't do anything without DB

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


# New village

def new_village() -> str:
    # Generate USERID
    USERID: str = str(uuid.uuid4())
    assert USERID not in all_userid()
    # Copy init
    village = copy.deepcopy(__initial_village)
    # Custom values
    village["version"] = version_code
    village["playerInfo"]["pid"] = USERID
    village["maps"][0]["timestamp"] = timestamp_now()
    village["privateState"]["dartsRandomSeed"] = abs(int((2**16 - 1) * random.random()))
    # Memory saves
    __saves[USERID] = village
    # Save to PostgreSQL
    data_json = _json_module.dumps(__saves[USERID])
    execute(
        "INSERT INTO player_saves (user_id, save_data) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET save_data = EXCLUDED.save_data",
        [USERID, data_json],
    )
    print("Done.")
    return USERID


def create_village_with_id(user_id: str) -> str:
    """Verilen user_id ile yeni koy olustur. initial.json'dan kopyalar.
    Auth sistemi tarafindan kullanilir — once UUID olusturulur, sonra koy kurulur.

    Returns:
        user_id (same as input, for chaining)
    """
    village = copy.deepcopy(__initial_village)
    village["version"] = version_code
    village["playerInfo"]["pid"] = user_id
    village["maps"][0]["timestamp"] = timestamp_now()
    village["privateState"]["dartsRandomSeed"] = abs(int((2**16 - 1) * random.random()))
    __saves[user_id] = village
    # PostgreSQL'e kaydet
    data_json = _json_module.dumps(village)
    execute(
        "INSERT INTO player_saves (user_id, save_data) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET save_data = EXCLUDED.save_data",
        [user_id, data_json],
    )
    return user_id

# Access functions

def all_saves_userid() -> list:
    "Returns a list of the USERID of every saved village."
    return list(__saves.keys())

def all_userid() -> list:
    "Returns a list of the USERID of every village."
    return list(__villages.keys()) + list(__saves.keys())

def save_info(USERID: str) -> dict:
    save = __saves[USERID]
    default_map = save["playerInfo"]["default_map"]
    empire_name = str(save["playerInfo"]["map_names"][default_map])
    xp = save["maps"][default_map]["xp"]
    level = save["maps"][default_map]["level"]
    return{"userid": USERID, "name": empire_name, "xp": xp, "level": level}

def all_saves_info() -> list:
    saves_info = []
    for userid in __saves:
        saves_info.append(save_info(userid))
    return list(saves_info)

def session(USERID: str) -> dict:
    assert(isinstance(USERID, str))
    return __saves[USERID] if USERID in __saves else None

def neighbor_session(USERID: str) -> dict:
    assert(isinstance(USERID, str))
    if USERID in __saves:
        return __saves[USERID]
    if USERID in __villages:
        return __villages[USERID]

def fb_friends_str(USERID: str) -> list:
    DELETE_ME = [{"uid": "1111", "pic_square":"http://127.0.0.1:5050/img/profile/Paladin_Justiciero.jpg"},
        {"uid": "aa_002", "pic_square":"/1025.png"}]
    friends = []
    # static villages
    for key in __villages:
        vill = __villages[key]
        # Avoid Arthur being loaded as friend.
        if vill["playerInfo"]["pid"] == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_1 \
        or vill["playerInfo"]["pid"] == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_2 \
        or vill["playerInfo"]["pid"] == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_3:
            continue
        frie = {}
        frie["uid"] = vill["playerInfo"]["pid"]
        frie["pic_square"] = vill["playerInfo"]["pic"]
        if not frie["pic_square"]: frie["pic_square"] = "/img/profile/1025.png"
        friends += [frie]
    # other players
    for key in __saves:
        vill = __saves[key]
        if vill["playerInfo"]["pid"] == USERID:
            continue
        frie = {}
        frie["uid"] = vill["playerInfo"]["pid"]
        frie["pic_square"] = vill["playerInfo"]["pic"]
        if not frie["pic_square"]: frie["pic_square"] = "/img/profile/1025.png"
        friends += [frie]
    return friends

def neighbors(USERID: str) -> list:
    neighbors = []
    # static villages
    for key in __villages:
        vill = __villages[key]
        # Avoid Arthur being loaded as multiple neigtbors.
        if vill["playerInfo"]["pid"] == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_1 \
        or vill["playerInfo"]["pid"] == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_2 \
        or vill["playerInfo"]["pid"] == Constant.NEIGHBOUR_ARTHUR_GUINEVERE_3:
            continue
        neigh = vill["playerInfo"]
        neigh["coins"] = vill["maps"][0]["coins"]
        neigh["xp"] = vill["maps"][0]["xp"]
        neigh["level"] = vill["maps"][0]["level"]
        neigh["stone"] = vill["maps"][0]["stone"]
        neigh["wood"] = vill["maps"][0]["wood"]
        neigh["food"] = vill["maps"][0]["food"]
        neigh["stone"] = vill["maps"][0]["stone"]
        neighbors += [neigh]
    # other players
    for key in __saves:
        vill = __saves[key]
        if vill["playerInfo"]["pid"] == USERID:
            continue
        neigh = vill["playerInfo"]
        neigh["coins"] = vill["maps"][0]["coins"]
        neigh["xp"] = vill["maps"][0]["xp"]
        neigh["level"] = vill["maps"][0]["level"]
        neigh["stone"] = vill["maps"][0]["stone"]
        neigh["wood"] = vill["maps"][0]["wood"]
        neigh["food"] = vill["maps"][0]["food"]
        neigh["stone"] = vill["maps"][0]["stone"]
        neighbors += [neigh]
    return neighbors

# Check for valid village
# The reason why this was implemented is to warn the user if a save game from Social Wars was used by accident

def is_valid_village(save: dict):
    if "playerInfo" not in save or "maps" not in save or "privateState" not in save:
        # These are obvious
        return False
    for map in save["maps"]:
        if "oil" in map or "steel" in map:
            return False
        if "stone" not in map or "food" not in map:
            return False
        if "items" not in map:
            return False
        if type(map["items"]) != list:
            return False

    return True

# Persistency

def backup_session(USERID: str):
    # TODO 
    return

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